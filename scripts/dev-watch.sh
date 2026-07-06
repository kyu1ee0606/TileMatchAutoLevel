#!/bin/bash
# 프론트/백엔드 자동 재시작 감시 — 죽으면 2초 후 재기동. 로그: /tmp/{vite,uvicorn}.log
ROOT="/Users/casualdev/TileMatchAutoLevel"

watch_frontend() {
  while true; do
    echo "[watch] frontend 시작 $(date '+%H:%M:%S')"
    (cd "$ROOT/frontend" && npm run dev >> /tmp/vite.log 2>&1)
    echo "[watch] frontend 종료 → 2s 후 재시작"
    sleep 2
  done
}
watch_backend() {
  while true; do
    echo "[watch] backend 시작 $(date '+%H:%M:%S')"
    (cd "$ROOT/backend" && venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload >> /tmp/uvicorn.log 2>&1)
    echo "[watch] backend 종료 → 2s 후 재시작"
    sleep 2
  done
}

watch_frontend &
watch_backend &
wait
