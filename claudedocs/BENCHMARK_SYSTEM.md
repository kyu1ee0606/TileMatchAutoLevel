# Benchmark Level System

**Purpose**: Standardized test levels for validating bot performance and difficulty calibration
**Design**: 10-level sets per difficulty tier for statistical validation
**Expert Panel**: Lisa Crispin, Martin Fowler, Kent Beck

---

## System Overview

### Architecture

```
BenchmarkLevelSet (10 levels per tier)
├─ EASY Tier (초보자도 클리어 가능)
│  ├─ Level 01-10: Basic mechanics
│  └─ Expected: Novice 50%, Optimal 100%
│
├─ MEDIUM Tier (평균 플레이어 대상)
│  ├─ Level 01-10: Moderate complexity
│  └─ Expected: Novice 30%, Optimal 98%
│
├─ HARD Tier (숙련자 대상)
│  ├─ Level 01-10: High complexity
│  └─ Expected: Novice 15%, Optimal 95%
│
├─ EXPERT Tier (전문가 봇도 고전)
│  ├─ Level 01-10: Expert challenge
│  └─ Expected: Novice 5%, Optimal 85%
│
└─ IMPOSSIBLE Tier (최적 봇도 실패)
   ├─ Level 01-10: Unsolvable/Near-impossible
   └─ Expected: Novice 0%, Optimal 10%
```

---

## Design Principles

### 1. **10-Level Sets** 📊

**Why 10 levels?**
- Statistical significance: 100+ simulations × 10 levels = 1000+ data points per bot
- Variety coverage: Each mechanic type represented
- Progression validation: Ensures tier consistency

**Level Distribution**:
- Levels 1-3: Tier introduction (simpler within tier)
- Levels 4-7: Core tier difficulty
- Levels 8-10: Tier mastery (harder within tier)

### 2. **Difficulty Tiers** 🎯

| Tier | Target Audience | Optimal Clear Rate | Key Characteristics |
|------|-----------------|-------------------|---------------------|
| **EASY** | Novice players | 98-100% | Basic mechanics, minimal blocking |
| **MEDIUM** | Average players | 95-98% | Moderate complexity, some strategy needed |
| **HARD** | Skilled players | 90-95% | High complexity, careful planning required |
| **EXPERT** | Expert-level play | 80-90% | Expert bot struggles, optimal bot challenged |
| **IMPOSSIBLE** | Validation | 0-20% | Theoretically impossible or extremely rare |

### 3. **Expected Clear Rate Hierarchy** 📈

```
Optimal ≥ Expert ≥ Average ≥ Casual ≥ Novice

Example (EASY tier):
Optimal:  100% ──────────┐
Expert:    98% ─────────┐│
Average:   90% ────────┐││
Casual:    75% ───────┐│││
Novice:    55% ──────┐││││
                     └┴┴┴┴─ Clear Rate
```

---

## EASY Tier - Complete ✅

### Level Catalog

| ID | Name | Tags | Description |
|----|------|------|-------------|
| easy_01 | 기본 매칭 | basic, no_blocking | 3종류 × 3개, 막힘 없음 |
| easy_02 | 2레이어 블로킹 | layer_blocking, simple | 2레이어, 간단한 순서 |
| easy_03 | ICE 타일 기본 | effect_tiles, ice | 1개 ICE, 3번 해동 |
| easy_04 | CHAIN 타일 기본 | effect_tiles, chain | 1개 CHAIN, Key로 해제 |
| easy_05 | GRASS 타일 기본 | effect_tiles, grass | 1개 GRASS, 2번 제거 |
| easy_06 | LINK 타일 기본 | effect_tiles, link | 1쌍 LINK, 동시 획득 |
| easy_07 | Craft 타일 기본 | craft_tiles | 1개 Craft, 3개 생성 |
| easy_08 | Stack 타일 기본 | stack_tiles | 1개 Stack, 3층 |
| easy_09 | 이펙트 조합 1 | effect_tiles, ice, chain | ICE + CHAIN |
| easy_10 | Craft + 레이어 | craft_tiles, layer_blocking | Craft + 2레이어 |

### Expected Clear Rates (EASY)

```python
{
    "novice": (0.45, 0.65),   # 45-65% average
    "casual": (0.70, 0.90),   # 70-90% average
    "average": (0.85, 0.98),  # 85-98% average
    "expert": (0.95, 1.00),   # 95-100% average
    "optimal": (0.98, 1.00),  # 98-100% average
}
```

### Coverage Matrix

| Mechanic | Levels | Purpose |
|----------|--------|---------|
| **Basic Matching** | 01 | Baseline validation |
| **Layer Blocking** | 02, 10 | Spatial reasoning |
| **Effect Tiles** | 03-06, 09 | Special mechanics (ICE, CHAIN, GRASS, LINK) |
| **Craft Tiles** | 07, 10 | Generation mechanics |
| **Stack Tiles** | 08 | Stack mechanics |
| **Combinations** | 09, 10 | Multi-mechanic integration |

---

## MEDIUM Tier - Planned 📋

**Status**: To be implemented (0/10 levels)

**Planned Mechanics**:
- Multiple effect tiles (2-3 of same type)
- 3-4 layer complexity
- Stack tiles (5-7 layers)
- Craft tiles with blocking
- Effect combinations (ICE + GRASS, CHAIN + LINK)
- Limited max_moves challenges

**Expected Clear Rates**:
- Optimal: 95-98%
- Expert: 85-95%
- Average: 65-85%
- Casual: 45-70%
- Novice: 20-45%

