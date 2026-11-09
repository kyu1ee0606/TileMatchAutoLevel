# 3단계 shadow 실행 런북 (2026-11-09)

계획서 `PLAN_CSHARP_BATCH_LIVE_20261106.md` §3단계(187~203줄) 실행 절차. **이 문서는 준비물이다 — 서버 재시작·실배치는 사용자 승인 후에만.**
코드 위치: 브랜치 `feature/tilecore-live` (worktree `~/TileMatchAutoLevel/.claude/worktrees/tclive`). [사실]=직접 확인, [추정]=계산·추론.

## 0. 현재 상태 요약
- push 완료: `feature/pv-seed-variants` 736bbc9..1c5e31f (fast-forward, 17커밋). `feature/tilecore-live` 는 push 안 함.
- `feature/tilecore-live` = pv-seed-variants(1c5e31f) + tilecore 연결 커밋 → **본 폴더에 `git merge --ff-only feature/tilecore-live` 로 반영 가능**(1c5e31f 가 조상) [사실: git log].
- 2-C 전체(1,500레벨, 점 12,000): 불일치 **0**, 오류 0, unsupported 760점(6.3%) + gen_state 95/1,500(6.3%) — 사유 전부 "t0 tile with randSeed<=0" [사실: `claudedocs/tilecore_sweep_parity_20261106/summary.json`]. → §5. **5% 기준에 걸림.**
- 8001 격리 연기 시험 통과(§2).

## 1. 서버 재시작 절차 (8000)
### 1-1. 지금 떠 있는 서버 [사실: `ps`/`lsof`, 2026-11-09 10:20]
```
PID 95448 (ppid=1, 11-03 10:54 시작) = uvicorn reloader 부모
  /Users/casualdev/TileMatchAutoLevel/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  cwd = /Users/casualdev/TileMatchAutoLevel/backend    stdout/stderr = /private/tmp/uvicorn_maptool_20261103.log
PID 84978 (ppid=95448) = 실제 서비스 프로세스(리로드로 재생성), 하위 풀 워커 22개
```
- `dev-watch.sh`/`run.sh` 감시 프로세스는 **없다**(부모가 launchd 직속) → 죽어도 자동 재기동되지 않는다.
- 이 서버는 `--reload-dir` 없이 떠 있다. 아래 새 명령은 `scripts/dev-watch.sh:21` 과 같은 옵션(`--reload-dir app`, 폴링)을 쓴다.

### 1-2. 환경변수는 어떻게 적용되나 (`--reload`)
- `--reload` 는 부모(reloader)가 자식을 `multiprocessing spawn` 으로 만들고, 자식과 그 풀 워커는 **부모 환경을 상속**한다. 코드 저장에 의한 자동 재로드도 부모 환경을 그대로 쓴다.
- 그러므로 **환경변수를 바꾸려면 부모(95448)를 새 환경으로 다시 띄워야 한다.** 파일 저장만으로는 안 바뀐다. 현재 부모 환경에 `TILECORE*` 변수는 없다 [사실: `ps eww`].
- off 로 되돌릴 때도 부모를 환경변수 없이 다시 띄운다.

### 1-3. 코드 반영 + shadow 켜기 (한 번에 — 배치가 돌지 않을 때만)
```bash
# (a) 정지: 부모를 종료하면 자식·풀 워커도 종료
kill -INT 95448; sleep 5; lsof -nP -iTCP:8000 -sTCP:LISTEN     # 출력이 없어야 함

# (b) 코드 반영(본 폴더, pv-seed-variants 체크아웃 상태)
cd ~/TileMatchAutoLevel && git status --short | head          # 미커밋 변경 확인
git merge --ff-only feature/tilecore-live

# (c) shadow 기동
mkdir -p ~/tilecore/shadow
cd ~/TileMatchAutoLevel/backend && \
TILECORE_GEN=shadow TILECORE_SWEEP=shadow \
TILECORE_SERVE_DLL=$HOME/tilecore/release/v7/bin/tilecore.dll \
TILECORE_SERVE_SHA=18a80934e83e67b9e5f235c1146d0eaf137e3d2421d6b5b172fbf97883a2f407 \
TILECORE_SERVE_THREADS_GEN=1 TILECORE_SERVE_THREADS_SWEEP=4 TILECORE_TIMEOUT_S=10 \
TILECORE_SHADOW_DIR=$HOME/tilecore/shadow \
WATCHFILES_FORCE_POLLING=true nohup venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --reload --reload-dir app --reload-exclude 'app/storage/*' >> /tmp/uvicorn_maptool_shadow_20261109.log 2>&1 &
disown
sleep 8; curl -s localhost:8000/health
```
- `TILECORE_SERVE_SHA` = `release/v7/SHA256SUMS` 의 tilecore.dll 해시 [사실]. 다르면 C# 비활성(전부 파이썬, 경고 로그).
- 공용 `TILECORE` 변수는 쓰지 않는다(solver FastJudge shadow 동시 활성 방지, 계획서 F14).
- 확인: 생성 호출 후 `ps -eo pid,rss,command | grep "tilecore.dll serve"` 로 serve 프로세스가 보여야 하고, `~/tilecore/shadow/gen_shadow_diff.jsonl` 이 늘어나야 한다.

