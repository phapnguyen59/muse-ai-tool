"""
Hàng đợi Job (Queue Manager) theo Mục 4, 5, 6 và 8.2 của đặc tả.
- Tách prompt theo 3 chế độ (dòng, đoạn, toàn bộ).
- Resolve @tag sang file ảnh tham chiếu tại thời điểm tạo job (Mục 8.6).
- Vòng đời trạng thái: Chờ → Đang chạy → Hoàn thành / Thất bại / Đã dừng.
- Bộ lọc, tìm kiếm, phân trang và dọn dẹp danh sách.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.ref_library import ref_library

from core.paths import DATA_DIR, JOBS_FILE, MEDIA_DIR


def split_prompts(text: str, mode: str = "line") -> List[str]:
    """Tách danh sách prompt theo 3 chế độ (Mục 4.1):
    - 'line': Mỗi dòng = 1 video (mặc định)
    - 'paragraph': Mỗi đoạn = 1 video (cách nhau bởi dòng trống)
    - 'all': Toàn bộ = 1 video
    """
    text = (text or "").strip()
    if not text:
        return []

    if mode == "paragraph":
        # Tách theo 2 hoặc nhiều dấu xuống dòng liên tiếp
        parts = re.split(r"\n\s*\n", text)
        return [p.strip() for p in parts if p.strip()]

    if mode == "all":
        return [text]

    # Mặc định: mỗi dòng không rỗng là 1 prompt
    lines = text.splitlines()
    return [l.strip() for l in lines if l.strip()]


def extract_tags(prompt: str) -> List[str]:
    """Trích xuất các @tag trong prompt theo thứ tự xuất hiện."""
    matches = re.findall(r"@([a-z0-9-_]+)", prompt, re.IGNORECASE)
    # Loại bỏ trùng lặp giữ nguyên thứ tự
    seen = set()
    result = []
    for m in matches:
        tag = m.lower()
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


class VideoJob:
    def __init__(
        self,
        job_id: str,
        prompt: str,
        duration: int = 15,
        ratio: str = "9:16",
        ref_tags: List[str] | None = None,
        resolved_refs: List[Dict[str, Any]] | None = None,
        status: str = "Chờ",  # "Chờ", "Đang chạy", "Hoàn thành", "Thất bại", "Đã dừng"
        progress: int = 0,
        account_id: str = "",
        attempts: int = 0,
        max_retries: int = 2,
        timeout_minutes: int = 15,
        created_at: float | None = None,
        started_at: float | None = None,
        finished_at: float | None = None,
        video_url: str = "",
        thumbnail_url: str = "",
        error: str = "",
        error_code: str = "",
        thread_id: str = "",
        tab_id: str = "",
        submitted: bool = False,
        assigned_account_id: str = "",
    ):
        self.thread_id = thread_id
        self.tab_id = tab_id
        self.submitted = submitted
        self.assigned_account_id = assigned_account_id
        self.id = job_id
        self.prompt = prompt
        self.duration = duration
        self.ratio = ratio
        self.ref_tags = ref_tags or []
        self.resolved_refs = resolved_refs or []
        self.status = status
        self.progress = progress
        self.account_id = account_id
        self.attempts = attempts
        self.max_retries = max_retries
        self.timeout_minutes = timeout_minutes
        self.created_at = created_at or time.time()
        self.started_at = started_at
        self.finished_at = finished_at
        self.video_url = video_url
        self.thumbnail_url = thumbnail_url
        self.error = error
        self.error_code = error_code
        self.last_progress_update: float = time.time()

    @property
    def elapsed_sec(self) -> int:
        if self.started_at is None:
            return 0
        end_time = self.finished_at or time.time()
        return max(0, int(end_time - self.started_at))

    def to_dict(self) -> Dict[str, Any]:
        acc_id = self.assigned_account_id or self.account_id
        acc_name = ''
        if acc_id:
            try:
                from core.account_pool import account_pool
                acc_obj = account_pool.accounts.get(acc_id)
                acc_name = (acc_obj.identifier if acc_obj else '') or acc_id
            except Exception:
                acc_name = acc_id

        return {
            "threadId": self.thread_id,
            "accountName": acc_name,
            "threadUrl": f"https://muse.ai/thread/{self.thread_id}" if self.thread_id else "",
            "tabId": self.tab_id,
            "submitted": self.submitted,
            "assignedAccountId": self.assigned_account_id,
            "id": self.id,
            "prompt": self.prompt,
            "refTags": self.ref_tags,
            "resolvedRefs": self.resolved_refs,
            "status": self.status,
            "progress": self.progress,
            "duration": self.duration,
            "ratio": self.ratio,
            "accountId": self.account_id,
            "attempts": self.attempts,
            "maxRetries": self.max_retries,
            "timeoutMinutes": self.timeout_minutes,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "elapsedSec": self.elapsed_sec,
            "videoUrl": self.video_url,
            "thumbnailUrl": self.thumbnail_url,
            "error": self.error,
            "errorCode": self.error_code,
        }


class QueueManager:
    def __init__(self, storage_path: Path = JOBS_FILE):
        self.storage_path = storage_path
        self.jobs: Dict[str, VideoJob] = {}
        self.load()

    def load(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            for item in raw:
                job = VideoJob(
                    thread_id=item.get("threadId", ""),
                    tab_id=item.get("tabId", ""),
                    submitted=item.get("submitted", False),
                    assigned_account_id=item.get("assignedAccountId", item.get("accountId", "")),
                    job_id=item["id"],
                    prompt=item["prompt"],
                    duration=item.get("duration", 15),
                    ratio=item.get("ratio", "9:16"),
                    ref_tags=item.get("refTags", []),
                    resolved_refs=item.get("resolvedRefs", []),
                    status=item.get("status", "Chờ"),
                    progress=item.get("progress", 0),
                    account_id=item.get("accountId", ""),
                    attempts=item.get("attempts", 0),
                    max_retries=item.get("maxRetries", 2),
                    timeout_minutes=item.get("timeoutMinutes", 15),
                    created_at=item.get("createdAt"),
                    started_at=item.get("startedAt"),
                    finished_at=item.get("finishedAt"),
                    video_url=item.get("videoUrl", ""),
                    thumbnail_url=item.get("thumbnailUrl", ""),
                    error=item.get("error", ""),
                    error_code=item.get("errorCode", ""),
                )
                self.jobs[job.id] = job
            self.recover_orphaned_jobs()
        except Exception as e:
            print(f"[QueueManager] Lỗi đọc jobs.json: {e}")

    def recover_orphaned_jobs(self):
        """Khôi phục các job bị kẹt ở trạng thái 'Đang chạy' do server khởi động lại."""
        changed = False
        for job in self.jobs.values():
            if (job.error == 'Muse finished replying without a video'
                    and job.submitted and job.thread_id):
                # Track the existing render; never resubmit a recovered prompt.
                job.status = "Ch\u1edd"
                job.progress = 0
                job.error = ""
                job.error_code = ""
                job.finished_at = None
                changed = True
            if job.status == "Đang chạy":
                # Resume tracking the recorded thread; file size is not proof of success.
                job.status = "Chờ"
                job.progress = 0
                job.error = "Resume existing Muse thread after restart"
                changed = True
        if changed:
            self.save()

    def save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [j.to_dict() for j in self.jobs.values()]
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def enqueue_batch(
        self,
        prompts: List[str],
        duration: int = 15,
        ratio: str = "9:16",
        batch_ref_tag: str = "",
        max_retries: int = 2,
        timeout_minutes: int = 15,
    ) -> List[str]:
        """Tạo job cho mỗi prompt đã tách (Mục 8.2).
        Resolve mọi @tag thành file ảnh cụ thể qua getRefImage(tag) và ghi vào job (Mục 8.6).
        """
        from core.account_pool import account_pool
        accounts = account_pool.get_online_accounts()
        loads = {a.id: 0 for a in accounts}
        created_ids = []
        for prompt_text in prompts:
            prompt_text = prompt_text.strip()
            if not prompt_text:
                continue

            job_id = f"task_{uuid.uuid4().hex[:8]}"
            tags = extract_tags(prompt_text)

            # Thêm ảnh dùng chung cho batch nếu có
            if batch_ref_tag and batch_ref_tag not in tags:
                tags.append(batch_ref_tag)

            resolved_refs = []
            for tag in tags:
                ref_info = ref_library.get_ref_image(tag)
                if ref_info:
                    resolved_refs.append(ref_info)

            job = VideoJob(
                job_id=job_id,
                prompt=prompt_text,
                duration=duration,
                ratio=ratio,
                ref_tags=tags,
                resolved_refs=resolved_refs,
                status="Chờ",
                progress=0,
                max_retries=max_retries,
                timeout_minutes=timeout_minutes,
            )
            if accounts:
                chosen = min(accounts, key=lambda a: loads[a.id])
                job.assigned_account_id = chosen.id
                loads[chosen.id] += 1
            self.jobs[job_id] = job
            created_ids.append(job_id)

        self.save()
        return created_ids

    def get_job(self, job_id: str) -> Optional[VideoJob]:
        return self.jobs.get(job_id)

    def list_jobs(
        self,
        status_filter: str = "Tất cả",
        search: str = "",
        page: int = 1,
        page_size: int = 10,
        all_records: bool = False,
    ) -> Dict[str, Any]:
        """Liệt kê job có lọc trạng thái, tìm kiếm, phân trang và bộ đếm (Mục 6.2 & 8.2)."""
        all_jobs = list(self.jobs.values())
        # Sắp xếp mới nhất lên đầu
        all_jobs.sort(key=lambda j: j.created_at, reverse=True)

        # Tính toán bộ đếm theo từng trạng thái
        counts = {
            "Tất cả": len(all_jobs),
            "Chờ": sum(1 for j in all_jobs if j.status == "Chờ"),
            "Đang chạy": sum(1 for j in all_jobs if j.status == "Đang chạy"),
            "Hoàn thành": sum(1 for j in all_jobs if j.status == "Hoàn thành"),
            "Thất bại": sum(1 for j in all_jobs if j.status == "Thất bại"),
            "Đã dừng": sum(1 for j in all_jobs if j.status == "Đã dừng"),
        }

        # Áp dụng bộ lọc trạng thái
        filtered = all_jobs
        if status_filter != "Tất cả":
            filtered = [j for j in filtered if j.status == status_filter]

        # Áp dụng tìm kiếm
        if search:
            q = search.lower().strip()
            filtered = [j for j in filtered if q in j.id.lower() or q in j.prompt.lower()
                        or q in j.thread_id.lower()]

        total = len(filtered)
        if all_records:
            return {
                "jobs": [j.to_dict() for j in filtered], "counts": counts,
                "total": total, "page": 1, "pageSize": total, "totalPages": 1,
            }
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = [j.to_dict() for j in filtered[start_idx:end_idx]]

        return {
            "jobs": page_items,
            "counts": counts,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }

    def retry_job(self, job_id: str) -> bool:
        """Chạy lại một job (thất bại / timeout / đã dừng)."""
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.status = "Chờ"
        job.progress = 0
        job.error = ""
        job.error_code = ""
        job.account_id = ""
        job.started_at = None
        job.finished_at = None
        self.save()
        return True

    def delete_job(self, job_id: str) -> bool:
        """Xóa một job khỏi danh sách."""
        if job_id in self.jobs:
            self.jobs.pop(job_id)
            self.save()
            return True
        return False

    def delete_jobs(self, job_ids: list[str]) -> list[str]:
        """Xóa nhiều job cùng lúc khỏi danh sách và lưu một lần."""
        deleted = []
        for jid in job_ids:
            if jid in self.jobs:
                self.jobs.pop(jid)
                deleted.append(jid)
        if deleted:
            self.save()
        return deleted

    def clear_finished(self) -> int:
        """Dọn toàn bộ job đã hoàn thành khỏi danh sách hiển thị (Mục 6.2)."""
        finished_ids = [jid for jid, j in self.jobs.items() if j.status == "Hoàn thành"]
        for jid in finished_ids:
            self.jobs.pop(jid, None)
        self.save()
        return len(finished_ids)

    def stop_all(self):
        """Dừng gán mới và dừng job đang chạy → 'Đã dừng' (Mục 5 & 8.2)."""
        for job in self.jobs.values():
            if job.status == "Đang chạy":
                job.status = "Đã dừng"
                job.error = "Người dùng bấm Dừng tất cả"
                job.finished_at = time.time()
        self.save()


queue_manager = QueueManager()
