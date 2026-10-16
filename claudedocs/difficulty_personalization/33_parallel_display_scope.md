# 33. 1단계 구현 범위 보고서 — 새 예측(봇 v2.3 + E1) 병행 표시 (D17)

> 작성 2026-10-16 · 브랜치 `feature/pv-seed-variants` · **코드 수정 없음. 읽기·문서만.** 사용자 승인 전.
> 범위: 문서 31 §7 D17 — 새 E1 예측(목표 지표 ⑤ 첫 시도·도움 포함)을 **기존 `predicted_clear_rate` 옆에 병행 표시만** 한다. 합격 판정 전환(D14)·게임 표시 난이도(xDifficulty, 트랙 B·D15)·라이브 배포는 범위 밖, 별도 승인.
> 전제 참고: 문서 31 §2~§7(설계 전체), 문서 26 §11(v2.4 최종 — 성능은 v2.3과 동일, "규칙만" 입력 채택. 모델은 v2.3 봇 입력 기준으로 둬도 된다).

## 1. MVP — 어디에 무엇을 표시하나

표시 위치 후보 2곳. **추천: 둘 다 아닌, 하나만 먼저.**

| 화면 | 표시 가능성 | 비고 |
|---|---|---|
| 프로덕션 대시보드 배치 표(`ProductionDashboard/index.tsx`) | **추천 시작점** | 레벨별 행이 이미 있다. 열 추가가 유닛 하나로 끝난다. 다만 이 파일은 **다른 세션이 지금 수정 중**(아래 §5) |
| 생성 결과 패널(`DifficultyPanel` 등 단건 뷰) | 2단계로 미룸 | 단건 흐름은 화면이 여러 개(생성/재생성/보스 미세조절)라 노출 지점이 흩어진다. 1단계는 배치 표 하나로 좁히는 게 작다 |

행(레벨)마다 추가 표시 값 — 문서 31 §3-4 카드의 축소판, **열 추가** 형태:

- `새 예상(⑤)` — E1 point estimate (0~1, %로 표시)
- `80% 범위` — `[lo, hi]`
- `신뢰도` — high/medium/low
- `경고` — 배지. `NEAR_CEILING`(천장, ≥0.95) / `LOW_CONFIDENCE`(신뢰 낮음, §3-2 hard 경고 중 하나라도 있으면) — **문서 31 사용자 확정 요건대로 0.85 미만 목표·예측엔 "신뢰 낮음" 필수, 0.95+는 천장 경고 필수**
- `무도움 클리어(LB)` / `도움 사용률` — 보조 지표, 작은 글씨로 같은 셀
- (목표가 있는 레벨만) `목표 대비` — 기존 목표 열 옆에 새 예측 기준 범위 포함 여부만 표시(판정 아님, 정보용)

**바꾸지 않는 것**: 기존 `predicted_clear_rate` 열·값, `verification_passed`(합격 판정), 업로드 시 `gboost.py`가 읽는 값. 새 값은 레벨 메타에 **새 필드**로만 추가한다(`expected_clear_rate_v1`, `clear_rate_range80`, `clear_rate_confidence`, `clear_rate_evidence_flags`, `unaided_lb_expected`, `help_rate_expected`, `clear_rate_model_version` — 이름은 결정 필요, §6 D-a).

**근거 부족 사유**는 문서 31 §3-2 `evidence_flags` 코드를 그대로 쓴다(새로 정의하지 않음) — `PLACEMENT_MISSING`, `LEVEL_OUT_OF_RANGE`, `TARGET_OUT_OF_SUPPORT`, `GIMMICK_UNSEEN`/`GIMMICK_LOW_TRAIN`, `GIMMICK_FIRST`/`NOVELTY_HIGH`, `GIMMICK_BOT_WEAK`, `FEATURE_OOD`, `NEAR_CEILING`, `BOT_PROTOCOL_MISMATCH`, `UNSOLVED`. 병행 표시 단계는 판정을 안 하므로 hard/soft 구분은 "경고 배지 색"으로만 쓰고 PASS/FAIL/INSUFFICIENT_EVIDENCE 판정 자체는 내지 않는다(D17 요건).

## 2. 백엔드

