import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.muse_driver import prepare_new_thread, open_new_thread, enter_prompt


class PrepareThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_typed_via_chrome_input_and_verified(self):
        send = AsyncMock(return_value={'result': {'result': {'value': True}}})
        with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
            await enter_prompt(send, lambda: False, 'video prompt', 'test')
        calls = [c for c in send.call_args_list if c.args[0] == 'Input.insertText']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[1], {'text': 'video prompt'})
        self.assertFalse(calls[0].kwargs['replay'])

    async def test_prompt_lost_during_hydration_is_reentered(self):
        verified = 0
        async def send(method, params, **kwargs):
            nonlocal verified
            value = True
            if ' === ' in params.get('expression', ''):
                verified += 1
                value = verified == 2
            return {'result': {'result': {'value': value}}}
        with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
            await enter_prompt(send, lambda: False, 'video prompt', 'test')
        self.assertEqual(verified, 2)

    async def test_slow_editor_is_not_failed_after_twelve_seconds(self):
        probes = 0

        async def send(method, params):
            nonlocal probes
            expression = params.get('expression', '')
            if 'const buttons' in expression:
                value = 'clicked'
            elif expression.startswith('location.origin'):
                self.assertIn('contenteditable', expression)
                probes += 1
                value = probes >= 31
            else:
                value = dict(origin='https://muse.ai', path='/thread/new', ready='complete')
            return {'result': {'result': {'value': value}}}

        with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
            await open_new_thread(send, lambda: False, 'test')
        self.assertEqual(probes, 31)

    async def test_new_thread_login_redirect_is_reported(self):
        async def send(method, params):
            expression = params.get('expression', '')
            value = ('clicked' if 'const buttons' in expression else
                     False if expression.startswith('location.origin') else {'path': '/login'})
            return {'result': {'result': {'value': value}}}
        with self.assertRaisesRegex(RuntimeError, 'login expired'):
            await open_new_thread(send, lambda: False, 'test')

    async def test_home_without_editor_still_clicks_compose(self):
        calls = []

        async def send(method, params):
            calls.append((method, params))
            expression = params.get('expression', '')
            if 'const buttons' in expression:
                value = 'clicked'
            elif expression.startswith('({origin:'):
                value = dict(origin='https://muse.ai', path='/', ready='complete', compose=True)
            else:
                value = True
            return {'result': {'result': {'value': value}}}

        await prepare_new_thread(send, lambda: False, 'test')
        self.assertTrue(any('const buttons' in p.get('expression', '') for _, p in calls))
        self.assertEqual([p['url'] for m, p in calls if m == 'Page.navigate'], ['https://muse.ai/'])

    async def test_missing_compose_uses_new_thread_fallback(self):
        calls = []

        async def send(method, params):
            calls.append((method, params))
            expression = params.get('expression', '')
            if 'const buttons' in expression:
                value = 'missing'
            elif expression.startswith('({origin:'):
                value = dict(origin='https://muse.ai', path='/', ready='complete', compose=False)
            else:
                value = True
            return {'result': {'result': {'value': value}}}

        with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
            await prepare_new_thread(send, lambda: False, 'test')
        self.assertEqual([p['url'] for m, p in calls if m == 'Page.navigate'],
                         ['https://muse.ai/', 'https://muse.ai/thread/new'])

    async def test_login_redirect_stops_before_submission(self):
        send = AsyncMock(return_value={'result': {'result': {'value': {'path': '/auth/login'}}}})
        with self.assertRaisesRegex(RuntimeError, 'login expired'):
            await prepare_new_thread(send, lambda: False, 'test')
        self.assertEqual(send.await_count, 2)

    async def test_cancelled_does_not_click(self):
        send = AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await prepare_new_thread(send, lambda: True, 'test')
        self.assertEqual(send.await_count, 1)
