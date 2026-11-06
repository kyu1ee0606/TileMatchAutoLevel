# 수정 설계서 — "DDA 시드만 내보내기" 실사용화 (2026-11-03)

> 성격: 읽기 전용 조사 기반 설계. 코드 수정·서버 쓰기·재시작 없음. 아래 수치/줄번호는 2026-11-03 작업 트리 기준 직접 읽어 확인한 것.
> "추정" 표시는 관측이 아닌 추론이다.

---

## 0. 결론 요약

1. 지금 경로는 **배치(탭)의 시드를 전혀 쓰지 않는다** — 옛 v1 목록(5개 토큰) 값만 보낼 수 있고(`_seed_values`), 10-20 출시 스냅샷과 행이 같아야 통과한다. 11-02 전체 업로드 뒤라 사실상 전 행 차단(추정, 미실측)이고, 통과해도 `PARTIAL_UPDATE_VERIFIED=False` 에서 막힌다.
2. 고칠 방향: `/dda-seed-export` 를 **v2로 다시 짠다**. 판정은 일반 업로드와 같은 함수(`prepare_export_level_json` → `export_fields` → `evidence_gate` → `write_guard`)를 쓴다. 전송은 `update_existing_level` 로 **바뀌는 시드 열만** 보낸다.
3. 옛 사본 사고 방지: **백엔드가 배치 파일(`backend/data/production/<batch>.json`)에서 직접 level_json 을 읽는다**(추천). 탭은 행 id 와 원본 레벨 번호만 보낸다. 탭이 아는 버전과 파일 버전이 다르거나 탭에 아직 안 올린 변경이 있으면 차단한다.
4. 서버 조회: 미리보기 때 보드 전체를 1회 GET(`load_board_rows`, 약 6 MB) 한다. 업로드 때는 청크마다 보드를 1회 다시 GET 해 digest 를 비교한다. 행별 GET 2,560회는 없앤다.
5. 부분 수정 근거: **10-28 시드 전송 2,262행이 같은 함수(update_existing_level)로 1~4열 부분 payload 를 보냈고, 행마다 전체 행 재조회 결과 = 직전 행+payload 였다(ok 2,262/2,262, 불일치 0)**. 그래도 해제는 "시험 1행 → 재조회 대조 → 사용자 승인" 순서로 한다.

---

## 1. 현재 막힌 지점 전체 목록

### 1-1 백엔드 — `backend/app/core/dda_seed_catalog.py`
| # | 위치 | 막힘 |
|---|---|---|
| B1 | :22 `SEED_FIELDS=("ddaEasySeeds","ddaHardSeeds")` | 시드만 경로가 2열만 다룬다. ddaEasy2Seeds/ddaHard2Seeds 는 보낼 수 없다. |
| B2 | :481-484 `seed_only_plan` `_LEVEL_ID` 검사 | `level_N` 만 통과하고 `infinity_N` 은 `not_level_row` 로 차단된다. |
| B3 | :487-494 | 행 판정이 `load_source_rows()`(10-20 출시 스냅샷)와 `load_catalog()`(v1 목록)에 묶여 있다. 목록에 없는 레벨은 `no_snapshot` 이다. |
| B4 | :501 | 서버 행에 2열이 있어야 한다(4열 확인 없음). |
| B5 | :504-507 `row_diff(server_row, snap)` | 시드·map·id·idx·etime 을 뺀 서버 행이 **10-20 스냅샷과 같아야** 한다. 11-02 업로드로 useTileCount 103행·autoCollect·difficulty 등이 바뀌어 대부분 `server_row_differs` 로 차단된다(추정 — 오프라인 대조 미실시). |
| B6 | :508-514 | 서버 map 해시가 **v1 목록의 sourceMapSha256** 과 같아야 한다. 11-02 map 보정 150행과 무한 relabel 1,030행은 불일치다. |
| B7 | :515, :166-177 `_seed_values` | **보낼 값 = v1 목록 값(5개 토큰)뿐**이다. 탭/배치의 현행 3개 시드는 쓰지 않는다. 목록 값과 다르면 `""`(conflict/missing)이 된다. 이것이 핵심 결함이다. |
| B8 | :518-522 | payload 가 2열 고정이고 change 판정도 2열 묶음이다(열 단위 아님). `""` 이면 `clear` 로 판정한다 — 일반 경로(`export_fields`)는 `""` 를 보내지 않는데 이 경로만 비우는 경로를 가진다. |
| B9 | :547 `PARTIAL_UPDATE_VERIFIED=False` | 모든 검사를 통과해도 실제 POST 0이다(`partial_update_unverified`). 주석 :545 "근거 없음"은 10-28 관측 이전 기준이라 낡았다(§2-4). |
| B10 | :550-556 `assert_partial_payload` | 키가 정확히 2열이어야 하고 값은 `is_valid_seed_str`(**5개 토큰**, :81-86)여야 한다. 현행 3개 값은 예외로 거부된다. |

### 1-2 백엔드 — `backend/app/api/routes/gboost.py` `/dda-seed-export` (:1267-1337)
| # | 위치 | 막힘 |
|---|---|---|
| R1 | :1285-1289 | 대상마다 `client.load_level(strict)` 단건 GET 을 한다. dry-run 1회 + 업로드 1회로 2,560행이면 GET 5,120회다. |
| R2 | :1256 `level_json` 을 요청 본문으로 받음 | 탭(IndexedDB) 사본을 그대로 믿는다 → 옛 사본 사고 경로. |
| R3 | :1294 | B3~B8 의 `seed_only_plan` 을 호출한다. |
| R4 | :1315-1318 | 근거 검사는 `payload` 2열만 본다. 일반 경로의 `evidence_gate`(열 단위로 빼기) 와 다르게 **행 전체를 차단**한다. |
| R5 | :1324-1327 | B9 로 전부 차단된다. |
| R6 | :1302 | digest 는 단건 GET 응답 기준이다. 보드 GET 과 단건 GET 은 `rewardList` 표기(null vs [])가 다를 수 있다(근거: `sp_meowsgarden/tools/dda_seed_random_101_inf.py:437-445` "read-path gap"). → 비교는 같은 읽기 경로끼리만 해야 한다. |
| R7 | 응답 1회 | 전 대상을 한 HTTP 요청으로 처리한다. 프론트 timeout 600 s(`api/gboost.ts:217`)라 대량이면 끊길 위험이 있다. |

