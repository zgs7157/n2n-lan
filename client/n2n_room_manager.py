#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
n2n 房间管理小工具 (N2N Room Manager)
=====================================
基于 n2n v3 的“房间式”虚拟局域网客户端。

- 房主“创建房间”：自动生成 房间码 = community@网段#密钥，并以网段 .1 作为房主虚拟 IP 启动 edge。
- 好友“加入房间”：粘贴房间码，自动建议空闲虚拟 IP，启动 edge 加入同一 community。
- 底层封装 n2n edge（n2n v3.1.1 x64），自带 TAP-Windows 虚拟网卡驱动安装与防火墙放行。

运行环境：Windows 10/11 x64，Python 3（本工具仅用标准库）。双击 start.bat 启动。
"""

import argparse
import ctypes
import hashlib
import json
import os
import random
import re
import secrets
import string
import subprocess
import sys
import threading
import time
import urllib.parse

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# ----------------------------------------------------------------------------
# 常量与路径
# ----------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # PyInstaller 打包成 exe 后：__file__ 指向临时解包目录，
    # 资源（bin/driver/tools）位于 exe 同目录，须以 exe 所在目录为基准。
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EDGE_EXE = os.path.join(BASE_DIR, "bin", "edge.exe")
DRIVER_DIR = os.path.join(BASE_DIR, "driver", "tap-windows", "x64")
TAP_INF = os.path.join(DRIVER_DIR, "OemVista.inf")
TAP_INSTALLER = os.path.join(BASE_DIR, "driver", "tap-windows", "9.24.7.exe")
WINIPBROADCAST_EXE = os.path.join(BASE_DIR, "tools", "WinIPBroadcast.exe")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")

DEFAULT_MTU = 1290

DEFAULT_CONFIG = {
    "supernode": "",          # 例如 "1.2.3.4:7654"，多个用逗号分隔
    "mtu": DEFAULT_MTU,
    "use_multicast": True,    # edge -E：接受组播/广播（MC 局域网发现需要）
    "use_game_metric": True,  # edge -x 1：更利于联机游戏识别
    "auto_broadcast": False,  # 是否随房间自动启动 WinIPBroadcast（广播助手）
    "lang": "",               # 界面语言：zh/en，空 = 按系统语言自动
    "rooms": {},              # community -> {"subnet": "...", "key": "...", "my_ip": "...", "last_host": 2}
}

RE_ROOM_CODE = re.compile(r"^([A-Za-z0-9_-]{3,32})@(10\.\d{1,3}\.0)#([A-Za-z0-9]{6,16})$")
RE_SUBNET = re.compile(r"^10\.(\d{1,3})\.0$")


# ----------------------------------------------------------------------------
# 多语言（中文 / English）
# ----------------------------------------------------------------------------
LANG_ZH = {
    "app_title": "n2n 房间管理小工具",
    "server_frame": "服务器（公网 supernode）",
    "server_fmt": "格式 IP:端口，多个用逗号分隔",
    "save": "保存",
    "room_frame": "房间",
    "create_room": "创建房间（我是房主）",
    "with_pwd": "带密码",
    "join_room": "加入房间",
    "leave_room": "退出房间",
    "copy_code": "复制房间码",
    "copy_link": "复制进房链接",
    "room_code": "房间码",
    "room_pwd": "房间密码",
    "pwd_hint": "房主创建后自动生成；好友加入时填房主单独发的密码，填错进不来；免密房留空",
    "my_ip": "我的虚拟IP",
    "ip_hint": "加入房间时自动建议空闲IP，可手动改",
    "status_frame": "状态",
    "disconnected": "未连接",
    "connected": "已连接（edge 运行中）",
    "virtual_ip": "虚拟IP: -",
    "room": "房间: -",
    "log_frame": "edge 运行日志",
    "tools_frame": "工具与设置",
    "lang": "语言",
    "install_driver": "安装/检测虚拟网卡驱动",
    "firewall": "防火墙放行 edge",
    "open_logs": "打开日志目录",
    "open_bin": "打开 bin 目录",
    "opt_multicast": "接受组播(-E, 局域网发现)",
    "opt_metric": "游戏识别(-x 1)",
    "opt_bcast": "自动启动广播助手",
    # 消息
    "info": "提示",
    "error": "错误",
    "leave_first": "请先退出当前房间",
    "no_driver": "缺少虚拟网卡驱动",
    "no_driver_msg": "未检测到 TAP 虚拟网卡驱动，进房前需要先安装。\n现在安装？（需要管理员权限，会弹出 UAC 确认）",
    "not_installed": "未安装",
    "denied_msg": "安装被拒绝，请点上方“安装/检测虚拟网卡驱动”手动操作",
    "install_fail": "安装失败",
    "install_fail_msg": "驱动安装失败，请手动运行 driver/tap-windows/9.24.7.exe 安装",
    "bad_code": "房间码无效",
    "bad_code_msg": "房间码格式应为：community@10.x.0#密钥\n请向房主索取完整的房间码",
    "bad_ip": "IP 无效",
    "bad_ip_msg": "虚拟IP 应为 10.x.0.1~254 的形式",
    "subnet_mismatch": "网段不符",
    "subnet_mismatch_msg": "虚拟IP 必须与房间码中的网段 %(subnet)s 一致",
    "no_server": "未配置服务器",
    "no_server_msg": "请先填写公网 supernode 地址（IP:端口）并保存",
    "check_result": "检查结果",
    "driver_ok": "虚拟网卡驱动已安装（TAP-Windows Adapter V9）",
    "installed_ok": "安装成功",
    "installed_ok_msg": "TAP 虚拟网卡驱动安装完成",
    "uac_cancel": "UAC 确认被取消，未安装驱动",
    "silent_fail_msg": "静默安装失败，请手动运行 driver/tap-windows/9.24.7.exe 安装",
    "lang_switch": "界面语言已切换，重启后完全生效",
    # 日志
    "log_server_saved": ">> 已保存服务器地址: %(sn)s",
    "log_driver_ready": ">> 虚拟网卡驱动已就绪",
    "log_pwd_gen": ">> 房间密码: %(pwd)s（请单独发给好友，密码不对进不来）",
    "log_nopwd_room": ">> 免密房间：房间码即全部凭证",
    "log_pwd_join": ">> 使用房间密码派生密钥（密码错误将无法互通）",
    "log_nopwd_join": ">> 免密加入（房间码即全部凭证）",
    "log_nopwd_switch": ">> 已切换为免密房间：创建/加入时密码留空即可",
    "log_edge_start": ">> 启动 edge：房间=%(room)s  虚拟IP=%(ip)s",
    "log_supernode": ">> supernode: %(sn)s",
    "log_edge_pid": ">> edge 已启动 (pid=%(pid)s)，等待注册…",
    "log_left": ">> 已退出房间",
    "log_copy_pwd": ">> 房间码已复制；房间密码需单独发给好友（在“房间密码”框里复制）",
    "log_copy_nopwd": ">> 免密房间，房间码已复制，发给好友即可加入",
    "log_copy_link": ">> 手机进房链接已复制，发给朋友即可（需路由器转发 TCP 25565 到本机）",
    "log_fw_ok": ">> 已放行 edge.exe 入站（若弹出 UAC 请点“是”）",
    "log_fw_cancel": ">> 防火墙规则添加被取消",
}

LANG_EN = {
    "app_title": "N2N Room Manager",
    "server_frame": "Server (public supernode)",
    "server_fmt": "Format IP:port, comma separated",
    "save": "Save",
    "room_frame": "Room",
    "create_room": "Create Room (I'm host)",
    "with_pwd": "Password",
    "join_room": "Join Room",
    "leave_room": "Leave Room",
    "copy_code": "Copy Room Code",
    "copy_link": "Copy Join Link",
    "room_code": "Room Code",
    "room_pwd": "Room Password",
    "pwd_hint": "Auto-generated by host; joiners enter the password sent separately; leave empty for no-password rooms",
    "my_ip": "My Virtual IP",
    "ip_hint": "Auto-suggested on join; you can edit",
    "status_frame": "Status",
    "disconnected": "Disconnected",
    "connected": "Connected (edge running)",
    "virtual_ip": "Virtual IP: -",
    "room": "Room: -",
    "log_frame": "edge log",
    "tools_frame": "Tools & Settings",
    "lang": "Language",
    "install_driver": "Install/Check TAP Driver",
    "firewall": "Allow edge in Firewall",
    "open_logs": "Open Logs Folder",
    "open_bin": "Open bin Folder",
    "opt_multicast": "Multicast (-E, LAN discovery)",
    "opt_metric": "Game mode (-x 1)",
    "opt_bcast": "Auto-start broadcast helper",
    # Messages
    "info": "Info",
    "error": "Error",
    "leave_first": "Please leave the current room first",
    "no_driver": "TAP driver not found",
    "no_driver_msg": "TAP virtual NIC driver not detected. Install before joining.\nInstall now? (Admin rights required, UAC prompt will appear)",
    "not_installed": "Not installed",
    "denied_msg": "Install denied. Use the 'Install/Check TAP Driver' button above",
    "install_fail": "Install failed",
    "install_fail_msg": "Driver install failed. Run driver/tap-windows/9.24.7.exe manually",
    "bad_code": "Invalid room code",
    "bad_code_msg": "Format: community@10.x.0#key\nAsk the host for the full room code",
    "bad_ip": "Invalid IP",
    "bad_ip_msg": "Virtual IP must be 10.x.0.1~254",
    "subnet_mismatch": "Subnet mismatch",
    "subnet_mismatch_msg": "Virtual IP must match subnet %(subnet)s from the room code",
    "no_server": "No server configured",
    "no_server_msg": "Enter the public supernode address (IP:port) and save first",
    "check_result": "Check result",
    "driver_ok": "TAP driver already installed (TAP-Windows Adapter V9)",
    "installed_ok": "Installed",
    "installed_ok_msg": "TAP virtual NIC driver installed",
    "uac_cancel": "UAC cancelled; driver not installed",
    "silent_fail_msg": "Silent install failed. Run driver/tap-windows/9.24.7.exe manually",
    "lang_switch": "Language switched; fully effective after restart",
    # Logs
    "log_server_saved": ">> Server saved: %(sn)s",
    "log_driver_ready": ">> TAP driver ready",
    "log_pwd_gen": ">> Room password: %(pwd)s (send separately; wrong password cannot join)",
    "log_nopwd_room": ">> No-password room: the room code is the only credential",
    "log_pwd_join": ">> Deriving key with room password (wrong password will not connect)",
    "log_nopwd_join": ">> Joining without password (room code is the only credential)",
    "log_nopwd_switch": ">> Switched to no-password room: leave the password empty",
    "log_edge_start": ">> Starting edge: room=%(room)s  virtual IP=%(ip)s",
    "log_supernode": ">> supernode: %(sn)s",
    "log_edge_pid": ">> edge started (pid=%(pid)s), waiting to register...",
    "log_left": ">> Left the room",
    "log_copy_pwd": ">> Room code copied; send the password separately (copy from the 'Room Password' box)",
    "log_copy_nopwd": ">> No-password room; room code copied, send it to your friend",
    "log_copy_link": ">> Mobile join link copied — send it to your friend (requires TCP 25565 port-forward to this PC)",
    "log_fw_ok": ">> edge.exe inbound allowed (click Yes if UAC appears)",
    "log_fw_cancel": ">> Firewall rule add cancelled",
}

LANGUAGES = {"zh": LANG_ZH, "en": LANG_EN}

# 当前语言（启动时由 App 按配置/系统语言设置）
_lang = "zh"


def detect_lang():
    """按 Windows 系统 UI 语言检测：中文系统默认中文，其余默认英文。"""
    try:
        ui = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "zh" if (ui & 0xFFFF) == 0x0804 else "en"
    except Exception:
        return "en"


def tr(key, **kw):
    """取当前语言文案；未定义 key 时回退英文再回退原文。"""
    table = LANGUAGES.get(_lang, LANG_EN)
    s = table.get(key, LANG_EN.get(key, key))
    if kw:
        try:
            s = s % kw
        except Exception:
            pass
    return s

_WORDS = [
    "pixel", "creeper", "ender", "nether", "craft", "block", "sword",
    "pick", "axe", "diamond", "iron", "gold", "redstone", "lava",
    "water", "stone", "wood", "sand", "cave", "mob", "torch", "pig",
]


# ----------------------------------------------------------------------------
# 配置存取
# ----------------------------------------------------------------------------
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = dict(DEFAULT_CONFIG)
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 房间码 / IP 逻辑
# ----------------------------------------------------------------------------
def gen_community():
    w1 = random.choice(_WORDS)
    w2 = random.choice([w for w in _WORDS if w != w1])
    return "mc-%s-%s-%d" % (w1, w2, random.randint(1000, 9999))


def gen_subnet(cfg):
    used_x = set()
    for r in cfg.get("rooms", {}).values():
        m = RE_SUBNET.match(r.get("subnet", ""))
        if m:
            used_x.add(int(m.group(1)))
    pool = [x for x in range(2, 255) if x not in used_x]
    if not pool:
        pool = [x for x in range(2, 255)]
    return "10.%d.0" % random.choice(pool)


def gen_key():
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))


def make_room_code(community, subnet, key):
    return "%s@%s#%s" % (community, subnet, key)


def gen_password():
    """生成 6 位数字房间密码（开黑房风格，方便口头/聊天传递）。"""
    return "%06d" % random.randint(0, 999999)


def derive_key(key, password):
    """房间密码参与 n2n 加密密钥派生。

    密码为空时回退为房间码自带密钥（兼容无密码流程）；
    密码非空时，最终密钥 = sha256(房间码密钥:密码)[:16]。
    密码错误 -> 密钥不同 -> 无法解密对端流量 -> 等同于进不来。
    """
    if not password:
        return key
    return hashlib.sha256(("%s:%s" % (key, password)).encode("utf-8")).hexdigest()[:16]


def parse_room_code(code):
    """返回 (community, subnet, key) 或 None"""
    code = (code or "").strip()
    m = RE_ROOM_CODE.match(code)
    if not m:
        return None
    community, subnet, key = m.group(1), m.group(2), m.group(3)
    sm = RE_SUBNET.match(subnet)
    x = int(sm.group(1))
    if x < 2 or x > 254:
        return None
    return community, subnet, key


def suggest_ip(subnet, cfg):
    used = set()
    for r in cfg.get("rooms", {}).values():
        if r.get("subnet") == subnet and r.get("my_ip"):
            tail = r["my_ip"].rsplit(".", 1)[-1]
            if tail.isdigit():
                used.add(int(tail))
    host = 2
    while host in used and host < 255:
        host += 1
    return "%s.%d" % (subnet, host)


def validate_ip(ip):
    m = re.match(r"^10\.(\d{1,3})\.0\.(\d{1,3})$", ip or "")
    if not m:
        return False
    x, h = int(m.group(1)), int(m.group(2))
    return 2 <= x <= 254 and 1 <= h <= 254


# ----------------------------------------------------------------------------
# 手机进房链接
# ----------------------------------------------------------------------------
JOIN_PAGE = "https://zgs7157.github.io/n2n-lan/join.html"


def make_join_link(host, port=25565, room="开黑房"):
    """生成手机进房页链接：?ip=<公网IP>&port=<MC端口>&room=<房间名>"""
    return "%s?ip=%s&port=%d&room=%s" % (
        JOIN_PAGE,
        urllib.parse.quote(str(host).strip(), safe=""),
        int(port),
        urllib.parse.quote(str(room).strip(), safe=""),
    )


# ----------------------------------------------------------------------------
# 系统工具：驱动 / 防火墙 / 提权
# ----------------------------------------------------------------------------
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_elevated(exe, args, workdir=None, wait=False):
    """以管理员权限运行，弹出 UAC 确认。返回 True 表示成功发起。"""
    try:
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, workdir or "", 0)
        return res > 32
    except Exception:
        return False


def tap_driver_installed():
    """检测是否已安装 TAP-Windows 虚拟网卡驱动（tap0901）。"""
    ps = (
        "(Get-NetAdapter -ErrorAction SilentlyContinue | "
        "Where-Object { $_.InterfaceDescription -like '*TAP*' -or $_.Name -like '*TAP*' } | "
        "Measure-Object).Count"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        if out.isdigit():
            return int(out) > 0
    except Exception:
        pass
    # 兜底：检查设备管理器中的驱动服务
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_SystemDriver -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'tap*' }).Count"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        if out.isdigit():
            return int(out) > 0
    except Exception:
        pass
    return False


def install_tap_driver():
    """静默安装 TAP-Windows 驱动。优先 tapinstall，失败则用官方安装器。"""
    if tap_driver_installed():
        return "already"
    ok = run_elevated(os.path.join(DRIVER_DIR, "tapinstall.exe"),
                      'install "%s" tap0901' % TAP_INF,
                      workdir=DRIVER_DIR, wait=True)
    time.sleep(4)
    if tap_driver_installed():
        return "ok"
    if os.path.exists(TAP_INSTALLER):
        ok = run_elevated(TAP_INSTALLER, "/S", workdir=os.path.dirname(TAP_INSTALLER), wait=True) or ok
        time.sleep(6)
        if tap_driver_installed():
            return "ok"
    return "fail" if ok else "denied"


def add_firewall_rule():
    rule = 'advfirewall firewall add rule name="n2n edge room" dir=in action=allow program="%s"' % EDGE_EXE
    return run_elevated("netsh", rule, wait=False)


def get_tap_ip():
    """读取 TAP 网卡当前 IPv4 地址（可能为空）。
    用 Get-NetIPConfiguration 按接口描述过滤：Get-NetIPAddress 对
    老式 TAP(NDIS6) 驱动不暴露 InterfaceDescription，会查不到。"""
    ps = (
        "(Get-NetIPConfiguration -ErrorAction SilentlyContinue | "
        "Where-Object { $_.InterfaceDescription -like '*TAP*' } | "
        "ForEach-Object { $_.IPv4Address.IPAddress }) -join ', '"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        return out
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# edge 进程与日志
# ----------------------------------------------------------------------------
class LogTailer(threading.Thread):
    """跟踪 edge 日志文件尾部，把新行回调给 GUI。"""

    def __init__(self, path, on_line):
        super().__init__(daemon=True)
        self._path = path
        self._on_line = on_line
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            with open(self._path, "rb") as f:
                f.seek(0, 2)
                while not self._stop.is_set():
                    data = f.read()
                    if data:
                        for line in data.splitlines():
                            if line.strip():
                                self._on_line(line.decode("utf-8", "replace"))
                    time.sleep(0.4)
        except Exception:
            pass


class EdgeSession:
    """一个 edge 会话：启动 / 停止 / 状态。"""

    def __init__(self, app):
        self.app = app
        self.proc = None
        self.tailer = None
        self.log_path = None
        self.broadcast_proc = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, community, key, ip, supernode_list):
        self.stop()
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(LOG_DIR, "edge_%s.log" % re.sub(r"[^A-Za-z0-9_-]", "_", community))

        args = [EDGE_EXE, "-c", community, "-k", key, "-a", ip + "/24"]
        for sn in supernode_list:
            sn = sn.strip()
            if sn:
                args += ["-l", sn]
        cfg = self.app.cfg
        if cfg.get("use_multicast", True):
            args.append("-E")
        if cfg.get("use_game_metric", True):
            args += ["-x", "1"]
        args += ["-M", str(int(cfg.get("mtu", DEFAULT_MTU))), "-I", "room-" + community]

        logf = open(self.log_path, "ab", buffering=0)
        self.proc = subprocess.Popen(
            args,
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.tailer = LogTailer(self.log_path, self.app.append_log)
        self.tailer.start()

        if cfg.get("auto_broadcast") and os.path.exists(WINIPBROADCAST_EXE):
            try:
                self.broadcast_proc = subprocess.Popen(
                    [WINIPBROADCAST_EXE], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                self.broadcast_proc = None
        return self.proc.pid

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass
            self.proc = None
        if self.tailer is not None:
            self.tailer.stop()
            self.tailer = None
        if self.broadcast_proc is not None:
            try:
                self.broadcast_proc.terminate()
            except Exception:
                pass
            self.broadcast_proc = None


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.session = EdgeSession(self)
        self._connected = None
        self._log_lines = []

        # 界面语言：配置优先，否则按系统语言
        global _lang
        _lang = self.cfg.get("lang") or detect_lang()
        if _lang not in LANGUAGES:
            _lang = "en"

        root.title(tr("app_title"))
        root.geometry("760x650")
        root.minsize(680, 580)

        self._build_ui()
        self._apply_cfg_to_ui()
        self._refresh_timer()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 服务器
        f_server = ttk.LabelFrame(self.root, text=tr("server_frame"))
        f_server.pack(fill="x", **pad)
        self.var_supernode = tk.StringVar()
        ttk.Entry(f_server, textvariable=self.var_supernode, width=46).pack(side="left", padx=6, pady=6)
        ttk.Button(f_server, text=tr("save"), command=self.save_supernode).pack(side="left", padx=4)
        ttk.Label(f_server, text=tr("server_fmt"), foreground="#666").pack(side="left", padx=6)

        # 房间操作
        f_room = ttk.LabelFrame(self.root, text=tr("room_frame"))
        f_room.pack(fill="x", **pad)
        row1 = ttk.Frame(f_room)
        row1.pack(fill="x", padx=6, pady=4)
        self.btn_create = ttk.Button(row1, text=tr("create_room"), command=self.create_room)
        self.btn_create.pack(side="left", padx=2)
        self.var_use_pwd = tk.BooleanVar(value=True)
        self.chk_pwd = ttk.Checkbutton(row1, text=tr("with_pwd"), variable=self.var_use_pwd,
                                       command=self.toggle_use_pwd)
        self.chk_pwd.pack(side="left", padx=2)
        self.btn_join = ttk.Button(row1, text=tr("join_room"), command=self.join_room)
        self.btn_join.pack(side="left", padx=2)
        self.btn_leave = ttk.Button(row1, text=tr("leave_room"), command=self.leave_room, state="disabled")
        self.btn_leave.pack(side="left", padx=2)
        self.btn_copy = ttk.Button(row1, text=tr("copy_code"), command=self.copy_code, state="disabled")
        self.btn_copy.pack(side="left", padx=2)
        self.btn_link = ttk.Button(row1, text=tr("copy_link"), command=self.copy_join_link)
        self.btn_link.pack(side="left", padx=2)

        row2 = ttk.Frame(f_room)
        row2.pack(fill="x", padx=6, pady=2)
        ttk.Label(row2, text=tr("room_code")).pack(side="left")
        self.var_code = tk.StringVar()
        ttk.Entry(row2, textvariable=self.var_code, width=52).pack(side="left", padx=6)

        row2p = ttk.Frame(f_room)
        row2p.pack(fill="x", padx=6, pady=2)
        ttk.Label(row2p, text=tr("room_pwd")).pack(side="left")
        self.var_pwd = tk.StringVar()
        ttk.Entry(row2p, textvariable=self.var_pwd, width=12).pack(side="left", padx=6)
        ttk.Label(row2p, text=tr("pwd_hint"), foreground="#666").pack(side="left", padx=4)

        row3 = ttk.Frame(f_room)
        row3.pack(fill="x", padx=6, pady=4)
        ttk.Label(row3, text=tr("my_ip")).pack(side="left")
        self.var_ip = tk.StringVar()
        ttk.Entry(row3, textvariable=self.var_ip, width=20).pack(side="left", padx=6)
        ttk.Label(row3, text=tr("ip_hint"), foreground="#666").pack(side="left", padx=4)

        # 状态
        f_status = ttk.LabelFrame(self.root, text=tr("status_frame"))
        f_status.pack(fill="x", **pad)
        self.lbl_state = ttk.Label(f_status, text=tr("disconnected"), foreground="#333")
        self.lbl_state.pack(side="left", padx=8, pady=6)
        self.lbl_ip = ttk.Label(f_status, text=tr("virtual_ip"), foreground="#333")
        self.lbl_ip.pack(side="left", padx=8)
        self.lbl_room = ttk.Label(f_status, text=tr("room"), foreground="#333")
        self.lbl_room.pack(side="left", padx=8)

        # 日志
        f_log = ttk.LabelFrame(self.root, text=tr("log_frame"))
        f_log.pack(fill="both", expand=True, **pad)
        self.txt_log = scrolledtext.ScrolledText(f_log, height=12, state="disabled", font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

        # 工具 + 设置
        f_tool = ttk.LabelFrame(self.root, text=tr("tools_frame"))
        f_tool.pack(fill="x", **pad)
        ttk.Button(f_tool, text=tr("install_driver"), command=self.cmd_install_driver).pack(side="left", padx=3, pady=5)
        ttk.Button(f_tool, text=tr("firewall"), command=self.cmd_firewall).pack(side="left", padx=3)
        ttk.Button(f_tool, text=tr("open_logs"), command=self.open_logs).pack(side="left", padx=3)
        ttk.Button(f_tool, text=tr("open_bin"), command=self.open_bin).pack(side="left", padx=3)
        ttk.Label(f_tool, text=tr("lang")).pack(side="left", padx=(10, 2))
        self.var_lang = tk.StringVar(value=_lang)
        cmb_lang = ttk.Combobox(f_tool, textvariable=self.var_lang, values=["zh", "en"], width=4, state="readonly")
        cmb_lang.pack(side="left", padx=2)
        cmb_lang.bind("<<ComboboxSelected>>", self.on_lang_change)

        self.var_multicast = tk.BooleanVar(value=True)
        self.var_metric = tk.BooleanVar(value=True)
        self.var_bcast = tk.BooleanVar(value=False)
        ttk.Checkbutton(f_tool, text=tr("opt_multicast"), variable=self.var_multicast,
                        command=self.save_settings).pack(side="left", padx=6)
        ttk.Checkbutton(f_tool, text=tr("opt_metric"), variable=self.var_metric,
                        command=self.save_settings).pack(side="left", padx=6)
        ttk.Checkbutton(f_tool, text=tr("opt_bcast"), variable=self.var_bcast,
                        command=self.save_settings).pack(side="left", padx=6)

    def on_lang_change(self, _event=None):
        global _lang
        new_lang = self.var_lang.get() if self.var_lang.get() in LANGUAGES else "en"
        _lang = new_lang
        self.cfg["lang"] = new_lang
        save_config(self.cfg)
        self.append_log(tr("lang_switch"))
        # 简单提示重启生效
        messagebox.showinfo(tr("info"), tr("lang_switch") + (" | " + LANG_EN["lang_switch"] if new_lang == "en" else ""))

    def _apply_cfg_to_ui(self):
        self.var_supernode.set(self.cfg.get("supernode", ""))
        self.var_multicast.set(bool(self.cfg.get("use_multicast", True)))
        self.var_metric.set(bool(self.cfg.get("use_game_metric", True)))
        self.var_bcast.set(bool(self.cfg.get("auto_broadcast", False)))

    # ---------------- 配置 ----------------
    def save_supernode(self):
        self.cfg["supernode"] = self.var_supernode.get().strip()
        save_config(self.cfg)
        self.append_log(tr("log_server_saved", sn=self.cfg["supernode"]))

    def save_settings(self):
        self.cfg["use_multicast"] = bool(self.var_multicast.get())
        self.cfg["use_game_metric"] = bool(self.var_metric.get())
        self.cfg["auto_broadcast"] = bool(self.var_bcast.get())
        save_config(self.cfg)

    # ---------------- 房间操作 ----------------
    def toggle_use_pwd(self):
        if not self.var_use_pwd.get():
            self.var_pwd.set("")
            self.append_log(tr("log_nopwd_switch"))

    def create_room(self):
        if not self._check_supernode():
            return
        if self.session.running:
            messagebox.showinfo(tr("info"), tr("leave_first"))
            return
        if not tap_driver_installed():
            if not messagebox.askyesno(tr("no_driver"), tr("no_driver_msg")):
                return
            res = install_tap_driver()
            if res == "denied":
                messagebox.showerror(tr("not_installed"), tr("denied_msg"))
                return
            if res == "fail":
                messagebox.showerror(tr("install_fail"), tr("install_fail_msg"))
                return
            self.append_log(tr("log_driver_ready"))

        community = gen_community()
        subnet = gen_subnet(self.cfg)
        key = gen_key()
        my_ip = subnet + ".1"
        code = make_room_code(community, subnet, key)

        pwd = ""
        if self.var_use_pwd.get():
            pwd = gen_password()
            self.var_pwd.set(pwd)
            self.append_log(tr("log_pwd_gen", pwd=pwd))
        else:
            self.var_pwd.set("")
            self.append_log(tr("log_nopwd_room"))

        self.cfg.setdefault("rooms", {})[community] = {
            "subnet": subnet, "key": key, "my_ip": my_ip, "last_host": 2,
            "password": pwd,
        }
        save_config(self.cfg)

        self.var_code.set(code)
        self.var_ip.set(my_ip)
        eff_key = derive_key(key, pwd)
        self._start_edge(community, eff_key, my_ip, code)

    def join_room(self):
        if not self._check_supernode():
            return
        if self.session.running:
            messagebox.showinfo(tr("info"), tr("leave_first"))
            return
        parsed = parse_room_code(self.var_code.get())
        if not parsed:
            messagebox.showerror(tr("bad_code"), tr("bad_code_msg"))
            return
        community, subnet, key = parsed
        pwd = self.var_pwd.get().strip()
        if pwd:
            self.append_log(tr("log_pwd_join"))
        else:
            self.append_log(tr("log_nopwd_join"))

        my_ip = self.var_ip.get().strip()
        if not my_ip or my_ip == "10.x.0.?":
            my_ip = suggest_ip(subnet, self.cfg)
        if not validate_ip(my_ip):
            messagebox.showerror(tr("bad_ip"), tr("bad_ip_msg"))
            return
        if my_ip.rsplit(".", 1)[0] != subnet:
            messagebox.showerror(tr("subnet_mismatch"), tr("subnet_mismatch_msg", subnet=subnet))
            return

        self.cfg.setdefault("rooms", {})[community] = {
            "subnet": subnet, "key": key, "my_ip": my_ip, "last_host": int(my_ip.rsplit(".", 1)[1]),
            "password": pwd,
        }
        save_config(self.cfg)
        eff_key = derive_key(key, pwd)
        self._start_edge(community, eff_key, my_ip, self.var_code.get().strip())

    def _check_supernode(self):
        sn = self.var_supernode.get().strip()
        if not sn:
            messagebox.showerror(tr("no_server"), tr("no_server_msg"))
            return False
        self.cfg["supernode"] = sn
        save_config(self.cfg)
        return True

    def _start_edge(self, community, key, ip, code):
        sn_list = [s for s in self.cfg["supernode"].split(",") if s.strip()]
        self.append_log(tr("log_edge_start", room=community, ip=ip))
        self.append_log(tr("log_supernode", sn=", ".join(sn_list)))
        pid = self.session.start(community, key, ip, sn_list)
        self.append_log(tr("log_edge_pid", pid=pid))
        self._connected = {"community": community, "code": code}
        self.btn_create.config(state="disabled")
        self.btn_join.config(state="disabled")
        self.btn_leave.config(state="normal")
        self.btn_copy.config(state="normal")
        self.lbl_room.config(text=tr("room") + " " + code)

    def leave_room(self):
        self.session.stop()
        self._connected = None
        self.btn_create.config(state="normal")
        self.btn_join.config(state="normal")
        self.btn_leave.config(state="disabled")
        self.btn_copy.config(state="disabled")
        self.lbl_state.config(text=tr("disconnected"))
        self.lbl_ip.config(text=tr("virtual_ip"))
        self.lbl_room.config(text=tr("room"))
        self.append_log(tr("log_left"))

    def copy_code(self):
        if self._connected:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._connected["code"])
            pwd = self.var_pwd.get().strip()
            if pwd:
                self.append_log(tr("log_copy_pwd"))
            else:
                self.append_log(tr("log_copy_nopwd"))

    def copy_join_link(self):
        """复制手机进房链接：朋友手机打开即可看到地址并复制进 FCL。"""
        sn = self.var_supernode.get().strip()
        if not sn:
            messagebox.showerror(tr("no_server"), tr("no_server_msg"))
            return
        host = sn.split(",")[0].strip()
        if ":" in host:
            host = host.split(":")[0]
        if not host:
            messagebox.showerror(tr("no_server"), tr("no_server_msg"))
            return
        room = self._connected["community"] if self._connected else "开黑房"
        link = make_join_link(host, 25565, room)
        self.root.clipboard_clear()
        self.root.clipboard_append(link)
        self.append_log(tr("log_copy_link"))

    # ---------------- 工具按钮 ----------------
    def cmd_install_driver(self):
        if tap_driver_installed():
            messagebox.showinfo(tr("check_result"), tr("driver_ok"))
            return
        res = install_tap_driver()
        if res == "already":
            messagebox.showinfo(tr("check_result"), tr("driver_ok"))
        elif res == "ok":
            messagebox.showinfo(tr("installed_ok"), tr("installed_ok_msg"))
        elif res == "denied":
            messagebox.showerror(tr("not_installed"), tr("uac_cancel"))
        else:
            messagebox.showerror(tr("install_fail"), tr("silent_fail_msg"))

    def cmd_firewall(self):
        ok = add_firewall_rule()
        if ok:
            self.append_log(tr("log_fw_ok"))
        else:
            self.append_log(tr("log_fw_cancel"))

    def open_logs(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        os.startfile(LOG_DIR)

    def open_bin(self):
        os.startfile(os.path.join(BASE_DIR, "bin"))

    # ---------------- 日志 / 状态刷新 ----------------
    def append_log(self, line):
        self._log_lines.append(line)
        if len(self._log_lines) > 600:
            self._log_lines = self._log_lines[-600:]
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _refresh_timer(self):
        try:
            if self.session.running:
                self.lbl_state.config(text=tr("connected"), foreground="#1a7f37")
            else:
                self.lbl_state.config(text=tr("disconnected"), foreground="#333")
            tap_ip = get_tap_ip()
            if tap_ip:
                self.lbl_ip.config(text=tr("virtual_ip").replace("-", tap_ip))
            elif self.session.running:
                self.lbl_ip.config(text="Virtual IP: waiting..." if _lang == "en" else "虚拟IP: 等待分配…")
        except Exception:
            pass
        self.root.after(2000, self._refresh_timer)


# ----------------------------------------------------------------------------
# 自检模式（无 GUI）：验证环境与房间码逻辑
# ----------------------------------------------------------------------------
def selftest():
    print("== n2n 房间管理小工具 自检 ==")
    print("Python:", sys.version.split()[0])
    print("edge.exe 存在:", os.path.exists(EDGE_EXE))
    print("驱动目录存在:", os.path.exists(TAP_INF))
    print("TAP 驱动已安装:", tap_driver_installed())
    code = make_room_code("mc-pixel-creeper-1234", "10.88.0", "Ab3CdEfGhJ")
    print("生成房间码示例:", code)
    print("解析结果:", parse_room_code(code))
    print("非法房间码解析:", parse_room_code("badcode"))
    print("密码派生(带密码 123456):", derive_key("Ab3CdEfGhJ", "123456"))
    print("密码派生(免密):", derive_key("Ab3CdEfGhJ", ""))
    print("密码不同则密钥不同:", derive_key("Ab3CdEfGhJ", "123456") != derive_key("Ab3CdEfGhJ", "654321"))
    print("IP 建议(10.88.0):", suggest_ip("10.88.0", DEFAULT_CONFIG))
    print("IP 校验 10.9.0.3:", validate_ip("10.9.0.3"), "| 10.9.1.3:", validate_ip("10.9.1.3"))
    print("手机进房链接:", make_join_link("39.162.81.68", 25565, "mc-pixel-creeper-1234"))
    print("== 自检完成 ==")


def main():
    ap = argparse.ArgumentParser(description="n2n 房间管理小工具")
    ap.add_argument("--selftest", action="store_true", help="环境与逻辑自检，不打开界面")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
