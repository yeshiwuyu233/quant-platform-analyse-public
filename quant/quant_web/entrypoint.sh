#!/bin/bash
set -e

# 默认启动 web
if [ $# -eq 0 ] || [ "$1" = "web" ]; then
  cd "$(dirname "$0")"  # 切到 quant_web 目录，使 import data_service 能找到
  exec gunicorn app:app \
    --bind 0.0.0.0:5000 \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --keep-alive 5 \
    --graceful-timeout 10
fi

case "$1" in
  pipeline)
    exec python quant_web/run_pipeline.py
    ;;
  bash)
    if [ $# -eq 1 ]; then
      exec bash
    else
      shift
      exec bash "$@"
    fi
    ;;
  *)
    exec "$@"
    ;;
esac
