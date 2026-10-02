# 02. 에디터 생성·배포 파이프라인 + 에디터↔클라이언트 재현성 조사

> 조사일 2026-10-02 · 조사 전용(코드/데이터 무변경) · 담당: 에디터생성조사 세션
> 표기: **[사실]** = 코드/데이터로 확인(파일:줄) · **[추정]** = 추론/제안 · **[에뮬]** = 임시 파이썬 재구현으로 돌려본 결과(Unity/Node 실행 아님)
> 경로 약어: `GEN`=backend/app/core/generator.py, `PD`=frontend/src/components/ProductionDashboard/index.tsx, `TD`=frontend/src/engine/tileDistributor.ts, `GE`=frontend/src/engine/gameEngine.ts, `BS`=backend/app/core/bot_simulator.py, `GB`=backend/app/api/routes/gboost.py, `CS`=sp_meowsgarden/Assets/08.Scripts/Tile_Script/InGame/DB_Level.cs, `ZW`=sp_meowsgarden/Assets/00.spComponents/zWellRandom.cs

---

## 0. 핵심 결론 (TL;DR)

1. **현재 32+ 레벨은 "생성 시 시드를 써서 굽고(bake) 명시 ID로 저장"한다.** 굽는 위치는 프론트 `bakeFullBoard`(PD:376-449, `ENABLE_INNER_TILE_BAKE=true` PD:314). t0와 count-only 컨테이너 내부를 TS 분배기(randSeed·useTileCount)로 풀고, 그 결과 전체를 `seed=levelNumber`로 1~15 relabel한 뒤 명시 ID로 덮어쓴다. JSON에 남은 `randSeed`/`useTileCount`는 **배포 후 효과 없는 잔존값**이다.
2. **1~31의 t0 25개 = `backend/data/fixed_levels.json`의 수작업 고정 레벨(4~9, 11~19, 21~29, 31)**, 전부 `randSeed=0`이다. bake는 `randSeed>0`일 때만 돌기 때문에(PD:380) 건너뛰고, 클라에서 seed 0은 시간 기반이 된다(ZW:25-30). 즉 **이 레벨들은 이미 매 플레이 랜덤 배치**다. 1~3은 명시, 10/20/30은 보스(명시+baked)다.
3. **에디터 분배기 포트 3종이 모두 현 클라 `ShuffleEmptyTiles`와 비트 단위로 다르다.** Python 포트는 구 알고리즘이고, TS 포트는 색상 클러스터 제거 셔플이 빠져 있으며, t0 순회 순서(JSON 키 순서)도 클라와 다르다. 지금은 "에디터에서 굽고 명시 출고"라서 문제가 드러나지 않을 뿐, **클라가 t0를 배정하는 개인화로 가면 바로 드러난다.**
4. **배포 변환(GB `_convert_to_townpop_format`)이 `useTileCount`를 실제 명시 타입 수로 덮어쓰고**(GB:425-451), `pattern_index`·`target_difficulty`·검증 결과·생성 파라미터는 전부 버린다. 버전/해시 개념은 없다(GameBoost `etime`만 있음).
5. **기존 맵의 원래 배치는 시드로 재현할 수 없다.** 따라서 현 명시 맵을 그대로 "기본형/폴백"으로 보존하고, 변형은 별도 필드로 추가하는 방식만 현실적이다(§5).

---

## 1. 시드·useTileCount 사용처와 "굽기" 여부

