"""

Muse ai tool — FastAPI Server

Triển khai toàn bộ Hợp đồng API nội bộ theo Mục 8 của đặc tả sản phẩm.

"""

from __future__ import annotations


import os
import asyncio

import sys


# Đảm bảo console UTF-8 trên Windows

if sys.platform == "win32":

    try:

        sys.stdout.reconfigure(encoding="utf-8")

        sys.stderr.reconfigure(encoding="utf-8")

    except Exception:

        pass


from pathlib import Path

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, File, HTTPException, Query, UploadFile, status

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field


from core.account_pool import account_pool

from core.machine_license import machine_license, LicenseError

from core.dispatcher import dispatcher

from core.flow_studio import flow_studio

from core.queue_manager import queue_manager, split_prompts

from core.ref_library import ref_library, sanitize_tag, is_valid_tag


from core.paths import (
    BASE_DIR,
    BUNDLE_DIR,
    STATIC_DIR,
    BIN_DIR,
    DATA_DIR,
    MEDIA_DIR,
    REFS_DIR,
    init_data_directory,
)




init_data_directory()

STATIC_DIR.mkdir(parents=True, exist_ok=True)

if BIN_DIR.is_dir() and str(BIN_DIR) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")


app = FastAPI(

    title="Muse ai tool API",

    description="Backend API cho tool tạo video AI hàng loạt Muse ai tool v1.0",

    version="1.0.0",

)


@app.on_event("startup")

async def on_startup():

    import asyncio

    from core.activity_log import record

    record('Tool đã khởi động, sẵn sàng xử lý hàng đợi')

    dispatcher._main_loop = asyncio.get_running_loop()

    # Khôi phục các job mồ côi nếu server bị tắt khi job đang chạy

    queue_manager.recover_orphaned_jobs()


    # Tự động đăng ký và đồng bộ mã máy + status lên Firebase Realtime Database

    async def _bg_license_sync():

        try:

            await asyncio.to_thread(machine_license.check)

        except Exception as e:

            print(f"[Firebase] Đồng bộ bản quyền: {e}", flush=True)

        while True:

            await asyncio.sleep(300)

            try:

                await asyncio.to_thread(machine_license.check)

            except Exception:

                pass


    asyncio.create_task(_bg_license_sync())


app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time
    from core.activity_log import record
    start_time = time.time()
    method = request.method
    path = request.url.path
    response = await call_next(request)
    duration = time.time() - start_time
    if (method in ("POST", "PUT", "DELETE", "PATCH") or response.status_code >= 400) and not path.startswith("/static"):
        status_code = response.status_code
        lvl = "error" if status_code >= 500 else ("warning" if status_code >= 400 else "info")
        record(f"[API] {method} {path} -> {status_code} ({duration:.2f}s)", level=lvl)
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# =========================================================================

# 8.1 Account — Quản lý tài khoản

# =========================================================================

class AddAccountRequest(BaseModel):

    credentials: str

    identifier: Optional[str] = ""


class PatchAccountRequest(BaseModel):

    enabled: bool


_account_add_lock = asyncio.Lock()
@app.get('/api/machine', tags=['Account'])
def api_machine_info():
    try:
        return {**machine_license.local_info(), 'savedAccounts': len(account_pool.accounts)}
    except LicenseError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error))
@app.post("/api/accounts", tags=["Account"])

async def api_add_account(req: AddAccountRequest):

    """Thêm tài khoản vào pool, mã hóa credentials trước khi lưu (Mục 8.1 & AC-12)."""

    if not req.credentials.strip():

        raise HTTPException(status_code=400, detail="Thông tin đăng nhập (credentials) không được để trống")

    async with _account_add_lock:
        try:
            decision = await asyncio.to_thread(machine_license.check)
        except LicenseError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error))
        saved = len(account_pool.accounts)
        if decision.max_accounts is not None and saved >= decision.max_accounts:
            raise HTTPException(status_code=409, detail=(
                f'Đã đạt giới hạn {saved}/{decision.max_accounts} tài khoản (status: {decision.status}). '
                'Tài khoản Offline hoặc bị tắt vẫn được tính; hãy xóa bớt hoặc nâng hạn mức.'))
        acc = account_pool.add_account(req.credentials, req.identifier or "")
        from core.activity_log import record
        acc_name = req.identifier or getattr(acc, "id", "") or "Mới"
        record(f"Tài khoản: Đã thêm tài khoản '{acc_name}' (Tổng pool: {saved + 1} tài khoản)")
        return {"ok": True, "account": acc.to_dict(include_credential=False),
                "license": decision.to_dict(), "savedAccounts": saved + 1}


