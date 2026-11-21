#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
房间在线成员 + 局域网房间发现（免费版 / Pro 共用，纯标准库）
=============================================================

两件独立的事，都走 UDP 广播，不需要任何服务器：

1. 成员在线表（免费版 + Pro 都有）
   进房后每 3 秒在房间虚拟网段 `10.x.0.255:23334` 上广播一条自己的 presence：
   虚拟 IP、显示名、是否房主。所有人都监听同一端口，各自维护一张成员表，
   于是界面上能实时看到「房间里有几个人、各自虚拟 IP、谁是房主」。

2. 房间公告 + 附近房间（Pro 用）
   房主每 4 秒在物理局域网 `255.255.255.255:23335`（外加本网段定向广播）发一条
   房间公告：房间码、网段、房主虚拟 IP、邀请用的 supernode、当前人数。
   Pro 版监听这个端口，就能列出同一局域网里别人开的房间，点一下直接加入。

协议版本 2；报文是单行 JSON，忽略任何不认识的字段。
"""

import json
import socket
import threading
import time

PRESENCE_PORT = 23334
DISCOVER_PORT = 23335
PROTO_VERSION = 2
PRESENCE_INTERVAL = 3.0
PRESENCE_TTL = 12.0
ROOM_INTERVAL = 4.0
ROOM_TTL = 20.0


def local_ipv4():
    """本机主网卡 IPv4（UDP connect 探测，不真正发包）"""
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


def local_broadcast():
    """按主网卡地址推算本网段定向广播地址（/24 假设，够用）"""
    ip = local_ipv4()
    parts = ip.split(".")
    if len(parts) == 4 and parts[0] not in ("127", "0"):
        return "%s.%s.%s.255" % (parts[0], parts[1], parts[2])
    return ""


class PresenceService(threading.Thread):
    """在线成员表 + 房主房间公告。

    用法：App 连上后调用 set_room(...)，离开房间调用 clear_room()，
    界面定时读 snapshot() 刷新成员列表。
    """

    def __init__(self, name_getter=None):
        super().__init__(daemon=True)
        self._name_getter = name_getter or (lambda: "")
        self._lock = threading.Lock()
        self._members = {}
        self._room = {}
        self._stop = threading.Event()
        self._sock = None
        self._bcast = None
        self._next_presence = 0.0
        self._next_room = 0.0
        self.failed = False

    # ---------------- 对外 ----------------
    def set_room(self, community="", code="", subnet="", my_ip="",
                 is_host=False, name="", server="", version=""):
        with self._lock:
            self._room = {
                "community": community or "",
                "code": code or "",
                "subnet": subnet or "",
                "my_ip": my_ip or "",
                "is_host": bool(is_host),
                "name": name or "",
                "server": server or "",
                "version": version or "",
            }
            if my_ip:
                self._members[my_ip] = {
                    "ip": my_ip,
                    "name": name or "",
                    "role": "host" if is_host else "guest",
                    "code": code or "",
                    "ts": time.time(),
                    "self": True,
                }
        self._next_presence = 0.0
        self._next_room = 0.0

    def set_my_ip(self, my_ip):
        with self._lock:
            old = self._room.get("my_ip") or ""
            self._room["my_ip"] = my_ip or ""
            if old and old in self._members and old != my_ip:
                self._members.pop(old, None)
            if my_ip:
                self._members[my_ip] = {
                    "ip": my_ip,
                    "name": self._room.get("name") or "",
                    "role": "host" if self._room.get("is_host") else "guest",
                    "code": self._room.get("code") or "",
                    "ts": time.time(),
                    "self": True,
                }

    def clear_room(self):
        with self._lock:
            self._room = {}
            self._members = {}

    def snapshot(self):
        """成员列表：房主在前，其余按虚拟 IP 数值排序。"""
        now = time.time()
        with self._lock:
            rows = []
            for ip, m in self._members.items():
                if now - float(m.get("ts") or 0) > PRESENCE_TTL:
                    continue
                rows.append({
                    "ip": ip,
                    "name": m.get("name") or "",
                    "role": m.get("role") or "guest",
                    "age": round(now - float(m.get("ts") or now), 1),
                    "self": bool(m.get("self")),
                })
        def key(r):
            host_first = 0 if r["role"] == "host" else 1
            try:
                num = tuple(int(x) for x in r["ip"].split("."))
            except Exception:
                num = (999, 999, 999, 999)
            return (host_first, num)
        return sorted(rows, key=key)

    def count(self):
        return len(self.snapshot())

    def host_ip(self):
        for r in self.snapshot():
            if r["role"] == "host":
                return r["ip"]
        return ""

    # ---------------- 线程 ----------------  -
    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", PRESENCE_PORT))
            sock.settimeout(0.4)
            self._sock = sock
        except Exception:
            self.failed = True
            return
        try:
            bc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            bc.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._bcast = bc
        except Exception:
            self._bcast = None

        while not self._stop.is_set():
            now = time.time()
            try:
                data, _addr = self._sock.recvfrom(2048)
                self._handle(data, now)
            except socket.timeout:
                pass
            except OSError:
                break
            except Exception:
                pass

            if now >= self._next_presence:
                self._next_presence = now + PRESENCE_INTERVAL
                self._send_presence()
            if now >= self._next_room:
                self._next_room = now + ROOM_INTERVAL
                self._send_room()

    def _handle(self, data, now):
        try:
            obj = json.loads(data.decode("utf-8", "replace"))
        except Exception:
            return
        if obj.get("v") != PROTO_VERSION:
            return
        with self._lock:
            room = dict(self._room)
        if not room.get("community"):
            return
        if obj.get("c") != room.get("community"):
            return
        ip = (obj.get("ip") or "").strip()
        if not ip or ip == room.get("my_ip"):
            return
        with self._lock:
            self._members[ip] = {
                "ip": ip,
                "name": (obj.get("n") or "")[:24],
                "role": "host" if obj.get("h") else "guest",
                "code": (obj.get("code") or ""),
                "ts": now,
                "self": False,
            }

    def _send_presence(self):
        with self._lock:
            room = dict(self._room)
            name = self._name_getter() or room.get("name") or ""
            if name:
                self._room["name"] = name
            if room.get("my_ip"):
                m = self._members.get(room["my_ip"])
                if m is not None:
                    m["name"] = name
                    m["ts"] = time.time()
        if not room.get("my_ip") or not room.get("community") or self._bcast is None:
            return
        target = self._subnet_broadcast(room.get("subnet") or room.get("my_ip"))
        if not target:
            return
        msg = json.dumps({
            "v": PROTO_VERSION, "t": "p", "c": room.get("community"),
            "code": room.get("code"), "ip": room.get("my_ip"),
            "n": name[:24], "h": 1 if room.get("is_host") else 0,
        }, ensure_ascii=False).encode("utf-8")
        try:
            self._bcast.sendto(msg, (target, PRESENCE_PORT))
        except Exception:
            pass

    def _subnet_broadcast(self, subnet_or_ip):
        parts = (subnet_or_ip or "").split(".")
        if len(parts) == 3:
            return "%s.255" % subnet_or_ip
        if len(parts) == 4:
            return "%s.%s.%s.255" % (parts[0], parts[1], parts[2])
        return ""

    def _send_room(self):
        with self._lock:
            room = dict(self._room)
        if not room.get("is_host") or not room.get("code") or self._bcast is None:
            return
        rows = self.snapshot()
        msg = json.dumps({
            "v": PROTO_VERSION, "t": "room", "code": room.get("code"),
            "subnet": room.get("subnet"), "host": room.get("my_ip"),
            "server": room.get("server"), "n": (room.get("name") or "")[:24],
            "cnt": len(rows), "ver": room.get("version") or "",
        }, ensure_ascii=False).encode("utf-8")
        targets = ["255.255.255.255"]
        lb = local_broadcast()
        if lb:
            targets.append(lb)
        for t in targets:
            try:
                self._bcast.sendto(msg, (t, DISCOVER_PORT))
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        for s in (self._sock, self._bcast):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        self._sock = None
        self._bcast = None


class RoomDiscovery(threading.Thread):
    """监听局域网里的房间公告，得到「附近房间」列表（Pro 版用）。"""

    def __init__(self):
        super().__init__(daemon=True)
        self._lock = threading.Lock()
        self._rooms = {}
        self._stop = threading.Event()
        self._sock = None
        self.failed = False
        self.on_update = None

    def snapshot(self):
        now = time.time()
        with self._lock:
            rows = []
            for code, r in self._rooms.items():
                if now - float(r.get("ts") or 0) > ROOM_TTL:
                    continue
                item = dict(r)
                item["age"] = round(now - float(r.get("ts") or now), 1)
                rows.append(item)
        return sorted(rows, key=lambda x: -float(x.get("ts") or 0))

    def count(self):
        return len(self.snapshot())

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVER_PORT))
            sock.settimeout(0.5)
            self._sock = sock
        except Exception:
            self.failed = True
            return
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                continue
            try:
                obj = json.loads(data.decode("utf-8", "replace"))
            except Exception:
                continue
            if obj.get("v") != PROTO_VERSION or obj.get("t") != "room":
                continue
            code = (obj.get("code") or "").strip()
            if len(code) < 6:
                continue
            with self._lock:
                self._rooms[code] = {
                    "code": code,
                    "subnet": obj.get("subnet") or "",
                    "host": obj.get("host") or "",
                    "server": obj.get("server") or "",
                    "name": (obj.get("n") or "")[:24],
                    "count": obj.get("cnt") or 0,
                    "ver": obj.get("ver") or "",
                    "src": addr[0] if addr else "",
                    "ts": time.time(),
                }
            if self.on_update:
                try:
                    self.on_update()
                except Exception:
                    pass

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
