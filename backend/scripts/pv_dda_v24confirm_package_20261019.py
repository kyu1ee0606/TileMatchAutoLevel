"""Package v2.4-confirmed DDA pilot sets (isolated; NOT uploaded, NOT applied to game). 2026-10-19, doc 44.

Reads dda_v24confirm_20261019/work/*/result.json (+ PREREG, queue) and R2 seedvar_rows.json (read only).
Writes dda_v24confirm_20261019/package_<stamp>/:
  seedvar_rows_pass.json  rows for PASS sets only; randSeed reduced to passed tiers (e2|h2 or e2|e1|h1|h2)
  sets.csv                level, status, base(original level_N) map sha256, tokens, v2.4 Δ/CI (c1, c2), hashes
  all_results.csv         every queued level incl. HOLD / NOT_MEASURED with reason
  pilot21.csv             21-level live pilot (pilot_B_v3_1) — EXPERIMENT set, separate from application sets
  MANIFEST.json, SHA256SUMS
All values are bot-based (v2.4 rule-parity). Live user clear rate unverified.
Usage: venv/bin/python scripts/pv_dda_v24confirm_package_20261019.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda_v24confirm_20261019 as C  # noqa: E402

P = C.P

ORDER = ("e2", "e1", "h1", "h2")
PILOT = os.path.join(C.P.SB, "dda_sets_v2", "consensus", "pilot_B_v3_1.json")
ROWS = os.path.join(C.P.DDA, "seedvar_rows.json")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    stamp = time.strftime("%Y%m%d_%H%M")
    out = os.path.join(C.OUT, f"package_{stamp}")
    os.makedirs(out, exist_ok=False)
    q = C.load(os.path.join(C.OUT, "queue.json"))
    rows = C.load(ROWS)["rows"]
    res = {it["level"]: C.load(os.path.join(C.OUT, "work", f"{it['level']:04d}", "result.json")) for it in q}
    pass_rows, sets, allr = {}, [], []
    for it in q:
        n, r = it["level"], res[it["level"]]
        st = r["status"] if r else "NOT_MEASURED"
        allr.append({"level": n, "class": it["class"], "priority": it["priority"], "status": st,
                     "reason": (r or {}).get("reason", "") if r else "not measured before deadline/stop",
                     "pilotB_v3_1": it["pilotB_v3_1"], "afN100": it["afN100"]})
        if st not in ("PASS3", "PASS5"):
            continue
        use = [t for t in ORDER if t in r["tiers"] and (st == "PASS5" or t in ("e2", "h2"))]
        row = dict(rows[f"seedvar_{n}"])
        r2order = ("e2", "h2") if len(row["randSeed"].split("|")) == 2 else ORDER
        r2tok = dict(zip(r2order, row["randSeed"].split("|")))
        for t in use:
            if str(r2tok[t]) != str(r["tiers"][t]["token"]):
                raise SystemExit(f"token mismatch L{n} {t}: row {r2tok[t]} vs readiness {r['tiers'][t]['token']}")
        row["randSeed"] = "|".join(str(r2tok[t]) for t in use)
        pass_rows[f"seedvar_{n}"] = row
        tv = r["tiers"]
        sets.append({"level": n, "class": it["class"], "status": st, "tiersUsed": "|".join(use),
                     "baseMapSha256_livematch": it["canonicalMapSha256"].get("livematch_batch"),
                     "baseMapSha256_live3": it["canonicalMapSha256"].get("live3_source"),
                     "randSeed": row["randSeed"], "thetasV24": "/".join(f"{x:g}" for x in r["thetas"]),
                     "wOrig_c1": r["wOrig_c1"], "wOrig_c2": r["wOrig_c2"],
                     **{f"{t}_{k}": (tv[t][k] if t in tv else "") for t in ORDER
                        for k in ("c1Delta", "c1CiLo", "c2Delta", "c2CiLo")},
                     **{f"{t}_botMapHash16": r["mapHash16"].get(tv[t]["key"], "") if t in tv else "" for t in ORDER},
                     "origBotMapHash16": r["mapHash16"]["orig"], "pilotB_v3_1": it["pilotB_v3_1"],
                     "label": "bot-based v2.4; live unverified"})
    C.save(os.path.join(out, "seedvar_rows_pass.json"),
           {"_note": "PREPARATION ONLY — NOT APPROVED, NOT UPLOADED. v2.4 rule-parity confirmed subset of R2 seedvar rows. "
                     "Base = original level_N (untouched). Bot-based; live user clear rate unverified.", "rows": pass_rows})
    for name, data in (("sets.csv", sets), ("all_results.csv", allr)):
        with open(os.path.join(out, name), "w", newline="") as f:
            if data:
                w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
    pil = C.load(PILOT)
    plev = pil.get("levels") if isinstance(pil, dict) else pil
    prow = []
    for x in plev or []:
        n = x["level"] if isinstance(x, dict) else int(x)
        r = res.get(n)
        prow.append({"level": n, "role": "live pilot experiment (pilot_B_v3_1; intentional disagree levels included) — "
                                          "NOT the application set", "pick": x.get("pick") if isinstance(x, dict) else "", "expose": x.get("expose") if isinstance(x, dict) else "",
                     "exposeToken": x.get("exposeToken") if isinstance(x, dict) else "", "inQueue": n in res,
                     "v24Status": (r or {}).get("status", "NOT_MEASURED" if n in res else "not in queue (class C)")})
    with open(os.path.join(out, "pilot21.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "role", "pick", "expose", "exposeToken", "inQueue", "v24Status"])
        w.writeheader()
        w.writerows(prow)
    # per-set map files (isolated copies of the R2 seedvar rows, randSeed reduced to passed tiers)
    os.makedirs(os.path.join(out, "maps"), exist_ok=True)
    for k, row in pass_rows.items():
        C.save(os.path.join(out, "maps", f"{k}.json"), {"_note": "PREPARATION ONLY — NOT UPLOADED. Bot-based v2.4; live unverified.",
                                                       "id": k, **row})
    # full measurement detail (every queued level): wins / n / rate per point, scan, judgement
    det = {}
    for it in q:
        n = it["level"]
        d = os.path.join(C.OUT, "work", f"{n:04d}")
        det[str(n)] = {"queue": it, "scan": C.load(os.path.join(d, "scan.json")), "c1": C.load(os.path.join(d, "c1.json")),
                       "c2": C.load(os.path.join(d, "c2.json")), "result": res[n]}
    C.save(os.path.join(out, "results_detail.json"), det)
    # seed bands: selection/exploration (earlier stages, read from readiness protocol) vs this run
    C.save(os.path.join(out, "seed_bands.json"), {
        "earlierSelection_R2_v1": {"scan": P.SEED_SCAN, "s1": P.SEED_S1, "s2": P.SEED_S2, "robust": P.SEED_ROBUST},
        "earlierChecks": {"a_v1_fresh": 7_600_000, "b_v2": 7_800_000, "c_v2_scan": 5_200_000, "c_v2_s2": 7_200_000,
                          "c_v2_robust": 9_300_000, "v2_hi": 9_500_000},
        "thisRun_v24": {"scan_exploration": C.SEED["scan"], "c1_pair": C.SEED["pair"], "c1_robust": C.SEED["rob"],
                        "c2_independent_confirmation": C.SEED["ind"]},
        "seedFormula": "seed = band + pointIndex*10_000 + gameIndex (gameIndex < 950); same seeds across maps (CRN)"})
    # logs (copies)
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    for fn in ("PREREG.json", "queue.json", "progress.jsonl", "sup.log", "sup_events.log", "sup_state.json", "runner.log",
               "supervisor.out", "resume_free_mb"):
        src = os.path.join(C.OUT, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, "logs", fn))
    cnt = {}
    for a in allr:
        cnt[f"{a['class']}:{a['status']}"] = cnt.get(f"{a['class']}:{a['status']}", 0) + 1
    with open(os.path.join(out, "README.md"), "w") as f:
        f.write(f"""# DDA pilot set package — bot v2.4 confirmation ({stamp})

