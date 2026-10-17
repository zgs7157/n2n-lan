# -*- coding: utf-8 -*-
"""
udp6_client_forward.py - n2n-lan IPv4 -> IPv6 UDP forwarder (客户端侧)
作用：监听本机 127.0.0.1:7654（IPv4 UDP），把 edge 发来的 n2n 数据包经 IPv6
     转发到服务器（开房电脑）的公网 IPv6 地址的 7654 端口，并反向转发回包。
用途：绕开"路由器端口转发做不通"的问题 —— edge 只认 IPv4 的 supernode 地址，
     所以让 edge 连本机 127.0.0.1，本转发器负责 IPv6 出口。

运行：python udp6_client_forward.py <服务器IPv6地址> [端口]
     例：python udp6_client_forward.py 2409:abcd:1234:…::xxxx
依赖：仅 Python 标准库。
"""
import socket
import sys
import threading
import time

LISTEN_ADDR = ("127.0.0.1", 7654)     # 本机监听（edge 填 127.0.0.1:7654）
SERVER_PORT = 7654                    # 服务器 supernode 端口
IDLE_TIMEOUT = 300


def log(msg):
    """无窗口模式下 stdout 可能为 None，统一安全输出。"""
    try:
        print(msg, flush=True)
    except Exception:
        pass


class ClientForwarder:
    def __init__(self, server_ipv6):
        self.v4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.v4.bind(LISTEN_ADDR)
        self.server6 = (server_ipv6, SERVER_PORT)
        self.clients = {}    # v4 来源地址 -> [IPv6 socket(已 connect 服务器), 最后活动时间]
        self.lock = threading.Lock()

    def recv_from_v4(self):
        """接收 edge(127.0.0.1) 的包 -> 经 IPv6 发给服务器 supernode。"""
        while True:
            try:
                data, addr = self.v4.recvfrom(65535)
            except OSError:
                time.sleep(0.1)
                continue
            now = time.time()
            with self.lock:
                ent = self.clients.get(addr)
                if ent is None:
                    try:
                        s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
                        s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                        s6.connect(self.server6)   # connect 后 send/recv 只针对服务器
                        self.clients[addr] = [s6, now]
                    except OSError as e:
                        log("新建 IPv6 socket 失败: %s" % e)
                        continue
                else:
                    ent[1] = now
                    s6 = ent[0]
            try:
                s6.send(data)
            except OSError:
                pass

    def relay_back(self):
        """接收服务器经 IPv6 的回包 -> 转发回本机 edge；清理空闲连接。"""
        while True:
            with self.lock:
                items = list(self.clients.items())
            for addr, (s6, _ts) in items:
                try:
                    s6.settimeout(0.05)
                    while True:
                        data = s6.recv(65535)
                        self.v4.sendto(data, addr)
                except socket.timeout:
                    pass
                except OSError:
                    with self.lock:
                        try:
                            s6.close()
                            self.clients.pop(addr, None)
                        except OSError:
                            pass
            now = time.time()
            with self.lock:
                for addr, (s6, ts) in list(self.clients.items()):
                    if now - ts > IDLE_TIMEOUT:
                        try:
                            s6.close()
                        except OSError:
                            pass
                        del self.clients[addr]
            time.sleep(0.02)


def main():
    if len(sys.argv) < 2:
        log("用法: python udp6_client_forward.py <服务器IPv6地址> [本地监听端口] [服务器端口]")
        sys.exit(1)
    server_ipv6 = sys.argv[1]
    listen_port = int(sys.argv[2]) if len(sys.argv) >= 3 else 7654
    server_port = int(sys.argv[3]) if len(sys.argv) >= 4 else 7654
    global LISTEN_ADDR, SERVER_PORT
    LISTEN_ADDR = ("127.0.0.1", listen_port)
    SERVER_PORT = server_port
    f = ClientForwarder(server_ipv6)
    log("udp6_client_forward: 监听 127.0.0.1:%d -> [%s]:%d 已启动" % (listen_port, server_ipv6, server_port))
    threading.Thread(target=f.relay_back, daemon=True).start()
    f.recv_from_v4()


if __name__ == "__main__":
    main()
