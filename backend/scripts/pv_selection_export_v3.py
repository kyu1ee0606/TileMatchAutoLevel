"""Export v3 (utc ±1 flex) selections -> <sandbox>/selection_v3.json.

Deployment string (proposal, 04 §A6-0 v3): randSeed = "tok|tok|tok|tok|tok" in order b|e2|e1|h1|h2,
token = "seed" (uses the level's useTileCount = utc0) or "seed@utc" (overrides useTileCount for that tier).
Both "strict" (base utc0) and "relaxed" (base may be utc0±1 for extreme-original levels) are exported.

Usage: python scripts/pv_selection_export_v3.py
"""
from __future__ import annotations

import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from app.core.pv.select import Z_V2, indep_diff  # noqa: E402

SB = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3")
A_ORDER = ("b", "e2", "e1", "h1", "h2")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def token(k: str, utc0: int) -> str:
    u, s = k.split(":")
    return s if int(u) == utc0 else f"{s}@{u}"


def parse_token(tok: str):
    """Client-side rule mirror: 'seed' or 'seed@utc'; seed 1..2^31-1, utc 1..15."""
    if "@" in tok:
        s, u = tok.split("@", 1)
        u = int(u)
        if not 1 <= u <= 15:
            raise ValueError(f"utc out of range in {tok!r}")
    else:
        s, u = tok, None
    if not s.isdigit():
        raise ValueError(f"bad seed token {tok!r}")
    s = int(s)
    if not 1 <= s <= 2**31 - 1:
        raise ValueError(f"seed out of range in {tok!r}")
    return s, u


def validate_a_v3(text: str, utc0: int, base_key: str) -> None:
    """Editor export check (v3): 5 tokens, valid seeds/utc, (seed, utc) pairs distinct, first = base,
    utc within utc0±1, '@' only when utc differs from utc0."""
    toks = text.split("|")
    if len(toks) != 5:
        raise ValueError("need exactly 5 tokens")
    pairs = []
    for t in toks:
        s, u = parse_token(t)
        if u is not None and u == utc0:
            raise ValueError(f"redundant @utc0 in {t!r}")
        u = utc0 if u is None else u
        if abs(u - utc0) > 1:
            raise ValueError(f"utc {u} outside utc0±1 ({utc0})")
        pairs.append((s, u))
    if len(set(pairs)) != 5:
        raise ValueError("duplicate (seed, utc) tokens")
    bu, bs = base_key.split(":")
    if pairs[0] != (int(bs), int(bu)):
        raise ValueError("first token must be base")


def merged_ev(n):
    d2 = os.path.join(SB, "eval2", f"{n:04d}")
    d3 = os.path.join(SB, "eval3", f"{n:04d}")
    prep = load(os.path.join(d2, "prep.json"))
    u0 = prep["meta"]["utc0"]
    ev = {}
    for p in (32, 64, 128):
        f = os.path.join(d2, f"s2_p{p}.json")
        if os.path.exists(f):
            ev.update({f"{u0}:{s}": e for s, e in load(f)["results"].items()})
    f = os.path.join(d3, "s2_flex.json")
    if os.path.exists(f):
        ev.update(load(f)["results"])
    return prep, u0, ev


def scenario_out(sc, n, prep, u0, ev, orig):
    out = {"ok": sc["ok"], "flexUsed": sc.get("flexUsed", [])}
    if not sc.get("ok"):
        out["unmet"] = {side: {"reason": v["reason"], "nValid": v["nValid"]}
                        for side, v in sc.get("sides", {}).items() if v["pick"] is None}
        if "reason" in sc:
            out["unmet"] = sc["reason"]
        return out
    seeds = dict(sc["seeds"])
    base = seeds["b"]
    bo = indep_diff(ev[base], orig)
    tiers = {}
    for t in ("b", "e2", "e1", "h1", "h2"):
        k = seeds[t]
        u, s = k.split(":")
        rec = {"seed": int(s), "utc": int(u), "W": ev[k]["W"],
               "perTheta": {th: v["rate"] for th, v in ev[k]["theta"].items()}}
        if t != "b":
            dd = indep_diff(ev[k], ev[base])
            rec.update(deltaVsBase=dd["diff"], ci=[dd["lo"], dd["hi"]])
        else:
            rec.update(deltaVsOrig=bo["diff"], ci=[bo["lo"], bo["hi"]])
        tiers[t] = rec
    text = "|".join(token(seeds[t], u0) for t in A_ORDER)
    validate_a_v3(text, u0, base)
    tc = prep["meta"]["tileCount"]
    notice = {t: {"kinds": v["utc"], "kindsDelta": v["utc"] - u0,
                  "tilesPerKind": round(tc / v["utc"], 2), "tilesPerKind_utc0": round(tc / u0, 2)}
              for t, v in tiers.items() if v["utc"] != u0}
    out.update(tiers=tiers, randSeedA=text, notice=notice)
    return out


def main() -> int:
    levels = load(os.path.join(SB, "sample2.json"))["levels"]
    rows = []
    for n in levels:
        d2 = os.path.join(SB, "eval2", f"{n:04d}")
        d3 = os.path.join(SB, "eval3", f"{n:04d}")
        fin2 = load(os.path.join(d2, "final.json"))
        prep = load(os.path.join(d2, "prep.json"))
        row = {"level": n, "structHash": prep["meta"]["structHash"], "utc0": prep["meta"]["utc0"],
               "tileCount": prep["meta"]["tileCount"], "v2Status": fin2["status"]}
        if fin2["status"] == "unevaluable":
            f = os.path.join(d3, "unevaluable_check.json")
            row.update(status="unevaluable", check=load(f) if os.path.exists(f) else None, deploy="keep_explicit_map")
            rows.append(row)
            continue
        if not os.path.exists(os.path.join(d3, "strict.json")):
            row["status"] = "not_finished"
            rows.append(row)
            continue
        prep, u0, ev = merged_ev(n)
        orig = load(os.path.join(d2, "orig2.json"))["results"]["orig"]
        row.update(thetas=fin2["thetas"], wOrig=orig["W"], origPercentile=fin2["basePick"]["origPercentile"],
                   seedBases={"stage1": 6_000_000, "stage2": 7_000_000})
        row["strict"] = scenario_out(load(os.path.join(d3, "strict.json")), n, prep, u0, ev, orig)
        rf = os.path.join(d3, "relaxed.json")
        if os.path.exists(rf):
            row["relaxed"] = scenario_out(load(rf), n, prep, u0, ev, orig)
        row["status"] = "ok" if row["strict"]["ok"] else "bidirectional_unmet"
        rows.append(row)
    out = {"format": "pv_selection_v3", "copyId": "pv_20261002_live3",
           "tokenFormat": "randSeed = 'b|e2|e1|h1|h2'; token = 'seed' (utc0) or 'seed@utc' (utc0±1)",
           "rule": "v2 rule + utc flex: utc0 first; easy side may use utc0-1, hard side utc0+1; flex pools ≤64; "
                   "relaxed base utc0∓1 only for extreme-original levels (pct>0.90 / <0.10)",
           "ciZ": Z_V2, "levels": rows}
    with open(os.path.join(SB, "selection_v3.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    from collections import Counter
    print("strict", Counter(r["status"] for r in rows),
          "relaxed ok", sum(1 for r in rows if r.get("relaxed", {}).get("ok")),
          "relaxed tried", sum(1 for r in rows if "relaxed" in r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
