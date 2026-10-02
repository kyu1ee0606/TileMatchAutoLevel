# 01. 게임 클라이언트 조사 노트 — 레벨 난도 개인화 사전조사

- 대상: `/Users/casualdev/sp_meowsgarden` (HEAD `66d725c3`, 워킹트리에 미커밋 변경 있음 — 프리팹/씬 위주, 조사 대상 스크립트 아님)
- 조사일: 2026-10-02 · 조사 방식: 코드 직접 확인 + baked 데이터 파일 읽기 전용 디코드 (`/tmp`에서 스크립트 실행 후 삭제)
- 표기: **[코드]** = 코드/데이터로 확인된 사실(경로:줄) · **[추정]** = 해석/제안 · 경로 접두 생략 시 `Assets/08.Scripts/Tile_Script/InGame/`

---

## 0. 요약 (TL;DR)

1. **레벨 데이터는 사실상 100% 빌드 내장(baked)**. 메타 테이블(`levels`)과 맵 샤드 모두 StreamingAssets. 런타임 서버 갱신(델타)은 v1.10.1025 에서 비활성화 → **레벨 수정·변형 배포 = 앱 빌드 배포**. 핫픽스 불가.
2. `randSeed`=**0이면 시간 기반 시드**(초 단위) → 매 판/재도전마다 배치가 달라짐. 음수는 시간 기반 아님((uint) 캐스팅된 고정 시드).
3. `ShuffleEmptyTiles`는 **t0 타일(보드 + 스택/생성기 내부)에만** 종류를 배정. 명시 타일(t1~t15)은 건드리지 않음 → **t0 없는 맵에서는 randSeed/useTileCount 변경이 논리 배치에 영향 0**.
4. **사용자 조사 결과 부분 불일치**: 1~31 중 25개 t0 ✔, 1501~1530 t0 없음 ✔, **32~1500은 70개 레벨에 t0 존재**(전부 구포맷 스택/생성기 내부 `[count]`) ✘. 이 70개는 전부 `randSeed=0` → 현재 **매 판 랜덤**.
5. `visualTileSeed`는 현재 **실질 무효**: baked 값이 전부 `""`이지만, 모든 레벨이 `icon_order`를 가진 스킨(0/1)을 쓰므로 `ApplyVisualTileRemap`이 조기 return.
6. **진행 중 판 저장/재개 없음**. 재도전 = 맵 재로드 + `ShuffleEmptyTiles` 재실행. 부활 = 보드 유지.
7. 이벤트는 단일 진입점 `MmpEvents.Log` → AppsFlyer + Firebase Analytics. 변형ID/시드/종류수 파라미터 추가 용이.
8. **원격 설정은 GBoost uconfig(전역 값)뿐**. Firebase Remote Config 없음. A/B 프레임워크(`FeatureToggle`)는 템플릿 코드로 존재하나 런타임 미배선.

---

## 1. 레벨 로딩 경로 (출처·버전·오프라인·폴백)

### [코드] 두 개의 데이터 원천
| 데이터 | 내용 | 위치/로딩 |
|---|---|---|
| 메타 테이블 `levels` | 레벨 행(randSeed, useTileCount, visualTileSeed, unlockTile, shuffleTile, timea, num, layer …) — **map 컬럼 없음** | GBoost baked `StreamingAssets/GBoost/a{md5("levels")}.txt`. `LevelController.InitLevelDB` 가 `Real_LoadArray(..., GBRealArray.No)` 고정 (`LevelController.cs:422-427`) → `Real_LoadArrayLocal` (`00.spComponents/spGBoost/spGBoostMng.cs:2577-2633, 2650-2653`) |
| 맵 샤드 | `levelId → map` (레이어/타일) | `StreamingAssets/GBoost/a{md5("levelmap_{prefix}_{(idx-1)/100}")}.txt`, 샤드당 100레벨 (`LevelMapProvider.cs:24-27, 233-247`) |

- 테이블 서버 로드 제거 사유 주석: 출시 직후 5.2MB 동시 요청으로 서버 다운 → baked 전용, "신규/수정 레벨은 다음 빌드의 baked 갱신으로만 반영(핫픽스 불가 = 의도된 트레이드오프)" (`LevelController.cs:422-426`).
- 레벨 진입 시 `LoadLevel` 이 boot 캐시 `m_jsonData[levelKey]` 를 **ToString→Parse 딥카피** 후, 행에 map 이 없으므로 `LevelMapProvider.GetLocalMap` → 없으면 `EmergencyLevelMap.Get()` (`LevelController.cs:764-800`). 이후 `UpdateNewMapData` → `ShuffleEmptyTiles` (`LevelController.cs:656`, `DB_Level.cs:1608`).

### [코드] LevelMapProvider 폴백 체인 (`LevelMapProvider.cs:1-19, 84-132`)
L1 델타 캐시(`LevelMapDelta.dat`, persistentDataPath, 암호화) → L2 baked 샤드 → L0 서버 단건 → L3 최근접 인덱스(±50) → L4 비상 레벨(4×4, 9타일).
- `IsPlayableMap`: layer≥1 && 타일 수≥3 (`LevelMapProvider.cs:60-78`).
- L0 "서버 단건"도 `GBRealArray.No` 로 고정 (`LevelMapProvider.cs:305-315`) → 실제로는 로컬 baked 테이블 행을 읽음(그 행엔 map 없음) ⇒ **사실상 네트워크 미사용**.
- 델타 갱신 `LevelDeltaUpdater.SyncInBackground()` 호출 주석 처리 (`LevelController.cs:377-380`). 호출처 없음.
- L2 샤드 메모리 캐시 최근 2개 (`LevelMapProvider.cs:44-47, 259-287`), 실패 결과는 캐시하지 않음.

