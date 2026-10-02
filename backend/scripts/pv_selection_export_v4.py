"""Export v4 selections -> <sandbox>/selection_v4.json (atomic write).

randSeed string (A-plan, 04 §A6-0c): 1, 3 or 5 tokens; first token = base.
  5 tiers: "b|e2|e1|h1|h2"     3 tiers: "b|e2|h2"     fixed map: no string (original explicit map kept)
  token = "seed" (level useTileCount = utc0) or "seed@utc" (utc0±1).
All measurement conditions used for selection are recorded so an independent verifier can avoid them.

Usage: python scripts/pv_selection_export_v4.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from app.core.pv.select import Z_V2, indep_diff  # noqa: E402
from pv_v4 import ROBUST_GAMES, SEED_ROBUST, Lv, hi_rate, lo_rate, point_rates  # noqa: E402

SB = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3")
ORDER = {5: ("b", "e2", "e1", "h1", "h2"), 3: ("b", "e2", "h2")}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def token(k, u0):
    u, s = k.split(":")
    return s if int(u) == u0 else f"{s}@{u}"


def validate_a_v4(text: str, utc0: int, base_key: str, tiers: int) -> None:
    """Editor export check (v4): 3 or 5 tokens, 'seed' or 'seed@utc', seed 1..2^31-1, utc 1..15 and
    within utc0±1, no redundant '@utc0', distinct (seed, utc) pairs, first token = base.
    Side policy: easy tokens utc ∈ {utc0-1, utc0}, hard tokens utc ∈ {utc0, utc0+1}."""
    toks = text.split("|")
    if len(toks) not in (3, 5) or len(toks) != tiers:
        raise ValueError(f"need {tiers} tokens (3 or 5), got {len(toks)}")
    names = ORDER[tiers]
    pairs = []
    for name, t in zip(names, toks):
        s, _, u = t.partition("@")
        if not s.isdigit() or not 1 <= int(s) <= 2**31 - 1:
            raise ValueError(f"bad seed in {t!r}")
        if u:
            if not u.isdigit() or not 1 <= int(u) <= 15 or int(u) == utc0:
                raise ValueError(f"bad/redundant utc in {t!r}")
            u = int(u)
        else:
            u = utc0
        if abs(u - utc0) > 1:
            raise ValueError(f"utc {u} outside utc0±1")
        if name.startswith("e") and u == utc0 + 1 or name.startswith("h") and u == utc0 - 1:
            raise ValueError(f"{name} token {t!r} uses a utc not allowed on its side")
        pairs.append((int(s), u))
    if len(set(pairs)) != len(pairs):
        raise ValueError("duplicate (seed, utc) tokens")
    bu, bs = base_key.split(":")
    if pairs[0] != (int(bs), int(bu)):
        raise ValueError("first token must be base")


def main() -> int:
    levels = load(os.path.join(SB, "sample2.json"))["levels"]
    rows = []
    for n in levels:
        lv = Lv(n)
        fp = lv.f("final.json")
        row = {"level": n, "structHash": lv.prep0["meta"]["structHash"], "utc0": lv.u0,
               "tileCount": lv.prep0["meta"]["tileCount"]}
        if not os.path.exists(fp):
            row["status"] = "not_finished"
            rows.append(row)
            continue
        fin = load(fp)
        row.update(status=fin["status"], reason=fin.get("reason"))
        if fin["status"] == "fixed_map" and "base" not in fin:
            row["deploy"] = "keep_explicit_map"
            rows.append(row)
            continue
        ev, _ = lv.s2()
        rob = lv.robust()
        orig = load(os.path.join(lv.d2, "orig2.json"))["results"]["orig"]
        base = fin["base"]
        bo = indep_diff(ev[base], orig)
        row.update(baseMode=fin["baseMode"], origPercentile=fin["origPct"], wOrig=orig["W"],
                   measurement={"selectionThetas": fin["thetas"], "stage2GamesPerTheta": 950,
                                "stage1GamesPerTheta": 64, "robustPoints": fin["robustPoints"],
                                "robustGames": ROBUST_GAMES,
                                "botSeedBases": {"stage1": 6_000_000, "stage2": 7_000_000,
                                                 "robust": SEED_ROBUST, "robustPerPointOffset": 10_000}},
                   base={"seed": int(base.split(":")[1]), "utc": int(base.split(":")[0]), "W": ev[base]["W"],
                         "deltaVsOrig": bo["diff"], "ci": [bo["lo"], bo["hi"]]},
                   expansionRounds=fin.get("rounds", []))
        if fin["tiers"] in (3, 5):
            seeds = dict(fin["seeds"])
            tiers = {}
            for t in ORDER[fin["tiers"]][1:]:
                k = seeds[t]
                d = indep_diff(ev[k], ev[base])
                side = "easy" if t.startswith("e") else "hard"
                j = fin["sides"][side]["judged"][k]
                tiers[t] = {"seed": int(k.split(":")[1]), "utc": int(k.split(":")[0]), "W": ev[k]["W"],
                            "deltaVsBase": d["diff"], "ci": [d["lo"], d["hi"]],
                            "robust": {"informative": j["informative"], "dirOk": j["dirOk"], "need": j["need"],
                                       "sensitive": j["sensitive"], "spread": j["spread"]},
                            "pointRates": point_rates(k, ev, rob),
                            "hiSkillRate": hi_rate(k, ev, rob), "loSkillRate": lo_rate(k, ev, rob)}
            text = "|".join(token(seeds[t], lv.u0) for t in ORDER[fin["tiers"]])
            validate_a_v4(text, lv.u0, base, fin["tiers"])
            row.update(tiers=tiers, tierCount=fin["tiers"], randSeedA=text, deploy="randSeed_A_string")
        else:
            row["deploy"] = "keep_explicit_map"
        rows.append(row)
    out = {"format": "pv_selection_v4", "copyId": "pv_20261002_live3",
           "tokenFormat": "1/3/5 tokens; 5='b|e2|e1|h1|h2', 3='b|e2|h2'; token='seed' or 'seed@utc'",
           "rule": "09 report: v3 base policy (extreme->relaxed), outer target Δ easy +0.20 / hard -0.25 with "
                   "robust test (extra θ + AVERAGE + EXPERT, 600 games; ≥2/3 informative points same direction; "
                   "skill-sensitive excluded), h2 floor max(θ_hi, EXPERT) ≥0.10, inner robust -> 5 tiers else 3",
           "ciZ": Z_V2, "levels": rows}
    dst = os.path.join(SB, "selection_v4.json")
    with open(dst + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(dst + ".tmp", dst)
    print(Counter(r["status"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
