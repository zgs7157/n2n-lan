#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
n2n 房间管理小工具 (N2N Room Manager)
=====================================
基于 n2n v3 的“房间式”虚拟局域网客户端。

- 房主“创建房间”：自动生成 房间码 = community@网段#密钥，并以网段 .1 作为房主虚拟 IP 启动 edge。
- 好友“加入房间”：粘贴房间码，自动建议空闲虚拟 IP，启动 edge 加入同一 community。
- 底层封装 n2n edge（n2n v3.1.1），自带虚拟网卡驱动检测与防火墙放行。
- 跨平台：Windows 10/11 x64（TAP-Windows 驱动 + start.bat）；
  macOS（tuntap 驱动 + start_mac.sh，Intel 与 Apple 芯片均可源码运行）；
  Linux（TUN/TAP + start_linux.sh）。

运行环境：Windows / macOS / Linux，Python 3（本工具仅用标准库）。Windows 双击 start.bat 启动。
"""

import argparse
import ctypes
import hashlib
import ipaddress
import json
import os
import random
import re
import secrets
import socket
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# 二维码：可选依赖（qrcode + pypng，纯 Python 写 PNG），缺失时自动隐藏该功能
try:
    import qrcode
    import qrcode.image.pure as qr_pure
    HAS_QR = True
except Exception:
    HAS_QR = False

# 房间在线成员 / 局域网房间发现（纯标准库，缺失时功能静默降级）
try:
    import room_presence
except Exception:
    room_presence = None

# ----------------------------------------------------------------------------
# 平台判断
# ----------------------------------------------------------------------------
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_POSIX = (IS_MACOS or IS_LINUX)

# ----------------------------------------------------------------------------
# 常量与路径
# ----------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # PyInstaller 打包成 exe 后：__file__ 指向临时解包目录，
    # 资源（bin/driver/tools）位于 exe 同目录，须以 exe 所在目录为基准。
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# edge 可执行名：Windows 为 edge.exe，macOS/Linux 为 edge（无扩展名，自行编译或 brew/apt 安装）
EDGE_EXE = os.path.join(BASE_DIR, "bin", "edge.exe" if IS_WINDOWS else "edge")
# IPv6 转发器：Windows 用打包好的 exe；macOS/Linux 用同目录源码（纯标准库，python3 直跑）
FORWARDER_EXE = os.path.join(BASE_DIR, "bin", "udp6_client_forward.exe")
FORWARDER_PY = os.path.join(BASE_DIR, "udp6_client_forward.py")
# Windows 专用：TAP-Windows 驱动
DRIVER_DIR = os.path.join(BASE_DIR, "driver", "tap-windows", "x64")
TAP_INF = os.path.join(DRIVER_DIR, "OemVista.inf")
TAP_INSTALLER = os.path.join(BASE_DIR, "driver", "tap-windows", "9.24.7.exe")
# Windows 专用：广播助手（局域网游戏发现）
WINIPBROADCAST_EXE = os.path.join(BASE_DIR, "tools", "WinIPBroadcast.exe")
# 房主本机内置 supernode：让开房不依赖第三方服务器
SUPERNODE_EXE = os.path.join(BASE_DIR, "bin", "supernode.exe" if IS_WINDOWS else "supernode")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")

DEFAULT_MTU = 1290
DEFAULT_SUPERNODE_PORT = 7654
MC_PORT = 25565            # 我的世界 Java 版默认端口
MAX_ROOM_PLAYERS = 8       # 建议人数上限（仅提示，n2n 层不强制）

# 版本号与在线更新（与 setup_n2n.iss 的 MyAppVersion、Release tag 保持一致）
APP_VERSION = "1.2.2"
UPDATE_REPO = "zgs7157/n2n-lan"
UPDATE_API = "https://api.github.com/repos/%s/releases/latest" % UPDATE_REPO
UPDATE_PAGE = "https://github.com/%s/releases/latest" % UPDATE_REPO
UPDATE_INTERVAL = 24 * 3600      # 自动检查间隔（秒）；手动点按钮不受限
UPDATE_LOCAL_PROXIES = ["http://127.0.0.1:26561", "http://127.0.0.1:7890"]

# 房间聊天：走虚拟局域网 UDP 广播（房间内所有成员同一网段，广播即房间内消息）
CHAT_PORT = 23333
CHAT_PROTO_VERSION = 1

DEFAULT_CONFIG = {
    "supernode": "",          # 自定义服务器（高级用户才会填），为空时自动选择
    "public_nodes": [],       # 备用公共节点（自定义服务器池）
    "mtu": DEFAULT_MTU,
    "use_multicast": True,    # edge -E：接受组播/广播（MC 局域网发现需要）
    "use_game_metric": True,  # edge -x 1：更利于联机游戏识别
    "auto_broadcast": False,  # 是否随房间自动启动 WinIPBroadcast（广播助手）
    "mc_mode": True,          # 我的世界联机模式：自动组播 + 自动给游戏放行
    "dev_mode": False,        # 高级排障模式：显示原始日志
    "lang": "",               # 界面语言：zh/en，空 = 按系统语言自动
    "username": "",           # 房间聊天显示名
    "rooms": {},              # community -> {"subnet": "...", "key": "...", "my_ip": "...", "last_host": 2}
    "update_check": {"last": 0, "skip": ""},   # 上次自动检查时间戳 / 用户选择跳过的版本
}

RE_ROOM_CODE = re.compile(r"^([A-Za-z0-9_-]{3,32})@(10\.\d{1,3}\.0)#([A-Za-z0-9]{6,16})$")
RE_SUBNET = re.compile(r"^10\.(\d{1,3})\.0$")


# ----------------------------------------------------------------------------
# 多语言（中文 / English）
# ----------------------------------------------------------------------------
LANG_ZH = {
    "app_title": "n2n 房间管理小工具",
    "server_frame": "服务器（公网 supernode）",
    "server_fmt": "格式 IP:端口 或 IPv6 地址（如 2409:xxxx），IPv6 自动走转发器；多个用逗号分隔",
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
    # 房间聊天
    "chat": "房间聊天",
    "chat_title": "房间聊天 · %(room)s",
    "chat_name": "显示名",
    "chat_name_hint": "进房聊天时显示给别人的名字，保存在本机",
    "chat_need_room": "请先创建或加入房间，再打开聊天",
    "chat_saved": ">> 显示名已保存: %(name)s",
    "chat_placeholder": "说点什么…（Enter 发送）",
    "chat_send": "发送",
    "chat_no_msg": "还没有消息。房间里的人进聊天窗口后，消息会显示在这里（UDP 广播，同房间互通）。",
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
    "log_fw_started": ">> 检测到 IPv6 supernode [%(v6)s]，已启动本地转发器 127.0.0.1:%(lp)d → IPv6",
    "log_left": ">> 已退出房间",
    "log_copy_pwd": ">> 房间码已复制；房间密码需单独发给好友（在“房间密码”框里复制）",
    "log_copy_nopwd": ">> 免密房间，房间码已复制，发给好友即可加入",
    "log_copy_link": ">> 手机进房链接已复制，发给朋友即可（需路由器转发 TCP 25565 到本机）",
    "log_fw_ok": ">> 已放行 edge.exe 入站（若弹出 UAC 请点“是”）",
    "log_fw_cancel": ">> 防火墙规则添加被取消",
    # 公网 IP 检测
    "check_public_ip": "检测公网 IP",
    "pip_title": "公网 IP 检测结果",
    "pip_checking": "检测中…（需要联网，大约几秒）",
    "pip_local": "本机 IPv4：%(ip)s（%(kind)s）",
    "pip_public4": "出口 IPv4：%(ip)s（公网）",
    "pip_public4_unknown": "出口 IPv4：未获取到",
    "pip_public6": "出口 IPv6：%(ip)s（公网 IPv6）",
    "pip_public6_none": "出口 IPv6：无（本机没有分配到公网 IPv6）",
    "pip_direct": "结论：本机网卡直接持有公网 IPv4 —— 可以直接拿本机当 supernode（记得在防火墙放行 UDP 7654）。",
    "pip_nat": "结论：本机在路由器/NAT 后面，出口公网 IPv4 是 %(ip)s。要拿本机当 IPv4 服务器：在路由器把 UDP 7654 转发到 %(local)s；公网 IP 会变就配 DDNS。",
    "pip_cgnat": "结论：出口 IPv4 %(ip)s 属于运营商级 NAT（CGNAT），没有独立公网 IPv4，外部主动连不进来。建议改用 IPv6（若可用）、云服务器 / 公共 supernode，或向运营商申请公网 IP。",
    "pip_unknown": "结论：未能获取出口 IPv4（网络可能受限）。可以稍后重试，或直接用云服务器 / 公共节点。",
    "pip_v6_tip": "提示：检测到公网 IPv6 —— 可以把本机 IPv6 地址当 supernode 用（客户端已支持 IPv6，不需要路由器端口转发，只要防火墙放行 UDP 7654）；个别运营商可能封 IPv6 入站，实际能否被外部访问要对方实测。",
    "pip_kind_public": "公网地址",
    "pip_kind_private": "内网地址",
    "pip_kind_cgnat": "运营商 NAT 地址",
    "pip_kind_loopback": "回环地址",
    "pip_kind_linklocal": "链路本地地址",
    "pip_kind_other": "未知类型",
    "pip_tip": "说明：本检测只判断出口 IP 类型。能不能被外部访问，还取决于路由器端口转发与防火墙设置。",
    "pip_copy": "复制结果",
    "pip_copied": "已复制到剪贴板",
    "pip_err_detail": "各接口返回：%(errs)s",
    "pip_log": ">> 公网 IP 检测：%(verdict)s  IPv4出口=%(ip)s",
    # 简单模式主界面
    "simple_tagline": "和朋友一起玩，三步搞定",
    "create_room_big": "创建房间（我是房主）",
    "or_join_hint": "或者，加入朋友的房间",
    "join_code_label": "房间码",
    "join_btn": "加入",
    "status_idle": "未连接",
    "status_preparing": "正在准备…",
    "status_connecting": "正在连接…",
    "status_connected": "已连上",
    "status_failed": "连接失败",
    "invite_title": "把这串邀请码发给朋友",
    "invite_hint": "朋友打开本程序，粘贴邀请码后点「加入」；也可以在聊天里直接发这串字符",
    "copy_invite": "复制邀请码",
    "copied": "已复制",
    "leave_btn": "退出房间",
    "show_qr": "二维码",
    "mc_addr": "游戏里连这个地址：%(ip)s:25565",
    "qr_title": "扫码加入",
    "qr_hint": "让好友在电脑上打开本程序，扫这张图或直接把下面的邀请码发给他",
    "qr_unavailable": "当前版本没带二维码组件，用「复制邀请码」也一样",
    "mc_tip": "联机玩法：进我的世界 → 对局域网开放 → 好友在「多人游戏」里直接就能看到你的世界",
    "settings_btn": "设置",
    "retry_btn": "重试",
    # 设置窗口
    "settings_title": "设置",
    "mc_mode_opt": "我的世界联机模式（自动组播 + 自动给游戏放行）",
    "dev_mode_opt": "高级排障模式（显示原始日志）",
    "srv_custom": "自定义服务器（留空 = 自动选择）",
    "srv_custom_hint": "懂技术再填：格式 IP:端口 或 IPv6 地址，多个用逗号分隔",
    "srv_public": "备用公共节点（每行一个）",
    "advanced_tools": "高级工具",
    "log_title": "运行日志",
    "app_ok": "确定",
    # 流程提示（人话）
    "prep_driver": "正在准备虚拟网卡…（会弹一次权限确认，请点“是”）",
    "prep_net": "正在检查网络环境…",
    "prep_server": "正在搭建房间服务器…",
    "prep_upnp": "正在尝试自动开放端口…",
    "prep_edge": "正在建立虚拟局域网…",
    "uac_reason": "需要管理员权限创建虚拟局域网网卡",
    "fail_human": "网络环境不支持，正在尝试备用方案…",
    "fail_final": "这一步没成功。换个网络（比如手机热点）再试，或让朋友当房主。",
    "room_busy_hint": "房间座位被占用了，等 30 秒再试一次",
    "no_public_net": "试了公网 IPv4、公网 IPv6、同局域网三种方式都没通。可以换手机热点试试，或让朋友当房主。",
    "no_server_hint": "这个房间码里没带服务器地址，请向房主要完整邀请码（码后面带 @地址 的那种）。",
    "bad_code_hint": "房间码不对。应该是 8 位字母数字，例如「ABCD-EFGH」",
    "need_code": "请先粘贴朋友给你的邀请码",
    "host_mode_v6": "房间已就绪（IPv6 直连，好友无需端口转发）",
    "host_mode_v4": "房间已就绪（已自动开放端口）",
    "host_mode_lan": "房间已就绪（仅限同一局域网内进房）",
    "host_mode_public": "房间已就绪（公共节点中转）",
    "host_mode_manual": "房间已就绪。如果好友进不来：在路由器把 UDP 7654 转发到 %(lan)s，再让好友重新加入。",
    "lan_unknown": "本机局域网地址",
    "log_v6_gateway": ">> 已开启 IPv6 反向转发器：[::]:%(port)d → 本机 supernode（好友可用 IPv6 地址连进来）",
    "log_v6_gateway_fail": ">> IPv6 反向转发器没能启动，好友可能连不上；可让好友改走同一局域网或换网络",
    "log_alloc_up": ">> 房主 IP 发号已开启（%(ip)s:%(port)d），好友进房会自动领到不重复的虚拟 IP",
    "log_alloc_fail": ">> IP 发号服务没能启动，好友可能撞到同一个虚拟 IP",
    "log_ip_switch": ">> 房主分配虚拟 IP：%(new)s（原 %(old)s），正在用新 IP 重连",
    "leave_confirm": "退出后房间就关闭了，朋友会掉线。确定退出？",
    "not_now": "再想想",
    "yes": "确定",
    # 在线更新
    "ver_btn": "版本 v%(v)s",
    "ver_btn_tip": "点击检查新版本",
    "update_available": "发现新版本 v%(new)s（当前 v%(cur)s）",
    "update_goto": "去下载",
    "update_later": "以后再说",
    "update_skip": "不再提示此版本",
    "version_label": "当前版本 v%(v)s",
    "update_checking": "正在检查更新…",
    "update_latest": "已是最新版本（v%(v)s）",
    "update_failed": "检查更新失败：连不上 GitHub。若开了加速器请稍后再试。",
    "update_none": "暂时拿不到版本信息，请稍后再试",
}

LANG_EN = {
    "app_title": "N2N Room Manager",
    "server_frame": "Server (public supernode)",
    "server_fmt": "Format IP:port or an IPv6 address (e.g. 2409:xxxx); IPv6 uses local forwarder; comma separated",
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
    # Room chat
    "chat": "Room Chat",
    "chat_title": "Room Chat · %(room)s",
    "chat_name": "Display name",
    "chat_name_hint": "Shown to others in room chat; saved locally",
    "chat_need_room": "Create or join a room before chatting",
    "chat_saved": ">> Display name saved: %(name)s",
    "chat_placeholder": "Type a message... (Enter to send)",
    "chat_send": "Send",
    "chat_no_msg": "No messages yet. When others in the room open the chat window, messages show up here (UDP broadcast within the room).",
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
    "log_fw_started": ">> IPv6 supernode [%(v6)s] detected, local forwarder started on 127.0.0.1:%(lp)d -> IPv6",
    "log_left": ">> Left the room",
    "log_copy_pwd": ">> Room code copied; send the password separately (copy from the 'Room Password' box)",
    "log_copy_nopwd": ">> No-password room; room code copied, send it to your friend",
    "log_copy_link": ">> Mobile join link copied — send it to your friend (requires TCP 25565 port-forward to this PC)",
    "log_fw_ok": ">> edge.exe inbound allowed (click Yes if UAC appears)",
    "log_fw_cancel": ">> Firewall rule add cancelled",
    # Public IP check
    "check_public_ip": "Check public IP",
    "pip_title": "Public IP check",
    "pip_checking": "Checking… (needs internet, a few seconds)",
    "pip_local": "Local IPv4: %(ip)s (%(kind)s)",
    "pip_public4": "Egress IPv4: %(ip)s (public)",
    "pip_public4_unknown": "Egress IPv4: not available",
    "pip_public6": "Egress IPv6: %(ip)s (public IPv6)",
    "pip_public6_none": "Egress IPv6: none (no public IPv6 assigned)",
    "pip_direct": "Verdict: this machine holds a public IPv4 directly — you can use it as a supernode (allow UDP 7654 in the firewall).",
    "pip_nat": "Verdict: behind a router/NAT; the egress public IPv4 is %(ip)s. To host an IPv4 supernode, forward UDP 7654 to %(local)s on the router, and set up DDNS if the IP changes.",
    "pip_cgnat": "Verdict: egress IPv4 %(ip)s is carrier-grade NAT (CGNAT) — no dedicated public IPv4, so inbound connections will not work. Prefer IPv6 if available, a cloud server / public supernode, or ask your ISP for a public IP.",
    "pip_unknown": "Verdict: could not obtain the egress IPv4 (network may be restricted). Retry later, or use a cloud server / public node.",
    "pip_v6_tip": "Tip: a public IPv6 was detected — you can use this machine's IPv6 address as the supernode (the client supports IPv6; no router port-forwarding needed, just allow UDP 7654 in the firewall). Some ISPs block inbound IPv6, so the other side should test it.",
    "pip_kind_public": "public",
    "pip_kind_private": "private",
    "pip_kind_cgnat": "carrier NAT",
    "pip_kind_loopback": "loopback",
    "pip_kind_linklocal": "link-local",
    "pip_kind_other": "unknown",
    "pip_tip": "Note: this only classifies the egress IP. Inbound reachability also depends on router port-forwarding and firewall rules.",
    "pip_copy": "Copy result",
    "pip_copied": "Copied to clipboard",
    "pip_err_detail": "Each endpoint returned: %(errs)s",
    "pip_log": ">> Public IP check: %(verdict)s  egress IPv4=%(ip)s",
    # Simple mode main window
    "simple_tagline": "Play with friends in three steps",
    "create_room_big": "Create a room (I'm the host)",
    "or_join_hint": "Or join a friend's room",
    "join_code_label": "Room code",
    "join_btn": "Join",
    "status_idle": "Not connected",
    "status_preparing": "Preparing…",
    "status_connecting": "Connecting…",
    "status_connected": "Connected",
    "status_failed": "Connection failed",
    "invite_title": "Send this invite code to your friends",
    "invite_hint": "They open this app, paste the invite code and press Join; you can also paste it in chat",
    "copy_invite": "Copy invite code",
    "copied": "Copied",
    "leave_btn": "Leave room",
    "show_qr": "QR code",
    "mc_addr": "In-game address: %(ip)s:25565",
    "qr_title": "Scan to join",
    "qr_hint": "Ask your friend to open this app on their PC and scan this image, or just send them the code below",
    "qr_unavailable": "This build has no QR component; 'Copy invite' works just as well",
    "mc_tip": "How to play: open Minecraft -> Open to LAN -> your friends see your world under Multiplayer",
    "settings_btn": "Settings",
    "retry_btn": "Retry",
    # Settings window
    "settings_title": "Settings",
    "mc_mode_opt": "Minecraft LAN mode (auto multicast + auto allow game through firewall)",
    "dev_mode_opt": "Advanced troubleshooting (show raw logs)",
    "srv_custom": "Custom server (empty = choose automatically)",
    "srv_custom_hint": "For advanced users: IP:port or an IPv6 address, separate multiple with commas",
    "srv_public": "Fallback public nodes (one per line)",
    "advanced_tools": "Advanced tools",
    "log_title": "Run log",
    "app_ok": "OK",
    # Flow messages
    "prep_driver": "Preparing the virtual network adapter… (a permission prompt will appear, click Yes)",
    "prep_net": "Checking your network…",
    "prep_server": "Setting up the room server…",
    "prep_upnp": "Trying to open the port automatically…",
    "prep_edge": "Building the virtual LAN…",
    "uac_reason": "Administrator permission is needed to create the virtual LAN adapter",
    "fail_human": "This network isn't cooperating, trying a fallback…",
    "fail_final": "That didn't work. Try another network (a phone hotspot works well), or let your friend host.",
    "room_busy_hint": "This seat in the room is still taken, try again in 30 seconds",
    "no_public_net": "Public IPv4, public IPv6 and same-LAN were all tried and none worked. Try a phone hotspot, or let your friend host.",
    "no_server_hint": "This room code carries no server address. Ask the host for the full invite code (the one with @address appended).",
    "bad_code_hint": "That room code doesn't look right. It should be 8 letters/digits, e.g. \"ABCD-EFGH\"",
    "need_code": "Paste the invite code your friend sent you first",
    "host_mode_v6": "Room ready (direct IPv6, no port forwarding needed)",
    "host_mode_v4": "Room ready (port opened automatically)",
    "host_mode_lan": "Room ready (same LAN only)",
    "host_mode_public": "Room ready (public node relay)",
    "host_mode_manual": "Room ready. If your friend can't get in: forward UDP 7654 to %(lan)s on your router, then ask them to rejoin.",
    "lan_unknown": "this PC's LAN address",
    "log_v6_gateway": ">> IPv6 reverse forwarder is up: [::]:%(port)d -> local supernode (friends can join over IPv6)",
    "log_v6_gateway_fail": ">> The IPv6 reverse forwarder did not start; friends may not reach you. Try the same LAN or another network.",
    "log_alloc_up": ">> Host IP allocation is up (%(ip)s:%(port)d); joiners get a unique virtual IP automatically",
    "log_alloc_fail": ">> IP allocation did not start; joiners may end up on the same virtual IP",
    "log_ip_switch": ">> Host assigned virtual IP %(new)s (was %(old)s); reconnecting with the new IP",
    "leave_confirm": "Leaving closes the room and your friends will disconnect. Leave?",
    "not_now": "Not now",
    "yes": "Yes",
    # Online update
    "ver_btn": "Version v%(v)s",
    "ver_btn_tip": "Click to check for updates",
    "update_available": "New version v%(new)s available (you have v%(cur)s)",
    "update_goto": "Download",
    "update_later": "Later",
    "update_skip": "Don't remind me again",
    "version_label": "Current version v%(v)s",
    "update_checking": "Checking for updates…",
    "update_latest": "You're on the latest version (v%(v)s)",
    "update_failed": "Update check failed: GitHub is unreachable. If a proxy/accelerator is on, try again later.",
    "update_none": "Couldn't get version info right now, please try again later",
}

LANGUAGES = {"zh": LANG_ZH, "en": LANG_EN}

# 房间成员面板文案（两版共用，追加在字典末尾，不改动原有键）
LANG_ZH.update({
    "members_fmt": "房间成员 %(n)d 人 · 房主 %(host)s",
    "members_alone": "房间成员 1 人（只有你自己）",
    "col_ip": "虚拟 IP",
    "col_role": "角色",
    "col_name": "名称",
    "role_host": "房主",
    "role_guest": "成员",
    "member_self_suffix": "（我）",
    "members_wait": "正在收集房间成员…",
})
LANG_EN.update({
    "members_fmt": "%(n)d in room · host %(host)s",
    "members_alone": "1 in room (just you)",
    "col_ip": "Virtual IP",
    "col_role": "Role",
    "col_name": "Name",
    "role_host": "Host",
    "role_guest": "Member",
    "member_self_suffix": " (me)",
    "members_wait": "Collecting room members…",
})

# 当前语言（启动时由 App 按配置/系统语言设置）
_lang = "zh"


def detect_lang():
    """按系统 UI 语言检测：中文系统默认中文，其余默认英文。
    Windows 读 GetUserDefaultUILanguage；macOS/Linux 读 LANG 环境变量。"""
    if IS_WINDOWS:
        try:
            ui = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if (ui & 0xFFFF) == 0x0804 else "en"
        except Exception:
            return "en"
    try:
        lang = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
        if lang.startswith("zh"):
            return "zh"
    except Exception:
        pass
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
# 版本与在线更新
# ----------------------------------------------------------------------------
def version_tuple(text):
    """'V1.2.1' / 'v1.2.1' / '1.2.1' / 'v1.2.1-beta' → (1, 2, 1)；解析失败返回 ()"""
    m = re.search(r"(\d+(?:\.\d+)*)", (text or "").strip())
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split("."))


def compare_version(a, b):
    """a 比 b 新返回 1，相同返回 0，更旧返回 -1；位数不足按 0 补齐"""
    ta, tb = version_tuple(a), version_tuple(b)
    if not ta or not tb:
        return 0
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def _urllib_open(url, proxy=None, timeout=8):
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    else:
        handler = urllib.request.ProxyHandler({})   # 空 = 显式直连，不吃系统代理
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={
        "User-Agent": "n2n-lan-room-manager/%s" % APP_VERSION,
        "Accept": "application/vnd.github+json",
    })
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def fetch_latest_release(timeout=8):
    """查 GitHub 最新 Release，返回 (tag, 页面地址)；取不到返回 (None, "")。
    依次尝试：直连 → 本机常见代理端口（Steam++ / Clash），任一条通路成功即用。
    GitHub 在部分网络下必须走代理，所以要留代理兜底；反过来代理没开时直连也能成。"""
    for proxy in [None] + UPDATE_LOCAL_PROXIES:
        try:
            raw = _urllib_open(UPDATE_API, proxy=proxy, timeout=timeout)
            data = json.loads(raw.decode("utf-8", "ignore"))
            tag = (data.get("tag_name") or "").strip()
            url = (data.get("html_url") or UPDATE_PAGE).strip()
            if tag:
                return tag, url
        except Exception:
            continue
    return None, ""


def open_external(url):
    """用系统默认浏览器打开链接。打包成无控制台的 exe 后 webbrowser 有时不灵，逐级兜底。"""
    try:
        if IS_WINDOWS:
            os.startfile(url)
            return True
    except Exception:
        pass
    try:
        if IS_MACOS:
            subprocess.Popen(["open", url])
            return True
        if IS_LINUX:
            subprocess.Popen(["xdg-open", url])
            return True
    except Exception:
        pass
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception:
        return False


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


# ----------------------------------------------------------------------------
# 短房间码 / 邀请码：8 位码确定性派生 n2n 参数，普通用户只需念 8 个字符
# ----------------------------------------------------------------------------
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"   # 32 字符，去掉 0/1/I/O 易混字符
RE_CODE_JUNK = re.compile(r"[^%s]" % CODE_ALPHABET)


def gen_short_code():
    """生成 8 位房间码（32^8 ≈ 1.1 万亿种，够用且方便口头传递）"""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def clean_code(text):
    """去掉 '-'、空格等分隔符并转大写，只留合法字符"""
    return RE_CODE_JUNK.sub("", (text or "").upper())


def code_to_params(code):
    """由 8 位房间码确定性推导 n2n 参数（无需中心服务器）。
    同一房间码在任何机器上算出的 community / 密钥 / 网段都相同。"""
    code = clean_code(code)
    if len(code) != 8:
        return None
    h = hashlib.sha256(("n2n-lan|" + code).encode("utf-8")).hexdigest()
    community = "room-%s-%s" % (code[:4].lower(), code[4:].lower())
    subnet = "10.%d.0" % (2 + (int(h[2:4], 16) % 250))
    return {
        "code": code,
        "community": community,
        "subnet": subnet,
        "key": h[:16],
        "host_ip": subnet + ".1",
    }


def make_invite(code, server=None):
    """邀请码 = 房间码[@服务器地址]。没有服务器表示用内置公共节点。"""
    code = clean_code(code)
    if not code:
        return ""
    if not server:
        return code
    return "%s@%s" % (code, server.strip())


def parse_invite(text):
    """解析用户粘贴的邀请码，返回 {code, server} 或 None。
    同时兼容旧版长房间码（community@网段#密钥）。"""
    s = (text or "").strip()
    if "#" in s:
        old = parse_room_code(s)
        if old:
            community, subnet, key = old
            return {"legacy": True, "community": community, "subnet": subnet,
                    "key": key, "code": community, "server": ""}
        return None
    if "@" in s:
        code_part, server = s.split("@", 1)
    else:
        code_part, server = s, ""
    code = clean_code(code_part)
    if len(code) != 8:
        return None
    params = code_to_params(code)
    params["server"] = server.strip()
    params["legacy"] = False
    return params


