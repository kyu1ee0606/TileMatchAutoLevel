# 35. 목표 곡선 → 생성·선별·검증 연결 최소 변경 계획 (조사·계획만)

> 작성 2026-10-16 · 브랜치 `feature/pv-seed-variants` · **코드·봇 측정·라이브 변경 없음. 문서만.**
> 최상위 목표: 레벨 번호별 **목표 유저 성공률 곡선**을 넣으면, 생성·선별·검증한 레벨셋의 **라이브 실측 성공률이 그 곡선에 가깝게** 나온다. 봇을 사람처럼 만드는 것은 목표가 아니다. 현 규칙 정합 봇(v2.4 규칙만, 머지 `26dd967`)과 보정 모델(E1)을 흐름에 연결하는 것이 우선이다.
> 근거: 31(설계·결정 D1~D17), 33(병행 표시 범위), 34(분포: E1 sd가 실제의 57%, 실제 <0.85에서 +12%p), 26 §11(v2.4 최종·신뢰 범위), 29(파일럿), 10 §9-12(업로드 후처리), 워크트리 `TileMatchAutoLevel_wt_clearrate`(읽기만).
> 현재 승인 범위 유지: 기존 `predicted_clear_rate`·합격 판정(`verification_passed`)·업로드 값·게임 표시 난이도는 **바꾸지 않는다**. 이 계획의 새 값은 전부 **새 필드**로만 쌓는다.

## 0. 요약

| 항목 | 결론 |
|---|---|
| 병행 표시(D17) 진행 | 워크트리에 **커밋 없음**(HEAD = `7d32d71`, 이 브랜치와 같은 기준). 미커밋으로 백엔드 예측 모듈·API·학습 스크립트·모델 산출물(v2.4 규칙만, 379레벨)·테스트·프론트 API 클라이언트·메타 타입까지 있음. 배치 표 열(`ClearRateCell.tsx`·`ProductionDashboard` 통합)은 아직 없음(§1) |
| 공통 예측 경로 | `app/core/clear_rate.predict()` 하나를 생성·선별·검증·표시 모두가 쓴다. 이 계획은 그 위에 **조건 해시·측정 함수·선별/판정 함수**만 더한다(§3) |
| 워크트리에서 발견한 연결 공백 4건 | ① 10의 배수 레벨(냥이 `autoCollectCount=3`) **학습 0레벨**인데 경고 없이 예측 ② `useTileCount`를 업로드가 재계산하는 값과 다르게 씀 ③ 요청으로 받은 봇 측정이 그 맵·조건에 묶이지 않음 ④ `timea>0` 학습 0레벨인데 경고 없음(§1-2, §4). 병행 표시 세션에 전달 필요 |
| 지금 구현 가능 | 조건 해시·측정 조건 일원화(값 불변), 측정 함수(S/C 시드 분리), 선별·판정 순수 함수, 목표 곡선 스키마, 오프라인 선별 스크립트(샌드박스 출력), 목표 vs 예측 곡선 표시(§5) |
| 실측 부족으로 보류 | 판정 전환(D14), 목표 <0.85 구간 판정, 위치 이동 효과, 냥이·시간제한 레벨 판정, 라이브 적중 주장 전부(§5-2) |
| 낮은 성공률 | 35a **대기**(파일 없음). 기존 데이터 범위(학습 <0.85 40레벨, 최저 0.37)에서 시작해 단계적 확장. 내부 테스트는 라이브 검증이 아니다(§2, §6) |
| 대규모 재측정 | 필요 없음(모델은 v2.4 행으로 이미 학습됨). 확장용 측정만: 냥이 레벨 부족분(41레벨은 θ0.85·1.0만 측정됨, 26 §6) + 501~1000 77레벨 ≈ 5.3만 판, 단일 워커 약 0.3~0.7시간(§8) |

## 1. 병행 표시 작업 현재 완료 범위 (워크트리 git log·파일 확인 사실만)

### 1-1. 상태
- 워크트리 `/Users/casualdev/TileMatchAutoLevel_wt_clearrate`, 브랜치 `feature/clear-rate-display`. `git log` 최상단 = `7d32d71`(문서 33 커밋). **이 작업의 커밋은 아직 없다.** 아래는 전부 미커밋 파일이다(2026-10-16 확인).
- 테스트는 이번에 실행하지 않았다(측정·무거운 프로세스 금지). "통과" 여부는 미확인.