@app.delete("/api/accounts/{account_id}", tags=["Account"])

def api_remove_account(account_id: str):

    """Xóa tài khoản, hủy session, xóa credential đã mã hóa; gán lại job đang chạy (Mục 2.4 & 8.1)."""

    acc = account_pool.remove_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    from core.activity_log import record
    record(f"Tài khoản: Đã xóa tài khoản {account_id}")

    return {"ok": True, "id": account_id}


@app.get("/api/accounts", tags=["Account"])

def api_list_accounts():

    """Danh sách tài khoản: định danh đã che, enabled, trạng thái phiên, số job đang chạy."""

    return account_pool.list_accounts()


@app.patch("/api/accounts/{account_id}", tags=["Account"])

def api_set_account_enabled(account_id: str, req: PatchAccountRequest):

    """Bật / tắt nhận job mới cho một tài khoản (Mục 8.1)."""

    acc = account_pool.set_account_enabled(account_id, req.enabled)

    if not acc:

        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")

    return {"ok": True, "account": acc.to_dict(include_credential=False)}


@app.get("/api/accounts/{account_id}/health", tags=["Account"])

def api_account_health(account_id: str):

    """Kiểm tra sức khỏe một phiên theo yêu cầu: healthy / expired / unreachable + lý do."""

    res = account_pool.check_health(account_id)

    return res


# =========================================================================

# 8.2 Queue — Hàng đợi job

# =========================================================================

class BatchDeleteRequest(BaseModel):
    job_ids: List[str] = Field(..., description="Danh sách Job ID cần xóa")


class BatchDownloadRequest(BaseModel):
    job_ids: List[str] = Field(..., description="Danh sách Job ID cần tải về")


class EnqueueBatchRequest(BaseModel):

    prompts: List[str]

    duration: int = 15

    ratio: str = "9:16"

    batchRefTag: Optional[str] = ""

    maxRetries: int = 2

    timeoutMinutes: int = 15


class FailJobRequest(BaseModel):

    jobId: str

    error: str

    errorCode: Optional[str] = "WORKER_ERROR"


class CompleteJobRequest(BaseModel):

    jobId: str

    videoUrl: str

    thumbnailUrl: str


@app.post("/api/queue/batch", tags=["Queue"])

def api_enqueue_batch(req: EnqueueBatchRequest):

    """Tạo job cho mỗi prompt đã tách; resolve @tag và ghi danh sách vào job (Mục 8.2 & 8.6)."""

    if not req.prompts:

        raise HTTPException(status_code=400, detail="Danh sách prompt không được rỗng")

    task_ids = queue_manager.enqueue_batch(

        prompts=req.prompts,

        duration=req.duration,

        ratio=req.ratio,

        batch_ref_tag=req.batchRefTag or "",

        max_retries=req.maxRetries,

        timeout_minutes=req.timeoutMinutes,

    )

    from core.activity_log import record
    record(f"Hàng đợi: Đã thêm {len(task_ids)} video vào hàng đợi")
    return {"ok": True, "taskIds": task_ids, "count": len(task_ids)}


@app.get("/api/queue/jobs", tags=["Queue"])

def api_list_jobs(

    status: str = Query("Tất cả"),

    search: str = Query(""),

    page: int = Query(1, ge=1),

    pageSize: int = Query(10, ge=1, le=100),

    allRecords: bool = Query(True),

):

    """Liệt kê job có lọc theo trạng thái, tìm theo prompt / Task ID, phân trang (Mục 6.2 & 8.2)."""

    return queue_manager.list_jobs(status_filter=status, search=search, page=page, page_size=pageSize, all_records=allRecords)


