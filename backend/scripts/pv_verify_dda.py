"""Independent verification of DDA sets — seedvar basis (game IMPL_SPEC §V2-9-2, user decision 2026-10-08).

Main deliverable: seedvar_N = t0 copy map + token "e2|e1|h1|h2" (3 tiers "e2|h2", no base b); the ORIGINAL map
(level_N, unchanged) is the baseline. reference_baked/easy_N, hard_N (e2/h2 baked into explicit tiles) are
reference only (checked for equality with the token assignment and invariants).

Inputs ONLY: selection_dda.json (status, tier keys/tokens, θ and robust points used), the baked row files
(dda_sets/work/<N>/baked_easy.json, baked_hard.json) and source.json (original level_N). The selection logic
(pv_dda.py, pv/evaluate.py, pv/select.py) is NOT imported. Bot runner / stats come from pv_verify_selection.py
(this session's verifier); port (cs_shuffle), map conversion (canonical, t0ize, gboost convert), bot and solver
are imported as allowed.

Checks per level (results saved per stage to <sandbox>/verify_dda/<level>.json):
  ①  Δ vs original reproduced: easy − orig ≥ +0.10, hard − orig ≤ −0.10 at the selection θ pair with a NEW bot
      seed stream (point estimate + z), shrink = Δ_verify / Δ_selection
  ①' direction kept at other θ (selection θ, robust θ and trough excluded) and unused profiles (≥ 2/3 informative)
  ②  order easy > orig > hard (selection θ mean; share of informative points)
  ③  solvability: a bot win here or solver PROVEN_SOLVABLE (node budget) for each baked row
  ④  baked row map == cs_shuffle(t0 map, seed, utc) == dotnet golden (C# client code), for every token tier
  ⑤  invariants vs the original row: all row fields except map/useTileCount/difficulty equal, per-position effect
      and container shape equal (structHash), per-kind ÷3, useTileCount == actual kinds, utc on the allowed side
  (+) editor predictor (mc sweep) with a different seed: hard predicted clear ≥ 0.20, easy > orig > hard

All bot numbers are bot success rates (relative, within a level) — NOT human clear rates.

Usage (from backend/):
  python3 scripts/pv_verify_dda.py --levels 55,123 --workers 4
  python3 scripts/pv_verify_dda.py --all --workers 4          # every level with a variant in selection_dda.json
  python3 scripts/pv_verify_dda.py --report [--levels …] [--out f.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

import pv_verify_selection as V  # noqa: E402  (own verifier: bot runner, stats, θ pool)
from app.api.routes.gboost import _convert_to_townpop_format  # noqa: E402  (import only)
from app.core.pv.canonical import canonical_map, check_layer_continuity, struct_hash  # noqa: E402
from app.core.pv.cs_shuffle import CTile, resolve_map, shuffle_empty_tiles  # noqa: E402
from app.core.pv.t0ize import bot_level_json, original_kinds, t0ize_level  # noqa: E402

SB = V.SB
DDA = os.path.join(SB, "dda_sets")
VDIR = os.path.join(SB, "verify_dda_seedvar")  # v1 (easy/hard rows basis) kept in verify_dda/
VERSION = "pv-verify-dda@2-seedvar"

# bot seed streams: selection used 5e6/6e6/7e6/9.1e6 (+ predictor 4242); seed-variant verification used 3.1e7–4.3e7
SEED_REP, SEED_THETA, SEED_PROF, SEED_PRED = 51_000_000, 52_000_000, 53_000_000, 777_777
GAMES_REP, GAMES_THETA, GAMES_PROF = 600, 300, 300
PROFILES = ("casual", "fast:expert", "optimal")  # selection used AVERAGE / EXPERT
OUTER_MIN = 0.10
H_PRED_MIN = 0.20
SAME_FIELDS_EXCLUDE = {"map", "useTileCount", "difficulty", "id", "_note"}


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def entries(from_work: bool = False) -> Dict[int, Dict[str, Any]]:
    """selection_dda.json levels. from_work=True: the main run's finished work/<N>/final.json fill levels that the
    exported file does not have yet (same fields as the export: status, tiers, thetas, robustPoints, token, utc0)."""
    out = {int(e["level"]): e for e in load(os.path.join(DDA, "selection_dda.json"))["levels"]}
    if from_work:
        wd = os.path.join(DDA, "work")
        for d in sorted(os.listdir(wd)):
            fp = os.path.join(wd, d, "final.json")
            if d.isdigit() and int(d) not in out and os.path.exists(fp):
                try:
                    out[int(d)] = {"level": int(d), "provisional": "work/final.json", **load(fp)}
                except (json.JSONDecodeError, OSError):
                    pass  # being written
    return out


SEGMENTS = ((32, 250), (251, 500), (501, 750), (751, 1000), (1001, 1250), (1251, 1500))
SAMPLE_PER_SEGMENT = 10


def stratified_sample(E: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic stratified sample of finished variant levels: per segment, levels ordered by
    sha256("dda-sample|N") and the first SAMPLE_PER_SEGMENT with a variant are taken (60 max)."""
    import hashlib
    seg_out = {}
    for lo, hi in SEGMENTS:
        fin = sorted((n for n in E if lo <= n <= hi), key=lambda n: hashlib.sha256(f"dda-sample|{n}".encode()).hexdigest())
        var = [n for n in fin if has_variant(E[n])]
        seg_out[f"{lo}-{hi}"] = {"finished": len(fin), "withVariant": len(var), "sample": var[:SAMPLE_PER_SEGMENT]}
    return seg_out


