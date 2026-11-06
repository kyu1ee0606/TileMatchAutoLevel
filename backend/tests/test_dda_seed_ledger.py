"""DDA 시드 이력 장부(app.core.dda_seed_ledger) — 기록·추가 전용·비교 분류·무한 행·생략 열·업로드 경로 훅.

외부 통신 없음: 업로드 경로는 메모리 가짜 서버(FakeServer)를 의존성으로 주입. 장부 폴더는 테스트마다 tmp_path
(conftest 도 세션 전체를 임시 폴더로 격리).
"""
from __future__ import annotations

import copy
import gzip
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gboost
from app.api.routes import gboost as gb_routes
from app.api.routes.gboost import _convert_to_townpop_format as conv
from app.api.routes.dda_seed_ledger import plan_rows_from_batch
from app.core import dda_seed_catalog as c
from app.core import dda_seed_ledger as L
from app.core import infinity_relabel as inf
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)
client = TestClient(app)


def lv(n: int, **kw) -> dict:
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(kw)
    return j


def verdicts(j: dict, target_id: str = "", **cols) -> dict:
    src, _ = inf.prepare_export_level_json(target_id, j, True) if target_id else (j, None)
    tp = conv(dict(src))
    ev = {"binding": {"mapSha256": c.map_sha256(tp), "useTileCount": tp["useTileCount"]}}
    for f, seeds in cols.items():
        ev[f] = [{"seed": s, "verdict": v, "nodes": 7, "source": "dda_seed_verify/test", "verifier": "v4"}
                 for s, v in seeds]
    return ev


@pytest.fixture(autouse=True)
def ledger_dir(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    monkeypatch.setenv("DDA_SEED_LEDGER_DIR", str(d))
    monkeypatch.setattr(L, "_auto_sessions", {})
    return d


class FakeServer:
    is_configured = True
    base_url, project_id = "fake://", "fake"

    def __init__(self, rows=None, fail_ids=(), save_fail_ids=()):
        self.rows = rows or {}
        self.fail_ids = set(fail_ids)
        self.save_fail_ids = set(save_fail_ids)
        self.saved = []

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        if level_id in self.fail_ids:
            if strict:
                raise gb_routes.GBoostLookupError("HTTP 500 (fake)")
            return None
        r = self.rows.get(level_id)
        return None if r is None else {"level_json": copy.deepcopy(r), "metadata": {}}

    async def load_board_rows(self, board_id):
        return {"rows": copy.deepcopy(self.rows), "raw_sha256": "fake", "raw_bytes": 0}

    async def save_level(self, board_id, level_id, level_json):
        if level_id in self.save_fail_ids:
            return {"success": False, "error": "fake save fail"}
        payload = json.loads(json.dumps(level_json))
        self.saved.append((board_id, level_id, payload))
        row = dict(self.rows.get(level_id) or {})
        row.update(payload)                                # 보내지 않은 열 = 서버 값 유지(real_array new=0)
        self.rows[level_id] = row
        return {"success": True}

    async def save_thumbnail(self, *a, **k):
        return {"success": True}

    async def update_existing_level(self, board_id, level_id, row):
        return {"success": True}


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


# ── 분류 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b,cls", [
    ("1,2,3", "1,2,3", "same"),
    ("", "", "same"),
    ("1,2,3", "3,1,2", "reordered"),
    ("1,2,3", "1,9,3", "replaced"),
    ("1,2,3", "1,2,3,4,5", "added"),
    ("1,2,3,4,5", "1,2,3", "removed"),
    ("1,2,3,4,5", "1,9,3", "resized"),
    ("", "1,2,3", "filled"),
    ("1,2,3", "", "cleared"),
    (None, "1,2,3", "unknown"),
])
def test_classify_field(a, b, cls):
    assert L.classify_field(a, b)["class"] == cls


def test_classify_positions_and_game_flags():
    r = L.classify_field("1,2,3", "1,9,3")
    assert r["positions"] == [{"pos": 1, "from": "2", "to": "9"}]
    assert r["addedTokens"] == ["9"] and r["removedTokens"] == ["2"]
    assert r["gameChanged"] and r["gameSetChanged"]
    o = L.classify_field("1,2,3", "3,1,2")
    assert o["gameChanged"] and not o["gameSetChanged"] and o["orderChanged"]
    # 옛 5개 값의 뒤 2개만 바뀜 → 게임이 읽는 앞 3개는 그대로
    t = L.classify_field("1,2,3,4,5", "1,2,3,4,6")
    assert t["class"] == "replaced" and not t["gameChanged"]


