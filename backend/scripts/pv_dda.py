"""DDA set preparation (game IMPL_SPEC §V2-9-2) — PREPARATION ONLY, NOT APPROVED, NOT UPLOADED.

Primary output : `seedvar_N` rows  = original row with t0-ized copy map + randSeed token string
                 (5 tiers "e2|e1|h1|h2", 3 tiers "e2|h2"; token "seed" or "seed@utc"), original level_N untouched.
Reference only : easy_N / hard_N rows = the chosen e2 / h2 assignment baked into explicit tiles.
Baseline       : the ORIGINAL map (not a t0 base seed) — §V2-9-2 ④.

Selection (proposed values, user decision pending — 10 report):
- adaptive θ pair from an original-map scan (bot skill trough [0.34,0.50) excluded), stage 1 64 games/θ,
  stage 2 950 games/θ, independent-sample CI (z=2.4977).
- outer e2/h2: |Δ vs original| ≥ 0.10, CI excludes 0, robust (extra θ + AVERAGE + EXPERT: ≥2/3 informative
  points keep direction, not skill-sensitive), h2: editor-predictor clear% ≥ 20 and max(θ_hi, EXPERT) ≥ 0.10;
  nearest target (e2 +0.15, h2 −0.20).
- inner e1/h1: Δ ≥ 0.04, CI excludes 0, robust, |inner| ≤ |outer| − 0.02 → 5 tiers if both, else 3 tiers.
- a low-skill point (θ 0.29/0.15) is measured and recorded (warning only).
- solvability: solver PROVEN_SOLVABLE (and no solver-unreliable gimmick) = "strict"; else a bot win = "extended".
- utc: easy side utc0 or utc0−1, hard side utc0 or utc0+1. Pools: utc0 32→64→128, then ±1 32→64 (failing side).
- non-target (no row): L<32, boss N%10==0, gimmick tutorial levels (§V2-4-1 b'③).
Shared core untouched; game repo untouched; outputs under <sandbox>/dda_sets/ only.

Usage: python scripts/pv_dda.py --level 55 --next      (one step per call; prints LEVEL_DONE when finished)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from app.api.routes.gboost import _convert_to_townpop_format  # noqa: E402  (import only)
from app.core.mc_difficulty import sweep_level_task  # noqa: E402
from app.core.pv.canonical import canonical_map, check_layer_continuity, struct_hash  # noqa: E402
from app.core.pv.cs_shuffle import CTile, resolve_map, shuffle_empty_tiles  # noqa: E402
from app.core.pv.evaluate import candidate_seeds, evaluate_maps, evaluate_points, solve_check  # noqa: E402
from app.core.pv.select import SCAN_THETAS, UNEVALUABLE_MAX, any_win, indep_diff  # noqa: E402
from app.core.pv.t0ize import PvT0izeError, bot_level_json, original_kinds, t0ize_level  # noqa: E402

COPY = "pv_20261002_live3"
SB = os.path.join(BACKEND, "data", "pv_sandbox", COPY)
DDA = os.path.join(SB, "dda_sets")
WORKERS = int(os.environ.get("PV_WORKERS", "6"))

TUTORIAL_LEVELS = {11, 21, 31, 51, 81, 111, 151, 191, 241, 291, 391, 441}  # GEN TUTORIAL_UNLOCK_LEVELS
UNRELIABLE_SOLVER = ("bomb", "curtain", "frog", "teleporter", "unknown")    # 03 §1
TROUGH = (0.34, 0.50)

SEED_SCAN, SEED_S1, SEED_S2, SEED_ROBUST, SEED_PRED = 5_000_000, 6_000_000, 7_000_000, 9_100_000, 4242
SCAN_GAMES, S1_GAMES, S2_GAMES, ROBUST_GAMES = 64, 64, 950, 600
SOLVER_NODES = 5000
OUTER_MIN, INNER_MIN, GAP_MIN = 0.10, 0.04, 0.02
TARGET = {"easy": 0.15, "hard": -0.20}
H_PRED_MIN, H_HI_MIN = 0.20, 0.10   # H_PRED_MIN kept for flags only (absolute floor rejected 10/09)
H_PRED_REL = 0.5                      # h2 predicted clear ≥ 0.5 × original predicted clear (proposed, user to confirm)
PRED_FLAGS = {"abs20": lambda pc, po: pc >= 0.20, "abs10": lambda pc, po: pc >= 0.10, "abs05": lambda pc, po: pc >= 0.05,
              "rel50": lambda pc, po: pc >= H_PRED_REL * po, "none": lambda pc, po: True}
LEVEL_TIME_CAP = 20 * 60
POOL_PLAN = [("u0", 0, 32), ("u0", 32, 64), ("u0", 64, 128), ("flex", 0, 32), ("flex", 32, 64)]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


_SRC = None


def source_level(n):
    global _SRC
    if _SRC is None:
        _SRC = {lv["meta"]["level_number"]: lv for lv in load(os.path.join(SB, "source.json"))["levels"]}
    return _SRC.get(n)


def orig_row(level_json):
    """Original level row as the GB exporter would emit it (etime dropped: time-dependent)."""
    lj = {k: ({**v, "tiles": {}} if k.startswith("layer_") and isinstance(v, dict) and isinstance(v.get("tiles"), list) else v)
          for k, v in level_json.items()}
    row = _convert_to_townpop_format(lj)
    row.pop("etime", None)
    return row


class W:
    """Per-level work dir with accumulating caches (keys 'u:seed')."""

    def __init__(self, n):
        self.n = n
        self.d = os.path.join(DDA, "work", f"{n:04d}")
        os.makedirs(self.d, exist_ok=True)

    def f(self, name):
        return os.path.join(self.d, name)

    def get(self, name, default=None):
        p = self.f(name)
        return load(p) if os.path.exists(p) else (copy.deepcopy(default) if default is not None else None)

    def put(self, name, obj):
        save(self.f(name), obj)

    def merge(self, name, upd):
        cur = self.get(name, {})
        cur.update(upd)
        self.put(name, cur)
        return cur


# ── reuse of earlier experiment data (same seeds, θ rule, bot seed bases, game counts) ─────────────
def import_previous(w: W, prep):
    if w.get("imported.json") is not None:
        return
    d2 = os.path.join(SB, "eval2", f"{w.n:04d}")
    d3 = os.path.join(SB, "eval3", f"{w.n:04d}")
    d4 = os.path.join(SB, "eval4", f"{w.n:04d}")
    u0 = prep["utc0"]
    s1, s2, sol, rob = {}, {}, {}, {}
    got = []
    if os.path.isdir(d2) and load(os.path.join(d2, "prep.json"))["meta"]["structHash"] == prep["structHash"]:
        for p in (32, 64, 128):
            for name, tgt, key in ((f"s1_p{p}.json", s1, "results"), (f"s2_p{p}.json", s2, "results"),
                                   (f"solve_p{p}.json", sol, "solved")):
                fp = os.path.join(d2, name)
                if os.path.exists(fp):
                    tgt.update({f"{u0}:{s}": v for s, v in load(fp)[key].items()})
        for name in ("scan.json", "orig2.json"):
            fp = os.path.join(d2, name)
            if os.path.exists(fp):
                w.put(f"imp_{name}", load(fp))
                got.append(name)
        if os.path.isdir(d3):
            for fn in os.listdir(d3):
                if fn.startswith("s1_u"):
                    s1.update({f"{fn.split('_')[1][1:]}:{s}": v for s, v in load(os.path.join(d3, fn))["results"].items()})
            for name, tgt, key in (("s2_flex.json", s2, "results"), ("solve_flex.json", sol, "solved")):
                fp = os.path.join(d3, name)
                if os.path.exists(fp):
                    tgt.update(load(fp)[key])
        if os.path.isdir(d4):
            for fn in os.listdir(d4):
                if fn.startswith("exp_s1_"):
                    s1.update(load(os.path.join(d4, fn))["results"])
            for name, tgt, key in (("exp_s2.json", s2, "results"), ("exp_solve.json", sol, "solved")):
                fp = os.path.join(d4, name)
                if os.path.exists(fp):
                    tgt.update(load(fp)[key])
            fp = os.path.join(d4, "robust.json")
            if os.path.exists(fp):
                r = load(fp)
                rob = {"points": r.get("points"), "results": r.get("results", {})}
    if s1:
        w.merge("s1.json", s1)
    if s2:
        w.merge("s2.json", s2)
    if sol:
        w.merge("solve.json", sol)
    if rob.get("results"):
        w.put("robust_v4.json", rob)
    w.put("imported.json", {"s1": len(s1), "s2": len(s2), "solve": len(sol), "robust_v4": len(rob.get("results", {})),
                            "files": got})


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────
def pool_seeds(prep, u):
    sh = prep["structHash"]
    return candidate_seeds(sh, 128) if u == prep["utc0"] else candidate_seeds(f"{sh}|u{u}", 64)


def row_for(prep, u, seed):
    row = copy.deepcopy(prep["t0row"])
    row["useTileCount"] = str(u)
    row["randSeed"] = str(seed)
    return row


def lj_seed(prep, key):
    u, s = (int(x) for x in key.split(":"))
    row = row_for(prep, u, s)
    res = shuffle_empty_tiles(row["map"], rand_seed=s, use_tile_count=u, strict=True)
    return bot_level_json(row, resolve_map(row["map"], res))


def lj_orig(prep):
    lv = source_level(prep["level"])
    o = prep["orig"]
    return bot_level_json({"randSeed": o.get("randSeed") or 1, "useTileCount": o.get("useTileCount") or prep["utc0"],
                           "unlockTile": 0}, canonical_map(lv["level_json"]))


def golden_check(w: W, prep, u, seeds):
    """dotnet golden for the pool chunk (all candidate boards checked before evaluation)."""
    done = w.get("golden.json", {})
    need = [s for s in seeds if f"{u}:{s}" not in done]
    if not need:
        return 0
    gdir = os.path.join(DDA, "golden")
    os.makedirs(gdir, exist_ok=True)
    inp = os.path.join(gdir, f"in_l{w.n:04d}_u{u}_{need[0]}.json")
    save(inp, {"caseId": f"dda_l{w.n:04d}_u{u}", "kind": "real", "levelId": f"level_{w.n}", "dumpRng": False,
               "note": "DDA prep candidate pool", "row": row_for(prep, u, need[0]),
               "runs": [{"randSeed": str(s)} for s in need]})
    out = subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "tools", "pv_golden"), "--", "case", inp],
                         cwd=REPO, capture_output=True, text=True, timeout=200)
    os.remove(inp)
    if out.returncode != 0:
        raise SystemExit(f"dotnet case failed: {out.stderr[-400:]}")
    exp = json.loads(out.stdout)
    upd = {}
    for s, r in zip(need, exp["results"]):
        got = shuffle_empty_tiles(prep["t0row"]["map"], rand_seed=s, use_tile_count=u)
        pos = [[x.layer_name, x.pos, -1 if x.inner_index is None else x.inner_index] for x in got.slots]
        ok = pos == r["positions"] and [CTile("", "", t, "").tile_id_num for t in got.assigned] == r["types"]
        upd[f"{u}:{s}"] = ok
        if not ok:
            raise SystemExit(f"GOLDEN MISMATCH level {w.n} utc {u} seed {s}")
    w.merge("golden.json", upd)
    return len(need)


def extra_theta(scan_rates, sel):
    cands = [t for t in SCAN_THETAS if not (TROUGH[0] <= t < TROUGH[1]) and t < 1.0
             and all(abs(t - s) >= 0.2 - 1e-9 for s in sel)]
    if not cands:
        cands = [t for t in SCAN_THETAS if not (TROUGH[0] <= t < TROUGH[1]) and t < 1.0 and t not in sel]
    r = {float(k): v for k, v in scan_rates.items()}
    return min(cands, key=lambda t: (abs(r.get(t, 0) - 0.5), t))


def low_theta(sel, extra):
    for t in (0.29, 0.15, 0.0):
        if t not in sel and abs(t - extra) > 1e-9:
            return t
    return 0.0


def choose_pair(rates):
    r = {float(t): v for t, v in rates.items()}
    best = max(r.values()) if r else 0.0
    if best < UNEVALUABLE_MAX:
        return {"evaluable": False, "reason": f"orig max rate over scan θ = {best:.3f} < {UNEVALUABLE_MAX}"}
    ranked = sorted(r, key=lambda t: (abs(r[t] - 0.5), t))
    return {"evaluable": True, "thetas": sorted(ranked[:2])}


def point_rates(key, s2, rob):
    out = {f"θ:{float(t):g}": v["rate"] for t, v in s2[key]["theta"].items()}
    for pt, v in rob.get(key, {}).get("point", {}).items():
        out[pt] = v["rate"]
    return out


def robust_judge(key, s2, rob, sign, judged_points):
    rc, ro = point_rates(key, s2, rob), point_rates("orig", s2, rob)
    pts = [p for p in judged_points if p in rc and p in ro]
    info = [p for p in pts if not (max(rc[p], ro[p]) <= 0.02 or min(rc[p], ro[p]) >= 0.98)]
    deltas = {p: sign * (rc[p] - ro[p]) for p in info}
    ok = sum(1 for v in deltas.values() if v > 0)
    need = math.ceil(2 * len(info) / 3) if info else 1
    spread = (max(deltas.values()) - min(deltas.values())) if deltas else 0.0
    sensitive = any(v < 0 for v in deltas.values()) and spread >= 0.15
    measured = len(pts) == len(judged_points)
    return {"pass": measured and bool(info) and ok >= need and not sensitive, "measured": measured,
            "informative": len(info), "dirOk": ok, "need": need, "sensitive": sensitive, "spread": round(spread, 4),
            "meanDelta": (sum(deltas.values()) / len(deltas)) if deltas else 0.0}


def side_of(prep, side, key):
    if key == "orig":
        return False
    u = int(key.split(":")[0])
    u0 = prep["utc0"]
    return u in ((u0 - 1, u0) if side == "easy" else (u0, u0 + 1))


def evidence(key, s1, s2, sol, unreliable):
    v = sol.get(key, {}).get("verdict")
    if v == "PROVEN_SOLVABLE" and not unreliable:
        return "strict"
    if any_win(s1.get(key), s2.get(key)):
        return "extended"
    return None


# ── one step ──────────────────────────────────────────────────────────────────────────────────────
def step(n, ex):
    w = W(n)
    if w.get("final.json") is not None:
        return "LEVEL_DONE"
    t_start = time.time()
    state = w.get("state.json", {"wall": 0.0})

    def done(final):
        final.update(level=n, wallSec=round(state["wall"] + time.time() - t_start, 1))
        w.put("final.json", final)
        return "final " + final["status"]

    def tick(msg):
        state["wall"] = state["wall"] + time.time() - t_start
        w.put("state.json", state)
        return msg

    if state["wall"] > LEVEL_TIME_CAP:
        return done({"status": "timeout_hold", "reason": f"level time cap {LEVEL_TIME_CAP}s exceeded"})

    # 0. target
    if n < 32 or n > 1500:
        return done({"status": "non_target", "reason": "outside L32~1500"})
    if n % 10 == 0:
        return done({"status": "non_target", "reason": "boss level (§V2-4-1 b'③)"})
    if n in TUTORIAL_LEVELS:
        return done({"status": "non_target", "reason": "gimmick tutorial level (§V2-4-1 b'③)"})
    lv = source_level(n)
    if lv is None:
        return done({"status": "error", "reason": "level not in source copy"})

    # 1. prep
    prep = w.get("prep.json")
    if prep is None:
        lj = lv["level_json"]
        try:
            first = t0ize_level(lj, 1)
        except PvT0izeError as e:
            msg = str(e)
            reason = ("key tiles — t0 rule for slot-lock keys not supported" if "key" in msg else
                      "original already has t0 (count-only containers = runtime random, no fixed baseline)"
                      if "t0 already" in msg else f"t0ize: {msg}")
            return done({"status": "not_prepared", "reason": reason})
        effects = sorted({t[1].lower() for k, l in canonical_map(lj).items() if k.startswith("layer_") and isinstance(l, dict)
                          for t in (l.get("tiles") or {}).values() if len(t) > 1 and isinstance(t[1], str) and t[1]})
        unreliable = any(e.startswith(UNRELIABLE_SOLVER) for e in effects)
        prep = {"level": n, "structHash": first["meta"]["structHash"], "utc0": first["meta"]["utc0"],
                "tileCount": first["meta"]["tileCount"], "t0row": first["row"], "origRow": orig_row(lj),
                "orig": {"randSeed": lj.get("randSeed"), "useTileCount": lj.get("useTileCount")},
                "effects": effects, "solverUnreliable": unreliable,
                "craft": any(isinstance(t, list) and t and isinstance(t[0], str) and t[0].startswith("craft_")
                             for k, l in lj.items() if k.startswith("layer_") and isinstance(l, dict)
                             for t in (l.get("tiles") or {}).values() if isinstance(l.get("tiles"), dict))}
        w.put("prep.json", prep)
        import_previous(w, prep)
        return tick("prep")
    u0 = prep["utc0"]

    # 2. scan (orig)
    scan = w.get("scan.json")
    if scan is None:
        imp = w.get("imp_scan.json")
        if imp is not None:
            rates = imp["rates"]
        else:
            out = evaluate_maps(ex, {"orig": lj_orig(prep)}, SCAN_GAMES, SEED_SCAN, thetas=SCAN_THETAS, chunk=64)
            out.pop("_cpuSec", None)
            rates = {t: v["rate"] for t, v in out["orig"]["theta"].items()}
        w.put("scan.json", {"rates": rates, "choice": choose_pair(rates)})
        return tick("scan")
    ch = scan["choice"]
    if not ch["evaluable"]:
        return done({"status": "unevaluable", "reason": ch["reason"], "scan": scan["rates"]})
    th = ch["thetas"]
    xt = extra_theta(scan["rates"], th)
    lt = low_theta(th, xt)
    points = [f"θ:{xt:g}", "profile:average", "profile:expert", f"θ:{lt:g}"]   # first 3 == v4 robust points
    judged = [f"θ:{float(t):g}" for t in th] + points[:3]
    judged_inner = judged + [points[3]]       # inner tiers: + low-skill point (10/09)

    # 3. orig stage-2
    s2 = w.get("s2.json", {})
    if "orig" not in s2:
        imp = w.get("imp_orig2.json")
        if imp is not None:
            s2 = w.merge("s2.json", {"orig": imp["results"]["orig"]})
        else:
            out = evaluate_maps(ex, {"orig": lj_orig(prep)}, S2_GAMES, SEED_S2, thetas=th)
            out.pop("_cpuSec", None)
            s2 = w.merge("s2.json", {"orig": out["orig"]})
        return tick("orig2")

    s1 = w.get("s1.json", {})
    # imported measurements must be at exactly this θ pair (defensive; same rule should give the same pair)
    th_set = {float(t) for t in th}
    s1 = {k: v for k, v in s1.items() if {float(t) for t in v["theta"]} == th_set}
    s2 = {k: v for k, v in s2.items() if {float(t) for t in v["theta"]} == th_set}
    sol = w.get("solve.json", {})
    rob = w.get("robust.json", {})
    rob_v4 = w.get("robust_v4.json", {"results": {}})
    # reuse v4 robust measurements for the first 3 points (same seeds/θ/profiles/games)
    if rob_v4.get("points") == points[:3]:
        for k, v in rob_v4["results"].items():
            if k not in rob:
                rob[k] = v
    w_orig = s2["orig"]["W"]
    rounds = w.get("rounds.json", [])

    sides_done = decide(prep, s1, s2, sol, rob, judged, None, judged_inner)
    failing = [sd for sd in ("easy", "hard") if sides_done[sd]["outer"] is None]

    # robust measurement for s2-valid candidates not yet measured
    def missing_pts(k):
        return [p for p in points if p not in rob.get(k, {}).get("point", {})]
    need_rob = ["orig"] if missing_pts("orig") else []
    for sd in ("easy", "hard"):
        need_rob += [k for k in sides_done[sd]["robustQueue"] if missing_pts(k)]
    need_rob = list(dict.fromkeys(need_rob))
    if need_rob:
        maps = {k: (lj_orig(prep) if k == "orig" else lj_seed(prep, k)) for k in need_rob}
        pts_missing = {k: [p for p in points if p not in rob.get(k, {}).get("point", {})] for k in need_rob}
        # measure all 4 points with fixed per-point seed offsets (index in `points`) so reuse stays identical
        out = {}
        for p_idx, pt in enumerate(points):
            ks = [k for k in need_rob if pt in pts_missing[k]]
            if not ks:
                continue
            r = evaluate_points(ex, {k: maps[k] for k in ks}, [pt], ROBUST_GAMES, SEED_ROBUST + p_idx * 10_000)
            for k, v in r.items():
                out.setdefault(k, {"point": {}})["point"].update(v["point"])
        for k, v in out.items():
            rob.setdefault(k, {"point": {}})["point"].update(v["point"])
        w.put("robust.json", rob)
        return tick(f"robust {len(need_rob)}")

    # editor predictor for h2 candidates that passed everything else
    pred = w.get("pred.json", {})
    pq = [k for k in sides_done["hard"]["predQueue"] if k not in pred]
    if pq and "orig" not in pred:
        pq = ["orig"] + pq
    if pq:
        futs = {k: ex.submit(sweep_level_task, {"level_json": lj_orig(prep) if k == "orig" else lj_seed(prep, k),
                                                "seed": SEED_PRED, "level_number": n}) for k in pq}
        w.merge("pred.json", {k: {"predicted_clear_rate": f.result().get("predicted_clear_rate"),
                                  "error": f.result().get("error")} for k, f in futs.items()})
        return tick(f"pred {len(pq)}")
    sides_done = decide(prep, s1, s2, sol, rob, judged, pred, judged_inner)
    failing = [sd for sd in ("easy", "hard") if sides_done[sd]["outer"] is None]

    if failing:
        # next pool round for failing sides
        r_idx = len(rounds)
        while r_idx < len(POOL_PLAN):
            kind, lo, hi = POOL_PLAN[r_idx]
            jobs = []
            for sd in failing:
                u = u0 if kind == "u0" else (u0 - 1 if sd == "easy" else u0 + 1)
                if not 1 <= u <= 15:
                    continue
                seeds = pool_seeds(prep, u)[lo:hi]
                if seeds:
                    jobs.append((sd, u, seeds))
            if jobs:
                break
            rounds.append({"round": r_idx, "skipped": True})
            r_idx += 1
        if r_idx >= len(POOL_PLAN):
            return finalize(w, prep, s1, s2, sol, rob, judged, points, th, sides_done, rounds, pred, done)
        # stage 1 (golden first)
        new_s1 = {}
        for sd, u, seeds in {(u, tuple(s)): (sd, u, s) for sd, u, s in jobs}.values():
            golden_check(w, prep, u, seeds)
            miss = [s for s in seeds if f"{u}:{s}" not in s1]
            if miss:
                out = evaluate_maps(ex, {f"{u}:{s}": lj_seed(prep, f"{u}:{s}") for s in miss}, S1_GAMES, SEED_S1,
                                    thetas=th, chunk=64)
                out.pop("_cpuSec", None)
                new_s1.update(out)
        if new_s1:
            s1 = w.merge("s1.json", new_s1)
        # shortlist (stage-1 Δ vs original stage-2 W) and stage 2
        picks = []
        for sd, u, seeds in jobs:
            sign = 1 if sd == "easy" else -1
            pool = [f"{u}:{s}" for s in seeds if f"{u}:{s}" in s1 and f"{u}:{s}" not in s2]
            pool = [k for k in pool if sign * (s1[k]["W"] - w_orig) > 0]
            outer = sorted(pool, key=lambda k: (abs((s1[k]["W"] - w_orig) - TARGET[sd]), k))[:2]
            inner = sorted([k for k in pool if k not in outer],
                           key=lambda k: (abs((s1[k]["W"] - w_orig) - sign * 0.06), k))[:2]
            picks += outer + inner
        picks = list(dict.fromkeys(picks))
        if picks:
            out = evaluate_maps(ex, {k: lj_seed(prep, k) for k in picks}, S2_GAMES, SEED_S2, thetas=th)
            out.pop("_cpuSec", None)
            s2 = w.merge("s2.json", out)
            nowin = [k for k in picks if not any_win(s1.get(k), s2.get(k))]
            futs = {k: ex.submit(solve_check, lj_seed(prep, k), SOLVER_NODES) for k in picks}
            w.merge("solve.json", {k: f.result() for k, f in futs.items()})
        rounds.append({"round": r_idx, "plan": POOL_PLAN[r_idx], "sides": failing, "stage2": picks,
                       "noWinBeforeSolver": len(nowin) if picks else 0})
        w.put("rounds.json", rounds)
        return tick(f"round {r_idx} {POOL_PLAN[r_idx]} picks={len(picks)}")

    # solver on every chosen tier (strict grade needs PROVEN_SOLVABLE; imported keys may not have been solved)
    chosen = [sides_done[sd][k]["key"] for sd in ("easy", "hard") for k in ("outer", "inner") if sides_done[sd][k]]
    gold = w.get("golden.json", {})
    ungold = [k for k in chosen if k not in gold]
    if ungold:
        by_u = {}
        for k in ungold:
            u, sd = k.split(":")
            by_u.setdefault(int(u), []).append(int(sd))
        for u, seeds in by_u.items():
            golden_check(w, prep, u, seeds)
        return tick(f"golden chosen {len(ungold)}")
    unsolved = [k for k in chosen if k not in sol]
    if unsolved:
        futs = {k: ex.submit(solve_check, lj_seed(prep, k), SOLVER_NODES) for k in unsolved}
        w.merge("solve.json", {k: f.result() for k, f in futs.items()})
        return tick(f"solve chosen {len(unsolved)}")
    return finalize(w, prep, s1, s2, sol, rob, judged, points, th, sides_done, rounds, pred, done)


def same_side_order(outer_k, inner_k, s2, rob, sign, pts):
    """Outer must be more extreme than inner on a majority of informative points (else order flipped)."""
    ro, ri, rb = point_rates(outer_k, s2, rob), point_rates(inner_k, s2, rob), point_rates("orig", s2, rob)
    use = [p for p in pts if p in ro and p in ri and p in rb
           and not (max(ro[p], ri[p], rb[p]) <= 0.02 or min(ro[p], ri[p], rb[p]) >= 0.98)]
    good = sum(1 for p in use if sign * (ro[p] - ri[p]) > 0)
    return {"ok": bool(use) and good * 2 > len(use), "points": len(use), "outerMoreExtreme": good}


def decide(prep, s1, s2, sol, rob, judged, pred=None, judged_inner=None):
    """Per side: valid candidates, robust queue, chosen outer/inner."""
    pred = pred or {}
    judged_inner = judged_inner or judged
    out = {}
    o = s2["orig"]
    for side in ("easy", "hard"):
        sign = 1 if side == "easy" else -1
        cand = []
        for k, e in s2.items():
            if not side_of(prep, side, k) or sign * (e["W"] - o["W"]) <= 0:
                continue
            d = indep_diff(e, o) if sign > 0 else indep_diff(o, e)
            ev = evidence(k, s1, s2, sol, prep["solverUnreliable"])
            if d["lo"] <= 0 or ev is None:
                continue
            cand.append({"key": k, "delta": e["W"] - o["W"], "absd": d["diff"], "lo": d["lo"], "hi": d["hi"], "evidence": ev})
        outer_c = sorted([c for c in cand if c["absd"] >= OUTER_MIN], key=lambda c: (abs(c["delta"] - TARGET[side]), c["key"]))
        inner_c = sorted([c for c in cand if INNER_MIN <= c["absd"]], key=lambda c: (c["absd"], c["key"]))
        queue = [c["key"] for c in outer_c[:3]] + [c["key"] for c in inner_c[:3]]
        judged_map = {c["key"]: robust_judge(c["key"], s2, rob, sign, judged) for c in cand if c["key"] in rob}
        pred_q = []
        outer = None
        for c in outer_c:
            j = judged_map.get(c["key"])
            if not j or not j["pass"]:
                continue
            if side == "hard":
                r = point_rates(c["key"], s2, rob)
                th_hi = max((p for p in r if p.startswith("θ:")), key=lambda p: float(p[2:]))
                hi = max(r[th_hi], r.get("profile:expert", 0.0))
                c["hiRate"] = hi
                if hi < H_HI_MIN:
                    continue
                if c["key"] not in pred:
                    pred_q.append(c["key"])
                    continue
                pcr = pred[c["key"]].get("predicted_clear_rate") or 0.0
                po = (pred.get("orig") or {}).get("predicted_clear_rate")
                c["pred"] = pcr
                if po is None:
                    if "orig" not in pred_q:
                        pred_q.insert(0, "orig")
                    continue
                if pcr < H_PRED_REL * po:
                    continue
            outer = c
            break
        inner = None
        inner_log = []
        if outer:
            for c in inner_c:
                if c["key"] == outer["key"] or c["absd"] > outer["absd"] - GAP_MIN or c["key"] not in rob:
                    continue
                # 10/09: inner robust test also includes the low-skill point (trough-free θ)
                ji = robust_judge(c["key"], s2, rob, sign, judged_inner)
                order = same_side_order(outer["key"], c["key"], s2, rob, sign, judged_inner)
                inner_log.append({"key": c["key"], "robust": ji, "order": order})
                if not ji["pass"] or not order["ok"]:
                    continue
                inner = c
                break
        out[side] = {"outer": outer, "inner": inner, "nCand": len(cand), "robustQueue": queue,
                     "predQueue": pred_q, "judged": judged_map, "innerLog": inner_log}
    return out


def candidate_info(prep, s2, rob, sides, pred):
    """All CI/evidence-valid candidates with robust verdict and h2 floor flags (re-selection without re-running)."""
    po = (pred.get("orig") or {}).get("predicted_clear_rate")
    out = {}
    for sd in ("easy", "hard"):
        rows = []
        for k, j in sides[sd]["judged"].items():
            r = point_rates(k, s2, rob)
            th = [p for p in r if p.startswith("θ:")]
            hi = max([r[max(th, key=lambda p: float(p[2:]))]] + ([r["profile:expert"]] if "profile:expert" in r else [])) if th else None
            pc = (pred.get(k) or {}).get("predicted_clear_rate")
            rec = {"key": k, "delta": s2[k]["W"] - s2["orig"]["W"], "robustPass": j["pass"], "sensitive": j["sensitive"],
                   "informative": j["informative"], "dirOk": j["dirOk"], "spread": j["spread"], "hiRate": hi, "pred": pc}
            if sd == "hard" and pc is not None and po is not None:
                rec["floorFlags"] = {name: bool(f(pc, po)) for name, f in PRED_FLAGS.items()}
            rows.append(rec)
        out[sd] = {"candidates": rows, "nJudged": len(rows), "nSensitive": sum(1 for x in rows if x["sensitive"]),
                   "nRobustPass": sum(1 for x in rows if x["robustPass"])}
    out["predOrig"] = po
    easy_outer = any(x["robustPass"] and x["delta"] >= OUTER_MIN for x in out["easy"]["candidates"])
    feas = {}
    for name in PRED_FLAGS:
        hard_outer = any(x["robustPass"] and x["delta"] <= -OUTER_MIN and (x["hiRate"] or 0) >= H_HI_MIN
                         and (x.get("floorFlags") or {}).get(name) for x in out["hard"]["candidates"])
        feas[name] = bool(easy_outer and hard_outer)
    out["levelRuleFeasible"] = feas   # would an e2/h2 pair exist under each h2 floor rule (no re-measurement)
    out["note"] = "floorFlags absent = predictor not run (candidate failed robust or max(θ_hi, EXPERT) ≥ 0.10 first)"
    return out


def tok(prep, key):
    u, s = key.split(":")
    return s if int(u) == prep["utc0"] else f"{s}@{u}"


def kinds_count(m):
    k, keys, t0 = original_kinds(m)
    return k


def invariants(prep, seedvar_row, baked):
    """§S-2 / §6-3 checks adapted to §V2-9-2 (row-level fields same as original, structure same)."""
    o = prep["origRow"]
    issues = []
    same_fields = ("rewardCoin", "rewardList", "tileSkin", "backgroundIndex", "autoCollectCount", "timea", "unlockTile",
                   "col", "row", "num", "sets", "layer", "shuffleLayer", "useInRandomizer", "teleportRandSeed",
                   "useTeleportInRandomizer")
    rows = {"seedvar": seedvar_row, **baked}
    for name, r in rows.items():
        for f in same_fields:
            if str(r.get(f)) != str(o.get(f)):
                issues.append(f"{name}.{f}: {r.get(f)!r} != orig {o.get(f)!r}")
        if struct_hash(r["map"]) != prep["structHash"]:
            issues.append(f"{name}: structHash differs (gimmick kind/position/count or container shape)")
        if check_layer_continuity(r["map"]):
            issues.append(f"{name}: layer continuity")
        cm = canonical_map({**{k: v for k, v in r["map"].items()}, "layer": int(r["map"]["layer"])})
        if list(cm.keys()) != list(r["map"].keys()) or any(
                list(cm[k]["tiles"].keys()) != list(r["map"][k]["tiles"].keys()) for k in cm if k.startswith("layer_")):
            issues.append(f"{name}: map key order not canonical")
    for name, r in baked.items():
        kinds = kinds_count(r["map"])
        if any(v % 3 for v in kinds.values()):
            issues.append(f"{name}: per-kind count not divisible by 3")
        if str(len(kinds)) != str(r["useTileCount"]):
            issues.append(f"{name}: useTileCount {r['useTileCount']} != actual kinds {len(kinds)}")
    return issues


def finalize(w, prep, s1, s2, sol, rob, judged, points, th, sides, rounds, pred, done):
    e, h = sides["easy"], sides["hard"]
    base = {"thetas": th, "robustPoints": points, "judgedPoints": judged, "wOrig": s2["orig"]["W"],
            "utc0": prep["utc0"], "rounds": rounds, "effects": prep["effects"], "solverUnreliable": prep["solverUnreliable"]}
    if not (e["outer"] and h["outer"]):
        miss = [sd for sd in ("easy", "hard") if sides[sd]["outer"] is None]
        reasons = {}
        for sd in miss:
            sign = 1 if sd == "easy" else -1
            n_dir = sum(1 for k, v in s2.items() if k != "orig" and side_of(prep, sd, k)
                        and sign * (v["W"] - s2["orig"]["W"]) > 0)
            reasons[sd] = {"nStage2SameDirection": n_dir, "nValidCI": sides[sd]["nCand"],
                           "nRobustJudged": len(sides[sd]["judged"]),
                           "nRobustPass": sum(1 for j in sides[sd]["judged"].values() if j["pass"])}
        return done({"status": "no_variant", "reason": "outer tier not found after pools: " + ",".join(miss),
                     "detail": reasons, "candidates": candidate_info(prep, s2, rob, sides, w.get("pred.json", {})), **base})
    tiers = {"e2": e["outer"], "h2": h["outer"]}
    if e["inner"] and h["inner"]:
        tiers.update(e1=e["inner"], h1=h["inner"])
        order = ("e2", "e1", "h1", "h2")
    else:
        order = ("e2", "h2")
    token = "|".join(tok(prep, tiers[t]["key"]) for t in order)
    # predictor for every chosen tier + orig (difficulty display values)
    pred = w.get("pred.json", {})
    need = [tiers[t]["key"] for t in order if tiers[t]["key"] not in pred] + ([] if "orig" in pred else ["orig"])
    if need:
        with ProcessPoolExecutor(max_workers=WORKERS) as ex2:
            futs = {k: ex2.submit(sweep_level_task, {"level_json": lj_orig(prep) if k == "orig" else lj_seed(prep, k),
                                                     "seed": SEED_PRED, "level_number": prep["level"]}) for k in need}
            pred = w.merge("pred.json", {k: {"predicted_clear_rate": f.result().get("predicted_clear_rate"),
                                             "error": f.result().get("error")} for k, f in futs.items()})
    # rows
    o = prep["origRow"]
    seedvar_row = {**copy.deepcopy(o), "map": copy.deepcopy(prep["t0row"]["map"]), "randSeed": token,
                   "useTileCount": str(prep["utc0"])}
    baked = {}
    for name, t in (("easy", "e2"), ("hard", "h2")):
        k = tiers[t]["key"]
        u, s = (int(x) for x in k.split(":"))
        res = shuffle_empty_tiles(prep["t0row"]["map"], rand_seed=s, use_tile_count=u, strict=True)
        m = resolve_map(prep["t0row"]["map"], res)
        kinds = kinds_count(m)
        pcr = pred.get(k, {}).get("predicted_clear_rate")
        baked[name] = {**copy.deepcopy(o), "map": m, "randSeed": o.get("randSeed"), "useTileCount": str(len(kinds)),
                       "difficulty": str(max(0, min(100, round(pcr * 100)))) if isinstance(pcr, (int, float)) else "-1"}
    issues = invariants(prep, seedvar_row, baked)
    tier_out = {}
    for t in order:
        c = tiers[t]
        sd = "easy" if t.startswith("e") else "hard"
        r = point_rates(c["key"], s2, rob)
        tier_out[t] = {"key": c["key"], "token": tok(prep, c["key"]), "delta": c["delta"], "ci": [c["lo"], c["hi"]],
                       "evidence": c["evidence"], "solver": sol.get(c["key"], {}).get("verdict"),
                       "robust": sides[sd]["judged"][c["key"]], "pointRates": r,
                       "lowSkillRate": r.get(points[3]), "predictedClearRate": pred.get(c["key"], {}).get("predicted_clear_rate")}
        pc, po_ = tier_out[t]["predictedClearRate"], pred.get("orig", {}).get("predicted_clear_rate")
        if t.startswith("h") and pc is not None and po_ is not None:
            tier_out[t]["floorFlags"] = {name: bool(f(pc, po_)) for name, f in PRED_FLAGS.items()}
    pcr_o = pred.get("orig", {}).get("predicted_clear_rate")
    pe, ph = tier_out["e2"]["predictedClearRate"], tier_out["h2"]["predictedClearRate"]
    order_ok = all(isinstance(x, (int, float)) for x in (pe, pcr_o, ph)) and pe > pcr_o > ph
    warn = []
    if not order_ok:
        warn.append(f"predicted clear% order easy>normal>hard violated: {pe} / {pcr_o} / {ph}")
    for t, v in tier_out.items():
        lr, orr = v["lowSkillRate"], rob.get("orig", {}).get("point", {}).get(points[3], {}).get("rate")
        if lr is not None and orr is not None and ((t.startswith("e") and lr < orr) or (t.startswith("h") and lr > orr)):
            warn.append(f"{t}: low-skill point direction reversed ({lr:.3f} vs orig {orr:.3f})")
    gold = w.get("golden.json", {})
    if not all(gold.get(tier_out[t]["key"]) is True for t in order):
        issues.append("golden check missing/failed for a chosen tier")
    status = ("invariant_fail" if issues else ("5tier" if len(order) == 4 else "3tier"))
    w.put("seedvar_row.json", seedvar_row)
    w.put("baked_easy.json", baked["easy"])
    w.put("baked_hard.json", baked["hard"])
    grade = "strict" if all(v["evidence"] == "strict" for v in tier_out.values()) else "extended"
    return done({"status": status, "token": token, "tiers": tier_out, "grade": grade, "invariantIssues": issues,
                 "candidates": candidate_info(prep, s2, rob, sides, pred), "h2FloorRule": f"pred >= {H_PRED_REL} x orig pred",
                 "innerLog": {sd: sides[sd]["innerLog"] for sd in ("easy", "hard")}, "innerRule": "robust incl. low-skill point + same-side order majority",
                 "warnings": warn, "predOrig": pcr_o, "orderOk": order_ok, **base})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--next", action="store_true")
    args = ap.parse_args()
    t = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        r = step(args.level, ex)
    print(f"{args.level} {r} {time.time() - t:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