### 1-1. 백엔드 생성기
| 항목 | 내용 | 근거 |
|---|---|---|
| randSeed 부여 | `_create_base_structure`에서 `random.randint(1,999999)`, useTileCount는 tile_types로 산출 | [사실] GEN:3176-3214 |
| 등껍질 경로 | 같은 규약(`randint(1,999999)`), useTileCount=레벨 그래프값 | [사실] GEN:1980-1989 |
| 재생성 변형 | `randint(100000,999999)`로 새 시드 | [사실] GEN:3084 |
| 시드 RNG 출처 | 전역 `random`. 프로세스풀 워커가 `random.seed(os.urandom(8))`로 재시드 → 생성 전체가 **비결정적** | [사실] backend/app/api/routes/generate.py:124 |
| 생성기의 randSeed 소비 ① | `_ensure_valid_t0_distribution`: t0가 있으면 Python 분배기로 ÷3 검사, 실패하면 **randSeed를 +1씩 바꿔 최대 50회** 탐색 | [사실] GEN:1251, 15176-15281 |
| 생성기의 randSeed 소비 ② | `_diversify_container_inner_tiles`: 필드 t0=0이고 count-only 컨테이너가 있으면 Python 분배기(randSeed)로 내부를 확정한 뒤 필드 타일과 라벨 스왑 → 신포맷 `[cnt,"tX_tY.."]`으로 **굽기** | [사실] GEN:1530-1537, 14096-14229 (조건 14143, RNG 14185) |
| t0 vs 명시 결정 | `get_tile_types_for_level`: 10레벨 주기 중 난이도 최저 3개 위치는 명시 `t1..tN`, 나머지 7개는 `["t0"]` | [사실] GEN:475-512 |
| useTileCount = 인덱스 상한 | 명시 배정 시 `valid_range={t1..t{useTileCount}}`로 필터 | [사실] GEN:4487-4507, 4710-4734 |
| 재생성 경로 | 프론트가 `tile_types=t1..t{steeredTileCount}`를 **명시로** 전달 → 이 경로는 처음부터 명시 생성 | [사실] PD:6373-6378, 6421 |
| 레벨 1~31 고정 | `_load_fixed_level` → `_finish_fixed_level`: 저장본 그대로 + ÷3/finalize tail(`_preserve_pattern`) | [사실] GEN:1035-1042, 1876-1930; 저장소 backend/app/core/fixed_levels.py, backend/data/fixed_levels.json |
| 구 1~3 하드코딩 경로 | `_create_fixed_layout_level_1/2/3`(GEN:3606-3795)과 generate.py 레벨1 직접 반환 코드는 남아 있으나, 지금은 fixed_levels 저장소가 먼저 걸린다 | [사실] GEN:1039 / [추정] 저장소에 1~3이 등록돼 있어 구 경로는 사실상 휴면 |

### 1-2. 프론트 최종 굽기 (실제 배포본을 결정)
- `applyProductionTileVisuals` → `ENABLE_INNER_TILE_BAKE`(true) → `bakeFullBoard` [사실] PD:314, 505-515
- `bakeFullBoard` 동작 [사실] PD:376-449
  1. 레벨 ≤3이거나 `randSeed<=0`이면 return (PD:377, 380) → **고정 t0 레벨 4~31은 미적용 = t0 유지**
  2. `resolveT0TileTypes`(GE:1986-1997 = TS 게임엔진 분배) 결과로 t0와 count-only 컨테이너 내부 타입을 확정
  3. 보드 전체 논리 타입을 `buildVisualIndexMap(usedTypes, levelNumber)`로 1~15 bijective relabel (PD:408, 346-358). **`visualTileSeed` 필드가 아니라 레벨 번호를 시드로 쓴다.**
  4. t0 → `t{v}`로, 컨테이너 → `[cnt,"..."]`(reverse해서 게임 index 0=바닥 규약)로 기록. 미해결 inner는 `[cnt]`로 남긴다(PD:432-442)
- 호출 지점: 생성·재생성·보스·튜너 등 13곳 [사실] PD:1550, 1875, 2782, 4188, 5640, 6051, 6118, 6167, 6514, 6583, 6834, 6991

