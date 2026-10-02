# pv_t0 골든 벡터 — 클라 `ShuffleEmptyTiles` t0 배정 정답 (E-P0-3, G1·G2)

게임 클라(sp_meowsgarden) **원본 C# 코드를 dotnet에서 그대로 실행**해 만든 t0 종류 배정 정답이다.
Python 포트(`backend/app/core/pv/`)가 이 파일과 비트 단위로 같아야 한다(04 계획 §A3, P0-G1·G2).

> ⚠️ **권위 수준: 잠정(G2).** 원본 메서드를 줄 범위 그대로 추출하고 shim으로 Unity 의존을 대신했다.
> 최종 정답은 Unity 에디터 실경로 덤프(G3, C-P0-1, **승인 대기**)와 비교해야 확정된다. G3 전에는 "dotnet 기준 잠정"으로 표기한다.

## 재생성

```bash
# 저장소 루트에서. 게임 저장소는 ../sp_meowsgarden 가정(-p:GameRepo=... 로 변경 가능)
dotnet run --project tools/pv_golden -- all          # rng_well512.json + expected/*.json + expected/_manifest.json
dotnet run --project tools/pv_golden -- case backend/tests/golden/pv_t0/inputs/s01_single_layer_9.json   # 1건 stdout
dotnet run --project tools/pv_golden -- rng /tmp/rng.json                                               # G1만
```
- 빌드 시 `tools/pv_golden/extract_methods.py`가 먼저 돈다. DB_Level.cs·zWellRandom.cs의 sha256이 고정값과 다르면 **빌드 실패**(클라 코드 변경 = 골든 무효 신호).
- 출력에 시각·경로 같은 가변값이 없다. 같은 입력 2회 실행 결과가 바이트 단위로 같음을 확인했다(전체 해시 `f20271ee…`, 2026-10-02).
- `all`은 케이스별 `expectSelfCheck`와 결과가 다르거나, Debug.LogError(SimpleJSON/spEncrypt 검증 실패)가 한 번이라도 나거나, `UnityEngine.Random.Range`가 허용 외 코드에서 불리면 exit 1이다.
- `inputs/`는 커밋된 데이터다. 실레벨 입력은 게임 샤드를 /tmp에서 읽기 전용으로 복호해 만들었고, 생성 스크립트는 지웠다(출처는 아래 표와 각 입력 `note`).

## 원문 고정 정보

| 항목 | 값 |
|---|---|
| 원문 | `sp_meowsgarden/Assets/08.Scripts/Tile_Script/InGame/DB_Level.cs` (마지막 커밋 `b741f6a3`, 2026-09-21, 워킹트리 변경 없음) |
| DB_Level.cs sha256 | `b76a2e014aca4823f53b8078671550a77bb5d2e1018b0f55c03cf69abc6c586b` |
| zWellRandom.cs sha256 | `af9ad44037ae5d1cf4324fdfea0e93ec7a9c8ff444df53d9d389c99b8478744c` (복사하지 않고 `<Compile Include>` 링크) |
| **distVer** | **`cs:191858cc9c06`** |
| distVer 정의 | `"cs:" + sha256(GetEmptyTileList[870-945] + GetToAddIndexList[1123-1156] + ShuffleEmptyTiles[1167-1292] + DistributeTiles+helpers[1356-1502] + zWellRandom.cs 전체 바이트)[:12]`. 각 구간 = 원문 줄을 LF로 잇고 끝에 LF 1개 |

- 04 §A3-5는 DistributeTiles를 1372-1502로 적었지만, 같은 로직에 쓰이는 `ImbalanceFactor`·`TilesPerColor`·`ActiveColorCount`·`ColorCapacityOf`(1356-1371)도 distVer에 넣었다.
- 추출 구간 전체(줄 번호·구간별 sha256)는 빌드 때 `tools/pv_golden/Generated/extract_meta.json`에 기록된다. 데이터 클래스 `CTileStackInfo`·`CTile`·`CTileList`·`CLayer`·`CLayerList`·`CLevel` 필드, `ApplyVisualTileRemap`, `UpdateNewMapData`·`GetLevel`·`SetLevel`도 원문 그대로 추출했다. 실행 경로는 클라와 같은 `UpdateNewMapData → new CLayerList(map) → ShuffleEmptyTiles`다.

## 파일과 형식 (pytest에서 읽는 법)

