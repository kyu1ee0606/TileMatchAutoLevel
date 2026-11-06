"""열쇠 3배수 규칙(key_not_div3) — 저장 게이트 · 검증 API · 생성기 보정.

t0 칸이 0 인 레벨에서 명시 열쇠(id t16/key 또는 effect key, 컨테이너 명시 내부 포함) 합계 %3 != 0 이면
남는 열쇠를 게임에서 지울 수 없다(DB_Level.cs:1123-1153 보충은 t0 가 있을 때만).
실서버·실저장소 쓰기 없음: 저장 게이트는 임시 디렉터리로 바꿔 함수 단위로 호출한다.
"""
from __future__ import annotations

import copy
import json

import pytest

from app.api.routes import production_store as ps
from app.core.generator import LevelGenerator
from app.core.solver import _clearability_type_counts


def mk(tiles: dict, **extra) -> dict:
    lj = {"layer": 1, "useTileCount": 3, "unlockTile": 1,
          "layer_0": {"col": "8", "row": "8", "tiles": tiles}}
    lj.update(extra)
    return lj


def colors(n_types=2, per=3, start=0):
    """t1..tn 각 per 장 (좌표 r=0..)."""
    out, k = {}, start
    for t in range(1, n_types + 1):
        for _ in range(per):
            out[f"{k % 8}_{k // 8}"] = [f"t{t}", ""]
            k += 1
    return out, k


def keys_at(start, n, tid="key", eff=""):
    return {f"{(start + i) % 8}_{(start + i) // 8}": [tid, eff] for i in range(n)}


def scan(lj, n=150):
    return ps._scan_rule_violations(lj, n).get("key_not_div3")


# ── 규칙 ─────────────────────────────────────────────────────────────────────

def test_four_keys_no_t0_violation_with_count_in_message():
    base, k = colors()
    v = scan(mk({**base, **keys_at(k, 4)}))
    assert v == {"keys": 4, "t0": 0, "remainder": 1}


def test_four_keys_with_t0_passes():
    base, k = colors()
    lj = mk({**base, **keys_at(k, 4), f"{(k + 4) % 8}_{(k + 4) // 8}": ["t0", ""]})
    assert scan(lj) is None


@pytest.mark.parametrize("n", [0, 3, 6])
def test_three_or_six_keys_pass(n):
    base, k = colors()
    assert scan(mk({**base, **keys_at(k, n)})) is None


def test_t16_and_case_insensitive_key_ids():
    base, k = colors()
    t = {**base, **keys_at(k, 2, "t16"), **keys_at(k + 2, 2, "KEY")}
    assert scan(mk(t))["keys"] == 4


def test_effect_key_cell_counts_as_key():
    base, k = colors()
    t = {**base, **keys_at(k, 3), f"{(k + 3) % 8}_0": ["t5", "key"]}
    assert scan(mk(t))["keys"] == 4


def test_inner_keys_counted_only_when_token_count_matches():
    base, k = colors()
    # 보드 열쇠 2 + 내부 열쇠 2 → 4 (위반)
    t = {**base, **keys_at(k, 2), "7_7": ["stack_n", "", [3, "key_t1_key"]]}
    assert scan(mk(t)) == {"keys": 4, "t0": 0, "remainder": 1}
    # 보드 2 + 내부 1 → 3 (통과)
    t2 = {**base, **keys_at(k, 2), "7_7": ["stack_n", "", [3, "t1_key_t2"]]}
    assert scan(mk(t2)) is None
    # 내부 수 불일치(옛 형식) → 내부 전체 t0 → t0 > 0 → 통과
    t3 = {**base, **keys_at(k, 4), "7_7": ["stack_n", "", [2, "key_t1_key"]]}
    assert scan(mk(t3)) is None
    # 내부 정보 없음(개수만) → t0
    t4 = {**base, **keys_at(k, 4), "7_7": ["craft_s", "", [3]]}
    assert scan(mk(t4)) is None
    # 신형식 내부 t0 토큰 → t0 > 0 → 통과
    t5 = {**base, **keys_at(k, 4), "7_7": ["stack_n", "", [3, "t0_t1_t2"]]}
    assert scan(mk(t5)) is None


# ── 저장 게이트(함수 단위, 임시 저장소) ───────────────────────────────────────

@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(ps, "_INDEX_PATH", str(tmp_path / "_index.json"))
    return tmp_path


