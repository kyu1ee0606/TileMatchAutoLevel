"""Unit tests for app.core.pv.t0ize / evaluate.candidate_seeds / select (P1 pilot helpers)."""
from __future__ import annotations

import pytest

from app.core.pv.canonical import canonical_map, struct_hash
from app.core.pv.cs_shuffle import build_level_model, get_empty_tile_list
from app.core.pv.evaluate import candidate_seeds
from app.core.pv.select import distinguishable, final_select, paired_diff, quantile, shortlist
from app.core.pv.t0ize import PvT0izeError, bot_level_json, t0ize_level


def _level(tiles0, tiles1=None):
    lj = {"layer": 2 if tiles1 is not None else 1, "useTileCount": 99, "randSeed": 0,
          "layer_0": {"col": "7", "row": "7", "tiles": tiles0, "num": str(len(tiles0))}}
    if tiles1 is not None:
        lj["layer_1"] = {"col": "8", "row": "8", "tiles": tiles1, "num": str(len(tiles1))}
    return lj


def _explicit():
    t0 = {"0_0": ["t2", "ice"], "1_0": ["t2", ""], "2_0": ["t2", "chain"],
          "3_0": ["stack_e", "", [3, "t5_t5_t5"]], "0_1": ["t9", ""], "1_1": ["t9", ""]}
    t1 = {"0_0": ["t9", "link_e"], "1_0": ["t2", ""], "2_0": ["t2", ""], "3_0": ["t2", ""]}
    return _level(t0, t1)


def test_t0ize_rules():
    out = t0ize_level(_explicit(), 12345)
    row, meta = out["row"], out["meta"]
    assert meta["utc0"] == 3  # t2, t5 (inner), t9 — key/t0 excluded
    assert row["useTileCount"] == "3" and row["randSeed"] == "12345"
    assert row["shuffleTile"] == "0" and row["typeImbalance"] == "" and row["unlockTile"] == "0"
    assert "visualTileSeed" not in row and "etime" not in row
    tiles0 = row["map"]["layer_0"]["tiles"]
    assert tiles0["0_0"] == ["t0", "ice"] and tiles0["2_0"] == ["t0", "chain"]
    assert tiles0["3_0"] == ["stack_e", "", [3]]
    assert row["map"]["layer_1"]["tiles"]["0_0"] == ["t0", "link_e"]
    assert struct_hash(row["map"]) == struct_hash(canonical_map(_explicit())) == meta["structHash"]
    assert len(get_empty_tile_list(build_level_model(row["map"]))) == meta["tileCount"] == 12


def test_t0ize_rejects():
    lj = _explicit()
    lj["layer_0"]["tiles"]["4_4"] = ["key", ""]
    with pytest.raises(PvT0izeError):
        t0ize_level(lj, 1)
    lj = _explicit()
    lj["layer_0"]["tiles"]["3_0"] = ["craft_s", "", [3]]  # count-only
    with pytest.raises(PvT0izeError):
        t0ize_level(lj, 1)
    with pytest.raises(PvT0izeError):
        t0ize_level(_explicit(), 0)
    lj = _explicit()
    lj["layer_0"]["tiles"]["1_0"] = ["t3", ""]  # breaks ÷3
    with pytest.raises(PvT0izeError):
        t0ize_level(lj, 1)


def test_bot_level_json_key_and_layer():
    resolved = {"layer": "1", "layer_0": {"tiles": {"0_0": ["t16", ""], "1_0": ["stack_e", "", [3, "t16_t1_t16"]]}},
                "layer_1": {"tiles": {"0_0": ["t1", ""]}}}
    lj = bot_level_json({"randSeed": "7", "useTileCount": "3"}, resolved)
    assert lj["layer"] == 2
    assert lj["layer_0"]["tiles"]["0_0"][0] == "key"
    assert lj["layer_0"]["tiles"]["1_0"][2][1] == "key_t1_key"
    assert lj["randSeed"] == 7 and lj["max_moves"] == 1 + 3 + 1 + 50


def test_candidate_seeds():
    a = candidate_seeds("abc", 32)
    assert a == candidate_seeds("abc", 32) and len(set(a)) == 32
    assert all(1 <= s <= 2**31 - 1 for s in a)
    assert a != candidate_seeds("abd", 32)


def _ev(rates_by_theta, n=400):
    th = {}
    for t, r in rates_by_theta.items():
        k = int(round(r * n))
        th[t] = {"wins": [1] * k + [0] * (n - k), "rate": k / n}
    return {"theta": th, "W": sum(v["rate"] for v in th.values()) / len(th)}