```
backend/tests/golden/pv_t0/
  rng_well512.json          G1: WELL512 원시 출력
  inputs/<caseId>.json      케이스 입력 (62개)
  expected/<caseId>.json    정답 (inputs와 같은 파일명)
  expected/_manifest.json   케이스 목록·자체점검 요약·Random.Range 호출자
```
모든 출력은 UTF-8, 한 줄 JSON이다. 공통 머리 필드: `format`("pv_t0_golden/v1"), `type`, `distVer`, `sourceSha256`, `zWellRandomSha256`, `authority`.

### rng_well512.json (G1)
`{"type":"rng", "seeds":[{"seed":<uint>, "raw":[<uint32> × 1000]}, …]}`. seed = 1, 12345, 625901, 2147483647, 4294967295(= `(uint)-1`).
`raw[k]` = `new zWellRandom(seed)` 뒤 k번째 `_rand()` 반환값(리플렉션 호출). 처음 5개는 01 노트 §3-6의 Python 값과 같다.

### inputs/*.json
```jsonc
{
  "caseId": "s01_single_layer_9", "kind": "synthetic" | "real", "note": "...",
  "levelId": "level_9000",                 // 클라 CLevel id (결과 무관)
  "row": { "randSeed": 1, "useTileCount": 3, "unlockTile": 0, "shuffleTile": 0, "typeImbalance": "",
           "tileSkin": 0, "layer": 1, ..., "map": { "layer": "1", "layer_0": { "col": "3", "row": "3", "tiles": { "0_0": ["t0",""], ... }, "num": "9" } } },
  "runs": [ { "randSeed": 1, "useTileCount": 1 }, ... ],   // run마다 row 필드 덮어쓰기(값 타입 유지)
  "dumpRng": true,                         // 선택: 결과에 rngRawPrefix 포함
  "expectSelfCheck": "pass" | "fail" | "exception",   // 생략 = pass (전 run 공통)
  "expectPerRun": ["pass", "nondeterministic", ...],   // 선택: run별 기대 결과 (s19~s25)
  "shim": { "tileCount": 16 }, "shimDependent": true   // s14 전용
}
```
- **맵 키 순서가 입력이다.** 클라 순회 순서 = 레이어 `layer_{i}`(i=0..레이어키수-1, 이름으로 조회) × 각 레이어 `tiles`의 JSON 키 등장 순서. Python은 `json.load`(dict 삽입 순서 보존)로 읽고 정렬하지 말 것.
- 행 값 타입은 원본 그대로다(실레벨은 테이블 값이 숫자·null·""). 클라는 `AsEncrypt.AsInt`로 읽는다(아래 "발견" 참조).

### expected/*.json
```jsonc
{
  "type": "case", "caseId", "kind", "note", "inputFile", "inputSha256", "levelId", "expectSelfCheck"?, "tileCountShim",
  "results": [                       // inputs.runs와 같은 순서·같은 개수
    {
      "overrides": { "randSeed": 1, ... },
      "effective": { "randSeed": <int AsInt>, "seedUint": <(uint)randSeed>, "useTileCount", "unlockTile",
                     "shuffleTile", "typeImbalance": <AsInt, 런타임은 /10f>, "maxTileIndex" },
      "positions": [ ["layer_0", "2_3", -1], ["layer_0", "4_4", 0], ... ],  // GetEmptyTileList(false) 순서
      "types": [ 7, 7, 3, ... ],     // positions[i]에 배정된 tileIDNum (1..15, 키=16). 정답 비교 대상
      "layerIndexByKey": { "layer_1": 0, "layer_0": 1 },  // CLayer.layerIndex = map 내 layer_* 키 등장 순번 (CS:548-553)
      "selfCheck": { "ok", "t0Count", "typesCount", "t0CountMod3", "allAssigned", "unresolvedTiles",
                     "assignedPerType": {"<id>": n}, "totalPerType": {"<id>": n}, "totalPerTypeNotMultipleOf3": [ids] },
      "resolvedMap": { ... },        // 입력 map에 배정 결과를 써 넣은 명시 맵. 보드 t0 → "tN", 컨테이너 [cnt] → [cnt,"id0_id1_…"] (index 0=바닥)
      "rngRawPrefix": [ ... ]        // dumpRng일 때만: 같은 seed의 _rand() 앞부분(소비량 상한 = sets+unlock+10+2·(t0+shuffleTile))
    }
  ]
}
```
- `positions[i] = [레이어 키, 위치 키, inner]`. inner = -1이면 보드 타일, k≥0이면 그 위치 컨테이너(stack/craft)의 `stackCTileList[k]`(0=바닥). 컨테이너 내부 t0는 루트 위치 차례에 index 0부터 끼워 넣는다.
- **클라가 예외를 던지는 run**(s11): `"types": null`, `"exception": {"type":"ArgumentOutOfRangeException","at":"DB_Level.cs:1253 ShuffleEmptyTiles"}`, `selfCheck.clientThrows=true`. Python 포트는 이 입력을 거부(예외)해야 한다.
- **randSeed AsInt가 0인 run**(null·누락 포함, s21): `"types": null`, `"nondeterministic": "..."`. 클라는 시간 기반 시드를 쓰므로 정답이 없다. 포트는 예외로 거부하면 된다.
- run별 결과 분류(`_manifest.json`의 `outcomes`): `pass` / `fail`(배정됐지만 종류별 3배수 깨짐) / `exception`(클라 예외) / `nondeterministic`(seed 0).
- 비교 권장: `types` 배열 완전 일치 + `positions` 일치. `resolvedMap`은 P0-G5(봇이 읽은 타입 == 덤프)에 쓴다.

