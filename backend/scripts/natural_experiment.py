"""자연 실험: AF map_match="mixed" 레벨(앱버전별 맵 다름)의 실제 유저 클리어율 차이(유저Δ) vs
봇 v2.3 클리어율 차이(봇Δ) 비교 — 25_natural_experiment_map_change.md 근거 데이터.

목표: 라이브 A/B 없이, 기존에 이미 존재하는 "자연 실험"으로 봇이 예측하는 맵간 클리어율 차이가
실제 유저 차이로 어떻게 환산되는지(기울기) 추정한다. DDA 시드 변형 선별 기준(|봇Δ|≥0.13)이
유저 체감 차이로 얼마나 되는지의 1차 근거.

데이터 소스 (전부 읽기만 함, AF CSV 재처리 없음 — level_metrics.json 재사용):
  backend/data/pv_sandbox/af_calibration/level_metrics.json (af_level_metrics.py 산출물)
    각 레벨 clean_ft_by_version: {"android|1.0.162":{n,rate}, "android|1.1.0":{...}, "ios|2.1.0":{...}}
    map_match: "same"(변화 없음, 드리프트 대조군) | "mixed"(버전별 맵 다름, 대상)
  게임 저장소 sp_meowsgarden (git show, 샤드 복호만 — 수정 없음):
    구맵 = android 1.0.162 샤드(커밋 a2229a5d), 신맵 = android 1.1.0 / ios 2.1.0 샤드(커밋 b741f6a3,
    에디터 LIVE3 소스와 동일 — af_level_metrics.VERSION_SHARD_COMMIT 근거)

Sub-commands (결과 backend/data/pv_sandbox/af_calibration/natural_exp/):
  af       level_metrics.json에서 mixed 레벨 유저Δ(버전 간 클리어율 차이) + same 레벨로 시간
           드리프트 보정(차이의 차이) → af_deltas.json
  maps     구맵/신맵 pull(git show) + row + 변화 종류 분류(tile_only/gimmick_changed/layout_changed)
           → maps.json
  run      봇 v2.3, θ grid, 레벨×맵×θ당 --games(기본 400)판 → bot_rows.json (resumable)
  report   유저Δ(보정) vs 봇Δ 산점·부호일치·역분산가중회귀 기울기(+CI)·상관 → report.json

Workers <= 2 (다른 장기 측정이 CPU 사용 중).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

OUT = BACKEND / "data/pv_sandbox/af_calibration/natural_exp"
GAME_REPO = "/Users/casualdev/sp_meowsgarden"
LEVEL_METRICS = BACKEND / "data/pv_sandbox/af_calibration/level_metrics.json"

OLD_COMMIT = "a2229a5d"                 # android 1.0.162 shard
NEW_COMMIT = "b741f6a3"                 # android 1.1.0 / ios 2.1.0 shard (= 에디터 LIVE3)
OLD_VERSIONS = ("android|1.0.162",)
NEW_VERSIONS = ("android|1.1.0", "ios|2.1.0")
WORKERS = min(2, int(os.environ.get("PV_WORKERS", "2")))
GAMES_DEFAULT = 400
THETAS_DEFAULT = (0.65, 0.75, 0.85)     # 14_bot_v2_vs_af_L1_31.md: L1~31 보정 θ v1≈0.85, v2≈0.75~0.85 근방


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), indent=1)
    os.replace(tmp, OUT / name)


# ── af: 유저Δ + 시간 드리프트 보정 ──────────────────────────────────────────────────────────────
def _combine(by_version, keys):
    n = sum((by_version.get(k) or {}).get("n", 0) for k in keys)
    if n == 0:
        return None, 0
    k = sum(round((by_version.get(key) or {}).get("n", 0) * (by_version.get(key) or {}).get("rate", 0))
            for key in keys)
    return k / n, n


def _wilson_var(p, n):
    """정규근사 분산(바이너미얼) — 역분산 가중치용. n=0 → None."""
    if not n:
        return None
    return p * (1 - p) / n


def cmd_af(a):
    from af_level_metrics import wilson
    rows = {r["level"]: r for r in load(LEVEL_METRICS)["levels"] if r["level"] <= 31}

    def level_pair(r):
        bv = r.get("clean_ft_by_version") or {}
        p_old, n_old = _combine(bv, OLD_VERSIONS)
        p_new, n_new = _combine(bv, NEW_VERSIONS)
        if p_old is None or p_new is None:
            return None
        diff = p_new - p_old
        var = _wilson_var(p_old, n_old) or 0
        var += _wilson_var(p_new, n_new) or 0
        return {"level": r["level"], "old": {"n": n_old, "rate": round(p_old, 4)},
                "new": {"n": n_new, "rate": round(p_new, 4)},
                "diff_raw": round(diff, 4), "diff_var": var}

    mixed = {L: level_pair(r) for L, r in rows.items() if r.get("map_match") == "mixed"}
    mixed = {L: v for L, v in mixed.items() if v}
    control = {L: level_pair(r) for L, r in rows.items() if r.get("map_match") == "same"}
    control = {L: v for L, v in control.items() if v}

    # 드리프트: 대조군(map_match=same) 역분산 가중 평균 diff_raw — 맵이 안 바뀐 레벨의 "버전 간 차이"는
    # 전부 시간 드리프트/표본노이즈여야 한다.
    ws = [(1 / v["diff_var"] if v["diff_var"] else 0, v["diff_raw"]) for v in control.values()]
    wsum = sum(w for w, _ in ws)
    drift_mean = sum(w * d for w, d in ws) / wsum if wsum else 0.0
    drift_var = 1 / wsum if wsum else None
    for v in mixed.values():
        v["diff_corrected"] = round(v["diff_raw"] - drift_mean, 4)

    out = {"old_versions": OLD_VERSIONS, "new_versions": NEW_VERSIONS,
           "drift": {"mean": round(drift_mean, 4), "var": drift_var, "n_control_levels": len(control),
                     "per_level": {L: v["diff_raw"] for L, v in sorted(control.items())}},
           "mixed": mixed}
    save("af_deltas.json", out)
    print(f"mixed={len(mixed)} control={len(control)} drift_mean={drift_mean:.4f}")
    for L, v in sorted(mixed.items()):
        print(L, v["old"], v["new"], "diff_raw", v["diff_raw"], "diff_corrected", v["diff_corrected"])


# ── maps: pull + 변화 종류 분류 ─────────────────────────────────────────────────────────────────
ROW_KEYS = ("randSeed", "useTileCount", "unlockTile", "shuffleTile", "typeImbalance", "autoCollectCount", "layer")


def _git_key(commit, key):
    from pv_scan_shards import decrypt_shard_file
    p = f"Assets/StreamingAssets/GBoost/a{hashlib.md5(key.encode()).hexdigest()}.txt"
    r = subprocess.run(["git", "-C", GAME_REPO, "show", f"{commit}:{p}"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git show failed: {commit}:{key}")
    return decrypt_shard_file(r.stdout)


def _rows_table(commit):
    tab = _git_key(commit, "levels")
    keys = tab["__keys"]
    out = {}
    for v in tab["__vals"]:
        o = {keys[i]: v[i] for i in range(min(len(keys), len(v)))}
        out[str(o.get("id"))] = o
    return out


def _flatten(canon_map):
    """{(layer, pos): (effect, container_root)} — 구조 차이(기믹/컨테이너 vs 레이아웃) 분류용."""
    n = int(canon_map.get("layer", 0) or 0)
    out = {}
    for i in range(n):
        layer = canon_map.get(f"layer_{i}") or {}
        tiles = layer.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue
        for pos, t in tiles.items():
            if not isinstance(t, list) or len(t) < 2:
                continue
            effect = t[1] if isinstance(t[1], str) else ""
            is_container = len(t) >= 3 and isinstance(t[2], list) and len(t[2]) >= 1
            root = t[0] if is_container and isinstance(t[0], str) else ""
            out[(i, pos)] = (effect, root)
    return out


GIMMICK_TAGS = ("ice", "chain", "grass", "bomb", "curtain", "teleport", "frog", "key", "link")


def classify_change(map_old, map_new):
    from app.core.pv.canonical import struct_hash
    if struct_hash(map_old) == struct_hash(map_new):
        return "tile_only"
    fa, fb = _flatten(map_old), _flatten(map_new)
    for k in set(fa) | set(fb):
        va, vb = fa.get(k, ("", "")), fb.get(k, ("", ""))
        if va == vb:
            continue
        eff = (va[0] or vb[0] or "").lower()
        root = va[1] or vb[1]
        if root or any(tag in eff for tag in GIMMICK_TAGS):
            return "gimmick_changed"
    return "layout_changed"


def cmd_maps(a):
    from app.core.pv.canonical import canonical_map
    levels = sorted(int(k) for k in load(OUT / "af_deltas.json")["mixed"])
    maps_old = _git_key(OLD_COMMIT, "levelmap_level_0")   # L1-100 live in shard 0
    maps_new = _git_key(NEW_COMMIT, "levelmap_level_0")
    rows_old, rows_new = _rows_table(OLD_COMMIT), _rows_table(NEW_COMMIT)
    out = {}
    for L in levels:
        m_old, m_new = maps_old[f"level_{L}"], maps_new[f"level_{L}"]
        r_old, r_new = rows_old[f"level_{L}"], rows_new[f"level_{L}"]
        c_old, c_new = canonical_map(m_old), canonical_map(m_new)
        out[L] = {
            "old": {"row": {k: r_old.get(k) for k in ROW_KEYS}, "map": m_old},
            "new": {"row": {k: r_new.get(k) for k in ROW_KEYS}, "map": m_new},
            "row_changed": {k: [r_old.get(k), r_new.get(k)] for k in ROW_KEYS if r_old.get(k) != r_new.get(k)},
            "change_type": classify_change(c_old, c_new),
        }
    save("maps.json", out)
    for L, v in sorted(out.items()):
        print(L, v["change_type"], "row_changed" if v["row_changed"] else "", v["row_changed"])


# ── run: 봇 v2.3 ────────────────────────────────────────────────────────────────────────────────
def level_layouts(entry):
    """bot_af_L1_31.level_layouts 와 동일 로직(모듈 분리 — maps.json 소스가 다름)."""
    from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles
    from app.core.pv.t0ize import bot_level_json
    row = entry["row"]
    fixed = int(row.get("randSeed") or 0)
    seeds = [fixed] if fixed else list(range(1, 33))   # randSeed 0 → 32 레이아웃(클라 시간시드 포팅)
    out = []
    for s in seeds:
        res = shuffle_empty_tiles(entry["map"], rand_seed=s, use_tile_count=row["useTileCount"],
                                  unlock_tile=row.get("unlockTile") or 0, shuffle_tile=row.get("shuffleTile") or 0,
                                  type_imbalance=row.get("typeImbalance") or 0, strict=True)
        r2 = {"randSeed": s, "useTileCount": row["useTileCount"], "unlockTile": row.get("unlockTile") or 0}
        out.append(bot_level_json(r2, resolve_map(entry["map"], res)))
    return out


def run_task(args):
    from app.core.bot_simulator import BotSimulator
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    entry = load(OUT / "maps.json")[str(args["L"])][args["which"]]
    lays = level_layouts(entry)
    games = args["games"]
    n_lay = min(32, games)
    lays = lays[:n_lay] if len(lays) > 1 else lays
    per = max(1, games // len(lays))
    prof = make_skill_profile(args["theta"], "v2.3")
    auto = int(float(entry["row"].get("autoCollectCount") or 0))
    if auto:
        import dataclasses
        cfg = dict(prof.gimmick_awareness)
        cfg["auto_collect"] = auto
        prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    wins, n = 0, 0
    for li, lj in enumerate(lays):
        bot.set_rule_parity(prof)
        base_state = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(base_state)
        for g in range(per):
            bot._rng.seed(13_000_000 + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(base_state), prof)
            n += 1
            wins += 1 if final.cleared else 0
    return {"L": args["L"], "which": args["which"], "theta": args["theta"], "games": n, "wins": wins,
            "layouts": len(lays), "sec": time.time() - t0}


def cmd_run(a):
    path = OUT / "bot_rows.json"
    done = load(path) if path.exists() else {"rows": []}
    have = {(r["L"], r["which"], r["theta"]) for r in done["rows"]}
    levels = sorted(int(k) for k in load(OUT / "maps.json"))
    thetas = [float(x) for x in a.thetas.split(",")] if a.thetas else THETAS_DEFAULT
    todo = [{"L": L, "which": w, "theta": th, "games": a.games}
            for L in levels for w in ("old", "new") for th in thetas if (L, w, th) not in have]
    print(f"todo={len(todo)} workers={WORKERS}")
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(run_task, todo, chunksize=1):
            done["rows"].append(r)
            if time.time() - t0 > 30:
                save("bot_rows.json", done)
                t0 = time.time()
    save("bot_rows.json", done)
    print(f"run done rows={len(done['rows'])}")


# ── report ──────────────────────────────────────────────────────────────────────────────────────
def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    den = (sxx * syy) ** 0.5
    return sxy / den if den else float("nan")


def weighted_regression(xs, ys, ws):
    """WLS y = a + b*x, weights ws. 반환: slope, intercept, slope_se, slope_ci95 (t, df=n-2)."""
    n = len(xs)
    wsum = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / wsum
    my = sum(w * y for w, y in zip(ws, ys)) / wsum
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    b = sxy / sxx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    df = n - 2
    if df <= 0:
        return b, a, None, [None, None]
    sigma2 = sum(w * r * r for w, r in zip(ws, resid)) / df
    se_b = (sigma2 / sxx) ** 0.5
    # t-critical, 95% — small lookup for common df, else normal approx
    t_table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
               10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110,
               18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}
    tcrit = t_table.get(df, 1.96)
    return b, a, se_b, [round(b - tcrit * se_b, 4), round(b + tcrit * se_b, 4)]


def cmd_report(a):
    af = load(OUT / "af_deltas.json")
    maps_meta = load(OUT / "maps.json")
    rows = load(OUT / "bot_rows.json")["rows"]
    by_lw = {}
    for r in rows:
        by_lw.setdefault((r["L"], r["which"]), []).append(r)

    levels = sorted(int(L) for L in af["mixed"])
    per_level = {}
    for L in levels:
        old_rs = by_lw.get((L, "old"), [])
        new_rs = by_lw.get((L, "new"), [])
        if not old_rs or not new_rs:
            continue
        p_old = sum(r["wins"] for r in old_rs) / sum(r["games"] for r in old_rs)
        p_new = sum(r["wins"] for r in new_rs) / sum(r["games"] for r in new_rs)
        n_old = sum(r["games"] for r in old_rs)
        n_new = sum(r["games"] for r in new_rs)
        var = p_old * (1 - p_old) / n_old + p_new * (1 - p_new) / n_new
        per_level[L] = {
            "change_type": maps_meta[str(L)]["change_type"],
            "user_n_old": af["mixed"][str(L)]["old"]["n"], "user_n_new": af["mixed"][str(L)]["new"]["n"],
            "user_diff_raw": af["mixed"][str(L)]["diff_raw"], "user_diff_corrected": af["mixed"][str(L)]["diff_corrected"],
            "user_diff_var": af["mixed"][str(L)]["diff_var"],
            "bot_old": round(p_old, 4), "bot_new": round(p_new, 4), "bot_diff": round(p_new - p_old, 4),
            "bot_n_old": n_old, "bot_n_new": n_new, "bot_diff_var": var,
            "by_theta": {str(r["theta"]): None for r in old_rs},
        }
        for th in sorted({r["theta"] for r in old_rs}):
            po = [r for r in old_rs if r["theta"] == th]
            pn = [r for r in new_rs if r["theta"] == th]
            ro = sum(r["wins"] for r in po) / sum(r["games"] for r in po)
            rn = sum(r["wins"] for r in pn) / sum(r["games"] for r in pn)
            per_level[L]["by_theta"][str(th)] = {"old": round(ro, 4), "new": round(rn, 4), "diff": round(rn - ro, 4)}

    small_n = {L: v for L, v in per_level.items() if min(v["user_n_old"], v["user_n_new"]) < 30}
    usable = {L: v for L, v in per_level.items() if L not in small_n}

    def analyze(subset, label):
        if len(subset) < 3:
            return {"label": label, "n": len(subset), "note": "표본 레벨 3개 미만 — 회귀 생략"}
        # 24_live_pilot_design.md §3: 봇Δ는 n이 커서(여기 ≥400x2) 거의 고정값, 유저Δ 분산으로 역분산 가중.
        xs = [v["bot_diff"] for v in subset.values()]
        ys = [v["user_diff_corrected"] for v in subset.values()]
        ws = [1 / v["user_diff_var"] if v["user_diff_var"] else 1.0 for v in subset.values()]
        sign_agree = sum(1 for v in subset.values()
                         if (v["bot_diff"] > 0) == (v["user_diff_corrected"] > 0) or
                            (abs(v["bot_diff"]) < 1e-6 and abs(v["user_diff_corrected"]) < 1e-6))
        slope, intercept, se, ci = weighted_regression(xs, ys, ws)
        return {"label": label, "n": len(subset), "sign_agreement": round(sign_agree / len(subset), 3),
                "pearson_r": round(pearson(xs, ys), 3), "slope": round(slope, 3), "slope_se": round(se, 3) if se else None,
                "slope_ci95": ci, "intercept": round(intercept, 4)}

    rep = {
        "n_mixed_levels": len(af["mixed"]), "n_control_levels": af["drift"]["n_control_levels"],
        "drift_correction": af["drift"]["mean"],
        "change_type_counts": {t: sum(1 for v in per_level.values() if v["change_type"] == t)
                               for t in ("tile_only", "gimmick_changed", "layout_changed")},
        "small_n_levels": sorted(small_n), "small_n_excluded_from": "all/usable 분석 (레벨별 결과엔 포함)",
        "all": analyze(per_level, "전체"),
        "usable": analyze(usable, "유저n>=30 둘다"),
        "tile_only": analyze({L: v for L, v in usable.items() if v["change_type"] == "tile_only"}, "타일만 변경"),
        "layout_changed": analyze({L: v for L, v in usable.items() if v["change_type"] == "layout_changed"}, "레이아웃 변경"),
        "gimmick_changed": analyze({L: v for L, v in usable.items() if v["change_type"] == "gimmick_changed"}, "기믹 변경"),
        "per_level": per_level,
    }
    save("report.json", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "per_level"}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("af").set_defaults(f=cmd_af)
    sub.add_parser("maps").set_defaults(f=cmd_maps)
    p = sub.add_parser("run")
    p.add_argument("--thetas", default="")
    p.add_argument("--games", type=int, default=GAMES_DEFAULT)
    p.set_defaults(f=cmd_run)
    sub.add_parser("report").set_defaults(f=cmd_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
