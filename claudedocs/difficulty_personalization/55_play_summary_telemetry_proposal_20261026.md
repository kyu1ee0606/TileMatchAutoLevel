# 55. 판 단위 요약 계측 제안서 (2026-10-26)

> **문서 성격: 제안서만. 구현은 게임 담당(Codex) 몫.** 이 세션은 게임 저장소·봇 코드를 수정하지 않았다.
> 근거는 파일 경로(가능하면 줄 번호)로 표기, 추정은 **'추정'**으로 명시.

## 0. 요약

- 지금 가능한 비교: 클리어율, 실패 원인 분포(`fail_reason` 8종), 판당 플레이 시간·콤보·픽 수 **총량**만.
- 지금 불가능한 비교: **선택 순서·판단 패턴** — 봇이 "사람처럼 고민하며 고르는지"는 집계값만으로 검증 불가.
- 권장: 기존 `level_clear`/`level_fail`는 무변경, **신규 `level_summary` 1개 이벤트**를 `dda_play`와 같은 선례 패턴으로 추가.
- P0 지표 8개는 전부 봇 트레이스 스크립트(`bot_dock_trace_20261026.py`, `bot_hazard_trace_20261026.py`)가 이미 산출 중인 턴별 필드의 요약판이라, 봇 쪽 구현 비용은 낮다(추정).

## 1. 목적·배경

### 1-1. 지금까지 비교 가능한 것

`level_clear`/`level_fail`의 기존 파라미터(`GameBridgeManager.cs:487 HandleLevelClear` / `:687 HandleLevelFail`, [DESIGN_MMP_EVENTS.md:651-652](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)):

- `level_clear`: `level, attempt, playtime_sec(누적), is_infinite, item_used, play_sec(판당), avg_click_ms, combo_max, perfect_count, combo_break_count, free_entry, combo_carry_in/combo_streak` — 18개(공통 6 포함, [:375](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)).
- `level_fail`: 위 + `fail_reason`(8종 enum) + `tiles_left` — 19개(공통 6 포함, [:375](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)).
- 흥미롭게도 **총 픽 수는 이미 간접 유도 가능**: `avg_click_ms`는 첫 클릭 제외 표본이라 `>0`이면 최소 2픽 확정, `tiles_left = 총계 − 픽수`이므로 `perfect_count`(3장 매치 1회=+1)와 겹치면 정확한 픽 수가 나온다 — 실측으로 폭탄 사망 14건을 "정확히 3픽"까지 확정한 사례가 있다([DESIGN_MMP_EVENTS.md:1450](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)). 그러나 이건 **사후 역산**이고, 공식 필드가 아니며 **순서 정보가 없다** — "몇 번째 턴에 무엇을 골랐는지"는 여전히 비교 불가.

### 1-2. 지금까지 비교 불가능한 것

- 선택 순서(언제 무엇을 집었는지), 독 운용 패턴(위험 상태 진입/탈출 시점), 기믹 대응 타이밍(폭탄 노출 후 몇 턴 안에 해제했는지 등).
- 이건 "클리어했는가/실패했는가"와 "실패 원인 범주"만으로는 검증 불가능한 질문이다.

### 1-3. 봇 고도화 현황 (오차 수준, 수치는 모두 [26_bot_v24.md](./26_bot_v24.md) 인용)

- 최종 v2.4 모델(E1, 410레벨): `클리어 MAE 0.063 / ρ 0.769 / 범위 적중 0.712 / 80%구간 0.793`([26_bot_v24.md:408](./26_bot_v24.md)) — ρ·범위 적중은 사전 기준 불합격(각 −0.011/−0.003).
- 실패 원인 분포(`clear/Grass/Bomb/Normal`, 봇 vs AF)는 맵마다 방향이 다르게 틀린다: 예 L152 풀 실패 과소(0.8% vs AF 58.6%), 폭탄 맵 3개는 폭탄 실패 과대([26_bot_v24.md:236](./26_bot_v24.md)).
- 즉 "클리어율·실패 원인 분포"조차 완전히 맞지 않는데, 그보다 더 미세한 "판단 패턴"은 **애초에 비교할 데이터 자체가 없다**. 본 제안은 그 데이터를 만드는 것이고, 봇 정확도 자체를 개선하는 것은 범위 밖이다.

## 2. 이벤트 설계

### 2-1. 옵션 A — 기존 `level_clear`/`level_fail`에 파라미터 추가

- 장점: 기존 조인(heart_run_id/level/attempt) 불필요, 기존 대시보드 그대로.
- 단점:
  - **AF/Firebase 파라미터 25개 한도** — `level_clear` 18/25(여유 7), `level_fail` 19/25(여유 6)([DESIGN_MMP_EVENTS.md:375](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)). §3의 P0 8개만으로 이미 여유를 넘는다.
  - 기존 이벤트의 "매치/실패 판정" 의미가 섞인다. 운영 시트·생성기 재동기화 필요(수동 CSV 편집 금지, 스크립트로 재생성, [DESIGN_MMP_EVENTS.md:108](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)).
  - 기존 대시보드·CPA 판정이 같은 이벤트에 걸려 있어([GameController.cs:936](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_HOOK_MAP.md) 마일스톤·CPA), 실수로 영향을 줄 위험이 있다.

### 2-2. 옵션 B — 신규 `level_summary` 1개 (권장)

- 선례: `dda_play`가 이미 "기존 `level_start/clear/fail` 3종은 무변경, 신규 1종만 추가" 결정을 거쳤다([DESIGN_MMP_EVENTS.md:25](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)), 판 연결은 `heart_run_id`로 조인([:38](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)). `level_summary`는 같은 패턴을 재사용한다.
- 예산: `dda_play`가 "전용 20 + 공통 5 = 25"([:31](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md))로 이미 한도를 다 썼으므로 **`dda_play`에 끼워 넣는 것도 불가능** — 별도 이벤트가 필요하다는 근거가 하나 더 있다.
- 단점: 판당 이벤트 전송 1건 추가(빈도 증가), 신규 조인 키·시트 신규 행 등록(`.context/build_mmp_csv.py` 재생성 필요, [:108](/Users/casualdev/sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/DESIGN_MMP_EVENTS.md)), 신규 파서가 raw 집계 쪽에도 필요.
- **권장**: B. clear/fail 판정 경로를 건드리지 않아 회귀 위험이 낮고, `dda_play` 선례로 결정 비용도 낮다.
- 발송 시점(제안): `level_clear`/`level_fail` 판정 직후, 같은 판의 `heart_run_id` 동봉. 무한 판 포함 여부는 §7 결정 필요.
- 파라미터 버짓(제안): `dda_play`와 동일 구조로 전용 ≤19~20 + 공통 ~5~6 = 25. §3 지표가 P0(8)+P1(4)+P2(4)=16개로 이 안에 들어온다.

## 3. 지표 목록

각 항목: **정의 · 집계 시점 · 타입 · 예상 비용 · 봇 산출 가능 여부 · 검증 가설**

### P0 (우선)

| # | 지표 | 정의 | 집계 시점 | 타입 | 비용 | 봇 가능? | 가설 |
|---|---|---|---|---|---|---|---|
| 1 | `total_picks` | 판 전체 픽(타일 선택) 수 | 판 종료 | int | 낮음(픽마다 +1) | ✅ `moves_used` 그대로([bot_simulator.py:529](/Users/casualdev/TileMatchAutoLevel/backend/app/core/bot_simulator.py)) | 봇-사람 픽 수 분포가 비슷한가(난이도 체감 proxy) |
| 2 | `first_match_turn` | 첫 3매치 완성까지 픽 수 | 런타임 중 1회 플래그 후 종료 시 기록 | int | 낮음 | ✅ `Move.will_match` 플래그([:587](/Users/casualdev/TileMatchAutoLevel/backend/app/core/bot_simulator.py))로 첫 발생 턴 추적 가능 | 오프닝 탐색 전략 유사성 |
| 3 | `max_dock_occupancy` | 판 중 독 최대 점유 칸 수 | 매 픽 후 비교·최대 유지 | int | 낮음 | ✅ `len(state.dock_tiles)` 턴별 추적([bot_dock_trace_20261026.py:48](/Users/casualdev/TileMatchAutoLevel/backend/scripts/bot_dock_trace_20261026.py)) | 독 관리 압박 재현도 |
| 4 | `dock_ge5_turns`/`dock_ge5_ratio` | 독 ≥5칸(7칸 중, [Dock.cs:512](/Users/casualdev/sp_meowsgarden) `CurMaxSlotCount`) 도달 턴 수·비율 | 매 픽 후 | int/float | 낮음 | ✅ 동일 트레이스 필드로 계산 | "위험 독" 체류 시간 사람-봇 일치 여부 |
| 5 | `last5_dock_signature` | 마지막 5수의 독 구성(타입-카운트 요약) | 롤링 버퍼, 실패 확정 시 flush | string(≤100자 값 제한, [DESIGN_MMP_EVENTS.md:154](/Users/casualdev/sp_meowsgarden)) | 중간(문자열 인코딩 필요) | ✅ `dock_types`/`pairs`/`singles` 필드 그대로([bot_dock_trace_20261026.py:44-49](/Users/casualdev/TileMatchAutoLevel/backend/scripts/bot_dock_trace_20261026.py)) — 봇 쪽이 더 쉬움 | 막판 독 구성이 사람과 비슷한가 |
| 6 | `pre_fail_dock_pairs` | 실패 직전 독 안 "같은 타입 2장" 묶음 수 | 실패 확정 시점 | int | 낮음 | ✅ `pairs` 필드 직접(`:49`) | "한 장만 더 있었으면" 식 간발의 실패 패턴 일치 여부 |
| 7 | `blind_newtype_pick_ratio` | 매치 없는 턴 중, 독에 無한 새 타입을 단일 픽한 비율 | 매 픽 | float | 낮음 | ✅ `will_match`=false + dock type dict 조회로 계산 | 탐색성 픽(정보 수집형) 비율이 사람과 비슷한가 |
| 8 | `bomb_expose_defuse_turns`/`bomb_remaining_at_end` | 폭탄 노출~해제(또는 폭발) 턴 차, 해제/폭발 시 남은 카운트 | 노출 시 시작, 해제/폭발 시 종료 | int | 중간(기믹별 상태 추적) | ✅ `bombs` dict(`rem`,`exposed`) 그대로([bot_hazard_trace_20261026.py:44-48](/Users/casualdev/TileMatchAutoLevel/backend/scripts/bot_hazard_trace_20261026.py)) | 폭탄 위기 대응 타이밍이 사람과 비슷한가 |

### P1

| 지표 | 정의 | 집계 시점 | 비용 | 봇 가능? | 가설 |
|---|---|---|---|---|---|
| `stack_destroy_start_turn`/`consecutive_destroy_run` | 스택/컨테이너 파기 시작 턴·연속 파기 길이 | 파기 발생마다 | 중간 | ✅ `kind()` 함수로 `stack`/`craft`/`craft_emitted` 연속성 추적 가능([bot_dock_trace_20261026.py:19-25](/Users/casualdev/TileMatchAutoLevel/backend/scripts/bot_dock_trace_20261026.py)) | 컨테이너 공략 순서가 사람과 비슷한가 |
| `grass_isolation_turn` | 풀 고립(더 이상 풀 수 없는 상태 진입) 발생 턴 | 매 픽 후 판정 | 중간(판정 로직 필요) | ✅ `_check_grass_impossible`(동일 판정, [bot_hazard_trace_20261026.py:36](/Users/casualdev/TileMatchAutoLevel/backend/scripts/bot_hazard_trace_20261026.py)) 재사용 가능. 단 게임측 동등 판정 로직 **위치 미확인**(§7) | 풀 고립을 사람도 비슷한 시점에 겪는가 |
| `key_unlock_turn` | 열쇠/잠금 해제 턴 | 해제 시점 | 낮음 | 추정 가능(봇에 key 추론 후보 있으나 PREREG 미채택, [26_bot_v24.md:200](./26_bot_v24.md)) | 잠금 해제 순서가 사람과 비슷한가 |
| `craft_link_pick_dock_occupancy` | craft/link 타일 픽 직후 독 점유 수 | 해당 픽 직후 | 낮음 | ✅ `kind()=='link'`/`'craft_emitted'` 시점 dock len | craft/link 픽을 독 여유 있을 때 하는지 |

