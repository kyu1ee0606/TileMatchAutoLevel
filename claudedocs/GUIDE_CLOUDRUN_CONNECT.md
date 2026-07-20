# Cloud Run 연결 가이드 (무료 온라인 연산 오프로드)

무거운 연산(**레벨 생성 · RL 순차검증 · 봇 시뮬**)만 Google Cloud Run 으로 오프로드.
저장/조회(**보스 템플릿 · 배치 · 컨셉 · 패턴**)는 항상 로컬 → 원격 휘발성 데이터 소실 방지.

연결 안 되어 있으면 기존대로 100% 로컬 동작. 언제든 버튼 하나로 로컬 복귀.

---

## 0. 무엇이 어디로 가나 (라우팅 규칙)

`frontend/src/api/client.ts` 인터셉터가 URL prefix 로 분기:

| Prefix | 대상 | 원격 오프로드? |
|--------|------|:---:|
| `/generate` | 레벨 생성·검증 생성 | ✅ 원격 |
| `/rl-sim` | RL 순차검증 | ✅ 원격 |
| `/analyze/autoplay` `/analyze/solvability` | 봇 시뮬·풀이가능성 | ✅ 원격 |
| 그 외 (`/debug/boss-*`, 배치, 컨셉 저장 등) | 상태 데이터 | ❌ 항상 로컬 |

원격 URL 미설정 시 전부 로컬. 설정 시 위 3종만 원격, 나머지 로컬.

---

## 1. 선행 준비 (최초 1회)

```bash
# gcloud CLI 설치 (macOS)
brew install --cask google-cloud-sdk

# 로그인 (원하는 구글 계정 선택)
gcloud auth login

# 프로젝트 생성 + 결제계정 연결 (무료티어 쓰려면 결제계정 필수, 과금은 무료량 초과분만)
gcloud projects create tilematch-123 --name="TileMatch"
# → Cloud Console 에서 결제계정 링크: https://console.cloud.google.com/billing
```

무료량: 결제계정당 **월 180,000 vCPU-초** (매월 리셋). 전체배치 검증 ~40회/월 또는 단건 ~6만회/월.

---

## 2. 배포 (코드 바뀔 때만 재실행)

```bash
cd backend
PROJECT_ID=tilematch-123 FRONTEND_ORIGIN=http://localhost:5173 ./deploy-cloudrun.sh
```

- 로컬 `Dockerfile` 로 Cloud Build → `data/` 베이크됨
- 끝나면 URL 출력: `https://tilematch-backend-xxxx.run.app`
- 옵션(환경변수): `REGION`(기본 us-central1) · `CPU`(기본 4, 무료아끼려면 1~2) · `MAX_INSTANCES`(기본 20)

```bash
# 예: 서울 리전, CPU 2로 무료량 절약
PROJECT_ID=tilematch-123 REGION=asia-northeast3 CPU=2 ./deploy-cloudrun.sh
```

---

## 3. 앱에서 연결 (매일 쓰는 부분)

1. 앱 헤더 우측 **`💻 로컬 연산`** 버튼 클릭
2. 배포 URL 붙여넣기: `https://tilematch-backend-xxxx.run.app`
3. **`연결(테스트 후 저장)`** 클릭
   - 내부적으로 `GET {url}/docs` 로 헬스체크
   - **성공 → 저장·활성** (`☁️ 원격 연산 ON` 녹색)
   - **실패 → 저장 안 함, 로컬 유지** (`✗ 실패 → 로컬 유지`)
4. 이제 생성·순차검증·봇시뮬 = 원격. 템플릿·배치 = 로컬 그대로.

로컬 복귀: **`💻 로컬로`** 클릭 → 즉시 로컬 검증만.

---

## 4. 구글 계정 바꾸기 (다른 무료 quota 로 갈아타기)

무료량 소진 시 다른 계정으로 스왑:

```bash
gcloud auth login            # 새 계정 선택
gcloud config set account new@gmail.com
PROJECT_ID=tilematch-b-456 FRONTEND_ORIGIN=http://localhost:5173 ./deploy-cloudrun.sh
```

새 URL 나오면 → 앱 토글에 **새 URL 재연결**. 끝. 기존 URL 은 덮어써짐.

---

## 5. "아닌 거 같으면 바로 분리"

- 앱: **`💻 로컬로`** 한 번 → 코드 변경 0, 즉시 로컬 전용
- 완전 제거: Cloud Run 서비스 삭제 → 과금 원천 차단
  ```bash
  gcloud run services delete tilematch-backend --region us-central1
  ```
- 프론트/백엔드 코드는 원격 미설정 시 원래대로 동작 → 롤백 불필요

---

## 6. 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| 연결 `✗ 실패` | CORS / URL 오타 / 콜드스타트 | URL 재확인, `FRONTEND_ORIGIN` 배포값과 앱 origin 일치 확인, 재시도(콜드스타트 몇 초) |
| 생성은 되는데 저장 안 됨 | 정상 | 저장은 로컬 백엔드로 감 → 로컬 백엔드도 켜둬야 함 |
| 첫 요청 느림 | 콜드스타트 | `--min-instances 1` 추가(무료량 더 씀) 또는 감수 |
| CORS 에러 | origin 불일치 | `FRONTEND_ORIGIN` 을 실제 앱 URL 로 재배포 |

**중요**: 원격 연산 켜도 **로컬 백엔드는 계속 켜둬야** 함 (템플릿·배치 저장/조회는 로컬행).