| 파일 | 상태 | 내용(읽은 사실) |
|---|---|---|
| `backend/app/core/clear_rate/features.py` (144줄) | 신규 | E1 48특징을 단건 입력으로 이식, 순수 파이썬. `map_hash` = 층 수 + 층별 col/row/tiles의 sha256 앞 16자 |
| `.../clear_rate/model.py` (93줄) | 신규 | 산출물 로드·예측(순수 파이썬 Ridge + 트리 순회, numpy·lightgbm 불필요 — D7은 순수 파이썬 쪽으로 구현됨). 80% 범위 = 분위수 GBM + CQR |
| `.../clear_rate/guard.py` (107줄) | 신규 | 31 §3-2 경고 코드. 억제(숫자 대신 사유) = `PLACEMENT_MISSING`·`LEVEL_OUT_OF_RANGE`·`GIMMICK_UNSEEN/LOW_TRAIN`·`FEATURE_OOD`(1~99분위 밖 ≥2개)·`BOT_PROTOCOL_MISMATCH`·`UNSOLVED`. `LOW_CONFIDENCE`(<0.85)·`NEAR_CEILING`(≥0.95)·`TARGET_OUT_OF_SUPPORT`. **PASS/FAIL 판정 없음**(D17 요건대로) |
| `.../clear_rate/service.py` (96줄) | 신규 | `predict(level_json, placement_level, target, bot_measurement)`. 봇 측정 출처 = 요청 → 모델 캐시(학습 맵, 키 `map_hash:useTileCount`) → 없으면 `measurement_required`(자동 측정 없음) |
| `backend/app/api/routes/clear_rate.py` (21줄) | 신규 | `POST /api/clear-rate/predict` |
| `backend/app/models/schemas.py` | +64줄 | `ClearRatePredictRequest/Response` 등 |
| `backend/app/main.py` | +2줄 | 라우터 등록 |
| `backend/scripts/train_clear_rate_model.py` (453줄) | 신규 | 학습·내보내기·`--check` 재현 |
| `backend/data/models/clear_rate/cr-ftany-v24r-20261016/` | 신규 | manifest 6KB · model 410KB · bot_cache 176KB, `active.json`이 이 버전 지정. manifest: `target_metric=ft_any_v1`, `bot_version=v2.4`(규칙만), `bot_protocol=theta4x128_v1`, 시드 규칙 `11,000,000 + level_index*1000 + game`, 샤드 `b741f6a3`, AF 2026-09-08~10-14, **n_levels 379** |
| `backend/tests/test_clear_rate.py` (17개 테스트), `tests/golden/clear_rate_L237.json` | 신규 | 학습-서빙 특징 일치, 결정성, 플래그, API |
| `frontend/src/api/clearRate.ts` (81줄) | 신규 | 타입 + `predictClearRate` + `toClearRateMeta` |
| `frontend/src/types/production.ts` | +13줄 | 메타 새 필드 `expected_clear_rate_v1`·`clear_rate_range80`·`clear_rate_confidence`·`clear_rate_evidence_flags`·`unaided_lb_expected`·`help_rate_expected`·`clear_rate_model_version`·`clear_rate_status`·`clear_rate_placement_level` |
| `frontend/src/components/ClearRate/ClearRateCell.tsx`, `ProductionDashboard` 열 | **없음** | 미착수(문서 33 §5대로 다른 세션 커밋 대기로 보임) |

### 1-2. 이 계획과 연결할 때 걸리는 점 (워크트리 코드 기준, 수정은 그 세션 몫)
| # | 사실 | 결과 | 제안 |
|---|---|---|---|
| G1 | 학습 준비(`bot_v2x/prep.json`)는 `autoCollectCount>0` 레벨을 `cat_help`로 **전부 제외**(L32~500의 10의 배수 47레벨 전부). 그래서 학습 특징 `is_boss`의 1·99분위 = 0·0. 서비스는 `is_boss = L%10==0`으로 넣지만 OOD는 "2개 이상"이라 이것 하나로는 억제 안 됨 | **10레벨마다 1개(배치의 10%) 지원 밖 예측이 경고 없이 숫자로 나감** | `CAT_HELP_UNSUPPORTED`(hard) 추가. 지원 확장은 §6 E2 |
| G2 | 서비스는 `level_json.useTileCount`를 캐시 키·특징에 씀. 업로드 컨버터(`gboost.py:423-449`)는 실제 타일 종류 수로 **다시 계산한 값**을 게임에 보냄 | 저장값이 낡은 레벨은 측정·예측 조건 ≠ 게임 조건 | 측정·예측 모두 §4의 최종 조건 함수 출력을 입력으로 |
| G3 | 요청 `bot_measurement`는 버전·프로토콜만 검사하고, **어떤 맵·조건으로 잰 값인지** 묶지 않음 | 다른 맵(재생성 전 맵 등)의 측정값으로 예측 가능 | 측정 결과에 `cond_hash` 기록, 불일치 시 `BOT_CONDITION_MISMATCH`(hard) |
| G4 | `timea>0`(시간 제한) 레벨도 학습에서 제외(`time_limit`, 1레벨) — 경고 없음 | 시간 제한 레벨은 지원 밖 | `TIME_LIMIT_UNSUPPORTED`(hard) |

