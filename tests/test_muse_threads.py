import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.muse_driver import open_new_thread
from core.muse_thread import PageConnection, ResponseTracker, thread_id_from_url
from core.queue_manager import QueueManager


class TestThreadTracking(unittest.TestCase):
    def test_playable_video_completes_despite_stale_busy_and_changing_prose(self):
        tracker = ResponseTracker()
        snapshot = {'ready': True, 'busy': True, 'hasAnswer': True, 'playable': True,
                    'src': 'blob:complete', 'videoSignature': 'same-video', 'signature': 'text1'}
        self.assertIsNone(tracker.observe(snapshot))
        snapshot['signature'] = 'text2'
        self.assertIsNone(tracker.observe(snapshot))
        snapshot['signature'] = 'text3'
        self.assertEqual(tracker.observe(snapshot), 'blob:complete')

    def test_finished_reply_without_video_fails(self):
        tracker = ResponseTracker()
        snapshot = {'ready': True, 'busy': False, 'hasAnswer': True,
                    'responseComplete': True, 'signature': 'final-text'}
        tracker.observe(snapshot)
        tracker.observe(snapshot)
        with self.assertRaisesRegex(RuntimeError, 'không có video'):
            tracker.observe(snapshot)

    def test_all_records_are_returned_without_page_limits(self):
        from core.queue_manager import VideoJob
        with tempfile.TemporaryDirectory() as tmp:
            queue = QueueManager(Path(tmp) / 'jobs.json')
            queue.jobs = {str(i): VideoJob(str(i), f'prompt {i}') for i in range(127)}
            result = queue.list_jobs(all_records=True)
            self.assertEqual(len(result['jobs']), 127)
            self.assertEqual(result['total'], 127)
            filtered = queue.list_jobs(search='prompt 12', all_records=True)
            self.assertEqual(len(filtered['jobs']), 8)

    def test_concurrency_survives_restart(self):
        from core.dispatcher import Dispatcher
        with tempfile.TemporaryDirectory() as tmp, patch('core.dispatcher.account_pool') as pool:
            pool.accounts = {}
            path = Path(tmp) / 'config.json'
            dispatcher = Dispatcher(config_path=path)
            dispatcher.set_concurrency(3)
            self.assertEqual(Dispatcher(config_path=path).concurrency, 3)
            with self.assertRaises(ValueError):
                dispatcher.set_concurrency(0)
            self.assertEqual(Dispatcher(config_path=path).concurrency, 3)

    def test_thread_url_validation(self):
        self.assertEqual(thread_id_from_url('https://muse.ai/thread/abc-123_4'), 'abc-123_4')
        for url in ('https://muse.ai/thread/new', 'https://other.test/thread/abc',
                    'https://muse.ai/thread/abc/extra', 'https://muse.ai.evil.test/thread/id'):
            self.assertEqual(thread_id_from_url(url), '')

    def test_idle_does_not_mean_finished(self):
        tracker = ResponseTracker()
        for _ in range(10000):
            self.assertIsNone(tracker.observe({'ready': True, 'busy': False}))

    def test_busy_keeps_waiting_even_with_video(self):
        tracker = ResponseTracker()
        snapshot = {'ready': True, 'busy': True, 'hasAnswer': True, 'src': 'blob:video', 'signature': 'a'}
        for _ in range(10000):
            self.assertIsNone(tracker.observe(snapshot))
        snapshot['busy'] = False
        self.assertIsNone(tracker.observe(snapshot))
        self.assertIsNone(tracker.observe(snapshot))
        self.assertEqual(tracker.observe(snapshot), 'blob:video')

    def test_text_response_waits_for_delayed_video(self):
        tracker = ResponseTracker()
        snapshot = {'ready': True, 'hasAnswer': True, 'answer': 'Unable to generate', 'signature': 'text'}
        for _ in range(100):
            self.assertIsNone(tracker.observe(snapshot))
        snapshot.update(src='blob:completed', signature='video')
        self.assertIsNone(tracker.observe(snapshot))
        self.assertIsNone(tracker.observe(snapshot))
        self.assertEqual(tracker.observe(snapshot), 'blob:completed')

    def test_explicit_error_fails_after_stabilizing(self):
        tracker = ResponseTracker()
        snapshot = {'ready': True, 'error': 'Render failed', 'signature': 'error'}
        tracker.observe(snapshot)
        tracker.observe(snapshot)
        with self.assertRaisesRegex(RuntimeError, 'Render failed'):
            tracker.observe(snapshot)

    def test_video_takes_priority_over_alert(self):
        tracker = ResponseTracker()
        snapshot = {'ready': True, 'hasAnswer': True, 'src': 'blob:video',
                    'error': 'Old alert', 'signature': 'video'}
        tracker.observe(snapshot)
        tracker.observe(snapshot)
        self.assertEqual(tracker.observe(snapshot), 'blob:video')

    def test_batch_balanced_and_thread_persisted(self):
        accounts = [SimpleNamespace(id='A'), SimpleNamespace(id='B'), SimpleNamespace(id='C')]
        with tempfile.TemporaryDirectory() as tmp, patch('core.account_pool.account_pool.get_online_accounts', return_value=accounts):
            path = Path(tmp) / 'jobs.json'
            queue = QueueManager(path)
            ids = queue.enqueue_batch([str(i) for i in range(7)])
            self.assertEqual([queue.jobs[i].assigned_account_id for i in ids], ['A', 'B', 'C', 'A', 'B', 'C', 'A'])
            job = queue.jobs[ids[0]]
            job.thread_id, job.tab_id, job.submitted = 'thread123', 'tab123', True
            job.status = 'Đang chạy'
            queue.save()
            recovered = QueueManager(path).jobs[job.id]
            self.assertEqual(recovered.thread_id, 'thread123')
            self.assertEqual(recovered.tab_id, 'tab123')
            self.assertTrue(recovered.submitted)
            self.assertEqual(recovered.assigned_account_id, 'A')
            self.assertEqual(recovered.status, 'Ch\u1edd')


