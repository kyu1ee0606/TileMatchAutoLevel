# 04. 시드 변형(t0화 + 클라 시드 배정) 실행 계획 — 확정안

> ⚠️ **계획 문서. 코드 수정·맵 재생성·배치 파일 생성·업로드·커밋 없음.** 작성 2026-10-02 (env 기준), 작성 세션 "시드계획전문가".
> 근거: [00 계획 초안](./00_plan.md) · [01 클라](./01_client_findings.md) · [02 에디터 파이프라인](./02_editor_pipeline_findings.md) · [03 솔버/봇](./03_solver_bot_findings.md)
> 표기: **[사실]** = 코드·데이터로 확인(파일:줄 또는 노트 §) · **[제안]** = 계획·판단(미검증) · **[스캔]** = 이번 작성 중 읽기 전용 스캔(/tmp 스크립트, 실행 후 삭제).
> 경로 약어(02 머리말과 같음): `GEN` generator.py, `PD` ProductionDashboard/index.tsx, `TD` tileDistributor.ts, `GE` gameEngine.ts, `BS` bot_simulator.py, `GB` api/routes/gboost.py, `PS` api/routes/production_store.py, `CS` sp_meowsgarden/…/InGame/DB_Level.cs, `ZW` sp_meowsgarden/Assets/00.spComponents/zWellRandom.cs, `MC` core/mc_difficulty.py.

---

## 0. 확정 방향 요약 · 00 계획과 달라진 점

### 0-1. 사용자 확정 방향
1. 레벨 1~3: 고정 타일 배치. 변경 없음.
2. 레벨 32~: 맵을 **t0화**한다. 타일 종류만 비우고 위치·레이어·덮임·총 타일 수·기믹·제한시간·트레이·보상은 유지한다. 종류는 클라 `ShuffleEmptyTiles`가 `randSeed` 기준으로 배정한다(= 00 §4의 **대안 0**).
3. 레벨마다 시드 후보를 여러 개 평가해서 **base 1 + easy 2 + hard 2 = 5개**를 고른다.
4. 테스트는 **최신 레벨 세트의 사본**에서만 한다. 원본 LIVE 배치와 서버 데이터는 건드리지 않는다.
5. 전문가 검토로 계획을 확정한 뒤 진행한다.
- 레벨 4~31은 언급되지 않았다 → 이번 범위에서는 **현행 유지**(fixed_levels t0 + seed 0 = 매 판 랜덤, 02 §1-3). 미확정 질문 Q1에 남긴다.

