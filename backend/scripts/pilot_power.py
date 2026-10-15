"""[분석 전용, 읽기 전용] 시드 변형 파일럿(라이브 소규모 측정) 표본·검정력 계산.

산출: claudedocs/difficulty_personalization/24_live_pilot_design.md 의 근거 수치.
입력(읽기만): backend/data/pv_sandbox/af_calibration/level_metrics.json
  (backend/scripts/af_level_metrics.py 가 만든 구간별 실측 — 구간당 레벨 수·기간·clean_ft 수)

계산 2가지:
  1. 레벨 1개 판정(원맵 vs 변형 1개, 2군 비교)에 필요한 표본·도달 일수 — 효과크기 5/8/10/13%p.
  2. 풀링 회귀(여러 레벨의 봇Δ·유저Δ 쌍으로 "환산 기울기" 추정)에 필요한 레벨당 표본.
     단순회귀 기울기 분산 Var(β1) = σ²_y / Σ(x_i − x̄)² 공식 사용 (x=봇Δ, y=유저Δ, σ²_y=유저Δ 추정분산).

사용: backend/.venv/bin/python scripts/pilot_power.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
METRICS = BACKEND / "data/pv_sandbox/af_calibration/level_metrics.json"

Z_ALPHA_95 = 1.96  # alpha=0.05 two-sided
Z_POWER_80 = 0.8416  # power=0.8

SEGMENTS = ["32-100", "101-300", "301-500", "501-1000"]
EFFECT_SIZES_PP = [5, 8, 10, 13]  # percentage points


def two_prop_n_per_arm(p0: float, delta: float, z_a=Z_ALPHA_95, z_b=Z_POWER_80) -> float:
    """2군 비율차 검정, 군당 필요 n (정규근사, 등분산 가정 — 각 군 자체 분산 사용)."""
    p1 = max(0.0, min(1.0, p0 - delta))
    var = p0 * (1 - p0) + p1 * (1 - p1)
    return (z_a + z_b) ** 2 * var / delta ** 2


def load_segment_traffic():
    d = json.loads(METRICS.read_text())
    t0 = datetime.strptime(d["scope"]["event_time_range_kst"][0], "%Y-%m-%d %H:%M:%S")
    t1 = datetime.strptime(d["scope"]["event_time_range_kst"][1], "%Y-%m-%d %H:%M:%S")
    days = (t1 - t0).total_seconds() / 86400
    out = {}
    for seg in SEGMENTS:
        s = d["segments"][seg]
        n_levels = s["levels"]
        clean_ft_n = s["clean_ft_n"]
        out[seg] = {
            "n_levels": n_levels,
            "baseline_rate": s["clean_ft_rate"],
            "ci95": s["clean_ft_ci95"],
            "clean_ft_per_level_per_day": clean_ft_n / n_levels / days,
        }
    return out, days


def section1_single_level(traffic: dict):
    """레벨 1개(원맵 vs 변형 1개, 50:50) 판정 — 필요 표본·도달 일수."""
    print("## 1. 레벨 1개 판정(원맵 vs 변형 1개, 트래픽 50:50) — α=0.05, 검정력=0.8\n")
    print("| 구간 | 기준 클리어율 | 일일 레벨당 첫시도(무도움) 유저 | 효과크기(pp) | 군당 필요 n | 양군 합 | 도달일수 |")
    print("|---|---|---|---|---|---|---|")
    for seg in SEGMENTS:
        t = traffic[seg]
        p0 = t["baseline_rate"]
        daily = t["clean_ft_per_level_per_day"]
        for d_pp in EFFECT_SIZES_PP:
            delta = d_pp / 100
            n = two_prop_n_per_arm(p0, delta)
            total = 2 * n
            days_needed = total / daily if daily > 0 else float("inf")
            print(f"| {seg} | {p0:.3f} | {daily:.2f} | {d_pp} | {n:.0f} | {total:.0f} | {days_needed:,.0f} |")
    print()


def section2_pooled_regression(traffic: dict):
    """풀링 회귀(봇Δ→유저Δ 환산 기울기) — 레벨당 n(군당, 50:50) 가정별 기울기 표준오차.

    가정: 파일럿 레벨들의 봇Δ(x) 분산은 §9-4/§10 실측 범위(바깥 칸 |Δ|≥0.13, 중앙값 0.16~0.20,
    선택 편향으로 재측정 시 축소 가능)를 참고해 sd(x) = 0.05 / 0.08 / 0.10 3가지로 스캔.
    각 레벨 유저Δ 추정 분산 = 2*p0*(1-p0)/n (군당 n 동일 가정, p0 = 구간 평균 기준 클리어율).
    단순회귀: Var(slope) = var(y) / (num_levels * sd(x)^2).
    """
    print("## 2. 풀링 회귀(여러 레벨 봇Δ↔유저Δ, 환산 기울기 slope 추정)\n")
    print("가정: slope 추정 표준오차 SE(β1). 판정 기준 예시 — slope=0.5를 0과 구별(검정력 0.8, α=0.05)하려면 "
          "SE(β1) ≤ 0.5/(1.96+0.8416) ≈ 0.179 필요. slope=1.0 구별이면 SE(β1) ≤ 0.357.\n")
    p0_avg = sum(traffic[s]["baseline_rate"] for s in SEGMENTS) / len(SEGMENTS)
    print(f"(기준 클리어율은 4구간 평균 {p0_avg:.3f} 사용 — 실제 파일럿 레벨 구성에 따라 조정 필요)\n")
    print("| 레벨 수 | 봇Δ 표준편차 가정 | 레벨당 군당 n | SE(slope) | slope=0.5 구별? | slope=1.0 구별? |")
    print("|---|---|---|---|---|---|")
    for num_levels in (20, 25, 30):
        for sd_x in (0.05, 0.08, 0.10):
            for n_per_arm in (50, 100, 200, 400, 800):
                var_y = 2 * p0_avg * (1 - p0_avg) / n_per_arm
                se_slope = (var_y / (num_levels * sd_x ** 2)) ** 0.5
                ok_05 = "O" if se_slope <= 0.5 / 2.8016 else "x"
                ok_10 = "O" if se_slope <= 1.0 / 2.8016 else "x"
                print(f"| {num_levels} | {sd_x:.2f} | {n_per_arm} | {se_slope:.3f} | {ok_05} | {ok_10} |")
    print()


def section3_days_for_pooled(traffic: dict):
    """§2 의 레벨당 군당 n을 구간별 트래픽으로 도달하는 일수 (레벨이 그 구간에 있다고 가정)."""
    print("## 3. 풀링 목표 n(군당)을 구간별 트래픽으로 도달하는 일수 (레벨 1개, 50:50 가정)\n")
    print("| 구간 | 일일 레벨당 첫시도 유저 | 군당 n=50 | n=100 | n=200 | n=400 |")
    print("|---|---|---|---|---|---|")
    for seg in SEGMENTS:
        daily = traffic[seg]["clean_ft_per_level_per_day"]
        cells = []
        for n_per_arm in (50, 100, 200, 400):
            total = 2 * n_per_arm
            days_needed = total / daily if daily > 0 else float("inf")
            cells.append(f"{days_needed:,.0f}")
        print(f"| {seg} | {daily:.2f} | " + " | ".join(cells) + " |")
    print()


def main():
    traffic, days = load_segment_traffic()
    print(f"(데이터 기간 {days:.1f}일 기준 — backend/data/pv_sandbox/af_calibration/level_metrics.json)\n")
    section1_single_level(traffic)
    section2_pooled_regression(traffic)
    section3_days_for_pooled(traffic)


if __name__ == "__main__":
    main()
