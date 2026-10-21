#!/usr/bin/env python3
"""DDA 시드만 GameBoost levels 보드에 저장 (문서 47 §8, 2026-10-20 사용자 명시 승인 범위 한정).

범위: levels 보드 기존 행의 ddaEasySeeds / ddaHardSeeds 두 컬럼 '채우기'만.
      빈 문자열로 서버 값 삭제·보류 레벨 비우기·충돌 덮어쓰기·다른 컬럼 변경·새 행 생성은 하지 않는다.

명령:
  snapshot --batch <batch_id>                 서버 보드 전체 읽기(쓰기 없음) + 로컬 내부 저장본 대조 → 감사 폴더 생성
  apply    --audit <dir> --roundtrip 158      L158: 서버 행을 그대로(같은 시드) 다시 저장 → 재조회 보존 시험
  apply    --audit <dir> --levels 159         지정 레벨(계획 category=fill) 시드 채우기
  apply    --audit <dir> --next 50            다음 미처리 fill 레벨 N개 (체크포인트 기준)
  verify   --audit <dir>                      보드 전체 재조회 → 스냅샷 대비 변경 키 집계(쓰기 없음)
쓰기 규칙: 매 행 저장 직전 strict 재조회 → 스냅샷 digest 와 다르면 중단 / update 전용(new=0, '=upt' 확인) /
          저장 후 strict 재조회로 두 컬럼 정확 일치 + 다른 키·값·자료형·map 동일 확인(--allow-auto-meta 키만 예외)
          → 이상 1건이면 즉시 중단(역덮어쓰기 없음). 요청 간 sleep ≥0.5s, 1프로세스 lock, swap<500MB 면 중단.
감사 자료에 자격증명/프로젝트 ID 를 쓰지 않는다.
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
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.api.routes.gboost import _convert_to_townpop_format as conv  # noqa: E402
import aiohttp  # noqa: E402
from app.clients.gboost import GBoostClient, GBoostLookupError  # noqa: E402
from app.core import dda_seed_catalog as c  # noqa: E402

BOARD = c.DDA_BOARD_ID
SEEDS = c.SEED_FIELDS
DDA_DIR = BACKEND / "data" / "dda_seeds"
LOCK = DDA_DIR / ".server_apply.lock"
KST = dt.timezone(dt.timedelta(hours=9))


def now() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def dump(o) -> bytes:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def swap_free_mb() -> float:
    out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"free = ([0-9.]+)M", out)
    return float(m.group(1)) if m else -1.0


def resource_ok(log) -> bool:
    free = swap_free_mb()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True).stdout.strip()
    log(f"resource swap_free={free:.0f}MB pressure={lvl}")
    return free >= 500 and lvl != "4"


class Lock:
    def __enter__(self):
        self.fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(self.fd, f"{os.getpid()} {now()}\n".encode())
        return self

    def __exit__(self, *a):
        os.close(self.fd)
        LOCK.unlink(missing_ok=True)


def mklog(audit: Path):
    f = (audit / "run.log").open("a", encoding="utf-8")

    def log(msg):
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        f.write(line + "\n")
        f.flush()
    return log


def field_state(srv_val, expected: str) -> str:
    v = c._norm(srv_val)
    if v == expected:
        return "same"
    if v == "":
        return "fill"
    return "conflict"


def classify(lid: str, lj: dict, srv_row) -> dict:
    """레벨별 계획 (쓰기 없음)."""
    level = int(lid.split("_")[1])
    entry = c.load_catalog()["_byLevel"].get(level)
    tp = conv(copy.deepcopy(lj))
    plan = c.seed_only_plan(lid, lj, tp, srv_row)
    plan.pop("payload", None)
    out = {"level": level, "id": lid}
    if srv_row is not None:
        out["serverSeeds"] = [c._norm(srv_row.get(f)) if f in srv_row else None for f in SEEDS]
        excl = {"etime", "idx"}
        out["condHashExact"] = (entry is not None and c.source_condition_hash(
            {k: v for k, v in srv_row.items() if k not in excl}) == entry.get("sourceConditionHash"))
        out["serverRowDigest"] = c.row_digest(srv_row)
    if entry is None:
        out.update(category="no_data")
        return out
    if entry["status"] != "candidate":
        out.update(category=f"excluded:{entry['status']}")
        return out
    if plan["blocked"]:
        out.update(category="blocked", reason=plan["reason"], detail=plan.get("detail", ""))
        return out
    if plan["reason"] != "valid":
        out.update(category="internal_invalid", reason=plan["reason"])
        return out
    states = [field_state(srv_row.get(f), entry[f]) for f in SEEDS]
    out["fieldStates"] = states
    out["expected"] = [entry[f] for f in SEEDS]
    out["category"] = ("conflict" if "conflict" in states else "same" if states == ["same", "same"] else "fill")
    return out


async def cmd_snapshot(a):
    stamp = dt.datetime.now(KST).strftime("%Y%m%d_%H%M")
    audit = DDA_DIR / f"server_apply_{stamp}"
    (audit / "rows").mkdir(parents=True, exist_ok=False)
    log = mklog(audit)
    if not resource_ok(log):
        log("STOP: resource")
        return 2
    batch_path = BACKEND / "data" / "production" / f"{a.batch}.json"
    braw = batch_path.read_bytes()
    batch = json.loads(braw)
    local = {f"level_{l['meta']['level_number']}": l["level_json"] for l in batch["levels"] if l.get("level_json")}
    log(f"local batch {a.batch} levels={len(local)} sha256={sha(braw)}")

    cli = GBoostClient()
    t0 = time.time()
    board = await cli.load_board_rows(BOARD)
    log(f"server board read: bytes={board['raw_bytes']} sha256={board['raw_sha256']} rows={len(board['rows'])} "
        f"keys={len(board['keys'])} {time.time() - t0:.1f}s")
    (audit / "server_levels_before.raw.json").write_bytes(board["raw"])
    data = json.loads(board["raw"].decode())
    n_vals = len(data["__vals"])
    bad_len = sum(1 for r in data["__vals"] if not r or len(r) != len(data["__keys"]))
    id_i = data["__keys"].index("id") if "id" in data["__keys"] else 0
    ids = [r[id_i] for r in data["__vals"] if r]
    dup = sorted({i for i in ids if ids.count(i) > 1}) if len(ids) != len(set(ids)) else []
    integrity = {"vals": n_vals, "parsedRows": len(board["rows"]), "badLength": bad_len, "duplicateIds": dup,
                 "keys": data["__keys"], "seedColumnsPresent": all(k in data["__keys"] for k in SEEDS)}
    log(f"integrity {json.dumps({k: v for k, v in integrity.items() if k != 'keys'})}")

    types = {}
    r158 = board["rows"].get("level_158")
    if r158:
        types = {k: type(v).__name__ for k, v in r158.items()}
    plans = [classify(lid, lj, board["rows"].get(lid)) for lid, lj in sorted(local.items(), key=lambda x: int(x[0].split("_")[1]))]
    from collections import Counter
    cnt = Counter(p["category"] + (":" + p["reason"] if p.get("reason") and p["category"] in ("blocked", "internal_invalid") else "") for p in plans)
    srv_nonempty_noncand = [p["id"] for p in plans if p["category"].startswith("excluded") or p["category"] == "no_data"
                            if p.get("serverSeeds") and any(p["serverSeeds"])]
    summary = {"time": now(), "batch": a.batch, "batchSha256": sha(braw), "serverHost": urlparse(cli.base_url).netloc,
               "board": BOARD, "serverRawSha256": board["raw_sha256"], "integrity": {k: v for k, v in integrity.items()},
               "catalogSha256": c.CATALOG_SHA256, "rowsSha256": c.ROWS_SHA256, "level158Types": types,
               "counts": dict(sorted(cnt.items())),
               "condHashExactTrue": sum(1 for p in plans if p.get("condHashExact")),
               "serverSeedOnNonCandidate": srv_nonempty_noncand}
    (audit / "plan.json").write_bytes(dump(plans))
    (audit / "summary_snapshot.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    write_sums(audit)
    log(f"counts {json.dumps(summary['counts'], ensure_ascii=False)}")
    log(f"AUDIT {audit}")
    return 0


async def load_row_raw(cli, lid: str):
    """단건 원시 조회(real_array act=load id=<lid>, load_level 과 같은 엔드포인트). 파서가 버리는 빈 이름 컬럼('')·idx 까지
    보존한 dict 와 키 순서를 돌려준다. 응답 실패/행 0개·2개 이상은 GBoostLookupError."""
    url = f"{cli.base_url}/real_array.php?act=load&gid={cli.project_id}&bid={BOARD}&id={lid}&filter="
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                raise GBoostLookupError(f"HTTP {r.status}")
            body = await r.read()
    data = json.loads(body.decode("utf-8"))
    ks, vals = data.get("__keys"), data.get("__vals")
    if not ks or vals is None:
        raise GBoostLookupError("unexpected format")
    rows = [v for v in vals if v and len(v) == len(ks) and v[ks.index("id")] == lid]
    if len(rows) != 1 or any(len(v) != len(ks) for v in vals):
        raise GBoostLookupError(f"row count {len(rows)} / vals {len(vals)}")
    return list(ks), dict(zip(ks, rows[0]))


def write_sums(audit: Path):
    lines = []
    for p in sorted(audit.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            lines.append(f"{sha(p.read_bytes())}  {p.relative_to(audit)}")
    (audit / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def done_ids(audit: Path) -> dict:
    out = {}
    p = audit / "results.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            r = json.loads(line)
            out[r["id"]] = r
    return out


def compare_rows(before: dict, after: dict, expected_seeds, allow_meta) -> list:
    diffs = []
    for k in list(before) + [k for k in after if k not in before]:
        if k in SEEDS:
            continue
        if k not in after:
            diffs.append(f"{k}:removed")
        elif k not in before:
            diffs.append(f"{k}:added")
        elif dump(before[k]) != dump(after[k]):
            diffs.append(f"{k}:changed")
    seeds_ok = [after.get(f) for f in SEEDS] == list(expected_seeds)
    if not seeds_ok:
        diffs.append(f"seeds:{[after.get(f) for f in SEEDS]}!={list(expected_seeds)}")
    return [d for d in diffs if d.split(":")[0] not in allow_meta]


async def cmd_apply(a):
    audit = Path(a.audit)
    log = mklog(audit)
    plans = {p["id"]: p for p in json.loads((audit / "plan.json").read_bytes())}
    before_board = json.loads((audit / "server_levels_before.raw.json").read_bytes().decode())
    snap_rows = {}
    ks = before_board["__keys"]
    for r in before_board["__vals"]:
        if r and len(r) == len(ks):
            snap_rows[r[ks.index("id")]] = dict(zip(ks, r))
    done = done_ids(audit)
    allow_meta = set(x for x in (a.allow_auto_meta or "").split(",") if x)

    if a.roundtrip:
        targets = [f"level_{a.roundtrip}"]
        e = c.load_catalog()["_byLevel"].get(a.roundtrip) or {}
        if plans[targets[0]].get("serverSeeds") != [e.get(f) for f in SEEDS]:
            log(f"STOP: roundtrip 대상의 서버 시드가 검증값과 같지 않음 — 같은 값 보존 시험 불가")
            return 2
    elif a.levels:
        targets = [f"level_{x.strip()}" for x in a.levels.split(",") if x.strip()]
    else:
        targets = [i for i, p in sorted(plans.items(), key=lambda x: x[1]["level"])
                   if p["category"] == "fill" and i not in done][: a.next]
    for t in targets:
        if not a.roundtrip and (plans.get(t, {}).get("category") != "fill" or t in done):
            log(f"STOP: {t} 대상 아님 (category={plans.get(t, {}).get('category')}, done={t in done})")
            return 2
    if a.roundtrip:
        log("STOP: 전체 행 roundtrip 경로는 §9 이후 비활성")
        return 2
    if not c.PARTIAL_UPDATE_VERIFIED:
        log("STOP: 부분 수정의 누락 컬럼 보존 근거 미확보(PARTIAL_UPDATE_VERIFIED=False) — 서버 쓰기 차단")
        return 2
    log(f"apply start targets={len(targets)} first={targets[:3]} roundtrip={bool(a.roundtrip)} allow_meta={sorted(allow_meta)}")
    cli = GBoostClient()
    res_f = (audit / "results.jsonl").open("a", encoding="utf-8")
    n_ok = 0
    for i, lid in enumerate(targets):
        if i % 10 == 0 and not resource_ok(log):
            log("STOP: resource")
            return 3
        await asyncio.sleep(a.sleep)
        try:
            keys_before, raw_before = await load_row_raw(cli, lid)
        except Exception as e:
            log(f"STOP: {lid} 저장 전 조회 실패 {e}")
            return 4
        row = {k: v for k, v in raw_before.items() if k}      # 파서와 같은 표현(빈 이름 컬럼 제외)
        if c.row_digest(row) != plans[lid]["serverRowDigest"]:
            log(f"STOP: {lid} 스냅샷 이후 서버 행 변경(경합) — 쓰기 안 함")
            (audit / "rows" / f"{lid}.changed_before_write.json").write_bytes(dump(row))
            return 5
        # [§9] 두 시드 필드만 담은 부분 수정 payload (전체 행 재전송 금지)
        expected = [row.get(f) for f in SEEDS] if a.roundtrip else plans[lid]["expected"]
        payload = {f: row.get(f) for f in SEEDS}
        if not a.roundtrip:
            for f, st, ev in zip(SEEDS, plans[lid]["fieldStates"], expected):
                if st == "fill":
                    payload[f] = ev
                elif st != "same":
                    log(f"STOP: {lid} {f} state={st}")
                    return 6
        c.assert_partial_payload(payload)
        (audit / "rows" / f"{lid}.before.json").write_bytes(dump({"keys": keys_before, "row": raw_before}))
        (audit / "rows" / f"{lid}.payload.json").write_bytes(dump(payload))
        r = await cli.update_existing_level(BOARD, lid, payload)
        log(f"{lid} save success={r.get('success')} head={r.get('head')!r} {r.get('error', '')}")
        await asyncio.sleep(a.sleep)
        try:
            keys_after, after = await load_row_raw(cli, lid)
        except Exception as e:
            keys_after, after = [], None
            log(f"{lid} 저장 후 조회 실패 {e}")
        (audit / "rows" / f"{lid}.after.json").write_bytes(dump({"keys": keys_after, "row": after}))
        diffs = compare_rows(raw_before, after, expected, allow_meta) if isinstance(after, dict) else ["after:missing"]
        if isinstance(after, dict) and keys_after != keys_before:
            diffs.append("keys:order_or_set_changed")
        meta = [k for k in (allow_meta or []) if isinstance(after, dict) and dump(raw_before.get(k)) != dump(after.get(k))]
        all_changed = [k for k in set(raw_before) | set(after or {}) if isinstance(after, dict)
                       and dump(raw_before.get(k)) != dump(after.get(k))]
        rec = {"id": lid, "time": now(), "saveSuccess": bool(r.get("success")), "diffs": diffs, "autoMetaChanged": meta,
               "changedKeys": sorted(all_changed),
               "beforeDigest": c.row_digest(row), "afterDigest": c.row_digest(after) if isinstance(after, dict) else None,
               "mode": "roundtrip" if a.roundtrip else "fill"}
        res_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        res_f.flush()
        if not r.get("success") or diffs:
            log(f"STOP: {lid} 이상 diffs={diffs} — 신규 쓰기 중단, 역덮어쓰기 없음")
            write_sums(audit)
            return 7
        n_ok += 1
    log(f"apply done ok={n_ok}/{len(targets)}")
    write_sums(audit)
    return 0


async def cmd_verify(a):
    audit = Path(a.audit)
    log = mklog(audit)
    cli = GBoostClient()
    board = await cli.load_board_rows(BOARD)
    stamp = dt.datetime.now(KST).strftime("%H%M%S")
    (audit / f"server_levels_after_{stamp}.raw.json").write_bytes(board["raw"])
    before = json.loads((audit / "server_levels_before.raw.json").read_bytes().decode())
    ks = before["__keys"]
    brows = {r[ks.index("id")]: dict(zip(ks, r)) for r in before["__vals"] if r and len(r) == len(ks)}
    done = done_ids(audit)
    from collections import Counter
    changed = Counter()
    unexpected = []
    for lid, b in brows.items():
        aft = board["rows"].get(lid)
        if aft is None:
            unexpected.append(f"{lid}:missing")
            continue
        diff = [k for k in set(b) | set(aft) if dump(b.get(k)) != dump(aft.get(k))]
        for k in diff:
            changed[k] += 1
        bad = [k for k in diff if k not in SEEDS and k not in (a.allow_auto_meta or "").split(",")]
        if bad or (diff and lid not in done):
            unexpected.append(f"{lid}:{sorted(diff)}")
    extra = [i for i in board["rows"] if i not in brows]
    out = {"time": now(), "rawSha256": board["raw_sha256"], "rows": len(board["rows"]), "changedKeyCounts": dict(changed),
           "processed": len(done), "unexpected": unexpected[:50], "unexpectedCount": len(unexpected), "newIds": extra[:20]}
    (audit / f"verify_{stamp}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    write_sums(audit)
    log(f"verify {json.dumps({k: v for k, v in out.items() if k != 'unexpected'}, ensure_ascii=False)}")
    return 0 if not unexpected and not extra else 8


# 2026-10-20 18:28 L159 1회 시험 완료(rewardList null→[["null",0,0,0]] 변경 확인) → 전체 행 재전송 영구 비활성 (§9)
ROUNDTRIP_ALLOWED: set = set()


async def fetch_raw(cli, lid: str):
    """단건 원시 GET — 응답 본문 바이트 그대로 반환(감사 저장용) + (keys, row)."""
    url = f"{cli.base_url}/real_array.php?act=load&gid={cli.project_id}&bid={BOARD}&id={lid}&filter="
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
            status = r.status
            body = await r.read()
    if status != 200:
        raise GBoostLookupError(f"HTTP {status}")
    data = json.loads(body.decode("utf-8"))
    ks, vals = data.get("__keys"), data.get("__vals")
    if not ks or vals is None or any(not v or len(v) != len(ks) for v in vals):
        raise GBoostLookupError("unexpected format / length mismatch")
    rows = [v for v in vals if v[ks.index("id")] == lid]
    if len(rows) != 1:
        raise GBoostLookupError(f"row count {len(rows)}")
    return body, list(ks), rows[0]


async def cmd_roundtrip_test(a):
    """L159 그대로 재저장 1회 시험. 시드 채우기·다른 레벨·재시도·두 번째 POST 불가."""
    if a.level not in ROUNDTRIP_ALLOWED:
        print(f"STOP: level {a.level} 는 승인 범위 밖 (허용 {sorted(ROUNDTRIP_ALLOWED)})")
        return 2
    lid = f"level_{a.level}"
    out = Path(a.audit) / f"roundtrip_{lid}"
    marker = out / "POST_ATTEMPTED"
    if marker.exists():
        print(f"STOP: {marker} 존재 — 두 번째 POST 금지")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    log = mklog(out)
    if not resource_ok(log):
        log("STOP: resource")
        return 3
    cli = GBoostClient()
    try:
        body0, ks0, v0 = await fetch_raw(cli, lid)
    except Exception as e:
        log(f"STOP: before GET 실패 {type(e).__name__}: {e}")
        return 4
    (out / "before.raw.json").write_bytes(body0)
    log(f"before GET ok bytes={len(body0)} sha256={sha(body0)} keys={len(ks0)}")
    raw0 = list(zip(ks0, v0))
    payload = {k: v for k, v in raw0 if k and k not in c.SERVER_MANAGED_KEYS}   # 빈 이름 열 미전송(기존 동작)
    sent_keys = [k for k, _ in raw0 if k and k not in c.SERVER_MANAGED_KEYS]
    assert list(payload) == sent_keys and all(dump(payload[k]) == dump(dict(raw0)[k]) for k in sent_keys)
    (out / "payload.json").write_bytes(dump(payload))
    log(f"payload keys={len(payload)} sha256={sha(dump(payload))} excluded={[k for k, _ in raw0 if k not in payload]}")
    marker.write_text(now() + "\n")
    r = await cli.update_existing_level(BOARD, lid, payload)      # 정확히 1회, new=0, 폴백 없음
    resp = {"time": now(), "success": bool(r.get("success")), "status": r.get("status"), "head": r.get("head"),
            "error": r.get("error")}
    (out / "post_response.json").write_text(json.dumps(resp, ensure_ascii=False, indent=1))
    log(f"POST 1회 {resp}")
    await asyncio.sleep(1.0)
    try:
        body1, ks1, v1 = await fetch_raw(cli, lid)
    except Exception as e:
        log(f"after GET 실패 {type(e).__name__}: {e} — 재시도·추가 쓰기 없음")
        write_sums(out)
        return 5
    (out / "after.raw.json").write_bytes(body1)
    b, aft = dict(zip(ks0, v0)), dict(zip(ks1, v1))
    cmp = {"keysOrderSame": ks0 == ks1, "keysBefore": ks0, "keysAfter": ks1,
           "perKey": {k: ("same" if (k in b and k in aft and dump(b[k]) == dump(aft[k])) else
                          "missing_after" if k not in aft else "added_after" if k not in b else
                          f"diff: {dump(b[k]).decode()[:80]} -> {dump(aft[k]).decode()[:80]}")
                      for k in list(ks0) + [k for k in ks1 if k not in ks0]},
           "typesSame": all(type(b.get(k)).__name__ == type(aft.get(k)).__name__ for k in set(b) | set(aft)),
           "rawBodySame": body0 == body1, "beforeSha256": sha(body0), "afterSha256": sha(body1)}
    diffs = {k: v for k, v in cmp["perKey"].items() if v != "same"}
    cmp["diffKeys"] = diffs
    (out / "compare.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=1))
    log(f"after GET ok sha256={sha(body1)} keysOrderSame={cmp['keysOrderSame']} diffs={diffs}")
    write_sums(out)
    return 0 if resp["success"] and not diffs and cmp["keysOrderSame"] else 6


UPLOAD_ONE_LEVEL = 159   # 2026-10-20 조율 승인: L159 원본(기존 변환기 payload)+두 시드 1건 한정 (§12)
STEP1_BATCH_SHA = "a6aa2af664f010bb91dc265f300d3a5bcdd612d6977a4dc296511ed9cff9bf2b"


async def cmd_upload_l159(a):
    """§12 L159 1건: 1단계 payload_local.json 그대로 update-only(new=0) 1회. 썸네일·재시도·다른 레벨 없음."""
    if a.level != UPLOAD_ONE_LEVEL:
        print(f"STOP: level {a.level} 거부 (허용 {UPLOAD_ONE_LEVEL})"); return 2
    lid = f"level_{a.level}"
    d = Path(a.audit) / "l159_upload_via_existing"
    out = d / "step2"
    marker = out / "POST_ATTEMPTED"
    if marker.exists():
        print("STOP: POST_ATTEMPTED 존재 — 두 번째 POST 금지"); return 2
    out.mkdir(parents=True, exist_ok=True)
    log = mklog(out)
    if not resource_ok(log):
        log("STOP: resource"); return 3
    # 고정값 확인
    bsha = sha((BACKEND / "data" / "production" / "batch_1792056041502_cn5e4ny66.json").read_bytes())
    cat = c.load_catalog(); e = cat["_byLevel"][a.level]
    pbytes = (d / "payload_local.json").read_bytes()
    payload = json.loads(pbytes)
    checks = {
        "batchSha": bsha == STEP1_BATCH_SHA, "catalogSha": cat["_sha256"] == c.CATALOG_SHA256,
        "payloadRoundtripBytes": dump(payload) == pbytes,
        "seedsEqCatalog": [payload.get(f) for f in SEEDS] == [e[f] for f in SEEDS],
        "mapShaEqCatalog": sha(dump(payload["map"])) == e["sourceMapSha256"],
        "N": payload.get("useTileCount") == str(e["N"]),
        "rewardCoin5": payload.get("rewardCoin") == "5", "difficulty61": payload.get("difficulty") == "61",
        "randSeed": payload.get("randSeed") == str(c.load_source_rows()["rows"][lid]["randSeed"]),
    }
    log(f"checks {checks} payloadSha={sha(pbytes)}")
    if not all(checks.values()):
        log("STOP: 고정값 검증 실패"); return 4
    step1 = sorted(d.glob("server_l159_*.raw.json"))[-1].read_bytes()
    cli = GBoostClient()
    try:
        body0, ks0, v0 = await fetch_raw(cli, lid)
    except Exception as ex:
        log(f"STOP: fresh GET 실패 {ex}"); return 5
    (out / "before.raw.json").write_bytes(body0)
    if body0 != step1:
        log(f"STOP: fresh GET ≠ 1단계 원시값 (sha {sha(body0)} vs {sha(step1)}) — 경합"); return 6
    log(f"fresh GET == step1 sha256={sha(body0)}")
    marker.write_text(now() + "\n")
    r = await cli.update_existing_level(BOARD, lid, payload)          # new=0 1회, 폴백·썸네일 없음
    resp = {"time": now(), "success": bool(r.get("success")), "status": r.get("status"), "head": r.get("head"), "error": r.get("error")}
    (out / "post_response.json").write_text(json.dumps(resp, ensure_ascii=False, indent=1))
    log(f"POST 1회 {resp}")
    await asyncio.sleep(1.0)
    try:
        body1, ks1, v1 = await fetch_raw(cli, lid)
    except Exception as ex:
        log(f"after GET 실패 {ex} — 중단"); write_sums(out); return 7
    (out / "after.raw.json").write_bytes(body1)
    before, after = dict(zip(ks0, v0)), dict(zip(ks1, v1))
    pred = dict(before)                                                  # 예측(추론: 08-19 2401행 관측 규칙)
    pred.update(backgroundIndex=None, tileSkin=None, rewardList=None, visualTileSeed="", useInRandomizer=0,
                useTeleportInRandomizer=0, ddaEasySeeds=e["ddaEasySeeds"], ddaHardSeeds=e["ddaHardSeeds"])
    rows = []
    for k in list(ks0) + [k for k in ks1 if k not in ks0]:
        pv, av, bv = pred.get(k, "<absent>"), after.get(k, "<absent>"), before.get(k, "<absent>")
        if k == "etime":
            st = "changed(server)" if av != bv else "unchanged"
        elif k == "map":
            st = "match" if dump(av) == dump(pv) else "MISMATCH"; pv, av, bv = sha(dump(pv))[:12], sha(dump(av))[:12], sha(dump(bv))[:12]
        else:
            st = "match" if dump(av) == dump(pv) else "MISMATCH"
        rows.append({"key": k, "before": bv, "predicted": pv, "actual": av, "status": st})
    snap = c.load_source_rows()["rows"][lid]
    core = {k: after.get(k) for k in snap}
    res = {"keysOrderSame": ks0 == ks1, "rows": rows,
           "condHashEqCatalog": c.source_condition_hash(core) == e["sourceConditionHash"],
           "afterCoreEqShipped": dump(core) == dump(snap),
           "seedsExact": [after.get(f) for f in SEEDS] == [e[f] for f in SEEDS],
           "mapShaEqCatalog": sha(dump(after.get("map"))) == e["sourceMapSha256"],
           "beforeSha": sha(body0), "afterSha": sha(body1)}
    (out / "compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    bad = [x["key"] for x in rows if x["status"] == "MISMATCH"]
    log(f"after GET sha256={sha(body1)} mismatches={bad} condHash={res['condHashEqCatalog']} seeds={res['seedsExact']} keysOrderSame={res['keysOrderSame']}")
    write_sums(out)
    return 0 if resp["success"] and not bad and res["condHashEqCatalog"] and res["seedsExact"] and res["keysOrderSame"] else 8


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--batch", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--audit", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--roundtrip", type=int)
    g.add_argument("--levels")
    g.add_argument("--next", type=int)
    p.add_argument("--sleep", type=float, default=0.6)
    p.add_argument("--allow-auto-meta", default="")
    rt = sub.add_parser("roundtrip-test")
    rt.add_argument("--audit", required=True)
    rt.add_argument("--level", type=int, required=True)
    up = sub.add_parser("upload-l159")
    up.add_argument("--audit", required=True)
    up.add_argument("--level", type=int, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--audit", required=True)
    v.add_argument("--allow-auto-meta", default="")
    a = ap.parse_args()
    if getattr(a, "sleep", 1) < 0.5:
        ap.error("--sleep >= 0.5")
    if getattr(a, "next", None) is not None and not (1 <= a.next <= 50):
        ap.error("--next 1..50")
    with Lock():
        fn = {"snapshot": cmd_snapshot, "apply": cmd_apply, "verify": cmd_verify,
              "roundtrip-test": cmd_roundtrip_test, "upload-l159": cmd_upload_l159}[a.cmd]
        return asyncio.run(fn(a))


if __name__ == "__main__":
    sys.exit(main())
