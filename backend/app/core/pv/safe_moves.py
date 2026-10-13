"""Safe-move metric B (doc 11): share of legal moves that keep a level solvable, along solution paths.

For a concrete board (seed already assigned):
  1. prove the start state solvable with a best-first search (same rules as core/solver.py — BotSimulator
     primitives, import only);
  2. walk K random solution paths: at every state, judge each legal move's child state
     SOLVABLE / IMPOSSIBLE / UNCERTAIN (per-child node budget), then step to a uniformly random safe child;
  3. aggregate per-point ratios safe / (safe + unsafe) into candidate metrics.

Caching (one analyzer per board):
  - SOLVABLE: every state on a witness chain is solvable -> cached.
  - IMPOSSIBLE: an exhausted search proves every visited state unsolvable -> all cached.
  - UNCERTAIN is cached per state for reuse but never trusted as a conclusion.

Trust: the solver core does not run per-turn effects (bomb/curtain/frog/teleport, blocked craft re-emission;
doc 03 §1) -> boards with those gimmicks are flagged `untrusted`; craft boards are flagged `craftRisk`.
"""
from __future__ import annotations

import copy as _copy
import heapq
import math
import random
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from app.core.bot_simulator import BotSimulator, DockSlot, GameState, TileEffectType, TileState
from app.core.solver import _remaining_count, _state_signature

S, I, U = "S", "I", "U"
UNTRUSTED_EFFECTS = ("bomb", "curtain", "frog", "teleport", "unknown")


def board_flags(level_json: Dict[str, Any]) -> Dict[str, Any]:
    effects, craft = set(), False
    for k, layer in level_json.items():
        if not (k.startswith("layer_") and isinstance(layer, dict) and isinstance(layer.get("tiles"), dict)):
            continue
        for t in layer["tiles"].values():
            if not (isinstance(t, list) and t):
                continue
            if isinstance(t[0], str) and t[0].startswith("craft_"):
                craft = True
            if len(t) > 1 and isinstance(t[1], str) and t[1]:
                effects.add(t[1].split("_")[0].lower())
    bad = sorted(e for e in effects if e.startswith(UNTRUSTED_EFFECTS))
    return {"effects": sorted(effects), "untrusted": bool(bad), "untrustedEffects": bad, "craftRisk": craft}


def _tile_copy(t: TileState) -> TileState:
    n = object.__new__(TileState)
    d = t.__dict__.copy()
    d["effect_data"] = _copy.copy(t.effect_data) if t.effect_data else {}
    n.__dict__.update(d)
    return n


def _shallow(t: TileState) -> TileState:
    n = object.__new__(TileState)
    n.__dict__.update(t.__dict__)
    return n


def fast_copy(state) -> GameState:
    """Same result as core `solver._copy_state` (= BotSimulator._fast_copy_state + mid-game restore), faster.

    Profiling (doc 11 §4): ~78% of the time went to `_fast_copy_state`, which re-copies the precomputed
    blocking maps (never mutated after `_precompute_blocking_map`) and rebuilds the blocking cache by string
    parsing. Here the maps are shared and the cache starts empty (it is filled lazily by
    `_is_blocked_by_upper`, and `_apply_move` clears it anyway). Everything else mirrors the core copy,
    including its resets (teleport counter, curtain memory). Equivalence: tests/test_pv_safe_moves.py.
    """
    n = GameState()
    # picked board tiles are shared (never read except `.picked`; verified by the equivalence test)
    n.tiles = {li: {pos: (t if t.picked else _tile_copy(t)) for pos, t in layer.items()}
               for li, layer in state.tiles.items()}
    n.layer_cols = state.layer_cols.copy()
    n.dock = [DockSlot(index=s.index, is_locked=s.is_locked) for s in state.dock]
    n.dock_tiles = [_shallow(t) for t in state.dock_tiles]
    n.goals_remaining = state.goals_remaining.copy()
    n.moves_used = state.moves_used
    n.max_moves = state.max_moves
    n.combo_count = getattr(state, "combo_count", 0)
    n.total_tiles_cleared = getattr(state, "total_tiles_cleared", 0)
    n.max_dock_slots = state.max_dock_slots
    n.link_pairs = state.link_pairs.copy()
    n.frog_positions = state.frog_positions.copy()
    n.bomb_tiles = state.bomb_tiles.copy()
    n.curtain_tiles = state.curtain_tiles.copy()
    n.ice_tiles = state.ice_tiles.copy()
    n.craft_boxes = {k: _copy.deepcopy(v) for k, v in state.craft_boxes.items()} if state.craft_boxes else {}
    n.teleport_click_count = 0
    n.teleport_tiles = state.teleport_tiles.copy() if state.teleport_tiles else []
    n.tile_type_overrides = state.tile_type_overrides.copy()
    n.all_tile_type_counts = state.all_tile_type_counts.copy()
    n._max_layer_idx = state._max_layer_idx
    n.curtain_memory = {}
    n.stacked_tiles = {k: _shallow(v) for k, v in state.stacked_tiles.items()} if state.stacked_tiles else {}
    if state._blocking_map is not None:
        n._blocking_map = state._blocking_map
        n._reverse_blocking_map = state._reverse_blocking_map
    return n


