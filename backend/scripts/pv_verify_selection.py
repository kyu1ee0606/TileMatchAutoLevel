"""Independent verification of the 5-seed selection (selection_v2.json).

Inputs ONLY: selection_v2.json (seeds, θ used, structHash, utc) + source.json (original level).
Does NOT import the selection logic (pv.evaluate / pv.select / pv_remeasure) to avoid confirmation
bias. Allowed imports: the client port (cs_shuffle), canonical/t0ize helpers (map conversion), the
bot simulator and the solver.

Checks (per level, results saved incrementally to <sandbox>/verify/<level>.json):
  ① rep     : same θ as selection, NEW bot seed stream -> order e2>e1>b>h1>h2, Δ sign vs base, shrink ratio
  ② theta   : other θ points (trough [0.34,0.50) and the selection θ excluded) -> easy/hard direction
  ③ profile : predefined bot profiles (AVERAGE lookahead 2, EXPERT lookahead 5) -> direction
  ④ solv    : bot win in any game here (witness) or solver PROVEN_SOLVABLE (node budget) per seed
  ⑤ golden  : dotnet C# client code (tools/pv_golden, prebuilt dll, `case`) == cs_shuffle port, 5 seeds
  ⑥ tray    : mean max tray occupancy / crisis-game rate vs tier order (Spearman)

All metrics are bot success rates — relative within a level, NOT human clear rates.

Usage (from backend/):
  python3 scripts/pv_verify_selection.py --levels 55 --budget 210 --workers 2
  python3 scripts/pv_verify_selection.py --all-done --budget 210      # every level with seeds in selection_v2
  python3 scripts/pv_verify_selection.py --watch --selection <sb>/selection_v3.json --verify-dir <sb>/verify_v3
  python3 scripts/pv_verify_selection.py --report --selection <sb>/selection_v3.json --verify-dir <sb>/verify_v3
Seed tokens may be "seed" or "seed@utc" (v3 utc±1): each tier is resolved with its own utc; map/result keys
are "seed" (level utc) or "seed@utc".
Each call runs stages until the time budget is used, then exits; re-run to continue (stages are cached).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.mc_difficulty import make_skill_profile  # noqa: E402
from app.core.pv.canonical import canonical_map  # noqa: E402
from app.core.pv.cs_shuffle import CTile, resolve_map, shuffle_empty_tiles  # noqa: E402
from app.core.pv.t0ize import bot_level_json, t0ize_level  # noqa: E402
from app.models.bot_profile import PREDEFINED_PROFILES, BotType, get_profile  # noqa: E402

COPY = "pv_20261002_live3"
SB = os.path.join(BACKEND, "data", "pv_sandbox", COPY)
SELECTION = os.path.join(SB, "selection_v2.json")  # --selection
VDIR = os.path.join(SB, "verify")                   # --verify-dir (use a separate dir per selection version)
VARIANT = "strict"                                  # --variant: v3 files carry strict/relaxed results per level
PRE_EVAL2 = False                                   # --pre-eval2: provisional entries from eval2/final.json (v2 run only)
DLL = os.path.join(REPO, "tools", "pv_golden", "bin", "Debug", "net8.0", "PvGolden.dll")
TIERS = ("e2", "e1", "b", "h1", "h2")  # easy -> hard (expected success rate: descending)
VERSION = "pv-verify@1"

# bot seed streams — selection used 5e6/6e6/7e6 (+θidx*1e4); these never overlap them
SEED_REP, SEED_THETA, SEED_PROF = 31_000_000, 32_000_000, 33_000_000
SEED_SHIFT = 0  # --seed-shift (v4: +10_000_000 -> 41M/42M/43M; selection v4 used 6M/7M/9.1M)
GAMES_REP, GAMES_THETA, GAMES_PROF = 600, 300, 300
CHUNK = 50
THETA_POOL = (0.29, 0.65, 0.85, 1.0, 0.15, 0.55, 0.0)  # preference order; all outside trough [0.34, 0.50)
THETA_MIN_SEP = 0.06                   # skip pool θ within this distance of a selection θ
PROFILES = ("average", "expert")        # default (v2/v3 runs). AVERAGE: lookahead 2 / EXPERT: lookahead 5
# --profiles for v4: profiles the selection did not use. "fast:<type>" = FAST_VERIFICATION_PROFILES
# (e.g. fast:expert = EXPERT params with lookahead 2), "optimal" = lookahead 10 / patience 1.0.
SOLVER_NODES, SOLVER_TIME_CAP = 5000, 150.0
Z95 = 1.96
FLOOR = 0.02                             # all 5 rates <FLOOR or >1-FLOOR at a point -> uninformative


# ───────────────────────────────────────────────────────────── io
def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


_SRC: Optional[Dict[int, Any]] = None


def source_level(level: int) -> Dict[str, Any]:
    global _SRC
    if _SRC is None:
        _SRC = {lv["meta"]["level_number"]: lv for lv in load(os.path.join(SB, "source.json"))["levels"]}
    return _SRC[level]


def selection_entries(pre: bool = False) -> Dict[int, Dict[str, Any]]:
    """Levels from selection_v2.json. pre=True: for levels still `not_finished` there, build a provisional
    entry from the selection run's own output eval2/<lv>/final.json (seeds/θ only) so verification can start
    early; once selection_v2.json has the level, is_stale() re-checks seeds/structHash against it."""
    sel = load(SELECTION)
    if sel.get("format") == "pv_selection_v4":
        return {e["level"]: v4_entry(e) for e in sel["levels"]}
    if sel.get("format") == "pv_selection_v3":
        return {e["level"]: v3_entry(e, VARIANT) for e in sel["levels"]}
    out = {e["level"]: e for e in sel["levels"]}
    if pre and PRE_EVAL2:
        for lv, e in out.items():
            if e.get("status") != "not_finished":
                continue
            d = os.path.join(SB, "eval2", f"{lv:04d}")
            fp = os.path.join(d, "final.json")
            if not os.path.exists(fp):
                continue
            fin = load(fp)
            if fin.get("status") != "ok":
                continue
            prep = load(os.path.join(d, "prep.json"))
            sd = {t: int(v) for t, v in dict(fin["sel"]["seeds"]).items()}
            out[lv] = {"level": lv, "structHash": prep["meta"]["structHash"], "utc": prep["meta"]["utc0"],
                       "status": "ok", "provisional": True, "thetas": fin["thetas"],
                       "base": {"seed": sd["b"]}, "tiers": {t: {"seed": sd[t]} for t in ("e2", "e1", "h1", "h2")},
                       "randSeedA": "|".join(str(sd[t]) for t in ("b", "e2", "e1", "h1", "h2")),
                       "deploy": "randSeed_A_string"}
    return out


A_ORDER = ("b", "e2", "e1", "h1", "h2")
A_ORDER3 = ("b", "e2", "h2")  # 3-tier deployment (v4)


def v4_entry(e: Dict[str, Any]) -> Dict[str, Any]:
    """pv_selection_v4 level -> v2-shaped entry. 3tier = b|e2|h2, 5tier = b|e2|e1|h1|h2. θ = selectionThetas;
    `usedThetas` = every θ the selection measured (selection + robust points) — excluded from ② here."""
    m = e.get("measurement") or {}
    out = {"level": e["level"], "structHash": e.get("structHash"), "utc": e.get("utc0"), "status": e.get("status")}
    if e.get("status") not in ("3tier", "5tier") or not e.get("base"):
        return out
    used = list(m.get("selectionThetas") or [])
    used += [float(x[2:]) for x in m.get("robustPoints") or [] if str(x).startswith("θ:")]
    out.update(status="ok", tierCount=e.get("tierCount"), base=e["base"], tiers=e.get("tiers") or {},
               thetas=m.get("selectionThetas"), usedThetas=used,
               usedProfiles=[x[8:] for x in m.get("robustPoints") or [] if str(x).startswith("profile:")],
               randSeedA=e.get("randSeedA"), deploy=e.get("deploy"), baseMode=e.get("baseMode"))
    return out


def v3_entry(e: Dict[str, Any], variant: str) -> Dict[str, Any]:
    """Normalise a pv_selection_v3 level (with `strict`/`relaxed` sub-results) to the v2-shaped entry used here.
    Level utc = utc0; per-tier utc comes from tiers.<t>.utc (seed@utc when != utc0). θ = keys of b.perTheta."""
    sub = e.get(variant) or {}
    out = {"level": e["level"], "structHash": e.get("structHash"), "utc": e.get("utc0"),
           "status": e.get("status"), "variant": variant}
    t = sub.get("tiers") or {}
    if not (sub.get("ok") and t.get("b")):
        out["status"] = f"{variant}_not_ok({e.get('status')})"
        return out
    out.update(status="ok", base=t["b"], tiers={k: t[k] for k in ("e2", "e1", "h1", "h2") if k in t},
               thetas=[float(x) for x in (t["b"].get("perTheta") or {})] or e.get("thetas"),
               randSeedA=sub.get("randSeedA"), deploy="randSeed_A_string", flexUsed=sub.get("flexUsed"))
    return out


def parse_token(v: Any, utc_field: Any = None) -> Tuple[int, Optional[int]]:
    """Seed token -> (seed, utc|None). Accepts int, "123", "123@11" (v3 utc±1 tokens) and an explicit utc field."""
    seed_s, _, utc_s = str(v).strip().partition("@")
    utc = int(utc_s) if utc_s else (int(utc_field) if utc_field not in (None, "") else None)
    return int(seed_s), utc


def make_key(seed: int, utc: Optional[int], level_utc: Any) -> str:
    """Map key per tier: "seed" when the tier uses the level utc, else "seed@utc" (backward compatible)."""
    if utc is None or (level_utc not in (None, "") and int(level_utc) == utc):
        return str(seed)
    return f"{seed}@{utc}"


def split_key(key: Any) -> Tuple[int, Optional[int]]:
    return parse_token(key)


def tier_seeds(entry: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """{tier: key} with key = "seed" or "seed@utc"; missing tier -> None.
    Per-tier utc comes from the tier's `utc` field or a "seed@utc" token; tiers absent from `base`/`tiers`
    are filled from the randSeedA string (A-plan order b|e2|e1|h1|h2) when it has 5 tokens."""
    lu = entry.get("utc")
    out: Dict[str, Optional[str]] = {t: None for t in TIERS}
    if entry.get("base"):
        out["b"] = make_key(*parse_token(entry["base"]["seed"], entry["base"].get("utc")), lu)
    for t, v in (entry.get("tiers") or {}).items():
        if t in out and v and v.get("seed") is not None:
            out[t] = make_key(*parse_token(v["seed"], v.get("utc")), lu)
    toks = str(entry.get("randSeedA") or "").split("|")
    order = A_ORDER if len(toks) == 5 else A_ORDER3 if len(toks) == 3 else ()
    if all(toks):
        for t, tok in zip(order, toks):
            if out[t] is None:
                out[t] = make_key(*parse_token(tok), lu)
    return out


def a_string_ok(seeds: Dict[str, Optional[str]], entry: Dict[str, Any]) -> bool:
    """randSeedA tokens == tier keys (tokens normalised the same way)."""
    toks = str(entry.get("randSeedA") or "").split("|")
    order = A_ORDER if len(toks) == 5 else A_ORDER3 if len(toks) == 3 else None
    if order is None:
        return False
    if any(seeds[t] is not None for t in TIERS if t not in order):  # 3-token string but 5 tiers present
        return False
    lu = entry.get("utc")
    return [make_key(*parse_token(x), lu) for x in toks] == [None if seeds[t] is None else str(seeds[t]) for t in order]


# ───────────────────────────────────────────────────────────── maps
def resolved_lj(row: Dict[str, Any], key: Any) -> Dict[str, Any]:
    seed, utc = split_key(key)
    utc = utc if utc is not None else int(row["useTileCount"])
    res = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=utc, strict=True)
    return bot_level_json({**row, "randSeed": str(seed), "useTileCount": str(utc)}, resolve_map(row["map"], res))


def orig_lj(level: int) -> Dict[str, Any]:
    lj = source_level(level)["level_json"]
    return bot_level_json({"randSeed": lj.get("randSeed") or 1, "useTileCount": lj.get("useTileCount") or 6,
                           "unlockTile": 0}, canonical_map(lj))


# ───────────────────────────────────────────────────────────── bot runner (own; not pv.evaluate)
class _TrayBot(BotSimulator):
    """Tray occupancy sampled once per turn through `_update_curtain_memory` (called once per turn
    at the top of `_play_game`)."""

    def begin(self):
        self.mx = 0
        self.crisis = 0

    def _update_curtain_memory(self, state, profile):
        occ = len(state.dock_tiles)
        self.mx = max(self.mx, occ)
        if occ >= state.max_dock_slots - 1:
            self.crisis += 1
        return super()._update_curtain_memory(state, profile)


def _profile(spec: str):
    if spec.startswith("theta:"):
        return make_skill_profile(float(spec[6:]))
    if spec.startswith("fast:"):
        return get_profile(BotType(spec[5:]), fast_mode=True)
    return PREDEFINED_PROFILES[BotType(spec)]


def v_profiles(V) -> List[str]:
    return list((V.get("profile") or {}).get("profiles") or PROFILES)


def games_task(a: Dict[str, Any]) -> Dict[str, Any]:
    bot = _TrayBot()
    prof = _profile(a["profile"])
    lj = a["lj"]
    base = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(base)
    wins, mx, cr = [], [], []
    for i in range(a["start"], a["start"] + a["count"]):
        bot._rng.seed(a["seed_base"] + i)
        bot.begin()
        final = bot._play_game(bot._fast_copy_state(base), prof)
        bot.mx = max(bot.mx, len(final.dock_tiles))
        wins.append(1 if final.cleared else 0)
        mx.append(bot.mx)
        cr.append(1 if bot.crisis > 0 else 0)
    return {"key": a["key"], "profile": a["profile"], "start": a["start"], "wins": wins, "mx": mx, "cr": cr}


def run_games(ex, maps: Dict[str, Dict[str, Any]], profiles: Sequence[str], n: int, seed_base: int):
    """Game i of profile index p uses bot seed seed_base + p*100000 + i (same across maps)."""
    futs = [ex.submit(games_task, {"key": k, "profile": pr, "lj": lj, "seed_base": seed_base + p * 100_000,
                                   "start": s, "count": min(CHUNK, n - s)})
            for k, lj in maps.items() for p, pr in enumerate(profiles) for s in range(0, n, CHUNK)]
    acc: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for f in futs:
        r = f.result()
        acc.setdefault(r["key"], {}).setdefault(r["profile"], []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for k, per in acc.items():
        out[k] = {}
        for pr, parts in per.items():
            parts.sort(key=lambda x: x["start"])
            w = [x for p in parts for x in p["wins"]]
            m = [x for p in parts for x in p["mx"]]
            c = [x for p in parts for x in p["cr"]]
            out[k][pr] = {"n": len(w), "wins": sum(w), "rate": sum(w) / len(w),
                          "trayMaxMean": sum(m) / len(m), "crisisRate": sum(c) / len(c)}
    return out


# ───────────────────────────────────────────────────────────── stats (independent two-sample)
def mean_rate(res: Dict[str, Any], profiles: Sequence[str]) -> float:
    return sum(res[p]["rate"] for p in profiles) / len(profiles)


def diff(a: Dict[str, Any], b: Dict[str, Any], profiles: Sequence[str]) -> Dict[str, float]:
    """Δ = mean_p(rate_a) - mean_p(rate_b); SE from independent binomials."""
    T = len(profiles)
    d = mean_rate(a, profiles) - mean_rate(b, profiles)
    var = sum(a[p]["rate"] * (1 - a[p]["rate"]) / a[p]["n"] + b[p]["rate"] * (1 - b[p]["rate"]) / b[p]["n"]
              for p in profiles) / (T * T)
    se = math.sqrt(var)
    return {"d": d, "se": se, "z": d / se if se > 0 else (0.0 if d == 0 else math.copysign(math.inf, d))}


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return None if sxx == 0 or syy == 0 else sxy / math.sqrt(sxx * syy)


def direction_block(res: Dict[str, Dict[str, Any]], seeds: Dict[str, Optional[int]], profiles: Sequence[str]):
    """Per tier vs base: Δ, z, sign-ok; adjacent order; informativeness."""
    present = [t for t in TIERS if seeds[t] is not None]
    key = {t: str(seeds[t]) for t in present}
    rates = {t: mean_rate(res[key[t]], profiles) for t in present}
    informative = not all(r < FLOOR or r > 1 - FLOOR for r in rates.values())
    vs_base = {}
    for t in present:
        if t == "b" or seeds[t] == seeds["b"]:
            continue
        dd = diff(res[key[t]], res[key["b"]], profiles)
        want = 1 if t.startswith("e") else -1
        vs_base[t] = {**{k: round(v, 4) for k, v in dd.items()}, "signOk": dd["d"] * want > 0,
                      "sigOk": dd["z"] * want > Z95}
    distinct = [t for i, t in enumerate(present) if i == 0 or seeds[t] != seeds[present[i - 1]]]
    adj = []
    for a, b in zip(distinct, distinct[1:]):
        dd = diff(res[key[a]], res[key[b]], profiles)
        adj.append({"pair": f"{a}>{b}", "d": round(dd["d"], 4), "z": round(dd["z"], 2), "ok": dd["d"] > 0})
    return {"profiles": list(profiles), "rates": {t: round(r, 4) for t, r in rates.items()},
            "informative": informative, "vsBase": vs_base, "adjacent": adj,
            "orderKept": all(x["ok"] for x in adj)}


# ───────────────────────────────────────────────────────────── stages
def st_prep(level, entry, V):
    lj = source_level(level)["level_json"]
    seeds = tier_seeds(entry)
    t = t0ize_level(lj, split_key(seeds["b"])[0])
    row = t["row"]
    V["prep"] = {
        "seeds": seeds, "row": row,
        "structHashOk": t["meta"]["structHash"] == entry.get("structHash"),
        "utcOk": int(row["useTileCount"]) == int(entry.get("utc", -1)),
        "aStringOk": a_string_ok(seeds, entry),
        "tierUtc": {k: (split_key(v)[1] or int(row["useTileCount"])) if v else None for k, v in seeds.items()},
        "selThetas": entry.get("thetas"),
        "excludeThetas": entry.get("usedThetas") or entry.get("thetas"),
        "selProfiles": entry.get("usedProfiles"),
        "selStructHash": entry.get("structHash"),
        "selStatus": entry.get("status"),
    }


def st_golden(level, V):
    row, seeds = V["prep"]["row"], V["prep"]["seeds"]
    uniq = sorted({s for s in seeds.values() if s is not None}, key=str)
    inp = f"/tmp/pv_verify_l{level:04d}.json"
    save(inp, {"caseId": f"verify_l{level:04d}", "kind": "real", "levelId": f"level_{level}", "dumpRng": False,
               "note": "pv_verify_selection", "row": row, "runs": [{"randSeed": str(split_key(s)[0]),
                                                          "useTileCount": str(split_key(s)[1] or row["useTileCount"])}
                                                         for s in uniq]})
    out = subprocess.run(["dotnet", DLL, "case", inp], cwd=REPO, capture_output=True, text=True, timeout=200)
    os.remove(inp)
    if out.returncode != 0:
        V["golden"] = {"ok": False, "error": out.stderr[-400:]}
        return
    exp = json.loads(out.stdout)
    per = {}
    for s, r in zip(uniq, exp["results"]):
        sd, su = split_key(s)
        got = shuffle_empty_tiles(row["map"], rand_seed=sd, use_tile_count=su or row["useTileCount"])
        pos = [[x.layer_name, x.pos, -1 if x.inner_index is None else x.inner_index] for x in got.slots]
        nums = [CTile("", "", tid, "").tile_id_num for tid in got.assigned]
        per[str(s)] = {"match": pos == r["positions"] and nums == r["types"], "n": len(nums),
                       "selfCheckOk": (r.get("selfCheck") or {}).get("ok")}
    V["golden"] = {"ok": all(v["match"] and v["selfCheckOk"] for v in per.values()), "perSeed": per,
                   "distVer": exp.get("distVer"), "authority": exp.get("authority"),
                   "dllMtime": os.path.getmtime(DLL)}


def _maps(V, with_orig=False):
    row, seeds = V["prep"]["row"], V["prep"]["seeds"]
    m = {str(s): resolved_lj(row, s) for s in sorted({s for s in seeds.values() if s is not None}, key=str)}
    if with_orig:
        m["orig"] = orig_lj(V["level"])
    return m


def theta_points(sel_thetas: Sequence[float]) -> List[float]:
    """Up to 3 points from THETA_POOL (preference order) at least THETA_MIN_SEP from every θ the selection used."""
    return [t for t in THETA_POOL if all(abs(t - s) >= THETA_MIN_SEP for s in sel_thetas)][:3]


def st_rep(ex, V):
    profs = [f"theta:{t}" for t in V["prep"]["selThetas"]]
    V["rep"] = {"games": GAMES_REP, "seedBase": SEED_REP + SEED_SHIFT,
                "results": run_games(ex, _maps(V, with_orig=True), profs, GAMES_REP, SEED_REP + SEED_SHIFT)}


def st_theta(ex, V):
    pts = theta_points(V["prep"].get("excludeThetas") or V["prep"]["selThetas"])
    V["theta"] = {"points": pts, "games": GAMES_THETA, "seedBase": SEED_THETA + SEED_SHIFT,
                  "results": run_games(ex, _maps(V), [f"theta:{t}" for t in pts], GAMES_THETA, SEED_THETA + SEED_SHIFT)}


def st_profile(ex, V):
    V["profile"] = {"games": GAMES_PROF, "seedBase": SEED_PROF + SEED_SHIFT, "profiles": list(PROFILES),
                    "results": run_games(ex, _maps(V), list(PROFILES), GAMES_PROF, SEED_PROF + SEED_SHIFT)}


def _solve(a):
    from app.core.solver import solve_level
    t0 = time.time()
    r = solve_level(a["lj"], node_budget=SOLVER_NODES, time_budget_s=SOLVER_TIME_CAP)
    v = r.get("verdict")
    return {"seed": a["seed"], "verdict": getattr(v, "value", v), "nodes": r.get("nodes_expanded"),
            "sec": round(time.time() - t0, 1)}


def st_solv(ex, V):
    wins = {}
    for stage in ("rep", "theta", "profile"):
        for k, per in V[stage]["results"].items():
            if k != "orig":
                wins[k] = wins.get(k, 0) + sum(p["wins"] for p in per.values())
    need = [k for k, w in wins.items() if w == 0]
    maps = _maps(V)
    solved = {r["seed"]: r for r in ex.map(_solve, [{"seed": k, "lj": maps[k]} for k in need])}
    V["solv"] = {k: {"botWins": w, "solver": solved.get(k),
                     "confirmed": w > 0 or (solved.get(k) or {}).get("verdict") == "PROVEN_SOLVABLE"}
                 for k, w in wins.items()}


def summarize(V, entry):
    seeds = V["prep"]["seeds"]
    rep = V["rep"]["results"]
    rp = [f"theta:{t}" for t in V["prep"]["selThetas"]]
    S: Dict[str, Any] = {"rep": direction_block(rep, seeds, rp)}
    # shrink ratio vs selection Δ (tier vs base)
    shrink = {}
    for t, v in S["rep"]["vsBase"].items():
        d_sel = (entry.get("tiers") or {}).get(t, {}).get("deltaVsBase")
        if d_sel:
            shrink[t] = round(v["d"] / d_sel, 3)
    S["rep"]["shrinkVsSelection"] = shrink
    S["rep"]["baseVsOrig"] = {k: round(v, 4) for k, v in diff(rep[str(seeds["b"])], rep["orig"], rp).items()}
    S["rep"]["perPoint"] = {p: direction_block(rep, seeds, [p]) for p in rp}
    if "theta" in V:
        S["theta"] = {f"theta:{t}": direction_block(V["theta"]["results"], seeds, [f"theta:{t}"])
                      for t in V["theta"]["points"]}
    if "profile" in V:
        S["profile"] = {p: direction_block(V["profile"]["results"], seeds, [p]) for p in v_profiles(V)}
    if "solv" in V:
        S["solv"] = {t: V["solv"][str(seeds[t])]["confirmed"] for t in TIERS if seeds[t] is not None}
    # ⑥ tray: tier rank (0=e2 easiest .. 4=h2) vs pooled rep tray metrics
    present = [t for t in TIERS if seeds[t] is not None]
    rank = [TIERS.index(t) for t in present]
    tm = [sum(rep[str(seeds[t])][p]["trayMaxMean"] for p in rp) / len(rp) for t in present]
    cr = [sum(rep[str(seeds[t])][p]["crisisRate"] for p in rp) / len(rp) for t in present]
    S["tray"] = {"trayMaxMean": dict(zip(present, [round(x, 3) for x in tm])),
                 "crisisRate": dict(zip(present, [round(x, 3) for x in cr])),
                 "rhoTrayMax": spearman(rank, tm), "rhoCrisis": spearman(rank, cr)}
    S["golden"] = V.get("golden", {}).get("ok")
    a_ok = V["prep"]["aStringOk"]
    if entry.get("randSeedA"):
        a_ok = a_string_ok(seeds, entry)
    S["inputsOk"] = bool(V["prep"]["structHashOk"] and V["prep"]["utcOk"] and a_ok)
    S["provisional"] = bool(entry.get("provisional")) or not entry.get("tiers")
    if "theta" in V and "profile" in V:
        S["judge"] = judge(V)
    return S


# ───────────────────────────────────────────────────────────── 2-layer judgement (mother decision 2026-10-02)
DIR_TRUST_FRAC = 2 / 3      # (a) tier direction vs base kept at >= this share of informative gen points
SENS_SPREAD_FLIP = 0.15     # skill-sensitive tier: Δ-vs-base changes sign across gen points AND range >= this


def gen_points(V) -> List[tuple]:
    """(name, results, profile) for every generalization point: other θ + predefined profiles."""
    pts = [(f"θ{t}", V["theta"]["results"], f"theta:{t}") for t in V["theta"]["points"]]
    pts += [(p, V["profile"]["results"], p) for p in v_profiles(V)]
    return pts


def judge(V) -> Dict[str, Any]:
    seeds = V["prep"]["seeds"]
    rates_at = []  # [(name, {tier: rate})] informative points only
    floor_pts = []
    for name, res, pr in gen_points(V):
        r = {t: res[str(s)][pr]["rate"] for t, s in seeds.items() if s is not None}
        if all(x < FLOOR or x > 1 - FLOOR for x in r.values()):
            floor_pts.append(name)
        else:
            rates_at.append((name, r))
    n = len(rates_at)
    # (a) direction trust per tier
    dir_a: Dict[str, Any] = {}
    sens: Dict[str, Any] = {}
    for t in ("e2", "e1", "h1", "h2"):
        if seeds[t] is None or seeds[t] == seeds["b"]:
            continue
        want = 1 if t.startswith("e") else -1
        ds = [r[t] - r["b"] for _, r in rates_at]
        kept = sum(1 for d in ds if d * want > 0)
        dir_a[t] = {"kept": kept, "n": n, "pass": n > 0 and kept / n >= DIR_TRUST_FRAC}
        if ds:
            pos, neg = sum(d > 0 for d in ds), sum(d < 0 for d in ds)
            spread = max(ds) - min(ds)
            mean = sum(ds) / len(ds)
            sd = math.sqrt(sum((d - mean) ** 2 for d in ds) / len(ds))
            flips = min(pos, neg)
            sens[t] = {"deltas": {nm: round(d, 3) for (nm, _), d in zip(rates_at, ds)},
                       "spread": round(spread, 3), "sd": round(sd, 3), "signFlips": flips,
                       "sensitive": flips > 0 and spread >= SENS_SPREAD_FLIP}
    # (b) inner order stability on the same side
    inner: Dict[str, Any] = {}
    for hi, lo in (("e2", "e1"), ("h1", "h2")):
        if seeds[hi] is None or seeds[lo] is None or seeds[hi] == seeds[lo] or seeds["b"] in (seeds[hi], seeds[lo]):
            continue
        kept = sum(1 for _, r in rates_at if r[hi] > r[lo])
        rev = sum(1 for _, r in rates_at if r[hi] < r[lo])
        unstable = n > 0 and rev > n / 2
        if not unstable:
            action = None
        elif rev >= DIR_TRUST_FRAC * n:
            action = "swap"            # reversed consistently -> exchange the two seeds
        else:
            action = "collapse"        # no consistent order -> keep one stage on that side
        inner[f"{hi}>{lo}"] = {"kept": kept, "reversed": rev, "n": n, "unstable": unstable, "action": action}
    both_sides = all(seeds[t] is not None and seeds[t] != seeds["b"] for t in ("e2", "h2"))
    present = [s for s in seeds.values() if s is not None]
    return {"points": [nm for nm, _ in rates_at], "floorPoints": floor_pts, "dirTrust": dir_a,
            "dirTrustAll": bool(dir_a) and all(v["pass"] for v in dir_a.values()),
            "inner": inner, "innerStable": all(not v["unstable"] for v in inner.values()),
            "skillSens": sens, "sensTiers": [t for t, v in sens.items() if v["sensitive"]],
            "bidirectional": both_sides,
            "fiveDistinct": len(set(present)) == 5, "allDistinct": len(set(present)) == len(present),
            "tierCount": len(present)}


# ───────────────────────────────────────────────────────────── driver
def is_stale(V, entry) -> bool:
    """Verified seeds/structHash differ from the current selection entry."""
    seeds_now = {t: s for t, s in tier_seeds(entry).items()}
    seeds_then = {t: (None if s is None else str(s)) for t, s in V["prep"]["seeds"].items()}
    sh_then = V["prep"].get("selStructHash", entry.get("structHash"))  # older files: structHashOk covered it
    return seeds_now != seeds_then or sh_then != entry.get("structHash") or not V["prep"]["structHashOk"]


def remeasure_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "pv_remeasure|pv_chain|pv_selection_export|pv_utcflex"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def watch(max_workers: int, low_workers: int) -> None:
    """Verify every level as soon as selection_v2 has seeds for it; re-read the file between levels.
    Uses `low_workers` while the selection run (pv_remeasure / pv_chain) is alive, else `max_workers`.
    Exits when the selection run has ended and every seeded level is verified against the current file."""
    vdir = VDIR
    while True:
        running = remeasure_running()
        entries = selection_entries(pre=True)
        todo = []
        for lv, e in entries.items():
            if not e.get("base") or not e.get("tiers"):  # nothing to compare against base
                continue
            p = os.path.join(vdir, f"{lv:04d}.json")
            if not os.path.exists(p):
                todo.append(lv)
                continue
            V = load(p)
            if not V.get("done") or ("prep" in V and is_stale(V, e)):
                todo.append(lv)
        if not todo:
            if not running:
                print(f"WATCH DONE {time.strftime('%H:%M:%S')}", flush=True)
                return
            time.sleep(60)
            continue
        w = low_workers if running else max_workers
        todo.sort(key=lambda x: entries[x].get("deploy") != "randSeed_A_string")  # deployable (A-plan) first
        lv = todo[0]
        print(f"[{time.strftime('%H:%M:%S')}] L{lv} workers={w} (remeasure running={running}, todo={len(todo)})",
              flush=True)
        with ProcessPoolExecutor(max_workers=w) as ex:
            step_level(ex, lv, entries[lv], time.time() + 10 ** 6)


def step_level(ex, level, entry, deadline) -> bool:
    """Run stages until done or deadline. Returns True when the level is complete."""
    vdir = VDIR
    os.makedirs(vdir, exist_ok=True)
    path = os.path.join(vdir, f"{level:04d}.json")
    V = load(path) if os.path.exists(path) else {"level": level, "version": VERSION, "timing": {}}
    if "prep" in V and is_stale(V, entry):
        os.replace(path, path.replace(".json", f".stale_{int(time.time())}.json"))
        print(f"  L{level} selection changed (seeds/structHash) -> re-verify", flush=True)
        V = {"level": level, "version": VERSION, "timing": {}}
    if V.get("done"):
        return True
    stages = [("prep", lambda: st_prep(level, entry, V)), ("golden", lambda: st_golden(level, V)),
              ("rep", lambda: st_rep(ex, V)), ("theta", lambda: st_theta(ex, V)),
              ("profile", lambda: st_profile(ex, V)), ("solv", lambda: st_solv(ex, V))]
    for name, fn in stages:
        if name in V:
            continue
        if time.time() > deadline:
            return False
        t0 = time.time()
        fn()
        V["timing"][name] = round(time.time() - t0, 1)
        save(path, V)
        print(f"  L{level} {name} {V['timing'][name]}s", flush=True)
    V["summary"] = summarize(V, entry)
    V["done"] = True
    save(path, V)
    return True


def report(out_json: Optional[str] = None) -> None:
    """Recompute summaries from raw results (current selection entry) and print a compact table."""
    vdir = VDIR
    entries = selection_entries()
    rows = []
    for f in sorted(os.listdir(vdir)):
        if not (f.endswith(".json") and f[:4].isdigit() and len(f) == 9):
            continue
        V = load(os.path.join(vdir, f))
        if not V.get("done"):
            continue
        e = entries.get(V["level"], {})
        stale = bool(e.get("base")) and is_stale(V, e)
        S = summarize(V, e if e.get("base") else {})
        rows.append({"level": V["level"], "stale": stale, "S": S, "sec": sum(V["timing"].values()),
                     "selStatus": e.get("status")})
    agg: Dict[str, Any] = {"levels": len(rows), "bidir5": 0, "aPassBidir5": 0, "innerStableBidir5": 0,
                           "orderKept": 0, "tierSign": [0, 0], "tierSig": 0, "shrink": [],
                           "tierA": {}, "inner": [0, 0], "sensTiers": 0, "tiers": 0,
                           "solv": [0, 0], "hardSolv": [0, 0], "golden": 0, "inputs": 0, "trayPos": 0}
    for r in rows:
        S, J = r["S"], r["S"]["judge"]
        rep = S["rep"]
        agg["orderKept"] += rep["orderKept"]
        agg["golden"] += bool(S["golden"])
        agg["inputs"] += bool(S["inputsOk"])
        agg["trayPos"] += (S["tray"]["rhoTrayMax"] or 0) > 0
        for v in rep["vsBase"].values():
            agg["tierSign"][1] += 1
            agg["tierSign"][0] += v["signOk"]
            agg["tierSig"] += v["sigOk"]
        agg["shrink"] += list(rep["shrinkVsSelection"].values())
        for t, v in J["dirTrust"].items():
            a = agg["tierA"].setdefault(t, [0, 0])
            a[0] += v["pass"]
            a[1] += 1
        for v in J["inner"].values():
            agg["inner"][1] += 1
            agg["inner"][0] += not v["unstable"]
        agg["tiers"] += len(J["skillSens"])
        agg["sensTiers"] += len(J["sensTiers"])
        for t, ok in (S.get("solv") or {}).items():
            agg["solv"][1] += 1
            agg["solv"][0] += ok
            if t.startswith("h"):
                agg["hardSolv"][1] += 1
                agg["hardSolv"][0] += ok
        tc = J.get("tierCount", 5)
        g = agg.setdefault("byTierCount", {}).setdefault(str(tc), {"levels": 0, "aAll": 0, "innerStable": 0,
                                                                   "outerA": 0, "orderKept": 0, "solvAll": 0})
        g["levels"] += 1
        g["aAll"] += J["dirTrustAll"]
        g["innerStable"] += J["innerStable"]
        g["outerA"] += all(J["dirTrust"].get(t, {}).get("pass") for t in ("e2", "h2"))
        g["orderKept"] += rep["orderKept"]
        g["solvAll"] += all((S.get("solv") or {}).values())
        outer = {t: abs(rep["vsBase"][t]["d"]) for t in ("e2", "h2") if t in rep["vsBase"]}
        agg.setdefault("outerAbsDelta", []).extend(round(v, 3) for v in outer.values())
        small = [f"{t}:{v:.3f}" for t, v in outer.items() if v < 0.08]
        if small:
            agg.setdefault("outerBelow008", []).append(f"L{r['level']} " + " ".join(small))
        bid5 = J["bidirectional"] and J["fiveDistinct"]
        if bid5:
            agg["bidir5"] += 1
            agg["aPassBidir5"] += J["dirTrustAll"]
            agg["innerStableBidir5"] += J["innerStable"]
        print(f"L{r['level']:>4}{' STALE' if r['stale'] else ''} [{r['selStatus']}] "
              f"rep {' '.join(f'{t}:{v:.3f}' for t, v in rep['rates'].items())} order={'Y' if rep['orderKept'] else 'N'} "
              f"Δb={' '.join(f'{t}:{v['d']:+.3f}(z{v['z']:.1f})' for t, v in rep['vsBase'].items())} "
              f"shrink={rep['shrinkVsSelection']} b-orig={rep['baseVsOrig']['d']:+.3f}")
        print(f"      (a) {' '.join(f'{t}:{v['kept']}/{v['n']}{'✓' if v['pass'] else '✗'}' for t, v in J['dirTrust'].items())} "
              f"(b) {' '.join(f'{k}:{v['kept']}/{v['n']}{'!' + v['action'] if v['unstable'] else ''}' for k, v in J['inner'].items())} "
              f"sens {' '.join(f'{t}:{v['spread']}' for t, v in J['skillSens'].items())} flag={J['sensTiers']} "
              f"floor={J['floorPoints']}")
        print(f"      solv={S.get('solv')} trayρ={S['tray']['rhoTrayMax']} crisisρ={S['tray']['rhoCrisis']} "
              f"golden={S['golden']} inputs={S['inputsOk']} t={r['sec']:.0f}s")
    od = sorted(agg.get("outerAbsDelta", []))
    if od:
        agg["outerAbsDeltaQ"] = {"min": od[0], "q25": od[len(od) // 4], "median": od[len(od) // 2],
                                 "q75": od[3 * len(od) // 4], "max": od[-1]}
    sh = sorted(agg["shrink"])
    agg["shrinkMedian"] = sh[len(sh) // 2] if sh else None
    print("\nAGG " + json.dumps({k: v for k, v in agg.items() if k != "shrink"}, ensure_ascii=False))
    if out_json:
        save(out_json, {"agg": agg, "rows": rows})


def main():
    global SELECTION, VDIR, PRE_EVAL2, VARIANT, PROFILES, SEED_SHIFT
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print table over finished verify/*.json and exit")
    ap.add_argument("--out", type=str, default=None, help="--report: also write rows+agg JSON here")
    ap.add_argument("--levels", type=str, default="")
    ap.add_argument("--all-done", action="store_true", help="every selection_v2 level that has seeds")
    ap.add_argument("--budget", type=float, default=210.0, help="seconds; stops starting new stages after this")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--selection", type=str, default=SELECTION, help="selection file (e.g. .../selection_v3.json)")
    ap.add_argument("--verify-dir", type=str, default=VDIR, help="output dir; keep one dir per selection version")
    ap.add_argument("--variant", choices=("strict", "relaxed"), default="strict",
                    help="v3 only: which sub-result to verify (use a separate --verify-dir per variant)")
    ap.add_argument("--profiles", type=str, default="", help="comma list, e.g. casual,fast:expert,optimal")
    ap.add_argument("--seed-shift", type=int, default=0, help="added to bot seed bases (v4: 10000000)")
    ap.add_argument("--pre-eval2", action="store_true",
                    help="v2 run only: start from eval2/<lv>/final.json before the selection file has the level")
    ap.add_argument("--watch", action="store_true", help="follow selection_v2 until the selection run ends")
    ap.add_argument("--max-workers", type=int, default=8, help="--watch: workers after the selection run ends")
    args = ap.parse_args()
    SELECTION = os.path.abspath(args.selection)
    VDIR = os.path.abspath(args.verify_dir)
    PRE_EVAL2 = args.pre_eval2
    VARIANT = args.variant
    if args.profiles:
        PROFILES = tuple(x for x in args.profiles.split(",") if x)
    SEED_SHIFT = args.seed_shift
    if args.report:
        report(args.out)
        return
    if args.watch:
        watch(args.max_workers, args.workers)
        return
    entries = selection_entries()
    if args.all_done:
        levels = [lv for lv, e in entries.items() if e.get("base")]
    else:
        levels = [int(x) for x in args.levels.split(",") if x]
    deadline = time.time() + args.budget
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for lv in levels:
            e = entries.get(lv)
            if not e or not e.get("base"):
                print(f"L{lv}: no seeds in selection_v2 (status={e and e.get('status')})")
                continue
            if not step_level(ex, lv, e, deadline):
                print("budget used; re-run to continue")
                return
    print("ALL DONE")


if __name__ == "__main__":
    main()
