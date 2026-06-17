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

            for attempt in range(1, request.max_regeneration_retries + 1):
                try:
                    # 원본 파라미터 또는 level_json에서 추출
                    grid_size = level_item.grid_size or original_json.get("grid_size", [8, 8])
                    max_layers = level_item.max_layers or original_json.get("layer_count", 5)
                    tile_types = level_item.tile_types or _extract_tile_types(original_json)
                    obstacle_types = level_item.obstacle_types or _extract_obstacle_types(original_json)
                    symmetry_mode = level_item.symmetry_mode or original_json.get("symmetry_mode", "vertical")
                    pattern_type = level_item.pattern_type or original_json.get("pattern_type")
                    # [v15.40] 재생성 시 pattern_index 보존 - 누락 시 모양이 깨짐
                    pattern_index = level_item.pattern_index if hasattr(level_item, 'pattern_index') and level_item.pattern_index is not None else original_json.get("pattern_index")

                    # goals 추출
                    goals = original_json.get("goals", [{"type": "stack", "direction": "s", "count": 3}])

                    # 재생성 파라미터 구성
                    actual_symmetry = resolve_symmetry_mode(symmetry_mode, allow_none=False)

                    params = GenerationParams(
                        target_difficulty=target_difficulty,
                        grid_size=tuple(grid_size) if isinstance(grid_size, list) else grid_size,
                        max_layers=max_layers,
                        tile_types=tile_types,
                        obstacle_types=obstacle_types or [],
                        goals=goals,
                        symmetry_mode=actual_symmetry,
                        pattern_type=pattern_type,
                        pattern_index=pattern_index,
                        level_number=level_item.level_number,
                    )

                    # 레벨 생성
                    generator = get_level_generator()
                    gen_result = generator.generate(params)
                    new_json = gen_result.level_json
                    new_json["target_difficulty"] = target_difficulty

                    # 새 레벨 검증
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

                    logger.info(f"[BATCH_VERIFY_REGEN] Level {level_id} attempt {attempt}: "
                               f"match_score={verify_result.match_score:.1f}, passed={verify_result.passed}")

                    # 더 나은 결과면 업데이트
                    if verify_result.match_score > best_result.match_score:
                        best_result = verify_result
                        best_new_json = new_json

                    # 통과하면 조기 종료
                    if verify_result.passed:
                        break

                except Exception as e:
                    logger.warning(f"[BATCH_VERIFY_REGEN] Level {level_id} regeneration attempt {attempt} failed: {e}")
                    continue

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
    return {"deleted": True, "pattern_index": pattern_index, "removed_keys": removed}


@router.get("/debug/custom-patterns")
async def debug_list_custom_patterns():
    """저장된 커스텀 패턴 목록."""
    data = _load_custom_patterns()
    return {"custom_patterns": {k: v for k, v in data.items()}}


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


class PatternSynthesizeRequest(_BaseModel):
    max_grid: int = 7                 # 가시 footprint 한 변 최대 (4~7 권장)
    min_grid: Optional[int] = None    # 미지정 시 max_grid와 동일
    count: int = 12                   # 반환 후보 수
    symmetry: Optional[str] = None    # both|h|v|rot180|quad|none, None이면 다양하게
    fill_min: float = 0.45
    fill_max: float = 0.85
    seed: Optional[int] = None


@router.post("/patterns/synthesize")
async def patterns_synthesize(request: PatternSynthesizeRequest):
    """
    [v16 🅑] 절차적으로 ÷3-보장 패턴 후보를 생성·랭킹해 반환.
    각 후보는 positions + 미리보기 grid + 미적 점수(breakdown) 포함. 저장은 별도(accept).
    """
    from ...core.pattern_synth import synthesize_patterns

    g_max = max(4, min(int(request.max_grid), 12))
    cands = synthesize_patterns(
        max_grid=g_max,
        count=max(1, min(int(request.count), 48)),
        min_grid=request.min_grid,
        symmetry=request.symmetry,
        fill_range=(request.fill_min, request.fill_max),
        seed=request.seed,
    )
    for c in cands:
        c["grid"] = _positions_to_grid(c["positions"], c["grid_size"])
    return {"candidates": cands, "count": len(cands)}


class PatternAcceptRequest(_BaseModel):
    positions: List[str]
    grid_size: int
    pattern_index: Optional[int] = None  # 미지정 시 다음 빈 인덱스 자동 배정
    name: Optional[str] = None


@router.post("/patterns/accept")
async def patterns_accept(request: PatternAcceptRequest):
    """
    [v16 🅑] 큐레이션 UI에서 채택한 후보를 custom_patterns.json에 저장(라이브러리 확장).
    pattern_index 미지정 시 64+ 다음 빈 인덱스 자동 배정. ÷3 검증 후 저장.
    """
    if len(request.positions) % 3 != 0:
        raise HTTPException(status_code=400, detail=f"positions 개수({len(request.positions)})가 3의 배수가 아님")
    data = _load_custom_patterns()
    idx = request.pattern_index if request.pattern_index is not None else _next_custom_index(data)
    size_key = f"{idx}_{request.grid_size}x{request.grid_size}"
    entry: Dict[str, Any] = {
        "grid_size": request.grid_size,
        "positions": request.positions,
        "count": len(request.positions),
        "synth": True,  # 절차적 생성 표식
    }
    if request.name:
        entry["name"] = request.name
    data[size_key] = entry
    _save_custom_patterns(data)
    return {"saved": True, "pattern_index": idx, "grid_size": request.grid_size, "count": len(request.positions)}


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
