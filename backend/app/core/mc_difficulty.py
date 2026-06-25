"""
Monte Carlo skill-sweep difficulty engine (RL 시뮬레이션 1단계).

기존 난이도별 AI 시뮬레이션(5종 봇)과 독립적으로 동작하는 별도 모듈.
bot_simulator의 룰 엔진(simulate_with_profile)을 그대로 재사용하되,
봇 실력을 연속 파라미터 theta ∈ [0, 1]로 보간한 프로파일 스펙트럼을
스윕해서 "클리어율 50%가 되는 스킬 지점(theta_star)"을 연속 난이도
점수로 산출한다.

- theta = 0.0 → NOVICE 수준 (거의 랜덤)
- theta = 1.0 → EXPERT(fast) 수준 (lookahead 2로 캡 — 속도 확보)
- theta_star가 낮을수록 쉬운 레벨 (낮은 실력으로도 50% 클리어)
- 어떤 스킬로도 클리어 못하면 theta_star = None → 언클리어러블 의심
"""
import logging
import math
from typing import Any, Dict, List, Optional

from ..models.bot_profile import BotProfile, BotType
from .bot_simulator import BotSimulator, GIMMICK_NOTICE_RATES

logger = logging.getLogger(__name__)

# 스킬 보간 앵커: (novice 값, expert 값)
# expert 쪽 lookahead는 FAST_VERIFICATION 기준(2)으로 캡 — 스윕 속도 확보
_ANCHORS = {
    "mistake_rate": (0.45, 0.02),
    "lookahead_depth": (0, 2),
    "goal_priority": (0.2, 0.92),
    "blocking_awareness": (0.1, 0.92),
    "chain_preference": (0.05, 0.85),
    "patience": (0.2, 0.8),
    "risk_tolerance": (0.8, 0.2),
    "pattern_recognition": (0.15, 0.88),
}

DEFAULT_SKILL_GRID = [0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0]
DEFAULT_ROLLOUTS_PER_POINT = 40
DEFAULT_BASE_SEED = 4242

# === 예측 유저 클리어율 (검증 주력 지표) ===
# RL 스킬곡선을 "평균 캐주얼유저" 실력분포로 가중평균 → 모집단 클리어율%.
# 앵커: Casual 봇(mistake 0.25/lookahead 1) 역매핑 → theta ≈ 0.47.
# std 0.18: novice~숙련 캐주얼을 포괄하는 분포폭.
# 실측(2026-06-23): 재측정 std 1.8%p(안정), td추종 Spearman -0.69~-0.80.
CASUAL_SKILL_MEAN = 0.47
CASUAL_SKILL_STD = 0.18

# td → 목표 캐주얼 클리어율 설계곡선.
# [2026-06-23 v2] easy-mid 완화 — 실게임(Triple Match류) 쉬운레벨은 70-90% 클리어가 정상이고,
# 생성기도 utc6 밴드가 ~80%대라 원래 곡선(td0.2=48%)은 비현실적·도달불가였음. 측정기반 현실화:
# utc6(easy-mid)/utc7(hard)/utc8(extreme) 밴드가 best-of-N 분포로 걸칠 수 있게 단조 완만화.
TARGET_CLEAR_CURVE = [
    (0.0, 0.90), (0.1, 0.80), (0.2, 0.70), (0.3, 0.55), (0.4, 0.42),
    (0.5, 0.32), (0.6, 0.24), (0.7, 0.17), (0.8, 0.12), (0.9, 0.08), (1.0, 0.05),
]
CLEAR_RATE_TOLERANCE = 0.12  # ±12%p 통과밴드 (생성변동 ±20~25%p, best-of-N으로 흡수)


def population_clear_rate(
    curve: List[Dict[str, Any]],
    mean: float = CASUAL_SKILL_MEAN,
    std: float = CASUAL_SKILL_STD,
) -> float:
    """스킬곡선을 유저 실력분포(캐주얼 중심 정규)로 가중평균 → 예측 클리어율 0~1."""
    if not curve:
        return 0.0
    weights = [math.exp(-0.5 * ((c["theta"] - mean) / std) ** 2) for c in curve]
    sw = sum(weights)
    if sw <= 0:
        return 0.0
    return sum(weights[i] * curve[i]["clear_rate"] for i in range(len(curve))) / sw


