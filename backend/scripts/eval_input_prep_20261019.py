"""Doc 42 — evaluation inputs for a future clear-rate retrain comparison (static, read-only aggregation).

No bot simulation, no training, no network, no server API. Reads stored artifacts only and writes a NEW directory
(refuses to overwrite). Inputs are never modified.

  inputs : active model cr-ftany-v24r-20261016 (manifest/model/bot_cache, _wt_clearrate worktree),
           af_calibration/{level_metrics.json (AF 10-14), refresh_20261019/{summary,bot_join_verified}.json (AF 10-19, docs 40/41),
           bot_v21/{prep,af}.json, cand_a1a2/{prep_ext,bot_v24_rules_A2}.json, bot_v24/{bot_v2.4f_no_rules_only,
           bot_v2.4f_no_covered_info,abl_rules_only_rows}.json, lowband/compare.json (doc 36 sealed set)},
           candidate model dirs C1/C2/C3 (train level lists only)
  outputs: af_calibration/eval_inputs/20261019/{classification,train379_fixed_eval,existing40,added13,
           protocol_review,MANIFEST}.json

Run from the main repo root with the backend venv (needs pydantic for app.core.pv.canonical):
  backend/venv/bin/python backend/scripts/eval_input_prep_20261019.py
"""
import hashlib
import importlib.util
import json
import math
import platform
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
import af_level_metrics as af  # noqa: E402  (only _map_hashes / OUT_DIR used; no CSV reading)

CAL = af.OUT_DIR
OUT = CAL / "eval_inputs" / "20261019"
WT = Path("/Users/casualdev/TileMatchAutoLevel_wt_clearrate/backend")
MODELS = WT / "data/models/clear_rate"
ACTIVE = MODELS / "cr-ftany-v24r-20261016"
CANDS = {"C1": "cr-ftany-v24r-cand-20261016-a1", "C2": "cr-ftany-v24r-cand-20261016-a1a2",
         "C3": "cr-ftany-v24r-cand-20261016-a1a2x"}
ADDED13_EXPECTED = [33, 498, 505, 507, 521, 531, 537, 551, 558, 566, 568, 577, 578]
RULES = {"unknown_hide", "curtain_hide", "unknown_nobonus", "ac_inner", "stack_hide", "dock_rel"}
THETAS = (0.55, 0.65, 0.85, 1.0)
Z = 1.959963984540054

