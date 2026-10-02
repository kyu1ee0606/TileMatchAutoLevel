# 03. 에디터 솔버/봇 조사 노트 — 변형 상대 난도 지표 신뢰성

- 대상: `/Users/casualdev/TileMatchAutoLevel` (HEAD `050abb1`), 조사일 2026-10-02
- 방식: 코드 정독(읽기 전용). 장시간 시뮬/서버 기동 없음.
- 표기: **[코드]** = 코드로 확인(경로:줄, 접두 `backend/app/` 생략) · **[제안]** = 해석/제안 · **[agent]** = 하위 조사 에이전트 보고(직접 미확인)
- 게임 규칙 원천: `01_client_findings.md §5`

---

## 1. 솔버 (A* / best-first 완전탐색) — `core/solver.py`

### [코드] 알고리즘
- `solve_level(level_json, node_budget=60000, time_budget_s=5.0)` (`core/solver.py:29-30, 201-368`).
- 단계: (a) **÷3 체크** — 클라 분배 포트(`TileDistributor.assign_t0_tiles`)로 t0 까지 배정한 뒤 타입별 카운트 `%3≠0` 이면 즉시 `PROVEN_IMPOSSIBLE` (`:60-155, 262-271`). (b) **best-first** — 힙 키 = 남은 타일 수(작을수록 우선), 동일 시 삽입순. 이동은 `will_match` 먼저 정렬(가지치기 아님) (`:279-336`).
- 이동 생성/적용/패배판정은 **BotSimulator 원시함수 재사용**: `_get_available_moves`, `_apply_move`, `_is_game_over` (`:297, 314, 317`). ⇒ 솔버의 규칙 정합성 = 봇 시뮬 규칙 정합성(§3 표).
- 중복 제거: `_state_signature` = (미픽 타일의 (layer,pos,type,effect_type,effect_data.remaining,effect_data.unlocked)) 정렬 + dock 타입 정렬 (`:158-175`).
- `max_moves` 무력화: `총타일+100` (`:224-226`). 제한시간(timea) 개념 없음.

### [코드] 판정 3종과 타임아웃 처리
| 판정 | 조건 | 위치 |
|---|---|---|
| PROVEN_SOLVABLE | 클리어 child 발견 (witness 길이 `moves_to_clear`) | `:319-326` |
| PROVEN_IMPOSSIBLE | ÷3 위반 / 힙 소진(상태공간 완전 탐색) & 미지원 기믹 없음 | `:264-271, 362-368` |
| UNCERTAIN | **시간 초과 또는 노드 예산 초과** / 초기상태 생성 실패 / 힙 소진이나 UNRELIABLE 기믹(frog/teleport/bomb/curtain/unknown) 포함 | `:253-255, 338-346, 352-361` |
- **솔버 자체는 시간초과를 불가능으로 처리하지 않음** ✔ (`:338-346`). `solve_level_task` 예외도 UNCERTAIN (`:378-382`).
- 호출처별 예산: `/api/analyze/solvability` = 요청값 (`api/routes/analyze.py:1341-1349`), batch = ProcessPool (`:1360-1371`), autoplay 내부 = `node_budget=300000, time_budget_s=12` (`analyze.py:893-896`), rl_sim = `200000/8.0` (`api/routes/rl_sim.py:339-340`), study = `200000/8.0` (`api/routes/study.py:124`).
- (호출처에서 UNCERTAIN 을 어떻게 소비하는지는 §1-추가 참조)

### [코드] 결정성
- 탐색 순서는 결정적(heap + counter tiebreak). 단 t0 배정은 `randSeed`; `randSeed=0` 이면 분배기 `zWellRandom(0)` → **시간 기반 시드** (`core/bot_simulator.py:42-45, 309`) ⇒ randSeed=0 레벨은 실행마다 다른 배치를 풀게 됨.
- 솔버는 frog/teleport 를 아예 처리하지 않으므로(아래 '턴 후처리 미호출') 이동 단계 난수 소비는 없음. randSeed≠0 이면 솔버 결과는 결정적(단 벽시계 예산 때문에 CPU 부하에 따라 SOLVABLE↔UNCERTAIN 경계가 흔들림). 솔버엔 `seed` 인자 없음.

### [코드] 실수 내성(robustness) — 이미 있는 '상대 난도' 후보
- `measure_robustness(max_depth=40, move_cap=8, node_budget=20000, time_budget_s=2.0)` (`core/solver.py:448-553`): 클리어 경로를 따라가며 각 결정점에서 "둔 뒤에도 클리어 가능한 수 / 결론난 수" 비율. 주 지표 `safe_move_ratio`(평균), `min_safe_ratio`. 예산초과(None)는 분모에서 제외 (`:521-528`).
- 한계: `move_cap` 앞쪽(`will_match` 우선)만 평가 → 표본 편향; 안전수 첫 번째로만 진행(경로 1개); 결정점당 최대 `move_cap × 2s`.
- 사용처: `api/routes/study.py:166, 203, 232` (max_depth 8~10, move_cap 4~5).

