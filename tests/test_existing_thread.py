import unittest
from unittest.mock import AsyncMock, patch

from core.muse_driver import open_existing_thread
from core.muse_thread import read_thread_snapshot


class ExistingThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_populated_thread_without_reloading(self):
        page = {'url': 'https://muse.ai/thread/thread1', 'state': 'complete', 'video': True}
        send = AsyncMock(return_value={'result': {'result': {'value': page}}})
        await open_existing_thread(send, lambda: False, 'thread1')
        self.assertFalse(any(call.args[0] == 'Page.navigate' for call in send.call_args_list))

    async def test_blank_thread_opens_through_history_after_bootstrap(self):
        calls = []
        count = 0
        async def send(method, params=None, **kwargs):
            nonlocal count
            calls.append((method, params))
            if method != 'Runtime.evaluate':
                return {}
            if 'const link =' in params['expression']:
                value = True
            else:
                count += 1
                value = {'url': 'https://muse.ai/' if count == 2 else 'https://muse.ai/thread/thread1',
                         'state': 'complete', 'textLength': 0 if count == 1 else 100}
            return {'result': {'result': {'value': value}}}
        await open_existing_thread(send, lambda: False, 'thread1')
        self.assertEqual([params['url'] for method, params in calls if method == 'Page.navigate'], ['https://muse.ai/'])
        self.assertTrue(any('const link =' in (params or {}).get('expression', '') for _, params in calls))

    async def test_blank_page_is_a_load_error_not_a_no_video_result(self):
        page = {'url': 'https://muse.ai/thread/thread1', 'state': 'complete', 'textLength': 0}
        send = AsyncMock(return_value={'result': {'result': {'value': page}}})
        with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, 'lỗi tải trang'):
                await open_existing_thread(send, lambda: False, 'thread1')

    async def test_reads_video_in_child_frame_with_parent_thread_identity(self):
        async def send(method, params=None):
            if method == 'Page.getFrameTree':
                return {'result': {'frameTree': {'childFrames': [{'frame': {'id': 'child', 'url': 'https://muse.ai/embed'}}]}}}
            if method == 'Page.createIsolatedWorld':
                return {'result': {'executionContextId': 7}}
            if params.get('contextId') == 7:
                value = {'url': 'https://muse.ai/embed', 'ready': True, 'src': 'https://media.test/video.mp4', 'hasAnswer': True}
            else:
                value = {'url': 'https://muse.ai/thread/thread1', 'ready': False, 'frameCount': 1}
            return {'result': {'result': {'value': value}}}
        snapshot = await read_thread_snapshot(send, 'original prompt')
        self.assertEqual(snapshot['src'], 'https://media.test/video.mp4')
        self.assertEqual(snapshot['url'], 'https://muse.ai/thread/thread1')
