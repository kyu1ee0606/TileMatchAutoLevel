# 백엔드 자원 점검 (읽기 전용, 2026-11-06)

표기: [실측]=이번 ps/du/find, [정적]=코드 읽기, [추정]. 봇 계산 속도·C# 이행 항목은 제외. 다른 세션의 tilecore_sweep_parity(PID 7091 + 워커 4 + dotnet 7126)는 측정에서 제외.

## 요약
- 가장 큰 낭비는 (1) 디스크: backend/data 3.6GB 중 production 1.6G(배치 440개×~5MB, 최대 9.3MB)·pv_sandbox 1.5G(pv_20261002_live3/dda_sets 1.2G)·dda_seeds 412M — 정리 정책 없음. (2) 풀 5개 중복·합계 상한 30 워커(코어 10). (3) 저장 PUT 마다 배치 전체 json 읽기 2회(+전체 쓰기). CPU·메모리는 유휴 시 거의 0.
- 로그 증가·전역 캐시 누수는 문제 없음(실측 /tmp/uvicorn_maptool_20261103.log 39KB, `_recent_pattern_categories` 길이 상한 있음).

## 실측
- 서버: reloader PID 95448(3일 7시간 가동, CPU 누적 2:05, 유휴 0%) → 서버 PID 29678(1시간 전 리로드) + 풀 워커 22개 상주, 워커 합계 RSS 218MB(개당 ~9MB), 유휴 CPU 0%. 워커는 유휴에도 정리되지 않음.
- 현재 실행 중인 서버는 `--reload` 만 있고 `--reload-dir app`·WATCHFILES_FORCE_POLLING 없음(ps eww 에 환경변수 없음) → dev-watch.sh 로 띄운 인스턴스가 아님. 폴링 비용은 이번에 못 쟀다.
- 감시 대상 파일 수: backend/data 46,502 / venv 2,870 / app/storage 7,889(app 전체 8,048 중 98%) / tests 267 / scripts 300.
- 로그: /tmp/uvicorn.log 없음(실제 로그는 /tmp/uvicorn_maptool_20261103.log 39KB, /tmp/vite.log 없음). 무한 증가 로그 미발견. ~/tilecore/shadow 36KB(TILECORE 환경변수 미설정=shadow off).
- 디스크(backend/data 3.6G): production 1.6G(440 파일, 5.4~9.3MB) / pv_sandbox 1.5G(live3 1.3G: dda_sets 1.2G) / dda_seeds 412M(19개 디렉터리, dryrun_v2* 62MB 3~4개) / dda_seed_ledger 45M(sessions 38M) / hurdle_rec 4.2M / live_backup 2.5M. backend/app/storage 57M(level_sets 241 디렉터리 2026-01-08 생성분 + local_levels 2467 파일, gitignore). venv 62M, analysis_venv(루트) 283M, frontend 300M.
- 참고: du 가 3.6G/2.0G 로 다르게 나온 건 du 중 파일 변화(다른 세션 작업) 때문으로 보임.