def target_casual_clear_rate(target_difficulty: float) -> float:
    """목표난이도(td) → 목표 캐주얼 클리어율 0~1 (설계곡선 선형보간)."""
    td = max(0.0, min(1.0, target_difficulty))
    pts = TARGET_CLEAR_CURVE
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if td <= x1:
            f = 0.0 if x1 == x0 else (td - x0) / (x1 - x0)
            return y0 + (y1 - y0) * f
    return pts[-1][1]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _interp_gimmick_notice_rates(theta: float) -> Dict[str, float]:
    """
    기믹 인지율을 θ로 연속 보간 (NOVICE 열 ↔ EXPERT 열).

    기존 GIMMICK_NOTICE_RATES는 bot_type 5단계로만 인덱싱되어, 보간 봇이
    전부 AVERAGE 열에 고정되는 문제가 있었음. DI로 연속 값을 주입한다.
    """
    t = max(0.0, min(1.0, theta))
    return {
        key: _lerp(rates[0], rates[3], t)
        for key, rates in GIMMICK_NOTICE_RATES.items()
    }


def make_skill_profile(theta: float) -> BotProfile:
    """theta ∈ [0,1]을 NOVICE↔EXPERT 파라미터 선형 보간 프로파일로 변환."""
    t = max(0.0, min(1.0, theta))
    params = {k: _lerp(lo, hi, t) for k, (lo, hi) in _ANCHORS.items()}
    return BotProfile(
        name=f"MC Skill {t:.2f}",
        bot_type=BotType.AVERAGE,  # 분류용 라벨일 뿐, 행동은 파라미터가 결정
        description=f"스킬 스윕용 보간 봇 (theta={t:.2f})",
        mistake_rate=params["mistake_rate"],
        lookahead_depth=int(round(params["lookahead_depth"])),
        goal_priority=params["goal_priority"],
        blocking_awareness=params["blocking_awareness"],
        chain_preference=params["chain_preference"],
        patience=params["patience"],
        risk_tolerance=params["risk_tolerance"],
        pattern_recognition=params["pattern_recognition"],
        weight=1.0,
        gimmick_notice_override=_interp_gimmick_notice_rates(t),
    )


