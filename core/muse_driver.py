"""

Muse AI Real CDP Driver — Điều khiển Google Chrome headless để tạo video thật trên Muse.ai

- Quản lý phiên Chrome với Chrome DevTools Protocol (CDP) qua WebSocket.

- Nạp Cookie thật của tài khoản (hatch_sess, hatch_vml, datr...).

- Gửi Prompt vào khung chat của Muse.ai.

- Bắt sự kiện render video thời gian thực, trích xuất blob MP4 và tải về thư mục data/media.

"""

from __future__ import annotations



import asyncio

import base64

import json

import logging

import os

import socket

import shutil

import subprocess

import threading

import time

import urllib.request

from pathlib import Path

from typing import Any, Callable, Dict, List, Optional



import sys

import websockets

from core.activity_log import record



log = logging.getLogger("muse_driver")





def find_chrome_path() -> Optional[str]:

    """Tự động tìm đường dẫn Google Chrome hoặc Edge trên máy tính Windows."""

    env_path = os.environ.get("CHROME_PATH")

    if env_path and os.path.isfile(env_path):

        return env_path



    try:

        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):

            try:

                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:

                    val, _ = winreg.QueryValueEx(key, "")

                    if val and os.path.isfile(val):

                        return val

            except OSError:

                pass

    except Exception:

        pass



    candidates = [

        r"C:\Program Files\Google\Chrome\Application\chrome.exe",

        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",

        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),

        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),

        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),

        shutil.which("chrome"),

        shutil.which("google-chrome"),

        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",

        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",

        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),

        shutil.which("msedge"),

    ]

    for c in candidates:

        if c and os.path.isfile(c):

            return c

    return None





def find_bin_tool(name: str) -> Optional[str]:

    """Tìm binary tool (ffmpeg, ffprobe) trong PATH hoặc thư mục bin đi kèm."""

    found = shutil.which(name)

    if found:

        return found

    app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent

    check_dirs = [app_dir / "bin", app_dir]

    if getattr(sys, "_MEIPASS", None):

        check_dirs.extend([Path(sys._MEIPASS) / "bin", Path(sys._MEIPASS)])

    for b_dir in check_dirs:

        exe_file = b_dir / f"{name}.exe"

        if exe_file.is_file():

            return str(exe_file)

        raw_file = b_dir / name

        if raw_file.is_file():

            return str(raw_file)

    return None





CHROME_PATH = find_chrome_path() or r"C:\Program Files\Google\Chrome\Application\chrome.exe"

from core.paths import DATA_DIR, MEDIA_DIR, PROFILES_DIR



# Stable attributes from the supplied Muse compose button; CSS classes vary.

COMPOSE_SELECTOR = ('button[data-testid="hatch-chat-compose"], '

                    'button[aria-label="\u0110o\u1ea1n chat ph\u1ee5 m\u1edbi"], '

                    'button[title="\u0110o\u1ea1n chat ph\u1ee5 m\u1edbi"]')



EDITOR_JS = """(() => {

    const selectors = [

        'textarea[data-hatch-composer-prehydration-input="true"]',

        'textarea[aria-label="Nh\\u1eafn tin"]',

        'textarea[placeholder="Nh\\u1eafn tin"]',

        'textarea:not(:disabled)', '[contenteditable="true"]'

    ];

    for (const selector of selectors) {

        const editor = [...document.querySelectorAll(selector)].find(el =>

            el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden'

            && !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true');

        if (editor) return editor;

    }

    return null;

})()"""





