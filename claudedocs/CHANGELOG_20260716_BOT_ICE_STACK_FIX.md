# 봇 시뮬 정확도 — ice 불가판정 완화 + 컨테이너 배출 임팩트 우선

> 2026-07-16 · 보스/복합 레벨의 봇 거짓실패(0%) 원인 2건 수정. RL·autoplay 자동 반영(단일 엔진).

## 배경
7.16 프로덕션 순차검증서 보스 L20/30/60 등이 **재생성 무한루프**. L60은 ÷3 정상·수동 클리어 가능한데 봇 0% → 재생성 반복. 원인 = **봇 거짓실패**.

## 원인 1: ice 불가판정 과도 (거짓실패)
- 게임(`TileGroup.CheckIceTileCanUncover`, sp_meowsgarden): **다른 타일 선택마다 커버 안 된 ice 한 겹 벗겨짐**(`TileEffect.OnClickOtherTile`). 불가조건 = `min-remain ice > 비-ice 활성타일` 하나뿐.
- 봇(기존 `_check_ice_impossible`): blocked ice마다 `blocking_count + remain` 합산 → **게임보다 과도하게 '불가'** → `state.failed=True` 조기 포기 → ice 다수 레벨 거짓 0%.
- **수정**: 게임 규칙으로 완화 — `min_ice_remaining > total_remaining_non_ice` 하나만 검사. 회귀검증(L36/40/45/50 정상 ice) 무영향.

## 원인 2: 컨테이너(stack/craft) 배출 우선순위 부재 (진짜 원인)
- 유저 관찰: 바닥 tall stack을 봇이 빨리 못 빼서 → 그것에 묶인 부족분 타일(예 t7×2, t3×4 배출) 처리 못하고 막힘.
- 봇(기존): 컨테이너 goal 타일 보너스 = `goal_priority×2` ≈ **+2** (chain +60 대비 무시) → tall stack 방치 → stuck.
- **수정**: `_score_move_with_profile` — dock 여유(≥2)일 때 **임팩트 비례** 보너스:
  ```
  impact = ①배출타입 기다리는 필드타일 수
         + ②컨테이너 잔여 내부깊이(tall일수록↑, 끝까지 배출 유지)
         + ③컨테이너가 덮은 타일 수
  보너스 = min(60, 6×impact) × goal_priority
  ```
  - **무조건 아님**: impact 0이면 보너스 0 (유저 요구 정확 반영 — 풀리는 타일 많을수록 가중).
  - dock 가득이면 미적용(배출이 clog 방지).

## 검증 (실측, /api/rl-sim/level)
| | 수정 전 | 수정 후 |
|---|---|---|
| L60 (stack, 64/200 rollout) | 0.0 / 0.0 | **0.61 / 0.73** |
| L60 craft 버전(동일구조) | (동일 0 예상) | **0.59 / 0.64** |
| 회귀 L21/25(stack)·L11(craft) | — | 1.0 (무회귀) |
- **craft = stack과 동일 문제**, 조건이 `is_stack_tile OR is_craft_tile OR origin_goal_type`라 **한 수정으로 둘 다 해결**.

## RL 반영 (자동)
- **RL 스윕·autoplay가 bot_simulator를 그대로 사용** (`mc_difficulty.py` → `BotSimulator.simulate_with_profile`). 별도 RL 구현 없음.
- bot_simulator 한 곳 수정 → **RL 검증에 자동 반영** (그래서 /rl-sim 결과가 즉시 바뀜).

## 영향
- 컨테이너/ice 있는 보스·복합 레벨의 **거짓 0% 대량 감소** → 재생성 무한루프(L20/30/60류) 상당수 해소.
- 봇 클리어율이 실제 클리어가능성에 더 근접 → 순차검증 신뢰도↑.

## 파일
- `backend/app/core/bot_simulator.py` — `_check_ice_impossible`(게임규칙), `_score_move_with_profile`(컨테이너 임팩트 보너스).
- **게임코드(sp_meowsgarden) 무변경** (규칙 확인 목적 읽기만).

## 참고 (게임 정본)
- ice: `OnClickOtherTile` — 다른 타일 선택마다 커버X ice −1. 불가 = `CheckIceTileCanUncover`(min-remain 기준).
- 봇↔게임 정합 검증: 단순 stack A/B(1.0), L60 craft/stack 대칭.
