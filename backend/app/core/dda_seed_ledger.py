"""DDA 시드 이력 장부(ledger) — 업로드(릴리스)마다 레벨별 DDA 시드 4열 값·순서를 파일로 남기고 비교한다.

목적(2026-11-02 사용자 요청): 패치마다 레벨별 DDA 시드 순서·값이 어떻게 바뀌었는지 나중에 알 수 있게.

저장 위치: backend/data/dda_seed_ledger/ (환경변수 DDA_SEED_LEDGER_DIR 로 바꿀 수 있음 — 테스트용)
  sessions/<id>.jsonl     업로드 1회(세션)의 기록 일지. 줄 단위 추가만 한다(header → row… → close).
  snapshots/<id>.json.gz  세션 마감 시 1회 생성되는 스냅샷(같은 이름이 있으면 실패 — 덮어쓰기 없음).
  index.jsonl             세션 열림/마감 이벤트 목록(추가만).
수정·삭제 API 는 없다. 파일 쓰기는 'a'(추가) 또는 'x'(새 파일 전용) 모드만 쓴다.

스냅샷 = 업로드 1회: id(UTC 시각 + 짧은 해시), 생성 시각, 메모/버전 태그, 대상 보드, 배치 id·이름,
행별 기록 {id, 보낸 4열 값(토큰 순서 그대로), 생략 열과 사유, 판정 근거 요약, map sha256, useTileCount,
무한 행 relabel 규칙·mapping, 업로드 직전 서버 값(strict 조회 결과), 업로드 후 재조회 값(마감 시, 있으면), 상태}.

종류(kind): upload(실제 업로드) / baseline(기준점 v0: 서버 읽기 또는 서버 원본 파일) / dryrun(가상 — 배치 기준 계획,
명시적으로 저장할 때만). 시뮬레이션·미리보기는 자동 기록하지 않는다.

게임 시드 잠금(sp_meowsgarden DdaRuntime.cs:458-462, :504-506, DdaStagePolicy.cs:60-65 확인): 잠금은 시드 '값'(Seed)을
저장하고 재시도·재시작 때 그 값으로 맵을 다시 만든다(DdaMapTransformer.cs:336 "A retry uses the saved seed VALUE,
never the current candidate index/list"). SeedIndex 는 분석 이벤트 dda_variant 표기(DdaRuntime.cs:678)에만 쓰인다.
→ 순서 변경은 진행 중 잠금을 깨지 않는다. 토큰 교체·삭제 후에도 이미 잠긴 유저는 옛 값으로 계속 플레이한다.
   맵이 바뀌면 잠긴 옛 시드가 새 맵에 적용된다(변환 실패 시 원본 맵·판정 동결, DdaRuntime.cs:508-512).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import dda_seed_catalog as _dda

SCHEMA = "dda_seed_ledger.v1"
SEED_FIELDS = _dda.EXPORT_SEED_FIELDS                    # (Easy2 −2, Easy −1, Hard +1, Hard2 +2)
FIELD_STEP = {"ddaEasy2Seeds": -2, "ddaEasySeeds": -1, "ddaHardSeeds": 1, "ddaHard2Seeds": 2}
GAME_SEED_COUNT = 3                                      # 게임은 앞 3개만 읽는다(DdaVariantCatalog.cs:39)
KINDS = ("upload", "baseline", "dryrun", "restore")
ROW_ID_RE = re.compile(r"^(level|infinity)_[1-9][0-9]*$")
_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")

LOCK_MODEL = {
    "stores": "value",
    "summary": "게임 DDA 잠금은 시드 '값'을 저장한다(인덱스 아님). 순서 변경은 진행 중 잠금을 깨지 않는다.",
    "notes": [
        "잠금 생성: index=Rand(0,2) 로 고른 seeds[index] 의 값을 l.Seed 에 저장 (DdaRuntime.cs:439,458-462)",
        "재시도·재시작: 저장된 l.Seed 값으로 맵 재생성, 현재 목록·인덱스 미사용 (DdaRuntime.cs:504-506, DdaMapTransformer.cs:336-338)",
        "SeedIndex 는 분석 이벤트 dda_variant=\"<index>_<seed>\" 표기에만 쓰임 (DdaRuntime.cs:678) — 순서가 바뀌면 같은 index 가 다른 값을 가리키므로 패치 전후 index 집계는 값으로 맞춰 봐야 함",
        "토큰 교체·삭제: 이미 잠긴 유저는 서버에서 빠진 옛 값으로 계속 플레이 → 옛 값 기록이 필요(이 장부)",
        "맵 변경: 잠긴 옛 시드가 새 맵에 적용됨(검증 안 된 조합). 변환 실패 시 원본 맵으로 플레이·판정 동결 (DdaRuntime.cs:508-512)",
    ],
}

_lock = threading.Lock()
_auto_sessions: Dict[Tuple[str, str], str] = {}


class LedgerError(Exception):
    pass


# ── 경로 ─────────────────────────────────────────────────────────────────────────
def ledger_dir() -> str:
    d = os.environ.get("DDA_SEED_LEDGER_DIR")
    if d:
        return d
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "dda_seed_ledger"))


def _p(*parts: str) -> str:
    return os.path.join(ledger_dir(), *parts)


def _ensure_dirs() -> None:
    os.makedirs(_p("sessions"), exist_ok=True)
    os.makedirs(_p("snapshots"), exist_ok=True)


def _check_id(sid: str) -> str:
    if not isinstance(sid, str) or not _ID_RE.match(sid):
        raise LedgerError(f"invalid snapshot id: {sid!r}")
    return sid


def _now() -> Tuple[float, str]:
    t = time.time()
    return t, datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(t: Optional[float] = None) -> str:
    t = time.time() if t is None else t
    stamp = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{t}:{secrets.token_hex(8)}".encode()).hexdigest()[:6]
    return f"{stamp}-{h}"


def _dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def _append_line(path: str, obj: Dict[str, Any]) -> None:
    line = _dumps(obj) + "\n"
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                out.append({"type": "corrupt_line"})      # 쓰다 끊긴 마지막 줄 등 — 건너뜀
    return out


# ── 값 정규화·근거 요약 ──────────────────────────────────────────────────────────
def norm_value(v: Any) -> Optional[str]:
    """시드 열 값 → 비교용 문자열. None = 값 모름(키 없음). "" = 빈 값."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return _dda._norm(v)


