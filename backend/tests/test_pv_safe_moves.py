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


def _two_layer():
    # layer_0 (bottom) cells 0_0..2_0 fully under same-parity layer_2 cells; 3_0..5_0 open.
    low = {f"{i}_0": [t, ""] for i, t in enumerate(["t1", "t2", "t3", "t1", "t2", "t3"])}
    top = {f"{i}_0": [t, ""] for i, t in enumerate(["t1", "t2", "t3"])}
    return {"layer": 3, "randSeed": 1, "useTileCount": 3, "unlockTile": 0,
            "layer_0": {"col": "6", "row": "1", "tiles": low, "num": "6"},
            "layer_1": {"col": "6", "row": "1", "tiles": {}, "num": "0"},
            "layer_2": {"col": "6", "row": "1", "tiles": top, "num": "3"}}


def test_hidden_tiles_and_determinize_preserve_visible_info():
    from app.core.pv.safe_moves import determinize, hidden_tiles

    an = SafeMoveAnalyzer(_two_layer())
    hid = hidden_tiles(an.sim, an.root, "occluded")
    assert sorted((t.layer_idx, t.x_idx) for t in hid) == [(0, 0), (0, 1), (0, 2)]
    assert len(hidden_tiles(an.sim, an.root, "covered")) == 3
    rng = random.Random(1)
    for _ in range(5):
        w, n = determinize(an.sim, an.root, "occluded", rng)
        assert n == 3
        seen = lambda st: sorted((li, p, t.tile_type) for li, l in st.tiles.items() for p, t in l.items()
                                 if not an.sim._is_blocked_by_upper(st, t))
        assert seen(w) == seen(an.root)                                  # visible tiles unchanged
        hid_types = lambda st: sorted(t.tile_type for t in hidden_tiles(an.sim, st, "occluded"))
        assert hid_types(w) == hid_types(an.root)                        # hidden type counts preserved
    assert [t.tile_type for t in hidden_tiles(an.sim, an.root, "occluded")] == ["t1", "t2", "t3"]  # root untouched


def test_analyze_board_info_runs_and_reports_both_variants():
    from app.core.pv.safe_moves import analyze_board_info

    r = analyze_board_info(_two_layer(), k_paths=1, points_per_path=3, m_worlds=4)
    assert r["ok"] and r["root"] == S and r["nSampled"] == 3
    for k in ("B", "B_nonTrivial", "Bp_occluded", "Bp_covered"):
        assert r[k] is None or 0.0 <= r[k] <= 1.0


def test_topk_bot_ranking_and_metrics():
    from app.core.mc_difficulty import make_skill_profile
    from app.core.pv.safe_moves import analyze_board_topk, bot_ranking

    types = [f"t{k}" for k in range(1, 8)] * 3
    an = SafeMoveAnalyzer(_flat(types))
    an.sim._rng = random.Random(1)
    st = an.apply(an.root, an.sim._get_available_moves(an.root)[0])
    st = an.apply(st, next(m for m in an.sim._get_available_moves(st) if m.tile_type == "t1"))
    moves = an.sim._get_available_moves(st)
    order = bot_ranking(an.sim, st, moves, make_skill_profile(0.7))
    assert moves[order[0]].will_match and sorted(order) == list(range(len(moves)))

    r = analyze_board_topk(_flat(types), [0.55, 0.65], k_paths=2, info_points_per_path=3, m_worlds=3)
    assert r["ok"] and r["stuckPaths"] == 0
    for k in (1, 2, 3, 5):
        assert 0.0 <= r[f"Bk{k}"] <= 1.0 and r[f"Bk{k}_info"] is not None
    assert sum("topk_info" in p for p in r["points"]) == 6
    easy = analyze_board_topk(_flat(["t1", "t2", "t1", "t2", "t1", "t2"]), [0.5], k_paths=1, info_points_per_path=1)
    assert easy["Bk5"] == 1.0
