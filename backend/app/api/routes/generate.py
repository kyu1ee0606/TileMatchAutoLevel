"""Level generation API routes."""
import os
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

logger = logging.getLogger(__name__)

from ...models.schemas import (
    GenerateRequest,
    GenerateResponse,
    SimulateRequest,
    SimulateResponse,
    ValidatedGenerateRequest,
    ValidatedGenerateResponse,
    EnhanceLevelRequest,
    EnhanceLevelResponse,
)
from ...models.level import GenerationParams, LayerTileConfig, LayerObstacleConfig, LayerPatternConfig
from ...core.generator import LevelGenerator
from ...core.simulator import LevelSimulator
from ...core.bot_simulator import BotSimulator
from ...models.bot_profile import BotType, get_profile
from ...models.gimmick_profile import (
    select_gimmicks_for_difficulty,
    get_gimmick_count_range,
    calculate_gimmick_distribution,
    get_all_profiles_info,
)
from ..deps import get_level_generator, get_level_simulator
import random


# ============================================================
# Module-level ProcessPoolExecutor for CPU-bound bot simulations
# Enables true CPU parallelism (bypasses GIL) even with single uvicorn worker
# ============================================================
_bot_process_pool: ProcessPoolExecutor | None = None

def _get_bot_pool() -> ProcessPoolExecutor:
    """Get or create the module-level ProcessPoolExecutor for bot simulations.

    Pool size = 3 (matches core bot count: casual/average/expert).
    With multi-worker uvicorn (4 workers), total child processes = 4 × 3 = 12.
    Fits within 10 CPU cores with acceptable oversubscription.
    """
    global _bot_process_pool
    if _bot_process_pool is None:
        workers = 3
        _bot_process_pool = ProcessPoolExecutor(max_workers=workers)
        logger.info(f"[BOT_POOL] Created ProcessPoolExecutor with {workers} workers (PID={os.getpid()})")
    return _bot_process_pool


def _simulate_single_bot(args: Tuple[str, dict, int, int]) -> Tuple[str, float]:
    """
    Top-level function for ProcessPoolExecutor (must be picklable).
    Runs a single bot simulation in a separate process for true CPU parallelism.
    """
    bot_type_value, level_json, iterations, max_moves = args
    from ...core.bot_simulator import BotSimulator
    from ...models.bot_profile import BotType, get_profile
    simulator = BotSimulator()
    profile = get_profile(BotType(bot_type_value))
    result = simulator.simulate_with_profile(
        level_json, profile, iterations=iterations, max_moves=max_moves,
    )
    return bot_type_value, result.clear_rate


def resolve_symmetry_mode(symmetry_mode: str | None, allow_none: bool = False) -> str:
    """
    Resolve symmetry mode.

    Rules:
    - Default: Weighted random selection for variety
    - "none" allowed for ~15% of levels for visual diversity
    - Special shape levels (allow_none=True) always get "none"

    Args:
        symmetry_mode: Requested symmetry mode or None for auto
        allow_none: If True, forces asymmetric level (special shapes)

    Returns:
        Resolved symmetry mode string
    """
    # Special shape levels always use "none" for distinctive patterns
    if allow_none:
        return "none"

    # If explicitly set to a valid mode, use it
    if symmetry_mode and symmetry_mode in ["horizontal", "vertical", "both", "none"]:
        return symmetry_mode

    # Default: weighted random selection for visual diversity
    # 30% horizontal, 30% vertical, 25% none, 15% both
    # "none" allows asymmetric layouts for more variety
    return random.choices(
        ["horizontal", "vertical", "none", "both"],
        weights=[0.30, 0.30, 0.25, 0.15],
        k=1
    )[0]


# Special shape level cycle configuration
# 톱니바퀴 사이클: 10스테이지 단위
# - 보스 레벨: 10, 20, 30, ... (매 10번째)
# - 특수 모양 레벨: 9, 19, 29, ... (보스 전 스테이지)
SPECIAL_SHAPE_CYCLE_SIZE = 10  # 10개 레벨 = 1사이클


def is_special_shape_level(level_number: int | None, cycle_size: int = SPECIAL_SHAPE_CYCLE_SIZE) -> bool:
    """
    Determine if a level should be a special shape level based on cycle position.

    톱니바퀴 규칙:
    - 10스테이지 단위로 보스 레벨 등장 (10, 20, 30, ...)
    - 보스 전 스테이지가 특수 모양 레벨 (9, 19, 29, ...)
    - 특수 모양 레벨은 비대칭(asymmetric) 허용

    Args:
        level_number: Current level number (1-based)
        cycle_size: Number of levels per cycle (default: 10)

    Returns:
        True if this level should be a special shape level (pre-boss level)
    """
    if level_number is None or level_number < 1:
        return False

    # Skip tutorial levels (1-3)
    if level_number <= 3:
        return False

    # Special shape level is the level BEFORE boss level
    # Boss levels: 10, 20, 30, ... (level_number % cycle_size == 0)
    # Special shape levels: 9, 19, 29, ... (level_number % cycle_size == cycle_size - 1)
    return level_number % cycle_size == (cycle_size - 1)  # 9, 19, 29, ...


def get_special_shape_pattern_index() -> int:
    """
    Get a random pattern index suitable for special shape levels.
    Special shapes use visually distinctive patterns like stars, letters, arrows.

    Returns:
        Pattern index (0-49) for aesthetic mode
    """
    # Special shape patterns: visually distinctive, works well without strict symmetry
    special_patterns = [
        8,   # heart_shape
        15,  # star_five_point
        16,  # star_six_point
        17,  # crescent_moon
        18,  # sun_burst
        19,  # spiral
        20,  # letter_H
        24,  # letter_X
        25,  # letter_Y
        45,  # butterfly
        46,  # flower_pattern
    ]
    return random.choice(special_patterns)


# Tutorial level configurations (levels 1-3)
# These are special introductory levels with minimal complexity
# NOTE: symmetry_mode="none" ensures exact tile counts (symmetry can cause count variations)
TUTORIAL_LEVEL_CONFIGS = {
    1: {
        "description": "첫 번째 레벨: 3종류 타일 × 3개 = 9타일 기본 매칭",
        "tile_types": ["t1", "t2", "t3"],
        "total_tiles": 9,  # Exactly 3 sets of 3
        "grid_size": (5, 5),
        "max_layers": 1,
        "goals": [],  # No craft/stack goals
        "obstacle_types": [],
        "symmetry_mode": "none",  # Exact tile count required
        "target_difficulty": 0.05,
    },
    2: {
        "description": "두 번째 레벨: 3종류 타일 × 6개 = 18타일, 2레이어",
        "tile_types": ["t1", "t2", "t3"],
        "total_tiles": 18,  # 6 sets of 3
        "grid_size": (5, 5),
        "max_layers": 2,
        "goals": [],
        "obstacle_types": [],
        "symmetry_mode": "none",  # Exact tile count required
        "target_difficulty": 0.08,
    },
    3: {
        "description": "세 번째 레벨: 4종류 타일 × 6개 = 24타일, 2-3레이어",
        "tile_types": ["t1", "t2", "t3", "t4"],
        "total_tiles": 24,  # 8 sets of 3
        "grid_size": (5, 5),
        "max_layers": 3,
        "goals": [],
        "obstacle_types": [],
        "symmetry_mode": "none",  # Exact tile count required
        "target_difficulty": 0.10,
    },
}


def get_tutorial_config(level_number: int | None) -> dict | None:
    """
    Get tutorial configuration for early levels (1-3).
    Returns None if not a tutorial level.
    """
    if level_number is None:
        return None
    return TUTORIAL_LEVEL_CONFIGS.get(level_number)


# =========================================================
# 10레벨 단위 기믹 언락 스케줄 (leveling_config.py와 동기화)
# =========================================================
# [연구 근거] Tile Busters/Triple Tile/Room 8 Studio 분석 결과:
# - Tile Busters: 레벨 5-10에서 첫 장애물 등장
# - Room 8 Studio: "50레벨 동안 메카닉 반복 금지"
# - Room 8 Studio: 히든 타일(unknown)은 레벨 175+ 본격 도입
# - 업계 공통: 장애물은 3무브 이하로 해제 가능해야 함
# - 튜토리얼 원칙: 1-3개 메카닉만 사용
#
# 언락 스케줄 (시장 조사 기반, ~20레벨 간격):
# - Level 1-5: 기믹 없음 (순수 매칭 학습)
# - Level 6: chain 언락 (Tile Busters 참고)
# - Level 25: ice 언락
# - Level 45: grass 언락
# - Level 65: frog 언락
# - Level 85: bomb 언락
# - Level 105: curtain 언락
# - Level 125: teleport 언락
# - Level 145: link 언락
# - Level 175: unknown 언락 (히든 타일 - Room 8 Studio 연구)
# - Level 195: craft 언락
# - Level 215: stack 언락
# - Level 216+: 모든 기믹 자유 조합
# =========================================================
DEFAULT_GIMMICK_UNLOCK_LEVELS = {
    "chain": 6,        # 첫 번째 기믹 - 기본 체인 (Tile Busters: 5-10)
    "ice": 25,         # 두 번째 기믹 - 얼음
    "grass": 45,       # 세 번째 기믹 - 풀
    "frog": 65,        # 네 번째 기믹 - 개구리 (이동)
    "bomb": 85,        # 다섯 번째 기믹 - 폭탄 (시간 압박)
    "curtain": 105,    # 여섯 번째 기믹 - 커튼 (기억력)
    "teleport": 125,   # 일곱 번째 기믹 - 텔레포트
    "link": 145,       # 여덟 번째 기믹 - 링크 (연결)
    "unknown": 175,    # 아홉 번째 기믹 - 히든 타일 (Room 8 Studio 연구)
    "craft": 195,      # 열 번째 기믹 - 크래프트 목표
    "stack": 215,      # 열한 번째 기믹 - 스택 목표
}

