"""/api/pv-play 라우트 테스트 (샌드박스 pv_20261002_live3, 읽기 전용).

v2 경로(?selection=v2, 레벨 55 5칸) + v4 기본 경로(레벨 55 5단계, 574 3단계 seed@utc11, 고정맵 orig 만).

결과 append 는 tmp_path 로 우회해 실제 manual_play/results.jsonl 을 오염시키지 않는다.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.api.routes import pv_play
from app.core.pv.canonical import types_hash
from app.core.pv.cs_shuffle import shuffle_empty_tiles
from app.main import app

LEVEL = 55
T0_PATH = os.path.join(pv_play.SANDBOX_DIR, "t0", f"{LEVEL:04d}.json")

pytestmark = pytest.mark.skipif(not os.path.exists(T0_PATH), reason="PV 샌드박스 없음")

client = TestClient(app)


def _selection_seed(tier: str) -> int:
    with open(os.path.join(pv_play.SANDBOX_DIR, "selection_v2.json"), encoding="utf-8") as f:
        e = next(x for x in json.load(f)["levels"] if x["level"] == LEVEL)
    return int(e["base"]["seed"] if tier == "b" else e["tiers"][tier]["seed"])


V4_PATH = os.path.join(pv_play.SANDBOX_DIR, "selection_v4.json")


def _v4_entry(level: int) -> dict:
    with open(V4_PATH, encoding="utf-8") as f:
        return next(x for x in json.load(f)["levels"] if x["level"] == level)


def _count_tiles(lj: dict) -> int:
    n = 0
    for i in range(int(lj["layer"])):
        for t in lj.get(f"layer_{i}", {}).get("tiles", {}).values():
            n += int(t[2][0]) if t[0].startswith(("stack_", "craft_")) else 1
    return n


def test_levels_list():
    r = client.get("/api/pv-play/levels?selection=v2")
    assert r.status_code == 200
    assert r.json()["selection"] == "v2"
    lv = next(x for x in r.json()["levels"] if x["level"] == LEVEL)
    assert lv["status"] == "5tier"
    assert lv["availableTiers"] == ["orig", "e2", "e1", "b", "h1", "h2"]
    assert lv["seeds"]["b"] == _selection_seed("b")


@pytest.mark.parametrize("tier", ["b", "e2"])
def test_variant_types_hash_matches_cs_shuffle(tier):
    r = client.get(f"/api/pv-play/levels/{LEVEL}/{tier}?selection=v2")
    assert r.status_code == 200
    body = r.json()
    seed = _selection_seed(tier)
    assert body["seed"] == seed

    with open(T0_PATH, encoding="utf-8") as f:
        row = json.load(f)["row"]
    direct = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=row["useTileCount"], strict=True)
    assert body["typesHash"] == types_hash(direct.assigned)
    assert body["utc"] == int(row["useTileCount"])

    lj = body["levelJson"]
    tiles = [t[0] for i in range(lj["layer"]) for t in lj[f"layer_{i}"]["tiles"].values()]
    assert "t0" not in tiles  # 명시 맵 (프론트 재분배 없음)
    assert _count_tiles(lj) == body["tileCount"] == len(direct.assigned)


def test_orig_is_source_map():
    r = client.get(f"/api/pv-play/levels/{LEVEL}/orig")
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] is None and body["tier"] == "orig"
    src = pv_play._source_level(LEVEL)
    lj = body["levelJson"]
    for i in range(int(src["layer"])):
        a = {p: t[0] for p, t in src[f"layer_{i}"]["tiles"].items()}
        b = {p: t[0] for p, t in lj[f"layer_{i}"]["tiles"].items()}
        assert a == b
    # 원맵과 기준 시드는 같은 구조, 다른 배정
    assert body["structHash"] == client.get(f"/api/pv-play/levels/{LEVEL}/b?selection=v2").json()["structHash"]


def test_bad_tier_and_missing_tier():
    assert client.get(f"/api/pv-play/levels/{LEVEL}/zz").status_code == 400
    assert client.get(f"/api/pv-play/levels/{LEVEL}/b?selection=v9").status_code == 400
    lv = next(x for x in client.get("/api/pv-play/levels?selection=v2").json()["levels"] if not x["seeds"])
    assert client.get(f"/api/pv-play/levels/{lv['level']}/b?selection=v2").status_code == 404


v4 = pytest.mark.skipif(not os.path.exists(V4_PATH), reason="selection_v4.json 없음")


@v4
def test_v4_default_levels_tiers_and_utc():
    body = client.get("/api/pv-play/levels").json()
    assert body["selection"] == "v4"
    by = {x["level"]: x for x in body["levels"]}
    for lv, e in ((x["level"], _v4_entry(x["level"])) for x in body["levels"]):
        st = e["status"]
        want = (["orig", "e2", "e1", "b", "h1", "h2"] if st == "5tier"
                else ["orig", "e2", "b", "h2"] if st == "3tier" else ["orig"])
        assert by[lv]["status"] == st and by[lv]["availableTiers"] == want, lv
    l574 = by[574]
    assert l574["status"] == "3tier"
    e = _v4_entry(574)
    assert l574["seeds"]["b"] == int(e["base"]["seed"]) and l574["tierUtc"]["b"] == int(e["base"]["utc"])


@v4
def test_v4_tier_uses_tier_utc():
    e = _v4_entry(574)
    for tier, v in (("b", e["base"]), ("e2", e["tiers"]["e2"]), ("h2", e["tiers"]["h2"])):
        body = client.get(f"/api/pv-play/levels/574/{tier}").json()
        assert body["selection"] == "v4" and body["seed"] == int(v["seed"]) and body["utc"] == int(v["utc"])
        row = pv_play._t0_row(574)
        direct = shuffle_empty_tiles(row["map"], rand_seed=int(v["seed"]), use_tile_count=int(v["utc"]), strict=True)
        assert body["typesHash"] == types_hash(direct.assigned)
        used = {t[0] for i in range(body["levelJson"]["layer"])
                for t in body["levelJson"][f"layer_{i}"]["tiles"].values() if not t[0].startswith(("stack_", "craft_"))}
        assert len(used) <= int(v["utc"])
    assert client.get("/api/pv-play/levels/574/e1").status_code == 404  # 3단계: e1 없음
    fixed = next(x["level"] for x in client.get("/api/pv-play/levels").json()["levels"] if x["availableTiers"] == ["orig"])
    assert client.get(f"/api/pv-play/levels/{fixed}/b").status_code == 404
    assert client.get(f"/api/pv-play/levels/{fixed}/orig").status_code == 200


@v4
def test_v4_verification_badges():
    if not os.path.exists(os.path.join(pv_play.SANDBOX_DIR, "verify_v4", "_report.json")):
        pytest.skip("verify_v4 없음")
    by = {x["level"]: x for x in client.get("/api/pv-play/levels").json()["levels"]}
    assert by[55]["verification"]["verdict"] == "pass"
    v312 = by[312]["verification"]  # 07 §v4: e2 방향 실패 + |Δ|<0.08
    assert v312["verdict"] == "warn" and v312["tiers"]["e2"]["verdict"] == "warn"
    assert by[1218]["verification"] is None  # 고정맵: 검증 대상 아님
    tb = client.get("/api/pv-play/levels/312/e2").json()["verification"]
    assert tb["level"] == "warn" and tb["tier"]["verdict"] == "warn"


def test_result_append(tmp_path, monkeypatch):
    path = tmp_path / "manual_play" / "results.jsonl"
    monkeypatch.setattr(pv_play, "RESULTS_PATH", str(path))
    rec = {"level": LEVEL, "tier": "e2", "seed": _selection_seed("e2"), "won": True, "outcome": "won", "moves": 36,
           "boardRemainingApprox": 0, "blind": True, "playedAt": "2026-10-02T00:00:00Z"}  # 옛 형식(selection 없음)
    assert client.post("/api/pv-play/results", json=rec).status_code == 200
    lost = {**rec, "won": False, "outcome": "lost", "moves": 20, "boardRemainingApprox": 16}
    assert client.post("/api/pv-play/results", json=lost).status_code == 200
    assert client.post("/api/pv-play/results", json={**lost, "outcome": "abandoned", "moves": 3}).status_code == 200
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[2])["outcome"] == "abandoned"
    first = json.loads(lines[0])
    assert first["tier"] == "e2" and first["blind"] is True and "recordedAt" in first
    s = client.get("/api/pv-play/results/summary").json()["summary"]
    assert s[str(LEVEL)]["e2"] == {"attempts": 2, "wins": 1, "abandoned": 1}
    assert client.post("/api/pv-play/results", json={**rec, "tier": "x"}).status_code == 400
    assert client.post("/api/pv-play/results", json={**rec, "outcome": "lost"}).status_code == 400
    assert client.post("/api/pv-play/results", json={**rec, "outcome": "quit"}).status_code == 422
    # 새 필드: selection·utc 기록, 요약은 selection 별 (옛 기록 = v2)
    new = {**rec, "selection": "v4", "utc": 11}
    assert client.post("/api/pv-play/results", json=new).status_code == 200
    last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert last["selection"] == "v4" and last["utc"] == 11
    assert client.get("/api/pv-play/results/summary?selection=v4").json()["summary"][str(LEVEL)]["e2"] == {
        "attempts": 1, "wins": 1, "abandoned": 0}
    assert client.get("/api/pv-play/results/summary?selection=v2").json()["summary"][str(LEVEL)]["e2"] == {
        "attempts": 2, "wins": 1, "abandoned": 1}
    assert client.post("/api/pv-play/results", json={**new, "selection": "v9"}).status_code == 400


# ── DDA 세트 (selection=dda): 행 파일 그대로 로드 · 재배정 없음 ────────────────────────────
@pytest.fixture
def dda_dir(tmp_path, monkeypatch):
    """임시 dda_sets: 레벨 55 easy = 기준(v2 b) 시드 명시 맵 행 파일(easy/0055.json), hard = {"row":…} 래퍼 + map 문자열."""
    from app.core.pv.cs_shuffle import resolve_map
    with open(T0_PATH, encoding="utf-8") as f:
        row = json.load(f)["row"]
    def baked(seed):
        res = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=row["useTileCount"], strict=True)
        return {**row, "randSeed": "0", "map": resolve_map(row["map"], res)}, res
    easy_row, easy_res = baked(_selection_seed("e2"))
    hard_row, hard_res = baked(_selection_seed("h2"))
    (tmp_path / "easy").mkdir()
    (tmp_path / "easy" / "0055.json").write_text(json.dumps(easy_row), encoding="utf-8")
    (tmp_path / "rows").mkdir()
    (tmp_path / "rows" / "hard_55.json").write_text(json.dumps({"row": {**hard_row, "map": json.dumps(hard_row["map"])}}),
                                                    encoding="utf-8")
    sel = {"format": "pv_selection_dda", "levels": [
        {"level": LEVEL, "status": "ok", "easy": {"seed": _selection_seed("e2"), "deltaVsOrig": 0.2},
         "hard": {"seed": _selection_seed("h2"), "file": "rows/hard_55.json", "deltaVsOrig": -0.15}},
        {"level": 1218, "status": "boss_or_unevaluable"},
    ]}
    (tmp_path / "selection_dda.json").write_text(json.dumps(sel), encoding="utf-8")
    monkeypatch.setattr(pv_play, "DDA_DIR", str(tmp_path))
    pv_play._selection_cache.pop("dda", None)
    yield {"easy": easy_res, "hard": hard_res}
    pv_play._selection_cache.pop("dda", None)


def test_dda_levels_and_rows_loaded_as_is(dda_dir):
    body = client.get("/api/pv-play/levels?selection=dda").json()
    assert body["selection"] == "dda" and body["tiers"] == ["orig", "e2", "e1", "h1", "h2", "easy", "hard"]
    by = {x["level"]: x for x in body["levels"]}
    assert by[LEVEL]["availableTiers"] == ["orig", "easy", "hard"]
    assert by[1218]["availableTiers"] == ["orig"]
    for tier in ("easy", "hard"):
        r = client.get(f"/api/pv-play/levels/{LEVEL}/{tier}?selection=dda")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["selection"] == "dda" and b["tier"] == tier
        assert b["typesHash"] == types_hash(dda_dir[tier].assigned)  # 행 그대로 (재배정 없음)
        assert b["tileCount"] == len(dda_dir[tier].assigned)
    assert client.get(f"/api/pv-play/levels/{LEVEL}/orig?selection=dda").status_code == 200
    assert client.get(f"/api/pv-play/levels/{LEVEL}/b?selection=dda").status_code == 400
    assert client.get(f"/api/pv-play/levels/1218/easy?selection=dda").status_code == 404


def test_dda_result_source(dda_dir, tmp_path, monkeypatch):
    path = tmp_path / "res" / "results.jsonl"
    monkeypatch.setattr(pv_play, "RESULTS_PATH", str(path))
    rec = {"level": LEVEL, "tier": "easy", "seed": None, "won": True, "outcome": "won", "moves": 36,
           "blind": True, "selection": "dda", "utc": 8}
    assert client.post("/api/pv-play/results", json=rec).status_code == 200
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["source"] == "dda"
    assert client.post("/api/pv-play/results", json={**rec, "tier": "b"}).status_code == 400  # DDA 에 기준 b 없음
    assert client.get("/api/pv-play/results/summary?selection=dda").json()["summary"][str(LEVEL)]["easy"]["wins"] == 1


def test_dda_pv_dda_layout(tmp_path, monkeypatch):
    """pv_dda.py 산출 형식: tiers.e2/h2 {key "utc:seed", token} + work/{N:04d}/baked_easy|hard.json."""
    from app.core.pv.cs_shuffle import resolve_map
    with open(T0_PATH, encoding="utf-8") as f:
        row = json.load(f)["row"]
    utc = int(row["useTileCount"])
    tiers, expect = {}, {}
    (tmp_path / "work" / f"{LEVEL:04d}").mkdir(parents=True)
    for name, t in (("easy", "e2"), ("hard", "h2")):
        seed = _selection_seed(t)
        res = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=utc, strict=True)
        (tmp_path / "work" / f"{LEVEL:04d}" / f"baked_{name}.json").write_text(
            json.dumps({**row, "map": resolve_map(row["map"], res), "useTileCount": str(utc)}), encoding="utf-8")
        tiers[t] = {"key": f"{utc}:{seed}", "token": str(seed), "delta": 0.12 if name == "easy" else -0.12}
        expect[name] = (seed, types_hash(res.assigned))
    (tmp_path / "selection_dda.json").write_text(json.dumps({"levels": [{"level": LEVEL, "status": "3tier", "tiers": tiers}]}),
                                                  encoding="utf-8")
    monkeypatch.setattr(pv_play, "DDA_DIR", str(tmp_path))
    pv_play._selection_cache.pop("dda", None)
    try:
        lv = client.get("/api/pv-play/levels?selection=dda").json()["levels"][0]
        assert lv["availableTiers"] == ["orig", "easy", "hard"] and lv["deltas"] == {"easy": 0.12, "hard": -0.12}
        for name, (seed, th) in expect.items():
            b = client.get(f"/api/pv-play/levels/{LEVEL}/{name}?selection=dda").json()
            assert b["seed"] == seed and b["typesHash"] == th and b["utc"] == utc
    finally:
        pv_play._selection_cache.pop("dda", None)


def test_dda_seedvar_primary(tmp_path, monkeypatch):
    """IMPL_SPEC §V2-9-2: seedvar_N = t0 사본 맵 + 토큰 e2|e1|h1|h2 (b 없음). 토큰 칸은 cs_shuffle 배정,
    reference_baked easy/hard 는 보조 칸."""
    from app.core.pv.cs_shuffle import resolve_map
    with open(T0_PATH, encoding="utf-8") as f:
        row = json.load(f)["row"]
    utc = int(row["useTileCount"])
    seeds = {t: _selection_seed(t) for t in ("e2", "e1", "h1", "h2")}
    token = "|".join(str(seeds[t]) for t in ("e2", "e1", "h1", "h2"))
    (tmp_path / "seedvar").mkdir()
    (tmp_path / "seedvar" / f"seedvar_{LEVEL}.json").write_text(
        json.dumps({**row, "id": f"seedvar_{LEVEL}", "randSeed": token}), encoding="utf-8")
    (tmp_path / "reference_baked").mkdir()
    res_e2 = shuffle_empty_tiles(row["map"], rand_seed=seeds["e2"], use_tile_count=utc, strict=True)
    (tmp_path / "reference_baked" / f"easy_{LEVEL}.json").write_text(
        json.dumps({**row, "id": f"easy_{LEVEL}", "map": resolve_map(row["map"], res_e2)}), encoding="utf-8")
    (tmp_path / "selection_dda.json").write_text(json.dumps({"levels": [
        {"level": LEVEL, "status": "5tier", "token": token, "utc0": utc,
         "tiers": {"e2": {"key": f"{utc}:{seeds['e2']}", "token": str(seeds["e2"]), "delta": 0.16}}}]}), encoding="utf-8")
    monkeypatch.setattr(pv_play, "DDA_DIR", str(tmp_path))
    pv_play._selection_cache.pop("dda", None)
    try:
        lv = client.get("/api/pv-play/levels?selection=dda").json()["levels"][0]
        assert lv["availableTiers"] == ["orig", "e2", "e1", "h1", "h2", "easy"]
        assert "b" not in lv["seeds"] and lv["seeds"]["h1"] == seeds["h1"]
        for t in ("e2", "h1"):
            b = client.get(f"/api/pv-play/levels/{LEVEL}/{t}?selection=dda").json()
            direct = shuffle_empty_tiles(row["map"], rand_seed=seeds[t], use_tile_count=utc, strict=True)
            assert b["seed"] == seeds[t] and b["typesHash"] == types_hash(direct.assigned)
        # 보조 구운 행 easy == 토큰 e2 배정 (같은 보드)
        assert client.get(f"/api/pv-play/levels/{LEVEL}/easy?selection=dda").json()["typesHash"] == types_hash(res_e2.assigned)
        assert client.get(f"/api/pv-play/levels/{LEVEL}/b?selection=dda").status_code == 400
    finally:
        pv_play._selection_cache.pop("dda", None)
