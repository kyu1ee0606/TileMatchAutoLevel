"""레벨 클리어율 분포 비교 — 실제 AF(ft_any) vs 기존 predicted_clear_rate vs 개선 모델(E1, v2.3/v2.4규칙만 입력) 비교.
새 봇 측정 없음 — target_metric_eval.py(379레벨 379·5겹×4반복 OOF)를 import 재사용하고,
E1 예측은 이미 생성된 bot_v24/target/ftany2.json 의 oof_e1(v23·rules_only)을 4반복 평균해 쓴다.
문서 34(claudedocs/difficulty_personalization/34_clear_rate_distribution.md) 원자료.

  analysis_venv/bin/python backend/scripts/clear_rate_distribution.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import target_metric_eval as tme  # noqa: E402

CAL = tme.CAL
FTANY2 = CAL / "bot_v24/target/ftany2.json"
LEGACY_BATCH = tme.LEGACY_BATCH

QS = [5, 10, 25, 50, 75, 90, 95]
BUCKETS = [(-np.inf, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 0.92), (0.92, 0.96), (0.96, np.inf)]
BUCKET_LABELS = ["<0.5", "0.5-0.7", "0.7-0.85", "0.85-0.92", "0.92-0.96", ">=0.96"]


def bucket_table(x):
    x = np.asarray(x)
    return [float(((x >= lo) & (x < hi)).mean()) for lo, hi in BUCKETS]


def summary(x):
    x = np.asarray(x)
    q = np.percentile(x, QS)
    out = {"n": len(x), "mean": float(x.mean()), "sd": float(x.std())}
    out.update({f"p{p}": float(v) for p, v in zip(QS, q)})
    out["buckets"] = bucket_table(x)
    return out


def hist(x, width=0.05, lo=0.0, hi=1.0):
    x = np.asarray(x)
    edges = np.arange(lo, hi + width / 2, width)
    counts, _ = np.histogram(x, bins=edges)
    return edges, counts


def main():
    base, _Xb = tme.load_base()  # v2.3 봇 입력, n=379 (문서 31 §1-5 379레벨)
    L = [r["L"] for r in base]
    seg = [r["seg"] for r in base]
    actual = np.array([r["ft_any"] for r in base])
    legacy = np.array([r["legacy_pred"] for r in base])

    d = json.load(open(FTANY2, encoding="utf-8"))
    assert d["meta"]["levels"] == L, "level order mismatch — ftany2.json vs load_base()"
    e1_v23 = np.array(d["results"]["ft_any|v23"]["oof_e1"]).mean(axis=0)
    e1_rules = np.array(d["results"]["ft_any|rules_only"]["oof_e1"]).mean(axis=0)

    dists = {"actual(ft_any)": actual, "legacy_pred": legacy,
              "E1(v2.3입력)": e1_v23, "E1(v2.4규칙만입력)": e1_rules}

    print(f"n={len(base)}\n")
    print("## 1) 전체 분포 (분위수·평균·sd)")
    print("| 분포 | n | mean | sd | " + " | ".join(f"p{p}" for p in QS) + " |")
    print("|---" * (len(QS) + 4) + "|")
    for name, x in dists.items():
        s = summary(x)
        print(f"| {name} | {s['n']} | {s['mean']:.4f} | {s['sd']:.4f} | "
              + " | ".join(f"{s[f'p{p}']:.4f}" for p in QS) + " |")

    print("\n## 2) 구간별 비율")
    print("| 분포 | " + " | ".join(BUCKET_LABELS) + " |")
    print("|---" * (len(BUCKET_LABELS) + 1) + "|")
    for name, x in dists.items():
        b = bucket_table(x)
        print(f"| {name} | " + " | ".join(f"{v:.3f}" for v in b) + " |")

    print("\n## 3) 레벨 구간별(32-100/101-300/301-500) 중앙값·p10·p90")
    for s in ("32-100", "101-300", "301-500"):
        mask = np.array([sg == s for sg in seg])
        print(f"\n### seg={s} (n={int(mask.sum())})")
        for name, x in dists.items():
            xs = x[mask]
            if len(xs) == 0:
                continue
            print(f"  {name}: median={np.median(xs):.4f} p10={np.percentile(xs, 10):.4f} p90={np.percentile(xs, 90):.4f}")

    print("\n## 4) 텍스트 히스토그램 (폭 0.05)")
    edges, _ = hist(actual)
    names = list(dists.keys())
    counts_by = {name: hist(x)[1] for name, x in dists.items()}
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        row = f"{lo:.2f}-{hi:.2f} | " + " | ".join(f"{names[j][:4]}:{counts_by[names[j]][i]:3d}" for j in range(len(names)))
        print(row)

    print("\n## 5) 실제 ft_any < 0.85 인 레벨에서 E1 예측 분포")
    mask = actual < 0.85
    print(f"n={int(mask.sum())}")
    for name, x in [("actual", actual), ("legacy", legacy), ("E1(v2.3)", e1_v23), ("E1(v2.4규칙만)", e1_rules)]:
        xs = x[mask]
        print(f"  {name}: mean={xs.mean():.4f} sd={xs.std():.4f} median={np.median(xs):.4f} p90={np.percentile(xs, 90):.4f}")

    print("\n## 6) 참고: 1~1500 전체 레벨 기존 predicted_clear_rate vs AF 실측(측정 있는 레벨) 분포")
    leg_all = json.load(open(LEGACY_BATCH, encoding="utf-8"))
    pcr_all = np.array([lv["meta"]["predicted_clear_rate"] for lv in leg_all["levels"]
                         if lv["meta"]["level_number"] <= 1500 and lv["meta"].get("predicted_clear_rate")])
    LM = json.load(open(CAL / "level_metrics.json", encoding="utf-8"))["levels"]
    af_all = np.array([r["ft_clear_rate_any_help"] for r in LM
                        if r.get("map_match") == "same" and (r.get("first_try_ended") or 0) >= 100
                        and r.get("ft_clear_rate_any_help") is not None])
    print("| 분포 | n | mean | sd | p10 | p50 | p90 |")
    print("|---|---|---|---|---|---|---|")
    for name, x in [("legacy_pred(1~1500)", pcr_all), ("AF실측(측정있는레벨)", af_all)]:
        s = summary(x)
        print(f"| {name} | {s['n']} | {s['mean']:.4f} | {s['sd']:.4f} | {s['p10']:.4f} | {s['p50']:.4f} | {s['p90']:.4f} |")


if __name__ == "__main__":
    main()
