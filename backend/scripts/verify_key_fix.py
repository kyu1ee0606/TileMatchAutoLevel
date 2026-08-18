"""키타일 결함 수정 내부검증.

3가지를 배치 전수로 확인한다:
  1) 게임 분배 시뮬(sim_game_distribution) 기준 매칭타입 ÷3 위반
  2) 키 개수 == unlockTile*3
  3) randomTileIndexList 인덱스 초과 (Unity IndexOutOfRange)

복구 전/후를 나란히 찍어 회귀가 없는지 본다.
"""
import copy
import glob
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.generator import LevelGenerator            # noqa: E402
from app.core.solver import _clearability_type_counts     # noqa: E402
from scripts.sim_game_distribution import (               # noqa: E402
    get_to_add_index_list, parse_level, simulate,
)


def defects(lj: dict) -> dict:
    """레벨 하나의 결함을 게임 기준으로 판정."""
    final, unlock, E, A, _ = simulate(lj)
    d = {}

    bad = {f"t{k}": v for k, v in final.items() if k != 16 and v % 3 != 0}
    if bad:
        d["div3"] = bad

    keys = final.get(16, 0)
    if keys % 3 != 0:
        d["key_not_div3"] = keys
    if unlock > 0 and keys < unlock * 3:
        d["key_short"] = f"{keys}/{unlock * 3}"

    # 인덱스 초과: used > len(randomTileIndexList)
    if E > 0:
        n_add = len(get_to_add_index_list(parse_level(lj)[1]))
        S = E // 3
        L = max(0, S - unlock) + unlock
        used = math.ceil((E - n_add) / 3) if E > n_add else 0
        if used > L:
            d["index_oob"] = f"used={used} > len={L}"

    return d


def repair(lj: dict) -> dict:
    g = LevelGenerator()
    out = copy.deepcopy(lj)
    out = g._repair_key_gimmick(out)
    out = g._repair_unlock_tile(out)
    out = g._repair_t0_divisibility(out)
    if {t: c for t, c in _clearability_type_counts(out).items() if c % 3}:
        out = g._repair_clearability(out)
    out = g._repair_goal_count(out)
    return out


def main():
    files = sorted(glob.glob("data/production/batch_*.json"), key=os.path.getmtime)[-4:]
    grand_before = grand_after = 0

    for f in files:
        d = json.load(open(f))
        levels = [e for e in d["levels"] if e.get("meta", {}).get("level_number")]
        if not levels:
            continue

        before, after, unfixed = [], [], []
        for e in levels:
            ln = e["meta"]["level_number"]
            lj = e.get("level_json") or {}
            db = defects(lj)
            if not db:
                continue
            before.append((ln, db))
            da = defects(repair(lj))
            if da:
                after.append((ln, da))
                unfixed.append((ln, db, da))

        grand_before += len(before)
        grand_after += len(after)
        print(f"\n{'=' * 78}")
        print(f"{d['batch'].get('name', '?')[:60]}   ({len(levels)}레벨)")
        print(f"  결함  복구전 {len(before):>3}건  →  복구후 {len(after):>3}건")
        for ln, db in before[:12]:
            fixed_mark = "❌ 미해결" if any(x[0] == ln for x in after) else "✅"
            print(f"    {fixed_mark} Lv{ln:<5} {db}")
        if len(before) > 12:
            print(f"    … 외 {len(before) - 12}건")
        for ln, db, da in unfixed:
            print(f"    ⚠️  Lv{ln} 남은 결함: {da}")

    print(f"\n{'=' * 78}")
    print(f"총계: 복구전 {grand_before}건 → 복구후 {grand_after}건")
    return 0 if grand_after == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
