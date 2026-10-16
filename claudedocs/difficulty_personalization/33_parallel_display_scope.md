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
