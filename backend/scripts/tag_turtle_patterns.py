"""[등껍질 화이트리스트] custom_patterns.json 의 '두꺼운' 모양을 스캔해 turtle 메타를 태깅.

등껍질 침식은 **선정된 모양에만** 적용한다(그 외 템플릿·패턴은 기존 경로 유지).
선정 기준은 순수 계산이므로 파생 데이터를 원본 옆에 기록한다(별도 저장소 불필요):

    "0_6x6": {
      "grid_size": 6, "positions": [...], "count": 36,
      "turtle": {"depth": 6, "total": 91, "per_layer": [36,25,16,9,4,1], "base": 6}
    }

`turtle` 이 없는 엔트리 = 등껍질 미대상. 재실행 시 항상 재계산해 덮어쓴다(멱등).

사용:
    python scripts/tag_turtle_patterns.py            # 드라이런(요약만)
    python scripts/tag_turtle_patterns.py --apply    # custom_patterns.json 갱신
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.generator import LevelGenerator  # noqa: E402

# 선정 기준 — 실험(exp_turtle_select.py) 실측 근거:
#   깊이 4 미만은 '등껍질' 실루엣이 안 나옴(2~3층은 기존 스택과 구분 안 됨)
#   총타일 130 초과는 프로덕션 p95(128) 초과 → 예산 밖
MIN_DEPTH = 4
MAX_TOTAL = 130

PATTERN_FILE = Path(__file__).resolve().parents[1] / "data" / "custom_patterns.json"


def entry_cells(entry: Dict[str, Any]) -> Tuple[Set[Tuple[int, int]], int] | None:
    try:
        g = int(entry.get("grid_size"))
    except (TypeError, ValueError):
        return None
    if not (4 <= g <= 8):
        return None
    cells: Set[Tuple[int, int]] = set()
    for p in entry.get("positions") or []:
        try:
            x, y = map(int, str(p).split("_"))
        except ValueError:
            continue
        if 0 <= x < g and 0 <= y < g:
            cells.add((x, y))
    return (cells, g) if cells else None


def main(apply: bool = False) -> None:
    data: Dict[str, Any] = json.loads(PATTERN_FILE.read_text())
    picked, cleared, skipped = 0, 0, 0
    rows = []
    for pid, entry in data.items():
        if not isinstance(entry, dict):
            continue
        parsed = entry_cells(entry)
        if not parsed:
            if entry.pop("turtle", None) is not None:
                cleared += 1
            skipped += 1
            continue
        cells, g = parsed
        stack = LevelGenerator._turtle_peel_stack(cells, g)
        per = [len(c) for _, _, c in stack]
        total = sum(per)
        if len(stack) >= MIN_DEPTH and total <= MAX_TOTAL:
            entry["turtle"] = {"depth": len(stack), "total": total,
                               "per_layer": per, "base": g}
            picked += 1
            rows.append((len(stack), total, g, pid, per))
        elif entry.pop("turtle", None) is not None:
            cleared += 1

    rows.sort(key=lambda r: (-r[0], r[1]))
    print(f"선정 {picked}개 / 태그제거 {cleared}개 / 대상외 {skipped}개 "
          f"(깊이≥{MIN_DEPTH}, 총≤{MAX_TOTAL})\n")
    for depth, total, g, pid, per in rows:
        print(f"  {pid:12s} base{g} 깊이{depth} 총{total:4d} {per}")

    if not apply:
        print("\n(드라이런 — 파일 미변경. --apply 로 반영)")
        return

    # 원자적 쓰기(임시파일 → rename): 부분쓰기로 패턴 라이브러리가 깨지는 사고 방지
    fd, tmp = tempfile.mkstemp(dir=str(PATTERN_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, PATTERN_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print(f"\n✅ {PATTERN_FILE} 갱신 완료")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
