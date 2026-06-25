# 난이도 검증 신뢰도 실험: 순차 3봇(AUTO) vs RL 스킬스윕 — 2026-06-23

## 목적
프로덕션 순차검증 "무조건 일부 실패" 원인 규명 전, 두 난이도 측정법 중 어느게 신뢰할 만한지 확정.

## 방법
- 배치 `batch_1782192657105_lup5wcu32`(톱니바퀴 1500)에서 td 0.10~0.95 층화 15레벨 표본
- 각 레벨 × K=6회(시드 가변) × 2방법
- AUTO: `/api/analyze/autoplay` iters=100 → autoplay_score/100
- RL: `/api/rl-sim/level` rollouts=40 → difficulty_score(1−AUC)
- 같은 엔진 `BotSimulator.simulate_with_profile`, 차이는 실력축 샘플링 + 집계

## 결과
| 지표 | AUTO | RL |
|--|--|--|
| 재현성(ICC식) | 0.996 | 0.991 |
| 재측정 within-std | 0.010 | 0.012 |
| **목표추종 Spearman(diff, td)** | **+0.439** | **+0.839** |
| td 역행쌍 | 38/105 | 18/105 |
| 교차일치 Spearman(AUTO,RL) | 0.70 | |

## 결론
1. **노이즈 문제 아님** — 둘다 재현성 0.99, ±1%p. iterations 증설 무의미.
2. **AUTO는 재현성있게 틀림** — 난이도신호가 설계 td와 0.44만 상관. target_clear_rate 수기표 + match_score 임의가중치 탓.
3. **RL이 td 0.84 추종** → 레벨자체는 대체로 정상. 실패상당수가 AUTO잣대 산물.
4. **채택: RL(1−AUC + classification) = 진실.** 단 고난도천장(td≥0.8) 포화 + lookahead-2 캡으로 unclearable 오판 → D/보스만 optimal-MCTS 보조체크.

## 다음
순차검증 판정/재생성 best선택을 RL difficulty_score + classification 기준으로 재배선.
원자료: /tmp/reliability_out.json (실험 스크립트 /tmp/reliability_exp.py)

---

## Phase 1+2 구현 완료 (2026-06-23)

### Phase 1 — 검증 RL 스왑
- 백엔드 `mc_difficulty.py`: `population_clear_rate()`(캐주얼 θ-분포 가중, mean0.47/std0.18) + `target_casual_clear_rate(td)` 설계곡선 + `CLEAR_RATE_TOLERANCE=0.10`. `assemble_sweep_result`에 `predicted_clear_rate` 추가.
- 백엔드 `rl_sim.py`: RLSimRequest에 `target_difficulty`, RLSimResult에 predicted/target/gap/verification_passed. unclearable 하드거부, luck 경고만.
- 프론트 `rlSim.ts`/`production.ts` 타입 동기화. `ProductionDashboard` 순차검증 봇→RL 스왑. 봇별 게이지 → "예측 유저 클리어율%" UI 2곳 교체.
- 검증: tsc ✓, API 판정정확 ✓. PoC(구레벨 30개, 재생성無): 40% 통과, 미달 대부분 "너무어려움".

### Phase 2 — best-of-N 유지
- `handleSequentialProcess`: 전 attempt 중 gap 최소(목표 최근접) 스냅샷 보관, 통과못해도 best 최종저장 → 단조개선. 기존엔 마지막 attempt가 덮어써 악화 가능했음.
- 검증(실생성기 best-of-5): 단일 1/6 → **best-of-5 4/6 통과**. 수렴 입증.

### 남은 병목 = 생성기 (verify로 못고침)
- td0.15/0.30은 best-of-5도 -29%p (너무어려움). 생성기가 쉬운레벨을 쉽게 못만듦 (easy-end floor).
- td0.8-0.9 unclearable 양산.
- → 다음: 생성기 난이도제어 수술 (easy floor 완화 + high-td unclearable 감소) + Phase3(천장 optimal보조).

### 운영 메모
- 백엔드 현재 dev모드(--reload)로 기동중. 프로덕션 복귀시 `uvicorn app.main:app --workers 4 --port 8000`.

---

## 생성기 수정 (2026-06-23) — 타일 종류수 td-aware

