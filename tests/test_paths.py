import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import paths


class TestPathsAndDataPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.fake_legacy_dir = self.temp_dir / "legacy_data"
        self.fake_target_dir = self.temp_dir / "target_data"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_data_dir_resolution(self):
        with patch.dict(os.environ, {"TOOL_MUSE_DATA_DIR": str(self.fake_target_dir)}):
            resolved = paths.get_default_data_dir()
            self.assertEqual(resolved, self.fake_target_dir.resolve())

    def test_migration_from_legacy_data(self):
        # Tạo dữ liệu giả định trong thư mục legacy
        self.fake_legacy_dir.mkdir(parents=True)
        fake_accounts = self.fake_legacy_dir / "accounts.json"
        fake_accounts.write_text('[{"id": "acc_1", "identifier": "test@muse.ai"}]', encoding="utf-8")
        
        profiles_dir = self.fake_legacy_dir / "chrome_profiles" / "acc_1"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "test_cookie.txt").write_text("sample_cookie", encoding="utf-8")

        # Giả lập môi trường chạy với DATA_DIR mới và legacy_candidates chứa fake_legacy_dir
        with patch.object(paths, "DATA_DIR", self.fake_target_dir), \
             patch.object(paths, "ACCOUNTS_FILE", self.fake_target_dir / "accounts.json"), \
             patch.object(paths, "MEDIA_DIR", self.fake_target_dir / "media"), \
             patch.object(paths, "REFS_DIR", self.fake_target_dir / "refs"), \
             patch.object(paths, "PROFILES_DIR", self.fake_target_dir / "chrome_profiles"), \
             patch.object(paths, "DESKTOP_CONFIG_FILE", self.fake_target_dir / "desktop_config.json"):
            
            with patch("core.paths._check_and_migrate_legacy_data") as mock_check:
                paths.init_data_directory()
                self.assertTrue(self.fake_target_dir.exists())

            # Test hàm migration trực tiếp
            paths._copy_tree_merge(self.fake_legacy_dir, self.fake_target_dir)
            
            migrated_accounts = self.fake_target_dir / "accounts.json"
            self.assertTrue(migrated_accounts.exists())
            self.assertIn("test@muse.ai", migrated_accounts.read_text(encoding="utf-8"))

            migrated_cookie = self.fake_target_dir / "chrome_profiles" / "acc_1" / "test_cookie.txt"
            self.assertTrue(migrated_cookie.exists())
            self.assertEqual(migrated_cookie.read_text(encoding="utf-8"), "sample_cookie")


if __name__ == "__main__":
    unittest.main()
