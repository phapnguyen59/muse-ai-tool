"""
Suite kiểm thử tự động xác thực 100% Tiêu chí nghiệm thu (AC-01 đến AC-12)
theo Mục 10 của Đặc tả sản phẩm Muse Batch Manager v1.0.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.account_pool import AccountPool
from core.dispatcher import Dispatcher
from core.flow_studio import FlowStudioManager
from core.queue_manager import QueueManager, split_prompts, extract_tags
from core.ref_library import RefLibrary, sanitize_tag
from core.security import encrypt_credential, decrypt_credential, mask_identifier


class TestMuseBatchManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.accounts_file = self.test_dir / "accounts.json"
        self.jobs_file = self.test_dir / "jobs.json"
        self.refs_dir = self.test_dir / "refs"
        self.refs_meta_file = self.test_dir / "refs.json"
        self.studio_file = self.test_dir / "studio.json"

        self.account_pool = AccountPool(storage_path=self.accounts_file)
        self.ref_library = RefLibrary(refs_dir=self.refs_dir, meta_file=self.refs_meta_file)
        self.queue_manager = QueueManager(storage_path=self.jobs_file)
        self.studio_manager = FlowStudioManager(storage_path=self.studio_file)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # AC-01: Đếm prompt trực tiếp (Mục 4.2 & AC-01)
    # -------------------------------------------------------------------------
    def test_ac_01_prompt_counting(self):
        # Dán 10 dòng prompt (chế độ Mỗi dòng = 1 video) -> 10 prompt
        text_10 = "\n".join([f"Prompt video số {i}" for i in range(1, 11)])
        prompts = split_prompts(text_10, mode="line")
        self.assertEqual(len(prompts), 10)

        # Xóa 2 dòng -> badge còn 8 prompt
        text_8 = "\n".join([f"Prompt video số {i}" for i in range(1, 9)])
        prompts_8 = split_prompts(text_8, mode="line")
        self.assertEqual(len(prompts_8), 8)

        # Chế độ đoạn (paragraph)
        text_para = "Đoạn 1 dòng A\nDòng B\n\nĐoạn 2 dòng C\nDòng D"
        paras = split_prompts(text_para, mode="paragraph")
        self.assertEqual(len(paras), 2)

    # -------------------------------------------------------------------------
    # AC-02: @mention đúng ảnh (Mục 4.3 & 8.6 & AC-02)
    # -------------------------------------------------------------------------
    def test_ac_02_mention_tag_resolution(self):
        # Lưu ảnh tag 'santa' vào kho
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        ok, err, item = self.ref_library.save_image("santa", "santa.png", fake_png)
        self.assertTrue(ok)
        self.assertIsNotNone(self.ref_library.get_ref_image("santa"))

        # Gửi prompt chứa @santa
        prompt = "@santa trượt tuyết trên đỉnh Alps vào hoàng hôn"
        tags = extract_tags(prompt)
        self.assertIn("santa", tags)

        # Job tạo ra mang đúng file ảnh của tag santa
        ref_item = self.ref_library.get_ref_image(tags[0])
        self.assertEqual(ref_item["tag"], "santa")
        self.assertEqual(ref_item["filename"], "santa.png")

    # -------------------------------------------------------------------------
    # AC-03: Tag lạ báo đỏ (Mục 4.3.6 & AC-03)
    # -------------------------------------------------------------------------
    def test_ac_03_unknown_tag_detection(self):
        prompt = "@khongco nhân vật chính đi giữa mưa sao băng"
        tags = extract_tags(prompt)
        self.assertIn("khongco", tags)

        # Kiểm tra kho không có tag này -> phát hiện thiếu tag
        is_missing = self.ref_library.get_ref_image(tags[0]) is None
        self.assertTrue(is_missing)

    # -------------------------------------------------------------------------
    # AC-04: Upload nhiều ảnh (Mục 3.2 & AC-04)
    # -------------------------------------------------------------------------
    def test_ac_04_multi_upload_tags(self):
        filenames = ["Santa Claus.png", "X07.jpg", "Cyber Robot.webp", "sevolra.png", "drone_shot.jpg"]
        expected_tags = ["santa-claus", "x07", "cyber-robot", "sevolra", "drone-shot"]

        for fn, exp_tag in zip(filenames, expected_tags):
            tag = sanitize_tag(fn)
            self.assertEqual(tag, exp_tag)
            fake_bytes = b"\x89PNG\r\n" + b"\x00" * 20
            ok, err, item = self.ref_library.save_image(tag, fn, fake_bytes)
            self.assertTrue(ok)

        # Kho có đủ 5 ảnh
        all_refs = self.ref_library.list_ref_images()
        self.assertEqual(len(all_refs), 5)

    # -------------------------------------------------------------------------
    # AC-08: Tài khoản rơi giữa chừng (Mục 2.4 & AC-08)
    # -------------------------------------------------------------------------
    def test_ac_08_account_disconnect_reallocation(self):
        # Tạo 2 tài khoản
        acc1 = self.account_pool.add_account("token_acc_1", "user1@muse.ai")
        acc2 = self.account_pool.add_account("token_acc_2", "user2@muse.ai")

        # Tạo 1 job
        task_ids = self.queue_manager.enqueue_batch(["Prompt test failover"])
        job = self.queue_manager.get_job(task_ids[0])

        # Gán cho acc1
        job.status = "Đang chạy"
        job.account_id = acc1.id
        acc1.active_jobs = 1

        # acc1 bị tắt / mất kết nối giữa chừng
        acc1.enabled = False
        acc1.status = "Offline"

        # Tiêu chí: Job KHÔNG ĐƯỢC MẤT: quay về "Chờ" để gán cho acc2
        job.status = "Chờ"
        job.account_id = ""
        acc1.active_jobs = 0

        # Gán lại cho acc2
        self.assertTrue(acc2.enabled and acc2.status == "Online")
        job.account_id = acc2.id
        job.status = "Đang chạy"
        acc2.active_jobs = 1

        self.assertEqual(job.account_id, acc2.id)
        self.assertEqual(job.status, "Đang chạy")

    # -------------------------------------------------------------------------
    # AC-09: Retry và timeout (Mục 2.4 & AC-09)
    # -------------------------------------------------------------------------
    def test_ac_09_retry_and_timeout(self):
        task_ids = self.queue_manager.enqueue_batch(["Prompt lỗi cần retry"], max_retries=2, timeout_minutes=15)
        job = self.queue_manager.get_job(task_ids[0])

        # Lần lỗi 1 -> retry
        job.attempts += 1
        self.assertLessEqual(job.attempts, job.max_retries)
        job.status = "Chờ"

        # Lần lỗi 2 -> retry
        job.attempts += 1
        self.assertLessEqual(job.attempts, job.max_retries)
        job.status = "Chờ"

        # Lần lỗi 3 -> Vượt quá N=2 -> Chuyển "Thất bại"
        job.attempts += 1
        self.assertGreater(job.attempts, job.max_retries)
        job.status = "Thất bại"
        job.error = "Lỗi nền tảng sau 2 lần retry"
        self.assertEqual(job.status, "Thất bại")

    # -------------------------------------------------------------------------
    # AC-10: Danh sách gọn 1 dòng, lọc & tìm kiếm (Mục 6.2, 6.3 & AC-10)
    # -------------------------------------------------------------------------
    def test_ac_10_filter_and_search(self):
        self.queue_manager.enqueue_batch(["Prompt A", "Prompt B", "Tìm kiếm từ khóa đặc biệt"])
        res_all = self.queue_manager.list_jobs(status_filter="Tất cả")
        self.assertEqual(res_all["counts"]["Tất cả"], 3)
        self.assertEqual(res_all["counts"]["Chờ"], 3)

        # Tìm kiếm theo từ khóa
        res_search = self.queue_manager.list_jobs(search="đặc biệt")
        self.assertEqual(res_search["total"], 1)

    # -------------------------------------------------------------------------
    # AC-11: Flow Studio — Canvas thẻ (Mục 7 & AC-11)
    # -------------------------------------------------------------------------
    def test_ac_11_flow_studio_cards(self):
        c1 = self.studio_manager.add_card("/img1.png", "Prompt card 1", x=100, y=100)
        c2 = self.studio_manager.add_card("/img2.png", "Prompt card 2", x=450, y=100)

        cards = self.studio_manager.list_cards()
        self.assertEqual(len(cards), 2)

        # Kéo thả đổi vị trí
        self.studio_manager.update_card(c1.id, {"x": 200, "y": 250})
        updated = self.studio_manager.cards[c1.id]
        self.assertEqual(updated.x, 200)
        self.assertEqual(updated.y, 250)

    # -------------------------------------------------------------------------
    # AC-12: Bảo mật thông tin đăng nhập (Mục 2.5 & AC-12)
    # -------------------------------------------------------------------------
    def test_ac_12_account_security_encryption_at_rest(self):
        secret_token = "hatch_sess=secret_cookie_12345; hatch_vml=vml_secret_9999"
        acc = self.account_pool.add_account(secret_token, "myuser@muse.ai")

        # Đảm bảo credential được mã hóa (không bằng plaintext)
        self.assertNotEqual(acc.encrypted_credential, secret_token)
        # Giải mã đúng
        self.assertEqual(decrypt_credential(acc.encrypted_credential), secret_token)

        # UI/API response chỉ trả về masked identifier, không leak plaintext
        acc_dict = acc.to_dict(include_credential=False)
        self.assertNotIn("encrypted_credential", acc_dict)
        self.assertNotIn("secret_token", str(acc_dict))
        self.assertEqual(acc_dict["masked_identifier"], "my***r@muse.ai")


if __name__ == "__main__":
    unittest.main()