### 2-1. 신규 모듈·API
| 항목 | 내용 |
|---|---|
| 모듈 | `backend/app/core/clear_rate/{__init__,features,model,guard}.py` (신규) — `residual_model_lib.py`의 특징 계산 로직을 단건 입력(level_json + placement_level)으로 이식. 학습은 안 하고 **artifact 로드 + 예측만** |
| API | `POST /api/clear-rate/predict`(단건) — 문서 31 §3-1 요청/응답 스키마 그대로. `select`(여러 후보 순위)·`model`(manifest)는 1단계엔 불필요(선별·판정은 범위 밖) → **2단계로 미룸** |
| 스키마 | `backend/app/models/schemas.py`에 요청/응답 Pydantic 모델 추가(기존 파일, 새 클래스만 추가) |
| 라우터 등록 | `backend/app/main.py`에 `clear_rate` 라우터 추가 — **충돌 위험**(아래 §5) |

### 2-2. 모델 파일·manifest
- 저장 위치: `backend/data/models/clear_rate/<version>/` (현재 없음 — `backend/data/models/` 디렉터리 자체가 없다, 신규 생성)
- 내용: Ridge 계수·표준화값, LightGBM point+quantile 모델, CQR 보정폭, 특징 이름/순서, manifest.json(`model_version`, `target_metric=ft_any_v1`, `bot_version=v2.3`, AF 기간·버전, 특징 해시, K-fold 지표)
- 학습은 서버 밖 스크립트(`backend/scripts/train_clear_rate_model.py`, 신규)가 `residual_model_lib.py` 재사용해서 만든다. 서버는 읽기만.

### 2-3. 봇 측정 재사용 vs 신규
- **재사용**: 문서 31 §1-5·§2-3 평가에 쓴 **v2.3, 410레벨(⑤ 교집합 379레벨) 측정 결과**를 그대로 학습 데이터로 쓴다. 새 봇 측정 불필요.
- **레벨당 예측 비용**(새 레벨 예측 시, 캐시 없는 경우): 봇 측정 θ 4개×128판 = 512판. 문서 31 §6에 "판당 시간은 v2.3에서 재야 한다"고 명시 — **현재 레벨당 소요 시간 수치 없음** (이번 조사에서도 측정 안 함, 별도 재는 작업 필요).
- **캐시**: `level_json` 해시 + `placement_level`을 키로, 봇 측정 결과·예측 결과를 레벨 메타에 저장(한 번 계산하면 재사용). 맵이 안 바뀌면 재계산 안 함.

### 2-4. 백엔드 런타임 의존성 (결정 필요, §6)
- 학습 코드(`residual_model_lib.py`, `target_metric_eval.py`)는 `analysis_venv`(lightgbm·scikit-learn 포함)에서 돈다. `backend/requirements.txt`에는 **없다**.
- 예측만 하는 1단계 API가 lightgbm을 로드하려면 백엔드 런타임에 lightgbm(+서버 libomp) 추가가 필요. 대안은 Ridge+LightGBM을 순수 파이썬 트리 순회로 재구현(의존성 0, 1~2일 추가, 문서 31 D7). **1단계 시작 전 결정 필요** — 승인 없으면 구현 착수 불가.

## 3. 프론트

| 파일 | 변경 |
|---|---|
| `frontend/src/api/clearRate.ts` (신규) | `predict` 호출 함수, 응답 타입 |
| `frontend/src/types/production.ts` (기존, 다른 세션 수정 중 — §5) | 레벨 메타에 새 필드 타입 추가(`expected_clear_rate_v1?`, `clear_rate_range80?`, `clear_rate_confidence?`, `clear_rate_evidence_flags?`, `unaided_lb_expected?`, `help_rate_expected?`) — **기존 `predicted_clear_rate` 등 타입은 안 건드림** |
| `frontend/src/components/ProductionDashboard/index.tsx` (기존, 다른 세션 대량 수정 중 — §5) | 배치 표에 열 추가, 셀 렌더 컴포넌트 import. **757/5240~5300/5520 등 판정 로직 라인은 안 건드림**(병행 표시는 판정과 무관) |
| `frontend/src/components/ClearRate/ClearRateCell.tsx` (신규, 작은 컴포넌트) | 예상·범위·신뢰도·경고 배지 렌더. 문서 31 §3-4 카드의 1줄 압축판 |

CLAUDE.md 프로젝트 규칙대로 **백엔드 스키마 변경 시 프론트 타입 동기화 필수** — `clearRate.ts` 응답 타입과 백엔드 Pydantic 스키마를 1:1로 맞춘다.

## 4. 데이터 파이프라인