### [코드] 🔴 솔버 규칙 결함 — 턴 후처리 미호출
- 봇은 매 수 `_apply_move` 후 `_process_move_effects` 호출 (`core/bot_simulator.py:1774-1778`): 폭탄 카운트다운, 개구리 이동, 커튼 토글, 텔레포트, **막혀있던 craft 재배출(`_emit_blocked_craft_tiles`)** (`:2755-2816`).
- 솔버(`solve_level`, `_solvable_from_state`, `measure_robustness`)는 `_apply_move` + `_is_game_over` 만 호출 — `_process_move_effects` 호출 없음 (grep: 호출처는 `bot_simulator.py:1778`, `api/routes/simulate.py:384` 뿐). `moves_used` 도 증가 안 함.
  - 결과: 솔버 세계에선 폭탄이 안 터지고 커튼이 안 바뀌고 개구리·텔레포트가 정지. 이 5종은 `UNRELIABLE_GIMMICKS` 로 IMPOSSIBLE→UNCERTAIN 강등되지만 **PROVEN_SOLVABLE 은 그대로 신뢰됨** → 폭탄 레벨에서 "폭탄 무시 경로"를 witness 로 낼 수 있음(false SOLVABLE 위험).
  - craft 는 UNRELIABLE 대상 아님. 정상 배출은 `_apply_move→_process_craft_after_pick` 에서 처리되나(`:1671-1722`), **배출칸이 다른 타일로 막혔다가 풀리는 경우**는 `_emit_blocked_craft_tiles` 에만 있음 → 솔버는 해당 craft 내부 타일에 영영 접근 못 해 **false PROVEN_IMPOSSIBLE 경로가 코드상 존재**(실측 사례는 미확인).
- 상태 시그니처 누락: curtain `is_open`, frog 위치, teleport 카운터, dock 잠금 슬롯 상태는 시그니처에 없음 (`core/solver.py:158-175`) → 다른 상태를 같은 것으로 병합 가능(현재는 위 후처리 미호출 때문에 실질 영향 적음).

### [코드] UNCERTAIN 소비처 (시간초과를 불가능으로 치는 곳?)
| 소비처 | 동작 | 위치 |
|---|---|---|
| `_verify_single_level` (배치/순차 검증) | 봇 불통과일 때만 솔버 호출. SOLVABLE→통과 승격, IMPOSSIBLE→실패 확정, UNCERTAIN→"판정 보류 — 봇 결과 유지" | `api/routes/analyze.py:885-907` |
| 같은 함수 통과조건 | `max_gap ≤ tol AND 모든 봇 clear_rate > 0` → 봇 0% + 솔버 UNCERTAIN 이면 **결과적으로 실패** (불가능 판정은 아니나 '실패' 라벨) | `analyze.py:860-861, 883` |
| study verdict | 단순 집계 | `api/routes/study.py:124-140` |
- ⇒ **시간초과를 PROVEN_IMPOSSIBLE 로 바꾸는 코드는 없음** ✔. 단 봇 0% 이슈 문구가 "클리어율 0% (클리어 불가)" (`analyze.py:861`)라 사람이 불가능으로 오독할 소지.

### [실측 — 기존 결과 파일] `backend/data/night_study.json` (2026-08-10, 1500레벨 배치, 솔버 200000노드/8s)
- 1467레벨: SOLVABLE 1094 / **UNCERTAIN 355(24%)** / IMPOSSIBLE 18. 순차 1스레드 78분 → **평균 ~3.2s/레벨**.
- RL(아래 MC 스윕) 예측 0% 인데 SOLVABLE 309개 → 봇 0% ≠ 불가능 실증.
- 이번 조사 단건 실측(55s 이내): Lv710(111타일, utc13) 60000/5s → **UNCERTAIN 768노드 5.85s**(주석상 과거엔 108노드로 SOLVABLE — 예산·배치에 따라 결과 흔들림), Lv1268(138타일) → SOLVABLE 171노드 4.24s. 노드 처리 ~40~130/s 로 느림(상태 복사 비용).

