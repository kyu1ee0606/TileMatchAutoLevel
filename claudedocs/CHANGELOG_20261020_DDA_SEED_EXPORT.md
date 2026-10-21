# CHANGELOG 2026-10-20 — DDA 시드 갱신 버튼 + GameBoost 익스포트 ddaEasySeeds/ddaHardSeeds

> 정본: `claudedocs/difficulty_personalization/47_dda_seed_editor_export_20261020.md`
> 범위: 맵에디터 로컬 기능만. 실제 업로드·서버 변경·게임 연결·Unity·커밋은 하지 않음.

## 계획 (구현 전)
- 개발용 목록(버전·sha256 고정)을 `backend/data/dda_seeds/`에 둔다.
- 프로덕션 → 테스트 탭에 'DDA 시드 갱신' 버튼을 추가한다(미리보기 → 확인 → 에디터 내부 저장).
- `levels` 보드 익스포트에서 두 필드를 항상 명시한다(유효하면 값, 아니면 `""`).
- 익스포트 충돌 단계에 서버 값 비움·변경 경고를 추가한다.

## 변경
- 백엔드: 개발용 목록 `data/dda_seeds/dda_t0_seed_catalog.v1.json`(sha256 `57930b55…` 로더 고정) + 생성 스크립트 `scripts/build_dda_seed_catalog_20261020.py`.
- 백엔드: `core/dda_seed_catalog.py`(판정·익스포트 필드), `routes/dda_seeds.py`(`/api/dda-seeds/catalog|preview|export-preview`, 읽기 전용).
- 백엔드: `gboost.py` 단건 저장·upload-local 경로에서 `levels` 보드면 `ddaEasySeeds/ddaHardSeeds`를 항상 명시(유효 후보만 값, 그 외 `""`). 목록 응답에 `dda_easy_seeds/dda_hard_seeds`(schemas·client) 추가.
- 프론트: 테스트 탭 `DdaSeedRefreshPanel`(미리보기 → 적용, 중복 클릭 방지, 경합·미저장 편집 건너뜀, 실패·부분 성공 표시), `ddaSeedApply.ts`, `api/ddaSeeds.ts`, 타입 동기화. 익스포트 충돌 단계에 DDA 비움/변경/신규 경고.
- 테스트: `backend/tests/test_dda_seed_catalog.py` 30건 + fixture. `npx tsc --noEmit` 통과.
- 상세 결과·미검증 사항: 문서 47 §2·§3.

## 승인 후속 (17:30~ KST) — 상세: 문서 47 §5~§7
- P0: `backend/tests/conftest.py` — 테스트 세션 전체 네트워크 차단(socket·getaddrinfo·aiohttp) + GameBoost 클라이언트 Fake 격리 + 시도 카운트(>0이면 세션 실패). `tests/test_network_guard.py`. 기존 `test_api -k gboost` 재실행 2 PASS·시도 0. 16:39 사고 행(test_board/test_level)은 보존(삭제·복구 안 함).
- P1: 원인 = 에디터 배치에 서버 행 필드가 없고 익스포트 변환이 기본값을 채움(`gboost.py:481,482,495,517`). 출시 원본 행 스냅샷 `data/dda_seeds/dda_t0_source_rows.v1.json`(sha `063954da…`, 조건 해시 1499/1499 결속) 추가.
  - 일반 익스포트: 행이 스냅샷과 다르면 시드 `""`(row_changed). 편집값은 보존.
  - 신규 '시드만 내보내기'(`POST /api/gboost/dda-seed-export`, `DdaSeedOnlyExport.tsx`): 서버 행 read-modify-write로 두 컬럼만 변경. 신뢰 조건 실패 시 차단.
- fail-closed: 클라이언트 strict 조회(`GBoostLookupError`), 목록 `?strict=true`→502, 단일 저장·upload-local의 levels 보드 행별 strict 조회(실패→업로드 안 함)와 서버 시드 비움/변경 시 `dda_confirm` 필요(409/skipped). ProductionExport 조회 실패 시 업로드 중단 + 1회용 검사 게이트 + '다시 검사'.
- 테스트: pytest 58 PASS(가드 2·카탈로그 31·안전 25) + test_api gboost 2 + pv_canonical 16, 외부 시도 0. tsc 0.

