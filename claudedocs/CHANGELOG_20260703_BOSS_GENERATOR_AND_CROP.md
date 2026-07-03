# CHANGELOG 2026-07-03 — 보스 레벨 전용 생성기 + 템플릿 크롭 + 디바이스 그리드 제약

## 요약
디바이스 가독성 한계(9x9 이상 타일 과소 표시)로 10x10 보스 레벨이 플레이 곤란하던 문제 해결.
보스(10의 배수)를 **선언 그리드 최대 8**로 제약하고, 기존 템플릿 모양을 **크롭해 최대한 차용**,
안 맞는(크롭 불가) 것만 전용 레시피로 절차생성. 보스 목표 클리어율은 절반(더 어렵게).

## 배경 / 문제
- 보스 150개 중 128개가 10x10 템플릿 배정 → 실기에서 타일 너무 작음.
- 스캔: 크롭 시 A(원래≤8) 17개 + B(크롭→≤8) 30개 = 47개 재사용 가능, 나머지 D(크롭 불가).

## 구현

### 백엔드
- **`boss_mode` 파라미터**: `GenerationParams` + 요청 스키마 2종(`schemas.py`) + 라우트 2경로(`generate.py`).
- **`_apply_boss_overrides`** (`generator.py`): 그리드 (7,7)→선언 최대 8, **5~6층**(폭 대신 깊이로
  물량·난이도 확보), symmetry both, 기믹 강도 상향. 그리드 테이블 축소 우회(`get_grid_size_for_level` skip).
- **`BOSS_RECIPES` 12종**: 레이어별 화려한 대칭 템플릿 스택(별/꽃/나비/선버스트/나선/팔각링/피라미드
  교대 등). `(level//10 - 1) % 12` **결정적 로테이션** → 보스 150개 조합 순환, 재시도에도 동일.
  `_generate_auto_layer_pattern_configs`에 `boss_level_number` 인자로 적용.
- **`crop_level_to_max_dim(level_json, max_dim=8)`** (`generator.py`, 모듈 함수): 빈 가장자리
  균일 크롭. 순수 좌표 시프트 → **타일수·타입·÷3 불변**, 홀짝 교대/블로킹 상대크기/link 상대위치 보존,
  에디터 메타(`_pattern_locked_positions`, grid_cols/rows) 시프트. 크롭 후에도 초과면 미적용.
- **`/generate/from-template`**: `crop_max_dim` 파라미터 + 응답 `cropped`/`cropped_max_dim` 플래그.
- **`/rl-sim/level`**: `target_clear_rate_scale`(보스=0.5) — 목표 클리어율 절반 → 더 어려워야 통과.

### 프론트 (`ProductionDashboard/index.tsx`, `api/`, `types/`)
- 파라미터 빌더 4곳(신규/재생성/enhance/band): 보스 분기(그리드≤8·5~6층·`boss_mode`·pattern_index 미지정).
- **템플릿 차용+크롭**: from-template를 `crop_max_dim=8`로 호출. A/B는 크롭된 템플릿 그대로,
  D(크롭 후 >8)는 템플릿 폐기 → `boss_mode` 레시피 절차생성 폴백(초기생성 catch / 재생성 else 분기).
- **RL 검증 5곳**에 `target_clear_rate_scale = bossTargetScale(levelNumber)`(보스 0.5) 전달.
- **순차검증 그리드 게이트**: `maxDeclaredGridDim > 8` → RL 무관 실패(재생성 유도) → from-template
  무한 재생성 루프 차단. 보스 재생성도 크롭/폴백 경유(template_id는 D폴백 시에만 제거).
- 보스 템플릿 자동배정 유지(난이도순), 10x10은 크롭/폴백이 처리.

## 데이터 작업 (서버 배치 v38)
- B타입 보스 30개 크롭 적용(10x10→≤8, 타일수·타입 불변 검증).
- (별건) craft/stack 내부 단색 87레벨 다양화 수리 — CHANGELOG 별도.

## 검증
- 크롭 12템플릿: B 5개 →8, D 7개 유지(applied=false), 전부 타일수 무결.
- 보스 생성 스모크 L30/40/50/60: 선언 최대변 8, 5~6층, ÷3 위반 0.
- `npx tsc --noEmit` + 백엔드 문법 통과.

## 게임 영향
없음. 크롭=순수 좌표 변환, 명시 inner=스키마 v1.10.382 리터럴 스폰, boss_mode=에디터측 파라미터.

## UI 추가
- Test 탭에 **검증 기준 skill_mean 표시**(모드탭 하단 상시 + 순차패널 헤더). 값/등급 라벨,
  조절은 생성 탭 '난이도 기준 실력' 슬라이더.

## 커밋
`dd457ba feat(boss): 보스 레벨 전용 생성기 + 템플릿 크롭 + 디바이스 그리드 제약`
