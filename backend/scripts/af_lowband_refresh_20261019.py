"""Read-only AF refresh; no bot/model API. Bounded-memory, separate outputs.

Uses existing reconstruction rules, one device at a time. Temporary SQLite
contains only ephemeral salted identifiers and filtered event payloads; removed
on exit. Final outputs contain aggregates only. Existing calibration untouched.
"""
import csv
import gzip
import hashlib
import itertools
import json
import os
import resource
import sqlite3
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import af_level_metrics as af

OUT = af.OUT_DIR / "refresh_20261019"
CUT = "2026-10-14 10:29:41"
BANDS = [(0, .5, "under50"), (.5, .7, "50to70"), (.7, .85, "70to85")]


def band(p):
    return next((s for lo, hi, s in BANDS if p is not None and lo <= p < hi), None)


def main():
    OUT.mkdir(exist_ok=False)
    baseline = json.loads((af.OUT_DIR / "level_metrics.json").read_text())
    old = {x["level"]: x for x in baseline["levels"]}
    index = json.loads((af.AF_DATA / "index.json").read_text())
    meta = {"generated_at": datetime.now().isoformat(), "cutoff": CUT,
            "index_updated": index.get("updated"), "files": [], "versions": Counter(),
            "rows": 0, "kept": 0, "duplicates": 0, "invalid_payload": 0,
            "missing_id": 0, "excluded_versions": Counter(), "day_events": Counter()}
    del index
    salt = os.urandom(32)
    # key -> n, clear, helped, no_end, censored; key includes period/version.
    agg = defaultdict(Counter)
    users = defaultdict(set)
    run_totals = Counter()
    with tempfile.TemporaryDirectory(prefix="af-lowband-20261019-") as temp:
        db = sqlite3.connect(str(Path(temp) / "events.sqlite"))
        db.execute("PRAGMA cache_size=-8192")
        db.execute("PRAGMA temp_store=FILE")
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("CREATE TABLE ev(k BLOB PRIMARY KEY,dev BLOB,t TEXT,o INT,n TEXT,v TEXT,p TEXT,a TEXT)")
        for plat in ("android", "ios"):
            for name in (f"{plat}_in_app_events.csv.gz", f"{plat}_organic_in_app_events.csv.gz"):
                path = af.AF_DATA / name
                before = path.stat()
                info = {"name": name, "size": before.st_size, "mtime_ns": before.st_mtime_ns,
                        "min": None, "max": None, "retained": 0}
                batch = []
                with gzip.open(path, "rt", encoding="utf-8-sig", newline="", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        meta["rows"] += 1
                        n = row["Event Name"]
                        booster = n.startswith("booster_use_")
                        if n not in af.LEVEL_EVENTS and not booster:
                            continue
                        ver, t = row["App Version"], row["Event Time"]
                        meta["versions"][f"{plat}|{ver}"] += 1
                        if (plat, ver) not in af.RUN_VERSIONS:
                            meta["excluded_versions"][f"{plat}|{ver}"] += 1
                            continue
                        if not row["AppsFlyer ID"]:
                            meta["missing_id"] += 1
                            continue
                        try:
                            val = json.loads(row["Event Value"] or "{}")
                            if not isinstance(val, dict):
                                raise ValueError()
                        except ValueError:
                            meta["invalid_payload"] += 1
                            val = {}
                        payload = json.dumps(val, sort_keys=True, ensure_ascii=False)
                        key = hashlib.sha256(salt + "\x1f".join((row["AppsFlyer ID"], t, n, payload, ver)).encode()).digest()
                        dev = hashlib.sha256(salt + (plat + row["AppsFlyer ID"]).encode()).digest()
                        nn = "booster" if booster else n
                        filtered = json.dumps({k: val[k] for k in af.KEEP_KEYS if k in val})
                        batch.append((key, dev, t, af.TIE_ORDER[nn], nn, filtered, plat, ver))
                        info["min"] = min(info["min"] or t, t)
                        info["max"] = max(info["max"] or t, t)
                        info["retained"] += 1
                        if len(batch) == 5000:
                            db.executemany("INSERT OR IGNORE INTO ev VALUES(?,?,?,?,?,?,?,?)", batch)
                            db.commit()
                            batch.clear()
                db.executemany("INSERT OR IGNORE INTO ev VALUES(?,?,?,?,?,?,?,?)", batch)
                db.commit()
                assert path.stat().st_mtime_ns == before.st_mtime_ns, "Source changed during read"
                meta["files"].append(info)
                print("read", name, info, flush=True)
        meta["kept"] = db.execute("SELECT COUNT(*) FROM ev").fetchone()[0]
        meta["duplicates"] = sum(x["retained"] for x in meta["files"]) - meta["kept"]
        meta["day_events"] = dict(db.execute("SELECT substr(t,1,10),COUNT(*) FROM ev GROUP BY substr(t,1,10)"))
        db.execute("CREATE INDEX dev_time ON ev(dev,t,o)")
        db.commit()
        cur = db.execute("SELECT dev,t,o,n,v,p,a FROM ev ORDER BY dev,t,o,rowid")
        for i, (dev, group) in enumerate(itertools.groupby(cur, lambda x: x[0])):
            ev = [(t,o,n,json.loads(v),p,a) for _,t,o,n,v,p,a in group]
            runs, _, _, _ = af.build_runs({dev: ev})
            af.mark_first_try(runs)
            for r in runs:
                if r["infinite"] or not 1 <= r["L"] <= af.MAX_LEVEL:
                    continue
                run_totals[r["oc"]] += 1
                if not r["first_try"]:
                    continue
                per = "new" if r["t0"] > CUT else "old_window"
                key = (r["L"], f"{r['plat']}|{r['ver']}", per)
                if r["oc"] in ("clear", "final_fail"):
                    agg[key]["n"] += 1
                    agg[key]["clear"] += int(r["oc"] == "clear")
                    agg[key]["helped"] += int(r["helped"])
                    users[key].add(dev)
                else:
                    agg[key][r["oc"]] += 1
            if i % 5000 == 0:
                print("devices", i, flush=True)
        meta["devices"] = i + 1
        db.close()
    # Map comparison uses existing audited canonical/shard code, no simulations.
    cmd = [str(af.BACKEND / ".venv/bin/python"), "-c",
           "import sys,json;sys.path.insert(0,'scripts');import af_level_metrics as a;s,m=a.load_map_match();print(json.dumps({'snaps':s,'meta':m}))"]
    maps = json.loads(subprocess.check_output(cmd, cwd=af.BACKEND, text=True))
    rows = []
    row_users = {}
    for L in range(1, af.MAX_LEVEL+1):
        row = {"level": L, "baseline_n": old[L]["first_try_ended"],
               "baseline_rate": old[L]["ft_clear_rate_any_help"], "baseline_map_match": old[L].get("map_match"),
               "versions": {}, "same": {}, "all_known": {}}
        for label, same_only in (("same", True), ("all_known", False)):
            for period in ("new", "old_window", "combined"):
                counts, us = Counter(), set()
                for (lv, version, per), values in agg.items():
                    if lv != L or (period != "combined" and period != per):
                        continue
                    commit = maps["meta"]["version_shard_commit"][version]
                    match = maps["snaps"][commit][str(L)]
                    if same_only and match != "same":
                        continue
                    counts.update(values)
                    us.update(users[(lv,version,per)])
                n, k = counts["n"], counts["clear"]
                row[label][period] = {**dict(counts), "n":n,"clear":k,"users":len(us),
                                       "rate":k/n if n else None,"ci95":af.wilson(k,n)}
                row_users[(L,label,period)] = us
        for version, commit in maps["meta"]["version_shard_commit"].items():
            row["versions"][version] = {"commit":commit,"match":maps["snaps"][commit][str(L)],
                                      "new_n":agg[(L,version,"new")]["n"],
                                      "old_n":agg[(L,version,"old_window")]["n"]}
        rows.append(row)
    summaries = {}
    for basis in ("baseline_fixed", "refreshed"):
        sums = {}
        for _,_,b in BANDS:
            selected = [r for r in rows if band(r["baseline_rate"] if basis == "baseline_fixed" else r["same"]["combined"]["rate"]) == b]
            ss = {"maps":len(selected), "baseline_n":sum(r["baseline_n"] for r in selected),
                  "baseline_usable_maps":sum(r["baseline_n"]>=100 and r["baseline_map_match"]=="same" for r in selected),
                  "usable_maps":sum(r["same"]["combined"]["n"]>=100 for r in selected)}
            for per in ("new","old_window","combined"):
                ss[per] = {"n":sum(r["same"][per]["n"] for r in selected),
                           "users":len(set().union(*(row_users[(r['level'],'same',per)] for r in selected))),
                           "maps_with_n":sum(r["same"][per]["n"]>0 for r in selected)}
            sums[b] = ss
        summaries[basis] = sums
    meta["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {"meta":meta,"run_outcomes":run_totals,"map_meta":maps["meta"],"summaries":summaries,
              "definition":"First observed device-level run, attempt=1, ended only, help included. New period by start time after cutoff. Same-map subset excludes mismatched builds. n>=100 is sample screen, not prediction approval.",
              "limitations":["Build-to-version mapping inherited from git evidence, not device map_hash telemetry.",
                              "Old-window may include late arrivals and newly resolved outcomes; not a frozen baseline reproduction.",
                              "Unique users are AppsFlyer device IDs, not deduplicated cross-device accounts."],"levels":rows}
    (OUT / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    with (OUT / "levels.csv").open("w",newline="") as f:
        w=csv.writer(f);w.writerow(["level","baseline_n","baseline_rate","new_same_n","combined_same_n","combined_same_rate","ci95_low","ci95_high","new_mismatch_n"])
        for r in rows:
            c=r["same"]["combined"]
            w.writerow([r["level"],r["baseline_n"],r["baseline_rate"],r["same"]["new"]["n"],c["n"],c["rate"],*c["ci95"],r["all_known"]["new"]["n"]-r["same"]["new"]["n"]])
    print(json.dumps({"meta":meta,"summaries":summaries},ensure_ascii=False,indent=2),flush=True)


if __name__ == "__main__":
    main()