### 1-3. 실데이터 확인 (최신 LIVE 배치 `batch_1789636723287_uulknmtej` "[LIVE 패치본 3차]", 1530레벨, backend/data/production)
[사실, 읽기 전용 스캔]
- t0 보유 레벨 **25개 = 4~9, 11~19, 21~29, 31**(fixed_levels와 일치). 32 이상은 t0 **0개**
- 분류: explicit+baked 컨테이너 807 / explicit만 628 / **explicit+count-only 컨테이너 70** / t0+count-only 19 / t0만 6
- **count-only 컨테이너 70개(32+)는 전부 randSeed·useTileCount 필드 자체가 없다**(템플릿 출신 `template_id=lp_…`, level_json 키가 `layer, max_moves[, goalCount]`뿐). 배포 시 randSeed가 `"0"`이 되므로(GB:465) **컨테이너 내부는 클라에서 매 플레이 랜덤**이다. → 사용자 사전조사의 "32 이후 스택 내부까지 명시"는 **대부분 맞지만 예외 70개가 있다**(샤드 기준 재확인 권장)
- randSeed 누락은 32+ 기준 102개(위 70 포함), useTileCount 누락도 같은 102개
- per-type ÷3 위반 0건(컨테이너 inner 포함, key 제외)

**결론 1** [사실]: 시드는 **생성 시 소비 후 굽는다**. 출고본에 시드 의존이 남는 곳은 (a) 고정 t0 레벨 4~31(seed 0 = 런타임 랜덤), (b) count-only 컨테이너 레벨(seed 없음 = 0 = 런타임 랜덤)뿐이다.

---

## 2. t0 분배 / visualTileSeed 포팅과 클라 일치 여부

### 2-1. 구현 위치
| 구현 | 위치 | 알고리즘 세대 |
|---|---|---|
| 클라 정본 | CS:1167-1292 `ShuffleEmptyTiles`, CS:1372-1502 `DistributeTiles`, CS:1123-1156 `GetToAddIndexList`, CS:870-945 `GetEmptyTileList`, CS:1307-1354 `ApplyVisualTileRemap`, ZW 전체 | 색상버킷 2단계 + **색상 클러스터 제거 Fisher-Yates**(CS:1210-1217, 2026-04-22 b369c2b8 도입) |
| TS 포트 | TD:127-253 distributeTiles, TD:397-489 assignT0Tiles, TD:333-376 applyVisualTileRemap; 순회/수집 GE:320-526 | 색상버킷 2단계, **클러스터 제거 셔플 없음** |
| Python 포트 | BS:26-109 zWellRandom, BS:123-211 distribute_tiles, BS:275-361 assign_t0_tiles | **구 sp_template 알고리즘**(타입당 최소 1세트 + 라운드로빈, rnd 미사용) |

