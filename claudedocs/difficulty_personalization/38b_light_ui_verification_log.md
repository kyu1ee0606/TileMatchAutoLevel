# 38b. 검증 탭 2차 구현 — 경량 검증 로그 (하위세션 "경량검증", 2026-10-16~)

## Codex 실제 브라우저 경량 검증 — 2026-10-16 21:38~21:44 KST

- 격리 환경: worktree uvicorn 8001(PID55943), Vite 5174(PID55970), IAB `http://127.0.0.1:5174`. `/api/production/batches` 프록시 응답 fixture 2개만 확인 후 진입. 첫 동기화 화면 업로드0/다운로드2 확인. 메인8000/5173 접근·변경 없음.
- **실제 UI PASS:** 검증 탭 3레벨 표시; 구간237~239=95%, 주기10/위치8=90%, 개별238=88% 입력→미리보기에서237/239=95%(구간),238=88%(개별)→적용. `v1 · tc-b4966f0c` 표시.
- **실제 IndexedDB 목표 복원 PASS:** 브라우저 새로고침 후 프로덕션→검증 재진입 시 입력값/해시/각 행 목표95·88·95 유지. 페이지 탭 자체는 기본 에디터로 돌아가므로 재진입해서 확인함.
- **정상 배치 전환 PASS(경합 검증 아님):** 빈 fixture 선택 시 레벨 행 제거, 원래 fixture로 돌아오면 저장된 목표/행 복원. 진행 중 측정이나 지연 응답을 만들지 않았으므로 B3 비동기 경합 전체 PASS로 해석 금지.
- **관측 범위 신규 봇/C 생성 요청0:** 이 서버 실행의 전체 access log는 production GET, gboost health GET, verify/info GET, target-check POST 1건뿐. verify/jobs 생성·autoplay·generate 호출 없음. A 탐색/C 준비·실행/판정/중앙정렬은 누르지 않음.
- **미검증 유지:** 실제 C 기록/작업 복원, F1 실패응답의 실제 회색배지, G1 맵 변경, 지연응답 경합, 저장 실패. 미리보기 표가 88%에 `현 모델로 신뢰 판정: 가능`이라 표시됨: 입력 지원과 합격 가능성을 혼동할 여지가 있어 문구 의미 점검 필요(수치 기준 변경 금지).
- 관찰: 최초 동기화 직후 배치 selector에 이름은 있지만 본문 `배치가 없습니다`가 나왔음. 빈 배치를 선택 후 돌아오면 정상, 새로고침 후 재진입은 정상. 새 배치 생성 버튼은 누르지 않음. fixture/기존 대시보드 초기선택 경로인지 후속 정적 조사 필요.
- 자원: 시작 swap53149.06M/압박2 → 기동53221.75M/압박2 → UI검증53760.75M/압박2. 약612MiB 증가하여 검증을 짧게 종료. 종료직후53752.75M/압박2; 즉시 기준값 복귀했다고 주장하지 않음.
- 정리: IAB 테스트 탭 닫음, 본인이 띄운 PID55943/55970만 TERM 종료,8001/5174 listener 없음 확인. fixture 파일과 검증 origin 목표 저장은 후속 재현용 보존. 임시 설정 `/tmp/codex-cr-20261016-vite.config.ts` 보존(서버 비실행). 코드 수정/커밋/푸시/전체테스트/봇 실행 없음.


승인 범위: 메인 venv 재사용(백엔드 :8001) + 워크트리 `npm ci`(프론트 :5174, proxy→8001). 봇 측정·생성 탐색·재학습·전체 테스트/빌드·Unity·운영 데이터 변경·모델/기준 변경·병합/push 전부 금지. 문서 38 '최신 인계'(미커밋)는 읽기만, 수정 안 함.

## 단계별 기록

### 19:06 — 자원 기록 (시작 전)
swap: used 54443.81M / total 55296M (free 852.19M) · free% 36 · 압축 pages 1,043,506 · disk 여유 51GiB

### 19:06~19:10 — 백엔드/프론트 기동
- 백엔드: PID 37570, 메인 venv(`/Users/casualdev/TileMatchAutoLevel/backend/venv/bin/python`), cwd=워크트리 `backend`, `uvicorn app.main:app --host 127.0.0.1 --port 8001`(`--reload` 없음), 로그 `/tmp/wt_clearrate_backend.log`. `requirements.txt` 메인=워크트리 diff 없음 → 별도 venv 불필요.
- `GET /api/clear-rate/verify/info` → 200, `{"model_version":"cr-ftany-v24r-20261016","judge_version":"judge-1974e96320","seed_band":"CV","max_concurrent":2,"bot_version":"v2.4","bot_protocol":"theta4x128_v1","games_per_map":512,"protocol_problems":[]}` — **PASS(실제 경로)**: 활성 모델·judge·CV밴드 노출 정상, 봇 실행 0.
- 프론트: `npm ci`(package-lock 기준, 59s, 394 packages) — PASS. 저장소 파일 수정 없음(새 `node_modules`만 생성, git-ignored).
- 임시 vite 설정 `/tmp/wt_clearrate_vite.config.ts`(원본 `vite.config.ts` import + `server.port=5174`, `proxy['/api'].target=http://localhost:8001`만 덮어씀). 최초 실행 시 `/tmp`에서 `require('vite')` 실패(모듈 해석 경로 밖) → `NODE_PATH=.../frontend/node_modules` 지정해 해결(파일은 그대로 `/tmp`, 저장소 비수정).
- 프론트 PID: `npm exec` 래퍼 38518 / vite 실자식 node 38536, `--port 5174 --strictPart`. `curl localhost:5174` → 200, `curl localhost:5174/api/clear-rate/verify/info` → 8001과 동일 응답(proxy 정상) — **PASS(실제 경로)**.
- 자원: 두 서버 기동 직후 swap free 850→412→**274MB**(순간 급락, free% 34)까지 떨어졌다가 10초 뒤 macOS가 swap total을 55296→56320MB로 자동 증설하며 free **1307MB**·free% 37로 회복. 응답 지연 없음(curl 13~17ms). 지속 증가 아님(1회성 증설) → 중단 기준(5분간 지속 +1GiB) 미해당, 계속 진행.
- 메인 서버(8000/5173, PID 39400/90754/34901) 무변경 확인(재조회).

### 19:10~19:11 — 재개 시점 확인
자원: swap used 54361M/55296M(free 935M)·free% 35. 서버 3개 PID 모두 생존(37570/38518/38536), 응답 200. 안정.

### Playwright MCP 가용성 확인 (차단 보고 후 재확인)
`ToolSearch` 2회(`"playwright mcp browser"`, `"claude-in-chrome/computer-use"`) — 이 하위세션에 브라우저 자동화 도구 **전무**(playwright, claude-in-chrome, computer-use, built-in-browser 모두 미탑재). → **브라우저 실 UI 검증(버튼 클릭·배지색·네트워크 요청 확인·새로고침 복원) 전부 미검증으로 남김.** 대안으로 소스 직접 호출(node, 실제 경로)과 백엔드 curl(실제 경로)만 수행. fixture 경로는 이번에 사용 안 함(백엔드 실측정 저장소에 가짜 기록 안 씀).

### 커브 로직(`targetCurve.ts`) 직접 호출 검증 — 실제 경로(node, 소스 그대로)
방법: `/tmp/wt_clearrate_curve_check.mjs`(워크트리 비수정, 저장소 파일 `targetCurve.ts`를 절대경로로 직접 import)로 `node --experimental-strip-types` 실행. 14건:

| 항목 | 결과 | 비고 |
|---|---|---|
| override > cycle > segment 우선순위 | PASS | L5(override)=0.99, L10(cycle)=0.6, L3(segment)=0.9 |
| 구간 밖(L21) → 목표 미설정 | PASS | target=null, source=null |
| 경계 양 끝 포함(L1 시작) | PASS | |
| 경계 양 끝 포함(L20 끝) | PASS | L20은 cycle(10의 배수)도 겹쳐 source='cycle'로 해석됨 — **버그 아님**, 의도된 우선순위 동작(cycle이 segment 안에서 더 우선) |
| cyclePosition 계산 | PASS×2 | |
| 중복 구간 검출(1-10, 10-20) | PASS | `validateCurve` errors kind='overlap' |
| 목표 미설정 레벨 목록([6,7]) | PASS | `validateCurve(..., levels).unset` |
| draftToCurve 정상 변환(%→0~1) | PASS | |
| curveHash 순서 무관 동일성 | PASS | version 달라도 해시 동일(해시가 version 제외하는 설계 확인) |
| draftToCurve 누락 오류 검출 | PASS | `to` 빈 칸 → errors에 "누락" 포함 |

**결론: 커브 우선순위·경계·중복·누락 로직(문서 §4 상태표의 데이터 레이어) 실제 경로 PASS 14/14.** 단, 이 결과는 화면 렌더링·사용자 입력 흐름(버튼 클릭 → 미리보기 → 적용)까지 검증한 것은 아님 — React 컴포넌트 연결은 미검증.

### 프론트 기존 유닛 테스트 실행 — 실제 경로
`cd frontend && node --experimental-strip-types --test tests/clearRateLabels.test.ts` → **9/9 PASS**(라벨·판정 문구·reason 치환·근거 출처 구분). 문서 §8 계획 2번 항목에 해당하는 기존 테스트 파일 1개만 실행(전체 테스트/빌드 아님).

### 미실행(이번 범위서 보류)
- `tsc --noEmit`, `npm run build` — 금지 항목("전체 테스트/빌드") 명시 제외.
- 백엔드 `pytest tests/test_clear_rate_experiment.py tests/test_clear_rate.py` — 금지 항목 범위 모호성으로 보수적으로 **스킵**(승인 시 다음 단계로 분리 — 봇 실행 없는 순수 로직 테스트로 보임, 재확인 필요).
- IndexedDB 저장/복원(`clearRateVerifyStore.ts`) — Node에 `indexedDB` 전역 없음(확인: `node -e "console.log(typeof indexedDB)"` → `undefined`), 브라우저 도구 없이 검증 불가. fake-indexeddb 등 신규 의존성 추가는 범위 밖(설치 안 함). **미검증.**
- C 확인 측정 준비 화면, 목표 입력 UI, 상태 배지 색상, 새로고침 복원, 네트워크 요청 0건 확인 — 전부 브라우저 필요, **미검증.**

## 항목별 PASS/FAIL/미검증 요약 (지시 §2 체크리스트 대응)

| # | 항목 | 상태 | 경로 |
|---|---|---|---|
| 1 | 검증 탭 UI·버튼·상태 표시 연결 | 미검증 | 브라우저 필요 |
| 2 | 목표 곡선 입력→미리보기→적용 | 부분(로직 PASS) / 화면 미검증 | 로직: node 실제경로 / 화면: 미검증 |
| 3 | 개별>주기>구간 우선순위 | PASS | node 실제경로 |
| 4 | 구간 경계·중복·목표 누락 | PASS | node 실제경로 |
| 5 | 새로고침 후 복원 | 미검증 | IndexedDB, 브라우저 필요 |
| 6 | 목표 변경→재평가 필요 | 미검증 | 브라우저/상태머신 필요 |
| 7 | 맵·배치·봇조건 변경→측정 무효 | 미검증 | 브라우저 필요 |
| 8 | 모델·기준 변경→평가 오래됨 | 미검증 | 브라우저 필요 |
| 9 | 무효·오래된 합격 회색 표시 | 미검증 | 브라우저 필요 |
| 10 | 탭진입/목표변경/새로고침 시 신규측정 0건 | 미검증 | 네트워크 탭 필요(브라우저) |
| C준비 | 준비~확인화면까지, 실행 금지 | 미검증(미시도) | 브라우저 필요, 실행 자체는 어차피 금지 |

## 자원 추적 (요약)

| 시각 | swap used/total | swap free | free% |
|---|---|---|---|
| 19:06 (시작전) | 54443.81/55296 | 852M | 36% |
| 19:08 (npm ci 후) | 54545.81/55296 | 750M | 37% |
| 19:09 (서버기동 직후) | 54883~55028/55296 | 274~412M | 34~35% |
| 19:09:59 | 55028.81/56320(자동증설) | 1291M | 37% |
| 19:10:27 | 54361.44/55296 | 935M | 35% |

지속 악화 없음(1회성 급락→회복). 응답 지연 없음.

## 발견 오류

없음(이번 단계에서 실제 코드 결함 미발견). 최초 "L20 FAIL"은 테스트 데이터 설계 오류(내 테스트 스크립트)였고, 실제 소스 동작(cycle이 segment 내에서 우선)은 문서 §11 설계와 일치 — 코드 수정 불필요.

### 19:14 — 종료 (서버 중단, 자원 재측정)
- `kill` 8001(PID 37570) · 5174 래퍼+실자식(PID 38518/38536) — 사용자 승인에 따라 브라우저 자동화 도구 부재로 더 켜둘 이유 없음 + 스왑 여유 낮음.
- 확인: `lsof -iTCP -sTCP:LISTEN` 에 8001/5174 없음, PID 3개 조회 결과 없음(종료 확인). 메인 8000(PID 39400/90754)·5173(PID 34901) 그대로 생존.
- `/tmp/wt_clearrate_vite.config.ts`, `/tmp/wt_clearrate_curve_check.mjs`, `/tmp/wt_clearrate_backend.log`, `/tmp/wt_clearrate_frontend.log` 삭제 확인(`/tmp/wt_clearrate*` 매치 0건).
- 자원 재측정: swap used 54444.19M/55296M(free **851.81M**) · free% **36%** · disk 여유 50GiB — **시작값(852M·36%)과 거의 동일, 서버 종료로 완전 복귀.** 이번 세션 동안 악화 지속 없었음(최저 274M 1회성, 자동 swap 증설로 즉시 회복).

### pytest 봇 실행 여부 분류 (승인 요청용, 미실행)
`test_clear_rate_confirm.py` 최상단 docstring: "Bot runs are replaced by a fake runner except in the tiny measure() cancel test". 실제로 3개 테스트 파일 소스를 읽어 `measure()/measure_theta()` 직접 호출(=실제 봇 플레이) 여부로 분류:

