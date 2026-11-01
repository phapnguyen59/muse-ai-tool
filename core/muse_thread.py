"""Read-only tracking of a Muse thread, with reconnects and no render deadline."""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlparse

import websockets


def thread_id_from_url(url):
    parsed = urlparse(url)
    match = re.fullmatch(r'/thread/([A-Za-z0-9_-]+)/?', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'muse.ai' or not match:
        return ''
    return match[1] if match[1] != 'new' else ''


class PageConnection:
    """Reconnect to the same tab. Never replay a potentially submitted prompt."""
    def __init__(self, websocket_url, is_cancelled):
        self.url = websocket_url
        self.is_cancelled = is_cancelled
        self.ws = None
        self.counter = 0

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def command(self, method, params=None, *, replay=True):
        while True:
            if self.is_cancelled():
                raise asyncio.CancelledError()
            try:
                if self.ws is None:
                    self.ws = await websockets.connect(self.url, max_size=256 * 1024 * 1024)
                self.counter += 1
                request_id = self.counter
                await self.ws.send(json.dumps({'id': request_id, 'method': method, 'params': params or {}}))
                while True:
                    response = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=30))
                    if response.get('id') != request_id:
                        continue
                    if 'error' in response:
                        message = response['error'].get('message', 'error')
                        if any(part in message.lower() for part in ('context was destroyed', 'cannot find context', 'inspected target navigated')):
                            if not replay:
                                raise ConnectionError('Navigation interrupted submission; do not send again')
                            await asyncio.sleep(1)
                            break
                        raise RuntimeError(f"CDP {method}: {message}")
                    if response.get('result', {}).get('exceptionDetails'):
                        raise RuntimeError(f'JavaScript failed during {method}')
                    return response
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException):
                await self.close()
                if not replay:
                    raise ConnectionError('Connection interrupted during submission; do not send again')
                await asyncio.sleep(3)


# A completed response requires actual assistant content, no active processing,
# and a stable response across consecutive snapshots. Idle alone is not completion.
THREAD_SNAPSHOT_JS = r"""(() => {
    const root = document.getElementById('hatch-chat-scroll') || document.querySelector('main')
        || document.querySelector('[role="main"]') || document.body;
    if (!root) return {url: location.href, ready: false, reason: 'no-document-body'};
    root.scrollTop = root.scrollHeight;
    const visible = el => !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
    const assistant = [...root.querySelectorAll(
        '[data-message-author-role="assistant"], [data-role="assistant"], [data-message-role="assistant"], [data-testid="assistant-message"]'
    )];
    const messages = assistant.length ? assistant : [...root.querySelectorAll('[aria-label="Assistant message"]')];
    const text = root.innerText || (root.tagName !== 'BODY' ? root.textContent : '') || '';
    const last = messages.length ? messages[messages.length - 1] : null;
    const marker = text.lastIndexOf('Assistant message:');
    let answer = last ? (last.innerText || '') : marker >= 0 ? text.slice(marker + 18) : '';
    // Muse can render unlabelled chat bubbles. Each job has a dedicated thread;
    // locate its exact submitted prompt before identifying subsequent reply text.
    const expected = typeof window !== 'undefined' ? window.__museExpectedPrompt : '';
    if (!answer && expected) {
        const normalized = text.replace(/\s+/g, ' ');
        const prompt = expected.replace(/\s+/g, ' ');
        const position = normalized.indexOf(prompt);
        if (position >= 0) answer = normalized.slice(position + prompt.length)
            .replace(/(?:Message|Nhắn tin)\s*Muse\s*$/i, '').trim();
    }
    // A render card can belong to an earlier assistant block in this thread.
    const scope = root;
    const videos = [...new Set([...scope.querySelectorAll('video'), ...document.querySelectorAll('video')])].filter(v =>
        !v.closest('.rounded-full, header, nav, [data-testid*="avatar"]'));
    const videoSource = v => v.currentSrc || v.src || v.querySelector('source[src]')?.src || '';
    const playable = v => !!videoSource(v) && v.readyState >= 2 && Number.isFinite(v.duration)
        && v.duration > 0 && v.videoWidth > 0 && v.videoHeight > 0;
    const video = [...videos].reverse().find(playable) || [...videos].reverse().find(videoSource);
    // Some completed results are download cards, with no <video> until played.
    const download = [...scope.querySelectorAll('a[href]')].reverse().find(a =>
        /\.(mp4|webm)(?:[?#]|$)/i.test(a.href) || /^video\//i.test(a.type || ''));
    const src = (video && playable(video) ? videoSource(video) : '') || download?.href || (video ? videoSource(video) : '') || '';
    const stop = [...document.querySelectorAll('button[aria-label]')].some(b =>
        visible(b) && !b.disabled && /^(stop|stop generating|stop response|dừng|dừng tạo|dừng phản hồi)$/i.test(b.getAttribute('aria-label').trim()));
    const pending = [...root.querySelectorAll('[aria-busy="true"], [role="progressbar"], [data-state="streaming"]')].some(visible)
        || [...root.querySelectorAll('[role="status"], [aria-live="polite"]')].some(el => visible(el)
            && (el.innerText || '').length < 200
            && /(?:Generating|Assembling|Rendering|Thinking|Processing|Đang tạo|Đang xử lý)\s*(?:\.{3}|…)/i.test(el.innerText || ''));
    const editor = document.querySelector('textarea:not(:disabled), [contenteditable="true"]');
    const editorEmpty = editor && !(editor.value || editor.textContent || '').trim();
    const sendPresent = [...document.querySelectorAll('button[aria-label], button[type="submit"]')].some(b => visible(b)
        && (/^(send|send message|gửi|gửi tin nhắn)$/i.test(b.getAttribute('aria-label') || '') || b.type === 'submit'));
    const explicitComplete = !!last && (last.matches('[data-state="complete"], [data-state="completed"], [data-state="finished"]')
        || [...last.querySelectorAll('button[aria-label]')].some(b => /copy (message|response)|regenerate|sao chép (tin nhắn|phản hồi)/i.test(b.getAttribute('aria-label') || '')));
    const error = [...root.querySelectorAll('[role="alert"]')].filter(visible).map(e => e.innerText).filter(Boolean).join('\n');
    const pageReady = !!text.trim() || videos.length > 0 || !!editor;
    return {url: location.href, ready: pageReady, busy: stop || pending,
        documentState: document.readyState, title: document.title,
        frameCount: document.querySelectorAll('iframe').length,
        bodyChildren: document.body?.children?.length || 0,
        reason: pageReady ? '' : 'empty-page',
        rootTag: root.tagName, online: navigator.onLine, videoCount: videos.length,
        messageCount: messages.length, bodyLength: text.length,
        hasAnswer: !!answer.trim() || !!src, answer, src, error,
        playable: (!!video && playable(video)) || !!download,
        responseComplete: !!answer.trim() && !stop && !pending && (explicitComplete || (editorEmpty && sendPresent)),
        videoSignature: JSON.stringify([src, video?.duration || 0, video?.videoWidth || 0, video?.videoHeight || 0]),
        signature: JSON.stringify([answer, src, error, video ? video.readyState : 0])};
})()"""


