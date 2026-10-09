#!/usr/bin/env bash
#
# n2n 房间加入脚本（Linux 版）
# 与 Windows 客户端同一套房间协议：房间码 = community@网段#密钥，密码参与密钥派生。
#
# 用法:
#   sudo bash join_room_linux.sh <房间码> [房间密码] <服务器IP:端口>
#
# 示例:
#   sudo bash join_room_linux.sh 'mc-pixel-1234@10.88.0#Ab3CdEfGhJ' 482913 39.162.81.68:7654
#   sudo bash join_room_linux.sh 'mc-pixel-1234@10.88.0#Ab3CdEfGhJ' 39.162.81.68:7654   # 免密房
#
# 前置条件:
#   - n2n v3 的 edge 命令（与服务器同为 v3 协议，2.x 不兼容）
#     Debian/Ubuntu 可用官方源: 见项目 README「Linux 客户端」一节
#     或从 lucktu 预编译包获取 Linux x64 版: https://github.com/lucktu/n2n
#   - 需要 root（创建虚拟网卡）
#
set -u

CODE="$1"
PWD_ARG="${2:-}"
SN_ARG="${3:-${N2N_SUPERNODE:-}}"

if [ "$(id -u)" != "0" ]; then
    echo "请用 sudo 运行：sudo bash $0 <房间码> [密码] <服务器IP:端口>"
    exit 1
fi

if [ -z "$CODE" ] || [ -z "$SN_ARG" ]; then
    echo "用法: sudo bash $0 <房间码> [房间密码] <服务器IP:端口>"
    echo "示例: sudo bash $0 'mc-pixel-1234@10.88.0#Ab3CdEfGhJ' 482913 39.162.81.68:7654"
    echo "       sudo bash $0 'mc-pixel-1234@10.88.0#Ab3CdEfGhJ' 39.162.81.68:7654   # 免密房"
    exit 1
fi

# ---------- 解析房间码 ----------
COMMUNITY=$(printf '%s' "$CODE" | cut -d'@' -f1)
REST=$(printf '%s' "$CODE" | cut -d'@' -f2-)
SUBNET=$(printf '%s' "$REST" | cut -d'#' -f1)
KEY=$(printf '%s' "$REST" | cut -d'#' -f2)

if [ -z "$COMMUNITY" ] || [ -z "$SUBNET" ] || [ -z "$KEY" ]; then
    echo "房间码格式错误，应为：community@10.x.0#密钥"
    exit 1
fi

# ---------- 密码派生（与 Windows 客户端一致：sha256(密钥:密码) 前16位） ----------
if [ -n "$PWD_ARG" ]; then
    EFF_KEY=$(printf '%s:%s' "$KEY" "$PWD_ARG" | sha256sum | cut -c1-16)
    echo ">> 使用房间密码派生密钥"
else
    EFF_KEY="$KEY"
    echo ">> 免密加入（房间码即全部凭证）"
fi

# ---------- 检查 edge ----------
EDGE_BIN=""
for c in edge /usr/local/bin/edge /usr/sbin/edge; do
    if command -v "$c" >/dev/null 2>&1; then EDGE_BIN=$(command -v "$c"); break; fi
done
if [ -z "$EDGE_BIN" ]; then
    echo "未找到 edge 命令。请先安装 n2n v3："
    echo "  1) 从 https://github.com/lucktu/n2n 下载 Linux x64 版并放入 PATH"
    echo "  2) 或按项目 README「Linux 客户端」用 apt/源码安装"
    exit 1
fi
echo ">> edge: $EDGE_BIN"

# ---------- 清理旧 n2n0 网卡 ----------
ip link del n2n0 2>/dev/null || true

# ---------- 启动 edge ----------
# 参数与 Windows 客户端对齐：-E 接受组播(MC 局域网发现) -x 1 游戏识别 -M 1290 MTU
"$EDGE_BIN" -c "$COMMUNITY" -k "$EFF_KEY" -a "${SUBNET}.2/24" \
    -l "$SN_ARG" -E -x 1 -M 1290 -d n2n0 \
    > /tmp/n2n_edge_linux.log 2>&1 &
EDGE_PID=$!

sleep 3
if ! kill -0 "$EDGE_PID" 2>/dev/null; then
    echo ">> edge 启动失败，日志如下："
    tail -30 /tmp/n2n_edge_linux.log
    exit 1
fi

# ---------- 结果 ----------
echo "=============================================="
echo "已加入房间: $COMMUNITY"
echo "虚拟 IP  : ${SUBNET}.2/24 （与房主同一网段）"
echo "supernode: $SN_ARG"
echo "edge PID : $EDGE_PID"
echo ""
echo "MC 联机：房主开好世界并『对局域网开放』后，"
echo "你打开 MC 多人游戏 → 直接连接 → 填 ${SUBNET}.1:25565"
echo ""
echo "退出房间：sudo kill $EDGE_PID && sudo ip link del n2n0"
echo "=============================================="
