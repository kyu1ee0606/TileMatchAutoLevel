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
    BatchVerifyRequest,
    BatchVerifyResponse,
    BatchVerifyResultItem,
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
# [v15.14] NOVICE(랜덤), CASUAL(신뢰도 낮음) 제외 - AVERAGE/EXPERT/OPTIMAL만 검증에 사용
BOT_WEIGHTS = {
    "novice": 0.0,   # 제외: 45% 실수율로 거의 랜덤 - 신뢰도 낮음
    "casual": 0.0,   # 제외: 25% 실수율 - 변동성 높음
    "average": 2.0,  # Most weight on average player
    "expert": 1.5,
    "optimal": 1.0,  # 최적 플레이 기준선
}

# [v15.14] 검증용 봇 목록 - 신뢰도 높은 봇만 포함
VALIDATION_BOT_PROFILES = ["average", "expert", "optimal"]


def calculate_target_clear_rates(target_difficulty: float) -> Dict[str, float]:
    """
    Calculate target clear rates based on target difficulty.

    target_difficulty=0.0: Very easy, but realistic considering game randomness
    target_difficulty=0.5: Balanced (moderate targets)
    target_difficulty=1.0: Very hard, lower rates based on game mechanics

    NOTE: Targets calibrated based on actual bot simulation results.
    Even easy levels have inherent variance from tile distribution and gimmicks.
    """
    rates = {}

    # TUTORIAL levels (0-0.1): Very easy, all bots should clear 90%+
    # [v14.2] 레벨 1-10 등 초반 튜토리얼 레벨 - 모든 봇 높은 클리어율 기대
    if target_difficulty <= 0.1:
        t = target_difficulty / 0.1
        tutorial_rates = {
            "novice": 0.95 - t * 0.05,    # 95% -> 90%
            "casual": 0.98 - t * 0.03,    # 98% -> 95%
            "average": 0.99 - t * 0.01,   # 99% -> 98%
            "expert": 0.99,               # 99% 고정
            "optimal": 0.99,              # 99% 고정
        }
        for bot_type in BASE_TARGET_CLEAR_RATES:
            rates[bot_type] = tutorial_rates.get(bot_type, 0.95)
    # EASY levels (0.1-0.4): Realistic targets
    # [v14.2] Novice/Casual 목표 현실화 - 실제 봇 시뮬레이션 결과 기반
    elif target_difficulty <= 0.4:
        t = (target_difficulty - 0.1) / 0.3
        easy_start = {
            "novice": 0.90,    # TUTORIAL 끝값과 연결
            "casual": 0.95,    # TUTORIAL 끝값과 연결
            "average": 0.98,   # TUTORIAL 끝값과 연결
            "expert": 0.99,    # TUTORIAL 끝값과 연결
            "optimal": 0.99,   # TUTORIAL 끝값과 연결
        }
        easy_end = {
            "novice": 0.10,    # MEDIUM 시작값과 연결
            "casual": 0.20,    # MEDIUM 시작값과 연결
            "average": 0.60,   # MEDIUM 시작값과 연결
            "expert": 0.90,    # MEDIUM 시작값과 연결
            "optimal": 0.95,   # MEDIUM 시작값과 연결
        }
        for bot_type in BASE_TARGET_CLEAR_RATES:
            start = easy_start.get(bot_type, 0.95)
            end = easy_end.get(bot_type, 0.60)
            rates[bot_type] = start - t * (start - end)
    elif target_difficulty <= 0.6:
        # MEDIUM levels (0.4-0.6): Transition zone
        # [v14.2] Novice/Casual 목표 현실화 - 연속성 유지
        t = (target_difficulty - 0.4) / 0.2
        medium_start = {
            "novice": 0.10,    # EASY 끝값과 연결 (현실화)
            "casual": 0.20,    # EASY 끝값과 연결 (현실화)
            "average": 0.60,   # EASY 끝값과 연결
            "expert": 0.90,    # EASY 끝값과 연결
            "optimal": 0.95,   # EASY 끝값과 연결
        }
        medium_end = {
            "novice": 0.05,    # HARD 시작값과 연결 (현실화)
            "casual": 0.15,    # HARD 시작값과 연결 (현실화)
            "average": 0.72,   # HARD 시작값과 연결
            "expert": 0.84,    # HARD 시작값과 연결
            "optimal": 0.92,   # HARD 시작값과 연결
        }
        for bot_type in BASE_TARGET_CLEAR_RATES:
            start = medium_start.get(bot_type, 0.70)
            end = medium_end.get(bot_type, 0.60)
            rates[bot_type] = start + t * (end - start)  # start → end로 변화
    else:
        # HARD levels (0.6-1.0): Significant difficulty
        # [v14.2] Novice/Casual 목표 현실화 - E등급 실제 결과 기반
        t = (target_difficulty - 0.6) / 0.4
        hard_start = {
            "novice": 0.05,    # MEDIUM 끝값과 연결 (현실화)
            "casual": 0.15,    # MEDIUM 끝값과 연결 (현실화)
            "average": 0.72,   # MEDIUM 끝값과 연결
            "expert": 0.84,    # MEDIUM 끝값과 연결
            "optimal": 0.92,   # MEDIUM 끝값과 연결
        }
        hard_end = {
            "novice": 0.02,    # E등급: 2% (실제 0-5% 범위)
            "casual": 0.08,    # E등급: 8% (실제 5-15% 범위)
            "average": 0.60,   # E등급: 60% (실제 50-70% 범위)
            "expert": 0.80,    # E등급: 80% (실제 75-90% 범위)
            "optimal": 0.88,   # E등급: 88% (실제 85-95% 범위)
        }
        for bot_type in BASE_TARGET_CLEAR_RATES:
            start = hard_start.get(bot_type, 0.60)
            end = hard_end.get(bot_type, 0.35)
            rates[bot_type] = start - t * (start - end)

    # Clamp all rates
    for bot_type in rates:
        rates[bot_type] = max(0.01, min(0.99, rates[bot_type]))
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
def analyze_autoplay(
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

        # Determine target difficulty for calculating expected clear rates
        # Priority: 1) request.target_difficulty (from Production generation)
        #           2) Fallback to static analysis score
        if request.target_difficulty is not None:
            # Use the target difficulty that was used when generating the level
            difficulty_for_targets = request.target_difficulty
        else:
            # Fallback: Convert static_score (0-100) to difficulty (0.0-1.0)
            # score 0 = easiest (S grade) → difficulty 0.0
            # score 100 = hardest (D grade) → difficulty 1.0
            difficulty_for_targets = static_score / 100.0

        target_rates = calculate_target_clear_rates(difficulty_for_targets)

        # Determine which bot profiles to use
        # [v15.14] 기본값: CASUAL/AVERAGE/EXPERT 3개 봇만 사용 (검증 신뢰도 향상)
        if request.bot_profiles:
            profiles = [p.lower() for p in request.bot_profiles if p.lower() in BASE_TARGET_CLEAR_RATES]
        else:
            profiles = VALIDATION_BOT_PROFILES.copy()

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


def _verify_single_level(
    level_item: dict,
    iterations: int,
    tolerance: float,
    use_core_bots_only: bool,
    analyzer: LevelAnalyzer,
    fast_mode: bool = True,
    early_termination: bool = True,
) -> BatchVerifyResultItem:
    """Verify a single level with bot simulation.

    Args:
        level_item: Level data with level_json, level_id, target_difficulty
        iterations: Number of simulation iterations per bot
        tolerance: Maximum allowed gap from target (in percentage points)
        use_core_bots_only: Use only core bots (casual, average, expert)
        analyzer: LevelAnalyzer for static analysis
        fast_mode: Use fast verification profiles (reduced lookahead)
        early_termination: Stop iterations early when results are conclusive
    """
    level_json = level_item["level_json"]
    level_id = level_item.get("level_id") or f"level_{id(level_json) % 10000}"
    target_difficulty = level_item.get("target_difficulty")

    issues = []

    try:
        # Static analysis first
        static_report = analyzer.analyze(level_json)
        static_grade = static_report.grade.value

        # Determine target difficulty
        if target_difficulty is None:
            target_difficulty = static_report.score / 100.0

        target_rates = calculate_target_clear_rates(target_difficulty)

        # Select bot profiles
        if use_core_bots_only:
            profiles = ["casual", "average", "expert"]
        else:
            profiles = list(BASE_TARGET_CLEAR_RATES.keys())

        # Calculate max moves
        max_moves = _calculate_max_moves(level_json)

        # Run simulations with optimizations
        # Note: Don't use parallel bot execution here since level-level parallelism is already in place
        # ProcessPoolExecutor overhead exceeds benefit when already parallelizing at level level
        simulator = BotSimulator()
        actual_rates = {}

        for profile_name in profiles:
            # Use fast verification profile if fast_mode is enabled
            profile = get_profile(profile_name, fast_mode=fast_mode)
            result = simulator.simulate_with_profile(
                level_json=level_json,
                profile=profile,
                iterations=iterations,
                max_moves=max_moves,
                seed=None,
                early_termination=early_termination,
            )
            actual_rates[profile_name] = result.clear_rate

        # Calculate gaps
        gaps = []
        for profile_name in profiles:
            target = target_rates.get(profile_name, 0.5)
            actual = actual_rates.get(profile_name, 0.0)
            gap = abs(target - actual) * 100
            gaps.append(gap)

            # Check for critical issues
            if actual == 0.0:
                issues.append(f"{profile_name}: 클리어율 0% (클리어 불가)")
            elif gap > tolerance * 2:
                issues.append(f"{profile_name}: 목표 대비 {gap:.1f}%p 차이")

        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        max_gap = max(gaps) if gaps else 0

        # Calculate match score (100 - avg_gap, clamped to 0-100)
        match_score = max(0, min(100, 100 - avg_gap))

        # Determine if passed
        passed = max_gap <= tolerance and all(r > 0 for r in actual_rates.values())

        return BatchVerifyResultItem(
            level_id=level_id,
            passed=passed,
            bot_clear_rates=actual_rates,
            target_clear_rates={p: target_rates.get(p, 0.5) for p in profiles},
            avg_gap=round(avg_gap, 2),
            max_gap=round(max_gap, 2),
            match_score=round(match_score, 2),
            static_grade=static_grade,
            issues=issues,
        )

    except Exception as e:
        return BatchVerifyResultItem(
            level_id=level_id,
            passed=False,
            bot_clear_rates={},
            target_clear_rates={},
            avg_gap=100.0,
            max_gap=100.0,
            match_score=0.0,
            static_grade="?",
            issues=[f"검증 실패: {str(e)}"],
        )


@router.post("/analyze/batch-verify", response_model=BatchVerifyResponse)
def batch_verify_levels(
    request: BatchVerifyRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> BatchVerifyResponse:
    """
    Batch verify multiple levels using bot simulation.

    Use this endpoint for post-generation validation when levels are generated
    with simulation_iterations=0 (fast generation mode).

    Args:
        request: BatchVerifyRequest with list of levels and verification parameters
        analyzer: LevelAnalyzer dependency

    Returns:
        BatchVerifyResponse with verification results for each level
    """
    start_time = time.time()

    if not request.levels:
        raise HTTPException(status_code=400, detail="No levels provided")

    results = []

    # Process levels in parallel with optimizations
    fast_mode = getattr(request, 'fast_mode', True)
    early_termination = getattr(request, 'early_termination', True)

    with ThreadPoolExecutor(max_workers=min(4, len(request.levels))) as executor:
        futures = {
            executor.submit(
                _verify_single_level,
                level_item.model_dump(),
                request.iterations,
                request.tolerance,
                request.use_core_bots_only,
                analyzer,
                fast_mode,
                early_termination,
            ): i
            for i, level_item in enumerate(request.levels)
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                idx = futures[future]
                results.append(BatchVerifyResultItem(
                    level_id=f"level_{idx}",
                    passed=False,
                    issues=[f"처리 오류: {str(e)}"],
                ))

    # Sort by original order (using level_id)
    results.sort(key=lambda x: int(x.level_id.split("_")[-1]) if x.level_id.split("_")[-1].isdigit() else 0)

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count

    execution_time_ms = int((time.time() - start_time) * 1000)

    return BatchVerifyResponse(
        results=results,
        total_levels=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        pass_rate=passed_count / len(results) if results else 0,
        execution_time_ms=execution_time_ms,
    )
