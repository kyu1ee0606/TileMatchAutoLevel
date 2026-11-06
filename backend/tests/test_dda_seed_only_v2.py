"""DDA 시드만 내보내기 v2 (PLAN_DDA_SEED_ONLY_EXPORT_FIX_20261103) · 일반 업로드 썸네일 생략 · solve_level_task 시간 제한.

외부 통신 없음: 메모리 가짜 서버(FakeBoard)를 의존성으로 주입하고, 배치 파일 폴더·시험 기록 폴더·장부 폴더는 tmp_path.
"""
from __future__ import annotations

import copy
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gboost
from app.api.routes import gboost as gb_routes
from app.api.routes import production_store as ps
from app.api.routes.gboost import _convert_to_townpop_format as conv
from app.core import dda_seed_catalog as c
from app.core import dda_seed_ledger as L
from app.core import infinity_relabel as inf
from app.core import solver
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)
client = TestClient(app)

BOARD_KEYS = ['id', 'idx', 'etime', 'backgroundIndex', 'tileSkin', 'timea', 'unlockTile', 'col', 'row', 'rewardCoin',
              'useInRandomizer', 'randSeed', 'ddaEasy2Seeds', 'ddaEasySeeds', 'ddaHardSeeds', 'ddaHard2Seeds',
              'shuffleLayer', 'shuffleTile', 'difficulty', '', 'useTeleportInRandomizer', 'teleportRandSeed',
              'autoCollectCount', 'visualTileSeed', 'num', 'sets', 'layer', 'field4', 'useTileCount', 'typeImbalance',
              'rewardList', 'map']
BATCH = "batch_test_seedfix"


def lv(n: int, **kw) -> dict:
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(kw)
    return j


def verdicts(j: dict, target_id: str = "", **cols) -> dict:
    src, _ = inf.prepare_export_level_json(target_id, j, True) if target_id else (j, None)
    tp = conv(dict(src))
    ev = {"binding": {"mapSha256": c.map_sha256(tp), "useTileCount": tp["useTileCount"]}}
    for f, seeds in cols.items():
        ev[f] = [{"seed": s, "verdict": "PATH", "nodes": 7} for s in seeds]
    return ev


def srow(target_id: str, j: dict, relabel: bool = True, **seeds) -> dict:
    """서버 행: 배치 level_json(무한이면 relabel) 변환 map·useTileCount + 시드 4열(기본 "")."""
    src, _ = inf.prepare_export_level_json(target_id, j, relabel)
    tp = conv(dict(src))
    row = {k: "" for k in BOARD_KEYS}
    row.update({"id": target_id, "idx": "1", "etime": "1790000000", "map": tp["map"],
                "useTileCount": int(tp["useTileCount"]), "rewardList": None})
    for f in c.EXPORT_SEED_FIELDS:
        row[f] = seeds.get(f, "")
    return row


