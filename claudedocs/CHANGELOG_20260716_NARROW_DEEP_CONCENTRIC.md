# 좁고깊은 레벨(중간보스) — layer_steps 노출 + 동심 침식 스택

> 2026-07-16 · Tile Explorer류 "작은 그리드 + 깊은 스택" 생성. 중간보스(×5, ¬×10) 적용 목표. 실현성 조사 + 동심 셰이프 구현.

## 목표
- 정규=넓고얕음 / 보스(×10)=현행 / **중간보스(×5 & ¬×10 = 5,15,25…) = 좁고깊은 타입**.
- 그리드 6,5,6,5 or 7,6,7,6 (홀짝) + 층 8 + 수직 스택.

## 실현성 조사 (실측)
1. **작은 그리드서 깊은층 안 됨**: 기본 피라미드 축소(step −1)가 상위층 소멸 → 4층만.
2. **`layer_steps` API 미노출** → 노출(schema+params). `[0,0,…]`=수직.
3. **step 0(수직) 만으론 언클리어러블(RL 0%)**: 얇은 깊은스택 = 트레이 클로그.
4. **역생성(use_reverse_generation) 병용 시 clearable**: 6,5,6,5=1.0, 7,6,7,6=0.59~0.75 (8층).
5. 10층 무리(6,5는 축소·7,6는 0.37 급락), **8층이 스위트스팟**.
> ⚠️ 빠른추정(clear_est)은 거짓(1.0)이었고 실제 RL이 0%로 잡음 → 역생성으로 해결. RL 검증 필수.

## 동심 침식 스택 (비주얼 개선)
- 문제: step 0 + 역생성 = **상위층 무작위 흩어짐**(바닥은 좋은데 위가 조각남) — 유저 피드백.
- 원인: 상위층을 독립 패턴으로 각각 생성 → 작은 조각. (역생성 아님.)
- **해결: `concentric_deep`** — layer_0=패턴 모양 → 위로 **테두리 한 겹씩 침식(erode)** = 거북등껍질 코히어런트 스택. 2층마다 완만 축소.
  - **패턴 모양 반영**(사각섬 고정 아님): `_generate_aesthetic_positions`로 마스터 → fill_holes → erode → 홀짝 그리드 중앙배치.
  - 각 층 = 아래층의 중앙 부분집합 → 홀짝 커버 정합, peel 클리어. 타입=t0(파이프라인/역생성 배정).
  - 채워진 패턴(square/blob/octagon) 적합, 프레임/링류 부적합(침식 시 소멸).
- 검증: 7,6 동심 7층 clear 0.6~1.0, 모양별 바닥 다양성 유지.

## 파라미터 (신규)
- `layer_steps: List[int]` — 층별 패턴크기 스텝(누적). None=−1(피라미드), [0..]=수직.
- `min_layers: int` — 최소 활성층 강제.
- `concentric_deep: bool` — 동심 침식 스택.
- 병용 권장: `use_reverse_generation=True` (타입 솔버블화).

## 프리셋 (실측 기반, 미구현 — 정식 슬롯은 후속)
```
NARROW_DEEP: grid [5,5](6,5,6,5) or [6,6](7,6,7,6), active_layer_count 8,
             min_layers 7, concentric_deep True, use_reverse_generation True
중간보스 슬롯: level%5==0 && level%10!=0 → NARROW_DEEP, 목표 scale ~0.7
```

## 검증 단계 (Phase)
- Phase1 비주얼(에디터/로컬레벨/GameBoost) → Phase2 체감난이도(RL/실기) → 정식 슬롯.
- 샘플: `claudedocs/midboss_samples/`, 로컬레벨 `midboss_c_L101~106`.

## 부수 개선
- **에디터 TileGrid**: 선택층 아래 **전체 층 표시**(기존 2층캡 → 깊은스택 전체 보이게, 깊이 fade).

## 파일
- `backend/app/models/schemas.py`·`level.py`·`api/routes/generate.py` — 파라미터 노출.
- `backend/app/core/generator.py` — `_build_concentric_layers`(동심 침식).
- `frontend/.../GridEditor/TileGrid.tsx` — 전체층 표시.
- 게임코드 무변경.

## 한계
- 동심은 채워진 패턴만 적합(프레임 부적합). 일부 패턴 언클리어러블 → 클리어검증 필터 필요.
- 정식 중간보스 슬롯 UI·난이도스케일은 후속.