## 서버 시드 저장 사전 조사 (18:17~ KST, 서버 쓰기 0) — 문서 47 §8
- update 전용 클라이언트 경로(new=1 폴백 없음), 보드 전체 strict 조회, 전용 스크립트 `scripts/dda_seed_server_apply_20261020.py` 추가(리허설 PASS).
- snapshot 18:22: 3066행 무결성 PASS. 후보 1216 전부 서버 전용 키(idx·etime·''·field4)로 기존 기준상 차단. L158만 조건 값 차이(useInRandomizer/useTeleportInRandomizer 0→"").
- 기준 완화(field4 제외)는 사용자 지시로 되돌림. 제안 기준(서버 전용 키 한정) 대상 1214건은 승인 대기.

## L159 원복 근거·부분 수정 개선 (18:40~ KST, 서버 읽기·쓰기 0) — 문서 47 §9
- 원복 근거 미확정((a) 누락 컬럼 보존 근거 없음, (b) "[]"→null 은 추정) → 쓰기 차단. 관리 UI 복구는 Codex/사용자 판단.
- 시드 경로: 전체 행 재전송 제거 → 두 필드 부분 수정 payload + `PARTIAL_UPDATE_VERIFIED=False` 기본 차단 + `assert_partial_payload`. roundtrip 경로 비활성. pytest 67 PASS(외부 시도 0).
- 18:45 L159 복구 미완료: 관리 UI 단일 셀 편집 경로 없음(행 전체 폼·checkbox 위험, Codex 저장 안 함), 부분 키 저장 선례 0건. L159 재조회 1회 = 시험 직후와 동일. 운영자 요청안·절차는 EVIDENCE.md.
- 18:49 사용자 관리 UI 복구 확인(GET 1회): L159 rewardList `[]`(원래 null 과 표현 다름), useInRandomizer/useTeleport 0→"" 부작용, etime 갱신, 나머지 동일. 기존 업로드 흐름·차이 표·A/B 제안 = 문서 47 §10. 부분 키 지원은 미확인 유지.
- 18:5x L159 기존 업로드 경유 1단계(쓰기 0, GET 1회): payload vs 서버 비교 — checkbox ""→0 복원·미전송 키로 게이트 미충족 → 업로드 보류. 08-19 2401행 관측상 업로드 후 출시 원본 행으로 복원 예측(문서 47 §11).
- 18:58 L159 1건 업로드(기존 변환기 payload + 두 시드, update-only new=0 1회, `level_159=upt`): 재조회 30키 예측=실측, 조건 해시 목록 일치, 시드 정확 일치, rewardList null·checkbox 0 복원. 문서 47 §12.

## 일괄 업로드 준비 (19:00~ KST, 서버 쓰기 0, 보드 GET 1회) — 문서 47 §13
- `predict_readback`/`READBACK_RULES`(L159 실측) 추가, `export_fields` 출시 행 비교를 예측 읽기값 기준으로. 일반 업로드 시드 미적용 payload 골든 동일.
- `scripts/dda_seed_bulk_20261020.py`: prepare(보드 GET 1회 → 전수 분류 → frozen manifest) / apply(기본 dry-run, `--apply` 시 update-only·fresh GET 경합·재조회·즉시 중단·재개).
- 결과: ready 1212 · 유지 L159 · 별도 승인 L158 · 보류 L1466(map)·L1523(predicted 없음). manifest sha `fbd24f9f…`. pytest 100 PASS, 외부 시도 0.

## 2026-10-21 — DDA 시드 일괄 업로드 보류 고정 (문서만, 서버 요청 0) — 문서 47 §14
- 상태 "준비 완료 / 사용자 일정에 따른 보류". 다음 업데이트 완료 후 사용자 재개 확인 → 최신 서버·원본·hash 재비교 → 새 manifest → 첫 10개 승인. 과거 manifest(`fbd24f9f…`) 자동 실행 금지, 업데이트 선행조건 아님. 보존 파일 sha 확인.
