"""[시드] custom_patterns 의 등껍질 자격 패턴(49종)을 turtle_bases 로 **복사**.

원본(`custom_patterns.json`)은 등껍질 외 경로에서도 쓰이므로 **건드리지 않는다**.
난이도 측정값(`turtle.difficulty`)이 이미 있으면 그대로 가져와 재측정을 아낀다.

사용:
    python scripts/seed_turtle_bases.py           # 드라이런
    python scripts/seed_turtle_bases.py --apply
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import turtle_bases as TB  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "data" / "custom_patterns.json"


def main(apply: bool = False) -> None:
    src = json.loads(SRC.read_text())
    cand = [(k, v) for k, v in src.items()
            if isinstance(v, dict) and isinstance(v.get("turtle"), dict)]
    print(f"custom_patterns 등껍질 자격 {len(cand)}종")

    grids = Counter()
    rows = []
    for pid, v in cand:
        grid = int(v.get("grid_size"))
        cells = [str(p) for p in (v.get("positions") or [])]
        why = TB.validate(cells, grid)
        grids[grid] += 1
        rows.append((pid, grid, len(cells), why))

    ok = [r for r in rows if r[3] is None]
    ng = [r for r in rows if r[3] is not None]
    print(f"  격자 분포 {dict(sorted(grids.items()))}")
    print(f"  복사 가능 {len(ok)} / 부적합 {len(ng)}")
    for pid, grid, n, why in ng[:8]:
        print(f"    ✗ {pid} ({grid}x{grid}, {n}셀): {why}")

    if not apply:
        print("\n(드라이런 — --apply 로 복사)")
        return

    added = 0
    for pid, v in cand:
        grid = int(v.get("grid_size"))
        cells = [str(p) for p in (v.get("positions") or [])]
        if TB.validate(cells, grid) is not None:
            continue
        bid = f"tb_{pid}"
        TB.put_base(bid, name=f"패턴 {pid}", grid=grid, cells=cells,
                    enabled=True, source=f"custom_patterns:{pid}")
        diff = (v.get("turtle") or {}).get("difficulty")
        if diff:
            TB.set_difficulty(bid, diff)   # 기존 실측치 승계 → 재측정 불필요
        added += 1
    print(f"\n✅ turtle_bases 에 {added}종 복사 완료 → {TB.STORE_PATH}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