### 1-4. off 원복
```bash
kill -INT $(lsof -nP -iTCP:8000 -sTCP:LISTEN -t | head -1)    # 8000 을 잡은 프로세스(자식) → 부모가 같이 정리되는지 아래로 확인
ps -eo pid,ppid,command | grep "uvicorn app.main" | grep -v grep   # 남아 있으면 ppid=1 인 부모를 kill -INT
sleep 5; pgrep -fl "tilecore.dll serve"                        # 남은 serve 가 있으면 pkill -f "tilecore.dll serve"
cd ~/TileMatchAutoLevel/backend && \
WATCHFILES_FORCE_POLLING=true nohup venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --reload --reload-dir app --reload-exclude 'app/storage/*' >> /tmp/uvicorn_maptool_off_20261109.log 2>&1 &
disown
```
- 환경변수가 없으면 자동 off(기본값). 코드는 그대로 두어도 된다 — off 는 원래 함수 호출과 동일(테스트로 확인).

## 2. 격리 연기 시험 결과 (포트 8001, 2026-11-09 10:16, 시험 후 종료 확인)
조건: worktree 코드, `TILECORE_GEN=shadow TILECORE_SWEEP=shadow`, `TILECORE_SHADOW_DIR=/tmp/shadow8001`, release/v7 + sha 지정, 127.0.0.1:8001. 8000 은 건드리지 않음. 데이터 쓰기 API 호출 없음.
| 항목 | 결과 |
|---|---|
| `/api/generate` 5회(난이도 0.3/0.5/0.7/0.9/0.6) | 전부 200. 막힘검사 shadow 기록 8줄: same 8, mismatch 0, unsupported 0, error 0, serialize_error 0 |
| `/api/rl-sim/level` 1회(rollouts 16, θ 8점) | 200. sweep shadow 8줄: same 8 |
| C# serve 프로세스 수 | 6개 = gen 풀 워커 5개(각 `--threads 1`) + 서버 본 프로세스 1개(`--threads 4`, 측정용) |
| serve RSS | 56~83 MB/개, 합계 ≈375 MB (계획 추정 160 MB/개보다 작음) |
| set 직렬화 | 실제 serve 로 `_pattern_locked_positions={(1,2),(0,1)}` 든 레벨 호출 → `cs_ok=1, error=0, serialize_error=0` |
| 한 호출 시간 | py 0.06~0.41 s / C# 0.008~0.39 s (0.39 s 는 serve 기동 포함) |
| 종료 | SIGINT 후 8001 listen 0, serve 0개, "Application shutdown complete" |
한계: 호출 수가 8+8 로 작아 기믹별 층화는 안 됐다(본 실행의 목적). 이 시험 로그에는 `gim` 태그가 없다(태그 추가 전 코드).

