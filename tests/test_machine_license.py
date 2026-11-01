import asyncio
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from core.machine_license import MachineLicense, LicenseDecision, LicenseError, get_machine_id


class MachineLicenseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'firebase_config.json'
        self.path.write_text('{"databaseURL":"https://muse-ai-test.firebaseio.com"}', encoding='utf-8')
        self.service = MachineLicense(self.path)
        self.env = patch.dict('os.environ', {}, clear=False)
        self.env.start()
        import os
        os.environ.pop('MUSE_FIREBASE_DATABASE_URL', None)
        self.identity = patch('core.machine_license.get_machine_id', return_value='MUSE-AAAA-BBBB-CCCC-DDDD')
        self.identity.start()

    def tearDown(self):
        self.identity.stop()
        self.env.stop()
        self.directory.cleanup()

    def test_each_tier_uses_one_read_only_request(self):
        for status, limit in [('free', 3), ('10', 10), ('50', 50), ('active', None)]:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({'status': status}).encode()
            with patch('core.machine_license.urllib.request.urlopen', return_value=response) as fetch:
                decision = self.service.check()
                self.assertEqual((decision.status, decision.max_accounts), (status, limit))
                fetch.assert_called_once()
                request = fetch.call_args.args[0]
                self.assertEqual(request.get_method(), 'GET')
                self.assertTrue(request.full_url.endswith('/licenses/MUSE-AAAA-BBBB-CCCC-DDDD.json'))
                self.assertIsNone(request.data)
                self.assertEqual(request.get_header('Cookie'), None)

    def test_local_machine_info_does_not_query_firebase(self):
        with patch('core.machine_license.urllib.request.urlopen') as fetch:
            info = self.service.local_info()
            self.assertEqual(info['machineId'], 'MUSE-AAAA-BBBB-CCCC-DDDD')
            self.assertTrue(info['firebaseConfigured'])
            fetch.assert_not_called()

    def test_new_machine_registers_free_without_overwriting_existing_license(self):
        missing = MagicMock()
        missing.__enter__.return_value.read.return_value = b'null'
        created = MagicMock()
        created.__enter__.return_value.read.return_value = b'{"status":"free"}'
        with patch('core.machine_license.urllib.request.urlopen', side_effect=[missing, created]) as fetch:
            decision = self.service.check()
            self.assertEqual(decision.max_accounts, 3)
            self.assertEqual(fetch.call_count, 2)
            request = fetch.call_args.args[0]
            self.assertEqual(request.get_method(), 'PUT')
            self.assertEqual(request.get_header('If-match'), 'null_etag')
            self.assertEqual(json.loads(request.data)['status'], 'free')

    def test_registration_conflict_does_not_grant_free_or_overwrite(self):
        missing = MagicMock()
        missing.__enter__.return_value.read.return_value = b'null'
        conflict = urllib.error.HTTPError('url', 412, 'changed', {}, None)
        with patch('core.machine_license.urllib.request.urlopen', side_effect=[missing, conflict]) as fetch:
            with self.assertRaises(LicenseError):
                self.service.check()
            self.assertEqual(fetch.call_count, 2)
            self.assertIsNone(self.service.last_check)

    def test_no_project_blocks_add_without_network(self):
        self.path.write_text('{"databaseURL":""}', encoding='utf-8')
        with patch('core.machine_license.urllib.request.urlopen') as fetch:
            with self.assertRaisesRegex(LicenseError, 'Chưa cấu hình'):
                self.service.check()
            fetch.assert_not_called()

    def test_unregistered_and_unreachable_are_not_free_fallbacks(self):
        failures = [(urllib.error.HTTPError('url', 404, 'missing', {}, None), 503),
                    (urllib.error.HTTPError('url', 403, 'denied', {}, None), 503),
                    (TimeoutError('offline'), 503)]
        for failure, status in failures:
            with patch('core.machine_license.urllib.request.urlopen', side_effect=failure):
                with self.assertRaises(LicenseError) as caught:
                    self.service.check()
                self.assertEqual(caught.exception.status_code, status)
                self.assertIsNone(self.service.last_check)

    def test_invalid_status_rejected(self):
        for fields in ({'status': 'blocked'}, {'status': 10}, {}):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(fields).encode()
            with patch('core.machine_license.urllib.request.urlopen', return_value=response):
                with self.assertRaises(LicenseError) as caught:
                    self.service.check()
                self.assertEqual(caught.exception.status_code, 403)

    def test_machine_id_is_stable_and_does_not_expose_raw_guid(self):
        get_machine_id.cache_clear()
        try:
            with patch('core.machine_license._windows_machine_guid', return_value='private-machine-guid'):
                first = get_machine_id()
                self.assertEqual(get_machine_id(), first)
                self.assertRegex(first, r'^MUSE-(?:[0-9A-F]{4}-){3}[0-9A-F]{4}$')
                self.assertNotIn('private-machine-guid', first)
        finally:
            get_machine_id.cache_clear()


class AccountLicenseAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_add_cannot_exceed_free_limit(self):
        import app
        accounts = {'disabled': object(), 'offline': object()}
        def add(credential, identifier):
            account = SimpleNamespace(to_dict=lambda **kwargs: {'id': 'new'})
            accounts['new'] = account
            return account
        pool = SimpleNamespace(accounts=accounts, add_account=add)
        decision = LicenseDecision('MUSE-AAAA-BBBB-CCCC-DDDD', 'free', 3, 123)
        with patch.object(app, 'account_pool', pool), patch.object(app, '_account_add_lock', asyncio.Lock()), patch.object(app.machine_license, 'check', return_value=decision) as check:
            request = app.AddAccountRequest(credentials='cookie=private')
            results = await asyncio.gather(app.api_add_account(request), app.api_add_account(request), return_exceptions=True)
            self.assertEqual(len(accounts), 3)
            self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
            self.assertEqual(sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results), 1)
            self.assertEqual(check.call_count, 2)

    async def test_firebase_failure_preserves_existing_accounts(self):
        import app
        pool = MagicMock()
        pool.accounts = {'existing': object()}
        with patch.object(app, 'account_pool', pool), patch.object(app, '_account_add_lock', asyncio.Lock()), patch.object(app.machine_license, 'check', side_effect=LicenseError('offline')):
            with self.assertRaises(HTTPException) as caught:
                await app.api_add_account(app.AddAccountRequest(credentials='cookie=private'))
            self.assertEqual(caught.exception.status_code, 503)
            pool.add_account.assert_not_called()
            self.assertEqual(len(pool.accounts), 1)

    async def test_unlimited_tier_does_not_cap_local_accounts(self):
        import app
        pool = MagicMock()
        pool.accounts = {str(i): object() for i in range(60)}
        decision = LicenseDecision('MUSE-AAAA-BBBB-CCCC-DDDD', 'active', None, 123)
        with patch.object(app, 'account_pool', pool), patch.object(app, '_account_add_lock', asyncio.Lock()), patch.object(app.machine_license, 'check', return_value=decision):
            response = await app.api_add_account(app.AddAccountRequest(credentials='cookie=private'))
            self.assertTrue(response['ok'])
            pool.add_account.assert_called_once()
