"""DDA 시드 규격 v2 (3×4, 문서 48) 판정·준비·실행기 mock 검증. 외부 통신 없음(conftest 차단 + 가짜 서버)."""
from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.api.routes.gboost import _convert_to_townpop_format as conv  # noqa: E402
from app.core import dda_seed_catalog as c  # noqa: E402
from app.core import dda_seed_catalog_v2 as c2  # noqa: E402
import dda_seed_bulk_20261020 as B  # noqa: E402
import dda_seed_bulk_v2_20261022 as B2  # noqa: E402
import dda_seed_server_apply_20261020 as base  # noqa: E402
from test_dda_seed_bulk import META, FakeServer, lj, srow  # noqa: E402

SPEC = c2.load_spec()
CAT = c.load_catalog()["_byLevel"]
V2COLS = {"ddaEasy2Seeds": "", "ddaHard2Seeds": ""}


def s2(n, **over):
    """서버 행 + 신규 2컬럼(빈 값으로 추가된 상태)."""
    r = srow(n)
    r.update(V2COLS)
    r.update(over)
    return r


def cls(n, srv, spec=SPEC):
    return B2.classify(f"level_{n}", n, lj(n), {"predicted_clear_rate": META.get(n, 0.5)}, srv, spec)


def held_spec(n, field):
    sp = copy.deepcopy(SPEC)
    sp["_byLevel"][n]["fields"][field] = ""
    sp["_byLevel"][n]["status"] = "partial"
    sp["_byLevel"][n].setdefault("holds", {})[field] = "useTileCount>13sets"
    return sp


# ── 규칙: 해시 제외 4필드 · 개수 ──────────────────────────────────────────────

def test_condition_hash_excludes_map_and_four_seed_fields():
    assert c2.COND_HASH_EXCLUDE == ("map", "ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds", "ddaHard2Seeds")
    snap = c.load_source_rows()["rows"]["level_158"]
    assert c2.source_condition_hash(snap) == c.source_condition_hash(snap) == CAT[158]["sourceConditionHash"]
    row = {**snap, "map": {"x": 1}, "ddaEasySeeds": "1,2,3,4,5", "ddaHardSeeds": "", "ddaEasy2Seeds": "7,8,9", "ddaHard2Seeds": ""}
    assert c2.source_condition_hash(row) == CAT[158]["sourceConditionHash"]
    assert c.source_condition_hash(row) != CAT[158]["sourceConditionHash"]          # v1 은 신규 컬럼을 해시에 넣음


def test_all_candidates_v2_hash_equals_catalog():
    snap = c.load_source_rows()["rows"]
    assert all(c2.source_condition_hash(snap[f"level_{n}"]) == e["sourceConditionHash"]
               for n, e in CAT.items() if e["status"] == "candidate")


@pytest.mark.parametrize("v,counts,ok", [
    ("1,2,3", (3,), True), ("1,2,3,4,5", (3,), False), ("1,2,3,4,5", (5, 3), True), ("1,2", (5, 3), False),
    ("1, 2,3", (3,), False), ("01,2,3", (3,), False), ("1,2,2147483648", (3,), False), ("", (3,), False),
])
def test_seed_count_rules(v, counts, ok):
    assert c2.is_valid_seed_str(v, counts) is ok


def test_field_state_keep5_prefix3_fill_conflict_not_target():
    e, s = CAT[158], SPEC["_byLevel"][158]
    t = c2.field_targets(e, s)
    assert len(t["ddaEasySeeds"].split(",")) == 5 and len(t["ddaEasy2Seeds"].split(",")) == 3
    p3 = s["fields"]["ddaEasySeeds"]
    assert c2.field_state("ddaEasySeeds", e["ddaEasySeeds"], t["ddaEasySeeds"], p3) == ("keep", e["ddaEasySeeds"])
    assert c2.field_state("ddaEasySeeds", p3, t["ddaEasySeeds"], p3) == ("keep", p3)              # 3개로 줄이거나 늘리지 않음
    assert c2.field_state("ddaEasySeeds", "", t["ddaEasySeeds"], p3) == ("fill", e["ddaEasySeeds"])  # 빈 행 = catalog 5개
    assert c2.field_state("ddaEasySeeds", None, t["ddaEasySeeds"], p3)[0] == "fill"
    assert c2.field_state("ddaEasySeeds", "1,2,3,4,5", t["ddaEasySeeds"], p3)[0] == "conflict"
    t2 = s["fields"]["ddaHard2Seeds"]
    assert c2.field_state("ddaHard2Seeds", "", t2, t2) == ("fill", t2)
    assert c2.field_state("ddaHard2Seeds", "1,2,3", t2, t2)[0] == "conflict"
    assert c2.field_state("ddaHard2Seeds", "", None, "") == ("not_target", None)


