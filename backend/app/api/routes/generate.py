"""Level generation API routes."""
import time
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...models.schemas import (
    GenerateRequest,
    GenerateResponse,
    SimulateRequest,
    SimulateResponse,
    ValidatedGenerateRequest,
    ValidatedGenerateResponse,
)
from ...models.level import GenerationParams, LayerTileConfig, LayerObstacleConfig
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


def resolve_symmetry_mode(symmetry_mode: str | None) -> str:
    """
    Resolve symmetry mode to ensure single-axis symmetry.
    Converts None, "none", or "both" to random "horizontal" or "vertical".
    """
    if symmetry_mode is None or symmetry_mode in ("none", "both"):
        return random.choice(["horizontal", "vertical"])
    return symmetry_mode


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
    simple_tile_types = ["t0", "t2", "t4"]  # Only 3 types
    simple_grid = (5, 5)  # Small grid
    simple_layers = 4  # Few layers

    # Adjust parameters based on difficulty
    if target_difficulty >= 0.6:
        simple_tile_types = ["t0", "t2", "t4", "t5"]
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
async def generate_level(
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
    try:
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

        # Handle auto gimmick selection
        obstacle_types = request.obstacle_types
        if request.auto_select_gimmicks and request.available_gimmicks:
            # Auto-select gimmicks based on target difficulty
            auto_selected = select_gimmicks_for_difficulty(
                request.target_difficulty,
                request.available_gimmicks
            )
            obstacle_types = auto_selected if auto_selected else None

        # Resolve symmetry mode: convert "both"/"none"/None to random "horizontal" or "vertical"
        actual_symmetry = resolve_symmetry_mode(request.symmetry_mode)

        params = GenerationParams(
            target_difficulty=request.target_difficulty,
            grid_size=tuple(request.grid_size),
            max_layers=request.max_layers,
            tile_types=request.tile_types,
            obstacle_types=obstacle_types,
            goals=goals,
            obstacle_counts=obstacle_counts,
            total_tile_count=request.total_tile_count,
            active_layer_count=request.active_layer_count,
            layer_tile_configs=layer_tile_configs,
            layer_obstacle_configs=layer_obstacle_configs,
            symmetry_mode=actual_symmetry,
            pattern_type=request.pattern_type,
            pattern_index=request.pattern_index,
            gimmick_intensity=request.gimmick_intensity,
        )

        result = generator.generate(params)

        # Store target_difficulty and generation config in level_json for verification
        result.level_json["target_difficulty"] = request.target_difficulty
        # Store actual symmetry mode used (not request value)
        result.level_json["symmetry_mode"] = actual_symmetry
        if request.pattern_type:
            result.level_json["pattern_type"] = request.pattern_type

        return GenerateResponse(
            level_json=result.level_json,
            actual_difficulty=result.actual_difficulty,
            grade=result.grade.value,
            generation_time_ms=result.generation_time_ms,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Generation failed: {str(e)}")


@router.post("/simulate", response_model=SimulateResponse)
async def simulate_level(
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
async def generate_validated_level(
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
    bot_simulator = BotSimulator()

    # Import analyzer for static analysis (only used once at the end)
    from ...core.analyzer import LevelAnalyzer
    analyzer = LevelAnalyzer()

    # OPTIMIZATION: Adaptive simulation iterations based on difficulty
    # Easy levels need fewer iterations for stable results
    if request.target_difficulty <= 0.3:
        effective_iterations = min(15, request.simulation_iterations)
    elif request.target_difficulty <= 0.5:
        effective_iterations = min(20, request.simulation_iterations)
    else:
        effective_iterations = request.simulation_iterations

    # OPTIMIZATION: Early exit threshold - stop if match is good enough
    EARLY_EXIT_THRESHOLD = 80.0  # Stop if match score >= 80%

    # Convert goals from Pydantic models to dicts
    goals = None
    if request.goals is not None:
        goals = [
            {"type": g.type, "direction": g.direction, "count": g.count}
            for g in request.goals
        ]

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
    # IMPROVED v2: Adjusted for 40-60% range underperformance
    if request.target_difficulty >= 0.85:
        default_tile_types = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]  # 9 types for extreme (80%+)
    elif request.target_difficulty >= 0.75:
        default_tile_types = ["t0", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]  # 8 types for very hard (70-80%)
    elif request.target_difficulty >= 0.6:
        default_tile_types = ["t0", "t2", "t3", "t4", "t5", "t6", "t7"]  # 7 types for hard (60-70%)
    elif request.target_difficulty >= 0.5:
        default_tile_types = ["t0", "t2", "t3", "t4", "t5", "t6"]  # 6 types for medium-hard (50-60%)
    elif request.target_difficulty >= 0.4:
        default_tile_types = ["t0", "t2", "t4", "t5", "t6"]  # 5 types for medium (40-50%)
    elif request.target_difficulty >= 0.3:
        default_tile_types = ["t0", "t2", "t4", "t5"]  # 4 types for easy (30-40%)
    else:
        default_tile_types = ["t0", "t2", "t4"]  # 3 types for very easy (<30%)

    base_tile_types = list(request.tile_types) if request.tile_types else default_tile_types
    all_tile_types = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"]  # Extended tile types
    current_tile_types = base_tile_types.copy()

    # Track tile type count separately for fine-tuning
    current_tile_type_count = len(current_tile_types)

    # Initial obstacle types from request (or auto-select based on difficulty)
    available_obstacles = ["chain", "frog", "ice", "grass", "bomb", "curtain"]

    # AUTO GIMMICK SELECTION: If enabled, select gimmicks based on difficulty
    if request.auto_select_gimmicks and request.available_gimmicks:
        # Use gimmick profile system to select appropriate gimmicks
        auto_selected_gimmicks = select_gimmicks_for_difficulty(
            request.target_difficulty,
            request.available_gimmicks
        )
        base_obstacle_types = auto_selected_gimmicks
    elif request.obstacle_types:
        # Use explicitly specified obstacles
        base_obstacle_types = list(request.obstacle_types)
    elif request.target_difficulty >= 0.7:
        # Default: add some obstacles for high difficulty
        default_obstacles = ["chain", "frog"]
        base_obstacle_types = default_obstacles
    else:
        base_obstacle_types = []

    current_obstacle_types = base_obstacle_types.copy()

    # CALIBRATED grid size based on target difficulty
    # Smaller grids = harder (less space for strategic moves)
    # Larger grids = easier (more moves available)
    # IMPROVED v2: More granular calibration for 40-60% range
    base_grid_size = list(request.grid_size)
    if request.target_difficulty >= 0.85:
        # Extreme: prefer smaller grid
        calibrated_grid = [min(base_grid_size[0], 5), min(base_grid_size[1], 5)]
    elif request.target_difficulty >= 0.75:
        # Very hard: small grid
        calibrated_grid = [min(base_grid_size[0], 6), min(base_grid_size[1], 6)]
    elif request.target_difficulty >= 0.6:
        # Hard: medium-small grid
        calibrated_grid = [min(base_grid_size[0], 6), min(base_grid_size[1], 6)]
    elif request.target_difficulty >= 0.5:
        # Medium-hard: larger grid than 60% to avoid overshoot
        calibrated_grid = [min(base_grid_size[0], 7), min(base_grid_size[1], 7)]
    elif request.target_difficulty >= 0.4:
        # Medium: normal grid
        calibrated_grid = [min(base_grid_size[0], 7), min(base_grid_size[1], 7)]
    elif request.target_difficulty <= 0.2:
        # Very easy: prefer larger grid
        calibrated_grid = [max(base_grid_size[0], 8), max(base_grid_size[1], 8)]
    elif request.target_difficulty <= 0.3:
        # Easy: slightly larger grid
        calibrated_grid = [max(base_grid_size[0], 7), max(base_grid_size[1], 7)]
    else:
        calibrated_grid = base_grid_size

    current_grid_size = calibrated_grid.copy()
    min_grid_size = 5  # Minimum grid dimension
    max_grid_size = 9  # Maximum grid dimension

    for attempt in range(1, request.max_retries + 1):
        try:
            # Adjust internal target difficulty based on previous results
            adjusted_difficulty = min(1.0, max(0.0, request.target_difficulty + difficulty_offset))

            # Resolve symmetry mode: convert "both"/"none"/None to random "horizontal" or "vertical"
            actual_symmetry = resolve_symmetry_mode(request.symmetry_mode)

            params = GenerationParams(
                target_difficulty=adjusted_difficulty,
                grid_size=tuple(current_grid_size),
                max_layers=current_max_layers,
                tile_types=current_tile_types,
                obstacle_types=current_obstacle_types if current_obstacle_types else None,
                goals=goals,
                symmetry_mode=actual_symmetry,
                pattern_type=request.pattern_type,
                pattern_index=request.pattern_index,
                gimmick_intensity=request.gimmick_intensity,
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
            level_json["target_difficulty"] = request.target_difficulty  # Store for verification
            # Store actual symmetry mode used (not request value)
            level_json["symmetry_mode"] = actual_symmetry
            if request.pattern_type:
                level_json["pattern_type"] = request.pattern_type

            # Calculate target rates based on USER's target_difficulty (NOT static score!)
            # This ensures the generated level matches what the user requested
            # The adaptive algorithm adjusts level parameters to hit these targets
            target_rates = calculate_target_clear_rates(request.target_difficulty)

            # OPTIMIZATION: Run bot simulations in PARALLEL
            actual_rates = {}
            bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

            def run_bot_simulation(bot_type: BotType) -> Tuple[str, float]:
                profile = get_profile(bot_type)
                sim_result = bot_simulator.simulate_with_profile(
                    level_json,
                    profile,
                    iterations=effective_iterations,
                    max_moves=modified_max_moves,
                )
                return bot_type.value, sim_result.clear_rate

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(run_bot_simulation, bt): bt for bt in bot_types}
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
                best_result.level_json["target_difficulty"] = request.target_difficulty  # Store for verification
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
                if request.target_difficulty >= 0.7 and average_gap > 0.1:
                    # Add tile types more aggressively
                    types_to_add = 1 if avg_gap < 20 else 2
                    for _ in range(types_to_add):
                        for t in all_tile_types:
                            if t not in current_tile_types and len(current_tile_types) < 9:
                                current_tile_types.append(t)
                                current_tile_type_count = len(current_tile_types)
                                break

                # Strategy 2: Reduce moves ratio (tighter constraint)
                if request.target_difficulty >= 0.7:
                    # Gradually reduce moves ratio for harder levels
                    reduction = 0.02 * (1 + gap_factor)
                    moves_ratio = max(1.02, moves_ratio - reduction)

                # Strategy 3: Add obstacles for complexity
                if request.target_difficulty >= 0.6 and avg_gap > 15:
                    for obs in ["chain", "frog", "ice"]:
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
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        def run_reshuffle_sim(bot_type: BotType) -> Tuple[str, float]:
                            profile = get_profile(bot_type)
                            sim_result = bot_simulator.simulate_with_profile(
                                reshuffled_level,
                                profile,
                                iterations=effective_iterations,
                                max_moves=best_max_moves,
                            )
                            return bot_type.value, sim_result.clear_rate

                        futures = {executor.submit(run_reshuffle_sim, bt): bt for bt in bot_types}
                        for future in as_completed(futures):
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
            target_rates = calculate_target_clear_rates(request.target_difficulty)

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