class ProcessQueueRequest(BaseModel):

    concurrency: Optional[int] = Field(default=None, ge=1, le=20)


@app.post("/api/queue/process", tags=["Queue"])

async def api_process_queue(req: Optional[ProcessQueueRequest] = None):

    """Khởi động / tiếp tục dispatcher: gán job chờ cho session trống, chạy cuốn chiếu (Mục 5 & 8.2)."""

    if not account_pool.get_online_accounts():

        raise HTTPException(

            status_code=400,

            detail="Không còn tài khoản Online nào khả dụng! Hãy thêm tài khoản hoặc bật tài khoản trong Account Pool trước khi chạy (Phụ lục A).",

        )

    if req is not None and req.concurrency is not None:

        dispatcher.set_concurrency(req.concurrency)

    dispatcher.start()
    from core.activity_log import record
    record(f"Hàng đợi: Bắt đầu xử lý cuốn chiếu (luồng={dispatcher.concurrency})")

    return {"ok": True, "isRunning": True, "configuredConcurrency": dispatcher.concurrency,

            "effectiveConcurrency": dispatcher.get_effective_concurrency()}


@app.post("/api/queue/stop", tags=["Queue"])

async def api_stop_all():

    """Dừng gán mới và dừng job đang chạy → 'Đã dừng' (Mục 5 & 8.2)."""

    dispatcher.stop()

    return {"ok": True, "isRunning": False}


@app.post("/api/queue/retry/{job_id}", tags=["Queue"])

def api_retry_job(job_id: str):

    """Chạy lại một job (thất bại / timeout / đã dừng)."""

    ok = queue_manager.retry_job(job_id)

    if not ok:

        raise HTTPException(status_code=404, detail="Không tìm thấy job")

    # Nếu dispatcher đang chạy, nó sẽ tự động cuốn chiếu job này

    return {"ok": True, "id": job_id}


@app.post('/api/queue/rescan/{job_id}', tags=['Queue'])

async def api_rescan_thread(job_id: str):

    try:

        await dispatcher.rescan_thread(job_id)

    except KeyError:

        raise HTTPException(status_code=404, detail='Không tìm thấy record')

    except ValueError as error:

        raise HTTPException(status_code=409, detail=str(error))

    return {'ok': True, 'id': job_id}


@app.delete("/api/queue/jobs/{job_id}", tags=["Queue"])

def api_delete_job(job_id: str):

    """Xóa một job khỏi danh sách."""

    if job_id in dispatcher.active_tasks:

        task = dispatcher.active_tasks.pop(job_id)

        if hasattr(task, 'done') and not task.done():

            task.cancel()

    job = queue_manager.get_job(job_id)

    if job and job.account_id:

        acc = account_pool.accounts.get(job.account_id)

        if acc and acc.active_jobs > 0:

            acc.active_jobs -= 1

    ok = queue_manager.delete_job(job_id)

    if not ok:

        raise HTTPException(status_code=404, detail="Không tìm thấy job")

    account_pool.save()

    return {"ok": True, "id": job_id}



def _create_batch_download_response(job_ids: List[str]):
    if not job_ids:
        raise HTTPException(status_code=400, detail="Danh sách ID trống")
    video_files = []
    for jid in job_ids:
        f = MEDIA_DIR / f"{jid}.mp4"
        if f.exists() and f.is_file() and f.stat().st_size > 0:
            video_files.append((jid, f))
    if not video_files:
        raise HTTPException(status_code=404, detail="Không tìm thấy file video hoàn thành nào để tải về")
    if len(video_files) == 1:
        single_id, single_path = video_files[0]
        return FileResponse(
            path=str(single_path),
            media_type="video/mp4",
            filename=f"{single_id}.mp4"
        )
    import io, zipfile, datetime
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for jid, f_path in video_files:
            zf.write(f_path, arcname=f"{jid}.mp4")
    buf.seek(0)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"muse_videos_{timestamp}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'}
    )


