"""무한 사본 그림 치환 v1 (app.core.infinity_relabel) — 규칙 단위 · 경로별 일관성 · 판정 근거 binding.

외부 통신 없음: conftest 가 전송 계층을 차단하고, 업로드 경로는 메모리 가짜 서버를 의존성으로 주입한다.
기준 벡터 = sp_meowsgarden tools/dda_level_fix/relabel_infinity.py 가 만든 out/relabel_v1/vectors.json (2026-11-02)
에서 (N, h, types, mapping) 을 옮겨 고정. 같은 폴더 infinity_maps.json 이 있으면 1,030행 전체 바이트 대조도 한다.
"""
from __future__ import annotations

import copy
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gboost
from app.api.routes import gboost as gb_routes
from app.api.routes.gboost import _convert_to_townpop_format as conv
from app.core import dda_seed_catalog as c
from app.core import infinity_relabel as R
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)
client = TestClient(app)
REF_DIR = os.path.expanduser("~/sp_meowsgarden/tools/dda_level_fix/out")


def lv(n, **kw):
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(kw)
    return j


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


# ── 규칙 단위 ──────────────────────────────────────────────────────────────────

VECTORS = [  # (N, h, types, mapping) — out/relabel_v1/vectors.json
    (1, 941128451, [1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 15], {'t1': 't14', 't2': 't1', 't3': 't10', 't4': 't6', 't5': 't13', 't6': 't2', 't10': 't5', 't11': 't3', 't12': 't15', 't13': 't4', 't14': 't12', 't15': 't11'}),
    (2, 601553860, [1, 2, 4, 5, 6, 7, 9, 10, 12, 13, 14, 15], {'t1': 't7', 't2': 't6', 't4': 't5', 't5': 't1', 't6': 't13', 't7': 't15', 't9': 't12', 't10': 't9', 't12': 't2', 't13': 't4', 't14': 't10', 't15': 't14'}),
    (10, 1738339065, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15], {'t2': 't14', 't3': 't11', 't4': 't6', 't5': 't8', 't6': 't15', 't7': 't10', 't8': 't3', 't9': 't12', 't10': 't2', 't11': 't9', 't12': 't7', 't14': 't4', 't15': 't5'}),
    (41, 3110988739, [2, 3, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15], {'t2': 't11', 't3': 't13', 't5': 't6', 't6': 't14', 't7': 't3', 't9': 't2', 't10': 't5', 't11': 't15', 't12': 't7', 't13': 't9', 't14': 't12', 't15': 't10'}),
    (141, 2309274698, [2, 3, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15], {'t2': 't11', 't3': 't15', 't5': 't3', 't6': 't9', 't8': 't12', 't9': 't13', 't10': 't2', 't11': 't5', 't12': 't10', 't13': 't14', 't14': 't8', 't15': 't6'}),
    (500, 1588207015, [1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15], {'t1': 't10', 't2': 't12', 't3': 't14', 't5': 't1', 't6': 't2', 't8': 't15', 't9': 't5', 't10': 't11', 't11': 't8', 't12': 't9', 't13': 't3', 't14': 't6', 't15': 't13'}),
    (1030, 315027132, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15], {'t1': 't7', 't2': 't15', 't3': 't8', 't4': 't3', 't5': 't12', 't6': 't14', 't7': 't13', 't8': 't9', 't9': 't6', 't10': 't2', 't12': 't10', 't13': 't4', 't14': 't5', 't15': 't1'}),
]


@pytest.mark.parametrize("n,h,types,mapping", VECTORS)
def test_reference_vectors_hash_and_mapping(n, h, types, mapping):
    assert R.rule_key(n) == f"infinity_{n}|relabel.v1"
    assert R.fnv1a32(R.rule_key(n)) == h
    mp = R.mapping_for(n, types)
    assert {f"t{k}": f"t{v}" for k, v in sorted(mp.items())} == mapping
    assert all(k != v for k, v in mp.items())                    # Sattolo: 모든 종류가 바뀜
    assert sorted(mp.values()) == sorted(mp) == types           # 같은 종류 집합의 순열


def test_fnv_known_values():
    assert R.fnv1a32("") == 2166136261
    assert R.fnv1a32("a") == 0xE40C292C                         # FNV-1a 32 표준 값


