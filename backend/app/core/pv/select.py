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


# ─────────────────────────────────────────────────────────────────────────────
# v2 (P1 re-measure, 06 §8): adaptive θ, independent-sample CI, bidirectional 5 seeds
# ─────────────────────────────────────────────────────────────────────────────
SCAN_THETAS = (0.0, 0.15, 0.29, 0.55, 0.65, 0.75, 0.85, 1.0)  # skips the bot skill trough [0.34, 0.50) (06 §7-1)
UNEVALUABLE_MAX = 0.10      # orig rate at θ=1.0 below this -> bot cannot evaluate the level
DELTA_MIN_V2 = 0.04         # easy/hard vs base: diff >= this AND independent CI lower bound > 0
GAP_MIN_V2 = 0.02           # e2 vs e1 (h2 vs h1): point-estimate order with at least this gap
Z_V2 = 2.4977               # Bonferroni over 4 comparisons vs base (two-sided 95%)


def choose_thetas(scan: Dict[str, float]) -> Dict[str, Any]:
    """scan: {θstr: orig success rate}. Pick 2 θ whose orig rate is closest to 0.5 (prefer 0.3–0.7)."""
    rates = {float(t): r for t, r in scan.items()}
    # max over all scanned θ (not θ=1.0 alone): the bot is non-monotone at θ=1.0 too — patience 0.8 hits the
    # `patience >= 0.8` early-return branch (bot_simulator.py:4137-4147) and skips look-ahead (06 §8).
    best = max(rates.values()) if rates else 0.0
    if best < UNEVALUABLE_MAX:
        return {"evaluable": False, "thetas": [], "reason": f"orig max rate over scan θ = {best:.3f} < {UNEVALUABLE_MAX}"}
    ranked = sorted(rates, key=lambda t: (abs(rates[t] - 0.5), t))
    pick = sorted(ranked[:2])
    in_band = [t for t in pick if 0.3 <= rates[t] <= 0.7]
    return {"evaluable": True, "thetas": pick, "inBand": len(in_band), "rates": {str(t): rates[t] for t in pick}}


def indep_diff(a: Dict[str, Any], b: Dict[str, Any], z: float = Z_V2) -> Dict[str, Any]:
    """W(a) - W(b) with an independent two-sample normal SE (no pairing; CRN gain was ~0, 06 §7-3)."""
    thetas = sorted(set(a["theta"]) & set(b["theta"]))
    var = 0.0
    diffs = {}
    for t in thetas:
        pa, na = a["theta"][t]["rate"], a["theta"][t]["n"]
        pb, nb = b["theta"][t]["rate"], b["theta"][t]["n"]
        diffs[t] = pa - pb
        var += pa * (1 - pa) / na + pb * (1 - pb) / nb
    T = len(thetas)
    diff = sum(diffs.values()) / T
    se = math.sqrt(var) / T
    return {"diff": diff, "se": se, "lo": diff - z * se, "hi": diff + z * se, "perTheta": diffs}


def base_pick(w1: Dict[str, float], w_orig: float, verified: Dict[str, bool]) -> Dict[str, Any]:
    vals = list(w1.values())
    q_lo, q_hi = quantile(vals, BAND[0]), quantile(vals, BAND[1])
    band = [s for s, w in w1.items() if q_lo <= w <= q_hi and verified.get(s)] or \
           [s for s, w in w1.items() if q_lo <= w <= q_hi]
    base = min(band, key=lambda s: (abs(w1[s] - w_orig), int(s)))
    pct = sum(1 for w in vals if w < w_orig) / len(vals)
    return {"base": base, "band": [q_lo, q_hi], "origPercentile": pct,
            "origExtreme": pct < 0.10 or pct > 0.90}


def staircase_shortlist(w1: Dict[str, float], base: str, verified: Dict[str, bool],
                        targets: Sequence[float] = (0.06, 0.12, 0.18, 0.26), exclude: Sequence[str] = ()) -> Dict[str, List[str]]:
    """Up to 4 easy and 4 hard candidates nearest to stepped Δ targets from base (stage-1 W)."""
    wb = w1[base]
    out = {}
    for side, sign in (("easy", 1), ("hard", -1)):
        pool = [s for s in w1 if s != base and s not in exclude and sign * (w1[s] - wb) > 0]
        if side == "hard":
            pool = [s for s in pool if verified.get(s)] or pool
        chosen: List[str] = []
        for tg in targets:
            rest = [s for s in pool if s not in chosen]
            if not rest:
                break
            chosen.append(min(rest, key=lambda s: (abs(sign * (w1[s] - wb) - tg), int(s))))
        out[side] = chosen
    return out


def bidirectional_select(base: str, cands: List[str], ev: Dict[str, Dict[str, Any]], verified: Dict[str, bool],
                         delta_min: float = DELTA_MIN_V2, gap_min: float = GAP_MIN_V2) -> Dict[str, Any]:
    """User rule (2026-10-02): base + 2 easy + 2 hard, distinct seeds, both directions required.

    near/far on each side: both significantly beyond base (Δ ≥ delta_min, CI lower > 0), solvability evidence,
    far beyond near by point estimate ≥ gap_min. Pick near = smallest valid |Δ|, far = largest valid |Δ|.
    """
    wb = ev[base]["W"]
    result: Dict[str, Any] = {"base": base, "sides": {}}
    ok_all = True
    for side, sign in (("easy", 1), ("hard", -1)):
        valid, log = [], []
        for s in cands:
            if s == base or s not in ev:
                continue
            d = indep_diff(ev[s], ev[base]) if sign > 0 else indep_diff(ev[base], ev[s])
            rec = {"seed": s, "delta": round(sign * d["diff"], 4), "lo": round(d["lo"], 4), "hi": round(d["hi"], 4)}
            if sign * (ev[s]["W"] - wb) <= 0:
                continue
            if not verified.get(s):
                rec["reject"] = "unverified"
            elif d["diff"] < delta_min:
                rec["reject"] = f"delta<{delta_min}"
            elif d["lo"] <= 0:
                rec["reject"] = "ci_includes_0"
            else:
                valid.append((d["diff"], s))
            log.append(rec)
        valid.sort()
        pick = None
        if len(valid) >= 2 and valid[-1][0] - valid[0][0] >= gap_min:
            pick = (valid[0][1], valid[-1][1])
        reason = None
        if pick is None:
            ok_all = False
            reason = "no_valid" if not valid else ("one_valid" if len(valid) == 1 else f"gap<{gap_min}")
        result["sides"][side] = {"pick": pick, "nValid": len(valid), "reason": reason, "log": log}
    result["ok"] = ok_all
    if ok_all:
        e1, e2 = result["sides"]["easy"]["pick"]
        h1, h2 = result["sides"]["hard"]["pick"]
        result["seeds"] = [("e2", e2), ("e1", e1), ("b", base), ("h1", h1), ("h2", h2)]
    return result