### P2 (보조 — 봇 비교 불가 다수, 명시)

| 지표 | 정의 | 게임측 근거 | 봇 비교 |
|---|---|---|---|
| 부스터/부활 사용 시점(수 번호)·종류 | 몇 번째 픽에서 어떤 부스터/부활을 썼는지 | `Item.cs:258 ApplyUse`, `GameController.LogReviveMmp`(결제 확정 6곳, [DESIGN_MMP_HOOK_MAP.md §2-5/§2-3](/Users/casualdev/sp_meowsgarden)) | ❌ 봇은 부스터/부활 로직 없음(코드에 미발견) — **비교 불가, 게임 쪽 단독 지표로만** |
| 튜토리얼/DDA 도움 사용 구분 | `assisted` 플래그와 일치 판정 | `dda_play.assisted`([DESIGN_MMP_EVENTS.md:46](/Users/casualdev/sp_meowsgarden)) | ❌ 봇은 튜토리얼 개념 없음 — 비교 불가 |
| 일시정지·이탈 | 판 중 pause/background 진입 | `GameDataController.cs:619/655 OnApplicationPause` | ❌ 봇은 세션/배경전환 개념 없음 — 비교 불가 |
| 수 간격 분포(중앙값·p90) | 픽 사이 시간 간격 | 기존 `avg_click_ms`는 **평균**만, 60초 초과 표본 폐기+부활 직후 제외([DESIGN_MMP_EVENTS.md:1097](/Users/casualdev/sp_meowsgarden)) | ❌ **직접 비교 불가** — 봇은 턴 기반이라 "시간"에 대응하는 의미 있는 값이 없다(추정). 분포(버킷 카운트)는 게임 쪽 단독 분석용으로만 의미 있음 |

> **줄번호 드리프트 정정**(2026-10-27, §8-11 조사 중 확인): 위 표 "부스터/부활 사용 시점·종류" 행의 `Item.cs:258 ApplyUse`는 이번 세션 코드 Read 결과 실제 위치가 아니다 — `ApplyUse`는 `Item.cs:416`(여러 `PayMode` 분기 `:318/322/340`에서 호출)에 있다. §3은 초안 보존 대상이라 본문은 고치지 않고 여기 각주로만 정정. `level_summary`에는 이 지표 자체가 없음(§8-5 "제거" 처리, `seg_boost`만 필터용으로 존재)이라 구현에 영향 없음.

## 4. 수집 범위·샘플링, 데이터량, 정책

- **범위(제안)**: 전체 유저가 아니라 QA 빌드/소수 운영 샘플부터 — §6 단계안 참조.
- **데이터량(추정)**: `level_summary` 1건/판, 페이로드는 현재 `dda_play`(25파라미터 문자열, 값 100자 이하)와 동급 — 기존 `dda_play` 1건과 전송 비용 유사(추정, 실측 없음).
- **개인정보**: payload에 전체 규칙 JSON/개인 GUID/영수증/닉네임/기기 ID를 넣지 않는 기존 원칙을 그대로 따른다([DESIGN_MMP_EVENTS.md:154](/Users/casualdev/sp_meowsgarden) 빙고/레이스 계약에서 이미 확립된 선례). 식별자는 기존 `heart_run_id`(판 ID)만 사용 — 신규 식별자 발급 불필요.
- **전송 정책(제안)**: 1단계는 QA 빌드 `MMP_DEBUG` 로컬 로그만(운영 미전송) — `ReportToGameBoost`가 `MMP_DEBUG_ON` 진단 경로 전용이라는 기존 관행과 동일([DESIGN_MMP_EVENTS.md:151](/Users/casualdev/sp_meowsgarden)). 2단계부터 실제 SDK 전송(`SendEnabled` 가드, `MMP_EVENTS_ON && !UNITY_EDITOR` 등 기존 패턴).

## 5. 분석 계획

1. **봇 동일 지표 산출**: §3에서 "✅"로 표시한 지표는 `bot_dock_trace_20261026.py`/`bot_hazard_trace_20261026.py`의 턴별 트레이스에서 판 단위로 요약(최대값·마지막N·플래그)만 추출하면 된다 — 신규 봇 로직 불필요(추정, 기존 트레이스 스크립트가 진단용 1회성이므로 운영 비교용으로는 별도 배치 실행 필요).
2. **분포 비교**: 맵·숙련도(θ) 구간별로 사람 분포 vs 봇 분포를 KS 검정 또는 분위수(중앙값/p25/p75) 비교. `26_bot_v24.md`에서 이미 사용한 "진단 공동 MSE"·"클리어 MAE" 틀을 재사용(지표가 다를 뿐 비교 방법론은 선례 따름).
3. **성공 기준(제안, 결정 필요)**: 예) P0 지표 8개 중 과반에서 KS 거리 또는 분위수 차이가 사전 정한 임계 이하 — 구체 임계값은 §7 결정 필요.
4. **표본 요구량**: KS 검정 통상 맵당 최소 수십~백 단위 판(추정) — 정확한 요구량은 지표별 분산에 따라 다르므로 파일럿 후 재계산 필요.

## 6. 단계적 도입안

1. **QA 빌드 로그 검증**: `MMP_DEBUG` 로컬 로그만, 전송 없음. 페이로드 포맷·값 범위·100자 제한 위반 여부 확인.
2. **소수 운영 샘플**: 식별된 소규모 계정/빌드에서만 `SendEnabled` 켜기(기존 빙고/레이스 "별도 테스트 계정, 운영 분석 제외" 패턴 재사용, [DESIGN_MMP_EVENTS.md:231](/Users/casualdev/sp_meowsgarden)).
3. **확대**: 1~2단계 검증 후 전체 적용.
4. **게임 코드 변경 범위·위험**:
   - 변경 범위: 신규 생산자 파일 1개(`level_summary` 전용, `RewardTrackFlowTelemetry` 등 기존 신규 flow 패턴과 유사), `GameBridgeManager`의 clear/fail 판정 직후 호출 추가, `MmpEvents`/`AnalyticsEventMap`에 이벤트 등록.
   - 위험: (a) 판당 이벤트 1건 추가로 전송 빈도 증가 — SDK 큐 영향은 기존 `dda_play` 도입 때와 동급(추정). (b) 독/기믹 상태를 매 턴 집계하는 로직이 게임 성능에 영향을 줄 수 있음 — 특히 `dock_ge5_turns`류는 매 픽마다 카운터 비교뿐이라 비용 낮음(추정), 반면 `grass_isolation_turn`은 고립 판정 로직이 기존에 매 턴 호출되는지 확인 필요(§7).
   - 하트·DDA 계측과 정합: `heart_run_id`로 조인되므로 `heart_run_end`/`dda_play`와 동일 판을 가리키는지 분석 단계에서 검증 필요. `level_fail`은 부활 가능한 중간 실패이므로 `level_summary`를 중간 실패마다 보낼지 최종 실패에만 보낼지는 §7 결정 필요.

## 7. 결정 필요 사항

1. `level_summary` 발송 범위: `level_clear`/최종 `level_fail`에만 보낼지, 부활 가능한 중간 실패(`level_fail`이지만 이어지는 판)에도 보낼지 — 봇은 "1판=1시도"라 중간 부활 개념이 봇 쪽과 안 맞을 수 있음.
2. 무한(`infinity_`) 판 포함 여부 — `dda_play`는 1.1.2.54부터 무한도 포함하지만(`is_infinite=1`), `level_summary`의 1차 범위를 정식 판으로 한정할지.
3. P0/P1 지표 중 어느 것까지 1차 구현에 넣을지(파라미터 예산 ≤19~20 안에서 우선순위 재조정 필요 — 8+4=12개는 여유 있으나, 일부 지표(`last5_dock_signature`)는 문자열 인코딩 설계가 추가로 필요).
4. `grass_isolation_turn`의 게임측 동등 판정 로직 위치 — 이번 조사에서 `TileEffect.CheckEffectTileCanUncover`가 "같은 층 4방향 생존 이웃 < 남은 풀" 규칙으로 언급됐으나([26_bot_v24.md:141](./26_bot_v24.md)) 매 턴 고립 여부를 실시간 계측할 수 있는 훅 지점은 게임 담당 확인 필요.
5. `key_unlock_turn`의 게임측 열쇠/잠금 타일 클래스명 — 이번 조사(grep)로 명확한 `KeyGimmick`류 클래스를 찾지 못했다(`Tile_LevelEditor/ExLevelEditor.cs` 등 에디터 코드만 매칭). 게임 담당 확인 필요.
6. 분석 성공 기준의 구체 임계값(§5-3) — KS 거리/분위수 차이 허용 범위는 파일럿 데이터 없이 사전 확정하기 어려움. 1단계 QA 로그 확보 후 재논의 제안.
7. 색인 추가(제안만, 이 세션은 편집하지 않음): `claudedocs/difficulty_personalization/README.md` §3 문서 지도에 "55. 판 단위 요약 계측 제안서" 한 줄 추가, `TODO.md`에 "게임 담당 리뷰 대기" 항목 추가 — 두 파일은 '봇고도화' 세션이 편집 중이므로 **이번 세션은 수정하지 않았고 제안만 남긴다.**

## 8. 최종 명세 v1 (2026-10-26, 패널 검토 후 확정안)

> §1~§7 초안은 보존. 이 절이 구현 기준이다. 게임 쪽 구현자(Codex/사용자)가 바로 쓸 수 있게 정의·훅·QA를 적었다.
> 근거 표기: 게임 = `sp_meowsgarden/Assets/08.Scripts/...`, 봇 = `backend/...`. 미확인 항목은 **'확인 필요'** 로 표시.
> **변경 이력**: 2026-10-27 — §8-11 실측(읽기전용 조사) 결과를 §8-2/§8-7에 반영(link 픽 1탭=1픽 확정·보정 방법, 열쇠/컨테이너 훅 확정). §9 "게임 구현 인계(Codex)" 신규 추가. 이 세션도 게임·봇 코드는 수정하지 않았다(문서만).

### 8-1. 이벤트 개요

| 항목 | 값 |
|---|---|
| 이벤트명 | `level_summary` (AF = Firebase 동일명, `AnalyticsEventMap` 매핑 추가 없음) |
| 발화 시점 | `DdaRuntime` 종료 경로에서 `dda_play` 송신 직후 **같은 호출에서 1회**: clear(`OnClear`), 최종 실패(`OnFinalFailure`), 포기(`OnQuit`). 근거 `Tile_Script/InGame/Dda/DdaRuntime.cs:396-406, SendPlay :490` |
| 미발화 | `abandon`(앱 종료·강종 복구) — 판 중 메모리 값이 없으므로 보내지 않는다. 분석에서 "dda_play는 있는데 level_summary 없음" = abandon/유실로 처리 |
| 대상 범위 | `dda_play`와 동일(`DdaRuntime.Active()` 판). 즉 TestPlay·수동비교·event1·`settled_replay` 제외, 정식 + 무한 포함(무한 구분은 `dda_play.is_infinite` 조인) |
| 멱등 | `dda_play`의 `Active()`→정산 게이트 안에서 보내므로 판당 최대 1건. 분석은 `heart_run_id` 첫 건 채택(dda_play와 같은 규칙) |
| 전송 | `MmpEvents.Log` 즉시 발송(기존 `SendEnabled` 가드). 1단계는 QA 빌드 `[MmpQA]` 로그만 확인(§6 유지) |

### 8-2. 핵심 정의 (게임·봇 공통 수식)