## 2. 낮은 성공률 데이터 — **35a 대기**
- 문서 35a(저성공률 데이터 인벤토리, 다른 세션 작성 중)는 이 문서 작성 시점에 **파일이 없다.** 완료 후 이 절을 갱신한다.
- 그때까지 확인된 사실(기존 문서):
  - E1 학습 379레벨 중 실제 ⑤ <0.85 = **40레벨**(최저 0.37). 이 구간 MAE 0.127, 편향 +0.118(쉽게 예측), ±5%p 적중 0.20(26 §11-9).
  - E1 분포 폭이 실제의 57%, p5 0.80 vs 0.86(34).
  - 구간별 학습 목표 p5~p95: 101-300 [0.790, 0.997] · 301-500 [0.803, 0.996] · 32-100 [0.915, 0.996](모델 support). 즉 **0.79 미만 목표는 현재 `TARGET_OUT_OF_SUPPORT`로 보류된다.**
  - 학습에 없는 라이브 레벨: 냥이 47레벨(L%10) — 이 중 41레벨은 v2.4 θ0.85·1.0 × 128판만 측정됨(26 §6 `item_cat_v24f.json`·`item_cat_rules.json`, θ0.55·0.65 없음). 501~1000은 AF는 있으나 봇 측정 없음(77레벨, 31 §1-5).

## 3. 생성·검증 연결 — 최소 변경 설계

### 3-1. 현행 경로 (코드 확인)
| 경로 | 위치 | 하는 일 | 새 흐름에서 |
|---|---|---|---|
| 단건 생성 | `generate.py:1072` `/api/generate` → `_generate_level_impl`(`:1091`) | td·기믹 언락·레벨 번호로 맵 1개 | **그대로 재사용**(후보 생성기) |
| 검증 생성 | `generate.py:1496` `/generate/validated`, `calculate_target_clear_rates`(`:846`), `calculate_match_score`(`:946`), 통과 = `use_best_match`/fallback 항상 통과 | 봇별 성공률 vs 봇별 목표 | **안 씀**(새 판정과 섞지 않음, 31 §3-3-6) |
| RL 스윕 | `rl_sim.py:263` `/api/rl-sim/level`, `mc_difficulty.population_clear_rate`(`:67`, θ 평균 0.47 고정 가중), `TARGET_CLEAR_CURVE`(`:60`), `|gap|≤0.12` → `verification_passed`(`:312`). 기본 봇 `v1`, 격자 `[0,0.15,…,1.0]` | 봇 값 = 클리어율로 직접 비교 | **유지**(승인 범위). 새 흐름의 입력으로 쓰지 않는다 — 모델 프로토콜(v2.4, θ 0.55/0.65/0.85/1.0 × 128)과 다름 |
| 프로덕션 순차 처리 | `ProductionDashboard/index.tsx:738` `computeSequentialPassThreshold`, `:5240-5300`(match_score = 100−2×|gap|, 라운드 시드 = round), `:5585-5641` 2차 패스(best-of 선택 후 `verification_passed: true`) | 레거시 판정·재생성 루프 | **유지**. 새 흐름은 별도 단계로 붙인다(파일이 다른 세션 수정 중 — 통합은 그 커밋 뒤) |
| 업로드 전 RL 일괄 측정 | `ProductionExport.tsx:802-830` | `predicted_clear_rate` 없는 레벨을 RL로 채움 | 유지 |
| 배치 저장 | `production_store.py:438` `PUT /batches/{id}`(낙관적 버전, 델타 병합, meta 자유 필드) | 레벨 메타 저장 | 새 필드 저장에 그대로 사용(스키마 변경 불필요) |

### 3-2. 새 흐름과 단계별 함수
```
목표 곡선 TargetCurve(level → ⑤ 목표, 폭)                                   [신규 스키마]
 → 후보 생성: 같은 레벨 번호·언락으로 /api/generate N회(td 격자 × 시드)      [기존 재사용]
 → 최종 게임 조건 확정 finalize_game_conditions(level_json, slot)           [신규, §4]
 → 탐색 측정 S: measure(cond, seed_band=S) = v2.4 θ4×128                    [신규 measure.py]
 → 예측 clear_rate.predict(cond, placement_level, measurement)              [워크트리 공통 경로]
 → 선별 select(candidates, target): hard 경고 제외 → 점수 = |logit p̂ − logit t| + λ·(80% 폭) → 상위 k  [신규 순수 함수]
 → 확인 측정 C: measure(cond, seed_band=C) → 재예측(C 값만)                  [같은 함수]
 → 판정 verdict(pred_C, target): PASS / FAIL / INSUFFICIENT_EVIDENCE       [신규 순수 함수, 31 §3-3]
 → 레벨셋: 새 메타 필드에만 기록(target·S/C 예측·판정·cond_hash·model_version)
 → 표시: 목표 곡선 vs 예측 곡선(80% 띠) vs (있으면) 실측                   [신규 컴포넌트]
 → 실플레이 검증(파일럿 하니스, §6) → AF 실측 → 재학습(train_clear_rate_model.py)
```
원칙 반영:
- **원시 봇 성공률 ↔ 유저 목표 직접 비교 없음**: 선별·판정 함수의 입력 타입이 `ClearRatePredictResponse`뿐이다. 봇 성공률은 `bot_success_reference`(참고)로만 지나간다.
- **탐색 S / 확인 C 시드 분리**: `measure()`가 `seed_band`를 필수 인자로 받고 결과에 기록. 판정 함수는 `seed_band=="C"`가 아니면 `SELECTION_UNCONFIRMED`(hard)로 보류. 시드 대역: 학습 = 11.0M 규칙(manifest), DDA 사용 7.6M·7.8M·(제안)8.2M과 겹치지 않게 **S = 13.0M대, C = 14.0M대** 제안(결정 필요).
- **선택 편향 보정**: ① 폭 벌점 λ(31 §4-1: 0.25에서 ±5%p 적중 0.37→0.44) ② 판정은 C 재측정 예측으로만 ③ S→C 예측 이동(평균)을 배치 리포트에 기록 — 평균 감소 >1%p면 선별 압력 과다 경보(31 §4-3) ④ 선택된 후보의 OOD 점수 분포 vs 전체 후보 비교.
- **학습 범위 밖 = 근거 부족**: guard의 억제 코드 + G1·G4 신규 코드 + `TARGET_OUT_OF_SUPPORT`.
- **중복 없음**: 특징·예측·경고는 워크트리 모듈만 쓴다. 측정은 학습 데이터를 만든 스크립트(`bot_af_L32_500.py` `level_layouts`·`run_task`, `bot_v24_eval.py`)의 로직을 **앱 모듈로 옮기고 스크립트가 그것을 import**하게 해 한 곳으로 모은다(학습 측정 = 서빙 측정 동일 보장, 골든 테스트로 확인).

