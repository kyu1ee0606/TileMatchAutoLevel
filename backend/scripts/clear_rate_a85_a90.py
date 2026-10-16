"""A85 feasibility analysis + A90 search (doc 33 §15). Sandbox only; the model, reliability rules and verdict are
used as they are.

  a85        no bot runs: the PASS rule for target 0.85 written as conditions, every training map (own placement,
             training measurement tagged as a confirmation run) and every saved pilot-1/2 candidate classified
             (① prediction not near the band / ② confidence gate / ③ range shape / ④ combined), the logical region
             where PASS is possible, and a placement diagnostic (training maps evaluated at L157 — diagnostic only)
  a90-analyze  no bot runs: generator variables vs structure / prediction on saved candidates + training maps
  run        A90 search (pre-registered PLAN, doc 33 §15-0)
  summary
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import math
import resource
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
import clear_rate_gen_pilot as P1  # noqa: E402
import clear_rate_gen_pilot2 as P2  # noqa: E402

CAL = P1.CAL
OUT = P1.DATA / "pv_sandbox/gen_pilot/20261016_p3"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.0f}s]", *a, flush=True)


def lgt(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


# ── A85 ───────────────────────────────────────────────────────────────────────────────────────────────────────
def classify(p, v, band):
    """① location: prediction outside the target band; ② gate: no number / hard target flag / confidence low;
    ③ shape: prediction inside the band but P(in band) < 0.5. Combined (④) when ② and ① or ③."""
    gate = (not p.in_support) or p.expected_ft_any is None or p.confidence == "low" or \
        any(f["severity"] == "hard" for f in v.target_flags if f["code"] != "SELECTION_UNCONFIRMED")
    if p.expected_ft_any is None:
        return "②", gate, None, None
    inside = band[0] <= p.expected_ft_any <= band[1]
    loc = not inside
    shape = inside and (v.p_in_band or 0) < 0.5
    if v.verdict == "PASS":
        return "PASS", gate, loc, shape
    if gate and (loc or shape):
        return "④", gate, loc, shape
    if gate:
        return "②", gate, loc, shape
    if loc:
        return "①", gate, loc, shape
    return "③", gate, loc, shape


def low_reasons(p):
    return sorted({f["code"] for f in p.evidence_flags if f["code"] in (
        "PRED_ZONE_HIGH_ERROR", "SIMILAR_MAPS_FEW", "COMBO_HIGH_ERROR", "NOVELTY_HIGH", "GIMMICK_FIRST",
        "LOW_CONFIDENCE")} | set(p.insufficient_reasons))


def spreads(pred, rng):
    """select.p_in_band's two-piece-normal spreads (logit) and lower-side weight w."""
    Z90 = 1.2815515655446004
    mu, (lo, hi) = lgt(pred), rng
    s_lo = (mu - lgt(lo)) / Z90 if 0 < lo < pred else None
    s_hi = (lgt(hi) - mu) / Z90 if pred < hi < 1 else None
    s_lo = s_lo or s_hi or 1e-6
    s_hi = s_hi or s_lo
    return s_lo, s_hi, s_lo / (s_lo + s_hi)


def eval_set(mdl, items, target):
    from app.core.clear_rate.predict import predict_level
    from app.core.clear_rate.select import target_band, verdict
    band = target_band(target)
    out = []
    for it in items:
        p = predict_level(mdl, it["map"], it["cond"], it["L"], it["meas"], random_layout=it["rl"])
        v = verdict(p, target, mdl.model["support"], confirm_bands=(it["meas"].seed_band,))
        cls, gate, loc, shape = classify(p, v, band)
        row = {"src": it["src"], "L": it["L"], "pred": p.expected_ft_any,
               "range80": list(p.range80_ft_any) if p.range80_ft_any else None, "confidence": p.confidence,
               "in_support": p.in_support, "p_in_band": v.p_in_band, "verdict": v.verdict, "class": cls,
               "gate_reasons": low_reasons(p) if gate else [], "target_hard": [f["code"] for f in v.target_flags
                                                                               if f["severity"] == "hard"]}
        if p.expected_ft_any is not None:
            row["s_lo"], row["s_hi"], row["w"] = [round(x, 4) for x in spreads(p.expected_ft_any, p.range80_ft_any)]
        out.append(row)
    return out


