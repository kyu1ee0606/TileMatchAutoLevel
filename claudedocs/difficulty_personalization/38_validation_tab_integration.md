# 38. 검증 탭 연동 — 실유저 예상 클리어율(A)·봇 가상 클리어율(B) 참고 판정 (2026-10-16)

> 브랜치 `feature/clear-rate-display` (워크트리 `TileMatchAutoLevel_wt_clearrate`). 설계 + 코드·테스트 코드 작성만 — **실행 검증 전부 보류**(tsc·pytest·node test·Playwright·서버 기동·봇 측정 0회). 근거: 문서 31(트랙 A), 33 §11~15, 35 §9(두 모드), 36 §8-3(P 과신, `_wt_lowband` 브랜치, 읽기만).

## 1. 범위와 불변 조건

- 새 화면 없음. 기존 **생산 대시보드 → `검증` 탭**(`ProductionDashboard/index.tsx:2448` `{ id: 'verify' }` → `BatchVerifyPanel`) 하단에 섹션 1개 추가.
- 불변: 활성 모델 `cr-ftany-v24r-20261016`(active.json 미변경), 운영 생성·기존 배치 검증(봇 매치 점수)·`verification_passed`·업로드 변환·게임 표시값, `predicted_clear_rate`. R1·R2 후보(`_wt_lowband`) 미연결.
- 판정식·임계값(`p_in_band`, 띠 logit ±0.7, P ≥ 0.5, confirm band `C`)·내부 필드명 불변. 바뀐 것은 **화면 문구**뿐(§4).
- 결과는 **저장하지 않는다**(세션 화면 상태만). 레벨 메타 저장은 `types/production.ts`·`productionStorage.ts` 수정이 필요한데 두 파일 모두 메인 작업트리에 다른 세션 미커밋 변경이 있음(§6) → 보류.

## 2. 화면 배치

```
[검증 탭]  BatchVerifyPanel (기존 그대로: 설정 · 진행률 · 통계 · 실패/재생성 목록 · 액션 버튼)
──────────────────────────────────────────────────────────────────────────
실유저 예상 클리어율 판정 (참고)        참고 표시 — 기존 배치 검증·verification_passed·업로드 값과 무관. 결과는 저장하지 않음.
[A 목표 실유저 클리어율 ___ % ][A 계산]       [B 봇 목표 성공률 ___ % ][B 계산]
A 판정: 합격 n · 불합격 n · 근거 부족 n
┌레벨(배치)┬목표──────────┬예상 실유저 클리어율(A)·범위·신뢰도┬목표 근접 지표(참고)┬A 판정·사유────┬봇 가상 클리어율(B)──────┬모델·봇·측정──────────┐
│ L237     │A 90%         │ClearRateCell 재사용               │0.62                │근거 부족       │BotVirtualCell 재사용     │모델 cr-ftany-…        │
│          │기존 목표(봇  │ 92.1% [86–96] 신뢰 높음 + 배지     │                    │확인 측정(C 시드)│봇 가상 — [실측 미검증]   │봇 v2.4 · theta4x128_v1│
│          │척도) 32% 회색│                                   │                    │없음            │봇 기준: 측정 부족        │측정 cache·시드 seed11M│
│          │              │                                   │                    │                │                          │·확인 측정(C) 없음     │
└──────────┴──────────────┴───────────────────────────────────┴────────────────────┴────────────────┴──────────────────────────┴───────────────────────┘
```

- A 열과 B 열은 **다른 칸**. B 칸은 미계산 상태에서도 회색 `실측 미검증` 배지가 보인다(`UnverifiedBadge`, 숨김 prop 없음, 초록 미사용).
- 목표: A 목표는 사용자가 입력(기본값 없음, 배치 전 레벨 공통 1값, 레벨 번호 = 배치 위치). 기존 `meta.target_clear_rate`는 봇 척도 목표곡선(문서 31 §2, td 0.5→0.32)이라 A 목표로 쓰지 않고 회색 "기존 목표(봇 척도)" 참고로만 표시.

