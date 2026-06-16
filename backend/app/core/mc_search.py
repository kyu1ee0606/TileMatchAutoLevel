"""
0단계: MC 탐색 루프 (generate-and-test).

기존 생성기(LevelGenerator)를 후보 공급원으로, MC 스킬 스윕을 목적함수로 사용해
목표 곡선 (theta0*, k*)에 가장 가까운 레벨을 탐색한다.

멀티 피델리티 구조:
1. 후보 N개 생성 (생성기 파라미터 변주)
2. 정적 체크 (타일 존재, 3배수)
3. 스크리닝: 스킬 3지점 × 저롤아웃 (병렬) → 대략적 곡선 거리로 상위 K 선별
4. 풀 측정: 기본 그리드 × 풀롤아웃 (병렬) → 최종 score 최소 후보 채택

자세한 설계: claudedocs/MC_PIPELINE_ROADMAP.md
"""
import logging
import random
from typing import Any, Dict, List, Optional

from ..models.level import GenerationParams
from .generator import LevelGenerator
from .mc_difficulty import _sigmoid

logger = logging.getLogger(__name__)

SCREEN_SKILL_GRID = [0.3, 0.6, 0.9]
SCREEN_ROLLOUTS = 8
DEFAULT_CANDIDATES = 16
DEFAULT_FINALISTS = 5
ACCEPT_TOLERANCE = 0.06  # score가 이보다 작으면 조기 채택

GRID_CHOICES = [(5, 5), (6, 6), (7, 7), (8, 8)]


def _count_total_tiles(level_json: Dict[str, Any]) -> int:
    total = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if isinstance(ld, dict) and isinstance(ld.get("tiles"), dict):
            total += len(ld["tiles"])
    return total


def _unlocked_gimmick_setup(
    level_number: int,
    gen_difficulty: float,
) -> Dict[str, Any]:
    """
    레벨 번호 기준 언락된 기믹만 사용하도록 obstacle/goal/tutorial 설정 구성.

    프로덕션 /generate 라우트와 동일한 헬퍼를 재사용해 언락 정책을 일치시킨다.
    (생성기는 obstacle_types=None이면 언락 무시하고 기본 풀을 쓰므로 반드시 명시 필요)
    라우트 모듈 임포트는 순환 참조 방지를 위해 지연 임포트.
    """
    from ..api.routes.generate import (
        DEFAULT_GIMMICK_UNLOCK_LEVELS,
        filter_goals_by_unlock_level,
        get_tutorial_gimmick,
        select_gimmicks_with_unlock_probability,
    )

    tutorial_gimmick = get_tutorial_gimmick(level_number)
    obstacle_types = select_gimmicks_with_unlock_probability(
        level_number=level_number,
        target_difficulty=gen_difficulty,
        unlock_levels=DEFAULT_GIMMICK_UNLOCK_LEVELS,
    )
    goals = filter_goals_by_unlock_level(
        None, level_number, DEFAULT_GIMMICK_UNLOCK_LEVELS, tutorial_gimmick
    )
    return {
        "obstacle_types": obstacle_types if obstacle_types else None,
        "goals": goals,
        "tutorial_gimmick": tutorial_gimmick,
    }


def sample_candidate_params(
    level_number: int,
    target_theta0: float,
    target_k: float,
    rng: random.Random,
) -> GenerationParams:
    """목표 곡선 주변에서 생성기 파라미터를 변주해 후보 파라미터를 샘플."""
    # 생성기의 target_difficulty는 자체 스케일 — θ0 주변에 ±0.15 지터
    gen_difficulty = min(0.95, max(0.05, target_theta0 + rng.uniform(-0.15, 0.15)))

    # θ0가 높을수록 큰 그리드/많은 레이어 쪽에 가중
    if target_theta0 < 0.3:
        grid = rng.choice(GRID_CHOICES[:2])
        max_layers = rng.randint(3, 5)
    elif target_theta0 < 0.6:
        grid = rng.choice(GRID_CHOICES[1:3])
        max_layers = rng.randint(4, 6)
    else:
        grid = rng.choice(GRID_CHOICES[2:])
        max_layers = rng.randint(5, 8)

    # 기믹 강도는 k의 핵심 레버: 목표 k가 낮을수록(완만한 곡선) 기믹을 줄인다
    if target_k <= 3.5:
        gimmick_intensity = rng.choice([0.0, 0.0, 0.5])
    elif target_k <= 5.5:
        gimmick_intensity = rng.choice([0.5, 1.0, 1.0])
    else:
        gimmick_intensity = rng.choice([1.0, 1.5, 2.0])

    # 레벨 번호 기준 언락된 기믹만 사용 (프로덕션 정책과 동일)
    gimmick_setup = _unlocked_gimmick_setup(level_number, gen_difficulty)

    return GenerationParams(
        target_difficulty=gen_difficulty,
        grid_size=grid,
        max_layers=max_layers,
        gimmick_intensity=gimmick_intensity,
        level_number=level_number,
        pattern_index=None,  # 자동 선택 (다양성)
        obstacle_types=gimmick_setup["obstacle_types"],
        goals=gimmick_setup["goals"],
        tutorial_gimmick=gimmick_setup["tutorial_gimmick"],
    )


