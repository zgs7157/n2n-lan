#!/usr/bin/env bash
# =============================================================================
# n2n-lan 房间管理工具 · macOS 一键部署脚本
# =============================================================================
# 作用：
#   1. 检查/安装 Homebrew 与编译工具
#   2. 从官方源码编译 n2n v3.1.1 的 edge，拷到本项目 bin/ 下
#   3. 检查 tuntap 驱动，给出安装指引（Intel / Apple 芯片不同提示）
# 用法：在终端执行  bash install_mac.sh
# 说明：需要网络与 Xcode Command Line Tools；Apple 芯片无需特殊处理（纯源码编译）。
# =============================================================================
set -u
cd "$(dirname "$0")" || exit 1
PROJ_BIN="$(pwd)/bin"

echo "=================================================="
echo " n2n-lan · macOS 一键部署"
echo "=================================================="

# ---------- 0. Xcode CLT ----------
echo ""
echo "[1/5] 检查 Xcode Command Line Tools..."
if ! xcode-select -p >/dev/null 2>&1; then
    echo "未安装，将弹出系统安装窗口，装完请重跑本脚本。"
    xcode-select --install
    exit 1
fi
echo "[OK] Xcode CLT 已就绪"

# ---------- 1. Homebrew ----------
echo ""
echo "[2/5] 检查 Homebrew..."
if ! command -v brew >/dev/null 2>&1; then
    echo "未安装 Homebrew，开始安装（约几分钟）..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple 芯片路径
    if [ -x "/opt/homebrew/bin/brew" ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
if ! command -v brew >/dev/null 2>&1; then
    echo "[错误] Homebrew 安装失败，请手动安装后重跑。"
    exit 1
fi
echo "[OK] Homebrew: $(brew --version | head -1)"

# ---------- 2. 编译依赖 ----------
echo ""
echo "[3/5] 安装编译依赖（autoconf automake libtool openssl）..."
brew install autoconf automake libtool openssl 2>&1 | tail -3

# ---------- 3. 编译 n2n edge ----------
echo ""
echo "[4/5] 编译 n2n v3.1.1 edge（首次编译约 2-5 分钟）..."
TMP="/tmp/n2n-lan-build-$$"
mkdir -p "$TMP"
if ! git clone --depth 1 --branch 3.1.1 https://github.com/ntop/n2n.git "$TMP" 2>/dev/null; then
    # git clone 失败（网络原因）则改用 codeload 下载源码包
    echo "git clone 失败，改用源码包下载..."
    curl -fsSL -o "$TMP.tar.gz" "https://codeload.github.com/ntop/n2n/tar.gz/refs/tags/3.1.1" || { echo "[错误] 下载失败"; exit 1; }
    tar -xzf "$TMP.tar.gz" -C "$TMP" --strip-components=1 2>/dev/null || { echo "[错误] 解压失败"; exit 1; }
fi
cd "$TMP" || exit 1
./autogen.sh >/dev/null 2>&1
./configure --disable-static >/dev/null 2>&1 || ./configure >/dev/null 2>&1
make -j4 >/dev/null 2>&1
if [ ! -x "./edge" ]; then
    echo "[错误] 编译失败。请手动按 README 的 macOS 章节编译，或改用 MacPorts："
    echo "  sudo port install n2n"
    exit 1
fi
mkdir -p "$PROJ_BIN"
cp ./edge "$PROJ_BIN/edge"
chmod +x "$PROJ_BIN/edge"
cd - >/dev/null 2>&1
rm -rf "$TMP" "$TMP.tar.gz"
echo "[OK] edge 已编译并安装到: $PROJ_BIN/edge"
"$PROJ_BIN/edge" --help 2>&1 | head -2

# ---------- 4. tuntap 驱动 ----------
echo ""
echo "[5/5] 检查虚拟网卡驱动..."
if [ -e /dev/tap0 ] || ifconfig 2>/dev/null | grep -q "utun"; then
    echo "[OK] 虚拟网卡可用"
else
    echo "未检测到 tuntap 驱动。两种方案："
    echo ""
    echo "  方案① 安装 tuntap（Intel Mac 通常可行）："
    echo "    brew install --cask tuntap"
    echo "    然后：系统设置 → 隐私与安全性 → 允许系统软件（内核扩展）→ 重启"
    echo ""
    echo "  方案② 走「好友直连」零安装（推荐，全部 Mac 可用）："
    echo "    不装 n2n，用 MC 客户端 → 多人游戏 → 直接连接 → 输入房主 IP:25565"
    echo ""
    echo "装好 tuntap 后运行:  bash start_mac.sh"
fi

echo ""
echo "=================================================="
echo " 部署完成！下一步：bash start_mac.sh"
echo "=================================================="