### 2-2. 비트 재현 위험 요소 (클라 vs 에디터)
| # | 위험 | 근거 | 영향 |
|---|---|---|---|
| R1 | **TS에 클러스터 제거 셔플 없음**: 클라는 DistributeTiles 직후 `for i=n-1..1: j=Rand(0,i)`로 세트 리스트를 섞어 rnd를 더 소비한다 → 이후 위치 셔플 스트림까지 전부 어긋남 | CS:1210-1217 vs TD:423-481 | 동일 시드에서도 배치 다름 [에뮬: 3/3 케이스 DIFF] |
| R2 | **Python 분배기가 구 알고리즘**: 색상버킷 아님, rnd 미사용. 타입별 세트 수부터 다름 | BS:123-211 vs CS:1372-1502 | [에뮬] (30,u6,s12345) C#형 {t3:3,t5:3,나머지 6} vs py {t5:3,t6:3,나머지 6}. 생성기 seed 탐색(GEN:15176)과 inner bake(GEN:14160)가 이 포트를 씀 |
| R3 | **t0 순회 순서**: 클라는 레이어 0..N, 각 레이어 `CTileList`(Dictionary) 삽입 순서 = 배포 JSON 키 순서. 배포 시 GB가 키를 row-major `(row,col)`로 재정렬한다(GB:365-375, 403). 에디터는 저장된 생성 순서 그대로 `Object.entries` 순회 | CS:880-903, GE:349; GB:403 | **LIVE 배치 1530개 중 1424개가 저장 순서 ≠ row-major** → 같은 시드라도 어느 위치가 어떤 타입이 되는지가 다르다 |
| R4 | `GetToAddIndexList` 입력 차이: 클라는 컨테이너 내부 **명시 ID와 key/t16까지** 전부 센다(`GetEmptyTileList(true)`). TS는 필드 `/^t\d+$/`만 세서 baked inner, `"key"` 문자열이 빠진다. Python은 호출부마다 다르다 | CS:1129-1138 vs GE:398-404, TD:293-314 | 혼재 레벨에서 toAdd 리스트 상이 |
| R5 | TS 1.5단계 자동보정: 총합 비÷3이면 컨테이너 개수를 줄이고 goalCount를 수정한다. 클라에는 이 동작이 없다 | GE:408-478 | 비÷3 입력에서 에디터≠클라 |
| R6 | 기본값 차이: TS `useTileCount` 미지정 시 6, `randSeed` 미지정 시 **42**. 클라는 useTileCount 0이면 스킨 타일 수-1, seed 0이면 시간 기반. 시간 기반 seed도 TS=`Date.now()` ms, Py=`time.time()` s, C#=2021-01-31 기준 초. 음수 seed: TS/Py는 `>0`이 아니면 시간 기반(TD:413, BS:309), C#은 `(uint)` 캐스팅으로 결정적 고정 시드(01 §2) | GE:482-489, TD:25-27, BS:40-43, ZW:25-30, CS:1190-1193 | 필드 누락 레벨(위 102개)의 에디터 미리보기·봇 결과는 실제와 무관 |
| R7 | 불균형 반올림: 클라 `Mathf.RoundToInt`(.5 → 짝수) + float 연산, TS `Math.round`(.5 → 올림) + double 연산 | CS:1417 vs TD:172 | typeImbalance>0일 때만 영향. 현재 배포값은 전부 ''/0 [사실: 샤드 levels 테이블] |
| R8 | 필드명 불일치: TS 엔진은 `xShuffleTile`/`xTypeImbalance`를 읽고 GB·클라는 `shuffleTile`/`typeImbalance`를 쓴다 | GE:491-494 vs GB:474,491 / CS:1566,1574 | 값이 0이 아니게 되면 에디터와 클라가 다른 파라미터로 분배 |
| R9 | `ApplyVisualTileRemap` 스킵 조건: 레벨 스킨에 icon order가 있으면 리맵을 건너뛴다 → 에디터 포트에 없는 분기 | CS:1312, TileSkinRotation.cs:135-139 | visualTileSeed 미리보기와 인게임 불일치 가능 |
| R10 | `isKeyTile`이 `xEffect=="key"`인 색타일도 16으로 센다 | CS:234, 259-262 | 생성기가 key 속성을 제거하고 있음(GEN `_repair_key_gimmick`). 개인화 변형에서도 같은 가드 필요 |

일치하는 부분 [사실]: zWellRandom 수식(TS/Py 모두 uint32 마스킹, `Rand(s,e)` 양끝 포함, 기본인자 동작), stack inner 순서(에디터 stackIdx n-1 → 클라 index 0, GE:371-383 / PD:438-441 / CS:157-158), visualTileSeed 리맵 수식(골든 459838 → 4,1,7,9,12,3 / 12345 → 9,5,3,8,2,14, claudedocs/CHANGELOG_20260630_VISUAL_TILE_SEED.md:30).

