"""PV canonical/structHash/typesHash 단위 테스트 — 담당: E-P0-2.

검증 대상: backend/app/core/pv/canonical.py
근거: claudedocs/difficulty_personalization/04_seed_variant_plan.md §A3-3, §A6,
      backend/app/api/routes/gboost.py의 `_convert_to_townpop_format` 재사용.
"""
import copy

from app.core.pv.canonical import (
    canonical_map,
    check_layer_continuity,
    struct_hash,
    types_hash,
)


def _simple_level(tiles: dict, layer: int | str = 1, col="3", row="3") -> dict:
    return {
        "layer": layer,
        "layer_0": {"col": col, "row": row, "tiles": tiles},
    }


# ---------------------------------------------------------------------------
# struct_hash: 결정성
# ---------------------------------------------------------------------------

def test_struct_hash_is_deterministic():
    lj = _simple_level({
        "0_0": ["t1", ""], "1_0": ["t2", ""], "2_0": ["t3", ""],
    })
    h1 = struct_hash(canonical_map(copy.deepcopy(lj)))
    h2 = struct_hash(canonical_map(copy.deepcopy(lj)))
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_struct_hash_unchanged_when_only_tile_type_changes():
    """t0화(타입 재배정)만으로는 구조가 바뀌지 않아야 한다 (04 §A2 단언 ③)."""
    explicit = _simple_level({
        "0_0": ["t1", ""], "1_0": ["t2", ""], "2_0": ["t3", ""],
    })
    all_t0 = _simple_level({
        "0_0": ["t0", ""], "1_0": ["t0", ""], "2_0": ["t0", ""],
    })
    assert struct_hash(canonical_map(explicit)) == struct_hash(canonical_map(all_t0))


def test_struct_hash_unchanged_when_insertion_order_differs_but_positions_same():
    """저장 시 키 삽입 순서가 달라도 canonical_map이 row-major로 재정렬하므로 같아야 한다."""
    a = _simple_level({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    b = _simple_level({"2_0": ["t1", ""], "0_0": ["t1", ""], "1_0": ["t1", ""]})
    assert struct_hash(canonical_map(a)) == struct_hash(canonical_map(b))


def test_struct_hash_changes_when_position_moves():
    a = _simple_level({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    b = _simple_level({"0_0": ["t1", ""], "1_0": ["t1", ""], "3_0": ["t1", ""]})
    assert struct_hash(canonical_map(a)) != struct_hash(canonical_map(b))


def test_struct_hash_changes_when_effect_differs():
    a = _simple_level({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    b = _simple_level({"0_0": ["t1", "ice"], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    assert struct_hash(canonical_map(a)) != struct_hash(canonical_map(b))


def test_struct_hash_changes_when_container_inner_count_differs():
    """스택/크래프트 inner 개수(innerCount)는 구조로 취급한다(04 §A2: cnt는 유지 대상)."""
    a = _simple_level({"0_0": ["stack_e", "", [3]], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    b = _simple_level({"0_0": ["stack_e", "", [5]], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    assert struct_hash(canonical_map(a)) != struct_hash(canonical_map(b))


def test_struct_hash_unchanged_when_container_inner_type_labels_differ():
    """신포맷 inner 명시 id("3_t1_t2_t3")는 타입이므로 cnt만 같으면 구조는 같아야 한다."""
    a = _simple_level({"0_0": ["stack_e", "", [3, "t1_t2_t3"]], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    b = _simple_level({"0_0": ["stack_e", "", [3]], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    assert struct_hash(canonical_map(a)) == struct_hash(canonical_map(b))


def test_struct_hash_changes_when_container_root_id_differs():
    """컨테이너 루트 id(stack_e vs craft_s)는 t0화해도 불변이어야 하는 구조 요소다."""
    a = _simple_level({"0_0": ["stack_e", "", [3]], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    b = _simple_level({"0_0": ["craft_s", "", [3]], "1_0": ["t1", ""], "2_0": ["t1", ""]})
    assert struct_hash(canonical_map(a)) != struct_hash(canonical_map(b))


def test_struct_hash_changes_when_layer_missing():
    """레이어 수(`layer`)는 그대로인데 해당 layer_i 키 자체가 없으면 구조 차이로 잡혀야 한다."""
    two_layers = {
        "layer": 2,
        "layer_0": {"col": "3", "row": "3", "tiles": {"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]}},
        "layer_1": {"col": "3", "row": "3", "tiles": {"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]}},
    }
    missing_layer_1 = copy.deepcopy(two_layers)
    del missing_layer_1["layer_1"]
    assert struct_hash(canonical_map(two_layers)) != struct_hash(canonical_map(missing_layer_1))


# ---------------------------------------------------------------------------
# canonical_map: 샤드 포맷 호환 (string layer, list-as-empty-tiles)
# ---------------------------------------------------------------------------

def test_canonical_map_accepts_string_layer_count_like_shard():
    """샤드 raw map은 layer 값이 문자열("1")이다 — 생성기 int 포맷과 동일 해시가 나와야 한다."""
    int_form = _simple_level({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]}, layer=1)
    str_form = _simple_level({"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]}, layer="1")
    assert struct_hash(canonical_map(int_form)) == struct_hash(canonical_map(str_form))


def test_canonical_map_handles_list_as_empty_tiles():
    """실측(샤드 9레벨)에서 빈 레이어의 tiles가 {}가 아니라 []로 직렬화돼 있었다.

    `_convert_to_townpop_format`(gboost.py)는 dict를 가정하므로 그대로 넘기면
    AttributeError가 난다 — canonical_map이 사전에 []를 {}로 정규화해야 한다.
    """
    level_json = {
        "layer": "2",
        "layer_0": {"col": "3", "row": "3", "tiles": [], "num": "0"},
        "layer_1": {"col": "3", "row": "3", "tiles": {"0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""]}, "num": "3"},
    }
    cm = canonical_map(level_json)  # 예외 없이 동작해야 함
    assert cm["layer_0"]["tiles"] == {}
    h = struct_hash(cm)
    assert len(h) == 64


# ---------------------------------------------------------------------------
# check_layer_continuity
# ---------------------------------------------------------------------------

def test_layer_continuity_ok():
    lj = {
        "layer": 2,
        "layer_0": {"col": "3", "row": "3", "tiles": {}},
        "layer_1": {"col": "3", "row": "3", "tiles": {}},
    }
    assert check_layer_continuity(canonical_map(lj)) == []


def test_layer_continuity_detects_missing_layer():
    lj = {
        "layer": 3,
        "layer_0": {"col": "3", "row": "3", "tiles": {}},
        "layer_2": {"col": "3", "row": "3", "tiles": {}},
        # layer_1 missing
    }
    problems = check_layer_continuity(canonical_map(lj))
    assert problems
    assert any("layer_1" in p for p in problems)


# ---------------------------------------------------------------------------
# types_hash
# ---------------------------------------------------------------------------

def test_types_hash_deterministic():
    assert types_hash(["t1", "t2", "t3"]) == types_hash(["t1", "t2", "t3"])


def test_types_hash_order_sensitive():
    assert types_hash(["t1", "t2", "t3"]) != types_hash(["t2", "t1", "t3"])


def test_types_hash_distinguishes_content():
    assert types_hash(["t1", "t2", "t3"]) != types_hash(["t1", "t2", "t4"])
