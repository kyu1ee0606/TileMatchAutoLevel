#!/usr/bin/env python3
"""DDA 시드 일괄 업로드 v2_2 — ±1 접두3 규칙 정리(keep / planned_change / FAIL) 준비·실행기.

기존 v2 실행기(dda_seed_bulk_v2_20261022.py)·v2 모듈은 기존 v2 manifest 가 codeSha256 로 고정하므로 수정하지 않고,
이 파일 + app/core/dda_seed_catalog_v2_2.py 로 분리한다. 구규격(v1) 실행기·manifest 도 그대로.

  prepare --batch <id> --spec-dir <dir> --spec-manifest-sha <sha> --spec-sums-sha <sha> [--snapshot <raw.json>]
          [--hold-level N ...] [--planned-change-mode write3|reorder5]
      서버 GET 1회(또는 저장 snapshot → 네트워크 0) → 레벨별 판정 → manifest v2_2 + ±1 keep/planned_change diff 파일.
      · ±1 keep: 서버 값 그대로(빈 값이면 catalog 5개 채움 — 기존 v2 규칙).
      · ±1 planned_change: 기본은 보내지 않음(서버 5개 보존, 빈 값도 채우지 않음). 제안값(write3/reorder5)은 diff 에만.
        --planned-change-mode 를 주면 제안값을 payload 에 넣고 entry 에 plannedChange 표시(정책 미결 — 실행 시 별도 플래그 필요).
      · hold 레벨(--hold-level, spec manifest holdLevels, 레벨 hold 플래그)은 쓰기 대상에서 제외.
  apply --manifest <path> --manifest-sha <sha> [--chunk N] [--apply] [--allow-planned-change]
      기본 dry-run(네트워크 없음). 안전장치는 v2 와 같음: 코드 sha·spec 재검사, fresh GET = 예상 백업(경합 시 중단),
      update-only 1회, readback = 예상, 청크≤10, 락, 자원 중지, 불확실 응답 재전송 금지, 첫 실행 1행 probe.
      plannedChange entry 는 --allow-planned-change 없으면 차단, 있어도 그 첫 쓰기는 별도 1행 probe.
manifest 키는 'entriesV2_2' — 구 실행기(v1: entries KeyError, v2: 버전 불일치)로는 돌지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import datetime as dt
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
from app.core import dda_seed_catalog as c  # noqa: E402
from app.core import dda_seed_catalog_v2 as c2  # noqa: E402
from app.core import dda_seed_catalog_v2_2 as c22  # noqa: E402
import dda_seed_bulk_20261020 as B  # noqa: E402  (conv, ui_upload_json, dump, sha, now, GBoostClient 재사용)
import dda_seed_server_apply_20261020 as base  # noqa: E402  (fetch_raw, Lock, resource_ok, write_sums)

BOARD = c.DDA_BOARD_ID
MANIFEST_VERSION = "dda_seed_bulk_manifest.v2_2"
MAX_CHUNK = B.MAX_CHUNK
dump, sha, now, conv = B.dump, B.sha, B.now, B.conv
CODE_FILES = ("app/core/dda_seed_catalog.py", "app/core/dda_seed_catalog_v2.py", "app/core/dda_seed_catalog_v2_2.py",
              "app/api/routes/gboost.py", "app/clients/gboost.py", "app/config.py",
              "scripts/dda_seed_bulk_20261020.py", "scripts/dda_seed_server_apply_20261020.py",
              "scripts/dda_seed_bulk_v2_2_20261022.py")
# 고정 범위: 실행 경로에서 쓰는 로컬 모듈(변환기·클라이언트·서버 URL 설정·락/자원/fresh GET/write_sums 모듈).
# routes/gboost.py 가 import 만 하는 models/schemas.py·api/deps.py(→ analyzer/generator/simulator)는 이 경로에서 쓰지 않아 제외.
PLANNED_STATES = ("planned_change", "planned_change_empty", "planned_write", "planned_unresolvable")


def _pm1_diff(level: int, f: str, rule: dict, sv, state: str) -> dict:
    d = {"level": level, "field": f, "serverValue": sv, "serverCount": len(sv.split(",")) if sv else 0,
         "catalog5": rule["catalog5"], "confirmed3": rule["confirmed3"], "state": state}
    if rule["kind"] == "planned_change":
        d.update(positionsIn5=rule["positionsIn5"], containedIn5=rule["containedIn5"], inServer5=rule["inServer5"],
                 resolution=rule["resolution"], proposalWrite3=rule["proposals"]["write3"],
                 proposalReorder5=rule["proposals"]["reorder5"])
    return d


def classify(lid: str, level: int, lj: dict, meta: dict, srv: dict | None, spec: dict, mode: str | None = None) -> dict:
    e = c.load_catalog()["_byLevel"].get(level)
    out = {"id": lid, "level": level}
    if e is None or e["status"] != "candidate":
        out.update(category="not_candidate", reason=(e or {}).get("status", "no_data")); return out
    s = spec["_byLevel"].get(level)
    if s is None or s.get("status") not in ("ready4", "partial"):
        out.update(category="hold", reason="spec_not_target"); return out
    rules = spec["pm1Rule"][level]
    out["pm1Kind"] = {f: rules[f]["kind"] for f in c2.PM1_FIELDS}
    if level in spec.get("holdLevels", ()):
        out.update(category="hold", reason="hold_flag"); return out
    if srv is None:
        out.update(category="hold", reason="no_server_row"); return out
    if any(f not in srv for f in c2.PM1_FIELDS):
        out.update(category="hold", reason="no_seed_column"); return out
    snap = c.load_source_rows()["rows"][lid]
    extra = [k for k in srv if k not in snap and k not in c2.SERVER_ONLY_KEYS]
    if extra:
        out.update(category="hold", reason="unexpected_server_key", detail=",".join(extra)); return out
    out["pm1Diff"] = [_pm1_diff(level, f, rules[f], srv.get(f) or "", "not_evaluated") for f in c2.PM1_FIELDS]
    if any(f not in srv for f in c2.PM2_FIELDS):
        out.update(category="hold", reason="no_v2_column"); return out
    states, send = {}, {}
    for i, f in enumerate(c2.PM1_FIELDS):
        st, val = c22.pm1_field_state(f, srv.get(f), rules[f], mode)
        states[f] = st
        out["pm1Diff"][i]["state"] = st
        if val is not None:
            send[f] = val
    for f in c2.PM2_FIELDS:
        target = s["fields"][f] or None
        st, val = c2.field_state(f, srv.get(f), target, s["fields"][f])
        states[f] = st
        if val is not None:
            send[f] = val
    out["fields"] = states
    out["notTarget"] = {f: s.get("holds", {}).get(f, "") for f, st in states.items() if st == "not_target"}
    out["plannedChange"] = {f: mode for f, st in states.items() if st == "planned_write"}
    if "conflict" in states.values():
        out.update(category="hold", reason="server_seed_conflict",
                   detail=str({f: srv.get(f) for f, st in states.items() if st == "conflict"})[:160]); return out
    if "planned_unresolvable" in states.values():
        out.update(category="hold", reason=f"planned_unresolvable:{mode}"); return out
    if not ({"fill", "planned_write"} & set(states.values())):
        diff = [k for k in snap if dump(srv.get(k)) != dump(snap[k])]
        if diff:
            out.update(category="approval_needed", reason="keep_but_condition_mismatch:" + ",".join(diff)); return out
        out.update(category="keep", reason="server_seeds_equal_target"); return out
    up = B.ui_upload_json(lj, meta, level)
    if up is None:
        out.update(category="hold", reason="predicted_missing(UI 는 RL 측정)"); return out
    tp = conv(copy.deepcopy(up))
    g = c._seed_values(level, lj, tp)                                      # 내부 시드·map·N 게이트(v1 과 같음)
    if g["reason"] != "valid":
        out.update(category="hold", reason=f"internal_{g['reason']}"); return out
    payload = {k: v for k, v in tp.items() if k not in c2.SEED_FIELDS}     # 시드 필드는 판정값만(보류·planned 는 제외)
    payload.update(send)
    pred, unverified = c2.predict_readback(payload, srv)
    if unverified:
        out.update(category="hold", reason="unverified_serialization", detail=",".join(unverified)); return out
    raw_diffs = {k for k in payload if k != "etime" and dump(payload.get(k)) != dump(srv.get(k))}
    meaning = {k: [srv.get(k), pred.get(k)] for k in srv
               if k not in c2.SEED_FIELDS and k != "etime" and dump(pred.get(k)) != dump(srv.get(k))}
    core = {k: pred.get(k) for k in snap}
    cond_ok = c2.source_condition_hash(core) == e["sourceConditionHash"] and dump(core) == dump(snap)
    map_ok = sha(dump(srv.get("map"))) == e["sourceMapSha256"] and dump(payload["map"]) == dump(srv.get("map"))
    out.update(rawDiffCount=len(raw_diffs), meaningDiffs=meaning, condOk=cond_ok, mapOk=map_ok,
               sentSeedFields=sorted(send))
    if not map_ok:
        out.update(category="hold", reason="map_mismatch"); return out
    if meaning:
        only_checkbox = set(meaning) <= {"useInRandomizer", "useTeleportInRandomizer"} and \
            all(v[0] == "" and v[1] == 0 for v in meaning.values())
        out.update(category="approval_needed" if only_checkbox else "hold",
                   reason=("checkbox_restore(\"\"→0)" if only_checkbox else "meaning_change:" + ",".join(sorted(meaning))))
        if only_checkbox:
            out.update(payload=payload, expected=pred, before=srv)
        return out
    if not cond_ok:
        out.update(category="hold", reason="condition_hash_mismatch"); return out
    out.update(category="ready",
               reason="fill:" + "+".join(f for f in c2.SEED_FIELDS if states[f] in ("fill", "planned_write")),
               payload=payload, expected=pred, before=srv)
    return out


def _spec_args(a) -> dict:
    return {"spec_dir": a.spec_dir, "manifest_sha256": a.spec_manifest_sha, "sums_sha256": a.spec_sums_sha,
            "hold_levels": getattr(a, "hold_level", None) or ()}


def _write_csv(path: Path, rows: list):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols or ["level"])
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    path.write_text(buf.getvalue())


async def cmd_prepare(a):
    stamp = dt.datetime.now(B.KST).strftime("%Y%m%d_%H%M%S")
    outd = Path(getattr(a, "out_root", None) or (BACKEND / "data" / "dda_seeds")) / f"bulk_prepare_v2_2_{stamp}"
    (outd / "rows").mkdir(parents=True, exist_ok=False)
    logf = (outd / "run.log").open("a")

    def log(m):
        line = f"[{now()}] {m}"; print(line, flush=True); logf.write(line + "\n"); logf.flush()
    if not base.resource_ok(log):
        log("STOP: resource"); return 3
    mode = getattr(a, "planned_change_mode", None)
    spec = c22.load_spec(**_spec_args(a))
    log(f"spec {spec['id']} manifest={spec['manifestSha256']} sums={spec['sumsSha256']} levels={spec['levelsFile']} "
        f"pm1Planned={len(spec['pm1Planned'])} holdLevels={spec['holdLevels']} plannedMode={mode}")
    bpath = Path(getattr(a, "batch_file", None) or (BACKEND / "data" / "production" / f"{a.batch}.json"))
    braw = bpath.read_bytes()
    batch = json.loads(braw)
    if getattr(a, "snapshot", None):                                        # 저장 snapshot 재사용(서버 요청 없음)
        raw = Path(a.snapshot).read_bytes()
        board = {"raw": raw, "raw_sha256": sha(raw), "raw_bytes": len(raw)}
        log(f"snapshot 재사용 {a.snapshot}")
    else:
        board = await B.GBoostClient().load_board_rows(BOARD)              # 서버 읽기 1회
    (outd / "server_levels_snapshot.raw.json").write_bytes(board["raw"])
    data = json.loads(board["raw"].decode())
    ks = data["__keys"]
    if any(not v or len(v) != len(ks) for v in data["__vals"]):
        log("STOP: 부분 응답(열 개수 불일치)"); return 4
    rows = {v[ks.index("id")]: dict(zip(ks, v)) for v in data["__vals"]}
    if len(rows) != len(data["__vals"]):
        log("STOP: 중복 id"); return 4
    log(f"server rows={len(rows)} keys={len(ks)} sha256={board['raw_sha256']} v2Columns={[f for f in c2.PM2_FIELDS if f in ks]}")
    plans = []
    for l in sorted(batch["levels"], key=lambda x: x["meta"]["level_number"]):
        if not l.get("level_json"):
            continue
        n = l["meta"]["level_number"]
        lid = f"level_{n}"
        plans.append(classify(lid, n, l["level_json"], l["meta"], rows.get(lid), spec, mode))
    ready = [p for p in plans if p["category"] == "ready"]
    for p in plans:
        if p["category"] in ("ready", "approval_needed") and "before" in p:
            (outd / "rows" / f"{p['id']}.before.json").write_bytes(dump({"keys": ks, "row": p["before"]}))
    entries = [{"id": p["id"], "level": p["level"], "payload": p["payload"], "payloadSha256": sha(dump(p["payload"])),
                "beforeRowSha256": sha(dump(p["before"])), "expected": {k: v for k, v in p["expected"].items() if k != "etime"},
                "fields": p["fields"], "sentSeedFields": p["sentSeedFields"], "notTarget": p["notTarget"],
                "plannedChange": p["plannedChange"], "backup": f"rows/{p['id']}.before.json"} for p in ready]
    manifest = {
        "manifestVersion": MANIFEST_VERSION, "createdAt": now(), "board": BOARD,
        "serverSnapshotSha256": board["raw_sha256"], "serverSnapshotBytes": board["raw_bytes"],
        "serverKeys": ks, "batch": a.batch, "batchSha256": sha(braw),
        "catalogSha256": c.CATALOG_SHA256, "rowsSha256": c.ROWS_SHA256,
        "specV2": {"id": spec["id"], "dir": str(Path(spec["dir"]).resolve().relative_to(BACKEND)),
                   "manifestSha256": spec["manifestSha256"], "sumsSha256": spec["sumsSha256"],
                   "levelsFile": spec["levelsFile"], "levelsSha256": spec["levelsSha256"],
                   "levelsCsvSha256": spec["levelsCsvSha256"], "holdLevels": spec["holdLevels"],
                   "pm1Planned": spec["pm1Planned"]},
        "plannedChangeMode": mode,
        "seedPolicy": {"ddaEasySeeds,ddaHardSeeds(keep)": "확정3 = catalog5 앞 3 → 서버 값 그대로 재전송; 빈 값 → catalog5 (문서 48 §7-3)",
                       "ddaEasySeeds,ddaHardSeeds(planned_change)": "확정3 ≠ 앞 3 → 보내지 않음(서버 5개 보존, 빈 값도 채우지 않음). "
                       "제안 write3(5→3)·reorder5(확정3 앞으로, 나머지 순서 보존)는 pm1_planned_change.* 에만. 적용 정책 미결",
                       "ddaEasy2Seeds,ddaHard2Seeds": "산출물 3개; 산출물 보류 필드는 payload 제외(서버 기존 값 유지)",
                       "hold": "holdLevels 는 쓰기 대상 제외",
                       "allowedCounts": c2.ALLOWED_COUNTS},
        "conditionHashExclude": list(c2.COND_HASH_EXCLUDE), "serverOnlyKeys": list(c2.SERVER_ONLY_KEYS),
        "readbackRules": {"version": c2.READBACK_RULES_VERSION, "rules": c2.READBACK_RULES,
                          "unverified": list(c2.READBACK_UNVERIFIED), "probeRequired": True,
                          "evidence": B.EVIDENCE_L159},
        "uiInputs": {"rewardCoin": B.UI_REWARD_COIN_FIXED, "autoCollect": f"slot%10==0 -> {B.UI_AUTOCOLLECT_VALUE} else 0",
                     "predicted_clear_rate": "meta"},
        "codeSha256": {f: sha((BACKEND / f).read_bytes()) for f in CODE_FILES},
        "entriesV2_2": entries,
    }
    mbytes = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
    (outd / "manifest.json").write_bytes(mbytes)
    diffs = [d for p in plans for d in p.get("pm1Diff", [])]
    for d in diffs:
        d["levelCategory"] = next(f"{p['category']}:{p['reason']}" for p in plans if p["level"] == d["level"])
    keep_d = [d for d in diffs if "proposalWrite3" not in d]
    plan_d = [d for d in diffs if "proposalWrite3" in d]
    (outd / "pm1_keep.json").write_text(json.dumps(keep_d, ensure_ascii=False, indent=0))
    (outd / "pm1_planned_change.json").write_text(json.dumps(plan_d, ensure_ascii=False, indent=1))
    _write_csv(outd / "pm1_keep.csv", keep_d)
    _write_csv(outd / "pm1_planned_change.csv", plan_d)
    hold_like = [p for p in plans if p["category"] in ("hold", "approval_needed")]
    summary = {"time": now(), "manifestSha256": sha(mbytes), "ready": len(ready),
               "byCategory": dict(Counter(p["category"] for p in plans)),
               "byReason": dict(Counter(f"{p['category']}:{p['reason']}" for p in plans)),
               "fieldStates": {f: dict(Counter(p["fields"][f] for p in plans if "fields" in p)) for f in c2.SEED_FIELDS},
               "pm1": {"specKeepFields": sum(r["kind"] == "keep" for v in spec["pm1Rule"].values() for r in v.values()),
                       "specPlannedFields": len(spec["pm1Planned"]),
                       "plannedInServer5": dict(Counter(d["inServer5"] for d in plan_d)),
                       "plannedResolution": dict(Counter(d["resolution"] for d in plan_d)),
                       "plannedStates": dict(Counter(d["state"] for d in plan_d)),
                       "keepStates": dict(Counter(d["state"] for d in keep_d)),
                       "plannedEntriesWithWrite": [e["id"] for e in entries if e["plannedChange"]]},
               "notTargetLevels": {p["id"]: p["notTarget"] for p in plans if p.get("notTarget")},
               "approvalNeeded": [p["id"] for p in plans if p["category"] == "approval_needed"],
               "keep": [p["id"] for p in plans if p["category"] == "keep"],
               "holdLevels": {r: [p["level"] for p in hold_like if f"{p['category']}:{p['reason']}" == r]
                              for r in {f"{p['category']}:{p['reason']}" for p in hold_like}}}
    (outd / "plan.json").write_bytes(dump([{k: v for k, v in p.items() if k not in ("payload", "expected", "before")} for p in plans]))
    (outd / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    base.write_sums(outd)
    log(f"manifest {outd/'manifest.json'} sha256={summary['manifestSha256']} ready={len(ready)}")
    log(f"byReason {json.dumps(summary['byReason'], ensure_ascii=False)}")
    log(f"pm1 {json.dumps(summary['pm1'], ensure_ascii=False)}")
    return 0


async def cmd_apply(a):
    mpath = Path(a.manifest)
    mbytes = mpath.read_bytes()
    if sha(mbytes) != a.manifest_sha:
        print(f"STOP: manifest sha 불일치 {sha(mbytes)}"); return 2
    m = json.loads(mbytes)
    if m.get("manifestVersion") != MANIFEST_VERSION:
        print(f"STOP: manifest 버전 {m.get('manifestVersion')} — v2_2 실행기는 {MANIFEST_VERSION} 만"); return 2
    outd = mpath.parent
    for f, h in m["codeSha256"].items():
        if sha((BACKEND / f).read_bytes()) != h:
            print(f"STOP: 코드 변경됨 {f} — manifest 재생성 필요"); return 2
    sp = m["specV2"]
    try:
        spec = c22.load_spec(str(BACKEND / sp["dir"]), sp["manifestSha256"], sp["sumsSha256"],
                             levels_file=sp["levelsFile"], hold_levels=sp["holdLevels"])
    except c.CatalogError as ex:
        print(f"STOP: v2_2 산출물 검사 실패 {ex}"); return 2
    if spec["levelsSha256"] != sp["levelsSha256"] or spec["pm1Planned"] != sp["pm1Planned"]:
        print("STOP: v2_2 산출물 레벨 파일 변경"); return 2
    entries = m["entriesV2_2"]
    held = [e["id"] for e in entries if e["level"] in spec["holdLevels"]]
    if held:
        print(f"STOP: hold 레벨이 쓰기 대상에 있음 {held}"); return 2
    res_p = outd / "results.jsonl"
    done = {}
    if res_p.exists():
        for line in res_p.read_text().splitlines():
            r = json.loads(line); done[r["id"]] = r
    uncertain = [i for i, r in done.items() if r["status"] not in ("ok",)]
    if uncertain:
        print(f"STOP: 이전 실행의 미완료/불확실 행 {uncertain} — 재조회 판정 필요, 재전송 금지"); return 2
    probe = m["readbackRules"].get("probeRequired") and not done
    chunk = min(a.chunk, MAX_CHUNK)
    todo = [e for e in entries if e["id"] not in done][:chunk]
    planned = [e["id"] for e in todo if e.get("plannedChange")]
    planned_probe = bool(planned) and not any(r.get("plannedChange") for r in done.values())
    if not a.apply:
        print(json.dumps({"dryRun": True, "manifestVersion": m["manifestVersion"], "remaining": len(entries) - len(done),
                          "probeRequired": bool(probe), "plannedChangeMode": m.get("plannedChangeMode"),
                          "plannedChangeInChunk": planned,
                          "nextChunk": [{"id": e["id"], "fields": e["fields"], "sent": {f: e["payload"][f] for f in e["sentSeedFields"]},
                                         "notTarget": e["notTarget"], "plannedChange": e.get("plannedChange", {})}
                                        for e in todo]}, ensure_ascii=False))
        return 0
    if planned and not getattr(a, "allow_planned_change", False):
        print(f"STOP: planned_change(±1 5→3/재정렬) 적용은 정책 미결 — --allow-planned-change 없이 차단 {planned}"); return 2
    if probe and a.chunk != 1:
        print("STOP: 신규 2필드 readback 미실측 — 첫 실행은 --chunk 1 (probe) 만 허용"); return 2
    if planned_probe and a.chunk != 1:
        print("STOP: planned_change 첫 쓰기는 --chunk 1 (probe) 만 허용"); return 2
    logf = (outd / "apply.log").open("a")

    def log(msg):
        line = f"[{now()}] {msg}"; print(line, flush=True); logf.write(line + "\n"); logf.flush()
    cli = B.GBoostClient()
    rf = res_p.open("a")
    t_res = 0.0
    for e in todo:
        if time.time() - t_res > 50:
            if not base.resource_ok(log):
                log("STOP: resource"); return 3
            t_res = time.time()
        if sha(dump(e["payload"])) != e["payloadSha256"]:
            log(f"STOP: {e['id']} payload sha 불일치"); return 4
        await asyncio.sleep(a.sleep)
        try:
            _, ks0, v0 = await base.fetch_raw(cli, e["id"])
        except Exception as ex:
            log(f"STOP: {e['id']} fresh GET 실패 {ex}"); return 5
        before = dict(zip(ks0, v0))
        if sha(dump(before)) != e["beforeRowSha256"]:
            log(f"STOP: {e['id']} snapshot 이후 서버 행 변경(경합) — 쓰기 안 함"); return 6
        rf.write(json.dumps({"id": e["id"], "time": now(), "status": "posting"}) + "\n"); rf.flush()
        r = await cli.update_existing_level(BOARD, e["id"], e["payload"])     # new=0 1회, 생성·재시도·썸네일 없음
        if not r.get("success"):
            rf.write(json.dumps({"id": e["id"], "time": now(), "status": "uncertain", "resp": r}) + "\n"); rf.flush()
            log(f"STOP: {e['id']} 응답 불확실 {r} — 재전송 금지"); return 7
        await asyncio.sleep(a.sleep)
        try:
            _, ks1, v1 = await base.fetch_raw(cli, e["id"])
        except Exception as ex:
            rf.write(json.dumps({"id": e["id"], "time": now(), "status": "readback_failed"}) + "\n"); rf.flush()
            log(f"STOP: {e['id']} 재조회 실패 {ex}"); return 8
        after = dict(zip(ks1, v1))
        bad = [k for k in set(after) | set(e["expected"]) if k != "etime" and dump(after.get(k)) != dump(e["expected"].get(k))]
        if ks1 != ks0:
            bad.append("keys_order")
        (outd / "rows" / f"{e['id']}.after.json").write_bytes(dump({"keys": ks1, "row": after}))
        status = "ok" if not bad else "readback_mismatch"
        rf.write(json.dumps({"id": e["id"], "time": now(), "status": status, "bad": bad, "probe": bool(probe),
                             "plannedChange": e.get("plannedChange", {}),
                             "etimeChanged": before.get("etime") != after.get("etime")}) + "\n"); rf.flush()
        if bad:
            log(f"STOP: {e['id']} readback 불일치 {bad} — 이후 쓰기 중단(자동 rollback 없음)"); return 9
        log(f"{e['id']} ok" + (" (probe)" if probe or (planned_probe and e.get("plannedChange")) else ""))
    base.write_sums(outd)
    log(f"chunk done {len(todo)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--batch", required=True)
    p.add_argument("--snapshot", help="이미 받은 보드 원시 응답 파일(서버 재요청 없이 재생성)")
    p.add_argument("--out-root", dest="out_root")
    p.add_argument("--spec-dir", required=True)
    p.add_argument("--spec-manifest-sha", required=True)
    p.add_argument("--spec-sums-sha", required=True)
    p.add_argument("--hold-level", dest="hold_level", type=int, action="append", default=[])
    p.add_argument("--planned-change-mode", dest="planned_change_mode", choices=c22.PLANNED_MODES, default=None,
                   help="정책 미결 — 지정 시 planned_change 제안값을 payload 에 넣음(실행 시 --allow-planned-change 필요)")
    q = sub.add_parser("apply")
    q.add_argument("--manifest", required=True); q.add_argument("--manifest-sha", required=True)
    q.add_argument("--chunk", type=int, default=10); q.add_argument("--sleep", type=float, default=0.6)
    q.add_argument("--apply", action="store_true", help="명시 시에만 실제 쓰기 (기본 dry-run, 네트워크 없음)")
    q.add_argument("--allow-planned-change", dest="allow_planned_change", action="store_true",
                   help="planned_change(±1 5→3/재정렬) entry 쓰기 허용 — 정책 결정 후에만")
    a = ap.parse_args()
    if getattr(a, "sleep", 1) < 0.5:
        ap.error("--sleep >= 0.5")
    if a.cmd == "apply" and not (1 <= a.chunk <= MAX_CHUNK):
        ap.error(f"--chunk 1..{MAX_CHUNK}")
    if a.cmd == "apply" and not a.apply:
        return asyncio.run(cmd_apply(a))                                    # dry-run: lock 불필요, 네트워크 없음
    with base.Lock():
        return asyncio.run({"prepare": cmd_prepare, "apply": cmd_apply}[a.cmd](a))


if __name__ == "__main__":
    sys.exit(main())
