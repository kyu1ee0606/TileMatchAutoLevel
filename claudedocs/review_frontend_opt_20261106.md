# 프론트 최적화 정적 리뷰

대상: `3d178b6`. 줄 번호는 이 커밋 기준. 본 저장소 Git 객체만 읽었으며 worktree 접근, tsc, 브라우저 실행, 동시성 재현은 하지 않았다. 아래 시나리오는 코드에서 도출한 재현 절차이며 실행 결과가 아니다.

## 지적

1. **중간 — JSON만 수정하면 폴링이 변경을 놓친다.** `frontend/src/components/ProductionDashboard/index.tsx:4840,4853`. 서명에 level_json이 없으며 실제 JSON-only 쓰기가 `BatchVerifyPanel.tsx:210` 및 `index.tsx:9572,10730`에 존재한다. 같은 origin의 브라우저 탭 A에서 생성 중 테스트 목록을 열어 두고, 탭 B에서 동일 배치의 중앙정렬을 수정하면 A의 서명은 그대로다. 다른 레벨의 서명 변경 또는 수동 새로고침 전까지 A의 목록 데이터는 옛 JSON이다. 단일 탭의 중앙정렬 버튼은 명시적으로 loadLevels를 호출하므로 그 경로 자체는 정상 갱신한다. 저장 시 공통 revision을 증가시키고 서명에 포함하거나 저장 알림을 활용해야 한다.

2. **중간 — 새 lazy 탭의 청크 로드 실패가 앱 전체로 전파된다.** `frontend/src/App.tsx:6,421` 및 `frontend/src/main.tsx:6`. Suspense만 추가되고 오류 경계는 없다(`git grep -n ErrorBoundary 3d178b6 -- frontend/src` 해당 없음). 초기 앱 로드 뒤 네트워크 단절 또는 배포로 청크가 없어졌을 때 미방문 lazy 탭을 처음 열면 import 거부를 처리하지 못한다. ProductionDashboard를 포함한 루트 트리가 내려가 생성·검증 작업에도 영향을 줄 수 있다. 탭 단위 오류 경계와 재시도/새로고침 안내가 필요하다. 기존 LevelShapesPanel에도 같은 한계가 있었으나 이번 변경은 10개 탭으로 확대한다.

3. **낮음 — 변경이 있는 폴링마다 전체 조회가 두 번 발생한다.** `frontend/src/components/ProductionDashboard/index.tsx:4851,4867`. 생성이 계속되어 매 5초마다 서명이 바뀌면 polled를 버리고 같은 배치를 다시 읽는다. `frontend/src/storage/productionStorage.ts:403`의 getAll 후 필터링 구조라 2000 limit도 DB 전체 복제를 막지 않는다. 이 경로는 변경 전 1회에서 2회로 증가한다. 첫 조회 결과를 상태 갱신에 재사용할 수 있다.

## 요청된 위험 중 기존부터 남아 있는 문제

- **중간 — 이미 시작된 통계 계산은 취소되지 않는다.** `index.tsx:823,824,1077,1084,1085`. A 통계 타이머가 실행되어 await에 진입한 뒤 B로 전환하면 타이머 ref는 이미 null이다. B 결과 다음에 A 결과가 완료되는 순서라면 A 통계가 B 화면을 덮는다. 언마운트 cleanup도 진행 중 계산 결과를 차단하지 않는다. 변경 전 즉시 통계 계산과 배치 선택 effect에도 같은 경쟁이 존재했으며, 이번 예약 취소만으로 해결되지 않았다. batchId/세대 토큰 및 mounted 가드가 필요하다.
- **높음 — 전송 중 같은 번호를 다시 수정하면 dirty가 소실될 수 있다.** `productionServerSync.ts:114,116,134-136,318,327`. A 버전을 읽어 보내는 동안 동일 번호 B 수정 → 응답에서 번호 삭제 → pending 재실행은 dirty 없음으로 종료(110). 기존 문제지만 maxWait로 지속 편집 도중 전송이 시작되는 빈도가 높아진다. 번호별 revision을 확인해 보낸 버전만 지워야 한다.
- 언로드 flush/영속 dirty 복구는 해당 모듈에 없고 `frontend/src`의 beforeunload/pagehide 검색도 일치 없음. 예약 중 닫으면 서버에는 미전송일 수 있으며 IndexedDB 저장과 서버 전송은 다르다. 이번 커밋에서 새로 생긴 문제로 분류하지 않았다.

