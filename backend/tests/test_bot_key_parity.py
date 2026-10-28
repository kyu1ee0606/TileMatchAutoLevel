"""Key tile / dock lock parity with the game client (2026-10-27, user-approved rule-parity fix).

Game rule (sp_meowsgarden, read-only):
- keys (id 16) are assigned only to t0 slots by ShuffleEmptyTiles -> DistributeTiles(specifiedCount=xUnlockTile)
  (DB_Level.cs:1167-1287, 1372-1499); explicit keys are never subtracted.
- locked dock slots = (all key tiles on the board, container inner included) // 3 (TileGroup.cs:1335-1338).
- a 3-key match frees one slot (Dock.cs:1980-1982, 904-916).
Golden: backend/tests/golden/pv_t0 (client code run through tools/pv_golden).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.bot_simulator import BotSimulator

GOLDEN = Path(__file__).parent / "golden" / "pv_t0"


def _tid(s: str) -> int:
    s = str(s)
    if s in ("key", "t16"):
        return 16
    return int(s[1:]) if s.startswith("t") and s[1:].isdigit() else -1


def _bot_slot_types(st):
    by = {}
    seen = set()
    for t in [x for lay in st.tiles.values() for x in lay.values()] + list(st.stacked_tiles.values()):
        if id(t) in seen:
            continue
        seen.add(id(t))
        if t.stack_index >= 0 and (t.is_stack_tile or t.is_craft_tile):
            layer, x, y, i = (t.original_full_key or t.full_key).split("_")
            by[(f"layer_{layer}", f"{x}_{y}", int(i))] = _tid(t.tile_type)
        else:
            by[(f"layer_{t.layer_idx}", t.position_key, -1)] = _tid(t.tile_type)
    return by


def _level_json(row: dict, run: dict) -> dict:
    r = dict(row)
    r.update(run)
    lj = json.loads(json.dumps(r["map"]))
    nums = [int(k[6:]) for k in lj if k.startswith("layer_") and k[6:].isdigit()]
    lj["layer"] = max(int(lj.get("layer") or 0), max(nums, default=-1) + 1)
    lj["randSeed"] = r.get("randSeed")
    lj["useTileCount"] = r.get("useTileCount")
    lj["unlockTile"] = int(float(r.get("unlockTile") or 0))
    lj["xShuffleTile"] = r.get("shuffleTile") or 0
    lj["xTypeImbalance"] = r.get("typeImbalance") or 0
    return lj


def _golden_key_runs():
    out = []
    for f in sorted((GOLDEN / "inputs").glob("*.json")):
        inp = json.loads(f.read_text())
        exp = json.loads((GOLDEN / "expected" / f.name).read_text())
        runs = inp.get("runs") or [{}]
        for i, (run, res) in enumerate(zip(runs, exp["results"])):
            u = run.get("unlockTile", inp["row"].get("unlockTile"))
            try:
                u = int(float(u or 0))
            except (TypeError, ValueError):
                continue
            if u > 0 and res.get("types") is not None:
                out.append(pytest.param(inp["row"], run, res, id=f"{f.stem}#{i}"))
    return out


@pytest.mark.parametrize("row,run,res", _golden_key_runs())
def test_key_levels_match_client_golden(row, run, res):
    lj = _level_json(row, run)
    if int(lj["useTileCount"] or 0) <= 0:
        pytest.skip("useTileCount<=0 needs the skin table (not ported) -> legacy path")
    st = BotSimulator()._create_initial_state(lj, 300)
    by = _bot_slot_types(st)
    for pos, t in zip(res["positions"], res["types"]):
        assert by.get(tuple(pos)) == t, pos
    total16 = int((res["selfCheck"].get("totalPerType") or {}).get("16", 0))
    assert sum(1 for s in st.dock if s.is_locked) == total16 // 3
    assert st.max_dock_slots == 7 - total16 // 3


def test_golden_has_key_runs():
    assert len(_golden_key_runs()) >= 4


def test_unlock_zero_never_uses_client_resolver(monkeypatch):
    inp = json.loads((GOLDEN / "inputs" / "s02_multilayer_pure_t0.json").read_text())
    lj = _level_json(inp["row"], {"randSeed": 1, "unlockTile": 0})

    def boom(*a, **k):
        raise AssertionError("resolver must not run for unlockTile=0")

    monkeypatch.setattr(BotSimulator, "_client_key_resolve", boom)
    st = BotSimulator()._create_initial_state(lj, 300)
    assert not any(s.is_locked for s in st.dock) and st.max_dock_slots == 7


def test_seed_zero_falls_back_to_legacy_path():
    inp = json.loads((GOLDEN / "inputs" / "s07_unlocktile_pure.json").read_text())
    lj = _level_json(inp["row"], {"randSeed": 0, "unlockTile": 1})
    assert BotSimulator()._client_key_resolve(lj, 1) == (None, 0)
    st = BotSimulator()._create_initial_state(lj, 300)
    assert sum(1 for s in st.dock if s.is_locked) == 1


def _stack_key_level():
    # L138-shaped: explicit keys inside one stack (bottom->top), no t0, unlockTile 1
    tiles = {"0_0": ["stack_n", "", [6, "t5_key_t9_t8_key_key"]]}
    for i, t in enumerate(["t5", "t5", "t9", "t9", "t8", "t8"]):
        tiles[f"{i + 1}_1"] = [t, ""]
    return {"layer": 1, "layer_0": {"col": "8", "row": "8", "tiles": tiles, "num": str(len(tiles))},
            "randSeed": 612053, "useTileCount": 11, "unlockTile": 1}


def test_explicit_stack_keys_lock_and_unlock():
    b = BotSimulator()
    st = b._create_initial_state(_stack_key_level(), 100)
    b._precompute_blocking_map(st)
    assert sum(1 for s in st.dock if s.is_locked) == 1 and st.max_dock_slots == 6
    order = []
    for _ in range(5):          # key, key, t8, t9, key from the stack top
        top = st.tiles[0]["0_0"]
        mv = next(m for m in b._get_available_moves(st) if m.tile_state is top)
        order.append(mv.tile_type)
        b._apply_move(st, mv)
    assert order == ["key", "key", "t8", "t9", "key"]
    assert sum(1 for s in st.dock if s.is_locked) == 0 and st.max_dock_slots == 7
    assert sorted(t.tile_type for t in st.dock_tiles) == ["t8", "t9"]


# ─────────────────────────────────────────────────────────────────────────────
# Codex review 2026-10-27: legacy invariance (unlockTile=0), forced fallback, t16/effect-key mix
# Golden = pre-fix core 4196e75a outputs (scripts/bot_key_legacy_snapshot_20261027.py)
# ─────────────────────────────────────────────────────────────────────────────
import importlib.util as _ilu  # noqa: E402
import sys as _sys  # noqa: E402

_SNAP_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bot_key_legacy_snapshot_20261027.py"
_spec = _ilu.spec_from_file_location("bot_key_legacy_snapshot_20261027", _SNAP_SCRIPT)
_SNAP = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_SNAP)
_LEGACY = json.loads((Path(__file__).parent / "golden" / "key_parity" / "legacy_4196e75a.json").read_text())
_CASES = {cid: (row, run, m) for cid, row, run, m in _SNAP.cases()}


def test_legacy_snapshot_is_from_prefix_core():
    assert _LEGACY["source_sha256"].startswith("4196e75a")
    assert set(_LEGACY["cases"]) == set(_CASES)
    assert sum(1 for v in _LEGACY["cases"].values() if v["unlock"] == 0) >= 2000


@pytest.mark.parametrize("cid", sorted(c for c, v in _LEGACY["cases"].items() if v["unlock"] == 0))
def test_unlock_zero_identical_to_prefix_core(cid):
    """unlockTile=0: tile strings (incl. 't16' spelling), type counts, locks and RNG state == pre-fix core."""
    row, run, m = _CASES[cid]
    lj = _SNAP.level_json(row, run, m)
    got = _SNAP.snapshot(BotSimulator, lj)
    want = dict(_LEGACY["cases"][cid]["legacy"])
    if lj["randSeed"] <= 0 and cid.endswith(":raw"):
        # legacy t0 pass seeds zWellRandom(0) = wall-clock time for randSeed<=0 (same in the old core: placement
        # differs between processes). Only the time-independent parts are comparable across runs.
        got.pop("tiles_sha"); want.pop("tiles_sha")
    assert got == want


@pytest.mark.parametrize("cid", sorted(c for c, v in _LEGACY["cases"].items() if v["unlock"] > 0))
def test_forced_resolver_exception_falls_back_to_prefix_core(cid, monkeypatch):
    """unlockTile>0 with the client port raising -> exactly the pre-fix (legacy) state and RNG."""
    import app.core.pv.cs_shuffle as cs

    def boom(*a, **k):
        raise RuntimeError("forced")

    monkeypatch.setattr(cs, "shuffle_empty_tiles", boom)
    row, run, m = _CASES[cid]
    lj = _SNAP.level_json(row, run, m)
    assert BotSimulator()._client_key_resolve(lj, lj["unlockTile"]) == (None, 0)
    assert _SNAP.snapshot(BotSimulator, lj) == _LEGACY["cases"][cid]["legacy"]


def test_resolver_does_not_mutate_input_or_rng():
    inp = json.loads((GOLDEN / "inputs" / "s07_unlocktile_pure.json").read_text())
    lj = _level_json(inp["row"], {"randSeed": 1, "unlockTile": 1})
    before = json.dumps(lj, sort_keys=True)
    b = BotSimulator()
    b._rng.seed(7)
    rng0 = b._rng.getstate()
    resolved, keys = b._client_key_resolve(lj, 1)
    assert resolved is not None and keys == 3
    assert json.dumps(lj, sort_keys=True) == before
    assert b._rng.getstate() == rng0


def _mixed_key_level():
    # board "t16" + effect-key tile ['t0','key'] + inner "KEY"/"t16" in a stack, plus t0 slots; unlockTile 1
    tiles = {
        "0_0": ["t16", ""],
        "1_0": ["t0", "key"],
        "2_0": ["stack_n", "", [3, "t1_KEY_t16"]],
    }
    for i in range(13):          # 13 t0: padding (2 key + 2 t1) + 3 sets incl. 1 key set -> every type a multiple of 3
        tiles[f"{i % 8}_{2 + i // 8}"] = ["t0", ""]
    return {"layer": 1, "layer_0": {"col": "8", "row": "8", "tiles": tiles, "num": str(len(tiles))},
            "randSeed": 4242, "useTileCount": 3, "unlockTile": 1}


def _all_tiles(st):
    seen = {}
    for t in [x for lay in st.tiles.values() for x in lay.values()] + list(st.stacked_tiles.values()):
        seen[id(t)] = t
    return list(seen.values())


def test_mixed_t16_effect_key_normalised_and_consistent():
    from collections import Counter
    b = BotSimulator()
    st = b._create_initial_state(_mixed_key_level(), 100)
    b._precompute_blocking_map(st)
    tiles = _all_tiles(st)
    per_type = Counter(t.tile_type for t in tiles)
    assert "t16" not in per_type and "KEY" not in per_type
    assert st.tiles[0]["1_0"].tile_type == "key"            # effect-key board tile became a plain key
    # game: 4 explicit keys (t16, effect key, KEY, t16) + padding to 6 + 1 set from unlockTile -> 9 keys
    assert per_type["key"] == 9
    assert all(v % 3 == 0 for v in per_type.values())        # every type 3-matchable after normalisation
    assert sum(1 for s in st.dock if s.is_locked) == 3 and st.max_dock_slots == 4
    # all_tile_type_counts keeps the core's existing convention (stack top in state.tiles is not counted,
    # bot_simulator.py:1492-1503, unchanged) — keys must be counted under ONE spelling only
    tops = Counter(t.tile_type for lay in st.tiles.values() for t in lay.values() if t.is_stack_tile or t.is_craft_tile)
    assert set(st.all_tile_type_counts) <= {"key", "t1", "t2", "t3"}
    for k, v in per_type.items():
        assert st.all_tile_type_counts.get(k, 0) == v - tops.get(k, 0)


def test_mixed_keys_three_match_unlocks_one_slot():
    b = BotSimulator()
    st = b._create_initial_state(_mixed_key_level(), 100)
    b._precompute_blocking_map(st)
    locks0 = sum(1 for s in st.dock if s.is_locked)
    picked = 0
    while picked < 3:
        mv = next((m for m in b._get_available_moves(st) if m.tile_type == "key"), None)
        assert mv is not None, "a key must be reachable"
        b._apply_move(st, mv)
        picked += 1
    assert not any(t.tile_type == "key" for t in st.dock_tiles)
    assert sum(1 for s in st.dock if s.is_locked) == locks0 - 1
