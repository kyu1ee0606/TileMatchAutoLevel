"""v2.4 최종 검증 — 목표 지표 E1 결과(bot_v24_target_eval.py 출력)의 짝 비교 요약 (26_bot_v24.md §11).

같은 레벨·같은 폴드(4반복)이므로 봇 입력 간 차이는 반복별 짝 차이로 본다:
  - 반복 짝 차이: Δ = metric(봇, rep) − metric(기준, rep) 의 4반복 평균·sd (폴드 잡음).
  - 레벨 부트스트랩: 반복 평균 OOF 로 |오차| 짝 차이를 레벨 재추출(2000회) → 95% 구간 (레벨 표본 잡음).
  - 기믹·구간별 MAE·편향 차이, 선별 재현(replay_reps) 차이.
같은 379레벨 AF 를 반복 사용한 결과이므로 독립 검증이 아니다.

  analysis_venv/bin/python backend/scripts/bot_v24_target_paired.py --name ftany2 --ref v23
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json

import numpy as np
from scipy.stats import spearmanr

import bot_v24_target_eval as te  # 같은 tme/set_target/GIMS

tme, rm = te.tme, te.rm


def rep_metrics(y, oof, mask=None):
    return [tme.metrics_for(y, np.asarray(o), mask) for o in oof]


def paired(y, oof_b, oof_r, mask=None):
    mb, mr = rep_metrics(y, oof_b, mask), rep_metrics(y, oof_r, mask)
    if mb[0] is None:
        return None
    out = {"n": mb[0]["n"]}
    for k in ("mae", "bias", "rho", "hit05", "hit10"):
        d = [b[k] - r[k] for b, r in zip(mb, mr)]
        out[k] = round(float(np.mean([b[k] for b in mb])), 4)
        out["d_" + k] = round(float(np.mean(d)), 4)
        out["sd_d_" + k] = round(float(np.std(d)), 4)
    return out


def level_boot(y, oof_b, oof_r, mask=None, B=2000, seed=11):
    pb, pr = np.mean(oof_b, axis=0), np.mean(oof_r, axis=0)
    if mask is not None:
        y, pb, pr = y[mask], pb[mask], pr[mask]
    dl = np.abs(pb - y) - np.abs(pr - y)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(y), size=(B, len(y)))
    dm = dl[idx].mean(axis=1)
    drho = []
    for i in idx[:500]:
        drho.append(spearmanr(pb[i], y[i])[0] - spearmanr(pr[i], y[i])[0])
    return {"d_mae": round(float(dl.mean()), 4), "ci_mae": [round(float(x), 4) for x in np.percentile(dm, [2.5, 97.5])],
            "ci_rho": [round(float(x), 4) for x in np.percentile(drho, [2.5, 97.5])]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--ref", default="v23")
    a = ap.parse_args()
    res = json.load(open(te.OUT / f"{a.name}.json", encoding="utf-8"))
    LM = {r["level"]: r for r in json.load(open(rm.CAL / "level_metrics.json", encoding="utf-8"))["levels"]}
    bots = res["meta"]["bots"]
    targets = sorted({k.split("|")[0] for k in res["results"]})
    summary = {}
    for tk in targets:
        base, _ = tme.load_base(str(rm.CAL / bots[a.ref]))
        te.set_target(base, tk, LM)
        y = np.array([r["ft_any"] for r in base])
        R = res["results"]
        ref = R[f"{tk}|{a.ref}"]
        segs = sorted({r["seg"] for r in base})
        print(f"\n## target={tk} (기준 {a.ref}, n={len(y)})")
        print("| 봇 | MAE | ΔMAE (반복sd) | 레벨부트 95% | bias | ρ | Δρ (반복sd) | 레벨부트 Δρ 95% | hit05 | Δhit05 |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for name in bots:
            e = R[f"{tk}|{name}"]
            p = paired(y, e["oof_e1"], ref["oof_e1"])
            lb = level_boot(y, e["oof_e1"], ref["oof_e1"])
            ent = {"overall": p, "boot": lb, "seg": {}, "gim": {}}
            print(f"| {name} | {p['mae']:.4f} | {p['d_mae']:+.4f} ({p['sd_d_mae']:.4f}) | [{lb['ci_mae'][0]:+.4f}, {lb['ci_mae'][1]:+.4f}] | "
                  f"{p['bias']:+.4f} | {p['rho']:.3f} | {p['d_rho']:+.3f} ({p['sd_d_rho']:.3f}) | "
                  f"[{lb['ci_rho'][0]:+.3f}, {lb['ci_rho'][1]:+.3f}] | {p['hit05']:.3f} | {p['d_hit05']:+.3f} |")
            for s in segs:
                m = np.array([r["seg"] == s for r in base])
                ent["seg"][s] = paired(y, e["oof_e1"], ref["oof_e1"], m)
            for g in te.GIMS + ["_none"]:
                if g == "_none":
                    m = np.array([not any(r.get("has_" + x) for x in te.GIMS) for r in base])
                else:
                    m = np.array([bool(r.get("has_" + g)) for r in base])
                if m.sum() >= 5:
                    ent["gim"][g] = paired(y, e["oof_e1"], ref["oof_e1"], m)
            if "replay_reps" in e:
                ent["replay"] = {k: {"mean": v["mean"], "sd": v["sd"],
                                     "d_mean": round(v["mean"] - ref["replay_reps"][k]["mean"], 4),
                                     "sd_d": round(float(np.std(np.array(v["reps"]) - np.array(ref["replay_reps"][k]["reps"]))), 4)}
                                 for k, v in e["replay_reps"].items()}
            summary[f"{tk}|{name}"] = ent
        print(f"\n### 구간별 MAE (Δ vs {a.ref}) — target={tk}")
        print("| 봇 | " + " | ".join(segs) + " |")
        print("|---|" + "---|" * len(segs))
        for name in bots:
            sg = summary[f"{tk}|{name}"]["seg"]
            print(f"| {name} | " + " | ".join(f"{sg[s]['mae']:.4f} ({sg[s]['d_mae']:+.4f}) ρ{sg[s]['rho']:.2f}" if sg.get(s) else "-" for s in segs) + " |")
        gl = list(summary[f"{tk}|{a.ref}"]["gim"])
        print(f"\n### 기믹별 MAE·bias (Δ vs {a.ref}) — target={tk}")
        print("| 봇 | " + " | ".join(f"{g}(n={summary[f'{tk}|{a.ref}']['gim'][g]['n']})" for g in gl) + " |")
        print("|---|" + "---|" * len(gl))
        for name in bots:
            gg = summary[f"{tk}|{name}"]["gim"]
            print(f"| {name} | " + " | ".join(f"{gg[g]['mae']:.4f} ({gg[g]['d_mae']:+.4f}) b{gg[g]['bias']:+.3f}" for g in gl) + " |")
        if "replay" in summary[f"{tk}|{a.ref}"]:
            ks = list(summary[f"{tk}|{a.ref}"]["replay"])
            print(f"\n### 선별 재현 (후보 20, 3000회, 4반복 평균 (Δ vs {a.ref}, 짝 sd)) — target={tk}")
            print("| 봇 | " + " | ".join(ks) + " |")
            print("|---|" + "---|" * len(ks))
            for name in bots:
                rp = summary[f"{tk}|{name}"]["replay"]
                print(f"| {name} | " + " | ".join(f"{rp[k]['mean']:.3f} ({rp[k]['d_mean']:+.3f}±{rp[k]['sd_d']:.3f})" for k in ks) + " |")
    out = te.OUT / f"{a.name}_paired_{a.ref}.json"
    json.dump(summary, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("\nsaved", out)


if __name__ == "__main__":
    main()