| 파일 | 실제 봇 실행 테스트 | 게임 수 | 나머지 |
|---|---|---|---|
| `test_clear_rate.py` | 없음 (grep 확인: `measure(`/`measure_theta(` 직접호출 0건) | — | 전부 FakeRunner/모킹, 안전 |
| `test_clear_rate_experiment.py` | `test_measure_reproduces_training_row_from_editor_json` | **128판** (`measure_theta(... games=128 ...)`) | 나머지 전부 안전 |
| `test_clear_rate_experiment.py` | `test_measure_tags_and_store_invalidation` | **4판** (`PROTOCOLS["tiny_test"]=((0.85,),4)`) | 〃 |
| `test_clear_rate_confirm.py` | `test_measure_should_stop_between_rows` | 소량(2게임×1 theta, should_stop으로 조기취소) | 나머지 전부 `FakeRunner`로 대체, 안전 |

**승인 시 실행할 안전 커맨드(위 3개 제외, 봇 미실행)**:
```
cd backend && venv/bin/python -m pytest \
  tests/test_clear_rate.py tests/test_clear_rate_experiment.py tests/test_clear_rate_confirm.py \
  -k "not test_measure_reproduces_training_row_from_editor_json and not test_measure_tags_and_store_invalidation and not test_measure_should_stop_between_rows" \
  -q
```
이번 턴에는 승인 대기 상태라 **미실행**.

## 다음 필요한 안전한 작업 (우선순위)

1. **(승인 필요 없음, 낮은 리스크)** 이 세션에 Playwright MCP(또는 claude-in-chrome) 연결 — 연결되면 §2의 1,2,5~10번(화면·저장복원·상태배지·네트워크 0건) 전부 실제 UI로 검증 가능. 현재 유일한 진짜 차단 요인.
2. **(승인 필요)** 백엔드 pytest 3개 파일 — 위 "pytest 봇 실행 여부 분류" 표의 `-k` 제외 명령으로 실행하면 봇 0판. 승인되면 그 커맨드 그대로 1회 실행.
3. **(승인 필요, 낮은 리스크)** `cd frontend && npx tsc --noEmit` — 금지 목록에 명시돼 있어 미실행. 다만 타입 에러만 보는 정적 검사라 서버·자원 영향 없음. 필요 시 별도 승인.
4. 브라우저 확보 후에도 C "실제 실행·완료·서버 재시작 복구"는 이번 경량 검증 범위 밖으로 유지(문서 38 §1 규칙 그대로) — 별도 승인 건.

---

## 정적 감사 (2026-10-16, 하위세션 "정적감사" — Codex 후속 확인 19:39 KST 요청)

> **방법: 소스 읽기·검색만.** 서버·브라우저 기동, 테스트·tsc·빌드, 봇 측정 0회. 코드 수정 0줄. 대상 커밋 `66fc314`.
> **정적 감사 결과 ≠ 실제 UI PASS.** 아래 "문제 없음"은 "코드 경로상 그런 경로를 찾지 못함"이라는 뜻이며, 실제 화면·IndexedDB·네트워크 동작은 위 표의 "미검증" 상태 그대로다.
> 줄 번호: `S`=`frontend/src/components/ClearRate/ClearRateVerifySection.tsx`, `M`=`clearRateVerifyModel.ts`, `ST`=`clearRateVerifyStore.ts`, `BVP`=`ProductionDashboard/BatchVerifyPanel.tsx`, `CF`=`backend/app/core/clear_rate/confirm.py`, `R`=`backend/app/api/routes/clear_rate.py`.

### 전제 사실 (감사 중 확인)
- `ClearRateVerifySection` 은 `BVP:587` 에서 `key` 없이 `batchId` prop 만 받는다. 상단 배치 선택 `<select>`(`ProductionDashboard/index.tsx:2333-2335`)는 검증 탭이 열린 상태에서도 바뀔 수 있음 → **배치 전환 시 컴포넌트가 다시 마운트되지 않고 상태·진행 중 비동기 루프가 그대로 이어진다.**
- 섹션의 레벨 목록(`levels`, 맵 해시 `hashes`)은 `batchId` 가 바뀔 때만 읽는다(`S:103-123`). 같은 화면의 `BatchVerifyPanel` 재생성(`BVP:141-160` `saveProductionLevel`/`updateProductionLevel` 의 `level_json` 교체)·중앙정렬(`BVP:192-221`)은 섹션을 다시 읽게 하지 않는다.

### 항목 1 — 저장 트랜잭션 완료 시점: **문제 없음(경미 2건)**
- 근거: `ST:47-53 done(tx)` 는 `oncomplete` 에서만 resolve, `onerror`/`onabort` 에서 reject. `saveCurve`·`saveBTarget`·`putRecord`·`putJobRef`(`ST:95-129`) 모두 `await done(tx)`. `putRecord` 의 history add + put 은 같은 트랜잭션 안(`ST:113-121`)이라 한쪽 실패 시 abort → reject.
- "저장 완료"류 문구는 `applyCurve`(`S:162-165`, 저장 성공 후에만 `setCurve`·메시지) 와 `applyB`(`S:170`, 성공 후 'B 봇 목표 저장') 두 곳뿐이며 둘 다 `await` 뒤. 실패는 `saveError` 로 "저장 실패(적용 안 됨)" 표시 → 실패가 성공으로 보이는 경로 없음.
- 경미 ①: `saveRec`(`S:129-138`)·`persistJob`(`S:79-82`)는 화면에 먼저 반영하고 저장은 뒤에 기다린다(낙관 표시). 저장 중에는 "저장 안 됨" 표시도 "저장됨" 표시도 없고, 실패 시에만 "저장 안 됨"(판정 기록)·상단 오류(작업 참조, 행 표시는 없음). 성공을 단정하는 문구는 아니므로 오류 아님.
- 경미 ②: `saveError` 는 한 번 설정되면 지우는 코드가 없다 → 이후 저장이 성공해도 이전 실패 문구가 남는다(보수 방향, 오류 아님).
- 경미 ③(참고): 작업 참조 저장 실패 후 새로고침 → 서버에서는 진행 중인 작업이 화면에 "미측정". 다시 [C 준비] 하면 `existing` 이 진행 중이라 `planSummary.runnable=0` → [실행] 비활성(`S:397`)이라 참조를 다시 붙일 경로가 없다(측정 중복은 없음).

### 항목 2 — 복원 경합: **경미 오류 2건(자체 회복), 큰 결함은 항목 3·5에 분리**
- R2-1 복원이 사용자 입력을 덮음: `S:109-119` 복원 결과는 도착 즉시 `setSegDraft`/`setOvDraft`/`setBInput`/`setCurve`/`setRecords`/`setJobs` 를 **통째로 교체**한다. IndexedDB 읽기가 끝나기 전에 사용자가 곡선 초안·B 목표를 입력하거나 A 계산·C 실행을 시작하면 그 화면 값이 사라진다(저장된 기록은 IndexedDB 에 남음). 창은 IndexedDB 읽기 시간(보통 수~수십 ms)으로 짧음. 국소 수정안: 복원 완료 전에는 입력·실행 버튼 비활성(`restored` 플래그) 또는 `setRecords(prev => ({...st.records 맵, ...prev}))` 병합. 재검증: 느린 IndexedDB(DevTools CPU 6x 감속) 상태에서 탭 진입 직후 입력 → 값 유지 확인.
- R2-2 폴링 응답 순서 역전: `refreshJobs`(`S:84-92`)는 호출 시점 스냅숏 `r` 과 비교 후 `{...r, job: j}` 로 덮는다. 복원 시 호출(`S:118`)과 3초 폴링(`S:98`)이 겹치거나, 응답이 3초보다 늦어 폴링끼리 겹치면(진행 중 요청 대기 없음) 늦게 도착한 **옛 응답이 새 상태를 덮는다**(예: `cancelC` 직후 `cancel_requested=true` → 옛 응답의 `false` 로 되돌아가 [취소] 버튼 재노출, 큐 취소 `cancelled` → 옛 `queued`). 경합 토큰·취소 처리 없음. 다만 서버 상태는 단조(queued→running→종료)라 옛 값은 항상 "진행 중" 쪽이고, 그 경우 폴링이 계속돼 다음 응답(≤3초)에 바로 잡힌다 → **자체 회복, 잘못된 완료/합격 표시로 이어지지 않음.** 국소 수정안: 폴링 중복 방지(`inFlight` ref) + 덮기 전에 최신 상태(`setJobs(prev => …)`)와 `games_done`/종료 상태 단조성 비교. 재검증: 백엔드 지연(네트워크 Slow 3G) 상태에서 진행 중 작업 취소 → '취소 요청됨' 유지 여부.
- 모델/기준 버전(`info`) 비동기 도착 전 창은 항목 5 F1 참조.

### 항목 3 — 배치 전환: **오류 (중간) — 이전 배치 데이터가 새 배치 화면에 섞이는 경로 있음**
- B3-1 전환 직후 이전 배치 레벨·곡선이 남음: 복원 effect(`S:105`)는 `records/jobs/plan/preview/selected/rowError` 만 비우고 **`levels`·`curve`·`segDraft`·`bInput` 은 비우지 않는다.** 새 배치 레벨/저장 상태가 도착하기 전(또는 `getProductionLevelsByBatch` 실패 시 영구히 — 실패는 `console.error` 만, `S:108`) 화면은 `batchId`=새 배치 + `levels`=이전 배치 + `curve`=이전 곡선. 이 창에서 [A 탐색]/[C 준비→실행]을 누르면 새 배치 키(`recordKey(새 배치,…)`, `map_id=새 배치:n`, `batch_id=새 배치`)로 **이전 배치 맵**을 계산·측정 요청한다. 표시상으로는 새 레벨이 도착하면 `map_hash` 불일치로 "측정 무효"(회색)가 되어 초록 합격은 안 나오지만, C 는 이전 배치 맵 512판을 새 배치 이름으로 측정하게 된다(명시 클릭은 필요).
- B3-2 진행 중 루프가 이전 배치 데이터를 새 화면에 씀: `runExploration`(`S:175-201`)·`executeC`(`S:215-235`)·`judgeC`(`S:243-263`)·`refreshJobs`(`S:84-92`, 복원 `S:118` 포함)·`cancelC`·`prepareC`(`S:211`)·`applyCurve`(`S:162-163`)는 `batchId`/`levels`/`plan` 을 클로저로 잡은 채 계속 돌고 **`alive`/배치 일치 검사 없이** setState 한다.
  - `jobs` 상태 키가 **레벨 번호만**(`S:80`, `Record<number, ConfirmJobRef>`) → 이전 배치 L*n* 의 작업이 새 배치 L*n* 행에 "대기/측정 중/완료/결과 오래됨"으로 보이고, 그 행 [취소]는 **이전 배치 작업을 취소**, `doneCount`(`S:278`)·폴링 대상에 포함. 두 배치 맵이 같은 경우(복제·동일 레벨) `judgeC` 가 이전 배치 작업으로 새 배치 판정 기록을 만든다(서버 cond_hash 일치로 통과 — 측정 자체는 같은 맵이라 값은 타당하나 출처가 섞임).
  - `rowError` 도 레벨 번호 키 → 이전 배치 오류가 새 배치 행에 표시.
  - `prepareC` 응답이 전환 뒤 도착하면 **이전 배치 계획이 새 배치 확인 패널에 뜸** → [실행] 시 새 배치 `level_json` + 이전 `cond_hash` 로 제출 → 맵이 다르면 서버 `CONDITION_CHANGED 409`(`CF:239-241`)로 거부(안전망), 같으면 측정 진행.
  - `applyCurve` 저장 완료가 전환 뒤면 새 배치 화면에 **이전 배치 곡선이 "적용됨"** 으로 뜬다(새 배치엔 저장 안 됨) → 이후 A 기록이 그 곡선 해시로 저장 → 새로고침 시 "재평가 필요"(회색).
  - `records` 는 키에 배치 ID 가 있어(`M:99-100`) 새 배치 행에 섞이지 않음, `busy` 는 이전 루프가 끝날 때까지 새 배치 버튼을 막음(혼동 요인).
- 영향: 판정 초록 배지 오표시까지는 가지 않음(기록 키 분리 + map_hash 비교), 그러나 실행 상태 칸·취소 버튼·오류·확인 패널·적용 곡선이 다른 배치 것으로 보일 수 있고, 다른 배치 작업을 취소할 수 있음.
- 국소 수정안(1줄 우선): `BVP:587` 을 `<ClearRateVerifySection key={batchId} batchId={batchId} />` 로 → 전환 시 전체 상태 초기화·이전 effect 정리(언마운트 후 늦은 setState 는 React 가 무시). 보강: 섹션 안 `batchRef = useRef(batchId)` 를 두고 각 비동기 루프의 `await` 뒤 `if (batchRef.current !== batchIdAtStart) return/break`(이전 배치 루프가 API 를 계속 부르는 것까지 멈춤). `jobs`/`rowError` 키를 `jobRefKey(batch, level)` 로 바꾸는 방법도 가능.
- 재검증: fixture 배치 2개(같은 레벨 번호) → 배치 X 에서 [A 탐색] 진행 중/[C 준비] 응답 대기 중 상단 선택을 Y 로 변경 → Y 행에 X 의 오류·실행 상태·확인 패널·곡선이 나타나지 않는지, 네트워크에 X 레벨 요청이 더 나가지 않는지.