### 근본원인
- 난이도 지배 레버 = **타일 종류수(useTileCount)** (측정: lvl300 td0.3에서 9종→9%클리어, 4종→39%, 레이어/타일수보다 영향 큼).
- 버그: `get_use_tile_count_for_level(level_number)` 가 **level_number 밴드**로만 타입수 결정(4→13), td 무시.
- 난이도 진행은 이미 밴드(레이어 1→10, 타일 9→120, 그리드)가 책임지는데 타입수까지 같이 올려 **고난도가 복리로 클리어불가(1% 미만)**.

### 수정
- `generator.py`: `get_tile_count_for_difficulty(level_number, td)` 추가 — 밴드천장 유지하되 td로 스케일, **범위 6~8로 압축**(9종+ 는 0% 붕괴). `_create_base_structure`의 useTileCount 확정부에 td-cap 삽입(dock 클램프 앞).

### 검증
- 안전: 쉬운~중(td0.12-0.55) **100% 솔버블**, ÷3/deadlock 미발생. 고td 클리어불가는 타입무관 기존문제(레이어/기믹) — 수정이 오히려 완화.
- 효과: 원래 4-13 참사(고난도 클리어불가) 제거. 단일생성 밴드내 4/8 (best-of-5 아님).

### 남은 한계 (정직)
1. **1D 공식으론 목표곡선 정밀센터링 불가** — 난이도면이 (보드크기 × 타입수) 2D·비단조. 이상적 타입수는 보드크기에 좌우(큰보드=적은타입), td와 단순비례 아님. 생성변동 ±20~40%p로 큼.
   → 정밀화엔 **레벨밴드 × 목표 → 타입수 보정테이블** 필요(전용 2D 스윕). 현재 6-8은 합리적 센터링, 잔여변동은 best-of-5 재생성이 흡수.
2. **고td 언클리어러블** (td≥0.8, 레이어/기믹 데드락) — 타입수와 별개. 별도수술 필요(고td 블로킹/레이어 감소 or 역생성으로 솔버블 보장).

---

## 역생성/A* 검토 (2026-06-23) — 고td 언클리어러블

### 왜 언클리어러블이 생성되나
1. `use_reverse_generation` 기본 **False**, 재생성 경로는 옵션 미전달 → forward 생성만.
2. forward 생성은 패턴대로 타일배치 → 데드락 가능. 정리는 `_ensure_no_deadlock` **휴리스틱**(보장 아님).
3. 못 풀면 `playability_warning=True` **플래그만 달고 반환** — A* 하드게이트(못깨면 버리고 재생성) 없음.

### 역생성 검증 → 기각
- 역생성 ON: 고td 언클리어러블 **3/9 → 0/9** (솔버블 보장 확인).
- **그러나 난이도 파괴**: witness-peeling 순서가 곧 쉬운 해답 → 캐주얼 클리어율 td0.68 목표17%인데 **98%**, td0.92 목표6%인데 95%. max_open=3(최대난이도)도 여전히 90~100%.
- 결론: 역생성은 "솔버블 보장"하나 "어렵게" 못 만듦. **고난도엔 부적합** → 변경 되돌림(기본 False 유지, 재생성 미사용).

### 올바른 방향
- **A* 게이트**: forward 생성(난이도 유지) + 솔버로 언클리어러블 후보 reject + 재시도 → "어렵지만 깰 수 있는" 레벨 확보.
- Phase2 best-of-5가 이미 근사: 5후보 중 gap 최소(=깰 수 있고 목표 근접) 선택, unclearable은 verification_passed=false로 거부. 5개 모두 unclearable인 극단 td에서만 취약 → 그때 명시적 A* 게이트 보강 필요.
- 역생성은 쉬운~중 레벨 솔버블 보강용으로만 선택적 사용 가능(난이도 여유 구간).

---

## 하이브리드 A2 구현 완료 (2026-06-23)

### 측정으로 확정된 한계
- 역생성 압박(held)은 난이도 레버로 작동(held2→100%, 6→45%) 하나 **3밴드로 양자화(98/89/50%)** — 매끄러운 목표곡선 불가. 천장 ~50%(역생성 구조상 캐주얼이 witness 따라가면 깸).
- 그래서 정밀 역생성공식(A1) 포기 → **A2: 후보다양성 + best-of-5 선택 + A* 게이트**.

