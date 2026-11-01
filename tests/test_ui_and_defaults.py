"""
Kiểm tra các yêu cầu tinh chỉnh UI và giá trị mặc định:
1. Mặc định 15s, có tùy chọn 30s
2. Luồng mặc định = 1
3. UI luồng đồng bộ chiều cao h-[32px] với các ô cùng hàng
4. Loại bỏ hoàn toàn tính năng tự động thêm vào hàng đợi khi dán trên cả UI và logic
"""
import unittest
from pathlib import Path
from core.dispatcher import Dispatcher
from core.queue_manager import QueueManager
from core.flow_studio import FlowStudioManager
import tempfile
import shutil

class TestUIAndDefaults(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.jobs_file = self.test_dir / "jobs.json"
        self.studio_file = self.test_dir / "studio.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_dispatcher_concurrency_default_is_1(self):
        d = Dispatcher()
        self.assertEqual(d.concurrency, 1)

    def test_queue_default_duration_is_15(self):
        qm = QueueManager(storage_path=self.jobs_file)
        task_ids = qm.enqueue_batch(["Prompt kiểm tra thời lượng mặc định"])
        job = qm.get_job(task_ids[0])
        self.assertEqual(job.duration, 15)

    def test_html_ui_components(self):
        html_path = Path("static/index.html")
        self.assertTrue(html_path.exists())
        content = html_path.read_text(encoding="utf-8")

        # 1. Thời lượng mặc định 15s và có option 30s
        self.assertIn('<option value="15" selected>15 giây (mặc định)</option>', content)
        self.assertIn('<option value="30">30 giây</option>', content)

        # 2. Luồng mặc định 1
        self.assertIn('id="inpConcurrency" value="1"', content)

        # 3. Kích thước UI luồng khớp chiều cao h-[32px]
        self.assertIn('h-[32px]', content)

        # 4. Loại bỏ tự động thêm khi dán
        self.assertNotIn("chkAutoPasteRun", content)
        self.assertNotIn("onPromptPaste", content)
        self.assertNotIn("Tự động thêm vào hàng đợi khi dán", content)

    def test_js_logic_cleaned(self):
        js_path = Path("static/app.js")
        self.assertTrue(js_path.exists())
        content = js_path.read_text(encoding="utf-8")

        # Đảm bảo logic dán tự động đã được gỡ bỏ hoàn toàn
        self.assertNotIn("chkAutoPasteRun", content)
        self.assertNotIn("onPromptPaste", content)
        self.assertNotIn("autoPasteRun", content)

if __name__ == "__main__":
    unittest.main()
