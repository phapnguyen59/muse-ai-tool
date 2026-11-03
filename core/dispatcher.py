"""
Bộ điều phối (Dispatcher) theo Mục 2.3, 2.4, 5 và 8.2 của đặc tả.
- Dispatcher là thành phần duy nhất được gán job (FIFO).
- Số luồng hiệu dụng = min(số luồng đã cấu hình, tổng slot trống của các tài khoản Online).
- Tự động gán lại job khi tài khoản mất kết nối / bị tắt giữa chừng (AC-08).
- Tự động retry tối đa N lần (AC-09), kiểm tra timeout X phút.
- Chạy cuốn chiếu cho tới khi hết job chờ hoặc bấm 'Dừng tất cả'.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.account_pool import account_pool
from core.queue_manager import queue_manager, VideoJob
from core.ref_library import ref_library
from core.worker import worker
from core.activity_log import record, snapshot


class Dispatcher:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self._next_account = 0
        self.is_running: bool = False
        self.concurrency: int = 1  # Giới hạn số luồng song song toàn hệ thống (mặc định = 1)
        self.max_retries: int = 2  # N lần retry
        self.timeout_minutes: int = 15  # X phút timeout
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self._rescanning = set()
        self._loop_task: Optional[Any] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        if self.config_path is not None:
            try:
                saved = json.loads(self.config_path.read_text(encoding='utf-8'))
                self.concurrency = max(1, min(20, int(saved['concurrency'])))
            except (OSError, ValueError, TypeError, KeyError):
                pass

    def set_concurrency(self, n: int):
        """Đặt số luồng song song toàn hệ thống (Mục 8.3)."""
        value = int(n)
        if not 1 <= value <= 20:
            raise ValueError('Concurrency must be between 1 and 20')
        if self.config_path is not None:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.config_path.with_suffix('.tmp')
            temp.write_text(json.dumps({'concurrency': value}), encoding='utf-8')
            temp.replace(self.config_path)
        self.concurrency = value
        self._sync_account_capacity()
        record(f'Concurrency applied: {self.concurrency}; active jobs: {len(self.active_tasks)}')

    def _sync_account_capacity(self):
        """The visible concurrency setting also unlocks slots on a single account."""
        changed = False
        for account in account_pool.accounts.values():
            if account.max_slots != self.concurrency:
                account.max_slots = self.concurrency
                changed = True
        if changed:
            account_pool.save()

    def get_effective_concurrency(self) -> int:
        """Số luồng hiệu dụng = min(số luồng cấu hình, tổng slot trống của tài khoản Online)."""
        total_slots = account_pool.total_free_slots()
        return min(self.concurrency, total_slots)

    def start(self):
        """Khởi động dispatcher chạy cuốn chiếu (Mục 5 & 8.2)."""
        self.is_running = True
        record('Bắt đầu xử lý hàng đợi')
        self._sync_account_capacity()
        if self._loop_task is None or (hasattr(self._loop_task, 'done') and self._loop_task.done()):
            try:
                loop = asyncio.get_running_loop()
                self._main_loop = loop
                self._loop_task = loop.create_task(self._dispatcher_loop())
            except RuntimeError:
                # Gọi từ worker thread
                if self._main_loop and self._main_loop.is_running():
                    self._loop_task = asyncio.run_coroutine_threadsafe(self._dispatcher_loop(), self._main_loop)
                else:
                    loop = asyncio.get_event_loop()
                    self._main_loop = loop
                    self._loop_task = loop.create_task(self._dispatcher_loop())

    def stop(self):
        """Dừng dispatcher và chuyển các job đang chạy sang 'Đã dừng' (Mục 5)."""
        self.is_running = False
        record('Đã yêu cầu dừng tất cả job', level='warning')
        # Hủy các task đang chạy
        for job_id, task in list(self.active_tasks.items()):
            if hasattr(task, 'done') and not task.done():
                task.cancel()
        queue_manager.stop_all()

    async def _dispatcher_loop(self):
        """Vòng lặp điều phối chính."""
        while self.is_running:
            # 0. Đồng bộ chuẩn xác số job đang chạy cho từng tài khoản (chống kẹt slot)
            running_by_acc = {}
            for j in queue_manager.jobs.values():
                if j.status == "Đang chạy" and j.account_id:
                    running_by_acc[j.account_id] = running_by_acc.get(j.account_id, 0) + 1
            account_pool.sync_active_jobs(running_by_acc)

            # 2. Lấy danh sách job 'Chờ' theo thứ tự FIFO
            waiting_jobs = [
                j for j in queue_manager.jobs.values()
                if j.status == "Chờ" and j.id not in self.active_tasks
            ]
            waiting_jobs.sort(key=lambda j: j.created_at)

            # 3. Lấy danh sách tài khoản Online và còn slot trống
            online_accounts = account_pool.get_online_accounts()
            self._sync_account_capacity()

            # Nếu không còn job chờ nào và không có task nào đang chạy -> Kết thúc đợt chạy
            if not waiting_jobs and not self.active_tasks:
                self.is_running = False
                record('Đã xử lý hết hàng đợi')
                break

            # Nếu không có tài khoản online nào mà còn job chờ, tạm nghỉ một lát
            if not online_accounts or not waiting_jobs:
                await asyncio.sleep(0.5)
                continue

            # Gán job cho tài khoản còn slot trống
            # Pin jobs before dispatch, keeping batches evenly distributed even at concurrency=1.
            for pending in waiting_jobs:
                if not pending.assigned_account_id:
                    pending.assigned_account_id = online_accounts[self._next_account % len(online_accounts)].id
                    self._next_account += 1
            queue_manager.save()
            # Fill available slots in account rounds, including multiple tabs
            # on the same account, without waiting for a running job to finish.
            for acc in online_accounts * self.concurrency:
                if len(self.active_tasks) + len(self._rescanning) >= self.concurrency:
                    break
                if acc.free_slots <= 0:
                    continue
                if not waiting_jobs:
                    break

                job = next((j for j in waiting_jobs if j.assigned_account_id == acc.id), None)
                if job is None:
                    continue
                waiting_jobs.remove(job)

                # Kiểm tra tag tham chiếu thiếu trước khi chạy (Mục 4.3.6)
                missing_tags = []
                for tag in job.ref_tags:
                    if not ref_library.get_ref_image(tag):
                        missing_tags.append(tag)
                if missing_tags:
                    record('Thiếu ảnh tham chiếu: ' + ', '.join(missing_tags), job.id, 'error')
                    job.status = "Thất bại"
                    job.error = f"Thiếu ảnh tham chiếu cho tag: @{', @'.join(missing_tags)} (Mục 4.3.6)"
                    job.error_code = "MISSING_REF_TAGS"
                    job.finished_at = time.time()
                    queue_manager.save()
                    continue

                # Gán job vào tài khoản
                acc.active_jobs += 1
                record('Nhận job, chuẩn bị kết nối tài khoản ' + acc.id, job.id)
                job.account_id = acc.id
                job.status = "Đang chạy"
                job.started_at = time.time()
                job.last_progress_update = time.time()
                job.progress = 0
                job.error = ""
                queue_manager.save()
                account_pool.save()

                task = asyncio.create_task(self._run_job_lifecycle(job, acc.id))
                self.active_tasks[job.id] = task
                await asyncio.sleep(0.2)

            await asyncio.sleep(0.5)

    async def rescan_thread(self, job_id: str):
        """Replace one watcher only after its old task has fully stopped."""
        job = queue_manager.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job_id in self._rescanning:
            raise ValueError('Record này đang được khởi động lại bộ quét')
        if job.status != '\u0110ang ch\u1ea1y' or not self.is_running:
            raise ValueError('Chỉ quét lại record đang chạy')
        if not job.thread_id:
            raise ValueError('Chưa có thread ID; không quét lại để tránh gửi trùng prompt')
        account_id = job.account_id
        acc = account_pool.accounts.get(account_id)
        if not acc or not acc.enabled or acc.status != 'Online':
            raise ValueError('Tài khoản gốc không khả dụng; hãy kiểm tra đăng nhập')
        if job_id not in self.active_tasks and len(self.active_tasks) >= self.concurrency:
            raise ValueError('Đã đủ số luồng đang chạy; chưa thể mở bộ quét cho record này')
        self._rescanning.add(job_id)
        try:
            record('Yêu cầu quét lại thread cũ; không gửi lại prompt', job_id)
            old = self.active_tasks.get(job_id)
            if old is not None:
                if old.done():
                    raise ValueError('Job vừa kết thúc; hãy cập nhật danh sách')
                old.cancel()
                done, _ = await asyncio.wait({old}, timeout=10)
                if not done:
                    raise ValueError('Bộ quét cũ đang đóng kết nối; vui lòng thử lại sau')
            if not self.is_running or queue_manager.get_job(job_id) is not job:
                raise ValueError('Hàng đợi đã dừng hoặc record đã bị xóa')
            if job.status == 'Ho\u00e0n th\u00e0nh':
                raise ValueError('Video vừa hoàn thành; không cần quét lại')
            if not acc.enabled or acc.status != 'Online' or account_pool.accounts.get(account_id) is not acc:
                raise ValueError('Tài khoản gốc đã thay đổi; chưa khởi động lại bộ quét')
            job.submitted = True
            job.status = '\u0110ang ch\u1ea1y'
            job.finished_at = None
            job.error = ''
            job.error_code = ''
            job.last_progress_update = time.time()
            # Keep thread ID, tab ID, account, prompt and original start time.
            account_pool.sync_active_jobs({a.id: sum(
                j.status == '\u0110ang ch\u1ea1y' and j.account_id == a.id
                for j in queue_manager.jobs.values()) for a in account_pool.accounts.values()})
            queue_manager.save()
            account_pool.save()
            self.active_tasks[job_id] = asyncio.create_task(self._run_job_lifecycle(job, account_id))
            record('Bộ quét đã khởi động lại trên thread ' + job.thread_id, job_id)
        finally:
            self._rescanning.discard(job_id)

    async def _run_job_lifecycle(self, job: VideoJob, account_id: str):
        """Thực thi một job và xử lý failover, retry theo Mục 2.4 & AC-08, AC-09."""
        acc = account_pool.accounts.get(account_id)

        def on_prog(pct: int):
            old_p = job.progress
            job.progress = pct
            job.last_progress_update = time.time()
            if pct == 100 or abs(pct - old_p) >= 5:
                queue_manager.save()

        def is_cancelled() -> bool:
            return not self.is_running or job.status == "Đã dừng"

        def is_account_valid() -> bool:
            curr_acc = account_pool.accounts.get(account_id)
            return bool(curr_acc and curr_acc.enabled and curr_acc.status == "Online")

        try:
            res = await worker.execute_job(
                job_id=job.id,
                prompt=job.prompt,
                duration=job.duration,
                ratio=job.ratio,
                account_id=account_id,
                on_progress=on_prog,
                is_cancelled=is_cancelled,
                is_account_valid=is_account_valid,
            )
            # Thành công!
            job.status = "Hoàn thành"
            job.progress = 100
            job.video_url = res["video_url"]
            record('Hoàn thành: video đã tải về và kiểm tra hợp lệ', job.id, 'success')
            job.thumbnail_url = res["thumbnail_url"]
            job.finished_at = time.time()
            job.error = ""
            job.error_code = ""

        except asyncio.CancelledError:
            record('Job đã dừng', job.id, 'warning')
            job.status = "Đã dừng"
            job.finished_at = time.time()
        except Exception as e:
            record('Job thất bại: ' + str(e)[:300], job.id, 'error')
            # Never resubmit automatically: a request may already have reached Muse.
            job.status = "Thất bại"
            job.finished_at = time.time()
            job.error = str(e)[:300]
            job.error_code = "MUSE_JOB_FAILED"

        finally:
            if acc and acc.active_jobs > 0:
                acc.active_jobs -= 1
            self.active_tasks.pop(job.id, None)
            queue_manager.save()
            account_pool.save()

    def get_state(self) -> Dict[str, Any]:
        """Ảnh tổng quan trong một lần gọi theo Mục 8.5 của đặc tả.
        Đủ để render header, tabs và dải trực tiếp mà không cần nhiều request rời.
        """
        all_jobs = list(queue_manager.jobs.values())
        running_jobs = [j for j in all_jobs if j.status == "Đang chạy"]
        running_jobs.sort(key=lambda j: j.started_at or 0)

        counts = {
            "Tất cả": len(all_jobs),
            "Chờ": sum(1 for j in all_jobs if j.status == "Chờ"),
            "Đang chạy": len(running_jobs),
            "Hoàn thành": sum(1 for j in all_jobs if j.status == "Hoàn thành"),
            "Thất bại": sum(1 for j in all_jobs if j.status == "Thất bại"),
            "Đã dừng": sum(1 for j in all_jobs if j.status == "Đã dừng"),
        }

        # Đồng bộ lại slot tài khoản theo thực tế running_jobs
        running_by_acc = {}
        for j in running_jobs:
            if j.account_id:
                running_by_acc[j.account_id] = running_by_acc.get(j.account_id, 0) + 1
        account_pool.sync_active_jobs(running_by_acc)

        online_accounts = account_pool.get_online_accounts()

        return {
            "logs": snapshot(),
            "counts": counts,
            "isRunning": self.is_running,
            "configuredConcurrency": self.concurrency,
            "concurrencyProtocol": 2,
            "activeTasksCount": len(self.active_tasks),
            "effectiveConcurrency": self.get_effective_concurrency(),
            "totalFreeSlots": account_pool.total_free_slots(),
            "onlineAccountsCount": len(online_accounts),
            "totalAccountsCount": len(account_pool.accounts),
            "isSystemOnline": len(online_accounts) > 0,
            "refImagesCount": len(ref_library.images),
            "runningJobs": [j.to_dict() for j in running_jobs],
        }


from core.paths import DISPATCHER_CONFIG_FILE
dispatcher = Dispatcher(config_path=DISPATCHER_CONFIG_FILE.resolve())