def tokens(v: Optional[str]) -> List[str]:
    if not v:
        return []
    return [t.strip() for t in str(v).split(",") if t.strip() != ""]


def seed_cols(row: Any) -> Dict[str, Optional[str]]:
    """서버/레벨 행 dict → 4열 값(키가 없으면 None)."""
    if not isinstance(row, dict):
        return {}
    return {f: (norm_value(row.get(f)) if f in row else None) for f in SEED_FIELDS}


def server_map_sha(m: Any) -> Optional[str]:
    return _dda._server_map_sha(m) if m is not None else None


def evidence_summary(level_json: Dict[str, Any], row_id: str, sent: Dict[str, str],
                     field_evidence: Dict[str, str]) -> Dict[str, Any]:
    """열별 판정 근거 요약: 상태 + 게임이 쓰는 앞 3개 토큰의 verdict 항목(seed·verdict·nodes·source·판정기 정보)."""
    ev = None
    if isinstance(level_json, dict):
        if (row_id or "").startswith("infinity_"):
            src = level_json.get(_dda.INFINITY_SEEDS_KEY)
            ent = src.get(row_id) if isinstance(src, dict) else None
            ev = ent.get(_dda.SEED_EVIDENCE_KEY) if isinstance(ent, dict) else None
        else:
            ev = level_json.get(_dda.SEED_EVIDENCE_KEY)
    out: Dict[str, Any] = {}
    binding = ev.get("binding") if isinstance(ev, dict) else None
    if isinstance(binding, dict):
        out["binding"] = {k: binding.get(k) for k in ("mapSha256", "useTileCount") if k in binding}
    for f in SEED_FIELDS:
        st = (field_evidence or {}).get(f)
        val = sent.get(f)
        if st is None and val is None:
            continue
        toks = tokens(val)[:GAME_SEED_COUNT]
        lst = ev.get(f) if isinstance(ev, dict) else None
        per = []
        for t in toks:
            hit = None
            if isinstance(lst, list):
                for x in lst:
                    if isinstance(x, dict) and str(x.get("seed")) == t:
                        hit = {k: v for k, v in x.items() if isinstance(v, (str, int, float, bool)) or v is None}
                        if hit.get("verdict") in _dda.SEED_PASS_VERDICTS:
                            break
            per.append(hit or {"seed": t, "verdict": None})
        out[f] = {"status": st or "none", "tokens": per}
    return out