### 1-3 프론트
| # | 위치 | 막힘 |
|---|---|---|
| F1 | `ProductionExport.tsx:1763` `enabled={gboostHealthy && gboostLevelPrefix === 'level_'}` | 무한 모드가 반영되지 않는다. |
| F2 | `ProductionExport.tsx:1764-1766` getTargets | `getExportableLevels()`(:678-692, IndexedDB `getProductionLevelsByBatch`)를 쓰고, id 를 항상 `level_${n}` 으로 만든다. `buildUploadTargets`(:507-530, 무한 번호 규칙)를 쓰지 않는다. |
| F3 | `storage/productionServerSync.ts:195-223` pullAllToLocal | 탭/앱 마운트 때만 호출한다(`ProductionDashboard/index.tsx:1046` syncBidirectional). `:211` 로컬 `__server_version >= 서버 version` 이면 건너뛴다. 버전을 올리지 않고 파일을 바꾸거나 마운트 뒤에 바뀌면 탭 사본이 옛것으로 남는다. 시드만 화면은 이를 감지하지 못한다. |
| F4 | `DdaSeedOnlyExport.tsx:52,117` | 2열 전제의 문구와 표시다. `REASON`(:15-29)에 `partial_update_unverified` 가 없다. |
| F5 | `DdaSeedOnlyExport.tsx:134-137` | 집계가 행 단위 change 1개다. 열 단위(채움/변경/같음/유지/근거없음)가 아니다. |
| F6 | `api/gboost.ts:199-219` | 타입이 2열이다(`server.ddaEasySeeds/ddaHardSeeds`). |
| F7 | 진행률 없음 | 단일 요청이라 진행 표시가 없다. |

---

## 2. 수정안

### 2-1 4칸 + 무한 행 지원
- 판정은 **`export_fields(board, target_id, level_json_relabeled, townpop)`(catalog :289-347)를 그대로 쓴다**.
  - `level_N`: level_json 루트 4열 중 게임 형식 값만 쓴다. 옛 v1 목록 5개 값은 `LEGACY_CATALOG_EXPORT=False` 라 생략한다(일반 경로와 같음).
  - `infinity_N`: `level_json.ddaInfinitySeeds[infinity_N]` 만 쓴다(없으면 4열 생략). 현재 LIVE 배치(`batch_1792056041502_cn5e4ny66`, version 5, 1,530레벨)에서 `ddaInfinitySeeds` 를 가진 레벨은 922개이고, 루트 4열 보유 수는 Easy2 1,513 · Easy 1,514 · Hard 1,513 · Hard2 1,468, `ddaSeedVerdicts` 는 1,362다(파일 직접 읽음).
- **relabel 필요: 예.** map 은 보내지 않지만 ① 근거 `binding.mapSha256` 가 relabel 된 map 기준이고(catalog :217-224) ② 서버 map 대조(아래)도 relabel 본 기준이어야 한다. `_inf_relabel.prepare_export_level_json(target_id, lj, infinity_relabel)` 를 판정 전에 1회 호출한다(기존 :1287 과 같음).
- 원본 번호 규칙: `infinity_N` ↔ 원본 `infinitySourceStart-1+N`(기본 500+N). 프론트 `buildUploadTargets` 결과(`targetId`, `sourceLevel`)를 그대로 넘긴다.
- 열 단위 결과 per row:
  - `sent{열:값}`: 서버와 다르고 근거 ok 인 값이다. 실제로 보낸다.
  - `same`: 서버와 같다. 보내지 않는다(최소 payload).
  - `kept`: export_fields 가 생략한 열이다(사유 fieldReasons).
  - `unverified{열:사유}`: `evidence_gate` 가 뺀 열이다.
  - 분류: `fill`(서버 빈 값) / `change`(서버 다른 값, confirm 필요).
  - `""` 전송 경로는 없다(clear 불가). `write_guard` 는 방어용으로 그대로 호출한다.

### 2-2 신뢰 조건 (스냅샷·v1 목록 의존 제거, 대신 "배치 ↔ 서버" 직접 대조)
행마다 하나라도 실패하면 그 행만 blocked 이고 기본값 추정은 없다.
1. 서버 행 존재·dict (`no_server_row`/`server_row_invalid`) — 시드만 경로는 행을 만들지 않는다.
2. 보드 `__keys` 에 보낼 열이 있어야 한다 (`no_seed_column`) — 새 컬럼 생성 방지.
3. **서버 map 해시 = 배치 level_json(relabel 후) 변환 map 해시**, 그리고 서버 `useTileCount` = 변환 값 (`server_map_differs`). 근거가 배치 map 에 묶여 있으므로 서버 map 이 다르면 그 시드는 서버 맵에 대한 근거가 아니다. 주의: 11-02 NOTE 에서 무한 9행이 "빈 층 [] 표기만 다름"으로 보고됐다 → 이 9행은 정규화 없이 차단될 수 있다. 정규화를 넣을지는 사용자 결정 Q3이다.
4. 근거 ok (`evidence_gate`) — 근거 없는 열만 빼고 행은 진행한다(일반 경로와 같음; 기존 R4 의 행 차단보다 관대하지만 보내는 값은 전부 근거 ok).
5. 보낼 열이 0이면 `unchanged`(POST 없음).

`row_diff`/`load_source_rows`/`_seed_values` 는 v2 경로에서 쓰지 않는다. 기존 함수는 다른 테스트·도구가 쓰므로 삭제하지 않는다.

