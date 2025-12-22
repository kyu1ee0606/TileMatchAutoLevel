# 새로운 EASY와 MEDIUM 티어 레벨
# EASY: 레이어 1-2개, 기믹 없음
# MEDIUM: 레이어 2-4개, 1개 기믹

from backend.app.models.benchmark_level import BenchmarkLevel, DifficultyTier
from typing import List

# =============================================================================
# EASY TIER - 10 Levels (레이어 1-2개, 기믹 없음)
# =============================================================================

EASY_LEVELS_NEW: List[BenchmarkLevel] = [
    # EASY-01: 3종류, 1레이어
    BenchmarkLevel(
        id="easy_01",
        name="기본 3종류",
        difficulty_tier=DifficultyTier.EASY,
        description="3종류 타일, 1레이어. 기본 매칭 연습.",
        level_json={
            "tiles": [
                {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 5},
            "goals": {"t1": 3, "t2": 3, "t3": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.60,
            "casual": 0.90,
            "average": 0.98,
            "expert": 1.00,
            "optimal": 1.00,
        },
        tags=["basic", "1_layer"],
    ),

    # EASY-02: 4종류, 1레이어
    BenchmarkLevel(
        id="easy_02",
        name="4종류 타일",
        difficulty_tier=DifficultyTier.EASY,
        description="4종류 타일, 1레이어. 타입 다양성.",
        level_json={
            "tiles": [
                {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.55,
            "casual": 0.85,
            "average": 0.95,
            "expert": 1.00,
            "optimal": 1.00,
        },
        tags=["basic", "1_layer", "variety"],
    ),

    # EASY-03: 5종류, 1레이어
    BenchmarkLevel(
        id="easy_03",
        name="5종류 타일",
        difficulty_tier=DifficultyTier.EASY,
        description="5종류 타일, 1레이어. 다양성 증가.",
        level_json={
            "tiles": [
                {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.50,
            "casual": 0.80,
            "average": 0.92,
            "expert": 0.99,
            "optimal": 1.00,
        },
        tags=["basic", "1_layer", "variety"],
    ),

    # EASY-04: 3종류, 2레이어 간단한 블로킹
    BenchmarkLevel(
        id="easy_04",
        name="2레이어 블로킹 기본",
        difficulty_tier=DifficultyTier.EASY,
        description="3종류 타일, 2레이어. 간단한 블로킹.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 5, 1: 5},
            "goals": {"t1": 3, "t2": 3, "t3": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.50,
            "casual": 0.85,
            "average": 0.95,
            "expert": 1.00,
            "optimal": 1.00,
        },
        tags=["layer_blocking", "2_layers"],
    ),

    # EASY-05: 4종류, 2레이어
    BenchmarkLevel(
        id="easy_05",
        name="2레이어 + 4종류",
        difficulty_tier=DifficultyTier.EASY,
        description="4종류 타일, 2레이어. 블로킹 + 다양성.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7, 1: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.48,
            "casual": 0.82,
            "average": 0.93,
            "expert": 0.99,
            "optimal": 1.00,
        },
        tags=["layer_blocking", "2_layers", "variety"],
    ),

    # EASY-06: 4종류, 2레이어, 더 많은 타일
    BenchmarkLevel(
        id="easy_06",
        name="2레이어 복잡",
        difficulty_tier=DifficultyTier.EASY,
        description="4종류 타일, 2레이어. 타일 수 증가.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7, 1: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.46,
            "casual": 0.80,
            "average": 0.92,
            "expert": 0.98,
            "optimal": 1.00,
        },
        tags=["layer_blocking", "2_layers", "variety"],
    ),

    # EASY-07: 5종류, 1레이어
    BenchmarkLevel(
        id="easy_07",
        name="5종류 다양성",
        difficulty_tier=DifficultyTier.EASY,
        description="5종류 타일, 1레이어. 인지 부하 연습.",
        level_json={
            "tiles": [
                {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.48,
            "casual": 0.78,
            "average": 0.90,
            "expert": 0.98,
            "optimal": 1.00,
        },
        tags=["basic", "1_layer", "variety"],
    ),

    # EASY-08: 5종류, 2레이어
    BenchmarkLevel(
        id="easy_08",
        name="2레이어 + 5종류",
        difficulty_tier=DifficultyTier.EASY,
        description="5종류 타일, 2레이어. 블로킹 + 다양성.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7, 1: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.44,
            "casual": 0.75,
            "average": 0.88,
            "expert": 0.96,
            "optimal": 0.99,
        },
        tags=["layer_blocking", "2_layers", "variety"],
    ),

    # EASY-09: 4종류, 2레이어, 복잡한 블로킹
    BenchmarkLevel(
        id="easy_09",
        name="2레이어 복잡 블로킹",
        difficulty_tier=DifficultyTier.EASY,
        description="4종류 타일, 2레이어. 복잡한 블로킹 패턴.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7, 1: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.42,
            "casual": 0.72,
            "average": 0.85,
            "expert": 0.95,
            "optimal": 0.99,
        },
        tags=["layer_blocking", "2_layers", "complex"],
    ),

    # EASY-10: 5종류, 2레이어, 최종 테스트
    BenchmarkLevel(
        id="easy_10",
        name="EASY 최종 챌린지",
        difficulty_tier=DifficultyTier.EASY,
        description="5종류 타일, 2레이어. EASY 티어 최고 난이도.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7, 1: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3},
            "max_moves": 50,
        },
        expected_clear_rates={
            "novice": 0.40,
            "casual": 0.70,
            "average": 0.83,
            "expert": 0.93,
            "optimal": 0.98,
        },
        tags=["layer_blocking", "2_layers", "variety", "challenging"],
    ),
]


# =============================================================================
# MEDIUM TIER - 10 Levels (레이어 2-4개, 1개 기믹)
# =============================================================================

MEDIUM_LEVELS_NEW: List[BenchmarkLevel] = [
    # MEDIUM-01: 6종류, 2레이어, ICE 1개
    BenchmarkLevel(
        id="medium_01",
        name="ICE + 2레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="6종류 타일, 2레이어, ICE 1개. 기믹 도입.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 1
                {"layerIdx": 1, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "6_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "6_3", "tileType": "t6", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3},
            "max_moves": 30,
        },
        expected_clear_rates={
            "novice": 0.30,
            "casual": 0.55,
            "average": 0.75,
            "expert": 0.90,
            "optimal": 0.97,
        },
        tags=["2_layers", "ice", "variety"],
    ),

    # MEDIUM-02: 7종류, 3레이어, GRASS 1개
    BenchmarkLevel(
        id="medium_02",
        name="GRASS + 3레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="7종류 타일, 3레이어, GRASS 1개. 레이어 증가.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_3", "tileType": "t7", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3},
            "max_moves": 28,
        },
        expected_clear_rates={
            "novice": 0.28,
            "casual": 0.52,
            "average": 0.72,
            "expert": 0.88,
            "optimal": 0.95,
        },
        tags=["3_layers", "grass", "variety"],
    ),

    # MEDIUM-03: 6종류, 3레이어, LINK 1쌍
    BenchmarkLevel(
        id="medium_03",
        name="LINK + 3레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="6종류 타일, 3레이어, LINK 1쌍. 효율적 선택.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "4_2"}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t6", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3},
            "max_moves": 26,
        },
        expected_clear_rates={
            "novice": 0.32,
            "casual": 0.57,
            "average": 0.76,
            "expert": 0.90,
            "optimal": 0.96,
        },
        tags=["3_layers", "link", "variety"],
    ),

    # MEDIUM-04: 7종류, 4레이어, ICE 1개
    BenchmarkLevel(
        id="medium_04",
        name="ICE + 4레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="7종류 타일, 4레이어, ICE 1개. 깊은 블로킹.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "4_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_4", "tileType": "t1", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3},
            "max_moves": 24,
        },
        expected_clear_rates={
            "novice": 0.25,
            "casual": 0.48,
            "average": 0.68,
            "expert": 0.85,
            "optimal": 0.93,
        },
        tags=["4_layers", "ice", "variety", "complex"],
    ),

    # MEDIUM-05: 8종류, 3레이어, GRASS 1개
    BenchmarkLevel(
        id="medium_05",
        name="GRASS + 8종류",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="8종류 타일, 3레이어, GRASS 1개. 높은 다양성.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "4_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "8_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "8_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "8_3", "tileType": "t8", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3},
            "max_moves": 26,
        },
        expected_clear_rates={
            "novice": 0.22,
            "casual": 0.45,
            "average": 0.65,
            "expert": 0.82,
            "optimal": 0.92,
        },
        tags=["3_layers", "grass", "variety", "high_cognitive"],
    ),

    # MEDIUM-06: 7종류, 4레이어, LINK 1쌍
    BenchmarkLevel(
        id="medium_06",
        name="LINK + 4레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="7종류 타일, 4레이어, LINK 1쌍. 복잡 블로킹.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "link_west", "effect_data": {"linked_pos": "3_3"}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3},
            "max_moves": 25,
        },
        expected_clear_rates={
            "novice": 0.26,
            "casual": 0.50,
            "average": 0.70,
            "expert": 0.86,
            "optimal": 0.94,
        },
        tags=["4_layers", "link", "complex"],
    ),

    # MEDIUM-07: 6종류, 4레이어, ICE 1개
    BenchmarkLevel(
        id="medium_07",
        name="ICE + 4레이어 복잡",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="6종류 타일, 4레이어, ICE 1개. 복잡한 4레이어.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "4_4", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "4_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_4", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3},
            "max_moves": 23,
        },
        expected_clear_rates={
            "novice": 0.24,
            "casual": 0.47,
            "average": 0.67,
            "expert": 0.84,
            "optimal": 0.92,
        },
        tags=["4_layers", "ice", "complex"],
    ),

    # MEDIUM-08: 7종류, 3레이어, GRASS 1개
    BenchmarkLevel(
        id="medium_08",
        name="GRASS + 7종류",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="7종류 타일, 3레이어, GRASS 1개. 다양성 + 기믹.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "4_2", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_3", "tileType": "t7", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3},
            "max_moves": 25,
        },
        expected_clear_rates={
            "novice": 0.26,
            "casual": 0.50,
            "average": 0.70,
            "expert": 0.86,
            "optimal": 0.94,
        },
        tags=["3_layers", "grass", "variety"],
    ),

    # MEDIUM-09: 8종류, 4레이어, LINK 1쌍
    BenchmarkLevel(
        id="medium_09",
        name="LINK + 8종류 + 4레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="8종류 타일, 4레이어, LINK 1쌍. 높은 복잡도.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "4_4", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "link_west", "effect_data": {"linked_pos": "3_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_4", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_3", "tileType": "t8", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3},
            "max_moves": 22,
        },
        expected_clear_rates={
            "novice": 0.20,
            "casual": 0.43,
            "average": 0.63,
            "expert": 0.80,
            "optimal": 0.90,
        },
        tags=["4_layers", "link", "variety", "high_cognitive", "complex"],
    ),

    # MEDIUM-10: 7종류, 4레이어, ICE 1개, 최종 챌린지
    BenchmarkLevel(
        id="medium_10",
        name="MEDIUM 최종 챌린지",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="7종류 타일, 4레이어, ICE 1개. MEDIUM 티어 최고 난이도.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "5_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "4_4", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_4", "tileType": "t2", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_4", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t7", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3},
            "max_moves": 20,
        },
        expected_clear_rates={
            "novice": 0.18,
            "casual": 0.40,
            "average": 0.60,
            "expert": 0.78,
            "optimal": 0.88,
        },
        tags=["4_layers", "ice", "variety", "complex", "challenging"],
    ),
]

print(f"EASY 레벨 수: {len(EASY_LEVELS_NEW)}")
print(f"MEDIUM 레벨 수: {len(MEDIUM_LEVELS_NEW)}")