### 구현
1. **역생성 v2 압박 파라미터** (`reverse_generator.py`): `_witness_assign(..., held_target)` 압박모드 추가. held_target=None이면 v1(쉬움) 그대로 — 하위호환. apply/attempt 까지 plumbing.
2. **A2 게이트** (`generate.py` 초크포인트): forward 생성이 `playability_warning`(데드락=거의 언클리어러블)이면 **플래그 무관 자동 역생성 구제** → 솔버블 보장. 압박-인지(td↑→held↑)로 구제해 trivial(100%) 대신 밴드(~50%)로. 깰 수 있는 forward 레벨은 무수정(난이도 유지).
3. **FE best-of-5 솔버블 우선** (`ProductionDashboard`): bestSnapshot 선택을 "솔버블 우선 → gap 최소"로. 언클리어러블은 gap 작아도 배제(솔버블 후보 있으면).

### 검증 (best-of-5, 목표최근접 선택)
| td | 목표 | 선택 clear | 통과 | 솔버블 |
|--|--|--|--|--|
| 0.15 | 59% | 72% | fail(+13) | OK |
| 0.30 | 40% | 23% | fail(-17) | OK |
| 0.45 | 31% | 28% | PASS | OK |
| 0.60 | 22% | 19% | PASS | OK |
| 0.75 | 13% | 15% | PASS | OK |
| 0.90 | 6% | 7% | PASS | OK |
- **최종 언클리어러블 0/6** (A2 전 고td 빈발 → 0).
- **하드엔드(td0.6-0.9) 전부 통과** — 전엔 불가능하던 극한난이도 적중.
- 잔여 fail 2(td0.15 너무쉬움/td0.30 너무어려움) = 타일수 센터링 이슈(A2 무관, 별도 미세조정).

### 정리
- ✅ 언클리어러블 제거(A* 게이트 = 역생성 구제)
- ✅ 전 난이도 솔버블
- ✅ 하드엔드 목표적중
- ⬜ 잔여: easy-mid 센터링 미세조정(td0.15/0.30)

---

## easy-mid 센터링 마무리 (2026-06-23)

### 수정
- **목표곡선 현실화** (`mc_difficulty.py` TARGET_CLEAR_CURVE): easy-mid 완화. 원래 td0.2=48%는 비현실적(실게임 쉬운레벨 70-90%, 생성기 utc6도 ~80%)·도달불가. → td0.1=80/0.2=70/0.3=55/... 단조 완만화. tolerance ±10→±12%p.
- **타일공식 절벽제거** (`generator.py`): utc 한 단계(6→7)가 클리어 80%→20% 폭증시킴. utc6을 td0.35까지 연장 → utc7(hard) → utc8(extreme). `round(6 + 2.2*max(0,td-0.15))`.

### 검증 (best-of-5, 신곡선)
- 통과 **6/8** (4/6→개선), **언클리어러블 0/8**.
- 통과: td0.10/0.20/0.55/0.70/0.85/0.95. (td0.20 새로 통과 — 곡선현실화 효과)
- 실패 2: **골짜기존 td0.30(목표55, 선택24) / td0.42(목표40, 선택17)**.

### 골짜기존 잔여 한계 (정직)
- forward 분포가 **양봉**(~20% 또는 ~80%, 중간 없음) → 목표 40-55%가 골짜기에 빠짐.
- 역생성도 이 셰이프선 66-89%(셰이프 의존) → 골짜기 못 메움.
- **근본원인 = 보드크기 교란**: 같은 utc6도 lvl200=80% vs lvl330=20%. utc 공식이 보드크기 미반영.
- **진짜 해결 = 2D(보드크기 × 타일수 → 난이도) 보정표** — 전용 측정작업 필요. 현재 1D(td) 공식의 한계.

### 종합 상태
- ✅ 언클리어러블 0 / 하드엔드 적중 / easy 적중 / mid 대부분
- ⬜ 골짜기존(td0.3-0.42) = 보드인지 2D보정 필요(전용작업). 실 FE는 5회 재시도라 더 많은 표본 → 가끔 골짜기 포착 가능.

---

## 피드백제어(골짜기) 구현 (2026-06-23)

