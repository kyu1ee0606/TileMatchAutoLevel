"""Generation pilot 2 — measured, adaptive candidate search for the same 5 targets (doc 33 §14). Sandbox only.

Changes vs pilot 1 (doc 33 §13): every candidate is generated in its own fresh process (PYTHONHASHSEED=0, seeded) so
the gen seed reproduces the map; candidate params follow the dashboard rules more closely (size diversity from L101);
duplicates (same final-condition hash or same structure) are not measured twice; mode A screens each map with the
bot-independent part of the prediction checks (experiment.structural_screen) before paying for a measurement; the
search is adaptive (broad td grid → refine around the closest measured candidates, both sides, repeats — no monotonic
assumption); B uses a θ0.85 × 64 screening run (never a verdict input) before the 512-game search measurement.
Unchanged: model, targets, placements, tolerance, reliability rules, verdict rules. New seed bands; pilot-1 bands
(S 15M / C 16M) are not reused.

  analyze  pilot-1 failure analysis from the saved candidates (no bot runs) → analysis_pilot1.json
  run      the pilot (per-level checkpoint; finished levels skipped)
  summary  summary.json + pilot1 vs pilot2 comparison
  gen1     internal: generate one candidate (called in a fresh process)
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import hashlib
import json
import math
import resource
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
import clear_rate_gen_pilot as P1  # noqa: E402  (Budget, save, load, log helpers, _OsProxy, pilot-1 paths)

DATA = P1.DATA
OUT = DATA / "pv_sandbox/gen_pilot/20261016_p2"
PILOT1 = P1.OUT
WORKERS = min(2, int(os.environ.get("PV_WORKERS", "2")))
PY = sys.executable
T0 = time.time()

AVAILABLE_ALL = P1.AVAILABLE
PLAN = {
    "levels": [
        # A: available gimmicks limited to well-supported training combos at that placement (forced practice gimmick
        # still added by the generator: grass at L157, unknown at L213, curtain at L268); knob "hardness" keeps
        # td < 0.6 and layers 3..5 (training p99 5.22) — see build_request
        {"id": "A85", "mode": "user_expected", "placement": 157, "target": 0.85,
         "available": ["craft", "stack", "link", "chain"], "knob": "hardness"},
        {"id": "A90", "mode": "user_expected", "placement": 213, "target": 0.90,
         "available": ["craft", "stack", "link"], "knob": "hardness"},
        {"id": "A95", "mode": "user_expected", "placement": 268, "target": 0.95,
         "available": ["craft", "stack", "link", "unknown"], "knob": "hardness"},
        {"id": "B15", "mode": "bot_virtual", "placement": 184, "target": 0.15, "available": AVAILABLE_ALL,
         "knob": "td"},
        {"id": "B50", "mode": "bot_virtual", "placement": 236, "target": 0.50, "available": AVAILABLE_ALL,
         "knob": "td"},
    ],
    "gen_seed_rule": "fresh process, PYTHONHASHSEED=0, generate route seeded with 9,260,000 + placement*100 + gen_index",
    "broad_td": [0.1, 0.3, 0.5, 0.7, 0.9],
    "tries_per_td": 4,                    # A: generations per proposed td until one passes screen + dedup
    "refine_offsets": [[-0.05, 0.05, 0.0], [-0.025, 0.025, 0.0]],
    "caps": {"user_expected": {"generations": 45, "full_measurements": 10},
             "bot_virtual": {"generations": 40, "screen_measurements": 30, "search_measurements": 3}},
    "early_stop": {"user_expected": "2 measured candidates with confidence high/medium, in support, no hard target "
                                    "flag and S p_in_band ≥ 0.5",
                   "bot_virtual": "3 screened candidates with |r64 − t| ≤ 0.05"},
    "bands": {"A_search": ["theta4x128_v1", "S2"], "A_confirm": ["theta4x128_v1", "C2"],
              "B_screen": ["theta085x64_v1", "P2"], "B_search": ["theta085x512_v1", "S2B"],
              "B_confirm": ["theta085x512_v1", "C2"]},
    "selection": {"user_expected": "eligible = in support, confidence ≠ low, no hard target flag; rank by S "
                                   "p_in_band desc, then select.score asc, then candidate order; if none eligible → "
                                   "INSUFFICIENT_EVIDENCE without confirmation",
                  "bot_virtual": "screen rank |logit r64 − logit t| (ties → order) → top 3 get the 512-game S2B "
                                 "measurement → select_virtual on S2B rates (k=1)"},
    "verdict": "unchanged: A select.verdict (confirm band C2); B virtual_verdict with VirtualDef(search "
               "theta085x512_v1, bands S2B/C2) — θ0.85, v2.4 rules, no help, 512 confirm games, ±0.05",
    "budget": {"max_run_games": 26000, "total_cap_incl_tests": 33000},
}


def log(*a):
    print(f"[{time.time() - T0:7.0f}s]", *a, flush=True)


def vdef():
    from app.core.clear_rate.virtual import VirtualDef
    return VirtualDef(search_protocol="theta085x512_v1", seed_bands=("S2B", "C2"))


# ── isolated, reproducible generation ─────────────────────────────────────────────────────────────────────────
def build_request(L, x, rng, spec):
    """Dashboard per-level candidate rules (non-boss, non-special-shape, L > 30) incl. size diversity from L101
    (dashboard default). pattern_index left to the backend auto-mix (dashboard picks from its frontend pool).
    x = search knob in [0, 1]:
      B ("td")       target_difficulty = x (as pilot 1)
      A ("hardness") target_difficulty = 0.10 + 0.48x (< 0.6: the generator's _increase_difficulty adds chain+ice
                     to any map at td ≥ 0.6 regardless of the selected gimmicks), layers = 3 + round(2x) (≤ 5)."""
    if spec["knob"] == "hardness":
        td = round(0.10 + 0.48 * x, 3)
        req = P1.candidate_request(L, td, rng)
        lay = 3 + round(2 * x)
        req.update(min_layers=lay, max_layers=lay)
    else:
        req = P1.candidate_request(L, x, rng)
    req["available_gimmicks"] = list(spec["available"])
    req["size_diversity_start_level"] = 101
    return req


def cmd_gen1(a):
    """Runs inside a fresh process: one generation with the given seed → JSON file."""
    import random as _random
    job = json.loads(Path(a.job).read_text())
    # Unseeded random.Random() instances (e.g. the deadlock-check bot inside the generator) draw OS entropy, so the
    # same seed gave different maps. In this isolated process only, seed them from the candidate seed + creation order.
    _orig_seed, _n = _random.Random.seed, [0]

    def _seed(self, a=None, version=2):
        if a is None:
            _n[0] += 1
            a = job["seed"] * 1_000_003 + _n[0]
        return _orig_seed(self, a, version)
    _random.Random.seed = _seed
    import app.api.routes.generate as G
    G.os = P1._OsProxy(job["seed"])
    r = G._generate_core_worker(job["request"])
    out = {"ok": bool(r.get("ok")), "detail": r.get("detail")}
    if r.get("ok"):
        resp = r["response"]
        out.update(level_json=resp.level_json, legacy_grade=resp.grade,
                   playability_warning=bool(getattr(resp, "playability_warning", False)))
    # generator metadata may hold sets (e.g. with an explicit pattern_index) — serialise them as sorted lists
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False,
                                      default=lambda o: sorted(o, key=str) if isinstance(o, (set, frozenset)) else str(o)))


def generate_isolated(request, seed):
    with tempfile.TemporaryDirectory() as d:
        job, out = Path(d) / "job.json", Path(d) / "out.json"
        job.write_text(json.dumps({"request": request, "seed": seed}))
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        t0 = time.time()
        subprocess.run([PY, "-W", "ignore", __file__, "gen1", "--job", str(job), "--out", str(out)], cwd=str(BACKEND),
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        r = json.loads(out.read_text()) if out.exists() else {"ok": False, "detail": "no output"}
        r["gen_sec"] = round(time.time() - t0, 2)
        return r


def structure_hash(game_map):
    """Layout + effects, tile types ignored (doc 35 §7-3 map group)."""
    n = int(game_map["layer"])
    s = {}
    for i in range(n):
        t = (game_map.get(f"layer_{i}") or {}).get("tiles") or {}
        s[i] = sorted((p, str(v[1]) if len(v) > 1 else "", str(v[0]).split("_")[0] if str(v[0]).startswith(
            ("stack", "craft")) else "") for p, v in (t.items() if isinstance(t, dict) else []))
    return hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()[:16]


# ── search helpers ────────────────────────────────────────────────────────────────────────────────────────────
def lgt(p, eps=1e-3):
    p = min(1 - eps, max(eps, p))
    return math.log(p / (1 - p))


def proposals(records, target, value_key, refine_round):
    """Next td values: bracket midpoint (closest measured value above and below the target, if both exist), then
    around the closest candidate (offsets of this round, incl. a repeat at the same td). No monotonic assumption."""
    rs = [r for r in records if r.get(value_key) is not None]
    if not rs:
        return []
    rs.sort(key=lambda r: (abs(lgt(r[value_key]) - lgt(target)), r["gen_index"]))
    out = []
    above = [r for r in rs if r[value_key] > target]
    below = [r for r in rs if r[value_key] <= target]
    if above and below:
        out.append(round((above[0]["x"] + below[0]["x"]) / 2, 3))
    offs = PLAN["refine_offsets"][min(refine_round, len(PLAN["refine_offsets"]) - 1)]
    out += [round(min(0.98, max(0.02, rs[0]["x"] + o)), 3) for o in offs]
    return out


class Level:
    def __init__(self, spec, mdl, store, bud, ex):
        self.spec, self.mdl, self.store, self.bud, self.ex = spec, mdl, store, bud, ex
        self.mode, self.L, self.t = spec["mode"], spec["placement"], spec["target"]
        self.dir = OUT / spec["id"]
        self.records, self.seen_hash, self.seen_struct = [], set(), set()
        self.gen_index = 0
        from app.core.clear_rate.measure import bot_exposure
        self.expo = bot_exposure(mdl.model["position"], self.L)

    def gen(self, td):
        """One isolated generation at td → record (screen / dedup applied, not measured yet)."""
        from app.core.clear_rate import finalize_game_conditions
        from app.core.clear_rate import experiment as X
        from app.core.clear_rate.measure import config_hash, bot_config
        from app.core.clear_rate.service import random_layout
        import random as _r
        i = self.gen_index
        self.gen_index += 1
        seed = 9_260_000 + self.L * 100 + i
        req = build_request(self.L, td, _r.Random(seed), self.spec)
        g = generate_isolated(req, seed)
        rec = {"gen_index": i, "x": td, "gen_seed": seed, "request": req, "ok": g["ok"], "gen_sec": g["gen_sec"],
               "detail": g.get("detail")}
        if not g["ok"]:
            rec["skip"] = "generation_failed"
            self.records.append(rec)
            return rec
        gm, cond = finalize_game_conditions(g["level_json"], self.L)
        from app.core.clear_rate import cond_hash
        h, sh = cond_hash(gm, cond), structure_hash(gm)
        rl = random_layout(gm)
        rec.update(cond_hash=h, structure_hash=sh, conditions=cond, legacy_grade=g.get("legacy_grade"),
                   playability_warning=g.get("playability_warning"), random_layout=rl,
                   bot_config_hash=config_hash(bot_config(self.expo, cond)))
        P1.save(self.dir / f"gen{i:03d}.json", {"level_json": g["level_json"], "placement": self.L, "conditions": cond,
                                               "cond_hash": h, "gen_seed": seed, "request": req})
        scr = X.structural_screen(self.mdl, gm, cond, self.L, random_layout=rl)
        rec["screen"] = scr
        excl = [k for k in ("timea", "autoCollectCount") if cond[k]]
        if excl:
            rec["skip"] = "excluded:" + ",".join(excl)
        elif h in self.seen_hash:
            rec["skip"] = "duplicate_cond_hash"
        elif sh in self.seen_struct:
            rec["skip"] = "duplicate_structure"
        elif self.mode == "user_expected" and scr["blocking"]:
            rec["skip"] = "screen:" + ",".join(scr["blocking"])
        self.seen_hash.add(h)
        self.seen_struct.add(sh)
        rec["_gm"] = gm
        self.records.append(rec)
        return rec

    def measure(self, rec, key):
        from app.core.clear_rate.measure import measure_cached, PROTOCOLS
        proto, band = PLAN["bands"][key]
        th, gpt = PROTOCOLS[proto]
        self.bud.check(len(th) * gpt)
        m, meta, hit = measure_cached(self.store, rec["_gm"], rec["conditions"], exposure=self.expo, protocol=proto,
                                      seed_band=band, executor=self.ex)
        if not hit:
            self.bud.add(f"{self.spec['id']}:{key}", meta)
        rec.setdefault("measurements", {})[key] = {
            "protocol": proto, "band": band, "rows": [{k: r[k] for k in ("theta", "games", "wins", "fail_reasons")}
                                                      for r in m.rows], "cpu_sec": meta["cpu_sec"]}
        rec["any_bot_win"] = rec.get("any_bot_win", False) or any(r["wins"] > 0 for r in m.rows)
        return m

    def reproduce(self, rec):
        """Regenerate the candidate from its seed + request in a fresh process; same final-condition hash? (0 games)"""
        from app.core.clear_rate import cond_hash, finalize_game_conditions
        g = generate_isolated(rec["request"], rec["gen_seed"])
        h = cond_hash(*finalize_game_conditions(g["level_json"], self.L)) if g["ok"] else None
        rec["reproduced"] = h == rec["cond_hash"]
        return rec["reproduced"]

    def checkpoint(self, extra=None):
        P1.save(self.dir / "progress.json", {"spec": self.spec, "records": [self._pub(r) for r in self.records],
                                            **(extra or {})})

    @staticmethod
    def _pub(r):
        return {k: v for k, v in r.items() if not k.startswith("_")}


# ── mode A ────────────────────────────────────────────────────────────────────────────────────────────────────
def run_a(lv):
    from app.core.clear_rate import experiment as X
    from app.core.clear_rate.predict import predict_level
    from app.core.clear_rate.select import score, verdict
    caps = PLAN["caps"]["user_expected"]
    sup = lv.mdl.model["support"]
    pre = X.user_expected_precheck(lv.mdl, lv.t, lv.L)
    out = {"precheck": pre}
    if pre:
        return {**out, "outcome": "INSUFFICIENT_EVIDENCE", "reason": "목표/배치가 학습 근거 밖: " + ", ".join(pre)}
    n_meas = 0

    def good(r):
        return r.get("s_eligible") and r.get("s_p_in_band", 0) >= 0.5

    def try_td(td):
        nonlocal n_meas
        for _ in range(PLAN["tries_per_td"]):
            if lv.gen_index >= caps["generations"] or n_meas >= caps["full_measurements"]:
                return
            r = lv.gen(td)
            log(f"{lv.spec['id']} gen {r['gen_index']} td {td} ok={r['ok']} skip={r.get('skip')} "
                f"combo={r.get('screen', {}).get('combo')} layers={r.get('screen', {}).get('structure', {}).get('layers')}")
            if r.get("skip"):
                continue
            m = lv.measure(r, "A_search")
            n_meas += 1
            p = predict_level(lv.mdl, r["_gm"], r["conditions"], lv.L, m, random_layout=r["random_layout"])
            r["s_prediction"] = {k: getattr(p, k) for k in ("status", "in_support", "insufficient_reasons",
                                                              "expected_ft_any", "range80_ft_any", "confidence")}
            r["s_flags"] = [f["code"] for f in p.evidence_flags]
            r["s_value"] = p.expected_ft_any
            if p.in_support and p.expected_ft_any is not None:
                v = verdict(p, lv.t, sup, confirm_bands=("S2",))       # S-band quantities for ranking only
                hard_t = [f["code"] for f in v.target_flags if f["severity"] == "hard" and f["code"] != "SELECTION_UNCONFIRMED"]
                r["s_p_in_band"], r["s_score"] = v.p_in_band, round(score(p, lv.t), 4)
                r["s_eligible"] = p.confidence in ("high", "medium") and not hard_t
                r["_pred"] = p
            log(f"   measured → pred {r['s_value']} conf {r['s_prediction']['confidence']} "
                f"p_in_band {r.get('s_p_in_band')} eligible {r.get('s_eligible')} | games {lv.bud.d['games']}")
            lv.checkpoint()
            return

    for td in PLAN["broad_td"]:
        try_td(td)
    rnd = 0
    while lv.gen_index < caps["generations"] and n_meas < caps["full_measurements"]:
        if sum(1 for r in lv.records if good(r)) >= 2:
            out["early_stop"] = True
            break
        props = proposals([r for r in lv.records if r.get("s_value") is not None], lv.t, "s_value", rnd)
        if not props:
            out["stop"] = "no measured in-support candidate after the broad grid — no refinement anchor"
            break
        for td in props:
            try_td(td)
        rnd += 1
    elig = [r for r in lv.records if r.get("s_eligible")]
    elig.sort(key=lambda r: (-r["s_p_in_band"], r["s_score"], r["gen_index"]))
    out.update(n_generated=lv.gen_index, n_measured=n_meas)
    if not elig:
        why = {}
        for r in lv.records:
            k = r.get("skip") or ("measured_low_conf" if r.get("s_prediction", {}).get("confidence") == "low" else
                                  "measured_no_support" if r.get("s_prediction") and not r["s_prediction"]["in_support"]
                                  else "measured_target_flag")
            why[k.split(":")[0] if k.startswith("screen") else k] = why.get(k.split(":")[0] if k.startswith("screen") else k, 0) + 1
        return {**out, "outcome": "INSUFFICIENT_EVIDENCE", "reason": f"신뢰 가능한 후보 없음 (확인 측정 생략): {why}"}
    top = elig[0]
    out["selected_gen_index"] = top["gen_index"]
    lv.reproduce(top)
    m_c = lv.measure(top, "A_confirm")
    ev = X.evaluate_user_expected(lv.mdl, top["_gm"], top["conditions"], lv.L, m_c, lv.t,
                                  random_layout=top["random_layout"], confirm_bands=("C2",))
    return {**out, "evaluation": ev, "outcome": ev["verdict"]["verdict"], "reason": ev["verdict"]["reason"],
            "selected": Level._pub(top)}


# ── mode B ────────────────────────────────────────────────────────────────────────────────────────────────────
def run_b(lv):
    from app.core.clear_rate import experiment as X
    from app.core.clear_rate.virtual import select_virtual, virtual_rate
    caps = PLAN["caps"]["bot_virtual"]
    d = vdef()
    out = {"bot_virtual_def": d.to_dict(), "bot_virtual_def_id": d.def_id}
    n_scr = 0

    def near(r):
        return r.get("r64") is not None and abs(r["r64"] - lv.t) <= d.tolerance_abs

    def try_td(td):
        nonlocal n_scr
        for _ in range(PLAN["tries_per_td"]):
            if lv.gen_index >= caps["generations"] or n_scr >= caps["screen_measurements"]:
                return
            r = lv.gen(td)
            if r.get("skip"):
                log(f"{lv.spec['id']} gen {r['gen_index']} td {td} skip={r.get('skip')}")
                continue
            m = lv.measure(r, "B_screen")
            n_scr += 1
            r["r64"] = round(m.rows[0]["wins"] / m.rows[0]["games"], 4)
            r["s_value"] = r["r64"]
            log(f"{lv.spec['id']} gen {r['gen_index']} td {td} r64 {r['r64']} | games {lv.bud.d['games']}")
            lv.checkpoint()
            return

    for td in PLAN["broad_td"]:
        try_td(td)
    rnd = 0
    while lv.gen_index < caps["generations"] and n_scr < caps["screen_measurements"]:
        if sum(1 for r in lv.records if near(r)) >= 3:
            out["early_stop"] = True
            break
        props = proposals([r for r in lv.records if r.get("r64") is not None], lv.t, "r64", rnd)
        if not props:
            break
        for td in props:
            try_td(td)
        rnd += 1
    scr = [r for r in lv.records if r.get("r64") is not None]
    out.update(n_generated=lv.gen_index, n_screened=n_scr)
    if not scr:
        return {**out, "outcome": "NO_CANDIDATE", "reason": "선별 측정된 후보 없음"}
    scr.sort(key=lambda r: (abs(lgt(r["r64"]) - lgt(lv.t)), r["gen_index"]))
    for r in scr[:caps["search_measurements"]]:
        m = lv.measure(r, "B_search")
        vr = virtual_rate(m, d)
        r["s512"] = vr["rate"]
        r["s512_ci95"] = vr["ci95"]
        r["_ms"] = m
        log(f"{lv.spec['id']} S2B gen {r['gen_index']} r64 {r['r64']} → r512 {r['s512']} | games {lv.bud.d['games']}")
    lv.checkpoint()
    srch = [r for r in scr[:caps["search_measurements"]] if r.get("s512") is not None]
    pick = select_virtual([(r["gen_index"], r["s512"]) for r in srch], lv.t, k=1)
    top = next(r for r in srch if r["gen_index"] == pick[0][0])
    out["selected_gen_index"] = top["gen_index"]
    lv.reproduce(top)
    m_c = lv.measure(top, "B_confirm")
    ev = X.evaluate_bot_virtual(top["_gm"], top["conditions"], top["_ms"], m_c, lv.t, d)
    return {**out, "evaluation": ev, "outcome": ev["bot_virtual_verdict"], "reason": ev["reason"],
            "selected": Level._pub(top)}


def cmd_run(a):
    from app.core.clear_rate import load_model
    from app.core.clear_rate.measure import MeasurementStore
    mdl = load_model()
    assert mdl.version == "cr-ftany-v24r-20261016", mdl.version
    store = MeasurementStore(OUT / "measurements.json")
    bud = P1.Budget(OUT / "budget.json")
    P1.PLAN["budget"]["max_total_games"] = PLAN["budget"]["max_run_games"]   # Budget.check reads pilot-1 PLAN
    log("run start, swap", P1.swap_used(), "games so far", bud.d["games"])
    with ProcessPoolExecutor(WORKERS) as ex:
        for spec in PLAN["levels"]:
            path = OUT / spec["id"] / "result.json"
            if path.exists():
                log(spec["id"], "done already — skipped")
                continue
            t0 = time.time()
            lv = Level(spec, mdl, store, bud, ex)
            r = run_a(lv) if spec["mode"] == "user_expected" else run_b(lv)
            r.update(spec=spec, records=[Level._pub(x) for x in lv.records], wall_sec=round(time.time() - t0, 1),
                     swap_used_after=P1.swap_used(),
                     finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            P1.save(path, r)
            log(spec["id"], "→", r["outcome"], "|", r.get("reason"), "| wall", r["wall_sec"], "| games",
                bud.d["games"])
    log("run done; games", bud.d["games"], "cpu", bud.d["cpu_sec"], "peak worker RSS", bud.d["peak_worker_rss_mb"],
        "MB; driver maxrss", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20, 1), "MB")


# ── analysis of pilot 1 (no bot runs) ─────────────────────────────────────────────────────────────────────────
def cmd_analyze(a):
    from app.core.clear_rate import experiment as X
    from app.core.clear_rate import finalize_game_conditions, load_model
    from app.core.clear_rate.predict import BotMeasurement, predict_level
    from app.core.clear_rate.service import random_layout
    from app.core.clear_rate.measure import MeasurementStore
    mdl = load_model()
    store1 = MeasurementStore(PILOT1 / "measurements.json")
    rows = []
    for spec in P1.PLAN["levels"]:
        r = P1.load(PILOT1 / spec["id"] / "result.json")
        for c in r["candidates"]:
            cj = P1.load(PILOT1 / spec["id"] / f"cand{c['index']:02d}.json")
            gm, cond = finalize_game_conditions(cj["level_json"], spec["placement"])
            rl = random_layout(gm)
            scr = X.structural_screen(mdl, gm, cond, spec["placement"], random_layout=rl)
            m = store1.get(c["cond_hash"], "theta4x128_v1", "S", c["bot_config_hash"])[0]   # full rows (pilot-1 store)
            p = predict_level(mdl, gm, cond, spec["placement"], m, random_layout=rl)
            if "s_prediction" in c:
                assert p.expected_ft_any == c["s_prediction"]["expected_ft_any"], "pilot-1 pred not reproduced"
            rows.append({"level": spec["id"], "index": c["index"], "td": c["request"]["target_difficulty"],
                         "layers": scr["structure"]["layers"], "tiles": scr["structure"]["tiles"],
                         "types": scr["structure"]["types"], "combo": scr["combo"],
                         "bot": {str(x["theta"]): round(x["wins"] / x["games"], 3) for x in c["s_rows"]},
                         "pred": p.expected_ft_any, "confidence": p.confidence, "in_support": p.in_support,
                         "flags": [f["code"] for f in p.evidence_flags], "screen_blocking": scr["blocking"],
                         "any_bot_win": any(x["wins"] for x in c["s_rows"])})
    P1.save(OUT / "analysis_pilot1.json", {"candidates": rows})
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))


def cmd_summary(a):
    bud = P1.load(OUT / "budget.json")
    res = []
    for spec in PLAN["levels"]:
        p = OUT / spec["id"] / "result.json"
        if not p.exists():
            res.append({"id": spec["id"], "outcome": "NOT_RUN"})
            continue
        r = P1.load(p)
        recs = r["records"]
        vals = [x.get("s512", x.get("s_value")) for x in recs if x.get("s_value") is not None]
        row = {"id": spec["id"], "mode": spec["mode"], "target": spec["target"], "outcome": r["outcome"],
               "reason": r.get("reason"), "n_generated": len(recs),
               "n_skipped": {k: sum(1 for x in recs if (x.get("skip") or "").split(":")[0] == k)
                             for k in ("generation_failed", "excluded", "duplicate_cond_hash", "duplicate_structure",
                                       "screen")},
               "n_measured": sum(1 for x in recs if x.get("measurements")),
               "closest": min((abs(v - spec["target"]) for v in vals), default=None),
               "within_tol": sum(1 for v in vals if abs(v - spec["target"]) <= 0.05),
               "values": vals, "wall_sec": r.get("wall_sec"),
               "any_bot_win_measured": sum(1 for x in recs if x.get("any_bot_win")),
               "all_bot_fail_measured": sum(1 for x in recs if x.get("measurements") and not x.get("any_bot_win"))}
        if spec["mode"] == "user_expected":
            row["eligible"] = sum(1 for x in recs if x.get("s_eligible"))
            if r.get("evaluation"):
                ev = r["evaluation"]
                row.update(s_pred=r["selected"]["s_value"], s_p_in_band=r["selected"].get("s_p_in_band"),
                           c_pred=ev["prediction"]["expected_ft_any"], c_range80=ev["prediction"]["range80_ft_any"],
                           c_conf=ev["prediction"]["confidence"], c_p_in_band=ev["verdict"]["p_in_band"])
        elif r.get("evaluation"):
            ev = r["evaluation"]
            row.update(s_r64=r["selected"]["r64"], s_r512=r["selected"]["s512"], c_rate=ev["bot_virtual_rate_c"],
                       c_ci95=ev["bot_virtual_ci95_c"], real_user_status=ev["real_user_status"])
        res.append(row)
    P1.save(OUT / "summary.json", {"levels": res, "budget": bud, "plan": PLAN})
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    print(json.dumps(bud))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("analyze").set_defaults(f=cmd_analyze)
    sub.add_parser("run").set_defaults(f=cmd_run)
    sub.add_parser("summary").set_defaults(f=cmd_summary)
    g = sub.add_parser("gen1")
    g.add_argument("--job")
    g.add_argument("--out")
    g.set_defaults(f=cmd_gen1)
    sub.add_parser("plan").set_defaults(f=lambda a: print(json.dumps(PLAN, ensure_ascii=False, indent=1)))
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