def _row(rid, status="baseline", seeds=None, map_sha="m1", utc=3):
    return {"id": rid, "status": status, "sent": dict(seeds or {}), "omitted": {}, "mapSha256": map_sha,
            "useTileCount": utc}


def test_diff_rows_classes_and_map_change():
    a = {"level_1": _row("level_1", seeds={"ddaEasySeeds": "1,2,3", "ddaHardSeeds": "4,5,6"}),
         "level_2": _row("level_2", seeds={"ddaEasySeeds": "1,2,3"}),
         "level_3": _row("level_3", seeds={"ddaEasySeeds": "1,2,3"})}
    b = {"level_1": _row("level_1", seeds={"ddaEasySeeds": "3,2,1", "ddaHardSeeds": "4,7,6"}),
         "level_2": _row("level_2", seeds={"ddaEasySeeds": "1,2,3"}, map_sha="m2"),
         "level_4": _row("level_4", seeds={"ddaEasySeeds": "1,2,3"})}
    items = {it["id"]: it for it in L.diff_rows(a, b)}
    assert items["level_1"]["fields"]["ddaEasySeeds"]["class"] == "reordered"
    assert items["level_1"]["fields"]["ddaHardSeeds"]["class"] == "replaced"
    assert items["level_1"]["fields"]["ddaHard2Seeds"]["class"] == "unknown"   # baseline 에 열 키 없음 = 모름
    assert any("order_only_safe" in n for n in items["level_1"]["lockNotes"])
    assert any("locked_old_values" in n for n in items["level_1"]["lockNotes"])
    assert items["level_2"]["mapChanged"] and items["level_2"]["changed"]
    assert any("map_changed_with_seeds" in n for n in items["level_2"]["lockNotes"])
    assert items["level_3"]["rowRemoved"] and items["level_4"]["rowAdded"]
    s = L.diff_summary(list(items.values()))
    assert s["mapChanged"] == 1 and s["rowAdded"] == 1 and s["rowRemoved"] == 1
    csv_text = L.diff_csv(list(items.values()))
    assert "level_1,ddaHardSeeds,1,replaced,\"4,5,6\",\"4,7,6\"" in csv_text
    assert "1:5->7" in csv_text


def test_parse_level_query():
    assert L.parse_level_query("5, 7-8 i3 infinity_10") == {"level_5", "level_7", "level_8", "infinity_3", "infinity_10"}
    assert L.parse_level_query("") is None


# ── 저장·추가 전용 ────────────────────────────────────────────────────────────────
def test_snapshot_append_only(ledger_dir):
    s = L.create_snapshot(kind="baseline", rows={"level_1": _row("level_1", seeds={"ddaEasySeeds": "1,2,3"})},
                          memo="m", tag="v0")
    sid = s["id"]
    gz = ledger_dir / "snapshots" / f"{sid}.json.gz"
    assert gz.exists()
    doc = json.loads(gzip.decompress(gz.read_bytes()))
    assert doc["rows"]["level_1"]["sent"]["ddaEasySeeds"] == "1,2,3" and doc["tag"] == "v0"
    before = gz.read_bytes()
    with pytest.raises(L.LedgerError):
        L.finalize(sid)                                    # 두 번 마감 불가
    with pytest.raises(L.LedgerError):
        L.append_row(sid, _row("level_2"))                 # 마감 후 추가 불가
    assert gz.read_bytes() == before
    idx = [json.loads(x) for x in (ledger_dir / "index.jsonl").read_text().splitlines()]
    assert [e["event"] for e in idx] == ["opened", "finalized"]
    # API 에 수정·삭제 경로 없음
    methods = {(r.path, m) for r in app.routes if getattr(r, "path", "").startswith("/api/dda-ledger")
               for m in getattr(r, "methods", ())}
    assert not any(m in ("DELETE", "PUT", "PATCH") for _, m in methods)
    with pytest.raises(L.LedgerError):
        L.load("../../etc/passwd")