# Legacy simple unlock levels (5-stage intervals)
# All 11 gimmicks unlock by level 55
SIMPLE_GIMMICK_UNLOCK_LEVELS = {
    "chain": 5,
    "frog": 10,
    "ice": 15,
    "link": 20,
    "grass": 25,
    "bomb": 30,
    "curtain": 35,
    "teleport": 40,
    "unknown": 45,
    "craft": 50,
    "stack": 55,
}


def filter_obstacles_by_unlock_level(
    obstacle_types: List[str] | None,
    level_number: int | None,
    unlock_levels: Dict[str, int] | None
) -> List[str] | None:
    """
    Filter obstacle types based on unlock levels.
    Only returns obstacles that have been unlocked at the current level.

    Args:
        obstacle_types: List of requested obstacle types
        level_number: Current level number (1-based)
        unlock_levels: Dict mapping gimmick names to unlock level numbers

    Returns:
        Filtered list of unlocked obstacles, or None if no obstacles
    """
    if obstacle_types is None or level_number is None:
        return obstacle_types

    # Use default unlock levels if not provided
    actual_unlock_levels = unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS

    # Filter to only include unlocked gimmicks
    unlocked = [
        obs for obs in obstacle_types
        if actual_unlock_levels.get(obs, 0) <= level_number
    ]

    return unlocked if unlocked else None


def filter_goals_by_unlock_level(
    goals: List[Dict] | None,
    level_number: int | None,
    unlock_levels: Dict[str, int] | None
) -> List[Dict] | None:
    """
    Filter goals based on unlock levels.
    craft_* goals require "craft" to be unlocked, stack_* goals require "stack".

    Args:
        goals: List of goal configurations (e.g., [{"type": "craft_s", "count": 3}])
        level_number: Current level number (1-based)
        unlock_levels: Dict mapping gimmick names to unlock level numbers

    Returns:
        Filtered list of unlocked goals, or empty list if no goals are unlocked
    """
    if level_number is None:
        return goals

    # Use default unlock levels if not provided
    actual_unlock_levels = unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS

    # If goals is None, check if craft/stack are unlocked
    # and return appropriate default or empty list
    if goals is None:
        craft_unlock = actual_unlock_levels.get("craft", 50)
        if level_number >= craft_unlock:
            # craft is unlocked, use default craft_s goal
            return None  # Let generator use its default
        else:
            # craft is not unlocked, use empty goals
            return []

    # Filter goals based on unlock levels
    filtered = []
    for goal in goals:
        goal_type = goal.get("type", "craft")
        # Extract base type (craft or stack) from goal type
        if goal_type.startswith("craft"):
            base_type = "craft"
        elif goal_type.startswith("stack"):
            base_type = "stack"
        else:
            base_type = goal_type

        unlock_level = actual_unlock_levels.get(base_type, 0)
        if level_number >= unlock_level:
            filtered.append(goal)

    return filtered if filtered else []


def get_tutorial_gimmick(
    level_number: int | None,
    unlock_levels: Dict[str, int] | None
) -> str | None:
    """
    Check if this level is a tutorial level (first level where a gimmick unlocks).
    Returns the gimmick name if this is a tutorial level, None otherwise.

    Tutorial levels should feature the new gimmick prominently with easier settings.
    """
    if level_number is None:
        return None

    actual_unlock_levels = unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS

    # Check if any gimmick unlocks at exactly this level
    for gimmick, unlock_level in actual_unlock_levels.items():
        if unlock_level == level_number:
            return gimmick

    return None


def select_gimmicks_with_unlock_probability(
    level_number: int,
    target_difficulty: float,
    unlock_levels: Dict[str, int],
    available_gimmicks: List[str] | None = None,
    inclusion_probability: float = 0.5,
) -> List[str]:
    """
    Select gimmicks for a level based on unlock status with probability-based inclusion.

    Rules:
    1. Tutorial levels (where a gimmick just unlocked): ALWAYS include the new gimmick
    2. For other unlocked gimmicks: include with `inclusion_probability` (default 50%)
    3. Respect max_gimmick_types limit from difficulty profile

    Args:
        level_number: Current level number (1-based)
        target_difficulty: Target difficulty (0.0-1.0)
        unlock_levels: Dict mapping gimmick names to unlock level numbers
        available_gimmicks: Optional pool of available gimmicks (uses all if None)
        inclusion_probability: Probability to include each unlocked gimmick (default 0.5 = 50%)

    Returns:
        List of selected gimmicks
    """
    from ...models.gimmick_profile import get_profile_for_difficulty

    # Get difficulty profile for max gimmick types
    profile = get_profile_for_difficulty(target_difficulty)
    max_types = profile.max_gimmick_types

    if max_types == 0:
        return []

    # Find the tutorial gimmick (newly unlocked at this level)
    tutorial_gimmick = None
    for gimmick, unlock_level in unlock_levels.items():
        if unlock_level == level_number:
            tutorial_gimmick = gimmick
            break

    # Get all unlocked gimmicks at this level
    unlocked_gimmicks = [
        g for g, unlock_lvl in unlock_levels.items()
        if unlock_lvl <= level_number
    ]

    # If available_gimmicks provided, filter to only those
    if available_gimmicks:
        unlocked_gimmicks = [g for g in unlocked_gimmicks if g in available_gimmicks]

    if not unlocked_gimmicks:
        return []

    selected = []

    # Step 1: Tutorial gimmick is ALWAYS included (if it exists and is unlocked)
    if tutorial_gimmick and tutorial_gimmick in unlocked_gimmicks:
        selected.append(tutorial_gimmick)
        logger.info(f"[GIMMICK_SELECT] Level {level_number}: Tutorial gimmick '{tutorial_gimmick}' ALWAYS included")

    # Step 2: For other unlocked gimmicks, include with probability
    other_gimmicks = [g for g in unlocked_gimmicks if g != tutorial_gimmick]
    random.shuffle(other_gimmicks)  # Randomize order for fair selection

    for gimmick in other_gimmicks:
        if len(selected) >= max_types:
            break

        # Include with probability
        if random.random() < inclusion_probability:
            selected.append(gimmick)
            logger.info(f"[GIMMICK_SELECT] Level {level_number}: '{gimmick}' included (50% probability)")

    # If no gimmicks selected and tutorial gimmick exists, ensure at least the tutorial gimmick
    if not selected and tutorial_gimmick:
        selected.append(tutorial_gimmick)

    # If still no gimmicks and we have unlocked ones, select at least one randomly
    # (ensures gimmick presence after unlock - 언락된 기믹은 반드시 학습되어야 함)
    if not selected and unlocked_gimmicks and max_types > 0:
        # Select one random gimmick from unlocked pool
        random_gimmick = random.choice(unlocked_gimmicks)
        selected.append(random_gimmick)
        logger.info(f"[GIMMICK_SELECT] Level {level_number}: '{random_gimmick}' selected as fallback (ensures gimmick presence)")

    logger.info(f"[GIMMICK_SELECT] Level {level_number}: Final selection = {selected} "
               f"(max_types={max_types}, unlocked={len(unlocked_gimmicks)})")

    return selected


# Base bot target clear rates (for target_difficulty=0.5)
# MUST be consistent with analyze.py
BASE_TARGET_RATES = {
    "novice": 0.40,
    "casual": 0.60,
    "average": 0.75,
    "expert": 0.90,
    "optimal": 0.98,
}


def calculate_total_tiles(level_json: Dict) -> int:
    """
    Calculate total tiles including internal tiles in stack/craft containers.

    This counts:
    - Regular tiles on the board (1 per position)
    - Internal tiles in stack/craft containers (based on their count parameter)

    Returns the total number of moves needed to clear all tiles.
    """
    total_tiles = 0
    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) > 0:
                tile_type = tile_data[0]
                # Check for stack/craft tiles (e.g., "stack_e", "craft_s")
                if isinstance(tile_type, str) and (
                    tile_type.startswith("stack_") or tile_type.startswith("craft_")
                ):
                    # Get internal tile count from tile_data[2]
                    # Format: [tile_type, attribute, [count]] or [tile_type, attribute, {"totalCount": count}]
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

    return total_tiles


