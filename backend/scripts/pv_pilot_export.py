"""Live pilot (plan B v3, 21 levels) — export, validation and pre-registration. PREPARATION ONLY, NOT UPLOADED.

  export   : dda_sets_v2/pilot_export/seedvar/seedvar_N.json + seedvar_rows.json + pilot_levels.json.
             Row = the R2 seedvar_N row (game IMPL_SPEC §V2-9-2 ②: t0 copy map + useTileCount + randSeed) with
             randSeed narrowed to the ONE exposed token (doc 24 §8-1: fixed token per level). R2 dda_sets/ is read only.
  validate : schema vs R2 row, token ∈ R2 token list, map = R2 prep t0 map, num == board tiles, num % 3 == 0,
             per-type counts % 3 == 0 after the python ShuffleEmptyTiles port, dotnet C# golden (tools/pv_golden),
             solver (same node budget as R2), original LIVE batch sha256, /api/pv-play (selection=dda) reachability.
  prereg   : preregistration.json — per-level original / variant expected user first-try clear rate and Δ under v1 and
             v2 (③) bot Δ with doc 25 logit slope 0.429 (CI 0.31~0.55), residual model (v2.3 E1) original prediction.
             Append-only "addenda" for later bot versions (v2.4).

Usage: .venv/bin/python scripts/pv_pilot_export.py export|validate|prereg
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402
from app.core.pv.cs_shuffle import CTile, resolve_map, shuffle_empty_tiles  # noqa: E402

V2 = os.path.join(P.SB, "dda_sets_v2")
OUT = os.path.join(V2, "pilot_export")
PLAN = os.path.join(V2, "consensus", "pilot_B_v3.json")
LIVE = os.path.join(P.BACKEND, "data", "production", "batch_1789636723287_uulknmtej.json")
LIVE_SHA_PREFIX = "1d4ba24ab6be6884"
RM_OOF = os.path.join(P.BACKEND, "data", "pv_sandbox", "af_calibration", "residual_retrain_v23", "v23", "interval_oof.csv")
AF = os.path.join(P.BACKEND, "data", "pv_sandbox", "af_calibration", "bot_compare_L32_500", "af.json")
API = os.environ.get("PV_API", "http://localhost:8000/api/pv-play")
BETA, BETA_LO, BETA_HI = 0.429, 0.31, 0.55   # doc 25 §2-1 logit slope (CI 0.308~0.550)
NOTE = "LIVE PILOT (plan B v3) — PREPARATION ONLY, NOT APPROVED, NOT UPLOADED. Game spec IMPL_SPEC §V2-9-2; doc 24/29."


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def head():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=P.REPO).stdout.strip()


def parse_token(tok, utc_row):
    s, _, u = str(tok).partition("@")
    return int(s), int(u) if u else int(utc_row)


def plan():
    return P.load(PLAN)["levels"]


def export():
    r2 = P.load(os.path.join(P.DDA, "seedvar_rows.json"))["rows"]
    rows, meta = {}, []
    for x in plan():
        n, tok = x["level"], x["exposeToken"]
        base = r2[f"seedvar_{n}"]
        assert tok in base["randSeed"].split("|"), (n, tok, base["randSeed"])
        row = copy.deepcopy(base)
        row["randSeed"] = tok
        rows[f"seedvar_{n}"] = row
        P.save(os.path.join(OUT, "seedvar", f"seedvar_{n}.json"), row)
        meta.append({"level": n, "rowId": f"seedvar_{n}", "expose": x["expose"], "token": tok, "segment": x["segment"],
                     "r2Token": base["randSeed"], "v2Tag": x["v2Tag"], "pick": x["pick"], "afFtRate": x["afFtRate"]})
    P.save(os.path.join(OUT, "seedvar_rows.json"), {"_note": NOTE, "rows": rows})
    P.save(os.path.join(OUT, "pilot_levels.json"), {"_note": NOTE, "planFile": os.path.relpath(PLAN, P.SB),
                                                   "planSha256": sha256(PLAN), "exportedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   "head": head(), "levels": meta})
    print(f"exported {len(rows)} rows")


def tile_total(m):
    """num semantics: board cells − containers + container contents (stack/craft count)."""
    n = 0
    for k, v in m.items():
        if k.startswith("layer_") and isinstance(v, dict):
            for t in (v.get("tiles") or {}).values():
                if str(t[0]).startswith(("stack", "craft")):
                    n += int(t[2][0]) if len(t) > 2 and t[2] else 0
                else:
                    n += 1
    return n


def bot_wins(n, key):
    """games won on the exposed variant in stored measurements (sep (a) v1 + ③ v2) — a win is a constructive proof."""
    w = 0
    s = os.path.join(V2, "sep", "work", f"{n:04d}.json")
    if os.path.exists(s):
        w += sum(round(x["rate"] * x["n"]) for x in P.load(s)["a_v1"].get(key, {}).values())
    m = os.path.join(V2, "work", f"{n:04d}", "m.json")
    if os.path.exists(m):
        w += sum(x.get("wins", round(x["rate"] * x["n"])) for x in P.load(m).get(key, {}).values())
    return w


def golden(n, row, s, u, res):
    gdir = os.path.join(OUT, "golden")
    inp = os.path.join(gdir, f"in_l{n:04d}.json")
    rr = copy.deepcopy(row)
    rr["useTileCount"], rr["randSeed"] = str(u), str(s)
    P.save(inp, {"caseId": f"pilot_l{n:04d}", "kind": "real", "levelId": f"level_{n}", "dumpRng": False,
                 "note": "live pilot exposed variant", "row": rr, "runs": [{"randSeed": str(s)}]})
    out = subprocess.run(["dotnet", "run", "--project", os.path.join(P.REPO, "tools", "pv_golden"), "--", "case", inp],
                         cwd=P.REPO, capture_output=True, text=True, timeout=230)
    if out.returncode != 0:
        return {"ok": False, "error": out.stderr[-300:]}
    exp = json.loads(out.stdout)["results"][0]
    pos = [[x.layer_name, x.pos, -1 if x.inner_index is None else x.inner_index] for x in res.slots]
    types = [CTile("", "", t, "").tile_id_num for t in res.assigned]
    return {"ok": pos == exp["positions"] and types == exp["types"], "slots": len(pos)}


def validate():
    rows = P.load(os.path.join(OUT, "seedvar_rows.json"))["rows"]
    r2 = P.load(os.path.join(P.DDA, "seedvar_rows.json"))["rows"]
    out, allok = {}, True
    for x in plan():
        n, t = x["level"], x["expose"]
        row, base = rows[f"seedvar_{n}"], r2[f"seedvar_{n}"]
        prep = P.W(n).get("prep.json")
        fin = P.W(n).get("final.json")
        s, u = parse_token(row["randSeed"], row["useTileCount"])
        key = fin["tiers"][t]["key"]
        chk = {"schemaSameAsR2": sorted(row) == sorted(base),
               "onlyRandSeedDiffers": all(row[k] == base[k] for k in row if k != "randSeed"),
               "tokenInR2": row["randSeed"] in base["randSeed"].split("|"),
               "keyMatchesFinal": key == f"{u}:{s}",
               "mapIsR2T0Copy": row["map"] == prep["t0row"]["map"]}
        m = row["map"]
        nt = tile_total(m)
        chk["numEqualsTiles"] = int(row["num"]) == nt
        chk["numMod3"] = int(row["num"]) % 3 == 0
        res = shuffle_empty_tiles(m, rand_seed=s, use_tile_count=u, strict=True)
        rm = resolve_map(m, res)
        cnt = Counter()
        for k, v in rm.items():
            if k.startswith("layer_") and isinstance(v, dict):
                for tl in (v.get("tiles") or {}).values():
                    tid = str(tl[0])
                    if tid.startswith(("stack", "craft")) and len(tl) > 2 and tl[2]:
                        for z in str(tl[2][1]).split("_"):
                            cnt[z] += 1
                    elif tid != "t0":
                        cnt[tid] += 1
        chk["noT0Left"] = "t0" not in cnt
        bad = {k: v for k, v in cnt.items() if v % 3 and k.startswith("t")}
        chk["typeCountsMod3"] = not bad
        g = golden(n, row, s, u, res)
        chk["csGolden"] = g["ok"]
        sv = P.solve_check(P.lj_seed(prep, key), P.SOLVER_NODES)
        chk["solver"] = sv["verdict"]
        chk["botWins"] = bot_wins(n, key)
        chk["solverOk"] = sv["verdict"] == "PROVEN_SOLVABLE" or chk["botWins"] > 0
        chk["solvabilityEvidence"] = "solver" if sv["verdict"] == "PROVEN_SOLVABLE" else ("bot win" if chk["botWins"] else "none")
        chk["solverR2"] = fin["tiers"][t].get("solver") if "solver" in fin["tiers"][t] else P.load(
            os.path.join(P.DDA, "meta", f"{n}.json"))["tiers"][t].get("solver")
        try:
            with urllib.request.urlopen(f"{API}/levels/{n}/{t}?selection=dda", timeout=20) as r:
                body = json.loads(r.read())
            chk["apiStatus"] = 200
            chk["apiTokenMatch"] = str(s) in json.dumps(body)
        except Exception as e:  # noqa: BLE001
            chk["apiStatus"] = getattr(e, "code", str(e)[:80])
            chk["apiTokenMatch"] = False
        if bad:
            chk["badCounts"] = bad
        ok = all(chk[k] for k in ("schemaSameAsR2", "onlyRandSeedDiffers", "tokenInR2", "keyMatchesFinal", "mapIsR2T0Copy",
                                  "numEqualsTiles", "numMod3", "noT0Left", "typeCountsMod3", "csGolden", "solverOk"))
        chk["ok"] = ok
        allok &= ok
        out[str(n)] = chk
        print(n, t, "OK" if ok else "FAIL", chk["solver"], "api", chk["apiStatus"], chk["apiTokenMatch"], flush=True)
    live = sha256(LIVE)
    rep = {"checkedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head(), "allOk": allok, "liveSha256": live,
           "liveUnchanged": live.startswith(LIVE_SHA_PREFIX), "solverNodes": P.SOLVER_NODES, "levels": out}
    P.save(os.path.join(OUT, "validation.json"), rep)
    print("allOk", allok, "live", live[:16])


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def expit(x):
    return 1 / (1 + math.exp(-x))


def prereg():
    import csv
    af = P.load(AF)
    rm = {int(r["L"]): r for r in csv.DictReader(open(RM_OOF))}
    v3 = {x["level"]: x for x in P.load(PLAN)["levels"]}
    levels = []
    for x in plan():
        n = x["level"]
        a = af[str(n)]
        p0 = a["clean_ft_rate"]
        sign = 1 if x["expose"] == "e2" else -1
        pred = {}
        for lab in ("v1", "v2"):
            rk = v3[n]["risk"][lab]
            bl = rk["botLogitDelta"]
            pv = {b: expit(logit(p0) + b * bl) for b in (BETA_LO, BETA, BETA_HI)}
            dv = sorted(pv[b] - p0 for b in pv)
            pred[lab] = {"botSource": "v1 fresh seeds, R2 θ pair (§9-8 a)" if lab == "v1" else "v2 ③ own θ pair (§9-7)",
                         "botWOrig": rk["botWOrig"], "botWVariant": rk["botWVar"], "botLogitDelta": bl,
                         "variantClear": round(pv[BETA], 4), "variantClearRange": [round(min(pv.values()), 4), round(max(pv.values()), 4)],
                         "userDelta": round(pv[BETA] - p0, 4), "userDeltaRange": [round(dv[0], 4), round(dv[-1], 4)],
                         "intendedSign": sign, "directionOk": sign * (pv[BETA] - p0) > 0}
        r = rm.get(n, {})
        levels.append({"level": n, "segment": x["segment"], "expose": x["expose"], "token": x["exposeToken"], "pick": x["pick"],
                       "v2Tag": x["v2Tag"],
                       "original": {"afCleanFtRate": p0, "afCleanFtN": a["clean_ft_n"], "afCleanFtCi95": a["clean_ft_ci95"],
                                    "afWindow": "2026-09-08~10-14 (35.7d), first try, unaided (doc 24 §1)",
                                    "residualModelV23E1": float(r["pred_E1"]) if r else None,
                                    "residualModelCqr80": [float(r["cqr_lo"]), float(r["cqr_hi"])] if r else None,
                                    "residualModelTarget": "midpoint of unaided clear lower/upper bound (doc 20/23) — not clean_ft",
                                    "afUnaidedMid": float(r["mid"]) if r else None},
                       "predictions": pred})

    def pooled(group, lab):
        d = [z["predictions"][lab]["userDelta"] * z["predictions"][lab]["intendedSign"] for z in group]
        return {"n": len(d), "meanIntendedDirectionDelta": round(sum(d) / len(d), 4),
                "directionOkShare": round(sum(1 for z in group if z["predictions"][lab]["directionOk"]) / len(group), 3)}
    groups = {"all": levels, "e2": [z for z in levels if z["expose"] == "e2"], "h2": [z for z in levels if z["expose"] == "h2"],
              "disagree6": [z for z in levels if z["v2Tag"].startswith("disagree")],
              "consensus12": [z for z in levels if z["v2Tag"] == "consensus"],
              "nearConsensus3": [z for z in levels if z["v2Tag"] == "near-consensus"]}
    summary = {g: {lab: pooled(v, lab) for lab in ("v1", "v2")} for g, v in groups.items()}
    reg = {"_note": "PRE-REGISTRATION — predictions fixed BEFORE any pilot result is seen. Do not edit; add addenda only.",
           "registeredAt": time.strftime("%Y-%m-%d %H:%M:%S %z"), "headAtRegistration": head(),
           "inputs": {"plan": {"path": os.path.relpath(PLAN, P.SB), "sha256": sha256(PLAN)},
                      "af": {"path": os.path.relpath(AF, P.BACKEND), "sha256": sha256(AF)},
                      "residualModel": {"path": os.path.relpath(RM_OOF, P.BACKEND), "sha256": sha256(RM_OOF)},
                      "rows": {"path": "dda_sets_v2/pilot_export/seedvar_rows.json",
                               "sha256": sha256(os.path.join(OUT, "seedvar_rows.json"))}},
           "model": {"formula": "variantClear = expit(logit(p0) + beta * (logit(botWVariant) - logit(botWOrig)))",
                     "beta": BETA, "betaCi": [BETA_LO, BETA_HI], "betaSource": "doc 25 §2-1 natural experiment, logit scale",
                     "p0": "AF clean first-try clear rate of the original map",
                     "outcome": "variant arm clean first-try clear rate − control arm (doc 29 §4, pilot_eval.py)"},
           "levels": levels, "pooledSummary": summary,
           "addenda": [], "addendaSchema": {"botVersion": "e.g. v2.4", "registeredAt": "...", "head": "...",
                                            "levels": "{level: {botWOrig, botWVariant, botLogitDelta, variantClear, userDelta, userDeltaRange}}",
                                            "rule": "append before pilot results are opened; never edit earlier entries"}}
    p = os.path.join(OUT, "preregistration.json")
    P.save(p, reg)
    digest = sha256(p)
    with open(p + ".sha256", "w") as f:
        f.write(f"{digest}  preregistration.json\n")
    print(json.dumps(summary, ensure_ascii=False))
    print("sha256", digest)


if __name__ == "__main__":
    {"export": export, "validate": validate, "prereg": prereg}[sys.argv[1]]()