def build_row_record(*, row_id: str, source: str, status: str, payload: Optional[Dict[str, Any]],
                     level_json: Optional[Dict[str, Any]] = None, field_reasons: Optional[Dict[str, str]] = None,
                     field_evidence: Optional[Dict[str, str]] = None, dropped: Optional[Dict[str, str]] = None,
                     relabel: Optional[Dict[str, Any]] = None, server_before: Any = "unknown",
                     message: str = "") -> Dict[str, Any]:
    """업로드 1행 기록. payload = 실제 전송한(또는 전송하려던) 변환 행. server_before = strict 조회 행 dict /
    None(서버에 행 없음) / "unknown"(조회 안 함·실패)."""
    payload = payload if isinstance(payload, dict) else {}
    sent = {f: payload[f] for f in SEED_FIELDS if f in payload}
    omitted: Dict[str, str] = {}
    for f in SEED_FIELDS:
        if f in sent:
            continue
        if dropped and f in dropped:
            omitted[f] = "evidence_gate:" + str(dropped[f])
        elif field_reasons and f in field_reasons:
            omitted[f] = str(field_reasons[f])
        else:
            omitted[f] = "not_in_payload"
    rec: Dict[str, Any] = {
        "id": row_id, "source": source, "status": status, "at": _now()[1],
        "sent": sent, "omitted": omitted,
        "mapSha256": server_map_sha(payload["map"]) if "map" in payload else None,
        # [되돌리기 준비] 이번 전송이 덮어쓴 열 목록(etime 제외 — 서버가 갱신)
        "payloadKeys": sorted(k for k in payload.keys() if k != "etime"),
        "useTileCount": payload.get("useTileCount"),
        "evidence": evidence_summary(level_json or {}, row_id, sent, field_evidence or {}),
        "relabel": relabel or None,
    }
    if server_before == "unknown":
        rec["serverBefore"] = None
    elif server_before is None:
        rec["serverBefore"] = {"exists": False}
    elif isinstance(server_before, dict):
        rec["serverBefore"] = {"exists": True, "seeds": seed_cols(server_before),
                               "mapSha256": server_map_sha(server_before.get("map")),
                               "useTileCount": server_before.get("useTileCount")}
        # [되돌리기 준비] 업로드 직전 strict 조회 행 전체(맵·useTileCount·시드 등 모든 열) — 복원 기준
        rec["serverBeforeRow"] = json.loads(json.dumps(server_before, ensure_ascii=False, default=str))
    if message:
        rec["message"] = str(message)[:500]
    return rec


# ── 세션(업로드 1회) ──────────────────────────────────────────────────────────────
def open_session(*, kind: str = "upload", board: str = _dda.DDA_BOARD_ID, memo: str = "", tag: str = "",
                 batch_id: str = "", batch_name: str = "", source: str = "", options: Optional[Dict[str, Any]] = None,
                 auto: bool = False) -> Dict[str, Any]:
    if kind not in KINDS:
        raise LedgerError(f"invalid kind: {kind}")
    _ensure_dirs()
    t, iso = _now()
    sid = new_id(t)
    path = _p("sessions", sid + ".jsonl")
    hdr = {"type": "header", "schema": SCHEMA, "id": sid, "kind": kind, "createdAt": iso, "board": board,
           "memo": memo or "", "tag": tag or "", "batchId": batch_id or "", "batchName": batch_name or "",
           "source": source or "", "options": options or {}, "auto": bool(auto)}
    with _lock:
        with open(path, "x", encoding="utf-8") as f:     # 새 파일 전용
            f.write(_dumps(hdr) + "\n")
    _append_line(_p("index.jsonl"), {"event": "opened", "id": sid, "kind": kind, "createdAt": iso, "board": board,
                                     "memo": hdr["memo"], "tag": hdr["tag"], "batchId": hdr["batchId"],
                                     "batchName": hdr["batchName"], "source": hdr["source"], "auto": bool(auto)})
    return hdr


def auto_session(board: str, source: str) -> str:
    """세션 id 없이 들어온 업로드(다른 화면·옛 클라이언트) 기록용 — 프로세스·날짜·보드·경로당 1개."""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = (day, f"{board}|{source}")
    sid = _auto_sessions.get(key)
    if sid and os.path.exists(_p("sessions", sid + ".jsonl")) and not _is_closed(sid):
        return sid
    hdr = open_session(kind="upload", board=board, memo="(자동 — 세션 없이 들어온 업로드)", source=source, auto=True)
    _auto_sessions[key] = hdr["id"]
    return hdr["id"]


def _is_closed(sid: str) -> bool:
    return os.path.exists(_p("snapshots", sid + ".json.gz"))


def append_row(sid: str, rec: Dict[str, Any]) -> None:
    _check_id(sid)
    path = _p("sessions", sid + ".jsonl")
    if not os.path.exists(path):
        raise LedgerError(f"no such session: {sid}")
    if _is_closed(sid):
        raise LedgerError(f"session already finalized: {sid}")
    _append_line(path, {"type": "row", **rec})


def append_note(sid: str, note: Dict[str, Any]) -> None:
    _check_id(sid)
    path = _p("sessions", sid + ".jsonl")
    if not os.path.exists(path):
        raise LedgerError(f"no such session: {sid}")
    if _is_closed(sid):
        raise LedgerError(f"session already finalized: {sid}")
    _append_line(path, {"type": "note", "at": _now()[1], **note})