### 2-3. visualTileSeed: 비주얼 전용인가?
- 클라: 배치 RNG 소비가 끝난 뒤 **별도 RNG**로, **t0 출신 타일(emptyTiles)만** 1:1 relabel한다 [사실] CS:1289-1291, 1307-1354
- **순수 t0 레벨이면 비주얼 전용**이다(bijective라 매칭 구조 불변)
- **혼재(t0+명시가 타입 공유) 레벨이면 논리에 영향**: t0쪽만 바뀌어 트리플이 깨지고 클리어 불가가 된다 [사실] DESIGN_LEVEL_MAP_SCHEMA.md §4-1 "한계", CHANGELOG_20260630:65-69. 에디터는 순수 t0에만 베이크하도록 가드한다(PD:490-497, 단 이 함수는 `ENABLE_INNER_TILE_BAKE=true`라 현재 미호출)
- **현재 배포본 visualTileSeed 실효 0건** [사실: 샤드 levels 테이블 `visualTileSeed=''` 전 행, LIVE 배치에도 키 없음. 보정(01 §2): 빈 문자열도 `xHasVisualTileSeed=true`가 되지만 전 레벨 스킨이 icon_order를 가져 리맵이 조기 return → 실효 없음]. 지금 비주얼 다양화는 bakeFullBoard의 `seed=levelNumber` relabel로 처리한다
- [추정] 개인화에서 t0 레벨에 visualTileSeed를 쓰려면 **명시 타일 0개(순수 t0)를 보장**하거나 클라 리맵을 "명시 사용 인덱스 제외"로 고쳐야 한다(게임측 TODO)

---

## 3. 내보내기/배포 경로별 필드 유지·소실

### 3-1. 경로
1. **GameBoost 업로드**(주 배포): `ProductionExport` → `saveToGBoost` → `POST /api/gboost/{board}/{id}` → `_convert_to_townpop_format` → GameBoost [사실] ProductionExport.tsx:884-900, GB:113-175, 377-499
   - 업로드 직전 주입: rewardCoin/autoCollectCount 오버라이드, `meta.predicted_clear_rate` → payload (ProductionExport.tsx:884-896)
