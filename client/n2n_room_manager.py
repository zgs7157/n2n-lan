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
    "rooms": {},              # community -> {"subnet": "...", "key": "...", "my_ip": "...", "last_host": 2}
}

RE_ROOM_CODE = re.compile(r"^([A-Za-z0-9_-]{3,32})@(10\.\d{1,3}\.0)#([A-Za-z0-9]{6,16})$")
RE_SUBNET = re.compile(r"^10\.(\d{1,3})\.0$")

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

        root.title("n2n 房间管理小工具")
        root.geometry("760x650")
        root.minsize(680, 580)

        self._build_ui()
        self._apply_cfg_to_ui()
        self._refresh_timer()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 服务器
        f_server = ttk.LabelFrame(self.root, text="服务器（公网 supernode）")
        f_server.pack(fill="x", **pad)
        self.var_supernode = tk.StringVar()
        ttk.Entry(f_server, textvariable=self.var_supernode, width=46).pack(side="left", padx=6, pady=6)
        ttk.Button(f_server, text="保存", command=self.save_supernode).pack(side="left", padx=4)
        ttk.Label(f_server, text="格式 IP:端口，多个用逗号分隔", foreground="#666").pack(side="left", padx=6)

        # 房间操作
        f_room = ttk.LabelFrame(self.root, text="房间")
        f_room.pack(fill="x", **pad)
        row1 = ttk.Frame(f_room)
        row1.pack(fill="x", padx=6, pady=4)
        self.btn_create = ttk.Button(row1, text="创建房间（我是房主）", command=self.create_room)
        self.btn_create.pack(side="left", padx=2)
        self.var_use_pwd = tk.BooleanVar(value=True)
        self.chk_pwd = ttk.Checkbutton(row1, text="带密码", variable=self.var_use_pwd,
                                       command=self.toggle_use_pwd)
        self.chk_pwd.pack(side="left", padx=2)
        self.btn_join = ttk.Button(row1, text="加入房间", command=self.join_room)
        self.btn_join.pack(side="left", padx=2)
        self.btn_leave = ttk.Button(row1, text="退出房间", command=self.leave_room, state="disabled")
        self.btn_leave.pack(side="left", padx=2)
        self.btn_copy = ttk.Button(row1, text="复制房间码", command=self.copy_code, state="disabled")
        self.btn_copy.pack(side="left", padx=2)

        row2 = ttk.Frame(f_room)
        row2.pack(fill="x", padx=6, pady=2)
        ttk.Label(row2, text="房间码").pack(side="left")
        self.var_code = tk.StringVar()
        ttk.Entry(row2, textvariable=self.var_code, width=52).pack(side="left", padx=6)

        row2p = ttk.Frame(f_room)
        row2p.pack(fill="x", padx=6, pady=2)
        ttk.Label(row2p, text="房间密码").pack(side="left")
        self.var_pwd = tk.StringVar()
        ttk.Entry(row2p, textvariable=self.var_pwd, width=12).pack(side="left", padx=6)
        ttk.Label(row2p, text="房主创建后自动生成；好友加入时填房主单独发的密码，填错进不来；免密房留空",
                  foreground="#666").pack(side="left", padx=4)

        row3 = ttk.Frame(f_room)
        row3.pack(fill="x", padx=6, pady=4)
        ttk.Label(row3, text="我的虚拟IP").pack(side="left")
        self.var_ip = tk.StringVar()
        ttk.Entry(row3, textvariable=self.var_ip, width=20).pack(side="left", padx=6)
        ttk.Label(row3, text="加入房间时自动建议空闲IP，可手动改", foreground="#666").pack(side="left", padx=4)

        # 状态
        f_status = ttk.LabelFrame(self.root, text="状态")
        f_status.pack(fill="x", **pad)
        self.lbl_state = ttk.Label(f_status, text="未连接", foreground="#333")
        self.lbl_state.pack(side="left", padx=8, pady=6)
        self.lbl_ip = ttk.Label(f_status, text="虚拟IP: -", foreground="#333")
        self.lbl_ip.pack(side="left", padx=8)
        self.lbl_room = ttk.Label(f_status, text="房间: -", foreground="#333")
        self.lbl_room.pack(side="left", padx=8)

        # 日志
        f_log = ttk.LabelFrame(self.root, text="edge 运行日志")
        f_log.pack(fill="both", expand=True, **pad)
        self.txt_log = scrolledtext.ScrolledText(f_log, height=12, state="disabled", font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

        # 工具 + 设置
        f_tool = ttk.LabelFrame(self.root, text="工具与设置")
        f_tool.pack(fill="x", **pad)
        ttk.Button(f_tool, text="安装/检测虚拟网卡驱动", command=self.cmd_install_driver).pack(side="left", padx=3, pady=5)
        ttk.Button(f_tool, text="防火墙放行 edge", command=self.cmd_firewall).pack(side="left", padx=3)
        ttk.Button(f_tool, text="打开日志目录", command=self.open_logs).pack(side="left", padx=3)
        ttk.Button(f_tool, text="打开 bin 目录", command=self.open_bin).pack(side="left", padx=3)

        self.var_multicast = tk.BooleanVar(value=True)
        self.var_metric = tk.BooleanVar(value=True)
        self.var_bcast = tk.BooleanVar(value=False)
        ttk.Checkbutton(f_tool, text="接受组播(-E, 局域网发现)", variable=self.var_multicast,
                        command=self.save_settings).pack(side="left", padx=6)
        ttk.Checkbutton(f_tool, text="游戏识别(-x 1)", variable=self.var_metric,
                        command=self.save_settings).pack(side="left", padx=6)
        ttk.Checkbutton(f_tool, text="自动启动广播助手", variable=self.var_bcast,
                        command=self.save_settings).pack(side="left", padx=6)

    def _apply_cfg_to_ui(self):
        self.var_supernode.set(self.cfg.get("supernode", ""))
        self.var_multicast.set(bool(self.cfg.get("use_multicast", True)))
        self.var_metric.set(bool(self.cfg.get("use_game_metric", True)))
        self.var_bcast.set(bool(self.cfg.get("auto_broadcast", False)))

    # ---------------- 配置 ----------------
    def save_supernode(self):
        self.cfg["supernode"] = self.var_supernode.get().strip()
        save_config(self.cfg)
        self.append_log(">> 已保存服务器地址: %s" % self.cfg["supernode"])

    def save_settings(self):
        self.cfg["use_multicast"] = bool(self.var_multicast.get())
        self.cfg["use_game_metric"] = bool(self.var_metric.get())
        self.cfg["auto_broadcast"] = bool(self.var_bcast.get())
        save_config(self.cfg)

    # ---------------- 房间操作 ----------------
    def toggle_use_pwd(self):
        if not self.var_use_pwd.get():
            self.var_pwd.set("")
            self.append_log(">> 已切换为免密房间：创建/加入时密码留空即可")

    def create_room(self):
        if not self._check_supernode():
            return
        if self.session.running:
            messagebox.showinfo("提示", "请先退出当前房间")
            return
        if not tap_driver_installed():
            if not messagebox.askyesno("缺少虚拟网卡驱动",
                                       "未检测到 TAP 虚拟网卡驱动，进房前需要先安装。\n现在安装？（需要管理员权限，会弹出 UAC 确认）"):
                return
            res = install_tap_driver()
            if res == "denied":
                messagebox.showerror("未安装", "安装被拒绝，请点上方“安装/检测虚拟网卡驱动”手动操作")
                return
            if res == "fail":
                messagebox.showerror("安装失败", "驱动安装失败，请手动运行 driver/tap-windows/9.24.7.exe 安装")
                return
            self.append_log(">> 虚拟网卡驱动已就绪")

        community = gen_community()
        subnet = gen_subnet(self.cfg)
        key = gen_key()
        my_ip = subnet + ".1"
        code = make_room_code(community, subnet, key)

        pwd = ""
        if self.var_use_pwd.get():
            pwd = gen_password()
            self.var_pwd.set(pwd)
            self.append_log(">> 房间密码: %s（请单独发给好友，密码不对进不来）" % pwd)
        else:
            self.var_pwd.set("")
            self.append_log(">> 免密房间：房间码即全部凭证")

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
            messagebox.showinfo("提示", "请先退出当前房间")
            return
        parsed = parse_room_code(self.var_code.get())
        if not parsed:
            messagebox.showerror("房间码无效", "房间码格式应为：community@10.x.0#密钥\n请向房主索取完整的房间码")
            return
        community, subnet, key = parsed
        pwd = self.var_pwd.get().strip()
        if pwd:
            self.append_log(">> 使用房间密码派生密钥（密码错误将无法互通）")
        else:
            self.append_log(">> 免密加入（房间码即全部凭证）")

        my_ip = self.var_ip.get().strip()
        if not my_ip or my_ip == "10.x.0.?":
            my_ip = suggest_ip(subnet, self.cfg)
        if not validate_ip(my_ip):
            messagebox.showerror("IP 无效", "虚拟IP 应为 10.x.0.1~254 的形式")
            return
        if my_ip.rsplit(".", 1)[0] != subnet:
            messagebox.showerror("网段不符", "虚拟IP 必须与房间码中的网段 %s 一致" % subnet)
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
            messagebox.showerror("未配置服务器", "请先填写公网 supernode 地址（IP:端口）并保存")
            return False
        self.cfg["supernode"] = sn
        save_config(self.cfg)
        return True

    def _start_edge(self, community, key, ip, code):
        sn_list = [s for s in self.cfg["supernode"].split(",") if s.strip()]
        self.append_log(">> 启动 edge：房间=%s  虚拟IP=%s" % (community, ip))
        self.append_log(">> supernode: %s" % ", ".join(sn_list))
        pid = self.session.start(community, key, ip, sn_list)
        self.append_log(">> edge 已启动 (pid=%s)，等待注册…" % pid)
        self._connected = {"community": community, "code": code}
        self.btn_create.config(state="disabled")
        self.btn_join.config(state="disabled")
        self.btn_leave.config(state="normal")
        self.btn_copy.config(state="normal")
        self.lbl_room.config(text="房间: " + code)

    def leave_room(self):
        self.session.stop()
        self._connected = None
        self.btn_create.config(state="normal")
        self.btn_join.config(state="normal")
        self.btn_leave.config(state="disabled")
        self.btn_copy.config(state="disabled")
        self.lbl_state.config(text="未连接")
        self.lbl_ip.config(text="虚拟IP: -")
        self.lbl_room.config(text="房间: -")
        self.append_log(">> 已退出房间")

    def copy_code(self):
        if self._connected:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._connected["code"])
            pwd = self.var_pwd.get().strip()
            if pwd:
                self.append_log(">> 房间码已复制；房间密码需单独发给好友（在“房间密码”框里复制）")
            else:
                self.append_log(">> 免密房间，房间码已复制，发给好友即可加入")

    # ---------------- 工具按钮 ----------------
    def cmd_install_driver(self):
        if tap_driver_installed():
            messagebox.showinfo("检查结果", "虚拟网卡驱动已安装（TAP-Windows Adapter V9）")
            return
        res = install_tap_driver()
        if res == "already":
            messagebox.showinfo("检查结果", "虚拟网卡驱动已安装（TAP-Windows Adapter V9）")
        elif res == "ok":
            messagebox.showinfo("安装成功", "TAP 虚拟网卡驱动安装完成")
        elif res == "denied":
            messagebox.showerror("未安装", "UAC 确认被取消，未安装驱动")
        else:
            messagebox.showerror("安装失败", "静默安装失败，请手动运行 driver/tap-windows/9.24.7.exe 安装")

    def cmd_firewall(self):
        ok = add_firewall_rule()
        if ok:
            self.append_log(">> 已放行 edge.exe 入站（若弹出 UAC 请点“是”）")
        else:
            self.append_log(">> 防火墙规则添加被取消")

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
                self.lbl_state.config(text="已连接（edge 运行中）", foreground="#1a7f37")
            else:
                self.lbl_state.config(text="未连接", foreground="#333")
            tap_ip = get_tap_ip()
            if tap_ip:
                self.lbl_ip.config(text="虚拟IP: " + tap_ip)
            elif self.session.running:
                self.lbl_ip.config(text="虚拟IP: 等待分配…")
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
