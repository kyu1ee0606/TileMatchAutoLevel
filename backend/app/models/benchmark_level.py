"""Benchmark level definitions for bot performance testing.

Provides standardized test levels for validating bot performance across
different difficulty tiers. Each difficulty tier contains 10 levels that
can be used for statistical validation.
"""

from dataclasses import dataclass
from typing import Dict, List, Any
from enum import Enum


class DifficultyTier(str, Enum):
    """Difficulty tier for benchmark levels."""
    EASY = "easy"           # 쉬움: 초보자도 클리어 가능
    MEDIUM = "medium"       # 보통: 평균 플레이어 대상
    HARD = "hard"           # 어려움: 숙련자 대상
    EXPERT = "expert"       # 전문가: 전문가 봇도 고전
    IMPOSSIBLE = "impossible"  # 불가능: 최적 봇도 실패


@dataclass
class BenchmarkLevel:
    """A single benchmark level for testing."""
    id: str
    name: str
    difficulty_tier: DifficultyTier
    description: str
    level_json: Dict[str, Any]
    expected_clear_rates: Dict[str, float]  # bot_type -> expected clear rate
    tags: List[str]  # e.g., ["effect_tiles", "stack_tiles", "blocking"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "difficulty_tier": self.difficulty_tier.value,
            "description": self.description,
            "level_json": self.level_json,
            "expected_clear_rates": self.expected_clear_rates,
            "tags": self.tags,
        }

    def to_simulator_format(self) -> Dict[str, Any]:
        """Convert simple format to bot_simulator expected format.

        Converts from:
            {"tiles": [{"layerIdx": 0, "pos": "1_1", ...}], "layer_cols": {0: 5}, ...}

        To:
            {"layer_0": {"tiles": {"1_1": [...]}}, "layer": 8, "randSeed": 0, ...}
        """
        simple = self.level_json

        # Organize tiles by layer
        layers: Dict[int, Dict[str, List]] = {}
        for tile in simple.get("tiles", []):
            layer_idx = tile["layerIdx"]
            pos = tile["pos"]

            if layer_idx not in layers:
                layers[layer_idx] = {}

            # Build tile data array: [type, effect, extra_data]
            tile_type = tile["tileType"]
            effect = tile.get("effect", "")

            # Handle effect_data if present
            if "effect_data" in tile:
                effect_data = tile["effect_data"]
                if "remaining" in effect_data:
                    effect = str(effect_data["remaining"])  # ICE/GRASS use numeric effect
                elif "unlocked" in effect_data and not effect_data["unlocked"]:
                    effect = "chain"
                elif "linked_pos" in effect_data:
                    # Link direction already in effect string
                    pass

            # Build extra_data for stack/craft tiles
            extra_data = []
            if tile.get("is_stack_tile") or tile.get("is_craft_tile"):
                stack_count = tile.get("stackCount", 1)
                extra_data = [stack_count]
            elif tile.get("craft"):
                # Craft direction
                craft_dir = tile["craft"]
                stack_count = tile.get("stackCount", 3)
                # Format: [type, craft_dir, [count]]
                layers[layer_idx][pos] = [tile_type, craft_dir, [stack_count]]
                continue

            # Standard format: [type, effect, extra_data]
            if extra_data:
                layers[layer_idx][pos] = [tile_type, effect, extra_data]
            elif effect:
                layers[layer_idx][pos] = [tile_type, effect]
            else:
                layers[layer_idx][pos] = [tile_type]

        # Build simulator format
        result = {
            "layer": max(layers.keys()) + 1 if layers else 1,
            "randSeed": simple.get("randSeed", 0),
            "useTileCount": simple.get("useTileCount", 15),
        }

        # Add layer data
        layer_cols = simple.get("layer_cols", {})
        for layer_idx in sorted(layers.keys()):
            layer_key = f"layer_{layer_idx}"
            result[layer_key] = {
                "tiles": layers[layer_idx],
                "col": layer_cols.get(str(layer_idx), layer_cols.get(layer_idx, 7)),
            }

        # Add goals
        goals = simple.get("goals", {})
        result["goals"] = goals

        return result


@dataclass
class BenchmarkLevelSet:
    """A set of 10 benchmark levels for a specific difficulty tier."""
    tier: DifficultyTier
    levels: List[BenchmarkLevel]
    description: str

    def __post_init__(self):
        """Validate that set contains exactly 10 levels."""
        if len(self.levels) != 10:
            raise ValueError(f"Benchmark set must contain exactly 10 levels, got {len(self.levels)}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "description": self.description,
            "level_count": len(self.levels),
            "levels": [level.to_dict() for level in self.levels],
        }


# =============================================================================
# EASY TIER - 10 Levels (초보자도 클리어 가능)
# 특징: 레이어 1-2개, 기믹 없음 (ICE, GRASS, LINK, Craft 사용 안 함)
# 재설계: 2025-12-22 - 순수 매칭과 레이어 블로킹만 사용
# =============================================================================

