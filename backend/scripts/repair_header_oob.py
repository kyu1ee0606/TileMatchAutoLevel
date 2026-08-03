"""[헤더-OOB 수정] 배포 배치의 54개 깨진 레벨 수정.
Class A(51): 초과타일을 최근접 in-header 빈칸으로 relocate(헤더 불변→홀짝 보존).
Class B(3): 0/0 헤더 → 실 extent 기반 정사각교대 헤더 재구성.
검증: 수정후 OOB=0 + solve_level PROVEN_SOLVABLE(구조 클리어가능) 재확인.
기본 dry-run(복사본). --apply 시 원본 백업 후 덮어쓰기.
"""
import sys, json, copy, argparse
from collections import deque
sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")
from app.core.solver import solve_level

BATCH = "/Users/casualdev/TileMatchAutoLevel/backend/data/production/batch_1785320918718_u7y6q83yg.json"


def scan_oob(lj):
    out = []
    for i in range(int(lj.get("layer", 0) or 0)):
        v = lj.get(f"layer_{i}")
        if not isinstance(v, dict):
            continue
        tiles = v.get("tiles") or {}
        try:
            col = int(v.get("col")); row = int(v.get("row"))
        except (TypeError, ValueError):
            if tiles:
                out.append((i, "BAD_HDR", v.get("col"), v.get("row")))
            continue
        if tiles and (col <= 0 or row <= 0):
            out.append((i, "ZERO", col, row)); continue
        for c in tiles:
            x, y = map(int, c.split("_"))
            if x < 0 or x >= col or y < 0 or y >= row:
                out.append((i, c, col, row))
    return out


def goal_output_positions(layer_tiles):
    """craft/stack 출력칸(비워야 함) 집합."""
    out = set()
    for pos, td in layer_tiles.items():
        if not (isinstance(td, list) and td and isinstance(td[0], str)):
            continue
        tt = td[0]
        if not (tt.startswith("craft_") or tt.startswith("stack_")):
            continue
        c, r = map(int, pos.split("_"))
        d = tt[-1]
        if d == "s": out.add(f"{c}_{r+1}")
        elif d == "n": out.add(f"{c}_{r-1}")
        elif d == "e": out.add(f"{c+1}_{r}")
        elif d == "w": out.add(f"{c-1}_{r}")
    return out


def bfs_nearest_empty(cx, cy, col, row, occupied, avoid):
    """(cx,cy)에서 가장 가까운 in-header 빈칸(occupied·avoid 제외) BFS."""
    seen = {(cx, cy)}
    q = deque([(cx, cy)])
    while q:
        x, y = q.popleft()
        pos = f"{x}_{y}"
        if 0 <= x < col and 0 <= y < row and pos not in occupied and pos not in avoid:
            return pos
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) not in seen and -2 <= nx < col + 2 and -2 <= ny < row + 2:
                seen.add((nx, ny)); q.append((nx, ny))
    return None


def repair_class_a(lj):
    """초과타일 relocate. 반환 moves 리스트."""
    moves = []
    for i in range(int(lj.get("layer", 0) or 0)):
        v = lj.get(f"layer_{i}")
        if not isinstance(v, dict):
            continue
        tiles = v.get("tiles") or {}
        try:
            col = int(v.get("col")); row = int(v.get("row"))
        except (TypeError, ValueError):
            continue
        if col <= 0 or row <= 0:
            continue  # Class B는 별도
        oob = []
        for c in list(tiles):
            x, y = map(int, c.split("_"))
            if x < 0 or x >= col or y < 0 or y >= row:
                oob.append((c, x, y))
        if not oob:
            continue
        occupied = set(tiles)
        avoid = goal_output_positions(tiles)
        for coord, x, y in oob:
            cx = min(max(x, 0), col - 1); cy = min(max(y, 0), row - 1)
            occupied.discard(coord)
            tgt = bfs_nearest_empty(cx, cy, col, row, occupied, avoid)
            if tgt is None:
                moves.append((i, coord, None)); continue
            data = tiles.pop(coord)
            tiles[tgt] = data
            occupied.add(tgt)
            moves.append((i, coord, tgt))
        v["num"] = str(len(tiles))
    return moves


def repair_class_b(lj):
    """0/0 헤더 → 정사각교대 재구성. 반환 headers."""
    n = int(lj.get("layer", 0) or 0)
    ext = {}
    for i in range(n):
        v = lj.get(f"layer_{i}")
        if not isinstance(v, dict):
            continue
        tiles = v.get("tiles") or {}
        mx = 0
        for c in tiles:
            x, y = map(int, c.split("_"))
            mx = max(mx, x + 1, y + 1)
        ext[i] = mx
    need_even = max([ext[i] for i in ext if i % 2 == 0] or [0])
    need_odd = max([ext[i] for i in ext if i % 2 == 1] or [0])
    S = max(need_even, need_odd + 1, 1)  # even=S, odd=S-1
    hdrs = {}
    for i in range(n):
        v = lj.get(f"layer_{i}")
        if not isinstance(v, dict):
            continue
        s = S if i % 2 == 0 else S - 1
        was_str = isinstance(v.get("col"), str)
        v["col"] = str(s) if was_str else s
        v["row"] = str(s) if was_str else s
        hdrs[i] = s
    return hdrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    d = json.load(open(BATCH))
    levels = d["levels"]
    repaired_a = 0; repaired_b = 0; solver_fail = []
    for e in levels:
        lj = e.get("level_json")
        if not isinstance(lj, dict):
            continue
        pre = scan_oob(lj)
        if not pre:
            continue
        ln = (e.get("meta") or {}).get("level_number")
        is_b = any(t[1] in ("ZERO", "BAD_HDR") for t in pre)
        if is_b:
            repair_class_b(lj); repaired_b += 1
        else:
            repair_class_a(lj); repaired_a += 1
        post = scan_oob(lj)
        if post:
            solver_fail.append((ln, "OOB_REMAINS", post[:3])); continue
        # solver 재검증(헤더 무시·구조 클리어가능 확인)
        try:
            r = solve_level(lj, node_budget=200000, time_budget_s=5.0)
            if r["verdict"] == "PROVEN_IMPOSSIBLE":
                solver_fail.append((ln, "IMPOSSIBLE", r["reason"][:60]))
        except Exception as ex:
            solver_fail.append((ln, "SOLVER_ERR", str(ex)[:50]))

    print(f"repaired Class A(relocate): {repaired_a} | Class B(reconstruct): {repaired_b}")
    # 전체 재스캔
    total_oob = sum(1 for e in levels if isinstance(e.get("level_json"), dict) and scan_oob(e["level_json"]))
    print(f"post-repair OOB levels remaining: {total_oob}")
    print(f"solver flags (IMPOSSIBLE/err/oob-remain): {len(solver_fail)}")
    for f in solver_fail[:20]:
        print("  ", f)

    if args.apply and total_oob == 0 and not solver_fail:
        import shutil, time
        bak = BATCH + f".bak_{int(time.time())}"
        shutil.copy(BATCH, bak)
        d["version"] = int(d.get("version", 0)) + 1
        json.dump(d, open(BATCH, "w"), ensure_ascii=False)
        print(f"APPLIED. backup={bak} new_version={d['version']}")
    elif args.apply:
        print("NOT APPLIED — 잔여 OOB 또는 solver 실패 있음. 수동 검토 필요.")
    else:
        print("(dry-run — --apply 로 원본 백업후 적용)")


if __name__ == "__main__":
    main()
