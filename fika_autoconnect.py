#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fika_autoconnect.py — Fika (SPT) 局域网主机自动探测 + 填入 Launcher

场景：主人用「汽游」虚拟局域网联机。每次进汽游房间后，主机（服主）
在 10.26.0.x 网段内开 SPT 服务器（端口 6969）。本脚本：
  1. 检测汽游虚拟网卡 (QIYOU_PLAY)，拿本机 IP + 网段
  2. 并发扫网段内开放 6969 的主机
  3. 把找到的主机 IP:6969 写进 SPT Launcher 的 LauncherSettings.json
     （更新/新建对应条目，条目名见 CONFIG）
  4. 启动 SPT.Launcher.exe

有窗口版（默认）：连不上时窗口不关，带「重新扫描」按钮 + 自动重试，
不用重新双击快捷方式。无窗口版（--cli）：旧行为，打印到控制台。

只改动 <SPT>/SPT_Runtime/user/Launcher/LauncherSettings.json（Launcher 自身
的配置，等价于手动填 IP）。绝不碰任何游戏/SPT 原文件。
"""

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import concurrent.futures
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk
    HAVE_TK = True
except Exception:  # 极简环境 / 无 tk 的 Python 也能跑 --cli
    HAVE_TK = False

# ============ 配置区（默认值；同目录 config.json 可覆盖） ============
# ⭐ 本脚本位于 <SPT根>/FikaAutoConnect/fika_autoconnect.py
#    → SPT_ROOT = 脚本所在目录的上一级（自动推导，无需配置、无需探测）
VLAN_ADAPTER_KEYWORD = "QIYOU_PLAY"

# SPT 服务端端口
SPT_PORT = 6969

# LauncherSettings.json 里要更新/新建的服务器条目名
# 注意：必须是 Launcher 里「服务器」下拉框中的名字
SERVER_ENTRY_NAME = "JR"

# LauncherSettings.json 相对 SPT_ROOT 的路径（SPT 4.1.x）
LAUNCHER_SETTINGS_REL = Path("SPT_Runtime") / "user" / "Launcher" / "LauncherSettings.json"

# 启动 Launcher？设 False 只改配置不启动
LAUNCH_LAUNCHER = True

# 探测并发数 / 单次超时（秒）
SCAN_CONCURRENCY = 120
SCAN_TIMEOUT = 0.35

# 窗口版：自动重试间隔（秒）
AUTO_RETRY_SEC = 6

# 允许的私有网段前缀（防扫到公网/别的东西；留空=不限制）
ALLOWED_SUBNETS = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                   "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                   "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                   "172.30.", "172.31.", "192.168.")
# ===========================================

# 运行时配置（由 load_config 填充覆盖默认值，见 apply_config）
CFG = {}

# 窗口版与命令行版共用的日志落点（纯排障用）
_LOG_PATH = None


def resolve_spt_root() -> Path:
    """
    SPT 根目录 = 脚本所在目录的上一级（脚本位于 <SPT根>/FikaAutoConnect/）。
    返回 Path；若结构不符（找不到 SPT_Runtime/SPT.Launcher.exe）则仍返回推导值，
    由后续步骤给出明确报错。
    """
    return Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """读取脚本同目录 config.json（可选）。返回 dict，不存在则空。"""
    cfg_path = Path(__file__).resolve().parent / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def apply_config():
    """把 config.json 的值应用到模块级配置变量（未配置的项保持代码默认）。"""
    global CFG, SPT_ROOT, VLAN_ADAPTER_KEYWORD, SPT_PORT, SERVER_ENTRY_NAME, \
        LAUNCH_LAUNCHER, SCAN_CONCURRENCY, SCAN_TIMEOUT, AUTO_RETRY_SEC
    CFG = load_config()
    VLAN_ADAPTER_KEYWORD = CFG.get("vlan_adapter_keyword", VLAN_ADAPTER_KEYWORD)
    SPT_PORT = int(CFG.get("spt_port", SPT_PORT))
    SERVER_ENTRY_NAME = CFG.get("server_entry_name", SERVER_ENTRY_NAME)
    LAUNCH_LAUNCHER = bool(CFG.get("launch_launcher", LAUNCH_LAUNCHER))
    SCAN_CONCURRENCY = int(CFG.get("scan_concurrency", SCAN_CONCURRENCY))
    SCAN_TIMEOUT = float(CFG.get("scan_timeout", SCAN_TIMEOUT))
    AUTO_RETRY_SEC = int(CFG.get("auto_retry_sec", AUTO_RETRY_SEC))
    # SPT_ROOT 由脚本位置推导；config 的 spt_root 仅作可选覆盖（一般不填）
    SPT_ROOT = resolve_spt_root()
    cfg_root = CFG.get("spt_root")
    if cfg_root:
        p = Path(cfg_root)
        if (p / "SPT_Runtime" / "SPT.Launcher.exe").exists():
            SPT_ROOT = p


def log(msg: str):
    """带时间戳打印（控制台有窗口时可见）+ 写日志文件"""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        global _LOG_PATH
        if _LOG_PATH is None:
            logdir = SPT_ROOT / "SPT_Runtime" / "user" / "sptappdata" / "fika_autoconnect_logs"
            logdir.mkdir(parents=True, exist_ok=True)
            _LOG_PATH = logdir / "fika_autoconnect.log"
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# 最终 SPT_ROOT：读取 config.json 并应用（config 无 spt_root 时自动探测）
apply_config()


def get_vlan_ip() -> str | None:
    """找汽游虚拟网卡 (QIYOU_PLAY) 的本机 IPv4"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetIPAddress -AddressFamily IPv4 | "
             "Where-Object { $_.InterfaceAlias -like '*QIYOU*' } | "
             "Select-Object -ExpandProperty IPAddress"],
            capture_output=True, text=True, timeout=20)
        for line in out.stdout.splitlines():
            line = line.strip()
            if line and line[0].isdigit():
                return line
    except Exception as e:
        log(f"获取虚拟网卡 IP 失败: {e}")
    return None