### 항목 4 — 무효화 연결: **연결됨(목표·모델·기준·맵·위치·봇 버전/프로토콜) / 간극 3건**
- 호출 경로: 행 렌더 `S:435-438` → `ctxFor(n)`(`S:266-270`: `hashes[n]`(level_json 해시)·`n`·`resolveTarget(curve,n).target`·`cHash`·`info.model_version/judge_version/bot_version/bot_protocol`) → `assessRecord`(`M:161-180`) → `displayVerdict`(`M:185-191`) + `VALIDITY_LABEL`(`S:478-480`) + 셀 흐림(`S:463`). 집계 `counts`(`S:271-276`)는 `current` 만 셈. B 칸은 `assessRecord(recB, {...ctx, target: bTarget, curveHash: null})`(`S:438`).
  - 목표 변경: [적용] → `setCurve`(`S:163`) → `cHash`·`resolveTarget` 변경 → `needs_rejudge` "재평가 필요". **연결됨.** (곡선 해시 비교라 해당 레벨 목표가 그대로여도 곡선 어디든 바뀌면 전 레벨 재평가 필요 — 보수적, 설계 §11 과 일치.) B 는 입력칸 값만 바뀌어도(저장 전) 즉시 재평가 필요로 표시됨.
  - 맵·배치 위치: `map_hash`·`level_number` 비교 → `measurement_invalid`. 실행 상태 `runState`(`M:194-199`)도 같은 두 값으로 '결과 오래됨'. **연결됨** — 단 간극 G1 참조.
  - 봇 버전/프로토콜: `info.bot_version/bot_protocol`(=활성 모델 manifest, `R:176-178`) vs 기록 값 → `measurement_invalid`. **연결됨**(둘 다 있을 때만 비교).
  - 모델·판정 기준: `info.model_version/judge_version` vs 기록 → `evaluation_stale`. **연결됨**(info 있을 때만 — 항목 5 F1).
- 간극 G1(중간): **같은 화면의 기존 배치 검증 재생성·중앙정렬이 `level_json` 을 바꿔도 섹션의 `levels/hashes` 가 갱신되지 않는다**(전제 사실 2). 그 사이 맵이 바뀐 레벨의 기존 기록이 "현재 유효"로 남고, [C 판정](`S:254`)·[C 실행](`S:226`)이 **옛 `level_json`** 을 서버에 보내므로 서버 cond_hash 검사(`CF:369`)도 통과 → 저장소에 없는 옛 맵 기준 판정이 "현재 유효"로 표시·저장될 수 있다(탭 이동·새로고침 후에는 map_hash 불일치로 회색 전환). 수정안: 섹션이 판정/실행 직전에 `getProductionLevelsByBatch` 로 레벨을 다시 읽거나, `BatchVerifyPanel` 의 재생성·중앙정렬 완료 시 섹션에 갱신 토큰(prop) 전달. 재검증: fixture 배치에서 C 완료 레벨을 중앙정렬로 바꾼 뒤(같은 화면) 행이 "측정 무효"로 바뀌는지.
- 간극 G2(낮음): 프런트는 **cond_hash·bot_config_hash·시드 대역을 현재 값과 비교하지 않는다**(현재 값을 프런트가 계산할 수 없음 — `assessRecord` 입력에 없음). 조건 확정 규칙(`finalize_game_conditions`) 코드 변경처럼 맵·모델·기준 버전은 같고 cond_hash 만 바뀌는 경우 기록이 "현재 유효"로 남는다. 모델 교체로 bot_config_hash(봇 노출값)가 바뀌는 경우는 "평가 오래됨"으로 표시되지만 지시 기준("측정 무효")과 문구가 다르고, [C 판정] 시 서버가 `MEASUREMENT_INVALIDATED 409`(`CF:369-371`)로 막는다. 시드 대역 변경은 `judge_version` 이 confirm band 를 포함(`CF:100-102`)해 "평가 오래됨"으로만 표시. 수정안(선택): `/verify/info` 에 현재 조건 규칙 버전을 추가해 기록에 저장·비교하거나, 복원 시 완료 C 레벨만 `/verify/plan`(봇 없음)으로 cond_hash 를 재확인.
- 간극 G3: `info` 미도착/실패 시 모델·기준·봇 검사 전부 생략 → 항목 5 F1.

### 항목 5 — 오래된/무효 결과 배지: **오류 (중간) 1건 + 간극 1건**
- 정상 경로: `displayVerdict`(`M:185-191`)는 `validity !== 'current'` 면 `과거: …` + 회색 클래스, 초록은 `current && PASS` 일 때만. 집계도 `current` 만. 탐색 기록은 판정이 항상 근거 부족(회색). B 칸은 별도 셀(`BotVirtualCell`, 중립색 설계).
- **F1(오류)**: `assessRecord` 는 `ctx.modelVersion`/`judgeVersion`/`botVersion`/`botProtocol` 이 null 이면 비교를 **건너뛴다**(`M:165-166,170-171`). `info` 는 `getVerifyInfo()` 비동기 결과이고 실패하면 `.catch(() => undefined)`(`S:120`)로 **조용히 null 유지 — 화면 표시 없음.** 따라서 (a) 탭 진입 직후 `/verify/info` 응답 전 짧은 창, (b) `/verify/info` 실패(모델 로드 오류·백엔드 구버전·네트워크) 시 **영구히**, 이전 모델·이전 판정 기준으로 저장된 C `PASS` 기록이 **초록 "합격" + "C 판정(현재 유효): 합격 n"** 으로 보인다. 재현 조건: 모델 버전이 바뀐 뒤(또는 기준 변경 뒤) `/verify/info` 가 실패하는 상태로 탭 진입. 국소 수정안: `assessRecord` 에서 모드 A 이고 `ctx.modelVersion == null || ctx.judgeVersion == null` 이면 `evaluation_stale`(사유 "현재 모델·기준 확인 안 됨") 반환, 그리고 `S:120` 실패 시 `setMessage('현재 모델·기준 버전 조회 실패 — 판정은 과거 결과로 표시')`. 영향: 무효 합격 초록 표시(지시 5번 직접 위반). **주의: 현재 `frontend/tests/clearRateVerifyModel.test.ts:81` 이 `modelVersion: null, judgeVersion: null` → `'current'` 를 명시적으로 기대한다(의도된 설계) → 수정은 설계 변경이므로 마더/사용자 결정 필요.** 재검증: 위 테스트 기대값을 바꾼 뒤 1회 실행 + 브라우저에서 `/verify/info` 를 DevTools 로 차단한 채 복원 → 회색 확인.
- F2(간극, 항목 4 G1 과 같은 원인): 같은 화면 재생성·중앙정렬 뒤 맵이 바뀐 레벨의 과거 합격이 초록으로 남음(탭 이동·새로고침 전까지).
- 참고(오류 아님): 무효 행에서도 `ClearRateCell` 의 신뢰도 글자(`ClearRateCell.tsx:14` `high: text-emerald-300`)는 초록 계열 그대로(셀 `opacity-60` 만). "합격" 배지는 아님.

### 항목 6 — 자동 측정 없음: **문제 없음**
프런트 전체에서 C·판정 API 를 부르는 곳은 `ClearRateVerifySection.tsx` 한 파일뿐(grep: `submitConfirm|planConfirm|evaluateConfirm|cancelConfirm|queryConfirmJobs|evaluateClearRateTarget` — 다른 사용처 0). effect 는 2개(`S:96-100` 폴링, `S:103-123` 복원)뿐이며 둘 다 생성 POST 를 부르지 않는다.

| 호출 | 메서드·경로 | 호출 지점 | 트리거 | 봇 실행 |
|---|---|---|---|---|
| `submitConfirm` | POST `/api/clear-rate/verify/jobs` | `S:226` (`executeC`) | **[실행] `cr-c-execute`(`S:397`)만** — `plan` 이 있어야 하고 `plan` 은 [C 확인 측정 준비] 클릭으로만 생김 | **예(유일한 생성 경로, 512판/맵, 데몬 스레드 `CF:264-266`)** |
| `planConfirm` | POST `/verify/plan` | `S:211` | [C 확인 측정 준비] `cr-c-prepare`(`S:374`) | 아니오(`structural_screen`, 봇 특성 NaN) |
| `evaluateConfirm` | POST `/verify/evaluate` | `S:254` | [C 판정] `cr-c-judge`(`S:375`) | 아니오(저장된 CV 기록 + `predict_level`, I/O 없음) |
| `evaluateClearRateTarget` | POST `/api/clear-rate/target-eval` | `S:186`, `S:192` | [A 탐색 계산] `cr-run-A`(`S:373`) / [B 봇 가상 계산] `cr-run-B`(`S:376`) | 아니오(캐시 조회·요청 측정만, `R:30-61`) |
| `checkTargets` | POST `/verify/target-check` | `S:152` | [미리보기] `cr-curve-preview`(`S:328`) | 아니오 |
| `cancelConfirm` | POST `/verify/jobs/{id}/cancel` | `S:238` | 행 [취소](`S:457`) | 아니오(중단) |
| `queryConfirmJobs` | POST `/verify/jobs/query` (동사는 POST 지만 `mgr.get` 조회만, `R:111-115`) | `S:85` | 복원 effect `S:118` + 진행 중 작업 폴링 `S:98`(3초) | 아니오 — **상태 조회** |
| `getVerifyInfo` | GET `/verify/info` | `S:120` | 복원 effect(배치 진입마다) | 아니오 |

- 탭 진입·새로고침·복원: 복원 effect → IndexedDB 읽기 + `queryConfirmJobs`(조회) + `getVerifyInfo`(GET). 생성 없음.
- 목표 변경: `applyCurve`/`applyB` → IndexedDB 쓰기만. 생성 없음.
- 배치 전환: 복원 effect 재실행(위와 동일). 생성 없음 — 단 항목 3 B3-2 처럼 **이미 사용자가 시작한** `executeC` 루프가 전환 뒤에도 남은 항목을 계속 제출할 수 있다(사용자 클릭에서 시작된 것이라 "자동 측정"은 아니나 화면 배치와 무관하게 진행).
- 중복 클릭: `busy` 검사는 렌더 전 연타에 뚫릴 수 있으나 `locks`(동기 ref, `S:222-224`) + 서버 `job_key` 단일화(`CF:245-251`)로 같은 맵 중복 측정은 생기지 않음.

### 정적 감사 결과 요약

| # | 항목 | 정적 판정 | 심각도 |
|---|---|---|---|
| 1 | 저장 완료 시점 | 문제 없음(경미 3) | — |
| 2 | 복원 경합 | 경미 오류 2(자체 회복/짧은 창) | 낮음 |
| 3 | 배치 전환 섞임 | **오류** B3-1·B3-2 | 중간 |
| 4 | 무효화 연결 | 연결됨 / 간극 G1(중간)·G2(낮음)·G3(=F1) | 중간 |
| 5 | 무효 합격 초록 | **오류** F1 (+F2=G1) | 중간 |
| 6 | 자동 측정 없음 | 문제 없음 | — |

**수정하지 않음**(지시: 오류는 보고 후 대기). 우선 수정 후보: F1(`assessRecord` null 처리, 모델 1곳) → B3(`key={batchId}` 1줄) → G1(판정/실행 직전 레벨 재읽기).

### 브라우저 검증 인계 (Codex 용, 정적 조사 — 실행 안 함)
`PD`=`frontend/src/components/ProductionDashboard/index.tsx`, `AZ`=`backend/app/api/routes/analyze.py`.

**3~5레벨 fixture: 기존 UI 에 안전한 소규모 배치 경로 없음.**
| 항목 | 내용 |
|---|---|
| 배치 생성 | 헤더 "+ 새 1500 배치 (톱니바퀴)/(선형)"(`PD:2209/2216`) → `handleCreateBatch`(`PD:1074`) → `createProductionBatch`(`storage/productionStorage.ts:81`). 입력 창 없음, `total_levels: 1500` 고정. 생성 자체는 메타만 쓰고 봇 없음, 이후 '생성' 탭으로 이동만. 레벨 0개 상태라 검증 탭 섹션은 빈 표. |
| 레벨 채우기 | JSON/파일로 생산 배치에 가져오는 UI 없음. "⬇️ 서버 가져오기"(`PD:2382`)는 백엔드 저장소에 이미 있는 배치만. 유일 경로 = [생성 시작] 후 [취소](`PD:2054`) — 동시 최대 10개라 개수 부정확, 레벨당 `/generate` 최대 18회(CPU). 봇을 피하려면 "난이도 검증 기반 생성" OFF(`PD:3090`, 기본 OFF) **및 "미할당 템플릿 자동 배치" 체크 해제(`PD:10914`, 기본 ON)** — 템플릿 슬롯은 검증 토글과 무관하게 `/analyze/autoplay` 50/100회 실행(`PD:1456`). 보스 레벨(10/20/30)은 `/generate/from-boss-template`. |
| 부작용 | 마운트 시 `syncBidirectional()`(`PD:1039`) + 레벨 저장마다 자동 푸시(`registerAutoSync`, `PD:1017`) → **테스트 배치가 백엔드 생산 저장소(`PUT /api/production/batches/{id}`)에도 복사됨.** 삭제 버튼(`PD:2432` → `deleteProductionBatch` `productionStorage.ts:826`)은 로컬 IndexedDB 만 지움, 서버 사본 삭제 UI 없음. |
| DB | 생산 `TileMatchProduction` v1(레벨 키 `[batch_id, level_number]`), 검증 탭 결과 `TileMatchClearRateVerify`(별도). 배치 id `batch_<ts>_<rand>` — 기존 배치와 충돌 없음. |
→ **결정 필요**: (a) 위 생성→취소 경로 허용(CPU·서버 사본 발생), (b) 기존 배치를 읽기 전용으로 쓰고 검증 탭 결과 DB 만 쓰기(운영 배치 레벨은 안 바뀌나 결과 기록이 그 배치 키로 남음), (c) DevTools 로 `TileMatchProduction` 에 테스트 배치 직접 기록(비UI). 이 감사에서는 선택하지 않음.