def training_items(mdl, placement=None):
    from app.core.clear_rate import cond_hash
    from app.core.clear_rate.conditions import normalize_conditions
    from app.core.clear_rate.predict import BotMeasurement
    prep = {int(k): v for k, v in P1.load(CAL / "bot_v21/prep.json").items()}
    items = []
    for L in mdl.model["support"]["train_levels"]:
        p = prep[L]
        cond = normalize_conditions(p["row"])
        hit = dict(mdl.bot_cache[cond_hash(p["map"], cond)])
        hit["seed_band"] = "C"          # treated as a confirmation run: the seed requirement is not what is tested
        items.append({"src": f"train L{L}", "L": placement or L, "map": p["map"], "cond": cond,
                      "meas": BotMeasurement.from_dict(hit), "rl": p["mode"] == "random"})
    return items


def candidate_items(mdl):
    """Saved pilot-1 / pilot-2 A candidates with full theta4x128 measurements (their own placement)."""
    from app.core.clear_rate import finalize_game_conditions
    from app.core.clear_rate.measure import MeasurementStore
    from app.core.clear_rate.service import random_layout
    items = []
    s1 = MeasurementStore(P1.OUT / "measurements.json")
    for spec in P1.PLAN["levels"]:
        r = P1.load(P1.OUT / spec["id"] / "result.json")
        for c in r["candidates"]:
            if not c.get("cond_hash"):
                continue
            lj = P1.load(P1.OUT / spec["id"] / f"cand{c['index']:02d}.json")["level_json"]
            gm, cond = finalize_game_conditions(lj, spec["placement"])
            m = s1.get(c["cond_hash"], "theta4x128_v1", "S", c["bot_config_hash"])[0]
            items.append({"src": f"p1 {spec['id']}#{c['index']}", "L": spec["placement"], "map": gm, "cond": cond,
                          "meas": m, "rl": random_layout(gm)})
    s2 = MeasurementStore(P2.OUT / "measurements.json")
    for spec in P2.PLAN["levels"]:
        if spec["mode"] != "user_expected":
            continue
        r = P1.load(P2.OUT / spec["id"] / "result.json")
        for x in r["records"]:
            if "A_search" not in (x.get("measurements") or {}):
                continue
            lj = P1.load(P2.OUT / spec["id"] / f"gen{x['gen_index']:03d}.json")["level_json"]
            gm, cond = finalize_game_conditions(lj, spec["placement"])
            m = s2.get(x["cond_hash"], "theta4x128_v1", "S2", x["bot_config_hash"])[0]
            items.append({"src": f"p2 {spec['id']}#{x['gen_index']}", "L": spec["placement"], "map": gm,
                          "cond": cond, "meas": m, "rl": x["random_layout"]})
    return items


