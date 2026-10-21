"""DDA 시드 갱신/익스포트 경량 검증 (문서 47).

fixture: tests/fixtures/dda_seeds/levels_fixture.json — LIVE 일치본 배치 level_json 사본 7개 + 출시 L158 테이블 행.
GameBoost 실서버 호출 없음: 저장/목록 경로는 가짜 클라이언트·가짜 HTTP 세션으로 대체한다.
"""
from __future__ import annotations

import copy
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gboost
from app.api.routes.gboost import _convert_to_townpop_format as conv
from app.clients import gboost as gb_client_mod
from app.core import dda_seed_catalog as c
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)

# 정답: dda_runtime_t0_20261020_1601/server/server_levels_dda_columns.csv level_158 행
E158 = "1155111777,1118964341,1181919731,1151877339,1102526043"
H158 = "1139242953,1154649038,1149573757,1148912175,1159080332"


def lv(n: int, **seeds) -> dict:
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(seeds)
    return j


def plan(n: int, j: dict) -> dict:
    return c.plan_level(n, j, conv(dict(j)))


@pytest.fixture
def snap158_matches_editor(monkeypatch):
    """L158 원본 행 스냅샷을 '에디터 변환 행과 같은 행'으로 바꿔 일반 익스포트의 유효 경로를 시험한다.
    (실제 출시 행은 에디터가 재현할 수 없는 null 값을 가져 row_changed 가 정상 — 아래 별도 테스트)"""
    rows = copy.deepcopy(c.load_source_rows())
    tp = conv(lv(158))
    base = rows["rows"]["level_158"]
    pred, unv = c.predict_readback(tp, base)          # [§13] 에디터 변환 행이 저장 후 읽힐 값 = 스냅샷으로 둔다
    assert not unv
    rows["rows"]["level_158"] = {k: pred[k] for k in base}
    monkeypatch.setattr(c, "_rows_cache", rows)


# ── 목록 / 해시 계약 ─────────────────────────────────────────────────────────

def test_catalog_pinned_and_counts():
    info = c.catalog_info()
    assert info["ok"] and info["sha256"] == c.CATALOG_SHA256
    assert info["counts"]["byStatus"] == {"candidate": 1216, "hold": 126, "auto_apply_excluded": 156, "partial_hold": 1}
    e = c.load_catalog()["_byLevel"][158]
    assert (e["ddaEasySeeds"], e["ddaHardSeeds"], e["N"]) == (E158, H158, 11)


def test_map_hash_matches_shipped_shard():
    e = c.load_catalog()["_byLevel"][158]
    assert c.map_sha256(conv(lv(158))) == e["sourceMapSha256"]


def test_source_condition_hash_golden_excludes_seed_fields():
    row = _FX["liveRow158"]
    gold = c.load_catalog()["_byLevel"][158]["sourceConditionHash"]
    assert c.source_condition_hash(row) == gold
    with_seeds = {**row, "ddaEasySeeds": E158, "ddaHardSeeds": H158}
    assert c.source_condition_hash(with_seeds) == gold            # 두 필드는 해시 제외 → 자기불일치 없음
    import hashlib
    naive = hashlib.sha256(c.dump({k: v for k, v in with_seeds.items() if k != "map"})).hexdigest()
    assert naive != gold                                          # 포함했다면 불일치(대조용)


def test_catalog_tamper_rejected(monkeypatch, tmp_path):
    p = tmp_path / "cat.json"
    p.write_bytes(open(c.CATALOG_PATH, "rb").read().replace(E158.encode(), E158.replace("1155", "1154").encode()))
    monkeypatch.setattr(c, "CATALOG_PATH", str(p))
    monkeypatch.setattr(c, "_cache", None)
    assert c.catalog_info()["ok"] is False
    r = plan(158, lv(158))
    assert (r["action"], r["reason"]) == ("skip", "catalog_error")
    f = c.export_fields("levels", "level_158", lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158), conv(lv(158)))
    assert (f["ddaEasySeeds"], f["ddaHardSeeds"], f["reason"]) == ("", "", "catalog_error")
    monkeypatch.setattr(c, "_cache", None)   # 다음 테스트는 원본 목록으로 다시 로드


# ── 갱신 정책 ────────────────────────────────────────────────────────────────

def test_l158_existing_values_kept():
    r = plan(158, lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158))
    assert (r["action"], r["reason"]) == ("keep", "already_valid")


def test_fill_both_then_idempotent():
    r = plan(158, lv(158))
    assert r["action"] == "update"
    assert {k: (d["state"], d["before"], d["after"]) for k, d in r["fields"].items()} == {
        "ddaEasySeeds": ("missing", None, E158), "ddaHardSeeds": ("missing", None, H158)}
    j = lv(158, **{k: d["after"] for k, d in r["fields"].items()})
    assert plan(158, j)["action"] == "keep"


