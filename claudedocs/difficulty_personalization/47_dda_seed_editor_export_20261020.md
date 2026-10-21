# 47. 맵에디터 DDA 시드 갱신 버튼 + GameBoost 익스포트 두 필드 (2026-10-20)

> 승인 범위: 맵에디터 로컬 기능 구현·문서·경량 fixture 검증만. 실제 GameBoost 전송/서버 변경, 운영데이터 변경, 게임 연결,
> Unity, 샤드 재굽기, 봇/시드 탐색, 126 배정, 커밋/푸시는 **하지 않는다**.
> 준비된 시드는 "실제 난이도 확인"이나 "Unity 검증 완료"를 뜻하지 않는다(문서 46·게임 IMPL_SPEC .406 후속 판정 상한 유지).
> 선행: [46](46_dda_t0_all_levels_prep_20261020.md) (후보 1216 시드), 게임측 `sp_meowsgarden/tools/out/dda_runtime_t0_20261020_1601/README.md` (해시 계약 §3).

## 1. 계획 (구현 전 기록)

### 1-1. 접점
| 구분 | 위치 |
|---|---|
| 버튼 UI | 프로덕션 → 테스트 탭 (`ProductionDashboard/index.tsx` TestTab) 도구 줄 → `DdaSeedRefreshPanel.tsx` |
| 레벨 저장 | `storage/productionStorage.ts` `saveProductionLevel` (IndexedDB) → 자동 동기화로 맵에디터 백엔드 `backend/data/production/` (GameBoost 아님) |
| 익스포트 | `ProductionExport.tsx` → `POST /api/gboost/{board}/{id}` · `POST /api/gboost/upload-local` → `gboost.py::_convert_to_townpop_format` |
| 판정 | 백엔드 `app/core/dda_seed_catalog.py` (익스포트와 같은 변환 코드로 map 해시 계산) + `POST /api/dda-seeds/preview`, `POST /api/dda-seeds/export-preview` |
| 개발용 목록 | `backend/data/dda_seeds/dda_t0_seed_catalog.v1.json` (sha256을 로더에 고정. 생성: `backend/scripts/build_dda_seed_catalog_20261020.py`) |

### 1-2. 입력 (읽기 전용 정답)
- `dda_runtime_t0_20261020_1601/server/server_levels_dda_columns.csv` (시드 1216행), `verify/dda_t0_verify_list.json` (status·sourceMapSha256·N·사유), `verify/cross_check.json`.
- 시드는 그대로 재사용한다(후보 1216 × easy 5 + hard 5, cand 1..5 순서). 새로 생성·탐색·측정하지 않는다.
- 서버에 추가되는 항목은 `ddaEasySeeds`, `ddaHardSeeds` 두 컬럼뿐이다. hash, version, 허용 목록은 개발용 목록에만 둔다.

### 1-3. 갱신 정책 (버튼)
레벨별 판정 순서는 다음과 같다.
1. 자료 없음 → 건너뜀
2. 보류(hold 126) / L322(partial_hold) / 제외(auto_apply_excluded) → 건너뜀 + 사유
3. 현재 에디터 map 해시 ≠ sourceMapSha256 → 건너뜀(원본 불일치)
4. 익스포트 useTileCount(타일에서 도출) ≠ N → 건너뜀(N 불일치)
5. 방향별 현재 값 분류: `match`(정답과 같음) / `missing`(없음·빈 값) / `invalid`(개수·형식·0·음수·overflow 오류) / `other`(형식은 정상이나 정답과 다름)
   - 한쪽이라도 `other`이면 충돌로 처리하고 **두 방향 모두 건너뛴다**(자동으로 덮어쓰지 않음).
   - `missing`/`invalid` 방향만 정답 값으로 보충·복구한다(미리보기에 이전 값과 새 값을 표시). `match`는 유지한다.
- 버튼을 누르면 사전검사와 미리보기만 실행하고 아무것도 바꾸지 않는다. 사용자가 "적용"을 눌러야 저장한다. 처리 중에는 중복 클릭을 막고, 다른 일괄 작업이 진행 중이면 비활성화한다.
- 저장 직전에 IndexedDB에서 다시 읽어 미리보기 시점의 level_json과 다르면 경합으로 보고 건너뛴다. 현재 선택 레벨에 미저장 다이얼 조정이 있으면 그 레벨도 건너뛴다.
- 레벨별로 저장하고, 실패·경합 목록과 부분 성공 건수를 표시한다. 같은 버튼을 다시 누르면 모두 "유지"로 나온다(멱등).
- 조건 해시(sourceConditionHash)는 출시 테이블 행(GameBoost가 타입을 붙여 구운 값) 기준이므로 에디터에서 재현할 수 없다. 에디터의 "배정 조건" 판정은 후보 상태 + map 해시 + N으로 한정한다. 조건 해시 검사는 런타임 몫으로 남는다.

### 1-4. 익스포트 계약
- `board_id == "levels"`일 때만 두 필드를 **항상 명시**한다(키 누락 없음).
  - `level_N`이고 후보이며 map 해시와 N이 맞고 저장값 두 방향이 모두 정답과 정확히 같으면 그 값을 쓴다(쉼표 구분, 공백 없음, 5개, 순서 보존).
  - 그 외(제외·보류·원본 변경·잘못된 시드·한쪽만 정답·목록 검증 실패·`infinity_*` 등)는 두 필드 모두 `""`로 보낸다. 오래된 서버 값을 지우기 위해서다. 에디터 내부 값은 지우지 않는다.
- 다른 보드에는 필드를 추가하지 않는다(컬럼 존재를 알 수 없음).
- 기존 맵에디터 → GameBoost 행 저장(`real_array.php act=save`, 기존 행이면 `new=0` update) 동작에 대한 근거:
  - 키를 누락했을 때 서버가 기존 값을 유지하는지 지우는지는 **코드·문서 어디에도 근거가 없다**. 그래서 키를 누락하지 않는 방식으로 우회한다.
  - `""` 전송은 기존 필드(`typeImbalance`, `""`)가 출시 테이블에 `''`로 구워진 선례가 있다. 다만 **비어 있지 않은 기존 값을 `""`로 덮어쓰는 동작은 실업로드로 확인하지 않았다**(승인 범위 밖).
- 익스포트 충돌 단계(기존 "덮어쓰기/백업 후 업로드" 확인 흐름)에서 서버 현재 값과 비교해 경고한다: 비움 예정(서버 값 있음 → `""`), 다른 값으로 변경, 신규 기입.

### 1-5. 해시 계약
- `sourceConditionHash = sha256(dump(행 − {map, ddaEasySeeds, ddaHardSeeds}))`이다. 새 두 필드는 제외 대상이므로 행에 들어가도 해시가 변하지 않아야 한다. L158 출시 행 + 두 필드로 골든을 비교한다.
- 맵 해시는 `dump(_convert_to_townpop_format(level_json)["map"])`로 계산한다. 출시 샤드 map과 바이트가 같아야 한다(사전 조사: LIVE 일치본 배치 1489/1499 일치).

## 2. 결과 (2026-10-20 16:4x KST)