def test_save_gate_flags_key_not_div3(tmp_store):
    base, k = colors()
    bad = {"meta": {"level_number": 150, "verification_passed": True}, "level_json": mk({**base, **keys_at(k, 4)})}
    ok = {"meta": {"level_number": 152, "verification_passed": True}, "level_json": mk({**base, **keys_at(k, 3)})}
    r = ps.save_batch("t_keydiv3", ps.SaveBatchRequest(batch_id="t_keydiv3", batch={}, levels=[bad, ok]))
    assert (r.rule_flagged, r.rule_levels, r.key_div3_flagged, r.key_div3_levels) == (1, [150], 1, [150])
    saved = json.loads((tmp_store / "t_keydiv3.json").read_text())["levels"]
    m = {l["meta"]["level_number"]: l["meta"] for l in saved}
    assert m[150]["verification_passed"] is False and m[150]["rule_violations"]["key_not_div3"]["keys"] == 4
    assert m[152]["verification_passed"] is True and "rule_violations" not in m[152]


# ── 생성기 보정 ──────────────────────────────────────────────────────────────

def test_repair_relabels_surplus_key_into_short_type():
    base, k = colors()                                   # t1×3, t2×3
    t = {**base, **keys_at(k, 4), "7_6": ["t3", ""], "6_6": ["t3", ""]}   # t3×2 (부족 1)
    lj = mk(t)
    g = LevelGenerator()
    g._last_playability_warning = False
    out = g._repair_key_divisibility(copy.deepcopy(lj))
    st = g._key_div3_scan(out)
    assert st["keys"] == 3 and not st["violation"]
    assert all(c % 3 == 0 for c in _clearability_type_counts(out).values())
    assert _clearability_type_counts(out).get("t3") == 3
    assert g._last_playability_warning is False
    assert out["unlockTile"] == lj["unlockTile"]                         # unlockTile 은 안 바꿈


def test_repair_two_surplus_into_two_short_types():
    base, k = colors()
    t = {**base, **keys_at(k, 5), "7_6": ["t3", ""], "6_6": ["t3", ""], "5_6": ["t4", ""], "4_6": ["t4", ""]}
    g = LevelGenerator()
    g._last_playability_warning = False
    out = g._repair_key_divisibility(mk(t))
    assert g._key_div3_scan(out)["keys"] == 3
    assert all(c % 3 == 0 for c in _clearability_type_counts(out).values())


def test_repair_inner_key_slot():
    base, k = colors()
    t = {**base, **keys_at(k, 3), "7_7": ["stack_n", "", [3, "t3_t3_key"]]}   # 열쇠 4, t3×2
    g = LevelGenerator()
    g._last_playability_warning = False
    out = g._repair_key_divisibility(mk(t))
    assert out["layer_0"]["tiles"]["7_7"][2][1] == "t3_t3_t3"
    assert not g._key_div3_scan(out)["violation"]


def test_repair_impossible_sets_warning_and_keeps_level():
    base, k = colors()                                   # 모든 종류 3배수 → 바꾸면 깨짐
    lj = mk({**base, **keys_at(k, 4)})
    g = LevelGenerator()
    g._last_playability_warning = False
    out = g._repair_key_divisibility(copy.deepcopy(lj))
    assert out == lj and g._last_playability_warning is True
    assert scan(out)["keys"] == 4                        # 저장 게이트가 막는다


def test_repair_noop_when_t0_present_or_div3():
    base, k = colors()
    g = LevelGenerator()
    g._last_playability_warning = False
    for lj in (mk({**base, **keys_at(k, 4), "7_7": ["t0", ""]}), mk({**base, **keys_at(k, 6)})):
        assert g._repair_key_divisibility(copy.deepcopy(lj)) == lj
    assert g._last_playability_warning is False


def test_finalize_level_runs_key_repair():
    base, k = colors()
    t = {**base, **keys_at(k, 4), "7_6": ["t3", ""], "6_6": ["t3", ""]}
    g = LevelGenerator()
    g._last_playability_warning = False
    out = g._finalize_level(mk(t, layer=1))
    assert not g._key_div3_scan(out)["violation"]
    assert all(c % 3 == 0 for c in _clearability_type_counts(out).values())


def test_editor_validate_reports_key_not_div3():
    """analyze.fixed_level_validate(저장 없음)가 같은 규칙을 issues 로 돌려준다(마무리 파이프라인 후 판정)."""
    import asyncio
    from app.api.routes import analyze as an
    base, k = colors()
    lj = mk({**base, **keys_at(k, 4)})                   # 보정 불가 케이스 → 남아야 함
    r = asyncio.run(an.fixed_level_validate(152, an.FixedLevelSaveRequest(level_json=lj)))
    kinds = [i["kind"] for i in (r.get("issues") if isinstance(r, dict) else r.issues)]
    assert "key_not_div3" in kinds
