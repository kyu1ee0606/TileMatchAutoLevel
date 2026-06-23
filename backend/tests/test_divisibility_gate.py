"""
Regression tests for _enforce_divisibility_gate in production_store.py.

Tests that:
- A level with t1 tile count not divisible by 3 (4 tiles → 4%3=1) is flagged:
    meta.verification_passed=False and level_number appears in returned flagged list.
- A level with t1 tile count divisible by 3 (6 tiles → 6%3=0) is NOT flagged:
    meta.verification_passed is unaffected.
"""
import copy
import pytest

from app.api.routes.production_store import _enforce_divisibility_gate


def _make_level(tile_count: int, level_number: int) -> dict:
    """Build a minimal level dict with `tile_count` t1 tiles in a single layer."""
    tiles = {f"0_{i}": ["t1", ""] for i in range(tile_count)}
    return {
        "level_json": {
            "layer": 1,
            "layer_0": {"col": "8", "row": "8", "tiles": tiles, "num": str(tile_count)},
        },
        "meta": {
            "level_number": level_number,
            "verification_passed": True,
        },
    }


@pytest.fixture()
def levels():
    """Two levels: one ÷3 violating (4 tiles), one clean (6 tiles)."""
    return [
        _make_level(tile_count=4, level_number=1),  # 4 % 3 = 1 → violation
        _make_level(tile_count=6, level_number=2),  # 6 % 3 = 0 → clean
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_violating_level_is_flagged(levels):
    """Level with 4 t1 tiles must appear in the returned flagged list."""
    flagged = _enforce_divisibility_gate(levels)
    assert 1 in flagged, f"Expected level_number 1 in flagged, got {flagged}"


def test_clean_level_is_not_flagged(levels):
    """Level with 6 t1 tiles must NOT appear in the returned flagged list."""
    flagged = _enforce_divisibility_gate(levels)
    assert 2 not in flagged, f"Level 2 should be clean but found in flagged: {flagged}"


def test_violating_level_meta_verification_passed_false(levels):
    """Gate must set meta.verification_passed=False on the violating level."""
    _enforce_divisibility_gate(levels)
    assert levels[0]["meta"]["verification_passed"] is False


def test_violating_level_meta_has_divisibility_violation(levels):
    """Gate must record the violating type counts in meta.divisibility_violation."""
    _enforce_divisibility_gate(levels)
    violation = levels[0]["meta"].get("divisibility_violation", {})
    assert "t1" in violation, f"Expected 't1' in divisibility_violation, got {violation}"
    assert violation["t1"] == 4


def test_clean_level_meta_unchanged(levels):
    """Gate must not modify meta.verification_passed on a clean level."""
    _enforce_divisibility_gate(levels)
    # The clean level's verification_passed should still be True (unchanged)
    assert levels[1]["meta"]["verification_passed"] is True


def test_clean_level_no_divisibility_violation(levels):
    """Gate must not add divisibility_violation to a clean level."""
    _enforce_divisibility_gate(levels)
    assert "divisibility_violation" not in levels[1]["meta"]


def test_flagged_list_length(levels):
    """Exactly one level should be flagged when one violates and one is clean."""
    flagged = _enforce_divisibility_gate(levels)
    assert len(flagged) == 1


def test_idempotent(levels):
    """Calling the gate twice must produce the same result (idempotent)."""
    flagged_first = _enforce_divisibility_gate(levels)
    levels_copy = copy.deepcopy(levels)
    flagged_second = _enforce_divisibility_gate(levels_copy)
    assert flagged_first == flagged_second


def test_empty_levels():
    """Gate called with an empty list must return an empty flagged list."""
    assert _enforce_divisibility_gate([]) == []


def test_level_without_level_json():
    """A level entry missing level_json must be skipped without error."""
    levels = [{"meta": {"level_number": 99, "verification_passed": True}}]
    flagged = _enforce_divisibility_gate(levels)
    assert flagged == []


def test_level_without_meta_gets_meta_created():
    """If a violating level has no 'meta' key the gate must create it."""
    level = {
        "level_json": {
            "layer": 1,
            "layer_0": {
                "col": "4",
                "row": "4",
                "tiles": {f"0_{i}": ["t1", ""] for i in range(4)},  # 4 % 3 = 1
                "num": "4",
            },
        }
        # no 'meta' key intentionally
    }
    _enforce_divisibility_gate([level])
    assert level["meta"]["verification_passed"] is False