def test_fill_one_side_only():
    r = plan(158, lv(158, ddaEasySeeds=E158, ddaHardSeeds=""))
    assert r["action"] == "update"
    assert r["fields"]["ddaEasySeeds"]["state"] == "match" and r["fields"]["ddaEasySeeds"]["after"] == E158
    assert r["fields"]["ddaHardSeeds"]["state"] == "missing" and r["fields"]["ddaHardSeeds"]["after"] == H158


@pytest.mark.parametrize("bad", [
    "1,2,3,4",                                  # 개수 부족
    "1,2,3,4,5,6",                              # 개수 초과
    "0,1,2,3,4",                                # 0
    "-1,1,2,3,4",                               # 음수
    "2147483648,1,2,3,4",                       # Int32 overflow
    "1, 2,3,4,5",                               # 공백
    "01,2,3,4,5",                               # 선행 0
    "1,2,3,4,",                                 # 빈 토큰
    "a,b,c,d,e",                                # 숫자 아님
    12345,                                      # 문자열 아님
])
def test_invalid_recovered_with_before_after(bad):
    r = plan(158, lv(158, ddaEasySeeds=bad, ddaHardSeeds=H158))
    assert r["action"] == "update"
    d = r["fields"]["ddaEasySeeds"]
    assert d["state"] == "invalid" and d["after"] == E158 and d["before"] == (bad if isinstance(bad, str) else str(bad))
    assert r["fields"]["ddaHardSeeds"]["state"] == "match"


def test_other_valid_value_is_conflict_both_skipped():
    other = ",".join(reversed(E158.split(",")))   # 정상 형식·다른 값(순서 다름)
    r = plan(158, lv(158, ddaEasySeeds=other, ddaHardSeeds=""))
    assert (r["action"], r["reason"]) == ("conflict", "conflict")
    assert r["fields"]["ddaEasySeeds"]["after"] == other
    assert r["fields"]["ddaHardSeeds"]["after"] == ""            # 부족한 쪽도 건너뜀
    f = c.export_fields("levels", "level_158", lv(158, ddaEasySeeds=other, ddaHardSeeds=H158), conv(lv(158)))
    assert (f["ddaEasySeeds"], f["ddaHardSeeds"], f["reason"]) == ("", "", "conflict")


@pytest.mark.parametrize("n,reason", [
    (322, "partial_hold"), (111, "hold"), (40, "excluded"), (5, "no_data"), (1466, "map_mismatch")])
def test_non_candidates_skipped_with_reason(n, reason):
    r = plan(n, lv(n, ddaEasySeeds=E158, ddaHardSeeds=H158))
    assert (r["action"], r["reason"]) == ("skip", reason)
    f = c.export_fields("levels", f"level_{n}", lv(n, ddaEasySeeds=E158, ddaHardSeeds=H158), conv(lv(n)))
    assert (f["ddaEasySeeds"], f["ddaHardSeeds"]) == ("", "")


def test_map_changed_is_skipped():
    j = lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)
    tiles = j["layer_0"]["tiles"]
    k = next(iter(tiles))
    tiles[k] = ["t1" if tiles[k][0] != "t1" else "t2"] + tiles[k][1:]
    assert plan(158, j)["reason"] == "map_mismatch"


def test_n_mismatch_is_skipped():
    tp = conv(lv(158))
    tp["useTileCount"] = "10"
    r = c.plan_level(158, lv(158), tp)
    assert (r["action"], r["reason"]) == ("skip", "n_mismatch")


# ── 익스포트 ─────────────────────────────────────────────────────────────────

def test_export_valid_and_preserves_existing_columns(snap158_matches_editor):
    j = lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)
    before = copy.deepcopy(j)
    base = conv(dict(j))
    out = c.apply_export_fields("levels", "level_158", j, conv(dict(j)))
    assert j == before                                             # 내부 값 불변
    assert (out["ddaEasySeeds"], out["ddaHardSeeds"]) == (E158, H158)
    rest = {k: v for k, v in out.items() if k not in c.SEED_FIELDS}
    base.pop("etime"); rest.pop("etime")                           # 업로드 시각(기존 동작)만 다를 수 있음
    assert rest == base and list(rest) == list(base)               # 기존 컬럼·순서·map 불변
    for s in (out["ddaEasySeeds"], out["ddaHardSeeds"]):
        assert len(s.split(",")) == 5 and " " not in s


def test_normal_export_row_changed_vs_shipped_row_blanks_seeds():
    """[P1 원인] 에디터 일반 익스포트 행은 출시 행과 다르다 → 유효 시드라도 "" (row_changed)."""
    j = lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)
    f = c.export_fields("levels", "level_158", j, conv(dict(j)))
    assert (f["ddaEasySeeds"], f["ddaHardSeeds"]) == ("", "")
    # [§13] L159 실측 규칙으로 표현 차이(backgroundIndex/tileSkin "0"→null, rewardList "[]"→null, 미전송 visualTileSeed)는
    # 동치로 보고, 실제 값 차이(rewardCoin 기본 10 vs 출시 5, difficulty 미측정 -1 vs 61)만 남는다
    assert "rewardCoin" in f["reason"] and "difficulty" in f["reason"], f["reason"]
    for k in ("backgroundIndex", "tileSkin", "rewardList", "visualTileSeed"):
        assert k not in f["reason"], f["reason"]