## 3. 데이터 흐름

```
검증 탭 섹션 ─ getProductionLevelsByBatch(batchId)  (읽기만)
   │ [A 계산] 사용자 클릭 (자동 실행 없음)
   ├─ 레벨마다 순차 POST /api/clear-rate/target-eval
   │    {target_mode:'user_expected', target:A목표, level_json, placement_level:level_number, use_cached_measurement:true}
   │    → 백엔드: finalize_game_conditions → (S/C 없음) 모델 bot_cache[cond_hash] 조회(= /predict 와 동일) →
   │      experiment.evaluate_user_expected → select.verdict (불변)
   │    ← user_expected {prediction, verdict{verdict, reason, p_in_band, support_reasons, target_flags, bot_seed_confirmed}}
   │    → ClearRateCell(toClearRateMeta(prediction)) · 목표 근접 지표 · 판정 배지·사유 · 출처
   └─ [B 계산] 사용자 클릭 (A 결과와 무관, A 실패 시 자동 호출 없음)
        {target_mode:'bot_virtual', target:B목표, level_json, placement_level}  (측정 미첨부)
        ← bot_virtual (봇 실행 없음; 저장된 S/C 측정이 없으므로 BOT_MEASUREMENT_INSUFFICIENT 가 정상)
        → BotVirtualCell
```

- **백엔드 최소 추가 1건**: `ClearRateTargetEvalRequest.use_cached_measurement: bool = False`(opt-in). 기본값 False → 기존 요청 응답 바이트 동일. True + 모드 A + S/C 없음일 때만 `/predict`와 같은 캐시 조회. 캐시 시드 묶음은 `seed11M`(확인 묶음 `C` 아님) → 판정은 항상 `INSUFFICIENT_EVIDENCE`(`SELECTION_UNCONFIRMED`). 즉 검증 탭에서 **합격/불합격은 C 확인 측정이 공급될 때만** 나온다(현재 생산 레벨에 C 측정 저장 경로 없음 → 현 상태 화면은 "근거 부족 · 확인 측정(C 시드) 없음" 또는 "봇 측정 없음"이 정상). 모드 B는 이 플래그를 무시.
- 왜 /predict 와 target-eval 두 번이 아니라 target-eval 1회인가: 예측값과 판정이 같은 측정·같은 조건 해시에서 나와야 한다(두 호출이 다른 측정을 쓰면 표시 숫자와 판정 근거가 어긋남).
- 생산 신규 맵은 대부분 캐시 미스 → A 칸 `측정 필요`/`근거 부족(봇 측정 없음)`. 이것을 메우려면 봇 v2.4 측정(θ4×128) 실행이 필요 — 이번 범위 밖(실행 금지).

## 4. 상태별 표시 규칙

| 상황 | A 칸 (ClearRateCell) | 목표 근접 지표 | A 판정 | B 칸 | 출처 칸 |
|---|---|---|---|---|---|
| 미계산 | `미계산` | — | (없음) | `미계산` + 실측 미검증 배지 | (없음) |
| 캐시 미스(신규 맵) | `⏸ 근거 부족` + `봇 측정 없음` | — | 근거 부족 · 봇 측정 없음 | — | 측정 없음 · 시드 — · C 없음 |
| 지원 범위 밖(L501+, 냥이, 시간제한, 새 기믹 등) | `⏸ 근거 부족` + hard 배지 | — | 근거 부족 · (사유 코드 문구) | — | |
| 목표가 학습 범위 밖 | 숫자 표시 | 값 | 근거 부족 · 목표 범위 밖 | — | |
| 신뢰 낮음 | 숫자 + 신뢰 낮음 | 값 | 근거 부족 · 신뢰 낮음 | — | |
| 캐시 측정(seed11M) | 숫자·범위·신뢰도 | 값 | 근거 부족 · 확인 측정(C 시드) 없음 | — | cache · seed11M · C 없음 |
| C 측정 공급(향후) | 숫자 | 값 | 합격(초록) / 불합격(빨강) | — | request · C · C 있음 |
| B 측정 없음 | (A와 무관) | | | `봇 가상 —` + 실측 미검증 + `봇 기준: 측정 부족` | |
| B 측정 있음(향후) | (A와 무관) | | | `봇 가상 15% ±3.0%p` + 실측 미검증 + `봇 기준: 목표 충족/미충족`(중립색) | |
| API 오류 | `오류: <detail>` (빨강 글자) | — | — | 각 칸 독립 | |