### 2-3 서버 조회: 보드 1회
- 미리보기: `client.load_board_rows("levels")`(clients/gboost.py:238-262, strict, 90 s timeout)를 1회 호출한다. 행별 `serverDigest = row_digest(행 − etime)` 를 쓰는데, **보드 GET 기준**이다.
- 업로드: 프론트가 대상을 청크(제안 250행)로 나눠 보낸다. 백엔드는 **청크마다 보드를 1회 다시 GET** 해 행 digest 가 미리보기와 다르면 `server_changed_since_preview` 로 차단한다. 2,560행 기준 보드 GET 은 약 11회(6 MB × 11 ≈ 66 MB)다. 단건 GET 과 섞지 않는다(R6 표기 차이).
- 대안: 행마다 직전 단건 GET(10-28 스크립트 방식)은 요청이 2배이고 rewardList 표기 정규화가 필요하다 → 기본으로 쓰지 않는다.

### 2-4 옛 화면 사본 방지 — **추천: 백엔드가 배치 파일에서 직접 읽기**
| 안 | 내용 | 평가 |
|---|---|---|
| A. 버전 비교만 | 탭 `getKnownVersion(batchId) ?? batch.__server_version` 을 보내고 파일 `version` 과 비교한다 | 버전을 안 올린 파일 수정(스크립트·수동 편집)은 못 잡는다. level_json 은 여전히 탭이 보낸다. |
| **B. 파일 직접 읽기 (추천)** | 요청 = `{batch_id, expected_batch_version, targets:[{target_id, source_level}], infinity_relabel, ...}`. 백엔드가 `production_store._path(batch_id)` 파일을 열어 `version`·파일 sha256 을 기록하고 `level_number==source_level` 의 level_json 을 쓴다 | 보내는 값 = 서버에 저장된 배치(정본)라 탭 사본과 무관하다. |

B 의 보조 장치:
- 파일 version ≠ `expected_batch_version` 이면 409 `batch_version_mismatch` 를 내고 화면에 "탭 새로고침(배치 당기기) 후 다시"를 띄운다. 탭과 파일 중 어느 쪽이 옛것이든 보는 화면과 보내는 값이 어긋나지 않게 한다.
- 프론트는 `getDirtyCount(batchId) > 0`(productionServerSync.ts:78, 아직 서버에 안 올린 편집)이면 미리보기 버튼을 막는다 — 파일에 없는 편집이 있다는 뜻이다.
- 미리보기 응답에 `batchVersion`, `batchFileSha256` 을 넣는다. 업로드 청크마다 둘 다 다시 대조하고, 다르면 전체 중단한다.
- 같은 배치 파일 + 같은 export_fields 라 일반 업로드 미리보기(ddaWarn)와 숫자가 같아야 한다 → 테스트 항목.

### 2-5 PARTIAL_UPDATE_VERIFIED 해제 조건
기존 관측 근거(직접 확인):
- `sp_meowsgarden/tools/out/dda_seed_random_20261028/upload/` — manifest 2,262행(level 1,304 · infinity 958). payload 열 조합은 4열 1,684 · Easy2+Hard2 490 · Easy2+Easy+Hard 85 · Easy2 단독 2 · Easy2+Easy 1이다. `results.jsonl` 은 posting 2,262 · ok 2,262 · bad 0이다. 행마다 `update_existing_level`(new=0, `=upt` 확인) 후 단건 재조회한 전체 행(etime 제외)이 `직전 행 + payload` 와 같았다(`dda_seed_random_101_inf.py:449-469`). 클라이언트는 `app.clients.gboost.GBoostClient`(`backend/scripts/dda_seed_bulk_20261020.py:37`)로 시드만 경로와 같은 함수다. 소요는 12:29:08 → 13:25:38 (56분)이다.
- catalog :571 READBACK_RULES "unsent 키 → 서버 기존값 유지(L159 실측)".
- 11-02 전체 업로드 검증(`upload_20261102/NOTE.md`): "미전송 열 변경 0" — 다만 이건 전체 행 save_level 경로이고 부분 payload 관측이 아니다.

→ 부분 수정 보존은 **관측됨**(10-28). 그래도 해제는 아래 단계로 한다:
1. 코드는 `PARTIAL_UPDATE_VERIFIED=False` 그대로 배포한다. 새 요청 옵션 `trial=true` 는 **대상 정확히 1행**일 때만 게이트를 우회한다.
2. 시험 1행 흐름(백엔드 내부): 보드 GET → 그 행 digest = 미리보기 digest → POST → 보드 GET(같은 경로) → `after(etime 제외) == before(etime 제외) + payload`, 그리고 **다른 모든 행 digest 불변**이면 통과다. 결과를 `backend/data/dda_seeds/partial_update_trial_<시각>.json` 에 저장한다(행 id, payload, before/after sha, 보드 raw sha).
3. 통과 기록 파일이 있고 사용자가 승인하면 전체 전송을 허용한다. 방식은 Q1 결정이다: (a) 상수를 True 로 바꾸는 1줄 수정 + 재시작, 또는 (b) 라우트가 통과 기록 파일 존재를 매 호출 확인(재시작 불필요).
4. 시험 행 후보: 근거 ok 이고 `change` 가 아닌 `fill` 1열짜리 정식 행. 없으면 `change` 1열 행에 confirm 을 붙인다. **실서버 시험은 사용자 승인 후**.

### 2-6 기존 안전장치 유지
- 근거 검사: `evidence_gate` + `SEED_EVIDENCE_REQUIRED=True`(catalog :213) 그대로.
- digest: 보드 GET 기준 행 digest + 배치 version/파일 sha (2-3, 2-4).
- confirm: 열 중 `change` 가 하나라도 있으면 요청 `confirm=true` 가 필요하다(없으면 그 행 `needs_dda_confirm`). 미리보기는 1회용이다(기존 프론트 :84 유지).
- 장부: 프론트가 `openLedgerSession`(source `dda_seed_export`)을 열고 청크마다 `ledger_session` 을 넘긴다. 끝에 `finalizeLedgerSession` 을 호출하는데, `readback_session` 은 행 수가 많으면 보드 1회 GET(ledger :373-402)이다. 행 기록은 `build_row_record(payload=보낸 열만, server_before=보드 행, relabel)` 이다.
- `assert_partial_payload` 를 4열용으로 바꾼다: 키 ⊆ EXPORT_SEED_FIELDS, 1개 이상, 값마다 `is_runtime_seed_str(열, 값)`(3개, ±1 열은 5개 허용), `""` 금지.
- `update_existing_level` 만 쓴다(new=1 폴백 없음, 썸네일 없음).
- 첫 오류에서 멈춤: POST 실패/미확인 1건이 나오면 나머지 청크를 중단한다(10-28 스크립트와 같은 정책).

