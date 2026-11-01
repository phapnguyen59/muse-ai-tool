import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.dispatcher import Dispatcher
from core.queue_manager import VideoJob


class RescanTests(unittest.IsolatedAsyncioTestCase):
    async def test_restarts_only_target_watcher_and_preserves_thread(self):
        account = SimpleNamespace(id='A', enabled=True, status='Online', active_jobs=2, max_slots=3)
        job = VideoJob('target', 'original prompt', account_id='A', assigned_account_id='A',
                       thread_id='thread-123', tab_id='tab-123', submitted=True,
                       status='\u0110ang ch\u1ea1y', started_at=123)
        other = VideoJob('other', 'other prompt', account_id='A', status='\u0110ang ch\u1ea1y')
        jobs = {'target': job, 'other': other}
        queue = SimpleNamespace(jobs=jobs, get_job=jobs.get, save=lambda: None)
        pool = SimpleNamespace(accounts={'A': account}, save=lambda: None,
                               sync_active_jobs=lambda counts: setattr(account, 'active_jobs', counts.get('A', 0)))
        dispatcher = Dispatcher()
        dispatcher.is_running = True
        dispatcher.concurrency = 3
        gate = asyncio.Event()
        starts = []
        async def execute(**kwargs):
            starts.append((kwargs['job_id'], job.thread_id, job.submitted))
            await gate.wait()
        with patch('core.dispatcher.queue_manager', queue), patch('core.dispatcher.account_pool', pool), patch('core.dispatcher.record'), patch('core.dispatcher.worker.execute_job', side_effect=execute):
            old = asyncio.create_task(dispatcher._run_job_lifecycle(job, 'A'))
            untouched = asyncio.create_task(dispatcher._run_job_lifecycle(other, 'A'))
            dispatcher.active_tasks = {'target': old, 'other': untouched}
            await asyncio.sleep(0)
            await dispatcher.rescan_thread('target')
            await asyncio.sleep(0)
            try:
                self.assertTrue(old.done())
                self.assertIs(dispatcher.active_tasks['other'], untouched)
                self.assertFalse(untouched.done())
                self.assertIsNot(dispatcher.active_tasks['target'], old)
                self.assertEqual(job.thread_id, 'thread-123')
                self.assertEqual(job.tab_id, 'tab-123')
                self.assertEqual(job.account_id, 'A')
                self.assertEqual(job.started_at, 123)
                self.assertEqual(job.prompt, 'original prompt')
                self.assertTrue(job.submitted)
                self.assertEqual(account.active_jobs, 2)
                self.assertEqual(sum(row[0] == 'target' for row in starts), 2)
            finally:
                tasks = list(dispatcher.active_tasks.values())
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def test_no_thread_id_rejected_before_cancelling_any_task(self):
        job = VideoJob('target', 'test', status='\u0110ang ch\u1ea1y')
        dispatcher = Dispatcher()
        dispatcher.is_running = True
        with patch('core.dispatcher.queue_manager', SimpleNamespace(get_job=lambda _: job)):
            with self.assertRaisesRegex(ValueError, 'thread ID'):
                await dispatcher.rescan_thread('target')
        self.assertEqual(dispatcher.active_tasks, {})

    async def test_duplicate_request_rejected(self):
        dispatcher = Dispatcher()
        dispatcher._rescanning.add('target')
        with patch('core.dispatcher.queue_manager', SimpleNamespace(get_job=lambda _: object())):
            with self.assertRaises(ValueError):
                await dispatcher.rescan_thread('target')
