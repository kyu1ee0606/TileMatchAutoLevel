"""DDA pilot set readiness table (read-only aggregation, 2026-10-19, doc 43).

Reads stored DDA/consensus/sep/③/AF files only. No bot, solver, predictor, network, server or C-job calls.
Imports only af_level_metrics._map_hashes (-> app.core.pv.canonical, pure functions) for canonical map sha256.

Run from the main repo root with the backend venv (pydantic needed by app.core.pv.canonical):
    backend/venv/bin/python backend/scripts/dda_readiness_20261019.py
Refuses to overwrite an existing output directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
import af_level_metrics as af  # noqa: E402  (only _map_hashes used; no CSV reading)

SB = ROOT / "backend/data/pv_sandbox"
LIVE3 = SB / "pv_20261002_live3"
OUT = LIVE3 / "dda_readiness_20261019"

INPUTS = {
    "source_live3": LIVE3 / "source.json",
    "livematch_batch": ROOT / "backend/data/production/batch_1792056041502_cn5e4ny66.json",
    "r2_rows": LIVE3 / "dda_sets/seedvar_rows.json",
    "r2_coverage": LIVE3 / "dda_sets/coverage.json",
    "consensus_levels": LIVE3 / "dda_sets_v2/consensus/levels.json",
    "consensus_summary": LIVE3 / "dda_sets_v2/consensus/summary.json",
    "pilot_B_v3_1": LIVE3 / "dda_sets_v2/consensus/pilot_B_v3_1.json",
    "pilot_A_v2": LIVE3 / "dda_sets_v2/consensus/pilot_A_v2.json",
    "mismatch_report": LIVE3 / "dda_sets_v2/pilot_export/mismatch_report.json",
    "prereg": LIVE3 / "dda_sets_v2/pilot_export/preregistration.json",
    "sep_levels": LIVE3 / "dda_sets_v2/sep/sep_levels.json",
    "evalVer_v2": LIVE3 / "dda_sets_v2/evalVer.json",
    "prep_L32_500": SB / "af_calibration/bot_compare_L32_500/prep.json",
    "af_level_metrics_1014": SB / "af_calibration/level_metrics.json",
    "af_refresh_1019_csv": SB / "af_calibration/refresh_20261019/levels.csv",
}
# P5 quarantine (doc 42 §6, _wt_clearrate guard.py): bot v2.4 cache rows measured with behaviour items on.
P5 = {429, 433, 441, 466, 479, 493, 494, 499}
Z = 2.4977  # app.core.pv.select.Z_V2 (same CI rule as R2 stage 2)
BETA = 0.429  # doc 25 §2-1 logit slope — PROVISIONAL, not validated on users
STAGES = ("R2", "a", "b", "c")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path):
    return json.loads(p.read_text())


def r4(x):
    return None if x is None else round(x, 4)


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def expit(x):
    return 1 / (1 + math.exp(-x))


def pair_ci(orig: dict, var: dict):
    """indep_diff over the shared θ pair (same formula as app.core.pv.select.indep_diff)."""
    th = sorted(set(orig) & set(var))
    if not th:
        return None
    var_ = sum(orig[t]["rate"] * (1 - orig[t]["rate"]) / orig[t]["n"] + var[t]["rate"] * (1 - var[t]["rate"]) / var[t]["n"]
               for t in th)
    d = sum(var[t]["rate"] - orig[t]["rate"] for t in th) / len(th)
    se = math.sqrt(var_) / len(th)
    return {"d": d, "lo": d - Z * se, "hi": d + Z * se, "wOrig": sum(orig[t]["rate"] for t in th) / len(th),
            "wVar": sum(var[t]["rate"] for t in th) / len(th), "n": [orig[th[0]]["n"], var[th[0]]["n"]], "thetas": th}


def user_delta(p0, w0, w1):
    if None in (p0, w0, w1):
        return None
    return expit(logit(p0) + BETA * (logit(w1) - logit(w0))) - p0


def main():
    if OUT.exists():
        sys.exit(f"output exists, refusing to overwrite: {OUT}")
    t0 = time.time()
    before = {k: (sha(p), p.stat().st_mtime_ns) for k, p in INPUTS.items()}

    src = {it["meta"]["level_number"]: it["level_json"] for it in load(INPUTS["source_live3"])["levels"]
           if isinstance(it.get("meta", {}).get("level_number"), int)}
    lmb = {it["meta"]["level_number"]: it["level_json"] for it in load(INPUTS["livematch_batch"])["levels"]
           if isinstance(it.get("meta", {}).get("level_number"), int)}
    rows = load(INPUTS["r2_rows"])["rows"]
    cons = load(INPUTS["consensus_levels"])
    sep = {}
    for f in sorted((LIVE3 / "dda_sets_v2/sep/work").glob("*.json")):
        j = load(f)
        sep[j["level"]] = j
    p3 = {}
    for f in sorted((LIVE3 / "dda_sets_v2/work").glob("*/p3.json")):
        j = load(f)
        p3[j["level"]] = j
    prep = load(INPUTS["prep_L32_500"])
    mism = load(INPUTS["mismatch_report"])
    mism_levels = set(mism["summary"]["levels"])
    afm = {x["level"]: x for x in load(INPUTS["af_level_metrics_1014"])["levels"]}
    afr = {}
    with open(INPUTS["af_refresh_1019_csv"]) as fh:
        for r in csv.DictReader(fh):
            afr[int(r["level"])] = r
    pilotB = {x["level"]: x for x in load(INPUTS["pilot_B_v3_1"])["levels"]}
    pilotB_active = set(pilotB) - set(load(INPUTS["pilot_B_v3_1"]).get("removedMismatch", []))
    pilotA = {x["level"] for x in load(INPUTS["pilot_A_v2"])["levels"]}

    levels_out, variants_out = [], []
    hash_seen = defaultdict(list)
    for key in sorted(rows, key=lambda k: int(k.split("_")[1])):
        L = int(key.split("_")[1])
        row = rows[key]
        meta = load(LIVE3 / f"dda_sets/meta/{L}.json")
        seg = "32-100" if L <= 100 else "101-300" if L <= 300 else "301-500" if L <= 500 else "501-1000" if L <= 1000 else "1001-1500"
        h_live3 = af._map_hashes(src[L])[0]
        h_lm = af._map_hashes(lmb[L])[0]
        h_t0 = af._map_hashes(row["map"])[0] if isinstance(row.get("map"), dict) else None
        hash_seen[h_lm].append(L)
        live_ok = h_live3 == h_lm and L not in mism_levels
        c = cons.get(str(L))
        tiers_r2 = list(meta["tiers"].keys())
        a = afm.get(L, {})
        p0 = a.get("clean_ft_rate")
        n0 = a.get("clean_ft_n")
        rr = afr.get(L)
        excl = None
        if str(L) in prep and prep[str(L)].get("exclude"):
            excl = prep[str(L)]["exclude"]
        if c and c.get("exclude"):
            excl = c["exclude"]
        sp = sep.get(L)
        q3 = p3.get(L)

        reasons_c, reasons_b = [], []
        if not live_ok:
            reasons_c.append("live_map_mismatch(doc13 §6 / 10 §9-10: LIVE3≠live shard → re-t0 + full re-run)")
        if excl:
            reasons_c.append(f"forced_exclusion:{excl}")
        if c and c.get("disagree"):
            reasons_c.append(f"bot_disagree:{c.get('disagreeKind')}:{','.join(c.get('disagreeSide') or [])}")
        if L in P5:
            reasons_c.append("P5_quarantine(doc42 §6)")
        if c is None:
            reasons_b.append("v1_only(no v2 recheck: L1001+ outside ③/sep)")
        elif not (c.get("consensus010v2") or c.get("disagree")):
            reasons_b.append("not_consensus_not_disagree(borderline: v1 fresh or v2 |Δ| below rule)")
        outer_verify_fail = [f for f in (c or {}).get("verifyFail") or [] if f.split(":")[-1] in ("e2", "h2")]
        if outer_verify_fail:
            reasons_b.append("07_independent_verify_outer_fail:" + "|".join(outer_verify_fail))
        cls = "C" if reasons_c else "B" if reasons_b else "A"

        five = bool(c and c.get("innerConsensus") and meta["status"] == "5tier")
        use_tiers = ["e2", "e1", "h1", "h2"] if five else ["e2", "h2"]
        tier_recs = {}
        for t in tiers_r2:
            tm = meta["tiers"][t]
            st = {}
            if c:
                st = (c["outer"].get(t) or c["inner"].get(t) or {})
            ci_a = ci_b = None
            if sp:
                if tm["key"] in sp["a_v1"]:
                    ci_a = pair_ci(sp["a_v1"]["orig"], sp["a_v1"][tm["key"]])
                if tm["key"] in sp["b_v2"]:
                    ci_b = pair_ci(sp["b_v2"]["orig"], sp["b_v2"][tm["key"]])
            ci_lo_c = (q3 or {}).get("tiers", {}).get(t, {}).get("ciLo")
            vals = [st.get(s) for s in STAGES if st.get(s) is not None] or [tm["delta"]]
            want = 1 if t.startswith("e") else -1
            signs_ok = all(v * want > 0 for v in vals)
            rec = {
                "level": L, "tier": t, "variantId": f"seedvar_{L}:{t}", "token": tm["token"], "candKey": tm["key"],
                "variantIdHash16": hashlib.sha256(f"{h_t0}|{tm['token']}".encode()).hexdigest()[:16] if h_t0 else None,
                "r2": {"delta": r4(tm["delta"]), "ci": [r4(x) for x in tm["ci"]] if tm.get("ci") else None,
                       "bot": "v1", "thetas": meta["thetas"], "games_per_theta": 950, "seedBand": "S2 7.0M",
                       "robustPoints": meta.get("robustPoints"), "solver": tm.get("solver"), "evidence": tm.get("evidence")},
                "a_v1_fresh": ci_a and {"delta": r4(ci_a["d"]), "ci": [r4(ci_a["lo"]), r4(ci_a["hi"])], "thetas": ci_a["thetas"],
                                        "games_per_theta": ci_a["n"][1], "seedBand": "7.6M"},
                "b_v2_samePair": ci_b and {"delta": r4(ci_b["d"]), "ci": [r4(ci_b["lo"]), r4(ci_b["hi"])], "thetas": ci_b["thetas"],
                                           "games_per_theta": ci_b["n"][1], "seedBand": "7.8M new / 7.2M reused(③)"},
                "c_v2_ownPair": q3 and {"delta": r4(st.get("c")), "ciLo_abs": ci_lo_c, "thetas": q3.get("thetasV2"),
                                        "games_per_theta": 950, "seedBand": "7.2M(S2)/9.3M(robust)"},
                "stageDeltas": {s: st.get(s) for s in STAGES} if c else {"R2": r4(tm["delta"])},
                "signConsistent": signs_ok, "minAbsDelta": r4(min(abs(v) for v in vals)),
                "nStages": len(vals),
                "verify07": None if not c or not c.get("verified") else
                ("fail" if any(f.endswith(":" + t) for f in c.get("verifyFail") or []) else "pass"),
                "provisionalUserDelta_beta0429": None,
            }
            if t in ("e2", "h2") and p0 is not None and n0 and n0 >= 100:
                rec["provisionalUserDelta_beta0429"] = {
                    "v1_a": r4(user_delta(p0, ci_a["wOrig"], ci_a["wVar"])) if ci_a else None,
                    "v2_b": r4(user_delta(p0, ci_b["wOrig"], ci_b["wVar"])) if ci_b else None,
                    "note": "PROVISIONAL (doc25 β=0.429 from L1~31 natural experiment) — not a validated user clear rate"}
            rec["useInSet"] = cls == "A" and t in use_tiers
            rec["notUsedReason"] = None if rec["useInSet"] else (
                f"set class {cls}" if cls != "A" else "inner tier: no 4-stage inner consensus → set used as 3 tiers")
            tier_recs[t] = rec
            variants_out.append(rec)

        lev = {
            "level": L, "segment": seg, "class": cls, "reasonsC": reasons_c, "reasonsB": reasons_b,
            "r2Status": meta["status"], "setTiersUsable": (("5tier" if five else "3tier") if cls == "A" else None),
            "nVariantsUsable": (len(use_tiers) if cls == "A" else 0), "nVariantsR2": len(tiers_r2),
            "canonicalMapSha256": {"live3_source": h_live3, "livematch_batch": h_lm, "t0_copy_row": h_t0},
            "liveMapMatch": live_ok, "inMismatch34": L in mism_levels,
            "consensusTag": (c or {}).get("consensusTag"), "consensus013": (c or {}).get("consensus013"),
            "consensus010v2": (c or {}).get("consensus010v2"), "disagree": (c or {}).get("disagree"),
            "disagreeKind": (c or {}).get("disagreeKind"), "v1Pass": (c or {}).get("v1Pass"),
            "innerConsensus": (c or {}).get("innerConsensus"), "verified07": (c or {}).get("verified"),
            "verifyPass07": (c or {}).get("verifyPass"), "verifyFail07": (c or {}).get("verifyFail"),
            "botVersions": ["v1(R2)", "v1(a)", "v2(b)", "v2(c)"] if c else ["v1(R2)"],
            "botV2_blob": "faadc98" if c else None, "botV23_V24_measured": False,
            "protocol": {"R2": "scan 8θ×64 → θ pair W≈0.5 (trough [0.34,0.50) excl) → S1 64 → S2 950/θ; robust 600/pt; CI z=2.4977",
                         "a": "v1, R2 θ pair, 950/θ, seeds 7.6M", "b": "v2, R2 θ pair, 950/θ, 7.8M (+③ reuse)",
                         "c": "v2, v2 θ pair, 950/θ + robust 600"} if c else {"R2": "as above (v1 only)"},
            "thetasR2": meta["thetas"], "thetasV2": (q3 or {}).get("thetasV2"), "wOrigR2": r4(meta.get("wOrig")),
            "afOriginal_1014_cleanFt": {"n": n0, "rate": p0, "map_match": a.get("map_match"),
                                        "window": "2026-09-08~10-14", "metric": "first-try unaided (clean_ft)"} if a else None,
            "afOriginal_1019_ftAny_sameMap": ({"n": int(rr["combined_same_n"]) if rr["combined_same_n"] else None,
                                                "rate": float(rr["combined_same_rate"]) if rr["combined_same_rate"] else None,
                                                "metric": "first-try ended incl. help (ft_any), doc 40"} if rr else None),
            "afVariant": None,
            "afN100": bool(n0 and n0 >= 100),
            "pilotB_v3_1": L in pilotB_active, "pilotB_v3_1_expose": (pilotB.get(L) or {}).get("expose") if L in pilotB_active else None,
            "pilotA_v2": L in pilotA, "p5": L in P5, "exclusion": excl,
            "tiers": tier_recs,
        }
        levels_out.append(lev)

    dup = {h: ls for h, ls in hash_seen.items() if len(ls) > 1}

    def agg(filter_fn=lambda x: True):
        out = Counter()
        for x in levels_out:
            if filter_fn(x):
                out[x["class"]] += 1
        return dict(out)

    seg_tab = {}
    for seg in ("32-100", "101-300", "301-500", "501-1000", "1001-1500"):
        rowsS = [x for x in levels_out if x["segment"] == seg]
        seg_tab[seg] = {
            "levels": len(rowsS), **{k: sum(1 for x in rowsS if x["class"] == k) for k in "ABC"},
            "A_5tier": sum(1 for x in rowsS if x["setTiersUsable"] == "5tier"),
            "A_3tier": sum(1 for x in rowsS if x["setTiersUsable"] == "3tier"),
            "A_consensus013": sum(1 for x in rowsS if x["class"] == "A" and x["consensus013"]),
            "A_afN100": sum(1 for x in rowsS if x["class"] == "A" and x["afN100"]),
            "A_variantsUsable": sum(x["nVariantsUsable"] for x in rowsS),
            "B_variantsR2": sum(x["nVariantsR2"] for x in rowsS if x["class"] == "B"),
            "C_variantsR2": sum(x["nVariantsR2"] for x in rowsS if x["class"] == "C"),
        }
    reasonC = Counter(r.split(":")[0].split("(")[0] for x in levels_out for r in x["reasonsC"])
    reasonB = Counter(r.split(":")[0].split("(")[0] for x in levels_out for r in x["reasonsB"] if x["class"] == "B")
    reasonC_primary = Counter()
    for x in levels_out:
        if x["class"] == "C":
            reasonC_primary["+".join(sorted({r.split(":")[0].split("(")[0] for r in x["reasonsC"]}))] += 1

    # timing basis from stored logs/records (no measurement)
    r2_wall = defaultdict(float)
    r2_cnt = Counter()
    for f in (LIVE3 / "dda_sets/meta").glob("*.json"):
        j = load(f)
        if j.get("wallSec") and j.get("status") in ("5tier", "3tier", "none"):
            L = j["level"]
            s = "32-500" if L <= 500 else "501-1000" if L <= 1000 else "1001-1500"
            r2_wall[s] += j["wallSec"]
            r2_cnt[s] += 1
    sep_wall = sum(x["wall"] for x in sep.values())
    sep_cpu = sum(x["cpuSec"] for x in sep.values())
    sep_games = sum(950 * (sum(len(v) for k, v in x["a_v1"].items()) + x.get("bMeasured", 0)) for x in sep.values())
    p3_wall = sum(x.get("wall", 0) for x in p3.values())
    p3_cpu = sum(x.get("cpuSec", 0) for x in p3.values())
    timing = {
        "r2_wallSec_by_segment(measured levels incl. 'none')": {s: {"sumSec": round(r2_wall[s]), "levels": r2_cnt[s],
                                                                    "meanSec": round(r2_wall[s] / r2_cnt[s], 1)} for s in r2_wall},
        "sep": {"levels": len(sep), "wallSumSec(per-level, workers overlap)": round(sep_wall), "cpuSec": round(sep_cpu),
                "games_est": sep_games, "cpuSecPerGame": round(sep_cpu / sep_games, 4) if sep_games else None,
                "doc10_reported": "6.5 h wall, 25.4 h CPU, 4 workers, CPU shared"},
        "p3": {"levels": len(p3), "wallSumSec": round(p3_wall), "cpuSec": round(p3_cpu),
               "doc10_reported": "5.2 h wall, 19.8 h CPU, 4 workers"},
        "doc26_doc33_rates": "v2.3/v2.4 0.020~0.045 CPU s/game (θ0.65~1.0, L32~500 maps, 2~3 procs)",
    }

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universe": "R2 current seedvar_N rows (dda_sets/seedvar_rows.json) = 296 levels; one level = one candidate set (orig + e2 + h2 [+ e1 + h1])",
        "classes": {"A": "existing evidence only → offline pilot package possible (NOT live-validated, NOT release-approved)",
                    "B": "needs additional confirmation measurement for some tiers (v2.x confirm) before use",
                    "C": "hold: condition mismatch (live map / forced exclusion / P5) or bot-version disagreement"},
        "totals": agg(), "bySegment": seg_tab, "reasonsC_count(multi)": dict(reasonC), "reasonsC_combo": dict(reasonC_primary),
        "reasonsB_count(multi, class B only)": dict(reasonB),
        "A_levels": [x["level"] for x in levels_out if x["class"] == "A"],
        "B_levels": [x["level"] for x in levels_out if x["class"] == "B"],
        "C_levels": [x["level"] for x in levels_out if x["class"] == "C"],
        "A_pilot_eligible(L32-500, afN>=100, live ok)": [x["level"] for x in levels_out if x["class"] == "A" and x["afN100"]
                                                          and x["segment"] in ("32-100", "101-300", "301-500")],
        "pilotB_v3_1_classes": {x["level"]: x["class"] for x in levels_out if x["pilotB_v3_1"]},
        "duplicateMapHashes_livematch": dup,
        "variants": {"R2_total": sum(x["nVariantsR2"] for x in levels_out),
                     "A_usable": sum(x["nVariantsUsable"] for x in levels_out)},
        "timing_basis": timing,
        "checks": {},
    }
    after = {k: (sha(p), p.stat().st_mtime_ns) for k, p in INPUTS.items()}
    summary["checks"] = {"inputs_unchanged": before == after, "levels": len(levels_out),
                         "consensus_scope_levels": len(cons), "sep_levels": len(sep), "p3_levels": len(p3),
                         "mismatch_in_R2": sorted(x["level"] for x in levels_out if x["inMismatch34"]),
                         "hash_live3_ne_livematch": sorted(x["level"] for x in levels_out
                                                           if x["canonicalMapSha256"]["live3_source"] != x["canonicalMapSha256"]["livematch_batch"]),
                         "elapsed_sec": round(time.time() - t0, 2)}

    OUT.mkdir(parents=True)
    (OUT / "levels.json").write_text(json.dumps(levels_out, ensure_ascii=False, indent=1))
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    cols = ["level", "segment", "class", "setTiersUsable", "nVariantsUsable", "r2Status", "consensusTag", "disagreeKind",
            "liveMapMatch", "p5", "exclusion", "afN1014", "p0_1014", "pilotB_v3_1", "verifyPass07", "livematchSha256_12", "reasons"]
    with open(OUT / "levels.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for x in levels_out:
            af_ = x["afOriginal_1014_cleanFt"] or {}
            w.writerow([x["level"], x["segment"], x["class"], x["setTiersUsable"], x["nVariantsUsable"], x["r2Status"],
                        x["consensusTag"], x["disagreeKind"], x["liveMapMatch"], x["p5"], x["exclusion"], af_.get("n"),
                        af_.get("rate"), x["pilotB_v3_1"], x["verifyPass07"], x["canonicalMapSha256"]["livematch_batch"][:12],
                        " | ".join(x["reasonsC"] + x["reasonsB"])])
    vcols = ["level", "tier", "token", "variantIdHash16", "useInSet", "notUsedReason", "R2", "a", "b", "c", "signConsistent",
             "minAbsDelta", "ciR2", "ciA", "ciB", "ciLoC", "verify07", "puD_v1a", "puD_v2b"]
    with open(OUT / "variants.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(vcols)
        for v in variants_out:
            sd = v["stageDeltas"]
            pu = v["provisionalUserDelta_beta0429"] or {}
            w.writerow([v["level"], v["tier"], v["token"], v["variantIdHash16"], v["useInSet"], v["notUsedReason"],
                        *(r4(sd.get(s)) for s in STAGES), v["signConsistent"], v["minAbsDelta"], v["r2"]["ci"],
                        (v["a_v1_fresh"] or {}).get("ci"), (v["b_v2_samePair"] or {}).get("ci"),
                        (v["c_v2_ownPair"] or {}).get("ciLo_abs"), v["verify07"], pu.get("v1_a"), pu.get("v2_b")])
    files = ["levels.json", "summary.json", "levels.csv", "variants.csv"]
    manifest = {"script": str(Path(__file__).relative_to(ROOT)), "script_sha256": sha(Path(__file__)),
                "command": "backend/venv/bin/python backend/scripts/dda_readiness_20261019.py",
                "inputs": {k: {"path": str(p.relative_to(ROOT)), "sha256": before[k][0]} for k, p in INPUTS.items()},
                "inputs_dirs_read": ["dda_sets/meta/*.json", "dda_sets_v2/sep/work/*.json", "dda_sets_v2/work/*/p3.json"],
                "outputs": {f: sha(OUT / f) for f in files}, "generated_at": summary["generated_at"],
                "inputs_unchanged": summary["checks"]["inputs_unchanged"]}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    with open(OUT / "SHA256SUMS", "w") as fh:
        for f in files + ["MANIFEST.json"]:
            fh.write(f"{sha(OUT / f)}  {f}\n")
    print(json.dumps({"totals": summary["totals"], "bySegment": seg_tab, "reasonsC_combo": dict(reasonC_primary),
                      "reasonsB": dict(reasonB), "variants": summary["variants"], "dup": dup,
                      "pilotB": summary["pilotB_v3_1_classes"], "checks": summary["checks"],
                      "A_pilot_eligible": summary["A_pilot_eligible(L32-500, afN>=100, live ok)"],
                      "timing": timing}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