async def enter_prompt(send_cmd, is_cancelled, prompt, job_id=''):

    """Type through Chrome's input path and verify after possible hydration."""

    for attempt in range(3):

        if is_cancelled():

            raise asyncio.CancelledError()

        focus = """(() => {

            const editor = EDITOR_EXPRESSION;

            if (!editor) return false;

            editor.focus();

            if (editor instanceof HTMLTextAreaElement) editor.select();

            else {

                const range = document.createRange(); range.selectNodeContents(editor);

                const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);

            }

            return true;

        })()""".replace('EDITOR_EXPRESSION', EDITOR_JS)

        result = await send_cmd('Runtime.evaluate', {'expression': focus, 'returnByValue': True})

        if not result.get('result', {}).get('result', {}).get('value'):

            await asyncio.sleep(1)

            continue

        await send_cmd('Input.insertText', {'text': prompt}, replay=False)

        await asyncio.sleep(1)

        verify = """(() => {

            const editor = EDITOR_EXPRESSION;

            return !!editor && (editor instanceof HTMLTextAreaElement ? editor.value : editor.textContent) === PROMPT_VALUE;

        })()""".replace('EDITOR_EXPRESSION', EDITOR_JS).replace('PROMPT_VALUE', json.dumps(prompt))

        result = await send_cmd('Runtime.evaluate', {'expression': verify, 'returnByValue': True})

        if result.get('result', {}).get('result', {}).get('value') is True:

            record('Prompt đã nhập và kiểm tra giữ nguyên trên ô Nhắn tin', job_id)

            return

        record('Ô nhập thay đổi khi tải giao diện; nhập lại trước khi gửi', job_id, 'warning')

    raise RuntimeError('Muse composer did not retain the prompt; prompt was not sent')





async def open_new_thread(send_cmd, is_cancelled, job_id=''):

    """Click Muse's compose button; navigate directly only when it is absent."""

    click_js = """(() => {

        const buttons = [...document.querySelectorAll(COMPOSE_SELECTOR_VALUE)]

            .filter(b => b.getClientRects().length && getComputedStyle(b).visibility !== 'hidden');

        if (!buttons.length) return 'missing';

        if (buttons.length !== 1) return 'ambiguous';

        const button = buttons[0];

        if (button.disabled || button.getAttribute('aria-disabled') === 'true') return 'disabled';

        button.click();

        return 'clicked';

    })()"""

    record('Đang tìm nút dấu cộng mở chat phụ', job_id)

    click_js = click_js.replace("COMPOSE_SELECTOR_VALUE", json.dumps(COMPOSE_SELECTOR))

    state = 'missing'

    for _ in range(10):

        if is_cancelled():

            raise asyncio.CancelledError()

        result = await send_cmd('Runtime.evaluate', {'expression': click_js, 'returnByValue': True})

        state = result.get('result', {}).get('result', {}).get('value')

        if state == 'clicked':

            record('Đã bấm nút dấu cộng; chờ trang chat mới', job_id)

            break

        if state not in ('missing', 'disabled'):

            raise RuntimeError('Cannot uniquely identify the Muse new-thread button')

        await asyncio.sleep(0.5)

    if state == 'missing':

        log.info('Muse compose button not found; opening /thread/new directly')

        record('Không tìm thấy nút dấu cộng; mở /thread/new dự phòng', job_id, 'warning')

        await send_cmd('Page.navigate', {'url': 'https://muse.ai/thread/new'})

    elif state != 'clicked':

        raise RuntimeError('Muse new-thread button is disabled')



    last_page = {}

    for attempt in range(120):

        if is_cancelled():

            raise asyncio.CancelledError()

        result = await send_cmd('Runtime.evaluate', {

            'expression': "location.origin === 'https://muse.ai' && /^\\/thread\\/new\\/?$/.test(location.pathname) && !!(" + EDITOR_JS + ")",

            'returnByValue': True,

        })

        if result.get('result', {}).get('result', {}).get('value') is True:

            record('Trang /thread/new và ô nhập prompt đã sẵn sàng', job_id)

            return

        if attempt % 10 == 0:

            result = await send_cmd('Runtime.evaluate', {

                'expression': "({origin:location.origin,path:location.pathname,ready:document.readyState,textarea:!!document.querySelector('textarea'),editable:!!document.querySelector('[contenteditable=\"true\"]')})",

                'returnByValue': True,

            })

            last_page = result.get('result', {}).get('result', {}).get('value') or {}

            record('Đang chờ giao diện chat mới: ' + json.dumps(last_page, ensure_ascii=False), job_id)

            if isinstance(last_page, dict) and any(x in last_page.get('path', '') for x in ('/login', '/auth')):

                raise RuntimeError('Muse login expired; update cookies')

        await asyncio.sleep(1)

    result = await send_cmd('Runtime.evaluate', {

        'expression': "JSON.stringify({origin:location.origin,path:location.pathname,ready:document.readyState,textarea:!!document.querySelector('textarea'),compose:!!document.querySelector(COMPOSE_SELECTOR_VALUE)})".replace("COMPOSE_SELECTOR_VALUE", json.dumps(COMPOSE_SELECTOR)),

        'returnByValue': True,

    })

    diagnostic = result.get('result', {}).get('result', {}).get('value', 'unknown page')

    record('Chat mới chưa sẵn sàng: ' + str(diagnostic), job_id, 'error')

    raise RuntimeError('Muse new-thread page did not become ready; prompt was not sent; page=' + str(diagnostic))