### [코드] 버전/해시 관리
- 레벨별 서버 수정시각 `etime` 스냅샷을 `levelmap_etime` 파일로 함께 베이크 (`TemplateScripts/LevelMapBakeTool.cs:98, 115`). 델타 비교용(`LevelMapProvider.cs:146-186`) — 델타 비활성이므로 현재 런타임 사용 없음.
- 레벨별 콘텐츠 해시/버전 필드 없음. 버전 = 앱 빌드.
- 베이크는 에디터 메뉴 `SP/GBoost/레벨 맵 굽기` 수동 실행 (`LevelMapBakeTool.cs:26-33`), 소스 `real_array.php` 전체 다운로드, playable 99% 미만이면 저장 거부 (`:29-30, 98-104`).

### [코드] 파일 형식 (읽기 전용 디코드로 확인)
- 샤드/테이블: `spZip.EncryptBytes` = ZIP(SharpZipLib, 엔트리 "data", level 9) → 키 XOR(LCG 위치 순회) (`00.spComponents/spZipUtil/spZip.cs:117-137, 180-206`). 복호: `spStreamingAssets.LoadDecZIP` (`00.spComponents/spFile/spStreamingAssets.cs:199-203`).
- 테이블 구조: `{"__keys":[...], "__vals":[[row]...], "__encrypts":", autoCollectCount,"}`.
- 실측(파일 mtime 2026-09-18 11:44, etime 최대 2026-09-18 11:43): `level` 1530행(1~1530, 샤드 16개), `infinity` 1030행(샤드 11), `test` 500, `tmp` 5, `event1` 1. **메타 있는데 샤드 없는 level 0건**.
- 샤드 맵 예 (`level_1`): `{"layer":"1","layer_0":{"col":"3","row":"3","tiles":{"0_0":["t1",""],...},"num":"9"}}` — 수치도 문자열.

### [추정]
- 변형 배포 방식은 "빌드에 변형 데이터 동봉"이 유일한 현실적 경로. 서버 경로 재활성화는 출시 트래픽 사고 이력이 있어 별도 결정 필요.
- 샤드 1개 ≈ 12.5KB(압축) — 변형 K개 추가 시 용량 영향 작음(맵 구조 공유, 배정만 다르면 더 작게 설계 가능).

---

## 2. randSeed / useTileCount / visualTileSeed 의 클라이언트 사용처

### [코드] 파싱
`CLevelList` 생성자 및 `UpdateNewMapData` 에서 동일하게 읽음 (`DB_Level.cs:1060, 1071, 1076-1080` / `1562, 1573, 1578-1582`).

| 필드 | 사용처 | 영향 |
|---|---|---|
| `randSeed` | `ShuffleEmptyTiles` 의 `zWellRandom` 시드 (`DB_Level.cs:1171`), `GetTileTypeRarity` 프리뷰 (`:1526`) | **논리 배정**(t0 종류 + 위치 스왑). t0 없으면 무영향 |
| `useTileCount` | `DistributeTiles` 의 tileTypeCount (`:1193, 1208`); 정적 난이도 합산 (`:645`) | **논리 배정**(t0 에만). `<=0` 이면 `TileSetting.GetTileCount(tileSkin)-1` 사용 (`:1190`, `:865-868`) |
| `visualTileSeed` | `ApplyVisualTileRemap` (`:1307-1354`) | **비주얼만**(t0 출신 타일의 1:1 종류 재매핑 → 매칭 구조 불변) |
| `teleportRandSeed` | `TileGroup.cs:2038` 에서 생성만 하고 **실제 셔플은 `System.Random`(무시드)** 사용 (`TileGroup.cs:2040, 2070-2074`) | 런타임 텔레포트 — 비결정 |
| `typeImbalance` | `AsInt / 10f` (`:1208`) — **정수로 읽음**(0~10 → 0~1.0). baked 값 전부 `""` → 0 | 논리 배정(t0) |
| `shuffleTile` | 2차 스왑 추가 횟수 (`:1271`) — baked 전부 0 | 논리 배정(t0) |
| `unlockTile` | `DistributeTiles` specifiedCount → 키타일(16) 세트 수 (`:1204, 1496-1499`) | t0 있을 때만 키타일 생성. baked 56레벨이 1 이지만 그 레벨들엔 t0 없음 → 무효 |

### [코드] randSeed=0 시간 기반 경로
- `zWellRandom.Seed(0)` → `seed = (uint)(DateTime.Now - 2021-01-31 로컬).TotalSeconds` (`00.spComponents/zWellRandom.cs:25-30`). **초 단위** → 1초 이상 지나 재로드하면 다른 배치.
- 판정은 `seed == 0` 만. `randSeed < 0` 은 `(uint)` 캐스팅으로 고정 비영(非零) 시드 → **결정적** (`DB_Level.cs:1171`). `:1173-1180` 의 `<= 0` 분기는 로그용 `curRandSeed` 만 계산(미사용).
- 실제 사용 시드는 `KLogger.LogError` 로그만 (`DB_Level.cs:1184`), 분석 이벤트로 전송 안 됨.

### [코드] visualTileSeed 가 현재 무효인 이유
- baked 테이블 `visualTileSeed` 값이 1530개 전부 `""`(빈 문자열). `jsonEvent["visualTileSeed"] != null` 은 JSONString("") 에 대해 true → `xHasVisualTileSeed = true` (`DB_Level.cs:1076-1080`, 테이블→객체 변환 `spGBoostMng.cs:2552-2573`).
- 그러나 `TileSkinRotation.HasIconOrderForLevelID(levelId)` 가 true 면 리맵 생략 (`DB_Level.cs:1312`; `TileSkinRotation.cs:135-139`). baked `tileSkin` 테이블: 스킨0 `icon_order="1,4,7,10,13,2,5,8,11,14,3,6,9,12,15"`(pingpong), 스킨1 `icon_order` 있음(fixed). `tile_skin_setting` 은 1~∞ 레벨 전부 스킨 0/1 cycle → **모든 레벨에서 리맵 생략**.
- 대신 논리 ID 는 보존되고 렌더 단계에서 스킨별 아이콘 순서 적용 (`TileSkinRotation.cs:100-112`, 문서 `DESIGN_TILE_COLOR_BALANCE.md:11`). pingpong 은 스킨 등장 횟수 홀짝으로 역순 (`TileSkinRotation.cs:114-133`).