| 항목 | 내용 |
|---|---|
| 학습 산출물 저장 | `backend/data/models/clear_rate/<version>/`(§2-2), git 포함(바이너리 작아야 함 — LightGBM txt는 보통 수백KB~수MB. 너무 크면 git-lfs 또는 제외 후 배포 시 별도 전달 — 결정 필요) |
| 재학습 절차 | ① AF 월 1회 pull → `af_level_metrics.py`(⑤는 이미 `ft_clear_rate_any_help`로 산출, 수정 불필요) ② `train_clear_rate_model.py`(신규) 실행 ③ 게이트(MAE ≤0.035, ρ≥0.72 — 문서 31 §2-2, 숫자는 D9 승인 필요) ④ manifest 갱신 ⑤ 활성 버전 전환(레지스트리 JSON 1개) |
| 봇 버전 고정 | v2.3 고정(또는 v2.4 "규칙만" — 문서 26 §11 확인: 성능 동일, 어느 쪽이든 379레벨 재측정 없이 씀). **봇 버전 바뀌면 410레벨 재측정 필요**(문서 31 §2-2) — 1단계는 재측정 계획 없음, 고정값으로 시작 |

## 5. 파일별 변경 범위 vs 다른 세션 미커밋 변경 (git status·diff --stat 실측, 2026-10-16)

현재 작업트리(미커밋, 같은 브랜치 `feature/pv-seed-variants`):

| 파일 | 다른 세션 변경 내용(실측) | 이 작업과 충돌 위험 |
|---|---|---|
| `backend/app/main.py` | `pv_play` 라우터 1줄 추가(import + include_router) | **낮음** — 같은 파일에 `clear_rate` 라우터를 추가해야 해서 같은 라인 근처를 건드리지만, 각자 추가/추가라 머지 쉬움. 순서만 주의 |
| `frontend/src/components/ProductionDashboard/ProductionExport.tsx` | 무한 레벨(1500→1530 확장) 로직 대량 수정, 47줄 diff | **없음** — 이 1단계는 ProductionExport.tsx를 안 건드림(업로드 후처리는 D16, 범위 밖) |
| `frontend/src/types/production.ts` | `PRODUCTION_MAX_LEVEL=1530` 등 상수·필드 추가, 25줄 diff | **중간** — 같은 파일에 새 타입 필드를 추가해야 함. 다른 세션 변경은 파일 하단(상수)·메타 블록 다른 위치라 **라인 충돌은 낮지만 동시 편집은 피해야** 함(머지 전 상대 세션 커밋 확인 필요) |
| `frontend/src/components/ProductionDashboard/index.tsx` | **217줄 diff**, 상세 미검토(배치 처리 로직으로 추정) | **높음** — 약 1만 줄 대형 파일이고 이미 대량 수정 중. 배치 표에 열을 추가하려면 같은 파일을 건드려야 함 → **이 세션 작업 완료·커밋 후 리베이스해서 작업 시작 권장**. 지금 건드리면 머지 충돌 거의 확실 |
| `frontend/src/storage/productionStorage.ts` | 23줄 diff(미검토, 1530 확장과 연관 추정) | **낮음** — 이 1단계는 안 건드림 |
| `backend/data/boss_templates.json`·`boss_concepts.json`·`fixed_levels.json` | 콘텐츠 데이터 변경 | **없음** — 무관 |
| `frontend/src/components/BossTemplatePanel.tsx`·`FixedLevelEditor.tsx` | 보스/고정레벨 UI | **없음** — 무관 |
| 신규 untracked (`backend/app/api/routes/pv_play.py`, `pvPlay.ts`, `PvSeedPlayPanel.tsx`, `pv_verify_*.py` 등) | 다른 트랙(DDA 시드 재생 검증) 작업 | **없음** — 완전히 다른 파일 |

**결론**: 백엔드 쪽(`main.py`, 신규 `clear_rate/*`)은 충돌이 작다. 프론트는 `ProductionDashboard/index.tsx`가 핵심 충돌 지점 — **이 파일에 열을 추가하는 작업은 다른 세션의 217줄 변경이 커밋된 뒤 시작**하는 것을 권장. 선행 가능한 부분(백엔드 모듈·API·모델 학습 스크립트·`types/production.ts`의 필드 추가만)은 먼저 진행할 수 있다.

## 6. 검증 계획 (프로젝트 CLAUDE.md 필수 절차)

1. 백엔드 스키마 추가 → `frontend/src/api/clearRate.ts` 타입 동기화
2. `npx tsc --noEmit` (프론트 전체 타입 에러 없는지)
3. Playwright 웹뷰 확인: 프로덕션 대시보드 열어서 새 열이 기존 레벨에 뜨는지, 값 없는 레벨(근거 부족)은 "—"나 경고 배지로 뜨는지
4. API 호출 테스트: `curl -X POST /api/clear-rate/predict`로 placement_level 포함/누락 케이스 응답 확인

