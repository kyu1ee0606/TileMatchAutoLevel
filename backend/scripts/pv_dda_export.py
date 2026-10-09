"""Collect DDA preparation results -> <sandbox>/dda_sets/ outputs (atomic writes). PREPARATION ONLY — NOT APPROVED.

Writes:
  seedvar/seedvar_N.json            primary rows (game IMPL_SPEC §V2-9-2), one file per level
  seedvar_rows.json                 bundle {"seedvar_N": row} (GameBoost upload format — NOT uploaded)
  reference_baked/easy_N.json, hard_N.json, easy_rows.json, hard_rows.json   reference only (D13 ③ style), NOT canonical
  meta/N.json                       per-level meta (seeds, utc, Δ, CI, robust, solver grade, invariants)
  coverage.json                     coverage by segment / status / reasons
  selection_dda.json                machine-readable selection + measurement conditions for independent verification

Usage: python scripts/pv_dda_export.py [--from 32 --to 1500]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from pv_dda import (  # noqa: E402
    DDA, GAP_MIN, H_HI_MIN, H_PRED_REL, INNER_MIN, OUTER_MIN, POOL_PLAN, ROBUST_GAMES, S1_GAMES, S2_GAMES,
    SCAN_GAMES, SEED_PRED, SEED_ROBUST, SEED_S1, SEED_S2, SEED_SCAN, SOLVER_NODES, TARGET, load,
)

NOTE = "PREPARATION ONLY — NOT APPROVED, NOT UPLOADED (TileMatchAutoLevel pv_sandbox). Game spec: IMPL_SPEC §V2-9-2."
SEGMENTS = [(32, 500), (501, 1000), (1001, 1500)]


def save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", type=int, default=32)
    ap.add_argument("--to", dest="hi", type=int, default=1500)
    args = ap.parse_args()
    work = os.path.join(DDA, "work")
    finals = {}
    for name in sorted(os.listdir(work)) if os.path.isdir(work) else []:
        fp = os.path.join(work, name, "final.json")
        if name.isdigit() and os.path.exists(fp) and args.lo <= int(name) <= args.hi:
            finals[int(name)] = (load(fp), os.path.join(work, name))
    seedvar_rows, easy_rows, hard_rows, sel_levels = {}, {}, {}, []
    for n, (fin, d) in sorted(finals.items()):
        st = fin["status"]
        meta = {"level": n, "status": st, "reason": fin.get("reason"), "wallSec": fin.get("wallSec")}
        if fin.get("candidates"):
            meta.update(levelRuleFeasible=fin["candidates"].get("levelRuleFeasible"), predOrig=fin["candidates"].get("predOrig"),
                        candidates={sd: fin["candidates"][sd] for sd in ("easy", "hard")},
                        sensitiveStats={sd: {"judged": fin["candidates"][sd]["nJudged"],
                                             "sensitive": fin["candidates"][sd]["nSensitive"]} for sd in ("easy", "hard")})
        if st in ("5tier", "3tier"):
            row = load(os.path.join(d, "seedvar_row.json"))
            seedvar_rows[f"seedvar_{n}"] = row
            save(os.path.join(DDA, "seedvar", f"seedvar_{n}.json"), {"_note": NOTE, "id": f"seedvar_{n}", **row})
            for name, tgt in (("easy", easy_rows), ("hard", hard_rows)):
                r = load(os.path.join(d, f"baked_{name}.json"))
                tgt[f"{name}_{n}"] = r
                save(os.path.join(DDA, "reference_baked", f"{name}_{n}.json"),
                     {"_note": "REFERENCE ONLY (not canonical, D13 ③ style bake of the same selection). " + NOTE,
                      "id": f"{name}_{n}", **r})
            meta.update(token=fin["token"], grade=fin["grade"], tiers=fin["tiers"], thetas=fin["thetas"],
                        robustPoints=fin["robustPoints"], wOrig=fin["wOrig"], predOrig=fin.get("predOrig"),
                        orderOk=fin.get("orderOk"), warnings=fin.get("warnings"), invariantIssues=fin.get("invariantIssues"),
                        utc0=fin["utc0"], rounds=fin.get("rounds"), innerLog=fin.get("innerLog"),
                        h2FloorFlags=fin["tiers"]["h2"].get("floorFlags"))
        elif st == "invariant_fail":
            meta.update(token=fin.get("token"), invariantIssues=fin.get("invariantIssues"))
        else:
            meta.update(detail=fin.get("detail"), thetas=fin.get("thetas"), wOrig=fin.get("wOrig"))
        save(os.path.join(DDA, "meta", f"{n}.json"), meta)
        sel_levels.append(meta)
    save(os.path.join(DDA, "seedvar_rows.json"), {"_note": NOTE, "rows": seedvar_rows})
    save(os.path.join(DDA, "reference_baked", "easy_rows.json"), {"_note": "REFERENCE ONLY. " + NOTE, "rows": easy_rows})
    save(os.path.join(DDA, "reference_baked", "hard_rows.json"), {"_note": "REFERENCE ONLY. " + NOTE, "rows": hard_rows})

    cov = {"note": NOTE, "levelsFinished": len(finals), "status": dict(Counter(m["status"] for m in sel_levels)),
           "bySegment": {}, "reasons": dict(Counter((m.get("reason") or "").split(":")[0] for m in sel_levels
                                                    if m["status"] not in ("5tier", "3tier"))),
           "grade": dict(Counter(m.get("grade") for m in sel_levels if m.get("grade"))),
           "orderViolations": sum(1 for m in sel_levels if m.get("orderOk") is False),
           "invariantFail": sum(1 for m in sel_levels if m["status"] == "invariant_fail"),
           "wallSecTotal": round(sum((m.get("wallSec") or 0) for m in sel_levels), 1)}
    for lo, hi in SEGMENTS:
        seg = [m for m in sel_levels if lo <= m["level"] <= hi]
        tgt = [m for m in seg if m["status"] != "non_target"]
        cov["bySegment"][f"{lo}-{hi}"] = {"finished": len(seg), "target": len(tgt),
                                          "status": dict(Counter(m["status"] for m in seg)),
                                          "withVariant": sum(1 for m in seg if m["status"] in ("5tier", "3tier"))}
    unmet = defaultdict(int)
    for m in sel_levels:
        if m["status"] == "no_variant":
            unmet[m.get("reason", "")] += 1
    cov["noVariantReasons"] = dict(unmet)
    save(os.path.join(DDA, "coverage.json"), cov)

    sel = {"format": "pv_selection_dda/v1", "note": NOTE, "copyId": "pv_20261002_live3",
           "spec": "game IMPL_SPEC §V2-9-2 seedvar_N (original level_N untouched; token e2|e1|h1|h2 or e2|h2; "
                   "token 'seed' or 'seed@utc'); baseline = original map",
           "proposedThresholds": {"outerAbsDeltaMin": OUTER_MIN, "innerDeltaMin": INNER_MIN, "sameSideGapMin": GAP_MIN,
                                  "target": TARGET, "h2PredictedClearRelMin": H_PRED_REL, "h2HiSkillRateMin": H_HI_MIN,
                                  "h2FloorFlagsRecorded": "abs20/abs10/abs05/rel50/none (reselect without re-measure)",
                                  "status": "proposed values — user decision pending (spec has no magnitude rule)"},
           "measurement": {"scan": {"thetas": "0,0.15,0.29,0.55,0.65,0.75,0.85,1.0", "games": SCAN_GAMES, "seedBase": SEED_SCAN},
                           "stage1": {"gamesPerTheta": S1_GAMES, "seedBase": SEED_S1},
                           "stage2": {"gamesPerTheta": S2_GAMES, "seedBase": SEED_S2},
                           "robust": {"games": ROBUST_GAMES, "seedBase": SEED_ROBUST, "perPointOffset": 10_000,
                                      "points": "extra θ, profile:average, profile:expert, low θ (low θ = warning only)"},
                           "predictor": {"function": "mc_difficulty.sweep_level_task (editor RL sweep, 8 θ x 64, early stop)",
                                         "seed": SEED_PRED},
                           "solver": {"nodeBudget": SOLVER_NODES},
                           "pools": POOL_PLAN,
                           "verifierNote": "independent verification must use different bot seed bases, θ points and profiles"},
           "levels": sel_levels}
    save(os.path.join(DDA, "selection_dda.json"), sel)
    print(json.dumps({k: v for k, v in cov.items() if k != "note"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