@app.post("/api/queue/batch-delete", tags=["Queue"])
def api_batch_delete(req: BatchDeleteRequest):
    """Xóa nhiều job cùng lúc khỏi danh sách và dọn dẹp tài nguyên."""
    for job_id in req.job_ids:
        if job_id in dispatcher.active_tasks:
            task = dispatcher.active_tasks.pop(job_id)
            if hasattr(task, 'done') and not task.done():
                task.cancel()
        job = queue_manager.get_job(job_id)
        if job and job.account_id:
            acc = account_pool.accounts.get(job.account_id)
            if acc and acc.active_jobs > 0:
                acc.active_jobs -= 1
        for ext in ('.mp4', '_thumb.jpg', '_thumb.svg'):
            f = MEDIA_DIR / f"{job_id}{ext}"
            if f.exists():
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
    deleted_ids = queue_manager.delete_jobs(req.job_ids)
    account_pool.save()
    return {"ok": True, "deletedCount": len(deleted_ids), "deletedIds": deleted_ids}


@app.get("/api/queue/batch-download", tags=["Queue"])
def api_batch_download_get(ids: str = Query(..., description="Danh sách job ID phân cách bằng dấu phẩy")):
    """Tải nhiều video (hoặc 1 video) qua liên kết GET."""
    job_ids = [x.strip() for x in ids.split(",") if x.strip()]
    return _create_batch_download_response(job_ids)


@app.post("/api/queue/batch-download", tags=["Queue"])
def api_batch_download_post(req: BatchDownloadRequest):
    """Tải nhiều video qua yêu cầu POST."""
    return _create_batch_download_response(req.job_ids)


@app.post("/api/queue/clear-finished", tags=["Queue"])

def api_clear_finished():

    """Dọn toàn bộ job đã hoàn thành khỏi danh sách (Mục 6.2 & 8.2)."""

    cleared = queue_manager.clear_finished()

    return {"ok": True, "clearedCount": cleared}


@app.post("/api/queue/fail", tags=["Queue"])

def api_fail_job(req: FailJobRequest):

    """Worker báo job thất bại kèm lỗi (Mục 8.2)."""

    job = queue_manager.get_job(req.jobId)

    if not job:

        raise HTTPException(status_code=404, detail="Không tìm thấy job")

    job.status = "Thất bại"

    job.error = req.error

    job.error_code = req.errorCode or "WORKER_ERROR"

    queue_manager.save()

    return {"ok": True}


@app.post("/api/queue/complete", tags=["Queue"])

def api_complete_job(req: CompleteJobRequest):

    """Worker báo job hoàn thành kèm file / URL video và thumbnail (Mục 8.2)."""

    job = queue_manager.get_job(req.jobId)

    if not job:

        raise HTTPException(status_code=404, detail="Không tìm thấy job")

    job.status = "Hoàn thành"

    job.progress = 100

    job.video_url = req.videoUrl

    job.thumbnail_url = req.thumbnailUrl

    job.error = ""

    queue_manager.save()

    return {"ok": True}


# =========================================================================

# 8.3 Refs & Cấu hình — Kho ảnh và số luồng

# =========================================================================

class SetConcurrencyRequest(BaseModel):

    concurrency: int = Field(ge=1, le=20)


class SaveRefImageItem(BaseModel):

    tag: str

    filename: str

    contentBase64: Optional[str] = None


@app.post("/api/refs/upload", tags=["Refs"])

async def api_upload_ref_images(files: List[UploadFile] = File(...)):

    """Upload nhiều file trong một lần gọi; trả về từng file kèm tag tự sinh đề xuất, lỗi (Mục 8.3 & AC-04)."""

    results = []

    for f in files:

        content = await f.read()

        filename = f.filename or "image.png"

        is_ok, err = ref_library.validate_file(filename, len(content))

        suggested_tag = sanitize_tag(filename)


        if not is_ok:

            results.append({

                "filename": filename,

                "valid": False,

                "error": err,

                "suggestedTag": suggested_tag,

                "size": len(content),

            })

            continue


        # Tự động điều chỉnh tag nếu đã trùng trong kho

        base_tag = suggested_tag

        counter = 1

        while suggested_tag in ref_library.images:

            suggested_tag = f"{base_tag}-{counter}"

            counter += 1


        # Lưu file tạm thời vào bộ nhớ hoặc lưu luôn

        ok, save_err, item = ref_library.save_image(suggested_tag, filename, content)

        if ok and item:

            results.append({

                "filename": filename,

                "valid": True,

                "tag": item["tag"],

                "url": item["url"],

                "size": item["size"],

            })

        else:

            results.append({

                "filename": filename,

                "valid": False,

                "error": save_err,

                "suggestedTag": suggested_tag,

                "size": len(content),

            })


    return {"results": results, "savedCount": sum(1 for r in results if r.get("valid"))}