def ext_signature(state) -> Tuple:
    """Solver signature + types of hidden stack/craft inner tiles (needed once worlds differ only there)."""
    inner = tuple(sorted((k, t.tile_type) for k, t in state.stacked_tiles.items() if not t.picked))
    return (_state_signature(state), inner)


# ── information-limited variant B′ (determinization) ─────────────────────────────────────────────
HIDE_MODES = ("occluded", "covered")


def _fully_occluded(sim: BotSimulator, state, t: TileState) -> bool:
    """Tile completely hidden under unpicked upper tiles: a same-parity tile on the same cell, or all four
    quadrants covered by opposite-parity tiles (half-offset grid, same offsets as `_is_blocked_by_upper`)."""
    quads = set()
    for ul in range(t.layer_idx + 1, state._max_layer_idx + 1):
        layer = state.tiles.get(ul)
        if not layer:
            continue
        if ul % 2 == t.layer_idx % 2:
            u = layer.get(f"{t.x_idx}_{t.y_idx}")
            if u is not None and not u.picked:
                return True
            continue
        bigger = state.layer_cols.get(ul, 7) > state.layer_cols.get(t.layer_idx, 7)
        offs = BotSimulator.BLOCKING_OFFSETS_UPPER_BIGGER if bigger else BotSimulator.BLOCKING_OFFSETS_UPPER_SMALLER
        for dx, dy in offs:
            u = layer.get(f"{t.x_idx + dx}_{t.y_idx + dy}")
            if u is not None and not u.picked:
                quads.add((dx, dy) if bigger else (dx + 1, dy + 1))
        if len(quads) == 4:
            return True
    return False


def hidden_tiles(sim: BotSimulator, state, mode: str) -> List[TileState]:
    """Tiles whose type the player cannot see now.

    Both modes: stack/craft inner tiles not on the board, and covered `unknown` tiles (game shows "?").
    occluded (game-faithful): + board tiles completely hidden under upper tiles. Covered-but-partly-visible
                              tiles are drawn dimmed with their type in the client (TileEffect CheckMask).
    covered (upper bound):    + every covered (blocked) board tile.
    """
    out, on_board = [], set()
    for layer in state.tiles.values():
        for t in layer.values():
            if t.picked:
                continue
            if t.original_full_key:
                on_board.add(t.original_full_key)
            if not sim._is_blocked_by_upper(state, t):
                continue
            if mode == "covered" or t.effect_type == TileEffectType.UNKNOWN or _fully_occluded(sim, state, t):
                out.append(t)
    out += [t for k, t in state.stacked_tiles.items() if not t.picked and k not in on_board]
    return out


def determinize(sim: BotSimulator, state, mode: str, rng: random.Random):
    """A world consistent with what the player sees: hidden tiles' types permuted (counts preserved)."""
    w = fast_copy(state)
    hid = hidden_tiles(sim, w, mode)
    types = [t.tile_type for t in hid]
    rng.shuffle(types)
    for t, ty in zip(hid, types):
        t.tile_type = ty
    return w, len(hid)