def _wilson_half_width(p: float, n: int, z: float = 1.96) -> float:
    """Wilson score interval half-width — 클리어율 추정 신뢰도 표시용."""
    if n <= 0:
        return 1.0
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    # center 이동분까지 포함한 보수적 half-width
    return max(margin, abs(center - p) + margin * 0.5)


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def fit_logistic(curve: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    P(clear) = sigmoid(k * (theta - theta0)) 를 라플라스 스무딩된 이항
    로그우도로 피팅 (순수 파이썬, 격자 탐색 + 2단계 국소 정밀화).

    완전 분리(0%/100% 다수) 시에도 발산하지 않도록 성공/실패에
    가상 관측 1회씩을 더한 (S+1)/(N+2) 카운트를 사용한다.
    """
    pts = [(c["theta"], c["clear_rate"], c["iterations"]) for c in curve if c["iterations"] > 0]
    if len(pts) < 3:
        return {"theta0": None, "k": None, "fit_ok": False}

    # 라플라스 스무딩된 (성공, 실패) 카운트
    obs = []
    for theta, p, n in pts:
        s = p * n
        obs.append((theta, s + 1.0, (n - s) + 1.0))

    def neg_log_lik(theta0: float, k: float) -> float:
        nll = 0.0
        for theta, succ, fail in obs:
            p = min(1.0 - 1e-9, max(1e-9, _sigmoid(k * (theta - theta0))))
            nll -= succ * math.log(p) + fail * math.log(1.0 - p)
        return nll

    # 1차 격자 탐색 → 2차 국소 정밀화
    best = (float("inf"), 0.5, 5.0)
    theta0_grid = [i * 0.05 for i in range(-10, 31)]          # -0.5 ~ 1.5
    k_grid = [0.5, 1.0, 2.0, 3.5, 5.0, 7.0, 10.0, 14.0, 20.0, 30.0]
    for t0 in theta0_grid:
        for k in k_grid:
            nll = neg_log_lik(t0, k)
            if nll < best[0]:
                best = (nll, t0, k)
    _, bt0, bk = best
    for t0 in [bt0 + i * 0.01 for i in range(-5, 6)]:
        for k in [max(0.1, bk * (1 + i * 0.1)) for i in range(-5, 6)]:
            nll = neg_log_lik(t0, k)
            if nll < best[0]:
                best = (nll, t0, k)

    _, theta0, k = best
    return {"theta0": round(theta0, 4), "k": round(k, 3), "fit_ok": True}


def compute_auc(curve: List[Dict[str, Any]]) -> float:
    """
    스킬→클리어율 곡선의 AUC (사다리꼴 적분, θ∈[0,1] 정규화).
    스무딩된 클리어율 (S+1)/(N+2) 사용 — 노이즈에 강건한 0~1 지표.
    난이도 점수는 1 - AUC.
    """
    pts = sorted(curve, key=lambda c: c["theta"])
    if not pts:
        return 0.0

    def smooth(c: Dict[str, Any]) -> float:
        n = c["iterations"]
        if n <= 0:
            return c["clear_rate"]
        return (c["clear_rate"] * n + 1.0) / (n + 2.0)

    # 경계 밖은 가장자리 값으로 연장 (그리드가 [0,1] 전체를 덮지 않을 수 있음)
    xs = [0.0] + [p["theta"] for p in pts] + [1.0]
    ys = [smooth(pts[0])] + [smooth(p) for p in pts] + [smooth(pts[-1])]
    area = 0.0
    for (x1, y1), (x2, y2) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        area += (x2 - x1) * (y1 + y2) / 2.0
    return max(0.0, min(1.0, area))


def compute_theta_star(curve: List[Dict[str, Any]]) -> Optional[float]:
    """
    클리어율이 50%를 넘는 첫 교차점을 선형 보간으로 계산.

    곡선이 단조가 아닐 수 있으므로(노이즈) 마지막 50% 미만 → 이상 교차를 사용.
    - 전 구간 ≥ 50%: 0.0 (매우 쉬움)
    - 전 구간 < 50%: None (이 스펙트럼 안에서는 50% 미달 — 매우 어려움/언클리어러블)
    """
    if not curve:
        return None
    pts = sorted(curve, key=lambda c: c["theta"])
    if pts[0]["clear_rate"] >= 0.5:
        return 0.0
    crossing = None
    for lo, hi in zip(pts, pts[1:]):
        if lo["clear_rate"] < 0.5 <= hi["clear_rate"]:
            span = hi["clear_rate"] - lo["clear_rate"]
            frac = 0.5 if span <= 0 else (0.5 - lo["clear_rate"]) / span
            crossing = lo["theta"] + (hi["theta"] - lo["theta"]) * frac
    return crossing


def classify_theta_star(theta_star: Optional[float], max_clear_rate: float) -> str:
    """theta_star 기반 난이도 분류 라벨."""
    if theta_star is None:
        # 최고 스킬로도 50% 미달
        if max_clear_rate < 0.05:
            return "unclearable_suspect"  # 언클리어러블 의심
        return "very_hard"
    if theta_star < 0.2:
        return "very_easy"
    if theta_star < 0.4:
        return "easy"
    if theta_star < 0.6:
        return "normal"
    if theta_star < 0.8:
        return "hard"
    return "very_hard"


def normalize_skill_grid(skill_grid: Optional[List[float]]) -> List[float]:
    """그리드 정규화: 기본값 대체, [0,1] 클램프, 중복 제거, 정렬."""
    grid = skill_grid if skill_grid else DEFAULT_SKILL_GRID
    return sorted({max(0.0, min(1.0, float(t))) for t in grid})


def sweep_point_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    단일 (레벨 × 스킬포인트) 시뮬레이션 — ProcessPool 분배 단위.

    레벨 단위가 아니라 포인트 단위로 쪼개면 워커 부하가 균등해져
    단일 레벨 측정도 코어 수만큼 병렬화된다 (총 연산량은 동일).
    """
    try:
        simulator = BotSimulator()
        theta = float(args["theta"])
        profile = make_skill_profile(theta)
        result = simulator.simulate_with_profile(
            args["level_json"],
            profile,
            iterations=max(4, min(500, int(args.get("rollouts", DEFAULT_ROLLOUTS_PER_POINT)))),
            max_moves=args.get("max_moves"),
            seed=args.get("seed", DEFAULT_BASE_SEED),
            honor_zero_seed=False,
            early_termination=True,
        )
        return {
            "key": args.get("key"),
            "error": None,
            "theta": round(theta, 4),
            "clear_rate": round(result.clear_rate, 4),
            "iterations": result.iterations,
            "ci_half_width": round(_wilson_half_width(result.clear_rate, result.iterations), 4),
            "avg_moves": round(result.avg_moves, 2),
            "avg_tiles_cleared": round(result.avg_tiles_cleared, 2),
        }
    except Exception as exc:
        logger.exception("[mc_difficulty] point task failed (key=%s, theta=%s)", args.get("key"), args.get("theta"))
        return {"key": args.get("key"), "theta": args.get("theta"), "error": str(exc)}


def run_skill_sweep(
    level_json: Dict[str, Any],
    skill_grid: Optional[List[float]] = None,
    rollouts_per_point: int = DEFAULT_ROLLOUTS_PER_POINT,
    seed: int = DEFAULT_BASE_SEED,
    max_moves: Optional[int] = None,
) -> Dict[str, Any]:
    """
    스킬 그리드를 스윕하며 클리어율 곡선과 theta_star를 산출 (단일 프로세스 버전).

    기존 시뮬레이션과 동일한 룰 엔진을 사용하므로 기믹 동작도 동일하게 반영됨.
    seed를 고정(공통 난수)해서 레벨 간 비교 시 분산을 줄인다.
    병렬 버전은 rl_sim 라우트가 sweep_point_task를 포인트 단위로 분배해 수행.
    """
    grid = normalize_skill_grid(skill_grid)
    rollouts = max(4, min(500, int(rollouts_per_point)))

    curve: List[Dict[str, Any]] = []
    for idx, theta in enumerate(grid):
        point = sweep_point_task({
            "level_json": level_json,
            "theta": theta,
            "rollouts": rollouts,
            "seed": seed + idx * 1000,  # 스킬 포인트별 독립 시드, 레벨 간에는 공통
            "max_moves": max_moves,
        })
        if point.get("error"):
            raise RuntimeError(point["error"])
        point.pop("key", None)
        point.pop("error", None)
        curve.append(point)

    return assemble_sweep_result(curve, grid, rollouts, seed)


def assemble_sweep_result(
    curve: List[Dict[str, Any]],
    grid: List[float],
    rollouts: int,
    seed: int,
) -> Dict[str, Any]:
    """스킬 곡선 포인트들로부터 모든 난이도 지표를 조립."""
    total_rollouts = sum(c["iterations"] for c in curve)
    theta_star = compute_theta_star(curve)
    max_clear = max((c["clear_rate"] for c in curve), default=0.0)
    min_clear = min((c["clear_rate"] for c in curve), default=0.0)

    # 메인 난이도 지표: 1 - AUC (강건, 이분 탐색 타겟용)
    auc = compute_auc(curve)
    difficulty_score = round(1.0 - auc, 4)

    # 보조 지표: 로지스틱 피팅 (theta0 = 정제된 50% 지점, k = 실력 민감도)
    fit = fit_logistic(curve)

    # 운빨 레벨 플래그: 피팅 곡선 기준 ΔP = P(0.9) - P(0.15) < 0.25
    # 가드: θ0(50% 지점)가 측정 스킬 범위 [0,1] 안에 있을 때만 판정.
    # θ0 < 0 이면 그냥 쉬운 레벨, θ0 > 1 이면 그냥 불가능한 레벨이라
    # ΔP가 작아도 "운빨"이 아님 (실측에서 둘 다 오탐 확인됨).
    delta_p = None
    luck_suspect = False
    if fit["fit_ok"]:
        p_hi = _sigmoid(fit["k"] * (0.9 - fit["theta0"]))
        p_lo = _sigmoid(fit["k"] * (0.15 - fit["theta0"]))
        delta_p = round(p_hi - p_lo, 4)
        mid_point_in_range = 0.0 <= fit["theta0"] <= 1.0
        luck_suspect = mid_point_in_range and delta_p < 0.25

    return {
        "theta_star": round(theta_star, 4) if theta_star is not None else None,
        "difficulty_score": difficulty_score,  # = 1 - AUC (메인 지표)
        "auc": round(auc, 4),
        "theta0": fit["theta0"],
        "k": fit["k"],
        "delta_p": delta_p,
        "luck_suspect": luck_suspect,
        "classification": classify_theta_star(theta_star, max_clear),
        "max_clear_rate": round(max_clear, 4),
        "min_clear_rate": round(min_clear, 4),
        # 예측 유저 클리어율 (검증 주력 지표) — 캐주얼 실력분포 가중
        "predicted_clear_rate": round(population_clear_rate(curve), 4),
        "skill_curve": curve,
        "total_rollouts": total_rollouts,
        "config": {
            "skill_grid": grid,
            "rollouts_per_point": rollouts,
            "seed": seed,
        },
    }


def sweep_level_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    ProcessPoolExecutor용 top-level 워커 (피클 가능해야 하므로 모듈 레벨 함수).

    레벨 단위 병렬화: 각 프로세스가 레벨 하나를 통째로 처리한다.
    내부 조기 종료 시간 편차는 executor.map의 동적 분배가 흡수.
    """
    try:
        result = run_skill_sweep(
            args["level_json"],
            skill_grid=args.get("skill_grid"),
            rollouts_per_point=args.get("rollouts_per_point", DEFAULT_ROLLOUTS_PER_POINT),
            seed=args.get("seed", DEFAULT_BASE_SEED),
            max_moves=args.get("max_moves"),
        )
        result["level_number"] = args.get("level_number")
        result["error"] = None
        return result
    except Exception as exc:  # 워커 예외는 결과로 전달 (풀 전체 중단 방지)
        logger.exception("[mc_difficulty] sweep task failed (level %s)", args.get("level_number"))
        return {"level_number": args.get("level_number"), "error": str(exc)}
