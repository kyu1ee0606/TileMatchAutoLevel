"""[내부 검증] 등껍질 통합 후 **각 템플릿 유형이 정상 생성되는지** 회귀 확인.

검증 대상 5유형:
  A. 등껍질 화이트리스트 (custom_patterns 의 turtle 태그 49개) → 침식 스택으로 생성
  B. 등껍질 **미대상** 커스텀 패턴 (turtle 태그 없음) → 기존 절차생성 그대로
  C. 층별 패턴 (level_shapes `lp_*`) → from-level-shape 파이프라인 그대로
  D. 보스 템플릿 (boss_templates) → 구조 그대로
  E. 일반 절차생성 (템플릿 없음) → 층수 상한 스위치 on/off 비교

각 건마다: 격자위반 / ÷3 / floating / 층수 / 타일수 / 봇 클리어율.
"""
from __future__ import annotations

import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import level_shapes as LS  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import (  # noqa: E402
    LevelGenerator, select_color_balanced_tiles,
)
from app.core.unit_templates import get_cover_offsets  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


def cells_of(ld: Dict[str, Any]) -> Set[Tuple[int, int]]:
    out = set()
    for pos in (ld.get("tiles") or {}):
        try:
            x, y = map(int, pos.split("_"))
        except ValueError:
            continue
        out.add((x, y))
    return out


def floating_count(lj: Dict[str, Any]) -> int:
    bad = 0
    n = int(lj.get("layer") or 0)
    for i in range(1, n):
        ld, below = lj.get(f"layer_{i}"), lj.get(f"layer_{i-1}")
        if not isinstance(ld, dict) or not isinstance(below, dict):
            continue
        try:
            bc, uc = int(below.get("col")), int(ld.get("col"))
        except (TypeError, ValueError):
            continue
        offs = get_cover_offsets(i - 1, i, bc, uc)
        lower = cells_of(below)
        for (ux, uy) in cells_of(ld):
            if not any((ux - dx, uy - dy) in lower for dx, dy in offs):
                bad += 1
    return bad


def div3_bad(lj: Dict[str, Any]) -> Dict[str, int]:
    n = int(lj.get("layer") or 0)
    cnt: Counter[str] = Counter()
    for i in range(n):
        for tile in ((lj.get(f"layer_{i}") or {}).get("tiles") or {}).values():
            t = tile[0] if isinstance(tile, list) and tile else str(tile)
            cnt[t] += 1
    return {t: c for t, c in cnt.items()
            if t.startswith("t") and t[1:].isdigit() and t != "t0" and c % 3}


def check(tag: str, lj: Dict[str, Any], sim: BotSimulator, iters: int = 30,
          strict_float: bool = True) -> bool:
    """strict_float=False: 템플릿 계열은 **원본에 이미 floating 이 설계되어 있다**
    (게임에 중력이 없어 층은 독립 렌더 → 의도된 비주얼). 생성기가 만든 게 아니므로
    합격 기준에서 제외하고 값만 표시한다."""
    n = int(lj.get("layer") or 0)
    per = [len((lj.get(f"layer_{i}") or {}).get("tiles") or {}) for i in range(n)]
    viol = LS.assert_in_board(lj)
    bad3 = div3_bad(lj)
    flo = floating_count(lj)
    try:
        r = sim.simulate_with_profile(lj, get_profile(BotType.AVERAGE), iterations=iters,
                                      max_moves=int(lj.get("max_moves") or 0) or None, seed=1)
        clear = float(getattr(r, "clear_rate", 0.0) or 0.0)
    except Exception as e:  # noqa: BLE001
        print(f"  {tag:26s} SIM-ERR {type(e).__name__}: {e}")
        return False
    ok = (not viol) and (not bad3) and (flo == 0 or not strict_float) and clear >= 0.20
    print(f"  {tag:26s} 층{n:2d} 총{sum(per):4d} {str(per):26s} "
          f"brd={len(viol)} d3={len(bad3)} flo={flo} clear={clear:.2f} {'OK' if ok else 'NG'}")
    return ok


def template_pipeline(gen: LevelGenerator, lj: Dict[str, Any], level_number: int) -> Dict[str, Any]:
    """from-template / from-level-shape 와 동일 순서."""
    lj = copy.deepcopy(lj)
    tile_types = select_color_balanced_tiles(6, seed=level_number)
    rng = random.Random(level_number)
    for i in range(int(lj.get("layer") or 0)):
        for tile in ((lj.get(f"layer_{i}") or {}).get("tiles") or {}).values():
            if isinstance(tile, list) and tile and tile[0] == "t0":
                tile[0] = rng.choice(tile_types)
    lj = gen._ensure_tutorial_unlock_gimmick(lj, level_number)
    lj = gen._finalize_divisibility_guarantee(lj)
    lj = gen._finalize_level(lj)
    return lj


