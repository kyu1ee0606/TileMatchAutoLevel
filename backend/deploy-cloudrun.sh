#!/bin/bash
# TileMatchAutoLevel 백엔드 → Google Cloud Run 배포 (생성/RL검증 컴퓨트 오프로드)
# 선행: gcloud CLI 설치 + `gcloud auth login` + 프로젝트 생성/결제계정 연결.
#
# 사용: PROJECT_ID=your-proj FRONTEND_ORIGIN=http://localhost:5173 ./deploy-cloudrun.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID 필요 (예: PROJECT_ID=tilematch-123)}"
REGION="${REGION:-us-central1}"          # 무료 리전(1.0x 배수). asia-northeast3(서울)은 가까우나 배수 확인
SERVICE="${SERVICE:-tilematch-backend}"
FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://localhost:5173}"
CPU="${CPU:-4}"                          # 컨테이너당 코어(RL ProcessPool = cpu-2). 무료량 아끼려면 1~2
MEMORY="${MEMORY:-2Gi}"
CONCURRENCY="${CONCURRENCY:-1}"          # 요청당 컨테이너(CPU바운드라 1 권장) → 오토스케일로 병렬
MAX_INSTANCES="${MAX_INSTANCES:-20}"     # 동시 최대 컨테이너(무료 quota 기본 상한 근처)

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

# source 배포(로컬 Dockerfile로 Cloud Build) — data/ 베이크됨.
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --cpu "$CPU" --memory "$MEMORY" \
  --concurrency "$CONCURRENCY" \
  --max-instances "$MAX_INSTANCES" \
  --timeout 600 \
  --set-env-vars "CORS_ORIGINS=${FRONTEND_ORIGIN}"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo ""
echo "========================================"
echo "배포 완료: $URL"
echo "프론트 연결: frontend/.env.local 에 VITE_API_URL=${URL}/api 추가 후 재빌드/재시작"
echo "========================================"