**실제 봇/무거운 작업을 실행하는 버튼·API (누르지 말 것)**
| 위치 · 버튼 | API | 실행 내용 |
|---|---|---|
| 검증 탭 섹션 [실행] `cr-c-execute`(C 준비 후) | POST `/api/clear-rate/verify/jobs` | **C 봇 측정 512판/맵** |
| 검증 탭 BatchVerifyPanel 배치 검증(`BVP:562`) | POST `/api/analyze/batch-verify` | 레벨당 봇 20회 |
| 〃 검증+재생성(`BVP:544`) | POST `/api/analyze/batch-verify-regenerate` | 봇 검증+재생성 |
| 〃 중앙정렬(`BVP:525`, 검토 탭에도) | POST `/api/analyze/fix-centering` | 봇 없음, **레벨 데이터 변경** |
| 생성 탭 "생성 시작"/"검증 기반 생성 시작"(`PD:3291`) · "▶ 자동생성 시작"(`PD:3021`) | POST `/api/generate`, `/generate/from-template`, `/generate/from-boss-template`, `/analyze/autoplay` | 1500레벨 생성(자동큐는 새 배치 반복) |
| 테스트 탭 "🚀 전체 순차 처리"·"🎯 선택 처리"·"🩹 OOB만"·"🏰 보스 재검증"·"🔒 초반 재검증"·"🔁 재검증(RL)"(`PD:7325~7674`) | POST `/api/rl-sim/level`, `/api/tune/auto`, `/api/generate` | RL 스윕+튜닝·재생성 |
| "🚀 일괄 테스트 시작"(`PD:8443`) · "🎯 자동 테스트 시작"(`PD:9547`) | POST `/api/analyze/autoplay`, `/api/rl-sim/level` | 봇 autoplay |
| "🎚️ 일괄 자동 튜닝"(`PD:7474`) · "🎚️ 미세"(`PD:8411`) | POST `/api/tune/*` | RL rollout |
| 각종 재생성 버튼(`PD:7771/7784/8318/8623/9067/9075`), 보스 재생성(`PD:7365/7374`), enhance | POST `/api/generate`, `/generate/enhance`, `/rl-sim/level` | 생성+RL |
| 내보내기 탭 gBoost 업로드(`ProductionExport.tsx:1503/1513`) | POST `/api/rl-sim/level` | `predicted_clear_rate` 없는 레벨 전부 RL(`:802`) |
| 야간 학습 시작(`NightStudyPanel`) | POST `/api/study/night/start` | 수 시간 백그라운드 |
| 편집기 AutoPlay 분석 · DifficultyPanel 시뮬/검증 생성 · RL 시뮬 패널 · 풀이가능성 · 패턴 디버그 측정 | POST `/api/analyze/autoplay`, `/api/simulate`, `/api/generate/validated`, `/api/rl-sim/batch`, `/rl-sim/search`, `/analyze/solvability(/batch)`, `/debug/.../measure` | 봇/RL/A* |

**안전(봇 없음·읽기 위주)**: 검증 탭 섹션 [미리보기] `/verify/target-check`, [적용]/[B 목표 저장](IndexedDB만), [A 탐색 계산]·[B 봇 가상 계산] `/target-eval`(캐시 조회만), [C 확인 측정 준비] `/verify/plan`, [C 판정] `/verify/evaluate`, 행 [취소], 폴링 `/verify/jobs/query`, GET `/verify/info`·`/verify/jobs/{id}`, `/clear-rate/predict`, POST `/api/analyze`(정적), 각종 GET 목록, 내보내기 "JSON 내보내기"(로컬 다운로드), 플레이테스트 탭 수동 기록. 배치 선택 `<select>` 변경은 안전하나 항목 3 오류 재현 경로임.
※ 이 표는 정적 조사(서브에이전트 + 주요 줄 직접 확인: `PD:1074-1100`, `PD:1450-1460`, `ProductionExport.tsx:802`, `PD:1017/1039`). 나머지 줄 번호는 표본 확인만.

### 미검증 (정적 감사로 대체 불가 — 기존 표 유지)
- 위 §항목별 표 1·2(화면)·5~10·C준비 전부 그대로 **미검증**. 이번 감사는 코드 경로만 봤고 실제 IndexedDB 트랜잭션·React 렌더 순서·네트워크 요청 0건은 확인하지 않음.
- 백엔드 pytest·tsc·프런트 모델/곡선 테스트 미실행.

---

## 국소 수정 B3·F1·G1 (2026-10-16 20:10 Codex 후속 지시, 하위세션 "정적감사")

> **작성만, 실행 0회**(tsc·node test·빌드·서버·브라우저·봇 없음). 모델·판정 기준·수치 신뢰도 변경 없음 — 버전·맵 확인 전 UI 과신 차단과 배치 전환 경계 처리만. 문서 38 은 상단 '최신 인계'(사용자 미커밋)와 같은 파일이라 **수정하지 않음** — 38 §10-4·§12-3 보정 문안은 아래 "38 보정 사항"에 둠(사용자 커밋 뒤 반영 권장).
> **정적 검토 결과 ≠ 실제 UI PASS.** 아래 근거는 호출 경로·상태 전이 읽기이며 테스트는 작성만 함.

### 변경 파일
| 파일 | 변경 |
|---|---|
| `frontend/src/components/ProductionDashboard/BatchVerifyPanel.tsx` | `levelsRevision` 상태(36-37줄), 재생성 검증 `finally`(184줄)·중앙정렬 `finally`(232줄)에서 `+1`, 섹션 호출(591-592줄) `key={batchId} levelsRevision levelsChanging={isVerifying}` |
| `frontend/src/components/ClearRate/clearRateVerifyModel.ts` | `Validity` 에 `unconfirmed`, `RunState` 에 `checking`(25-26줄)·라벨(30·35줄); `CurrentContext.mapHash: string\|null`·`modelVersion` null 의미 변경(153·157줄); `assessRecord`: mapHash null → unconfirmed(164줄), 모드 A 버전 null → unconfirmed(172-175줄), 버전 비교 무조건화(177-178줄); `displayVerdict` "확인 불가:" 접두(200-202줄); `runState` mapHash null + done → `checking`(205줄) |
| `frontend/src/components/ClearRate/ClearRateVerifySection.tsx` | props `levelsRevision/levelsChanging`(64-70줄); `loadedRev`·`levelsError`·`infoError`(72-74·90줄); 세대 `gen`·`live()`·`mapEpoch`·`polling`·`planRef`·`mapsConfirmed`(94-102줄); `persistJob/refreshJobs` 세대·배치 확인 + 조회 중복 방지(104-124줄); 레벨 읽기 effect 분리(134-146줄); 맵 갱신 시 계획 폐기 effect(148-152줄); 복원 effect cleanup 에서 `gen++`, info 실패 기록(154-175줄); 모든 비동기 핸들러 세대·맵세대 확인(181-337줄); `curMap`·`runLocked`(341·355줄); 상태 문구 `cr-info-error/cr-info-loading/cr-levels-error/cr-map-checking`(369-379줄); 실행 버튼 잠금(462-465·486줄); 행 실행 상태 `runState(ref, curMap(n), n)`(521줄) |
| `frontend/tests/clearRateVerifyModel.test.ts` | 81줄 기대값 `current` → 별도 테스트로 `unconfirmed`; 테스트 2개 추가 + 배지 테스트 보강 |

### B3 — 배치 전환
- 재현 조건(수정 전): 검증 탭에서 [A 탐색]/[C 판정]/[C 준비] 응답 대기·C 실행 루프·작업 폴링 중 상단 배치 `<select>` 변경.
- 수정: ① `key={batchId}` → 배치가 바뀌면 섹션 전체 재마운트(모든 상태 초기화, 이전 폴링 interval 은 effect cleanup 으로 `clearInterval`). ② key 만 믿지 않음: 복원 effect cleanup 에서 `gen.current++`. 모든 비동기 핸들러(`doPreview·applyCurve·applyB·runExploration·prepareC·executeC·cancelC·judgeC·refreshJobs`)는 시작 시 `g=gen.current` 를 잡고, `await` 뒤 `live(g)` 가 거짓이면 **setState 안 함 + 루프는 다음 요청 전에 `return`**(새 측정 `submitConfirm`·판정·조회 요청 없음).
- 저장소 쓰기 정책: 이미 서버가 만든 C 작업의 참조(`putJobRef`)와 이미 받은 판정 기록(`putRecord`)은 **원래 배치 키**로 IndexedDB 에 남김(추적 유지 — 다른 배치 키로 쓰는 경로 없음). 화면 상태 반영은 현재 세대 + `ref.batch_id === batchId` 일 때만(`persistJob` 106줄). 세대가 바뀐 폴링 응답은 저장소에도 쓰지 않음(117줄 `return`).
- 매핑 키 확인: `jobs`·`rowError` 상태 키는 여전히 레벨 번호이나, 인스턴스가 배치마다 새로 만들어지고(key) 쓰기는 세대·배치 확인을 거치므로 다른 배치 값이 들어갈 경로 없음. `records` 키는 원래 배치 포함. `doneCount`·`judgeC` 대상도 `ref.batch_id === batchId` 추가(318·354줄). `locks` 는 인스턴스별 ref.
- 비실행 검토 근거(상태 전이): 배치 X→Y: 부모 렌더 → key 변경 → X 인스턴스 언마운트(cleanup: `alive=false`, `gen++`, interval 해제) → X 의 대기 중 `await` 복귀 → `live(g)` 거짓 → 화면 미반영·후속 요청 없음. Y 인스턴스는 새 `gen=0`·빈 상태에서 복원.
- 남은 위험: 언마운트 직전에 이미 전송된 요청 1건(예: `submitConfirm`)은 취소되지 않음(AbortController 미도입 — 서버 작업 생성은 사용자 클릭에서 시작된 것이고 참조는 원래 배치 키로 저장됨). 폴링 응답 순서 역전(R2-2)은 중복 조회 방지(`polling` ref)로 줄였으나 `cancelC` 응답과 진행 중 조회의 역전은 남음(자체 회복).

### F1 — 버전 확인 전·실패 시 초록 합격 금지
- 재현 조건(수정 전): `/verify/info` 응답 전 또는 실패 상태로 복원 → 이전 모델 C `PASS` 가 초록 "합격" + 집계 "합격 n".
- 수정: `assessRecord` 모드 A 에서 `ctx.modelVersion == null || ctx.judgeVersion == null` → `unconfirmed`(사유 "현재 모델·판정 기준 버전 확인 불가"). `displayVerdict` → 회색 `확인 불가: 합격`. 집계 `counts` 는 `current` 만이라 자동 제외. 화면: 조회 중 `cr-info-loading`, 실패 `cr-info-error`(오류 내용 + "회색 표시·합격 집계 제외"). 판정식·임계·모델·기준 버전 값 변경 없음.
- 순서: 맵·위치·봇 변경 검사(측정 무효)가 먼저 → 버전을 몰라도 맵이 바뀐 기록은 "측정 무효". 모드 B 는 합격 색이 없는 별도 칸이라 버전 확인 대상에서 제외(B 의 봇 버전/프로토콜 비교는 info 없으면 생략 — 남은 간극, 초록 표시 경로 아님).
- 비실행 검토 근거: 행 렌더 → `ctxFor(n)`(info 없으면 version null) → `assessRecord` → `unconfirmed` → `displayVerdict` 회색, `counts` 미포함, 셀 `opacity-60`.

### G1 — 같은 배치에서 맵이 바뀐 뒤 최신 level_json 다시 읽기
- 재현 조건(수정 전): 같은 검증 탭에서 BatchVerifyPanel [검증+재생성] 또는 [중앙정렬]이 `level_json` 을 저장 → 섹션은 옛 `levels` 그대로 → 옛 맵 해시로 "현재 유효", [C 판정]·[실행]이 옛 `level_json` 전송.
- 수정: 부모가 저장 작업 중이면 `levelsChanging=isVerifying`, 끝나면(`finally`, 오류·부분 완료 포함) `levelsRevision+1`. 섹션은 `[batchId, levelsRevision]` effect 로 `getProductionLevelsByBatch` 를 **실제로 다시 읽고**, 다 읽은 revision 을 `loadedRev` 에 기록. `mapsConfirmed = loadedRev === levelsRevision && !levelsChanging` — revision 이 올라간 렌더부터 읽기 완료 전까지 1프레임도 확인 완료로 보지 않음. 확인 전: `ctx.mapHash=null` → 판정 `unconfirmed`(회색), 완료 C 작업 실행 상태 "맵 확인 중"(`checking`, [C 판정] 대상 아님), A·B·C 실행 버튼 잠금(`runLocked`), 문구 `cr-map-checking`. 읽기 실패 시 `cr-levels-error` 표시 + 계속 잠금.
- C 계획 무효화: `[levelsRevision, levelsChanging]` effect 가 `mapEpoch++` 하고 준비된 계획이 있으면 폐기 + 안내 문구. `prepareC` 응답이 맵세대 변경 뒤 도착하면 계획을 띄우지 않음. `executeC`·`judgeC`·`runExploration` 루프는 매 항목 전 맵세대 확인 → 바뀌었으면 남은 요청 중단.
- 갱신 비용: 저장 작업 1회 종료당 IndexedDB 배치 읽기 1회 + 맵 해시 재계산(레벨 수만큼). 폴링·매 프레임 없음.
- 비실행 검토 근거(상태 전이): 중앙정렬 클릭 → `setIsVerifying(true)` → 섹션 `levelsChanging=true` → `mapsConfirmed=false`, 맵세대++ / 계획 폐기 → 저장들 → `finally`: `isVerifying=false`, `levelsRevision=r+1`(같은 배치 렌더) → `loadedRev(r) ≠ r+1` 이므로 여전히 확인 전 → 다시 읽기 완료 → `loadedRev=r+1` → 새 해시로 `assessRecord` → 바뀐 레벨은 "측정 무효", 완료 작업은 "결과 오래됨".
- 남은 위험: 섹션 밖 다른 탭(테스트·검토 등)이 레벨을 바꾸는 경우는 탭 전환으로 섹션이 재마운트되어 다시 읽힘(대시보드는 탭별 조건부 렌더) — 같은 화면 동시 변경 경로는 BatchVerifyPanel 뿐으로 확인. 다른 브라우저 탭/서버 pull 에 의한 변경은 감지하지 않음(기존과 동일). 기존 배치 검증 [배치 검증](재생성 없음)은 메타만 바꾸므로 revision 을 올리지 않으나 실행 중 `isVerifying` 으로 잠금은 걸림.

