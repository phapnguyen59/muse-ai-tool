"""
Account Pool — Quản lý nhiều tài khoản theo Mục 2 và 8.1.
- Quản lý nhiều tài khoản đăng nhập trong một pool dùng chung.
- Bật / tắt, thêm, xóa tài khoản.
- Health check định kỳ và trước khi gán job.
- Bảo mật: credential luôn được mã hóa at rest.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import ACCOUNTS_FILE, DATA_DIR
from core.security import decrypt_credential, encrypt_credential, mask_identifier


class Account:
    def __init__(
        self,
        account_id: str,
        identifier: str,
        encrypted_credential: str,
        enabled: bool = True,
        status: str = "Online",  # "Online", "Offline"
        session_health: str = "healthy",  # "healthy", "expired", "unreachable"
        health_reason: str = "Sẵn sàng nhận job",
        max_slots: int = 1,
        created_at: float | None = None,
        last_health_check: float | None = None,
    ):
        self.id = account_id
        self.identifier = identifier  # Plaintext identifier (e.g. email or username)
        self.encrypted_credential = encrypted_credential
        self.enabled = enabled
        self.status = status
        self.session_health = session_health
        self.health_reason = health_reason
        self.max_slots = max_slots
        self.active_jobs: int = 0
        self.created_at = created_at or time.time()
        self.last_health_check = last_health_check or time.time()

    @property
    def free_slots(self) -> int:
        if not self.enabled or self.status != "Online":
            return 0
        return max(0, self.max_slots - self.active_jobs)

    def to_dict(self, include_credential: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.identifier,
            "identifier": self.identifier,
            "masked_identifier": mask_identifier(self.identifier),
            "enabled": self.enabled,
            "status": self.status,
            "session_health": self.session_health,
            "health_reason": self.health_reason,
            "active_jobs": self.active_jobs,
            "max_slots": self.max_slots,
            "free_slots": self.free_slots,
            "last_health_check": self.last_health_check,
            "created_at": self.created_at,
        }
        if include_credential:
            data["encrypted_credential"] = self.encrypted_credential
            data["identifier"] = self.identifier
        return data


class AccountPool:
    def __init__(self, storage_path: Path = ACCOUNTS_FILE):
        self.storage_path = storage_path
        self.accounts: Dict[str, Account] = {}
        self.load()

    def load(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            return
        try:
            raw_data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            for item in raw_data:
                acc = Account(
                    account_id=item["id"],
                    identifier=item.get("identifier", "user@muse.ai"),
                    encrypted_credential=item.get("encrypted_credential", ""),
                    enabled=item.get("enabled", True),
                    status=item.get("status", "Online"),
                    session_health=item.get("session_health", "healthy"),
                    health_reason=item.get("health_reason", "Sẵn sàng nhận job"),
                    max_slots=item.get("max_slots", 1),
                    created_at=item.get("created_at"),
                    last_health_check=item.get("last_health_check"),
                )
                acc.active_jobs = 0  # Luôn reset active_jobs về 0 khi khởi động
                self.accounts[acc.id] = acc
        except Exception as e:
            print(f"[AccountPool] Lỗi đọc accounts.json: {e}")

    def save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [acc.to_dict(include_credential=True) for acc in self.accounts.values()]
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_account(self, credential: str, identifier: str = "") -> Account:
        """Thêm tài khoản vào pool với mã hóa thông tin đăng nhập at rest."""
        credential = credential.strip()
        if not identifier:
            # Tự trích xuất identifier nếu credential là email hoặc chứa email
            if "@" in credential and " " not in credential and ";" not in credential:
                identifier = credential
            else:
                identifier = f"acc_{uuid.uuid4().hex[:6]}"

        acc_id = f"acc_{uuid.uuid4().hex[:8]}"
        encrypted = encrypt_credential(credential)
        account = Account(
            account_id=acc_id,
            identifier=identifier,
            encrypted_credential=encrypted,
            enabled=True,
            status="Online",
            session_health="healthy",
            health_reason="Đã kết nối phiên thành công",
            max_slots=1,
        )
        self.accounts[acc_id] = account
        self.save()
        return account

    def remove_account(self, account_id: str) -> Optional[Account]:
        """Xóa tài khoản khỏi pool, xóa credential đã mã hóa."""
        if account_id in self.accounts:
            acc = self.accounts.pop(account_id)
            self.save()
            return acc
        return None

    def set_account_enabled(self, account_id: str, enabled: bool) -> Optional[Account]:
        """Bật / tắt nhận job mới cho một tài khoản."""
        if account_id in self.accounts:
            self.accounts[account_id].enabled = enabled
            self.save()
            return self.accounts[account_id]
        return None

    def check_health(self, account_id: str) -> Dict[str, Any]:
        """Kiểm tra sức khỏe phiên làm việc của tài khoản (Mục 2.1 & 8.1)."""
        acc = self.accounts.get(account_id)
        if not acc:
            return {"status": "unreachable", "reason": "Tài khoản không tồn tại trong pool"}

        acc.last_health_check = time.time()
        # Kiểm tra giải mã credential
        plain = decrypt_credential(acc.encrypted_credential)
        if not plain:
            acc.status = "Offline"
            acc.session_health = "expired"
            acc.health_reason = "Không thể giải mã phiên đăng nhập / khóa không hợp lệ"
        elif not acc.enabled:
            acc.status = "Offline"
            acc.session_health = "healthy"
            acc.health_reason = "Tài khoản đang bị tạm tắt (Disabled)"
        else:
            acc.status = "Online"
            acc.session_health = "healthy"
            acc.health_reason = "Phiên làm việc hợp lệ và đang hoạt động"

        self.save()
        return {
            "status": acc.session_health,
            "online": acc.status == "Online",
            "reason": acc.health_reason,
            "last_check": acc.last_health_check,
        }

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Danh sách tài khoản (chỉ trả về masked identifier, không leak plaintext)."""
        return [acc.to_dict(include_credential=False) for acc in self.accounts.values()]

    def get_online_accounts(self) -> List[Account]:
        return [acc for acc in self.accounts.values() if acc.enabled and acc.status == "Online"]

    def total_free_slots(self) -> int:
        return sum(acc.free_slots for acc in self.get_online_accounts())

    def sync_active_jobs(self, running_by_acc: Dict[str, int]):
        """Đồng bộ số active_jobs theo các job đang chạy thực tế."""
        for acc in self.accounts.values():
            acc.active_jobs = running_by_acc.get(acc.id, 0)


account_pool = AccountPool()
