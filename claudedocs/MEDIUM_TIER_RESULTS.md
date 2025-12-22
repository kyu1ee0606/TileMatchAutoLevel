# MEDIUM Tier Test Results

**날짜**: 2025-12-22
**목표**: MEDIUM 티어 난이도 검증 및 봇 차별화 확인

---

## 📊 테스트 결과

### MEDIUM Tier Clear Rates (100 iterations × 10 levels)

| Bot Type | Clear Rate | Expected Range | Status |
|----------|-----------|----------------|--------|
| **Novice**  | 98.90% | 20-45% | ❌ Too Easy |
| **Casual**  | 99.80% | 45-70% | ❌ Too Easy |
| **Average** | 100.00% | 65-85% | ❌ Too Easy |
| **Expert**  | 100.00% | 85-98% | ⚠️ Above Range |
| **Optimal** | 100.00% | 95-100% | ✅ Pass |

**Hierarchy Check**: ✅ PASS (Optimal ≥ Expert ≥ Average ≥ Casual ≥ Novice)
**Expected Rates**: ❌ FAIL (All bots above expected ranges)

### Individual Level Results

| Level | Novice | Casual | Average | Expert | Optimal |
|-------|--------|--------|---------|--------|---------|
| medium_01 (6종류) | 94% | 99% | 100% | 100% | 100% |
| medium_02 (4레이어) | 100% | 100% | 100% | 100% | 100% |
| medium_03 (ICE×2) | 99% | 100% | 100% | 100% | 100% |
| medium_04 (GRASS×2) | 100% | 100% | 100% | 100% | 100% |
| medium_05 (LINK×2) | 97% | 100% | 100% | 100% | 100% |
| medium_06 (Craft×2) | 100% | 100% | 100% | 100% | 100% |
| medium_07 (레이어+ICE) | 100% | 100% | 100% | 100% | 100% |
| medium_08 (레이어+GRASS) | 100% | 100% | 100% | 100% |100% |
| medium_09 (Craft+3레이어) | 100% | 100% | 100% | 100% | 100% |
| medium_10 (복합 챌린지) | 99% | 99% | 100% | 100% | 100% |

---

## 🔍 분석

### 1. 난이도 문제

**증상**: MEDIUM 티어가 EASY 티어와 거의 동일한 난이도
- Novice 봇: 98.9% (기대: 20-45%)
- 모든 봇이 거의 완벽하게 클리어
- 봇 간 차별화 거의 없음

**원인 추정**:
1. **타일 수량 부족**: 현재 12-18 타일 → 더 많은 타일 필요
2. **max_moves 너무 여유**: 25-30 moves → 더 타이트하게 조정 필요
3. **레이어 복잡도 부족**: 3-4 레이어 → 더 깊은 블로킹 필요
4. **이펙트 타일 약함**: ICE/GRASS 2개 정도는 충분하지 않음
5. **타일 종류 부족**: 6-7 종류 → 8-10 종류로 증가 필요

### 2. 레벨 설계 문제점

**medium_01 (6종류 타일)**:
- 현재: 18 타일 (6종류 × 3개), max_moves=25
- 문제: Novice도 94% 클리어
- 개선: 24-30 타일 (8종류 × 3-4개), max_moves=15-18

**medium_02 (4레이어 블로킹)**:
- 현재: 12 타일, 4 레이어
- 문제: 모든 봇 100% 클리어
- 개선: 더 복잡한 블로킹 패턴, 더 많은 타일

**medium_03-08 (이펙트 타일)**:
- 현재: 이펙트 타일 2개
- 문제: 충분하지 않음
- 개선: 이펙트 타일 3-4개로 증가

**medium_10 (복합 챌린지)**:
- 현재: 6종류 + 4레이어 + ICE 1개
- 문제: Novice도 99% 클리어
- 개선: 더 많은 제약 조합

---

## 💡 개선 방향

### 즉시 조치 필요

1. **타일 수량 증가**:
   - EASY: 9-15 타일
   - MEDIUM: 21-30 타일 (현재 12-18에서 증가)
   - HARD: 35-45 타일 (예정)

