"""[진단 전용] 유닛 조립 v3 상위층 실루엣 실측.

프로덕션과 같은 경로(LevelGenerator.generate + unit_assembly=True)로 N개 생성해
각 레벨의 최상위 2개 층을 ASCII 로 찍고, 상위층 실루엣의 형태 통계를 낸다.

목적: "가로형 직사각형만 나온다 / 다양성 없다" 주장을 수치로 확인.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.generator import LevelGenerator  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402


def cells(ld: dict) -> set[tuple[int, int]]:
    out = set()
    for pos in (ld.get("tiles") or {}):
        try:
            x, y = map(int, pos.split("_"))
        except ValueError:
            continue
        out.add((x, y))
    return out


def ascii_layer(ld: dict) -> list[str]:
    col = int(ld.get("col") or 0)
    row = int(ld.get("row") or 0)
    cs = cells(ld)
    return ["".join("#" if (x, y) in cs else "." for x in range(col)) for y in range(row)]


def classify(cs: set[tuple[int, int]]) -> str:
    """실루엣 형태 라벨."""
    if not cs:
        return "EMPTY"
    xs = [x for x, _ in cs]
    ys = [y for _, y in cs]
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    if len(cs) == w * h:                       # 바운딩박스를 꽉 채움 = 통짜 사각형
        return f"SOLID_RECT_{w}x{h}"
    fill = len(cs) / (w * h)
    if h == 1:
        return "BAR_H"
    if w == 1:
        return "BAR_V"
    return f"SHAPE_{w}x{h}_f{fill:.2f}"


def main(n: int = 12, difficulty: float = 0.55) -> None:
    gen = LevelGenerator()
    labels: Counter[str] = Counter()
    for i in range(n):
        params = GenerationParams(
            target_difficulty=difficulty,
            unit_assembly=True,
            level_number=200 + i * 7,
        )
        try:
            res = gen.generate(params)
            level = getattr(res, 'level_json', None) or getattr(res, 'level', None) or res
        except Exception as e:  # noqa: BLE001
            print(f"[{i}] generate failed: {e}")
            continue
        nlayer = int(level.get("layer") or 0)
        counts = []
        for li in range(nlayer):
            ld = level.get(f"layer_{li}") or {}
            counts.append(len(ld.get("tiles") or {}))
        print(f"\n=== sample {i}  layers={nlayer} tiles={counts} ===")
        for li in range(max(1, nlayer - 2), nlayer):
            ld = level.get(f"layer_{li}") or {}
            cs = cells(ld)
            lab = classify(cs)
            if li == nlayer - 1:
                labels[lab] += 1
            print(f"-- layer {li}  col={ld.get('col')} n={len(cs)}  {lab}")
            for line in ascii_layer(ld):
                print("   " + line)
    print("\n=== TOP-LAYER SILHOUETTE HISTOGRAM ===")
    for lab, c in labels.most_common():
        print(f"  {c:3d}  {lab}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12,
         float(sys.argv[2]) if len(sys.argv) > 2 else 0.55)
