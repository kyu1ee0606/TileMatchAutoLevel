"""E-P1-4: 5-seed selection (04 §A5 final rules).

Inputs are `evaluate_maps` outputs (per-game win lists per θ). All comparisons in the final tiering use
stage-2 data only (independent bot streams from stage 1 → no winner's-curse reuse, 04 §B S1).
W = bot-weighted success rate (relative metric, never a human clear rate).
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

DELTA_MIN = 0.05          # 04 §A5-3 initial value (re-set after P1 from σ_meas)
Z_BONF = 2.4977           # two-sided α = 0.05 / 4 adjacent comparisons
H_FLOOR_THETA = "0.65"    # highest skill point
H_FLOOR = 0.10            # hard seeds: success at highest θ must be ≥ this (fairness floor)
BAND = (0.25, 0.75)       # base must come from this W1 quantile band


def quantile(values: Sequence[float], q: float) -> float:
    xs = sorted(values)
    if not xs:
        return float("nan")
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def paired_diff(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """W(a) - W(b) with a paired (same game index = same bot stream) normal-approx SE."""
    per_t = {}
    var_sum = 0.0
    thetas = sorted(set(a["theta"]) & set(b["theta"]))
    for t in thetas:
        wa, wb = a["theta"][t]["wins"], b["theta"][t]["wins"]
        n = min(len(wa), len(wb))
        d = [wa[i] - wb[i] for i in range(n)]
        m = sum(d) / n
        v = sum((x - m) ** 2 for x in d) / (n - 1) if n > 1 else 0.0
        per_t[t] = m
        var_sum += v / n
    T = len(thetas)
    diff = sum(per_t.values()) / T
    se = math.sqrt(var_sum) / T
    return {"diff": diff, "se": se, "perTheta": per_t}


def crn_corr(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[float]:
    xs, ys = [], []
    for t in set(a["theta"]) & set(b["theta"]):
        wa, wb = a["theta"][t]["wins"], b["theta"][t]["wins"]
        n = min(len(wa), len(wb))
        xs += wa[:n]
        ys += wb[:n]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def distinguishable(easier: Dict[str, Any], harder: Dict[str, Any], delta: float = DELTA_MIN) -> Dict[str, Any]:
    pd = paired_diff(easier, harder)
    crossing = any((d < 0 and abs(d) >= delta) for d in pd["perTheta"].values())
    ok = pd["diff"] >= delta and (pd["diff"] - Z_BONF * pd["se"]) > 0 and not crossing
    return {**pd, "ok": ok, "crossing": crossing, "lo": pd["diff"] - Z_BONF * pd["se"]}


def any_win(*evals: Optional[Dict[str, Any]]) -> bool:
    for e in evals:
        if e and any(sum(v["wins"]) > 0 for v in e["theta"].values()):
            return True
    return False


def shortlist(stage1: Dict[str, Dict[str, Any]], w_orig: float) -> Dict[str, Any]:
    """stage1: {seedStr: eval}. Returns base + easy/hard candidates (≤4 each)."""
    w1 = {s: e["W"] for s, e in stage1.items()}
    q_lo, q_hi = quantile(list(w1.values()), BAND[0]), quantile(list(w1.values()), BAND[1])
    band = [s for s, w in w1.items() if q_lo <= w <= q_hi and any_win(stage1[s])]
    if not band:
        band = [s for s, w in w1.items() if q_lo <= w <= q_hi]
    base = min(band, key=lambda s: (abs(w1[s] - w_orig), int(s)))
    wb = w1[base]

    def pick(pool: List[str], extreme_last: bool) -> List[str]:
        # pool sorted from base outward; avoid the single most extreme as a primary pick
        if not pool:
            return []
        far = pool[-1]
        mid_target = (wb + w1[far]) / 2
        chosen: List[str] = []
        prim1 = min(pool, key=lambda s: (abs(w1[s] - mid_target), int(s)))
        chosen.append(prim1)
        prim2 = pool[-2] if len(pool) >= 2 else pool[-1]
        if prim2 not in chosen:
            chosen.append(prim2)
        alts = sorted((s for s in pool if s not in chosen), key=lambda s: (abs(w1[s] - mid_target), int(s)))
        for s in alts[:1] + ([pool[-3]] if len(pool) >= 3 and pool[-3] not in chosen else []) + alts[1:]:
            if len(chosen) >= 4:
                break
            if s not in chosen:
                chosen.append(s)
        return chosen

    easy_pool = sorted((s for s in w1 if w1[s] > wb), key=lambda s: (w1[s], int(s)))
    hard_pool = sorted((s for s in w1 if w1[s] < wb), key=lambda s: (-w1[s], int(s)))
    return {
        "base": base, "band": [q_lo, q_hi],
        "easy": pick(easy_pool, True), "hard": pick(hard_pool, True),
        "w1": w1,
    }


def _side(base: str, cands: List[str], ev: Dict[str, Dict[str, Any]], verified: Dict[str, bool],
          easy: bool, delta: float) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """Return (picked [near, far], collapsed tiers, comparison log)."""
    log: List[Dict[str, Any]] = []
    wb = ev[base]["W"]
    ok_c = []
    for s in cands:
        if not verified.get(s):
            log.append({"seed": s, "reject": "unverified"})
            continue
        if not easy and ev[s]["theta"][H_FLOOR_THETA]["rate"] < H_FLOOR:
            log.append({"seed": s, "reject": f"h_floor θ{H_FLOOR_THETA} < {H_FLOOR}"})
            continue
        if (ev[s]["W"] > wb) != easy:
            log.append({"seed": s, "reject": "wrong side in stage2"})
            continue
        ok_c.append(s)

    def dist(x: str, y: str) -> Dict[str, Any]:  # x farther from base than y
        return distinguishable(ev[x], ev[y], delta) if easy else distinguishable(ev[y], ev[x], delta)

    best = None
    for x, y in combinations(ok_c, 2):
        near, far = (x, y) if abs(ev[x]["W"] - wb) < abs(ev[y]["W"] - wb) else (y, x)
        d1, d2 = dist(near, base), dist(far, near)
        log.append({"pair": [near, far], "d1": round(d1["diff"], 4), "lo1": round(d1["lo"], 4), "ok1": d1["ok"],
                    "d2": round(d2["diff"], 4), "lo2": round(d2["lo"], 4), "ok2": d2["ok"]})
        if d1["ok"] and d2["ok"]:
            score = min(d1["diff"], d2["diff"])
            if best is None or score > best[0]:
                best = (score, near, far)
    if best:
        return [best[1], best[2]], [], log
    singles = []
    for s in ok_c:
        d = dist(s, base)
        log.append({"single": s, "d": round(d["diff"], 4), "lo": round(d["lo"], 4), "ok": d["ok"]})
        if d["ok"]:
            singles.append((d["diff"], s))
    if singles:
        s = max(singles)[1]
        return [s, s], ["far"], log
    return [base, base], ["near", "far"], log


def final_select(base: str, easy_c: List[str], hard_c: List[str], stage2: Dict[str, Dict[str, Any]],
                 verified: Dict[str, bool], delta: float = DELTA_MIN) -> Dict[str, Any]:
    (e1, e2), e_col, e_log = _side(base, easy_c, stage2, verified, True, delta)
    (h1, h2), h_col, h_log = _side(base, hard_c, stage2, verified, False, delta)
    collapsed = [("e1" if c == "near" else "e2") for c in e_col] + [("h1" if c == "near" else "h2") for c in h_col]
    status = "flat" if len(collapsed) == 4 else ("collapsed" if collapsed else "ok")
    seeds = [("e2", e2), ("e1", e1), ("b", base), ("h1", h1), ("h2", h2)]
    return {"status": status, "collapsed": sorted(collapsed), "seeds": seeds, "log": {"easy": e_log, "hard": h_log}}
