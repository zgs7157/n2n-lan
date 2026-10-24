#!/usr/bin/env bash
# =============================================================================
# n2n-lan 房间管理工具 · macOS 启动脚本
# =============================================================================
# 用法：在终端执行  bash start_mac.sh
# 前置：Python 3（自带 tkinter）、n2n edge、tuntap 驱动（或使用 utun）
# 若缺组件，脚本会自动给出安装指引。
# =============================================================================
set -u
cd "$(dirname "$0")" || exit 1

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "[错误] 未找到 python3。请先安装 Python 3（带 tkinter）："
    echo "  brew install python-tk"
    echo "  （或从 https://www.python.org/downloads/macos/ 下载安装包）"
    exit 1
fi

# ---------- 1. 检查 tkinter ----------
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "[错误] Python 缺少 tkinter。请安装："
    echo "  brew install python-tk"
    exit 1
fi

# ---------- 2. 检查 n2n edge ----------
EDGE=""
# 优先用项目自带（用户自己编译后放 bin/）
if [ -x "./bin/edge" ]; then
    EDGE="./bin/edge"
elif command -v edge >/dev/null 2>&1; then
    EDGE="$(command -v edge)"
elif [ -x "/opt/local/bin/edge" ]; then
    EDGE="/opt/local/bin/edge"          # MacPorts
elif [ -x "/opt/local/sbin/edge" ]; then
    EDGE="/opt/local/sbin/edge"         # MacPorts (sbin)
fi

if [ -z "$EDGE" ]; then
    echo "[提示] 未找到 n2n edge。请任选一种方式安装："
    echo ""
    echo "  方式A（推荐，MacPorts 一键装）："
    echo "    sudo port install n2n"
    echo ""
    echo "  方式B（Homebrew 源码编译，Intel/Apple 芯片均可）："
    echo "    brew install autoconf automake libtool openssl"
    echo "    git clone https://github.com/ntop/n2n.git /tmp/n2n && cd /tmp/n2n"
    echo "    ./autogen.sh && ./configure && make"
    echo "    sudo make install        # edge 会装到 /usr/local/bin/edge"
    echo ""
    echo "  装好后把 edge 拷到本目录 bin/ 下，或重新运行本脚本。"
    exit 1
fi
echo "[OK] 找到 edge: $EDGE"

# ---------- 3. 检查虚拟网卡（tuntap 或 utun） ----------
if [ -e /dev/tap0 ] || [ -e /dev/tun0 ] || ifconfig 2>/dev/null | grep -q "utun"; then
    echo "[OK] 虚拟网卡可用（tuntap/utun）"
else
    echo "[提示] 未检测到 tuntap 驱动。n2n 需要 TUN/TAP 接口："
    echo "  Intel Mac:  brew install --cask tuntap"
    echo "  然后到「系统设置 → 隐私与安全性」允许内核扩展，重启生效。"
    echo "  Apple 芯片（M 系列）: 官方 tuntap 驱动安装受限，"
    echo "  请参考项目 README 的 macOS 章节（可能需要降低安全策略）。"
    echo ""
    echo "若只是当「好友」进房，可完全不装 n2n：直接用 MC 客户端"
    echo "「多人游戏 → 直接连接 → 输入房主 IP:25565」即可，无需本工具。"
    echo ""
    read -r -p "是否仍要继续启动（等装好驱动后再进房）？[y/N] " ans
    case "$ans" in
        y|Y) ;;
        *) echo "已取消。"; exit 0 ;;
    esac
fi

# ---------- 4. 启动主程序 ----------
echo "[启动] python3 n2n_room_manager.py"
exec "$PY" n2n_room_manager.py