def machine_id(cfg=None):
    """本机稳定标识：首次生成随机串存进配置，用于分散虚拟 IP 与向房主申请 IP。
    不依赖硬件指纹，重装软件会换新 ID（代价只是换一个尾号，不影响房间）。"""
    cfg = cfg if cfg is not None else load_config()
    mid = str(cfg.get("machine_id") or "").strip()
    if len(mid) >= 8:
        return mid
    mid = secrets.token_hex(8)
    cfg["machine_id"] = mid
    try:
        save_config(cfg)
    except Exception:
        pass
    return mid


def pick_candidate_ip(subnet, cfg=None, mid=None):
    """由机器标识派生候选虚拟 IP（.2 ~ .253）。

    旧实现从 .2 起按本机历史记录顺序占位，但那份记录只在本机，第二、第三个
    好友各自的配置里都没有别人的记录，于是全都算到 .2 —— 三人房间必撞。
    改成按机器标识散列，天然分散到不同尾号。"""
    mid = mid or machine_id(cfg)
    h = hashlib.sha256(("%s|%s" % (subnet, mid)).encode("utf-8")).hexdigest()
    return "%s.%d" % (subnet, 2 + (int(h[6:10], 16) % 252))


def suggest_ip(subnet, cfg):
    """兼容旧调用点：语义从「本地顺序占位」升级为「按机器分散」。"""
    return pick_candidate_ip(subnet, cfg)


