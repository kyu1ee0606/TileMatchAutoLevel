"""Metric B (safe-move ratio) — app/core/pv/safe_moves.py."""
import math
import random

from app.core.pv.safe_moves import I, S, SafeMoveAnalyzer, analyze_board, board_flags, path_metrics


def _flat(types, effect=""):
    tiles = {f"{i}_0": [t, effect] for i, t in enumerate(types)}
    return {"layer": 1, "randSeed": 1, "useTileCount": 7, "unlockTile": 0,
            "layer_0": {"col": str(len(types)), "row": "1", "tiles": tiles, "num": str(len(types))}}


def test_path_metrics_synthetic():
    pts = [(4, 4, 0, 0), (4, 1, 3, 0), (5, 2, 2, 1), (3, 3, 0, 0)]
    m = path_metrics(pts)
    assert math.isclose(m["meanSafe"], (1 + 0.25 + 0.5 + 1) / 4)
    assert math.isclose(m["low10Safe"], 0.25)          # lowest ceil(10%) = 1 point
    assert m["bottle1"] == 1 and m["bottle2"] == 2     # only points with a real trap count
    assert math.isclose(m["uncertainFrac"], 1 / 16)
    assert math.isclose(m["log10RandClear"], math.log10(0.25 * 0.5))


def test_board_flags():
    assert board_flags(_flat(["t1"] * 3))["untrusted"] is False
    f = board_flags(_flat(["t1"] * 3, "bomb_3"))
    assert f["untrusted"] and f["untrustedEffects"] == ["bomb"]


def test_all_open_easy_board_is_fully_safe():
    r = analyze_board(_flat(["t1", "t2", "t1", "t2", "t1", "t2"]), k_paths=2)
    assert r["ok"] and r["root"] == S
    assert r["meanSafe"] == 1.0 and r["bottle1"] == 0 and r["uncertainFrac"] == 0.0
    assert r["stuckPaths"] == 0


def test_dock_trap_points_are_counted_and_consistent():
    # 7 types x 3, all open: with 6 singles in the dock a 7th new type overflows -> unsafe moves exist.
    types = [f"t{k}" for k in range(1, 8)] * 3
    an = SafeMoveAnalyzer(_flat(types))
    assert an.judge(an.root) == S
    w = an.walk(random.Random(3))
    assert w["end"] == "cleared"
    for legal, safe, unsafe, unc in w["points"]:
        assert safe + unsafe + unc == legal and safe >= 1
    # a failed child is judged IMPOSSIBLE without search
    kids = an.children(an.root)
    assert all(an.judge(k) in (S, I) for k in kids)


def test_fast_copy_matches_core_copy_on_random_playouts():
    """fast_copy must reproduce solver._copy_state exactly (board, dock, stacks/craft, legal moves)."""
    from dataclasses import replace

    from app.core.pv.safe_moves import fast_copy
    from app.core.solver import _copy_state, _state_signature
    from tests.test_bot_simulator import SAMPLE_LEVEL_EASY, SAMPLE_LEVEL_HARD

    def snap(sim, st):
        mv = sorted((m.layer_idx, m.position, m.tile_type, m.will_match) for m in sim._get_available_moves(st))
        stk = sorted((k, v.picked, v.tile_type, v.is_crafted) for k, v in st.stacked_tiles.items())
        return (_state_signature(st), st.cleared, st.failed, tuple(t.tile_type for t in st.dock_tiles), tuple(mv),
                tuple(stk), st.moves_used)

    def step(sim, st, m, cp):
        c = cp(st)
        sim._apply_move(c, replace(m, tile_state=c.tiles[m.layer_idx][m.position]))
        sim._is_game_over(c)
        return c

    rng = random.Random(5)
    for lvl in (SAMPLE_LEVEL_EASY, SAMPLE_LEVEL_HARD, _flat([f"t{k}" for k in range(1, 8)] * 3, "ice")):
        an = SafeMoveAnalyzer({**lvl, "randSeed": 7})
        sim, core = an.sim, (lambda s: _copy_state(an.sim, s))
        for _ in range(3):
            a = b = an.root
            while True:
                ms = sim._get_available_moves(a)
                if not ms:
                    break
                for m in ms:
                    assert snap(sim, step(sim, a, m, core)) == snap(sim, step(sim, b, m, fast_copy))
                m = rng.choice(ms)
                a, b = step(sim, a, m, core), step(sim, b, m, fast_copy)
                if a.cleared or a.failed:
                    break
