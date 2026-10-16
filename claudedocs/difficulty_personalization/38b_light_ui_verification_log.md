# 38b. 검증 탭 2차 구현 — 경량 검증 로그 (하위세션 "경량검증", 2026-10-16~)

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
