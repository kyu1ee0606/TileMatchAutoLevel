"""Level generation API routes."""
from fastapi import APIRouter, Depends, HTTPException

from ...models.schemas import (
    GenerateRequest,
    GenerateResponse,
    SimulateRequest,
    SimulateResponse,
)
from ...models.level import GenerationParams
from ...core.generator import LevelGenerator
from ...core.simulator import LevelSimulator
from ..deps import get_level_generator, get_level_simulator

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
        goals = None
        if request.goals:
            goals = [{"type": g.type, "count": g.count} for g in request.goals]

        params = GenerationParams(
            target_difficulty=request.target_difficulty,
            grid_size=tuple(request.grid_size),
            max_layers=request.max_layers,
            tile_types=request.tile_types,
            obstacle_types=request.obstacle_types,
            goals=goals,
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