### 2-7 동시 전송 여부와 속도 예상
- 측정치: 일반 내보내기 2,560행 약 18분 ≈ 0.42 s/행. 행당 요청은 exists GET + strict GET + save POST + 썸네일 생성·POST 이다. 10-28 스크립트는 2,262행 56분인데 sleep 0.6 s×2 + GET 2 + POST 1 이다.
- v2 요청 수: 보드 GET (1 + 청크 수) + **바뀌는 행만 POST**. "같음" 행은 POST 가 없다.
- 예상(추정): POST 1건 0.1~0.3 s → 순차로 2,560행 전부 바뀌어도 약 4~13분, 보드 GET 11회 추가 약 1~2분이다. 실제로는 바뀌는 행만이라 더 짧다.
- **기본은 순차(동시 1)**를 추천한다. 라이브 게임 서버 부하가 미확인이고, 첫 오류에서 멈추기가 쉽다. 옵션 동시 2~4(Semaphore)는 시험 후 별도 승인을 받는다. 4면 약 1~4분(추정)이다.
- 청크 요청마다 응답을 받으므로 진행률을 표시할 수 있고, 요청당 시간은 timeout(600 s)보다 훨씬 짧다.

---

## 3. 수정할 파일 목록

### 백엔드 (4 + 테스트 2)
| 파일 | 변경 요지 |
|---|---|
| `backend/app/core/dda_seed_catalog.py` | `seed_only_plan_v2(target_id, level_json_relabeled, townpop, server_row, board_keys)` 를 추가한다: 2-2 조건 + `export_fields` + `evidence_gate` + 열 분류 → `{sent, same, kept, unverified, change[], fill[], serverDigest, blocked, reason}`. `assert_partial_payload` 4열·3개 형식 판으로 바꾼다(옛 함수는 이름 바꿔 보존하거나 v1 테스트용으로 유지). 시험 기록 파일 확인 함수 `partial_update_allowed()`(Q1 b 일 때)를 둔다. :545 주석을 10-28 근거로 갱신한다. |
| `backend/app/api/routes/gboost.py` | `/dda-seed-export` 요청 모델을 `{batch_id, expected_batch_version, expected_batch_sha?, targets:[{target_id, source_level, expected_server_digest?}], dry_run, confirm, trial, infinity_relabel}` 로 바꾼다. 흐름: 배치 파일 로드·버전 대조 → 보드 1회 GET → 행 판정 → (업로드) 게이트·trial → `update_existing_level` 순차 → 장부. 단건 `load_level` 루프(R1)를 제거한다. |
| `backend/app/api/routes/production_store.py` | 읽기 헬퍼 `read_batch_file(batch_id) -> (doc, version, sha256)` 를 추가한다(`_path`, :42 재사용, 쓰기 없음). |
| `backend/app/clients/gboost.py` | 변경 없음 예상(`load_board_rows` :238 이 `keys`·`rows`·`raw_sha256` 을 이미 반환). |
| `backend/tests/test_dda_seed_export_safety.py` | 스냅샷 기반 `test_seed_only_*`(:134-233, :323, :378-429)를 v2 기준으로 고친다. 기본 차단 테스트(:388-409)는 유지한다. |
| `backend/tests/test_dda_seed_only_v2.py` (신규) | §4 항목. |
| `backend/tests/test_dda_seed_ledger.py` | :294-304 seed_export 기록 테스트를 새 요청 형식에 맞춘다. |

### 프론트 (3)
| 파일 | 변경 요지 |
|---|---|
| `frontend/src/api/gboost.ts` | `DdaSeedExportResult` 를 4열·열 단위 필드로 바꾸고 요청 타입을 `batch_id/expected_batch_version/targets{target_id,source_level}` 로 바꾼다. `batchVersion/batchFileSha256` 응답을 추가한다. |
| `frontend/src/components/ProductionDashboard/DdaSeedOnlyExport.tsx` | props 를 `batchId`, `getTargets(): {target_id, source_level}[]`, `infinityRelabel`, `tabBatchVersion`, `dirtyCount` 로 바꾼다. 화면: 탭 버전 vs 파일 버전 표시, 불일치·미전송 편집 시 차단, 열별 집계(채움/변경/같음/유지/근거없음/차단 사유), 청크 순차 업로드·진행률, 장부 세션 열기/마감, `시험 1행` 버튼(승인 문구), `REASON` 보강. |
| `frontend/src/components/ProductionDashboard/ProductionExport.tsx` | :1761-1767 마운트를 바꾼다: `getTargets` = `buildUploadTargets(await getExportableLevels())` → `{targetId, sourceLevel}`. `enabled` = 건강 + 업로드 단계 아님 + `gboostLevelPrefix==='level_'` + (무한 켬이면 `infinityPrefix==='infinity_'`). `getKnownVersion`/`getDirtyCount` 를 전달한다. |

`productionServerSync.ts` 는 변경 없음(기존 export 함수만 사용).

---

## 4. 테스트 계획