## 5. 문구 사전 (표시만 — 필드·값·임계값 불변)

| 위치 | 기존 | 새 표시 | 내부(불변) |
|---|---|---|---|
| 판정 근거 수치 이름 | 목표 충족 확률 / (reason 원문) "목표 범위 안 확률" | **목표 근접 지표(참고)** (툴팁: "검증된 확률이 아님(현행 모델은 과신 경향 확인됨, 문서 36)…") | `verdict.p_in_band`, 임계 0.5, `select.py` reason 원문 |
| 근접 지표 값 형식 | (설계 문서상 "92.5%") | `0.93` (0~1 점수, % 미사용) | 동일 값 |
| A 판정 | PASS / FAIL / INSUFFICIENT_EVIDENCE | 합격 / 불합격 / 근거 부족 | enum 불변 |
| 사유 코드 | SELECTION_UNCONFIRMED (라벨 없음) | 확인 측정(C 시드) 없음 | 코드 불변 (기존 FLAG_LABEL 23개는 그대로, `clearRateLabels.ts`로 이동만) |
| 기존 목표 | target_clear_rate (표시 없음) | 기존 목표(봇 척도) N% (회색, 참고) | 값 불변 |

- reason 원문 치환은 화면(툴팁)에서만 `split/join` 문자열 치환. 백엔드 reason·파일럿 산출물 원문은 그대로.
- 라벨 상수: `frontend/src/components/ClearRate/clearRateLabels.ts` (`TARGET_PROXIMITY_LABEL`, `TARGET_PROXIMITY_TOOLTIP`, `LEGACY_PROXIMITY_TEXT`, `A_VERDICT_LABEL`, `FLAG_LABEL` …).

## 6. 다른 세션 파일과의 충돌 지점 (2026-10-16 확인)

| 파일 | 메인 작업트리(`feature/pv-seed-variants`) 상태 | 이번 처리 |
|---|---|---|
| `ProductionDashboard/index.tsx` (탭 구조) | **미커밋 수정**(+217/-) | 건드리지 않음. 탭 연결은 BatchVerifyPanel 내부에서 해결 |
| `ProductionDashboard/BatchVerifyPanel.tsx` | 변경 없음(메인=워크트리 동일) | import 1줄 + JSX 1줄 추가(파일 끝) |
| `types/production.ts`, `storage/productionStorage.ts` | **미커밋 수정** | 건드리지 않음 → 결과 저장 보류(§1) |
| `ClearRate/*`, `api/clearRate*.ts`, `routes/clear_rate.py`, `schemas.py` | 메인에 없음/무관 | 수정 |
- 병합 시 주의: `schemas.py` 는 메인 쪽 다른 변경과 같은 파일일 수 있음(현재 메인 미커밋 목록엔 없음). BatchVerifyPanel 은 병합 전 메인에서 다시 diff 확인.

## 7. 변경 파일