## 7. 작업량 추정(인일, 추정) · 단계 분할

| 단계 | 내용 | 인일(추정) |
|---|---|---|
| 1 | 백엔드 코어(`clear_rate/` 모듈, artifact 로드, 단건 predict) | 3~4 |
| 2 | API 라우트·스키마·main.py 등록 | 1 |
| 3 | 학습 스크립트(`train_clear_rate_model.py`) + v2.3 379레벨로 1회 학습·manifest | 2 |
| 4 | 프론트 타입·API 클라이언트·`ClearRateCell` 컴포넌트 | 1~2 |
| 5 | `ProductionDashboard/index.tsx` 열 통합(**다른 세션 변경 완료 후**) | 1~2 |
| 6 | 검증(tsc·Playwright·curl) | 0.5~1 |
| **합계** | | **약 8.5~12 인일** (문서 31 전체 17~25 인일 중 "병행 표시만" 부분. select API·판정 전환·게임 표시 연동·독립 선별 재현 스크립트는 제외) |

봇 재측정 비용 제외(기존 379레벨 측정 재사용). 레벨당 신규 예측 시 512판 소요 — 실측 시간 없음(별도 측정 필요).

## 8. 위험

- `ProductionDashboard/index.tsx` 동시 편집 충돌 (위 §5) — 가장 큰 일정 위험.
- lightgbm 백엔드 의존성 미결정이면 1단계 전체가 막힘(§2-4).
- 모델 artifact 파일 크기·저장 위치(git 포함 여부) 미결정.
- 379레벨 학습 데이터 밖(저신뢰) 레벨이 많으면 "경고만 뜨고 값 없음"인 레벨이 다수 → 화면이 비어 보일 수 있음(기대치 관리 필요, 기능 결함 아님).
- 캐시 키(level_json 해시+placement_level) 설계 누락 시 매번 재측정(비용 큼).

## 9. 승인 필요 결정 (이 1단계 범위)

| # | 결정 | 비고 |
|---|---|---|
| a | 새 필드 이름(`expected_clear_rate_v1` 등) | 레벨 메타 스키마에 영구히 남음 |
| b | 백엔드 런타임에 lightgbm 추가 vs 순수 파이썬 예측기(D7, 문서 31) | 1단계 착수 전 필수 |
| c | 모델 artifact 저장 방식(git 포함 크기 vs 별도 배포) | |
| d | 봇 버전 고정값 — v2.3 vs v2.4 "규칙만"(문서 26 §11, 성능 동일) | 어느 쪽이든 379레벨 재측정 불필요 |
| e | 근거 부족 임계값 — 문서 31 §3-2 표를 그대로 쓸지, 병행 표시 단계에서 일부만 켤지(예: 1단계는 `NEAR_CEILING`·저신뢰만, 나머지는 2단계) | 범위를 좁히면 구현량 줄어듦 |
| f | `ProductionDashboard/index.tsx` 작업 착수 시점 — 다른 세션 커밋 대기 여부 | §5 |
| g | 표시 위치 1단계를 배치 표만으로 좁히는 것에 동의하는지(단건 뷰는 2단계) | §1 |

## 10. 범위 밖 (명시)

- 합격/불합격 판정 전환(D14) — 기존 `verification_passed` 경로 그대로.
- 게임 표시 난이도(xDifficulty) 변경, `ProductionExport.tsx`/`gboost.py`의 업로드 값 변경(트랙 B, D15 — 보류 상태 유지).
- `select` API(후보 순위·자동 선별), 생성기 반복 탐색 연동(§4-3류 안전장치).
- 라이브 검증(§5), 파일럿 29 연동(D12).

## 11. 구현 기록 — 1단계 (2026-10-16, 브랜치 `feature/clear-rate-display`, 워크트리 `TileMatchAutoLevel_wt_clearrate`)

> 승인 결정(마더 전달): (a) 필드 이름 §1 제안대로 (b) **순수 파이썬 예측기 — lightgbm 등 새 런타임 의존성 없음** (c) 모델 파일 git 포함 (d) 봇 v2.4 규칙 정합 6건(26dd967 `V24_DEFAULT`) + E1 재학습, 목표 ft_any (e) 경고: 예상·목표 <0.85 "신뢰 낮음", ≥0.95 "천장", 근거 부족은 **예측 대신 사유 표시**, placement_level 필수 (f) `ProductionDashboard/index.tsx` 는 다른 세션 커밋 뒤 (g) 배치 표만.
> 기존 `predicted_clear_rate`·`verification_passed`·업로드 값(`ProductionExport.tsx`·`gboost.py`)은 **건드리지 않았다.**

