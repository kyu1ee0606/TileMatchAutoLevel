"""Low clear-rate band (≈27–85 % ft_any) — data support + candidate models (doc 36). Offline only.

The active model (cr-ftany-v24r-20261016), active.json and every saved model directory are never written.
No bot measurement: stored AF aggregates (level_metrics / low_clear_inventory), stored bot v2.4 rows
(training file + cand_a1a2 A2 rows) and the doc 33 §12 comparison only.

  support  §1 table: per actual band — levels, first-try n, Wilson CI, map match, placement / gimmick / version
           skew, training inclusion and exclusion reasons → lowband/support.{json,md}
  eval     §2–3 pre-registered comparison (doc 36 §3, committed before this was run) → lowband/compare.{json,md}

Run from the worktree root with the analysis venv (numpy only); data are read from the main checkout's ignored
sandbox (CR_DATA_ROOT, default ../TileMatchAutoLevel/backend/data), outputs go to <CAL>/lowband/.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clear_rate_cand_a1a2 as CA  # noqa: E402  (data paths, dataset(), tr())

CAL = CA.CAL
OUT = CAL / "lowband"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


def save(path, obj):
    CA.save(path, obj)


# ── §1 data support ─────────────────────────────────────────────────────────────────────────────
BANDS = (("<0.50", -9, 0.50), ("0.50-0.70", 0.50, 0.70), ("0.70-0.85", 0.70, 0.85),
         ("0.85-0.92", 0.85, 0.92), ("0.92-0.96", 0.92, 0.96), (">=0.96", 0.96, 9))
PLACE = (("L1-31", 1, 31), ("L32-100", 32, 100), ("L101-300", 101, 300), ("L301-500", 301, 500),
         ("L501-1000", 501, 1000), ("L1001-1500", 1001, 1500))
MIN_N = 100


def wilson(k, n, z=1.96):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def version_z(v):
    a, b = v.get("android|1.0.162"), v.get("android|1.1.0")
    if not a or not b or not a["n"] or not b["n"]:
        return None
    p = (a["rate"] * a["n"] + b["rate"] * b["n"]) / (a["n"] + b["n"])
    se = math.sqrt(max(1e-12, p * (1 - p) * (1 / a["n"] + 1 / b["n"])))
    return (b["rate"] - a["rate"]) / se


def maps_all():
    """Played map per level: build-1.1.0 shard prep (L32..578, same as training); editor LIVE3 source otherwise
    (gimmick presence only — marked as such)."""
    P, _ = CA.prep_all()
    src = CA.load(CA.DATA / "pv_sandbox/pv_20261002_live3/source.json")["levels"]
    out = {}
    for lv in src:
        L = int(lv["meta"]["level_number"])
        out[L] = (lv["level_json"], "editor_live3")
    for L, p in P.items():
        out[int(L)] = (p["map"], "shard_110")
    return out


def cmd_support(a):
    TR = CA.tr()
    inv = CA.load(CAL / "low_clear_inventory.json")
    LM = {r["level"]: r for r in CA.load(CAL / "level_metrics.json")["levels"]}
    bot_L = {r["L"] for r in CA.load(CAL / TR.BOT_FILE)["rows"]} | {r["L"] for r in CA.load(CA.OUT / "bot_v24_rules_A2.json")["rows"]}
    added = set(CA.A1) | set(CA.A2)
    maps = maps_all()
    recs = []
    for x in inv["all_levels"]:
        L, ft, n = x["L"], x["ft_any"], x["n_first_try_ended"] or 0
        if not x["has_af_data"] or ft is None:
            continue
        k = round(ft * n)
        lo, hi = wilson(k, n)
        mf = TR.FE.map_features(maps[L][0]) if L in maps else None
        gims = TR.FE.present_gimmicks(mf) if mf else []
        lm = LM.get(L, {})
        recs.append({
            "L": L, "ft_any": ft, "n": n, "wilson": [round(lo, 4), round(hi, 4)], "half_width": round((hi - lo) / 2, 4),
            "map_match": x["map_match"], "analyzable": n >= MIN_N and x["map_match"] == "same",
            "in_379": x["in_379"], "in_394": x["in_379"] or L in added, "bot_measured": L in bot_L,
            "exclusion": x["exclusion_reason"], "help_rate": x["help_rate"], "noend_rate": x["noend_rate"],
            "combo": TR.combo_key(gims) if mf else None, "has_bomb": "bomb" in gims, "map_source": maps.get(L, (0, None))[1],
            "gimmick_first": bool(lm.get("is_gimmick_first")), "is_boss": bool(lm.get("is_boss")),
            "version_z": version_z(x["clean_ft_by_version"] or {}),
            "ver_n": {k2: v["n"] for k2, v in (x["clean_ft_by_version"] or {}).items()},
            "place": next(s for s, l0, h0 in PLACE if l0 <= L <= h0)})
    out = {"bands": {}, "levels_lt085_analyzable": [], "note": "ft_any = first-try clear incl. help, no_end excluded; "
           "Wilson on k=round(ft_any·n), n = first-try ended; analyzable = n ≥ 100 ∧ map_match == same"}
    for nm, lo, hi in BANDS:
        B = [r for r in recs if lo <= r["ft_any"] < hi]
        A = [r for r in B if r["analyzable"]]
        hw = sorted(r["half_width"] for r in A)
        vz = [r["version_z"] for r in A if r["version_z"] is not None]
        vn = Counter()
        for r in A:
            vn.update(r["ver_n"])
        tot_vn = sum(vn.values()) or 1
        excl = Counter(("in_394" if r["in_394"] else (r["exclusion"] or "none")) for r in A)
        out["bands"][nm] = {
            "levels_observed": len(B), "first_try_n_sum_observed": sum(r["n"] for r in B),
            "first_try_n_median_observed": sorted(r["n"] for r in B)[len(B) // 2] if B else None,
            "map_match_observed": dict(Counter(r["map_match"] for r in B)),
            "not_analyzable": {"n_lt_100": sum(r["n"] < MIN_N for r in B),
                               "map_not_same_n_ge_100": sum(r["n"] >= MIN_N and r["map_match"] != "same" for r in B)},
            "analyzable": len(A),
            "analyzable_first_try_n": {"min": min((r["n"] for r in A), default=None),
                                       "median": sorted(r["n"] for r in A)[len(A) // 2] if A else None,
                                       "max": max((r["n"] for r in A), default=None)},
            "analyzable_wilson_half_width": {"median": hw[len(hw) // 2] if hw else None, "max": hw[-1] if hw else None},
            "analyzable_wilson_upper_lt_band_hi": sum(r["wilson"][1] < hi for r in A),
            "analyzable_wilson_upper_lt_085": sum(r["wilson"][1] < 0.85 for r in A),
            "analyzable_by_place": dict(Counter(r["place"] for r in A)),
            "analyzable_in_379": sum(r["in_379"] for r in A), "analyzable_in_394": sum(r["in_394"] for r in A),
            "analyzable_bot_measured": sum(r["bot_measured"] for r in A),
            "analyzable_inclusion": dict(excl),
            "analyzable_has_bomb_share": round(sum(r["has_bomb"] for r in A) / len(A), 3) if A else None,
            "analyzable_gimmick_first_share": round(sum(r["gimmick_first"] for r in A) / len(A), 3) if A else None,
            "analyzable_top_combos": Counter(r["combo"] for r in A).most_common(5),
            "analyzable_help_rate_mean": round(sum(r["help_rate"] or 0 for r in A) / len(A), 4) if A else None,
            "analyzable_version_share": {k2: round(v / tot_vn, 3) for k2, v in sorted(vn.items())},
            "analyzable_version_abs_z_gt_1_96": sum(abs(z) > 1.96 for z in vz), "analyzable_version_z_n": len(vz),
            "analyzable_levels": [r["L"] for r in sorted(A, key=lambda r: r["ft_any"])] if hi <= 0.85 else None,
        }
    out["levels_lt085_analyzable"] = [r for r in sorted(recs, key=lambda r: r["ft_any"]) if r["analyzable"] and r["ft_any"] < 0.85]
    save(OUT / "support.json", out)
    (OUT / "support.md").write_text(render_support(out), encoding="utf-8")
    log("saved", OUT / "support.json")


def render_support(o):
    B = o["bands"]
    names = list(B)
    row = lambda title, f: f"| {title} | " + " | ".join(str(f(B[n])) for n in names) + " |"
    L = ["| 항목 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
         row("관측 레벨(n 무관)", lambda b: b["levels_observed"]),
         row("관측 첫시도 n 합 / 중앙값", lambda b: f"{b['first_try_n_sum_observed']} / {b['first_try_n_median_observed']}"),
         row("분석 불가: n<100 / 맵 불일치", lambda b: f"{b['not_analyzable']['n_lt_100']} / {b['not_analyzable']['map_not_same_n_ge_100']}"),
         row("**분석 가능**(n≥100·맵 same)", lambda b: f"**{b['analyzable']}**"),
         row("분석 가능 n 최소/중앙/최대", lambda b: "{min}/{median}/{max}".format(**b["analyzable_first_try_n"])),
         row("Wilson 95% 반폭 중앙/최대", lambda b: "{median}/{max}".format(**b["analyzable_wilson_half_width"])),
         row("Wilson 상한 < 구간 상단", lambda b: b["analyzable_wilson_upper_lt_band_hi"]),
         row("Wilson 상한 < 0.85", lambda b: b["analyzable_wilson_upper_lt_085"]),
         row("379 포함 / 394 포함", lambda b: f"{b['analyzable_in_379']} / {b['analyzable_in_394']}"),
         row("봇 v2.4 측정 있음", lambda b: b["analyzable_bot_measured"]),
         row("394 밖 사유", lambda b: ", ".join(f"{k}:{v}" for k, v in b["analyzable_inclusion"].items() if k != "in_394") or "-"),
         row("배치 구간", lambda b: ", ".join(f"{k}:{v}" for k, v in sorted(b["analyzable_by_place"].items()))),
         row("폭탄 포함 비율", lambda b: b["analyzable_has_bomb_share"]),
         row("기믹 첫 등장 비율", lambda b: b["analyzable_gimmick_first_share"]),
         row("도움 사용률 평균", lambda b: b["analyzable_help_rate_mean"]),
         row("버전 n 비중(1.0.162/1.1.0/ios)", lambda b: "/".join(str(v) for v in b["analyzable_version_share"].values())),
         row("버전 |z|>1.96 / z 계산 레벨", lambda b: f"{b['analyzable_version_abs_z_gt_1_96']} / {b['analyzable_version_z_n']}")]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("support").set_defaults(f=cmd_support)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