- **픽(pick)**: 유저가 보드 타일을 탭해 독으로 들어간 1회. 게임 = `Dock.AddTile`의 `!tile.m_SelectedByHint` 블록(`MmpEvents.RegisterTileClick` 호출 지점, `Dock.cs:1081-1091`)과 **같은 조건**. 힌트 부스터·냥이의 도움/낚싯대 자동수집 = 픽 아님. 되돌리기(undo)로 픽 수가 줄지 않음. 부스터 사용 자체는 픽 아님. 봇 = `state.moves_used` 1 증가 = 1픽(`bot_simulator.py:1920`), 자동수집(`_v23_auto_collect_after_move`)은 미포함 → 동일.
  - link: 1탭에 2장이 들어가도 **1픽**(확정, §8-11-1 실측 — 추정 아님). 게임 확인 결과: `GameController.OnClickTileWithCheck`(`:2963`)의 `isLinkTile` 분기(`:2981-3006`)가 `linkTiles=[tile, linkedTile]`을 `GetSortedTileListByCanMatchFirst`로 **재정렬**(`:2996`)한 뒤 `OnClickTileList`(`:3068-3114`) 루프에서 **두 타일 각각** `Dock.AddTile`(`:3084`)을 호출하고, 둘 다 `!m_SelectedByHint`를 통과해 `RegisterTileClick`이 **1탭당 2회** 불린다(`Dock.cs:1091`, 코드 Read로 직접 확인). 보정 없이 쓰면 게임 쪽 `picks`가 봇의 2배로 집계됨. **구현: `picks` 집계 훅을 `Dock.AddTile` 내부 단독이 아니라 `OnClickTileWithCheck`/`OnClickTileList` 호출 1회당 +1로 두거나, link 쌍의 2번째 `AddTile` 호출에서 picks 증가만 생략하는 가드를 추가**(occ/cap 스냅샷·기믹 집계는 2번째 호출에서도 그대로 수행). 분류(`pick_new`/`pick_match`)는 **재정렬 전 원래 탭한 `tile` 파라미터 기준** — `linkTiles` 재정렬로 루프 0번째가 원래 탭 대상이 아닐 수 있어 별도 식별·고정 필요. 봇 = Move 1개(`linked_tiles` 동반, `bot_simulator.py:588, 2209-2233`) — 위 보정 적용 시 일치.
- **픽 순번**: 구간 내 k번째 픽 = k (1부터).
- **구간(segment) = 판 시작 → 첫 종료 사건**. 첫 종료 사건 = 클리어, **첫 `GameController.OnLevelFailed` 호출**(부활 팝업 전, `GameController.cs:1395`), 또는 실패 전 포기. 이 순간 모든 값을 **동결**하고 이후(부활 후 이어하기)는 누적하지 않는다.
  - 이유: 봇은 부스터·부활이 없고 첫 실패에서 끝난다(`_play_game`, `bot_simulator.py:1833-`). 부활 후 구간은 봇과 비교 불가하고, 최종 결과·부활 수는 이미 `dda_play.result/revive_cnt`에 있다.
- **독 점유(occ)**: 픽 **직전**의 논리 점유 = 독 타일 중 매치 확정분 제외 수. 게임 = `Dock.GetTileCountExceptOnMatchNew()`(onMatch 제외 + 타입별 `%3`, `Dock.cs:3730`) — 연속 탭으로 매치 애니메이션 중이어도 논리값. 봇 = 선택 시점 `len(state.dock_tiles)`(봇은 3매치 즉시 제거, `bot_dock_trace_20261026.py` trace의 `dock`과 같은 시점).
- **독 용량(cap)**: 그 순간 `Dock.CurMaxSlotCount`(잠금·추가매치 칸 제외, `Dock.cs:512`). 봇 = `sum(1 for s in state.dock if not s.is_locked)`.
- **여유칸(free)** = cap − occ. **위험 상태** = free ≤ 2. 게임 경고 펄스 기준과 같다(`_bufferDangerThreshold = 2`, `Dock.cs:85/1265`). 단 그 필드는 SerializeField라 인스펙터 값이 바뀔 수 있으므로 **계측은 상수 2를 쓴다**.
- **픽 분류**: 픽 직전 독 안 같은 타입 수 n(= `Dock.AddTile`의 `existingCount`, `Dock.cs:1076`) — n=0 새 타입 / n=1 짝 만들기 / n=2 매치 완성. 봇 = trace `chosen.in_dock`.
- **기믹 유무 판정**: 판 로드 시 맵에 해당 기믹 타일/잠금 칸이 1개라도 있으면 "있음". 없으면 해당 파라미터 = **−1**.

### 8-3. 파라미터 표

공통 자동 6종(`level`·`surface`·`elapsed_d`·`gold`·`star`·`energy`, `MmpEvents.InjectCommonParams` `MmpEvents.cs:134-149`)이 붙는다. `level_summary`는 하트 정책 키 주입 대상이 아니다(`InjectHeartPolicyParams`는 level_start/clear/fail/retry/energy_empty/heart_run_end만, `:152-155`) → `heart_run_id`는 직접 넣어야 한다. `level`은 `dda_play`와 같은 값으로 **직접 설정**(공통 주입은 덮어쓰지 않음, `SetIfAbsent`).

| # | 이름 | 타입 | 정의(수식) | 집계 시점 | 기믹 없을 때 | 봇 산출 | 목적 | 우선 |
|---|---|---|---|---|---|---|---|---|
| (공) | `level` | int | `dda_play.level`과 같은 값(정식 N, 무한 RunLevel) | 송신 | — | 맵 번호 | 맵 키 | 필수 |
| 1 | `heart_run_id` | str32 | 판 ID(`HeartRunPolicy.CurrentRunId`, dda_play와 동일) | 송신 | — | 해당 없음(봇 판 ID) | 조인 키(dda_play: dda_variant·revive_cnt·result·is_infinite) | 필수 |
| 2 | `sv` | int | 스키마 버전, v1 = `1` | 상수 | — | — | 정의 변경 시 분리 | 필수 |
| 3 | `seg_end` | enum | `clear` / `quit` / `FailReason` 이름(`Normal`,`Ice`,`Grass`,`Chain`,`Grass_CantRevive`,`Chain_CantRevive`,`Bomb`,`TimeOver`, `UIFailReason.cs:18`) — 첫 종료 사건 | 구간 끝 | — | `fail_reason()`(`bot_af_L32_500.py:226`) 매핑: Grass_CantRevive→Grass 등 분석에서 통합 | 첫 실패 원인(봇 실패 범주와 1:1). level_fail은 run_id가 없어 조인 불가 → 여기서 확보 | P0 |
| 4 | `picks` | int | 구간 픽 수 | 구간 끝 | — | `moves_used` | 판 길이·진행도, 비율 분모 | P0 |
| 5 | `seg_boost` | int | 구간 내 부스터 사용 수(전 종류, `BoostersUsedThisRun` 증가분 기준, 카운터 `MmpEvents.cs:1234`, 증가 `:1474`, 리셋 `:1453` — 확인됨 §8-11) | 구간 끝 | — | 항상 0 | **봇 비교 가능 표본 필터**(=0만 비교) | P0 |
| 6 | `pick_new` | int | Σ 픽[n=0] | 매 픽 | — | trace `in_dock==0` | 새 타입 투입 성향(탐색/수집형). 비율=pick_new/picks | P0 |
| 7 | `pick_match` | int | Σ 픽[n=2] | 매 픽 | — | `will_match` | 매치 완성 성향. 짝 만들기 = picks − pick_new − pick_match(파생, 미전송) | P0 |
| 8 | `min_free` | int | min over 픽 (free), 픽 0회면 −1 | 매 픽 직전 | — | min(cap − dock) | 독 압박 최대치 | P0 |
| 9 | `danger_picks` | int | Σ 픽[free ≤ 2] | 매 픽 직전 | — | 동일 | 위험 독 체류 길이(비율은 분석에서) | P0 |
| 10 | `danger_tail` | int | 구간 마지막 픽부터 거꾸로 센 연속 [free ≤ 2] 픽 수 | 구간 끝 | — | trace 꼬리 | "급사 vs 서서히 질식" 붕괴 패턴(초안 last5 문자열 대체) | P0 |
| 11 | `end_pairs` | int | 구간 끝 독에서 같은 타입 정확히 2장인 타입 수(onMatch 제외) | 구간 끝 | — | final dock `Counter` ==2 | "한 장만 더" 간발 실패 | P0 |
| 12 | `bomb_left_min` | int | 구간 중 폭탄 처리 순간의 남은 카운트 최소값. 폭탄 픽(해제) 시 그 폭탄의 픽 직전 `bombEffectRemainCount`, 폭발 시 0 | 해제/폭발 순간 | −1(폭탄 없음), −2(있으나 구간 중 해제·폭발 0건) | 픽 직전 `state.bomb_tiles[key]`, 폭발=0 | 폭탄 대응 여유(봇 폭탄 실패 과대 검증) | P0 |
| 13 | `grass_first` | int | 첫 풀 1겹 제거가 일어난 픽 순번 | 첫 발생 | −1, 구간 중 0건이면 0 | 풀 `effect_data['remaining']` 첫 감소 턴 | 풀 공략 시작 시점(봇 풀 실패 과소 검증) | P0 |
| 14 | `grass_left` | int | 구간 끝 미제거 풀 겹 합 Σ`grassEffectRemainCount`(보드 미픽 타일) | 구간 끝 | −1 | Σ `effect_data['remaining']` 미픽 풀 | 풀 방치량 | P0 |
| 15 | `key_unlock` | int | 첫 잠금 칸 해제가 일어난 픽 순번 | 첫 발생 | −1(잠금 칸 없음), 구간 중 미해제 0 | `state.dock` 잠금 칸 수 첫 감소 턴(`unlock_tile`, `bot_simulator.py:1096-1112`) | 열쇠 처리 시점(L138형 봇 과소 성공 진단) | P0 |
| 16 | `cont_first` | int | 컨테이너(스택 또는 craft 배출) 출신 타일을 처음 집은 픽 순번 | 첫 발생 | −1(컨테이너 없음), 구간 중 0건 0 | trace `kind in {stack, craft_emitted}` 첫 턴(`bot_dock_trace_20261026.py:19-25`) | 파기 시작 시점(craft/link/stack 탐색 차이) | P0 |

- 값은 전부 invariant 정수 문자열(기존 Dictionary 경로), `heart_run_id` 32자·`seg_end` ≤16자 → 100자 제한 무관. 카디널리티: `seg_end` 10값, 나머지 정수.
- 범위: 4·6·7·9·10은 0..picks, 8은 −1..cap, 11은 0..3(cap 7 기준), 12는 −2..초기 카운트, 13·15·16은 −1..picks, 14는 −1 이상.

### 8-4. 예산

- **전용 16 + 공통 6 = 22 / 25 → 여유 3.** (`dda_play` 20+5=25 만석과 달리 여유를 남김.)
- 여유 3은 v2 예약(§8-6 연기 항목 중 실측 필요성이 확인된 것). 공통 키를 늘리는 다른 작업이 이 이벤트에 영향을 주지 않는지 계약 검사(`tools/mmp_contract_check.py`)로 확인.

### 8-5. 제거·통합·연기 (초안 §3 대비)

| 초안 지표 | 판정 | 이유 |
|---|---|---|
| `total_picks` | **유지→`picks`** | 단 구간(첫 종료까지) 기준으로 재정의 |
| `first_match_turn` | **제거** | 대부분 맵에서 3~6픽에 몰려 분산 작음. 오프닝 성향은 `pick_new`/`pick_match`가 판 전체로 더 잘 잡음(분석가·디자이너 합의) |
| `max_dock_occupancy` | **대체→`min_free`** | 잠금 칸·칸추가로 cap이 맵마다 달라 점유 절대값은 비교 불가. 여유칸 기준이 dda_play `slots_left`와도 같은 축 |
| `dock_ge5_turns`/`ratio` | **통합→`danger_picks`** | 비율은 /picks로 파생. 기준을 "7칸 중 5"가 아니라 게임 경고와 같은 free≤2로(잠금 맵에서도 일관) |
| `last5_dock_signature` | **제거, `danger_tail`+`end_pairs`로 대체** | 문자열 인코딩·카디널리티·봇 동일 인코딩 부담. 독 7칸에서 매치 없는 상태는 타입 수 = 점유 − 짝 수로 결정되어 짝 수 + 점유(Normal이면 cap)로 구성 대부분 복원 |
| `pre_fail_dock_pairs` | **유지→`end_pairs`** | clear/bomb 등 모든 종료에 같은 정의로 확장 |
| `blind_newtype_pick_ratio` | **대체→`pick_new`(+`pick_match`)** | 비율 대신 카운트(파생 원칙). "매치 없는 턴 중" 조건은 봇·게임 판정 차이 위험(가용 매치 목록이 게임에 없음) → 단순 n=0 분류로 |
| `bomb_expose_defuse_turns` | **제거** | 카운트다운이 "노출 중 다른 픽마다 −1"(게임 `TileEffect.cs:1050-1061`, 봇 `:2959-`)이라 노출~해제 픽 수 = 초기값 − 해제 시 남은 값으로 파생. 다중 폭탄 집계 규칙도 필요 없어짐 |
| `bomb_remaining_at_end` | **대체→`bomb_left_min`** | 다중 폭탄에서 "end"가 모호. 최소값(가장 아슬했던 순간)이 판별력 큼 |
| P1 `stack_destroy_start_turn` | **채택→`cont_first`** | 봇 최대 오차가 key/stack/craft 맵(26 §L138·L306·L292) — P0로 승격 |
| P1 `consecutive_destroy_run` | **연기** | 정의(연속 기준) 합의 필요, 1차 값 보고 결정 |
| P1 `grass_isolation_turn` | **연기, `grass_first`+`grass_left`로 대체** | 매 픽 고립 판정은 게임에서 실패 순간에만 확인됨(실시간 훅 미확인) — 성능·버그 위험. 시작 시점·방치량은 단순 카운터로 충분 |
| P1 `key_unlock_turn` | **채택→`key_unlock`** | 잠금 칸 해제 1회 이벤트라 비용 낮음 |
| P1 `craft_link_pick_dock_occupancy` | **연기(v2 예약 1순위)** | link 짝 타일 계측 경로 확인 전엔 정의 위험 |
| `revive`/부스터 시점, 튜토/DDA 도움, pause, 수 간격 분포(P2) | **제거(이 이벤트)** | 봇 비교 불가. 부활 수·assisted·play_sec는 `dda_play`, 부스터는 `booster_use_*`/`item_used`에 이미 있음 |
| (신규) `seg_boost`, `seg_end`, `sv` | **추가** | 봇 비교 가능 표본 필터, level_fail 조인 불가 보완, 정의 버전 |