### [추정]
- `useTileCount` 메타 신뢰도 낮음: 32~1530 중 57레벨은 명시 타일의 실제 종류 수 ≠ `useTileCount` (예: level_111 실제 12종 / 메타 11). 에디터는 "실제 종류 수"를 맵에서 재계산해야 함.
- 비주얼 아이콘 순서(5색×3)가 사람 기준 난도(색 유사도)에 영향 줄 수 있음 → 변형 설계 시 "논리 배정"과 "아이콘 매핑"을 분리 관리 권장.

---

## 3. ShuffleEmptyTiles 알고리즘 정밀 기술 (`DB_Level.cs:1167-1292`)

### 3-1. 호출 시점 [코드]
- `UpdateNewMapData` 에서만 호출 (`DB_Level.cs:1608`). `CLevelList` 생성자 쪽 호출은 주석 (`:1101`).
- `LoadLevel` 마다 새 `CLevel` 생성 → 매 진입/재도전마다 1회 실행 (`LevelController.cs:656`).

### 3-2. 입력 수집 [코드]
1. `random = new zWellRandom((uint)randSeed)` — **단일 인스턴스**가 이후 모든 배치 난수 소비 (`:1171, 1181`).
2. `emptyTiles = GetEmptyTileList(false)` (`:870-920`):
   - `for i in 0..cLayerList.Count-1: layer_{i}` 순, 레이어 내부는 `xTiles`(Dictionary) **삽입 순서 = 맵 JSON 키 순서**.
   - `tileIDNum == 0` 이면 추가. `tileIDNum` = `spInteger.Parse` 숫자 추출("t0"→0, "t12"→12), key 판정 시 16, stack/craft 루트(`stack_e` 등)는 -1 (`:230-271`, `00.spComponents/spInteger.cs:9-35`).
   - 루트(-1)면 `xTileStackInfo.stackCTileList` 를 index 0(바닥)부터 순회하며 `tileIDNum==0` 인 내부 타일 추가 → **스택/생성기 내부 t0 은 루트 위치에서 인라인 삽입**.
   - 키(effect "key" 또는 tileID "key")는 tileIDNum 16 → empty 아님.
3. `toAddIndexList = GetToAddIndexList(cLevel)` (`:1123-1156`): `GetEmptyTileList(true)`(스택 루트 대신 내부 전체, 일반은 자기 자신) 의 **명시 타일** 종류별 개수 `% 3 != 0` 이면 부족분 `(3-r)` 만큼 해당 종류 id 를 i=1..16 순서로 추가. (t0, -1 제외)
4. `maxTileIndex = useTileCount > 0 ? useTileCount : GetUsingTileCount()-1` (`:1190-1193`).
5. `emptyTilesLength == 0` 이면 즉시 return (`:1202`) — RNG 소비 없음, visual 리맵도 없음.