## 3. CPU·메모리 배정 (코어 10개, 메모리 32 GB [사실: sysctl])
풀 크기는 코드 고정값이라 환경변수로 못 바꾼다 [사실]: gen 풀 `generate.py:67` = min(8, cpu−2) = **8**, autoplay 풀 `:82` = **6**, 봇 풀 `:52` = 3, rl 풀 `rl_sim.py:50` = min(10, cpu−2) = **8**. 풀은 lazy 생성.
shadow 중 한 워커: 파이썬 계산 → 끝난 뒤 같은 워커가 C# 재생을 기다림(순차) → **워커당 동시 활성 코어 ≈1** [사실: `simulate` shadow 분기와 `_shadow_sweep` 이 파이썬 완료 후 C# 호출].
| 국면 | 동시 계산 | 코어 |
|---|---|---|
| 생성 | gen 풀 8 워커(파이썬) | **8** |
| 측정(순차검증 RL) | rl 풀 8(파이썬) → 끝난 뒤 serve 4스레드 재생 | 8 → 4 (겹치지 않음) |
| 재생성 + 측정 동시 | gen 8 + rl 8 | **16 → 10코어 초과** |
**8코어 상한을 지키려면**
1. (추천) 국면을 겹치지 않게: shadow 중에는 생성 / 검증을 한 가지씩만(순차검증 중 재생성 동시 실행 금지). 다른 계산 세션 중지.
2. 풀 크기 축소는 코드 수정 필요(`GEN_POOL_WORKERS`, `rl_sim.MAX_WORKERS` 환경변수화, 각 1줄) — 이번 범위 밖, 승인 시 별도.
3. shadow 중 시간은 파이썬 단독 대비 +5~15% 정도 [추정: 8001 시험에서 C#/파이썬 시간 비 0.03~1.0, 호출이 짧아 편차 큼].
메모리: serve 최대 9개 × ~80 MB ≈ 0.7 GB. 로그: 생성 호출당 ~300 B → 배치 1개 ≈24,500건 ≈7 MB, sweep ≈1,530×8 ≈4 MB.

## 4. 집계 스크립트
`backend/scripts/tilecore_shadow_report.py` (커밋됨; 본 폴더 반영 후 사용):
```bash
cd ~/TileMatchAutoLevel/backend && venv/bin/python scripts/tilecore_shadow_report.py --dir ~/tilecore/shadow --since 2026-11-09T11:00 --json /tmp/shadow_report.json
```
- 경로별(gen / sweep): 전체·same·mismatch·cs_unsupported·timeout·cs_error·serialize_error, 비교 불가 %, 기믹별 층화표(`gim` 태그: ice/chain/grass/bomb/stack/craft/t0/rs0…), 첫 불일치 사례.
- **PASS = 불일치 0 AND 비교 불가 <5% AND 호출 수 ≥1,000**(`--min-calls`). 기믹별 30호출 미만은 "thin" 표시만(실패 아님). 종료 코드 0=PASS, 2=FAIL, 3=자료 없음.
- 비교 불가 중 `rs0`(randSeed≤0) 비중을 따로 보여 §5 사유를 분리한다.
- 검증: 8001 시험 로그로 실행해 PASS 출력 확인(`--min-calls 5`). 기믹 태그 단위 테스트는 `test_gimmick_tags_and_shadow_log_field`.

## 5. unsupported 6.3% (5% 기준 초과) — 원인과 선택지
**원인 [사실, 코드 확인]**: `zWellRandom.seed()` 가 seed==0 이면 `int(time.time())` 로 시드(bot_simulator.py:46-47), `TileDistributor` 호출부는 `rand_seed if rand_seed > 0 else 0`(:311). 레벨 `randSeed` 가 없거나 0 이고 t0 가 있으면 분배가 **호출 시각마다 달라진다** → 파이썬끼리도 재현 불가. C# 은 `UnsupportedException` 으로 거절(`BotSim.Init.cs:156,262`). 2-C 의 95개 레벨 중 25개는 최상위 t0 칸, 70개는 stack/craft 내부 t0(`randSeed` 키 없음) [사실: results.jsonl 집계]. 이 레벨의 파이썬 sweep 시간 비중 = 1,388 s / 26,970 s = **5.1%**.
**(a) 호출 직전에 시드 고정 사본 만들기** — `randSeed<=0` 이고 t0 가 있는 레벨이면 `dict(level, randSeed=int(time.time())&0xFFFFFFFF)` 사본을 C# 에 준다(shadow 에서는 파이썬 비교 실행에도 같은 사본).
- 의미 보존: 파이썬 원래 동작이 "호출 시각 기준 시드"라 분포가 같고 같은 초의 호출이 같은 분포를 공유하는 성질도 유지. `zWellRandom` 은 `self._rng` 와 별개 객체라 RNG 소비 변화 없음 [코드 확인]. off 경로는 변경 없음.
- 실험 [사실]: 2-C 의 unsupported 레벨 중 가벼운 8개에 고정 시드 사본을 줬더니 **θ 점 64/64 일치 + gen_state 8/8 일치**(판 단위·끝 RNG 상태 포함). 8개 표본이라 전체 95개 보장은 아님.
- 변경 위치: `tilecore_client.py` 의 `_cs_call` 앞(simulate/sweep 공통) 약 20줄 + 테스트. 호출처 수정 불필요. 작업량 ≈0.3~0.5 인일 [추정].
- 위험: shadow 에서 "서비스 결과 = 원래 파이썬" 이 "시드를 호출 시점에 고정한 파이썬" 이 된다(통계적 동일, 바이트 동일은 아님 — 원래도 비결정). 서비스 결과는 원본 레벨로 계산하고 비교용 파이썬을 한 번 더 돌리는 변형도 가능(시간 증가).
**(b) 분모 제외 + 기준 조정** — 파이썬끼리도 비교 불가이므로 분모에서 빼고 "비교 가능 중 불일치 0 + rs0 비율 별도 보고" 로 기준 변경. 코드 변경 없음(리포트가 rs0 분리 표시). 단점: 기준이 사후에 느슨해짐, 이 레벨들은 on 에서도 파이썬이라 속도 이득 감소.
**(c) 폴백 유지** — 속도 [추정, 2-C 실측]: sweep 은 파이썬 시간의 5.1% 가 남아 전체 속도 상한 ≈ 1/(0.051 + 0.949/68) ≈ **15배**(C# 단독 68배 → 15배), D6 "측정 ≥10×" 간신히 충족. 생성 막힘검사는 호출의 6.3% 가 파이썬이라 상한 ≈ 10배 이하.
**추천: (a)**. 변경이 한 파일·소규모이고 의미 보존이 코드·실험으로 확인됐으며 5% 기준을 건드리지 않고 비교 불가를 낮출 수 있다. **shadow 실행 전에** 적용하면 rs0 레벨도 비교 대상이 된다. (a) 전에 shadow 를 먼저 돌려야 하면 (b) 로 판정한다.

## 6. 사용자가 할 일 (프로덕션 대시보드, 탭은 계속 열어 둘 것)
탭 라벨은 코드에서 확인 [사실: ProductionDashboard/index.tsx:2536-2544 `개요/생성/검증/테스트/…`]. 버튼 문구는 코드에서 정확히 확인하지 못했다 — 첫 실행 때 화면과 대조해 주세요.
1. §1-3 으로 shadow 기동(마더/사용자 승인 후). 절전 해제: `caffeinate -dis`(대시보드 안내문, index.tsx:3091).
2. 대시보드 **생성** 탭에서 §7 후보 중 하나로 생성 시작(구간 생성 기능은 index.tsx:1157 `levelRange`). 진행은 같은 탭에서 확인.
3. 생성이 끝나면 **검증** 탭에서 "순차검증" 실행. 생성과 겹쳐 돌리지 않는다(§3).
4. 30분마다 `tilecore_shadow_report.py` 실행 → 불일치 0·비교 불가% 확인. 불일치가 보이면 중단하고 보고.
5. 종료 후 리포트 PASS/FAIL 판정, 서버를 §1-4 로 off 원복(on 전환은 별도 승인).
탭을 닫거나 새로고침하면 생성 진행 상태(비영속)가 초기화될 수 있다(index.tsx:3396 주석) — 열어 둔다.

## 7. 배치 후보 제안
| 후보 | 내용 | 예상 시간 | 장단 |
|---|---|---|---|
| A (추천 1단계) | 구간 생성 100레벨(`levelRange`) + 그 100레벨 순차검증 1라운드 | 전체 배치 ≈4.5 h 의 약 6.5% → 20~30분 [추정] | 빨리 방향을 본다. 호출이 적어 기믹별 30호출 미달 가능 |
| B | 확장 30레벨(`handleExtendBatch`) + RL 1라운드 | 10분 안팎 [추정] | 연결 확인용, 판정용으로는 부족 |
| C | 배치 1개 전체(1,500+30) | 파이썬 ≈4.5 h 이상 [계획서] | 계획서 기본 종료 기준(생성 ≈24,500, 측정 ≥1,530). 8코어 점유 |
**추천 순서**: A → 리포트 확인(불일치 0, 비교 불가 구성) → 이상 없으면 C(또는 경로별 비교 성공 ≥1,000호출 + 기믹별 ≥30 충족 시 종료).

## 8. 사용자가 정할 것
1. §5: (a) 시드 고정 사본(추천) / (b) 분모 제외·기준 조정 / (c) 폴백 유지.
2. §3: 겹침 방지 운영(추천) vs 풀 크기 환경변수화(코드 수정 승인).
3. §7: 첫 배치 후보(A 추천 → C).
4. 서버 재시작 시점(§1-3, 배치 미실행 시점) — 승인 필요.
5. `ff-only` 로 본 폴더에 `feature/tilecore-live` 반영(반영 즉시 `--reload` 재시작 발생) 허용 여부.
6. 이 문서는 격리 규칙 때문에 worktree 에만 있다 — 본 폴더 `claudedocs/` 로 복사는 마더가 수행.
