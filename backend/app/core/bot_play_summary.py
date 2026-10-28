"""Bot per-game summary with the same keys/definitions as the game `level_summary` event (spec v1).

Spec: claudedocs/difficulty_personalization/55_play_summary_telemetry_proposal_20261026.md §8 (sv=1).
No change to BotSimulator behaviour: `SummaryBot` only observes state at each decision (before the pick) and
at the end. It consumes no RNG and does not alter scoring/selection (verified by choice-sequence parity tests).

Segment: the bot always stops at the first terminal event (clear / first failure), which is the spec's frozen
segment. Bot has no boosters/revives -> seg_boost = 0. Auto-collect (cat help) picks are not picks (same as game).
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from app.core.bot_simulator import BotSimulator, GameState, TileEffectType

SV = 1
DANGER_FREE = 2  # spec §8-2: constant 2 (game _bufferDangerThreshold default)

# Bot terminal category -> game seg_end (UIFailReason enum names, §8-3 #3).
SEG_END_MAP = {
    "clear": "clear",
    "Normal": "Normal",
    "Bomb": "Bomb",
    "Grass": "Grass",      # game sends Grass / Grass_CantRevive raw (55 §9-7 #6); bot reports Grass (merged in analysis)
    "Chain": "Chain",      # game sends Chain / Chain_CantRevive raw; bot reports Chain (merged in analysis)
    "Ice": "Ice",
    "MaxMoves": "bot_max_moves",  # bot-only safety cap; no game counterpart (TimeOver is a different mechanic)
    "NoMoves": "bot_no_moves",    # bot-only (no selectable move); no game counterpart
    "unfinished": "bot_unfinished",
}
GAME_SEG_END = ("clear", "quit", "Normal", "Ice", "Grass", "Chain", "Grass_CantRevive", "Chain_CantRevive", "Bomb", "TimeOver")


def _bomb_key(tile) -> str:
    return f"{tile.layer_idx}_{tile.position_key}"


def _grass_total(state: GameState) -> int:
    return sum(int(t.effect_data.get("remaining", 0) or 0) for layer in state.tiles.values() for t in layer.values()
               if not t.picked and t.effect_type == TileEffectType.GRASS and int(t.effect_data.get("remaining", 0) or 0) > 0)


def _locked(state: GameState) -> int:
    return sum(1 for s in state.dock if s.is_locked)


def _cap(state: GameState) -> int:
    return sum(1 for s in state.dock if not s.is_locked)


def map_presence(state: GameState) -> Dict[str, bool]:
    """Gimmick presence at map load (§8-2: any tile/locked slot -> present)."""
    tiles = [t for layer in state.tiles.values() for t in layer.values()] + list(state.stacked_tiles.values())
    return dict(
        bomb=bool(state.bomb_tiles) or any(t.effect_type == TileEffectType.BOMB for t in tiles),
        grass=any(t.effect_type == TileEffectType.GRASS for t in tiles),
        # 55 §9-7 #5: lock = unlockTile>0 (locked dock slots at load) or any key tile, incl. container contents
        lock=_locked(state) > 0 or any(t.tile_type in ("key", "t16") for t in tiles),
        container=bool(state.craft_boxes) or any(t.is_stack_tile or t.is_craft_tile for t in tiles),
    )


class SummaryBot(BotSimulator):
    """BotSimulator that logs one record per pick (pre-pick snapshot). Behaviour unchanged."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.pick_log: List[dict] = []

    def _v23_auto_collect_after_move(self, state, picked_types):
        # 55 §9-7 #2: bombs collected by auto-collect (cat help) also count as defused, with their count then.
        before = {}
        for key, rem in state.bomb_tiles.items():
            p = key.split("_")
            t = state.tiles.get(int(p[0]), {}).get(f"{p[1]}_{p[2]}") if len(p) >= 3 else None
            if t is not None and not t.picked:
                before[key] = (t, int(rem))
        out = super()._v23_auto_collect_after_move(state, picked_types)
        if self.pick_log:
            self.pick_log[-1].setdefault("bomb_auto", []).extend(v for t, v in before.values() if t.picked)
        return out

    def _select_move_with_profile(self, moves, state, profile):
        sel = super()._select_move_with_profile(moves, state, profile)
        if sel is not None:
            self.pick_log.append(self._snapshot(state, sel))
        return sel

    def _snapshot(self, state: GameState, move) -> dict:
        ts = move.tile_state
        dock = Counter(t.tile_type for t in state.dock_tiles)
        bombs_picked = []
        for tile in [ts] + [state.tiles.get(li, {}).get(lp) for li, lp in (move.linked_tiles or [])]:
            if tile is not None and not tile.picked and tile.effect_type == TileEffectType.BOMB:
                key = _bomb_key(tile)
                if key in state.bomb_tiles:
                    bombs_picked.append(int(state.bomb_tiles[key]))
        return dict(
            occ=len(state.dock_tiles), cap=_cap(state), n=dock.get(move.tile_type, 0),
            container=bool(ts is not None and (ts.is_stack_tile or ts.is_craft_tile)),
            bomb_defuse=bombs_picked, grass_total=_grass_total(state), locked=_locked(state),
        )