### 8-6. 패널 토론 요약

참가(가상): ① 레벨 디자이너 ② 라이브옵스/DDA ③ 데이터 분석가 ④ 봇 엔지니어 ⑤ 클라이언트 엔지니어 ⑥ 데이터 정책.

1. **부활 후 구간을 포함할 것인가** — ②: "DDA는 최종 결과·부활 후 행동이 중요". ④: "봇은 첫 실패에서 끝나 혼합하면 비교 불가". ③: 최종 결과·부활 수는 `dda_play`에 이미 있음. **결론: 첫 종료 사건에서 동결**. ② 반대 의견(부활 후 독 관리도 보고 싶다)은 v2 여유 슬롯 후보로 기록만.
2. **last5 문자열 vs 정수 요약** — ①: "마지막 독 모양이 레벨 설계 피드백에 직관적". ③⑤: 100자 제한·인코딩 버그·GA4 카디널리티, ④: 봇 인코딩 일치 보장 어려움. **결론: `danger_tail`+`end_pairs`**. ①은 QA 로그(`[MmpQA]`)에서 1단계 동안 원시 독 구성을 별도 디버그 출력으로 보는 것에 동의.
3. **비율 vs 카운트** — ③: 비율은 픽 수가 작은 판에서 노이즈, 카운트+분모면 가중 집계 가능. **결론: 카운트만 전송**.
4. **기믹 지표를 공통 이벤트에 넣을지** — ⑤: 기믹별 이벤트로 쪼개면 송신 수 증가. ③: −1 규칙이면 필터로 충분. **결론: 한 이벤트, 없으면 −1**. ⑥: 식별자는 기존 `heart_run_id`만, 신규 ID·기기 정보 없음 → 문제 없음.
5. **풀 고립 판정** — ④는 봇 `_check_grass_impossible` 재사용 가능하다고 했으나 ⑤가 게임측 매 픽 판정 비용·위치 미확인을 들어 반대. **결론: 연기**.
6. **위험 기준 free≤2** — ①: 잠금 칸 맵(cap 6)에서 "≥5칸"은 다른 의미. 게임 경고 펄스와 같은 기준이면 "유저가 경고를 본 픽"과도 일치. 합의.

### 8-7. 구현 체크리스트 (게임 쪽)

훅 후보(확인된 위치):
- 판 리셋: `MmpEvents.ResetRunMetrics`(`TemplateScripts/Analytics/MmpEvents.cs:1449`, 다시하기 경로 `ResetRunMetricsForReplay :1428` 포함). **부활 시 리셋 금지**(동결 플래그만 유지).
- 기믹 유무(−1 결정): 판 로드 완료 시(`LevelController.LoadLevelRoutine` → `Dock.Init` 직후, `BeginComboRun`과 같은 지점) 보드 타일 효과·잠금 칸 스캔.
- 픽 집계: `Dock.AddTile`의 `!tile.m_SelectedByHint` 블록(`Tile_Script/InGame/Dock.cs:1081-1091`) — `existingCount`(n), 추가 전 occ/cap. 동결 상태면 무시. `DdaManualCompare.IsActiveRun` 제외 조건도 `RegisterTileClick`과 동일하게. **link 보정 필요(확정, §8-11-1)**: `OnClickTileWithCheck`(`GameController.cs:2963`)의 `isLinkTile` 분기가 재정렬된 `linkTiles` 두 장을 각각 `Dock.AddTile`(`:3084`)로 넣어 `!m_SelectedByHint`를 둘 다 통과시키므로, `picks` 훅은 `OnClickTileWithCheck`/`OnClickTileList`(`:3068-3114`) 호출 1회당 +1로 두거나 link 쌍 2번째 `AddTile`에서 picks 증가만 생략하는 가드를 넣는다(occ/cap·기믹 집계는 2번째 호출에서도 유지). `pick_new`/`pick_match` 분류는 재정렬 전 원래 탭 `tile` 기준.
- 폭탄: 폭탄 타일 픽 시 그 타일 `bombEffectRemainCount`, 폭발 시 0 → `TileEffect.AddBombCount`/`CheckBombCount`(`TileEffect.cs:1364/1408`), 노출 중 다른 픽마다 감소 호출은 `TileEffect.cs:1061 AddBombCount(-1)`(확인됨, §8-11 추가항목).
- 풀: `TileEffect.cs:965-975` `grassEffectRemainCount--` 지점에서 첫 발생 픽 순번 기록. 끝 시점 합은 보드 스캔. 매 턴 호출 경로에 있는 단순 감소 카운터라 성능 우려 없음(확인됨, §8-11 추가항목) — 단 "고립 판정"(연기된 `grass_isolation_turn`)과는 별개.
- 열쇠: **확정(§8-11-2)**. 훅 = `Dock.UnLockSlot()`(`Dock.cs:900-912`, `lockedDockSlots` 역순 pop), 트리거는 `Dock.RemoveRoutineTiles`의 `if (keyTileCount>=3) UnLockSlot()`(`Dock.cs:1964-1966`, 키 3매치 완성 매치애니메이션 종료 콜백) — 호출 시점 누적 `picks` 값을 그대로 `key_unlock`에 기록. 보드 잠금 타일은 **없음**(`KeyGimmick`/`TileLock` 등 클래스 grep 전수 확인 결과 미존재) — §7-5의 "확인 필요"는 해소, 독 잠금 슬롯(`DockSlot.isLock`, `DockSlot.cs:15`)만 존재. `min_free`/`cap`은 `Dock.CurMaxSlotCount`(`Dock.cs:512`) → `CurDockCountExceptAdditionalMatchSlotAndLock`(`:491-508`)에서 잠금 슬롯 제외(`:500`)로 §8-2 cap 정의와 일치 확인됨.
- 컨테이너: **확정(§8-11-3), 신규 플래그 불필요**. `Tile.isStackTile`(`Tile.cs:42`)·`isCraftTile`(`Tile.cs:44`)가 `Tile.Init`(`:491,630`)에서 이미 설정·유지되고 피킹 로직에서 계속 참조됨. `cont_first` 훅 = `Dock.AddTile`(`Dock.cs:1049`) 진입 시 전달된 `tile` 파라미터의 `isStackTile`/`isCraftTile` **첫 true 시점**(link 보정과 같은 지점에서 함께 처리 가능). 봇 `kind() in {stack, craft_emitted}`(`bot_dock_trace_20261026.py:19-25`)과 개념적으로 동일 — `craft_emitted`가 배출 전/후 어느 쪽까지 포괄하는지 교차 대조는 추정 수준.
- 구간 동결: 클리어 `GameController.OnLevelClear`(`GameController.cs:1141`, `StoreClearedCombo` 직전), 실패 `GameController.OnLevelFailed`(`:1395`, `RegisterFailReason :1429` 직후, 첫 호출만), 포기 `DdaRuntime.OnQuit`(실패 전일 때만 seg_end=quit).
- 송신: `DdaRuntime.SendPlay`(`Dda/DdaRuntime.cs:490`) 직후 별도 try/catch로 `MmpEvents.Log("level_summary", p)` — 계측 예외가 정책 경로를 깨지 않게(dda_play 규칙).
- 카탈로그: `.context/build_mmp_csv.py`에 신규 행(No.242 예상) 추가 후 재생성(CSV 수동 편집 금지), `DESIGN_MMP_EVENTS.md`/`HOOK_MAP` 갱신, `mmp_contract_check` ERROR 0, 외부 시트 1행.

QA 확인 항목:
1. 판당 1건: clear / 최종 실패 / 포기 각각 1건, abandon 0건, 다시하기·재진입 후 이전 값 누적 없음.
2. 부활: 첫 실패 후 부활→클리어 판에서 `seg_end`=첫 실패 사유, `picks`가 부활 후 증가하지 않음.
3. 픽 정의: 힌트 부스터·자동수집·undo가 `picks` 불변, link 1탭 = 1픽.
4. 값 범위: §8-3 범위 위반 0, `pick_new + pick_match ≤ picks`, `danger_tail ≤ danger_picks ≤ picks`, Normal 실패면 `danger_tail ≥ 1`.
5. 기믹 없음 맵에서 12~16 = −1, 있는 맵에서 −1 아님.
6. 무한 판: 송신되고 `dda_play.is_infinite=1`과 같은 run_id.
7. 연속 빠른 탭(매치 애니메이션 중)에서 `min_free`가 음수·cap 초과 없음.
8. 키 수 22, 값 100자 이하(`[MmpQA] params=22`).

### 8-8. 분석 계획 요약

1. `level_summary` ⨝ `dda_play` on `heart_run_id`(첫 건). 봇 비교 표본 = `seg_boost=0` ∧ (`dda_variant`로 봇이 같은 맵 변형 재현 가능).
2. 봇: 같은 맵·변형을 θ 혼합(26 v2.4 고정 혼합)으로 돌려 trace에서 §8-3 수식 그대로 산출(신규 봇 로직 불필요, 판 단위 요약 함수 1개 추가 예정 — 별도 작업).
3. 비교: 맵별 `seg_end` 분포(기존), 정수 지표는 분위수(p25/50/75)·KS, 비율(pick_new/picks, danger_picks/picks)은 픽 가중 평균. 기믹 지표는 해당 기믹 맵만.
4. 판정용 질문: 봇 독 가득 과대 → `min_free`·`danger_picks`·`pick_new` 비율 차이? 폭탄 실패 과대 → `bomb_left_min` 분포? 풀 실패 과소 → `grass_first` 지연·`grass_left`? key/stack/craft → `key_unlock`·`cont_first` 시점 차이?
5. 임계값·표본은 1단계 QA 로그 + 소수 운영 샘플 후 확정(§7-6 유지).

### 8-9. 남은 결정

1. 무한 판 포함 — 본 명세는 dda_play와 같이 **포함**(조인으로 분리 가능). 다르게 원하면 결정 필요.
2. `seg_end=quit`(실패 전 포기) 포함 — 포함으로 정함. 이탈 분석용, 봇 비교에서는 제외.
3. link 짝 타일의 AddTile 경로, 열쇠 잠금 해제 위치, 컨테이너 출신 플래그 존재 — 게임 담당 확인.
4. 여유 3슬롯 v2 후보 우선순위(`link_pick_free` / 부활 후 구간 요약 / `cont_run`) — 1단계 데이터 후.
5. 색인: README §3 문서 지도·TODO 항목 추가는 해당 세션 편집 종료 후(제안만).

### 8-10. 파라미터별 역할·판정 근거 (리스트 요약, 사용자 요청 형식)

#### A. 유지 파라미터 — 이름 — 역할(답하는 질문) — 쓰임 예시

