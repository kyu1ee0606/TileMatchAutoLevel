"""Level analysis API routes."""
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional, Tuple

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
    # [v15.35] 재생성 지원 스키마
    BatchVerifyRegenerateRequest,
    BatchVerifyRegenerateLevelItem,
    # [v15.40] 중앙정렬 수정 스키마
    FixCenteringRequest,
    FixCenteringResponse,
    FixCenteringResultItem,
)
from ...models.bot_profile import BotType, get_profile, PREDEFINED_PROFILES
from ...core.analyzer import LevelAnalyzer
from ...core.bot_simulator import BotSimulator
from ...core.generator import LevelGenerator
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


def calculate_gimmick_penalty(level_json: Dict[str, Any]) -> Dict[str, float]:
    """
    [v15.34] Calculate penalty factors for target clear rates based on gimmick combinations.

    Returns penalty factors (0.0-1.0) for each bot type.
    1.0 = no penalty, 0.5 = 50% reduction, etc.

    Difficult combinations that bots struggle with:
    - High unknown count (>8): Hard to plan ahead
    - unknown + ice/chain: Blocking + hidden info
    - craft goals: Requires specific tile combinations
    - deep layers (>4): More blocking complexity
    """
    penalties = {
        "novice": 1.0,
        "casual": 1.0,
        "average": 1.0,
        "expert": 1.0,
        "optimal": 1.0,
    }

    # Count gimmicks
    unknown_count = 0
    ice_count = 0
    chain_count = 0
    link_count = 0
    craft_goals = 0
    total_tiles = 0
    active_layers = 0

    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        if tiles:
            active_layers += 1
            total_tiles += len(tiles)

            for pos, tile_data in tiles.items():
                if len(tile_data) > 1:
                    gimmick = tile_data[1]
                    if gimmick == "unknown":
                        unknown_count += 1
                    elif gimmick == "ice":
                        ice_count += 1
                    elif gimmick == "chain":
                        chain_count += 1
                    elif gimmick and gimmick.startswith("link"):
                        link_count += 1

                # Check for craft tiles
                tile_type = tile_data[0] if tile_data else ""
                if tile_type.startswith("craft"):
                    craft_goals += 1

    # Also check goalCount for craft requirements
    goal_count = level_json.get("goalCount", {})
    for goal_type, count in goal_count.items():
        if "craft" in goal_type.lower():
            craft_goals = max(craft_goals, count)

    # === Apply penalties ===

    # 1. High unknown count penalty (>8 unknown is problematic)
    if unknown_count > 8:
        excess = min(unknown_count - 8, 10)  # Cap excess at 10
        # Average/Expert/Optimal struggle with unpredictability
        penalties["average"] *= max(0.5, 1.0 - excess * 0.04)   # Up to 40% reduction
        penalties["expert"] *= max(0.6, 1.0 - excess * 0.03)    # Up to 30% reduction
        penalties["optimal"] *= max(0.7, 1.0 - excess * 0.02)   # Up to 20% reduction

    # 2. Unknown + Ice combo penalty (hidden tiles under ice = no planning possible)
    if unknown_count > 5 and ice_count > 0:
        combo_factor = min(unknown_count * ice_count / 30.0, 0.3)  # Max 30% reduction
        penalties["average"] *= (1.0 - combo_factor)
        penalties["expert"] *= (1.0 - combo_factor * 0.8)
        penalties["optimal"] *= (1.0 - combo_factor * 0.5)

    # 3. Unknown + Chain combo penalty
    if unknown_count > 5 and chain_count > 0:
        combo_factor = min(unknown_count * chain_count / 40.0, 0.25)  # Max 25% reduction
        penalties["average"] *= (1.0 - combo_factor)
        penalties["expert"] *= (1.0 - combo_factor * 0.7)
        penalties["optimal"] *= (1.0 - combo_factor * 0.4)

    # 4. Craft goal penalty (craft tiles require specific combinations)
    if craft_goals > 0:
        craft_penalty = min(craft_goals * 0.03, 0.15)  # Max 15% reduction
        penalties["novice"] *= (1.0 - craft_penalty * 2)  # Novice struggles most
        penalties["casual"] *= (1.0 - craft_penalty * 1.5)
        penalties["average"] *= (1.0 - craft_penalty)

    # 5. Deep layer penalty (>4 active layers)
    if active_layers > 4:
        depth_penalty = (active_layers - 4) * 0.05  # 5% per extra layer
        penalties["average"] *= (1.0 - min(depth_penalty, 0.15))
        penalties["expert"] *= (1.0 - min(depth_penalty * 0.7, 0.1))

    # Clamp all penalties
    for bot in penalties:
        penalties[bot] = max(0.3, min(1.0, penalties[bot]))  # Never below 30%

    return penalties


def calculate_adjusted_target_rates(
    target_difficulty: float,
    level_json: Dict[str, Any]
) -> Dict[str, float]:
    """
    [v15.34] Calculate target clear rates with gimmick-based adjustments.

    This function applies penalty factors based on difficult gimmick combinations
    that cause bots to underperform relative to static difficulty analysis.
    """
    # Get base rates from difficulty
    base_rates = calculate_target_clear_rates(target_difficulty)

    # Get gimmick penalties
    penalties = calculate_gimmick_penalty(level_json)

    # Apply penalties to rates
    adjusted_rates = {}
    for bot_type, base_rate in base_rates.items():
        penalty = penalties.get(bot_type, 1.0)
        # Apply penalty but preserve minimum rates
        adjusted = base_rate * penalty
        adjusted_rates[bot_type] = max(0.01, min(0.99, adjusted))

    return adjusted_rates


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


def _run_bot_sim_chunk(args: Tuple) -> Dict[str, Any]:
    """
    ProcessPool 워커 (피클러블, 모듈 레벨) — 한 프로파일의 iteration 청크를 실행하고
    병합 가능한 원시 집계를 반환. GIL을 탈출해 코어 수만큼 진짜 병렬.
    """
    profile_name, level_json, iterations, max_moves, seed, early_term = args
    from ...core.bot_simulator import BotSimulator
    from ...models.bot_profile import get_profile
    simulator = BotSimulator()
    profile = get_profile(profile_name)
    result = simulator.simulate_with_profile(
        level_json=level_json,
        profile=profile,
        iterations=iterations,
        max_moves=max_moves,
        seed=seed,
        early_termination=early_term,
    )
    n = result.iterations
    return {
        "profile": profile_name,
        "n": n,
        "cleared": round(result.clear_rate * n),
        "sum_moves": result.avg_moves * n,
        "sum_combo": result.avg_combo * n,
        "min_moves": result.min_moves,
        "max_moves": result.max_moves,
        "mean_moves": result.avg_moves,
        # 표본분산 → M2 (Chan 병합용). n<=1이면 0.
        "m2_moves": (result.std_moves ** 2) * (n - 1) if n > 1 else 0.0,
    }


def _run_profiles_parallel(
    profiles: List[str],
    level_json: Dict[str, Any],
    iterations: int,
    max_moves: int,
    seed: int | None,
    target_rates: Dict[str, float],
    early_termination: bool = True,
) -> List[BotClearStats]:
    """
    프로파일 × iteration 청크를 CPU 프로세스 풀에 분배해 병렬 시뮬 후 프로파일별로 병합.

    - GIL 탈출(프로세스) + early_termination(명백한 0%/100% 조기 종료)으로
      순차검증 핵심 병목 제거.
    - 청크 시드는 누적 오프셋으로 겹치지 않게 분리(고정 시드일 때 중복 방지).
    - clear_rate/avg/min/max/combo는 정확 병합, std는 Chan 병렬분산으로 정확 병합.
    """
    from .generate import _get_gen_pool, GEN_POOL_WORKERS

    # 프로파일당 청크 수: 총 태스크가 풀 워커를 채우도록
    chunks_per_profile = max(1, round(GEN_POOL_WORKERS / max(1, len(profiles))))
    tasks: List[Tuple] = []
    for profile_name in profiles:
        base = iterations // chunks_per_profile
        rem = iterations % chunks_per_profile
        offset = 0
        for c in range(chunks_per_profile):
            chunk_iters = base + (1 if c < rem else 0)
            if chunk_iters <= 0:
                continue
            chunk_seed = None if seed is None else seed + offset
            tasks.append((profile_name, level_json, chunk_iters, max_moves, chunk_seed, early_termination))
            offset += chunk_iters

    pool = _get_gen_pool()
    raw = list(pool.map(_run_bot_sim_chunk, tasks))

    # 프로파일별 병합
    merged: Dict[str, Dict[str, Any]] = {}
    for r in raw:
        p = r["profile"]
        if p not in merged:
            merged[p] = {"n": 0, "cleared": 0, "sum_moves": 0.0, "sum_combo": 0.0,
                         "min_moves": None, "max_moves": None, "mean": 0.0, "m2": 0.0}
        m = merged[p]
        # Chan 병렬분산 병합
        nb, mb, m2b = r["n"], r["mean_moves"], r["m2_moves"]
        if nb > 0:
            na, ma, m2a = m["n"], m["mean"], m["m2"]
            nab = na + nb
            delta = mb - ma
            m["mean"] = ma + delta * nb / nab
            m["m2"] = m2a + m2b + delta * delta * na * nb / nab
            m["n"] = nab
        m["cleared"] += r["cleared"]
        m["sum_moves"] += r["sum_moves"]
        m["sum_combo"] += r["sum_combo"]
        m["min_moves"] = r["min_moves"] if m["min_moves"] is None else min(m["min_moves"], r["min_moves"])
        m["max_moves"] = r["max_moves"] if m["max_moves"] is None else max(m["max_moves"], r["max_moves"])

    bot_stats: List[BotClearStats] = []
    for profile_name in profiles:
        m = merged.get(profile_name)
        if not m or m["n"] == 0:
            bot_stats.append(BotClearStats(
                profile=profile_name,
                profile_display=BOT_DISPLAY_NAMES.get(profile_name, profile_name),
                clear_rate=0.0, target_clear_rate=target_rates.get(profile_name, 0.5),
                avg_moves=0.0, min_moves=0, max_moves=0, std_moves=0.0, avg_combo=0.0, iterations=0,
            ))
            continue
        n = m["n"]
        std = math.sqrt(m["m2"] / (n - 1)) if n > 1 else 0.0
        bot_stats.append(BotClearStats(
            profile=profile_name,
            profile_display=BOT_DISPLAY_NAMES.get(profile_name, profile_name),
            clear_rate=m["cleared"] / n,
            target_clear_rate=target_rates.get(profile_name, 0.5),
            avg_moves=m["sum_moves"] / n,
            min_moves=m["min_moves"] or 0,
            max_moves=m["max_moves"] or 0,
            std_moves=std,
            avg_combo=m["sum_combo"] / n,
            iterations=n,
        ))
    return bot_stats


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

        # [v15.34] Use adjusted target rates that account for gimmick combinations
        target_rates = calculate_adjusted_target_rates(difficulty_for_targets, level_json)

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

        # Run simulations in parallel across the CPU process pool (GIL escape).
        # 프로파일 × iteration 청크로 코어를 채우고 early_termination으로 명백한
        # 0%/100% 레벨을 조기 종료 — 순차검증의 핵심 병목(ThreadPool GIL 직렬화) 제거.
        bot_stats: List[BotClearStats] = _run_profiles_parallel(
            profiles, level_json, iterations, max_moves, seed, target_rates,
            early_termination=True,
        )

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

        # [v15.34] Use adjusted target rates that account for gimmick combinations
        target_rates = calculate_adjusted_target_rates(target_difficulty, level_json)

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

        # [v15.32] Dynamic tolerance adjustment for hard levels
        # Hard levels (target_difficulty >= 0.7) have inherently more variance
        # due to complex gimmick combinations, so tolerance is expanded by 1.3x
        effective_tolerance = tolerance
        if target_difficulty >= 0.7:
            effective_tolerance = tolerance * 1.3  # 15% → 19.5%
        elif target_difficulty >= 0.5:
            # Gradual increase for medium-hard levels
            t = (target_difficulty - 0.5) / 0.2  # 0 at 0.5, 1 at 0.7
            effective_tolerance = tolerance * (1.0 + t * 0.3)  # 15% → 19.5%

        # Determine if passed
        passed = max_gap <= effective_tolerance and all(r > 0 for r in actual_rates.values())

        # [솔버 통과봇] 휴리스틱 봇이 실패시켰지만 '봇이 못 깬 것'일 수 있다.
        # A* 솔버가 클리어 경로를 증명(PROVEN_SOLVABLE)하면 통과로 승격(레벨은 클리어 가능).
        # PROVEN_IMPOSSIBLE 면 실패 확정. UNCERTAIN 이면 봇 결과 유지(판정 보류).
        # 비용 절약: passed=False 인 소수에만 실행.
        solver_verified = False
        solver_verdict = None
        if not passed:
            try:
                from ...core.solver import solve_level
                # 예산 상향: 순차검증 병렬 시 CPU 경합으로 쉬운 레벨도 6s 타임아웃 → UNCERTAIN 오판.
                # 12s/300k 로 올려 시간제한 케이스 흡수(기믹 블라인드는 여전히 UNCERTAIN — 시간무관).
                sv = solve_level(level_json, node_budget=300000, time_budget_s=12)
                solver_verdict = sv.get("verdict")
                if solver_verdict == "PROVEN_SOLVABLE":
                    passed = True
                    solver_verified = True
                    issues.append("✅ A* 솔버 통과 — 봇은 못 깼으나 클리어 경로 증명됨(난이도 높음)")
                elif solver_verdict == "PROVEN_IMPOSSIBLE":
                    issues.append(f"⛔ A* 솔버 클리어 불가 확정: {sv.get('reason','')[:60]}")
                else:
                    issues.append(f"❔ A* 판정 보류({solver_verdict}) — 봇 결과 유지")
            except Exception as ex:
                issues.append(f"A* 솔버 fallback 실패: {str(ex)[:50]}")

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
            solver_verified=solver_verified,
            solver_verdict=solver_verdict,
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
        regenerated_count=0,  # 기존 API는 재생성 없음
    )


# ============================================================
# [v15.35] Batch Verify with Regeneration API
# ============================================================