def _fold_session(sid: str) -> Dict[str, Any]:
    lines = _read_jsonl(_p("sessions", sid + ".jsonl"))
    if not lines or lines[0].get("type") != "header":
        raise LedgerError(f"session header missing: {sid}")
    hdr = dict(lines[0])
    hdr.pop("type", None)
    rows: Dict[str, Dict[str, Any]] = {}
    notes = []
    close = None
    for ln in lines[1:]:
        ty = ln.get("type")
        if ty == "row":
            r = dict(ln)
            r.pop("type", None)
            prev = rows.get(r["id"])
            r["attempts"] = (prev.get("attempts", 1) + 1) if prev else 1
            if prev and prev.get("status") != r.get("status"):
                r["previousStatus"] = prev.get("status")
            if prev and prev.get("serverBefore") and r.get("status") == "sent" and prev.get("status") != "sent":
                r.setdefault("serverBefore", prev.get("serverBefore"))
            rows[r["id"]] = r
        elif ty == "note":
            notes.append({k: v for k, v in ln.items() if k != "type"})
        elif ty == "readback":
            for rid, after in (ln.get("rows") or {}).items():
                if rid in rows:
                    rows[rid]["serverAfter"] = after
            hdr["readback"] = {k: v for k, v in ln.items() if k not in ("type", "rows")}
        elif ty == "close":
            close = ln
    doc = {**hdr, "status": "finalized" if close else "open", "rows": rows, "notes": notes}
    if close:
        doc["finalizedAt"] = close.get("at")
        doc["clientCounts"] = close.get("clientCounts") or {}
    return doc