- `level` — 어느 맵인지(봇이 같은 맵을 돌릴 기준). — 예: L138 사람 분포 vs L138 봇 분포를 같은 행에 놓는다.
- `heart_run_id` — `dda_play`와 같은 판 묶기(변형 `dda_variant`, 부활 수, 최종 결과, 무한 여부를 가져옴). — 예: DDA −1 변형 판만 골라 봇에 같은 변형을 재현시킨다.
- `sv` — 정의 버전 구분. — 예: v2에서 위험 기준을 바꾸면 v1 행과 섞지 않는다.
- `seg_end` — 첫 실패 원인이 무엇인가(봇 실패 범주 Normal/Bomb/Grass와 1:1). `level_fail`에는 판 ID가 없어 이것만 판과 묶인다. — 예: L152 사람 첫 실패 Grass 비중 vs 봇 Grass 비중 → 풀 실패 과소 크기 측정.
- `picks` — 판이 얼마나 진행됐나(실패 시점이 초반인가 막판인가), 비율 지표의 분모. — 예: 사람은 막판 실패, 봇은 11픽 조기 실패 → 봇 초반 운영 결함(L306형).
- `seg_boost` — 이 판을 봇과 비교해도 되나(부스터 0만 비교). — 예: 비교 표본을 seg_boost=0으로 거른 뒤 분포 비교.
- `pick_new` — 새 타입을 얼마나 독에 들이나(쌓아두는 성향). 독 가득 실패 원인 판별. — 예: 봇 pick_new/picks가 사람보다 높으면 "새 타입 단일 픽 과다"(26 L306·L292 가설) 확인 → 봇 감점 후보 채택 근거.
- `pick_match` — 매치 완성을 얼마나 바로 하나(짝 만들기 = picks−new−match 파생). — 예: 사람은 짝 만들기 비중 높고 봇은 즉시 매치 위주 → 봇 탐욕성 조정.
- `min_free` — 독이 가장 위험했던 순간 얼마나 몰렸나. 독 관리 난이도 지표. — 예: 클리어 판인데 min_free 1 비율이 높은 레벨 = 아슬아슬 클리어 → 체감 난이도 높음, DDA 하향 후보.
- `danger_picks` — 위험 독(여유 ≤2)에 얼마나 오래 머물렀나. — 예: 봇 위험 체류가 사람보다 길면 "독 가득 과대"의 원인이 운영 습관임을 확인.
- `danger_tail` — 실패가 급사인가 서서히 질식인가. — 예: 사람 Normal 실패는 tail 1~2(급사), 봇은 tail 6+(서서히) → 봇이 위험 상태에서 탈출 못 함.
- `end_pairs` — "한 장만 더 있었으면" 간발 실패인가. — 예: end_pairs 3 실패가 많은 레벨 = 타입 분배가 짝 끊김을 유발 → 레벨 타입 수·배치 조정.
- `bomb_left_min` — 폭탄을 얼마나 여유 있게 처리하나. 폭탄 난이도 원인 판별. — 예: 사람 대부분 2 이상, 봇 0~1 → 봇 폭탄 실패 과대는 봇 인지 결함, 레벨 탓 아님.
- `grass_first` — 풀 공략을 언제 시작하나. — 예: 사람이 봇보다 늦게 시작 → 봇 풀 실패 과소 원인 = 봇이 너무 일찍 풀을 챙김 → 봇 풀 주의 하향.
- `grass_left` — 끝날 때 풀을 얼마나 방치했나. — 예: 실패 판 grass_left 큰 레벨 = 풀 배치가 난이도 주범 → 풀 겹 수 하향.
- `key_unlock` — 열쇠(잠금 칸)를 언제 푸나. key 맵 난이도 원인. — 예: 사람은 초반 해제, 봇은 미해제(0) 많음 → L138형 봇 과소 성공 원인 확정.
- `cont_first` — 스택/craft를 언제 파기 시작하나. 컨테이너 맵 탐색 차이. — 예: 봇이 사람보다 훨씬 늦게/일찍 파면 `container_dig_capacity` 같은 후보의 방향 결정.

#### B. 초안에서 뺀 것 / 통합 / 연기 — 판정 — 근거(누가) — 대체

- `total_picks` — 통합(재정의) — 부활 후 구간은 봇 비교 불가(④ 봇 엔지니어) — → `picks`(첫 종료까지).
- `first_match_turn` — 제거 — 대부분 맵 3~6픽에 몰려 분산 작고 판단에 안 쓰임(③ 분석가, ① 디자이너 동의) — 오프닝 성향은 `pick_new`/`pick_match`가 대신.
- `max_dock_occupancy` — 통합 — 잠금 칸·칸추가로 용량이 맵마다 달라 절대 점유는 비교 불가(① 디자이너) — → `min_free`.
- `dock_ge5_turns` — 통합 — 기준을 "7칸 중 5"에서 게임 경고(여유 ≤2)로 바꿔 잠금 맵 일관(①) — → `danger_picks`.
- `dock_ge5_ratio` — 제거 — `danger_picks/picks`로 파생 가능, 비율은 소표본 노이즈(③) — → 분석에서 계산.
- `last5_dock_signature` — 제거 — 문자열 인코딩 버그 위험·100자 제한·GA4 카디널리티(③⑤), 봇 동일 인코딩 보장 어려움(④). 디자이너(①)는 원시 독 모양 선호 → 1단계 QA 디버그 로그로만 보기로 합의 — → `danger_tail` + `end_pairs`.
- `pre_fail_dock_pairs` — 통합(확장) — 실패뿐 아니라 모든 종료에 같은 정의 — → `end_pairs`.
- `blind_newtype_pick_ratio` — 통합 — "매치 없는 턴" 조건은 게임에 가용 매치 목록이 없어 봇과 판정 불일치 위험(④⑤), 비율은 파생(③) — → `pick_new` 카운트.
- `bomb_expose_defuse_turns` — 제거 — 카운트다운이 노출 중 다른 픽마다 −1이라 "초기값 − 해제 시 남은 값"으로 파생, 다중 폭탄 집계 규칙도 불필요(④) — → `bomb_left_min` + 맵 초기값.
- `bomb_remaining_at_end` — 통합 — 폭탄이 여러 개면 "끝"이 모호, 최소값(가장 아슬한 순간)이 판별력 큼(②③) — → `bomb_left_min`.
- `stack_destroy_start_turn` (P1) — 통합·승격 — 봇 최대 오차가 key/stack/craft 맵(②④) — → `cont_first`(P0).
- `consecutive_destroy_run` (P1) — 연기 — "연속" 정의 합의 필요, 1차 데이터 전 판단 근거 없음(③) — v2 여유 슬롯 후보.
- `grass_isolation_turn` (P1) — 연기 — 게임은 고립을 실패 순간에만 판정, 매 픽 판정 훅 미확인·성능·버그 위험(⑤가 ④의 봇 함수 재사용 안에 반대) — 당장은 `grass_first` + `grass_left`로 대체.
- `key_unlock_turn` (P1) — 통합·승격 — 해제 1회 이벤트라 비용 낮고 L138형 진단에 핵심(④⑤) — → `key_unlock`(P0).
- `craft_link_pick_dock_occupancy` (P1) — 연기 — link 짝 타일 계측 경로 미확인이라 정의 위험(⑤) — v2 여유 슬롯 1순위.
- 부스터/부활 사용 시점·종류 (P2) — 제거 — 봇에 부스터·부활 없음(④), 부활 수는 `dda_play.revive_cnt`, 부스터는 `booster_use_*`/`item_used`에 이미 있음(③) — 이 이벤트엔 `seg_boost`(필터용)만.
- 튜토/DDA 도움 구분 (P2) — 제거 — 봇에 개념 없음, `dda_play.assisted`와 중복(③) — 조인으로 사용.
- 일시정지·이탈 (P2) — 제거 — 봇 비교 불가, 난이도 판단에 안 쓰임(②③) — 없음.
- 수 간격 분포 (P2) — 제거 — 봇은 턴 기반이라 시간 대응값 없음(④), 평균은 기존 `avg_click_ms`(③) — 없음.
- (부활 후 구간 요약) — 연기 — ② DDA 담당 요청, ④ 봇 비교 불가 반대 — v2 여유 슬롯 후보.

### 8-11. 게임 코드 확인 결과 (읽기전용 조사, 2026-10-26)

> §7 결정 필요 사항 1건(link 짝 타일), 2건(열쇠/잠금 위치)에 대한 실측. 이 세션은 게임·봇 코드를 수정하지 않았다(읽기만).

**1. link 짝 타일 픽 카운트 경로 — 부분(정의 보정 필요, §8-2 가정이 "통과함" 쪽으로 확정)**

- 탭 입력 진입점 `GameController.OnClickTileWithCheck`(`GameController.cs:2963`). `isLinkTile==true` 분기(`:2981-3006`)에서 `linkTiles = [tile, tile.tileEffect.linkedTile]`를 구성하고 `GetSortedTileListByCanMatchFirst`로 **재정렬**(`:2996`) 후 `OnClickTileList(linkTiles)`(`:3006`) 호출.
- `OnClickTileList`(`GameController.cs:3068-3114`)는 루프에서 **두 타일 각각** `levelController.m_Dock.AddTile(tile, ...)`(`:3084`)를 호출.
- `Dock.AddTile`(`Dock.cs:1049`)의 `!tile.m_SelectedByHint` 블록(`:1067-1091`)은 "힌트 아닌 사용자 수집" 조건이며, link의 두 타일 모두 이 조건을 통과 → `MmpEvents.RegisterTileClick()`(`:1091`)이 **1탭당 2회** 호출됨(코드 Read로 직접 확인, 추정 아님).
- 결론: 문서 §8-2가 "확인 필요"로 남긴 질문("짝 타일이 AddTile을 한 번 더 `!m_SelectedByHint`로 통과하는지")은 **통과함**으로 확정. §8-2 정의(픽=이 훅)를 보정 없이 그대로 쓰면 link 1탭=2픽으로 집계되어 명세(1탭=1픽) 위반.
- 추가 주의: `linkTiles`가 매치 우선 정렬로 재배열되므로, 루프 0번째가 원래 탭한 타일이 아닐 수 있음. "탭한 타일 기준" 분류(`pick_new`/`pick_match`)를 하려면 정렬 전 `tile` 파라미터(원래 탭 대상)를 별도로 식별·고정해야 함.
- 구현 권장: `picks`/분류 집계 훅을 `Dock.AddTile` 내부가 아니라 `OnClickTileWithCheck`(또는 `OnClickTile`/`OnClickTileList` 호출 1회당 1픽 보장하는 래퍼)로 옮기거나, `OnClickTileList` 루프에 "link 쌍의 2번째 호출은 picks 증가 생략, occ/cap 스냅샷·기믹 집계(폭탄/풀/열쇠/컨테이너)는 그대로 수행" 가드 추가. 분류는 정렬 전 원래 탭 타일 기준.
- 봇 정의 일치 여부: 봇(`bot_simulator.py:1920 state.moves_used += 1`)은 link 쌍을 Move 1개로 처리(`linked_tiles` 동반, `:588, 2209-2233`) → **보정 없이는 게임 쪽이 봇보다 2배로 집계되어 불일치**. 위 보정 적용 시 일치.

**2. 잠금 칸(key/lock) 해제 위치 — 확인됨(독 잠금 슬롯만 존재, 보드 잠금 타일 없음)**

