"""Bot v2.3 game-rule parity — tiny fixed boards that pin the game's behaviour (19_bot_rule_parity.md).

Each test builds a minimal level, runs the same scenario with the v2.1 bot (old rule) and with v2.3 with only the
relevant parity item on, and asserts the game's outcome (C# file:line in the docstring).
"""
import dataclasses

from app.core.bot_simulator import BotSimulator, TileEffectType
from app.core.mc_difficulty import make_skill_profile


def _level(layers, **extra):
    lj = {"layer": len(layers), "randSeed": 1, "useTileCount": 6, "unlockTile": 0, "max_moves": 200}
    for i, tiles in enumerate(layers):
        lj[f"layer_{i}"] = {"col": "7", "row": "7", "tiles": tiles, "num": str(len(tiles))}
    lj.update(extra)
    return lj


def _bot(lj, version="v2.1", items=(), auto_collect=0):
    prof = make_skill_profile(1.0, version)
    if version == "v2.3":
        cfg = dict(prof.gimmick_awareness)
        cfg["parity"] = list(items)
        cfg["auto_collect"] = auto_collect
        prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    bot.set_rule_parity(prof)
    state = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(state)
    if bot._par:
        bot._v23_game_start(state)          # what _play_game does at move 0
    return bot, state


def _move_at(bot, state, layer, pos):
    for m in bot._get_available_moves(state):
        if m.layer_idx == layer and m.position == pos:
            return m
    return None


def _pick(bot, state, layer, pos):
    m = _move_at(bot, state, layer, pos)
    assert m is not None, f"tile {layer}:{pos} not pickable"
    assert bot._v2_step(state, m)
    return m


def _tile(state, layer, pos):
    return state.tiles[layer][pos]


# ── stack ──────────────────────────────────────────────────────────────────────────────────────
STACK_COVERED = _level([
    {"3_3": ["stack_e", "", [2, "t1_t2"]], "0_0": ["t1", ""], "1_0": ["t2", ""]},
    {},
    {"3_3": ["t5", ""]},                      # same parity as layer 0 → covers 3_3 directly
])


def test_stack_top_ignores_upper_layer():
    """Game: a stack tile never checks upper layers (Tile.cs:1389-1391 `if (isStackTile == false) CheckUpperTileExist`)."""
    bot, st = _bot(STACK_COVERED)
    assert _move_at(bot, st, 0, "3_3") is None                       # v2.1: blocked by layer 2
    bot, st = _bot(STACK_COVERED, "v2.3", ["stack_cover"])
    m = _move_at(bot, st, 0, "3_3")
    assert m is not None and m.tile_type == "t2"                     # top (index 1) pickable at move 0
    _pick(bot, st, 0, "3_3")
    assert _move_at(bot, st, 0, "3_3").tile_type == "t1"             # next tile pickable while layer 2 still holds t5


# ── grass / chain neighbour = first object of the cell (stack root) ────────────────────────────
GRASS_STACK = _level([
    {"0_0": ["stack_e", "", [3, "t1_t2_t4"]], "1_0": ["t3", "grass"], "2_0": ["t6", ""],
     "0_2": ["t1", ""], "1_2": ["t2", ""], "2_2": ["t4", ""]},
])


def test_grass_only_counts_stack_root():
    """Game: grass reacts only to its cached neighbour objects; a stack cell's object is the root, picked last
    (Tile.cs:1075-1078 nearTile, TileEffect.cs:965-975 IsNearTile)."""
    bot, st = _bot(GRASS_STACK)
    _pick(bot, st, 0, "0_0")
    _pick(bot, st, 0, "0_0")
    assert _tile(st, 0, "1_0").effect_data["remaining"] == 0          # v2.1: every stack pick lowered the grass
    bot, st = _bot(GRASS_STACK, "v2.3", ["near_identity"])
    _pick(bot, st, 0, "0_0")                                          # top t4
    _pick(bot, st, 0, "0_0")                                          # middle t2
    assert _tile(st, 0, "1_0").effect_data["remaining"] == 2
    assert not bot._check_grass_impossible(st)                       # root still alive → 2 neighbours
    _pick(bot, st, 0, "0_0")                                          # root t1
    assert _tile(st, 0, "1_0").effect_data["remaining"] == 1


CHAIN_STACK = _level([
    {"0_0": ["stack_e", "", [2, "t1_t2"]], "1_0": ["t3", "chain"], "0_2": ["t1", ""], "1_2": ["t2", ""]},
])


