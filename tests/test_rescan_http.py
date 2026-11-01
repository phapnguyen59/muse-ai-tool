import unittest
from unittest.mock import AsyncMock, patch

import httpx
import app


class RescanHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_reaches_rescan_handler(self):
        with patch.object(app.dispatcher, 'rescan_thread', new=AsyncMock()) as rescan:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                response = await client.post('/api/queue/rescan/task_test')
            self.assertEqual(response.status_code, 200)
            rescan.assert_awaited_once_with('task_test')

    async def test_unknown_post_falls_through_static_mount_with_405(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
            response = await client.post('/api/queue/nonexistent-endpoint/task_test')
        self.assertEqual(response.status_code, 405)
