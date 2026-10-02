# 05. P0 재현성 보고 — 레퍼런스 포트 · 골든 · 샤드 스캔

> 작성 2026-10-02 · 브랜치 `feature/pv-seed-variants`(미커밋) · 계획: [04](./04_seed_variant_plan.md) §A3·§A7·§D
> 표기: **[사실]** = 실행·코드로 확인 · **[제안]** = 판단 · 줄 번호 약어는 04와 같다(`CS`=DB_Level.cs, `GB`=gboost.py, `BS`=bot_simulator.py)
> 담당: E-P0-1 포트(시드계획전문가) · E-P0-3 골든(P0골든) · E-P0-2 정규화·스캔(P0스캔)

---

## 1. 게이트 결과 요약

| 게이트 | 내용 | 결과 | 근거 |
|---|---|---|---|
| **G1** | WELL512 원시 출력: 5 seed(1, 12345, 625901, 2147483647, 4294967295) × 1000개 | ✅ **PASS** (5,000/5,000 일치) | `test_golden_g1_rng`, `rng_well512.json` |
| **G2** | 포트 == dotnet 하네스(원본 메서드 추출 + 원본 zWellRandom 링크): 62파일 / 371 run | ✅ **PASS** (371/371). 위치·타입·실효 seed·maxTileIndex·RNG 앞부분·풀어 쓴 맵(`resolvedMap`)까지 전부 일치 | `test_golden_g2_case` |
| **G3** | 포트 == Unity 에디터 실경로 덤프(C-P0-1) | ⏸ **사용자 승인 대기**(04 Q4). 그때까지 G1·G2는 "dotnet 기준 잠정" | — |
| **G4** | 샤드 1530 키 순서 == GB 정렬, 레이어 연속성, 구조 차이 | ✅ **PASS**. 키 순서 불일치 0, 레이어 연속성 위반 0, 구조 차이는 Lv34 하나 | [p0_scan_result.md](./p0_scan_result.md) |
| **G5** | 풀어 쓴 명시 맵을 **기존 봇**(`BotSimulator._create_initial_state`)이 읽은 타입 == 골든(inner 순서 포함) | ✅ **PASS** (366 run, 슬롯 18,188개, 그중 컨테이너 inner 2,684개, craft 포함 175 run·stack 포함 130 run). 단 key 표기 문제 F-G5-1 | `test_golden_g5_bot_reads_resolved_map` |

- 테스트 실행: `backend/.venv/bin/python -m pytest tests/test_pv_cs_shuffle.py` → **813 passed**(2.2s). 구성: 골든 없는 단위 테스트 74 + 버전 확인 1 + G1 1 + G2 371 + G5 366.
- **변이 검사** [사실]: 포트에서 클러스터 제거 Fisher-Yates(CS:1211-1217) 한 줄을 빼면 G2가 **349/371 실패**한다. 남은 22개는 seed 0·예외 거부 run 등 배정 결과를 비교하지 않는 run이다. 확인 후 원본으로 되돌렸다. → G2는 실제 배정 경로를 검증하고 있다.
- 포트는 골든을 보기 전에 C# 원문만으로 작성했다(독립 구현). 첫 대조에서 불일치는 **0건**이었다. 골든을 보고 추가한 것은 입력 형태 1건(아래 §3-1)뿐이고, 배정 로직은 바꾸지 않았다.

---

## 2. 분배 버전(distVer)·원문 고정