### 2-1. 수정 파일
| 파일 | 책임 |
|---|---|
| `backend/scripts/build_dda_seed_catalog_20261020.py` (신규) | 입력 3개(읽기 전용, `--src` 인자)로 개발용 목록 생성. cross_check sha 불일치 시 중단 |
| `backend/data/dda_seeds/dda_t0_seed_catalog.v1.json` (신규) | `dda_seed_catalog.v1`, sha256 `57930b55…5d13`, 1499레벨(candidate 1216 / hold 126 / auto_apply_excluded 156 / partial_hold 1). 출처 sha: csv `c8c21045…`, verify `34ecf084…`, cross_check `beb75b74…` |
| `backend/app/core/dda_seed_catalog.py` (신규) | 목록 로드(sha·버전 고정), 형식 검사, `plan_level`, `export_fields`, `source_condition_hash` |
| `backend/app/api/routes/dda_seeds.py` (신규) + `main.py` | `GET /api/dda-seeds/catalog`, `POST /preview`, `POST /export-preview` (읽기 전용) |
| `backend/app/api/routes/gboost.py` | 단건 저장·upload-local 두 경로에서 `levels` 보드면 두 필드 주입. 목록 응답에 서버 값 추가 |
| `backend/app/clients/gboost.py`, `backend/app/models/schemas.py` | 목록 행의 `ddaEasySeeds/ddaHardSeeds` → `dda_easy_seeds/dda_hard_seeds`(컬럼 없으면 null) |
| `frontend/src/api/ddaSeeds.ts` (신규), `types/index.ts` | API·타입 동기화(`LevelJSON.ddaEasySeeds/ddaHardSeeds`, `LevelMetadata.dda_*`) |
| `frontend/src/components/ProductionDashboard/DdaSeedRefreshPanel.tsx`, `ddaSeedApply.ts` (신규), `index.tsx` | 테스트 탭 버튼·미리보기·적용(순수 로직 분리) |
| `frontend/src/components/ProductionDashboard/ProductionExport.tsx` | 충돌 단계에 서버 값 비움·변경·신규 경고 |
| `backend/tests/test_dda_seed_catalog.py`, `backend/tests/fixtures/dda_seeds/levels_fixture.json` (신규) | 경량 검증(fixture: LIVE 일치본 배치 L5·40·111·158·159·322·1466 + 출시 L158 행) |

### 2-2. 사용 순서 (UI)
1. 프로덕션 탭에서 배치 선택 → **테스트** 탭 → 상단 '🎚️ DDA 시드 갱신'을 누른다(다른 일괄 작업 중이면 비활성).
2. 미리보기를 확인한다: 대상 범위, 갱신 예정/유지/충돌/보류 수와 사유, 갱신 예정 레벨별 easy·hard 이전→새 값(보충/복구).
3. '적용'을 누르면 맵에디터 내부 레벨만 저장된다(IndexedDB → 맵에디터 백엔드 자동 동기화). 결과에 저장, 경합, 미저장 편집, 실패 목록이 표시된다. 다시 누르면 '유지'로 나온다.
4. 익스포트: 기존 GBoost 업로드 흐름 그대로다. 덮어쓸 행이 있으면 충돌 단계에 DDA 경고(비움 예정/변경/신규)가 함께 표시되고, 기존 확인 버튼으로 진행한다.

### 2-3. 검증 (실제 수행)
| 항목 | 결과 |
|---|---|
| pytest `test_dda_seed_catalog.py` 30건: 목록 sha·집계, L158 map 해시 = 출시 샤드, sourceConditionHash 골든(두 필드 포함 행 = 제외 행 = 정답, 포함 계산 시 불일치 대조), 목록 변조 거부, L158 유지, 양쪽/한쪽 보충 + 멱등, 형식 오류 10종(개수·0·음수·overflow·공백·선행0·빈 토큰·비숫자·비문자열) 복구와 이전/새 값, 다른 정상 값 충돌(두 방향 건너뜀·익스포트 `""`), L322/126(L111)/제외(L40)/자료없음(L5)/원본불일치(L1466·타일 변경)/N불일치 건너뜀, 익스포트 기존 컬럼·순서·map 불변 + 내부 값 불변, 빈 값 직렬화, infinity·다른 보드, API 2종, 가짜 클라이언트로 저장 라우트 payload 확인, 가짜 HTTP 세션으로 목록 서버 값 파싱 | 30 PASS |
| 적용 로직(node, esbuild 번들, 백엔드 실제 미리보기 결과 입력) 8건: 저장 158·159, 값=목록, 다른 필드/map 불변, 비대상 불변, 묵은 계획 재적용 시 저장 0(경합), 편집 경합 건너뜀, 미저장 편집 건너뜀, 저장 실패 → 부분 성공 목록 | 8 PASS |
| 저장 → 재로드 → 익스포트 (임시 디렉터리로 돌린 production_store PUT/GET 왕복): 필드·JSON 동일, 재미리보기 keep, 익스포트 값 = 정답 | PASS |
| 정답 1216 출력 대조 (LIVE 일치본 배치 1530레벨, 미리보기 → 적용 시뮬 → 익스포트 vs 서버 CSV) | 1529 일치 / 1 불일치(L1466: 에디터 맵이 출시와 달라 원본불일치로 `""`, 의도된 동작) |
| `npx tsc --noEmit` | 오류 0 |
| Playwright 웹뷰 | **미실행**(사유 §3) |

미리보기 집계 (LIVE 일치본 배치 `batch_1792056041502_cn5e4ny66`, 현재 저장값 없음): 갱신 예정 1215, 유지 0, 충돌 0, 건너뜀 315 = 자료없음 31(L1~31) + 제외 156 + 보류 126 + L322 1 + 원본불일치 1(L1466). 적용 후 재검사: 유지 1215 / 건너뜀 315.

예시 출력 (L158, levels 보드):
```
"ddaEasySeeds": "1155111777,1118964341,1181919731,1151877339,1102526043",
"ddaHardSeeds": "1139242953,1154649038,1149573757,1148912175,1159080332"
```
L40(제외)·L322·infinity_N: `"ddaEasySeeds": "", "ddaHardSeeds": ""`.

### 2-4. 확인된 사항·주의
- **에디터 익스포트 행 ≠ 출시 행** → 원인과 수정은 §5. (17:3x 정정: 처음 보고한 `rewardCoin 5→10`, `difficulty 61→-1`은 업로드 UI가 넣는 값을 거치지 않은 조사 스크립트의 결과였다. 실제 업로드 기본 설정(rewardCoin 고정 5, meta 예측 클리어율 0.6113 → 61)에서는 L158이 일치한다. 남는 차이는 `backgroundIndex/tileSkin`, `rewardList`, `visualTileSeed`, 그리고 자료형이다.)
- 조건 해시는 에디터에서 검사하지 않는다(재현 불가). 에디터 판정은 후보 상태 + map 해시 + N이다.
- 키 누락 시 서버 처리 방식은 근거가 없어 항상 명시하는 방식으로 우회했다. **`""`로 기존 비어 있지 않은 값을 덮어쓰는 동작은 실업로드로 확인하지 않았다.** 첫 실업로드 전에 사용자 승인 하의 1행 확인이 필요하다.
- ~~충돌 검사 단계에서 목록 조회가 실패하면 경고 없이 업로드로 진행~~ → §6에서 fail-closed로 수정했다.

## 3. 미검증 / 보류
- Playwright 웹뷰: 미실행. 앱을 마운트하면 `/api/gboost/health`(실 GameBoost 호출)와 배치 자동 동기화(실 `backend/data/production` 쓰기)가 일어나므로, 차단 장치 없이 띄우지 않았다. 메모리 압박도 warn 상태였다.
- 실제 GameBoost 업로드/서버 반영, 굽기 후 런타임 조건 해시 일치, Unity G3, 배정 후 정합·난이도: 전부 미검증·보류.
- 준비된 시드는 실제 난이도 확인이나 Unity 검증 완료를 뜻하지 않는다.

## 4. 사고 기록 — 기존 테스트의 실 GameBoost 호출 (16:39~16:40 KST)
- 관련 회귀를 보려고 기존 `tests/test_api.py -k gboost`를 2회 실행했다. 이 환경은 GameBoost 클라이언트가 실제로 설정되어 있어서(`gameboost.cafe24.com`, project `6d126f4db852`) 다음 호출이 실서버로 나갔다.
  - `GET /health`
  - `test_gboost_not_configured`: **`POST /api/gboost/test_board/test_level` 저장 2회 + 썸네일 업로드.** 이 테스트는 "미설정"을 가정했는데 200이 반환되어 FAIL했다.