def detect_adapter_online() -> bool:
    """QIYOU_PLAY 网卡是否在线"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter | Where-Object { $_.Name -like '*QIYOU*' } | "
             "Select-Object -ExpandProperty Status"],
            capture_output=True, text=True, timeout=20)
        return "Up" in out.stdout
    except Exception:
        return False


def probe_port(ip: str, port: int, timeout: float) -> bool:
    """TCP 端口探测"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def scan_hosts(network_prefix: str, exclude_ip: str | None = None):
    """并发扫网段内开放 SPT_PORT 的主机，返回 IP 列表（已排序）"""
    hosts = [f"{network_prefix}.{i}" for i in range(1, 255)
             if f"{network_prefix}.{i}" != exclude_ip]
    found = []

    def worker(ip):
        if probe_port(ip, SPT_PORT, SCAN_TIMEOUT):
            return ip
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_CONCURRENCY) as ex:
        for res in ex.map(worker, hosts):
            if res:
                found.append(res)
    # 排序让结果稳定（低 IP 优先，通常是主机）
    found.sort(key=lambda ip: int(ip.rsplit(".", 1)[1]))
    return found


def update_launcher_settings(settings_path: Path, server_name: str, ip: str,
                             log_fn=log) -> bool:
    """
    在 LauncherSettings.json 里把名为 server_name 的条目 IP 改成 ip:6969。
    没有该条目则新增。返回是否发生了修改。
    """
    if not settings_path.exists():
        log_fn(f"!! LauncherSettings.json 不存在: {settings_path}")
        return False

    # 读原文件 + 备份
    original = settings_path.read_text(encoding="utf-8")
    backup = settings_path.with_suffix(".json.bak")
    backup.write_text(original, encoding="utf-8")

    data = json.loads(original)
    servers = data.setdefault("Servers", [])
    target = f"{ip}:{SPT_PORT}"

    # 找同名条目
    for srv in servers:
        if srv.get("Name", "").strip().lower() == server_name.strip().lower():
            if srv.get("IpAddress") == target:
                log_fn(f"条目 [{server_name}] 已是 {target}，无需修改")
                return False
            srv["IpAddress"] = target
            log_fn(f"更新条目 [{server_name}] -> {target}")
            settings_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return True

    # 没有 -> 新增
    servers.append({
        "Name": server_name,
        "IpAddress": target,
        "ServerId": str(int(time.time()))
    })
    log_fn(f"新增条目 [{server_name}] -> {target}")
    settings_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def set_preferred_server(settings_path: Path, server_name: str, log_fn=log) -> bool:
    """
    把指定服务器条目设为 PreferredProfile（自动连接目标）。
    SPT Launcher 的 PreferredProfile 形如 {"ServerId": "...", "ProfileId": "..."}，
    需要 ServerId 与条目匹配。这里找到条目后同步 PreferredProfile.ServerId。
    """
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        servers = data.get("Servers", [])
        pref = data.get("PreferredProfile", {})
        # 找指定名字的条目
        srv = next((s for s in servers
                    if s.get("Name", "").strip().lower() == server_name.strip().lower()), None)
        if not srv:
            return False
        srv_id = srv.get("ServerId")
        if not srv_id:
            return False
        # 如果 PreferredProfile 已有该 ServerId，不动
        if pref.get("ServerId") == srv_id:
            return False
        # 保留 ProfileId（同一个人物跨服通用），只更新 ServerId
        pref["ServerId"] = srv_id
        data["PreferredProfile"] = pref
        settings_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log_fn(f"已把条目 [{server_name}] 设为自动连接目标")
        return True
    except Exception as e:
        log_fn(f"设置自动连接目标失败: {e}")
        return False


