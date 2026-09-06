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
全程零手动，双击即用。

只改动 <SPT>/user/Launcher/LauncherSettings.json（Launcher 自身的配置，
等价于手动填 IP）。绝不碰任何游戏/SPT 原文件。
"""

import json
import os
import socket
import subprocess
import sys
import time
import concurrent.futures
from pathlib import Path

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

# 允许的私有网段前缀（防扫到公网/别的东西；留空=不限制）
ALLOWED_SUBNETS = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                   "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                   "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                   "172.30.", "172.31.", "192.168.")
# ===========================================

# 运行时配置（由 load_config 填充覆盖默认值，见 apply_config）
CFG = {}


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
        LAUNCH_LAUNCHER, SCAN_CONCURRENCY, SCAN_TIMEOUT
    CFG = load_config()
    VLAN_ADAPTER_KEYWORD = CFG.get("vlan_adapter_keyword", VLAN_ADAPTER_KEYWORD)
    SPT_PORT = int(CFG.get("spt_port", SPT_PORT))
    SERVER_ENTRY_NAME = CFG.get("server_entry_name", SERVER_ENTRY_NAME)
    LAUNCH_LAUNCHER = bool(CFG.get("launch_launcher", LAUNCH_LAUNCHER))
    SCAN_CONCURRENCY = int(CFG.get("scan_concurrency", SCAN_CONCURRENCY))
    SCAN_TIMEOUT = float(CFG.get("scan_timeout", SCAN_TIMEOUT))
    # SPT_ROOT 由脚本位置推导；config 的 spt_root 仅作可选覆盖（一般不填）
    SPT_ROOT = resolve_spt_root()
    cfg_root = CFG.get("spt_root")
    if cfg_root:
        p = Path(cfg_root)
        if (p / "SPT_Runtime" / "SPT.Launcher.exe").exists():
            SPT_ROOT = p


def log(msg: str):
    """带时间戳打印（控制台有窗口时可见；无窗口时写日志文件）"""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    # 同时写日志，方便排查（放在 Launcher 配置同级 user 目录，纯排障用）
    try:
        logdir = SPT_ROOT / "SPT_Runtime" / "user" / "sptappdata" / "fika_autoconnect_logs"
        logdir.mkdir(parents=True, exist_ok=True)
        with open(logdir / "fika_autoconnect.log", "a", encoding="utf-8") as f:
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


def update_launcher_settings(settings_path: Path, server_name: str, ip: str) -> bool:
    """
    在 LauncherSettings.json 里把名为 server_name 的条目 IP 改成 ip:6969。
    没有该条目则新增。返回是否发生了修改。
    """
    if not settings_path.exists():
        log(f"!! LauncherSettings.json 不存在: {settings_path}")
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
                log(f"条目 [{server_name}] 已是 {target}，无需修改")
                return False
            srv["IpAddress"] = target
            log(f"更新条目 [{server_name}] -> {target}")
            # 同时把该条目设为 PreferredProfile（如果存在的话）
            # 注意 PreferredProfile 里是 ServerId 而非 Name，这里不强改
            settings_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return True

    # 没有 -> 新增
    servers.append({
        "Name": server_name,
        "IpAddress": target,
        "ServerId": str(int(time.time()))
    })
    log(f"新增条目 [{server_name}] -> {target}")
    settings_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def set_preferred_server(settings_path: Path, server_name: str) -> bool:
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
        log(f"已把条目 [{server_name}] 设为自动连接目标")
        return True
    except Exception as e:
        log(f"设置自动连接目标失败: {e}")
        return False


def main():
    log("===== Fika AutoConnect 启动 =====")
    log(f"SPT 根目录: {SPT_ROOT}")
    log(f"服务器条目名: {SERVER_ENTRY_NAME}")

    # 1) 汽游网卡在线？
    if not detect_adapter_online():
        log("!! 未检测到汽游虚拟网卡 (QIYOU_PLAY)。请先加入汽游局域网房间。")
        _msgbox("未检测到汽游虚拟局域网\n\n请先打开汽游并加入房间，再运行本工具。")
        sys.exit(2)

    # 2) 拿本机虚拟网卡 IP
    vlan_ip = get_vlan_ip()
    if not vlan_ip:
        log("!! 拿到本机虚拟网卡 IP 失败")
        _msgbox("无法获取汽游网段 IP\n\n请确认汽游已连接。")
        sys.exit(3)
    network_prefix = ".".join(vlan_ip.split(".")[:3])
    log(f"本机汽游 IP: {vlan_ip}，扫描网段: {network_prefix}.0/24")

    # 3) 扫主机
    log(f"正在扫描 {network_prefix}.1~254 的 {SPT_PORT} 端口 ...")
    hosts = scan_hosts(network_prefix, exclude_ip=vlan_ip)
    if not hosts:
        log("!! 没扫到任何开放 6969 的主机")
        _msgbox("没检测到 SPT 主机\n\n请确认：\n1. 主机已打开 SPT 服务器（SPT.Server.exe）\n2. 你和主机在同一个汽游房间")
        sys.exit(4)

    # 取第一个（通常唯一）
    host_ip = hosts[0]
    if len(hosts) > 1:
        log(f"检测到多个主机 {hosts}，取第一个 {host_ip}")
    log(f"✅ 找到 SPT 主机: {host_ip}:{SPT_PORT}")

    # 4) 更新 LauncherSettings.json
    settings_path = SPT_ROOT / LAUNCHER_SETTINGS_REL
    changed = update_launcher_settings(settings_path, SERVER_ENTRY_NAME, host_ip)
    # 5) 设为自动连接
    set_preferred_server(settings_path, SERVER_ENTRY_NAME)

    # 6) 启动 Launcher
    if LAUNCH_LAUNCHER:
        launcher_exe = SPT_ROOT / "SPT_Runtime" / "SPT.Launcher.exe"
        if launcher_exe.exists():
            log(f"启动 SPT Launcher: {launcher_exe}")
            # 用 subprocess.Popen 启动（MSYS 下唯一可靠方式）
            subprocess.Popen([str(launcher_exe)], cwd=str(launcher_exe.parent))
        else:
            log(f"!! Launcher 不存在: {launcher_exe}")
            _msgbox(f"Launcher 未找到：{launcher_exe}\n\n请手动打开 SPT Launcher。")
    else:
        log("按配置不启动 Launcher（LAUNCH_LAUNCHER=False）")

    log("===== 完成 =====")


def _msgbox(text: str):
    """弹 Windows 消息框（有窗口时可见）"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Fika AutoConnect", 0x40)
    except Exception:
        pass


if __name__ == "__main__":
    main()