pytest 예:
```python
import json, pathlib
G = pathlib.Path("backend/tests/golden/pv_t0")
for exp_path in sorted((G / "expected").glob("[rs]*.json")):          # _manifest.json 제외
    inp = json.loads((G / "inputs" / exp_path.name).read_text())
    exp = json.loads(exp_path.read_text())
    for run, res in zip(inp.get("runs") or [{}], exp["results"]):
        row = {**inp["row"], **run}
        ...  # port(row["map"], row) -> types; res["exception"] 있으면 예외 기대, 아니면 == res["types"]
```

### expected/_manifest.json
`cases[]`: `file`, `kind`, `runs`, `t0Count`(첫 run), `selfCheckOk`, `clientThrows`, `expectSelfCheck`(run별이면 "perRun"), `outcomes[]`, `asExpected`. `unityRandomCallers`: 실행 중 `UnityEngine.Random.Range`를 부른 타입(현재 `["spEncrypt"]`).

## 케이스 (합성 27 · 실레벨 35 = 62파일, run 총 371)

자체점검(마지막 확인): **62/62 asExpected.** pass 케이스는 모든 run에서 (명시+배정) 종류별 개수가 3의 배수이고 `types` 길이 = 입력 t0 수다.

| 케이스 | run | t0 | 기대 | 내용 |
|---|---|---|---|---|
| s01_single_layer_9 | 4 | 9 | pass | 단일 레이어 3×3, utc 1/3/4 |
| s02_multilayer_pure_t0 | 26 | 96 | pass | 3레이어(홀짝·크기 혼합) + 효과(ice/chain/grass/bomb/curtain/teleporter/unknown/frog/link). seed 1, 2³¹−1, 고정 20개, utc 1/3/4/12/15 |
| s03_containers_oldformat | 3 | 69 | pass | 구포맷 stack/craft `[cnt]`(craft effect null 포함) + 보드 t0 |
| s04_newformat_inner_mixed | 2 | 25 | pass | 신포맷 inner 명시+"t0" 혼재(`t5_t0_t0`, `t0_t7_t0`), 개수 불일치 `[3,"t1_t2"]` → 전부 t0 폴백, toAdd 패딩 1 |
| s05_explicit_padding | 3 | 31 | pass | 보드 명시 t2×4·t9×1 → 패딩이 앞쪽 t0를 소모 |
| s06_key_tiles | 3 | 33 | pass | inner `key_t0_t0`, 보드 `"key"`, `["t0","key"]`(=키, empty 아님). unlockTile 0/1 |
| s07_unlocktile_pure | 3 | 45 | pass | 순수 t0 + unlockTile 1/2 (마지막 세트 → 16) |
| s08_negative_seed | 3 | 30 | pass | seed −1, −123456789, −2³¹ → `(uint)` 캐스팅 |
| s09_shuffletile | 2 | 30 | pass | shuffleTile 5/37 |
| s10_imbalance_6sets | 2 | 18 | pass | imbalance 5, delta ±4.5 — clamp+재보정 때문에 반올림 방식과 무관한 결과 |
| s10_imbalance_banker | 2 | 90 | pass | utc15, 30세트, imbalance 5 → 색상1 delta `RoundToInt(-4.5)`. **banker's → 색상별 세트 [0,2,6,10,12]** (away-from-zero면 [0,1,6,11,12]) |
| s10_imbalance_misc | 4 | 36 | pass | imbalance 3, 10(utc9), 숫자 0.5, 문자열 "5" |
| s11_non_multiple_of_3 | 1 | 10 | exception | t0 10, 명시 없음 → 클라 예외 |
| s12_noncanonical_order | 2 | 36 | pass | tiles 키 셔플 순서, map 키 `layer_1, layer, layer_0` |
| s13_no_t0 | 1 | 0 | pass | t0 없음 → 즉시 return, types `[]` |
| s14_utc0_shim_dependent | 1 | 30 | pass | useTileCount 0 → **shim 값**(GetTileCount=16 → 15종). 권위 없음 |
| s15_string_fields | 1 | 30 | pass | randSeed·useTileCount 등을 문자열로 |
| s16_large_utc15 | 5 | 195 | pass | 6레이어 대형, utc 15 |
| s17_padding_remainder_valid | 2 | 10 | pass | t0 10(%3≠0)이지만 명시 t3×2 → 패딩 1 + 3세트로 유효 |
| s18_padding_breaks_sets | 1 | 9 | fail | t0 9 + 명시 t2×1 → 패딩 2, 남은 7칸에 3세트 → 1세트가 잘림(예외 없이 클리어 불가 배치) |
| s19_null_fields | 2 | 30 | pass,pass | unlockTile·shuffleTile·typeImbalance·tileSkin·layer = null → AsInt 0. run2 useTileCount null → 0 → shim 15종(`shimDependentRuns`) |
| s20_missing_fields | 1 | 30 | pass | 위 필드 키 자체가 없음 → AsInt 0 |
| s21_seed_null_missing | 3 | 30 | nondet,nondet,pass | randSeed 누락·null → 0 → 시간 기반. run3 seed 5 + useTileCount 누락 → shim 15종 |
| s22_string_numeric_edges | 8 | 30 | pass×8 | 문자열 "1.9"→1, "3000000000"→int −1294967296(uint 3000000000), "-5", "-2147483649"→2147483647, utc "7.9"→7, unlock "1.9"→1, shuffle "2.5"→2, imbalance "5.9"→5 |
| s23_layer_keys_reversed | 2 | 12 | pass,pass | map 키 `layer, layer_1, layer_0`. 순회 = layer_0 먼저(번호순), layerIndex = {layer_1:0, layer_0:1}(등장순) |
| s24_effect_key_plain | 2 | 6 | pass,pass | `["t0","key"]`, `["t3","key"]`, `["t0","KEY"]` → 전부 키(16), empty 아님 |
| s25_inner_count_mismatch | 2 | 35 | pass,pass | `[3,"t1_t2"]`, `[2,"t1_t2_t3"]`, `[3,""]`, `[3,null]` → 전부 t0 폴백. `[4,"t1_t1_t1_t2"]`는 명시 채택(t2 패딩 2) |
| r_level_0004…0031 (25개) | 8 each | 33~87 | pass | 레벨 4~31 중 t0 보유 25개(10·20·30 제외), 테이블 행 그대로 + randSeed만 교체 |
| r_level_0149/0208/0256/0341/0559/0599/0768/0911/1456/1467 | 8 each | 3~21 | pass | 32+ count-only 컨테이너 레벨(구포맷 `[cnt]`). 599·911·1467은 빈 레이어 `"tiles": []` 포함 |

