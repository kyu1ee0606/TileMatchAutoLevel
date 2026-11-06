# C# 가속 계획 — 맵툴·DDA 도구의 시뮬레이션 코어 이식 (2026-11-02, 계획만·구현 없음)

작성: 하위 세션 "C#가속계획". 코드·기존 문서 수정 없음. 실측은 단일 프로세스·짧게, 기계 부하 load avg 37~43(10코어) 상태에서 잼 → **절대 시간은 부풀려져 있음**(같은 입력 2회 3.97 s / 2.26 s, 편차 ~1.7배).
표기: **[실측]** = 이번에 직접 잰 값 또는 기존 산출물(csv/jsonl `sec` 열) 합산, **[정적]** = 코드 읽기, **[추정]** = 근거 있는 예측(측정 아님).
원자료: `/tmp/csharp_accel/` (prof_bot_judge.txt, det_check.txt, prof_generator.txt, prof_solver.txt, prof_mc.txt, 스크립트 prof_*.py).
**개정 2026-11-02 (사용자 결정 반영)**: 바뀐 절에 **[개정]**/**[신설]** 표시 — §0 요약(이전 원칙·순서·작업량), **§0-A 이전 절차(공통 게이트) [신설]**, §3-3 폴백 문단, §5 로드맵 전면, §6 끝 CPU 메모, **§8 결정 대기·착수 시점 [신설]**. 그 외 절은 어제 내용 그대로.

---
## 0. 1페이지 요약 [개정]

**이전 원칙 (사용자 결정 2026-11-02)**: "맵툴 관련 개선은 C# 작업부터 우선 하고, 파이썬과 같이 돌리면서 결과가 동일하고 속도가 빠른지 검증한 뒤에 이전한다."
→ ① 맵툴 쪽 C# 작업이 최우선. ② 어떤 단계도 **파이썬과 병행 실행(shadow) → 동일성 판정 → 속도 판정**을 통과해야 C# 결과를 서비스에 쓴다(§0-A). ③ 통과 전엔 서비스 결과는 항상 파이썬 것. ④ 파이썬 경로는 안정화 전까지 폴백으로 유지.

**핵심 사실**
1. 두 저장소의 느린 작업은 결국 **엔진 2개**로 모인다: (a) fengine 계열 A* 판정(sp, 이미 FastJudge C# 이식 중), (b) **맵툴 BotSimulator**(`bot_simulator.py` 7,040줄) — 봇 판정·교체 탐색(봇)·레벨 생성(내부 교착 검사)·검증 생성·autoplay·MC/RL/tune·pv evaluate·맵툴 A*(solver.py 는 BotSimulator 규칙을 그대로 씀) 전부가 이것을 탄다 [정적].
2. 레벨 생성기는 **생성 자체가 아니라 생성 안의 봇 시뮬이 시간의 97~99%** [실측: `generate()` 3.1 s 중 `_ensure_no_deadlock` 3.1 s, 10.1 s 중 9.8 s]. 생성 코드(배치·패턴)는 옮길 필요 없음.
3. 맵툴 A*(solver.py)는 5 s 예산에 **768 노드**만 전개하고 보통 레벨 2개 모두 UNCERTAIN [실측]. 시간 65~70%가 상태 복사(`_fast_copy_state`). FastJudge C# 은 **중앙값 25만 노드/s**, 파이썬 fengine 1.7만 노드/s [실측: 기존 결과 csv].
4. 봇 1판 비용: 그리디 프로필 9~80 ms/판, **θ>1(롤아웃 탐색) 프로필은 6 s/판** [실측 θ1.3: 16판 95 s]. seek 의 hard 레벨 v24_1.3, mc_difficulty·tune 의 θ>1 격자가 이것.

**무엇을 옮기면 얼마나 빨라지나**
| 대상 | 지금 | C# 후 (기대) | 근거 |
|---|---|---|---|
| A* 판정(sp, 14,364칸) | CPU 24.0 h | CPU 3.3 h (**7배**, PATH 칸만 17배) | [실측] FastJudge 전수 실행(다른 세션) official_ref.csv |
| 봇 판정 bot_judge(816칸×60판) | CPU 1.18 h | 1~4 분 CPU (**20~60배**) | [실측 Python] + [추정 C#] |
| 교체 탐색(봇) seek/replace | 후보당 4~10 s, θ1.3 은 판당 6 s | 후보당 0.1~0.3 s, θ1.3 판당 30~120 ms | [실측]+[추정] |
| 레벨 생성 `generate()` | 3~10 s/회 (봇 10~58회 호출) | 0.2~0.5 s/회 (생성 파이썬 부분만 남음) | [실측]+[추정] |
| 맵툴 A* solve_level | 5 s 에 768 노드, UNCERTAIN | 5 s 에 ~100만 노드 → 판정 확정 비율 큰 폭 상승 | [실측]+[추정] |
| MC 난이도(8점×64판) / tune / rl_sim | θ≤1 점 ~0.1~5 s, θ>1 점 수 분 | 20~100배 | [실측]+[추정] |

**추천 순서 [개정: 맵툴 쪽 C# 우선, 단계마다 shadow·검증 포함]**: ⓪ 코어 분리(FastJudge → 공용 코어, shadow 하네스 포함) → ① 봇 시뮬(맵툴 BotSimulator `bs` 모드 충실 이식, 파이썬 호환 RNG 로 매 수 동일; DDA `bot_judge` 대체도 **같은 코어**) → ② 맵툴 solver·autoplay·batch-verify 상주 워커 → ③ 생성기 막힘(교착) 검사·검증 생성·MC/RL/tune/pv evaluate. (④ 선택: 게임 원문 규칙 모드 전환·Unity 오라클.) 각 단계 = 구현 → shadow → 동일성 판정 → 속도 판정 → `on` (§0-A).
**통합 방식 추천**: sp 배치 = CLI + JSONL(지금 FastJudge 방식 유지). 맵툴 = **상주 C# 워커(stdin/stdout JSONL, 다중 스레드) + 파이썬 얇은 클라이언트 + `TILECORE=off|shadow|on` 스위치**. pythonnet·NativeAOT 공유 라이브러리는 비추천(후순위).
**총 작업량 [개정]**: 구현 + shadow·동일성·속도 검증 포함 **⓪~③ 37~52 인일**(⓪ 3~5, ① 13~18, ② 8~11, ③ 13~18), ④ 포함 40~57. (어제 30~40 → 검증 작업 약 +9~12 인일.) shadow *기간*(달력)은 다음 단계 구현과 겹치므로 인일에는 비교·분석 작업만 넣음. 달력은 §5. 가장 큰 위험 = BotSimulator 정책 코드(점수·v2.4 행동 플래그 73곳)의 충실 이식 범위 — ①의 첫 작업으로 **실사용 분기 커버리지 측정** 후 범위를 확정한다.
**착수 시점**: 2026-11-03 DDA 업데이트 이후 착수 권장(오늘 밤은 DDA 판정·교체 탐색이 CPU 사용 중). ⓪ 설계·코드 작업처럼 CPU 거의 안 쓰는 일은 먼저 가능(§8).

---
## 0-A. 이전 절차(공통 게이트) [신설]

모든 단계(① 봇 시뮬, ② solver·autoplay, ③ 생성기 막힘 검사·MC/RL)와 ⓪ 코어 분리에 **똑같이** 적용한다.

1. **C# 구현** — 해당 단계 범위를 코어에 구현. 미지원 프로필/기믹 조합은 `unsupported` 로 거절 → 파이썬이 처리(shadow 에서는 "비교 불가"로 별도 집계, 불일치로 세지 않음. 단 비교 불가 비율을 보고).
2. **병행 실행(shadow, `TILECORE=shadow`)** — 같은 입력을 파이썬과 C# 이 함께 처리, **서비스 결과는 파이썬 것**. 차이는 `shadow_diff.jsonl` 로 수집(입력 해시, 엔진 태그, 파이썬/C# 결과, 첫 불일치 지점, 양쪽 시간). sp 배치는 같은 입력 파일로 두 번 돌려 비교(`--shadow`). C# 오류·타임아웃은 서비스에 영향 주지 않고 로그만.
3. **동일성 판정**
   - 결정적 경로(A*, 동일 rngSeed 봇): 결과·수순 **100% 일치**. 봇은 클리어 여부·첫 클리어 rngSeed·탭 경로·클리어율 전부.
   - 무작위 기믹(개구리·텔레포터 등 봇 RNG 사용): 같은 rngSeed 재현이면 **100% 일치**(MT19937 호환 RNG).
   - rngSeed 재현 불가(예: 파이썬 쪽이 시드 없는 RNG 를 쓰는 경로, 타 엔진 비교): **분포 동등** — 레벨별 판수 ≥300(권장 ≥1,000), 2비율 차이의 95% 신뢰구간이 ±3%p 안 + Bonferroni 보정(레벨 수로 나눔) 후 유의차 레벨 0개; 착지·순열 균등성은 고정 상태 10만 회 χ² 검정 p>0.01. **[검정 기준·표본 수는 제안값 — 사용자/마더 확정 필요]**
   - **불일치 0 이 아니면**: 원인 분류 = (a) C# 버그 (b) 파이썬 버그 (c) 규칙 차이(의도적 `bs`↔`game`) → 매 수 대조(§4-3)로 첫 어긋난 수 찾기 → 수정 → **재측정**(표본 새로 시작). (b)·(c) 는 파이썬을 바꾸지 않고 기록 후 사용자 결정(파이썬 정본 유지 vs 수정)을 받는다.
4. **속도 판정** — 같은 표본·같은 동시 수·같은 기계, 부하 낮은 시간대(§6)에서 **중앙값·p95 시간, 처리량(판/s·노드/s), 최대 메모리(RSS)** 비교표 작성(`speed_compare.md`). 최소 기준은 단계별(아래 표). 기준 미달이면 프로파일 → 최적화 후 재측정; 이전 *자체*는 동일성 통과만으로도 가능하나 "빠르다" 확인 전에는 `on` 안 함(사용자 결정 그대로).
5. **통과 시 `TILECORE=on`** — C# 결과 사용. 파이썬 경로는 **폴백으로 유지**(C# 오류·`unsupported`·버전 불일치 시 자동 사용) + 안정화 기간 동안 표본 1~5% 를 계속 shadow 로 돌려 회귀 감시.
6. **안정화 후 파이썬 제거 여부 결정** — 폴백 발동 0, 감시 불일치 0 이 안정화 기간 지속 시 사용자에게 제안(제거 / 영구 폴백 / 검증 도구로만 유지). 자동 제거 없음.

**단계별 게이트 표**

| 단계 | shadow 기간 | 표본 규모 | 통과 기준 (동일성 + 속도) | 롤백 |
|---|---|---|---|---|
| ⓪ 코어 분리 | 없음(코드 이동). 대신 FastJudge 동결본과 바이트 대조 | R1 500칸 + t0 전수(24,129) + 추가 무작위 500칸 | 결과·경로 파일 **바이트 동일**; 속도 동결본 대비 ≥0.95배(퇴행 없음) | 기존 FastJudge 바이너리 계속 사용 |
| ① 봇 시뮬 (맵툴 bs + DDA bot_judge) | **2주** (sp: 20261029 규모 배치 1회분 + DDA 업데이트 1회, 맵툴: autoplay 요청 shadow) | R2 전 칸(1,524+816) × 30판 × 봇 3종 + R3 레벨 프로필 전부 × 고정 seed 100판 | 클리어 여부·첫 클리어 rngSeed·탭 경로·클리어율 **100% 일치**; 판당 중앙값 **≥20배**(그리디), θ>1 롤아웃 **≥50배**; 메모리 ≤ 파이썬 | `TILECORE=off`; bot_judge.py 경로 그대로 |
| ② 맵툴 solver·autoplay·batch-verify | **1~2주** (실사용 요청 shadow, 서버 재시작은 승인 시) | 실요청 전량 + 고정 회귀 레벨 300개 | autoplay·batch-verify 클리어율 **100% 일치**; solve: 노드 상한 같은 조건에서 판정 범주 일치 100%, PROVEN 경로 파이썬 재생 100% 클리어, 상한 크게 올린 C# 판정은 파이썬 판정과 모순 0(파이썬 UNCERTAIN→C# 확정은 허용·목록화); 요청 지연 중앙값 **≥20배**, solve 노드 처리율 **≥300배** | `TILECORE=off` (코드 경로 유지) |
| ③ 생성기 막힘 검사·검증 생성·MC/RL/tune | **2주** (생성 요청·MC 야간 실행 shadow) | 고정 시드 생성 100건(레벨 JSON 바이트 비교) + MC 격자 R3 전체 + tune/rl_sim 각 1회 | 생성 레벨 JSON **바이트 동일**; 막힘 검사·MC θ 격자 클리어율 100% 일치; `generate()` 중앙값 **≥10배**, MC θ>1 점 **≥30배**, tune/rl_sim 전체 시간 **≥20배** | `TILECORE=off` (스위치별 분리: 막힘 검사/검증 생성/MC 개별 off 가능) |

shadow 비용: 파이썬 + C# 둘 다 돌리므로 CPU = 기존 + C# 몫(C# 이 빨라 +5% 안팎 [추정]). 단 sp 배치 shadow 는 같은 입력 2회 실행이라 *C# 쪽만 추가*, 파이썬 결과는 어차피 필요.

---
## 1. 오래 걸리는 작업 목록과 실측

### 1-1. sp 도구 (`sp_meowsgarden/tools/`)
| 작업 | 호출 흐름 [정적] | 실측 | 핫스팟 |
|---|---|---|---|
| A* 판정 run_all/judge_rows (fengine+fsolve) | variants.jsonl → `fsolve.judge` (2→20→120 s 단계) | 20261029 14,364칸 **CPU 24.0 h**, 중앙 0.17 s, p99 143.7 s; **≥20 s 칸 765개(5%)가 시간 85%**; UNKNOWN(budget) 46%·PATH 51% [실측 results.csv] / rinf 10,258칸 CPU 19.4 h, 같은 분포 | 어려운 칸 탐색. 파이썬 1.7만 노드/s(중앙) |
| 위 작업의 C# 판 (FastJudge, 판정기고속화 세션) | `fastjudge judge --rules ref` | 14,272/14,364 진행 시점 **CPU 3.29 h**, 벽 ~3,000 s(동시 2), 같은 PATH 11,899칸 파이썬 12.1 h → C# 0.7 h (**17.2배**) [실측 official_ref.csv, 실행 중 파일 읽기만] | 남은 시간은 UNKNOWN(budget 120 s) 칸 — 4단계(해시·빔·가지치기)가 담당 |
| 봇 판정 bot_judge.py | 칸마다 `play()` = 봇 2종(optimal+parity, v2.4 θ1.0) × 30판, 맵툴 BotSimulator 서브클래스 | 20261029 1,524칸 CPU 2.13 h(중앙 4.25 s/칸), rinf 816칸 **CPU 1.18 h**(중앙 3.8 s, p90 10.9 s) [실측 bot_results.csv]. cProfile 표본(2칸×2봇×10판=40판, 17.6 s): `_score_move_with_profile` 50%, 덮임 검사(`_is_blocked_by_upper`+`_v23_box_covers`+`_v23_cover_positions`) ~40%, 수 생성 28%(겹침), 개구리 5% [실측 prof_bot_judge.txt] | 매 수 전 타일 덮임 재계산(딕셔너리·문자열 키), 점수 함수 |
| 교체 탐색 seek.py / replace.py / seek_bot.py / retry_wide.py | 대상마다 후보 시드 스트림 → 후보마다 fsolve(2,20 s) 또는 bot_judge.play(30판×2봇, hard 레벨은 v24_1.3 추가) | seek_bot 501후보/97대상 0.68 h(대상당 5.2후보), seek 294후보/15대상 0.21 h(대상당 19.6), retry_wide 3,200후보/16대상 3.02 h, replace_partial 629대상 3.43 h(v1 14.4 h) [실측 *log.jsonl 합] | 후보 판정 반복 = 위 두 판정기의 곱. **봇 판정은 첫 클리어 후에도 30판 끝까지 돎**(bot_judge.py:51-56) |
| dda_level_fix/key_relocate.py | KEY 행마다 후보 배치 여러 개 × fixed_eval.bot_rates(30판×2봇) + 선택 후 판정 | 미측정(실행 중일 수 있어 건드리지 않음) [정적] | bot_judge 와 같은 코어 |
| t0 배정 gamet0 / VariantDump | 행당 ms 단위 | 병목 아님 [정적, FastJudge 에 이미 C#] | — |

결정성 확인 [실측 det_check.txt]: 같은 2칸을 PYTHONHASHSEED=1, 2 로 각각 돌려 클리어율·첫 클리어 rngSeed·경로 길이 동일(infinity_262: optimal 0.9 / v2.4 0.4 / rngSeed 4242 / 78수; infinity_414: 0.0 / 0.1 / 4248 / 129수). → 파이썬 봇이 문자열 해시 순서에 의존하지 않는다는 **표본 2칸 근거**(증명 아님). 매 수 동일 대조(4절)의 전제.

### 1-2. 맵툴 (`~/TileMatchAutoLevel/backend/app`)
| 작업 | 호출 흐름·기본값 [정적, 파일:줄] | 실측 | 비고 |
|---|---|---|---|
| `LevelGenerator.generate` | generator.py:1020 → 항상 `_ensure_no_deadlock`(:1273-1287, 기본 2회 시도) → `_quick_deadlock_check`(:16387, optimal 5판) + `_fix_same_type_blocking`(:16235, 최대 50시드×3판) | lv150 td0.3: **3.12 s 중 3.11 s 가 봇**(play_game 8판); lv600 td0.6: **10.09 s 중 9.83 s**(simulate_with_profile 58회, play_game 178판) [실측 cProfile prof_generator.txt] | 생성 순수 부분 ≤0.3 s. `_fix_same_type_blocking` 이 스파이크 원인 |
| `/generate` | gen_pool → generate, 타일 하한 재시도 ≤5(generate.py:124-127), reverse_generation 시 봇 15판 + solve_level 120k노드/6 s(reverse_generator.py:328-364) | 미측정(서버 경로, 재시작 금지) | — |
| `/generate/validated` | 시도 ≤max_retries(기본 5)×{generate + 봇 3~5종×8~25판(+3회마다 리셔플 2배)} × 타일 하한 재시도 ≤5 (generate.py:1572-2660) | 기본 `simulation_iterations=0` → 검증 봇 없음(=generate 비용만). 켜면 시도당 봇 3~5×최대 25판 [정적] | 봇 1판 실측: casual 4~40 ms, average 24~107 ms, expert 27~107 ms, optimal 27~126 ms (20판 기준, 레벨 2개) [실측] |
| `/generate/enhance` | 반복 ≤5 × 봇 3종 × 50판 | 미측정 | — |
| solver.solve_level | 60k 노드/5 s 기본(solver.py:29-30), BotSimulator `_get_available_moves/_apply_move/_fast_copy_state` 사용, 서명 = 정렬 튜플 | **lv150·lv600 모두 5.0 s 에 768 노드 전개 → UNCERTAIN** [실측 prof_solver.txt, cProfile 켠 상태]. `_fast_copy_state` 63~73% | 호출처: reverse_gen, analyze(batch-verify 실패 시 300k/12 s, /solvability), rl_sim(200k/8 s), study(measure_robustness ≈570회 solve/레벨), pv/evaluate. **batch 경로는 time_budget 을 버림(solver.py:374)** |
| `/analyze/autoplay` | 프로필별 100판(10~1000), autoplay_pool | 미측정(위 1판 비용 × 100 × 프로필 수 ≈ 수 s~수십 s) [추정] | — |
| `/analyze/batch-verify(-regenerate)` | 스레드 4개(GIL → CPU 병렬 없음), 3봇×20판 + 실패 시 solve 300k/12 s | 미측정 | 스레드 대신 C# 상주 워커면 진짜 병렬 |
| mc_difficulty sweep | 8 θ점 × 64판, `sweep_point_task`, rl_sim pool(cpu-2) | 16판 실측: θ0.3 0.14 s(9 ms/판), θ0.9 1.31 s(82 ms/판), **θ1.3 95.3 s(5,958 ms/판)** [실측 prof_mc.txt, 프로파일러 없음] | θ>1 = `search_rollouts=(θ-1)·10` 롤아웃(V2_SEARCH_WIDTH 6 × LEN 10) — 복사+v2_step |
| mc_search / tune / rl_sim batch | 후보 16 × 스크리닝 24판 + 결선 5×격자 / tune 후보 6~12 × 격자 | 미측정 → 위 판당 비용으로 산정 가능 | — |
| pv/evaluate | `_TrackingBot(BotSimulator)` θ(0.29,0.47,0.65) × 100판 청크 + solve 5000노드 | 미측정 | 오프라인 스크립트 |
| assess / difficulty_assessor | 봇당 100판(quick ≤50, detailed ≥500) | 미측정 | — |
| simulator.py(LevelSimulator) | `/simulate` 전용 옛 엔진 | — | **이식 대상 아님**(레거시) |

기존 C# 자산: `~/TileMatchAutoLevel/tools/pv_golden/`(net8, 게임 DB_Level.cs t0 셔플 추출 + UnityEngine 심, 골든 파일 생성용, 백엔드 미사용) [정적]. `pv/cs_shuffle.py` 는 게임 t0 분배의 비트 일치 포팅(규칙 엔진 아님).

---
## 2. C# 이식 후보 평가

| # | 작업 | (a) 시간 비중 | (b) 이식 난이도 | (c) 기대 배수 | (d) 파이썬 통합 | (e) 정합성 검증 |
|---|---|---|---|---|---|---|
| A | sp A* 판정 (FastJudge) | sp 배치 최대(24 CPU-h/회) | **진행 중**(판정기고속화) | 7배(전체)·17배(PATH) 실측, 4단계 후 UNKNOWN 감소 | CLI JSONL (이미) | 이미: py_equiv·cs_parity(t0 24,129칸, walk 20만 수, 노드 상한 탐색 330개 동일) |
| B | **BotSimulator 규칙 코어**(상태·수 생성·적용·기믹·실패·개구리·텔레포터·냥이의 도움·t0) | 아래 C~H 전부의 공통 바닥. bot_judge 프로파일에서 덮임·수 생성·효과 ≈ 45~50% | 중상: 규칙 부분 ≈2,000줄(_create_initial_state 340, stack/craft 400, moves/apply/effects 900, v23 parity 500). 무작위 = `random.Random` 3개 스트림(self._rng, c_rng, mem_rng, style_rng, getrandbits(128) 시드 파생) | 50~150배 [추정: 비트셋+사전계산 덮임, FastJudge 대비 상태 크기 비슷] | 상주 워커/CLI | **파이썬 호환 MT19937**(seed(int)·random()·getrandbits·_randbelow·choice·shuffle·randint·randrange 를 CPython 알고리즘 그대로) → 같은 rngSeed 로 **매 수 동일** 대조 가능 |
| C | 봇 정책(프로필 수 선택) | bot_judge 의 50%(점수 함수) + θ>1 롤아웃 전부 | **상**: `_score_move_with_profile` 680줄, `_select_move_with_profile` 140줄, v2 search/rollout/determinize 250줄, v2.4 행동 ~600줄, optimal 완전정보 전략(+`copy.deepcopy`) 300줄+, 플래그 분기 73곳 | 30~100배 (롤아웃은 복사 비용 제거로 100배+) [추정] | B 와 같은 워커 | 같은 RNG + 같은 부동소수 연산 순서 → 수 선택 동일. **주의**: 파이썬 `sorted`/`max` 의 안정·첫 최대값 규칙(C# `List.Sort` 는 불안정 → 안정 정렬 사용), dict 삽입 순서 = 타일 순회 순서, `sum()` 순서 |
| D | sp 봇 판정 bot_judge·seek_bot·replace(봇)·key_relocate | sp 봇 경로 100% (816칸 CPU 1.18 h, θ1.3 은 판당 6 s) | B+C 중 사용 프로필 3개만(optimal+parity 강제, v2.4 θ1.0, v2.4 θ1.3) | 20~60배 [추정] + **첫 클리어 즉시 중단 옵션**(seek 용, 파이썬에서도 가능) | CLI JSONL: `tilecore bot --variants … --bots optimal,v24_1.0 --games 30 --rng-base 4242` → bot_results.csv 같은 열 | 같은 rngSeed 30판 클리어 여부·경로 **판별 일치**(목표 100%), 불일치 시 매 수 대조로 원인 |
| E | 맵툴 solver.solve_level / measure_robustness / safe_moves | autoplay·batch-verify 실패 경로·study(밤샘 13 h)·reverse_gen | 하: 규칙 = B, 탐색 = FastJudge Search 재사용. 단 맵툴 판정 범주(PROVEN_SOLVABLE/IMPOSSIBLE/UNCERTAIN, 무작위 기믹은 IMPOSSIBLE 불가 규칙 solver.py:36) 유지 | 노드 처리율 300~1,000배 [추정: 파이썬 ~150 노드/s(프로파일 켬) vs C# 25만] | 상주 워커 `solve` 요청 | 같은 레벨에서 PROVEN 결과의 경로를 파이썬 BotSimulator 로 재생해 클리어 확인, IMPOSSIBLE 은 노드 상한 낮춰 파이썬과 판정 일치 |
| F | 생성기 교착 검사(`_quick_deadlock_check`, `_fix_same_type_blocking`) | **generate() 시간의 97~99%** [실측] | 하(B+C optimal 프로필만). 호출 2곳 교체 | generate 3~10 s → 0.2~0.5 s [추정] | 상주 워커 `simulate` | 같은 시드로 클리어율 동일(매 수 동일 모드) → 생성 결과(레벨 JSON) 바이트 동일까지 확인 가능 |
| G | 검증 생성 루프·enhance·autoplay·assess | 검증 켤 때 지배적 [정적] | 하(F 와 같은 API). 루프·재시도 로직은 파이썬 유지 | 20~60배 | `_simulate_single_bot` 내부만 교체 | 요청 단위 결과(선택된 레벨·match_score) 동일, 클리어율 동일 |
| H | 난이도 측정 MC/mc_search/rl_sim/tune/pv evaluate | θ>1 점이 지배(판당 6 s) | 중: θ 보간 프로필 전 버전(v1/v2/v2.1/v2.3/v2.4) 정책 커버 필요 → C 범위 확대. pv `_TrackingBot` 의 추적 훅(어떤 통계를 모으는지) 이식 | 20~100배 | `sweep_point_task` 를 워커 호출로 | θ 격자별 클리어율 동일(매 수 동일 모드), 분포 모드면 2비율 검정 |
| I | 개구리·텔레포터 판정(판정기고속화 3단계) | sp UNKNOWN(unsupported) 칸 | B 에 이미 포함되는 규칙(frog_land, tele_perm) → **같은 코어 재사용**하면 중복 없음 | — | — | 분포 비교(4-4) |
| J | simulator.py LevelSimulator | `/simulate` 뿐 | — | — | **이식 안 함** | — |

### 2-1. BotSimulator 이식 상세
- **범위 확정 절차(①의 첫 작업)**: 회귀 레벨 세트(4-2)로 실제 쓰는 프로필 조합(sp 3종, 맵툴 BotType 4~5종, make_skill_profile 격자 θ×버전)을 파이썬에서 `coverage.py` 분기 커버리지로 돌려 **실행되는 분기만** 이식 대상으로 고정. 미이식 플래그 조합은 C# 이 `unsupported_profile` 로 거절 → 파이썬 폴백. (플래그 `in self._v24/_par` 검사 73곳 [정적 grep])
- **두 의미론 모드**: `--rules bs`(BotSimulator 그대로, 버그 포함 — 정합성 기준) / `--rules game`(DIFF.md 차이 해소). 처음에는 bs 로 동일성 확보 → 항목별 플래그로 game 쪽 전환(4-1).
- **무작위 처리**
  - 봇 자체 무작위(실수율·충동·롤아웃 시드): CPython MT19937 재현으로 **비트 일치**. `random.Random.seed(int)` = init_by_array(절댓값 32비트 청크), `random()` = (a>>5, b>>6) 53비트, `_randbelow` = getrandbits 거부 샘플링, `shuffle` = 역순 Fisher-Yates + `_randbelow`, `choice` = `_randbelow(len)`. 단위 테스트: 파이썬이 뽑은 수열 10만 개와 대조.
  - 개구리(게임 = 시드 없는 UnityEngine.Random): 봇은 자기 RNG 로 `shuffle(available_tiles)`(bot_simulator.py:3026) → 위 재현으로 파이썬과 동일. 게임과는 **분포만** 같게(후보 C 중 F 칸 균등) — 기기 재현은 원리상 불가(ANALYSIS.md 2-1).
  - 텔레포터(게임 = `new System.Random()`): BS `tele_perm` Sattolo 순환을 같은 RNG 소비 순서로 이식 → 파이썬과 동일, 게임과 분포 동일((n-1)! 균등).
- **클리어율 분포 동등성**: 매 수 동일 모드에서 같은 rngSeed 목록이면 클리어율이 **정확히 같아야** 함(통계 검정 불필요). game 모드 전환 후에는 레벨별 클리어율 차이를 2비율 검정(예: 판수 ≥300, |Δ| 의 95% 신뢰구간) + 전체 회귀 세트에서 판정(PATH_BOT/SUSPECT) 뒤집힘 목록으로 영향 보고.

### 2-2. 레벨 생성기 — 어디만 옮기면 되나
- 생성 자체(패턴·레이어·기믹 배치·색 균형, generator.py 1.7만 줄): **옮기지 않음**. 실측상 0.3 s 이하.
- 옮길 것 = 생성 안의 봇 호출 2곳(`_quick_deadlock_check` :16412-16427, `_fix_same_type_blocking` :16275-16296)과 검증 루프의 `_simulate_single_bot`(generate.py:2192-2200, 2584-2606), reverse_generator 의 봇 15판 + solve_level. 모두 `simulate_with_profile(level_json, profile, iterations, seed, …)` / `solve_level(...)` 시그니처 하나로 모임 → **파이썬 쪽은 이 두 함수의 구현만 바꾸는 어댑터**.

### 2-3. 난이도 측정
- MC(mc_difficulty)·rl_sim·tune·mc_search 는 모두 `sweep_point_task` → `simulate_with_profile` 로 모임 → 같은 어댑터. pv/evaluate 는 `_TrackingBot` 서브클래스가 기록하는 통계(무엇을 덮어쓰는지)를 C# 결과에 같이 실어 보내도록 API 에 "trace 옵션" 추가.
- 파이썬은 격자·집계·회귀만 유지, 시뮬레이션 코어만 공유 엔진.

---
## 3. 공통 엔진 구조

### 3-1. 계층
```
TileCore (C# 라이브러리, net9)
 ├─ Model     : 레벨 JSON 파싱(맵툴 level_json / sp DDA row 둘 다), 타일 색인, 덮임 사전계산(비트마스크), 스택·craft·링크·이웃
 ├─ T0        : gamet0 이식(FastJudge MapModel) + 맵툴 TileDistributor/cs_shuffle 경로(같은 게임 원문 → 하나로)
 ├─ Variant   : 게임 DdaMapTransformer·DdaVariantCatalog·zWellRandom 소스 링크(현행 csproj 방식)
 ├─ Rules     : 상태(비트셋 occ + 기믹 카운터 + 독 정렬 바이트 + 클릭 수 + 개구리/텔레포터 위치) / Moves / Apply / Fail
 │              모드: fe-ref | fe-game (FastJudge 현행) | bs (BotSimulator 동일) | game (DIFF 해소 최종)
 ├─ Rng       : PyRandom(MT19937 CPython 호환), ZWell(게임), 기타
 └─ Telemetry : 매 수 trace(합법 수 목록·선택·독·카운터) — 대조용
모듈
 ├─ Judge     : A*/빔/가지치기 (FastJudge Search — 판정기고속화 4단계 결과 그대로 흡수)
 ├─ Bot       : BotSimulator 정책(프로필) + simulate(n판, rngSeeds) + 첫 클리어 중단
 ├─ MC        : θ 격자 sweep, 재계획 봇(판정기고속화 3단계 개구리 몬테카를로가 여기 사용)
 └─ GenCheck  : 교착 검사·solve_level 의미 범주 어댑터
