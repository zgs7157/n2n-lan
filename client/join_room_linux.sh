#!/usr/bin/env bash
# =============================================================================
# n2n-lan 房间加入脚本（Linux 版）
# =============================================================================
# 与 Windows / macOS 客户端同一套派生规则：8 位房间码 → community / 网段 / 密钥
# 由 sha256("n2n-lan|"+房间码) 推导，所以同一个房间码在任何机器上算出的参数都一样。
#
# 用法:
#   sudo bash join_room_linux.sh <房间码或邀请码> [服务器地址] [旧格式密码]
#
# 示例:
#   # 新格式（推荐）：邀请码自带服务器
#   sudo bash join_room_linux.sh 'J7N3-WD8Y@39.162.81.144:7654'
#   # 新格式：房间码和服务器分开给
#   sudo bash join_room_linux.sh J7N3-WD8Y 39.162.81.144:7654
#   # 房主走 IPv6 兜底时，服务器是 IPv6 地址（脚本会自动起本地转发器）
#   sudo bash join_room_linux.sh J7N3-WD8Y 2409:8a48:9d4:5ff0:add1:1ad8:fac2:3ba0
#   # 旧格式长房间码（仍兼容，第四个参数是老的房间密码，可省略）
#   sudo bash join_room_linux.sh 'mc-pixel-1234@10.88.0#Ab3CdEfGhJ' 39.162.81.144:7654
#
# 前置条件:
#   - python3（脚本用它做密钥派生和虚拟 IP 领号；几乎每个发行版自带）
#   - n2n v3 的 edge 命令（v2 协议不兼容）：apt install n2n 或从
#     https://github.com/lucktu/n2n 下载 Linux x64 版放进 PATH
#   - 需要 root（创建虚拟网卡）
# =============================================================================
set -u

IN="${1:-}"
SRV_ARG="${2:-}"
PWD_ARG="${3:-}"
SRV_ENV="${N2N_SUPERNODE:-}"
SELF_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

usage() {
    cat <<'EOF'
用法: sudo bash join_room_linux.sh <房间码或邀请码> [服务器地址] [旧格式密码]

  新格式: sudo bash join_room_linux.sh 'J7N3-WD8Y@39.162.81.144:7654'
  旧格式: sudo bash join_room_linux.sh 'mc-pixel-1234@10.88.0#Ab3CdEfGhJ' 39.162.81.144:7654
EOF
}

if [ -z "$IN" ]; then
    usage
    exit 1
fi
if [ "$(id -u)" != "0" ]; then
    echo "请用 sudo 运行（需要创建虚拟网卡）："
    echo "  sudo bash $0 $*"
    exit 1
fi

# ---------- python3 ----------
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
    echo "未找到 python3。密钥派生和虚拟 IP 领号需要它："
    echo "  Debian/Ubuntu: sudo apt install python3"
    echo "  Fedora:        sudo dnf install python3"
    echo "  Arch:          sudo pacman -S python"
    exit 1
fi

