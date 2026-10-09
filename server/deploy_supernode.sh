#!/usr/bin/env bash
# =============================================================================
# n2n v3 supernode 一键部署脚本（Linux / systemd）
# 用法:   bash deploy_supernode.sh [端口]
# 默认:   端口 7654 (UDP)
# 部署后客户端填写:  你的服务器公网IP:7654
# =============================================================================
set -euo pipefail
PORT="${1:-7654}"
VERSION="3.1.1"

if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  echo "错误: 需要 curl 或 wget" >&2; exit 1
fi

echo "[1/5] 安装编译依赖..."
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y build-essential autoconf automake libtool pkg-config make gcc
elif command -v yum >/dev/null 2>&1; then
  yum install -y gcc make autoconf automake libtool pkg-config
else
  echo "不支持的发行版，请手动安装 gcc/make/autoconf/automake/libtool" >&2; exit 1
fi

echo "[2/5] 下载 n2n v${VERSION} 源码..."
cd /tmp
dl() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o n2n.tar.gz "$1"
  else
    wget -q -O n2n.tar.gz "$1"
  fi
}
dl "https://github.com/ntop/n2n/archive/refs/tags/${VERSION}.tar.gz" \
  || dl "https://ghproxy.net/https://github.com/ntop/n2n/archive/refs/tags/${VERSION}.tar.gz" \
  || { echo "下载失败，请检查服务器到 GitHub 的连通性"; exit 1; }
rm -rf "n2n-${VERSION}"
tar xzf n2n.tar.gz
cd "n2n-${VERSION}"

echo "[3/5] 编译安装（约 1-3 分钟）..."
./autogen.sh
./configure
make -j"$(nproc)"
make install
ldconfig 2>/dev/null || true
SUPERNODE_BIN="$(command -v supernode || true)"
if [ -z "${SUPERNODE_BIN}" ] && [ -x /usr/local/sbin/supernode ]; then
  SUPERNODE_BIN="/usr/local/sbin/supernode"
fi
if [ -z "${SUPERNODE_BIN}" ]; then
  echo "错误: 未能定位 supernode 可执行文件，请检查 make install 输出" >&2; exit 1
fi
echo "supernode 位于: ${SUPERNODE_BIN}"

echo "[4/5] 配置 systemd 服务 (UDP ${PORT})..."
cat > /etc/systemd/system/n2n-supernode.service <<EOF
[Unit]
Description=n2n supernode (v${VERSION})
After=network.target

[Service]
Type=simple
ExecStart=${SUPERNODE_BIN} -p ${PORT} -f
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable n2n-supernode
systemctl restart n2n-supernode

echo "[5/5] 防火墙放行 UDP/${PORT}..."
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "${PORT}/udp"
elif command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="${PORT}/udp" >/dev/null
  firewall-cmd --reload >/dev/null
else
  iptables -I INPUT -p udp --dport "${PORT}" -j ACCEPT 2>/dev/null || true
fi

echo ""
echo "========== 部署完成 =========="
echo "服务状态:  systemctl status n2n-supernode"
echo "监听检查:  ss -ulnp | grep ${PORT}"
echo "客户端填写:  公网IP:${PORT}"
echo "注意: 云厂商安全组/防火墙控制台也要放行 UDP ${PORT}"
echo "查看日志:  journalctl -u n2n-supernode -f"
echo "=============================="
