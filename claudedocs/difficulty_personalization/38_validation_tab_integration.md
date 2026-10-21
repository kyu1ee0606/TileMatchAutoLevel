# 38. 검증 탭 연동 — 실유저 예상 클리어율(A)·봇 가상 클리어율(B) 참고 판정 (2026-10-16)

## 최신 인계 — 2026-10-16 19시경: 개선 요약 및 경량 검증 범위

이 절은 현재 상태 요약이다. 아래 1차 화면 예시 및 일시중지 메모는 이력이며, 2차 구현 상태는 §10~§16을 따른다. 이번 기록 작업에서는 실행 검증을 하지 않았다.

### 현재까지 개선한 봇·예측·생성 흐름

- **봇 규칙 정합:** 문서 26 최종 §11 기준 v2.4는 규칙 정합 6건을 기본으로 하고 행동 개선 후보는 기본에서 제외한다. 가려진 정보 취급·게임 규칙 대응을 개선했으나, 1차 목표(ft_any, 첫 시도·도움 포함)의 예측 정확도가 v2.3보다 유의하게 개선됐다고 결론 내리지 않는다. 중간 실험 성과와 최종 채택을 혼동하지 않는다.
- **예측 목표 분리:** 원시 봇 성공률을 실유저 클리어율로 사용하지 않는다. A는 AF 기반 실유저 예상값, B는 봇 가상 성공률이며 B에는 실측 미검증을 명시한다. 활성 모델은 `cr-ftany-v24r-20261016`을 유지한다.
- **생성→측정→선별:** 목표에 맞는 후보 탐색 및 독립 확인 시드 측정 경로를 마련했다. 문서 33 §15의 A90 파일럿은 독립 확인 후 예상 약 93.1%까지 접근했다. 이는 모델 예측값이지 신규 맵 라이브 실측 93.1%라는 의미가 아니다.
- **85% 및 저구간 한계:** 현 활성 모델·신뢰 기준 조합에서는 85% 합격 영역이 없다는 진단이 나왔다. 생성 횟수를 늘리는 것만으로 해결하지 않는다. 저구간 점예측 후보 및 범위 후보 R1/R2는 다른 구간 성능 또는 사전 기준을 충족하지 못해 미채택이다. 범위 기준 재설계는 승인 전 초안이며 기준 완화로 합격을 만들지 않는다. 상세 근거는 `_wt_lowband`의 문서 36.
- **검증 탭 2차 코드 작성 완료:** C 준비·조건 고정·명시 실행·상태/취소·완료 판정, 별도 IndexedDB 요약 및 서버 측정 원본 저장/복원, 배치별 목표 곡선 UI가 연결됐다. 곡선 우선순위는 개별 레벨 > 10레벨 주기 > 구간. 목표 변경과 측정 무효화를 구분한다. 코드 작성 완료와 실행 검증 완료는 별개다.
- **남은 한계:** B 확인 측정 미구현, 목표 곡선은 배치 단위, 서버 재시작 시 실행 중 작업은 중단 상태 처리. 실제 C 실행 성능·취소 및 서버 복구·실제 UI 저장 복원은 아직 검증하지 않았다.

### 자원 관측과 다음 검증 제한

2026-10-16 18:55~18:56 KST 읽기 전용 관측: RAM 32GiB, 메모리 압박 값 2(경고), 스왑 약 52.7GiB, 압축 메모리 점유 약 16GiB, 디스크 여유 51GiB, 가동 36일. 약 17초간 스왑 읽기 약 145MiB, 스왑 사용량 약 152MiB 감소. 짧은 관측으로 지속적인 자원 부족을 확정하지 않는다. macOS 재시작은 필수 기능 요건이 아니다.

사용자 전달용 경량 검증 범위(이 문서 작성 시 실행하지 않음):