### 작성한 테스트 (미실행)
`frontend/tests/clearRateVerifyModel.test.ts` — 실행 명령(승인 시): `cd frontend && node --experimental-strip-types --test tests/clearRateVerifyModel.test.ts`
- 수정: `model or judgment criteria change → evaluation stale` (null 케이스 제거)
- 신규: `unknown current versions (/verify/info loading or failed) → unconfirmed, never current` (4 조합 + 맵 변경 우선)
- 신규: `latest map not yet confirmed (mapHash null) → unconfirmed; done job → checking, not judgeable`
- 보강: `no PASS badge under new conditions` (`unconfirmed` 회색·"확인 불가:" + 버전 null assess→display 연결)
- React 컴포넌트(B3 세대 경계·G1 갱신 경로)는 단위 테스트 수단 없음(테스트 런너는 node 내장, DOM 없음) → 브라우저 검증 항목으로 남김(아래 fixture).

### 38 보정 사항 (사용자 미커밋 상단과 같은 파일이라 미반영 — 반영 권장 문안)
- §10-4 실행 상태 목록에 `맵 확인 중(최신 맵 다시 읽기 전 — 완료 작업도 판정 대상 아님)` 추가.
- §12-3 표에 행 추가: `최신 맵 확인 전 · 현재 모델/기준 버전 조회 전·실패 | unconfirmed | "현재 상태 확인 불가" — 회색 "확인 불가: …", 집계 제외, 실행 버튼 잠금(맵 확인 전)`. 표 아래 "모델 버전 없으면 오래됨 처리"는 기록 쪽 값이 없을 때(그대로), 현재 쪽 값을 모를 때는 unconfirmed 로 구분.
- §10-4 하단: "배치 전환 시 섹션 재마운트(key) + 진행 중 비동기 작업은 세대 확인으로 화면 쓰기·후속 요청 중단".

### 브라우저 fixture 인계 (향후 별도 테스트 컨텍스트용 — 이번에 주입·실행 안 함)
**격리 원칙**: IndexedDB 는 origin(호스트:포트)별이다. 운영 화면 `localhost:5173` 과 다른 포트(예: 워크트리 프런트 `:5174`)의 **새 브라우저 프로필**에서만 주입한다. 대시보드는 마운트 시 `syncBidirectional()` → 로컬에만 있는 배치를 **연결된 백엔드 생산 저장소로 push**(`pushLocalMissingToServer`, `productionServerSync.ts:226-245`)하므로, 프런트 `:5174` 의 `/api` 프록시는 반드시 **워크트리 백엔드 `:8001`**(저장 위치 `TileMatchAutoLevel_wt_clearrate/backend/data/production/`, git-ignored·현재 없음 — 메인 `:8000` 의 운영 저장소와 별개)로 향해야 한다. 메인 `:8000` 에 연결된 화면에서는 주입 금지.
**주입 대상** (DB `TileMatchProduction` v1, `storage/productionStorage.ts:20-62`)
| 스토어 | 키 | 최소 레코드 |
|---|---|---|
| `batches` | keyPath `id` | `{ id:'batch_fixture_cr_<날짜>', name:'[fixture] CR 검증 3레벨', created_at, updated_at, total_levels:3, levels_per_set:10, total_sets:1, generated_count:3, playtest_count:0, approved_count:0, rejected_count:0, exported_count:0, saved_level_count:3, difficulty_start:0.3, difficulty_end:0.3, use_sawtooth:false, gimmick_unlock_levels:{} }` (필수 필드는 `types/production.ts:248-294` 중 `?` 없는 것 — 위가 전부, `tile_type_profile`·`__server_version` 등은 선택) |
| `levels` | keyPath `['batch_id','meta.level_number']`, 인덱스 `batch_id` | `{ batch_id, meta:{ level_number, set_index:0, local_index, generated_at, target_difficulty:0.3, actual_difficulty:0.3, grade:'B', status:'generated', status_updated_at, playtest_required:false, playtest_priority:0, playtest_results:[] }, level_json }` (필수 meta 는 `types/production.ts:128-239` 중 `?` 없는 필드) |
**레벨 JSON 출처(봇·생성 없이)**: 저장소 골든 `backend/tests/golden/clear_rate_L237.json` 의 `level_json`(키 `layer, layer_0~2, useTileCount, unlockTile, randSeed, shuffleTile, typeImbalance, timea, autoCollectCount`, `placement_level=237`, 모델 캐시 적중 → [A 탐색]이 숫자 결과를 냄). 권장 3~5레벨:
1. L237 = 골든 그대로(캐시 적중, 탐색 결과·C 준비 확인용)
2. L238 = 같은 JSON(배치 위치 다름 → cond_hash 다름, 캐시 미스 "측정 없음" 확인용)
3. L239 = 같은 JSON 에서 `randSeed` 만 +1(맵 해시 다름 — 무효화 비교용)
4. (선택) L240·L241 = 같은 JSON(목표 곡선 구간·주기·개별 우선순위 확인용)
또는 기존 운영 배치의 레벨을 **읽기만** 해서(운영 화면 DevTools 에서 `levels` 인덱스 `batch_id` getAll → JSON 복사) 위 형식으로 테스트 프로필에 붙여 넣는다(운영 DB 쓰기 없음).
**주입 절차**: ① 워크트리 백엔드 `:8001`·프런트 `:5174`(별도 승인 필요, 38b 앞 절의 임시 vite 설정 방식) ② 새 프로필로 `http://localhost:5174` 를 열되 대시보드 진입 전 빈 페이지에서 DevTools 콘솔로 `indexedDB.open('TileMatchProduction',1)` — 스토어가 없으면 `onupgradeneeded` 에서 위 keyPath·인덱스대로 생성(앱 코드와 동일하게: `batches`(keyPath id), `levels`(keyPath ['batch_id','meta.level_number'] + 인덱스 batch_id·status·level_number·grade·playtest_required), `playtest_queue`(keyPath ['batch_id','level_number'] + 인덱스 priority)) ③ readwrite 트랜잭션으로 batch 1건 + level 3~5건 `put`, `oncomplete` 확인 ④ 생산 대시보드 → 배치 선택 → 검증 탭. (주입은 앱 저장 함수를 거치지 않으므로 자동 push 알림은 안 생기지만, 대시보드 마운트 시 `syncBidirectional` 은 `:8001` 로 push 함 — 그래서 ①의 백엔드 분리가 필수.)
**정리**: 테스트 프로필 삭제(또는 DevTools Application → IndexedDB `TileMatchProduction`·`TileMatchClearRateVerify` 삭제) + 워크트리 `backend/data/production/batch_fixture_cr_*`(push 사본)·`backend/data/clear_rate_verify/`(C 작업·측정 — C 실행 안 했으면 없음) 삭제. 운영(메인) 저장소·`:5173` IndexedDB 는 손대지 않음.
**검증 항목 매핑**: B3 = fixture 배치 + 아무 다른 배치 1개(빈 배치도 가능) 사이 전환 중 대기 응답 확인 / F1 = DevTools 네트워크에서 `/api/clear-rate/verify/info` 차단 후 복원 → 회색 "확인 불가"·`cr-info-error` / G1 = fixture 에서 [중앙정렬] → `cr-map-checking` → 갱신 후 바뀐 레벨 "측정 무효"(중앙정렬은 봇 없음, 레벨 데이터 변경이므로 fixture 에서만).

---

## 단위 테스트 1회 실행 — clearRateVerifyModel.test.ts (2026-10-16 20:39 KST, Codex 20:40 지시)

> **단위 테스트(순수 함수) PASS ≠ React/IndexedDB 실UI 검증.** 이번 결과는 `assessRecord`·`displayVerdict`·`runState` 등 순수 함수만 확인. B3(배치 전환 세대 경계)·G1(레벨 다시 읽기·버튼 잠금)·F1 화면 문구·IndexedDB 저장/복원·네트워크 요청 0건은 여전히 **미검증**(브라우저 필요).

- 실행 전 runtime import 확인(grep `import|require|fetch|axios|apiClient|indexedDB|setTimeout|setInterval|Worker`): 테스트 → `node:test`, `node:assert/strict`, `clearRateVerifyModel.ts` → runtime: `clearRateLabels.ts`, `targetCurve.ts`(→ `clearRateLabels.ts`)만. `api/clearRateVerify`·`api/clearRateTarget` 는 **type-only**(strip 시 제거). fetch/axios/IndexedDB/타이머 호출 0건 → 실행.
- 명령: `cd TileMatchAutoLevel_wt_clearrate/frontend && node --experimental-strip-types --test tests/clearRateVerifyModel.test.ts` (node v22.22.3), 1회.
- 결과: **14/14 PASS, fail 0**, exit 0, 129ms. 신규·수정 테스트(버전 모름 → unconfirmed, 맵 확인 전 → unconfirmed/checking, 배지 회색) 포함.
- 자원: 전 20:39:36 — free% 36, swap used 54088.31M / 55296M (free 1207.69M) · 후 20:39:36 — free% 36, swap 동일(54088.31M, free 1207.69M). 변화 없음.
- 다른 테스트 파일·tsc·빌드·서버(8001/5174)·브라우저·봇 실행 없음.

---

## 서버 측 UI fixture 준비 (2026-10-16 21:10 KST, Codex 21:10 지시) — 파일 준비만, 서버·브라우저·API 호출 0회

> 배경: Codex 브라우저는 DevTools JS 로 IndexedDB 주입 불가 → 대시보드의 **기존 동기화 UI**(마운트 시 `syncBidirectional` → `pullAllToLocal`)가 워크트리 백엔드 `:8001` 저장소에서 읽어 가도록 서버 파일을 둔다. fixture 결과는 실제 레벨·실측이 아니다.

### 형식 근거 (읽기만)
| 항목 | 근거 |
|---|---|
| 저장 위치 | `backend/app/api/routes/production_store.py:25-27` `_STORE_DIR = <backend>/data/production`, 파일명 `{batch_id}.json`(`:41-42`), id 는 `/ \ .. \0` 금지(`:34-38`) |
| 파일 스키마 | PUT 저장 형식 그대로 `{batch_id, batch, levels, saved_at, version}`(`:511-517`). 서버는 batch/levels 를 opaque JSON 으로 보관(`:8-9`) |
| 목록 | `GET /api/production/batches`(`:546-601`): 디렉터리 스캔, `_index.json` 은 (mtime,size) 캐시일 뿐 — 없거나 미스면 그 파일을 파싱해 인덱스 재작성(`:569-584`) → **index 수동 갱신 불필요**(생성하지 않음) |
| 조회 | `GET /api/production/batches/{id}`(`:604-611`) 파일 그대로 반환 |
| 프런트 pull | `productionServerSync.ts:198-224` `pullAllToLocal`: 서버 목록 중 로컬에 없는 배치 → `pullBatchToLocal`(`:162-171`): `putBatchRaw({...batch, __server_version: version})` + `saveProductionLevels(batchId, levels, {silent:true})`(쓰기 알림 없음 → 자동 push 없음). 레벨 레코드 = `{batch_id, ...level}`(`productionStorage.ts:244-248`), 키 `[batch_id, meta.level_number]` |
| 마운트 동작 | `PD:1039` `syncBidirectional()` = `pushLocalMissingToServer`(로컬에만 있는 배치를 **연결된 서버로 강제 업로드**, `productionServerSync.ts:226-245`) → `pullAllToLocal` |
| 필수 필드 | `ProductionBatch`(`types/production.ts:248-294`, `?` 없는 것): id·name·created_at·updated_at·total_levels·levels_per_set·total_sets·generated/playtest/approved/rejected/exported_count·difficulty_start/end·use_sawtooth·gimmick_unlock_levels. `ProductionLevelMeta`(`:128-239`): level_number·set_index·local_index·generated_at·target_difficulty·actual_difficulty·grade·status·status_updated_at·playtest_required·playtest_priority·playtest_results. `calculateProductionStats`(`productionStorage.ts:633~`)가 `by_status[status]`·`by_grade[grade]` 를 세므로 enum 값 필요 |

### 생성 파일 (git-ignored 확인: `.gitignore:52 backend/data/production/` · `git status --ignored` → `!!`) — 미추적·커밋 안 함
디렉터리는 원래 없었음(`ls` → No such file) → 새로 만듦, 덮어쓴 파일 없음. 메인 트리 `backend/data/production` 은 읽지도 쓰지도 않음.
| 파일 | id | 내용 |
|---|---|---|
| `TileMatchAutoLevel_wt_clearrate/backend/data/production/codex_ui_fixture_20261016_a.json` | `codex_ui_fixture_20261016_a` | 이름 `[FIXTURE] codex_ui_20261016_a — L237 골든×3 (238/239=같은 맵)`, version 1, 레벨 3개 L237·L238·L239 |
| `…/backend/data/production/codex_ui_fixture_20261016_empty.json` | `codex_ui_fixture_20261016_empty` | 이름 `[FIXTURE] codex_ui_20261016_empty — 전환용 빈 배치`, version 1, `levels: []`(서버 `levels` 기본값 빈 배열 허용, `:90`), total_levels 0 |

