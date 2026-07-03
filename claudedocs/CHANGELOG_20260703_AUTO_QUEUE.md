# CHANGELOG 2026-07-03 — 프로덕션 자동 연속생성 큐

## 요약
자리비움(야간) 운용을 위해 **여러 1500레벨 배치를 연속(순차) 자동 생성**하는 큐를
프로덕션 생성 탭에 추가. 목표 개수만큼 만들거나 정지 누를 때까지 무한.

## 배경 / 문제
- 기존: 프론트 1탭 = 배치 1개만 수동 생성. 각 배치 완료 후 사람이 다시 클릭해야 다음 배치.
- 생성은 **프론트 주도 오케스트레이션**(JS 루프가 레벨별 `/generate` 호출), 백엔드는 무상태.
- 로컬 CPU(GEN_POOL_WORKERS=8, 10코어 기준)가 처리량 상한 → **배치 병렬은 이득 없음**
  (동시 2배치 = 각 절반속도). 따라서 **연속(back-to-back) 순차 생성**이 유일한 실효 자동화.

## 구현

### 프론트 (`frontend/src/components/ProductionDashboard/index.tsx`)
1. **`handleStartGeneration` 리팩터**: 2번째 인자 `overrideBatchId?: string` 추가.
   - 명시 batchId 우선(`activeBatchId = overrideBatchId ?? selectedBatchId`) → 큐 루프에서
     `setSelectedBatchId` 비동기 반영을 안 기다리고 즉시 그 배치로 생성.
   - 본문 8개 `selectedBatchId` 참조 → `activeBatchId`로 치환.
   - 반환값 `Promise<boolean>`: 정상완료 true / 중단·오류 false (`completedOk` 플래그).
2. **자동 큐 상태**: `autoQueueRunning`, `autoQueueMade`, `autoQueueTarget`, `autoQueueStopRef`.
3. **`handleAutoQueueStart(preset, targetCount, playtestConfig)`**:
   ```
   while (!stop && (target===0 || made<target)):
     batch = createProductionBatch({...preset, 1500레벨})
     ok = await handleStartGeneration(config, batch.id)   // 1500레벨 완료까지 대기
     if (!ok || stop) break
     made++
   ```
   - target=0 → 무한(정지까지). 중단/오류 시 큐 종료(미완성 배치 보존).
4. **`handleAutoQueueStop`**: `autoQueueStopRef=true` + 현재 배치 `abort`.
5. **UI (생성 탭 최상단 패널)**: 프리셋 선택 + 목표 배치수 입력(0/빈=무한) + 시작/정지 +
   진행표시(`배치 3/10 완료`, 현재 배치 레벨 진행률). 프리셋/개수 localStorage 유지.

## 운용 주의 (UI에 안내 내장)
- **컴퓨터 절전 해제 필수** — Mac: `caffeinate -dis`. sleep 시 큐 중단.
- **탭 열어두기** — 브라우저 백그라운드 탭 타이머 스로틀로 느려질 수 있음. 포그라운드 권장.
- 배치당 ~20~40분 → 8시간 자리비움 ≈ **12~19배치** 자동 생성.

## 성능 컨텍스트 (실측, 로컬 8워커)
- 생성 `/generate`: ~0.8초/레벨 · RL 검증 `/rl-sim/level`: ~2.3초/레벨
- 재생성 포함 레벨당 실효 ~5~9 코어-초 → 1500레벨 배치 ≈ 20~40분

## 대안 검토 (기각)
- **Cloud Run 등 온라인 위임**: 백엔드만 무상태라 `VITE_API_URL` 하나로 교체 가능. 동시
  다수 배치 진짜 병렬(오토스케일). 단 이번엔 로컬 자동화 요청이라 보류. 무료티어 월
  180,000 vCPU-초(결제계정당, 매월 리셋) ≈ ~20배치.

## 검증
- `npx tsc --noEmit` 통과. vite 서빙 정상. import(createProductionBatch,
  PROFESSIONAL_GIMMICK_UNLOCK_LEVELS) 스코프 확인.
- 런타임 E2E(배치 2개 연속): 사용자 테스트 중.

## 게임 영향
없음(순수 프론트 오케스트레이션). 생성 로직/포맷 불변.
