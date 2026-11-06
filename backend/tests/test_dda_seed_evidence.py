"""DDA 시드 클리어 가능 판정 근거 게이트 (2026-11-02).

서버 값과 다른 새 시드는 level_json.ddaSeedVerdicts 에 PATH/PATH_BOT 근거(앞 3개 시드, map·useTileCount 결속)가
있어야 업로드된다. 근거가 없으면 그 열만 생략(서버 값 유지). 실서버 호출 없음(가짜 클라이언트).
"""
from __future__ import annotations

import copy
import json
import os

from fastapi.testclient import TestClient

from app.api.deps import get_gboost
from app.api.routes.gboost import _convert_to_townpop_format as conv
from app.core import dda_seed_catalog as c
from app.main import app

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "dda_seeds", "levels_fixture.json")
with open(FIX, encoding="utf-8") as _f:
    _FX = json.load(_f)


def lv(n: int, **kw) -> dict:
    j = copy.deepcopy(_FX["levels"][str(n)])
    j.update(kw)
    return j


def binding(j: dict) -> dict:
    tp = conv(dict(j))
    return {"mapSha256": c.map_sha256(tp), "useTileCount": tp["useTileCount"]}


def verdicts(j: dict, **cols) -> dict:
    ev = {"binding": binding(j)}
    for f, seeds in cols.items():
        ev[f] = [{"seed": s, "verdict": v, "nodes": 1, "source": "test"} for s, v in seeds]
    return ev


def test_seed_evidence_states():
    j = lv(40, ddaHardSeeds="11,12,13")
    tp = conv(dict(j))
    ok = verdicts(j, ddaHardSeeds=[(11, "PATH"), (12, "PATH_BOT"), (13, "PATH")])
    assert c.seed_evidence("ddaHardSeeds", "11,12,13", ok, tp) == "ok"
    part = verdicts(j, ddaHardSeeds=[(11, "PATH"), (12, "IMPOSSIBLE"), (13, "UNKNOWN")])
    assert c.seed_evidence("ddaHardSeeds", "11,12,13", part, tp) == "partial:1/3"
    assert c.seed_evidence("ddaHardSeeds", "11,12,13", None, tp) == "none"
    stale = copy.deepcopy(ok)
    stale["binding"]["mapSha256"] = "0" * 64
    assert c.seed_evidence("ddaHardSeeds", "11,12,13", stale, tp) == "binding_mismatch"
    stale2 = copy.deepcopy(ok)
    stale2["binding"]["useTileCount"] = "99"
    assert c.seed_evidence("ddaHardSeeds", "11,12,13", stale2, tp) == "binding_mismatch"
    # 옛 5개 값: 게임은 앞 3개만 쓴다 → 앞 3개 근거면 ok
    five = verdicts(j, ddaEasySeeds=[(1, "PATH"), (2, "PATH"), (3, "PATH_BOT")])
    assert c.seed_evidence("ddaEasySeeds", "1,2,3,4,5", five, tp) == "ok"


def test_export_fields_reports_evidence_and_key_not_sent():
    j = lv(40, ddaHardSeeds="11,12,13", ddaEasy2Seeds="21,22,23")
    j["ddaSeedVerdicts"] = verdicts(j, ddaHardSeeds=[(11, "PATH"), (12, "PATH"), (13, "PATH")])
    f = c.export_fields("levels", "level_40", j, conv(dict(j)))
    assert f["fieldEvidence"] == {"ddaEasy2Seeds": "none", "ddaHardSeeds": "ok"}
    assert "ddaSeedVerdicts" not in conv(dict(j))                         # 근거 키는 서버로 안 감


def test_evidence_gate_drops_only_unverified_new_values():
    srv = {"ddaEasySeeds": "1,2,3", "ddaHardSeeds": "4,5,6"}
    p = {"ddaEasySeeds": "1,2,3", "ddaHardSeeds": "7,8,9", "ddaEasy2Seeds": "10,11,12", "ddaHard2Seeds": "13,14,15"}
    ev = {"ddaEasySeeds": "none", "ddaHardSeeds": "none", "ddaEasy2Seeds": "ok", "ddaHard2Seeds": "partial:2/3"}
    dropped = c.evidence_gate(srv, p, ev)
    assert dropped == {"ddaHardSeeds": "none", "ddaHard2Seeds": "partial:2/3"}
    assert p == {"ddaEasySeeds": "1,2,3", "ddaEasy2Seeds": "10,11,12"}      # 같은 값·근거 있는 새 값만 남음
    p2 = {"ddaEasySeeds": "1,2,3"}
    assert c.evidence_gate(None, p2, {}) == {"ddaEasySeeds": "none"} and p2 == {}   # 새 행도 근거 필요


class _Fake:
    is_configured = True

    def __init__(self, existing):
        self.existing, self.saved = existing, []

    async def load_level(self, board_id, level_id, project_id_override="", strict=False):
        r = self.existing.get(level_id)
        return {"level_json": r, "metadata": {}} if r is not None else None

    async def save_level(self, board_id, level_id, level_json):
        self.saved.append((level_id, json.loads(json.dumps(level_json))))
        return {"success": True, "saved_at": "x", "message": "ok"}

    async def save_thumbnail(self, *a, **k):
        return {"success": True}


def test_save_route_sends_verified_and_same_drops_unverified():
    client = TestClient(app)
    j = lv(40, ddaEasySeeds="1,2,3", ddaHardSeeds="7,8,9", ddaEasy2Seeds="10,11,12")
    j["ddaSeedVerdicts"] = verdicts(j, ddaEasy2Seeds=[(10, "PATH"), (11, "PATH_BOT"), (12, "PATH")])
    fake = _Fake({"level_40": {"ddaEasySeeds": "1,2,3", "ddaHardSeeds": "4,5,6", "ddaEasy2Seeds": "", "ddaHard2Seeds": ""}})
    prev = app.dependency_overrides.get(get_gboost)
    app.dependency_overrides[get_gboost] = lambda: fake
    try:
        r = client.post("/api/gboost/levels/level_40", json={"level_json": j})
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_gboost, None)
        else:
            app.dependency_overrides[get_gboost] = prev
    assert r.status_code == 200 and "미검증 새 시드 미전송: ddaHardSeeds" in r.json()["message"]
    p = fake.saved[0][1]
    assert p.get("ddaEasySeeds") == "1,2,3"            # 서버와 같음 → 그대로
    assert p.get("ddaEasy2Seeds") == "10,11,12"        # 새 값 + 근거 → 보냄
    assert "ddaHardSeeds" not in p                     # 새 값 + 근거 없음 → 생략(서버 4,5,6 유지)
    assert "ddaSeedVerdicts" not in p