## 우선순위
| # | 항목 | 위치 | 근거 | 개선 | 난이도 | 위험 |
|---|---|---|---|---|---|---|
| 1 | 정적 대용량 데이터 무정리 | data/production(1.6G), data/pv_sandbox(1.5G), data/dda_seeds(412M) | [실측] du | 오래된 실험 디렉터리 압축(.gz)·이동. production 은 배치 파일 gzip 저장 시 5배 이상 감소 [추정] | 쉬움(수동)/중간(코드) | production 은 gboost·프론트가 읽음 → 코드 변경 시 신중 |
| 2 | 저장 PUT 시 배치 전체 파싱 2~3회 | production_store.py:439-448(`_current_version` 가 5MB 전체 json.load 후 version 만 사용), :493(partial 병합 시 전체 load), :552 전체 dump | [정적] 5.5MB×(read+read+write)/PUT | version 을 _index.json 에서 읽기(이미 존재) 또는 파일 앞부분에 version 선기록; 병합 시 로드 1회로 | 쉬움 | 낮음(버전 일관성 테스트 필요) |
| 3 | 프로세스 풀 5개 중복 | generate.py:41(bot 3), :67(gen cpu-2=8), :82(autoplay 6), rl_sim.py:49(rl 8), bot_simulator.py:382(bot_sim 5) + main.py:100 startup 가 rl·gen 즉시 워밍업 | [실측] 상주 워커 22개 [정적] 최대 합계 30 > 코어 10 | 풀 하나로 통합(작업 종류별 세마포어) 또는 유휴 N분 뒤 shutdown; 워밍업은 gen 만 | 중간 | 중간: 풀 분리는 "검증이 생성을 막지 않게" 의도(generate.py:79 주석) |
| 4 | async def 안에서 무거운 동기 계산 | analyze.py: turtle_bases_measure:1945, debug_level_template_measure:3210(analyze_autoplay 직접 호출), generate_from_template:3063, generate_from_boss_template:2431, debug_test_level:3995, analyze_level:303 | [정적] async 핸들러가 이벤트 루프에서 직접 실행 → 실행 중 모든 요청(health 포함) 정지 | `def` 로 바꿔 스레드풀에서 실행 (한 줄 변경) | 쉬움 | 낮음(내부 await 유무 확인) |
| 5 | 템플릿/패턴 JSON 요청마다 재로드 | analyze.py:2740 `_load_level_templates`(1.5MB, 12곳 호출, 캐시 없음) | [정적] [추정] 요청당 ~10ms | mtime 캐시(generator.py:678 의 패턴 캐시와 동일 방식) | 쉬움 | 낮음(저장 후 캐시 무효화 필요) |
| 6 | 리로드 감시 범위 | dev-watch.sh `--reload-dir app` + 폴링: app/storage 7,889 파일(98%)을 300ms 마다 stat | [정적] 스크립트 주석 "코어 1개의 약 14%"; [실측] 실행 중 서버는 폴링 아님 | `--reload-exclude 'app/storage/*'` 추가 시 감시 파일 ~160개로 감소 [추정]. 현재 인스턴스처럼 --reload-dir 없이 띄우면 backend/data 46,502 파일이 감시 대상 | 쉬움 | 낮음 |
| 7 | app/storage 정리 | app/storage/level_sets 241 디렉터리(2026-01), local_levels 2467 파일 | [실측] | 사용 여부 확인 후 app 밖으로 이동/삭제 | 쉬움 | 사용 중인지 미확인 |
| 8 | 섀도 서브프로세스 | solver.py:213-220, tilecore_shadow.py:217 `subprocess.run` 동기, 호출마다 dotnet 기동 | [정적] 현재 TILECORE 미설정이라 비용 0 | shadow 켤 때만 문제. 켜면 상주 프로세스 방식 | 중간 | 지금은 영향 없음 |

## 낮은 위험 / 신중
- 바로 가능: #2(버전 조회), #4(async→def), #5(mtime 캐시), #6(exclude), #1 의 수동 압축·이동(sandbox/dda_seeds 만).
- 신중: #3(풀 통합 — 동시 처리량 동작 변화), #1 production 포맷 변경(gboost/프론트 연동), #7(사용처 확인).

## 문제 아님(확인함)
- `LevelGenerator._recent_pattern_categories`(generator.py:654): 3235-3236 에서 `_PATTERN_HISTORY_SIZE` 로 잘라 길이 상한 있음. 단 클래스 변수라 프로세스(워커)별로 호출 간 유지돼 요청 간 결과 의존이 생길 수 있음(자원 문제 아님, 재현성 문제).
- production_store 목록 API: 인덱스 캐시(mtime,size)로 파일 안 엶(list_batches:580). 라우트가 `def` 라 스레드풀.
- deepcopy: generator.py 10, analyze.py 9 등 총 40회 미만 — 핫패스 여부 미확인(프로파일 안 함).
- 로그: logger.warning generator.py 68개 있으나 실제 로그 파일 39KB. 레벨당 다발 여부는 대량 생성 중 실측 못 함.
- 전역 dict: live_backup._jobs(core/live_backup.py:527), pv_play 캐시 2종, gboost._image_cache 는 정리 코드 없음(`_jobs.pop` 미발견) — 크기 작을 것으로 보이나 미측정.

## 미확인
- 폴링 reloader 실제 CPU(현재 서버가 폴링 아님), 대량 생성 중 워커 RSS·로그 증가, deepcopy 핫패스, pytest/수동 스크립트 산출물(backend/test_results 9.9M, tests 7.9M)의 중요도, data 하위 각 디렉터리의 현재 사용 여부.