async def open_existing_thread(send_cmd, is_cancelled, thread_id, job_id=''):

    """Keep a usable tab; otherwise bootstrap Muse before opening its history link."""

    from core.muse_thread import thread_id_from_url

    target = f'https://muse.ai/thread/{thread_id}'

    if thread_id_from_url(target) != thread_id:

        raise RuntimeError('Invalid saved thread ID; prompt was not sent')



    async def probe():

        if is_cancelled():

            raise asyncio.CancelledError()

        response = await send_cmd('Runtime.evaluate', {'expression': """(() => ({

            url:location.href, state:document.readyState, title:document.title,

            textLength:(document.body?.innerText || '').trim().length,

            editor:!!(EDITOR), video:!!document.querySelector('video'),

            frames:document.querySelectorAll('iframe').length,

            children:document.body?.children.length || 0

        }))()""".replace('EDITOR', EDITOR_JS), 'returnByValue': True})

        page = response.get('result', {}).get('result', {}).get('value') or {}

        if '/login' in page.get('url', '') or '/auth' in page.get('url', ''):

            raise RuntimeError('Muse login expired; update cookies')

        return page



    def usable(page):

        return page.get('state') != 'loading' and bool(page.get('editor') or page.get('video') or page.get('frames') or page.get('textLength', 0) > 0)



    await send_cmd('Page.bringToFront')

    page = await probe()

    if thread_id_from_url(page.get('url', '')) == thread_id and usable(page):

        record('Giữ nguyên tab thread đang có nội dung để quét kết quả', job_id)

        return

    record('Tab thread chưa có nội dung; mở Muse và tìm lại thread trong lịch sử', job_id, 'warning')

    await send_cmd('Page.navigate', {'url': 'https://muse.ai/'})

    clicked = False

    for _ in range(24):

        page = await probe()

        if usable(page):

            response = await send_cmd('Runtime.evaluate', {'expression': r"""(() => {

                const link = [...document.querySelectorAll('a[href]')].find(a => {

                    try { const url = new URL(a.href, location.href); return url.origin === 'https://muse.ai' && url.pathname.replace(/\/$/, '') === PATH; }

                    catch (_) { return false; }

                });

                if (!link) return false;

                link.click(); return true;

            })()""".replace('PATH', json.dumps('/thread/' + thread_id)), 'returnByValue': True}, replay=False)

            if response.get('result', {}).get('result', {}).get('value') is True:

                clicked = True

                break

        await asyncio.sleep(1)

    if not clicked:

        record('Không thấy thread trong lịch sử; mở đúng URL thread đã lưu', job_id)

        await send_cmd('Page.navigate', {'url': target})

    for _ in range(30):

        page = await probe()

        if thread_id_from_url(page.get('url', '')) == thread_id and usable(page):

            record('Thread cũ đã có nội dung; bắt đầu quét video và phản hồi', job_id)

            return

        await asyncio.sleep(1)

    record('Không tải được nội dung thread: ' + json.dumps(page, ensure_ascii=False), job_id, 'error')

    raise RuntimeError('Không đọc được nội dung thread Muse (trang trống hoặc sai thread). Đây là lỗi tải trang, chưa thể xác định có video hay không.')





async def prepare_new_thread(send_cmd, is_cancelled, job_id=''):

    """The compose button must be usable before a chat editor even exists."""

    record('Đang mở trang Muse để tìm nút tạo chat phụ', job_id)

    await send_cmd('Page.navigate', {'url': 'https://muse.ai/'})

    for _ in range(24):

        if is_cancelled():

            raise asyncio.CancelledError()

        result = await send_cmd('Runtime.evaluate', {

            'expression': "({origin:location.origin,path:location.pathname,ready:document.readyState,compose:!!document.querySelector(COMPOSE_SELECTOR_VALUE)})".replace("COMPOSE_SELECTOR_VALUE", json.dumps(COMPOSE_SELECTOR)),

            'returnByValue': True,

        })

        page = result.get('result', {}).get('result', {}).get('value') or {}

        if '/login' in page.get('path', '') or '/auth' in page.get('path', ''):

            raise RuntimeError('Muse login expired; update cookies')

        if page.get('origin') == 'https://muse.ai' and page.get('ready') != 'loading' and page.get('compose'):

            break

        await asyncio.sleep(1)

    # No home-page textarea requirement. open_new_thread owns the missing-button

    # fallback and verifies the editor only AFTER reaching /thread/new.

    await open_new_thread(send_cmd, is_cancelled, job_id)





