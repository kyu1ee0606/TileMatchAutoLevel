# 레벨 난도 개인화 (시드 변형) — 인덱스

> 기록 2026-10-02 · 브랜치 `feature/pv-seed-variants` · **문서 전용 인덱스**(코드·데이터 변경 없음)
> 게임 위키 노드(클라 관점): `/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_LEVEL_DIFFICULTY_PERSONALIZATION.md`
> 모든 수치 W는 **봇 성공률(레벨 안 상대 지표)**이다. 사람 클리어율이 아니다.

## 1. 목적
- **과금이 아니라 플레이 능력에 따라** 레벨 난도를 개인화한다.
- 에디터가 레벨마다 시드 후보를 봇 시뮬로 평가·검증해 **기준 1 + 쉬움 2 + 어려움 2** 시드를 고른다.
- 클라는 평가 계산을 하지 않는다. 검증된 후보 중에서 **판 시작 전에만** 하나를 선택한다.
- 맵은 32레벨부터 t0(빈 종류)로 바꾸고, 종류는 클라 `ShuffleEmptyTiles`가 선택된 시드로 배정한다.

## 2. 현재 상태 (2026-10-02 저녁)

| 단계 | 상태 | 핵심 결과 |
|---|---|---|
| P0 재현성 | G1·G2·G4·G5 통과 / **G3(Unity 실경로 덤프) 사용자 승인 대기** | Python 포트 = dotnet으로 실행한 클라 원본 C# 배정(distVer `cs:191858cc9c06`, "dotnet 기준 잠정") |
| P1 파일럿 (20레벨) | 완료 | 봇 스킬 비단조 결함, 후반 레벨 바닥 효과, t0화 시 난도 상승 위험 확인 |
| P1 재측정 v2 (30레벨) | 완료 | 양방향 5시드 **19/30** (`selection_v2.json`) |
| v3 종류 수 ±1 | 완료 | strict 19/30(v2와 시드 동일), **극단 레벨만 relaxed 22/30**. relaxed는 기준−원맵 차이 ≤0.065 (`selection_v3.json`) |
| 독립 검증 (07) | v2 19레벨 + v3 relaxed 9레벨 완료 | 재현성 높음(서열 18/19, 축소율 중앙 1.00, 비트 일치 95/95·45/45, 해법 확인 전부). **바깥 칸(e2·h2)은 견고, 안쪽 칸(특히 h1)은 스킬 민감.** relaxed h2 5레벨은 봇이 거의 못 깸 |
| v4 재선별 | **진행 중**(시드계획전문가) | h2 하한, 바깥 칸 견고 선별, 안쪽 칸 실패 시 3단계(b\|e2\|h2). 보고 09 예정 |
| 수동 플레이 UI | 구현됨(미커밋) | 프로덕션 탭 "시드 변형 플레이". 블라인드 플레이, 결과 기록 |
| P2 확대 (546레벨) | 미착수 | v4 결과·봇 결함 수정 여부 확정 후 진행 |
| 클라 구현 | 미착수 | 명세 초안은 게임 위키 노드 §4 |