1. 기존 서버가 어느 checkout을 서비스하는지 먼저 확인한다. main 서버를 임의 종료·재시작하거나 병합하지 않는다. 2차 코드 제공 서버가 없고 추가 서버가 필요하면 별도 승인 요청.
2. 단일 브라우저/소규모 테스트 배치에서 UI 연결, 목표 입력·미리보기·적용·경계·누락·우선순위, 새로고침 후 목표/기록 복원만 확인한다. 운영 배치·기존 사용자 저장 데이터는 덮어쓰거나 초기화하지 않는다.
3. C는 준비/확인 화면까지. 실제 실행 버튼 및 측정 생성 API 호출 금지. fixture를 이용하면 별도 테스트 저장소/컨텍스트에서만 사용하고 실제 C 완료 또는 실제 보상·라이브 성과로 보고하지 않는다.
4. 목표 변경→재평가 필요, 맵/배치 위치/봇 조건 변경→측정 무효, 모델/기준 변경→평가 오래됨, 과거 합격 회색 표시를 경량 fixture로 확인한다. 실제 서버 작업 복구는 미검증으로 남긴다.
5. 탭 진입·목표 변경·새로고침 시 새 측정 요청이 없는지 확인한다. 기존 측정 작업 폴링과 신규 작업 생성을 구분한다.
6. 대량/소량을 불문하고 신규 봇 측정(512판 포함), 생성 탐색, 모델 재학습, 전체 테스트/빌드, Unity 추가 실행, QA 복제, 캐시 삭제는 이번 범위 밖이다. 문서 §14의 전체 검증 명령을 일괄 실행하지 않는다.
7. 자원을 전후 비교하고 압박 악화·스왑 증가 지속·UI 응답 저하 시 중단한다. PASS/FAIL/미검증 및 fixture/실데이터 경로를 구분하여 보고한다.

근거: [봇 v2.4](26_bot_v24.md), [생성 파일럿](33_parallel_display_scope.md), 본 문서 §10~§16; 범위/저구간 후보는 `/Users/casualdev/TileMatchAutoLevel_wt_lowband/claudedocs/difficulty_personalization/36_lowband_candidates.md`에 보존. 이 기록은 모델 교체·기준 변경·커밋·푸시 승인이 아니다.

> 브랜치 `feature/clear-rate-display` (워크트리 `TileMatchAutoLevel_wt_clearrate`). 설계 + 코드·테스트 코드 작성만 — **실행 검증 전부 보류**(tsc·pytest·node test·Playwright·서버 기동·봇 측정 0회). 근거: 문서 31(트랙 A), 33 §11~15, 35 §9(두 모드), 36 §8-3(P 과신, `_wt_lowband` 브랜치, 읽기만).

## 1. 범위와 불변 조건

- 새 화면 없음. 기존 **생산 대시보드 → `검증` 탭**(`ProductionDashboard/index.tsx:2448` `{ id: 'verify' }` → `BatchVerifyPanel`) 하단에 섹션 1개 추가.
- 불변: 활성 모델 `cr-ftany-v24r-20261016`(active.json 미변경), 운영 생성·기존 배치 검증(봇 매치 점수)·`verification_passed`·업로드 변환·게임 표시값, `predicted_clear_rate`. R1·R2 후보(`_wt_lowband`) 미연결.
- 판정식·임계값(`p_in_band`, 띠 logit ±0.7, P ≥ 0.5, confirm band `C`)·내부 필드명 불변. 바뀐 것은 **화면 문구**뿐(§4).
- ~~결과는 저장하지 않는다~~ → **2차(§10~§16)에서 변경**: 검증 탭 전용 저장소(별도 IndexedDB + 백엔드 측정 저장소)에 저장·복원. 레벨 메타(`types/production.ts`·`productionStorage.ts`)는 여전히 건드리지 않는다(§13).

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

---

# 2차 구현 (검증탭2, 2026-10-16 재개) — C 확인 측정 · 저장·복원 · 레벨별 목표 곡선

> 코드·테스트 코드 작성까지만. **실행 0회**(pytest·node test·tsc·빌드·Playwright·서버 재시작·봇 측정 모두 안 함). 커밋: `4ef96cc`(백엔드 C 작업) → `0381bbd`(목표 곡선) → `24ec6d2`(검증 탭 UI·저장·복원) → 문서 커밋. 사용자 흐름: **레벨별 A 목표 설정 → (A 탐색 계산) → C 확인 측정 준비·확인·실행 → C 판정 → 저장 → 새로고침 후 복원**.

## 10. C 확인 측정 연결

