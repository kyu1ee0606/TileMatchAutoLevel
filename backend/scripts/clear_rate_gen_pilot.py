"""Generation pilot for the two target modes (doc 35 §9, doc 33 §13) — sandbox only, ≤ 5 final levels.

Flow per level: mode / placement / target (pre-registered in PLAN) → candidates (generate route core, seeded) →
final game conditions (finalize_game_conditions, cond_hash) → bot measurement on search band S (shared measure +
store) → A: predict_level + select / B: virtual_rate + select_virtual → top-1 → re-measure on confirmation band C →
A: select.verdict / B: virtual_verdict → level JSON + measurement records + verdict + evidence saved.

  golden   measure() on training maps with the training band (seed11M) must reproduce the stored training rows
           (bot_cache wins / fail reasons + full rows file) exactly — the shared measure path == training protocol
  run      the pilot (checkpointed per level; re-running skips finished levels, never re-optimises on C)
  summary  summary.json / summary.md from the saved level results

Run from the worktree backend with the main venv; data written to the main checkout's sandbox (CR_DATA_ROOT).
At most 2 measuring processes. Total bot games capped by PLAN["budget"]["max_total_games"].
Bot results are bot results: a C re-measurement checks bot-measurement stability, not a real-user clear rate.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import random
import resource
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
DATA = Path(os.environ.get("CR_DATA_ROOT", str(BACKEND.parent.parent / "TileMatchAutoLevel/backend/data")))
CAL = DATA / "pv_sandbox/af_calibration"
OUT = DATA / "pv_sandbox/gen_pilot/20261016"
WORKERS = min(2, int(os.environ.get("PV_WORKERS", "2")))
T0 = time.time()

# ── pre-registered plan (doc 33 §13; committed before any pilot result was seen) ─────────────────────────────
PLAN = {
    "levels": [
        {"id": "A85", "mode": "user_expected", "placement": 157, "target": 0.85},
        {"id": "A90", "mode": "user_expected", "placement": 213, "target": 0.90},
        {"id": "A95", "mode": "user_expected", "placement": 268, "target": 0.95},
        {"id": "B15", "mode": "bot_virtual", "placement": 184, "target": 0.15},
        {"id": "B50", "mode": "bot_virtual", "placement": 236, "target": 0.50},
    ],
    "candidates_per_level": 10,                       # generation attempts; failures / excluded are not replaced
    "candidate_target_difficulty": [round(0.05 + 0.10 * i, 2) for i in range(10)],
    "gen_seed_rule": "random.seed(9_160_000 + placement*100 + candidate_index) before each generation (best effort: "
                     "the generator keeps module state, so a re-run is not bit-identical — the saved level JSON is "
                     "the record)",
    "confirm_top_k": 1,
    "search": {"protocol": "theta4x128_v1", "seed_band": "S"},                 # both modes (shared measurement)
    "confirm": {"user_expected": {"protocol": "theta4x128_v1", "seed_band": "C"},
                "bot_virtual": {"protocol": "theta085x512_v1", "seed_band": "C"}},
    "golden": {"levels": [237, 291, 301, 345], "protocol": "theta4x128_v1", "seed_band": "seed11M"},
    "budget": {"max_total_games": 31000, "expected_games": 2048 + 5 * (10 * 512 + 512)},
    "selection": {"user_expected": "select.select(k=1, λ=0.25): in-support only, |logit pred − logit t| + λ·width80; "
                                   "ties → lower candidate index",
                  "bot_virtual": "virtual.select_virtual(k=1): |logit r_S − logit t|; ties → lower candidate index"},
    "verdict": {"user_expected": "select.verdict on the C prediction (doc 31 D5/D6 proposals: band logit ±0.7, "
                                 "P(in band) ≥ 0.5; low confidence / target <0.85 / outside support → "
                                 "INSUFFICIENT_EVIDENCE) — experiment criteria, not validated",
                "bot_virtual": "virtual.virtual_verdict on C (θ0.85 × 512): |r_C − t| ≤ 0.05 → met; Wilson 95% "
                               "half-width > 0.05, 0 wins, wrong version / protocol / band / cond hash → "
                               "measurement insufficient; else not met. Real-user status always 'unverified'"},
    "stop": {"user_expected": "precheck hard (target <0.85, outside segment p5–p95, placement outside L32–500) → "
                              "no generation, INSUFFICIENT_EVIDENCE; no in-support candidate after S → "
                              "INSUFFICIENT_EVIDENCE (no C)",
             "bot_virtual": "no candidate with a valid S θ0.85 row → NO_CANDIDATE (no C)",
             "common": "candidate excluded (generation failed / timea > 0 / autoCollectCount > 0) is not replaced; "
                       "budget cap reached → stop and report; no re-run on C, no extra candidates"},
}
GIMMICK_UNLOCK = {"craft": 11, "stack": 21, "ice": 31, "link": 51, "chain": 81, "key": 111, "grass": 151,
                  "unknown": 191, "curtain": 241, "bomb": 291, "time_attack": 341, "frog": 391, "teleport": 441}
AVAILABLE = ["craft", "stack", "chain", "frog", "ice", "grass", "link", "bomb", "curtain", "teleport", "unknown"]


def log(*a):
    print(f"[{time.time() - T0:7.0f}s]", *a, flush=True)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=list)
    os.replace(tmp, path)


def swap_used():
    try:
        s = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
        return s.split("used = ")[1].split()[0]
    except Exception:
        return "?"


class Budget:
    def __init__(self, path):
        self.path = path
        self.d = load(path) if path.exists() else {"games": 0, "cpu_sec": 0.0, "peak_worker_rss_mb": 0.0,
                                                   "by_step": {}}

    def check(self, games):
        if self.d["games"] + games > PLAN["budget"]["max_total_games"]:
            raise SystemExit(f"BUDGET: {self.d['games']} + {games} > {PLAN['budget']['max_total_games']} — stop")

    def add(self, step, meta):
        self.d["games"] += meta["games"]
        self.d["cpu_sec"] = round(self.d["cpu_sec"] + meta["cpu_sec"], 2)
        self.d["peak_worker_rss_mb"] = max(self.d["peak_worker_rss_mb"], meta["peak_worker_rss_mb"])
        self.d["by_step"][step] = self.d["by_step"].get(step, 0) + meta["games"]
        save(self.path, self.d)


def games_of(protocol):
    from app.core.clear_rate.measure import PROTOCOLS
    th, g = PROTOCOLS[protocol]
    return len(th) * g


# ── golden: shared measure path reproduces the training rows ─────────────────────────────────────────────────
def cmd_golden(a):
    from app.core.clear_rate import cond_hash, load_model
    from app.core.clear_rate.conditions import normalize_conditions
    from app.core.clear_rate.measure import bot_exposure, measure
    mdl = load_model()
    prep = {int(k): v for k, v in load(CAL / "bot_v21/prep.json").items()}
    stored_ex = {int(k): v for k, v in load(CAL / "bot_v21/exposure.json").items()}
    full = {(r["L"], r["theta"]): r for r in load(CAL / "bot_v24/bot_v2.4f_no_rules_only.json")["rows"]}
    bud = Budget(OUT / "budget.json")
    g = PLAN["golden"]
    res, ok_all = [], True
    log("golden start, swap used", swap_used())
    with ProcessPoolExecutor(WORKERS) as ex:
        for L in g["levels"]:
            p = prep[L]
            cond = normalize_conditions(p["row"])
            h = cond_hash(p["map"], cond)
            cache = mdl.bot_cache.get(h)
            expo = bot_exposure(mdl.model["position"], L)
            expo_same = all(expo["exposure"][k] == stored_ex[L][k] for k in ("bomb", "grass"))
            bud.check(games_of(g["protocol"]))
            m, meta = measure(p["map"], cond, exposure=expo, protocol=g["protocol"], seed_band=g["seed_band"],
                              executor=ex)
            bud.add("golden", meta)
            rows = []
            for r in m.rows:
                c = next(x for x in cache["rows"] if x["theta"] == r["theta"]) if cache else None
                f = full.get((L, r["theta"]))
                same_c = bool(c) and r["wins"] == c["wins"] and r["fail_reasons"] == c["fail_reasons"]
                same_f = bool(f) and all(r[k] == f[k] for k in ("games", "wins", "fail_reasons", "fail_tiles_left",
                                                                 "fail_tiles_left_board"))
                rows.append({"theta": r["theta"], "wins": r["wins"], "cache_wins": c and c["wins"],
                             "identical_cache": same_c, "identical_full_rows": same_f})
                ok_all &= same_c and same_f
            res.append({"L": L, "mode": p["mode"], "cond_hash": h, "cache_hit": bool(cache),
                        "exposure_equals_training": expo_same, "rows": rows, "cpu_sec": meta["cpu_sec"],
                        "peak_worker_rss_mb": meta["peak_worker_rss_mb"]})
            ok_all &= bool(cache) and expo_same
            log(f"golden L{L} ({p['mode']}): " + ", ".join(f"θ{r['theta']} {r['wins']}/{r['cache_wins']}"
                                                           f"{'=' if r['identical_full_rows'] else '≠'}" for r in rows))
    save(OUT / "golden.json", {"ok": ok_all, "levels": res, "swap_used_after": swap_used(),
                               "checked": "wins + fail_reasons vs model bot_cache; games, wins, fail_reasons, "
                                          "fail_tiles_left(_board) vs bot_v2.4f_no_rules_only.json"})
    log("golden", "OK — identical" if ok_all else "MISMATCH", "swap used", swap_used())
    if not ok_all:
        raise SystemExit(1)


# ── candidates ───────────────────────────────────────────────────────────────────────────────────────────────
class _OsProxy:
    """os stand-in for the generate route module: urandom returns the candidate seed bytes so the route's own
    `random.seed(os.urandom(8))` becomes reproducible. Everything else is the real os module."""

    def __init__(self, seed):
        self._b = int(seed).to_bytes(8, "big")

    def urandom(self, n):
        return self._b[:n].rjust(n, b"\0")

    def __getattr__(self, k):
        return getattr(os, k)


def candidate_request(L, td, rng):
    """Python mirror of the production dashboard's per-level candidate params (non-boss, non-special-shape,
    L > 30): symmetry / goal / grid / layers rules, aesthetic patterns, auto gimmicks with the professional unlock
    table. Simplified: pattern_index left to the backend, unit assembly / sub-boss turtle / reverse generation off."""
    roll = rng.random()
    sym = "none" if roll < 0.05 else "horizontal" if roll < 0.40 else "vertical" if roll < 0.75 else "both"
    if sym in ("both", "vertical"):
        dirs = ["s", "n"] if rng.random() < 0.7 else ["e", "w"]
    elif sym == "horizontal":
        dirs = ["e", "w"] if rng.random() < 0.7 else ["s", "n"]
    else:
        dirs = ["s", "n", "e", "w"]
    gdir = dirs[int(rng.random() * len(dirs))]
    gtype = ("craft", "stack")[int(rng.random() * 2)]
    grid = [8, 8] if rng.random() < 0.3 else [7, 7]
    return {"target_difficulty": td, "grid_size": grid, "min_layers": 2, "max_layers": min(10, 3 + int(td * 7)),
            "obstacle_types": [], "goals": [{"type": gtype, "direction": gdir, "count": max(2, int(3 + td * 2))}],
            "symmetry_mode": sym, "pattern_type": "aesthetic", "auto_select_gimmicks": True,
            "available_gimmicks": AVAILABLE, "gimmick_unlock_levels": GIMMICK_UNLOCK, "level_number": L,
            "gimmick_intensity": min(td, L / 500)}


def generate_candidate(L, i):
    import app.api.routes.generate as G
    seed = 9_160_000 + L * 100 + i
    td = PLAN["candidate_target_difficulty"][i]
    req = candidate_request(L, td, random.Random(seed))
    real_os = G.os
    G.os = _OsProxy(seed)
    try:
        t0 = time.time()
        r = G._generate_core_worker(req)
    finally:
        G.os = real_os
    if not r.get("ok"):
        return {"index": i, "gen_seed": seed, "request": req, "ok": False, "detail": r.get("detail")}
    resp = r["response"]
    return {"index": i, "gen_seed": seed, "request": req, "ok": True, "level_json": resp.level_json,
            "gen_sec": round(time.time() - t0, 2), "legacy_grade": resp.grade,
            "playability_warning": bool(getattr(resp, "playability_warning", False))}


# ── run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def run_level(spec, mdl, store, bud, ex):
    from app.core.clear_rate import finalize_game_conditions, select
    from app.core.clear_rate import experiment as X
    from app.core.clear_rate.measure import bot_exposure, measure_cached
    from app.core.clear_rate.predict import predict_level
    from app.core.clear_rate.service import random_layout
    from app.core.clear_rate.virtual import DEFAULT_DEF, select_virtual, virtual_rate
    mode, L, t = X.require_mode(spec["mode"]), spec["placement"], spec["target"]
    out = {**spec, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": []}
    if mode == X.USER_EXPECTED:
        pre = X.user_expected_precheck(mdl, t, L)
        out["precheck"] = pre
        if pre:
            out.update(outcome="INSUFFICIENT_EVIDENCE", reason="목표/배치가 학습 근거 밖: " + ", ".join(pre))
            return out
    else:
        out["bot_virtual_def"], out["bot_virtual_def_id"] = DEFAULT_DEF.to_dict(), DEFAULT_DEF.def_id
    expo = bot_exposure(mdl.model["position"], L)
    s = PLAN["search"]
    eligible = []
    for i in range(PLAN["candidates_per_level"]):
        c = generate_candidate(L, i)
        rec = {k: v for k, v in c.items() if k != "level_json"}
        if c["ok"]:
            gm, cond = finalize_game_conditions(c["level_json"], L)
            excl = [k for k in ("timea", "autoCollectCount") if cond[k]]
            rec.update(conditions=cond, excluded=excl)
            save(OUT / spec["id"] / f"cand{i:02d}.json", {"level_json": c["level_json"], "placement": L,
                                                         "conditions": cond, "gen_seed": c["gen_seed"],
                                                         "request": c["request"]})
            if not excl:
                bud.check(games_of(s["protocol"]))
                m, meta, hit = measure_cached(store, gm, cond, exposure=expo, protocol=s["protocol"],
                                              seed_band=s["seed_band"], executor=ex)
                if not hit:
                    bud.add(f"{spec['id']}:S", meta)
                rec.update(cond_hash=m.cond_hash, bot_config_hash=meta["bot_config_hash"], s_from_store=hit,
                           s_rows=[{k: r[k] for k in ("theta", "games", "wins", "fail_reasons")} for r in m.rows],
                           s_cpu_sec=meta["cpu_sec"])
                if mode == X.USER_EXPECTED:
                    p = predict_level(mdl, gm, cond, L, m, random_layout=random_layout(gm))
                    rec["s_prediction"] = {k: getattr(p, k) for k in ("status", "in_support", "insufficient_reasons",
                                                                      "expected_ft_any", "range80_ft_any",
                                                                      "confidence")}
                    rec["s_flags"] = [f["code"] for f in p.evidence_flags]
                    eligible.append((i, gm, cond, p))
                else:
                    vr = virtual_rate(m, DEFAULT_DEF)
                    rec["s_bot_virtual"] = vr
                    if vr is not None:
                        eligible.append((i, gm, cond, vr))
        out["candidates"].append(rec)
        log(f"{spec['id']} cand {i} td {PLAN['candidate_target_difficulty'][i]} ok={c['ok']} "
            f"excl={rec.get('excluded')} " +
            (f"S pred {rec['s_prediction']['expected_ft_any']} {rec['s_prediction']['status']}"
             if 's_prediction' in rec else f"S bot θ0.85 {rec['s_bot_virtual']['rate']}"
             if rec.get('s_bot_virtual') else "") + f" | games so far {bud.d['games']}")
        save(OUT / spec["id"] / "progress.json", out)
    out["n_generated"] = sum(1 for c in out["candidates"] if c["ok"])
    out["n_eligible"] = len(eligible)

    if mode == X.USER_EXPECTED:
        picked = select([e[3] for e in eligible], t, k=PLAN["confirm_top_k"])
        if not picked:
            out.update(outcome="INSUFFICIENT_EVIDENCE", reason="S 측정 후 지원 범위 안 후보 없음 (확인 측정 생략)")
            return out
        top = next(e for e in eligible if e[3] is picked[0])
    else:
        ranked = select_virtual([(e[0], e[3]["rate"]) for e in eligible], t, k=PLAN["confirm_top_k"])
        if not ranked:
            out.update(outcome="NO_CANDIDATE", reason="유효한 S θ0.85 측정 후보 없음 (확인 측정 생략)")
            return out
        top = next(e for e in eligible if e[0] == ranked[0][0])
    i, gm, cond, _ = top
    out["selected_index"] = i
    cp = PLAN["confirm"][mode]
    bud.check(games_of(cp["protocol"]))
    m_c, meta_c, hit = measure_cached(store, gm, cond, exposure=expo, protocol=cp["protocol"],
                                      seed_band=cp["seed_band"], executor=ex)
    if not hit:
        bud.add(f"{spec['id']}:C", meta_c)
    out["c_rows"] = [{k: r[k] for k in ("theta", "games", "wins", "fail_reasons")} for r in m_c.rows]
    out["c_cpu_sec"] = meta_c["cpu_sec"]
    if mode == X.USER_EXPECTED:
        ev = X.evaluate_user_expected(mdl, gm, cond, L, m_c, t, random_layout=random_layout(gm))
        out["evaluation"] = ev
        out["outcome"] = ev["verdict"]["verdict"]
        out["reason"] = ev["verdict"]["reason"]
    else:
        m_s = store.get(m_c.cond_hash, s["protocol"], s["seed_band"], meta_c["bot_config_hash"])[0]
        ev = X.evaluate_bot_virtual(gm, cond, m_s, m_c, t)
        out["evaluation"] = ev
        out["outcome"] = ev["bot_virtual_verdict"]
        out["reason"] = ev["reason"]
    save(OUT / spec["id"] / "final_level.json", {"level_json": load(OUT / spec["id"] / f"cand{i:02d}.json")
                                                 ["level_json"], "placement": L, "mode": mode, "target": t,
                                                 "conditions": cond, "cond_hash": m_c.cond_hash})
    return out


def cmd_run(a):
    from app.core.clear_rate import load_model
    from app.core.clear_rate.measure import MeasurementStore
    mdl = load_model()
    assert mdl.version == "cr-ftany-v24r-20261016", mdl.version
    gold = OUT / "golden.json"
    if not gold.exists() or not load(gold)["ok"]:
        raise SystemExit("golden reproduction not OK — run `golden` first")
    store = MeasurementStore(OUT / "measurements.json")
    bud = Budget(OUT / "budget.json")
    log("run start, swap used", swap_used(), "games so far", bud.d["games"])
    with ProcessPoolExecutor(WORKERS) as ex:
        for spec in PLAN["levels"]:
            path = OUT / spec["id"] / "result.json"
            if path.exists():
                log(spec["id"], "done already — skipped")
                continue
            t0 = time.time()
            r = run_level(spec, mdl, store, bud, ex)
            r["wall_sec"] = round(time.time() - t0, 1)
            r["swap_used_after"] = swap_used()
            save(path, r)
            log(spec["id"], "→", r["outcome"], "|", r.get("reason"), "| wall", r["wall_sec"], "s | games",
                bud.d["games"], "| swap", r["swap_used_after"])
    log("run done; total games", bud.d["games"], "cpu", bud.d["cpu_sec"], "peak worker RSS",
        bud.d["peak_worker_rss_mb"], "MB; driver maxrss",
        round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20, 1), "MB")


def cmd_summary(a):
    bud = load(OUT / "budget.json")
    rows = []
    for spec in PLAN["levels"]:
        p = OUT / spec["id"] / "result.json"
        if not p.exists():
            rows.append({**spec, "outcome": "NOT_RUN"})
            continue
        r = load(p)
        sel = r.get("selected_index")
        cand = next((c for c in r["candidates"] if c["index"] == sel), None) if sel is not None else None
        row = {**spec, "outcome": r["outcome"], "reason": r.get("reason"), "n_generated": r.get("n_generated"),
               "n_eligible": r.get("n_eligible"), "selected_index": sel, "wall_sec": r.get("wall_sec")}
        if spec["mode"] == "user_expected" and cand:
            ev = r["evaluation"]
            row.update(s_expected=cand["s_prediction"]["expected_ft_any"], s_range80=cand["s_prediction"]["range80_ft_any"],
                       c_expected=ev["prediction"]["expected_ft_any"], c_range80=ev["prediction"]["range80_ft_any"],
                       c_confidence=ev["prediction"]["confidence"], c_p_in_band=ev["verdict"]["p_in_band"],
                       c_flags=[f["code"] for f in ev["prediction"]["evidence_flags"]],
                       s_in_support=sum(1 for c in r["candidates"] if c.get("s_prediction", {}).get("in_support")),
                       s_expected_all=[c.get("s_prediction", {}).get("expected_ft_any") for c in r["candidates"]])
        if spec["mode"] == "bot_virtual" and cand:
            ev = r["evaluation"]
            row.update(s_rate=cand["s_bot_virtual"]["rate"], s_ci95=cand["s_bot_virtual"]["ci95"],
                       c_rate=ev["bot_virtual_rate_c"], c_ci95=ev["bot_virtual_ci95_c"],
                       c_half_width=ev["bot_virtual_half_width_c"], real_user_status=ev["real_user_status"],
                       s_rate_all=[(c.get("s_bot_virtual") or {}).get("rate") for c in r["candidates"]])
        rows.append(row)
    save(OUT / "summary.json", {"levels": rows, "budget": bud, "plan": PLAN})
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print(json.dumps(bud))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("golden").set_defaults(f=cmd_golden)
    sub.add_parser("run").set_defaults(f=cmd_run)
    sub.add_parser("summary").set_defaults(f=cmd_summary)
    sub.add_parser("plan").set_defaults(f=lambda a: print(json.dumps(PLAN, ensure_ascii=False, indent=1)))
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