- `backend/app/models/schemas.py` — `use_cached_measurement` 필드 1개
- `backend/app/api/routes/clear_rate.py` — target-eval 모드 A opt-in 캐시 조회
- `backend/tests/test_clear_rate_experiment.py` — 테스트 4개(기본값 불변, 캐시는 확인 불가, 공급 측정 우선, B 불변)
- `frontend/src/api/clearRateTarget.ts` — 요청 필드·verdict 타입(support_reasons/target_flags) 추가
- `frontend/src/components/ClearRate/clearRateLabels.ts` (신규) — 라벨·문구 사전·순수 표시 함수
- `frontend/src/components/ClearRate/ClearRateVerifySection.tsx` (신규) — 검증 탭 섹션
- `frontend/src/components/ClearRate/ClearRateCell.tsx` — FLAG_LABEL 을 라벨 모듈에서 import (값 동일)
- `frontend/src/components/ClearRate/BotVirtualCell.tsx` — `UnverifiedBadge` export
- `frontend/src/components/ProductionDashboard/BatchVerifyPanel.tsx` — 섹션 삽입
- `frontend/tests/clearRateLabels.test.ts` (신규) — node 내장 test (의존성 추가 없음, tsc 대상 밖)

## 8. 실행 검증 계획 (승인 후, 아직 1회도 실행 안 함)

1. 타입: `cd frontend && npx tsc --noEmit`
2. 프런트 단위: `cd frontend && node --experimental-strip-types --test tests/clearRateLabels.test.ts` (node 22.6+)
3. 백엔드: `cd backend && python -m pytest tests/test_clear_rate_experiment.py tests/test_clear_rate.py -q`
4. API 수동: `curl -s -XPOST localhost:8000/api/clear-rate/target-eval -H 'content-type: application/json' -d @<L237 골든 + use_cached_measurement:true>` → `measurement.source=cache`, `verdict=INSUFFICIENT_EVIDENCE`, `bot_seed_confirmed=false`
5. Playwright(MCP) 시나리오:
   1. `browser_navigate http://localhost:5173` → 생산 대시보드 → 배치 선택 → `검증` 탭
   2. `clear-rate-verify-section` 존재, 기존 배치 검증 UI 변화 없음 확인(스냅샷 비교)
   3. A/B 버튼 비활성(목표 미입력) 확인 → A 목표 `90` 입력 → `cr-run-A` 클릭 → `cr-a-counts` 표시 대기
   4. 각 행: A 칸 숫자 또는 근거 부족, `목표 근접 지표(참고)` 헤더 툴팁 문구, 판정이 `합격/불합격` 아닌 `근거 부족`(캐시) 확인
   5. B 칸이 미계산일 때도 `실측 미검증` 배지 보임, B 실행 후 `봇 기준: 측정 부족`, 초록 클래스 없음
   6. A 계산이 B 칸을 바꾸지 않고, B 계산이 A 칸을 바꾸지 않음
   7. 기존 `verification_passed`·업로드 미리보기 값 불변(검증 전후 내보내기 탭 비교)

## 9. 남은 결정 (마더/사용자)

- C 확인 측정을 생산 레벨에 공급·저장하는 경로(봇 측정 실행 + 메타 필드) — 없으면 검증 탭 A 판정은 계속 "근거 부족".
- 결과 저장(레벨 메타) 여부 — `types/production.ts` 다른 세션 커밋 후.
- A 목표를 레벨별 목표 곡선(문서 31 D13)으로 입력할지 — 현재 배치 공통 1값.

## §재개 메모(검증탭2) — 2026-10-16 일시중지 (맥 재시작)

> 2차 작업(C 확인 측정 연결 / 결과 저장·복원 / 레벨별 목표 곡선) 착수 직후 사용자 지시로 중단. **코드 변경 0줄** — 이 커밋은 재개 메모만 담는다. 실행(테스트·tsc·빌드·봇 측정) 0회.

### 기능별 상태

