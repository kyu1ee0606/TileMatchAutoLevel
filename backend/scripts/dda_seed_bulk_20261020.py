#!/usr/bin/env python3
"""DDA 시드 일괄 업로드 — 준비(manifest) / 실행기 (문서 47 §13).

정식 경로: 프로덕션 배치 에디터 원본 + 업로드 화면 기본 입력 → 기존 변환기(_convert_to_townpop_format) + 두 시드.
(L159 단건과 같은 형식. 서버 행을 변환기에 넣거나 부분 키만 보내지 않는다.)

  prepare --batch <id>
      서버 levels 보드 전체 GET 1회(snapshot) → 레벨별 payload 생성·예측 읽기값(READBACK_RULES)·전수 비교
      → 준비/유지/보류/별도승인 분류 → frozen manifest(payload·hash·예상 readback·원본 backup) 작성. 쓰기 없음.
  apply --manifest <path> --manifest-sha <sha> [--chunk N] [--apply]
      기본 dry-run(네트워크 없음, 다음 청크 대상만 출력). --apply 일 때만 실제 쓰기:
      행마다 fresh GET(manifest 의 원본 행과 동일해야 함) → update-only(new=0 1회, '<id>=upt' 만 성공, 생성 fallback 없음,
      썸네일 없음) → 재조회 = 예상 readback(etime 제외) 확인. 이상·불확실 응답은 즉시 중단(재전송 없음).
      체크포인트(results.jsonl)로 재개 시 처리 행 skip, 불확실 행은 재조회로 상태 판정만(재전송 금지).
자동 rollback 없음 — 복구는 manifest 의 rows/<id>.before.json 을 근거로 별도 승인 후.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
from app.api.routes.gboost import _convert_to_townpop_format as conv  # noqa: E402
from app.clients.gboost import GBoostClient  # noqa: E402
from app.core import dda_seed_catalog as c  # noqa: E402
import dda_seed_server_apply_20261020 as base  # noqa: E402  (fetch_raw, Lock, resource_ok 재사용)

BOARD = c.DDA_BOARD_ID
SEEDS = c.SEED_FIELDS
KST = dt.timezone(dt.timedelta(hours=9))
EVIDENCE_L159 = "backend/data/dda_seeds/server_apply_20261020_1822/l159_upload_via_existing/step2/compare.json"
# 업로드 화면 기본값 (frontend/src/components/ProductionDashboard/ProductionExport.tsx)
UI_REWARD_COIN_FIXED = 5          # :333-334 fixed 5, :904, :948
UI_AUTOCOLLECT_VALUE = 3          # :344-345 multiples10 / 3, :921-925, :949
MAX_CHUNK = 20


def dump(o) -> bytes:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def now() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def ui_upload_json(level_json: dict, meta: dict, slot: int):
    """ProductionExport.handleUpload 기본 흐름과 같은 업로드 입력. predicted 없으면 None(화면은 RL 측정을 돌림 → 재현 불가)."""
    if meta.get("predicted_clear_rate") is None:
        return None
    up = copy.deepcopy(level_json)
    up["rewardCoin"] = UI_REWARD_COIN_FIXED
    up["autoCollectCount"] = UI_AUTOCOLLECT_VALUE if (slot > 0 and slot % 10 == 0) else 0
    up["predicted_clear_rate"] = meta["predicted_clear_rate"]
    return up


def classify(lid: str, level: int, lj: dict, meta: dict, srv: dict | None) -> dict:
    e = c.load_catalog()["_byLevel"].get(level)
    out = {"id": lid, "level": level}
    if e is None or e["status"] != "candidate":
        out.update(category="not_candidate", reason=(e or {}).get("status", "no_data"))
        return out
    if srv is None:
        out.update(category="hold", reason="no_server_row"); return out
    if any(f not in srv for f in SEEDS):
        out.update(category="hold", reason="no_seed_column"); return out
    srv_seeds = [srv.get(f) for f in SEEDS]
    exp = [e[f] for f in SEEDS]
    if srv_seeds == exp:
        snap = c.load_source_rows()["rows"][lid]
        diff = [k for k in snap if dump(srv.get(k)) != dump(snap[k])]
        if diff:   # 시드는 이미 같지만 행 조건이 출시와 다름(예: L158 관리 UI checkbox "") → 별도 승인 목록
            out.update(category="approval_needed", reason="keep_but_condition_mismatch:" + ",".join(diff)); return out
        out.update(category="keep", reason="server_seeds_equal_catalog"); return out
    if any(v not in ("", None) for v in srv_seeds):
        out.update(category="hold", reason="server_seed_conflict", detail=str(srv_seeds)[:120]); return out
    up = ui_upload_json(lj, meta, level)
    if up is None:
        out.update(category="hold", reason="predicted_missing(UI 는 RL 측정)"); return out
    tp = conv(copy.deepcopy(up))
    g = c._seed_values(level, lj, tp)                                      # 내부 시드·map·N 게이트
    if g["reason"] != "valid":
        out.update(category="hold", reason=f"internal_{g['reason']}"); return out
    payload = dict(tp)
    payload["ddaEasySeeds"], payload["ddaHardSeeds"] = exp
    pred, unverified = c.predict_readback(payload, srv)
    if unverified:
        out.update(category="hold", reason="unverified_serialization", detail=",".join(unverified)); return out
    raw_diffs = {k: [srv.get(k), payload.get(k)] for k in payload if k != "etime" and dump(payload.get(k)) != dump(srv.get(k))}
    meaning = {k: [srv.get(k), pred.get(k)] for k in srv if k not in SEEDS and k != "etime" and dump(pred.get(k)) != dump(srv.get(k))}
    snap = c.load_source_rows()["rows"][lid]
    core = {k: pred.get(k) for k in snap}
    cond_ok = c.source_condition_hash(core) == e["sourceConditionHash"] and dump(core) == dump(snap)
    map_ok = sha(dump(srv.get("map"))) == e["sourceMapSha256"] and dump(payload["map"]) == dump(srv.get("map"))
    out.update(rawDiffCount=len(raw_diffs), meaningDiffs=meaning, condOk=cond_ok, mapOk=map_ok)
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
    out.update(category="ready", reason="fill", payload=payload, expected=pred, before=srv)
    return out


async def cmd_prepare(a):
    stamp = dt.datetime.now(KST).strftime("%Y%m%d_%H%M")
    outd = Path(getattr(a, "out_root", None) or (BACKEND / "data" / "dda_seeds")) / f"bulk_prepare_{stamp}"
    (outd / "rows").mkdir(parents=True, exist_ok=False)
    logf = (outd / "run.log").open("a")

    def log(m):
        line = f"[{now()}] {m}"; print(line, flush=True); logf.write(line + "\n"); logf.flush()
    if not base.resource_ok(log):
        log("STOP: resource"); return 3
    bpath = Path(getattr(a, "batch_file", None) or (BACKEND / "data" / "production" / f"{a.batch}.json"))
    braw = bpath.read_bytes()
    batch = json.loads(braw)
    if getattr(a, "snapshot", None):                                        # 이미 받은 snapshot 재사용(서버 요청 없음)
        raw = Path(a.snapshot).read_bytes()
        board = {"raw": raw, "raw_sha256": sha(raw), "raw_bytes": len(raw)}
        log(f"snapshot 재사용 {a.snapshot}")
    else:
        cli = GBoostClient()
        board = await cli.load_board_rows(BOARD)                           # 서버 읽기 1회
    (outd / "server_levels_snapshot.raw.json").write_bytes(board["raw"])
    data = json.loads(board["raw"].decode())
    ks = data["__keys"]
    if any(not v or len(v) != len(ks) for v in data["__vals"]):
        log("STOP: 부분 응답(열 개수 불일치)"); return 4
    rows = {v[ks.index("id")]: dict(zip(ks, v)) for v in data["__vals"]}
    if len(rows) != len(data["__vals"]):
        log("STOP: 중복 id"); return 4
    log(f"server GET 1회 bytes={board['raw_bytes']} sha256={board['raw_sha256']} rows={len(rows)} keys={len(ks)}")
    plans = []
    for l in sorted(batch["levels"], key=lambda x: x["meta"]["level_number"]):
        if not l.get("level_json"):
            continue
        n = l["meta"]["level_number"]
        lid = f"level_{n}"
        plans.append(classify(lid, n, l["level_json"], l["meta"], rows.get(lid)))
    ready = [p for p in plans if p["category"] == "ready"]
    for p in plans:
        if p["category"] in ("ready", "approval_needed") and "before" in p:
            (outd / "rows" / f"{p['id']}.before.json").write_bytes(dump({"keys": ks, "row": p["before"]}))
    entries = [{"id": p["id"], "level": p["level"], "payload": p["payload"], "payloadSha256": sha(dump(p["payload"])),
                "beforeRowSha256": sha(dump(p["before"])), "expected": {k: v for k, v in p["expected"].items() if k != "etime"},
                "backup": f"rows/{p['id']}.before.json"} for p in ready]
    manifest = {
        "manifestVersion": "dda_seed_bulk_manifest.v1", "createdAt": now(), "board": BOARD,
        "serverSnapshotSha256": board["raw_sha256"], "serverSnapshotBytes": board["raw_bytes"],
        "batch": a.batch, "batchSha256": sha(braw), "catalogSha256": c.CATALOG_SHA256, "rowsSha256": c.ROWS_SHA256,
        "readbackRules": {"version": c.READBACK_RULES_VERSION, "rules": c.READBACK_RULES, "evidence": EVIDENCE_L159},
        "uiInputs": {"rewardCoin": UI_REWARD_COIN_FIXED, "autoCollect": f"slot%10==0 -> {UI_AUTOCOLLECT_VALUE} else 0",
                     "predicted_clear_rate": "meta", "source": "frontend/src/components/ProductionDashboard/ProductionExport.tsx:333-345,902-954"},
        "codeSha256": {f: sha((BACKEND / f).read_bytes()) for f in
                       ("app/core/dda_seed_catalog.py", "app/api/routes/gboost.py", "app/clients/gboost.py",
                        "scripts/dda_seed_bulk_20261020.py")},
        "entries": entries,
    }
    mbytes = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
    (outd / "manifest.json").write_bytes(mbytes)
    summary = {"time": now(), "manifestSha256": sha(mbytes), "ready": len(ready),
               "byCategory": dict(Counter(p["category"] for p in plans)),
               "byReason": dict(Counter(f"{p['category']}:{p['reason']}" for p in plans)),
               "approvalNeeded": [p["id"] for p in plans if p["category"] == "approval_needed"],
               "keep": [p["id"] for p in plans if p["category"] == "keep"],
               "holdLevels": {r: [p["level"] for p in plans if f"{p['category']}:{p['reason']}" == r]
                              for r in {f"{p['category']}:{p['reason']}" for p in plans if p["category"] == "hold"}},
               "rawDiffCountReady": dict(Counter(p.get("rawDiffCount") for p in ready))}
    (outd / "plan.json").write_bytes(dump([{k: v for k, v in p.items() if k not in ("payload", "expected", "before")} for p in plans]))
    (outd / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    base.write_sums(outd)
    log(f"manifest {outd/'manifest.json'} sha256={summary['manifestSha256']} ready={len(ready)}")
    log(f"byReason {json.dumps(summary['byReason'], ensure_ascii=False)}")
    return 0


async def cmd_apply(a):
    mpath = Path(a.manifest)
    mbytes = mpath.read_bytes()
    if sha(mbytes) != a.manifest_sha:
        print(f"STOP: manifest sha 불일치 {sha(mbytes)}"); return 2
    m = json.loads(mbytes)
    outd = mpath.parent
    for f, h in m["codeSha256"].items():
        if f != "scripts/dda_seed_bulk_20261020.py" and sha((BACKEND / f).read_bytes()) != h:
            print(f"STOP: 코드 변경됨 {f} — manifest 재생성 필요"); return 2
    res_p = outd / "results.jsonl"
    done = {}
    if res_p.exists():
        for line in res_p.read_text().splitlines():
            r = json.loads(line); done[r["id"]] = r
    uncertain = [i for i, r in done.items() if r["status"] not in ("ok",)]
    if uncertain:
        print(f"STOP: 이전 실행의 미완료/불확실 행 {uncertain} — 재조회 판정 필요, 재전송 금지"); return 2
    todo = [e for e in m["entries"] if e["id"] not in done][: min(a.chunk, MAX_CHUNK)]
    if not a.apply:
        print(json.dumps({"dryRun": True, "remaining": len(m["entries"]) - len(done), "nextChunk": [e["id"] for e in todo]},
                         ensure_ascii=False))
        return 0
    logf = (outd / "apply.log").open("a")

    def log(msg):
        line = f"[{now()}] {msg}"; print(line, flush=True); logf.write(line + "\n"); logf.flush()
    cli = GBoostClient()
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
            body1, ks1, v1 = await base.fetch_raw(cli, e["id"])
        except Exception as ex:
            rf.write(json.dumps({"id": e["id"], "time": now(), "status": "readback_failed"}) + "\n"); rf.flush()
            log(f"STOP: {e['id']} 재조회 실패 {ex}"); return 8
        after = dict(zip(ks1, v1))
        bad = [k for k in set(after) | set(e["expected"]) if k != "etime" and dump(after.get(k)) != dump(e["expected"].get(k))]
        if ks1 != ks0:
            bad.append("keys_order")
        (outd / "rows" / f"{e['id']}.after.json").write_bytes(dump({"keys": ks1, "row": after}))
        status = "ok" if not bad else "readback_mismatch"
        rf.write(json.dumps({"id": e["id"], "time": now(), "status": status, "bad": bad,
                             "etimeChanged": before.get("etime") != after.get("etime")}) + "\n"); rf.flush()
        if bad:
            log(f"STOP: {e['id']} readback 불일치 {bad} — 이후 쓰기 중단(자동 rollback 없음)"); return 9
        log(f"{e['id']} ok")
    base.write_sums(outd)
    log(f"chunk done {len(todo)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--batch", required=True)
    p.add_argument("--snapshot", help="이미 받은 보드 원시 응답 파일(서버 재요청 없이 재생성)")
    q = sub.add_parser("apply")
    q.add_argument("--manifest", required=True); q.add_argument("--manifest-sha", required=True)
    q.add_argument("--chunk", type=int, default=10); q.add_argument("--sleep", type=float, default=0.6)
    q.add_argument("--apply", action="store_true", help="명시 시에만 실제 쓰기 (기본 dry-run, 네트워크 없음)")
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