- 영향: `test_board` 보드에 `test_level` 행 1개(`tests/test_api.py` sample_level fixture, `etime` 포함)가 저장되었다(2회 저장 = 같은 키 생성 후 갱신 또는 갱신 2회). 썸네일 업로드는 저장마다 1회씩 최대 2회 시도했다(성공 여부는 응답을 남기지 않아 미상). `GET /health`도 2회 호출했다.
- **기존 내용 불명**: 실행 전 `test_board/test_level`이 서버에 있었는지, 있었다면 무엇이었는지는 확인하지 않았고 지금도 확인하지 않는다(서버 읽기도 금지 범위). 이전 값이 덮어써졌을 가능성이 있다.
- `levels` 보드와 DDA 필드에는 영향이 없다(보드가 다르면 필드를 넣지 않음).
- 삭제·복구하지 않는다(사용자 승인 범위 밖). 지금 상태 그대로 보존한다.
- **재발 방지(완료, 17:3x)**: `backend/tests/conftest.py`로 테스트 세션 전체를 격리했다(§5-0). 이후 `test_api -k gboost`를 다시 실행했고 결과는 2 PASS, 외부 연결 시도 0, FakeGBoostClient 호출 0이었다.

## 5. 승인 후속 (2026-10-20 17:30~ KST) — P0 격리 · P1 행 보존 · fail-closed

### 5-0. P0 테스트 격리 (`backend/tests/conftest.py`, 신규)
- `pytest_configure`에서 설치한다. 테스트 모듈 import·수집보다 먼저 실행된다.
  1. **전송 계층 차단**: `socket.socket.connect/connect_ex/sendto`, `socket.create_connection`, `socket.getaddrinfo`(localhost 외)를 가로챈다. AF_UNIX만 통과시킨다. 시도하면 즉시 `NetworkBlocked`를 던지고 `NETWORK_ATTEMPTS`에 기록한다.
  2. **aiohttp 차단**: `aiohttp.ClientSession`(GameBoost 클라이언트가 쓰는 유일한 HTTP 경로, `app/clients/gboost.py:3`)을 생성 자체를 차단하는 클래스로 교체한다.
  3. **클라이언트 격리**: `app.clients.gboost._client`, 그리고 `get_gboost_client`/`update_gboost_client`의 정의 모듈과 import해 간 모듈(`app.clients`, `app.api.deps:5,25`, `app.api.routes.gboost:30` 참조 지점 60·74·80)을 모두 미설정 `FakeGBoostClient`로 바꾼다. FastAPI `get_gboost` 의존성도 override한다. Fake의 메서드가 호출되면 기록 후 예외를 던진다.
  4. 세션 종료 시 시도가 1건이라도 있으면 종료 코드를 실패로 바꾸고, 요약 줄 `[network-guard]`를 출력한다.
  - `.env`·전역 설정·자격증명은 읽기만 한다(수정 없음).
- 정적 근거: 앱에서 외부 통신을 하는 import는 `app/clients/gboost.py:3 aiohttp` 하나뿐이다(`grep -E "^(import|from) (aiohttp|httpx|requests|urllib|socket)" app` 결과). 라우트의 네트워크 지점은 모두 `client.*` 호출이다(`gboost.py` health·save·load·list·delete·upload-local·thumbnail). 이 client는 `Depends(get_gboost)` 또는 `get_gboost_client()`로만 얻으며, 둘 다 Fake로 대체된다.
- 실행 순서와 증거:
  1. `tests/test_network_guard.py` 먼저 실행: 2 PASS, `[network-guard] 차단된 외부 연결 시도 0건, FakeGBoostClient 호출 0건`. TEST-NET `192.0.2.1`·`.invalid` 도메인으로 의도한 시도는 전송 전에 차단됨을 확인했고, 그 기록은 테스트 안에서 지웠다.
  2. 그다음 `test_api -k gboost`: 2 PASS, 시도 0.
- 기존 DDA 테스트가 override를 `pop`하면 격리가 풀리므로, 이전 값을 복원하도록 고쳤다(`_restore_override`).
- 범위: `backend/tests/` 아래만 해당한다. 저장소 루트의 `test_*.py`·`*.sh` 스크립트는 pytest testpaths 밖이라 이 격리가 적용되지 않는다(실행하지 않음).

### 5-1. P1 원인 — 필드별 경로
| 필드 | 출시 행(L158) | 에디터 업로드 행 | 원인 (경로·파일:줄) |
|---|---|---|---|
| backgroundIndex | `null` | `"0"` | 에디터 배치 level_json에 키가 없다 → `gboost.py:481`의 기본값 0 |
| tileSkin | `null` | `"0"` | 같음, `gboost.py:482` |
| rewardList | `null` | `"[]"` | `gboost.py:517`의 기본값 `[]` |
| visualTileSeed | `""` | 키 없음 | `gboost.py:495-496`: None이면 키를 생략 |
| rewardCoin | `5` | `"5"` (기본 설정) | `ProductionExport.tsx:948`의 UI 일괄값(기본 fixed 5)이 들어간다 → 값은 같고 자료형만 문자열. 설정을 바꾸면 값도 바뀐다 |
| difficulty | `61` | `"61"` | `ProductionExport.tsx:954` meta.predicted_clear_rate(0.6113) → `gboost.py:503` round(×100). 미측정이면 -1 |
| (전체) | 정수형 | 전부 문자열 | `gboost.py:479~` 변환이 모든 칼럼을 `str()`로 만든다 |
| etime | (출시 테이블에 없음) | 업로드 시각 | `gboost.py:518` |
- 경로: LIVE 일치본 배치는 서버에서 import한 것이 아니다. 에디터 생성 배치를 복제한 것이다(`backend/scripts/live_match_batch.py`). 대조한 행 키는 `ROW_KEYS`(:39 — randSeed·useTileCount·unlockTile·shuffleTile·typeImbalance·autoCollectCount·timea·layer·col·row·num)뿐이었다. 그래서 위 필드들은 level_json에 저장된 적이 없다.
- 이후 경로(내부 저장 → 재로드)는 level_json을 그대로 보존한다(§2-3 왕복 PASS). 원인은 **익스포트 변환의 기본값 채움**이다.
- 신뢰할 수 있는 원본 행 snapshot은 에디터 안에 없었다. 출시 테이블 복호 사본(`data/pv_sandbox/dda_t0_all_20261020/live_copy/b741f6a3/levels.json`)이 유일한 근거다.

### 5-2. P1 수정
1. **원본 행 스냅샷**: `backend/data/dda_seeds/dda_t0_source_rows.v1.json` (sha256 `063954da…120e`, 로더에 고정. `catalogSha256`으로 목록에 결속).
   - 1499행을 자료형·키 순서 그대로 담았다. 각 행은 sourceConditionHash가 목록 값과 같은지 확인한 뒤 수록했다(1499/1499).
   - 생성: `build_dda_seed_catalog_20261020.py --source-rows <levels.json>`. 목록(`57930b55…`)은 바꾸지 않았다. 검증 목록 해시를 다시 만드는 방식은 쓰지 않았다.
2. **일반(전체 행) 익스포트**: 사용자가 편집한 값은 그대로 보낸다(스냅샷으로 덮어쓰지 않음). 다만 업로드 행(map·시드·etime·id 제외)이 스냅샷과 다르면 유효 시드라도 두 필드를 `""`(`row_changed:<키들>`)로 보낸다.
   - 이유: 행이 바뀌면 런타임 조건 해시가 달라져 그 시드는 더 이상 검증된 값이 아니다.
   - 결과: 현재 에디터 배치의 일반 익스포트는 L158 등 후보 시드를 `""`로 보낸다.
3. **'DDA 시드만 내보내기'**(신규): `POST /api/gboost/dda-seed-export` + `DdaSeedOnlyExport.tsx`(익스포트 탭 GBoost 영역, `levels` 보드 + `level_` 프리픽스일 때만 표시).
   - 서버 기존 행을 strict로 조회해, 그 사본에서 두 컬럼만 바꿔 보낸다. 다른 값·자료형·키 유무·키 순서·map·etime·미지 필드는 서버 값 그대로 돌려보낸다(`id` 키만 제외 — 기존 업로드도 행 안에 id를 넣지 않음). 변환·기본값·썸네일은 없다.
   - 아래 경우는 차단하고 사유를 표시한다: 스냅샷 없음, 서버 행 없음/형식 오류, 시드 컬럼 없음, 서버 행이 스냅샷과 다름(값·누락 키·미지 키), 서버 map이 sourceMapSha256과 다르거나 확인 불가, 조회 실패.
   - 실행할 때마다 다시 strict 조회한다. 미리보기 digest와 다르면 `server_changed_since_preview`로 차단한다. 비움·변경은 confirm이 필요하다. UI는 미리보기를 1회만 쓴다.