### 골든 사용 방식 (결정 근거)
- 저장소 골든 중 **배치 위치 237~239 에 해당하는 맵은 `backend/tests/golden/clear_rate_L237.json` 하나뿐**(그 밖의 골든: `bot_v2/v1_golden.json` L55·L123, `bot_v2/v21_bomb_level.json` L302, `pv_t0/inputs` r_level_0004~ — 레벨 번호가 다름). L237 골든은 모델 캐시가 있어 [A 탐색]이 숫자 결과를 낸다(문서 38 §14 근거 맵).
- 결정: **3레벨 모두 L237 골든 `level_json` 을 변경 없이 복사**, 배치 위치(meta.level_number)만 237/238/239. randSeed 변형 등 데이터 가공 안 함. 238·239 는 **실제 238/239 맵이 아님**을 배치 이름과 각 레벨 `meta.fixture_note` 에 명시.
- 의미: L238/L239 는 같은 맵이 다른 배치 위치에 놓인 것 → cond_hash 가 달라 캐시 미스("봇 측정 없음") 예상(배치 위치 무효화·캐시 미스 표시 확인용). 맵 변경 무효화(G1)는 fixture 에서 [중앙정렬] 결과에 의존하며, L237 골든이 중앙정렬 대상이 아닐 수 있음 → 그 경우 G1 은 "변경 0건 → 무효화 없음" 확인만 가능(미검증으로 남김).
- 허위 값 없음: `bot_clear_rates`·`match_score`·`verified`·`verification_passed`·`predicted_clear_rate`·`target_clear_rate(s)`·보상·RL 필드 **미포함**. `status` 는 `'generated'`(타입 주석 "생성됨 (봇 검증 완료)", `types/production.ts:13`)가 검증 완료를 암시하므로 쓰지 않고 `'needs_rework'` 사용. 타입 필수 숫자 `target_difficulty=0`·`actual_difficulty=0`·`grade='S'` 는 **자리채움**(측정·예측 아님)으로 `fixture_note` 에 명시. 배치 카운터는 0, `difficulty_start/end=0`.
- 주의: fixture 레벨은 `bot_clear_rates` 가 없어 BatchVerifyPanel 의 "미검증 레벨" 목록에 나타남 — **[배치 검증]·[검증+재생성]은 봇 실행이므로 누르지 말 것.** [중앙정렬]은 봇 없음이나 레벨 데이터 변경(fixture 에서만).

### 다음 검증 턴 기동 명령 (지금 실행 안 함 — 별도 승인 턴에서)
(a) 백엔드 `:8001` (메인 venv, 워크트리 코드·워크트리 `data/`):
```
cd /Users/casualdev/TileMatchAutoLevel_wt_clearrate/backend && \
nohup /Users/casualdev/TileMatchAutoLevel/backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 \
  > /tmp/wt_clearrate_backend.log 2>&1 &  echo "backend PID $!"
curl -s 127.0.0.1:8001/api/production/batches   # fixture 2개만 보여야 함(봇 없음, 목록 조회)
```
(`--reload` 없음. `requirements.txt` 메인=워크트리 동일 — 앞 절 기록.)

(b) 프런트 `:5174` — 임시 설정 `/tmp/wt_clearrate_vite.config.ts` 전체 내용:
```ts
import { defineConfig, mergeConfig } from 'vite'
import base from '/Users/casualdev/TileMatchAutoLevel_wt_clearrate/frontend/vite.config.ts'

export default mergeConfig(base, defineConfig({
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
}))
```
실행(앞 절과 같은 이유로 `/tmp` 설정의 모듈 해석을 위해 `NODE_PATH` 지정):
```
cd /Users/casualdev/TileMatchAutoLevel_wt_clearrate/frontend && \
NODE_PATH=$PWD/node_modules nohup npx vite --config /tmp/wt_clearrate_vite.config.ts \
  > /tmp/wt_clearrate_frontend.log 2>&1 &  echo "frontend PID $!"
curl -s -o /dev/null -w '%{http_code}\n' localhost:5174/            # 200
curl -s localhost:5174/api/production/batches                       # (a)와 같은 응답 = proxy→8001 확인
```
`mergeConfig` 는 `server.proxy['/api']` 객체를 병합 → target 만 8001 로 바뀜(원 설정 8000 덮어씀). **기동 직후 반드시 위 두 번째 curl 로 8001 경유를 확인**한 뒤 브라우저를 연다.

(c) 종료(PID 기준, 기동 때 출력한 PID):
```
kill <backend PID>; kill <frontend PID>          # npx 래퍼면 자식 vite node 도: pgrep -f "vite --config /tmp/wt_clearrate_vite" | xargs kill
lsof -nP -iTCP:8001 -sTCP:LISTEN; lsof -nP -iTCP:5174 -sTCP:LISTEN   # 출력 없음 확인
rm -f /tmp/wt_clearrate_vite.config.ts /tmp/wt_clearrate_backend.log /tmp/wt_clearrate_frontend.log
```
메인 `:8000`/`:5173` 프로세스는 건드리지 않는다.

### 브라우저 주의 (필수)
- **반드시 `http://localhost:5174` + 새(빈) 브라우저 프로필.** 대시보드 마운트 시 `pushLocalMissingToServer` 가 그 프로필 IndexedDB 의 로컬 배치를 연결된 서버로 강제 업로드한다. `:5173`(운영 origin)을 열거나 기존 프로필로 `:5174` 를 열면 다른 배치가 `:8001` 저장소로 복사될 수 있고, 반대로 `:5174` 가 `:8000` 으로 프록시되면 fixture·검증 결과가 운영 저장소에 섞인다.
- 새 프로필 `:5174` 첫 진입 → pull 로 fixture 2개가 로컬 IndexedDB(`localhost:5174` origin)에 생김 → 생산 대시보드 배치 선택에서 `[FIXTURE] …` 선택 → 검증 탭.
- 위험 버튼(앞 절 표) 금지. C [실행]은 별도 승인 전 금지.

### 정리(삭제) 방법
1. 서버 종료(위 c).
2. fixture·push 사본 삭제: `rm -r /Users/casualdev/TileMatchAutoLevel_wt_clearrate/backend/data/production`(이번에 새로 만든 디렉터리 — 이 안에는 fixture 2개와 실행 중 생긴 `_index.json`·push 사본만 있어야 함, 지우기 전 `ls` 로 확인). C 를 실행했다면 `backend/data/clear_rate_verify/{jobs,measurements}.json` 도 확인 후 삭제(현재 없음).
3. 테스트 브라우저 프로필 삭제(또는 `localhost:5174` origin 의 IndexedDB `TileMatchProduction`·`TileMatchClearRateVerify` 삭제).
4. 메인 트리 `backend/data/production`·`:5173` IndexedDB 는 손대지 않음.

---

## 이번 작업 — 실제 UI 발견 2건 국소 수정 (2026-10-16 22:10 Codex 지시, 하위세션 "정적감사")

> Codex 실제 UI 검증(8001/5174 격리)에서 발견된 문제의 **코드 수정만**. 수정 후 실제 UI 검증은 **별도(미실시)**. 서버·브라우저·tsc·테스트 실행 0회(테스트 작성만). 위 Codex 기록·문서 38 상단 미커밋분은 건드리지 않음(이 절은 파일 끝에 추가만). 착수 전 `git status`: `ProductionDashboard/index.tsx` clean 확인.

### 1. 새 프로필 첫 동기화 직후 셀렉터에는 fixture 가 보이나 본문이 빔
- 원인: 로컬 배치 0개 → 초기 선택 `null`. 백그라운드 `syncBidirectional` 후 `setBatches` 만 하고 선택은 그대로 → 셀렉터 `value=''` 에 해당 option 이 없어 브라우저가 첫 항목을 표시(상태는 null, 본문은 `selectedBatchId &&` 조건으로 미렌더). 같은 항목 재선택은 onChange 가 없어 복구 안 됨.
- 수정:
  - `frontend/src/components/ProductionDashboard/batchSelection.ts`(신규): `latestBatchId`, `pickSelectedBatchId(cur, batches)` — 현재 선택이 목록에 있으면 보존, 없을 때만 created_at 최신(없으면 null).
  - `ProductionDashboard/index.tsx:59` import, `:1026` `let cancelled`, `:1047-1052` 동기화 후 `if (cancelled) return; setBatches(bs); setSelectedBatchId(cur => pickSelectedBatchId(cur, bs))`(함수형 — 그사이 사용자가 고른 배치 보존), `:1063` effect cleanup `cancelled = true`(언마운트 뒤 늦은 응답 무시), `:2349` 선택 없음일 때 `<option value="" disabled>배치 선택</option>`.
- 재검증: 새 프로필 `:5174`+`:8001`(fixture 만) 첫 진입 → 동기화 알림 뒤 **새로고침 없이** 최신 fixture 가 선택되고 본문 표시 / 동기화 전에 다른 배치를 고른 경우 선택 유지 / 로컬·서버 모두 0개면 셀렉터 "배치 선택"·본문 없음.

### 2. 목표 미리보기 "현 모델로 신뢰 판정: 가능" 과장
- 원인: 칸은 `/verify/target-check` 의 `judgeable`(= `user_expected_precheck` 코드 없음: 배치 위치 학습 범위·목표 0.85 이상·구간 학습 p5~p95)만 반영. 측정 후 예측 구간 신뢰도 게이트(`guard.reliability_flags`)는 반영 안 됨 → "신뢰 판정 가능"은 과장.
- 수정(문구만, API·스키마·모델·판정식 변경 없음, 모델 수치 하드코딩 없음):
  - `ClearRate/clearRateLabels.ts:60-70` `TARGET_SUPPORT_HEADER='현 모델 입력 지원 범위'`, `TARGET_SUPPORT_NOTE`(입력 지원 범위 통과는 합격·높은 신뢰도를 보장하지 않음, 실제 판정은 측정 결과와 현재 모델 신뢰도 기준을 함께 확인), `targetSupportText()` → `미확인`/`범위 안`/`범위 밖(사유)`.
  - `ClearRate/ClearRateVerifySection.tsx:29` import, `:429` 미리보기 고정 안내(`cr-target-support-note`), `:432` 헤더, `:442` 칸.
- 재검증: 미리보기에서 88% 등 입력 → 헤더 "현 모델 입력 지원 범위", 칸 "범위 안", 안내 문구 표시 / 85% 미만 → "범위 밖(신뢰 낮음)".

### 작성한 테스트 (미실행)
- `frontend/tests/batchSelection.test.ts`(신규, 4건): 최신 선택·빈 목록 null / 새 프로필 첫 pull → 최신 / 현재 선택 보존 / 목록에 없으면 최신·빈 목록 null.
- `frontend/tests/clearRateLabels.test.ts`(1건 추가): 헤더·칸 문구, "신뢰/가능/합격" 미사용, 안내에 숫자 없음.
- 실행 명령(승인 시): `cd frontend && node --experimental-strip-types --test tests/batchSelection.test.ts tests/clearRateLabels.test.ts` (둘 다 runtime import 순수 모듈뿐 — `batchSelection.ts` import 없음, `clearRateLabels.ts` type-only import).
- 남은 위험: `index.tsx` 는 확인된 시점(메인 HEAD `329a1a0`, 문서 38 §13)의 메인 커밋과 이 브랜치가 분기한 상태 — 병합 시 이번 5곳 충돌 확인 필요. (정정 2026-10-16 22:40: 현시점 메인 작업트리의 실제 `git status` 는 이번에 읽지 않았으므로 미커밋 여부·clean 여부를 단정하지 않음.) 타입 검사 미실행.

---

## 최종 상태표 (2026-10-16 22:40 작성 · 23:42 Codex UI 확인 결과로 갱신 — 문서 정리만, 실행·코딩 없음)

**상태 구분: 경량 검증 부분 완료 — 전체 목표 완료 아님.**

| 구분 | 항목 | 근거·조건 |
|---|---|---|
| 실제 UI PASS | 목표 곡선 저장·복원(구간·주기·개별 → 미리보기 → 적용 → 새로고침·재진입 복원) | Codex 브라우저(IAB), `:8001`/`:5174` 격리, fixture(`codex_ui_fixture_20261016_a/_empty`)만 |
| 실제 UI PASS | 정상 배치 전환(빈 배치 ↔ 원배치, 행 없음 → 복원) | 같은 조건 |
| 순수 함수 PASS | `frontend/tests/clearRateVerifyModel.test.ts` 14/14 | B3·F1·G1 수정 반영본(`413154e`) 기준, 20:39 1회 실행 |
| 실제 UI PASS | 최신 `3b50d17` 최초 배치 선택(fixture pull 후 선택 조작·새로고침 없이 `fixture_a` 본문 표시) · 미리보기 문구("현 모델 입력 지원 범위"·"범위 안"·합격/고신뢰 보장 아님 안내, L237~239 88%) | 2026-10-16 23:42 Codex, `localhost:5174` 별도 origin + `:8001` fixture. 요청은 GET + target-check POST 1회, 봇·C 실행 0 |
| 순수 함수 PASS | `tests/batchSelection.test.ts` + `tests/clearRateLabels.test.ts` 14/14 | 23:09 1회 실행 |
| 미검증 | 실제 C 측정 기록·서버 재시작 복구 | 봇 측정 필요(별도 승인) |
| 미검증 | F1 버전 조회 실패 표시(실UI) | 브라우저에서 `/verify/info` 차단 필요 |
| 미검증 | G1 같은 배치 맵 변경 후 다시 읽기·무효화(실UI) | fixture 에서 중앙정렬 변경 발생 여부 불확실 |
| 미검증 | 비동기 경합(배치 전환·맵 갱신 중 늦은 응답) 실UI | 정적 검토·코드 수정만 |

### 다음 자원 안정 후 최소 순서 — **완료**(1단계 23:09 단위 테스트 14/14 · 2단계 23:42 Codex 실제 UI PASS)
각 단계 전후로 시각·`memory_pressure` 요약·`sysctl vm.swapusage` 기록, 압박 악화(스왑 지속 증가·경고 상승·응답 저하) 시 즉시 중단.
1. ✅ 최신 2파일 단위 테스트 1회: `cd TileMatchAutoLevel_wt_clearrate/frontend && node --experimental-strip-types --test tests/batchSelection.test.ts tests/clearRateLabels.test.ts` (실행 전 runtime import 순수 여부 재확인).
2. ✅ `:5174` 새 프로필 + `:8001` fixture 로 첫 진입 배치 선택(새로고침 없이 본문 표시)·미리보기 문구("현 모델 입력 지원 범위"/"범위 안"/안내) UI 재검증 1회. 기동·종료 명령은 위 "서버 측 UI fixture 준비" 절. → 23:42 Codex PASS, 서버·탭 종료·포트 비어 있음, swap 52948.56→52940.56M·압박 2 유지(Codex 기록)