### [제안] A(무부스터 해법 존재) 평가 가능성
- **부분 가능**. 기믹 없는/ice·grass·chain·link 만 있는 레벨: SOLVABLE 은 신뢰 가능(규칙 정합 범위 내), 시간초과는 UNCERTAIN 으로 정직하게 남음. 단 UNCERTAIN 비율 ~24% 라 "A 확인됨" 커버리지는 3/4 수준.
- bomb/curtain/frog/teleport 포함: SOLVABLE 도 신뢰 불가(후처리 미호출) → '미확인' 취급 필요. craft 포함: IMPOSSIBLE 신뢰 주의.
- 변형 생성 시 역생성(`core/reverse_generator.py`, 커버 DAG peel + witness 배정)은 **구성 단계에서 해법 존재를 보장**하는 별도 경로 — 단 concrete 레벨 전용(메모리 `project_solvability_roadmap`), t0 변형(randSeed 구동)에는 부적합.

---

## 2. 봇 (휴리스틱 시뮬레이터) — `core/bot_simulator.py`, `models/bot_profile.py`, `core/mc_difficulty.py`

### [코드] 봇 종류 (프로필 파라미터)
| 봇 | mistake | lookahead | patience | pattern_rec | 위치 |
|---|---|---|---|---|---|
| novice | 0.45 | 0 | 0.2 | 0.15 | `models/bot_profile.py:82-93` |
| casual | 0.25 | 1 (fast 0) | 0.35 | 0.35 | `:105-116`, fast `:198-209` |
| average | 0.12 | 2 (fast 1) | 0.5 | 0.6 | `:128-139`, `:212-223` |
| expert | 0.03 | 5 (fast 2) | 0.8 | 0.88 | `:151-162`, `:226-237` |
| optimal | 0.0 | 10 | 1.0 | **0.99** | `:174-187` |
- 수 선택 (`bot_simulator.py:4087-4175`): attention 필터(pattern_rec<0.85 이면 깊은 레이어 수를 확률적으로 숨김, `:3796-3878`) → dock panic(독 점유 임계 이상이면 mistake↑/lookahead↓, `:3942-4002`) → `rng<mistake` 면 **완전 랜덤 수** (`:4106-4107`) → 위험수(-100 이하) 제외 → 매치 완성 수 있으면 최고점 → patience<0.5 면 상위 일부 중 랜덤(`:4132-4136`) → lookahead>0 이면 `_estimate_future_score` 로 후보(최대 3~7개, `:4218-4274`) 평가, 실효 깊이 = min(적응깊이 2~8, lookahead) (`:4177-4216`).
- `_optimal_perfect_information_strategy`(숨은 정보 사용)는 `pattern_recognition >= 1.0` 일 때만 (`:4150`) — **optimal 프로필은 0.99 라 이 경로를 안 탐**. 즉 "optimal" 도 휴리스틱 봇이며 해법 존재 증명 능력 없음.
- MC 스킬 스윕(현재 주력 '난이도' 지표, 내부 명칭 RL): θ∈[0,1] 를 novice↔expert 앵커 사이 선형 보간 (`core/mc_difficulty.py:24-40, 113`), 그리드 8점 `[0,0.15,…,1.0]`, **점당 64판**, 기본 시드 4242 (`:42-46`). 산출: 곡선, `predicted_clear_rate`(θ~N(0.47,0.18) 가중평균, `:67-79`), `difficulty_score=1-AUC`, `theta_star`, 로지스틱(θ0,k), `luck_suspect`, 점별 Wilson `ci_half_width` (`:134-143, 268-391`).

### [코드] 시뮬 횟수·조기종료
- `simulate_with_profile(iterations=100, early_termination=False)` (`bot_simulator.py:778-787`). 조기종료: ≥5판 후 0%/100% 이면 중단, ≥10판 후 ≥90% 또는 ≤10% 면 중단 (`:775-776, 896-933`).
- `/api/analyze/autoplay`: 기본 iterations=100(`models/schemas.py:488` [agent]), 봇 = `VALIDATION_BOT_PROFILES`=[average, expert, optimal] (`analyze.py:65` [agent], `:727-730`), **early_termination=True 고정** (`:744-747`).
- `/api/generate/validated`: 레벨 등급별 적응 iterations S=8/A=12/B=18/C≥20/D≥25, 재시도 기본 5 (`api/routes/generate.py:1589, 1618`, `schemas.py:590-592` [agent]).
- MC 스윕도 `early_termination=True` (`mc_difficulty.py:286`).
- ⚠️ 조기종료 때문에 **쉬운 쪽(≥90%) 변형끼리, 어려운 쪽(≤10%) 변형끼리는 10판 근처에서 멈춰 구분 불가**. 변형 비교용으로는 조기종료 off 필요.