- 독 잠금 슬롯: `DockSlot.isLock`(`DockSlot.cs:15`), 해제 `DockSlot.SetUnlockTile(bool playFx)`(`:296,298`). 트리거는 `Dock.UnLockSlot()`(`Dock.cs:900-912`, `lockedDockSlots`에서 역순 pop) — 키 타일(`CTile.isKeyTile`, `DB_Level.cs:234`, `t16`/`"key"`) 3매치 완성 시 매치 애니메이션 종료 콜백 `Dock.RemoveRoutineTiles`(`Dock.cs:1826`) 안 `if (keyTileCount>=3) UnLockSlot();`(`:1964-1966`)에서 호출. `key_unlock` 훅 후보 = 이 지점(비동기 콜백이므로 호출 당시 누적 `picks` 값을 그대로 기록하면 "첫 해제 픽 순번"이 됨).
- 보드 잠금 타일: `KeyGimmick`/`TileLock` 등 별도 클래스 **없음**(grep 전수 확인). 열쇠(t16)는 일반 보드 타일처럼 집는 타일이고, "잠겨서 못 집는" 대상은 Dock 슬롯뿐 — 문서 §7-5·§8-7의 "확인 필요"는 **해소**: 이 코드베이스에 보드 잠금 타일 기믹 없음.
- `min_free`/`cap` 반영: `Dock.CurMaxSlotCount`(`Dock.cs:512`) → `CurDockCountExceptAdditionalMatchSlotAndLock`(`:491-508`)에서 `dockSlots[i].isLock`인 슬롯을 제외(`:500`) — §8-2 cap 정의와 일치, 확인됨.
- 봇 정의 일치 여부: 봇 `unlock_tile`(`bot_simulator.py:1096-1112`)의 "독 잠금칸 수 첫 감소 턴" 개념과 동일 축. 다중 잠금 슬롯 맵에서 "첫 해제"는 양쪽 다 1번째 키 3매치 시점이라 일치할 것으로 **추정**(맵별 `totalLockCount` 분포별 교차검증은 안 함, 범위 밖).

**3. 컨테이너(스택/craft) 출신 표식 — 확인됨(이미 존재, 신규 플래그 불필요)**

- `Tile`에 `isStackTile`(`Tile.cs:42`), `isCraftTile`(`Tile.cs:44`), `stackIndex`(`:52`) 필드가 이미 있고 `Tile.Init(cTile, isStackTile)`(`:491,630`)에서 설정되며, 피킹·해제 로직(`:1272-1427`)에서 계속 참조됨. 즉 픽 시점에 `tile.isStackTile || tile.isCraftTile`로 컨테이너 출신 여부를 바로 판정 가능 — 문서 §8-7 "확인 필요"(스폰 시 표식 추가 필요할 수도)는 **해소**: 신규 표식 불필요.
- `cont_first` 훅 후보: `Dock.AddTile`(`Dock.cs:1049`) 진입 시 전달된 `tile` 파라미터의 `isStackTile`/`isCraftTile` 검사 — 1번 항목의 link 보정과 같은 지점에서 함께 처리 가능.
- 봇 정의 일치 여부: 봇 trace `kind() in {stack, craft_emitted}`(`bot_dock_trace_20261026.py:19-25`)와 개념적으로 동일. 단 봇의 `craft_emitted`가 "배출 후"만 가리키는지, 게임의 `isCraftTile=true`가 craft 스택 전체(배출 전 포함)에 항상 true인지 교차 코드 대조는 안 함 — 피킹 가능한 타일만 `AddTile`에 도달하므로 실질적으로는 일치할 것으로 **추정**.

**추가 항목(파일:줄만, 요청 범위)**

- `danger_picks` 기준(free ≤ 2) = 게임 경고 UI 임계와 동일 상수: `Dock.cs:85 _bufferDangerThreshold = 2`, 판정 `Dock.cs:1259-1265 IsBufferDanger()`. 확인됨 — §8-2 기술과 일치.
- `bomb_left_min`: 카운트 조작 `TileEffect.cs:1364 AddBombCount` / `:1408 CheckBombCount`, 감소 호출 지점 `TileEffect.cs:1061 AddBombCount(-1)`. 확인됨.
- `grass_first`/`grass_left`: `TileEffect.cs:965-975`(`grassEffectRemainCount--` 및 `GrassAnimState` 전환). 확인됨 — §8-5 삭제 사유("풀 고립 판정은 실패 순간에만")와 별개로, 단순 감소 카운터는 매 턴 호출 경로에 있어 비용 우려 없음.
- `seg_boost`: 카운터 `MmpEvents.cs:1234 BoostersUsedThisRun{get;}`, 증가 `:1474 BoostersUsedThisRun++`, 리셋 `:1453`. 확인됨(카운터 존재). 단 §3 P2가 인용한 호출처 `Item.cs:258`는 이번 조사에서 실제 `ApplyUse`가 `Item.cs:416`(여러 `PayMode` 분기에서 호출, `:318/322/340`)로 확인돼 **줄 번호 드리프트** 있음 — §3은 이번 세션 수정 범위 밖이라 여기만 기록.
- `seg_end`: `GameController.cs:1395 OnLevelFailed`, 실패 사유 등록 `:1429 RegisterFailReason` 호출. `FailReason` enum은 `UIFailReason.cs:18`에 `Normal, Ice, Grass, Chain, Grass_CantRevive, Chain_CantRevive, Bomb, TimeOver` 8종으로 §8-3 표와 **정확히 일치**(확인됨).

## 9. 게임 구현 인계 (Codex)

> 이 절이 게임 쪽 구현자가 바로 작업을 시작할 수 있는 최종 요약이다. §8 전체(정의·훅·QA·결정)를 압축했을 뿐 새 결정은 없다 — 모순 시 §8-2/§8-3/§8-7/§8-11이 원본.

### 9-1. 이벤트 요약

- **이벤트명**: `level_summary` (AF=Firebase 동일명, `AnalyticsEventMap` 신규 매핑 불필요).
- **발화 시점**: 판당 **1건**, **첫 종료(terminal) 사건** 시점에만 — 클리어(`GameController.OnLevelClear`, `:1141`), 첫 `OnLevelFailed`(`:1395`, 부활 팝업 전), 또는 실패 전 포기(`DdaRuntime.OnQuit`). 부활 후 구간은 집계하지 않음(동결). `DdaRuntime.SendPlay`(`Dda/DdaRuntime.cs:490`) 직후 같은 호출에서 `MmpEvents.Log("level_summary", p)`를 별도 try/catch로 호출 — 계측 예외가 정책 경로를 깨지 않게.
- **조인 키**: `heart_run_id`(`dda_play`와 동일 값, `HeartRunPolicy.CurrentRunId`) — `level_fail`엔 run_id가 없어 이 이벤트가 조인의 유일한 다리.
- **중복 방지**: `dda_play`의 `Active()` → 정산 게이트 안에서만 보내므로 판당 최대 1건. 재진입/다시하기는 `ResetRunMetrics`(`MmpEvents.cs:1449`, 리플레이 `ResetRunMetricsForReplay :1428`)에서 값이 리셋되지만 **부활 중엔 리셋 금지**(동결 플래그로만 구분).
- **미발화**: abandon(앱 강종)은 보내지 않음 — 분석에서 "dda_play 있는데 level_summary 없음"=abandon/유실로 처리.

### 9-2. 파라미터 최종표 (22개 = 공통 6 + 전용 16)

| # | 이름 | 타입 | 정의(수식) | 집계 시점 | 기믹 없을 때 | 훅 위치(file:line) |
|---|---|---|---|---|---|---|
| 공1 | `level` | int | `dda_play.level`과 같은 값(정식 N/무한 RunLevel) | 송신 | — | 공통 주입 `MmpEvents.InjectCommonParams`(`MmpEvents.cs:134-149`) + `SetIfAbsent`로 직접 설정(dda_play와 동일, `DdaRuntime.cs:490` 호출부) |
| 공2 | `surface` | — | 공통 자동 | 송신 | — | `MmpEvents.cs:134-149` |
| 공3 | `elapsed_d` | — | 공통 자동 | 송신 | — | `MmpEvents.cs:134-149` |
| 공4 | `gold` | — | 공통 자동 | 송신 | — | `MmpEvents.cs:134-149` |
| 공5 | `star` | — | 공통 자동 | 송신 | — | `MmpEvents.cs:134-149` |
| 공6 | `energy` | — | 공통 자동 | 송신 | — | `MmpEvents.cs:134-149` |
| 1 | `heart_run_id` | str32 | 판 ID, `HeartRunPolicy.CurrentRunId` (dda_play와 동일) | 송신 | — | `DdaRuntime.cs:490` 호출부에서 직접 세팅(하트 정책 공통주입 대상 아님, `InjectHeartPolicyParams`는 level_summary 미포함 `:152-155`) |
| 2 | `sv` | int | 스키마 버전, v1=`1` | 상수 | — | 리터럴(코드 생성 시 고정값) |
| 3 | `seg_end` | enum | `clear`/`quit`/`FailReason`(`Normal,Ice,Grass,Chain,Grass_CantRevive,Chain_CantRevive,Bomb,TimeOver`) | 구간 끝 | — | 실패 `GameController.cs:1395 OnLevelFailed` → `:1429 RegisterFailReason`, enum `UIFailReason.cs:18`; 클리어 `GameController.cs:1141 OnLevelClear`; 포기 `DdaRuntime.OnQuit` |
| 4 | `picks` | int | 구간 픽 수(1탭=1픽, link 보정 필수) | 구간 끝 | — | `GameController.OnClickTileWithCheck`(`:2963`)/`OnClickTileList`(`:3068-3114`) 호출 1회당 +1, **또는** `Dock.AddTile`(`:1049`) 중 link 쌍 2번째 호출 가드 |
| 5 | `seg_boost` | int | 구간 내 부스터 사용 수(전 종류) | 구간 끝 | — | `MmpEvents.BoostersUsedThisRun`(`:1234`, 증가 `:1474`, 리셋 `:1453`) |
| 6 | `pick_new` | int | Σ 픽[독 내 같은 타입 n=0] | 매 픽 | — | `Dock.AddTile`의 `existingCount`(`Dock.cs:1076`)==0, **재정렬 전 원래 탭 타일 기준** |
| 7 | `pick_match` | int | Σ 픽[n=2] | 매 픽 | — | 동일 위치, `existingCount`==2 |
| 8 | `min_free` | int | min(cap−occ), 픽 0회면 −1 | 매 픽 직전 | — | cap=`Dock.CurMaxSlotCount`(`:512`→`:491-508`, 잠금 제외 `:500`), occ=`Dock.GetTileCountExceptOnMatchNew()`(`:3730`) |
| 9 | `danger_picks` | int | Σ 픽[free≤2] | 매 픽 직전 | — | 상수 2=`_bufferDangerThreshold`(`Dock.cs:85`), 판정 `IsBufferDanger()`(`:1259-1265`) |
| 10 | `danger_tail` | int | 구간 끝부터 역산 연속 [free≤2] 픽 수 | 구간 끝 | — | 위 danger 판정 재사용, 꼬리 카운트 |
| 11 | `end_pairs` | int | 구간 끝 독에서 같은 타입 정확히 2장인 타입 수 | 구간 끝 | — | 종료 시점 독 스캔(onMatch 제외, `Dock.GetTileCountExceptOnMatchNew` 기준 집계) |
| 12 | `bomb_left_min` | int | 폭탄 해제/폭발 순간 남은 카운트 최소값 | 해제/폭발 순간 | −1(없음)/−2(미해제·미폭발) | `TileEffect.AddBombCount`(`:1364`)/`CheckBombCount`(`:1408`), 감소 호출 `:1061 AddBombCount(-1)` |
| 13 | `grass_first` | int | 첫 풀 1겹 제거 픽 순번 | 첫 발생 | −1(없음)/0(미발생) | `TileEffect.cs:965-975` `grassEffectRemainCount--` |
| 14 | `grass_left` | int | 구간 끝 미제거 풀 겹 합 | 구간 끝 | −1 | 동일 위치, 종료 시 보드 스캔 |
| 15 | `key_unlock` | int | 첫 잠금 칸 해제 픽 순번 | 첫 발생 | −1(없음)/0(미발생) | `Dock.UnLockSlot()`(`:900-912`), 트리거 `RemoveRoutineTiles`의 `keyTileCount>=3` 분기(`:1964-1966`) |
| 16 | `cont_first` | int | 스택/craft 배출 출신 타일 첫 픽 순번 | 첫 발생 | −1(없음)/0(미발생) | `Dock.AddTile`(`:1049`) 진입 시 `tile.isStackTile`(`Tile.cs:42`)/`isCraftTile`(`:44`) 첫 true |

- 범위·카디널리티·값 100자 제한은 §8-3 하단 설명과 동일(전부 정수/짧은 enum 문자열).
- 예산: 전용16+공통6=22/25, 여유 3(§8-4, v2 예약).

### 9-3. 전송 정책

