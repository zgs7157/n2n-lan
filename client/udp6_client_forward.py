# -*- coding: utf-8 -*-
"""
udp6_client_forward.py - n2n-lan IPv4 <-> IPv6 UDP 转发器（双向两种模式）

客户端模式（默认）：
    监听本机 127.0.0.1:<本地端口>，把 edge 发来的 n2n 数据包经 IPv6 转发到
    服务器（开房电脑）的公网 IPv6 地址，并反向转发回包。
    用途：edge 只认 IPv4 的 supernode 地址，本转发器负责 IPv6 出口，
          绕开"路由器端口转发做不通"。

    运行：python udp6_client_forward.py <服务器IPv6地址> [本地监听端口] [服务器端口]
          例：python udp6_client_forward.py 2409:abcd:1234:…::xxxx

服务端模式（--server）：
    监听 [::]:<监听端口>，把公网 IPv6 进来的 n2n 数据包转给本机
    127.0.0.1:<supernode 端口>，并反向转发回包。
    用途：房主**只有公网 IPv6、没有公网 IPv4** 时的兜底 —— supernode 本身
          只监听 IPv4，由本转发器对 IPv6 世界开门。

    运行：python udp6_client_forward.py --server [监听端口] [本地supernode端口]

依赖：仅 Python 标准库。
"""
import select
import socket
import sys
import threading
import time

IDLE_TIMEOUT = 300
LOG_PATH = None


def log(msg):
    """无窗口模式下 stdout 可能为 None，统一安全输出。"""
    try:
        print(msg, flush=True)
    except Exception:
        pass


class ClientForwarder:
    """127.0.0.1:<本地端口> -> [服务器IPv6]:<服务器端口>，双向。"""

    def __init__(self, server_ipv6, listen_port=7654, server_port=7654):
        self.listen_addr = ("127.0.0.1", listen_port)
        self.v4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.v4.bind(self.listen_addr)
        self.server6 = (server_ipv6, server_port)
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


class ServerForwarder:
    """[::]:<监听端口> -> 127.0.0.1:<supernode端口>，双向。

    每个 IPv6 客户端一个独立的 IPv4 socket（connect 到本机 supernode），
    这样 supernode 看到的来源端口各不相同，回包也能一一对应。
    """

    def __init__(self, listen_port=7654, target_port=7654):
        self.listen_addr = ("::", listen_port)
        self.s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            self.s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        self.s6.bind(self.listen_addr)
        self.target = ("127.0.0.1", target_port)
        self.clients = {}    # (ipv6 addr, port) -> [v4 socket(已 connect 本机 supernode), 最后活动时间]
        self.lock = threading.Lock()
        self.total = 0

    def _make_v4(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(self.target)
        return s

    def recv_from_v6(self):
        """接收公网 IPv6 的包 -> 转给本机 supernode。"""
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
                        v4 = self._make_v4()
                        self.clients[addr] = [v4, now]
                        self.total += 1
                        log("新客户端 %s:%d（在线 %d）" % (addr[0], addr[1], len(self.clients)))
                    except OSError as e:
                        log("建立本地 socket 失败: %s" % e)
                        continue
                else:
                    ent[1] = now
                    v4 = ent[0]
            try:
                v4.send(data)
            except OSError:
                pass

    def relay_back(self):
        """接收本机 supernode 的回包 -> 经 IPv6 转发回客户端；清理空闲连接。"""
        while True:
            with self.lock:
                items = list(self.clients.items())
            for addr, (v4, ts) in items:
                try:
                    v4.settimeout(0.05)
                    while True:
                        data = v4.recv(65535)
                        try:
                            self.s6.sendto(data, addr)
                        except OSError:
                            pass
                except socket.timeout:
                    pass
                except OSError:
                    with self.lock:
                        try:
                            v4.close()
                            self.clients.pop(addr, None)
                        except OSError:
                            pass
                else:
                    with self.lock:
                        ent = self.clients.get(addr)
                        if ent:
                            ent[1] = time.time()
            now = time.time()
            with self.lock:
                for addr, (v4, ts) in list(self.clients.items()):
                    if now - ts > IDLE_TIMEOUT:
                        try:
                            v4.close()
                        except OSError:
                            pass
                        del self.clients[addr]
            time.sleep(0.02)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("--server", "-s", "server"):
        # 服务端模式：监听 IPv6，把包转给本机 supernode
        argv = argv[1:]
        listen_port = int(argv[0]) if len(argv) >= 1 else 7654
        target_port = int(argv[1]) if len(argv) >= 2 else 7654
        try:
            f = ServerForwarder(listen_port, target_port)
        except OSError as e:
            log("IPv6 监听端口 %d 不可用: %s" % (listen_port, e))
            sys.exit(2)
        log("udp6_forward --server: 监听 [::]:%d -> 127.0.0.1:%d 已启动"
            % (listen_port, target_port))
        threading.Thread(target=f.relay_back, daemon=True).start()
        f.recv_from_v6()
        return

    if len(argv) < 1:
        log("用法:")
        log("  客户端: python udp6_client_forward.py <服务器IPv6> [本地监听端口] [服务器端口]")
        log("  服务端: python udp6_client_forward.py --server [监听端口] [本地supernode端口]")
        sys.exit(1)
    server_ipv6 = argv[0]
    listen_port = int(argv[1]) if len(argv) >= 2 else 7654
    server_port = int(argv[2]) if len(argv) >= 3 else 7654
    f = ClientForwarder(server_ipv6, listen_port, server_port)
    log("udp6_client_forward: 监听 127.0.0.1:%d -> [%s]:%d 已启动"
        % (listen_port, server_ipv6, server_port))
    threading.Thread(target=f.relay_back, daemon=True).start()
    f.recv_from_v4()


if __name__ == "__main__":
    main()