4. 조건 해시 계약(`행 − map/두 시드`)은 그대로 유지했다. 비교에서 etime을 제외한 근거는 출시 테이블 키에 etime이 없기 때문이다.

### 5-3. fail-closed (단일 · 일괄)
| 경로 | 조치 |
|---|---|
| 클라이언트 `load_level/list_levels` | `strict=True`일 때 HTTP 비200(404 제외)·빈 응답·JSON 오류·연결 오류를 `GBoostLookupError`로 올린다. 404/`{}`만 "없음". 기본값(비strict)은 기존 동작 그대로 |
| `GET /api/gboost/{board}?strict=true` | 조회 실패 → 502 |
| `POST /api/gboost/{board}/{id}` (단일, 프로덕션 업로드 루프·GBoostPanel 공용) | `levels` 보드면 기존 행을 strict 조회한다. 실패 → 502(업로드 안 함). 서버 시드를 비우거나 바꾸는데 `dda_confirm`이 없으면 → 409 |
| `POST /api/gboost/upload-local` (일괄, GridEditor 업로드 모달) | 같은 검사를 행별로 한다. 조회 실패 → failed, 확인 없는 비움/변경 → skipped |
| `ProductionExport` 충돌 검사 | 목록 strict 조회. 실패하면 업로드하지 않고 오류를 표시한다(이전: 그대로 업로드). DDA 사전검사 실패나 서버 컬럼 미확인(부분 누락)이면 업로드 버튼 대신 '다시 검사'. 검사 통과 기록은 업로드 1회에 소비된다(재시도 = 새 검사). 충돌 단계에서 경고를 본 뒤 업로드할 때만 `dda_confirm=true` |
| 시드만 내보내기 | §5-2 3 |

## 6. QA 케이스 (맵툴 정본 — 별도 테스트 정본 문서 없음, 여기 기록)
| ID | 케이스 | 근거 | 결과 |
|---|---|---|---|
| DDA-ED-01 | 네트워크 격리: 전송 계층·aiohttp 차단, 실클라이언트 미생성, gboost 라우트 전부 미설정 응답, 시도 0 | `test_network_guard.py` 2 | PASS |
| DDA-ED-02 | 기존 `test_api -k gboost` 재실행 | 2 PASS, 시도 0 | PASS |
| DDA-ED-03 | 버튼 정책(L158 유지·보충·복구·충돌·건너뜀·멱등), 해시 골든, 목록 변조 | `test_dda_seed_catalog.py` 31 | PASS |
| DDA-ED-04 | 원본 행 스냅샷 = 골든 L158 행(자료형 포함)·조건 해시 결속 | `test_source_rows_pinned_and_bound_to_catalog` | PASS |
| DDA-ED-05 | 시드만: 두 컬럼만 변경(값·자료형·키 순서·map·etime 동일), ""/null/숫자 문자열/map 문자열 왕복 | `test_seed_only_changes_only_two_columns` ×4 | PASS |
| DDA-ED-06 | 시드만: 동일 값 미전송, 비움·변경은 confirm 필요 | 3건 | PASS |
| DDA-ED-07 | 시드만: 신뢰 불가 차단(다른 값·미지 필드·키 누락·시드 컬럼 없음·map 다름·map 확인 불가) | 6건 | PASS |
| DDA-ED-08 | 시드만: 조회 실패·서버 행 없음·스냅샷 없음·묵은 digest/digest 없음 재시도 차단, 모든 조회 strict | 1건 | PASS |
| DDA-ED-09 | L1466 불일치 차단, L322·L40은 ""만 | 1건 | PASS |
| DDA-ED-10 | 단일 저장 fail-closed(조회 실패 502·비움 409·confirm 200·새 행·다른 보드) | 1건 | PASS |
| DDA-ED-11 | 일반 익스포트: 명시 편집값(rewardCoin 7·tileSkin 2) 보존 + 시드 "" | 1건 | PASS |
| DDA-ED-12 | 일괄(upload-local) fail-closed: 조회 실패 failed·비움 skipped·confirm 후 성공, 저장 호출 0→1 | 1건 | PASS |
| DDA-ED-13 | 목록 strict 502 / 비strict 기존 동작 | 1건 | PASS |
| DDA-ED-14 | 클라이언트 strict: 500·빈 응답·JSON 오류 → 예외, 404·`{}` → 없음, 비strict는 None | 5건 | PASS |
| DDA-ED-15 | 일반 익스포트 L158: 출시 행과 달라 row_changed → "" (원인 필드 6개 사유 포함) | 1건 | PASS |
| DDA-ED-16 | 정답 1216 대조(시드만, LIVE 일치본 + 서버 행 = 스냅샷 + 빈 시드 가정) | fill 1215·same 274, 시드 1489/1489 = 서버 CSV, 다른 컬럼 변경 0, 차단 10(map 불일치 — L1466 포함), 스냅샷 없음 31(L1~31) | PASS |
| DDA-ED-17 | 버튼 적용 로직(경합·미저장·실패·재클릭) | node 8건(§2-3) | PASS (이전 회차) |
| DDA-ED-18 | 프론트 fail-closed(충돌 검사 strict·1회 소비 게이트·다시 검사 버튼)·시드만 UI | `npx tsc --noEmit` 0, 코드 정적 확인 | **실행 미검증** (프론트 테스트 러너 없음, Playwright 미실행) |
- 합계: pytest 58(가드 2 + 카탈로그 31 + 안전 25) PASS, `test_api -k gboost` 2 PASS, `test_pv_canonical` 16 PASS. 모든 실행에서 외부 시도 0.

## 7. 버튼 안전 사용 범위 (17:4x 기준)
- **안전(로컬)**: 테스트 탭 'DDA 시드 갱신' → 미리보기 → 적용. 맵에디터 내부 level_json의 두 필드만 바뀌고, 서버 호출은 없다.
- **사용 보류(서버 쓰기, 별도 승인 필요)**:
  - '시드만 업로드'와 일반 GBoost 업로드: 미검증 항목이 남아 있다. ① 서버 real_array가 돌려주는 행 표현(자료형·map 형식)을 그대로 다시 저장했을 때 값이 보존되는가 ② `""`로 기존 값을 덮어쓰는 동작 ③ etime을 갱신하지 않을 때 게임 델타 갱신에 미치는 영향.
  - '시드만 미리보기'(dry_run)는 쓰기는 없지만 서버를 **읽는다**. 이번 승인 범위에서는 실행하지 않았다.
- 일반 GBoost 업로드는 이제 후보 시드를 대부분 `""`로 보낸다(row_changed). 서버에 수동 입력한 L158 값이 있으면 비움 경고(409/확인)가 뜬다.

## 8. 서버 시드 저장 — 사전 조사·snapshot (2026-10-20 18:17~ KST, 서버 쓰기 0건)

### 8-1. 진행 기록
- 18:18: swap 여유 285~350MB(<500MB)로 서버 작업 보류. 18:21 swap 1303MB·pressure 1로 회복되어 진행.
- 준비:
  - 클라이언트에 `update_existing_level`(new=0 1회, `=upt` 확인, new=1 폴백 없음)과 `load_board_rows`(보드 전체 strict 조회) 추가.
  - 근거: 기존 `save_level`은 update가 확인되지 않거나 존재 확인이 실패하면 new=1로 재시도하는데, docstring상 new=1은 같은 id라도 새 레코드를 추가한다 → **중복 행 생성 위험**.
  - 전용 스크립트 `backend/scripts/dda_seed_server_apply_20261020.py` 추가(기본 읽기, lock, sleep≥0.5s, 저장 전후 원시 단건 재조회 비교). 가짜 서버·네트워크 차단 상태의 리허설 PASS. pytest 64 PASS(외부 시도 0).
