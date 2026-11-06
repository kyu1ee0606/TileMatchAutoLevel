"""라이브 levels 보드 전체 백업 + 복원(되돌리기) 계획·실행 (2026-11-02 사용자 지시 "되돌리기 준비").

■ 전체 백업 (주 경로)
  GameBoost levels 보드 전체를 '읽기만' 해서(GBoostClient.load_board_rows — real_array act=load id= 1회, strict)
  응답 원문 그대로({__keys, __vals}) 백엔드 파일로 저장한다. 정식·무한·test 등 보드에 있는 행 전부.
  backend/data/live_backup/ (환경변수 LIVE_BACKUP_DIR 로 변경 가능 — 테스트용)
    levels_<UTC시각>_<짧은해시>.json.gz   {schema, id, board, createdAt, memo, source, raw:{__keys,__vals,...},
                                           rawSha256, rawBytes, rows, complete, problems}
    index.jsonl                           백업 이벤트(추가만). 삭제·수정 API 없음. 파일은 'x' 모드(새 파일 전용).
  '불완전 백업' = 열 개수가 __keys 와 다른 행·id 없는 행·같은 id 중복 행이 있을 때(그 행은 복원 기준에서 빠짐).
  파일 가져오기(import_raw_file): 예전 readback 원문(예 10-28 levels.raw.json)도 백업으로 등록할 수 있다(source=file,
  stale 경고 — 그 뒤 서버 변경분을 덮어쓸 위험).

■ 복원 = 미리보기 → 확인 → 실행 (2단계, 실행은 사람만)
  기준(base): 전체 백업 1개 또는 장부 업로드 스냅샷의 '업로드 직전 행 전체'(serverBeforeRow).
  범위(scope): 전체 열 / 장부 업로드 스냅샷이 실제로 덮어쓴 열(payloadKeys)만 / 레벨 id 필터.
  미리보기: 현재 서버 보드(읽기 1회)와 비교해 base 와 값이 다른 열만 모은 행별 payload 를 만들고 파일로 저장
            (restore_plans/<plan_id>.json.gz, 'x' 모드). 실행엔 plan_id + planDigest + confirm_text="복원" 필요.
  실행: 행마다 strict 재조회 → 미리보기 때 현재 값과 다르면 그 행 차단(server_changed_since_preview) →
        update_existing_level(new=0 1회, '<id>=upt' 확인, new=1 폴백 없음) → strict 재조회로 검증.
        실행 기록은 시드 장부에 kind="restore" 스냅샷으로 남는다.

■ 값 표현 (GBoostClient 동작·dda_seed_catalog.READBACK_RULES 실측 근거)
  - 보내지 않은 열 = 서버 기존 값 유지(READBACK_RULES "unsent", 10-28 시드만 2,262행 전송 무변경) → 바뀐 열만 보낸다.
  - 열 삭제 API 없음: 보드는 고정 열(__keys) 배열 형식이라 모든 행이 모든 열을 가진다('열이 없음' = null/"" 값).
  - "" → "" (empty_string 실측) / 정수 → 정수 문자열로 보냄(numeric_string 실측) / map 객체 → 같은 객체 /
    시드 문자열 → 같은 문자열 / backgroundIndex·tileSkin 의 null ← "0" / rewardList 의 null ← "[]" /
    useInRandomizer·useTeleportInRandomizer 의 0 ← "0".
  - 그 밖의 null·실수·불리언·비어있지 않은 목록 등 = 표현 미확인 → 'unverified' 로 표시, 기본 제외(allow_unverified 로만).
  - 행 삭제(업로드로 새로 생긴 행)는 하지 않는다: delete_level 은 new=1 + null 저장이라 동작 미확인 → 수동 처리 목록.
  - 시드 '빈 값 금지' 규칙과의 관계: 일반 업로드의 시드 게이트(export_fields·evidence_gate·write_guard)는 '새로 정하는
    시드'를 막는 규칙이다. 복원은 서버가 예전에 실제로 갖고 있던 값(빈 값 포함)으로 되돌리는 것이라 별도 경로
    (이 모듈)로 분리했다 — 업로드 경로 게이트는 그대로 둔다.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import dda_seed_catalog as _dda
from . import dda_seed_ledger as L

SCHEMA = "live_backup.v1"
PLAN_SCHEMA = "restore_plan.v1"
EXCLUDE_COLS = ("id", "idx", "etime", "")          # 서버 관리 열 · 파서가 버리는 빈 이름 열
CONFIRM_TEXT = "복원"
STALE_HOURS = 2.0                                  # 업로드 전 백업 권장 — 이보다 오래되면 경고(차단 안 함)
_ID_RE = re.compile(r"^levels_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{6}$|^[a-z0-9_]+_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{6}$")
_PLAN_RE = re.compile(r"^plan_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{6}$")
_lock = threading.Lock()


class BackupError(Exception):
    pass


# ── 경로 ─────────────────────────────────────────────────────────────────────────
def backup_dir() -> str:
    d = os.environ.get("LIVE_BACKUP_DIR")
    if d:
        return d
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "live_backup"))


def _p(*parts: str) -> str:
    return os.path.join(backup_dir(), *parts)


def _stamp(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _short(t: float) -> str:
    return hashlib.sha256(f"{t}:{secrets.token_hex(8)}".encode()).hexdigest()[:6]


def _dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def _append_index(ev: Dict[str, Any]) -> None:
    os.makedirs(backup_dir(), exist_ok=True)
    with _lock:
        with open(_p("index.jsonl"), "a", encoding="utf-8") as f:
            f.write(_dumps(ev) + "\n")


def _write_new_gz(path: str, obj: Any) -> str:
    data = gzip.compress(_dumps(obj).encode("utf-8"), mtime=0)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        with open(path, "xb") as f:                 # 새 파일 전용 — 덮어쓰기 없음
            f.write(data)
    return hashlib.sha256(data).hexdigest()


def _read_gz(path: str) -> Any:
    with open(path, "rb") as f:
        return json.loads(gzip.decompress(f.read()).decode("utf-8"))


# ── 원문 → 행 ────────────────────────────────────────────────────────────────────
def rows_from_raw(raw: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """{__keys, __vals} → ({id: row}, problems). parse_gboost_response 와 같은 규칙 + 문제 행 목록."""
    keys = raw.get("__keys") or []
    vals = raw.get("__vals") or []
    if not keys or not isinstance(vals, list):
        raise BackupError("unexpected format (no __keys/__vals)")
    idi = keys.index("id") if "id" in keys else 0
    rows: Dict[str, Dict[str, Any]] = {}
    problems: List[Dict[str, Any]] = []
    for n, v in enumerate(vals):
        if not isinstance(v, list) or len(v) != len(keys):
            problems.append({"index": n, "reason": "column_count", "id": v[idi] if isinstance(v, list) and len(v) > idi else None})
            continue
        rid = v[idi]
        if not rid:
            problems.append({"index": n, "reason": "no_id"})
            continue
        if rid in rows:
            problems.append({"index": n, "reason": "duplicate_id", "id": rid})
        rows[rid] = {k: v[i] for i, k in enumerate(keys) if k}
    dup = {p["id"] for p in problems if p["reason"] == "duplicate_id"}
    for rid in dup:                                  # 중복 id 는 어느 값이 맞는지 모름 → 복원 기준에서 뺀다
        rows.pop(rid, None)
    return rows, problems


def _save_backup(raw: Dict[str, Any], raw_bytes: bytes, *, board: str, memo: str, source: str,
                 extra: Optional[Dict[str, Any]] = None, t: Optional[float] = None) -> Dict[str, Any]:
    t = time.time() if t is None else t
    rows, problems = rows_from_raw(raw)
    bid = f"{board}_{_stamp(t)}_{_short(t)}"
    kinds: Dict[str, int] = {}
    for rid in rows:
        k = re.sub(r"[0-9]+", "N", str(rid))
        kinds[k] = kinds.get(k, 0) + 1
    doc = {"schema": SCHEMA, "id": bid, "board": board, "createdAt": _iso(t), "memo": memo or "", "source": source,
           "rawSha256": hashlib.sha256(raw_bytes).hexdigest(), "rawBytes": len(raw_bytes),
           "rowCount": len(rows), "rawRowCount": len(raw.get("__vals") or []), "rowKinds": kinds,
           "complete": not problems, "problems": problems[:200], "problemCount": len(problems),
           **(extra or {}), "raw": raw}
    path = _p(bid + ".json.gz")
    fsha = _write_new_gz(path, doc)
    summ = {k: v for k, v in doc.items() if k != "raw"}
    summ.update({"file": path, "fileSha256": fsha})
    _append_index({"event": "backup", **{k: v for k, v in summ.items() if k != "problems"}})
    return summ


async def take_backup(client: Any, board: str = _dda.DDA_BOARD_ID, memo: str = "",
                      progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """보드 전체 읽기(1회) → 파일 저장. 쓰기 없음. 실패는 BackupError."""
    if not getattr(client, "is_configured", False):
        raise BackupError("GBoost client not configured")
    progress and progress("reading")
    t0 = time.time()
    try:
        res = await client.load_board_rows(board)
    except Exception as e:  # noqa: BLE001
        raise BackupError(f"보드 읽기 실패: {type(e).__name__}: {e}") from e
    raw_bytes = res.get("raw")
    if raw_bytes is None:
        raw_bytes = _dumps({"__keys": res.get("keys"), "__vals": []}).encode()
    try:
        raw = json.loads(raw_bytes.decode("utf-8") if isinstance(raw_bytes, (bytes, bytearray)) else raw_bytes)
    except ValueError as e:
        raise BackupError(f"원문 JSON 해석 실패: {e}") from e
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8")
    progress and progress("saving")
    return _save_backup(raw, raw_bytes, board=board, memo=memo, source="server_read",
                        extra={"readSeconds": round(time.time() - t0, 2)})


def import_raw_file(path: str, memo: str = "", board: str = _dda.DDA_BOARD_ID) -> Dict[str, Any]:
    """예전 readback 원문 파일을 백업으로 등록(서버 호출 없음). stale 경고 대상."""
    with open(path, "rb") as f:
        data = f.read()
    raw = json.loads(data)
    mt = os.path.getmtime(path)
    return _save_backup(raw, data, board=board, memo=memo or f"파일 가져옴: {os.path.basename(path)}", source="file",
                        extra={"importedFrom": path, "fileMtime": _iso(mt)})


def list_backups() -> List[Dict[str, Any]]:
    out = []
    if os.path.exists(_p("index.jsonl")):
        with open(_p("index.jsonl"), encoding="utf-8") as f:
            for ln in f:
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue
                if ev.get("event") == "backup":
                    out.append({k: v for k, v in ev.items() if k != "event"})
    out.sort(key=lambda s: s.get("createdAt") or "")
    return out


def _check(bid: str) -> str:
    if not isinstance(bid, str) or not _ID_RE.match(bid):
        raise BackupError(f"invalid backup id: {bid!r}")
    return bid


def load_backup(bid: str) -> Dict[str, Any]:
    p = _p(_check(bid) + ".json.gz")
    if not os.path.exists(p):
        raise BackupError(f"no such backup: {bid}")
    doc = _read_gz(p)
    doc["rows"], _ = rows_from_raw(doc["raw"])
    return doc


def backup_status(now: Optional[float] = None) -> Dict[str, Any]:
    """업로드 버튼 옆 안내용: 마지막 '서버 읽기' 백업 시각·경과 시간·경고."""
    now = time.time() if now is None else now
    srv = [b for b in list_backups() if b.get("source") == "server_read"]
    if not srv:
        return {"last": None, "warn": "no_backup", "message": "라이브 전체 백업 없음 — 업로드 전 백업 권장"}
    last = srv[-1]
    t = datetime.strptime(last["createdAt"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    hours = (now - t) / 3600.0
    warn = None
    msg = f"마지막 백업 {last['createdAt'][:16].replace('T', ' ')} UTC ({hours:.1f}시간 전)"
    if not last.get("complete", True):
        warn, msg = "incomplete", msg + " — 불완전 백업"
    elif hours > STALE_HOURS:
        warn, msg = "stale", msg + f" — {STALE_HOURS:g}시간 넘음, 업로드 전 새 백업 권장"
    return {"last": last, "ageHours": round(hours, 2), "warn": warn, "message": msg}


# ── 복원 계획 ────────────────────────────────────────────────────────────────────
def encode_restore_value(col: str, v: Any) -> Tuple[Any, bool, str]:
    """서버에서 읽은 값 v 로 되돌리려면 보낼 값. (보낼 값, 표현 실측 여부, 근거/사유)."""
    if col == "map":
        if isinstance(v, dict):
            return v, True, "map 객체 → 같은 객체"
        return v, False, "map 이 객체가 아님(문자열/null) — 미확인"
    if col in _dda.EXPORT_SEED_FIELDS:
        if v is None:
            return "", False, "시드 null → \"\" 로 보내면 \"\" 로 읽힘(null 복원은 미확인)"
        if isinstance(v, str):
            return v, True, "시드 문자열 → 같은 문자열"
        return str(v), False, "시드가 문자열 아님 — 미확인"
    if v is None:
        if col in ("backgroundIndex", "tileSkin"):
            return "0", True, "\"0\" → null (실측)"
        if col == "rewardList":
            return "[]", True, "\"[]\" → null (실측)"
        return None, False, "null 복원 표현 미확인"
    if isinstance(v, bool):
        return v, False, "불리언 — 미확인"
    if isinstance(v, int):
        if col in ("backgroundIndex", "tileSkin"):
            return str(v), False, "backgroundIndex/tileSkin 정수 — \"0\"→null 만 실측"
        if col in ("useInRandomizer", "useTeleportInRandomizer") and v != 0:
            return str(v), False, "\"1\" 미확인"
        return str(v), True, "정수 문자열 → 정수 (실측)"
    if isinstance(v, float):
        return v, False, "실수 — 미확인"
    if isinstance(v, str):
        if v == "":
            return "", True, "\"\" → \"\" (실측)"
        if re.match(r"^-?[0-9]+$", v):
            return v, True, "정수 문자열 → 정수 (실측, 문자열로 저장돼 있던 값은 정수로 읽힐 수 있음)"
        if col == "rewardList":
            return v, False, "비어있지 않은 rewardList — 미확인"
        return v, False, "일반 문자열 — 미확인"
    return v, False, f"{type(v).__name__} — 미확인"


def same_value(a: Any, b: Any) -> bool:
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        sa = L.server_map_sha(a) if isinstance(a, (dict, str)) else None
        sb = L.server_map_sha(b) if isinstance(b, (dict, str)) else None
        if sa and sb:
            return sa == sb
    return _dda._norm(a) == _dda._norm(b)


def _digest(row: Optional[Dict[str, Any]], cols: List[str]) -> str:
    if row is None:
        return "absent"
    return hashlib.sha256(_dumps({c: row.get(c) for c in sorted(cols)}).encode()).hexdigest()


def base_from_backup(bid: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Optional[Dict[str, List[str]]]]:
    doc = load_backup(bid)
    meta = {"type": "backup", "id": bid, "createdAt": doc["createdAt"], "source": doc.get("source"),
            "memo": doc.get("memo"), "complete": doc.get("complete"), "rowCount": doc.get("rowCount"),
            "dataTime": doc.get("fileMtime") or doc["createdAt"]}
    return doc["rows"], meta, None


def base_from_snapshot(sid: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, List[str]]]:
    """장부 업로드 스냅샷 → (업로드 직전 행 전체, meta, 덮어쓴 열 scope). 업로드가 새로 만든 행은 base 없음 → created."""
    doc = L.load(sid)
    base: Dict[str, Dict[str, Any]] = {}
    scope: Dict[str, List[str]] = {}
    created: List[str] = []
    for rid, r in (doc.get("rows") or {}).items():
        if r.get("status") not in ("sent",):
            continue
        sb = r.get("serverBefore") or {}
        if sb.get("exists") is False:
            created.append(rid)
            continue
        if isinstance(r.get("serverBeforeRow"), dict):
            base[rid] = r["serverBeforeRow"]
            scope[rid] = [k for k in (r.get("payloadKeys") or []) if k not in EXCLUDE_COLS]
    meta = {"type": "snapshot", "id": sid, "createdAt": doc.get("createdAt"), "kind": doc.get("kind"),
            "memo": doc.get("memo"), "tag": doc.get("tag"), "createdRows": created,
            "rowsWithoutBefore": sum(1 for r in (doc.get("rows") or {}).values()
                                     if r.get("status") == "sent" and not isinstance(r.get("serverBeforeRow"), dict)
                                     and (r.get("serverBefore") or {}).get("exists") is not False)}
    return base, meta, scope


def scope_from_snapshot(sid: str) -> Dict[str, List[str]]:
    _, _, scope = base_from_snapshot(sid)
    return scope


def build_plan(base_rows: Dict[str, Dict[str, Any]], current_rows: Dict[str, Dict[str, Any]], *,
               scope: Optional[Dict[str, List[str]]] = None, ids: Optional[set] = None,
               columns: Optional[List[str]] = None) -> Dict[str, Any]:
    """base 값으로 되돌리는 행별 payload. scope 가 있으면 그 행·열만, 없으면 base 의 모든 열(EXCLUDE 제외)."""
    rows_out: List[Dict[str, Any]] = []
    missing, extra = [], []
    target_ids = set(scope.keys()) if scope is not None else set(base_rows.keys())
    if ids is not None:
        target_ids &= ids
    for rid in sorted(target_ids, key=_sort_key):
        b = base_rows.get(rid)
        if b is None:
            continue
        cur = current_rows.get(rid)
        cols = scope[rid] if scope is not None else [k for k in b.keys() if k not in EXCLUDE_COLS]
        if columns:
            cols = [c for c in cols if c in columns]
        if cur is None:
            missing.append(rid)                      # 서버에 지금 없는 행 — update 불가(new=1 생성은 하지 않음)
            continue
        changes = []
        for c in cols:
            if c not in b:
                continue
            if same_value(cur.get(c), b.get(c)):
                continue
            send, ok, why = encode_restore_value(c, b.get(c))
            changes.append({"col": c, "current": _brief(cur.get(c), c), "restore": _brief(b.get(c), c),
                            "restoreValue": b.get(c), "send": send, "verified": ok, "why": why})
        if changes:
            rows_out.append({"id": rid, "changes": changes, "currentDigest": _digest(cur, [x["col"] for x in changes]),
                             "unverified": [x["col"] for x in changes if not x["verified"]]})
    if scope is None and ids is None:
        extra = sorted((set(current_rows) - set(base_rows)), key=_sort_key)
    col_counts: Dict[str, int] = {}
    for r in rows_out:
        for x in r["changes"]:
            col_counts[x["col"]] = col_counts.get(x["col"], 0) + 1
    return {"rows": rows_out, "rowCount": len(rows_out), "columnCounts": col_counts,
            "unverifiedRows": sum(1 for r in rows_out if r["unverified"]),
            "missingOnServer": missing, "extraOnServer": extra}


def _brief(v: Any, col: str) -> Any:
    if col == "map" and v is not None:
        return {"mapSha256": L.server_map_sha(v)}
    return v


def _sort_key(rid: str):
    m = re.match(r"^([a-z]+)_?([0-9]+)?", str(rid))
    order = {"level": 0, "infinity": 1}
    return (order.get(m.group(1), 2) if m else 3, int(m.group(2)) if m and m.group(2) else 0, str(rid))


def payload_of(plan_row: Dict[str, Any], allow_unverified: bool) -> Dict[str, Any]:
    return {x["col"]: x["send"] for x in plan_row["changes"] if x["verified"] or allow_unverified}


def save_plan(plan: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    t = time.time()
    pid = f"plan_{_stamp(t)}_{_short(t)}"
    core = [{"id": r["id"], "currentDigest": r["currentDigest"],
             "payload": {x["col"]: x["send"] for x in r["changes"]}} for r in plan["rows"]]
    digest = hashlib.sha256(_dumps(core).encode()).hexdigest()
    doc = {"schema": PLAN_SCHEMA, "id": pid, "createdAt": _iso(t), "planDigest": digest, **meta, "plan": plan}
    _write_new_gz(_p("restore_plans", pid + ".json.gz"), doc)
    _append_index({"event": "restore_plan", "id": pid, "createdAt": doc["createdAt"], "planDigest": digest,
                   "rows": plan["rowCount"], "base": meta.get("base"), "board": meta.get("board")})
    return doc


def load_plan(pid: str) -> Dict[str, Any]:
    if not isinstance(pid, str) or not _PLAN_RE.match(pid):
        raise BackupError(f"invalid plan id: {pid!r}")
    p = _p("restore_plans", pid + ".json.gz")
    if not os.path.exists(p):
        raise BackupError(f"no such plan: {pid}")
    return _read_gz(p)


def preview_summary(doc: Dict[str, Any], sample: int = 20) -> Dict[str, Any]:
    plan = doc["plan"]
    warnings = list(doc.get("warnings") or [])
    return {"planId": doc["id"], "planDigest": doc["planDigest"], "createdAt": doc["createdAt"], "base": doc.get("base"),
            "board": doc.get("board"), "currentSource": doc.get("currentSource"), "scope": doc.get("scope"),
            "rowCount": plan["rowCount"], "columnCounts": plan["columnCounts"],
            "unverifiedRows": plan["unverifiedRows"], "missingOnServer": plan["missingOnServer"][:200],
            "missingCount": len(plan["missingOnServer"]), "extraOnServer": plan["extraOnServer"][:200],
            "extraCount": len(plan["extraOnServer"]), "createdByUpload": (doc.get("base") or {}).get("createdRows", []),
            "sample": [{"id": r["id"], "unverified": r["unverified"],
                        "changes": [{k: x[k] for k in ("col", "current", "restore", "verified", "why")} for x in r["changes"]]}
                       for r in plan["rows"][:sample]],
            "warnings": warnings, "confirmText": CONFIRM_TEXT}


def base_warnings(meta: Dict[str, Any], now: Optional[float] = None) -> List[str]:
    w = []
    now = time.time() if now is None else now
    if meta.get("type") == "backup" and meta.get("source") == "file":
        w.append("파일에서 가져온 백업(예 10-28 readback) — 그 뒤 서버에 들어간 변경(이후 업로드·시드 갱신)을 모두 이 값으로 덮어씁니다. "
                 "범위를 '업로드 스냅샷이 바꾼 열'로 좁히거나 최신 서버 백업을 쓰세요.")
    if meta.get("type") == "backup" and meta.get("complete") is False:
        w.append("불완전 백업 — 문제 행은 복원 대상에서 빠집니다.")
    if meta.get("dataTime") or meta.get("createdAt"):
        try:
            t = datetime.strptime(meta.get("dataTime") or meta["createdAt"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
            if (now - t) / 3600 > 24:
                w.append(f"기준 시점이 {((now - t) / 3600):.0f}시간 전 — 그 뒤 변경분도 되돌려집니다.")
        except ValueError:
            pass
    if meta.get("type") == "snapshot" and meta.get("createdRows"):
        w.append(f"업로드로 새로 생긴 행 {len(meta['createdRows'])}개는 지우지 않습니다(행 삭제 미지원) — 수동 처리 필요.")
    if meta.get("type") == "snapshot" and meta.get("rowsWithoutBefore"):
        w.append(f"업로드 직전 행 전체가 없는 기록 {meta['rowsWithoutBefore']}행(이 기능 이전 기록) — 복원 대상에서 빠짐.")
    return w


async def execute_plan(client: Any, pid: str, plan_digest: str, confirm_text: str, *, allow_unverified: bool = False,
                       sleep_s: float = 0.05, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """복원 실행(사람이 미리보기 확인 후). 행마다 strict 재조회 → 미리보기와 다르면 차단 → update(new=0) → 재조회 검증."""
    doc = load_plan(pid)
    if confirm_text != CONFIRM_TEXT:
        raise BackupError(f"confirm_text 가 '{CONFIRM_TEXT}' 가 아님")
    if plan_digest != doc["planDigest"]:
        raise BackupError("plan_digest 불일치 — 새 미리보기 필요")
    if not getattr(client, "is_configured", False):
        raise BackupError("GBoost client not configured")
    board = doc.get("board") or _dda.DDA_BOARD_ID
    rows = doc["plan"]["rows"]
    hdr = L.open_session(kind="restore", board=board, memo=f"복원 실행 {pid}", tag="restore", source="restore",
                         options={"planId": pid, "base": doc.get("base"), "allowUnverified": allow_unverified})
    sid = hdr["id"]
    res = {"planId": pid, "ledgerSession": sid, "total": len(rows), "restored": 0, "verified": 0, "mismatch": 0,
           "failed": 0, "blocked": 0, "results": []}
    for i, r in enumerate(rows):
        rid = r["id"]
        cols = [x["col"] for x in r["changes"]]
        payload = payload_of(r, allow_unverified)
        out = {"id": rid}
        try:
            got = await client.load_level(board, rid, strict=True)
            cur = got.get("level_json") if got else None
        except Exception as e:  # noqa: BLE001
            out.update({"status": "failed", "reason": f"lookup_failed: {e}"})
            res["failed"] += 1
            res["results"].append(out)
            L.append_row(sid, L.build_row_record(row_id=rid, source="restore", status="failed", payload=payload,
                                                 server_before="unknown", message=out["reason"]))
            continue
        if _digest(cur, cols) != r["currentDigest"]:
            out.update({"status": "blocked", "reason": "server_changed_since_preview"})
            res["blocked"] += 1
        elif not payload:
            out.update({"status": "blocked", "reason": "only_unverified_columns"})
            res["blocked"] += 1
        else:
            wr = await client.update_existing_level(board, rid, payload)
            if not wr.get("success"):
                out.update({"status": "failed", "reason": str(wr.get("error", ""))[:200]})
                res["failed"] += 1
            else:
                res["restored"] += 1
                try:
                    after = await client.load_level(board, rid, strict=True)
                    arow = (after or {}).get("level_json") or {}
                    want = {x["col"]: x for x in r["changes"] if x["col"] in payload}
                    bad = [c for c, x in want.items() if not same_value(arow.get(c), x["restoreValue"])]
                    out.update({"status": "verified" if not bad else "mismatch", "mismatchCols": bad})
                    res["verified" if not bad else "mismatch"] += 1
                except Exception as e:  # noqa: BLE001
                    out.update({"status": "restored_unverified", "reason": f"readback_failed: {e}"})
        out["skippedUnverified"] = [c for c in r["unverified"] if c not in payload]
        res["results"].append(out)
        L.append_row(sid, L.build_row_record(row_id=rid, source="restore",
                                             status="sent" if out["status"] in ("verified", "mismatch", "restored_unverified") else out["status"],
                                             payload=payload, server_before=cur, message=out.get("reason", "")))
        if progress:
            progress(i + 1, len(rows))
        if sleep_s:
            await asyncio.sleep(sleep_s)
    L.finalize(sid, {k: res[k] for k in ("total", "restored", "verified", "mismatch", "failed", "blocked")})
    _append_index({"event": "restore_exec", "planId": pid, "at": _iso(time.time()),
                   **{k: res[k] for k in ("total", "restored", "verified", "mismatch", "failed", "blocked", "ledgerSession")}})
    return res


# ── 간단한 백그라운드 작업(진행률 표시용, 프로세스 메모리) ───────────────────────────────
_jobs: Dict[str, Dict[str, Any]] = {}


def new_job(kind: str) -> Dict[str, Any]:
    jid = f"job_{_short(time.time())}{secrets.token_hex(2)}"
    j = {"id": jid, "kind": kind, "status": "running", "phase": "start", "startedAt": _iso(time.time()),
         "t0": time.time(), "current": 0, "total": 0, "result": None, "error": None}
    _jobs[jid] = j
    return j


def job_view(jid: str) -> Optional[Dict[str, Any]]:
    j = _jobs.get(jid)
    if not j:
        return None
    return {**{k: v for k, v in j.items() if k != "t0"}, "elapsed": round(time.time() - j["t0"], 1)}