1. **1단계(선행 필수)**: QA 빌드 `MMP_DEBUG_ON` 진단 경로로만 `[MmpQA]` 로컬 로그 출력 — 운영 SDK 전송 금지. 페이로드 포맷·값 범위(§8-3 범위표)·100자 제한·키 수(22) 확인.
2. **운영 전송**: 1단계 검증 통과 + **별도 승인** 후에만 `SendEnabled`/`MMP_EVENTS_ON && !UNITY_EDITOR` 가드로 활성화(§4/§6 기존 패턴). 이번 문서는 운영 전송을 승인하지 않음 — 승인은 게임 담당·분석 담당 합의 별도 트랙.
3. **한도**: AF/Firebase 파라미터 25개 한도 내 22 사용, 여유 3(v2 예약: `link_pick_free`/부활 후 구간 요약/`cont_run` 후보, §8-9-4).
4. **카탈로그 동기화**: `.context/build_mmp_csv.py` 신규 행 추가 후 재생성(CSV 수동 편집 금지), `DESIGN_MMP_EVENTS.md`/`HOOK_MAP` 갱신, `mmp_contract_check` ERROR 0.

### 9-4. QA 체크리스트

1. 판당 1건: clear/최종실패/포기 각 1건, abandon 0건, 다시하기·재진입 후 이전 값 누적 없음.
2. **link 탭=1픽 확인(중요, §8-11-1 확정 사항)**: link 1탭 발생 시 `RegisterTileClick`/`Dock.AddTile`이 내부적으로 2회 불려도 `picks`는 +1만 되는지 로그로 직접 확인(가드 미적용 시 2배 집계 — 반드시 QA에서 잡아야 함). 분류(`pick_new`/`pick_match`)가 재정렬 전 원래 탭 타일 기준인지도 확인.
3. 부활: 첫 실패 후 부활→클리어 판에서 `seg_end`=첫 실패 사유 유지, `picks`가 부활 후 증가하지 않음(동결 확인).
4. 재시도(다시하기): 새 `heart_run_id`로 완전히 새 판 취급, 이전 값 이어받지 않음.
5. 무한 판: 송신되고 `dda_play.is_infinite=1`과 같은 `heart_run_id`로 조인됨.
6. 테스트판 제외: TestPlay·수동비교·event1·`settled_replay`에서는 `level_summary` 미발화(= `dda_play` 대상 범위와 동일, `DdaRuntime.Active()` 가드 확인).
7. 힌트 부스터·자동수집·undo가 `picks` 불변.
8. 값 범위: §8-3/§9-2 범위 위반 0, `pick_new + pick_match ≤ picks`, `danger_tail ≤ danger_picks ≤ picks`.
9. 기믹 없음 맵에서 `bomb_left_min`/`grass_first`/`grass_left`/`key_unlock`/`cont_first` = −1, 있는 맵에서 −1 아님.
10. **잠금 슬롯 해제 시 `key_unlock` 기록**: 키 타일 3매치 완성 → `Dock.UnLockSlot` 호출 프레임에서 그 시점 누적 `picks`가 `key_unlock`에 정확히 기록되는지(비동기 매치 애니메이션 종료 콜백 타이밍 주의).
11. 키 수 22, 값 100자 이하(`[MmpQA] params=22`).

### 9-5. 남은 결정 (§7 중 미해결) — 권장안

1. **중간 실패(부활 가능) 포함 여부**: §8 결론은 "구간=첫 종료 사건에서 동결"이라 중간 실패 자체가 별도 레코드로 가지 않는다 — `seg_end`는 항상 **첫** 실패 사유를 고정값으로 담고, 최종 결과(클리어/포기 등)는 `dda_play.result`로 조인해 구분한다. **권장**: 이 결론 유지. 추가로 "부활 후 독 관리"를 보고 싶다는 라이브옵스 요청(§8-6-1)은 v2 여유 슬롯 후보로만 남긴다.
2. **무한(`infinity_`) 판 포함 여부**: §8-9-1 결론은 **포함**(dda_play와 동일 범위, `is_infinite` 조인으로 분리 가능). **권장**: 유지 — 제외할 경우 무한 모드 난이도 비교 데이터가 통째로 빠지는 손실이 더 크다.
3. **분석 성공 기준 임계값(KS 거리/분위수 차이 허용범위)**: 파일럿 데이터 없이 사전 확정 불가. **권장**: 1단계 QA 로그 + 2단계 소수 운영 샘플 확보 후, `26_bot_v24.md`가 쓴 "클리어 MAE/ρ/범위적중" 틀을 그대로 가져와 P0 8개 지표 중 과반 통과를 1차 기준으로 시범 설정 — 확정은 데이터 보고 나서.

### 9-6. 봇 쪽 대응

- 이 문서가 정의한 16개 전용 파라미터(§9-2)와 **같은 수식**으로 산출하는 **봇 쪽 판 단위 요약 함수**는 이 세션의 범위 밖이다 — **맵 에디터(이 저장소) 봇 담당이 별도로 구현할 예정**(§8-8-2 "판 단위 요약 함수 1개 추가 예정 — 별도 작업"). 게임 구현자는 봇 코드를 기다리지 않고 §9-2 훅대로 게임 쪽만 구현하면 된다.
- 봇 쪽 구현 시 참조할 기존 트레이스 스크립트: `backend/app/core/bot_simulator.py`(`moves_used`, `will_match`, `unlock_tile` 등), `backend/scripts/bot_dock_trace_20261026.py`, `backend/scripts/bot_hazard_trace_20261026.py` — 이미 턴별로 같은 개념의 필드를 산출 중이라 판 단위 요약(최대값·첫발생·꼬리카운트)만 뽑으면 된다(§5-1, §8-8-2).

### 9-7. 정의 확정 (2026-10-27)

> 봇 판 요약 도구 작업에서 나온 정의 분기 7건을 확정했다(마더 지시). 게임 구현(sp_meowsgarden 1.1.2.90 `LevelSummaryMetrics`)에 반영됨. 봇 쪽은 이 표에 맞춰 매핑한다.

| # | 항목 | 확정 정의 | 게임 구현 |
|---|---|---|---|
| 1 | link 픽 | 탭 1회 = 1픽. `pick_new`/`pick_match`·`cont_first`는 **탭한 원래 타일 기준**, 짝 타일은 분류·`cont_first`에 넣지 않음 | `OnClickTileWithCheck` 탭 컨텍스트(`BeginTap`~`EndTap`), 2번째 `AddTile`은 picks·분류·독 압박·`cont_first` 제외. 분류 n은 재정렬 전 원래 타일 타입의 독 내 수 |
| 2 | `bomb_left_min` | 짝 타일 포함, **출처(탭/짝/자동수집/힌트) 무관**, 실제로 독에 수집된 폭탄은 해제로 셈(그 순간 남은 카운트). 폭발 = 0. 힌트 사용 판은 `seg_boost>0`으로 분석에서 걸러 별도 구분 없음 | `Dock.AddTile` 콤보 블록 뒤 `OnTileCollected`(힌트 포함 전 경로), 폭발 `TileEffect.AddBombCount` 결과 ≤0 |
| 3 | `key_unlock` 기록 시점 | 매치 애니 종료 콜백 시각의 picks가 아니라 **해제를 일으킨 매치(키 3장째)를 만든 픽의 순번**을 저장해 두었다가 기록 — 빠른 연속 탭 k+1 밀림 방지 | 키 타일 `AddTile`에서 독 내 키 2장(existingCount==2)이면 그 탭 순번 저장 → `Dock.UnLockSlot`에서 기록. 매치 픽이 구간 안이면 애니 도중 동결돼도 송신 전까지 기록 |
| 4 | 같은 픽에서 종료 사건이 겹칠 때 | 게임의 실제 `FailReason` 판정을 그대로 `seg_end`에 보냄 | 아래 우선순위. 봇 매핑은 봇 담당이 맞춤 |
| 5 | 기믹 유무(−1) | 보드 타일 + **스택·craft 내용물까지 포함**, 레벨 시작 시 판정(봇과 동일) | `BeginRun`(=`BeginComboRun`, 맵 데이터 확정·스폰 직후)에서 `LevelDB.xLayerList` 전 타일 + `xTileStackInfo.stackCTileList` 스캔: 폭탄/풀 = 효과, 컨테이너 = stack/craft 루트 또는 내용물 존재. **잠금(열쇠) = 실제 독 잠금 칸 수 > 0**(2026-10-27 보정, 아래 5-a) |
| 6 | `Grass_CantRevive`/`Chain_CantRevive` | `seg_end`에 게임 원값 그대로(분석에서 Grass/Chain으로 통합) | `failReason.ToString()` 그대로 |
| 7 | 무한·DDA 변형 판 | `heart_run_id`로 `dda_play` 조인해 맵(`level`·`is_infinite`)·변형(`dda_stage`·`dda_variant`) 식별. 추가 파라미터 없음 | `level`·`heart_run_id`는 같은 프레임 `dda_play` 페이로드 값 그대로 |

**5-a — 열쇠 기믹 유무 = 실제 잠금 칸 (2026-10-27 보정)**

- 판정: `Dock.SetLockSlot`(`TileGroup.AfterAllTileSpawnAnimEnd`, 판 시작 1회, 잠금 칸 수 = 그 시점 `c_KeyTileList.Count/3`) 직후 잠긴 슬롯 수 > 0이면 "있음", 0이면 `key_unlock = -1`. 맵의 `unlockTile`·키 타일 존재는 쓰지 않는다 — 게임이 실제로 만든 잠금 상태를 그대로 보낸다.
- 시점 관계: `SetLockSlot` 관측이 최종 판정(덮어씀). 그 전에 픽이 있으면(스폰 애니 중 입력 등 예외) 첫 픽 직전 보조 스캔이 **그 순간 독 잠금 칸**으로 임시 판정하고, 이후 `SetLockSlot`이 오면 교체. 픽 0회 동결 시에도 같은 규칙. 실제 해제(`Dock.UnLockSlot`)가 관측되면 "있음" 확정.
- **`unlockTile`과 실제 잠금 수가 다른 판(분석 구분 규칙, 파라미터 추가 없음 — 22개 유지)**: 분석에서 `level_summary.level`(+ `heart_run_id` → `dda_play.dda_variant`로 변형 맵)의 레벨 행 `unlockTile`을 조인한다. `unlockTile>0`인데 `key_unlock=-1`이면 **"잠금 미설정 판"** = 게임 쪽 잠금 생성 불일치(예: 열쇠 일부가 `c_KeyTileList`에서 누락 → `/3` 내림 0) → 봇 key 비교 표본에서 제외하고 게임 버그 후보로 별도 집계. `unlockTile=0`인데 `key_unlock≠-1`도 같은 불일치로 분류. 둘이 일치하는 판만 `key_unlock` 분포 비교에 쓴다. 잠금 칸이 2개 이상인 맵에서 개수 차이는 이 이벤트로 구분 불가(첫 해제만 기록) — QA RT-MMP-LEVEL-SUMMARY.10 ⓪으로 확인.

**4번 — 게임 실패 판정 우선순위(코드 확인, sp_meowsgarden 현재 작업 트리)**

- `GameController.OnLevelFailed`는 `gameState == GameOver` 재진입 가드(`GameController.cs` OnLevelFailed 첫부분)로 **먼저 호출된 사유 1개만** 확정한다. `seg_end`도 같은 지점(`RegisterFailReason` 직후)에서 동결되므로 게임 판정과 항상 같다.
- 한 탭 안의 호출 순서(`GameController.OnClickTile`): ① `Dock.AddTile` 끝의 `CheckGameFail` → `IsGameOver()`가 **폭탄(카운트 ≤0 미픽 폭탄, `TileGroup.IsBombTileActive`)을 먼저** 검사해 `Bomb`, 아니면 독 가득이면 `Normal`(`Dock.cs` CheckGameFail/IsGameOver) → ② 이어서 `TileGroup.CheckCantUncoverTileExist`(보드 타일 리스트 순서로 첫 발견: Grass/Grass_CantRevive, Chain/Chain_CantRevive, Ice). 따라서 **Bomb > Normal > (Grass·Chain·Ice 중 보드 순서상 첫 타일)**. CantRevive 구분은 독에 탈출용 인접 타일이 있는지로 결정.
- link 탭(`OnClickTileList`)은 마지막 타일 `AddTile`에서만 `CheckGameFail`(첫 타일은 `checkOnChangeTileList=false`), `CheckCantUncover`는 link 경로에서 호출되지 않음.
- `TimeOver`는 타이머 비동기(`LevelTimer`) — 탭과 겹치면 먼저 도달한 쪽.
- 클리어는 매치 애니 종료 시점이라 같은 탭 실패가 먼저 확정되면 `OnLevelFailed`가 GameOver로 바꾼다. 클리어 판정 후 실패 호출은 `isGameActive`/GameOver 가드로 무시.

