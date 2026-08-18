"""키타일(unlockTile) ÷3 정합 전수 감사.

게임 클라(DB_Level.cs → TileDistributor)의 t0 분배는 다음 순서다:
  1) set_count      = t0_count // 3
  2) toAddIndexList = 기존(concrete)타입 중 %3 != 0 인 것을 3배수로 올리는 보충분
                      ← **key(index 16)도 여기 포함된다**
  3) type_indices   = distribute_tiles(set_length=set_count, specified_count=unlockTile)
                      → 앞쪽은 매칭타입 세트, 뒤쪽 unlockTile 개는 key 세트
  4) t0 자리마다: toAddIndexList 먼저 소진 → 이후 type_indices[assign_set_count // 3]

즉 **key 세트는 t0 풀에서 잘라 쓴다**. 따라서 매칭에 쓸 수 있는 타일은
t0_count - 3*unlockTile 이며, 이 값이 ÷3 이어야 클리어 가능하다.

이 스크립트는 실제 분배기를 돌려 최종 타입별 개수를 세고,
key 를 제외한 매칭타입이 전부 ÷3 인지 검사한다.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.bot_simulator import TileDistributor  # noqa: E402


def scan_level(lj: dict) -> dict:
    """레벨 하나를 실제 분배기로 돌려 최종 타입 카운트를 낸다."""
    unlock = int(lj.get("unlockTile", lj.get("xUnlockTile", 0)) or 0)
    use_tile_count = min(int(lj.get("useTileCount", 6) or 6), 15)

    concrete = Counter()          # 고정 배치된 t1~t15
    explicit_key_top = 0          # 최상위 타입이 "key" 인 타일
    explicit_key_inner = 0        # 컨테이너 내부 baked 문자열의 "key"
    t0_count = 0
    inner_placeholder = 0

    for i in range(int(lj.get("layer", 0) or 0)):
        ld = lj.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt = td[0]
            if tt == "t0":
                t0_count += 1
            elif tt == "key":
                explicit_key_top += 1
            elif tt.startswith("craft_") or tt.startswith("stack_"):
                if len(td) > 2 and isinstance(td[2], list) and td[2]:
                    inner_str = td[2][1] if len(td[2]) > 1 and isinstance(td[2][1], str) else ""
                    baked = [s for s in inner_str.split("_") if s] if inner_str else []
                    is_baked = bool(baked) and all(
                        s == "key" or (s.startswith("t") and s[1:].isdigit() and s != "t0")
                        for s in baked
                    )
                    if is_baked:
                        for s in baked:
                            if s == "key":
                                explicit_key_inner += 1
                            else:
                                concrete[s] += 1
                    else:
                        try:
                            inner_placeholder += int(td[2][0])
                            t0_count += int(td[2][0])
                        except (ValueError, TypeError):
                            pass
            elif tt.startswith("t") and tt[1:].isdigit():
                concrete[tt] += 1

    # 게임 분배 재현 — existing_tile_counts 에 key 도 넣어야 클라와 동일 (GetToAddIndexList가 16 포함)
    existing = dict(concrete)
    if explicit_key_top or explicit_key_inner:
        existing["key"] = explicit_key_top + explicit_key_inner

    final = Counter(concrete)
    if explicit_key_top or explicit_key_inner:
        final["key"] = explicit_key_top + explicit_key_inner

    to_add = TileDistributor.get_to_add_index_list(existing)

    if t0_count > 0:
        existing_types = [t for t in concrete if t[1:].isdigit()]
        offset = 0
        if existing_types:
            mn = min(int(t[1:]) for t in existing_types)
            offset = mn - 1 if mn > use_tile_count else 0
        assigns = TileDistributor.assign_t0_tiles(
            t0_count=t0_count,
            use_tile_count=use_tile_count,
            rand_seed=int(lj.get("randSeed", 0) or 0),
            shuffle_tile=lj.get("xShuffleTile", 0) or 0,
            type_imbalance=lj.get("xTypeImbalance", lj.get("typeImbalance", 0)) or 0,
            unlock_tile=unlock,
            tile_type_offset=offset,
            existing_tile_counts=existing,
        )
        for a in assigns:
            final[a] += 1

    match_bad = {t: c for t, c in final.items() if t != "key" and c % 3 != 0}
    key_total = final.get("key", 0)

    return {
        "unlock": unlock,
        "t0_count": t0_count,
        "t0_div3": t0_count % 3 == 0,
        "to_add_len": len(to_add),
        "to_add": to_add,
        "explicit_key_top": explicit_key_top,
        "explicit_key_inner": explicit_key_inner,
        "key_total": key_total,
        "key_expected": unlock * 3,
        "key_ok": key_total == unlock * 3,
        "match_bad": match_bad,
        "inner_placeholder": inner_placeholder,
        "final": dict(final),
    }


def main(path: str, lo: int = 1, hi: int = 1500) -> None:
    d = json.load(open(path))
    levels = d["levels"]
    print(f"배치: {d['batch'].get('name')}  레벨수={len(levels)}")
    print(f"key 언락 레벨: {d['batch'].get('gimmick_unlock_levels', {}).get('key')}")
    print()

    rows = []
    for entry in levels:
        ln = entry.get("meta", {}).get("level_number")
        if ln is None or not (lo <= ln <= hi):
            continue
        r = scan_level(entry.get("level_json") or {})
        r["ln"] = ln
        rows.append(r)

    with_unlock = [r for r in rows if r["unlock"] > 0]
    print(f"검사 {len(rows)}개 / unlockTile>0 {len(with_unlock)}개")
    print()

    bad_match = [r for r in rows if r["match_bad"]]
    bad_t0 = [r for r in rows if not r["t0_div3"]]
    bad_key = [r for r in with_unlock if not r["key_ok"]]
    has_toadd = [r for r in rows if r["to_add_len"] > 0]
    expl_key = [r for r in rows if r["explicit_key_top"] or r["explicit_key_inner"]]

    print(f"[A] 매칭타입 ÷3 위반      : {len(bad_match)}")
    print(f"[B] t0 총량 ÷3 위반       : {len(bad_t0)}")
    print(f"[C] key 개수 != unlock*3  : {len(bad_key)}")
    print(f"[D] toAddIndexList 비어있지 않음 : {len(has_toadd)}")
    print(f"[E] 명시적 key 타일 존재  : {len(expl_key)}")
    print()

    def dump(tag, rs, n=12):
        if not rs:
            return
        print(f"--- {tag} (상위 {min(n, len(rs))}건) ---")
        for r in rs[:n]:
            print(
                f"  Lv{r['ln']:<5} unlock={r['unlock']} t0={r['t0_count']} "
                f"toAdd={r['to_add_len']} keyTop={r['explicit_key_top']} "
                f"keyInner={r['explicit_key_inner']} keyTotal={r['key_total']}"
                f"(기대 {r['key_expected']}) bad={r['match_bad']}"
            )
        print()

    dump("[A] 매칭타입 ÷3 위반", bad_match)
    dump("[C] key 개수 불일치", bad_key)
    dump("[D] toAdd 비어있지 않음", has_toadd)
    dump("[E] 명시적 key", expl_key)

    # unlockTile 분포
    from collections import Counter as C
    print("unlockTile 분포:", dict(sorted(C(r["unlock"] for r in rows).items())))
    if with_unlock:
        lns = [r["ln"] for r in with_unlock]
        print(f"unlockTile>0 레벨 범위: {min(lns)} ~ {max(lns)}")


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "data/production/batch_1786702378168_tf27w47o4.json"
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
    main(p, lo, hi)
