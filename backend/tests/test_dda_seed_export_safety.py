"""DDA 시드만 내보내기 · 업로드 fail-closed 검증 (문서 47 §5, P1/P2).

외부 통신 없음: conftest 가 전송 계층을 차단하고, 여기서는 메모리 가짜 서버(FakeServer)를 의존성으로 주입한다.
서버 행 = 출시 원본 행 스냅샷(골든) + 출시와 같은 map + 시드 컬럼 — 실제 서버 표현(자료형)은 미확인이라
정수/문자열 두 표현을 모두 시험한다.
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
from app.clients import gboost as gb_client_mod
from app.clients.gboost import GBoostLookupError
from app.core import dda_seed_catalog as c
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)

E158 = "1155111777,1118964341,1181919731,1151877339,1102526043"
H158 = "1139242953,1154649038,1149573757,1148912175,1159080332"
client = TestClient(app)


def lv(n, **kw):
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(kw)
    return j


def server_row(n, *, easy="", hard="", stringify=False, map_as_str=False, **over):
    """출시 행 스냅샷 + 출시 map(에디터 변환 map 의 해시 = sourceMapSha256 확인됨) + 시드 + etime."""
    row = copy.deepcopy(c.load_source_rows()["rows"][f"level_{n}"])
    if stringify:   # 숫자 문자열 표현(서버가 문자열로 돌려주는 경우)
        row = {k: (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in row.items()}
    m = conv(lv(n))["map"]
    row["map"] = json.dumps(m) if map_as_str else m
    row["etime"] = "1790000000"
    if easy is not None:
        row["ddaEasySeeds"] = easy
    if hard is not None:
        row["ddaHardSeeds"] = hard
    row.update(over)
    return row


class FakeServer:
    is_configured = True
    base_url, project_id = "fake://", "fake"

    def __init__(self, rows=None, fail_ids=(), fail_list=False):
        self.rows = rows or {}
        self.fail_ids = set(fail_ids)
        self.fail_list = fail_list
        self.saved, self.loads = [], []

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        self.loads.append((level_id, strict))
        if level_id in self.fail_ids:
            if strict:
                raise GBoostLookupError("HTTP 500 (fake)")
            return None
        r = self.rows.get(level_id)
        return None if r is None else {"level_json": copy.deepcopy(r), "metadata": {}}

    async def list_levels(self, board_id, prefix="level_", limit=100, project_id_override="", strict=False):
        if self.fail_list:
            if strict:
                raise GBoostLookupError("timeout (fake)")
            return []
        return [{"id": k} for k in self.rows]

    async def save_level(self, board_id, level_id, level_json):
        self.saved.append((board_id, level_id, json.loads(json.dumps(level_json))))
        return {"success": True}

    async def save_thumbnail(self, *a, **k):
        self.saved.append(("thumbnail",) + a[:2])
        return {"success": True}

    async def update_existing_level(self, board_id, level_id, row):
        self.saved.append((board_id, level_id, json.loads(json.dumps(row))))
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


@pytest.fixture
def partial_on(monkeypatch):
    """부분 수정 전송 게이트를 시험용으로만 연다(기본값 False 는 실서버 근거 확보 전 차단)."""
    monkeypatch.setattr(c, "PARTIAL_UPDATE_VERIFIED", True)


def seed_export(targets, dry_run=True, confirm=False):
    return client.post("/api/gboost/dda-seed-export",
                       json={"targets": targets, "dry_run": dry_run, "confirm": confirm}).json()["results"]


# ── 스냅샷 신뢰 기준 ─────────────────────────────────────────────────────────

def test_source_rows_pinned_and_bound_to_catalog():
    rows = c.load_source_rows()
    assert len(rows["rows"]) == 1499 and rows["catalogSha256"] == c.CATALOG_SHA256
    snap = rows["rows"]["level_158"]
    assert snap == _FX["liveRow158"]                              # 골든(출시 행) 그대로·자료형 보존
    assert c.source_condition_hash(snap) == c.load_catalog()["_byLevel"][158]["sourceConditionHash"]


# ── 시드만 내보내기: 두 컬럼만 변경 ───────────────────────────────────────────

@pytest.mark.parametrize("stringify,map_as_str,empty", [
    (False, False, ""), (True, False, ""), (False, True, None), (True, True, "")])
def test_seed_only_changes_only_two_columns(server, partial_on, stringify, map_as_str, empty):
    row = server_row(158, easy=empty, hard=empty, stringify=stringify, map_as_str=map_as_str)
    if empty is None:                       # null 값(키는 있음)
        row["ddaEasySeeds"] = None
        row["ddaHardSeeds"] = None
    s = server(FakeServer({"level_158": row}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)}]
    pre = seed_export(t)
    assert pre[0]["status"] == "preview" and pre[0]["change"] == "fill" and not s.saved
    t[0]["expected_server_digest"] = pre[0]["serverDigest"]
    res = seed_export(t, dry_run=False)
    assert res[0]["status"] == "saved"
    (board, lid, payload), = s.saved
    assert (board, lid) == ("levels", "level_158")
    # [§9] 부분 수정: 정확히 두 시드 필드만 전송 (다른 컬럼·map·etime·rewardList 미전송)
    assert payload == {"ddaEasySeeds": E158, "ddaHardSeeds": H158}
    assert all(("thumbnail" not in x) for x in s.saved)


def test_seed_only_same_value_not_sent(server):
    s = server(FakeServer({"level_158": server_row(158, easy=E158, hard=H158)}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)}]
    pre = seed_export(t)
    assert pre[0]["change"] == "same"
    t[0]["expected_server_digest"] = pre[0]["serverDigest"]
    assert seed_export(t, dry_run=False)[0]["status"] == "unchanged" and not s.saved


@pytest.mark.parametrize("internal,server_vals,change", [
    ({}, (E158, H158), "clear"),                                               # 내부 값 없음 → 서버 값 비움
    ({"ddaEasySeeds": E158, "ddaHardSeeds": H158}, ("1,2,3,4,5", "6,7,8,9,10"), "change"),
])
def test_seed_only_clear_or_change_needs_confirm(server, partial_on, internal, server_vals, change):
    s = server(FakeServer({"level_158": server_row(158, easy=server_vals[0], hard=server_vals[1])}))
    t = [{"target_id": "level_158", "level_json": lv(158, **internal)}]
    pre = seed_export(t)
    assert pre[0]["change"] == change
    t[0]["expected_server_digest"] = pre[0]["serverDigest"]
    r = seed_export(t, dry_run=False, confirm=False)
    assert (r[0]["status"], r[0]["reason"]) == ("blocked", "needs_dda_confirm") and not s.saved
    assert seed_export(t, dry_run=False, confirm=True)[0]["status"] == "saved"
    assert s.saved[0][2] == ({"ddaEasySeeds": "", "ddaHardSeeds": ""} if change == "clear"
                             else {"ddaEasySeeds": E158, "ddaHardSeeds": H158})


@pytest.mark.parametrize("mutate,reason", [
    (lambda r: r.update(rewardCoin=6), "server_row_differs"),
    (lambda r: r.update(zzUnknown="x"), "server_row_differs"),                # 미지 필드 → 신뢰 불가 차단
    (lambda r: r.pop("visualTileSeed"), "server_row_differs"),                # 키 누락
    (lambda r: r.pop("ddaHardSeeds"), "no_seed_column"),
    (lambda r: r["map"]["layer_0"]["tiles"].update({"0_0": ["t2", ""]}), "server_map_differs"),
    (lambda r: r.update(map="not json"), "server_map_unverifiable"),
])
def test_seed_only_blocks_untrusted_server_row(server, mutate, reason):
    row = server_row(158)
    mutate(row)
    s = server(FakeServer({"level_158": row}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)}]
    r = seed_export(t)
    assert (r[0]["blocked"], r[0]["reason"]) == (True, reason)
    t[0]["expected_server_digest"] = "x"
    assert seed_export(t, dry_run=False, confirm=True)[0]["status"] == "blocked" and not s.saved


def test_seed_only_lookup_fail_missing_row_and_stale_preview(server):
    row = server_row(158)
    s = server(FakeServer({"level_158": row}, fail_ids={"level_159"}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)},
         {"target_id": "level_159", "level_json": lv(159)},
         {"target_id": "level_5", "level_json": lv(5)}]
    pre = {x["target_id"]: x for x in seed_export(t)}
    assert pre["level_159"]["reason"] == "lookup_failed"
    assert pre["level_5"]["reason"] == "no_snapshot"
    # 재시도에 묵은 digest 사용 → 서버 행이 바뀌었으면 차단
    t[0]["expected_server_digest"] = pre["level_158"]["serverDigest"]
    row["etime"] = "1790000001"
    r = seed_export(t[:1], dry_run=False)
    assert r[0]["reason"] == "server_changed_since_preview" and not s.saved
    t[0].pop("expected_server_digest")
    assert seed_export(t[:1], dry_run=False)[0]["reason"] == "server_changed_since_preview"
    s.rows.pop("level_158")
    assert seed_export(t[:1])[0]["reason"] == "no_server_row"
    assert all(strict for _, strict in s.loads)                   # 모든 조회 strict


def test_seed_only_l1466_and_hold_levels(server):
    """L1466: 에디터 map ≠ 출시 → 시드 "" + 서버 map(에디터 기준)도 출시와 달라 차단. 보류/제외는 "" 로만."""
    rows = {"level_1466": server_row(1466), "level_322": server_row(322, easy=E158, hard=H158),
            "level_40": server_row(40)}
    server(FakeServer(rows))
    r = {x["target_id"]: x for x in seed_export([
        {"target_id": "level_1466", "level_json": lv(1466, ddaEasySeeds=E158, ddaHardSeeds=H158)},
        {"target_id": "level_322", "level_json": lv(322)},
        {"target_id": "level_40", "level_json": lv(40)}])}
    assert r["level_1466"]["reason"] == "server_map_differs"
    assert (r["level_322"]["change"], r["level_322"]["reason"]) == ("clear", "partial_hold")
    assert (r["level_40"]["change"], r["level_40"]["reason"]) == ("same", "excluded")


# ── 일반 업로드 경로 fail-closed (단일 · 일괄) ─────────────────────────────────

def test_single_save_fail_closed(server):
    j = lv(158)
    s = server(FakeServer({"level_158": server_row(158, easy=E158, hard=H158)}, fail_ids={"level_159"}))
    r = client.post("/api/gboost/levels/level_159", json={"level_json": lv(159)})
    assert r.status_code == 502 and not s.saved                    # 조회 실패 → 업로드 안 함
    r = client.post("/api/gboost/levels/level_158", json={"level_json": j})
    assert r.status_code == 409 and not s.saved                    # 서버 시드 비움 → 확인 필요
    r = client.post("/api/gboost/levels/level_158", json={"level_json": j, "dda_confirm": True})
    assert r.status_code == 200 and s.saved[0][1] == "level_158"
    s.saved.clear()
    r = client.post("/api/gboost/levels/level_777", json={"level_json": lv(159)})
    assert r.status_code == 200                                     # 새 행(서버 값 없음)
    r = client.post("/api/gboost/other/level_158", json={"level_json": j})
    assert r.status_code == 200 and "ddaEasySeeds" not in s.saved[-1][2]


def test_general_edit_values_preserved_in_normal_export(server):
    """일반 익스포트는 사용자가 바꾼 기존 필드를 스냅샷으로 덮어쓰지 않는다(시드만 "" 로 막음)."""
    s = server(FakeServer({}))
    j = lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158, rewardCoin=7, tileSkin=2)
    assert client.post("/api/gboost/levels/level_158", json={"level_json": j}).status_code == 200
    p = [x for x in s.saved if x[0] == "levels"][0][2]
    assert (p["rewardCoin"], p["tileSkin"]) == ("7", "2")
    assert (p["ddaEasySeeds"], p["ddaHardSeeds"]) == ("", "")


def test_upload_local_fail_closed(server, monkeypatch, tmp_path):
    monkeypatch.setattr(gb_routes, "LOCAL_LEVELS_DIR", tmp_path)
    for n in (158, 159):
        (tmp_path / f"l{n}.json").write_text(json.dumps({"level_data": lv(n)}))
    s = server(FakeServer({"level_158": server_row(158, easy=E158, hard=H158)}, fail_ids={"level_159"}))
    body = {"board_id": "levels", "level_ids": ["l158", "l159"], "rename_strategy": "custom",
            "custom_names": {"l158": "level_158", "l159": "level_159"}, "overwrite": True}
    r = client.post("/api/gboost/upload-local", json=body).json()
    st = {x["target_id"]: x["status"] for x in r["results"]}
    assert st == {"level_158": "skipped", "level_159": "failed"} and not s.saved
    r = client.post("/api/gboost/upload-local", json={**body, "dda_confirm": True}).json()
    st = {x["target_id"]: x["status"] for x in r["results"]}
    assert st == {"level_158": "success", "level_159": "failed"}
    assert [x[1] for x in s.saved if x[0] == "levels"] == ["level_158"]


def test_list_strict_fail_closed(server):
    server(FakeServer({}, fail_list=True))
    assert client.get("/api/gboost/levels", params={"strict": "true"}).status_code == 502
    assert client.get("/api/gboost/levels").json()["levels"] == []   # 기존(비strict) 동작 유지


@pytest.mark.parametrize("status,body,exc", [(500, "err", True), (200, "", True), (200, "{bad", True),
                                             (404, "", False), (200, "{}", False)])
def test_client_strict_lookup_distinguishes_error_from_absent(monkeypatch, status, body, exc):
    import asyncio

    class _Resp:
        def __init__(self):
            self.status = status

        async def text(self):
            return body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Sess:
        def __init__(self, *a, **k):
            pass

        def get(self, *a, **k):
            return _Resp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(gb_client_mod.aiohttp, "ClientSession", _Sess)
    cli = gb_client_mod.GBoostClient.__new__(gb_client_mod.GBoostClient)
    cli.base_url, cli.project_id, cli.api_key = "fake://", "p", "k"
    if exc:
        with pytest.raises(GBoostLookupError):
            asyncio.run(cli.load_level("levels", "level_1", strict=True))
    else:
        assert asyncio.run(cli.load_level("levels", "level_1", strict=True)) is None
    assert asyncio.run(cli.load_level("levels", "level_1")) is None        # 비strict 는 기존대로 None


def test_seed_only_server_idx_excluded_and_preserved_out_of_payload(server, partial_on):
    """서버가 레코드 번호 idx 를 돌려줘도 비교·payload 에서 제외(서버 관리 키, 기존 업로드도 보내지 않음)."""
    row = server_row(158)
    row["idx"] = 4242
    s = server(FakeServer({"level_158": row}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)}]
    pre = seed_export(t)
    assert pre[0]["change"] == "fill"
    t[0]["expected_server_digest"] = pre[0]["serverDigest"]
    assert seed_export(t, dry_run=False)[0]["status"] == "saved"
    assert set(s.saved[0][2]) == {"ddaEasySeeds", "ddaHardSeeds"}


@pytest.mark.parametrize("status,head,ok", [(200, "level_158=upt", True), (200, "level_158=new", False),
                                            (200, "", False), (500, "level_158=upt", False)])
def test_update_existing_level_no_new_record_fallback(monkeypatch, status, head, ok):
    import asyncio
    posts = []

    class _Resp:
        def __init__(self):
            self.status = status

        async def text(self):
            return head + "\n"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Sess:
        def __init__(self, *a, **k):
            pass

        def post(self, url, data=None, **k):
            posts.append(dict(data))
            return _Resp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(gb_client_mod.aiohttp, "ClientSession", _Sess)
    cli = gb_client_mod.GBoostClient.__new__(gb_client_mod.GBoostClient)
    cli.base_url, cli.project_id, cli.api_key = "fake://", "p", "k"
    r = asyncio.run(cli.update_existing_level("levels", "level_158", {"a": 1}))
    assert r["success"] is ok
    assert len(posts) == 1 and posts[0]["new"] == "0"            # 1회, new=0 만 (new=1 폴백 없음)



def test_server_extra_column_field4_blocks(server):
    """[18:3x 사용자 지시] 서버 추가 키(field4 등)는 기준 완화 없이 차단 유지."""
    row = server_row(158)
    row["field4"] = ""
    server(FakeServer({"level_158": row}))
    pre = seed_export([{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)}])
    assert (pre[0]["blocked"], pre[0]["reason"]) == (True, "server_row_differs")



def test_partial_update_blocked_by_default_no_post(server):
    """[§9] 기본(PARTIAL_UPDATE_VERIFIED=False): 검증을 다 통과해도 실제 POST 0 — partial_update_unverified."""
    assert c.PARTIAL_UPDATE_VERIFIED is False
    s = server(FakeServer({"level_158": server_row(158)}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)}]
    pre = seed_export(t)
    assert pre[0]["change"] == "fill"
    t[0]["expected_server_digest"] = pre[0]["serverDigest"]
    r = seed_export(t, dry_run=False, confirm=True)
    assert (r[0]["status"], r[0]["reason"]) == ("blocked", "partial_update_unverified") and not s.saved


def test_partial_payload_guard_rejects_extra_keys_or_bad_values():
    c.assert_partial_payload({"ddaEasySeeds": E158, "ddaHardSeeds": ""})
    for bad in ({"ddaEasySeeds": E158}, {"ddaEasySeeds": E158, "ddaHardSeeds": H158, "rewardList": None},
                {"ddaEasySeeds": "1,2", "ddaHardSeeds": H158}):
        with pytest.raises(ValueError):
            c.assert_partial_payload(bad)


def test_partial_mode_race_and_lookup_errors_block(server, partial_on):
    row = server_row(158)
    s = server(FakeServer({"level_158": row}, fail_ids={"level_159"}))
    t = [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)},
         {"target_id": "level_159", "level_json": lv(159)}]
    pre = {x["target_id"]: x for x in seed_export(t)}
    t[0]["expected_server_digest"] = pre["level_158"]["serverDigest"]
    row["etime"] = "1790000099"                                   # 미리보기 후 서버 행 변경
    r = {x["target_id"]: x for x in seed_export(t, dry_run=False, confirm=True)}
    assert r["level_158"]["reason"] == "server_changed_since_preview"
    assert r["level_159"]["reason"] == "lookup_failed"
    assert not s.saved