def test_chain_only_counts_stack_root():
    """Game: chain unlock uses IsNearTile(other, true) on the cached east/west objects (TileEffect.cs:~1000)."""
    bot, st = _bot(CHAIN_STACK)
    _pick(bot, st, 0, "0_0")
    assert _tile(st, 0, "1_0").effect_data.get("unlocked")            # v2.1: top pick unlocked it
    bot, st = _bot(CHAIN_STACK, "v2.3", ["near_identity"])
    _pick(bot, st, 0, "0_0")
    assert not _tile(st, 0, "1_0").effect_data.get("unlocked")
    assert not bot._check_chain_impossible(st)
    _pick(bot, st, 0, "0_0")                                          # root
    assert _tile(st, 0, "1_0").effect_data.get("unlocked")


# ── ice: active count includes hidden stack tiles ──────────────────────────────────────────────
ICE_STACK = _level([{"0_0": ["t3", "ice"], "4_0": ["stack_e", "", [3, "t1_t1_t1"]]}])


def test_ice_active_count_includes_stack_inner():
    """Game: CheckIceTileCanUncover uses GetActiveTileCount, which counts every unpicked tile incl. those under a
    stack top (TileGroup.cs:1565-1579, 2855-2890): 3 > 4 − 1 is false → not impossible."""
    bot, st = _bot(ICE_STACK)
    assert bot._check_ice_impossible(st)                              # v2.1: 3 > 1 → false failure
    bot, st = _bot(ICE_STACK, "v2.3", ["ice_active"])
    assert not bot._check_ice_impossible(st)


def test_v23_items_off_equal_v21():
    bot, st = _bot(GRASS_STACK, "v2.3", [])
    _pick(bot, st, 0, "0_0")
    assert _tile(st, 0, "1_0").effect_data["remaining"] == 1          # same as v2.1 when no item is on
    assert TileEffectType.GRASS == _tile(st, 0, "1_0").effect_type


# ── craft ──────────────────────────────────────────────────────────────────────────────────────
CRAFT_COVERED = _level([
    {"3_3": ["craft_e", "", [2, "t1_t2"]], "0_0": ["t1", ""], "1_0": ["t2", ""], "0_5": ["t5", ""], "1_5": ["t5", ""]},
    {},
    {"3_3": ["t5", ""]},
])


def test_covered_craft_box_does_not_emit():
    """Game: TileCraft emission returns while the box cell is covered (TileCraft.cs:511-515, maskActive :884)."""
    bot, st = _bot(CRAFT_COVERED)
    assert "4_3" in st.tiles[0]                                      # v2.1 emits at init regardless
    bot, st = _bot(CRAFT_COVERED, "v2.3", ["craft_cover"])
    assert "4_3" not in st.tiles[0]
    _pick(bot, st, 2, "3_3")                                          # uncover the box
    bot._emit_blocked_craft_tiles(st)
    assert st.tiles[0]["4_3"].tile_type == "t2"


BOX_ABOVE = _level([
    {"3_3": ["t7", ""], "0_0": ["t7", ""], "1_0": ["t7", ""]},
    {},
    {"3_3": ["craft_s", "", [2, "t1_t2"]], "0_6": ["t1", ""], "1_6": ["t2", ""]},
])


def test_craft_box_with_unemitted_tiles_covers_lower():
    """Game: tiles inside a box stay alive at the box cell, so the cell lookup still finds them (Tile.cs:1634-1644)."""
    bot, st = _bot(BOX_ABOVE)
    assert _move_at(bot, st, 0, "3_3") is not None                   # v2.1: the box cell is empty on the board
    bot, st = _bot(BOX_ABOVE, "v2.3", ["craft_cover"])
    assert _move_at(bot, st, 0, "3_3") is None
    _pick(bot, st, 2, "3_4")                                          # emitted t2 → t1 comes out, box now empty
    bot._process_move_effects(st, set(), set())
    assert _move_at(bot, st, 0, "3_3") is not None


# ── effect parsing ─────────────────────────────────────────────────────────────────────────────
PARSE = _level([{"0_0": ["t1", "bomb_7"], "1_0": ["t2", "ice_2"], "2_0": ["t3", "5"], "3_0": ["t4", "curtain"],
                 "4_0": ["t5", "bomb"], "5_0": ["t6", "grass_1"]}])


