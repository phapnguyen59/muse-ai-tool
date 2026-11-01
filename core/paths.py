"""Muse AI Tool - Centralized Path & Storage Management.

Manages application paths, persistent user data storage (%LOCALAPPDATA%/ToolMuse/data),
and handles seamless auto-migration from legacy relative data paths.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


# 1. BASE_DIR & BUNDLE_DIR (Application Code / Binaries)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = BASE_DIR

STATIC_DIR = BUNDLE_DIR / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"

BIN_DIR = BASE_DIR / "bin"


# 2. PERSISTENT DATA_DIR (User State, Accounts, Profiles, Media)
def get_default_data_dir() -> Path:
    """Trả về thư mục dữ liệu người dùng chuẩn hệ thống."""
    env_dir = os.environ.get("TOOL_MUSE_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return (Path(local_app_data) / "ToolMuse" / "data").resolve()

    return (Path.home() / ".toolmuse" / "data").resolve()


DATA_DIR = get_default_data_dir()
MEDIA_DIR = DATA_DIR / "media"
REFS_DIR = DATA_DIR / "refs"
PROFILES_DIR = DATA_DIR / "chrome_profiles"

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
JOBS_FILE = DATA_DIR / "jobs.json"
DISPATCHER_CONFIG_FILE = DATA_DIR / "dispatcher_config.json"
ACTIVITY_LOG_FILE = DATA_DIR / "activity_log.json"
STUDIO_FILE = DATA_DIR / "studio.json"
REFS_META_FILE = DATA_DIR / "refs.json"
DESKTOP_CONFIG_FILE = DATA_DIR / "desktop_config.json"


def _copy_tree_merge(src: Path, dst: Path):
    """Sao chép toàn bộ cây thư mục mà không ghi đè file mới hơn."""
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        target_root = dst / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_file = Path(root) / f
            dst_file = target_root / f
            if not dst_file.exists():
                try:
                    shutil.copy2(src_file, dst_file)
                except Exception:
                    pass


def _has_meaningful_data(directory: Path) -> bool:
    """Kiểm tra xem thư mục có chứa dữ liệu thực sự (tài khoản, profile, job...) hay không."""
    if not directory.is_dir():
        return False
    cand_accounts = directory / "accounts.json"
    if cand_accounts.is_file() and cand_accounts.stat().st_size > 50:
        return True
    profiles = directory / "chrome_profiles"
    if profiles.is_dir():
        try:
            if any(profiles.iterdir()):
                return True
        except Exception:
            pass
    cand_jobs = directory / "jobs.json"
    if cand_jobs.is_file() and cand_jobs.stat().st_size > 50:
        return True
    return False


def _check_and_migrate_legacy_data():
    """Tự động phát hiện và đồng bộ dữ liệu cũ từ các thư mục cài đặt/dev trước đây."""
    # Nếu DATA_DIR đã có accounts.json dung lượng > 50 bytes thì không cần migrate
    if ACCOUNTS_FILE.exists() and ACCOUNTS_FILE.stat().st_size > 50:
        return

    legacy_candidates = [
        BASE_DIR / "data",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MuseAITool" / "data",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tool Muse" / "data",
    ]

    for candidate in legacy_candidates:
        if not candidate.is_dir():
            continue
        try:
            if candidate.resolve() == DATA_DIR.resolve():
                continue
        except Exception:
            continue

        if _has_meaningful_data(candidate):
            try:
                print(f"[Storage] Found legacy data at {candidate}. Migrating to {DATA_DIR}...")
            except Exception:
                pass
            _copy_tree_merge(candidate, DATA_DIR)

            # Đồng bộ desktop_config.json nếu có
            cand_desktop_cfg = candidate.parent / "desktop_config.json"
            if cand_desktop_cfg.is_file() and not DESKTOP_CONFIG_FILE.exists():
                try:
                    shutil.copy2(cand_desktop_cfg, DESKTOP_CONFIG_FILE)
                except Exception:
                    pass

            try:
                print(f"[Storage] Migration to {DATA_DIR} completed successfully!")
            except Exception:
                pass
            break


def init_data_directory() -> Path:
    """Khởi tạo cấu trúc thư mục dữ liệu chuẩn và tự động migrate dữ liệu cũ."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    _check_and_migrate_legacy_data()

    return DATA_DIR
