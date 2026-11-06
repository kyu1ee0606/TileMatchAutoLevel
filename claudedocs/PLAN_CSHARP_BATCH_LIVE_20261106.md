# 계획서 — 생산 배치(≈1,530레벨) 생성·검증 봇 계산을 C#(상주 워커)로 돌려 라이브 사용 (2026-11-06, 계획만)

작성: 하위 세션 "C#배치가속계획". 구현·빌드·실행·측정 없음(파일 읽기·grep·git status/diff·sha256 읽기만). 저장소 변경 = 이 문서 1개.
표기: **[사실]** = 이번에 파일/명령으로 확인(파일:줄), **[문서]** = 기존 문서 인용(재확인 안 함), **[추정]** = 계산·설계 판단.
범위(사용자 승인): ① 상주 워커 `tilecore serve` + 파이썬 연결부 + 스위치 + 자동 폴백, ② 생성기 막힘 검사 2곳 + 난이도 측정(MC sweep·`/tune/*`) 연결 + v1 프로필 일치 확인, ③ 배치 1개 분량 나란히 실행 → 동일성·속도 확인 후 켜기, ④(추가 2026-11-06) C# 경로로 시험 배치 1개를 돌려 라이브용 레벨 **내보내기 파일 추출까지**(업로드·배포 제외). **A\* 이식 제외**(§5 선택 항목).
근거 문서: `BATCH_SPEED_CSHARP_ESTIMATE_20261106.md`(이하 "산정"), `panel_csharp_port_20261105/A_round2.md`·`B_round2.md`(패널 A/B), `CSHARP_PORT_SCOPE_REVIEW_20261105.md`(이하 "조사"), `PLAN_CSHARP_ACCELERATION_20261102.md`(이하 "PLAN").

---
## 1. 요약 (1페이지)

**목표**: 배치 1개(1,530레벨)의 "초기 생성 + RL 검증 + 미달 재생성" 계산 중 봇 시뮬 부분을 C# 상주 워커로 처리. 서비스 결과 의미(판 수·시드·집계·후보 선택)는 **그대로 유지**하고 엔진만 바꾼다.

**기대 효과 [문서: 산정 §0·§4, 전부 추정]**: 배치 계산 시간 중앙 **≈4.5 h → ≈50 min**(범위 18~97 min, 배수 3~20×, 중앙 ≈5×). 남는 최대 덩어리 = 파이썬 A\* 대조 5~38 min(범위 밖). 달력 13일 중 사람 확인·세션 사이 수정·배포 시간은 줄지 않음 [문서: 산정 §4 끝].
요청당 CLI 방식으로는 ≈1.2×뿐(.NET 기동 0.11~0.34 s [문서 실측]) → **생성기는 상주 워커로만 켠다**.