class SafeMoveAnalyzer:
    def __init__(self, level_json: Dict[str, Any], node_budget: int = 3000, time_cap_s: float = 20.0,
                 root_node_budget: int = 20000, ext_sig: bool = False):
        self.sim = BotSimulator()
        total = sum(len(l["tiles"]) for k, l in level_json.items()
                    if k.startswith("layer_") and isinstance(l, dict) and isinstance(l.get("tiles"), dict))
        lvl = dict(level_json)
        lvl["max_moves"] = total + 100  # same as solver: structural solvability, no move limit
        self.total_tiles = total
        self.root = self.sim._create_initial_state(lvl, lvl["max_moves"])
        self.sim._precompute_blocking_map(self.root)
        self.node_budget = node_budget
        self.root_node_budget = root_node_budget
        self.time_cap_s = time_cap_s
        self.cache: Dict[Tuple, str] = {}
        self.sig = ext_signature if ext_sig else _state_signature
        self.nodes = 0
        self.solves = 0

    # ── primitives ────────────────────────────────────────────────────────────────────────────
    def apply(self, state, move):
        """Child after `move` (by position) or None. cleared/failed flags set."""
        child = fast_copy(state)
        ct = child.tiles.get(move.layer_idx, {}).get(move.position)
        if ct is None:
            return None
        try:
            self.sim._apply_move(child, replace(move, tile_state=ct))
        except Exception:  # noqa: BLE001 — same tolerance as core solver
            return None
        self.sim._is_game_over(child)
        return child

    def children(self, state) -> List[Any]:
        """Child states of every legal move (cleared/failed flags set). Move order = legal-move order."""
        return [c for c in (self.apply(state, m) for m in self.sim._get_available_moves(state)) if c is not None]

    def judge(self, state, node_budget: Optional[int] = None) -> str:
        if state.cleared or _remaining_count(state) == 0:
            return S
        if state.failed:
            return I
        sig = self.sig(state)
        got = self.cache.get(sig)
        if got in (S, I):
            return got
        v = self._search(state, sig, node_budget or self.node_budget)
        self.cache[sig] = v
        return v

    def _search(self, start, start_sig, budget: int) -> str:
        """Best-first (fewest remaining tiles) like core solver, with S/I cache pruning and propagation."""
        self.solves += 1
        parent: Dict[Tuple, Optional[Tuple]] = {start_sig: None}
        heap = [(_remaining_count(start), 0, start, start_sig)]
        counter = nodes = 0
        t0 = time.monotonic()

        def mark_chain(sig):
            while sig is not None:
                self.cache[sig] = S
                sig = parent[sig]

        while heap:
            if nodes >= budget or (nodes % 64 == 0 and time.monotonic() - t0 > self.time_cap_s):
                self.nodes += nodes
                return U
            _, _, cur, cur_sig = heapq.heappop(heap)
            nodes += 1
            for child in self.children(cur):
                if child.cleared:
                    mark_chain(cur_sig)
                    self.nodes += nodes
                    return S
                if child.failed:
                    continue
                sig = self.sig(child)
                if sig in parent:
                    continue
                c = self.cache.get(sig)
                if c == I:
                    continue
                parent[sig] = cur_sig
                if c == S:
                    mark_chain(sig)
                    self.nodes += nodes
                    return S
                counter += 1
                heapq.heappush(heap, (_remaining_count(child), counter, child, sig))
        for sig in parent:  # exhausted: every visited state is unsolvable
            self.cache[sig] = I
        self.nodes += nodes
        return I

    # ── paths ────────────────────────────────────────────────────────────────────────────────
    def walk(self, rng: random.Random, deadline: float = math.inf) -> Dict[str, Any]:
        state = self.root
        points = []
        end = "cleared"
        while True:
            if time.monotonic() > deadline:
                end = "wallCap"  # partial path (cost cap)
                break
            kids = self.children(state)
            if not kids:
                end = "noMove"
                break
            safe_kids, unsafe, unc = [], 0, 0
            for ch in kids:
                v = self.judge(ch)
                if v == S:
                    safe_kids.append(ch)
                elif v == I:
                    unsafe += 1
                else:
                    unc += 1
            points.append((len(kids), len(safe_kids), unsafe, unc))
            if not safe_kids:
                end = "stuck"  # only uncertain children left
                break
            state = rng.choice(safe_kids)
            if state.cleared:
                break
        return {"points": points, "end": end}