### pytest (네트워크 없음, 가짜 클라이언트) — 신규 `test_dda_seed_only_v2.py`
1. 4열 각각: fill/change/same/kept/unverified 분류와 payload = sent 열만.
2. 3개 형식 값 통과, 5개 v1 목록 값은 생략(LEGACY False), `""` 는 절대 payload 에 없음.
3. infinity_N: `ddaInfinitySeeds[id]` 만 사용, 없으면 POST 0. relabel on 이면 binding 이 relabel map 기준이라 통과하고, relabel off 이면 binding_mismatch 로 열이 빠지는지.
4. 서버 map/useTileCount ≠ 배치 → `server_map_differs`, POST 0.
5. 서버 `__keys` 에 열 없음 → `no_seed_column`.
6. 배치 version 불일치 → 409. 미리보기 후 배치 파일 sha 변경 → 업로드 중단.
7. 보드 GET 실패 → 전체 차단(fail-closed). 미리보기 후 행 변경 → `server_changed_since_preview`.
8. `change` 열 + confirm 없음 → `needs_dda_confirm`.
9. `PARTIAL_UPDATE_VERIFIED=False` → trial 아니면 POST 0. trial + 2행 이상이면 거부. trial 1행이면 POST 1 + 재조회 대조 기록 파일 생성. 재조회 불일치면 실패 기록.
10. 게이트 열림 + 정상: POST 횟수 = sent 가 있는 행 수, 보드 GET 횟수 = 1 + 청크 수, 단건 `load_level` 호출 0.
11. 첫 POST 실패 → 이후 POST 0.
12. 장부: 보낸 열만 기록, dry_run 은 기록 없음(기존 :294 유지).
13. 일반 경로 일치: 같은 배치·서버 행에 대해 v2 sent/unverified 열 집합 = `export-preview`(`dda_seeds.py:68-81`) + `evidence_gate` 결과.
14. `assert_partial_payload` v2: 빈 dict·미지 키·`""`·형식 오류를 거부한다.

실행: `cd backend && python -m pytest tests/test_dda_seed_only_v2.py tests/test_dda_seed_export_safety.py tests/test_dda_seed_ledger.py tests/test_dda_seed_catalog.py tests/test_dda_seed_evidence.py -q`

### 프론트
- `cd frontend && npx tsc --noEmit`.
- 화면 미리보기 숫자 확인(dry_run 만, 쓰기 없음): ① 일반 업로드 '충돌 검사' ddaWarn 의 fill/change/same/unverified 와 v2 미리보기 열 집계가 같은 범위에서 일치하는지 ② 탭 버전 표시 = `/api/production/batches` version ③ 무한 모드 off/append/only 별 대상 수 = 화면의 "업로드될 무한 사본" 수.
  - 주의: 미리보기도 보드 GET 1회(약 6 MB)를 한다 → **라이브 업로드가 끝난 뒤** 실행한다.
- **실서버 시험 1행(trial)은 사용자 승인 후**. 그 뒤 전체 전송도 별도 승인을 받는다.

---

## 5. 위험과 대안

### 5-1 일반 업로드 재사용 vs 전용 경로
| | 일반 업로드에 "시드만" 플래그 | **전용 경로 v2 (추천)** |
|---|---|---|
| 전송 | `save_level`(exists GET + new=0/new=1 폴백) → 행 생성 위험, 썸네일 | `update_existing_level` 만(생성 없음) |
| payload | 전체 행 변환본에서 시드 외 키를 빼야 함 → 분기 복잡 | 처음부터 시드 열만 |
| 서버 조회 | 행별 strict GET 구조 | 보드 1회 |
| 판정 함수 | 같음 | 같은 함수 재사용(export_fields/evidence_gate/write_guard/relabel) |
| 화면 | ProductionExport 업로드 루프(:1007-1046) 수정 → 18분 전체 업로드 경로 회귀 위험 | 별도 컴포넌트, 기존 업로드 경로 무변경 |

### 5-2 위험
1. **서버 map 표기 차이로 과잉 차단**(무한 9행 빈 층 [] 표기 등) → fail-closed 라 안전하지만 일부 행이 안 간다. 대안은 비교 전 빈 층 정규화(Q3).
2. **배치 파일 = 정본 가정**: 탭에서 편집 후 아직 push 안 된 변경이 있으면 파일에 없다 → dirtyCount 차단으로 막는다. 다른 브라우저 탭이 동시에 push 하면 version 이 바뀌므로 청크마다 sha 대조로 중단한다.
3. 보드 GET 6 MB × 청크 수의 부하 → 청크 크기를 키우면 줄어든다(500행이면 6회).
4. 동시 전송 시 첫 오류 정지가 늦어진다 → 기본 순차.
5. 보드 GET 과 단건 GET 표기 차이(rewardList) → digest 는 보드 GET 끼리만 비교한다.
6. 장부 finalize 재조회가 실패해도 업로드 결과에는 영향이 없다(기존 동작). 화면에 "재조회 실패"를 표시한다.
7. 백엔드 재시작이 필요하다(Python 라우트 변경) → 진행 중인 라이브 업로드가 끝난 뒤에만 한다.

### 5-3 예상 작업량 (추정)
- 백엔드 catalog + 라우트 + 배치 읽기 헬퍼: 3~4 h
- pytest 신규 14항목 + 기존 테스트 수정: 2~3 h
- 프론트 3파일 + tsc + 화면 미리보기 대조: 2~3 h
- 합계 **약 1일(7~10 h)**, 실서버 시험 1행·전체 전송 시간 제외.

---

## 6. 사용자 결정 필요
- **Q1** 시험 1행 통과 후 부분 수정 허용 방식: (a) 상수 True 수정 + 백엔드 재시작 / (b) 통과 기록 파일로 자동 허용(재시작 없음).
- **Q2** 동시 전송: 순차만(추천) vs 시험 후 동시 2~4 허용.
- **Q3** 서버 map 대조 시 빈 층 [] 등 표기 차이를 정규화할지(안 하면 그 행은 차단).
- **Q4** 옛 v1 시드만 경로(스냅샷·목록 기반) 코드를 남길지 제거할지(남기면 v2와 이름 분리).
- **Q5** 시험 1행 대상 행과 실행 시점(라이브 업로드 종료 후).

---

## 7. 구현 결과 (2026-11-03, worktree `~/TileMatchAutoLevel_wt_seedfix` · 브랜치 `seedfix-20261103` · 미커밋)

