"""Unit tests for app.core.pv.features (placement features for seed pre-filtering)."""
from app.core.pv.features import build_graph, compute_features, greedy_play


def _map(l0, l1=None, col0=3, col1=4):
    m = {"layer": 2 if l1 is not None else 1, "layer_0": {"col": str(col0), "row": "3", "tiles": l0}}
    if l1 is not None:
        m["layer_1"] = {"col": str(col1), "row": "4", "tiles": l1}
    return m


def test_cover_rule_bigger_upper_layer():
    # layer_1 (col 4 > 3, other parity) covers (x,y),(x+1,y),(x,y+1),(x+1,y+1) of layer_0 tile (0,0)
    m = _map({"0_0": ["t1", ""]}, {"0_0": ["t2", ""], "1_1": ["t3", ""], "2_2": ["t4", ""]})
    nodes = build_graph(m)
    blockers = {nodes[b].kind for b in nodes[0].blockers}
    assert blockers == {"t2", "t3"}


def test_cover_rule_smaller_upper_layer():
    m = _map({"1_1": ["t1", ""]}, {"0_0": ["t2", ""], "1_1": ["t3", ""], "2_2": ["t4", ""]}, col0=4, col1=3)
    nodes = build_graph(m)
    assert {nodes[b].kind for b in nodes[0].blockers} == {"t2", "t3"}


def test_stack_inner_chain_and_cover_by_stack():
    m = _map({"0_0": ["t1", ""]}, {"0_0": ["stack_e", "", [3, "t5_t6_t7"]]})
    nodes = build_graph(m)
    kinds = [n.kind for n in nodes]
    i5, i6, i7 = kinds.index("t5"), kinds.index("t6"), kinds.index("t7")
    assert nodes[i5].blockers == [i6] and nodes[i6].blockers == [i7] and nodes[i7].blockers == []
    assert nodes[0].blockers == [i5]  # board tile under a stack waits for the bottom inner


def test_features_easy_vs_hard_assignment():
    # same structure: 3 exposed on top + 3 hidden below; easy = exposed triple, hard = split kinds
    easy = _map({"0_0": ["t2", ""], "1_0": ["t2", ""], "2_0": ["t2", ""]},
                {"0_0": ["t1", ""], "2_0": ["t1", ""], "0_2": ["t1", ""]}, col0=3, col1=3)
    hard = _map({"0_0": ["t1", ""], "1_0": ["t2", ""], "2_0": ["t2", ""]},
                {"0_0": ["t1", ""], "2_0": ["t2", ""], "0_2": ["t1", ""]}, col0=3, col1=3)
    fe, fh = compute_features(easy), compute_features(hard)
    assert fe["exposedTripleKinds"] >= fh["exposedTripleKinds"]
    assert fe["greedyCleared"] == 1


def test_greedy_clears_trivial():
    m = _map({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    r = greedy_play(build_graph(m))
    assert r["greedyCleared"] == 1 and r["greedyMaxTray"] == 2
