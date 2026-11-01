"""Attach local reference images through Muse's real file input over CDP."""
import asyncio
import json
from pathlib import Path

from core.activity_log import record


async def attach_reference_images(send_cmd, is_cancelled, paths, editor_js, job_id=''):
    if not paths:
        return
    files = list(dict.fromkeys(str(Path(path).resolve()) for path in paths))
    for path in files:
        if not Path(path).is_file():
            raise RuntimeError('Reference image is missing; prompt was not submitted')
    if len(files) > 1:
        for path in files:
            await attach_reference_images(send_cmd, is_cancelled, [path], editor_js, job_id)
        return

    async def evaluate(expression, by_value=True):
        response = await send_cmd('Runtime.evaluate', {'expression': expression, 'returnByValue': by_value})
        return response.get('result', {}).get('result', {})

    if is_cancelled():
        raise asyncio.CancelledError()
    record(f'Đang đính kèm {len(files)} ảnh tham chiếu lên Muse', job_id)
    # Snapshot before choosing files, so existing page artwork cannot count as
    # evidence that Muse accepted an attachment.
    setup_js = r"""(() => {
        const editor = EDITOR;
        if (!editor) return 'no-editor';
        const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
        let scope = editor.closest('form, [data-testid="hatch-chat-composer"]') || editor.parentElement;
        for (let i = 0; i < 4 && scope.parentElement && !scope.querySelector('input[type="file"]'); i++) {
            if (scope.parentElement === document.body) break;
            scope = scope.parentElement;
        }
        const acceptsImages = input => !input.disabled && (!input.accept || input.accept === '*/*' || /image|\.png|\.jpg|\.jpeg|\.webp/i.test(input.accept));
        let inputs = [...scope.querySelectorAll('input[type="file"]')].filter(acceptsImages);
        if (inputs.length > 1) inputs = inputs.filter(input => /image/i.test(input.accept));
        if (inputs.length > 1) return 'ambiguous-input';
        if (!inputs.length) {
            const buttons = [...scope.querySelectorAll('button')].filter(b => visible(b) && !b.disabled
                && /^(attach( files?| images?)?|upload( files?| images?)?|add (files?|images?|photos?)|đính kèm( tệp| ảnh)?|tải (tệp|ảnh) lên)$/i.test(
                    (b.getAttribute('aria-label') || b.title || b.textContent || '').trim()));
            if (buttons.length !== 1) return 'missing-input';
            buttons[0].click();
            return 'opened-attachment-menu';
        }
        const input = inputs[0];
        window.__museReferenceUpload = {input, scope,
            before: [...scope.querySelectorAll('img')].map(img => img.currentSrc || img.src),
            oldAlerts: [...document.querySelectorAll('[role="alert"]')].map(el => el.innerText)};
        return 'ready';
    })()""".replace('EDITOR', editor_js)
    for _ in range(10):
        if is_cancelled():
            raise asyncio.CancelledError()
        state = (await evaluate(setup_js)).get('value')
        if state == 'ready':
            break
        if state != 'opened-attachment-menu':
            raise RuntimeError(f'Cannot locate Muse image attachment input ({state}); prompt was not submitted')
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError('Muse attachment input did not become available; prompt was not submitted')

    node = await evaluate('window.__museReferenceUpload.input', by_value=False)
    if not node.get('objectId'):
        raise RuntimeError('Muse attachment input disappeared; prompt was not submitted')
    await send_cmd('DOM.enable')
    await send_cmd('DOM.getDocument', {'depth': 0})
    response = await send_cmd('DOM.requestNode', {'objectId': node['objectId']})
    node_id = response.get('result', {}).get('nodeId')
    if not node_id:
        raise RuntimeError('Cannot access Muse attachment input; prompt was not submitted')
    try:
        await send_cmd('DOM.setFileInputFiles', {'nodeId': node_id, 'files': files}, replay=False)
    finally:
        await send_cmd('Runtime.releaseObject', {'objectId': node['objectId']})

    # File selection alone is not success. Require new rendered previews or
    # attachment chips for all files, and wait for processing to finish.
    poll_js = r"""(() => {
        const state = window.__museReferenceUpload;
        if (!state || !state.scope.isConnected) return {lost: true};
        const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
        const scope = state.scope;
        const alerts = [...document.querySelectorAll('[role="alert"]')].filter(visible)
            .map(el => el.innerText).filter(text => text && !state.oldAlerts.includes(text));
        const previews = [...scope.querySelectorAll('img')].filter(img => visible(img) && img.complete
            && img.naturalWidth > 0 && !state.before.includes(img.currentSrc || img.src));
        const text = scope.innerText || '';
        const names = FILE_NAMES;
        const chips = names.every(name => text.includes(name)) && [...scope.querySelectorAll('button')].some(button =>
            /remove|delete|xóa|gỡ/i.test(button.getAttribute('aria-label') || button.title || button.innerText));
        const busy = [...scope.querySelectorAll('[aria-busy="true"], [role="progressbar"], [data-state="uploading"]')].some(visible)
            || /uploading|đang tải lên|đang tải ảnh/i.test(text);
        return {error: alerts.join('; '), ready: !busy && (previews.length >= FILE_COUNT || chips)};
    })()""".replace('FILE_NAMES', json.dumps([Path(path).name for path in files])).replace('FILE_COUNT', str(len(files)))
    stable = 0
    while True:
        if is_cancelled():
            raise asyncio.CancelledError()
        state = (await evaluate(poll_js)).get('value') or {}
        if state.get('error') or state.get('lost'):
            raise RuntimeError(state.get('error') or 'Muse attachment composer disappeared; prompt was not submitted')
        stable = stable + 1 if state.get('ready') else 0
        if stable >= 2:
            record(f'Muse đã nhận {len(files)} ảnh tham chiếu; chuẩn bị gửi prompt', job_id)
            return
        await asyncio.sleep(1)