class TestThreadActions(unittest.IsolatedAsyncioTestCase):
    async def test_start_api_applies_selected_concurrency_before_start(self):
        import app
        with patch.object(app, 'dispatcher') as dispatcher, patch.object(app, 'account_pool') as pool:
            pool.get_online_accounts.return_value = [object()]
            await app.api_process_queue(app.ProcessQueueRequest(concurrency=3))
            self.assertEqual([call[0] for call in dispatcher.mock_calls][:2], ['set_concurrency', 'start'])
            dispatcher.set_concurrency.assert_called_once_with(3)

    async def test_three_prompts_on_one_account(self):
        from core.account_pool import Account
        from core.dispatcher import Dispatcher
        from core.queue_manager import VideoJob
        account = Account('A', 'A', '', max_slots=1)
        jobs = {str(i): VideoJob(str(i), 'test', assigned_account_id='A') for i in range(4)}
        pool = SimpleNamespace(accounts={'A': account}, get_online_accounts=lambda: [account],
                               save=lambda: None, sync_active_jobs=lambda counts: setattr(account, 'active_jobs', counts.get('A', 0)))
        queue = SimpleNamespace(jobs=jobs, save=lambda: None, stop_all=lambda: None)
        started = []
        gate = asyncio.Event()
        async def execute(**kwargs):
            started.append(kwargs['job_id'])
            await gate.wait()
        dispatcher = Dispatcher()
        with patch('core.dispatcher.account_pool', pool), patch('core.dispatcher.queue_manager', queue), patch('core.dispatcher.worker.execute_job', side_effect=execute):
            dispatcher.set_concurrency(3)
            self.assertEqual(account.max_slots, 3)
            dispatcher.start()
            try:
                for _ in range(150):
                    if len(started) == 3:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(started, ['0', '1', '2'])
                self.assertEqual(len(dispatcher.active_tasks), 3)
                self.assertEqual(jobs['3'].status, 'Ch\u1edd')
            finally:
                tasks = list(dispatcher.active_tasks.values())
                dispatcher.stop()
                await asyncio.gather(*tasks, return_exceptions=True)
                await dispatcher._loop_task

    async def test_dispatcher_obeys_concurrency_and_keeps_assignment(self):
        from core.account_pool import Account
        from core.dispatcher import Dispatcher
        from core.queue_manager import VideoJob
        accounts = [Account('A', 'A', ''), Account('B', 'B', ''), Account('C', 'C', '')]
        jobs = {str(i): VideoJob(str(i), 'test', assigned_account_id=accounts[i % 3].id) for i in range(6)}
        def sync(counts):
            for acc in accounts:
                acc.active_jobs = counts.get(acc.id, 0)
        pool = SimpleNamespace(accounts={a.id: a for a in accounts}, get_online_accounts=lambda: accounts,
                               save=lambda: None, sync_active_jobs=sync)
        queue = SimpleNamespace(jobs=jobs, save=lambda: None, stop_all=lambda: None)
        started = []
        gate = asyncio.Event()
        async def execute(**kwargs):
            started.append((kwargs['job_id'], kwargs['account_id']))
            await gate.wait()
        dispatcher = Dispatcher()
        with patch('core.dispatcher.account_pool', pool), patch('core.dispatcher.queue_manager', queue), patch('core.dispatcher.worker.execute_job', side_effect=execute):
            dispatcher.set_concurrency(2)
            dispatcher.start()
            try:
                for _ in range(100):
                    if len(started) == 2:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(started, [('0', 'A'), ('1', 'B')])
                self.assertEqual(len(dispatcher.active_tasks), 2)
            finally:
                tasks = list(dispatcher.active_tasks.values())
                dispatcher.stop()
                await asyncio.gather(*tasks, return_exceptions=True)
                await dispatcher._loop_task

    async def test_compose_click_and_missing_fallback(self):
        for state in ('clicked', 'missing'):
            calls = []
            async def send(method, params):
                calls.append((method, params))
                value = state if 'const buttons' in params.get('expression', '') else True
                return {'result': {'result': {'value': value}}}
            with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
                await open_new_thread(send, lambda: False)
            navigations = [p for m, p in calls if m == 'Page.navigate']
            self.assertEqual(navigations, [{'url': 'https://muse.ai/thread/new'}] if state == 'missing' else [])

    async def test_cancel_is_immediate(self):
        with self.assertRaises(asyncio.CancelledError):
            await open_new_thread(AsyncMock(), lambda: True)

    async def test_disabled_does_not_navigate(self):
        send = AsyncMock(return_value={'result': {'result': {'value': 'disabled'}}})
        with patch('core.muse_driver.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                await open_new_thread(send, lambda: False)
        self.assertTrue(all(call.args[0] != 'Page.navigate' for call in send.call_args_list))

    async def test_connection_recovers_on_same_tab(self):
        disconnected = AsyncMock()
        disconnected.recv.side_effect = OSError('temporary disconnect')
        connected = AsyncMock()
        connected.recv.return_value = json.dumps({'id': 2, 'result': {'value': 42}})
        with patch('core.muse_thread.websockets.connect', new=AsyncMock(side_effect=[disconnected, connected])), patch('core.muse_thread.asyncio.sleep', new=AsyncMock()):
            page = PageConnection('ws://same-tab', lambda: False)
            result = await page.command('Runtime.evaluate', {'expression': 'location.href'})
            self.assertEqual(result['result']['value'], 42)
            await page.close()

    async def test_uncertain_submit_is_not_replayed(self):
        socket = AsyncMock()
        socket.recv.side_effect = OSError('lost acknowledgement')
        with patch('core.muse_thread.websockets.connect', new=AsyncMock(return_value=socket)):
            page = PageConnection('ws://same-tab', lambda: False)
            with self.assertRaises(ConnectionError):
                await page.command('Runtime.evaluate', {'expression': 'button.click()'}, replay=False)
            self.assertEqual(socket.send.await_count, 1)


if __name__ == '__main__':
    unittest.main()