- 실레벨 출처: `sp_meowsgarden/Assets/StreamingAssets/GBoost/` baked 파일(2026-09-18 11:44)을 spZip(XOR+ZIP)으로 복호. 맵 = `levelmap_level_{(n-1)/100}` 샤드의 해당 레벨(키 순서 그대로), 행 = `levels` 테이블(`id` 제외 전 필드, 끝에 `map` 추가). 원래 randSeed는 전부 0(시간 기반)이라 seed 8개 {1, 7, 12345, 625901, 104729, 998244353, 1834920117, 2147483647}로 교체.
- 04 A3-4의 "P1 표본 실레벨 20개"는 표본이 정해지지 않아 넣지 않았다. 그 레벨들은 t0화(E-P1-2) 결과가 있어야 입력을 만들 수 있다. 표본이 정해지면 `inputs/`에 추가하고 `all`을 다시 돌리면 된다.
- randSeed가 AsInt 0(0·null·누락)이면 types 없이 `nondeterministic`으로 기록한다(시간 기반이라 재현 불가).

## shim 위험 지점 (원본 동작을 바꿀 수 있는 곳)

| shim | 원본에서 쓰이는 곳 | 위험 판단 |
|---|---|---|
| `UnityEngine.Random.Range` (고정 시드 System.Random) | spEncrypt/SimpleJSON의 난독화 키(`m_nEncrypt`)만. 배정 로직(DB_Level 추출분)에는 호출이 없다(원문 검색 + 실행 중 호출자 기록 `unityRandomCallers=["spEncrypt"]`) | 키 값은 XOR/덧셈 마스크로 왕복되므로 논리값 무관. 검증 실패 시 원본이 `Debug.LogError` 후 ""를 돌려주는데, 그 호출 횟수가 0임을 매 실행 확인한다 |
| `Mathf.RoundToInt = (int)Math.Round(float)` | DistributeTiles 1-C(imbalance>0) | Unity 구현과 같은 식(짝수 반올림). s10_imbalance_banker로 결과 차이가 드러나는 케이스를 고정. **Unity 실제 값은 G3로 확인 필요** |
| `Mathf.Max/Clamp` | DistributeTiles, ColorCapacityOf | 정수 표준 동작 |
| `TileSetting.GetTileCount` = 16 고정 | ShuffleEmptyTiles 1190: `useTileCount<=0`일 때만 maxTileIndex에 쓰임 | **실제 값은 스킨 프리팹(tileSkinGroups)에 달려 있다.** s14만 의존하고 `shimDependent`로 표시. 정답으로 쓰지 말 것 |
| `TileSkinRotation.HasIconOrderForLevelID` = true | ApplyVisualTileRemap 1312 | 현 라이브 스킨 0/1 모두 icon_order 보유(01 §2) → 리맵 생략이 실제 동작. 합성 입력엔 visualTileSeed 없음, 실레벨은 `""`(키 존재) → 같은 이유로 생략 |
| KLogger·spGBoostMng·GameController·Tile·spItem·spEncryptDB | 로그/보상/레벨 저장 경로 | 배정 로직과 무관(no-op 또는 빈 객체) |
| 링크한 원본 그대로 | SimpleJSON.cs, spEncryptValue.cs, spInteger.cs, zWellRandom.cs, TileEffectType.cs | 파싱·AsInt·키 순서는 클라 원본 코드 |