def _params_summary(params: GenerationParams) -> Dict[str, Any]:
    return {
        "gen_difficulty": round(params.target_difficulty, 3),
        "grid": f"{params.grid_size[0]}x{params.grid_size[1]}",
        "max_layers": params.max_layers,
        "gimmick_intensity": params.gimmick_intensity,
        "gimmicks": ",".join(params.obstacle_types) if params.obstacle_types else "없음",
    }


def generate_candidates(
    level_number: int,
    target_theta0: float,
    target_k: float,
    count: int,
    seed: int,
) -> List[Dict[str, Any]]:
    """후보 레벨 생성 + 정적 체크. 반환: [{index, level_json, gen_params, static_ok, reject_reason}]"""
    rng = random.Random(seed)
    generator = LevelGenerator()
    candidates: List[Dict[str, Any]] = []

    for i in range(count):
        params = sample_candidate_params(level_number, target_theta0, target_k, rng)
        entry: Dict[str, Any] = {
            "index": i,
            "gen_params": _params_summary(params),
            "level_json": None,
            "static_ok": False,
            "reject_reason": None,
        }
        try:
            result = generator.generate(params)
            level_json = result.level_json
            level_json["target_difficulty"] = params.target_difficulty

            total_tiles = _count_total_tiles(level_json)
            # 충분한 이동 수 보장 (탐색은 곡선 형태가 목적 — 이동 수 부족으로 오염 방지)
            level_json.setdefault("max_moves", max(total_tiles + 20, int(total_tiles * 1.5)))

            # NOTE: 총 타일 3배수 체크는 하지 않는다 — craft/stack은 서브타일을 스폰하고
            # goal 타일은 매칭 대상이 아니라서 배치 수 기준 3배수가 성립하지 않음.
            # 유효성은 생성기 내부 보장 + MC 스크리닝(언클리어러블 탈락)이 담당.
            if total_tiles == 0:
                entry["reject_reason"] = "no_tiles"
            else:
                entry["level_json"] = level_json
                entry["static_ok"] = True
        except Exception as exc:
            logger.warning("[mc_search] candidate %d generation failed: %s", i, exc)
            entry["reject_reason"] = f"generation_error: {exc}"
        candidates.append(entry)

    return candidates


def screen_distance(
    curve: List[Dict[str, Any]],
    target_theta0: float,
    target_k: float,
) -> Optional[float]:
    """스크리닝 곡선(3지점)과 목표 시그모이드의 평균 절대 거리. 언클리어러블이면 None."""
    if not curve:
        return None
    max_clear = max(c["clear_rate"] for c in curve)
    if max_clear < 0.05:
        return None  # 언클리어러블 의심 — 즉시 탈락
    dist = 0.0
    for c in curve:
        expected = _sigmoid(target_k * (c["theta"] - target_theta0))
        dist += abs(c["clear_rate"] - expected)
    return dist / len(curve)


def final_score(
    measurement: Dict[str, Any],
    target_theta0: float,
    target_k: float,
    target_difficulty_score: Optional[float] = None,
) -> Optional[float]:
    """풀 측정 결과의 목표 곡선 거리 score (낮을수록 좋음). 측정 불가면 None."""
    theta0 = measurement.get("theta0")
    k = measurement.get("k")
    if theta0 is None or k is None:
        return None
    if measurement.get("classification") == "unclearable_suspect":
        return None
    score = abs(theta0 - target_theta0) + abs(k - target_k) / 10.0
    if target_difficulty_score is not None and measurement.get("difficulty_score") is not None:
        score += abs(measurement["difficulty_score"] - target_difficulty_score)
    return round(score, 4)