def incremental_pick(E: Dict[int, Dict[str, Any]], lo: int, hi: int, k: int) -> List[int]:
    """Up to k not-yet-verified finished variant levels in [lo, hi]: split the candidates (sorted by level) into k
    contiguous bins and take the first by sha256("dda-inc|N") in each bin (deterministic, spread over the range)."""
    import hashlib
    done = {int(f[:4]) for f in os.listdir(VDIR) if f[:4].isdigit() and f.endswith(".json") and len(f) == 9} \
        if os.path.isdir(VDIR) else set()
    cand = sorted(n for n, e in E.items() if lo <= n <= hi and has_variant(e) and n not in done)
    if not cand:
        return []
    k = min(k, len(cand))
    bins = [cand[i * len(cand) // k:(i + 1) * len(cand) // k] for i in range(k)]
    return [min(b, key=lambda n: hashlib.sha256(f"dda-inc|{n}".encode()).hexdigest()) for b in bins if b]


def has_variant(e: Dict[str, Any]) -> bool:
    return e.get("status") in ("3tier", "5tier") and bool(e.get("token"))


def used_thetas(e: Dict[str, Any]) -> List[float]:
    out = [float(x) for x in e.get("thetas") or []]
    for p in (e.get("robustPoints") or []) + (e.get("judgedPoints") or []):
        if isinstance(p, str) and p.startswith("θ:"):
            out.append(float(p[2:]))
    return out


def row_path(n: int, name: str) -> str:
    """Deliverable row (reference_baked/easy_N.json); falls back to the work copy."""
    p = os.path.join(DDA, "reference_baked", f"{name}_{n}.json")
    return p if os.path.exists(p) else os.path.join(DDA, "work", f"{n:04d}", f"baked_{name}.json")


def orig_row(n: int) -> Dict[str, Any]:
    lj = V.source_level(n)["level_json"]
    from app.core.pv.t0ize import _patch_empty_tiles  # same normalisation the t0-izer applies before converting
    r = _convert_to_townpop_format(_patch_empty_tiles(lj))
    r.pop("etime", None)
    return r


def row_lj(row: Dict[str, Any]) -> Dict[str, Any]:
    m = row["map"] if isinstance(row["map"], dict) else json.loads(row["map"])
    return bot_level_json({"randSeed": 1, "useTileCount": row.get("useTileCount"), "unlockTile": row.get("unlockTile")}, m)


# ───────────────────────────────────────────────────────────── stages
def seedvar_path(n: int) -> Optional[str]:
    for c in (os.path.join(DDA, "seedvar", f"seedvar_{n}.json"), os.path.join(DDA, "work", f"{n:04d}", "seedvar_row.json")):
        if os.path.exists(c):
            return c
    return None


def token_tiers(token: str, utc0: int) -> Dict[str, List[int]]:
    """seedvar token "e2|e1|h1|h2" / "e2|h2" -> {tier: [utc, seed]} (token 'seed' or 'seed@utc')."""
    toks = [x for x in str(token).split("|") if x]
    order = {4: ("e2", "e1", "h1", "h2"), 2: ("e2", "h2")}.get(len(toks))
    if order is None:
        raise ValueError(f"token must have 2 or 4 values: {token!r}")
    out = {}
    for t, tok in zip(order, toks):
        seed, utc = V.parse_token(tok)
        out[t] = [utc or utc0, seed]
    return out


def st_prep(n, e, W):
    lj = V.source_level(n)["level_json"]
    t0 = t0ize_level(lj, 1)
    utc0 = int(t0["row"]["useTileCount"])
    sp = seedvar_path(n)
    sv = load(sp) if sp else None
    token = (sv or {}).get("randSeed") or e.get("token")
    W["prep"] = {"status": e.get("status"), "utc0": utc0, "seedvarFile": os.path.relpath(sp, DDA) if sp else None,
                 "token": token, "tokenMatchesSelection": sv is None or e.get("token") in (None, sv.get("randSeed")),
                 "keys": token_tiers(token, utc0), "thetas": e.get("thetas"), "usedThetas": used_thetas(e),
                 "t0map": t0["row"]["map"],
                 "selDelta": {t: tv.get("delta") for t, tv in (e.get("tiers") or {}).items()},
                 "selPred": {"orig": e.get("predOrig"), **{t: tv.get("predictedClearRate")
                                                          for t, tv in (e.get("tiers") or {}).items()}}}


def _field_issues(name, r, o, skip):
    return [f"{name}.{f}: {r.get(f)!r} != orig {o.get(f)!r}" for f in sorted(set(o) | set(r))
            if f not in skip and str(o.get(f)) != str(r.get(f))]


def st_rows(n, W):
    """⑤ seedvar_N invariants (map = t0 copy, token, fields = original) + reference_baked easy/hard rows
    (= cs_shuffle of the e2/h2 token, invariants). ④-a: reference rows == port recompute."""
    P = W["prep"]
    t0map, utc0 = P["t0map"], P["utc0"]
    o = orig_row(n)
    sh = struct_hash(canonical_map(V.source_level(n)["level_json"]))
    out: Dict[str, Any] = {}
    iss = []
    if not P["seedvarFile"]:
        iss.append("seedvar row missing")
    else:
        sv = load(os.path.join(DDA, P["seedvarFile"]))
        m = sv["map"] if isinstance(sv["map"], dict) else json.loads(sv["map"])
        if m != t0map:
            iss.append("seedvar map != t0ize(original) map")
        if struct_hash(m) != sh:
            iss.append("seedvar structHash != original")
        if str(sv.get("useTileCount")) != str(utc0):
            iss.append(f"seedvar useTileCount {sv.get('useTileCount')} != utc0 {utc0}")
        if sv.get("id") not in (None, f"seedvar_{n}"):
            iss.append(f"seedvar id {sv.get('id')!r}")
        if not P["tokenMatchesSelection"]:
            iss.append("seedvar randSeed != selection token")
        iss += _field_issues("seedvar", sv, o, {"map", "useTileCount", "randSeed", "difficulty", "id", "_note"})
        for t, (u, s) in P["keys"].items():
            allowed = (utc0 - 1, utc0) if t.startswith("e") else (utc0, utc0 + 1)
            if u not in allowed:
                iss.append(f"token {t} utc {u} outside {allowed}")
    out["seedvar"] = {"exists": bool(P["seedvarFile"]), "issues": iss}
    for name, tier in (("easy", "e2"), ("hard", "h2")):
        rp = row_path(n, name)
        if not os.path.exists(rp):
            out[name] = {"exists": False, "issues": []}  # reference only — absence is not a failure
            continue
        r = load(rp)
        m = r["map"] if isinstance(r["map"], dict) else json.loads(r["map"])
        u, s = P["keys"][tier]
        issues = []
        if resolve_map(t0map, shuffle_empty_tiles(t0map, rand_seed=s, use_tile_count=u, strict=True)) != m:
            issues.append(f"reference {name} map != cs_shuffle({tier} token)")
        issues += _field_issues(name, r, o, SAME_FIELDS_EXCLUDE)
        if struct_hash(m) != sh:
            issues.append("structHash differs from original")
        kinds, _, t0left = original_kinds(m)
        if t0left:
            issues.append(f"t0 left: {t0left}")
        if any(v % 3 for v in kinds.values()):
            issues.append("per-kind count not divisible by 3")
        if str(len(kinds)) != str(r.get("useTileCount")):
            issues.append(f"useTileCount {r.get('useTileCount')} != kinds {len(kinds)}")
        if r.get("id") not in (None, f"{name}_{n}"):
            issues.append(f"id {r.get('id')!r}")
        out[name] = {"exists": True, "file": os.path.relpath(rp, DDA), "utc": u, "seed": s,
                     "difficulty": r.get("difficulty"), "issues": issues}
    W["rows"] = out


def st_golden(n, W):
    """④ dotnet C# client code == port for every seedvar token (seed, utc) on the t0 map."""
    P = W["prep"]
    runs = sorted({tuple(v) for v in P["keys"].values()})
    row = {"randSeed": "1", "useTileCount": str(P["utc0"]), "unlockTile": "0", "shuffleTile": "0",
           "typeImbalance": "", "map": P["t0map"]}
    inp = f"/tmp/pv_seedverify_dda_l{n:04d}.json"
    V.save(inp, {"caseId": f"verify_dda_l{n:04d}", "kind": "real", "levelId": f"level_{n}", "dumpRng": False,
                 "note": "pv_verify_dda", "row": row,
                 "runs": [{"randSeed": str(s), "useTileCount": str(u)} for u, s in runs]})
    out = subprocess.run(["dotnet", V.DLL, "case", inp], cwd=REPO, capture_output=True, text=True, timeout=200)
    os.remove(inp)
    if out.returncode != 0:
        W["golden"] = {"ok": False, "error": out.stderr[-400:]}
        return
    exp = json.loads(out.stdout)
    per = {}
    for (u, s), r in zip(runs, exp["results"]):
        got = shuffle_empty_tiles(P["t0map"], rand_seed=s, use_tile_count=u)
        pos = [[x.layer_name, x.pos, -1 if x.inner_index is None else x.inner_index] for x in got.slots]
        nums = [CTile("", "", t, "").tile_id_num for t in got.assigned]
        per[f"{u}:{s}"] = pos == r["positions"] and nums == r["types"] and bool((r.get("selfCheck") or {}).get("ok"))
    W["golden"] = {"ok": all(per.values()), "perKey": per, "distVer": exp.get("distVer")}


def _maps(n, W):
    """orig = original explicit map (baseline, §V2-9-2 ④); token tiers = cs_shuffle on the seedvar t0 map."""
    P = W["prep"]
    m = {"orig": V.orig_lj(n)}
    for t, (u, s) in P["keys"].items():
        res = shuffle_empty_tiles(P["t0map"], rand_seed=s, use_tile_count=u, strict=True)
        m[t] = bot_level_json({"randSeed": str(s), "useTileCount": str(u), "unlockTile": "0"}, resolve_map(P["t0map"], res))
    return m


def st_rep(ex, n, W):
    profs = [f"theta:{t}" for t in W["prep"]["thetas"]]
    W["rep"] = {"seedBase": SEED_REP, "games": GAMES_REP, "results": V.run_games(ex, _maps(n, W), profs, GAMES_REP, SEED_REP)}


def st_gen(ex, n, W):
    pts = V.theta_points(W["prep"]["usedThetas"])
    W["gen"] = {"thetaPoints": pts, "profiles": list(PROFILES), "seedBase": [SEED_THETA, SEED_PROF],
                "theta": V.run_games(ex, _maps(n, W), [f"theta:{t}" for t in pts], GAMES_THETA, SEED_THETA),
                "profile": V.run_games(ex, _maps(n, W), list(PROFILES), GAMES_PROF, SEED_PROF)}


def _solve(a):
    from app.core.solver import solve_level
    t0 = time.time()
    r = solve_level(a["lj"], node_budget=5000, time_budget_s=150.0)
    v = r.get("verdict")
    return {"name": a["name"], "verdict": getattr(v, "value", v), "sec": round(time.time() - t0, 1)}


def st_solv(ex, n, W):
    tiers = list(W["prep"]["keys"])
    wins = {k: 0 for k in tiers}
    for res in (W["rep"]["results"], W["gen"]["theta"], W["gen"]["profile"]):
        for k in tiers:
            wins[k] += sum(p["wins"] for p in res[k].values())
    maps = _maps(n, W)
    need = [k for k, w in wins.items() if w == 0]
    solved = {r["name"]: r for r in ex.map(_solve, [{"name": k, "lj": maps[k]} for k in need])}
    W["solv"] = {k: {"botWins": w, "solver": solved.get(k),
                     "confirmed": w > 0 or (solved.get(k) or {}).get("verdict") == "PROVEN_SOLVABLE"} for k, w in wins.items()}


def _pred(a):
    from app.core.mc_difficulty import sweep_level_task
    r = sweep_level_task({"level_json": a["lj"], "seed": SEED_PRED, "level_number": a["n"]})
    return {"name": a["name"], "pcr": r.get("predicted_clear_rate"), "error": r.get("error")}


def st_pred(ex, n, W):
    maps = _maps(n, W)
    names = ["orig", "e2", "h2"]
    W["pred"] = {r["name"]: {"pcr": r["pcr"], "error": r["error"]}
                 for r in ex.map(_pred, [{"name": k, "lj": maps[k], "n": n} for k in names])}


# ───────────────────────────────────────────────────────────── judgement
TIER_SIGN = {"e2": 1, "e1": 1, "h1": -1, "h2": -1}
ORDER = ("e2", "e1", "orig", "h1", "h2")


def _rate(res, k, profs):
    return sum(res[k][p]["rate"] for p in profs) / len(profs)


def summarize(W) -> Dict[str, Any]:
    P = W["prep"]
    tiers = list(P["keys"])
    S: Dict[str, Any] = {"status": P["status"], "tierCount": len(tiers)}
    rp = [f"theta:{t}" for t in P["thetas"]]
    rep = W["rep"]["results"]
    d = {t: V.diff(rep[t], rep["orig"], rp) for t in tiers}
    rates = {k: _rate(rep, k, rp) for k in ["orig"] + tiers}
    present = [k for k in ORDER if k in rates]
    S["rep"] = {"rates": {k: round(rates[k], 4) for k in present},
                "delta": {t: round(v["d"], 4) for t, v in d.items()}, "z": {t: round(v["z"], 2) for t, v in d.items()},
                "signOk": {t: d[t]["d"] * TIER_SIGN[t] > 0 for t in tiers},
                "outerOk": {t: d[t]["d"] * TIER_SIGN[t] >= OUTER_MIN for t in ("e2", "h2")},
                "orderOk": all(rates[a] > rates[b] for a, b in zip(present, present[1:]))}
    S["rep"]["shrink"] = {t: round(d[t]["d"] / P["selDelta"][t], 3) for t in tiers if P["selDelta"].get(t)}
    pts = [(f"θ{t}", W["gen"]["theta"], f"theta:{t}") for t in W["gen"]["thetaPoints"]]
    pts += [(p, W["gen"]["profile"], p) for p in W["gen"]["profiles"]]
    info, floor = [], []
    for name, res, pr in pts:
        r = {k: res[k][pr]["rate"] for k in ["orig"] + tiers}
        (floor if all(x < V.FLOOR or x > 1 - V.FLOOR for x in r.values()) else info).append((name, r))
    nI = len(info)
    dt = {}
    for t in tiers:
        ds = [r[t] - r["orig"] for _, r in info]
        kept = sum(x * TIER_SIGN[t] > 0 for x in ds)
        flips = min(sum(x > 0 for x in ds), sum(x < 0 for x in ds)) if ds else 0
        spread = (max(ds) - min(ds)) if ds else 0.0
        dt[t] = {"kept": kept, "n": nI, "pass": nI > 0 and kept / nI >= V.DIR_TRUST_FRAC, "spread": round(spread, 3),
                 "signFlips": flips, "sensitive": flips > 0 and spread >= V.SENS_SPREAD_FLIP,
                 "deltas": {nm: round(r[t] - r["orig"], 3) for nm, r in info}}
    inner = {}
    for hi, lo in (("e2", "e1"), ("h1", "h2")):
        if hi in tiers and lo in tiers:
            rev = sum(r[hi] < r[lo] for _, r in info)
            inner[f"{hi}>{lo}"] = {"kept": sum(r[hi] > r[lo] for _, r in info), "reversed": rev, "n": nI,
                                   "unstable": nI > 0 and rev > nI / 2}
    S["gen"] = {"points": [x for x, _ in info], "floor": [x for x, _ in floor], "dirTrust": dt, "inner": inner,
                "orderKept": sum(all(r[a] > r[b] for a, b in zip(present, present[1:])) for _, r in info), "n": nI}
    S["solv"] = {k: v["confirmed"] for k, v in (W.get("solv") or {}).items()}
    S["golden"] = W.get("golden", {}).get("ok")
    S["rowIssues"] = {k: v.get("issues") for k, v in W.get("rows", {}).items()}
    S["invariantsOk"] = bool(W.get("rows", {}).get("seedvar", {}).get("exists")) and all(not v for v in S["rowIssues"].values())
    if "pred" in W:
        p = {k: v["pcr"] for k, v in W["pred"].items()}
        ok = all(isinstance(x, (int, float)) for x in p.values())
        S["pred"] = {"pcr": p, "selPred": P["selPred"], "h2MinOk": ok and p["h2"] >= H_PRED_MIN,
                     "orderOk": ok and p["e2"] > p["orig"] > p["h2"]}
    S["pass"] = bool(all(S["rep"]["outerOk"].values()) and all(S["rep"]["signOk"].values()) and S["rep"]["orderOk"]
                     and all(v["pass"] for v in dt.values()) and all(S["solv"].values()) and S["golden"]
                     and S["invariantsOk"])
    S["outerPass"] = bool(all(S["rep"]["outerOk"].values()) and all(dt[t]["pass"] for t in ("e2", "h2"))
                          and all(S["solv"].values()) and S["golden"] and S["invariantsOk"])
    return S


# ───────────────────────────────────────────────────────────── driver
def step_level(ex, n, e) -> None:
    os.makedirs(VDIR, exist_ok=True)
    path = os.path.join(VDIR, f"{n:04d}.json")
    W = load(path) if os.path.exists(path) else {"level": n, "version": VERSION, "timing": {}}
    sp = seedvar_path(n)
    token_now = (load(sp).get("randSeed") if sp else None) or e.get("token")
    if W.get("done") and W["prep"]["token"] == token_now:
        return
    if W.get("done"):  # token changed -> redo
        os.replace(path, path.replace(".json", f".stale_{int(time.time())}.json"))
        W = {"level": n, "version": VERSION, "timing": {}}
    stages = [("prep", lambda: st_prep(n, e, W)), ("rows", lambda: st_rows(n, W)), ("golden", lambda: st_golden(n, W)),
              ("rep", lambda: st_rep(ex, n, W)), ("gen", lambda: st_gen(ex, n, W)), ("solv", lambda: st_solv(ex, n, W)),
              ("pred", lambda: st_pred(ex, n, W))]
    for name, fn in stages:
        if name in W:
            continue
        t0 = time.time()
        fn()
        W["timing"][name] = round(time.time() - t0, 1)
        V.save(path, json.loads(json.dumps(W)))
        print(f"  L{n} {name} {W['timing'][name]}s", flush=True)
    W["summary"] = summarize(json.loads(json.dumps(W)))
    W["done"] = True
    V.save(path, W)


def report(levels: Optional[List[int]], out: Optional[str]) -> None:
    rows = []
    for f in sorted(os.listdir(VDIR)):
        if not (f.endswith(".json") and f[:4].isdigit() and len(f) == 9):
            continue
        W = load(os.path.join(VDIR, f))
        if not W.get("done") or (levels and W["level"] not in levels):
            continue
        S = summarize(W)
        rows.append({"level": W["level"], "S": S, "sec": sum(W["timing"].values())})
        r, g = S["rep"], S["gen"]
        print(f"L{W['level']:>4} [{S['status']}] W {'/'.join(f'{k}:{v:.3f}' for k, v in r['rates'].items())} "
              f"Δ {' '.join(f'{t}:{v:+.3f}' for t, v in r['delta'].items())} outer≥0.10={r['outerOk']} "
              f"order={'Y' if r['orderOk'] else 'N'} shrink={r['shrink']} | gen "
              f"{' '.join(f'{t}:{v['kept']}/{v['n']}' for t, v in g['dirTrust'].items())} inner={ {k: f'{v['kept']}/{v['n']}' for k, v in g['inner'].items()} } "
              f"sens={[t for t, v in g['dirTrust'].items() if v['sensitive']]} | solv={all(S['solv'].values())} "
              f"golden={S['golden']} inv={S['invariantsOk']} pred={(S.get('pred') or {}).get('pcr')} "
              f"PASS={S['pass']} outerPASS={S['outerPass']}")
        for k, iss in S["rowIssues"].items():
            if iss:
                print(f"      {k} issues: {iss[:4]}")
    def cnt(fn):
        return sum(1 for r in rows if fn(r["S"]))
    agg = {"levels": len(rows), "pass": cnt(lambda S: S["pass"]), "outerPass": cnt(lambda S: S["outerPass"]),
           "5tier": cnt(lambda S: S["tierCount"] == 4), "5tierPass": cnt(lambda S: S["tierCount"] == 4 and S["pass"]),
           "3tier": cnt(lambda S: S["tierCount"] == 2), "3tierPass": cnt(lambda S: S["tierCount"] == 2 and S["pass"]),
           "outerDeltaOk": cnt(lambda S: all(S["rep"]["outerOk"].values())), "orderOk": cnt(lambda S: S["rep"]["orderOk"]),
           "signAll": cnt(lambda S: all(S["rep"]["signOk"].values())),
           "dirTrustByTier": {t: [sum(1 for r in rows if t in r["S"]["gen"]["dirTrust"] and r["S"]["gen"]["dirTrust"][t]["pass"]),
                                  sum(1 for r in rows if t in r["S"]["gen"]["dirTrust"])] for t in ("e2", "e1", "h1", "h2")},
           "innerUnstable": cnt(lambda S: any(v["unstable"] for v in S["gen"]["inner"].values())),
           "sensitive": cnt(lambda S: any(v["sensitive"] for v in S["gen"]["dirTrust"].values())),
           "solvAll": cnt(lambda S: all(S["solv"].values())), "golden": cnt(lambda S: S["golden"]),
           "invariants": cnt(lambda S: S["invariantsOk"]),
           "predH2Min": cnt(lambda S: (S.get("pred") or {}).get("h2MinOk")),
           "predOrder": cnt(lambda S: (S.get("pred") or {}).get("orderOk"))}
    sh = sorted(x for r in rows for x in r["S"]["rep"]["shrink"].values())
    agg["shrinkMedian"] = sh[len(sh) // 2] if sh else None
    print("\nAGG " + json.dumps(agg, ensure_ascii=False))
    if out:
        V.save(out, {"agg": agg, "rows": rows})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", type=str, default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--sample", action="store_true", help="stratified 60-level sample of finished variant levels")
    ap.add_argument("--from-work", action="store_true", help="also read the main run's work/<N>/final.json")
    ap.add_argument("--increment", type=str, default="", help="LO-HI:K -> verify K new stratified levels in [LO,HI]")
    ap.add_argument("--out", type=str, default=None)
    a = ap.parse_args()
    lv = [int(x) for x in a.levels.split(",") if x]
    if a.report:
        report(lv or None, a.out)
        return
    E = entries(a.from_work)
    if a.increment:
        rng, k = a.increment.split(":")
        lo, hi = (int(x) for x in rng.split("-"))
        todo = incremental_pick(E, lo, hi, int(k))
        fin = sum(1 for n in E if lo <= n <= hi)
        var = sum(1 for n, e in E.items() if lo <= n <= hi and has_variant(e))
        print(json.dumps({"range": rng, "finished": fin, "withVariant": var, "picked": todo}), flush=True)
    elif a.sample:
        segs = stratified_sample(E)
        print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "sample"} | {"n": len(v["sample"])}
                          for k, v in segs.items()}, ensure_ascii=False), flush=True)
        os.makedirs(VDIR, exist_ok=True)
        V.save(os.path.join(VDIR, "_sample.json"), {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "segments": segs})
        todo = [n for v in segs.values() for n in v["sample"]]
    else:
        todo = [n for n, e in E.items() if has_variant(e)] if a.all else lv
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for n in todo:
            if n not in E or not has_variant(E[n]):
                print(f"L{n}: no variant ({E.get(n, {}).get('status')})")
                continue
            print(f"[{time.strftime('%H:%M:%S')}] L{n}", flush=True)
            step_level(ex, n, E[n])
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