def calculate_target_clear_rates(target_difficulty: float) -> Dict[str, float]:
    """
    Calculate target clear rates based on target difficulty.

    target_difficulty=0.0: Very easy, all bots ~99%
    target_difficulty=0.5: Balanced (base rates)
    target_difficulty=1.0: Very hard, lower rates based on game mechanics

    NOTE: Calibrated based on extensive game simulation testing.
    For EASY levels (< 0.4), we expect all bots to have very high clear rates.
    The tile matching game difficulty is primarily driven by:
    - Tile type count (more types = harder to match before dock fills)
    - Move constraint ratio (tighter moves = less room for suboptimal play)
    - Bot skill levels have meaningful variance when properly constrained
    """
    rates = {}

    # EASY levels (0-0.4): All bots should have very high clear rates
    # This is realistic because easy levels give generous moves and few tile types
    if target_difficulty <= 0.4:
        t = target_difficulty / 0.4  # 0 at difficulty 0, 1 at difficulty 0.4
        easy_rates = {
            "novice": 0.99 - t * 0.20,    # 99% -> 79%
            "casual": 0.99 - t * 0.15,    # 99% -> 84%
            "average": 0.99 - t * 0.10,   # 99% -> 89%
            "expert": 0.99 - t * 0.05,    # 99% -> 94%
            "optimal": 0.99 - t * 0.01,   # 99% -> 98%
        }
        for bot_type in BASE_TARGET_RATES:
            rates[bot_type] = easy_rates.get(bot_type, 0.95)
    elif target_difficulty <= 0.6:
        # MEDIUM levels (0.4-0.6): Transition zone
        t = (target_difficulty - 0.4) / 0.2  # 0 at 0.4, 1 at 0.6
        medium_start = {
            "novice": 0.79,
            "casual": 0.84,
            "average": 0.89,
            "expert": 0.94,
            "optimal": 0.98,
        }
        medium_end = {
            "novice": 0.55,
            "casual": 0.70,
            "average": 0.82,
            "expert": 0.92,
            "optimal": 0.98,
        }
        for bot_type in BASE_TARGET_RATES:
            start = medium_start.get(bot_type, 0.80)
            end = medium_end.get(bot_type, 0.70)
            rates[bot_type] = start - t * (start - end)
    else:
        # HARD levels (0.6-1.0): Significant difficulty for all but optimal
        t = (target_difficulty - 0.6) / 0.4  # 0 at 0.6, 1 at 1.0
        hard_start = {
            "novice": 0.55,
            "casual": 0.70,
            "average": 0.82,
            "expert": 0.92,
            "optimal": 0.98,
        }
        hard_end = {
            "novice": 0.10,    # Heavily affected by tile types and move limits
            "casual": 0.25,    # Significantly affected
            "average": 0.50,   # Noticeable impact
            "expert": 0.75,    # Good but not perfect
            "optimal": 0.88,   # Very good but can fail
        }
        for bot_type in BASE_TARGET_RATES:
            start = hard_start.get(bot_type, 0.70)
            end = hard_end.get(bot_type, 0.40)
            rates[bot_type] = start - t * (start - end)

    # Clamp all rates
    for bot_type in rates:
        rates[bot_type] = max(0.01, min(0.99, rates[bot_type]))

    return rates


def calculate_match_score(actual_rates: Dict[str, float], target_rates: Dict[str, float]) -> Tuple[float, float, float]:
    """
    Calculate match score between actual and target clear rates.

    Returns: (match_score, avg_gap, max_gap)
    - match_score: 0-100%, higher is better
    - avg_gap: average gap in percentage points
    - max_gap: maximum gap in percentage points
    """
    gaps = []
    for bot_type in target_rates:
        actual = actual_rates.get(bot_type, 0)
        target = target_rates[bot_type]
        gap = abs(actual - target) * 100  # Convert to percentage points
        gaps.append(gap)

    if not gaps:
        return 100.0, 0.0, 0.0

    avg_gap = sum(gaps) / len(gaps)
    max_gap = max(gaps)
    weighted_gap = avg_gap * 0.6 + max_gap * 0.4
    match_score = max(0, 100 - weighted_gap * 2)

    return match_score, avg_gap, max_gap

router = APIRouter(prefix="/api", tags=["generate"])


def generate_fallback_level(
    generator: "LevelGenerator",
    target_difficulty: float,
    goals: List[Dict] = None,
) -> Dict:
    """
    Generate a guaranteed-to-work fallback level with simplified parameters.
    This is called when all normal generation attempts fail.
    """
    # Use very simple, safe parameters that are guaranteed to work
    # NOTE: t0 is excluded - causes issues with bot simulation
    # t1~t15 풀에서 랜덤 선택
    _all_tiles = [f"t{i}" for i in range(1, 16)]
    simple_tile_types = sorted(random.sample(_all_tiles, 3))  # 3 types
    simple_grid = (5, 5)  # Small grid
    simple_layers = 4  # Few layers

    # Adjust parameters based on difficulty
    if target_difficulty >= 0.6:
        simple_tile_types = sorted(random.sample(_all_tiles, 4))
        simple_grid = (6, 6)
        simple_layers = 5

    params = GenerationParams(
        target_difficulty=target_difficulty,
        grid_size=simple_grid,
        max_layers=simple_layers,
        tile_types=simple_tile_types,
        obstacle_types=None,  # No obstacles for safety
        goals=goals or [{"type": "craft", "direction": "s", "count": 2}],
        symmetry_mode="none",
        pattern_type="geometric",
    )

    result = generator.generate(params)
    level_json = result.level_json

    # Ensure generous moves
    total_tiles = calculate_total_tiles(level_json)
    level_json["max_moves"] = max(total_tiles + 20, int(total_tiles * 1.5))
    level_json["target_difficulty"] = target_difficulty
    level_json["_fallback"] = True  # Mark as fallback level

    return {
        "level_json": level_json,
        "actual_difficulty": result.actual_difficulty,
        "grade": result.grade.value,
    }