| 항목 | 값 [사실] |
|---|---|
| distVer | **`cs:191858cc9c06`** (골든 헤더 = 포트 테스트 상수 `EXPECTED_DISTVER`) |
| 정의 | `"cs:" + sha256(GetEmptyTileList[CS:870-945] + GetToAddIndexList[1123-1156] + ShuffleEmptyTiles[1167-1292] + DistributeTiles·헬퍼[1356-1502] + zWellRandom.cs 전체)[:12]` |
| DB_Level.cs | 커밋 `b741f6a3`(2026-09-21), sha256 `b76a2e01…c586b`, 워킹트리 변경 없음 |
| zWellRandom.cs | sha256 `af9ad440…478744c` |
- 04 §A3-5와 다른 점: 04는 DistributeTiles를 1372-1502로 적었다. 골든 측은 같은 로직에 쓰이는 `ImbalanceFactor`·`TilesPerColor`·`ActiveColorCount`·`ColorCapacityOf`(1356-1371)도 distVer에 넣었다. → **골든 정의를 정본으로 채택한다.**
- 클라 원문이 바뀌면 골든 빌드가 실패하고(sha 고정), 포트 테스트도 distVer 상수 불일치로 실패한다. 이때 그 distVer로 평가한 seed는 전부 stale 처리한다(04 §A6).

---

## 3. 불일치·판정 기록

### 3-1. 포트 변경 1건 (입력 형태 지원, 배정 로직 무관)
- 샤드 9개 레벨(599·615·665·671·736·829·911·1466·1467)에 `"tiles": []`(빈 배열) 레이어가 있다(골든 README 발견 5).
- 초판 포트는 이 형태를 `PvUnsupportedInput`으로 거부했다.
- C# 근거: `CTileList` 생성자는 `foreach (var item in tileData)`로 순회한다(CS:392). 빈 JSONArray는 아무것도 열거하지 않으므로 타일 0개 레이어가 된다.
- 판정: **포트를 고쳐 빈 배열을 0타일로 받는다.** 비어 있지 않은 배열은 여전히 거부한다(키가 ""로 열거되므로 클라 동작이 정의되지 않는다).

### 3-2. 골든 측 판정 사항 — 포트와 일치 확인
| 항목 | 판정 | 포트 |
|---|---|---|
| null·누락 필드의 AsInt | 0 (s19~s21) | 일치(`as_int(None)=0`). 중간 보고의 "미확정" 해소 |
| AsInt | `(int)AsLong`: 문자열은 double 파싱 → 버림 → 하위 32비트 (s22: `"3000000000"`→uint 3000000000, `"-2147483649"`→2147483647) | 일치 |
| t0 순회 | `layer_{i}` 번호순(CS:880). `layerIndexByKey`는 키 등장순(CS:548-553). 둘 다 사실 | 일치(s23) |
| effect "key" | 대소문자 무시, `["t0","key"]`도 key(16)이며 빈 칸 아님 (s24) | 일치 |
| 신포맷 inner 개수 불일치 | 전부 t0 폴백 (s25) | 일치 |
| t0가 세트로 덮이지 않음 | 클라 `ArgumentOutOfRangeException`(CS:1253) (s11) | `CsClientCrash`로 거부 |
| 패딩 뒤 세트 잘림 | 예외 없이 3배수가 깨진 배치 (s18) | strict: `PvContractError` / lenient: 같은 배치 재현 |
| seed AsInt 0 (0·null·누락) | 시간 기반 → nondeterministic (s21) | `PvContractError`로 거부 |
| useTileCount ≤ 0 | 스킨 타일 수 shim 의존 (s14·s19·s21) | 인자 없으면 `PvUnsupportedInput`. shim 값(16)을 넣으면 하네스와 같은 배치(정답 아님, 동치 확인용) |

### 3-3. 04 계획 정정
1. **t0화 단언 ①**(04 §A2): "key 제외 t0 총수 %3==0"은 **순수 t0 맵에서만** 맞다.
   - 명시 타일과 t0가 섞이면(key 레벨 신포맷) 패딩(toAdd)이 t0 일부를 먼저 쓴다. 그래서 기준은 "**(명시 + 배정) 종류별 개수 %3==0**"이다(골든 s17·s18).
   - 포트 strict 검사가 바로 이 일반 기준이다(`_check_divisible`).
   - [제안] E-P1-2 단언 ①은 "포트 strict 실행 성공"으로 바꾼다.