def test_spec_v2_l358_l541_hard2_held_and_pinned_sha():
    for n in (358, 541):
        sp = SPEC["_byLevel"][n]
        assert sp["fields"]["ddaHard2Seeds"] == "" and sp["fields"]["ddaEasy2Seeds"] != ""
        assert c2.field_targets(CAT[n], sp)["ddaHard2Seeds"] is None
    assert SPEC["manifestSha256"].startswith("1a8b57da")
    with pytest.raises(c.CatalogError, match="spec_manifest_sha_mismatch"):
        c2.load_spec(manifest_sha256="0" * 64)
    with pytest.raises(c.CatalogError, match="spec_sums_sha_mismatch"):
        c2.load_spec(sums_sha256="0" * 64)


# ── 준비(classify) ─────────────────────────────────────────────────────────

def test_no_v2_column_holds():
    assert (cls(158, srow(158))["category"], cls(158, srow(158))["reason"]) == ("hold", "no_v2_column")


def test_ready_empty_row_payload_is_converter_plus_four_fields():
    r = cls(158, s2(158))
    assert r["category"] == "ready", r
    assert r["reason"] == "fill:ddaEasySeeds+ddaHardSeeds+ddaEasy2Seeds+ddaHard2Seeds" and r["condOk"] and r["mapOk"]
    expect = conv(copy.deepcopy(B.ui_upload_json(lj(158), {"predicted_clear_rate": META[158]}, 158)))
    sp = SPEC["_byLevel"][158]["fields"]
    expect.update(ddaEasySeeds=CAT[158]["ddaEasySeeds"], ddaHardSeeds=CAT[158]["ddaHardSeeds"],
                  ddaEasy2Seeds=sp["ddaEasy2Seeds"], ddaHard2Seeds=sp["ddaHard2Seeds"])
    p = dict(r["payload"]); p.pop("etime"); expect.pop("etime")
    assert p == expect
    assert [len(p[f].split(",")) for f in c2.SEED_FIELDS] == [5, 5, 3, 3]
    assert all(r["expected"][f] == p[f] for f in c2.SEED_FIELDS)


