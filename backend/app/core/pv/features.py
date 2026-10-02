"""Fast placement features for seed pre-filtering (P1 extension).

Input: one resolved explicit map (canonical townpop map after `cs_shuffle.resolve_map`).
Output: a dict of numbers computed in milliseconds. Meant ONLY for comparing seeds of the same
level (same structure, different kind assignment) — cross-level meaning is not claimed.

Cover graph follows the client rule `CLevel.FindAllUpperTiles` (DB_Level.cs:751-835):
  for every upper layer i > L: same parity -> (x, y); different parity -> 4 cells, offset by the
  layer `col` comparison (upper col > cur col: (x,y),(x+1,y),(x,y+1),(x+1,y+1); else
  (x-1,y-1),(x,y-1),(x-1,y),(x,y)).
Stacks (non-craft): inner k is blocked only by inner k+1 (Tile.cs:1390-1438, 01 §5-3); a board tile
under a stack position is blocked by the stack's bottom inner (index 0, removed last).
Craft containers are approximated like stacks (not present in the P1 sample).
Gimmicks (ice/chain/grass/link) are ignored here — features are placement-only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

TRAY = 7


class _Node:
    __slots__ = ("kind", "layer", "pos", "inner", "blockers", "children")

    def __init__(self, kind: str, layer: int, pos: str, inner: Optional[int]):
        self.kind = kind
        self.layer = layer
        self.pos = pos
        self.inner = inner
        self.blockers: List[int] = []  # direct upper blockers (node ids)
        self.children: List[int] = []  # nodes this one directly blocks


def _is_container(tile: Any) -> bool:
    return isinstance(tile, list) and len(tile) >= 3 and isinstance(tile[0], str) \
        and tile[0].startswith(("stack_", "craft_")) and isinstance(tile[2], list)


def build_graph(resolved_map: Dict[str, Any]) -> List[_Node]:
    n_layers = int(resolved_map.get("layer", 0))
    nodes: List[_Node] = []
    # (layer, x, y) -> node id that a lower tile depends on (board tile, or stack bottom inner)
    cover_node: Dict[Tuple[int, int, int], int] = {}
    board: List[Tuple[int, int, int, int]] = []  # (node id, layer, x, y) for cover lookups
    cols: Dict[int, int] = {}
    for li in range(n_layers):
        layer = resolved_map.get(f"layer_{li}") or {}
        cols[li] = int(layer.get("col", 0) or 0)
        tiles = layer.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue
        for pos, tile in tiles.items():
            x, y = (int(v) for v in pos.split("_"))
            if _is_container(tile):
                ids = tile[2][1].split("_") if len(tile[2]) >= 2 and isinstance(tile[2][1], str) else []
                cnt = int(tile[2][0])
                if len(ids) != cnt:
                    raise ValueError(f"unresolved container at layer_{li}/{pos}")
                inner_ids = []
                for k, kid in enumerate(ids):
                    nodes.append(_Node(kid, li, pos, k))
                    inner_ids.append(len(nodes) - 1)
                for k in range(cnt - 1):  # inner k blocked by inner k+1
                    nodes[inner_ids[k]].blockers.append(inner_ids[k + 1])
                cover_node[(li, x, y)] = inner_ids[0]
            else:
                nodes.append(_Node(tile[0], li, pos, None))
                nid = len(nodes) - 1
                cover_node[(li, x, y)] = nid
                board.append((nid, li, x, y))
    # layer covers for board tiles only (stack inner ignores upper layers)
    for nid, li, x, y in board:
        cur_par = li % 2
        for ui in range(li + 1, n_layers):
            if ui % 2 == cur_par:
                cells = [(x, y)]
            elif cols.get(ui, 0) > cols.get(li, 0):
                cells = [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]
            else:
                cells = [(x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y)]
            for cx, cy in cells:
                b = cover_node.get((ui, cx, cy))
                if b is not None:
                    nodes[nid].blockers.append(b)
    for i, nd in enumerate(nodes):
        nd.blockers = sorted(set(nd.blockers))
        for b in nd.blockers:
            nodes[b].children.append(i)
    return nodes


def _levels_and_ancestors(nodes: List[_Node]) -> Tuple[List[int], List[int]]:
    """peel level (longest blocker chain) and transitive ancestor count per node."""
    n = len(nodes)
    level = [-1] * n
    anc: List[Optional[set]] = [None] * n

    def visit(i: int) -> None:
        stack = [(i, False)]
        while stack:
            j, done = stack.pop()
            if level[j] >= 0:
                continue
            if not done:
                stack.append((j, True))
                for b in nodes[j].blockers:
                    if level[b] < 0:
                        stack.append((b, False))
            else:
                bl = nodes[j].blockers
                level[j] = 0 if not bl else 1 + max(level[b] for b in bl)
                s = set(bl)
                for b in bl:
                    s |= anc[b]  # type: ignore[operator]
                anc[j] = s

    for i in range(n):
        visit(i)
    return level, [len(a) for a in anc]  # type: ignore[arg-type]


def _pct(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def greedy_play(nodes: List[_Node]) -> Dict[str, Any]:
    """Deterministic greedy tray game on the cover graph (no RNG, gimmicks ignored).

    Priority among exposed tiles: completes a triple in tray > kind already in tray > exposes most
    tiles > lowest node id. Lose when tray holds TRAY tiles after matching.
    """
    n = len(nodes)
    remaining_blockers = [len(nd.blockers) for nd in nodes]
    exposed = {i for i in range(n) if remaining_blockers[i] == 0}
    tray: Dict[str, int] = {}
    occ = 0
    max_occ = 0
    crisis = 0
    turns = 0
    picked = 0
    while exposed:
        def key(i: int):
            k = nodes[i].kind
            c = tray.get(k, 0)
            frees = sum(1 for ch in nodes[i].children if remaining_blockers[ch] == 1)
            return (c == 2, c > 0, frees, -i)

        i = max(exposed, key=key)
        exposed.discard(i)
        picked += 1
        turns += 1
        for ch in nodes[i].children:
            remaining_blockers[ch] -= 1
            if remaining_blockers[ch] == 0:
                exposed.add(ch)
        k = nodes[i].kind
        tray[k] = tray.get(k, 0) + 1
        occ += 1
        if tray[k] == 3:
            tray[k] = 0
            occ -= 3
        max_occ = max(max_occ, occ)
        if occ >= TRAY - 1:
            crisis += 1
        if occ >= TRAY:
            break
    return {"greedyCleared": int(picked == n and occ == 0), "greedyMaxTray": max_occ,
            "greedyCrisisTurns": crisis, "greedyProgress": picked / n if n else 1.0}


def compute_features(resolved_map: Dict[str, Any]) -> Dict[str, float]:
    nodes = build_graph(resolved_map)
    level, anc = _levels_and_ancestors(nodes)
    by_kind: Dict[str, List[int]] = {}
    for i, nd in enumerate(nodes):
        by_kind.setdefault(nd.kind, []).append(i)

    tri_max_level, tri_spread, tri_gap = [], [], []
    for ids in by_kind.values():
        ids = sorted(ids, key=lambda i: (anc[i], level[i], i))  # exposure order proxy
        for t in range(0, len(ids) - len(ids) % 3, 3):
            tri = ids[t:t + 3]
            lv = [level[i] for i in tri]
            tri_max_level.append(max(lv))
            tri_spread.append(max(lv) - min(lv))
            tri_gap.append(anc[tri[2]] - anc[tri[0]])

    exposed = [i for i in range(len(nodes)) if level[i] == 0]
    exp_counts: Dict[str, int] = {}
    for i in exposed:
        exp_counts[nodes[i].kind] = exp_counts.get(nodes[i].kind, 0) + 1

    # stack concentration: max same-kind share per container, and same-kind adjacent pairs
    conc, adj = [], 0
    stacks: Dict[Tuple[int, str], List[str]] = {}
    for nd in nodes:
        if nd.inner is not None:
            stacks.setdefault((nd.layer, nd.pos), []).append(nd.kind)
    for kinds in stacks.values():
        cnt: Dict[str, int] = {}
        for k in kinds:
            cnt[k] = cnt.get(k, 0) + 1
        conc.append(max(cnt.values()) / len(kinds))
        adj += sum(1 for a, b in zip(kinds, kinds[1:]) if a == b)

    nt = max(1, len(tri_max_level))
    feats: Dict[str, float] = {
        "triMaxLevelMean": sum(tri_max_level) / nt,
        "triSpreadMean": sum(tri_spread) / nt,
        "triSpreadMax": max(tri_spread) if tri_spread else 0,
        "peelGapMean": sum(tri_gap) / nt,
        "peelGapP75": _pct(tri_gap, 0.75),
        "exposedTripleKinds": sum(1 for v in exp_counts.values() if v >= 3),
        "exposedPairKinds": sum(1 for v in exp_counts.values() if v == 2),
        "exposedKindDiversity": len(exp_counts),
        "stackConcMean": (sum(conc) / len(conc)) if conc else 0.0,
        "stackAdjSame": adj,
    }
    feats.update(greedy_play(nodes))
    return feats


# Orientation hint: + means "larger value expected easier" (used only for reporting; the pilot measures it).
FEATURE_EXPECTED_SIGN = {
    "triMaxLevelMean": -1, "triSpreadMean": -1, "triSpreadMax": -1, "peelGapMean": -1, "peelGapP75": -1,
    "exposedTripleKinds": +1, "exposedPairKinds": +1, "exposedKindDiversity": -1,
    "stackConcMean": -1, "stackAdjSame": +1,
    "greedyCleared": +1, "greedyMaxTray": -1, "greedyCrisisTurns": -1, "greedyProgress": +1,
}