2. **P1 제외 목록 — 샤드 불일치**: 34개 → **Lv34 하나**("shard 구조 불일치")로 줄인다.
   - 33개는 타입만 다르다. t0화하면 타입을 지우므로 구조가 같아진다.
   - Lv341은 timea만 다르고, timea>0 규칙으로 이미 따로 제외된다.
3. **distVer 정의**: 1356-1371을 포함한다(§2).

---

## 4. layerIndex(키 등장순)가 덮임 판정에 주는 영향

- [사실] 클라에는 기준이 두 개 있다.
  - **t0 배정 순회**는 레이어 이름 `layer_{i}`를 번호순으로 조회한다(CS:880-882). 맵 키 순서와 무관하다.
  - **`CLayer.layerIndex`/`CTile.layerIndex`**는 map JSON의 `layer_*` 키가 나타난 순번이다(CS:548-553, 402).
  - 덮임 판정 `FindAllUpperTiles(layerIndex, …)`는 이 layerIndex로 `GetLayer($"layer_{layerIndex}")`를 찾고, 상위 레이어는 `layer_{layerIndex+1..}` 이름으로 훑는다(CS:764-771). 홀짝 규칙도 layerIndex 기준이다(CS:763, 776).
  - 따라서 키 순서가 번호순이 아니면 **배정(번호순)과 덮임(등장순)이 서로 다른 레이어를 가리킨다.** 예: 키가 `layer_1, layer_0` 순이면 layer_1 타일의 layerIndex가 0이 되어, 자기보다 위에 있는 layer_1을 상위로 검사하게 된다. 골든 s23에서 `layerIndexByKey={layer_1:0, layer_0:1}`을 확인했다.
- [사실] **정규 맵에서는 둘이 일치한다.**
  - GB 변환은 `map_data = {"layer": …}` 뒤에 `layer_0..N-1`을 번호 오름차순으로 넣는다(GB:394-404).
  - G4 샤드 전수 스캔에서 **map 최상위 레이어 키 순서 불일치 0/1530, 레이어 연속성 위반 0/1530**이었다. 즉 배포본은 키 등장순 = 번호순 = layerIndex다.
- [사실] 남은 틈: GB는 level_json에 없는 레이어 키를 건너뛴다(GB:397). 중간 레이어가 빠지면 `CLayerList.Count`가 최대 번호+1보다 작아진다. 그러면 클라 `GetEmptyTileList`가 `layer_{i}`를 못 찾아 NRE가 나고(포트: `CsClientCrash`), 등장순 layerIndex도 번호와 어긋난다.
- [제안]
  - E-P1-2(t0화)는 `canonical.check_layer_continuity` 통과를 필수로 한다.
  - 포트는 정규 맵(`canonical_map`) 출력만 입력으로 받는다.
  - 기기(IL2CPP) Dictionary 열거 순서는 이번 범위에서 검증할 수 없다 → G3(Unity 에디터)와 P3 기기 로그로 확인한다.

---

## 5. G5에서 나온 봇 쪽 발견 (P1 평가 설계에 반영 필요)