- **etime·델타 계약(코드)**:
  - 게임 내 에디터는 저장할 때 클라이언트가 직접 etime을 넣는다(`Assets/08.Scripts/Tile_LevelEditor/ExLevelEditor.cs:663`). 맵에디터 업로드도 같다(`gboost.py:518`).
  - 델타 갱신기는 etime을 비교해 **map만** 받아 온다(`LevelDeltaUpdater.cs:71-119`, `StoreDelta(levelId, map)`). 행 컬럼(시드)은 전체 테이블 로드나 굽기로만 전달된다.
  - 따라서 etime을 수동으로 바꿀 필요가 없고, 바꾸지 않는다. L158 etime 1792481020 = 2026-10-20 16:23:40 KST(사용자의 관리 화면 수정 시각). 서버가 etime을 자동으로 갱신하는지는 미확인.
- 18:22 snapshot(GET 1회): 5,655,398 B, 3066행·30키, 열 개수 불일치 0, 중복 id 0, 시드 컬럼 있음. 감사 폴더 `backend/data/dda_seeds/server_apply_20261020_1822/`.
- 같은 판정 기준을 적용하자 후보 1216개가 **전부 `server_row_differs`로 차단**되었다. 18:3x 사용자 지시에 따라 기준 완화(field4 비교 제외)는 즉시 되돌렸다. 아래는 로컬 분석 결과다(`analyze_diff_local.py` → `diff_analysis_local.json`).

### 8-2. 서버 행 vs 출시 행 차이 (후보 1216)
| 유형 | 내용 | 건수·레벨 |
|---|---|---|
| (a) 서버 전용 키 | `idx`(레코드 번호, 행마다 고유) · `etime`(405가지 값) · 빈 이름 열 `''`(전부 `""`) · `field4`(전부 `""`) · `ddaEasySeeds/ddaHardSeeds`(1215행 `""`, L158만 값) | 1216 전부. 보드 3066행 전체에서도 `''`·`field4`는 전부 `""` |
| (b) 같은 키 값 차이 | `useInRandomizer 0→""`, `useTeleportInRandomizer 0→""` | **L158 1건** (보드 전체: useInRandomizer `""` 2건 = L158·L341, useTeleport `""` 8건) |
| (c) 자료형만 차이 | 없음. 서버 응답은 출시 테이블과 같은 자료형(정수·null) | 0 |
| (d) map 차이 | 없음. 서버 map 해시 = sourceMapSha256 | 0 (L1466 포함 — L1466은 에디터 내부 map만 다르다) |
| (e) 기타 | 누락 키·키 순서 차이 없음 | 0 |
- 공통 키만으로 계산한 조건 해시 = 목록 값: **1215/1216** (L158만 불일치 → 현재 서버 행 그대로면 런타임에서 원본으로 폴백한다).

### 8-3. 서버 전용 키 보존 판단
- `idx`·`id`: 기존 업로드(`gboost.py:479-518`)는 둘 다 보내지 않는다. 시드 작업 payload도 제외한다. 레코드 식별용이라 update(new=0)가 유지할 것으로 보지만 **직접 입증하지는 못했다**.
- `field4`: 파싱 결과에 들어 있다(값 `""`). payload에는 읽은 값 그대로 실린다.
- 빈 이름 열 `''`: 파서가 빈 키를 버리므로(`app/clients/gboost.py:60`) payload에 들어가지 않는다(기존 업로드와 같다). 서버가 보내지 않은 키를 유지하는지 지우는지는 근거가 없다 → **입증 불가**.
  - 정황: 08-19 14시 에디터 일괄 업로드로 갱신된 2401행도 지금 `''`=`""`. 다만 원래 값도 `""`였을 수 있어 "유지"와 "기본값으로 초기화"를 구별할 수 없다.
- `etime`: payload에는 읽은 값 그대로 실린다. 서버가 저장할 때 자동으로 갱신하는지는 미확인.

### 8-4. 제안 기준 (승인 전 쓰기 없음)
- 대상 조건(전부 충족):
  1. 목록 candidate이고 에디터 내부 시드가 정답과 같다(내부 map·N 일치).
  2. 출시 행의 모든 키가 서버 행과 **값·자료형까지 dump 동일**(정규화 없음).
  3. 서버 map 해시 = sourceMapSha256.
  4. 서버 전용 키가 정확히 {idx, etime, '', field4, ddaEasySeeds, ddaHardSeeds}이고, `''`·`field4`·시드 두 칸이 모두 `""`.
- 해당 수: **1214** = 1216 − L158(조건 차이 보류) − L1466(에디터 내부 map 불일치로 내부 시드 없음).
- 쓰기 방식: payload = 서버 원시 행 − {id, idx}. 시드 두 칸만 바꾸고 `''`는 기존 업로드처럼 보내지 않는다. 저장 후 원시 단건을 다시 조회해 `idx`·`''`·`field4`·etime·map·나머지 전 키가 동일한지 확인하고, 하나라도 다르면 즉시 중단한다.
- 첫 시험 순서 제안(L158 보류에 따라 변경):
  1. L159 동일 내용 재저장(데이터 변경 없는 roundtrip)으로 표현 보존과 서버 전용 키 유지를 입증한다.
  2. 이어서 L159 시드 채우기.
- 승인이 필요한 결정:
  - ① 4번 조건(서버 전용 키를 위 집합·빈 값으로 한정)을 신뢰 기준으로 채택할지.
  - ② L158 roundtrip 대신 L159 roundtrip으로 바꿀지.
  - ③ 서버가 etime을 자동 갱신하면 그 변화를 허용할 메타로 인정할지.
- L158: `useInRandomizer`/`useTeleportInRandomizer`의 0↔"" 차이로 보류한다(정규화·덮어쓰기 금지). 시드가 현재 서버에 있어도 런타임 조건 해시가 맞지 않는다. 처리하려면 사용자가 관리 화면에서 값을 원복할지, 아니면 검증 목록 기준을 재검토할지 결정해야 한다.

### 8-5. L159 그대로 재저장 1회 시험 (18:28:59 KST, 사용자 승인 범위: L159 1회)
- 경로: `dda_seed_server_apply_20261020.py roundtrip-test --level 159`. 허용 레벨은 {159}뿐이고, `POST_ATTEMPTED` 표식이 있으면 두 번째 POST를 막는다. 오프라인 리허설 PASS(L160 거부, POST 1회, 재실행 차단, new=0, payload = 원시 행 − {id, idx, 빈 이름 열}, 27키).
- 실제 실행: before GET(1631 B, sha `9182f88f…`) → **POST 1회** `level_159=upt`(HTTP 200) → after GET(sha `04c531b5…`).
- 비교(30키, 키 순서 동일): 28키 동일 — map·idx·`''`·field4·시드 두 칸·useInRandomizer 등 포함.
  - **etime**: `"1787117533"` → `"1792488539"` (= POST 시각 18:28:59). 보낸 값과 상관없이 서버가 저장 시각으로 갱신한다.
  - **rewardList**: `null` → `[["null",0,0,0]]` — **데이터 변경**. 읽은 값 null을 JSON null로 보냈더니 서버가 보상 목록 항목 "null"로 해석해 저장했다. 보드 3066행은 전부 null이었다.
- 결론: **차이 있음 — 서버 행을 그대로 다시 보내는 방식으로는 원형이 보존되지 않는다.** 시드만 저장 경로는 차단한다.
- 재시도·롤백·추가 쓰기는 하지 않았다. L159 rewardList는 현재 변경된 상태로 남아 있다(원복은 별도 승인 필요).
- 증거: `backend/data/dda_seeds/server_apply_20261020_1822/roundtrip_level_159/` (before/after 원시 응답, payload, post_response, compare, run.log, SHA256SUMS).

## 9. L159 원복 근거 조사 · 부분 수정 경로 개선 (18:40~ KST, 서버 읽기·쓰기 0)
- 근거 조사: `backend/data/dda_seeds/server_apply_20261020_1822/l159_restore_review/EVIDENCE.md`.
  - (a) 일부 필드만 보낸 update가 보내지 않은 컬럼을 보존한다는 근거: 없음. 게임 에디터와 맵에디터 모두 행 전체를 보낸다.
  - (b) null로 저장되는 값 표현: 08-19 코드상 `"[]"`를 보냈다는 추정만 있고, 원문 payload·로그는 없음.
  - 결과: 이 세션의 원복 쓰기는 차단. 복구는 Codex/사용자가 GameBoost 관리 UI로 할지 판단한다.