### 10-1. 탐색 vs C (타입·필드·API 구분)
| | 탐색(exploration) | C 확인(confirm) |
|---|---|---|
| 출처 | 모델 `bot_cache`(seed11M 학습 행), 파일럿 대역(S·C·S2·P2·S2B·C2·S3·C3), 요청에 실은 측정 | 서버가 **CV 대역**으로 잰 기록만 (`confirm.ConfirmJobManager`) |
| API | 기존 `POST /api/clear-rate/target-eval` (`use_cached_measurement`) — 응답 불변 | `POST /api/clear-rate/verify/evaluate {job_id,…}` — 응답 `measurement_kind:"confirm"` + `provenance` |
| 판정 | 항상 `INSUFFICIENT_EVIDENCE`(SELECTION_UNCONFIRMED) | `select.verdict(confirm_bands=("CV",))` — 임계·식 불변 |
| 화면 | `[탐색]` 라벨, 버튼 "A 탐색 계산(캐시 측정·C 아님)" | `[C 확인]` 라벨, 버튼 "C 확인 측정 준비" → "C 판정" |
- **C 판정 측정 원자료는 요청에서 받지 않는다** — 서버 저장소에서 `job_id`로 읽고 `meta.measurement_kind=="confirm"` + `seed_band=="CV"` 를 다시 확인. seed11M 캐시·탐색 기록은 C 로 승격될 경로가 없다.
- 프런트 `normalizeRecord`도 `measurement_kind=confirm` 이면서 `seed_band=CV`·`job_id` 가 있을 때만 C 로 읽는다(이전 데이터 승격 금지).

### 10-2. 시드 대역 (레지스트리 확장 + 충돌 검사)
- `measure.SEED_BANDS["CV"] = 22_000_000` (검증 탭 C 전용, 탐색·학습·파일럿이 쓰지 않음). 사용 범위 = 22,000,000 + layout×1000 + game ≤ 22,031,511(32 레이아웃·θ당 최대 512판) — 외부 23M(자연실험)과 968,489 간격.
- `confirm.BAND_PURPOSE`: 등록된 모든 대역의 용도. `confirm.band_registry_problems()`: 대역끼리·외부 대역(pv 1–9.1M, 13M, 23M)과 겹침 + 용도 미등록 검사 — **submit 때마다 호출, 문제 있으면 거부**. 기존 테스트 `test_seed_bands_do_not_overlap`·`test_seed_bands_avoid_other_experiments`가 CV 도 자동 포함.
- 같은 맵·조건을 다시 재면 같은 시드 → 같은 결과(결정적). 그래서 완료 C 는 재사용만 하고 재측정하지 않는다.

