# 프론트엔드 자원 점검 (정적, 2026-11-06)
범위: frontend/src 읽기만. 빌드·실행 안 함. [정적]=코드에서 확인, [추정]=코드로 추정(미측정).

## 우선순위
| # | 항목 | 위치 | 근거 | 개선 | 난이도/위험 |
|---|---|---|---|---|---|
| 1 | 라운드마다 배치 전체(1,500) getAll | index.tsx:5451 (순차검증 라운드당 1회, 최대 10회) | [정적] index.getAll(batchId)로 level_json 전부 복제 | 미통과 번호만 getProductionLevelsByNumbers(이미 있음) | 낮음/낮음 |
| 2 | calculateProductionStats = 전체 로드 | productionStorage.ts:635-636; 호출 onStatsUpdate 23곳(index.tsx), 2599·2614·2632·1072 | [정적] 통계에 meta만 필요한데 level_json 포함 1500개 로드. 탭/배치 변경·저장 후마다 | meta 전용 커서/별도 스토어(meta만) 또는 openKeyCursor+ meta 인덱스; 호출 디바운스 | 중/중(스키마) — 디바운스만이면 낮음 |
| 3 | 생성 중 5초 폴링 loadLevels | index.tsx:4685-4692, 4834-4845 | [정적] 5초마다 getAll(≤2000)+setLevels(1500 배열)→1500행 리스트 전체 리렌더. 가드는 isAutoTesting/isPlaying뿐 | 변경된 번호만 갱신(onLevelsWritten 구독) 또는 15~30초+탭 hidden 시 중지 | 중/낮음 |
| 4 | 1,500행 리스트 비가상화 + 거대 컴포넌트 | index.tsx:8920 filteredLevels.map, 10801 levels.map; useMemo/memo 5개뿐(11,257줄) | [정적] content-visibility:auto 로 페인트만 완화, React 렌더 비용은 그대로. 주석상 react-virtual 은 충돌로 배제됨 | 행 컴포넌트 React.memo + props 안정화(가장 안전). 가상화는 충돌 이력 있어 신중 | 중/중 |
| 5 | production 탭 상시 마운트 | App.tsx:444 display:none (activeTab!=='production' 이어도 마운트 유지) | [정적] 숨겨도 effect·상태 갱신·리렌더 계속. 다른 탭 보는 동안 순차검증 상태 갱신이 숨은 트리의 렌더 유발 | 의도(검증 지속)일 수 있음 — 숨김 시 렌더 억제만(진행 상태 ref 화) | 중/중 |
| 6 | 요청 동시성 상수 고정 | index.tsx:5091-5092(검증2/재생성8), 1352(생성 8/10), 5778(테스트 10), 6659(재생성 20) | [정적] 파이썬 CPU 기준 하드코딩. 서버 처리량 조정 불가 | 서버 능력(헬스/설정)에서 받아 동적 | 낮음/중(과부하) |
| 7 | 요청마다 console.log | api/client.ts:29-33 (/generate 제외 전부 로그) | [정적] 장시간 devtools 열면 로그 보관으로 메모리 증가. 검증 /rl-sim 호출 전부 해당 | 프로덕션/장시간 시 억제 플래그 | 낮음/낮음 |
| 8 | 번들 1.4MB 단일 | dist/assets/index-*.js 1,407,647B(6/25 빌드); App.tsx 정적 import 다수(lazy는 LevelShapes 1개) | [정적] 최신 빌드 아님. recharts·html-to-image 포함 | 탭 단위 lazy | 낮음/낮음 |

## 확인 결과 (우려했던 것)
- 전량 push 2곳: index.tsx:1132(배치 '확장' 버튼 1회), :2035(전체 생성 완료 직후 1회), :2484(수동 버튼). 모두 1회성 → 비용 낮음 [정적]. 자동 경로는 델타(productionServerSync.ts:96-118)·dirty 없으면 no-op.
- 타이머 정리: NightStudyPanel:66, HurdleRangeRec:108, GenerationProgress:35, 4687 모두 cleanup 있음 [정적]. 누수 없음. NightStudy 5초 폴링은 open 일 때만, Hurdle 2초는 running 일 때만. GenerationProgress 100ms 는 generating 일 때 해당 컴포넌트만 리렌더.
- 누수 후보: knownVersions/dirtyLevels/pushTimers (productionServerSync.ts:46,64,263) — 키는 배치 ID, 레벨 번호는 Set 이라 최대 1,500·배치 수로 유한. 배치 삭제 시 정리 코드 없음(미미). 알림: uiStore.ts:127 최대 5개 상한. _writeListeners 는 등록 1회(registerAutoSync 가드).
- 라운드당 localStorage CURSOR 저장(5460): passed 배열 JSON ≤1500 숫자, 무시 가능.

## C# 전환 후 새 병목 (추정)
- 현재 측정 1건 수 초(예 3~8초)/동시 2 → 초당 ~0.3-0.7건. C# 10~50배면 초당 5~30건, 즉 VERIFY_CONCURRENCY=2 가 상한이 되면 (건당 0.1~0.2초 가정 시 RTT·직렬 await 구조가 지배) 처리량이 서버가 아니라 프론트 왕복에 묶인다. 동시성 상향 또는 서버 배치 엔드포인트 필요.
- 건당 saveProductionLevels(5319 부근, 단건 IDB 트랜잭션+level_json 구조적 복제): 초당 5~30 트랜잭션 → 쓰기 배치화(예: 250ms 묶음) 필요.
- 디바운스 push(4초, productionServerSync.ts:295)는 쓰기가 계속되면 리셋되어 검증 끝날 때까지 안 나감 → 그동안 dirty 가 1,500까지 쌓였다가 한 번에 PUT(≈ 전량 5MB). 데이터 안전성(중간 크래시 시 서버 미반영) 문제. maxWait(예 30~60초) 필요.
- flushMeta(500ms) 마다 setLevels(prev.map 1500) + 1500행 리렌더: 빈도는 고정 2Hz 지만 C# 후엔 매번 대량 패치 → 렌더 비용이 CPU 상위로.
- 라운드 수: 라운드 전환 getAll(#1) 빈도는 변하지 않으나 라운드 자체가 짧아져 상대 비중 증가.
- console.log(#7) 초당 수십 건 → 로그 폭증.

## 바로 고쳐도 위험 낮음
#1(5451 번호 지정 로드), #7(로그 억제), #8(lazy), push maxWait 추가, 폴링 주기 완화(#3 주기만), 통계 호출 디바운스.
## 신중
#2 스키마(meta 분리), #4 가상화(과거 충돌), #5 숨김 탭 렌더 억제(검증 지속 보장 확인 필요), #6 동시성(서버 과부하 — 백엔드 세션 결과와 같이 결정).
## 미확인
실행 시 실제 메모리/렌더 프로파일, onStatsUpdate 23곳 각각의 호출 빈도, 5319 이후 measureOneLevel 의 추가 저장·네트워크 호출 전수, RLSimulationPanel/SolvabilityPanel/기타 패널(getAll 12곳 이상, 전부 사용자 클릭형으로 보임) 세부, 최신 번들 크기.
