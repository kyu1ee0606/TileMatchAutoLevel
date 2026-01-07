# 세션 요약: 등급 분포 정확도 개선

## 날짜: 2025-01-05

## 주요 작업 완료

### 1. 백엔드 등급 생성 개선 (완료)
- `generator.py`: `_adjust_difficulty`에서 tiles_maxed_out 상태 추적
- `_increase_difficulty`에서 타일이 최대일 때 장애물(chain, frog, ice) 추가
- `_add_ice_to_tile` 메서드 추가
- 타일 수와 레이어 수를 난이도에 따라 조정:
  - S등급: 9-24 타일, 2-3 레이어
  - A등급: 24-45 타일, 3-5 레이어
  - B+ 등급: 45-120 타일 + 장애물

### 2. Analyzer ice_count 지원 (완료)
- `analyzer.py`: WEIGHTS에 ice_count 추가 (2.5)
- `_extract_metrics`에서 ice_count 추출
- `models/level.py`: LevelMetrics에 ice_count 필드 추가

### 3. 프론트엔드 UI 개선 (완료)
- 장애물 없이 B/C/D 등급 요청 시 경고 배너 표시
- 재시도 로직 개선: 30회 최대 재시도, 동적 난이도 조정

### 4. 진행 중인 작업
- `GenerationResultItem`에 `retryCount`, `targetGrade` 필드 추가
- `GenerationProgress.tsx`에서 재시도 횟수 표시
- `GradeSummary`에 등급 일치율 및 총 재시도 통계 추가

## 핵심 발견

### 등급별 난이도 범위
- S: 0-20% (매우 쉬움)
- A: 20-40% (쉬움)
- B: 40-60% (보통)
- C: 60-80% (어려움)
- D: 80-100% (매우 어려움)

### 장애물 없이 달성 가능한 최대 난이도
- 장애물 없음: ~40% (A등급 상한)
- B/C/D 등급을 위해서는 장애물 필수 (chain, frog, ice 등)

### 재시도 전략
- 등급 불일치 시 ±0.05씩 난이도 조정
- 최대 ±0.15 범위 내에서 조정
- 30회까지 재시도

## 파일 변경 목록

### 백엔드
- `backend/app/core/generator.py` - 난이도 조정 로직 개선
- `backend/app/core/analyzer.py` - ice_count 지원
- `backend/app/models/level.py` - LevelMetrics ice_count 필드

### 프론트엔드
- `frontend/src/types/levelSet.ts` - retryCount, targetGrade 필드
- `frontend/src/components/LevelSetGenerator/index.tsx` - 재시도 로직, 경고 배너
- `frontend/src/components/LevelSetGenerator/GenerationProgress.tsx` - 재시도 UI 표시

## 다음 세션 작업
1. 재시도 로직 테스트 및 검증
2. 등급 일치율 향상 방안 검토 (필요시)
3. UI에서 재시도 진행 상황 실시간 표시 개선