## 추가 확인 범위

- `index.tsx:5241,5473-5488`: fresh는 번호 Map으로만 사용하고 측정 대상도 pending이다. 재생성 runPool 완료를 기다린 뒤 다음 라운드마다 새 readonly transaction으로 번호를 조회한다(`productionStorage.ts:353-382`). 배치 전체 인덱스/카운트 의존은 이 변경 경로에서 발견하지 못했다.
- `productionServerSync.ts:294-327`: 타이머와 첫 시각은 batchId별이며 fire에서 둘 다 삭제한다. 기존 타이머 취소 후 남은 maxWait로 재예약한다. 진행 중 push에는 pending만 표시하고 완료 후 직렬 실행한다. 배치 전환으로 다른 배치 키가 섞이는 경로는 발견하지 못했다. 30초는 예약 상한이며 이벤트 루프 지연·네트워크 완료까지 보장하지 않는다.
- 주요 재생성·튜닝 경로는 generated_at/status_updated_at을 바꾼다(`index.tsx:2797,5420,6089,6205`). 모든 쓰기가 그러한 것은 아니므로 첫 지적은 유효하다.
- 탭 조건부 렌더 구조와 ProductionDashboard의 display:none 상시 마운트는 유지된다. 일반 탭의 전환 시 unmount 동작도 기존과 같다. 요청 로그 플래그는 localStorage 접근 예외를 처리한다.

검증 명령: `git show 3d178b6`, `git show 3d178b6:<경로>`, `git grep`으로 관련 쓰기·오류 처리 경로 확인. 실행 테스트 0건. 성능 수치·UI 실제 재현은 미검증.

## 재검토

대상 `3a97848` (2026-11-06). 정적 리뷰만 수행; 아래 줄 번호는 이 커밋 기준이다.

- **해소:** 지적 2의 루트 오류 전파는 `frontend/src/components/common/lazyTab.tsx:13-29`의 오류 경계로 차단된다. retry에서 lazy 객체를 새로 만들고 failed를 초기화한다. Wrapper/Boundary 정의는 factory 호출 시 고정되므로 일반 렌더마다 탭을 새로 마운트하지 않는다. ProductionDashboard 상시 마운트도 유지된다. 단, 배포로 기존 청크 URL 자체가 없어졌거나 모듈 로더가 실패를 캐시하면 같은 URL 재시도만으로 복구되지 않을 수 있다. 실제 브라우저 재시도 성공은 미검증이다.
- **해소:** 지적 3의 중복 조회는 `index.tsx:4867,4881`에서 prefetched를 재사용하여 제거됐다. 변경 없는 폴링은 조기 반환하고, 변경 있는 폴링도 DB 조회는 1회다. 서명 계산은 polled와 loadedLevels에 각각 수행되므로 타일 키 순회는 2회지만 DB 재조회와는 다르다.
- **중간, 부분 해소/잔존 — 서명은 여전히 모든 데이터 변경을 대표하지 않는다.** `index.tsx:4841-4852`: 중앙정렬로 첫/끝 좌표나 크기가 바뀌는 경우는 잡지만 타일 값, randSeed/useTileCount, 중간 키의 같은 개수 교체, verification_passed 등은 제외된다. 실제 저장 경로 `RLSimulationPanel.tsx:731-753`은 기존 meta를 유지하면서 best.level_json을 교체하고 verified=false만 설정한다. 원본이 이미 verified=false이며 후보가 동일 좌표·개수에 seed/타일 값만 달라지면 서명이 같다. 같은 origin의 다른 탭에서 적용하고 생성 중 테스트 탭이 폴링하면 수동 갱신/다른 서명 변경 전까지 옛 데이터를 유지한다. `BatchVerifyPanel.tsx:142-154` 역시 generated_at/status_updated_at을 갱신하지 않아 verified와 match_score까지 같은 재생성 결과에서는 같은 문제가 남는다. 저장 공통 revision 또는 전체 내용 비교가 필요하다. 새로 도입된 회귀라기보다 기존 지적의 불완전한 보완이다.
- 앞서 기록한 통계 완료 경쟁·동일 번호 dirty 유실은 이번 보완 범위에 없으며 해소로 판정하지 않았다. 이외 lazyTab/prefetched 변경에서 새 확정 회귀는 발견하지 못했다.

확인: `git show 3a97848`, 커밋 기준 관련 파일 조회. 실행 테스트 0건, tsc·브라우저 검증 없음.