def test_sattolo_i1_consumes_rng_and_effect_key_excluded(monkeypatch):
    # i=1 단계도 Rand(0,0) → _rand() 1회 소비(zWellRandom.cs Rand: e-s+1=1 ≠ 0). K 종류면 정확히 K-1 회.
    made = []
    orig = R.ZWellRandom

    def spy(seed):
        z = orig(seed)
        made.append(z)
        return z
    monkeypatch.setattr(R, "ZWellRandom", spy)
    R.mapping_for(3, [1, 2, 3, 4, 5])
    assert made[-1].calls == 4
    z = orig(R.fnv1a32(R.rule_key(3)))
    for i in range(4, 0, -1):
        z.rand(0, i - 1)
    assert z.calls == 4 and z._state == made[-1]._state
    # 효과 "key" 칸은 집계·치환 모두 제외(DB_Level.cs:234)
    m = {"layer": 1, "layer_0": {"tiles": {"0_0": ["t2", "key"], "1_0": ["t5", ""], "2_0": ["t9", ""], "3_0": ["t2", "KEY"]}}}
    assert R.types_of(m) == [5, 9]
    o, mp = R.relabel_level_json(m, 1)
    assert o["layer_0"]["tiles"]["0_0"] == ["t2", "key"] and o["layer_0"]["tiles"]["3_0"] == ["t2", "KEY"]
    assert mp == {5: 9, 9: 5}


HAND = {"layer": 2, "useTileCount": 3,
        "layer_0": {"col": 7, "row": 7, "tiles": {
            "0_0": ["t1", ""], "1_0": ["t3", "ice"], "2_0": ["t16", ""], "3_0": ["t2", "key"], "4_0": ["t0", ""],
            "5_0": ["stack_e", "", [4, "t3_t1_key_t7"]], "6_0": ["craft_s", "", [3]], "0_1": ["stack_n", "", [3, "t1_t2"]]}},
        "layer_1": {"col": 8, "row": 8, "tiles": {}},
        "layer_2": {"col": 8, "row": 8, "tiles": {"0_0": ["t9", ""]}}}   # layer=2 → layer_2 는 변환 밖(무시)


def test_hand_map_rule():
    src = copy.deepcopy(HAND)
    assert R.types_of(src) == [1, 3, 7]   # ['t2','key'] = 열쇠, 't1_t2' 내부 수 불일치 → 무시, layer_2 밖
    out, mp = R.relabel_level_json(src, 7)
    assert dump(src) == dump(HAND)                                # 입력 불변
    out2, mp2 = R.relabel_level_json(HAND, 7)
    assert dump(out) == dump(out2) and mp == mp2                  # 결정적
    assert all(k != v for k, v in mp.items()) and sorted(mp.values()) == [1, 3, 7]
    t = out["layer_0"]["tiles"]
    assert t["0_0"] == [f"t{mp[1]}", ""] and t["1_0"] == [f"t{mp[3]}", "ice"]
    assert t["2_0"] == ["t16", ""] and t["3_0"] == ["t2", "key"] and t["4_0"] == ["t0", ""]
    assert t["5_0"] == ["stack_e", "", [4, f"t{mp[3]}_t{mp[1]}_key_t{mp[7]}"]]
    assert t["6_0"] == ["craft_s", "", [3]] and t["0_1"] == ["stack_n", "", [3, "t1_t2"]]
    assert out["layer_2"] == HAND["layer_2"] and out["layer_1"] == HAND["layer_1"]
    assert {k: v for k, v in out.items() if k != "layer_0"} == {k: v for k, v in HAND.items() if k != "layer_0"}
    assert conv(copy.deepcopy(out))["useTileCount"] == conv(copy.deepcopy(HAND))["useTileCount"] == "3"


def test_k_lt_2_no_change_and_id_gate():
    one = {"layer": 1, "layer_0": {"col": 7, "row": 7, "tiles": {"0_0": ["t4", ""], "1_0": ["t4", ""], "2_0": ["t4", ""]}}}
    out, mp = R.relabel_level_json(one, 5)
    assert mp == {} and out == one
    j = lv(158)
    for tid in ("level_658", "infinity_0", "infinity_", "inf_3", "infinity_03", "Infinity_3", None):
        o, info = R.prepare_export_level_json(tid, j, True)
        assert o is j and info is None, tid
    o, info = R.prepare_export_level_json("infinity_3", j, False)            # 끔
    assert o is j and info is None
    o, info = R.prepare_export_level_json("infinity_3", j, True)
    assert info["rule"] == "relabel.v1" and info["slot"] == 3 and info["mapping"]
    assert dump(o) != dump(j) and dump(j) == dump(lv(158))