@app.get("/api/refs", tags=["Refs"])

def api_list_ref_images():

    """Toàn bộ ảnh trong kho: thumbnail, tên file, tag, dung lượng (Mục 8.3)."""

    return ref_library.list_ref_images()


@app.get("/api/refs/{tag}", tags=["Refs"])

def api_get_ref_image(tag: str):

    """Lấy đúng một ảnh theo tag (Mục 8.3 & 8.6)."""

    img = ref_library.get_ref_image(tag)

    if not img:

        raise HTTPException(status_code=404, detail=f"Không tìm thấy ảnh với tag @{tag}")

    return img


@app.get("/api/refs/{tag}/file", tags=["Refs"])

def api_get_ref_image_file(tag: str):

    """Trả về file ảnh trực tiếp."""

    path = ref_library.get_image_file_path(tag)

    if not path or not path.exists():

        raise HTTPException(status_code=404, detail="Tệp ảnh không tồn tại trên đĩa")

    return FileResponse(path)


@app.delete("/api/refs/{tag}", tags=["Refs"])

def api_delete_ref_image(tag: str):

    """Xóa một ảnh khỏi kho theo tag."""

    # Kiểm tra xem có job nào trong hàng đợi đang nhắc tới tag này không (Mục 3.3)

    referenced_jobs = [

        j.id for j in queue_manager.jobs.values()

        if j.status in ("Chờ", "Đang chạy") and tag in j.ref_tags

    ]

    warning = ""

    if referenced_jobs:

        warning = f"Cảnh báo: Có {len(referenced_jobs)} job đang chờ/chạy sử dụng tag @{tag} này!"


    ok = ref_library.delete_ref_image(tag)

    if not ok:

        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh để xóa")

    return {"ok": True, "tag": tag, "warning": warning}


@app.post("/api/config/concurrency", tags=["Config"])

async def api_set_concurrency(req: SetConcurrencyRequest):

    """Đặt số luồng song song toàn hệ thống (Mục 8.3)."""

    dispatcher.set_concurrency(req.concurrency)

    return {"ok": True, "concurrency": dispatcher.concurrency, "effective": dispatcher.get_effective_concurrency(),

            "concurrencyProtocol": 2}


# =========================================================================

# 8.4 Studio — Thẻ image-to-video

# =========================================================================

class AddStudioCardRequest(BaseModel):

    imageUrl: str

    prompt: Optional[str] = ""

    x: Optional[int] = None

    y: Optional[int] = None


class UpdateStudioCardRequest(BaseModel):

    prompt: Optional[str] = None

    x: Optional[int] = None

    y: Optional[int] = None

    imageUrl: Optional[str] = None

    status: Optional[str] = None


class GenerateAllStudioRequest(BaseModel):

    duration: int = 15

    ratio: str = "9:16"


@app.post("/api/studio/cards", tags=["Studio"])

def api_add_studio_card(req: AddStudioCardRequest):

    """Tạo thẻ mới trên canvas từ một ảnh đầu vào (Mục 7.2 & 8.4)."""

    card = flow_studio.add_card(

        image_url=req.imageUrl,

        prompt=req.prompt or "",

        x=req.x,

        y=req.y,

    )

    return {"ok": True, "card": card.to_dict()}


@app.patch("/api/studio/cards/{card_id}", tags=["Studio"])

