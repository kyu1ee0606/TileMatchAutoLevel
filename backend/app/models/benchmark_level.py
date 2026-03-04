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
# 특징: 8-10종류 타일, 3-4레이어, ICE+GRASS 복합 기믹
# 목표: Novice 10%, Casual 25%, Average 50%, Expert 80%, Optimal 95%
# =============================================================================

HARD_LEVELS: List[BenchmarkLevel] = [
    # HARD-01: 8종류, 3레이어, ICE 2개, GRASS 2개
    BenchmarkLevel(
        id="hard_01",
        name="ICE+GRASS 3레이어",
        difficulty_tier=DifficultyTier.HARD,
        description="8종류 타일, 3레이어, ICE 2개, GRASS 2개. 복합 기믹 도입.",
        level_json={
            "tiles": [
                # Layer 0 - ICE/GRASS 기믹 타일
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_5", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1 - 블로킹 타일
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_4", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                # Layer 2 - 메인 타일
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t8", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3},
            "max_moves": 22,
        },
        expected_clear_rates={
            "novice": 0.12,
            "casual": 0.28,
            "average": 0.52,
            "expert": 0.78,
            "optimal": 0.93,
        },
        tags=["3_layers", "ice", "grass", "complex"],
    ),

    # HARD-02: 9종류, 3레이어, ICE 3개
    BenchmarkLevel(
        id="hard_02",
        name="ICE 집중 + 9종류",
        difficulty_tier=DifficultyTier.HARD,
        description="9종류 타일, 3레이어, ICE 3개. ICE 집중 기믹.",
        level_json={
            "tiles": [
                # Layer 0 - ICE 기믹
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1 - 블로킹
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t5", "craft": "", "stackCount": 1},
                # Layer 2 - 메인
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_3", "tileType": "t9", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3},
            "max_moves": 20,
        },
        expected_clear_rates={
            "novice": 0.10,
            "casual": 0.25,
            "average": 0.50,
            "expert": 0.78,
            "optimal": 0.94,
        },
        tags=["3_layers", "ice", "9_types"],
    ),

    # HARD-03: 8종류, 4레이어, GRASS 3개
    BenchmarkLevel(
        id="hard_03",
        name="GRASS + 4레이어",
        difficulty_tier=DifficultyTier.HARD,
        description="8종류 타일, 4레이어, GRASS 3개. 깊은 블로킹 + GRASS.",
        level_json={
            "tiles": [
                # Layer 0 - GRASS 기믹
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3},
            "max_moves": 18,
        },
        expected_clear_rates={
            "novice": 0.08,
            "casual": 0.22,
            "average": 0.48,
            "expert": 0.76,
            "optimal": 0.92,
        },
        tags=["4_layers", "grass", "deep_blocking"],
    ),

    # HARD-04: 9종류, 4레이어, ICE 2개, LINK 1쌍
    BenchmarkLevel(
        id="hard_04",
        name="ICE+LINK 4레이어",
        difficulty_tier=DifficultyTier.HARD,
        description="9종류 타일, 4레이어, ICE 2개, LINK 1쌍. 복합 기믹.",
        level_json={
            "tiles": [
                # Layer 0 - ICE + LINK
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "4_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t9", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3},
            "max_moves": 18,
        },
        expected_clear_rates={
            "novice": 0.09,
            "casual": 0.24,
            "average": 0.50,
            "expert": 0.78,
            "optimal": 0.94,
        },
        tags=["4_layers", "ice", "link", "complex"],
    ),

    # HARD-05: 10종류, 3레이어, GRASS 4개
    BenchmarkLevel(
        id="hard_05",
        name="GRASS 집중 + 10종류",
        difficulty_tier=DifficultyTier.HARD,
        description="10종류 타일, 3레이어, GRASS 4개. 높은 다양성.",
        level_json={
            "tiles": [
                # Layer 0 - GRASS 기믹
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "8_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "8_2", "tileType": "t10", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3},
            "max_moves": 20,
        },
        expected_clear_rates={
            "novice": 0.08,
            "casual": 0.22,
            "average": 0.48,
            "expert": 0.76,
            "optimal": 0.93,
        },
        tags=["3_layers", "grass", "10_types", "high_cognitive"],
    ),

    # HARD-06: 9종류, 4레이어, ICE 3개, GRASS 1개
    BenchmarkLevel(
        id="hard_06",
        name="ICE+GRASS 4레이어",
        difficulty_tier=DifficultyTier.HARD,
        description="9종류 타일, 4레이어, ICE 3개, GRASS 1개. 복합 기믹.",
        level_json={
            "tiles": [
                # Layer 0
                {"layerIdx": 0, "pos": "3_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t9", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3},
            "max_moves": 17,
        },
        expected_clear_rates={
            "novice": 0.10,
            "casual": 0.26,
            "average": 0.52,
            "expert": 0.80,
            "optimal": 0.95,
        },
        tags=["4_layers", "ice", "grass", "complex"],
    ),

    # HARD-07: 10종류, 4레이어, LINK 2쌍
    BenchmarkLevel(
        id="hard_07",
        name="LINK 집중 + 10종류",
        difficulty_tier=DifficultyTier.HARD,
        description="10종류 타일, 4레이어, LINK 2쌍. 링크 기믹 중심.",
        level_json={
            "tiles": [
                # Layer 0 - LINK 기믹
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "3_2"}},
                {"layerIdx": 0, "pos": "5_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "link_west", "effect_data": {"linked_pos": "5_2"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t4", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_3", "tileType": "t10", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3},
            "max_moves": 18,
        },
        expected_clear_rates={
            "novice": 0.09,
            "casual": 0.24,
            "average": 0.50,
            "expert": 0.78,
            "optimal": 0.94,
        },
        tags=["4_layers", "link", "10_types"],
    ),

    # HARD-08: 9종류, 4레이어, 모든 기믹
    BenchmarkLevel(
        id="hard_08",
        name="전체 기믹 4레이어",
        difficulty_tier=DifficultyTier.HARD,
        description="9종류 타일, 4레이어, ICE 2개, GRASS 1개, LINK 1쌍.",
        level_json={
            "tiles": [
                # Layer 0 - 모든 기믹
                {"layerIdx": 0, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "6_3", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "link_north", "effect_data": {"linked_pos": "5_3"}},
                # Layer 1
                {"layerIdx": 1, "pos": "3_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_2", "tileType": "t5", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t9", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3},
            "max_moves": 16,
        },
        expected_clear_rates={
            "novice": 0.11,
            "casual": 0.27,
            "average": 0.53,
            "expert": 0.80,
            "optimal": 0.95,
        },
        tags=["4_layers", "ice", "grass", "link", "all_gimmicks"],
    ),

    # HARD-09: 10종류, 3레이어, ICE 4개
    BenchmarkLevel(
        id="hard_09",
        name="ICE 극한 + 10종류",
        difficulty_tier=DifficultyTier.HARD,
        description="10종류 타일, 3레이어, ICE 4개. ICE 집중.",
        level_json={
            "tiles": [
                # Layer 0 - ICE 집중
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "6_2", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "7_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "8_1", "tileType": "t10", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3},
            "max_moves": 18,
        },
        expected_clear_rates={
            "novice": 0.08,
            "casual": 0.22,
            "average": 0.48,
            "expert": 0.78,
            "optimal": 0.94,
        },
        tags=["3_layers", "ice", "10_types"],
    ),

    # HARD-10: 10종류, 4레이어, 복합 기믹, HARD 최종
    BenchmarkLevel(
        id="hard_10",
        name="HARD 최종 챌린지",
        difficulty_tier=DifficultyTier.HARD,
        description="10종류 타일, 4레이어, ICE 2개, GRASS 2개, LINK 1쌍. HARD 최종.",
        level_json={
            "tiles": [
                # Layer 0 - 복합 기믹
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_4", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3},
            "max_moves": 15,
        },
        expected_clear_rates={
            "novice": 0.10,
            "casual": 0.25,
            "average": 0.50,
            "expert": 0.80,
            "optimal": 0.95,
        },
        tags=["4_layers", "ice", "grass", "link", "10_types", "challenging"],
    ),
]

# =============================================================================
# EXPERT TIER - 10 Levels (전문가 봇도 고전)
# 특징: 10-12종류 타일, 4레이어, 다수의 복합 기믹
# 목표: Novice 2%, Casual 10%, Average 30%, Expert 65%, Optimal 90%
# =============================================================================

EXPERT_LEVELS: List[BenchmarkLevel] = [
    # EXPERT-01: 10종류, 4레이어, ICE 4개, GRASS 3개
    BenchmarkLevel(
        id="expert_01",
        name="ICE+GRASS 극한",
        difficulty_tier=DifficultyTier.EXPERT,
        description="10종류 타일, 4레이어, ICE 4개, GRASS 3개. 기믹 집중.",
        level_json={
            "tiles": [
                # Layer 0 - ICE/GRASS 집중
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "6_2", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t10", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3},
            "max_moves": 12,
        },
        expected_clear_rates={
            "novice": 0.03,
            "casual": 0.12,
            "average": 0.32,
            "expert": 0.65,
            "optimal": 0.88,
        },
        tags=["4_layers", "ice", "grass", "10_types", "extreme"],
    ),

    # EXPERT-02: 11종류, 4레이어, ICE 5개
    BenchmarkLevel(
        id="expert_02",
        name="ICE 11종류 극한",
        difficulty_tier=DifficultyTier.EXPERT,
        description="11종류 타일, 4레이어, ICE 5개. 극한 ICE.",
        level_json={
            "tiles": [
                # Layer 0 - ICE 집중
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t11", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3},
            "max_moves": 12,
        },
        expected_clear_rates={
            "novice": 0.02,
            "casual": 0.10,
            "average": 0.30,
            "expert": 0.63,
            "optimal": 0.88,
        },
        tags=["4_layers", "ice", "11_types"],
    ),

    # EXPERT-03: 12종류, 4레이어, GRASS 5개
    BenchmarkLevel(
        id="expert_03",
        name="GRASS 12종류 극한",
        difficulty_tier=DifficultyTier.EXPERT,
        description="12종류 타일, 4레이어, GRASS 5개. 극한 다양성.",
        level_json={
            "tiles": [
                # Layer 0 - GRASS 집중
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "6_2", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_2", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 12,
        },
        expected_clear_rates={
            "novice": 0.02,
            "casual": 0.09,
            "average": 0.28,
            "expert": 0.62,
            "optimal": 0.88,
        },
        tags=["4_layers", "grass", "12_types"],
    ),

    # EXPERT-04: 11종류, 4레이어, ICE+GRASS+LINK
    BenchmarkLevel(
        id="expert_04",
        name="전체 기믹 11종류",
        difficulty_tier=DifficultyTier.EXPERT,
        description="11종류 타일, 4레이어, ICE 3개, GRASS 2개, LINK 2쌍.",
        level_json={
            "tiles": [
                # Layer 0 - 전체 기믹
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_3", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "6_3"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t9", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t11", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3},
            "max_moves": 11,
        },
        expected_clear_rates={
            "novice": 0.02,
            "casual": 0.10,
            "average": 0.30,
            "expert": 0.65,
            "optimal": 0.90,
        },
        tags=["4_layers", "ice", "grass", "link", "11_types", "all_gimmicks"],
    ),

    # EXPERT-05: 12종류, 4레이어, ICE 6개
    BenchmarkLevel(
        id="expert_05",
        name="ICE 지옥 12종류",
        difficulty_tier=DifficultyTier.EXPERT,
        description="12종류 타일, 4레이어, ICE 6개. 극한 ICE.",
        level_json={
            "tiles": [
                # Layer 0 - ICE 지옥
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t9", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 11,
        },
        expected_clear_rates={
            "novice": 0.01,
            "casual": 0.08,
            "average": 0.26,
            "expert": 0.60,
            "optimal": 0.86,
        },
        tags=["4_layers", "ice", "12_types", "extreme"],
    ),

    # EXPERT-06: 11종류, 4레이어, GRASS 5개, LINK 2쌍
    BenchmarkLevel(
        id="expert_06",
        name="GRASS+LINK 극한",
        difficulty_tier=DifficultyTier.EXPERT,
        description="11종류 타일, 4레이어, GRASS 5개, LINK 2쌍.",
        level_json={
            "tiles": [
                # Layer 0 - GRASS + LINK
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "5_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t9", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t11", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3},
            "max_moves": 11,
        },
        expected_clear_rates={
            "novice": 0.02,
            "casual": 0.10,
            "average": 0.30,
            "expert": 0.65,
            "optimal": 0.90,
        },
        tags=["4_layers", "grass", "link", "11_types"],
    ),

    # EXPERT-07: 12종류, 4레이어, ICE+GRASS 복합
    BenchmarkLevel(
        id="expert_07",
        name="ICE+GRASS 12종류",
        difficulty_tier=DifficultyTier.EXPERT,
        description="12종류 타일, 4레이어, ICE 4개, GRASS 4개.",
        level_json={
            "tiles": [
                # Layer 0 - ICE+GRASS 복합
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 10,
        },
        expected_clear_rates={
            "novice": 0.01,
            "casual": 0.08,
            "average": 0.28,
            "expert": 0.62,
            "optimal": 0.88,
        },
        tags=["4_layers", "ice", "grass", "12_types"],
    ),

    # EXPERT-08: 11종류, 4레이어, LINK 4쌍
    BenchmarkLevel(
        id="expert_08",
        name="LINK 4쌍 극한",
        difficulty_tier=DifficultyTier.EXPERT,
        description="11종류 타일, 4레이어, LINK 4쌍. 링크 극한.",
        level_json={
            "tiles": [
                # Layer 0 - LINK 4쌍
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "3_2"}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "6_2"}},
                {"layerIdx": 0, "pos": "5_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "6_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "7_2", "tileType": "t11", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3},
            "max_moves": 11,
        },
        expected_clear_rates={
            "novice": 0.02,
            "casual": 0.10,
            "average": 0.30,
            "expert": 0.65,
            "optimal": 0.90,
        },
        tags=["4_layers", "link", "11_types", "extreme"],
    ),

    # EXPERT-09: 12종류, 4레이어, 모든 기믹
    BenchmarkLevel(
        id="expert_09",
        name="전체 기믹 12종류",
        difficulty_tier=DifficultyTier.EXPERT,
        description="12종류 타일, 4레이어, ICE 3개, GRASS 3개, LINK 2쌍.",
        level_json={
            "tiles": [
                # Layer 0 - 전체 기믹
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_3", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "6_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 10,
        },
        expected_clear_rates={
            "novice": 0.01,
            "casual": 0.08,
            "average": 0.28,
            "expert": 0.63,
            "optimal": 0.88,
        },
        tags=["4_layers", "ice", "grass", "link", "12_types", "all_gimmicks"],
    ),

    # EXPERT-10: 12종류, 4레이어, EXPERT 최종
    BenchmarkLevel(
        id="expert_10",
        name="EXPERT 최종 챌린지",
        difficulty_tier=DifficultyTier.EXPERT,
        description="12종류 타일, 4레이어, ICE 4개, GRASS 3개, LINK 2쌍. EXPERT 최종.",
        level_json={
            "tiles": [
                # Layer 0 - 전체 기믹 극한
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "6_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t11", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 9,
        },
        expected_clear_rates={
            "novice": 0.02,
            "casual": 0.10,
            "average": 0.30,
            "expert": 0.65,
            "optimal": 0.90,
        },
        tags=["4_layers", "ice", "grass", "link", "12_types", "all_gimmicks", "challenging"],
    ),
]

# =============================================================================
# IMPOSSIBLE TIER - 10 Levels (최적 봇도 실패)
# 특징: 12종류 타일, 4레이어, 극한 기믹 조합
# 목표: Novice 0%, Casual 2%, Average 10%, Expert 40%, Optimal 75%
# =============================================================================

IMPOSSIBLE_LEVELS: List[BenchmarkLevel] = [
    # IMPOSSIBLE-01: 12종류, 4레이어, ICE 8개
    BenchmarkLevel(
        id="impossible_01",
        name="ICE 지옥",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 8개. 극한 얼음.",
        level_json={
            "tiles": [
                # Layer 0 - ICE 지옥
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 8,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.02,
            "average": 0.10,
            "expert": 0.40,
            "optimal": 0.75,
        },
        tags=["4_layers", "ice", "12_types", "impossible"],
    ),

    # IMPOSSIBLE-02: 12종류, 4레이어, GRASS 8개
    BenchmarkLevel(
        id="impossible_02",
        name="GRASS 지옥",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, GRASS 8개. 극한 풀.",
        level_json={
            "tiles": [
                # Layer 0 - GRASS 지옥
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 8,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.02,
            "average": 0.10,
            "expert": 0.40,
            "optimal": 0.75,
        },
        tags=["4_layers", "grass", "12_types", "impossible"],
    ),

    # IMPOSSIBLE-03: 12종류, 4레이어, LINK 6쌍
    BenchmarkLevel(
        id="impossible_03",
        name="LINK 지옥",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, LINK 6쌍. 극한 링크.",
        level_json={
            "tiles": [
                # Layer 0 - LINK 지옥
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "2_4"}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "4_4"}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "5_4"}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "6_4"}},
                {"layerIdx": 0, "pos": "7_2", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "7_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "5_3", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "6_2", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 8,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.02,
            "average": 0.10,
            "expert": 0.40,
            "optimal": 0.75,
        },
        tags=["4_layers", "link", "12_types", "impossible"],
    ),

    # IMPOSSIBLE-04: 12종류, 4레이어, ICE 6개 + GRASS 4개
    BenchmarkLevel(
        id="impossible_04",
        name="ICE+GRASS 복합",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 6개, GRASS 4개. 복합 지옥.",
        level_json={
            "tiles": [
                # Layer 0 - ICE+GRASS 복합
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_5", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "5_5", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t12", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 7,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.02,
            "average": 0.10,
            "expert": 0.38,
            "optimal": 0.73,
        },
        tags=["4_layers", "ice", "grass", "12_types", "impossible"],
    ),

    # IMPOSSIBLE-05: 12종류, 4레이어, 모든 기믹
    BenchmarkLevel(
        id="impossible_05",
        name="전체 기믹 지옥",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 5개, GRASS 4개, LINK 3쌍.",
        level_json={
            "tiles": [
                # Layer 0 - 전체 기믹
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "7_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t11", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "6_3"}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t12", "craft": "", "stackCount": 1,
                 "effect": "link_north", "effect_data": {"linked_pos": "6_3"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t4", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t12", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "3_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "4_1", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 7,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.02,
            "average": 0.10,
            "expert": 0.40,
            "optimal": 0.75,
        },
        tags=["4_layers", "ice", "grass", "link", "12_types", "all_gimmicks", "impossible"],
    ),

    # IMPOSSIBLE-06 ~ IMPOSSIBLE-10: 추가 불가능 레벨
    BenchmarkLevel(
        id="impossible_06",
        name="ICE 극한 V2",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 10개. 극한 ICE V2.",
        level_json={
            "tiles": [
                # Layer 0 - ICE 극한
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "8_3", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t12", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 6,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.01,
            "average": 0.08,
            "expert": 0.35,
            "optimal": 0.70,
        },
        tags=["4_layers", "ice", "12_types", "impossible", "extreme"],
    ),

    BenchmarkLevel(
        id="impossible_07",
        name="GRASS+LINK 복합",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, GRASS 6개, LINK 4쌍.",
        level_json={
            "tiles": [
                # Layer 0 - GRASS+LINK
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "5_2"}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "7_4"}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t12", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 6,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.02,
            "average": 0.10,
            "expert": 0.40,
            "optimal": 0.75,
        },
        tags=["4_layers", "grass", "link", "12_types", "impossible"],
    ),

    BenchmarkLevel(
        id="impossible_08",
        name="ICE+LINK 극한",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 6개, LINK 4쌍.",
        level_json={
            "tiles": [
                # Layer 0 - ICE+LINK
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "2_5"}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "4_4"}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "6_4"}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "4_2"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t12", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "6_3", "tileType": "t10", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 6,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.01,
            "average": 0.08,
            "expert": 0.38,
            "optimal": 0.72,
        },
        tags=["4_layers", "ice", "link", "12_types", "impossible"],
    ),

    BenchmarkLevel(
        id="impossible_09",
        name="전체 기믹 극한",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 5개, GRASS 5개, LINK 4쌍.",
        level_json={
            "tiles": [
                # Layer 0 - 전체 기믹 극한
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "7_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "8_3", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t11", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "3_4"}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t12", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "6_3"}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "8_3"}},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "2_5"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t6", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t12", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t2", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t3", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t4", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_2", "tileType": "t5", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_3", "tileType": "t6", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 5,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.01,
            "average": 0.08,
            "expert": 0.35,
            "optimal": 0.70,
        },
        tags=["4_layers", "ice", "grass", "link", "12_types", "all_gimmicks", "impossible", "extreme"],
    ),

    BenchmarkLevel(
        id="impossible_10",
        name="IMPOSSIBLE 최종 챌린지",
        difficulty_tier=DifficultyTier.IMPOSSIBLE,
        description="12종류 타일, 4레이어, ICE 6개, GRASS 6개, LINK 5쌍. 절대 불가능.",
        level_json={
            "tiles": [
                # Layer 0 - 최종 극한
                {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "2_4", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "4_4", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_2", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "6_4", "tileType": "t6", "craft": "", "stackCount": 1,
                 "effect": "ice", "effect_data": {"remaining": 3}},
                {"layerIdx": 0, "pos": "3_3", "tileType": "t7", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_3", "tileType": "t8", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "7_3", "tileType": "t9", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "3_5", "tileType": "t10", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 2}},
                {"layerIdx": 0, "pos": "5_5", "tileType": "t11", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "7_5", "tileType": "t12", "craft": "", "stackCount": 1,
                 "effect": "grass", "effect_data": {"remaining": 1}},
                {"layerIdx": 0, "pos": "2_3", "tileType": "t1", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "2_5"}},
                {"layerIdx": 0, "pos": "3_2", "tileType": "t2", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "4_2"}},
                {"layerIdx": 0, "pos": "5_2", "tileType": "t3", "craft": "", "stackCount": 1,
                 "effect": "link_south", "effect_data": {"linked_pos": "6_2"}},
                {"layerIdx": 0, "pos": "4_3", "tileType": "t4", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "4_5"}},
                {"layerIdx": 0, "pos": "6_3", "tileType": "t5", "craft": "", "stackCount": 1,
                 "effect": "link_east", "effect_data": {"linked_pos": "6_5"}},
                # Layer 1
                {"layerIdx": 1, "pos": "2_2", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "3_3", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "4_2", "tileType": "t8", "craft": "", "stackCount": 1},
                {"layerIdx": 1, "pos": "5_3", "tileType": "t9", "craft": "", "stackCount": 1},
                # Layer 2
                {"layerIdx": 2, "pos": "2_1", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "2_2", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_2", "tileType": "t12", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "3_3", "tileType": "t6", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_2", "tileType": "t7", "craft": "", "stackCount": 1},
                {"layerIdx": 2, "pos": "4_3", "tileType": "t8", "craft": "", "stackCount": 1},
                # Layer 3
                {"layerIdx": 3, "pos": "1_1", "tileType": "t9", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_2", "tileType": "t10", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "1_3", "tileType": "t11", "craft": "", "stackCount": 1},
                {"layerIdx": 3, "pos": "2_1", "tileType": "t12", "craft": "", "stackCount": 1},
            ],
            "layer_cols": {0: 9, 1: 9, 2: 9, 3: 9},
            "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3, "t5": 3, "t6": 3, "t7": 3, "t8": 3, "t9": 3, "t10": 3, "t11": 3, "t12": 3},
            "max_moves": 5,
        },
        expected_clear_rates={
            "novice": 0.00,
            "casual": 0.00,
            "average": 0.05,
            "expert": 0.30,
            "optimal": 0.65,
        },
        tags=["4_layers", "ice", "grass", "link", "12_types", "all_gimmicks", "impossible", "final_challenge"],
    ),
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