### 11-1. 파일
| 파일 | 내용 |
|---|---|
| `backend/app/core/clear_rate/features.py` | `residual_model.map_features`·`build` 의 48특징을 단건(맵, 배치 레벨, 봇 측정)으로 이식. numpy 없음, `app` import 없음(학습 스크립트가 파일 경로로 로드) |
| `backend/app/core/clear_rate/model.py` | artifact 로드 + Ridge 내적·트리 순회 예측(순수 파이썬). CQR 범위 → 확률 변환 |
| `backend/app/core/clear_rate/guard.py` | 문서 31 §3-2 코드 + 측정 조건 코드로 경고·신뢰도 |
| `backend/app/core/clear_rate/predict.py` | **순수 예측 함수** `predict_level` (최종 게임 조건 맵 + 조건 + 배치 + 봇 측정·메타 → 결과). I/O·캐시·UI 없음 |
| `backend/app/core/clear_rate/judge.py` | **판정 함수** `judge` (PASS/FAIL/INSUFFICIENT_EVIDENCE, 문서 31 §3-3). 라우트·기존 판정에 연결 안 함 |
| `backend/app/core/clear_rate/service.py` | 에디터 진입: level_json → 업로드 변환(최종 게임 조건) → 봇 측정(요청 → 캐시) → `predict_level` |
| `backend/app/api/routes/clear_rate.py`, `schemas.py`(클래스 추가만), `main.py`(import 1줄 + include 1줄) | `POST /api/clear-rate/predict` |
| `backend/scripts/train_clear_rate_model.py` | 재학습·평가·내보내기·활성화. `--check` = 재학습 결과가 저장본과 바이트 동일한지 |
| `backend/data/models/clear_rate/cr-ftany-v24r-20261016/{model.json 404KB, bot_cache.json 172KB, manifest.json}`, `active.json` | 모델·봇 캐시·출처 |
| `backend/tests/test_clear_rate.py`, `tests/golden/clear_rate_L237.json` | 24건 (L237 픽스처 = 라이브 샤드 맵 + 행 필드) |
| `frontend/src/api/clearRate.ts` | 요청·응답 타입(백엔드 1:1), `predictClearRate`, `toClearRateMeta`(응답 → 메타 새 필드) |
| `frontend/src/types/production.ts` | `ProductionLevelMeta` 새 필드만 추가(`mc_replaced_at` 뒤 — 다른 세션 미커밋 변경과 다른 위치) |
| `frontend/src/components/ClearRate/ClearRateCell.tsx` | 배치 표 1칸: 예상·80% 범위·신뢰도·경고 배지·무도움/도움 사용(보조). 메타 필드만 props 로 받음(독립 렌더) |

### 11-2. 모델 (문서 21 c+ 직접 구현 재사용)
- 점예측: `residual_model.Ridge`(내부 CV λ) + `residual_model.GBM`(250트리·깊이3) logit 평균. 헤드 3개: ft_any(판정 목표 ⑤), 보조 `unaided_lb`(무도움 LB)·`help_rate`(첫 시도 도움 사용률).
- 80% 범위: **CQR 순수 구현** — 직접 분위수 GBM(핀볼 손실, 잎 값 = 잎에 든 잔차의 α분위) q0.1/q0.9 + 내부 5겹 점수 E=max(lo−y, y−hi)의 80% 분위(유한표본 보정), 내부 분할 3개 점수 합침(한 분할만 쓰면 폴드별 폭이 logit 0.00~0.22로 흔들림).
- **천장 처리**: 학습 목표는 `residual_model.logit` 이 [0.01, 0.99]로 자른다(⑤ 레벨의 14.5%가 0.99 초과). 범위 끝이 이 자름값에 닿으면 확률 1.0(아래는 0.0)으로 표시한다 — 자름값 그대로 두면 포함률이 0.715로 낮게 나왔다(실제 0.995인 레벨이 상한 0.99 밖). 이 처리 후 0.818.
- 학습 데이터: `bot_v24/bot_v2.4f_no_rules_only.json`(규칙만 = 현재 기본값, 문서 26 §11-1) × 기존 AF `level_metrics.json` — **새 봇 측정 없음.** 레벨 집합은 `target_metric_eval.py` 와 같은 379레벨. 학습 스크립트가 런타임 `features.py` 로 만든 특징이 `residual_model.build` 와 **469레벨 전부 일치**하는지 단언한 뒤 학습한다.
- manifest: 봇 버전·설정·행 파일, 프로토콜 `theta4x128_v1`·시드 규칙, 샤드 커밋 `b741f6a3`(빌드 1.1.0), AF 기간(2026-09-08~10-14, level_metrics 생성 시각), 목표 정의, 학습 시각, K-fold 지표·기준선·게이트, model.json/bot_cache.json sha256, 순수 파이썬 vs numpy 최대 차이.