# ---------- 解析房间码并派生参数（与 Windows 客户端同一套算法） ----------
DERIVE=$("$PY" - "$IN" "$SRV_ARG" "$PWD_ARG" "$SRV_ENV" <<'PYEOF'
import hashlib
import re
import shlex
import socket
import sys

IN, SRV_ARG, PWD_ARG, SRV_ENV = (sys.argv + ["", "", "", ""])[1:5]
ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
JUNK = re.compile("[^%s]" % ALPHA)


def clean_code(text):
    return JUNK.sub("", (text or "").upper())


def die(msg):
    print("ERR=%s" % shlex.quote(msg))
    sys.exit(0)


def machine_id():
    try:
        with open("/etc/machine-id") as f:
            mid = f.read().strip()
        if mid:
            return mid
    except Exception:
        pass
    try:
        return socket.gethostname() or "unknown-host"
    except Exception:
        return "unknown-host"


def ipv6_like(host):
    return host.count(":") >= 2 and not host.startswith("[")


code = ""
legacy = False
server_raw = SRV_ARG.strip() or SRV_ENV.strip()

if "#" in IN:
    # 旧格式：community@10.x.0#密钥
    legacy = True
    left, _, key = IN.partition("#")
    if "@" not in left:
        die("旧格式房间码应为 community@10.x.0#密钥")
    community, subnet = left.split("@", 1)
    if not community or not subnet or not key:
        die("旧格式房间码不完整")
    if PWD_ARG.strip():
        key = hashlib.sha256(("%s:%s" % (key, PWD_ARG.strip())).encode("utf-8")).hexdigest()[:16]
else:
    head, _, tail = IN.partition("@")
    code = clean_code(head)
    if len(code) != 8:
        die("房间码应是 8 位字母数字（例如 J7N3-WD8Y）；老格式请用 community@网段#密钥")
    if tail and not server_raw:
        server_raw = tail.strip()
    h = hashlib.sha256(("n2n-lan|" + code).encode("utf-8")).hexdigest()
    community = "room-%s-%s" % (code[:4].lower(), code[4:].lower())
    subnet = "10.%d.0" % (2 + (int(h[2:4], 16) % 250))
    key = h[:16]

if not server_raw:
    die("没有服务器地址：请用完整邀请码（房间码@IP:端口），或第二个参数给服务器地址")

server_raw = server_raw.strip()
if server_raw.startswith("[") and "]" in server_raw:
    host, _, rest = server_raw[1:].partition("]")
    kind, port = "v6", 7654
    if rest.startswith(":"):
        try:
            port = int(rest[1:])
        except ValueError:
            die("服务器端口不合法：%s" % server_raw)
elif ipv6_like(server_raw):
    host, port, kind = server_raw.strip("[]"), 7654, "v6"
else:
    if server_raw.count(":") == 1:
        host, port_s = server_raw.split(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            die("服务器端口不合法：%s" % server_raw)
    else:
        host, port, kind = server_raw, 7654, "v4"
    kind = "v4"

# 候选虚拟 IP：与 Windows 端同一算法，按机器指纹分散，避免所有人挤在 .2
mid = machine_id()
mh = hashlib.sha256(("%s|%s" % (subnet, mid)).encode("utf-8")).hexdigest()
myip = "%s.%d" % (subnet, 2 + int(mh[6:10], 16) % 252)

print("COMMUNITY=%s" % shlex.quote(community))
print("SUBNET=%s" % shlex.quote(subnet))
print("KEY=%s" % shlex.quote(key))
print("CODE=%s" % shlex.quote(code))
print("MID=%s" % shlex.quote(mid))
print("MYIP=%s" % shlex.quote(myip))
print("SRV_HOST=%s" % shlex.quote(host))
print("SRV_PORT=%d" % port)
print("SRV_KIND=%s" % kind)
print("LEGACY=%d" % (1 if legacy else 0))
PYEOF
)

eval "$DERIVE"
if [ -n "${ERR:-}" ]; then
    echo ">> $ERR"
    exit 1
fi

echo ">> 房间        : ${CODE:+$CODE（新格式）}${LEGACY:+旧格式}"
echo ">> community   : $COMMUNITY"
echo ">> 虚拟网段    : $SUBNET.0/24"
echo ">> 候选虚拟 IP : $MYIP"

# ---------- 检查 edge ----------
EDGE_BIN=""
for c in edge /usr/local/bin/edge /usr/sbin/edge "$SELF_DIR/bin/edge"; do
    if [ -x "$c" ] 2>/dev/null && [ "$c" != "edge" ]; then EDGE_BIN="$c"; break; fi
    if command -v "$c" >/dev/null 2>&1; then EDGE_BIN="$(command -v "$c")"; break; fi
done
if [ -z "$EDGE_BIN" ]; then
    echo "未找到 edge 命令。请先安装 n2n v3："
    echo "  1) sudo apt install n2n（Debian/Ubuntu，注意版本需为 v3）"
    echo "  2) 或从 https://github.com/lucktu/n2n 下载 Linux x64 版放进 PATH"
    exit 1
fi
echo ">> edge: $EDGE_BIN"

# ---------- 服务器是 IPv6 时，起本地转发器（edge 只认 IPv4） ----------
FW_PID=""
LISTEN_ADDR="${SRV_HOST}:${SRV_PORT}"
if [ "$SRV_KIND" = "v6" ]; then
    FW_PY="$SELF_DIR/udp6_client_forward.py"
    if [ ! -f "$FW_PY" ]; then
        echo "服务器是 IPv6 地址，需要同目录下的 udp6_client_forward.py 做转发，但没找到：$FW_PY"
        echo "请从绿色版整包里运行本脚本（包里自带该文件）。"
        exit 1
    fi
    "$PY" "$FW_PY" "$SRV_HOST" 7655 "$SRV_PORT" > /tmp/n2n_fw_linux.log 2>&1 &
    FW_PID=$!
    sleep 3
    if ! kill -0 "$FW_PID" 2>/dev/null; then
        echo ">> IPv6 转发器启动失败："
        tail -20 /tmp/n2n_fw_linux.log 2>/dev/null
        exit 1
    fi
    LISTEN_ADDR="127.0.0.1:7655"
    echo ">> IPv6 转发器   : [${SRV_HOST}]:${SRV_PORT} → 127.0.0.1:7655（pid $FW_PID）"
fi

# ---------- 启动 edge ----------
start_edge() {
    ip link del n2n0 2>/dev/null || true
    "$EDGE_BIN" -c "$COMMUNITY" -k "$KEY" -a "${1}/24" \
        -l "$LISTEN_ADDR" -E -x 1 -M 1290 -d n2n0 \
        > /tmp/n2n_edge_linux.log 2>&1 &
    EDGE_PID=$!
}

start_edge "$MYIP"
sleep 3
if ! kill -0 "$EDGE_PID" 2>/dev/null; then
    echo ">> edge 启动失败，日志如下："
    tail -30 /tmp/n2n_edge_linux.log
    exit 1
fi

# ---------- 向房主领号（房主 1.2.0+ 才有这个服务，失败就用候选 IP） ----------
if [ -n "$CODE" ]; then
    GOT_IP=$("$PY" - "$MYIP" "$SUBNET" "$CODE" "$MID" 4 <<'PYEOF'
import socket
import sys

MYIP, SUBNET, CODE, MID = sys.argv[1:5]
TAG = "N2NLANIP"
PORT = 23336
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.bind((MYIP, 0))
except OSError:
    sys.exit(0)
s.settimeout(1.2)
ip = ""
for _ in range(18):
    try:
        s.sendto(("%s|REQ|%s|%s" % (TAG, CODE, MID)).encode("utf-8"), (SUBNET + ".1", PORT))
        data, _addr = s.recvfrom(512)
        parts = data.decode("utf-8", "ignore").split("|")
        if len(parts) == 4 and parts[0] == TAG and parts[1] == "OK" and parts[2] == CODE:
            ip = parts[3].strip()
            break
    except (socket.timeout, OSError):
        continue
s.close()
if ip:
    print(ip)
PYEOF
)
    if [ -n "${GOT_IP:-}" ]; then
        echo ">> 房主分配虚拟 IP : $GOT_IP"
        if [ "$GOT_IP" != "$MYIP" ]; then
            echo ">> 与候选 IP 不同，按房主分配重启 edge"
            kill "$EDGE_PID" 2>/dev/null
            sleep 1
            MYIP="$GOT_IP"
            start_edge "$MYIP"
            sleep 3
            if ! kill -0 "$EDGE_PID" 2>/dev/null; then
                echo ">> 用新 IP 重启 edge 失败，日志如下："
                tail -30 /tmp/n2n_edge_linux.log
                exit 1
            fi
        fi
    else
        echo ">> 没领到房主的号（房主可能不是 1.2.0，或不在同一虚拟网段可答话），继续用候选 IP $MYIP"
    fi
fi

# ---------- 结果 ----------
echo "=============================================="
echo "已加入房间 : $COMMUNITY"
echo "虚拟 IP    : ${MYIP}/24"
echo "supernode  : $LISTEN_ADDR"
echo "edge PID   : $EDGE_PID"
[ -n "$FW_PID" ] && echo "转发器 PID : $FW_PID"
echo ""
echo "MC 联机：房主开好世界并『对局域网开放』后，"
echo "你打开 MC 多人游戏 → 直接连接 → 填 ${SUBNET}.1:25565"
echo ""
echo "退出房间："
if [ -n "$FW_PID" ]; then
    echo "  sudo kill $EDGE_PID $FW_PID && sudo ip link del n2n0"
else
    echo "  sudo kill $EDGE_PID && sudo ip link del n2n0"
fi
echo "新版脚本：https://github.com/zgs7157/n2n-lan/releases/latest"
echo "=============================================="