### [코드] 무작위성·시드 제어
- 봇 의사결정·개구리·텔레포트 모두 `self._rng = random.Random()` 하나 (`bot_simulator.py:772, 2732, 2869, 4106` 등).
- `seed` 인자 주면 판 i 마다 `_rng.seed(seed+i)` (`:807-808, 865-866`) → **randSeed≠0 레벨은 전체 결정적 재현 가능**. MC 스윕은 점별 `seed+idx*1000` 공통난수(CRN) (`mc_difficulty.py:326`) — 레벨 간 비교 분산 감소 의도.
- `seed=None` 경로: `_verify_single_level` (`analyze.py:846`) → 비결정.
- 🔴 **randSeed=0 함정**: `honor_zero_seed=False`(기본) 주석은 "seed 0 을 고정 시드로 사용"이라 하나 (`:797, 823-857`), 실제 `zWellRandom(0)` 은 `time.time()` 시드 (`:42-45, 309`) → **초 단위로 t0 배치가 바뀜**. 즉 randSeed=0 레벨은 같은 seed 로 돌려도 재현 안 되고, 한 호출 안에서는 배치 1개만 평가(배치 분포를 못 봄). `honor_zero_seed=True` 면 판마다 다른 randSeed(1~999999)로 배치 분포 평가 (`:830-855`).

---

## 3. 에디터 시뮬 규칙 vs 실제 게임 규칙

게임측 근거는 `01_client_findings.md §5` (경로 접두 `Assets/08.Scripts/Tile_Script/InGame/`). 에디터측 `core/bot_simulator.py` 줄. "봇"=`_play_game` 경로, "솔버"=`solver.py` 경로.