### 11-3. 재검증 (맵 해시 그룹 5겹 × 4반복, 379레벨, 반복 평균 ± sd)
| | MAE | 편향 | ρ | ±5%p | ±10%p |
|---|---|---|---|---|---|
| 기준선 v2.3 + E1(lightgbm, 26 §11-2) | 0.0320 (0.0001) | +0.0124 | 0.758 (0.008) | 0.838 | 0.930 |
| 참고 v2.4 규칙만 + E1(lightgbm) | 0.0320 | +0.0125 | 0.758 | 0.838 | 0.930 |
| **이번: v2.4 규칙만 + c+(순수 구현)** | **0.0311 (0.0001)** | +0.0113 | **0.763 (0.007)** | 0.844 | 0.934 |
- 동등 판정(반복 sd 기준, 사전 정의 |ΔMAE| ≤ 2·max sd, Δρ ≥ −2·max sd): ΔMAE −0.0009(허용 0.0010), Δρ +0.005(허용 −0.016) → **동등**. 게이트(MAE ≤0.035, ρ ≥0.72, 문서 31 D9 제안값) 통과.
- 구간별 MAE/ρ: 32-100 0.016/0.72 (n=29) · 101-300 0.028/0.75 (180) · 301-500 0.037/0.70 (170).
- 실제값 구간별(26 §11-9 재현): ≥0.96 MAE 0.014 · 0.92~0.96 0.024 · 0.85~0.92 0.040(편향 +0.029) · <0.85 0.120(편향 **+0.109**) → `LOW_CONFIDENCE` 근거 유지.
- 보조: LB MAE 0.078 / ρ 0.730, 도움 사용률 MAE 0.057 / ρ 0.681.
- 80% 범위(rep 0 OOF): 포함 **0.818**(32-100 0.83 · 101-300 0.84 · 301-500 0.79), 평균 폭 0.096(중앙 0.073), 상한이 1.0인 레벨 73%(천장), 점예측이 범위 안 0.995.
- 재현성: 학습은 결정적(고정 시드). `--check` 로 재학습 → model.json·bot_cache.json 바이트 동일(pytest 에 포함).

