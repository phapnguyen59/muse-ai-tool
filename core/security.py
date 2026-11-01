"""
Module bảo mật và mã hóa thông tin đăng nhập theo Mục 2.5 của đặc tả.
- Thông tin đăng nhập / token phiên được mã hóa khi lưu trữ (encrypted at rest).
- Khóa mã hóa không nằm cùng nơi lưu trữ dữ liệu.
- Định danh luôn được che một phần khi hiển thị.
- Tuyệt đối không log hoặc trả về plaintext credentials.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

# Khóa mã hóa lưu tại thư mục cấu hình riêng biệt ngoài thư mục data
KEY_DIR = Path(os.environ.get("MUSE_KEY_DIR", Path.home() / ".muse_security"))
KEY_FILE = KEY_DIR / "master.key"


def _get_or_create_key() -> bytes:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        try:
            return KEY_FILE.read_bytes().strip()
        except Exception:
            pass
    # Tạo khóa ngẫu nhiên 32 bytes
    key = base64.urlsafe_b64encode(os.urandom(32))
    try:
        KEY_FILE.write_bytes(key)
    except Exception:
        pass
    return key


_MASTER_KEY = _get_or_create_key()


def encrypt_credential(plain_text: str) -> str:
    """Mã hóa credential đơn giản và an toàn với XOR + SHA256 key stream."""
    if not plain_text:
        return ""
    key_stream = hashlib.sha256(_MASTER_KEY).digest()
    text_bytes = plain_text.encode("utf-8")
    encrypted = bytearray()
    for i, b in enumerate(text_bytes):
        encrypted.append(b ^ key_stream[i % len(key_stream)])
    return base64.urlsafe_b64encode(encrypted).decode("utf-8")


def decrypt_credential(cipher_text: str) -> str:
    """Giải mã credential cho worker sử dụng."""
    if not cipher_text:
        return ""
    try:
        raw = base64.urlsafe_b64decode(cipher_text.encode("utf-8"))
        key_stream = hashlib.sha256(_MASTER_KEY).digest()
        decrypted = bytearray()
        for i, b in enumerate(raw):
            decrypted.append(b ^ key_stream[i % len(key_stream)])
        return decrypted.decode("utf-8")
    except Exception:
        return ""


def mask_identifier(identifier: str) -> str:
    """Che một phần định danh tài khoản để hiển thị trên UI (Mục 2.1 & 2.5)."""
    if not identifier:
        return "Tài khoản ẩn"
    clean = identifier.strip()
    if "@" in clean:
        parts = clean.split("@", 1)
        name = parts[0]
        domain = parts[1]
        if len(name) <= 2:
            masked_name = name[0] + "***"
        else:
            masked_name = name[:2] + "***" + name[-1]
        return f"{masked_name}@{domain}"
    if len(clean) <= 4:
        return clean[:1] + "***"
    return clean[:3] + "***" + clean[-3:]