사용자 결정: Q1 (b) 통과 기록 파일 자동 허용(대상 행·대조 결과·코드 해시에 묶음) · Q2 순차만 · Q3 빈 층 정규화 · Q4 옛 경로 제거(공용 함수는 보존/이동) · Q5 시험 1행은 나중.
기준선: worktree 인덱스 = 본 폴더 미커밋 상태 그대로 복사(64파일). 반영용 패치 `~/TileMatchAutoLevel_wt_seedfix/SEEDFIX_20261103.patch`(sha256 9022038b…, 12파일 +1153/−379) — 본 폴더 현재 파일에 `git apply --check` 통과.

### 7-1 구현 내용
| 파일 | 변경 |
|---|---|
| `backend/app/core/dda_seed_catalog.py` | `seed_only_plan_v2`(칸 단위 send/same/kept/unverified/blocked), `normalize_map`/`map_compare_sha`(빈 층 `tiles: []`→`{}`, 키 정렬 비교), `assert_seed_payload`(4열 부분집합·게임 형식·`""` 금지), `judge_partial_trial`, `write_partial_trial_record`, `partial_update_allowed(code_hash)`, `code_fingerprint`. `PARTIAL_UPDATE_VERIFIED=False` 유지. 옛 `seed_only_plan`·v1 `assert_partial_payload` 는 이동. `row_diff`·`row_digest`·`_server_map_sha`·`SERVER_MANAGED_KEYS` 는 그대로(장부 :156·10-20 스크립트 사용). |
| `backend/app/core/dda_seed_only_v1_legacy.py` (신규) | 옛 v1 판정 코드 원문 보존(10-20 스크립트 전용). |
| `backend/scripts/dda_seed_server_apply_20261020.py` | v1 함수 2곳을 legacy 모듈로 연결(동작 무변경). |
| `backend/app/api/routes/gboost.py` | `/dda-seed-export` v2: 요청 `{batch_id, expected_batch_version, expected_batch_sha256, targets[{target_id, source_level, expected_server_digest}], dry_run, confirm, trial, infinity_relabel, client_unsynced_edits}`. 배치 파일 직접 읽기 → 버전 불일치 409 `batch_version_mismatch` / 미동기 편집 409 `unsynced_local_edits` / 업로드 시 파일 sha 불일치 409 `batch_changed_since_preview` → `load_board_rows` 요청당 1회(행별 GET 없음) → 행 판정 → digest·confirm·write_guard·게이트 → `update_existing_level` 순차, 첫 실패 후 `stopped_after_failure`. trial: 대상 1개만(아니면 400), 전송 후 보드 재조회 대조 → 기록 파일(`backend/data/dda_seeds/partial_update_trials/`). 응답에 `summary.cells`(칸 단위), `partialUpdate{allowed, by, codeHash}`. **추가 1**: 단일 저장 라우트와 `upload-local` 에서 서버 기존 map = 보낼 map(정규화)이면 썸네일 생성·업로드 생략, 메시지 `(thumbnail skipped: map same)`. 다르거나 비교 불가(새 행·파싱 불가)면 기존대로. |
| `backend/app/api/routes/production_store.py` | `read_batch_file()` 읽기 전용 헬퍼. |
| `backend/app/core/solver.py` | **추가 2**: `solve_level_task` 가 `args.time_budget_s` 를 넘김(없음/None → DEFAULT 5.0). 확인 간격 256 유지(아래 7-3). |
| 프론트 `api/gboost.ts` · `DdaSeedOnlyExport.tsx` · `ProductionExport.tsx` | 4열 칸 단위 타입·표시, 대상 = `buildUploadTargets`(무한 포함), 탭 버전(`getKnownVersion` → `__server_version`)·미동기 편집(`getDirtyCount`) 전달·차단, 250행 청크 순차·진행률·첫 실패 정지, 장부 세션 열기/마감, `시험 1행 전송`(승인 체크) 버튼, 통과 기록 없으면 전체 업로드 버튼 비활성. |

### 7-2 검증 (실행한 것)
- pytest 전체(worktree, 본 폴더 venv): **4,719 통과 · 7 실패 · 45 건너뜀**. 실패 7개는 수정 전 기준선 사본(`/tmp/seedfix_base`)에서도 같은 7개(4,709 통과)라 기존 문제다: bot_behavior_candidates 2, bot_play_summary 1, dda_seed_bulk_v2 old_manifest 2, generator 2. `test_generate_with_custom_tile_types` 는 기준선·수정본 모두 6회 중 2~3회 실패하는 흔들리는 테스트다.
- 신규 `tests/test_dda_seed_only_v2.py` 24개 통과: 4칸 시드, 변경 confirm, v1 5개 값 생략, 무한 relabel(통과/불일치 2종), 옛 버전 409·미리보기 후 파일 변경 409, 미동기 편집 409, 요청 level_json 무시, 보드 1회 조회(행별 0), 보드 조회 실패 502, 행 가드 4종 + 미리보기 후 행 변경, 첫 실패 정지, 빈 층 정규화, payload 가드, 게이트 기본 차단, 시험 1행 → 기록 → 게이트 열림 · 다른 코드 해시 무효, 재조회 불일치 시험은 게이트 안 열림, 장부, 썸네일 생략(단일/일괄/헬퍼), solve_level_task 시간 전달·실측.
- `npx tsc --noEmit`(worktree/frontend, node_modules 는 본 폴더 심볼릭 링크) → 오류 0.
- 오프라인 미리보기 시뮬레이션(파일만, GameBoost 접속 없음, `/tmp/seedfix_sim/sim.py`, 2,560행 = level_1~1530 + infinity_1~1030(원본 500+N), relabel 켬). 배치 v5 파일 sha 38bce36f…:
  | 서버 raw | 보냄(변경) | 같음 | 보내지 않음 | 근거 없음 | 차단 | 기대값 |
  |---|---|---|---|---|---|---|
  | 최신 `upload_20261103/final.raw.json` (c7eb5f0a…) | **0** | 9,047 | 1,193 | 0 | 0 | 변경 0 ✔ |
  | 재업로드 전 `base_after_first_upload.raw.json` (6fc7ae9d… = /tmp/up4/base) | **7,306**(정식 4,462 · 무한 2,844, 전부 서버 값 변경) | **1,741** | **1,193** | 0 | 0 | 7,306 / 1,741 / 1,193 ✔ |
  보내지 않음 1,193 내역: 레벨 데이터에 값 없음 753 · 무한 시드 없음 432 · 옛 목록 값 충돌 8. 빈 층 정규화가 필요한 행은 18개(level_599·615·665·671·736·829·911·1466·1467, infinity_99·115·165 …)이고, 정규화 덕에 차단 0이다.

