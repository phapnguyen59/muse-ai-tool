"""
Kho ảnh tham chiếu (Reference Library) theo Mục 3 và 8.3 của đặc tả.
- Upload nhiều ảnh trong một lần (PNG, JPG/JPEG, WebP; tối đa 8 MB/file).
- Tự sinh tag từ tên file ([a-z0-9-_]), cho phép sửa tag, cảnh báo tag trùng / sai định dạng.
- Quản lý kho, tra cứu bằng @tag để worker resolve vào job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.paths import DATA_DIR, REFS_DIR, REFS_META_FILE
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8 MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def sanitize_tag(filename: str) -> str:
    """Tự sinh tag từ tên file (Mục 3.2.4).
    Ví dụ: 'Santa Claus.png' -> 'santa-claus', 'X07.jpg' -> 'x07'.
    """
    stem = Path(filename).stem
    # Chuyển thường
    tag = stem.lower()
    # Chuyển khoảng trắng thành gạch ngang
    tag = re.sub(r"[\s_]+", "-", tag)
    # Giữ lại chỉ ký tự [a-z0-9-]
    tag = re.sub(r"[^a-z0-9-]", "", tag)
    tag = tag.strip("-")
    return tag or "ref"


def is_valid_tag(tag: str) -> bool:
    """Kiểm tra tag hợp lệ [a-z0-9-_]."""
    if not tag:
        return False
    return bool(re.match(r"^[a-z0-9-_]+$", tag))


class RefLibrary:
    def __init__(self, refs_dir: Path = REFS_DIR, meta_file: Path = REFS_META_FILE):
        self.refs_dir = refs_dir
        self.meta_file = meta_file
        self.images: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        if not self.meta_file.exists():
            return
        try:
            self.images = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[RefLibrary] Lỗi đọc refs.json: {e}")

    def save(self):
        self.meta_file.parent.mkdir(parents=True, exist_ok=True)
        self.meta_file.write_text(json.dumps(self.images, ensure_ascii=False, indent=2), encoding="utf-8")

    def validate_file(self, filename: str, file_size: int) -> Tuple[bool, str]:
        """Kiểm tra tính hợp lệ của từng file riêng lẻ (Mục 3.2.2)."""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"Định dạng {ext} không được hỗ trợ (chỉ nhận PNG, JPG, JPEG, WebP)"
        if file_size > MAX_FILE_SIZE:
            mb = round(file_size / (1024 * 1024), 2)
            return False, f"Dung lượng {mb} MB vượt quá giới hạn tối đa 8 MB"
        return True, ""

    def save_image(self, tag: str, filename: str, content: bytes) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Lưu một ảnh vào kho với tag chỉ định."""
        tag = tag.strip().lower()
        if not is_valid_tag(tag):
            return False, f"Tag '@{tag}' không hợp lệ (chỉ chấp nhận ký tự thường a-z, 0-9, dấu gạch)", None

        if tag in self.images:
            return False, f"Tag '@{tag}' đã tồn tại trong kho ảnh tham chiếu", None

        is_ok, err = self.validate_file(filename, len(content))
        if not is_ok:
            return False, err, None

        ext = Path(filename).suffix.lower()
        stored_filename = f"{tag}{ext}"
        target_path = self.refs_dir / stored_filename
        target_path.write_bytes(content)

        item = {
            "tag": tag,
            "filename": filename,
            "stored_filename": stored_filename,
            "url": f"/api/refs/{tag}/file",
            "size": len(content),
            "size_kb": round(len(content) / 1024, 1),
            "created_at": time.time(),
        }
        self.images[tag] = item
        self.save()
        return True, "", item

    def get_ref_image(self, tag: str) -> Optional[Dict[str, Any]]:
        """Lấy đúng một ảnh theo tag — worker dùng khi resolve @tag (Mục 8.3 & 8.6)."""
        tag = tag.strip().lower()
        if tag.startswith("@"):
            tag = tag[1:]
        return self.images.get(tag)

    def get_image_file_path(self, tag: str) -> Optional[Path]:
        img = self.get_ref_image(tag)
        if not img:
            return None
        p = self.refs_dir / img["stored_filename"]
        return p if p.exists() else None

    def list_ref_images(self) -> List[Dict[str, Any]]:
        """Toàn bộ ảnh trong kho: thumbnail, tên file, tag, dung lượng."""
        return sorted(list(self.images.values()), key=lambda x: x.get("created_at", 0), reverse=True)

    def delete_ref_image(self, tag: str) -> bool:
        """Xóa một ảnh khỏi kho theo tag."""
        tag = tag.strip().lower()
        if tag.startswith("@"):
            tag = tag[1:]
        if tag in self.images:
            item = self.images.pop(tag)
            path = self.refs_dir / item.get("stored_filename", "")
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
            self.save()
            return True
        return False


ref_library = RefLibrary()