### 11-4. API (`POST /api/clear-rate/predict`) — 개정 2026-10-16(공통 예측 경로화, §11-7)
요청 `{level_json, placement_level?, bot_measurement?: {bot_version, protocol, condition_hash, seed_set?, rows[]}}` → 응답 `{model_version, target_metric, bot_version, bot_protocol, placement_level, condition_hash, status, in_support, insufficient_reasons[], evidence_flags[], expected_ft_any, range80_ft_any, expected_unaided_lb, expected_help_rate, confidence, measurement{source, bot_version, protocol, seed_set, condition_hash}, bot_unaided_win_rate{θ}}`. 판정(`verdict`)은 응답에 없다(`judge` 는 라이브러리로만 둠).
- **필드 이름으로 지표 분리**: `expected_ft_any`/`range80_ft_any` = 주 목표(실유저 첫 시도·도움 포함·종료된 판). `expected_unaided_lb` = 실유저 무도움 첫 시도 클리어 비율(LB) 예측. `expected_help_rate` = 실유저 첫 시도 도움 사용률 예측(**출력만**). `bot_unaided_win_rate` = 봇(도움 없이 플레이) θ별 승률 = 입력, 클리어율 아님.
- **입력 감사**: 특징은 맵 구조·기믹, 배치 위치(log L·구간·라이브 일정 기준 기믹 노출·첫 등장 표·보스=autoCollectCount 1~3), 봇 측정뿐이다. 그 레벨의 AF 값(도움 사용률·클리어율 등 출시 전에 알 수 없는 값)은 입력에 없다(manifest `input_audit`, 테스트 `test_no_post_release_inputs`).
- `status`: `ok` / `insufficient_evidence`(예측 대신 `insufficient_reasons`) / `measurement_required`(그 게임 조건의 봇 측정 없음). `in_support` = 판정에 쓸 수 있는지.
- 예측을 막는 경고(hard): `PLACEMENT_MISSING`, `LEVEL_OUT_OF_RANGE`(L32~500 밖), `GIMMICK_UNSEEN`/`GIMMICK_LOW_TRAIN`(학습 레벨 <10), `FEATURE_OOD`(학습 1~99분위 밖 특징 ≥2개), `BOT_PROTOCOL_MISMATCH`(버전·프로토콜·θ·판 수), `MEASUREMENT_MISSING`, **`MEASUREMENT_CONDITION_MISMATCH`**(측정한 게임 조건 해시 ≠ 현재), `UNSOLVED`(모든 θ 봇 클리어 0).
- 표시 경고(soft, 예상값 기준): `LOW_CONFIDENCE`(<0.85, 신뢰도 low), `NEAR_CEILING`(≥0.95), `GIMMICK_FIRST`/`NOVELTY_HIGH`(신뢰도 low), `GIMMICK_BOT_WEAK`(grass·chain, 신뢰도 medium). 목표값 경고(목표 <0.85·≥0.95·`TARGET_OUT_OF_SUPPORT`)는 `judge` 쪽으로 옮겼다.
- **측정 조건 해시** `condition_hash(game_map, conditions)`: 맵(층 수, 층별 col/row/타일) + 게임 동작 필드 `GAME_FIELDS` = useTileCount·unlockTile·autoCollectCount·randSeed·shuffleTile·typeImbalance·timea(빌드 샤드 행 키). 표시용 필드(tileSkin·배경·visualTileSeed·difficulty·rewardCoin)는 뺐다. 최종 게임 조건은 업로드 변환(`gboost._convert_to_townpop_format`: 타일 순서 정규화, **useTileCount 를 실제 타입 수로 재계산**) + 업로드 패널 기본 autoCollectCount 규칙(레벨 %10 == 0 → 3, 아니면 0)이다. 봇 캐시도 라이브 빌드 측정을 이 해시로 찾는다(메타: v2.4·theta4x128_v1·seed11M).
- 예시(라이브 3차 배치 L153): `status ok, expected_ft_any 0.9554, range80_ft_any [0.902, 1.0], expected_unaided_lb 0.793, expected_help_rate 0.161, confidence low, flags NOVELTY_HIGH·GIMMICK_BOT_WEAK·NEAR_CEILING, measurement {cache, v2.4, theta4x128_v1, seed11M, f4693509…}, bot_unaided_win_rate {θ0.55 0.305 … θ1.0 0.945}`.

### 11-5. 배치에 돌린 결과 (L32~500, 조건 해시 기준)
| 배치 | ok | 측정 필요 | 근거 부족 |
|---|---|---|---|
| 현재 에디터 3차 `batch_1789636723287` | **366** | 81 | 22 (전부 `FEATURE_OOD`) |
| 라이브 빌드와 같은 2차 `batch_1792056041502` | 396 | 50 (= 원래 봇 행이 없는 50레벨) | 23 |
- 3차의 측정 필요 81 = 봇 행이 없는 레벨 + 업로드 조건이 라이브와 다른 레벨(useTileCount 32·randSeed 1·timea 1, L32~79 는 라이브가 2차 맵). 이 조건들은 봇이 잰 적 없으니 측정 필요가 맞다. 처음 구현(맵 + 저장된 useTileCount 키)은 업로드가 useTileCount 를 재계산하는 것을 반영하지 못해 측정 필요를 139로 과대 계산했다.
- 3차 ok 366레벨 예상 p10/p50/p90 = 0.89 / 0.96 / 0.98. `NEAR_CEILING` 227 · `LOW_CONFIDENCE` 21 · 신뢰도 high 226 / medium 57 / low 83. L1~31·L501+ 는 전부 `LEVEL_OUT_OF_RANGE`.