## 3. 문서 지도
| 문서 | 내용 |
|---|---|
| [00_plan.md](./00_plan.md) | 최초 조사·계획: 대안 비교, 위험, 에디터↔클라 재현성 쟁점 |
| [01_client_findings.md](./01_client_findings.md) | 클라 조사: `ShuffleEmptyTiles`·`DistributeTiles`·zWellRandom, 레벨 데이터 빌드 내장, 샤드 형식 |
| [02_editor_pipeline_findings.md](./02_editor_pipeline_findings.md) | 에디터 생성→GB 변환→배포 파이프라인, bakeFullBoard 재굽기 위험, 키 순서 |
| [03_solver_bot_findings.md](./03_solver_bot_findings.md) | 솔버·봇 신뢰성: 결정성, 기믹별 한계, CRN, 비용 |
| [04_seed_variant_plan.md](./04_seed_variant_plan.md) | 확정 실행 계획: t0화 규칙, 비트 일치, 평가, 선별, A안 배포 형식, 게이트 |
| [05_p0_report.md](./05_p0_report.md) | P0 보고: 포트, dotnet 골든, 샤드 전수 스캔, 게이트 결과 |
| [06_p1_pilot_report.md](./06_p1_pilot_report.md) | P1 파일럿과 v2 재측정: 스킬 골짜기 결함, 적응형 θ, 비대칭 tier, 사전필터 미채택 |
| [07_seed_verification_report.md](./07_seed_verification_report.md) | 독립 검증(v2·v3 relaxed): 재현성, θ/봇 일반화, 내부 서열, 스킬 민감 지표, 개선 제안 |
| [08_utc_flex_report.md](./08_utc_flex_report.md) | v3 종류 수 ±1(strict/relaxed), seed@utc 토큰, 눈치 지표, 견고 선별 사후 시뮬 |
| 09 (작성 중) | v4 재선별 보고(시드계획전문가) |
| [p0_scan_result.md](./p0_scan_result.md) | P0 샤드 스캔 원자료 요약 |
| [22_af_test_retest.md](./22_af_test_retest.md) | AF 클리어율 test-retest(시간분할/유저분할): 반-반 MAE·ρ, 전체표본 노이즈 바닥, 드리프트 성분, 검증 게이트 기준 판정 |
| [23_residual_retrain_v23.md](./23_residual_retrain_v23.md) | 잔차 보정 모델(E1+CQR) v2.3 봇 입력 재학습: v2.1과 동률(MAE 0.067·ρ 0.743), 검증 게이트 MAE·포함률 합격 / ρ·tolAF·chain·grass 불합격, novelty 집계 버그 수정 |
| [24_live_pilot_design.md](./24_live_pilot_design.md) | 시드 변형 라이브 파일럿 설계(실행 없음): 구간별 트래픽·검정력, 레벨당 n=100/군이면 20~30레벨 풀링 회귀로 봇Δ→유저Δ 기울기 추정 가능, 배정안 3개 비교(IMPL_SPEC 사다리와 충돌 명시), 게임팀 요청 목록 |
| [25_natural_experiment_map_change.md](./25_natural_experiment_map_change.md) | 기존 AF 자연실험(앱버전별 맵 다른 L1~31 20레벨): 부호일치 80%, 봇Δ→유저Δ 환산 기울기 0.155[0.031~0.280] — 방향은 전달되나 크게 압축, 타일만 변경 사례는 L1 천장뿐이라 시드 변형 외삽엔 제한적 |
| [26_bot_v24.md](./26_bot_v24.md) | 봇 v2.4: unknown 정보 누수 감사(실누수 1곳·죽은 코드·노출 unknown 가점 오류 수정), 텔레포트·개구리 이동 후 선택 확인(수정 없음), 냥이 savvy/naive(p_savvy 식별 불가), 덮인 스택 top 터치 가능·독 7칸 확인, 커튼 기억 모델(식별 불가), 행동감사 후속(bomb β=0·냥이 스택 속 수집·stack_early·covered_info·bomb_impulse·key_first 채택), 최종 E1 MAE 0.063·ρ 0.769·적중 0.712, 기믹별 v2.3→v2.4 표. §11 최종 검증(2026-10-16): 기본값 = 규칙 정합 6건만(행동 항목 전부 꺼짐) — 1차 목표 ft_any 에서 v2.4 어느 조합도 v2.3 과 구별 안 됨, 행동 항목은 사전 기준상 보류 |
| [27_human_vs_bot_behavior_audit.md](./27_human_vs_bot_behavior_audit.md) | 기믹별 사람 행동 vs 봇 v2.4 판단 감사(코드 수정 없음): 통제 회귀상 행동 잔차는 stack −0.13·grass +0.08 뿐, teleporter·bomb 은 공존·θ 몫. 우선 제안 = 스택 조기 개방, 독 감점 임계를 잠기지 않은 칸 기준으로, bomb β 적합, 냥이 진단. 기획 질문 15 |
| [28_bot_v1_vs_v2_discrimination.md](./28_bot_v1_vs_v2_discrimination.md) | 봇 v1 vs v2.3 판별(라이브 데이터 가벼운 체크): 자연실험 기울기·불일치135 집중특징(`eff_unknown`="가려진 타일" 기믹, v2.4가 정보정합 수정)·그 특징군 라이브 예측력 모두 v2.3 소폭 우위지만 부트스트랩 CI는 0 포함 — 근거 약함. §6: 구버전(1.0.146~160) 자연실험 확장 시도 — L32+ 맵은 1.0.148~162 전체가 완전 동일(교체 1회뿐), 판별력 못 늘림 |
| [29_pilot_handoff.md](./29_pilot_handoff.md) | 라이브 파일럿(B v3, 21레벨) 게임팀 인계: 레벨·토큰 표, 해시(CUID+level)%2 배정, `pilot_arm` 파라미터, 4주·2주차 점검, 가드레일·중단 절차, 사다리 비중첩, 체크리스트 + 내보내기 검증·사전 등록(`pilot_export/`)·`pilot_eval.py` |
| [30_af_player_skill_distribution.md](./30_af_player_skill_distribution.md) | AF 실제 유저 실력(θ) 분포(Rasch, 봇 매핑 전 사전 조사, 적용 없음): 단봉+우측꼬리(상위 θ는 준분리로 과신 주의), 구간별 생존편향 뚜렷(1-31 θ0.52→1001-1500 θ5.25), 보조지표 중 플레이시간·tiles_left만 유효, 앞/뒤 절반 재추정 순위상관 0.78 |
| [31_target_clear_rate_design.md](./31_target_clear_rate_design.md) | 목표 실유저 클리어율 → 생성·검증·선별 설계(문서만): 지표 1안 = 첫 시도 클리어율(도움 포함, no_end 제외, 재현 MAE 2.1%p·드리프트 최소, 천장 주의) + 대안 mid/LB, 유저 구간 차이 < 재현 오차, E1 목표 열 교체 재학습(ρ 0.739 동률), 합격/불합격/근거 부족 판정·API·UI 초안, 410레벨 선별 재현, 파일럿 29 하니스 재사용 2차 검증, 구현 17~25인일·결정 17건(D17 신규). 개정(세 번째): 현행 `predicted_clear_rate` 판정 경로 = 교체 대상, 배치 레벨 번호 필수 입력, 학습 맵 = 라이브 샤드, 게임 표시 난이도(xDifficulty) 연동은 **트랙 B로 분리해 보류**(일괄 갱신 안 함), 초기 연동은 **새 예측 병행 표시**(판정은 기존 유지, D17), 같은 목표(⑤)·같은 379레벨·같은 K-fold로 (a)원값/(b)재보정/(c)봇없음/(d)E1 재비교(ρ는 (d)만 유의미, §1-5) + ⑤ 기준 고정 확률 폭(±5/±10%p)·logit 폭 선별 재현(천장 구간 분리, §4-4, 기존 라이브 레벨 재현일 뿐 신규 맵 보장 아님) — 재현 스크립트 `backend/scripts/target_metric_eval.py`
| [32_resume_handoff_20261016.md](./32_resume_handoff_20261016.md) | 맥 재부팅 인계(문서만): 최상위 목표·채택 기준 재확인, 확정 기준선(§1-5 수치), 진행 중 작업(봇 v2.4·DDA v2.4 측정 범위·라이브 파일럿·문서 31 승인) 현황, 주요 발견 요약, 재개 절차(dev-watch.sh·워크트리·메모리 이슈), 사용자 결정 대기 목록 |
| [33_parallel_display_scope.md](./33_parallel_display_scope.md) | D17(새 예측 병행 표시) 1단계 구현 범위 보고서(문서만, 코드 수정 없음): 배치 표에 열 추가(예상⑤·80%범위·신뢰도·경고·LB·도움사용률), 신규 `clear_rate/` 모듈·API, lightgbm 백엔드 의존성 결정 필요(D7), `ProductionDashboard/index.tsx` 동시편집 충돌 위험 큼(다른 세션 217줄 변경 중), 추정 8.5~12인일, 승인 필요 결정 7건 |
| [34_clear_rate_distribution.md](./34_clear_rate_distribution.md) | 379레벨 클리어율 분포 3종 비교(실제 AF ft_any / 기존 predicted_clear_rate / 개선 E1 OOF, v2.3·v2.4규칙만 입력 둘 다, 새 봇 측정 없음): 기존 예측은 방향은 맞으나(rho 0.21) 크게 낮고 좁게(평균 0.57 vs 실제 0.93) 찍음, E1은 평균은 맞히지만 sd가 실제의 57%로 평균회귀(특히 실제 0.85 미만 40레벨에서 +0.12 과대추정), v2.3/v2.4규칙만 입력 차이는 분포 수준에서도 무시 가능 |

