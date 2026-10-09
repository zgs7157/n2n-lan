#!/usr/bin/env bash
# =============================================================================
# n2n supernode 部署（Docker 方式，备用方案）
# 用法:   bash deploy_supernode_docker.sh [端口]
# 前置:   已安装 docker 且当前用户有权限
# 说明:   qida/n2n 为社区镜像（含 n2n v3），使用前建议 docker pull 后核对版本
# =============================================================================
set -euo pipefail
PORT="${1:-7654}"

docker pull qida/n2n
docker rm -f n2n-supernode >/dev/null 2>&1 || true
docker run -d --name n2n-supernode --restart=always \
  -p "${PORT}:${PORT}/udp" \
  qida/n2n supernode -p "${PORT}" -f

echo "Docker supernode 已启动: UDP ${PORT}"
echo "日志: docker logs -f n2n-supernode"
echo "提示: 云安全组同样需要放行 UDP ${PORT}"