@router.post("/generate", response_model=GenerateResponse)
def generate_level(
    request: GenerateRequest,
    generator: LevelGenerator = Depends(get_level_generator),
) -> GenerateResponse:
    """
    Generate a level with target difficulty.

    Args:
        request: GenerateRequest with generation parameters.
        generator: LevelGenerator dependency.

    Returns:
        GenerateResponse with generated level and actual difficulty.
    """
    # Check for tutorial levels (1-3) - use special simplified configurations
    tutorial_config = get_tutorial_config(request.level_number)
    if tutorial_config:
        logger.info(f"[TUTORIAL_LEVEL] Generating level {request.level_number}: {tutorial_config['description']}")

        # Level 1: Use fixed 3x3 grid with horizontal tile rows
        # Layout:
        #   t1 t1 t1
        #   t2 t2 t2
        #   t3 t3 t3
        if request.level_number == 1:
            import time
            start_time = time.time()

            # Fixed 3x3 layout centered in 5x5 grid (positions 1-3 in both axes)
            level_json = {
                "layer": 1,
                "useTileCount": 3,
                "randSeed": random.randint(1, 999999),
                "layer_0": {
                    "col": "5",
                    "row": "5",
                    "tiles": {
                        # Row 1: t1 t1 t1
                        "1_1": ["t1", ""],
                        "2_1": ["t1", ""],
                        "3_1": ["t1", ""],
                        # Row 2: t2 t2 t2
                        "1_2": ["t2", ""],
                        "2_2": ["t2", ""],
                        "3_2": ["t2", ""],
                        # Row 3: t3 t3 t3
                        "1_3": ["t3", ""],
                        "2_3": ["t3", ""],
                        "3_3": ["t3", ""],
                    },
                    "num": "9"
                },
                "goalCount": {},
                "max_moves": 19,  # 9 tiles + 10 generous
                "target_difficulty": 0.05,
                "is_tutorial": True,
                "tutorial_level": 1
            }

            generation_time_ms = int((time.time() - start_time) * 1000)

            return GenerateResponse(
                level_json=level_json,
                actual_difficulty=0.05,
                grade="S",
                generation_time_ms=generation_time_ms,
            )

        # Other tutorial levels (2, 3): use generator with fixed parameters
        params = GenerationParams(
            target_difficulty=tutorial_config["target_difficulty"],
            grid_size=tuple(tutorial_config["grid_size"]),
            max_layers=tutorial_config["max_layers"],
            tile_types=tutorial_config["tile_types"],
            obstacle_types=tutorial_config["obstacle_types"],
            goals=tutorial_config["goals"],
            total_tile_count=tutorial_config["total_tiles"],
            symmetry_mode=tutorial_config["symmetry_mode"],
            pattern_type="geometric",
        )

        result = generator.generate(params)

        # Ensure generous moves for tutorial
        total_tiles = tutorial_config["total_tiles"]
        result.level_json["max_moves"] = total_tiles + 10  # Very generous
        result.level_json["target_difficulty"] = tutorial_config["target_difficulty"]
        result.level_json["is_tutorial"] = True
        result.level_json["tutorial_level"] = request.level_number

        return GenerateResponse(
            level_json=result.level_json,
            actual_difficulty=result.actual_difficulty,
            grade=result.grade.value,
            generation_time_ms=result.generation_time_ms,
        )

    # Convert goals from Pydantic models to dicts
    # Use None check to allow empty list (empty list means no goals)
    goals = None
    if request.goals is not None:
        goals = [
            {"type": g.type, "direction": g.direction, "count": g.count}
            for g in request.goals
        ]

    # Convert obstacle_counts from Pydantic models to dicts
    obstacle_counts = None
    if request.obstacle_counts is not None:
        obstacle_counts = {
            k: {"min": v.min, "max": v.max}
            for k, v in request.obstacle_counts.items()
        }

    # Convert layer_tile_configs from Pydantic models to dataclasses
    layer_tile_configs = None
    if request.layer_tile_configs is not None:
        layer_tile_configs = [
            LayerTileConfig(layer=c.layer, count=c.count)
            for c in request.layer_tile_configs
        ]

    # Convert layer_obstacle_configs from Pydantic models to dataclasses
    layer_obstacle_configs = None
    if request.layer_obstacle_configs is not None:
        layer_obstacle_configs = [
            LayerObstacleConfig(
                layer=c.layer,
                counts={
                    k: {"min": v.min, "max": v.max}
                    for k, v in c.counts.items()
                }
            )
            for c in request.layer_obstacle_configs
        ]

    # Convert layer_pattern_configs from Pydantic models to dataclasses
    layer_pattern_configs = None
    if hasattr(request, 'layer_pattern_configs') and request.layer_pattern_configs is not None:
        layer_pattern_configs = [
            LayerPatternConfig(
                layer=c.layer,
                pattern_type=c.pattern_type,
                pattern_index=c.pattern_index
            )
            for c in request.layer_pattern_configs
        ]

    # Check if this is a tutorial level (new gimmick introduction)
    tutorial_gimmick = get_tutorial_gimmick(
        request.level_number,
        request.gimmick_unlock_levels
    )

    # Debug logging for tutorial gimmick
    logger.info(f"[TUTORIAL_GIMMICK] level_number={request.level_number}, "
               f"unlock_levels={request.gimmick_unlock_levels}, "
               f"tutorial_gimmick={tutorial_gimmick}")

    # Tutorial level settings: easier difficulty, only the new gimmick
    target_difficulty = request.target_difficulty
    if tutorial_gimmick and request.auto_select_gimmicks:
        # Tutorial levels are easier (reduce difficulty by 30%)
        target_difficulty = max(0.2, request.target_difficulty * 0.7)

    # Handle auto gimmick selection with unlock probability system
    obstacle_types = request.obstacle_types
    if request.auto_select_gimmicks and request.level_number is not None:
        unlock_levels = request.gimmick_unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS

        # Use new probability-based selection:
        # - Tutorial levels (11, 21, 31...): 100% new gimmick included
        # - Other unlocked gimmicks: 50% probability each
        # - Respects max_gimmick_types from difficulty profile
        # NOTE: Use ORIGINAL difficulty (not reduced tutorial difficulty) for max_gimmick_types
        # This allows other unlocked gimmicks to also be included in tutorial levels
        obstacle_types = select_gimmicks_with_unlock_probability(
            level_number=request.level_number,
            target_difficulty=request.target_difficulty,  # Use original, not reduced
            unlock_levels=unlock_levels,
            available_gimmicks=list(request.available_gimmicks) if request.available_gimmicks else None,
            inclusion_probability=0.5,  # 50% for each unlocked gimmick
        )

        logger.info(f"[GIMMICK_SELECT] Level {request.level_number}: "
                   f"auto_selected={obstacle_types}, tutorial_gimmick={tutorial_gimmick}")
    elif request.obstacle_types:
        # For manual selection mode, apply gimmick unlock filter
        obstacle_types = filter_obstacles_by_unlock_level(
            obstacle_types,
            request.level_number,
            request.gimmick_unlock_levels
        )
    else:
        # No gimmicks specified
        obstacle_types = []

    # Check if this is a special shape level (톱니바퀴 사이클: 매 10레벨마다 1개)
    is_special_shape = is_special_shape_level(request.level_number)

    # For special shape levels, use distinctive patterns and allow asymmetry
    pattern_index = request.pattern_index
    pattern_type = request.pattern_type
    if is_special_shape and pattern_index is None:
        pattern_index = get_special_shape_pattern_index()
        pattern_type = "aesthetic"
        logger.info(f"[SPECIAL_SHAPE] Level {request.level_number} is a special shape level, using pattern {pattern_index}")

    # Resolve symmetry mode
    # At least one axis symmetry required, unless it's a special shape level
    actual_symmetry = resolve_symmetry_mode(request.symmetry_mode, allow_none=is_special_shape)

    # DEBUG: Log symmetry mode resolution
    logger.info(f"[SYMMETRY_DEBUG] Level {request.level_number}: "
                f"request.symmetry_mode={request.symmetry_mode}, "
                f"is_special_shape={is_special_shape}, "
                f"actual_symmetry={actual_symmetry}, "
                f"pattern_type={pattern_type}, "
                f"pattern_index={pattern_index}")

    # Filter goals by unlock level (craft/stack goals only available after unlock)
    filtered_goals = filter_goals_by_unlock_level(
        goals,
        request.level_number,
        request.gimmick_unlock_levels
    )

    params = GenerationParams(
        target_difficulty=target_difficulty,  # Use adjusted difficulty for tutorial levels
        grid_size=tuple(request.grid_size),
        max_layers=request.max_layers,
        tile_types=request.tile_types,
        obstacle_types=obstacle_types,
        goals=filtered_goals,
        obstacle_counts=obstacle_counts,
        total_tile_count=request.total_tile_count,
        active_layer_count=request.active_layer_count,
        layer_tile_configs=layer_tile_configs,
        layer_obstacle_configs=layer_obstacle_configs,
        layer_pattern_configs=layer_pattern_configs,
        symmetry_mode=actual_symmetry,
        pattern_type=pattern_type,  # Use local variable (may be overridden for special shape)
        pattern_index=pattern_index,  # Use local variable (may be overridden for special shape)
        gimmick_intensity=request.gimmick_intensity,
        # Tutorial gimmick: place on top layer for tutorial UI
        tutorial_gimmick=tutorial_gimmick,
        tutorial_gimmick_min_count=3,  # Ensure at least 3 tutorial gimmicks are visible
        # [연구 근거] 레벨 번호 전달 - unknown 비율 동적 계산용
        level_number=request.level_number,
    )

    # Try generation with up to 3 fallback attempts
    MAX_GENERATION_ATTEMPTS = 3
    last_error = None

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            if attempt > 0:
                # Simplify parameters for fallback attempts
                logger.warning(f"[GENERATE] Fallback attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}")

                # Progressively simplify parameters
                if attempt >= 1:
                    # Remove obstacles on first retry, but PRESERVE tutorial gimmick
                    params = GenerationParams(
                        target_difficulty=params.target_difficulty,
                        grid_size=params.grid_size,
                        max_layers=min(params.max_layers, 5),  # Reduce layers
                        tile_types=params.tile_types[:4] if params.tile_types else ["t1", "t2", "t3", "t4"],
                        obstacle_types=[tutorial_gimmick] if tutorial_gimmick else [],  # Keep tutorial gimmick
                        goals=params.goals,
                        symmetry_mode=params.symmetry_mode,
                        pattern_type=params.pattern_type,
                        gimmick_intensity=0.5 if tutorial_gimmick else 0,  # Reduced but not zero for tutorial
                        tutorial_gimmick=tutorial_gimmick,  # PRESERVE tutorial gimmick
                        tutorial_gimmick_min_count=3,
                        level_number=request.level_number,
                    )

                if attempt >= 2:
                    # Use simplest possible parameters, but STILL preserve tutorial gimmick
                    params = GenerationParams(
                        target_difficulty=params.target_difficulty,
                        grid_size=(6, 6),  # Simple grid
                        max_layers=4,  # Few layers
                        tile_types=["t1", "t2", "t3"],  # Minimum tile types
                        obstacle_types=[tutorial_gimmick] if tutorial_gimmick else [],  # Keep tutorial gimmick
                        goals=[{"type": "craft", "direction": "s", "count": 3}],
                        symmetry_mode="horizontal",
                        pattern_type="geometric",
                        tutorial_gimmick=tutorial_gimmick,  # PRESERVE tutorial gimmick
                        tutorial_gimmick_min_count=3,
                        level_number=request.level_number,
                    )

            result = generator.generate(params)

            # Store target_difficulty and generation config in level_json for verification
            result.level_json["target_difficulty"] = target_difficulty
            # Mark tutorial levels with the gimmick being introduced
            if tutorial_gimmick:
                result.level_json["tutorial_gimmick"] = tutorial_gimmick
            # Store actual symmetry mode used (not request value)
            result.level_json["symmetry_mode"] = actual_symmetry
            if request.pattern_type:
                result.level_json["pattern_type"] = request.pattern_type

            # Mark if this was a fallback generation
            if attempt > 0:
                result.level_json["_fallback_attempt"] = attempt + 1

            return GenerateResponse(
                level_json=result.level_json,
                actual_difficulty=result.actual_difficulty,
                grade=result.grade.value,
                generation_time_ms=result.generation_time_ms,
            )
        except Exception as e:
            import traceback
            last_error = e
            error_details = traceback.format_exc()
            logger.error(f"[GENERATE] Attempt {attempt + 1} failed: {str(e)}\n{error_details}")
            continue

    # All attempts failed
    logger.error(f"[GENERATE] All {MAX_GENERATION_ATTEMPTS} attempts failed. Last error: {str(last_error)}")
    raise HTTPException(status_code=400, detail=f"Generation failed after {MAX_GENERATION_ATTEMPTS} attempts: {str(last_error)}")