**총 작업량 [추정]**: 1~3단계 **약 9~13.5 인일**, 4단계 포함 **약 10~15 인일** + 계산 시간(배치 shadow ≈4.5 h 파이썬 계산 1회, 오프라인 재생 1~3 h, 시험 배치 C# ≈1 h + 파이썬 기준 100레벨 ≈0.5~1.5 h).
| 단계 | 내용 | 인일 |
|---|---|---|
| 0 | `~/tilecore` git·릴리스 고정, DDA 경로 고정 릴리스화 방안, 맵툴 미커밋 tilecore 파일 정리 | 0.5~1 |
| 1 | `tilecore serve`(C#) + RNG 상태 입출력 + 조기 종료·출력 확장 / 파이썬 `tilecore_client.py`(스위치·폴백·카운터) | 3.5~5 |
| 2 | 생성기 막힘 검사 2곳 연결 / `_parallel_point_sweep` 연결(= rl-sim·tune 전부) / v1 프로필 일치 확인 | 2.5~4.5 |
| 3 | 오프라인 결정적 재생(생성 JSON 바이트·측정 판별) + 실배치 shadow 1회 + 단독 속도 측정 → 켜기(승인) | 2~3 (+계산) |
| 4 | **시험 배치 실행 1회**(추가 범위 2026-11-06): C# on 으로 100레벨 → 1,530레벨 생성·RL 검증 → 배포 게이트·게임 정본 형식 확인 → 내보내기 파일 추출(업로드·배포 안 함) | 1~1.5 (+계산) |

**순서**: 0 → 1(C#·파이썬 병렬) → 2(생성기·측정 병렬) → 3 → 4. **AI 세션 기준 달력 약 5~9일**(승인 대기 제외, §2 4단계 끝 표) [추정]. 각 경로는 `off → shadow → 동일성 → 속도 → on`(PLAN §0-A). 서버 재시작·스위치 on·커밋·push 는 **사용자 승인 사항**.

---
## 2. 단계별 상세

### 공통 사실 (설계에 직접 영향)
| # | 사실 | 근거 |
|---|---|---|
| F1 | C# CLI 분기는 `dda`/`profile`/`bake`/`bot` 뿐, `serve` 없음 | [사실] `~/tilecore/src/TileCore.Cli/Program.cs:21-24` |
| F2 | C# `gen` 모드 = `Seed(seeds[0])` → 초기 상태 1회 → 판 i 마다 `Seed(seeds[0]+i)`. **조기 종료 없음**, 출력 = cleared/failed/moves/ms | [사실] Program.cs:75-83, :92-93 |
| F3 | C# `PyRandom` 은 내부 `Clone()` 만 있고 **외부에서 상태를 넣는 API(setstate) 없음**(필드 `mt`·`mti` private) | [사실] `src/TileCore/PyRandom.cs:13,127-130` |
| F4 | 파이썬 `simulate_with_profile`: `seed is not None` 일 때만 `self._rng.seed(seed)`, 판마다 `seed+i` 재설정. **seed=None 이면 재설정 없이 같은 RNG 를 이어 씀**(초기 상태 생성 포함). `_create_initial_state` 도 `self._rng.choice` 를 소비 | [사실] `bot_simulator.py:910-911,963-971,1442,1616` |
| F5 | `BotSimulator()` = `random.Random()`(OS 시드) | [사실] bot_simulator.py:874-875 |
| F6 | `_quick_deadlock_check`: 매 호출 새 `BotSimulator()`, optimal 5판, `seed=None`, `max_moves` 명시, 판정 `clear_rate < 0.3`, `avg_moves` 는 failure_reason 에 사용 | [사실] generator.py:16412-16436 |
| F7 | `_fix_same_type_blocking`: 한 `BotSimulator` 를 50후보에 **재사용**(RNG 연속), optimal 3판, seed 미전달, `clear_rate` 최고 시드 채택(≥0.5 즉시 중단), 못 찾으면 전역 `random.randint` | [사실] generator.py:16282-16324 |
| F8 | `_ensure_no_deadlock` 은 실패 후보 중 클리어율 최고 레벨을 보존·반환 | [사실] generator.py:16753-16755, :16778 (`return best_level, best_clear_rate >= 0.1, …`) |
| F9 | 측정 경로는 전부 `rl_sim._parallel_point_sweep` → `pool.map(sweep_point_task)` 1곳으로 모임. 호출처 rl_sim.py:272,423,449,534 / tune.py:151,328,521,776,1007,1043 | [사실] grep |
| F10 | `_parallel_point_sweep` 은 `bot_version` 을 안 넘김 → 항상 **v1**; `seed+idx*1000`, `early_termination=True`, `honor_zero_seed=False` | [사실] rl_sim.py:96-104, mc_difficulty.py:290-301 |
| F11 | sweep 결과가 쓰는 필드 = clear_rate, iterations, ci_half_width, avg_moves, **avg_tiles_cleared**(응답 모델 필수) | [사실] mc_difficulty.py:304-313, rl_sim.py:176-183 |
| F12 | C# 상태에 `Combo`·`TotalCleared` 필드는 이미 있음(출력만 안 함) | [사실] `src/TileCore/Bs/Model.cs:112` |
| F13 | max_moves 기본값 계산 차이: 파이썬 = `range(int(layer))` 층만 합산, C# = 모든 `layer_*` 키 합산 | [사실] bot_simulator.py:917-921 vs Program.cs:68-70 |
| F14 | 스위치 이름 충돌: solver FastJudge shadow 는 `TILECORE`, 봇 shadow 는 `TILECORE_BOT` 없으면 `TILECORE` 로 대체 → `TILECORE=on` 하나로 켜면 solver shadow(FastJudge)까지 같이 켜짐 | [사실] tilecore_bot.py:52-57, solver.py:212-220 |
| F15 | 개발 서버는 `uvicorn --reload` → 본 폴더 백엔드 파일 저장 시 자동 재시작 | [사실] run.sh:14 |
| F16 | DDA 야간 기본 CLI = `~/tilecore/experiments/e1/cli_snap_1900/tilecore.dll`(sha256 39b10a1c…), 환경변수 `TILECORE_CLI` 로 바꿀 수 있음. 이 sha 는 release v1~v6 어느 것과도 다름(v6 = 68cbf19d…) | [사실] night_common.py:11, `shasum` |
| F17 | gen_pool = 프로세스 8개(`min(8, cpu-2)`), rl_sim 풀 = 8(`min(10, cpu-2)`) | [사실] generate.py:67, rl_sim.py:50 |

---
### 0단계 — 출처·버전 고정 (패널 합의: serve 보다 먼저) [0.5~1 인일]

**0-1. `~/tilecore` git 관리** [사실: 현재 git 아님(`git status` → not a git repository)]
- `.gitignore`: `build/`, `**/bin/`, `**/obj/`, `harness/out/`·대용량 산출물(harness 1.7 GB, tests 486 MB [사실 `du`]), `shadow/*.jsonl`, `release/*/bin/`(바이너리는 디스크에 읽기 전용 유지, git 에는 `SHA256SUMS`·`SOURCE_SHA256SUMS`·README 만).
- 첫 커밋 전 확인: 현재 `src/` 가 `release/v6/SOURCE_SHA256SUMS` 와 같은지(같으면 첫 커밋 = 태그 `v6`, 다르면 v6 시점 소스를 따로 표시) [추정: 조사 §1-1 "11-02 21:20 이후 변경 없음" 근거로 같을 가능성 높음].
- 주의: `vendor/`·`release/v3~v6/bin` 에 게임 `Assembly-CSharp.dll` 포함 [사실 find] → **원격 push 는 비공개 원격만, 또는 로컬 전용**(사용자 결정 D1).
- 이후 모든 릴리스는 `make_release.sh vN`(덮어쓰기 거부) + 커밋 sha 를 릴리스 README 에 기록. serve 의 `hello` 응답에 dll sha256·커밋 sha·프로토콜 버전을 넣는다(1단계).
- **커밋 자체는 사용자 승인 필요**.

**0-2. DDA 야간 경로 고정** (F16)
- 선결: 개발 스냅샷 39b10a1c 와 `release/v6` 의 DDA 출력 바이트 동일 확인(같은 `--levels/--cands` 표본 300행, `--threads` 동일). README 의 "사본으로 전체 회귀 바이트 동일"은 비교 대상이 문장상 불명확 [사실: `~/tilecore/README.md:35`] → 재확인 필요.
- 선택지(D2): (a) 실행 쪽에서 `TILECORE_CLI=~/tilecore/release/v6/bin/tilecore.dll` 지정(코드 수정 없음) / (b) `night_common.py:11` 기본값을 릴리스 경로로 변경(sp 저장소 수정 = sp 쪽 세션·사용자 승인) / (c) 스냅샷을 `release/v6s` 로 정식 등록(SHA 기록)하고 그대로 사용. **추천 (b)**, 최소 (a). 야간 작업이 정기 예약인지 수동인지 [미확인: `~/Library/LaunchAgents` 에 dda 항목 없음].

**0-3. 맵툴 미커밋 tilecore 연결 파일 정리** [사실: `git status`, 현재 브랜치 `feature/pv-seed-variants`]
| 파일 | 상태 | 비고 |
|---|---|---|
| `backend/app/core/tilecore_bot.py`, `tilecore_shadow.py` | `??` | autoplay·solver shadow |
| `backend/tests/test_tilecore_bot.py`, `test_tilecore_shadow.py` | `??` | |
| `backend/scripts/tilecore_bot_shadow_sample_20261103.py`, `tilecore_solver_shadow.py` | `??` | |
| `backend/app/api/routes/analyze.py` | `M` | diff 36줄 = tilecore 훅만 [사실 git diff] |
| `backend/app/core/solver.py` | `M` | **혼합**: tilecore 훅 + 다른 세션의 `_TIME_CHECK_EVERY`(PLAN_DDA_SEED_ONLY_EXPORT_FIX) [사실 git diff] |
- 방안: tilecore 전용 커밋 1개 = 위 `??` 6개 + analyze.py 전체 + solver.py 의 tilecore 덩어리만 부분 스테이징. 커밋 전 `pytest tests/test_tilecore_bot.py tests/test_tilecore_shadow.py` 통과 확인. `_TIME_CHECK_EVERY` 덩어리는 해당 세션 소유 → 건드리지 않음(또는 그 세션 커밋 후 진행).
- worktree `~/TileMatchAutoLevel_wt_tilecore`(브랜치 `tilecore-shadow-20261103`)는 HEAD 68b4028 위에 다른 작업 스테이징이 섞여 있음 [사실: `git -C … status` 에 `A dda_seed_ledger.py` 등] → 이 작업에 재사용하지 않음. 정리(삭제)는 사용자 결정(D3), 자동 삭제 없음.
- 커밋 위치(D3): 현재 브랜치 vs 새 브랜치 `feature/tilecore-live`. 커밋·push = 사용자 승인.

**완료 기준**: `~/tilecore` 첫 커밋·태그 존재, v6 sha 기록; DDA 쪽이 고정 릴리스(또는 등록된 스냅샷)를 가리킴; 맵툴 tilecore 파일이 커밋돼 이후 작업 diff 가 깨끗함. **롤백**: git 도입은 파일을 바꾸지 않음; DDA 는 환경변수 제거로 원복.

---
### 1단계 — 상주 워커 + 파이썬 연결부 + 스위치 + 폴백 [3.5~5 인일]

#### 1-A. C# (`~/tilecore`, 릴리스 v7) [2~3 인일]
| 작업 | 파일 | 내용 |
|---|---|---|
| RNG 상태 입출력 | `src/TileCore/PyRandom.cs`(:127-130 부근 추가) | `GetState() → (uint[624], int index)`, `SetState(uint[] mt, int index)`(길이 624·0<index≤624 검증). CPython `getstate()` = `(3, (mt0..mt623, index), gauss_next)` 와 1:1 [추정: CPython 형식; BotSimulator 는 gauss 미사용(grep 0건) → `gauss_next` 가 None 이 아니면 unsupported] |
| `gen_state` 모드 | `Program.cs` `RunJob`(:58-88) | `SetState` → 초기 상태 1회 → 판마다 **재설정 없이** 연속 진행(F4 seed=None 흐름) → 끝 상태 `rng_state_out` 반환. 기존 `gen`/`dda` 출력은 바이트 동일 유지 |
| 조기 종료 | 같은 곳 | 파이썬 `_should_terminate_early`(bot_simulator.py:999-1036) 직역: n≥5 에서 율 1.0/0.0, n≥10 에서 율 ≥0.90 또는 ≤0.10 → 중단 |
| 출력 확장 | `Play`(:90-93) | 판별 `combo`(=`Combo`), `tiles_cleared`(=`TotalCleared`) 추가(F12). 집계(mean/stdev)는 **파이썬이 판별 정수로 계산**(부동소수 동일 보장 [추정: `statistics.mean` 결과를 C# 에서 맞추는 부담 제거]) |
| `serve` | 새 `src/TileCore.Cli/Serve.cs`, Program.cs:21 앞에 분기 1줄 | 아래 프로토콜. 스레드 풀 `--threads N`, 출력 쓰기 잠금, stdin EOF → 진행 중 작업 마치고 종료, `--max-mem-mb` |
| 버전 | `tilecore version` + serve `hello` | proto, engine semver, dll sha256, 소스 커밋 sha, rules=bs |
| 회귀 | `harness/fast.sh` + 신규 PyRandom 상태 벡터 | v6↔v7: 기존 `gen`/`dda` 출력 바이트 동일(기준선 13세트·R2 표본); CPython 에서 k회 소비 후 getstate → C# SetState → 다음 10만 수 일치; `Combo`·`TotalCleared` 파이썬 일치(shadow_bot.py 표본 — 현재 비교 항목인지 [미확인]) |

**serve 프로토콜 초안 (proto 1, stdin/stdout JSONL, 한 줄 = 한 메시지, 응답 순서 무관·`id` 로 대응)**
```jsonc
// 기동 직후 1줄 (stdout)
{"type":"hello","proto":1,"engine":"tilecore/7.0.0","rules":"bs","dll_sha256":"…","src_commit":"…","threads":1,"pid":12345}
// 요청
{"id":"g-17-3","op":"sim",
 "mode":"gen" | "gen_state",                 // gen = seed 고정(seed+i), gen_state = 파이썬 RNG 상태 이어받기(seed=None)
 "profile":{ /* dataclasses.asdict(BotProfile), bot_type 문자열 */ },
 "level":{ /* level_json */ },
 "iterations":5, "seed":4242 | null,
 "rng_state":{"mt":[/*624 uint*/],"index":624} | null,   // gen_state 일 때만
 "max_moves":123,                           // 항상 파이썬이 계산해서 명시 (F13 차이 제거)
 "early_termination":false,
 "want_state_out":true,
 "deadline_ms":10000}
{"id":"p1","op":"ping"}   {"id":"q","op":"shutdown"}
// 응답
{"id":"g-17-3","ok":true,"n":5,
 "games":[{"cleared":true,"failed":"","moves":88,"combo":12,"tiles_cleared":81}, …],
 "rng_state_out":{"mt":[…],"index":311} | null, "ms":3.1}
{"id":"g-17-3","ok":false,"unsupported":true,"error":"t0 with randSeed<=0"}
{"id":"g-17-3","ok":false,"unsupported":false,"error":"InvalidOperationException: … @ …"}
{"id":"p1","ok":true,"pong":true,"inflight":0,"rss_mb":161}
```
- 최소 계약(패널 A): 요청 ID·요청별 deadline·EOF 종료·버전 확인·unsupported 응답. 취소(cancel)·기능 협상은 넣지 않음 — 파이썬이 타임아웃 시 프로세스를 죽이고 재시작하는 것으로 대체 [추정: 패널 B 의 "협상·취소" 요구는 D7 로 표시].

#### 1-B. 파이썬 연결부 (`backend/app/core/tilecore_client.py` 신규) [1.5~2 인일]
```python
# 스위치: 경로별, 공용 TILECORE 는 읽지 않음(F14)
#   TILECORE_GEN   = off|shadow|on   (생성기 막힘 검사 2곳)
#   TILECORE_SWEEP = off|shadow|on   (_parallel_point_sweep)
#   TILECORE_SERVE_DLL (기본 ~/tilecore/release/v7/bin/tilecore.dll), TILECORE_SERVE_SHA (기대 sha256, 불일치 → 이 프로세스 C# 비활성 + 경고)
#   TILECORE_SERVE_THREADS_GEN=1, TILECORE_SERVE_THREADS_SWEEP=4, TILECORE_TIMEOUT_S=10, TILECORE_SHADOW_SAMPLE (on 후 표본 감시 비율, 기본 0)
def path_mode(path: str) -> str: ...                      # "off" | "shadow" | "on"

class ServeWorker:                                         # 프로세스당 1개(lazy), 스레드 안전
    def request(self, msg: dict, timeout_s: float) -> dict  # 리더 스레드 + id→Future; 타임아웃/EOF/크래시 → 프로세스 kill, 대기 요청 전부 예외 → 호출자 폴백, 지수 백오프 재시작
    def hello(self) -> dict

def resolve_max_moves(level_json: dict, max_moves: int | None) -> int   # bot_simulator.py:914-922 그대로 복제
def simulate(simulator: "BotSimulator", level_json: dict, profile, *, iterations: int,
             max_moves: int | None = None, seed: int | None = None,
             honor_zero_seed: bool = False, early_termination: bool = False,
             path: str) -> "BotSimulationResult":
    """off → simulator.simulate_with_profile(...) 그대로 호출(코드 경로 동일).
       on  → C# (seed=None 이면 simulator._rng.getstate() 전달, 응답의 rng_state_out 으로 simulator._rng.setstate()),
             판별 결과로 BotSimulationResult 를 bot_simulator.py:985-998 과 같은 식으로 계산.
             unsupported/오류/타임아웃/버전 불일치 → 같은 호출을 파이썬으로(RNG 상태는 호출 전 그대로라 결과 의미 동일).
       shadow → 파이썬 결과 반환 + 호출 전 RNG 상태로 C# 실행 → 판별 비트·moves·tiles·끝 RNG 상태 비교 로그."""
def sweep_points(tasks: list[dict], path: str = "sweep") -> list[dict]:
    """sweep_point_task 와 같은 dict 목록 반환. 점 단위로 C# 에 파이프라인 전송, unsupported/실패 점만 파이썬(풀)으로."""
def counters() -> dict                                    # {path: {cs_ok, unsupported, error, timeout, fallback, shadow_same, shadow_mismatch}}
```
- 지원 판정(파이썬 측 사전 거절 → 바로 파이썬): `honor_zero_seed=True`, `bot_version ∉ {"v1"}`(sweep), `gauss_next≠None`. C# 측 거절: t0+randSeed≤0, PR≥1.0, V24_DEFAULT 밖 항목 등 [문서: 조사 §1-2].
- 로그: `~/tilecore/shadow/{gen,sweep}_shadow_diff.jsonl`(입력 해시·프로필·판별 비트·끝 상태 해시·범주 same/mismatch/cs_unsupported/cs_error/timeout·양쪽 시간), `usage.jsonl`(5분마다 카운터 1줄). API 응답 스키마 변경 없음 → 프론트 타입 동기화 불필요 [추정; 스키마를 바꾸게 되면 CLAUDE.md 규칙대로 `npx tsc --noEmit` + Playwright].
- 테스트(`backend/tests/test_tilecore_client.py` + 가짜 serve `backend/tests/fake_tilecore_serve.py`): off 경로 바이트 동일(C# 미호출), 폴백 3종(kill·타임아웃·버전 불일치) 결과 = 파이썬, 대기 요청 유실 0, unsupported 카운트, RNG 상태 왕복(getstate→JSON→setstate 동일).

**프로세스 배치 [추정]**: gen_pool 프로세스 8개(F17) 각각 `serve --threads 1`(파이썬은 C# 응답을 기다리므로 프로세스당 실사용 ≈1코어). 측정은 uvicorn 본 프로세스에 `serve --threads 4` 1개(파이썬 rl 풀은 폴백용으로 유지). RSS ≈160 MB/워커(v6 1스레드 Server GC [문서 README:170]) × 9 ≈ 1.5 GB → `DOTNET_gcServer=0`·`DOTNET_GCHeapHardLimit` 로 상한(D8).
**완료 기준**: v7 회귀 바이트 동일; 가짜 serve 테스트 전부 통과; 실제 v7 serve 로 고정 입력 300레벨 × 막힘 검사 호출 형태(5판 seed=None 상태 전달, 3판 연속 50후보)에서 판별 결과·끝 RNG 상태 100% 일치; 유휴 단독 IPC 왕복 p50/p95 기록.
**위험**: CPython 상태 표현 결합(버전 업 시 형식 변화) → hello 에 파이썬 버전 기록·불일치 시 비활성; 리더 스레드·fork(ProcessPool 은 macOS 기본 spawn [추정]) 상호작용; 좀비 프로세스(EOF 종료로 방지). **롤백**: 스위치 off(기본값) = 기존 코드 경로.

---
### 2단계 — 호출처 연결 + v1 프로필 일치 확인 [2.5~4.5 인일]

**2-A. 생성기 막힘 검사 2곳** [1~2 인일]
- 수정: `generator.py:16295`(`_fix_same_type_blocking`) / `:16419`(`_quick_deadlock_check`) 의 `simulator.simulate_with_profile(...)` → `tilecore_client.simulate(simulator, …, path="gen")`. 인자·판 수·임계값·후보 선택 로직은 손대지 않음. 전역 `random.randint`(:16324)는 파이썬 그대로.
- 주의: generator.py 에 다른 세션 미커밋 덩어리 3개(:3958, :13506, :13767 부근) [사실 git diff] → 2곳 최소 diff, 부분 스테이징.
- 동일성(seed=None 처리, 결정 D4) — **추천 = 패널 A 안(상태 전달) + 패널 B 보강(끝 상태 대조)**:
  - 근거: F4 상 seed=None 경로는 "호출 전 RNG 상태 + 입력"만 같으면 결정적. C# 쪽 필요 작업은 `SetState`/`GetState` + `gen_state` 모드뿐(F3, 작음). `_fix_same_type_blocking` 은 RNG 를 50후보에 이어 쓰므로(F7) **끝 상태를 파이썬에 되돌려 넣어야** on 결과가 순수 파이썬 실행과 비트 동일 → 끝 상태 대조가 패널 B 의 "판 종료 상태·연속 재생" 우려를 그대로 덮는다.
  - 대안(상태 전달이 막힐 때만): 분포 비교. 2비율 차이 95% 반폭 = 1.96·√(0.5/n) → n=300 이면 **±8.0%p**(±3%p 불성립), ±3%p 에는 레벨당 각 ≈2,134판 필요 [추정: 계산]. 5판/3판 호출 단위로는 판정 불가 → 레벨 단위 대량 재실행 필요해 비싸고 약함.
- 오프라인 재생 하네스 `backend/scripts/tilecore_gen_replay.py`(신규): `BotSimulator.__init__` 시드를 호출 순번으로 고정 + 전역 `random`·생성 파라미터 고정 → 같은 입력으로 `generate()` 를 off/on 각각 실행 → **최종 레벨 JSON 바이트 동일** + 호출별 판별 일치. (실서비스는 OS 시드라 JSON 바이트 비교는 이 하네스에서만 성립 [추정].)

**2-B. 측정(MC sweep·`/tune/*`)** [1~1.5 인일]
- 수정: `rl_sim.py:108` `raw_points = list(pool.map(sweep_point_task, tasks, chunksize=1))` 한 줄을 모드 분기로: off = 그대로 / on = `tilecore_client.sweep_points(tasks)` / shadow = 파이썬(풀, 판별 비트 기록 버전) + C# 비교. F9 상 rl-sim/level·batch·tune 전 경로가 이 1곳으로 커버. `check_solver_on_zero` A\*(rl_sim.py:337-345)는 파이썬 그대로.
- 판별 기록용 파이썬 작업 함수는 `tilecore_client.py` 에 둠(mc_difficulty.py 수정 없음; 풀 pickle 위해 모듈 최상위 함수).
- 출력 확장 필요(F11): `avg_tiles_cleared`(필수), `avg_moves`, `iterations`(조기 종료 후 실제 판 수).

**2-C. v1 프로필 C# 일치 확인** [0.5~1 인일]
- 현황: `skill_v1_*` 는 "값만, shadow 미검증" [문서 README_v6 §1], 산정 실측 24점·486판 판별 전부 일치 [문서 산정 §3 — 작은 표본].
- 방법 `backend/scripts/tilecore_sweep_parity.py`(신규): 라이브 일치본 배치 1,530레벨 × θ 8점 × 64판(seed 4242+idx·1000, 조기 종료) → 판별 cleared·moves·tiles_cleared·실제 판 수 **100% 일치**(완전 결정적 경로라 분포 검정 불필요). 파이썬 CPU ≈1,530 × 4~21 s ≈ 1.7~9 CPU-h → 6~8 코어로 15~90 min [추정]. 이것이 "측정 1라운드 = 배치 1개 분량" 대조를 겸함.
- 생성기용 `optimal`(get_profile, PR 0.99)도 `gen_state` 모드로 재확인(기존 검증 315판은 `gen` 모드 [문서 조사 §2-2]).

**출력 확장 필요 항목을 쓰는 경로 목록** [사실: grep]
| 필드 | 쓰는 경로 | 이번 범위 |
|---|---|---|
| clear_rate | 막힘 검사 2곳, sweep, `/generate/validated`(generate.py:244-261), autoplay | 포함(판별 cleared 로 계산) |
| avg_moves | `_quick_deadlock_check` failure_reason(generator.py:16429-16433), sweep(mc_difficulty.py:311) | 포함(판별 moves) |
| avg_tiles_cleared | sweep(mc_difficulty.py:312, rl_sim.py:183 응답 필수) | **포함 — C# 출력 추가 필요** |
| iterations(실제 판 수) | sweep ci_half_width(mc_difficulty.py:309), 총 롤아웃(:363) | 포함(C# 조기 종료 필요) |
| avg_combo, min/max/std_moves | autoplay(analyze.py:548-551,587-592), assess | 범위 밖(출력은 combo 까지 넣어 두므로 나중에 파이썬 집계로 가능) |

**완료 기준(2단계)**: off 경로 바이트 동일 테스트; 2-C 100% 일치(비교 건수·unsupported 비율 함께 보고); 2-A 하네스 ≥300레벨(기믹·크기·t0 유무 층화) JSON 바이트 100% 동일. **롤백**: 경로별 off.

---
### 3단계 — 배치 1개 분량 나란히 실행 → 속도 → 켜기 [2~3 인일 + 계산]

**3-1. 오프라인 결정적 대조(서버 재시작 불필요)**: 2-A 하네스로 배치 1개분 생성 스펙(≥300, 가능하면 1,530) off/on, 2-C 하네스(1,530레벨 sweep). 산출: 경로별 `비교 건수 / 일치 / 불일치 / unsupported / 오류` 표 + 기믹별 층화표.
- 생산 프론트가 넘기는 GenerationParams 를 배치 파일에서 복원할 수 있는지 [미확인] — 안 되면 레벨의 level_number·기믹 구성으로 근사 스펙 생성(한계로 명시).

**3-2. 실배치 shadow 1회(사용자 승인: 서버 재시작 `TILECORE_GEN=shadow TILECORE_SWEEP=shadow`)**: 프로덕션 대시보드로 배치 1개(또는 확장 30레벨 + RL 1라운드) 실행. 서비스 결과 = 파이썬. 비교 분모 = 실호출 − unsupported, **"불일치 0"은 비교한 건수 기준으로만** 말하고 unsupported·timeout·error 비율 별도 보고.

**shadow 종료 기준 제안 (D5)** — 달력 2주 대신 건수:
- 기본 = **배치 1개 분량**(생성 ≈24,500 `/generate`, 측정 ≈1,530건 이상). 배치가 중간에 끊기면 대체 기준 = 경로별 **비교 성공 ≥1,000호출 + 기믹별 ≥30호출**.
- 근거 [추정]: ① 판 단위 정확 대조라 통계 검정이 아님 — 불일치 0/N 이면 호출당 불일치율 95% 상한 ≈3/N(N=1,000 → 0.3%, 배치 1개 생성 경로 N≈24,500 이상 → ≈0.01%). ② 오류 원천은 시간 경과보다 **입력 다양성**(기믹·크기·t0·키) → 층화 커버리지가 기간보다 중요(패널 B). ③ 장시간 관찰 항목(누수·재시작)은 배치 1개(≈4.5 h 파이썬 계산)로 최소 1회 확보. ④ 비교 불가 비율 ≥5% 면 통과 아님(패널 A 기준 "비교 성공 ≥95%").

**3-3. 속도 판정(shadow 와 분리, 단독)**: load avg ≤ 8 확인 후 다른 대형 작업 없는 시간에. 같은 표본·같은 동시 수. 측정: `generate()` 호출 p50/p95(off vs on), 측정 1건 p50/p95, IPC 왕복 p95, 최대 RSS, 이후 on 모드 배치 1개 종단 시간(기록 비교: 초기 생성 80~95 min [문서]). 기준(D6) 추천: generate p50 ≥5×·p95 악화 없음, 측정 1건 p50 ≥10×.
**CPU 상한**: 계산 작업 합 ≤8 코어(PLAN §6). shadow 중엔 파이썬+C# 동시이므로 gen_pool·rl 풀을 줄이거나 다른 계산 세션을 멈추도록 마더가 배정(D8). 현재 load 5.1~6.9 [사실 `uptime` 15:39].

**3-4. 켜기(사용자 승인)**: 경로별로 `TILECORE_GEN=on` → 배치 1개 → `TILECORE_SWEEP=on`. 켠 뒤 `TILECORE_SHADOW_SAMPLE`(예 0.02) 표본 감시 + 폴백 카운터 확인. 웹뷰 확인: Playwright 로 프로덕션 대시보드 10레벨 생성·순차검증 1라운드 정상 동작(CLAUDE.md 테스트 지침).
**롤백**: 환경변수 off + 서버 재시작(승인) → 즉시 파이썬. 코드 경로·폴백 상시 유지.
**위험**: 배치 중 `--reload` 재시작(F15) → 구현은 worktree 에서, 본 폴더 반영은 배치가 돌지 않을 때만(마더 조율); 실배치 shadow 가 파이썬 시간(≈4.5 h 이상) 그대로 소요; GenerationParams 복원 불가 시 오프라인 생성 대조가 근사.

---
### 4단계 — 시험 배치 실행 1회: C# 경로로 라이브용 레벨 추출 [1~1.5 인일 + 계산]

**관련 사실**
| # | 사실 | 근거 |
|---|---|---|
| G1 | 배치 생성은 크기 고정(`PRODUCTION_MAX_LEVEL = 1530`), 생성 함수는 `levelRange`(구간 생성) 인자를 받음, 순차검증은 대상 레벨 번호 목록을 받음 | [사실] types/production.ts:412, index.tsx:1087, :1143, :1436, :5076 |
| G2 | RL 통과 판정 = `rl_unreliable` 이면 통과 / `unclearable_suspect` 면 실패 / 1~10 레벨은 gap ≥ −0.12 / 그 외 백엔드 `verification_passed`(\|gap\| ≤ 0.12 AND 클리어 불가 의심 아님) + 격자 ≤ `MAX_PLAYABLE_GRID` + 규칙 위반 0 | [사실] index.tsx:781-810, :5290, mc_difficulty.py:64 |
| G3 | 배포 게이트(순수 함수, 모든 배포 경로 공유): BOMB 3~5, timea 정수, 기믹 언락 첫 스테이지 표, 열쇠 3배수(`key_not_div3`), `div3` | [사실] ProductionExport.tsx:22-30, :143, :183 |
| G4 | 내보내기 = 브라우저 다운로드 `production_levels_<batchId>.json`(일괄) 또는 레벨별 `level_{number:04d}.json`; 무한 레벨 = 501~1530 을 `infinity_1..1030` 으로 복사 추가 | [사실] ProductionExport.tsx:307, :318, :591, :602 |
| G5 | 8월 라이브 원본 `qi96gz8x5`(1,500레벨): `verification_method` rl 1,500 / `verification_passed` True 1,406·None 93·False 1 / \|gap\| ≤ 0.12 = 1,368 / status generated 1,215·playtest_queue 284·approved 1 / 재생성 871레벨·1,875회 / 초기 생성 시도 6회 = 1,328 | [사실] 배치 파일 meta 집계(이번 세션, python 읽기) |
| G6 | 8월 이후 생성기 규칙이 바뀜(타일 하한·KEY_DIV3 등 미커밋 변경 포함) | [사실] generator.py git diff, 게임 정본 §6 "타일 수 하한" |

**4-0. 전제**: 3단계 통과(경로별 shadow 불일치 0, 비교 불가 ≤5%, 속도 기준 충족), `TILECORE_GEN=on`·`TILECORE_SWEEP=on`, 표본 감시 2%. 다른 계산 세션 정지 또는 합 ≤8 코어 배정, load avg ≤8 확인. 서버 재시작(on 전환)·실행 자체가 **사용자 승인**.

**4-1. 소규모 시험(100레벨) — C# on 과 파이썬 off 를 같은 코드로 비교**
1. 화면 = 프로덕션 대시보드(`http://localhost:5173`, ProductionDashboard). "1500 프리셋"으로 새 배치 생성(`handleCreateBatch` index.tsx:1081) — 이름에 `TRIAL-CS-<날짜>` 표시. 배치 이름·id 기록.
2. 초기 생성: 1~100 구간만(`handleStartGeneration` 의 `levelRange` — 화면에서 임의 구간을 지정할 수 있는지 [미확인]; 안 되면 1,530 생성을 시작해 100레벨 뒤 중지, 또는 구간 입력 UI 추가는 별도 승인). 검증 모드는 8월과 같게 **끔**(G5: match_score 있는 레벨 = 템플릿분뿐 [문서 산정 §1]). t0 시각 시드 굽기는 자동(index.tsx:1879).
3. 순차검증: 1~100 선택 → `handleSequentialProcess`(라운드 ≤10, 측정·`/tune/auto`·재생성). A\* 대조(`check_solver_on_zero`)는 파이썬 그대로.
4. 같은 100레벨을 파이썬으로: 스위치 off 로 서버 재시작(승인) 후 **새 배치**로 1~3 반복. (동시 실행 금지 — 속도 비교가 무효가 됨.)
5. 100레벨에서 ① C# 오류·폴백 비율 ② 결과 판정·형식(4-3) ③ 시간·품질 표(4-4)를 확인 → 이상 없으면 4-2.
- 비교 해석 주의 [추정]: 생성은 OS 시드라 두 배치의 레벨 자체는 다르다 → "같은 레벨" 비교가 아니라 **분포 비교**(클리어율·재생성 횟수). 판 단위 동일성은 이미 3단계에서 확인했으므로 여기 차이는 우연 변동으로 봐야 함. 100레벨이면 통과율 차이 95% 반폭 ≈ ±12%p(50% 기준) → 품질 비교는 참고용, 판정 근거는 4-3 기준 충족 여부.

**4-2. 전체 시험(1,530레벨, C# on 만)**: 같은 배치(또는 새 배치)로 1~1,530 생성(검증 모드 끔) → 전체 순차검증 → 미달 최근접 스냅샷 복원·QD 2차 패스(index.tsx:5465~)까지 기존 흐름 그대로. 브라우저 탭은 끝까지 열어 둠(산정 §1). 파이썬 전체 배치는 돌리지 않음 — 시간 기준은 8월 기록(초기 생성 80~95 min, 재생성 활동 ≥11.1 h [문서 산정 §2])과 4-1 의 파이썬 100레벨 실측으로 대신 [추정: 파이썬 전체 1회 ≈4.5~11 h 를 아끼기 위한 선택, D11].

**4-3. "라이브 사용 가능" 판정 기준**
| 기준 | 내용 | 확인 방법 |
|---|---|---|
| L1 검증 기준 동일 | 8월 배치가 통과한 판정 = G2 (`verification_method=rl`, \|gap\| ≤ 0.12 등). 현재 코드의 판정 함수(index.tsx:781-810, :5290)가 8월 당시와 같은지 [미확인: 이후 `rl_unreliable`·격자·규칙 위반 조건이 추가됐을 수 있음] → `git log -L` 로 8월 시점 판정 코드를 찾아 차이를 표로 남김 | git 읽기 |
| L2 통과 수준 | `verification_passed` True 비율 ≥ 8월 기록(1,406/1,500 = 93.7%) 수준, False·None 은 레벨 번호 목록으로 보고. 8월은 None 93개(playtest_queue)를 남긴 채 배포됨(G5) → 같은 처리를 할지 사용자 결정(D12) | 배치 meta 집계 스크립트(읽기 전용) |
| L3 배포 게이트 | 배포 게이트(G3) 탈락 0 — 내보내기 화면이 탈락 목록을 보여주는 방식 그대로 사용 | ProductionExport 화면 |
| L4 게임 정본 형식 | 게임 정본 `DESIGN_LEVEL_MAP_SCHEMA.md` §6(타일 총수 %3, 좌표 범위 `0≤col<layer.col`, 타일 ID t1~t16/stack_*/craft_*, 효과 ID §5 목록), §3-1·§3-2(`layer` 값 ↔ `layer_N` 키 일치 — 넘침·모자람 둘 다), §8 JSON 형태, §6-1 폭탄 권장(최상단 폭탄 C ≥ N+3, 경고만) | 내보내기 파일을 읽는 오프라인 검사 스크립트 `backend/scripts/check_export_schema.py`(신규, 정본 §번호를 규칙마다 주석) — 같은 스크립트를 8월 라이브 일치본(`batch_1792056041502`)에도 돌려 **기준선 위반 수**와 비교(새 위반 0이 기준) |
| L5 구조 동일 | 내보내기 레벨 JSON 의 키 집합·값 타입이 라이브 일치본 레벨과 같음(새/누락 키 0, 타입 불일치 0). `visualTileSeed` 등 t0 관련 필드 포함 여부 동일 | 같은 스크립트의 키·타입 비교 |
| L6 C# 운영 | 폴백 비율·오류·타임아웃 수, 표본 감시 불일치 0(비교 건수와 함께) | `usage.jsonl`, `*_shadow_diff.jsonl` |
| L7 타일 하한 | 정본 §6 신규 레벨 타일 수 하한(생성 차단 규칙) 충족 — 8월 배치는 이 규칙 이전이라 기준선에서 제외 | 검사 스크립트 |

**4-4. 결과물**
- 내보내기 파일: 브라우저 다운로드(`~/Downloads/production_levels_<batchId>.json`, 무한 레벨 복사 포함 여부 기록)를 `~/TileMatchAutoLevel/claudedocs/trial_cs_batch_<날짜>/export/` 로 복사·sha256 기록(원본 다운로드는 그대로 둠). 배치 원본은 서버 저장본 `backend/data/production/<batchId>.json`.
- 시간 비교표(`.../time_compare.md`): 단계별(초기 생성 / 측정 / tune / 재생성 / A\* / 브라우저 저장) 벽시간 — C# 1,530 실측 vs 파이썬(4-1 100레벨 실측 ×15.3 환산 + 8월 기록), 측정 시 load avg 기록.
- 품질 비교표(`.../quality_compare.md`): 클리어율 분포(predicted_clear_rate 사분위, \|gap\| ≤ 0.05/0.10/0.12 개수), rl_classification 분포, `verification_passed` 분포, 재생성 레벨 수·횟수 합, 초기 생성 시도 수 — C# 시험 vs 4-1 파이썬 100레벨 vs 8월 `qi96gz8x5`. G6 때문에 8월과의 차이는 C# 효과가 아닐 수 있음을 표에 명시.
- 판정 보고(`.../README.md`): L1~L7 통과/미통과, 미통과 레벨 목록, 한계.

**4-5. 범위 경계 (시험 실행에서 포함·생략)**
| 단계 | 시험 실행 | 비고 |
|---|---|---|
| 배치 생성·초기 생성·t0 굽기·RL 순차검증·tune·재생성·스냅샷 복원 | **포함** | 기존 흐름 그대로, 봇만 C# |
| A\* 대조(전 구간 0 레벨) | **포함(파이썬)** | C# 이식 범위 밖 |
| 배포 게이트·정본 형식 검사·내보내기 파일 생성 | **포함** | 끝점 = 파일 생성 |
| 사람 플레이테스트(playtest_queue) | **생략** — 큐 개수만 보고 | 8월도 비우지 않고 배포됨(G5); 실제 배포 전 필요 여부는 사용자 결정 |
| 승인(approved) 표기 | 생략 | 사람 단계 |
| sp DDA 시드 판정(FastJudge A\* + bot_judge) | **생략** | 별도 파이프라인(산정 §1-7). 라이브 투입 시 필요 → 별도 작업 |
| GBoost 업로드·LiveBackup 업로드·게임/라이브 서버 배포 | **하지 않음** | **사용자 별도 승인 항목** |

**4-6. 1~4단계 달력 소요 [추정, AI 세션 기준]** — 참고: ① 봇 이식은 계획 13~18 인일이 실제 약 1~2일에 1차 완료 [문서 PLAN §8]. 구현은 이 비율(≈1/8)로 줄지만 **계산 시간·승인 대기·브라우저 파이프라인은 줄지 않음**.
| 단계 | 구현·분석 | 계산·대기 | 달력 |
|---|---|---|---|
| 0 | 0.3일 | DDA 바이트 대조 ~1 h | 0.5일 |
| 1 | 1~1.5일(S1·S2 병렬) | 회귀 ~1 h | 1~1.5일 |
| 2 | 1일(S3·S4 병렬) | v1 대조 15~90 min, 생성 재생 1~2 h | 1~1.5일 |
| 3 | 0.5일 | 실배치 shadow ≈4.5 h(기록상 ≥11 h 가능) + 단독 속도 측정 시간대 대기 | 1~2일 |
| 4 | 0.5일(검사 스크립트·보고) | 100레벨 ×2 ≈1~2 h, 1,530 C# ≈1~2 h(브라우저 흐름·라운드 포함) | 1~1.5일 |
| 합 | | | **약 5~9일**(승인 대기 제외) |

**4-7. 사용자 승인 필요 시점 (시간순)**
1. 0단계: `~/tilecore` git 첫 커밋·태그(원격 push 는 D1), sp `night_common.py` 수정(D2), 맵툴 tilecore 파일 커밋(D3).
2. 1~2단계 코드 커밋, worktree → 본 폴더 반영(자동 재시작 발생, F15).
3. 3단계: 서버 재시작(`TILECORE_GEN/SWEEP=shadow`), 실배치 shadow 실행(CPU 수 시간), 단독 속도 측정 시간대 확보(다른 계산 작업 중지).
4. 3→4단계: on 전환 서버 재시작, 시험 배치 실행, 4-1 의 파이썬 비교를 위한 off 재시작.
5. 4단계 결과 후: 시험 배치를 실제 라이브 후보로 쓸지, 업로드·배포(GBoost), 플레이테스트·DDA 시드 판정 진행 — **전부 별도 승인**.

---
## 3. 하위 세션 분할안

| 세션 | 단계 | 담당 파일(쓰기) | 선행 | 병렬 |
|---|---|---|---|---|
| S0 "tilecore릴리스고정" | 0 | `~/tilecore/.gitignore`, `~/tilecore/README.md`(릴리스 절), git 메타; 맵툴은 커밋 준비만(스테이징 목록 작성) | 없음 | DDA 바이트 대조는 CPU 사용 → 슬롯 배정 |
| S1 "C#serve" | 1-A | `~/tilecore/src/**`(PyRandom.cs, Program.cs, 새 Serve.cs), `harness/`(새 벡터 테스트), `release/v7` | S0(git 존재) | S2 와 병렬 |
| S2 "파이썬연결부" | 1-B | 새 `backend/app/core/tilecore_client.py`, `backend/tests/test_tilecore_client.py`, `backend/tests/fake_tilecore_serve.py` | 이 문서 §2 프로토콜 동결 | S1 과 병렬(가짜 serve 로 개발) |
| S3 "생성기연결" | 2-A | `generator.py` 2곳(:16295, :16419) + import, 새 `backend/scripts/tilecore_gen_replay.py`, 새 `backend/tests/test_tilecore_gen_hook.py` | S1·S2 | S4 와 병렬 |
| S4 "측정연결" | 2-B·2-C | `rl_sim.py:108` 1곳, 새 `backend/scripts/tilecore_sweep_parity.py`, 새 `backend/tests/test_tilecore_sweep_hook.py` | S1·S2 | S3 와 병렬 |
| S5 "배치대조" | 3 | 보고서만(`claudedocs/` 신규 결과 문서), 코드 수정 없음 | S3·S4 | 순차, CPU 슬롯 독점 필요 |
| S6 "시험배치" | 4 | 새 `backend/scripts/check_export_schema.py`, `claudedocs/trial_cs_batch_<날짜>/`(결과·복사본). 대시보드 조작은 Playwright | S5 통과 + on 승인 | 검사 스크립트는 S5 와 병렬 작성 가능, 실행은 순차 |
- 겹침 방지: `tilecore_client.py` 는 S2 단독 소유(S3·S4 가 필요한 변경은 마더 경유 S2 에 요청). 모든 맵툴 작업은 **새 worktree**(예 `~/TileMatchAutoLevel_wt_tclive`)에서 — 본 폴더 `--reload` 재시작 방지(F15). 본 폴더 반영·커밋은 마더가 배치 미실행 시점에 승인받아 수행.
- generator.py·solver.py 는 다른 세션 미커밋 변경이 있으므로 S3 는 2곳 외 수정 금지, 반영 시 부분 스테이징.

---
## 4. 사용자 결정 필요 항목

| # | 항목 | 선택지 (추천 ★) |
|---|---|---|
| D1 | `~/tilecore` git 원격 | ★로컬 전용 / 비공개 원격(게임 dll 포함 주의) ; 릴리스 bin: ★git 제외(SHA 만) / 포함 |
| D2 | DDA 야간 CLI 고정 | (a) 환경변수 / ★(b) night_common.py 기본값 변경(sp 저장소 수정 승인) / (c) 스냅샷 정식 등록 |
| D3 | 맵툴 tilecore 파일 커밋 | 현재 브랜치 / ★새 브랜치 `feature/tilecore-live` ; `wt_tilecore` worktree 처리(유지/삭제) ; solver.py 혼합 덩어리 처리 순서 |
| D4 | seed=None 대조 방식 | ★상태 전달(+끝 상태 대조) / 분포 비교(±3%p 면 레벨당 ≈2,134판) |
| D5 | shadow 종료 기준 | ★배치 1개 분량(끊기면 ≥1,000호출+기믹별 ≥30) / 고정 N호출 / 달력 2주 |
| D6 | 속도 기준 | ★generate p50 ≥5×·측정 ≥10×·p95 악화 없음 / PLAN 원안 generate ≥10× |
| D7 | serve 계약 두께 | ★최소(ID·deadline·EOF·버전·unsupported, 타임아웃 시 kill) / 취소·기능 협상 포함(패널 B) |
| D8 | CPU·메모리 배정 | gen 8프로세스×C# 1스레드 + 측정 4스레드(★) / gen_pool 축소 ; shadow 기간 다른 계산 세션 중지 여부 |
| D9 | 서버 재시작 시점(shadow 켜기, on 켜기) | 마더 조율 + 사용자 승인 |
| D10 | on 후 표본 감시 비율 | 0 / ★2% / 5% |
| D11 | 시험 배치 파이썬 기준 | ★100레벨만 파이썬 동시 비교 + 8월 기록 / 1,530 전체 파이썬도 실행(+4.5~11 h) |
| D12 | 미검증(None)·플레이테스트 큐 레벨 처리 | 8월처럼 그대로 내보내기 / ★목록 보고 후 사용자 판단 / 통과 레벨만 내보내기 |
| D13 | 100레벨 구간 생성 방법 | ★기존 `levelRange` 를 쓰는 화면 경로가 있으면 사용 / 1,530 시작 후 중지 / 구간 입력 UI 추가(프론트 수정 별도 승인) |
| D14 | 시험 결과 레벨의 실사용 | 시험용 보관만(★) / 라이브 후보로 승격(업로드·DDA·플레이테스트 별도 승인) |

---
## 5. 범위 밖 (이번에 안 함)
- **A\*(BotSimulator 규칙 `solve_level`) C# 이식** — 선택 항목, 5~8 인일 [문서 산정 §5]. 배치 잔여 최대 덩어리(5~38 min). FastJudge 는 규칙이 달라 대체 불가 [문서 조사 §2-1].
- **조기 중단(막힘 검사 "2승/4패에서 멈춤")** — 보고 `clear_rate`·`avg_moves` 가 바뀌고 `_ensure_no_deadlock` 이 실패 후보 중 클리어율 최고 레벨을 고르므로(F8, generator.py:16753) 선택 레벨이 달라짐 + 후속 RNG 흐름 변화(F7). 이식 완료 후 별도 결정.
- MC v2~v2.4 정책 sweep, `/generate/validated`·enhance·batch-verify·autoplay `on`(autoplay 는 combo·std 집계 필요), reverse_generator, assess, pv/evaluate.
- 파이썬 봇 제거(폴백·미지원 경로 때문에 유지).
- 시험 배치의 GBoost·LiveBackup 업로드, 게임/라이브 서버 배포, 사람 플레이테스트, sp DDA 시드 판정(4단계 4-5 표).

---
## 6. 미확인·한계
- C# `Combo`·`TotalCleared` 가 파이썬 `combo_count`·`total_tiles_cleared` 와 비트 일치하는지(기존 매 수 스냅샷 비교 항목에 들어 있는지) 미확인 → 1-A 회귀에 넣음.
- 생산 GenerationParams 복원 가능 여부, DDA 야간 작업의 정기 실행 여부, 스냅샷 39b10a1c 와 v6 의 출력 동일 여부 미확인.
- macOS ProcessPool 시작 방식(spawn)과 리더 스레드 상호작용, IPC 왕복 시간, 상주 워커 배수(15~27×)는 미측정 추정.
- 작업량·시간은 모두 추정. 이번 세션은 실행·측정 0회(4단계 근거용 8월 배치 meta 집계 = 파일 읽기만).
- 4단계: 화면에서 임의 구간(1~100) 생성 가능 여부, 현재 RL 판정 코드가 8월 당시와 같은지, 내보내기 파일에 무한 레벨 복사가 기본 포함되는지 미확인.
