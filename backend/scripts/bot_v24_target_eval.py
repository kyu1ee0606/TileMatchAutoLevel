"""v2.4 최종 검증 — 목표 지표 E1 홀드아웃 비교 (26_bot_v24.md §11).

메인 `backend/scripts/target_metric_eval.py`(커밋 39efbe1)를 수정 없이 import 해서 같은 조건으로 돌린다:
같은 레벨 집합(봇 행 410 ∩ map_match=same ∩ 레거시값, n=379) · 같은 목표(⑤ ft_clear_rate_any_help) ·
맵해시 그룹 5겹×4반복(같은 폴드) · 같은 특징 세트 · E1(Ridge+LGBM 단조) 재학습. 봇 입력 파일만 바꾼다.
목표 변형(--targets): ft_any(기본) / mid / lb / ub (unaided 무도움 중간값·하한·상한) — 결론 견고성 확인용.
출력: data/pv_sandbox/af_calibration/bot_v24/target/<name>.json (메인 target_metric/ 결과 파일은 건드리지 않음).

  analysis_venv/bin/python backend/scripts/bot_v24_target_eval.py --bots v23=bot_v23/bot_v2.3.json,v24=bot_v24/bot_v2.4f.json ...
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import residual_model as rm  # noqa: E402  (이 브랜치 판: RM_EXTRA_FEATS 미설정이면 기본 특징 = 메인과 동일)
import residual_model_lib as lib  # noqa: E402

MAIN_TME = Path("/Users/casualdev/TileMatchAutoLevel/backend/scripts/target_metric_eval.py")
spec = importlib.util.spec_from_file_location("target_metric_eval", MAIN_TME)
tme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tme)          # sys.modules 의 rm/lib 를 재사용(같은 이름) → 이 브랜치 판으로 동작

OUT = rm.CAL / "bot_v24" / "target"
OUT.mkdir(parents=True, exist_ok=True)
GIMS = ["stack", "craft", "bomb", "grass", "chain", "ice", "curtain", "teleporter", "frog", "unknown", "link"]


def set_target(base, kind, LM):
    for r in base:
        m = LM[r["L"]]
        lb, ub = m.get("unaided_clear_lower_bound"), m.get("unaided_clear_upper_bound")
        if kind == "mid":
            r["ft_any"] = (lb + ub) / 2
        elif kind == "lb":
            r["ft_any"] = lb
        elif kind == "ub":
            r["ft_any"] = ub
    return base


def gim_metrics(base, y_true, oof_d, reps):
    out = {}
    for g in GIMS + ["_none"]:
        if g == "_none":
            mask = np.array([not any(r.get("has_" + x) for x in GIMS) for r in base])
        else:
            mask = np.array([bool(r.get("has_" + g)) for r in base])
        if mask.sum() < 5:
            continue
        ms = [tme.metrics_for(y_true, oof_d[rep], mask) for rep in range(reps)]
        out[g] = tme.agg_reps(ms)
    return out


def replay_reps(base, y_true, oof_d, reps):
    """target_metric_eval.replay_ftany 의 nearest_D 규칙을 반복마다(rep 0..reps-1) 같은 추첨(random.seed(7),
    후보 20 × 3000회, random 규칙의 choice 까지 같은 난수 소비)으로 재현 → 반복 평균·sd (원 스크립트는 rep 0 만)."""
    import random
    # 0.85(p10, ±5%p 안 49레벨)·0.88(76레벨) = 비천장 다른 목표 구간(26 §11, 선별 견고성)
    targets = {"t0.85": 0.85, "t0.88": 0.88, "t0.92": 0.92, "t0.963": 0.963, "t0.983": 0.983}
    out = {}
    for tname, t in targets.items():
        for w in (0.05, 0.10):
            hits = []
            for rep in range(reps):
                rows = [{"actual": float(y_true[i]), "predD": float(oof_d[rep][i])} for i in range(len(base))]
                random.seed(7)
                h = 0
                for _ in range(tme.DRAWS):
                    cands = random.sample(rows, tme.N_CAND)
                    random.choice(cands)                       # 원 스크립트의 random 규칙 난수 소비
                    s_ = min(cands, key=lambda r: abs(r["predD"] - t))
                    h += (t - w <= s_["actual"] <= t + w)
                hits.append(h / tme.DRAWS)
            out[f"{tname}_pm{int(w * 100):02d}"] = {"mean": round(float(np.mean(hits)), 4), "sd": round(float(np.std(hits)), 4),
                                                    "reps": [round(x, 4) for x in hits]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", required=True, help="name=path(rel. to af_calibration),...")
    ap.add_argument("--targets", default="ft_any,mid,lb,ub")
    ap.add_argument("--name", default="compare")
    ap.add_argument("--replay", action="store_true")
    a = ap.parse_args()
    LM = {r["level"]: r for r in json.load(open(rm.CAL / "level_metrics.json", encoding="utf-8"))["levels"]}
    bots = dict(x.split("=", 1) for x in a.bots.split(","))
    res = {"meta": {"bots": bots, "reps": tme.REPS, "feats": len(lib.FEATS),
                    "extra_feats": os.environ.get("RM_EXTRA_FEATS", ""),
                    "script": "target_metric_eval.py@39efbe1 (import, unmodified)"}, "results": {}}
    levels_ref = None
    for tk in a.targets.split(","):
        for name, path in bots.items():
            base, Xb = tme.load_base(str(rm.CAL / path))
            Ls = [r["L"] for r in base]
            if levels_ref is None:
                levels_ref = Ls
            assert Ls == levels_ref, f"level set differs for {name}"
            set_target(base, tk, LM)
            y_true, oof = tme.run_eval(base, Xb, tme.REPS)
            summ = tme.summarize(base, y_true, oof, tme.REPS)
            entry = {"n": len(base), "e1": summ["overall"]["d_e1"], "seg": {s: v.get("d_e1") for s, v in summ["by_segment"].items()},
                     "baselines": {m: summ["overall"][m] for m in ("a_raw", "b_recal", "c_segmean")},
                     "gim": gim_metrics(base, y_true, oof["d_e1"], tme.REPS),
                     "oof_e1": oof["d_e1"].tolist()}
            if a.replay and tk == "ft_any":
                targets, sel = tme.replay_ftany(base, y_true, oof)
                entry["replay"] = sel
                entry["replay_reps"] = replay_reps(base, y_true, oof["d_e1"], tme.REPS)
            res["results"][f"{tk}|{name}"] = entry
            e = entry["e1"]
            tme.log(f"{tk:6s} {name:14s} n={len(base)} MAE {e['mae']:.4f}±{e['sd']['mae']:.4f} bias {e['bias']:+.4f} "
                    f"ρ {e['rho']:.3f} hit05 {e['hit05']:.3f} hit10 {e['hit10']:.3f}")
    res["meta"]["levels"] = levels_ref
    json.dump(res, open(OUT / f"{a.name}.json", "w", encoding="utf-8"), ensure_ascii=False)
    tme.log("saved", OUT / f"{a.name}.json")


if __name__ == "__main__":
    main()