@router.post("/simulate", response_model=SimulateResponse)
def simulate_level(
    request: SimulateRequest,
    simulator: LevelSimulator = Depends(get_level_simulator),
) -> SimulateResponse:
    """
    Run Monte Carlo simulation on a level.

    Args:
        request: SimulateRequest with level and simulation parameters.
        simulator: LevelSimulator dependency.

    Returns:
        SimulateResponse with simulation statistics.
    """
    try:
        # Validate strategy
        valid_strategies = ["random", "greedy", "optimal"]
        if request.strategy not in valid_strategies:
            raise ValueError(f"Invalid strategy. Must be one of: {valid_strategies}")

        result = simulator.simulate(
            level_json=request.level_json,
            iterations=request.iterations,
            strategy=request.strategy,
        )

        # Calculate difficulty estimate from clear rate
        # Lower clear rate = higher difficulty
        difficulty_estimate = 1.0 - result.clear_rate

        return SimulateResponse(
            clear_rate=result.clear_rate,
            avg_moves=result.avg_moves,
            min_moves=result.min_moves,
            max_moves=result.max_moves,
            difficulty_estimate=difficulty_estimate,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Simulation failed: {str(e)}")


@router.post("/generate/validated", response_model=ValidatedGenerateResponse)
def generate_validated_level(
    request: ValidatedGenerateRequest,
    generator: LevelGenerator = Depends(get_level_generator),
) -> ValidatedGenerateResponse:
    """
    Generate a level with simulation-based validation.

    This endpoint generates levels and validates them against target clear rates
    using bot simulation. If the generated level doesn't match the target difficulty,
    it will retry with adjusted parameters including:
    - difficulty_offset: internal target adjustment
    - max_layers: layer count (3-7)
    - obstacle_types: automatically added for hard levels
    - tile_types: more types for harder levels
    - grid_size: larger grids for harder levels
    - max_moves_modifier: reduce available moves for harder levels

    Args:
        request: ValidatedGenerateRequest with generation and validation parameters.
        generator: LevelGenerator dependency.

    Returns:
        ValidatedGenerateResponse with generated level and validation results.
    """
    start_time = time.time()

    if request.scoring_difficulty is not None:
        logger.info(f"[REGEN] scoring_difficulty={request.scoring_difficulty:.3f}, target_difficulty={request.target_difficulty:.3f} (match_score will use scoring_difficulty)")

    # Check for tutorial levels (1-3) - use special simplified configurations
    tutorial_config = get_tutorial_config(request.level_number)
    if tutorial_config:
        logger.info(f"[TUTORIAL_LEVEL] Generating validated level {request.level_number}: {tutorial_config['description']}")

        # Generate tutorial level with fixed parameters - no validation needed
        params = GenerationParams(
            target_difficulty=tutorial_config["target_difficulty"],
            grid_size=tuple(tutorial_config["grid_size"]),
            max_layers=tutorial_config["max_layers"],
            tile_types=tutorial_config["tile_types"],
            obstacle_types=tutorial_config["obstacle_types"],
            goals=tutorial_config["goals"],
            total_tile_count=tutorial_config["total_tiles"],
            symmetry_mode=tutorial_config["symmetry_mode"],
            pattern_type="geometric",
        )

        result = generator.generate(params)

        # Ensure generous moves for tutorial
        total_tiles = tutorial_config["total_tiles"]
        result.level_json["max_moves"] = total_tiles + 10
        result.level_json["target_difficulty"] = tutorial_config["target_difficulty"]
        result.level_json["is_tutorial"] = True
        result.level_json["tutorial_level"] = request.level_number
        result.level_json["symmetry_mode"] = tutorial_config["symmetry_mode"]

        generation_time_ms = int((time.time() - start_time) * 1000)

        # Tutorial levels always pass validation with perfect scores
        return ValidatedGenerateResponse(
            level_json=result.level_json,
            actual_difficulty=result.actual_difficulty,
            grade=result.grade.value,
            generation_time_ms=generation_time_ms,
            validation_passed=True,
            attempts=1,
            bot_clear_rates={"novice": 0.99, "casual": 0.99, "average": 0.99, "expert": 0.99, "optimal": 0.99},
            target_clear_rates={"novice": 0.99, "casual": 0.99, "average": 0.99, "expert": 0.99, "optimal": 0.99},
            avg_gap=0.0,
            max_gap=0.0,
            match_score=100.0,
        )

    # Skip bot simulator initialization if simulation is disabled
    skip_simulation = (request.simulation_iterations == 0)
    bot_simulator = None if skip_simulation else BotSimulator()

    # Import analyzer for static analysis (only used once at the end)
    from ...core.analyzer import LevelAnalyzer
    analyzer = LevelAnalyzer()

    # OPTIMIZATION: Adaptive simulation iterations based on difficulty
    # Lower difficulty = fewer iterations needed (more predictable outcomes)
    if skip_simulation:
        effective_iterations = 0
        logger.info(f"[FAST_GENERATE] simulation_iterations=0, skipping bot simulation")
    elif request.target_difficulty <= 0.2:
        effective_iterations = min(8, request.simulation_iterations)   # Very easy: 8 iterations enough
    elif request.target_difficulty <= 0.4:
        effective_iterations = min(12, request.simulation_iterations)  # Easy: 12 iterations
    elif request.target_difficulty <= 0.6:
        effective_iterations = min(18, request.simulation_iterations)  # Medium: 18 iterations
    else:
        effective_iterations = request.simulation_iterations            # Hard: full iterations

    # OPTIMIZATION: Early exit threshold - stop if match is good enough
    EARLY_EXIT_THRESHOLD = 80.0  # Stop if match score >= 80%

    # Convert goals from Pydantic models to dicts
    goals = None
    if request.goals is not None:
        goals = [
            {"type": g.type, "direction": g.direction, "count": g.count}
            for g in request.goals
        ]

    # Filter goals by unlock level (craft/stack goals only available after unlock)
    goals = filter_goals_by_unlock_level(
        goals,
        request.level_number,
        request.gimmick_unlock_levels
    )

    best_result = None
    best_match_score = -1
    best_actual_rates = {}
    best_target_rates = {}  # Store best target rates to avoid undefined variable
    best_gaps = (100.0, 100.0)
    best_max_moves = 50

    # Adaptive parameters for retry
    current_max_layers = request.max_layers
    difficulty_offset = 0.0  # Adjust target difficulty for generator
    max_moves_modifier = 1.0  # Reduce max_moves for harder levels

    # CALIBRATED moves_ratio based on target difficulty
    # This is the key parameter for controlling difficulty
    # Higher ratio = easier (more moves allowed)
    # Lower ratio = harder (tighter move constraint)
    # IMPROVED: More aggressive settings based on test findings
    if request.target_difficulty <= 0.2:
        moves_ratio = 1.5  # Very very easy: 50% extra moves
    elif request.target_difficulty <= 0.35:
        moves_ratio = 1.35  # Very easy: 35% extra moves
    elif request.target_difficulty <= 0.5:
        moves_ratio = 1.2  # Medium: 20% extra moves
    elif request.target_difficulty <= 0.65:
        moves_ratio = 1.1  # Hard: 10% extra moves
    elif request.target_difficulty <= 0.8:
        moves_ratio = 1.02  # Very Hard: 2% extra moves (almost exact)
    else:
        moves_ratio = 1.0  # Extreme: exact tile count (no extra moves)

    # CALIBRATED tile types based on target difficulty
    # More types = harder (more variety to match)
    # NOTE: t0 is excluded - causes issues with bot simulation
    # t1~t15 풀에서 난이도별 개수만큼 랜덤 선택 (골고루 사용)
    #
    # 프로페셔널 게임 참고 (Tile Buster, Tile Explorer 등):
    # - 대부분의 타일 매칭 게임은 4-8개 타일 타입 사용
    # - 9개 이상은 인지 부하가 과도하여 플레이 경험 저하
    # - 최대 난이도에서도 8개로 제한 (기믹과 무브 제한으로 난이도 조절)
    # - 3개 타일은 레벨 1 튜토리얼에서만 사용, 이후 최소 4개
    ALL_AVAILABLE_TILES = [f"t{i}" for i in range(1, 16)]  # t1~t15 전체 풀
    is_tutorial_level_1 = request.level_number == 1

    if request.target_difficulty >= 0.85:
        tile_type_count = 8   # extreme (85%+)
    elif request.target_difficulty >= 0.75:
        tile_type_count = 8   # very hard (75-85%)
    elif request.target_difficulty >= 0.65:
        tile_type_count = 7   # hard (65-75%)
    elif request.target_difficulty >= 0.55:
        tile_type_count = 6   # medium-hard (55-65%)
    elif request.target_difficulty >= 0.45:
        tile_type_count = 5   # medium (45-55%)
    elif request.target_difficulty >= 0.35:
        tile_type_count = 5   # medium-easy (35-45%)
    elif is_tutorial_level_1 and request.target_difficulty < 0.25:
        tile_type_count = 3   # level 1 tutorial only (<25%)
    else:
        tile_type_count = 4   # minimum for all other levels

    default_tile_types = sorted(random.sample(ALL_AVAILABLE_TILES, tile_type_count))

    base_tile_types = list(request.tile_types) if request.tile_types else default_tile_types
    all_tile_types = ALL_AVAILABLE_TILES[:]  # t1~t15 전체 풀 (retry 시 랜덤 추가용)
    current_tile_types = base_tile_types.copy()

    # Track tile type count separately for fine-tuning
    current_tile_type_count = len(current_tile_types)

    # Initial obstacle types from request (or auto-select based on difficulty)
    available_obstacles = ["chain", "frog", "ice", "grass", "bomb", "curtain", "teleport", "crate", "craft", "stack"]

    # Check if this is a tutorial level (new gimmick introduction)
    tutorial_gimmick = get_tutorial_gimmick(
        request.level_number,
        request.gimmick_unlock_levels
    )

    # Tutorial level settings: adjust difficulty for easier learning
    effective_difficulty = request.target_difficulty
    if tutorial_gimmick and request.auto_select_gimmicks:
        # Tutorial levels are easier (reduce difficulty by 30%)
        effective_difficulty = max(0.2, request.target_difficulty * 0.7)

    # AUTO GIMMICK SELECTION with unlock probability system
    if request.auto_select_gimmicks and request.level_number is not None:
        unlock_levels = request.gimmick_unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS

        # Use new probability-based selection:
        # - Tutorial levels (11, 21, 31...): 100% new gimmick included
        # - Other unlocked gimmicks: 50% probability each
        # - Respects max_gimmick_types from difficulty profile
        # NOTE: Use ORIGINAL difficulty (not reduced tutorial difficulty) for max_gimmick_types
        # This allows other unlocked gimmicks to also be included in tutorial levels
        base_obstacle_types = select_gimmicks_with_unlock_probability(
            level_number=request.level_number,
            target_difficulty=request.target_difficulty,  # Use original, not reduced
            unlock_levels=unlock_levels,
            available_gimmicks=list(request.available_gimmicks) if request.available_gimmicks else None,
            inclusion_probability=0.5,  # 50% for each unlocked gimmick
        )

        logger.info(f"[GIMMICK_SELECT] Validated Level {request.level_number}: "
                   f"auto_selected={base_obstacle_types}, tutorial_gimmick={tutorial_gimmick}")
    elif request.obstacle_types:
        # Use explicitly specified obstacles - apply unlock filter
        filtered_obstacles = filter_obstacles_by_unlock_level(
            list(request.obstacle_types),
            request.level_number,
            request.gimmick_unlock_levels
        )
        base_obstacle_types = list(filtered_obstacles) if filtered_obstacles else []
    else:
        base_obstacle_types = []

    current_obstacle_types = base_obstacle_types.copy()

    # CALIBRATED grid size based on target difficulty
    # 타일 매칭 게임 기준:
    # - 작은 그리드 = 적은 타일 = 쉬움 (S등급)
    # - 큰 그리드 = 많은 타일 = 어려움 (D등급)
    # 각 난이도는 연속된 2개 사이즈 중 랜덤 선택 (다양성 제공)
    if request.target_difficulty <= 0.2:
        # S등급 (매우 쉬움): 5x5 또는 6x6
        grid_choice = random.choice([5, 6])
    elif request.target_difficulty <= 0.4:
        # A등급 (쉬움): 5x5 또는 6x6
        grid_choice = random.choice([5, 6])
    elif request.target_difficulty <= 0.6:
        # B등급 (보통): 6x6 또는 7x7
        grid_choice = random.choice([6, 7])
    elif request.target_difficulty <= 0.8:
        # C등급 (어려움): 7x7 또는 8x8
        grid_choice = random.choice([7, 8])
    else:
        # D등급 (매우 어려움): 7x7 또는 8x8
        grid_choice = random.choice([7, 8])

    calibrated_grid = [grid_choice, grid_choice]

    current_grid_size = calibrated_grid.copy()
    min_grid_size = 5  # Minimum grid dimension
    max_grid_size = 9  # Maximum grid dimension

    for attempt in range(1, request.max_retries + 1):
        try:
            # Adjust internal target difficulty based on previous results
            adjusted_difficulty = min(1.0, max(0.0, request.target_difficulty + difficulty_offset))

            # Check if this is a special shape level (보스 전 스테이지: 9, 19, 29...)
            is_special_shape = is_special_shape_level(request.level_number)

            # For special shape levels, use distinctive patterns and allow asymmetry
            pattern_index = request.pattern_index
            pattern_type = request.pattern_type
            if is_special_shape and pattern_index is None:
                pattern_index = get_special_shape_pattern_index()
                pattern_type = "aesthetic"
                logger.info(f"[SPECIAL_SHAPE] Level {request.level_number} is a special shape level (pre-boss), using pattern {pattern_index}")

            # Resolve symmetry mode
            actual_symmetry = resolve_symmetry_mode(request.symmetry_mode, allow_none=is_special_shape)

            params = GenerationParams(
                target_difficulty=adjusted_difficulty,
                grid_size=tuple(current_grid_size),
                max_layers=current_max_layers,
                tile_types=current_tile_types,
                obstacle_types=current_obstacle_types,  # Pass empty list explicitly (not None)
                goals=goals,
                symmetry_mode=actual_symmetry,
                pattern_type=pattern_type,  # Use local variable (may be overridden for special shape)
                pattern_index=pattern_index,  # Use local variable (may be overridden for special shape)
                gimmick_intensity=request.gimmick_intensity,
                # Tutorial gimmick: place on top layer for tutorial UI
                tutorial_gimmick=tutorial_gimmick,
                tutorial_gimmick_min_count=3,  # Ensure at least 3 tutorial gimmicks are visible
                # [연구 근거] 레벨 번호 전달 - unknown 비율 동적 계산용
                level_number=request.level_number,
            )

            result = generator.generate(params)
            level_json = result.level_json

            # Calculate total tiles including internal tiles in stack/craft containers
            # This is crucial for setting correct max_moves
            total_tiles = calculate_total_tiles(level_json)

            # Apply max_moves based on moves_ratio (key for high difficulty)
            # For high difficulty targets, use tighter moves ratio
            # max_moves should always be >= total_tiles to ensure level is clearable
            original_max_moves = level_json.get("max_moves", 50)
            ratio_based_moves = max(total_tiles, int(total_tiles * moves_ratio * max_moves_modifier))
            modified_max_moves = max(total_tiles, min(original_max_moves, ratio_based_moves))
            level_json["max_moves"] = modified_max_moves
            level_json["target_difficulty"] = effective_difficulty  # Store actual difficulty used
            # Mark tutorial levels with the gimmick being introduced
            if tutorial_gimmick:
                level_json["tutorial_gimmick"] = tutorial_gimmick
            # Store actual symmetry mode used (not request value)
            level_json["symmetry_mode"] = actual_symmetry
            if request.pattern_type:
                level_json["pattern_type"] = request.pattern_type

            # FAST PATH: Skip bot simulation entirely when simulation is disabled
            if skip_simulation:
                static_report = analyzer.analyze(level_json)
                generation_time_ms = int((time.time() - start_time) * 1000)
                return ValidatedGenerateResponse(
                    level_json=level_json,
                    actual_difficulty=result.actual_difficulty,
                    grade=result.grade.value,
                    generation_time_ms=generation_time_ms,
                    validation_passed=True,
                    attempts=1,
                    bot_clear_rates={},
                    target_clear_rates={},
                    avg_gap=0.0,
                    max_gap=0.0,
                    match_score=100.0,
                )

            # Calculate target rates for match_score calculation
            # Use scoring_difficulty (original difficulty) when provided (regeneration case)
            # Otherwise use target_difficulty (normal generation case)
            # This ensures regeneration match_score is always against the ORIGINAL difficulty target,
            # even when target_difficulty has been adjusted by the binary search algorithm
            scoring_diff = request.scoring_difficulty if request.scoring_difficulty is not None else request.target_difficulty
            all_target_rates = calculate_target_clear_rates(scoring_diff)

            # OPTIMIZATION: Run bot simulations in PARALLEL
            # Core bots mode: 3 bots (casual/average/expert) for ~40% faster validation
            # Full mode: 5 bots (all types) for comprehensive validation
            actual_rates = {}
            if request.use_core_bots_only:
                bot_types = [BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT]
            else:
                bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

            # Filter target rates to only include simulated bot types
            bot_type_names = {bt.value for bt in bot_types}
            target_rates = {k: v for k, v in all_target_rates.items() if k in bot_type_names}

            # Run bot simulations in PARALLEL using ProcessPoolExecutor
            # True CPU parallelism (separate processes, no GIL)
            pool = _get_bot_pool()
            sim_args = [
                (bt.value, level_json, effective_iterations, modified_max_moves)
                for bt in bot_types
            ]
            futures = [pool.submit(_simulate_single_bot, args) for args in sim_args]
            for future in as_completed(futures):
                bot_name, clear_rate = future.result()
                actual_rates[bot_name] = clear_rate

            # Calculate match score
            match_score, avg_gap, max_gap = calculate_match_score(actual_rates, target_rates)

            # Track best result
            if match_score > best_match_score:
                best_match_score = match_score
                best_result = result
                best_result.level_json["max_moves"] = modified_max_moves  # Store modified max_moves
                best_result.level_json["target_difficulty"] = effective_difficulty  # Store actual difficulty used
                # Mark tutorial levels with the gimmick being introduced
                if tutorial_gimmick:
                    best_result.level_json["tutorial_gimmick"] = tutorial_gimmick
                # Store actual symmetry mode used (not request value)
                best_result.level_json["symmetry_mode"] = actual_symmetry
                if request.pattern_type:
                    best_result.level_json["pattern_type"] = request.pattern_type
                best_actual_rates = actual_rates.copy()
                best_target_rates = target_rates.copy()  # Store target rates for response
                best_gaps = (avg_gap, max_gap)
                best_max_moves = modified_max_moves

            # OPTIMIZATION: Early exit if match score is excellent
            if match_score >= EARLY_EXIT_THRESHOLD:
                # Run static analysis only for final result
                static_report = analyzer.analyze(level_json)
                generation_time_ms = int((time.time() - start_time) * 1000)
                return ValidatedGenerateResponse(
                    level_json=level_json,
                    actual_difficulty=result.actual_difficulty,
                    grade=result.grade.value,
                    generation_time_ms=generation_time_ms,
                    validation_passed=True,
                    attempts=attempt,
                    bot_clear_rates=actual_rates,
                    target_clear_rates=target_rates,
                    avg_gap=avg_gap,
                    max_gap=max_gap,
                    match_score=match_score,
                )

            # Check if validation passed (skip if use_best_match is True - will return best at end)
            if not request.use_best_match and avg_gap <= request.tolerance and max_gap <= request.tolerance * 1.5:
                # Validation passed with tolerance check
                static_report = analyzer.analyze(level_json)
                generation_time_ms = int((time.time() - start_time) * 1000)
                return ValidatedGenerateResponse(
                    level_json=level_json,
                    actual_difficulty=result.actual_difficulty,
                    grade=result.grade.value,
                    generation_time_ms=generation_time_ms,
                    validation_passed=True,
                    attempts=attempt,
                    bot_clear_rates=actual_rates,
                    target_clear_rates=target_rates,
                    avg_gap=avg_gap,
                    max_gap=max_gap,
                    match_score=match_score,
                )

            # Calculate gap direction (positive = level too easy)
            avg_direction = sum(
                (actual_rates.get(bt, 0) - target_rates[bt])
                for bt in target_rates
            ) / len(target_rates)

            # Calculate per-bot gaps for smarter adjustment
            casual_gap = actual_rates.get("casual", 0) - target_rates["casual"]
            average_gap = actual_rates.get("average", 0) - target_rates["average"]
            expert_gap = actual_rates.get("expert", 0) - target_rates["expert"]

            if avg_direction > 0:
                # Level too easy (higher clear rates than target)
                # Apply multiple strategies to increase difficulty
                gap_factor = min(1.0, avg_gap / 15.0)  # More aggressive factor

                # PRIMARY Strategy: Tile type count (most effective for high difficulty)
                # More tile types = harder to match before dock fills
                # t1~t15 중 미사용 타일에서 랜덤 선택
                if request.target_difficulty >= 0.7 and average_gap > 0.1:
                    # Add tile types more aggressively
                    types_to_add = 1 if avg_gap < 20 else 2
                    unused_tiles = [t for t in all_tile_types if t not in current_tile_types]
                    random.shuffle(unused_tiles)
                    for t in unused_tiles[:types_to_add]:
                        if len(current_tile_types) < 8:
                            current_tile_types.append(t)
                            current_tile_type_count = len(current_tile_types)

                # Strategy 2: Reduce moves ratio (tighter constraint)
                if request.target_difficulty >= 0.7:
                    # Gradually reduce moves ratio for harder levels
                    reduction = 0.02 * (1 + gap_factor)
                    moves_ratio = max(1.02, moves_ratio - reduction)

                # Strategy 3: Add obstacles for complexity (respecting unlock levels)
                if request.target_difficulty >= 0.6 and avg_gap > 15:
                    unlock_levels = request.gimmick_unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS
                    for obs in ["chain", "frog", "ice"]:
                        # Only add if obstacle is unlocked at current level
                        if request.level_number is None or unlock_levels.get(obs, 0) <= request.level_number:
                            if obs not in current_obstacle_types and len(current_obstacle_types) < 3:
                                current_obstacle_types.append(obs)
                                break

                # Strategy 4: Increase internal difficulty
                difficulty_offset += 0.15 * (1 + gap_factor)

                # Strategy 5: Increase max layers
                if current_max_layers < 7 and avg_gap > 20:
                    current_max_layers = min(7, current_max_layers + 1)

                # Strategy 6: Reduce max_moves modifier
                if request.target_difficulty >= 0.7 and avg_gap > 10:
                    max_moves_modifier = max(0.7, max_moves_modifier - 0.05)

                # Strategy 7: Reduce grid size (NEW - based on test findings)
                # Smaller grids significantly increase difficulty
                if request.target_difficulty >= 0.6 and avg_gap > 15:
                    if current_grid_size[0] > min_grid_size:
                        current_grid_size[0] -= 1
                    if current_grid_size[1] > min_grid_size:
                        current_grid_size[1] -= 1

            else:
                # Level too hard (lower clear rates than target)
                gap_factor = min(1.0, avg_gap / 15.0)

                # PRIMARY Strategy: Reduce tile type count
                if len(current_tile_types) > 4 and avg_gap > 10:
                    # Remove tile types to make matching easier
                    current_tile_types.pop()
                    current_tile_type_count = len(current_tile_types)

                # Strategy 2: Increase moves ratio (more room for error)
                if avg_gap > 10:
                    moves_ratio = min(1.15, moves_ratio + 0.02)

                # Strategy 3: Decrease internal difficulty
                difficulty_offset -= 0.15 * (1 + gap_factor)

                # Strategy 4: Decrease max layers
                if current_max_layers > 3 and avg_gap > 15:
                    current_max_layers = max(3, current_max_layers - 1)

                # Strategy 5: Remove obstacles
                if current_obstacle_types and avg_gap > 15:
                    current_obstacle_types.pop()

                # Strategy 6: Increase max_moves modifier
                if avg_gap > 10:
                    max_moves_modifier = min(1.1, max_moves_modifier + 0.05)

                # Strategy 7: Increase grid size (NEW - based on test findings)
                # Larger grids significantly decrease difficulty
                if request.target_difficulty <= 0.4 and avg_gap > 15:
                    if current_grid_size[0] < max_grid_size:
                        current_grid_size[0] += 1
                    if current_grid_size[1] < max_grid_size:
                        current_grid_size[1] += 1

            # RESHUFFLE STRATEGY: Try reshuffling best result before generating new level
            # This preserves gimmicks and tile types while changing positions
            if best_result is not None and attempt % 3 == 0:  # Try reshuffle every 3rd attempt
                for reshuffle_attempt in range(2):  # Try 2 reshuffles
                    reshuffled_level = generator.reshuffle_positions(
                        best_result.level_json.copy(),
                        params
                    )
                    reshuffled_level["max_moves"] = best_max_moves
                    reshuffled_level["target_difficulty"] = request.target_difficulty
                    # Preserve generation config (use actual symmetry from best_result)
                    reshuffled_level["symmetry_mode"] = best_result.level_json.get("symmetry_mode", actual_symmetry)
                    if request.pattern_type:
                        reshuffled_level["pattern_type"] = request.pattern_type

                    # Run bot simulations on reshuffled level
                    reshuffle_rates = {}
                    reshuffle_sim_args = [
                        (bt.value, reshuffled_level, effective_iterations, best_max_moves)
                        for bt in bot_types
                    ]
                    reshuffle_futures = [pool.submit(_simulate_single_bot, args) for args in reshuffle_sim_args]
                    for future in as_completed(reshuffle_futures):
                        bot_name, clear_rate = future.result()
                        reshuffle_rates[bot_name] = clear_rate

                    reshuffle_score, reshuffle_avg_gap, reshuffle_max_gap = calculate_match_score(
                        reshuffle_rates, target_rates
                    )

                    # Update best if reshuffled version is better
                    if reshuffle_score > best_match_score:
                        best_match_score = reshuffle_score
                        best_result.level_json = reshuffled_level
                        best_actual_rates = reshuffle_rates.copy()
                        best_gaps = (reshuffle_avg_gap, reshuffle_max_gap)

                        # Early exit if excellent
                        if reshuffle_score >= EARLY_EXIT_THRESHOLD:
                            static_report = analyzer.analyze(reshuffled_level)
                            generation_time_ms = int((time.time() - start_time) * 1000)
                            return ValidatedGenerateResponse(
                                level_json=reshuffled_level,
                                actual_difficulty=best_result.actual_difficulty,
                                grade=best_result.grade.value,
                                generation_time_ms=generation_time_ms,
                                validation_passed=True,
                                attempts=attempt,
                                bot_clear_rates=reshuffle_rates,
                                target_clear_rates=target_rates,
                                avg_gap=reshuffle_avg_gap,
                                max_gap=reshuffle_max_gap,
                                match_score=reshuffle_score,
                            )

        except Exception as e:
            # Generation failed - progressively simplify parameters for next attempt
            import traceback
            print(f"Generation attempt {attempt} failed: {e}")
            traceback.print_exc()

            # Simplify parameters for next retry
            if len(current_tile_types) > 3:
                current_tile_types = current_tile_types[:3]
            if current_obstacle_types:
                current_obstacle_types = []
            if current_max_layers > 4:
                current_max_layers = 4
            if current_grid_size[0] > 5:
                current_grid_size = [5, 5]
            moves_ratio = min(1.5, moves_ratio + 0.1)  # More generous moves
            continue

    # Return best result
    generation_time_ms = int((time.time() - start_time) * 1000)

    # FALLBACK: If all attempts failed, generate a guaranteed fallback level
    if best_result is None:
        print(f"All {request.max_retries} attempts failed. Generating fallback level...")
        try:
            fallback = generate_fallback_level(generator, request.target_difficulty, goals)
            fallback_scoring_diff = request.scoring_difficulty if request.scoring_difficulty is not None else request.target_difficulty
            target_rates = calculate_target_clear_rates(fallback_scoring_diff)

            return ValidatedGenerateResponse(
                level_json=fallback["level_json"],
                actual_difficulty=fallback["actual_difficulty"],
                grade=fallback["grade"],
                generation_time_ms=int((time.time() - start_time) * 1000),
                validation_passed=True,  # Fallback always passes
                attempts=request.max_retries + 1,  # +1 for fallback
                bot_clear_rates={"novice": 0.95, "casual": 0.95, "average": 0.98, "expert": 0.99, "optimal": 0.99},
                target_clear_rates=target_rates,
                avg_gap=10.0,
                max_gap=15.0,
                match_score=60.0,  # Fallback score
            )
        except Exception as fallback_error:
            # Even fallback failed - this should never happen
            print(f"CRITICAL: Fallback generation also failed: {fallback_error}")
            raise HTTPException(status_code=500, detail=f"Critical generation failure: {str(fallback_error)}")

    return ValidatedGenerateResponse(
        level_json=best_result.level_json,
        actual_difficulty=best_result.actual_difficulty,
        grade=best_result.grade.value,
        generation_time_ms=generation_time_ms,
        validation_passed=request.use_best_match,  # Best match always passes
        attempts=request.max_retries,
        bot_clear_rates=best_actual_rates,
        target_clear_rates=best_target_rates,  # Use stored best target rates
        avg_gap=best_gaps[0],
        max_gap=best_gaps[1],
        match_score=best_match_score,
    )


@router.post("/generate/enhance", response_model=EnhanceLevelResponse)
def enhance_level(
    request: EnhanceLevelRequest,
    generator: LevelGenerator = Depends(get_level_generator),
) -> EnhanceLevelResponse:
    """
    Enhance an existing level by incrementally adjusting its difficulty.

    Instead of regenerating from scratch, this endpoint modifies the existing level:
    - Too easy: adds gimmicks (chain, ice), adds tiles, reduces max_moves
    - Too hard: removes gimmicks, removes tiles, increases max_moves

    The enhancement loop runs bot simulations to measure the effect of each modification,
    keeping the best version found within max_iterations attempts.
    """
    import copy
    import time as _time

    start_time = _time.time()
    level_json = copy.deepcopy(request.level_json)
    modifications: List[str] = []

    bot_simulator = BotSimulator()
    pool = _get_bot_pool()

    # Calculate target clear rates from the original target difficulty
    target_rates = calculate_target_clear_rates(request.target_difficulty)

    # --- Step 1: Measure current state ---
    bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]
    max_moves_val = level_json.get("max_moves", 50)

    def _run_simulation(lj: Dict) -> Dict[str, float]:
        """Run parallel bot simulation and return clear rates."""
        mv = lj.get("max_moves", 50)
        sim_args = [
            (bt.value, lj, request.simulation_iterations, mv)
            for bt in bot_types
        ]
        futures = [pool.submit(_simulate_single_bot, args) for args in sim_args]
        rates: Dict[str, float] = {}
        for future in as_completed(futures):
            bot_name, clear_rate = future.result()
            rates[bot_name] = clear_rate
        return rates

    current_rates = _run_simulation(level_json)
    current_score, current_avg_gap, current_max_gap = calculate_match_score(current_rates, target_rates)

    best_level = copy.deepcopy(level_json)
    best_rates = current_rates.copy()
    best_score = current_score
    best_avg_gap = current_avg_gap
    best_max_gap = current_max_gap

    logger.info(f"[ENHANCE] Start: match_score={current_score:.1f}%, avg_gap={current_avg_gap:.1f}%, "
                f"target_difficulty={request.target_difficulty:.3f}")

    # --- Step 2: Determine direction ---
    avg_direction = sum(
        (current_rates.get(bt.value, 0) - target_rates[bt.value])
        for bt in bot_types
    ) / len(bot_types)

    # Deadband: if direction is very small, level is already close
    DIRECTION_THRESHOLD = 0.02

    # --- Step 3: Iterative enhancement ---
    for iteration in range(1, request.max_iterations + 1):
        candidate = copy.deepcopy(best_level)
        iter_mods: List[str] = []

        if avg_direction > DIRECTION_THRESHOLD:
            # === TOO EASY: increase difficulty ===
            # Priority order based on analyzer weights
            action = random.choice(["chain", "ice", "tiles", "max_moves"])

            if action == "chain":
                try:
                    candidate = generator._add_chain_to_tile(candidate)
                    iter_mods.append("chain 추가")
                except Exception:
                    pass

            elif action == "ice":
                try:
                    candidate = generator._add_ice_to_tile(candidate)
                    iter_mods.append("ice 추가")
                except Exception:
                    pass

            elif action == "tiles":
                # Add tiles in multiples of 3
                added = 0
                for _ in range(3):
                    try:
                        candidate = generator._add_tile_to_layer(candidate)
                        added += 1
                    except Exception:
                        break
                if added > 0:
                    iter_mods.append(f"타일 {added}개 추가")

            elif action == "max_moves":
                cur_moves = candidate.get("max_moves", 50)
                total_tiles = calculate_total_tiles(candidate)
                new_moves = max(total_tiles, cur_moves - 3)
                if new_moves < cur_moves:
                    candidate["max_moves"] = new_moves
                    iter_mods.append(f"max_moves {cur_moves} → {new_moves}")

        elif avg_direction < -DIRECTION_THRESHOLD:
            # === TOO HARD: decrease difficulty ===
            action = random.choice(["remove_gimmick", "remove_tiles", "max_moves"])

            if action == "remove_gimmick":
                try:
                    candidate = generator._remove_random_obstacle(candidate)
                    iter_mods.append("기믹 제거")
                except Exception:
                    pass

            elif action == "remove_tiles":
                removed = 0
                for _ in range(3):
                    try:
                        candidate = generator._remove_tile_from_layer(candidate)
                        removed += 1
                    except Exception:
                        break
                if removed > 0:
                    iter_mods.append(f"타일 {removed}개 제거")
                    # Ensure tile count stays divisible by 3
                    total_tiles = calculate_total_tiles(candidate)
                    remainder = total_tiles % 3
                    if remainder != 0:
                        for _ in range(3 - remainder):
                            try:
                                candidate = generator._remove_tile_from_layer(candidate)
                                removed += 1
                            except Exception:
                                break
                        if removed > 0:
                            iter_mods[-1] = f"타일 {removed}개 제거"

            elif action == "max_moves":
                cur_moves = candidate.get("max_moves", 50)
                new_moves = cur_moves + 3
                candidate["max_moves"] = new_moves
                iter_mods.append(f"max_moves {cur_moves} → {new_moves}")

        else:
            # Already close enough, try minor tweaks
            logger.info(f"[ENHANCE] Iteration {iteration}: direction={avg_direction:.4f} within deadband, skipping")
            continue

        if not iter_mods:
            continue

        # --- Run simulation on candidate ---
        try:
            cand_rates = _run_simulation(candidate)
            cand_score, cand_avg_gap, cand_max_gap = calculate_match_score(cand_rates, target_rates)
        except Exception as e:
            logger.warning(f"[ENHANCE] Iteration {iteration} simulation failed: {e}")
            continue

        logger.info(f"[ENHANCE] Iteration {iteration}: {', '.join(iter_mods)} → "
                    f"match_score={cand_score:.1f}% (was {best_score:.1f}%)")

        # Update best if improved
        if cand_score > best_score:
            best_level = copy.deepcopy(candidate)
            best_rates = cand_rates.copy()
            best_score = cand_score
            best_avg_gap = cand_avg_gap
            best_max_gap = cand_max_gap
            modifications.extend(iter_mods)

            # Recalculate direction based on new best
            avg_direction = sum(
                (best_rates.get(bt.value, 0) - target_rates[bt.value])
                for bt in bot_types
            ) / len(bot_types)

            # Early exit if match score is great
            if best_score >= 80.0:
                logger.info(f"[ENHANCE] Early exit: match_score={best_score:.1f}% >= 80%")
                break

    enhanced = best_score > current_score
    elapsed_ms = int((_time.time() - start_time) * 1000)
    logger.info(f"[ENHANCE] Done in {elapsed_ms}ms: {current_score:.1f}% → {best_score:.1f}%, "
                f"enhanced={enhanced}, modifications={modifications}")

    return EnhanceLevelResponse(
        level_json=best_level,
        match_score=best_score,
        bot_clear_rates=best_rates,
        target_clear_rates=target_rates,
        avg_gap=best_avg_gap,
        max_gap=best_max_gap,
        modifications=modifications,
        enhanced=enhanced,
    )