def cmd_a85(a):
    from app.core.clear_rate import load_model
    from app.core.clear_rate.select import target_band
    mdl = load_model()
    sup = mdl.model["support"]
    band = target_band(0.85)
    zones = sup["reliability"]["pred_bins"]
    from app.core.clear_rate import guard
    zone_low = [(z["lo"], z["hi"]) for z in zones
                if z["mae"] >= guard.ZONE_LOW["mae_ge"] or z["coverage80"] < guard.ZONE_LOW["coverage80_lt"]]
    min_ok_pred = max(hi for _, hi in zone_low)
    # PASS needs P(in band) ≥ 0.5 with pred ≥ min_ok_pred > band upper → the mass below the prediction must exceed
    # 0.5: w = s_lo/(s_lo+s_hi) > 0.5 (lower spread wider than upper) and the upper bound of the 80% range < 1
    # (a bound at 1 is censored: the upper spread is then copied from the lower side, w = 0.5 exactly).
    mu0, u, l = lgt(min_ok_pred), lgt(band[1]), lgt(band[0])
    from statistics import NormalDist
    N = NormalDist()

    def p_best(pred, s_lo, w):
        mu = lgt(pred)
        return 2 * w * (N.cdf((u - mu) / s_lo) - N.cdf((l - mu) / s_lo))
    tr = eval_set(mdl, training_items(mdl), 0.85)
    cand = eval_set(mdl, candidate_items(mdl), 0.85)
    diag = eval_set(mdl, training_items(mdl, placement=157), 0.85)

    def tab(rows):
        c = Counter(r["class"] for r in rows)
        g = Counter(x for r in rows if r["class"] in ("②", "④") for x in r["gate_reasons"] or ["NO_NUMBER"])
        ok = [r for r in rows if r["pred"] is not None and r["class"] not in ("②", "④")]
        return {"n": len(rows), "classes": dict(c), "gate_reasons": dict(g),
                "gate_ok": len(ok), "gate_ok_pred_min": min((r["pred"] for r in ok), default=None),
                "gate_ok_hi_lt_1": sum(1 for r in ok if r["range80"][1] < 1.0),
                "gate_ok_w_gt_half": sum(1 for r in ok if r["w"] > 0.5),
                "gate_ok_p_in_band_max": max((r["p_in_band"] for r in ok), default=None),
                "pred_in_band": sum(1 for r in rows if r["pred"] is not None and band[0] <= r["pred"] <= band[1])}
    res = {
        "rule": {
            "target": 0.85, "band": [round(x, 4) for x in band],
            "pass_conditions": [
                "in_support (no SUPPRESS flag: placement/level/gimmick/condition/measurement/feature OOD)",
                "no hard target flag: 0.85 inside the segment's training p5–p95 (101-300 [0.790, 0.997], 301-500 "
                "[0.803, 0.996]; 32-100 [0.915, 0.996] → excluded)",
                "confidence ≠ low: pred zone MAE < 0.045 and coverage ≥ 0.75 → pred ≥ %.2f; same gimmick combination "
                "in training ≥ 5 with OOF MAE < 0.05; no NOVELTY_HIGH / GIMMICK_FIRST; target ≥ 0.85" % min_ok_pred,
                "measurement on the confirmation band (C)",
                "P(in band) ≥ 0.5 under the two-piece normal read of the 80% range",
            ],
            "zones_low_confidence": zone_low, "min_pred_not_low": min_ok_pred,
            "consequence": "band upper %.4f < %.2f: a prediction that passes the confidence gate is always above the "
                           "band, so P(in band) ≥ 0.5 needs w > 0.5 (lower spread wider than upper) with the 80%% "
                           "range's upper bound < 1" % (band[1], min_ok_pred),
            "required_w_at_pred_0.92": {f"s_lo={s}": round(0.5 / (2 * (N.cdf((u - mu0) / s) - N.cdf((l - mu0) / s))), 3)
                                        for s in (0.3, 0.5, 0.8, 1.2, 2.0)},
            "best_case_p_at_w1": {f"pred={pp}": round(max(p_best(pp, s, 1.0) for s in (0.3, 0.5, 0.8, 1.2, 2.0)), 3)
                                  for pp in (0.92, 0.925, 0.93, 0.94, 0.95)},
        },
        "training_own_placement": tab(tr), "candidates_saved": tab(cand),
        "diagnostic_training_at_L157": tab(diag),
        "by_segment": {seg: tab([r for r in tr if lo <= int(r["src"].split("L")[1]) <= hi])
                       for seg, lo, hi in (("32-100", 32, 100), ("101-300", 101, 300), ("301-500", 301, 500))},
        "rows": {"training": tr, "candidates": cand, "diag_L157": diag},
    }
    P1.save(OUT / "a85_analysis.json", res)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))


