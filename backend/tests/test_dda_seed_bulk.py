"""DDA 시드 일괄 업로드 준비·실행기 mock 검증 (문서 47 §13). 외부 통신 없음(conftest 차단 + 가짜 서버)."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

from app.api.deps import get_gboost  # noqa: E402
from app.api.routes.gboost import _convert_to_townpop_format as conv  # noqa: E402
from app.core import dda_seed_catalog as c  # noqa: E402
from app.main import app  # noqa: E402
import dda_seed_bulk_20261020 as B  # noqa: E402
import dda_seed_server_apply_20261020 as base  # noqa: E402

FIXD = BACKEND / "tests" / "fixtures" / "dda_seeds"
FX = json.loads((FIXD / "levels_fixture.json").read_text())
E158 = "1155111777,1118964341,1181919731,1151877339,1102526043"
H158 = "1139242953,1154649038,1149573757,1148912175,1159080332"
META = {158: 0.6113, 159: 0.6145}
client = TestClient(app)


# ── 일반 업로드 회귀 (시드 미포함 경로 payload 동일) ────────────────────────────

def test_normal_upload_payload_unchanged_vs_golden():
    golden = json.loads((FIXD / "normal_upload_golden_before_bulk.json").read_text())
    saved = []

    class F:
        is_configured = True

        async def load_level(self, *a, **k):
            return None

        async def save_level(self, b, i, j):
            saved.append(json.loads(json.dumps(j)))
            return {"success": True, "saved_at": "", "message": ""}

        async def save_thumbnail(self, *a, **k):
            return {"success": True}

    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: F()
    try:
        for g in golden:
            lvl = g["id"].split("_")[1]
            j = copy.deepcopy(FX["levels"].get(lvl, FX["levels"]["159"]))
            if g["id"] == "level_158" and g["payload"].get("ddaEasySeeds") == "" and len(saved) == 1:
                j.update(ddaEasySeeds=E158, ddaHardSeeds=H158)
            assert client.post(f"/api/gboost/{g['board']}/{g['id']}", json={"level_json": j}).status_code == 200
            p = saved[-1]
            p.pop("etime", None)
            assert p == g["payload"], g["id"]
    finally:
        app.dependency_overrides[get_gboost] = prev


# ── 준비(classify) ─────────────────────────────────────────────────────────

def srow(n, **over):
    """서버 행 = 출시 행 + 출시 map + 서버 전용 키(idx/''/field4/etime) + 빈 시드."""
    snap = c.load_source_rows()["rows"][f"level_{n}"]
    r = {"id": f"level_{n}", "idx": str(60000 + n), "etime": "1787117533"}
    for k, v in snap.items():
        if k != "id":
            r[k] = copy.deepcopy(v)
    r.update({"ddaEasySeeds": "", "ddaHardSeeds": "", "": "", "field4": ""})
    r["map"] = conv(copy.deepcopy(FX["levels"][str(n)]))["map"]
    r.update(over)
    return r


def lj(n, **kw):
    j = copy.deepcopy(FX["levels"][str(n)])
    e = c.load_catalog()["_byLevel"].get(n)
    if e and e["status"] == "candidate":
        j.update(ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"])
    j.update(kw)
    return j


def cls(n, srv, meta=None, **kw):
    return B.classify(f"level_{n}", n, lj(n, **kw), {"predicted_clear_rate": META.get(n, 0.5)} if meta is None else meta, srv)


def test_ready_payload_is_converter_plus_two_seeds_and_readback_matches_shipped():
    r = cls(158, srow(158))
    assert (r["category"], r["reason"]) == ("ready", "fill") and r["condOk"] and r["mapOk"]
    up = B.ui_upload_json(lj(158), {"predicted_clear_rate": 0.6113}, 158)
    expect = conv(copy.deepcopy(up))
    expect["ddaEasySeeds"], expect["ddaHardSeeds"] = E158, H158
    p = dict(r["payload"]); p.pop("etime"); expect.pop("etime")
    assert p == expect                                        # 기존 변환기 출력 + 두 시드뿐
    assert (p["rewardCoin"], p["difficulty"], p["rewardList"]) == ("5", "61", "[]")
    assert r["expected"]["rewardList"] is None and r["expected"]["backgroundIndex"] is None


@pytest.mark.parametrize("over,cat,reason", [
    ({"rewardList": [["gold", 10, 0, 0]]}, "hold", "meaning_change:rewardList"),        # 비어있지 않은 보상 보존 → 보류
    ({"rewardCoin": 7}, "hold", "meaning_change:rewardCoin"),
    ({"difficulty": 40}, "hold", "meaning_change:difficulty"),
    ({"useInRandomizer": "", "useTeleportInRandomizer": ""}, "approval_needed", 'checkbox_restore(""→0)'),
    ({"useInRandomizer": 1}, "hold", "meaning_change:useInRandomizer"),
    ({"ddaEasySeeds": "1,2,3,4,5"}, "hold", "server_seed_conflict"),
    ({"ddaEasySeeds": E158, "ddaHardSeeds": H158}, "keep", "server_seeds_equal_catalog"),
    ({"ddaEasySeeds": E158, "ddaHardSeeds": H158, "useInRandomizer": ""}, "approval_needed",
     "keep_but_condition_mismatch:useInRandomizer"),
])
def test_classify_holds_and_approvals(over, cat, reason):
    r = cls(158, srow(158, **over))
    assert (r["category"], r["reason"]) == (cat, reason)


def test_classify_other_holds():
    assert cls(158, None)["reason"] == "no_server_row"
    assert cls(158, srow(158), meta={})["reason"].startswith("predicted_missing")
    assert cls(1466, srow(1466))["reason"] == "internal_map_mismatch"
    assert cls(322, srow(322))["category"] == "not_candidate"
    m = srow(158)
    m["map"] = copy.deepcopy(m["map"]); m["map"]["layer"] = "9"
    assert cls(158, m)["reason"] == "map_mismatch"


# ── 실행기 ─────────────────────────────────────────────────────────────────

class FakeServer:
    def __init__(self, rows):
        self.rows = {k: copy.deepcopy(v) for k, v in rows.items()}
        self.posts, self.thumbs, self.gets = [], 0, 0
        self.respond = "upt"
        self.mutate_on_read = None
        self.store_override = None

    def raw_board(self):
        ks = list(next(iter(self.rows.values())).keys())
        return json.dumps({"__keys": ks, "__vals": [[r[k] for k in ks] for r in self.rows.values()]}).encode()

    async def fetch_raw(self, cli, lid):
        self.gets += 1
        if self.mutate_on_read:
            self.mutate_on_read(self.rows[lid])
        r = self.rows[lid]
        ks = list(r.keys())
        return b"", ks, [r[k] for k in ks]

    async def update(self, board, lid, payload):
        self.posts.append((board, lid, json.loads(json.dumps(payload))))
        if self.respond != "upt":
            return {"success": False, "head": f"{lid}={self.respond}"}
        r = self.rows[lid]
        pred, _ = c.predict_readback(payload, r)
        pred["etime"] = "1792999999"
        if self.store_override:
            pred.update(self.store_override)
        self.rows[lid] = {k: pred[k] for k in r}
        return {"success": True, "head": f"{lid}=upt"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    rows = {f"level_{n}": srow(n) for n in (158, 159)}
    fs = FakeServer(rows)
    batch = {"levels": [{"meta": {"level_number": n, "predicted_clear_rate": META[n]}, "level_json": lj(n)} for n in (158, 159)]}
    bf = tmp_path / "batch.json"
    bf.write_text(json.dumps(batch))

    async def lbr(self, board):
        raw = fs.raw_board()
        import hashlib
        return {"raw": raw, "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw), "rows": {}, "keys": []}

    monkeypatch.setattr(B.GBoostClient, "load_board_rows", lbr)
    monkeypatch.setattr(B.GBoostClient, "update_existing_level", lambda self, b, i, p: fs.update(b, i, p))
    monkeypatch.setattr(B.GBoostClient, "save_thumbnail", lambda *a, **k: (_ for _ in ()).throw(AssertionError("thumbnail")),
                        raising=False)
    monkeypatch.setattr(base, "fetch_raw", fs.fetch_raw)
    monkeypatch.setattr(base, "resource_ok", lambda log: True)
    monkeypatch.setattr(base, "LOCK", tmp_path / ".lock")

    class A:
        pass
    a = A(); a.batch = "fx"; a.batch_file = str(bf); a.out_root = str(tmp_path)
    assert asyncio.run(B.cmd_prepare(a)) == 0
    d = next(tmp_path.glob("bulk_prepare_*"))
    msha = B.sha((d / "manifest.json").read_bytes())

    def run(apply=True, chunk=10, sha=None):
        q = A(); q.manifest = str(d / "manifest.json"); q.manifest_sha = sha or msha
        q.apply = apply; q.chunk = chunk; q.sleep = 0
        return asyncio.run(B.cmd_apply(q))
    return fs, d, run


def test_manifest_frozen_contents(env):
    fs, d, run = env
    m = json.loads((d / "manifest.json").read_text())
    assert [e["id"] for e in m["entries"]] == ["level_158", "level_159"]
    assert m["readbackRules"]["version"] == c.READBACK_RULES_VERSION and m["readbackRules"]["evidence"]
    assert all((d / e["backup"]).exists() for e in m["entries"])
    assert fs.posts == []                                      # 준비 단계 쓰기 0


def test_dry_run_no_network_and_sha_guard(env):
    fs, d, run = env
    assert run(apply=False) == 0 and fs.gets == 0 and fs.posts == []
    assert run(apply=True, sha="0" * 64) == 2 and fs.posts == []


def test_apply_chunk_resume_and_readback(env):
    fs, d, run = env
    assert run(chunk=1) == 0
    assert [p[1] for p in fs.posts] == ["level_158"]
    assert fs.posts[0][2] == json.loads((d / "manifest.json").read_text())["entries"][0]["payload"]
    assert fs.rows["level_158"]["ddaEasySeeds"] == E158 and fs.rows["level_158"]["rewardList"] is None
    assert run(chunk=10) == 0                                  # 재개: 158 skip, 159 만
    assert [p[1] for p in fs.posts] == ["level_158", "level_159"]
    assert run(chunk=10) == 0 and len(fs.posts) == 2           # 모두 완료 → 추가 쓰기 없음


def test_apply_race_stops_before_post(env):
    fs, d, run = env
    fs.mutate_on_read = lambda r: r.update(rewardCoin=9)
    assert run() == 6 and fs.posts == []


def test_apply_uncertain_response_stops_and_never_resends(env):
    fs, d, run = env
    fs.respond = "new"
    assert run() == 7 and len(fs.posts) == 1
    fs.respond = "upt"
    assert run() == 2 and len(fs.posts) == 1                   # 불확실 행 존재 → 재전송 금지


def test_apply_readback_mismatch_stops(env):
    fs, d, run = env
    fs.store_override = {"rewardList": [["null", 0, 0, 0]]}
    assert run() == 9 and len(fs.posts) == 1
    assert run() == 2 and len(fs.posts) == 1