### 7-3 설계와 다른 점 / 남은 판단
- **solver 확인 간격은 바꾸지 않았다(256 유지).** 실측: 큰 40레벨에서 제한 초과 최대 1.08 s(32로 줄이면 0.27 s). 그러나 기본 5 s 판정 81레벨 표본(배치 1/19 추출)에서 32로 줄이면 3레벨(970·1331·1464)이 PROVEN_SOLVABLE → UNCERTAIN 으로 바뀌었다(기준선은 5.64~6.54 s 에 해를 찾음 = 초과 시간 덕). "기존 결과 불변"을 우선해 256 유지했다. 간격을 줄일지는 별도 결정이 필요하다.
- `solve_level_task` 변경으로 analyze 배치 API 가 `time_budget_s` 를 5.0 이 아닌 값으로 보낼 때만 결과가 달라진다(의도한 버그 수정. 0 → 무제한). 기본 5.0 호출은 같다.
- 근거 검사는 행 차단이 아니라 열 단위로 뺀다(일반 업로드와 같음). 보내는 값은 전부 근거 ok 다.
- 서버 행 digest 는 보드 조회 행 전체(etime 포함) 기준이다. 시험 대조는 etime 만 제외한다.
- 미검증: 실서버 시험 1행(사용자 승인 후 마더가 진행), 웹 화면 동작(GameBoost 읽기도 금지라 8100/5273 서버는 띄우지 않음), 실제 전송 속도.
- 반영 시 맵툴 백엔드 재시작이 필요하다(uvicorn --reload 라 파일 반영 즉시 자동 재시작 → 업로드가 없을 때 반영). 프론트는 vite HMR 로 탭이 새로고침된다.

---

## 8. 교차 리뷰(GPT) 반영 v2 (2026-11-03) — 패치 `SEEDFIX_20261103_v2.patch`

