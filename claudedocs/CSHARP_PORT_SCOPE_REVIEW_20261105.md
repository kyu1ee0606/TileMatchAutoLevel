# C# 이식 범위 조사 — 봇 시뮬 외 나머지 이식 가능성 (2026-11-05, 읽기 전용 조사)

작성: 하위 세션 "C#이식범위조사". 코드·빌드·실행 없음(파일 읽기·git 읽기·`ps`·`ls` 만). 이 문서가 유일한 산출물.
표기: **[사실]** = 이번에 파일/명령으로 직접 확인, **[문서]** = 계획·README 기록 인용(재확인 안 함), **[추정]** = 읽은 코드에서 추론, **[미확인]** = 확인 못 함.
기준 문서: `claudedocs/PLAN_CSHARP_ACCELERATION_20261102.md`(§1-2, §2, §5, §8), `~/tilecore/README.md`, `~/tilecore/release/README_v6.md`.

---
## 0. 결론

1. **바로(추가 C# 작업 없이) 연결 가능한 것은 "BotType 4종 + optimal 을 쓰는 `simulate_with_profile` 호출처"** — 생성기 교착 검사 2곳, `/generate/validated` 검증 봇, batch-verify, autoplay(이미 shadow). 그러나 **C# 쪽은 요청당 서브프로세스 CLI 뿐(상주 `serve` 없음)** 이라 "작은 호출이 많은" 생성기·검증 루프는 서브프로세스 기동(~0.1 s)이 파이썬 비용과 비슷해져 **상주 워커가 선행 조건**이다 [사실: Program.cs 에 `serve` 없음, tilecore_bot.py 요청당 CLI].
2. **우선순위(가치 ÷ 추가 작업)**: ① `serve` 상주 워커 + 어댑터 → ② 생성기 교착 검사(`generate()` 시간의 97~99%, gen_optimal 프로필은 이미 검증됨) → ③ 검증 생성 루프·batch-verify·enhance(같은 어댑터) → ④ solver.solve_level(BotSimulator 규칙 A* 가 C# 에 **없음** — 새 구현) → ⑤ MC/RL/tune(v1~v2.3 프로필 정책 추가 필요). 생성기 본체·정적 분석·t0 는 시간 비중이 낮거나 이미 별도 포팅이 있어 **이식 불필요**, `simulator.py` 는 레거시라 **비추천**.
3. **현재 `on`(C# 결과 실사용)은 어디에도 없다.** 연결된 것은 shadow 2곳(autoplay 봇, solve_level)뿐이고, 이 서버에서 켜진 흔적은 없다(아래 §1-3).

---
## 1. 현재 이식·연결 상태

### 1-1. C# 쪽 구현 범위 (`~/tilecore`, git 저장소 아님·커밋 없음 [사실: `git log` → not a git repository])
| 항목 | 상태 | 근거 |
|---|---|---|
| PyRandom(MT19937 CPython 비트 일치) | 완료, 벡터 89,528줄 일치 [문서] | README 구성 표 |
| T0 TileDistributor + zWellRandom | 완료, 25,000건 일치 [문서] | README ① 코드 표 |
| CsShuffle(Pv/CsShuffle.cs, 열쇠 배정) | v2 에서 완료 [문서] | README 릴리스 표 |
| BotSim 규칙(`bs` 모드) | stack/craft/링크/얼음/풀/체인/폭탄/커튼/열쇠/개구리/텔레포터/냥이의 도움(auto_collect, v4) [문서] | README ① |
| 봇 정책 | 점수·선택·v2.1 인지·v2.4 기본(V24_DEFAULT 12항목)·θ>1 롤아웃 [문서] | README ① 코드 표 |
| 프로필 | `optimal_par`, `v24_<θ>`(any θ), `gen_optimal`, 맵툴 BotType 4종(novice~expert), `acv24_<θ>`; `skill_<ver>_<θ>`(v1/v2/v2.1/v2.3)는 **값만 있고 shadow 미검증** [문서] | README_v6 §1, README 남은 일 |
| CLI | `dda`(대량), `bot`(작업 단위), `profile`, `bake`. **`serve`·`solve`·`sweep`·`judge`(bs 규칙) 없음** [사실: Program.cs `args[0]` 분기 grep] | Program.cs:22-24 |
| 속도 | v6 1스레드: 그리디 CPU 26.7×·판 중앙 52×, θ1.3 CPU 58.7×·판 중앙 71×(load 3.6~6 교대 측정, 유휴 단독 아님); 큰 배치 8스레드 3.75배 [문서] | README 속도표 측정 3 |
| 동일성 | R2 2,340칸(140,400판) rate·첫 클리어 rngSeed·경로 100%, 매 수 대조 shadow 4,008판+보스 560판 불일치 0 [문서] | README |
| 릴리스 | v1~v6 (`release/v6` 가 최신, 11-02 21:20 이후 코드·릴리스 추가 **없음**) [사실: `find ~/tilecore -newermt "2026-11-03 11:10"` → 0건] | |

### 1-2. 미지원(호출하면 `unsupported` 로 거절 → 파이썬이 처리) [사실: Policy/Rules/Init/PyVal 의 `UnsupportedException` grep + 문서]
- `pattern_recognition ≥ 1.0` 프로필(optimal 완전정보 전략 미이식; OPTIMAL 은 0.99 라 해당 없음) — BotSim.Policy.cs:67
- V24_DEFAULT 밖 v2.4 항목(`curtain_memory_v24`·`ac_policy`·`skill_planning`·`public_*`·`covered_info` 등), gimmick_awareness 추가 키 — Policy.cs:34,42,44; Rules.cs:242
- t0 칸이 있는데 `randSeed ≤ 0` (파이썬 TileDistributor 가 `time.time()` 시드 — 파이썬 자체가 재현 불가) — Init.cs:262
- 파이썬이 TypeError/NameError 를 내는 입력(col str/int 혼합, 비문자열 타일 id, goal 타입 일반 타일 등) — PyVal.cs, Init.cs:146,231
- 핵심: **봇 결과 중 클리어/실패/수(moves)만 출력** — `avg_combo`, `avg_tiles_cleared`, `std` 는 CLI 출력에 없음 [사실: Program.cs:97 출력 필드 `cleared/failed/moves/ms`(+trace 시 path/final)]. `final` 스냅샷에서 얻을 수 있는지는 [미확인]. `sweep_point_task` 는 `avg_tiles_cleared` 를 반환하므로 필요.
- 기믹 미지원 목록은 따로 없음(전 기믹 이식됨) [문서].

### 1-3. 맵툴 쪽 실제 연결 지점과 스위치 상태
| 지점 | 파일:줄 | 스위치 | 상태 |
|---|---|---|---|
| `solver.solve_level` → `tilecore_shadow.shadow_solve` | solver.py:205-221 (`_solve_level_py` 분리 :224) | `TILECORE` off/shadow, `on` = shadow 취급 | shadow 전용. **C# 은 FastJudge(fengine `--rules game`) — BotSimulator 규칙이 아님** [사실: tilecore_shadow.py 헤더 3-27] |
| `/api/analyze/autoplay` 봇 청크 | analyze.py:555-600(`_run_bot_sim_chunk`), :636-645(`_run_profiles_parallel` 내 `tilecore_bot.submit`) | `TILECORE_BOT` → `TILECORE` → off | shadow 전용(`on`=shadow). v6 `tilecore bot` mode gen, 요청당 서브프로세스, 백그라운드 스레드 1·큐 16 [사실 tilecore_bot.py:1-45,291-304] |
| 신규 모듈 | core/tilecore_bot.py(354줄), core/tilecore_shadow.py(357줄) | — | 둘 다 **메인 폴더에 있음, 미커밋(`??`)**; solver.py·analyze.py 도 미커밋(`M`) [사실: git status] |
- **스위치 현재 값**: 실행 중 uvicorn(PID 95448, `--reload`)의 환경에 `TILECORE*` 변수 없음 [사실: `ps eww` 출력 → 변수 0개] → **off**. `~/tilecore/shadow/` 에 `bot_shadow_diff.jsonl`·`solver_shadow_diff.jsonl` 없음 [사실: ls] → 서버에서 shadow 가 켜진 적 없음. (단 worktree `claudedocs/tilecore_bot_shadow_20261103/` 에 소규모 오프라인 로그 2개 존재 [사실: ls].)
- 위 두 모듈·훅이 **본 폴더에 복사 반영됐고 worktree `~/TileMatchAutoLevel_wt_tilecore`(브랜치 `tilecore-shadow-20261103`)에는 HEAD 68b4028 위 미커밋 상태** [사실: git status/log] — 이 브랜치에 별도 커밋은 없음.
- `solve_level_task` 가 `time_budget_s` 를 넘기도록 수정됨(plan §5 끝 "빠른 효과" 항목): solver.py:407-414 [사실] → 계획 문서의 solver.py:374 줄 번호는 이동.

---
## 2. 후보별 판정

판정: **바로 가능** / **추가 작업 후 가능** / **불필요·비추천**. "공통 선행"은 아래 §3 참고.

### 2-1. solver.solve_level / measure_robustness (A* 판정) — **추가 작업 후 가능 (규모 큼)**
- (a) 재사용: BotSim 의 `_get_available_moves`·`_apply_move`·`_fast_copy_state` 등가 규칙(Rules.cs/Init.cs) [문서·추정]. FastJudge Search(해시·빔·가지치기)는 **fengine 상태 위**라 BotSimulator 규칙 상태에는 못 붙임 [추정].
- (b) 필요: ① BotSim 상태용 A*(서명 = `_state_signature` solver.py:162, 복사 = :186 `_copy_state`, dock 필드 보강 포함) 신규 구현 ② 판정 범주 PROVEN_SOLVABLE/IMPOSSIBLE/UNCERTAIN 규칙(무작위 기믹 IMPOSSIBLE 불가, solver.py:36) 어댑터 ③ `serve` ④ measure_robustness 는 `_get_available_moves` 직접 호출·`_solvable_from_state`(solver.py:445) 사용 → 상태 단위 API 필요(수 생성·적용·solve) — study 라우트 전용. 현재 FastJudge shadow 는 규칙이 달라(DIFF.md #4~#8b) 동일성 게이트 §0-A ② 를 통과할 수 없음 [추정].
- (c) 교체 지점: solver.py:224(`_solve_level_py`) 본체; 호출처 analyze.py:909-912(batch-verify 실패, 300k/12 s), :1364-1365(/solvability), :1379-1387(`solve_level_task` 풀), rl_sim.py:339-340, reverse_generator.py:363-364(120k/6 s), pv/evaluate.py:144-147, study.py:79,124,166,203,232(measure_robustness) [사실: grep].
- (d) 가치: 파이썬 5 s 에 768 노드 → UNCERTAIN [문서 실측 prof_solver, 프로파일러 켠 상태]. 판정 확정 비율 향상이 목적(속도보다 판정 품질). measure_robustness 는 레벨당 ≈570 회 solve [문서 solver.py:440 주석] → 밤샘 study 13 h [문서].
- (e) **추가 작업 후 가능**, 단 신규 알고리즘 포트가 필요해 단일 항목 중 최대 규모(계획 ② 8~11 인일 중 대부분 [문서]). `bs` 규칙 A* 가 아닌 FastJudge 를 쓰는 대안은 규칙 불일치 때문에 **서비스 결과 대체 불가**, 참고 지표 shadow 로만 유효 [추정].

### 2-2. 생성기 교착 검사 `_quick_deadlock_check` / `_fix_same_type_blocking` (generator.py) — **추가 작업 후 가능 (최우선)**
- (a) 재사용: `gen_optimal` 프로필(플래그 없는 BotSimulator + OPTIMAL, `_fast_copy_state` 고속 경로, `max_moves = level.get("max_moves", maxMoves, 50)`) 이 정확히 이 두 호출을 위해 이식·검증됨 — production 67레벨×5판 315판 불일치 0 [문서 README ①(b)].
- (b) 필요: ① **상주 `serve`**(호출이 3~5판짜리 소형이라 서브프로세스 기동이 지배; `_fix_same_type_blocking` 은 최대 50시드×3판 반복, :16286-16296) ② 어댑터(`simulate_with_profile` 시그니처 → job JSON; 결과는 `clear_rate` 만 쓰임 :16419-16427, :16296-16300) ③ **`seed=None` 호출은 파이썬 자체가 비결정**(`BotSimulator()` 신규 → `random.Random()` OS 시드, bot_simulator.py:874-875; 호출 :16419-16426 `seed=None`) → shadow 동일성은 판 단위 일치가 아니라 **클리어율 분포 동등**으로 판정해야 함(계획 §0-A ③ 의 "생성 레벨 JSON 바이트 동일"은 이 경로에서 성립 불가 [추정]) — 시드를 명시하는 어댑터 옵션 필요 ④ unlockTile>0 은 v2 이후 지원, randSeed≤0+t0 는 unsupported → 파이썬 폴백.
- (c) 교체 지점: generator.py:16295(`_fix_same_type_blocking` 내 simulate), :16419(`_quick_deadlock_check`); 호출 상위 `_ensure_no_deadlock` :16671/:16738/:16743, 상위 `generate()` :1020~, 모양 보존 경로 :1906 [사실: grep, 줄 번호 확인]. 계획 문서의 :16412-16427 / :16275-16296 은 현재 :16419 / :16295 (소폭 이동).
- (d) 가치: generate() 3.1 s 중 3.11 s, 10.1 s 중 9.83 s 가 봇 [문서 실측 prof_generator] → 기대 0.2~0.5 s [추정]. 이식 후보 중 **사용자 체감(레벨 생성 시간)에 가장 직접적**.
- (e) **추가 작업 후 가능**(serve + 어댑터 + 분포 동등 판정). 프로필 정합성은 이미 검증된 범위.

### 2-3. `/generate/validated` 검증 루프 `_simulate_single_bot` — **추가 작업 후 가능 (2-2 와 같은 어댑터)**
- (a) 재사용: BotType novice/casual/average/expert/optimal. average·expert 등 4종 756판 불일치 0(생산 레벨 67×3판) [문서 README ①(c')] — 단 README 남은 일에는 "표본 검증 안 함"이라는 이전 문구가 남아 있어 **상충**; (c') 표가 더 늦게 추가된 실측으로 보임 [추정]. fast_mode 프로필(`get_profile(..., fast_mode=True)`, bot_profile.py:252-261)은 C# 검증 기록 [미확인].
- (b) 필요: serve + 어댑터; `early_termination`(통계 조기 종료) 의미를 C# 쪽에 구현하거나 파이썬이 판별 비트열로 재현하는 어댑터 필요 — tilecore_bot.py 가 이미 `early_termination` 인자를 받음(analyze.py:566-580) [사실]. 결과 필드 중 `clear_rate` 만 쓰임(generate.py:244-261).
- (c) 교체 지점: generate.py:244-261(`_simulate_single_bot`), 호출 :2197, :2603(리셔플), :2747(enhance) [사실: grep]. 풀 `_get_bot_pool`(:2193) 은 C# 워커로 대체 가능.
- (d) 가치: 기본 `simulation_iterations=0` 이면 검증 봇 없음(비용 = generate 만) [문서 §1-2]. 켜면 시도당 봇 3~5종×≤25판. 봇 1판 4~126 ms [문서 실측]. 이득은 켤 때만.
- (e) **추가 작업 후 가능**(2-2 완료 후 거의 무료).

### 2-4. `/generate/enhance` — **추가 작업 후 가능 (2-3 과 동일 경로)**
- (a)(b) `_simulate_single_bot` 재사용(generate.py:2743-2747) [사실]. (c) 교체 지점 동일. (d) 반복≤5×3봇×50판 [문서], 미측정. (e) 어댑터가 되면 자동 포함; 독립 작업 불필요.

### 2-5. reverse_generator — **일부 가능 (봇 15판은 바로, solve 는 2-1 에 종속)**
- (a) 봇 15판(optimal, `seed=12345`, early_termination, reverse_generator.py:328-333): 고정 시드·optimal 이라 **결정적 동일성 검증이 가능한 유일한 생성 경로** [사실: 코드]. optimal(parity 없음) = gen_optimal 과 같은 프로필 가정 [추정]. (b) 어댑터. solve_level(:363-364)은 2-1. (d) 미측정. (e) **추가 작업 후 가능**(봇 부분), solve 부분은 2-1 판정 따름.

### 2-6. `/analyze/batch-verify(-regenerate)` — **추가 작업 후 가능**
- (a) 3봇×20판 시뮬(analyze.py:857-866, `seed=None`, `early_termination`) = 2-2 와 같은 경로; 실패 시 solve_level(:909-912) = 2-1.
- (b) serve + 어댑터. `seed=None` → 분포 동등. 스레드 4 개(GIL)를 C# 다중 스레드로 대체 시 진짜 병렬 [문서].
- (c) analyze.py:857-866(sim), :909-912(solve), 엔드포인트 :953, :1032 [사실].
- (d) 미측정 [문서]. (e) 시뮬 부분은 2-2 이후 쉬움, solve 부분은 2-1 종속.

### 2-7. assess / difficulty_assessor — **추가 작업 후 가능 (낮은 우선순위)**
- 호출: `BotSimulator.assess_difficulty` → `simulate_with_profile` 래퍼(bot_simulator.py:1081 부근, assess.py:115). difficulty_assessor.py 는 `BotSimulator` 를 받아 사용(:91-99) [사실: grep]. 봇당 100판 [문서]. 어댑터가 `simulate_with_profile` 단위면 자동 적용 가능하나 **`avg_combo`·`avg_tiles_cleared` 출력이 C# 에 없음**(1-2) → 필요하면 CLI 출력 확장. 가치 낮음(요청 빈도·시간 측정 없음 [미확인]).

### 2-8. MC 난이도(mc_difficulty sweep) / mc_search / rl_sim / tune — **추가 작업 후 가능 (프로필 범위 확장 필요)**
- (a) θ>1 롤아웃 포함 `v24_<θ>`, `skill_*` 값 계산은 C# 에 있음. (b) 필요: ① **`make_skill_profile` 기본 `bot_version="v1"`**(mc_difficulty.py:113, sweep_point_task :294 `args.get("bot_version","v1")`; pv/evaluate.py `args.get("bot_version","v1")`) → v1/v2/v2.1/v2.3 정책 분기 **shadow 미검증** [문서: "값만, 미검증"]. 어떤 bot_version 이 실사용인지 호출 통계 [미확인] ② `avg_tiles_cleared`·`avg_moves` 출력 확장 ③ `honor_zero_seed=False`, `early_termination=True` 지원 ④ `serve`.
- (c) 교체 지점: mc_difficulty.py:284-300(`sweep_point_task`), :332-340(`run_skill_sweep`), rl_sim.py:108(`pool.map(sweep_point_task)`) + :339-340(solve), tune.py:136-158,328,521(`_parallel_point_sweep`), mc_search.py(직접 시뮬 없음 — 후보 생성 + 위 sweep 호출 [사실: grep 에 simulate 없음]) [사실].
- (d) 가치: θ1.3 판당 5,958 ms(파이썬) → C# 52 ms [문서] 로 격차 최대. MC 8점×64판 sweep 이 수 분 → 수 초 [추정]. **θ>1 가 지배적이고 C# θ>1 이 이미 검증·최적화됨** → v24 계열 sweep 만 먼저 이식하면 가치 대부분 확보 [추정].
- (e) **추가 작업 후 가능**: `v24` bot_version sweep 은 비교적 적은 작업(어댑터 + 출력 확장), v1~v2.3 은 정책 이식·검증 필요(계획 ③ 의 정책 버전 확장 4~6 인일 [문서]).

### 2-9. pv/evaluate (`_TrackingBot`) — **추가 작업 후 가능 (trace 옵션 필요, 가치 낮음)**
- `_TrackingBot._update_curtain_memory` 를 훅으로 매 턴 독 점유를 기록(evaluate.py:37-60) → wins/dockMax/crisisAny/crisisFrac 반환(:62-91). C# 에 독 점유 트레이스 출력이 없음 [사실: Program.cs 출력 필드]. `bot_version` 기본 "v1"(미검증 정책). `lj["max_moves"]` 필수 [사실 :68-73]. 오프라인 스크립트 [문서]. (e) 이식 시 C# 쪽 "턴별 독 점유 요약" 옵션 신규 + v1 정책 필요 → 우선순위 낮음.

### 2-10. 생성기 본체(패턴·레이어·기믹 배치) — **불필요·비추천**
- 근거: 생성 순수 부분 ≤0.3 s, 봇 호출이 97~99% [문서 실측 prof_generator]. generator.py 1.7만 줄 [문서]. 파이썬 쪽 로직이 계속 바뀌는 중(레벨 JSON 포맷·템플릿) — 동기화 비용 큼 [추정]. (e) **불필요**.

### 2-11. 정적 난이도 분석 `/api/analyze` (analyzer.py) — **불필요·비추천**
- 시뮬이 아닌 정적 점수 계산이며 BotSimulator 의존이 없음 [사실: `grep BotSimulator` 대상 파일 목록에 analyzer.py 없음]. 시간 측정 없음 [미확인]이지만 병목으로 보고된 바 없음. (e) **불필요**(필요 시 측정 후 재검토).

### 2-12. t0 분배 — **이미 이식됨(맵툴 연결 불필요)**
- C# `T0/TileDistributor`·zWellRandom 25,000건 일치 [문서]; 봇 내부(`_create_initial_state`)에서 사용. 맵툴 쪽 별도 `pv/cs_shuffle.py` + `tools/pv_golden`(net8)은 골든 파일용이며 병목 아님 [문서]. (e) 추가 작업 없음.

### 2-13. simulator.py(LevelSimulator, 레거시) — **불필요·비추천**
- `/simulate` 전용 옛 엔진 [문서 §2 J]. (e) 이식 안 함.

---
## 3. 공통 선행 작업 (여러 후보에 걸림)
1. **`tilecore serve` 상주 워커**(stdin/stdout JSONL, 다중 스레드) — 현재 없음 [사실]. 계획 §3-3 의 추천 방식. 생성기·검증 루프·batch-verify·MC 전부의 전제. 서버 프로세스 수명 관리(시작·헬스체크·재시작)는 맵툴 쪽 작업.
2. **`simulate_with_profile` 어댑터**(같은 시그니처): `seed=None` 처리(C# 에 임의 시드 부여 + 분포 동등 판정), `early_termination`, `honor_zero_seed`, `max_moves` 기본값(타일수+50), 결과 필드(`clear_rate/avg_moves/avg_combo/avg_tiles_cleared/std`).
3. **C# 결과 필드 확장**: combo/tiles_cleared (1-2).
4. **`on` 스위치 구현**: 현재 `on`=shadow. 파이썬 폴백(unsupported·오류·버전 불일치) 포함.
5. **정합성 게이트 재정의**: `seed=None` 경로(생성기·batch-verify)는 판 단위 일치 불가 → 분포 동등 기준(계획 §0-A ③ 의 ±3%p·판수≥300·Bonferroni 은 "제안값, 확정 필요" [문서 §8-2]).
6. 비밀·재현: C# 릴리스는 `release/v6` 고정, 맵툴은 `TILECORE_BOT_DLL` 로 지정(기본값 있음) [사실 tilecore_bot.py:21,44].

## 4. 계획 문서 대비 달라진 점
| 항목 | 계획(11-02) | 현재 |
|---|---|---|
| ① 봇 시뮬 | 계획 단계 | `bs` 모드 완료, 속도 기준(그리디≥20×, θ>1≥50×) 충족(교대 측정 한정) [문서 §8 진행] |
| ② solver 작업 | 상주 워커 + Judge 탐색 | **FastJudge(fe 규칙)로 shadow 만**; BotSimulator 규칙 A* 는 없음 → 계획의 "맵툴 판정 범주 어댑터(규칙 BS)"는 미착수 |
| 상주 `serve` | ② 에 포함 | **없음**(요청당 CLI) |
| solver.py:374 time_budget 누락 | 문제로 기재 | **수정됨** solver.py:407-414 |
| 줄 번호 | generator :16412-16427 / :16275-16296; generate :2192-2200, 2584-2606; solver `solve_level` | :16419 / :16295; :2197, :2603, 2747; solver :205(래퍼)+:224(`_solve_level_py`) |
| 호출처 | — | `generate.py:2743-2747`(enhance), reverse_generator :328, simulate.py:901/999, analyze.py:534/1986, bot_simulator.py:411/1081 래퍼 추가 확인 [사실: grep] |
| 맵툴 코드 상태 | worktree 브랜치 | 본 폴더에 `tilecore_bot.py`·`tilecore_shadow.py`·훅 반영됨(미커밋 `??`/`M`); 실행 중 서버 환경에 `TILECORE*` 없음 → off |
| 11-03 이후 진행 | — | **없음**: tilecore 최종 변경 11-03 00:36(README)/shadow 폴더 11-03 11:07, 맵툴 tilecore_bot.py 11-03 10:58, 계획 문서 11-03 11:44. `~/tilecore` 에 v6 이후 릴리스 없음, `project_modifications_log.md` 끝부분(2026-10-16~19)에 C# 항목 없음 [사실] |

## 5. 미확인·한계
- 이번 조사는 정적 읽기 + `ps`/`ls`/`git status` 뿐. **실행·벤치마크·테스트 0회.** 아래 모두 [미확인]: BotType 4종·fast_mode 프로필의 최신 C# 일치(문서 README 에 상충 문구 있음, 위 2-3), `acv24`/`skill_*` 실사용 빈도, `/analyze`·assess 시간 비중, `pv/evaluate` 가 실제로 쓰는 bot_version.
- `final` 스냅샷으로 combo/tiles_cleared 를 복원할 수 있는지 [미확인].
- 실행 중 서버 환경은 `ps eww` 출력에서 `TILECORE*` 변수 부재로 판단 — 서버 시작 래퍼 스크립트가 다른 경로로 주입했을 가능성은 낮으나 로그로 재확인하지 않음.
- 시간·배수 수치는 모두 계획/README 인용이며 부하 있는 조건의 값. 신규 측정 없음.
