"""DDA v2_2 ±1 접두3 규칙(keep / planned_change / FAIL) 판정·준비·실행기 mock 검증. 외부 통신 없음(conftest 차단 + 가짜 서버)."""
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

from app.core import dda_seed_catalog as c  # noqa: E402
from app.core import dda_seed_catalog_v2 as c2  # noqa: E402
from app.core import dda_seed_catalog_v2_2 as c22  # noqa: E402
import dda_seed_bulk_20261020 as B  # noqa: E402
import dda_seed_bulk_v2_20261022 as B2  # noqa: E402
import dda_seed_bulk_v2_2_20261022 as B22  # noqa: E402
import dda_seed_server_apply_20261020 as base  # noqa: E402
from test_dda_seed_bulk import META, lj  # noqa: E402
from test_dda_seed_bulk_v2 import FakeServerV2, s2  # noqa: E402

SPEC = c22.load_spec()
CAT = c.load_catalog()["_byLevel"]
EXPECTED_PLANNED = ["L65.ddaEasySeeds", "L86.ddaEasySeeds", "L86.ddaHardSeeds", "L95.ddaEasySeeds", "L225.ddaEasySeeds",
                    "L234.ddaEasySeeds", "L278.ddaEasySeeds", "L278.ddaHardSeeds", "L325.ddaHardSeeds",
                    "L407.ddaEasySeeds", "L407.ddaHardSeeds", "L442.ddaHardSeeds", "L472.ddaEasySeeds",
                    "L472.ddaHardSeeds", "L521.ddaEasySeeds", "L521.ddaHardSeeds", "L851.ddaHardSeeds",
                    "L1195.ddaEasySeeds", "L1195.ddaHardSeeds"]


def c5(n, f="ddaEasySeeds"):
    return CAT[n][f].split(",")


def planned_spec(n=158, f="ddaEasySeeds", confirmed=None, holds=()):
    """L158 의 ±1 확정3 을 비접두로 바꾼 모의 spec(로더 결속 검사는 별도 테스트)."""
    sp = copy.deepcopy(SPEC)
    x = c5(n, f)
    conf = confirmed or ",".join([x[0], x[2], x[4]])
    sp["pm1Rule"][n][f] = c22.pm1_rule(conf, CAT[n][f])
    sp["_byLevel"][n]["fields"][f] = conf
    sp["holdLevels"] = sorted(set(sp["holdLevels"]) | set(holds))
    return sp


def cls(n, srv, spec=SPEC, mode=None):
    return B22.classify(f"level_{n}", n, lj(n), {"predicted_clear_rate": META.get(n, 0.5)}, srv, spec, mode)


# ── 규칙 ───────────────────────────────────────────────────────────────────

def test_pm1_rule_keep_planned_contained_partial_none():
    x = c5(158)
    assert c22.pm1_rule(",".join(x[:3]), CAT[158]["ddaEasySeeds"])["kind"] == "keep"
    r = c22.pm1_rule(",".join([x[0], x[2], x[4]]), CAT[158]["ddaEasySeeds"])
    assert (r["kind"], r["inServer5"], r["positionsIn5"], r["resolution"]) == ("planned_change", "all", [1, 3, 5], "reorder5_possible")
    assert r["proposals"] == {"write3": ",".join([x[0], x[2], x[4]]), "reorder5": ",".join([x[0], x[2], x[4], x[1], x[3]])}
    p = c22.pm1_rule(",".join([x[0], x[1], "999"]), CAT[158]["ddaEasySeeds"])
    assert (p["inServer5"], p["containedIn5"], p["proposals"]["reorder5"], p["resolution"]) == ("partial", 2, None, "write3_required")
    z = c22.pm1_rule("7,8,9", CAT[158]["ddaEasySeeds"])
    assert (z["inServer5"], z["resolution"]) == ("none", "write3_required")


