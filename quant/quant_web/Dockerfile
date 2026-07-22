FROM python:3.11-slim

# 爬取渲染由宿主机 Chrome 服务提供，容器内仅保留 SSL 证书
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY quant_web/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 复制项目代码（排除 xlsx 等大文件，见 .dockerignore）
COPY . /app/
WORKDIR /app

RUN chmod +x /app/quant_web/entrypoint.sh

# 默认启动 Flask (gunicorn)
EXPOSE 5000
ENTRYPOINT ["/app/quant_web/entrypoint.sh"]
CMD ["web"]
