# -*- coding: utf-8 -*-
"""
udp6_forward.py - n2n-lan IPv6 -> IPv4 UDP forwarder
作用：监听本机 IPv6 UDP 7654 端口，把来自外网（IPv6）的 n2n 数据包转发给
     本机正在监听的 supernode（IPv4 127.0.0.1:7654），并把 supernode 的
     回包转发回对应的 IPv6 客户端。
用途：绕开"路由器端口转发做不通"的问题 —— 电脑有公网 IPv6，
     朋友客户端填 [电脑IPv6]:7654 即可直连本机 supernode。

运行：python udp6_forward.py          （或打包成 exe 后台运行）
依赖：仅 Python 标准库。
"""
import socket
import threading
import time

LISTEN_ADDR = ("::", 7654)      # 监听 IPv6 全部地址的 7654（V6ONLY，不与 supernode 的 IPv4 冲突）
TARGET = ("127.0.0.1", 7654)    # 本机 supernode 的 IPv4 地址与端口
IDLE_TIMEOUT = 300              # 客户端空闲 300 秒后释放对应 socket


class Forwarder:
    def __init__(self):
        self.s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        self.s6.bind(LISTEN_ADDR)
        self.clients = {}        # v6 客户端地址 -> [对应 IPv4 socket, 最后活动时间]
        self.lock = threading.Lock()

    def recv_from_v6(self):
        """接收来自 IPv6 客户端的包并转发给 supernode（每个客户端一个独立本地 socket，保证回包可对应）。"""
        while True:
            try:
                data, addr = self.s6.recvfrom(65535)
            except OSError:
                time.sleep(0.1)
                continue
            now = time.time()
            with self.lock:
                ent = self.clients.get(addr)
                if ent is None:
                    try:
                        t4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        t4.bind(("127.0.0.1", 0))   # 随机本地端口，supernode 回包会回到它
                        self.clients[addr] = [t4, now]
                    except OSError:
                        continue
                else:
                    ent[1] = now
                    t4 = ent[0]
            try:
                t4.sendto(data, TARGET)
            except OSError:
                pass

    def relay_back(self):
        """把 supernode 的回包转发回对应的 IPv6 客户端，并清理空闲连接。"""
        while True:
            with self.lock:
                items = list(self.clients.items())
            for addr, (t4, _ts) in items:
                try:
                    t4.settimeout(0.05)
                    while True:
                        data, _ = t4.recvfrom(65535)
                        self.s6.sendto(data, addr)
                except socket.timeout:
                    pass
                except OSError:
                    with self.lock:
                        try:
                            t4.close()
                            self.clients.pop(addr, None)
                        except OSError:
                            pass
            now = time.time()
            with self.lock:
                for addr, (t4, ts) in list(self.clients.items()):
                    if now - ts > IDLE_TIMEOUT:
                        try:
                            t4.close()
                        except OSError:
                            pass
                        del self.clients[addr]
            time.sleep(0.02)


def main():
    f = Forwarder()
    print("udp6_forward: 监听 [::]:7654 -> 127.0.0.1:7654 已启动", flush=True)
    threading.Thread(target=f.relay_back, daemon=True).start()
    f.recv_from_v6()


if __name__ == "__main__":
    main()