@pytest.mark.parametrize("n", [5, 40, 111, 158, 159, 322, 1466])
def test_layout_and_counts_preserved_on_fixture_levels(n):
    j = lv(n)
    o, info = R.prepare_export_level_json("infinity_9", j, True)
    a, b = conv(copy.deepcopy(j)), conv(copy.deepcopy(o))
    assert a["useTileCount"] == b["useTileCount"]
    assert {k: v for k, v in a.items() if k not in ("map", "etime")} == {k: v for k, v in b.items() if k not in ("map", "etime")}
    inv = {v: k for k, v in info["mapping"].items()}
    for lk, la in a["map"].items():
        if not lk.startswith("layer_"):
            assert la == b["map"][lk]
            continue
        lb = b["map"][lk]
        assert list(la["tiles"]) == list(lb["tiles"]) and la["num"] == lb["num"]
        for p, ca in la["tiles"].items():
            cb = lb["tiles"][p]
            assert len(ca) == len(cb) and ca[1:2] == cb[1:2]                  # 효과 불변
            is_key = len(cb) > 1 and isinstance(cb[1], str) and cb[1].lower() == "key"
            if R._NORMAL_RE.match(cb[0]) and not is_key:
                assert inv[cb[0]] == ca[0]                                     # 칸 id = 매핑의 역으로 원본 복원
            else:
                assert cb[0] == ca[0]                                          # 열쇠·t0·컨테이너 이름 불변
            if len(ca) > 2:
                ta, tb = ca[2], cb[2]
                assert ta[:1] == tb[:1] and len(ta) == len(tb)
                if len(ta) > 1 and isinstance(ta[1], str) and ta[1] != tb[1]:
                    assert [inv.get(x, x) for x in tb[1].split("_")] == ta[1].split("_")


@pytest.mark.skipif(not os.path.exists(os.path.join(REF_DIR, "relabel_v1", "infinity_maps.json")),
                    reason="sp_meowsgarden 기준 산출물 없음")
def test_full_1030_rows_byte_identical_to_reference():
    batch = json.load(open(os.path.join(REF_DIR, "batch_final_dryrun.v2.json")))
    src = {L["meta"]["level_number"]: L["level_json"] for L in batch["levels"]}
    ref_raw = open(os.path.join(REF_DIR, "relabel_v1", "infinity_maps.json"), "rb").read()
    ref = json.loads(ref_raw)
    import hashlib
    sha = lambda o: hashlib.sha256(dump(o).encode()).hexdigest()  # noqa: E731
    mine = {}
    for n in range(1, 1031):
        o, info = R.prepare_export_level_json(f"infinity_{n}", src[500 + n], True)
        t, t0 = conv(copy.deepcopy(o)), conv(copy.deepcopy(src[500 + n]))
        mine[f"infinity_{n}"] = {"map": t["map"], "useTileCount": t["useTileCount"], "mapping": info["mapping"],
                                 "sourceMapSha256": sha(t0["map"]), "mapSha256": sha(t["map"])}
        assert t["useTileCount"] == t0["useTileCount"]
        assert c.map_sha256(t) == ref[f"infinity_{n}"]["mapSha256"]
    assert dump(mine).encode() == ref_raw


# ── 경로별 일관성 (업로드 · upload-local · export-preview · JSON 내보내기 API · 시드만 내보내기) ─────

class FakeServer:
    is_configured = True
    base_url, project_id = "fake://", "fake"

    def __init__(self):
        self.saved = []

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        return None

    async def save_level(self, board_id, level_id, level_json):
        self.saved.append((board_id, level_id, json.loads(json.dumps(level_json))))
        return {"success": True}

    async def save_thumbnail(self, *a, **k):
        return {"success": True}


@pytest.fixture
def server():
    s = FakeServer()
    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: s
    yield s
    app.dependency_overrides[get_gboost] = prev


def _saved_map(server, level_id):
    rows = [x for x in server.saved if x[1] == level_id]
    assert rows and len({dump(x[2]["map"]) for x in rows}) == 1     # 보드가 달라도 같은 map
    return rows[-1][2]


