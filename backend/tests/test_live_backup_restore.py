"""라이브 전체 백업 → 업로드 → 복원 왕복 (app.core.live_backup, /api/live-backup). 외부 통신 없음.

가짜 서버는 dda_seed_catalog.READBACK_RULES 실측 규칙대로 저장한다(정수 문자열→정수, backgroundIndex/tileSkin "0"→null,
rewardList "[]"→null, 보내지 않은 열 유지, etime 갱신). 실서버 동작과 같다는 보장은 아니다(규칙 범위 내 시뮬레이션).
"""
from __future__ import annotations

import copy
import json
import os
import re
import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gboost
from app.api.routes.gboost import _convert_to_townpop_format as conv
from app.clients.gboost import GBoostLookupError
from app.core import dda_seed_catalog as c
from app.core import dda_seed_ledger as L
from app.core import live_backup as B
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)
client = TestClient(app)
KEYS = ["id", "idx", "etime", "backgroundIndex", "tileSkin", "timea", "unlockTile", "col", "row", "rewardCoin",
        "useInRandomizer", "randSeed", "ddaEasy2Seeds", "ddaEasySeeds", "ddaHardSeeds", "ddaHard2Seeds", "shuffleLayer",
        "shuffleTile", "difficulty", "", "useTeleportInRandomizer", "teleportRandSeed", "autoCollectCount",
        "visualTileSeed", "num", "sets", "layer", "field4", "useTileCount", "typeImbalance", "rewardList", "map"]


def lv(n, **kw):
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(kw)
    return j


def stored(payload: dict, base: dict) -> dict:
    """READBACK_RULES 대로 저장된 행."""
    row = dict(base)
    for k, v in payload.items():
        if k == "etime":
            continue
        if k in ("backgroundIndex", "tileSkin") and v == "0":
            row[k] = None
        elif k == "rewardList" and v == "[]":
            row[k] = None
        elif k == "map" or k in c.EXPORT_SEED_FIELDS:
            row[k] = copy.deepcopy(v)
        elif isinstance(v, str) and re.match(r"^-?[0-9]+$", v):
            row[k] = int(v)
        else:
            row[k] = v
    row["etime"] = str(int(time.time()))
    return row


class FakeServer:
    is_configured = True
    base_url, project_id = "fake://", "fake"

    def __init__(self, rows):
        self.rows = rows
        self.writes = []
        self.idx = 70000

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        r = self.rows.get(level_id)
        return None if r is None else {"level_json": copy.deepcopy(r), "metadata": {}}

    async def load_board_rows(self, board_id):
        vals = [[r.get(k, "") if k else "" for k in KEYS] for r in self.rows.values()]
        raw = json.dumps({"__keys": KEYS, "__vals": vals, "__encrypts": ""}).encode()
        return {"rows": copy.deepcopy(self.rows), "keys": KEYS, "raw_sha256": "x", "raw_bytes": len(raw), "raw": raw}

    async def save_level(self, board_id, level_id, level_json):
        p = json.loads(json.dumps(level_json))
        self.writes.append(("save", level_id, p))
        base = self.rows.get(level_id) or {k: ("" if k not in ("map",) else None) for k in KEYS if k}
        if level_id not in self.rows:
            self.idx += 1
            base.update({"id": level_id, "idx": str(self.idx)})
        self.rows[level_id] = stored(p, base)
        return {"success": True}

    async def update_existing_level(self, board_id, level_id, row):
        p = json.loads(json.dumps(row))
        self.writes.append(("update", level_id, p))
        if level_id not in self.rows:
            return {"success": False, "error": "no row"}
        self.rows[level_id] = stored(p, self.rows[level_id])
        return {"success": True}

    async def save_thumbnail(self, *a, **k):
        return {"success": True}


def server_row(n, rid=None, **seeds):
    """출시 상태처럼 생긴 서버 행(정수·null 표현)."""
    tp = conv(lv(n))
    tp.update({k: v for k, v in seeds.items()})
    row = stored(tp, {k: "" for k in KEYS if k})
    row.update({"id": rid or f"level_{n}", "idx": str(60000 + n), "visualTileSeed": "", "field4": ""})
    for f in c.EXPORT_SEED_FIELDS:
        row.setdefault(f, "")
    return row


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DDA_SEED_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LIVE_BACKUP_DIR", str(tmp_path / "backup"))
    monkeypatch.setattr(L, "_auto_sessions", {})
    monkeypatch.setattr(c, "SEED_EVIDENCE_REQUIRED", False)     # 업로드 단계만 단순화(게이트는 별도 테스트)


@pytest.fixture
def fake():
    rows = {"level_5": server_row(5, ddaEasySeeds="1,2,3", ddaHardSeeds="4,5,6"),
            "level_40": server_row(40, ddaHard2Seeds="7,8,9"),
            "infinity_1": server_row(40, "infinity_1"),
            "test_1": server_row(111, "test_1")}
    s = FakeServer(rows)
    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: s
    yield s
    app.dependency_overrides[get_gboost] = prev


