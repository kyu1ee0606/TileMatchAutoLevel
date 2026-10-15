"""[분석 전용] 라이브 파일럿(plan B v3, 21레벨) 결과 분석 — doc 24 §6 · doc 29 §5 · 10 §9-9-3.

가정: 게임이 level_start(및 clear/fail)에 파일럿 군 파라미터(기본 `pilot_arm` = control|variant)를 싣는다.
파라미터 이름·값·기간·버전은 설정(--config JSON)으로 바꾼다. 판 재구성은 af_level_metrics.py 를 그대로 재사용한다
(같은 중복 제거 키·판 규칙·첫시도·무도움 정의). 식별자는 메모리 안 해시로만 쓴다(출력 안 함).

산출 (--out, 기본 dda_sets_v2/pilot_export/eval/report.json):
  레벨별: 군별 clean_ft(첫시도·무도움) n·클리어율·Wilson CI, 유저Δ(variant−control)·SE·z, logit Δ,
          사전 등록 예측(v1·v2)과의 차, 방향 일치 여부
  풀링  : 의도 방향 Δ 역분산 가중 평균, 방향 일치율, logit 기울기(유저 logitΔ ~ 봇 logitΔ, WLS 원점·절편 둘 다; v1·v2)
  판별  : 불일치 6 묶음에서 관측 유저Δ가 v1 예측과 v2 예측 중 어디에 가까운가(가중 제곱오차·차이 z)
  가드레일: 레벨별 반대 방향 차이(>5%p, 단측 z>2), 24h 복귀율·다음 레벨 진입률·no_end 차이(−3%p, z>2),
          h2 묶음 복귀율, 방향 일치율 <50%(2주차) → 중단 권고 플래그
--aa : 군 파라미터가 없는 지금 데이터로 코드 경로 점검(A/A — 기기·레벨 해시로 가짜 군 배정, 기대 Δ≈0).

사용 (backend 디렉터리에서):
    .venv/bin/python scripts/pilot_eval.py [--config cfg.json] [--aa] [--out path]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import af_level_metrics as AL  # noqa: E402  (판 재구성 재사용)

PILOT_DIR = BACKEND / "data/pv_sandbox/pv_20261002_live3/dda_sets_v2/pilot_export"
DEFAULT = {
    "arm_param": "pilot_arm",                 # level_start payload key carrying the arm
    "arm_values": {"control": "control", "variant": "variant"},
    "token_param": "pilot_token",             # optional: exposed token echoed by the client (checked if present)
    "start": None, "end": None,               # pilot window "YYYY-MM-DD HH:MM:SS" (Event Time, UTC as in AF export)
    "versions": None,                         # [["android","1.1.x"], ...]; None = every version
    "af_data_dir": str(AL.AF_DATA),
    "preregistration": str(PILOT_DIR / "preregistration.json"),
    "levels_file": str(PILOT_DIR / "pilot_levels.json"),
    "return_window_h": [24, 48],              # 24h return = any level_start in (t0+24h, t0+48h]
    "next_level_window_h": 24,
    "guard_opposite_pp": 0.05, "guard_retention_pp": 0.03, "guard_z": 2.0, "guard_direction_min": 0.5,
}


class _Any:
    def __contains__(self, _):
        return True


def load_cfg(path):
    cfg = dict(DEFAULT)
    if path:
        cfg.update(json.load(open(path, encoding="utf-8")))
    return cfg


def load_runs(cfg, aa=False):
    """Events → runs with an arm label (from the level_start payload, or a fake A/A label with --aa)."""
    arm_key, tok_key = cfg["arm_param"], cfg["token_param"]
    AL.KEEP_KEYS = tuple(dict.fromkeys(AL.KEEP_KEYS + (arm_key, tok_key)))
    if cfg["versions"] is not None:
        AL.RUN_VERSIONS = {tuple(v) for v in cfg["versions"]}
    elif not aa:  # A/A keeps af_level_metrics' run-reconstructable versions
        AL.RUN_VERSIONS = _Any()
    orig_new_run = AL._new_run

    def new_run(dev, d, t, plat, ver):
        r = orig_new_run(dev, d, t, plat, ver)
        r["arm"] = d.get(arm_key)
        r["tok"] = d.get(tok_key)
        return r
    AL._new_run = new_run
    per_dev, meta = AL.load_events(Path(cfg["af_data_dir"]))
    runs, _, _, _ = AL.build_runs(per_dev)
    del per_dev
    AL.mark_first_try(runs)
    runs = [r for r in runs if not r["infinite"] and 1 <= r["L"] <= AL.MAX_LEVEL]
    if aa:
        for r in runs:
            h = int(hashlib.sha1(f"{r['dev']}|{r['L']}".encode()).hexdigest()[:8], 16)
            r["arm"] = cfg["arm_values"]["variant" if h % 2 else "control"]
    return runs, meta


def rate_block(rs):
    clean = [r for r in rs if r["first_try"] and r["oc"] in ("clear", "final_fail") and not r["helped"]]
    k = sum(1 for r in clean if r["oc"] == "clear")
    n = len(clean)
    ft = [r for r in rs if r["first_try"] and r["oc"] != "censored"]
    return {"n": n, "k": k, "rate": k / n if n else None, "wilson95": list(AL.wilson(k, n)) if n else None,
            "ftRuns": len(ft), "noEndRate": sum(1 for r in ft if r["oc"] == "no_end") / len(ft) if ft else None}


def logit_cc(k, n):
    p = (k + 0.5) / (n + 1)
    return math.log(p / (1 - p)), 1 / ((n + 1) * p * (1 - p))


def diff(a, b):
    """a − b for two proportions dicts {k, n}."""
    if not a["n"] or not b["n"]:
        return None
    pa, pb = a["k"] / a["n"], b["k"] / b["n"]
    se = math.sqrt(max(pa * (1 - pa) / a["n"] + pb * (1 - pb) / b["n"], 1e-12))
    return {"delta": pa - pb, "se": se, "z": (pa - pb) / se}


def device_index(runs):
    starts = defaultdict(list)
    for r in runs:
        starts[r["dev"]].append((r["t0"], r["L"]))
    for v in starts.values():
        v.sort()
    return starts


def guard_rates(rs, starts, cfg):
    """24h return and next-level entry for first-try runs of the level (one per device)."""
    lo, hi = cfg["return_window_h"]
    nl = cfg["next_level_window_h"]
    ret = nxt = tot = 0
    for r in rs:
        if not r["first_try"]:
            continue
        t0 = datetime.strptime(r["t0"], "%Y-%m-%d %H:%M:%S")
        a, b, c = (t0 + timedelta(hours=lo)).strftime("%Y-%m-%d %H:%M:%S"), (t0 + timedelta(hours=hi)).strftime(
            "%Y-%m-%d %H:%M:%S"), (t0 + timedelta(hours=nl)).strftime("%Y-%m-%d %H:%M:%S")
        ev = starts[r["dev"]]
        tot += 1
        ret += any(a < t <= b for t, _ in ev)
        nxt += any(r["t0"] < t <= c and L == r["L"] + 1 for t, L in ev)
    return {"n": tot, "return24h": {"k": ret, "n": tot}, "nextLevel": {"k": nxt, "n": tot}}


def wls(xs, ys, ws, intercept):
    if len(xs) < 2:
        return None
    if not intercept:
        sxx = sum(w * x * x for x, w in zip(xs, ws))
        if sxx <= 0:
            return None
        b = sum(w * x * y for x, y, w in zip(xs, ys, ws)) / sxx
        return {"slope": b, "se": math.sqrt(1 / sxx), "ci95": [b - 1.96 / math.sqrt(sxx), b + 1.96 / math.sqrt(sxx)]}
    sw = sum(ws)
    mx = sum(w * x for x, w in zip(xs, ws)) / sw
    my = sum(w * y for y, w in zip(ys, ws)) / sw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    if sxx <= 0:
        return None
    b = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws)) / sxx
    se = math.sqrt(1 / sxx)
    return {"slope": b, "intercept": my - b * mx, "se": se, "ci95": [b - 1.96 * se, b + 1.96 * se]}


def evaluate(runs, cfg):
    pre = json.load(open(cfg["preregistration"], encoding="utf-8"))
    plan = {x["level"]: x for x in pre["levels"]}
    av = cfg["arm_values"]
    t_lo, t_hi = cfg["start"], cfg["end"]
    sel = [r for r in runs if r["L"] in plan and r.get("arm") in av.values()
           and (t_lo is None or r["t0"] >= t_lo) and (t_hi is None or r["t0"] <= t_hi)]
    starts = device_index(runs)
    by = defaultdict(lambda: defaultdict(list))
    for r in sel:
        by[r["L"]][r["arm"]].append(r)
    levels, pooled_x, pooled_w = {}, [], []
    reg = {"v1": ([], [], []), "v2": ([], [], [])}
    flags = []
    for L, p in sorted(plan.items()):
        c, v = rate_block(by[L][av["control"]]), rate_block(by[L][av["variant"]])
        sign = 1 if p["expose"] == "e2" else -1
        d = diff(v, c)
        gc, gv = guard_rates(by[L][av["control"]], starts, cfg), guard_rates(by[L][av["variant"]], starts, cfg)
        g = {"return24h": diff(gv["return24h"], gc["return24h"]), "nextLevel": diff(gv["nextLevel"], gc["nextLevel"]),
             "noEnd": (v["noEndRate"] - c["noEndRate"]) if v["noEndRate"] is not None and c["noEndRate"] is not None else None}
        tok_mismatch = sum(1 for r in by[L][av["variant"]] if r.get("tok") not in (None, "", p["token"]))
        out = {"expose": p["expose"], "token": p["token"], "v2Tag": p["v2Tag"], "control": c, "variant": v, "userDelta": d,
               "guard": g, "variantTokenMismatchRuns": tok_mismatch}
        if d:
            out["intendedDirectionDelta"] = sign * d["delta"]
            out["directionOk"] = sign * d["delta"] > 0
            for lab in ("v1", "v2"):
                out[f"pred_{lab}_userDelta"] = p["predictions"][lab]["userDelta"]
            pooled_x.append(sign * d["delta"])
            pooled_w.append(1 / d["se"] ** 2)
            lc, vc_ = logit_cc(c["k"], c["n"]), logit_cc(v["k"], v["n"])
            out["userLogitDelta"] = vc_[0] - lc[0]
            w = 1 / (lc[1] + vc_[1])
            for lab in ("v1", "v2"):
                xs, ys, ws = reg[lab]
                xs.append(p["predictions"][lab]["botLogitDelta"])
                ys.append(out["userLogitDelta"])
                ws.append(w)
            if sign * d["delta"] < -cfg["guard_opposite_pp"] and -sign * d["z"] > cfg["guard_z"]:
                flags.append({"level": L, "rule": "opposite direction > guard_opposite_pp (one-sided z)", "delta": d["delta"]})
        for gk in ("return24h", "nextLevel"):
            x = g[gk]
            if x and x["delta"] < -cfg["guard_retention_pp"] and x["z"] < -cfg["guard_z"]:
                flags.append({"level": L, "rule": f"{gk} drop > guard_retention_pp (z)", "delta": x["delta"]})
        levels[str(L)] = out
    res = {"levels": levels}
    if pooled_x:
        sw = sum(pooled_w)
        m = sum(x * w for x, w in zip(pooled_x, pooled_w)) / sw
        share = sum(1 for x in pooled_x if x > 0) / len(pooled_x)
        res["pooled"] = {"levelsWithData": len(pooled_x), "intendedDirectionDelta": m, "se": math.sqrt(1 / sw),
                         "directionOkShare": share}
        if share < cfg["guard_direction_min"]:
            flags.append({"level": "all", "rule": "direction agreement < guard_direction_min (design review)", "share": share})
    res["logitSlope"] = {lab: {"throughOrigin": wls(*reg[lab], intercept=False), "withIntercept": wls(*reg[lab], intercept=True)}
                         for lab in ("v1", "v2")}
    dis = [(levels[str(L)], plan[L]) for L in plan if plan[L]["v2Tag"].startswith("disagree") and levels[str(L)].get("userDelta")]
    if dis:
        e = {lab: sum((o["userDelta"]["delta"] - p["predictions"][lab]["userDelta"]) ** 2 / o["userDelta"]["se"] ** 2
                      for o, p in dis) for lab in ("v1", "v2")}
        gap = [(p["predictions"]["v1"]["userDelta"] - p["predictions"]["v2"]["userDelta"],
                o["userDelta"]["delta"] - p["predictions"]["v2"]["userDelta"], o["userDelta"]["se"]) for o, p in dis]
        # projection of observed onto the v1−v2 gap: 0 = v2, 1 = v1
        num = sum(g * y / s ** 2 for g, y, s in gap)
        den = sum(g * g / s ** 2 for g, _, s in gap)
        res["v1VsV2"] = {"levels": len(dis), "chi2_v1": e["v1"], "chi2_v2": e["v2"], "closer": "v1" if e["v1"] < e["v2"] else "v2",
                         "lambda": num / den if den else None, "lambdaSe": math.sqrt(1 / den) if den else None,
                         "note": "lambda = observed position on the v2→v1 prediction gap (0 = v2, 1 = v1)"}
    h2 = [(o["guard"]["return24h"]) for o in levels.values() if o["expose"] == "h2" and o["guard"]["return24h"]]
    if h2:
        w = [1 / x["se"] ** 2 for x in h2]
        mh = sum(x["delta"] * wi for x, wi in zip(h2, w)) / sum(w)
        seh = math.sqrt(1 / sum(w))
        res["h2Return24hPooled"] = {"delta": mh, "se": seh, "z": mh / seh}
        if mh < -cfg["guard_retention_pp"] and mh / seh < -cfg["guard_z"]:
            flags.append({"level": "h2-all", "rule": "pooled h2 24h return drop → stop all h2 exposure", "delta": mh})
    res["guardFlags"] = flags
    res["runsInPilot"] = len(sel)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--aa", action="store_true", help="A/A dry run on current data (fake arm by device×level hash)")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    runs, meta = load_runs(cfg, aa=a.aa)
    res = evaluate(runs, cfg)
    res["config"] = cfg
    res["mode"] = "A/A dry run (no real arms — expected Δ≈0)" if a.aa else "pilot"
    res["eventRange"] = [meta["min_time"], meta["max_time"]]
    out = Path(a.out) if a.out else PILOT_DIR / "eval" / ("report_aa.json" if a.aa else "report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res.get(k) for k in ("mode", "runsInPilot", "pooled", "logitSlope", "v1VsV2", "h2Return24hPooled", "guardFlags")},
                     ensure_ascii=False, default=str)[:3000])
    print("wrote", out)


if __name__ == "__main__":
    main()