def test_list_and_open_session_visible(ledger_dir):
    h = L.open_session(memo="업로드 중", tag="1.1.2")
    L.append_row(h["id"], {**_row("level_9", status="sent", seeds={"ddaHardSeeds": "1,2,3"})})
    lst = L.list_snapshots()
    assert lst[-1]["id"] == h["id"] and lst[-1]["status"] == "open" and lst[-1]["counts"]["sent"] == 1


# ── 업로드 경로 훅(가짜 서버) ─────────────────────────────────────────────────────
def test_upload_route_records_actual_payload(server, ledger_dir):
    j = lv(40, ddaHardSeeds="11,12,13", ddaEasySeeds="21,22,23", ddaEasy2Seeds="31,32,33")
    j["ddaSeedVerdicts"] = verdicts(j, ddaHardSeeds=[(11, "PATH"), (12, "PATH_BOT"), (13, "PATH")],
                                    ddaEasySeeds=[(21, "PATH"), (22, "IMPOSSIBLE"), (23, "PATH")])
    srv_row = {"id": "level_40", "ddaEasySeeds": "1,2,3", "ddaHardSeeds": "", "ddaEasy2Seeds": "31,32,33",
               "ddaHard2Seeds": "", "map": conv(dict(j))["map"], "useTileCount": conv(dict(j))["useTileCount"]}
    s = server(FakeServer(rows={"level_40": copy.deepcopy(srv_row)}, save_fail_ids={"level_5"}))
    sess = client.post("/api/dda-ledger/sessions", json={"memo": "1.1.2 업데이트", "tag": "1.1.2",
                                                         "batch_id": "b1", "batch_name": "배치"}).json()
    sid = sess["id"]
    r = client.post(f"/api/gboost/levels/level_40?ledger_session={sid}", json={"level_json": j})
    assert r.status_code == 200, r.text
    r2 = client.post(f"/api/gboost/levels/level_5?ledger_session={sid}", json={"level_json": lv(5)})
    assert r2.status_code == 500
    fin = client.post(f"/api/dda-ledger/sessions/{sid}/finalize", json={"client_counts": {"success": 1}}).json()
    assert fin["status"] == "finalized" and fin["readbackResult"]["ok"]
    doc = L.load(sid)
    rec = doc["rows"]["level_40"]
    sent_payload = [p for b, i, p in s.saved if i == "level_40"][0]
    # 장부 = 실제 전송 payload 의 시드 열(토큰 순서 그대로)
    assert rec["sent"] == {f: sent_payload[f] for f in c.EXPORT_SEED_FIELDS if f in sent_payload}
    assert rec["sent"] == {"ddaHardSeeds": "11,12,13", "ddaEasy2Seeds": "31,32,33"}
    assert rec["omitted"]["ddaEasySeeds"] == "evidence_gate:partial:2/3"
    assert rec["omitted"]["ddaHard2Seeds"] == "absent"
    assert rec["mapSha256"] == c.map_sha256(sent_payload)
    assert str(rec["useTileCount"]) == str(sent_payload["useTileCount"])
    assert rec["evidence"]["ddaHardSeeds"]["status"] == "ok"
    assert rec["evidence"]["ddaHardSeeds"]["tokens"][1]["verdict"] == "PATH_BOT"
    assert rec["evidence"]["ddaHardSeeds"]["tokens"][0]["verifier"] == "v4"
    assert rec["serverBefore"]["seeds"]["ddaEasySeeds"] == "1,2,3"
    assert rec["serverAfter"]["seeds"]["ddaHardSeeds"] == "11,12,13"
    assert rec["serverAfter"]["seeds"]["ddaEasySeeds"] == "1,2,3"          # 생략 열 = 서버 값 유지
    assert doc["rows"]["level_5"]["status"] == "failed"
    assert doc["memo"] == "1.1.2 업데이트" and doc["batchName"] == "배치"
    assert L.effective_seeds(rec)["ddaHardSeeds"] == "11,12,13"