## 4. 결정 로그 (사용자 확정)
| # | 결정 |
|---|---|
| D1 | 목표는 **과금이 아닌 플레이 능력 기반** 난도 개인화다. 클라는 평가 계산 없이 검증된 후보만 선택하고, **판 시작 전에만** 결정한다 |
| D2 | 레벨 1~3은 완전 고정이다. **32레벨부터 t0 + randSeed**(클라 `ShuffleEmptyTiles`)로 간다. 4~31은 언급이 없어 현행 유지로 **가정**한다(재확인 필요) |
| D3 | 레벨당 **기준 1 + 쉬움 2 + 어려움 2**. 위아래 **양방향 필수**이고 간격은 비대칭이어도 된다. 한쪽만 있는 구성은 불가 |
| D4 | 종류 수 ±1 허용: 쉬움 쪽은 utc0−1, 어려움 쪽은 utc0+1까지. **기준 시드 ±1은 원맵 극단 레벨에만**(relaxed) |
| D5 | 배포 **A안**: 새 필드 없이 기존 `randSeed`에 `"b\|e2\|e1\|h1\|h2"`(첫 값 = 기준)를 넣는다. 토큰은 `seed` 또는 `seed@utc`. 토큰 수는 1/3/5(검증 실패 시 3단계 `b\|e2\|h2`) |
| D6 | 구버전 앱 호환은 고려하지 않는다(레벨이 빌드에 내장되고 델타가 OFF이므로). **델타를 다시 켤 때 최소 앱 버전 강제를 재검토**한다 |
| D7 | 정적 난이도 점수로는 시드를 구분할 수 없어 쓰지 않는다. 배치 지표 사전필터도 상관이 약해 채택하지 않았다 |
| D8 | 테스트는 **최신 LIVE 3차 배치 사본(pv_sandbox)**에서만 한다. 원본 배치·서버 데이터는 건드리지 않는다 |
| D9 | 프로덕션 탭에 **"시드 변형 플레이"** 수동 플레이 UI를 추가한다(블라인드, 결과 기록) |
| D10 | 봇 결함 2건(θ 0.34~0.50 골짜기, θ1.0 patience 분기) 수정은 **별건**으로 하되 **P2 전에 권고**한다 |