- L159 영향(정적, 미실행): `JSONToItemArray`가 `[["null",0,0,0]]`를 `{id:"null", 개수 1}` 보상으로 읽어 클리어 보상에 추가할 수 있다(`DB_Level.cs:1082`, `spGBoostMng.cs:1809-1850`, `GameController.cs:1286-1291`).
- 개선(로컬):
  1. 전체 행 재전송 경로 제거: `seed_only_plan` payload를 두 시드 필드만으로 변경. 스크립트 `roundtrip-test` 허용 레벨을 빈 집합으로, `apply --roundtrip`을 비활성.
  2. 부분 수정 기본 차단: `dda_seed_catalog.PARTIAL_UPDATE_VERIFIED = False`. 라우트 `/dda-seed-export`와 스크립트 `apply`는 이 값이 False이면 POST 없이 `partial_update_unverified`로 차단한다. 미리보기(dry-run)는 허용.
  3. `assert_partial_payload`: 전송 키가 정확히 `{ddaEasySeeds, ddaHardSeeds}`이고 값이 유효 시드 또는 `""`일 때만 통과.
  4. 전송은 update 전용(`update_existing_level`, new=0 1회, `=upt` 확인, new=1 폴백 없음) 경로만 쓴다.
- 테스트(P0 격리 유지): pytest 67 PASS, 외부 시도 0.
  - 신규: 기본 차단 시 POST 0, payload 정확히 두 필드, 추가 키·잘못된 값 거부, 부분 모드에서 경합·조회 실패 차단.
  - 기존 확인 유지: new=0 1회·폴백 없음.
- 남은 승인: 누락 컬럼 보존 근거(관리 UI 단일 셀 수정 관측 등)가 확보된 뒤 `PARTIAL_UPDATE_VERIFIED`를 켤지, 이후 시험 1행을 실행할지. 일괄 저장은 계속 보류.

### 9-1. L159 복구 미완료 (18:45 KST)
- Codex 관리 UI 관측(저장 안 함):
  - 단건 편집은 행 전체 폼이라 체크하지 않은 checkbox 등이 함께 저장될 위험이 있다.
  - 목록 셀 단일 편집은 없다.
  - 일괄수정은 여러 행의 전체 폼이다.
  - API·UI 모두 쓰기 0회.
- 부분 키 저장 선례: 0건. `Real_SaveSingleArray` 사용처는 ExLevelEditor 2곳이며 둘 다 행 전체를 보낸다. 로컬에 서버 구현·공식 문서가 없다.
- L159 재조회(GET 1회, 18:45:39): 시험 직후 저장본과 바이트가 동일하다. 현재 rewardList는 `[["null",0,0,0]]`.
- 필요한 근거, 복구 절차, 운영자 요청안: `backend/data/dda_seeds/server_apply_20261020_1822/l159_restore_review/EVIDENCE.md`.

## 10. 사용자 관리 UI 복구 후 확인 · 기존 업로드 인프라 대조 (18:49~ KST, 서버 쓰기 0, GET 1회)

### 10-1. L159 현재 (GET 18:49:36, `l159_restore_review/l159_after_user_fix_184936.raw.json`, sha `1e1c8754…`)
| 키 | 시험 전(18:28 before) | 현재 |
|---|---|---|
| rewardList | `null` | `[]` (빈 목록 — 원래 null 과는 표현이 다름) |
| useInRandomizer / useTeleportInRandomizer | `0` / `0` | `""` / `""` (관리 UI 저장의 checkbox 부작용, L158 과 같은 패턴) |
| etime | 1787117533 | 1792489730 (18:48:50, UI 저장 시각) |
| map·idx·`''`·field4·시드 두 칸·나머지 | — | 동일 |
- 게임 영향(정적): `[]` → 보상 0개(`JSONToItemArray` count 0)라 'null' 보상 위험은 해소. 단 L159 행 조건이 출시와 달라져(useInRandomizer 등) 런타임 조건 해시 불일치 → L159 도 L158 과 같이 DDA 원본 폴백 대상.

### 10-2. 기존 업로드 흐름 (파일:줄)
1. 프론트: `ProductionExport.tsx:959` `saveToGBoost(board, targetId, uploadJson, ddaConfirm)` → `api/gboost.ts:72` `POST /api/gboost/{board}/{id}` · GridEditor `GBoostUploadModal.tsx:192` → `/api/gboost/upload-local` · GBoostPanel `index.tsx:241` saveToGBoost
2. 라우트: `routes/gboost.py:117` save → `:147` `_convert_to_townpop_format` → `:149` DDA 필드 → (levels 보드 strict 조회·write_guard) → `:162` `client.save_level` · upload-local `:892` → `:988` 변환 → `:1010` save_level
3. 변환기 `gboost.py:402-521` 규칙: 모든 스칼라를 `str()` (누락 시 기본값: backgroundIndex/tileSkin 0, rewardCoin 10, timea 0, …) · **None 이면 `str(None)`="None"** · useInRandomizer/useTeleport truthy→"1"/"0" · difficulty = predicted_clear_rate 있으면 round(×100) 없으면 "-1"(`:503`) · num/sets/layer/useTileCount 재계산(`:512-515`) · visualTileSeed None 이면 키 생략, 있으면 `int()` (`:495-496`) · **rewardList = `json.dumps(get(...,[]))` → 누락 시 `"[]"`, 명시 None 이면 `"null"`(`:517`)** · etime=현재시각(`:518`) · map: layer별 col/row 문자열·tiles 행우선 정렬·num 재계산(`:418-430`)
4. 클라이언트 `clients/gboost.py:100` save_level: `json.dumps({id: row})`(`:135`) → form act=save/gid/bid/new/json(`:142`) · `_exists` 로 new=0/1 결정(`:168-171`) · 응답 첫 줄 `=new`/`=upt` 확인(`:160-162`) · 미확인이면 반대 플래그로 재시도(`:186`, new=1 = 같은 id 새 레코드 위험)

### 10-3. 시드 부분 수정 경로와 차이
| 항목 | 기존 업로드(save_level) | 시드 부분 수정(신규, 기본 차단) |
|---|---|---|
| 직렬화 | 변환기 문자열화·기본값 채움·재계산 | 두 필드 문자열(유효 5시드 또는 "") 그대로 |
| 보내는 키 | 변환기 출력 전체(~24키 + map) — idx·''·field4·시드는 미전송 | `ddaEasySeeds`, `ddaHardSeeds` 2키만(`assert_partial_payload`) |
| new | 존재 확인으로 0/1, 실패 시 반대 플래그 재시도 | new=0 1회, 재시도·new=1 없음(`clients/gboost.py:216-238`) |
| 응답 확인 | `=new` 또는 `=upt` 이면 성공 | `<id>=upt` 만 성공 |
| 경합 검사 | 없음(levels 보드는 write_guard 의 시드 비움/변경 확인만) | 미리보기 digest vs 저장 직전 strict 재조회 |
| 실패 처리 | 행별 실패 카운트, 다음 행 계속 | 대상 차단·사유 기록, 스크립트는 즉시 중단 |
| 실서버 근거 | 전체 행 업로드 다수 성공 | 미전송 컬럼 보존 **미확인** → `PARTIAL_UPDATE_VERIFIED=False` |

### 10-4. 18:29 시험이 기존 계약과 달랐던 지점
- `scripts/dda_seed_server_apply_20261020.py:423` — 조회 원시값(JSON null 포함)을 변환기 없이 그대로 payload 로 사용 → `clients/gboost.py:225` `json.dumps({level_id: row})` 가 rewardList 를 JSON `null` 로 전송 → 서버가 `[["null",0,0,0]]` 로 저장. 기존 업로드는 rewardList 를 항상 문자열 `"[]"` 로 보낸다(누락 시).
- 변환기 엣지케이스(명시 `rewardList: None` → `"null"`, `backgroundIndex/tileSkin: None` → `"None"`): 로컬 데이터 확인 — production 배치 전부·local_levels 2453개에 `rewardList` 키 0건 → 지금까지 발생 안 함(잠재). 프론트도 rewardList 를 다루지 않음.