def _counts(rows: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    c: Dict[str, int] = {}
    for r in rows.values():
        c[r.get("status", "?")] = c.get(r.get("status", "?"), 0) + 1
    c["total"] = len(rows)
    return c


def rows_sha256(rows: Dict[str, Dict[str, Any]]) -> str:
    """스냅샷 행 내용 해시(시드 값·맵 sha 등 비교 핵심만, 기록 시각 제외)."""
    core = {}
    for rid in sorted(rows):
        r = rows[rid]
        core[rid] = {"status": r.get("status"), "seeds": effective_seeds(r), "mapSha256": effective_map_sha(r)}
    return hashlib.sha256(_dumps(core).encode()).hexdigest()


def readback_from_rows(server_rows: Dict[str, Any], ids: Iterable[str]) -> Dict[str, Any]:
    out = {}
    for rid in ids:
        sr = server_rows.get(rid)
        if isinstance(sr, dict):
            out[rid] = {"exists": True, "seeds": seed_cols(sr), "mapSha256": server_map_sha(sr.get("map")),
                        "useTileCount": sr.get("useTileCount"), "etime": sr.get("etime")}
        else:
            out[rid] = {"exists": False}
    return out


def append_readback(sid: str, rows_after: Dict[str, Any], meta: Dict[str, Any]) -> None:
    _check_id(sid)
    if _is_closed(sid):
        raise LedgerError(f"session already finalized: {sid}")
    _append_line(_p("sessions", sid + ".jsonl"), {"type": "readback", "at": _now()[1], **meta, "rows": rows_after})


PER_ROW_READBACK_MAX = 50


async def readback_session(client: Any, sid: str) -> Dict[str, Any]:
    """업로드 후 재조회(읽기만): 행이 적으면 행별 조회, 많으면 보드 전체 1회 조회. 실패해도 예외 없이 결과만 남긴다."""
    doc = _fold_session(sid)
    ids = [rid for rid, r in doc["rows"].items() if r.get("status") in ("sent", "failed", "unchanged", "blocked")]
    meta: Dict[str, Any] = {"ok": False, "rows": len(ids)}
    if not ids:
        meta.update({"ok": True, "method": "none"})
        return meta
    if not getattr(client, "is_configured", False):
        meta["error"] = "client_not_configured"
        append_readback(sid, {}, meta)
        return meta
    try:
        if len(ids) <= PER_ROW_READBACK_MAX:
            srv = {}
            for rid in ids:
                got = await client.load_level(doc.get("board") or _dda.DDA_BOARD_ID, rid, strict=True)
                srv[rid] = got.get("level_json") if got else None
            meta["method"] = "per_row_strict"
        else:
            board = await client.load_board_rows(doc.get("board") or _dda.DDA_BOARD_ID)
            srv = board.get("rows") or {}
            meta.update({"method": "board", "rawSha256": board.get("raw_sha256"), "rawBytes": board.get("raw_bytes")})
        after = readback_from_rows(srv, ids)
        meta["ok"] = True
        append_readback(sid, after, meta)
    except Exception as e:                                # 조회 실패 — 업로드 결과에는 영향 없음
        meta["error"] = f"{type(e).__name__}: {e}"[:300]
        append_readback(sid, {}, meta)
    return meta


def finalize(sid: str, client_counts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """세션 마감: close 줄 추가 + 스냅샷 gz 생성('x' 모드 — 이미 있으면 실패) + 인덱스 이벤트."""
    _check_id(sid)
    if _is_closed(sid):
        raise LedgerError(f"session already finalized: {sid}")
    _append_line(_p("sessions", sid + ".jsonl"), {"type": "close", "at": _now()[1], "clientCounts": client_counts or {}})
    doc = _fold_session(sid)
    doc["counts"] = _counts(doc["rows"])
    doc["rowsSha256"] = rows_sha256(doc["rows"])
    data = gzip.compress(_dumps(doc).encode("utf-8"), mtime=0)
    with _lock:
        with open(_p("snapshots", sid + ".json.gz"), "xb") as f:
            f.write(data)
    _append_line(_p("index.jsonl"), {"event": "finalized", "id": sid, "kind": doc["kind"], "createdAt": doc["createdAt"],
                                     "finalizedAt": doc.get("finalizedAt"), "board": doc["board"], "memo": doc["memo"],
                                     "tag": doc["tag"], "batchId": doc["batchId"], "batchName": doc["batchName"],
                                     "source": doc.get("source", ""), "counts": doc["counts"],
                                     "rowsSha256": doc["rowsSha256"], "fileSha256": hashlib.sha256(data).hexdigest(),
                                     "auto": doc.get("auto", False)})
    return summary(doc)


def summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: doc.get(k) for k in ("id", "kind", "status", "createdAt", "finalizedAt", "board", "memo", "tag",
                                    "batchId", "batchName", "source", "auto", "readback")} | {
        "counts": doc.get("counts") or _counts(doc.get("rows") or {}),
        "rowsSha256": doc.get("rowsSha256") or rows_sha256(doc.get("rows") or {})}


def create_snapshot(*, kind: str, rows: Dict[str, Dict[str, Any]], memo: str = "", tag: str = "", board: str = "levels",
                    batch_id: str = "", batch_name: str = "", source: str = "",
                    options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """한 번에 만드는 스냅샷(기준점·가상). 세션 일지에 같은 내용을 남기고 바로 마감한다."""
    hdr = open_session(kind=kind, board=board, memo=memo, tag=tag, batch_id=batch_id, batch_name=batch_name,
                       source=source, options=options)
    sid = hdr["id"]
    path = _p("sessions", sid + ".jsonl")
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            for rid in sorted(rows, key=row_sort_key):
                f.write(_dumps({"type": "row", **rows[rid]}) + "\n")
    return finalize(sid)


# ── 읽기 ─────────────────────────────────────────────────────────────────────────
def load(sid: str) -> Dict[str, Any]:
    _check_id(sid)
    gz = _p("snapshots", sid + ".json.gz")
    if os.path.exists(gz):
        with open(gz, "rb") as f:
            return json.loads(gzip.decompress(f.read()).decode("utf-8"))
    if os.path.exists(_p("sessions", sid + ".jsonl")):
        return _fold_session(sid)
    raise LedgerError(f"no such snapshot: {sid}")


def list_snapshots(include_dryrun: bool = True) -> List[Dict[str, Any]]:
    """인덱스 + 세션 파일로 목록(오래된 → 최신). 열린 세션은 일지에서 집계."""
    _ensure_dirs()
    by: Dict[str, Dict[str, Any]] = {}
    for ev in _read_jsonl(_p("index.jsonl")):
        sid = ev.get("id")
        if not sid:
            continue
        cur = by.setdefault(sid, {})
        cur.update({k: v for k, v in ev.items() if k != "event"})
        cur["status"] = "finalized" if ev.get("event") == "finalized" else cur.get("status", "open")
    for fn in os.listdir(_p("sessions")):
        if fn.endswith(".jsonl"):
            sid = fn[:-6]
            if sid not in by and _ID_RE.match(sid):
                by[sid] = {"id": sid, "status": "open", "note": "index_missing"}
    out = []
    for sid, s in by.items():
        if s.get("status") != "finalized":
            try:
                s = summary(_fold_session(sid))
            except (LedgerError, OSError):
                continue
        if not include_dryrun and s.get("kind") == "dryrun":
            continue
        out.append(s)
    out.sort(key=lambda s: (s.get("createdAt") or "", s.get("id")))
    return out


def row_sort_key(rid: str) -> Tuple[int, int]:
    m = ROW_ID_RE.match(rid or "")
    if not m:
        return (9, 0)
    return (0 if m.group(1) == "level" else 1, int(rid.split("_")[1]))


# ── 행의 '유효 값' (비교 기준) ─────────────────────────────────────────────────────
def effective_seeds(r: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """그 스냅샷 시점에 서버에 있는(있었을) 값. 우선순위: 업로드 후 재조회 > 전송 성공 값 > 업로드 직전 서버 값.
    None = 알 수 없음(예: 실패 행에 직전 조회 값도 없음)."""
    after = r.get("serverAfter") or {}
    if after.get("exists"):
        return dict(after.get("seeds") or {})
    if after and after.get("exists") is False:
        return {f: None for f in SEED_FIELDS}
    before = (r.get("serverBefore") or {})
    bseeds = before.get("seeds") or {}
    out = {}
    for f in SEED_FIELDS:
        if r.get("status") in ("sent", "baseline", "planned") and f in (r.get("sent") or {}):
            out[f] = norm_value(r["sent"][f])
        elif before.get("exists"):
            out[f] = bseeds.get(f)
        elif before.get("exists") is False and r.get("status") in ("sent", "planned"):
            out[f] = ""                                   # 새 행: 보내지 않은 열은 빈 값
        else:
            out[f] = None
    return out


def effective_map_sha(r: Dict[str, Any]) -> Optional[str]:
    after = r.get("serverAfter") or {}
    if after.get("exists") and after.get("mapSha256"):
        return after["mapSha256"]
    if r.get("status") in ("sent", "baseline", "planned") and r.get("mapSha256"):
        return r["mapSha256"]
    return (r.get("serverBefore") or {}).get("mapSha256")


def effective_use_tile_count(r: Dict[str, Any]) -> Any:
    after = r.get("serverAfter") or {}
    if after.get("exists") and "useTileCount" in after:
        return after.get("useTileCount")
    if r.get("status") in ("sent", "baseline", "planned"):
        return r.get("useTileCount")
    return (r.get("serverBefore") or {}).get("useTileCount")


# ── 비교 ─────────────────────────────────────────────────────────────────────────
# 열 분류(class):
#   same       값 동일(둘 다 빈 값 포함)
#   reordered  토큰 구성 동일, 순서만 바뀜
#   replaced   토큰 개수 동일, 일부 토큰이 다른 값으로 바뀜(positions: 위치별 from→to)
#   added      토큰 개수 증가, 기존 토큰은 모두 유지(addedTokens)
#   removed    토큰 개수 감소, 남은 토큰은 모두 기존에 있던 것(removedTokens)
#   resized    개수 변화 + 교체가 함께 있음
#   filled     빈 값 → 값
#   cleared    값 → 빈 값
#   unknown    한쪽 값을 모름(행 없음·실패 행·조회 안 됨)
# 부가 플래그: gameChanged(게임이 읽는 앞 3개의 순서 목록이 다름), gameSetChanged(앞 3개 집합이 다름),
#             orderChanged(공통 토큰의 상대 순서가 다름).
# 행 분류: rowAdded / rowRemoved / mapChanged(map sha 다름 — 맵이 바뀌면 시드 의미도 바뀜) / useTileCountChanged.
CLASSES = ("same", "reordered", "replaced", "added", "removed", "resized", "filled", "cleared", "unknown")


def classify_field(a: Optional[str], b: Optional[str]) -> Dict[str, Any]:
    if a is None or b is None:
        return {"class": "unknown", "from": a, "to": b, "bothUnknown": a is None and b is None}
    ta, tb = tokens(a), tokens(b)
    res: Dict[str, Any] = {"from": a, "to": b}
    if ta == tb:
        res["class"] = "same"
        return res
    if not ta:
        res["class"] = "filled"
    elif not tb:
        res["class"] = "cleared"
    elif sorted(ta) == sorted(tb):
        res["class"] = "reordered"
    else:
        sa, sb = set(ta), set(tb)
        added = [t for t in tb if t not in sa]
        removed = [t for t in ta if t not in sb]
        if len(ta) == len(tb):
            res["class"] = "replaced"
        elif len(tb) > len(ta) and not removed:
            res["class"] = "added"
        elif len(tb) < len(ta) and not added:
            res["class"] = "removed"
        else:
            res["class"] = "resized"
        res["addedTokens"] = added
        res["removedTokens"] = removed
        res["positions"] = [{"pos": i, "from": ta[i] if i < len(ta) else None, "to": tb[i] if i < len(tb) else None}
                            for i in range(max(len(ta), len(tb)))
                            if (ta[i] if i < len(ta) else None) != (tb[i] if i < len(tb) else None)]
    common = [t for t in ta if t in set(tb)]
    res["orderChanged"] = common != [t for t in tb if t in set(ta)]
    ga, gb = ta[:GAME_SEED_COUNT], tb[:GAME_SEED_COUNT]
    res["gameChanged"] = ga != gb
    res["gameSetChanged"] = set(ga) != set(gb)
    return res


def _lock_notes(fields: Dict[str, Dict[str, Any]], map_changed: bool) -> List[str]:
    notes = []
    cls = {v["class"] for v in fields.values()}
    if "reordered" in cls or any(v.get("orderChanged") for v in fields.values()):
        notes.append("order_only_safe: 잠금은 값 저장 — 진행 중 유저 영향 없음(dda_variant index 의미만 바뀜)")
    if cls & {"replaced", "removed", "resized", "cleared"}:
        notes.append("locked_old_values: 이미 잠긴 유저는 빠진 옛 시드값으로 계속 플레이")
    if map_changed and any((v.get("from") or v.get("to")) for v in fields.values()):
        notes.append("map_changed_with_seeds: 잠긴 옛 시드가 새 맵에 적용(미검증 조합 가능)")
    return notes


def diff_rows(rows_a: Dict[str, Dict[str, Any]], rows_b: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for rid in sorted(set(rows_a) | set(rows_b), key=row_sort_key):
        ra, rb = rows_a.get(rid), rows_b.get(rid)
        ea = effective_seeds(ra) if ra else {f: None for f in SEED_FIELDS}
        eb = effective_seeds(rb) if rb else {f: None for f in SEED_FIELDS}
        fields = {f: classify_field(ea.get(f), eb.get(f)) for f in SEED_FIELDS}
        ma, mb = (effective_map_sha(ra) if ra else None), (effective_map_sha(rb) if rb else None)
        ua, ub = (effective_use_tile_count(ra) if ra else None), (effective_use_tile_count(rb) if rb else None)
        map_changed = bool(ma and mb and ma != mb)
        utc_changed = ua is not None and ub is not None and str(ua) != str(ub)
        changed = any(v["class"] != "same" and not v.get("bothUnknown") for v in fields.values()) \
            or map_changed or utc_changed \
            or (ra is None) != (rb is None)
        out.append({
            "id": rid, "changed": changed,
            "rowAdded": ra is None and rb is not None, "rowRemoved": rb is None and ra is not None,
            "statusA": ra.get("status") if ra else None, "statusB": rb.get("status") if rb else None,
            "mapShaA": ma, "mapShaB": mb, "mapChanged": map_changed,
            "useTileCountA": ua, "useTileCountB": ub, "useTileCountChanged": utc_changed,
            "fields": fields, "lockNotes": _lock_notes(fields, map_changed),
        })
    return out


def diff_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_class = {f: {c: 0 for c in CLASSES} for f in SEED_FIELDS}
    s = {"rows": len(items), "changedRows": 0, "rowAdded": 0, "rowRemoved": 0, "mapChanged": 0,
         "useTileCountChanged": 0, "gameChanged": 0, "byField": by_class}
    for it in items:
        s["changedRows"] += it["changed"]
        s["rowAdded"] += it["rowAdded"]
        s["rowRemoved"] += it["rowRemoved"]
        s["mapChanged"] += it["mapChanged"]
        s["useTileCountChanged"] += it["useTileCountChanged"]
        s["gameChanged"] += any(v.get("gameChanged") for v in it["fields"].values())
        for f, v in it["fields"].items():
            by_class[f][v["class"]] += 1
    return s


def diff_snapshots(doc_a: Dict[str, Any], doc_b: Dict[str, Any], q: str = "", only_changed: bool = True,
                   klass: str = "") -> Dict[str, Any]:
    items = diff_rows(doc_a.get("rows") or {}, doc_b.get("rows") or {})
    summ = diff_summary(items)
    sel = filter_items(items, q=q, only_changed=only_changed, klass=klass)
    return {"a": summary(doc_a), "b": summary(doc_b), "summary": summ, "items": sel, "lockModel": LOCK_MODEL}


def filter_items(items: List[Dict[str, Any]], q: str = "", only_changed: bool = True, klass: str = "") -> List[Dict[str, Any]]:
    out = []
    ids = parse_level_query(q)
    for it in items:
        if only_changed and not it["changed"]:
            continue
        if ids is not None and it["id"] not in ids:
            continue
        if klass:
            if klass == "mapChanged":
                if not it["mapChanged"]:
                    continue
            elif klass in ("rowAdded", "rowRemoved", "useTileCountChanged", "gameChanged"):
                if klass == "gameChanged":
                    if not any(v.get("gameChanged") for v in it["fields"].values()):
                        continue
                elif not it[klass]:
                    continue
            elif not any(v["class"] == klass for v in it["fields"].values()):
                continue
        out.append(it)
    return out


def parse_level_query(q: str) -> Optional[set]:
    """'level_5', '5', '1-20', 'infinity_3', 'i3', '5,7,100-110' → id 집합. 빈 값이면 None(전체)."""
    q = (q or "").strip()
    if not q:
        return None
    ids = set()
    for part in re.split(r"[,\s]+", q):
        if not part:
            continue
        pre = "level_"
        p = part
        if p.startswith("infinity_"):
            pre, p = "infinity_", p[len("infinity_"):]
        elif p.startswith("level_"):
            p = p[len("level_"):]
        elif p[:1] in ("i", "I") and p[1:2].isdigit():
            pre, p = "infinity_", p[1:]
        m = re.match(r"^([0-9]+)(?:-([0-9]+))?$", p)
        if not m:
            ids.add(part)
            continue
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        for n in range(lo, min(hi, lo + 5000) + 1):
            ids.add(f"{pre}{n}")
    return ids


def diff_csv(items: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "field", "step", "class", "from", "to", "gameChanged", "orderChanged", "positions",
                "addedTokens", "removedTokens", "rowAdded", "rowRemoved", "mapChanged", "mapShaA", "mapShaB",
                "useTileCountA", "useTileCountB", "statusA", "statusB", "lockNotes"])
    for it in items:
        for f in SEED_FIELDS:
            v = it["fields"][f]
            if (v["class"] == "same" or v.get("bothUnknown")) and not it["mapChanged"] and not it["rowAdded"] and not it["rowRemoved"] \
                    and not it["useTileCountChanged"]:
                continue
            w.writerow([it["id"], f, FIELD_STEP[f], v["class"], v.get("from") if v.get("from") is not None else "(unknown)",
                        v.get("to") if v.get("to") is not None else "(unknown)", int(bool(v.get("gameChanged"))),
                        int(bool(v.get("orderChanged"))),
                        ";".join(f"{p['pos']}:{p['from']}->{p['to']}" for p in v.get("positions") or []),
                        ";".join(v.get("addedTokens") or []), ";".join(v.get("removedTokens") or []),
                        int(it["rowAdded"]), int(it["rowRemoved"]), int(it["mapChanged"]), it["mapShaA"] or "",
                        it["mapShaB"] or "", "" if it["useTileCountA"] is None else it["useTileCountA"],
                        "" if it["useTileCountB"] is None else it["useTileCountB"], it["statusA"] or "",
                        it["statusB"] or "", " | ".join(it["lockNotes"])])
    return buf.getvalue()


def timeline(row_id: str, include_dryrun: bool = False) -> Dict[str, Any]:
    """한 레벨의 스냅샷별 시드 변천(오래된 → 최신). 직전 등장과의 열 분류 포함."""
    out = []
    prev = None
    for s in list_snapshots(include_dryrun=include_dryrun):
        try:
            doc = load(s["id"])
        except (LedgerError, OSError, ValueError):
            continue
        r = (doc.get("rows") or {}).get(row_id)
        if not r:
            continue
        e = {"snapshot": summary(doc), "status": r.get("status"), "seeds": effective_seeds(r),
             "sent": r.get("sent"), "omitted": r.get("omitted"), "mapSha256": effective_map_sha(r),
             "useTileCount": effective_use_tile_count(r), "relabel": r.get("relabel"),
             "evidence": r.get("evidence"), "serverBefore": r.get("serverBefore"), "serverAfter": r.get("serverAfter"),
             "message": r.get("message")}
        if prev is not None:
            e["changeFromPrev"] = {f: classify_field(prev["seeds"].get(f), e["seeds"].get(f)) for f in SEED_FIELDS}
            e["mapChangedFromPrev"] = bool(prev["mapSha256"] and e["mapSha256"] and prev["mapSha256"] != e["mapSha256"])
        out.append(e)
        prev = e
    return {"id": row_id, "entries": out, "lockModel": LOCK_MODEL}


# ── 기준점(v0) — 서버 행(읽기 결과) → 스냅샷 행 ──────────────────────────────────────
def rows_from_server_board(server_rows: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    _, iso = _now()
    for rid, row in server_rows.items():
        if not ROW_ID_RE.match(str(rid)) or not isinstance(row, dict):
            continue
        seeds = seed_cols(row)
        out[rid] = {"id": rid, "source": "server_readback", "status": "baseline", "at": iso,
                    "sent": {f: v for f, v in seeds.items() if v is not None}, "omitted": {
                        f: "column_absent" for f, v in seeds.items() if v is None},
                    "mapSha256": server_map_sha(row.get("map")), "useTileCount": row.get("useTileCount"),
                    "etime": row.get("etime"), "evidence": {}, "relabel": None, "serverBefore": None}
    return out


def parse_raw_board(raw: Dict[str, Any]) -> Dict[str, Any]:
    """real_array load 원문({__keys, __vals}) → {id: row}. app.clients.gboost.parse_gboost_response 와 같은 결과."""
    from ..clients.gboost import parse_gboost_response
    return parse_gboost_response(raw)


def baseline_from_raw_file(path: str, *, memo: str = "", tag: str = "v0") -> Dict[str, Any]:
    with open(path, "rb") as f:
        data = f.read()
    raw = json.loads(data)
    rows = rows_from_server_board(parse_raw_board(raw))
    return create_snapshot(kind="baseline", rows=rows, memo=memo or f"기준점 — 서버 원본 파일 {os.path.basename(path)}",
                           tag=tag, source="raw_file", options={"path": path,
                                                                 "fileSha256": hashlib.sha256(data).hexdigest(),
                                                                 "fileBytes": len(data)})
