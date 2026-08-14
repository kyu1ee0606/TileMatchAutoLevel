"""[야간 연구 배치] 난이도 판정 체계의 미결 쟁점을 한 번에 확정하는 장시간 잡.

왜 필요한가:
  난이도 판정을 RL 봇 시뮬(predicted_clear_rate)에 의존해 왔는데 그 값의 신뢰도가 불명이다.
  실측으로 드러난 것:
    - RL 전 구간 0.000 인 Lv710 을 A* 는 108노드로 해결 (PROVEN_SOLVABLE)
    - 55조합 격자에서 색 종류(V)가 난이도 분산의 89.9%, 기믹 강도는 3.0%
    - RL 스킬곡선이 64롤아웃에도 비단조(θ0.9=0.41 → θ1.0=0.00)
  이 잡은 봇에 의존하지 않는 A* 기반 지표(solve_level / measure_robustness)로
  같은 레벨들을 재서, RL 눈금을 검증·보정할 근거를 만든다.

4단계:
  1. verdict   — 배치 전수 A* 판정. "RL 0% 레벨이 진짜 클리어 불가인가"
  2. vsweep    — V 3~13 스윕의 실수 내성. "V 절벽이 봇과 무관하게 어디인가"
  3. corr      — RL 전 구간 표본의 실수 내성. "RL 눈금이 A* 기준과 얼마나 일치하나"
  4. deep      — 남은 시간 동안 RL 0% 레벨 정밀 측정

진행 상태와 결과는 파일에 계속 기록한다(브라우저를 닫아도 계속 진행 / 재접속 시 조회).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/study", tags=["study"])

_THIS = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.normpath(os.path.join(_THIS, "..", "..", "..", "data", "night_study.json"))

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


# ── 상태 파일 ────────────────────────────────────────────────────────────────
def _save(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def _load() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"status": "idle"}


class StartRequest(BaseModel):
    batch_id: str = Field(..., description="분석 대상 프로덕션 배치")
    hours: float = Field(default=13.0, ge=0.2, le=24.0, description="총 시간 예산(시간)")
    # 단계별 시간 배분 비율 — 합이 1이 아니어도 정규화한다
    verdict_share: float = Field(default=0.10, ge=0.0, le=1.0)
    vsweep_share: float = Field(default=0.25, ge=0.0, le=1.0)
    corr_share: float = Field(default=0.35, ge=0.0, le=1.0)
    # 나머지는 deep 단계
    vsweep_base_levels: List[int] = Field(default_factory=lambda: [710, 790, 1268],
                                          description="V 스윕 기준 레벨(모양 고정, 색만 바꿔 비교)")
    corr_samples: int = Field(default=60, ge=4, le=400)


def _levels_of(batch_id: str) -> List[Dict[str, Any]]:
    from .production_store import get_batch
    data = get_batch(batch_id)
    return list(data.get("levels") or [])


def _run(req: StartRequest) -> None:
    """워커 스레드 본체. 각 단계는 자기 시간 예산을 넘기면 중단하고 다음으로 넘어간다."""
    from ...core.solver import solve_level, measure_robustness

    t_start = time.monotonic()
    budget_total = req.hours * 3600.0
    shares = [req.verdict_share, req.vsweep_share, req.corr_share]
    shares.append(max(0.0, 1.0 - sum(shares)))
    ssum = sum(shares) or 1.0
    budgets = [budget_total * s / ssum for s in shares]

    st: Dict[str, Any] = {
        "status": "running",
        "batch_id": req.batch_id,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "hours": req.hours,
        "phase": "load",
        "progress": {"done": 0, "total": 0},
        "phases": {},
        "log": [],
    }

    def log(msg: str) -> None:
        st["log"] = (st.get("log") or [])[-200:] + [f"{time.strftime('%H:%M:%S')} {msg}"]
        _save(st)

    def out_of_time(phase_idx: int) -> bool:
        used = time.monotonic() - t_start
        limit = sum(budgets[: phase_idx + 1])
        return used >= limit

    try:
        levels = _levels_of(req.batch_id)
        by_ln = {int(l["meta"]["level_number"]): l for l in levels}
        log(f"배치 로드: {len(levels)}개 레벨")

        # ── 1단계: 전수 A* 판정 ────────────────────────────────────────────
        st["phase"] = "verdict"
        _save(st)
        verdicts: Dict[str, Any] = {}
        order = sorted(by_ln)
        st["progress"] = {"done": 0, "total": len(order)}
        for i, ln in enumerate(order, 1):
            if _stop.is_set() or out_of_time(0):
                log(f"verdict 중단 ({i-1}/{len(order)})")
                break
            try:
                r = solve_level(by_ln[ln]["level_json"], node_budget=200000, time_budget_s=8.0)
                verdicts[str(ln)] = {
                    "verdict": r["verdict"], "nodes": r["nodes_expanded"],
                    "rl": by_ln[ln]["meta"].get("predicted_clear_rate"),
                    "cls": by_ln[ln]["meta"].get("rl_classification"),
                }
            except Exception as exc:  # noqa: BLE001
                verdicts[str(ln)] = {"verdict": "ERROR", "reason": str(exc)[:120]}
            st["progress"] = {"done": i, "total": len(order)}
            if i % 25 == 0:
                _save(st)
        agg: Dict[str, int] = {}
        for v in verdicts.values():
            agg[v["verdict"]] = agg.get(v["verdict"], 0) + 1
        # RL 0% 인데 A* 는 풀 수 있다고 한 레벨 — 이 잡의 핵심 질문
        rl0_solvable = [int(k) for k, v in verdicts.items()
                        if v.get("verdict") == "PROVEN_SOLVABLE" and (v.get("rl") or 0) == 0]
        st["phases"]["verdict"] = {"summary": agg, "measured": len(verdicts),
                                   "rl0_but_solvable": len(rl0_solvable),
                                   "rl0_but_solvable_levels": sorted(rl0_solvable)[:100],
                                   "detail": verdicts}
        log(f"1단계 완료: {agg} · RL0인데 solvable {len(rl0_solvable)}개")

        # ── 2단계: V 스윕 실수 내성 ────────────────────────────────────────
        st["phase"] = "vsweep"
        _save(st)
        from .tune import tune_tilecount, TileCountTuneRequest
        vs: List[Dict[str, Any]] = []
        combos = [(b, v) for b in req.vsweep_base_levels for v in range(3, 14)]
        st["progress"] = {"done": 0, "total": len(combos)}
        for i, (base_ln, v) in enumerate(combos, 1):
            if _stop.is_set() or out_of_time(1):
                log(f"vsweep 중단 ({i-1}/{len(combos)})")
                break
            src = by_ln.get(base_ln)
            if src is None:
                continue
            try:
                # 기믹은 그대로 두고 색 종류만 바꾼다(±2 제한 해제 — 전 구간을 훑는 게 목적).
                tuned = tune_tilecount(TileCountTuneRequest(
                    level_json=json.loads(json.dumps(src["level_json"])),
                    tile_count=v, evaluate=False, enforce_limit=False)).best_level_json
                r = measure_robustness(tuned, max_depth=10, move_cap=5,
                                       node_budget=60000, time_budget_s=5.0)
                vs.append({"base": base_ln, "V": v,
                           "safe_move_ratio": r.get("safe_move_ratio"),
                           "min_safe_ratio": r.get("min_safe_ratio"),
                           "points": r.get("points_measured"),
                           "uncertain": r.get("uncertain_evals"),
                           "elapsed_ms": r.get("elapsed_ms")})
            except Exception as exc:  # noqa: BLE001
                vs.append({"base": base_ln, "V": v, "error": str(exc)[:120]})
            st["progress"] = {"done": i, "total": len(combos)}
            st["phases"]["vsweep"] = {"rows": vs}
            _save(st)
        log(f"2단계 완료: {len(vs)}조합")

        # ── 3단계: RL 전 구간 표본 상관 ────────────────────────────────────
        st["phase"] = "corr"
        _save(st)
        # RL 예측 클리어율을 10구간으로 나눠 고르게 뽑는다(한쪽에 몰리면 상관계수가 왜곡).
        buckets: Dict[int, List[int]] = {}
        for ln, l in by_ln.items():
            p = l["meta"].get("predicted_clear_rate")
            if not isinstance(p, (int, float)):
                continue
            buckets.setdefault(min(9, int(p * 10)), []).append(ln)
        per = max(1, req.corr_samples // max(1, len(buckets)))
        sample: List[int] = []
        for b in sorted(buckets):
            sample.extend(sorted(buckets[b])[:per])
        st["progress"] = {"done": 0, "total": len(sample)}
        rows: List[Dict[str, Any]] = []
        for i, ln in enumerate(sample, 1):
            if _stop.is_set() or out_of_time(2):
                log(f"corr 중단 ({i-1}/{len(sample)})")
                break
            l = by_ln[ln]
            try:
                r = measure_robustness(l["level_json"], max_depth=10, move_cap=5,
                                       node_budget=60000, time_budget_s=5.0)
                rows.append({"level": ln,
                             "rl": l["meta"].get("predicted_clear_rate"),
                             "cls": l["meta"].get("rl_classification"),
                             "V": r.get("use_tile_count"), "tiles": r.get("total_tiles"),
                             "safe_move_ratio": r.get("safe_move_ratio"),
                             "min_safe_ratio": r.get("min_safe_ratio"),
                             "points": r.get("points_measured"),
                             "uncertain": r.get("uncertain_evals")})
            except Exception as exc:  # noqa: BLE001
                rows.append({"level": ln, "error": str(exc)[:120]})
            st["progress"] = {"done": i, "total": len(sample)}
            st["phases"]["corr"] = {"rows": rows, "correlation": _spearman(rows)}
            _save(st)
        log(f"3단계 완료: {len(rows)}개 · 상관 {(_spearman(rows) or {}).get('rho')}")

        # ── 4단계: RL 0% 레벨 정밀 ─────────────────────────────────────────
        st["phase"] = "deep"
        _save(st)
        deep_targets = [ln for ln in sorted(by_ln)
                        if by_ln[ln]["meta"].get("rl_classification") == "unclearable_suspect"]
        st["progress"] = {"done": 0, "total": len(deep_targets)}
        deep: List[Dict[str, Any]] = []
        for i, ln in enumerate(deep_targets, 1):
            if _stop.is_set() or out_of_time(3):
                log(f"deep 중단 ({i-1}/{len(deep_targets)})")
                break
            try:
                r = measure_robustness(by_ln[ln]["level_json"], max_depth=8, move_cap=4,
                                       node_budget=60000, time_budget_s=5.0)
                deep.append({"level": ln, "V": r.get("use_tile_count"),
                             "safe_move_ratio": r.get("safe_move_ratio"),
                             "min_safe_ratio": r.get("min_safe_ratio"),
                             "points": r.get("points_measured")})
            except Exception as exc:  # noqa: BLE001
                deep.append({"level": ln, "error": str(exc)[:120]})
            st["progress"] = {"done": i, "total": len(deep_targets)}
            st["phases"]["deep"] = {"rows": deep}
            if i % 5 == 0:
                _save(st)
        log(f"4단계 완료: {len(deep)}개")

        st["status"] = "stopped" if _stop.is_set() else "done"
        st["phase"] = "finished"
        st["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        st["elapsed_s"] = int(time.monotonic() - t_start)
        _save(st)
    except Exception as exc:  # noqa: BLE001
        st["status"] = "error"
        st["error"] = str(exc)[:400]
        _save(st)


def _spearman(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """RL 예측 vs 실수 내성의 순위상관. 두 눈금이 같은 순서를 매기는지 본다."""
    pts = [(r["rl"], r["safe_move_ratio"]) for r in rows
           if isinstance(r.get("rl"), (int, float)) and isinstance(r.get("safe_move_ratio"), (int, float))]
    n = len(pts)
    if n < 4:
        return None

    def ranks(xs: List[float]) -> List[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk

    ra, rb = ranks([p[0] for p in pts]), ranks([p[1] for p in pts])
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = sum((ra[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((rb[i] - mb) ** 2 for i in range(n)) ** 0.5
    if da == 0 or db == 0:
        return {"rho": None, "n": n}
    return {"rho": round(num / (da * db), 4), "n": n}


@router.post("/night/start")
def start_night_study(req: StartRequest) -> Dict[str, Any]:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise HTTPException(status_code=409, detail="이미 실행 중입니다")
        _stop.clear()
        _thread = threading.Thread(target=_run, args=(req,), daemon=True, name="night-study")
        _thread.start()
    return {"ok": True, "started": True}


@router.post("/night/stop")
def stop_night_study() -> Dict[str, Any]:
    _stop.set()
    return {"ok": True, "stopping": True}


@router.get("/night")
def get_night_study(detail: bool = False) -> Dict[str, Any]:
    """진행 상태 + 결과. detail=false 면 대용량 detail 을 제외해 가볍게 돌려준다."""
    st = _load()
    st["alive"] = bool(_thread is not None and _thread.is_alive())
    if not detail:
        ph = st.get("phases") or {}
        if "verdict" in ph:
            ph["verdict"] = {k: v for k, v in ph["verdict"].items() if k != "detail"}
    return st
