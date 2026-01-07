# 세션 요약: 난이도 생성 로직 수정

## 날짜: 2025-01-06

## 문제점
- B/C/D 등급 레벨 생성 불가 (30회 재시도해도 실패)
- 난이도 상한이 ~40%로 제한됨
- Ice 장애물만으로는 효과 미미

## 해결 방안

### 1. generator.py - _increase_difficulty 로직 강화
- target_difficulty 매개변수 추가
- 등급별 전략 분기:
  - B등급(≥0.4): 60% 확률로 장애물 1-2개 추가
  - C등급(≥0.6): 장애물 1-3개 추가
  - D등급(≥0.8): 장애물 2-4개 + 타일 추가

### 2. analyzer.py - 장애물 가중치 상향
- chain_count: 3.0 → 5.0
- frog_count: 4.0 → 6.0
- ice_count: 2.5 → 4.0
- link_count: 2.0 → 3.0

## 결과
- 등급 일치율: 30% → **100%**
- 모든 등급(A/B/C/D) 첫 시도에 생성 성공
- 소요 시간: ~1분 → **53ms**

## 수정된 파일
- `backend/app/core/generator.py`: _adjust_difficulty, _increase_difficulty
- `backend/app/core/analyzer.py`: WEIGHTS
