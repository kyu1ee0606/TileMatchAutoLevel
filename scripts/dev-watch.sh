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
    # --reload-dir app: backend/scripts·tests·data 저장으로는 재로드하지 않는다(분석 스크립트 저장마다 재로드되던 문제)
    # WATCHFILES_FORCE_POLLING: macOS FSEvents 감시가 이벤트를 한 박자 늦게(다음 변경 때) 전달해
    #   재로드가 멈춘 것처럼 보이던 문제 → 폴링(300ms)으로 즉시·결정적 감지 (2026-10-14 실측: 네이티브 감시는
    #   70초간 이벤트 0건). 비용: app/storage 데이터 파일까지 훑어 리로더가 코어 1개의 약 14% 사용.
    #   (uvicorn --reload-dir 는 디렉터리만 받아 main.py 등 루트 파일을 따로 지정할 수 없어 app 전체를 감시)
    (cd "$ROOT/backend" && WATCHFILES_FORCE_POLLING=true venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app >> /tmp/uvicorn.log 2>&1)
    echo "[watch] backend 종료 → 2s 후 재시작"
    sleep 2
  done
}

watch_frontend &
watch_backend &
wait