- Status: OFFLINE PREPARATION ONLY. Not applied to the game, not uploaded. All rates are BOT-based (v2.4 rule-parity);
  real user clear rates are UNVERIFIED (no live measurement, no game integration test).
- Counts: {json.dumps(cnt, ensure_ascii=False)} — bot-based PASS sets = {len(sets)}.
- Application candidate sets = `sets.csv` / `seedvar_rows_pass.json` / `maps/`. The 21-level live pilot
  (`pilot21.csv`, pilot_B_v3_1, intentional disagree levels) is a separate EXPERIMENT set.
- Files: sets.csv (base level_N <-> easy/hard tokens, hashes, Δ/CI c1+c2) · all_results.csv (155, PASS/HOLD reason) ·
  results_detail.json (wins/n/rate per θ point, scan, judgement) · seed_bands.json · maps/ · logs/ · MANIFEST.json · SHA256SUMS.
- Criteria: logs/PREREG.json (written before any result, 2026-10-19 19:25:52 KST). Not changed afterwards.
- Reproduce measurement (same seeds -> same results): `cd backend && venv/bin/python scripts/pv_dda_v24confirm_20261019.py run`
  (requires bot_simulator.py blob {C.BOT_BLOB}; finished stages are skipped — delete work/NNNN to re-measure a level).
- Re-package: `backend/venv/bin/python backend/scripts/pv_dda_v24confirm_package_20261019.py`
- Verify: `backend/venv/bin/python backend/scripts/pv_dda_v24confirm_verify_20261020.py <package dir>`
- Resume after interruption: stage checkpoints in work/NNNN/{{scan,c1,c2,result}}.json; supervisor
  `scripts/pv_dda_v24confirm_supervisor_20261019.py` (single instance lock, adopts running runner; deadline constants inside).
""")
    files = sorted(os.path.relpath(os.path.join(dp, f), out) for dp, _, fs in os.walk(out) for f in fs)
    man = {"created": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "counts": cnt, "passSets": len(sets),
           "command": "backend/venv/bin/python backend/scripts/pv_dda_v24confirm_package_20261019.py",
           "measureScript": {"path": "backend/scripts/pv_dda_v24confirm_20261019.py",
                             "sha256": sha(os.path.join(C.P.BACKEND, "scripts", "pv_dda_v24confirm_20261019.py"))},
           "prereg": {"path": "PREREG.json", "sha256": sha(os.path.join(C.OUT, "PREREG.json"))},
           "inputs": {"seedvar_rows": sha(ROWS), "readiness_levels": sha(C.READY), "pilot_B_v3_1": sha(PILOT)},
           "bot": {"version": C.BOT_VER, "blob": C.BOT_BLOB, "seeds": C.SEED},
           "files": {f: sha(os.path.join(out, f)) for f in files},
           "status": "offline preparation only — not applied, not uploaded, live user clear rate unverified"}
    C.save(os.path.join(out, "MANIFEST.json"), man)
    with open(os.path.join(out, "SHA256SUMS"), "w") as f:
        for fn in sorted(os.path.relpath(os.path.join(dp, x), out) for dp, _, fs in os.walk(out) for x in fs):
            if fn != "SHA256SUMS":
                f.write(f"{sha(os.path.join(out, fn))}  {fn}\n")
    print(out, json.dumps(cnt, ensure_ascii=False), "pass", len(sets))


if __name__ == "__main__":
    main()
