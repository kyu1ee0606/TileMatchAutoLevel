"""게임(DB_Level.cs ShuffleEmptyTiles/DistributeTiles) 분배를 **그대로** 재현해서
최종 타입별 개수를 뽑고 ÷3 정합과 키타일 개수를 검사한다.

포팅 원본 (읽기 전용 참조):
  Assets/08.Scripts/Tile_Script/InGame/DB_Level.cs
    841  GetEmptyTileList(bool getAllTile)
    1094 GetToAddIndexList
    1158 emptyTiles = GetEmptyTileList()          ← t0 만
    1159 toAddIndexList = GetToAddIndexList()     ← 전체 타일(컨테이너 내부 포함)
    1173 lockBufferCount = xUnlockTile
    1179 DistributeTiles(emptyTilesLength / 3, maxTileIndex, lockBufferCount, ...)
    1183 randomTileIndexList 셔플
    1196 배정 루프 (toAdd 우선 소진 → curIndex = setCount/3)
    1329 ActiveColorCount / 1332 ColorCapacityOf / 1327 TilesPerColor=3
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.bot_simulator import zWellRandom  # noqa: E402

TILES_PER_COLOR = 3
IMBALANCE_FACTOR = 3.0
SPECIFIED_INDEX = 16


def active_color_count(use_tile_count: int) -> int:
    return 0 if use_tile_count <= 0 else (use_tile_count + TILES_PER_COLOR - 1) // TILES_PER_COLOR


def color_capacity_of(color_idx: int, use_tile_count: int) -> int:
    return max(0, min(use_tile_count - color_idx * TILES_PER_COLOR, TILES_PER_COLOR))


def round_to_int(x: float) -> int:
    """Unity Mathf.RoundToInt = banker's rounding (MidpointRounding.ToEven)."""
    import math
    f = math.floor(x)
    diff = x - f
    if diff > 0.5:
        return int(f) + 1
    if diff < 0.5:
        return int(f)
    return int(f) if int(f) % 2 == 0 else int(f) + 1


def distribute_tiles(set_length, tile_type_count, specified_count, imbalance, rnd):
    """DB_Level.cs:1340 DistributeTiles 그대로."""
    result = []
    non_specified_total = max(0, set_length - specified_count)

    if tile_type_count > 0 and non_specified_total > 0:
        active_colors = active_color_count(tile_type_count)
        color_cap = [color_capacity_of(c, tile_type_count) for c in range(active_colors)]
        total_cap = sum(color_cap)
        color_set = [0] * active_colors

        assigned_sum = 0
        if total_cap > 0:
            for c in range(active_colors):
                color_set[c] = non_specified_total * color_cap[c] // total_cap
                assigned_sum += color_set[c]

        remainder = non_specified_total - assigned_sum
        for i in range(remainder):
            color_set[i % active_colors] += 1

        if imbalance > 0.0 and active_colors > 1:
            base_count = non_specified_total / active_colors
            for c in range(active_colors):
                norm = (2 * c - (active_colors - 1)) / (active_colors - 1)
                delta = round_to_int(base_count * imbalance * IMBALANCE_FACTOR * norm)
                color_set[c] = max(0, color_set[c] + delta)

            cur = sum(color_set)
            diff = non_specified_total - cur
            guard = 0
            while diff != 0 and guard < 10000:
                guard += 1
                if diff > 0:
                    t = 0
                    for c in range(1, active_colors):
                        if color_set[c] < color_set[t]:
                            t = c
                    color_set[t] += 1
                    diff -= 1
                else:
                    t = -1
                    for c in range(active_colors):
                        if color_set[c] <= 0:
                            continue
                        if t == -1 or color_set[c] > color_set[t]:
                            t = c
                    if t == -1:
                        break
                    color_set[t] -= 1
                    diff += 1

        for c in range(active_colors):
            cap = color_cap[c]
            sets = color_set[c]
            if cap <= 0 or sets <= 0:
                continue
            quotient = sets // cap
            rem = sets % cap
            per_slot = [quotient] * cap
            if rem > 0:
                if cap == 1:
                    per_slot[0] += rem
                else:
                    order = list(range(cap))
                    if rnd is not None:
                        for i in range(cap - 1, 0, -1):
                            j = rnd.rand(0, i)
                            order[i], order[j] = order[j], order[i]
                    for k in range(rem):
                        per_slot[order[k]] += 1
            for o in range(cap):
                tile_id = c * TILES_PER_COLOR + o + 1
                result.extend([tile_id] * per_slot[o])

    for _ in range(specified_count):
        result.append(SPECIFIED_INDEX)

    return result


def parse_level(lj: dict):
    """게임의 CTile 트리를 흉내낸다.

    반환:
      empty_ids : 분배 대상 t0 리스트 (GetEmptyTileList(false) 상당)
      all_ids   : 전체 타일 id 리스트 (GetEmptyTileList(true) 상당, 컨테이너 내부 포함)
    """
    empty = 0
    all_ids = []          # tileIDNum 값들

    for i in range(int(lj.get("layer", 0) or 0)):
        ld = lj.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt = td[0]
            gim = td[1] if len(td) > 1 and isinstance(td[1], str) else ""

            if tt.startswith("craft_") or tt.startswith("stack_"):
                # xTileStackInfo 존재 → GetEmptyTileList(true)는 stackCTileList 만 넣는다
                si = td[2] if len(td) > 2 else None
                if not (isinstance(si, list) and si):
                    continue
                try:
                    n = int(si[0])
                except (ValueError, TypeError):
                    continue
                inner_str = si[1] if len(si) > 1 and isinstance(si[1], str) else ""
                ids = [s for s in inner_str.split("_") if s] if inner_str else []
                # CTileStackInfo:149 — 개수가 정확히 일치할 때만 baked 채택
                if len(ids) == n:
                    for s in ids:
                        all_ids.append(tile_id_num(s, ""))
                        if tile_id_num(s, "") == 0:
                            empty += 1
                else:
                    for _ in range(n):
                        all_ids.append(0)
                        empty += 1
            else:
                v = tile_id_num(tt, gim)
                all_ids.append(v)
                if v == 0:
                    empty += 1

    return empty, all_ids