| 기능 | 상태 | 내용 |
|---|---|---|
| 1. C 확인 측정 연결 | **미착수** (읽기만 완료) | 재사용 대상 확인: `measure.py` `measure/measure_cached/MeasurementStore`(키 = cond_hash\|protocol\|seed_band\|bot_config_hash), `SEED_BANDS`(seed11M·S·C·S2·P2·S2B·C2·S3·C3), `PROTOCOLS`(theta4x128_v1 = A 모델 프로토콜), `guard.bot_flags`(버전·프로토콜·cond_hash·판 수 검사), `select.verdict(confirm_bands=...)`, 테스트 `test_seed_bands_do_not_overlap`·`test_seed_bands_avoid_other_experiments`(외부 대역 1–9.1M·13M·23M). 백엔드 비동기 작업 API·검증 탭 전용 C 대역 미추가 |
| 2. 결과 저장·복원 | **미착수** | `productionStorage.ts`·`types/production.ts` 는 메인 작업트리에 다른 세션 미커밋 변경 → 별도 모듈(`ClearRate/clearRateStorage.ts` 등)로 분리 예정. 구조 미확인(IndexedDB 스토어 패턴 읽기 전) |
| 3. 레벨별 목표 곡선 | **미착수** (조사 중) | 문서 31 §3-3 규칙 7·D13(레벨 번호별 계단식 목표 곡선, td→TARGET_CLEAR_CURVE 봇 척도 사용 금지) 확인. 기존 곡선 구현 후보: `types/production.ts:153,160` `target_clear_rates`/`target_clear_rate`(봇 척도 — A 목표로 변환 금지), `api/leveling.ts` `/leveling/difficulty-curve`, `models/leveling_config.py`, `routes/tune.py`, `rl_sim.py` TARGET_CLEAR_CURVE — 구조 재사용 가능 여부 미판정 |

### 작성한 파일
- 이 절(문서 38 §재개 메모) 1건뿐. 코드·테스트 파일 없음.

### 재개 시 다음 순서
1. 메인 `git status`/`git diff --stat` 재확인(다른 세션 index.tsx·productionStorage.ts·types/production.ts 커밋 여부 — 커밋됐으면 레벨 메타 필드 직접 추가 재검토).
2. 기존 곡선 구현(`leveling_config.py`, `api/leveling.ts`, `tune.py`) 읽고 A 목표 곡선 데이터 구조 결정(구간 규칙 + 개별 레벨 override, 우선순위 override > 구간, 경계 포함 규칙 명시).
3. `productionStorage.ts` 저장 패턴 확인 → 별도 `clearRateStorage.ts`(측정 참조·요약 + 평가 결과 분리, 무효화 키 = cond_hash·bot_config_hash·protocol·model_version·judge_version·target_curve_hash).
4. 백엔드: 검증 탭 C 전용 시드 대역 추가(레지스트리 확장 + 충돌 테스트), 측정 종류(탐색/C) 명시 필드, 비동기 작업(작업 ID·상태·취소) 라우트 연결 코드 + 테스트.
5. 프런트: 실행 상태(미측정/대기/측정 중/완료/실패/취소/오래됨)와 판정 분리 표시, 실행 전 확인 화면, 중복 실행 잠금.
6. 문서 38 갱신 + 재시작 후 검증 체크리스트·명령·예산(맵 1개 × C 512판 등) → 로컬 커밋.

### 다른 세션 파일 충돌 처리 현황
- 메인 작업트리(`feature/pv-seed-variants`) 미커밋: `ProductionDashboard/index.tsx`, `ProductionExport.tsx`, `storage/productionStorage.ts`, `types/production.ts`, `main.py` 등 — **이번에 아무것도 건드리지 않음**.
- 참고: 문서 33·35·36·37 은 이 워크트리에 없음(35·37 메인, 36 `feature/clear-rate-lowband`).

### 남은 결정 (마더/사용자)
- C 확인 측정 시드 대역: 검증 탭 전용 새 대역 할당(예: 22M대 — 외부 23M과 간격 검사 필요) vs 기존 C/C2/C3 재사용 금지 확인.
- 결과 저장 위치: 레벨 메타 필드 추가(다른 세션 커밋 후) vs 별도 저장소(IndexedDB 별 스토어/백엔드 파일).
- 목표 곡선 저장 범위: 배치 단위 vs 프로젝트 전역.
