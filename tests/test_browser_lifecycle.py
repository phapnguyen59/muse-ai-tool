import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import shutil

from core.muse_driver import MuseCDPSession, clean_profile_orphans, cleanup_all_sessions, _sessions

class TestBrowserLifecycle(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_clean_profile_orphans_removes_stale_lockfiles(self):
        lock = self.test_dir / "lockfile"
        lock.write_text("locked", encoding="utf-8")
        self.assertTrue(lock.exists())

        clean_profile_orphans(self.test_dir)
        self.assertFalse(lock.exists())

    def test_is_browser_alive_false_when_no_proc(self):
        sess = MuseCDPSession("acc_test", "auth=dummy")
        self.assertFalse(sess.is_browser_alive())

    def test_is_browser_alive_false_when_proc_exited(self):
        sess = MuseCDPSession("acc_test", "auth=dummy")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        sess.proc = mock_proc
        sess.port = 12345
        self.assertFalse(sess.is_browser_alive())

    def test_is_browser_alive_false_when_port_refused(self):
        sess = MuseCDPSession("acc_test", "auth=dummy")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        sess.proc = mock_proc
        sess.port = 12345
        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            self.assertFalse(sess.is_browser_alive())

    def test_is_browser_alive_true_when_cdp_responds_200(self):
        sess = MuseCDPSession("acc_test", "auth=dummy")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        sess.proc = mock_proc
        sess.port = 12345
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        with patch("urllib.request.urlopen", return_value=mock_response):
            self.assertTrue(sess.is_browser_alive())

    def test_cleanup_all_sessions(self):
        sess = MuseCDPSession("acc_test_cleanup", "auth=dummy")
        sess.stop_browser = MagicMock()
        _sessions["acc_test_cleanup"] = sess

        cleanup_all_sessions()
        sess.stop_browser.assert_called_once()
        _sessions.pop("acc_test_cleanup", None)

if __name__ == "__main__":
    unittest.main()
