"""Tests for app.core.pv.cs_shuffle — reference port of client ShuffleEmptyTiles.

Part 1: golden-free unit tests (hand-derived from the C# text, documented values).
Part 2: golden comparison against backend/tests/golden/pv_t0/ (dotnet / Unity dumps).
        Loader is pending until the golden file format is fixed by E-P0-3.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from app.core.pv.cs_shuffle import (
    CsClientCrash,
    CTile,
    PvContractError,
    PvUnsupportedInput,
    ZWellRandom,
    apply_visual_tile_remap,
    as_int,
    build_level_model,
    distribute_tiles,
    get_empty_tile_list,
    get_to_add_index_list,
    resolve_map,
    round_to_int_unity,
    shuffle_empty_tiles,
    shuffle_level_row,
    sp_integer_parse,
)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _layer(tiles: dict, col: int = 7, row: int = 7) -> dict:
    return {"col": str(col), "row": str(row), "tiles": tiles, "num": str(len(tiles))}


def _t0_grid(n: int, effect: str = "") -> dict:
    return {f"{i % 7}_{i // 7}": ["t0", effect] for i in range(n)}


def _counts(ids):
    return Counter(ids)


# ─────────────────────────────────────────────────────────────────────────────
# zWellRandom
# ─────────────────────────────────────────────────────────────────────────────
# Raw _rand() first 5 — 01_client_findings.md §3-6 (independent Python port by the client survey;
# C# execution confirmation comes from golden G1).
WELL512_FIRST5 = {
    1: [427107241, 3478131665, 1329158148, 4270539161, 922294098],
    12345: [3072437747, 3304182464, 2955451663, 3096138484, 1011788893],
    625901: [1847860848, 2935187508, 2739093739, 1480485179, 2116881938],
}


@pytest.mark.parametrize("seed,expected", sorted(WELL512_FIRST5.items()))
def test_well512_raw_first5(seed, expected):
    r = ZWellRandom(seed)
    assert [r._rand() for _ in range(5)] == expected


def test_well512_seed_zero_is_time_based():
    with pytest.raises(PvContractError):
        ZWellRandom(0)
    with pytest.raises(PvContractError):
        ZWellRandom(2**32)  # (uint) wraps to 0


def test_rand_inclusive_and_zero_width_no_consumption():
    r = ZWellRandom(777)
    vals = [r.rand(0, 4) for _ in range(500)]
    assert set(vals) == {0, 1, 2, 3, 4}
    calls = r.calls
    assert r.rand(5, 4) == 0  # e - s + 1 == 0 -> return 0, no _rand()
    assert r.calls == calls
    assert r.rand(3, 3) == 3 and r.calls == calls + 1  # width 1 still consumes (ZW:80-83)


def test_rand_one_arg_form():
    a, b = ZWellRandom(99), ZWellRandom(99)
    assert [a.rand(6) for _ in range(50)] == [b.rand(0, 5) for _ in range(50)]


def test_visual_remap_documented_golden():
    # CHANGELOG_20260630_VISUAL_TILE_SEED.md:30 — "TS↔C# 바이트 일치 검증" values, usedTypes=[1..6]
    ids = [f"t{i}" for i in range(1, 7)]
    assert apply_visual_tile_remap(ids, 459838) == ["t4", "t1", "t7", "t9", "t12", "t3"]
    assert apply_visual_tile_remap(ids, 12345) == ["t9", "t5", "t3", "t8", "t2", "t14"]


# ─────────────────────────────────────────────────────────────────────────────
# parsing semantics
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12", 12), (" 7 ", 7), ("1.9", 1), ("-3", -3), ("-1.9", -1), ("", 0), ("abc", 0),
        ("1e3", 1000), ("+5", 5), (".5", 0), ("1.", 1), ("3000000000", -1294967296),
        (None, 0), (5, 5), (2.7, 2), (-2.7, -2), (4294967291, -5),
    ],
)
def test_as_int(raw, expected):
    assert as_int(raw) == expected


def test_as_int_unsupported():
    for raw in ("Infinity", "NaN", True, [1], {"a": 1}):
        with pytest.raises(PvUnsupportedInput):
            as_int(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [("t12", 12), ("t0", 0), ("t", 0), ("t-1", -1), ("t1.5", 1), ("x", 0), ("", 0), (None, 0), ("t007", 7)],
)
def test_sp_integer_parse(raw, expected):
    assert sp_integer_parse(raw) == expected


@pytest.mark.parametrize(
    "tid,eff,expected",
    [("key", "", 16), ("KEY", "", 16), ("t3", "key", 16), ("t3", "Key", 16), ("t16", "", 16),
     ("stack_e", "", -1), ("craft_s", "", -1), ("t0", "ice", 0), ("t12", "chain", 12)],
)
def test_tile_id_num(tid, eff, expected):
    assert CTile("layer_0", "0_0", tid, eff).tile_id_num == expected


def test_round_to_int_bankers():
    assert [round_to_int_unity(x) for x in (2.5, -2.5, 3.5, 0.5, 1.4999, -7.5)] == [2, -2, 4, 0, 1, -8]


# ─────────────────────────────────────────────────────────────────────────────
# DistributeTiles (hand-derived from CS:1372-1502)
# ─────────────────────────────────────────────────────────────────────────────
def _color_totals(lst, active):
    tot = [0] * active
    for v in lst:
        if v != 16:
            tot[(v - 1) // 3] += 1
    return tot


def test_distribute_utc6_set10():
    r = ZWellRandom(4242)
    lst = distribute_tiles(10, 6, 0, 0.0, r)
    # caps [3,3], floor 10*3/6 = 5 each, remainder 0; each color q=1 rem=2 -> 2 Rand calls per color
    assert len(lst) == 10
    assert _color_totals(lst, 2) == [5, 5]
    assert r.calls == 4
    c = _counts(lst)
    assert all(c[i] in (1, 2) for i in range(1, 7))
    # output order: color asc, slot asc
    assert lst == sorted(lst)


def test_distribute_utc13_set20():
    r = ZWellRandom(1)
    lst = distribute_tiles(20, 13, 0, 0.0, r)
    # caps [3,3,3,3,1] total 13; floor: 4,4,4,4,1 (=17); remainder 3 -> colors 0,1,2 -> [5,5,5,4,1]
    assert _color_totals(lst, 5) == [5, 5, 5, 4, 1]
    assert _counts(lst)[13] == 1
    assert r.calls == 8  # colors 0..3 have rem>0 and cap 3 -> 2 calls each; color 4 cap 1 -> none


def test_distribute_specified_keys_and_no_types():
    lst = distribute_tiles(5, 6, 2, 0.0, ZWellRandom(3))
    assert lst.count(16) == 2 and len(lst) == 5 and lst[-2:] == [16, 16]
    assert distribute_tiles(4, 0, 1, 0.0, ZWellRandom(3)) == [16]  # tileTypeCount 0 -> keys only


def test_distribute_imbalance_half():
    # setLength 30, utc 9: colorSet [10,10,10]; base 10.0, norm [-1,0,1], delta round(10*0.5*3*norm)=[-15,0,15]
    # -> [0,10,25], sum 35, diff -5 -> decrement max (c2) -> [0,10,20]
    lst = distribute_tiles(30, 9, 0, 0.5, ZWellRandom(5))
    assert _color_totals(lst, 3) == [0, 10, 20]


def test_distribute_no_rnd_is_deterministic_order():
    lst = distribute_tiles(10, 6, 0, 0.0, None)
    # order = identity -> slots 0,1 get +1 in both colors
    assert lst == [1, 1, 2, 2, 3, 4, 4, 5, 5, 6]


# ─────────────────────────────────────────────────────────────────────────────
# ShuffleEmptyTiles
# ─────────────────────────────────────────────────────────────────────────────
def _pure_map(n=9, layers=1):
    m = {"layer": str(layers)}
    per = n // layers
    for li in range(layers):
        m[f"layer_{li}"] = _layer(_t0_grid(per))
    return m


def test_pure_t0_invariants_and_rng_budget():
    m = _pure_map(9)
    res = shuffle_empty_tiles(m, rand_seed=12345, use_tile_count=3)
    assert len(res.slots) == 9
    c = _counts(res.assigned)
    assert set(c) <= {"t1", "t2", "t3"} and all(v % 3 == 0 for v in c.values())
    # distribute: active 1, cap 3, sets 3 -> q1 rem0 -> 0 calls; cluster: 3-1 = 2; swaps: 2*9 = 18
    assert res.rng_calls == 20


def test_rng_budget_formula_larger():
    m = _pure_map(42, layers=2)
    res = shuffle_empty_tiles(m, rand_seed=625901, use_tile_count=12, shuffle_tile=3)
    sets = 42 // 3
    # sets 14, utc 12: caps [3,3,3,3]; floor 14*3/12 = 3 each (12), remainder 2 -> [4,4,3,3]
    # rem per color: 1,1,0,0 -> 2 calls for colors 0,1 -> 4
    assert res.rng_calls == 4 + (sets - 1) + 2 * (42 + 3)


def test_determinism_and_input_not_mutated():
    m = _pure_map(21)
    snap = copy.deepcopy(m)
    a = shuffle_empty_tiles(m, rand_seed=98765, use_tile_count=7)
    b = shuffle_empty_tiles(m, rand_seed="98765", use_tile_count="7")
    assert a.assigned == b.assigned
    assert m == snap


def test_negative_seed_is_uint_cast():
    m = _pure_map(21)
    a = shuffle_empty_tiles(m, rand_seed=-5, use_tile_count=7)
    b = shuffle_empty_tiles(m, rand_seed=4294967291, use_tile_count=7)
    assert a.seed_u32 == 4294967291 and a.assigned == b.assigned


@pytest.mark.parametrize("seed", [0, "0", "", None, "abc", 4294967296])
def test_zero_seed_forbidden(seed):
    with pytest.raises(PvContractError):
        shuffle_empty_tiles(_pure_map(9), rand_seed=seed, use_tile_count=3)


def test_use_tile_count_zero_needs_skin():
    with pytest.raises(PvUnsupportedInput):
        shuffle_empty_tiles(_pure_map(9), rand_seed=1, use_tile_count=0)
    res = shuffle_empty_tiles(_pure_map(9), rand_seed=1, use_tile_count=0, skin_tile_count=16)
    assert res.use_tile_count == 15


def test_non_div3_pure_t0_crashes_like_client():
    m = {"layer": "1", "layer_0": _layer(_t0_grid(7))}
    with pytest.raises(CsClientCrash):
        shuffle_empty_tiles(m, rand_seed=11, use_tile_count=3)


def test_padding_from_explicit_types():
    tiles = {"0_0": ["t5", ""]}
    tiles.update({f"{i}_1": ["t0", ""] for i in range(8)})
    m = {"layer": "1", "layer_0": _layer(tiles)}
    res = shuffle_empty_tiles(m, rand_seed=31337, use_tile_count=3)
    assert res.to_add == [5, 5]
    full = Counter(t.tile_id for t in get_empty_tile_list(res.model, True))
    assert all(v % 3 == 0 for v in full.values()) and full["t5"] == 3


def test_padding_leaves_partial_set_strict_vs_lenient():
    tiles = {"0_0": ["t5", ""]}
    tiles.update({f"{i}_1": ["t0", ""] for i in range(7)})
    m = {"layer": "1", "layer_0": _layer(tiles)}
    with pytest.raises(PvContractError):
        shuffle_empty_tiles(m, rand_seed=31337, use_tile_count=3)
    res = shuffle_empty_tiles(m, rand_seed=31337, use_tile_count=3, strict=False)
    assert len(res.assigned) == 7


def test_traversal_order_layers_by_number_tiles_by_json_order():
    l1 = _layer({"3_3": ["t0", ""], "0_0": ["t0", ""], "1_0": ["t0", ""]})
    l0 = _layer({"6_6": ["t0", ""], "2_0": ["t0", ""], "0_5": ["t0", ""]})
    m = {"layer": "2", "layer_1": l1, "layer_0": l0}  # map key order: layer_1 first
    res = shuffle_empty_tiles(m, rand_seed=5, use_tile_count=2)
    assert [(s.layer_name, s.pos) for s in res.slots] == [
        ("layer_0", "6_6"), ("layer_0", "2_0"), ("layer_0", "0_5"),
        ("layer_1", "3_3"), ("layer_1", "0_0"), ("layer_1", "1_0"),
    ]


def test_tile_key_order_changes_result():
    tiles = _t0_grid(30)
    m1 = {"layer": "1", "layer_0": _layer(tiles)}
    m2 = {"layer": "1", "layer_0": _layer(dict(reversed(list(tiles.items()))))}
    r1 = shuffle_empty_tiles(m1, rand_seed=2024, use_tile_count=10)
    r2 = shuffle_empty_tiles(m2, rand_seed=2024, use_tile_count=10)
    by_pos1 = {s.pos: t for s, t in zip(r1.slots, r1.assigned)}
    by_pos2 = {s.pos: t for s, t in zip(r2.slots, r2.assigned)}
    assert r1.assigned == r2.assigned  # same sequence ...
    assert by_pos1 != by_pos2  # ... lands on different positions


def test_stack_inner_slots_inline_and_explicit_inner_kept():
    tiles = {
        "0_0": ["t0", ""],
        "1_0": ["craft_s", "", [3]],  # old format -> 3 t0 inner
        "2_0": ["stack_e", "", [3, "t1_t1_t1"]],  # explicit inner -> not distributed
        "3_0": ["stack_w", None, [3, "key_t0_t0"]],  # new format with t0 + key
        "4_0": ["t0", "ice"],
    }
    m = {"layer": "1", "layer_0": _layer(tiles)}
    model = build_level_model(m)
    empty = get_empty_tile_list(model, False)
    assert [(t.pos, t.inner_index) for t in empty] == [
        ("0_0", None), ("1_0", 0), ("1_0", 1), ("1_0", 2), ("3_0", 1), ("3_0", 2), ("4_0", None),
    ]
    # toAdd: t1 x3 (ok), key x1 -> 2 more keys (16)
    assert get_to_add_index_list(model) == [16, 16]


def test_count_mismatch_inner_falls_back_to_t0():
    m = {"layer": "1", "layer_0": _layer({"0_0": ["stack_e", "", [3, "t1_t2"]]})}
    model = build_level_model(m)
    assert [t.tile_id for t in model.layers["layer_0"][0].stack] == ["t0", "t0", "t0"]


def test_layer_gap_crashes():
    m = {"layer": "3", "layer_0": _layer(_t0_grid(3)), "layer_2": _layer(_t0_grid(3))}
    with pytest.raises(CsClientCrash):
        shuffle_empty_tiles(m, rand_seed=1, use_tile_count=1)


def test_stack_root_without_stack_info_crashes():
    m = {"layer": "1", "layer_0": _layer({"0_0": ["stack_e", ""], "1_0": ["t0", ""]})}
    with pytest.raises(CsClientCrash):
        shuffle_empty_tiles(m, rand_seed=1, use_tile_count=1)


def test_unlock_tile_generates_keys():
    res = shuffle_empty_tiles(_pure_map(18), rand_seed=777, use_tile_count=3, unlock_tile=1)
    c = _counts(res.assigned)
    assert c["t16"] == 3 and sum(c.values()) == 18


def test_no_empty_tiles_no_rng():
    m = {"layer": "1", "layer_0": _layer({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]})}
    res = shuffle_empty_tiles(m, rand_seed=9, use_tile_count=3)
    assert res.slots == [] and res.rng_calls == 0


def test_effects_stay_in_place():
    tiles = {f"{i}_0": ["t0", eff] for i, eff in enumerate(["ice", "chain", "", "bomb_5", "link_e", ""])}
    m = {"layer": "1", "layer_0": _layer(tiles)}
    res = shuffle_empty_tiles(m, rand_seed=55, use_tile_count=2)
    out = resolve_map(m, res)
    assert [v[1] for v in out["layer_0"]["tiles"].values()] == ["ice", "chain", "", "bomb_5", "link_e", ""]


def test_resolve_map_board_and_inner():
    tiles = {"0_0": ["t0", ""], "1_0": ["craft_s", "", [3]], "2_0": ["stack_e", "", ["2", "t0_t0"]]}  # 6 t0
    m = {"layer": "1", "layer_0": _layer(tiles)}
    snap = copy.deepcopy(m)
    res = shuffle_empty_tiles(m, rand_seed=424242, use_tile_count=2)
    out = resolve_map(m, res)
    assert m == snap
    by_slot = {(s.pos, s.inner_index): t for s, t in zip(res.slots, res.assigned)}
    t = out["layer_0"]["tiles"]
    assert t["0_0"][0] == by_slot[("0_0", None)]
    assert t["1_0"][2] == [3, "_".join(by_slot[("1_0", i)] for i in range(3))]
    assert t["2_0"][2] == ["2", "_".join(by_slot[("2_0", i)] for i in range(2))]
    # resolved map has no t0 left -> client would leave it untouched
    again = build_level_model(out)
    assert get_empty_tile_list(again, False) == []


def test_shuffle_level_row_with_string_map():
    m = _pure_map(12)
    row = {"map": json.dumps(m), "randSeed": "1834920117", "useTileCount": "4", "unlockTile": "0",
           "shuffleTile": "0", "typeImbalance": ""}
    a = shuffle_level_row(row)
    b = shuffle_empty_tiles(m, rand_seed=1834920117, use_tile_count=4)
    assert a.assigned == b.assigned


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — golden vectors (E-P0-3 dotnet G1/G2, C-P0-1 Unity G3)
# ─────────────────────────────────────────────────────────────────────────────
GOLDEN_DIR = Path(__file__).parent / "golden" / "pv_t0"
EXPECTED_DISTVER = "cs:191858cc9c06"  # DB_Level.cs b741f6a3 — must match golden header (README "원문 고정 정보")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _golden_runs():
    """[(id, row, expected_result, tileCountShim)] for every run of every case (format pv_t0_golden/v1)."""
    out = []
    if not (GOLDEN_DIR / "expected").is_dir():
        return out
    for exp_path in sorted((GOLDEN_DIR / "expected").glob("[rs]*.json")):
        inp = _load(GOLDEN_DIR / "inputs" / exp_path.name)
        exp = _load(exp_path)
        runs = inp.get("runs") or [{}]
        assert len(runs) == len(exp["results"]), exp_path.name
        for k, (run, res) in enumerate(zip(runs, exp["results"])):
            row = {**inp["row"], **run}
            out.append(pytest.param(row, res, exp.get("tileCountShim"), id=f"{exp_path.stem}#{k}"))
    return out


_GOLDEN = _golden_runs()


def _nums(ids):
    return [CTile("", "", t, "").tile_id_num for t in ids]


def test_golden_present_and_version():
    assert _GOLDEN, "golden vectors missing"
    man = _load(GOLDEN_DIR / "expected" / "_manifest.json")
    assert man["format"] == "pv_t0_golden/v1"
    assert man["distVer"] == EXPECTED_DISTVER


def test_golden_g1_rng():
    rng = _load(GOLDEN_DIR / "rng_well512.json")
    assert rng["distVer"] == EXPECTED_DISTVER
    for entry in rng["seeds"]:
        r = ZWellRandom(entry["seed"])
        assert [r._rand() for _ in range(len(entry["raw"]))] == entry["raw"], entry["seed"]


@pytest.mark.parametrize("row,res,shim", _GOLDEN)
def test_golden_g2_case(row, res, shim):
    eff = res.get("effective") or {}
    if res.get("nondeterministic") is not None:
        # randSeed AsInt == 0 -> time-based on client -> port must refuse
        with pytest.raises(PvContractError):
            shuffle_level_row(row)
        return
    if res.get("exception"):
        with pytest.raises(CsClientCrash):
            shuffle_level_row(row, strict=False)
        return
    shim_dependent = as_int(row.get("useTileCount")) <= 0
    if shim_dependent:
        # maxTileIndex comes from TileSetting (skin prefab) -> not a truth; port must refuse without it
        with pytest.raises(PvUnsupportedInput):
            shuffle_level_row(row)
        kw = {"skin_tile_count": shim["tileCount"] if isinstance(shim, dict) else shim}
    else:
        kw = {}

    failing = bool(res["selfCheck"].get("totalPerTypeNotMultipleOf3"))
    if failing:
        with pytest.raises(PvContractError):
            shuffle_level_row(row, **kw)
    got = shuffle_level_row(row, strict=False, **kw)

    assert got.seed_u32 == eff["seedUint"]
    assert got.use_tile_count == eff["maxTileIndex"]
    assert [[s.layer_name, s.pos, -1 if s.inner_index is None else s.inner_index] for s in got.slots] == res["positions"]
    assert _nums(got.assigned) == res["types"]
    if "rngRawPrefix" in res:
        r = ZWellRandom(eff["seedUint"])
        assert [r._rand() for _ in range(len(res["rngRawPrefix"]))] == res["rngRawPrefix"]
    assert resolve_map(row["map"], got) == res["resolvedMap"]


# ─────────────────────────────────────────────────────────────────────────────
# P0-G5 — resolved explicit map read by the existing bot == golden types (inner order included)
# ─────────────────────────────────────────────────────────────────────────────
def _bot_level_json(row, resolved_map):
    """Editor-format level_json for BotSimulator from a resolved townpop map (no t0 left)."""
    lj = copy.deepcopy(resolved_map)
    layer_nums = [int(k[6:]) for k in lj if k.startswith("layer_") and k[6:].isdigit()]
    lj["layer"] = max(as_int(lj.get("layer")), max(layer_nums, default=-1) + 1)  # ~ EffectiveLayerCount
    for k in list(lj):
        if k.startswith("layer_") and isinstance(lj[k].get("tiles"), list):
            lj[k]["tiles"] = {}
    lj["randSeed"] = as_int(row.get("randSeed"))
    lj["useTileCount"] = as_int(row.get("useTileCount"))
    lj["unlockTile"] = as_int(row.get("unlockTile"))
    return lj


def _bot_types_by_slot(lj):
    from app.core.bot_simulator import BotSimulator

    state = BotSimulator()._create_initial_state(lj, max_moves=10_000)
    by_key = {}
    for layer_tiles in state.tiles.values():
        for ts in layer_tiles.values():
            by_key[ts.original_full_key or ts.full_key] = ts.tile_type
    for ts in state.stacked_tiles.values():
        by_key[ts.original_full_key or ts.full_key] = ts.tile_type
    return by_key


_G5 = [p for p in _GOLDEN if p.values[1].get("types") and not p.values[1]["selfCheck"].get("totalPerTypeNotMultipleOf3")]


@pytest.mark.parametrize("row,res,shim", _G5)
def test_golden_g5_bot_reads_resolved_map(row, res, shim):
    lj = _bot_level_json(row, res["resolvedMap"])
    by_key = _bot_types_by_slot(lj)
    for (layer, pos, inner), want in zip(res["positions"], res["types"]):
        li = int(layer[6:])
        key = f"{li}_{pos}" if inner < 0 else f"{li}_{pos}_{inner}"
        got = by_key.get(key)
        assert got is not None, f"bot has no tile at {key}"
        # bot spells keys "key"; client resolved maps write "t16" (see 05_p0_report F-G5-1)
        want_str = "t16" if want == 16 else f"t{want}"
        # 2026-10-27 key parity: ONLY with unlockTile>0 the bot normalises "t16" -> "key" itself
        # (test_bot_key_parity.py). unlockTile=0 must stay byte-identical to the legacy reading ("t16").
        if lj["unlockTile"] > 0:
            ok = got == want_str or (want == 16 and got == "key")
        else:
            ok = got == want_str
        assert ok, f"{key}: bot={got} golden={want_str}"