def api_update_studio_card(card_id: str, req: UpdateStudioCardRequest):

    """Cập nhật prompt, vị trí kéo-thả, ảnh đầu vào của một thẻ (Mục 8.4)."""

    patch_data = {k: v for k, v in req.dict().items() if v is not None}

    card = flow_studio.update_card(card_id, patch_data)

    if not card:

        raise HTTPException(status_code=404, detail="Không tìm thấy thẻ canvas")

    return {"ok": True, "card": card.to_dict()}


@app.delete("/api/studio/cards/{card_id}", tags=["Studio"])

def api_delete_studio_card(card_id: str):

    """Xóa thẻ canvas."""

    ok = flow_studio.delete_card(card_id)

    if not ok:

        raise HTTPException(status_code=404, detail="Không tìm thấy thẻ canvas")

    return {"ok": True, "id": card_id}


@app.get("/api/studio/cards", tags=["Studio"])

def api_list_studio_cards():

    """Liệt kê toàn bộ thẻ canvas."""

    return flow_studio.list_cards()


@app.post("/api/studio/generate-all", tags=["Studio"])

async def api_generate_all_studio(req: GenerateAllStudioRequest):

    """Đưa mọi thẻ chưa tạo / bị lỗi vào dispatcher dùng chung (Mục 7.3 & 8.4)."""

    job_ids = flow_studio.generate_all_studio(duration=req.duration, ratio=req.ratio)

    if not job_ids:

        return {"ok": True, "message": "Không có thẻ nào cần tạo", "jobIds": []}

    # Tự động kích hoạt dispatcher nếu có tài khoản online

    if account_pool.get_online_accounts() and not dispatcher.is_running:

        dispatcher.start()

    return {"ok": True, "count": len(job_ids), "jobIds": job_ids}


# =========================================================================

# 8.5 Trạng thái tổng quan

# =========================================================================

@app.get("/api/state", tags=["State"])

def api_get_state():

    """Ảnh tổng quan trong một lần gọi theo Mục 8.5 của đặc tả.

    Bộ đếm đang chạy / chờ / xong, trạng thái Online, số ảnh trong kho, danh sách job đang chạy kèm tiến độ.

    """

    return dispatcher.get_state()


@app.delete('/api/logs', tags=['State'])

async def api_clear_logs():

    from core.activity_log import clear

    try:

        clear()

    except OSError:

        raise HTTPException(status_code=500, detail='Không thể xóa log đã lưu')

    return {'ok': True}


# =========================================================================

# Media serving endpoint

# =========================================================================

@app.get("/api/media/{filename}", tags=["Media"])

def api_get_media(filename: str):

    """Phục vụ file video MP4 và thumbnail trực tiếp cho player nhúng (Mục 6.3 & 6.5)."""

    file_path = MEDIA_DIR / filename

    if not file_path.exists():

        raise HTTPException(status_code=404, detail="File media không tồn tại")

    ext = file_path.suffix.lower()

    content_types = {

        ".mp4": "video/mp4",

        ".webm": "video/webm",

        ".jpg": "image/jpeg",

        ".jpeg": "image/jpeg",

        ".png": "image/png",

        ".webp": "image/webp",

        ".svg": "image/svg+xml",

    }

    media_type = content_types.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type)


# Phục vụ giao diện tĩnh

if STATIC_DIR.exists():

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":

    import multiprocessing

    import threading

    import time

    import webbrowser

    import uvicorn


    multiprocessing.freeze_support()


    print("=" * 70)

    print("             Muse ai tool - TOOL TAO VIDEO AI HANG LOAT")

    print("=" * 70)

    print("[+] May chu dang khoi dong tai: http://127.0.0.1:18610")

    print("[+] Trinh duyet se tu dong mo giao dien sau giay lat...")

    print("    (Vui long giu cua so nay chay trong suot qua trinh su dung tool)")

    print("=" * 70)


    def _auto_open_browser():

        time.sleep(1.2)

        try:

            webbrowser.open("http://127.0.0.1:18610")

        except Exception:

            pass


    threading.Thread(target=_auto_open_browser, daemon=True).start()


    uvicorn.run(app, host="127.0.0.1", port=18610, reload=False)