CLI `tilecore` : judge | bot | sweep | solve | t0 | variants | walk | serve(상주 워커)
```
- 원칙: 규칙 모드는 **상태 표현 하나 + 규칙 분기 플래그**(같은 Apply 에 모드별 분기). fengine 의미론과 BotSimulator 의미론의 차이(DIFF.md #4 stack_cover, #7 얼음, #8b 커튼 규칙 등)는 플래그 항목으로 1:1 관리(V23_PARITY_ITEMS 명명을 그대로 씀).
- 출력마다 `TileCore/<semver>/rules=<mode>/<git short sha>` 태그(현 FastJudge `Tag()` 방식 확장) → 결과 파일에서 엔진 버전 추적.

### 3-2. 배포·버전
| 안 | 내용 | 장단 |
|---|---|---|
| **별도 저장소 `~/tilecore`(git, 추천)** | 코어+CLI+테스트. 게임 소스는 `GameRoot` 속성으로 링크(현 csproj 방식), 게임 dll 스냅샷 경로 설정 | 두 도구가 같은 커밋을 지정. 태그 `v0.x`, 빌드 산출물 `~/tilecore/dist/<ver>/` 고정(덮어쓰기 금지) |
| 공유 폴더(sp tools 안) | FastJudge 처럼 sp 저장소 안 | 맵툴이 sp 저장소 경로에 의존, 버전 고정 어려움 |
| 맵툴 저장소 안 | — | sp 도구가 맵툴에 의존(지금 bot_judge 가 이미 그렇다) |
- 맵툴·sp 는 환경변수 `TILECORE_BIN=~/tilecore/dist/0.3.1/tilecore` 로 버전 고정, 시작 시 `tilecore version` 확인 후 기대 버전 아니면 파이썬 폴백 + 경고.
- 판정기고속화 세션의 FastJudge(`dda_seed_verify_fast/cs`)는 **그 세션 4단계 완료·동결 후** ⓪에서 코드 이동(복사 후 원본은 동결 사본으로 남김; 이동은 그 세션/마더 승인 필요).

### 3-3. 통합 방식 비교
| 방식 | 지연 | 처리량 | 운영 | 디버깅 | 판단 |
|---|---|---|---|---|---|
| CLI 서브프로세스 + 배치 JSONL | 프로세스 기동 ~50~100 ms(.NET, ReadyToRun 시 더 짧음) [추정] | 배치면 최고(내부 다중 스레드) | 가장 단순, 재현(입력 파일=재실행) | 입력 jsonl 로 그대로 재현 | **sp 배치 도구 표준** |
| 상주 프로세스 + stdin/stdout JSONL(또는 유닉스 소켓) | 요청당 ~1 ms 미만 [추정] | 높음, 다중 스레드 1프로세스로 코어 활용 | 수명 관리(시작·헬스체크·재시작), 버전 고정 | 요청 로그 jsonl 저장 → CLI 로 재현 | **맵툴 서버 표준**(작은 요청 다수: generate 안 5판×2, 검증 25판×5) |
| pythonnet | 호출 µs | 높음 | multiprocessing spawn 마다 CLR 기동·메모리 중복, GIL 하에서 .NET 스레드 해제 관리, 버전 결합 | 혼합 스택 디버깅 어려움 | 비추천 |
| NativeAOT 공유 라이브러리 + ctypes | 호출 µs | 최고 | C ABI·마샬링 직접 관리, 크래시 = 파이썬 워커 동반 사망 | 어려움 | 후순위(지연이 진짜 병목일 때만) |
- 추천 근거: 맵툴의 요청 단위 시뮬은 수십~수천 판(ms~s)이라 1 ms 왕복은 무시 가능 → 상주 워커로 충분. 기존 ProcessPool(bot_pool 3, gen_pool cpu-2, autoplay_pool cpu-2, rl_sim pool cpu-2)은 C# 워커 하나(스레드 N)로 대체 가능 → **코어 과다 사용도 줄어듦**.
- 폴백 [개정]: 환경변수 `TILECORE=off|shadow|on`. `shadow` = 파이썬·C# 둘 다 돌리고 **서비스 결과는 파이썬**, 차이만 로그. `on` = C# 결과 사용(파이썬은 폴백). 기간·판정은 §0-A 단계별 표.

---
## 4. 정합성 체계

### 4-1. DIFF.md 차이 해소 방법 (C# 코어 `game` 모드)
| DIFF # | 차이 | C# 처리 |
|---|---|---|
| 6, 8 | FE 링크 쌍 폭탄 2감소·커튼 2회 토글 | 이미 FastJudge `--rules game` 에서 해소(m_selectedFirst). 코어로 승계 |
| 7a | BS 얼음 실패: 다 녹은 얼음을 비얼음에서 제외 | `game` 에서 TileGroup.cs:2855-2890 대로. `bs` 는 원래대로 |
| 7b | BS 링크 쌍 얼음: 이동 전 노출 집합 | `game` = 2번째 타일 때 재판정(FE 와 같음) |
| 8b | BS 커튼 특수 규칙 대상(스택 속·미배출 craft 누락) | `game` = GetAllRemainTilesOnLevel 기준. "마지막/첫 커튼" 색인 순서는 c_TileList 스폰 순서 확인 필요 → Unity 덤프 항목(4-2) |
| 12 | 열쇠 잠금 해제 타이밍(트윈 후) | 기본 "느긋한 플레이어" 유지. 선택 플래그 `tempo=fast` 로 다음 1수까지 잠금 유지 모델(민감도 분석용) |
| 14, 15, 5 | 개구리 0.5 s 창, 텔레포터 0.5 s 지연, craft 배출 onAnim | 기본 느긋 모델. `tempo=fast` 플래그로 각각 모델 → 판정 영향 크기만 보고 |
| 16 | 타임어택 미모델 | 봇 판정에서 `timea>0` 칸은 `PATH_BOT_UNTIMED` 로 구분 표기(판정 범주 변경은 마더/사용자 결정) |
| 17 | BS max_moves = 칸 수+50(스택·craft 1칸) | `bs` 는 그대로, `game` 은 상한 = 전체 타일 수+여유(이동 상한 없음이 원문) |
| 3 | 덮임 기하(FindAllUpperTiles 미대조) | Assembly-CSharp 스냅샷의 `CLevel.FindAllUpperTiles` 를 링크 가능하면 레벨 로드 때 교차 검사(ANALYSIS 6절 (c)). 불가 시 Unity 덤프 대조 |
| 18 | 아이템·냥이의 도움 | `auto_collect` 는 BS 이식 대상(맵툴 사용). 아이템은 범위 밖 |

### 4-2. 회귀 데이터 세트
| 세트 | 출처 | 용도 |
|---|---|---|
| R1 A* 판정 | 20261029 results.csv 14,364칸 + rinf 10,258칸 + FastJudge official_ref.csv/paths | Judge 모드 회귀(판정 범주·경로 재생) |
| R2 봇 판정 | 20261029/bot, rinf/bot bot_results.csv(칸별 rate·clear_rngSeed) + clear_paths.jsonl | Bot `bs` 모드: 클리어율·첫 클리어 rngSeed·탭 경로 **완전 일치** |
| R3 맵툴 레벨 | 맵툴 production_store / benchmark 레벨(claudedocs/benchmark_result_*.json) + 생성기 고정 시드 출력 | simulate_with_profile 프로필 전부 × 고정 seed → 클리어율 동일 |
| R4 t0 | FastJudge t0_all/t0_rinf + pv_golden(`backend/tests/golden/pv_t0`) | 두 t0 경로가 같은 게임 원문임을 상호 확인 |
| R5 Unity 덤프 | 원본 README 의 15판(이 머신에 없음 — FastJudge README) + 새 덤프(QaAutoMatch 궤적) | 오라클. **Unity 실행은 별도 승인 필요** |
- 회귀 실행은 표본(예: 각 세트 300~500칸, 계층 표본: 판정 범주·기믹별) 매 커밋, 전수는 릴리스 태그마다.

### 4-3. 매 수 대조(transition parity)
- `tilecore walk --rules bs --trace` 와 파이썬 BotSimulator 계측(서브클래스로 `_get_available_moves`·`_apply_move` 후 상태 덤프) 출력의 **수 단위 diff**: 합법 수 집합(정렬), 선택 수, 독 내용, 기믹 카운터, 개구리·텔레포터 위치, RNG 소비 횟수(호출 카운터 — 어긋난 첫 지점 찾기).
- 정책까지 포함: 후보별 `score` 값을 1e-9 허용 오차로 대조 → 어긋나면 점수 항목별(덮임·체인·풀·폭탄 등) 분해 출력.
- 기존 transition_parity.py(FE↔BS)·cs_parity.py(C#↔FE) 를 3자 대조로 확장: C#(fe) ↔ fengine, C#(bs) ↔ BotSimulator, C#(game) ↔ 게임 덤프.

### 4-4. 무작위 기믹 분포 비교 기준
- 같은 엔진 내부(파이썬↔C#, `bs` 모드): RNG 재현으로 **정확 일치** — 분포 검정 불필요.
- 모델↔게임: 개구리 착지 = 후보 C 칸 중 F 칸 균등, 텔레포터 = (n-1)! 순환 균등. 검증 = (i) 엔진에서 고정 상태 10만 회 착지 빈도 χ² 검정(균등성), (ii) Unity 덤프(승인 시)에서 후보 집합 C 의 정의(CheckMask·onAnim 제외 등)가 엔진과 같은지 **집합 일치** 확인 — 확률 값이 아니라 지지 집합을 대조.
- 클리어율: 모드 전환 영향은 레벨별 2비율 차이 95% CI 와 판정 뒤집힘 목록으로 보고(판수 ≥300 권장, C# 이면 비용 무시 가능).

---
## 5. 단계별 로드맵 [개정]

순서 원칙: **맵툴 쪽 C# 작업 우선**(사용자 결정). 모든 단계는 §0-A 게이트(구현 → shadow → 동일성 → 속도 → on)를 통과. 아래 "완료 기준"은 §0-A 표의 통과 기준과 같다. 작업량은 **구현 + 검증(shadow 로그 분석·불일치 분류·속도표) 분리 표기**.

판정기고속화 세션과의 경계: **그 세션 = Judge 모듈(4단계: 64비트 해시 상태·빔 먼저·불가능 가지치기)과 3단계(개구리·텔레포터 판정)**. 이 계획은 그 결과를 코어로 흡수한다. 3단계를 ① 코어 위에서 할지 / 별도 장기안으로 할지는 **§8 결정 대기 #1**.

| 단계 | 목표·범위 | 완료 기준 | 작업량 | 위험 | 롤백 |
|---|---|---|---|---|---|
| ⓪ 코어 분리 | FastJudge(4단계 동결본) → `~/tilecore` 라이브러리+CLI, 기존 CLI 명령 호환, 테스트 하네스(cs_parity 이관), **shadow 하네스**(shadow_diff.jsonl 수집·비교표 생성 도구, `TILECORE` 스위치 골격) | FastJudge 동결본과 R1 표본 500칸·t0 전수 결과 바이트 동일; 속도 퇴행 없음 | **3~5일** = 구현 2~3 + 검증·shadow 하네스 1~2. **설계·코드(CPU 거의 안 씀)는 11-03 이전에도 가능**, 바이트 대조 실행만 DDA 이후 | 판정기고속화 진행 중 코드와 충돌 → 4단계 착지 후 코드 이동 | 기존 FastJudge 바이너리 그대로 사용 |
| ① 봇 시뮬 — 맵툴 BotSimulator(`bs` 모드) + DDA `bot_judge` 대체(같은 코어) | (1) 커버리지 측정으로 이식 범위 확정 (2) PyRandom (3) Rules `bs` 모드(BotSimulator 규칙 전부: stack/craft/링크/얼음/풀/체인/폭탄/커튼/열쇠/개구리/텔레포터/냥이의 도움, V23 parity 항목) (4) 정책: 맵툴 BotType + optimal+parity 강제, v2.4 θ1.0, v2.4 θ1.3 (5) `tilecore bot` CLI = bot_judge 출력 열 동일, `--stop-on-clear` (6) **shadow 2주 + 동일성·속도 판정** | §0-A 표 ①: R2 전 칸 rate·clear_rngSeed·탭 경로 **100% 일치**, 판당 ≥20배 / θ>1 ≥50배 | **13~18일** = 구현 10~14 (커버리지 1, RNG 1, 규칙 4~5, 정책 3~4, CLI·대조 2) + 검증 3~4 (R2 전수 대조·불일치 분류·속도표). shadow 2주는 ② 구현과 겹침 | 정책 이식 범위가 커버리지보다 큼 / 부동소수·정렬 순서 미세 차 | `TILECORE=off`; bot_judge.py 파이썬 경로 그대로 |
| ② 맵툴 solver·autoplay·batch-verify | `tilecore serve` 상주 워커 + `app/core/tilecore_client.py` 어댑터(`simulate_with_profile`, `solve_level` 동일 시그니처), `TILECORE=off/shadow/on`; solve = Judge 탐색 + 맵툴 판정 범주; **shadow 1~2주 + 판정** | §0-A 표 ②: 클리어율 100% 일치, PROVEN 경로 재생 100% 클리어, 지연 ≥20배·노드율 ≥300배; 서버 재시작은 사용자 승인 시 | **8~11일** = 구현 6~8 + 검증 2~3 | 서버 프로세스 수명·동시성(요청 큐), 맵툴 프로필 분기 추가 | `TILECORE=off` (코드 경로 유지) |
| ③ 생성기 막힘 검사·검증 생성·MC/RL/tune | `_quick_deadlock_check`/`_fix_same_type_blocking`/`_simulate_single_bot`/reverse_gen/`sweep_point_task`/pv `_TrackingBot` trace → 워커; make_skill_profile 전 버전(v1~v2.4) 정책; **shadow 2주 + 판정** | §0-A 표 ③: 고정 시드 생성 100건 레벨 JSON 바이트 동일; MC 격자 클리어율 동일(R3); tune/rl_sim 동일; generate ≥10배, MC θ>1 ≥30배 | **13~18일** = 구현 10~14 (생성기 2, 검증 루프 2, 정책 버전 확장 4~6, pv trace 2) + 검증 3~4 | v1/v2/v2.1/v2.3 정책 분기 다수 → 커버리지로 범위 제한, 미이식 조합은 폴백 | 스위치별 개별 off |
| ④ (선택) 게임 원문 모드 | `game` 모드 항목별 전환(4-1), tempo 민감도, Unity 오라클 대조(승인 시) | 항목별 영향 보고서(판정·클리어율 뒤집힘 목록), 사용자 승인 후 기본 모드 전환 (분포 동등 판정 §0-A 3) | 3~5일 (+Unity 작업 별도) | 기존 판정·업로드된 시드와 기준 불일치 → 재판정 범위 결정 필요 | 모드 플래그로 `bs`/`fe-ref` 유지 |

**작업량 합계 [개정]**: ⓪ 3~5 + ① 13~18 + ② 8~11 + ③ 13~18 = **37~52 인일**, ④ 포함 **40~57**. 어제(31~44, ④ 제외 28~39) 대비 검증·shadow 하네스 몫 약 +9~12 인일.
**일정(달력) [추정]**: 착수 = 2026-11-03 DDA 업데이트 이후(⓪ 설계·코드는 그 전부터 가능). 구현·비교 작업은 순차 약 8~11주(주 5일, 1 작업자 기준); 각 단계 shadow 대기(2주/1~2주/2주)는 **다음 단계 구현과 겹침**, 단 ③ 의 shadow 2주는 겹칠 작업이 없어 끝에 붙음 → **전체 약 10~13주**(④ 제외). 단계별 `on` 시점: ① 착수+약 5~6주, ② +약 8~9주, ③ +약 10~13주. 시간 예산형 A*·shadow 측정은 부하에 따라 흔들리므로 CPU 할당(§6) 지키는 조건. 이 달력은 근거 있는 추정이며 측정 아님.

빠른 효과(이식 전, 파이썬만 — 범위 밖이라 제안만): seek/replace 의 봇 판정을 첫 클리어 즉시 중단(PATH_BOT 은 1판이면 충분), `solve_level_task` 의 time_budget 누락(solver.py:374) 수정.

---
## 6. 하드웨어 활용
측정 [실측]: `hw.ncpu 10` (P코어 6 `hw.perflevel0.physicalcpu`, E코어 4), `hw.memsize 34359738368`(32 GB), `vm.swapusage total = 0.00M`(**스왑 없음**), 측정 시점 load avg 36.9/42.2/43.5(코어 수의 ~4배 과부하). 상주 메모리 상위: 안드로이드 에뮬레이터 4.1 GB, FastJudge 판정(다른 세션) 2.9 GB, Unity 2.3 GB, 브라우저 ~1 GB.

권장:
- **CPU**: 전체 계산 작업자 합 ≤ 8(P6+E2), 2코어는 Unity·에뮬레이터·서버용. 세션별 할당을 마더가 관리(지금은 합이 크게 초과 → 측정·판정 시간이 부하에 따라 흔들림, A* 는 시간 예산 판정이라 결과 자체가 바뀔 수 있음).
- C# 은 **1프로세스 다중 스레드**(레벨 데이터·JIT 공유, GC 1개)로. 파이썬 ProcessPool 여러 개 대신 워커 1개(스레드 6) 권장.
- **메모리**(스왑 없음 → 초과 시 압축·강제 종료): 도구 전체 상한 16 GB. A* 판정 작업자당 `--max-mem-mb 1200~2400` × 동시 2 = ≤5 GB(현 실측 2,000만 상태·동시 2 에 4.8~6 GB). 봇·MC 는 판당 상태가 작아(수십 KB~수 MB) 스레드 6 에 <1 GB [추정]. .NET 은 `DOTNET_GCHeapHardLimit`(예 0x180000000=6 GB)로 프로세스 상한을 강제.
- 배치는 `taskpolicy -b`(백그라운드 QoS → E코어 우선)로 돌려 대화형·Unity 응답성 유지. 속도 비교 측정은 부하 낮은 시간대에 동시 1개로.
- [개정] shadow 는 CPU 를 추가로 쓴다 → shadow 중에도 합 ≤ 8 유지. **속도 판정(§0-A 4)은 반드시 shadow 와 분리해, DDA·FastJudge 등 다른 대형 작업이 없는 시간대에 단독 측정**(load avg ≤ 코어 수 확인 후).

---
## 7. 실측·추정 구분 / 한계
- 실측: §1 표의 [실측] 값(기존 산출물 sec 합산 6개 파일군, cProfile 3건, 결정성 2회, MC θ 3점). 모두 고부하(load ~40)에서 측정 — 상대 비중은 유효, 절대 시간은 1.5~2배 부풀었을 수 있음. cProfile 은 함수 호출당 오버헤드로 파이썬 시간을 추가로 부풀림(solver 768 노드는 프로파일러 켠 값).
- 추정: 모든 C# 기대 배수(FastJudge A* 7/17배만 실측). 봇 C# 배수는 FastJudge 노드 처리율(25만/s)과 파이썬 봇 수당 비용(2~4 ms/수) 비교에서 나온 예측이며 C# 봇은 아직 없음.
- 측정 못 함: `/generate/validated`·enhance·autoplay·batch-verify 요청 전체(서버 경로·풀 생성 필요, 재시작 금지), key_relocate(다른 작업 진행 가능성), pv evaluate·tune·rl_sim 실요청. 대신 그 구성 요소(generate·봇 1판·solve·θ점)를 잼.
- 결정성 확인은 2칸 표본뿐. ① 착수 시 R2 전체로 재확인 필요.
- 맵툴 경로·기본값은 정적 읽기(하위 에이전트 보고 포함, 파일:줄 인용) — 실행 확인 아님.

---
## 8. 결정 대기 항목 · 착수 시점 [신설]

**결정 대기**
1. **판정기고속화 3단계(개구리·텔레포터 판정)의 위치** — 선택지 (a) ① 코어(Rules+Rng) 위에서 구현 → 개구리 규칙 이중 구현 방지, 단 3단계가 ① 완료까지 대기 또는 ① 규칙 구현을 먼저 당겨야 함. (b) 지금 판정기고속화 세션에서 독자 구현 → 빠르지만 규칙 2벌, 나중에 코어로 통합 비용. (c) **장기안(선택지로만 기록, 지금 추천 아님)**: 게임 규칙 계산을 **순수 C# 라이브러리로 분리**해 게임(Unity)·도구가 **같은 코드**를 쓴다 → 규칙 드리프트 원천 제거, 단 게임 코드 변경·Unity 빌드/QA 부담이 커서 별도 승인·계획 필요. 현재 계획의 코어는 (c)로 가는 중간 단계로 쓸 수 있게 Rules 를 UnityEngine 비의존으로 유지.
2. 동일성 검정 기준·표본 수(§0-A 3: ±3%p, 판수 ≥300, Bonferroni, χ² p>0.01) 확정.
3. 속도 최소 기준(§0-A 표: ①≥20배/θ>1 ≥50배, ②≥20배·노드율 ≥300배, ③≥10배/θ>1 ≥30배) 확정 — 어제 기대치 [추정] 기반이라 ① 첫 측정 후 조정 가능.
4. 불일치 원인이 "파이썬 버그"일 때 파이썬 정본 유지 vs 수정(§0-A 3).
5. 안정화 기간 길이와 파이썬 제거 여부(§0-A 6).
6. ④ 게임 원문(`game`) 모드 전환 여부(어제 항목 그대로).

**착수 시점 메모**: 2026-11-03 DDA 업데이트 이후 착수 권장 — 오늘 밤은 DDA 판정·교체 탐색이 CPU 를 사용 중(load avg ~40 실측). 단 ⓪ 코어 분리의 **설계·코드 작업**(저장소 골격, 모듈 분리, shadow 하네스 코드 작성)은 CPU 를 거의 안 쓰므로 먼저 가능. 컴파일·바이트 대조 실행·shadow·속도 측정은 DDA 이후(그리고 FastJudge 4단계 동결 후 코드 이동은 해당 세션/마더 승인).

**진행 2026-11-02 (세션 C#빠른도입)**: ② 앞당김 — 맵툴 `solver.solve_level` 에 `TILECORE=off|shadow` 스위치(`app/core/tilecore_shadow.py`, 기본 off = HEAD 와 결과 동일 25/25, `on` 은 아직 shadow 취급) + 표본 30레벨 shadow 불일치 0(same 24·파이썬 UNCERTAIN→C# PATH 6, 고부하 측정이라 속도 판정 아님); ⓪ 골격 `~/tilecore`(FastJudge 1.2 동결 사본 SHA 동일, 4단계 동결 후 재복사 필요) + ① `PyRandom.cs` CPython 비트 일치(89,528줄); 대량 검증 명령은 `~/tilecore/README.md` "DDA 작업 끝난 뒤".

**진행 2026-11-02 (세션 C#1단계봇이식)**: ① 봇 시뮬 `bs` 모드 1차 이식 — `~/tilecore/src/TileCore/Bs`(규칙·정책·θ>1 롤아웃) + `T0`(TileDistributor, 25,000건 일치) + CLI `tilecore bot`, 프로필 optimal_par·v24_1.0·v24_1.3·gen_optimal(+맵툴 BotType 4종); shadow 매 수 대조 1,873판 불일치 0(탭·MT 색인·매 수 후 상태), R2 기록 대조 2,340칸(140,400판) rate·첫 클리어 rngSeed·탭 경로 100% 일치; 미지원 = unlockTile>0&randSeed≠0(cs_shuffle)·auto_collect·V24_DEFAULT 밖 항목·PR≥1.0(상세 `~/tilecore/README.md` ①절). 속도 판정·최적화·맵툴 어댑터는 미착수.

**진행 2026-11-02 저녁 (세션 C#1단계봇이식, 속도·대량 실행)**: 의미 보존 최적화(키 캐시·정수 덮임 캐시·무할당 순회·기믹 스캔 생략 등) 후 고정 릴리스 `~/tilecore/release/v1`(19:29)·`v2`(19:55, cs_shuffle 열쇠 배정 포함); `tilecore dda`(VariantDump 또는 레벨+시드 입력, 게임 DdaMapTransformer 사본, t0 굽기, 다중 스레드, resume, stop-on-clear); 회귀 shadow 4,008판·R2 140,400판 불일치 0; 속도(교대 측정, 부하 11~15 — 단독 아님) 그리디 CPU ≈24×·판 중앙 ≈46~50×, θ1.3 판 중앙 ≈13~14×(기준 50× 미달). 맵툴 어댑터는 초안만(`~/tilecore/adapters/`).

**진행 2026-11-02 밤 (세션 C#1단계봇이식)**: 다중 스레드 둔화 원인 = 경합 아님(4프로세스×1 = 1프로세스×4 총 CPU 동일, 부하·E코어), 할당 −52%·Server GC로 4스레드 벽시간 −28%; `release/v3`(증분 덮임·캐시, 결과 비트 동일, 그리디 CPU v2 대비 −24%·θ1.3 −17%) · `release/v4`(냥이의 도움 auto_collect 이식, 보스 60레벨 shadow 560판 일치). θ>1 50×는 미달 — 배열 상태·되돌리기 재설계 필요(2~3일, `~/tilecore/README.md` 끝).
**진행 2026-11-02 21:06**: `release/v5`(θ>1 롤아웃 상수 개선: Determinize 계획 재사용·사본 COW, 결과 비트 동일, 롤아웃 CPU v2 대비 ≈−26%) — 50×는 증분 수 생성·점수 분해·되돌리기 로그가 필요(3~4일, `~/tilecore/wip/ROLLOUT_REDESIGN.md`).
**속도 판정 2026-11-03 00:30 (load 3.6~6, 유휴 단독 아님·교대 측정)**: v6 1스레드 — 그리디 CPU 26.7×·판 중앙 52×, θ1.3 CPU 58.7×·판 중앙 71× → §0-A ① 기준(그리디 ≥20×, θ>1 ≥50×) 충족(이 조건). 큰 배치 48,960판 1스레드 32 s / 8스레드 8.5 s. 표 `~/tilecore/README.md` 끝.

**진행 2026-11-03 (세션 C#맵툴연결, worktree `~/TileMatchAutoLevel_wt_tilecore` 브랜치 `tilecore-shadow-20261103`, 본 폴더 미반영)**: ①/② 맵툴 봇 시뮬 shadow 연결 — `/api/analyze/autoplay` 1곳(`analyze._run_bot_sim_chunk`·`_run_profiles_parallel`) + 신규 `app/core/tilecore_bot.py`. 스위치 = `TILECORE_BOT`(없으면 `TILECORE`) off|shadow, `on` 은 shadow 취급(미구현). off = 원래 코드 경로(청크 결과 json 바이트 동일·C# 미호출 테스트). shadow = 파이썬 결과 그대로 반환 + `RecordingBotSimulator`(BotSimulator 하위 클래스, 판별 클리어만 기록) → 같은 프로필·rngSeed(seed+i, 파이썬이 실제 돌린 n판)·max_moves 를 `release/v6` `tilecore bot`(mode gen, 요청당 서브프로세스 1개, `--threads 1`)로 **백그라운드 데몬 스레드 1개 + 상한 16 큐**에서 재실행 → `bot_shadow_diff.jsonl`(입력 해시·프로필·판별 클리어 비트열·첫 클리어 rngSeed·클리어율·양쪽 시간·category same/mismatch/cs_unsupported/cs_error/skip_seed_none/dropped_queue_full·unsupported 사유). seed=None 요청은 재현 불가 → `skip_seed_none` 집계만(프론트 autoplay 호출 대부분이 seed 미지정 — 운영 shadow 표본 확보 방법은 결정 대기). v6 에 상주 `serve` 명령이 없어 상주 워커 대신 요청당 CLI(.NET 기동 ≈0.1 s 포함). pytest 신규 28/28, 관련 기존 63/63. 소규모 동일성(부하 load 6~12 하, 속도 판정 아님): 생산 레벨 40 × average/expert/optimal × 20판(조기 종료) = 120줄·1,297판 **불일치 0**, unsupported 0, 파이썬 82.8 s vs C# 벽 12.0 s(기동 포함)·판 계산 합 7.1 s; randSeed 0 변형 10 × novice/casual = 20줄 중 same 18·unsupported 2(t0+randSeed 0). 로그 `claudedocs/tilecore_bot_shadow_20261103/`. 반영 = worktree 3파일(analyze.py·tilecore_bot.py·tests) 본 폴더 복사 → `--reload` 로 서버 자동 재시작(기본 off 라 동작 불변), shadow 켜기는 `TILECORE=shadow` 환경변수로 서버 재시작 필요(승인 시).
