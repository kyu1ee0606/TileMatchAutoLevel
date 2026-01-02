"""Level generation API routes."""
import time
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Tuple

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
from ..deps import get_level_generator, get_level_simulator


# Target clear rates per bot type (based on target_difficulty=0.5 standard)
# These define what "balanced" means for each bot profile
BASE_TARGET_RATES = {
    "novice": 0.60,
    "casual": 0.75,
    "average": 0.85,
    "expert": 0.95,
    "optimal": 0.99,
}


def calculate_target_clear_rates(target_difficulty: float) -> Dict[str, float]:
    """
    Calculate target clear rates based on target difficulty.

    target_difficulty=0.0: Very easy, all bots ~95-99%
    target_difficulty=0.5: Balanced (base rates)
    target_difficulty=1.0: Very hard, all bots ~5-30%
    """
    rates = {}
    for bot_type, base_rate in BASE_TARGET_RATES.items():
        if target_difficulty <= 0.5:
            # Easier: interpolate from 0.99 to base_rate
            t = target_difficulty / 0.5
            rate = 0.99 - t * (0.99 - base_rate)
        else:
            # Harder: interpolate from base_rate to low rates
            t = (target_difficulty - 0.5) / 0.5
            # Harder targets: novice->0.05, casual->0.10, average->0.20, expert->0.40, optimal->0.60
            hard_targets = {
                "novice": 0.05,
                "casual": 0.10,
                "average": 0.20,
                "expert": 0.40,
                "optimal": 0.60,
            }
            hard_rate = hard_targets.get(bot_type, 0.30)
            rate = base_rate - t * (base_rate - hard_rate)
        rates[bot_type] = max(0.01, min(0.99, rate))
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

        params = GenerationParams(
            target_difficulty=request.target_difficulty,
            grid_size=tuple(request.grid_size),
            max_layers=request.max_layers,
            tile_types=request.tile_types,
            obstacle_types=request.obstacle_types,
            goals=goals,
            obstacle_counts=obstacle_counts,
            total_tile_count=request.total_tile_count,
            active_layer_count=request.active_layer_count,
            layer_tile_configs=layer_tile_configs,
            layer_obstacle_configs=layer_obstacle_configs,
            symmetry_mode=request.symmetry_mode,
            pattern_type=request.pattern_type,
        )

        result = generator.generate(params)

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

    # Calculate target clear rates based on target_difficulty
    target_rates = calculate_target_clear_rates(request.target_difficulty)

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
    best_gaps = (100.0, 100.0)
    best_max_moves = 50

    # Adaptive parameters for retry
    current_max_layers = request.max_layers
    difficulty_offset = 0.0  # Adjust target difficulty for generator
    max_moves_modifier = 1.0  # Reduce max_moves for harder levels

    # Initial tile types from request (or default)
    base_tile_types = list(request.tile_types) if request.tile_types else ["t0", "t2", "t4", "t5", "t6"]
    all_tile_types = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7"]  # Available tile types
    current_tile_types = base_tile_types.copy()

    # Initial obstacle types from request (or empty)
    base_obstacle_types = list(request.obstacle_types) if request.obstacle_types else []
    available_obstacles = ["chain", "frog", "ice", "grass", "bomb", "curtain"]
    current_obstacle_types = base_obstacle_types.copy()

    # Initial grid size
    current_grid_size = list(request.grid_size)

    for attempt in range(1, request.max_retries + 1):
        try:
            # Adjust internal target difficulty based on previous results
            adjusted_difficulty = min(1.0, max(0.0, request.target_difficulty + difficulty_offset))

            params = GenerationParams(
                target_difficulty=adjusted_difficulty,
                grid_size=tuple(current_grid_size),
                max_layers=current_max_layers,
                tile_types=current_tile_types,
                obstacle_types=current_obstacle_types if current_obstacle_types else None,
                goals=goals,
                symmetry_mode=request.symmetry_mode,
                pattern_type=request.pattern_type,
            )

            result = generator.generate(params)
            level_json = result.level_json

            # Apply max_moves modifier for harder levels
            original_max_moves = level_json.get("max_moves", 50)
            modified_max_moves = max(20, int(original_max_moves * max_moves_modifier))
            level_json["max_moves"] = modified_max_moves

            # Run bot simulation for validation
            actual_rates = {}
            bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

            for bot_type in bot_types:
                profile = get_profile(bot_type)
                sim_result = bot_simulator.simulate_with_profile(
                    level_json,
                    profile,
                    iterations=request.simulation_iterations,
                    max_moves=modified_max_moves,
                )
                actual_rates[bot_type.value] = sim_result.clear_rate

            # Calculate match score
            match_score, avg_gap, max_gap = calculate_match_score(actual_rates, target_rates)

            # Track best result
            if match_score > best_match_score:
                best_match_score = match_score
                best_result = result
                best_result.level_json["max_moves"] = modified_max_moves  # Store modified max_moves
                best_actual_rates = actual_rates.copy()
                best_gaps = (avg_gap, max_gap)
                best_max_moves = modified_max_moves

            # Check if validation passed
            if avg_gap <= request.tolerance and max_gap <= request.tolerance * 1.5:
                # Validation passed
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

            if avg_direction > 0:
                # Level too easy (higher clear rates than target)
                # Apply multiple strategies to increase difficulty
                gap_factor = min(1.0, avg_gap / 20.0)

                # Strategy 1: Increase internal difficulty
                difficulty_offset += 0.20 * (1 + gap_factor)

                # Strategy 2: Increase max layers
                if current_max_layers < 7:
                    current_max_layers = min(7, current_max_layers + 1)

                # Strategy 3: Add obstacles progressively for hard targets
                if request.target_difficulty >= 0.5 and avg_gap > 15:
                    # Add obstacles if not enough
                    for obs in ["chain", "ice", "frog"]:
                        if obs not in current_obstacle_types and len(current_obstacle_types) < 3:
                            current_obstacle_types.append(obs)
                            break  # Add one at a time

                # Strategy 4: Add more tile types for harder matching
                if request.target_difficulty >= 0.6 and avg_gap > 20:
                    for t in all_tile_types:
                        if t not in current_tile_types and len(current_tile_types) < 7:
                            current_tile_types.append(t)
                            break  # Add one at a time

                # Strategy 5: Reduce max_moves for harder levels
                if request.target_difficulty >= 0.7 and avg_gap > 15:
                    max_moves_modifier = max(0.6, max_moves_modifier - 0.1)

                # Strategy 6: Increase grid size for very hard levels
                if request.target_difficulty >= 0.8 and avg_gap > 25:
                    if current_grid_size[0] < 9:
                        current_grid_size[0] = min(9, current_grid_size[0] + 1)
                    if current_grid_size[1] < 9:
                        current_grid_size[1] = min(9, current_grid_size[1] + 1)

            else:
                # Level too hard (lower clear rates than target)
                gap_factor = min(1.0, avg_gap / 20.0)

                # Strategy 1: Decrease internal difficulty
                difficulty_offset -= 0.20 * (1 + gap_factor)

                # Strategy 2: Decrease max layers
                if current_max_layers > 3:
                    current_max_layers = max(3, current_max_layers - 1)

                # Strategy 3: Remove obstacles progressively
                if current_obstacle_types and avg_gap > 15:
                    current_obstacle_types.pop()  # Remove last added obstacle

                # Strategy 4: Increase max_moves
                if avg_gap > 15:
                    max_moves_modifier = min(1.2, max_moves_modifier + 0.1)

                # Strategy 5: Reduce grid size
                if current_grid_size[0] > request.grid_size[0]:
                    current_grid_size[0] = max(request.grid_size[0], current_grid_size[0] - 1)
                if current_grid_size[1] > request.grid_size[1]:
                    current_grid_size[1] = max(request.grid_size[1], current_grid_size[1] - 1)

        except Exception as e:
            # Generation failed, try again with default params
            continue

    # Return best result even if validation didn't pass
    generation_time_ms = int((time.time() - start_time) * 1000)

    if best_result is None:
        raise HTTPException(status_code=400, detail="All generation attempts failed")

    return ValidatedGenerateResponse(
        level_json=best_result.level_json,
        actual_difficulty=best_result.actual_difficulty,
        grade=best_result.grade.value,
        generation_time_ms=generation_time_ms,
        validation_passed=False,
        attempts=request.max_retries,
        bot_clear_rates=best_actual_rates,
        target_clear_rates=target_rates,
        avg_gap=best_gaps[0],
        max_gap=best_gaps[1],
        match_score=best_match_score,
    )