def test_quantile_and_paired_diff():
    assert quantile([0, 1, 2, 3, 4], 0.25) == 1.0
    a, b = _ev({"0.29": 0.6, "0.47": 0.5, "0.65": 0.7}), _ev({"0.29": 0.4, "0.47": 0.3, "0.65": 0.5})
    pd = paired_diff(a, b)
    assert pd["diff"] == pytest.approx(0.2) and pd["se"] > 0
    assert distinguishable(a, b)["ok"]
    assert not distinguishable(b, a)["ok"]


def test_shortlist_base_in_band_near_orig():
    s1 = {str(i): _ev({"0.29": i / 40, "0.47": i / 40, "0.65": i / 40}, n=64) for i in range(1, 33)}
    sl = shortlist(s1, w_orig=0.05)  # orig far below band -> base = band low edge
    w = sl["w1"][sl["base"]]
    assert sl["band"][0] <= w <= sl["band"][1]
    assert abs(w - sl["band"][0]) < 0.03
    assert all(sl["w1"][s] > w for s in sl["easy"]) and all(sl["w1"][s] < w for s in sl["hard"])
    assert "32" not in sl["easy"][:2]  # single most extreme is not a primary pick


def test_final_select_ok_collapse_flat():
    lv = {"b": 0.5, "e1": 0.6, "e2": 0.7, "h1": 0.4, "h2": 0.3}
    s2 = {k: _ev({"0.29": v, "0.47": v, "0.65": v}, n=1200) for k, v in lv.items()}
    ver = {k: True for k in lv}
    r = final_select("b", ["e1", "e2"], ["h1", "h2"], s2, ver)
    assert r["status"] == "ok" and [s for _, s in r["seeds"]] == ["e2", "e1", "b", "h1", "h2"]
    r = final_select("b", ["e1"], ["h1", "h2"], s2, ver)
    assert r["status"] == "collapsed" and r["collapsed"] == ["e2"] and dict(r["seeds"])["e2"] == "e1"
    r = final_select("b", ["e1", "e2"], ["h1", "h2"], s2, {k: k == "b" for k in lv})
    assert r["status"] == "flat" and all(s == "b" for _, s in r["seeds"])


# ── v2: adaptive θ / independent CI / bidirectional selection ─────────────────
from app.core.pv.select import (  # noqa: E402
    base_pick, bidirectional_select, choose_thetas, indep_diff, staircase_shortlist,
)


def _ev2(rates, n=950):
    th = {t: {"rate": r, "n": n, "wins": [1] * int(round(r * n)) + [0] * (n - int(round(r * n)))} for t, r in rates.items()}
    return {"theta": th, "W": sum(rates.values()) / len(rates)}


def test_choose_thetas():
    c = choose_thetas({"0.0": 0.1, "0.29": 0.35, "0.55": 0.52, "0.65": 0.7, "1.0": 0.95})
    assert c["evaluable"] and c["thetas"] == [0.29, 0.55]
    assert not choose_thetas({"0.65": 0.0, "1.0": 0.05})["evaluable"]


def test_indep_diff():
    d = indep_diff(_ev2({"0.55": 0.6, "0.85": 0.7}), _ev2({"0.55": 0.5, "0.85": 0.6}))
    assert d["diff"] == pytest.approx(0.1) and d["lo"] > 0
    d = indep_diff(_ev2({"0.55": 0.52}), _ev2({"0.55": 0.5}))
    assert d["lo"] < 0


def test_base_pick_and_staircase():
    w1 = {str(i): i / 100 for i in range(1, 33)}
    ver = {s: True for s in w1}
    bp = base_pick(w1, 0.20, ver)
    assert bp["base"] == "20" and not bp["origExtreme"]
    assert base_pick(w1, 0.95, ver)["origExtreme"]
    sl = staircase_shortlist(w1, "20", ver)
    assert sl["easy"][:2] == ["26", "32"] and sl["hard"][:2] == ["14", "8"]


def test_bidirectional_select_rules():
    ev = {"b": _ev2({"t": 0.5}), "e1": _ev2({"t": 0.56}), "e2": _ev2({"t": 0.7}),
          "h1": _ev2({"t": 0.44}), "h2": _ev2({"t": 0.35}), "hx": _ev2({"t": 0.49})}
    ver = {k: True for k in ev}
    r = bidirectional_select("b", list(ev), ev, ver)
    assert r["ok"] and r["seeds"] == [("e2", "e2"), ("e1", "e1"), ("b", "b"), ("h1", "h1"), ("h2", "h2")]
    r = bidirectional_select("b", ["e1", "e2", "h1"], ev, ver)  # only one valid hard
    assert not r["ok"] and r["sides"]["hard"]["reason"] == "one_valid"
    ver["h2"] = False
    r = bidirectional_select("b", list(ev), ev, ver)  # unverified hard excluded
    assert not r["ok"]