EASY_LEVELS: List[BenchmarkLevel] = [
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
# MEDIUM TIER - 10 Levels (평균 플레이어 대상)
# =============================================================================

MEDIUM_LEVELS: List[BenchmarkLevel] = [
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
                {"layerIdx": 2, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
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

    # MEDIUM-09: 6종류, 3레이어, GRASS 1개
    BenchmarkLevel(
        id="medium_09",
        name="GRASS + 6종류 + 3레이어",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="6종류 타일, 3레이어, GRASS 1개. 복잡한 블로킹.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 7, 1: 7, 2: 7},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3},
            "max_moves": 28,
        },
        expected_clear_rates={
            "novice": 0.25,
            "casual": 0.48,
            "average": 0.68,
            "expert": 0.84,
            "optimal": 0.94,
        },
        tags=["3_layers", "grass", "variety", "complex"],
    ),

    # MEDIUM-10: 7종류, 3레이어, ICE 1개, 최종 챌린지
    BenchmarkLevel(
        id="medium_10",
        name="MEDIUM 최종 챌린지",
        difficulty_tier=DifficultyTier.MEDIUM,
        description="7종류 타일, 3레이어, ICE 1개. MEDIUM 티어 최고 난이도.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t7", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 8, 1: 8, 2: 8},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3},
            "max_moves": 30,
        },
        expected_clear_rates={
            "novice": 0.22,
            "casual": 0.45,
            "average": 0.65,
            "expert": 0.82,
            "optimal": 0.92,
        },
        tags=["3_layers", "ice", "variety", "challenging"],
    ),
]

# =============================================================================
# HARD TIER - 10 Levels (숙련자 대상)
# =============================================================================

HARD_LEVELS: List[BenchmarkLevel] = [
    # Hard levels will be added here
    # Placeholder for now - 10 levels required
]

# =============================================================================
# EXPERT TIER - 10 Levels (전문가 봇도 고전)
# =============================================================================

EXPERT_LEVELS: List[BenchmarkLevel] = [
    # Expert levels will be added here
    # Placeholder for now - 10 levels required
]

# =============================================================================
# IMPOSSIBLE TIER - 10 Levels (최적 봇도 실패)
# =============================================================================

IMPOSSIBLE_LEVELS: List[BenchmarkLevel] = [
    # Impossible levels will be added here
    # Placeholder for now - 10 levels required
]


def create_benchmark_set(tier: DifficultyTier, levels: List[BenchmarkLevel]) -> BenchmarkLevelSet:
    """Create a benchmark level set for a specific tier."""
    descriptions = {
        DifficultyTier.EASY: "초보자도 클리어 가능한 쉬운 난이도 (10개 레벨)",
        DifficultyTier.MEDIUM: "평균 플레이어를 대상으로 한 보통 난이도 (10개 레벨)",
        DifficultyTier.HARD: "숙련된 플레이어를 대상으로 한 어려운 난이도 (10개 레벨)",
        DifficultyTier.EXPERT: "전문가 봇도 고전하는 전문가 난이도 (10개 레벨)",
        DifficultyTier.IMPOSSIBLE: "최적 봇도 실패하는 불가능 난이도 (10개 레벨)",
    }

    return BenchmarkLevelSet(
        tier=tier,
        levels=levels,
        description=descriptions[tier],
    )


def get_benchmark_set(tier: DifficultyTier) -> BenchmarkLevelSet:
    """Get benchmark level set for a specific tier."""
    tier_levels = {
        DifficultyTier.EASY: EASY_LEVELS,
        DifficultyTier.MEDIUM: MEDIUM_LEVELS,
        DifficultyTier.HARD: HARD_LEVELS,
        DifficultyTier.EXPERT: EXPERT_LEVELS,
        DifficultyTier.IMPOSSIBLE: IMPOSSIBLE_LEVELS,
    }

    levels = tier_levels[tier]
    if len(levels) != 10:
        raise ValueError(f"Tier {tier.value} does not have 10 levels yet (has {len(levels)})")

    return create_benchmark_set(tier, levels)


def get_all_benchmark_sets() -> List[BenchmarkLevelSet]:
    """Get all benchmark level sets."""
    return [
        create_benchmark_set(DifficultyTier.EASY, EASY_LEVELS),
        # MEDIUM, HARD, EXPERT, IMPOSSIBLE will be added as they are completed
    ]


def get_benchmark_level_by_id(level_id: str) -> BenchmarkLevel:
    """Get a specific benchmark level by ID."""
    all_levels = EASY_LEVELS + MEDIUM_LEVELS + HARD_LEVELS + EXPERT_LEVELS + IMPOSSIBLE_LEVELS
    for level in all_levels:
        if level.id == level_id:
            return level
    raise ValueError(f"Benchmark level {level_id} not found")