def test_upload_infinity_row_records_relabel(server):
    j = lv(40)
    j["ddaInfinitySeeds"] = {"infinity_7": {"ddaHardSeeds": "5,6,7",
                                            "ddaSeedVerdicts": verdicts(j, "infinity_7",
                                                                        ddaHardSeeds=[(5, "PATH"), (6, "PATH"), (7, "PATH")])}}
    j["ddaHardSeeds"] = "91,92,93"                      # 정식 시드 — 무한 행엔 안 감
    s = server(FakeServer(rows={}))
    sid = client.post("/api/dda-ledger/sessions", json={}).json()["id"]
    r = client.post(f"/api/gboost/levels/infinity_7?ledger_session={sid}", json={"level_json": j})
    assert r.status_code == 200, r.text
    rec = L.load(sid)["rows"]["infinity_7"]
    sent = s.saved[0][2]
    assert rec["sent"] == {"ddaHardSeeds": "5,6,7"} and sent["ddaHardSeeds"] == "5,6,7"
    assert rec["relabel"]["rule"] == inf.RULE and rec["relabel"]["slot"] == 7 and rec["relabel"]["mapping"]
    assert rec["mapSha256"] == c.map_sha256(sent)
    assert rec["serverBefore"] == {"exists": False}
    assert rec["omitted"]["ddaEasySeeds"] == "absent"


def test_upload_without_session_goes_to_auto_session(server):
    server(FakeServer(rows={}))
    r = client.post("/api/gboost/levels/level_5", json={"level_json": lv(5)})
    assert r.status_code == 200
    snaps = L.list_snapshots()
    assert len(snaps) == 1 and snaps[0]["auto"] and snaps[0]["counts"]["sent"] == 1


def test_lookup_failure_recorded_as_failed(server):
    server(FakeServer(rows={}, fail_ids={"level_5"}))
    sid = client.post("/api/dda-ledger/sessions", json={}).json()["id"]
    r = client.post(f"/api/gboost/levels/level_5?ledger_session={sid}", json={"level_json": lv(5)})
    assert r.status_code == 502
    rec = L.load(sid)["rows"]["level_5"]
    assert rec["status"] == "failed" and rec["message"].startswith("lookup_failed") and rec["serverBefore"] is None
    assert all(v is None for v in L.effective_seeds(rec).values())


def test_upload_local_own_session(server, monkeypatch, tmp_path):
    loc = tmp_path / "local"
    loc.mkdir()
    (loc / "a.json").write_text(json.dumps({"level_data": lv(5, ddaHardSeeds="1,2,3")}))
    monkeypatch.setattr(gb_routes, "LOCAL_LEVELS_DIR", loc)
    monkeypatch.setattr(c, "SEED_EVIDENCE_REQUIRED", False)
    s = server(FakeServer(rows={}))
    r = client.post("/api/gboost/upload-local?ledger_memo=local&ledger_tag=t",
                    json={"board_id": "levels", "level_ids": ["a"], "rename_strategy": "custom",
                          "custom_names": {"a": "level_5"}, "overwrite": True})
    assert r.status_code == 200 and r.json()["uploaded"] == 1, r.text
    snaps = L.list_snapshots()
    assert snaps[-1]["status"] == "finalized" and snaps[-1]["source"] == "upload_local" and snaps[-1]["memo"] == "local"
    doc = L.load(snaps[-1]["id"])
    assert doc["rows"]["level_5"]["sent"] == {"ddaHardSeeds": "1,2,3"}
    assert doc["rows"]["level_5"]["serverAfter"]["seeds"]["ddaHardSeeds"] == "1,2,3"
    assert s.saved[0][2]["ddaHardSeeds"] == "1,2,3"


def test_seed_export_dry_run_not_recorded(server, tmp_path, monkeypatch):
    """[v2] 시드만 내보내기: 값 출처 = 배치 파일, 서버 = 보드 1회 조회. dry_run 은 장부 기록 없음."""
    from app.api.routes import production_store as ps
    monkeypatch.setattr(ps, "_STORE_DIR", str(tmp_path / "production"))
    os.makedirs(tmp_path / "production")
    with open(tmp_path / "production" / "b1.json", "w", encoding="utf-8") as f:
        json.dump({"batch_id": "b1", "batch": {}, "version": 1, "levels": [{"meta": {"level_number": 5}, "level_json": lv(5)}]}, f)
    server(FakeServer(rows={}))
    body = {"batch_id": "b1", "expected_batch_version": 1, "targets": [{"target_id": "level_5", "source_level": 5}]}
    r = client.post("/api/gboost/dda-seed-export", json={**body, "dry_run": True})
    assert r.status_code == 200 and r.json()["results"][0]["reason"] == "no_server_row"
    assert L.list_snapshots() == []
    r = client.post("/api/gboost/dda-seed-export",
                    json={**body, "dry_run": False, "expected_batch_sha256": r.json()["batchFileSha256"],
                          "preview_id": r.json()["preview_id"]})
    assert r.status_code == 200
    snaps = L.list_snapshots()
    assert len(snaps) == 1 and snaps[0]["source"] == "dda_seed_export"
    assert L.load(snaps[0]["id"])["rows"]["level_5"]["status"] == "blocked"