# ── A90 search ────────────────────────────────────────────────────────────────────────────────────────────────
PLAN = {
    "level": {"id": "A90", "mode": "user_expected", "placement": 213, "target": 0.90},
    "space": {   # real generator inputs (generate route core, unchanged defaults elsewhere)
        "pattern_index": list(range(64)),           # aesthetic pattern (dashboard picks from its pool; here explicit)
        "layers": [3, 4, 5],                        # min = max layers (training p99 5.22)
        "grid": [7, 8],
        "target_difficulty": [0.2, 0.35, 0.5],      # < 0.6: no forced chain+ice from _increase_difficulty
        "gimmick_intensity": [0.3, 0.6, 1.0, 1.5],  # experiment-only range (dashboard: min(td, L/500) = ≤ 0.426)
        "goal_type": ["stack", "craft"],
        "available": [["craft", "link"], ["craft", "stack"], ["craft", "stack", "link"]],
    },
    "explore": {"draws": 60, "measure_max": 14,
                "rule": "seeded uniform draws over the space; screen + dedup; measure in draw order but at most "
                        "3 per (layers, tiles tercile <51/51–75/>75, stack present) cell so different structures are "
                        "measured"},
    "exploit": {"measure_max": 22,
                "rule": "anchors = eligible measured candidates ordered by |logit pred − logit 0.90| (ties → order); "
                        "for each anchor in turn: same config with a new seed, then one variable changed at a time "
                        "(layers ±1, grid other, td next, intensity next, goal type other, pattern_index ±1); plus "
                        "one edge config per round (layers 5, grid 8, td 0.5, intensity 1.5, stack goals, random "
                        "pattern). No monotonic assumption."},
    "caps": {"generations": 220, "full_measurements": 36},
    "early_stop": "3 measured candidates eligible (in support, confidence ≠ low, no hard target flag) with S "
                  "P(in band) ≥ 0.5",
    "selection": "eligible ranked by S P(in band) desc → select.score asc → order; confirm only the top 1",
    "bands": {"search": ["theta4x128_v1", "S3"], "confirm": ["theta4x128_v1", "C3"]},
    "gen_seed_rule": "fresh process, PYTHONHASHSEED=0, seed 9,360,000 + gen_index",
    "verdict": "select.verdict unchanged (band logit ±0.7, P(in band) ≥ 0.5, confidence / support gates), "
               "confirm band C3",
    "budget": {"max_run_games": 19500, "total_cap_incl_tests": 33000},
}


def a90_request(L, cfg, seed):
    import random as _r
    req = P1.candidate_request(L, cfg["target_difficulty"], _r.Random(seed))   # symmetry / goal direction / grid rules
    req["goals"][0]["type"] = cfg["goal_type"]
    req.update(pattern_index=cfg["pattern_index"], min_layers=cfg["layers"], max_layers=cfg["layers"],
               grid_size=[cfg["grid"], cfg["grid"]], gimmick_intensity=cfg["gimmick_intensity"],
               available_gimmicks=list(cfg["available"]), size_diversity_start_level=101)
    return req


def neighbours(cfg):
    S = PLAN["space"]
    out = [dict(cfg)]

    def nxt(lst, v, step=1):
        i = lst.index(v)
        return lst[(i + step) % len(lst)]
    for k, vals in (("layers", S["layers"]), ("grid", S["grid"]), ("target_difficulty", S["target_difficulty"]),
                    ("gimmick_intensity", S["gimmick_intensity"]), ("goal_type", S["goal_type"])):
        out.append({**cfg, k: nxt(vals, cfg[k])})
    out.append({**cfg, "pattern_index": (cfg["pattern_index"] + 1) % 64})
    out.append({**cfg, "pattern_index": (cfg["pattern_index"] - 1) % 64})
    return out


