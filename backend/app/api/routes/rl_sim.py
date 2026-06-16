"""
RL 시뮬레이션 (몬테카를로 스킬 스윕) API.

기존 /api/analyze/autoplay (난이도별 봇 시뮬레이션)와 독립적인 엔드포인트.
- POST /api/rl-sim/level : 단일 레벨 스윕
- POST /api/rl-sim/batch : 레벨 묶음을 ProcessPool로 병렬 스윕 (레벨 단위 분배)
프론트엔드 RL 시뮬레이션 탭이 청크 단위로 호출하며, 전체 진행/취소는
프론트가 청크 루프를 돌면서 제어한다.
"""
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.mc_difficulty import (
    DEFAULT_ROLLOUTS_PER_POINT,
    DEFAULT_SKILL_GRID,
    DEFAULT_BASE_SEED,
    assemble_sweep_result,
    normalize_skill_grid,
    sweep_point_task,
)
from ...core.mc_search import (
    ACCEPT_TOLERANCE,
    DEFAULT_CANDIDATES,
    DEFAULT_FINALISTS,
    SCREEN_ROLLOUTS,
    SCREEN_SKILL_GRID,
    final_score,
    generate_candidates,
    screen_distance,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rl-sim", tags=["rl-sim"])

# 레벨 단위 병렬화용 프로세스 풀 (lazy 초기화)
_pool: Optional[ProcessPoolExecutor] = None
MAX_WORKERS = max(2, min(10, (os.cpu_count() or 4) - 2))
MAX_BATCH_SIZE = 32


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)
        logger.info("[rl-sim] process pool started (workers=%d)", MAX_WORKERS)
    return _pool


def warmup_pool() -> None:
    """워커 프로세스를 미리 스폰해 첫 요청 지연 제거 (startup 훅에서 백그라운드 호출)."""
    try:
        pool = _get_pool()
        # 워커 수만큼 no-op을 흘려 스폰 + 모듈 임포트를 미리 완료
        list(pool.map(int, range(MAX_WORKERS)))
        logger.info("[rl-sim] process pool warmed up")
    except Exception:
        logger.exception("[rl-sim] pool warmup failed")