### 11-6. 하지 않은 것 · 남은 단계
- **자동 봇 측정**: §1 MVP 에 없어 생략. 측정이 없는 맵은 `measurement_required` 로 응답한다. 측정 비용(512판/레벨)은 여전히 미측정.
- `FEATURE_OOD` 의 마할라노비스 거리 규칙(문서 31 §3-2 "또는")은 구현하지 않았다(48특징·379레벨, 공분산 특이). 특징 수 규칙만 쓴다 — 학습 레벨 자체에서 9/379(2.4%)가 걸린다.
- `POSITION_SHIFT`: 원래 위치 정보가 요청에 없어 구현하지 않음. 저장 필드 `clear_rate_placement_level` 로 나중에 비교 가능.
- 셀의 "목표 대비" 표시는 넣지 않았다 — 메타의 기존 `target_clear_rate` 는 봇 척도 목표곡선(td 0.5 → 0.32)이라 ⑤ 범위와 비교하면 뜻이 없다. 목표 비교는 `judge` 로만 한다(레벨 번호별 ⑤ 목표 곡선이 생기면 연결).
- 새 메타 필드는 §1 제안 7개 + `clear_rate_status`(측정 필요/근거 부족 구분)·`clear_rate_placement_level`(문서 31 §2-1 ② "위치를 함께 기록") 2개를 더했다.
- `judge` 의 P(목표 범위 안)는 80% 범위를 logit 공간 두 조각 정규분포로 근사한 값이다(10%/90% 점 = 범위 끝, 천장 쪽 끝이 1.0 이면 반대쪽 폭을 씀). 판정 임계(0.5)·폭(logit ±0.7)은 문서 31 D5·D6 제안값이고, ⑤ 기준 판정 재현(CQR 범위로 §4 선별 재현)은 아직 안 했다.
- **대시보드 연결(다음 단계)**: 다른 세션의 `ProductionDashboard/index.tsx` 변경이 커밋된 뒤, 이 브랜치를 리베이스하고 배치 표에 열 추가 → 각 레벨 `predictClearRate({level_json, placement_level: meta.level_number})` → `toClearRateMeta` 로 메타 저장 → `<ClearRateCell {...meta} />`. 그때 Playwright 웹뷰 확인(§6-3).
- 머지 시 주의: `backend/app/main.py` 는 다른 세션 미커밋 변경(`pv_play` 라우터)과 같은 위치 근처에 2줄 추가, `frontend/src/types/production.ts` 는 import 1줄 + 메타 필드 블록(다른 세션 변경과 다른 위치).

### 11-7. 생성·검증에서 재사용할 인터페이스 (`app.core.clear_rate`)
| 함수 | 입력 → 출력 | 비고 |
|---|---|---|
| `game_conditions(level_json, placement_level)` | → `(game_map, conditions)` 최종 게임 조건 | 업로드 변환 + autoCollectCount 기본 규칙. 생성기 후보도 이걸로 정규화 |
| `condition_hash(game_map, conditions)` | → 20자 해시 | 봇 측정 결과에 붙이는 태그. 측정 저장 시 함께 기록 |
| `BotMeasurement(bot_version, protocol, condition_hash, rows, seed_set, source)` | 측정 + 프로토콜 메타 | `seed_set` 으로 선별 시드 S / 확인 시드 C 구분(문서 31 §4-3) |
| `predict_level(model, game_map, conditions, placement_level, measurement, random_layout=)` | → `ClearRatePrediction` | **순수 함수.** 같은 입력 → 같은 출력(테스트). 해시 불일치·프로토콜 불일치·지원 범위 밖이면 숫자 없이 `insufficient_reasons` |
| `predict_editor_level(level_json, placement_level, bot_measurement=None)` | → `ClearRatePrediction` | 에디터/API 진입. 위 셋을 묶고 봇 캐시를 조회 |
| `judge(prediction, target, support, half_width_logit=0.7)` | → `ClearRateVerdict(verdict, reason, target, band, p_in_band, target_flags)` | PASS / FAIL / INSUFFICIENT_EVIDENCE. **기존 합격 판정(`verification_passed`, `/generate/validated`, 순차 검증)은 바꾸지 않았고 연결도 안 했다** |
| `load_model(version="")` | → `ClearRateModel`(manifest·model·bot_cache) | `model.model["support"]` 를 `judge` 에 넘긴다 |

이후 경로(목표 곡선 → 후보 생성 → 봇 측정 → 예측 → 선별 → 독립 시드 확인 → 레벨셋)에서 남은 것: 레벨 번호별 ⑤ 목표 곡선 입력(문서 31 D13), 봇 측정 실행기가 `condition_hash`·`seed_set` 을 붙여 측정을 저장하는 부분(θ 4개 × 128판 실행·시간 측정), 확인 시드 C 재측정 후 `judge` 를 C 측정으로 다시 돌리는 선별 규칙, ⑤ 기준 판정 재현.
