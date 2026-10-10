#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
n2n 官网访问统计服务（自建）
============================
单文件、仅标准库（http.server + sqlite3），Windows / Linux 通用。

功能：
- GET /hit?page=xxx   官网打点（返回 1x1 透明 GIF，不阻塞页面）
- GET /badge.svg      官网 Footer 徽章（动态显示累计访客数）
- GET /admin?key=xxx  后台统计页（今日/累计 PV·UV、近7天、最近记录）

配置：
首次运行在同目录生成 stats_config.json，可修改 admin_key / port，改后重启生效。

启动：
- Windows：双击 start_stats.bat（后台运行）
- Linux：  python3 visit_stats.py  （或 nohup ... &）
"""

import json
import os
import socket
import sqlite3
import time
import urllib.parse
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if getattr(__import__("sys"), "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(__import__("sys").executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONF_PATH = os.path.join(BASE_DIR, "stats_config.json")
DB_PATH = os.path.join(BASE_DIR, "visits.db")

DEFAULT_CONFIG = {"admin_key": "n2n2026", "port": 8088}

# 1x1 透明 GIF（打点响应体）
PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
         b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONF_PATH):
        try:
            with open(CONF_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        except Exception:
            pass
    return cfg


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS visits("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts INTEGER, ip TEXT, page TEXT, ua TEXT)")
    conn.commit()
    return conn


def q_int(q, name, default=0):
    try:
        return int((q.get(name) or [str(default)])[0])
    except Exception:
        return default


class StatsServer(ThreadingHTTPServer):
    """IPv4 + IPv6 双栈监听（IPv6 无 NAT，公网可直接访问）"""
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "n2n-stats"

    def log_message(self, fmt, *args):
        pass  # 静默访问日志，不往控制台刷

    # ---------- 工具 ----------
    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _bad(self, code, text):
        body = text.encode("utf-8")
        self._send(code, "text/plain; charset=utf-8", body)

    # ---------- 打点 ----------
    def _hit(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        page = (q.get("page") or ["home"])[0][:80] or "home"
        ip = self.client_address[0]
        if ip.startswith("::ffff:"):  # IPv4 经双栈进入时去掉映射前缀
            ip = ip[7:]
        ua = self.headers.get("User-Agent", "")[:200]
        try:
            conn = get_db()
            conn.execute("INSERT INTO visits(ts, ip, page, ua) VALUES(?,?,?,?)",
                         (int(time.time()), ip, page, ua))
            conn.commit()
            conn.close()
        except Exception:
            pass
        self._send(200, "image/gif", PIXEL)

    # ---------- 徽章 ----------
    def _badge(self):
        uv = 0
        try:
            conn = get_db()
            uv = conn.execute("SELECT COUNT(DISTINCT ip) FROM visits").fetchone()[0]
            conn.close()
        except Exception:
            pass
        text = "N2N 官网 · 访客 %d" % uv
        width = 130 + 9 * len(str(uv))
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="22">'
            '<rect width="100%%" height="22" rx="11" fill="#161C22"/>'
            '<rect width="100%%" height="22" rx="11" fill="none" stroke="#28313C"/>'
            '<text x="50%%" y="15" text-anchor="middle" font-family="Microsoft YaHei,Arial,sans-serif" '
            'font-size="12" fill="#63C74D">%s</text></svg>'
        ) % (width, _xml_escape(text))
        self._send(200, "image/svg+xml", svg.encode("utf-8"), {"Access-Control-Allow-Origin": "*"})

    # ---------- 后台 ----------
    def _admin(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        key = (q.get("key") or [""])[0]
        cfg = load_config()
        if key != cfg.get("admin_key"):
            body = (
                "<!doctype html><meta charset=utf-8><title>访问统计</title>"
                "<body style='background:#0F1317;color:#E8E6E1;font-family:sans-serif;"
                "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
                "<div style='text-align:center'><h2>需要后台密码</h2>"
                "<p>请在网址后加 ?key=你的后台密码（见 stats_config.json）</p>"
                "<p><code style='color:#D9A03F'>/admin?key=xxx</code></p></div></body>"
            ).encode("utf-8")
            self._send(401, "text/html; charset=utf-8", body)
            return

        now = int(time.time())
        today0 = int(time.mktime(date.today().timetuple()))
        try:
            conn = get_db()
            today_pv = conn.execute(
                "SELECT COUNT(*) FROM visits WHERE ts>=?", (today0,)).fetchone()[0]
            today_uv = conn.execute(
                "SELECT COUNT(DISTINCT ip) FROM visits WHERE ts>=?", (today0,)).fetchone()[0]
            total_pv = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
            total_uv = conn.execute("SELECT COUNT(DISTINCT ip) FROM visits").fetchone()[0]

            rows7 = conn.execute(
                "SELECT date(ts,'unixepoch','localtime') d, COUNT(*), COUNT(DISTINCT ip) "
                "FROM visits WHERE ts>=? GROUP BY d ORDER BY d DESC LIMIT 7",
                (now - 7 * 86400,)).fetchall()
            rows7 = list(reversed(rows7))

            recent = conn.execute(
                "SELECT datetime(ts,'unixepoch','localtime'), ip, page, ua "
                "FROM visits ORDER BY id DESC LIMIT 30").fetchall()
            conn.close()
        except Exception as e:
            self._bad(500, "db error: %s" % e)
            return

        def esc(s):
            return _xml_escape(str(s))

        days_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(d), pv, uv)
            for d, pv, uv in rows7)
        rec_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td title='%s'>%s</td></tr>"
            % (esc(t), esc(ip), esc(page), esc(ua), esc(ua[:40]))
            for t, ip, page, ua in recent) or "<tr><td colspan=4>暂无记录</td></tr>"

        card = ('<div class="card"><b>%s</b><span>%s</span></div>')
        html = (
            "<!doctype html><html lang=zh><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>n2n 官网访问统计</title>"
            "<style>"
            "body{background:#0F1317;color:#E8E6E1;font-family:'Microsoft YaHei',sans-serif;"
            "margin:0;padding:28px 20px 60px}"
            ".wrap{max-width:860px;margin:0 auto}"
            "h1{font-size:22px;margin:0 0 18px}"
            ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}"
            ".card{background:#161C22;border:1px solid #28313C;border-radius:10px;padding:16px}"
            ".card b{display:block;font-size:26px;color:#63C74D}"
            ".card span{font-size:13px;color:#9AA3AD}"
            "h2{font-size:16px;margin:20px 0 10px;color:#9AA3AD}"
            "table{width:100%%;border-collapse:collapse;font-size:13px;background:#161C22;"
            "border:1px solid #28313C;border-radius:10px;overflow:hidden}"
            "th,td{padding:8px 10px;border-bottom:1px solid #28313C;text-align:left}"
            "th{color:#9AA3AD;font-weight:600}"
            "td{font-family:Consolas,monospace;font-size:12.5px;word-break:break-all}"
            "</style><div class=wrap>"
            "<h1>n2n 官网访问统计</h1>"
            "<div class=cards>"
            + card % ("%d" % today_pv, "今日访问") + card % ("%d" % today_uv, "今日访客")
            + card % ("%d" % total_pv, "累计访问") + card % ("%d" % total_uv, "累计访客")
            + "</div>"
            "<h2>最近 7 天</h2>"
            "<table><tr><th>日期</th><th>访问</th><th>访客</th></tr>%s</table>"
            "<h2>最近 30 条访问记录</h2>"
            "<table><tr><th>时间</th><th>IP</th><th>页面</th><th>UA</th></tr>%s</table>"
            "</div></body></html>"
        ) % (days_rows, rec_rows)
        self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))

    # ---------- 路由 ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/hit":
                self._hit()
            elif path == "/badge.svg":
                self._badge()
            elif path == "/admin":
                self._admin()
            elif path == "/":
                self._send(200, "text/html; charset=utf-8",
                           ("<meta charset=utf-8><title>n2n stats</title>"
                            "<body style='background:#0F1317;color:#E8E6E1;font-family:sans-serif;"
                            "padding:40px'><h2>n2n 官网统计服务运行中</h2>"
                            "<p>后台：<code>/admin?key=xxx</code></p>"
                            "<p>打点：<code>/hit?page=home</code></p></body>").encode("utf-8"))
            else:
                self._bad(404, "not found")
        except BrokenPipeError:
            pass


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def main():
    cfg = load_config()
    if not os.path.exists(CONF_PATH):
        try:
            with open(CONF_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    port = int(cfg.get("port", 8088))
    print("== n2n visit stats ==")
    print("config:", CONF_PATH)
    print("db:", DB_PATH)
    print("admin key:", cfg.get("admin_key"))
    print("listening on port", port)
    StatsServer(("::", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