### 3-3. 파일·함수 단위 변경 목록
| # | 파일 | 함수/내용 | 신규/수정 | 충돌 위험 |
|---|---|---|---|---|
| 1 | `backend/app/core/clear_rate/conditions.py` | `finalize_game_conditions(level_json, slot_number, upload_opts) -> dict`(§4 표의 게임 영향 필드 확정), `cond_hash(final) -> str` | 신규 | 없음 |
| 2 | `backend/app/core/clear_rate/measure.py` | `measure(final, *, seed_band, bot_version="v2.4", protocol="theta4x128_v1") -> {rows, cond_hash, seed_band, bot_version, protocol}`. 고정/런타임 랜덤 배치 판별·레이아웃 샘플링은 `bot_af_L32_500.level_layouts` 이식, 냥이(`auto_collect`) cfg는 최종 조건에서 | 신규 | 없음 |
| 3 | `backend/app/core/clear_rate/select.py` | `score(pred, target, lam)`, `select(cands, target, k)`, `verdict(pred_C, target) -> PASS/FAIL/INSUFFICIENT_EVIDENCE`(31 §3-3 규칙, p_in = 80% 범위 logit 정규 근사) | 신규 | 없음 |
| 4 | `.../clear_rate/guard.py` | `CAT_HELP_UNSUPPORTED`, `TIME_LIMIT_UNSUPPORTED`, `BOT_CONDITION_MISMATCH`, `SELECTION_UNCONFIRMED` 추가 | 수정(워크트리 커밋 후) | 워크트리 세션과 조율 |
| 5 | `.../clear_rate/service.py` | 입력을 `finalize_game_conditions` 출력으로, 캐시 키 = `cond_hash`, 요청 측정의 `cond_hash` 검사 | 수정(같음) | 같음 |
| 6 | `backend/app/models/schemas.py` | `TargetCurve`, `ClearRateSelectRequest/Response`, 측정 결과 스키마. 예측 요청은 `extra="forbid"`(§A-2) | 새 클래스만 추가 | 낮음 |
| 7 | `backend/app/api/routes/clear_rate.py` | `POST /api/clear-rate/measure`(비동기 작업), `POST /api/clear-rate/select`, `GET /api/clear-rate/model` | 수정(워크트리 커밋 후) | 낮음 |
| 8 | `backend/scripts/clear_rate_select_batch.py` | 배치 파일 **사본**을 읽어 레벨별 후보 생성→S→선별→C→판정, 결과를 샌드박스 JSON으로. 라이브 배치·서버 데이터 무변경 | 신규 | 없음 |
| 9 | `backend/scripts/bot_af_L32_500.py`·`bot_v24_eval.py` | 측정 로직을 #2 import로 교체(동작 동일, 골든 비교) | 수정 | 낮음(분석 스크립트) |
| 10 | `backend/tests/test_clear_rate_pipeline.py` | 조건 해시(필드 변경 시 해시 변함/무관 필드 불변), 업로드 후처리 미러 일치(§4), measure 결정성·학습 행 재현(379 중 표본), select/verdict 규칙, S/C 분리 강제 | 신규 | 없음 |
| 11 | `frontend/src/api/clearRate.ts` | select/measure 타입·호출 | 수정(워크트리 커밋 후) | 낮음 |
| 12 | `frontend/src/components/ClearRate/TargetCurveChart.tsx` | 레벨 번호 x축: 목표 곡선(폭 띠) · 예측(80% 띠) · 레거시 `predicted_clear_rate`(회색 "봇 추정 참고") · AF 실측(있으면) | 신규 | 없음 |
| 13 | `frontend/src/components/ProductionDashboard/index.tsx` | 목표 곡선 입력(구간·계단식) + 차트 import + 열(#1-1의 `ClearRateCell`과 함께) | 수정 | **높음** — 다른 세션 미커밋 변경 커밋 후 |
| 14 | `frontend/src/types/production.ts` | 메타 새 필드: `target_ft_any`, `target_band`, `clear_rate_s`, `clear_rate_c`, `clear_rate_verdict`, `clear_rate_cond_hash`, `clear_rate_seed_bands` | 수정 | 중간(워크트리·다른 세션 모두 수정 중) |

바꾸지 않는 것: `rl_sim.py`·`mc_difficulty.py`·`generate.py` 판정·`computeSequentialPassThreshold`·`ProductionExport.tsx`·`gboost.py`(업로드 값). 레거시 판정은 계속 돌고, 새 판정은 옆 필드로만 쌓인다.

### 3-4. A. 목표 지표 강제 방법 (스키마)
| 규칙 | 강제 방법 |
|---|---|
| 주 목표 = ⑤ 첫 시도·도움 포함·종료 판(no_end 제외) | `TargetCurve.metric: Literal["ft_any_v1"]`. 다른 값이면 422. 모델 manifest `target_metric`과 다르면 `BOT_PROTOCOL_MISMATCH`와 같은 수준의 hard |
| 보조 = 무도움 LB 예상·도움 사용률 예상·no_end 비율 | 응답 `aux`(LB·help_rate는 모델 헤드 있음). no_end는 모델 헤드 없음 → 위치 구간 AF 평균을 `aux.no_end_rate_segment`(참고)로. **판정 함수 시그니처에 aux가 들어가지 않는다** |
| 무도움 봇 성공률과 혼용 금지 | 봇 값 필드명은 `bot_success_reference`만, 목표·예상 필드와 다른 타입. 선별·판정 함수는 이 필드를 읽지 않는다(테스트로 고정) |
| 출시 전 알 수 없는 값 입력 금지 | 예측 요청 모델 `model_config = {"extra": "forbid"}` — `help_rate_observed`·`actual_clear_rate` 같은 키가 들어오면 422. 위치 특징의 노출(exposure)은 **그 위치 앞 라이브 일정**에서 서버가 계산(요청으로 받지 않음) |
| 배치 레벨 번호 필수 | `placement_level`·`TargetCurve.points[].level` 필수. 둘이 다르면 `PLACEMENT_MISSING`(31 §3-2). 메타에 `clear_rate_placement_level` 저장, 옮기면 재예측(측정 재사용) |
| 대상 유저 조건 | `TargetCurve.population: Literal["all_reached_v1"]`(레벨 도달 전체 유저, Android+iOS, 판 재구성 버전 — D3). 구간별 목표는 받지 않음 |
| 슬롯(무한 사본) | 무한 모드 사본은 `slot_number`가 다르므로(냥이·코인 위치 기준, `ProductionExport.tsx:856-870`) 별도 예측 대상. 원본 예측을 사본에 복사하지 않음 |

## 4. D. 측정 맵 = 실제 실행 맵

### 4-1. 측정 조건 vs 게임 조건이 어긋날 수 있는 지점 (전수, 코드 확인)
| 필드 | 게임에 가는 값이 정해지는 곳 | 게임 동작 영향 | 현재 측정과의 차이 | 해시 포함 |
|---|---|---|---|---|
| map(층·좌표·타일·효과·컨테이너) | 저장 `level_json` → `gboost._convert_to_townpop_format` | 있음 | 정규화 순서는 `canonical_map`으로 같음 | O |
| `useTileCount` | **업로드 시 실제 타일 종류 수로 재계산**(`gboost.py:423-449`) | 있음(t0 분배 색 수) | 서비스는 저장값 사용(G2) | O(재계산값) |
| `randSeed` | 저장값 그대로(`:465`) | 런타임 랜덤 배치(t0·개수만 컨테이너) 분배 | 학습 측정은 랜덤 배치 레벨을 레이아웃 시드 1..N 샘플로 잼(`bot_af_L32_500.level_layouts`). 고정 시드 해석이 게임과 같은지는 정본(DESIGN_LEVEL_MAP_SCHEMA §4-1) 확인 필요 | O |
| `shuffleTile`·`unlockTile`·`typeImbalance` | 저장값 그대로 | 분배·잠금 | 측정이 `unlockTile`·`shuffleTile`은 반영, `typeImbalance`는 `shuffle_empty_tiles` 인자로 넘기는지 확인 필요 | O |
| `autoCollectCount`(냥이) | **프론트 업로드에서만** `slot%10==0 → 3`, 그 외 0(기본 모드 `multiples10`, `ProductionExport.tsx:856-890`). 저장본엔 없음 | 있음(뱃지 3장 자동 수집) | 생성·RL 측정은 저장본(대개 0)으로 잼 → **보스 레벨은 측정 조건 ≠ 게임 조건**. 학습엔 0레벨(G1) | O(최종값) |
| `timea` | 저장값(`timeAttack`/`timea`) | 있음(시간 제한) | 봇은 시간 개념 없음, 학습 제외(G4) | O |
| `max_moves` | 게임엔 안 감(게임은 독 7칸 규칙) | 봇 이동 예산만 | 순차 처리가 `computeMaxMoves`로 자가 교정(`index.tsx:5228-5237`) | X(봇 내부, 프로토콜에 고정) |
| `rewardCoin` | 업로드 시 고정 5(기본) | 없음(보상) | — | X |
| `difficulty`(표시 난이도) | `round(predicted_clear_rate×100)` 또는 −1 | 플레이 동작 없음(팝업·문구만) | — | X(단, 표시가 유저 행동에 줄 영향은 트랙 B 범위) |
| `visualTileSeed` | 있으면 그대로 | 스프라이트만(배치 고정 후 리맵) | — | X |
| `shuffleLayer`·`teleportRandSeed`·`useTeleportInRandomizer`·`useInRandomizer` | 저장값 | 텔레포트·랜덤 | 측정 반영 여부 확인 필요 | O(보수적으로 포함) |
| 게임 쪽 후처리(DDA 시드 변형 등) | 게임 런타임 | 있음 | 파일럿 레벨은 변형 맵 기준 별도 측정 필요(29) | 레벨 목록에서 제외 표시 |

### 4-2. 설계
- `finalize_game_conditions(level_json, slot_number, upload_opts)`: 위 표의 "게임에 가는 값"을 **업로드와 같은 규칙**으로 계산한 dict. 측정·예측은 이 출력만 입력으로 받는다.
- `cond_hash` = 정규화 map + 표의 "해시 포함" 필드(최종값)의 sha256. 측정 결과·예측 결과·레벨 메타 모두에 기록.
- **무효화**: 표시·판정 시 현재 레벨의 `cond_hash`를 다시 계산해 저장값과 다르면 예측을 `stale`로 표시하고 판정 숫자를 숨긴다(재측정 필요). 업로드 직전 검사 목록에 "조건 해시 불일치 레벨 수"를 정보로만 추가(차단 아님 — 업로드 동작 변경은 승인 범위 밖).
- **D16과의 관계**: D16은 업로드 후처리(코인·냥이·표시 난이도)를 백엔드 함수 하나로 옮기자는 안이다. 이 계획은 그 함수의 "게임 동작에 영향 주는 부분"(냥이·useTileCount 재계산)을 **먼저 측정 쪽에서만** 쓰고, 프론트 업로드 로직과 같은 결과를 내는지 테스트로 묶는다(값 불변). 프론트 업로드가 이 함수를 호출하도록 바꾸는 것(= D16 본체)과 표시 난이도 부분(D15)은 **별도 승인**. 그 전까지 두 구현이 공존하므로 미러 테스트가 드리프트 방지 장치다.

## 5. 지금 구현 가능 vs 보류

### 5-1. 지금 가능 (새 필드·샌드박스만, 기존 판정·업로드 불변)
| 항목 | 전제 |
|---|---|
| 조건 해시·최종 조건 함수·미러 테스트(§4) | 없음 |
| `measure.py`(S/C 대역) + 학습 측정 스크립트 공용화 | 골든: 기존 v2.4 행 재현(표본 레벨) |
| guard 신규 코드 4개(G1~G4 대응), select/verdict 순수 함수 | 워크트리 커밋 후 그 위에 |
| 목표 곡선 스키마·`select` API·배치 오프라인 스크립트 | 결과는 샌드박스 JSON |
| 목표 vs 예측 곡선 차트 | `ProductionDashboard` 통합은 다른 세션 커밋 후 |
| 오프라인 생성 후보 평가(31 §4-3): S→C 이동, OOD 쏠림, 다른 모델 버전 불일치율 | 절대 정확도 주장 없음 |

### 5-2. 실측 부족으로 보류
| 항목 | 막는 것 |
|---|---|
| 판정 전환(D14): 레거시 `verification_passed` 대신 새 판정 | 신규 생성 맵 라이브 검증 없음(379 재현은 기존 맵 안 선택) |
| 목표 <0.85 판정(현재 `LOW_CONFIDENCE`, <0.79는 `TARGET_OUT_OF_SUPPORT`) | 학습 40레벨, +12%p 편향 |
| 냥이(10의 배수)·시간 제한 레벨 판정 | 학습 0레벨(§6 E2로 일부 해소) |
| 위치 이동 효과(같은 맵 다른 위치) | 맵-위치 1:1 학습, 실험 없음 |
| 신규 맵 목표 적중률 수치 약속 | §6 E3·§7 독립 검증 전 |
| 게임 표시 난이도·업로드 값 변경 | 트랙 B·D15·D16 보류 |

## 6. E. 낮은 성공률 구간 확장 — 단계

| 단계 | 내용 | 표본·기간(개략) | 완료 조건 | 승인 |
|---|---|---|---|---|
| E0 | 표시만: <0.85 `LOW_CONFIDENCE`, 미검증 예측임을 셀에 명시 | — | 워크트리 병행 표시 완료 | D17 범위 |
| E1 | 봇으로 낮은 성공률 후보 생성·측정(오프라인). 결과는 "봇 측정·미검증 예측"으로만 저장. 유저 보정 아님 | 레벨 30 × 후보 20 × 512판(§8) | S/C 이동·OOD 쏠림 리포트 | 불필요(샌드박스) |
| E2 | **기존 라이브 데이터 범위부터 확장**: 학습에서 빠진 냥이 47레벨의 부족분(41레벨 θ0.55·0.65, 6레벨 전체)을 v2.4 + 냥이 cfg로 측정 → 학습 포함(보스 지원). 냥이 레벨은 측정 설정 사이 ρ가 0.21~0.47로 흔들림(26 §11, n=41) → 포함 후 보스 레벨만 따로 게이트, 501~1000 77레벨 측정 → 지원 범위 확장 검토, 35a가 찾은 저성공률 실측 레벨 추가 | 약 5.3만 판(§8). 재학습 수 초 | 같은 맵-그룹 K-fold에서 기존 게이트(MAE·ρ) 악화 없음, <0.85 구간 편향 재측정 | 측정은 불필요, 모델 활성 전환은 사용자 |
| E3 | **제한 실플레이**: 파일럿 29 종료 후, 같은 하니스(해시 50:50, `pilot_arm`)로 **L101~300**에서만, 원맵 대조. 목표 0.75~0.85 맵 6~10레벨. **L1~100 신규 유저 구간에는 고난도 맵 배포 금지.** 내부 QA 플레이는 라이브 검증으로 세지 않음(행동 확인용) | 101-300 군당 4주 n≈214 → p≈0.8에서 레벨 95% CI 반폭 약 ±5.4%p. 레벨 묶음(8개) 평균 편향 SE ≈ 2%p | 사전 등록(목표·예상·80% 범위·모델 버전·판정, 결과 보기 전 해시 고정), 가드레일(그 레벨 이탈·D1, 29 §6 규칙) 위반 없음 | **필요**(라이브 배포·게임팀) |
| E4 | 학습용 / 독립 검증용 맵 분리: E3 맵을 맵 그룹 기준 2:1로 나눠, 검증용은 선별·λ 조정·재학습에 쓰지 않음 | E3 종료 후 1주 | 재학습 모델로 **검증용 신규 맵**의 목표 적중률·포함률 보고(§7) | 모델 활성 전환은 사용자 |
| E5 | 31 §5 2차(30레벨·4주, 목표 0.80/0.88/0.95)로 확대 | 4주 + 준비 1~2주 | §7 판정 지표 | **필요** |

파일럿 29 연결: ① 29 결과 열기 전 변형 21맵의 E1 예측을 `addenda`로 고정(D12, 변형 맵 v2.4 측정 21×512 ≈ 1.1만 판). 변형 맵은 "학습에 없던 맵" 점이지만 **원맵 구조가 학습에 있으므로 같은 맵 그룹 → 완전 독립 검증으로 세지 않는다**(§7-3). ② E3·E5는 29 종료 후, 레벨 비중첩(29 §7).

## 7. F. 검증 기준

### 7-1. 지표 (모두 ⑤ 기준, 레벨 단위, 구간 <0.85 / 0.85~0.92 / 0.92~0.96 / ≥0.96 별로)
| 지표 | 정의 | 주의 |
|---|---|---|
| MAE·편향 | 예측 − 실측 | 천장 구간 MAE는 작게 보임 → 구간별로만 비교 |
| 순위상관 ρ | 구간 안 Spearman | 변별력의 주 지표(31 §1-5: 구간 평균 기준선은 ρ≈0) |
| 목표 적중률 | 실측이 목표 ±5%p / ±10%p / logit ±0.7 안 | 무작위 선택 기준선과 함께(31 §4-4) |
| 80% 구간 포함률 | 실측이 range80 안 | 목표 0.75~0.85, 실측 잡음 포함 기대 포함률과 비교 |
| 보정 기울기 | logit 실측 ~ logit 예측 | 1에서 크게 벗어나면 재학습 |
| 승자의 저주 | 선택 맵의 실측 − 확인(C) 예측 평균 | 재현 예상 −1~−3%p |
| 곡선 패턴 | 레벨 번호 x축에 목표·예측·실측; 구간별 평균 차, 계단(어려운 레벨) 위치 일치율 | 시각 + 수치 병기 |
| 표본·불확실성 | 레벨별 n과 Wilson CI, 레벨 묶음 bootstrap CI | n<100 레벨은 레벨 단위 지표에서 제외·별도 표기 |

### 7-2. 두 종류 검증을 분리 보고
| 종류 | 데이터 | 이름 |
|---|---|---|
| 기존 맵 교차검증 | 379레벨 맵-그룹 K-fold OOF, 그 안에서 고른 선별 재현 | "오프라인 재현"(31 §1-5·§4-4). **"독립 검증"이라 부르지 않는다** — 같은 379레벨에서 λ·폭·게이트를 반복 탐색했다 |
| 신규 생성 맵 독립 검증 | E3·E5 검증용 맵(학습·선별 규칙 조정에 미사용, 사전 등록) | "독립 검증" — 이 수치만 신규 맵 성능 주장에 쓴다 |

### 7-3. 맵 그룹 정의 (학습/검증 누수 방지)
- **구조 해시**: 층 수·좌표·효과·컨테이너 구조만, **타일 타입 배정 제외**. 근거: 라이브 샤드 vs 에디터 LIVE3 불일치 34레벨 중 33레벨이 타입 배정만 다름(29 §2-1).
- 같은 레벨의 시드 변형(DDA `seedvar`), 같은 맵의 위치 이동본, 무한 모드 사본 → 같은 그룹.
- 같은 템플릿·패턴(`pattern_index`)에서 나온 생성 맵은 우선 다른 그룹으로 보되, 구조 해시가 같으면 묶는다. 근사 중복(구조 유사도) 기준은 구현 시 표본 검토 후 정한다.
- 그룹 단위로 K-fold·학습/검증 분할. 현재 학습 스크립트의 `kfolds`(map-hash 그룹)는 타입 배정을 포함한 해시인지 확인 필요 — 포함이면 구조 해시로 교체.

## 8. 단계별 완료 조건·승인 / 봇 측정 비용

### 8-1. 단계
| 단계 | 내용 | 완료 조건 | 승인 |
|---|---|---|---|
| P0 | 워크트리 병행 표시 커밋 + G1~G4 반영 | 워크트리 테스트 통과, tsc, Playwright로 열 확인 | 진행 중(D17) |
| P1 | 조건 해시·최종 조건·measure(S/C) | 미러 테스트(프론트 업로드 규칙과 동일), 학습 행 재현 골든 | 불필요(값 불변) |
| P2 | select/verdict·목표 곡선 스키마·API·오프라인 배치 스크립트 | 단위 테스트, curl, 샌드박스 1개 배치(예: L101~130) 리포트 | 불필요 |
| P3 | 차트·목표 곡선 입력·열(ProductionDashboard) | tsc·Playwright(CLAUDE.md 필수 절차) | 다른 세션 커밋 후 착수 |
| P4 | E2 측정·재학습·모델 활성 전환 | 게이트 악화 없음 | **사용자**(활성 전환) |
| P5 | E3 제한 실플레이 | 사전 등록·가드레일 | **사용자·게임팀** |
| P6 | 판정 전환(D14)·업로드 일원화(D16)·표시 난이도(D15) | §7 독립 검증 결과 | **각각 별도 승인** |

### 8-2. 봇 측정 비용 (추정 — 판당 시간은 26 §6 측정 0.020~0.044 s/판/워커 사용)
| 작업 | 판 수 | 단일 워커 | 워커 3 |
|---|---|---|---|
| 379레벨 재측정 | **불필요**(모델이 v2.4 규칙만 행으로 학습됨) | — | — |
| E2 냥이 부족분(41×2θ×128 + 6×512) + 501~1000 77레벨(×512) | ≈ 1.4만 + 3.9만 ≈ 5.3만 | 약 0.3~0.7 h | 약 0.1~0.25 h |
| 파일럿 21 변형 addenda | 1.1만 | 약 4~8 분 | — |
| 생성 배치 30레벨 × 후보 20 (S) + 상위 3 (C) | 30×23×512 ≈ 35만 | 약 2~4.3 h | 약 0.7~1.5 h |
| 같은 배치 2단 측정(64판 거르기 → 상위 5만 512판, 31 §6) | 30×(20×64+5×512+3×512) ≈ 16만 | 약 0.9~2 h | 약 0.3~0.7 h |
| 전체 프로덕션 배치(~500레벨) 2단 측정 | ≈ 270만 | 약 15~33 h | 약 5~11 h |
- 랜덤 배치 레벨은 레이아웃 샘플만큼 판이 나뉠 뿐 총 판 수는 같다. 판당 시간은 맵 크기·θ에 따라 다르므로 P1에서 실측해 이 표를 갱신한다.
- 메모리: 26 §11 측정 때 스왑 35~36 GB/36.8 GB 포화(다른 측정 동시 실행)였다. 워커 3 이하, DDA 측정과 동시 실행 금지, 배치 단위 체크포인트(재개 가능) 권장. 전체 배치 측정은 야간 작업으로 분리.

## 9. 결정 필요 (이 계획 신규)
| # | 결정 | 제안 |
|---|---|---|
| P-a | S/C 시드 대역 | S 13.0M대, C 14.0M대(학습 11.0M·DDA 7.6/7.8/8.2M과 비중첩) |
| P-b | 선별 폭 벌점 λ·후보 수 N·확인 상위 k | λ 0.25, N 20, k 3(31 §4-1 기반 시작값, 오프라인 재현으로 조정 — 조정에 쓴 데이터는 독립 검증에서 제외) |
| P-c | G1~G4 대응을 워크트리 1단계에 넣을지 | 넣는 것을 권장(10레벨마다 지원 밖 숫자 노출 방지) |
| P-d | 측정 조건에 포함할 필드 목록(§4-1 "확인 필요" 3건) | 정본 확인 후 확정 |
| P-e | E2 측정 범위(냥이 부족분·501~1000 77) | 진행 권장, 활성 전환은 게이트 후 |
| P-f | E3 제한 실플레이 레벨·목표 | 파일럿 29 종료 후 별도 제안서 |