def shutdown_pool() -> None:
    """앱 종료 시 풀 정리 (main.py shutdown 훅에서 호출)."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False)
        _pool = None


def _parallel_point_sweep(
    items: List[tuple],  # [(key, level_json)]
    skill_grid: Optional[List[float]],
    rollouts: int,
    seed: int,
    max_moves: Optional[int] = None,
) -> Dict[Any, Dict[str, Any]]:
    """
    (레벨 × 스킬포인트) 단위로 프로세스 풀에 분배해 병렬 스윕.

    레벨 단위 분배보다 부하가 균등해서 단일 레벨도 코어 수만큼 빨라지고,
    배치에서는 느린 레벨 하나가 워커들을 놀게 하는 꼬리 지연이 사라진다.
    반환: key → 조립된 스윕 결과 (오류 시 {"error": ...}).
    """
    grid = normalize_skill_grid(skill_grid)
    tasks = []
    for key, level_json in items:
        for idx, theta in enumerate(grid):
            tasks.append({
                "key": key,
                "level_json": level_json,
                "theta": theta,
                "rollouts": rollouts,
                "seed": seed + idx * 1000,  # run_skill_sweep과 동일한 시드 매핑
                "max_moves": max_moves,
            })

    pool = _get_pool()
    raw_points = list(pool.map(sweep_point_task, tasks, chunksize=1))

    by_key: Dict[Any, List[Dict[str, Any]]] = {}
    for p in raw_points:
        by_key.setdefault(p.get("key"), []).append(p)

    results: Dict[Any, Dict[str, Any]] = {}
    for key, points in by_key.items():
        error_point = next((p for p in points if p.get("error")), None)
        if error_point:
            results[key] = {"error": error_point["error"]}
            continue
        for p in points:
            p.pop("key", None)
            p.pop("error", None)
        points.sort(key=lambda c: c["theta"])
        result = assemble_sweep_result(points, grid, rollouts, seed)
        result["error"] = None
        results[key] = result
    return results


class RLSimRequest(BaseModel):
    level_json: Dict[str, Any]
    skill_grid: Optional[List[float]] = Field(
        default=None, description="스윕할 스킬 포인트 목록 (0~1). 생략 시 기본 그리드"
    )
    rollouts_per_point: int = Field(
        default=DEFAULT_ROLLOUTS_PER_POINT, ge=4, le=500,
        description="스킬 포인트당 롤아웃 수"
    )
    seed: int = Field(default=DEFAULT_BASE_SEED, description="공통 난수 기준 시드")
    max_moves: Optional[int] = Field(default=None, description="이동 수 제한 (생략 시 레벨 값)")


class RLSimBatchItem(BaseModel):
    level_number: int
    level_json: Dict[str, Any]


class RLSimBatchRequest(BaseModel):
    levels: List[RLSimBatchItem] = Field(..., description=f"레벨 묶음 (최대 {MAX_BATCH_SIZE}개)")
    skill_grid: Optional[List[float]] = None
    rollouts_per_point: int = Field(default=DEFAULT_ROLLOUTS_PER_POINT, ge=4, le=500)
    seed: int = Field(default=DEFAULT_BASE_SEED)
    max_moves: Optional[int] = None


class SkillCurvePoint(BaseModel):
    theta: float
    clear_rate: float
    iterations: int
    ci_half_width: float
    avg_moves: float
    avg_tiles_cleared: float


class RLSimResult(BaseModel):
    theta_star: Optional[float]
    difficulty_score: Optional[float]  # = 1 - AUC (메인 연속 난이도 지표)
    auc: Optional[float] = None
    theta0: Optional[float] = None     # 로지스틱 중간점 (정제된 50% 지점)
    k: Optional[float] = None          # 로지스틱 기울기 (실력 민감도)
    delta_p: Optional[float] = None    # P(θ=0.9) - P(θ=0.15)
    luck_suspect: bool = False         # 운빨 레벨 의심 (ΔP < 0.25, 중간 난이도)
    classification: str
    max_clear_rate: float
    min_clear_rate: float
    skill_curve: List[SkillCurvePoint]
    total_rollouts: int
    elapsed_ms: int
    config: Dict[str, Any]


class RLSimBatchResultItem(RLSimResult):
    level_number: int
    error: Optional[str] = None


class RLSimBatchResponse(BaseModel):
    results: List[RLSimBatchResultItem]
    elapsed_ms: int
    workers: int


class RLSimConfigResponse(BaseModel):
    default_skill_grid: List[float]
    default_rollouts_per_point: int
    default_seed: int
    max_batch_size: int
    workers: int


_EMPTY_RESULT_FIELDS: Dict[str, Any] = {
    "theta_star": None,
    "difficulty_score": None,
    "auc": None,
    "theta0": None,
    "k": None,
    "delta_p": None,
    "luck_suspect": False,
    "classification": "unclearable_suspect",
    "max_clear_rate": 0.0,
    "min_clear_rate": 0.0,
    "skill_curve": [],
    "total_rollouts": 0,
    "elapsed_ms": 0,
    "config": {},
}


@router.get("/config", response_model=RLSimConfigResponse)
def get_rl_sim_config() -> RLSimConfigResponse:
    """프론트 탭 초기값용 기본 설정."""
    return RLSimConfigResponse(
        default_skill_grid=DEFAULT_SKILL_GRID,
        default_rollouts_per_point=DEFAULT_ROLLOUTS_PER_POINT,
        default_seed=DEFAULT_BASE_SEED,
        max_batch_size=MAX_BATCH_SIZE,
        workers=MAX_WORKERS,
    )


@router.post("/level", response_model=RLSimResult)
def simulate_level_skill_sweep(request: RLSimRequest) -> RLSimResult:
    """단일 레벨에 대해 스킬 스윕 몬테카를로 시뮬레이션 실행."""
    if not request.level_json or not request.level_json.get("layer"):
        raise HTTPException(status_code=400, detail="유효한 level_json이 필요합니다")

    started = time.monotonic()
    try:
        # 스킬 포인트 단위 병렬 — 단일 레벨도 코어 수만큼 빨라짐
        result = _parallel_point_sweep(
            [(0, request.level_json)],
            request.skill_grid,
            request.rollouts_per_point,
            request.seed,
            request.max_moves,
        )[0]
        if result.get("error"):
            raise RuntimeError(result["error"])
        result.pop("error", None)
    except Exception as exc:
        logger.exception("[rl-sim] skill sweep failed")
        raise HTTPException(status_code=500, detail=f"시뮬레이션 실패: {exc}") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return RLSimResult(elapsed_ms=elapsed_ms, **result)


class RLSearchRequest(BaseModel):
    level_number: int = Field(..., description="레벨 번호 (기믹 해금/타일 수 산정에 사용)")
    target_theta0: float = Field(..., ge=0.0, le=1.0, description="목표 θ0 (클리어율 50% 스킬 지점)")
    target_k: float = Field(default=4.0, ge=0.5, le=20.0, description="목표 k (실력 민감도)")
    target_difficulty_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="목표 1-AUC (옵션, 지정 시 score에 가산)"
    )
    candidates: int = Field(default=DEFAULT_CANDIDATES, ge=2, le=64, description="생성할 후보 수")
    finalists: int = Field(default=DEFAULT_FINALISTS, ge=1, le=16, description="풀 측정할 상위 후보 수")
    rollouts_per_point: int = Field(default=DEFAULT_ROLLOUTS_PER_POINT, ge=4, le=500)
    seed: int = Field(default=DEFAULT_BASE_SEED)


class RLSearchCandidate(BaseModel):
    index: int
    gen_params: Dict[str, Any]
    static_ok: bool
    reject_reason: Optional[str] = None
    screen_distance: Optional[float] = None
    finalist: bool = False
    score: Optional[float] = None
    theta0: Optional[float] = None
    k: Optional[float] = None
    difficulty_score: Optional[float] = None
    classification: Optional[str] = None


class RLSearchResponse(BaseModel):
    accepted: bool          # score가 허용오차(ACCEPT_TOLERANCE) 이내인지
    tolerance: float
    best: Optional[Dict[str, Any]]  # {level_json, gen_params, score, measurement}
    candidates: List[RLSearchCandidate]
    elapsed_ms: int
    config: Dict[str, Any]


@router.post("/search", response_model=RLSearchResponse)
def search_curve_target(request: RLSearchRequest) -> RLSearchResponse:
    """
    0단계 MC 탐색 루프: 목표 곡선 (θ0, k)에 맞는 레벨을 generate-and-test로 탐색.

    멀티 피델리티: 스크리닝(3지점×8롤아웃, 병렬) → 상위 finalists만 풀 측정(병렬).
    """
    started = time.monotonic()

    # 1) 후보 생성 + 정적 체크
    cands = generate_candidates(
        level_number=request.level_number,
        target_theta0=request.target_theta0,
        target_k=request.target_k,
        count=request.candidates,
        seed=request.seed,
    )
    valid = [c for c in cands if c["static_ok"]]

    # 2) 스크리닝 (저예산 스윕, 포인트 단위 병렬)
    if valid:
        screen_results = _parallel_point_sweep(
            [(c["index"], c["level_json"]) for c in valid],
            SCREEN_SKILL_GRID,
            SCREEN_ROLLOUTS,
            request.seed,
        )
        for c in valid:
            r = screen_results.get(c["index"], {"error": "결과 누락"})
            if r.get("error"):
                c["reject_reason"] = f"screen_error: {r['error']}"
                c["screen_distance"] = None
            else:
                c["screen_distance"] = screen_distance(
                    r.get("skill_curve", []), request.target_theta0, request.target_k
                )
                if c["screen_distance"] is None:
                    c["reject_reason"] = "screen_unclearable"

    survivors = sorted(
        [c for c in valid if c.get("screen_distance") is not None],
        key=lambda c: c["screen_distance"],
    )[: request.finalists]

    # 3) 풀 측정 (포인트 단위 병렬)
    best: Optional[Dict[str, Any]] = None
    if survivors:
        full_results = _parallel_point_sweep(
            [(c["index"], c["level_json"]) for c in survivors],
            None,  # 기본 그리드
            request.rollouts_per_point,
            request.seed,
        )
        for c in survivors:
            c["finalist"] = True
            r = full_results.get(c["index"], {"error": "결과 누락"})
            if r.get("error"):
                c["reject_reason"] = f"full_error: {r['error']}"
                continue
            r.pop("error", None)
            c["measurement"] = r
            c["score"] = final_score(
                r, request.target_theta0, request.target_k, request.target_difficulty_score
            )
            if c["score"] is None:
                c["reject_reason"] = "full_unclearable_or_unfit"

        scored = [c for c in survivors if c.get("score") is not None]
        if scored:
            top = min(scored, key=lambda c: c["score"])
            m = top["measurement"]
            best = {
                "candidate_index": top["index"],
                "score": top["score"],
                "gen_params": top["gen_params"],
                "level_json": top["level_json"],
                "measurement": {
                    k: v for k, v in m.items() if k not in ("level_number", "error")
                },
            }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    candidate_rows = [
        RLSearchCandidate(
            index=c["index"],
            gen_params=c["gen_params"],
            static_ok=c["static_ok"],
            reject_reason=c.get("reject_reason"),
            screen_distance=c.get("screen_distance"),
            finalist=c.get("finalist", False),
            score=c.get("score"),
            theta0=(c.get("measurement") or {}).get("theta0"),
            k=(c.get("measurement") or {}).get("k"),
            difficulty_score=(c.get("measurement") or {}).get("difficulty_score"),
            classification=(c.get("measurement") or {}).get("classification"),
        )
        for c in cands
    ]

    return RLSearchResponse(
        accepted=best is not None and best["score"] <= ACCEPT_TOLERANCE,
        tolerance=ACCEPT_TOLERANCE,
        best=best,
        candidates=candidate_rows,
        elapsed_ms=elapsed_ms,
        config={
            "target_theta0": request.target_theta0,
            "target_k": request.target_k,
            "target_difficulty_score": request.target_difficulty_score,
            "candidates": request.candidates,
            "finalists": request.finalists,
            "screen_skill_grid": SCREEN_SKILL_GRID,
            "screen_rollouts": SCREEN_ROLLOUTS,
            "rollouts_per_point": request.rollouts_per_point,
            "seed": request.seed,
        },
    )


@router.post("/batch", response_model=RLSimBatchResponse)
def simulate_batch_skill_sweep(request: RLSimBatchRequest) -> RLSimBatchResponse:
    """레벨 묶음을 레벨 단위로 프로세스 풀에 분배해 병렬 스윕."""
    if not request.levels:
        raise HTTPException(status_code=400, detail="levels가 비어 있습니다")
    if len(request.levels) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"한 번에 최대 {MAX_BATCH_SIZE}개까지 처리 가능합니다 (요청: {len(request.levels)}개)",
        )

    started = time.monotonic()
    # (레벨 × 스킬포인트) 단위 병렬 — 느린 레벨 하나가 꼬리 지연을 만들지 않음
    sweep_results = _parallel_point_sweep(
        [(item.level_number, item.level_json) for item in request.levels],
        request.skill_grid,
        request.rollouts_per_point,
        request.seed,
        request.max_moves,
    )

    items: List[RLSimBatchResultItem] = []
    for item in request.levels:
        raw = sweep_results.get(item.level_number, {"error": "결과 누락"})
        if raw.get("error"):
            items.append(RLSimBatchResultItem(
                level_number=item.level_number,
                error=raw["error"],
                **_EMPTY_RESULT_FIELDS,
            ))
        else:
            raw.pop("error", None)
            items.append(RLSimBatchResultItem(
                level_number=item.level_number,
                error=None,
                elapsed_ms=0,  # 개별 시간은 병렬이라 의미 없음 — 전체 elapsed 참조
                **raw,
            ))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return RLSimBatchResponse(results=items, elapsed_ms=elapsed_ms, workers=MAX_WORKERS)
