# 세션 노트 - 2026-01-16

## 완료된 작업

### 1. 체인 기믹 차단 규칙 수정 (커밋됨: c8b2b6d)
- 체인 타일이 상위 레이어로 덮여있을 때 인접 타일 선택해도 해제 안됨
- 선택 가능한 이동이 없을 때 게임오버 조건 추가
- 폭탄/커튼 카운트다운이 "선택 전" 상태 기준으로 처리
- 기믹 해제 시 오버레이 이미지 숨김 처리 (링크, 언노운, 커튼)
- 테스트 레벨 추가: `chain_block_test.json`, `chain_gameover_test.json`

### 2. 저장소 통합 설계 (문서만 작성)
- 설계 문서: `docs/STORAGE_CONSOLIDATION_DESIGN.md`
- 백엔드를 주 저장소로, localStorage는 오프라인 캐시/폴백으로 변경 예정
- 구현은 미완료 (문서만 준비됨)

## 미커밋 파일

### 커밋 필요
- `docs/STORAGE_CONSOLIDATION_DESIGN.md` - 저장소 통합 설계 문서

### 정리 필요 (테스트 데이터)
- `backend/app/storage/local_levels/test5_level_*.json` (10개) - 이전 테스트 데이터

## 다음 세션 작업

### 저장소 통합 구현 (우선순위: 중간)
1. `docs/STORAGE_CONSOLIDATION_DESIGN.md` 참조
2. `frontend/src/services/localLevelsApi.ts` 수정 - 백엔드 우선 저장
3. 동기화 함수 추가 및 UI 연동

### 체인 테스트 검증 (우선순위: 낮음)
- `chain_block_test` 레벨로 체인 차단 동작 검증
- `chain_gameover_test` 레벨로 게임오버 조건 검증

## 현재 저장소 상태
- 백엔드 레벨: ~2,051개
- localStorage: 브라우저별 상이 (확인 필요)

## 관련 파일 위치
| 기능 | 파일 |
|------|------|
| 프론트엔드 게임 엔진 | `frontend/src/engine/gameEngine.ts` |
| 백엔드 봇 시뮬레이터 | `backend/app/core/bot_simulator.py` |
| 레벨 저장 API | `frontend/src/services/localLevelsApi.ts` |
| localStorage 헬퍼 | `frontend/src/storage/levelStorage.ts` |
| 백엔드 저장 API | `backend/app/api/routes/simulate.py:1314` |