def _upload(fake):
    sid = client.post("/api/dda-ledger/sessions", json={"memo": "1.1.2", "tag": "1.1.2"}).json()["id"]
    up = [("level_5", lv(158, ddaEasySeeds="3,1,2", ddaHardSeeds="40,50,60", rewardCoin=77)),   # 맵·시드·보상 변경
          ("level_40", lv(40, ddaHard2Seeds="")),                                                # 시드 열 생략(""), 맵 동일
          ("infinity_1", lv(322)),                                                               # 무한 맵 변경(relabel)
          ("infinity_9", lv(5))]                                                                 # 새 행
    for tid, j in up:
        r = client.post(f"/api/gboost/levels/{tid}?ledger_session={sid}", json={"level_json": j, "dda_confirm": True})
        assert r.status_code == 200, r.text
    client.post(f"/api/dda-ledger/sessions/{sid}/finalize", json={"client_counts": {}})
    return sid


def _cmp(before: dict, after: dict, ids):
    bad = []
    for rid in ids:
        for k, v in before[rid].items():
            if k in ("etime",):
                continue
            if not B.same_value(after[rid].get(k), v):
                bad.append((rid, k, v if k != "map" else "map", after[rid].get(k) if k != "map" else "map"))
    return bad


def test_backup_upload_restore_roundtrip(fake):
    r = client.post("/api/live-backup/backups/start", json={"memo": "1.1.2 업로드 직전", "wait": True}).json()
    assert r["status"] == "done", r
    bk = r["result"]
    assert bk["rowCount"] == 4 and bk["complete"] and bk["rowKinds"] == {"level_N": 2, "infinity_N": 1, "test_N": 1}
    assert os.path.exists(bk["file"]) and len(bk["fileSha256"]) == 64
    before = copy.deepcopy(fake.rows)
    sid = _upload(fake)
    changed = _cmp(before, fake.rows, ["level_5", "infinity_1"])
    assert any(k == "map" for _, k, *_ in changed) and any(k == "ddaHardSeeds" for _, k, *_ in changed)
    # 장부: 업로드 직전 행 전체 + 덮어쓴 열
    rec = L.load(sid)["rows"]["level_5"]
    assert rec["serverBeforeRow"]["rewardCoin"] == before["level_5"]["rewardCoin"]
    assert "map" in rec["payloadKeys"] and "useTileCount" in rec["payloadKeys"]

    # 1단계 미리보기(백업 기준, 현재 서버와 비교)
    pv = client.post("/api/live-backup/restore/preview", json={"base": {"type": "backup", "id": bk["id"]}}).json()
    assert pv["rowCount"] == 2, pv                      # level_5, infinity_1 (level_40 은 실제 값 변화 없음)
    assert pv["columnCounts"]["map"] == 2 and pv["unverifiedRows"] == 0
    assert pv["extraOnServer"] == ["infinity_9"]        # 업로드로 생긴 행 — 지우지 않음
    assert not fake.writes or all(w[0] == "save" for w in fake.writes)   # 미리보기는 쓰기 없음
    n_writes = len(fake.writes)
    # 확인 문구 틀리면 거부
    bad = client.post("/api/live-backup/restore/execute", json={"plan_id": pv["planId"], "plan_digest": pv["planDigest"],
                                                                "confirm_text": "ok", "wait": True})
    assert bad.status_code == 400 and len(fake.writes) == n_writes
    # 2단계 실행
    ex = client.post("/api/live-backup/restore/execute", json={"plan_id": pv["planId"], "plan_digest": pv["planDigest"],
                                                               "confirm_text": "복원", "sleep_ms": 0, "wait": True}).json()
    res = ex["result"]
    assert ex["status"] == "done" and res["verified"] == 2 and res["mismatch"] == 0 and res["failed"] == 0, ex
    assert all(w[0] == "update" for w in fake.writes[n_writes:])          # new=0 경로만
    assert _cmp(before, fake.rows, ["level_5", "level_40", "infinity_1", "test_1"]) == []
    assert "infinity_9" in fake.rows                                      # 새 행은 수동 처리
    # 복원 기록이 장부에 restore 스냅샷으로
    snaps = L.list_snapshots()
    assert snaps[-1]["kind"] == "restore" and snaps[-1]["counts"]["sent"] == 2


def test_restore_from_upload_snapshot_scope(fake):
    before = copy.deepcopy(fake.rows)
    sid = _upload(fake)
    fake.rows["test_1"]["rewardCoin"] = 999          # 업로드와 무관한 이후 변경 — 스냅샷 범위 복원은 건드리지 않아야 함
    pv = client.post("/api/live-backup/restore/preview", json={"base": {"type": "snapshot", "id": sid}}).json()
    assert pv["rowCount"] == 2 and pv["createdByUpload"] == ["infinity_9"]
    assert any("새로 생긴 행" in w for w in pv["warnings"])
    ex = client.post("/api/live-backup/restore/execute", json={"plan_id": pv["planId"], "plan_digest": pv["planDigest"],
                                                               "confirm_text": "복원", "sleep_ms": 0, "wait": True}).json()
    assert ex["result"]["verified"] == 2
    assert _cmp(before, fake.rows, ["level_5", "level_40", "infinity_1"]) == []
    assert fake.rows["test_1"]["rewardCoin"] == 999