# ── 기준점·가상(배치) 비교 ─────────────────────────────────────────────────────────
def test_baseline_from_raw_and_batch_plan_diff(tmp_path):
    keys = ["id", "idx", "ddaEasy2Seeds", "ddaEasySeeds", "ddaHardSeeds", "ddaHard2Seeds", "useTileCount", "map"]
    j5 = lv(5)
    tp5 = conv(dict(j5))
    raw = {"__keys": keys, "__vals": [
        ["level_5", "1", "", "1,2,3", "4,5,6", "", tp5["useTileCount"], tp5["map"]],
        ["level_40", "2", "", "1,2,3", "", "", 3, {"layer": "1"}],
        ["infinity_1", "3", "", "", "7,8,9", "", 3, {"layer": "1"}],
        ["junk_row", "4", "", "", "", "", 3, {}]]}
    p = tmp_path / "levels.raw.json"
    p.write_text(json.dumps(raw))
    r = client.post("/api/dda-ledger/baseline/from-file", json={"path": str(p), "tag": "v0"})
    assert r.status_code == 200, r.text
    base = r.json()
    assert base["kind"] == "baseline" and base["counts"]["total"] == 3
    # 배치: level_5 시드 순서만 바뀜(근거 게이트: 서버와 다른 값 → 근거 필요 → 근거 넣음), level_40 맵 다름
    j5b = lv(5, ddaEasySeeds="3,1,2", ddaHardSeeds="4,5,6")
    j5b["ddaSeedVerdicts"] = verdicts(j5b, ddaEasySeeds=[(1, "PATH"), (2, "PATH"), (3, "PATH")])
    rows = plan_rows_from_batch([{"level_number": 5, "level_json": j5b}, {"level_number": 40, "level_json": lv(40)}],
                                L.load(base["id"])["rows"], infinity_mode="off")
    assert rows["level_5"]["sent"] == {"ddaEasySeeds": "3,1,2", "ddaHardSeeds": "4,5,6"}
    items = {it["id"]: it for it in L.diff_rows(L.load(base["id"])["rows"], rows)}
    assert items["level_5"]["fields"]["ddaEasySeeds"]["class"] == "reordered"
    assert items["level_5"]["fields"]["ddaHardSeeds"]["class"] == "same"
    assert not items["level_5"]["mapChanged"]
    assert items["level_40"]["mapChanged"]
    assert items["level_40"]["fields"]["ddaEasySeeds"]["class"] == "same"   # 생략 열 = 기준 값 유지
    assert items["infinity_1"]["rowRemoved"]
    # API(persist=True) → dryrun 스냅샷 + 목록에서 제외 옵션
    r = client.post("/api/dda-ledger/diff-batch", json={"base": base["id"], "levels": [
        {"level_number": 5, "level_json": j5b}], "infinity_mode": "off", "persist": True})
    assert r.status_code == 200, r.text
    assert r.json()["saved"]["kind"] == "dryrun"
    assert all(s["kind"] != "dryrun" for s in client.get("/api/dda-ledger/snapshots?include_dryrun=false").json()["snapshots"])
    d = client.get(f"/api/dda-ledger/diff?a={base['id']}&b={r.json()['saved']['id']}&format=csv")
    assert d.status_code == 200 and "reordered" in d.text
    tl = client.get("/api/dda-ledger/levels/level_5/timeline?include_dryrun=true").json()
    assert len(tl["entries"]) == 2 and tl["entries"][1]["changeFromPrev"]["ddaEasySeeds"]["class"] == "reordered"
    assert tl["lockModel"]["stores"] == "value"