def test_pm1_field_state_matrix():
    x = c5(158)
    keep = c22.pm1_rule(",".join(x[:3]), CAT[158]["ddaEasySeeds"])
    f = "ddaEasySeeds"
    assert c22.pm1_field_state(f, CAT[158][f], keep) == ("keep", CAT[158][f])
    assert c22.pm1_field_state(f, ",".join(x[:3]), keep) == ("keep", ",".join(x[:3]))
    assert c22.pm1_field_state(f, "", keep) == ("fill", CAT[158][f])
    assert c22.pm1_field_state(f, "1,2,3,4,5", keep)[0] == "conflict"
    pl = c22.pm1_rule(",".join([x[0], x[2], x[4]]), CAT[158][f])
    assert c22.pm1_field_state(f, CAT[158][f], pl) == ("planned_change", None)          # 서버 5 보존, 보내지 않음
    assert c22.pm1_field_state(f, "", pl) == ("planned_change_empty", None)              # catalog5 로 채우지 않음
    assert c22.pm1_field_state(f, None, pl) == ("planned_change_empty", None)
    assert c22.pm1_field_state(f, pl["confirmed3"], pl) == ("keep", pl["confirmed3"])    # 이미 해결
    assert c22.pm1_field_state(f, pl["proposals"]["reorder5"], pl) == ("keep", pl["proposals"]["reorder5"])
    assert c22.pm1_field_state(f, "1,2,3,4,5", pl)[0] == "conflict"
    assert c22.pm1_field_state(f, CAT[158][f], pl, "write3") == ("planned_write", pl["confirmed3"])
    assert c22.pm1_field_state(f, "", pl, "reorder5") == ("planned_write", pl["proposals"]["reorder5"])
    none = c22.pm1_rule("7,8,9", CAT[158][f])
    assert c22.pm1_field_state(f, CAT[158][f], none, "reorder5") == ("planned_unresolvable", None)


# ── 로더(결속) ─────────────────────────────────────────────────────────────

def test_load_spec_v2_2_planned_list_and_containment():
    assert SPEC["manifestSha256"].startswith("a803dc2e") and SPEC["levelsFile"] == "levels_spec_v2_2.json"
    assert SPEC["pm1Planned"] == sorted(EXPECTED_PLANNED, key=lambda s: (int(s[1:].split(".")[0]), s))
    rules = [r for v in SPEC["pm1Rule"].values() for r in v.values()]
    assert sum(r["kind"] == "keep" for r in rules) == len(rules) - 19
    assert all(r["inServer5"] == "all" for r in rules if r["kind"] == "planned_change")
    assert SPEC["pm1Rule"][65]["ddaEasySeeds"]["positionsIn5"] == [1, 3, 5]
    for n in (358, 541):                                                     # ±2 보류 필드 유지
        assert SPEC["_byLevel"][n]["fields"]["ddaHard2Seeds"] == ""


def test_manifest_and_sums_sha_mismatch():
    with pytest.raises(c.CatalogError, match="spec_manifest_sha_mismatch"):
        c22.load_spec(manifest_sha256="0" * 64)
    with pytest.raises(c.CatalogError, match="spec_sums_sha_mismatch"):
        c22.load_spec(sums_sha256="0" * 64)


def _tamper(tmp_path, edit_levels=None, edit_manifest=None):
    """spec 복사본을 고치고 SHA256SUMS·sha 를 다시 맞춘다 → 결속 검사만으로 걸리는지 확인."""
    src = Path(c22.SPEC_DIR_DEFAULT)
    d = tmp_path / "spec"
    d.mkdir(parents=True)
    lv = json.loads((src / "levels_spec_v2_2.json").read_bytes())
    man = json.loads((src / "manifest.json").read_bytes())
    if edit_levels:
        edit_levels({r["level"]: r for r in lv})
    if edit_manifest:
        edit_manifest(man)
    lb = json.dumps(lv).encode() if edit_levels else (src / "levels_spec_v2_2.json").read_bytes()
    mb = json.dumps(man).encode() if edit_manifest else (src / "manifest.json").read_bytes()
    (d / "levels_spec_v2_2.json").write_bytes(lb)
    (d / "manifest.json").write_bytes(mb)
    h = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    sb = f"{h(lb)}  levels_spec_v2_2.json\n{h(mb)}  manifest.json\n".encode()
    (d / "SHA256SUMS").write_bytes(sb)
    return dict(spec_dir=str(d), manifest_sha256=h(mb), sums_sha256=h(sb))


def test_tamper_copy_unchanged_loads(tmp_path):
    assert c22.load_spec(**_tamper(tmp_path))["pm1Planned"] == SPEC["pm1Planned"]