@router.post("/analyze/batch-verify-regenerate", response_model=BatchVerifyResponse)
def batch_verify_with_regeneration(
    request: BatchVerifyRegenerateRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> BatchVerifyResponse:
    """
    Batch verify levels with automatic regeneration for failed levels.

    This endpoint verifies levels and automatically regenerates failed levels
    using the validated generation API. This provides a "root cause" solution
    by creating new levels that actually meet the target difficulty.

    Args:
        request: BatchVerifyRegenerateRequest with levels and regeneration options
        analyzer: LevelAnalyzer dependency

    Returns:
        BatchVerifyResponse with verification results (including regenerated levels)
    """
    import logging
    from ...core.generator import LevelGenerator, GenerationParams
    from ..deps import get_level_generator
    from .generate import resolve_symmetry_mode

    logger = logging.getLogger(__name__)
    start_time = time.time()

    if not request.levels:
        raise HTTPException(status_code=400, detail="No levels provided")

    results: List[BatchVerifyResultItem] = []
    regenerated_count = 0

    # Phase 1: Initial verification (parallel)
    logger.info(f"[BATCH_VERIFY_REGEN] Starting verification of {len(request.levels)} levels")

    with ThreadPoolExecutor(max_workers=min(4, len(request.levels))) as executor:
        futures = {
            executor.submit(
                _verify_single_level,
                level_item.model_dump(),
                request.iterations,
                request.tolerance,
                request.use_core_bots_only,
                analyzer,
                request.fast_mode,
                request.early_termination,
            ): (i, level_item)
            for i, level_item in enumerate(request.levels)
        }

        initial_results: Dict[int, tuple] = {}  # idx -> (result, level_item)
        for future in as_completed(futures):
            idx, level_item = futures[future]
            try:
                result = future.result()
                initial_results[idx] = (result, level_item)
            except Exception as e:
                logger.error(f"[BATCH_VERIFY_REGEN] Level {idx} verification failed: {e}")
                initial_results[idx] = (
                    BatchVerifyResultItem(
                        level_id=level_item.level_id or f"level_{idx}",
                        passed=False,
                        issues=[f"검증 오류: {str(e)}"],
                    ),
                    level_item,
                )

    # Phase 2: Regeneration for failed levels (if enabled)
    failed_indices = [
        idx for idx, (result, _) in initial_results.items()
        if not result.passed and request.enable_regeneration
    ]

    logger.info(f"[BATCH_VERIFY_REGEN] Initial verification complete: {len(request.levels) - len(failed_indices)} passed, {len(failed_indices)} failed")

    if failed_indices and request.enable_regeneration:
        logger.info(f"[BATCH_VERIFY_REGEN] Starting regeneration for {len(failed_indices)} failed levels")

        for idx in failed_indices:
            original_result, level_item = initial_results[idx]
            level_id = original_result.level_id

            # 원본 레벨에서 파라미터 추출
            original_json = level_item.level_json
            target_difficulty = level_item.target_difficulty or (original_json.get("target_difficulty", 0.5))

            # 재생성 시도
            best_result = original_result
            best_new_json = None
            attempt = 0

            try:
                # 원본 파라미터 또는 level_json에서 추출
                grid_size = level_item.grid_size or original_json.get("grid_size", [8, 8])
                max_layers = level_item.max_layers or original_json.get("layer_count", 5)
                tile_types = level_item.tile_types or _extract_tile_types(original_json)
                obstacle_types = level_item.obstacle_types or _extract_obstacle_types(original_json)
                pattern_type = level_item.pattern_type or original_json.get("pattern_type")
                # [v15.40] 재생성 시 pattern_index 보존 - 누락 시 모양이 깨짐
                pattern_index = level_item.pattern_index if hasattr(level_item, 'pattern_index') and level_item.pattern_index is not None else original_json.get("pattern_index")
                goals = original_json.get("goals", [{"type": "stack", "direction": "s", "count": 3}])

                # [패턴 보존] pattern_index를 잃은 저장 패턴 레벨(_preserve_pattern 보유)은
                # from-scratch 재생성 시 패턴모드 미진입 → 난이도조정이 타일을 제거 → 모양에 구멍.
                # 이 경우 원본을 제자리 난이도 재튜닝(기믹만 조정)해 모양을 100% 보존한다.
                if pattern_index is None and bool(original_json.get("_preserve_pattern")):
                    new_json = _retune_pattern_level_in_place(
                        original_json, target_difficulty, grid_size,
                        obstacle_types, level_item.level_number,
                    )
                    attempt = 1
                else:
                    # [통합] 단순 재롤(generate) 대신 RL과 동일한 '적응 검증 생성'(generate_validated_level)을
                    # 호출 → 내부에서 difficulty_offset/기믹/그리드/타일종류를 gap 기반 조정하며 목표 난이도로
                    # 점차 수렴(MAX_GENERATION_ATTEMPTS 내부 루프). 동일 파라미터 재롤로는 수렴 안 하던 문제 해결.
                    from .generate import generate_validated_level
                    from ...models.schemas import ValidatedGenerateRequest

                    # [재생성 규칙 보존] 원본이 유닛조립(_unit_assembly)/역생성으로 생성됐으면
                    # 재생성도 동일 모드로 → 순차검증 후 재생성이 규칙(솔리드→하단·패턴→상단 등) 유지.
                    _ua = bool(original_json.get("_unit_assembly"))
                    _rev = _ua or bool(original_json.get("reverse_generated"))
                    vreq = ValidatedGenerateRequest(
                        target_difficulty=target_difficulty,
                        grid_size=tuple(grid_size) if isinstance(grid_size, list) else grid_size,
                        max_layers=max_layers,
                        tile_types=tile_types,
                        obstacle_types=obstacle_types or [],
                        goals=goals,
                        pattern_type=pattern_type,
                        pattern_index=pattern_index,
                        level_number=level_item.level_number,
                        unit_assembly=_ua,
                        use_reverse_generation=_rev,
                    )
                    vresp = generate_validated_level(vreq, get_level_generator())
                    new_json = vresp.level_json
                    new_json["target_difficulty"] = target_difficulty
                    attempt = vresp.attempts

                # 적응 생성 결과 → 표준 검증으로 판정(솔버봇 fallback 포함, 일관된 BatchVerifyResultItem)
                verify_result = _verify_single_level(
                    {
                        "level_json": new_json,
                        "level_id": level_id,
                        "target_difficulty": target_difficulty,
                    },
                    request.regeneration_iterations,
                    request.regeneration_tolerance,
                    request.use_core_bots_only,
                    analyzer,
                    request.fast_mode,
                    request.early_termination,
                )

                logger.info(f"[BATCH_VERIFY_REGEN] Level {level_id} 적응재생성 {attempt}회: "
                           f"match_score={verify_result.match_score:.1f}, passed={verify_result.passed}")

                if verify_result.match_score > best_result.match_score:
                    best_result = verify_result
                    best_new_json = new_json

            except Exception as e:
                logger.warning(f"[BATCH_VERIFY_REGEN] Level {level_id} 적응재생성 실패: {e}")

            # 최종 결과 업데이트
            if best_new_json is not None:
                best_result.regenerated = True
                best_result.regeneration_attempts = attempt
                best_result.new_level_json = best_new_json
                regenerated_count += 1
                logger.info(f"[BATCH_VERIFY_REGEN] Level {level_id} regenerated: "
                           f"passed={best_result.passed}, match_score={best_result.match_score:.1f}")

            initial_results[idx] = (best_result, level_item)

    # 결과 정렬 및 수집
    for idx in sorted(initial_results.keys()):
        result, _ = initial_results[idx]
        results.append(result)

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count
    execution_time_ms = int((time.time() - start_time) * 1000)

    logger.info(f"[BATCH_VERIFY_REGEN] Complete: {passed_count} passed, {failed_count} failed, "
               f"{regenerated_count} regenerated, {execution_time_ms}ms")

    return BatchVerifyResponse(
        results=results,
        total_levels=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        pass_rate=passed_count / len(results) if results else 0,
        execution_time_ms=execution_time_ms,
        regenerated_count=regenerated_count,
    )


def _retune_pattern_level_in_place(
    original_json: Dict[str, Any],
    target_difficulty: float,
    grid_size: Any,
    obstacle_types: Optional[List[str]],
    level_number: Optional[int],
) -> Dict[str, Any]:
    """[패턴 보존 재생성] pattern_index를 잃은 저장 패턴 레벨을 from-scratch 재생성하면
    패턴모드에 진입하지 못해(_preserve_pattern은 pattern_index가 있을 때만 세팅됨) 난이도
    조정 단계에서 타일이 제거되어 모양(템플릿)에 구멍이 생긴다.

    대신 원본 level_json(이미 _preserve_pattern + 정확한 위치 보유)을 그대로 두고 난이도만
    제자리 재튜닝한다. generator._adjust_difficulty 는 level['_preserve_pattern'] 를 존중해
    타일을 추가/제거하지 않고 기믹(장애물)만 조정 → 모양 100% 보존.
    """
    import copy
    from ...core.generator import GenerationParams
    from ..deps import get_level_generator

    gen = get_level_generator()
    retuned = copy.deepcopy(original_json)
    retuned["_preserve_pattern"] = True  # 방어적 보강(원본 누락 대비)
    gparams = GenerationParams(
        target_difficulty=target_difficulty,
        grid_size=tuple(grid_size) if isinstance(grid_size, list) else grid_size,
        symmetry_mode=original_json.get("symmetry_mode", "none"),
        obstacle_types=obstacle_types or [],
        level_number=level_number,
    )
    retuned = gen._adjust_difficulty(retuned, target_difficulty, params=gparams)
    retuned["target_difficulty"] = target_difficulty
    return retuned


def _extract_tile_types(level_json: Dict[str, Any]) -> List[str]:
    """Extract tile types from level JSON."""
    tile_types = set()
    layers = level_json.get("layers", [])
    for layer in layers:
        tiles = layer.get("tiles", [])
        for tile in tiles:
            tile_type = tile.get("type")
            if tile_type and tile_type.startswith("t"):
                tile_types.add(tile_type)
    return list(tile_types) if tile_types else ["t0", "t1", "t2", "t3", "t4"]


def _extract_obstacle_types(level_json: Dict[str, Any]) -> List[str]:
    """Extract obstacle types from level JSON."""
    obstacle_types = set()
    layers = level_json.get("layers", [])
    for layer in layers:
        tiles = layer.get("tiles", [])
        for tile in tiles:
            obstacles = tile.get("obstacles", [])
            for obs in obstacles:
                obs_type = obs.get("type")
                if obs_type:
                    obstacle_types.add(obs_type)
    return list(obstacle_types)


def _calc_visual_center_diff(level: Dict[str, Any]) -> float:
    """[v15.40] 레벨의 레이어 간 최대 시각적 중심 차이 계산."""
    num_layers = level.get("layer", 1)
    centers = []
    for i in range(num_layers):
        tiles = level.get(f"layer_{i}", {}).get("tiles", {})
        if not tiles:
            continue
        cols = [int(p.split("_")[1]) for p in tiles.keys() if "_" in p]
        if not cols:
            continue
        vc = (min(cols) + max(cols)) / 2 + (0.5 if i % 2 == 1 else 0)
        centers.append(vc)
    if len(centers) < 2:
        return 0.0
    return max(centers) - min(centers)


from pydantic import BaseModel as _BaseModel, Field as _Field


class SolvabilityRequest(_BaseModel):
    level_json: Dict[str, Any]
    node_budget: int = _Field(default=60000, ge=1000, le=2000000)
    time_budget_s: float = _Field(default=5.0, ge=0.0, le=600.0)  # 0 = 무제한(노드예산만), 최대 600s


class SolvabilityResult(_BaseModel):
    verdict: str                      # PROVEN_SOLVABLE | PROVEN_IMPOSSIBLE | UNCERTAIN
    reason: str
    nodes_expanded: int
    moves_to_clear: Optional[int] = None
    divisibility_violation: Optional[Dict[str, int]] = None
    distribution_bug_suspect: bool = False
    unsupported_gimmicks: Optional[List[str]] = None  # frog 등 솔버 미지원 기믹(UNCERTAIN 사유)


class SolvabilityBatchItem(_BaseModel):
    level_number: int
    level_json: Dict[str, Any]


class SolvabilityBatchRequest(_BaseModel):
    levels: List[SolvabilityBatchItem]
    node_budget: int = _Field(default=60000, ge=1000, le=2000000)
    time_budget_s: float = _Field(default=5.0, ge=0.0, le=600.0)  # 0 = 무제한(노드예산만), 최대 600s


class SolvabilityBatchResultItem(SolvabilityResult):
    level_number: int
    error: Optional[str] = None


class SolvabilityBatchResponse(_BaseModel):
    results: List[SolvabilityBatchResultItem]
    elapsed_ms: int


@router.post("/analyze/solvability", response_model=SolvabilityResult)
def analyze_solvability(request: SolvabilityRequest) -> SolvabilityResult:
    """
    완전탐색 A* 솔버로 레벨 클리어 가능성을 확정 판정 (휴리스틱 봇과 독립).
    PROVEN_SOLVABLE(witness 발견) / PROVEN_IMPOSSIBLE(÷3 위반 또는 상태공간 소진) /
    UNCERTAIN(예산 초과). t0 분배 ÷3 위반은 분배 버그로 별도 표시.
    """
    from ...core.solver import solve_level
    r = solve_level(request.level_json, node_budget=request.node_budget, time_budget_s=request.time_budget_s)
    return SolvabilityResult(
        verdict=r["verdict"],
        reason=r["reason"],
        nodes_expanded=r["nodes_expanded"],
        moves_to_clear=r.get("moves_to_clear"),
        divisibility_violation=r.get("divisibility_violation"),
        distribution_bug_suspect=r.get("distribution_bug_suspect", False),
    )


@router.post("/analyze/solvability/batch", response_model=SolvabilityBatchResponse)
def analyze_solvability_batch(request: SolvabilityBatchRequest) -> SolvabilityBatchResponse:
    """레벨 묶음을 프로세스 풀로 병렬 솔버 판정 (레벨 단위 분배)."""
    from ...core.solver import solve_level_task
    from .generate import _get_gen_pool

    started = time.time()
    tasks = [{"level_number": it.level_number, "level_json": it.level_json,
              "node_budget": request.node_budget, "time_budget_s": request.time_budget_s}
             for it in request.levels]
    pool = _get_gen_pool()
    raw = list(pool.map(solve_level_task, tasks))

    items: List[SolvabilityBatchResultItem] = []
    for r in raw:
        items.append(SolvabilityBatchResultItem(
            level_number=r.get("level_number") or 0,
            error=r.get("error"),
            verdict=r.get("verdict", "UNCERTAIN"),
            reason=r.get("reason", ""),
            nodes_expanded=r.get("nodes_expanded", 0),
            moves_to_clear=r.get("moves_to_clear"),
            divisibility_violation=r.get("divisibility_violation"),
            distribution_bug_suspect=r.get("distribution_bug_suspect", False),
            unsupported_gimmicks=r.get("unsupported_gimmicks"),
        ))
    return SolvabilityBatchResponse(results=items, elapsed_ms=int((time.time() - started) * 1000))


@router.post("/analyze/fix-centering", response_model=FixCenteringResponse)
async def fix_centering(request: FixCenteringRequest):
    """[v15.40] 기존 레벨 데이터에 시각적 중앙정렬만 적용 (재생성 없음).

    레벨의 타일 타입, 기믹, 난이도 등은 변경하지 않고
    레이어 간 시각적 중심만 맞추도록 가장자리 타일을 트리밍합니다.
    """
    import copy
    start_time = time.time()

    generator = LevelGenerator()
    results = []
    modified_count = 0

    for level_data in request.levels:
        level_number = level_data.get("levelNumber", 0) or level_data.get("level_number", 0)

        # 원본 diff 계산
        diff_before = _calc_visual_center_diff(level_data)

        # 깊은 복사 후 중앙정렬 적용
        fixed_level = copy.deepcopy(level_data)
        fixed_level = generator._fix_visual_centering(fixed_level)
        fixed_level = generator._sync_layer_num_fields(fixed_level)
        # [÷3 재보장] 중앙정렬(타일 위치 변형)이 매칭타입 ÷3 카운트를 깰 수 있으므로
        # generate() 밖 변형 직후에도 권위 게이트를 한 번 더 통과(멱등). 클리어불가 출고 차단.
        fixed_level = generator._finalize_divisibility_guarantee(fixed_level)

        # 수정 후 diff 계산
        diff_after = _calc_visual_center_diff(fixed_level)

        was_modified = diff_before != diff_after

        if was_modified:
            modified_count += 1

        results.append(FixCenteringResultItem(
            level_number=level_number,
            level_json=fixed_level,
            was_modified=was_modified,
            center_diff_before=round(diff_before, 2),
            center_diff_after=round(diff_after, 2),
        ))

    processing_time_ms = int((time.time() - start_time) * 1000)

    return FixCenteringResponse(
        results=results,
        total=len(results),
        modified=modified_count,
        processing_time_ms=processing_time_ms,
    )


@router.post("/debug/pattern-preview")
async def debug_pattern_preview(
    pattern_index: int = 0,
    grid_cols: int = 8,
    grid_rows: int = 8,
):
    """[v15.40] 패턴 디버그: 템플릿 원본 vs 실제 생성 비교.

    레이어 1개만 생성하여 패턴 형태 보존 여부를 확인합니다.
    """
    generator = LevelGenerator()

    # 1. 패턴 템플릿 원본
    template = generator._generate_aesthetic_positions(
        grid_cols, grid_rows, target_count=1000, pattern_index=pattern_index
    )

    # 2. 실제 레벨 생성 (레이어 1개)
    from app.models.level import GenerationParams
    params = GenerationParams(
        level_number=50,
        target_difficulty=0.2,
        grid_size=(grid_cols - 1, grid_rows - 1),
        min_layers=1,
        max_layers=1,
        pattern_index=pattern_index,
        pattern_type="aesthetic",
    )
    result = generator.generate(params)
    generated = result.level_json
    actual_positions = list(generated.get("layer_0", {}).get("tiles", {}).keys())

    # 3. 비교
    template_set = set(template)
    actual_set = set(actual_positions)
    missing = sorted(template_set - actual_set)
    extra = sorted(actual_set - template_set)

    # 4. 그리드 시각화
    grid = []
    for y in range(grid_rows):
        row = []
        for x in range(grid_cols):
            pos = f"{x}_{y}"
            if pos in template_set and pos in actual_set:
                row.append("match")
            elif pos in template_set:
                row.append("missing")
            elif pos in actual_set:
                row.append("extra")
            else:
                row.append("empty")
        grid.append(row)

    return {
        "pattern_index": pattern_index,
        "grid_cols": grid_cols,
        "grid_rows": grid_rows,
        "template_count": len(template),
        "actual_count": len(actual_positions),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "match_rate": round((len(template_set & actual_set) / len(template_set) * 100) if template_set else 0, 1),
        "template_positions": template,
        "actual_positions": actual_positions,
        "missing": missing,
        "extra": extra,
        "grid": grid,
        "level_json": generated,
    }


@router.get("/debug/pattern-list")
async def debug_pattern_list(grid_cols: int = 8, grid_rows: int = 8):
    """[v15.40] 64개 기본 + 커스텀 패턴 목록 + 미니 프리뷰."""
    generator = LevelGenerator()
    patterns = []

    # 커스텀 패턴에서 64+ 인덱스 수집
    custom = _load_custom_patterns()
    custom_indices = set()
    for k in custom.keys():
        try:
            idx = int(k.split("_")[0])
            if idx >= 64:
                custom_indices.add(idx)
        except ValueError:
            pass

    # 기본 64개 + 커스텀 인덱스
    all_indices = list(range(64)) + sorted(custom_indices)

    for idx in all_indices:
        try:
            positions = generator._generate_aesthetic_positions(
                grid_cols, grid_rows, target_count=1000, pattern_index=idx
            )
            grid = [[0] * grid_cols for _ in range(grid_rows)]
            for p in positions:
                x, y = int(p.split("_")[0]), int(p.split("_")[1])
                if 0 <= x < grid_cols and 0 <= y < grid_rows:
                    grid[y][x] = 1

            patterns.append({
                "index": idx,
                "count": len(positions),
                "fill_rate": round(len(positions) / (grid_cols * grid_rows) * 100, 1),
                "grid": grid,
                "is_custom": idx >= 64,
            })
        except Exception:
            patterns.append({"index": idx, "count": 0, "fill_rate": 0, "grid": [], "is_custom": idx >= 64})

    return {"patterns": patterns, "grid_cols": grid_cols, "grid_rows": grid_rows}


# ===== 커스텀 패턴 저장/로드 =====
import os
import json as json_module

CUSTOM_PATTERNS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "custom_patterns.json")