| 항목 | 게임 | 에디터 봇 | 에디터 솔버 | 판정 |
|---|---|---|---|---|
| 트레이 칸 수 | 7 (`Dock.cs:559`), key 수 기반 잠금 floor(key/3), AddSlot 부스터 +1 | 7 − `unlockTile` 잠금 (`:1012-1020`), key 3매치마다 1칸 해제 (`:2574-2581`) | 봇과 동일 | ≈ (잠금 수 원천이 key 개수 vs unlockTile 필드 — 대부분 일치, 불일치 레벨은 미확인) |
| 매치 | 같은 tileIDNum 3개 제거 | 같은 tile_type 3개 제거 (`:2537-2559`) | 동일 | ✔ |
| 패배(트레이) | Σ종류(count%3) ≥ 용량, 매치 진행분 제외 (`Dock.cs:2525-2560`) | 매치 처리 후 Σ(count%3) ≥ max_dock_slots (`:1840-1852`, 순서 `:2497-2498`→`:1808`) | 동일 | ✔ (3번째 매치 타일 생존 규칙 일치) |
| 승리 | 보드 미픽 0 & dock 비어있음 | + goals_remaining 전부 0 (`:1795-1801, 1782-1789`) | 동일 | ≈ (goal/unlock 잔존 시 에디터만 클리어 불가 — 메모리 `_normalize_goal_unlock` 이력) |
| 이동 제한 | 없음 | `moves_used ≥ max_moves` 패배 (`:1819` 부근) — max_moves=타일수+50 또는 `_calculate_max_moves`≥총타일 (`:811-821`, `analyze.py:375`) | 무력화(+100) | ≈ (상한이 충분히 커서 영향 작음) |
| 덮임 | 상위 전 레이어, 홀짝·col 비교 4칸 규칙 (`DB_Level.cs:751-835`) | 동일 규칙 (`:2125-2169, 2309-2393`) [agent+부분 확인] | 동일 | ✔ |
| 스택 내부 덮임 | 상위 레이어 검사 안 함, 위 스택 타일만 (`Tile.cs:1390-1438`) | `upper_stacked_tile_key` 만 검사 (`:1559-1573`) [agent] | 동일 | ✔ |
| craft 배출 | 배출칸 1개씩, **박스가 덮이면 배출 정지** | 배출칸 비면 배출 (`:1598-1669, 1671-1722`); 박스 덮임 검사 코드 못 찾음 | 막혔다 풀린 배출 **미처리** | ⚠️ 박스 덮임 미확인 / 솔버 ✘ |
| ice | 시작 3, 노출 상태에서 다른 타일 클릭마다 −1 (덮던 타일 클릭은 미카운트) | 3 고정 (`:1200`), 픽 **전** 노출된 ice 만 −1 (`:2401-2418, 2596-2612`) | 동일(`_apply_move` 내) | ✔ |
| grass | 2, 같은 레이어 4방 이웃 클릭(노출 시) | 2 (`:1209`), 4방, 노출 시만 (`:2614-2637`) [agent] | 동일 | ✔ |
| chain | 동/서 이웃 클릭 1회 | 동/서 이웃 픽 시 unlocked (`:2651-2654`) [agent] | 동일 | ✔ |
| link | 둘 다 노출 필요, 함께 수집 | 동일 (`:2420-2492, 2659-2679`) | 동일 | ✔ |
| curtain | 노출 상태 다른 클릭마다 토글 | 이동 전 노출된 것만 토글 (`:1760-1772, 2794-2808`) | **미처리**(UNRELIABLE→IMPOSSIBLE만 강등) | 봇 ✔ / 솔버 ✘ |
| bomb_N | N = `spInteger.Parse(effect)` **제한 없음** (`TileEffect.cs:570`), 0 → 즉시 패배 | N 을 **3~5 로 클램프** (`:1229-1240`), 이동 전 노출된 폭탄만 −1 (`:1744-1758, 2766-2788`) | **미처리** | ⚠️ N∉[3,5] 면 봇도 불일치 / 솔버 ✘ |
| teleporter | 3클릭마다 Sattolo, 무시드 `System.Random` (`TileGroup.cs:2040, 2070-2074`) | 3클릭마다 Sattolo, `self._rng` (`:2818-2878`) | **미처리** | 봇 ≈(분포 동일 가정) / 솔버 ✘ |
| frog | 매 클릭 후 노출 타일로 랜덤 점프, 무시드 `UnityEngine.Random` (`FrogManager.cs:185`) | `_rng.shuffle` 후 배정 (`:2681-2754`) | **미처리** | 봇 ≈(후보 조건 일치 미확인) / 솔버 ✘ |
| unknown | 덮인 동안 종류 숨김, 노출되면 픽 가능 | 규칙상 일반 타일, 봇 점수에 조기노출 보너스 (`:3696-3700`), 정보 차단 플래그 (`:654`) | 일반 타일 | ✔(규칙) |
| key 타일 | tileIDNum 16, 3매치 시 슬롯 해제 | "key" 타입 매칭 + 해제 (`:2574-2581`), 판정 `solver.is_key_tile` 게임식 (`solver.py:40-57`) | 동일 | ✔ |
| 기믹 불가능 즉시 패배 | grass/chain 이웃 부족, ice 잔여>활성 타일 (`GameController.cs:2772-2779`) | `_check_grass/ice/chain_impossible` (`:1854-1975`) | 동일 | ≈ (세부 조건 대조 미확인) |
| 제한시간 timea | 있음(현재 level_341 만 180s) | **미모델** (grep 0건) [agent] | 미모델 | ✘ (영향 1레벨) |
| 부스터 | Undo/UndoSet/Shuffle/Hint/AddSlot, 부활(보드 유지) | **미모델** [agent] | 미모델 | ✘ (평가 관점 A 는 무부스터라 의도와 일치, B 는 과소평가 방향) |
| t0 분배 | `ShuffleEmptyTiles` (zWellRandom, emptyTiles 순서=레이어순+JSON 키 삽입순) | `TileDistributor.assign_t0_tiles` 포트 (`:112-375`) | 동일 포트 | ⚠️ **비트 일치 미검증**(01 미확인 #3). 변형=randSeed 구동이면 에디터가 평가한 배치 ≠ 게임 배치 위험 |
| randSeed=0 | 시간 기반(초) → 매 판 다른 배치 | 시간 기반(초) — 주석과 달리 고정 아님 (`:42-45, 309`) | 동일 | ✔(동작) / 평가 재현성 ✘ |

**Top 5 차이(변형 평가 영향 순)**
1. 솔버가 턴 후처리(bomb/curtain/frog/teleport/막힌 craft 재배출) 미호출 → 해당 기믹 레벨의 SOLVABLE/IMPOSSIBLE 신뢰 불가.
2. t0 분배 포트의 게임 비트 일치 미검증 → randSeed 변형은 "에디터가 본 보드 = 게임 보드"가 전제인데 미보장.
3. 부스터·부활 미모델 → 봇 성공률은 무부스터 1회 시도 기준(실유저보다 낮게 나오는 방향, 레벨·변형 간 균일하지 않을 수 있음).
4. bomb_N 클램프(3~5) → 게임 데이터에 N∉[3,5] 있으면 봇 결과 왜곡.
5. 텔레포트/개구리 RNG 출처 차이(게임 무시드, 에디터 시드 가능) + craft 박스 덮임 처리 미확인.

---

## 4. 지표 지원 현황

| 지표 | 상태 | 위치 | 추가 난이도 / 메모 |
|---|---|---|---|
| 봇별 성공률 | **있음** | `BotSimulationResult.clear_rate` (`bot_simulator.py:589-615`), autoplay `bot_stats` (`schemas.py:621` [agent]) | — |
| 스킬 곡선·모집단 성공률 | **있음** | `mc_difficulty.assemble_sweep_result` (`:338-391`): 곡선, `predicted_clear_rate`, `1-AUC`, θ*, θ0/k | 상대 지표로 바로 사용 가능. "유저 클리어율" 명칭은 오해 소지(원칙상 상대 지표로만) |
| 시도 횟수 | **부분** | `iterations`(실제 돌린 판 수, 조기종료 반영) (`:883-887`) | "클리어까지 평균 시도"는 없음 → 1/p 로 파생 가능(쉬움) |
| 진행도(실패 시 얼마나 갔나) | **부분** | `avg_tiles_cleared`, `avg_moves`, `std_moves` (`:878-894`) | 성공·실패 섞인 평균. 실패판만 분리 필요(쉬움) |
| 트레이 최대 점유량 | **없음** | `GameState` 에 dock 이력 필드 없음 (`:515-572`), 결과에 미집계 | 쉬움: `_play_game` 루프(`:1726-1778`)에서 `len(dock_tiles)` 최대/히스토그램 기록 → 결과 dataclass·프로세스풀 반환 경로 3곳 수정 |
| 위기 상태 빈도 (예: dock ≥ 용량−1) | **없음** | 봇 내부는 dock_count 로 panic 계산만 (`:3942-4002`) | 쉬움(위와 동일 지점). '위기→생존' 비율도 같이 가능 |
| 실패 원인 분류 | **없음** | `_is_game_over` 는 `failed=True` 만 세팅 (`:1793-1838`) | 쉬움: 사유 enum 기록(dock/bomb/grass/ice/chain/no-move/max_moves). 게임 `fail_reason` 이벤트와 대응 가능 (`01 §7`) |
| 기본 맵 대비 변형 차이 | **부분** | `/api/tune/tilecount` (`api/routes/tune.py:805-900`): useTileCount 만 변경(t0 레벨) 또는 V색 재배색(concrete), 기본 ±2 제한, `evaluate=True` 면 원본·조절본을 같은 시드로 스윕. `/api/tune/gimmick`도 [(0,원본),(1,변형)] 쌍 스윕 (`:519-531`) | **변형 생성+쌍비교 골격이 이미 있음**. randSeed 축 변형·N개 후보 일괄·차이 신뢰구간은 없음(중간) |
| 실수 내성(A* 기반) | **있음(실험적)** | `measure_robustness` (`solver.py:448-553`) | 노이즈 큼(아래 §4-1), 레벨당 20~200s |
| 평가 변동성 | **부분** | 점별 Wilson `ci_half_width` (`mc_difficulty.py:134-143, 290`); 주석 실측 "재측정 std 1.8%p" (`:52`) | 후보 간 **차이**의 CI/검정 없음(중간). CRN 시드는 있음(`:326`) |
| 해법 존재(A) | **부분** | `solve_level` 3값 판정 (`solver.py:201-368`) | §1 결함 수정 전엔 bomb/curtain/frog/teleport/craft 레벨 신뢰 제한 |

### 4-1. [실측 — 기존 결과 파일] 색 종류(V) 스윕의 실수 내성 (`data/night_study.json` vsweep, max_depth 10 / move_cap 5)
- Lv710: V3~5=1.0, V6=0.94, V7=0.78, V8=0.96, V9=0.68, V10=0.72, **V11=1.0**, V12=0.94, V13=0.73. Lv790·1268 도 비단조, V10/V13 은 측정 불가(전부 미확정) 사례.
- ⇒ ±1 V 차이를 `measure_robustness` 단일 경로·소표본으로 서열화하는 것은 **신뢰 불가**(값이 0.2 단위로 양자화: move_cap 5 → 안전수/결론수 비율). 레벨당 19~206s.
- 같은 파일 corr: RL 예측(MC 스윕)과 실수내성 Spearman ρ=0.705 (n=43, 60 중 17 미확정).

### 4-2. [제안] 후보 간 차이 신뢰도 — 필요 시행 수 추정 (독립 표본 근사)
- 두 후보 클리어율 차 Δ 검출(양측 α=0.05, 검정력 0.8), p≈0.5 최악: n/후보 ≈ 7.84·2p(1−p)/Δ² = 3.92/Δ².
  - Δ=0.15 → ~175판, Δ=0.10 → ~390판, Δ=0.05 → ~1570판 (스킬점 1개 기준).
- 현행 MC 스윕은 점당 64판(점별 95% 반폭 ≈ ±0.12 @p=0.5) — 점 단위로는 Δ≈0.2 이상만 구분. 8점 가중합(`predicted_clear_rate`)은 유효 표본이 커서 재측정 std 1.8%p 수준(주석 실측, 조건 미상).
- CRN(같은 seed+i) 쌍비교로 분산 추가 감소 가능하나, 보드가 달라지면 봇 난수 소비 경로가 바로 갈라져 상관이 얼마나 남는지는 **미측정**.
- 조기종료(≥90%/≤10% 에서 10판 중단)는 변형 비교 시 반드시 off.

---

## 5. 평가 비용

### [실측] 단건 (이번 조사, 10코어 Mac, 단일 프로세스, 55s 이내)
| 레벨 | 타일 | utc | θ=0.47 (판당) | θ=1.0 (판당) | 솔버 60000/5s |
|---|---|---|---|---|---|
| 710 | 111 | 13 | 0.009s (8판 0%, 조기 실패) | 0.117s (25%) | UNCERTAIN 768노드 5.85s |
| 1268 | 138 | 13 | 0.024s (0%) | 0.107s (0%) | SOLVABLE 171노드 4.24s |
- 판당 비용은 봇이 오래 버틸수록(쉬운 변형·고스킬) 증가 → **쉬운 변형일수록 평가가 비쌈**. 상한 근사 ~0.12s/판(lookahead 5 + 적응깊이).

### [코드] 기본값
- MC 스윕: 8점 × 64판 = 512판/레벨 (`mc_difficulty.py:42-45`), 풀 워커 = min(10, cpu−2) = 8 (`api/routes/rl_sim.py:49`).
- autoplay: 3봇 × 100판(조기종료) (`analyze.py:727-747`), 풀 min(5,cpu) (`bot_simulator.py:376-382`).
- 솔버: 검증 경로 12s/300k 노드 상한 (`analyze.py:896`), 실측 평균 ~3.2s/레벨(8s 상한, `night_study`).

### [제안] 규모 추정 (t_game ≈ 0.06s 평균 가정, 8워커)
- 후보 1개 MC 스윕(512판): ~30 CPU-s ≈ **4~5s wall**.
- 비용 ≈ 레벨 수 × N(후보) × M(스킬점) × K(판) × t_game / 8.
| 시나리오 | N | M×K | 레벨당 wall | 1500레벨 |
|---|---|---|---|---|
| 현행 정밀도 (base, ±1) | 3 | 8×64 | ~12s | ~5h |
| ±1 × randSeed 5개 | 15 | 8×64 | ~60s | ~25h |
| Δ=0.1 구분 목표 (점 3개×400판) | 3 | 3×400 | ~27s | ~11h |
| Δ=0.1 + randSeed 5개 | 15 | 3×400 | ~135s | ~56h |
- 솔버(A) 추가: 후보당 평균 ~3s(상한 12s) / 1코어 → 8병렬 시 1500×3후보 ≈ 30분~2h. robustness 는 후보당 20~200s → 대량 적용 비현실적.
- 수치는 2레벨 단건 실측 + 기본값 기반 대략치. 기믹·타일 수에 따라 수 배 차이 가능(**미검증**).

---

## 6. 정적 분석 점수 / 동적 목표 클리어율의 변형 분류 재사용

### [코드]
- 정적 점수 `LevelAnalyzer._calculate_score` (`core/analyzer.py:326-347`): 총타일×0.5, 활성레이어×4, goal×1.5, 레이어블로킹×0.15, 기믹점수, **max(0, 종류수−8)×8**, max(0, 타일/max_moves−2)×15, 합/3.
  - 종류수: t0 있으면 `useTileCount`, 없으면 실제 t1~t15 종류 수 (`analyzer.py:178-183`). **randSeed 미사용**, 배치(위치별 색) 미사용.
  - ⇒ 같은 구조 변형에서 점수 차는 **종류수 >8 일 때 ±1종당 ±2.67점**, ≤8 이면 **0**. randSeed 변형은 항상 동점.
- 동적 목표 클리어율: `calculate_target_clear_rates(td)` + 기믹 페널티 `calculate_adjusted_target_rates` (`api/routes/analyze.py:176-200, 210~`), td 미지정 시 `static_score/100` (`:713-720, 817-818`). MC 경로는 `TARGET_CLEAR_CURVE` (`mc_difficulty.py:57-62`).
  - 용도는 "이 레벨이 의도 난도에 맞나" 합격 판정(목표-실측 gap) — 변형 간 서열 지표가 아님.

### [제안] 재사용 판단
- 정적 점수: 변형 분류 **부적합**(randSeed 변형 구분 0, ±1종도 >8 구간만 소폭). 기본 맵 대비 "종류 수 방향" 사전 필터 정도로만.
- 동적 목표 클리어율: 분류 기준선으로 쓰면 **순환 위험**(목표 자체가 정적 점수에서 파생 → 정적 점수가 못 보는 차이를 목표도 못 봄). 또 곡선 값이 '유저 클리어율'처럼 표현돼 있어 원칙(봇 성공률≠유저 클리어율)과 충돌.
- 변형 서열은 **MC 스윕의 `1-AUC` 또는 `predicted_clear_rate` 를 기본 맵과의 쌍 차이로** 쓰는 게 현 코드에서 가장 가까운 경로(`/api/tune/tilecount evaluate=True` 패턴). 절대값이 아니라 Δ와 그 CI로 쉬움/기본/도전 분류.

---

## 7. 종합 [제안]

- **A (무부스터 해법 존재)**: 부분 가능. 기본 기믹(ice/grass/chain/link)·스택 레벨은 SOLVABLE 신뢰, UNCERTAIN ~24% 는 '미확인'으로 남김. bomb/curtain/frog/teleport/막힌 craft 는 솔버 후처리 결함 수정 전까지 SOLVABLE·IMPOSSIBLE 모두 '미확인' 취급. 수정 방향: 솔버 child 생성 시 봇 `_play_game` 과 같이 이동 전 노출 bomb/curtain 수집 → `_process_move_effects` 호출, 시그니처에 curtain/frog/teleport 카운터 추가. frog/teleport 는 확률 분기라 결정적 완전탐색 대상 아님(기대값/표본 처리 필요).
- **B (일반 전략 성공률)**: 가능(상대 지표). MC 스킬 스윕이 규칙 정합 높은 봇 경로를 쓰고, 시드 고정(randSeed≠0) 시 재현 가능. 변형 비교엔 조기종료 off + 쌍비교 + 차이 CI 필요.
- 전제 조건: (1) **t0 분배 포트 ↔ 게임 비트 일치 검증**(같은 randSeed/useTileCount 로 에디터 배치 vs 기기 배치 대조) — 안 되면 평가 대상 보드 자체가 틀림. (2) 변형은 randSeed≠0 고정(0 이면 게임·에디터 모두 매 판 랜덤).
- 계측 추가(쉬움): dock 최대 점유/위기 빈도/실패 원인 — `_play_game` 1곳 + 결과 전달 경로.

---

## 미확인 목록

1. 솔버 막힌-craft 재배출 누락이 실제 false PROVEN_IMPOSSIBLE 을 낸 사례(코드 경로만 확인).
2. 솔버의 bomb 레벨 false SOLVABLE 실사례.
3. `_fast_copy_state` 가 `tiles` 와 `stacked_tiles` 를 별도 객체로 복사(`bot_simulator.py:2208-2286`) → 스택/craft 의 같은 타일이 두 객체로 갈림. `_emit_blocked_craft_tiles` 가 `stacked_tiles` 쪽 picked 를 보므로 봇·솔버 모두 craft 재배출이 어긋날 가능성 — 동작 미검증.
4. craft 박스가 상위 레이어에 덮였을 때 배출 정지 규칙의 에디터 구현 여부.
5. 게임 데이터 bomb_N 의 N 분포(3~5 밖 존재 여부).
6. key 슬롯 잠금 수: 게임(key 개수 기반) vs 에디터(`unlockTile` 필드) 불일치 레벨 존재 여부.
7. frog 점프 후보 조건, curtain 잔여 특수 규칙, 기믹 불가능 즉시패배 세부 조건의 게임↔에디터 일치(일부 agent 보고 기반).
8. t0 분배 포트(`TileDistributor`)의 게임 비트 일치 (01 미확인 #3 과 동일 — 에디터측에서도 미검증).
9. CRN 쌍비교의 실제 분산 감소 폭, `predicted_clear_rate` 재측정 std 1.8%p 의 측정 조건.
10. 판당 시뮬 비용의 레벨 분포(이번 실측 2레벨뿐), 기믹 많은 레벨의 솔버 시간.
11. generate/validated 재시도·적응 iterations 줄번호(`generate.py:1589, 1618`, `schemas.py:590-592`)는 하위 에이전트 보고(직접 미열람). autoplay 기본 100판(`schemas.py:491`, seed 기본 None `:496`)·`VALIDATION_BOT_PROFILES=[average,expert,optimal]`(`analyze.py:65`)은 직접 확인. (주석 `analyze.py:726` 의 "CASUAL/AVERAGE/EXPERT" 는 코드와 불일치)
