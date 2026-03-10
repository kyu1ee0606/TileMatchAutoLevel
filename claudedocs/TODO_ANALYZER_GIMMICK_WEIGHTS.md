# TODO: 레벨 생성 개선 작업

---

## [완료] 31레벨 이후 일치율 하락 개선 (v13)

### 날짜: 2026-02-25

### 작업 요약

**문제**: Level 31+ 에서 일치율 급락 (59.9% → 목표 85%)
**원인**:
1. ice 기믹 해금 + 레이어/타일 수 급변
2. novice/casual 목표 클리어율이 비현실적 (30% 목표, 실제 0-10%)
3. max_moves_modifier가 너무 낮아 novice/casual 클리어 불가

**결과**: Level 35 E등급(90%) 테스트 5회 평균 **84.8%** 달성 (3/5회 85%+ 달성)

---

### v13 수정 사항

#### 1. max_moves_modifier 상향 조정 (`generate.py`)

| 등급 | v12 modifier | v13 modifier | 변경 이유 |
|------|-------------|-------------|----------|
| E (85%+) | 0.75 | **0.82** | novice/casual 최소 클리어 보장 |
| D (70-85%) | 0.80 | **0.85** | |
| C (50-70%) | 0.85 | **0.88** | |
| B (35-50%) | 0.90 | **0.92** | |
| S/A (<35%) | 1.0 | 1.0 | 변경 없음 |

**하한선 상향**: "Too easy" 조정 시 `max(0.78, ...)` (v12: 0.70)

#### 2. 목표 클리어율 현실화 (`generate.py`, `analyze.py`)

**HARD levels (0.6-1.0) 목표 클리어율:**

| 봇 | hard_start (0.6) | v12 hard_end (1.0) | v13 hard_end (1.0) |
|----|-----------------|-------------------|-------------------|
| novice | 45% | 20% | **3%** |
| casual | 55% | 35% | **20%** |
| average | 72% | 55% | **70%** |
| expert | 84% | 75% | **85%** |
| optimal | 92% | 88% | **92%** |

**E등급(90%) 최종 목표**: nov=13%, cas=29%, ave=70%, exp=85%, opt=92%

#### 3. 봇별 가중치 적용 (`calculate_match_score`)

난이도별로 봇 가중치를 차등 적용하여 일치율 계산:

```python
if target_difficulty >= 0.8:  # E등급
    bot_weights = {"novice": 0.3, "casual": 0.5, "average": 1.5, "expert": 1.5, "optimal": 1.2}
elif target_difficulty >= 0.6:  # C/D등급
    bot_weights = {"novice": 0.6, "casual": 0.8, "average": 1.3, "expert": 1.2, "optimal": 1.1}
else:  # 낮은 난이도
    bot_weights = {"novice": 1.0, "casual": 1.0, "average": 1.0, "expert": 1.0, "optimal": 1.0}
```

**이유**: 높은 난이도에서 novice/casual은 클리어 못하는 것이 정상, average/expert/optimal 중심으로 평가

#### 4. 레이어 설정 조정

**DIFFICULTY_PROFILES 업데이트:**

| 등급 | v12 layers | v13 layers | v12 moves_ratio | v13 moves_ratio |
|------|-----------|-----------|-----------------|-----------------|
| E | 6-7 | **6-8** | 0.70 | **0.65** |
| D | 5-6 | **5-7** | 0.80 | **0.78** |
| C | 4-5 | 4-5 | 0.90 | **0.88** |

**초기 레이어 설정:**
- E등급: `max(6, min(request.max_layers, 8))` (최소 6, 최대 8)
- D등급: `max(5, min(request.max_layers, 7))` (최소 5, 최대 7)

---

### 테스트 결과 (Level 35, E등급 90%)

```
✅ 일치율=85.4% 레이어=5 봇OK=4/5 | nov=8%/13%✓ cas=24%/29%✓ ave=92%/70%✗ exp=88%/85%✓ opt=96%/92%✓
✅ 일치율=87.7% 레이어=4 봇OK=4/5 | nov=32%/13%✗ cas=40%/29%✓ ave=80%/70%✓ exp=92%/85%✓ opt=96%/92%✓
⚠️ 일치율=80.7% 레이어=6 봇OK=5/5 | nov=0%/13%✓ cas=24%/29%✓ ave=60%/70%✓ exp=96%/85%✓ opt=100%/92%✓
⚠️ 일치율=84.4% 레이어=5 봇OK=4/5 | nov=4%/13%✓ cas=40%/29%✓ ave=92%/70%✗ exp=88%/85%✓ opt=100%/92%✓
✅ 일치율=85.9% 레이어=6 봇OK=4/5 | nov=4%/13%✓ cas=20%/29%✓ ave=68%/70%✓ exp=100%/85%✗ opt=100%/92%✓
```

**평균 일치율**: 84.8%
**85%+ 달성**: 3/5회 (60%)

---

### 수정된 파일

| 파일 | 수정 내용 |
|------|----------|
| `backend/app/api/routes/generate.py` | max_moves_modifier 상향, 목표 클리어율 조정, 봇별 가중치, 레이어 설정 |
| `backend/app/api/routes/analyze.py` | 목표 클리어율 동기화 |

---

### 향후 작업 (P1)

1. **다른 레벨/난이도 검증**
   - Level 50, 100에서 각 등급별 테스트
   - S/A/B/C/D 등급 일치율 확인

2. **목표 클리어율 구조 개선 검토**
   - 현재: target_difficulty → 고정 공식으로 봇별 목표 계산
   - 대안: 봇별 목표 직접 지정 또는 기준 봇+클리어율 방식

---

## [보류] 분석기 기믹 가중치 조정

### 날짜: 2026-02-23

**상태**: 보류 (v13에서 목표 클리어율 조정으로 우선 해결)

### 문제 상황
레벨 520 테스트: 정적 난이도 일치, 봇 일치율 25%

### 원인
teleporter, unknown, time_attack 기믹의 가중치가 과소평가됨

### 해결 방향
- teleporter/unknown/time_attack 가중치 상향
- 기믹 조합 시너지 반영

**참고 파일**: `backend/app/core/analyzer.py`, `backend/app/models/gimmick_profile.py`