# ----------------------------------------------------------------------------
# 房主侧虚拟 IP 发号：没有中心服务器时，房主是唯一可靠的仲裁者
# ----------------------------------------------------------------------------
IP_ASSIGN_PORT = 23336
IP_ASSIGN_TAG = "N2NLANIP"


def parse_assign_msg(data):
    """解析报文：N2NLANIP|REQ|房间码|机器标识   /   N2NLANIP|OK|房间码|IP"""
    try:
        text = data.decode("utf-8", "ignore").strip()
    except Exception:
        return None
    parts = text.split("|")
    if len(parts) != 4 or parts[0] != IP_ASSIGN_TAG:
        return None
    return parts[1], parts[2], parts[3]


class IpAllocator:
    """房主侧 IP 发号服务：绑虚拟网段 .1 的 UDP 端口，按序发号并持久化。

    好友拿到号码后若与自己当前 IP 不同，会重启 edge 换成新 IP —— 从机制上
    保证同一房间不会出现两个 .2。"""

    def __init__(self):
        self.sock = None
        self.thread = None
        self.running = False
        self.subnet = ""
        self.code = ""
        self.map = {}
        self.cfg = None
        self.on_log = None

    def start(self, subnet, code, cfg):
        self.stop()
        self.subnet = subnet
        self.code = code
        self.cfg = cfg
        room = (cfg.get("rooms") or {}).get(code) or {}
        self.map = {str(k): int(v) for k, v in (room.get("ip_map") or {}).items()
                    if str(v).isdigit()}
        sock = None
        # 优先绑虚拟 IP，源地址才对得上；TAP 还没拿到地址时退到全部地址
        for addr in ((subnet + ".1", IP_ASSIGN_PORT), ("0.0.0.0", IP_ASSIGN_PORT)):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(addr)
                sock = s
                break
            except OSError:
                try:
                    s.close()
                except Exception:
                    pass
        if sock is None:
            return False
        sock.settimeout(0.6)
        self.sock = sock
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def _next_free(self):
        used = set(int(v) for v in self.map.values())
        for tail in range(2, 255):
            if tail not in used:
                return tail
        return None

    def _bank(self):
        """分配表写回配置，房主重进同一房间时不重新发号"""
        if not self.cfg:
            return
        try:
            rooms = self.cfg.setdefault("rooms", {})
            room = rooms.setdefault(self.code, {})
            room["ip_map"] = dict(self.map)
            room["subnet"] = self.subnet
            save_config(self.cfg)
        except Exception:
            pass

    def _loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_assign_msg(data)
            if not parsed:
                continue
            action, code, payload = parsed
            if action != "REQ" or code != self.code:
                continue
            mid = payload.strip()
            if not mid:
                continue
            ip = self._serve(mid)
            if not ip:
                continue
            try:
                self.sock.sendto(
                    ("%s|OK|%s|%s" % (IP_ASSIGN_TAG, self.code, ip)).encode("utf-8"),
                    addr)
            except OSError:
                pass

    def _serve(self, mid):
        """给一个机器标识发号（同一标识固定同一个号），返回 IP 字符串。"""
        tail = self.map.get(mid)
        if tail is None:
            tail = self._next_free()
            if tail is None:
                return ""
            self.map[mid] = tail
            self._bank()
            if self.on_log:
                self.on_log("分配虚拟 IP %s.%d 给 %s" % (self.subnet, tail, mid[:8]))
        return "%s.%d" % (self.subnet, tail)

    def stop(self):
        self.running = False
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.thread = None


def request_room_ip(subnet, code, mid, current_ip, timeout=22.0):
    """好友侧：向房主 10.x.0.1 申请房间内唯一的虚拟 IP。

    必须绑自己的虚拟 IP 发出，否则包会从物理网卡走、进不了虚拟网段。
    返回房主分配的 IP（如 10.30.0.5）或 None。"""
    if not subnet or not current_ip:
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((current_ip, 0))
        sock.settimeout(1.2)
    except OSError:
        return None
    msg = ("%s|REQ|%s|%s" % (IP_ASSIGN_TAG, code, mid)).encode("utf-8")
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                sock.sendto(msg, (subnet + ".1", IP_ASSIGN_PORT))
            except OSError:
                pass
            try:
                data, _addr = sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_assign_msg(data)
            if parsed and parsed[0] == "OK" and parsed[1] == code:
                return parsed[2].strip() or None
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return None


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


def parse_supernode(sn):
    """解析 supernode 输入，返回 (kind, host, port)。
    kind: "v6"（IPv6 地址，端口默认 7654，edge 不认 IPv6 地址，需走转发器）
          "v4"（IPv4 或域名，host:port 或纯 host）
    支持格式：1.2.3.4:7654 / host:port / [2409:xxxx]:7654 / 2409:xxxx（多冒号视为 IPv6）
    """
    sn = sn.strip()
    if sn.startswith("["):
        m = re.match(r"\[([^\]]+)\](?::(\d+))?", sn)
        if m:
            return "v6", m.group(1), int(m.group(2) or 7654)
    if sn.count(":") >= 2:
        return "v6", sn, 7654
    if ":" in sn:
        h, p = sn.rsplit(":", 1)
        try:
            return "v4", h.strip(), int(p)
        except ValueError:
            return "v4", sn, 7654
    return "v4", sn, 7654


def get_local_ipv6s():
    """返回本机当前的 IPv6 地址列表（小写）。用于判断"开房者填的是不是自己"。"""
    addrs = set()
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-NetIPAddress -AddressFamily IPv6 -ErrorAction SilentlyContinue | "
                 "Where-Object { $_.PrefixOrigin -ne 'WellKnown' }).IPAddress"],
                capture_output=True, text=True, errors="replace", timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            for line in out.splitlines():
                a = line.strip().lower()
                if a:
                    addrs.add(a)
        except Exception:
            pass
    else:
        # macOS / Linux：ifconfig 列出 inet6，取含 ':' 的全局/链路地址（去 fe80 之外的都可判断）
        for cmd in (["ifconfig", "-a"],):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=15).stdout
            except Exception:
                continue
            for line in out.splitlines():
                m = re.match(r"\s*inet6\s+([0-9a-fA-F:]+)", line)
                if m:
                    a = m.group(1).lower()
                    a = a.split("%")[0]  # 去掉 fe80::1%en0 的接口后缀
                    if ":" in a:
                        addrs.add(a)
    return addrs


def chat_broadcast_addr(virtual_ip):
    """由虚拟 IP 计算房间聊天广播地址：10.x.0.h -> 10.x.0.255"""
    parts = (virtual_ip or "").split(".")
    if len(parts) == 4 and parts[0] == "10":
        return "%s.%s.%s.255" % (parts[0], parts[1], parts[2])
    return ""


# ----------------------------------------------------------------------------
# 公网 IP 检测：判断本机有没有公网 IP（决定能不能直接拿本机当 supernode）
# ----------------------------------------------------------------------------

_IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")

# 出口 IP 接口按协议分开：双栈机器访问通用接口会拿到 IPv6，必须显式分开取
_PUBLIC_IP4_SOURCES = [
    "https://api-ipv4.ip.sb/ip",
    "https://ipv4.ident.me",
    "https://ipv4.icanhazip.com",
    "https://v4.ident.me",
    "https://api.ip.sb/ip",
    "https://ipinfo.io/ip",
]
_PUBLIC_IP6_SOURCES = [
    "https://api-ipv6.ip.sb/ip",
    "https://v6.ident.me",
    "https://ipv6.icanhazip.com",
]

# 直连 opener（空 ProxyHandler）：显式绕过系统代理，
# 否则开着 Steam++/Clash 时测出来的会是代理出口 IP，不是本机真实出口
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_UA = {"User-Agent": "n2n-lan-room-manager/1.0"}


def _valid_ipv4(ip):
    m = _IPV4_RE.match((ip or "").strip())
    if not m:
        return False
    return all(0 <= int(g) <= 255 for g in m.groups())


def ip_kind(ip):
    """IPv4 归类：public 公网 / private 内网 / cgnat 运营商级NAT / loopback / linklocal / invalid"""
    if not _valid_ipv4(ip):
        return "invalid"
    ip = ip.strip()
    a, b = [int(x) for x in ip.split(".")[:2]]
    if a == 127:
        return "loopback"
    if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
        return "private"
    if a == 100 and 64 <= b <= 127:
        return "cgnat"
    if a == 169 and b == 254:
        return "linklocal"
    if a == 0 or a >= 224:
        return "invalid"
    return "public"


def is_public_ipv6(ip):
    """IPv6 是否公网可路由（排除回环/链路本地/唯一本地/组播）"""
    try:
        addr = ipaddress.ip_address((ip or "").strip().strip("[]"))
    except Exception:
        return False
    return addr.version == 6 and addr.is_global