### 10-3. 작업 흐름 (백엔드 `core/clear_rate/confirm.py`, 라우트 `/api/clear-rate/verify/*`)
```
POST /verify/plan   {items:[{level_json, placement_level, map_id, batch_id}]}     봇 실행 없음
   → 맵별 cond_hash · bot_config_hash · job_key(=cond_hash|protocol|CV|cfg_hash) · games_planned(512)
     · blocking(SUPPRESS 구조 코드: 측정해도 판정 불가) · warnings(저신뢰 구조 코드) · existing(기존 작업)
[화면 확인 패널] 대상 맵 n · 새로 측정 n · 예상 판수 · 동시 실행 상한 2 · 재사용/진행 중/제외 · "C 측정은 봇 측정 재현성 확인이며 실유저 클리어율 독립 검증이 아님"
POST /verify/jobs   {…, target_mode:"user_expected", expected_cond_hash}       사용자 [실행] 클릭 시만
   거부: 모델 bot_version/protocol/θ/판수 ≠ measure (PROTOCOL_MISMATCH 409) · 시드 대역 충돌 · cond_hash 불일치(CONDITION_CHANGED 409)
         · 학습 지원 밖 입력(UNSUPPORTED_INPUT 422) · target_mode 없음/bot_virtual (422)
   같은 job_key 진행 중 → 그 작업 반환(reused="active") · 완료 C 있음 → 반환(reused="done", 재측정 없음)
   → 데몬 스레드, BoundedSemaphore(2) — 초과분은 queued
GET  /verify/jobs/{id} · POST /verify/jobs/query {job_ids}                       상태 조회(측정 아님)
POST /verify/jobs/{id}/cancel     queued → 즉시 cancelled / running → cancel_requested, 현재 θ 행 끝나고 cancelled
POST /verify/evaluate {job_id, target, level_json, placement_level}             완료 작업만(JOB_NOT_DONE 409)
   현재 맵·조건·배치로 cond_hash·bot_config_hash 재계산 → 다르면 MEASUREMENT_INVALIDATED(409)
POST /verify/target-check {items:[{placement_level,target}]}                    목표 판정 가능 여부(user_expected_precheck)
GET  /verify/info                                                                 model_version · judge_version · 프로토콜 (봇 실행 없음)
```
- 측정 실행: `measure.measure(..., seed_band="CV", should_stop, on_row)` — 공용 측정 함수 그대로(θ 행 사이 취소·진행 콜백만 추가, 기본 동작 불변). 결과는 `MeasurementStore`(공용 저장 형식, 파일 `backend/data/clear_rate_verify/measurements.json`)에 `meta.measurement_kind="confirm"`, `job_id`, `measured_at` 을 붙여 저장.
- 완료 인정 조건: cond_hash·bot_config_hash·대역·프로토콜·봇 버전 일치 + **판수 = 계획 판수(512)** + 취소 요청 없음. 하나라도 어긋나면 failed/cancelled, 저장 안 함.
- 실패: 오류 문자열 기록, **재시도 없음, 다른 맵 재선택 없음, B 전환 없음**. 서버 재시작: `jobs.json` 로드 시 queued/running → failed(`interrupted`), 부분 판수는 표시만.
- 스레드 실행 트레이드오프: 봇 시뮬은 순수 파이썬 → GIL 때문에 동시 2개도 한 코어를 나눠 씀(느림). 프로세스 풀은 θ 행 중간 취소가 어려워 택하지 않음. 취소 반응 시간 = 진행 중 θ 행 1개(128판) 소요 시간.

### 10-4. UI 실행 상태 (판정과 별도 칸)
`미측정 / 대기 / 측정 중 / 완료 / 실패 / 취소 / 결과 오래됨(완료 작업인데 요청 때와 맵·배치가 다름)` + 진행 판수, `취소 요청됨`, 오류 문구. 실패·취소에는 "(완료 C 아님)". 판정 칸은 `합격/불합격/근거 부족` + `[탐색]/[C 확인]` + 유효성.
- 측정 요청은 확인 패널의 [실행]뿐. 탭 진입·복원·목표 수정은 저장 상태 읽기·작업 상태 조회·`/verify/info`·(미리보기 버튼 시) target-check 만 한다.
- 중복 방지: 버튼은 진행 중 비활성 + 맵·cond_hash 잠금(`confirmLockKey`) + 서버 job_key 단일화(이중 안전).
- C 판정은 [C 판정] 버튼(측정 없음): 완료 C 이고 맵이 그대로이며 목표가 있는 레벨만 평가.

## 11. 레벨별 A 목표 곡선 (`ClearRate/targetCurve.ts`)
- 기존 곡선 구조 재사용: `leveling_config.calculate_level_difficulty` 의 **구간(PhaseConfig.level_range) + 10레벨 톱니 위치((L-1)%10, SAWTOOTH_PATTERN_10)** 모양. 값은 A 목표(ft_any)만. 문서 31 §3-3 규칙 7 예시("L101~300 10레벨마다 0.80, 나머지 0.95") = 구간 `101–300 95%` + 주기 `10 / 위치 10 / 80%`.
- 적용 규칙: **개별 레벨 > 주기 > 구간 > 목표 미설정**. 구간 경계는 양 끝 포함. 주기 위치 = ((L-1) % period) + 1 (위치 10 = 10의 배수 레벨).
- 입력 검사: 목표 0%<t<100%(백엔드와 동일), 시작≤끝, 정수, 구간 겹침 = 오류(중복), 주기 위치 1~period·중복 금지, 개별 레벨 중복·누락 = 오류. 목표가 없는 레벨은 오류가 아니라 "목표 미설정"(기본값 없음).
- [미리보기]: 레벨별 목표·출처(개별/주기/구간)·"입력 가능"과 "현 모델로 신뢰 판정: 가능 / 불가(사유)"(target-check = `user_expected_precheck`: 목표<85% LOW_CONFIDENCE, 구간 학습 p5~p95 밖, L32~500 밖) — **값을 올리거나 B 로 바꾸지 않는다**.
- [적용]: 곡선 저장(version+1, 해시 `tc-…`) → 기존 판정은 "재평가 필요"로만 표시. 측정 자동 실행 없음. 운영 곡선 값 설정·레벨 메타 일괄 변경 없음(배치 곡선만, 검증 탭 저장소).
- B 봇 목표는 별도 데이터(`targets` 의 `${batch}|B`, 단일값). `meta.target_clear_rate`(봇 척도)는 회색 참고 표시만, A 로 변환하지 않는다.