def test_effect_parse_matches_game():
    """Game: bomb N = all digits of the string, no clamp (TileEffect.cs:570); ice/grass exact strings only
    (DB_Level.cs:283, :310); plain 'curtain' → curtainActive=false (TileEffect.cs:540-562)."""
    bot, st = _bot(PARSE)
    assert st.bomb_tiles["0_0_0"] == 5 and st.tiles[0]["1_0"].effect_type == TileEffectType.ICE
    bot, st = _bot(PARSE, "v2.3", ["effect_parse"])
    t = st.tiles[0]
    assert st.bomb_tiles["0_0_0"] == 7 and st.bomb_tiles["0_4_0"] == 0
    assert t["1_0"].effect_type == TileEffectType.NONE and t["5_0"].effect_type == TileEffectType.NONE
    assert t["2_0"].effect_type == TileEffectType.NONE and t["3_0"].effect_type == TileEffectType.NONE


# ── teleport permutation ───────────────────────────────────────────────────────────────────────
TELE = _level([{"0_0": ["t1", "teleport"], "1_0": ["t2", "teleport"], "2_0": ["t3", "teleport"], "3_0": ["t5", "teleport"],
                "0_3": ["t4", ""], "1_3": ["t4", ""], "2_3": ["t4", ""]}])
TELE_POS = ("0_0", "1_0", "2_0", "3_0")


def _tele_outcomes(version, items):
    seen = set()
    for seed in range(60):
        bot, st = _bot(TELE, version, items)
        bot._rng.seed(seed)
        for _ in range(3):
            bot._process_teleport(st)
        seen.add(tuple(st.tiles[0][p].tile_type for p in TELE_POS))
    return seen


def test_teleport_is_random_cycle():
    """Game: Sattolo-shuffle the list, then rotate types along the SHUFFLED list (TileGroup.cs:2041-2088).
    For n=3 every Sattolo order is a rotation of the original, so the result is fixed even in the game; with n=4
    several results occur, all derangements. The old bot rotated along the original order (one fixed result)."""
    assert len(_tele_outcomes("v2.1", ())) == 1
    out = _tele_outcomes("v2.3", ["tele_perm"])
    assert len(out) > 1
    orig = ("t1", "t2", "t3", "t5")
    assert all(all(a != b for a, b in zip(o, orig)) for o in out)


# ── frog landing / link partner frog ───────────────────────────────────────────────────────────
FROG = _level([{"0_0": ["t1", "frog"], "2_0": ["t2", "ice"], "4_0": ["t3", ""]}])


def test_frog_lands_on_any_uncovered_tile():
    """Game: landing candidates have no type/effect filter (TileGroup.cs:1780-1796)."""
    bot, st = _bot(FROG)
    cand = {pos for _, pos, _ in bot._get_frog_movable_tiles(st)}
    assert cand == {"4_0"}
    bot, st = _bot(FROG, "v2.3", ["frog_land"])
    cand = {pos for _, pos, _ in bot._get_frog_movable_tiles(st)}
    assert cand == {"2_0", "4_0"}


LINK = _level([{"0_0": ["t1", "link_e"], "1_0": ["t2", "frog"], "0_3": ["t1", ""], "1_3": ["t2", ""]}])


def test_link_partner_frog_blocks_pair():
    """Game: a link pair can be picked only if neither tile has a frog (TileEffect.cs:1274-1279)."""
    bot, st = _bot(LINK)
    bot._update_link_tiles_status(st)
    assert st.tiles[0]["0_0"].effect_data["can_pick"]
    bot, st = _bot(LINK, "v2.3", ["link_frog"])
    bot._update_link_tiles_status(st)
    assert not st.tiles[0]["0_0"].effect_data["can_pick"]


# ── key locks ──────────────────────────────────────────────────────────────────────────────────
KEYS = _level([{"0_0": ["key", ""], "1_0": ["key", ""], "2_0": ["key", ""], "0_2": ["t1", ""]}])


def test_key_tiles_lock_slots():
    """Game: SetLockSlot(#keyTiles) → floor(keys/3) locked slots (TileGroup.cs:1338, Dock.cs:844)."""
    bot, st = _bot(KEYS)
    assert st.max_dock_slots == 7
    bot, st = _bot(KEYS, "v2.3", ["key_locks"])
    assert st.max_dock_slots == 6


# ── curtain rules ──────────────────────────────────────────────────────────────────────────────
CURTAINS = _level([{"0_0": ["t1", "curtain_close"], "1_0": ["t2", "curtain_close"], "5_5": ["t3", ""]},
                   {},
                   {"5_5": ["t4", "curtain_close"]}])


