# CHANGELOG 2026-07-01 — 타일 종류 수 고정 + 독천장 제거 + RL 난이도 기준 실력

프로덕션 레벨의 "타일 종류 수 고정 그래프"가 실제 생성/재생성에서 안 지켜지던 문제 해결 +
난이도 검증(RL) 기준 실력을 프로덕션 생성 시 슬라이더로 조절 가능하게.

## 1. 원인 진단 (실측)
- **초기 생성(코어 `/api/generate`)**: 그래프값(useTileCount) 준수. 문제 아님.
- **순차검증 재생성**: `handleRegenerateLevel`/`genCandidate`가 그래프 대신 **난이도 기반 종류 수**
  (`round(6+2.2*(td-0.15))` clamp[6,8] + offset)로 덮어써 그래프 붕괴.
- **독 천장 캡**: `_validate_dock_tile_compatibility` + base structure가 `useTileCount`를
  `(7-unlockTile)+2`(기본 9)로 캡 → 고레벨(그래프 V=10~12)이 9로 잘림.
- 실측: 코어 그래프값(9~12) 유지, validated는 3까지 붕괴.

## 2. 재생성 타일 종류 그래프 고정
`frontend/src/components/ProductionDashboard/index.tsx`
- `handleRegenerateLevel`(steeredTileCount), `genCandidate`(cnt): 난이도식 → **그래프값**
  (`vAtLevel(TILE_TYPE_PROFILE_CURVES[tileTypeProfile], levelNumber)`)으로 변경.
- 난이도 조준은 타일 종류 대신 **층수(diffOffset→ml)/기믹**으로만.
- `TestTab`에 `tileTypeProfile` prop 배선.

## 3. 독 천장(dock ceiling) 개념 제거
"트레이 용량 대비 종류 과다 → 캡" 기능 폐지 (불필요 판정). `useTileCount`=그래프값(카탈로그 15 클램프만).
- `generator.py`: base structure의 dock 캡 + td-aware 캡(`get_tile_count_for_difficulty`) 제거.
  `_validate_dock_tile_compatibility` 무캡화(safe_max=15). 고아 함수 `get_tile_count_for_difficulty` 삭제.
- `allow_high_tile_variety` 필드 **전면 제거**: schemas.py, level.py, routes/generate.py(3곳),
  프론트 state/UI 체크박스/prop, api/generate.ts, types/index.ts.
- 검증: level 800→11, 1200→12, 1500→12 (이전 9로 잘리던 것 해결).
- ⚠️ 트레이 데드락 안전망 = `_ensure_no_deadlock` 시뮬 + 프로덕션 봇/RL 검증(사후).

## 4. RL 난이도 기준 실력 슬라이더 (전체 난이도 조절)
순차검증 RL이 예측 클리어율을 판정할 때 기준 실력(θ, 0=최고초보~1=최고고수)을 조절 가능.
- `backend/app/api/routes/rl_sim.py`: `RLSimRequest`에 `skill_mean`/`skill_std` 추가.
  `/level`에서 이미 계산된 스킬곡선을 그 실력 중심으로 **재가중만**(롤아웃 재실행 없음) →
  `population_clear_rate(curve, mean=skill_mean)`로 predicted_clear_rate 재산출.
- `frontend`: `rlSim.ts` `RLSimRequest`에 skill_mean/skill_std. `ProductionDashboard` 상태
  `rlSkillMean`(기본 0.47) + **슬라이더 UI**(생성 설정) + 순차검증 RL 호출 5곳에 전달.
  `TestTab`/`GenerateTab` prop 배선.
- 동작: mean↑ = 고수 기준 → 어려운 레벨도 통과(게임 난이도↑), mean↓ = 초보 기준(난이도↓).
  **초기 생성값 불변, 검증 기준만 이동.**
- 검증: 그라디언트 레벨서 skill_mean 0.3→0.9 predicted 0.03→0.80, 통과판정 반응 확인.

### 배경: RL 신뢰성
- 고종류(11) + 데드락 취약 레벨에서 RL(중간실력 모델)이 과소예측 → 순차검증 오탐 다발.
  실측: 어떤 level_72는 RL 2~15%인데 솔버 PROVEN_SOLVABLE·expert봇 100%·사람 쉬움.
- 근본 정합은 실플레이 캘리브레이션(별도 후속) — 슬라이더는 그 기준을 수동 반영하는 노브.

## 검증
- py_compile(generator/solver/rl_sim/level/schemas/generate) 0, tsc --noEmit 0.
- API 실측: useTileCount 그래프값, skill_mean 재가중, RL 통과판정 반응 모두 확인.

## 알려진 트레이드오프
- 타일 종류 고정 ↔ 난이도 목표는 물리적 충돌(종류수가 난이도 지배 레버). 종류 고정 시
  고레벨이 실제로 어려워짐 → RL 기준 실력 슬라이더로 검증 기준을 맞추거나 그래프 자체를 조정.