### 0-2. 00 계획 추천과 달라진 점
| 항목 | 00 추천 | 04 확정 (사용자 방향 반영) |
|---|---|---|
| 변형 방식 | 기존 명시 맵은 base로 보존하고, 에디터가 명시 타입 배열로 구운 변형을 추가(0'·1). 대안 0은 대조군 | **대안 0을 본안으로 채택.** 32~ 맵을 t0화하고 클라가 seed로 배정한다. 대안 1(구조 인지 배정)과 0'(구워 넣기)는 이번 범위에서 뺀다 |
| 기존 맵 지위 | base = 현 명시 맵(불변) | 현 명시 맵은 **원본 배치에만 보존**(롤백 원천)한다. 새 base는 "t0 맵 + base seed"이며, 원 맵 난도에 가장 가까운 seed를 고른다(§A5) |
| 최우선 전제 | 해시 대조(구운 배열) | **에디터↔클라 분배 비트 일치**(00 T2~T5)가 P0 게이트다. 00 §8 E6 작업이 필수가 된다 |
| tier 수 | easy/base/hard 3단계(Q11 미정) | 5단계(e2·e1·b·h1·h2). 구분이 안 되면 축소 규칙을 적용한다(§A5-4) |
| 배포 계약 | `pv.variants[].types` | `pv.seeds[]`(seed·typesHash) + `randSeed`=base seed(§A6). 이번에는 사본 테스트 스키마만 정한다 |
| 00 T1(원래 배치 재현 불가) | t0화하지 않는 근거 | 수용한다. t0화하면 **모든 플레이어의 레벨이 바뀐다**는 점을 전제로 하고, base 근접 게이트(§A7 P1-G4)로 관리한다 |

---

## A. 실행 계획

### A1. 최신 레벨 세트 식별 · 사본 위치

**[사실]**
- 에디터 배치 인덱스(`backend/data/production/_index.json`)를 saved_at 순으로 보면 최신은 `batch_1789636723287_uulknmtej` "[LIVE 패치본 3차] 2026.9.17", 1530레벨, version 87, saved_at 1789699382(≈2026-09-18 11:43)이다. 그 앞은 2차 `batch_1789435856664_o0klei461`, 1차 `batch_1788744001053_wa5xrgv82`이다 [스캔].
- 게임 샤드의 `levelmap_etime` 최대값 2026-09-18 11:43:38은 3차 저장 시각과 같다. 다만 맵 34개가 다르다. 그중 33개는 2차 배치와 같고, Lv341은 2차·3차 어느 쪽과도 다르다(02 §3-3).
- 클라 `DB_Level.cs` 최종 커밋은 `b741f6a3`(2026-09-21)로, 샤드를 구운 뒤의 커밋이다 [스캔: git log]. 분배 코드 버전은 이 커밋을 기준으로 고정한다(§A3-5).

**[제안] 기준 원본**
- **사본 원천 = 에디터 LIVE 3차 배치 JSON**(`batch_1789636723287_uulknmtej.json`, 5.26MB). 평가 파이프라인(Python 봇/솔버)이 이 포맷(level_json + meta)을 직접 먹고, 원 맵의 난도 메타(`predicted_clear_rate` 등)도 들어 있기 때문이다.
- 샤드와 다른 34레벨에는 `shardMismatch=true` 표시를 하고 **P1·P2에서 제외**한다. P0에서 샤드와 구조(위치·레이어·효과·컨테이너 개수) 비교를 전수로 돌려 34개 외 구조 차이가 0인지 확인한다(P0-G4).
- 사본은 바이트 그대로 복사하고 원본의 sha256·batch_id·version·saved_at을 manifest에 기록한다. 원본 파일은 읽기만 한다.

**[제안] 사본 위치·이름 규칙 — 업로드·동기화 경로에 섞이지 않게**
- 위치: `backend/data/pv_sandbox/{copyId}/` (예: `pv_20261002_live3/`).
  - `source.json`(원본 사본, 불변) / `manifest.json` / `t0/levels.jsonl`(t0화 결과) / `eval/stage1.jsonl`, `eval/stage2.jsonl` / `selected.jsonl` / `golden/`
  - 파일 이름에 `batch_` 접두사를 쓰지 않는다. 최상위 구조도 `{batch, levels}`가 아니다(실수로 옮겨도 PS가 배치로 인식하지 못하게 하려는 것).
- 이 위치를 고른 근거 [사실]:
  - 서버 배치 목록 `list_batches`는 `backend/data/production` **한 디렉터리만** `os.listdir`로 훑는다(PS:25-27, 546-600). 프론트 `syncBidirectional`→`pullAllToLocal`은 이 목록을 IndexedDB로 당겨 온다(`productionServerSync.ts:163-171, 251-255`). 즉 production 디렉터리에 두면 UI에 노출되고 다시 push된다. **production 밖에 두면 UI와 동기화 양쪽에서 보이지 않는다.**
  - GameBoost 업로드는 프론트가 IndexedDB 레벨로 `POST /api/gboost/{board}/{id}`를 호출할 때만 일어난다(02 §3-1). 로컬 업로드는 `backend/app/storage/local_levels/`만 읽는다(GB:34). sandbox는 두 경로 어디에도 없다.
  - 추가 위험 [사실]: 프론트 `bakeFullBoard`는 레벨>3이고 randSeed>0이면 t0를 명시 ID로 **다시 굽는다**(PD:376-449, `ENABLE_INNER_TILE_BAKE=true` PD:314). t0화한 사본이 에디터 UI(생성·재생성·튜너 13곳)를 한 번이라도 거치면 t0가 사라진다. → **sandbox 맵은 에디터 UI에 import하지 않는다**(Python 스크립트 전용).
- `.gitignore`에 `backend/data/pv_sandbox/`를 추가한다(production이 이미 ignore 대상, `.gitignore:51-52`). golden 벡터만 `backend/tests/golden/pv_t0/`에 커밋 대상으로 둔다.

### A2. t0화 규칙

**[사실] 클라가 처리할 수 있는 형식**
- 보드 타일 `["t0", effect]`: `tileIDNum==0`이면 emptyTiles에 들어간다(CS:880-903, 01 §3-2). 효과는 스왑 대상이 아니므로 위치에 고정된다(CS:1271-1287).
- 스택/생성기 구포맷 `[cnt]`: `GetTileIDArr`가 전부 "t0"로 폴백한다(CS:197-211). 루트 위치에서 inner index 0(바닥)→n-1 순서로 끼워 넣는다. **LIVE 샤드에 70레벨이 이미 이 형식으로 배포돼 동작 중**이다(01 §4).
- 신포맷 `[cnt,"id0_id1…"]`은 개수가 맞으면 명시 id를 쓴다(CS:158-169). 내부 "t0"를 명시한 사례는 0건이다(01 §4).
- key: tileIDNum 16. empty 대상이 아니고, toAdd 계산(`GetEmptyTileList(true)`)에는 포함된다(CS:1123-1156).
- `unlockTile`=N이면 DistributeTiles가 마지막 N세트를 key(16)로 채운다(01 §3-3). 현재는 t0가 없어서 무효다.

**[스캔] LIVE 3차 32~1500 (1469레벨)**
- 컨테이너 명시 inner 1295개, key 보유 57레벨(그중 56레벨은 컨테이너 inner에 key), 총 타일(key 제외) %3≠0 **0건**.
- 저장된 useTileCount ≠ 재계산(inner 포함 명시 종류 수) 121레벨. 재계산 종류 수 분포: 12종 701 / 13종 392 / 11종 156 / 6종 81 / 10종 57 / 14종 39 / 기타 43.
- 링크 짝의 같은 타입 비율 100/726(14%) → 링크에 "같은 종류" 제약은 없다(t0화해도 계약 위반 아님).
- 레벨 내 종류별 세트 수 편차(최대−최소): 0→72, 1→900, 2→381, **≥3→116레벨**. 클라 DistributeTiles는 색상 버킷으로 고르게 나누므로(01 §3-3) 이 116레벨은 t0화 뒤 빈도 분포가 평탄해진다(§B 디자이너 D2).

**[제안] 규칙 (32~ 대상 레벨)**
| 대상 | 규칙 |
|---|---|
| 보드 일반 타일(t1~t15) | `t0`로 바꾸고 effect는 그대로 둔다(ice/chain/grass/bomb_N/curtain/teleporter/unknown/link_*/frog 포함) |
| 스택/생성기 inner | 명시 `[cnt,"…"]` → **구포맷 `[cnt]`**(live로 검증된 형식). 루트 id(`stack_e`/`craft_s` 등)와 cnt는 유지 |
| key 보유 57레벨 | **P1·P2 제외.** 이후 채택안: key 위치·개수는 명시로 유지하고, key가 섞인 inner는 `[cnt,"key_t0_t0"]` 신포맷, 행의 `unlockTile=0`(중복 key 생성 방지), 봇 잠금 수는 key 개수로 계산(03 §3 차이 해소). 클라 신포맷 inner "t0" 경로가 live 0건이므로 골든 케이스 필수(§A3) |
| useTileCount(기준값 `utc0`) | **원 맵 실제 명시 종류 수(보드 + 컨테이너 inner, key 제외)를 다시 계산한 값.** 저장값·GB 재계산값은 쓰지 않는다(GB는 필드 명시만 세고 inner 전용 타입을 빠뜨린다, GB:425-451). utc0는 1~15 범위로 강제한다 |
| GB 재계산과의 관계 | 전부 t0인 맵은 GB의 `actual_tile_types`가 비어서 **저장값을 그대로 출고**한다(GB:444). 저장값이 없으면 기본 **6**이 되므로(GB:443) `useTileCount`를 반드시 명시 기록한다 |
| randSeed | base seed(양수, §A4). 0·음수 금지 |
| shuffleTile | **0 고정**(현 배포값 전부 0, 01 §4). 바꾸면 스왑 횟수가 늘어나 시드와 독립된 손잡이가 하나 더 생긴다 → 이번 범위 밖 |
| typeImbalance | **빈 값/0 고정.** R7(반올림)과 단위 불일치(에디터 float vs 런타임 `AsInt/10`, 01 §9-2)가 남아 있다 |
| visualTileSeed | 키를 넣지 않는다(GB가 생략, GB:468-472). 현 스킨이 전부 icon_order라 리맵을 건너뛰고(CS:1312), 순수 t0 맵에서는 리맵이 bijective라 논리 영향도 없다 |
| 유지 | layer 수·레이어 col/row·위치 키·effect·goalCount·timea·rewardCoin·autoCollectCount·tileSkin·backgroundIndex 등 기존 값 전부 |
| 단언(assert) | ① key 제외 t0 총수 %3==0 ② 레이어 키 `layer_0..N-1` 연속(누락 시 클라 NRE·layerIndex 어긋남, 01 §3-7·§9-1) ③ t0화 전후 structHash 동일 ④ 명시 타일 잔존 0(key 레벨 제외) |

**[제안] 대상 제외 (P1·P2 공통)**: 보스(끝자리 0), 기믹 튜토리얼 레벨(GEN `TUTORIAL_UNLOCK_LEVELS`: 51·81·111·151·191·241·291·391·441, 00 §7-3), timea>0(Lv341), key 57, 샤드 불일치 34, count-only 컨테이너 70(이미 런타임 랜덤이므로 t0화 대상에는 포함하되 P1 표본에서는 제외), 그리고 1~31. 포함 여부의 최종 결정은 Q2.

### A3. 에디터↔클라 비트 일치 (최우선 전제)

**A3-1. 해소할 차이 [사실]**
| # | 차이 | 근거 | 레퍼런스 포트에서 처리 |
|---|---|---|---|
| R1 | TS에 색상 클러스터 제거 Fisher-Yates(세트 수 n−1회 `Rand(0,i)`)가 없음 | CS:1208-1217, 01 §9-3 | 그대로 포함 |
| R2 | Python 분배기가 구 알고리즘 | BS:123-211 | 쓰지 않음. 새로 포팅 |
| R3 | t0 순회 = 레이어 0..N + tiles JSON 키 삽입 순서. 에디터 저장 순서와 1424/1530이 다름 | CS:880-903, 01 §9-1, 02 R3 | **정규 입력 = GB 변환 출력 순서**(아래 A3-3) |
| — | `layerIndex` = map 키 열거 순번 | CS:548-553 | 정규 맵은 `layer, layer_0..N-1` 순서로 고정 |
| R4 | toAdd 입력에 inner 명시·key 포함 | CS:1123-1156 | `GetEmptyTileList(true)` 그대로 포팅 |
| R5 | TS 1.5단계 자동보정(클라에는 없음) | GE:408-478 | 넣지 않음. 비÷3 입력은 단언으로 거부 |
| R6 | 0 = 시간 기반, 음수 = `(uint)` 캐스팅 결정적 | ZW:25-30, CS:1171 | seed 0은 예외 처리. 음수는 uint 캐스팅까지 재현하되 생성은 금지 |
| R7 | `Mathf.RoundToInt`(짝수 반올림) + float | CS:1417 | imbalance=0 고정이라 미사용 경로. 포트에는 banker's rounding + float32로 구현하고 골든 1케이스로 확인 |
| R8 | 필드명 `shuffleTile`/`typeImbalance` | 01 §9-2 | 정본 키명만 읽음 |
| — | `emptyLen==0` → 즉시 return, RNG 미소비 / `Rand` 범위 크기 0이면 미소비 | CS:1202, ZW:72-84 | 그대로 |

**A3-2. 레퍼런스 포트 언어 = Python [제안]**
- 근거 [사실]: 평가 파이프라인 전체가 Python이다. 봇 `BS`, MC 스윕 `MC`(`make_skill_profile` MC:113, `sweep_point_task` MC:268), 솔버 `solve_level`(solver.py:201)이 여기에 해당한다. TS 엔진은 에디터 UI 미리보기에만 쓰인다.
- 구조: **"배정 후 평가"(resolve-then-evaluate)**. 포트가 (정규 맵, seed, utc)로 클라와 같은 타입 배열을 만들어 **명시 맵으로 풀어 쓰고**, 봇·솔버는 그 명시 맵을 그대로 평가한다. 기존 봇 내부 분배기(`TileDistributor`)는 건드리지 않는다. 그 경로에는 t0가 남지 않으므로 탈 일이 없다. 공유 핵심 파일을 수정하지 않아도 되고, 병렬 세션과 충돌할 일도 없다.
  - inner 순서 확인 필요: Python 봇은 `inner_ids[stack_idx]`를 쓰고(BS:1396-1402), craft 배출은 높은 index부터 진행한다(BS:1619) → index 0이 바닥인 클라 규약과 같다고 추정한다. P0 골든에서 "풀어 쓴 맵을 봇이 읽은 결과 = 클라 덤프"로 확인한다(P0-G3).
- TS 포트(TD/GE) 수정은 **범위 밖**이다. 대신 sandbox를 UI에 넣지 않는다는 규칙(A1)으로 차단한다. 에디터 UI 미리보기를 클라와 맞추는 작업은 P3 이후에 한다.

**A3-3. 정규 키 순서 보존 [사실→제안]**
- [사실] GB 변환은 맵을 `{"layer", layer_0..N-1}` 순서로 만들고, tiles 키를 `(y, x)` 오름차순으로 정렬한다(`_tile_pos_sort_key`·`_normalize_tiles_order`, GB:355-375, 394-404). 레이어 키가 없으면 건너뛴다(GB:397).
- [사실] 클라 샤드 순서 = 굽기 시점의 서버 `real_array` 응답 순서이고(01 §9-1), 샤드 예(level_4)가 이 정렬과 일치한다. 파서는 순서를 보존하고 삭제 경로가 없다(01 §9-1).
- [제안] **정규 맵 = `_convert_to_townpop_format(level_json)["map"]`** 결과로 정의한다. 기존 함수를 import해서 재사용하고, GB는 수정하지 않는다. 에디터 저장 순서와 무관하게 결정적이다. 평가·해시·골든은 모두 이 정규 맵을 입력으로 한다.
- 구간별 보존 방법
  - 에디터 저장: 순서 무관(GB가 정렬).
  - GB 변환→GameBoost→`real_array`→`LevelMapBakeTool`: **P0-G2에서 현 샤드 1530 전수에 대해 "tiles 키 순서 == GB 정렬 순서, 레이어 키 순서 == layer, layer_0.." 스캔**으로 확인한다. 하나라도 다르면 서버 구간에서 순서가 바뀐다는 뜻이므로 typesHash 런타임 검증(§A6)을 필수 조건으로 올린다.
  - 클라 기기(IL2CPP) Dictionary 열거 순서: 명세상 보장되지 않는다(01 §9-1 추정). 이번 범위에서는 Unity 에디터 덤프로만 확인하고, 기기 확인은 P3에서 `random.CurSeed` 로그(CS:1184)와 typesHash로 한다.
- structHash에 정규 순서를 포함한다(§A6). 순서가 바뀌면 해시가 바뀌어 평가 결과가 자동으로 무효가 된다.

**A3-4. 골든 정답 확보 [사실→제안]**
- [사실] 머신 확인 결과: `dotnet` SDK 6.0.4xx·7.0.3xx·8.0.101·9.0.202, `mono` 6.12, `csc`/`mcs` 사용 가능. Unity 6000.0.62f1(게임 프로젝트 버전)이 설치돼 있고, **현재 sp_meowsgarden 프로젝트가 Unity 에디터에서 열려 있다**(pid 확인). 같은 프로젝트로 batchmode를 동시에 실행할 수는 없다.
- [사실] 의존성: `zWellRandom.cs`는 `using System`만 쓴다 → **원본 파일을 그대로 컴파일**할 수 있다. `SimpleJSON.cs`·`spInteger.cs`는 `UnityEngine`을 참조한다(Random.Range, `#if UNITY_EDITOR`). `DB_Level.cs`는 UnityEngine·GameBoost·KLogger·spEncrypt에 의존한다.
- [제안] 3단 정답 체계
  | 단계 | 수단 | 역할 |
  |---|---|---|
  | G1 | dotnet 콘솔(`tools/pv_golden/`)에서 **원본 `zWellRandom.cs`를 경로 링크로 컴파일**, seed별 `_rand()` 1000개 덤프 | RNG 정답(01 §3-6 Python 값의 C# 실행 확인 포함) |
  | G2 | 같은 콘솔에서 `DB_Level.cs`의 `GetEmptyTileList`/`GetToAddIndexList`/`DistributeTiles`/`ShuffleEmptyTiles` 본문을 **줄 범위 그대로 추출**(추출 스크립트가 원본 텍스트 sha256을 기록하고 불일치하면 실패) + 최소 shim(spEncrypt=문자열 래퍼, `Mathf.RoundToInt`=`(int)Math.Round(float)`, KLogger no-op) + 원본 `SimpleJSON.cs`(UnityEngine shim) | 빠른 반복용 정답(CI용) |
  | G3 | **Unity 에디터 전용 스크립트**(게임 저장소 `Assets/Editor/` 하위, 빌드 미포함)로 실제 `CLevel` 생성 → `UpdateNewMapData` 경로를 같은 입력으로 실행해 덤프. 열려 있는 에디터에서 메뉴 실행 또는 Unity MCP로 EditMode 실행 | **최종 정답(권위).** G2 추출·shim 오류를 잡는다 |
  - 판정: Python 포트 == G2 == G3가 전 케이스에서 일치해야 한다. G3를 못 하면 P1은 진행하되 "G2 기준 잠정"으로 표시하고, 배포 계약 확정(P3)은 G3가 끝나야 가능하다.
  - 케이스(02 §7 확장): 순수 t0 소/대형 / 레이어 다수 + 비정규 키 순서 입력(정규화 확인) / 구포맷 stack·craft / 신포맷 inner "t0" 혼재(key 레벨용) / unlockTile 1·2 / utc 1·3·4·12·15 / seed 1·2³¹−1·임의 20개 / shuffleTile>0 1건 / imbalance>0 1건(.5 경계) / emptyLen이 3의 배수가 아닌 입력(거부 확인) / **실 레벨 20개**(P1 표본 그대로).

**A3-5. 버전 고정 [제안]**
- `distVer` = `"cs:" + sha256(위 4개 메서드 원문 + zWellRandom.cs)[:12]`. 추출 스크립트가 계산하고, 기준 커밋은 `b741f6a3`이다. 클라 원문이 바뀌면 distVer가 바뀌므로 해당 seed 평가 전체를 stale로 처리한다.

### A4. 시드 후보 생성·평가

**[제안] 시드 값**
- `seed_k = 1 + (u32(sha256(f"{structHash}|{k}")[:4]) mod (2³¹−2))`, k=0..K−1. 1~2³¹−1 범위의 양수이고, 같은 구조라면 결정적으로 재현된다. 0은 나올 수 없고(+1), 음수도 없다. 레벨 내 중복은 다음 k로 대체한다.
- 클라는 `xRandSeed.AsInt`(int32)로 읽으므로 상한은 2³¹−1이다(CS:1171).

**[제안] 평가 축**
| 축 | 방법 | 비고 |
|---|---|---|
| B 봇 성공률(주 지표) | 스킬점 θ∈{0.29, 0.47, 0.65}(모집단 N(0.47,0.18)의 ±1σ, MC:67-79)에서 `make_skill_profile`(MC:113)로 만든 봇을 `simulate_with_profile(..., early_termination=False)`로 직접 호출한다. MC 스윕 함수는 조기종료가 고정돼 있어(MC:286) 쓰지 않는다. **지표 W = 3점 평균 성공률**("봇 가중 성공률", 사람 클리어율 아님) | 공통 난수(CRN): 같은 단계 안의 모든 후보에 같은 봇 시드열(`seed+i`, BS:807-808)을 쓴다 |
| A 해법 존재 | `solve_level`, **노드 예산만 사용**(200k, 시간 예산은 크게: CPU 부하에 따라 SOLVABLE↔UNCERTAIN이 흔들리는 문제 차단, 03 §1 결정성) | 시간·노드 초과 = **미확인**(불가능 아님) |
| A 대체 증거 | 봇이 한 판이라도 클리어하면 **해법 존재 실증**(witness). 단 teleport·frog 레벨은 런타임 난수 때문에 "그 난수 실현에서 가능"일 뿐임 | 솔버를 믿을 수 없는 기믹(bomb/curtain/craft)에서 A를 보완 |
| 보조(기록만) | 트레이 최대 점유·위기(용량−1) 빈도·실패 원인 | `_play_game` 계측 추가 필요(03 §4). P1 선택 작업 E-P1-5 |

**[제안] A 판정의 레벨 유형별 규칙**
| 유형 | 솔버 결과 사용 | seed 확인 조건 |
|---|---|---|
| 일반 / ice·grass·chain·link / stack | SOLVABLE 신뢰, IMPOSSIBLE이면 제외 | 솔버 SOLVABLE **또는** 봇 클리어 ≥1 |
| bomb·curtain(후처리 미호출, 03 §1) | **참고 불가**(SOLVABLE도 무시) | 봇 클리어 ≥1 |
| craft(막힌 재배출 누락) | IMPOSSIBLE 무시, SOLVABLE만 사용 | 솔버 SOLVABLE 또는 봇 클리어 ≥1 |
| teleport·frog(무시드 런타임 난수, 01 §5-4) | 참고 불가 | 봇 클리어율 ≥ 하한(최고 스킬점에서 ≥2%, P1에서 조정). 판수를 1.5배로 늘린다 |
- 확인되지 않은 seed(모든 판 실패 + 솔버 미확인/참고 불가)는 **최종 5개에 넣지 않는다.** 스크리닝 분포 집계에는 포함하고 표시만 한다.

**[제안] K와 판수 (2단계)**
| 단계 | 대상 | 판수 | 근거 |
|---|---|---|---|
| 1단계 스크리닝 | K=32 후보(P1). P2에서는 P1 결과로 K를 다시 정한다 | 3점 × 64판 = 192판/후보, CRN | W의 표준오차 ≈ √(0.25/192) ≈ 0.036. 분포 모양과 극단 후보를 대략 찾는 용도. K=32면 상·하위 각 ~3%(1/32) 분위까지 볼 수 있다 |
| 2단계 확정 | 숏리스트 9개(base 후보 1 + 각 방향 주 2·대체 2) + **원 맵(명시)** | 3점 × 400판 = 1200판, **1단계와 독립인 새 봇 시드열**, 단계 안에서는 CRN | 독립 비교 기준으로 차이 SE ≈ 0.020 → Δ≈0.05를 Bonferroni(α=0.05/4, z≈2.5)로 검출. CRN이 유효하면 더 좋아진다(03 §4-2) |
| P1 전용 반복 | base 후보 1개를 독립 시드열 4회 × 1200판 | 측정 잡음 σ_meas 추정 | — |
- 비용 [제안, 03 §5 기준 t_game≈0.06s·8워커, 미검증]: 레벨당 1단계 32×192 = 6,144판 + 2단계 10×1,200 = 12,000판 (+P1 반복 4,800판) ≈ 18~23k판 → **약 2.3~2.9분/레벨**, 솔버 32후보 ×~3s/8 ≈ 12~48s 추가. P1 20레벨 ≈ **1~1.5시간**. P2(대상 ~1,000레벨 가정) ≈ **40~55시간** → 100레벨 단위 야간 분할 실행.

### A5. 5개 시드 선별 규칙

**A5-1. base 선택 — 두 안 비교**
| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| (가) 분포 중앙 | 1단계 W 분포의 중앙값에 가장 가까운 seed | 양쪽 여유가 최대여서 5단계 확보율이 높다 | 원 맵 난도와 무관하다. 기획 난도 곡선(쉬어가기·도전 흐름)이 레벨마다 무작위로 흔들린다 |
| (나) 원 맵 근접 | 2단계에서 원 명시 맵의 W_orig를 재고, 그에 가장 가까운 seed | 기존 곡선을 보존한다 | 원 맵이 의도적으로 배정돼 분포 끝에 있으면 한쪽 tier를 못 만든다 |
- **추천 = (나)에 띠 제약.** base는 1단계 분포의 **25~75 분위 띠 안에서** W_orig에 가장 가까운 seed로 한다. W_orig가 띠 밖이면 가까운 띠 끝을 고르고 `baseShift = W_base − W_orig`를 기록한다. |baseShift|가 큰 레벨 비율이 P1 게이트다(P1-G4).

**A5-2. 숏리스트(1단계 결과로)**: base 후보 1개. easy 방향은 base보다 W가 큰 후보 중 "base와 최댓값의 중간" 근처 1개와 상위 2~3번째 1개를 주 후보로, 그 이웃 2개를 대체 후보로 고른다. hard 방향도 대칭으로 고른다. **단일 최극단 후보는 주 후보로 쓰지 않는다**(winner's curse 완화, §B S1).

**A5-3. 최종 tier(2단계 값만 사용)**
- 순서 조건: W(e2) > W(e1) > W(b) > W(h1) > W(h2).
- 구분 조건(인접 4쌍 각각): ① 차이 ≥ δ_min(**초기값 0.05**, P1에서 σ_meas로 재설정) ② 차이의 95% CI(같은 판 인덱스 쌍 부트스트랩, Bonferroni α=0.05/4)가 0을 포함하지 않음.
- 추가 조건: 5개 모두 A 확인(§A4). h2는 최고 스킬점 W ≥ 하한(초기 0.10)이어야 한다("불공정하게 어려운" seed 차단, §B D5).
- 스킬점별로 순위가 뒤집히면(예: θ0.29에선 쉬운데 θ0.65에선 어려움) `crossing=true`로 표시하고 그 쌍은 구분 실패로 처리한다.

**A5-4. 폴백(5개를 못 뽑을 때)**
1. 대체 후보로 다시 맞춘다.
2. 안 되면 축소한다. e2=e1(또는 h2=h1)에 **같은 seed를 중복 기록**하고 `collapsed=["e2"]`를 표시한다. 클라는 항상 5칸을 읽으므로 로직은 바뀌지 않는다.
3. e1이나 h1조차 base와 구분되지 않으면 `pv.status="flat"`으로 두고 5칸 모두 base seed를 넣는다(개인화 효과 없음, 안전).
4. utc±1 보조 손잡이는 **이번 범위에서 쓰지 않는다**. 사용자 유지 항목에는 없지만 종류 수를 바꾸면 정적 점수·시각 구성이 바뀐다. P1 결과 `flat`·`collapsed` 비율이 높을 때만 Q3으로 결정한다(스키마에는 seed별 `utc` 슬롯만 마련).

**A5-5. 표현 원칙**: 모든 결과는 "봇 가중 성공률 W와 그 차이"로만 쓴다. "사람 클리어율 x%"라고 표기하지 않는다(00 §7-1). tier는 레벨 안에서의 **상대 순위**다.

### A6. 배포 형식

#### A6-0. 확정: A안 — 기존 `randSeed` 필드에 5시드 문자열 (2026-10-02 사용자 결정)
- 형식: `randSeed = "base|e2|e1|h1|h2"`. 구분자는 `|`, **첫 값 = 기준(base)**이다. 새 필드는 만들지 않는다.
  - 예: `"1929029997|149028555|1903905507|1771213338|800834984"`
- 양방향 5시드를 확보하지 못한 레벨: t0화하지 않고 **기존 명시 맵을 유지**한다(randSeed는 기존 값). 단일 시드 t0 운영은 사용자 결정 전까지 쓰지 않는다.
- **클라 파싱 규칙(신규 코드)**:
  - `|`로 나눈 모든 값이 양의 정수(1~2³¹−1)이고 개수가 1 또는 5일 때만 사용한다.
  - 그 외에는 첫 값만 쓴다. 첫 값도 불량이면 기존 동작(`xRandSeed.AsInt`)으로 간다.
  - 선택된 값을 `ShuffleEmptyTiles`의 시드로 쓴다. 개인화 선택 로직은 별건이다.
- **에디터 내보내기 검사**: 정확히 5개, 0·음수·범위 밖 없음, 서로 다른 값, 첫 값 = 선별된 base. 위반 시 내보내기를 차단한다. 구현 예: `backend/scripts/pv_selection_export.py::validate_a_values`.
- **(참고) 구버전 클라 호환 — 현 구조에서는 해당 없음** (2026-10-02 사용자 결정으로 필수 안전장치에서 제외)
  - 현 구조에서는 레벨 데이터가 빌드에 내장되고 서버 델타는 꺼져 있다(01 §1). 5시드 맵과 파서 코드는 같은 새 빌드에 함께 들어가므로, 구버전 앱은 새 데이터를 받지 않는다. **고려 대상이 아니다.**
  - 향후 **서버 델타나 서버 단건 조회를 다시 켤 때만** 재검토한다.
    - [사실] 구 코드는 `xRandSeed.AsInt`로 읽는다. `"a|b|c|d|e"`는 `double.TryParse`에 실패해 0이 되고, 시간 기반 시드로 동작한다(SE:529-535, ZW:25-30, 05 §3-2).
    - 그때는 "A안 파서를 가진 최소 앱 버전 미만은 A안 행을 받지 않는다" 규칙을 검토한다.
- GB 변환 [사실]: `str(level_json.get("randSeed"))`로 출고한다(GB:465). 문자열이면 그대로 통과하므로 변환 코드 수정은 필요 없다. 다만 아래 영향 지점에서 에디터 쪽이 깨진다.
- **에디터 randSeed 숫자 처리 영향 지점** (전수 Grep, 수정 안 함):
  | 위치 | 처리 | A안 문자열 입력 시 |
  |---|---|---|
  | `backend/app/core/bot_simulator.py:309`(`rand_seed > 0`), `:824-843`(`== 0`, 대입), `:1023`(`get` → 분배기 전달) | 숫자 비교·연산 | `str > int` **TypeError** |
  | `backend/app/core/solver.py:140` `int(level_json.get("randSeed"))` | int 변환 | **ValueError** |
  | `backend/app/core/generator.py` 약 40곳(`:1989, 3084, 3212, 14158, 14185, 14452, 14727, 15235-15334, 15753, 15790, 16164-16219, 16361, 16531-16553, 16579-16658`) | 생성·재시드·`int()`·`+` 연산 | 생성 경로는 숫자를 새로 쓰므로 무관. 재검증·수정 경로(`int()`, `+ offset`)에서 **예외** |
  | `backend/app/api/routes/tune.py:313, 502, 748, 876, 1117` `int(... randSeed ...)` | int 변환 | **ValueError** |
  | `backend/app/api/routes/simulate.py:114, 162, 1081-1082` | 분배기에 전달 | TypeError |
  | `backend/app/api/routes/analyze.py:1956-1967, 2471, 3028, 3131, 3992` | 숫자 대입·int 정규화(3028) | 3028 정규화 **ValueError**, 나머지는 덮어씀 |
  | `backend/app/api/routes/generate.py:1123` | 새 숫자 생성 | 무관 |
  | `backend/app/models/benchmark_level.py:103` | 기본값 0 | 문자열이 그대로 전달됨 |
  | `backend/app/api/routes/gboost.py:465` | `str()` 출고 | 통과(정상) |
  | `frontend/src/types/index.ts:24` `randSeed?: number` | 타입 | TS 타입 불일치 |
  | `frontend/src/components/ProductionDashboard/index.tsx:379-380` bakeFullBoard `typeof === 'number'` 아니면 0 | bake 생략 | 굽기를 건너뜀(t0 유지 — A안에는 의도에 맞음) |
  | `frontend/src/engine/gameEngine.ts:488-489` `typeof === 'number'` 아니면 **42** | 미리보기 시드 | 미리보기가 42로 배치(클라와 다름) |
  | `frontend/src/engine/tileDistributor.ts:400-413` `randSeed > 0` | 숫자 | 문자열 비교로 시간 시드 경로 |
  | `frontend/src/components/RLSimulationPanel.tsx:1678`, `FixedLevelEditor.tsx:117` | 표시 / 0 대입 | 표시만 |
  - 결론 [제안]: A안 문자열은 **내보내기 직전(GB 변환 입력 단계)에만** 만들고, 에디터 내부 저장은 숫자 base + 별도 메타(선별 결과)로 둔다. 그러면 위 지점을 고치지 않아도 된다. 내부에서도 문자열로 저장해야 한다면 위 지점 전부에 파서를 추가해야 한다.

#### A6-0b. 제안: 종류 수 ±1 허용에 따른 토큰 확장 (v3, 08 §7)
- 사용자 결정(쉬움 ≤ utc0−1, 어려움 ≤ utc0+1 허용)으로 tier마다 utc가 다를 수 있다. 새 필드 없이 **토큰 = `seed` 또는 `seed@utc`**로 확장한다(`@` 없으면 레벨 useTileCount = utc0).
  - 예: `1635606022@11|358522884@11|2079322438@11|894482049|264350516`
- 클라 파싱: 각 토큰이 `^\d+(@\d+)?$`이고 seed 1~2³¹−1, utc 1~15이며 개수 1 또는 5일 때만 쓴다. 아니면 첫 토큰(그 `@utc` 포함), 그것도 불량이면 기존 동작. 선택된 토큰의 utc를 그 판 `ShuffleEmptyTiles`의 maxTileIndex로 쓰고, 레벨 행의 useTileCount는 utc0을 유지한다.
- 에디터 검사(`pv_selection_export_v3.py::validate_a_v3`): 5토큰, (seed, utc) 쌍 서로 다름, |utc−utc0| ≤1, utc0에는 `@` 금지, 첫 토큰 = 기준 시드. 정책 검사: 쉬움 칸 utc ∈ {utc0−1, utc0}, 어려움 칸 ∈ {utc0, utc0+1}, 기준 칸은 strict면 utc0, relaxed면 utc0±1.
- 대안(병렬 useTileCount 문자열, seed에 utc 인코딩)과의 비교는 08 §7.

#### A6-0c. v4 확정 형식: 토큰 수 1 / 3 / 5 (2026-10-02 사용자 결정, 09 보고서)
- 토큰 개수는 **1, 3, 5만** 허용한다. 첫 토큰은 항상 기준 시드(b)다.
  - 5단계: `"b|e2|e1|h1|h2"`
  - 3단계: `"b|e2|h2"`(안쪽 칸이 견고 판정을 통과하지 못한 레벨)
  - 1개: 단일 시드(형식상 허용. 현재 선별 결과에서는 쓰지 않음)
  - 고정 맵 레벨: 문자열 없음(기존 명시 맵과 기존 randSeed 유지)
- 토큰은 `seed` 또는 `seed@utc`다(A6-0b와 같음). 예(3단계): `1635606022@11|358522884@11|264350516`
- **클라 파싱**: `|`로 나눠 1·3·5개이고 모든 토큰이 `^\d+(@\d+)?$`(seed 1~2³¹−1, utc 1~15)일 때만 쓴다. 아니면 첫 토큰, 그것도 불량이면 기존 동작. 토큰 개수로 단계 수를 판정한다.
- **에디터 검사** `pv_selection_export_v4.py::validate_a_v4`:
  - 개수는 3 또는 5, 선별 단계 수와 같아야 한다.
  - utc0에는 `@`를 쓰지 않는다. |utc−utc0| ≤1. 쉬움 토큰은 utc0+1 금지, 어려움 토큰은 utc0−1 금지.
  - (seed, utc) 쌍은 서로 달라야 하고, 첫 토큰 = 기준 시드다.
- **클라 단계 이동 규칙 (제안)**: 개인화 로직이 유저 단계 s ∈ {−2, −1, 0, +1, +2}(음수 = 쉽게)를 갖는다고 가정한다.
  | s | 5단계 레벨 | 3단계 레벨 (보수적 권고) |
  |---|---|---|
  | −2 | e2 | e2 |
  | −1 | e1 | **e2** (완화는 너그럽게: 반복 실패 유저가 기준 시드를 다시 만나지 않게) |
  | 0 | b | b |
  | +1 | h1 | **b** (상향은 보수적으로: 한 칸 위는 기준 유지) |
  | +2 | h2 | h2 |
  - 근거: 개인화의 주목적은 반복 실패 완화이고 지루함 방지는 보조다. 3단계 레벨의 바깥 칸은 기준 대비 차이가 크므로(목표 쉬움 +0.20 / 어려움 −0.25), 어려워지는 쪽은 강한 신호(s=+2)에서만 쓴다.
  - 대안: 양쪽 모두 기준으로 내리는 방식(s=±1 → b)은 가장 보수적이지만, 완화가 필요한 유저에게 효과가 늦게 나타난다.

#### A6-1. 보류안: 별도 `pv.*` 필드 (아래 초안, 참고용으로 남김)

**[보류안] t0화된 level_json (sandbox `selected.jsonl`)**
```json
{
  "layer": 6, "layer_0": { "col": "7", "row": "7", "tiles": { "1_1": ["t0", ""], "2_5": ["craft_s", "", [3]] } },
  "useTileCount": 12,
  "randSeed": 1834920117,
  "shuffleTile": 0,
  "pv": {
    "v": 1,
    "mode": "seed",
    "distVer": "cs:3fa91c0d2e7b",
    "structHash": "9f2c…e1",
    "utc": 12,
    "status": "ok",
    "seeds": [
      { "tier": "e2", "seed": 77120394,   "typesHash": "c3d0…5b" },
      { "tier": "e1", "seed": 501922711,  "typesHash": "…" },
      { "tier": "b",  "seed": 1834920117, "typesHash": "41aa…07" },
      { "tier": "h1", "seed": 932001455,  "typesHash": "…" },
      { "tier": "h2", "seed": 1200388017, "typesHash": "…" }
    ],
    "collapsed": []
  }
}
```
- `seeds`는 **항상 5칸, 쉬운 것→어려운 것 순서**이며 index 2가 base다. `randSeed`는 언제나 base seed와 같다.
- `structHash` = sha256(정규 맵을 타입만 "t0"로 비운 뒤 정규 순서로 `(layerIdx, posKey, effect, rootId, innerCnt)` 직렬화). **순서를 포함**하므로 키 순서가 바뀌면 다른 해시가 된다.
- `typesHash` = sha256(정규 순회 순서[= `GetEmptyTileList(false)`]의 배정 결과 tileID 배열). 레퍼런스 포트가 계산하고, 나중에 클라가 배정 직후 같은 값을 계산해 대조할 수 있게 한다(00 §5-4-3).
- 에디터 보관 메타(배포 안 함, `eval/*.jsonl`): `genVer`(t0화 규칙 버전), `evalVer`(봇·솔버 커밋 + θ grid + 판수 + 봇 시드 기준값), 1·2단계 W·CI·A 판정·baseShift·crossing·W_orig, 원본 batch_id·version.
- **호환** [사실→제안]
  - pv를 모르는 클라는 `randSeed`(=base)만 읽어 base를 결정적으로 플레이한다. **레벨 데이터가 빌드에 내장되므로**(01 §1) "새 데이터 + 구 코드" 상황은 "pv 미지원 코드로 새 샤드를 굽는 경우"뿐이다. 그 경우에도 base로 안전하게 동작한다.
  - GB 변환은 정해진 필드만 출고하므로 `pv`는 버려진다(GB:456-497). GameBoost 테이블은 필드를 컬럼으로 저장한다 → 실제 배포에는 컬럼 추가(예 `pvSeeds` 문자열)와 GB 수정이 필요하다 → **P3(이번 범위 밖)**.
  - 롤백: 원본 LIVE 3차 배치와 샤드는 수정하지 않으므로 롤백 = 원 명시 맵 재업로드다. 부분 롤백은 해당 레벨 `pv.status="flat"`으로 한다.

### A7. 테스트 단계와 게이트

| 단계 | 작업 | 완료 기준(게이트) | 예상 시간 [제안·미검증] | 산출물 |
|---|---|---|---|---|
| **P0 재현성** | 레퍼런스 포트(Python), dotnet 골든 G1·G2, Unity 덤프 G3(승인 시), 정규 맵·해시, 샤드 순서·구조 스캔 | **G1** RNG 1000개×5 seed 일치 / **G2** 합성+실레벨 케이스 Python==dotnet 100% / **G3** Python==Unity 100%(못 하면 P1은 잠정 진행) / **G4** 샤드 1530 키 순서 == GB 정렬, 구조 차이는 기존 34개뿐 / **G5** 풀어 쓴 명시 맵을 봇이 읽은 타입 == 덤프(inner 순서 포함) | 구현 1~2일, 실행 수 분 | `backend/app/core/pv/*`, `tools/pv_golden/`, `backend/tests/golden/pv_t0/`, `05_p0_report.md` |
| **P1 파일럿** | 사본 생성 → 표본 20레벨 t0화 → 1·2단계 평가 → 선별 | **G1** t0화 단언 위반 0 / **G2** 측정: σ_between(1단계 W의 seed 간 SD), σ_meas(반복 SD), 신뢰도 = σ_between²/(σ_between²+σ_meas²) / **G3** 5단계 확보율, collapsed·flat 비율 / **G4** \|baseShift\| ≤ 0.05인 레벨 비율 / **G5** 회귀 비율 = (2단계 Δ)/(1단계 Δ) / **G6** CRN 상관 ρ(같은 판 인덱스 성공 여부) / **G7** seed A 미확인·불가 비율 | 실행 1~1.5h | `pv_sandbox/{copyId}/eval/`, `06_pilot_report.md` |
| **P2 확대** | P1 결과로 K·판수·δ_min 재설정 후 대상 전 레벨(구간별 100레벨 묶음) | P1 게이트 기준 통과 + 묶음마다 회귀 지표 유지 | 40~55h(대상 ~1,000 가정) | `selected.jsonl` 전체, `07_scale_report.md` |
- P1 표본(층화 20): 구간 6개(00 §7-3 구간 분포 기준) × 기믹 유형 {일반·ice/grass/chain/link, stack/craft, bomb/curtain, teleport/frog}에서 고른다. 제외 대상(§A2)은 빼고, 251~500 구간은 후보가 적다는 점을 기록한다.
- P1→P2 진행 판단(수치는 P1 후 확정): 5단계 확보율, 신뢰도, |baseShift| 비율이 기준을 밑돌면 P2 전에 Q3(utc±1) 또는 tier 축소를 결정한다.

### A8. 작업 분담 초안 (충돌 없는 단위)
| ID | 담당 단위 | 파일(신규 N / 수정 M) | 의존 |
|---|---|---|---|
| E-P0-1 | 레퍼런스 포트 | N `backend/app/core/pv/__init__.py`, N `backend/app/core/pv/cs_shuffle.py`, N `backend/tests/test_pv_cs_shuffle.py` | 골든(E-P0-3) |
| E-P0-2 | 정규화·해시·스캔 | N `backend/app/core/pv/canonical.py`(GB `_convert_to_townpop_format` import 재사용, GB 무수정), N `backend/scripts/pv_scan_shards.py`(샤드 복호·키 순서·구조 비교, 읽기 전용) | — |
| E-P0-3 | dotnet 골든 | N `tools/pv_golden/PvGolden.csproj`, N `tools/pv_golden/Shims/*.cs`, N `tools/pv_golden/extract_methods.py`, N `tools/pv_golden/Program.cs`, 출력 `backend/tests/golden/pv_t0/*.json` | 게임 저장소 읽기만 |
| C-P0-1 | 클라 골든 덤프(승인 필요) | 게임 저장소 N `Assets/Editor/PvGolden/PvGoldenDump.cs`(에디터 전용 메뉴, 빌드 미포함) | E-P0-3 입력 세트 |
| E-P1-1 | 사본 | N `backend/scripts/pv_make_sandbox.py`, M `.gitignore`(1줄) | — |
| E-P1-2 | t0화 | N `backend/app/core/pv/t0ize.py` | E-P0-2 |
| E-P1-3 | 평가 | N `backend/app/core/pv/evaluate.py`(봇·솔버 import만, 핵심 파일 무수정) | E-P0-1 |
| E-P1-4 | 선별 | N `backend/app/core/pv/select.py` | E-P1-3 |
| E-P1-5 (선택) | 트레이·위기·실패원인 계측 | M `backend/app/core/bot_simulator.py`(`_play_game` + 결과 dataclass, 필드 추가만) | 다른 세션의 BS 수정과 겹치는지 먼저 확인 |
| E-P1-6 | 실행기 | N `backend/scripts/pv_run_pilot.py` | E-P1-1~4 |
- 클라 측은 이번에 **골든 덤프(C-P0-1)만** 필요하다. pv 파싱·seed 선택·typesHash 자가검증·이벤트 파라미터(00 §8 C1~C5)는 P3 이후로 미룬다.
- 프론트 수정은 없다(CLAUDE.md의 BE→FE 타입 동기화 절차 대상 아님). 백엔드 API를 신설하지 않고 스크립트로 실행한다.

---

## B. 전문가 검토

### B-1. 퍼즐 레벨 디자이너
| # | 지적 | 판단 | 반영 |
|---|---|---|---|
| D1 | t0화하면 base까지 새 레벨이 된다. 검증된 난도 곡선(쉬어가기/도전)이 레벨마다 흔들린다 | 타당 | **반영(변경)**: base = 원 맵 W 근접 + 25~75 분위 띠(A5-1), baseShift 기록과 P1-G4 게이트 |
| D2 | 원 맵의 의도적 타입 빈도 불균형(세트 편차 ≥3인 116레벨)이 클라 균등 분배로 사라진다 | 타당. typeImbalance로 되살리는 방법은 단위·반올림 문제(R7, 01 §9-2) 때문에 보류 | **반영**: 레벨별 원 빈도 편차를 기록하고 P1에서 편차 큰 레벨의 baseShift를 따로 집계 |
| D3 | 기믹 첫 등장(튜토리얼)·보스·시간제한 레벨은 배치 자체가 연출이다 | 타당 | **반영(변경)**: 제외 목록에 추가(A2). 최종 포함 여부는 Q2 |
| D4 | 시드만으로 5단계 폭이 나오는지 불명. 차이가 너무 작으면 의미가 없다 | 타당. 측정 전에는 알 수 없다 | **반영**: δ_min·구분 조건, 축소·flat 폴백(A5-3/4), P1-G3 확보율 게이트 |
| D5 | hard seed가 "초반 막힘" 같은 운 나쁜 배치면 불공정하게 느껴진다 | 타당 | **반영(변경)**: h2에 최고 스킬 W 하한, 위기 빈도 기록(E-P1-5) |
| D6 | 원 bake는 레벨 번호 seed로 1~15를 relabel해 레벨마다 아이콘 구성을 바꿨다(PD:408). t0 맵은 항상 t1..t{utc}라 utc≤12면 13~15번 아이콘이 나오지 않는다 → 시각 단조로움 | 타당. 클라 리맵은 icon_order 때문에 건너뛴다(CS:1312) | **위험으로 기록**: 해결하려면 클라 변경(순수 t0 레벨에서 리맵 허용 등)이 필요 → P3 게임팀 협의. 논리 난도에는 영향 없음 |
| D7 | 링크 짝 같은 종류 요구 여부 | 데이터상 14%만 같은 종류 → 제약 없음 | 변경 없음 |

### B-2. 클라이언트/재현성 엔지니어
| # | 지적 | 판단 | 반영 |
|---|---|---|---|
| C1 | dotnet 추출 하네스만으로 정답을 삼으면, 추출·shim 오류가 Python 포트와 같은 방향으로 틀릴 수 있다(자기참조) | 타당 | **반영(변경)**: Unity 실경로 덤프 G3를 권위 정답으로 둔다. G2는 CI용. 추출 원문 sha256 검증 |
| C2 | GB 정렬 후 서버·굽기 구간에서 순서가 유지된다는 근거가 샤드 예시 1건뿐 | 타당 | **반영(변경)**: P0-G4 샤드 전수 순서 스캔. structHash에 순서 포함 |
| C3 | 레이어 키 누락·비연속이면 클라 NRE·layerIndex 어긋남 | 타당 | **반영**: t0화 단언 ② |
| C4 | 클라가 ShuffleEmptyTiles를 고치면 모든 seed가 조용히 무효가 된다 | 타당 | **반영**: distVer = 원문 해시. P3에서 게임 저장소에 골든 EditMode 테스트 상시화(00 C7) 권고 |
| C5 | 미지원 빌드 호환과 롤백 | randSeed=base로 해결. 원본 무수정 | 반영(A6) |
| C6 | sandbox가 에디터 UI를 거치면 bakeFullBoard가 t0를 다시 굽는다 | 타당(PD:376-449) | **반영(변경)**: UI import 금지, production 밖 위치, `batch_` 접두사 금지 |
| C7 | GB의 utc 재계산은 t0 맵에서 저장값을 쓰고, 저장값이 없으면 6 | 타당(GB:443-444) | **반영**: utc 명시 기록 단언 |
| C8 | 기기 IL2CPP Dictionary 순서는 명세상 보장되지 않음 | 위험 낮음(01 §9-1) | P3 기기 로그·typesHash 확인으로 넘김 |
| C9 | 솔버 벽시계 예산은 결과를 비결정으로 만든다 | 타당(03 §1) | **반영(변경)**: 노드 예산만 사용 |

### B-3. 통계/평가 전문가
| # | 지적 | 판단 | 반영 |
|---|---|---|---|
| S1 | K개 중 극단을 같은 데이터로 고르면 winner's curse로 실제 차이가 과대평가된다 | 타당 | **반영(변경)**: 2단계 독립 재측정, 최종 tier는 2단계 값만 사용, 단일 최극단 배제, 회귀 비율 P1-G5 |
| S2 | K=32의 근거가 약하다 | 일부 타당 | **반영**: P1은 K=32, P2의 K는 σ_between·확보율로 다시 정함 |
| S3 | 보드가 다르면 봇 난수 경로가 곧바로 갈라져 CRN 효과가 미지수 | 타당(03 §4-2) | **반영**: P1-G6에서 ρ 측정. ρ≈0이면 독립 CI 기준으로 판수 산정 |
| S4 | 레벨당 인접 비교 4회 → 다중비교 | 타당 | **반영**: Bonferroni α/4. 레벨 간 FWER은 보고만 함 |
| S5 | 스킬점마다 순위가 뒤집힐 수 있다(V스윕 비단조 전례, 03 §4-1) | 타당 | **반영(변경)**: crossing 표시 + 구분 실패 처리 |
| S6 | 조기종료가 쉬운/어려운 쪽 구분을 지운다 | 타당(03 §2) | 반영: early_termination=False, MC 스윕 함수 대신 직접 호출 |
| S7 | teleport/frog는 판 사이 분산이 크다 | 타당 | **반영**: 판수 1.5배, A 하한 규칙 별도 |
| S8 | 봇 W 차이 0.05가 사람에게 의미 있는지 모른다 | 타당. 실측 없이는 판단할 수 없다 | 상대 지표 원칙 유지. 실측 보정은 P3+ (00 §9 3단계) |

---

## C. 확정안 변경점 (초안 → 확정)
1. **base 선택**: "분포 중앙" 또는 "원 맵 근접" 중 하나를 고르던 것을 **원 맵 근접 + 25~75 분위 띠 제약 + baseShift 게이트**로 바꿨다(D1).
2. **평가 2단계화**: 1단계(K=32×192판) 스크리닝 → 숏리스트 9개 + 원 맵을 **독립 난수**로 2단계(1200판) 측정하고, 최종 tier는 2단계 값만 쓴다(S1).
3. **골든 권위 = Unity 실경로 덤프(G3)**. dotnet 추출 하네스는 CI용이다(C1).
4. **P0 게이트 추가**: 샤드 전수 키 순서·구조 스캔(C2), 풀어 쓴 맵 봇 판독 일치(G5).
5. **제외 목록 확장**: 보스·기믹 튜토리얼·timea·key·샤드 불일치·count-only(P1 표본)(D3).
6. **hard 공정성 하한 + crossing 처리**(D5, S5).
7. **솔버 노드 예산 전용, 기믹 유형별 A 판정표, 봇 클리어 = 해법 실증**(C9, 03 §1).
8. **sandbox 격리 규칙**: production 밖, UI import 금지, `batch_` 접두사 금지(C6).
9. **utc±1 폴백 보류**: 스키마 슬롯만 두고, 사용 여부는 P1 결과 후 Q3로 결정(D4).

---

## D. 작업 지시서 초안

### P0 — 재현성 (병렬 가능 3+1 단위)
**E-P0-1 레퍼런스 포트** (`backend/app/core/pv/cs_shuffle.py`, `backend/tests/test_pv_cs_shuffle.py`)
- 입력: 정규 맵 dict(순서 보존) + `randSeed`·`useTileCount`·`unlockTile`·`shuffleTile`·`typeImbalance` / 출력: 정규 순회 위치 목록, 배정 tileID 배열, 풀어 쓴 명시 맵(inner는 `[cnt,"…"]`, index 0=바닥), typesHash.
- CS:870-945(`GetEmptyTileList` true/false), 1123-1156, 1167-1292, 1372-1502와 ZW 전체를 줄 단위로 대응해 포팅한다. 주석에 원본 줄 번호를 붙인다. 기존 `BS.TileDistributor`는 수정·재사용하지 않는다.
- seed 0이면 예외, 음수는 uint 캐스팅, 비÷3이면 예외. 완료 = pytest가 golden 전 케이스 통과.

**E-P0-2 정규화·해시·샤드 스캔** (`backend/app/core/pv/canonical.py`, `backend/scripts/pv_scan_shards.py`)
- `canonical_map(level_json)` = GB `_convert_to_townpop_format(...)["map"]`(import만). `struct_hash`, `types_hash`, 레이어 연속성 검사.
- 샤드 스캔: 01 §1 복호 방식(spZip XOR+ZIP)으로 `levelmap_level_*` 16개를 읽기 전용 디코드한다. (a) tiles 키 순서 == GB 정렬 (b) 레이어 키 순서 (c) LIVE 3차 대비 structHash 비교 → 차이 목록. 출력은 `05_p0_report.md`의 표.

**E-P0-3 dotnet 골든** (`tools/pv_golden/*`, 출력 `backend/tests/golden/pv_t0/`)
- `zWellRandom.cs`는 게임 저장소 원본을 `<Compile Include>`로 링크한다(복사 아님).
- `extract_methods.py`: DB_Level.cs에서 4개 메서드를 줄 범위로 추출하고, 원문 sha256과 distVer를 기록한다. 원문이 바뀌면 실패한다.
- Shims: `UnityEngine`(Random.Range, Mathf.RoundToInt=`(int)Math.Round(float)`, Debug), `spEncrypt`, `KLogger`.
- 케이스는 A3-4 목록. net8.0 대상.

**C-P0-1 Unity 덤프(승인 후, 게임 저장소)** (`Assets/Editor/PvGolden/PvGoldenDump.cs`)
- 메뉴 `SP/PV/Golden Dump`: `backend/tests/golden/pv_t0/inputs/*.json`을 읽어 실제 `CLevel` 생성 → `UpdateNewMapData`(→`ShuffleEmptyTiles`) 실행 → 정규 순회 tileID 배열 JSON으로 덤프. 에디터 전용이며 빌드에 포함되지 않는다. 런타임 코드는 수정하지 않는다.

**P0 완료 보고**: `claudedocs/difficulty_personalization/05_p0_report.md` — G1~G5 결과, distVer, 샤드 스캔 표.

### P1 — 파일럿 (P0 G1·G2·G4·G5 통과 후. G3 미완이면 "잠정")
- **E-P1-1** `pv_make_sandbox.py`: 원본을 `backend/data/pv_sandbox/{copyId}/source.json`으로 바이트 복사하고 manifest(sha256·batch_id·version·saved_at)를 남긴다. 원본은 읽기 전용이다. `.gitignore`에 1줄 추가.
- **E-P1-2** `t0ize.py`: §A2 규칙과 단언 4종. 결과는 `t0/levels.jsonl`(레벨별 utc0·원 빈도 편차·제외 사유 포함).
- **E-P1-3** `evaluate.py`: §A4 1·2단계, 원 맵 W_orig, 솔버 노드 예산 200k, 봇 클리어 witness 기록, ProcessPool 8.
- **E-P1-4** `select.py`: §A5 규칙 → `selected.jsonl`(§A6 스키마).
- **E-P1-5(선택)** `bot_simulator.py` 계측 필드 추가.
- **E-P1-6** `pv_run_pilot.py`: 층화 20레벨 실행 → `06_pilot_report.md`(P1-G1~G7, 레벨별 표, 분포 그림 데이터).

### P2 — 확대
- P1 보고를 바탕으로 K·판수·δ_min·h2 하한을 다시 정하고 문서화한다(06에 추가). 대상 전 레벨을 100레벨 묶음으로 실행하고 묶음별 회귀 지표를 감시한다. `07_scale_report.md`.
- 배포(P3: GB `pvSeeds` 컬럼, 클라 C1~C5, 기기 typesHash 확인)는 별도 계획으로 한다.

---

## E. 미확정 질문 (사용자 결정 필요, 5개)
| # | 질문 | 권고(전문가) | 영향 |
|---|---|---|---|
| Q1 | **레벨 4~31**(현재 t0 + seed 0 = 매 판 랜덤)은 이번처럼 현행을 유지하는가? | 현행 유지 | 범위 |
| Q2 | **보스(끝자리 0)·기믹 튜토리얼·Lv341(timea)·key 57레벨**을 최종 t0화 대상에서 영구 제외하는가, 아니면 P2 이후 편입하는가? | 보스·튜토리얼·341 영구 제외 / key는 P0 골든(신포맷 inner t0) 통과 후 편입 | 대상 수, 기획 의도 |
| Q3 | P1에서 5단계 확보율이 낮으면 **utc±1(타일 종류 수 변경)**을 보조 손잡이로 허용하는가? 아니면 tier 축소(3단계/flat)를 받아들이는가? | P1 결과 보고 결정. 기본은 축소 수용 | 스키마 seed별 utc, 시각 구성 |
| Q4 | **게임 저장소에 에디터 전용 골든 덤프 스크립트(C-P0-1) 추가**를 허용하는가? 누가 실행하는가(현재 Unity 에디터가 열려 있음 — 메뉴 1회 실행 또는 Unity MCP)? | 허용 권장. 없으면 비트 일치는 "dotnet 잠정"에 머문다 | P0-G3, P3 배포 가능 여부 |
| Q5 | **P2 실행 범위와 컴퓨트 예산**: 대상 전체(~1,000레벨, 40~55시간 추정)인가, 구간 층화 표본(예: 300레벨)부터인가? | 층화 300 → 확대 | 일정 |

> 위 5개 외의 결정(base 규칙, K·판수, 시드 범위, 스키마 필드명, 제외 기준, A 판정표, sandbox 위치)은 §B 전문가 권고대로 확정한다.