def tile_id_num(tile_id: str, effect: str = "") -> int:
    """DB_Level.cs:257 GetTileIDNum + :234 isKeyTile."""
    if tile_id == "t16" or tile_id.lower() == "key" or (effect or "").lower() == "key":
        return 16
    if tile_id.startswith("t"):
        try:
            return int(tile_id[1:])
        except ValueError:
            return 0
    return -1


def get_to_add_index_list(all_ids):
    """DB_Level.cs:1094 GetToAddIndexList."""
    arr = [0] * 16
    for v in all_ids:
        if v == 0 or v == -1:
            continue
        if 1 <= v <= 16:
            arr[v - 1] += 1
    out = []
    for i, c in enumerate(arr):
        odd = c % 3
        if odd != 0:
            out.extend([i + 1] * (3 - odd))
    return out


def simulate(lj: dict):
    empty_count, all_ids = parse_level(lj)
    use_tile_count = int(lj.get("useTileCount", 0) or 0)
    unlock = int(lj.get("unlockTile", lj.get("xUnlockTile", 0)) or 0)
    imbalance = float(lj.get("xTypeImbalance", lj.get("typeImbalance", 0)) or 0) / 10.0
    seed = int(lj.get("randSeed", 0) or 0)

    # 최종 카운트의 출발점: 이미 확정된 타일들 (t0 제외)
    final = Counter()
    for v in all_ids:
        if v > 0:
            final[v] += 1

    if empty_count == 0:
        # DB_Level.cs:1172 `if (emptyTilesLength == 0) return;` — 분배 자체를 하지 않는다
        return final, unlock, empty_count, 0, None

    rnd = zWellRandom(seed if seed > 0 else 0)
    to_add = get_to_add_index_list(all_ids)
    max_tile_index = use_tile_count if use_tile_count > 0 else 15

    idx_list = distribute_tiles(empty_count // 3, max_tile_index, unlock, imbalance, rnd)

    # DB_Level.cs:1183 셔플
    for i in range(len(idx_list) - 1, 0, -1):
        j = rnd.rand(0, i)
        idx_list[i], idx_list[j] = idx_list[j], idx_list[i]

    to_add_q = list(to_add)
    set_count = 0
    truncated = None
    for i in range(empty_count):
        if to_add_q:
            final[to_add_q.pop(0)] += 1
        else:
            cur = set_count // 3
            set_count += 1
            if cur < len(idx_list):
                final[idx_list[cur]] += 1
            else:
                truncated = cur
                final[1] += 1  # 게임은 여기서 IndexOutOfRange — 관측용

    return final, unlock, empty_count, len(to_add), truncated


def main(path, lo=1, hi=1500):
    d = json.load(open(path))
    print(f"배치: {d['batch'].get('name')}")
    print()

    bad_div3, bad_key, oob, rows = [], [], [], []
    for e in d["levels"]:
        ln = e.get("meta", {}).get("level_number")
        if ln is None or not (lo <= ln <= hi):
            continue
        lj = e.get("level_json") or {}
        final, unlock, empty, n_add, trunc = simulate(lj)

        match_bad = {f"t{k}": v for k, v in final.items() if k != 16 and v % 3 != 0}
        keys = final.get(16, 0)
        r = dict(ln=ln, unlock=unlock, empty=empty, n_add=n_add, keys=keys,
                 bad=match_bad, trunc=trunc, key_bad=(keys % 3 != 0),
                 key_short=(unlock > 0 and keys < unlock * 3))
        rows.append(r)
        if match_bad:
            bad_div3.append(r)
        if r["key_bad"] or r["key_short"]:
            bad_key.append(r)
        if trunc is not None:
            oob.append(r)

    print(f"검사 {len(rows)}개")
    print(f"[1] 매칭타입 ÷3 위반          : {len(bad_div3)}")
    print(f"[2] key 개수 결함(비÷3/부족)  : {len(bad_key)}")
    print(f"[3] randomTileIndexList 초과  : {len(oob)}")
    print()

    def dump(tag, rs, n=30):
        if not rs:
            return
        print(f"--- {tag} ({len(rs)}건, 상위 {min(n, len(rs))}) ---")
        for r in rs[:n]:
            print(f"  Lv{r['ln']:<5} unlock={r['unlock']} t0={r['empty']} toAdd={r['n_add']} "
                  f"key={r['keys']}(기대{r['unlock']*3}) bad={r['bad']}")
        print()

    dump("[1] 매칭타입 ÷3 위반", bad_div3)
    dump("[2] key 결함", bad_key)
    dump("[3] 인덱스 초과", oob)
    return rows


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "data/production/batch_1786702378168_tf27w47o4.json"
    main(p, int(sys.argv[2]) if len(sys.argv) > 2 else 1,
         int(sys.argv[3]) if len(sys.argv) > 3 else 1500)
