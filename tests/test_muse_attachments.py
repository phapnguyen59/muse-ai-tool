import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.muse_attachments import attach_reference_images


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_attaches_file_and_waits_for_ready_previews(self):
        calls = []
        polls = iter([{'ready': False}, {'ready': True}, {'ready': True}])
        async def send(method, params=None, **kwargs):
            params = params or {}
            calls.append((method, params, kwargs))
            if method == 'DOM.requestNode':
                return {'result': {'nodeId': 7}}
            if method != 'Runtime.evaluate':
                return {'result': {}}
            expression = params['expression']
            if expression == 'window.__museReferenceUpload.input':
                return {'result': {'result': {'objectId': 'input-node'}}}
            value = next(polls) if 'const state = window.__museReferenceUpload;' in expression else 'ready'
            return {'result': {'result': {'value': value}}}

        with tempfile.TemporaryDirectory() as tmp, patch('core.muse_attachments.asyncio.sleep', new=AsyncMock()):
            path = Path(tmp) / 'ref.png'
            path.write_bytes(b'fixture')
            await attach_reference_images(send, lambda: False, [path], 'document.querySelector("textarea")')
            uploads = [call for call in calls if call[0] == 'DOM.setFileInputFiles']
            self.assertEqual(len(uploads), 1)
            self.assertEqual(uploads[0][1], {'nodeId': 7, 'files': [str(path.resolve())]})
            self.assertFalse(uploads[0][2]['replay'])
            self.assertEqual(len([c for c in calls if 'const state = window.__museReferenceUpload;' in c[1].get('expression', '')]), 3)

    async def test_missing_file_fails_before_browser_calls(self):
        send = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            await attach_reference_images(send, lambda: False, [Path('missing-ref.png')], 'null')
        send.assert_not_called()

    async def test_missing_input_fails_instead_of_sending_without_image(self):
        send = AsyncMock(return_value={'result': {'result': {'value': 'missing-input'}}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ref.png'
            path.write_bytes(b'fixture')
            with self.assertRaisesRegex(RuntimeError, 'missing-input'):
                await attach_reference_images(send, lambda: False, [path], 'null')
        self.assertFalse(any(call.args[0] == 'DOM.setFileInputFiles' for call in send.call_args_list))

    async def test_cancel_does_not_attach(self):
        send = AsyncMock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ref.png'
            path.write_bytes(b'fixture')
            with self.assertRaises(asyncio.CancelledError):
                await attach_reference_images(send, lambda: True, [path], 'null')
        send.assert_not_called()
