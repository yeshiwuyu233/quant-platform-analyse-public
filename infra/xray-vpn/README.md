# Xray VPN

基于 Docker 的独立 VPN 服务，使用 Xray + VLESS + TLS。

## 快速部署

```bash
# 1. 复制配置并填入 UUID
cp xray/config.example.json xray/config.json
# 编辑 xray/config.json，替换 YOUR_UUID_HERE 为实际 UUID

# 2. 申请 TLS 证书（以 acme.sh + 阿里云 DNS 为例）
export Ali_Key="your_ali_key"
export Ali_Secret="your_ali_secret"
acme.sh --issue --dns dns_ali -d your-domain.com \
  --key-file ./xray/cert/privkey.pem \
  --fullchain-file ./xray/cert/fullchain.pem

# 3. 启动
docker compose up -d
```

## 项目结构

```
├── docker-compose.yml      # 容器定义
├── xray/
│   ├── config.json         # Xray 配置 (含 UUID，不上传)
│   ├── config.example.json # 配置模板
│   └── cert/               # TLS 证书 (不上传)
├── subscription/
│   ├── nginx.conf          # 订阅页面 nginx 配置
│   ├── index.html          # 订阅页面
│   └── config.example.yaml # Clash 订阅模板
└── ttyd/
    └── nginx.conf          # 终端反向代理配置
```

## 客户端

- **Shadowrocket**: VLESS + TLS，直接扫码
- **Clash Verge**: 导入 subscription 订阅链接