def test_export_blank_cases_and_serialization():
    tp = conv(lv(158))
    one_side = c.export_fields("levels", "level_158", lv(158, ddaEasySeeds=E158), tp)
    assert (one_side["ddaEasySeeds"], one_side["ddaHardSeeds"], one_side["reason"]) == ("", "", "missing")
    inf = c.export_fields("levels", "infinity_1", lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158), tp)
    assert (inf["ddaEasySeeds"], inf["ddaHardSeeds"], inf["reason"]) == ("", "", "not_level_row")
    assert c.export_fields("other_board", "level_158", lv(158), tp) is None
    out = c.apply_export_fields("levels", "level_40", lv(40, ddaEasySeeds=E158, ddaHardSeeds=H158), conv(lv(40)))
    s = json.dumps({"level_40": out})
    assert '"ddaEasySeeds": ""' in s and '"ddaHardSeeds": ""' in s


# ── API (실서버 호출 없음) ──────────────────────────────────────────────────

client = TestClient(app)


def _restore_override(prev):
    """conftest 의 전역 Fake 의존성 override 를 되돌린다(pop 하면 격리가 풀림)."""
    if prev is None:
        app.dependency_overrides.pop(get_gboost, None)
    else:
        app.dependency_overrides[get_gboost] = prev


def test_preview_and_export_preview_routes():
    body = {"levels": [{"level_number": 158, "level_json": lv(158)},
                       {"level_number": 322, "level_json": lv(322)}]}
    r = client.post("/api/dda-seeds/preview", json=body).json()
    assert r["catalog"]["ok"] and r["summary"]["byAction"] == {"update": 1, "skip": 1}
    r2 = client.post("/api/dda-seeds/export-preview", json={
        "board_id": "levels",
        "levels": [{"target_id": "level_158", "level_json": lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)},
                   {"target_id": "infinity_3", "level_json": lv(158)}]}).json()
    assert [(x["target_id"], x["ddaEasySeeds"]) for x in r2["results"]] == [("level_158", ""), ("infinity_3", "")]
    assert r2["results"][0]["reason"].startswith("row_changed:")


class _FakeClient:
    is_configured = True

    def __init__(self):
        self.saved = []

    async def save_level(self, board_id, level_id, level_json):
        self.saved.append((board_id, level_id, json.loads(json.dumps(level_json))))
        return {"success": True, "saved_at": "x", "message": "ok"}

    async def save_thumbnail(self, *a, **k):
        return {"success": True}

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        return None                                          # 새 행 (서버 값 없음)


def test_gboost_save_route_payload_has_fields(snap158_matches_editor):
    fake = _FakeClient()
    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: fake
    try:
        for lid, j in (("level_158", lv(158, ddaEasySeeds=E158, ddaHardSeeds=H158)), ("level_322", lv(322))):
            assert client.post(f"/api/gboost/levels/{lid}", json={"level_json": j}).status_code == 200
        assert client.post("/api/gboost/other/level_158", json={"level_json": lv(158)}).status_code == 200
    finally:
        _restore_override(prev)
    p = {(b, lid): pl for b, lid, pl in fake.saved}
    assert (p[("levels", "level_158")]["ddaEasySeeds"], p[("levels", "level_158")]["ddaHardSeeds"]) == (E158, H158)
    assert (p[("levels", "level_322")]["ddaEasySeeds"], p[("levels", "level_322")]["ddaHardSeeds"]) == ("", "")
    assert "ddaEasySeeds" not in p[("other", "level_158")]
    assert c.map_sha256(p[("levels", "level_158")]) == c.load_catalog()["_byLevel"][158]["sourceMapSha256"]


def test_list_levels_reads_server_seed_columns(monkeypatch):
    raw = {"__keys": ["id", "difficulty", "ddaEasySeeds", "ddaHardSeeds"],
           "__vals": [["level_158", 61, E158, H158], ["level_159", 50, "", None]]}

    class _Resp:
        status = 200

        async def text(self):
            return json.dumps(raw)

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
    cli.base_url, cli.project_id, cli.api_key = "http://fixture.invalid", "p", "k"
    monkeypatch.setattr(gb_client_mod.GBoostClient, "is_configured", property(lambda self: True))
    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: cli
    try:
        r = client.get("/api/gboost/levels", params={"prefix": "level_"}).json()
    finally:
        _restore_override(prev)
    by = {x["id"]: x for x in r["levels"]}
    assert (by["level_158"]["dda_easy_seeds"], by["level_158"]["dda_hard_seeds"]) == (E158, H158)
    assert (by["level_159"]["dda_easy_seeds"], by["level_159"]["dda_hard_seeds"]) == ("", "")
