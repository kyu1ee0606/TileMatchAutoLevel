"""Multi-bot difficulty assessment API routes."""
from fastapi import APIRouter, HTTPException
from typing import List

from ...models.schemas import (
    MultiBotAssessRequest,
    MultiBotAssessResponse,
    BotResultItem,
    ComprehensiveAssessRequest,
    ComprehensiveAssessResponse,
    BotProfileListResponse,
    ErrorResponse,
)
from ...models.bot_profile import (
    BotType,
    BotTeam,
    BotProfile,
    get_all_profiles,
    get_profile,
    create_custom_profile,
    PREDEFINED_PROFILES,
)
from ...core.bot_simulator import get_bot_simulator
from ...core.difficulty_assessor import get_difficulty_assessor


router = APIRouter(prefix="/api/assess", tags=["Assessment"])


@router.post(
    "/multibot",
    response_model=MultiBotAssessResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Multi-bot difficulty assessment",
    description="""
    Run difficulty assessment using multiple bot profiles with different skill levels.

    **Bot Types:**
    - `novice`: Beginner player simulation (random-like, high mistakes)
    - `casual`: Casual player simulation (basic strategy)
    - `average`: Average player simulation (greedy strategy)
    - `expert`: Expert player simulation (optimized strategy)
    - `optimal`: Perfect play simulation (MCTS-based)

    **Quick Mode:** Uses only 3 bots (novice, casual, average) with fewer iterations
    for faster results. Good for real-time feedback during level editing.
    """,
)
async def assess_multibot(request: MultiBotAssessRequest):
    """
    Run multi-bot difficulty assessment on a level.

    This endpoint simulates the level with multiple bot profiles representing
    different player skill levels. Each bot runs multiple iterations, and
    the results are aggregated to provide a comprehensive difficulty assessment.

    Returns:
        MultiBotAssessResponse with per-bot results and overall difficulty metrics.
    """
    try:
        simulator = get_bot_simulator()

        # Build bot team
        if request.quick_mode:
            team = BotTeam.casual_team(iterations_per_bot=min(50, request.iterations_per_bot))
        elif request.bot_types:
            # Custom bot selection
            profiles: List[BotProfile] = []
            for bot_type_str in request.bot_types:
                try:
                    bot_type = BotType(bot_type_str.lower())
                    profiles.append(get_profile(bot_type))
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid bot type: {bot_type_str}. "
                               f"Valid types: {[t.value for t in BotType]}"
                    )
            team = BotTeam(profiles=profiles, iterations_per_bot=request.iterations_per_bot)
        else:
            # Default: all bots
            team = BotTeam.default_team(iterations_per_bot=request.iterations_per_bot)

        # Apply custom profile overrides if provided
        if request.custom_profiles:
            for custom_config in request.custom_profiles:
                try:
                    bot_type = BotType(custom_config.bot_type.lower())
                except ValueError:
                    continue

                # Find and update the profile
                for i, profile in enumerate(team.profiles):
                    if profile.bot_type == bot_type:
                        # Create modified profile
                        overrides = {}
                        if custom_config.mistake_rate is not None:
                            overrides["mistake_rate"] = custom_config.mistake_rate
                        if custom_config.lookahead_depth is not None:
                            overrides["lookahead_depth"] = custom_config.lookahead_depth
                        if custom_config.goal_priority is not None:
                            overrides["goal_priority"] = custom_config.goal_priority
                        if custom_config.weight is not None:
                            overrides["weight"] = custom_config.weight

                        if overrides:
                            team.profiles[i] = create_custom_profile(
                                name=f"Custom {profile.name}",
                                base_type=bot_type,
                                **overrides
                            )
                        break

        # Run assessment
        result = simulator.assess_difficulty(
            level_json=request.level_json,
            team=team,
            max_moves=request.max_moves,
            parallel=True,
        )

        # Convert to response model
        bot_results = [
            BotResultItem(
                bot_type=r.bot_type.value,
                bot_name=r.bot_name,
                iterations=r.iterations,
                clear_rate=r.clear_rate,
                avg_moves=r.avg_moves,
                min_moves=r.min_moves,
                max_moves=r.max_moves,
                std_moves=r.std_moves,
                avg_combo=r.avg_combo,
                avg_tiles_cleared=r.avg_tiles_cleared,
            )
            for r in result.bot_results
        ]

        return MultiBotAssessResponse(
            bot_results=bot_results,
            overall_difficulty=result.overall_difficulty,
            difficulty_grade=result.difficulty_grade,
            target_audience=result.target_audience,
            recommended_moves=result.recommended_moves,
            difficulty_variance=result.difficulty_variance,
            analysis_summary=result.analysis_summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/comprehensive",
    response_model=ComprehensiveAssessResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Comprehensive difficulty assessment",
    description="""
    Run comprehensive difficulty assessment combining static analysis and multi-bot simulation.

    **Assessment Modes:**
    - `quick`: Fast assessment with reduced iterations (good for real-time feedback)
    - `standard`: Balanced assessment (default)
    - `detailed`: Thorough assessment with high iterations (for final validation)

    This endpoint combines:
    1. **Static Analysis**: Metrics-based analysis of level structure
    2. **Simulation Analysis**: Multi-bot Monte Carlo simulation
    3. **Combined Analysis**: Weighted combination with confidence scoring
    """,
)
async def assess_comprehensive(request: ComprehensiveAssessRequest):
    """
    Run comprehensive difficulty assessment (static + simulation).

    Returns both static metrics-based analysis and simulation-based analysis,
    along with a combined score and confidence level.
    """
    try:
        assessor = get_difficulty_assessor()

        # Select assessment method based on mode
        if request.assessment_mode == "quick":
            result = assessor.quick_assess(
                level_json=request.level_json,
                iterations=min(50, request.iterations_per_bot),
                max_moves=request.max_moves,
            )
        elif request.assessment_mode == "detailed":
            result = assessor.detailed_assess(
                level_json=request.level_json,
                iterations=max(request.iterations_per_bot, 500),
                max_moves=request.max_moves,
            )
        else:  # standard
            result = assessor.assess(
                level_json=request.level_json,
                iterations_per_bot=request.iterations_per_bot,
                max_moves=request.max_moves,
            )

        return ComprehensiveAssessResponse(**result.to_dict())

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/profiles",
    response_model=BotProfileListResponse,
    summary="List available bot profiles",
    description="Get all available predefined bot profiles with their configurations.",
)
async def list_bot_profiles():
    """
    List all available bot profiles.

    Returns predefined profiles for novice, casual, average, expert, and optimal bots.
    These profiles can be used as references for custom configurations.
    """
    profiles = get_all_profiles()

    return BotProfileListResponse(
        profiles=[p.to_dict() for p in profiles]
    )


@router.get(
    "/profiles/{bot_type}",
    responses={404: {"model": ErrorResponse}},
    summary="Get specific bot profile",
    description="Get detailed configuration for a specific bot profile.",
)
async def get_bot_profile(bot_type: str):
    """Get a specific bot profile by type."""
    try:
        bt = BotType(bot_type.lower())
        profile = get_profile(bt)
        return profile.to_dict()
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Bot type not found: {bot_type}. "
                   f"Valid types: {[t.value for t in BotType]}"
        )