def test_all_paths_same_relabelled_map(server, monkeypatch, tmp_path):
    j = lv(158)
    expect_lj, info = R.prepare_export_level_json("infinity_7", j, True)
    expect = conv(copy.deepcopy(expect_lj))
    plain = conv(copy.deepcopy(j))
    assert dump(expect["map"]) != dump(plain["map"]) and expect["useTileCount"] == plain["useTileCount"]

    # 1) 업로드 화면 경로 (POST /api/gboost/{board}/{id}) — 기본값 = 켬
    for board in ("levels", "test_board"):
        for tid in ("infinity_7", "level_158"):
            r = client.post(f"/api/gboost/{board}/{tid}", json={"level_json": j})
            assert r.status_code == 200, r.text
    assert dump(_saved_map(server, "infinity_7")["map"]) == dump(expect["map"])
    assert dump(_saved_map(server, "level_158")["map"]) == dump(plain["map"])          # 정식 행 불변
    assert all(x[2]["useTileCount"] == plain["useTileCount"] for x in server.saved)
    assert "그림 치환 relabel.v1" in client.post("/api/gboost/x/infinity_7", json={"level_json": j}).json()["message"]

    # 2) JSON 내보내기용 API — 같은 함수, 입력 level_json 불변
    r = client.post("/api/dda-seeds/infinity-relabel", json={"levels": [
        {"target_id": "infinity_7", "level_json": j}, {"target_id": "level_158", "level_json": j}]}).json()
    assert dump(r["results"][0]["level_json"]) == dump(expect_lj) and r["results"][0]["relabel"] == info
    assert dump(r["results"][1]["level_json"]) == dump(j) and r["results"][1]["relabel"] is None
    assert dump(conv(copy.deepcopy(r["results"][0]["level_json"]))["map"]) == dump(expect["map"])

    # 3) upload-local (대상 id infinity_7)
    monkeypatch.setattr(gb_routes, "LOCAL_LEVELS_DIR", tmp_path)
    (tmp_path / "loc1.json").write_text(json.dumps({"level_data": j}), encoding="utf-8")
    server.saved.clear()
    r = client.post("/api/gboost/upload-local", json={"board_id": "test_board", "level_ids": ["loc1"],
                                                      "rename_strategy": "custom", "custom_names": {"loc1": "infinity_7"},
                                                      "overwrite": True})
    assert r.status_code == 200, r.text
    assert dump(_saved_map(server, "infinity_7")["map"]) == dump(expect["map"])

    # 4) 끄면 모든 경로가 원본 그대로
    server.saved.clear()
    client.post("/api/gboost/test_board/infinity_7", json={"level_json": j, "infinity_relabel": False})
    assert dump(_saved_map(server, "infinity_7")["map"]) == dump(plain["map"])
    r = client.post("/api/dda-seeds/infinity-relabel", json={"levels": [{"target_id": "infinity_7", "level_json": j}],
                                                             "infinity_relabel": False}).json()
    assert dump(r["results"][0]["level_json"]) == dump(j) and r["results"][0]["relabel"] is None


# ── 판정 근거 binding: 무한 행 map sha = 치환 후 맵 ─────────────────────────────────

def _inf_seeds(binding_townpop):
    return {"infinity_7": {"ddaEasySeeds": "11,12,13", "ddaSeedVerdicts": {
        "binding": {"mapSha256": c.map_sha256(binding_townpop), "useTileCount": binding_townpop["useTileCount"]},
        "ddaEasySeeds": [{"seed": s, "verdict": "PATH"} for s in (11, 12, 13)]}}}


def test_binding_uses_relabelled_map(server):
    base = lv(158)
    relab = conv(copy.deepcopy(R.prepare_export_level_json("infinity_7", base, True)[0]))
    plain = conv(copy.deepcopy(base))
    j_relab = lv(158, ddaInfinitySeeds=_inf_seeds(relab))     # 근거가 치환본 기준
    j_plain = lv(158, ddaInfinitySeeds=_inf_seeds(plain))     # 근거가 옛 원본 복사 기준

    def prev(j, on=True):
        r = client.post("/api/dda-seeds/export-preview", json={"board_id": "levels", "infinity_relabel": on,
                                                               "levels": [{"target_id": "infinity_7", "level_json": j}]}).json()
        return r["results"][0]

    p = prev(j_relab)
    assert p["ddaEasySeeds"] == "11,12,13" and p["fieldEvidence"]["ddaEasySeeds"] == "ok"
    assert p["relabel"]["rule"] == "relabel.v1" and p["relabel"]["slot"] == 7
    assert prev(j_plain)["fieldEvidence"]["ddaEasySeeds"] == "binding_mismatch"
    assert prev(j_plain, on=False)["fieldEvidence"]["ddaEasySeeds"] == "ok"            # 끄면 원본 기준
    assert "relabel" not in prev(j_plain, on=False)

    # 실제 업로드(levels 보드, 새 행) — 치환본 근거면 시드 전송, 옛 근거면 미전송(서버 값 유지)
    r = client.post("/api/gboost/levels/infinity_7", json={"level_json": j_relab})
    assert r.status_code == 200, r.text
    row = _saved_map(server, "infinity_7")
    assert row["ddaEasySeeds"] == "11,12,13" and c.map_sha256(row) == c.map_sha256(relab)
    assert "ddaSeedVerdicts" not in row and "ddaInfinitySeeds" not in row
    server.saved.clear()
    r = client.post("/api/gboost/levels/infinity_7", json={"level_json": j_plain})
    assert r.status_code == 200 and "ddaEasySeeds" not in _saved_map(server, "infinity_7")
    assert "미검증 새 시드 미전송: ddaEasySeeds" in r.json()["message"]