### 10-5. 부분 키 update 지원 근거 탐색 — **미확인 유지**
- 저장 사용처: 게임 ExLevelEditor 2곳(행 전체)·맵에디터 변환기(거의 전체)·sp_event 0. 부분 키 호출 0건
- 테스트: 실서버 대상 없음(내 mock 테스트만). 로그: 로컬 업로드 로그·응답 기록 없음(이번 run.log 만)
- 과거 기록: 커밋 77933df(2026-06-11) "autoCollectCount 변환 시 누락되어 업로드되지 않던 문제 수정" — 누락 시 서버가 기존 값을 유지했는지 기록 없음
- 관측: L159 시험에서 미전송 idx·'' 유지(레코드 번호·원래 빈 값이라 일반 컬럼 보존 근거로 부족)

### 10-6. 제안 (구현 안 함)
- **(A) 기존 변환기 재사용 전체 행 + 두 시드**: 18:22 snapshot 1216 로컬 예측(`predict_optionA_local*.json`)
  - 서버 행 그대로는 변환기 입력 불가: visualTileSeed `""` → `int('')` 오류 1215, 빈 층 `tiles: []` 오류 1
  - 최소 어댑터(빈 visualTileSeed 생략·빈 층 `{}`) 적용 시 서버값과 달라지는 필드: backgroundIndex `null→"None"` 1216 · tileSkin `null→"None"` 1216 · **rewardList `null→"null"` 1216**(L159 사고와 같은 위험) · difficulty → `"-1"` 1216(predicted 미주입) · etime 1216 · useInRandomizer/useTeleport 1(L158 `""`→`"0"`) · map 1(빈 층) · 미전송 visualTileSeed·field4·''·idx(+시드는 별도 주입 필요)
  - 결론: 변환기는 '에디터 레벨' 용이라 서버 행 원형 보존용으로 부적합. A 를 하려면 서버 행 전용 직렬화(서버 응답 표현 → 기존 업로드와 같은 문자열 표현, null 컬럼별 규칙)를 새로 정의하고 1행 시험 필요 — 그 자체가 컬럼별 '저장 표현' 근거(특히 null/빈값)를 요구.
  - 위험: 컬럼 표현 오판 시 전 행 훼손(1216×). 필요 승인: 직렬화 규칙 확정·1행 시험·일괄. 검증: 1행 저장 후 원시 재조회 전 키 비교.
- **(B) 두 필드 부분 수정(코드 준비 완료, 기본 차단)**
  - 필요 근거: GameBoost real_array save(new=0)가 미전송 컬럼을 유지한다는 서버 구현·공식 문서·운영자 확인 중 하나. 또는 사용자 승인 하에 **피해가 작은 시험 대상**(예: 별도 시험 보드/시험 행)에서 1회 관측.
  - 위험: 근거 없이 실행 시 미전송 컬럼 소실 가능. 필요 승인: 근거 확보 방식 선택 → 1행 시험 → (통과 시) 일괄. 검증: 시험 전후 원시행 전 키 비교(etime 은 서버 자동 갱신 확인됨 — 차이로 기록).
- 공통: L158·L159 는 행 조건이 출시와 달라져(관리 UI checkbox `""`) 현재 상태로는 시드를 넣어도 런타임 폴백 — 별도 결정 필요.

## 11. L159 기존 업로드 인프라 경유 — 1단계 비교 (18:5x KST, 서버 쓰기 0, GET 1회) — 업로드 보류
- 감사: `backend/data/dda_seeds/server_apply_20261020_1822/l159_upload_via_existing/` (STEP1_REPORT.md, payload_local.json, compare_step1.json, server_l159_*.raw.json)
- 입력: 배치 L159 원본 + UI 기본값(rewardCoin 5, autoCollect 0, predicted 0.6145) → 기존 변환기 → + 두 시드. 내부 시드 = catalog 5+5 **일치**.
- 비교(서버 현재 vs payload): 동일 typeImbalance·map(sha f0d9bb… = 목록) / 표현 차이(숫자↔문자열) timea·unlockTile·col·row·rewardCoin 5·randSeed·shuffle*·difficulty 61·teleportRandSeed·autoCollectCount·num·sets·layer·useTileCount 11, rewardList `[]`↔`"[]"` / 의미 차이 backgroundIndex·tileSkin null↔"0", useInRandomizer·useTeleportInRandomizer ""↔"0", 시드 두 칸 ""↔값, etime / 미전송 idx·''·field4·visualTileSeed
- 08-19 업로드 2401행 관측(같은 변환기·같은 전송 형태): 보낸 "0"/"0"/"[]"/미전송/"0"/"0" → 지금 읽기 null/null/null/""/0/0 (2401/2401, 원문 로그는 없음·코드+배치+서버값 대응). ⇒ backgroundIndex·tileSkin·rewardList 차이는 **서버 읽기 표현 차이일 가능성 높음**, checkbox 는 업로드 시 **출시값 0 으로 복원**(현재 "" 는 사용자 UI 저장 부작용).
- 예측: 업로드 후 행 = 출시 원본 행 → 조건 해시 목록 일치(현재 불일치).
- 게이트 미충족(시드·etime 외 의미 차이·미전송 키) → 업로드 안 함. 최소 수정안·필요 승인은 보고 참조.

## 12. L159 기존 업로드 형식 + 두 시드 1건 업로드 (18:58:37 KST, 조율 승인 한정) — 성공
- 경로: `dda_seed_server_apply_20261020.py upload-l159 --level 159`(다른 레벨 거부·POST_ATTEMPTED 로 2회 금지·썸네일 없음). 오프라인 리허설 PASS 후 실행.
- 고정값 확인: 배치 sha `a6aa2af6…` · catalog sha · payload_local.json 바이트 동일(sha `13688a6c…`) · 시드=catalog 5+5 · map sha=목록 · N 11 · rewardCoin 5 · difficulty 61 · randSeed 798801 — 전부 True
- fresh GET = 1단계 원시값(sha `1e1c8754…`, 경합 없음) → **POST 1회 new=0 → `level_159=upt`** → 재조회 sha `cf08a75a…`
- 30키 예측 vs 실측: **전부 일치**(키 순서 동일). etime 1792489730→1792490317(서버 자동 갱신). useInRandomizer/useTeleportInRandomizer `""`→`0`(원본 false 의 기존 직렬화 "0" — 현재 UI 빈값과 차이, 출시값으로 복원). rewardList `[]`→`null`(보낸 `"[]"`, 시험 전 원래 값과 동일). backgroundIndex·tileSkin 보낸 "0" → 읽기 null(이전과 동일). visualTileSeed·field4·''·idx 미전송 → 값 유지(""/""/""/62985).
  - 예측 근거는 추론(08-19 2401행 관측), 결과는 실측 — 이번 1건으로 추론 규칙이 실측 확인됨.
- 조건 해시(출시 행 키) = 검증 목록 **일치**, 행 = 출시 원본 행 + 두 시드, map sha = 목록, 시드 정확 일치.
- 증거: `backend/data/dda_seeds/server_apply_20261020_1822/l159_upload_via_existing/step2/` (before/after 원시, post_response, compare, run.log, SHA256SUMS)
- 범위 외(미실행): 다른 레벨·일괄·썸네일·굽기·게임 적용. 서버 시드 준비 ≠ 게임 동적 레벨 적용.

