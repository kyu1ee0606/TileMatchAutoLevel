"""Level analysis API routes."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any

from ...models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
    BatchAnalyzeResultItem,
    AutoPlayRequest,
    AutoPlayResponse,
    BotClearStats,
)
from ...models.bot_profile import BotType, get_profile, PREDEFINED_PROFILES
from ...core.analyzer import LevelAnalyzer
from ...core.bot_simulator import BotSimulator
from ..deps import get_level_analyzer

router = APIRouter(prefix="/api", tags=["analyze"])

# Base bot target clear rates (for target_difficulty=0.5)
BASE_TARGET_CLEAR_RATES = {
    "novice": 0.40,
    "casual": 0.60,
    "average": 0.75,
    "expert": 0.90,
    "optimal": 0.98,
}

# Bot display names (Korean)
BOT_DISPLAY_NAMES = {
    "novice": "초보자",
    "casual": "캐주얼",
    "average": "일반",
    "expert": "숙련자",
    "optimal": "최적",
}

# Bot weights for difficulty calculation (mid-tier bots weighted higher)
BOT_WEIGHTS = {
    "novice": 1.0,
    "casual": 1.5,
    "average": 2.0,  # Most weight on average player
    "expert": 1.5,
    "optimal": 1.0,
}


def calculate_target_clear_rates(target_difficulty: float) -> Dict[str, float]:
    """
    Calculate target clear rates based on target difficulty.

    target_difficulty=0.0: Very easy, all bots ~95-99%
    target_difficulty=0.5: Balanced (base rates)
    target_difficulty=1.0: Very hard, lower rates based on game mechanics

    NOTE: Hard targets are calibrated based on game simulation testing.
    The tile matching game has limited variance between bot skill levels
    when levels are mathematically solvable. Key difficulty drivers are:
    - Tile type count (more types = harder to match before dock fills)
    - Move constraint (tighter moves = less room for suboptimal play)
    """
    rates = {}
    for bot_type, base_rate in BASE_TARGET_CLEAR_RATES.items():
        if target_difficulty <= 0.5:
            # Easier: interpolate from 0.99 to base_rate
            t = target_difficulty / 0.5
            rate = 0.99 - t * (0.99 - base_rate)
        else:
            # Harder: interpolate from base_rate to realistic hard targets
            t = (target_difficulty - 0.5) / 0.5
            # Adjusted hard targets based on game mechanics testing:
            # - Novice/Casual are most affected by tile type count
            # - Expert/Optimal almost always clear solvable levels (game mechanics limitation)
            # - Target rates reflect achievable variance, not ideal distribution
            hard_targets = {
                "novice": 0.20,    # Strongly affected by tile type count
                "casual": 0.40,    # Moderately affected
                "average": 0.70,   # Good strategy limits variance
                "expert": 0.90,    # Very good at solving, minor failures only
                "optimal": 0.95,   # Near-perfect, only fails on edge cases
            }
            hard_rate = hard_targets.get(bot_type, 0.40)
            rate = base_rate - t * (base_rate - hard_rate)
        rates[bot_type] = max(0.01, min(0.99, rate))
    return rates


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_level(
    request: AnalyzeRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> AnalyzeResponse:
    """
    Analyze a level and return difficulty metrics.

    Args:
        request: AnalyzeRequest with level_json.
        analyzer: LevelAnalyzer dependency.

    Returns:
        AnalyzeResponse with score, grade, metrics, and recommendations.
    """
    try:
        report = analyzer.analyze(request.level_json)
        return AnalyzeResponse(**report.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Analysis failed: {str(e)}")


@router.post("/levels/batch-analyze", response_model=BatchAnalyzeResponse)
async def batch_analyze_levels(
    request: BatchAnalyzeRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> BatchAnalyzeResponse:
    """
    Analyze multiple levels in batch.

    Args:
        request: BatchAnalyzeRequest with levels or level_ids.
        analyzer: LevelAnalyzer dependency.

    Returns:
        BatchAnalyzeResponse with results for each level.
    """
    results: List[BatchAnalyzeResultItem] = []

    if request.levels:
        # Analyze provided level JSONs
        for i, level_json in enumerate(request.levels):
            try:
                report = analyzer.analyze(level_json)
                results.append(BatchAnalyzeResultItem(
                    level_id=f"level_{i}",
                    score=report.score,
                    grade=report.grade.value,
                    metrics=report.metrics.to_dict(),
                ))
            except Exception as e:
                results.append(BatchAnalyzeResultItem(
                    level_id=f"level_{i}",
                    score=0,
                    grade="?",
                    metrics={"error": str(e)},
                ))
    elif request.level_ids and request.board_id:
        # TODO: Load levels from GBoost and analyze
        # This would require async loading from GBoost client
        raise HTTPException(
            status_code=501,
            detail="Loading levels from GBoost in batch is not yet implemented"
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Either 'levels' or 'level_ids' with 'board_id' must be provided"
        )

    return BatchAnalyzeResponse(results=results)


def _calculate_max_moves(level_json: Dict[str, Any]) -> int:
    """Calculate max moves for auto-play simulation.

    Ensures max_moves is at least total_tiles to make level clearable.
    This fixes issues with saved levels that have incorrectly low max_moves.
    """
    # Calculate based on total tiles (including stack/craft internal tiles)
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
                if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                    # Get internal tile count from tile_data[2]
                    # Format can be: [count], {"totalCount": count}, or just count
                    stack_count = 1
                    if len(tile_data) > 2:
                        extra = tile_data[2]
                        if isinstance(extra, list) and len(extra) > 0:
                            # Format: [count] or [count, "types"]
                            stack_count = int(extra[0]) if extra[0] else 1
                        elif isinstance(extra, dict):
                            # Format: {"totalCount": count} or similar
                            stack_count = int(extra.get("totalCount", extra.get("count", 1)))
                        elif isinstance(extra, (int, float)):
                            # Format: just a number
                            stack_count = int(extra)
                    total_tiles += stack_count
                else:
                    # Normal tile
                    total_tiles += 1
            else:
                total_tiles += 1

    # Use level's max_moves if set and >= total_tiles, otherwise use total_tiles
    # This ensures levels are always clearable for simulation
    level_max_moves = level_json.get("max_moves")
    if level_max_moves is not None and level_max_moves >= total_tiles:
        return int(level_max_moves)

    # Max moves = total tiles (minimum needed to pick all tiles)
    return max(30, total_tiles)


def _calculate_autoplay_difficulty(bot_stats: List[BotClearStats]) -> float:
    """
    Calculate difficulty based on bot clear rates vs expected rates.

    Scoring logic:
    - Base score is 50 (balanced)
    - If bots clear less than target: score increases (harder)
    - If bots clear more than target: score decreases (easier)
    """
    if not bot_stats:
        return 50.0

    weighted_score = 0.0
    total_weight = 0.0

    for stats in bot_stats:
        weight = BOT_WEIGHTS.get(stats.profile, 1.0)
        # gap > 0 means harder than expected (target - actual)
        gap = stats.target_clear_rate - stats.clear_rate
        weighted_score += gap * weight * 100  # Scale to percentage points
        total_weight += weight

    base_score = 50.0  # Balanced baseline
    adjustment = weighted_score / total_weight if total_weight > 0 else 0

    # Clamp to 0-100 range
    return max(0.0, min(100.0, base_score + adjustment))


def _get_grade_from_score(score: float) -> str:
    """Convert score to grade."""
    if score <= 20:
        return "S"
    elif score <= 40:
        return "A"
    elif score <= 60:
        return "B"
    elif score <= 80:
        return "C"
    else:
        return "D"


def _assess_balance(bot_stats: List[BotClearStats]) -> tuple[str, List[str]]:
    """
    Assess level balance and generate recommendations.

    Returns:
        Tuple of (balance_status, recommendations)
    """
    recommendations = []
    all_below_target = True
    all_above_target = True
    any_extreme = False

    for stats in bot_stats:
        gap = stats.clear_rate - stats.target_clear_rate

        if gap >= 0:
            all_below_target = False
        if gap <= 0:
            all_above_target = False

        # Check for extreme deviations (>20% from target)
        if abs(gap) > 0.20:
            any_extreme = True

            if gap < -0.20:
                # Much harder than expected
                recommendations.append(
                    f"{stats.profile_display} 클리어율이 목표보다 {abs(gap)*100:.0f}%p 낮음 - 기믹 감소 권장"
                )
            elif gap > 0.20:
                # Much easier than expected
                recommendations.append(
                    f"{stats.profile_display} 클리어율이 목표보다 {gap*100:.0f}%p 높음 - 난이도 상향 권장"
                )

    # Determine balance status
    if any_extreme:
        balance_status = "unbalanced"
    elif all_below_target:
        balance_status = "too_hard"
        if not recommendations:
            recommendations.append("전체적으로 난이도가 높음 - 기믹 수 감소 또는 레이어 축소 권장")
    elif all_above_target:
        balance_status = "too_easy"
        if not recommendations:
            recommendations.append("전체적으로 난이도가 낮음 - 기믹 추가 또는 레이어 증가 권장")
    else:
        balance_status = "balanced"
        if not recommendations:
            recommendations.append("난이도 균형이 적절함")

    return balance_status, recommendations


def _run_bot_simulation(
    profile_name: str,
    level_json: Dict[str, Any],
    iterations: int,
    max_moves: int,
    seed: int | None,
    target_clear_rate: float,
) -> BotClearStats:
    """Run simulation for a single bot profile."""
    simulator = BotSimulator()
    profile = get_profile(profile_name)

    result = simulator.simulate_with_profile(
        level_json=level_json,
        profile=profile,
        iterations=iterations,
        max_moves=max_moves,
        seed=seed,
    )

    return BotClearStats(
        profile=profile_name,
        profile_display=BOT_DISPLAY_NAMES.get(profile_name, profile_name),
        clear_rate=result.clear_rate,
        target_clear_rate=target_clear_rate,
        avg_moves=result.avg_moves,
        min_moves=result.min_moves,
        max_moves=result.max_moves,
        std_moves=result.std_moves,
        avg_combo=result.avg_combo,
        iterations=result.iterations,
    )


@router.post("/analyze/autoplay", response_model=AutoPlayResponse)
async def analyze_autoplay(
    request: AutoPlayRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> AutoPlayResponse:
    """
    Analyze level difficulty using auto-play bot simulations.

    Runs multiple bot profiles with repeated simulations to measure
    actual clear rates and compare against expected performance.

    Args:
        request: AutoPlayRequest with level_json, iterations, and optional bot_profiles.
        analyzer: LevelAnalyzer dependency for static analysis comparison.

    Returns:
        AutoPlayResponse with bot statistics, difficulty scores, and recommendations.
    """
    start_time = time.time()

    try:
        level_json = request.level_json
        iterations = request.iterations
        seed = request.seed

        # Run static analysis FIRST to get actual difficulty score
        static_report = analyzer.analyze(level_json)
        static_score = static_report.score
        static_grade = static_report.grade.value

        # Calculate target clear rates based on STATIC ANALYSIS difficulty score
        # Convert static_score (0-100) to difficulty (0.0-1.0)
        # score 0 = easiest (S grade) → difficulty 0.0
        # score 100 = hardest (D grade) → difficulty 1.0
        difficulty_from_score = static_score / 100.0
        target_rates = calculate_target_clear_rates(difficulty_from_score)

        # Determine which bot profiles to use
        if request.bot_profiles:
            profiles = [p.lower() for p in request.bot_profiles if p.lower() in BASE_TARGET_CLEAR_RATES]
        else:
            profiles = list(BASE_TARGET_CLEAR_RATES.keys())

        if not profiles:
            raise HTTPException(
                status_code=400,
                detail="No valid bot profiles specified"
            )

        # Calculate max moves based on level
        max_moves = _calculate_max_moves(level_json)

        # Run simulations in parallel
        bot_stats: List[BotClearStats] = []
        with ThreadPoolExecutor(max_workers=min(5, len(profiles))) as executor:
            futures = {
                executor.submit(
                    _run_bot_simulation,
                    profile,
                    level_json,
                    iterations,
                    max_moves,
                    seed,
                    target_rates.get(profile, 0.5),
                ): profile
                for profile in profiles
            }

            for future in as_completed(futures):
                try:
                    stats = future.result()
                    bot_stats.append(stats)
                except Exception as e:
                    profile = futures[future]
                    # Create a failed stats entry
                    bot_stats.append(BotClearStats(
                        profile=profile,
                        profile_display=BOT_DISPLAY_NAMES.get(profile, profile),
                        clear_rate=0.0,
                        target_clear_rate=target_rates.get(profile, 0.5),
                        avg_moves=0.0,
                        min_moves=0,
                        max_moves=0,
                        std_moves=0.0,
                        avg_combo=0.0,
                        iterations=0,
                    ))

        # Sort by profile order
        profile_order = list(BASE_TARGET_CLEAR_RATES.keys())
        bot_stats.sort(key=lambda x: profile_order.index(x.profile) if x.profile in profile_order else 999)

        # Calculate autoplay difficulty score
        autoplay_score = _calculate_autoplay_difficulty(bot_stats)
        autoplay_grade = _get_grade_from_score(autoplay_score)

        # static_score and static_grade already calculated above

        # Assess balance
        balance_status, recommendations = _assess_balance(bot_stats)

        # Calculate execution time
        execution_time_ms = int((time.time() - start_time) * 1000)
        total_simulations = sum(s.iterations for s in bot_stats)

        return AutoPlayResponse(
            bot_stats=bot_stats,
            autoplay_score=round(autoplay_score, 2),
            autoplay_grade=autoplay_grade,
            static_score=round(static_score, 2),
            static_grade=static_grade,
            score_difference=round(autoplay_score - static_score, 2),
            balance_status=balance_status,
            recommendations=recommendations,
            total_simulations=total_simulations,
            execution_time_ms=execution_time_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"AutoPlay analysis failed: {str(e)}")