INPUTS = {
    "model_manifest": ACTIVE / "manifest.json",
    "model_json": ACTIVE / "model.json",
    "bot_cache": ACTIVE / "bot_cache.json",
    "conditions_py": WT / "app/core/clear_rate/conditions.py",
    "level_metrics_20261014": CAL / "level_metrics.json",
    "refresh_summary_20261019": CAL / "refresh_20261019/summary.json",
    "bot_join_verified_20261019": CAL / "refresh_20261019/bot_join_verified.json",
    "prep": CAL / "bot_v21/prep.json",
    "af_v21": CAL / "bot_v21/af.json",
    "prep_ext": CAL / "cand_a1a2/prep_ext.json",
    "bot_rules_only": CAL / "bot_v24/bot_v2.4f_no_rules_only.json",
    "bot_no_covered_info": CAL / "bot_v24/bot_v2.4f_no_covered_info.json",
    "abl_rules_only_rows": CAL / "bot_v24/abl_rules_only_rows.json",
    "bot_A2": CAL / "cand_a1a2/bot_v24_rules_A2.json",
    "lowband_compare": CAL / "lowband/compare.json",
    **{f"cand_{k}_model": MODELS / v / "model.json" for k, v in CANDS.items()},
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def wilson(k, n):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def r4(x):
    return None if x is None else round(x, 4)


def blk(b):
    """AF block from refresh summary (n, clear, helped) → ft_any / help rate, Wilson on ft_any."""
    n, c, h = b["n"], b.get("clear", 0), b.get("helped", 0)  # empty blocks (e.g. L33 same-map n=0) carry n only
    return {"n": n, "clear": c, "helped": h, "no_end": b.get("no_end"),
            "ft_any": r4(c / n) if n else None, "wilson95": wilson(c, n),
            "help_rate": r4(h / n) if n else None}  # unaided LB not derivable from summary (helped incl. failed runs)


def main():
    assert not OUT.exists(), f"output exists, refusing to overwrite: {OUT}"
    t0 = time.time()
    in_sha = {k: sha(p) for k, p in INPUTS.items()}
    in_mtime = {k: Path(p).stat().st_mtime_ns for k, p in INPUTS.items()}

    spec = importlib.util.spec_from_file_location("cr_conditions", INPUTS["conditions_py"])
    CN = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CN)

    man, mdl, cache = load(INPUTS["model_manifest"]), load(INPUTS["model_json"]), load(INPUTS["bot_cache"])
    checks = {}
    checks["model_json_sha_matches_manifest"] = in_sha["model_json"] == man["model_json_sha256"]
    checks["bot_cache_sha_matches_manifest"] = in_sha["bot_cache"] == man["bot_cache_sha256"]
    LMdoc = load(INPUTS["level_metrics_20261014"])
    checks["level_metrics_generated_at_matches_manifest"] = (
        LMdoc["generated_at"] == man["train_data"]["af_level_metrics_generated_at"])
    LM = {r["level"]: r for r in LMdoc["levels"]}
    S = load(INPUTS["refresh_summary_20261019"])
    SL = {a["level"]: a for a in S["levels"]}
    J = load(INPUTS["bot_join_verified_20261019"])
    prep = {int(k): v for k, v in load(INPUTS["prep"]).items()}
    AFv21 = {int(k): v for k, v in load(INPUTS["af_v21"]).items()}
    pext = {int(k): v for k, v in load(INPUTS["prep_ext"])["levels"].items()}
    allprep = {**prep, **pext}
    checks["prep_ext_disjoint_from_prep"] = not (set(prep) & set(pext))

    def hashes(L):
        p = allprep[L]
        return {"canonical_map_sha256": af._map_hashes(p["map"])[0],
                "maphash12_sha1": hashlib.sha1(json.dumps(p["map"], sort_keys=True).encode()).hexdigest()[:12],
                "cond_hash20": CN.cond_hash(p["map"], p["row"]),
                "conditions_sha256": hashlib.sha256(json.dumps(p["row"], sort_keys=True).encode()).hexdigest(),
                "map_source": "bot_v21/prep.json" if L in prep else "cand_a1a2/prep_ext.json"}

    # ── active training set (379) ──
    train = mdl["support"]["train_levels"]
    checks["train_n"] = len(train)
    checks["train_unique"] = len(set(train)) == len(train)
    checks["train_n_matches_manifest"] = len(train) == man["train_data"]["n_levels"] == mdl["support"]["n_train"]
    TH = {L: hashes(L) for L in train}
    by_cond = {h["cond_hash20"]: L for L, h in TH.items()}
    by_map = {h["maphash12_sha1"]: L for L, h in TH.items()}
    by_canon = {h["canonical_map_sha256"]: L for L, h in TH.items()}
    checks["train_hash_unique"] = {"cond": len(by_cond), "maphash12": len(by_map), "canonical": len(by_canon)}

    # bot_cache ↔ rules-only rows for the 379
    ro_rows = load(INPUTS["bot_rules_only"])["rows"]
    ro = {}
    for r in ro_rows:
        ro.setdefault(r["L"], {})[round(float(r["theta"]), 2)] = r
    cache_bad = []
    for L in train:
        e = cache.get(TH[L]["cond_hash20"])
        ok = bool(e) and e["L"] == L and all(
            (row["games"], row["wins"], row["fail_reasons"]) ==
            (ro[L][row["theta"]]["games"], ro[L][row["theta"]]["wins"], ro[L][row["theta"]]["fail_reasons"])
            for row in e["rows"]) and [row["theta"] for row in e["rows"]] == list(THETAS)
        if not ok:
            cache_bad.append(L)
    checks["train379_bot_cache_rows_equal_rules_only_file"] = not cache_bad
    checks["train379_bot_cache_mismatch"] = cache_bad

    # ── reusable 53 (doc 41) and classification by hash ──
    J53 = [r for r in J["levels"] if r["status"] == "reusable_candidate" and r["af_n"] >= 100]
    checks["reusable_n"] = len(J53)
    cls = []
    for r in J53:
        L = r["level"]
        h = hashes(L)
        hit = {"cond": by_cond.get(h["cond_hash20"]), "maphash12": by_map.get(h["maphash12_sha1"]),
               "canonical": by_canon.get(h["canonical_map_sha256"])}
        hits = {v for v in hit.values() if v is not None}
        cat = "existing_train" if hits else "added_candidate"
        cls.append({"level": L, "category": cat, "train_level_by_hash": hit,
                    "level_number_in_train": L in set(train), "hash_and_number_agree": (L in set(train)) == bool(hits)
                    and (not hits or hits == {L}),
                    "join_canonical_sha256_equal": r.get("bot_map_sha256") == h["canonical_map_sha256"],
                    "join_conditions_sha256_equal": r.get("conditions_sha256") == h["conditions_sha256"], **h})
    ex40 = sorted(c["level"] for c in cls if c["category"] == "existing_train")
    ad = sorted(c["level"] for c in cls if c["category"] == "added_candidate")
    checks["existing_n"], checks["added_n"] = len(ex40), len(ad)
    checks["added_equals_user_list"] = ad == ADDED13_EXPECTED
    checks["hash_number_disagreements"] = [c["level"] for c in cls if not c["hash_and_number_agree"]]
    checks["join_hash_disagreements"] = [c["level"] for c in cls
                                         if not (c["join_canonical_sha256_equal"] and c["join_conditions_sha256_equal"])]
    # partial matches: map equal but conditions differ, or vice versa
    checks["partial_hash_matches"] = [c["level"] for c in cls if len({v for v in c["train_level_by_hash"].values()}) > 1]

    # cross-check: train levels with latest same-map ft_any <0.85 & n≥100 that are NOT among the 40
    lat_low = sorted(L for L in train if SL[L]["same"]["combined"]["n"] >= 100
                     and SL[L]["same"]["combined"]["rate"] < 0.85)
    old_low = sorted(L for L in train if LM[L]["ft_clear_rate_any_help"] < 0.85)
    checks["train_latest_lt085_n100"] = {"n": len(lat_low), "not_in_40": sorted(set(lat_low) - set(ex40)),
                                         "in_40_not_latest_low": sorted(set(ex40) - set(lat_low))}
    checks["train_old_lt085"] = {"n": len(old_low), "manifest_lt085_n": man["kfold"]["ft_any_by_actual"]["lt0.85"]["n"],
                                 "old_low_not_in_40": sorted(set(old_low) - set(ex40)),
                                 "in_40_not_old_low": sorted(set(ex40) - set(old_low))}

    # ── train379 fixed evaluation table (old AF vs latest AF) ──
    sealed = set(load(INPUTS["lowband_compare"])["sealed"]["levels"])

    def old_af(L):
        m = LM[L]
        n = m["first_try_ended"]
        c = round(m["ft_clear_rate_any_help"] * n)
        return {"n": n, "clear_derived": c, "ft_any": m["ft_clear_rate_any_help"], "wilson95": wilson(c, n),
                "help_rate": m["ft_help_rate"], "unaided_lb": m["unaided_clear_lower_bound"],
                "map_match": m.get("map_match")}

    def new_af(L):
        a = SL[L]
        return {"same_combined": blk(a["same"]["combined"]), "same_new_window_only": blk(a["same"]["new"]),
                "same_old_window_recomputed": blk(a["same"]["old_window"]),
                "all_known_combined": blk(a["all_known"]["combined"]),
                "versions": a["versions"], "baseline_n_in_summary": a["baseline_n"]}

    rows379, drift = [], Counter()
    for L in sorted(train):
        o, nw = old_af(L), new_af(L)
        sc = nw["same_combined"]
        # derivation check: refresh old_window vs level_metrics (same definition; doc 40 notes +65 late arrivals overall)
        ow = nw["same_old_window_recomputed"]
        drift["old_window_n_minus_level_metrics_n"] += ow["n"] - o["n"]
        if ow["n"] != o["n"]:
            drift["levels_with_old_window_n_change"] += 1
        if ow["n"] == o["n"] and (ow["clear"] != o["clear_derived"]):
            drift["levels_same_n_diff_clear"] += 1
        if ow["n"] == o["n"] and ow["help_rate"] is not None and abs(ow["help_rate"] - o["help_rate"]) > 1e-4:
            drift["levels_same_n_diff_help"] += 1
        lo, hi = o["wilson95"], sc["wilson95"]
        rows379.append({"level": L, **TH[L], "seg": "32-100" if L <= 100 else ("101-300" if L <= 300 else "301-500"),
                        "old_af_20261014": o, "latest_af_20261019": nw,
                        "delta": {"ft_any": r4(sc["ft_any"] - o["ft_any"]), "n": sc["n"] - o["n"],
                                  "wilson_overlap": not (lo[1] < hi[0] or hi[1] < lo[0])},
                        "same_eq_all_known": nw["same_combined"] == nw["all_known_combined"],
                        "in_reusable53": L in ex40, "in_doc36_sealed79": L in sealed,
                        "bot_cache_cond_hash_present": TH[L]["cond_hash20"] in cache})
    checks["old_vs_refresh_old_window"] = dict(drift)
    checks["train379_same_eq_all_known"] = sum(r["same_eq_all_known"] for r in rows379)
    checks["train379_latest_n_lt100"] = [r["level"] for r in rows379 if r["latest_af_20261019"]["same_combined"]["n"] < 100]
    checks["train379_n_decreased"] = [r["level"] for r in rows379 if r["delta"]["n"] < 0]

    # ── existing 40 ──
    by_L379 = {r["level"]: r for r in rows379}
    existing40 = []
    for L in ex40:
        r = by_L379[L]
        jr = next(x for x in J53 if x["level"] == L)
        existing40.append({**{k: r[k] for k in ("level", "seg", "canonical_map_sha256", "maphash12_sha1", "cond_hash20",
                                                 "conditions_sha256", "old_af_20261014", "delta", "in_doc36_sealed79")},
                           "latest_af_20261019": {k: r["latest_af_20261019"][k] for k in
                                                  ("same_combined", "same_new_window_only", "all_known_combined")},
                           "join": {"af_n": jr["af_n"], "af_rate": r4(jr["af_rate"]), "af_new_n": jr["af_new_n"],
                                    "matched_af_n": jr["matched_af_n"], "versions": jr["versions"]},
                           "old_source": {"file": "af_calibration/level_metrics.json",
                                          "generated_at": LMdoc["generated_at"],
                                          "fields": "first_try_ended, ft_clear_rate_any_help, ft_help_rate, "
                                                    "unaided_clear_lower_bound"},
                           "latest_source": {"file": "af_calibration/refresh_20261019/summary.json",
                                             "generated_at": S["meta"]["generated_at"],
                                             "fields": "levels[].same.{combined,new,old_window}, all_known.combined"}})

    # ── added 13 ──
    cands = {k: set(load(INPUTS[f"cand_{k}_model"])["support"]["train_levels"]) - set(train) for k in CANDS}
    A2 = load(INPUTS["bot_A2"])
    abl = {(r["L"], round(float(r["theta"]), 2)) for r in load(INPUTS["abl_rules_only_rows"])["rows"]}
    a2L = set(A2["meta"]["levels"])
    added13 = []
    for L in ad:
        jr = next(x for x in J53 if x["level"] == L)
        h = next(c for c in cls if c["level"] == L)
        a = SL[L]
        used = sorted(k for k, s in cands.items() if L in s)
        if L in a2L:
            src = {"file": "cand_a1a2/bot_v24_rules_A2.json", "bot_version": A2["meta"]["bot_version"],
                   "v24_items": A2["meta"]["v24_items"], "protocol": A2["meta"]["protocol"],
                   "seed_band": A2["meta"]["seed_band"], "seed_rule": A2["meta"]["seed_rule"],
                   "shard_commit": A2["meta"]["shard_commit"], "measured_at": A2["meta"]["measured_at"],
                   "row_source": "measured (A2)"}
        else:
            flags = sorted({f for t in THETAS for f in (ro[L][t].get("v24") or [])})
            src = {"file": "bot_v24/bot_v2.4f_no_rules_only.json", "bot_version": ro[L][1.0]["ver"],
                   "row_v24_flags": flags, "protocol": man["bot_protocol"], "seed_band": man["bot_seed_band"],
                   "seed_rule": man["bot_seed_rule"], "file_meta": "none in file — protocol from model manifest/doc 26",
                   "row_source": "re-measured in abl_rules_only_rows" if all((L, t) in abl for t in THETAS)
                   else "copied from bot_v2.4f_no_covered_info.json (ablation level set excluded it)"}
        reasons = []
        if used:
            reasons.append(f"used in doc 33 §12 comparison ({'/'.join(used)}) and doc 36 D394 — NOT independent validation")
        if L in sealed:
            reasons.append("in doc 36 sealed-79 set (already used as sealed evaluation)")
        if L > 500:
            reasons.append("outside active support level_range [32,500] — S2 inclusion needs range decision")
        if L in (505, 531):
            reasons.append("doc 33 C3: version-z significant level (excluded in C3)")
        if L == 531:
            reasons.append("runtime random layout (32 layouts × 4 games)")
        if L == 33:
            reasons.append("editor LIVE3 map differs (types); bot input = shipped shard map (2nd batch) — "
                           "active filter map_match==same excludes it; inclusion = filter policy change, map2nd=1")
        if L == 498:
            reasons.append("clean_ft_n 98 < 100 (A1 reason); rows copied from full combo but no behaviour-triggering "
                           "feature (grass only, autoCollectCount 0)")
        reasons.append("selected by low observed clear rate (outcome-dependent selection)")
        added13.append({"level": L, **{k: h[k] for k in ("canonical_map_sha256", "maphash12_sha1", "cond_hash20",
                                                          "conditions_sha256", "map_source")},
                        "editor_map_match_20261014": LM[L].get("map_match"),
                        "latest_af_20261019": {"same_combined": blk(a["same"]["combined"]),
                                               "all_known_combined": blk(a["all_known"]["combined"]),
                                               "all_known_new_window_only": blk(a["all_known"]["new"]),
                                               "basis": "all_known (shard-matched per doc 41)" if L == 33 else "same"},
                        "join": {"af_n": jr["af_n"], "af_rate": r4(jr["af_rate"]), "matched_af_n": jr["matched_af_n"],
                                 "versions": jr["versions"], "bot_rates": jr["bot_rates"]},
                        "bot_measurement": {"present": jr["bot_rows"] == 4, **src},
                        "in_active_bot_cache": h["cond_hash20"] in cache,
                        "used_in_prior_comparison": used, "already_used_in_comparison": bool(used),
                        "in_doc36_sealed79": L in sealed, "independent_validation": False,
                        "exclusion_or_hold_reason_candidates": reasons})

    # ── protocol review (rules-only rows that kept active behaviour items) ──
    noc = {(r["L"], round(float(r["theta"]), 2)): r for r in load(INPUTS["bot_no_covered_info"])["rows"]}
    lv_of = [L for L in sorted(prep) if not prep[L]["exclude"] and (AFv21[L]["clean_ft_n"] or 0) >= 100]

    def has(L, f):
        return int(prep[L]["row"].get("unlockTile") or 0) > 0 if f == "row_unlock" else prep[L]["features"].get(f, 0) > 0
    abl_sel = {L for L in lv_of if any(has(L, f) for f in ("stack", "eff_bomb", "row_unlock", "eff_curtain"))}
    checks["ablation_level_set_reproduced"] = abl_sel == {L for L, _ in abl}
    checks["ablation_level_set_n"] = len(abl_sel)

    def active_items(L):
        p, f, out = prep[L], prep[L]["features"], []
        if float(p["row"].get("autoCollectCount") or 0) > 0:
            out.append("ac_policy")
        if f.get("eff_curtain"):
            out.append("curtain_memory_v24")
        if f.get("eff_bomb"):
            out += ["bomb_beta", "bomb_impulse"]
        if f.get("stack"):
            out.append("stack_early")
        if int(p["row"].get("unlockTile") or 0) > 0:
            out.append("key_first")
        return out
    cache_by_L = {v["L"]: k for k, v in cache.items()}
    pr = []
    for L in sorted(ro):
        if all((L, t) in abl for t in THETAS) or not active_items(L):
            continue
        hL = hashes(L)
        pr.append({"level": L, "clean_ft_n_v21": AFv21[L]["clean_ft_n"], "exclude": prep[L]["exclude"],
                   "features": prep[L]["features"], "row": prep[L]["row"],
                   "behaviour_items_can_act": active_items(L),
                   "row_v24_flags": sorted({f for t in THETAS for f in (ro[L][t].get("v24") or [])}),
                   "rows_identical_to_no_covered_info": all(ro[L][t] == noc[(L, t)] for t in THETAS),
                   "in_abl_rules_only_rows": any((L, t) in abl for t in THETAS),
                   "in_active_train379": L in set(train),
                   "in_active_bot_cache": cache_by_L.get(L) == hL["cond_hash20"],
                   "in_candidates": sorted(k for k, s in cands.items() if L in s),
                   "in_reusable53": False,
                   "bot_join_status": next((x["status"] for x in J["levels"] if x["level"] == L), None),
                   "latest_af_same_combined": blk(SL[L]["same"]["combined"]),
                   **{k: hL[k] for k in ("canonical_map_sha256", "maphash12_sha1", "cond_hash20")}})

    # proxy effect size: on re-measured ablation levels, full-combo (no_covered_info) − rules-only win rate by gimmick group
    abl_rows = {(r["L"], round(float(r["theta"]), 2)): r for r in load(INPUTS["abl_rules_only_rows"])["rows"]}
    grp_d = {}
    for (L, t), r in abl_rows.items():
        f = prep[L]["features"]
        g = ("bomb+stack" if f.get("eff_bomb") and f.get("stack") else "bomb_only" if f.get("eff_bomb")
             else "stack_only" if f.get("stack") else "other")
        grp_d.setdefault(f"{g}|{t}", []).append((noc[(L, t)]["wins"] - r["wins"]) / r["games"])
    proxy = {k: {"n_levels": len(v), "mean_diff": r4(sum(v) / len(v)), "mean_abs_diff": r4(sum(map(abs, v)) / len(v)),
                 "max_abs_diff": r4(max(map(abs, v)))} for k, v in sorted(grp_d.items())}

    # ── duplicates / integrity ──
    all_eval = [*train, *ad]
    eh = [hashes(L)["maphash12_sha1"] if L not in TH else TH[L]["maphash12_sha1"] for L in all_eval]
    checks["train379_plus_added13_unique_levels"] = len(set(all_eval)) == len(all_eval)
    checks["train379_plus_added13_unique_maphash"] = len(set(eh)) == len(eh)
    checks["added13_wilson_lb_lt_ub"] = all(
        x["latest_af_20261019"]["same_combined"]["n"] == 0 or x["latest_af_20261019"]["same_combined"]["wilson95"][0] <
        x["latest_af_20261019"]["same_combined"]["wilson95"][1] for x in added13)
    checks["inputs_unchanged_during_run"] = all(Path(p).stat().st_mtime_ns == in_mtime[k] for k, p in INPUTS.items())
    checks["inputs_sha_unchanged_during_run"] = all(sha(p) == in_sha[k] for k, p in INPUTS.items())

    OUT.mkdir(parents=True)
    outs = {
        "classification.json": {"reusable53": cls, "existing40": ex40, "added13": ad, "checks": checks},
        "train379_fixed_eval.json": {"note": "fixed evaluation set = active model train_levels (379). old = level_metrics "
                                             "2026-10-14 (training target); latest = refresh 2026-10-19 same-map. "
                                             "Latest includes old samples (not independent).", "levels": rows379},
        "existing40.json": {"note": "reusable-53 ∩ active train set by hash. Old/latest are nested samples; Wilson "
                                    "overlap is descriptive only.", "levels": existing40},
        "added13.json": {"note": "reusable-53 not in active train set by hash. 12 of 13 were already used in doc 33 "
                                 "C1–C3 / doc 36 comparisons — never an independent validation set.", "levels": added13},
        "protocol_review.json": {"note": "rules-only file rows copied from bot_v2.4f_no_covered_info.json (all behaviour "
                                         "items except covered_info) on levels outside the ablation set "
                                         "(levels_of: not excluded ∩ clean_ft_n≥100) where a behaviour item can act.",
                                 "levels": pr,
                                 "proxy_effect_full_minus_rules_only_win_rate": {
                                     "note": "other levels (re-measured 274), same seeds; NOT the effect on the levels "
                                             "above — indicates the items do change outcomes on bomb/stack maps",
                                     "by_group_theta": proxy}},
    }
    files = {}
    for name, obj in outs.items():
        s = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False)
        (OUT / name).write_text(s, encoding="utf-8")
        files[name] = {"sha256": hashlib.sha256(s.encode("utf-8")).hexdigest(), "bytes": len(s.encode("utf-8"))}
    manifest = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                "script": str(Path(__file__).relative_to(BACKEND.parent)), "script_sha256": sha(__file__),
                "command": "backend/venv/bin/python backend/scripts/eval_input_prep_20261019.py",
                "python": platform.python_version(), "wall_sec": round(time.time() - t0, 2),
                "no_bot_no_training_no_network": True,
                "inputs": {k: {"path": str(p), "sha256": in_sha[k]} for k, p in INPUTS.items()},
                "outputs": files, "checks": checks}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "files": files, "checks": checks}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
