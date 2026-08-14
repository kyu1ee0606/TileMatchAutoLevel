"""[내부 검증] 템플릿 크롭본 전용 배정 수정 후 종합 점검.

수정 배경(실측): 배정 로직이 크롭본(lp_)이 없으면 **원본 템플릿으로 폴백**했다.
  - 원본 73종은 타일이 10칸 폭에 꽉 차 여백 크롭 불가(D타입) → 선언격자 10x10 출고
  - 원본 경로는 min_level=0 이라 기믹 해금 필터까지 무력화 → 조기 등장 8건
→ 크롭본만 후보로 쓰도록 수정. 이 스크립트가 그 결과를 검증한다.

검증 축:
  A. 저장소 정합 — lp_ 사본 전수가 규격(선언격자 ≤8) 통과인가
  B. 실생성      — from-level-shape 로 생성한 레벨이 실제 사용 가능한가
                   (격자·÷3·floating·언락·규칙 게이트 + 봇 클리어율)
  C. 후보 풀     — 배정 가능한 크롭본이 난이도/해금 구간을 덮는가
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.api.routes.analyze import generate_from_level_shape  # noqa: E402
from app.api.routes.production_store import _scan_header_oob, _scan_rule_violations  # noqa: E402
from app.core import level_shapes as LS  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from app.api.routes.analyze import LevelShapeGenerateRequest  # noqa: E402
from verify_turtle_integration import div3_bad, floating_count  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
MAX_DECLARED = 8


def max_dim(lj: Dict[str, Any]) -> int:
    m = 0
    for i in range(int(lj.get("layer") or 0)):
        ld = lj.get(f"layer_{i}") or {}
        try:
            m = max(m, int(ld.get("col")), int(ld.get("row")))
        except (TypeError, ValueError):
            continue
    return m


def main(samples: int = 25) -> None:
    shapes: Dict[str, Any] = json.loads((DATA / "level_shapes.json").read_text())
    tpls: Dict[str, Any] = json.loads((DATA / "level_templates.json").read_text())["templates"]
    sim = BotSimulator()

    # ── A. 저장소 정합 ──
    print("[A] 크롭본 저장소 규격")
    dims = Counter()
    bad_a: List[str] = []
    for sid, e in shapes.items():
        lj = e.get("level_json") or {}
        d = max_dim(lj)
        dims[d] += 1
        if d > MAX_DECLARED or LS.assert_in_board(lj):
            bad_a.append(sid)
    print(f"  lp_ 사본 {len(shapes)}종  선언격자 분포 {dict(sorted(dims.items()))}")
    print(f"  규격 위반 {len(bad_a)}" + (f" → {bad_a[:5]}" if bad_a else " (없음)"))
    covered = {k[3:] for k in shapes if k.startswith("lp_")}
    print(f"  원본 {len(tpls)}종 중 크롭본 있음 {len(covered & set(tpls))} / 없음 {len(set(tpls) - covered)}"
          f"  ← 없는 것은 배정 후보에서 제외됨")

    # ── B. 실생성 ──
    print("\n[B] 크롭본 실생성 (from-level-shape, min_level 존중)")
    random.seed(5)
    ids = random.sample(sorted(shapes), min(samples, len(shapes)))
    bad_b = Counter()
    rates: List[float] = []
    tiles: List[int] = []
    for sid in ids:
        min_lv = int(shapes[sid].get("min_level") or 0)
        ln = max(min_lv, 60)
        try:
            resp = asyncio.run(generate_from_level_shape(LevelShapeGenerateRequest(
                shape_id=sid, level_number=ln, use_tile_count=6,
                randomize_tiles=True, random_seed=ln)))
        except Exception as e:  # noqa: BLE001
            bad_b["route_error"] += 1
            print(f"  {sid} ROUTE-ERR {type(e).__name__}: {e}")
            continue
        lj = resp["level_json"]
        if max_dim(lj) > MAX_DECLARED:
            bad_b["oversized"] += 1
        if _scan_header_oob(lj):
            bad_b["header_oob"] += 1
        if LS.assert_in_board(lj):
            bad_b["board"] += 1
        if div3_bad(lj):
            bad_b["div3"] += 1
        for k in _scan_rule_violations(lj, ln):
            bad_b[f"rule:{k}"] += 1
        n = int(lj.get("layer") or 0)
        tiles.append(sum(len((lj.get(f"layer_{i}") or {}).get("tiles") or {}) for i in range(n)))
        r = sim.simulate_with_profile(
            lj, get_profile(BotType.AVERAGE), iterations=30,
            max_moves=int(lj.get("max_moves") or 0) or None, seed=1)
        rates.append(float(getattr(r, "clear_rate", 0.0) or 0.0))
    print(f"  표본 {len(ids)}  위반 {dict(bad_b) or '없음'}")
    if rates:
        print(f"  총타일 {min(tiles)}~{max(tiles)}  avg봇 평균 {sum(rates)/len(rates):.3f}"
              f"  0.25이상 {sum(1 for x in rates if x >= 0.25)}/{len(rates)}")

    # ── C. 후보 풀 커버리지 ──
    print("\n[C] 배정 후보 커버리지")
    mins = Counter(int(e.get("min_level") or 0) for e in shapes.values())
    tiers = Counter(str(e.get("tier") or "?") for e in shapes.values())
    enabled = sum(1 for e in shapes.values() if e.get("enabled", True))
    print(f"  enabled {enabled}/{len(shapes)}  tier {dict(tiers)}")
    print(f"  min_level 분포 {dict(sorted(mins.items()))}")
    free = sum(v for k, v in mins.items() if k <= 1)
    print(f"  해금 제약 없는 것 {free}종 (초반 슬롯 배정 가능)")

    ok = not bad_a and not bad_b
    print(f"\n=== 종합: {'전체 통과' if ok else '실패 있음'} ===")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 25)