### 38 상단 '최신 인계'(사용자 미커밋 — 수정 안 함) 갱신 필요 항목
- "남은 한계" 의 "실제 UI 저장 복원은 아직 검증하지 않았다" → 부분 갱신 필요: 목표 곡선 저장·복원, 배치 전환, 최초 배치 선택, 미리보기 문구는 fixture 격리 환경 실제 UI PASS(38b 최종 상태표). 판정 기록·C 작업 참조 복원, 실제 C 실행·취소·서버 복구는 여전히 미검증.
- "이번 기록 작업에서는 실행 검증을 하지 않았다"·경량 검증 범위 1~7 은 19시 시점 계획 — 이후 실행분(단위 테스트 2회, Codex 실제 UI 2회)은 38b 참조로 연결 필요.
- 미리보기 칸 의미 변경("신뢰 판정 가능" → "입력 지원 범위", `3b50d17`)이 §11 [미리보기] 설명("현 모델로 신뢰 판정: 가능/불가")과 다름 → §11 문구도 맞출 필요(38 본문은 상단 미커밋과 같은 파일이라 이번에 수정 안 함).

---

## 최소 계획 1단계 — 최신 2파일 단위 테스트 1회 (2026-10-16 23:09 KST, Codex 23:09 지시)

> **순수 함수 단위 테스트 PASS ≠ UI PASS.** 초기 배치 선택(동기화 후 화면 반영)·미리보기 문구 화면 표시는 2단계(5174 새 프로필 + 8001 fixture) 전까지 **미검증**.

- 실행 전 runtime import 확인: `tests/batchSelection.test.ts` → `node:test`, `node:assert/strict`, `src/components/ProductionDashboard/batchSelection.ts`(import 없음). `tests/clearRateLabels.test.ts` → `node:test`, `node:assert/strict`, `src/components/ClearRate/clearRateLabels.ts`(`api/clearRateTarget` 은 **type-only**). 네트워크·IndexedDB·타이머·서버·봇 경로 0건.
- 명령(1회): `cd TileMatchAutoLevel_wt_clearrate/frontend && node --experimental-strip-types --test tests/batchSelection.test.ts tests/clearRateLabels.test.ts`
- 결과: **14/14 PASS, fail 0**, exit 0, 120ms (batchSelection 4건 + clearRateLabels 10건 — 기존 9 + 이번 문구 1).
- 자원: 전 23:09:38 — free% 36, swap used 53105.00M / 54272M (free 1167.00M) · 후 23:09:38 — 동일. 변화 없음.
- `clearRateVerifyModel.test.ts` 재실행·전체 테스트·tsc·빌드·서버·브라우저·봇 없음.

## 최소 계획 2단계 — 실제 UI 재확인 (2026-10-16 23:38~23:42 KST, Codex)

- `3b50d17` 기준, worktree 전용 8001/5174와 기존 fixture 두 개만 사용. 이전 `127.0.0.1:5174`와 저장소가 분리되는 `localhost:5174` origin으로 확인(새 브라우저 프로필로 표현하지 않음).
- **실제 UI PASS:** 최초 프로덕션 진입·서버 fixture 동기화 후 선택 조작/새로고침 없이 fixture_a가 선택되고 본문 3개 레벨 표시. 이전 선택/본문 불일치 재현되지 않음.
- **실제 UI PASS:** 검증 탭에서 L237~239 목표 88% 미리보기 → 헤더 `현 모델 입력 지원 범위`, 각 행 `범위 안`, 합격·높은 신뢰도를 보장하지 않는다는 고정 안내 확인. 적용 버튼은 누르지 않음.
- 접근 로그: GET(배치 목록/fixture/health/verify info)와 `POST /api/clear-rate/verify/target-check` 1회뿐. 신규 봇·C 실행 요청 0건. 생성/중앙정렬/서버 저장 미실행.
- 테스트 탭 종료, 직접 기동한 backend PID 67750/frontend PID 67777 종료. 메인 8000/5173 미변경.
- 자원: 시작 swap used 52948.56M → 종료 직후 52940.56M, 압박 수준 2 유지. 자원 완전 정상화 판정은 하지 않음.
- 위 이전 상태표의 `3b50d17 작성만·미실행`은 이 기록 및 23:09 순수 함수 PASS로 대체. 기존 C 실측/서버 복구, F1 실패 실UI, G1 변경 실UI, 비동기 경합은 여전히 미검증. 이번 확인 항목은 반복 실행하지 않음.

---

## 남은 미검증 재개 준비 — F1·G1·비동기 경합 (2026-10-18 11:15~ KST, 사용자 추가 승인, 기한 10-18 23:00)

> 이 세션에는 브라우저 제어 도구가 없다 → **실제 UI 단계는 전부 Codex 브라우저 몫.** 여기서는 조사(읽기)·준비물·절차서만. 서버 기동·테스트 실행·API 호출·봇·C 0회. 커밋 안 함.

### 0. 자원·프로세스 (11:15:38 KST)
- `memory_pressure`: free 36% · `kern.memorystatus_vm_pressure_level` = 2(경고, 이전과 같음) · swap used 54744.25M / 55296M (**free 551.75M** — 10-16 23:09 의 1167M 대비 절반 이하) · `df -h /` 여유 49Gi(25%).
- 판단: 압박 단계는 그대로지만 스왑 여유가 크게 줄어 **새 실행 없이 문서·파일 준비만**(신규 테스트 실행도 보류). Codex 기동 전 재측정 권장 — swap free 500M 미만이거나 압박 3 이면 기동 보류.
- LISTEN: `:5173` node 34901, `:8000` Python 39400/90754(메인 — 손대지 않음). **`:8001`·`:5174` 없음**(이전 Codex 기동분 종료 확인, 중복 기동 없음).

### 1. 주입 방법 조사 (읽기만)
| 방법 | 가능 | 범위·위험 |
|---|---|---|
| (a) 프런트 기존 훅/환경 변수 | 부적합 | `api/client.ts:4` `VITE_API_URL`(전체 base 교체뿐), `:16-21` localStorage `remote_compute_url`(무거운 경로를 **원격으로 우회** — 새 프로필에서 비어 있는지 확인 필요, 주입 수단으로 쓰면 안 됨). 경로별 실패·지연 훅 없음 |
| (b) `/tmp` vite 설정 플러그인 미들웨어 | **채택** | `configureServer` 에서 직접 `server.middlewares.use` 한 미들웨어는 vite 내부 미들웨어(프록시 포함)보다 먼저 실행 → 저장소 파일 수정 없이 `/api/*` 경로별 지연·500·403·응답 변조 가능. **비-GET 은 허용 목록 외 전부 403**(봇·C 작업 생성·생성·검증·RL·튜닝 차단), GET 은 `measure` 포함 경로 403. 런타임 토글은 브라우저로 `http://localhost:5174/__fault?...` 열기. 위험: axios 타임아웃 30s(`client.ts:12`) — 지연은 30s 미만으로(넘기면 타임아웃 오류 경로가 됨) |
| (c) 8001 앞단 별도 지연 프록시 | 가능하나 불필요 | 프로세스 1개 추가(메모리), (b)와 기능 동일 |

- **F1**: (b)로 `/api/clear-rate/verify/info` 만 500 또는 지연. 녹색 "합격" 오표시 차단을 실제로 보려면 PASS 기록이 필요하나 C 실행 금지 → 선택적 **mock**: (b)가 `/api/clear-rate/target-eval` 응답의 `user_expected.verdict.verdict` 를 `PASS` 로 바꿔 돌려줌(사유 앞에 `[MOCK PASS …]`) → 탐색 기록이 PASS 로 저장(테스트 프로필 IndexedDB 에만). 이 단계 결과는 **mock 검증**으로 구분.
- **G1**: 봇·생성 없이 맵을 바꾸는 UI 경로 = BatchVerifyPanel [중앙정렬](`BVP:525-546` → `POST /api/analyze/fix-centering`, `routes/analyze.py:1389`, 봇 없음·레벨 변경). 정적 확인 결과 **L237 골든(fixture_a)은 `"layer": "3"`(문자열) → `_calc_visual_center_diff`(`analyze.py:1285-1287` `range(num_layers)`) 에서 TypeError → 500 예상** → fixture_a 로는 맵 변경 불가(그래도 `finally` 에서 `levelsRevision+1` → "맵 확인 중 → 다시 읽기" 경로는 탐). → G1 전용 fixture 를 새로 둠(아래). 정수 layer 로 보면 layer_2 시각 중심 4.0 vs layer_0 3.0 → `_fix_visual_centering`(`generator.py:14276~`)이 layer_2 를 1칸 이동할 것으로 정적 계산(실행 확인 아님). [재생성]·[배치 검증]은 생성/봇 → 금지(프록시도 403).
- **경합**: (b)로 특정 경로만 지연(예: `target-eval`·`verify/plan`·`verify/info` 8~15s) → 지연 중 배치 전환·중앙정렬 → 늦은 응답이 새 화면에 쓰이는지 확인.

### 2. 순수 함수·mock 범위 정리 (재실행 없음)
- 이미 검증(10-16 20:39, `clearRateVerifyModel.test.ts` 14/14): 버전 null → `unconfirmed`(4조합) · 맵 미확인(mapHash null) → `unconfirmed`/완료 작업 `checking` · `unconfirmed` 배지 회색·"확인 불가:" · 버전 null 상태의 assess→display 회색 연결.
- 컴포넌트 세대 경계(`gen`/`mapEpoch`)·레벨 다시 읽기는 React/DOM 필요 → 순수 함수로 더 뺄 부분 없음 → **신규 테스트 작성 없음**(자원 판단상 실행도 보류).

### 3. 준비물
**3-1. G1 fixture (생성함, 미추적 — `git status --ignored` → `!! backend/data/production/`)**
`TileMatchAutoLevel_wt_clearrate/backend/data/production/codex_ui_fixture_20261018_g1.json` — id `codex_ui_fixture_20261018_g1`, 이름 `[FIXTURE] codex_ui_20261018_g1 — L237 골든(layer 정수화) 1레벨, 중앙정렬 G1용`, L237 1레벨. 골든 `level_json` 에서 `"layer": "3"` → `3` 만 변경(타일·좌표 무변경), `fixture_note` 에 실제 레벨 아님·변경 내용 명시. 허위 측정·검증·보상 필드 없음, status `needs_rework`. 기존 fixture 2개·`_index.json` 은 그대로.

**3-2. 지연·실패 주입 + 위험 경로 차단 vite 설정** — `/tmp/wt_clearrate_vite.fault.config.ts` (Codex 가 heredoc 으로 생성; 이 세션은 만들지 않음):
```ts
import { defineConfig, mergeConfig, type Plugin } from 'vite'
import { appendFileSync } from 'node:fs'
import base from '/Users/casualdev/TileMatchAutoLevel_wt_clearrate/frontend/vite.config.ts'

const BACKEND = 'http://127.0.0.1:8001'
const LOG = '/tmp/wt_clearrate_fault.log'
// 비-GET 허용 목록 — 이 밖의 비-GET /api 는 전부 403 (봇·C 작업 생성·생성·검증·RL·튜닝·야간학습 등)
const ALLOW_WRITE: Array<[string, RegExp]> = [
  ['POST', /^\/api\/clear-rate\/(target-eval|predict)$/],
  ['POST', /^\/api\/clear-rate\/verify\/(plan|jobs\/query|evaluate|target-check)$/],
  ['POST', /^\/api\/analyze\/fix-centering$/],
  ['PUT', /^\/api\/production\/batches\/codex_ui_fixture_[A-Za-z0-9_]+$/],
]
const BLOCK_GET = /measure/i
const state = { info: 'off', delays: {} as Record<string, number>, mockPass: false }
const lines: string[] = []
const log = (s: string) => {
  const l = `${new Date().toISOString()} ${s}`
  lines.push(l); if (lines.length > 500) lines.shift()
  try { appendFileSync(LOG, l + '\n') } catch { /* ignore */ }
}
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))
const readBody = (req: any) => new Promise<Buffer>((ok, bad) => {
  const c: Buffer[] = []; req.on('data', (d: Buffer) => c.push(d)); req.on('end', () => ok(Buffer.concat(c))); req.on('error', bad)
})
const json = (res: any, status: number, body: unknown) => {
  res.statusCode = status; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(body, null, 2))
}

function fault(): Plugin {
  return {
    name: 'wt-clearrate-fault',
    configureServer(server) {
      // 직접 use → vite 내부 미들웨어(/api 프록시 포함)보다 먼저 실행
      server.middlewares.use(async (req: any, res: any, next: any) => {
        const url = new URL(req.url ?? '/', 'http://x')
        const path = url.pathname
        const m = String(req.method ?? 'GET').toUpperCase()
        if (path === '/__fault') {
          const q = url.searchParams
          if (q.has('reset')) { state.info = 'off'; state.delays = {}; state.mockPass = false }
          if (q.has('info')) state.info = q.get('info')!                    // off | 500 | delay:<ms>
          if (q.has('delay_path')) {                                         // 예: delay_path=/api/clear-rate/target-eval&ms=12000 (ms=0 해제)
            const p = q.get('delay_path')!, ms = Number(q.get('ms') ?? 0)
            if (ms > 0) state.delays[p] = ms; else delete state.delays[p]
          }
          if (q.has('mock_pass')) state.mockPass = q.get('mock_pass') === '1'
          log(`CONTROL ${url.search}`)
          return json(res, 200, { state, log: lines.slice(-80) })
        }
        if (!path.startsWith('/api/')) return next()
        const blocked = m === 'GET' ? BLOCK_GET.test(path) : !ALLOW_WRITE.some(([mm, re]) => mm === m && re.test(path))
        if (blocked) { log(`BLOCK403 ${m} ${path}`); return json(res, 403, { detail: 'blocked by wt-clearrate fault proxy' }) }
        const d = state.delays[path]
        if (d) { log(`DELAY ${d}ms ${m} ${path}`); await sleep(d) }
        if (path === '/api/clear-rate/verify/info' && state.info !== 'off') {
          if (state.info === '500') { log(`INFO500 ${m} ${path}`); return json(res, 500, { detail: 'injected failure (wt-clearrate fault proxy)' }) }
          if (state.info.startsWith('delay:')) { const ms = Number(state.info.slice(6)); log(`INFODELAY ${ms}ms`); await sleep(ms) }
        }
        if (state.mockPass && m === 'POST' && path === '/api/clear-rate/target-eval') {
          const body = await readBody(req)
          const r = await fetch(BACKEND + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
          const j: any = await r.json()
          if (j?.user_expected?.verdict) {
            j.user_expected.verdict.verdict = 'PASS'
            j.user_expected.verdict.reason = '[MOCK PASS — fault proxy, 실제 판정 아님] ' + j.user_expected.verdict.reason
          }
          log(`MOCKPASS ${r.status} ${path}`)
          return json(res, r.status, j)
        }
        log(`FWD ${m} ${path}`)
        next()
      })
    },
  }
}

export default mergeConfig(base, defineConfig({
  plugins: [fault()],
  server: { port: 5174, strictPort: true, proxy: { '/api': { target: BACKEND, changeOrigin: true } } },
}))
```
(이 세션에서 실행·문법 검사 안 함. 기동 실패 시 로그 `/tmp/wt_clearrate_frontend.log` 확인.)

