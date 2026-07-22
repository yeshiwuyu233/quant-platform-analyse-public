#!/bin/bash
# ═══════════════════════════════════════════════════
# 阿里云 Ubuntu 22.04 一键部署脚本
# 用法:
#   1. 把整个项目 scp 到服务器
#      scp -r /本地路径/全市场 root@你的IP:/var/www/quant
#   2. ssh 登录服务器后执行
#      cd /var/www/quant/quant_web && bash deploy.sh 你的域名.com
# ═══════════════════════════════════════════════════
set -euo pipefail

DOMAIN="${1:-yourdomain.com}"

echo "========================================"
echo " 量化系统部署 — Ubuntu 22.04"
echo " 域名: $DOMAIN"
echo "========================================"

# 1. 安装 Docker
echo "[1/6] 安装 Docker..."
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. 确认已上传
echo ""
echo "[2/6] 检查项目文件..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJ_DIR/Whole Market.xlsx" ]; then
    echo "  ✅ 项目文件完整"
else
    echo "  ⚠️  Whole Market.xlsx 不存在，流水线首次运行时会自动创建"
fi

# 3. 安装 certbot 并获取 SSL 证书
echo "[3/6] 申请 SSL 证书..."
apt-get install -y certbot
certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos -m admin@"${DOMAIN}" 2>/dev/null || {
    echo "  ⚠️  certbot 失败，可后续手动配置或先用 HTTP"
    echo "  临时方案: 修改 nginx.conf 去掉 SSL 部分，只保留 HTTP"
}

# 4. 修改 nginx.conf 中的域名
echo "[4/6] 配置 nginx..."
cd "$SCRIPT_DIR"
sed -i "s/yourdomain.com/$DOMAIN/g" nginx.conf

# 5. 构建并启动容器
echo "[5/6] 构建并启动容器..."
cd "$SCRIPT_DIR"
docker compose up -d --build

# 6. 设置定时任务（交易日 17:30 执行流水线）
echo "[6/6] 设置定时任务..."
PIPELINE_CMD="20 17 * * 1-5 /root/pipeline_wrapper.sh >> /var/log/quant/pipeline_wrapper.log 2>&1"
(crontab -l 2>/dev/null | grep -v "quant-pipeline"; echo "$PIPELINE_CMD") | crontab -

echo ""
echo "========================================"
echo " 🎉 部署完成！"
echo " 访问: https://$DOMAIN"
echo ""
echo " 日常管理:"
echo "  docker compose -f $SCRIPT_DIR/docker-compose.yml logs web  # Web 日志"
echo "  tail -f /var/log/quant-pipeline.log                        # 流水线日志"
echo "  docker exec quant-web /app/quant_web/entrypoint.sh bash     # 进入容器"
echo "========================================"
