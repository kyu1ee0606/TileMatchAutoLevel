"""자연 실험 확장: RUN_VERSIONS 밖(판 재구성 불가 구버전)까지 포함한 추가 맵-교체 전환점.

25_natural_experiment_map_change.md / natural_experiment.py는 C→D 전환(android 1.0.162 → 1.1.0/
ios 2.1.0)만 썼다 — RUN_VERSIONS 3개로 한정된 탓에 L1~31 20레벨뿐이었다. `af_attempt_ft.py`가
`level_start` 없이도(attempt 필드로 직접 묶어) 신뢰 가능한 첫시도 클리어율을 구버전까지 뽑아낸 걸 이용해
더 이른 맵 교체 전환점을 추가한다(28_bot_v1_vs_v2_discrimination.md 확장).

버전→빌드 내장 샤드 커밋 조사(읽기전용 git 조사, 전부 `af_level_metrics.py`의 VERSION_SHARD_COMMIT과
같은 방법): 1.0.143~1.0.156(146·147·148·149·151·152·156) 전부 같은 샤드(`1e0b3579`) — 1.0.146·147은
v1.10.1025(=1.0.148, 델타 갱신 비활성화 기준점) **이전**이라 델타패치로 실제 맵이 빌드 내장본과 다를
위험이 있어 제외. 1.0.160(=ios 2.0.160)에서 `9593daea`로 교체, 1.0.162에서 `a2229a5d`로 교체(기존
C), 1.1.0/2.1.0에서 `b741f6a3`로 교체(기존 D, natural_experiment.py가 이미 씀).

EPOCHS: A(1e0b3579, 1.0.148~156 풀링) → B(9593daea, 1.0.160/ios2.0.160) → C(a2229a5d, 1.0.162)
→ D(b741f6a3, 1.1.0/2.1.0, 기존 C→D 그대로 natural_experiment.py 참조).
이 스크립트는 A→B, B→C 두 전환만 다룬다(C→D는 natural_experiment.py 산출물 재사용).

Sub-commands (결과 backend/data/pv_sandbox/af_calibration/natural_exp_ext/):
  maps <T>      두 epoch의 전체 레벨맵(1~1500, 샤드 0~15 전부) pull + row + 변화종류 분류 → maps_<T>.json
  af <T>        attempt_ft/all_versions.json 풀링(에포크별 버전 합산) 유저Δ + 드리프트 보정(맵 안 바뀐
                레벨로) + n>=50(양쪽) 필터 → af_deltas_<T>.json
  run <T> --bot-version v1|v2.3   mixed 레벨 전부 봇 측정 → bot_rows_<T>.json (resumable)
  report <T> --bot-version        회귀(logit) → report_<T>_<ver>.json
  pool          A→B, B→C, (+ natural_exp/report*.json 의 C→D) 전부 모아 봇버전별 통합 회귀 +
                v1 vs v2.3 부트스트랩 diff CI → pool_report.json

Workers<=2(다른 측정과 합쳐 전체 측정 프로세스 2개 제한).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

OUT = BACKEND / "data/pv_sandbox/af_calibration/natural_exp_ext"
CACHE = OUT / "map_cache"
GAME_REPO = "/Users/casualdev/sp_meowsgarden"
ATTEMPT_FT = BACKEND / "data/pv_sandbox/af_calibration/attempt_ft/all_versions.json"
ORIG_OUT = BACKEND / "data/pv_sandbox/af_calibration/natural_exp"  # C→D(기존) 산출물 위치

MAX_LEVEL = 1500
WORKERS = min(2, int(os.environ.get("PV_WORKERS", "2")))
GAMES_DEFAULT = 400
THETAS_DEFAULT = (0.65, 0.75, 0.85)
MIN_USER_N = 50  # 맵별 첫시도(클린) n 하한

EPOCHS = {
    "A": {"commit": "1e0b3579", "versions": [("android", "1.0.148"), ("android", "1.0.149"),
                                               ("android", "1.0.151"), ("android", "1.0.152"),
                                               ("android", "1.0.156")]},
    "B": {"commit": "9593daea", "versions": [("android", "1.0.160"), ("ios", "2.0.160")]},
    "C": {"commit": "a2229a5d", "versions": [("android", "1.0.162")]},
}
TRANSITIONS = {"AB": ("A", "B"), "BC": ("B", "C")}

ROW_KEYS = ("randSeed", "useTileCount", "unlockTile", "shuffleTile", "typeImbalance", "autoCollectCount", "layer")
GIMMICK_TAGS = ("ice", "chain", "grass", "bomb", "curtain", "teleport", "frog", "key", "link")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), indent=1)
    os.replace(tmp, path)


# ── 맵 pull(커밋 전체 1~1500, 샤드 0~15) — 커밋당 1회 캐시 ───────────────────────────────────────
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


def pull_commit(commit):
    """커밋의 전 레벨 맵+row. 결과를 CACHE/<commit>.json 에 캐시(git show 16+1회만)."""
    cf = CACHE / f"{commit}.json"
    if cf.exists():
        return load(cf)
    maps = {}
    for i in range(16):
        try:
            maps.update(_git_key(commit, f"levelmap_level_{i}"))
        except RuntimeError:
            continue
    rows = _rows_table(commit)
    out = {"maps": maps, "rows": rows}
    save(cf, out)
    return out


def _flatten(canon_map):
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
    old_e, new_e = TRANSITIONS[a.transition]
    old_c, new_c = EPOCHS[old_e]["commit"], EPOCHS[new_e]["commit"]
    print(f"pulling {old_e}({old_c}) + {new_e}({new_c})", flush=True)
    old = pull_commit(old_c)
    new = pull_commit(new_c)
    from app.core.pv.canonical import canonical_map
    out = {}
    levels = sorted(set(int(k.split("_")[1]) for k in old["maps"] if k.startswith("level_"))
                     & set(int(k.split("_")[1]) for k in new["maps"] if k.startswith("level_")))
    for L in levels:
        key = f"level_{L}"
        m_old, m_new = old["maps"].get(key), new["maps"].get(key)
        r_old, r_new = old["rows"].get(key), new["rows"].get(key)
        if not m_old or not m_new or not r_old or not r_new:
            continue
        c_old, c_new = canonical_map(m_old), canonical_map(m_new)
        full_old = hashlib.sha256(json.dumps(c_old, separators=(",", ":")).encode()).hexdigest()
        full_new = hashlib.sha256(json.dumps(c_new, separators=(",", ":")).encode()).hexdigest()
        row_changed = {k: [r_old.get(k), r_new.get(k)] for k in ROW_KEYS if r_old.get(k) != r_new.get(k)}
        ct = classify_change(c_old, c_new)
        # map_changed = 전체(타입 포함) 해시가 다르거나 row(랜덤시드·장수 등)가 다른 경우만 — struct_hash
        # 버킷(change_type)이 "tile_only"여도 full_old==full_new면 "아무것도 안 바뀐 것"이라 제외해야 한다
        # (AB/BC 전환 대부분이 이 경우 — 바이트까지 완전히 동일한 레벨).
        map_changed = (full_old != full_new) or bool(row_changed)
        out[L] = {"old": {"row": {k: r_old.get(k) for k in ROW_KEYS}, "map": m_old},
                   "new": {"row": {k: r_new.get(k) for k in ROW_KEYS}, "map": m_new},
                   "row_changed": row_changed, "change_type": ct, "map_changed": map_changed}
    save(OUT / f"maps_{a.transition}.json", out)
    counts = {}
    for v in out.values():
        counts[v["change_type"]] = counts.get(v["change_type"], 0) + 1
    print(f"levels common={len(levels)} out={len(out)} change_type_counts={counts}")


# ── af: attempt_ft 풀링 + 드리프트 보정 ────────────────────────────────────────────────────────────
def logit(p):
    return math.log(p / (1 - p))


def cc(p, n):
    if not n:
        return 0.5
    k = round(p * n)
    return (k + 0.5) / (n + 1)


def _pool_epoch(ft, epoch):
    """attempt_ft all_versions.json 에서 그 에포크 버전들의 레벨별 n/clear 합산."""
    out = {}
    for plat, ver in EPOCHS[epoch]["versions"]:
        key = f"{plat}|{ver}"
        for L, v in ft.get(key, {}).items():
            o = out.setdefault(int(L), {"n": 0, "clear": 0})
            o["n"] += v["n_clean"]
            o["clear"] += v["clear_clean"]
    return out


def cmd_af(a):
    old_e, new_e = TRANSITIONS[a.transition]
    ft = load(ATTEMPT_FT)
    pool_old, pool_new = _pool_epoch(ft, old_e), _pool_epoch(ft, new_e)
    maps_meta = load(OUT / f"maps_{a.transition}.json")
    levels = sorted(int(L) for L in maps_meta)

    def rate(pool, L):
        o = pool.get(L)
        if not o or o["n"] < MIN_USER_N:
            return None
        return o["clear"] / o["n"], o["n"]

    mixed, control = {}, {}
    for L in levels:
        ro, rn = rate(pool_old, L), rate(pool_new, L)
        if ro is None or rn is None:
            continue
        p_old, n_old = ro
        p_new, n_new = rn
        diff = p_new - p_old
        var = p_old * (1 - p_old) / n_old + p_new * (1 - p_new) / n_new
        p_old_c, p_new_c = cc(p_old, n_old), cc(p_new, n_new)
        n_old_c, n_new_c = n_old + 1, n_new + 1
        diff_logit = logit(p_new_c) - logit(p_old_c)
        var_logit = 1 / (n_old_c * p_old_c * (1 - p_old_c)) + 1 / (n_new_c * p_new_c * (1 - p_new_c))
        entry = {"level": L, "old": {"n": n_old, "rate": round(p_old, 4)}, "new": {"n": n_new, "rate": round(p_new, 4)},
                 "diff_raw": round(diff, 4), "diff_var": var,
                 "diff_logit_raw": round(diff_logit, 4), "diff_logit_var": var_logit,
                 "change_type": maps_meta[str(L)]["change_type"], "map_changed": maps_meta[str(L)]["map_changed"]}
        if maps_meta[str(L)]["map_changed"]:
            mixed[L] = entry
        else:
            control[L] = entry

    def wmean(group, key, vk):
        ws = [(1 / v[vk] if v[vk] else 0, v[key]) for v in group.values()]
        wsum = sum(w for w, _ in ws)
        return (sum(w * d for w, d in ws) / wsum if wsum else 0.0), (1 / wsum if wsum else None)

    drift_mean, _ = wmean(control, "diff_raw", "diff_var") if control else (0.0, None)
    drift_logit_mean, _ = wmean(control, "diff_logit_raw", "diff_logit_var") if control else (0.0, None)
    for v in mixed.values():
        v["diff_corrected"] = round(v["diff_raw"] - drift_mean, 4)
        v["diff_logit_corrected"] = round(v["diff_logit_raw"] - drift_logit_mean, 4)

    out = {"transition": a.transition, "old_epoch": old_e, "new_epoch": new_e,
           "n_mixed": len(mixed), "n_control": len(control),
           "drift_mean": round(drift_mean, 4), "drift_logit_mean": round(drift_logit_mean, 4),
           "mixed": mixed, "control_n": len(control)}
    save(OUT / f"af_deltas_{a.transition}.json", out)
    print(f"transition {a.transition}: mixed={len(mixed)} control={len(control)} "
          f"drift={drift_mean:.4f} drift_logit={drift_logit_mean:.4f}")
    ctc = {}
    for v in mixed.values():
        ctc[v["change_type"]] = ctc.get(v["change_type"], 0) + 1
    print("mixed change_type counts:", ctc)


# ── run: 봇 측정 (v1 / v2.3) ────────────────────────────────────────────────────────────────────
def level_layouts(entry):
    from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles
    from app.core.pv.t0ize import bot_level_json
    row = entry["row"]
    fixed = int(row.get("randSeed") or 0)
    seeds = [fixed] if fixed else list(range(1, 33))
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
    entry = load(OUT / f"maps_{args['transition']}.json")[str(args["L"])][args["which"]]
    try:
        lays = level_layouts(entry)
    except Exception as e:  # noqa: BLE001 — 봇 미지원 레벨(구조 이상 등) 건너뛰기, 집계에서 제외
        return {"L": args["L"], "which": args["which"], "theta": args["theta"], "bot_version": args["bot_version"],
                "games": 0, "wins": 0, "layouts": 0, "sec": time.time() - t0, "error": str(e)[:200]}
    games = args["games"]
    n_lay = min(32, games)
    lays = lays[:n_lay] if len(lays) > 1 else lays
    per = max(1, games // len(lays))
    bot_version = args["bot_version"]
    prof = make_skill_profile(args["theta"], bot_version)
    auto = int(float(entry["row"].get("autoCollectCount") or 0))
    if auto and prof.gimmick_awareness is not None:
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
            bot._rng.seed(23_000_000 + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(base_state), prof)
            n += 1
            wins += 1 if final.cleared else 0
    return {"L": args["L"], "which": args["which"], "theta": args["theta"], "bot_version": bot_version,
            "games": n, "wins": wins, "layouts": len(lays), "sec": time.time() - t0}


def cmd_run(a):
    path = OUT / f"bot_rows_{a.transition}.json"
    done = load(path) if path.exists() else {"rows": []}
    have = {(r["L"], r["which"], r["theta"], r.get("bot_version", "v2.3")) for r in done["rows"]}
    af = load(OUT / f"af_deltas_{a.transition}.json")
    levels = sorted(int(L) for L in af["mixed"])
    thetas = [float(x) for x in a.thetas.split(",")] if a.thetas else THETAS_DEFAULT
    todo = [{"L": L, "which": w, "theta": th, "games": a.games, "bot_version": a.bot_version, "transition": a.transition}
            for L in levels for w in ("old", "new") for th in thetas if (L, w, th, a.bot_version) not in have]
    print(f"transition={a.transition} bot_version={a.bot_version} todo={len(todo)} workers={WORKERS}")
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(run_task, todo, chunksize=1):
            done["rows"].append(r)
            if time.time() - t0 > 30:
                save(path, done)
                t0 = time.time()
    save(path, done)
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
    n = len(xs)
    wsum = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / wsum
    my = sum(w * y for w, y in zip(ws, ys)) / wsum
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    b = sxy / sxx if sxx else 0.0
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    df = n - 2
    if df <= 0:
        return b, a, None, [None, None]
    sigma2 = sum(w * r * r for w, r in zip(ws, resid)) / df
    se_b = (sigma2 / sxx) ** 0.5 if sxx else None
    t_table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
               10: 2.228, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 50: 2.009, 60: 2.000}
    tcrit = t_table.get(df) or min((v for k, v in t_table.items() if k >= df), default=1.96)
    return b, a, se_b, [round(b - tcrit * se_b, 4), round(b + tcrit * se_b, 4)] if se_b else [None, None]


def cmd_report(a):
    af = load(OUT / f"af_deltas_{a.transition}.json")
    rows = [r for r in load(OUT / f"bot_rows_{a.transition}.json")["rows"]
            if r.get("bot_version", "v2.3") == a.bot_version and r.get("games", 0) > 0]
    by_lw = {}
    for r in rows:
        by_lw.setdefault((r["L"], r["which"]), []).append(r)
    per_level = {}
    for L_str, entry in af["mixed"].items():
        L = int(L_str)
        old_rs, new_rs = by_lw.get((L, "old"), []), by_lw.get((L, "new"), [])
        if not old_rs or not new_rs:
            continue
        p_old = sum(r["wins"] for r in old_rs) / sum(r["games"] for r in old_rs)
        p_new = sum(r["wins"] for r in new_rs) / sum(r["games"] for r in new_rs)
        n_old, n_new = sum(r["games"] for r in old_rs), sum(r["games"] for r in new_rs)
        var = p_old * (1 - p_old) / n_old + p_new * (1 - p_new) / n_new
        bot_diff_logit = logit(cc(p_new, n_new)) - logit(cc(p_old, n_old))
        per_level[L] = {"change_type": entry["change_type"],
                        "user_diff_corrected": entry["diff_corrected"], "user_diff_var": entry["diff_var"],
                        "user_diff_logit_corrected": entry["diff_logit_corrected"], "user_diff_logit_var": entry["diff_logit_var"],
                        "bot_diff": round(p_new - p_old, 4), "bot_diff_var": var, "bot_diff_logit": round(bot_diff_logit, 4)}

    def analyze(subset, label, xk, yk, wk):
        if len(subset) < 3:
            return {"label": label, "n": len(subset), "note": "표본 3개 미만"}
        xs = [v[xk] for v in subset.values()]
        ys = [v[yk] for v in subset.values()]
        ws = [1 / v[wk] if v[wk] else 1.0 for v in subset.values()]
        sign_agree = sum(1 for v in subset.values() if (v[xk] > 0) == (v[yk] > 0) or (abs(v[xk]) < 1e-6 and abs(v[yk]) < 1e-6))
        slope, intercept, se, ci = weighted_regression(xs, ys, ws)
        return {"label": label, "n": len(subset), "sign_agreement": round(sign_agree / len(subset), 3),
                "pearson_r": round(pearson(xs, ys), 3), "slope": round(slope, 3),
                "slope_se": round(se, 4) if se else None, "slope_ci95": ci, "intercept": round(intercept, 4)}

    rep = {"transition": a.transition, "bot_version": a.bot_version, "n_mixed": len(per_level),
           "all_logit": analyze(per_level, "logit 전체", "bot_diff_logit", "user_diff_logit_corrected", "user_diff_logit_var"),
           "by_change_type": {ct: analyze({L: v for L, v in per_level.items() if v["change_type"] == ct}, ct,
                                           "bot_diff_logit", "user_diff_logit_corrected", "user_diff_logit_var")
                               for ct in ("tile_only", "layout_changed", "gimmick_changed")},
           "per_level": per_level}
    save(OUT / f"report_{a.transition}_{a.bot_version}.json", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "per_level"}, ensure_ascii=False, indent=1))


# ── pool: 전체 전환(A→B, B→C, 기존 C→D) 통합 ────────────────────────────────────────────────────
def cmd_pool(a):
    def wls_slope(xs, ys, ws):
        n = len(xs)
        wsum = sum(ws)
        mx = sum(w * x for w, x in zip(ws, xs)) / wsum
        my = sum(w * y for w, y in zip(ws, ys)) / wsum
        sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
        sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
        return sxy / sxx if sxx else 0.0

    def collect(ver):
        pts = []  # (transition, L, bot_diff_logit, user_diff_logit_corrected, weight)
        for t in ("AB", "BC"):
            p = OUT / f"report_{t}_{ver}.json"
            if not p.exists():
                continue
            per = load(p)["per_level"]
            for L, v in per.items():
                w = 1 / v["user_diff_logit_var"] if v["user_diff_logit_var"] else 1.0
                pts.append((t, int(L), v["bot_diff_logit"], v["user_diff_logit_corrected"], w, v["change_type"]))
        # 기존 C→D (natural_exp/report.json 은 v2.3, report_v1.json 은 v1)
        cd_file = ORIG_OUT / ("report.json" if ver == "v2.3" else f"report_{ver}.json")
        if cd_file.exists():
            per = load(cd_file)["per_level"]
            for L, v in per.items():
                w = 1 / v["user_diff_logit_var"] if v["user_diff_logit_var"] else 1.0
                pts.append(("CD", int(L), v["bot_diff_logit"], v["user_diff_logit_corrected"], w, v["change_type"]))
        return pts

    out = {}
    pooled = {}
    for ver in ("v1", "v2.3"):
        pts = collect(ver)
        pooled[ver] = pts
        if len(pts) < 3:
            out[ver] = {"n": len(pts), "note": "표본 부족"}
            continue
        xs = [p[2] for p in pts]
        ys = [p[3] for p in pts]
        ws = [p[4] for p in pts]
        sign_agree = sum(1 for x, y in zip(xs, ys) if (x > 0) == (y > 0) or (abs(x) < 1e-6 and abs(y) < 1e-6))
        slope, intercept, se, ci = weighted_regression(xs, ys, ws)
        by_trans = {}
        for t in ("AB", "BC", "CD"):
            sub = [p for p in pts if p[0] == t]
            by_trans[t] = len(sub)
        out[ver] = {"n": len(pts), "by_transition_n": by_trans, "sign_agreement": round(sign_agree / len(pts), 3),
                    "pearson_r": round(pearson(xs, ys), 3), "slope": round(slope, 3),
                    "slope_se": round(se, 4) if se else None, "slope_ci95": ci, "intercept": round(intercept, 4)}

    # v1 vs v2.3 부트스트랩 diff CI — (transition, L) 쌍 단위 리샘플(두 봇이 같은 레벨 집합을 봐야 공정)
    common = {}
    for ver in ("v1", "v2.3"):
        for t, L, x, y, w, ct in pooled[ver]:
            common.setdefault((t, L), {})[ver] = (x, y, w)
    keys = [k for k, v in common.items() if "v1" in v and "v2.3" in v]
    random.seed(7)
    diffs = []
    B = 5000
    if len(keys) >= 3:
        for _ in range(B):
            samp = [random.choice(keys) for _ in range(len(keys))]
            x1 = [common[k]["v1"][0] for k in samp]; y1 = [common[k]["v1"][1] for k in samp]; w1 = [common[k]["v1"][2] for k in samp]
            x2 = [common[k]["v2.3"][0] for k in samp]; y2 = [common[k]["v2.3"][1] for k in samp]; w2 = [common[k]["v2.3"][2] for k in samp]
            diffs.append(wls_slope(x1, y1, w1) - wls_slope(x2, y2, w2))
        diffs.sort()
        lo, hi = diffs[int(0.025 * B)], diffs[int(0.975 * B)]
        boot = {"n_common_points": len(keys), "mean_diff_v1_minus_v23": round(sum(diffs) / B, 4),
                "ci95": [round(lo, 4), round(hi, 4)], "share_v1_gt_v23": round(sum(1 for d in diffs if d > 0) / B, 3)}
    else:
        boot = {"n_common_points": len(keys), "note": "표본 부족"}

    rep = {"per_bot": out, "bootstrap_diff": boot}
    save(OUT / "pool_report.json", rep)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("maps")
    pm.add_argument("transition", choices=list(TRANSITIONS))
    pm.set_defaults(f=cmd_maps)
    pa = sub.add_parser("af")
    pa.add_argument("transition", choices=list(TRANSITIONS))
    pa.set_defaults(f=cmd_af)
    pr = sub.add_parser("run")
    pr.add_argument("transition", choices=list(TRANSITIONS))
    pr.add_argument("--bot-version", default="v2.3")
    pr.add_argument("--games", type=int, default=GAMES_DEFAULT)
    pr.add_argument("--thetas", default="")
    pr.set_defaults(f=cmd_run)
    pp = sub.add_parser("report")
    pp.add_argument("transition", choices=list(TRANSITIONS))
    pp.add_argument("--bot-version", default="v2.3")
    pp.set_defaults(f=cmd_report)
    sub.add_parser("pool").set_defaults(f=cmd_pool)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
