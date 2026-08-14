"""[서브보스 후처리] 배치를 복사한 뒤, 끝자리 5 레벨(5 제외)을 등껍질 침식으로 재생성.

프론트의 서브보스 정책(subBossPlan/pickTurtleForLevel)과 **동일 규칙**을 복제한다:
  - 대상: level % 10 == 5 and level > 5  → 15, 25, …, 1495 (149개)
  - 패턴 선택: 레벨의 색 종류(V)에서 실측한 `turtle.difficulty.by_v[V].avg` 가
    (목표 클리어율 + MARGIN) 에 가장 가까운 상위 K개 중 레벨번호로 결정적 회전.
    MARGIN 은 실측 보정값 — by_v 는 기믹/컨테이너 없이 잰 값이라 실제 생성보다 쉽다.
    (마진 스윕: 0.00→5/15, 0.25→9/15, 0.45→9/15 → 0.25 채택)

재생성된 레벨은 `verified=False` 로 되돌려 순차검증 대상이 되게 한다(보스 템플릿 규약과 동일).

사용:
    python scripts/apply_subboss_turtle.py <SRC_BATCH_ID> "<새 배치명>"            # 드라이런
    python scripts/apply_subboss_turtle.py <SRC_BATCH_ID> "<새 배치명>" --apply
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import level_shapes as LS  # noqa: E402
from app.core.generator import LevelGenerator  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402

STORE = Path(__file__).resolve().parents[1] / "data" / "production"
PATTERN_FILE = Path(__file__).resolve().parents[1] / "data" / "custom_patterns.json"

MARGIN = 0.25
TOP_K = 10
ATTR_POOL = ["ice", "chain", "grass", "link", "curtain", "unknown"]


def is_sub_boss(n: int) -> bool:
    return n % 10 == 5 and n > 5


def approx_use_tile_count(n: int) -> int:
    """백엔드 LEVEL_CONFIG_TABLE 미러(패턴 선택용 근사)."""
    for max_lv, v in ((3, 4), (10, 5), (30, 6), (60, 8), (100, 9), (225, 9),
                      (600, 10), (1125, 11), (1500, 12)):
        if n <= max_lv:
            return v
    return 13


def load_patterns() -> List[Dict[str, Any]]:
    data = json.loads(PATTERN_FILE.read_text())
    return [{"id": k, **v["turtle"]} for k, v in data.items()
            if isinstance(v, dict) and v.get("turtle")]


def pick_pattern(level_number: int, target_difficulty: float,
                 patterns: List[Dict[str, Any]]) -> Optional[str]:
    v = approx_use_tile_count(level_number)
    want = min(0.98, max(0.15, 1.05 - target_difficulty) - 0.10 + MARGIN)
    scored = []
    for p in patterns:
        byv = (p.get("difficulty") or {}).get("by_v")
        if not byv:
            continue
        keys = sorted(int(k) for k in byv)
        k = min(keys, key=lambda x: abs(x - v))
        scored.append((abs(byv[str(k)]["avg"] - want), p["id"]))
    if not scored:
        return None
    scored.sort()
    top = [pid for _, pid in scored[:TOP_K]]
    return top[(level_number // 10) % len(top)]


def _jsonable(o: Any) -> Any:
    """생성기가 내부용으로 넣는 set(`_pattern_locked_positions`)을 JSON 배열로 변환.
    API 경로에서는 FastAPI 직렬화가 처리하지만 여기선 직접 덤프하므로 필요."""
    if isinstance(o, set):
        return sorted(o)
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    return o


def _atomic_dump(path: Path, payload: Dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main(src_id: str, new_name: str, apply: bool = False) -> None:
    src_path = STORE / f"{src_id}.json"
    if not src_path.exists():
        print(f"❌ 원본 배치 없음: {src_path}")
        return
    src = json.loads(src_path.read_text())
    levels: List[Dict[str, Any]] = src.get("levels") or []
    print(f"원본  {src_id}  '{(src.get('batch') or {}).get('name')}'  레벨 {len(levels)}")

    targets = [L for L in levels if is_sub_boss(int(L["meta"]["level_number"]))]
    print(f"서브보스 대상 {len(targets)}개 (끝자리 5, 5레벨 제외)\n")

    patterns = load_patterns()
    gen = LevelGenerator()
    out_levels = [copy.deepcopy(L) for L in levels]
    by_ln = {int(L["meta"]["level_number"]): L for L in out_levels}

    done = fail = 0
    stats: Dict[str, int] = {}
    for L in targets:
        ln = int(L["meta"]["level_number"])
        td = float(L["meta"].get("target_difficulty") or 0.5)
        td = min(0.99, max(0.01, td))
        pid = pick_pattern(ln, td, patterns)
        if not pid:
            fail += 1
            continue
        # [언락 강제] 이 레벨에서 해금된 기믹만 넘긴다. 생성기에도 방어선이 있지만
        # 호출부에서 먼저 걸러야 기믹 강도 배분이 왜곡되지 않는다.
        # (이 필터가 없던 초판 실측: 서브보스 149개 중 23개가 언락 위반)
        allowed = LevelGenerator.filter_gimmicks_by_unlock(ATTR_POOL, ln)
        try:
            res = gen.generate(GenerationParams(
                target_difficulty=td, level_number=ln, turtle_pattern_id=pid,
                obstacle_types=allowed, gimmick_intensity=min(1.5, 0.4 + td)))
        except Exception as e:  # noqa: BLE001
            print(f"  Lv{ln}: 생성 실패 {type(e).__name__}: {e}")
            fail += 1
            continue
        lj = res.level_json
        if not lj.get("_turtle_peel"):
            print(f"  Lv{ln}: 등껍질 미적용(폴백) — 원본 유지")
            fail += 1
            continue
        viol = LS.assert_in_board(lj)
        if viol:
            print(f"  Lv{ln}: 격자 위반 {viol[:3]} — 원본 유지")
            fail += 1
            continue
        tgt = by_ln[ln]
        tgt["level_json"] = _jsonable(lj)
        m = tgt["meta"]
        m["actual_difficulty"] = res.actual_difficulty
        m["grade"] = str(res.grade).split(".")[-1]
        m["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        m["status_updated_at"] = m["generated_at"]
        m["regen_attempts"] = int(m.get("regen_attempts") or 0) + 1
        # 재검증 대상으로 되돌림(보스 템플릿 재생성 규약과 동일)
        m["match_score"] = None
        m["verified"] = False
        m["verification_passed"] = None
        stats[pid] = stats.get(pid, 0) + 1
        done += 1

    n_layers = [int((by_ln[int(L['meta']['level_number'])]["level_json"] or {}).get("layer") or 0)
                for L in targets]
    tiles = [gen._turtle_total_tiles(by_ln[int(L['meta']['level_number'])]["level_json"])
             for L in targets]
    print(f"\n적용 {done} / 실패·유지 {fail}")
    print(f"  층수 분포 {sorted(set(n_layers))}  총타일 min {min(tiles)} med {sorted(tiles)[len(tiles)//2]} max {max(tiles)}")
    print(f"  패턴 {len(stats)}종 사용, 최다 {sorted(stats.items(), key=lambda e: -e[1])[:3]}")

    if not apply:
        print("\n(드라이런 — 파일 미생성. --apply 로 새 배치 저장)")
        return

    new_id = f"batch_{int(time.time()*1000)}_subboss"
    batch = copy.deepcopy(src.get("batch") or {})
    batch["id"] = new_id
    batch["name"] = new_name
    batch["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    payload = {
        "batch_id": new_id,
        "batch": batch,
        "levels": out_levels,
        "saved_at": time.time(),
        "version": 1,
    }
    _atomic_dump(STORE / f"{new_id}.json", payload)
    print(f"\n✅ 새 배치 저장: {new_id}  '{new_name}'  레벨 {len(out_levels)}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], apply="--apply" in sys.argv)
