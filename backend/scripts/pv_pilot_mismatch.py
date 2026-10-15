"""Live-shard vs editor LIVE3 map mismatch check for the DDA rows and the live pilot (10 §9-10, doc 29 §2-1).

Doc 13 §6: 34 levels in L32~500 have a live build-shard map (what users played, AF p0) that differs from the editor
LIVE3 copy (source.json) that the DDA seedvar rows and bot Δ are based on. Stored values only, no measurement.

  report : per mismatch level — structure hash (positions/effects/containers), tile count, layers, tile kinds,
           shard row useTileCount vs seedvar useTileCount, in R2 / in pilot.
  plan   : pilot_B_v3_1.json = pilot_B_v3 with mismatch levels replaced by the same rule as §9-9-3
           (32~100 ceiling h2 kept-by-traffic -> next-traffic consensus h2 from B v2's dropped list;
            import (p0 0.35~0.85, v1 pass, e2) -> next import by the same greedy order), mismatch levels excluded.
Usage: .venv/bin/python scripts/pv_pilot_mismatch.py report|plan
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402
import pv_dda_pilot_v2 as V2P  # noqa: E402
import pv_dda_pilot_v3 as V3P  # noqa: E402
from app.core.pv.canonical import canonical_map, struct_hash  # noqa: E402

V2 = os.path.join(P.SB, "dda_sets_v2")
CONS = os.path.join(V2, "consensus")
OUT = os.path.join(V2, "pilot_export")
AF_PREP = os.path.join(V2P.AFD, "prep.json")


def kinds(m):
    c = Counter()
    for k, v in m.items():
        if k.startswith("layer_") and isinstance(v, dict):
            for t in (v.get("tiles") or {}).values():
                tid = str(t[0])
                if tid.startswith("t") and tid != "t0":
                    c[tid] += 1
    return c


def tiles(m):
    return sum(len((v or {}).get("tiles") or {}) for k, v in m.items() if k.startswith("layer_") and isinstance(v, dict))


def mismatch_levels():
    d = P.load(AF_PREP)
    return d, sorted(int(k) for k, v in d.items() if v["map_match_editor"] == "mismatch")


def report():
    d, mm = mismatch_levels()
    r2 = P.load(os.path.join(P.DDA, "seedvar_rows.json"))["rows"]
    pilot = {x["level"]: x for x in P.load(os.path.join(CONS, "pilot_B_v3.json"))["levels"]}
    rows = {}
    for n in mm:
        sh, l3 = canonical_map(d[str(n)]["map"]), canonical_map(P.source_level(n)["level_json"])
        ks, kl = kinds(sh), kinds(l3)
        row = r2.get(f"seedvar_{n}")
        rows[n] = {"structSame": struct_hash(sh) == struct_hash(l3), "tiles": [tiles(sh), tiles(l3)],
                   "layers": [sh.get("layer"), l3.get("layer")], "kinds": [len(ks), len(kl)], "typeCountsSame": ks == kl,
                   "shardUseTileCount": d[str(n)]["row"].get("useTileCount"),
                   "inR2": row is not None, "r2Status": P.W(n).get("final.json", {}).get("status") if row else None,
                   "seedvarUseTileCount": row.get("useTileCount") if row else None,
                   "seedvarTokens": row.get("randSeed") if row else None,
                   "inPilotB3": n in pilot,
                   "basis": {"seedvarMap": "LIVE3 (source.json) t0 copy", "botDelta": "vs LIVE3 original map",
                             "afP0": "live build shard map (1.1.0 = 1.0.162 shard, doc 15 §1)"}}
    summ = {"mismatch": len(mm), "levels": mm, "structSame": sum(v["structSame"] for v in rows.values()),
            "kindsDiffer": [n for n, v in rows.items() if v["kinds"][0] != v["kinds"][1]],
            "inR2": [n for n, v in rows.items() if v["inR2"]], "inPilotB3": [n for n, v in rows.items() if v["inPilotB3"]]}
    P.save(os.path.join(OUT, "mismatch_report.json"), {"summary": summ, "levels": {str(k): v for k, v in rows.items()}})
    print(json.dumps(summ))
    for n, v in rows.items():
        if v["inR2"]:
            print(n, v["r2Status"], "struct", v["structSame"], "kinds shard/live3", v["kinds"], "utc shard", v["shardUseTileCount"],
                  "seedvar", v["seedvarUseTileCount"], v["seedvarTokens"], "PILOT" if v["inPilotB3"] else "")


def plan():
    _, mm = mismatch_levels()
    mm = set(mm)
    b3 = P.load(os.path.join(CONS, "pilot_B_v3.json"))
    b2 = P.load(os.path.join(CONS, "pilot_B_v2.json"))["levels"]
    lv = {int(k): v for k, v in P.load(os.path.join(CONS, "levels.json")).items()}
    prep = P.load(AF_PREP)
    for r in lv.values():
        r["gimmicks"] = V2P.gimmicks(prep[str(r["level"])]["features"]) if str(r["level"]) in prep else ["?"]
        r["daily"] = round((r["afFtN"] or 0) / V2P.DAYS, 1)
        r["eligible"] = r["segment"] != "501-1000" and not r["exclude"] and (r["afFtN"] or 0) >= 100
    keep = [x for x in b3["levels"] if x["level"] not in mm]
    out = [x["level"] for x in b3["levels"] if x["level"] in mm]
    have = {x["level"] for x in keep}
    new, log = [], []
    for x in [z for z in b3["levels"] if z["level"] in mm]:
        if x["pick"] == "consensus" and x["segment"] == "32-100" and x["afFtRate"] >= 0.9:
            cand = sorted([z for z in b2 if z["segment"] == "32-100" and z["afFtRate"] >= 0.9 and z["level"] not in have
                           and z["level"] not in mm and z["level"] not in {y["level"] for y in new}], key=lambda z: -z["daily"])
            c = lv[cand[0]["level"]]
            t = "h2"
            pick = "consensus"
        else:
            pool = [r for r in lv.values() if r["eligible"] and r["v1Pass"] and 0.35 <= r["afFtRate"] <= 0.85
                    and r["level"] not in have and r["level"] not in mm and r["level"] not in {y["level"] for y in new}]
            covered = {g for z in keep + new for g in lv[z["level"]]["gimmicks"]}
            missing = [g for g in V2P.GIMMICKS if g not in covered]
            pool.sort(key=lambda r: (-len(set(r["gimmicks"]) & set(missing)), -r["daily"], r["level"]))
            c, t, pick = pool[0], "e2", "import"
        e = {**c, "pick": pick, "expose": t, "exposeToken": c["tokens"][t], "botDelta": c["outer"][t]}
        o = e["outer"][t]
        s = 1 if t == "e2" else -1
        rev = [st for st in ("b", "c") if s * o[st] < 0]
        collapse = max(abs(o["b"]), abs(o["c"])) < 0.5 * abs(o["a"])
        e["v2Tag"] = "consensus" if pick == "consensus" else "disagree:reversed" if rev else "disagree:collapsed" if collapse else "near-consensus"
        e["v2Reversed"] = rev
        k = P.W(e["level"]).get("final.json")["tiers"][t]["key"]
        risk = {}
        for src in ("v1", "v2"):
            wo, wv = V3P.bot_w(e["level"], "orig", src), V3P.bot_w(e["level"], k, src)
            bl = V3P.logit(wv) - V3P.logit(wo)
            risk[src] = {"botWOrig": round(wo, 4), "botWVar": round(wv, 4), "botLogitDelta": round(bl, 4),
                         "predUserDelta": round(V3P.expit(V3P.logit(e["afFtRate"]) + V3P.BETA * bl) - e["afFtRate"], 4)}
        e["risk"] = risk
        pu2 = risk["v2"]["predUserDelta"]
        e["riskFlag"] = "opposite" if s * pu2 < 0 else "none-effect" if abs(pu2) < 0.01 else "ok"
        new.append(e)
        log.append({"out": x["level"], "in": e["level"], "rule": "32-100 ceiling h2 by traffic" if pick == "consensus" else "import greedy (gimmick, traffic)"})
    keepk = ("level", "segment", "pick", "v2Tag", "v2Reversed", "disType", "consensusTag", "expose", "exposeToken", "botDelta",
             "afFtRate", "afFtN", "daily", "gimmicks", "risk", "riskFlag", "verifyPass", "verifyFail")
    levels = keep + [{k: e.get(k) for k in keepk} for e in new]
    cov = {"n": len(levels), "bySegment": dict(Counter(r["segment"] for r in levels)), "expose": dict(Counter(r["expose"] for r in levels)),
           "v2Tag": dict(Counter(r["v2Tag"] for r in levels)),
           "p0bands": dict(Counter(("0.35-0.85", "0.85-0.9", ">=0.9", "<0.35")[V2P.band(r["afFtRate"])] for r in levels)),
           "gimmicksZero": [g for g in V2P.GIMMICKS if not any(g in r["gimmicks"] for r in levels)]}
    P.save(os.path.join(CONS, "pilot_B_v3_1.json"),
           {"_note": "plan B v3.1 — B v3 with live-shard/LIVE3 map mismatch levels replaced (NOT APPROVED)",
            "basedOn": "pilot_B_v3.json", "replaced": log, "removedMismatch": out, "coverage": cov, "levels": levels})
    print(json.dumps({"replaced": log, "coverage": cov}, ensure_ascii=False))
    for e in new:
        print(e["level"], e["segment"], e["pick"], e["v2Tag"], e["expose"], e["exposeToken"], e["afFtRate"], e["daily"],
              {s: e["risk"][s]["predUserDelta"] for s in ("v1", "v2")}, e["gimmicks"])


if __name__ == "__main__":
    {"report": report, "plan": plan}[sys.argv[1]]()