@pytest.mark.parametrize("edit,err", [
    # 다른 catalog 시드로 바꿔 끼움 → 해당 시드의 condSha(N−1 결속) 불일치
    (lambda L: L[65]["fields"].__setitem__("ddaEasySeeds", ",".join(c5(65)[:2] + [c5(65)[3]])), "spec_cond_sha_binding"),
    (lambda L: L[65]["useTileCount"].__setitem__("ddaEasySeeds", 9), "spec_use_tile_count_binding"),          # N+1 로 오결속
    (lambda L: L[65].__setitem__("sourceConditionHash", "0" * 64), "spec_level_binding_mismatch"),
    (lambda L: L[65]["fields"].__setitem__("ddaEasySeeds", "1,1,2"), "spec_seed_format"),
    (lambda L: L[65]["fields"].__setitem__("ddaEasySeeds", ""), "spec_empty_without_hold"),
    (lambda L: L[65]["condSha256"]["ddaHardSeeds"].__setitem__(0, L[65]["condSha256"]["ddaHard2Seeds"][0]), "spec_cond_sha_binding"),
])
def test_binding_failures(tmp_path, edit, err):
    with pytest.raises(c.CatalogError, match=err):
        c22.load_spec(**_tamper(tmp_path, edit_levels=edit))


def test_planned_list_must_match_manifest(tmp_path):
    with pytest.raises(c.CatalogError, match="spec_pm1_planned_list_mismatch"):
        c22.load_spec(**_tamper(tmp_path, edit_manifest=lambda m: m["pm1ServerPrefixMismatch"].pop()))
    with pytest.raises(c.CatalogError, match="spec_catalog_binding_mismatch"):
        c22.load_spec(**_tamper(tmp_path / "x", edit_manifest=lambda m: m["inputs"]["catalog"].__setitem__("sha256", "0")))


# ── classify ───────────────────────────────────────────────────────────────