2. **로컬 업로드**: `POST /api/gboost/upload-local`(storage/local_levels/*.json) → 같은 변환 [사실] GB:866-1000
3. **파일 내보내기**: `exportProductionLevels` → level_json(+meta는 include_meta 옵션) JSON 다운로드 [사실] ProductionExport.tsx:510-555, storage/productionStorage.ts:~737-790
4. **"서버 동기화"** = 같은 머신의 백엔드 로컬 파일 저장소 `backend/data/production/{batch}.json` + `_index.json`. 프론트 구조를 opaque JSON으로 그대로 저장(meta+level_json 전부 유지) [사실] backend/app/api/routes/production_store.py:1-60. 원격 서버가 아니다
5. **게임 샤드**: 게임측 `LevelMapBakeTool`이 GameBoost `real_array`를 받아 굽는다 → `StreamingAssets/GBoost/a{MD5("levelmap_level_N")}.txt`(map만) + `a{MD5("levels")}.txt`(메타 23컬럼) + `levelmap_etime` [사실] DESIGN_LEVEL_DATA_DELIVERY.md §3, LevelMapProvider.cs:26-30, 232-247

### 3-2. GB 변환 시 유지/소실 [사실] GB:456-497
| 유지(출고 필드) | 비고 |
|---|---|
| `map`(layer_i: col,row,tiles,num) | tiles 키 row-major 재정렬(GB:403) |
| `randSeed` | 없으면 `"0"` (GB:465) |
| `visualTileSeed` | 있을 때만 (GB:468-472) |
| `useTileCount` | 🔴 **저장값이 아니라 "필드 명시 t1~t15 distinct 수"로 재계산**. t0/컨테이너 inner는 제외, 명시가 없을 때만 저장값 (GB:425-451) |
| `unlockTile, shuffleTile, shuffleLayer, typeImbalance, timea, col, row, rewardCoin, autoCollectCount, tileSkin, backgroundIndex, useInRandomizer, teleport*` | |
| `difficulty` | `predicted_clear_rate×100`(없으면 -1)로 용도 전용 (GB:475-482) |
| `num, sets, layer(활성 레이어 수), rewardList, etime` | 계산값 |

| 소실 | |
|---|---|
| 생성 파라미터 일체: `target_difficulty, pattern_index, pattern_type, symmetry_mode, _unit_assembly, _tile_type_profile, _boss_template_id, _turtle_*, reverse_generated, template_id` | level_json 키는 있으나 미출고 |
| `max_moves, goalCount` | goalCount는 계산만 하고 미출고(GB:419-421) |
| 검증/난도 결과: `bot_clear_rates, match_score, rl_classification, solver_verdict, mc_measurement, verification_*` | meta 전용. predicted_clear_rate만 difficulty로 출고 |
| 생성 알고리즘 버전 | 원래 존재하지 않음(§6) |
| 원래 t0 위치 정보 | bake 시점에 소실(§5) |

### 3-3. 원본 vs 로컬 샤드 비교 [사실, 복호화 후 읽기 전용 비교]
- 샤드: `levels` 테이블 3066행(level 1530 + infinity 1030 + test 500 + tmp 5 + event1 1, 01 §1 보정), `levelmap_etime` 최대 **2026-09-18 11:43:38** = LIVE 3차 배치 저장 시각(09-18 11:43)과 일치
- 맵 비교(1~1530): **1496 동일 / 34 상이**. 상이한 34개 중 33개(32~34, 36~44, 46~49, 61~64, 66~71, 73~79)는 **2차 배치와 동일**하다 → 에디터 3차에서 재생성됐으나 샤드(=GameBoost에 올라간 것)는 2차 버전. Lv341은 2차·3차 모두와 다르다
- 메타: randSeed 상이 1건(Lv34: 샤드 809853 / 에디터 427303)
- [추정] 에디터 최신본 일부가 GameBoost에 재업로드되지 않았거나, 샤드 굽기 이후 에디터 측이 변경된 상태다. 개인화 작업 기준 데이터는 **GameBoost(배포) 정본**을 쓰는 편이 안전하다
- 저장 위치: 에디터 원본 = `backend/data/production/*.json`(1.6GB, 436배치) + 브라우저 IndexedDB(productionStorage.ts), 고정 레벨 = `backend/data/fixed_levels.json`, 패턴 = `backend/data/patterns.db`(+custom_patterns.json)

---

## 4. 스택/크래프트/키타일 내부 ID 생성·저장과 정합성

- **저장 포맷** [사실]: 구포맷 `[cnt]`(내부 전부 t0, 런타임 분배) / 신포맷 `[cnt,"id0_id1_.."]`(index 0=바닥, 개수가 맞을 때만 채택하고 틀리면 t0 폴백). 게임 v1.10.382+ 지원 (CS:157-168, 190-212)
- **생성 경로** [사실]
  - 백엔드: 필드 t0=0인 레벨만 Python 분배(R2 포트) → 필드와 라벨 스왑해 신포맷으로 굽고, ÷3이 깨지면 롤백 (GEN:1530-1537, 14096-14229)
  - 프론트: bakeFullBoard가 남은 count-only 내부를 TS 분배로 굽는다. 미해결이면 `[cnt]` 유지 (PD:421-442)
  - key: `unlockTile>0`이면 분배기가 마지막 unlockTile개 세트를 16(key)으로 채운다(CS:1495-1499 / TD:248-250). baked 문자열에는 `"key"`로 기록(PD:430)
- **혼재 정합성 규칙** [사실]
  - 클라 `GetEmptyTileList(false)`: 필드 t0 + 컨테이너 내부 중 **t0인 슬롯만** 분배 대상 (CS:880-903)
  - `GetToAddIndexList`: 명시 타입(필드 + 컨테이너 명시 inner + key) 각각의 mod3 결손을 **t0 앞부분으로 먼저 채운다** (CS:1123-1156, 1229-1236)
  - 이어서 `emptyTilesLength/3` 세트를 t1..t{useTileCount}로 배정. 불변식: `(명시 총합 + t0 수) ≡ 0 (mod 3)`이면 전 타입 ÷3이 보장된다 (메모리 modifications_log 2026-06-16 증명, GEN `_finalize_divisibility_guarantee` 15429~)
- **개인화 함의** [추정]
  - t0 세트는 `t1..t{useTileCount}`만 쓴다. 명시 타일이 `> useTileCount` 인덱스를 쓰면 toAdd로만 보충된다 → useTileCount ±1 변형 시 **명시 타입과의 공유/분리 구조가 달라진다**
  - 컨테이너 inner를 변형 대상에 넣으려면 구포맷 `[cnt]`로 되돌려야 클라가 배정한다. 신포맷 명시를 남기면 그 슬롯은 고정된다
  - key가 섞인 baked 컨테이너는 ÷3 계산에서 key를 제외해야 한다(GEN:1520-1529 사고 사례 Lv336)

---

## 5. 고정 맵 t0화 시 원래 배치 재현 가능성 + 보존안

### 5-1. 재현 불가 근거 [사실]
1. 명시 타일 상당수는 처음부터 생성기가 명시로 만들었다(재생성 경로 PD:6377, 역생성 628개 `reverse_generated`, 템플릿 102개). 전역 `random`이 os.urandom으로 재시드되므로 시드 정보가 남지 않는다 (generate.py:124)
2. t0 출신 타일은 bake로 명시 ID에 덮였고, **어느 위치가 원래 t0였는지 기록이 없다**(PD:418-420)
3. 이후 `seed=levelNumber` relabel까지 거쳤다(PD:408)
4. bake에 쓴 TS 분배기는 현 클라와 다르고(R1), 순회 순서도 다르다(R3). 같은 (randSeed, useTileCount)를 클라에 줘도 원래 배치가 나오지 않는다
5. 고정 4~31은 seed 0 = 원래부터 매 플레이 랜덤이라 "원래 배치" 자체가 없다

### 5-2. 기존 맵 보존 방안 후보 [추정/제안]
| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. 현 `map` 불변 + 변형 별도 필드** | `map`=현 명시본(기본형/폴백). 신규 선택 필드(예: `variants`)에 변형 목록 추가. 구 클라는 무시 | 롤백 0비용, 구버전 호환, 데이터 손실 없음 | 클라 신규 파싱 필요 |
| **A-1. 변형을 명시 맵으로 굽기** | 에디터가 (utc, seed)마다 명시 배치를 계산해 `[{id, utc, seed, tilesTypesOnly}]` 저장. 위치는 공유하고 타입 배열만 저장해 용량 절감 | **클라 RNG 포팅 불필요 → R1~R8 위험 제거**, 검증본 = 배포본 보장 | 용량 증가(레벨당 타입 문자열 × N), 델타 갱신 단건 크기 증가 |
| A-2. t0 템플릿 + 시드 목록 | `mapT0`(타입 제거본) + `[ {utc, randSeed} ]`. 클라 ShuffleEmptyTiles로 생성 | 용량 최소 | **에디터 포트를 클라와 비트 일치시켜야 함**(R1~R8 전부 수정 + 골든 테스트 필수) |
| B. 현 맵을 variant 0으로 명시 등록 | A의 목록에 현 명시본을 `{id:0, source:"legacy"}`로 포함 | 클라 선택 로직 단순화 | — |
- 공통 [추정]: 고정 4~31(seed 0)은 결정적 시드로 고정해 굽거나, 현행 런타임 랜덤을 유지할지 **정책 결정이 필요**하다. 레벨 1~3은 bake 제외 정책(PD:377)이 이미 있다
- 공통 [사실 기반 제안]: 변형 생성 시 GB `useTileCount` 재계산(GB:425-451)을 변형별 값 보존으로 바꿔야 한다

---

## 6. 버전/해시 개념 존재 여부

- **생성 알고리즘 버전 필드 없음, 맵 해시 없음** [사실] backend/app·frontend/src에서 `generator_version|algo_version|level_hash|map_hash|hashlib` 등 검색 결과 0건(관련 없는 `levelHasHeaderOob`만 매치)
- 존재하는 유사 개념 [사실]
  - GameBoost 행 `etime`(업로드 시각, GB:493) → 게임 델타 갱신/샤드 재굽기 비교용(LevelMapProvider, LevelDeltaUpdater)
  - 배치 저장소 `version`(저장 카운터, production_store `_index.json`)
  - 주석상 버전 태그(v15.xx/v16)와 게임 빌드 게이트 상수 `ENABLE_INNER_TILE_BAKE`(PD:311-314)
  - level_json 마커: `_fixed_level, _turtle_peel, _unit_assembly, reverse_generated, _boss_template_id` (생성 모드 식별용이며 미출고)
- [제안] 변형마다 `distVersion`(분배 알고리즘 세대: 예 `cs-2026-04-22-cluster`)과 `typesHash`(정규화 맵 → 타입 배열 해시)를 넣는다. 클라가 자기 알고리즘 세대와 다르면 해당 변형을 버리고 기본형으로 폴백하게 한다

---

## 7. 에디터→클라 동일 배치 검증 방법 제안 [제안]

1. **정규화 입력 정의**: 배포 변환 후 JSON(GB 출력: row-major 키, 실제 출고 useTileCount/randSeed/unlockTile/shuffleTile/typeImbalance)을 단일 정본 입력으로 쓴다. 에디터 검증도 **반드시 이 정규화본**으로 돌린다(R3 차단)
2. **골든 벡터(크로스 언어)**: `tests/golden/t0_dist/*.json` = {input map, params} → 기대 출력 = emptyTiles 순서대로 배정 ID 배열. 클라는 Unity EditMode 테스트로 `ShuffleEmptyTiles`를 실행해 덤프한 값을 정답으로 생성하고, TS(vitest)·Python(pytest)이 같은 값을 내야 통과
   - 케이스: 순수 t0 / 혼재(명시 mod3 결손) / count-only 컨테이너 / 신포맷 inner / unlockTile 1·2(key) / typeImbalance>0(.5 반올림 경계) / shuffleTile>0 / useTileCount 1·3·4·15 / seed 1·2^31-1 / 레이어 다수 + 비정규 키 순서 입력
   - zWellRandom 단독 벡터(seed별 첫 1000개 `_rand()`)도 포함
3. **해시 비교**: `sha256(정규화된 (layer,pos,stackIdx)→typeId 리스트)`를 에디터가 변형별로 저장·출고한다. 클라는 배정 직후 같은 해시를 계산해 불일치 시 폴백 + 로그/MMP 이벤트 발행(침묵 금지 원칙, DESIGN_LEVEL_DATA_DELIVERY §7)
4. **전수 회귀**: 배포 전 배치 전체(1530 × 변형 N)를 Unity 배치모드(헤드리스)로 돌려 해시를 덤프하고, 에디터 해시와 diff 0이 아니면 배포를 차단한다
5. **A-1안 채택 시**: 클라는 RNG 없이 타입 배열을 그대로 적용하므로 검증은 해시 1단계로 축소된다(권장)

---

## 미확인 (추가 조사 필요)
- 클라 SimpleJSON `JSONObject`의 키 순서 보존이 모든 플랫폼(IL2CPP/Mono)에서 보장되는지 (Dictionary 삽입 순서는 구현 의존). R3 판단의 전제
- 에뮬 결과(§2-2 R1·R2)는 C# 코드를 Python으로 옮긴 재구현 기준이다. Unity 실제 실행 덤프와의 대조는 미실시
- 레벨 341 맵이 2차·3차 배치 모두와 다른 원인(배치 외 경로로 업로드?)
- GameBoost 서버 현재 데이터(real_array)와 샤드의 일치 여부. 서버 조회는 범위 밖이라 미실시. 샤드 etime 최대값은 2026-09-18
- ~~`levels` 메타 테이블 `timea=0`의 의미~~ → 해소(01 §9-4): 0 = 시간제한 없음, timea>0은 level_341(180초)뿐
- infinity_* 1030행의 원본 매핑과 개인화 적용 범위(클라 선택 로직은 01 §9-4)
- 브라우저 IndexedDB 내용과 backend/data/production 파일의 최신성 차이(브라우저 직접 조회 안 함)
- 템플릿(`lp_*`) 출신 102개 레벨의 원본 출처와 randSeed 부재가 의도된 것인지
- 구 1~3 하드코딩 경로(generate.py:~925, GEN:3606-3795)가 fixed_levels 미등록 시 실제로 타는지(저장소에 1~3 등록되어 있어 현재는 미사용으로 추정)
