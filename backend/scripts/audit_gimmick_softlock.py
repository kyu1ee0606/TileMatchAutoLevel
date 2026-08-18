"""기믹 소프트락/오파싱 정적 전수감사 — 게임 코드 근거 기반.

각 검사는 sp_meowsgarden 실제 코드에서 확인한 조건만 쓴다(추측 금지).

[G] grass 순환 데드락
    TileEffect.cs:515  grassEffectRemainCount = 2      (인접 타일 2번 수거해야 해제)
    TileEffect.cs:941  해제는 '인접 타일이 픽될 때'만 진행
    TileEffect.cs:1424 게임 감지기는 CheckRemainNearTile() < 2 만 봄 = **존재 여부만 셈**
    Tile.cs:1584       nearTile 중 !m_Picked 개수 → 이웃이 grass 여도 카운트됨
    ⇒ 서로가 서로를 기다리는 grass 덩어리는 **감지 없이 영구 정지**(2×2 grass 블록이 최소 사례).
    판정: grass 를 '해제가능'으로 만드는 이웃은 non-grass 이거나 이미 해제가능한 grass.
          고정점 반복 후 해제 불가로 남는 grass 가 있으면 소프트락.

[C] chain 순환 데드락
    TileEffect.cs:967   IsNearTile(other, checkHorizon:true) → **좌우(E/W) 이웃만** 해제 트리거
    TileEffect.cs:1433  감지기는 CheckRemainNearTile(true) < 1 만 봄
    ⇒ 좌우로 chain 끼리만 붙어있고 양 끝에 non-chain 이 없으면 영구 정지.

[X] 기믹 문자열 오파싱
    DB_Level.cs:272 GetTileEffectEnum — 완전일치(소문자). 목록 밖은 전부 TileEffectType.None.
    특히 "curtain" 은 None ("curtain_open"/"curtain_close" 만 인정), "teleport" 도 None.

[B] 데이터 기인 하드 실패
    DB_Level.cs:1096 new int[16] + :1108 indexCountArr[tileID-1]  → tileIDNum>16 이면 예외
    TileRow.cs:196 / TileCraft.cs:211  stackTotalCount<=1 이면 인덱스/NRE
    TileCraft.cs:875 switch 식에 default 없음 → 방향이 e/w/s/n 밖이면 플레이 중 예외
    TileEffect.cs:570 bombEffectRemainCount = spInteger.Parse(effect) → 숫자 없으면 0 = 즉시 실패
    Dock.cs:804 SetLockSlot — dockSlots 범위 검사 없음
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KNOWN_EFFECTS = {"ice", "link_e", "link_w", "link_s", "link_n", "unknown", "craft",
                 "grass", "chain", "curtain_open", "curtain_close", "frog",
                 "teleporter", "key"}
DOCK_SLOTS = 7


def layers(lj):
    for i in range(int(lj.get("layer", 0) or 0) + 1):
        ld = lj.get(f"layer_{i}")
        t = ld.get("tiles") if isinstance(ld, dict) else None
        if isinstance(t, dict):
            yield i, t


def pos_xy(p):
    try:
        a, b = p.split("_")
        return int(a), int(b)
    except (ValueError, AttributeError):
        return None


def eff(td):
    return td[1].lower() if len(td) > 1 and isinstance(td[1], str) else ""


def freeable_fixpoint(tiles, targets, need, horizontal_only):
    """targets 안에서 '해제 가능'을 고정점으로 확장. 남는 것이 소프트락.

    need            : 해제에 필요한 이웃 수거 횟수 (grass 2 / chain 1)
    horizontal_only : chain 처럼 좌우 이웃만 트리거로 인정
    """
    coords = {}
    for p in tiles:
        xy = pos_xy(p)
        if xy:
            coords[xy] = p
    tset = {pos_xy(p) for p in targets if pos_xy(p)}

    def neigh(xy):
        x, y = xy
        cand = [(x + 1, y), (x - 1, y)] if horizontal_only else \
               [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        return [c for c in cand if c in coords]

    freeable = set()
    changed = True
    while changed:
        changed = False
        for xy in tset - freeable:
            helpers = 0
            for n in neigh(xy):
                if n not in tset or n in freeable:
                    helpers += 1
            if helpers >= need:
                freeable.add(xy)
                changed = True
    return [coords[xy] for xy in sorted(tset - freeable)]


def audit(lj):
    out = defaultdict(list)
    unlock = int(lj.get("unlockTile", lj.get("xUnlockTile", 0)) or 0)
    if unlock >= DOCK_SLOTS:
        out["A3_dock_overflow"].append(f"unlockTile={unlock} >= 독 {DOCK_SLOTS}칸")

    for li, tiles in layers(lj):
        grass, chain = [], []
        for p, td in tiles.items():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt, e = td[0], eff(td)

            if e and e not in KNOWN_EFFECTS and not e.startswith("bomb"):
                out["X_unparsed_effect"].append(f"L{li}:{p}='{e}'")
            if e.startswith("bomb") and not any(c.isdigit() for c in e):
                out["B4_bomb_zero"].append(f"L{li}:{p}='{e}'")
            if e == "grass":
                grass.append(p)
            elif e == "chain":
                chain.append(p)

            if tt.startswith("t") and tt[1:].isdigit() and int(tt[1:]) > 16:
                out["B1_tileid_overflow"].append(f"L{li}:{p}={tt}")

            if tt.startswith("craft_") or tt.startswith("stack_"):
                d = tt.split("_", 1)[1] if "_" in tt else ""
                if d not in ("e", "w", "s", "n"):
                    out["B6_bad_direction"].append(f"L{li}:{p}={tt}")
                si = td[2] if len(td) > 2 else None
                n = 0
                if isinstance(si, list) and si:
                    try:
                        n = int(si[0])
                    except (ValueError, TypeError):
                        n = 0
                if n <= 1:
                    out["B3_inner_count"].append(f"L{li}:{p}={tt} inner={n}")

        if grass:
            stuck = freeable_fixpoint(tiles, grass, need=2, horizontal_only=False)
            if stuck:
                out["G_grass_softlock"].append(f"L{li}:{stuck[:6]}")
        if chain:
            stuck = freeable_fixpoint(tiles, chain, need=1, horizontal_only=True)
            if stuck:
                out["C_chain_softlock"].append(f"L{li}:{stuck[:6]}")

    return dict(out)


def main(path):
    d = json.load(open(path))
    print(f"배치: {d['batch'].get('name', '?')[:60]}\n")
    agg = defaultdict(list)
    for e in d["levels"]:
        ln = e.get("meta", {}).get("level_number")
        if ln is None:
            continue
        for k, v in audit(e.get("level_json") or {}).items():
            agg[k].append((ln, v))

    LABEL = {
        "G_grass_softlock":   "🔴 grass 순환 데드락 (게임 미감지 = 영구 정지)",
        "C_chain_softlock":   "🔴 chain 좌우 순환 데드락 (게임 미감지)",
        "X_unparsed_effect":  "🟠 기믹 문자열 미인식 → 게임에서 기믹 소멸",
        "B4_bomb_zero":       "🔴 bomb 카운트 0 → 첫 클릭에 강제 실패",
        "B1_tileid_overflow": "🔴 tileIDNum>16 → indexCountArr 예외",
        "B3_inner_count":     "🟠 컨테이너 내부 ≤1 → 인덱스/NRE 위험",
        "B6_bad_direction":   "🔴 craft/stack 방향 비정상 → 플레이 중 예외",
        "A3_dock_overflow":   "🔴 unlockTile ≥ 독 슬롯",
    }
    if not agg:
        print("결함 없음")
        return
    for k in LABEL:
        rows = agg.get(k)
        if not rows:
            print(f"{LABEL[k]}\n    없음\n")
            continue
        print(f"{LABEL[k]}\n    {len(rows)}개 레벨")
        for ln, v in rows[:10]:
            print(f"      Lv{ln:<5} {v[:3]}")
        if len(rows) > 10:
            print(f"      … 외 {len(rows) - 10}개")
        print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "data/production/batch_1786011385119_qi96gz8x5.json")