## 12. 저장 형식 · 무효화
### 12-1. 위치
| 데이터 | 위치 | 비고 |
|---|---|---|
| C 측정 원자료(θ 행) | 백엔드 `data/clear_rate_verify/measurements.json` (MeasurementStore 키 `cond_hash|protocol|CV|cfg_hash`) | 디렉터리 `.gitignore`(`*`) |
| C 작업 | 백엔드 `data/clear_rate_verify/jobs.json` (삭제 안 함) | 재시작 시 진행 중 → interrupted |
| A 목표 곡선 / B 목표 | IndexedDB `TileMatchClearRateVerify.targets` (`${batch}|A`, `${batch}|B`) | 생산 DB(`TileMatchProduction`)와 별개 |
| 판정 기록(최신) | `records` 키 `${batch}|${level}|${A|B}|${exploration|confirm}` | 참조·요약 + 표시용 응답(봇 판 원자료 없음) |
| 이전 판정 기록 | `history` (덮어쓸 때 이전 값 보존, `archived_at`) | 현재 유효와 구분 |
| C 작업 참조 | `jobs` 키 `${batch}|${level}` (서버 작업 사본 + 요청 때 `map_hash`) | 새로고침 후 진행 중 작업 복원·폴링 |

### 12-2. 판정 기록 필드 (`EvaluationRecord`, schema 1)
맵 ID(`batch:level`)·`map_hash`(level_json 키 정렬 FNV-1a)·`cond_hash` / 배치 레벨 / A·B 모드·목표·목표 출처·`target_curve_hash`·`target_curve_version` / 봇 버전·프로토콜·`bot_config_hash` / 탐색·C 구분·측정 출처(cache/store)·시드 대역·실제 완료 판수·`job_id`·`measurement_ref` / 모델 버전·`judge_version`(select.PROPOSED + confirm band 해시) / 점예측·80% 범위·신뢰도 / 목표 근접 지표(참고, p_in_band) / 판정·사유 코드·원문 / 측정·평가 시각. 실행 상태는 작업 참조(`jobs`)에 따로.

### 12-3. 무효화 (`assessRecord`)
| 바뀐 것 | 결과 | 화면 |
|---|---|---|
| 맵(level_json)·배치 위치·봇 버전·봇 프로토콜 | `measurement_invalid` — 측정을 현재 결과로 안 씀 | "측정 무효", 실행 상태 "결과 오래됨", 서버 evaluate 도 거부 |
| 모델 버전·판정 기준 버전 | `evaluation_stale` | "평가 오래됨" — C 측정은 유효하면 [C 판정]으로 재평가 |
| 목표만(값·곡선 해시) | `needs_rejudge` | "재평가 필요" — 측정 재사용, [C 판정] 클릭 시 재판정 |
| 목표 없음 | `target_unset` | "목표 미설정" |
- 현재 유효가 아니면 판정 배지는 `과거: 합격` 처럼 회색(초록/빨강 금지) + 셀 흐리게. 출처 칸에 당시 모델·기준·목표·시각 유지.
- 이전 저장 데이터: 필수 필드 없으면 무시(개수 표시), 나머지 기본값 null, 모델 버전 없으면 오래됨 처리. 기존 검증 결과·레벨 메타·업로드 메타는 읽기만(덮어쓰기 없음).
- 저장 실패: `putRecord`/`saveCurve` 는 트랜잭션 완료까지 기다리고 실패는 reject → "저장 실패" 문구 + 행에 "저장 안 됨". 곡선 저장 실패 시 적용하지 않음.

