# tilecore_gen_replay 결과 (2026-11-06)
- 하네스: `backend/scripts/tilecore_gen_replay.py --n 300 --procs 3 --set-workaround` (venv: ~/TileMatchAutoLevel/backend/.venv)
- `summary.txt` = 최종 요약, `results.jsonl` = 레벨별 기록, `prev_coldstart_run1/` = 워밍업 없이 돌린 1차(바이트 299/300; 불일치는 아래 ②와 같은 파이썬-파이썬 상태 차)
- 발견 ① `tilecore_client.request()` 의 `json.dumps` 가 set 값(`_pattern_locked_positions`)에서 TypeError → 실제 생성 레벨은 C# 호출이 전부 error→폴백
  (20레벨 중 8레벨 폴백 100%). 하네스 `--set-workaround` 는 C# 요청 직렬화에만 set→list 를 허용(파이썬 경로 무변경).
- 발견 ② randSeed<=0 인 t0 레벨(L≤26 일반 레벨 13개)은 C# 이 unsupported → 파이썬 폴백. 이 파이썬 경로 자체가
  time.time() 시드(TileDistributor)라 호출 끝 RNG 상태가 실행마다 다를 수 있음(결과 JSON 은 동일).
- 하네스 고정 항목: 전역 random/os.urandom/미시드 random.Random()/BotSimulator 시드/PYTHONHASHSEED=0/LevelGenerator._recent_pattern_categories 초기화, 케이스당 버림 워밍업 쌍.