| # | 지적 | 반영 (worktree 줄 번호) |
|---|---|---|
| 1 high | 배치 경합 | `gboost.py:1303` 전역 `asyncio.Lock`(잡혀 있으면 :1393 409 `seed_export_busy`). `_BatchWatch`(:1334)가 배치 파일 stat(ino·mtime_ns·size)을 보고 바뀌면 sha/version 을 재계산한다. 확인 시점은 보드 조회 직후(:1461, 전체), 매 행 전송 직전(:1509, stat + 25행마다 전체), 요청 끝(:1522, 전체)이고, 바뀌면 즉시 409 `batch_changed_during_export`. 이미 보낸 행은 응답 `detail.results` 와 장부에 남는다. |
| 2 high | 시험 기록을 GameBoost 대상에 묶기 | `dda_seed_catalog.py:522` `normalize_gb_target`(스킴·호스트 소문자, 기본 포트·끝 '/' 제거) + project_id + board_id. 시험 기록 `gbTarget`(gboost.py:1532), 미리보기 응답 `gbTarget`(:1559), 게이트 비교(catalog :665, :684). 대상이 다르면 기록이 무효다. |
| 3 medium | 코드 해시 범위 | catalog `:502` `code_fingerprint_files` 가 모듈 파일 전체 바이트를 해시한다. 대상은 dda_seed_catalog · infinity_relabel · routes/gboost(변환 함수 `_convert_to_townpop_format` 포함) · clients/gboost(update_existing_level·load_board_rows) · production_store 다. 여기에 `seed_settings_snapshot`(:514, SEED_EVIDENCE_REQUIRED·LEGACY_CATALOG_EXPORT·PASS_VERDICTS·CATALOG_SHA256 등 현재 값)을 더한다. 해시는 호출마다 다시 계산한다(gboost.py:1309). |
| 4 medium | 프론트 dirty | `DdaSeedOnlyExport.tsx:169` 청크마다 미동기 편집 수·옵션·탭 버전을 다시 확인하고, 양수거나 바뀌면 즉시 중단한다. 판정은 순수 함수 `ddaSeedOnlyGuards.ts` 에 있다. **한계(코드 주석 기재)**: 이 값은 클라이언트가 세는 값이라 서버가 독립적으로 보장하지 못한다. 서버 쪽 방어는 배치 파일 sha/version 재확인(#1)과 업로드 요청의 `client_unsynced_edits>0` 409 다. |
| 5 medium | 미리보기 무효화 | 프론트: `selection`(배치 id·보드·프리픽스·범위·무한 모드/프리픽스/원본 범위·relabel, `ProductionExport.tsx:1772`)이 바뀌면 미리보기와 확인 체크를 버리고(`DdaSeedOnlyExport.tsx:82`) 전송 버튼을 막는다(:90 `stale`). 전송 직전에 대상 목록·탭 버전을 다시 비교한다(:124). 서버: 미리보기 저장소(`_SEED_PREVIEWS`, :1553, 최근 8개, 메모리)에 `{batch_id, version, sha, relabel, gbTarget, selection}` 와 대상(id→원본 번호)을 둔다. 업로드는 `preview_id` 가 필수이고, 없거나 만료되면 409 `preview_unknown`(:1423), 식별값이나 대상이 다르면 409 `preview_mismatch`(:1427). |

검증(v2):
- pytest 전체 **4,728 통과 · 6 실패 · 45 건너뜀**. 실패 6개는 모두 기준선의 기존 실패 집합 안에 있다. `test_generate_with_goals` 는 이번 회차에 통과했다(흔들림).
- DDA 관련 5파일 127 통과(신규 v2 파일 32개 = 기존 24 + 리뷰 8: 동시 실행 409, 보드 조회 중 배치 변경 → 전송 0, 전송 중 배치 변경 → 첫 행만 저장 후 409·장부 기록, 같은 크기 재작성 감지, 다른 base_url/project 기록 무효·표기만 다른 같은 서버는 유효, 코드 해시 범위(설정 상수·relabel·catalog·클라이언트 파일), 업로드 청크 dirty 409, 미리보기 식별값 불일치 409 5종).
- 프론트 순수 판정 11개: esbuild 로 변환해 node 에서 실행(`/tmp/seedfix_sim/guards_test.mjs`). 저장소에는 프론트 테스트 실행기가 없어서 저장소 테스트로 추가하지는 않았다.
- `npx tsc --noEmit` 오류 0.
- 오프라인 시뮬 두 기준 그대로다: 최신 raw → 보냄 0 / 같음 9,047 / 보내지 않음 1,193. 기준선 raw → 7,306(정식 4,462·무한 2,844) / 1,741 / 1,193.

남은 한계:
- GameBoost 서버 행이 다른 경로(다른 프로세스·도구·사람)로 바뀌는 경합은 막지 못한다. 청크마다 보드 재조회 digest 비교로만 줄인다.
- 잠금과 미리보기 저장소는 프로세스 메모리라 백엔드 재시작이나 다중 워커에서는 공유되지 않는다(재시작 → `preview_unknown` 으로 안전하게 실패).
- 해시에 routes/gboost.py 전체가 들어가므로, 이 파일을 어떻게 고치든 시험 1행을 다시 해야 한다(의도된 보수적 동작).

---

## 9. 재리뷰(Sonnet) 반영 v3 (2026-11-03) — 패치 `SEEDFIX_20261103_v3.patch`

| # | 반영 (worktree 줄 번호) |
|---|---|
| A medium | `gboost.py:1471-1574`: 전송 루프와 시험 대조를 `try/except BaseException` 으로 감쌌다. 예외나 취소(CancelledError) 때 처리한 out 을 `_ledger_once`(:1460, 한 번만 기록)로 장부에 남기고 다시 raise 한다. 전송 중 끊긴 행은 `failed / interrupted_uncertain`(서버 반영 여부 불명)이다. `assert_seed_payload` 실패는 예외 대신 그 행을 `blocked / payload_invalid`(:1523)로 두고, 이후 행은 `stopped_after_failure`(첫 실패 중단)다. |
| B low-medium | `DdaSeedOnlyExport.tsx:80-81` `selRef` 로 최신 선택값을 읽는다. 전송 직전(:138)과 청크마다(:181) 이 값과 미리보기 때 값을 비교한다. |
| C low | 코드 해시 대상에 `core/pv/cs_shuffle.py`(relabel 이 의존), `models/schemas.py`, `config.py` 를 더했다(`gboost.py:1318`). **한계**: 파일 바이트 기준이라 디스크와 이미 import 된 메모리 코드가 다른 경우(--reload 없이 파일만 바뀐 경우)는 구분하지 못한다(:1316 주석). |
| G low | `runSend` 가 첫 await 전에 inFlight 를 잡는다(:125). 본문은 `sendOnce`(:136)이고, 끝나면 finally 에서 해제한다. |
| E low-medium | `solver.py:394-415` `task_time_budget`: None → 5.0, 0 이하 또는 60 초과 → 60 s(`TASK_MAX_TIME_BUDGET_S`), 그 외는 그대로. 확인 결과는 아래. |

E 확인 결과(코드 읽기):
- `/analyze/solvability/batch` 를 부르는 프론트 경로는 두 곳이다. 둘 다 `batchAnalyzeSolvability`(`api/analyze.ts:360-379`)를 통한다.
  1. `RLSimulationPanel.tsx:494` — `timeBudgetS: 0, nodeBudget: 1,000,000` ("시간 제한 없이 끝까지 탐색 → 의심 레벨 확정" 의도). 수정 전에는 백엔드가 이 값을 무시해 **실제로는 5 s** 로 돌았다. v3 에서는 60 s 상한을 적용한다 → 이 경로의 판정이 더 많이 확정 쪽으로 바뀔 수 있다(의도에 가까워짐, 레벨당 최대 60 s).
  2. `SolvabilityPanel.tsx:152` — 화면 입력값(기본 **3 s**, 범위 0.5~60). 수정 전에는 무시돼 5 s 로 돌았다. 이제 입력값(기본 3 s)이 적용된다 → 기본 설정의 결과가 수정 전(5 s)과 다를 수 있다(UNCERTAIN 이 조금 늘 수 있음).
- 기본 5.0 으로 부르는 호출의 결과는 같다. 테스트 `test_solve_level_task_default_budget_result_unchanged` 는 solve_level 직접 호출과 판정·노드·수가 같은지 본다. 단일 판정 API(`/analyze/solvability`)는 task 를 거치지 않으므로 변경이 없다.

D(썸네일): 서버 map 이 같아 생략한 경우, 서버 썸네일이 예전에 업로드 실패 등으로 비어 있거나 틀려도 이 경로로는 다시 채워지지 않는다. 복구하려면 map 이 다른 업로드나 썸네일 업로드 API(`/api/gboost/thumbnail`)를 따로 써야 한다(한계, 미반영).

검증(v3):
- pytest 전체 **4,731 통과 · 7 실패 · 45 건너뜀**. 실패 7개는 기준선 기존 실패 6개 + 흔들리는 `test_generate_with_custom_tile_types`(기준선·수정본 모두 간헐 실패)다.
- DDA 5파일 131 통과(v2 파일 36개: +예외/취소 장부 2, payload_invalid 중단 1, 기본 예산 결과 불변 1, 시간 상한 케이스 추가, 해시 범위 cs_shuffle·schemas·config).
- 프론트 가드 점검 13/13(esbuild→node, ref 최신값 vs 클릭 시점 값 재현 포함).
- `npx tsc --noEmit` 오류 0.
- 오프라인 시뮬 두 기준 그대로다: 0 / 9,047 / 1,193 · 7,306(4,462+2,844) / 1,741 / 1,193.
