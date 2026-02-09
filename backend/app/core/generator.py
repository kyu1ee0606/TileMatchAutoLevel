"""Level generator engine with difficulty targeting."""
import logging
import random
import time
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============ GBoost-Style Level Range Gimmick Configuration ============
# 인게임 확정 기믹 언락 스케줄 (2026.02 최종 확정 - 13개 기믹)
# Gimmicks are progressively introduced to match the natural learning curve

def get_gboost_style_gimmicks(level_number: int) -> Dict[str, Any]:
    """
    Get recommended gimmick configuration based on level number.

    인게임 확정 기믹 언락 순서 (총 13개):
    - Stage   1-9:   No gimmicks (tutorial/learning phase)
    - Stage  10-19:  craft only (공예 - 첫 번째 기믹)
    - Stage  20-29:  +stack (스택) [간격: 10]
    - Stage  30-49:  +ice (얼음) [간격: 10]
    - Stage  50-79:  +link (연결) [간격: 20]
    - Stage  80-109: +chain (사슬) [간격: 30]
    - Stage 110-149: +key (버퍼잠금) [간격: 30] ★신규
    - Stage 150-189: +grass (풀) [간격: 40]
    - Stage 190-239: +unknown (상자) [간격: 40]
    - Stage 240-289: +curtain (커튼) [간격: 50]
    - Stage 290-339: +bomb (폭탄) [간격: 50]
    - Stage 340-389: +time_attack (타임어택) [간격: 50] ★신규
    - Stage 390-439: +frog (개구리) [간격: 50]
    - Stage 440+:    +teleport (텔레포터, 모든 기믹) [간격: 50]

    특수 기믹 설정:
    - key: unlockTile 필드로 버퍼 잠금 타일 수 설정
    - time_attack: timea 필드로 제한 시간(초) 설정

    Args:
        level_number: The level number (1-based)

    Returns:
        Dict with:
        - obstacle_types: List of allowed gimmick types
        - gimmick_intensity: Suggested intensity (0.0-1.5)
        - description: Human-readable description
    """
    if level_number < 10:
        return {
            "obstacle_types": [],
            "gimmick_intensity": 0.0,
            "description": "튜토리얼 - 기믹 없음"
        }
    elif level_number < 20:
        return {
            "obstacle_types": ["craft"],
            "gimmick_intensity": 0.2,
            "description": "첫 번째 기믹 - craft(공예)"
        }
    elif level_number < 30:
        return {
            "obstacle_types": ["craft", "stack"],
            "gimmick_intensity": 0.25,
            "description": "목표 기믹 - craft + stack"
        }
    elif level_number < 50:
        return {
            "obstacle_types": ["craft", "stack", "ice"],
            "gimmick_intensity": 0.3,
            "description": "얼음 추가 - +ice"
        }
    elif level_number < 80:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link"],
            "gimmick_intensity": 0.4,
            "description": "연결 추가 - +link"
        }
    elif level_number < 110:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain"],
            "gimmick_intensity": 0.5,
            "description": "사슬 추가 - +chain"
        }
    elif level_number < 150:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key"],
            "gimmick_intensity": 0.55,
            "description": "버퍼잠금 추가 - +key"
        }
    elif level_number < 190:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass"],
            "gimmick_intensity": 0.6,
            "description": "풀 추가 - +grass"
        }
    elif level_number < 240:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown"],
            "gimmick_intensity": 0.65,
            "description": "상자 추가 - +unknown"
        }
    elif level_number < 290:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain"],
            "gimmick_intensity": 0.7,
            "description": "커튼 추가 - +curtain"
        }
    elif level_number < 340:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb"],
            "gimmick_intensity": 0.75,
            "description": "폭탄 추가 - +bomb"
        }
    elif level_number < 390:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb", "time_attack"],
            "gimmick_intensity": 0.8,
            "description": "타임어택 추가 - +time_attack"
        }
    elif level_number < 440:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb", "time_attack", "frog"],
            "gimmick_intensity": 0.9,
            "description": "개구리 추가 - +frog"
        }
    else:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb", "time_attack", "frog", "teleport"],
            "gimmick_intensity": 1.0,
            "description": "모든 기믹 사용 가능 (13개)"
        }


def get_gboost_style_layer_config(level_number: int) -> Dict[str, Any]:
    """
    Get recommended layer configuration based on level number.

    Based on analysis of GBoost production levels (221 human-designed levels)
    and commercial games (Tile Explorer, Triple Tile, Tile Master 3D).

    1500레벨 전체에 대한 점진적 설정:
    - Level 1-10: Tutorial - 1-2 layers, 7x7, 9-18 tiles
    - Level 11-30: Early - 2-3 layers, 7x7, 18-36 tiles
    - Level 31-60: Early-Mid - 3-4 layers, 7x7, 30-50 tiles
    - Level 61-100: Mid - 4-5 layers, 10x10, 50-80 tiles
    - Level 101-225: Mid-Late - 4-5 layers, 10x10, 60-90 tiles
    - Level 226-600: Standard - 4-5 layers, 10x10, 70-100 tiles
    - Level 601-1125: Advanced - 5 layers, 10x10, 75-105 tiles
    - Level 1126-1500: Expert - 5-6 layers, 10x10, 84-120 tiles
    - Level 1501+: Master - 5-6 layers, 10x10, 96-120 tiles

    Args:
        level_number: The level number (1-based)

    Returns:
        Dict with layer and grid configuration including tile_types
    """
    if level_number <= 10:
        return {
            "min_layers": 1,
            "max_layers": 2,
            "cols": 7,
            "rows": 7,
            "total_tile_range": (9, 18),
            "tile_types": 4,  # 4종류 (튜토리얼)
            "description": "Tutorial - minimal complexity"
        }
    elif level_number <= 30:
        return {
            "min_layers": 2,
            "max_layers": 3,
            "cols": 7,
            "rows": 7,
            "total_tile_range": (18, 36),
            "tile_types": 4,  # 4종류
            "description": "Early game - basic layering"
        }
    elif level_number <= 60:
        return {
            "min_layers": 3,
            "max_layers": 4,
            "cols": 7,
            "rows": 7,
            "total_tile_range": (30, 50),
            "tile_types": 5,  # 5종류
            "description": "Early-mid game - moderate complexity"
        }
    elif level_number <= 100:
        return {
            "min_layers": 4,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (50, 80),
            "tile_types": 5,  # 5종류
            "description": "Mid game - larger grid"
        }
    elif level_number <= 225:
        return {
            "min_layers": 4,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (60, 90),
            "tile_types": 5,  # 5종류
            "description": "Mid-late game - S등급 마무리"
        }
    elif level_number <= 600:
        return {
            "min_layers": 4,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (70, 100),
            "tile_types": 6,  # 6종류 (A등급)
            "description": "Standard game - A등급 주력"
        }
    elif level_number <= 1125:
        return {
            "min_layers": 5,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (75, 105),
            "tile_types": 6,  # 6종류 (B등급 ★핵심 재미 구간)
            "description": "Advanced game - B등급 핵심 재미"
        }
    elif level_number <= 1500:
        return {
            "min_layers": 5,
            "max_layers": 6,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (84, 120),
            "tile_types": 7,  # 7종류 (C/D등급 - 7슬롯 독과 균형)
            "description": "Expert game - C/D등급 도전"
        }
    else:
        return {
            "min_layers": 5,
            "max_layers": 6,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (96, 120),
            "tile_types": 8,  # 8종류 (엔드게임)
            "description": "Master game - 엔드게임"
        }


def get_lowest_difficulty_positions(count: int = 3) -> Set[int]:
    """
    톱니바퀴 패턴에서 가장 낮은 난이도의 position들을 동적으로 찾습니다.

    Args:
        count: 찾을 position 개수 (기본 3개)

    Returns:
        가장 낮은 난이도의 position 집합
    """
    from ..models.leveling_config import SAWTOOTH_PATTERN_10

    # (position, difficulty) 튜플 리스트 생성 후 난이도 기준 정렬
    indexed_difficulties = [(i, diff) for i, diff in enumerate(SAWTOOTH_PATTERN_10)]
    sorted_by_difficulty = sorted(indexed_difficulties, key=lambda x: x[1])

    # 가장 낮은 count개의 position 반환
    return {pos for pos, _ in sorted_by_difficulty[:count]}


# 캐시: 톱니바퀴 패턴에서 가장 낮은 3개 난이도 position (lazy 초기화)
_LOWEST_DIFFICULTY_POSITIONS_CACHE: Optional[Set[int]] = None


def _get_lowest_positions() -> Set[int]:
    """캐시된 lowest difficulty positions 반환 (lazy 초기화)"""
    global _LOWEST_DIFFICULTY_POSITIONS_CACHE
    if _LOWEST_DIFFICULTY_POSITIONS_CACHE is None:
        _LOWEST_DIFFICULTY_POSITIONS_CACHE = get_lowest_difficulty_positions(3)
    return _LOWEST_DIFFICULTY_POSITIONS_CACHE