def test_keep_level_matches_v2_payload():
    """비변경(keep) 레벨은 기존 v2 실행기와 payload·판정이 같다."""
    e = CAT[158]
    for srv in (s2(158), s2(158, ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"])):
        r = cls(158, srv)
        r2 = B2.classify("level_158", 158, lj(158), {"predicted_clear_rate": META[158]}, srv,
                         {**SPEC, "_byLevel": SPEC["_byLevel"]})
        assert (r["category"], r["reason"], r["fields"]) == (r2["category"], r2["reason"], r2["fields"])
        assert r["pm1Kind"] == {"ddaEasySeeds": "keep", "ddaHardSeeds": "keep"}
        p, p2 = dict(r["payload"]), dict(r2["payload"])
        p.pop("etime"); p2.pop("etime")
        assert p == p2


def test_planned_change_server5_preserved_not_sent():
    sp = planned_spec()
    e = CAT[158]
    r = cls(158, s2(158, ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"]), sp)
    assert r["category"] == "ready" and r["reason"] == "fill:ddaEasy2Seeds+ddaHard2Seeds"
    assert r["fields"]["ddaEasySeeds"] == "planned_change" and "ddaEasySeeds" not in r["payload"]
    assert r["expected"]["ddaEasySeeds"] == e["ddaEasySeeds"] and r["plannedChange"] == {}
    d = r["pm1Diff"][0]
    assert d["inServer5"] == "all" and d["proposalWrite3"] == sp["pm1Rule"][158]["ddaEasySeeds"]["confirmed3"]
    assert d["proposalReorder5"].split(",")[:3] == d["confirmed3"].split(",") and len(d["proposalReorder5"].split(",")) == 5


def test_planned_change_empty_server_not_filled():
    r = cls(158, s2(158), planned_spec())
    assert r["fields"]["ddaEasySeeds"] == "planned_change_empty" and "ddaEasySeeds" not in r["payload"]
    assert r["expected"]["ddaEasySeeds"] == "" and r["fields"]["ddaHardSeeds"] == "fill"


def test_planned_change_not_contained():
    sp = planned_spec(confirmed="7,8,9")
    r = cls(158, s2(158), sp)
    assert r["pm1Diff"][0]["inServer5"] == "none" and r["pm1Diff"][0]["resolution"] == "write3_required"
    assert r["pm1Diff"][0]["proposalReorder5"] is None
    assert cls(158, s2(158), sp, "reorder5")["reason"] == "planned_unresolvable:reorder5"
    w = cls(158, s2(158), sp, "write3")
    assert w["fields"]["ddaEasySeeds"] == "planned_write" and w["payload"]["ddaEasySeeds"] == "7,8,9"
    assert w["plannedChange"] == {"ddaEasySeeds": "write3"}


def test_hold_flag_excluded():
    r = cls(158, s2(158), planned_spec(holds=[158]))
    assert (r["category"], r["reason"]) == ("hold", "hold_flag") and "payload" not in r


def test_conflict_and_existing_holds_kept():
    assert cls(158, s2(158, ddaEasySeeds="1,2,3,4,5"), planned_spec())["reason"] == "server_seed_conflict"
    assert cls(158, srow_no_v2())["reason"] == "no_v2_column"
    assert cls(1466, s2(1466))["reason"] == "internal_map_mismatch"
    assert cls(322, s2(322))["category"] == "not_candidate"


def srow_no_v2():
    r = s2(158)
    for f in c2.PM2_FIELDS:
        r.pop(f)
    return r


# ── 실행기 ─────────────────────────────────────────────────────────────────

def _env(tmp_path, monkeypatch, sp, mode=None, server5=True):
    e = CAT[158]
    pm1 = dict(ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"]) if server5 else {}
    rows = {f"level_{n}": s2(n, **(pm1 if n == 158 else {})) for n in (158, 159)}
    fs = FakeServerV2(rows)
    batch = {"levels": [{"meta": {"level_number": n, "predicted_clear_rate": META[n]}, "level_json": lj(n)} for n in (158, 159)]}
    bf = tmp_path / "batch.json"
    bf.write_text(json.dumps(batch))
    snapf = tmp_path / "snap.raw.json"
    snapf.write_bytes(fs.raw_board())
    monkeypatch.setattr(c22, "load_spec", lambda *a, **k: sp)
    monkeypatch.setattr(B.GBoostClient, "load_board_rows", lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET")))
    monkeypatch.setattr(B.GBoostClient, "update_existing_level", lambda self, b, i, p: fs.update(b, i, p))
    monkeypatch.setattr(base, "fetch_raw", fs.fetch_raw)
    monkeypatch.setattr(base, "resource_ok", lambda log: True)

    class A:
        pass
    a = A(); a.batch = "fx"; a.batch_file = str(bf); a.out_root = str(tmp_path); a.snapshot = str(snapf)
    a.spec_dir = c22.SPEC_DIR_DEFAULT; a.spec_manifest_sha = c22.SPEC_MANIFEST_SHA256_DEFAULT
    a.spec_sums_sha = c22.SPEC_SUMS_SHA256_DEFAULT; a.hold_level = []; a.planned_change_mode = mode
    assert asyncio.run(B22.cmd_prepare(a)) == 0
    d = next(tmp_path.glob("bulk_prepare_v2_2_*"))
    msha = B.sha((d / "manifest.json").read_bytes())

    def run(apply=True, chunk=10, sha=None, runner=B22, allow=False):
        q = A(); q.manifest = str(d / "manifest.json"); q.manifest_sha = sha or msha
        q.apply = apply; q.chunk = chunk; q.sleep = 0; q.allow_planned_change = allow
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = asyncio.run(runner.cmd_apply(q))
        run.out = buf.getvalue()
        return rc
    return fs, d, run


def test_prepare_outputs_keep_and_planned_files_no_network(tmp_path, monkeypatch):
    fs, d, run = _env(tmp_path, monkeypatch, planned_spec())
    m = json.loads((d / "manifest.json").read_text())
    assert m["manifestVersion"] == "dda_seed_bulk_manifest.v2_2" and "entries" not in m and "entriesV2" not in m
    assert m["plannedChangeMode"] is None and all(not e["plannedChange"] for e in m["entriesV2_2"])
    e158 = m["entriesV2_2"][0]
    assert "ddaEasySeeds" not in e158["payload"] and e158["fields"]["ddaEasySeeds"] == "planned_change"
    plan = json.loads((d / "pm1_planned_change.json").read_text())
    keep = json.loads((d / "pm1_keep.json").read_text())
    assert [(x["level"], x["field"]) for x in plan] == [(158, "ddaEasySeeds")]
    assert {(x["level"], x["field"]) for x in keep} == {(158, "ddaHardSeeds"), (159, "ddaEasySeeds"), (159, "ddaHardSeeds")}
    assert (d / "pm1_planned_change.csv").read_text().startswith("level,")
    assert fs.posts == [] and fs.gets == 0
    assert run(apply=False) == 0 and fs.gets == 0 and fs.posts == []


def test_default_apply_preserves_server5(tmp_path, monkeypatch):
    fs, d, run = _env(tmp_path, monkeypatch, planned_spec())
    assert run(chunk=2) == 2 and "probe" in run.out and fs.posts == []
    assert run(chunk=1) == 0 and run(chunk=10) == 0
    assert "ddaEasySeeds" not in fs.posts[0][2]
    assert fs.rows["level_158"]["ddaEasySeeds"] == CAT[158]["ddaEasySeeds"]               # 5개 그대로
    assert len(fs.rows["level_158"]["ddaEasy2Seeds"].split(",")) == 3


def test_planned_write_blocked_without_flag_then_probe(tmp_path, monkeypatch):
    sp = planned_spec()
    fs, d, run = _env(tmp_path, monkeypatch, sp, mode="write3")
    m = json.loads((d / "manifest.json").read_text())
    assert m["plannedChangeMode"] == "write3" and m["entriesV2_2"][0]["plannedChange"] == {"ddaEasySeeds": "write3"}
    assert run(apply=False) == 0 and json.loads(run.out)["plannedChangeInChunk"] == ["level_158"]
    assert run(chunk=1) == 2 and "정책 미결" in run.out and fs.posts == [] and fs.gets == 0
    assert run(chunk=1, allow=True) == 0 and len(fs.posts) == 1
    assert fs.rows["level_158"]["ddaEasySeeds"] == sp["pm1Rule"][158]["ddaEasySeeds"]["confirmed3"]


def test_race_server_ne_backup_stops(tmp_path, monkeypatch):
    fs, d, run = _env(tmp_path, monkeypatch, planned_spec())
    fs.mutate_on_read = lambda r: r.update(ddaEasySeeds=",".join(c5(158)[::-1]))       # 누군가 5개를 재정렬
    assert run(chunk=1) == 6 and fs.posts == []
    fs.mutate_on_read = None
    fs.rows["level_158"]["ddaEasySeeds"] = CAT[158]["ddaEasySeeds"]
    fs.respond = "new"
    assert run(chunk=1) == 7 and len(fs.posts) == 1
    assert run(chunk=1) == 2 and len(fs.posts) == 1                                      # 불확실 → 재전송 금지


def test_apply_refuses_when_level_became_hold(tmp_path, monkeypatch):
    sp = planned_spec()
    fs, d, run = _env(tmp_path, monkeypatch, sp)
    sp["holdLevels"] = [158]
    assert run(chunk=1) == 2 and "hold" in run.out and fs.posts == [] and fs.gets == 0


def test_other_runners_refuse_v2_2_manifest(tmp_path, monkeypatch):
    fs, d, run = _env(tmp_path, monkeypatch, planned_spec())
    assert run(apply=False, runner=B2) == 2
    with pytest.raises(KeyError):
        run(apply=False, runner=B)
    assert fs.posts == [] and fs.gets == 0


def test_code_change_stops(tmp_path, monkeypatch):
    fs, d, run = _env(tmp_path, monkeypatch, planned_spec())
    m = json.loads((d / "manifest.json").read_text())
    assert "app/core/dda_seed_catalog_v2_2.py" in m["codeSha256"]
    m["codeSha256"]["app/core/dda_seed_catalog_v2_2.py"] = "0" * 64
    (d / "manifest.json").write_text(json.dumps(m))
    assert run(apply=False, sha=B.sha((d / "manifest.json").read_bytes())) == 2 and "코드 변경됨" in run.out


@pytest.mark.parametrize("dep", ["scripts/dda_seed_server_apply_20261020.py", "app/config.py"])
def test_dependency_module_change_stops_apply(tmp_path, monkeypatch, dep):
    """락·자원·fresh GET 모듈(및 서버 URL 설정)이 prepare 이후 바뀌면 apply 가 네트워크 전에 멈춘다."""
    fs, d, run = _env(tmp_path, monkeypatch, planned_spec())
    m = json.loads((d / "manifest.json").read_text())
    assert m["codeSha256"][dep] == B.sha((BACKEND / dep).read_bytes())
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes",                                   # 파일은 건드리지 않고 '바뀐 바이트'를 모의
                        lambda self: real(self) + b"\n# changed" if self == BACKEND / dep else real(self))
    assert run(chunk=1) == 2 and f"코드 변경됨 {dep}" in run.out and fs.posts == [] and fs.gets == 0
