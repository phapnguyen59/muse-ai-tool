"""Muse AI Tool - Server Control Panel & Launcher.

Runs the Muse AI Tool backend server and provides a native desktop dashboard
with web access links (Local & LAN), quick browser launch, and live logs.
"""
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

# Bắt buộc đặt AppUserModelID riêng biệt để Windows gán đúng App Icon cho Taskbar
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MuseAI.ToolMuse.Server.1.0")
    except Exception:
        pass

APP_TITLE = "Tool Muse - Máy Chủ Server"
PORT = 18610
SERVER_URL = f"http://127.0.0.1:{PORT}"
HEALTH_URL = f"{SERVER_URL}/api/state"
CONFIG_FILE = "desktop_config.json"
from core.paths import (
    DESKTOP_CONFIG_FILE,
    MEDIA_DIR,
    init_data_directory,
)


def get_version(base_dir: str) -> str:
    ver_file = os.path.join(base_dir, "VERSION")
    if os.path.isfile(ver_file):
        try:
            with open(ver_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return "1.0.2"


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


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
            req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "ToolMuseServerPanel/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def load_config(base_dir: str = "") -> dict:
    if DESKTOP_CONFIG_FILE.is_file():
        try:
            with open(DESKTOP_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if base_dir:
        old_path = os.path.join(base_dir, CONFIG_FILE)
        if os.path.isfile(old_path):
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {"auto_open_browser": True}


def save_config(base_dir: str, cfg: dict):
    try:
        DESKTOP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DESKTOP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def kill_process_on_port(port: int):
    if sys.platform == "win32":
        try:
            out = subprocess.check_output("netstat -ano -p tcp", shell=True, text=True)
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                    pid = parts[4]
                    if pid and pid != "0":
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                        time.sleep(0.4)
        except Exception:
            pass


class ServerApp(tk.Tk):
    def __init__(self, base_dir: str):
        super().__init__()
        init_data_directory()
        self.base_dir = base_dir
        self.version = get_version(base_dir)
        self.config_data = load_config(base_dir)
        self.lan_ip = get_local_ip()
        self.lan_url = f"http://{self.lan_ip}:{PORT}" if self.lan_ip != "127.0.0.1" else ""
        self.server_proc = None
        self.is_shutting_down = False

        try:
            from core.machine_license import get_machine_id
            self.machine_id = get_machine_id()
        except Exception:
            self.machine_id = "MUSE-UNKNOWN"

        self.title(f"{APP_TITLE} v{self.version}")
        self.geometry("860x670")
        self.minsize(720, 540)
        self.configure(bg="#13151f")

        icon_path = os.path.join(base_dir, "app_icon.ico")
        if os.path.isfile(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self._init_styles()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.last_log_id = 0
        self.after(300, self.start_server_thread)
        self.after(600, self._start_log_poller)

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background="#13151f", foreground="#f1f5f9")
        style.configure("TFrame", background="#13151f")
        style.configure("Card.TFrame", background="#1e2132", relief="flat")
        style.configure("TLabel", background="#13151f", foreground="#f1f5f9", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#1e2132", foreground="#f1f5f9", font=("Segoe UI", 10))
        style.configure("Header.TLabel", background="#13151f", foreground="#ffffff", font=("Segoe UI", 15, "bold"))
        style.configure("SubHeader.TLabel", background="#13151f", foreground="#94a3b8", font=("Segoe UI", 10))
        style.configure("Url.TLabel", background="#1e2132", foreground="#38bdf8", font=("Consolas", 12, "bold"))

        style.configure("TCheckbutton", background="#13151f", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#13151f")])

        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background="#6366f1", foreground="#ffffff", padding=(12, 6))
        style.map("Primary.TButton",
                  background=[("active", "#4f46e5"), ("pressed", "#4338ca"), ("disabled", "#334155")],
                  foreground=[("disabled", "#64748b")])

        style.configure("Secondary.TButton", font=("Segoe UI", 9), background="#2d3148", foreground="#e2e8f0", padding=(8, 4))
        style.map("Secondary.TButton",
                  background=[("active", "#3d4263"), ("pressed", "#1e2132"), ("disabled", "#222638")],
                  foreground=[("disabled", "#64748b")])

        style.configure("Danger.TButton", font=("Segoe UI", 9), background="#dc2626", foreground="#ffffff", padding=(8, 4))
        style.map("Danger.TButton", background=[("active", "#b91c1c")])

        style.configure("Success.TButton", font=("Segoe UI", 10, "bold"), background="#10b981", foreground="#ffffff", padding=(12, 6))
        style.map("Success.TButton", background=[("active", "#059669")])

    def _build_ui(self):
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=20, pady=(16, 12))

        title_box = ttk.Frame(header_frame)
        title_box.pack(side="left")

        lbl_title = ttk.Label(title_box, text="🎬 TOOL MUSE - MÁY CHỦ DỊCH VỤ", style="Header.TLabel")
        lbl_title.pack(anchor="w")

        lbl_sub = ttk.Label(title_box, text=f"Hệ thống tạo video Muse AI hàng loạt • Phiên bản v{self.version}", style="SubHeader.TLabel")
        lbl_sub.pack(anchor="w", pady=(2, 0))

        self.status_frame = tk.Frame(header_frame, bg="#27273a", padx=12, pady=6, highlightbackground="#3f3f5a", highlightthickness=1)
        self.status_frame.pack(side="right")

        self.status_dot = tk.Label(self.status_frame, text="●", fg="#f59e0b", bg="#27273a", font=("Segoe UI", 12))
        self.status_dot.pack(side="left", padx=(0, 6))

        self.status_text = tk.Label(self.status_frame, text="Đang khởi động...", fg="#f59e0b", bg="#27273a", font=("Segoe UI", 10, "bold"))
        self.status_text.pack(side="left")

        card = tk.Frame(self, bg="#1e2132", padx=18, pady=14, highlightbackground="#2e344d", highlightthickness=1)
        card.pack(fill="x", padx=20, pady=(0, 12))

        card_title = tk.Label(card, text="THÔNG TIN HỆ THỐNG & ĐƯỜNG DẪN TRUY CẬP (SYSTEM & ACCESS URL)", fg="#94a3b8", bg="#1e2132", font=("Segoe UI", 9, "bold"))
        card_title.pack(anchor="w", pady=(0, 8))

        # Row 1: Local URL
        row1 = tk.Frame(card, bg="#1e2132")
        row1.pack(fill="x", pady=2)

        lbl_local = tk.Label(row1, text="Máy này (Local):", fg="#cbd5e1", bg="#1e2132", width=18, anchor="w", font=("Segoe UI", 10))
        lbl_local.pack(side="left")

        self.entry_local = tk.Entry(row1, font=("Consolas", 11, "bold"), fg="#38bdf8", bg="#13151f", insertbackground="#38bdf8", relief="flat", highlightbackground="#3b4261", highlightthickness=1)
        self.entry_local.insert(0, SERVER_URL)
        self.entry_local.configure(state="readonly")
        self.entry_local.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=3)

        btn_open = ttk.Button(row1, text="🌐 Mở Web ngay", style="Primary.TButton", command=self.open_in_browser)
        btn_open.pack(side="left", padx=(0, 6))

        btn_copy_local = ttk.Button(row1, text="📋 Copy", style="Secondary.TButton", command=lambda: self.copy_to_clipboard(SERVER_URL))
        btn_copy_local.pack(side="left")

        # Row 2: LAN URL
        if self.lan_url:
            row2 = tk.Frame(card, bg="#1e2132")
            row2.pack(fill="x", pady=4)

            lbl_lan = tk.Label(row2, text="Mạng LAN / WiFi:", fg="#cbd5e1", bg="#1e2132", width=18, anchor="w", font=("Segoe UI", 10))
            lbl_lan.pack(side="left")

            self.entry_lan = tk.Entry(row2, font=("Consolas", 10), fg="#a5b4fc", bg="#13151f", insertbackground="#a5b4fc", relief="flat", highlightbackground="#3b4261", highlightthickness=1)
            self.entry_lan.insert(0, self.lan_url)
            self.entry_lan.configure(state="readonly")
            self.entry_lan.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=2)

            btn_copy_lan = ttk.Button(row2, text="📋 Copy", style="Secondary.TButton", command=lambda: self.copy_to_clipboard(self.lan_url))
            btn_copy_lan.pack(side="left")

        # Row 3: Mã máy Firebase
        row3 = tk.Frame(card, bg="#1e2132")
        row3.pack(fill="x", pady=4)

        lbl_mid = tk.Label(row3, text="Mã máy (Firebase):", fg="#cbd5e1", bg="#1e2132", width=18, anchor="w", font=("Segoe UI", 10))
        lbl_mid.pack(side="left")

        self.entry_mid = tk.Entry(row3, font=("Consolas", 10, "bold"), fg="#ec4899", bg="#13151f", insertbackground="#ec4899", relief="flat", highlightbackground="#3b4261", highlightthickness=1)
        self.entry_mid.insert(0, self.machine_id)
        self.entry_mid.configure(state="readonly")
        self.entry_mid.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=2)

        btn_copy_mid = ttk.Button(row3, text="📋 Copy", style="Secondary.TButton", command=lambda: self.copy_to_clipboard(self.machine_id))
        btn_copy_mid.pack(side="left")

        # Toolbar Frame
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=20, pady=(0, 10))

        self.auto_open_var = tk.BooleanVar(value=self.config_data.get("auto_open_browser", True))
        chk_auto = ttk.Checkbutton(toolbar, text="Tự động mở trình duyệt web khi khởi chạy",
                                   variable=self.auto_open_var, command=self.on_toggle_auto_open)
        chk_auto.pack(side="left")

        btn_open_downloads = ttk.Button(toolbar, text="📁 Thư mục Video", style="Secondary.TButton", command=self.open_downloads_folder)
        btn_open_downloads.pack(side="right", padx=(6, 0))

        self.btn_restart = ttk.Button(toolbar, text="🔄 Khởi động lại Server", style="Secondary.TButton", command=self.restart_server)
        self.btn_restart.pack(side="right", padx=(6, 0))

        self.btn_toggle_server = ttk.Button(toolbar, text="⏹ Dừng Server", style="Secondary.TButton", command=self.toggle_server)
        self.btn_toggle_server.pack(side="right")

        # Logs Frame
        log_header = ttk.Frame(self)
        log_header.pack(fill="x", padx=20, pady=(0, 4))

        lbl_log = ttk.Label(log_header, text="NHẬT KÝ MÁY CHỦ (SERVER LOGS):", font=("Segoe UI", 9, "bold"), foreground="#94a3b8")
        lbl_log.pack(side="left")

        btn_clear_log = ttk.Button(log_header, text="Xóa log", style="Secondary.TButton", command=self.clear_logs)
        btn_clear_log.pack(side="right")

        self.log_text = ScrolledText(
            self,
            bg="#0f111a",
            fg="#cbd5e1",
            insertbackground="#cbd5e1",
            font=("Consolas", 9),
            relief="flat",
            highlightbackground="#23273a",
            highlightthickness=1,
            padx=10,
            pady=8,
            wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self.toast_label = tk.Label(self, text="", fg="#10b981", bg="#13151f", font=("Segoe UI", 9, "bold"))
        self.toast_label.pack(side="bottom", anchor="w", padx=20, pady=(0, 4))

    def log(self, message: str):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.after(0, _append)

    def clear_logs(self):
        self.log_text.delete("1.0", tk.END)

    def set_status(self, text: str, state: str = "warning"):
        colors = {
            "online": ("#10b981", "#10b981", "🟢"),
            "warning": ("#f59e0b", "#f59e0b", "🟡"),
            "offline": ("#ef4444", "#ef4444", "🔴"),
        }
        fg, dot_color, dot_sym = colors.get(state, ("#94a3b8", "#94a3b8", "⚪"))
        def _update():
            self.status_dot.configure(fg=dot_color, text=dot_sym)
            self.status_text.configure(fg=fg, text=text)
        self.after(0, _update)

    def copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.toast_label.configure(text=f"✓ Đã sao chép liên kết '{text}' vào bộ nhớ tạm!")
        self.after(3000, lambda: self.toast_label.configure(text=""))

    def open_in_browser(self):
        try:
            webbrowser.open(SERVER_URL)
            self.log(f"[App] Đang mở trình duyệt: {SERVER_URL}")
        except Exception as e:
            self.log(f"[Lỗi] Không thể mở trình duyệt: {e}")

    def open_downloads_folder(self):
        media_dir = str(MEDIA_DIR)
        os.makedirs(media_dir, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(media_dir)
            else:
                subprocess.Popen(["xdg-open", media_dir])
            self.log(f"[App] Đã mở thư mục video: {media_dir}")
        except Exception as e:
            self.log(f"[Lỗi] Không thể mở thư mục video: {e}")

    def on_toggle_auto_open(self):
        val = self.auto_open_var.get()
        self.config_data["auto_open_browser"] = val
        save_config(self.base_dir, self.config_data)
        self.log(f"[Cài đặt] Tự động mở trình duyệt: {'Bật' if val else 'Tắt'}")

    def start_server_thread(self):
        threading.Thread(target=self._run_server_flow, daemon=True).start()

    def _run_server_flow(self):
        self.set_status(f"Đang kiểm tra cổng {PORT}...", "warning")
        self.log("[Server] Kiểm tra trạng thái máy chủ...")

        # Tự động đồng bộ bản quyền với Firebase ngay khi mở Dashboard
        try:
            from core.machine_license import machine_license
            dec = machine_license.check()
            self.log(f"[Firebase] ✓ Đã đồng bộ mã máy: {dec.machine_id} | Status: {dec.status.upper()} (Tối đa: {dec.max_accounts or 'Không giới hạn'} tài khoản)")
        except Exception as fe:
            self.log(f"[Firebase] Cảnh báo kết nối: {fe}")

        if is_port_in_use(PORT):
            try:
                req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "ToolMuseServerPanel/1.0"})
                with urllib.request.urlopen(req, timeout=1.2) as resp:
                    if resp.status == 200:
                        self.log(f"[Server] ✓ Phát hiện máy chủ đã đang chạy sẵn trên cổng {PORT}!")
                        self.set_status("ĐANG HOẠT ĐỘNG", "online")
                        self.btn_toggle_server.configure(text="⏹ Dừng Server")
                        if self.auto_open_var.get():
                            self.after(500, self.open_in_browser)
                        return
            except Exception:
                pass

            self.log(f"[Server] Cổng {PORT} đang bận bởi tiến trình cũ, đang giải phóng...")
            kill_process_on_port(PORT)
            time.sleep(0.8)

        self.set_status("Đang khởi động Server...", "warning")
        self.log(f"[Server] Đang khởi chạy Uvicorn backend trên cổng {PORT}...")

        venv_py = os.path.join(self.base_dir, ".venv", "Scripts", "python.exe")
        server_py = venv_py if os.path.isfile(venv_py) else sys.executable

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        bin_dir = os.path.join(self.base_dir, "bin")
        if os.path.isdir(bin_dir) and bin_dir not in env.get("PATH", ""):
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000

        cmd = [
            server_py,
            "-u",
            "-c",
            f"import uvicorn, app; uvicorn.run(app.app, host='127.0.0.1', port={PORT}, access_log=False)"
        ]

        try:
            self.server_proc = subprocess.Popen(
                cmd,
                cwd=self.base_dir,
                env=env,
                startupinfo=startupinfo,
                creationflags=creationflags,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )
        except Exception as e:
            self.log(f"[LỖI] Không thể khởi chạy tiến trình server: {e}")
            self.set_status("KHỞI ĐỘNG THẤT BẠI", "offline")
            return

        def _read_output():
            if self.server_proc and self.server_proc.stdout:
                for line in iter(self.server_proc.stdout.readline, ''):
                    if line:
                        cleaned = line.rstrip()
                        if ' - "GET /' in cleaned and (' 200 ' in cleaned or ' 304 ' in cleaned):
                            continue
                        self.log(cleaned)
                self.server_proc.stdout.close()

        threading.Thread(target=_read_output, daemon=True).start()

        if wait_for_server(timeout=35):
            self.log(f"[Server] ✓ Máy chủ đã sẵn sàng hoạt động tại: {SERVER_URL}")
            if self.lan_url:
                self.log(f"[Server] ✓ Truy cập mạng nội bộ (LAN): {self.lan_url}")
            self.set_status("ĐANG HOẠT ĐỘNG", "online")
            self.btn_toggle_server.configure(text="⏹ Dừng Server")
            if self.auto_open_var.get():
                self.after(500, self.open_in_browser)
        else:
            self.log("[LỖI] Máy chủ không phản hồi sau 35 giây kiểm tra!")
            self.set_status("MẤT KẾT NỐI", "offline")

    def toggle_server(self):
        if self.server_proc and self.server_proc.poll() is None:
            self.log("[Server] Đang dừng máy chủ...")
            self.set_status("Đang dừng...", "warning")
            self._stop_server_process()
            self.set_status("ĐÃ DỪNG", "offline")
            self.btn_toggle_server.configure(text="▶ Bật Server")
        else:
            self.btn_toggle_server.configure(text="⏹ Dừng Server")
            self.start_server_thread()

    def restart_server(self):
        self.log("[Server] Yêu cầu khởi động lại máy chủ...")
        self.set_status("Đang khởi động lại...", "warning")
        self._stop_server_process()
        kill_process_on_port(PORT)
        time.sleep(1.0)
        self.start_server_thread()

    def _stop_server_process(self):
        if self.server_proc:
            try:
                self.server_proc.terminate()
                self.server_proc.wait(timeout=3)
            except Exception:
                try:
                    self.server_proc.kill()
                except Exception:
                    pass
            self.server_proc = None

    def on_closing(self):
        self.is_shutting_down = True
        self._stop_server_process()
        kill_process_on_port(PORT)
        self.destroy()


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    app = ServerApp(base_dir)
    app.mainloop()


if __name__ == "__main__":
    main()