### 9-8. 검증 계획 (등록만 — 실행은 별도 승인)

> 사용자 요구: 계측 추가 후 에뮬레이터 QA 자동화나 테스트 플레이로 원하는 항목이 제대로 수집되는지 확인. 게임 QA 정본 `sp_meowsgarden/Assets/99.Docs/claudedocs/nodes/TEST_EDITOR_RUNTIME_CHECKLIST.md` **RT-MMP-LEVEL-SUMMARY.01~14**에 같은 내용 등록. 이번 작업은 계획·등록만 했고 컴파일·play·빌드·에뮬레이터는 실행하지 않았다.

**대상 레벨 후보** — 봇 캐시 `backend/data/pv_sandbox/af_calibration/bot_compare_L32_500/prep.json`(2026-10-14 스냅샷, L32~500)에서 다른 기믹이 가장 적은 맵을 뽑음. **실행 전 현재 서버 맵으로 다시 확인**(맵 갱신 가능). 전체 클리어 기대 picks = 보드 타일 + 컨테이너 내용물 − link 표시 타일 수(link 1탭=2장), 부스터·자동수집 0 기준.

| 기믹 | 후보 | 기대 picks(전체 클리어) | 비고 |
|---|---|---|---|
| 없음 | L35 · L55 · L85 | 36 | 자동수집 0, 타이머 없음 |
| link | L199 · L115 · L135 | 9 · 118 · 118 | L199는 18장 중 9장 link 표시 → 2배 집계면 18 |
| 폭탄 | L297(+ice) · L296(+craft) | 72 · 45 | 초기 카운트 L297=5·5·4·4, L296=3·3 |
| 풀 | L184 · L498 | 39 · 54 | 다른 기믹 없음 |
| 잠금 칸(열쇠) | L138(+stack) | 72 | `unlockTile=1`(키 3장 → 잠금 칸 1) |
| 스택 | L33 · L37 | 51(L33) | 다른 기믹 없음 |
| craft | L32 · L34 | 48(L32) | 다른 기믹 없음 |
| 타이머 | L341 | — | TimeOver 확인용(+link·stack) |

**시나리오별 기대값** (공통: `params=22`, `sv=1`, 같은 프레임 `dda_play` 1건과 `heart_run_id`·`level` 동일, 관계식 `pick_new+pick_match ≤ picks`, `danger_tail ≤ danger_picks ≤ picks`)

| # | 시나리오 | 맵 | 기대값 |
|---|---|---|---|
| S01 | 기믹 없음 클리어(부스터 0) | L35 | `seg_end=clear`, `picks=36`, `seg_boost=0`, `end_pairs=0`, `bomb_left_min=grass_first=grass_left=key_unlock=cont_first=-1`, `min_free` 0..7 |
| S02 | 독 가득 실패(서로 다른 타입만 집기) | L35 | `seg_end=Normal`, `min_free=1`(마지막 픽 직전 여유 1칸 — 7칸이 차는 픽에서 실패하므로 0이 아닌 1이 정상, 0은 매치 대기 중 연속 탭일 때만), `danger_tail ≥ 2`, `danger_picks ≥ danger_tail`, `pick_new` 대부분, `end_pairs` = 실패 독의 2장 타입 수 |
| S03 | 포기(실패 전) | L35 | `seg_end=quit`, `picks`=포기까지 탭 수 |
| S04 | 재도전(실패창 다시하기) | L35 | 판마다 1건, `heart_run_id` 서로 다름, 2판 값이 1판 미누적 |
| S05 | 부활 후 이어서 클리어 | L35 | 1건만(클리어 시점), `seg_end=Normal`, `picks`=첫 실패까지 탭 수, 부활 후 값 미반영. `dda_play.result=clear revive_cnt=1` |
| S06 | 부스터 사용(힌트·되돌리기·셔플 각 1) | L35 | `seg_boost ≥ 3`, `picks`=유저 탭 수(힌트 수집·undo 미반영) |
| S07 | link 맵 클리어 | L199 | `picks=9`(18이면 link 가드 실패), 원래 탭 타일 기준 분류 |
| S08a | 폭탄 집어서 해제 | L297 | `bomb_left_min` = 집은 순간 남은 카운트 최소(1..5) |
| S08b | 폭탄 폭발 실패 | L297 | `seg_end=Bomb`, `bomb_left_min=0` |
| S08c | 폭탄 미처리 포기(첫 탭 전 포기) | L297 | `bomb_left_min=-2` |
| S09 | 풀 맵 클리어 / 풀 실패 | L184 | 클리어: `grass_first ≥ 1`, `grass_left=0`. 실패: `seg_end ∈ {Grass, Grass_CantRevive}`, `grass_left ≥ 1` |
| S10 | 잠금 칸 해제 | L138 | `key_unlock` = 키 3장째를 집은 탭 순번 k(매치 애니 중 빠르게 1~2탭 더 해도 k). 해제 전 포기 = 0 |
| S11 | 스택/craft 첫 파기 | L33 · L32 | `cont_first` = 컨테이너 출신 타일을 처음 탭한 순번, 컨테이너 타일 미탭 포기 = 0 |
| S12 | 무한 판 | 무한 구간 QA 계정 | 송신, `dda_play.is_infinite=1`과 조인 |
| S13 | 제외 판 | TestPlay·수동비교·event1·클리어한 레벨 재플레이 | `level_summary` 0건(`dda_play`도 0) |
| S14 | DDA 변형 판 | 에디터 DDA 테스트 단계 ±1 | `dda_play.dda_variant ≠ orig`인 판과 `heart_run_id` 조인, `picks` = 그 변형 맵 기준 |
| S15 | 타이머 초과 | L341 | `seg_end=TimeOver` |

**자동화 범위**

1. 에디터 테스트 플레이(컴파일 1회 승인 후): 콘솔 `[MmpQA] ... event=level_summary ... params=22 {k=v ...}` 수집(`unity-cli console --lines 500 --filter all | grep "event=level_summary"`). 에디터는 `SP/DDA 단계 이동 테스트/1 로비에서 테스트 켜기`가 있어야 `DdaRuntime.Active()`라 발송된다.
2. 자동 플레이(기존 하네스 확장 — 신규 Verify 헬퍼 추가 승인 필요): 기존 `InGameVerify.StartLevel`은 `StartGame(..., testPlay:true)`라 **제외 판(발송 0)** → 실제 로비 입장 경로(`LobbyUIController.EnterGame`, 하트 소모) 헬퍼가 필요. 기존 `InGameVerify.DoMatch`는 `GameController.OnClickTile` 직접 호출이라 탭 컨텍스트를 우회한다(link 2배 집계 재현용으로만 유효) → 플레이 지표 검증은 **`OnClickTileWithCheck`(실제 입력 경로)** 로 탭하는 헬퍼 사용. 정책: 클리어용 그리디(독 내 2장 타입 우선 → 1장 → 새 타입), 독 가득용(서로 다른 타입만), 기믹 시나리오용(폭탄·키·컨테이너 지정 탭). 헬퍼가 직접 센 탭 수·분류를 기대값으로 로그와 대조.
3. 테스트 콘솔 즉시 클리어/실패(`DebugTestTabController.OnForceGameClear/OnForceGameFail` → `OnLevelClear`/`OnLevelFailed`): **이벤트 발송·키 22개·형식·`seg_end` 확인용으로만**. picks 등 플레이 지표는 그때까지 실제로 한 탭만 반영하므로 실제 입력 경로 판으로 검증한다.
4. 에뮬레이터(QA 빌드 설치 후): Android QA 프로필(`EnableMmpDebug=1`, 이벤트 OFF) → `adb logcat -v time -s Unity | grep "event=level_summary"`로 수집, 같은 기대값 표로 대조. 이벤트 ON+디버그 빌드면 `stage=GATED_UNAPPROVED`·AF/FB `SDK_CALL` 줄 없음 확인. 결과는 **실제 손 터치 판 / adb input 자동 터치 판**을 구분 기록. 에뮬레이터 PASS ≠ 실기·수신 완료.
5. 로그 파서(제안만, 작성은 승인 후): `sp_meowsgarden/tools/mmp_level_summary_check.py` — 입력 = Unity 콘솔/logcat 텍스트(stdin 또는 파일). `[MmpQA] ... event=(level_summary|dda_play) ... params=N {k=v ...}` 줄을 파싱해 `heart_run_id`로 조인 → 관계식·범위·키 수·100자 검사 + 시나리오 기대값 JSON(`{"S07":{"level":199,"picks":9}}`) 대조 → PASS/FAIL 표 출력. 판 단위 CSV 내보내기(봇 요약 비교용) 옵션.

**필요한 승인** — ① Unity 컴파일 1회(공용 잠금) ② 에디터 play·공용 잠금·하트/재화 소모·QA 계정 진행도 조정(대상 레벨까지 진행 변경 = 데이터 변경) ③ 에디터 전용 Verify 헬퍼 + `tools/unity_verify_level_summary.sh` 추가 ④ 로그 파서 작성 ⑤ QA 빌드 생성·에뮬레이터 설치·실행 ⑥ 무한 구간·event1 QA 계정 사용.

### 9-9. 발송 조건 정정 — DDA 독립 (2026-10-27, 게임 1.1.2.94)

> §8-1·§9-1의 "dda_play 송신 직후·`DdaRuntime.Active()` 판과 동일 범위"를 정정한다. 에디터 QA에서 DDA 저장 상태 무효(`saved_lock_invalid`)로 `Active()`가 거짓이면 level_summary도 0건이 되는 것을 확인 → 사용자 승인으로 분리.

- **발송**: 하트 run 종료 기준 판당 1건. 클리어 = `GameController.OnLevelClear`(`HeartRunPolicy.MarkCleared` 직후 — Cleared run은 `heart_run_end`를 내지 않음), 최종 실패·포기 = `HeartRunPolicy.ReportTerminalOnce`(`heart_run_end`와 같은 거래 1회 가드 안). 하트 정산 사유 `quit`/`quit_lobby` → `seg_end=quit`(미동결 시), 그 외 → 첫 실패 사유.
- **대상**: 하트 run이 있는 정식(`level_`)·무한(`infinity_`) 판 전부 — 운영 DDA OFF, DDA 범위 밖(L101+ 등), DDA 저장 무효 판도 포함. 제외 = TestPlay(빈 run id)·수동비교·event1(구분자)·하트 run 없는 판. 부팅 복구 정산(abandon)은 미발화(집계기 미가동, run id 불일치).
- **조인**: `heart_run_id` = 하트 run id(판 시작 시점 `HeartRunPolicy.CurrentRunId`, 정산 run id와 일치해야 발송). `level_start`·`heart_run_end`와 항상 조인 가능. `dda_play`는 **DDA가 활성인 판에만** 존재 — 없으면 DDA 비활성/범위 밖 판으로 해석(변형 = 원본). §9-7 7번(무한·DDA 변형 식별)은 dda_play가 있는 판에 한정.
- **순서 변화**: 최종 실패·포기는 level_summary(하트 정산) → dda_play(DdaRuntime) 순, 클리어는 level_summary → dda_play(`OnClear`) 순. 분석은 순서에 의존하지 않는다.
- 파라미터 22개·정의·운영 전송 OFF는 그대로.

> **상태(2026-10-27)**: 게임 코드 구현 완료(sp_meowsgarden 1.1.2.90·.91·.94·.98 + DDA 옛 저장본 호환 1.1.2.95), 에디터 QA PASS 13/16 + .09 재검증 PASS, 외부 MMP 이벤트 시트 `level_summary` 행 사용자 입력 완료. 남은 것: .10 열쇠 해제 순번 k(수동 플레이)·.11 실수신(다음 배포 후 AF/Firebase 대시보드 확인)·.07 구간 내 undo·자동수집·.01 abandon. 별도 발송 게이트(`ProductionSendApproved`)는 1.1.2.100에서 제거 — 다른 MMP 이벤트와 동일 발송.