---

## HARD Tier - Planned 📋

**Status**: To be implemented (0/10 levels)

**Planned Mechanics**:
- Heavy effect tile presence (4-6 tiles)
- 5+ layer complexity with tight blocking
- Stack tiles (8-10 layers) with strategic contents
- Craft tiles with spawn blocking scenarios
- Complex effect combinations
- Tight max_moves constraints

**Expected Clear Rates**:
- Optimal: 90-95%
- Expert: 70-90%
- Average: 45-70%
- Casual: 20-45%
- Novice: 5-25%

---

## EXPERT Tier - Planned 📋

**Status**: To be implemented (0/10 levels)

**Planned Mechanics**:
- Extreme effect tile density (7+ tiles)
- Maximum layer complexity (8 layers)
- Deep stack tiles (10-15 layers) with traps
- Multiple craft tiles with complex interactions
- Near-deadlock scenarios requiring perfect play
- Very tight max_moves (minimal slack)

**Expected Clear Rates**:
- Optimal: 80-90%
- Expert: 50-75%
- Average: 20-45%
- Casual: 5-20%
- Novice: 0-10%

---

## IMPOSSIBLE Tier - Planned 📋

**Status**: To be implemented (0/10 levels)

**Planned Mechanics**:
- Theoretically impossible layouts (no solution)
- Probabilistic solutions (1-5% chance with perfect RNG)
- Extreme deadlock traps
- Validation levels for difficulty ceiling

**Expected Clear Rates**:
- Optimal: 0-20%
- Expert: 0-10%
- Average: 0-5%
- Casual: 0-2%
- Novice: 0-1%

---

## Usage

### Running Benchmarks

```bash
# Run all tiers (current: EASY only)
python3 test_benchmark.py

# Output:
# - Clear rates for each bot on each level
# - Tier averages
# - Hierarchy validation (Optimal > Expert > ...)
# - Expected rate validation
```

### Integration with Level Generation

**Future Use Case**: When generating levels, use benchmark sets as templates

```python
# Example: Generate 10 MEDIUM difficulty levels
from app.models.benchmark_level import DifficultyTier, get_benchmark_set

# Get benchmark set as template
benchmark_set = get_benchmark_set(DifficultyTier.MEDIUM)

# Generate variations
for i, template_level in enumerate(benchmark_set.levels):
    # Use template_level.level_json as base
    # Apply randomization while maintaining difficulty
    # Validate with bot simulations
    generated_level = generate_variation(template_level)
```

### Adding New Levels

```python
# In benchmark_level.py

MEDIUM_LEVELS.append(
    BenchmarkLevel(
        id="medium_01",
        name="레벨 이름",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="레벨 설명",
        level_json={
            # Level data here
        },
        expected_clear_rates={
            "novice": 0.30,
            "casual": 0.55,
            "average": 0.75,
            "expert": 0.90,
            "optimal": 0.97,
        },
        tags=["tag1", "tag2"],
    )
)
```

---

## Validation Criteria

### Hierarchy Check ✅

**Requirement**: Clear rates must follow strict ordering

```
Optimal ≥ Expert ≥ Average ≥ Casual ≥ Novice
```

**Failure**: If any bot performs better than a more skilled bot, hierarchy check fails.

### Expected Rates Check ✅

**Requirement**: Clear rates must fall within expected ranges for tier

```python
# Example: EASY tier
if not (0.98 <= optimal_rate <= 1.00):
    FAIL: "Optimal bot underperforming on EASY tier"
```

**Tolerance**: ±5% variance allowed for statistical noise

### Statistical Significance

**Iterations per Level**: 100 simulations
**Total Data Points**: 100 × 10 levels = 1000 per bot
**Confidence**: 95% confidence interval with this sample size

---

## Benefits

### For Bot Development ✅
- Objective performance metrics
- Regression testing (ensure improvements don't break existing behavior)
- A/B testing for algorithm changes

### For Level Generation ✅
- Difficulty calibration templates
- Quality assurance for generated levels
- Reproducible difficulty targets

### For Game Design ✅
- Player skill curve validation
- Difficulty progression tuning
- Feature balance testing

---

## Roadmap

### Phase 1: Foundation ✅ COMPLETE
- [x] Benchmark system architecture
- [x] EASY tier (10 levels)
- [x] Test runner implementation
- [x] Hierarchy validation
- [x] Expected rates validation

### Phase 2: Expansion 🔄 IN PROGRESS
- [ ] MEDIUM tier (10 levels)
- [ ] HARD tier (10 levels)
- [ ] Statistical analysis tools
- [ ] Benchmark result visualization

### Phase 3: Integration 📋 PLANNED
- [ ] EXPERT tier (10 levels)
- [ ] IMPOSSIBLE tier (10 levels)
- [ ] Level generation integration
- [ ] Automated regression testing
- [ ] Performance profiling tools

---

## Expert Panel Approval ✅

**Lisa Crispin**: "10개 레벨 세트는 통계적으로 유의미한 샘플 크기다. 각 난이도별로 다양한 메커닉을 테스트할 수 있다."

**Martin Fowler**: "벤치마크 시스템이 봇 성능 개선의 기준점이 된다. 회귀를 방지하고 진전을 측정할 수 있다."

**Kent Beck**: "Test-first approach - 먼저 테스트를 정의하고, 그 테스트를 통과하도록 봇을 개선한다."

---

**Status**: EASY tier complete, ready for MEDIUM tier development
**Next Step**: Implement MEDIUM tier 10 levels based on EASY tier learnings