## 13. 메인 신규 7커밋과의 겹침 (feature/pv-seed-variants 329a1a0, 읽기만 확인)
- `git diff 7d32d71..feature/pv-seed-variants --stat`: 이 워크트리가 2차에서 바꾼 파일과 **겹치는 파일 없음**. 메인이 바꾼 `ProductionDashboard/index.tsx`·`ProductionExport.tsx`·`productionStorage.ts`·`types/production.ts`·`main.py`·`.gitignore` 는 2차에서 건드리지 않음.
- 의도적 회피: 결과 저장을 레벨 메타(`types/production.ts` — 메인이 `rule_violations`·`PRODUCTION_MAX_LEVEL` 등 추가)·생산 IndexedDB(버전 업 필요) 대신 별도 DB 로 분리. `.gitignore` 대신 `backend/data/clear_rate_verify/.gitignore` 신규. 라우터는 기존 `clear_rate.py` 에 추가 → `main.py` 미수정.
- 병합 시 확인 지점: ① `schemas.py` 끝부분(이 브랜치가 ClearRateVerify* 추가) ② `BatchVerifyPanel.tsx`(1차에서 import+JSX 2줄) ③ 메인 `PRODUCTION_MAX_LEVEL=1530` — 이 탭은 배치 레벨을 그대로 쓰므로 영향 없음(L501+ 는 지원 범위 밖 → C 요청 거부·판정 근거 부족). 리베이스·머지는 하지 않음(승인 범위 밖).

## 14. 재시작 후 검증 (승인 후 실행 — 이번에 0회)
### 14-1. 명령 (순서·예산)
| # | 명령 | 예산 |
|---|---|---|
| 1 | `cd frontend && npx tsc --noEmit` | 1회 |
| 2 | `cd frontend && node --experimental-strip-types --test tests/clearRateLabels.test.ts tests/targetCurve.test.ts tests/clearRateVerifyModel.test.ts` (node ≥ 22.6) | 1회 |
| 3 | `cd backend && python -m pytest tests/test_clear_rate_confirm.py tests/test_clear_rate_experiment.py tests/test_clear_rate.py -q` | 1회 (봇 실측 없음: fake runner. 예외 `test_measure_should_stop_between_rows` 4판, 기존 `test_measure_reproduces_training_row_from_editor_json` 128판) |
| 4 | 백엔드 재시작(TERM 먼저 — main.py 주석) 후 `curl -s localhost:8000/api/clear-rate/verify/info` → `seed_band=CV`, `games_per_map=512`, `protocol_problems=[]` | 1회 |
| 5 | Playwright 시나리오(14-2) | 1회 |
| 6 | **최소 실측: 맵 1개 × C 512판(θ4×128)** — L237 골든(학습 캐시 있음 → 탐색 값과 C 값 비교 가능) | 512판, 동시 1 |
### 14-2. Playwright 시나리오
1. `browser_navigate http://localhost:5173` → 생산 대시보드 → 배치 → `검증` 탭. `clear-rate-verify-section`·`cr-c-note` 존재, 기존 BatchVerifyPanel 영역 변화 없음.
2. 곡선 구간 `32~300 95`, 주기 `10 / 10 / 80`, 개별 `237=88` → `cr-curve-preview` → 레벨별 출처(주기·개별) 확인, 경계(32, 300) 확인 → 겹치는 구간 추가 시 오류·적용 비활성 → 제거 후 `cr-curve-apply` → `cr-curve-applied` 에 v·해시.
3. 이 시점까지 네트워크에 `/verify/jobs` POST 없음(자동 측정 없음) 확인.
4. `cr-run-A` → 판정 `근거 부족 [탐색]`, 출처 `cache · seed11M`.
5. L237 체크 → `cr-c-prepare` → `cr-c-summary` "대상 맵 1 · 새로 측정 1 · 예상 512판 · 동시 실행 상한 2" → `cr-c-execute`. 즉시 다시 준비·실행 → 같은 job(`reused=active`), 새 작업 없음.
6. `cr-run-state-237` 대기→측정 중→완료. 측정 중 새로고침 → 상태 복원·폴링 재개.
7. `cr-c-judge` → `[C 확인]` 판정(합격/불합격/근거 부족 중 하나 — 결과 값은 미리 단정하지 않음), 출처 `C 확인 · store · 시드 CV · 512판`.
8. 곡선 개별 237 을 90 으로 바꿔 적용 → "재평가 필요", 배지 `과거: …` 회색, 측정 요청 없음 → `cr-c-judge` 로 재판정.
9. 새로고침 → 곡선·판정·작업 상태 모두 복원.
10. (선택) 측정 중 `취소` → 취소 요청됨 → 취소, 저장 없음 확인 / 기존 업로드 미리보기·verification_passed 불변.
### 14-3. 체크리스트 ↔ 테스트
| 항목 | 테스트 |
|---|---|
| 학습·탐색 측정을 C 로 오인 안 함 | `test_training_cache_is_never_accepted_as_c`, `test_band_registry_has_no_collision_and_cv_is_the_only_confirm_band`, model `only a full CV confirm job counts…`, `old saved data… never promoted` |
| C 중복 방지·시드 충돌 차단 | `test_duplicate_submit_joins_active_job_then_reuses_done`, `test_band_registry_detects_collision`, `plan summary`, `lock key` |
| 완료·실패·취소·부분 결과 | `test_done_job_is_stored_as_confirm…`, `test_failure_is_recorded_and_not_retried`, `test_cancel_queued_job`, `test_cancel_running_job_stores_nothing`, `test_partial_measurement_is_not_a_completed_c`, `test_measure_should_stop_between_rows` |
| 저장·새로고침·복원 | `test_restart_marks_active_jobs_interrupted`, model `old saved data` round trip, Playwright 6·9 |
| 맵 변경 무효화 | `test_evaluate_refuses_changed_map_or_placement`, model `map / placement / bot protocol change` |
| 목표만 변경 → 측정·판정 분리 | model `target-only change → needs rejudge`, Playwright 8 |
| 모델 버전 변경 → 오래됨 | model `model or judgment criteria change`, `test_judge_version_tracks_thresholds` |
| A·B 분리 | `test_api_submit_mode_a_only`, 기존 `test_api_target_eval_modes_are_separate`, curve `normalize … B 데이터는 A 곡선이 아님` |
| 곡선 경계·누락·우선순위 | targetCurve 테스트 전체 |
| 판정 로직 불변 | `test_done_job_…evaluates_like_request_c`(CV 판정 = 기존 C 경로 판정과 동일 값) |
| 기존 검증 탭·저장·업로드 회귀 | 기존 test_clear_rate*.py, Playwright 1·10 |