그 밖의 차이: .NET 8(CoreCLR) `Dictionary` 열거 순서가 Unity Mono/IL2CPP와 같다는 것은 명세 보장이 아니다(삭제 없는 삽입 순서). 이 하네스가 확인할 수 없으므로 **G3(Unity 에디터 덤프)와 기기 로그(P3)로 확인**해야 한다.

## 원문 실행에서 확인한 사실 (01 노트와 다른 점 포함)

1. **(01 §3-5와 다름) t0가 세트로 덮이지 않으면 클라는 예외를 던진다.** 세트 수 = `floor(t0수/3)`(+unlockTile)인데, 배정 루프는 `randomTileIndexList[setCount/3]`를 범위 검사 없이 읽는다(DB_Level.cs:1253). `ceil((t0수 − 패딩수)/3) > floor(t0수/3)`이면 `ArgumentOutOfRangeException` → 레벨 로드 실패(s11). 01 노트의 "마지막 세트가 1~2개만 놓여 클리어 불가"는 남는 칸이 세트 범위 안에 있을 때만 맞다(s18: 예외 없이 불완전 세트).
2. **t0수 %3 ≠ 0이어도 유효할 수 있다.** 명시 타일 패딩(toAdd)이 t0 일부를 먼저 쓰므로, 판정 기준은 "(명시+배정) 종류별 3의 배수"다(s17). 04 §A2 단언 ①(key 제외 t0 총수 %3==0)은 순수 t0 맵에서는 맞지만 명시+t0 혼합(key 레벨 신포맷)에서는 기준이 다르다.
3. `typeImbalance`를 숫자 0.5로 넣으면 런타임 `AsInt`가 0이다(01 §9-2 추정 확인). 문자열 "5"는 5.
4. WELL512 첫 5개 원시값이 01 §3-6의 Python 산출값과 C# 실행 결과에서 같다(01 미확인 4번 해소).
5. 샤드에 `"tiles": []`(빈 배열) 레이어가 9개 레벨에 있다(599·615·665·671·736·829·911·1466·1467). 클라는 0타일로 처리한다. Python 포트는 dict가 아닌 `[]`도 받아야 한다.
6. **레이어 순회와 layerIndex는 기준이 다르다**(s23). `GetEmptyTileList`는 `layer_{i}`를 번호순으로 조회(CS:880-882)하므로 t0 순회는 번호순이다. 01 §9-1의 "layerIndex = 키 등장 순번"(CS:548-553)도 맞다. 둘 다 사실이며, 배정 결과는 번호순 순회만 따른다. 키가 역순이면 CTile.layerIndex가 이름과 어긋나 런타임 덮임 판정이 달라질 수 있다(배정과는 별개. GB 정규화가 레이어 키를 `layer, layer_0..N-1` 순으로 고정하므로 정규 맵에서는 둘이 일치).
7. AsInt = `(int)AsLong`. 문자열 소수는 버림, int 범위를 넘는 값은 하위 32비트로 잘린다(s22). null·누락 필드는 0(s19~s21).