def main(sample: int = 8) -> None:
    gen = LevelGenerator()
    sim = BotSimulator()
    cps: Dict[str, Any] = json.loads((DATA / "custom_patterns.json").read_text())
    results: Dict[str, Tuple[int, int]] = {}

    # ── A. 등껍질 화이트리스트 ──
    print("\n[A] 등껍질 화이트리스트 (turtle 태그)")
    turtle_ids = [k for k, v in cps.items() if isinstance(v, dict) and v.get("turtle")]
    ok = 0
    for pid in turtle_ids:
        res = gen.generate(GenerationParams(target_difficulty=0.5, level_number=320,
                                            turtle_pattern_id=pid))
        lj = res.level_json
        marker = lj.get("_turtle_peel") is True
        good = check(f"{pid}{'' if marker else ' (마커없음!)'}", lj, sim) and marker
        ok += good
    results["A 등껍질"] = (ok, len(turtle_ids))

    # ── B. 등껍질 미대상 커스텀 패턴 (기존 절차생성) ──
    print("\n[B] 미대상 커스텀 패턴 → 기존 절차생성")
    plain = [k for k, v in cps.items() if isinstance(v, dict) and not v.get("turtle")][:sample]
    ok = 0
    for pid in plain:
        try:
            idx = int(pid.split("_")[0])
        except ValueError:
            continue
        res = gen.generate(GenerationParams(target_difficulty=0.5, level_number=320,
                                            pattern_index=idx, pattern_type="aesthetic"))
        lj = res.level_json
        if lj.get("_turtle_peel"):
            print(f"  {pid:26s} NG — 미대상인데 등껍질 마커가 붙음")
            continue
        ok += check(pid, lj, sim)
    results["B 일반패턴"] = (ok, len(plain))

    # ── C. 층별 패턴 (level_shapes) ──
    print("\n[C] 층별 패턴 lp_* (from-level-shape 경로)")
    shapes: Dict[str, Any] = json.loads((DATA / "level_shapes.json").read_text())
    sids = [k for k, v in shapes.items() if isinstance(v, dict) and v.get("level_json")][:sample]
    ok = 0
    for sid in sids:
        lv = max(int(shapes[sid].get("min_level") or 0), 320)
        lj = template_pipeline(gen, shapes[sid]["level_json"], lv)
        ok += check(sid.replace("21ff4576052__", ""), lj, sim, strict_float=False)
    results["C 층별패턴"] = (ok, len(sids))

    # ── D. 보스 템플릿 ── 실제 엔드포인트(/generate/from-boss-template)를 그대로 호출.
    # (boss_templates.json 은 level_json 이 아니라 layers 리스트로 저장 → 변환은 라우트가 담당)
    print("\n[D] 보스 템플릿 (from-boss-template 라우트)")
    import asyncio

    from app.api.routes.analyze import generate_from_boss_template  # noqa: PLC0415
    from app.api.routes.analyze import BossTemplateGenerateRequest  # noqa: PLC0415

    bosses: Dict[str, Any] = json.loads((DATA / "boss_templates.json").read_text())
    bids = [k for k, v in bosses.items() if isinstance(v, dict)][:sample]
    ok = 0
    for bid in bids:
        lv = int(bosses[bid].get("level_min") or 10)
        try:
            resp = asyncio.run(generate_from_boss_template(
                BossTemplateGenerateRequest(level_number=lv, target_difficulty=0.5,
                                            apply_gimmicks=True)))
        except Exception as e:  # noqa: BLE001
            print(f"  {bid:26s} ROUTE-ERR {type(e).__name__}: {e}")
            continue
        ok += check(f"{bid}(lv{lv})", resp["level_json"], sim, strict_float=False)
    results["D 보스템플릿"] = (ok, len(bids))

    # ── E. 일반 절차생성 + 층수 상한 스위치 ──
    print("\n[E] 일반 절차생성 — 층수 상한 on/off")
    ok = 0
    trials: List[Tuple[str, GenerationParams]] = []
    for diff in (0.3, 0.5, 0.7):
        trials.append((f"cap=ON  diff{diff}", GenerationParams(
            target_difficulty=diff, level_number=320, enforce_layer_cap=True)))
        trials.append((f"cap=OFF diff{diff}", GenerationParams(
            target_difficulty=diff, level_number=320, enforce_layer_cap=False,
            min_layers=6, max_layers=8)))
    for tag, p in trials:
        res = gen.generate(p)
        ok += check(tag, res.level_json, sim)
    results["E 절차생성"] = (ok, len(trials))

    print("\n=== 요약 ===")
    for k, (o, t) in results.items():
        print(f"  {k:14s} OK {o}/{t}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