| # | 발견 [사실] | 영향 | 조치 [제안] |
|---|---|---|---|
| F-G5-1 | 클라는 unlockTile로 생긴 key를 `"t16"`으로 쓴다(CS:1253, isKeyTile CS:234). 풀어 쓴 맵도 `"t16"`이다. **봇은 `MATCHABLE_TYPES = t1..t15 + "key"`(BS:724)이고 key 처리도 `== "key"`만 본다**(BS:1074, 2575, 3206). `"t16"`은 매칭·잠금 해제 대상이 아니다 | G5는 타입 문자열 위치 일치만 확인했다(21슬롯·5 run이 t16). 이 맵을 봇에 그대로 넣으면 key 레벨 평가가 틀린다 | E-P1-3에서 풀어 쓴 맵을 봇에 넘기기 전에 `"t16"`→`"key"`로 바꾼다. P1은 key 레벨을 제외하고 unlockTile=0이므로 당장 영향은 없다 |
| F-G5-2 | 봇은 `level_json["layer"]`(정수)만큼 `layer_{i}`를 돈다(BS:991-1060). 클라는 `max(layer 컬럼, 최대 layer_N+1)`(CS:618-627) | 컬럼 값이 1 작은 레벨(01 기록상 과거 20레벨)에서 봇이 최상층을 빠뜨린다 | 평가 입력의 `layer` = EffectiveLayerCount로 맞춘다(G5 테스트의 `_bot_level_json`과 같은 방식) |
| F-G5-3 | 봇 초기화는 컨테이너 inner를 명시여도 t0 수집 목록에 넣고 자체 분배기를 돌린다(BS:1048-1060). 단 명시 inner가 있으면 그 값을 쓴다(BS:1396-1402) | 풀어 쓴 맵에서는 결과 타입에 영향 없음(G5로 확인). 봇 RNG 소비만 일어난다 | 조치 불필요. 봇 난수 재현성은 봇 seed로 관리한다 |
| — | inner 순서: 봇 `stack_index` 0 = 바닥, craft는 최상단(n−1)부터 배출(BS:1499, 1538) = 클라 index 0=바닥 규약 | G5에서 inner 2,684슬롯 일치 | 확인 완료 |

---

## 6. P0스캔(E-P0-2) 요약 — 상세는 [p0_scan_result.md](./p0_scan_result.md)
- 대상: 샤드 1530 vs LIVE 3차 배치를 canonical로 비교. 생성 스크립트는 `backend/scripts/pv_scan_shards.py`(읽기 전용).
- (a) tiles 키 순서 불일치 0, (b) map 레이어 키 순서 불일치 0, 레이어 연속성 위반 0.
- structHash 구조 차이 **1개(Lv34)**. 02 노트의 "34개 상이" 중 나머지 33개는 타입만 다르고, Lv341은 timea만 다르다(구조 동일).
- 결론: GB 정렬 → GameBoost → real_array → 굽기 전 구간에서 **키 순서가 보존된다**(배포 데이터 기준). 04 §A3-3 전제가 성립한다.

---

## 7. 산출물 (미커밋)
| 파일 | 담당 | 비고 |
|---|---|---|
| `backend/app/core/pv/__init__.py` | E-P0-1 | |
| `backend/app/core/pv/cs_shuffle.py` | E-P0-1 | 673줄. 공개 API: `shuffle_empty_tiles`, `shuffle_level_row`, `resolve_map`, `ZWellRandom`, `as_int`, `apply_visual_tile_remap`(선택) |
| `backend/tests/test_pv_cs_shuffle.py` | E-P0-1 | 단위 + G1·G2·G5 |
| `backend/app/core/pv/canonical.py`, `backend/scripts/pv_scan_shards.py`, `backend/tests/test_pv_canonical.py` | E-P0-2 | |
| `tools/pv_golden/*`, `backend/tests/golden/pv_t0/*` | E-P0-3 | |
- 공유 코어(bot_simulator.py·generator.py·gboost.py), LIVE 배치, 서버 데이터는 수정하지 않았다. 업로드·push 없음.

## 8. 남은 일 · 확인 필요
1. **G3 Unity 덤프**: 사용자 승인 필요(04 Q4). 승인이 나면 같은 입력 62개로 덤프해 G2 정답과 diff한다. G3 전까지 P1은 "잠정"으로 진행할 수 있다(04 §A3-4).
2. G2 하네스가 확인하지 못하는 것: Unity `Mathf.RoundToInt` 실제 값(imbalance=0 고정이라 P1 영향 없음), 스킨 타일 수(utc>0 강제로 회피), IL2CPP Dictionary 순서(G3·P3).
3. P1 표본 실레벨 20개를 t0화하면 골든 `inputs/`에 추가하고 G2를 다시 돌린다(골든 README 안내).
4. P1 착수 전 04에 반영할 것: §3-3 정정 3건, F-G5-1·F-G5-2 조치(E-P1-3 명세).