def _load_custom_patterns() -> Dict[str, Any]:
    try:
        with open(CUSTOM_PATTERNS_PATH, "r") as f:
            return json_module.load(f)
    except (FileNotFoundError, json_module.JSONDecodeError):
        return {}


def _save_custom_patterns(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(CUSTOM_PATTERNS_PATH), exist_ok=True)
    with open(CUSTOM_PATTERNS_PATH, "w") as f:
        json_module.dump(data, f, indent=2)


# ===== [보스 템플릿] 다층 t0 모양 손그림 저장 — 프로덕션 보스(10의 배수) 생성용 =====
# 사용자가 각 층을 t0로 직접 그려 모양만 잡고(홀짝 8/7 교대), 생성기가 useTileCount(난이도
# 그래프)+기믹+검증을 오버레이. level_min/max = 이 템플릿이 배정될 레벨 구간(깊이별 분류).
BOSS_TEMPLATES_PATH = os.path.join(os.path.dirname(CUSTOM_PATTERNS_PATH), "boss_templates.json")


def _load_boss_templates() -> Dict[str, Any]:
    try:
        with open(BOSS_TEMPLATES_PATH, "r") as f:
            return json_module.load(f)
    except (FileNotFoundError, json_module.JSONDecodeError):
        return {}


def _save_boss_templates(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(BOSS_TEMPLATES_PATH), exist_ok=True)
    with open(BOSS_TEMPLATES_PATH, "w") as f:
        json_module.dump(data, f, indent=2)


class BossTemplateLayer(_BaseModel):
    layer: int
    col: int
    row: int
    positions: List[str]  # "col_row" 키 목록 (t0로 채울 셀)
    gimmicks: Optional[Dict[str, str]] = None  # {pos: gimmick} 수동 지정 기믹(속성). 자동배치가 보존.


class BossTemplateSaveRequest(_BaseModel):
    id: str
    name: str = ""
    level_min: int = 10           # 배정 구간(포함)
    level_max: int = 1500
    layers: List[BossTemplateLayer]
    created_at: Optional[float] = None  # 클라 타임스탬프(서버 시간 비의존)


@router.post("/debug/boss-template-save")
async def boss_template_save(req: BossTemplateSaveRequest):
    """보스 템플릿 저장/갱신 (id 기준 upsert)."""
    data = _load_boss_templates()
    data[req.id] = {
        "id": req.id,
        "name": req.name or req.id,
        "level_min": int(req.level_min),
        "level_max": int(req.level_max),
        "layers": [
            {"layer": l.layer, "col": l.col, "row": l.row, "positions": l.positions,
             "gimmicks": l.gimmicks or {}}
            for l in req.layers
        ],
        "layer_count": len(req.layers),
        "created_at": req.created_at,
    }
    _save_boss_templates(data)
    return {"ok": True, "id": req.id, "count": len(data)}


@router.get("/debug/boss-templates")
async def boss_templates_list():
    """저장된 보스 템플릿 전체."""
    return {"boss_templates": _load_boss_templates()}


@router.delete("/debug/boss-template/{template_id}")
async def boss_template_delete(template_id: str):
    """보스 템플릿 삭제."""
    data = _load_boss_templates()
    if template_id in data:
        del data[template_id]
        _save_boss_templates(data)
        return {"ok": True, "deleted": template_id}
    return {"ok": False, "detail": "not_found"}


# ===== [보스 컨셉 노트] 보스 레벨별 스토리 비트/모양 컨셉 (기획 참조) =====
BOSS_CONCEPTS_PATH = os.path.join(os.path.dirname(CUSTOM_PATTERNS_PATH), "boss_concepts.json")


def _load_boss_concepts() -> Dict[str, Any]:
    try:
        with open(BOSS_CONCEPTS_PATH, "r") as f:
            return json_module.load(f)
    except (FileNotFoundError, json_module.JSONDecodeError):
        return {}


def _save_boss_concepts(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(BOSS_CONCEPTS_PATH), exist_ok=True)
    with open(BOSS_CONCEPTS_PATH, "w") as f:
        json_module.dump(data, f, indent=2, ensure_ascii=False)


class BossConceptsSaveRequest(_BaseModel):
    # { "10": {chapter, beat, deco, shape, note}, ... } — 레벨번호(str) 키
    concepts: Dict[str, Dict[str, Any]]


class BossShapeLLMRequest(_BaseModel):
    description: str
    sizes: List[int] = [8, 7]     # 생성할 그리드 크기(홀짝 8/7). 각 크기별 1회 호출.
    symmetric: bool = True


def _parse_grid(text: str, n: int) -> List[str]:
    """LLM 출력에서 n×n 0/1 그리드 파싱 → 'col_row' positions."""
    rows = []
    for line in text.splitlines():
        s = "".join(ch for ch in line.strip() if ch in "01")
        if len(s) >= n:
            rows.append(s[:n])
        if len(rows) >= n:
            break
    # 부족하면 0행 패딩
    while len(rows) < n:
        rows.append("0" * n)
    pos = []
    for y, row in enumerate(rows[:n]):
        for x, ch in enumerate(row[:n]):
            if ch == "1":
                pos.append(f"{x}_{y}")
    return pos


@router.post("/debug/boss-shape-llm")
async def boss_shape_llm(req: BossShapeLLMRequest):
    """모양 설명 → LLM이 n×n 0/1 그리드 생성 → t0 positions. (C안: 임의 모양 자동생성.)

    인증 = Claude Code CLI(`claude -p`) 이미 로그인된 세션 사용. API 키 불필요.
    CLI 미설치/미인증 시 에러. 모델 = 세션 기본(또는 CLAUDE_CLI_BIN env로 경로 지정).
    """
    import os as _os
    import asyncio as _asyncio
    cli = _os.environ.get("CLAUDE_CLI_BIN", "claude")
    sym = "좌우 대칭(left-right symmetric)으로. " if req.symmetric else ""
    grids: Dict[str, List[str]] = {}
    for n in sorted(set(int(s) for s in req.sizes)):
        prompt = (
            f"{n}x{n} 크기의 0/1 그리드만 출력해. 설명/여분텍스트 없이 {n}줄, 각 줄 {n}자.\n"
            f"1=채운 타일, 0=빈칸. '{req.description}'의 알아볼 수 있는 실루엣을 그려.\n"
            f"{sym}게임 보드용이라 전체의 35~70% 정도 채워. 오직 0과 1로 된 {n}줄만 출력."
        )
        try:
            proc = await _asyncio.create_subprocess_exec(
                cli, "-p", prompt,
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
            )
            out, err = await _asyncio.wait_for(proc.communicate(), timeout=90)
            if proc.returncode != 0:
                raise RuntimeError((err or b"").decode()[:200] or f"exit {proc.returncode}")
            grids[str(n)] = _parse_grid(out.decode(), n)
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail=f"claude CLI 없음('{cli}') — Claude Code 설치/인증 필요")
        except _asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="LLM 타임아웃(90s)")
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"LLM 오류: {ex}")
    return {"grids": grids, "via": "claude-cli"}


@router.get("/debug/boss-concepts")
async def boss_concepts_list():
    """보스 레벨별 스토리 컨셉 노트 전체."""
    return {"boss_concepts": _load_boss_concepts()}


@router.post("/debug/boss-concepts-save")
async def boss_concepts_save(req: BossConceptsSaveRequest):
    """보스 컨셉 노트 전체 저장(덮어쓰기)."""
    _save_boss_concepts(req.concepts)
    return {"ok": True, "count": len(req.concepts)}


class BossTemplateGenerateRequest(_BaseModel):
    level_number: int
    target_difficulty: Optional[float] = None
    tile_type_profile: Optional[str] = None
    random_seed: Optional[int] = None
    apply_gimmicks: bool = True                        # 언락/난이도 기반 기믹 자동배치
    gimmick_intensity: Optional[float] = None          # None=난이도 기반 기본
    gimmick_unlock_levels: Optional[Dict[str, int]] = None  # 없으면 DEFAULT 사용
    # [보스 난이도] 타일 종류(useTileCount) 하한/보너스 — 보스는 주변 일반레벨보다 어렵게.
    # 종류 수 = 난이도 지배 레버라 그래프값 그대로면 저레벨 보스가 트리비얼(클리어율↑).
    tile_type_bonus: int = 1        # 그래프값 + N
    tile_type_floor: Optional[int] = None  # 최소 하한(종류). None=레벨대별 자동(초반 완화).
    tile_type_cap: int = 15         # 상한 = 스프라이트 풀 최대(t1~t15). 사실상 무제한
    use_tile_count_override: Optional[int] = None  # 지정 시 그래프/floor 무시하고 이 종류수 직접 사용(난이도 파악 슬라이더).
    layers: Optional[List[BossTemplateLayer]] = None  # 인라인 레이어(난이도 파악 미리보기). 있으면 저장분 조회 대신 사용.