def test_ready_after_old_upload_keeps_five_and_fills_pm2_only():
    e = CAT[158]
    r = cls(158, s2(158, ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"]))
    assert (r["category"], r["reason"]) == ("ready", "fill:ddaEasy2Seeds+ddaHard2Seeds")
    assert r["fields"] == {"ddaEasySeeds": "keep", "ddaHardSeeds": "keep", "ddaEasy2Seeds": "fill", "ddaHard2Seeds": "fill"}
    assert (r["payload"]["ddaEasySeeds"], r["payload"]["ddaHardSeeds"]) == (e["ddaEasySeeds"], e["ddaHardSeeds"])  # 5개 보존


def test_server_three_prefix_is_kept_not_expanded():
    sp = SPEC["_byLevel"][158]["fields"]
    r = cls(158, s2(158, ddaEasySeeds=sp["ddaEasySeeds"], ddaHardSeeds=sp["ddaHardSeeds"]))
    assert r["category"] == "ready" and r["payload"]["ddaEasySeeds"] == sp["ddaEasySeeds"]


def test_held_pm2_field_omitted_from_payload_and_server_value_preserved():
    sp = held_spec(158, "ddaHard2Seeds")
    r = cls(158, s2(158), spec=sp)
    assert r["category"] == "ready" and "ddaHard2Seeds" not in r["payload"]
    assert r["fields"]["ddaHard2Seeds"] == "not_target" and r["notTarget"] == {"ddaHard2Seeds": "useTileCount>13sets"}
    assert r["expected"]["ddaHard2Seeds"] == ""                       # 보내지 않음 → 서버 기존 값 유지 예측
    r2 = cls(158, s2(158, ddaHard2Seeds="5,6,7"), spec=sp)            # 서버에 값이 있어도 건드리지 않음
    assert r2["category"] == "ready" and r2["expected"]["ddaHard2Seeds"] == "5,6,7"


def test_keep_conflict_and_unexpected_key():
    e, sp = CAT[158], SPEC["_byLevel"][158]["fields"]
    full = dict(ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"],
                ddaEasy2Seeds=sp["ddaEasy2Seeds"], ddaHard2Seeds=sp["ddaHard2Seeds"])
    assert (cls(158, s2(158, **full))["category"], cls(158, s2(158, **full))["reason"]) == ("keep", "server_seeds_equal_target")
    r = cls(158, s2(158, **{**full, "useInRandomizer": ""}))
    assert (r["category"], r["reason"]) == ("approval_needed", "keep_but_condition_mismatch:useInRandomizer")
    assert cls(158, s2(158, ddaEasy2Seeds="1,2,3"))["reason"] == "server_seed_conflict"
    assert cls(158, s2(158, ddaEasySeeds="1,2,3,4,5"))["reason"] == "server_seed_conflict"
    assert cls(158, s2(158, ddaEasy3Seeds=""))["reason"] == "unexpected_server_key"
    assert cls(322, s2(322))["category"] == "not_candidate"
    assert cls(1466, s2(1466))["reason"] == "internal_map_mismatch"


def test_v1_classify_unchanged_with_v2_columns_present():
    """구 실행기는 신규 컬럼을 보내지도 바꾸지도 않는다(기존 판정 유지)."""
    r = B.classify("level_158", 158, lj(158), {"predicted_clear_rate": META[158]}, s2(158))
    assert (r["category"], r["reason"]) == ("ready", "fill")
    assert not any(f in r["payload"] for f in c2.PM2_FIELDS) and r["expected"]["ddaEasy2Seeds"] == ""


# ── 실행기 ─────────────────────────────────────────────────────────────────

class FakeServerV2(FakeServer):
    async def update(self, board, lid, payload):
        self.posts.append((board, lid, json.loads(json.dumps(payload))))
        if self.respond != "upt":
            return {"success": False, "head": f"{lid}={self.respond}"}
        r = self.rows[lid]
        pred, _ = c2.predict_readback(payload, r)
        pred["etime"] = "1792999999"
        if self.store_override:
            pred.update(self.store_override)
        self.rows[lid] = {k: pred[k] for k in r}
        return {"success": True, "head": f"{lid}=upt"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    rows = {f"level_{n}": s2(n) for n in (158, 159)}
    fs = FakeServerV2(rows)
    batch = {"levels": [{"meta": {"level_number": n, "predicted_clear_rate": META[n]}, "level_json": lj(n)} for n in (158, 159)]}
    bf = tmp_path / "batch.json"
    bf.write_text(json.dumps(batch))
    raw = fs.raw_board()
    snapf = tmp_path / "snap.raw.json"
    snapf.write_bytes(raw)
    sp = held_spec(159, "ddaHard2Seeds")                                  # L358·L541 유형 모의
    monkeypatch.setattr(c2, "load_spec", lambda *a, **k: sp)
    monkeypatch.setattr(B.GBoostClient, "load_board_rows", lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET")))
    monkeypatch.setattr(B.GBoostClient, "update_existing_level", lambda self, b, i, p: fs.update(b, i, p))
    monkeypatch.setattr(base, "fetch_raw", fs.fetch_raw)
    monkeypatch.setattr(base, "resource_ok", lambda log: True)

    class A:
        pass
    a = A(); a.batch = "fx"; a.batch_file = str(bf); a.out_root = str(tmp_path); a.snapshot = str(snapf)
    a.spec_dir = c2.SPEC_DIR_DEFAULT; a.spec_manifest_sha = c2.SPEC_MANIFEST_SHA256_DEFAULT
    a.spec_sums_sha = c2.SPEC_SUMS_SHA256_DEFAULT
    assert asyncio.run(B2.cmd_prepare(a)) == 0
    d = next(tmp_path.glob("bulk_prepare_v2_*"))
    msha = B.sha((d / "manifest.json").read_bytes())

    def run(apply=True, chunk=10, sha=None, runner=B2):
        q = A(); q.manifest = str(d / "manifest.json"); q.manifest_sha = sha or msha
        q.apply = apply; q.chunk = chunk; q.sleep = 0
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = asyncio.run(runner.cmd_apply(q))
        run.out = buf.getvalue()
        return rc
    return fs, d, run


def test_manifest_v2_frozen(env):
    fs, d, run = env
    m = json.loads((d / "manifest.json").read_text())
    assert m["manifestVersion"] == "dda_seed_bulk_manifest.v2" and "entries" not in m
    assert [e["id"] for e in m["entriesV2"]] == ["level_158", "level_159"]
    assert m["specV2"]["manifestSha256"] == c2.SPEC_MANIFEST_SHA256_DEFAULT
    assert m["readbackRules"]["version"] == "dda_readback_rules.v2" and m["readbackRules"]["probeRequired"]
    assert m["conditionHashExclude"] == list(c2.COND_HASH_EXCLUDE)
    e159 = m["entriesV2"][1]
    assert "ddaHard2Seeds" not in e159["payload"] and e159["sentSeedFields"] == ["ddaEasy2Seeds", "ddaEasySeeds", "ddaHardSeeds"]
    assert fs.posts == [] and fs.gets == 0


def test_dry_run_no_network_and_guards(env):
    fs, d, run = env
    assert run(apply=False) == 0 and fs.gets == 0 and fs.posts == []
    out = json.loads(run.out)
    assert out["probeRequired"] and out["nextChunk"][1]["notTarget"] == {"ddaHard2Seeds": "useTileCount>13sets"}
    assert run(apply=True, sha="0" * 64) == 2 and fs.posts == []
    assert run(apply=True, chunk=2) == 2 and "probe" in run.out and fs.posts == []          # 첫 실행 청크 금지
    with pytest.raises(KeyError):                                                            # 구 실행기 + v2 manifest
        run(apply=True, runner=B)
    assert fs.gets == 0 and fs.posts == []


def test_apply_probe_then_chunk_and_held_field_preserved(env):
    fs, d, run = env
    fs.rows["level_159"]["ddaHard2Seeds"] = ""
    assert run(chunk=1) == 0 and [p[1] for p in fs.posts] == ["level_158"]
    r158 = fs.rows["level_158"]
    assert [len(r158[f].split(",")) for f in c2.SEED_FIELDS] == [5, 5, 3, 3]
    assert json.loads((d / "results.jsonl").read_text().splitlines()[-1])["probe"] is True
    assert run(chunk=10) == 0 and [p[1] for p in fs.posts] == ["level_158", "level_159"]
    assert "ddaHard2Seeds" not in fs.posts[1][2] and fs.rows["level_159"]["ddaHard2Seeds"] == ""
    assert run(chunk=10) == 0 and len(fs.posts) == 2


def test_apply_pm2_readback_mismatch_stops(env):
    fs, d, run = env
    fs.store_override = {"ddaEasy2Seeds": None}                          # 서버가 신규 컬럼을 다르게 저장
    assert run(chunk=1) == 9 and len(fs.posts) == 1
    assert run(chunk=1) == 2 and len(fs.posts) == 1                      # 불확실/불일치 행 → 재전송 금지


def test_apply_race_and_uncertain(env):
    fs, d, run = env
    fs.mutate_on_read = lambda r: r.update(ddaEasy2Seeds="1,2,3")
    assert run(chunk=1) == 6 and fs.posts == []
    fs.mutate_on_read = None
    fs.rows["level_158"]["ddaEasy2Seeds"] = ""
    fs.respond = "new"
    assert run(chunk=1) == 7 and len(fs.posts) == 1


def test_v2_runner_refuses_v1_manifest(tmp_path):
    old = BACKEND / "data" / "dda_seeds" / "bulk_prepare_20261022_1054" / "manifest.json"
    q = type("A", (), {})(); q.manifest = str(old); q.manifest_sha = hashlib.sha256(old.read_bytes()).hexdigest()
    q.apply = False; q.chunk = 1; q.sleep = 0
    assert asyncio.run(B2.cmd_apply(q)) == 2


# ── 구규격 manifest 회귀 (저장 파일 읽기만, 네트워크·쓰기 없음) ─────────────────────

@pytest.mark.parametrize("name,prefix", [("bulk_prepare_20261020_1906", "fbd24f9f"), ("bulk_prepare_20261022_1054", "310d2105")])
def test_old_manifest_dry_run_still_works(name, prefix, monkeypatch):
    p = BACKEND / "data" / "dda_seeds" / name / "manifest.json"
    msha = hashlib.sha256(p.read_bytes()).hexdigest()
    assert msha.startswith(prefix)
    q = type("A", (), {})(); q.manifest = str(p); q.manifest_sha = msha; q.apply = False; q.chunk = 10; q.sleep = 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = asyncio.run(B.cmd_apply(q))
    assert rc == 0 and "코드 변경됨" not in buf.getvalue()
    out = json.loads(buf.getvalue())
    assert out["dryRun"] and len(out["nextChunk"]) == 10