## 13. 일괄 업로드 준비 (19:00~ KST, 서버 쓰기 0, 보드 GET 1회) — 실행은 승인 대기
### 13-1. 정식 경로
- 프로덕션 배치 에디터 원본 + 업로드 화면 기본 입력(rewardCoin 고정 5, autoCollect 10배수→3 그 외 0, meta 예측 클리어율 — `ProductionExport.tsx:333-345,902-954`) → 기존 `_convert_to_townpop_format` + `ddaEasySeeds/ddaHardSeeds`. 서버 행을 변환기에 넣거나 부분 키만 보내지 않는다.
- `dda_seed_catalog.predict_readback` + `READBACK_RULES`(`dda_readback_rules.v1`, 근거 `server_apply_20261020_1822/l159_upload_via_existing/step2/compare.json`): 정수 문자열→정수, `""`→`""`, backgroundIndex/tileSkin `"0"`→null, rewardList `"[]"`→null, checkbox `"0"`→0, map·시드 그대로, 미전송(visualTileSeed·field4·''·idx) 서버값 유지, etime 서버 갱신. **규칙 외 표현은 unverified → 보류.**
- `export_fields`(일반 업로드)의 출시 행 비교도 같은 규칙으로 예측 읽기값 기준으로 변경 — 실제 값 차이(rewardCoin·difficulty 등)는 그대로 `row_changed` 로 시드 "" 유지. 시드 미적용 경로 payload 는 변경 전 골든과 동일(테스트).
- L159 단건 스크립트(`dda_seed_server_apply_20261020.py upload-l159`)는 L159 하드 한정 그대로 — 일괄은 별도 `scripts/dda_seed_bulk_20261020.py`.

### 13-2. 사전검증 결과 (보드 GET 19:05:44, sha `dfe57eb5…`, 5,655,506 B, 3066행·30키, 열 불일치·중복 0)
| 분류 | 수 | 레벨/사유 |
|---|---|---|
| **준비 완료(ready)** | **1212** | 의미 차이 0 · 조건 해시=목록 · map=목록 · 원시 차이는 규칙 내 22키(`raw_diff_summary.json`) |
| 유지(이미 5+5 일치) | 1 | L159 |
| 별도 승인 | 1 | L158 — 시드 일치, 조건 불일치(useInRandomizer/useTeleportInRandomizer `""`, 관리 UI 저장 부작용) |
| 보류 | 2 | L1466 내부 map 불일치(에디터≠출시) · L1523 예측 클리어율 없음(화면은 RL 측정 → 재현 불가) |
| 비대상 | 314 | 자료 없음 31 · 자동적용 제외 156 · 보류 126 · L322 1 |
- 서버 충돌 시드·비어있지 않은 rewardList·rewardCoin/difficulty/checkbox 차이: ready 안에 0건.

### 13-3. frozen manifest
- `backend/data/dda_seeds/bulk_prepare_20261020_1906/manifest.json` sha256 **`fbd24f9feed26d93a19bcef6609f5a524971329583fd302b135174c024af936d`**
  - 레벨별 payload·payloadSha256·beforeRowSha256(snapshot 행)·expected readback(etime 제외)·backup(`rows/<id>.before.json` 1212개)
  - 고정: snapshot sha·batch sha `a6aa2af6…`·catalog/rows sha·readback 규칙표·UI 입력·코드 sha(core/routes/clients — 실행 시 불일치면 거부)
- 감사: 같은 폴더 summary.json·plan.json·raw_diff_summary.json·run.log·SHA256SUMS. GET 원본: `bulk_snapshot_20261020_1905_get/`(첫 실행이 backup 쓰기 KeyError 로 중단 → 수정 후 같은 snapshot 재사용, 서버 재요청 없음).

### 13-4. 실행기
- `apply --manifest <path> --manifest-sha <sha> [--chunk N≤20, 기본 10] [--sleep ≥0.5, 기본 0.6] [--apply]`
- 기본 dry-run: 네트워크 없음, 다음 청크만 출력(확인: remaining 1212, 첫 청크 L32~39·41·42).
- `--apply`: lock·자원(≤50초마다, swap<500MB/critical 중단) → 행마다 fresh GET = manifest 원본 행(다르면 중단) → posting 기록 → update-only(new=0 1회, `<id>=upt` 만, 생성 fallback·재전송·썸네일 없음) → 재조회 = expected(etime 제외)·키 순서 → 불일치/불확실/조회 실패 즉시 중단. 재개 시 완료 행 skip, 미완료·불확실 행이 있으면 실행 거부(재조회 판정 필요). 자동 rollback 없음(backup 근거로 별도 승인 후 복구).

### 13-5. 검증 (네트워크 차단 mock)
- pytest 100 PASS(가드 2·카탈로그 31·안전 34·일괄 17·pv_canonical 16) + test_api gboost 2 PASS, 외부 시도 0, tsc 0.
- 일괄 17건: 일반 업로드 payload 골든 동일(8케이스) · ready payload = 변환기 출력+두 시드 · 보류(비어있지 않은 rewardList·rewardCoin·difficulty·checkbox 1·시드 충돌·no row·predicted 없음·map) · 별도 승인(checkbox "" 복원·keep 조건 불일치) · manifest 고정·backup · dry-run 네트워크 0·sha 불일치 거부 · 청크/재개/중복 없음 · 경합 시 POST 0 · 불확실 응답 후 재전송 금지 · readback 불일치 중단.

### 13-6. 남은 미검증·승인
- 실서버 쓰기: 0(준비 단계). 1212 실행은 승인 후(첫 청크 10 권장 → 결과 확인 후 다음).
- 미검증: 보드 GET 행 표현과 단건 GET 행 표현의 바이트 동일성(다르면 첫 행에서 경합으로 안전 중단) · 일괄 저장 시 서버 부하/속도 · 08-19 이후 다른 경로 수정 행.
- L158(조건 복원 여부)·L1466·L1523 은 별도 결정. 서버 시드 준비 ≠ 게임 동적 레벨 적용.

## 14. 보류 결정(2026-10-21) 및 재개 조건
- **상태: 준비 완료 / 사용자 일정에 따른 보류.** DDA 시드 일괄 업로드는 현재 준비 중인 다음 업데이트 완료 후 재개한다. 이 업데이트의 선행조건이 아니다(업데이트 이후 별도 후속).
- **금지(재개 확인 전)**: 실제 업로드(1212 일괄·첫 10개), L158 단건, L159 재실행(완료됨, 반복 안 함), 추가 봇 측정, 게임 동적 레벨 실제 적용.
- **보존 대상** (2026-10-21 10:20 확인, 서버 요청 0):
  - manifest `backend/data/dda_seeds/bulk_prepare_20261020_1906/manifest.json` sha256 `fbd24f9feed26d93a19bcef6609f5a524971329583fd302b135174c024af936d` · 원본 backup `rows/` 1212개 · summary/plan/raw_diff_summary/run.log · SHA256SUMS 전 파일 일치
  - 보드 snapshot `backend/data/dda_seeds/bulk_snapshot_20261020_1905_get/server_levels_snapshot.raw.json` (sha `dfe57eb5…`)
  - 감사 폴더 `backend/data/dda_seeds/server_apply_20261020_1822/` (18:22 snapshot·차이 분석·L159 시험/복구/업로드 증거) — L159 업로드 증거 `l159_upload_via_existing/step2/` (compare.json sha `d7caac74…`)
- **과거 manifest 자동 실행 금지.** 실행기(`scripts/dda_seed_bulk_20261020.py apply`)의 기존 안전장치: manifest sha 불일치 거부, core/routes/clients 코드 sha 불일치 거부, 미완료·불확실 행 존재 시 거부, 행별 fresh GET 이 snapshot 행과 다르면 쓰기 전 중단. **manifest 생성 시각(유효기간) 검사는 없음** → 코드 변경 없이 운영 규칙으로 **재개 시 새 manifest 필수**.
- **재개 절차**: ① 사용자 재개 확인 → ② 읽기 전용 비교: 최신 서버 보드 GET 1회, 배치 원본 map·배치 digest(`a6aa2af6…` 대비), catalog/rows sha, 코드 sha → ③ `prepare` 로 목록 재검증(ready/유지/보류/별도 승인 재분류) → ④ 새 manifest·sha 보고 → ⑤ 첫 10개 실행 승인 단계로 복귀(이후 청크별 확인).
- 별도 결정 남음: L158(체크박스 `""`), L1466(에디터 map 불일치), L1523(예측 클리어율 없음).