def path_metrics(points: List[Tuple[int, int, int, int]]) -> Dict[str, Any]:
    """points: (legal, safe, unsafe, uncertain) per decision point."""
    ratios = [s / (s + u) for _, s, u, _ in points if s + u > 0]
    n_eval = sum(p[0] for p in points)
    unc = sum(p[3] for p in points)
    low = sorted(ratios)[:max(1, math.ceil(0.1 * len(ratios)))] if ratios else []
    log10p = sum(math.log10(s / (s + u)) for _, s, u, _ in points if s + u > 0 and s > 0)
    return {
        "nPoints": len(points),
        "meanSafe": (sum(ratios) / len(ratios)) if ratios else None,           # (a)
        "low10Safe": (sum(low) / len(low)) if low else None,                    # (b) mean of lowest 10% points
        "bottle1": sum(1 for _, s, u, _ in points if s <= 1 and u >= 1),        # (c) ≤1 safe with a real trap
        "bottle2": sum(1 for _, s, u, _ in points if s <= 2 and u >= 1),
        "uncertainFrac": (unc / n_eval) if n_eval else None,                    # (d)
        "log10RandClear": log10p,                                               # (e) Π safe-ratio along path
    }


def analyze_board(level_json: Dict[str, Any], k_paths: int = 4, seed: int = 1, node_budget: int = 3000,
                  root_node_budget: int = 20000, time_cap_s: float = 20.0, wall_cap_s: float = 600.0) -> Dict[str, Any]:
    """Metric B for one concrete board. Averages over K random solution paths (shared cache)."""
    t_start = time.monotonic()
    flags = board_flags(level_json)
    an = SafeMoveAnalyzer(level_json, node_budget=node_budget, time_cap_s=time_cap_s,
                          root_node_budget=root_node_budget)
    out: Dict[str, Any] = {"tiles": an.total_tiles, **flags, "k": k_paths, "nodeBudget": node_budget, "impl": "fastcopy"}
    root_v = an.judge(an.root, node_budget=root_node_budget)
    out["root"] = root_v
    if root_v != S:
        out.update({"ok": False, "sec": round(time.monotonic() - t_start, 2), "nodes": an.nodes})
        return out
    rng = random.Random(seed)
    paths = []
    for _ in range(k_paths):
        if paths and time.monotonic() - t_start > wall_cap_s:
            break
        w = an.walk(rng, deadline=t_start + wall_cap_s)
        paths.append({**path_metrics(w["points"]), "end": w["end"]})
    agg: Dict[str, Any] = {}
    for key in ("meanSafe", "low10Safe", "bottle1", "bottle2", "uncertainFrac"):
        vals = [p[key] for p in paths if p[key] is not None]
        agg[key] = (sum(vals) / len(vals)) if vals else None
    # (e) unbiased estimate of a uniform-random player's clear probability = mean of Π over random safe paths
    # (exact only when no uncertain children; uncertain ones are excluded from the denominators)
    vals = [10 ** p["log10RandClear"] for p in paths]
    agg["log10RandClear"] = math.log10(sum(vals) / len(vals)) if vals and sum(vals) > 0 else None
    out.update({"ok": True, **agg, "paths": paths, "pathsDone": len(paths),
                "stuckPaths": sum(1 for p in paths if p["end"] != "cleared"),
                "nodes": an.nodes, "solves": an.solves, "cacheSize": len(an.cache),
                "sec": round(time.monotonic() - t_start, 2)})
    return out


def _ratio(s: int, u: int) -> Optional[float]:
    return s / (s + u) if s + u > 0 else None


def _mean(xs: List[Optional[float]]) -> Optional[float]:
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def info_metrics(points: List[Dict[str, Any]], modes=HIDE_MODES) -> Dict[str, Any]:
    """B (all points / sampled points / excluding immediately-failing moves) and B′ per hiding mode."""
    rb = [_ratio(p["safe"], p["unsafe"]) for p in points]
    rnt = [_ratio(p["safe"], p["unsafe"] - p["imm"]) for p in points]
    smp = [p for p in points if modes[0] in p]
    out = {
        "nPoints": len(points), "nSampled": len(smp),
        "B": _mean(rb),
        "B_nonTrivial": _mean(rnt),                                    # immediate dock/gimmick fails removed
        "B_sat1": _mean([1.0 if r == 1.0 else 0.0 for r in rb if r is not None]),      # share of points at 1.0
        "B_ntSat1": _mean([1.0 if r == 1.0 else 0.0 for r in rnt if r is not None]),
        "B_sampled": _mean([_ratio(p["safe"], p["unsafe"]) for p in smp]),
        "immFrac": (sum(p["imm"] for p in points) / sum(p["legal"] for p in points)) if points else None,
    }
    for m in modes:
        rr = [_ratio(p[m]["safe"], p[m]["unsafe"]) for p in smp]
        out[f"Bp_{m}"] = _mean(rr)
        out[f"Bp_{m}_sat1"] = _mean([1.0 if r == 1.0 else 0.0 for r in rr if r is not None])
        out[f"Bp_{m}_unc"] = (sum(p[m]["unc"] for p in smp) / sum(p["legal"] for p in smp)) if smp else None
        out[f"Bp_{m}_hidden"] = _mean([p[m]["hidden"] for p in smp])
    return out