def get_tile_types_for_level(level_number: int) -> List[str]:
    """
    Get recommended tile types list based on level number.

    톱니바퀴 패턴(10레벨 순환) 기반 타일 종류 선택:
    - 10레벨 주기 내 가장 낮은 난이도 3개 레벨: 실제 타일 타입 5가지 사용
    - 나머지 7개 레벨: t0 사용 (클라이언트에서 랜덤 타일로 변환)

    타일 그룹 순환 (30레벨마다 전체 순환, 쉬운 레벨에만 적용):
    - 그룹 0: t1~t5 (레벨 1-10, 31-40, 61-70...)
    - 그룹 1: t6~t10 (레벨 11-20, 41-50, 71-80...)
    - 그룹 2: t11~t15 (레벨 21-30, 51-60, 81-90...)

    [동적 난이도 기반 선택]
    SAWTOOTH_PATTERN_10에서 가장 낮은 난이도 3개 position을 동적으로 찾아 적용.
    현재 패턴 기준: position 0, 1, 2 (난이도 0.0, 0.1, 0.2)
    패턴이 변경되면 자동으로 새로운 가장 낮은 position들이 선택됨.

    Args:
        level_number: The level number (1-based)

    Returns:
        List of tile type strings (t0 for random, or t1~t15 for fixed)
    """
    # 10레벨 주기 내 위치 (0~9)
    position_in_10 = (level_number - 1) % 10

    # 톱니바퀴 패턴에서 가장 낮은 난이도 3개 position에 해당하면 실제 타일 사용
    lowest_positions = _get_lowest_positions()
    if position_in_10 in lowest_positions:
        # 레벨에 따른 타일 종류 수 결정 (난이도 스케일링)
        config = get_gboost_style_layer_config(level_number)
        tile_count = config.get("tile_types", 5)

        # 30레벨마다 타일 그룹 순환 (0, 1, 2)
        group_index = ((level_number - 1) // 10) % 3

        # 그룹별 타일 풀 정의
        if group_index == 0:
            base_tiles = ["t1", "t2", "t3", "t4", "t5"]
        elif group_index == 1:
            base_tiles = ["t6", "t7", "t8", "t9", "t10"]
        else:
            base_tiles = ["t11", "t12", "t13", "t14", "t15"]

        # tile_count에 맞게 조정 (최소 3개 보장)
        tile_count = max(3, min(tile_count, len(base_tiles)))
        return base_tiles[:tile_count]
    else:
        # 나머지 7개 레벨은 t0 사용 (클라이언트에서 랜덤 타일로 변환)
        return ["t0"]


def get_use_tile_count_for_level(level_number: int) -> int:
    """
    Get useTileCount setting for level.

    레벨에 따른 타일 종류 수:
    - Level 1-30: 4종류
    - Level 31-60: 5종류
    - Level 61-225: 5종류
    - Level 226-600: 6종류
    - Level 601-1125: 6종류
    - Level 1126-1500: 7종류
    - Level 1501+: 8종류

    Args:
        level_number: The level number (1-based)

    Returns:
        useTileCount value (1-15)
    """
    config = get_gboost_style_layer_config(level_number)
    return config.get("tile_types", 5)

from ..models.level import (
    GenerationParams,
    GenerationResult,
    DifficultyGrade,
    TILE_TYPES,
)
from ..models.leveling_config import calculate_hidden_tile_ratio
from .analyzer import get_analyzer


class LevelGenerator:
    """Generates levels with target difficulty."""

    # Default tile types for generation
    # NOTE: t0 is excluded - use t1~t5 for consistent tile types
    # t0 was previously used as "random tile" but causes issues with bot simulation
    DEFAULT_TILE_TYPES = ["t1", "t2", "t3", "t4", "t5"]
    OBSTACLE_TILE_TYPES = ["t8", "t9"]
    SPECIAL_TILE_TYPES = ["t10", "t11", "t12", "t14", "t15"]
    # All goal types - craft and stack with all 4 directions (s=south, n=north, e=east, w=west)
    GOAL_TYPES = [
        "craft_s", "craft_n", "craft_e", "craft_w",
        "stack_s", "stack_n", "stack_e", "stack_w"
    ]

    # Generation parameters
    MAX_ADJUSTMENT_ITERATIONS = 50
    DIFFICULTY_TOLERANCE = 3.0  # ±3 points (tighter tolerance for better accuracy)

    # Maximum useTileCount - user can specify up to 15 tile types
    # Note: More tile types = harder levels (with 7-slot dock)
    MAX_USE_TILE_COUNT = 15

    # Level similarity threshold (0.0-1.0) - levels more similar than this are considered duplicates
    SIMILARITY_THRESHOLD = 0.75

    # Pattern diversity tracking - class-level to persist across instances
    # Tracks recently used pattern categories to avoid repetition between levels
    _recent_pattern_categories: List[int] = []
    _PATTERN_HISTORY_SIZE = 5  # Remember last N pattern categories to avoid

    # ============================================================
    # Tile Creation Helper Methods
    # ============================================================
    # All tile data structures should be created through these methods
    # to ensure consistency and easy modification of tile format.

    @staticmethod
    def _create_tile(tile_type: str, attribute: str = "", extra: Optional[List] = None) -> List:
        """Create a tile data structure.

        Args:
            tile_type: The tile type (t1-t6, craft_s, stack_n, etc.)
            attribute: The attribute/gimmick (chain, ice_1, frog, etc.)
            extra: Additional data (goal count, teleport pair id, etc.)

        Returns:
            Tile data as list: [tile_type, attribute] or [tile_type, attribute, extra]
        """
        if extra is not None:
            return [tile_type, attribute, extra]
        return [tile_type, attribute]

    @staticmethod
    def _place_tile(tiles: Dict[str, List], pos: str, tile_type: str,
                    attribute: str = "", extra: Optional[List] = None) -> None:
        """Place a tile at the specified position.

        Args:
            tiles: The tiles dictionary to modify
            pos: Position string (e.g., "3_4")
            tile_type: The tile type
            attribute: The attribute/gimmick
            extra: Additional data
        """
        tiles[pos] = LevelGenerator._create_tile(tile_type, attribute, extra)

    # Minimum count for craft/stack goals (match-3 game rule)
    MIN_GOAL_COUNT = 3

    # Minimum total tile count for playable levels (industry standard: 18-30 for tutorial)
    # Based on Tile Buster, Triple Tile research: minimum 18 tiles (6 sets of 3)
    # Exception: Level 1-5 tutorial levels can have fewer tiles
    MIN_TILE_COUNT = 18
    TUTORIAL_MIN_TILE_COUNT = 9  # Level 1-5 tutorial: minimum 3 sets (9 tiles)

    @staticmethod
    def _create_goal_tile(goal_type: str, count: int) -> List:
        """Create a goal tile (craft/stack) data structure.

        Args:
            goal_type: Goal type with direction (craft_s, stack_n, etc.)
            count: Number of tiles the goal produces (minimum 3)

        Returns:
            Goal tile data as list: [goal_type, "", [count]]
        """
        # Enforce minimum count of 3 for match-3 game rule
        safe_count = max(LevelGenerator.MIN_GOAL_COUNT, count)
        return [goal_type, "", [safe_count]]

    @staticmethod
    def _place_goal_tile(tiles: Dict[str, List], pos: str, goal_type: str, count: int) -> None:
        """Place a goal tile at the specified position.

        Args:
            tiles: The tiles dictionary to modify
            pos: Position string
            goal_type: Goal type with direction
            count: Number of tiles the goal produces
        """
        tiles[pos] = LevelGenerator._create_goal_tile(goal_type, count)

    @staticmethod
    def _get_tile_type(tile_data: List) -> Optional[str]:
        """Extract tile type from tile data.

        Args:
            tile_data: Tile data list

        Returns:
            Tile type string or None if invalid
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 0:
            return tile_data[0]
        return None

    @staticmethod
    def _get_tile_attribute(tile_data: List) -> Optional[str]:
        """Extract attribute from tile data.

        Args:
            tile_data: Tile data list

        Returns:
            Attribute string or None if not present
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 1:
            return tile_data[1]
        return None

    @staticmethod
    def _get_tile_extra(tile_data: List) -> Optional[List]:
        """Extract extra data from tile data.

        Args:
            tile_data: Tile data list

        Returns:
            Extra data list or None if not present
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 2:
            return tile_data[2]
        return None

    @staticmethod
    def _set_tile_attribute(tile_data: List, attribute: str) -> None:
        """Set the attribute of a tile in place.

        Args:
            tile_data: Tile data list to modify
            attribute: New attribute value
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 1:
            tile_data[1] = attribute

    @staticmethod
    def _set_tile_extra(tile_data: List, extra: List) -> None:
        """Set the extra data of a tile in place.

        Args:
            tile_data: Tile data list to modify
            extra: New extra data value
        """
        if tile_data and isinstance(tile_data, list):
            if len(tile_data) > 2:
                tile_data[2] = extra
            elif len(tile_data) == 2:
                tile_data.append(extra)

    @staticmethod
    def calculate_level_similarity(level1: Dict[str, Any], level2: Dict[str, Any]) -> float:
        """Calculate similarity between two levels based on layout patterns.

        Returns a score from 0.0 (completely different) to 1.0 (identical).

        Compares:
        - Tile positions per layer (weighted by layer)
        - Total tile count
        - Layer structure
        """
        try:
            map1 = level1.get("map", level1)
            map2 = level2.get("map", level2)

            # Extract layer data
            layers1 = {}
            layers2 = {}

            for key, value in map1.items():
                if key.startswith("layer") and isinstance(value, dict):
                    layer_idx = int(key.replace("layer", ""))
                    positions = set(value.get("position", {}).keys())
                    layers1[layer_idx] = positions

            for key, value in map2.items():
                if key.startswith("layer") and isinstance(value, dict):
                    layer_idx = int(key.replace("layer", ""))
                    positions = set(value.get("position", {}).keys())
                    layers2[layer_idx] = positions

            if not layers1 or not layers2:
                return 0.0

            # Compare layer structure
            all_layers = set(layers1.keys()) | set(layers2.keys())
            layer_count_sim = 1.0 - abs(len(layers1) - len(layers2)) / max(len(all_layers), 1)

            # Compare positions per layer with weighted importance
            position_similarities = []
            for layer_idx in all_layers:
                pos1 = layers1.get(layer_idx, set())
                pos2 = layers2.get(layer_idx, set())

                if not pos1 and not pos2:
                    continue

                intersection = len(pos1 & pos2)
                union = len(pos1 | pos2)
                jaccard = intersection / union if union > 0 else 0.0

                # Higher layers (more visible) weighted more
                weight = 1.0 + layer_idx * 0.2
                position_similarities.append((jaccard, weight))

            if not position_similarities:
                return layer_count_sim * 0.5

            weighted_pos_sim = sum(s * w for s, w in position_similarities) / sum(w for _, w in position_similarities)

            # Compare total tile counts
            total1 = sum(len(p) for p in layers1.values())
            total2 = sum(len(p) for p in layers2.values())
            count_sim = 1.0 - abs(total1 - total2) / max(total1, total2, 1)

            # Final weighted similarity
            similarity = (
                weighted_pos_sim * 0.6 +  # Position similarity most important
                layer_count_sim * 0.2 +   # Layer structure
                count_sim * 0.2           # Total count
            )

            return min(1.0, max(0.0, similarity))

        except Exception as e:
            logger.warning(f"Error calculating level similarity: {e}")
            return 0.0

    @staticmethod
    def is_too_similar(new_level: Dict[str, Any], recent_levels: List[Dict[str, Any]], threshold: float = None) -> bool:
        """Check if new level is too similar to any recent levels.

        Args:
            new_level: The newly generated level
            recent_levels: List of recently generated levels to compare against
            threshold: Similarity threshold (default: SIMILARITY_THRESHOLD)

        Returns:
            True if the level is too similar to any recent level
        """
        if threshold is None:
            threshold = LevelGenerator.SIMILARITY_THRESHOLD

        for recent_level in recent_levels:
            similarity = LevelGenerator.calculate_level_similarity(new_level, recent_level)
            if similarity > threshold:
                logger.debug(f"Level too similar: {similarity:.2f} > {threshold}")
                return True

        return False

    def generate(self, params: GenerationParams) -> GenerationResult:
        """
        Generate a level with target difficulty.

        Args:
            params: Generation parameters including target difficulty.

        Returns:
            GenerationResult with generated level and actual difficulty.

        Raises:
            ValueError: If layer_tile_configs total is not divisible by 3.
        """
        start_time = time.time()

        # Check if user has specified per-layer tile configs OR total_tile_count (strict mode)
        # In strict mode, we respect user's tile counts exactly without adjustment
        has_strict_tile_config = (
            (bool(params.layer_tile_configs) and len(params.layer_tile_configs) > 0) or
            (params.total_tile_count is not None)
        )

        # Calculate total goal inner tiles (craft_s with count=3 means 3 additional tiles inside)
        # Goal tiles are visual tiles that CONTAIN inner tiles, not replace them
        # Example: 21+21 tiles + craft_s(3) = 42 visual tiles + 3 inner tiles = 45 actual tiles
        goal_inner_tiles = 0
        goals = params.goals if params.goals is not None else [{"type": "craft_s", "count": 3}]
        if goals:
            for goal in goals:
                # Handle both dict and GoalConfig objects
                if hasattr(goal, 'count'):
                    goal_count = goal.count
                else:
                    goal_count = goal.get("count", 3)
                goal_inner_tiles += goal_count

        # Validate: In strict mode, total tile count (including goal inner tiles) must be divisible by 3
        if has_strict_tile_config:
            # Get config tiles from layer_tile_configs or total_tile_count
            if params.layer_tile_configs and len(params.layer_tile_configs) > 0:
                config_tiles = sum(config.count for config in params.layer_tile_configs)
            elif params.total_tile_count is not None:
                config_tiles = params.total_tile_count
            else:
                config_tiles = 0

            # Actual tiles = visual tiles + goal inner tiles
            # Goal tile itself is counted in config_tiles, but it contains inner tiles that need to be added
            # Example: 42 config tiles + 3 inner tiles = 45 actual tiles
            actual_tiles = config_tiles + goal_inner_tiles

            if actual_tiles % 3 != 0:
                raise ValueError(
                    f"실제 타일 수({actual_tiles})가 3의 배수가 아닙니다. "
                    f"(설정 타일 {config_tiles}개 + 골 내부 타일 {goal_inner_tiles}개 = {actual_tiles}개) "
                    f"클리어가 불가능하므로 생성할 수 없습니다. "
                    f"(예: 총 설정 타일을 {config_tiles - (actual_tiles % 3)} 또는 {config_tiles + (3 - actual_tiles % 3)}로 조정)"
                )

        # Create initial level structure
        level = self._create_base_structure(params)

        # Populate layers with tiles based on target difficulty
        level = self._populate_layers(level, params)

        # Add obstacles and attributes
        level = self._add_obstacles(level, params)

        # Add goals (in strict mode, replace existing tiles instead of adding)
        level = self._add_goals(level, params, strict_mode=has_strict_tile_config)

        # CRITICAL: Fix any goals with count below MIN_GOAL_COUNT
        # This ensures all craft/stack goals have at least 3 tiles
        level = self._fix_goal_counts(level)

        # Adjust to target difficulty (only if NOT using strict tile config)
        # When user specifies exact tile counts, don't modify them for difficulty
        if not has_strict_tile_config:
            # Pass max tile count to prevent adding tiles beyond the target
            max_tiles = params.total_tile_count if params.total_tile_count else None
            # Pass tutorial_gimmick to preserve it during difficulty adjustment
            tutorial_gimmick = getattr(params, 'tutorial_gimmick', None)
            level = self._adjust_difficulty(level, params.target_difficulty, max_tiles=max_tiles, params=params, tutorial_gimmick=tutorial_gimmick)

        # CRITICAL: Ensure tile count is divisible by 3 (only if NOT using strict config)
        # When user specifies exact counts, they are responsible for divisibility
        if not has_strict_tile_config:
            level = self._ensure_tile_count_divisible_by_3(level, params)

        # CRITICAL: Validate obstacles AFTER all tile modifications
        # This ensures all obstacles (chain, link, grass) have valid clearable neighbors
        level = self._validate_and_fix_obstacles(level)

        # Final check: if obstacle removal broke divisibility, fix it again (only if not strict)
        if not has_strict_tile_config:
            level = self._ensure_tile_count_divisible_by_3(level, params)
            # Re-validate obstacles since tile removal might have broken chain/link neighbors
            level = self._validate_and_fix_obstacles(level)

        # CRITICAL: Ensure tutorial gimmicks are maintained after all validations
        # Tutorial gimmick count may have been reduced by obstacle validation
        tutorial_gimmick = getattr(params, 'tutorial_gimmick', None)
        tutorial_gimmick_min_count = getattr(params, 'tutorial_gimmick_min_count', 3)
        if tutorial_gimmick:
            if tutorial_gimmick == "unknown":
                # Unknown gimmicks need special handling - must be covered by upper layers
                level = self._ensure_unknown_tutorial_count(level, tutorial_gimmick_min_count)
            else:
                level = self._ensure_tutorial_gimmick_count(level, tutorial_gimmick, tutorial_gimmick_min_count)

        # NOTE: Craft/Stack boxes wait if output position has a tile (during GAMEPLAY).
        # But during GENERATION, we should ensure no tiles exist in output positions.
        # Relocate (not delete) tiles to maintain counts.
        level = self._relocate_tiles_from_goal_outputs(level)

        # CRITICAL: Validate frog positions after ALL tile modifications
        # Frogs must be selectable at spawn (not covered by upper layers)
        # This fixes frogs that became covered due to tiles added in later steps
        level = self._validate_and_fix_frog_positions(level)

        # FINAL VALIDATION: Ensure level is playable (all tile types divisible by 3, minimum tiles)
        validation_result = self._validate_playability(level, params.level_number)
        if not validation_result["is_playable"]:
            logger.warning(
                f"Generated level may not be playable! "
                f"Total tiles: {validation_result['total_tiles']}, "
                f"Min required: {validation_result.get('min_required', 'N/A')}, "
                f"Below minimum: {validation_result.get('below_minimum', False)}, "
                f"Types with bad count: {validation_result['bad_types']}"
            )

            # If below minimum tile count, add more tiles
            if validation_result.get("below_minimum", False):
                level = self._ensure_minimum_tiles(level, params, validation_result.get("min_required", self.MIN_TILE_COUNT))
                # Re-validate after adding tiles
                validation_result = self._validate_playability(level, params.level_number)

            # Try aggressive fix for remaining issues (not divisible by 3, etc.)
            if not validation_result["is_playable"]:
                level = self._force_fix_tile_counts(level, params)

        # Calculate final metrics
        analyzer = get_analyzer()
        report = analyzer.analyze(level)

        # Auto-calculate max_moves based on total tiles
        level["max_moves"] = self._calculate_max_moves(level)

        # Set special gimmick fields based on level number (레벨 전역 설정)
        # key와 time_attack은 타일 레벨 기믹이 아닌 레벨 전역 설정
        # 레벨 번호 기반으로 언락 여부 판단 (get_gboost_style_gimmicks 참조)
        # 확률 기반 적용: 모든 레벨에 적용하면 과도하므로 30% 확률로 적용
        level_number = params.level_number if params.level_number else 0
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0)

        # key 기믹: unlockTile 필드 설정 (버퍼 잠금) + key 타일 배치
        # - 레벨 111 (튜토리얼): 100% 확률로 적용
        # - 레벨 112+: 30% 확률로 적용
        # key 기믹 작동 방식:
        # 1. unlockTile: N → N개 버퍼 슬롯 잠금
        # 2. "key" 타일 ID를 가진 타일 N*3개 배치 필요
        # 3. key 타일 3개 모을 때마다 잠금 해제
        KEY_UNLOCK_LEVEL = 111  # 백엔드 leveling_config.py와 동기화
        KEY_PROBABILITY = 0.3  # 30% 확률
        if level_number >= KEY_UNLOCK_LEVEL and gimmick_intensity > 0:
            # 튜토리얼 레벨(111)은 항상 적용, 그 외는 확률 적용
            is_key_tutorial = (level_number == KEY_UNLOCK_LEVEL)
            if is_key_tutorial or random.random() < KEY_PROBABILITY * gimmick_intensity:
                # 난이도에 따라 잠금 슬롯 수 결정 (1-2)
                unlock_tile_count = 1  # 기본값: 1칸 잠금
                if params.target_difficulty >= 0.7 and not is_key_tutorial:
                    unlock_tile_count = 2  # 고난이도: 2칸 잠금 (튜토리얼은 항상 1칸)
                level["unlockTile"] = unlock_tile_count

                # key 타일 배치: unlockTile * 3개의 "key" 타일 필요
                key_tiles_needed = unlock_tile_count * 3
                self._place_key_tiles(level, key_tiles_needed)

        # time_attack 기믹: timea 필드 설정 (제한 시간, 초)
        # 적용 규칙 (TileBuster 패턴):
        # - 레벨 341 (튜토리얼): 최초 언락 레벨에 적용
        # - 레벨 350, 360, 370...: 톱니바퀴 패턴의 보스 레벨(10번째)에만 적용
        # 제한 시간 (디자인 문서 기준):
        # - 쉬움 (difficulty < 0.3): 120초
        # - 보통 (0.3 <= difficulty < 0.5): 90초
        # - 어려움 (0.5 <= difficulty < 0.7): 60초
        # - 매우 어려움 (0.7 <= difficulty): 45초
        TIME_ATTACK_UNLOCK_LEVEL = 341  # 백엔드 leveling_config.py와 동기화
        if level_number >= TIME_ATTACK_UNLOCK_LEVEL and gimmick_intensity > 0:
            is_time_tutorial = (level_number == TIME_ATTACK_UNLOCK_LEVEL)
            # 톱니바퀴 패턴의 보스 레벨 (10번째 = 가장 어려운 레벨)
            is_boss_level = (level_number % 10 == 0)

            # 튜토리얼 레벨 또는 보스 레벨에만 적용
            if is_time_tutorial or is_boss_level:
                # 난이도에 따라 제한 시간 결정
                # 튜토리얼은 넉넉하게 120초, 그 외는 난이도 기반
                if is_time_tutorial:
                    time_limit = 120  # 튜토리얼은 넉넉하게
                else:
                    difficulty = params.target_difficulty
                    if difficulty < 0.3:
                        time_limit = 120  # 쉬움: 2분
                    elif difficulty < 0.5:
                        time_limit = 90   # 보통: 1분 30초
                    elif difficulty < 0.7:
                        time_limit = 60   # 어려움: 1분
                    else:
                        time_limit = 45   # 매우 어려움: 45초
                level["timea"] = time_limit

        generation_time_ms = int((time.time() - start_time) * 1000)

        return GenerationResult(
            level_json=level,
            actual_difficulty=report.score / 100.0,
            grade=report.grade,
            generation_time_ms=generation_time_ms,
        )

    def _place_key_tiles(self, level: Dict[str, Any], count: int) -> None:
        """
        Place 'key' tiles in the level by converting existing tiles.

        key 기믹 작동 방식:
        - key 타일 3개를 모으면 잠긴 버퍼 슬롯 1개가 해제됨
        - unlockTile * 3개의 key 타일이 필요

        Args:
            level: Level JSON to modify
            count: Number of key tiles to place (should be unlockTile * 3)
        """
        if count <= 0:
            return

        # Collect all tile positions from all layers
        all_positions = []
        max_layer = level.get("layer", 5)

        for layer_idx in range(max_layer):
            layer_key = f"layer_{layer_idx}"
            if layer_key not in level:
                continue

            tiles = level[layer_key].get("tiles", {})
            for pos, tile_data in tiles.items():
                if tile_data and len(tile_data) >= 2:
                    tile_type = tile_data[0]
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""
                    # Only convert regular tiles (t0~t15) without gimmicks
                    if tile_type.startswith("t") and not gimmick:
                        all_positions.append((layer_idx, pos))

        # Randomly select positions to convert to key tiles
        if len(all_positions) < count:
            # Not enough tiles, use what we have
            positions_to_convert = all_positions
        else:
            positions_to_convert = random.sample(all_positions, count)

        # Convert selected tiles to key tiles
        for layer_idx, pos in positions_to_convert:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            if pos in tiles:
                original_tile = tiles[pos]
                # Keep original tile type but set ID to "key"
                # Format: [tile_type, gimmick, extras...]
                # For key tiles: the tile ID becomes "key"
                tiles[pos] = ["key", original_tile[1] if len(original_tile) > 1 else ""]

    def reshuffle_positions(self, level: Dict[str, Any], params: Optional[GenerationParams] = None) -> Dict[str, Any]:
        """
        Reshuffle tile positions while keeping tile types, gimmicks, and layer structure.

        This method:
        1. Extracts all tile data (type, gimmick, extra) from each layer
        2. Generates new positions using smart placement for gimmick tiles
        3. Places tiles with neighbor-dependent gimmicks (chain, link, grass) first
        4. Ensures these tiles have valid neighbors

        Args:
            level: Existing level JSON to reshuffle
            params: Optional generation params for validation

        Returns:
            New level JSON with reshuffled positions
        """
        import copy
        new_level = copy.deepcopy(level)

        num_layers = new_level.get("layer", 8)

        # Gimmicks that require at least one clearable neighbor
        NEIGHBOR_DEPENDENT_GIMMICKS = {'chain', 'link', 'link_s', 'link_n', 'link_e', 'link_w', 'grass'}

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            if layer_key not in new_level:
                continue

            layer_data = new_level[layer_key]
            tiles = layer_data.get("tiles", {})
            if not tiles:
                continue

            # Extract tile data into categories
            goal_tiles = []           # [(tile_type, gimmick, extra), ...]
            gimmick_tiles = []        # Tiles with neighbor-dependent gimmicks
            other_gimmick_tiles = []  # Tiles with other gimmicks (ice, frog, bomb, etc.)
            plain_tiles = []          # Tiles without gimmicks

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list):
                    continue
                tile_type = tile_data[0] if len(tile_data) > 0 else "t1"
                gimmick = tile_data[1] if len(tile_data) > 1 else ""
                extra = tile_data[2] if len(tile_data) > 2 else None

                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                    goal_tiles.append((tile_type, gimmick, extra))
                elif gimmick and any(gimmick.startswith(g) for g in NEIGHBOR_DEPENDENT_GIMMICKS):
                    gimmick_tiles.append((tile_type, gimmick, extra))
                elif gimmick:
                    other_gimmick_tiles.append((tile_type, gimmick, extra))
                else:
                    plain_tiles.append((tile_type, gimmick, extra))

            # Get grid dimensions from layer
            cols = int(layer_data.get("col", 8))
            rows = int(layer_data.get("row", 8))

            # Helper to get required adjacent positions based on gimmick type
            def get_required_adjacent(pos_str, gimmick_type=""):
                col, row = map(int, pos_str.split("_"))
                adj = []

                # Chain only checks LEFT and RIGHT (horizontal neighbors)
                if gimmick_type == "chain":
                    directions = [(-1, 0), (1, 0)]  # Left, Right only
                # Link checks specific direction
                elif gimmick_type.startswith("link_"):
                    if gimmick_type == "link_n":
                        directions = [(0, -1)]  # North
                    elif gimmick_type == "link_s":
                        directions = [(0, 1)]   # South
                    elif gimmick_type == "link_e":
                        directions = [(1, 0)]   # East
                    elif gimmick_type == "link_w":
                        directions = [(-1, 0)]  # West
                    else:
                        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
                else:
                    # Default: all 4 directions
                    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

                for dc, dr in directions:
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < cols and 0 <= nr < rows:
                        adj.append(f"{nc}_{nr}")
                return adj

            # Generate all positions and shuffle
            all_positions = [f"{c}_{r}" for c in range(cols) for r in range(rows)]
            random.shuffle(all_positions)

            new_tiles = {}
            used_positions = set()

            # STEP 1: Place goal tiles FIRST (need clear output direction for craft/stack)
            # Must be placed before other tiles to ensure output positions are available
            # Goal tiles (craft/stack) need their output direction to be clear of other tiles
            for tile_type, gimmick, extra in goal_tiles:
                direction = tile_type[-1] if tile_type else 's'
                valid_positions = []

                # Calculate output direction offset
                dir_offsets = {'s': (0, 1), 'n': (0, -1), 'e': (1, 0), 'w': (-1, 0)}
                dc, dr = dir_offsets.get(direction, (0, 1))

                # Calculate how many output positions need to be clear
                # stack_offset = 0.1 per item, so count=3 → max_offset=0.2 → 1 position
                stack_count = extra[0] if extra and isinstance(extra, list) and len(extra) > 0 else 3
                max_offset = (stack_count - 1) * 0.1
                positions_to_clear = max(1, int(max_offset) + 1)  # At least the immediate output position

                for pos in all_positions:
                    if pos in used_positions:
                        continue
                    col_pos, row_pos = map(int, pos.split("_"))

                    # Check boundary constraints
                    if direction == 's' and row_pos >= rows - 1:
                        continue
                    if direction == 'n' and row_pos <= 0:
                        continue
                    if direction == 'e' and col_pos >= cols - 1:
                        continue
                    if direction == 'w' and col_pos <= 0:
                        continue

                    # Check that output positions are clear (not occupied by any tile)
                    output_clear = True
                    for step in range(1, positions_to_clear + 1):
                        out_c = col_pos + dc * step
                        out_r = row_pos + dr * step
                        out_pos = f"{out_c}_{out_r}"
                        # Output position must be within bounds and not occupied
                        if out_c < 0 or out_c >= cols or out_r < 0 or out_r >= rows:
                            output_clear = False
                            break
                        if out_pos in used_positions or out_pos in new_tiles:
                            output_clear = False
                            break

                    if not output_clear:
                        continue

                    valid_positions.append(pos)

                if valid_positions:
                    random.shuffle(valid_positions)
                    pos = valid_positions[0]
                    used_positions.add(pos)
                    # Also reserve output positions so other goals don't use them
                    col_pos, row_pos = map(int, pos.split("_"))
                    for step in range(1, positions_to_clear + 1):
                        out_c = col_pos + dc * step
                        out_r = row_pos + dr * step
                        out_pos = f"{out_c}_{out_r}"
                        used_positions.add(out_pos)
                    self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                else:
                    # FALLBACK: If no valid position found, place in any available position
                    # This ensures goals are never lost during reshuffle
                    for pos in all_positions:
                        if pos not in used_positions:
                            used_positions.add(pos)
                            self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                            break

            # STEP 2: Place plain tiles (they will be neighbors for gimmick tiles)
            random.shuffle(plain_tiles)
            for tile_type, gimmick, extra in plain_tiles:
                for pos in all_positions:
                    if pos not in used_positions:
                        used_positions.add(pos)
                        self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                        break

            # STEP 3: Place neighbor-dependent gimmick tiles using gimmick-specific neighbor rules
            random.shuffle(gimmick_tiles)
            for tile_type, gimmick, extra in gimmick_tiles:
                placed = False
                candidates = []
                for pos in all_positions:
                    if pos in used_positions:
                        continue
                    required_adj = get_required_adjacent(pos, gimmick)
                    for adj_pos in required_adj:
                        if adj_pos in new_tiles:
                            adj_tile = new_tiles[adj_pos]
                            if len(adj_tile) >= 2 and (not adj_tile[1] or adj_tile[1] == "frog"):
                                candidates.append(pos)
                                break

                if candidates:
                    random.shuffle(candidates)
                    pos = candidates[0]
                    used_positions.add(pos)
                    self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                    placed = True

                if not placed:
                    for pos in all_positions:
                        if pos not in used_positions:
                            used_positions.add(pos)
                            self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                            break

            # STEP 4: Place other gimmick tiles (ice, frog, bomb, etc.)
            random.shuffle(other_gimmick_tiles)
            for tile_type, gimmick, extra in other_gimmick_tiles:
                for pos in all_positions:
                    if pos not in used_positions:
                        used_positions.add(pos)
                        self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                        break

            # Update layer with new tiles
            layer_data["tiles"] = new_tiles
            layer_data["num"] = str(len(new_tiles))

        # Re-validate obstacles (should preserve most gimmicks now)
        new_level = self._validate_and_fix_obstacles(new_level)

        # Recalculate max_moves
        new_level["max_moves"] = self._calculate_max_moves(new_level)

        # Generate new random seed
        new_level["randSeed"] = random.randint(100000, 999999)

        return new_level

    def _calculate_max_moves(self, level: Dict[str, Any]) -> int:
        """Calculate max_moves based on total tiles in the level.

        Counts all tiles including internal tiles in stack/craft.
        """
        total_tiles = 0
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Check for stack/craft tiles
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        # Get internal tile count from tile_data[2]
                        stack_count = 1
                        if len(tile_data) > 2:
                            extra = tile_data[2]
                            if isinstance(extra, list) and len(extra) > 0:
                                stack_count = int(extra[0]) if extra[0] else 1
                            elif isinstance(extra, dict):
                                stack_count = int(extra.get("totalCount", extra.get("count", 1)))
                            elif isinstance(extra, (int, float)):
                                stack_count = int(extra)
                        total_tiles += stack_count
                    else:
                        # Normal tile
                        total_tiles += 1
                else:
                    total_tiles += 1

        # Return total tiles as max_moves (minimum 30)
        return max(30, total_tiles)

    def _create_base_structure(self, params: GenerationParams) -> Dict[str, Any]:
        """Create the base level structure with empty layers."""
        cols, rows = params.grid_size

        # Calculate useTileCount from tile_types
        # If tile_types not specified and level_number is provided, use auto-config
        tile_types = params.tile_types
        if not tile_types and params.level_number:
            # Auto-select tile types based on level number (GBoost style)
            tile_types = get_tile_types_for_level(params.level_number)
        elif not tile_types:
            tile_types = self.DEFAULT_TILE_TYPES

        # Filter to only valid tile types (t0~t15)
        valid_tile_types = [t for t in tile_types if t.startswith('t') and (t == 't0' or t[1:].isdigit())]
        if valid_tile_types:
            # Check if t0 is used (placeholder for client-side random tiles)
            uses_t0 = 't0' in valid_tile_types
            if uses_t0:
                # t0 사용 시: 레벨에 맞는 useTileCount 사용 (클라이언트가 참조)
                if params.level_number:
                    use_tile_count = get_use_tile_count_for_level(params.level_number)
                else:
                    use_tile_count = 5  # default for t0 mode
            else:
                # 일반 타일 사용 시: 타일 개수가 useTileCount
                tile_count = len(valid_tile_types)
                use_tile_count = min(self.MAX_USE_TILE_COUNT, tile_count)
        else:
            # No valid tiles, use default of 15 (matches TownPop client - t1~t15 균등 분배)
            use_tile_count = 15

        level = {
            "layer": params.max_layers,
            "useTileCount": use_tile_count,
            "randSeed": random.randint(1, 999999),
            "autoCollectCount": 0,  # 암호화 설정 (0: 해제)
        }

        for i in range(params.max_layers):
            # Alternating grid sizes (odd layers are smaller)
            layer_cols = str(cols + 1 if i % 2 == 0 else cols)
            layer_rows = str(rows + 1 if i % 2 == 0 else rows)

            level[f"layer_{i}"] = {
                "col": layer_cols,
                "row": layer_rows,
                "tiles": {},
                "num": "0",
            }

        return level

    @classmethod
    def _record_used_pattern_category(cls, category_idx: int) -> None:
        """Record a used pattern category for diversity tracking between levels."""
        cls._recent_pattern_categories.append(category_idx)
        # Keep only the most recent N categories
        if len(cls._recent_pattern_categories) > cls._PATTERN_HISTORY_SIZE:
            cls._recent_pattern_categories = cls._recent_pattern_categories[-cls._PATTERN_HISTORY_SIZE:]

    @classmethod
    def clear_pattern_history(cls) -> None:
        """Clear pattern history - useful when starting a new batch."""
        cls._recent_pattern_categories = []

    def _select_layer_pattern_indices(
        self, active_layers: List[int], base_pattern_index: Optional[int] = None
    ) -> Dict[int, int]:
        """Select varied pattern indices for each layer to create geometric diversity.

        Pattern Categories (50 patterns total):
        - 0-9: Basic shapes (rectangle, diamond, oval, cross, donut, etc.)
        - 10-14: Arrow/Direction patterns
        - 15-19: Star/Celestial patterns
        - 20-29: Letter shapes (H, I, L, U, X, Y, Z, S, O, C)
        - 30-39: Advanced geometric (triangles, hourglass, stairs, pyramid, zigzag)
        - 40-44: Frame/Border patterns
        - 45-49: Artistic patterns (butterfly, flower, islands, stripes, honeycomb)

        Strategy: Select patterns from different categories for adjacent layers
        to create visually interesting, non-repetitive geometric compositions.
        Also avoids recently used patterns from previous levels for batch diversity.

        Args:
            active_layers: List of layer indices that will be populated
            base_pattern_index: If specified, use as base; otherwise auto-select

        Returns:
            Dict mapping layer_idx -> pattern_index
        """
        # Define pattern categories with complementary aesthetics
        # Each category has patterns that look distinct from each other
        # Extended categories for maximum variety
        pattern_categories = [
            [0, 1, 2],      # Basic shapes: rectangle, diamond, oval
            [3, 4, 5],      # Structural: cross, donut, chevron
            [10, 11, 12],   # Directional: arrows (up, down, left)
            [13, 14],       # More arrows (right, double)
            [15, 16, 17],   # Celestial: stars (5pt, 6pt, scattered)
            [18, 19],       # Celestial: crescents
            [20, 21, 22],   # Letters: H, I, L
            [23, 24, 25],   # Letters: U, X, Y
            [26, 27, 28, 29],  # Letters: Z, S, O, C
            [30, 31, 32],   # Geometric: triangles, hourglass
            [33, 34, 35],   # Advanced: stairs, pyramid, zigzag
            [36, 37, 38, 39],  # More advanced geometric
            [40, 41, 42],   # Frames: borders
            [43, 44],       # More frames
            [45, 46, 47],   # Artistic: butterfly, flower, islands
            [48, 49],       # Artistic: stripes, honeycomb
            [6, 7, 8, 9],   # Misc basic shapes
            [50, 51],       # Bridge patterns: horizontal, vertical bridges
            [52, 53],       # Multi-island: triangle, grid arrangements
            [54, 55],       # Distributed: archipelago, hub-and-spokes
        ]

        # Flatten for random selection if needed
        all_patterns = [p for cat in pattern_categories for p in cat]

        layer_patterns: Dict[int, int] = {}
        used_categories: Set[int] = set()

        # Also consider categories used in recent levels (for batch diversity)
        recently_used_in_batch = set(self._recent_pattern_categories)

        # Sort layers to ensure consistent ordering (top to bottom)
        sorted_layers = sorted(active_layers, reverse=True)

        # Track the first category selected for this level (to record later)
        first_category_selected: Optional[int] = None

        for i, layer_idx in enumerate(sorted_layers):
            if base_pattern_index is not None and i == 0:
                # Use base pattern for first layer
                layer_patterns[layer_idx] = base_pattern_index
                # Find which category this belongs to
                for cat_idx, cat in enumerate(pattern_categories):
                    if base_pattern_index in cat:
                        used_categories.add(cat_idx)
                        first_category_selected = cat_idx
                        break
            else:
                # For the first layer without base pattern, also avoid recent batch categories
                exclude_categories = used_categories.copy()
                if i == 0:
                    exclude_categories = exclude_categories.union(recently_used_in_batch)

                # Select from a different category than recent layers
                available_categories = [
                    cat_idx for cat_idx in range(len(pattern_categories))
                    if cat_idx not in exclude_categories
                ]

                # If all categories used, reset but avoid immediate repeat
                if not available_categories:
                    used_categories.clear()
                    # Keep the most recent category excluded
                    if i > 0:
                        prev_layer = sorted_layers[i - 1]
                        prev_pattern = layer_patterns.get(prev_layer, 0)
                        for cat_idx, cat in enumerate(pattern_categories):
                            if prev_pattern in cat:
                                used_categories.add(cat_idx)
                                break
                    available_categories = [
                        cat_idx for cat_idx in range(len(pattern_categories))
                        if cat_idx not in used_categories
                    ]

                if available_categories:
                    selected_cat_idx = random.choice(available_categories)
                    selected_pattern = random.choice(pattern_categories[selected_cat_idx])
                    used_categories.add(selected_cat_idx)
                    if i == 0:
                        first_category_selected = selected_cat_idx
                else:
                    # Fallback: random pattern avoiding immediate repeat
                    prev_pattern = layer_patterns.get(sorted_layers[i - 1], -1) if i > 0 else -1
                    candidates = [p for p in all_patterns if p != prev_pattern]
                    selected_pattern = random.choice(candidates) if candidates else random.choice(all_patterns)

                layer_patterns[layer_idx] = selected_pattern

        # Record the first category used for batch diversity tracking
        if first_category_selected is not None:
            self._record_used_pattern_category(first_category_selected)

        return layer_patterns

    def _generate_auto_layer_pattern_configs(
        self,
        active_layers: List[int],
        target_difficulty: float,
        total_tile_count: int,
        is_boss_level: bool = False,
    ) -> List["LayerPatternConfig"]:
        """Generate intelligent layer pattern configurations for aesthetic variety.

        This method creates visually appealing multi-layer compositions by mixing
        different pattern types across layers. The mixing strategy adapts to:
        - Level difficulty (easy levels use simpler patterns)
        - Number of active layers (more layers = more variety)
        - Boss level status (uses more impressive patterns)

        Pattern Type Characteristics:
        - 'aesthetic': Artistic, visually impressive (best for top/visible layers)
        - 'geometric': Structured, regular shapes (good for base layers)
        - 'clustered': Grouped tiles (creates interesting visual clusters)
        - 'random': Natural, organic feel (good for middle layers)

        IMPROVEMENT: Always use aesthetic patterns for top layer to maximize visual appeal
        and create clear layer differentiation.

        Args:
            active_layers: List of layer indices that will be populated
            target_difficulty: Target difficulty (0.0-1.0)
            total_tile_count: Total tiles across all layers
            is_boss_level: Whether this is a boss level

        Returns:
            List of LayerPatternConfig for each layer
        """
        from app.models.level import LayerPatternConfig

        configs: List[LayerPatternConfig] = []
        num_layers = len(active_layers)
        sorted_layers = sorted(active_layers, reverse=True)  # Top to bottom

        # ===== ENHANCED PATTERN SETS FOR BETTER TOP LAYER VISIBILITY =====

        # Top layer special patterns (always aesthetic, visually distinctive)
        # Priority: Star/Heart/Butterfly/Flower shapes that stand out
        top_layer_patterns = [
            8,   # star_five_point
            15,  # heart_shape
            45,  # butterfly
            46,  # flower_pattern
            16,  # crescent_moon
            17,  # spiral_outward
            50,  # bridge_horizontal
            51,  # bridge_vertical
            52,  # three_islands_triangle
            53,  # four_islands_grid
            54,  # archipelago
            55,  # hub_and_spokes
        ]

        # Boss level extra impressive patterns
        boss_top_patterns = [8, 15, 45, 46, 17, 18, 54, 55]

        # Easy level top patterns (simpler but still distinctive)
        easy_top_patterns = [8, 15, 20, 21, 50, 51, 52]  # Stars, hearts, letters, bridges

        # Medium level top patterns
        medium_top_patterns = [8, 15, 45, 46, 40, 41, 50, 51, 52, 53]

        # Hard level top patterns (complex)
        hard_top_patterns = [45, 46, 47, 48, 49, 54, 55, 8, 15]

        # Middle layer patterns (varied)
        middle_patterns = [4, 5, 10, 11, 30, 31, 40, 41, 33, 34]

        # Bottom layer patterns (structural base - can be simpler)
        bottom_patterns = [0, 1, 2, 3, 4, 5, 20, 21]

        # ===== PATTERN ASSIGNMENT LOGIC =====

        if is_boss_level:
            # Boss levels: Maximum visual impact on top
            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - most visible, impressive
                    pattern_idx = random.choice(boss_top_patterns)
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=pattern_idx
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom layer - structural base
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice(bottom_patterns)
                    ))
                else:  # Middle layers - mix for variety
                    if i % 2 == 0:
                        configs.append(LayerPatternConfig(
                            layer=layer_idx,
                            pattern_type="clustered",
                            pattern_index=None
                        ))
                    else:
                        configs.append(LayerPatternConfig(
                            layer=layer_idx,
                            pattern_type="aesthetic",
                            pattern_index=random.choice(middle_patterns)
                        ))
        elif target_difficulty < 0.3:
            # Easy levels: Simple but still aesthetic on top for visibility
            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - ALWAYS aesthetic for distinction
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=random.choice(easy_top_patterns)
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom layer
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice([0, 1, 2, 3])
                    ))
                else:  # Middle layers
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice(bottom_patterns)
                    ))
        elif target_difficulty < 0.6:
            # Medium difficulty: Balanced variety with aesthetic top
            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - aesthetic
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=random.choice(medium_top_patterns)
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom - geometric
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice(bottom_patterns)
                    ))
                else:  # Middle - alternate
                    pattern_type = "clustered" if i % 2 == 0 else "random"
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type=pattern_type,
                        pattern_index=None
                    ))
        else:
            # Hard levels: Complex, varied patterns with impressive top
            # Higher difficulty = more scattered patterns for increased challenge
            # Scattered/Island patterns: 47 (scattered_islands), 52-55 (island patterns)
            scattered_patterns = [47, 52, 53, 54, 55]  # More spread out patterns

            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - use scattered patterns for high difficulty
                    # 70% chance of scattered pattern, 30% other aesthetic
                    if random.random() < 0.7:
                        pattern_idx = random.choice(scattered_patterns)
                    else:
                        pattern_idx = random.choice(hard_top_patterns)
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=pattern_idx
                    ))
                elif i == 1 and num_layers > 2:  # Second layer - scattered/random
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="random",  # More scattered than clustered
                        pattern_index=None
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom - geometric base
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice([3, 4, 5, 30, 31])
                    ))
                else:  # Other middle layers - prefer random/scattered
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="random",  # All middle layers use random for scatter
                        pattern_index=None
                    ))

        return configs

    def _populate_layers(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Populate layers with tiles based on difficulty and user configuration."""
        target = params.target_difficulty
        cols, rows = params.grid_size

        # Auto-select tile types based on level number if not specified
        tile_types = params.tile_types
        if not tile_types and params.level_number:
            tile_types = get_tile_types_for_level(params.level_number)
        elif not tile_types:
            tile_types = self.DEFAULT_TILE_TYPES

        # Check if per-layer tile configs are provided (they take priority)
        has_layer_tile_configs = bool(params.layer_tile_configs) and len(params.layer_tile_configs) > 0

        if has_layer_tile_configs:
            # Use ONLY the layers specified in layer_tile_configs
            # This gives full control to the user
            active_layers = sorted(
                [c.layer for c in params.layer_tile_configs],
                reverse=True  # Start from top layer
            )
            active_layer_count = len(active_layers)

            # Build per-layer tile counts from config
            layer_tile_counts: Dict[int, int] = {}
            for config in params.layer_tile_configs:
                layer_tile_counts[config.layer] = config.count

            # Total is sum of configured counts
            total_target = sum(layer_tile_counts.values())
        else:
            # Determine layers from active_layer_count or calculate based on difficulty
            if params.active_layer_count is not None:
                active_layer_count = min(params.active_layer_count, params.max_layers)
            else:
                # Tile Buster style layer count based on difficulty:
                # - S grade (0-0.2): 2-3 layers (tutorial, simple)
                # - A grade (0.2-0.4): 3-4 layers (easy-medium)
                # - B grade (0.4-0.6): 4-5 layers (medium)
                # - C grade (0.6-0.8): 5-6 layers (hard)
                # - D grade (0.8-1.0): 6-8 layers (very hard)
                min_layers = max(1, params.min_layers)
                max_layers = params.max_layers

                # Tutorial mode: For very low difficulty (≤0.15), use 2-3 layers
                is_tutorial_mode = target <= 0.15
                if is_tutorial_mode:
                    max_layers = min(max_layers, 3)
                    min_layers = min(min_layers, 2)
                elif target < 0.4:
                    # A grade: 3-4 layers
                    min_layers = max(min_layers, 3)
                    max_layers = min(max_layers, 4)
                elif target < 0.6:
                    # B grade: 4-5 layers
                    min_layers = max(min_layers, 4)
                    max_layers = min(max_layers, 5)
                elif target < 0.8:
                    # C grade: 5-6 layers
                    min_layers = max(min_layers, 5)
                    max_layers = min(max_layers, 6)
                else:
                    # D grade: 6-8 layers (use full range)
                    min_layers = max(min_layers, 6)

                # Ensure min <= max
                if min_layers > max_layers:
                    min_layers = max_layers

                # Linear interpolation based on difficulty within grade range
                layer_range = max_layers - min_layers
                active_layer_count = min_layers + int(layer_range * target)

                # Clamp to valid range
                active_layer_count = max(min_layers, min(max_layers, active_layer_count))

            # Update level["layer"] to reflect actual active layer count
            level["layer"] = active_layer_count

            # Use layers 0 to active_layer_count-1 (bottom to top)
            active_layers = list(range(active_layer_count))

            # Calculate total tile count target
            if params.total_tile_count is not None:
                total_target = (params.total_tile_count // 3) * 3
                if total_target < 9:
                    total_target = 9
            else:
                # Tile Buster style tile count ranges:
                # - Early levels (tutorial): 30-45 tiles, simple layout
                # - Mid levels: 45-60 tiles, moderate complexity
                # - Late levels: 60-90 tiles, high complexity
                #
                # S grade (0-0.2): Tutorial style, 30-45 tiles
                # A grade (0.2-0.4): Easy-medium, 45-60 tiles
                # B grade (0.4-0.6): Medium, 54-72 tiles
                # C grade (0.6-0.8): Hard, 66-84 tiles
                # D grade (0.8-1.0): Very hard, 78-99 tiles
                if target < 0.2:
                    # S grade: tutorial style
                    min_tiles = 30
                    max_tiles = 45
                elif target < 0.4:
                    # A grade: easy-medium
                    min_tiles = 45
                    max_tiles = 60
                elif target < 0.6:
                    # B grade: medium
                    min_tiles = 54
                    max_tiles = 72
                elif target < 0.8:
                    # C grade: hard
                    min_tiles = 66
                    max_tiles = 84
                else:
                    # D grade: very hard
                    min_tiles = 78
                    max_tiles = 99

                # Linear interpolation within the grade range
                if target < 0.2:
                    t = target / 0.2
                elif target < 0.4:
                    t = (target - 0.2) / 0.2
                elif target < 0.6:
                    t = (target - 0.4) / 0.2
                elif target < 0.8:
                    t = (target - 0.6) / 0.2
                else:
                    t = (target - 0.8) / 0.2

                base_tiles = int(min_tiles + (max_tiles - min_tiles) * t)
                base_tiles = max(min_tiles, min(max_tiles, base_tiles))

                # Add random variation for diversity (±15% within grade range)
                variation_range = int((max_tiles - min_tiles) * 0.3)  # 30% of grade range
                random_variation = random.randint(-variation_range, variation_range)
                base_tiles = max(min_tiles, min(max_tiles, base_tiles + random_variation))

                total_target = (base_tiles // 3) * 3
                if total_target < 30:
                    total_target = 30

            # Build per-layer tile counts with random variation for diversity
            layer_tile_counts = {}
            tiles_per_layer = total_target // len(active_layers)
            extra_tiles = total_target % len(active_layers)

            # Shuffle which layers get extra tiles for variety
            extra_tile_layers = random.sample(active_layers, min(extra_tiles, len(active_layers)))

            # CRITICAL: When exact tile count is specified (tutorial levels, etc.),
            # disable variation to ensure exact tile count
            exact_tile_mode = params.total_tile_count is not None

            if exact_tile_mode:
                # Exact mode: no variation, distribute evenly
                for layer_idx in active_layers:
                    base_count = tiles_per_layer + (3 if layer_idx in extra_tile_layers else 0)
                    layer_tile_counts[layer_idx] = (base_count // 3) * 3
            else:
                # Create varied distribution patterns
                # 'gboost_pyramid' is based on analysis of 221 human-designed GBoost levels:
                # Layer 0: ~30%, Layer 1: ~29%, Layer 2: ~22%, Layer 3: ~14%, Layer 4: ~8%
                # This creates a natural difficulty curve where bottom layers have more tiles
                distribution_pattern = random.choices(
                    ['gboost_pyramid', 'uniform', 'bottom_heavy', 'alternating', 'random'],
                    weights=[0.50, 0.15, 0.15, 0.10, 0.10],  # 50% chance for gboost_pyramid
                    k=1
                )[0]

                if distribution_pattern == 'gboost_pyramid':
                    # GBoost human-designed level ratios (analyzed from level_1 ~ level_221)
                    # These ratios create a natural difficulty progression
                    pyramid_ratios = [0.30, 0.29, 0.22, 0.14, 0.08, 0.05, 0.03, 0.02]
                    num_layers = len(active_layers)

                    # Normalize ratios to match actual layer count
                    used_ratios = pyramid_ratios[:num_layers]
                    ratio_sum = sum(used_ratios)
                    normalized_ratios = [r / ratio_sum for r in used_ratios]

                    # Distribute tiles according to pyramid ratios
                    remaining_tiles = total_target
                    for i, layer_idx in enumerate(sorted(active_layers)):
                        if i < len(active_layers) - 1:
                            layer_count = int(total_target * normalized_ratios[i])
                            # Ensure divisible by 3
                            layer_count = (layer_count // 3) * 3
                            layer_count = max(6, layer_count)  # Minimum 6 tiles
                        else:
                            # Last layer gets remaining tiles
                            layer_count = remaining_tiles
                            layer_count = (layer_count // 3) * 3
                            layer_count = max(6, layer_count)

                        layer_tile_counts[layer_idx] = layer_count
                        remaining_tiles -= layer_count
                else:
                    # Original distribution patterns
                    for layer_idx in active_layers:
                        # More aggressive per-layer variation for diversity
                        if distribution_pattern == 'uniform':
                            layer_variation = random.choice([-6, -3, 0, 3, 6])
                        elif distribution_pattern == 'bottom_heavy':
                            # Lower layers get more tiles
                            layer_variation = -(layer_idx - len(active_layers) // 2) * 3
                        elif distribution_pattern == 'alternating':
                            # Alternating heavy/light layers
                            layer_variation = 6 if layer_idx % 2 == 0 else -6
                        else:  # random
                            layer_variation = random.randint(-3, 3) * 3

                        base_count = tiles_per_layer + (3 if layer_idx in extra_tile_layers else 0)
                        final_count = max(6, base_count + layer_variation)  # Minimum 6 tiles per layer
                        # Ensure divisible by 3
                        layer_tile_counts[layer_idx] = (final_count // 3) * 3

        # Collect all positions across all layers
        all_layer_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)

        # Generate varied pattern indices for each layer (for aesthetic mode)
        # This creates geometric diversity by using different patterns per layer
        layer_pattern_indices = self._select_layer_pattern_indices(
            active_layers, base_pattern_index=params.pattern_index
        )

        # When exact tile counts are specified, force symmetry_mode="none" to get exact counts
        # (unless user explicitly requested a specific symmetry mode)
        exact_count_mode = has_layer_tile_configs or (params.total_tile_count is not None)
        effective_symmetry_mode = params.symmetry_mode
        if exact_count_mode and params.symmetry_mode is None:
            effective_symmetry_mode = "none"

        # DEBUG: Log symmetry mode in generator
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(f"[GENERATOR_DEBUG] params.symmetry_mode={params.symmetry_mode}, "
                     f"exact_count_mode={exact_count_mode}, "
                     f"effective_symmetry_mode={effective_symmetry_mode}, "
                     f"pattern_type={params.pattern_type}")

        # Auto-mixing: Generate intelligent layer pattern configs for aesthetic variety
        # Conditions for auto-mixing:
        # 1. No explicit layer_pattern_configs provided
        # 2. Multiple active layers (>= 3 for meaningful variety)
        # 3. pattern_type is 'aesthetic' or None (default)
        enable_auto_mixing = (
            params.layer_pattern_configs is None and
            len(active_layers) >= 3 and
            params.pattern_type in (None, "aesthetic")
        )

        effective_layer_pattern_configs = None
        if enable_auto_mixing:
            # Calculate total tile count for auto-mixing strategy
            total_tiles = sum(layer_tile_counts.values())
            # Detect boss level: high tile count (>100) or multiple goals
            is_boss_level = total_tiles > 100 or (
                params.goals and len(params.goals) > 1
            )
            effective_layer_pattern_configs = self._generate_auto_layer_pattern_configs(
                active_layers=active_layers,
                target_difficulty=params.target_difficulty,
                total_tile_count=total_tiles,
                is_boss_level=is_boss_level,
            )
            _logger.info(f"[GENERATOR_DEBUG] Auto-mixing enabled: {len(effective_layer_pattern_configs)} layer configs generated, is_boss={is_boss_level}")
        elif params.layer_pattern_configs:
            effective_layer_pattern_configs = params.layer_pattern_configs

        # Helper function to get pattern config for a layer
        def get_effective_layer_pattern(layer_idx: int):
            """Get effective pattern config for a layer from auto or explicit configs."""
            if effective_layer_pattern_configs:
                for config in effective_layer_pattern_configs:
                    if config.layer == layer_idx:
                        return (config.pattern_type, config.pattern_index)
            return None

        # Layer scaling disabled - all layers use full dimensions
        max_layer_idx = max(active_layers) if active_layers else 0
        layer_shrink_rate = 1.0  # No shrink - preserve pattern shapes

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            is_odd_layer = layer_idx % 2 == 1

            # Calculate base layer dimensions (original logic)
            base_cols = cols if is_odd_layer else cols + 1
            base_rows = rows if is_odd_layer else rows + 1

            # Phase 1: Apply dynamic layer shrinking for pyramid/turtle effect
            # Higher layers get progressively smaller to create visual depth
            if max_layer_idx > 0 and layer_idx > 0:
                # Calculate shrink factor based on layer position
                # layer_idx 0 = full size, higher = smaller
                shrink_factor = layer_shrink_rate ** layer_idx

                # Apply shrink factor but ensure minimum viable size (at least 4x4)
                layer_cols = max(4, int(base_cols * shrink_factor))
                layer_rows = max(4, int(base_rows * shrink_factor))

                # Ensure dimensions stay within original grid bounds
                layer_cols = min(layer_cols, base_cols)
                layer_rows = min(layer_rows, base_rows)
            else:
                layer_cols = base_cols
                layer_rows = base_rows

            # Phase 2: Calculate center offset for depth emphasis
            # Higher layers are visually centered within the lower layer's footprint
            # This creates the turtle/pyramid depth effect
            layer_offset_x = (base_cols - layer_cols) // 2
            layer_offset_y = (base_rows - layer_rows) // 2

            # Get target tile count for this layer
            target_count = layer_tile_counts.get(layer_idx, 0)
            if target_count <= 0:
                continue

            # Determine pattern type and index for this layer
            # Priority: 1) Explicit/Auto layer config, 2) Level-wide default
            layer_pattern_config = get_effective_layer_pattern(layer_idx)

            if layer_pattern_config:
                # Use per-layer configuration (explicit or auto-generated)
                layer_pattern_type = layer_pattern_config[0]
                layer_pattern_index = layer_pattern_config[1] if layer_pattern_config[1] is not None else layer_pattern_indices.get(layer_idx, params.pattern_index)
            else:
                # Use level-wide pattern_type with varied pattern_index per layer
                layer_pattern_type = params.pattern_type
                layer_pattern_index = layer_pattern_indices.get(layer_idx, params.pattern_index)

            # Generate positions for this layer with symmetry and pattern options
            # Note: positions are generated within the shrunk layer dimensions
            positions = self._generate_layer_positions_for_count(
                layer_cols, layer_rows, target_count,
                symmetry_mode=effective_symmetry_mode,
                pattern_type=layer_pattern_type,
                pattern_index=layer_pattern_index  # Use varied pattern per layer
            )

            # Phase 2: Apply center offset to positions so higher layers appear centered
            if layer_offset_x > 0 or layer_offset_y > 0:
                offset_positions = []
                for pos in positions:
                    parts = pos.split("_")
                    x, y = int(parts[0]), int(parts[1])
                    new_x = x + layer_offset_x
                    new_y = y + layer_offset_y
                    # Ensure within original grid bounds
                    if 0 <= new_x < base_cols and 0 <= new_y < base_rows:
                        offset_positions.append(f"{new_x}_{new_y}")
                positions = offset_positions

            for pos in positions:
                all_layer_positions.append((layer_idx, pos))

        # CRITICAL: Ensure total positions is divisible by 3
        # When layers are full, clamping may break divisibility
        total_positions = len(all_layer_positions)
        remainder = total_positions % 3

        # For symmetric patterns, we can't just remove random positions
        # as it would break the symmetry. Only remove if no symmetry.
        symmetry = params.symmetry_mode or "none"
        if remainder > 0 and symmetry == "none":
            # Remove excess positions to make divisible by 3
            # Remove from the end (random positions anyway)
            all_layer_positions = all_layer_positions[:total_positions - remainder]
        elif remainder > 0 and symmetry != "none":
            # For symmetric patterns, add dummy positions to reach divisible by 3
            # We'll use already existing positions (they'll just be duplicated in assignment)
            # This is a simple workaround - the tile assignment handles extra positions
            pass  # Let the tile assignment code handle the non-divisibility

        # CRITICAL: Distribute tile types ensuring each type has count divisible by 3
        # Calculate how many tiles of each type we need
        total_positions = len(all_layer_positions)
        num_tile_types = len(tile_types)

        # Each type should get roughly equal share, but must be divisible by 3
        tiles_per_type = (total_positions // num_tile_types // 3) * 3
        if tiles_per_type < 3:
            tiles_per_type = 3

        # Create a list of tile types to assign (each type appears in multiples of 3)
        tile_assignments = []
        for tile_type in tile_types:
            tile_assignments.extend([tile_type] * tiles_per_type)

        # If we have more positions than assignments, add more tiles (in groups of 3)
        while len(tile_assignments) < len(all_layer_positions):
            tile_type = random.choice(tile_types)
            tile_assignments.extend([tile_type] * 3)

        # If we have more assignments than positions, trim to match
        # (positions are already divisible by 3 from earlier check)
        if len(tile_assignments) > len(all_layer_positions):
            tile_assignments = tile_assignments[:len(all_layer_positions)]

        # Initialize tiles dict for each layer
        for layer_idx in active_layers:
            level[f"layer_{layer_idx}"]["tiles"] = {}

        # HIGH DIFFICULTY: Spread same-type tiles apart for increased challenge
        # Low/Medium difficulty: Random distribution (original behavior)
        if target >= 0.6:
            # Spread assignment: same type tiles are placed far apart
            self._assign_tiles_with_spread(
                level, all_layer_positions, tile_assignments, tile_types, target
            )
        else:
            # Original random shuffle for easy/medium levels
            random.shuffle(tile_assignments)

            # Assign tiles to positions
            for i, (layer_idx, pos) in enumerate(all_layer_positions):
                if i < len(tile_assignments):
                    tile_type = tile_assignments[i]
                else:
                    # Fallback (shouldn't happen)
                    tile_type = random.choice(tile_types)

                layer_key = f"layer_{layer_idx}"
                level[layer_key]["tiles"][pos] = [tile_type, ""]

        # Update tile counts
        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        return level

    def _assign_tiles_with_spread(
        self,
        level: Dict[str, Any],
        all_layer_positions: List[Tuple[int, str]],
        tile_assignments: List[str],
        tile_types: List[str],
        target_difficulty: float
    ) -> None:
        """Assign tile types with same-type tiles spread apart for higher difficulty.

        For hard levels, this places tiles of the same type as far apart as possible,
        making it harder to find and match them.

        Args:
            level: Level dict to modify
            all_layer_positions: List of (layer_idx, pos) tuples
            tile_assignments: List of tile types to assign
            tile_types: Available tile types
            target_difficulty: Target difficulty (0.0-1.0)
        """
        from collections import defaultdict

        def get_pos_coords(pos: str) -> Tuple[int, int]:
            """Extract x, y from position string."""
            parts = pos.split("_")
            return int(parts[0]), int(parts[1])

        def calc_distance(pos1: str, layer1: int, pos2: str, layer2: int) -> float:
            """Calculate distance between two positions (including layer difference)."""
            x1, y1 = get_pos_coords(pos1)
            x2, y2 = get_pos_coords(pos2)
            # Include layer difference as additional distance factor
            layer_dist = abs(layer1 - layer2) * 2  # Layer separation adds distance
            return ((x1 - x2) ** 2 + (y1 - y2) ** 2 + layer_dist ** 2) ** 0.5

        def min_distance_to_same_type(
            pos: str, layer: int, tile_type: str, placed: Dict[str, List[Tuple[int, str]]]
        ) -> float:
            """Calculate minimum distance from pos to any placed tile of same type."""
            if tile_type not in placed or not placed[tile_type]:
                return float('inf')  # No same-type tiles yet, maximum distance

            min_dist = float('inf')
            for placed_layer, placed_pos in placed[tile_type]:
                dist = calc_distance(pos, layer, placed_pos, placed_layer)
                min_dist = min(min_dist, dist)
            return min_dist

        # Count how many of each type we need
        type_counts = defaultdict(int)
        for t in tile_assignments:
            type_counts[t] += 1

        # Track placed tiles by type: {type: [(layer, pos), ...]}
        placed_tiles: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

        # Available positions (copy to modify)
        available_positions = list(all_layer_positions)
        random.shuffle(available_positions)  # Start with random order

        # Spread intensity based on difficulty (0.6 = mild spread, 1.0 = maximum spread)
        # Higher intensity = more strictly enforce distance
        spread_intensity = (target_difficulty - 0.6) / 0.4  # 0.0 to 1.0 for difficulty 0.6-1.0
        spread_intensity = max(0.0, min(1.0, spread_intensity))

        # For each tile type, place tiles trying to maximize distance from same type
        types_to_place = list(type_counts.keys())
        random.shuffle(types_to_place)

        for tile_type in types_to_place:
            count = type_counts[tile_type]

            for _ in range(count):
                if not available_positions:
                    break

                # Find position with maximum distance from existing same-type tiles
                best_pos = None
                best_layer = None
                best_score = -1

                # Sample positions to check (for performance, don't check all)
                sample_size = min(len(available_positions), max(10, int(len(available_positions) * 0.3)))
                positions_to_check = random.sample(available_positions, sample_size)

                for layer_idx, pos in positions_to_check:
                    min_dist = min_distance_to_same_type(pos, layer_idx, tile_type, placed_tiles)

                    # Score combines distance with some randomness (based on spread intensity)
                    # Low intensity = more random, High intensity = strictly distance-based
                    random_factor = random.random() * (1 - spread_intensity) * 5
                    score = min_dist + random_factor

                    if score > best_score:
                        best_score = score
                        best_pos = pos
                        best_layer = layer_idx

                if best_pos is not None:
                    # Place tile
                    layer_key = f"layer_{best_layer}"
                    level[layer_key]["tiles"][best_pos] = [tile_type, ""]

                    # Track placement
                    placed_tiles[tile_type].append((best_layer, best_pos))

                    # Remove from available
                    available_positions.remove((best_layer, best_pos))

        # If any positions left (shouldn't happen), fill with random types
        for layer_idx, pos in available_positions:
            tile_type = random.choice(tile_types)
            layer_key = f"layer_{layer_idx}"
            level[layer_key]["tiles"][pos] = [tile_type, ""]

    def _generate_layer_positions(
        self, cols: int, rows: int, density: float,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None
    ) -> List[str]:
        """Generate tile positions for a layer based on density."""
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Select positions based on density
        target_count = max(1, int(len(all_positions) * density))

        # IMPORTANT: Ensure tile count is divisible by 3 for match-3 game
        target_count = (target_count // 3) * 3
        if target_count == 0:
            target_count = 3  # Minimum 3 tiles

        selected = self._generate_positions_with_pattern(
            cols, rows, target_count, symmetry_mode, pattern_type
        )

        return selected

    def _generate_layer_positions_for_count(
        self, cols: int, rows: int, target_count: int,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None,
        pattern_index: Optional[int] = None
    ) -> List[str]:
        """Generate tile positions for a layer with specific count."""
        # Clamp to available positions
        max_positions = cols * rows
        actual_count = min(target_count, max_positions)
        if actual_count <= 0:
            return []

        selected = self._generate_positions_with_pattern(
            cols, rows, actual_count, symmetry_mode, pattern_type, pattern_index
        )

        # CRITICAL: When symmetry is applied, do NOT trim or pad randomly
        # as it would break the symmetric pattern. Only adjust for "none" symmetry.
        has_symmetry = symmetry_mode and symmetry_mode != "none"

        if has_symmetry:
            # For symmetric patterns, return as-is to preserve symmetry
            # The tile assignment code will handle any count differences
            return selected

        # Only for symmetry_mode="none": Ensure exact tile count by trimming or padding
        if len(selected) > actual_count:
            # Trim excess - prefer to keep positions closer to center
            center_x, center_y = cols / 2.0, rows / 2.0
            def distance_from_center(pos: str) -> float:
                parts = pos.split("_")
                x, y = int(parts[0]), int(parts[1])
                return ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
            selected.sort(key=distance_from_center)
            selected = selected[:actual_count]
        elif len(selected) < actual_count:
            # Pad with random unused positions
            all_positions = set(f"{x}_{y}" for x in range(cols) for y in range(rows))
            unused = list(all_positions - set(selected))
            if unused:
                random.shuffle(unused)
                needed = actual_count - len(selected)
                selected.extend(unused[:needed])

        return selected

    def _generate_positions_with_pattern(
        self, cols: int, rows: int, target_count: int,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None,
        pattern_index: Optional[int] = None
    ) -> List[str]:
        """Generate positions with symmetry and pattern options."""
        # Default to geometric pattern for more regular shapes
        pattern = pattern_type or "geometric"

        # Resolve symmetry mode:
        # - "none" explicitly passed: truly no symmetry (for exact tile counts)
        # - None (not specified): random single-axis for visual appeal
        # - "both": 4-way symmetry for aesthetic patterns
        if symmetry_mode == "none":
            # User explicitly requested no symmetry - respect this for exact counts
            symmetry = "none"
        elif symmetry_mode is None:
            # Default: weighted random symmetry based on GBoost level analysis
            # Human-designed levels show 73% horizontal symmetry, 33% vertical symmetry
            # This creates visually balanced and appealing tile arrangements
            symmetry_options = ["horizontal", "vertical", "none", "both"]
            # 55% horizontal (primary), 15% vertical, 15% none, 15% both
            # Combined h+both = 70% horizontal influence (close to 73% observed)
            symmetry_weights = [0.55, 0.15, 0.15, 0.15]
            symmetry = random.choices(symmetry_options, weights=symmetry_weights, k=1)[0]
        else:
            symmetry = symmetry_mode

        # DEBUG: Log position generation parameters
        import logging
        _logger = logging.getLogger(__name__)
        _logger.debug(f"[POSITION_GEN_DEBUG] cols={cols}, rows={rows}, target_count={target_count}, "
                      f"symmetry_mode={symmetry_mode}, symmetry={symmetry}, pattern={pattern}")

        # Generate base positions based on pattern type
        if pattern == "aesthetic":
            # Aesthetic mode: generate pattern then apply symmetry mirroring
            raw_positions = self._generate_aesthetic_positions(cols, rows, target_count, pattern_index)
            # Apply symmetry to aesthetic patterns too
            base_positions = self._apply_symmetry_to_positions(cols, rows, raw_positions, symmetry, target_count)
        elif pattern == "geometric":
            base_positions = self._generate_geometric_positions(cols, rows, target_count, symmetry)
        elif pattern == "clustered":
            base_positions = self._generate_clustered_positions(cols, rows, target_count, symmetry)
        else:  # random
            base_positions = self._generate_random_positions(cols, rows, target_count, symmetry)

        return base_positions

    def _generate_aesthetic_positions(
        self, cols: int, rows: int, target_count: int,
        pattern_index: Optional[int] = None
    ) -> List[str]:
        """Generate visually appealing positions using 50 diverse patterns.

        Patterns are inspired by high-level stages from Tile Buster, Triple Match 3D,
        Tile Explorer, and other popular tile-matching puzzle games.

        Categories:
        - 0-9: Basic shapes (rectangle, diamond, oval, cross, donut, etc.)
        - 10-14: Arrow/Direction patterns
        - 15-19: Star/Celestial patterns
        - 20-29: Letter shapes (H, I, L, U, X, Y, Z, S, O, C)
        - 30-39: Advanced geometric (triangles, hourglass, stairs, pyramid, zigzag)
        - 40-44: Frame/Border patterns
        - 45-49: Artistic patterns (butterfly, flower, islands, stripes, honeycomb)

        Args:
            cols: Grid columns
            rows: Grid rows
            target_count: Target number of tiles
            pattern_index: If specified (0-49), forces use of that specific pattern.
                          None = auto-select best pattern based on target_count.
        """
        import math
        center_x, center_y = cols / 2.0, rows / 2.0

        # ============ Category 1: Basic Shapes (0-9) ============

        # Pattern 0: Filled Rectangle
        def filled_rectangle():
            aspect_ratio = cols / rows
            rect_height = int((target_count / aspect_ratio) ** 0.5)
            rect_width = int(rect_height * aspect_ratio)
            if rect_width * rect_height < target_count:
                rect_width += 1
            if rect_width * rect_height < target_count:
                rect_height += 1
            start_x = int((cols - rect_width) / 2)
            start_y = int((rows - rect_height) / 2)
            positions = []
            for x in range(start_x, min(cols, start_x + rect_width)):
                for y in range(start_y, min(rows, start_y + rect_height)):
                    if x >= 0 and y >= 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 1: Diamond/Rhombus shape
        def diamond_shape():
            radius = int((target_count * 2) ** 0.5)
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dist = abs(x - center_x + 0.5) + abs(y - center_y + 0.5)
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 2: Oval/Ellipse shape
        def oval_shape():
            radius_x = int((target_count * cols / (rows * 3.14)) ** 0.5) + 1
            radius_y = int((target_count * rows / (cols * 3.14)) ** 0.5) + 1
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / max(1, radius_x)
                    dy = (y - center_y + 0.5) / max(1, radius_y)
                    if dx * dx + dy * dy <= 1.0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 3: Plus/Cross shape
        def cross_shape():
            positions = []
            arm_width = max(2, int(cols * 0.4))
            arm_height = max(2, int(rows * 0.4))
            start_x = int((cols - arm_width) / 2)
            start_y = int((rows - arm_height) / 2)
            for x in range(cols):
                for y in range(start_y, min(rows, start_y + arm_height)):
                    positions.append(f"{x}_{y}")
            for x in range(start_x, min(cols, start_x + arm_width)):
                for y in range(rows):
                    if f"{x}_{y}" not in positions:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 4: Donut shape (hollow center)
        def donut_shape():
            outer_radius = int((target_count / 2.5) ** 0.5) + 2
            inner_radius = max(1, outer_radius // 3)
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dist = ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
                    if inner_radius <= dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 5: Concentric diamond
        def concentric_diamond():
            positions = []
            outer_radius = int((target_count * 2) ** 0.5)
            for x in range(cols):
                for y in range(rows):
                    dist = abs(x - center_x + 0.5) + abs(y - center_y + 0.5)
                    if dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 6: Corner-anchored pattern
        def corner_anchored():
            positions = []
            corner_size = max(1, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    is_corner = (
                        (x < corner_size and y < corner_size) or
                        (x < corner_size and y >= rows - corner_size) or
                        (x >= cols - corner_size and y < corner_size) or
                        (x >= cols - corner_size and y >= rows - corner_size)
                    )
                    if not is_corner:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 7: Hexagonal-ish pattern
        def hexagonal():
            positions = []
            radius = int((target_count / 2.6) ** 0.5) + 1
            for x in range(cols):
                for y in range(rows):
                    dx = abs(x - center_x + 0.5)
                    dy = abs(y - center_y + 0.5) * 1.15
                    dist = max(dx, dy, (dx + dy) * 0.55)
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 8: Heart shape
        def heart_shape():
            positions = []
            scale = max(cols, rows) / 8
            for x in range(cols):
                for y in range(rows):
                    nx = (x - center_x + 0.5) / scale
                    ny = -(y - center_y + 0.5) / scale + 0.5
                    value = (nx**2 + ny**2 - 1)**3 - (nx**2) * (ny**3)
                    if value <= 0.5:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 9: T-shape
        def t_shape():
            positions = []
            bar_height = max(2, rows // 4)
            stem_width = max(2, cols // 3)
            stem_start_x = int((cols - stem_width) / 2)
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            for x in range(stem_start_x, min(cols, stem_start_x + stem_width)):
                for y in range(bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # ============ Category 2: Arrow/Direction Patterns (10-14) ============

        # Pattern 10: Arrow Up
        def arrow_up():
            positions = []
            tip_y = 0
            base_y = rows - 1
            arrow_width = max(2, cols // 3)
            start_x = int((cols - arrow_width) / 2)
            # Arrow head (triangle)
            for y in range(rows // 2):
                width = max(1, (y + 1) * 2)
                sx = int(center_x - width / 2)
                for x in range(sx, min(cols, sx + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            # Arrow stem
            for x in range(start_x, min(cols, start_x + arrow_width)):
                for y in range(rows // 2, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 11: Arrow Down
        def arrow_down():
            positions = []
            arrow_width = max(2, cols // 3)
            start_x = int((cols - arrow_width) / 2)
            # Arrow stem (top)
            for x in range(start_x, min(cols, start_x + arrow_width)):
                for y in range(rows // 2):
                    positions.append(f"{x}_{y}")
            # Arrow head (triangle pointing down)
            for y in range(rows // 2, rows):
                rel_y = y - rows // 2
                width = max(1, cols - rel_y * 2)
                sx = int(center_x - width / 2)
                for x in range(sx, min(cols, sx + width)):
                    if 0 <= x < cols and width > 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 12: Arrow Left
        def arrow_left():
            positions = []
            arrow_height = max(2, rows // 3)
            start_y = int((rows - arrow_height) / 2)
            # Arrow head (triangle pointing left)
            for x in range(cols // 2):
                height = max(1, (x + 1) * 2)
                sy = int(center_y - height / 2)
                for y in range(sy, min(rows, sy + height)):
                    if 0 <= y < rows:
                        positions.append(f"{x}_{y}")
            # Arrow stem
            for y in range(start_y, min(rows, start_y + arrow_height)):
                for x in range(cols // 2, cols):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 13: Arrow Right
        def arrow_right():
            positions = []
            arrow_height = max(2, rows // 3)
            start_y = int((rows - arrow_height) / 2)
            # Arrow stem (left side)
            for y in range(start_y, min(rows, start_y + arrow_height)):
                for x in range(cols // 2):
                    positions.append(f"{x}_{y}")
            # Arrow head (triangle pointing right)
            for x in range(cols // 2, cols):
                rel_x = x - cols // 2
                height = max(1, rows - rel_x * 2)
                sy = int(center_y - height / 2)
                for y in range(sy, min(rows, sy + height)):
                    if 0 <= y < rows and height > 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 14: Chevron (double arrow)
        def chevron_pattern():
            positions = []
            thickness = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    # V shape
                    v_dist = abs(y - (rows - 1 - abs(x - center_x + 0.5) * rows / cols * 0.8))
                    if v_dist <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 3: Star/Celestial Patterns (15-19) ============

        # Pattern 15: Five-pointed Star
        def star_five_point():
            positions = []
            radius = min(cols, rows) / 2.5
            inner_radius = radius * 0.4
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    angle = math.atan2(dy, dx)
                    dist = (dx**2 + dy**2) ** 0.5
                    # Star shape formula
                    star_angle = (angle + math.pi) % (2 * math.pi / 5)
                    star_radius = inner_radius + (radius - inner_radius) * abs(math.cos(star_angle * 2.5))
                    if dist <= star_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 16: Six-pointed Star (Star of David)
        def star_six_point():
            positions = []
            radius = min(cols, rows) / 2.5
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    # Two overlapping triangles
                    tri1 = (dy <= radius * 0.5 - abs(dx) * 0.866) or (dy >= -radius * 0.5 + abs(dx) * 0.866 and dy <= 0)
                    tri2 = (dy >= -radius * 0.5 + abs(dx) * 0.866) or (dy <= radius * 0.5 - abs(dx) * 0.866 and dy >= 0)
                    dist = abs(dx) + abs(dy) * 0.7
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 17: Crescent Moon
        def crescent_moon():
            positions = []
            outer_radius = min(cols, rows) / 2.2
            inner_radius = outer_radius * 0.7
            offset_x = outer_radius * 0.5
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    outer_dist = (dx**2 + dy**2) ** 0.5
                    inner_dist = ((dx + offset_x)**2 + dy**2) ** 0.5
                    if outer_dist <= outer_radius and inner_dist > inner_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 18: Sun Burst
        def sun_burst():
            positions = []
            core_radius = min(cols, rows) / 4
            ray_length = min(cols, rows) / 2.5
            num_rays = 8
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx**2 + dy**2) ** 0.5
                    angle = math.atan2(dy, dx)
                    # Core circle
                    if dist <= core_radius:
                        positions.append(f"{x}_{y}")
                    # Rays
                    elif dist <= ray_length:
                        ray_angle = (angle + math.pi) % (2 * math.pi / num_rays)
                        if ray_angle < math.pi / num_rays * 0.5 or ray_angle > 2 * math.pi / num_rays - math.pi / num_rays * 0.5:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 19: Spiral
        def spiral():
            positions = []
            max_radius = min(cols, rows) / 2.2
            turns = 2.5
            thickness = max(1.5, min(cols, rows) / 8)
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx**2 + dy**2) ** 0.5
                    if dist < 0.5:
                        positions.append(f"{x}_{y}")
                        continue
                    angle = math.atan2(dy, dx)
                    expected_dist = (angle + math.pi) / (2 * math.pi) * max_radius / turns
                    for i in range(int(turns) + 1):
                        check_dist = expected_dist + i * max_radius / turns
                        if abs(dist - check_dist) <= thickness:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # ============ Category 4: Letter Shapes (20-29) ============

        # Pattern 20: Letter H
        def letter_H():
            positions = []
            bar_width = max(2, cols // 4)
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            for x in range(cols - bar_width, cols):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            mid_y = rows // 2
            bar_height = max(2, rows // 4)
            for x in range(bar_width, cols - bar_width):
                for y in range(mid_y - bar_height // 2, mid_y + bar_height // 2 + 1):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 21: Letter I
        def letter_I():
            positions = []
            bar_height = max(2, rows // 4)
            stem_width = max(2, cols // 3)
            stem_start = int((cols - stem_width) / 2)
            # Top bar
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            # Bottom bar
            for x in range(cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            # Stem
            for x in range(stem_start, stem_start + stem_width):
                for y in range(bar_height, rows - bar_height):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 22: Letter L
        def letter_L():
            positions = []
            bar_width = max(2, cols // 3)
            bar_height = max(2, rows // 4)
            # Vertical bar
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Horizontal bar at bottom
            for x in range(bar_width, cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 23: Letter U
        def letter_U():
            positions = []
            bar_width = max(2, cols // 4)
            bar_height = max(2, rows // 4)
            # Left vertical
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Right vertical
            for x in range(cols - bar_width, cols):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Bottom connector
            for x in range(bar_width, cols - bar_width):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 24: Letter X
        def letter_X():
            positions = []
            thickness = max(1.5, min(cols, rows) / 5)
            for x in range(cols):
                for y in range(rows):
                    # Diagonal 1 (top-left to bottom-right)
                    d1 = abs((x - center_x) - (y - center_y) * cols / rows)
                    # Diagonal 2 (top-right to bottom-left)
                    d2 = abs((x - center_x) + (y - center_y) * cols / rows)
                    if d1 <= thickness or d2 <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 25: Letter Y
        def letter_Y():
            positions = []
            stem_width = max(2, cols // 3)
            stem_start = int((cols - stem_width) / 2)
            mid_y = rows // 2
            thickness = max(1.5, cols / 5)
            # Top diagonals
            for x in range(cols):
                for y in range(mid_y):
                    d1 = abs((x - center_x) - (y - mid_y) * cols / rows)
                    d2 = abs((x - center_x) + (y - mid_y) * cols / rows)
                    if d1 <= thickness or d2 <= thickness:
                        positions.append(f"{x}_{y}")
            # Bottom stem
            for x in range(stem_start, stem_start + stem_width):
                for y in range(mid_y, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 26: Letter Z
        def letter_Z():
            positions = []
            bar_height = max(2, rows // 4)
            thickness = max(1.5, min(cols, rows) / 5)
            # Top bar
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            # Bottom bar
            for x in range(cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            # Diagonal
            for x in range(cols):
                for y in range(bar_height, rows - bar_height):
                    expected_x = cols - 1 - (y - bar_height) * cols / (rows - 2 * bar_height)
                    if abs(x - expected_x) <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 27: Letter S
        def letter_S():
            positions = []
            bar_height = max(2, rows // 5)
            bar_width = max(2, cols // 4)
            # Top bar
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            # Upper left vertical
            for x in range(bar_width):
                for y in range(bar_height, rows // 2):
                    positions.append(f"{x}_{y}")
            # Middle bar
            for x in range(cols):
                for y in range(rows // 2 - bar_height // 2, rows // 2 + bar_height // 2 + 1):
                    positions.append(f"{x}_{y}")
            # Lower right vertical
            for x in range(cols - bar_width, cols):
                for y in range(rows // 2 + 1, rows - bar_height):
                    positions.append(f"{x}_{y}")
            # Bottom bar
            for x in range(cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 28: Letter O (ring)
        def letter_O():
            positions = []
            outer_rx = cols / 2.2
            outer_ry = rows / 2.2
            inner_rx = outer_rx * 0.5
            inner_ry = outer_ry * 0.5
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / outer_rx
                    dy = (y - center_y + 0.5) / outer_ry
                    outer_dist = dx * dx + dy * dy
                    dx2 = (x - center_x + 0.5) / inner_rx
                    dy2 = (y - center_y + 0.5) / inner_ry
                    inner_dist = dx2 * dx2 + dy2 * dy2
                    if outer_dist <= 1.0 and inner_dist >= 1.0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 29: Letter C
        def letter_C():
            positions = []
            outer_rx = cols / 2.2
            outer_ry = rows / 2.2
            inner_rx = outer_rx * 0.5
            inner_ry = outer_ry * 0.5
            gap_width = cols / 3
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / outer_rx
                    dy = (y - center_y + 0.5) / outer_ry
                    outer_dist = dx * dx + dy * dy
                    dx2 = (x - center_x + 0.5) / inner_rx
                    dy2 = (y - center_y + 0.5) / inner_ry
                    inner_dist = dx2 * dx2 + dy2 * dy2
                    # C shape - open on the right
                    if outer_dist <= 1.0 and inner_dist >= 1.0 and x < cols - gap_width:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 5: Advanced Geometric (30-39) ============

        # Pattern 30: Triangle Up
        def triangle_up():
            positions = []
            for y in range(rows):
                width = int((rows - y) * cols / rows)
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 31: Triangle Down
        def triangle_down():
            positions = []
            for y in range(rows):
                width = int((y + 1) * cols / rows)
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 32: Hourglass
        def hourglass():
            positions = []
            for y in range(rows):
                # Distance from center row
                dist_from_center = abs(y - center_y)
                width = int(cols * (dist_from_center / center_y + 0.3))
                width = max(2, min(cols, width))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 33: Bowtie
        def bowtie():
            positions = []
            for y in range(rows):
                dist_from_center = abs(y - center_y)
                width = int(cols * (1 - dist_from_center / center_y * 0.7))
                width = max(2, min(cols, width))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 34: Stairs Ascending (left to right)
        def stairs_ascending():
            positions = []
            num_steps = min(cols, rows) // 2
            step_width = cols // num_steps
            step_height = rows // num_steps
            for step in range(num_steps):
                x_start = step * step_width
                y_start = rows - (step + 1) * step_height
                for x in range(x_start, min(cols, x_start + step_width + 1)):
                    for y in range(max(0, y_start), rows):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 35: Stairs Descending
        def stairs_descending():
            positions = []
            num_steps = min(cols, rows) // 2
            step_width = cols // num_steps
            step_height = rows // num_steps
            for step in range(num_steps):
                x_start = step * step_width
                y_end = (step + 1) * step_height
                for x in range(x_start, min(cols, x_start + step_width + 1)):
                    for y in range(min(rows, y_end)):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 36: Pyramid
        def pyramid():
            positions = []
            levels = min(rows, cols // 2)
            for level in range(levels):
                y = rows - 1 - level
                width = (level + 1) * 2 - 1
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols and 0 <= y < rows:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 37: Inverted Pyramid
        def inverted_pyramid():
            positions = []
            levels = min(rows, cols // 2)
            for level in range(levels):
                y = level
                width = (levels - level) * 2 - 1
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 38: Zigzag Horizontal
        def zigzag_horizontal():
            positions = []
            amplitude = rows // 3
            period = cols // 3
            thickness = max(2, rows // 4)
            for x in range(cols):
                base_y = int(center_y + amplitude * math.sin(x * 2 * math.pi / period))
                for y in range(max(0, base_y - thickness), min(rows, base_y + thickness + 1)):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 39: Wave Pattern
        def wave_pattern():
            positions = []
            num_waves = 3
            wave_height = rows // (num_waves * 2)
            for x in range(cols):
                for y in range(rows):
                    wave_offset = int(wave_height * math.sin(x * 2 * math.pi / (cols / 2)))
                    if (y + wave_offset) % (rows // num_waves) < rows // num_waves // 2:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 6: Frame/Border Patterns (40-44) ============

        # Pattern 40: Frame Border
        def frame_border():
            positions = []
            border_width = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    if x < border_width or x >= cols - border_width or y < border_width or y >= rows - border_width:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 41: Double Frame
        def double_frame():
            positions = []
            outer_width = max(1, min(cols, rows) // 6)
            gap = max(1, min(cols, rows) // 6)
            inner_width = max(1, min(cols, rows) // 6)
            for x in range(cols):
                for y in range(rows):
                    # Outer frame
                    if x < outer_width or x >= cols - outer_width or y < outer_width or y >= rows - outer_width:
                        positions.append(f"{x}_{y}")
                    # Inner frame
                    inner_start = outer_width + gap
                    inner_end_x = cols - outer_width - gap
                    inner_end_y = rows - outer_width - gap
                    if inner_start <= x < inner_end_x and inner_start <= y < inner_end_y:
                        if x < inner_start + inner_width or x >= inner_end_x - inner_width or y < inner_start + inner_width or y >= inner_end_y - inner_width:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 42: Corner Triangles
        def corner_triangles():
            positions = []
            tri_size = min(cols, rows) // 3
            for x in range(cols):
                for y in range(rows):
                    # Top-left
                    if x + y < tri_size:
                        positions.append(f"{x}_{y}")
                    # Top-right
                    elif (cols - 1 - x) + y < tri_size:
                        positions.append(f"{x}_{y}")
                    # Bottom-left
                    elif x + (rows - 1 - y) < tri_size:
                        positions.append(f"{x}_{y}")
                    # Bottom-right
                    elif (cols - 1 - x) + (rows - 1 - y) < tri_size:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 43: Center Hollow (filled corners, hollow center)
        def center_hollow():
            positions = []
            hollow_size = min(cols, rows) // 3
            hollow_x_start = int((cols - hollow_size) / 2)
            hollow_y_start = int((rows - hollow_size) / 2)
            for x in range(cols):
                for y in range(rows):
                    # Not in center hollow
                    if not (hollow_x_start <= x < hollow_x_start + hollow_size and hollow_y_start <= y < hollow_y_start + hollow_size):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 44: Window Panes (4 quadrants)
        def window_panes():
            positions = []
            gap = max(1, min(cols, rows) // 6)
            mid_x = cols // 2
            mid_y = rows // 2
            for x in range(cols):
                for y in range(rows):
                    # Not in center cross
                    if not (mid_x - gap <= x < mid_x + gap or mid_y - gap <= y < mid_y + gap):
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 7: Artistic Patterns (45-49) ============

        # Pattern 45: Butterfly
        def butterfly():
            positions = []
            wing_radius = min(cols, rows) / 2.5
            body_width = max(1, cols // 6)
            for x in range(cols):
                for y in range(rows):
                    dx = abs(x - center_x + 0.5)
                    dy = y - center_y + 0.5
                    # Wings (two circles offset from center)
                    wing_dist = ((dx - wing_radius * 0.5) ** 2 + dy ** 2) ** 0.5
                    # Body (center column)
                    if wing_dist <= wing_radius * 0.7 or dx <= body_width / 2:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 46: Flower Pattern (petals around center)
        def flower_pattern():
            positions = []
            petal_radius = min(cols, rows) / 3
            center_radius = min(cols, rows) / 6
            num_petals = 6
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx ** 2 + dy ** 2) ** 0.5
                    # Center
                    if dist <= center_radius:
                        positions.append(f"{x}_{y}")
                    else:
                        # Petals
                        angle = math.atan2(dy, dx)
                        for i in range(num_petals):
                            petal_angle = i * 2 * math.pi / num_petals
                            petal_cx = center_x + math.cos(petal_angle) * petal_radius * 0.7
                            petal_cy = center_y + math.sin(petal_angle) * petal_radius * 0.7
                            petal_dist = ((x - petal_cx) ** 2 + (y - petal_cy) ** 2) ** 0.5
                            if petal_dist <= petal_radius * 0.5:
                                positions.append(f"{x}_{y}")
                                break
            return positions

        # Pattern 47: Scattered Islands
        def scattered_islands():
            positions = []
            # Create 4-6 island clusters with random positions for variety
            num_islands = min(6, max(4, (cols * rows) // 30))
            islands = []
            for _ in range(num_islands):
                ix = random.randint(1, cols - 2)
                iy = random.randint(1, rows - 2)
                ir = random.uniform(1.5, min(cols, rows) / 4)
                islands.append((ix, iy, ir))
            for x in range(cols):
                for y in range(rows):
                    for ix, iy, ir in islands:
                        if ((x - ix) ** 2 + (y - iy) ** 2) ** 0.5 <= ir:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # Pattern 48: Diagonal Stripes
        def diagonal_stripes():
            positions = []
            stripe_width = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    if ((x + y) // stripe_width) % 2 == 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 49: Honeycomb
        def honeycomb():
            positions = []
            cell_size = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    # Offset every other row
                    offset = (cell_size // 2) if (y // cell_size) % 2 == 1 else 0
                    cell_x = (x + offset) // cell_size
                    cell_y = y // cell_size
                    # Create hexagonal-ish cells
                    local_x = (x + offset) % cell_size
                    local_y = y % cell_size
                    # Fill cells but leave small gaps
                    if local_x > 0 and local_x < cell_size - 1 and local_y > 0 and local_y < cell_size - 1:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 8: Bridge/Island Patterns (50-55) ============
        # Inspired by Tile Explorer game's island+bridge level designs

        # Helper function for bridge patterns - calculate point to line distance
        def point_to_line_distance(px, py, x1, y1, x2, y2):
            """Calculate perpendicular distance from point (px,py) to line segment (x1,y1)-(x2,y2)."""
            line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
            if line_len_sq == 0:
                return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
            t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
            proj_x = x1 + t * (x2 - x1)
            proj_y = y1 + t * (y2 - y1)
            return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5

        # Pattern 50: Two Islands with Bridge (horizontal)
        def bridge_horizontal():
            """Two circular islands connected by a horizontal bridge."""
            positions = []
            island_radius = min(cols, rows) / 3.5
            bridge_width = max(2, rows // 5)

            # Left island center
            left_cx = cols / 4
            left_cy = rows / 2

            # Right island center
            right_cx = cols * 3 / 4
            right_cy = rows / 2

            for x in range(cols):
                for y in range(rows):
                    # Left island
                    left_dist = ((x - left_cx) ** 2 + (y - left_cy) ** 2) ** 0.5
                    # Right island
                    right_dist = ((x - right_cx) ** 2 + (y - right_cy) ** 2) ** 0.5
                    # Bridge (horizontal connection in center)
                    in_bridge = (left_cx <= x <= right_cx and
                                 rows / 2 - bridge_width / 2 <= y <= rows / 2 + bridge_width / 2)

                    if left_dist <= island_radius or right_dist <= island_radius or in_bridge:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 51: Two Islands with Bridge (vertical)
        def bridge_vertical():
            """Two circular islands connected by a vertical bridge."""
            positions = []
            island_radius = min(cols, rows) / 3.5
            bridge_width = max(2, cols // 5)

            # Top island center
            top_cx = cols / 2
            top_cy = rows / 4

            # Bottom island center
            bottom_cx = cols / 2
            bottom_cy = rows * 3 / 4

            for x in range(cols):
                for y in range(rows):
                    # Top island
                    top_dist = ((x - top_cx) ** 2 + (y - top_cy) ** 2) ** 0.5
                    # Bottom island
                    bottom_dist = ((x - bottom_cx) ** 2 + (y - bottom_cy) ** 2) ** 0.5
                    # Bridge (vertical connection in center)
                    in_bridge = (top_cy <= y <= bottom_cy and
                                 cols / 2 - bridge_width / 2 <= x <= cols / 2 + bridge_width / 2)

                    if top_dist <= island_radius or bottom_dist <= island_radius or in_bridge:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 52: Three Islands Triangle (with bridges)
        def three_islands_triangle():
            """Three islands arranged in a triangle with connecting bridges."""
            positions = []
            island_radius = min(cols, rows) / 4.5
            bridge_width = max(2, min(cols, rows) // 6)

            # Island centers (triangle arrangement)
            top_cx, top_cy = cols / 2, rows / 4
            left_cx, left_cy = cols / 4, rows * 3 / 4
            right_cx, right_cy = cols * 3 / 4, rows * 3 / 4

            islands = [(top_cx, top_cy), (left_cx, left_cy), (right_cx, right_cy)]

            for x in range(cols):
                for y in range(rows):
                    in_pattern = False

                    # Check islands
                    for cx, cy in islands:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= island_radius:
                            in_pattern = True
                            break

                    # Check bridges (connecting all islands)
                    if not in_pattern:
                        # Top to left bridge
                        t_l_dist = point_to_line_distance(x, y, top_cx, top_cy, left_cx, left_cy)
                        if t_l_dist <= bridge_width / 2 and min(top_cx, left_cx) - 1 <= x <= max(top_cx, left_cx) + 1:
                            if min(top_cy, left_cy) - 1 <= y <= max(top_cy, left_cy) + 1:
                                in_pattern = True

                        # Top to right bridge
                        t_r_dist = point_to_line_distance(x, y, top_cx, top_cy, right_cx, right_cy)
                        if t_r_dist <= bridge_width / 2 and min(top_cx, right_cx) - 1 <= x <= max(top_cx, right_cx) + 1:
                            if min(top_cy, right_cy) - 1 <= y <= max(top_cy, right_cy) + 1:
                                in_pattern = True

                        # Left to right bridge
                        l_r_dist = point_to_line_distance(x, y, left_cx, left_cy, right_cx, right_cy)
                        if l_r_dist <= bridge_width / 2 and min(left_cx, right_cx) - 1 <= x <= max(left_cx, right_cx) + 1:
                            if min(left_cy, right_cy) - 1 <= y <= max(left_cy, right_cy) + 1:
                                in_pattern = True

                    if in_pattern:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 53: Four Islands Grid (with bridges)
        def four_islands_grid():
            """Four islands in a 2x2 grid with connecting bridges."""
            positions = []
            island_radius = min(cols, rows) / 4.5
            bridge_width = max(2, min(cols, rows) // 7)

            # Island centers (2x2 grid)
            islands = [
                (cols / 4, rows / 4),       # Top-left
                (cols * 3 / 4, rows / 4),   # Top-right
                (cols / 4, rows * 3 / 4),   # Bottom-left
                (cols * 3 / 4, rows * 3 / 4)  # Bottom-right
            ]

            for x in range(cols):
                for y in range(rows):
                    in_pattern = False

                    # Check islands
                    for cx, cy in islands:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= island_radius:
                            in_pattern = True
                            break

                    # Check horizontal bridges
                    if not in_pattern:
                        # Top horizontal bridge
                        if cols / 4 <= x <= cols * 3 / 4 and abs(y - rows / 4) <= bridge_width / 2:
                            in_pattern = True
                        # Bottom horizontal bridge
                        if cols / 4 <= x <= cols * 3 / 4 and abs(y - rows * 3 / 4) <= bridge_width / 2:
                            in_pattern = True
                        # Left vertical bridge
                        if rows / 4 <= y <= rows * 3 / 4 and abs(x - cols / 4) <= bridge_width / 2:
                            in_pattern = True
                        # Right vertical bridge
                        if rows / 4 <= y <= rows * 3 / 4 and abs(x - cols * 3 / 4) <= bridge_width / 2:
                            in_pattern = True

                    if in_pattern:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 54: Archipelago (distributed islands without bridges)
        def archipelago():
            """Multiple small islands distributed across the grid - Tile Explorer style."""
            positions = []
            # Create a grid-based island distribution for more regular spacing
            island_count_x = max(2, cols // 4)
            island_count_y = max(2, rows // 4)

            # Calculate spacing
            spacing_x = cols / (island_count_x + 1)
            spacing_y = rows / (island_count_y + 1)

            # Generate island centers with slight randomization
            islands = []
            for ix in range(island_count_x):
                for iy in range(island_count_y):
                    # Base position with some randomness
                    cx = spacing_x * (ix + 1) + random.uniform(-spacing_x * 0.2, spacing_x * 0.2)
                    cy = spacing_y * (iy + 1) + random.uniform(-spacing_y * 0.2, spacing_y * 0.2)
                    # Variable island size
                    radius = random.uniform(1.5, min(spacing_x, spacing_y) * 0.45)
                    islands.append((cx, cy, radius))

            for x in range(cols):
                for y in range(rows):
                    for cx, cy, radius in islands:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= radius:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # Pattern 55: Central Hub with Spokes
        def hub_and_spokes():
            """Central circular hub with radiating spoke connections."""
            positions = []
            hub_radius = min(cols, rows) / 4
            spoke_width = max(2, min(cols, rows) // 6)
            spoke_count = 4  # Four spokes

            for x in range(cols):
                for y in range(rows):
                    in_pattern = False

                    # Central hub
                    dist_from_center = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                    if dist_from_center <= hub_radius:
                        in_pattern = True

                    # Spokes (extending to edges)
                    if not in_pattern:
                        for i in range(spoke_count):
                            angle = i * math.pi / 2  # 0, 90, 180, 270 degrees
                            # Direction vector
                            dx_dir = math.cos(angle)
                            dy_dir = math.sin(angle)

                            # Project point onto spoke direction
                            px = x - center_x
                            py = y - center_y

                            # Distance along spoke direction
                            proj = px * dx_dir + py * dy_dir

                            # Distance perpendicular to spoke
                            perp_dist = abs(px * (-dy_dir) + py * dx_dir)

                            # In spoke if: beyond hub, within spoke width, and along spoke direction
                            if proj > hub_radius * 0.8 and perp_dist <= spoke_width / 2:
                                in_pattern = True
                                break

                    if in_pattern:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 9: GBoost Human-Designed Patterns (56-63) ============
        # These patterns are derived from analysis of 221 human-designed levels
        # from the GBoost production server (level_1 ~ level_221)

        # Pattern 56: GBoost Corner Blocks (inspired by level_200)
        # Four symmetric corner blocks with connecting elements
        def gboost_corner_blocks():
            """Four corner blocks with symmetric arrangement (level_200 style)."""
            positions = []
            block_size = max(2, min(cols, rows) // 4)
            margin = 1  # Edge margin

            for x in range(cols):
                for y in range(rows):
                    # Top-left corner block
                    in_tl = (margin <= x < margin + block_size and
                             margin <= y < margin + block_size)
                    # Top-right corner block
                    in_tr = (cols - margin - block_size <= x < cols - margin and
                             margin <= y < margin + block_size)
                    # Bottom-left corner block
                    in_bl = (margin <= x < margin + block_size and
                             rows - margin - block_size <= y < rows - margin)
                    # Bottom-right corner block
                    in_br = (cols - margin - block_size <= x < cols - margin and
                             rows - margin - block_size <= y < rows - margin)

                    if in_tl or in_tr or in_bl or in_br:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 57: GBoost Octagon Ring (inspired by level_50)
        # Octagonal ring shape with hollow center
        def gboost_octagon_ring():
            """Octagonal ring pattern with hollow center (level_50 style)."""
            positions = []
            outer_radius = min(cols, rows) * 0.45
            inner_radius = outer_radius * 0.35

            for x in range(cols):
                for y in range(rows):
                    dx = abs(x - center_x + 0.5)
                    dy = abs(y - center_y + 0.5)
                    # Octagon distance (Chebyshev-ish with corner cut)
                    dist = max(dx, dy) + min(dx, dy) * 0.41

                    if inner_radius <= dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 58: GBoost Diagonal Staircase (inspired by level_150)
        # Diagonal chain-like staircase pattern
        def gboost_diagonal_staircase():
            """Diagonal staircase pattern (level_150 chain style)."""
            positions = []
            step_size = max(2, min(cols, rows) // 5)

            for x in range(cols):
                for y in range(rows):
                    # Diagonal index (which step we're on)
                    step_idx = (x + y) // step_size
                    # Position within step
                    pos_in_step = (x + y) % step_size

                    # Include tiles that form the staircase pattern
                    if pos_in_step < step_size * 0.7:
                        # Add some depth to the steps
                        step_depth = abs(x - y) % step_size
                        if step_depth < step_size * 0.6:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 59: GBoost Symmetric Wings (inspired by level_100 diagonal mirror)
        # Diagonally mirrored wing pattern
        def gboost_symmetric_wings():
            """Diagonal mirrored wing pattern (level_100 style)."""
            positions = []
            wing_width = max(3, cols // 3)

            for x in range(cols):
                for y in range(rows):
                    # Distance from main diagonal
                    diag_dist = abs(x - y)
                    # Distance from anti-diagonal
                    anti_diag_dist = abs(x + y - (cols - 1))

                    # Create wings along both diagonals
                    if diag_dist <= wing_width or anti_diag_dist <= wing_width:
                        # Add some tapering toward edges
                        edge_dist = min(x, y, cols - 1 - x, rows - 1 - y)
                        if edge_dist >= 0 or diag_dist <= wing_width // 2:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 60: GBoost Scattered Clusters (common in mid-late levels)
        # Multiple small clusters distributed across the grid
        def gboost_scattered_clusters():
            """Multiple small clusters distributed across grid."""
            positions = []
            cluster_count = random.randint(4, 7)
            cluster_radius = min(cols, rows) / 5

            # Generate cluster centers with spacing
            centers = []
            for _ in range(cluster_count * 3):  # Try more times for better distribution
                cx = random.uniform(cluster_radius, cols - cluster_radius)
                cy = random.uniform(cluster_radius, rows - cluster_radius)

                # Check distance from existing centers
                too_close = False
                for ecx, ecy in centers:
                    if ((cx - ecx) ** 2 + (cy - ecy) ** 2) ** 0.5 < cluster_radius * 1.5:
                        too_close = True
                        break

                if not too_close and len(centers) < cluster_count:
                    centers.append((cx, cy))

            for x in range(cols):
                for y in range(rows):
                    for cx, cy in centers:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= cluster_radius * random.uniform(0.6, 1.0):
                            positions.append(f"{x}_{y}")
                            break

            return positions

        # Pattern 61: GBoost Cross Bridge (inspired by level_10)
        # Alternating tiles forming a cross-bridge pattern
        def gboost_cross_bridge():
            """Alternating cross-bridge pattern (level_10 style)."""
            positions = []

            # Horizontal bridge
            h_band_start = int(rows * 0.35)
            h_band_end = int(rows * 0.65)

            # Vertical bridge
            v_band_start = int(cols * 0.35)
            v_band_end = int(cols * 0.65)

            for x in range(cols):
                for y in range(rows):
                    in_h_band = h_band_start <= y < h_band_end
                    in_v_band = v_band_start <= x < v_band_end

                    # Checkerboard-like pattern with offset
                    checker = (x + y) % 3 != 0

                    if (in_h_band or in_v_band) and checker:
                        positions.append(f"{x}_{y}")

            return positions

        # Pattern 62: GBoost Triple Bar (horizontal bars pattern)
        # Three horizontal bars with gaps
        def gboost_triple_bar():
            """Three horizontal bars pattern."""
            positions = []
            bar_height = max(2, rows // 5)
            gap = max(1, rows // 7)

            bar_positions = [
                gap,
                rows // 2 - bar_height // 2,
                rows - gap - bar_height
            ]

            for x in range(cols):
                for y in range(rows):
                    for bar_y in bar_positions:
                        if bar_y <= y < bar_y + bar_height:
                            # Slight taper at edges
                            edge_margin = max(0, 2 - min(x, cols - 1 - x))
                            if edge_margin == 0:
                                positions.append(f"{x}_{y}")
                            break
            return positions

        # Pattern 63: GBoost Frame with Center (common frame + center dot)
        def gboost_frame_center():
            """Frame border with center cluster."""
            positions = []
            border_width = max(2, min(cols, rows) // 5)
            center_radius = min(cols, rows) / 4

            for x in range(cols):
                for y in range(rows):
                    # Border frame
                    in_frame = (x < border_width or x >= cols - border_width or
                                y < border_width or y >= rows - border_width)

                    # Center cluster
                    dist_from_center = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                    in_center = dist_from_center <= center_radius

                    if in_frame or in_center:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Build Pattern List ============

        all_patterns = [
            # Category 1: Basic Shapes (0-9)
            ("filled_rectangle", filled_rectangle),       # 0
            ("diamond_shape", diamond_shape),             # 1
            ("oval_shape", oval_shape),                   # 2
            ("cross_shape", cross_shape),                 # 3
            ("donut_shape", donut_shape),                 # 4
            ("concentric_diamond", concentric_diamond),   # 5
            ("corner_anchored", corner_anchored),         # 6
            ("hexagonal", hexagonal),                     # 7
            ("heart_shape", heart_shape),                 # 8
            ("t_shape", t_shape),                         # 9
            # Category 2: Arrow/Direction (10-14)
            ("arrow_up", arrow_up),                       # 10
            ("arrow_down", arrow_down),                   # 11
            ("arrow_left", arrow_left),                   # 12
            ("arrow_right", arrow_right),                 # 13
            ("chevron_pattern", chevron_pattern),         # 14
            # Category 3: Star/Celestial (15-19)
            ("star_five_point", star_five_point),         # 15
            ("star_six_point", star_six_point),           # 16
            ("crescent_moon", crescent_moon),             # 17
            ("sun_burst", sun_burst),                     # 18
            ("spiral", spiral),                           # 19
            # Category 4: Letter Shapes (20-29)
            ("letter_H", letter_H),                       # 20
            ("letter_I", letter_I),                       # 21
            ("letter_L", letter_L),                       # 22
            ("letter_U", letter_U),                       # 23
            ("letter_X", letter_X),                       # 24
            ("letter_Y", letter_Y),                       # 25
            ("letter_Z", letter_Z),                       # 26
            ("letter_S", letter_S),                       # 27
            ("letter_O", letter_O),                       # 28
            ("letter_C", letter_C),                       # 29
            # Category 5: Advanced Geometric (30-39)
            ("triangle_up", triangle_up),                 # 30
            ("triangle_down", triangle_down),             # 31
            ("hourglass", hourglass),                     # 32
            ("bowtie", bowtie),                           # 33
            ("stairs_ascending", stairs_ascending),       # 34
            ("stairs_descending", stairs_descending),     # 35
            ("pyramid", pyramid),                         # 36
            ("inverted_pyramid", inverted_pyramid),       # 37
            ("zigzag_horizontal", zigzag_horizontal),     # 38
            ("wave_pattern", wave_pattern),               # 39
            # Category 6: Frame/Border (40-44)
            ("frame_border", frame_border),               # 40
            ("double_frame", double_frame),               # 41
            ("corner_triangles", corner_triangles),       # 42
            ("center_hollow", center_hollow),             # 43
            ("window_panes", window_panes),               # 44
            # Category 7: Artistic (45-49)
            ("butterfly", butterfly),                     # 45
            ("flower_pattern", flower_pattern),           # 46
            ("scattered_islands", scattered_islands),     # 47
            ("diagonal_stripes", diagonal_stripes),       # 48
            ("honeycomb", honeycomb),                     # 49
            # Category 8: Bridge/Island Patterns (50-55) - Tile Explorer inspired
            ("bridge_horizontal", bridge_horizontal),     # 50
            ("bridge_vertical", bridge_vertical),         # 51
            ("three_islands_triangle", three_islands_triangle),  # 52
            ("four_islands_grid", four_islands_grid),     # 53
            ("archipelago", archipelago),                 # 54
            ("hub_and_spokes", hub_and_spokes),           # 55
            # Category 9: GBoost Human-Designed Patterns (56-63)
            # Derived from analysis of 221 human-designed production levels
            ("gboost_corner_blocks", gboost_corner_blocks),     # 56
            ("gboost_octagon_ring", gboost_octagon_ring),       # 57
            ("gboost_diagonal_staircase", gboost_diagonal_staircase),  # 58
            ("gboost_symmetric_wings", gboost_symmetric_wings), # 59
            ("gboost_scattered_clusters", gboost_scattered_clusters),  # 60
            ("gboost_cross_bridge", gboost_cross_bridge),       # 61
            ("gboost_triple_bar", gboost_triple_bar),           # 62
            ("gboost_frame_center", gboost_frame_center),       # 63
        ]

        TOTAL_PATTERNS = 64

        # If pattern_index is specified, use that specific pattern
        if pattern_index is not None and 0 <= pattern_index < TOTAL_PATTERNS:
            pattern_name, pattern_fn = all_patterns[pattern_index]
            best_positions = pattern_fn()
            if not best_positions:
                # Fallback to filled rectangle if chosen pattern returns nothing
                best_positions = filled_rectangle()
        else:
            # Auto-select: Score all patterns and pick best match for target_count
            pattern_results = []
            for pattern_name, pattern_fn in all_patterns:
                try:
                    positions = pattern_fn()
                    if positions:
                        # Score based on how close to target count
                        score = -abs(len(positions) - target_count)
                        # Penalize if too few positions
                        if len(positions) < target_count * 0.7:
                            score -= 1000
                        # Bonus for visually interesting patterns
                        if pattern_name in ["star_five_point", "heart_shape", "butterfly", "flower_pattern"]:
                            score += 5
                        pattern_results.append((score, positions, pattern_name))
                except Exception:
                    continue

            if not pattern_results:
                return filled_rectangle()[:target_count]

            # Sort by score and pick from top candidates with randomness
            pattern_results.sort(key=lambda x: x[0], reverse=True)

            # Pick from top 5-8 candidates randomly for variety
            # Filter to only include patterns within reasonable score range
            top_score = pattern_results[0][0]
            viable_candidates = [p for p in pattern_results if p[0] >= top_score - 15]
            num_candidates = min(len(viable_candidates), random.randint(5, 8))
            top_candidates = viable_candidates[:num_candidates]

            # Weighted random selection - higher scores more likely but not guaranteed
            weights = [max(1, p[0] - top_score + 20) for p in top_candidates]
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]

            selected_idx = random.choices(range(len(top_candidates)), weights=weights, k=1)[0]
            _, best_positions, selected_pattern = top_candidates[selected_idx]

        # If we have too many positions, trim from edges (maintain symmetry)
        if len(best_positions) > target_count:
            def dist_from_center(pos: str) -> float:
                x, y = map(int, pos.split("_"))
                return ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
            best_positions.sort(key=dist_from_center)
            best_positions = best_positions[:target_count]

        return best_positions

    def _generate_random_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate random positions with optional symmetry."""
        if symmetry == "none":
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            return random.sample(all_positions, min(target_count, len(all_positions)))

        return self._apply_symmetry(cols, rows, target_count, symmetry, "random")

    def _generate_geometric_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate geometric pattern positions with proper symmetry support."""
        # For symmetry modes, generate in base region first, then mirror
        if symmetry == "horizontal":
            # Generate in left half, mirror to right
            base_cols = (cols + 1) // 2
            base_count = (target_count + 1) // 2
            # For symmetry, don't sample - use all positions from pattern
            base_positions = self._generate_base_geometric_for_symmetry(base_cols, rows, base_count)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            # Generate in top half, mirror to bottom
            base_rows = (rows + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_geometric_for_symmetry(cols, base_rows, base_count)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            # Generate in top-left quadrant, mirror to all 4 quadrants
            base_cols = (cols + 1) // 2
            base_rows = (rows + 1) // 2
            base_count = (target_count + 3) // 4
            base_positions = self._generate_base_geometric_for_symmetry(base_cols, base_rows, base_count)
            return self._mirror_both(cols, rows, base_positions, target_count)

        else:
            # No symmetry - generate full grid patterns with sampling
            return self._generate_base_geometric(cols, rows, target_count, 0, 0)

    def _generate_base_geometric_for_symmetry(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate geometric pattern for symmetry - returns deterministic positions."""
        center_x, center_y = cols // 2, rows // 2

        # Pattern 1: Filled rectangle from center
        rect_positions = []
        rect_size = int((target_count ** 0.5) * 1.2)
        rect_half = rect_size // 2
        for x in range(max(0, center_x - rect_half), min(cols, center_x + rect_half + 1)):
            for y in range(max(0, center_y - rect_half), min(rows, center_y + rect_half + 1)):
                rect_positions.append(f"{x}_{y}")

        # Pattern 2: Diamond shape
        diamond_positions = []
        radius = int((target_count / 2) ** 0.5) + 1
        for x in range(cols):
            for y in range(rows):
                dist = abs(x - center_x) + abs(y - center_y)
                if dist <= radius:
                    diamond_positions.append(f"{x}_{y}")

        # Pattern 3: Fill all (for maximum coverage)
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Choose the best fitting pattern - return ALL positions from chosen pattern
        # No sampling to preserve symmetry!
        all_patterns = [rect_positions, diamond_positions, all_positions]

        # Find pattern closest to target count
        chosen = min(all_patterns, key=lambda p: abs(len(p) - target_count))

        # If chosen pattern is too big and we need fewer positions,
        # use a deterministic subset (from center outward)
        if len(chosen) > target_count * 1.5:
            # Sort by distance from center and take closest positions
            def dist_from_center(pos: str) -> float:
                x, y = map(int, pos.split("_"))
                return abs(x - center_x) + abs(y - center_y)
            chosen = sorted(chosen, key=dist_from_center)[:target_count]

        return chosen

    def _generate_base_geometric(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate geometric pattern in a base region with diverse shapes."""
        # Random offset to avoid always-centered shapes
        offset_range_x = max(1, cols // 4)
        offset_range_y = max(1, rows // 4)
        rand_offset_x = random.randint(-offset_range_x, offset_range_x)
        rand_offset_y = random.randint(-offset_range_y, offset_range_y)
        center_x = cols // 2 + rand_offset_x
        center_y = rows // 2 + rand_offset_y

        # Clamp center to valid range
        center_x = max(1, min(cols - 2, center_x))
        center_y = max(1, min(rows - 2, center_y))

        all_patterns = []

        # Pattern 1: Filled rectangle (traditional)
        rect_positions = []
        rect_size = int((target_count ** 0.5) * 1.2)
        rect_half = rect_size // 2
        for x in range(max(0, center_x - rect_half), min(cols, center_x + rect_half + 1)):
            for y in range(max(0, center_y - rect_half), min(rows, center_y + rect_half + 1)):
                rect_positions.append(f"{x + offset_x}_{y + offset_y}")
        if rect_positions:
            all_patterns.append(rect_positions)

        # Pattern 2: Diamond shape
        diamond_positions = []
        radius = int((target_count / 2) ** 0.5) + 1
        for x in range(cols):
            for y in range(rows):
                dist = abs(x - center_x) + abs(y - center_y)
                if dist <= radius:
                    diamond_positions.append(f"{x + offset_x}_{y + offset_y}")
        if diamond_positions:
            all_patterns.append(diamond_positions)

        # Pattern 3: L-shape (multiple rotations)
        l_rotation = random.randint(0, 3)
        l_positions = self._generate_l_shape(cols, rows, target_count, l_rotation, offset_x, offset_y)
        if l_positions:
            all_patterns.append(l_positions)

        # Pattern 4: T-shape (multiple rotations)
        t_rotation = random.randint(0, 3)
        t_positions = self._generate_t_shape(cols, rows, target_count, t_rotation, offset_x, offset_y)
        if t_positions:
            all_patterns.append(t_positions)

        # Pattern 5: Cross/Plus shape
        cross_positions = self._generate_cross_shape(cols, rows, target_count, center_x, center_y, offset_x, offset_y)
        if cross_positions:
            all_patterns.append(cross_positions)

        # Pattern 6: Donut/Ring shape
        donut_positions = self._generate_donut_shape(cols, rows, target_count, center_x, center_y, offset_x, offset_y)
        if donut_positions:
            all_patterns.append(donut_positions)

        # Pattern 7: Zigzag pattern
        zigzag_positions = self._generate_zigzag_shape(cols, rows, target_count, offset_x, offset_y)
        if zigzag_positions:
            all_patterns.append(zigzag_positions)

        # Pattern 8: Diagonal stripe
        diagonal_positions = self._generate_diagonal_shape(cols, rows, target_count, offset_x, offset_y)
        if diagonal_positions:
            all_patterns.append(diagonal_positions)

        # Pattern 9: Corner cluster (L positioned at corner)
        corner_cluster = self._generate_corner_cluster(cols, rows, target_count, offset_x, offset_y)
        if corner_cluster:
            all_patterns.append(corner_cluster)

        # Pattern 10: Scattered clusters
        scattered_positions = self._generate_scattered_clusters(cols, rows, target_count, offset_x, offset_y)
        if scattered_positions:
            all_patterns.append(scattered_positions)

        # Pattern 11: Horizontal bar
        h_bar_positions = self._generate_horizontal_bar(cols, rows, target_count, center_y, offset_x, offset_y)
        if h_bar_positions:
            all_patterns.append(h_bar_positions)

        # Pattern 12: Vertical bar
        v_bar_positions = self._generate_vertical_bar(cols, rows, target_count, center_x, offset_x, offset_y)
        if v_bar_positions:
            all_patterns.append(v_bar_positions)

        # Randomly select from all valid patterns (not just closest to target)
        valid_patterns = [p for p in all_patterns if len(p) >= target_count * 0.7]

        if valid_patterns:
            # Randomly choose a pattern for variety
            chosen = random.choice(valid_patterns)
            selected = random.sample(chosen, min(target_count, len(chosen)))
        else:
            # Fallback: use all positions and sample
            all_positions = [f"{x + offset_x}_{y + offset_y}" for x in range(cols) for y in range(rows)]
            selected = random.sample(all_positions, min(target_count, len(all_positions)))

        # Apply random position perturbation for additional diversity
        # This shifts the entire pattern by a random offset
        shift_x = random.randint(-2, 2)
        shift_y = random.randint(-2, 2)
        shifted = []
        for pos in selected:
            x, y = map(int, pos.split("_"))
            new_x = max(0, min(cols - 1, x + shift_x))
            new_y = max(0, min(rows - 1, y + shift_y))
            shifted.append(f"{new_x}_{new_y}")

        # Remove duplicates that may have been created by shifting
        shifted = list(set(shifted))

        # If we lost too many tiles due to deduplication, add random positions
        if len(shifted) < target_count:
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            available = [p for p in all_positions if p not in shifted]
            if available:
                extra = random.sample(available, min(target_count - len(shifted), len(available)))
                shifted.extend(extra)

        return shifted[:target_count]

    def _generate_l_shape(
        self, cols: int, rows: int, target_count: int, rotation: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate L-shaped pattern with rotation."""
        positions = []
        size = int((target_count / 2) ** 0.5) + 2
        thickness = max(2, size // 2)

        # Base L shape (rotation 0: vertical bar on left, horizontal bar on bottom)
        for x in range(cols):
            for y in range(rows):
                in_vertical = (x < thickness and y < size)
                in_horizontal = (y >= size - thickness and x < size)

                # Apply rotation
                if rotation == 0:
                    if in_vertical or in_horizontal:
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 1:  # 90 degrees
                    if (y < thickness and x < size) or (x >= size - thickness and y < size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 2:  # 180 degrees
                    if (x >= cols - thickness and y >= rows - size) or (y < thickness and x >= cols - size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 3:  # 270 degrees
                    if (y >= rows - thickness and x >= cols - size) or (x < thickness and y >= rows - size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_t_shape(
        self, cols: int, rows: int, target_count: int, rotation: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate T-shaped pattern with rotation."""
        positions = []
        center_x, center_y = cols // 2, rows // 2
        arm_length = int((target_count / 3) ** 0.5) + 1
        thickness = max(2, arm_length // 2)

        for x in range(cols):
            for y in range(rows):
                # T shape based on rotation
                if rotation == 0:  # T pointing down
                    in_horizontal = (abs(y - center_y) < thickness and x < cols)
                    in_vertical = (abs(x - center_x) < thickness and y >= center_y)
                elif rotation == 1:  # T pointing left
                    in_vertical = (abs(x - center_x) < thickness and y < rows)
                    in_horizontal = (abs(y - center_y) < thickness and x <= center_x)
                elif rotation == 2:  # T pointing up
                    in_horizontal = (abs(y - center_y) < thickness and x < cols)
                    in_vertical = (abs(x - center_x) < thickness and y <= center_y)
                else:  # T pointing right
                    in_vertical = (abs(x - center_x) < thickness and y < rows)
                    in_horizontal = (abs(y - center_y) < thickness and x >= center_x)

                if in_horizontal or in_vertical:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_cross_shape(
        self, cols: int, rows: int, target_count: int, center_x: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate cross/plus shaped pattern."""
        positions = []
        arm_length = int((target_count / 4) ** 0.5) + 1
        thickness = max(1, arm_length // 2)

        for x in range(cols):
            for y in range(rows):
                # Horizontal arm
                in_horizontal = (abs(y - center_y) < thickness and abs(x - center_x) <= arm_length)
                # Vertical arm
                in_vertical = (abs(x - center_x) < thickness and abs(y - center_y) <= arm_length)

                if in_horizontal or in_vertical:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_donut_shape(
        self, cols: int, rows: int, target_count: int, center_x: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate donut/ring shaped pattern with hollow center."""
        positions = []
        outer_radius = int((target_count / 2.5) ** 0.5) + 2
        inner_radius = max(1, outer_radius // 2)

        for x in range(cols):
            for y in range(rows):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                if inner_radius <= dist <= outer_radius:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_zigzag_shape(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate zigzag pattern."""
        positions = []
        amplitude = max(1, rows // 4)
        thickness = max(2, int((target_count / rows) ** 0.5))

        for x in range(cols):
            # Zigzag center line
            zigzag_y = rows // 2 + int(amplitude * (1 if (x // 2) % 2 == 0 else -1))
            for y in range(rows):
                if abs(y - zigzag_y) < thickness:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_diagonal_shape(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate diagonal stripe pattern."""
        positions = []
        thickness = max(2, int((target_count / max(cols, rows)) ** 0.5) + 1)
        direction = random.choice([1, -1])  # 1 = top-left to bottom-right, -1 = top-right to bottom-left

        for x in range(cols):
            for y in range(rows):
                # Diagonal line: y = x (or y = -x) with some offset
                if direction == 1:
                    diag_dist = abs(y - x)
                else:
                    diag_dist = abs(y - (cols - 1 - x))

                if diag_dist < thickness:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_corner_cluster(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate cluster positioned at a random corner."""
        positions = []
        corner = random.randint(0, 3)
        cluster_size = int((target_count ** 0.5)) + 1

        # Determine corner position
        if corner == 0:  # Top-left
            start_x, start_y = 0, 0
        elif corner == 1:  # Top-right
            start_x, start_y = max(0, cols - cluster_size), 0
        elif corner == 2:  # Bottom-left
            start_x, start_y = 0, max(0, rows - cluster_size)
        else:  # Bottom-right
            start_x, start_y = max(0, cols - cluster_size), max(0, rows - cluster_size)

        for x in range(start_x, min(cols, start_x + cluster_size)):
            for y in range(start_y, min(rows, start_y + cluster_size)):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_scattered_clusters(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate multiple small scattered clusters."""
        positions = set()
        num_clusters = random.randint(3, 5)
        tiles_per_cluster = target_count // num_clusters
        cluster_radius = max(1, int((tiles_per_cluster / 3.14) ** 0.5))

        for _ in range(num_clusters):
            # Random cluster center
            cx = random.randint(cluster_radius, cols - cluster_radius - 1)
            cy = random.randint(cluster_radius, rows - cluster_radius - 1)

            for x in range(cols):
                for y in range(rows):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= cluster_radius:
                        positions.add(f"{x + offset_x}_{y + offset_y}")

        return list(positions)

    def _generate_horizontal_bar(
        self, cols: int, rows: int, target_count: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate horizontal bar pattern."""
        positions = []
        bar_height = max(2, target_count // cols + 1)

        for x in range(cols):
            for y in range(max(0, center_y - bar_height // 2), min(rows, center_y + bar_height // 2 + 1)):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_vertical_bar(
        self, cols: int, rows: int, target_count: int, center_x: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate vertical bar pattern."""
        positions = []
        bar_width = max(2, target_count // rows + 1)

        for x in range(max(0, center_x - bar_width // 2), min(cols, center_x + bar_width // 2 + 1)):
            for y in range(rows):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _mirror_horizontal(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions horizontally (left to right).

        Note: Returns all mirrored positions to preserve symmetry.
        The target_count is used only to limit base position generation.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            result.add(f"{x}_{y}")
            mirror_x = cols - 1 - x
            if 0 <= mirror_x < cols:
                result.add(f"{mirror_x}_{y}")
        # Return all positions to preserve symmetry - don't slice!
        return list(result)

    def _mirror_vertical(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions vertically (top to bottom).

        Note: Returns all mirrored positions to preserve symmetry.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            result.add(f"{x}_{y}")
            mirror_y = rows - 1 - y
            if 0 <= mirror_y < rows:
                result.add(f"{x}_{mirror_y}")
        return list(result)

    def _mirror_both(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions in all 4 directions.

        Note: Returns all mirrored positions to preserve symmetry.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            mirror_x = cols - 1 - x
            mirror_y = rows - 1 - y
            # Add all 4 quadrants
            result.add(f"{x}_{y}")
            if 0 <= mirror_x < cols:
                result.add(f"{mirror_x}_{y}")
            if 0 <= mirror_y < rows:
                result.add(f"{x}_{mirror_y}")
            if 0 <= mirror_x < cols and 0 <= mirror_y < rows:
                result.add(f"{mirror_x}_{mirror_y}")
        return list(result)

    def _apply_symmetry_to_positions(
        self, cols: int, rows: int, positions: List[str], symmetry: str, target_count: int
    ) -> List[str]:
        """Apply symmetry transformation to a set of positions.

        Takes existing positions and enforces the specified symmetry by:
        1. Keeping positions in one half of the grid
        2. Mirroring them to create perfect symmetry
        """
        if symmetry == "horizontal":
            # Keep only left half, then mirror to right
            center_x = cols / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                if x < center_x or (cols % 2 == 1 and x == cols // 2):
                    base_positions.append(pos)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            # Keep only top half, then mirror to bottom
            center_y = rows / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                if y < center_y or (rows % 2 == 1 and y == rows // 2):
                    base_positions.append(pos)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            # Keep only top-left quadrant, then mirror to all 4
            center_x = cols / 2.0
            center_y = rows / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                in_x = x < center_x or (cols % 2 == 1 and x == cols // 2)
                in_y = y < center_y or (rows % 2 == 1 and y == rows // 2)
                if in_x and in_y:
                    base_positions.append(pos)
            return self._mirror_both(cols, rows, base_positions, target_count)

        # No symmetry - return as-is
        return positions

    def _generate_clustered_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate clustered positions with proper symmetry support."""
        # For symmetry modes, generate in base region first, then mirror
        if symmetry == "horizontal":
            base_cols = (cols + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_clustered_for_symmetry(base_cols, rows, base_count)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            base_rows = (rows + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_clustered_for_symmetry(cols, base_rows, base_count)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            base_cols = (cols + 1) // 2
            base_rows = (rows + 1) // 2
            base_count = (target_count + 3) // 4
            base_positions = self._generate_base_clustered_for_symmetry(base_cols, base_rows, base_count)
            return self._mirror_both(cols, rows, base_positions, target_count)

        else:
            return self._generate_base_clustered(cols, rows, target_count)

    def _generate_base_clustered_for_symmetry(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate clustered positions for symmetry - deterministic, no random sampling."""
        # Use center of base region as cluster center
        center_x, center_y = cols // 2, rows // 2

        # Generate all positions within cluster radius
        cluster_radius = int((target_count / 3.14) ** 0.5) + 1
        positions = []

        for x in range(cols):
            for y in range(rows):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                if dist <= cluster_radius:
                    positions.append((dist, f"{x}_{y}"))

        # Sort by distance and take closest positions (deterministic)
        positions.sort(key=lambda p: p[0])
        result = [pos for _, pos in positions]

        # If we have too many, take the closest to center
        if len(result) > target_count * 1.5:
            result = result[:target_count]

        return result

    def _generate_base_clustered(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate clustered positions in a base region (with randomness for non-symmetric)."""
        positions = set()

        # Create 1-3 cluster centers
        num_clusters = random.randint(1, min(3, max(1, target_count // 6)))
        tiles_per_cluster = target_count // max(1, num_clusters)

        # Generate cluster centers (avoid edges)
        margin = max(1, min(cols, rows) // 4)
        cluster_centers = []

        for _ in range(num_clusters):
            cx = random.randint(margin, max(margin, cols - margin - 1)) if cols > 2 * margin else cols // 2
            cy = random.randint(margin, max(margin, rows - margin - 1)) if rows > 2 * margin else rows // 2
            cluster_centers.append((cx, cy))

        # Generate positions around each cluster center
        for cx, cy in cluster_centers:
            cluster_radius = int((tiles_per_cluster / 3.14) ** 0.5) + 1
            cluster_positions = []

            for x in range(max(0, cx - cluster_radius), min(cols, cx + cluster_radius + 1)):
                for y in range(max(0, cy - cluster_radius), min(rows, cy + cluster_radius + 1)):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= cluster_radius:
                        cluster_positions.append(f"{x}_{y}")

            sample_count = min(tiles_per_cluster, len(cluster_positions))
            if sample_count > 0:
                sampled = random.sample(cluster_positions, sample_count)
                positions.update(sampled)

        # Fill remaining if needed - O(n) using random.sample instead of O(n²) loop
        if len(positions) < target_count:
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            remaining = [p for p in all_positions if p not in positions]
            need_count = min(target_count - len(positions), len(remaining))
            if need_count > 0:
                positions.update(random.sample(remaining, need_count))

        return list(positions)[:target_count]

    def _apply_symmetry(
        self, cols: int, rows: int, target_count: int, symmetry: str, pattern: str
    ) -> List[str]:
        """Apply symmetry by generating half and mirroring."""
        if symmetry == "horizontal":
            # Left-right symmetry: generate left half, mirror to right
            half_cols = (cols + 1) // 2
            half_count = (target_count + 1) // 2

            # Generate positions in left half
            left_positions = [f"{x}_{y}" for x in range(half_cols) for y in range(rows)]
            selected_left = random.sample(left_positions, min(half_count, len(left_positions)))

            # Mirror to right
            result = set()
            for pos in selected_left:
                x, y = map(int, pos.split("_"))
                result.add(pos)
                mirror_x = cols - 1 - x
                if mirror_x >= 0 and mirror_x < cols:
                    result.add(f"{mirror_x}_{y}")

            return list(result)[:target_count]

        elif symmetry == "vertical":
            # Top-bottom symmetry: generate top half, mirror to bottom
            half_rows = (rows + 1) // 2
            half_count = (target_count + 1) // 2

            top_positions = [f"{x}_{y}" for x in range(cols) for y in range(half_rows)]
            selected_top = random.sample(top_positions, min(half_count, len(top_positions)))

            result = set()
            for pos in selected_top:
                x, y = map(int, pos.split("_"))
                result.add(pos)
                mirror_y = rows - 1 - y
                if mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{x}_{mirror_y}")

            return list(result)[:target_count]

        elif symmetry == "both":
            # 4-way symmetry: generate top-left quadrant, mirror to all
            half_cols = (cols + 1) // 2
            half_rows = (rows + 1) // 2
            quarter_count = (target_count + 3) // 4

            quadrant_positions = [f"{x}_{y}" for x in range(half_cols) for y in range(half_rows)]
            selected_quadrant = random.sample(quadrant_positions, min(quarter_count, len(quadrant_positions)))

            result = set()
            for pos in selected_quadrant:
                x, y = map(int, pos.split("_"))
                # Add all 4 symmetric positions
                result.add(f"{x}_{y}")
                mirror_x = cols - 1 - x
                mirror_y = rows - 1 - y
                if mirror_x >= 0 and mirror_x < cols:
                    result.add(f"{mirror_x}_{y}")
                if mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{x}_{mirror_y}")
                if mirror_x >= 0 and mirror_x < cols and mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{mirror_x}_{mirror_y}")

            return list(result)[:target_count]

        # Default: no symmetry
        all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
        return random.sample(all_positions, min(target_count, len(all_positions)))

    def _is_position_covered_by_upper(
        self, level: Dict[str, Any], layer_idx: int, col: int, row: int
    ) -> bool:
        """Check if a position is covered by tiles in upper layers.

        Based on sp_template TileGroup.FindAllUpperTiles logic:
        - Same parity (layer 0→2, 1→3): Check same position only
        - Different parity: Compare layer col sizes to determine offset direction
          - Upper layer col > current layer col: Check (0,0), (+1,0), (0,+1), (+1,+1)
          - Upper layer col <= current layer col: Check (-1,-1), (0,-1), (-1,0), (0,0)

        Parity is determined by layer_idx % 2.
        """
        num_layers = level.get("layer", 8)

        # Early exit if on top layer
        if layer_idx >= num_layers - 1:
            return False

        tile_parity = layer_idx % 2
        cur_layer_data = level.get(f"layer_{layer_idx}", {})
        cur_layer_col = int(cur_layer_data.get("col", 7))

        # Blocking offsets based on parity
        BLOCKING_OFFSETS_SAME_PARITY = ((0, 0),)
        BLOCKING_OFFSETS_UPPER_BIGGER = ((0, 0), (1, 0), (0, 1), (1, 1))
        BLOCKING_OFFSETS_UPPER_SMALLER = ((-1, -1), (0, -1), (-1, 0), (0, 0))

        for upper_layer_idx in range(layer_idx + 1, num_layers):
            upper_layer_key = f"layer_{upper_layer_idx}"
            upper_layer_data = level.get(upper_layer_key, {})
            upper_tiles = upper_layer_data.get("tiles", {})

            if not upper_tiles:
                continue

            upper_parity = upper_layer_idx % 2
            upper_layer_col = int(upper_layer_data.get("col", 7))

            # Determine blocking positions based on parity and layer size
            if tile_parity == upper_parity:
                # Same parity (odd-odd or even-even): only check same position
                blocking_offsets = BLOCKING_OFFSETS_SAME_PARITY
            else:
                # Different parity: compare layer col sizes
                if upper_layer_col > cur_layer_col:
                    # Upper layer is bigger (has more columns)
                    blocking_offsets = BLOCKING_OFFSETS_UPPER_BIGGER
                else:
                    # Upper layer is smaller or same size
                    blocking_offsets = BLOCKING_OFFSETS_UPPER_SMALLER

            for dx, dy in blocking_offsets:
                bx = col + dx
                by = row + dy
                pos_key = f"{bx}_{by}"
                if pos_key in upper_tiles:
                    return True

        return False

    def _add_tutorial_gimmick(
        self, level: Dict[str, Any], gimmick_type: str, min_count: int = 2
    ) -> Dict[str, Any]:
        """
        Add tutorial gimmick to the top layers for tutorial UI display.

        Tutorial gimmicks are placed on the topmost layers with tiles to make them
        immediately visible when the level starts, facilitating tutorial UI overlay.
        If the top layer doesn't have enough eligible positions, lower layers are tried.

        Args:
            level: Level data to modify
            gimmick_type: Type of gimmick to add (e.g., 'chain', 'ice', 'frog')
            min_count: Minimum number of gimmicks to place (default: 2)

        Returns:
            Modified level with tutorial gimmicks placed on top layers
        """
        num_layers = level.get("layer", 8)

        # Find all layers with tiles, sorted from top to bottom
        layers_with_tiles = []
        for i in range(num_layers - 1, -1, -1):  # num_layers-1 → ... → 0 (highest first)
            layer_key = f"layer_{i}"
            layer_tiles = level.get(layer_key, {}).get("tiles", {})
            if layer_tiles:
                layers_with_tiles.append(i)

        if not layers_with_tiles:
            return level  # No tiles found

        top_layer_idx = layers_with_tiles[0]
        layer_key = f"layer_{top_layer_idx}"
        layer_data = level.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        # Find eligible tiles (normal tiles without existing gimmicks)
        eligible_positions = []
        for pos, tile_data in tiles.items():
            if not isinstance(tile_data, list) or len(tile_data) == 0:
                continue
            tile_type = tile_data[0]
            # Skip goal tiles (craft_*, stack_*)
            if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                continue
            # Skip tiles with existing gimmicks
            gimmick = tile_data[1] if len(tile_data) > 1 else ""
            if gimmick:
                continue
            eligible_positions.append(pos)

        if not eligible_positions:
            return level  # No eligible positions

        # Map gimmick types to their attribute format
        GIMMICK_ATTRIBUTES = {
            "chain": "chain",
            "ice": "ice",
            "frog": "frog",
            "grass": "grass",
            "bomb": "bomb",
            "curtain": "curtain",
            "unknown": "unknown",
            "link": "link_e",  # Default to east direction for link
            "teleport": "teleport",
        }

        # craft/stack are tile types, not attributes - skip tutorial gimmick placement
        if gimmick_type in ("craft", "stack"):
            logger.info(f"Tutorial gimmick '{gimmick_type}' is a goal tile type, not an attribute - skipping")
            return level

        # unknown gimmick requires tiles to be COVERED by upper layers to work
        # Placing on top layer would make them visible (no curtain effect)
        # Unknown tutorial is handled by boosting unknown ratio in _add_obstacles instead
        if gimmick_type == "unknown":
            logger.info(f"Tutorial gimmick 'unknown' requires covered tiles - will boost ratio in _add_obstacles instead")
            return level

        # SPECIAL HANDLING: Grass needs 2+ clearable neighbors
        if gimmick_type == "grass":
            grass_eligible = []
            for pos in eligible_positions:
                try:
                    col, row = map(int, pos.split('_'))
                except:
                    continue
                # Check 4 directions for clearable neighbors
                neighbors = [(col, row-1), (col, row+1), (col-1, row), (col+1, row)]
                clearable_count = 0
                for ncol, nrow in neighbors:
                    npos = f"{ncol}_{nrow}"
                    if npos in tiles:
                        ndata = tiles[npos]
                        if (isinstance(ndata, list) and len(ndata) >= 1 and
                            not (isinstance(ndata[0], str) and (ndata[0].startswith("craft_") or ndata[0].startswith("stack_")))):
                            clearable_count += 1
                if clearable_count >= 2:
                    grass_eligible.append(pos)

            if not grass_eligible:
                logger.warning(f"Tutorial gimmick 'grass' - no positions with 2+ clearable neighbors found")
                # Fallback: use any eligible position
                grass_eligible = eligible_positions

            eligible_positions = grass_eligible
            logger.info(f"Tutorial gimmick 'grass' - {len(eligible_positions)} positions with valid neighbors")

        # SPECIAL HANDLING: Link needs pairs with matching directions
        if gimmick_type == "link":
            placed_count = 0
            target_count = min_count  # Need at least min_count link tiles (2 tiles per pair)

            # Try each layer from top to bottom
            for current_layer_idx in layers_with_tiles:
                if placed_count >= target_count:
                    break

                current_layer_key = f"layer_{current_layer_idx}"
                current_tiles = level.get(current_layer_key, {}).get("tiles", {})

                # Find eligible positions on this layer
                layer_eligible = []
                for pos, tile_data in current_tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) == 0:
                        continue
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        continue
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""
                    if gimmick:
                        continue
                    layer_eligible.append(pos)

                # Find horizontal and vertical pairs
                link_pairs = []
                used_positions = set()

                for pos in layer_eligible:
                    if pos in used_positions:
                        continue
                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Check for horizontal pair (east-west)
                    east_pos = f"{col+1}_{row}"
                    if east_pos in layer_eligible and east_pos not in used_positions:
                        link_pairs.append((pos, east_pos, "link_e", "link_w", current_tiles))
                        used_positions.add(pos)
                        used_positions.add(east_pos)
                        continue

                    # Check for vertical pair (north-south)
                    south_pos = f"{col}_{row+1}"
                    if south_pos in layer_eligible and south_pos not in used_positions:
                        link_pairs.append((pos, south_pos, "link_n", "link_s", current_tiles))
                        used_positions.add(pos)
                        used_positions.add(south_pos)

                # Place link pairs on this layer
                random.shuffle(link_pairs)
                for pos1, pos2, attr1, attr2, layer_tiles in link_pairs:
                    if placed_count >= target_count:
                        break

                    tile1 = layer_tiles[pos1]
                    tile2 = layer_tiles[pos2]

                    if len(tile1) == 1:
                        tile1.append(attr1)
                    else:
                        tile1[1] = attr1

                    if len(tile2) == 1:
                        tile2.append(attr2)
                    else:
                        tile2[1] = attr2

                    placed_count += 2
                    logger.debug(f"Tutorial gimmick 'link' pair placed at layer {current_layer_idx}: {pos1}({attr1}), {pos2}({attr2})")

            logger.info(f"Tutorial gimmick 'link' placed: {placed_count} tiles total")
            return level

        # Place gimmicks on top layer (for non-special gimmicks)
        gimmick_attr = GIMMICK_ATTRIBUTES.get(gimmick_type, gimmick_type)
        placed_count = 0

        # Try to place on top layer first
        positions_to_use = min(min_count, len(eligible_positions))
        random.shuffle(eligible_positions)

        for pos in eligible_positions[:positions_to_use]:
            tile_data = tiles[pos]
            if len(tile_data) == 1:
                tile_data.append(gimmick_attr)
            else:
                tile_data[1] = gimmick_attr
            placed_count += 1
            logger.debug(f"Tutorial gimmick '{gimmick_attr}' placed at layer {top_layer_idx}, pos {pos}")

        # If we didn't place enough, try lower layers
        if placed_count < min_count and len(layers_with_tiles) > 1:
            for lower_layer_idx in layers_with_tiles[1:]:  # Skip top layer, try lower ones
                if placed_count >= min_count:
                    break

                lower_layer_key = f"layer_{lower_layer_idx}"
                lower_tiles = level.get(lower_layer_key, {}).get("tiles", {})

                # Find eligible positions on this layer
                lower_eligible = []
                for pos, tile_data in lower_tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) == 0:
                        continue
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        continue
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""
                    if gimmick:
                        continue

                    # For grass, check neighbors on this layer
                    if gimmick_type == "grass":
                        try:
                            col, row = map(int, pos.split('_'))
                        except:
                            continue
                        neighbors = [(col, row-1), (col, row+1), (col-1, row), (col+1, row)]
                        clearable_count = 0
                        for ncol, nrow in neighbors:
                            npos = f"{ncol}_{nrow}"
                            if npos in lower_tiles:
                                ndata = lower_tiles[npos]
                                if isinstance(ndata, list) and len(ndata) >= 1:
                                    clearable_count += 1
                        if clearable_count < 2:
                            continue

                    lower_eligible.append(pos)

                if lower_eligible:
                    random.shuffle(lower_eligible)
                    for pos in lower_eligible:
                        if placed_count >= min_count:
                            break
                        tile_data = lower_tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append(gimmick_attr)
                        else:
                            tile_data[1] = gimmick_attr
                        placed_count += 1
                        logger.debug(f"Tutorial gimmick '{gimmick_attr}' placed at layer {lower_layer_idx}, pos {pos} (fallback)")

        logger.info(f"Tutorial gimmick '{gimmick_type}' placed: {placed_count} tiles (top layer: {top_layer_idx})")

        return level

    def _ensure_tutorial_gimmick_count(
        self, level: Dict[str, Any], gimmick_type: str, min_count: int
    ) -> Dict[str, Any]:
        """
        Ensure the tutorial gimmick has at least min_count instances after all validations.

        This is called at the END of generation after all obstacle validations, which may have
        removed some gimmicks. If count is below minimum, adds more in valid positions.

        Args:
            level: Level data
            gimmick_type: Type of gimmick to ensure (e.g., 'chain', 'ice', 'frog')
            min_count: Minimum number of gimmicks required

        Returns:
            Modified level with tutorial gimmicks ensured
        """
        # craft/stack are goal tile types, not attributes - skip
        if gimmick_type in ("craft", "stack"):
            logger.info(f"Tutorial gimmick '{gimmick_type}' is a goal tile type, not an attribute - skipping ensure count")
            return level

        num_layers = level.get("layer", 8)

        # Map gimmick types to their attribute format
        GIMMICK_ATTRIBUTES = {
            "chain": "chain",
            "ice": "ice",
            "frog": "frog",
            "grass": "grass",
            "bomb": "bomb",
            "curtain": "curtain",
            "link": "link_e",
            "teleport": "teleport",
        }

        gimmick_attr = GIMMICK_ATTRIBUTES.get(gimmick_type, gimmick_type)

        # Count current gimmick instances
        current_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 1:
                    attr = tile_data[1]
                    # Handle variants (link_e, link_w, link_n, link_s)
                    if attr == gimmick_attr or (gimmick_type == "link" and attr and attr.startswith("link_")):
                        current_count += 1

        if current_count >= min_count:
            return level  # Already have enough

        needed = min_count - current_count
        logger.info(f"Tutorial gimmick '{gimmick_type}' needs {needed} more (current: {current_count}, min: {min_count})")

        # Find layers with tiles, sorted from top to bottom
        layers_with_tiles = []
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            layer_tiles = level.get(layer_key, {}).get("tiles", {})
            if layer_tiles:
                layers_with_tiles.append(i)

        if not layers_with_tiles:
            return level

        added = 0

        # For chain: need LEFT or RIGHT clearable neighbor
        if gimmick_type == "chain":
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                # Find eligible positions with valid neighbors
                candidates = []
                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    # Skip goal tiles
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    # Skip tiles with existing gimmicks
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    # Check for clearable left or right neighbor
                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    for ncol in [col - 1, col + 1]:
                        npos = f"{ncol}_{row}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if isinstance(ndata, list) and len(ndata) >= 2:
                                # Neighbor must be clearable (no obstacle or frog only)
                                if not ndata[1] or ndata[1] == "frog":
                                    candidates.append(pos)
                                    break

                if candidates:
                    random.shuffle(candidates)
                    for pos in candidates:
                        if added >= needed:
                            break
                        tile_data = tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append("chain")
                        else:
                            tile_data[1] = "chain"
                        added += 1
                        logger.debug(f"Tutorial gimmick 'chain' ensured at layer {layer_idx}, pos {pos}")

        # For link: need pairs
        elif gimmick_type == "link":
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                # Find eligible pairs
                used = set()
                pairs = []
                for pos, tile_data in tiles.items():
                    if pos in used:
                        continue
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Check east neighbor
                    east_pos = f"{col+1}_{row}"
                    if east_pos in tiles and east_pos not in used:
                        east_data = tiles[east_pos]
                        if isinstance(east_data, list) and len(east_data) >= 1:
                            if not (east_data[0] in self.GOAL_TYPES or east_data[0].startswith("craft_") or east_data[0].startswith("stack_")):
                                if len(east_data) < 2 or not east_data[1]:
                                    pairs.append((pos, east_pos, "link_e", "link_w"))
                                    used.add(pos)
                                    used.add(east_pos)
                                    continue

                    # Check south neighbor
                    south_pos = f"{col}_{row+1}"
                    if south_pos in tiles and south_pos not in used:
                        south_data = tiles[south_pos]
                        if isinstance(south_data, list) and len(south_data) >= 1:
                            if not (south_data[0] in self.GOAL_TYPES or south_data[0].startswith("craft_") or south_data[0].startswith("stack_")):
                                if len(south_data) < 2 or not south_data[1]:
                                    pairs.append((pos, south_pos, "link_n", "link_s"))
                                    used.add(pos)
                                    used.add(south_pos)

                for pos1, pos2, attr1, attr2 in pairs:
                    if added >= needed:
                        break
                    tile1 = tiles[pos1]
                    tile2 = tiles[pos2]
                    if len(tile1) == 1:
                        tile1.append(attr1)
                    else:
                        tile1[1] = attr1
                    if len(tile2) == 1:
                        tile2.append(attr2)
                    else:
                        tile2[1] = attr2
                    added += 2
                    logger.debug(f"Tutorial gimmick 'link' ensured at layer {layer_idx}: {pos1}, {pos2}")

        # For grass: need 2+ clearable neighbors
        elif gimmick_type == "grass":
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                candidates = []
                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Count clearable neighbors
                    neighbors = [(col-1, row), (col+1, row), (col, row-1), (col, row+1)]
                    clearable = 0
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if isinstance(ndata, list) and len(ndata) >= 1:
                                clearable += 1
                    if clearable >= 2:
                        candidates.append(pos)

                if candidates:
                    random.shuffle(candidates)
                    for pos in candidates:
                        if added >= needed:
                            break
                        tile_data = tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append("grass")
                        else:
                            tile_data[1] = "grass"
                        added += 1
                        logger.debug(f"Tutorial gimmick 'grass' ensured at layer {layer_idx}, pos {pos}")

        # For simple gimmicks (ice, frog, bomb, curtain, teleport): just add to any empty tile
        else:
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                candidates = []
                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue
                    candidates.append(pos)

                if candidates:
                    random.shuffle(candidates)
                    for pos in candidates:
                        if added >= needed:
                            break
                        tile_data = tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append(gimmick_attr)
                        else:
                            tile_data[1] = gimmick_attr
                        added += 1
                        logger.debug(f"Tutorial gimmick '{gimmick_attr}' ensured at layer {layer_idx}, pos {pos}")

        logger.info(f"Tutorial gimmick '{gimmick_type}' ensured: added {added}, total now {current_count + added}")
        return level

    def _ensure_unknown_tutorial_count(
        self, level: Dict[str, Any], min_count: int
    ) -> Dict[str, Any]:
        """
        Ensure the tutorial 'unknown' gimmick has at least min_count instances.

        Unknown gimmicks are special because they MUST be covered by upper layer tiles
        to show the curtain effect. This method:
        1. Counts current covered unknown gimmicks
        2. If below minimum, finds tiles that ARE covered and adds unknown to them
        3. If not enough covered positions, adds tiles to create coverage

        Args:
            level: Level data
            min_count: Minimum number of unknown gimmicks required

        Returns:
            Modified level with unknown tutorial gimmicks ensured
        """
        num_layers = level.get("layer", 8)

        # Count current unknown gimmicks that are properly covered
        current_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 1 and tile_data[1] == "unknown":
                    # Verify it's covered
                    try:
                        col, row = map(int, pos.split('_'))
                        if self._is_position_covered_by_upper(level, i, col, row):
                            current_count += 1
                    except:
                        pass

        if current_count >= min_count:
            return level  # Already have enough

        needed = min_count - current_count
        logger.info(f"Tutorial gimmick 'unknown' needs {needed} more (current covered: {current_count}, min: {min_count})")

        # Find tiles that ARE covered by upper layers but don't have a gimmick
        covered_candidates = []
        for i in range(num_layers - 1):  # Skip top layer (can't be covered)
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 1:
                    continue
                # Skip goal tiles
                if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                    continue
                # Skip tiles with existing gimmicks
                if len(tile_data) >= 2 and tile_data[1]:
                    continue
                # Check if covered
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, i, col, row):
                        covered_candidates.append((i, pos, tile_data))
                except:
                    continue

        # Add unknown to covered candidates
        added = 0
        random.shuffle(covered_candidates)
        for layer_idx, pos, tile_data in covered_candidates:
            if added >= needed:
                break
            if len(tile_data) == 1:
                tile_data.append("unknown")
            else:
                tile_data[1] = "unknown"
            added += 1
            logger.debug(f"Tutorial gimmick 'unknown' ensured at layer {layer_idx}, pos {pos}")

        # If still need more, we need to create coverage by adding tiles above existing tiles
        if added < needed:
            remaining = needed - added
            logger.info(f"Need {remaining} more unknown gimmicks - will create coverage")

            # Find tiles without gimmicks on lower layers (0, 1, 2) that could potentially be covered
            for target_layer in range(min(3, num_layers - 1)):  # Lower layers have more room for upper tiles
                if added >= needed:
                    break

                layer_key = f"layer_{target_layer}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                for pos, tile_data in list(tiles.items()):
                    if added >= needed:
                        break
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Check if already covered
                    if self._is_position_covered_by_upper(level, target_layer, col, row):
                        # Already covered - just add unknown
                        if len(tile_data) == 1:
                            tile_data.append("unknown")
                        else:
                            tile_data[1] = "unknown"
                        added += 1
                        logger.debug(f"Tutorial gimmick 'unknown' added to already-covered tile at layer {target_layer}, pos {pos}")
                        continue

                    # Not covered - try to add a tile above to create coverage
                    # Find the nearest upper layer that could cover this position
                    tile_added = False
                    for upper_layer in range(target_layer + 1, num_layers):
                        upper_layer_key = f"layer_{upper_layer}"
                        if upper_layer_key not in level:
                            continue

                        upper_tiles = level.get(upper_layer_key, {}).get("tiles", {})
                        upper_layer_data = level.get(upper_layer_key, {})

                        # Calculate the covering position based on parity
                        tile_parity = target_layer % 2
                        upper_parity = upper_layer % 2

                        if tile_parity == upper_parity:
                            # Same parity - same position covers
                            cover_pos = pos
                        else:
                            upper_col = int(upper_layer_data.get("col", 7))
                            current_col = int(level.get(layer_key, {}).get("col", 7))

                            if upper_col > current_col:
                                # Check if any of the 4 positions would cover - use (0,0) for simplicity
                                cover_pos = pos
                            else:
                                # Use offset position
                                cover_pos = pos

                        # Check if position is valid for this layer (within bounds)
                        try:
                            c, r = map(int, cover_pos.split('_'))
                            layer_col = int(upper_layer_data.get("col", 7))
                            layer_row = int(upper_layer_data.get("row", 7))
                            if c < 0 or r < 0 or c >= layer_col or r >= layer_row:
                                continue
                        except:
                            continue

                        # Add tile to upper layer if position is empty
                        if cover_pos not in upper_tiles:
                            # Get a tile type from existing tiles
                            tile_types = []
                            for td in tiles.values():
                                if isinstance(td, list) and len(td) >= 1 and td[0] not in self.GOAL_TYPES:
                                    if not td[0].startswith("craft_") and not td[0].startswith("stack_"):
                                        tile_types.append(td[0])
                            if tile_types:
                                new_tile_type = random.choice(tile_types)
                                self._place_tile(upper_tiles, cover_pos, new_tile_type, "")
                                level[upper_layer_key]["tiles"] = upper_tiles
                                # Update num count
                                level[upper_layer_key]["num"] = str(len(upper_tiles))

                                # Now add unknown to the target tile
                                if len(tile_data) == 1:
                                    tile_data.append("unknown")
                                else:
                                    tile_data[1] = "unknown"
                                added += 1
                                tile_added = True
                                logger.debug(f"Tutorial gimmick 'unknown' created by adding cover tile at layer {upper_layer}, pos {cover_pos}")
                                break

                    if not tile_added:
                        # Couldn't create coverage - skip this position
                        pass

        logger.info(f"Tutorial gimmick 'unknown' ensured: added {added}, total now {current_count + added}")
        return level

    def _add_obstacles(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add obstacles and attributes to tiles following game rules."""
        # Use None check to allow empty list (empty list means no obstacles)
        # Default: ALL obstacle types (filtering by unlock level should happen at API level)
        ALL_OBSTACLE_TYPES_DEFAULT = ["chain", "frog", "link", "grass", "ice", "bomb", "curtain", "teleport", "unknown"]
        obstacle_types = params.obstacle_types if params.obstacle_types is not None else ALL_OBSTACLE_TYPES_DEFAULT
        target = params.target_difficulty

        # Get gimmick intensity multiplier (0.0 = no gimmicks, 1.0 = normal, 2.0 = double)
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0)

        # If gimmick_intensity is 0, skip all obstacle generation (except tutorial gimmick)
        tutorial_gimmick = getattr(params, 'tutorial_gimmick', None)
        tutorial_gimmick_min_count = getattr(params, 'tutorial_gimmick_min_count', 2)

        # Handle tutorial gimmick first (always placed on top layer for tutorial UI)
        logger.info(f"[_add_obstacles] tutorial_gimmick={tutorial_gimmick}, min_count={tutorial_gimmick_min_count}")
        if tutorial_gimmick:
            logger.info(f"[_add_obstacles] Calling _add_tutorial_gimmick with gimmick_type={tutorial_gimmick}")
            level = self._add_tutorial_gimmick(level, tutorial_gimmick, tutorial_gimmick_min_count)

        if gimmick_intensity <= 0:
            return level

        # Calculate target obstacle counts based on difficulty
        num_layers = level.get("layer", 8)
        total_tiles = sum(
            len(level.get(f"layer_{i}", {}).get("tiles", {}))
            for i in range(num_layers)
        )

        # Check if per-layer obstacle configs are provided (they take priority)
        has_layer_obstacle_configs = bool(params.layer_obstacle_configs)

        # Helper to get target count for an obstacle type (global)
        # Only used when per-layer configs are NOT provided
        # [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        GIMMICK_MAX_COUNTS = {
            "frog": 3,  # 개구리는 선택 가능해야 하므로 최대 3개
            "bomb": 4,  # 폭탄도 과도하면 어려움
        }

        def get_global_target(obstacle_type: str, default_ratio: float) -> int:
            if has_layer_obstacle_configs:
                # Per-layer configs take priority, don't use global targets for distribution
                return 0
            if params.obstacle_counts and obstacle_type in params.obstacle_counts:
                config = params.obstacle_counts[obstacle_type]
                min_count = config.get("min", 0)
                max_count = config.get("max", 10)
                # Apply gimmick_intensity to configured counts
                result = int(random.randint(min_count, max_count) * gimmick_intensity)
                # Apply max cap if defined
                if obstacle_type in GIMMICK_MAX_COUNTS:
                    result = min(result, GIMMICK_MAX_COUNTS[obstacle_type])
                return result

            # Calculate based on difficulty
            calculated = int(total_tiles * target * default_ratio * gimmick_intensity)

            # IMPORTANT: If this gimmick is requested and gimmick_intensity > 0,
            # ensure minimum 2 instances so players can learn the mechanic
            # (언락된 기믹은 최소 2개 보장하여 학습 가능하도록)
            if obstacle_type in obstacle_types and gimmick_intensity > 0:
                min_for_learning = 2  # Minimum for player to understand the gimmick
                calculated = max(calculated, min_for_learning)

            # Apply max cap if defined (e.g., frog max 3)
            if obstacle_type in GIMMICK_MAX_COUNTS:
                calculated = min(calculated, GIMMICK_MAX_COUNTS[obstacle_type])

            return calculated

        # Helper to get per-layer obstacle target
        def get_layer_target(layer_idx: int, obstacle_type: str) -> Optional[int]:
            config = params.get_layer_obstacle_config(layer_idx, obstacle_type)
            if config is not None:
                min_count, max_count = config
                # Apply gimmick_intensity to per-layer configs
                return int(random.randint(min_count, max_count) * gimmick_intensity)
            return None

        # All supported obstacle types
        ALL_OBSTACLE_TYPES = ["chain", "frog", "link", "grass", "ice", "bomb", "curtain", "teleport", "unknown"]

        # Build per-layer obstacle targets
        layer_targets: Dict[int, Dict[str, int]] = {}
        configured_totals: Dict[str, int] = {obs: 0 for obs in ALL_OBSTACLE_TYPES}

        for i in range(num_layers):
            layer_targets[i] = {}
            for obs_type in ALL_OBSTACLE_TYPES:
                layer_target = get_layer_target(i, obs_type)
                if layer_target is not None:
                    layer_targets[i][obs_type] = layer_target
                    configured_totals[obs_type] += layer_target

        # Get global targets (use configured values or calculate from difficulty)
        # These are only used when per-layer configs are NOT provided
        #
        # Tile Buster style gimmick distribution:
        # - Gimmicks should be conservative, typically 10-20% of tiles at max difficulty
        # - S grade (0-0.2): ~0% gimmicks
        # - A grade (0.2-0.4): ~3-5% total gimmicks
        # - B grade (0.4-0.6): ~5-8% total gimmicks
        # - C grade (0.6-0.8): ~8-12% total gimmicks
        # - D grade (0.8-1.0): ~12-15% total gimmicks
        #
        # Reduced ratios to match Tile Buster style (was: chain=0.15, frog=0.08, ice=0.12)
        # Target: ~10-15% total gimmicks at max difficulty
        # [연구 근거] Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
        # 레벨 번호에 따른 unknown 비율 동적 계산
        level_number = getattr(params, 'level_number', None)
        unknown_ratio = 0.02  # 기본값 2%
        if level_number is not None:
            # calculate_hidden_tile_ratio returns 0.0-0.6 based on level number
            # Level 1-90: 0%, Level 91-175: 0-15%, Level 175+: 15-60%
            unknown_ratio = max(0.02, calculate_hidden_tile_ratio(level_number))

        # Boost unknown ratio for tutorial level (unknown gimmick introduction)
        # Tutorial needs more visible unknown tiles to demonstrate the mechanic
        unknown_min_count = 0
        if tutorial_gimmick == "unknown":
            # Minimum 15% for tutorial to ensure enough unknown tiles are visible
            unknown_ratio = max(0.15, unknown_ratio)
            unknown_min_count = tutorial_gimmick_min_count  # Ensure at least min_count unknown tiles
            logger.info(f"Tutorial gimmick 'unknown' - boosted ratio to {unknown_ratio:.0%}, min_count={unknown_min_count}")

        global_targets = {
            "chain": get_global_target("chain", 0.04),
            "frog": get_global_target("frog", 0.02),
            "link": get_global_target("link", 0.02),
            "grass": get_global_target("grass", 0.03),
            "ice": get_global_target("ice", 0.03),
            "bomb": get_global_target("bomb", 0.02),  # Increased from 0.01 to ensure at least 1 bomb
            "curtain": get_global_target("curtain", 0.02),
            "teleport": get_global_target("teleport", 0.02),  # Increased from 0.01 to ensure at least 1 teleport
            # [연구 근거] 레벨 기반 동적 비율, tutorial에서는 최소 min_count 보장
            "unknown": max(unknown_min_count, get_global_target("unknown", unknown_ratio)),
        }

        # Distribute remaining to unconfigured layers
        # Only if per-layer configs are NOT provided
        if not has_layer_obstacle_configs:
            unconfigured_layers = []
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                if level.get(layer_key, {}).get("tiles", {}):
                    unconfigured_layers.append(i)

            # Gimmicks that benefit from being on lower layers (blocked by upper tiles)
            # These should be placed on layer_1+ for higher difficulty
            PREFER_LOWER_LAYER_GIMMICKS = {"chain", "grass", "ice", "link"}

            for obs_type in ALL_OBSTACLE_TYPES:
                remaining = max(0, global_targets[obs_type] - configured_totals[obs_type])
                if remaining > 0 and unconfigured_layers:
                    # Distribute remaining to layers without specific config
                    layers_needing = [
                        l for l in unconfigured_layers
                        if obs_type not in layer_targets.get(l, {})
                    ]

                    # DIFFICULTY ENHANCEMENT: For blockable gimmicks at high difficulty,
                    # prefer lower layers (layer_1+) so they can be blocked by upper tiles
                    if obs_type in PREFER_LOWER_LAYER_GIMMICKS and target >= 0.5:
                        # Sort layers by index descending (lower layers first for gimmicks)
                        # But keep some on layer_0 for variety
                        layers_needing_sorted = sorted(layers_needing, reverse=True)
                        # Allocate more to lower layers (70% to layer_1+, 30% to layer_0)
                        lower_layers = [l for l in layers_needing_sorted if l > 0]
                        if lower_layers and remaining > 1:
                            # Put majority on lower layers
                            lower_allocation = int(remaining * 0.7)
                            upper_allocation = remaining - lower_allocation
                            # Distribute to lower layers
                            if lower_allocation > 0:
                                per_lower = lower_allocation // len(lower_layers)
                                extra_lower = lower_allocation % len(lower_layers)
                                for idx, layer_idx in enumerate(lower_layers):
                                    if layer_idx not in layer_targets:
                                        layer_targets[layer_idx] = {}
                                    layer_targets[layer_idx][obs_type] = per_lower + (1 if idx < extra_lower else 0)
                            # Distribute remaining to layer_0 if it exists
                            if 0 in layers_needing and upper_allocation > 0:
                                if 0 not in layer_targets:
                                    layer_targets[0] = {}
                                layer_targets[0][obs_type] = upper_allocation
                            continue

                    if layers_needing:
                        per_layer = remaining // len(layers_needing)
                        extra = remaining % len(layers_needing)
                        for idx, layer_idx in enumerate(layers_needing):
                            if layer_idx not in layer_targets:
                                layer_targets[layer_idx] = {}
                            layer_targets[layer_idx][obs_type] = per_layer + (1 if idx < extra else 0)

        obstacles_added = {obs: 0 for obs in ALL_OBSTACLE_TYPES}

        # Add obstacles per layer
        for layer_idx in range(num_layers):
            targets = layer_targets.get(layer_idx, {})

            # Add frog obstacles (no special rules)
            if "frog" in obstacle_types:
                frog_target = targets.get("frog", 0)
                if frog_target > 0:
                    level = self._add_frog_obstacles_to_layer(
                        level, layer_idx, frog_target, obstacles_added
                    )

            # Add chain obstacles (must have clearable LEFT or RIGHT neighbor)
            if "chain" in obstacle_types:
                chain_target = targets.get("chain", 0)
                if chain_target > 0:
                    level = self._add_chain_obstacles_to_layer(
                        level, layer_idx, chain_target, obstacles_added
                    )

            # Add link obstacles (must create valid pairs with clearable neighbor)
            if "link" in obstacle_types:
                link_target = targets.get("link", 0)
                if link_target > 0:
                    level = self._add_link_obstacles_to_layer(
                        level, layer_idx, link_target, obstacles_added
                    )

            # Add grass obstacles (must have at least 2 clearable neighbors)
            if "grass" in obstacle_types:
                grass_target = targets.get("grass", 0)
                if grass_target > 0:
                    level = self._add_grass_obstacles_to_layer(
                        level, layer_idx, grass_target, obstacles_added
                    )

            # Add ice obstacles (covers tile, must be cleared by adjacent matches)
            if "ice" in obstacle_types:
                ice_target = targets.get("ice", 0)
                if ice_target > 0:
                    level = self._add_ice_obstacles_to_layer(
                        level, layer_idx, ice_target, obstacles_added
                    )

            # Add bomb obstacles (countdown bomb)
            if "bomb" in obstacle_types:
                bomb_target = targets.get("bomb", 0)
                if bomb_target > 0:
                    level = self._add_bomb_obstacles_to_layer(
                        level, layer_idx, bomb_target, obstacles_added
                    )

            # Add curtain obstacles (hides tile until adjacent match)
            if "curtain" in obstacle_types:
                curtain_target = targets.get("curtain", 0)
                if curtain_target > 0:
                    level = self._add_curtain_obstacles_to_layer(
                        level, layer_idx, curtain_target, obstacles_added
                    )

            # Add teleport obstacles (paired teleport tiles)
            if "teleport" in obstacle_types:
                teleport_target = targets.get("teleport", 0)
                if teleport_target > 0:
                    level = self._add_teleport_obstacles_to_layer(
                        level, layer_idx, teleport_target, obstacles_added
                    )

            # Add unknown obstacles (tile type hidden when covered by upper layer)
            if "unknown" in obstacle_types:
                unknown_target = targets.get("unknown", 0)
                if unknown_target > 0:
                    level = self._add_unknown_obstacles_to_layer(
                        level, layer_idx, unknown_target, obstacles_added
                    )

        # DIFFICULTY ENHANCEMENT: Place blocking tiles above chain/grass gimmicks
        # This increases difficulty by requiring players to clear upper tiles first
        if target >= 0.5:  # Only apply for medium+ difficulty levels
            level = self._add_blocking_tiles_above_gimmicks(level, target)

        return level

    def _add_blocking_tiles_above_gimmicks(
        self, level: Dict[str, Any], target_difficulty: float
    ) -> Dict[str, Any]:
        """
        DIFFICULTY ENHANCEMENT: Place blocking tiles on upper layers above chain/grass gimmicks.

        This increases difficulty by:
        - Requiring players to clear upper tiles first before accessing gimmicks
        - Chain tiles become harder because adjacent matches are blocked
        - Grass tiles become harder because neighbors are covered

        The blocking probability scales with difficulty:
        - 0.5 difficulty: ~20% of gimmicks get blocked
        - 0.7 difficulty: ~40% of gimmicks get blocked
        - 0.85 difficulty: ~60% of gimmicks get blocked
        - 1.0 difficulty: ~80% of gimmicks get blocked
        """
        num_layers = level.get("layer", 8)

        # Helper to check if gimmick type is blockable
        # Includes variants like ice_1, ice_2, link_e, link_w, link_s, link_n
        def is_blockable_gimmick(gimmick: str) -> bool:
            if not gimmick:
                return False
            return (gimmick in {"chain", "grass"} or
                    gimmick.startswith("ice") or
                    gimmick.startswith("link"))

        # Calculate blocking probability based on difficulty
        # Higher difficulty = more blocking = harder to access gimmicks
        # Maps difficulty 0.5-1.0 to probability 0.3-0.9
        blocking_probability = 0.3 + (target_difficulty - 0.5) * 1.2
        blocking_probability = max(0.3, min(0.9, blocking_probability))

        # Collect all gimmick positions per layer (except layer 0 which has no upper layer)
        gimmick_positions = []  # List of (layer_idx, position, gimmick_type)

        for layer_idx in range(1, num_layers):  # Start from 1 (layer 0 has no upper layer)
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue
                gimmick_type = tile_data[1]
                if is_blockable_gimmick(gimmick_type):
                    gimmick_positions.append((layer_idx, pos, gimmick_type))

        if not gimmick_positions:
            return level

        # Randomly select gimmicks to block based on probability
        random.shuffle(gimmick_positions)
        num_to_block = int(len(gimmick_positions) * blocking_probability)
        positions_to_block = gimmick_positions[:num_to_block]

        # Get available tile types from layer_0 for creating blocking tiles
        layer_0_tiles = level.get("layer_0", {}).get("tiles", {})
        available_tile_types = set()
        for tile_data in layer_0_tiles.values():
            if isinstance(tile_data, list) and len(tile_data) >= 1:
                tile_type = tile_data[0]
                if tile_type and tile_type not in self.GOAL_TYPES:
                    available_tile_types.add(tile_type)

        if not available_tile_types:
            # Fallback: use t0 to match the standard tile type format
            available_tile_types = {"t0"}

        tile_types_list = list(available_tile_types)

        # Place blocking tiles on upper layers
        blocked_count = 0
        for layer_idx, pos, gimmick_type in positions_to_block:
            upper_layer_idx = layer_idx - 1
            upper_layer_key = f"layer_{upper_layer_idx}"

            # Check if upper layer exists and has tiles dict
            if upper_layer_key not in level:
                continue

            upper_tiles = level[upper_layer_key].get("tiles", {})
            if upper_tiles is None:
                level[upper_layer_key]["tiles"] = {}
                upper_tiles = level[upper_layer_key]["tiles"]

            # Try to add blocking tile at the exact position first
            if pos not in upper_tiles:
                # Create a new blocking tile (random type, no gimmick)
                blocking_tile_type = random.choice(tile_types_list)
                self._place_tile(upper_tiles, pos, blocking_tile_type, "")
                blocked_count += 1
            else:
                # If exact position is occupied, try adjacent positions
                # This still increases difficulty by limiting access paths to the gimmick
                try:
                    col, row = map(int, pos.split('_'))
                    adjacent_positions = [
                        f"{col-1}_{row}",  # left
                        f"{col+1}_{row}",  # right
                        f"{col}_{row-1}",  # up
                        f"{col}_{row+1}",  # down
                    ]
                    for adj_pos in adjacent_positions:
                        if adj_pos not in upper_tiles:
                            blocking_tile_type = random.choice(tile_types_list)
                            self._place_tile(upper_tiles, adj_pos, blocking_tile_type, "")
                            blocked_count += 1
                            break  # Only add one adjacent blocking tile
                except (ValueError, AttributeError):
                    pass

        return level

    def _add_frog_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add frog obstacles to a specific layer.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.

        [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        """
        # Global max check - ensure we never exceed max frogs per level
        MAX_FROGS_PER_LEVEL = 3
        if counter["frog"] >= MAX_FROGS_PER_LEVEL:
            logger.debug(f"[FROG] Layer {layer_idx}: Skipping - already at max {MAX_FROGS_PER_LEVEL} frogs")
            return level

        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        added = 0
        skipped_covered = 0

        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            # Check both per-layer target and global max
            if added >= target or counter["frog"] >= MAX_FROGS_PER_LEVEL:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # RULE: Skip positions covered by upper layers (frogs must be selectable at spawn)
            try:
                col, row = map(int, pos.split('_'))
                if self._is_position_covered_by_upper(level, layer_idx, col, row):
                    skipped_covered += 1
                    continue
            except Exception as e:
                logger.warning(f"[FROG] Layer {layer_idx}: Error parsing position {pos}: {e}")
                continue

            tile_data[1] = "frog"
            added += 1
            counter["frog"] += 1
            logger.debug(f"[FROG] Layer {layer_idx}: Added frog at {pos} (total: {counter['frog']})")

        if skipped_covered > 0:
            logger.debug(f"[FROG] Layer {layer_idx}: Skipped {skipped_covered} covered positions")

        return level

    def _add_chain_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add chain obstacles to a specific layer.

        RULE: Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT.
        The neighbor must:
        1. Exist in the same layer
        2. NOT be covered by upper layers (so it can be selected first)
        3. NOT have a blocking gimmick (chain, ice, grass, link, etc.)
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (col±1 = left/right on screen)
            neighbors = [
                (col-1, row),  # Left (on screen)
                (col+1, row),  # Right (on screen)
            ]

            valid_chain = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos not in tiles:
                    continue
                ndata = tiles[npos]
                if not isinstance(ndata, list) or len(ndata) < 2:
                    continue
                if ndata[0] in self.GOAL_TYPES:
                    continue
                # Neighbor must be clearable (no obstacle or frog only)
                if ndata[1] and ndata[1] != "frog":
                    continue
                # CRITICAL: Neighbor must NOT be covered by upper layers
                # If covered, the chain cannot be unlocked because neighbor can't be selected first
                if self._is_position_covered_by_upper(level, layer_idx, ncol, nrow):
                    continue
                valid_chain = True
                break

            if valid_chain:
                tile_data[1] = "chain"
                added += 1
                counter["chain"] += 1

        return level

    def _add_link_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add link obstacles to a specific layer.

        Link tiles point to a direction and MUST have a tile in that direction.
        IMPORTANT: Only ONE tile in a linked pair should have the link attribute.
        The target tile must NOT have any attribute (including other links).
        A tile that is already a link target CANNOT be targeted by another link.

        Position format is "col_row" (x_y).
        - link_n: points north (up), tile must exist at row-1 (y-1)
        - link_s: points south (down), tile must exist at row+1 (y+1)
        - link_w: points west (left), tile must exist at col-1 (x-1)
        - link_e: points east (right), tile must exist at col+1 (x+1)
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 15

        positions = list(tiles.keys())

        # Track positions that are already link targets
        # This prevents multiple links pointing to the same tile
        linked_targets: set = set()

        # Also collect existing link targets from tiles that already have link attributes
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1]:
                attr = tile_data[1]
                if attr.startswith("link_"):
                    try:
                        col, row = map(int, pos.split('_'))
                        # Calculate target position based on link direction
                        if attr == "link_n":
                            linked_targets.add(f"{col}_{row - 1}")
                        elif attr == "link_s":
                            linked_targets.add(f"{col}_{row + 1}")
                        elif attr == "link_w":
                            linked_targets.add(f"{col - 1}_{row}")
                        elif attr == "link_e":
                            linked_targets.add(f"{col + 1}_{row}")
                    except:
                        pass

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Source tile must not be a link target already
            if pos in linked_targets:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Direction mapping: link type -> target position
            # Position format: f"{col}_{row}"
            # link_n points north (up), so row-1
            # link_s points south (down), so row+1
            # link_w points west (left), so col-1
            # link_e points east (right), so col+1
            directions = [
                ("link_n", col, row - 1),  # North (up)
                ("link_s", col, row + 1),  # South (down)
                ("link_w", col - 1, row),  # West (left)
                ("link_e", col + 1, row),  # East (right)
            ]
            random.shuffle(directions)

            for link_type, target_col, target_row in directions:
                target_pos = f"{target_col}_{target_row}"

                # CRITICAL: The linked direction MUST have a tile
                if target_pos not in tiles:
                    continue

                # CRITICAL: Target must NOT already be a link target
                if target_pos in linked_targets:
                    continue

                target_tile = tiles[target_pos]
                if not isinstance(target_tile, list) or len(target_tile) < 2:
                    continue

                # Target tile must be a valid clearable tile (not a goal)
                if target_tile[0] in self.GOAL_TYPES:
                    continue

                # CRITICAL: Target tile must NOT have any attribute
                # This prevents both tiles in a pair from having link attributes
                # (which would count as 2 links instead of 1)
                if target_tile[1]:
                    logger.debug(f"[LINK] Skipping {pos} -> {target_pos}: target has attribute '{target_tile[1]}'")
                    continue

                # CRITICAL: Explicitly reject chain, ice, grass on target (blocking gimmicks)
                # This is a defensive double-check in case the generic check above fails
                BLOCKING_GIMMICKS = {"chain", "ice", "ice_1", "ice_2", "ice_3", "grass"}
                if target_tile[1] in BLOCKING_GIMMICKS:
                    logger.warning(f"[LINK] BLOCKED: {pos} -> {target_pos} would create link->chain/ice/grass")
                    continue

                # Valid link found - assign the link type
                tile_data[1] = link_type
                added += 1
                counter["link"] += 1

                # Mark target as linked (cannot be targeted by another link)
                linked_targets.add(target_pos)
                # Also mark source as linked target to prevent it from being targeted
                linked_targets.add(pos)
                break

        return level

    def _add_grass_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add grass obstacles to a specific layer (must have 2+ clearable neighbors)."""
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (col, row-1),  # Up
                (col, row+1),  # Down
                (col-1, row),  # Left
                (col+1, row),  # Right
            ]

            clearable_count = 0
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        clearable_count += 1

            # Must have at least 2 clearable neighbors
            if clearable_count >= 2:
                tile_data[1] = "grass"
                added += 1
                counter["grass"] += 1

        return level

    def _add_ice_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add ice obstacles to a specific layer.
        Ice covers tiles and must be cleared by adjacent matches.
        Can have 1-3 layers of ice (ice_1, ice_2, ice_3).
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Random ice level (1-3), weighted toward lower levels
            ice_level = random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0]
            tile_data[1] = f"ice_{ice_level}"
            added += 1
            counter["ice"] += 1

        return level

    def _add_bomb_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add bomb obstacles to a specific layer.

        Bombs have a countdown and explode if not cleared in time.
        NOTE: Bombs CAN be placed on covered tiles. The countdown only starts
        when the bomb becomes selectable (exposed/not covered by upper layers).
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Set bomb with countdown (stored in extra field)
            countdown = random.randint(5, 10)
            tile_data[1] = "bomb"
            if len(tile_data) < 3:
                tile_data.append([countdown])
            else:
                tile_data[2] = [countdown]
            added += 1
            counter["bomb"] += 1

        return level

    def _add_curtain_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add curtain obstacles to a specific layer.
        Curtain hides the tile underneath until an adjacent match is made.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Curtain needs at least one adjacent tile to be cleared
            neighbors = [
                (col, row-1), (col, row+1),
                (col-1, row), (col+1, row),
            ]

            has_neighbor = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        ndata[0] not in self.GOAL_TYPES):
                        has_neighbor = True
                        break

            if has_neighbor:
                tile_data[1] = "curtain_close"
                added += 1
                counter["curtain"] += 1

        return level

    def _add_teleport_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add teleport obstacles to a specific layer.
        Teleports work in pairs - clearing one affects the paired teleport.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        # Need at least 2 tiles for a teleport pair
        if len(tiles) < 2:
            return level

        added = 0
        # Teleports are added in pairs
        pairs_to_add = target // 2
        if pairs_to_add == 0 and target > 0:
            pairs_to_add = 1

        available_positions = [
            pos for pos, data in tiles.items()
            if isinstance(data, list) and len(data) >= 2 and
            data[0] not in self.GOAL_TYPES and not data[1]
        ]
        random.shuffle(available_positions)

        pair_id = 0
        for i in range(0, len(available_positions) - 1, 2):
            if pair_id >= pairs_to_add:
                break

            pos1 = available_positions[i]
            pos2 = available_positions[i + 1]

            # Set teleport with pair ID using helper methods
            self._set_tile_attribute(tiles[pos1], "teleport")
            self._set_tile_extra(tiles[pos1], [pair_id])

            self._set_tile_attribute(tiles[pos2], "teleport")
            self._set_tile_extra(tiles[pos2], [pair_id])

            added += 2
            counter["teleport"] += 2
            pair_id += 1

        return level

    def _add_unknown_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add unknown obstacles to a specific layer.

        RULE: Unknown tiles should ONLY be placed on tiles that ARE covered by upper layers.
        This is because the unknown effect only activates when the tile is hidden by upper tiles.
        When upper tiles are removed, the tile type becomes visible.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())
        random.shuffle(positions)

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # RULE: Unknown tiles must be covered by upper layers to have any effect
            if not self._is_position_covered_by_upper(level, layer_idx, col, row):
                continue

            tile_data[1] = "unknown"
            added += 1
            counter["unknown"] += 1

        return level

    def _add_frog_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add frog obstacles.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.

        [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        """
        MAX_FROGS_PER_LEVEL = 3
        num_layers = level.get("layer", 8)

        for i in range(num_layers - 1, -1, -1):
            # Check both target and global max
            if counter["frog"] >= target or counter["frog"] >= MAX_FROGS_PER_LEVEL:
                break

            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in list(tiles.items()):
                if counter["frog"] >= target or counter["frog"] >= MAX_FROGS_PER_LEVEL:
                    break

                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                # Skip goal tiles and tiles with attributes
                if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                    continue

                # RULE: Skip positions covered by upper layers (frogs must be selectable at spawn)
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, i, col, row):
                        continue
                except:
                    continue

                if random.random() < 0.15:
                    tile_data[1] = "frog"
                    counter["frog"] += 1

        return level

    def _add_chain_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add chain obstacles following the rule:
        Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT (same row).
        Chain is released by clearing adjacent tiles on the left or right side only.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer with their positions
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = {
                    "tiles": tiles,
                    "cols": int(level[layer_key].get("col", 8)),
                    "rows": int(level[layer_key].get("row", 8))
                }

        # Try to add chains
        attempts = 0
        max_attempts = target * 10  # Prevent infinite loop

        while counter["chain"] < target and attempts < max_attempts:
            attempts += 1

            # Pick a random layer with tiles
            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            layer_data = layer_tiles[layer_idx]
            tiles = layer_data["tiles"]

            # Pick a random tile
            positions = list(tiles.keys())
            if not positions:
                continue

            pos = random.choice(positions)
            tile_data = tiles[pos]

            # Skip if not valid
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Parse position (format is col_row = x_y)
            try:
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (col±1 = left/right on screen)
            neighbors = [
                (col-1, row),  # Left (on screen)
                (col+1, row),  # Right (on screen)
            ]

            valid_chain = False
            for ncol, nrow in neighbors:
                neighbor_pos = f"{ncol}_{nrow}"
                if neighbor_pos not in tiles:
                    continue

                neighbor_data = tiles[neighbor_pos]
                if not isinstance(neighbor_data, list) or len(neighbor_data) < 2:
                    continue

                # Skip goal tiles
                if neighbor_data[0] in self.GOAL_TYPES:
                    continue

                # RULE: Neighbor must be clearable (no obstacle or frog only)
                if neighbor_data[1] and neighbor_data[1] != "frog":
                    continue

                # CRITICAL: Neighbor must NOT be covered by upper layers
                # If covered, the chain cannot be unlocked because neighbor can't be selected first
                if self._is_position_covered_by_upper(level, layer_idx, ncol, nrow):
                    continue

                # Valid chain position found!
                valid_chain = True
                break

            if valid_chain:
                tile_data[1] = "chain"
                counter["chain"] += 1

        return level

    def _add_grass_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add grass obstacles following the rule:
        Grass tiles MUST have at least 2 clearable neighbors in 4 directions (up/down/left/right).
        Grass is released by clearing adjacent tiles (needs at least 2 to be clearable).
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        attempts = 0
        max_attempts = target * 10

        while counter["grass"] < target and attempts < max_attempts:
            attempts += 1

            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            tiles = layer_tiles[layer_idx]

            positions = list(tiles.keys())
            if not positions:
                continue

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (col, row-1),  # Up
                (col, row+1),  # Down
                (col-1, row),  # Left
                (col+1, row),  # Right
            ]

            clearable_count = 0
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        clearable_count += 1

            # RULE: Must have at least 2 clearable neighbors
            if clearable_count >= 2:
                tile_data[1] = "grass"
                counter["grass"] += 1

        return level

    def _add_link_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add link obstacles following the rules:
        1. Linked tiles must have their partner tile exist in the connected direction.
        2. ONLY ONE tile in a linked pair has the link attribute (not both).
        3. The target tile must NOT have any attribute.
        4. A tile that is already a link target CANNOT be targeted by another link.

        Position format is "col_row" (x_y).
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        # Track positions that are already link targets (per layer)
        # This prevents multiple links pointing to the same tile
        linked_targets_per_layer: Dict[int, set] = {i: set() for i in layer_tiles.keys()}

        # Collect existing link targets from tiles that already have link attributes
        for layer_idx, tiles in layer_tiles.items():
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1]:
                    attr = tile_data[1]
                    if attr.startswith("link_"):
                        try:
                            col, row = map(int, pos.split('_'))
                            # Calculate target position based on link direction
                            if attr == "link_n":
                                linked_targets_per_layer[layer_idx].add(f"{col}_{row - 1}")
                            elif attr == "link_s":
                                linked_targets_per_layer[layer_idx].add(f"{col}_{row + 1}")
                            elif attr == "link_w":
                                linked_targets_per_layer[layer_idx].add(f"{col - 1}_{row}")
                            elif attr == "link_e":
                                linked_targets_per_layer[layer_idx].add(f"{col + 1}_{row}")
                            # Also add source position as it's part of a link pair
                            linked_targets_per_layer[layer_idx].add(pos)
                        except:
                            pass

        attempts = 0
        max_attempts = target * 10

        while counter["link"] < target and attempts < max_attempts:
            attempts += 1

            # Pick a random layer
            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            tiles = layer_tiles[layer_idx]
            linked_targets = linked_targets_per_layer[layer_idx]

            # Pick a random tile
            positions = list(tiles.keys())
            if not positions:
                continue

            pos1 = random.choice(positions)
            tile_data1 = tiles[pos1]

            # Skip if not valid
            if not isinstance(tile_data1, list) or len(tile_data1) < 2:
                continue
            if tile_data1[0] in self.GOAL_TYPES or tile_data1[1]:
                continue

            # Source tile must not be a link target already
            if pos1 in linked_targets:
                continue

            # Parse position (format is col_row = x_y)
            try:
                col1, row1 = map(int, pos1.split('_'))
            except:
                continue

            # Try to find a valid partner in one of 4 directions
            directions = [
                ("link_n", col1, row1 - 1),  # North (up = row-1)
                ("link_s", col1, row1 + 1),  # South (down = row+1)
                ("link_w", col1 - 1, row1),  # West (left = col-1)
                ("link_e", col1 + 1, row1),  # East (right = col+1)
            ]
            random.shuffle(directions)

            valid_link = False
            for link_type, col2, row2 in directions:
                pos2 = f"{col2}_{row2}"

                # RULE 1: Partner tile MUST exist
                if pos2 not in tiles:
                    continue

                # CRITICAL: Target must NOT already be a link target
                if pos2 in linked_targets:
                    continue

                tile_data2 = tiles[pos2]
                if not isinstance(tile_data2, list) or len(tile_data2) < 2:
                    continue

                # Skip goal tiles
                if tile_data2[0] in self.GOAL_TYPES:
                    continue

                # CRITICAL: Target tile must NOT have any attribute
                # This ensures only one tile in the pair has link attribute
                if tile_data2[1]:
                    logger.debug(f"[LINK] Skipping {pos1} -> {pos2}: target has attribute '{tile_data2[1]}'")
                    continue

                # CRITICAL: Explicitly reject chain, ice, grass on target (blocking gimmicks)
                # Defensive double-check
                BLOCKING_GIMMICKS = {"chain", "ice", "ice_1", "ice_2", "ice_3", "grass"}
                if tile_data2[1] in BLOCKING_GIMMICKS:
                    logger.warning(f"[LINK] BLOCKED: {pos1} -> {pos2} would create link->blocking gimmick")
                    continue

                # Valid link found - assign the link type to ONLY the source tile
                tile_data1[1] = link_type
                counter["link"] += 1  # Count as 1 link (not 2)

                # Mark both source and target as linked (cannot be targeted by another link)
                linked_targets.add(pos1)
                linked_targets.add(pos2)
                valid_link = True
                break

            if valid_link:
                pass  # Successfully added link pair

        return level

    def _link_pair_has_clearable_neighbor(
        self, tiles: Dict, pos1: str, pos2: str,
        row1: int, col1: int, row2: int, col2: int
    ) -> bool:
        """
        Check if at least one tile in the link pair has a clearable neighbor.
        A clearable neighbor is a tile without obstacle attribute (or frog only).
        The link partner itself doesn't count as a clearable neighbor.
        """
        # Get all neighbors for both tiles (excluding each other)
        neighbors1 = [
            (row1+1, col1), (row1-1, col1), (row1, col1+1), (row1, col1-1)
        ]
        neighbors2 = [
            (row2+1, col2), (row2-1, col2), (row2, col2+1), (row2, col2-1)
        ]

        # Check neighbors of tile 1 (excluding pos2)
        for nrow, ncol in neighbors1:
            npos = f"{nrow}_{ncol}"
            if npos == pos2:
                continue
            if npos in tiles:
                ndata = tiles[npos]
                if (isinstance(ndata, list) and len(ndata) >= 2 and
                    (not ndata[1] or ndata[1] == "frog") and
                    ndata[0] not in self.GOAL_TYPES):
                    return True

        # Check neighbors of tile 2 (excluding pos1)
        for nrow, ncol in neighbors2:
            npos = f"{nrow}_{ncol}"
            if npos == pos1:
                continue
            if npos in tiles:
                ndata = tiles[npos]
                if (isinstance(ndata, list) and len(ndata) >= 2 and
                    (not ndata[1] or ndata[1] == "frog") and
                    ndata[0] not in self.GOAL_TYPES):
                    return True

        return False

    def _add_goals(
        self, level: Dict[str, Any], params: GenerationParams, strict_mode: bool = False
    ) -> Dict[str, Any]:
        """Add goal tiles to the level.

        In strict mode (when layer_tile_configs is specified), goal tiles REPLACE
        existing tiles rather than being added, to maintain exact tile counts.

        Direction rules for goals:
        - craft_s / stack_s: outputs tiles downward (row+1), cannot be at bottom row
        - craft_n / stack_n: outputs tiles upward (row-1), cannot be at top row
        - craft_e / stack_e: outputs tiles rightward (col+1), cannot be at rightmost column
        - craft_w / stack_w: outputs tiles leftward (col-1), cannot be at leftmost column

        Stack additional rule: output position must not overlap with existing tiles
        """
        # Use None check instead of falsy check to allow empty list
        goals = params.goals if params.goals is not None else [{"type": "craft_s", "count": 3}]

        # If goals is empty list, skip adding goals
        if not goals:
            return level

        # Find the topmost active layer
        num_layers = level.get("layer", 8)
        top_layer_idx = None

        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                top_layer_idx = i
                break

        if top_layer_idx is None:
            return level

        layer_key = f"layer_{top_layer_idx}"
        tiles = level[layer_key]["tiles"]

        # Find the bottom row positions for goals
        cols = int(level[layer_key]["col"])
        rows = int(level[layer_key]["row"])

        def get_output_direction(goal_type: str) -> tuple:
            """Get output direction offset (col_offset, row_offset) for goal type."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                return (0, 1)   # output downward
            elif direction == 'n':
                return (0, -1)  # output upward
            elif direction == 'e':
                return (1, 0)   # output rightward
            elif direction == 'w':
                return (-1, 0)  # output leftward
            return (0, 1)  # default: south

        def has_adjacent_gimmick(col: int, row: int, gimmick_types: List[str]) -> bool:
            """Check if any adjacent position (4-way) has specified gimmicks.

            Chain and grass gimmicks need adjacent tiles to be cleared.
            Placing craft/stack next to them would block the clearing mechanism.
            """
            adjacent_offsets = [(0, 1), (0, -1), (1, 0), (-1, 0)]  # 4-way adjacency

            for dc, dr in adjacent_offsets:
                adj_col, adj_row = col + dc, row + dr
                if adj_col < 0 or adj_col >= cols or adj_row < 0 or adj_row >= rows:
                    continue

                adj_pos = f"{adj_col}_{adj_row}"

                # Check ALL layers for gimmicks at adjacent position
                for i in range(num_layers):
                    layer_key_i = f"layer_{i}"
                    layer_tiles = level.get(layer_key_i, {}).get("tiles", {})
                    if adj_pos in layer_tiles:
                        tile_data = layer_tiles[adj_pos]
                        if isinstance(tile_data, list) and len(tile_data) > 1:
                            attribute = tile_data[1] or ""
                            # Check for chain or grass gimmicks
                            for gimmick in gimmick_types:
                                if attribute == gimmick or attribute.startswith(f"{gimmick}_"):
                                    return True
            return False

        def is_valid_goal_position(col: int, row: int, goal_type: str) -> bool:
            """Check if position is valid for goal considering output direction.

            Rules for craft/stack goals:
            1. Output position must be within bounds
            2. Output position must be empty across ALL layers (both craft and stack)
            3. Goal position must NOT be adjacent to chain/grass gimmicks
               (chain/grass need adjacent tiles cleared, craft/stack blocks this)

            NOTE: Goal position having tiles in lower layers is handled by clearing them
            during placement.
            """
            col_off, row_off = get_output_direction(goal_type)
            output_col = col + col_off
            output_row = row + row_off

            # Check output position is within bounds
            if output_col < 0 or output_col >= cols:
                return False
            if output_row < 0 or output_row >= rows:
                return False

            # For BOTH craft AND stack goals, output position must not overlap with existing tiles
            # CRITICAL: Check ALL layers, not just current layer
            # Both craft and stack spawn tiles at output position, which would conflict with any existing tile
            if goal_type.startswith("stack") or goal_type.startswith("craft"):
                output_pos = f"{output_col}_{output_row}"
                # Check ALL layers for existing tiles at output position
                for i in range(num_layers):
                    layer_key_i = f"layer_{i}"
                    layer_tiles = level.get(layer_key_i, {}).get("tiles", {})
                    if output_pos in layer_tiles:
                        return False

                # CRITICAL: Craft/Stack must NOT be adjacent to chain or grass gimmicks
                # Chain/grass need adjacent tiles cleared to be removed.
                # Craft/stack tiles are permanent until goal is met, blocking clearance.
                if has_adjacent_gimmick(col, row, ["chain", "grass"]):
                    return False

                # Also check output position - don't output next to chain/grass
                if has_adjacent_gimmick(output_col, output_row, ["chain", "grass"]):
                    return False

            return True

        def get_preferred_row_for_direction(goal_type: str) -> int:
            """Get preferred starting row based on goal direction."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                # South: prefer upper rows (not bottom row)
                return 0
            elif direction == 'n':
                # North: prefer lower rows (not top row)
                return rows - 1
            else:
                # East/West: prefer bottom row
                return rows - 1

        def get_row_search_order(goal_type: str) -> range:
            """Get row search order based on goal direction."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                # South: search from top to bottom-1
                return range(0, rows - 1)
            elif direction == 'n':
                # North: search from bottom to top+1
                return range(rows - 1, 0, -1)
            else:
                # East/West: search from bottom to top
                return range(rows - 1, -1, -1)

        # In strict mode, goals are ADDED (not replacing existing tiles)
        # Goal tiles contain inner tiles, so:
        # - Visual tiles = config tiles + num_goals
        # - Actual tiles = config tiles + goal_inner_tiles
        # Example: 21+21 config + craft(3) = 42 visual + 1 goal = 43 visual, 42 + 3 = 45 actual

        # Find available positions for goals (positions not already occupied)
        center_col = cols // 2
        center_row = rows // 2
        symmetry_mode = params.symmetry_mode or "none"
        placed_positions = set()  # Track positions used by goals
        output_positions = set()  # Track output positions of goals
        goal_positions_info = []  # Track (pos, goal_type) for adjacency check

        def is_self_symmetric_position(col: int, row: int) -> bool:
            """Check if position is its own mirror (for placing single goals in symmetric mode)."""
            if symmetry_mode == "horizontal":
                # For horizontal symmetry, only the exact center column(s) work
                # But for even cols, there's no perfect center. Allow near-center.
                mirror_col = cols - 1 - col
                return col == mirror_col  # Only true if col == (cols-1)/2, i.e., odd cols
            elif symmetry_mode == "vertical":
                mirror_row = rows - 1 - row
                return row == mirror_row
            elif symmetry_mode == "both":
                mirror_col = cols - 1 - col
                mirror_row = rows - 1 - row
                return col == mirror_col and row == mirror_row
            return True  # No symmetry, any position works

        def get_mirror_position(col: int, row: int) -> Tuple[int, int]:
            """Get the mirror position for symmetry mode."""
            if symmetry_mode == "horizontal":
                return (cols - 1 - col, row)
            elif symmetry_mode == "vertical":
                return (col, rows - 1 - row)
            elif symmetry_mode == "both":
                return (cols - 1 - col, rows - 1 - row)
            return (col, row)

        def get_mirrored_direction(direction: str) -> str:
            """Get the mirrored goal direction for symmetry mode.

            horizontal symmetry (left-right): e <-> w, n and s stay same
            vertical symmetry (top-bottom): n <-> s, e and w stay same
            """
            if symmetry_mode == "horizontal":
                if direction == 'e':
                    return 'w'
                elif direction == 'w':
                    return 'e'
            elif symmetry_mode == "vertical":
                if direction == 'n':
                    return 's'
                elif direction == 's':
                    return 'n'
            elif symmetry_mode == "both":
                # Mirror both axes
                if direction == 'e':
                    return 'w'
                elif direction == 'w':
                    return 'e'
                elif direction == 'n':
                    return 's'
                elif direction == 's':
                    return 'n'
            return direction

        def get_preferred_columns_for_symmetry() -> List[int]:
            """Get column order that respects symmetry."""
            if symmetry_mode in ("horizontal", "both"):
                # For horizontal symmetry, prefer center column
                # If cols=8, center is between 3 and 4. For even cols, prefer 3 or 4.
                if cols % 2 == 1:
                    # Odd cols: exact center exists
                    return [cols // 2]
                else:
                    # Even cols: no exact center, use the two middle columns
                    # They are at (cols//2 - 1) and (cols//2)
                    # e.g., for cols=8: 3 and 4
                    return [cols // 2 - 1, cols // 2]
            else:
                # No horizontal symmetry constraint
                return list(range(cols))

        def get_adjacent_positions(col: int, row: int) -> set:
            """Get all adjacent positions (including diagonals)."""
            adjacent = set()
            for dc in [-1, 0, 1]:
                for dr in [-1, 0, 1]:
                    if dc == 0 and dr == 0:
                        continue
                    adjacent.add(f"{col + dc}_{row + dr}")
            return adjacent

        def would_face_each_other(pos1: str, type1: str, pos2: str, type2: str) -> bool:
            """Check if two craft tiles would face each other (output into each other)."""
            col1, row1 = map(int, pos1.split("_"))
            col2, row2 = map(int, pos2.split("_"))

            dir1 = type1[-1] if type1.endswith(('_s', '_n', '_e', '_w')) else 's'
            dir2 = type2[-1] if type2.endswith(('_s', '_n', '_e', '_w')) else 's'

            # Get output positions
            offsets = {'s': (0, 1), 'n': (0, -1), 'e': (1, 0), 'w': (-1, 0)}
            out1 = (col1 + offsets[dir1][0], row1 + offsets[dir1][1])
            out2 = (col2 + offsets[dir2][0], row2 + offsets[dir2][1])

            # Check if they face each other (output to each other's position)
            if out1 == (col2, row2) or out2 == (col1, row1):
                return True

            # Check if outputs collide
            if out1 == out2:
                return True

            return False

        def would_craft_stack_conflict(
            try_pos: str, try_type: str,
            existing_goals: List[Tuple[str, str]],
            existing_output_positions: set
        ) -> bool:
            """Check if placing a goal would create craft-stack output conflict.

            Rules:
            - Stack tiles must NOT be placed at craft output positions
            - Craft tiles must NOT output into stack tile positions
            """
            try_col, try_row = map(int, try_pos.split("_"))
            is_try_stack = try_type.startswith("stack_")
            is_try_craft = try_type.startswith("craft_")

            # Get output position for the tile being placed
            try_col_off, try_row_off = get_output_direction(try_type)
            try_output_pos = f"{try_col + try_col_off}_{try_row + try_row_off}"

            for existing_pos, existing_type in existing_goals:
                is_existing_stack = existing_type.startswith("stack_")
                is_existing_craft = existing_type.startswith("craft_")

                existing_col, existing_row = map(int, existing_pos.split("_"))
                existing_col_off, existing_row_off = get_output_direction(existing_type)
                existing_output_pos = f"{existing_col + existing_col_off}_{existing_row + existing_row_off}"

                # Rule 1: Stack tile placed at craft output position
                if is_try_stack and is_existing_craft:
                    if try_pos == existing_output_pos:
                        logger.debug(f"Craft-Stack conflict: Stack {try_pos} at Craft {existing_pos} output")
                        return True

                # Rule 2: Craft tile output into stack position
                if is_try_craft and is_existing_stack:
                    if try_output_pos == existing_pos:
                        logger.debug(f"Craft-Stack conflict: Craft {try_pos} output into Stack {existing_pos}")
                        return True

                # Rule 3: Stack tile output into craft position (blocks craft)
                if is_try_stack and is_existing_craft:
                    if try_output_pos == existing_pos:
                        logger.debug(f"Craft-Stack conflict: Stack {try_pos} output into Craft {existing_pos}")
                        return True

                # Rule 4: Craft tile placed at stack output position
                if is_try_craft and is_existing_stack:
                    if try_pos == existing_output_pos:
                        logger.debug(f"Craft-Stack conflict: Craft {try_pos} at Stack {existing_pos} output")
                        return True

            return False

        for i, goal in enumerate(goals):
            # Handle both old format (type="craft_s") and new format (type="craft", direction="s")
            base_type = goal.get("type", "craft")
            goal_direction = goal.get("direction") or "s"  # Handle None value

            # If type already includes direction suffix, use as-is
            if base_type.endswith(('_s', '_n', '_e', '_w')):
                goal_type = base_type
            else:
                # Combine type and direction
                goal_type = f"{base_type}_{goal_direction}"

            goal_count = max(self.MIN_GOAL_COUNT, goal.get("count", self.MIN_GOAL_COUNT))

            # Calculate preferred column with more spacing between goals
            # For symmetric modes, prefer center columns
            if symmetry_mode in ("horizontal", "both"):
                preferred_cols = get_preferred_columns_for_symmetry()
                target_col = preferred_cols[i % len(preferred_cols)]
            else:
                spacing = 2  # Minimum 2 columns apart
                target_col = center_col - (len(goals) * spacing) // 2 + i * spacing
            target_col = max(0, min(cols - 1, target_col))

            # Find valid position considering direction rules
            pos = None
            row_order = get_row_search_order(goal_type)

            # Build column search order - RANDOMIZED for variety
            if symmetry_mode in ("horizontal", "both"):
                # Start with preferred symmetric columns, then expand outward
                preferred = get_preferred_columns_for_symmetry()
                col_search_order = preferred[:]
                for offset in range(1, cols):
                    for c in preferred:
                        if c - offset >= 0 and (c - offset) not in col_search_order:
                            col_search_order.append(c - offset)
                        if c + offset < cols and (c + offset) not in col_search_order:
                            col_search_order.append(c + offset)
            else:
                # Randomized column search for variety in goal placement
                col_search_order = list(range(cols))
                random.shuffle(col_search_order)

            # Randomize row order while respecting direction constraints
            # (e.g., craft_s can't be at bottom row, craft_n can't be at top row)
            row_order_list = list(row_order)
            random.shuffle(row_order_list)

            # For symmetric modes, goals should REPLACE existing tiles at self-symmetric positions
            # to preserve overall symmetry. For non-symmetric modes, add at new positions.
            use_replacement_mode = symmetry_mode in ("horizontal", "vertical", "both")

            # Try positions in randomized order
            for try_row in row_order_list:
                for try_col in col_search_order:
                    try_pos = f"{try_col}_{try_row}"

                    # In symmetric mode: REPLACE existing tiles at self-symmetric positions
                    # In non-symmetric mode: ADD at new positions (original behavior)
                    if use_replacement_mode:
                        # For symmetry preservation: must be an existing tile position
                        if try_pos not in tiles:
                            continue
                        # Check if this is a self-symmetric position OR we can place mirrored goal
                        mirror_col, mirror_row = get_mirror_position(try_col, try_row)
                        mirror_pos = f"{mirror_col}_{mirror_row}"
                        is_self_symmetric = is_self_symmetric_position(try_col, try_row)

                        # If not self-symmetric, check if mirror position is also valid
                        if not is_self_symmetric:
                            # Mirror position must exist and not be used
                            # Also check if mirror position is another goal's output position
                            if mirror_pos not in tiles or mirror_pos in placed_positions or mirror_pos in output_positions:
                                continue
                            # Get mirrored goal type and check validity
                            goal_dir = goal_type[-1]
                            mirrored_dir = get_mirrored_direction(goal_dir)
                            mirrored_goal_type = goal_type[:-1] + mirrored_dir
                            if not is_valid_goal_position(mirror_col, mirror_row, mirrored_goal_type):
                                continue

                        # Must not be already used by another goal
                        if try_pos in placed_positions:
                            continue
                    else:
                        # Original behavior: add at new positions
                        if try_pos in tiles or try_pos in placed_positions:
                            continue

                    # CRITICAL: Position must not be another goal's output position
                    # This prevents goals from being placed where other goals output tiles
                    # which would cause facing/collision issues
                    if try_pos in output_positions:
                        continue

                    # Check if this position is valid for the goal direction
                    if not is_valid_goal_position(try_col, try_row, goal_type):
                        continue

                    # Get output position for this goal
                    col_off, row_off = get_output_direction(goal_type)
                    output_pos = f"{try_col + col_off}_{try_row + row_off}"

                    # Check output position is not occupied by goals
                    if output_pos in placed_positions or output_pos in output_positions:
                        continue
                    # For replacement mode, output can overlap existing tiles (they'll be cleared)
                    # For non-replacement mode, output should not overlap existing tiles
                    if not use_replacement_mode and output_pos in tiles:
                        continue

                    # Check no adjacent to existing goals (minimum 1 cell gap)
                    adjacent = get_adjacent_positions(try_col, try_row)
                    if adjacent & placed_positions:
                        continue

                    # Check output position adjacency
                    output_adjacent = get_adjacent_positions(try_col + col_off, try_row + row_off)
                    if output_adjacent & output_positions:
                        continue

                    # Check not facing any existing goal
                    facing_conflict = False
                    for existing_pos, existing_type in goal_positions_info:
                        if would_face_each_other(try_pos, goal_type, existing_pos, existing_type):
                            facing_conflict = True
                            break
                    if facing_conflict:
                        continue

                    # Check craft-stack output conflict
                    # (stack tile at craft output position or craft output into stack position)
                    if would_craft_stack_conflict(try_pos, goal_type, goal_positions_info, output_positions):
                        continue

                    pos = try_pos
                    break
                if pos:
                    break

            if pos:
                p_col, p_row = map(int, pos.split("_"))
                col_off, row_off = get_output_direction(goal_type)
                output_pos = f"{p_col + col_off}_{p_row + row_off}"

                placed_positions.add(pos)
                output_positions.add(output_pos)
                goal_positions_info.append((pos, goal_type))

                self._place_goal_tile(tiles, pos, goal_type, goal_count)

                # CRITICAL: Clear tiles from lower layers at goal position
                # This ensures the goal is visible and not visually confusing
                for i in range(top_layer_idx):
                    lower_layer_key = f"layer_{i}"
                    lower_tiles = level.get(lower_layer_key, {}).get("tiles", {})
                    if pos in lower_tiles:
                        del lower_tiles[pos]
                        level[lower_layer_key]["num"] = str(len(lower_tiles))
                        logger.debug(f"[_add_goals] Cleared tile at {lower_layer_key}:{pos} for goal visibility")

                # CRITICAL: Clear tiles from ALL layers at output position
                # Stack/Craft goals spawn tiles at output position, so existing tiles would block them
                for i in range(level.get("layer", 8)):
                    check_layer_key = f"layer_{i}"
                    check_tiles = level.get(check_layer_key, {}).get("tiles", {})
                    if output_pos in check_tiles:
                        del check_tiles[output_pos]
                        level[check_layer_key]["num"] = str(len(check_tiles))
                        logger.debug(f"[_add_goals] Cleared tile at {check_layer_key}:{output_pos} for goal output")

                # CRITICAL: For stack goals, clear additional positions in stack direction
                # Stack tiles are offset by 0.1 per stacked tile in the output direction
                # [연구 근거] townpop sp_template: interval_stackOffSetY = 0.1f
                # Example: stack_e with count=6 extends 5*0.1=0.5 units east (half tile)
                # Example: stack_e with count=11 extends 10*0.1=1.0 unit east (exactly 1 tile)
                # Example: stack_e with count=12 extends 11*0.1=1.1 units east (need to block 2nd tile)
                #
                # Stacked tiles extend from stack position by (count-1) * 0.1 tiles
                # Output position is 1 tile from stack (already cleared)
                # Need to clear positions BEYOND output if extension > 1.0
                #
                # Formula: additional_positions_to_clear = ceil(max_offset) - 1
                # - count <= 11: max_offset <= 1.0, ceil=1, 1-1=0 → no extra clearing
                # - count 12-21: max_offset 1.1-2.0, ceil=2, 2-1=1 → clear 1 extra
                # - count 22+: max_offset > 2.0, ceil >= 3, 3-1=2 → clear 2 extra
                if goal_type.startswith("stack_"):
                    import math
                    STACK_OFFSET = 0.1  # 타일당 오프셋 (타운팝 기준)
                    # Calculate how far stacked tiles extend from stack position
                    max_offset = (goal_count - 1) * STACK_OFFSET

                    # Positions beyond output to clear = ceil(max_offset) - 1
                    # Output position (1 tile from stack) is already cleared
                    additional_blocked = max(0, math.ceil(max_offset) - 1)

                    if additional_blocked > 0:
                        logger.debug(f"[_add_goals] Stack {goal_type} count={goal_count}, offset={max_offset:.1f}: blocking {additional_blocked} additional positions beyond output")

                        # Clear tiles in the extended stack direction (positions beyond output)
                        for ext_idx in range(1, additional_blocked + 1):
                            # ext_idx=1: 2 tiles from stack (1 beyond output)
                            # ext_idx=2: 3 tiles from stack (2 beyond output)
                            ext_col = p_col + col_off * (ext_idx + 1)
                            ext_row = p_row + row_off * (ext_idx + 1)
                            ext_pos = f"{ext_col}_{ext_row}"

                            # Check bounds
                            if ext_col < 0 or ext_col >= cols or ext_row < 0 or ext_row >= rows:
                                continue

                            # Clear from all layers
                            for i in range(level.get("layer", 8)):
                                check_layer_key = f"layer_{i}"
                                check_tiles = level.get(check_layer_key, {}).get("tiles", {})
                                if ext_pos in check_tiles:
                                    del check_tiles[ext_pos]
                                    level[check_layer_key]["num"] = str(len(check_tiles))
                                    logger.debug(f"[_add_goals] Cleared tile at {check_layer_key}:{ext_pos} for stack extension")

                            # Also add to output_positions to prevent other goals from using it
                            output_positions.add(ext_pos)

                # In symmetric mode, also place mirrored goal if not self-symmetric position
                if use_replacement_mode and not is_self_symmetric_position(p_col, p_row):
                    mirror_col, mirror_row = get_mirror_position(p_col, p_row)
                    mirror_pos = f"{mirror_col}_{mirror_row}"

                    # Get mirrored goal type
                    goal_dir = goal_type[-1]
                    mirrored_dir = get_mirrored_direction(goal_dir)
                    mirrored_goal_type = goal_type[:-1] + mirrored_dir

                    # Check if mirrored goal would face the original goal or any existing goals
                    mirror_facing_conflict = False
                    # Check against original goal
                    if would_face_each_other(mirror_pos, mirrored_goal_type, pos, goal_type):
                        mirror_facing_conflict = True
                    # Check against all existing goals
                    if not mirror_facing_conflict:
                        for existing_pos, existing_type in goal_positions_info:
                            if would_face_each_other(mirror_pos, mirrored_goal_type, existing_pos, existing_type):
                                mirror_facing_conflict = True
                                break

                    # Check craft-stack conflict for mirrored goal
                    mirror_craft_stack_conflict = would_craft_stack_conflict(
                        mirror_pos, mirrored_goal_type, goal_positions_info, output_positions
                    )

                    # Only place mirrored goal if no facing conflict and no craft-stack conflict
                    if not mirror_facing_conflict and not mirror_craft_stack_conflict:
                        # Calculate mirrored output position
                        mirror_col_off, mirror_row_off = get_output_direction(mirrored_goal_type)
                        mirror_output_pos = f"{mirror_col + mirror_col_off}_{mirror_row + mirror_row_off}"

                        # Place mirrored goal
                        placed_positions.add(mirror_pos)
                        output_positions.add(mirror_output_pos)
                        goal_positions_info.append((mirror_pos, mirrored_goal_type))

                        self._place_goal_tile(tiles, mirror_pos, mirrored_goal_type, goal_count)

                        # CRITICAL: Clear tiles from lower layers at mirrored goal position
                        for i in range(top_layer_idx):
                            lower_layer_key = f"layer_{i}"
                            lower_tiles = level.get(lower_layer_key, {}).get("tiles", {})
                            if mirror_pos in lower_tiles:
                                del lower_tiles[mirror_pos]
                                level[lower_layer_key]["num"] = str(len(lower_tiles))
                                logger.debug(f"[_add_goals] Cleared tile at {lower_layer_key}:{mirror_pos} for mirrored goal visibility")

                        # CRITICAL: Clear tiles from ALL layers at mirrored output position
                        for i in range(level.get("layer", 8)):
                            check_layer_key = f"layer_{i}"
                            check_tiles = level.get(check_layer_key, {}).get("tiles", {})
                            if mirror_output_pos in check_tiles:
                                del check_tiles[mirror_output_pos]
                                level[check_layer_key]["num"] = str(len(check_tiles))
                                logger.debug(f"[_add_goals] Cleared tile at {check_layer_key}:{mirror_output_pos} for mirrored goal output")
            else:
                logger.warning(f"[_add_goals] Could not find position for {goal_type}")

        # Update tile count
        level[layer_key]["num"] = str(len(tiles))

        # Set goalCount for the level - ONLY include goals that were actually placed
        # Build goalCount from successfully placed tiles, not from requested goals
        goalCount = {}
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) > 0:
                tile_type = tile_data[0]
                # Check if it's a craft/stack goal tile
                if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                    # Extract count from tile_data[2]
                    tile_count = self.MIN_GOAL_COUNT  # Default to minimum
                    if len(tile_data) > 2:
                        extra = tile_data[2]
                        if isinstance(extra, list) and len(extra) > 0:
                            tile_count = max(self.MIN_GOAL_COUNT, int(extra[0]) if extra[0] else self.MIN_GOAL_COUNT)
                        elif isinstance(extra, (int, float)):
                            tile_count = max(self.MIN_GOAL_COUNT, int(extra))
                    goalCount[tile_type] = goalCount.get(tile_type, 0) + tile_count

        # Warn if not all requested goals were placed
        requested_goals = set()
        for goal in goals:
            base_type = goal.get("type", "craft")
            direction = goal.get("direction") or "s"
            if base_type.endswith(('_s', '_n', '_e', '_w')):
                full_goal_type = base_type
            else:
                full_goal_type = f"{base_type}_{direction}"
            requested_goals.add(full_goal_type)

        placed_goals = set(goalCount.keys())
        missing_goals = requested_goals - placed_goals
        if missing_goals:
            logger.warning(f"Could not place some goals: {missing_goals}. Placed: {placed_goals}")

        level["goalCount"] = goalCount

        return level

    def _adjust_difficulty(
        self, level: Dict[str, Any], target: float, max_tiles: Optional[int] = None, params: Optional["GenerationParams"] = None, tutorial_gimmick: Optional[str] = None
    ) -> Dict[str, Any]:
        """Adjust level to match target difficulty within tolerance.

        Args:
            level: The level to adjust
            target: Target difficulty (0.0-1.0)
            max_tiles: If specified, don't add tiles beyond this count
            params: Generation parameters (for symmetry awareness)
            tutorial_gimmick: Tutorial gimmick type to preserve during adjustment
        """
        analyzer = get_analyzer()
        target_score = target * 100
        symmetry_mode = params.symmetry_mode if params else "none"

        # Track if we've hit tile limit - need to use obstacles
        tiles_maxed_out = False
        # Track consecutive no-change iterations
        no_change_count = 0
        last_score = None

        for iteration in range(self.MAX_ADJUSTMENT_ITERATIONS):
            report = analyzer.analyze(level)
            current_score = report.score
            diff = target_score - current_score

            if abs(diff) <= self.DIFFICULTY_TOLERANCE:
                break

            # Check if score isn't changing (stuck)
            if last_score is not None and abs(current_score - last_score) < 0.1:
                no_change_count += 1
                if no_change_count >= 3:
                    # Score is stuck, need to use obstacles to increase further
                    tiles_maxed_out = True
            else:
                no_change_count = 0
            last_score = current_score

            if diff > 0:
                # Need to increase difficulty
                # If max_tiles is set, check if we can add more tiles
                if max_tiles is not None:
                    current_tiles = sum(
                        len(level.get(f"layer_{i}", {}).get("tiles", {}))
                        for i in range(level.get("layer", 8))
                    )
                    if current_tiles >= max_tiles:
                        tiles_maxed_out = True

                # Pass target difficulty to enable aggressive obstacle addition for high targets
                level = self._increase_difficulty(level, params, tiles_maxed_out=tiles_maxed_out, target_difficulty=target)
            else:
                # Need to decrease difficulty - pass target for aggressive reduction at low targets
                # Also pass tutorial_gimmick to preserve it during obstacle removal
                level = self._decrease_difficulty(level, params, target_difficulty=target, tutorial_gimmick=tutorial_gimmick)

        return level

    def _increase_difficulty(self, level: Dict[str, Any], params: Optional["GenerationParams"] = None, tiles_maxed_out: bool = False, target_difficulty: float = 0.5) -> Dict[str, Any]:
        """Apply a random modification to increase difficulty.

        When tiles are maxed out or target difficulty is high, adds obstacles
        (chain, frog, ice) to increase difficulty. This allows generating B, C, D grade levels.

        Strategy based on target_difficulty:
        - target < 0.4 (S/A grade): Primarily add tiles
        - target >= 0.4 (B grade): Mix of tiles and obstacles (50% chance each)
        - target >= 0.6 (C grade): Primarily obstacles, multiple per iteration
        - target >= 0.8 (D grade): Aggressive obstacle addition, activate more layers
        """
        symmetry_mode = params.symmetry_mode if params else "none"

        # Check gimmick_intensity - if 0, don't add obstacles, only add tiles
        # For values between 0 and 1, use as probability multiplier
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0) if params else 1.0

        # Also check obstacle_types - if empty list, no obstacles should be added
        # This respects the gimmick unlock system where certain levels have no unlocked gimmicks
        obstacle_types = getattr(params, 'obstacle_types', None) if params else None
        obstacles_disabled = gimmick_intensity <= 0 or (obstacle_types is not None and len(obstacle_types) == 0)

        # Obstacle addition actions - filter by allowed obstacle types
        # NOTE: link, grass, bomb, curtain, teleport are NOT in this list because they:
        # - Are added during initial generation (_add_obstacles)
        # - Require special placement rules (pairs, neighbors, etc.)
        # - Should not be randomly added during difficulty adjustment
        all_obstacle_actions = {
            "chain": self._add_chain_to_tile,
            "frog": self._add_frog_to_tile,
            "ice": self._add_ice_to_tile,
            "unknown": self._add_unknown_to_tile,
        }
        # If obstacle_types is specified, only allow those actions
        if obstacle_types is not None and len(obstacle_types) > 0:
            obstacle_actions = [all_obstacle_actions[t] for t in obstacle_types if t in all_obstacle_actions]
        else:
            obstacle_actions = list(all_obstacle_actions.values())

        # If no valid obstacle actions available, mark obstacles as disabled for this adjustment
        if not obstacle_actions:
            obstacles_disabled = True

        # Helper: check if we should add obstacles based on gimmick_intensity probability
        def should_add_obstacle() -> bool:
            if obstacles_disabled:
                return False
            if gimmick_intensity >= 1.0:
                return True
            # For values 0 < gimmick_intensity < 1, use as probability
            return random.random() < gimmick_intensity

        # For low gimmick_intensity (< 0.5), prefer adding tiles over obstacles
        # This ensures early levels have minimal gimmicks
        prefer_tiles_over_obstacles = gimmick_intensity < 0.5

        # Tile Buster style: Very conservative gimmick addition
        # - Primary difficulty comes from tiles and layers, not obstacles
        # - Obstacles are added very sparingly (10-20% chance)
        # - Skip obstacle addition if already at target gimmick percentage

        # Count current gimmicks to cap at ~15% of total tiles
        total_tiles = 0
        total_gimmicks = 0
        for layer_idx in range(8):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            total_tiles += len(tiles)
            for tile_data in tiles.values():
                if len(tile_data) > 1 and tile_data[1]:
                    total_gimmicks += 1

        # Cap gimmicks based on target difficulty
        # Low difficulty (S/A): 15% cap
        # Medium difficulty (B): 25% cap
        # High difficulty (C/D): 40% cap
        if target_difficulty >= 0.6:
            max_gimmick_ratio = 0.40
        elif target_difficulty >= 0.4:
            max_gimmick_ratio = 0.25
        else:
            max_gimmick_ratio = 0.15
        max_gimmicks = int(total_tiles * max_gimmick_ratio)
        gimmicks_capped = total_gimmicks >= max_gimmicks

        # D grade (target >= 0.8): Add obstacles aggressively (70% chance)
        if target_difficulty >= 0.8:
            if prefer_tiles_over_obstacles and not tiles_maxed_out:
                if symmetry_mode == "none":
                    return self._add_tile_to_layer(level)
            elif not gimmicks_capped and random.random() < 0.70 and should_add_obstacle():
                action = random.choice(obstacle_actions)
                return action(level)
            if symmetry_mode == "none" and not tiles_maxed_out:
                return self._add_tile_to_layer(level)

        # C grade (target >= 0.6): Add obstacles frequently (50% chance)
        if target_difficulty >= 0.6:
            if prefer_tiles_over_obstacles and not tiles_maxed_out:
                if symmetry_mode == "none":
                    return self._add_tile_to_layer(level)
            elif not gimmicks_capped and random.random() < 0.50 and should_add_obstacle():
                action = random.choice(obstacle_actions)
                return action(level)

        # B grade (target >= 0.4): Add obstacles moderately (30% chance)
        if target_difficulty >= 0.4:
            if prefer_tiles_over_obstacles:
                if symmetry_mode == "none" and not tiles_maxed_out:
                    return self._add_tile_to_layer(level)
            elif not gimmicks_capped and random.random() < 0.30 and should_add_obstacle():
                action = random.choice(obstacle_actions)
                return action(level)

        # If tiles are maxed out, add obstacles sparingly (20% chance, if not capped)
        if tiles_maxed_out and not gimmicks_capped and random.random() < 0.2 and should_add_obstacle():
            action = random.choice(obstacle_actions)
            return action(level)

        # For symmetric patterns, skip random tile addition to preserve symmetry
        if symmetry_mode != "none":
            return level

        # Default: add tiles (for S/A grade targets)
        return self._add_tile_to_layer(level)

    def _decrease_difficulty(self, level: Dict[str, Any], params: Optional["GenerationParams"] = None, target_difficulty: float = 0.5, tutorial_gimmick: Optional[str] = None) -> Dict[str, Any]:
        """Apply a random modification to decrease difficulty.

        Strategy based on target_difficulty:
        - target >= 0.4: Remove 1 tile (gentle reduction)
        - target >= 0.2 (A grade): Remove 1-2 tiles, possibly remove obstacle
        - target < 0.2 (S grade): Aggressively remove 2-3 tiles and obstacles

        Args:
            level: Level data
            params: Generation parameters
            target_difficulty: Target difficulty score
            tutorial_gimmick: Tutorial gimmick type to preserve (don't remove this type)
        """
        symmetry_mode = params.symmetry_mode if params else "none"
        # For symmetric patterns, skip random tile removal to preserve symmetry
        if symmetry_mode != "none":
            return level

        # S grade (target < 0.2): Very aggressive - remove multiple tiles and obstacles
        if target_difficulty < 0.2:
            # Remove 2-3 tiles per iteration
            num_removals = random.randint(2, 3)
            for _ in range(num_removals):
                level = self._remove_tile_from_layer(level)
            # Also try to remove obstacles if any exist (but preserve tutorial gimmick)
            if random.random() < 0.7:
                level = self._remove_random_obstacle(level, tutorial_gimmick=tutorial_gimmick)
            return level

        # A grade (target < 0.4): Moderate reduction
        if target_difficulty < 0.4:
            # Remove 1-2 tiles
            num_removals = random.randint(1, 2)
            for _ in range(num_removals):
                level = self._remove_tile_from_layer(level)
            # Sometimes remove obstacles (but preserve tutorial gimmick)
            if random.random() < 0.3:
                level = self._remove_random_obstacle(level, tutorial_gimmick=tutorial_gimmick)
            return level

        # Default: gentle reduction - remove 1 tile
        return self._remove_tile_from_layer(level)

    def _remove_random_obstacle(self, level: Dict[str, Any], tutorial_gimmick: Optional[str] = None) -> Dict[str, Any]:
        """Remove a random obstacle (chain, frog, ice) from the level.

        Args:
            level: Level data
            tutorial_gimmick: Tutorial gimmick type to preserve (don't remove this type)
        """
        num_layers = level.get("layer", 8)

        # Find all tiles with obstacles (excluding tutorial gimmick type)
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (isinstance(tile_data, list) and len(tile_data) >= 2
                    and tile_data[1] in ["chain", "frog", "ice"]):
                    # Skip if this is the tutorial gimmick type
                    if tutorial_gimmick and tile_data[1] == tutorial_gimmick:
                        continue
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = ""

        return level

    def _add_chain_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add chain attribute to a random tile.
        RULE: Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT (same row).
        The neighbor must NOT be covered by upper layers (so it can be selected first).
        Chain is released by clearing adjacent tiles on the left or right side.
        """
        num_layers = level.get("layer", 8)

        # Collect candidates: tiles without attributes that have a clearable LEFT or RIGHT neighbor
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Skip if already has attribute or is goal tile
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue
                if tile_data[1] or tile_data[0] in self.GOAL_TYPES:
                    continue

                # Check if has clearable neighbor on LEFT or RIGHT
                try:
                    # Position format is "col_row" (x_y)
                    col, row = map(int, pos.split('_'))
                except:
                    continue

                # Only check LEFT (col-1) and RIGHT (col+1) neighbors (on screen)
                neighbors = [
                    (col-1, row),  # Left (on screen)
                    (col+1, row),  # Right (on screen)
                ]

                has_clearable_neighbor = False
                for ncol, nrow in neighbors:
                    npos = f"{ncol}_{nrow}"
                    if npos in tiles:
                        ndata = tiles[npos]
                        # Clearable = no obstacle or frog only
                        if (isinstance(ndata, list) and len(ndata) >= 2 and
                            (not ndata[1] or ndata[1] == "frog") and
                            ndata[0] not in self.GOAL_TYPES):
                            # CRITICAL: Neighbor must NOT be covered by upper layers
                            if not self._is_position_covered_by_upper(level, i, ncol, nrow):
                                has_clearable_neighbor = True
                                break

                if has_clearable_neighbor:
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "chain"

        return level

    def _add_frog_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add frog attribute to a random tile.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.

        [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        """
        MAX_FROGS_PER_LEVEL = 3

        # Count existing frogs
        num_layers = level.get("layer", 8)
        current_frog_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1] == "frog":
                    current_frog_count += 1

        # Don't add if already at max
        if current_frog_count >= MAX_FROGS_PER_LEVEL:
            logger.debug(f"[FROG] _add_frog_to_tile: Skipping - already at max {MAX_FROGS_PER_LEVEL} frogs")
            return level

        # Collect all tiles without attributes that are NOT covered by upper layers
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    # Check if position is covered by upper layers
                    try:
                        col, row = map(int, pos.split('_'))
                        if not self._is_position_covered_by_upper(level, i, col, row):
                            candidates.append((layer_key, pos))
                    except:
                        continue

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "frog"
            logger.debug(f"[FROG] _add_frog_to_tile: Added frog at {layer_key}/{pos}")

        return level

    def _add_ice_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add ice attribute to a random tile.

        Ice tiles require 2 taps to clear: first tap removes ice, second tap clears tile.
        Ice is a good difficulty modifier as it doesn't require neighbor rules like chain.
        """
        return self._add_attribute_to_tile(level, "ice")

    def _add_unknown_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add unknown attribute to a random tile.

        RULE: Unknown tiles should be placed on tiles that ARE covered by upper layers.
        This is because the unknown effect only works when the tile is hidden by upper tiles.
        When upper tiles are removed, the tile type becomes visible.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles without attributes that ARE covered by upper layers
        candidates = []
        for i in range(num_layers - 1):  # Exclude top layer (no upper layers to cover)
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    try:
                        col, row = map(int, pos.split('_'))
                        # Only add to tiles covered by upper layers
                        if self._is_position_covered_by_upper(level, i, col, row):
                            candidates.append((layer_key, pos))
                    except:
                        continue

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "unknown"

        return level

    def _add_attribute_to_tile(
        self, level: Dict[str, Any], attribute: str
    ) -> Dict[str, Any]:
        """Add an attribute to a random tile without one."""
        num_layers = level.get("layer", 8)

        # Collect all tiles without attributes
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = attribute

        return level

    def _remove_chain_from_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove chain attribute from a random tile."""
        return self._remove_attribute_from_tile(level, "chain")

    def _remove_frog_from_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove frog attribute from a random tile."""
        return self._remove_attribute_from_tile(level, "frog")

    def _validate_and_fix_frog_positions(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and fix frog positions to ensure they are not covered by upper layers.

        RULE: Frogs must be immediately selectable when the level spawns.
        This function should be called AFTER all tile modifications to ensure no frog
        is covered by tiles added in later generation steps.

        Covered frogs are removed (attribute cleared) as there's no safe place to move them
        that wouldn't violate placement rules or break tile count divisibility.
        """
        num_layers = level.get("layer", 8)
        removed_count = 0

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                # Check if this is a frog tile
                if tile_data[1] != "frog":
                    continue

                # Check if covered by upper layers
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, layer_idx, col, row):
                        # Remove frog attribute from covered tile
                        tile_data[1] = ""
                        removed_count += 1
                        logger.warning(
                            f"[FROG FIX] Removed frog at {layer_key}/{pos} - covered by upper layer"
                        )
                except Exception as e:
                    logger.warning(f"[FROG FIX] Error checking position {pos}: {e}")
                    continue

        if removed_count > 0:
            logger.info(f"[FROG FIX] Removed {removed_count} covered frogs from level")

        return level

    def _remove_attribute_from_tile(
        self, level: Dict[str, Any], attribute: str
    ) -> Dict[str, Any]:
        """Remove a specific attribute from a random tile."""
        num_layers = level.get("layer", 8)

        # Find tiles with the attribute
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and tile_data[1] == attribute
                ):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = ""

        return level

    def _add_tile_to_layer(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new tile to a random layer that already has tiles.

        Uses tiles that respect the level's useTileCount setting.
        Only adds to layers that already have tiles (respects user's layer config).
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Collect existing tile types from level to match user's selection
        # IMPORTANT: Exclude goal types (craft_s, stack_s, etc.) - they should only be added via _add_goals
        existing_tile_types = set()
        for i in range(num_layers):
            layer_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            for tile_data in layer_tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    # Exclude goal types and craft/stack tiles
                    if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available, otherwise fall back to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_types = list(existing_tile_types)
        else:
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Find layers that already have tiles (respect user's layer config)
        active_layer_indices = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layer_indices.append(i)

        if not active_layer_indices:
            return level

        # Find a layer with tiles but with available positions
        for _ in range(10):  # Try up to 10 times
            # Only use layers that already have tiles
            layer_idx = random.choice(active_layer_indices)
            layer_key = f"layer_{layer_idx}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            cols = int(layer_data.get("col", 7))
            rows = int(layer_data.get("row", 7))

            # Find available position
            for _ in range(20):
                x = random.randint(0, cols - 1)
                y = random.randint(0, rows - 1)
                pos = f"{x}_{y}"

                if pos not in tiles:
                    tile_type = random.choice(valid_tile_types)
                    self._place_tile(tiles, pos, tile_type, "")
                    level[layer_key]["num"] = str(len(tiles))
                    return level

        return level

    def _remove_tile_from_layer(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a tile from a random layer.

        IMPORTANT: Do not remove tiles that are neighbors of chain/link/grass obstacles,
        as this would make them impossible to clear.
        """
        num_layers = level.get("layer", 8)

        # Find layers with tiles that can be removed
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Don't remove goal tiles
                if not isinstance(tile_data, list) or tile_data[0] in self.GOAL_TYPES:
                    continue

                # Don't remove tiles with obstacles
                if len(tile_data) >= 2 and tile_data[1]:
                    continue

                # Check if this tile is a neighbor of a chain (left or right on screen)
                # If removed, the chain would have no clearable neighbor
                try:
                    # Position format is "col_row" (x_y)
                    col, row = map(int, pos.split('_'))
                except:
                    continue

                is_critical_neighbor = False

                # Check if left neighbor (col-1) is chain (on screen)
                left_pos = f"{col-1}_{row}"
                if left_pos in tiles:
                    left_data = tiles[left_pos]
                    if isinstance(left_data, list) and len(left_data) >= 2 and left_data[1] == "chain":
                        # Check if chain has other clearable neighbor (left side = col-2)
                        other_side = f"{col-2}_{row}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                # Check if right neighbor (col+1) is chain (on screen)
                right_pos = f"{col+1}_{row}"
                if right_pos in tiles:
                    right_data = tiles[right_pos]
                    if isinstance(right_data, list) and len(right_data) >= 2 and right_data[1] == "chain":
                        # Check if chain has other clearable neighbor (right side = col+2)
                        other_side = f"{col+2}_{row}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                if not is_critical_neighbor:
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            del level[layer_key]["tiles"][pos]
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        return level

    def _increase_goal_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Increase the count of a random goal."""
        return self._modify_goal_count(level, 1)

    def _decrease_goal_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Decrease the count of a random goal."""
        return self._modify_goal_count(level, -1)

    def _modify_goal_count(self, level: Dict[str, Any], delta: int) -> Dict[str, Any]:
        """Modify a goal's count by delta."""
        num_layers = level.get("layer", 8)

        # Find goal tiles
        goals = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 3
                    and tile_data[0] in self.GOAL_TYPES
                ):
                    goals.append((layer_key, pos))

        if goals:
            layer_key, pos = random.choice(goals)
            tile_data = level[layer_key]["tiles"][pos]

            if len(tile_data) >= 3 and isinstance(tile_data[2], list):
                # Minimum 3 tiles for craft/stack gimmicks (match-3 game rule)
                new_count = max(3, tile_data[2][0] + delta)
                tile_data[2][0] = new_count

        return level

    def _fix_goal_counts(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Fix any goals with count below MIN_GOAL_COUNT and ensure total is divisible by 3.

        This is a safety net to ensure all craft/stack goals have at least
        MIN_GOAL_COUNT tiles, regardless of how they were created.
        Also ensures total matchable tiles (regular + goal internal) is divisible by 3.
        """
        num_layers = level.get("layer", 8)
        fixed_count = 0

        # Step 1: Fix all goals to minimum count
        goal_tiles: List[Tuple[int, str, list]] = []  # (layer_idx, pos, tile_data)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 1:
                    continue

                tile_type = tile_data[0]
                if not isinstance(tile_type, str):
                    continue

                # Check if it's a goal tile
                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                    # Ensure tile_data has the count array
                    if len(tile_data) < 3:
                        # Add count array if missing
                        while len(tile_data) < 2:
                            tile_data.append("")
                        tile_data.append([self.MIN_GOAL_COUNT])
                        fixed_count += 1
                        logger.debug(f"[_fix_goal_counts] Added missing count at {layer_key}:{pos}")
                    elif isinstance(tile_data[2], list) and len(tile_data[2]) > 0:
                        current_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                        if current_count < self.MIN_GOAL_COUNT:
                            tile_data[2][0] = self.MIN_GOAL_COUNT
                            fixed_count += 1
                            logger.warning(f"[_fix_goal_counts] Fixed count {current_count} -> {self.MIN_GOAL_COUNT} at {layer_key}:{pos}")
                    else:
                        # Count array is empty or invalid
                        tile_data[2] = [self.MIN_GOAL_COUNT]
                        fixed_count += 1
                        logger.debug(f"[_fix_goal_counts] Fixed invalid count array at {layer_key}:{pos}")

                    goal_tiles.append((i, pos, tile_data))

        # Step 2: Count total matchable tiles
        total_matchable = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        # Count internal tiles only, not the box itself
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            total_matchable += internal_count
                    else:
                        total_matchable += 1

        # Step 3: Ensure goal internal tiles (t0) are divisible by 3
        # CRITICAL: Goal internal tiles become t0 when output, so t0 must be divisible by 3
        t0_count = 0
        for layer_idx, pos, tile_data in goal_tiles:
            if isinstance(tile_data[2], list) and tile_data[2]:
                t0_count += int(tile_data[2][0])

        t0_remainder = t0_count % 3
        if t0_remainder != 0 and goal_tiles:
            # Need to add (3 - remainder) internal tiles to make t0 divisible by 3
            tiles_to_add_t0 = 3 - t0_remainder  # 1 or 2

            # Add to goal counts (prefer spreading across multiple goals)
            goal_idx = 0
            while tiles_to_add_t0 > 0 and goal_tiles:
                layer_idx, pos, tile_data = goal_tiles[goal_idx % len(goal_tiles)]
                if isinstance(tile_data[2], list) and tile_data[2]:
                    tile_data[2][0] = int(tile_data[2][0]) + 1
                    tiles_to_add_t0 -= 1
                    total_matchable += 1
                    t0_count += 1
                    logger.info(f"[_fix_goal_counts] Added +1 to goal at layer_{layer_idx}:{pos} for t0 divisibility")
                goal_idx += 1
                # Safety: prevent infinite loop
                if goal_idx > len(goal_tiles) * 3:
                    break

            logger.info(f"[_fix_goal_counts] Adjusted goal internals (t0) to {t0_count} (divisible by 3)")

        # Step 4: Total divisibility will be handled by _ensure_tile_count_divisible_by_3
        # DO NOT add more to goals here - that would break t0 divisibility
        # If t0 is divisible by 3 and regular tiles are divisible by 3, total will also be divisible by 3

        # Step 4: Recalculate goalCount
        goalCount = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            tile_count = int(tile_data[2][0])
                        else:
                            tile_count = self.MIN_GOAL_COUNT
                        goalCount[tile_type] = goalCount.get(tile_type, 0) + tile_count

        level["goalCount"] = goalCount

        if fixed_count > 0 or t0_remainder != 0:
            logger.info(f"[_fix_goal_counts] Final goalCount: {goalCount}, total matchable: {total_matchable}")

        return level

    def _relocate_tiles_from_goal_outputs(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relocate tiles from goal (craft/stack) output positions to other valid positions.

        CRITICAL: This must be called AFTER all tile modifications to ensure
        no tiles exist in stack/craft output positions. Stack and craft gimmicks
        spawn tiles at their output positions, so existing tiles would block them.

        Unlike deletion, this function RELOCATES tiles to maintain tile counts.

        Direction rules:
        - craft_s / stack_s: outputs to row+1 (south)
        - craft_n / stack_n: outputs to row-1 (north)
        - craft_e / stack_e: outputs to col+1 (east)
        - craft_w / stack_w: outputs to col-1 (west)
        """
        num_layers = level.get("layer", 8)
        grid_width = level.get("gridWidth", 7)
        grid_height = level.get("gridHeight", 7)

        # Collect all goal output positions (positions that must be clear)
        goal_output_positions = set()
        goal_positions = set()
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or not tile_data:
                    continue
                tile_type = tile_data[0]
                if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                    continue

                goal_positions.add(pos)

                # Calculate output position based on direction
                col, row = map(int, pos.split("_"))
                direction = tile_type[-1]
                if direction == 's':
                    output_pos = f"{col}_{row + 1}"
                elif direction == 'n':
                    output_pos = f"{col}_{row - 1}"
                elif direction == 'e':
                    output_pos = f"{col + 1}_{row}"
                elif direction == 'w':
                    output_pos = f"{col - 1}_{row}"
                else:
                    continue

                goal_output_positions.add(output_pos)

        if not goal_output_positions:
            return level

        # Collect tiles that need to be relocated
        tiles_to_relocate = []  # [(layer_idx, pos, tile_data)]
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos in list(tiles.keys()):
                if pos in goal_output_positions:
                    tile_data = tiles[pos]
                    # Only relocate regular tiles, not goals themselves
                    if isinstance(tile_data, list) and tile_data:
                        tile_type = tile_data[0]
                        if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                            tiles_to_relocate.append((i, pos, tile_data))

        if not tiles_to_relocate:
            return level

        # Remove tiles from their current positions
        for layer_idx, pos, _ in tiles_to_relocate:
            layer_key = f"layer_{layer_idx}"
            del level[layer_key]["tiles"][pos]
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Find valid positions for relocation
        relocated_count = 0
        for layer_idx, old_pos, tile_data in tiles_to_relocate:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]

            # Collect occupied positions in this layer
            occupied_positions = set(tiles.keys())

            # Find a valid new position
            new_pos = None
            for row in range(grid_height):
                for col in range(grid_width):
                    candidate_pos = f"{col}_{row}"
                    # Must not be occupied, must not be goal output position, must not be goal position
                    if (candidate_pos not in occupied_positions and
                        candidate_pos not in goal_output_positions and
                        candidate_pos not in goal_positions):
                        new_pos = candidate_pos
                        break
                if new_pos:
                    break

            if new_pos:
                # Place tile at new position
                tiles[new_pos] = tile_data
                level[layer_key]["num"] = str(len(tiles))
                relocated_count += 1
                logger.debug(f"[_relocate_tiles_from_goal_outputs] Relocated {layer_key}:{old_pos} → {new_pos}")
            else:
                # If no valid position found, try another layer
                for alt_layer_idx in range(num_layers):
                    if alt_layer_idx == layer_idx:
                        continue
                    alt_layer_key = f"layer_{alt_layer_idx}"
                    alt_tiles = level.get(alt_layer_key, {}).get("tiles", {})
                    alt_occupied = set(alt_tiles.keys())

                    for row in range(grid_height):
                        for col in range(grid_width):
                            candidate_pos = f"{col}_{row}"
                            if (candidate_pos not in alt_occupied and
                                candidate_pos not in goal_output_positions and
                                candidate_pos not in goal_positions):
                                new_pos = candidate_pos
                                break
                        if new_pos:
                            break

                    if new_pos:
                        alt_tiles[new_pos] = tile_data
                        level[alt_layer_key]["num"] = str(len(alt_tiles))
                        relocated_count += 1
                        logger.debug(f"[_relocate_tiles_from_goal_outputs] Relocated {layer_key}:{old_pos} → {alt_layer_key}:{new_pos}")
                        break

                if not new_pos:
                    # Last resort: log warning (tile count will be off)
                    logger.warning(f"[_relocate_tiles_from_goal_outputs] Could not relocate tile from {layer_key}:{old_pos}")

        if relocated_count > 0:
            logger.info(f"[_relocate_tiles_from_goal_outputs] Relocated {relocated_count} tiles from goal output positions")

        return level

    def _ensure_tile_count_divisible_by_3(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """
        Ensure EACH tile type count is divisible by 3 for match-3 completion.

        CRITICAL FIX: Not just total count, but EACH TYPE must be divisible by 3!
        Example: If we have 4x t0, 5x t1, 3x t2 (total 12, divisible by 3)
                 But t0=4 (not divisible), t1=5 (not divisible) -> UNPLAYABLE!

        This function adjusts tile types to ensure each has count divisible by 3.

        Also ensures all tiles are within useTileCount range (t0~t{useTileCount}).

        CRITICAL: First ensures TOTAL matchable tiles is divisible by 3 by adjusting
        craft_s internal tile counts if necessary.
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Collect existing tile types from level to match user's selection
        existing_tile_types = set()
        for i in range(num_layers):
            layer_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            for tile_data in layer_tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    if tile_type.startswith("t") and tile_type not in self.GOAL_TYPES:
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available, otherwise fall back to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_set = existing_tile_types
            valid_tile_types = list(existing_tile_types)
        else:
            valid_tile_set = {f"t{i}" for i in range(1, use_tile_count + 1)}
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Step 0: Convert out-of-range tiles to valid range
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Skip goal tiles (craft_s, craft_n, craft_e, craft_w, stack_s, etc.)
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        continue
                    # Check if tile type is out of valid range
                    if tile_type.startswith("t") and tile_type not in valid_tile_set:
                        # Convert to a random valid tile type
                        tile_data[0] = random.choice(valid_tile_types)

        # Step 0.5: Ensure TOTAL matchable tiles is divisible by 3
        # This is CRITICAL - if total is not divisible by 3, we can't make all types divisible
        # Count regular tiles on grid + internal tiles in craft/stack
        total_matchable = 0
        goal_tiles_with_internal: List[Tuple[int, str, list]] = []  # (layer_idx, pos, tile_data)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles for goal tiles (craft/stack)
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            total_matchable += internal_count
                            goal_tiles_with_internal.append((i, pos, tile_data))
                    else:
                        total_matchable += 1

        # Adjust total to be divisible by 3 (NOT modifying goal counts)
        # User-specified goal internal counts should be preserved
        # Strategy: Try to add tiles first, if not possible then remove tiles
        # CRITICAL: For symmetric patterns, we must add/remove tiles symmetrically!
        total_remainder = total_matchable % 3
        tiles_were_removed = False  # Track if we removed tiles for total adjustment
        symmetry_mode = params.symmetry_mode or "none"

        if total_remainder != 0:
            cols, rows = params.grid_size

            # First, try to add tiles (3 - remainder tiles needed)
            tiles_to_add = 3 - total_remainder
            added_count = 0

            # For symmetric patterns, we need to add/remove tiles to reach divisible by 3
            # Strategy: Since symmetric addition is complex, use tile type redistribution
            # If redistribution fails, we'll use _force_fix_tile_counts later
            if symmetry_mode in ("horizontal", "vertical", "both"):
                # For symmetric patterns, try to remove tiles to make total divisible
                # Remove remainder tiles (1 or 2) from center positions or paired positions
                cols, rows = params.grid_size

                # Find removable tiles (regular tiles without special attributes)
                removable: List[Tuple[int, str, str]] = []  # (layer_idx, pos, tile_type)
                for i in range(num_layers):
                    layer_key = f"layer_{i}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) >= 2:
                            tile_type = tile_data[0]
                            attribute = tile_data[1] if len(tile_data) > 1 else ""
                            if (tile_type not in self.GOAL_TYPES and
                                not tile_type.startswith("craft_") and
                                not tile_type.startswith("stack_") and
                                not attribute):
                                removable.append((i, pos, tile_type))

                # Sort by position to prefer edge tiles (less impactful)
                random.shuffle(removable)

                # Remove tiles to make total divisible by 3
                tiles_to_remove = total_remainder  # 1 or 2
                removed_count = 0
                for layer_idx, pos, _ in removable[:tiles_to_remove]:
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1
                        if removed_count >= tiles_to_remove:
                            break

                if removed_count > 0:
                    tiles_were_removed = True
                    logger.debug(f"[_ensure_tile_count_divisible_by_3] Removed {removed_count} tiles for symmetric level divisibility")
            else:
                for i in range(num_layers):
                    if added_count >= tiles_to_add:
                        break
                    layer_key = f"layer_{i}"
                    layer_data = level.get(layer_key, {})
                    tiles = layer_data.get("tiles", {})
                    if not tiles:
                        continue

                    is_odd_layer = i % 2 == 1
                    layer_cols = cols if is_odd_layer else cols + 1
                    layer_rows = rows if is_odd_layer else rows + 1

                    all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
                    used_positions = set(tiles.keys())

                    for pos in all_positions:
                        if added_count >= tiles_to_add:
                            break
                        if pos not in used_positions:
                            # Add a t1 tile to this position (t0 is excluded)
                            level[layer_key]["tiles"][pos] = ["t1", ""]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            added_count += 1

            # If adding tiles failed (no available positions), remove tiles instead
            # If remainder=1, remove 1 tile. If remainder=2, remove 2 tiles.
            # CRITICAL: For symmetric patterns, we SKIP removal to preserve symmetry!
            if added_count < tiles_to_add and symmetry_mode == "none":
                tiles_to_remove = total_remainder  # 1 or 2
                removed_count = 0

                # Collect removable tiles (regular tiles without attributes, not goals)
                removable_tiles: List[Tuple[int, str]] = []
                for i in range(num_layers):
                    layer_key = f"layer_{i}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) >= 2:
                            tile_type = tile_data[0]
                            attribute = tile_data[1] if len(tile_data) > 1 else ""
                            # Only remove regular tiles without attributes (not goal tiles)
                            if (tile_type not in self.GOAL_TYPES and
                                not tile_type.startswith("craft_") and
                                not tile_type.startswith("stack_") and
                                not attribute):
                                removable_tiles.append((i, pos))

                # Remove tiles from the end of the list (less impactful positions)
                random.shuffle(removable_tiles)
                for layer_idx, pos in removable_tiles[:tiles_to_remove]:
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1
                        if removed_count >= tiles_to_remove:
                            break

                if removed_count > 0:
                    tiles_were_removed = True

        # Step 1: Count each tile type across all layers
        # IMPORTANT: Also count internal tiles in craft/stack containers as t0
        type_counts: Dict[str, int] = {}
        type_positions: Dict[str, List[Tuple[int, str]]] = {}  # type -> [(layer_idx, pos), ...]

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # For craft/stack tiles, count internal tiles as t0
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # [count] = number of internal t0 tiles
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts["t0"] = type_counts.get("t0", 0) + internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        if not type_counts:
            return level

        # Step 2: Find types that need adjustment
        # Strategy: Reassign tiles from types with remainder to types that need more
        types_needing_add = []  # (type, tiles_needed) - needs 1 or 2 more to reach multiple of 3
        types_with_excess = []  # (type, excess_count, positions) - has 1 or 2 extra

        for tile_type, count in type_counts.items():
            remainder = count % 3
            if remainder == 0:
                continue
            elif remainder == 1:
                # Need 2 more, or remove 1
                types_needing_add.append((tile_type, 2))
            else:  # remainder == 2
                # Need 1 more, or remove 2
                types_needing_add.append((tile_type, 1))

        if not types_needing_add:
            return level

        # Step 3: Find available positions to add tiles
        active_layers = []
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layers.append(i)

        if not active_layers:
            return level

        # Collect available positions across all active layers
        available_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)
        cols, rows = params.grid_size

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            is_odd_layer = layer_idx % 2 == 1
            layer_cols = cols if is_odd_layer else cols + 1
            layer_rows = rows if is_odd_layer else rows + 1

            all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
            used_positions = set(tiles.keys())
            for pos in all_positions:
                if pos not in used_positions:
                    available_positions.append((layer_idx, pos))

        # Step 4: Add tiles to reach multiples of 3 for each type
        # IMPORTANT: Skip adding tiles if we already removed tiles for total adjustment
        # Adding tiles would undo the total divisibility fix
        # CRITICAL: For symmetric patterns, skip random tile addition to preserve symmetry!
        if not tiles_were_removed and symmetry_mode == "none":
            for tile_type, tiles_needed in types_needing_add:
                for _ in range(tiles_needed):
                    if not available_positions:
                        break
                    layer_idx, pos = available_positions.pop(0)
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos] = [tile_type, ""]
                    level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Step 5: Final verification - if still have issues, reassign existing tiles
        # Recount after additions (include internal t0 tiles)
        type_counts_final: Dict[str, int] = {}
        type_positions_final: Dict[str, List[Tuple[int, str]]] = {}

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles as t0
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts_final["t0"] = type_counts_final.get("t0", 0) + internal_count
                    else:
                        type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1
                        if tile_type not in type_positions_final:
                            type_positions_final[tile_type] = []
                        type_positions_final[tile_type].append((i, pos))

        # Check if any type still has remainder
        still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        # Keep fixing until all types are divisible by 3 or no more fixes possible
        max_fix_iterations = 10
        fix_iteration = 0

        while still_broken and fix_iteration < max_fix_iterations:
            fix_iteration += 1
            fixed_any = False

            # Separate types by remainder
            rem1_types = [t for t, r in still_broken if r == 1]
            rem2_types = [t for t, r in still_broken if r == 2]

            # Strategy 1: Pair rem1 with rem2 types
            while rem1_types and rem2_types:
                type_a = rem1_types.pop(0)  # remainder 1
                type_b = rem2_types.pop(0)  # remainder 2

                # Move 1 tile from type_a to type_b
                # type_a: -1 → remainder 0
                # type_b: +1 → remainder 0
                if type_a in type_positions_final and type_positions_final[type_a]:
                    layer_idx, pos = type_positions_final[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

            # Strategy 2: Handle 3 types with same remainder
            # 3 types with rem 1: redistribute 1 tile each to balance
            while len(rem1_types) >= 3:
                type_a = rem1_types.pop(0)
                type_b = rem1_types.pop(0)
                type_c = rem1_types.pop(0)

                # Move 1 from type_a to type_b → a:rem0, b:rem2
                # Move 2 from type_b to type_c → b:rem0, c:rem0
                if type_a in type_positions_final and type_positions_final[type_a]:
                    layer_idx, pos = type_positions_final[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

                if type_b in type_positions_final and len(type_positions_final.get(type_b, [])) >= 2:
                    for _ in range(2):
                        layer_idx, pos = type_positions_final[type_b].pop()
                        layer_key = f"layer_{layer_idx}"
                        level[layer_key]["tiles"][pos][0] = type_c
                    fixed_any = True

            # 3 types with rem 2: redistribute 2 tiles each to balance
            while len(rem2_types) >= 3:
                type_a = rem2_types.pop(0)
                type_b = rem2_types.pop(0)
                type_c = rem2_types.pop(0)

                # Move 2 from type_a to type_b → a:rem0, b:rem1
                # Move 1 from type_b to type_c → b:rem0, c:rem0
                if type_a in type_positions_final and len(type_positions_final.get(type_a, [])) >= 2:
                    for _ in range(2):
                        layer_idx, pos = type_positions_final[type_a].pop()
                        layer_key = f"layer_{layer_idx}"
                        level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

                if type_b in type_positions_final and type_positions_final[type_b]:
                    layer_idx, pos = type_positions_final[type_b].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_c
                    fixed_any = True

            if not fixed_any:
                break

            # Recount for next iteration
            type_counts_final = {}
            type_positions_final = {}
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                type_counts_final["t0"] = type_counts_final.get("t0", 0) + internal_count
                        else:
                            type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1
                            if tile_type not in type_positions_final:
                                type_positions_final[tile_type] = []
                            type_positions_final[tile_type].append((i, pos))

            still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        # FINAL STEP: FORCE divisibility by 3
        # If still_broken has any types, it means the total is not divisible by 3
        # or the reassignment strategies failed. Force fix by removing tiles.
        # NOTE: Even for symmetric patterns, we must force fix if redistribution failed
        if still_broken:
            # Recount everything one more time
            total_matchable = 0
            removable_tiles_final: List[Tuple[int, str, str]] = []  # (layer_idx, pos, tile_type)

            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            # Count internal tiles
                            if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                total_matchable += internal_count
                        else:
                            total_matchable += 1
                            # Only add regular tiles without obstacles as removable
                            attr = tile_data[1] if len(tile_data) > 1 else ""
                            if not attr:
                                removable_tiles_final.append((i, pos, tile_type))

            total_remainder = total_matchable % 3
            if total_remainder != 0:
                # We MUST remove tiles to fix the total
                tiles_to_remove = total_remainder  # 1 or 2

                # Sort removable tiles by type - prefer removing from types with remainder
                type_counts_for_sort: Dict[str, int] = {}
                for layer_idx, pos, tile_type in removable_tiles_final:
                    type_counts_for_sort[tile_type] = type_counts_for_sort.get(tile_type, 0) + 1

                # Calculate remainder for each type
                type_remainders = {t: c % 3 for t, c in type_counts_for_sort.items()}

                # Sort: prefer types with remainder matching tiles_to_remove
                # e.g., if we need to remove 1 tile, prefer types with remainder 1
                def sort_key(item: Tuple[int, str, str]) -> Tuple[int, str]:
                    _, _, tile_type = item
                    remainder = type_remainders.get(tile_type, 0)
                    # Priority: exact match > any remainder > no remainder
                    if remainder == tiles_to_remove:
                        return (0, tile_type)
                    elif remainder > 0:
                        return (1, tile_type)
                    else:
                        return (2, tile_type)

                removable_tiles_final.sort(key=sort_key)

                removed_count = 0
                for layer_idx, pos, tile_type in removable_tiles_final:
                    if removed_count >= tiles_to_remove:
                        break
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1

                # After removing tiles for total, we need to re-run type redistribution
                # But now the total IS divisible by 3, so redistribution will work
                if removed_count > 0:
                    # Quick redistribution pass
                    type_counts_final2: Dict[str, int] = {}
                    type_positions_final2: Dict[str, List[Tuple[int, str]]] = {}

                    for i in range(num_layers):
                        layer_key = f"layer_{i}"
                        tiles = level.get(layer_key, {}).get("tiles", {})
                        for pos, tile_data in tiles.items():
                            if isinstance(tile_data, list) and len(tile_data) > 0:
                                tile_type = tile_data[0]
                                if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                                    if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                        internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                        type_counts_final2["t0"] = type_counts_final2.get("t0", 0) + internal_count
                                else:
                                    type_counts_final2[tile_type] = type_counts_final2.get(tile_type, 0) + 1
                                    if tile_type not in type_positions_final2:
                                        type_positions_final2[tile_type] = []
                                    type_positions_final2[tile_type].append((i, pos))

                    # Simple redistribution: pair rem1 with rem2
                    still_broken2 = [(t, c % 3) for t, c in type_counts_final2.items() if c % 3 != 0]
                    rem1_types2 = [t for t, r in still_broken2 if r == 1]
                    rem2_types2 = [t for t, r in still_broken2 if r == 2]

                    while rem1_types2 and rem2_types2:
                        type_a = rem1_types2.pop(0)
                        type_b = rem2_types2.pop(0)
                        if type_a in type_positions_final2 and type_positions_final2[type_a]:
                            layer_idx, pos = type_positions_final2[type_a].pop()
                            layer_key = f"layer_{layer_idx}"
                            if pos in level.get(layer_key, {}).get("tiles", {}):
                                level[layer_key]["tiles"][pos][0] = type_b

        return level

    def _validate_playability(self, level: Dict[str, Any], level_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Validate that a level is playable (can be cleared).

        Rules for playability:
        1. Total matchable tiles must be divisible by 3
        2. Each tile type count must be divisible by 3
        3. Total tiles must meet minimum count (industry standard)
           - Level 1-5 (tutorial): minimum 9 tiles (3 sets)
           - Level 6+: minimum 18 tiles (6 sets)

        Args:
            level: The level data to validate
            level_number: Optional level number for tutorial exception

        Returns:
            Dict with is_playable (bool), total_tiles (int), bad_types (list), below_minimum (bool)
        """
        num_layers = level.get("layer", 8)
        type_counts: Dict[str, int] = {}
        total_matchable = 0

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Count internal tiles for craft/stack
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts["t0"] = type_counts.get("t0", 0) + internal_count
                            total_matchable += internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        total_matchable += 1

        # Check for types with count not divisible by 3
        bad_types = [(t, c) for t, c in type_counts.items() if c % 3 != 0]

        # Check minimum tile count based on level number
        # Tutorial levels (1-5) have lower minimum, regular levels (6+) need more tiles
        is_tutorial = level_number is not None and level_number <= 5
        min_tiles = self.TUTORIAL_MIN_TILE_COUNT if is_tutorial else self.MIN_TILE_COUNT
        below_minimum = total_matchable < min_tiles

        # Level is playable if: no bad types, divisible by 3, and meets minimum
        is_playable = len(bad_types) == 0 and total_matchable % 3 == 0 and not below_minimum

        return {
            "is_playable": is_playable,
            "total_tiles": total_matchable,
            "bad_types": bad_types,
            "type_counts": type_counts,
            "below_minimum": below_minimum,
            "min_required": min_tiles
        }

    def _ensure_minimum_tiles(
        self,
        level: Dict[str, Any],
        params: GenerationParams,
        min_required: int
    ) -> Dict[str, Any]:
        """
        Ensure level has at least the minimum required number of tiles.

        If the level has fewer tiles than required, add tiles to meet minimum.
        Tiles are added in sets of 3 to maintain match-3 game rules.

        Args:
            level: The level data
            params: Generation parameters
            min_required: Minimum number of tiles required

        Returns:
            Updated level with minimum tiles ensured
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Count current tiles
        current_tiles = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            current_tiles += int(tile_data[2][0]) if tile_data[2][0] else 0
                    elif tile_type.startswith("t"):
                        current_tiles += 1

        if current_tiles >= min_required:
            return level

        # Calculate tiles needed (in sets of 3)
        tiles_needed = min_required - current_tiles
        sets_needed = (tiles_needed + 2) // 3  # Round up to sets of 3
        tiles_to_add = sets_needed * 3

        logger.info(f"[_ensure_minimum_tiles] Current: {current_tiles}, Min: {min_required}, Adding: {tiles_to_add}")

        # Get available tile types from existing tiles to preserve t0 if used
        existing_tile_types = set()
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    if tile_type.startswith("t") and not tile_type.startswith("craft_") and not tile_type.startswith("stack_"):
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available (preserves t0), otherwise fallback to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_types = sorted(list(existing_tile_types))
        else:
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Find positions to add tiles (prefer upper layers, avoid existing tiles)
        added = 0
        for layer_idx in range(num_layers - 1, -1, -1):  # Start from top layer
            layer_key = f"layer_{layer_idx}"
            if layer_key not in level:
                level[layer_key] = {"tiles": {}, "col": "8", "row": "8", "num": "0"}

            layer_tiles = level[layer_key].get("tiles", {})
            col = int(level[layer_key].get("col", 8))
            row = int(level[layer_key].get("row", 8))

            # Find empty positions
            for y in range(row):
                for x in range(col):
                    if added >= tiles_to_add:
                        break
                    pos = f"{x}_{y}"
                    if pos not in layer_tiles:
                        # Add tile - distribute types evenly in sets of 3
                        tile_type_idx = (added // 3) % len(valid_tile_types)
                        tile_type = valid_tile_types[tile_type_idx]
                        layer_tiles[pos] = [tile_type, ""]
                        added += 1

                if added >= tiles_to_add:
                    break

            level[layer_key]["tiles"] = layer_tiles
            level[layer_key]["num"] = str(len(layer_tiles))

            if added >= tiles_to_add:
                break

        logger.info(f"[_ensure_minimum_tiles] Added {added} tiles to meet minimum")

        return level

    def _force_fix_tile_counts(self, level: Dict[str, Any], params: GenerationParams) -> Dict[str, Any]:
        """
        Aggressively fix tile counts to ensure playability.
        This is a last-resort function that will force-fix any remaining issues.
        """
        num_layers = level.get("layer", 8)

        # CRITICAL: First fix t0 (goal internals) to be divisible by 3
        # This must happen BEFORE removing regular tiles, because t0 affects total
        goal_tiles = []
        t0_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            t0_count += internal_count
                            goal_tiles.append((i, pos, tile_data))

        t0_remainder = t0_count % 3
        if t0_remainder != 0 and goal_tiles:
            # Add (3 - remainder) to goal internal counts to make t0 divisible by 3
            tiles_to_add = 3 - t0_remainder
            goal_idx = 0
            while tiles_to_add > 0:
                _, _, tile_data = goal_tiles[goal_idx % len(goal_tiles)]
                if isinstance(tile_data[2], list) and tile_data[2]:
                    tile_data[2][0] = int(tile_data[2][0]) + 1
                    tiles_to_add -= 1
                    t0_count += 1
                goal_idx += 1
                if goal_idx > len(goal_tiles) * 3:
                    break

            # Update goalCount
            goalCount = {}
            for _, _, tile_data in goal_tiles:
                tile_type = tile_data[0]
                internal_count = int(tile_data[2][0]) if isinstance(tile_data[2], list) and tile_data[2] else 0
                goalCount[tile_type] = goalCount.get(tile_type, 0) + internal_count
            level["goalCount"] = goalCount

        # Now count all tiles including updated t0
        type_counts: Dict[str, int] = {}
        type_positions: Dict[str, List[Tuple[int, str]]] = {}
        total_matchable = 0

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts["t0"] = type_counts.get("t0", 0) + internal_count
                            total_matchable += internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        total_matchable += 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        # If total is not divisible by 3, remove tiles
        total_remainder = total_matchable % 3
        if total_remainder != 0:
            tiles_to_remove = total_remainder

            # Find removable tiles - prefer tiles without attributes, but allow any regular tile
            removable_no_attr = []
            removable_with_attr = []
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) >= 2:
                        tile_type = tile_data[0]
                        attr = tile_data[1] if len(tile_data) > 1 else ""
                        if tile_type not in self.GOAL_TYPES and not tile_type.startswith("craft_") and not tile_type.startswith("stack_"):
                            if not attr:
                                removable_no_attr.append((i, pos, tile_type))
                            else:
                                removable_with_attr.append((i, pos, tile_type))

            # Combine: prefer no-attr tiles, but use attr tiles if needed
            removable = removable_no_attr + removable_with_attr

            random.shuffle(removable)
            for layer_idx, pos, _ in removable[:tiles_to_remove]:
                layer_key = f"layer_{layer_idx}"
                if pos in level.get(layer_key, {}).get("tiles", {}):
                    del level[layer_key]["tiles"][pos]
                    level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Recount and fix type distribution
        type_counts = {}
        type_positions = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type not in self.GOAL_TYPES and not tile_type.startswith("craft_") and not tile_type.startswith("stack_"):
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        # Pair up types with remainder 1 and remainder 2
        max_iterations = 20
        for _ in range(max_iterations):
            rem1 = [t for t, c in type_counts.items() if c % 3 == 1 and type_positions.get(t)]
            rem2 = [t for t, c in type_counts.items() if c % 3 == 2 and type_positions.get(t)]

            if not rem1 and not rem2:
                break

            if rem1 and rem2:
                # Move 1 tile from rem1 type to rem2 type
                type_a = rem1[0]
                type_b = rem2[0]
                if type_positions[type_a]:
                    layer_idx, pos = type_positions[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        level[layer_key]["tiles"][pos][0] = type_b
                        type_counts[type_a] -= 1
                        type_counts[type_b] = type_counts.get(type_b, 0) + 1
            else:
                # Need to handle 3 types with same remainder
                break

        return level

    def _validate_and_fix_obstacles(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Final validation pass to ensure all obstacles follow game rules.
        This is called AFTER all modifications (difficulty adjustment, tile addition, etc.)

        Rules:
        1. Chain tiles: At least ONE neighbor must be clearable (no obstacle attribute)
        2. Link tiles: Partner tile MUST exist AND at least one of the pair must have clearable neighbor
        """
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if not tiles:
                continue

            # Collect invalid obstacles to remove
            invalid_obstacles = []

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                attr = tile_data[1]

                # Validate chain tiles - Chain only checks LEFT and RIGHT (on screen)
                # Position format is "col_row" (x_y)
                if attr == "chain":
                    col, row = map(int, pos.split('_'))
                    # Only LEFT (col-1) and RIGHT (col+1) neighbors on screen
                    neighbors = [
                        (col-1, row),  # Left (on screen)
                        (col+1, row),  # Right (on screen)
                    ]

                    has_clearable_neighbor = False
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            # Check if neighbor is clearable (no obstacle or frog only)
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                # CRITICAL: Neighbor must NOT be a goal tile (stack_*/craft_* boxes)
                                # Goal boxes can't be picked directly, so they're not clearable neighbors
                                if ndata[0] in self.GOAL_TYPES:
                                    continue
                                # CRITICAL: Neighbor must NOT be covered by upper layers
                                # If covered, the chain cannot be unlocked
                                if not self._is_position_covered_by_upper(level, i, ncol, nrow):
                                    has_clearable_neighbor = True
                                    break

                    if not has_clearable_neighbor:
                        invalid_obstacles.append(pos)
                        logger.debug(f"[VALIDATE] Invalid chain at layer {i}/{pos}: no clearable uncovered horizontal neighbor")

                # Validate link tiles - connected direction MUST have a tile
                # Position format is "col_row" (x_y)
                elif attr and attr.startswith("link_"):
                    col, row = map(int, pos.split('_'))

                    # Determine the position that the link points to
                    # link_n points north (up), so there must be a tile at row-1
                    # link_s points south (down), so there must be a tile at row+1
                    # link_w points west (left), so there must be a tile at col-1
                    # link_e points east (right), so there must be a tile at col+1
                    if attr == "link_n":
                        target_pos = f"{col}_{row-1}"
                    elif attr == "link_s":
                        target_pos = f"{col}_{row+1}"
                    elif attr == "link_w":
                        target_pos = f"{col-1}_{row}"
                    elif attr == "link_e":
                        target_pos = f"{col+1}_{row}"
                    else:
                        continue

                    # CRITICAL: The linked direction MUST have a tile
                    # CRITICAL: Target must NOT have blocking gimmicks (chain, ice, grass)
                    BLOCKING_GIMMICKS = {"chain", "ice", "ice_1", "ice_2", "ice_3", "grass"}
                    valid_link = False
                    invalid_reason = ""

                    if target_pos in tiles:
                        target_data = tiles[target_pos]
                        if isinstance(target_data, list) and len(target_data) >= 2:
                            # Target must not be a goal tile (craft/stack)
                            target_type = target_data[0]
                            target_attr = target_data[1] if len(target_data) > 1 else ""

                            if (target_type not in self.GOAL_TYPES and
                                not target_type.startswith("craft_") and
                                not target_type.startswith("stack_")):
                                # NEW: Check if target has blocking gimmick
                                if target_attr in BLOCKING_GIMMICKS:
                                    invalid_reason = f"target has blocking gimmick '{target_attr}'"
                                else:
                                    valid_link = True
                            else:
                                invalid_reason = "target is a goal tile"
                        else:
                            invalid_reason = "invalid target data"
                    else:
                        invalid_reason = "target tile does not exist"

                    if not valid_link:
                        logger.debug(f"[VALIDATE] Invalid link at {layer_key}/{pos} ({attr}): {invalid_reason}")
                        invalid_obstacles.append(pos)

                # Validate grass tiles - must have at least 2 clearable neighbors in 4 directions
                # Position format is "col_row" (x_y)
                elif attr and (attr == "grass" or attr.startswith("grass_")):
                    col, row = map(int, pos.split('_'))
                    neighbors = [
                        (col, row-1),  # Up
                        (col, row+1),  # Down
                        (col-1, row),  # Left
                        (col+1, row),  # Right
                    ]

                    clearable_count = 0
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                # CRITICAL: Neighbor must NOT be a goal tile (stack_*/craft_* boxes)
                                if ndata[0] in self.GOAL_TYPES:
                                    continue
                                clearable_count += 1

                    # RULE: Must have at least 2 clearable neighbors
                    if clearable_count < 2:
                        invalid_obstacles.append(pos)

                # Validate unknown tiles - must be covered by upper layer
                # Position format is "col_row" (x_y)
                elif attr == "unknown":
                    col, row = map(int, pos.split('_'))
                    # Unknown tiles MUST be covered by upper layers to show curtain effect
                    if not self._is_position_covered_by_upper(level, i, col, row):
                        invalid_obstacles.append(pos)

            # Remove invalid obstacles
            for pos in invalid_obstacles:
                if pos in tiles and tiles[pos][1]:
                    tiles[pos][1] = ""

        return level


# Singleton instance
_generator = None


def get_generator() -> LevelGenerator:
    """Get or create generator singleton instance."""
    global _generator
    if _generator is None:
        _generator = LevelGenerator()
    return _generator