2. **max_moves 대폭 감소**:
   - EASY: 40-50 moves
   - MEDIUM: 12-18 moves (현재 25-30에서 감소)
   - HARD: 8-12 moves (예정)

3. **타일 종류 증가**:
   - EASY: 3-5 종류
   - MEDIUM: 8-10 종류 (현재 6-7에서 증가)
   - HARD: 10-12 종류 (예정)

4. **이펙트 타일 강화**:
   - MEDIUM: 3-4 이펙트 타일
   - 복합 이펙트: ICE + GRASS 동시, LINK + Craft 조합

5. **레이어 복잡도 증가**:
   - 더 깊은 블로킹 체인
   - 여러 타일이 동시에 블록된 상황
   - 타이트한 해제 순서 요구

### 레벨 재설계 전략

**MEDIUM 티어 목표**:
- Novice: 20-35% (현재 98.9%)
- Casual: 50-65% (현재 99.8%)
- Average: 70-82% (현재 100%)
- Expert: 88-95% (현재 100%)
- Optimal: 95-99% (현재 100%)

**핵심 원칙**:
1. **Cognitive Load**: Novice는 많은 타일 종류를 추적하기 어려움
2. **Planning Depth**: Lookahead 0-2인 봇은 깊은 블로킹을 못 봄
3. **Effect Understanding**: 낮은 봇은 이펙트 타일 전략이 약함
4. **Move Efficiency**: 타이트한 moves는 최적 경로를 요구함

---

## 📋 다음 단계

### Option 1: MEDIUM 티어 재설계 (권장)
MEDIUM 티어를 완전히 재설계하여 실제 MEDIUM 난이도 달성

**장점**:
- 봇 차별화 명확하게 검증 가능
- HARD/EXPERT 티어 설계 기준 확보
- 벤치마크 시스템의 실제 유효성 검증

**작업량**: 10개 레벨 재설계 + 테스트

### Option 2: 현재 MEDIUM을 EASY-PLUS로 재분류
현재 MEDIUM을 "EASY-PLUS"로 재명명하고, 더 어려운 MEDIUM 생성

**장점**:
- 기존 작업 보존
- 점진적 난이도 증가

**작업량**: 티어 재구성 + 새 MEDIUM 10개 + 테스트

### Option 3: HARD 티어 먼저 구현
현재 MEDIUM 유지하고, 훨씬 어려운 HARD 구현

**단점**:
- MEDIUM의 목표 달성 실패
- 난이도 곡선 불균형
- 벤치마크 신뢰도 하락

---

## 🎯 권장사항

**MEDIUM 티어 재설계**를 권장합니다:

1. **Phase 1**: 현재 MEDIUM 레벨 분석
   - 어떤 요소가 쉽게 만들었는지 파악
   - 봇 행동 패턴 분석

2. **Phase 2**: 난이도 증가 전략 수립
   - 타일 수량, 종류, max_moves 조정 공식
   - 이펙트 타일 배치 전략
   - 레이어 블로킹 패턴 라이브러리

3. **Phase 3**: 새 MEDIUM 레벨 설계
   - 10개 레벨 재설계
   - 점진적 난이도 증가 (medium_01 쉬움 → medium_10 어려움)

4. **Phase 4**: 검증 및 조정
   - 벤치마크 테스트 실행
   - 기대 범위 달성할 때까지 반복 조정

---

## 📊 현재 상태 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| EASY 티어 | ✅ 완료 | 10 levels, 99-100% clear (trivially easy) |
| MEDIUM 티어 | ⚠️ 너무 쉬움 | 10 levels, 98.9-100% clear (재설계 필요) |
| HARD 티어 | ⏳ 대기 | 0 levels |
| EXPERT 티어 | ⏳ 대기 | 0 levels |
| IMPOSSIBLE 티어 | ⏳ 대기 | 0 levels |

**결론**: MEDIUM 티어가 EASY와 거의 동일한 난이도로 판명되었습니다. 실제 봇 차별화를 위해서는 난이도를 대폭 높여야 합니다.
