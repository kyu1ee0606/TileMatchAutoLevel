# 자동 튜너 연동 — 순차검증이 색+기믹 튜너로 재생성 대체

> 2026-07-16 · 순차검증 첫 실패 시 재생성 전에 색+기믹 자동튜닝으로 목표 도달 시도. 재생성 횟수↓.

## 배경
3단 다이얼(모양/기믹/색)은 수동 전용이었음. 순차검증은 구 `/tune/arrangement`(색, block방식)만 폴백 사용.
→ 새 Ising 색엔진 + 기믹 튜너를 target 추종 방식으로 순차검증에 연동.

## 구조
### 백엔드 `POST /api/tune/auto`
- 입력: `level_json, level_number, target_difficulty(+scale) | target_clear_rate, tolerance, skill_mean`
- 절차:
  1. **색 스윕** (spread 5점: 0/.25/.5/.75/1) → 각 Ising 배치 → RL 스크리닝 → 목표 최근접.
  2. tolerance 내면 반환(lever=color).
  3. 부족하면 **기믹 스윕** (강도 5점) → 색 best 위에 → RL → best 갱신(lever=gimmick).
- 반환: `best_level_json, predicted_clear_rate, close(tolerance 내), lever, spread/intensity, cluster_index`.
- **스크리닝 rollout=20**(정본 64 대비 경량) — 후보선별 근사. **최종 확정은 순차검증이 full RL 재측정** → 이중잣대 없음(자기교정).
- 공용 헬퍼: `_color_context`/`_color_at_spread`(색), `_gimmick_arrangement`(기믹), `_sweep_pick`(RL 1회 병렬평가). tune_color·tune_gimmick도 이 헬퍼로 리팩터(중복 제거).

### 프론트 순차검증 (`handleSequentialProcess`)
- 첫 실패(attempts===1) + 클리어가능(max_clear≥0.05) 시:
  - `/tune/arrangement` → **`/tune/auto`로 교체**.
  - `tuned && close` 면 저장(verified=false) → `continue` → 정밀 재측정. 통과 시 **재생성 회피**.
  - 근접 못하면(close=false) → 기존 재생성 폴백.

## 3경로 정리
| 경로 | 튜너 |
|---|---|
| 배치 생성(1500) | 미사용(거친 재생성 — 속도 우선) |
| **순차검증** | **`/tune/auto`**(색→기믹 target 추종) → 부족시 재생성 |
| 수동 3단 다이얼 | `/tune/gimmick`·`/tune/color`(직접값 슬라이더) |

## 검증 (실측)
- target 추종 동작: L102 orig 0.38→0.84(목표0.74) **close=True 구제**(재생성 회피). L100/L101(하드 목표) close=False→재생성 폴백(정상).
- **÷3 보존** True(색 순열/기믹 td1). 모양·기믹 보존.
- 속도: 2.5~9s(스크리닝 rollout=20, 후보 5+5). 재생성 반복(각 수십초)보다 유리.
- 프론트 `tsc` 통과, `/tune/auto` 라우트 live.

## 한계
- 하드 목표(원본과 큰 격차)는 튜닝으로 못 맞춤 → close=false → 재생성(정상 폴백).
- 스크리닝(20 rollout) 근사 → 순차검증 full RL(64)이 최종 판정(자기교정).
- 배치 생성엔 미투입(속도 위해; 순차검증에서 미세조정).

## 파일
- `backend/app/api/routes/tune.py` — `/tune/auto` + `_sweep_pick` + 색/기믹 헬퍼 추출.
- `frontend/.../ProductionDashboard/index.tsx` — 순차검증 폴백 `/tune/arrangement`→`/tune/auto`.
- 게임코드 무변경.