## 5. 미결정
- v4 결과 확정(5단계 / 3단계 레벨 비율, h2 하한 적용 결과)
- P2 확대 범위·시점(대상 546레벨, 예상 시간은 08 §6·09)
- 봇 결함 수정 시점(공유 코어 `bot_simulator.py`, 에디터 전체 난도 지표에 영향)
- G3(Unity 실경로 골든 덤프, 게임 저장소에 에디터 전용 스크립트 추가) 승인
- 클라 착수 시점, 사다리 수치(N_up / K_down 등), 재도전 시 시드 유지 정책
- 레벨 1~31 정책 재확인(4~31 현행 유지 가정)
- t0화로 원맵보다 어려워지는 레벨(원맵이 무작위 배정보다 쉬운 경우가 다수) 처리: relaxed 적용 / 제외 / 수용

## 6. 관련 코드 (에디터 저장소)
| 경로 | 역할 |
|---|---|
| `backend/app/core/pv/cs_shuffle.py` | 클라 `ShuffleEmptyTiles`·zWellRandom 비트 일치 Python 포트 |
| `backend/app/core/pv/canonical.py` | 정규 맵(GB 변환 순서), structHash·typesHash |
| `backend/app/core/pv/t0ize.py` | t0화 규칙과 단언, 봇 입력 변환 |
| `backend/app/core/pv/evaluate.py` · `select.py` · `features.py` | 시드 평가(봇·솔버), 선별 규칙, 배치 지표 |
| `backend/scripts/pv_*.py` | 샌드박스 생성, 파일럿, 재측정(v2), utc ±1(v3), v4, export, **독립 검증 `pv_verify_selection.py`** |
| `backend/app/api/routes/pv_play.py` | 수동 플레이 API(`/api/pv-play/*`). 샌드박스 읽기 + 결과 append |
| `frontend/src/components/ProductionDashboard/PvSeedPlayPanel.tsx` · `frontend/src/api/pvPlay.ts` | 프로덕션 탭 "시드 변형 플레이" UI |
| `tools/pv_golden/` | dotnet 골든 CLI(클라 원본 C# 링크·추출 실행) |
| `backend/tests/golden/pv_t0/` | 골든 벡터(입력·정답·manifest, README) |
| `backend/tests/test_pv_*.py` | 포트·정규화·t0화/선별·지표·플레이 API 테스트 |

## 7. 샌드박스
- 위치: `backend/data/pv_sandbox/pv_20261002_live3/` (git 제외, production 경로 밖, 에디터 UI import 금지)
  - `source.json`: LIVE 3차 배치 바이트 사본. `manifest.json`: 원본 sha256·버전
  - `t0/`, `eval/`, `eval2/`, `eval3/`, `eval4/`: 평가 원자료(v4 진행 중)
  - `selection_v2.json`, `selection_v3.json`, `selection_v4.json`(v4 진행 중): 선별 결과(기계 판독용)
  - `verify/`, `verify_v3_relaxed/`: 독립 검증 결과
  - `golden2/`, `golden3/`: 실행 중 대조한 골든
  - `manual_play/results.jsonl`: 수동 플레이 기록(첫 기록 때 생성)
- 원본 LIVE 배치(`backend/data/production/`)와 서버 데이터는 수정하지 않는다. 업로드 경로와도 섞이지 않는다(04 §A1).
