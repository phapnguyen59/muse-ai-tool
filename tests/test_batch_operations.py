import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
import zipfile
import io

from starlette.testclient import TestClient
import app
from core.queue_manager import queue_manager, VideoJob
from core.paths import MEDIA_DIR

class TestBatchOperations(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.test_dir = Path(tempfile.mkdtemp())
        self._orig_media_dir = app.MEDIA_DIR
        app.MEDIA_DIR = self.test_dir

    def tearDown(self):
        app.MEDIA_DIR = self._orig_media_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_queue_manager_delete_jobs(self):
        j1 = VideoJob(job_id="test_j1", prompt="Prompt 1", status="Hoàn thành")
        j2 = VideoJob(job_id="test_j2", prompt="Prompt 2", status="Thất bại")
        j3 = VideoJob(job_id="test_j3", prompt="Prompt 3", status="Chờ")
        queue_manager.jobs["test_j1"] = j1
        queue_manager.jobs["test_j2"] = j2
        queue_manager.jobs["test_j3"] = j3

        deleted = queue_manager.delete_jobs(["test_j1", "test_j2", "test_nonexistent"])
        self.assertEqual(set(deleted), {"test_j1", "test_j2"})
        self.assertNotIn("test_j1", queue_manager.jobs)
        self.assertNotIn("test_j2", queue_manager.jobs)
        self.assertIn("test_j3", queue_manager.jobs)

        # Cleanup
        queue_manager.jobs.pop("test_j3", None)

    def test_api_batch_delete(self):
        j1 = VideoJob(job_id="test_del1", prompt="P1", status="Hoàn thành")
        j2 = VideoJob(job_id="test_del2", prompt="P2", status="Chờ")
        queue_manager.jobs["test_del1"] = j1
        queue_manager.jobs["test_del2"] = j2

        # Create dummy media files
        (self.test_dir / "test_del1.mp4").write_bytes(b"dummy_mp4")
        (self.test_dir / "test_del1_thumb.jpg").write_bytes(b"dummy_thumb")

        res = self.client.post("/api/queue/batch-delete", json={"job_ids": ["test_del1", "test_del2"]})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["deletedCount"], 2)
        self.assertEqual(set(data["deletedIds"]), {"test_del1", "test_del2"})

        # Verify media deleted
        self.assertFalse((self.test_dir / "test_del1.mp4").exists())
        self.assertFalse((self.test_dir / "test_del1_thumb.jpg").exists())

    def test_api_batch_download_single_file(self):
        (self.test_dir / "test_single.mp4").write_bytes(b"video_content_single")

        res = self.client.get("/api/queue/batch-download?ids=test_single")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "video/mp4")
        self.assertEqual(res.content, b"video_content_single")

    def test_api_batch_download_multiple_files_zip(self):
        (self.test_dir / "test_multi1.mp4").write_bytes(b"video_content_1")
        (self.test_dir / "test_multi2.mp4").write_bytes(b"video_content_2")

        res = self.client.get("/api/queue/batch-download?ids=test_multi1,test_multi2")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/zip")
        self.assertIn("attachment; filename=", res.headers.get("content-disposition", ""))

        # Verify zip contents
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        names = zf.namelist()
        self.assertIn("test_multi1.mp4", names)
        self.assertIn("test_multi2.mp4", names)
        self.assertEqual(zf.read("test_multi1.mp4"), b"video_content_1")
        self.assertEqual(zf.read("test_multi2.mp4"), b"video_content_2")

    def test_api_batch_download_post_zip(self):
        (self.test_dir / "test_post1.mp4").write_bytes(b"post_video_1")
        (self.test_dir / "test_post2.mp4").write_bytes(b"post_video_2")

        res = self.client.post("/api/queue/batch-download", json={"job_ids": ["test_post1", "test_post2"]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/zip")

    def test_api_batch_download_404_when_no_videos(self):
        res = self.client.get("/api/queue/batch-download?ids=nonexistent_1,nonexistent_2")
        self.assertEqual(res.status_code, 404)

if __name__ == "__main__":
    unittest.main()
