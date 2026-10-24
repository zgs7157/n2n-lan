#!/usr/bin/env bash
# =============================================================================
# n2n-lan · macOS 客户端打包脚本（可选）
# =============================================================================
# 生成一个可分发的 macOS 客户端目录（含 edge、转发器源码、启动脚本），
# 朋友拷贝到 Mac 上直接 bash start_mac.sh 就能用（仍需装 tuntap 驱动）。
#
# 用法：在 Mac 上 cd client && bash make_mac_pkg.sh
# 输出：../n2n-lan-client-mac/ 目录
# =============================================================================
set -u
cd "$(dirname "$0")" || exit 1
OUT="../n2n-lan-client-mac"

echo "[1/3] 创建输出目录: $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/bin" "$OUT/logs"

echo "[2/3] 拷贝必需文件..."
cp n2n_room_manager.py "$OUT/"
cp udp6_client_forward.py "$OUT/bin/"
cp start_mac.sh "$OUT/"
cp start.bat "$OUT/" 2>/dev/null || true
cp join_room_linux.sh "$OUT/" 2>/dev/null || true
cp 使用说明.txt "$OUT/" 2>/dev/null || true
cp README_EN.txt "$OUT/" 2>/dev/null || true
if [ -x bin/edge ]; then
    cp bin/edge "$OUT/bin/edge"
    echo "     已带上编译好的 edge"
else
    echo "     [提示] bin/edge 不存在，接收方需先运行 install_mac.sh 编译"
fi
chmod +x "$OUT/start_mac.sh" "$OUT/bin/edge" 2>/dev/null || true

echo "[3/3] 完成。目录内容："
ls -la "$OUT" "$OUT/bin"
echo ""
echo "分发：把 n2n-lan-client-mac 文件夹整个发给朋友。"
echo "朋友操作："
echo "  1. （如缺 edge）先 bash install_mac.sh 编译 edge"
echo "  2. bash start_mac.sh"
echo ""
echo "可选：若想打包成 .app（双击打开），在 Mac 上执行："
echo "  brew install pyinstaller"
echo "  cd $OUT"
echo "  pyinstaller --onefile --windowed --name N2NRoomManager \\"
echo "      --add-data 'bin/edge:bin' --add-data 'bin/udp6_client_forward.py:bin' \\"
echo "      n2n_room_manager.py"
echo "  产物在 dist/N2NRoomManager.app"