### 3-3. 종류 리스트 생성 — `DistributeTiles(setLength = emptyLen/3, tileTypeCount = maxTileIndex, specifiedCount = unlockTile, imbalance = typeImbalance/10f, rnd)` (`:1372-1502`)
- `nonSpecifiedTotal = max(0, setLength - specifiedCount)`.
- `activeColors = ceil(tileTypeCount/3)`, `colorCap[c] = clamp(tileTypeCount - 3c, 0, 3)`.
- 1-A: `colorSet[c] = nonSpecifiedTotal * colorCap[c] / totalCap` (정수 나눗셈).
- 1-B: 잔여 `remainder` 를 `colorSet[i % activeColors]++` (rnd 미사용).
- 1-C: imbalance>0 && activeColors>1 이면 `delta = RoundToInt(base*imb*3.0*norm)` 적용 후 결정론적 재보정 (Mathf.RoundToInt = banker's rounding 주의).
- 2단계: 색상 c 마다 `quotient = sets/cap, rem = sets%cap`. `rem>0 && cap>1` 일 때만 `order=[0..cap-1]` 를 **`for i=cap-1..1: j=rnd.Rand(0,i)` Fisher-Yates** 로 섞고 앞 `rem` 개 +1. → **rnd 소비 발생 지점 #1**.
- 출력 순서: 색상 c 오름차순 → 색 내 o 오름차순, `tileId = 3c + o + 1` 을 `tilePerSlot[o]` 회 반복. 마지막에 `16` 을 specifiedCount 회.
- 결과 길이 = 세트 수 (원소 1개 = 3타일 1세트).

### 3-4. 전역 셔플 + 배정 + 스왑
- **rnd 소비 #2**: `for i = list.Count-1 .. 1: j = random.Rand(0, i); swap` (`:1211-1217`).
- `TileTypeRarityScore += 1 / (id*3)` — 정수 나눗셈이라 항상 0 (부작용 없음, `:1220-1223`).
- 배정 (`:1229-1255`): `i=0..emptyLen-1` 순서로 `toAddIndexList` 가 남아 있으면 앞에서부터 그 id(패딩) 배정, 아니면 `randomTileIndexList[setCount/3]` 배정 후 `setCount++`. ⇒ **같은 세트 3개가 emptyTiles 상 연속 3칸에 들어감**.
- **rnd 소비 #3**: `for i in 0..(emptyLen + shuffleTile - 1): r1 = Rand(0, emptyLen-1); r2 = Rand(0, emptyLen-1); swap(tileID)` (`:1271-1287`). r1==r2 허용. effect 는 스왑 안 함(타일 위치 고정, 종류만 이동).
- 비주얼 리맵 (`:1291`, 별도 RNG — §2).

### 3-5. 3의 배수 보장 방식 [코드]
- 명시 타일은 `toAddIndexList` 패딩으로 종류별 3배수가 되도록 **t0 일부를 그 종류로 소모**.
- 나머지 t0 는 세트 단위(3개씩)로 배정. **t0 총수 - 패딩 수가 3의 배수라는 가정에 의존**(검증 코드 없음). 아니면 마지막 세트가 1~2개만 놓여 클리어 불가 가능.
- 세트 수 `setLength` 는 패딩 포함 `emptyLen/3` 으로 계산 → 패딩이 있으면 끝 세트 일부 미사용(낭비지만 무해).
- 실측: t0 를 가진 95개 level 모두 명시 타일 종류별 개수 3배수(패딩 0) — 32+ 70개 확인.

### 3-6. zWellRandom 정밀 (`00.spComponents/zWellRandom.cs`)
- 시드: `state[0]=seed; state[i] = (uint)(1812433253 * (prev ^ (prev>>30)) + i)` (i=1..15), `index=0` (`:21-42`). seed==0 → 시간 기반.
- `_rand()` WELL512 (`:50-69`), `Rand(s, e)` = `s + _rand() % (e-s+1)` **양끝 포함**. `Rand(n)`(1인자) = `[0, n-1]`. 범위 크기 0 이면 rnd 소비 없이 0 반환 (`:72-84`).
- Python 포팅으로 검증: 문서 골든(visual seed 459838 → `4,1,7,9,12,3`, 12345 → `9,5,3,8,2,14`) 재현 성공. 원시 `_rand()` 첫 5개 (에디터 비교용, Python 포팅 산출 — C# 실행 아님):
  - seed 1: `427107241, 3478131665, 1329158148, 4270539161, 922294098`
  - seed 12345: `3072437747, 3304182464, 2955451663, 3096138484, 1011788893`
  - seed 625901: `1847860848, 2935187508, 2739093739, 1480485179, 2116881938`

### 3-7. rnd 호출 순서 요약 (배치 RNG 단일 스트림)
1. DistributeTiles 2단계: 색상 c 오름차순, `cap>1 && rem>0` 일 때 `cap-1` 회 (`Rand(0,i)`, i=cap-1..1)
2. 전역 Fisher-Yates: `len-1` 회
3. 스왑: `(emptyLen + shuffleTile)` × 2회
(문서 `DESIGN_TILE_COLOR_BALANCE.md:364-368` 과 일치. 단 문서 의사코드 `filter(t0)` 는 **스택 내부 포함/순서 규칙/패딩 산출 범위**가 생략됨 → 위 3-2 가 정밀판)

### [추정] 에디터 포팅 시 비트 일치 리스크
- emptyTiles 순서 = 레이어 번호순 + 맵 JSON 키 삽입 순서(.NET Dictionary 열거 순서에 의존). 에디터가 키를 재정렬하면 불일치.
- `GetEmptyTileList` 는 `layer_{0..Count-1}` 접근 → 레이어 키 누락 시 NRE 가능(`EffectiveLayerCount` 와 기준 다름).
- `Mathf.RoundToInt` 반올림 규칙(짝수 반올림)은 imbalance>0 일 때만 영향. 현재 데이터는 전부 0.

---

## 4. 사용자 샤드 조사 결과 재확인 (baked 파일 직접 디코드)

| 범위 | 레벨 수 | t0 포함 | 전부 t0 | 판정 |
|---|---|---|---|---|
| 1~31 | 31 | **25** (1,2,3,10,20,30 제외) | 25 | ✔ 일치 |
| 32~1500 | 1469 | **70** | 0 | ✘ **불일치** (사용자: 0) |
| 1501~1530 | 30 | 0 | 0 | ✔ 일치 |
| infinity_* | 1030 | 44 | – | (참고) |

- 32~1500 의 70개(예: 149, 208, 219, 238, 239, 243, 256 …)는 **보드 t0 0개, 전부 구포맷 스택/생성기 내부** `["craft_s", null, [3]]` 처럼 내부 id 없음 → `GetTileIDArr` t0 폴백 (`DB_Level.cs:158-169, 205-211`). 명시 내부 id 에 "t0" 을 쓴 경우는 0건.
- **t0 보유 95개 level 전부 `randSeed=0`** → 현재 매 판 시간 기반 랜덤 배정. (`randSeed=0` 인 level 총 127개, 그중 t0 없는 32개는 무영향)
- 1~31 중 t0 없는 1,2,3,10,20,30 은 `randSeed≠0`(625901 등) — 고정 레이아웃.
- "ShuffleEmptyTiles 는 t0 에만 배정 → 고정 맵에서 randSeed/useTileCount 바꿔도 효과 없음" → **코드상 ✔ 정확**(3-2, 3-4). 단 위 70+25개는 예외(효과 있음 + 현재 비결정).
- 기타 메타 실측: useTileCount 분포 12(702)/13(419)/11(172)/6(90)…, typeImbalance 전부 `""`, shuffleTile 전부 0, timea 는 level_341 만 180 나머지 0, autoCollectCount 3 이 153개, visualTileSeed 전부 `""`. 맵에 t16 0건.
- 효과 실측 빈도(level 1530 전체): unknown 3126, ice 873, chain 631, bomb 561, teleporter 443, curtain_close 436, grass 272, link_* 728, frog 108, curtain_open 49.

[추정] 개인화 대상(32+ 대부분)은 현재 "t0 없음" → 변형을 만들려면 (a) 에디터가 변형별 **완전 명시 맵**을 생성·배포하거나 (b) 일부 타일을 t0 로 되돌리고 (randSeed, useTileCount) 로 구동하는 방식 중 택1. (b)는 클라이언트 코드 변경 0 이지만 배치 결정론이 맵 JSON 키 순서에 묶임.

---

## 5. 게임 실제 규칙 (솔버 비교용)

### 5-1. 클릭 처리 순서 [코드] (`GameController.cs:2756-2786`)
`tile.OnClickTile()`(자기 효과 해제) → undo 리스트 push → `CheckOtherTile` 1차(클릭 타일 아직 미픽) → `Dock.AddTile`(m_Picked=true, 매치/실패 판정) → `CheckOtherTile` 2차 → `CheckCantUncoverTileExist`(기믹 불가능 실패) → `AddClickCount`(텔레포트/커튼) → `MoveAllFrog`.

### 5-2. 트레이(dock) [코드]
- 기본 7칸 `initMaxSlotCount = 7` (`Dock.cs:559`). 용량 = 매치 임시칸·잠금칸 제외 슬롯 수 (`Dock.cs:454-475`).
- AddSlot 부스터 +1(판당 1회) (agent 보고: `Dock.cs:3399-3441`, `LevelController.cs:1591-1599`).
- 삽입 정렬: 종류별 그룹, 그룹 순서 = 그 종류 최초 진입 순, 그룹 내 진입 순 (`Dock.cs:948-975`).
- 매치: 같은 `tileIDNum` 3개 → 제거 (`GetMatchTripleTileIndexList`, agent: `Dock.cs:2652-2700`).
- **패배(가득참)**: `activeTileCount = Σ_종류 ((count - hintCount) % 3)` (매치 진행 중 제외) ≥ 용량 (`Dock.cs:2525-2560, 3574-3609`). ⇒ 3번째로 들어와 매치를 완성하는 타일은 칸 계산에서 빠짐 = "7칸 꽉 채운 순간 매치되면 생존".
- **패배(폭탄)**: `IsGameOver` 가 먼저 폭탄 카운트 0 체크 → `FailReason.Bomb` (`Dock.cs:2529-2538`).
- 승리: 보드 미픽 0 && dock 비어있음 (`Dock.cs:2562-2574`).
- FailReason: `Normal, Ice, Grass, Chain, Grass_CantRevive, Chain_CantRevive, Bomb, TimeOver` (`UI/UIFailReason.cs:18`).
- 제한시간: `timea` → `xTimer`, 0=타이머 없음, 첫 클릭부터 시작 (agent: `LevelTimer.cs:23-37`, `GameController.cs:2742-2754`). baked 데이터상 level_341 만 180초.

### 5-3. 덮임 판정 [코드]
- `CLevel.FindAllUpperTiles` (`DB_Level.cs:751-835`), 런타임 동일 로직 `TileGroup.FindAllUpperTiles` (agent: `TileGroup.cs:335-391`):
  - 상위 **모든** 레이어(`layer+1 .. EffectiveLayerCount-1`) 검사.
  - 같은 홀짝: 같은 `(x,y)` 만.
  - 다른 홀짝 & 상위 `col` > 현재 `col`: `(x,y),(x+1,y),(x,y+1),(x+1,y+1)`.
  - 다른 홀짝 & 그 외: `(x-1,y-1),(x,y-1),(x-1,y),(x,y)`.
  - 크기 비교는 **레이어 JSON `col` 만** (row 미비교).
- `EffectiveLayerCount = max(layer 컬럼, 최대 layer_N + 1)` (`DB_Level.cs:618-627`).
- **스택(비-craft) 내부 타일은 상위 레이어 덮임을 검사하지 않음** — `upperStackedTile` 미픽 여부만 (`Tile.cs:1390-1438`). 스택 최상단은 레이어 덮임과 무관하게 픽 가능. ← 솔버 차이 위험 지점.
- craft 배출 타일: `TileCraft.CanPickTile` (agent: `TileCraft.cs:1086-1108`).

### 5-4. 기믹 요약 (agent 보고, 핵심 항목은 표시한 것만 직접 확인)
| 기믹 | 픽 차단 | 해제/동작 |
|---|---|---|
| ice | 카운트>0 동안 (시작 3) | 노출 상태에서 **다른** 타일 클릭마다 -1. 1차 `CheckOtherTile`에서만 카운트 → 자신을 덮던 타일 클릭은 미카운트 |
| grass | 카운트 2 | 같은 레이어 4방 이웃 클릭 시(노출 상태) -1 |
| chain | 해제 전 | 동/서 이웃 클릭 1회 |
| curtain_open/close | close 동안 | 노출 상태에서 다른 타일 클릭마다 토글; 잔여 특수 처리 |
| bomb_N | 차단 안 함 | 노출·미픽 상태에서 다른 타일 클릭마다 -1, 0 → 즉시 패배 |
| teleporter | 0.5s 스왑 창 | 3클릭마다 미픽 텔레포트 타일 종류를 Sattolo 순열 — **무시드 `System.Random`** (직접 확인 `TileGroup.cs:2040, 2070-2074`) |
| frog | 개구리 올라간 타일 | 매 클릭 후 노출 타일로 랜덤 점프 — **무시드 `UnityEngine.Random`** (`FrogManager.cs:185`) |
| unknown | 덮인 동안 | 노출되면 픽 가능(종류 표시만 숨김) |
| link_e/w/s/n | 둘 다 노출·개구리 없음 필요 | 한쪽 클릭 시 둘 함께 수집 |
| stack_dir | 최상단만 | 내부 명시 id 또는 t0 |
| craft_dir | 배출칸 1개씩 | 픽하면 다음 배출, 박스가 덮이면 배출 정지 |
| key(t16/"key") | 아님 | 시작 시 `floor(key/3)` 슬롯 잠금, 키 3개 매치마다 1칸 해제 |
- 기믹 불가능 실패: grass/chain 이웃 부족, ice 남은 카운트 > 활성 타일 수 → 즉시 패배 (`GameController.cs:2772-2779`, agent: `TileGroup.cs:2780-2923`).

### 5-5. 부스터 [코드/agent]
- 타입: `UndoSingle, Shuffle, UndoSet, Hint, AddSlot` (agent: `Item.cs:11`).
- **Shuffle 부스터**: 미픽 전체(덮인/기믹/스택/craft 내부 포함) 종류 랜덤 스왑, RNG `new zWellRandom()` = 시간 기반 (`TileGroup.cs:1595, 1911`).
- Hint: 덮임·기믹 무시하고 강제 수집. UndoSet: dock 3개를 별도 스택으로. UndoSingle: 마지막 타일 원위치(기믹 제거).

### [추정]
- 텔레포트·개구리·셔플·힌트가 무시드 랜덤 → 동일 변형이라도 런타임 경로가 달라짐. 솔버는 이 기믹들을 확률적으로 다뤄야 함.
- `randSeed ≤ 0 → 시간기반` 이라는 agent 보고 문구는 부정확(==0 만). §2 참조.

---

## 6. 진행 중 판 저장/재개, 재도전

### [코드]
- **보드/배정/시드/dock/타이머 저장 없음**. 앱 일시정지 핸들러는 입력 취소만 (`GameController.cs:2572-2582`). 저장 시스템(`TemplateScripts/SaveSystem/SaveSystemController.cs`)은 플레이어 DB(레벨/골드/별)만.
- 판 단위로 영속되는 것은 분석용 시도 횟수 (`TemplateScripts/Analytics/MmpEvents.cs:1092-1104`, `KEY_MMP_TRY_STAGE/COUNT`).
- 재도전: `UIResult.OnClickRetryLevel` → `GameController.ReplayLevel()` (`GameController.cs:1762`) → `LoadLevel` → `UnloadLevel` + 딥카피 + `UpdateNewMapData` → `ShuffleEmptyTiles` 재실행.
  - `randSeed≠0` → 같은 배치. `randSeed=0` → 다른 배치(초 단위).
- 부활: `GameController.Revive()` (`GameController.cs:1883`) → `LevelController.Revive()` 플래그만 해제, **보드 유지**.

### [추정]
- 변형 고정: 판 시작 시 고른 변형 ID 를 플레이어 DB(예: 레벨→변형 맵)에 저장하면 재도전/앱 재시작 시 같은 변형 유지 가능. 현재 구조상 `LoadLevel` 직전에 맵(또는 randSeed/useTileCount) 치환 지점 1곳(`LevelController.cs:775-800`)이 자연스러운 훅.
- 앱 강제 종료 시 판 상실(하트는 진입 시 차감, fail 이벤트 없음).

---

## 7. 분석/이벤트 로깅

### [코드]
- 단일 진입점 `MmpEvents.Log(afName, Dictionary<string,string>)` (`TemplateScripts/Analytics/MmpEvents.cs:65`) → AppsFlyer + Firebase Analytics. 공통 파라미터 주입 `InjectCommonParams` (`:133`): level, surface, elapsed_d, gold, star, energy (SetIfAbsent).
- `MMP_EVENTS_ON` 빌드에서만, 에디터 미전송 (agent: `:54-59`).
- 레벨 이벤트:
| 이벤트 | 위치 | 파라미터 |
|---|---|---|
| level_start | 로비 `LobbyUIController.cs:3471-3479`, 재도전/연속 `GameController.cs:2119`(`LogLevelStartMmp`) | level, entry_from(lobby/retry/clear_continue), attempt, gold, energy_used, free_entry |
| level_clear | `TemplateScripts/Core/GameBridgeManager.cs:530` | level, playtime_sec, is_infinite, attempt, item_used, play_sec, avg_click_ms, combo_max, perfect_count, combo_break_count, free_entry (+infinite 전용) |
| level_fail | `GameBridgeManager.cs:708` | level, is_infinite, attempt, item_used, **fail_reason**, **tiles_left**, play_sec, avg_click_ms, combo_* , free_entry |
| level_revive | `GameController.cs:1673`(`LogReviveMmp`) | level, revive_type(item/gold/ad) |
| level_retry | agent: `UI/UIResult.cs:659-670` | level, attempt, free_entry |
| level_toohard | `MmpEvents.cs:1108` | level, attempt (≥3) |
| booster_use_{undo,shuffle,undoset,hint,addslot} | `Item.cs:414` | pay_type, use_count |
- 서버 StageLog: start/clear/fail 카운터만, 파라미터 없음 (agent: `00.spComponents/spStageLogMng/spStageLogMng.cs`).
- 레벨 포기(중도 이탈) 이벤트 없음.

### [추정]
- 확장 용이: 판 단위 정적 필드(`FreeEntryThisRun` 패턴, `MmpEvents.cs:1169-1182`)에 variant_id / seed_used(`random.CurSeed`) / tile_kinds 를 저장하고 `InjectCommonParams`에서 `level_*` 이벤트에 주입하면 5개 빌더 수정 없이 반영 가능.
- 주의: GA4 커스텀 디멘션 등록 필요, AppsFlyer 이벤트명 한도(파라미터 추가는 무관).

---

## 8. 원격 설정 / A·B 테스트

### [코드]
- Firebase Remote Config **없음** (Firebase 플러그인은 Analytics/App/Messaging 만 — agent 확인).
- GBoost 서버 설정: `config_unity.php` (`spGBoostMng.cs:601`), `uconfig.php` (`:606`), 캐시 후 `GetIntCfg/GetBoolCfg/...(cfgId, key, default)` (agent: `:882-900`). 전역(앱 단위) 값, 유저 세그먼트 없음. 사용 예: `failRevivePayMode`, `failReviveLimitPerStage`, `DifficultyPopupCooldownStages` 등.
- `TemplateScripts/Core/FeatureToggle.cs`: ABTest 상태, `GetVariant(featureKey, userId)` (`:618`), `SyncFromRemote` 존재. **런타임 초기화/호출처 없음**(agent: 씬/프리팹 참조 없음).

### [추정]
- ON/OFF 플래그는 uconfig 키 1개 추가로 즉시 가능(기본값 OFF 로 코드 배포).
- 유저 버킷팅은 FeatureToggle 재활용 또는 `hash(userId + experimentKey) % 100` 직접 구현 필요. `string.GetHashCode()` 는 .NET 런타임/플랫폼 간 안정성 보장 없음 → 안정 해시(MD5 등, `spBase64.MD5` 존재) 권장.
- uconfig 가 출시 트래픽 사고 이후에도 런타임에 실제 fetch 되는지는 미확인(아래).

---

## 미확인 / 추가 확인 필요

1. uconfig/config_unity 가 현재 빌드에서 부팅 시 실제로 fetch 되는지(트래픽 사고 후 비활성 여부) — `spGBoostMng.cs:591-650` 호출 흐름 실행 확인 필요.
2. `spEncrypt(spString "").AsInt` 결과가 0 인지(추정 0) — 현재는 icon_order 로 리맵 자체가 생략되어 영향 없음.
3. .NET `Dictionary` 열거 순서(삽입 순서) 의존 — IL2CPP/모노 실기기에서 맵 JSON 키 순서와 동일한지 실측(같은 randSeed 로 에디터 vs 기기 배치 비교) 필요.
4. Python WELL512 포팅값은 문서 골든과 일치하나 C# 실행으로 원시 출력 직접 대조는 안 함.
5. 기믹 세부(ice 시작 3, grass 2, curtain 잔여 규칙, frog 후보 조건, 키 슬롯 잠금)와 부스터 줄번호는 하위 조사 에이전트 보고 기반 — 핵심(덮임, dock 계산, 스택 마스크, 텔레포트 RNG, 클릭 순서)만 직접 확인함.
6. AddSlot 부활 콜백이 UndoSingle 체크에 묶여 있다는 보고(`ItemGroup.cs:753-756`, "TODO : ADD addslot action") — 미검증.
7. 서버 `levels` 테이블 현재 값이 baked(2026-09-18) 와 같은지 — 서버 조회 금지 범위라 미확인.
8. infinity 모드 레벨 선택 경로(`pool_level` 등)와 개인화 적용 범위 — 미조사.
9. 레벨 1~3 고정 레이아웃 코드(에디터측 메모리 `project_fixed_layout_levels`)와 클라이언트 관계 — 클라이언트 쪽 특수 처리는 발견 못함(샤드 데이터에 명시 타일로 존재).

---

## §9 에디터 대조 추가 확인 (02_editor_pipeline_findings.md 대응)

### 9-1. JSON 파서 / 딕셔너리 타입 / t0 순회 순서 (R3 전제)
**[코드]**
- 파서: **SimpleJSON (Bunny83, "Copyright (c) 2012-2022")** 프로젝트 내장 수정본 `Assets/00.spComponents/SimpleJSON.cs:8-15`. 별도 패키지 버전 없음(AsEncrypt 등 사내 확장 포함).
- `JSONObject` 저장소 = `Dictionary<string, JSONNode> m_Dict` (`SimpleJSON.cs:1095`). 열거 = `m_Dict.GetEnumerator()` (`:1107`). 파싱 시 키 추가는 `ctx.Add(TokenName, …)` (`:748, 766, 787, 820`) → `Add`: 키 존재 시 `m_Dict[aKey] = item`(제자리 덮어쓰기), 없으면 `m_Dict.Add` (`:1155-1167`). ⇒ **JSON 텍스트의 키 등장 순서 = Dictionary 삽입 순서.** 정렬 없음.
- 맵 → 런타임 구조: `CLayerList : Dictionary<string, CLayer>` (`DB_Level.cs:515-557`), `CTileList : Dictionary<string, CTile>` (`DB_Level.cs:383-424`) 둘 다 `foreach (var item in tileData)` 로 JSONObject 열거 순서 그대로 `Add`.
- t0 순회 `GetEmptyTileList(false)` (`DB_Level.cs:880-903`): 레이어는 이름 `layer_{i}` (i=0..Count-1) 로 **숫자 순 직접 조회**, 레이어 내부는 `cLayer.xTiles.Values` 열거 = **CTileList 삽입 순서 = 맵 JSON tiles 키 순서**. 스택/생성기 내부는 루트 위치에서 `stackCTileList` index 0(바닥)→N-1 순.
- **삭제/재삽입 여부**: 맵 로드~`ShuffleEmptyTiles` 경로에서 JSONObject/`CTileList` 에 대한 Remove 없음 (`xTiles.Remove`, `["tiles"].Remove` 등 검색 0건, 08.Scripts 전체). `LoadLevel` 은 테이블 행을 `JSON.Parse(ToString())` 딥카피(`LevelController.cs:776-778`) — 직렬화·재파싱도 순서 보존. 샤드 맵 노드는 복사 없이 붙지만(`:797`) 셔플은 `CTile.xTileID`(spEncrypt 신규 객체, `DB_Level.cs:399`)만 바꾸므로 JSON 원본 무변경. `CTile.AddOffset` 은 `xID` 문자열만 바꾸고 딕셔너리 키는 그대로(`DB_Level.cs:1001-1033`, 순서 무영향).
- 샤드 파일의 tiles 키 순서 = 베이크 시 서버 `real_array` 응답 순서 그대로(`LevelMapBakeTool.cs:58, 94` 에서 `JSON.Parse` 후 `shard[levelId] = map`) → 02 노트 GB:403 row-major 재정렬본이 그대로 기기 순회 순서가 됨. (샤드 실측 예 level_4 layer_0: `0_0, 1_0, 4_0, 5_0, 0_1, …` — 키 `a_b` 에서 **두 번째 숫자 바깥, 첫 번째 숫자 안쪽** 순. 클라는 첫 숫자를 `xIndex`, 둘째를 `yIndex` 로 해석(`DB_Level.cs:230-231`). 주석 `{row}_{col}`(`DB_Level.cs:40, 397`)과 명칭이 엇갈리므로 에디터 정규화는 "문자열 키 순서 그대로"를 기준으로 할 것)
- 빌드 설정: Unity **6000.0.62f1** (`ProjectSettings/ProjectVersion.txt:1`). `scriptingBackend: Android: 1` = **IL2CPP** (`ProjectSettings/ProjectSettings.asset:793-794`). iOS 항목 없음 → iOS 는 Unity 상 IL2CPP 만 지원. `apiCompatibilityLevel: 6` (`:888`, .NET Standard 2.1 계열로 추정).

**[추정]**
- IL2CPP 는 BCL `Dictionary<TKey,TValue>` IL 을 그대로 C++ 변환하므로 에디터(Mono)와 기기에서 동일 구현. 삭제 없는 Dictionary 는 entries 배열을 앞에서부터 채우고 열거도 그 순서 → 실질적으로 삽입 순서 유지. **명세 보장은 아님** — Unity/BCL 버전 변경 시 재검증 필요. 위험 낮음, 단 골든 테스트(02 §7)로 상시 감시 권장.
- `CLayer.layerIndex` 는 `layer_N` 의 N 이 아니라 **map 키 열거 순번**(`DB_Level.cs:548-553`). 현 샤드는 `layer, layer_0, layer_1, …` 순이라 일치하지만, 에디터가 레이어 키를 비순차로 내보내면 덮임 판정·순회가 어긋남 → 배포 정규화 시 레이어 키 순서 고정 필요.

### 9-2. 셔플 관련 필드명 (R8)
**[코드]** 클라는 JSON 키 **`shuffleTile` / `typeImbalance`** 만 읽는다. `xShuffleTile` / `xTypeImbalance` 는 **C# 멤버명**(`spEncrypt`)이고 JSON 키로 쓰이지 않는다.
- 읽기: `DB_Level.cs:1064, 1072`(CLevelList 생성자), `:1566, 1574`(UpdateNewMapData). 문자열 `"xShuffleTile"`/`"xTypeImbalance"` 검색 결과 0건(Assets 전체).
- 사용: `xShuffleTile.AsInt` → 스왑 횟수 가산(`:1271`), `xTypeImbalance.AsInt / 10f`(`:1208`).
- ⇒ 02 노트 R8 결론 유지: **TS 엔진(GE:491-494)이 `xShuffleTile`/`xTypeImbalance` 키를 읽는 것이 오류**. 정본은 `shuffleTile`/`typeImbalance`.
- 추가 위험 **[코드]**: 게임 내장 레벨에디터는 `typeImbalance` 를 **float(0~1)** 로 저장(`Tile_LevelEditor/ExLevelEditor.cs:483, 636`)하지만 런타임은 **`AsInt / 10f`**(0~10 정수 가정)로 읽음 → 0.5 저장 시 런타임 0(추정: spDouble→AsInt 절삭). 현 배포값 전부 `""` 라 무영향. 개인화에서 imbalance 를 쓰려면 단위(정수 0~10) 확정 필요.

### 9-3. 색상 클러스터 제거 셔플의 난수 소비 (R1) — §3-4/3-7 보강
**[코드]** `DB_Level.cs:1208-1217`
```
randomTileIndexList = DistributeTiles(emptyLen/3, maxTileIndex, unlockTile, typeImbalance/10f, random);  // 같은 random 인스턴스 전달
for (int i = randomTileIndexList.Count - 1; i > 0; i--) {   // Count = 세트 수(키타일 16 세트 포함)
    int j = random.Rand(0, i);                                 // [0, i] 양끝 포함 → _rand() % (i+1)
    swap(list[i], list[j]);
}
```
- **배치 RNG 단일 스트림의 정확한 소비 순서** (seed = `(uint)randSeed`, 0이면 시간 기반):
  1. `DistributeTiles` 2단계 (`:1452-1485`): 색상 c = 0..activeColors-1 순, `cap>1 && rem>0` 인 색상에서만 `for i=cap-1..1: Rand(0,i)` → 색상당 `cap-1` 회(=최대 2회).
  2. **클러스터 제거 Fisher-Yates** (`:1211-1217`): `n = 세트 수` 일 때 `i = n-1, n-2, …, 1` 순으로 **정확히 n-1 회** `Rand(0,i)`. 범위 크기 i+1 ≥ 2 이므로 매회 `_rand()` 1회 소비(0 반환 단축 없음).
  3. 위치 스왑 (`:1271-1287`): `(emptyLen + shuffleTile)` 회 × `Rand(0, emptyLen-1)` 2회 (r1 먼저, r2 다음). `emptyLen == 1` 이어도 범위 크기 1 → `_rand()` 소비함(`zWellRandom.cs:80-83`: 크기 0일 때만 미소비).
  - 총 `_rand()` 호출 = Σ(1단계) + (n-1) + 2·(emptyLen+shuffleTile).
- **누락 시 영향**: 2단계(n-1회)를 빼면 세트→위치 대응(배정 루프 `:1229-1255` 는 셔플된 리스트를 앞에서 3칸씩 소비) 이 달라지고, 3단계 스왑도 스트림 오프셋이 n-1 만큼 밀려 **모든 위치 스왑이 다름** → 동일 시드라도 전 배치 불일치(02 R1 에뮬 결과와 부합).
- 별도 RNG(배치 스트림 무관): `GetTileTypeRarity` 의 `rarityRnd`(`:1526`, 정적 난이도 계산 전용), `ApplyVisualTileRemap` 의 `vrnd`(`:1331`).
- 도입 시점: 02 노트 기준 2026-04-22 커밋 b369c2b8 (클라 git 로그 미확인).

### 9-4. 02 노트 '미확인' 중 클라 코드로 답한 것
| 02 미확인 항목 | 답 |
|---|---|
| SimpleJSON 키 순서 보존(IL2CPP/Mono) | 9-1. 파서는 순서 보존(Dictionary 삽입), 삭제 경로 없음, 기기는 IL2CPP(Android 설정 확인, iOS 는 IL2CPP 전용). 명세 보장 아님 → 골든 테스트로 감시 |
| `timea=0` 의미 | **[코드] 0 = 시간제한 없음.** `xTimer > 0` 일 때만 타이머 연출+`LevelTimer.Init/StartTimer` (`LevelController.cs:1340-1365`), 아니면 `LevelTimer.Init(0)` → `setInitActive=false`, 타이머 UI 비활성 (`LevelController.cs:1373-1376`, `LevelTimer.cs:23-38`). baked 데이터상 timea>0 은 level_341(180초) 하나 |
| infinity_* 적용 범위 | **[코드]** 정식 진행도 `normal_curlv` > uconfig `MaxOfficialLevel`(미설정 시 int.MaxValue = 비활성) 이면 `level_N` 진입을 `infinity_*` 로 치환 (`GameController.cs:2930-2985`). 풀에서 "다음 플레이 순번 일의 자리" 버킷으로 랜덤 선택, 선택 ID 는 **메모리 필드** `_servingInfinityLevelID` 에만 보관해 재도전 간 고정·클리어 시 해제 (`:2951-2962`). infinity 행도 같은 `ShuffleEmptyTiles` 경로(맵 샤드 `levelmap_infinity_*`). 원본 level 과의 매핑 정보는 클라에 없음 |
| level_341 이 2·3차 배치와 다른 원인 | 클라로는 판단 불가. 단 341 은 baked 에서 유일하게 `timea=180` 인 레벨 → 다른 경로(수동 수정/별도 업로드) 가능성 [추정] |
| Unity 실제 실행 덤프 대조 / 서버 real_array 일치 / IndexedDB / lp_* 출처 | 클라 코드로 답 불가 (실행·서버 조회 필요) |
