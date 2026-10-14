#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# n2n supernode 手机部署脚本（Termux / Linux / Android）
# 在 Termux 终端里执行： bash deploy_supernode_android.sh
# 作用：下载 lucktu 预编译静态包并后台启动 supernode（UDP 7654）
# 手机建议：插电 + 开热点/移动数据（走移动数据时有公网 IPv6，朋友可直接连）
# ============================================================

set -e

echo "==== n2n supernode 手机部署 ===="

# 1) 确保基础工具
for cmd in wget tar curl; do
  command -v $cmd >/dev/null 2>&1 || { echo "安装 $cmd ..."; pkg install -y $cmd; }
done

# 2) 判断 CPU 架构（绝大多数安卓手机是 arm64）
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64)
    FILE="n2n_v3_linux_arm64%28aarch64%29_v3.1.1_r1255_static_by_heiye.tar.gz" ;;
  x86_64|amd64)
    FILE="n2n_v3_linux_x64_v3.1.1_r1255_static_by_heiye.tar.gz" ;;
  *)
    echo "不支持的架构: $ARCH（需要 arm64 或 x86_64）"; exit 1 ;;
esac
URL="https://gitee.com/lucktu/n2n/raw/master/Linux/$FILE"
echo "架构: $ARCH"

mkdir -p ~/n2n-supernode
cd ~/n2n-supernode

# 3) 下载解压（已存在则跳过）
if [ ! -x ./supernode ]; then
  echo "下载预编译包 ..."
  wget -q -O pkg.tar.gz "$URL"
  tar xzf pkg.tar.gz
  chmod +x supernode
  echo "下载完成"
else
  echo "supernode 已存在，跳过下载"
fi

echo "版本: $(./supernode --version 2>&1 | head -1 || echo v3)"

# 4) 后台启动（已在运行则跳过）
if pgrep -f "supernode -p 7654" >/dev/null 2>&1; then
  echo "supernode 已在运行（UDP 7654）"
else
  echo "启动 supernode（UDP 7654，后台）..."
  nohup ./supernode -p 7654 -l 5645 > supernode.log 2>&1 &
  echo "已启动 PID: $!"
  sleep 2
  echo "--- 日志 ---"
  tail -5 supernode.log
fi

# 5) 验证 + 输出给朋友填的地址
echo ""
echo "==== 部署结果 ===="
if pgrep -f "supernode -p 7654" >/dev/null 2>&1; then
  echo "[OK] supernode 运行中，UDP 7654"
else
  echo "[!] 未检测到运行，请看 ~/n2n-supernode/supernode.log"
fi

echo ""
echo "==== 你的公网 IPv6（发给朋友填进客户端「服务器」栏）===="
V6=""
if command -v curl >/dev/null 2>&1; then
  V6="$(curl -6 -s --max-time 6 https://6.ipw.cn || true)"
fi
if [ -z "$V6" ] && command -v ip >/dev/null 2>&1; then
  V6="$(ip -6 addr show scope global 2>/dev/null | grep inet6 | awk '{print $2}' | cut -d'/' -f1 | grep -v '^fe80' | head -1)"
fi
if [ -n "$V6" ]; then
  echo "朋友在客户端「服务器」栏填："
  echo "    [$V6]:7654"
  echo ""
  echo "注意：手机重连网络（飞行模式/重启/换 WiFi）后 IPv6 会变，需重新查一次。"
else
  echo "（未取到 IPv6。检查：是否开启了数据/WiFi 的 IPv6？或稍后手动执行： curl -6 https://6.ipw.cn）"
fi

echo ""
echo "==== 可选：开机自启 ===="
echo "安装 Termux:Boot 插件后，把下面两行存为 ~/.termux/boot/supernode.sh 即可开机自动启动："
echo "  cd ~/n2n-supernode"
echo "  nohup ./supernode -p 7654 -l 5645 > supernode.log 2>&1 &"
