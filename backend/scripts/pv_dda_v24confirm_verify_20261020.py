"""Read-only / pure verification of a v2.4 confirmation package (no bot games are played).

Checks: completeness (all queued levels present), duplicates (levels, variant keys, tokens within a set), P5 levels absent,
seed-band separation (exploration vs independent confirmation vs earlier selection bands, by actual seed ranges),
recorded judgement reproducible from stored measurements under PREREG thresholds, base-map hashes
(livematch == live3 for PASS sets), bot-map hashes recomputed (pure t0 shuffle, no simulation), file SHA256 vs SHA256SUMS.
Usage: venv/bin/python scripts/pv_dda_v24confirm_verify_20261020.py <package_dir>
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda_v24confirm_20261019 as C  # noqa: E402

P = C.P


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main(pkg):
    out, fails = {}, []

    def check(name, ok, detail=""):
        out[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            fails.append(name)

    q = C.load(os.path.join(C.OUT, "queue.json"))
    det = C.load(os.path.join(pkg, "results_detail.json"))
    allr = list(csv.DictReader(open(os.path.join(pkg, "all_results.csv"))))
    sets = list(csv.DictReader(open(os.path.join(pkg, "sets.csv"))))
    rows = C.load(os.path.join(pkg, "seedvar_rows_pass.json"))["rows"]
    qlv = [it["level"] for it in q]
    # completeness / duplicates
    check("queue155", len(q) == 155 and len(set(qlv)) == 155, f"queue {len(q)}, unique {len(set(qlv))}")
    check("allResultsComplete", sorted(int(r["level"]) for r in allr) == sorted(qlv)
          and all(r["status"] != "NOT_MEASURED" for r in allr), f"rows {len(allr)}")
    check("detailComplete", sorted(int(k) for k in det) == sorted(qlv) and all(det[k]["result"] for k in det))
    passes = [r for r in allr if r["status"] in ("PASS3", "PASS5")]
    check("setsMatchPass", sorted(int(s["level"]) for s in sets) == sorted(int(r["level"]) for r in passes)
          and len(rows) == len(sets) and len(os.listdir(os.path.join(pkg, "maps"))) == len(sets), f"pass {len(passes)}")
    check("noDupSetLevels", len({s["level"] for s in sets}) == len(sets))
    dup_var = []
    for it in q:
        keys = list(it["tiers"].values())
        if len(set(keys)) != len(keys):
            dup_var.append(it["level"])
    for s in sets:
        toks = s["randSeed"].split("|")
        if len(set(toks)) != len(toks):
            dup_var.append(int(s["level"]))
    check("noDupVariantsWithinSet", not dup_var, f"{dup_var}")
    # P5
    p5 = sorted(C.P5 & (set(qlv) | {int(s["level"]) for s in sets}))
    check("noP5", not p5, f"P5 present: {p5}")
    # seed bands: actual ranges used
    pts_scan = len(P.SCAN_THETAS)
    rng = {"scan": (C.SEED["scan"], C.SEED["scan"] + (pts_scan - 1) * 10_000 + P.SCAN_GAMES),
           "pair": (C.SEED["pair"], C.SEED["pair"] + 1 * 10_000 + C.PAIR_GAMES),
           "rob": (C.SEED["rob"] + 2 * 10_000, C.SEED["rob"] + 5 * 10_000 + C.ROB_GAMES),
           "ind": (C.SEED["ind"], C.SEED["ind"] + 1 * 10_000 + C.PAIR_GAMES)}
    earlier = {"R2scan": P.SEED_SCAN, "R2s1": P.SEED_S1, "R2s2": P.SEED_S2, "R2rob": P.SEED_ROBUST, "a": 7_600_000,
               "b": 7_800_000, "v2scan": 5_200_000, "v2s2": 7_200_000, "v2rob": 9_300_000, "v2hi": 9_500_000}
    for k, b in earlier.items():
        rng[k] = (b, b + 10 * 10_000 + 1000)
    ov = [(a, b) for a in rng for b in rng if a < b and rng[a][0] < rng[b][1] and rng[b][0] < rng[a][1]]
    check("seedBandsDisjoint", not ov, f"ranges {rng}; overlaps {ov}")
    # judgement reproducible from stored measurements (PREREG thresholds as coded)
    mism = []
    for it in q:
        d = det[str(it["level"])]
        r = d["result"]
        if r["status"].startswith("HOLD") and "unevaluable" in r.get("reason", ""):
            if d["scan"]["choice"]["evaluable"]:
                mism.append(it["level"])
            continue
        th = d["scan"]["choice"]["thetas"]
        xt, lt = P.extra_theta(d["scan"]["rates"], th), P.low_theta(th, P.extra_theta(d["scan"]["rates"], th))
        rj = C.judge(it, th, xt, lt, d["c1"], d["c2"])
        if rj["status"] != r["status"]:
            mism.append(it["level"])
    check("judgementReproduced", not mism, f"mismatch {mism}")
    # base map hashes
    bad_base = [s["level"] for s in sets if s["baseMapSha256_livematch"] != s["baseMapSha256_live3"]]
    check("baseMapLiveMatch", not bad_base, f"{bad_base}")
    # recompute bot-map hashes (pure, no simulation) for PASS sets
    bad_h = []
    for s in sets:
        n = int(s["level"])
        prep = P.W(n).get("prep.json")
        r = det[str(n)]["result"]
        if C.lj_hash(P.lj_orig(prep)) != r["mapHash16"]["orig"]:
            bad_h.append((n, "orig"))
        for t, v in r["tiers"].items():
            if C.lj_hash(P.lj_seed(prep, v["key"])) != r["mapHash16"][v["key"]]:
                bad_h.append((n, t))
    check("botMapHashes", not bad_h, f"{bad_h}")
    # tokens in rows == tokens in result tiers
    bad_t = []
    for s in sets:
        r = det[s["level"]]["result"]
        use = s["tiersUsed"].split("|")
        if s["randSeed"] != "|".join(str(r["tiers"][t]["token"]) for t in use) or \
                rows[f"seedvar_{s['level']}"]["randSeed"] != s["randSeed"]:
            bad_t.append(s["level"])
    check("tokensConsistent", not bad_t, f"{bad_t}")
    # file hashes
    bad_f = []
    for line in open(os.path.join(pkg, "SHA256SUMS")):
        h, fn = line.rstrip("\n").split("  ", 1)
        if sha(os.path.join(pkg, fn)) != h:
            bad_f.append(fn)
    man = C.load(os.path.join(pkg, "MANIFEST.json"))
    for fn, h in man["files"].items():
        if sha(os.path.join(pkg, fn)) != h:
            bad_f.append("manifest:" + fn)
    check("fileSha256", not bad_f, f"{bad_f}")
    check("preregUnchanged", sha(os.path.join(C.OUT, "PREREG.json")) == man["prereg"]["sha256"])
    rep = {"package": pkg, "checks": out, "allOk": not fails, "failed": fails}
    C.save(os.path.join(os.path.dirname(pkg), os.path.basename(pkg) + "_VERIFY.json"), rep)
    print(json.dumps({k: v["ok"] for k, v in out.items()}, ensure_ascii=False), "ALL OK" if not fails else f"FAILED {fails}")


if __name__ == "__main__":
    main(sys.argv[1])
