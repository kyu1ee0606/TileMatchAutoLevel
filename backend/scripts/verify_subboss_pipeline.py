"""[내부 검증] 등껍질 바닥 라이브러리(7x7/8x8) + 기믹 언락 강제 전수 확인.

검증 3축:
  A. 라이브러리 무결성 — 28종 전부 생성 가능 · 격자/÷3/floating/언락 위반 0
  B. 언락 강제 방어선  — 미해금 기믹을 일부러 넘겨도 생성물에 안 들어가는가
  C. 서브보스 배정     — 149레벨 전수 시뮬 + 표본 실생성으로 위반/난이도/다양성
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.api.routes.production_store import _scan_rule_violations  # noqa: E402
from app.core import level_shapes as LS  # noqa: E402
from app.core import turtle_bases as TB  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import LevelGenerator  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402
from apply_subboss_turtle import ATTR_POOL, MARGIN, approx_use_tile_count  # noqa: E402
from verify_turtle_integration import div3_bad, floating_count  # noqa: E402

SUB_LEVELS = [n for n in range(15, 1500, 10) if n % 10 == 5]


def pool() -> List[Dict[str, Any]]:
    return [b for b in TB.list_bases(enabled_only=True, with_shape=False)
            if (b.get("difficulty") or {}).get("coef") is not None]


def pick_k(n: int) -> int:
    return max(10, round(n / 3))


def pick(ln: int, td: float, p: List[Dict[str, Any]]) -> str:
    v = approx_use_tile_count(ln)
    want = min(0.98, max(0.15, 1.05 - td) - 0.10 + MARGIN)
    sc = []
    for b in p:
        byv = b["difficulty"]["by_v"]
        ks = sorted(int(x) for x in byv)
        k = min(ks, key=lambda x: abs(x - v))
        sc.append((abs(byv[str(k)]["avg"] - want), b["id"]))
    sc.sort()
    top = [i for _, i in sc[:pick_k(len(sc))]]
    return top[(ln // 10) % len(top)]


def td_of(ln: int) -> float:
    return min(0.95, 0.12 + 0.83 * (ln / 1500) ** 0.75)


def check(lj: Dict[str, Any], ln: int) -> Dict[str, Any]:
    bad: Dict[str, Any] = {}
    if not lj.get("_turtle_peel"):
        bad["no_turtle"] = True
    v = LS.assert_in_board(lj)
    if v:
        bad["board"] = v[:3]
    d3 = div3_bad(lj)
    if d3:
        bad["div3"] = d3
    f = floating_count(lj)
    if f:
        bad["float"] = f
    rv = _scan_rule_violations(lj, ln)
    if "gimmick_unlock_violation" in rv:
        bad["unlock"] = rv["gimmick_unlock_violation"]
    return bad


def main(samples: int = 40) -> None:
    P = pool()
    gen, sim = LevelGenerator(), BotSimulator()
    print(f"라이브러리 {len(P)}종  격자 {dict(Counter(b['grid'] for b in P))}  K={pick_k(len(P))}\n")

    # ── A. 라이브러리 전수: 각 바닥이 실제로 생성되는가 ──
    print("[A] 바닥 28종 전수 생성 (Lv615, 기믹 전량 해금 구간)")
    fail_a = Counter()
    for b in P:
        lj = gen.generate(GenerationParams(
            target_difficulty=0.70, level_number=615, turtle_pattern_id=b["id"],
            obstacle_types=ATTR_POOL, gimmick_intensity=1.1)).level_json
        bad = check(lj, 615)
        if bad or lj.get("_turtle_pattern_id") != b["id"]:
            fail_a[b["id"]] = bad or "id_mismatch"
    print(f"  통과 {len(P) - len(fail_a)}/{len(P)}"
          + (f"  실패 {dict(fail_a)}" if fail_a else "  실패 없음"))

    # ── B. 언락 강제: 미해금 기믹을 억지로 넘겨도 막히는가 ──
    print("\n[B] 언락 방어선 — 미해금 기믹을 강제 주입해도 배치되지 않는가")
    fail_b = []
    for ln in (15, 45, 95, 165, 205, 265, 305):
        lj = gen.generate(GenerationParams(
            target_difficulty=td_of(ln), level_number=ln, turtle_pattern_id=P[0]["id"],
            obstacle_types=ATTR_POOL,     # 필터 없이 전량 주입(호출자 실수 시나리오)
            gimmick_intensity=1.2)).level_json
        rv = _scan_rule_violations(lj, ln)
        mark = "OK" if "gimmick_unlock_violation" not in rv else "NG"
        if mark == "NG":
            fail_b.append((ln, rv["gimmick_unlock_violation"]))
        print(f"  Lv{ln:4d} 해금기믹 {LevelGenerator.filter_gimmicks_by_unlock(ATTR_POOL, ln)}  → {mark}")
    print(f"  통과 {7 - len(fail_b)}/7" + (f"  실패 {fail_b}" if fail_b else ""))

    # ── C. 서브보스 배정: 149 전수 시뮬 + 표본 실생성 ──
    print("\n[C] 서브보스 배정")
    assign = Counter()
    grids = Counter()
    byid = {b["id"]: b for b in P}
    for ln in SUB_LEVELS:
        pid = pick(ln, td_of(ln), P)
        assign[pid] += 1
        grids[byid[pid]["grid"]] += 1
    print(f"  149레벨 배정 — 사용 {len(assign)}/{len(P)}종  격자 {dict(sorted(grids.items()))}")
    print(f"  상위3 점유 {sum(k for _, k in assign.most_common(3)) / len(SUB_LEVELS) * 100:.0f}%"
          f"  최다 {assign.most_common(3)}")

    random.seed(7)
    samp = sorted(random.sample(SUB_LEVELS, min(samples, len(SUB_LEVELS))))
    bad_c = Counter()
    rates, tiles, layers = [], [], Counter()
    for ln in samp:
        td = td_of(ln)
        pid = pick(ln, td, P)
        allowed = LevelGenerator.filter_gimmicks_by_unlock(ATTR_POOL, ln)
        lj = gen.generate(GenerationParams(
            target_difficulty=td, level_number=ln, turtle_pattern_id=pid,
            obstacle_types=allowed, gimmick_intensity=min(1.5, 0.4 + td))).level_json
        for k in check(lj, ln):
            bad_c[k] += 1
        tiles.append(gen._turtle_total_tiles(lj))
        layers[int(lj.get("layer") or 0)] += 1
        rates.append(float(getattr(sim.simulate_with_profile(
            lj, get_profile(BotType.AVERAGE), iterations=30,
            max_moves=int(lj.get("max_moves") or 0) or None, seed=1), "clear_rate", 0) or 0))
    print(f"  실생성 표본 {len(samp)}  위반 {dict(bad_c) or '없음'}")
    print(f"  총타일 {min(tiles)}~{max(tiles)}  층수 {dict(sorted(layers.items()))}")
    print(f"  avg봇 평균 {sum(rates) / len(rates):.3f}  0.25이상 {sum(1 for r in rates if r >= 0.25)}/{len(rates)}")

    ok = not fail_a and not fail_b and not bad_c
    print(f"\n=== 종합: {'전체 통과' if ok else '실패 있음'} ===")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