def test_execute_blocks_when_server_changed_after_preview(fake):
    r = client.post("/api/live-backup/backups/start", json={"wait": True}).json()["result"]
    _upload(fake)
    pv = client.post("/api/live-backup/restore/preview", json={"base": {"type": "backup", "id": r["id"]}}).json()
    fake.rows["level_5"]["ddaHardSeeds"] = "11,22,33"                     # 미리보기 뒤 서버 변경
    ex = client.post("/api/live-backup/restore/execute", json={"plan_id": pv["planId"], "plan_digest": pv["planDigest"],
                                                               "confirm_text": "복원", "sleep_ms": 0, "wait": True}).json()
    st = {x["id"]: x["status"] for x in ex["result"]["results"]}
    assert st["level_5"] == "blocked" and st["infinity_1"] == "verified"
    assert fake.rows["level_5"]["ddaHardSeeds"] == "11,22,33"
    bad = client.post("/api/live-backup/restore/execute", json={"plan_id": pv["planId"], "plan_digest": "0" * 64,
                                                                "confirm_text": "복원", "wait": True})
    assert bad.status_code == 400


def test_import_file_backup_stale_warning_and_offline_preview(fake, tmp_path):
    vals = [[fake.rows["level_5"].get(k, "") if k else "" for k in KEYS],
            [fake.rows["level_5"].get(k, "") if k else "" for k in KEYS]]          # 중복 id → 불완전
    vals.append(["bad"])                                                             # 열 개수 다름
    p = tmp_path / "levels.raw.json"
    p.write_text(json.dumps({"__keys": KEYS, "__vals": vals}))
    imp = client.post("/api/live-backup/backups/import-file", json={"path": str(p), "memo": "10-28"}).json()
    assert imp["source"] == "file" and imp["complete"] is False and imp["problemCount"] == 2 and imp["rowCount"] == 0
    good = tmp_path / "ok.raw.json"
    good.write_text(json.dumps({"__keys": KEYS, "__vals": [[fake.rows["level_5"].get(k, "") if k else "" for k in KEYS]]}))
    imp2 = client.post("/api/live-backup/backups/import-file", json={"path": str(good)}).json()
    cur = client.post("/api/live-backup/backups/start", json={"wait": True}).json()["result"]
    pv = client.post("/api/live-backup/restore/preview", json={"base": {"type": "backup", "id": imp2["id"]},
                                                               "current_backup": cur["id"]}).json()
    assert pv["currentSource"]["type"] == "backup" and pv["rowCount"] == 0
    assert any("파일에서 가져온 백업" in w for w in pv["warnings"])
    # 상태: 파일 가져오기는 '서버 백업'으로 치지 않음, 서버 백업 직후 경고 없음
    st = client.get("/api/live-backup/status").json()
    assert st["last"]["id"] == cur["id"] and st["warn"] is None
    # 수정·삭제 API 없음
    methods = {m for r in app.routes if getattr(r, "path", "").startswith("/api/live-backup") for m in getattr(r, "methods", ())}
    assert not methods & {"DELETE", "PUT", "PATCH"}
    with pytest.raises(FileExistsError):
        B._write_new_gz(cur["file"], {})


def test_backup_status_without_and_stale(monkeypatch):
    assert B.backup_status()["warn"] == "no_backup"
    B._save_backup({"__keys": ["id"], "__vals": [["level_1"]]}, b"{}", board="levels", memo="", source="server_read",
                   t=time.time() - 5 * 3600)
    assert B.backup_status()["warn"] == "stale"


def test_encode_rules():
    assert B.encode_restore_value("backgroundIndex", None) == ("0", True, "\"0\" → null (실측)")
    assert B.encode_restore_value("rewardList", None)[:2] == ("[]", True)
    assert B.encode_restore_value("rewardCoin", 5)[:2] == ("5", True)
    assert B.encode_restore_value("ddaHardSeeds", "")[:2] == ("", True)
    assert B.encode_restore_value("rewardList", [["a", 1]])[1] is False
    assert B.encode_restore_value("visualTileSeed", None)[1] is False


def test_board_read_failure_no_file(monkeypatch, fake):
    async def boom(board):
        raise GBoostLookupError("timeout")
    monkeypatch.setattr(fake, "load_board_rows", boom)
    r = client.post("/api/live-backup/backups/start", json={"wait": True}).json()
    assert r["status"] == "failed" and "보드 읽기 실패" in r["error"]
    assert B.list_backups() == []