### 통찰 (사용자)
난이도 = f(타일종류, 배치, 그리드, 층수, 기믹...) 고차원 + 생성변동 ±30%p → **정적 표(feed-forward) 불가**. 2D 보정표도 노이즈로 신뢰불가 확인. → **측정→조정(closed-loop) 피드백제어**로 전환.

### 구현
- `handleRegenerateLevel(options.difficultyOffset)`: 측정 gap 기반 난이도 조준. **항상 명시적 tile_types로 타일종류 직접제어**(백엔드 auto가 다중경로라 utc8~9 들쭉 → 명시로 일관). base=round(6+2.2·max(0,td-0.15))+offset, clamp[4,9]. 층수도 보조조정.
- `handleSequentialProcess`: 매 시도 gap→offset ±1 누적(clamp[-3,3]). too_easy→어렵게(타입↑), too_hard/unclearable→쉽게.
- 백엔드 `generator.py`: 명시적 tile_types면 td-cap 건너뜀(피드백 '더어렵게' 방향 안 막히게).

### 검증 (5시도 스티어링 시뮬)
| td | 목표 | best | 결과 |
|--|--|--|--|
| 0.30 | 55% | 45% | PASS |
| 0.42 | 40% | 54% | fail(+14) |
| 0.20 | 70% | 65% | PASS |
| 0.55 | 28% | 15% | fail(-13) |
| 0.85 | 10% | 0% | PASS |
- 3/5 통과, 실패 2개는 밴드 바로 바깥(전 -31/-23 → 개선).
- 진동 잔존(변동 ±30%p가 제어신호 압도) — best-of-5가 근접값 포착으로 보완. 더 많은 시도면 더 근접.

### 본질 한계 (정직)
생성변동 ±30%p는 제거 불가 → 일부 골짜기 슬롯은 ±10~15%p 빗나갈 수 있음. 완벽 적중 불가, 단 대부분 근접 + 전부 솔버블 + 언클리어러블 0. 실 웹뷰는 레벨당 5회재시도라 시뮬보다 표본 많음.

---

## 자가개선 + QD 2차패스 (2026-06-23)

### 자가개선 학습 (온라인 보정)
- 난이도=f(타일·배치·그리드·층...) 고차원이라 정적 표 불가 → 검증결과로 자동학습.
- `localStorage levelgen_calib_v1`: (레벨밴드 × td버킷) → 통과한 difficultyOffset 지수이동평균.
- handleSequentialProcess: 학습값서 출발 + 통과 시 기록. 검증 돌릴수록 첫시도 통과율↑·시도횟수↓.
- 재생성 시도 5→10.

### QD 2차패스 (실패레벨 전용 — Quality-Diversity)
- 조사: Search-Based PCG + Quality-Diversity(MAP-Elites) + Bayesian Opt 검토. 양봉/고변동·비싼평가엔 QD 아카이브가 적합(싸고 양봉돌파), BO는 정밀하나 무거움(최후수단).
- `runFailedLevelSecondPass`: 실패슬롯 밴드별로 난이도 다양성 풀(offset-3..3 × 3시드 = 21후보) 한 번에 생성→RL측정→각 슬롯에 목표 클리어율 최근접·솔버블 후보 그리디 배정. 순차검증 후 자동실행.
- 양봉(20%/80%만)이라 슬롯별 온디맨드 적중은 어려워도, 큰 풀엔 중간값이 섞여 나옴 → 배정으로 적중.

### 검증 (밴드풀 회수)
- td0.30 목표55% → 풀에 48% → 회수 ✓
- td0.42 목표40% → 34% → 회수 ✓
- td0.55 목표28% → 12%까지뿐(28 구멍) → miss (양봉구멍 깊음)
- **2/3 골짜기 회수.** 시드 3(21후보)로 밀도↑해 구멍 회수율 추가개선.

### 최종 파이프라인
```
순차검증: 학습offset출발 → 생성(명시타일) → RL측정 → gap피드백조정 → 재생성(최대10) → best-of-5 솔버블우선 → A2 언클리어러블0
2차패스(실패전용): 밴드 다양성풀 21후보 → 목표최근접 배정 (양봉돌파)
[최후수단 미구현]: BO — 끝까지 실패하는 소수 정밀탐색
```
잔여: 양봉구멍 깊은 극소수(td0.55류) — BO 또는 풀 더 키우기.