@router.post("/generate/from-boss-template")
async def generate_from_boss_template(req: BossTemplateGenerateRequest):
    """보스 템플릿(다층 t0 모양)으로 레벨 생성.

    반자동: 템플릿 = 모양(t0)만. 여기서 useTileCount(레벨 그래프)+randSeed 세팅 후
    ÷3 보정/OOB/link 정화 오버레이. 타입은 t0라 게임이 런타임 분배. (기믹은 후속.)
    level_number 로 배정 구간(level_min~max) 맞는 템플릿 선택(복수면 결정적 로테이션).
    """
    import random as _random
    from ...core.generator import (
        LevelGenerator, get_use_tile_count_for_level,
    )
    from ...core.analyzer import LevelAnalyzer

    ln = int(req.level_number)
    # 인라인 layers(미리보기) 우선 — 저장 안 하고 현재 편집중 템플릿으로 난이도 파악.
    if req.layers is not None:
        tpl = {"id": "__preview__", "layers": [
            {"layer": l.layer, "col": l.col, "row": l.row, "positions": l.positions,
             "gimmicks": l.gimmicks or {}}
            for l in req.layers
        ]}
    else:
        templates = list(_load_boss_templates().values())
        cand = [t for t in templates if int(t.get("level_min", 0)) <= ln <= int(t.get("level_max", 999999))]
        if not cand:
            raise HTTPException(status_code=404, detail=f"no_boss_template_for_level_{ln}")
        cand.sort(key=lambda t: t.get("id", ""))
        tpl = cand[((ln // 10) - 1) % len(cand)]  # 구간 내 결정적 로테이션

    seed = req.random_seed if req.random_seed is not None else ((ln * 7919 + 13) % 900000 + 1000)
    if req.use_tile_count_override is not None:
        use_tile_count = max(1, min(15, int(req.use_tile_count_override)))  # 직접 지정(슬라이더)
    else:
        graph_v = get_use_tile_count_for_level(ln, req.tile_type_profile)
        # [보스 난이도 완화] 초반(10~30)은 언락 기믹 부족+튜토리얼이라 하한 없음(그래프값 그대로).
        # 40~100 floor 8, 110+ floor 9. 그래프값 + 보너스, [floor, cap] 클램프.
        if req.tile_type_floor is not None:
            floor = int(req.tile_type_floor)
        elif ln <= 30:
            floor = 0
        elif ln <= 100:
            floor = 8
        else:
            floor = 9
        use_tile_count = min(int(req.tile_type_cap), max(int(graph_v) + int(req.tile_type_bonus), floor))

    # [결정성] 기믹 선택(select_gimmicks_*)·_add_obstacles·÷3 보정은 전역 random 사용 →
    # seed 안 고정하면 매 호출 기믹배치/패딩 달라져 tile_count 흔들림(난이도 파악 92 vs 실제 93).
    # 여기서 전역 random을 seed로 고정 → 같은 (레벨·seed·종류수)면 추정==실제.
    _random.seed(seed)

    # 다층 t0 레벨 조립
    tpl_layers = sorted(tpl.get("layers", []), key=lambda l: l.get("layer", 0))
    level: Dict[str, Any] = {
        "layer": len(tpl_layers),
        "useTileCount": int(use_tile_count),
        "randSeed": int(seed),
        "autoCollectCount": 0,
    }
    # 배치만으로 언클리어러블(0%) 되는 무효 기믹 제거 카운터. (게임 CheckEffectTileCanUncover 정합)
    # chain: 좌/우(수평) 이웃 픽 시 언락 → 좌우 둘다 없으면(수평 이웃 0) 영원히 잠김.
    # grass: 게임 grassEffectRemainCount=2 고정, 4방 남은이웃 < 2 이면 못 벗김 → 4방 이웃 ≥2 필요.
    chain_stripped = 0
    grass_stripped = 0
    for l in tpl_layers:
        i = int(l.get("layer", 0))
        col = int(l.get("col", 8)); row = int(l.get("row", 8))
        gm = l.get("gimmicks") or {}  # {pos: gimmick} 수동 지정 — 속성으로 bake(자동배치가 보존)
        pos_set = {str(p) for p in l.get("positions", []) if isinstance(p, str)}
        tiles: Dict[str, Any] = {}
        for p in pos_set:
            eff = str(gm.get(p, ""))
            try:
                px, py = map(int, p.split("_"))
            except ValueError:
                tiles[p] = ["t0", eff]
                continue
            if eff == "chain":  # 좌/우(수평) 이웃 ≥1 필요
                if f"{px-1}_{py}" not in pos_set and f"{px+1}_{py}" not in pos_set:
                    eff = ""; chain_stripped += 1
            elif eff == "grass":  # 4방(상하좌우) 이웃 ≥2 필요 (게임 remaining=2)
                _n4 = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if f"{px+dx}_{py+dy}" in pos_set)
                if _n4 < 2:
                    eff = ""; grass_stripped += 1
            elif eff == "bomb":  # 게임 bomb는 xEffect=숫자(카운트다운). "bomb"만 쓰면 Parse→0→즉시 게임오버.
                eff = f"bomb_{_random.randint(5, 10)}"  # 생성기와 동일 카운트다운 범위
            tiles[p] = ["t0", eff]
        level[f"layer_{i}"] = {"col": str(col), "row": str(row), "tiles": tiles, "num": str(len(tiles))}

    # [수동 컨테이너] 사용자가 craft/stack을 직접 그린 셀(`["t0","craft"|"stack"]`)을 실제 컨테이너로 변환.
    # 수동 배치 = 위치·개수 고정 → 타일수 결정적(자동배치 무작위성 제거). craft는 같은 층 빈 출력칸 필요,
    # 없으면 stack으로 폴백(컨테이너 유지). goalCount 누적. 변환된 셀은 아래 자동 컨테이너 대상서 제외됨.
    manual_containers = 0
    _DIRS = {"e": (1, 0), "w": (-1, 0), "s": (0, 1), "n": (0, -1)}
    _gcnt = level.setdefault("goalCount", {})
    for i in range(len(tpl_layers)):
        ld = level.get(f"layer_{i}", {})
        tmap = ld.get("tiles", {})
        col_t = int(ld.get("col", 8)); row_t = int(ld.get("row", 8))
        for pos, t in list(tmap.items()):
            if not (isinstance(t, list) and len(t) >= 2 and t[0] == "t0"):
                continue
            parts = str(t[1]).split("_")  # "craft_e_3" → [craft,e,3] / "craft" → [craft]
            if parts[0] not in ("craft", "stack"):
                continue
            ctype = parts[0]
            cdir = parts[1] if len(parts) >= 3 and parts[1] in _DIRS else "e"
            inner = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) > 0 else 3
            # [일반레벨 동일 파이프라인] 컨테이너 내부는 ÷3 (일반레벨=3). 비-÷3이면 field t0가 ÷3 못돼
            # 게임 분배서 외톨이 타입 발생. → 내부를 3의 배수로 클램프(최소 3) → field·내부 모두 ÷3.
            inner = max(3, round(inner / 3) * 3)
            # [오프셋 방향 클리어 — stack 전용] stack은 내부타일이 방향으로 시각 오프셋되며 쌓여
            # 그 방향 일반타일을 '시각적으로 덮지만 선택 가능'하게 만들어 착각 유발(게임 확인).
            # craft는 InitHighestTileAtSpawn이 배출위치 기존타일 처리(대기/위에 쌓기)해 문제없음 → 방향 그대로.
            # stack만: 지정 방향 막혔으면 '오프셋 셀 빈' 방향으로 회전, 없으면 지정 유지(최선).
            if ctype == "stack":
                x0, y0 = map(int, pos.split("_"))
                steps = max(1, int((inner - 1) * 0.1) + 1)  # 내부≤10→1칸, 11~20→2칸

                def _offset_clear(d: str) -> bool:
                    dc, dr = _DIRS[d]
                    for s in range(1, steps + 1):
                        nx, ny = x0 + dc * s, y0 + dr * s
                        if not (0 <= nx < col_t and 0 <= ny < row_t):
                            return False
                        if f"{nx}_{ny}" in tmap:
                            return False
                    return True

                if not _offset_clear(cdir):
                    alts = [d for d in _DIRS if _offset_clear(d)]
                    if alts:
                        cdir = alts[0]  # 빈 방향으로 회전
            full = f"{ctype}_{cdir}"
            tmap[pos] = [full, "", [inner]]
            _gcnt[full] = _gcnt.get(full, 0) + inner
            manual_containers += 1
        ld["num"] = str(len(tmap))

    # [보스 컨테이너 기믹] craft/stack 골 배치 — 저레벨(11~30) 언락 기믹이 craft/stack뿐이라
    # 속성기믹만으론 기믹 0. 상위층 t0 셀 일부를 컨테이너로 변환(내부 t0×3, 게임 분배). craft는
    # 출력방향 빈 칸 확보. goalCount 누적. ÷3은 finalize가 보정.
    # [수동 우선] 사용자가 craft/stack 직접 그렸으면(manual_containers>0) 자동배치 스킵 → 타일수 고정.
    if req.apply_gimmicks and manual_containers == 0:
        import random as _r2
        from .generate import DEFAULT_GIMMICK_UNLOCK_LEVELS as _UNLOCK
        unlock2 = req.gimmick_unlock_levels or _UNLOCK
        containers = []
        if ln >= int(unlock2.get("craft", 11)):
            containers.append("craft")
        if ln >= int(unlock2.get("stack", 21)):
            containers.append("stack")
        if containers:
            rng2 = _r2.Random(int(seed) * 31 + 7)
            td2 = float(req.target_difficulty) if req.target_difficulty is not None else 0.3
            n_want = max(1, min(4, round(1 + td2 * 3)))  # 1~4개
            top_i = len(tpl_layers) - 1  # 상위층(픽 가능)
            ld = level.get(f"layer_{top_i}", {})
            tmap = ld.get("tiles", {})
            col_t = int(ld.get("col", 8)); row_t = int(ld.get("row", 8))
            gcnt = level.setdefault("goalCount", {})
            DIRS = {"e": (1, 0), "w": (-1, 0), "s": (0, 1), "n": (0, -1)}
            # 수동 기믹(속성) 지정된 셀은 제외 → 컨테이너가 수동 chain/ice 등 덮어쓰지 않음(보존).
            cells = [p for p, t in tmap.items()
                     if isinstance(t, list) and len(t) >= 2 and t[0] == "t0" and not t[1]]
            rng2.shuffle(cells)
            placed = 0
            for pos in cells:
                if placed >= n_want:
                    break
                x, y = map(int, pos.split("_"))
                ctype = rng2.choice(containers)
                if ctype == "stack":
                    full = f"stack_{rng2.choice(list(DIRS))}"  # 스택=제자리 누적(방향=시각 오프셋)
                else:
                    valid = [d for d, (dc, dr) in DIRS.items()
                             if 0 <= x + dc < col_t and 0 <= y + dr < row_t and f"{x+dc}_{y+dr}" not in tmap]
                    if not valid:
                        continue  # 출력칸 없음 → 스킵
                    full = f"craft_{rng2.choice(valid)}"
                tmap[pos] = [full, "", [3]]
                gcnt[full] = gcnt.get(full, 0) + 3
                placed += 1
            ld["num"] = str(len(tmap))

    gen = LevelGenerator()

    # [기믹 자동배치] 언락/난이도 기반 — 고정 모양 위에 속성 기믹 얹음(craft/stack 제외:
    # 보스는 순수 매치, craft sort 이슈·모양 훼손 회피). ÷3/정화 전에 실행.
    if req.apply_gimmicks:
        try:
            from .generate import select_gimmicks_with_unlock_probability, DEFAULT_GIMMICK_UNLOCK_LEVELS
            from ...models.level import GenerationParams
            td = float(req.target_difficulty) if req.target_difficulty is not None else 0.5
            unlock = req.gimmick_unlock_levels or DEFAULT_GIMMICK_UNLOCK_LEVELS
            # 속성 기믹만(컨테이너/키 제외)
            attr_pool = ["ice", "chain", "link", "grass", "frog", "bomb", "curtain", "teleport", "unknown"]
            selected = select_gimmicks_with_unlock_probability(
                level_number=ln, target_difficulty=td,
                unlock_levels=unlock, available_gimmicks=attr_pool,
            )
            gi = float(req.gimmick_intensity) if req.gimmick_intensity is not None else min(1.0, 0.4 + td)
            if selected and gi > 0:
                gparams = GenerationParams(
                    target_difficulty=td, level_number=ln,
                    obstacle_types=selected, gimmick_intensity=gi,
                )
                level = gen._add_obstacles(level, gparams)
        except Exception as ex:  # noqa: BLE001
            import logging as _logging
            _logging.getLogger(__name__).warning(f"[boss-template] 기믹 배치 스킵: {ex}")

    # 생성 tail 정화 재사용 (÷3 보정 → OOB → 고아 link → 컨테이너 내부 다양화[해당없음 안전])
    try:
        level = gen._remove_out_of_bounds_tiles(level)
        # [무효 기믹 일괄제거] OOB 후 이웃 사라진 chain/grass(수동+자동배치 모두) 속성 제거.
        # chain: 좌우 이웃 없음 / grass: 4방 이웃 없음 → 영원히 못 풀림(0%). 전 레이어 스캔.
        for _li in range(int(level.get("layer", 0))):
            _lt = (level.get(f"layer_{_li}", {}) or {}).get("tiles", {}) or {}
            for _p, _t in _lt.items():
                if not (isinstance(_t, list) and len(_t) >= 2):
                    continue
                _eff = _t[1]
                if _eff not in ("chain", "grass"):
                    continue
                try:
                    _px, _py = map(int, _p.split("_"))
                except ValueError:
                    continue
                if _eff == "chain":
                    if f"{_px-1}_{_py}" not in _lt and f"{_px+1}_{_py}" not in _lt:
                        _t[1] = ""; chain_stripped += 1
                else:  # grass — 4방 이웃 ≥2 필요(게임 remaining=2)
                    if sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if f"{_px+dx}_{_py+dy}" in _lt) < 2:
                        _t[1] = ""; grass_stripped += 1
        level = gen._finalize_divisibility_guarantee(level)
        level = gen._strip_orphaned_link_tiles(level)
        level = gen._diversify_container_inner_tiles(level)
        # [grass 홀짝착각방지] 짝수 층차 0오프셋 겹침 grass 일괄 제거(생성기와 동일 규칙).
        _before_g = grass_stripped
        level = gen._strip_confusing_grass(level)
        # (grass_stripped 카운트는 위 4방검사분만 반영 — 홀짝 제거분은 로그로 확인)
        del _before_g
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"boss_overlay_failed: {ex}")

    total = sum(len((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}) for i in range(level["layer"]))
    # [내역] t0(런타임 분배 대상 — ÷3 보정은 이 풀에 적용) vs 컨테이너(craft/stack — 셀1개+내부÷3 별도).
    # 총합(total)은 t0+컨테이너라 ÷3 아닐 수 있음(정상). 프론트 표시 오해 방지용.
    t0_count = 0
    container_count = 0
    for i in range(level["layer"]):
        for _t in ((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).values():
            if not isinstance(_t, list) or not _t:
                continue
            b = str(_t[0])
            if b == "t0":
                t0_count += 1
            elif b.startswith("craft") or b.startswith("stack"):
                container_count += 1
    # [실제 매치 타일 총수] 컨테이너 셀(craft/stack)은 배출기라 매치 대상 아님 → 총계 제외.
    # 실제 타일 = field t0 + 컨테이너 내부(배출) = 매치/수집 대상. max_moves·난이도 기준.
    inner_count = sum(int(v) for v in (level.get("goalCount", {}) or {}).values())
    actual_total = t0_count + inner_count
    level["max_moves"] = actual_total + 50
    if req.target_difficulty is not None:
        level["target_difficulty"] = float(req.target_difficulty)
    level["_boss_template_id"] = tpl.get("id")

    analyzer = LevelAnalyzer()
    try:
        static = analyzer.analyze(level)
        actual = float(static.score) / 100.0
        grade = static.grade.value if hasattr(static.grade, "value") else str(static.grade)
    except Exception:  # noqa: BLE001
        actual, grade = float(req.target_difficulty or 0.5), "C"

    return {
        "level_json": level,
        "actual_difficulty": actual,
        "grade": grade,
        "from_boss_template": True,
        "template_id": tpl.get("id"),
        "template_name": tpl.get("name"),
        "layer_count": len(tpl_layers),
        "tile_count": actual_total,        # 실제 플레이 총수(visual + 컨테이너 내부). 내부 반영.
        "visual_count": total,             # 화면 셀 수(컨테이너=1). 참고용
        "inner_count": inner_count,        # 컨테이너 내부 타일 합(런타임 배출)
        "t0_count": t0_count,              # 런타임 분배 대상 field t0(÷3 보정 적용 풀)
        "container_count": container_count,  # craft/stack 컨테이너 셀 수
        "chain_stripped": chain_stripped,  # 좌우 이웃없어 제거된 무효 체인 수(있으면 프론트 경고)
        "grass_stripped": grass_stripped,  # 4방 이웃없어 제거된 무효 잔디 수
    }


PATTERN_CONFIG_PATH = os.path.join(os.path.dirname(CUSTOM_PATTERNS_PATH), "pattern_config.json")

from pydantic import BaseModel as _BaseModel  # noqa: E402 — 아래 섹션들에서 공통 사용

# ===== [v15.50] 레벨 템플릿 — 원본 레벨 통째 저장 (기믹 포함) =====
LEVEL_TEMPLATES_PATH = os.path.join(os.path.dirname(CUSTOM_PATTERNS_PATH), "level_templates.json")


def _load_level_templates() -> Dict[str, Any]:
    try:
        with open(LEVEL_TEMPLATES_PATH, "r") as f:
            return json_module.load(f)
    except (FileNotFoundError, json_module.JSONDecodeError):
        return {"templates": {}}


def _save_level_templates(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(LEVEL_TEMPLATES_PATH), exist_ok=True)
    with open(LEVEL_TEMPLATES_PATH, "w") as f:
        json_module.dump(data, f, indent=2)


def _tile_effective_count(tile: Any) -> int:
    """타일 1개의 실효 카운트 — stack_s는 extra[0] 만큼, 나머지는 1.
    craft_s의 extra는 goal count이므로 타일 수 기여는 1."""
    if not isinstance(tile, list) or len(tile) < 1:
        return 1
    t0 = tile[0] if isinstance(tile[0], str) else ""
    if t0 == "stack_s":
        extra = tile[2] if len(tile) >= 3 else None
        if isinstance(extra, list) and len(extra) >= 1:
            try:
                return max(1, int(extra[0]))
            except (ValueError, TypeError):
                return 1
        return 1
    return 1


def _summarize_level_template(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """레벨 JSON에서 메타 요약 추출. 권위 소스는 game의 `num` 필드 — 그 게임의 진짜 타일 카운트.
    `num` 없거나 0이면 stack_s만 반영한 fallback 카운트."""
    try:
        num_layers = int(level_json.get("layer", 0) or 0)
    except (TypeError, ValueError):
        num_layers = 0
    ingame_cols: List[int] = []
    ingame_rows: List[int] = []
    total_tiles = 0
    total_positions = 0
    gimmick_types: Dict[str, int] = {}
    for i in range(num_layers):
        ld = level_json.get(f"layer_{i}") or {}
        if not isinstance(ld, dict):
            continue
        try:
            col = int(ld.get("col") or 0)
            row = int(ld.get("row") or 0)
        except (TypeError, ValueError):
            col, row = 0, 0
        ingame_cols.append(col)
        ingame_rows.append(row)

        tiles_raw = ld.get("tiles")
        tiles = tiles_raw if isinstance(tiles_raw, dict) else {}
        position_count_layer = 0
        fallback_eff_count = 0
        if isinstance(tiles, dict):
            position_count_layer = len(tiles)
            for tile in tiles.values():
                fallback_eff_count += _tile_effective_count(tile)
                if isinstance(tile, list) and len(tile) >= 2:
                    attr = tile[1] if isinstance(tile[1], str) else ""
                    t0 = tile[0] if isinstance(tile[0], str) else ""
                    if attr:
                        gimmick_types[attr] = gimmick_types.get(attr, 0) + 1
                    if t0 and t0 != "t0" and not t0.startswith("t"):
                        gimmick_types[t0] = gimmick_types.get(t0, 0) + 1

        # 권위 있는 num 필드 우선
        game_num = ld.get("num")
        try:
            game_num_int = int(game_num) if game_num is not None else 0
        except (TypeError, ValueError):
            game_num_int = 0
        effective = game_num_int if game_num_int > 0 else fallback_eff_count

        total_tiles += effective
        total_positions += position_count_layer

    return {
        "layer_count": num_layers,
        "total_tiles": total_tiles,
        "total_positions": total_positions,
        "ingame_cols": ingame_cols,
        "ingame_rows": ingame_rows,
        "gimmick_types": gimmick_types,
    }


class LevelTemplateSaveRequest(_BaseModel):
    template_id: Optional[str] = None  # None이면 자동 생성
    name: str
    source_project_id: Optional[str] = None
    source_level_id: Optional[str] = None
    level_json: Dict[str, Any]  # 원본 rawJson 통째로 (기믹, col/row, tiles 포함)


@router.post("/debug/level-template-save")
async def debug_level_template_save(request: LevelTemplateSaveRequest):
    """레벨 JSON을 통째로 템플릿으로 저장. 기믹·위치 완전 보존."""
    data = _load_level_templates()
    templates = data.get("templates") or {}

    # template_id 자동 생성: source_level_id 있으면 그대로, 없으면 name + timestamp
    tid = request.template_id
    if not tid:
        if request.source_level_id:
            tid = f"{request.source_project_id or 'local'}__{request.source_level_id}"
        else:
            tid = f"tpl_{int(time.time() * 1000)}"

    summary = _summarize_level_template(request.level_json)
    templates[tid] = {
        "template_id": tid,
        "name": request.name or tid,
        "source_project_id": request.source_project_id,
        "source_level_id": request.source_level_id,
        "level_json": request.level_json,
        "created_at": int(time.time() * 1000),
        **summary,
    }
    data["templates"] = templates
    _save_level_templates(data)
    return {"saved": True, "template_id": tid, **summary}


@router.get("/debug/level-templates")
async def debug_level_templates_list():
    """레벨 템플릿 목록 조회 — level_json은 제외하고 메타만 반환.
    저장된 summary가 stale이면 즉시 재계산 + 저장 (num 필드 권위 기반)."""
    data = _load_level_templates()
    templates = data.get("templates") or {}
    dirty = False
    for tid, entry in list(templates.items()):
        lj = entry.get("level_json")
        if not isinstance(lj, dict):
            continue
        # total_positions 필드 없거나 stale일 가능성 → 재계산
        fresh = _summarize_level_template(lj)
        # 3배수 판정이 틀렸거나 필드 누락이면 갱신
        if (entry.get("total_tiles") != fresh["total_tiles"]
            or entry.get("total_positions") != fresh["total_positions"]
            or entry.get("layer_count") != fresh["layer_count"]):
            entry.update(fresh)
            templates[tid] = entry
            dirty = True
    if dirty:
        data["templates"] = templates
        _save_level_templates(data)

    result = []
    for tid, entry in templates.items():
        result.append({
            "template_id": tid,
            "name": entry.get("name", tid),
            "source_project_id": entry.get("source_project_id"),
            "source_level_id": entry.get("source_level_id"),
            "created_at": entry.get("created_at"),
            "layer_count": entry.get("layer_count", 0),
            "total_tiles": entry.get("total_tiles", 0),
            "total_positions": entry.get("total_positions"),
            "ingame_cols": entry.get("ingame_cols", []),
            "ingame_rows": entry.get("ingame_rows", []),
            "gimmick_types": entry.get("gimmick_types", {}),
            # [v15.53] 측정 난이도
            "measured_difficulty": entry.get("measured_difficulty"),
            "static_score": entry.get("static_score"),
            "static_grade": entry.get("static_grade"),
            "autoplay_score": entry.get("autoplay_score"),
            "autoplay_grade": entry.get("autoplay_grade"),
            "bot_clear_rates": entry.get("bot_clear_rates"),
            "difficulty_measured_at": entry.get("difficulty_measured_at"),
        })
    # 최신순 정렬
    result.sort(key=lambda t: t.get("created_at", 0), reverse=True)
    return {"templates": result, "total": len(result)}


@router.get("/debug/level-template/{template_id}")
async def debug_level_template_get(template_id: str):
    """특정 레벨 템플릿의 상세 (level_json 포함)."""
    data = _load_level_templates()
    templates = data.get("templates") or {}
    entry = templates.get(template_id)
    if not entry:
        return {"error": "not_found", "template_id": template_id}
    return entry


class LevelTemplateLayerUpdate(_BaseModel):
    layer: int
    # 클라이언트가 추가한 셀 좌표 ("x_y" 문자열). 기존 포지션은 gimmick과 함께 그대로 유지됨.
    added_positions: List[str] = []
    # 제거된 셀 좌표. 기존 tiles에서 삭제.
    removed_positions: List[str] = []
    # 선택적: 새 col/row (레이어 크기 변경 시)
    col: Optional[int] = None
    row: Optional[int] = None


class LevelTemplateUpdateRequest(_BaseModel):
    layers: List[LevelTemplateLayerUpdate]
    name: Optional[str] = None


@router.post("/debug/level-template/{template_id}/update")
async def debug_level_template_update(template_id: str, request: LevelTemplateUpdateRequest):
    """템플릿 레이어별 편집 — 추가/삭제된 셀을 diff로 받아 반영. 기믹 보존."""
    data = _load_level_templates()
    templates = data.get("templates") or {}
    entry = templates.get(template_id)
    if not entry:
        return {"error": "not_found", "template_id": template_id}

    level_json = entry.get("level_json") or {}
    if not isinstance(level_json, dict):
        return {"error": "invalid_level_json", "template_id": template_id}

    for lu in request.layers:
        layer_key = f"layer_{lu.layer}"
        ld = level_json.get(layer_key)
        if not isinstance(ld, dict):
            # 레이어가 없으면 생성
            ld = {"col": str(lu.col or 8), "row": str(lu.row or 8), "tiles": {}, "num": "0"}
            level_json[layer_key] = ld
        tiles = ld.get("tiles")
        if not isinstance(tiles, dict):
            tiles = {}
            ld["tiles"] = tiles

        # 제거: 기믹 포함 타일도 완전 삭제
        for pos in lu.removed_positions:
            if pos in tiles:
                del tiles[pos]

        # 추가: 기존에 없던 셀만 신규로 ["t0", ""] 할당. 이미 있으면 건드리지 않음 (기믹 보존).
        for pos in lu.added_positions:
            if pos not in tiles:
                tiles[pos] = ["t0", ""]

        # col/row 변경 지원
        if lu.col is not None:
            ld["col"] = str(lu.col)
        if lu.row is not None:
            ld["row"] = str(lu.row)

        ld["num"] = str(len(tiles))

    # 전체 layer 수 갱신 (필요 시)
    max_layer_idx = -1
    for k in level_json.keys():
        if k.startswith("layer_"):
            try:
                max_layer_idx = max(max_layer_idx, int(k.split("_")[1]))
            except (ValueError, IndexError):
                pass
    if max_layer_idx >= 0:
        level_json["layer"] = str(max_layer_idx + 1)

    if request.name is not None and request.name.strip():
        entry["name"] = request.name.strip()

    # 메타 재계산
    summary = _summarize_level_template(level_json)
    entry.update(summary)
    entry["level_json"] = level_json
    entry["updated_at"] = int(time.time() * 1000)
    templates[template_id] = entry
    data["templates"] = templates
    _save_level_templates(data)

    return {
        "updated": True,
        "template_id": template_id,
        **summary,
    }


def _normalize_level_json_strings(lj: Dict[str, Any]) -> Dict[str, Any]:
    """level_json을 분석기/엔진 호환 형태로 정규화:
    - 숫자 문자열 필드 → int (layer/col/row/num/goalCount/max_moves/useTileCount/autoCollectCount/randSeed)
    - 빈 tiles (리스트 또는 기타) → {} (dict)
    - 원본은 변경하지 않고 새 dict 반환."""
    out = dict(lj)
    if "layer" in out and isinstance(out["layer"], str):
        try: out["layer"] = int(out["layer"])
        except ValueError: pass
    for k in list(out.keys()):
        if not k.startswith("layer_"):
            continue
        layer_data = out[k]
        if not isinstance(layer_data, dict):
            continue
        new_ld = dict(layer_data)
        for f in ("col", "row", "num"):
            if f in new_ld and isinstance(new_ld[f], str):
                try: new_ld[f] = int(new_ld[f])
                except ValueError: pass
        # tiles: list(빈 배열) 또는 None → {} 로 강제 (빈 레이어 처리)
        tiles = new_ld.get("tiles")
        if tiles is None or isinstance(tiles, list):
            new_ld["tiles"] = {}
        out[k] = new_ld
    for f in ("goalCount", "max_moves", "useTileCount", "autoCollectCount", "randSeed"):
        if f in out and isinstance(out[f], str):
            try: out[f] = int(out[f])
            except ValueError: pass
    return out


class LevelTemplateFromTemplateRequest(_BaseModel):
    template_id: str
    level_number: Optional[int] = None          # 생성 레벨 번호 (번호별 타일 타입 결정용)
    use_tile_count: Optional[int] = 6           # 몇 종류 타일 쓸지
    randomize_tiles: bool = True                # 일반 t0 타일을 t1~t6로 재할당
    random_seed: Optional[int] = None
    # [보스 크롭] 지정 시 빈 가장자리를 균일 크롭해 선언 그리드 최대변을 이 값 이하로 축소.
    # 크롭 후에도 초과하면 미적용(응답 cropped=false). 보스 레벨 10x10 → 8 축소용(디바이스 가독성).
    crop_max_dim: Optional[int] = None


@router.post("/generate/from-template")
async def generate_from_template(request: LevelTemplateFromTemplateRequest):
    """템플릿 기반 프로덕션 레벨 생성. 기믹·위치·레이어 구조 보존, 일반 타일만 t1~t6 재할당.
    응답은 GenerateResponse와 호환 (level_json + actual_difficulty + grade)."""
    import copy
    import random
    from ...core.generator import select_color_balanced_tiles
    from ...core.analyzer import LevelAnalyzer

    data = _load_level_templates()
    templates = data.get("templates") or {}
    entry = templates.get(request.template_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"template_not_found: {request.template_id}")

    raw_lj = entry.get("level_json") or {}
    if not isinstance(raw_lj, dict):
        raise HTTPException(status_code=400, detail="invalid_level_json")

    # 1) 정규화 (string → int, list tiles → dict)
    level_json = copy.deepcopy(_normalize_level_json_strings(raw_lj))

    # 2) 타일 타입 재할당 (일반 t0 타일만, 기믹 보존)
    if request.randomize_tiles:
        tile_count = max(1, min(6, request.use_tile_count or 6))
        seed = request.random_seed if request.random_seed is not None else (
            request.level_number if request.level_number is not None else None
        )
        tile_types = select_color_balanced_tiles(tile_count, seed=seed)
        rng = random.Random(seed)

        try:
            num_layers = int(level_json.get("layer", 0) or 0)
        except (TypeError, ValueError):
            num_layers = 0

        replaced_t0 = 0
        for i in range(num_layers):
            ld = level_json.get(f"layer_{i}")
            if not isinstance(ld, dict):
                continue
            tiles = ld.get("tiles")
            if not isinstance(tiles, dict):
                continue
            for pos, tile in list(tiles.items()):
                if not isinstance(tile, list) or len(tile) < 1:
                    continue
                t0 = tile[0] if isinstance(tile[0], str) else ""
                # t0(placeholder) → t1~t6 색상. chain/link/curtain 등 attribute는 보존.
                # stack_s/craft_s/bomb 같은 기믹 tile_type은 건드리지 않음.
                if t0 == "t0":
                    tile[0] = rng.choice(tile_types)
                    replaced_t0 += 1

        # CRITICAL: useTileCount는 실제 결과를 반영해야 함.
        # 템플릿이 이미 사전 할당된 타입(t2, t6 등)이면 위 루프가 침묵 No-op이므로
        # tile_count(=6)을 그대로 기록하면 "6종 사용 중"이라는 거짓 메타가 됨.
        # 실제 등장한 일반 타일 타입만 카운트해서 useTileCount에 반영한다.
        actual_types: set = set()
        for i in range(num_layers):
            ld = level_json.get(f"layer_{i}")
            if not isinstance(ld, dict):
                continue
            tiles = ld.get("tiles")
            if not isinstance(tiles, dict):
                continue
            for tile in tiles.values():
                if not isinstance(tile, list) or len(tile) < 1:
                    continue
                tt = tile[0] if isinstance(tile[0], str) else ""
                # 일반 색상 타일만 카운트(t1~t15). 기믹·골 타일·t0 placeholder 제외.
                if tt.startswith("t") and tt[1:].isdigit() and tt != "t0":
                    actual_types.add(tt)
        if actual_types:
            level_json["useTileCount"] = len(actual_types)
        else:
            level_json["useTileCount"] = tile_count
        if replaced_t0 == 0 and len(actual_types) != tile_count:
            print(
                f"[from-template] template={request.template_id} pre-assigned tiles only "
                f"(t0 placeholders=0). Requested useTileCount={tile_count} but actual={len(actual_types)} "
                f"({sorted(actual_types)}). useTileCount adjusted to actual."
            )

    # randSeed 갱신 (템플릿마다 다른 시드 부여)
    level_json["randSeed"] = request.random_seed if request.random_seed is not None else int(time.time() * 1000) % 1000000

    # _preserve_pattern 플래그 추가 (프로덕션 후처리에서 구조 보호)
    level_json["_preserve_pattern"] = True

    # [보스 크롭] 빈 가장자리 균일 크롭으로 선언 그리드 최대변 축소(디바이스 가독성 ≤ crop_max_dim).
    # 순수 좌표 시프트(타일 수·타입·÷3 불변, 게임 무변경). 크롭 불가(D타입)면 미적용 → 응답 cropped 플래그.
    cropped_applied = False
    cropped_max_dim = None
    if request.crop_max_dim is not None:
        from ...core.generator import crop_level_to_max_dim
        cropped_applied, cropped_max_dim = crop_level_to_max_dim(level_json, int(request.crop_max_dim))

    # [÷3 게이트] from-template 은 generator.generate() 를 우회하므로 v16 권위 게이트를
    # 여기서 직접 호출(멱등). 템플릿이 비-÷3 타일 분배를 가지면 클리어 불가 레벨이 되는데,
    # 게이트가 잉여 t0/타일 r(1~2)개 제거로 총합 ÷3 → 클리어가능 보장. (root: 우회 경로 차단)
    try:
        from ...core.generator import LevelGenerator
        level_json = LevelGenerator()._finalize_divisibility_guarantee(level_json)
    except Exception as ex:
        print(f"[from-template] divisibility gate skipped: {ex}")

    # 3) 정적 분석으로 난이도/등급
    analyzer = LevelAnalyzer()
    try:
        static = analyzer.analyze(level_json)
        actual_difficulty = float(static.score) / 100.0
        grade = static.grade.value if hasattr(static.grade, 'value') else str(static.grade)
    except Exception as ex:
        actual_difficulty = float(entry.get("measured_difficulty") or 0.5)
        grade = entry.get("autoplay_grade") or "C"
        print(f"[WARN] Static analysis failed for template {request.template_id}: {ex}")

    # 4) 응답 — GenerateResponse 포맷 + 추가 메타
    return {
        "level_json": level_json,
        "actual_difficulty": actual_difficulty,
        "grade": grade,
        "generation_time_ms": 0,
        "from_template": True,
        "cropped": cropped_applied,
        "cropped_max_dim": cropped_max_dim,
        "template_id": request.template_id,
        "template_name": entry.get("name"),
        "template_measured_difficulty": entry.get("measured_difficulty"),
        "template_autoplay_grade": entry.get("autoplay_grade"),
    }


@router.post("/debug/level-template/{template_id}/measure")
async def debug_level_template_measure(template_id: str, iterations: int = 100):
    """템플릿 저장 데이터로 봇 시뮬레이션 + 난이도 측정 + 자동 저장.
    level_json의 문자열 숫자 필드를 내부에서 정규화하여 분석기에 전달."""
    from ...models.schemas import AutoPlayRequest
    from ...core.analyzer import LevelAnalyzer

    data = _load_level_templates()
    templates = data.get("templates") or {}
    entry = templates.get(template_id)
    if not entry:
        return {"error": "not_found", "template_id": template_id}

    raw_level_json = entry.get("level_json") or {}
    if not isinstance(raw_level_json, dict):
        return {"error": "invalid_level_json", "template_id": template_id}

    # 정규화 (string → int for layer/col/row/num/goalCount/max_moves)
    normalized_lj = _normalize_level_json_strings(raw_level_json)

    # autoplay 실행 — 기존 analyze_autoplay 로직 재사용
    try:
        autoplay_req = AutoPlayRequest(level_json=normalized_lj, iterations=iterations)
        analyzer = LevelAnalyzer()
        autoplay_resp = analyze_autoplay(autoplay_req, analyzer)
    except Exception as ex:
        return {"error": "measurement_failed", "template_id": template_id, "reason": str(ex)}

    # 결과를 템플릿 메타에 저장
    measured = (autoplay_resp.autoplay_score or 0) / 100.0
    bot_rates = {b.profile: b.clear_rate for b in autoplay_resp.bot_stats}
    entry["measured_difficulty"] = measured
    entry["static_score"] = autoplay_resp.static_score
    entry["static_grade"] = autoplay_resp.static_grade
    entry["autoplay_score"] = autoplay_resp.autoplay_score
    entry["autoplay_grade"] = autoplay_resp.autoplay_grade
    entry["bot_clear_rates"] = bot_rates
    entry["difficulty_measured_at"] = int(time.time() * 1000)
    templates[template_id] = entry
    data["templates"] = templates
    _save_level_templates(data)

    return {
        "measured": True,
        "template_id": template_id,
        "measured_difficulty": measured,
        "autoplay_score": autoplay_resp.autoplay_score,
        "autoplay_grade": autoplay_resp.autoplay_grade,
        "static_score": autoplay_resp.static_score,
        "static_grade": autoplay_resp.static_grade,
        "bot_clear_rates": bot_rates,
    }


class LevelTemplateDifficultyRequest(_BaseModel):
    measured_difficulty: float        # 0.0~1.0 — autoplay_score/100 또는 수동
    static_score: Optional[float] = None      # 0~100
    static_grade: Optional[str] = None
    autoplay_score: Optional[float] = None    # 0~100
    autoplay_grade: Optional[str] = None
    bot_clear_rates: Optional[Dict[str, float]] = None   # {bot_name: clear_rate}


@router.post("/debug/level-template/{template_id}/set-difficulty")
async def debug_level_template_set_difficulty(template_id: str, request: LevelTemplateDifficultyRequest):
    """봇 시뮬 결과를 템플릿 메타에 저장. 프로덕션 자동 배치 시 사용."""
    data = _load_level_templates()
    templates = data.get("templates") or {}
    entry = templates.get(template_id)
    if not entry:
        return {"error": "not_found", "template_id": template_id}

    entry["measured_difficulty"] = float(request.measured_difficulty)
    if request.static_score is not None:
        entry["static_score"] = float(request.static_score)
    if request.static_grade is not None:
        entry["static_grade"] = request.static_grade
    if request.autoplay_score is not None:
        entry["autoplay_score"] = float(request.autoplay_score)
    if request.autoplay_grade is not None:
        entry["autoplay_grade"] = request.autoplay_grade
    if request.bot_clear_rates is not None:
        entry["bot_clear_rates"] = request.bot_clear_rates
    entry["difficulty_measured_at"] = int(time.time() * 1000)

    templates[template_id] = entry
    data["templates"] = templates
    _save_level_templates(data)

    return {
        "saved": True,
        "template_id": template_id,
        "measured_difficulty": entry["measured_difficulty"],
    }


@router.delete("/debug/level-template/{template_id}")
async def debug_level_template_delete(template_id: str):
    data = _load_level_templates()
    templates = data.get("templates") or {}
    if template_id in templates:
        del templates[template_id]
        data["templates"] = templates
        _save_level_templates(data)
        return {"deleted": True, "template_id": template_id}
    return {"deleted": False, "template_id": template_id, "error": "not_found"}


@router.post("/debug/level-template-spawn/{template_id}")
async def debug_level_template_spawn(template_id: str):
    """템플릿을 디버거 test-level과 동일한 응답 포맷으로 반환 (원본 level_json 그대로)."""
    data = _load_level_templates()
    templates = data.get("templates") or {}
    entry = templates.get(template_id)
    if not entry:
        return {"error": "not_found", "template_id": template_id}

    level_json = entry.get("level_json") or {}
    try:
        num_layers = int(level_json.get("layer", 0) or 0)
    except (TypeError, ValueError):
        num_layers = 0
    layer_views = []
    total_tiles = 0          # stack 전개
    total_positions = 0      # 그리드 셀 수
    for i in range(num_layers):
        ld = level_json.get(f"layer_{i}") or {}
        tiles = ld.get("tiles") or {}
        try:
            gc = int(ld.get("col") or 0)
            gr = int(ld.get("row") or 0)
        except (TypeError, ValueError):
            gc, gr = 0, 0
        if not tiles or gc <= 0 or gr <= 0:
            layer_views.append({
                "layer": i, "count": 0, "position_count": 0,
                "grid": [], "grid_size": 0, "grid_cols": gc, "grid_rows": gr,
                "tiles_detail": {},
            })
            continue
        grid = [[0] * gc for _ in range(gr)]
        tiles_detail: Dict[str, Any] = {}
        layer_position_count = 0
        fallback_count = 0
        for pos, tile in tiles.items():
            if "_" not in pos:
                continue
            try:
                x, y = int(pos.split("_")[0]), int(pos.split("_")[1])
            except ValueError:
                continue
            if 0 <= x < gc and 0 <= y < gr:
                grid[y][x] = 1
                layer_position_count += 1
                eff = _tile_effective_count(tile)
                fallback_count += eff
                t0 = tile[0] if isinstance(tile, list) and len(tile) >= 1 and isinstance(tile[0], str) else "t0"
                attr = tile[1] if isinstance(tile, list) and len(tile) >= 2 and isinstance(tile[1], str) else ""
                extra = tile[2] if isinstance(tile, list) and len(tile) >= 3 else None
                tiles_detail[pos] = {
                    "tile_type": t0,
                    "attribute": attr,
                    "extra": extra,
                    "effective_count": eff,
                }
        # 권위 소스: 게임의 num 필드. 없으면 fallback.
        game_num = ld.get("num")
        try:
            game_num_int = int(game_num) if game_num is not None else 0
        except (TypeError, ValueError):
            game_num_int = 0
        layer_effective_count = game_num_int if game_num_int > 0 else fallback_count
        layer_views.append({
            "layer": i,
            "count": layer_effective_count,
            "position_count": layer_position_count,
            "grid_size": max(gc, gr),
            "grid_cols": gc,
            "grid_rows": gr,
            "grid": grid,
            "tiles_detail": tiles_detail,
        })
        total_tiles += layer_effective_count
        total_positions += layer_position_count

    return {
        "template_id": template_id,
        "name": entry.get("name", template_id),
        "num_layers": num_layers,
        "total_tiles": total_tiles,
        "total_positions": total_positions,
        "layers": layer_views,
        "level_json": level_json,
        "gimmick_types": entry.get("gimmick_types", {}),
    }


def _load_pattern_config() -> Dict[str, Any]:
    try:
        with open(PATTERN_CONFIG_PATH, "r") as f:
            return json_module.load(f)
    except (FileNotFoundError, json_module.JSONDecodeError):
        return {"disabled_patterns": [], "custom_pattern_names": {}}


def _save_pattern_config(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(PATTERN_CONFIG_PATH), exist_ok=True)
    with open(PATTERN_CONFIG_PATH, "w") as f:
        json_module.dump(data, f, indent=2)


class PatternSaveRequest(_BaseModel):
    pattern_index: int
    grid_size: int = 8
    positions: List[str]
    # [v15.49] 원본 레벨 재현용 메타데이터 (선택적)
    ingame_origin: Optional[List[int]] = None   # [minX, minY] — bbox의 원본 ingame 좌표
    ingame_col: Optional[int] = None             # 원본 레이어의 ingame col
    ingame_row: Optional[int] = None             # 원본 레이어의 ingame row
    bbox_pad: Optional[List[int]] = None         # [padX, padY] — 저장 시 적용된 bbox 중앙 패딩


@router.post("/debug/pattern-save")
async def debug_pattern_save(request: PatternSaveRequest):
    """커스텀 패턴 저장. 크기별로 별도 저장됨."""
    data = _load_custom_patterns()
    size_key = f"{request.pattern_index}_{request.grid_size}x{request.grid_size}"
    entry: Dict[str, Any] = {
        "grid_size": request.grid_size,
        "positions": request.positions,
        "count": len(request.positions),
    }
    if request.ingame_origin is not None:
        entry["ingame_origin"] = request.ingame_origin
    if request.ingame_col is not None:
        entry["ingame_col"] = request.ingame_col
    if request.ingame_row is not None:
        entry["ingame_row"] = request.ingame_row
    if request.bbox_pad is not None:
        entry["bbox_pad"] = request.bbox_pad
    data[size_key] = entry
    _save_custom_patterns(data)
    return {"saved": True, "pattern_index": request.pattern_index, "grid_size": request.grid_size, "positions_count": len(request.positions)}


@router.delete("/debug/pattern-save/{pattern_index}")
async def debug_pattern_delete(pattern_index: int, grid_size: Optional[int] = None):
    """커스텀 패턴 삭제. grid_size 지정 시 해당 크기만, 없으면 해당 인덱스의 모든 크기 삭제."""
    data = _load_custom_patterns()
    removed: List[str] = []
    if grid_size is not None:
        size_key = f"{pattern_index}_{grid_size}x{grid_size}"
        if size_key in data:
            del data[size_key]
            removed.append(size_key)
        legacy_key = str(pattern_index)
        if legacy_key in data:
            del data[legacy_key]
            removed.append(legacy_key)
    else:
        prefix = f"{pattern_index}_"
        for key in list(data.keys()):
            if key == str(pattern_index) or key.startswith(prefix):
                del data[key]
                removed.append(key)
    if removed:
        _save_custom_patterns(data)
    # synth 패턴은 DB가 정본 — DB에서도 삭제(없으면 0행, 무해). grid_size 단위 삭제는
    # 컨셉(모든 사이즈)을 함께 두는 게 일관적이라 인덱스 통째 삭제 시에만 DB 제거.
    db_removed = 0
    if grid_size is None:
        try:
            from ...core import pattern_db
            db_removed = pattern_db.delete_index(pattern_index)
        except Exception:
            db_removed = 0
    return {"deleted": True, "pattern_index": pattern_index, "removed_keys": removed, "db_rows_removed": db_removed}


@router.get("/debug/custom-patterns")
async def debug_list_custom_patterns():
    """저장된 커스텀 패턴 목록."""
    data = _load_custom_patterns()
    return {"custom_patterns": {k: v for k, v in data.items()}}


@router.get("/debug/unit-library")
async def debug_unit_library():
    """[유닛 조립] 소형 유닛 라이브러리(3·6·9칸) 미리보기. 각 유닛=이름·크기·밀도·그리드."""
    from ...core.unit_templates import units_by_size
    UNITS_BY_SIZE = units_by_size()
    out = []
    for size in sorted(UNITS_BY_SIZE.keys()):
        for u in UNITS_BY_SIZE[size]:
            grid = [[0] * u.w for _ in range(u.h)]
            for (x, y) in u.cells:
                grid[y][x] = 1
            out.append({
                "name": u.name, "size": u.size,
                "w": u.w, "h": u.h,
                "density": round(u.density(), 2),
                "grid": grid,
            })
    return {"units": out, "count": len(out)}


class UnitSaveRequest(_BaseModel):
    name: str
    cells: List[List[int]]   # [[x,y], ...] — 상대 좌표


@router.post("/debug/unit-save")
async def debug_unit_save(req: UnitSaveRequest):
    """유닛 추가/수정. 타일수 ÷3 + 3~15칸 검증. 같은 이름이면 덮어씀."""
    from ...core.unit_templates import save_unit
    ok, msg = save_unit(req.name, [tuple(c) for c in req.cells])
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"saved": True, "name": req.name, "size": len(req.cells)}


@router.delete("/debug/unit-save/{name}")
async def debug_unit_delete(name: str):
    """유닛 삭제."""
    from ...core.unit_templates import delete_unit
    return {"deleted": delete_unit(name), "name": name}


@router.post("/debug/unit-reset")
async def debug_unit_reset():
    """유닛 라이브러리를 기본 시드로 리셋."""
    from ...core.unit_templates import reset_units
    return {"reset": True, "count": reset_units()}


@router.get("/debug/pattern-usage/{pattern_index}")
async def debug_pattern_usage(pattern_index: int):
    """이 pattern_index 를 쓰는 프로덕션 레벨 스캔(고아 방지용). 삭제 전 참조 확인.
    Returns: {count, levels:[{batch_id, level_number}...]} (최대 50개)."""
    import glob as _glob
    prod_dir = os.path.normpath(os.path.join(
        os.path.dirname(CUSTOM_PATTERNS_PATH), "production"))
    hits: List[Dict[str, Any]] = []
    total = 0
    for f in _glob.glob(os.path.join(prod_dir, "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json_module.load(fh)
        except (OSError, ValueError):
            continue
        levels = d.get("levels") or (d.get("batch", {}) or {}).get("levels") or []
        for lv in levels:
            m = lv.get("meta", {}) if isinstance(lv, dict) else {}
            if m.get("pattern_index") == pattern_index:
                total += 1
                if len(hits) < 50:
                    hits.append({
                        "batch_id": os.path.basename(f)[:-5],
                        "level_number": m.get("level_number"),
                    })
    return {"pattern_index": pattern_index, "count": total, "levels": hits}


# ===== [v16 🅑] 절차적 패턴 생성 + 큐레이션 =====
def _positions_to_grid(positions: List[str], g: int) -> List[List[int]]:
    """미리보기용 2D 0/1 그리드."""
    grid = [[0] * g for _ in range(g)]
    for p in positions:
        try:
            x, y = (int(v) for v in p.split("_"))
        except (ValueError, TypeError):
            continue
        if 0 <= x < g and 0 <= y < g:
            grid[y][x] = 1
    return grid


def _next_custom_index(data: Dict[str, Any]) -> int:
    """custom_patterns에서 다음 빈 인덱스(>=64)."""
    used = set()
    for k in data.keys():
        try:
            used.add(int(k.split("_")[0]))
        except ValueError:
            continue
    idx = 64
    while idx in used:
        idx += 1
    return idx


def _diversity_params(diversity: Optional[float]) -> Dict[str, Any]:
    """랜덤성/다양성 슬라이더(0~1) → synthesize_concepts 파라미터 매핑.
    0 = 정돈(안전·고품질·사람템플릿 위주), 1 = 최대랜덤(유기적·실험적·셀룰러 위주).
    None = 기본값 사용(매핑 안 함)."""
    if diversity is None:
        return {}
    d = max(0.0, min(1.0, float(diversity)))
    return {
        "pretty": d < 0.6,                     # 0.6+ 면 비대칭/유기적 모양 허용
        "min_quality": round(0.62 - 0.30 * d, 3),   # 0.62→0.32 (높을수록 특이한 것 통과)
        "template_ratio": round(0.50 - 0.35 * d, 3),# 0.50→0.15 (높을수록 템플릿 적게=신규↑)
        "cellular_ratio": round(0.15 + 0.30 * d, 3),# 0.15→0.45 (높을수록 셀룰러 신규모양↑)
    }


class PatternSynthesizeRequest(_BaseModel):
    max_grid: int = 7                 # 컨셉 묶음 최대 그리드 한 변 (가시 캡 7)
    min_grid: int = 4                 # 컨셉 묶음 최소 그리드 한 변 (레벨 최소 4)
    count: int = 12                   # 반환 컨셉 수
    symmetry: Optional[str] = None    # both|h|v|rot180|quad|none, None이면 다양하게
    fill_min: float = 0.45
    fill_max: float = 0.85
    seed: Optional[int] = None
    cellular_only: bool = False       # True면 템플릿·모티프 배제, 순수 셀룰러 스프라이트만
    diversity: Optional[float] = None # 0=정돈~1=최대랜덤 (None=기본)
    seed_positions: Optional[List[str]] = None  # [A] 유저가 그린 씨앗 모양("x_y") — 이 모양 기반 변주 생성
    seed_grid: Optional[int] = None             # 씨앗 그리드 한 변
    seed_strength: float = 0.5                  # 씨앗 변형 강도 0~1


@router.post("/patterns/synthesize")
async def patterns_synthesize(request: PatternSynthesizeRequest):
    """
    [v16 🅑] 절차적으로 '모양 컨셉 묶음'을 생성·랭킹해 반환.
    한 컨셉 = (전략·대칭·채움률 고정)을 [min_grid..max_grid] 모든 사이즈로 렌더한 변형 묶음.
    레벨은 레이어마다 grid/grid+1 사이즈를 번갈아 쓰므로 한 인덱스에 모든 사이즈 변형이 필요.
    각 변형은 ÷3 보장 + 미리보기 grid + 미적 점수 포함. 저장은 별도(accept, 묶음 통째).
    """
    from ...core.pattern_synth import synthesize_concepts

    g_max = max(4, min(int(request.max_grid), 12))
    g_min = max(4, min(int(request.min_grid), g_max))
    concepts = synthesize_concepts(
        min_grid=g_min,
        max_grid=g_max,
        count=max(1, min(int(request.count), 48)),
        symmetry=request.symmetry,
        fill_range=(request.fill_min, request.fill_max),
        seed=request.seed,
        cellular_only=request.cellular_only,
        seed_positions=request.seed_positions,
        seed_grid=request.seed_grid,
        seed_strength=request.seed_strength,
        **_diversity_params(request.diversity),
    )
    return {"concepts": concepts, "count": len(concepts)}


class PatternAutoGenerateRequest(_BaseModel):
    count: int = 8                    # 자동 채택할 '비주얼 우수' 컨셉 수
    max_grid: int = 7
    min_grid: int = 4
    symmetry: Optional[str] = None
    fill_min: float = 0.45
    fill_max: float = 0.85
    seed: Optional[int] = None
    pool_multiplier: int = 12         # 후보 풀 배수(클수록 더 많이 생성→상위만 채택→품질↑)
    diversity: Optional[float] = None # 0=정돈~1=최대랜덤 (None=기본)
    seed_positions: Optional[List[str]] = None  # [A] 유저가 그린 씨앗 모양 — 이 모양 기반 변주 생성
    seed_grid: Optional[int] = None             # 씨앗 그리드 한 변
    seed_strength: float = 0.5                  # 씨앗 변형 강도 0~1


@router.post("/patterns/auto-generate")
async def patterns_auto_generate(request: PatternAutoGenerateRequest):
    """
    [v16 🅑] AI 자동 큐레이션: 대량 컨셉 풀을 생성·비주얼 점수로 랭킹해 상위 N개를
    custom_patterns.json에 자동 저장(사람 수동 채택 불필요). 각 컨셉은 모든 사이즈 변형 묶음
    + ÷3 보장. 저장된 인덱스/미리보기를 반환.
    """
    from ...core.pattern_synth import synthesize_concepts

    n = max(1, min(int(request.count), 48))
    g_max = max(4, min(int(request.max_grid), 12))
    g_min = max(4, min(int(request.min_grid), g_max))
    # 상위 N만 채택하므로 oversample을 크게 → 풀에서 비주얼 최상위만 선별
    concepts = synthesize_concepts(
        min_grid=g_min,
        max_grid=g_max,
        count=n,
        symmetry=request.symmetry,
        fill_range=(request.fill_min, request.fill_max),
        seed=request.seed,
        oversample=max(4, int(request.pool_multiplier)),
        seed_positions=request.seed_positions,
        seed_grid=request.seed_grid,
        seed_strength=request.seed_strength,
        **_diversity_params(request.diversity),
    )

    from ...core import pattern_db

    saved = []
    for c in concepts:
        idx = pattern_db.next_index()
        pattern_db.save_concept(
            idx, c["variants"], score=c["score"],
            strategy=c["strategy"], symmetry=c["symmetry"],
            name=f"ai_{c['strategy']}_{c['symmetry']}",
        )
        saved.append({
            "pattern_index": idx,
            "sizes": c["sizes"],
            "score": c["score"],
            "strategy": c["strategy"],
            "symmetry": c["symmetry"],
            "variants": c["variants"],  # 미리보기용(grid 포함)
        })
    pattern_db.materialize_to_json()  # DB(정본) → custom_patterns.json (생성기/에디터용)
    return {"saved_count": len(saved), "patterns": saved}


class PatternVariant(_BaseModel):
    grid_size: int
    positions: List[str]


class PatternAcceptRequest(_BaseModel):
    # 묶음(여러 사이즈 변형)을 한 인덱스에 저장. 단일 변형도 variants 1개로 전달.
    variants: Optional[List[PatternVariant]] = None
    pattern_index: Optional[int] = None  # 미지정 시 다음 빈 인덱스 자동 배정
    name: Optional[str] = None
    # [하위호환] 단일 변형 직접 전달도 허용
    positions: Optional[List[str]] = None
    grid_size: Optional[int] = None


@router.post("/patterns/accept")
async def patterns_accept(request: PatternAcceptRequest):
    """
    [v16 🅑] 채택한 '모양 컨셉 묶음'을 custom_patterns.json에 저장(라이브러리 확장).
    한 컨셉의 모든 사이즈 변형을 동일 pattern_index 아래 size_key별로 저장 →
    레벨 생성 시 레이어 사이즈별로 일관된 모양이 렌더됨. pattern_index 미지정 시 64+ 자동.
    """
    # 변형 목록 정규화 (묶음 우선, 없으면 단일)
    variants: List[PatternVariant] = list(request.variants or [])
    if not variants and request.positions is not None and request.grid_size is not None:
        variants = [PatternVariant(grid_size=request.grid_size, positions=request.positions)]
    if not variants:
        raise HTTPException(status_code=400, detail="variants(또는 positions+grid_size)가 필요함")
    for v in variants:
        if len(v.positions) % 3 != 0:
            raise HTTPException(status_code=400, detail=f"{v.grid_size}x{v.grid_size} positions 개수({len(v.positions)})가 3의 배수가 아님")

    from ...core import pattern_db

    idx = request.pattern_index if request.pattern_index is not None else pattern_db.next_index()
    saved_sizes = pattern_db.save_concept(
        idx,
        [{"grid_size": v.grid_size, "positions": v.positions} for v in variants],
        name=request.name,
    )
    pattern_db.materialize_to_json()  # DB(정본) → custom_patterns.json (생성기/에디터용)
    return {"saved": True, "pattern_index": idx, "sizes": saved_sizes, "variant_count": len(variants)}


# ===== 패턴 활성/비활성 설정 =====

@router.post("/debug/pattern-rename")
async def rename_pattern(pattern_index: int, name: str):
    """패턴 이름 변경."""
    config = _load_pattern_config()
    names = config.get("custom_pattern_names", {})
    names[str(pattern_index)] = name
    config["custom_pattern_names"] = names
    _save_pattern_config(config)
    return {"pattern_index": pattern_index, "name": name}


@router.get("/debug/pattern-config")
async def get_pattern_config(grid_size: int = 8):
    """패턴 활성/비활성 설정 + 커스텀 이름 조회 (그리드 크기별)."""
    config = _load_pattern_config()
    custom = _load_custom_patterns()

    disabled_map = config.get("disabled_patterns", {})
    # 마이그레이션: 기존 배열 → 크기별 객체
    if isinstance(disabled_map, list):
        disabled_list = list(disabled_map)
    else:
        disabled_list = disabled_map.get(str(grid_size), [])

    display_order = config.get("display_order", [])

    return {
        "disabled_patterns": disabled_list,
        "disabled_patterns_all": disabled_map,
        "display_order": display_order,
        "custom_pattern_names": config.get("custom_pattern_names", {}),
        "custom_pattern_count": len(custom),
        "custom_pattern_indices": sorted(set(int(k.split("_")[0]) for k in custom.keys() if k.split("_")[0].isdigit())),
        # 해당 크기에 커스텀이 있는 패턴 인덱스 목록
        "custom_for_size": sorted(set(
            int(k.split("_")[0]) for k in custom.keys()
            if f"_{grid_size}x{grid_size}" in k
        )),
    }


class PatternOrderRequest(_BaseModel):
    order: List[int]


@router.post("/debug/pattern-order")
async def save_pattern_order(request: PatternOrderRequest):
    """패턴 표시 순서 저장 (모든 크기 공통)."""
    config = _load_pattern_config()
    config["display_order"] = request.order
    # 구버전 크기별 순서 제거
    config.pop("display_orders", None)
    _save_pattern_config(config)
    return {"saved": True, "count": len(request.order)}


@router.post("/debug/pattern-toggle")
async def toggle_pattern(pattern_index: int, enabled: bool, grid_size: int = 8):
    """패턴 활성/비활성 토글 (그리드 크기별)."""
    config = _load_pattern_config()
    disabled_map = config.get("disabled_patterns", {})

    # 마이그레이션: 기존 배열 → 크기별 객체
    if isinstance(disabled_map, list):
        old_list = disabled_map
        disabled_map = {}
        for s in [6, 7, 8, 9]:
            disabled_map[str(s)] = list(old_list)
        config["disabled_patterns"] = disabled_map

    key = str(grid_size)
    if key not in disabled_map:
        disabled_map[key] = []

    disabled = set(disabled_map[key])
    if enabled:
        disabled.discard(pattern_index)
    else:
        disabled.add(pattern_index)
    disabled_map[key] = sorted(disabled)
    config["disabled_patterns"] = disabled_map
    _save_pattern_config(config)
    return {"pattern_index": pattern_index, "enabled": enabled, "grid_size": grid_size, "disabled_patterns": disabled_map[key]}


@router.post("/debug/pattern-create")
async def create_new_pattern(grid_size: int = 8, positions: List[str] = [], name: str = ""):
    """새 커스텀 패턴 추가 (인덱스 64~)."""
    custom = _load_custom_patterns()
    # 다음 사용 가능한 인덱스 찾기 (64부터)
    existing_indices = {int(k) for k in custom.keys()}
    new_index = 64
    while new_index in existing_indices:
        new_index += 1
    custom[str(new_index)] = {
        "grid_size": grid_size,
        "positions": positions,
        "count": len(positions),
        "name": name,
        "custom": True,
    }
    _save_custom_patterns(custom)
    return {"created": True, "pattern_index": new_index, "positions_count": len(positions)}


def _normalize_positions_div3(positions: List[str], grid_size: int) -> List[str]:
    """패턴 변형 셀 수를 3의 배수로 자동 정규화. 추가 우선(인접+대칭, 모양 보존),
    그리드 꽉 차면 가장자리 제거 폴백. 각 레이어 ÷3 → 하위 divisibility 트리밍 0 → 패턴 보존."""
    cells = set()
    for p in positions:
        try:
            x, y = map(int, p.split("_"))
        except ValueError:
            continue
        cells.add((x, y))
    r = len(cells) % 3
    if r == 0:
        return [f"{x}_{y}" for x, y in sorted(cells)]
    c = (grid_size - 1) / 2.0
    occ = set(cells)
    adj = set()
    for (x, y) in cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < grid_size and 0 <= ny < grid_size and (nx, ny) not in occ:
                adj.add((nx, ny))
    need = 3 - r

    def _add_score(cell):
        mx, my = int(round(2 * c - cell[0])), int(round(2 * c - cell[1]))
        sym = 0 if (mx, my) in occ else 1          # 대칭짝 존재 우선
        return (sym, (cell[0] - c) ** 2 + (cell[1] - c) ** 2)

    picks = sorted(adj, key=_add_score)[:need]
    if len(picks) >= need:                          # 추가 성공(모양 보존)
        cells |= set(picks)
    else:                                           # 그리드 꽉참 → 가장자리 r개 제거 폴백
        def _nbr(cell):
            return sum((cell[0] + dx, cell[1] + dy) in occ
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        for cell in sorted(cells, key=_nbr)[:r]:
            cells.discard(cell)
    return [f"{x}_{y}" for x, y in sorted(cells)]


class PatternVariantIn(_BaseModel):
    grid_size: int
    positions: List[str]


class PatternCreateMultiRequest(_BaseModel):
    name: str = ""
    variants: List[PatternVariantIn]   # 크기별로 따로 그린 변형들


@router.post("/debug/pattern-create-multi")
async def create_new_pattern_multi(request: PatternCreateMultiRequest):
    """새 커스텀 패턴을 이름 + 여러 크기 변형으로 한 번에 저장.
    각 크기(grid_size)는 사용자가 따로 그린 positions 로 저장된다(자동 fit 없음)."""
    variants = [v for v in request.variants if v.positions and len(v.positions) >= 3]
    if not variants:
        raise HTTPException(status_code=400, detail="유효한 변형 없음(각 크기 최소 3타일)")

    # [÷3 자동 정규화] 각 크기 변형을 3의 배수로 맞춤 → 레이어별 ÷3 → 하위 트리밍 0(패턴 보존)
    for v in variants:
        v.positions = _normalize_positions_div3(v.positions, v.grid_size)

    custom = _load_custom_patterns()
    # 사용중 인덱스 집계(base "64" + 크기변형 "64_8x8" 둘 다 접두 숫자로 판단)
    existing_indices = set()
    for k in custom.keys():
        head = str(k).split("_")[0]
        if head.isdigit():
            existing_indices.add(int(head))
    new_index = 64
    while new_index in existing_indices:
        new_index += 1

    # base 엔트리 = 이름 + 대표(첫) 변형
    primary = variants[0]
    custom[str(new_index)] = {
        "grid_size": primary.grid_size,
        "positions": primary.positions,
        "count": len(primary.positions),
        "name": request.name or f"custom_{new_index}",
        "custom": True,
    }
    # 크기별 변형 저장
    saved_sizes = []
    for v in variants:
        key = f"{new_index}_{v.grid_size}x{v.grid_size}"
        custom[key] = {
            "grid_size": v.grid_size,
            "positions": v.positions,
            "count": len(v.positions),
        }
        saved_sizes.append(v.grid_size)
    _save_custom_patterns(custom)

    # 이름을 pattern_config 에도 기록(목록 표시용)
    try:
        cfg = _load_pattern_config()
        cfg.setdefault("custom_pattern_names", {})[str(new_index)] = custom[str(new_index)]["name"]
        _save_pattern_config(cfg)
    except Exception as ex:  # noqa: BLE001
        print(f"[pattern-create-multi] name config 저장 스킵: {ex}")

    return {
        "created": True,
        "pattern_index": new_index,
        "name": custom[str(new_index)]["name"],
        "sizes": sorted(saved_sizes),
    }


class TestLevelLayerConfig(_BaseModel):
    grid_size: int = 8
    pattern_index: Optional[int] = None  # None = 전체 pattern_index 사용

class TestLevelRequest(_BaseModel):
    pattern_index: int
    layers: List[TestLevelLayerConfig]
    target_difficulty: float = 0.3
    render_base_size: Optional[int] = None  # None = auto(max(8, 최대 레이어 크기))


@router.post("/debug/test-level")
async def debug_test_level(request: TestLevelRequest):
    """패턴 + 레이어별 그리드 크기로 테스트 레벨 1개 생성. 레이어별 배치 시각화 포함."""
    generator = LevelGenerator()
    num_layers = len(request.layers)

    # [v15.44] 렌더 프레임 크기: 기본 max(8, 각 레이어 패턴 크기).
    # 짝수 레이어는 render_base, 홀수는 render_base-1 (인게임 0.5 오프셋 컨벤션).
    max_layer_size = max(l.grid_size for l in request.layers)
    render_base = request.render_base_size if request.render_base_size else max(8, max_layer_size)

    level: Dict[str, Any] = {
        "layer": num_layers,
        "useTileCount": "6",
        "randSeed": int(time.time()) % 1000000,
        "autoCollectCount": 0,
        "_preserve_pattern": True,
    }

    all_positions = []
    custom_data = _load_custom_patterns()

    for i, layer_cfg in enumerate(request.layers):
        gs = layer_cfg.grid_size
        is_odd = i % 2 == 1

        grid_size = render_base - 1 if is_odd else render_base

        layer_pat = layer_cfg.pattern_index if layer_cfg.pattern_index is not None else request.pattern_index

        # [v15.49] 커스텀 패턴 저장 시 기록한 ingame_origin 메타데이터가 있으면
        # 저장 변형의 bbox_pad와 함께 원본 ingame 위치로 복원.
        size_key = f"{layer_pat}_{gs}x{gs}"
        saved_entry = custom_data.get(size_key) if layer_pat is not None else None

        use_ingame_placement = (
            saved_entry is not None
            and saved_entry.get("ingame_origin") is not None
            and saved_entry.get("ingame_col") is not None
            and grid_size == saved_entry.get("ingame_col")  # 프레임이 원본 ingame col과 일치해야 복원 가능
        )

        positions = generator._generate_aesthetic_positions(
            gs, gs, target_count=1000, pattern_index=layer_pat
        )

        if use_ingame_placement:
            # shift = ingame_origin - bbox_pad → 저장 좌표를 원본 ingame 좌표로 이동
            origin = saved_entry["ingame_origin"]
            pad = saved_entry.get("bbox_pad") or [0, 0]
            shift_x = int(origin[0]) - int(pad[0])
            shift_y = int(origin[1]) - int(pad[1])
            offset_x = shift_x
            offset_y = shift_y
        else:
            # fallback: 중앙 정렬
            diff_x = grid_size - gs
            offset_x = (diff_x + 1) // 2 if diff_x % 2 == 1 else diff_x // 2
            offset_x = max(0, offset_x)
            offset_y = offset_x

        layer_key = f"layer_{i}"
        tiles = {}
        for pos in positions:
            x, y = int(pos.split("_")[0]), int(pos.split("_")[1])
            new_x = x + offset_x
            new_y = y + offset_y
            # 프레임 밖이면 스킵 (원본 ingame 복원 실패 시 안전장치)
            if new_x < 0 or new_y < 0 or new_x >= grid_size or new_y >= grid_size:
                continue
            new_pos = f"{new_x}_{new_y}"
            tiles[new_pos] = ["t0", ""]
            all_positions.append((i, new_pos))
        level[layer_key] = {
            "col": str(grid_size),
            "row": str(grid_size),
            "tiles": tiles,
            "num": str(len(tiles)),
        }

    # 타일 타입 재배정 (t0 → t1~t6 균등)
    import random
    total = len(all_positions)
    types_count = 6
    assignments = []
    per_type = (total // types_count // 3) * 3
    for t in range(1, types_count + 1):
        assignments.extend([f"t{t}"] * per_type)
    while len(assignments) < total:
        assignments.append(f"t{(len(assignments) % types_count) + 1}")
    random.shuffle(assignments)

    idx = 0
    for layer_idx, pos in all_positions:
        layer_key = f"layer_{layer_idx}"
        if idx < len(assignments):
            level[layer_key]["tiles"][pos] = [assignments[idx], ""]
        idx += 1

    # 레이어별 시각화
    layer_views = []
    for i in range(level.get("layer", 1)):
        tiles = level.get(f"layer_{i}", {}).get("tiles", {})
        if not tiles:
            layer_views.append({"layer": i, "count": 0, "grid": [], "grid_size": 0})
            continue
        gc = int(level.get(f"layer_{i}", {}).get("col", render_base))
        gr = int(level.get(f"layer_{i}", {}).get("row", render_base))
        grid = [[0] * gc for _ in range(gr)]
        for pos in tiles.keys():
            if "_" not in pos:
                continue
            x, y = int(pos.split("_")[0]), int(pos.split("_")[1])
            if 0 <= x < gc and 0 <= y < gr:
                grid[y][x] = 1
        layer_views.append({
            "layer": i,
            "count": len(tiles),
            "grid_size": max(gc, gr),
            "grid_cols": gc,
            "grid_rows": gr,
            "grid": grid,
        })

    return {
        "pattern_index": request.pattern_index,
        "num_layers": level.get("layer", 1),
        "total_tiles": sum(lv["count"] for lv in layer_views),
        "layers": layer_views,
        "level_json": level,
        "difficulty": request.target_difficulty,
        "grade": "N/A",
    }


@router.get("/debug/color-balance-test")
async def debug_color_balance_test(tile_count: int = 6, samples: int = 10):
    """[v15.40] 색상 균등 분배 테스트.

    tile_count개 타일을 색상 균등하게 선택하는 결과를 samples회 반복하여 보여줌.
    """
    from ...core.generator import select_color_balanced_tiles, COLOR_BUCKETS

    results = []
    color_stats_total: Dict[int, int] = {c: 0 for c in COLOR_BUCKETS}

    for i in range(samples):
        tiles = select_color_balanced_tiles(tile_count, seed=i * 100 + tile_count)
        # 색상별 카운트
        color_counts: Dict[int, int] = {c: 0 for c in COLOR_BUCKETS}
        for t in tiles:
            for c, bucket in COLOR_BUCKETS.items():
                if t in bucket:
                    color_counts[c] += 1
                    color_stats_total[c] += 1
                    break
        results.append({
            "seed": i,
            "tiles": tiles,
            "color_counts": color_counts,
        })

    return {
        "tile_count": tile_count,
        "samples": samples,
        "color_buckets": {str(c): tiles for c, tiles in COLOR_BUCKETS.items()},
        "results": results,
        "color_totals": color_stats_total,
        "balance_score": round(
            min(color_stats_total.values()) / max(max(color_stats_total.values()), 1) * 100, 1
        ) if any(v > 0 for v in color_stats_total.values()) else 0,
    }