def summarize(pick_log: List[dict], start: GameState, end: GameState, end_category: str,
              level: int, run_id: str) -> dict:
    """Build the level_summary dict (game keys) from a SummaryBot pick log and the start/end states."""
    pres = map_presence(start)
    picks = len(pick_log)
    frees = [p["cap"] - p["occ"] for p in pick_log]
    danger = [f <= DANGER_FREE for f in frees]
    tail = 0
    for d in reversed(danger):
        if not d:
            break
        tail += 1
    end_counts = Counter(t.tile_type for t in end.dock_tiles)

    # after-pick values: pick k's effect is visible at pick k+1's snapshot, or at the end state
    grass_seq = [p["grass_total"] for p in pick_log] + [_grass_total(end)]
    lock_seq = [p["locked"] for p in pick_log] + [_locked(end)]
    grass_first = next((k + 1 for k in range(picks) if grass_seq[k + 1] < grass_seq[k]), 0)
    key_unlock = next((k + 1 for k in range(picks) if lock_seq[k + 1] < lock_seq[k]), 0)
    cont_first = next((k + 1 for k, p in enumerate(pick_log) if p["container"]), 0)

    bomb_events = [v for p in pick_log for v in p["bomb_defuse"] + p.get("bomb_auto", [])]
    if end_category == "Bomb":
        bomb_events.append(0)
    if not pres["bomb"]:
        bomb_left_min = -1
    elif not bomb_events:
        bomb_left_min = -2
    else:
        bomb_left_min = min(bomb_events)

    return {
        "level": int(level),
        "heart_run_id": run_id,
        "sv": SV,
        "seg_end": SEG_END_MAP.get(end_category, f"bot_{end_category}"),
        "picks": picks,
        "seg_boost": 0,
        "pick_new": sum(1 for p in pick_log if p["n"] == 0),
        "pick_match": sum(1 for p in pick_log if p["n"] == 2),
        "min_free": min(frees) if frees else -1,
        "danger_picks": sum(danger),
        "danger_tail": tail,
        "end_pairs": sum(1 for v in end_counts.values() if v == 2),
        "bomb_left_min": bomb_left_min,
        "grass_first": grass_first if pres["grass"] else -1,
        "grass_left": _grass_total(end) if pres["grass"] else -1,
        "key_unlock": key_unlock if pres["lock"] else -1,
        "cont_first": cont_first if pres["container"] else -1,
    }


def seg_end_category(bot: BotSimulator, end: GameState) -> str:
    """Bot terminal category in the game's failure order (55 §9-7 #4): Bomb > Normal > Grass/Chain/Ice.
    (Game: CheckGameFail checks bombs first, then dock full; CheckCantUncover afterwards.)"""
    if not end.failed:
        return "clear" if end.cleared else "unfinished"
    for key, rem in end.bomb_tiles.items():
        p = key.split("_")
        t = end.tiles.get(int(p[0]), {}).get(f"{p[1]}_{p[2]}") if len(p) >= 3 else None
        if rem <= 0 and t is not None and not t.picked:
            return "Bomb"
    if bot._is_dock_full(end):
        return "Normal"
    if bot._check_grass_impossible(end):
        return "Grass"
    if bot._check_ice_impossible(end):
        return "Ice"
    if bot._check_chain_impossible(end):
        return "Chain"
    if end.moves_used >= end.max_moves:
        return "MaxMoves"
    return "NoMoves"


def check_ranges(s: dict) -> List[str]:
    """§8-7 QA value-range rules applied to a bot summary; returns violations."""
    bad = []
    p = s["picks"]
    for k in ("pick_new", "pick_match", "danger_picks", "danger_tail"):
        if not 0 <= s[k] <= p:
            bad.append(k)
    if s["pick_new"] + s["pick_match"] > p:
        bad.append("new+match>picks")
    if not s["danger_tail"] <= s["danger_picks"]:
        bad.append("tail>danger")
    if s["seg_end"] == "Normal" and s["danger_tail"] < 1:
        bad.append("normal_without_tail")
    if p == 0 and s["min_free"] != -1:
        bad.append("min_free")
    for k in ("grass_first", "key_unlock", "cont_first"):
        if not -1 <= s[k] <= p:
            bad.append(k)
    if s["bomb_left_min"] < -2:
        bad.append("bomb_left_min")
    if s["grass_left"] < -1:
        bad.append("grass_left")
    return bad


def play_and_summarize(bot: SummaryBot, start: GameState, profile, seed: int, level: int, run_id: str,
                       fail_reason=None) -> dict:
    """Play one game from a copy of `start` and return its summary. Default category = seg_end_category
    (game failure order); pass `fail_reason(bot, end)` only to reproduce the legacy bot ordering."""
    fail_reason = fail_reason or seg_end_category
    bot.pick_log = []
    bot._rng.seed(seed)
    end = bot._play_game(bot._fast_copy_state(start), profile)
    category = fail_reason(bot, end)
    out = summarize(bot.pick_log, start, end, category, level, run_id)
    out["_bot_category"] = category
    return out
