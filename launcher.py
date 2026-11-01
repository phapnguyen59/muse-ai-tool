"""Muse AI Tool - Dedicated Application Launcher.

Handles environment initialization, Python 64-bit auto-detection / offline install,
and launches the native desktop dashboard without terminal windows.
"""
import ctypes
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

APP_TITLE = "Tool Muse"
PORT = 18610
SERVER_URL = f"http://127.0.0.1:{PORT}"
HEALTH_URL = f"{SERVER_URL}/api/state"


def sync_firebase_on_launch(base_dir: str):
    """Đăng ký mã máy ngay lập tức lên Firebase ngay khi người dùng mở launcher."""
    try:
        import hashlib, uuid, winreg, json
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography', 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            val, _ = winreg.QueryValueEx(key, 'MachineGuid')
        guid = uuid.UUID(str(val).strip()).hex
        digest = hashlib.sha256(('muse-ai-machine-v1:' + guid).encode('utf-8')).hexdigest().upper()
        mid = 'MUSE-' + '-'.join(digest[i:i + 4] for i in range(0, 16, 4))

        cfg_file = os.path.join(base_dir, "firebase_config.json")
        if os.path.isfile(cfg_file):
            with open(cfg_file, "r", encoding="utf-8-sig") as f:
                db_url = json.load(f).get("databaseURL", "").rstrip("/")
            if db_url:
                url = f"{db_url}/licenses/{mid}.json"
                req = urllib.request.Request(url, headers={"User-Agent": "ToolMuse/1.0"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    raw = resp.read().decode("utf-8") or "null"
                    doc = json.loads(raw)
                if doc is None:
                    payload = json.dumps({
                        "machine_id": mid,
                        "status": "free",
                        "created_at": int(time.time() * 1000),
                        "app": "Muse AI Tool"
                    }).encode("utf-8")
                    put_req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "If-Match": "null_etag"}, method="PUT")
                    urllib.request.urlopen(put_req, timeout=4.0)
    except Exception:
        pass