### 4. Codex 절차서
**기동**(앞 "서버 측 UI fixture 준비" 절과 같되 설정 파일만 교체):
```
# 0) 자원 재측정: date; memory_pressure | grep percentage; sysctl vm.swapusage kern.memorystatus_vm_pressure_level
# 1) 백엔드 :8001
cd /Users/casualdev/TileMatchAutoLevel_wt_clearrate/backend && nohup /Users/casualdev/TileMatchAutoLevel/backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 > /tmp/wt_clearrate_backend.log 2>&1 & echo "backend PID $!"
curl -s 127.0.0.1:8001/api/production/batches     # fixture 3개(a, empty, g1)만
# 2) 위 3-2 내용을 /tmp/wt_clearrate_vite.fault.config.ts 로 저장 후 프런트 :5174
cd /Users/casualdev/TileMatchAutoLevel_wt_clearrate/frontend && NODE_PATH=$PWD/node_modules nohup npx vite --config /tmp/wt_clearrate_vite.fault.config.ts > /tmp/wt_clearrate_frontend.log 2>&1 & echo "frontend PID $!"
curl -s localhost:5174/api/production/batches     # (1)과 같음 = proxy→8001
curl -s localhost:5174/__fault                    # {"state":{"info":"off",...}}
curl -s -X POST localhost:5174/api/clear-rate/verify/jobs -o /dev/null -w '%{http_code}\n'   # 403 이어야 함(차단 확인, 백엔드 미도달)
```
브라우저: **새 프로필 `http://localhost:5174`** 만. 첫 진입 후 DevTools 없이도 확인 가능하도록 모든 판정은 화면 + `/__fault` 로그로 본다. 새 프로필의 localStorage `remote_compute_url` 은 비어 있어야 함(설정 화면에서 건드리지 말 것).

**F1 — 버전 조회 실패·지연** (실제 UI)
0. 사전: `__fault?reset=1` 상태에서 `fixture_a` 검증 탭 → 목표 곡선(예: 구간 237~239 95%) 적용 → [A 탐색 계산](봇 없음)으로 행 기록을 먼저 만든다(새 프로필엔 기록이 없음).
1. 탭: `localhost:5174/__fault?info=500` → 대시보드 새로고침 → `fixture_a` → 검증 탭.
2. 기대: `cr-info-error`("현재 모델·판정 기준 버전 조회 실패 … 회색 표시·합격 집계 제외") 표시. 기존 기록 행 판정은 "확인 불가: …" 회색, `cr-a-counts` 없음. 로그에 `INFO500`.
3. `__fault?info=delay:12000` → 새로고침 → 12초 동안 `cr-info-loading` + 회색 "확인 불가"; 이후 문구 사라지고 정상 표시. 로그 `INFODELAY`.
4. 판정: 2·3 화면대로면 **실제 UI PASS(F1 표시)**.
5. (선택, **mock 검증**) `__fault?info=off&mock_pass=1` → 목표 곡선 적용 상태에서 [A 탐색 계산] → 행이 초록 "합격"(MOCK) → `__fault?info=500&mock_pass=0` → 새로고침 → 같은 행이 회색 "확인 불가: 합격", `cr-a-counts` 에 합격 미집계. → 결과는 "mock PASS"로만 보고(실제 판정 아님). 끝나면 테스트 프로필 폐기(MOCK 기록이 남음).

**G1 — 같은 배치 맵 변경** (실제 UI)
1. `__fault?reset=1` → `fixture_g1`(1레벨 L237) → 검증 탭 → 목표 곡선(예: 구간 237~237 95%) 적용 → [A 탐색 계산](target-eval, 봇 없음) → 행에 기록 생김(현재 유효 또는 근거 부족).
2. 같은 화면 BatchVerifyPanel **[중앙정렬]** 클릭(봇 없음). 진행 중 섹션에 `cr-map-checking`("기존 배치 검증이 맵을 바꾸는 중"), A/B/C 버튼 비활성.
3. 완료 후 `centeringResult` "1개 중 1개 수정됨" 기대 → 섹션이 레벨을 다시 읽고 해당 행이 **"측정 무효(맵·조건 변경)"** + 회색 "과거: …". 로그: `FWD POST /api/analyze/fix-centering`, `FWD PUT /api/production/batches/codex_ui_fixture_20261018_g1`(자동 push, 워크트리 저장소).
4. 판정: 3이 맞으면 **실제 UI PASS(G1)**. "0개 수정됨"이거나 500 이면 맵 변경 없음 → G1 무효화 미검증 유지(단 2의 잠금·다시 읽기 문구가 보였으면 그 부분만 PASS로 기록). 정적 계산상 수정 1건 예상이나 실행 확인 아님.
5. (C 준비 계획 폐기) 1 다음 L237 체크 → [C 확인 측정 준비](plan, 봇 없음) → 확인 패널 표시 상태에서 [중앙정렬] → 패널이 사라지고 "C 준비 결과를 비움" 문구. **[실행]은 절대 누르지 말 것**(프록시 403 이지만 누르지 않음).

**비동기 경합** (실제 UI)
- R1 탐색 중 배치 전환: `__fault?reset=1&delay_path=/api/clear-rate/target-eval&ms=12000` → `fixture_a`(3레벨) 곡선 적용 → [A 탐색 계산] → 2초 안에 상단 셀렉터로 `fixture_empty` 전환 → 15초 대기 → `fixture_a` 복귀. 기대: empty 화면에 행·오류·진행 문구 없음, 로그상 target-eval **1건만**(남은 2레벨 요청 없음), 복귀 후 a 화면 정상(늦게 끝난 1건은 a 기록으로만 저장돼도 됨).
- R2 C 준비 응답 중 전환: `delay_path=/api/clear-rate/verify/plan&ms=12000` → a 에서 레벨 선택 → [C 확인 측정 준비] → 전환(empty) → 15초 → 기대: empty 에 확인 패널 없음, a 복귀 시에도 패널 없음(새 마운트).
- R3 C 준비 응답 중 맵 갱신: g1 에서 `delay_path=/api/clear-rate/verify/plan&ms=12000` → [C 확인 측정 준비] → 곧바로 [중앙정렬] → 기대: plan 응답이 와도 패널 안 뜸 + "C 준비 결과를 비움" 문구.
- R4 버전 지연 중 전환: `info=delay:12000` → a → 즉시 empty → 기대: empty 에 오류·잔상 없음.
- 판정: 각 기대대로면 해당 R* **실제 UI PASS**. 하나라도 이전 배치 데이터가 새 화면에 보이면 FAIL — 화면·로그 캡처 후 보고.

**종료·정리**
```
kill <backend PID> <frontend PID>; pgrep -f "vite --config /tmp/wt_clearrate_vite.fault" | xargs kill 2>/dev/null
lsof -nP -iTCP:8001 -sTCP:LISTEN; lsof -nP -iTCP:5174 -sTCP:LISTEN     # 출력 없음
cp /tmp/wt_clearrate_fault.log <기록 위치>   # 필요 시 38b 요약용
rm -f /tmp/wt_clearrate_vite.fault.config.ts /tmp/wt_clearrate_fault.log /tmp/wt_clearrate_backend.log /tmp/wt_clearrate_frontend.log
# 테스트 브라우저 프로필 삭제(MOCK 기록 포함). fixture 정리는 앞 절 방법(워크트리 backend/data/production 전체 삭제) — 이후 검증 계속하면 보존
```

### 5. 코드 읽기로 발견한 것 (수정 안 함, 보고만)
- `POST /api/analyze/fix-centering`(`analyze.py:1285-1287` `_calc_visual_center_diff`, `generator.py:14285-14286` `num_layers < 2`)는 `level["layer"]` 가 **문자열이면 TypeError → 500**. 생산 레벨(에디터 형식)은 정수라 운영 영향은 확인 안 됨, 게임 빌드 형식(골든)에서만 재현 예상. 이번 범위(검증 탭) 밖 → 수정하지 않고 기록만. fixture_g1 은 이 때문에 정수 layer 로 둠.
- 검증 탭 섹션 쪽 신규 결함은 이번 읽기에서 찾지 못함.

### 이번 단계 실행·호출 내역
서버 기동 0 · API 호출 0 · 봇 0 · C 0 · 테스트 실행 0 · 커밋 0. 실행한 것은 자원/포트 조회와 골든 JSON 읽기·fixture 파일 1개 쓰기(python 표준 라이브러리, 앱 모듈 import 없음)뿐.

## 2026-10-19 Codex 경량 UI 재개 (10:18~10:22 KST)

- 사용자 재승인으로 8001/5174만 실행. `/tmp/codex-cr-20261019.config.mts` 허용 목록 프록시 사용. 봇·생성·C 작업 제출 경로는 차단하고 호출하지 않음. 실제 봇 측정 0, C 준비 API만 사용. 게임·모델·판정 코드 변경 없음.
- 실제 UI PASS(F1 부분): verify/info 500 및 12초 지연 주입 시 기존 캐시 판정이 `확인 불가: 근거 부족`로 표시. 오류/로딩 안내 확인. 기존 PASS를 회색으로 바꾸는 mock PASS 시험은 미실시. 지연 후 정상 복원 단독 시험도 미완료.
- 실제 UI PASS(R1 부분): fixture_g1의 target-eval을 12초 지연하고 빈 배치로 전환. 늦은 응답 후 빈 배치에 레벨 행이 생기지 않음. 다중 레벨 후속 요청 중단 시험은 미실시(1레벨 사용).
- 실제 UI PASS(R2): C plan을 12초 지연하고 빈 배치 전환. 응답 후 빈 배치 및 원래 배치 재진입에 C 실행 전 확인 패널이 남지 않음. C 실행 버튼은 누르지 않음.
- 실제 UI PASS(G1): fixture_g1 목표 95% 적용·캐시 탐색 결과 생성·C 준비 패널 표시 후 중앙정렬. `전체 1개 중 1개 수정됨`, `측정 무효(맵·조건 변경)`, `C 준비 결과를 비움` 확인. 변경은 테스트 fixture/로컬 UI 저장에만 한정. 기존 fixture는 삭제하지 않음.
- R3(지연된 plan 중 맵 갱신), R4(버전 지연 중 배치 전환), 실제 C 실측·서버 재시작 복구는 미검증 유지. 전체 경량 QA 완료로 보지 않음.
- 실행 중 자원: 압박 1, swap used 22367.50 → 22271.50M. 앞선 경고 2 상태와 달리 이 실행에서는 정상 단계 확인. 재부팅/프로세스 강제 정리 수행 없음.
- 초기 임시 Vite `.ts` 설정은 ESM 로딩 실패하여 `.mts`로 수정 후 기동. 전체 빌드·tsc·신규 테스트·커밋·푸시 없음.

## 2026-10-19 P5 — 활성 bot_cache 8개 측정 격리 (미커밋)

- 원인: 문서 42(메인) §3. L429·433·441·466·479·493·494·499 캐시 행이 행동 항목을 켠 봇 측정인데 라벨은 v2.4/`theta4x128_v1`/`seed11M`이다. 그래서 G3로 걸리지 않고 `/predict`·검증 탭 캐시 판정에 수치가 나왔다(변경 전 7/8은 `ok`, 예측값 표시).
- 격리 키: 모델 `cr-ftany-v24r-20261016` + 봇 v2.4/`theta4x128_v1` + `cond_hash`(맵+조건) + 측정 행 sha256. 레벨 번호와 `seed_band`는 키에 넣지 않았다. 근거: `protocol_review.json` sha256 `edab9428…`.
- 적용 위치: `guard.bot_flags` 1곳 → `/predict`와 `/target-eval use_cached_measurement` 공통. 새 hard 코드는 `BOT_CACHE_CONDITION_MISMATCH`("측정 조건 불일치 → 근거 부족")이다. 수치·봇 승률을 내지 않으며, 자동 측정·C로 넘어가지 않는다.
- 변경: `guard.py` 9–10·21·23–63·101–103, `predict.py` 115–117, `clearRateLabels.ts` 19, `api/clearRate.ts` 17–18, `frontend/tests/clearRateLabels.test.ts` +1. 신규 파일: `backend/tests/test_clear_rate_p5_quarantine.py`, `backend/tests/golden/clear_rate_p5_quarantine.json`.
- 경량 검증(봇·measure·C 경로를 호출 시 실패하게 패치): P5 테스트 24 passed. 기존 캐시 API 테스트 3 passed. 라벨 테스트 11/11. 정상 5맵은 변경 전 응답과 바이트 동일. 봇 0, 재학습 0. 활성 모델 4파일 sha256 불변. 압박 2, 스왑 여유 588→836MB.
- 미검증: tsc·빌드·전체 테스트·UI 표시.