# ---------------------------------------------------------------------------
# 可重入的连接流程（窗口版重试 / 命令行版共用）
# 返回 (status, detail)：
#   ok / no_adapter / no_ip / no_host / launcher_missing / error
# ---------------------------------------------------------------------------
def find_host(log_fn=log):
    """探测汽游网卡并扫描主机。返回 (status, detail=host_ip 或 原因说明)。"""
    log_fn("检测汽游虚拟网卡 (QIYOU_PLAY) …")
    if not detect_adapter_online():
        return "no_adapter", "QIYOU_PLAY 网卡不在线——请先打开汽游并加入房间。"

    vlan_ip = get_vlan_ip()
    if not vlan_ip:
        return "no_ip", "拿到了网卡但取不到 IP：请确认汽游已连接（不是只开了客户端）。"
    network_prefix = ".".join(vlan_ip.split(".")[:3])
    log_fn(f"本机汽游 IP: {vlan_ip}，扫描网段: {network_prefix}.0/24")

    log_fn(f"正在扫描 {network_prefix}.1~254 的 {SPT_PORT} 端口 …")
    hosts = scan_hosts(network_prefix, exclude_ip=vlan_ip)
    if not hosts:
        return "no_host", (f"{network_prefix}.0/24 里没有开放 {SPT_PORT} 的主机："
                           "确认主机已开 SPT.Server.exe，且你们在同一个汽游房间。")
    host_ip = hosts[0]
    if len(hosts) > 1:
        log_fn(f"检测到多个主机 {hosts}，取第一个 {host_ip}")
    log_fn(f"✅ 找到 SPT 主机: {host_ip}:{SPT_PORT}")
    return "ok", host_ip


def apply_launcher(host_ip: str, log_fn=log):
    """写 LauncherSettings.json + 启动 Launcher。返回 (status, detail)。"""
    settings_path = SPT_ROOT / LAUNCHER_SETTINGS_REL
    update_launcher_settings(settings_path, SERVER_ENTRY_NAME, host_ip, log_fn)
    set_preferred_server(settings_path, SERVER_ENTRY_NAME, log_fn)

    if not LAUNCH_LAUNCHER:
        log_fn("按配置不启动 Launcher（LAUNCH_LAUNCHER=False）")
        return "ok", host_ip

    launcher_exe = SPT_ROOT / "SPT_Runtime" / "SPT.Launcher.exe"
    if not launcher_exe.exists():
        log_fn(f"!! Launcher 不存在: {launcher_exe}")
        return "launcher_missing", f"Launcher 未找到：{launcher_exe}"
    log_fn(f"启动 SPT Launcher: {launcher_exe}")
    subprocess.Popen([str(launcher_exe)], cwd=str(launcher_exe.parent))
    return "ok", host_ip


