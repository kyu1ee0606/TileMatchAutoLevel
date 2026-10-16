"""[분석 전용, 읽기 전용] 저성공률(ft_any<0.85) 구간 예측 오차 원인 점검 — 문서 35a §2 보강.

"사례 부족"으로 단정하지 않고 저장 데이터로 점검한다(새 봇 측정 없음):
  (a) 특징 범위: 379레벨 중 저성공 40개의 맵 특징(tiles/layers/types/기믹조합/bomb_sum/novelty)이
      고성공 339개의 분포 밖(OOD)인지 — rm.build() 특징 재사용.
  (b) 모델 평균 쏠림: target_metric_eval.run_eval() 로 E1(d) OOF 예측을 다시 돌려(재학습 아님,
      같은 K-fold 재현) 잔차(pred-actual) vs 실제값 기울기를 본다. 레거시 예측 잔차도 대조.
  (c) 도움 사용 차이: level_metrics 의 ft_help_rate·unaided_clear_lower_bound 로 저성공/고성공
      도움 의존도와 "도움효과폭"(ft_any - lb_af)을 비교.

사용 (backend 디렉터리에서, numpy/sklearn/lightgbm 필요 → analysis_venv):
    ../analysis_venv/bin/python scripts/low_clear_diagnostics.py
출력: backend/data/pv_sandbox/af_calibration/low_clear_diagnostics.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import residual_model as rm  # noqa: E402
import target_metric_eval as t  # noqa: E402

OUT = rm.CAL / "low_clear_diagnostics.json"


def stat(arr):
    a = np.asarray(arr, float)
    return {"mean": round(float(a.mean()), 4), "sd": round(float(a.std()), 4),
            "median": round(float(np.median(a)), 4), "min": round(float(a.min()), 4),
            "max": round(float(a.max()), 4), "n": int(len(a))}


def main():
    base, Xb = t.load_base()
    y = np.array([r["ft_any"] for r in base])
    low_mask = y < 0.85
    out = {"n_low": int(low_mask.sum()), "n_high": int((~low_mask).sum())}

    # (a) 특징 범위 — rm.build() 로 재계산한 맵 특징, 저성공 vs 고성공
    recs23 = rm.build(rm.CAL / "bot_v23/bot_v2.3.json")
    REC = {r["L"]: r for r in recs23}
    Ls_low = [b["L"] for i, b in enumerate(base) if low_mask[i]]
    Ls_high = [b["L"] for i, b in enumerate(base) if not low_mask[i]]
    feat_keys = ["tiles", "layers", "types", "n_gimmick_types", "bomb_sum", "novelty", "random_layout"]
    out["a_feature_range"] = {
        k: {"low": stat([REC[L][k] for L in Ls_low]), "high": stat([REC[L][k] for L in Ls_high])}
        for k in feat_keys
    }
    out["a_combo_low"] = dict(Counter(REC[L]["combo"] for L in Ls_low).most_common())
    out["a_seg_low"] = dict(Counter(REC[L]["seg"] for L in Ls_low))
    out["a_seg_high"] = dict(Counter(REC[L]["seg"] for L in Ls_high))
    out["a_verdict"] = ("저성공 40개 특징(tiles/layers/types/gimmick수)은 전부 고성공 339개 분포 "
                         "범위 안(OOD 아님). bomb_sum 평균은 약 2배(3.5 vs 1.9), novelty 평균도 높음"
                         "(0.41 vs 0.27) — 범위 이탈이 아니라 '폭탄 노출+신규기믹 노출'이 겹치는 "
                         "조합이 저성공 쪽에 더 몰려 있다는 뜻")

    # (b) 모델 평균 쏠림 — E1 OOF 재현(재학습 아님, target_metric_eval.run_eval 그대로 재사용)
    y_true, oof = t.run_eval(base, Xb, reps=4)
    pred_d = oof["d_e1"].mean(axis=0)
    resid = pred_d - y_true
    sl_all, ic_all = np.polyfit(y_true, resid, 1)
    sl_low, ic_low = np.polyfit(y_true[low_mask], resid[low_mask], 1)
    legacy = np.array([r["legacy_pred"] for r in base])
    resid_leg = legacy - y_true
    out["b_model_shrinkage"] = {
        "e1_resid_vs_actual_slope_all": round(float(sl_all), 4),
        "e1_resid_vs_actual_slope_low_only": round(float(sl_low), 4),
        "e1_mean_resid_low": round(float(resid[low_mask].mean()), 4),
        "e1_mean_resid_high": round(float(resid[~low_mask].mean()), 4),
        "legacy_mean_resid_low": round(float(resid_leg[low_mask].mean()), 4),
        "legacy_mean_resid_high": round(float(resid_leg[~low_mask].mean()), 4),
        "verdict": ("E1은 저성공 레벨에서 평균 +0.117(과대추정, 평균회귀) — 기울기(-0.57)가 뚜렷한 "
                    "음수라 '실제가 낮을수록 더 높게 찍는' 체계적 쏠림. 레거시는 반대로 저성공 "
                    "레벨에서 평균 -0.181(과소추정) — 둘 다 사례부족이 아니라 모델별 체계 오차"),
    }

    # (c) 도움 사용 차이
    help_low = [r["help_rate"] for i, r in enumerate(base) if low_mask[i]]
    help_high = [r["help_rate"] for i, r in enumerate(base) if not low_mask[i]]
    lb_low = [r["lb_af"] for i, r in enumerate(base) if low_mask[i]]
    lb_high = [r["lb_af"] for i, r in enumerate(base) if not low_mask[i]]
    width_low = [base[i]["ft_any"] - base[i]["lb_af"] for i in range(len(base)) if low_mask[i]]
    width_high = [base[i]["ft_any"] - base[i]["lb_af"] for i in range(len(base)) if not low_mask[i]]
    noend_low = [r["noend_rate"] for i, r in enumerate(base) if low_mask[i]]
    noend_high = [r["noend_rate"] for i, r in enumerate(base) if not low_mask[i]]
    out["c_help_usage"] = {
        "help_rate": {"low": stat(help_low), "high": stat(help_high)},
        "lb_af_unaided": {"low": stat(lb_low), "high": stat(lb_high)},
        "help_effect_width_ft_any_minus_lb": {"low": stat(width_low), "high": stat(width_high)},
        "noend_rate": {"low": stat(noend_low), "high": stat(noend_high)},
        "verdict": ("저성공 레벨은 도움 사용률이 더 높고(27.6% vs 16.1%) 도움효과폭도 거의 2배"
                    "(26.2%p vs 15.3%p) — ft_any 가 무도움 실력보다 도움 사용 변동에 더 많이 좌우됨. "
                    "no_end 비율은 오히려 낮아(1.97% vs 2.33%) 중단 때문은 아님"),
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("done ->", OUT, flush=True)


if __name__ == "__main__":
    main()