def test_all_uncovered_closed_curtains_force_open():
    """Game: when every uncovered tile is a closed curtain, the first one is opened (TileGroup.cs:2134-2154)."""
    bot, st = _bot(CURTAINS, "v2.3", ["curtain_rules"])
    bot._v23_curtain_rules(st)
    opened = [p for (l, p) in ((0, "0_0"), (0, "1_0"), (2, "5_5")) if st.tiles[l][p].effect_data.get("is_open")]
    assert len(opened) == 1


ONLY_CURTAINS = _level([{"0_0": ["t1", "curtain_close"], "1_0": ["t1", "curtain_close"]}])


def test_only_curtains_left_last_deactivated():
    """Game: if only curtain tiles remain, the last curtain's effect is removed (TileGroup.cs:2118-2132)."""
    bot, st = _bot(ONLY_CURTAINS, "v2.3", ["curtain_rules"])
    bot._v23_curtain_rules(st)
    assert sum(1 for t in st.tiles[0].values() if t.effect_type == TileEffectType.NONE) == 1


# ── auto collect (냥이의 도움) ─────────────────────────────────────────────────────────────────
CAT = _level([{f"{x}_0": ["t1", ""] for x in range(6)} | {f"{x}_2": ["t2", ""] for x in range(6)}
              | {f"{x}_4": ["t3", ""] for x in range(6)}])


def test_auto_collect_cycle():
    """Game: a cycle puts 3 badge tiles in the dock (≤2 per type) (AutoCollectController.cs:1282-1350, 1668-1723);
    when every badge is matched the cat fills the dock's partial pairs from the field and a new cycle starts
    (:517-570, :927-1000, :621)."""
    bot, st = _bot(CAT, "v2.3", ["auto_collect"], auto_collect=1)
    assert len(st.dock_tiles) == 3
    counts = {}
    for t in st.dock_tiles:
        counts[t.tile_type] = counts.get(t.tile_type, 0) + 1
    assert max(counts.values()) <= 2
    # user completes every badge type, plus one extra tile of another type (a partial pair the cat must fill)
    for tt, c in counts.items():
        for _ in range(3 - c):
            tile = next(t for li in st.tiles for t in st.tiles[li].values() if not t.picked and t.tile_type == tt)
            bot._v2_step(st, _move_at(bot, st, tile.layer_idx, tile.position_key))
            bot._v23_auto_collect_after_move(st, [tt])
    # every badge matched → dock emptied → a new cycle put 3 new badges in
    assert len(st.dock_tiles) == 3


def test_auto_collect_off_without_level_flag():
    bot, st = _bot(CAT, "v2.3", ["auto_collect"], auto_collect=0)
    assert len(st.dock_tiles) == 0


# ── chain awareness (behaviour item, not a rule) ───────────────────────────────────────────────
CHAIN_COVERED = _level([{"1_0": ["t3", "chain"], "0_0": ["t1", ""], "2_0": ["t2", ""], "4_4": ["t5", ""]},
                        {},
                        {"1_0": ["t4", ""]}])


def _chain_bot(alpha):
    prof = make_skill_profile(1.0, "v2.3")
    cfg = dict(prof.gimmick_awareness)
    cfg["parity"] = ["chain_aware"]
    cfg["alpha"] = dict(cfg["alpha"], chain=alpha)
    prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    bot.set_rule_parity(prof)
    st = bot._create_initial_state(CHAIN_COVERED, 200)
    bot._precompute_blocking_map(st)
    return bot, st, prof


def test_chain_awareness_gates_isolation_penalty():
    """Users fail by Chain (AF 9% of 301~500 fails) while the θ≥0.73 bot never isolates a covered chain:
    v2.3 draws chain awareness per turn like bomb/grass in v2.1; unaware turns ignore the chain threat."""
    for alpha, expect in ((20.0, True), (-20.0, False)):
        bot, st, prof = _chain_bot(alpha)
        bot._v21_draw_awareness(st, prof)
        assert bot._v21_aware.get("chain") is expect
        m = _move_at(bot, st, 0, "0_0")
        score = bot._score_move_with_profile(m, st, prof)
        bot2, st2, prof2 = _chain_bot(alpha)
        bot2._v21_aware = {"chain": expect}
        if expect:
            assert bot2._chain_isolation_penalty(0.0, st2, prof2, _move_at(bot2, st2, 0, "0_0").tile_state) == 0.0
    # v2.1 profile never draws chain awareness
    bot = BotSimulator()
    p21 = make_skill_profile(1.0, "v2.1")
    bot.set_rule_parity(p21)
    st = bot._create_initial_state(CHAIN_COVERED, 200)
    bot._v21_draw_awareness(st, p21)
    assert "chain" not in bot._v21_aware