## 15. 실행하지 않아 미검증인 부분
- 모든 테스트·타입 검사 결과(작성만). 특히 TSX 타입(strict·noUnusedLocals), node strip-types 의 `.ts` 확장자 import, pydantic `min_length` 리스트 검증.
- 실제 봇 C 측정 소요 시간·메모리(스레드 2개 동시 시 GIL 경합), 취소 반응 시간.
- IndexedDB 새 DB 생성·트랜잭션 오류 처리 실제 동작, 1500레벨 배치에서 `mapHash` 계산 비용.
- `/verify/plan` 의 structural_screen 이 생산 신규 맵에서 예외 없이 도는지(맵별 오류는 개별 표시로 격리).

## 16. 남은 결정 (마더/사용자)
1. CV 대역(22M) 확정 여부 — 다른 세션이 22M 대를 쓰는지 알려진 바 없음(레지스트리·외부 목록 기준 충돌 없음).
2. 실패·취소 후 **사용자가 다시 [실행]** 하는 것은 허용(자동 재시도만 금지)으로 구현 — 수동 재실행도 막을지.
3. 학습 지원 밖 입력(L501+, 미학습 기믹 등)은 C 요청 자체를 거부(측정해도 판정 불가)로 구현 — 측정만이라도 허용할지.
4. B 확인 측정(θ0.85×512, B 정의 대역)은 이번 범위에서 제외 — B 칸은 계속 "측정 부족". 필요 시 별도 승인.
5. 목표 곡선 저장 범위: 현재 **배치 단위**. 프로젝트 전역 곡선이 필요하면 추가 결정.
6. 결과 저장을 나중에 레벨 메타로 옮길지(메인 병합 후).

## §재개 메모(검증탭2) — 2026-10-16 일시중지 (맥 재시작) → **재개·구현 완료(위 §10~§16)**

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