# ---------------------------------------------------------------------------
# 窗口版
# ---------------------------------------------------------------------------
class RetryWindow:
    """一个常驻小窗：扫描进度 + 失败原因 + 重新扫描 / 自动重试。"""

    COLORS = {
        "idle": "#57606a",
        "busy": "#1f6feb",
        "ok": "#1a7f37",
        "fail": "#cf222e",
    }
    FAIL_TITLES = {
        "no_adapter": "没连上：汽游网卡没起来",
        "no_ip": "没连上：取不到汽游网段 IP",
        "no_host": "没连上：没扫到 SPT 主机",
        "launcher_missing": "找到主机了，但 Launcher 不见了",
        "error": "出错了",
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.queue = queue.Queue()
        self.busy = False
        self.finished = False
        self.auto_after = None
        self.countdown_after = None
        self.build_ui()
        self.root.after(150, self.start_attempt)
        self.root.after(100, self.pump)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI ----------
    def build_ui(self):
        self.root.title("Fika 联机启动")
        self.root.configure(bg="#f6f7f9")
        self.root.resizable(False, False)
        w, h = 580, 430
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 40)}")

        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"),
                        padding=(18, 8))
        style.configure("Plain.TButton", font=("Microsoft YaHei UI", 9), padding=(10, 6))

        head = tk.Frame(self.root, bg="#0f172a")
        head.pack(fill="x")
        tk.Label(head, text="Fika 联机启动", bg="#0f172a", fg="#ffffff",
                 font=("Microsoft YaHei UI", 14, "bold"), anchor="w").pack(
            padx=18, pady=(12, 2), fill="x")
        tk.Label(head, text="自动扫描汽游网段里的 SPT 主机，填进 Launcher 的 JR 条目",
                 bg="#0f172a", fg="#9fb0c9", font=("Microsoft YaHei UI", 9),
                 anchor="w").pack(padx=18, pady=(0, 12), fill="x")

        body = tk.Frame(self.root, bg="#f6f7f9")
        body.pack(fill="both", expand=True, padx=18, pady=(14, 8))

        self.status_var = tk.StringVar(value="准备中…")
        self.status_label = tk.Label(body, textvariable=self.status_var, bg="#f6f7f9",
                                     fg=self.COLORS["idle"], justify="left", anchor="w",
                                     font=("Microsoft YaHei UI", 13, "bold"),
                                     wraplength=540)
        self.status_label.pack(fill="x")

        self.detail_var = tk.StringVar(value="")
        self.detail_label = tk.Label(body, textvariable=self.detail_var, bg="#f6f7f9",
                                     fg="#57606a", justify="left", anchor="w",
                                     font=("Microsoft YaHei UI", 10), wraplength=540)
        self.detail_label.pack(fill="x", pady=(4, 2))

        self.hint_var = tk.StringVar(value="")
        tk.Label(body, textvariable=self.hint_var, bg="#f6f7f9", fg="#8b949e",
                 justify="left", anchor="w", font=("Microsoft YaHei UI", 9),
                 wraplength=540).pack(fill="x", pady=(0, 8))

        logframe = tk.Frame(body, bg="#ffffff", highlightbackground="#d8dee4",
                            highlightthickness=1)
        logframe.pack(fill="both", expand=True)
        self.log_text = tk.Text(logframe, height=7, wrap="word", bd=0, bg="#ffffff",
                                fg="#24292f", font=("Consolas", 9), state="disabled",
                                padx=8, pady=6)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(logframe, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

        btns = tk.Frame(self.root, bg="#f6f7f9")
        btns.pack(fill="x", padx=18, pady=(0, 14))

        self.retry_btn = ttk.Button(btns, text="重新扫描", style="Primary.TButton",
                                    command=self.start_attempt)
        self.retry_btn.pack(side="left")

        self.auto_var = tk.BooleanVar(value=True)
        self.auto_chk = tk.Checkbutton(
            btns, text=f"自动重试（每 {AUTO_RETRY_SEC} 秒）", variable=self.auto_var,
            bg="#f6f7f9", fg="#57606a", activebackground="#f6f7f9",
            font=("Microsoft YaHei UI", 9), command=self.on_auto_toggle)
        self.auto_chk.pack(side="left", padx=(14, 0))

        ttk.Button(btns, text="看日志", style="Plain.TButton",
                   command=self.open_log).pack(side="right")
        ttk.Button(btns, text="退出", style="Plain.TButton",
                   command=self.on_close).pack(side="right", padx=(0, 8))

        self.retry_btn.state(["disabled"])
        self.root.bind("<Return>", lambda e: self.start_attempt() if not self.busy else None)
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def append_log(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        log(msg)  # 同时落盘

    def log_msg(self, msg: str):
        """后台线程专用：只入队，绝不在子线程碰 tkinter 控件。"""
        self.queue.put(("log", msg, None))

    def set_status(self, status: str, detail: str, tone: str):
        self.status_var.set(status)
        self.detail_var.set(detail)
        self.status_label.configure(fg=self.COLORS[tone])

    # ---------- 流程 ----------
    def start_attempt(self):
        if self.busy or self.finished:
            return
        self.cancel_auto()
        self.busy = True
        self.retry_btn.state(["disabled"])
        self.set_status("正在扫描…", "检测汽游网卡并扫描 SPT 主机，请稍候。", "busy")
        self.hint_var.set("扫描 254 个地址，通常 1~3 秒")
        self.append_log("===== 开始扫描 =====")
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            status, detail = find_host(self.log_msg)
            if status == "ok":
                status2, detail2 = apply_launcher(detail, self.log_msg)
                self.queue.put(("done", status2, detail2))
            else:
                self.queue.put(("fail", status, detail))
        except Exception as e:  # 兜底：任何异常都不许让窗口静默死掉
            self.queue.put(("fail", "error", f"未预期的错误：{e}"))

    def pump(self):
        try:
            while True:
                kind, a, b = self.queue.get_nowait()
                if kind == "log":
                    self.append_log(a)
                elif kind == "fail":
                    self.on_fail(a, b)
                elif kind == "done":
                    self.on_done(a, b)
        except queue.Empty:
            pass
        if not self.finished:
            self.root.after(100, self.pump)

    def on_fail(self, status: str, detail: str):
        self.busy = False
        title = self.FAIL_TITLES.get(status, "没连上")
        self.set_status(title, detail + "\n修好后点「重新扫描」，不用重开工具。", "fail")
        self.hint_var.set("")
        self.retry_btn.state(["!disabled"])
        self.append_log(f"[X] {title} — {detail}")
        if self.auto_var.get():
            self.schedule_auto()

    def on_done(self, status: str, detail: str):
        self.busy = False
        if status == "ok":
            self.finished = True
            self.cancel_auto()
            self.set_status(f"✅ 已连上 {detail}",
                            "Launcher 已启动，窗口即将自动关闭。", "ok")
            self.hint_var.set("")
            self.append_log(f"[OK] 完成：{detail}")
            self.root.after(2200, self.on_close)
        else:
            # launcher_missing：主机找到了但启动器不在
            self.set_status(self.FAIL_TITLES.get(status, "启动失败"), detail, "fail")
            self.hint_var.set("")
            self.retry_btn.state(["!disabled"])
            self.append_log(f"[X] {detail}")

    # ---------- 自动重试 ----------
    def schedule_auto(self):
        self.cancel_auto()
        n = AUTO_RETRY_SEC

        def tick():
            nonlocal n
            if self.finished or self.busy:
                return
            if not self.auto_var.get():
                self.hint_var.set("")
                return
            if n <= 0:
                self.start_attempt()
                return
            self.hint_var.set(f"{n} 秒后自动重试（取消勾选可停）")
            n -= 1
            self.countdown_after = self.root.after(1000, tick)

        tick()

    def cancel_auto(self):
        for attr in ("auto_after", "countdown_after"):
            aid = getattr(self, attr, None)
            if aid:
                try:
                    self.root.after_cancel(aid)
                except Exception:
                    pass
                setattr(self, attr, None)
        try:
            self.hint_var.set("")
        except Exception:
            pass

    def on_auto_toggle(self):
        if self.auto_var.get() and not self.busy and not self.finished:
            self.schedule_auto()
        else:
            self.cancel_auto()

    def open_log(self):
        try:
            path = _LOG_PATH
            if path is None:
                log("初始化日志路径")
                path = _LOG_PATH
            os.startfile(str(path.parent))  # noqa: S606
        except Exception as e:
            self.append_log(f"打开日志目录失败：{e}")

    def on_close(self):
        self.finished = True
        self.cancel_auto()
        try:
            self.root.destroy()
        except Exception:
            pass


def run_gui():
    root = tk.Tk()
    RetryWindow(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


# ---------------------------------------------------------------------------
# 命令行版（--cli）：保留旧的无窗口行为
# ---------------------------------------------------------------------------
def _msgbox(text: str):
    """弹 Windows 消息框"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Fika AutoConnect", 0x40)
    except Exception:
        pass


def main_cli() -> int:
    log("===== Fika AutoConnect 启动（命令行模式） =====")
    log(f"SPT 根目录: {SPT_ROOT}")
    log(f"服务器条目名: {SERVER_ENTRY_NAME}")
    status, detail = find_host(log)
    if status != "ok":
        log(f"!! {status}: {detail}")
        _msgbox(detail)
        return {"no_adapter": 2, "no_ip": 3, "no_host": 4}.get(status, 5)
    status2, detail2 = apply_launcher(detail, log)
    if status2 != "ok":
        log(f"!! {status2}: {detail2}")
        _msgbox(detail2)
        return 6
    log("===== 完成 =====")
    return 0


def main():
    if "--cli" in sys.argv or not HAVE_TK:
        return main_cli()
    log("===== Fika AutoConnect 启动（窗口模式） =====")
    log(f"SPT 根目录: {SPT_ROOT}")
    return run_gui()


if __name__ == "__main__":
    if HAVE_TK and "--cli" not in sys.argv:
        try:
            sys.exit(main())
        except Exception as exc:  # pythonw 下没有控制台，至少留个框
            _msgbox(f"Fika AutoConnect 启动失败：\n{exc}")
            raise
    else:
        sys.exit(main_cli())