def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def wait_for_server(timeout: int = 30) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "ToolMuseLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def check_python_compatibility(exe_path: str) -> tuple[bool, str]:
    """Kiểm tra xem python.exe có phải là Python 64-bit và phiên bản tương thích (3.10 - 3.12) không."""
    if not exe_path or not os.path.isfile(exe_path):
        return False, "File không tồn tại"
    if "windowsapps" in os.path.abspath(exe_path).lower():
        return False, "WindowsApps redirector stub"
    try:
        code = (
            "import sys, platform; "
            "is_64 = sys.maxsize > 2**32; "
            "v = sys.version_info; "
            "supported = is_64 and (v.major == 3 and 10 <= v.minor <= 12); "
            "import venv; "
            "print(f'{supported}|{v.major}.{v.minor}.{v.micro}|{platform.architecture()[0]}')"
        )
        res = subprocess.run(
            [exe_path, "-c", code],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            if out.startswith("True|"):
                return True, out.split("|", 1)[1]
            return False, f"Không tương thích ({out})"
        return False, f"Chạy thử lỗi: {res.stderr[:80]}"
    except Exception as e:
        return False, str(e)


def get_compatible_python(base_dir: str) -> tuple[str, str]:
    """Tìm Python 64-bit tương thích (3.10 - 3.12) trên hệ thống."""
    venv_py = os.path.join(base_dir, ".venv", "Scripts", "python.exe")
    ok, info = check_python_compatibility(venv_py)
    if ok:
        return venv_py, f"Môi trường .venv ({info})"

    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        for ver in ["Python312", "Python311", "Python310"]:
            candidates.append(os.path.join(local_app_data, "Programs", "Python", ver, "python.exe"))

    for pf in [os.environ.get("ProgramFiles", "C:\\Program Files"), os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")]:
        for ver in ["Python312", "Python311", "Python310"]:
            candidates.append(os.path.join(pf, "Python", ver, "python.exe"))
            candidates.append(os.path.join(pf, ver, "python.exe"))

    for cand in candidates:
        ok, info = check_python_compatibility(cand)
        if ok:
            return cand, f"Python hệ thống ({info})"

    for cmd in ["python", "py", "python3"]:
        cand = shutil.which(cmd)
        if cand:
            ok, info = check_python_compatibility(cand)
            if ok:
                return cand, f"PATH {cmd} ({info})"

    return "", "Không tìm thấy Python tương thích"


def install_python_environment(base_dir: str) -> str:
    print("\n" + "=" * 68)
    print(" [THÔNG BÁO] Cài đặt môi trường Python 3.12 (64-bit) chuẩn cho ứng dụng")
    print("=" * 68)
    print(" Ứng dụng yêu cầu Python 3.12 64-bit để vận hành mượt mà.")
    print(" Đang tiến hành cài đặt tự động vào máy...\n")

    bundled_installer = os.path.join(base_dir, "redist", "python-3.12.10-amd64.exe")
    installer_path = None

    if os.path.isfile(bundled_installer) and os.path.getsize(bundled_installer) > 20 * 1024 * 1024:
        print("[*] Sử dụng bộ cài Python 3.12 64-bit đính kèm sẵn trong app...", flush=True)
        installer_path = bundled_installer
    else:
        import tempfile
        temp_installer = os.path.join(tempfile.gettempdir(), "python-3.12.10-amd64.exe")
        if os.path.isfile(temp_installer) and os.path.getsize(temp_installer) > 20 * 1024 * 1024:
            print("[*] Đã có sẵn bộ cài Python trong bộ nhớ tạm.", flush=True)
            installer_path = temp_installer
        else:
            print("[*] Đang tải bộ cài Python 3.12 64-bit chính thức (~26MB)...", flush=True)
            url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
            try:
                def progress(count, block_size, total_size):
                    if total_size > 0:
                        percent = min(100, int(count * block_size * 100 / total_size))
                        bar = ("#" * (percent // 4)).ljust(25, "-")
                        sys.stdout.write(f"\r    [{bar}] {percent}%")
                        sys.stdout.flush()

                urllib.request.urlretrieve(url, temp_installer, reporthook=progress)
                print("\n[*] Tải hoàn tất!", flush=True)
                installer_path = temp_installer
            except Exception as e:
                print(f"\n[LỖI] Không thể tải Python 3.12: {e}")
                return ""

    if not installer_path:
        return ""

    print("[*] Đang tự động cài đặt Python 3.12 ngầm (vui lòng chờ khoảng 20-30 giây)...", flush=True)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    target_dir = os.path.join(local_app_data, "Programs", "Python", "Python312") if local_app_data else ""
    cmd = [
        installer_path,
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_pip=1",
        "Include_test=0",
        "Include_launcher=0",
        "SimpleInstall=1"
    ]
    if target_dir:
        cmd.append(f"TargetDir={target_dir}")

    res = subprocess.run(cmd, timeout=300)
    if res.returncode == 0:
        print("[✓] Cài đặt Python 3.12 thành công!", flush=True)
        if target_dir:
            cand = os.path.join(target_dir, "python.exe")
            ok, info = check_python_compatibility(cand)
            if ok:
                py_dir = os.path.dirname(cand)
                scripts_dir = os.path.join(py_dir, "Scripts")
                os.environ["PATH"] = f"{py_dir};{scripts_dir};" + os.environ.get("PATH", "")
                return cand

        py, _ = get_compatible_python(base_dir)
        if py:
            return py
    else:
        print(f"[!] Quá trình cài đặt Python trả về mã: {res.returncode}")

    return ""


def ensure_environment(base_dir: str, python_exe: str):
    venv_dir = os.path.join(base_dir, ".venv")
    venv_py = os.path.join(venv_dir, "Scripts", "python.exe")

    if not os.path.isfile(venv_py):
        print("[1/2] Đang khởi tạo môi trường ảo Python (.venv)...", flush=True)
        res = subprocess.run([python_exe, "-m", "venv", venv_dir], cwd=base_dir)
        if res.returncode != 0:
            print("[LỖI] Không thể tạo virtual environment (.venv)!", flush=True)
            input("Nhấn Enter để thoát...")
            sys.exit(1)

    check_code = "import fastapi, uvicorn, websockets, pydantic, cryptography, multipart, PIL"
    res = subprocess.run([venv_py, "-c", check_code], cwd=base_dir, capture_output=True)
    if res.returncode != 0:
        req_file = os.path.join(base_dir, "requirements.txt")
        if os.path.isfile(req_file):
            print("[2/2] Đang cài đặt thư viện cần thiết (requirements.txt)...", flush=True)
            print("      (Quá trình này chỉ mất 1-2 phút trong lần khởi động đầu tiên)", flush=True)
            subprocess.run([venv_py, "-m", "pip", "install", "--upgrade", "pip"], cwd=base_dir, capture_output=True)
            pip_res = subprocess.run([venv_py, "-m", "pip", "install", "-r", req_file], cwd=base_dir)
            if pip_res.returncode != 0:
                print("\n[CẢNH BÁO] Cài đặt thư viện có thể chưa hoàn tất. Đang tiếp tục thử khởi chạy...")
        print("[✓] Đã hoàn tất cài đặt toàn bộ môi trường và thư viện!\n", flush=True)


def main():
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    os.chdir(base_dir)

    # Đăng ký ngay mã máy lên Firebase trong nền
    sync_firebase_on_launch(base_dir)

    desktop_script = os.path.join(base_dir, "desktop.py")
    venv_pythonw = os.path.join(base_dir, ".venv", "Scripts", "pythonw.exe")
    venv_py = os.path.join(base_dir, ".venv", "Scripts", "python.exe")

    # 1. TRƯỜNG HỢP BÌNH THƯỜNG (Môi trường đã sẵn sàng):
    run_py = venv_pythonw if os.path.isfile(venv_pythonw) else (venv_py if os.path.isfile(venv_py) else "")
    if run_py and os.path.isfile(desktop_script):
        ok, _ = check_python_compatibility(run_py)
        if ok:
            check_py = venv_py if os.path.isfile(venv_py) else run_py
            check_code = "import fastapi, uvicorn, websockets, pydantic, cryptography, multipart, PIL"
            pkg_res = subprocess.run([check_py, "-c", check_code], cwd=base_dir, capture_output=True)
            if pkg_res.returncode == 0:
                subprocess.Popen([run_py, desktop_script], cwd=base_dir)
                sys.exit(0)

    # 2. TRƯỜNG HỢP LẦN ĐẦU (Chưa có .venv hoặc máy mới):
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.AllocConsole()
            os.system("title " + APP_TITLE + " - Thiet lap lan dau")
            os.system("color 0b")
            subprocess.run(["chcp", "65001"], shell=True, capture_output=True)
        except Exception:
            pass

    print("=" * 68)
    print("         TOOL MUSE - THIET LAP MOI TRUONG LAN DAU TIEN")
    print("=" * 68)

    py_exe, info = get_compatible_python(base_dir)
    if py_exe:
        print(f"[*] Sử dụng: {info}", flush=True)
    else:
        print(f"[*] {info}. Tiến hành chuẩn bị môi trường Python 3.12 (64-bit)...", flush=True)
        py_exe = install_python_environment(base_dir)
        if not py_exe:
            print("\n[LỖI] Không thể chuẩn bị môi trường Python 3.12 (64-bit)!")
            print("Vui lòng tải và cài đặt Python 3.12 (64-bit) từ: https://www.python.org/downloads/")
            input("\nNhấn phím Enter để thoát...")
            sys.exit(1)

    ensure_environment(base_dir, py_exe)

    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
    app_data_dir = os.path.join(local_app_data, "ToolMuse", "data")
    os.makedirs(os.path.join(app_data_dir, "media"), exist_ok=True)
    os.makedirs(os.path.join(app_data_dir, "refs"), exist_ok=True)

    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass

    run_py = venv_pythonw if os.path.isfile(venv_pythonw) else (venv_py if os.path.isfile(venv_py) else py_exe)
    if os.path.isfile(desktop_script):
        subprocess.Popen([run_py, desktop_script], cwd=base_dir)
        sys.exit(0)
    else:
        webbrowser.open(SERVER_URL)


if __name__ == "__main__":
    main()