def cmd_run(a):
    import random as _r
    from app.core.clear_rate import cond_hash, finalize_game_conditions, load_model
    from app.core.clear_rate import experiment as X
    from app.core.clear_rate.measure import MeasurementStore, bot_config, bot_exposure, config_hash, measure_cached
    from app.core.clear_rate.predict import predict_level
    from app.core.clear_rate.select import score, verdict
    from app.core.clear_rate.service import random_layout
    mdl = load_model()
    assert mdl.version == "cr-ftany-v24r-20261016"
    spec = PLAN["level"]
    L, t = spec["placement"], spec["target"]
    sup = mdl.model["support"]
    lvdir = OUT / spec["id"]
    if (lvdir / "result.json").exists():
        log("done already")
        return
    store = MeasurementStore(OUT / "measurements.json")
    bud = P1.Budget(OUT / "budget.json")
    P1.PLAN["budget"]["max_total_games"] = PLAN["budget"]["max_run_games"]
    expo = bot_exposure(mdl.model["position"], L)
    pre = X.user_expected_precheck(mdl, t, L)
    assert not pre, pre
    recs, seen_h, seen_s = [], set(), set()
    t0 = time.time()
    log("A90 run start, swap", P1.swap_used())

    def gen(cfg, phase):
        i = len(recs)
        seed = 9_360_000 + i
        req = a90_request(L, cfg, seed)
        g = P2.generate_isolated(req, seed)
        rec = {"gen_index": i, "phase": phase, "cfg": cfg, "gen_seed": seed, "request": req, "ok": g["ok"],
               "gen_sec": g["gen_sec"]}
        recs.append(rec)
        if not g["ok"]:
            rec["skip"] = "generation_failed"
            return rec
        gm, cond = finalize_game_conditions(g["level_json"], L)
        h, sh, rl = cond_hash(gm, cond), P2.structure_hash(gm), random_layout(gm)
        scr = X.structural_screen(mdl, gm, cond, L, random_layout=rl)
        rec.update(cond_hash=h, structure_hash=sh, conditions=cond, random_layout=rl, screen=scr,
                   bot_config_hash=config_hash(bot_config(expo, cond)),
                   playability_warning=g.get("playability_warning"))
        P1.save(lvdir / f"gen{i:03d}.json", {"level_json": g["level_json"], "placement": L, "conditions": cond,
                                            "cond_hash": h, "gen_seed": seed, "request": req, "cfg": cfg})
        if any(cond[k] for k in ("timea", "autoCollectCount")):
            rec["skip"] = "excluded"
        elif h in seen_h:
            rec["skip"] = "duplicate_cond_hash"
        elif sh in seen_s:
            rec["skip"] = "duplicate_structure"
        elif scr["blocking"]:
            rec["skip"] = "screen:" + ",".join(scr["blocking"])
        seen_h.add(h)
        seen_s.add(sh)
        rec["_gm"] = gm
        return rec

    def measure(rec, key):
        proto, band = PLAN["bands"][key]
        bud.check(512)
        m, meta, hit = measure_cached(store, rec["_gm"], rec["conditions"], exposure=expo, protocol=proto,
                                      seed_band=band, executor=ex)
        if not hit:
            bud.add(f"A90:{key}", meta)
        rec.setdefault("measurements", {})[key] = {"band": band, "rows": [
            {k: r[k] for k in ("theta", "games", "wins", "fail_reasons")} for r in m.rows]}
        rec["any_bot_win"] = rec.get("any_bot_win", False) or any(r["wins"] > 0 for r in m.rows)
        return m

    def evaluate(rec):
        m = measure(rec, "search")
        p = predict_level(mdl, rec["_gm"], rec["conditions"], L, m, random_layout=rec["random_layout"])
        rec["pred"] = p.expected_ft_any
        rec["s_prediction"] = {k: getattr(p, k) for k in ("status", "in_support", "insufficient_reasons",
                                                          "expected_ft_any", "range80_ft_any", "confidence")}
        rec["s_flags"] = [f["code"] for f in p.evidence_flags]
        if p.in_support and p.expected_ft_any is not None:
            v = verdict(p, t, sup, confirm_bands=("S3",))
            hard = [f["code"] for f in v.target_flags if f["severity"] == "hard"]
            rec["s_p_in_band"], rec["s_score"] = v.p_in_band, round(score(p, t), 4)
            rec["eligible"] = p.confidence in ("high", "medium") and not hard
        st = rec["screen"]["structure"]
        log(f"gen {rec['gen_index']} {rec['phase']} {rec['cfg']} tiles {int(st['tiles'])} Ly {int(st['layers'])} "
            f"{rec['screen']['combo']} → pred {rec['pred']} {p.confidence} P(band) {rec.get('s_p_in_band')} "
            f"eligible {rec.get('eligible')} | games {bud.d['games']}")
        P1.save(lvdir / "progress.json", {"plan": PLAN, "records": [_pub(r) for r in recs]})

    def n_meas():
        return sum(1 for r in recs if r.get("measurements"))

    def n_good():
        return sum(1 for r in recs if r.get("eligible") and (r.get("s_p_in_band") or 0) >= 0.5)

    def cell(rec):
        st = rec["screen"]["structure"]
        tl = 0 if st["tiles"] < 51 else 1 if st["tiles"] <= 75 else 2
        return (int(st["layers"]), tl, "stack" in rec["screen"]["combo"])
    caps = PLAN["caps"]
    with ProcessPoolExecutor(2) as ex:
        rng = _r.Random(20261016)
        S = PLAN["space"]
        cells = Counter()
        for _ in range(PLAN["explore"]["draws"]):
            if n_meas() >= PLAN["explore"]["measure_max"] or len(recs) >= caps["generations"]:
                break
            cfg = {k: rng.choice(v) for k, v in S.items()}
            r = gen(cfg, "explore")
            if r.get("skip"):
                log(f"gen {r['gen_index']} explore skip {r['skip']}")
                continue
            c = cell(r)
            if cells[c] >= 3:
                r["skip"] = "cell_full"
                continue
            cells[c] += 1
            evaluate(r)
        anchors_done, rnd = set(), 0
        while n_meas() < caps["full_measurements"] and len(recs) < caps["generations"] and n_good() < 3:
            el = sorted([r for r in recs if r.get("eligible")],
                        key=lambda r: (abs(lgt(r["pred"]) - lgt(t)), r["gen_index"]))
            anchor = next((r for r in el if r["gen_index"] not in anchors_done), None)
            if anchor is None:
                log("no unused eligible anchor — stop")
                break
            anchors_done.add(anchor["gen_index"])
            todo = neighbours(anchor["cfg"]) + [{"pattern_index": rng.choice(S["pattern_index"]), "layers": 5,
                                                 "grid": 8, "target_difficulty": 0.5, "gimmick_intensity": 1.5,
                                                 "goal_type": "stack", "available": ["craft", "stack"]}]
            for cfg in todo:
                if n_meas() >= caps["full_measurements"] or len(recs) >= caps["generations"] or n_good() >= 3:
                    break
                r = gen(cfg, f"exploit{rnd}:a{anchor['gen_index']}")
                if r.get("skip"):
                    log(f"gen {r['gen_index']} exploit skip {r['skip']}")
                    continue
                evaluate(r)
            rnd += 1
        out = {"plan": PLAN, "n_generated": len(recs), "n_measured": n_meas(), "n_good": n_good()}
        el = sorted([r for r in recs if r.get("eligible")],
                    key=lambda r: (-r["s_p_in_band"], r["s_score"], r["gen_index"]))
        if not el:
            out.update(outcome="INSUFFICIENT_EVIDENCE", reason="근거 충분 후보 없음 (확인 생략)")
        else:
            top = el[0]
            out["selected_gen_index"] = top["gen_index"]
            g2 = P2.generate_isolated(top["request"], top["gen_seed"])
            top["reproduced"] = g2["ok"] and cond_hash(*finalize_game_conditions(g2["level_json"], L)) == top["cond_hash"]
            m_c = measure(top, "confirm")
            ev = X.evaluate_user_expected(mdl, top["_gm"], top["conditions"], L, m_c, t,
                                          random_layout=top["random_layout"], confirm_bands=("C3",))
            out.update(evaluation=ev, outcome=ev["verdict"]["verdict"], reason=ev["verdict"]["reason"],
                       selected=_pub(top))
        out.update(records=[_pub(r) for r in recs], wall_sec=round(time.time() - t0, 1),
                   swap_used_after=P1.swap_used(), finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        P1.save(lvdir / "result.json", out)
    log("A90 →", out["outcome"], "|", out.get("reason"), "| games", bud.d["games"], "cpu", bud.d["cpu_sec"],
        "peak worker RSS", bud.d["peak_worker_rss_mb"], "driver maxrss",
        round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20, 1), "MB")


def _pub(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("a85").set_defaults(f=cmd_a85)
    sub.add_parser("run").set_defaults(f=cmd_run)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
