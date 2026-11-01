"""Realtime Database licenses: check/register only when adding an account."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import uuid


LIMITS = {'free': 3, '10': 10, '50': 50, 'active': None}


class LicenseError(Exception):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def _windows_machine_guid():
    if sys.platform != 'win32':
        raise LicenseError('Chức năng mã máy hiện chỉ hỗ trợ Windows')
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, 'MachineGuid')
        identifier = uuid.UUID(str(value).strip())
        if identifier.int == 0:
            raise ValueError('Empty machine GUID')
        return identifier.hex
    except (OSError, ValueError, TypeError):
        raise LicenseError('Không đọc được mã định danh Windows; chưa thể thêm tài khoản') from None


@lru_cache(maxsize=1)
def get_machine_id():
    # The raw Windows GUID never leaves this machine and is not stored by the tool.
    digest = hashlib.sha256(('muse-ai-machine-v1:' + _windows_machine_guid()).encode('utf-8')).hexdigest().upper()
    return 'MUSE-' + '-'.join(digest[i:i + 4] for i in range(0, 16, 4))


def default_config_path():
    if getattr(sys, 'frozen', False):
        external = Path(sys.executable).resolve().parent / 'firebase_config.json'
        if external.is_file():
            return external
        return Path(getattr(sys, '_MEIPASS', external.parent)) / 'firebase_config.json'
    return Path(__file__).resolve().parent.parent / 'firebase_config.json'


@dataclass(frozen=True)
class LicenseDecision:
    machine_id: str
    status: str
    max_accounts: int | None
    checked_at: float

    def to_dict(self):
        return {'machineId': self.machine_id, 'status': self.status,
                'maxAccounts': self.max_accounts, 'checkedAt': self.checked_at}


class MachineLicense:
    def __init__(self, config_path=None):
        self.config_path = config_path
        self.last_check = None

    def database_url(self):
        database = os.environ.get('MUSE_FIREBASE_DATABASE_URL')
        if database is None:
            path = Path(self.config_path) if self.config_path is not None else default_config_path()
            try:
                config = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(config, dict):
                    raise ValueError('Invalid config')
                database = config.get('databaseURL', '')
            except FileNotFoundError:
                database = ''
            except (OSError, ValueError, TypeError):
                raise LicenseError('Không đọc được firebase_config.json; hãy kiểm tra cấu hình') from None
        if not isinstance(database, str):
            raise LicenseError('databaseURL Firebase phải là chuỗi')
        database = database.strip().rstrip('/')
        if database:
            parsed = urlparse(database)
            if (parsed.scheme != 'https' or parsed.netloc != parsed.hostname
                    or not parsed.hostname or not parsed.hostname.endswith(('.firebaseio.com', '.firebasedatabase.app'))
                    or parsed.path or parsed.query or parsed.fragment):
                raise LicenseError('URL Realtime Database không hợp lệ; cần URL HTTPS gốc của Firebase')
        return database

    def local_info(self):
        """This endpoint never contacts Firebase."""
        machine_id = get_machine_id()
        try:
            configured = bool(self.database_url())
            config_error = ''
        except LicenseError as error:
            configured, config_error = False, str(error)
        return {'machineId': machine_id, 'firebaseConfigured': configured,
                'configError': config_error,
                'lastCheck': self.last_check.to_dict() if self.last_check else None}

    def _request(self, url, method='GET', payload=None, headers=None):
        request = urllib.request.Request(url,
            data=json.dumps(payload).encode('utf-8') if payload is not None else None,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json', **(headers or {})}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('Oversized response')
            return json.loads(raw)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise LicenseError('Không tìm thấy Realtime Database; hãy kiểm tra databaseURL') from None
            if error.code in (401, 403):
                raise LicenseError('Firebase từ chối quyền đọc/tạo license; hãy publish database.rules.json trong Realtime Database Rules') from None
            if error.code == 412:
                raise LicenseError('License vừa được tạo hoặc cập nhật; vui lòng bấm thêm tài khoản lại') from None
            raise LicenseError('Firebase tạm thời không khả dụng; chưa thêm tài khoản') from None
        except (OSError, ValueError, urllib.error.URLError):
            raise LicenseError('Không kết nối được Firebase hoặc phản hồi không hợp lệ; chưa thêm tài khoản') from None

    def check(self):
        database = self.database_url()
        if not database:
            raise LicenseError('Chưa cấu hình Firebase: điền databaseURL trong firebase_config.json trước khi thêm tài khoản')
        machine_id = get_machine_id()
        url = f'{database}/licenses/{machine_id}.json'
        document = self._request(url)
        if document is None:
            document = self._request(url, method='PUT', payload={
                'machine_id': machine_id, 'status': 'free',
                'created_at': int(time.time() * 1000), 'app': 'Muse AI Tool',
            }, headers={'If-Match': 'null_etag'})
        status = document.get('status') if isinstance(document, dict) else None
        if not isinstance(status, str) or status not in LIMITS:
            raise LicenseError('Status Firebase không hợp lệ; chỉ nhận free, 10, 50, active (kiểu string)', 403) from None
        decision = LicenseDecision(machine_id, status, LIMITS[status], time.time())
        self.last_check = decision
        return decision


machine_license = MachineLicense()