def get_primary_local_ip():
    """本机主网卡 IPv4（UDP connect 探测，不会真的发包）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 53))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""


def fetch_public_ip(version=4, timeout=6):
    """取出口 IP。version=4 只认 IPv4，version=6 只认 IPv6。
    返回 (ip|None, 错误摘要)。"""
    sources = _PUBLIC_IP4_SOURCES if version == 4 else _PUBLIC_IP6_SOURCES
    errs = []
    for url in sources:
        try:
            req = urllib.request.Request(url, headers=_UA)
            with _OPENER.open(req, timeout=timeout) as r:
                text = r.read(2048).decode("utf-8", "replace").strip()
            first = (text.split()[0] if text else "").strip("[]")
            try:
                addr = ipaddress.ip_address(first)
            except Exception:
                errs.append("%s 非 IP 响应" % url)
                continue
            if addr.version == version:
                return str(addr), ""
            errs.append("%s 返回 v%d" % (url, addr.version))
        except Exception as e:
            errs.append("%s %s" % (url, type(e).__name__))
    return None, "; ".join(errs)


def detect_public_ip():
    """检测本机公网情况。
    返回 dict: local_ip / local_kind / public_ip4 / public_ip6 / verdict / errors4 / errors6
    verdict: direct=网卡直接持有公网IPv4 | nat=路由器NAT后需端口转发 |
             cgnat=运营商级NAT | unknown=没测出IPv4
    """
    local_ip = get_primary_local_ip()
    local_kind = ip_kind(local_ip)
    pub4, err4 = fetch_public_ip(4)
    pub6, err6 = fetch_public_ip(6)
    pub4_kind = ip_kind(pub4) if pub4 else "invalid"

    if local_kind == "public":
        verdict = "direct"
        pub4 = pub4 or local_ip
    elif pub4 and pub4_kind == "cgnat":
        verdict = "cgnat"
    elif pub4 and pub4_kind == "public":
        verdict = "nat"
    else:
        verdict = "unknown"

    return {
        "local_ip": local_ip,
        "local_kind": local_kind,
        "public_ip4": pub4 or "",
        "public_ip6": pub6 or "",
        "ipv6_public": is_public_ipv6(pub6) if pub6 else False,
        "verdict": verdict,
        "errors4": "" if pub4 else err4,
        "errors6": "" if pub6 else err6,
    }


# ----------------------------------------------------------------------------
# 系统工具：驱动 / 防火墙 / 提权
# ----------------------------------------------------------------------------
def is_admin():
    if IS_WINDOWS:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    # macOS / Linux：euid==0 即 root
    try:
        return os.geteuid() == 0
    except Exception:
        return False


def run_elevated(exe, args, workdir=None, wait=False):
    """以管理员/root 权限运行。
    Windows：ShellExecuteW runas 弹 UAC；
    macOS：osascript 弹系统授权框；
    Linux：pkexec（有图形会话时）或 sudo。
    返回 True 表示成功发起。"""
    if IS_WINDOWS:
        try:
            res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, workdir or "", 0)
            return res > 32
        except Exception:
            return False
    if IS_MACOS:
        # osascript 提权执行：整个命令拼成一行，用 do shell script ... with administrator privileges
        cmd = "cd '%s' && %s %s" % (
            (workdir or os.getcwd()).replace("'", "'\\''"),
            exe.replace("'", "'\\''"),
            args.replace("'", "'\\''"),
        )
        script = 'do shell script "%s" with administrator privileges' % cmd.replace('"', '\\"')
        try:
            p = subprocess.Popen(["osascript", "-e", script],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if wait:
                p.wait(timeout=120)
            return True
        except Exception:
            return False
    # Linux
    try:
        p = subprocess.Popen(["pkexec", exe] + args.split(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait:
            p.wait(timeout=120)
        return True
    except Exception:
        pass
    try:
        p = subprocess.Popen(["sudo", exe] + args.split(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait:
            p.wait(timeout=120)
        return True
    except Exception:
        return False


def tap_driver_installed():
    """检测虚拟网卡驱动是否已装：
    Windows：TAP-Windows (tap0901)；
    macOS：tuntap 内核扩展（/dev/tap*）或原生 utun；
    Linux：/dev/net/tun。"""
    if IS_WINDOWS:
        ps = (
            "(Get-NetAdapter -ErrorAction SilentlyContinue | "
            "Where-Object { $_.InterfaceDescription -like '*TAP*' -or $_.Name -like '*TAP*' } | "
            "Measure-Object).Count"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, errors="replace", timeout=30,
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
                capture_output=True, text=True, errors="replace", timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
            if out.isdigit():
                return int(out) > 0
        except Exception:
            pass
        return False
    if IS_MACOS:
        # tuntap 驱动装好后会出现 /dev/tap0..tap15；n2n 也可走原生 utun（若 edge 支持）
        try:
            import glob
            taps = glob.glob("/dev/tap*")
            if taps:
                return True
        except Exception:
            pass
        # 兜底：检查 utun 接口（macOS 自带，无驱动依赖）
        try:
            out = subprocess.run(["ifconfig"], capture_output=True, text=True, errors="replace", timeout=15).stdout
            return "utun" in out
        except Exception:
            return False
    # Linux
    return os.path.exists("/dev/net/tun")


def install_tap_driver():
    """安装/检测虚拟网卡驱动。返回 "already" / "ok" / "denied" / "fail"。
    Windows：静默装 TAP-Windows；
    macOS：提示用户装 tuntap（brew cask install tuntap）——GUI 里给引导；
    Linux：提示 modprobe tun。"""
    if tap_driver_installed():
        return "already"
    if IS_WINDOWS:
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
    if IS_MACOS:
        # tuntap 驱动需用户手动安装（会弹系统安全确认），GUI 会给完整指引，这里只返回 "manual"
        return "manual"
    # Linux
    return "manual"


def add_firewall_rule():
    """放行 edge 与虚拟 IP 发号端口入站。Windows：netsh；macOS/Linux：无 UI 弹窗则提示手动。"""
    if IS_WINDOWS:
        cmds = [
            'advfirewall firewall add rule name="n2n edge room" dir=in action=allow program="%s"' % EDGE_EXE,
            # 发号是主程序自己监听，按端口放行（源码与打包路径不同，不能按 exe 放行）
            'advfirewall firewall add rule name="n2n ip assign" dir=in action=allow protocol=UDP localport=%d'
            % IP_ASSIGN_PORT,
        ]
        ok = True
        for c in cmds:
            ok = bool(run_elevated("netsh", c, wait=False)) and ok
        return ok
    # macOS / Linux：应用防火墙一般会自行弹窗询问，无需（也难）预设规则
    return True


def get_tap_ip():
    """读取虚拟网卡当前 IPv4 地址（可能为空）。"""
    if IS_WINDOWS:
        ps = (
            "(Get-NetIPConfiguration -ErrorAction SilentlyContinue | "
            "Where-Object { $_.InterfaceDescription -like '*TAP*' } | "
            "ForEach-Object { $_.IPv4Address.IPAddress }) -join ', '"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, errors="replace", timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
            return out
        except Exception:
            return ""
    if IS_MACOS:
        try:
            out = subprocess.run(["ifconfig"], capture_output=True, text=True, errors="replace", timeout=15).stdout
            ips = []
            cur_if = None
            for line in out.splitlines():
                m = re.match(r"^([a-z0-9]+):", line)
                if m:
                    cur_if = m.group(1)
                m2 = re.match(r"\s*inet\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m2 and cur_if and (cur_if.startswith("tap") or cur_if.startswith("utun")):
                    ips.append(m2.group(1))
            return ", ".join(ips)
        except Exception:
            return ""
    # Linux
    try:
        out = subprocess.run(["ip", "-4", "addr", "show"], capture_output=True, text=True, errors="replace", timeout=15).stdout
        ips = []
        cur_if = None
        for line in out.splitlines():
            m = re.match(r"^\d+:\s+([a-zA-Z0-9_]+):", line)
            if m:
                cur_if = m.group(1)
            m2 = re.match(r"\s*inet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if m2 and cur_if and (cur_if.startswith("tap") or cur_if.startswith("n2n") or cur_if.startswith("tun")):
                ips.append(m2.group(1))
        return ", ".join(ips)
    except Exception:
        return ""


def open_folder(path):
    """跨平台打开目录：Windows 资源管理器 / macOS Finder / Linux 文件管理器。"""
    try:
        if IS_WINDOWS:
            os.startfile(path)
        elif IS_MACOS:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


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


class ChatListener(threading.Thread):
    """房间聊天监听：常驻监听 UDP 广播端口；进房后只显示当前房间(community)的消息。

    原理：同一 n2n 房间 = 同一虚拟局域网（10.x.0.0/24），成员在虚拟网卡上向
    10.x.0.255:23333 发 UDP 广播，房间内所有开着本工具的成员都能收到。
    不需要额外服务器，消息不经过 supernode 以外的地方。
    """

    def __init__(self, on_msg):
        super().__init__(daemon=True)
        self._on_msg = on_msg
        self._stop = threading.Event()
        self._sock = None
        self._room = None  # 当前所在房间的 community；None = 未进房，不显示

    def set_room(self, community):
        self._room = community

    def clear_room(self):
        self._room = None

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass

    def run(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("", CHAT_PORT))
            self._sock.settimeout(0.4)
        except Exception:
            return
        while not self._stop.is_set():
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                obj = json.loads(data.decode("utf-8", "replace"))
            except Exception:
                continue
            if obj.get("v") != CHAT_PROTO_VERSION:
                continue
            if not self._room or obj.get("c") != self._room:
                continue
            self._on_msg(obj.get("u", "?"), obj.get("m", ""))


# ----------------------------------------------------------------------------
# UPnP 自动端口映射（免登录路由器，纯标准库）
# ----------------------------------------------------------------------------
UPNP_SSDP_ADDR = "239.255.255.250"
UPNP_SSDP_PORT = 1900


def upnp_discover(timeout=3):
    """SSDP 发现 InternetGatewayDevice，返回设备描述文件 URL 列表"""
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST: %s:%d\r\n"
           'MAN: "ssdp:discover"\r\n'
           "MX: 2\r\n"
           "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n"
           % (UPNP_SSDP_ADDR, UPNP_SSDP_PORT)).encode("utf-8")
    locs = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(msg, (UPNP_SSDP_ADDR, UPNP_SSDP_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                break
            text = data.decode("utf-8", "ignore")
            for line in text.split("\r\n"):
                if line.lower().startswith("location:"):
                    loc = line.split(":", 1)[1].strip()
                    if loc and loc not in locs:
                        locs.append(loc)
    except Exception:
        pass
    finally:
        s.close()
    return locs


def upnp_control(location):
    """从设备描述里找 WAN*Connection 服务的 serviceType 与 controlURL"""
    try:
        req = urllib.request.Request(location, headers=_UA)
        with _OPENER.open(req, timeout=6) as r:
            desc = r.read(65536)
        root = ET.fromstring(desc)
    except Exception:
        return None, None
    base = location.rsplit("/", 1)[0]
    for node in root.iter():
        if not node.tag.endswith("service"):
            continue
        st = cu = None
        for ch in node.iter():
            if ch.tag.endswith("serviceType"):
                st = ch.text
            elif ch.tag.endswith("controlURL"):
                cu = ch.text
        if st and cu and ("WANIPConnection" in st or "WANPPPConnection" in st):
            cu = cu.strip()
            if not cu.startswith("http"):
                cu = base + ("" if cu.startswith("/") else "/") + cu
            return st.strip(), cu
    return None, None


def upnp_soap(control_url, service_type, action, args):
    body = "".join("<%s>%s</%s>" % (k, v, k) for k, v in args.items())
    payload = ('<?xml version="1.0"?>'
               '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
               's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
               '<s:Body><u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>'
               % (action, service_type, body, action)).encode("utf-8")
    req = urllib.request.Request(
        control_url, data=payload,
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": '"%s#%s"' % (service_type, action),
                 "User-Agent": "n2n-lan-room-manager/1.0"})
    with _OPENER.open(req, timeout=8) as r:
        return r.read().decode("utf-8", "ignore")


def upnp_add_mapping(ext_port, proto, internal_ip, internal_port=None, desc="n2n-lan"):
    """尝试自动映射端口。返回 (True, 网关地址) 或 (False, 简短原因)"""
    internal_port = internal_port or ext_port
    locs = upnp_discover()
    if not locs:
        return False, "路由器未开启 UPnP"
    for loc in locs:
        st, cu = upnp_control(loc)
        if not st or not cu:
            continue
        try:
            text = upnp_soap(cu, st, "AddPortMapping", {
                "NewRemoteHost": "",
                "NewExternalPort": str(ext_port),
                "NewProtocol": proto.upper(),
                "NewInternalPort": str(internal_port),
                "NewInternalClient": internal_ip,
                "NewEnabled": "1",
                "NewPortMappingDescription": desc,
                "NewLeaseDuration": "0",
            })
            if "errorCode" in text:
                return False, "路由器拒绝了映射"
            return True, loc
        except Exception as e:
            return False, type(e).__name__
    return False, "网关不支持端口映射"


class HostSupernode:
    """房主本机内置 supernode：让房间完全不依赖第三方服务器。"""

    def __init__(self):
        self.proc = None
        self.port = DEFAULT_SUPERNODE_PORT

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def port_busy(port, host="0.0.0.0"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True
        finally:
            s.close()

    def start(self, port=DEFAULT_SUPERNODE_PORT, fed="n2n-lan"):
        """返回 'ok' / 'reuse'（已有服务在跑）/ 'missing' / 'fail'"""
        self.port = port
        if self.port_busy(port):
            return "reuse"
        if not os.path.exists(SUPERNODE_EXE):
            return "missing"
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            logf = open(os.path.join(LOG_DIR, "supernode_local.log"), "ab", buffering=0)
            self.proc = subprocess.Popen(
                [SUPERNODE_EXE, "-p", str(port), "-F", fed],
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0)
        except Exception:
            return "fail"
        deadline = time.time() + 6
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return "fail"
            if self.port_busy(port):
                return "ok"
            time.sleep(0.25)
        return "ok" if self.port_busy(port) else "fail"

    def stop(self):
        """只结束自己启动的进程；复用他人 supernode 时不动手"""
        if self.proc is not None:
            try:
                if IS_WINDOWS:
                    subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=10,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    self.proc.terminate()
            except Exception:
                pass
            self.proc = None


class EdgeSession:
    """一个 edge 会话：启动 / 停止 / 状态。"""

    def __init__(self, app):
        self.app = app
        self.proc = None
        self.tailer = None
        self.log_path = None
        self.broadcast_proc = None
        self.fw_procs = []      # IPv6 转发器进程列表

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def _port_free(port):
        """探测本机 UDP 端口是否空闲。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def _start_forwarder(self, v6host, server_port):
        """为 IPv6 supernode 启动一个本地转发器（127.0.0.1:<本地端口> -> [v6host]:server_port）。
        返回实际使用的本地端口；失败返回 None。
        Windows 用打包好的 exe；macOS/Linux 用 python3 跑同目录源码。"""
        if IS_WINDOWS:
            if not os.path.exists(FORWARDER_EXE):
                return None
            fw_cmd = [FORWARDER_EXE]
        else:
            if not os.path.exists(FORWARDER_PY):
                return None
            py = sys.executable or "python3"
            fw_cmd = [py, FORWARDER_PY]
        # 本地端口从 7655 起：7654 是 supernode 惯例端口，本机若同时开着
        # supernode（0.0.0.0:7654），转发器 bind 127.0.0.1:7654 会因
        # SO_REUSEADDR 并存而探测失真，导致环回；避开 7654 两个场景都安全。
        for lp in range(7655, 7663):
            if not self._port_free(lp):
                continue
            try:
                p = subprocess.Popen(
                    fw_cmd + [v6host, str(lp), str(server_port)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
                )
            except Exception:
                continue
            # 轮询等待转发器真正开始监听（onefile 首启解包可能需 2-4 秒）
            deadline = time.time() + 8
            ok = False
            while time.time() < deadline:
                if p.poll() is not None:
                    break          # 进程已退出 = 启动失败
                if not self._port_free(lp):
                    ok = True      # 端口已被转发器占用 = 监听成功
                    break
                time.sleep(0.4)
            if ok:
                self.fw_procs.append(p)
                return lp
            try:
                p.terminate()
            except Exception:
                pass
        return None

    def start_server_forwarder(self, listen_port=DEFAULT_SUPERNODE_PORT, target_port=DEFAULT_SUPERNODE_PORT):
        """房主走 IPv6 兜底时：对 IPv6 世界监听 listen_port，转发给本机 supernode。
        supernode 本身只监听 IPv4，这个反向转发器就是那道门。
        返回 True / False。"""
        if IS_WINDOWS:
            if not os.path.exists(FORWARDER_EXE):
                return False
            fw_cmd = [FORWARDER_EXE]
        else:
            if not os.path.exists(FORWARDER_PY):
                return False
            py = sys.executable or "python3"
            fw_cmd = [py, FORWARDER_PY]
        try:
            p = subprocess.Popen(
                fw_cmd + ["--server", str(listen_port), str(target_port)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
            )
        except Exception:
            return False
        # 轮询确认转发器没在一开始就退出（IPv6 端口被占、栈不可用等）
        deadline = time.time() + 6
        while time.time() < deadline:
            if p.poll() is not None:
                return False
            time.sleep(0.4)
        if p.poll() is None:
            self.fw_procs.append(p)
            return True
        return False

    def start(self, community, key, ip, supernode_list):
        self.stop()
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(LOG_DIR, "edge_%s.log" % re.sub(r"[^A-Za-z0-9_-]", "_", community))

        args = [EDGE_EXE, "-c", community, "-k", key, "-a", ip + "/24"]
        local_v6 = self.app.local_ipv6s
        for sn in supernode_list:
            sn = sn.strip()
            if not sn:
                continue
            kind, host, port = parse_supernode(sn)
            if kind == "v6":
                if host.lower() in local_v6:
                    # 开房者填的是自己的 IPv6（supernode 就在本机）→ 直连本机，无需转发器
                    args += ["-l", "127.0.0.1:7654"]
                    continue
                lp = self._start_forwarder(host, port)
                if lp is not None:
                    self.app.append_log(tr("log_fw_started", v6=host, lp=lp))
                    args += ["-l", "127.0.0.1:%d" % lp]
                else:
                    # 转发器不可用：直连本机端口碰运气（本机就是服务器时有效）
                    args += ["-l", "127.0.0.1:7654"]
            else:
                args += ["-l", sn]
        cfg = self.app.cfg
        if cfg.get("use_multicast", True):
            args.append("-E")
        if IS_WINDOWS and cfg.get("use_game_metric", True):
            # -x 1 仅 Windows 支持（网络接口跃点数），macOS/Linux 传了会报错
            args += ["-x", "1"]
        args += ["-M", str(int(cfg.get("mtu", DEFAULT_MTU))), "-I", "room-" + community]

        logf = open(self.log_path, "ab", buffering=0)
        self.proc = subprocess.Popen(
            args,
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
        )
        self.tailer = LogTailer(self.log_path, self.app.append_log)
        self.tailer.start()

        if cfg.get("auto_broadcast") and IS_WINDOWS and os.path.exists(WINIPBROADCAST_EXE):
            # 广播助手仅 Windows 有对应工具
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
        for p in self.fw_procs:
            try:
                if IS_WINDOWS:
                    # PyInstaller onefile 有父子进程，用 taskkill /T /F 整树杀干净
                    subprocess.run(
                        ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                        capture_output=True, timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    # macOS / Linux：转发器是 python 单进程，terminate 即可
                    p.terminate()
                    try:
                        p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        p.kill()
            except Exception:
                pass
        self.fw_procs = []


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
def plan_host_network(cfg=None, port=DEFAULT_SUPERNODE_PORT, local6=None):
    """房主自动挑选服务器方案（普通用户无感知）。

    实测结论：内置 supernode 只监听 IPv4（不支持 IPv6 绑定），
    所以房主自建服务器必须走「公网 IPv4 + 端口可达」。
    优先级：高级自定义 > 公共节点 > 公网 IPv4（UPnP 自动映射）> 公网 IPv4（需路由器手动转发）
            > 公网 IPv6（本机 supernode + IPv6 反向转发器）> 同局域网直连
    返回 {"mode": "custom"|"public"|"v4"|"manual"|"v6"|"lan"|"none", "server": str, "detail": str, "lan_ip": str}
    """
    cfg = cfg or {}
    lan = get_primary_local_ip()
    custom = (cfg.get("supernode") or "").strip()
    if custom:
        return {"mode": "custom", "server": custom, "detail": "custom", "lan_ip": lan}

    nodes = [n.strip() for n in (cfg.get("public_nodes") or []) if n.strip()]
    if nodes:
        return {"mode": "public", "server": ",".join(nodes), "detail": "public", "lan_ip": lan}

    pub4 = ""
    try:
        pub4, _ = fetch_public_ip(4)
    except Exception:
        pub4 = ""

    if pub4 and ip_kind(pub4) == "public":
        ok, info = upnp_add_mapping(port, "udp", lan, port, "n2n-lan supernode")
        if ok:
            return {"mode": "v4", "server": "%s:%d" % (pub4, port), "detail": info, "lan_ip": lan}
        # 有公网地址但路由器没开 UPnP：让用户做一次手动端口转发即可长期可用
        return {"mode": "manual", "server": "%s:%d" % (pub4, port), "detail": info, "lan_ip": lan}

    # —— 没有公网 IPv4，开始兜底 ——
    # 兜底一：公网 IPv6。supernode 仍在本机跑（0.0.0.0:7654），
    # 由 IPv6 反向转发器对 IPv6 世界开门；好友侧用现成的 udp6 转发器连。
    v6 = ""
    try:
        v6, _ = fetch_public_ip(6)
    except Exception:
        v6 = ""
    if not v6:
        try:
            pool = list(local6 or []) or list(get_local_ipv6s())
        except Exception:
            pool = []
        cands = [ip for ip in pool if is_public_ipv6(ip)]
        v6 = sorted(cands)[0] if cands else ""
    if v6:
        return {"mode": "v6", "server": v6, "detail": "public ipv6", "lan_ip": lan}

    # 兜底二：同一局域网内直连（两边在同一个路由器/WiFi 下，不依赖公网）
    if lan:
        return {"mode": "lan", "server": "%s:%d" % (lan, port),
                "detail": "same lan only", "lan_ip": lan}

    return {"mode": "none", "server": "", "detail": "no reachable path", "lan_ip": lan}


def firewall_rule_ready(name="n2n edge room"):
    """检查某条防火墙规则是否已存在（存在就不必再提权）"""
    if not IS_WINDOWS:
        return True
    try:
        out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=%s" % name],
            capture_output=True, text=True, errors="replace", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return name in out
    except Exception:
        return False


def _win_proc_list(name):
    """Windows：列出指定进程名的 (pid, 可执行路径)。失败返回空列表。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='%s'" % name,
             "get", "ProcessId,ExecutablePath", "/format:csv"],
            capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return []
    rows = []
    for line in (out or "").splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        # csv 列序：Node,ExecutablePath,ProcessId
        if len(parts) >= 3 and parts[2].isdigit():
            rows.append((int(parts[2]), parts[1]))
    return rows


def cleanup_stale_children():
    """收拾上次异常退出（被强杀 / 崩溃）留下的 edge、supernode 孤儿进程。

    这些孤儿会一直占着 TAP 网卡和 UDP 7654，导致之后"建房"时 edge 打不开设备、
    supernode 起不来，表现就是"无法设立房间"。本程序启动时房间里必然没有自己的
    edge，所以只清理可执行文件位于本程序目录下的那些，不会误伤别人的 n2n。
    返回被清理的 ["edge.exe(1234)", ...]。
    """
    if not IS_WINDOWS:
        return []
    killed = []
    try:
        root_norm = os.path.normcase(os.path.abspath(BASE_DIR)).rstrip("\\") + "\\"
    except Exception:
        return []
    for name in ("edge.exe", "supernode.exe"):
        for pid, path in _win_proc_list(name):
            if not path:
                continue
            try:
                p_norm = os.path.normcase(os.path.abspath(path))
            except Exception:
                continue
            if not p_norm.startswith(root_norm):
                continue
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=6)
                killed.append("%s(%d)" % (name, pid))
            except Exception:
                pass
    return killed


def prepare_system():
    """首次开房时一次性提权：装虚拟网卡驱动 + 放行 edge / supernode 入站。
    普通用户只会看到一次 UAC 确认，之后不再打扰。
    返回 "already"（本来就齐） / "ok" / "denied"（用户拒绝） / "manual"（非 Windows）"""
    if not IS_WINDOWS:
        return "already" if tap_driver_installed() else "manual"

    names = ("n2n edge room", "n2n supernode", "n2n ip assign")
    need_driver = not tap_driver_installed()
    need_fw = not all(firewall_rule_ready(n) for n in names)
    if not need_driver and not need_fw:
        return "already"

    lines = ["$ErrorActionPreference = 'SilentlyContinue'"]
    if need_driver:
        lines.append('Set-Location -LiteralPath "%s"' % DRIVER_DIR)
        lines.append('& "%s" install "%s" tap0901' % (os.path.join(DRIVER_DIR, "tapinstall.exe"), TAP_INF))
        lines.append("Start-Sleep -Seconds 4")
    if need_fw:
        for name, exe in (("n2n edge room", EDGE_EXE), ("n2n supernode", SUPERNODE_EXE)):
            lines.append(
                'netsh advfirewall firewall add rule name="%s" dir=in action=allow program="%s" enable=yes'
                % (name, exe))
        # 虚拟 IP 发号是主程序自己在监听，不能按 exe 放行（源码与打包路径不同），
        # 按端口放行最稳：好友进房时会往 10.x.0.1:23336 发请求。
        lines.append(
            'netsh advfirewall firewall add rule name="n2n ip assign" dir=in action=allow '
            'protocol=UDP localport=%d enable=yes' % IP_ASSIGN_PORT)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        script_path = os.path.join(LOG_DIR, "prepare_room.ps1")
        with open(script_path, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("\n".join(lines))
    except Exception:
        return "denied"

    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                      "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.exists(ps):
        ps = "powershell.exe"
    started = run_elevated(ps, '-NoProfile -ExecutionPolicy Unrestricted -File "%s"' % script_path)
    if not started:
        return "denied"

    deadline = time.time() + 90
    while time.time() < deadline:
        d_ok = (not need_driver) or tap_driver_installed()
        f_ok = (not need_fw) or all(firewall_rule_ready(n) for n in names)
        if d_ok and f_ok:
            return "ok"
        time.sleep(2)
    return "ok" if (not need_driver and need_fw) else "denied"


def format_code(code):
    """把 8 位房间码显示成 ABCD-EFGH，方便口头传递"""
    code = clean_code(code)
    if len(code) != 8:
        return code
    return code[:4] + "-" + code[4:]


class App:
    """面向普通用户的简单界面：两个按钮 + 一个状态，内部全自动。"""

    STATE_COLORS = {
        "idle": "#9aa0a6",
        "preparing": "#0b64c4",
        "connecting": "#e08600",
        "connected": "#1a9e4b",
        "failed": "#d93025",
    }

    def __init__(self, root):
        self.root = root
        # 先清掉上次异常退出留下的 edge/supernode 孤儿，否则它们占着 TAP 和 7654，
        # 这一轮"创建房间"必然失败（表现为点建房后卡住/连不上）
        self._stale_killed = cleanup_stale_children()
        self.cfg = load_config()
        if not self.cfg.get("mc_mode", True):
            self.cfg["use_multicast"] = False
            self.cfg["auto_broadcast"] = False
        else:
            # 我的世界模式：开组播 + 局域网广播助手，好友在多人游戏列表里直接看到世界
            self.cfg["use_multicast"] = True
            self.cfg["auto_broadcast"] = True
        self.session = EdgeSession(self)
        self.host_sn = HostSupernode()
        self.ip_alloc = IpAllocator()
        self._is_host = False
        self._ip_asked = False
        self._v6_gateway_up = False
        self.local_ipv6s = set()
        self._connected = None
        self._params = None
        self._log_lines = []
        self._log_text = None
        self._settings_win = None
        self._busy = False
        self._pending_ok = False
        self._connect_deadline = 0
        self._fail_reason = ""
        self._retry_done = False
        self._host_mode = ""
        self._plan_lan = ""
        self._invite = ""
        self.chat_win = None
        self._chat_cache = []
        self.chat_listener = ChatListener(self.on_chat_msg)
        self.chat_listener.start()
        # 房间在线成员：进房后在虚拟网段广播自己，所有人互相看得见
        self.presence = None
        self.mem_tree = None
        self.lbl_members = None
        self._members_last_ui = 0.0
        if room_presence is not None:
            self.presence = room_presence.PresenceService(self._presence_name)
            try:
                self.presence.start()
            except Exception:
                self.presence = None
        # 在线更新：发现新版后在窗口顶部显示提示条
        self._latest_tag = ""
        self._latest_url = ""
        self._update_busy = False
        self._ver_btn = None

        global _lang
        _lang = self.cfg.get("lang") or detect_lang()
        if _lang not in LANGUAGES:
            _lang = "en"

        root.title(tr("app_title"))
        root.geometry("820x720")
        root.minsize(740, 620)

        self._build_ui()
        self._tick()
        # 启动 4 秒后自动查一次新版本（距上次检查不足 24 小时则跳过）
        self.root.after(4000, self._maybe_auto_check)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=16, pady=(12, 0))
        self._head = head
        ttk.Label(head, text=tr("app_title"), font=("", 15, "bold")).pack(side="left")
        ttk.Button(head, text=tr("settings_btn"), command=self.open_settings).pack(side="right")
        self._ver_btn = ttk.Button(head, text=tr("ver_btn", v=APP_VERSION),
                                   command=lambda: self.check_update(manual=True))
        self._ver_btn.pack(side="right", padx=(0, 8))

        # 更新提示条：发现新版才 pack 出来（默认隐藏）
        self.bar_update = tk.Frame(self.root, bg="#fff8e1")
        tk.Button(self.bar_update, text=tr("update_skip"), bd=0, bg="#fff8e1", fg="#8a5a00",
                  activebackground="#fff0c2", relief="flat", cursor="hand2",
                  command=self._skip_update_version).pack(side="right", padx=(0, 12), pady=8)
        ttk.Button(self.bar_update, text=tr("update_goto"),
                   command=self._open_update_page).pack(side="right", padx=6, pady=8)
        self.lbl_update = tk.Label(self.bar_update, text="", bg="#fff8e1", fg="#8a5a00",
                                   anchor="w", justify="left", font=("", 10), wraplength=500)
        self.lbl_update.pack(side="left", fill="x", expand=True, padx=(16, 8), pady=8)

        ttk.Label(self.root, text=tr("simple_tagline"), foreground="#777").pack(anchor="w", padx=16, pady=(2, 12))

        self.btn_host = ttk.Button(self.root, text=tr("create_room_big"), command=self.create_room)
        self.btn_host.pack(fill="x", padx=16, ipady=10)

        join_box = ttk.Frame(self.root)
        join_box.pack(fill="x", padx=16, pady=(14, 0))
        ttk.Label(join_box, text=tr("or_join_hint"), foreground="#777").pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(join_box)
        row.pack(fill="x")
        self.var_code = tk.StringVar()
        ent = ttk.Entry(row, textvariable=self.var_code, font=("Consolas", 14), width=26)
        ent.pack(side="left", ipady=3)
        ent.bind("<Return>", lambda e: self.join_room())
        self.btn_join = ttk.Button(row, text=tr("join_btn"), command=self.join_room)
        self.btn_join.pack(side="left", padx=8, ipady=2)

        st = ttk.Frame(self.root)
        st.pack(fill="x", padx=16, pady=(18, 0))
        self.lbl_dot = tk.Label(st, text="●", font=("", 15), fg="#9aa0a6")
        self.lbl_dot.pack(side="left")
        self.lbl_state = tk.Label(st, text=tr("status_idle"), font=("", 14, "bold"), fg="#444")
        self.lbl_state.pack(side="left", padx=6)
        self.lbl_note = tk.Label(st, text="", font=("", 9), fg="#777", justify="left",
                                 anchor="w", wraplength=560)
        self.lbl_note.pack(side="left", padx=10, fill="x", expand=True)

        self.lbl_tip = ttk.Label(self.root, text=tr("mc_tip"), foreground="#555",
                                 wraplength=660, justify="left")

        self.card = ttk.LabelFrame(self.root, text=tr("invite_title"))
        self.var_invite = tk.StringVar()
        self.lbl_invite = tk.Label(self.card, textvariable=self.var_invite,
                                   font=("Consolas", 15, "bold"), fg="#0b64c4")
        self.lbl_invite.pack(anchor="w", padx=10, pady=(8, 2))
        ttk.Label(self.card, text=tr("invite_hint"), foreground="#777",
                  wraplength=640, justify="left").pack(anchor="w", padx=10)
        self.lbl_mc = tk.Label(self.card, text="", font=("Consolas", 11), fg="#333")
        self.lbl_mc.pack(anchor="w", padx=10, pady=(4, 0))

        # ---- 房间成员：人数 / 虚拟 IP / 角色 / 名称 ----
        self.lbl_members = tk.Label(self.card, text=tr("members_wait"),
                                    font=("", 9), fg="#555", anchor="w")
        self.lbl_members.pack(anchor="w", padx=10, pady=(8, 2))
        mem_box = ttk.Frame(self.card)
        mem_box.pack(fill="x", padx=10)
        self.mem_tree = ttk.Treeview(mem_box, columns=("ip", "role", "name"),
                                     show="headings", height=3)
        self.mem_tree.heading("ip", text=tr("col_ip"))
        self.mem_tree.heading("role", text=tr("col_role"))
        self.mem_tree.heading("name", text=tr("col_name"))
        self.mem_tree.column("ip", width=128, anchor="w", stretch=False)
        self.mem_tree.column("role", width=64, anchor="center", stretch=False)
        self.mem_tree.column("name", width=240, anchor="w")
        mem_sb = ttk.Scrollbar(mem_box, orient="vertical", command=self.mem_tree.yview)
        self.mem_tree.configure(yscrollcommand=mem_sb.set)
        self.mem_tree.pack(side="left", fill="x", expand=True)
        mem_sb.pack(side="right", fill="y")
        self.mem_tree.tag_configure("host", foreground="#b3261e")
        crow = ttk.Frame(self.card)
        crow.pack(fill="x", padx=10, pady=8)
        ttk.Button(crow, text=tr("copy_invite"), command=self.copy_invite).pack(side="left")
        if HAS_QR:
            ttk.Button(crow, text=tr("show_qr"), command=self.open_qr).pack(side="left", padx=6)
        ttk.Button(crow, text=tr("chat"), command=self.open_chat).pack(side="left", padx=6)
        ttk.Button(crow, text=tr("leave_btn"), command=self.leave_room).pack(side="right")

        self.lbl_tip.pack(anchor="w", padx=16, pady=(16, 4))

    # ---------------- 在线更新 ----------------
    def _maybe_auto_check(self):
        """启动后自动查一次新版本；距上次检查不足 24 小时就跳过，避免每次开窗都去戳 GitHub"""
        uc = self.cfg.get("update_check") or {}
        try:
            last = float((uc or {}).get("last") or 0)
        except (TypeError, ValueError):
            last = 0
        if time.time() - last >= UPDATE_INTERVAL:
            self.check_update(manual=False)

    def check_update(self, manual=False):
        """manual=True 时用户点了版本号按钮，无论结果都回一句；False 为后台静默检查"""
        if self._update_busy:
            return
        self._update_busy = True
        if self._ver_btn is not None:
            self._ver_btn.configure(state="disabled", text=tr("update_checking"))
        threading.Thread(target=self._update_worker, args=(manual,), daemon=True).start()

    def _update_worker(self, manual):
        try:
            tag, url = fetch_latest_release()
        except Exception:
            tag, url = None, ""
        try:
            self.root.after(0, lambda: self._update_done(manual, tag, url))
        except Exception:
            pass

    def _update_done(self, manual, tag, url):
        self._update_busy = False
        if self._ver_btn is not None:
            self._ver_btn.configure(state="normal", text=tr("ver_btn", v=APP_VERSION))
        self._latest_tag = tag or ""
        self._latest_url = url or UPDATE_PAGE
        self._mark_checked()

        if not tag:
            if manual:
                messagebox.showinfo(tr("info"), tr("update_none"), parent=self.root)
            return
        if compare_version(tag, APP_VERSION) > 0:
            skip = ((self.cfg.get("update_check") or {}).get("skip") or "").strip()
            if not manual and skip and compare_version(tag, skip) <= 0:
                return                       # 用户选了"不再提示此版本"
            self._show_update_bar(tag)
        elif manual:
            messagebox.showinfo(tr("info"), tr("update_latest", v=APP_VERSION), parent=self.root)

    def _mark_checked(self):
        uc = self.cfg.get("update_check")
        if not isinstance(uc, dict):
            uc = {"last": 0, "skip": ""}
        uc["last"] = int(time.time())
        self.cfg["update_check"] = uc
        save_config(self.cfg)

    def _show_update_bar(self, tag):
        self._latest_tag = tag
        shown = re.sub(r"^[vV]", "", (tag or "").strip())   # tag 自带 V 前缀，展示时不重复
        self.lbl_update.configure(text=tr("update_available", new=shown, cur=APP_VERSION))
        if not self.bar_update.winfo_manager():
            self.bar_update.pack(fill="x", after=self._head)

    def _open_update_page(self):
        open_external(self._latest_url or UPDATE_PAGE)

    def _skip_update_version(self):
        if self._latest_tag:
            uc = self.cfg.get("update_check")
            if not isinstance(uc, dict):
                uc = {"last": 0, "skip": ""}
            uc["skip"] = self._latest_tag
            self.cfg["update_check"] = uc
            save_config(self.cfg)
        self.bar_update.pack_forget()

    def _set_state(self, kind, note=""):
        color = self.STATE_COLORS.get(kind, "#444")
        self.lbl_dot.configure(fg=color)
        self.lbl_state.configure(fg=color, text=tr("status_" + kind))
        self.lbl_note.configure(text=note, fg=color if kind in ("failed", "connected") else "#777")

        if kind == "connected":
            self.btn_host.configure(state="disabled")
            self.btn_join.configure(state="disabled")
            if not self.card.winfo_ismapped():
                self.card.pack(fill="x", padx=16, pady=(14, 0), before=self.lbl_tip)
        else:
            if not self._busy:
                self.btn_host.configure(state="normal")
                self.btn_join.configure(state="normal")
            if kind == "failed":
                self.btn_host.configure(state="normal")
                self.btn_join.configure(state="normal")
                self._busy = False

    def _finish_fail(self, note=""):
        self._busy = False
        self._set_state("failed", note or tr("fail_final"))
        self.session.stop()
        self.host_sn.stop()
        self.ip_alloc.stop()
        self._connected = None

    # ---------------- 房主流程 ----------------
    def create_room(self):
        if self._busy or self.session.running:
            return
        self._busy = True
        self.btn_host.configure(state="disabled")
        self.btn_join.configure(state="disabled")
        self._set_state("preparing", tr("prep_driver"))
        self._retry_done = False
        self._is_host = True
        self._ip_asked = False
        self._v6_gateway_up = False
        params = code_to_params(gen_short_code())
        snapshot = dict(self.cfg)
        threading.Thread(target=self._host_flow, args=(params, snapshot), daemon=True).start()

    def _host_flow(self, params, cfg):
        """后台线程：准备驱动 → 规划网络 → 起本机服务器 → 起 edge"""
        def ui(fn):
            try:
                self.root.after(0, fn)
            except Exception:
                pass

        try:
            ui(lambda: self._set_state("preparing", tr("prep_driver")))
            res = prepare_system()
            if res == "denied":
                ui(lambda: self._finish_fail(tr("fail_final")))
                return
            self._ensure_firewall()

            ui(lambda: self._set_state("preparing", tr("prep_net")))
            try:
                self.local_ipv6s = set(get_local_ipv6s())
            except Exception:
                self.local_ipv6s = set()
            plan = plan_host_network(cfg, local6=self.local_ipv6s)
            if plan["mode"] == "none":
                ui(lambda: self._finish_fail(tr("no_public_net")))
                return

            server = plan["server"]
            mode = plan["mode"]
            self._plan_lan = plan.get("lan_ip", "")
            if mode in ("v4", "manual", "v6", "lan"):
                ui(lambda: self._set_state("preparing", tr("prep_server")))
                stt = self.host_sn.start()
                if stt in ("fail", "missing"):
                    nodes = [n.strip() for n in (cfg.get("public_nodes") or []) if n.strip()]
                    if not nodes:
                        ui(lambda: self._finish_fail(tr("fail_final")))
                        return
                    mode = "public"
                    server = ",".join(nodes)
            self._host_mode = mode
            invite = make_invite(params["code"], server)
            # 服务器就在本机：自己走回环，好友走公网/局域网地址（邀请码里带这个地址）
            connect_server = server
            if mode in ("v4", "manual", "v6", "lan"):
                connect_server = "127.0.0.1:%d" % DEFAULT_SUPERNODE_PORT
            ui(lambda: self._start_edge(params, connect_server, invite))
        except Exception as e:
            msg = str(e)
            ui(lambda: self._finish_fail(msg))

    def _ensure_firewall(self):
        """prepare_system() 之后的兜底：规则缺失才补一次（正常不会触发）"""
        if not IS_WINDOWS:
            return True
        names = ("n2n edge room", "n2n supernode", "n2n ip assign")
        if all(firewall_rule_ready(n) for n in names):
            return True
        try:
            add_firewall_rule()
        except Exception:
            pass
        return True

    # ---------------- 好友流程 ----------------
    def join_room(self):
        if self._busy or self.session.running:
            return
        text = self.var_code.get().strip()
        if not text:
            self._set_state("failed", tr("need_code"))
            return
        parsed = parse_invite(text)
        if not parsed:
            self._set_state("failed", tr("bad_code_hint"))
            return

        if parsed.get("legacy"):
            params = {"code": parsed["community"], "community": parsed["community"],
                      "subnet": parsed["subnet"], "key": parsed["key"],
                      "host_ip": suggest_ip(parsed["subnet"], self.cfg)}
        else:
            params = {
                "code": parsed["code"],
                "community": parsed["community"],
                "subnet": parsed["subnet"],
                "key": parsed["key"],
                "host_ip": suggest_ip(parsed["subnet"], self.cfg),
            }

        self._busy = True
        self.btn_host.configure(state="disabled")
        self.btn_join.configure(state="disabled")
        self._retry_done = False
        self._is_host = False
        self._ip_asked = False
        self._v6_gateway_up = False
        self._set_state("preparing", tr("prep_driver"))
        server = parsed.get("server") or ""
        threading.Thread(target=self._join_flow, args=(params, server), daemon=True).start()

    def _join_flow(self, params, server):
        def ui(fn):
            try:
                self.root.after(0, fn)
            except Exception:
                pass

        try:
            ui(lambda: self._set_state("preparing", tr("prep_driver")))
            res = prepare_system()
            if res == "denied":
                ui(lambda: self._finish_fail(tr("fail_final")))
                return

            if not server:
                nodes = [n.strip() for n in (self.cfg.get("public_nodes") or []) if n.strip()]
                custom = (self.cfg.get("supernode") or "").strip()
                if custom:
                    server = custom
                elif nodes:
                    server = ",".join(nodes)
                else:
                    ui(lambda: self._finish_fail(tr("no_server_hint")))
                    return

            self._host_mode = "public"
            ui(lambda: self._start_edge(params, server, make_invite(params["code"], server)))
        except Exception as e:
            msg = str(e)
            ui(lambda: self._finish_fail(msg))

    # ---------------- 起 edge / 状态 ----------------
    def _start_edge(self, params, server, invite):
        self._params = params
        self._invite = invite
        self.var_invite.set(format_code(params["code"]))
        self._pending_ok = False
        self._fail_reason = ""
        self._connect_deadline = time.time() + 40
        self._set_state("connecting", tr("prep_edge"))
        try:
            self.session.start(params["community"], params["key"], params["host_ip"],
                               [s for s in server.split(",") if s.strip()])
        except Exception as e:
            self._finish_fail(str(e))
            return
        self._connected = {"community": params["community"], "code": params["code"],
                           "ip": params["host_ip"], "server": server}
        self.chat_listener.set_room(params["community"])
        if self._is_host and self._host_mode == "v6":
            self._start_v6_gateway()

    def _start_v6_gateway(self):
        """IPv6 兜底：supernode 只监听 IPv4，这里对 IPv6 世界开门。"""
        if self._v6_gateway_up:
            return
        ok = self.session.start_server_forwarder(DEFAULT_SUPERNODE_PORT, DEFAULT_SUPERNODE_PORT)
        self._v6_gateway_up = bool(ok)
        if ok:
            self.append_log(tr("log_v6_gateway", port=DEFAULT_SUPERNODE_PORT))
        else:
            self.append_log(tr("log_v6_gateway_fail"))

    def _on_edge_log(self, line):
        """edge 日志 → 人话状态机（后台线程调用）"""
        if "[OK] edge" in line:
            if self._connected and not self._pending_ok:
                self._pending_ok = True
                try:
                    self.root.after(0, self._mark_connected)
                except Exception:
                    pass
        elif "authentication error" in line:
            self._fail_reason = "busy"
        elif "supernode not responding" in line:
            if self._fail_reason != "busy":
                self._fail_reason = "noresp"

    def _mark_connected(self):
        self._busy = False
        mode = self._host_mode
        if mode == "manual":
            note = tr("host_mode_manual", lan=self._plan_lan or tr("lan_unknown"))
        elif mode == "v4":
            note = tr("host_mode_v4")
        elif mode == "v6":
            note = tr("host_mode_v6")
        elif mode == "lan":
            note = tr("host_mode_lan")
        else:
            note = tr("host_mode_public")
        self._set_state("connected", note)
        # 游戏内连接地址（组播发现不通时好友可手动填；房主虚拟 IP 恒为网段 .1）
        subnet = ""
        try:
            subnet = (self._params or {}).get("subnet", "")
        except Exception:
            subnet = ""
        host_ip = (subnet + ".1") if subnet else ""
        self.lbl_mc.configure(text=tr("mc_addr", ip=host_ip) if host_ip else "")
        # 房主负责发号；好友去领号，避免所有人挤在同一个虚拟 IP 上
        if self._is_host:
            self._start_ip_allocator()
        else:
            self._request_ip_async()
        self._sync_presence()

    # ---------------- 房间在线成员 ----------------
    def _presence_name(self):
        """给成员表用的显示名：只读配置，绝不写盘（presence 每 3 秒取一次）"""
        try:
            name = (self.cfg.get("username") or "").strip()
        except Exception:
            name = ""
        if not name:
            try:
                name = socket.gethostname()[:16]
            except Exception:
                name = ""
        return name

    def _sync_presence(self):
        """把当前房间信息同步给 presence 广播（连上、换 IP 后都要调）"""
        if self.presence is None:
            return
        params = self._params or {}
        server = ""
        invite = self._invite or ""
        if "@" in invite:
            server = invite.split("@", 1)[1].strip()
        try:
            self.presence.set_room(community=params.get("community") or "",
                                   code=params.get("code") or "",
                                   subnet=params.get("subnet") or "",
                                   my_ip=params.get("host_ip") or "",
                                   is_host=bool(self._is_host),
                                   name=self._presence_name(),
                                   server=server,
                                   version=APP_VERSION)
        except Exception:
            pass
        self._refresh_members()

    def _refresh_members(self):
        """把 presence 快照画到成员表上（UI 线程调用）"""
        if self.mem_tree is None or self.lbl_members is None:
            return
        if self.presence is None:
            try:
                self.lbl_members.configure(text=tr("members_wait"))
            except Exception:
                pass
            return
        try:
            rows = self.presence.snapshot()
        except Exception:
            rows = []
        n = len(rows)
        host_ip = ""
        for r in rows:
            if r.get("role") == "host":
                host_ip = r.get("ip") or ""
                break
        try:
            if n <= 1:
                self.lbl_members.configure(text=tr("members_alone") if self._connected
                                           else tr("members_wait"))
            else:
                self.lbl_members.configure(text=tr("members_fmt", n=n,
                                                   host=host_ip or "—"))
        except Exception:
            pass
        try:
            self.mem_tree.delete(*self.mem_tree.get_children())
        except Exception:
            return
        for r in rows:
            ip = r.get("ip") or "—"
            is_host = r.get("role") == "host"
            name = r.get("name") or "—"
            if r.get("self"):
                name += tr("member_self_suffix")
            try:
                self.mem_tree.insert("", "end",
                                     values=(ip,
                                             tr("role_host") if is_host else tr("role_guest"),
                                             name),
                                     tags=("host",) if is_host else ())
            except Exception:
                break

    def _start_ip_allocator(self):
        """房主开始发号：绑 .1 的 UDP 端口，好友来领唯一尾号。"""
        params = self._params or {}
        subnet = params.get("subnet") or ""
        code = params.get("code") or ""
        if not subnet or not code or self.ip_alloc.running:
            return
        self.ip_alloc.on_log = self.append_log
        if self.ip_alloc.start(subnet, code, self.cfg):
            self.append_log(tr("log_alloc_up", ip=subnet + ".1", port=IP_ASSIGN_PORT))
        else:
            self.append_log(tr("log_alloc_fail"))

    def _request_ip_async(self):
        """好友领号：拿到与当前不同的 IP 就换号重连，从机制上消灭 .2 撞车。"""
        if self._ip_asked:
            return
        self._ip_asked = True
        params = self._params or {}
        subnet = params.get("subnet") or ""
        code = params.get("code") or ""
        current = params.get("host_ip") or ""
        if not subnet or not code or not current:
            return
        mid = machine_id(self.cfg)

        def work():
            ip = request_room_ip(subnet, code, mid, current, timeout=22.0)
            if not ip or ip == current or not validate_ip(ip):
                return
            try:
                self.root.after(0, lambda: self._switch_ip(ip, current))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _switch_ip(self, new_ip, old_ip):
        """房主发了别的号：用新 IP 重启 edge（同一房间码、同一服务器）。"""
        if self._busy or not self.session.running:
            return
        params = self._params or {}
        if params.get("host_ip") == new_ip:
            return
        self.append_log(tr("log_ip_switch", new=new_ip, old=old_ip))
        params["host_ip"] = new_ip
        if self._connected:
            self._connected["ip"] = new_ip
        server = (self._connected or {}).get("server") or ""
        self._pending_ok = False
        self._connect_deadline = time.time() + 40
        try:
            self.session.stop()
            self.session.start(params["community"], params["key"], new_ip,
                               [s for s in server.split(",") if s.strip()])
        except Exception as e:
            self._finish_fail(str(e))
            return
        if self.presence is not None:
            try:
                self.presence.set_my_ip(new_ip)
            except Exception:
                pass
        self._sync_presence()

    def _tick(self):
        if self._connected and not self._pending_ok and time.time() > self._connect_deadline:
            self._on_timeout()
        # 成员表每 2.5 秒刷新一次（presence 内部 3 秒一轮广播）
        try:
            if (self._connected and self.mem_tree is not None
                    and time.time() - self._members_last_ui >= 2.5):
                self._members_last_ui = time.time()
                self._refresh_members()
        except Exception:
            pass
        try:
            self.root.after(1500, self._tick)
        except Exception:
            pass

    def _on_timeout(self):
        """超时未握手：自动换方案重试一次（普通用户全程无感知），再判定失败"""
        if self._fail_reason == "busy":
            self._finish_fail(tr("room_busy_hint"))
            return
        if self._retry_done or not self._params:
            self._finish_fail(tr("fail_final"))
            return
        self._retry_done = True
        self.session.stop()
        self._set_state("connecting", tr("fail_human"))
        snapshot = dict(self.cfg)
        snapshot["supernode"] = ""
        threading.Thread(target=self._fallback_flow, args=(snapshot,), daemon=True).start()

    def _fallback_flow(self, cfg):
        """降级链兜底：重新规划网络方案并重连"""
        def ui(fn):
            try:
                self.root.after(0, fn)
            except Exception:
                pass

        try:
            try:
                self.local_ipv6s = set(get_local_ipv6s())
            except Exception:
                self.local_ipv6s = set()
            plan = plan_host_network(cfg, local6=self.local_ipv6s)
            server = plan["server"]
            mode = plan["mode"]
            self._plan_lan = plan.get("lan_ip", "")
            if mode == "none" or not server:
                ui(lambda: self._finish_fail(tr("no_public_net")))
                return
            if mode in ("v4", "manual", "v6", "lan"):
                stt = self.host_sn.start()
                if stt in ("fail", "missing"):
                    nodes = [n.strip() for n in (cfg.get("public_nodes") or []) if n.strip()]
                    if not nodes:
                        ui(lambda: self._finish_fail(tr("fail_final")))
                        return
                    server, mode = ",".join(nodes), "public"
            self._host_mode = mode
            connect_server = server
            if mode in ("v4", "manual", "v6", "lan"):
                connect_server = "127.0.0.1:%d" % DEFAULT_SUPERNODE_PORT
            ui(lambda: self._start_edge(self._params, connect_server,
                                        make_invite(self._params["code"], server)))
        except Exception as e:
            msg = str(e)
            ui(lambda: self._finish_fail(msg))

    def leave_room(self):
        if not self._connected and not self.session.running:
            return
        if not messagebox.askyesno(tr("info"), tr("leave_confirm")):
            return
        self.session.stop()
        self.host_sn.stop()
        self.ip_alloc.stop()
        self._connected = None
        self._busy = False
        self.chat_listener.clear_room()
        if self.presence is not None:
            try:
                self.presence.clear_room()
            except Exception:
                pass
        if self.mem_tree is not None:
            try:
                self.mem_tree.delete(*self.mem_tree.get_children())
                self.lbl_members.configure(text=tr("members_wait"))
            except Exception:
                pass
        if self.chat_win is not None:
            self._close_chat()
        if self.card.winfo_ismapped():
            self.card.pack_forget()
        self._set_state("idle")

    def copy_invite(self):
        text = self._invite or format_code(self.var_code.get())
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_state(self._state_kind(), tr("copied"))

    def open_qr(self):
        """把邀请码变成二维码，好友用手机扫或截图发过去都行"""
        text = self._invite or format_code(self.var_code.get())
        if not text:
            messagebox.showinfo(tr("info"), tr("need_code"))
            return
        if not HAS_QR:
            messagebox.showinfo(tr("info"), tr("qr_unavailable"))
            return
        try:
            qr = qrcode.QRCode(border=2, box_size=10)
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(image_factory=qr_pure.PyPNGImage)
            os.makedirs(LOG_DIR, exist_ok=True)
            qr_path = os.path.join(LOG_DIR, "invite_qr.png")
            img.save(qr_path)
            photo = tk.PhotoImage(file=qr_path)
        except Exception:
            messagebox.showinfo(tr("info"), tr("qr_unavailable"))
            return

        win = tk.Toplevel(self.root)
        win.title(tr("qr_title"))
        win.geometry("420x520")
        win.transient(self.root)
        lbl = tk.Label(win, image=photo)
        lbl.image = photo
        lbl.pack(pady=14)
        tk.Label(win, text=text, font=("Consolas", 13, "bold"), fg="#0b64c4").pack()
        ttk.Label(win, text=tr("qr_hint"), foreground="#777", wraplength=360,
                  justify="center").pack(pady=6)
        ttk.Button(win, text=tr("app_ok"), command=win.destroy).pack(pady=8)

    def _state_kind(self):
        if self._connected and self._pending_ok:
            return "connected"
        if self._connected:
            return "connecting"
        return "idle"

    # ---------------- 设置窗口 ----------------
    def open_settings(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title(tr("settings_title"))
        win.geometry("660x620")
        win.minsize(600, 520)

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=12, pady=10)

        row1 = ttk.Frame(body)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text=tr("lang")).pack(side="left")
        self.var_lang = tk.StringVar(value=_lang)
        cmb = ttk.Combobox(row1, textvariable=self.var_lang, values=["zh", "en"],
                           width=5, state="readonly")
        cmb.pack(side="left", padx=6)
        cmb.bind("<<ComboboxSelected>>", self.on_lang_change)

        self.var_mc = tk.BooleanVar(value=bool(self.cfg.get("mc_mode", True)))
        ttk.Checkbutton(body, text=tr("mc_mode_opt"), variable=self.var_mc,
                        command=self.save_settings).pack(anchor="w", pady=2)

        self.var_dev = tk.BooleanVar(value=bool(self.cfg.get("dev_mode", False)))
        ttk.Checkbutton(body, text=tr("dev_mode_opt"), variable=self.var_dev,
                        command=self.toggle_dev).pack(anchor="w", pady=2)

        f_srv = ttk.LabelFrame(body, text=tr("srv_custom"))
        f_srv.pack(fill="x", pady=(10, 4))
        self.var_supernode = tk.StringVar(value=self.cfg.get("supernode", ""))
        ttk.Entry(f_srv, textvariable=self.var_supernode).pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(f_srv, text=tr("srv_custom_hint"), foreground="#777",
                  wraplength=580, justify="left").pack(anchor="w", padx=8)
        ttk.Button(f_srv, text=tr("save"), command=self.save_supernode).pack(anchor="e", padx=8, pady=6)

        f_pub = ttk.LabelFrame(body, text=tr("srv_public"))
        f_pub.pack(fill="x", pady=4)
        self.txt_pub = tk.Text(f_pub, height=3)
        self.txt_pub.pack(fill="x", padx=8, pady=(6, 2))
        self.txt_pub.insert("1.0", "\n".join(self.cfg.get("public_nodes") or []))
        ttk.Button(f_pub, text=tr("save"), command=self.save_supernode).pack(anchor="e", padx=8, pady=(0, 6))

        tools = ttk.LabelFrame(body, text=tr("advanced_tools"))
        tools.pack(fill="x", pady=6)
        bar = ttk.Frame(tools)
        bar.pack(fill="x", padx=6, pady=6)
        for label, cmd in ((tr("install_driver"), self.cmd_install_driver),
                           (tr("firewall"), self.cmd_firewall),
                           (tr("check_public_ip"), self.check_public_ip),
                           (tr("open_logs"), self.open_logs),
                           (tr("open_bin"), self.open_bin)):
            ttk.Button(bar, text=label, command=cmd).pack(side="left", padx=2)

        self.log_frame = ttk.LabelFrame(body, text=tr("log_title"))
        self._log_text = scrolledtext.ScrolledText(self.log_frame, height=10, state="disabled",
                                                   font=("Consolas", 9))
        self._log_text.pack(fill="both", expand=True, padx=6, pady=6)
        if self.var_dev.get():
            self.log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self._dump_log()

        ttk.Button(body, text=tr("app_ok"), command=self._close_settings).pack(anchor="e", pady=(8, 0))
        win.protocol("WM_DELETE_WINDOW", self._close_settings)
        win.transient(self.root)

    def _close_settings(self):
        if self._settings_win is not None:
            self._settings_win.destroy()
        self._settings_win = None
        self._log_text = None

    def toggle_dev(self):
        self.cfg["dev_mode"] = bool(self.var_dev.get())
        save_config(self.cfg)
        if self._settings_win is None:
            return
        if self.var_dev.get():
            if not self.log_frame.winfo_ismapped():
                self.log_frame.pack(fill="both", expand=True, pady=(8, 0))
            self._dump_log()
        else:
            self.log_frame.pack_forget()

    def _dump_log(self):
        if self._log_text is None:
            return
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        for line in self._log_lines[-400:]:
            self._log_text.insert("end", line + "\n")
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _write_log(self, line):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state="normal")
            self._log_text.insert("end", line + "\n")
            self._log_text.see("end")
            self._log_text.config(state="disabled")
        except Exception:
            pass

    def on_lang_change(self, _event=None):
        global _lang
        new_lang = self.var_lang.get() if self.var_lang.get() in LANGUAGES else "en"
        _lang = new_lang
        self.cfg["lang"] = new_lang
        save_config(self.cfg)
        messagebox.showinfo(tr("info"), tr("lang_switch"))

    def save_supernode(self):
        self.cfg["supernode"] = self.var_supernode.get().strip()
        nodes = [ln.strip() for ln in self.txt_pub.get("1.0", "end").splitlines() if ln.strip()]
        self.cfg["public_nodes"] = nodes
        save_config(self.cfg)
        messagebox.showinfo(tr("info"), tr("save"))

    def save_settings(self):
        self.cfg["mc_mode"] = bool(self.var_mc.get())
        self.cfg["use_multicast"] = bool(self.var_mc.get())
        self.cfg["auto_broadcast"] = bool(self.var_mc.get())
        save_config(self.cfg)

    # ---------------- 公网 IP 检测 ----------------
    def check_public_ip(self):
        def work():
            try:
                info = detect_public_ip()
            except Exception as e:
                info = {"local_ip": "", "local_kind": "invalid", "public_ip4": "",
                        "public_ip6": "", "ipv6_public": False, "verdict": "unknown",
                        "errors4": str(e), "errors6": ""}
            try:
                self.root.after(0, lambda: self._show_pip_result(info))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _show_pip_result(self, info):
        kind_map = {
            "public": tr("pip_kind_public"),
            "private": tr("pip_kind_private"),
            "cgnat": tr("pip_kind_cgnat"),
            "loopback": tr("pip_kind_loopback"),
            "linklocal": tr("pip_kind_linklocal"),
        }
        local_ip = info.get("local_ip") or "-"
        local_kind = kind_map.get(info.get("local_kind"), tr("pip_kind_other"))
        pub4 = info.get("public_ip4") or ""
        pub6 = info.get("public_ip6") or ""
        verdict = info.get("verdict") or "unknown"

        lines = [
            tr("pip_local", ip=local_ip, kind=local_kind),
            tr("pip_public4", ip=pub4) if pub4 else tr("pip_public4_unknown"),
            tr("pip_public6", ip=pub6) if pub6 else tr("pip_public6_none"),
            "",
        ]
        if verdict == "direct":
            lines.append(tr("pip_direct"))
        elif verdict == "nat":
            lines.append(tr("pip_nat", ip=pub4, local=local_ip))
        elif verdict == "cgnat":
            lines.append(tr("pip_cgnat", ip=pub4))
        else:
            lines.append(tr("pip_unknown"))
            if info.get("errors4"):
                lines.append(tr("pip_err_detail", errs=info.get("errors4")))
        if info.get("ipv6_public"):
            lines.append("")
            lines.append(tr("pip_v6_tip"))
        lines.append("")
        lines.append(tr("pip_tip"))
        text = "\n".join(lines)

        win = tk.Toplevel(self.root)
        win.title(tr("pip_title"))
        win.geometry("660x400")
        win.transient(self.root)
        box = tk.Text(win, wrap="word", height=12)
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", text)
        box.configure(state="disabled")
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=10, pady=(0, 10))

        def do_copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo(tr("info"), tr("pip_copied"), parent=win)

        ttk.Button(bar, text=tr("pip_copy"), command=do_copy).pack(side="left")
        ttk.Button(bar, text=tr("app_ok"), command=win.destroy).pack(side="right")

    # ---------------- 房间聊天 ----------------
    def current_username(self):
        name = self.var_username.get().strip()
        if not name:
            prefix = "玩家" if _lang == "zh" else "Player"
            name = "%s%d" % (prefix, random.randint(1000, 9999))
            self.var_username.set(name)
        self.cfg["username"] = name
        save_config(self.cfg)
        return name

    def open_chat(self):
        if not self._connected:
            messagebox.showinfo(tr("info"), tr("chat_need_room"))
            return
        if self.chat_win is not None and self.chat_win.winfo_exists():
            self.chat_win.lift()
            return

        win = tk.Toplevel(self.root)
        self.chat_win = win
        win.title(tr("chat_title", room=format_code(self._connected["code"])))
        win.geometry("520x420")
        win.minsize(420, 320)

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text=tr("chat_name")).pack(side="left")
        self.var_username = tk.StringVar(value=self.cfg.get("username", ""))
        ttk.Entry(top, textvariable=self.var_username, width=20).pack(side="left", padx=6)
        ttk.Button(top, text=tr("save"), command=self.save_chat_name).pack(side="left", padx=4)
        ttk.Label(top, text=tr("chat_name_hint"), foreground="#666").pack(side="left", padx=6)

        chat_font = ("PingFang SC", 11) if IS_MACOS else ("Microsoft YaHei UI", 10)
        self.txt_chat = scrolledtext.ScrolledText(win, height=14, state="disabled", font=chat_font)
        self.txt_chat.pack(fill="both", expand=True, padx=10, pady=4)

        bottom = ttk.Frame(win)
        bottom.pack(fill="x", padx=10, pady=8)
        self.var_chat_msg = tk.StringVar()
        entry = ttk.Entry(bottom, textvariable=self.var_chat_msg)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", self.send_chat)
        ttk.Button(bottom, text=tr("chat_send"), command=self.send_chat).pack(side="left")

        for line in self._chat_cache:
            self._chat_append_line(line)
        if not self._chat_cache:
            self._chat_append_line(tr("chat_no_msg"))

        win.protocol("WM_DELETE_WINDOW", self._close_chat)

    def _close_chat(self):
        if self.chat_win is not None:
            self.chat_win.destroy()
        self.chat_win = None

    def _chat_append_line(self, line):
        if self.txt_chat is not None:
            self.txt_chat.config(state="normal")
            self.txt_chat.insert("end", line + "\n")
            self.txt_chat.see("end")
            self.txt_chat.config(state="disabled")

    def on_chat_msg(self, user, msg):
        line = "[%s] %s: %s" % (time.strftime("%H:%M"), user, msg)
        self._chat_cache.append(line)
        if len(self._chat_cache) > 200:
            self._chat_cache = self._chat_cache[-200:]
        if self.chat_win is not None and self.chat_win.winfo_exists():
            try:
                self.root.after(0, lambda: self._chat_append_line(line))
            except Exception:
                pass

    def save_chat_name(self):
        name = self.var_username.get().strip()
        if not name:
            name = self.current_username()
        self.cfg["username"] = name
        save_config(self.cfg)
        messagebox.showinfo(tr("info"), tr("chat_saved", name=name))

    def send_chat(self, _event=None):
        if not self._connected:
            messagebox.showinfo(tr("info"), tr("chat_need_room"))
            return
        msg = self.var_chat_msg.get().strip()
        if not msg:
            return
        ip = self._connected.get("ip", "")
        bcast = chat_broadcast_addr(ip)
        if not bcast:
            messagebox.showinfo(tr("info"), tr("chat_need_room"))
            return
        name = self.current_username()
        payload = json.dumps({
            "v": CHAT_PROTO_VERSION,
            "c": self._connected["community"],
            "u": name,
            "m": msg,
        }).encode("utf-8")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(payload, (bcast, CHAT_PORT))
            s.close()
        except Exception:
            pass
        self.var_chat_msg.set("")
        self.on_chat_msg(name, msg)

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
        elif res == "manual":
            if IS_MACOS:
                messagebox.showinfo(
                    tr("check_result"),
                    "macOS 需要 tuntap 驱动（Apple 芯片需允许内核扩展）。\n"
                    "请在「系统设置 → 隐私与安全性」允许后运行：\n"
                    "  brew install --cask tuntap\n"
                    "或参考官网 README 的 macOS 章节。")
            else:
                messagebox.showinfo(
                    tr("check_result"),
                    "Linux 需要 TUN 设备：sudo modprobe tun（或 sudo apt install tunctl）")
        elif res == "denied":
            messagebox.showerror(tr("not_installed"), tr("uac_cancel"))
        else:
            messagebox.showerror(tr("install_fail"), tr("silent_fail_msg"))

    def cmd_firewall(self):
        if IS_MACOS:
            self.append_log(">> macOS 会在首次运行 edge 时自动询问是否允许传入连接，点「允许」即可")
            return
        ok = add_firewall_rule()
        self.append_log(tr("log_fw_ok") if ok else tr("log_fw_cancel"))

    def open_logs(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        open_folder(LOG_DIR)

    def open_bin(self):
        open_folder(os.path.join(BASE_DIR, "bin"))

    # ---------------- 日志（后台线程安全） ----------------
    def append_log(self, line):
        self._log_lines.append(line)
        if len(self._log_lines) > 2000:
            self._log_lines = self._log_lines[-1200:]
        self._on_edge_log(line)
        try:
            self.root.after(0, lambda: self._write_log(line))
        except Exception:
            pass


def selftest():
    print("== n2n 房间助手 自检 ==")
    print("Python:", sys.version.split()[0])
    print("平台:", sys.platform)
    print("edge 存在:", os.path.exists(EDGE_EXE))
    print("supernode 存在:", os.path.exists(SUPERNODE_EXE))
    print("驱动目录存在:", os.path.exists(TAP_INF))
    print("虚拟网卡驱动就绪:", tap_driver_installed())
    print("本机 IPv6:", ", ".join(sorted(get_local_ipv6s())) or "(无)")

    code = gen_short_code()
    p = code_to_params(code)
    print("8 位房间码:", format_code(code))
    print("派生参数:", p)
    print("码 → 参数 → 邀请码:", make_invite(code, "1.2.3.4:7654"))
    print("邀请码解析:", parse_invite(make_invite(code, "1.2.3.4:7654")))
    print("旧格式兼容:", bool(parse_invite(make_room_code("mc-test", "10.88.0", "Ab3CdEfGhJ"))))
    print("同码派生一致:", code_to_params(code)["key"] == p["key"])

    local_ip4 = get_primary_local_ip()
    print("本机主网卡 IPv4:", local_ip4 or "(无)", "| 类型:", ip_kind(local_ip4))
    print("IP 归类 1.2.3.4:", ip_kind("1.2.3.4"), "| 192.168.1.4:", ip_kind("192.168.1.4"),
          "| 100.64.1.1:", ip_kind("100.64.1.1"), "| 127.0.0.1:", ip_kind("127.0.0.1"))
    print("== 自检完成 ==")


def main():
    ap = argparse.ArgumentParser(description="n2n 房间助手")
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