async def read_thread_snapshot(send_cmd, prompt):
    """Read the page, and its child frames when the top document has no result."""
    expression = '(window.__museExpectedPrompt = ' + json.dumps(prompt) + ', ' + THREAD_SNAPSHOT_JS + ')'

    async def evaluate(context_id=None):
        params = {'expression': expression, 'returnByValue': True}
        if context_id is not None:
            params['contextId'] = context_id
        response = await send_cmd('Runtime.evaluate', params)
        value = response.get('result', {}).get('result', {}).get('value')
        return value if isinstance(value, dict) else {'ready': False, 'reason': 'invalid-snapshot'}

    top = await evaluate()
    if top.get('src') or not top.get('frameCount'):
        return top
    tree = await send_cmd('Page.getFrameTree')
    pending = list(tree.get('result', {}).get('frameTree', {}).get('childFrames', []))
    best = top
    while pending:
        node = pending.pop()
        pending.extend(node.get('childFrames', []))
        frame = node.get('frame', {})
        if not frame.get('id') or not frame.get('url', '').startswith(('http://', 'https://', 'about:')):
            continue
        try:
            world = await send_cmd('Page.createIsolatedWorld', {
                'frameId': frame['id'], 'worldName': 'muse-thread-monitor',
            })
            context = world.get('result', {}).get('executionContextId')
            if context is None:
                continue
            snapshot = await evaluate(context)
        except RuntimeError:
            continue  # A child frame can be replaced while the page loads.
        if snapshot.get('src') or (snapshot.get('hasAnswer') and not best.get('hasAnswer')):
            snapshot['contentFrameUrl'] = snapshot.get('url', '')
            snapshot['url'] = top.get('url', '')  # Identity remains the parent thread.
            best = snapshot
            if snapshot.get('src'):
                break
    return best


class ResponseTracker:
    def __init__(self):
        self.signature = None
        self.stable = 0

    def observe(self, snapshot):
        if not snapshot.get('ready') or (snapshot.get('busy') and not snapshot.get('playable')):
            self.signature, self.stable = None, 0
            return None
        if not (snapshot.get('hasAnswer') or snapshot.get('error')):
            self.signature, self.stable = None, 0
            return None
        signature = snapshot.get('videoSignature') if snapshot.get('src') else snapshot.get('signature')
        if signature is None:
            signature = snapshot.get('signature')
        self.stable = self.stable + 1 if signature == self.signature else 1
        self.signature = signature
        if self.stable < 3:
            return None
        if snapshot.get('src'):
            return snapshot['src']
        if snapshot.get('error'):
            raise RuntimeError(snapshot['error'])
        if snapshot.get('responseComplete'):
            raise RuntimeError('Muse đã trả lời xong nhưng không có video')
        # Stable prose is not a render completion signal. Muse may append the
        # video later, with no progress indicator while the render is queued.
        return None