class FakeBoard:
    is_configured = True
    base_url, project_id = "fake://", "fake"

    def __init__(self, rows=None, fail_update=(), corrupt_other=None, keys=None, base_url="https://gb.example/api",
                 project_id="p1", on_board_load=None, on_update=None):
        self.base_url, self.project_id = base_url, project_id
        self.on_board_load, self.on_update = on_board_load, on_update
        self.rows = rows or {}
        self.keys = keys or BOARD_KEYS
        self.fail_update = set(fail_update)
        self.corrupt_other = corrupt_other
        self.board_loads = 0
        self.level_loads = 0
        self.updates, self.saved, self.thumbs = [], [], []

    async def load_board_rows(self, board_id):
        self.board_loads += 1
        if self.on_board_load:
            self.on_board_load(self)
        return {"rows": copy.deepcopy(self.rows), "keys": list(self.keys),
                "raw_sha256": f"raw{self.board_loads}", "raw_bytes": 0}

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        self.level_loads += 1
        r = self.rows.get(level_id)
        return None if r is None else {"level_json": copy.deepcopy(r), "metadata": {}}

    async def update_existing_level(self, board_id, level_id, row):
        exc = getattr(self, "raise_on", {}).get(level_id)
        if exc is not None:
            raise exc
        self.updates.append((level_id, json.loads(json.dumps(row))))
        if level_id in self.fail_update:
            return {"success": False, "error": "fake fail"}
        self.rows[level_id].update(row)                          # 보내지 않은 열 = 서버 값 유지
        self.rows[level_id]["etime"] = str(int(self.rows[level_id]["etime"]) + 1)
        if self.corrupt_other:
            self.rows[self.corrupt_other]["rewardCoin"] = 99
        if self.on_update:
            self.on_update(self)
        return {"success": True}

    async def save_level(self, board_id, level_id, level_json):
        self.saved.append((level_id, json.loads(json.dumps(level_json))))
        return {"success": True}

    async def save_thumbnail(self, board_id, level_id, data, size=128):
        self.thumbs.append(level_id)
        return {"success": True}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "_STORE_DIR", str(tmp_path / "production"))
    monkeypatch.setattr(c, "PARTIAL_TRIAL_DIR", str(tmp_path / "trials"))
    monkeypatch.setenv("DDA_SEED_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setattr(L, "_auto_sessions", {})
    os.makedirs(tmp_path / "production")
    return tmp_path


@pytest.fixture
def server():
    holder = {}
    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: holder["s"]

    def use(s):
        holder["s"] = s
        return s
    yield use
    app.dependency_overrides[get_gboost] = prev


def write_batch(levels: dict, version: int = 5) -> None:
    doc = {"batch_id": BATCH, "batch": {"name": "t"}, "version": version, "saved_at": 0,
           "levels": [{"meta": {"level_number": n}, "level_json": j} for n, j in levels.items()]}
    with open(os.path.join(ps._STORE_DIR, f"{BATCH}.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)


def call(targets, *, dry_run=True, version=5, sha=None, confirm=False, trial=False, relabel=True, dirty=0, raw=False,
         preview_id=None, selection=None):
    body = {"batch_id": BATCH, "expected_batch_version": version, "targets": targets, "dry_run": dry_run,
            "confirm": confirm, "trial": trial, "infinity_relabel": relabel, "client_unsynced_edits": dirty,
            "preview_id": preview_id, "selection": selection}
    if sha:
        body["expected_batch_sha256"] = sha
    r = client.post("/api/gboost/dda-seed-export", json=body)
    return r if raw else r.json()


def upload(targets, pre, **kw):
    dig = {x["target_id"]: x.get("serverDigest") for x in pre["results"]}
    t2 = [dict(t, expected_server_digest=dig.get(t["target_id"])) for t in targets]
    kw.setdefault("preview_id", pre.get("preview_id"))
    return call(t2, dry_run=False, sha=pre["batchFileSha256"], **kw)


@pytest.fixture
def gate_open(monkeypatch):
    monkeypatch.setattr(c, "PARTIAL_UPDATE_VERIFIED", True)


def j158_four():
    j = lv(158, ddaEasy2Seeds="1,2,3", ddaEasySeeds="4,5,6", ddaHardSeeds="7,8,9")
    j[c.SEED_EVIDENCE_KEY] = verdicts(j, ddaEasy2Seeds=[1, 2, 3], ddaEasySeeds=[4, 5, 6])   # Hard 근거 없음
    return j


# ── 4칸 시드 ─────────────────────────────────────────────────────────────────────
def test_four_columns_cell_states_and_payload(server, gate_open):
    j = j158_four()
    write_batch({158: j})
    s = server(FakeBoard({"level_158": srow("level_158", j, ddaEasySeeds="4,5,6", ddaHard2Seeds="10,11,12")}))
    T = [{"target_id": "level_158", "source_level": 158}]
    pre = call(T)
    cells = pre["results"][0]["cells"]
    assert {f: x["state"] for f, x in cells.items()} == {
        "ddaEasy2Seeds": "send", "ddaEasySeeds": "same", "ddaHardSeeds": "unverified", "ddaHard2Seeds": "kept"}
    assert pre["summary"]["cells"] == {"send": 1, "same": 1, "kept": 1, "unverified": 1, "blocked": 0}
    assert cells["ddaEasy2Seeds"]["kind"] == "fill" and not s.updates
    r = upload(T, pre)
    assert r["results"][0]["status"] == "saved"
    assert s.updates == [("level_158", {"ddaEasy2Seeds": "1,2,3"})]        # 바뀌고 근거 있는 열만
    assert s.rows["level_158"]["ddaHard2Seeds"] == "10,11,12" and not s.thumbs and not s.saved


def test_change_needs_confirm_and_same_row_unchanged(server, gate_open):
    j = lv(158, ddaEasySeeds="4,5,6")
    j[c.SEED_EVIDENCE_KEY] = verdicts(j, ddaEasySeeds=[4, 5, 6])
    write_batch({158: j, 159: lv(159)})
    s = server(FakeBoard({"level_158": srow("level_158", j, ddaEasySeeds="1,2,3"),
                          "level_159": srow("level_159", lv(159), ddaHardSeeds="7,8,9")}))
    T = [{"target_id": "level_158", "source_level": 158}, {"target_id": "level_159", "source_level": 159}]
    pre = call(T)
    assert pre["results"][0]["change"] == "change"
    r = {x["target_id"]: x for x in upload(T, pre)["results"]}
    assert r["level_158"]["reason"] == "needs_dda_confirm" and r["level_159"]["status"] == "unchanged"
    assert not s.updates
    r = upload(T, call(T), confirm=True)
    assert r["results"][0]["status"] == "saved" and s.updates == [("level_158", {"ddaEasySeeds": "4,5,6"})]


def test_old_five_token_catalog_value_not_sent_and_no_empty_payload(server, gate_open):
    e = c.load_catalog()["_byLevel"][158]
    j = lv(158, ddaEasySeeds=e["ddaEasySeeds"])                  # v1 목록 5개 값 → 생략(LEGACY_CATALOG_EXPORT False)
    write_batch({158: j})
    s = server(FakeBoard({"level_158": srow("level_158", j, ddaEasySeeds="1,2,3")}))
    T = [{"target_id": "level_158", "source_level": 158}]
    pre = call(T)
    assert pre["results"][0]["cells"]["ddaEasySeeds"]["state"] == "kept"
    assert upload(T, pre)["results"][0]["status"] == "unchanged" and not s.updates


# ── 무한 relabel ─────────────────────────────────────────────────────────────────
def test_infinity_row_uses_infinity_seeds_with_relabel(server, gate_open):
    j = lv(158, ddaHardSeeds="7,8,9")                            # 정식 시드 — 무한 행엔 쓰지 않음
    ent = {"ddaHardSeeds": "11,12,13"}
    ent[c.SEED_EVIDENCE_KEY] = verdicts(j, "infinity_7", ddaHardSeeds=[11, 12, 13])
    j[c.INFINITY_SEEDS_KEY] = {"infinity_7": ent}
    write_batch({158: j})
    s = server(FakeBoard({"infinity_7": srow("infinity_7", j)}))
    T = [{"target_id": "infinity_7", "source_level": 158}]
    pre = call(T)
    st = {f: x["state"] for f, x in pre["results"][0]["cells"].items()}
    assert st == {"ddaEasy2Seeds": "kept", "ddaEasySeeds": "kept", "ddaHardSeeds": "send", "ddaHard2Seeds": "kept"}
    assert upload(T, pre)["results"][0]["status"] == "saved"
    assert s.updates == [("infinity_7", {"ddaHardSeeds": "11,12,13"})]


def test_infinity_relabel_mismatch_blocks(server, gate_open):
    j = lv(158)
    j[c.INFINITY_SEEDS_KEY] = {"infinity_7": {"ddaHardSeeds": "11,12,13"}}
    write_batch({158: j})
    # 서버 map = relabel 안 한 정식 map → 배치(relabel 본)와 다름
    server(FakeBoard({"infinity_7": srow("infinity_7", j, relabel=False)}))
    r = call([{"target_id": "infinity_7", "source_level": 158}])["results"][0]
    assert (r["blocked"], r["reason"]) == (True, "server_map_differs")
    # 서버 relabel 본 + 요청 relabel 끔 → 다름
    server(FakeBoard({"infinity_7": srow("infinity_7", j)}))
    r = call([{"target_id": "infinity_7", "source_level": 158}], relabel=False)["results"][0]
    assert r["reason"] == "server_map_differs"


# ── 옛 버전 409 · 미동기 편집 차단 · 배치 파일이 값 출처 ────────────────────────────────
def test_batch_version_mismatch_409_and_changed_since_preview(server, gate_open):
    j = j158_four()
    write_batch({158: j}, version=5)
    s = server(FakeBoard({"level_158": srow("level_158", j)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    r = call(T, version=4, raw=True)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "batch_version_mismatch"
    pre = call(T)
    write_batch({158: lv(158, ddaEasy2Seeds="3,2,1")}, version=5)          # 같은 버전, 파일 내용 바뀜
    dig = pre["results"][0]["serverDigest"]
    r = call([dict(T[0], expected_server_digest=dig)], dry_run=False, sha=pre["batchFileSha256"], raw=True)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "batch_changed_since_preview"
    r = call([dict(T[0], expected_server_digest=dig)], dry_run=False, raw=True)      # sha 없음
    assert r.status_code == 409
    assert not s.updates and s.board_loads == 1


def test_unsynced_local_edits_blocked(server):
    write_batch({158: lv(158)})
    s = server(FakeBoard({}))
    r = call([{"target_id": "level_158", "source_level": 158}], dirty=3, raw=True)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "unsynced_local_edits"
    assert s.board_loads == 0


def test_request_level_json_is_ignored_batch_file_is_source(server, gate_open):
    j = j158_four()
    write_batch({158: j})
    server(FakeBoard({"level_158": srow("level_158", j)}))
    T = [{"target_id": "level_158", "source_level": 158, "level_json": lv(158, ddaEasy2Seeds="9,9,9")}]
    r = call(T)["results"][0]
    assert r["cells"]["ddaEasy2Seeds"]["value"] == "1,2,3"


# ── 보드 1회 조회 ────────────────────────────────────────────────────────────────
def test_board_loaded_once_no_per_row_lookup(server, gate_open):
    j = j158_four()
    write_batch({158: j, 159: lv(159), 5: lv(5)})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", lv(159)),
                          "level_5": srow("level_5", lv(5))}))
    T = [{"target_id": f"level_{n}", "source_level": n} for n in (158, 159, 5)]
    pre = call(T)
    assert s.board_loads == 1 and s.level_loads == 0
    upload(T, pre)
    assert s.board_loads == 2 and s.level_loads == 0 and len(s.updates) == 1


def test_board_lookup_failure_blocks_everything(server):
    write_batch({158: lv(158)})

    class Broken(FakeBoard):
        async def load_board_rows(self, board_id):
            raise gb_routes.GBoostLookupError("timeout (fake)")
    s = server(Broken({}))
    r = call([{"target_id": "level_158", "source_level": 158}], raw=True)
    assert r.status_code == 502 and not s.updates


def test_row_guards_missing_row_column_level_and_stale_digest(server, gate_open):
    j = j158_four()
    write_batch({158: j, 159: lv(159)})
    keys = [k for k in BOARD_KEYS if k != "ddaHard2Seeds"]
    row = srow("level_158", j)
    row.pop("ddaHard2Seeds")
    server(FakeBoard({"level_158": row}, keys=keys))
    r = {x["target_id"]: x for x in call([{"target_id": "level_158", "source_level": 158},
                                          {"target_id": "level_159", "source_level": 159},
                                          {"target_id": "level_9", "source_level": 9},
                                          {"target_id": "test_1", "source_level": 158}])["results"]}
    assert r["level_158"]["reason"] == "no_seed_column"
    assert r["level_159"]["reason"] == "no_server_row"
    assert r["level_9"]["reason"] == "no_batch_level"
    assert r["test_1"]["reason"] == "not_seed_row"
    s = server(FakeBoard({"level_158": srow("level_158", j)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    pre = call(T)
    s.rows["level_158"]["etime"] = "1790000099"                  # 미리보기 후 서버 행 변경
    assert upload(T, pre)["results"][0]["reason"] == "server_changed_since_preview" and not s.updates


def test_stop_after_first_failure(server, gate_open):
    j = j158_four()
    j2 = lv(159, ddaEasySeeds="4,5,6")
    j2[c.SEED_EVIDENCE_KEY] = verdicts(j2, ddaEasySeeds=[4, 5, 6])
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)},
                         fail_update={"level_158"}))
    T = [{"target_id": "level_158", "source_level": 158}, {"target_id": "level_159", "source_level": 159}]
    r = {x["target_id"]: x for x in upload(T, call(T))["results"]}
    assert r["level_158"]["status"] == "failed" and r["level_159"]["reason"] == "stopped_after_failure"
    assert [u[0] for u in s.updates] == ["level_158"]


def test_empty_layer_list_normalized_for_map_compare():
    j = lv(158)
    m = conv(dict(j))["map"]
    m2 = copy.deepcopy(m)
    m2["layer_9"] = {"col": "7", "row": "7", "tiles": [], "num": "0"}
    m3 = copy.deepcopy(m)
    m3["layer_9"] = {"col": "7", "row": "7", "tiles": {}, "num": "0"}
    assert c.map_compare_sha(m2) == c.map_compare_sha(m3) == c.map_compare_sha(json.dumps(m3))
    assert c.map_compare_sha(m) != c.map_compare_sha(m3)
    assert c.map_compare_sha("not json") is None and c.normalize_map(5) is None


def test_assert_seed_payload_v2():
    c.assert_seed_payload({"ddaEasy2Seeds": "1,2,3"})
    c.assert_seed_payload({"ddaEasySeeds": "1,2,3,4,5"})
    for bad in ({}, {"ddaEasySeeds": ""}, {"rewardList": None}, {"ddaEasy2Seeds": "1,2,3,4,5"},
                {"ddaHardSeeds": "1,1,2"}, {"ddaHardSeeds": "1,2"}):
        with pytest.raises(ValueError):
            c.assert_seed_payload(bad)


# ── 통과 기록 게이트 ──────────────────────────────────────────────────────────────
def test_gate_closed_by_default_no_post(server):
    assert c.PARTIAL_UPDATE_VERIFIED is False
    j = j158_four()
    write_batch({158: j})
    s = server(FakeBoard({"level_158": srow("level_158", j)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    r = upload(T, call(T))
    assert r["results"][0]["reason"] == "partial_update_unverified" and not s.updates
    assert r["partialUpdate"]["allowed"] is False


def test_trial_one_row_creates_record_then_opens_gate(server, isolate):
    j = j158_four()
    j2 = lv(159, ddaEasySeeds="4,5,6")
    j2[c.SEED_EVIDENCE_KEY] = verdicts(j2, ddaEasySeeds=[4, 5, 6])
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    two = T + [{"target_id": "level_159", "source_level": 159}]
    r = upload(two, call(two), trial=True, raw=True)
    assert r.status_code == 400 and not s.updates               # 대상 2개 → 거부, 전송 없음
    r = upload(T, call(T), trial=True)
    tr = r["trial"]
    assert r["results"][0]["status"] == "saved" and tr["judge"]["passed"] is True
    assert tr["target_id"] == "level_158" and tr["payload"] == {"ddaEasy2Seeds": "1,2,3", "ddaEasySeeds": "4,5,6"}
    assert tr["codeHash"] == gb_routes._seed_export_code_hash() and os.path.exists(tr["recordPath"])
    g = c.partial_update_allowed(gb_routes._seed_export_code_hash(), tr["gbTarget"])
    assert g["allowed"] is True and g["by"] == "trial"
    T2 = [{"target_id": "level_159", "source_level": 159}]
    r = upload(T2, call(T2))
    assert r["results"][0]["status"] == "saved" and s.updates[-1] == ("level_159", {"ddaEasySeeds": "4,5,6"})
    # 다른 코드 해시 → 기록 무효
    assert c.partial_update_allowed("deadbeef", tr["gbTarget"])["allowed"] is False


def test_trial_failed_readback_does_not_open_gate(server):
    j = j158_four()
    write_batch({158: j, 159: lv(159)})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", lv(159))},
                         corrupt_other="level_159"))
    T = [{"target_id": "level_158", "source_level": 158}]
    tr = upload(T, call(T), trial=True)["trial"]
    assert tr["judge"]["passed"] is False and tr["judge"]["othersChanged"] == 1
    assert c.partial_update_allowed(gb_routes._seed_export_code_hash(), tr["gbTarget"])["allowed"] is False
    assert len(s.updates) == 1


def test_judge_partial_trial_target_mismatch():
    before = {"a": {"id": "a", "etime": "1", "ddaEasySeeds": ""}, "b": {"id": "b"}}
    after_ok = {"a": {"id": "a", "etime": "2", "ddaEasySeeds": "1,2,3"}, "b": {"id": "b"}}
    after_bad = {"a": {"id": "a", "etime": "2", "ddaEasySeeds": "1,2,3", "x": 1}, "b": {"id": "b"}}
    assert c.judge_partial_trial("a", {"ddaEasySeeds": "1,2,3"}, before, after_ok)["passed"] is True
    j = c.judge_partial_trial("a", {"ddaEasySeeds": "1,2,3"}, before, after_bad)
    assert j["passed"] is False and j["badKeys"] == ["x"]


def test_ledger_records_sent_columns_only(server, gate_open):
    j = j158_four()
    write_batch({158: j})
    server(FakeBoard({"level_158": srow("level_158", j)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    call(T)
    assert L.list_snapshots() == []                              # dry_run 은 기록 없음
    upload(T, call(T))
    snaps = L.list_snapshots()
    assert len(snaps) == 1 and snaps[0]["source"] == "dda_seed_export"
    assert L.load(snaps[0]["id"])["rows"]["level_158"]["sent"] == {"ddaEasy2Seeds": "1,2,3", "ddaEasySeeds": "4,5,6"}


# ── 일반 업로드: 서버 map 같으면 썸네일 생략 ─────────────────────────────────────────
def test_single_save_skips_thumbnail_when_map_same(server):
    j = lv(158)
    s = server(FakeBoard({"level_158": srow("level_158", j)}))
    r = client.post("/api/gboost/levels/level_158", json={"level_json": j})
    assert r.status_code == 200 and "(thumbnail skipped: map same)" in r.json()["message"]
    assert not s.thumbs and [x[0] for x in s.saved] == ["level_158"]
    row = srow("level_158", j)
    row["map"]["layer_0"]["tiles"]["0_0"] = ["t2", ""]               # 다른 map → 기존대로 업로드
    s = server(FakeBoard({"level_158": row}))
    r = client.post("/api/gboost/levels/level_158", json={"level_json": j})
    assert r.status_code == 200 and "skipped" not in r.json()["message"]
    assert s.thumbs == (["level_158"] if gb_routes.PIL_AVAILABLE else [])
    s = server(FakeBoard({}))                                     # 새 행(비교 불가) → 기존대로
    r = client.post("/api/gboost/levels/level_777", json={"level_json": j})
    assert "skipped" not in r.json()["message"]


def test_upload_local_skips_thumbnail_when_map_same(server, monkeypatch, tmp_path):
    monkeypatch.setattr(gb_routes, "LOCAL_LEVELS_DIR", tmp_path)
    for n in (158, 159):
        (tmp_path / f"l{n}.json").write_text(json.dumps({"level_data": lv(n)}))
    other = srow("level_159", lv(159))
    other["map"] = "not json"                                     # 비교 불가 → 기존대로
    s = server(FakeBoard({"level_158": srow("level_158", lv(158)), "level_159": other}))
    body = {"board_id": "levels", "level_ids": ["l158", "l159"], "rename_strategy": "custom",
            "custom_names": {"l158": "level_158", "l159": "level_159"}, "overwrite": True}
    r = client.post("/api/gboost/upload-local", json=body).json()
    msg = {x["target_id"]: x["message"] for x in r["results"]}
    assert "(thumbnail skipped: map same)" in msg["level_158"] and "skipped" not in msg["level_159"]
    assert "level_158" not in s.thumbs


def test_server_map_same_helper_normalizes_empty_layer():
    j = lv(158)
    tp = conv(dict(j))
    row = {"map": copy.deepcopy(tp["map"])}
    tp2 = copy.deepcopy(tp)
    tp2["map"]["layer_9"] = {"tiles": {}}
    row["map"]["layer_9"] = {"tiles": []}
    assert gb_routes._server_map_same(row, tp2) is True
    assert gb_routes._server_map_same("unknown", tp) is False and gb_routes._server_map_same({"map": None}, tp) is False


# ── solve_level_task 시간 제한 ────────────────────────────────────────────────────
def test_solve_level_task_passes_time_budget(monkeypatch):
    seen = []

    def fake(level_json, node_budget=0, time_budget_s=None):
        seen.append((node_budget, time_budget_s))
        return {"verdict": "UNCERTAIN"}
    monkeypatch.setattr(solver, "solve_level", fake)
    solver.solve_level_task({"level_number": 1, "level_json": {}, "node_budget": 7, "time_budget_s": 0.25})
    solver.solve_level_task({"level_number": 2, "level_json": {}, "node_budget": 7})
    solver.solve_level_task({"level_number": 3, "level_json": {}, "node_budget": 7, "time_budget_s": None})
    solver.solve_level_task({"level_number": 4, "level_json": {}, "node_budget": 7, "time_budget_s": 0})
    solver.solve_level_task({"level_number": 5, "level_json": {}, "node_budget": 7, "time_budget_s": 5.0})
    solver.solve_level_task({"level_number": 6, "level_json": {}, "node_budget": 7, "time_budget_s": 600})
    solver.solve_level_task({"level_number": 7, "level_json": {}, "node_budget": 7, "time_budget_s": -1})
    cap = solver.TASK_MAX_TIME_BUDGET_S
    assert cap == 60.0
    # 0(무제한)·음수·상한 초과 → 60 s 로 자름. 기본 5.0 은 그대로(기존 결과 불변)
    assert seen == [(7, 0.25), (7, solver.DEFAULT_TIME_BUDGET_S), (7, solver.DEFAULT_TIME_BUDGET_S), (7, cap),
                    (7, 5.0), (7, cap), (7, cap)]


def test_solve_level_task_default_budget_result_unchanged():
    """기본 5.0 예산: solve_level_task 결과 = solve_level 직접 호출 결과(판정·노드·수)."""
    for n in (5, 40, 158):
        j = lv(n)
        a = solver.solve_level(j)
        b = solver.solve_level_task({"level_number": n, "level_json": j})
        c5 = solver.solve_level_task({"level_number": n, "level_json": j, "time_budget_s": 5.0})
        if a["verdict"] != "UNCERTAIN":
            for r in (b, c5):
                assert (r["verdict"], r["nodes_expanded"], r["moves_to_clear"]) == \
                    (a["verdict"], a["nodes_expanded"], a["moves_to_clear"])


def test_solve_level_task_respects_small_budget_real():
    j = lv(1466)
    t0 = time.monotonic()
    r = solver.solve_level_task({"level_number": 1466, "level_json": j, "node_budget": 10 ** 9, "time_budget_s": 0.05})
    el = time.monotonic() - t0
    assert r["error"] is None
    if r["verdict"] == "UNCERTAIN" and "시간" in r["reason"]:
        assert el < 3.0                                            # 확인 간격 256노드(기존 결과 보존) — 초과 상한 관측 ~1.1 s
    assert solver._TIME_CHECK_EVERY == 256


# ── [리뷰 반영 v2] 경합·대상 묶음·해시 범위·미동기 편집·미리보기 무효화 ─────────────────────────
def _two_rows():
    j = j158_four()
    j2 = lv(159, ddaEasySeeds="4,5,6")
    j2[c.SEED_EVIDENCE_KEY] = verdicts(j2, ddaEasySeeds=[4, 5, 6])
    return j, j2


def test_concurrent_request_blocked_by_lock(server, monkeypatch):
    write_batch({158: lv(158)})
    s = server(FakeBoard({}))

    class _Held:
        def locked(self):
            return True
    monkeypatch.setattr(gb_routes, "_SEED_EXPORT_LOCK", _Held())
    r = call([{"target_id": "level_158", "source_level": 158}], raw=True)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "seed_export_busy" and s.board_loads == 0


def test_batch_changed_after_board_load_aborts_before_any_post(server, gate_open):
    j, j2 = _two_rows()
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}, {"target_id": "level_159", "source_level": 159}]
    pre = call(T)
    s.on_board_load = lambda _s: write_batch({158: j, 159: lv(159)}, version=5)   # 보드 조회 중 배치 저장
    r = upload(T, pre, raw=True)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "batch_changed_during_export" and not s.updates


def test_batch_changed_mid_export_stops_immediately(server, gate_open):
    j, j2 = _two_rows()
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}, {"target_id": "level_159", "source_level": 159}]
    pre = call(T)
    s.on_update = lambda _s: write_batch({158: j, 159: j2, 5: lv(5)}, version=6)  # 첫 전송 뒤 배치 변경
    r = upload(T, pre, raw=True)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["reason"] == "batch_changed_during_export"
    assert [u[0] for u in s.updates] == ["level_158"]                             # 두 번째 행은 보내지 않음
    assert [x["status"] for x in d["results"]] == ["saved"]
    snaps = L.list_snapshots()
    assert snaps and L.load(snaps[-1]["id"])["rows"]["level_158"]["status"] == "sent"   # 보낸 행은 장부에 남음


def test_batch_watch_detects_same_size_rewrite(isolate):
    write_batch({158: lv(158)})
    from app.api.routes.production_store import read_batch_file
    bf = read_batch_file(BATCH)
    w = gb_routes._BatchWatch(BATCH, bf["version"], bf["sha256"])
    assert w.changed() is None and w.changed(full=True) is None
    write_batch({158: lv(158, rewardCoin=9)})
    assert w.changed() == "batch_changed_during_export"
    os.remove(os.path.join(ps._STORE_DIR, f"{BATCH}.json"))
    assert w.changed() == "batch_missing"


def test_trial_record_bound_to_gameboost_target(server):
    j, j2 = _two_rows()
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    tr = upload(T, call(T), trial=True)["trial"]
    assert tr["judge"]["passed"] and tr["gbTarget"] == {"base_url": "https://gb.example/api", "project_id": "p1",
                                                         "board_id": "levels"}
    T2 = [{"target_id": "level_159", "source_level": 159}]
    for kw in ({"base_url": "https://other.example/api"}, {"project_id": "p2"}):
        s2 = server(FakeBoard({"level_159": srow("level_159", j2)}, **kw))
        pre = call(T2)
        assert pre["partialUpdate"]["allowed"] is False and pre["gbTarget"] != tr["gbTarget"]
        assert upload(T2, pre)["results"][0]["reason"] == "partial_update_unverified" and not s2.updates
    # 표기만 다른 같은 서버(대소문자·끝 '/'·기본 포트) → 같은 대상
    s3 = server(FakeBoard({"level_159": srow("level_159", j2)}, base_url="HTTPS://GB.example:443/api/"))
    assert call(T2)["partialUpdate"]["allowed"] is True
    assert upload(T2, call(T2))["results"][0]["status"] == "saved" and s3.updates


def test_code_hash_covers_modules_and_settings(monkeypatch, tmp_path):
    h0 = gb_routes._seed_export_code_hash()
    assert gb_routes._seed_export_code_hash() == h0
    monkeypatch.setattr(c, "SEED_EVIDENCE_REQUIRED", False)
    assert gb_routes._seed_export_code_hash() != h0
    monkeypatch.setattr(c, "SEED_EVIDENCE_REQUIRED", True)
    assert gb_routes._seed_export_code_hash() == h0
    for mod in (inf, c):
        fake = tmp_path / os.path.basename(mod.__file__)
        fake.write_bytes(open(mod.__file__, "rb").read() + b"\n# changed\n")
        with pytest.MonkeyPatch.context() as mp:            # 자동 격리 픽스처의 패치는 건드리지 않음
            mp.setattr(mod, "__file__", str(fake))
            assert gb_routes._seed_export_code_hash() != h0
    from app import config as cfg
    from app.core.pv import cs_shuffle as cs
    from app.models import schemas as sch
    for mod in (cs, sch, cfg):
        fake = tmp_path / ("x_" + os.path.basename(mod.__file__))
        fake.write_bytes(open(mod.__file__, "rb").read() + b"\n# changed\n")
        with pytest.MonkeyPatch.context() as mp:            # 자동 격리 픽스처의 패치는 건드리지 않음
            mp.setattr(mod, "__file__", str(fake))
            assert gb_routes._seed_export_code_hash() != h0
    assert gb_routes._seed_export_code_hash() == h0
    from app.clients import gboost as gbc
    fake = tmp_path / "gboost_client.py"
    fake.write_bytes(open(gbc.__file__, "rb").read() + b"\n# changed\n")
    monkeypatch.setattr(gbc, "__file__", str(fake))
    assert gb_routes._seed_export_code_hash() != h0


def test_unsynced_edits_block_upload_chunk(server, gate_open):
    j = j158_four()
    write_batch({158: j})
    s = server(FakeBoard({"level_158": srow("level_158", j)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    pre = call(T)
    r = upload(T, pre, dirty=1, raw=True)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "unsynced_local_edits" and not s.updates


def test_preview_identity_must_match_on_upload(server, gate_open):
    j, j2 = _two_rows()
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}]
    sel = {"range": [1, 200], "infinityMode": "off"}
    pre = call(T, selection=sel)
    for kw, why in (({"relabel": False}, "infinity_relabel"), ({"selection": {"range": [1, 300], "infinityMode": "off"}}, "selection"),
                    ({"selection": sel, "preview_id": "nope"}, None)):
        r = upload(T, pre, raw=True, **({"selection": sel} | kw))
        d = r.json()["detail"]
        assert r.status_code == 409
        assert (d["reason"], why in d.get("fields", [why])) == (("preview_unknown", True) if why is None else ("preview_mismatch", True))
    r = upload(T + [{"target_id": "level_159", "source_level": 159}], pre, raw=True, selection=sel)
    assert r.status_code == 409 and r.json()["detail"]["fields"] == ["targets"]
    r = upload([{"target_id": "level_158", "source_level": 159}], pre, raw=True, selection=sel)
    assert r.status_code == 409                                                     # 원본 번호 다름
    assert not s.updates
    assert upload(T, pre, selection=sel)["results"][0]["status"] == "saved"


# ── [재리뷰 v3] 예외·취소 시 장부 · payload 가드 실패 중단 ──────────────────────────────────
def _direct_upload(s, T, pre):
    """라우트 내부 함수를 직접 호출(TestClient 를 거치지 않아 CancelledError 를 그대로 받는다)."""
    import asyncio as _aio
    dig = {x["target_id"]: x.get("serverDigest") for x in pre["results"]}
    req = gb_routes.DdaSeedExportRequest(
        batch_id=BATCH, expected_batch_version=5, expected_batch_sha256=pre["batchFileSha256"],
        preview_id=pre["preview_id"], dry_run=False, confirm=True,
        targets=[dict(t, expected_server_digest=dig[t["target_id"]]) for t in T])
    return _aio.run(gb_routes._dda_seed_export_locked(req, s, None, "", ""))


@pytest.mark.parametrize("exc", [RuntimeError("boom"), __import__("asyncio").CancelledError()])
def test_exception_or_cancel_mid_loop_records_ledger(server, gate_open, exc):
    j, j2 = _two_rows()
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}, {"target_id": "level_159", "source_level": 159}]
    pre = call(T)
    s.raise_on = {"level_159": exc}
    with pytest.raises(type(exc)):
        _direct_upload(s, T, pre)
    assert [u[0] for u in s.updates] == ["level_158"]
    snaps = L.list_snapshots()
    assert snaps, "장부 세션이 남아야 한다"
    rows = L.load(snaps[-1]["id"])["rows"]
    assert rows["level_158"]["status"] == "sent"                     # 앞 행 기록
    assert rows["level_159"]["status"] == "failed"                   # 전송 중 끊긴 행 = 반영 여부 불명(failed)


def test_payload_guard_failure_blocks_row_and_stops(server, gate_open, monkeypatch):
    j, j2 = _two_rows()
    write_batch({158: j, 159: j2})
    s = server(FakeBoard({"level_158": srow("level_158", j), "level_159": srow("level_159", j2)}))
    T = [{"target_id": "level_158", "source_level": 158}, {"target_id": "level_159", "source_level": 159}]
    pre = call(T)
    real = c.assert_seed_payload

    def bad(payload):
        if "ddaEasy2Seeds" in payload:
            raise ValueError("fake invalid")
        return real(payload)
    monkeypatch.setattr(c, "assert_seed_payload", bad)
    r = {x["target_id"]: x for x in upload(T, pre)["results"]}
    assert (r["level_158"]["status"], r["level_158"]["reason"]) == ("failed", "payload_invalid")
    assert r["level_159"]["reason"] == "stopped_after_failure" and not s.updates
    snaps = L.list_snapshots()
    assert L.load(snaps[-1]["id"])["rows"]["level_158"]["status"] == "failed"   # 장부도 실패로