def get_free_port() -> int:

    """Tìm một cổng mạng còn trống để mở Chrome CDP."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.bind(("", 0))

        return s.getsockname()[1]





def format_muse_video_prompt(user_prompt: str, duration: int = 15, ratio: str = "9:16", has_ref: bool = False) -> str:

    """Định dạng câu lệnh prompt chuẩn nhất cho mô hình sinh video của Muse (Hatch VM)."""

    p = user_prompt.strip()

    if ratio in ("9:16", "portrait", "dọc", "vertical"):

        if has_ref:

            return f"Based on the uploaded reference image attachment as the first frame: Create a dynamic image-to-video in strict 9:16 vertical full-screen mobile aspect ratio (9:16 vertical portrait video, 720x1280, duration strictly {duration} seconds): {p}"

        return f"Brand new text-to-video creation (pure text generation from scratch): Generate a strict 9:16 vertical full-screen mobile video (9:16 vertical portrait video, 720x1280, duration strictly {duration} seconds): {p}"

    elif ratio in ("16:9", "landscape", "ngang"):

        if has_ref:

            return f"Based on the uploaded reference image attachment as the first frame: Create a 16:9 widescreen landscape image-to-video (16:9 widescreen landscape video, duration strictly {duration} seconds): {p}"

        return f"Brand new text-to-video creation (pure text generation from scratch): Generate a 16:9 widescreen landscape video (16:9 widescreen landscape video, duration strictly {duration} seconds): {p}"

    else:

        return f"Brand new text-to-video creation: Generate a 1:1 square video (duration strictly {duration} seconds): {p}"





class MuseCDPSession:

    def __init__(self, account_id: str, cookie_header: str):

        self.account_id = account_id

        self.cookie_header = cookie_header

        self.port: Optional[int] = None

        self.proc: Optional[subprocess.Popen] = None

        self._browser_lock = threading.Lock()

        self.profile_dir = (PROFILES_DIR / account_id).resolve()

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)



    def _parse_cookies(self) -> List[Dict[str, str]]:

        cookies = []

        for part in self.cookie_header.split(";"):

            part = part.strip()

            if "=" in part:

                k, v = part.split("=", 1)

                k = k.strip()

                v = v.strip()

                if k:

                    cookies.append({

                        "name": k,

                        "value": v,

                        "url": "https://muse.ai/",

                    })

        return cookies



    def start_browser(self):

        with self._browser_lock:

            self._start_browser()



    def _start_browser(self):

        if self.proc and self.proc.poll() is None:

            return

        self.port = get_free_port()

        chrome_exe = find_chrome_path() or CHROME_PATH

        if not os.path.isfile(chrome_exe):

            raise RuntimeError(

                "Không tìm thấy Google Chrome hoặc Edge trên máy tính của bạn.\n"

                "Vui lòng cài đặt Google Chrome tại https://www.google.com/chrome/ để Muse AI Tool có thể hoạt động."

            )

        cmd = [

            chrome_exe,

            f"--remote-debugging-port={self.port}",

            "--headless=new",

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-gpu",

            "--disable-background-networking",

            "--disable-background-timer-throttling",

            "--disable-renderer-backgrounding",

            "--disable-backgrounding-occluded-windows",

            "--disable-sync",

            f"--user-data-dir={self.profile_dir}",

        ]

        self.proc = subprocess.Popen(cmd)

        # Chờ Chrome sẵn sàng lắng nghe CDP

        for _ in range(15):

            time.sleep(0.3)

            try:

                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as r:

                    if r.status == 200:

                        break

            except Exception:

                pass



    def stop_browser(self):

        if self.proc:

            try:

                self.proc.terminate()

                self.proc.wait(timeout=3)

            except Exception:

                try:

                    self.proc.kill()

                except Exception:

                    pass

            self.proc = None



    async def generate_video(

        self,

        job_id: str,

        user_prompt: str,

        duration: int,

        ratio: str,

        resolved_refs: List[Dict[str, Any]],

        on_progress: Callable[[int], None],

        is_cancelled: Callable[[], bool],

    ) -> Dict[str, str]:

        """Quy trình tạo video thực tế qua Chrome DevTools Protocol."""

        from core.queue_manager import queue_manager

        from core.muse_thread import PageConnection, ResponseTracker, read_thread_snapshot, thread_id_from_url



        job = queue_manager.get_job(job_id)

        if job is None:

            raise RuntimeError("Job not found")

        await asyncio.to_thread(self.start_browser)

        record('Trình duyệt sẵn sàng, đang kết nối tab Muse', job_id)

        prompt_formatted = format_muse_video_prompt(user_prompt, duration, ratio, bool(resolved_refs))

        on_progress(5)



        def get_tab():

            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=5) as response:

                tabs = json.loads(response.read().decode())

            existing = next((tab for tab in tabs if job.tab_id and tab.get('id') == job.tab_id), None)

            if existing:

                return existing

            if job.submitted and not job.thread_id:

                raise RuntimeError("Submitted tab is unavailable and thread ID is unknown; refusing to resubmit")

            request = urllib.request.Request(f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT")

            with urllib.request.urlopen(request, timeout=5) as response:

                return json.loads(response.read().decode())



        tab = await asyncio.to_thread(get_tab)

        job.tab_id = tab['id']

        queue_manager.save()

        connection = PageConnection(tab['webSocketDebuggerUrl'], is_cancelled)

        send_cmd = connection.command



        async def evaluate(expression):

            result = await send_cmd('Runtime.evaluate', {'expression': expression, 'returnByValue': True})

            return result.get('result', {}).get('result', {}).get('value')



        try:

            await send_cmd('Network.enable')

            await send_cmd('Network.setCookies', {'cookies': self._parse_cookies()})

            if job.thread_id:

                record('Tiếp tục theo dõi thread cũ, không gửi lại prompt', job_id)

                await open_existing_thread(send_cmd, is_cancelled, job.thread_id, job_id)

            elif not job.submitted:

                await prepare_new_thread(send_cmd, is_cancelled, job_id)

                record('Đã mở chat mới, đang nhập prompt', job_id)

                on_progress(20)

                await enter_prompt(send_cmd, is_cancelled, prompt_formatted, job_id)

                if resolved_refs:

                    from core.ref_library import ref_library

                    from core.muse_attachments import attach_reference_images

                    paths = [ref_library.get_image_file_path(ref['tag']) for ref in resolved_refs]

                    if any(path is None for path in paths):

                        raise RuntimeError('Reference image was deleted; prompt was not submitted')

                    await attach_reference_images(send_cmd, is_cancelled, paths, EDITOR_JS, job_id)

                    # Attachment hydration can replace the composer; recheck its text.

                    await enter_prompt(send_cmd, is_cancelled, prompt_formatted, job_id)

                # Persist before clicking: a lost acknowledgement must not send twice.

                job.submitted = True

                record('Đang gửi prompt tới Muse', job_id)

                queue_manager.save()

                click_js = """(() => {

                    const ta = EDITOR_EXPRESSION;

                    const scope = ta?.closest('form') || ta?.closest('div[class*="rounded"]') || ta?.parentElement?.parentElement;

                    const buttons = [...(scope || document).querySelectorAll('button')];

                    const button = buttons.find(b => /^(send|send message|gửi|gửi tin nhắn)$/i.test(b.getAttribute('aria-label') || ''))

                        || scope?.querySelector('button[type="submit"]');

                    if (!button || button.disabled) return false;

                    button.click();

                    return true;

                })()""".replace("EDITOR_EXPRESSION", EDITOR_JS)

                try:

                    result = await send_cmd('Runtime.evaluate', {'expression': click_js, 'returnByValue': True}, replay=False)

                except ConnectionError:

                    record('Mất xác nhận gửi; tiếp tục theo dõi, không gửi trùng', job_id, 'warning')

                    # Continue reading this tab; never click again after an uncertain send.

                    pass

                else:

                    if not result.get('result', {}).get('result', {}).get('value'):

                        job.submitted = False

                        queue_manager.save()

                        raise RuntimeError('Muse send button was not available; prompt was not submitted')



            on_progress(35)

            tracker = ResponseTracker()

            record('Đang chờ Muse tạo video', job_id)

            last_wait_log = time.monotonic()

            last_refresh = time.monotonic()

            while True:

                if is_cancelled():

                    raise asyncio.CancelledError()

                snapshot = await read_thread_snapshot(send_cmd, prompt_formatted)

                if time.monotonic() - last_wait_log >= 60:

                    record('Theo dõi thread: ' + json.dumps({

                        'busy': snapshot.get('busy'), 'video': bool(snapshot.get('src')),

                        'playable': snapshot.get('playable'), 'answer': snapshot.get('hasAnswer'),

                        'complete': snapshot.get('responseComplete'),

                        'ready': snapshot.get('ready'), 'root': snapshot.get('rootTag'),

                        'online': snapshot.get('online'), 'videos': snapshot.get('videoCount'),

                        'messages': snapshot.get('messageCount'), 'bodyLength': snapshot.get('bodyLength'),

                        'documentState': snapshot.get('documentState'), 'title': snapshot.get('title'),

                        'frames': snapshot.get('frameCount'), 'bodyChildren': snapshot.get('bodyChildren'),

                        'reason': snapshot.get('reason'),

                    }), job_id)

                    last_wait_log = time.monotonic()

                url = snapshot.get('url', '')

                if 'login' in url or '/auth' in url:

                    raise RuntimeError('Muse login expired while tracking the thread')

                thread_id = thread_id_from_url(url)

                if thread_id:

                    if job.thread_id and job.thread_id != thread_id:

                        raise RuntimeError('Muse switched to another thread; refusing to collect its video')

                    if not job.thread_id:

                        job.thread_id = thread_id

                        queue_manager.save()

                if job.thread_id and thread_id == job.thread_id:

                    new_video_src = tracker.observe(snapshot)

                    if new_video_src:

                        record('Đã tìm thấy video ổn định trong thread', job_id)

                        break

                if job.thread_id and not snapshot.get('src') and not snapshot.get('busy') and time.monotonic() - last_refresh >= 120:

                    record('Làm mới thread cũ để đồng bộ kết quả; không gửi lại prompt', job_id)

                    await open_existing_thread(send_cmd, is_cancelled, job.thread_id, job_id)

                    tracker = ResponseTracker()

                    last_refresh = time.monotonic()

                await asyncio.sleep(3)



            on_progress(90)

            record('Đang tải video về máy', job_id)



            # 6. Tải dữ liệu video (blob hoặc URL) về máy tính

            vid_filename = f"{job_id}.mp4"

            thumb_filename = f"{job_id}_thumb.jpg"

            target_vid_path = MEDIA_DIR / vid_filename

            target_thumb_path = MEDIA_DIR / thumb_filename



            # Dùng fetch trong trình duyệt để chuyển video src thành base64

            fetch_blob_js = f"""(async function(){{

                try {{

                    var resp = await fetch({json.dumps(new_video_src)});

                    var blob = await resp.blob();

                    return new Promise((resolve, reject) => {{

                        var reader = new FileReader();

                        reader.onloadend = () => resolve(reader.result);

                        reader.onerror = reject;

                        reader.readAsDataURL(blob);

                    }});

                }} catch(e) {{

                    return '';

                }}

            }})()"""

            res_blob = await send_cmd("Runtime.evaluate", {

                "expression": fetch_blob_js,

                "awaitPromise": True,

                "returnByValue": True,

            })

            data_url = res_blob.get("result", {}).get("result", {}).get("value", "")



            if data_url and "base64," in data_url:

                b64_data = data_url.split("base64,", 1)[1]

                target_vid_path.write_bytes(base64.b64decode(b64_data))

            else:

                # Nếu không lấy được bằng blob fetch, tải qua urllib nếu là http URL

                if new_video_src.startswith("http"):

                    await asyncio.to_thread(urllib.request.urlretrieve, new_video_src, str(target_vid_path))

                else:

                    raise RuntimeError("Không thể tải luồng blob video MP4 từ Muse.ai")



            # A downloaded HTML error page or a synthetic header is not a video.

            probe = find_bin_tool('ffprobe')

            record('Đang kiểm tra file video bằng ffprobe', job_id)

            if not probe:

                raise RuntimeError('ffprobe is required to validate the downloaded video')

            result = await asyncio.to_thread(

                subprocess.run,

                [probe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',

                 'stream=codec_name,width,height:format=duration', '-of', 'json', str(target_vid_path)],

                capture_output=True, text=True, timeout=60,

            )

            metadata = json.loads(result.stdout or '{}') if result.returncode == 0 else {}

            streams = metadata.get('streams', [])

            if not streams or not streams[0].get('width') or float(metadata.get('format', {}).get('duration', 0)) <= 0:

                target_vid_path.unlink(missing_ok=True)

                raise RuntimeError('Muse did not return a valid video file')



            # Trích xuất thumbnail từ Muse (ưu tiên poster/img của Muse, fallback canvas)

            snap_thumb_js = f"""(async function(){{

                var v = [...document.querySelectorAll('video')].find(el => (el.src || el.currentSrc) === {json.dumps(new_video_src)});

                if (!v) return '';



                // 1. Poster chính thức do Muse gắn trên thẻ video

                var posterUrl = v.poster || v.getAttribute('poster');

                if (posterUrl && posterUrl.length > 5) {{

                    try {{

                        var r = await fetch(posterUrl);

                        var blob = await r.blob();

                        return new Promise((resolve) => {{

                            var reader = new FileReader();

                            reader.onloadend = () => resolve(reader.result);

                            reader.readAsDataURL(blob);

                        }});

                    }} catch(e) {{}}

                }}



                // 2. Thẻ img ảnh bìa nằm cùng card/bubble video của Muse

                var card = v.closest('div.relative, article, section, [class*="bubble"]') || v.parentElement;

                if (card) {{

                    var img = card.querySelector('img');

                    if (img && img.src && !img.src.includes('avatar') && !img.src.includes('profile')) {{

                        try {{

                            var r = await fetch(img.src);

                            var blob = await r.blob();

                            return new Promise((resolve) => {{

                                var reader = new FileReader();

                                reader.onloadend = () => resolve(reader.result);

                                reader.readAsDataURL(blob);

                            }});

                        }} catch(e) {{}}

                    }}

                }}



                // 3. Chụp trực tiếp frame từ thẻ video của Muse bằng HTML5 Canvas

                try {{

                    var canvas = document.createElement('canvas');

                    canvas.width = v.videoWidth || 720;

                    canvas.height = v.videoHeight || 1280;

                    var ctx = canvas.getContext('2d');

                    ctx.drawImage(v, 0, 0, canvas.width, canvas.height);

                    return canvas.toDataURL('image/jpeg', 0.85);

                }} catch(e) {{

                    return '';

                }}

            }})()"""

            record('Đang lấy ảnh bìa cho video', job_id)

            res_snap = await send_cmd("Runtime.evaluate", {

                "expression": snap_thumb_js,

                "awaitPromise": True,

                "returnByValue": True,

            })

            thumb_data_url = res_snap.get("result", {}).get("result", {}).get("value", "")



            if thumb_data_url and "base64," in thumb_data_url:

                b64_thumb = thumb_data_url.split("base64,", 1)[1]

                target_thumb_path.write_bytes(base64.b64decode(b64_thumb))

            else:

                ffmpeg = find_bin_tool('ffmpeg')

                if not ffmpeg:

                    raise RuntimeError('ffmpeg is required to extract a real video thumbnail')

                result = await asyncio.to_thread(

                    subprocess.run,

                    [ffmpeg, '-y', '-v', 'error', '-i', str(target_vid_path),

                     '-frames:v', '1', str(target_thumb_path)],

                    capture_output=True, timeout=60,

                )

                if result.returncode or not target_thumb_path.exists():

                    raise RuntimeError('Could not extract a thumbnail from the Muse video')



            on_progress(100)



            return {

                "video_url": f"/api/media/{vid_filename}",

                "thumbnail_url": f"/api/media/{thumb_filename}",

                "filename": vid_filename,

            }

        finally:

            await connection.close()





_sessions: Dict[str, MuseCDPSession] = {}





def get_muse_session(account_id: str, cookie_header: str) -> MuseCDPSession:

    if account_id not in _sessions:

        _sessions[account_id] = MuseCDPSession(account_id, cookie_header)

    else:

        _sessions[account_id].cookie_header = cookie_header

    return _sessions[account_id]