def analyze_board_info(level_json: Dict[str, Any], k_paths: int = 2, points_per_path: int = 6, m_worlds: int = 6,
                       thr: float = 0.8, modes=HIDE_MODES, seed: int = 1, node_budget: int = 3000,
                       root_node_budget: int = 20000, time_cap_s: float = 20.0,
                       wall_cap_s: float = 900.0, world_node_budget: int = 1000) -> Dict[str, Any]:
    """B and information-limited B′ on the same random solution paths.

    B′ (per sampled point, per hiding mode): build M worlds consistent with what the player sees (hidden tiles'
    types permuted); a move is safe′ if, among worlds where it was decided, ≥ thr keep it solvable, unsafe′ if
    fewer, uncertain′ if fewer than M/2 worlds were decided. Paths follow the TRUE board (random truly-safe move).
    """
    t_start = time.monotonic()
    an = SafeMoveAnalyzer(level_json, node_budget=node_budget, time_cap_s=time_cap_s,
                          root_node_budget=root_node_budget, ext_sig=True)
    out: Dict[str, Any] = {"tiles": an.total_tiles, **board_flags(level_json), "k": k_paths, "M": m_worlds,
                           "thr": thr, "pointsPerPath": points_per_path, "nodeBudget": node_budget,
                           "worldNodeBudget": world_node_budget,
                           "impl": "fastcopy+info"}
    root_v = an.judge(an.root, node_budget=root_node_budget)
    out["root"] = root_v
    if root_v != S:
        out.update({"ok": False, "sec": round(time.monotonic() - t_start, 2), "nodes": an.nodes})
        return out
    rng, wrng = random.Random(seed), random.Random(seed + 1)
    sim = an.sim
    paths = []
    for _ in range(k_paths):
        if paths and time.monotonic() - t_start > wall_cap_s:
            break
        span = max(1, an.total_tiles - 3)   # path length = tile count; skip the trivial last moves
        sample = set(rng.sample(range(span), min(points_per_path, span)))
        state, pts, end, step = an.root, [], "cleared", 0
        while True:
            if time.monotonic() - t_start > wall_cap_s:
                end = "wallCap"
                break
            kids = [(m, c) for m in sim._get_available_moves(state) for c in [an.apply(state, m)] if c is not None]
            if not kids:
                end = "noMove"
                break
            verd = [an.judge(c) for _, c in kids]
            pt = {"step": step, "legal": len(kids), "imm": sum(1 for _, c in kids if c.failed),
                  "safe": verd.count(S), "unsafe": verd.count(I), "unc": verd.count(U)}
            if step in sample:
                for mode in modes:
                    worlds = [determinize(sim, state, mode, wrng) for _ in range(m_worlds)]
                    sp = up = uc = 0
                    for m, _c in kids:
                        cs = ci = 0
                        for w, _h in worlds:
                            wc = an.apply(w, m)
                            v = U if wc is None else an.judge(wc, node_budget=world_node_budget)
                            cs += v == S
                            ci += v == I
                        if cs + ci < m_worlds / 2:
                            uc += 1
                        elif cs / (cs + ci) >= thr:
                            sp += 1
                        else:
                            up += 1
                    pt[mode] = {"safe": sp, "unsafe": up, "unc": uc, "hidden": worlds[0][1]}
            pts.append(pt)
            safe_kids = [c for (_m, c), v in zip(kids, verd) if v == S]
            if not safe_kids:
                end = "stuck"
                break
            state = rng.choice(safe_kids)
            step += 1
            if state.cleared:
                break
        paths.append({"end": end, "points": pts})
    allpts = [p for pp in paths for p in pp["points"]]
    out.update({"ok": True, **info_metrics(allpts, modes),
                "paths": [{"end": pp["end"], **info_metrics(pp["points"], modes)} for pp in paths],
                "points": allpts, "pathsDone": len(paths),
                "stuckPaths": sum(1 for pp in paths if pp["end"] != "cleared"),
                "nodes": an.nodes, "solves": an.solves, "cacheSize": len(an.cache),
                "sec": round(time.monotonic() - t_start, 2)})
    return out
