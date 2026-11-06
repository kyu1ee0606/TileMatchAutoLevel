"""
DDA 시드 개발용 목록 + 레벨별 판정 (문서 47).

- 목록: backend/data/dda_seeds/dda_t0_seed_catalog.v1.json (sha256 고정 — 다르면 로드 거부).
  서버 컬럼이 아니다. 목록 판정 대상은 levels.ddaEasySeeds / ddaHardSeeds 두 문자열뿐.
  [2026-11-02] 일반 익스포트는 4열(EXPORT_SEED_FIELDS)을 레벨 데이터 값으로만 보내고 없으면 생략 — export_fields.
- 판정 입력의 `townpop` 은 gboost._convert_to_townpop_format(level_json) 결과 —
  익스포트와 같은 변환으로 map 해시/useTileCount 를 본다(이 모듈은 routes 를 import 하지 않음).
- 새 시드를 만들거나 고르지 않는다. 목록 값과 정확히 같은 값만 유지/보충/익스포트한다.
"""
import hashlib
import json
import os
import re
from typing import Any, Dict, Optional

CATALOG_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "dda_seeds", "dda_t0_seed_catalog.v1.json"))
CATALOG_VERSION = "dda_seed_catalog.v1"
CATALOG_SHA256 = "57930b559bf935f076b1f77051dd2afc1ed95db60cd4f2cad0bae350fdfc5d13"

SEED_FIELDS = ("ddaEasySeeds", "ddaHardSeeds")
DDA_BOARD_ID = "levels"
_SEED_TOKEN = re.compile(r"^[1-9][0-9]*$")
_LEVEL_ID = re.compile(r"^level_([0-9]+)$")
_INT32_MAX = 2147483647

_cache: Optional[Dict[str, Any]] = None


class CatalogError(Exception):
    pass


def load_catalog() -> Dict[str, Any]:
    """목록 로드 + sha256/버전 검사. 실패 시 CatalogError."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(CATALOG_PATH, "rb") as f:
            data = f.read()
    except OSError as e:
        raise CatalogError(f"catalog_missing: {e}") from e
    digest = hashlib.sha256(data).hexdigest()
    if digest != CATALOG_SHA256:
        raise CatalogError(f"catalog_sha_mismatch: {digest}")
    cat = json.loads(data)
    if cat.get("catalogVersion") != CATALOG_VERSION:
        raise CatalogError(f"catalog_version_mismatch: {cat.get('catalogVersion')}")
    cat["_byLevel"] = {int(e["level"]): e for e in cat["levels"]}
    cat["_sha256"] = digest
    _cache = cat
    return cat


def catalog_info() -> Dict[str, Any]:
    try:
        cat = load_catalog()
    except CatalogError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "catalogVersion": cat["catalogVersion"], "settingsVersion": cat["settingsVersion"],
            "sha256": cat["_sha256"], "source": cat["source"], "counts": cat["counts"]}


def dump(obj: Any) -> bytes:
    """해시 계약 공통 직렬화 (dda_t0_all_prepare_20261020.py::dump 와 동일)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def map_sha256(townpop: Dict[str, Any]) -> str:
    return hashlib.sha256(dump(townpop.get("map"))).hexdigest()


def source_condition_hash(row: Dict[str, Any]) -> str:
    """sha256(dump(행 − {map, ddaEasySeeds, ddaHardSeeds})). 두 시드 필드는 해시에서 제외된다."""
    excl = ("map",) + SEED_FIELDS
    return hashlib.sha256(dump({k: v for k, v in row.items() if k not in excl})).hexdigest()


def is_valid_seed_str(value: Any) -> bool:
    """정확히 5개, 쉼표 구분·공백 없음, 각 1..Int32.Max, 부호·선행0·빈 토큰 불허."""
    if not isinstance(value, str) or not value:
        return False
    toks = value.split(",")
    return len(toks) == 5 and all(_SEED_TOKEN.match(t) and int(t) <= _INT32_MAX for t in toks)


def is_runtime_seed_str(field: str, value: Any) -> bool:
    """게임 DdaVariantCatalog.TryParseSeeds 와 같은 형식: 3개(±1 두 열은 옛 5개도 허용), 쉼표 구분·공백 없음,
    각 1..Int32.Max, 부호·선행0·빈 토큰·중복 불허."""
    if not isinstance(value, str) or not value:
        return False
    toks = value.split(",")
    if not (len(toks) == 3 or (field in SEED_FIELDS and len(toks) == 5)):
        return False
    if not all(_SEED_TOKEN.match(t) and int(t) <= _INT32_MAX for t in toks):
        return False
    return len(set(int(t) for t in toks)) == len(toks)


def classify(value: Any, expected: str) -> str:
    """match(정답) / missing(없음·빈 값) / invalid(형식 오류) / other(정상 형식·다른 값).
    [2026-11-02] 현행 3개 형식(서버·게임 정본)의 정상 값도 other — 'DDA 시드 갱신'이 검증된 3개 시드를
    옛 5개 목록 값으로 덮어쓰지 않게 한다(conflict → 건너뜀)."""
    if value is None or value == "":
        return "missing"
    if not is_valid_seed_str(value):
        return "other" if is_runtime_seed_str("ddaEasy2Seeds", value) else "invalid"
    return "match" if value == expected else "other"


def _gate(level_number: int, townpop: Dict[str, Any]) -> Dict[str, Any]:
    """후보·map·N 게이트. 통과하면 {"entry": e}, 아니면 {"reason": ..}."""
    try:
        cat = load_catalog()
    except CatalogError as e:
        return {"reason": "catalog_error", "detail": str(e)}
    e = cat["_byLevel"].get(int(level_number))
    if e is None:
        return {"reason": "no_data"}
    st = e["status"]
    if st == "hold":
        return {"reason": "hold", "detail": ";".join(e.get("reasons", []))}
    if st == "partial_hold":
        return {"reason": "partial_hold", "detail": ";".join(e.get("reasons", []))}
    if st != "candidate":
        return {"reason": "excluded", "detail": ";".join(e.get("reasons", []))}
    if map_sha256(townpop) != e["sourceMapSha256"]:
        return {"reason": "map_mismatch"}
    try:
        utc = int(townpop.get("useTileCount"))
    except (TypeError, ValueError):
        utc = None
    if utc != e["N"]:
        return {"reason": "n_mismatch", "detail": f"useTileCount={utc} N={e['N']}"}
    return {"entry": e}


def plan_level(level_number: int, level_json: Dict[str, Any], townpop: Dict[str, Any]) -> Dict[str, Any]:
    """'DDA 시드 갱신' 사전검사 (변경 없음). action: update / keep / conflict / skip."""
    res: Dict[str, Any] = {"level": int(level_number)}
    g = _gate(level_number, townpop)
    if "entry" not in g:
        res.update({"action": "skip", "reason": g["reason"], "detail": g.get("detail", "")})
        return res
    e = g["entry"]
    dirs = {}
    for fld in SEED_FIELDS:
        cur = level_json.get(fld)
        st = classify(cur, e[fld])
        dirs[fld] = {"state": st, "before": cur if isinstance(cur, str) or cur is None else str(cur),
                     "after": e[fld] if st in ("missing", "invalid") else cur}
    res["fields"] = dirs
    if any(d["state"] == "other" for d in dirs.values()):
        res.update({"action": "conflict", "reason": "conflict"})
        for d in dirs.values():
            d["after"] = d["before"]          # 두 방향 모두 건너뜀
    elif all(d["state"] == "match" for d in dirs.values()):
        res.update({"action": "keep", "reason": "already_valid"})
    else:
        res.update({"action": "update", "reason": "fill"})
    return res


def _seed_values(level_number: int, level_json: Dict[str, Any], townpop: Dict[str, Any]) -> Dict[str, Any]:
    """후보·map·N 게이트 + 저장값이 정답과 정확히 같을 때만 값, 아니면 "" (+reason)."""
    g = _gate(level_number, townpop)
    if "entry" not in g:
        return {"ddaEasySeeds": "", "ddaHardSeeds": "", "reason": g["reason"]}
    e = g["entry"]
    if all(level_json.get(f) == e[f] for f in SEED_FIELDS):
        return {"ddaEasySeeds": e["ddaEasySeeds"], "ddaHardSeeds": e["ddaHardSeeds"], "reason": "valid"}
    states = {f: classify(level_json.get(f), e[f]) for f in SEED_FIELDS}
    reason = "conflict" if "other" in states.values() else (
        "invalid" if "invalid" in states.values() else "missing")
    return {"ddaEasySeeds": "", "ddaHardSeeds": "", "reason": reason}


# ── 일반 익스포트 시드 열 (2026-11-02 개정) ──────────────────────────────────────
# 서버 levels 시드 4열(게임 DdaVariantCatalog.cs:35-39). 열마다 독립: 레벨 데이터(level_json 루트, 서버와 같은 키)에
# 유효 값이 있으면 보내고, 없거나 쓸 수 없으면 키 자체를 생략한다 → real_array save(new=0)는 보내지 않은 컬럼을
# 서버 기존 값으로 유지한다(근거: READBACK_RULES "unsent", 2026-10-28 시드만 2,262행 전송·전 행 재조회 무변경).
# "" 로 덮어써 서버 시드를 지우는 경로는 없다.
EXPORT_SEED_FIELDS = ("ddaEasy2Seeds", "ddaEasySeeds", "ddaHardSeeds", "ddaHard2Seeds")
# 무한 사본(infinity_N)은 정식 level_{500+N} 의 level_json 을 복사해 올린다. 무한 행은 자기 시드를 가지므로
# (2026-10-28 결정) 정식 시드를 보내지 않는다. 확장 지점: 원본 level_json 루트의
#   "ddaInfinitySeeds": {"infinity_N": {"ddaEasySeeds": "a,b,c", ...}}
# 에 그 무한 행 값이 있으면 그 열만 보낸다(형식 검사 동일). 없으면 4열 모두 생략.
INFINITY_SEEDS_KEY = "ddaInfinitySeeds"
_INF_ID = re.compile(r"^infinity_([0-9]+)$")
# 옛 v1 목록(5개) 값을 문서 47 판정 유효 시 보낼지. 기본 False(생략).
# 근거(2026-11-02 실측, LIVE 일치본 배치 × 11:55 서버 readback, UI 기본 설정): 판정 유효 1,214행×2열 중
# 서버와 같음 1,102열 · 서버가 이후 값을 가짐 1,326열/664행(10-28 무작위 3개 662행·L65/L95 순서 다른 5개 2행) · 서버 빈 값 0.
# 즉 보내면 최신 서버 시드를 옛 목록 값으로 되돌리기만 한다(운영 DDA 는 목록을 참조하지 않음 — IMPL_SPEC :264).
LEGACY_CATALOG_EXPORT = False

# ── 클리어 가능 판정 근거 (2026-11-02, 사용자 지시 "시드는 최소한 클리어 가능한 것으로") ──────────────
# 서버 값과 '다른' 시드(새 값)는 판정 근거가 있을 때만 보낸다. 근거가 없으면 그 열을 생략(서버 값 유지)한다.
# 근거 = level_json 루트(무한 행은 ddaInfinitySeeds[id] 안)의 "ddaSeedVerdicts" — 서버로는 보내지 않는다
# (_convert_to_townpop_format 은 이 키를 복사하지 않음).
#   "ddaSeedVerdicts": {
#     "binding": {"mapSha256": map_sha256(변환된 행), "useTileCount": "<변환된 행 useTileCount>"},
#     "ddaHardSeeds": [{"seed": 950941980, "verdict": "PATH", "nodes": 9, "source": "dda_seed_verify/20261029/replace"}, ...],
#     ...
#   }
# 형식은 sp_meowsgarden tools/dda_seed_verify 의 v4_seed_patch.json proof 항목({seed, verdict, nodes})·
# results.csv / bot_results.csv 의 verdict 와 같다. 통과 판정 = PATH(검증된 클리어 경로) / PATH_BOT(봇 30판 중 1판 이상 클리어).
# binding 이 지금 변환 결과(map·useTileCount)와 다르면 맵이 바뀐 뒤의 옛 근거이므로 무효.
# 게임은 시드 문자열의 앞 3개만 쓴다(DdaVariantCatalog.cs:97,123 — ±1 옛 5개 값도 앞 3개) → 앞 3개 각각에 통과 판정 필요.
SEED_EVIDENCE_KEY = "ddaSeedVerdicts"
SEED_PASS_VERDICTS = ("PATH", "PATH_BOT")
SEED_EVIDENCE_REQUIRED = True
_GAME_SEED_COUNT = 3


def seed_evidence(field: str, value: Any, ev: Any, townpop: Dict[str, Any]) -> str:
    """열 값의 판정 근거 상태: ok / none / binding_mismatch / partial:<통과수>/<필요수>."""
    if not isinstance(ev, dict):
        return "none"
    b = ev.get("binding")
    if not isinstance(b, dict) or b.get("mapSha256") != map_sha256(townpop) \
            or str(b.get("useTileCount")) != str(townpop.get("useTileCount")):
        return "binding_mismatch"
    lst = ev.get(field)
    if not isinstance(lst, list):
        return "none"
    passed = set()
    for x in lst:
        if isinstance(x, dict) and x.get("verdict") in SEED_PASS_VERDICTS:
            try:
                passed.add(int(x.get("seed")))
            except (TypeError, ValueError):
                pass
    used = [int(t) for t in str(value).split(",")[:_GAME_SEED_COUNT]]
    n = sum(1 for t in used if t in passed)
    return "ok" if n == len(used) else f"partial:{n}/{len(used)}"


def _attach_evidence(out: Dict[str, Any], ev: Any, townpop: Dict[str, Any]) -> None:
    out["fieldEvidence"] = {f: seed_evidence(f, out[f], ev, townpop) for f in EXPORT_SEED_FIELDS if f in out}


def evidence_gate(existing_row: Any, payload: Dict[str, Any], field_evidence: Dict[str, str]) -> Dict[str, str]:
    """서버 값과 다르고 판정 근거(ok)가 없는 시드 열을 payload 에서 뺀다(생략 = 서버 값 유지).
    반환 {열: 사유} = 뺀 열. existing_row 가 dict 가 아니면(새 행) 서버 값 "" 로 본다."""
    dropped: Dict[str, str] = {}
    if not SEED_EVIDENCE_REQUIRED:
        return dropped
    srv = existing_row if isinstance(existing_row, dict) else {}
    for f in EXPORT_SEED_FIELDS:
        if f not in payload:
            continue
        if _norm(srv.get(f)) == _norm(payload[f]):
            continue                                    # 서버와 같은 값 — 새로 정하는 시드 아님
        st = (field_evidence or {}).get(f, "none")
        if st != "ok":
            payload.pop(f)
            dropped[f] = st
    return dropped


def _pick_fields(src: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """src 의 4열 중 보낼 값만 고른다. 반환 {열: 값, ..., "fieldReasons": {열: 사유}}."""
    out: Dict[str, Any] = {}
    why: Dict[str, str] = {}
    for f in EXPORT_SEED_FIELDS:
        v = src.get(f)
        if v is None or v == "":
            why[f] = "absent"
        elif not is_runtime_seed_str(f, v):
            why[f] = "invalid_format"
        else:
            out[f] = v
            why[f] = tag
    out["fieldReasons"] = why
    return out


def _is_legacy_catalog_value(level: int, field: str, value: Any) -> Optional[bool]:
    """옛 v1 목록(5개) 값인가. 목록 로드 실패면 None(판단 불가)."""
    try:
        e = load_catalog()["_byLevel"].get(level)
    except CatalogError:
        return None
    return bool(e) and value == e.get(field)


def export_fields(board_id: str, level_id: str, level_json: Dict[str, Any],
                  townpop: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """일반(전체 행) GameBoost 익스포트에 넣을 시드 열(0~4개). None = 이 보드엔 필드를 추가하지 않음.

    반환: 보낼 열만 키로 포함 + "reason"(요약) + "fieldReasons"(열별). 키가 없는 열 = 전송 생략(서버 값 유지).
    - level_N: level_json 의 열 값이 게임 형식(3개, ±1 은 5개도)이면 보냄.
      단 ddaEasySeeds/ddaHardSeeds 의 5개 값이 그 레벨 v1 목록 값과 같으면 기본 생략(LEGACY_CATALOG_EXPORT=False).
      True 이면 그 레벨 v1 목록 값이고 기존 문서 47 판정(_legacy_export_fields)이 유효일 때만 보냄. 어느 쪽도 "" 는 안 보냄.
    - infinity_N: 정식 시드 미사용. ddaInfinitySeeds[level_id] 가 있을 때만 그 값.
    - 그 외 id: 생략.
    """
    if board_id != DDA_BOARD_ID:
        return None
    if _INF_ID.match(level_id or ""):
        src = level_json.get(INFINITY_SEEDS_KEY)
        ent = src.get(level_id) if isinstance(src, dict) else None
        if not isinstance(ent, dict):
            return {"reason": "infinity_omitted",
                    "fieldReasons": {f: "infinity_omitted" for f in EXPORT_SEED_FIELDS}}
        out = _pick_fields(ent, "infinity_data")
        out["reason"] = "infinity_data"
        _attach_evidence(out, ent.get(SEED_EVIDENCE_KEY), townpop)
        return out
    m = _LEVEL_ID.match(level_id or "")
    if not m:
        return {"reason": "not_level_row", "fieldReasons": {f: "not_level_row" for f in EXPORT_SEED_FIELDS}}
    level = int(m.group(1))
    out = _pick_fields(level_json, "level_data")
    why = out["fieldReasons"]
    legacy: Optional[Dict[str, Any]] = None
    for f in SEED_FIELDS:
        if f not in out:
            continue
        if len(str(out[f]).split(",")) != 5:
            continue                                   # 현행 3개 형식 → 레벨 데이터 값 그대로
        # 5개 형식: 그 레벨 v1 목록 값과 같으면 옛 목록 값(기본 생략, LEGACY_CATALOG_EXPORT).
        # 목록 값과 다르면 레벨 데이터 값(예: 배치 보정에서 토큰 일부를 바꾼 검증 값) → 그대로 보냄.
        is_legacy = _is_legacy_catalog_value(level, f, out[f])
        if is_legacy is None:
            out.pop(f)
            why[f] = "legacy_unverifiable:catalog_error"
        elif not is_legacy:
            continue
        else:
            if legacy is None:
                legacy = _legacy_export_fields(level_id, level, level_json, townpop)
            if legacy["reason"] == "valid" and LEGACY_CATALOG_EXPORT:
                out[f] = legacy[f]
                why[f] = "legacy_valid"
            elif legacy["reason"] == "valid":
                out.pop(f)
                why[f] = "legacy_valid_not_sent"
            else:
                out.pop(f)
                why[f] = "legacy:" + legacy["reason"]
    sent = [f for f in EXPORT_SEED_FIELDS if f in out]
    out["reason"] = ("send:" + ",".join(sent)) if sent else "omitted"
    _attach_evidence(out, level_json.get(SEED_EVIDENCE_KEY), townpop)
    return out


def _legacy_export_fields(level_id: str, level: int, level_json: Dict[str, Any],
                          townpop: Dict[str, Any]) -> Dict[str, Any]:
    """[문서 47 옛 판정] 두 필드: 유효 후보면 값, 아니면 "" (+reason). 호출부는 "" 를 보내지 않고 생략한다.
    [P1] 유효 후보라도 이번 업로드 행(다른 컬럼)이 검증 기준 원본 행과 다르면 "" (row_changed) —
    행이 바뀌면 런타임 조건 해시가 달라져 시드가 무효이기 때문. 일반 편집 값은 그대로 둔다(덮어쓰지 않음).
    """
    f = _seed_values(level, level_json, townpop)
    if f["reason"] != "valid":
        return f
    try:
        snap = load_source_rows()["rows"].get(level_id)
    except CatalogError:
        snap = None
    if snap is None:
        return {"ddaEasySeeds": "", "ddaHardSeeds": "", "reason": "no_snapshot"}
    # [§13] 업로드 후 서버 읽기값을 L159 실측 규칙으로 예측해 출시 행과 비교(규칙 외 표현은 미확인 → 차단)
    pred, unverified = predict_readback(townpop, snap)
    diff = [k for k in snap if k != "id" and dump(pred.get(k)) != dump(snap.get(k))] + [f"{k}(unverified)" for k in unverified]
    if diff:
        return {"ddaEasySeeds": "", "ddaHardSeeds": "", "reason": "row_changed:" + ",".join(diff[:6])}
    return f


def apply_export_fields_with_evidence(board_id: str, level_id: str, level_json: Dict[str, Any],
                                      townpop: Dict[str, Any]):
    """apply_export_fields + 열별 판정 근거 상태. 반환 (townpop, fieldEvidence)."""
    f = export_fields(board_id, level_id, level_json, townpop)
    if f is None:
        return townpop, {}
    for k in EXPORT_SEED_FIELDS:
        townpop.pop(k, None)
        if k in f:
            townpop[k] = f[k]
    return townpop, dict(f.get("fieldEvidence") or {})


def apply_export_fields(board_id: str, level_id: str, level_json: Dict[str, Any],
                        townpop: Dict[str, Any]) -> Dict[str, Any]:
    """townpop 에 보낼 시드 열만 넣어 반환 (levels 보드 외엔 그대로). 보내지 않을 열은 키를 넣지 않는다."""
    f = export_fields(board_id, level_id, level_json, townpop)
    if f is None:
        return townpop
    for k in EXPORT_SEED_FIELDS:
        townpop.pop(k, None)
        if k in f:
            townpop[k] = f[k]
    return townpop


# ── 원본 행 스냅샷 · 시드만 내보내기 · 쓰기 가드 (P1, 문서 47 §5) ─────────────────
ROWS_PATH = os.path.normpath(os.path.join(os.path.dirname(CATALOG_PATH), "dda_t0_source_rows.v1.json"))
ROWS_SHA256 = "063954da17f7b2fd2d8b36039963f1e531f7438a738fe11506bf98796fd3120e"
# 행 비교 제외: 행 키(id) · map(별도 해시 검사) · 시드 두 컬럼 · 업로드 시각(etime, 출시 테이블에 없음)
# idx = 서버 레코드 번호(서버 관리, 매니페스트 id/idx/etime) — 비교·payload 에서 제외 (§8)
ROW_COMPARE_EXCLUDE = ("id", "idx", "map") + SEED_FIELDS + ("etime",)
SERVER_MANAGED_KEYS = ("id", "idx")
_rows_cache: Optional[Dict[str, Any]] = None


def load_source_rows() -> Dict[str, Any]:
    """출시 행 스냅샷(신뢰 기준) 로드 + sha256/목록 결속 검사. 실패 시 CatalogError."""
    global _rows_cache
    if _rows_cache is not None:
        return _rows_cache
    try:
        with open(ROWS_PATH, "rb") as f:
            data = f.read()
    except OSError as e:
        raise CatalogError(f"rows_missing: {e}") from e
    if hashlib.sha256(data).hexdigest() != ROWS_SHA256:
        raise CatalogError("rows_sha_mismatch")
    doc = json.loads(data)
    if doc.get("catalogSha256") != CATALOG_SHA256:
        raise CatalogError("rows_catalog_mismatch")
    _rows_cache = doc
    return doc


def _norm(v: Any) -> str:
    """행 값 비교용 정규화(비교에만 사용, 전송 값은 바꾸지 않음): None≡"", 숫자·불리언·문자열은 문자열 표기,
    정수값 실수는 정수 표기, 리스트/객체는 dump."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, dict)):
        return dump(v).decode()
    return str(v)


def row_diff(row: Dict[str, Any], snap: Dict[str, Any]) -> list:
    """비교 대상 키 집합·값(정규화) 차이. 빈 리스트면 같음. 형식: key(사유)."""
    out = []
    rk = [k for k in row if k not in ROW_COMPARE_EXCLUDE]
    sk = [k for k in snap if k not in ROW_COMPARE_EXCLUDE]
    for k in sk:
        if k not in row:
            out.append(f"{k}(missing)")
        elif _norm(row[k]) != _norm(snap[k]):
            out.append(f"{k}({_norm(snap[k])}->{_norm(row[k])})")
    out.extend(f"{k}(extra)" for k in rk if k not in snap)
    return out


def _server_map_sha(m: Any) -> Optional[str]:
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            return None
    return hashlib.sha256(dump(m)).hexdigest() if isinstance(m, dict) else None


def row_digest(row: Any) -> str:
    return hashlib.sha256(dump(row)).hexdigest()


def write_guard(existing_row: Any, payload: Dict[str, Any], confirm: bool) -> Optional[str]:
    """실제 업로드 직전 안전 조건(4열). 서버의 비어 있지 않은 시드를 빈 값으로 바꾸려면 confirm 필요.
    payload 에 키가 없는 열(생략 = 서버 값 유지)·서버와 같은 값·비어 있지 않은 다른 값은 막지 않는다.
    반환: None=통과, 문자열=차단 사유."""
    if not isinstance(existing_row, dict):
        return None                      # 새 행(서버 값 없음)
    for f in EXPORT_SEED_FIELDS:
        if f not in payload:
            continue
        if _norm(existing_row.get(f)) != "" and _norm(payload.get(f)) == "" and not confirm:
            return "needs_dda_confirm"
    return None


# ── 시드만 내보내기 v2 (2026-11-03, PLAN_DDA_SEED_ONLY_EXPORT_FIX_20261103) ───────────────────
# 값 출처 = 맵툴 배치 파일(서버 저장본) level_json → export_fields(일반 업로드와 같은 4열 판정) → evidence_gate.
# 서버 행은 보드 전체 1회 조회(load_board_rows) 결과로 판정한다. 보낼 payload = 서버와 다르고 근거 ok 인 시드 열만.
# 신뢰 조건: 서버 행 존재 · 4열 컬럼 존재 · 서버 map(빈 층 []→{} 정규화) = 배치 변환 map · useTileCount 같음.
# 옛 v1(두 열·v1 목록·출시 스냅샷) 판정은 dda_seed_only_v1_legacy.py 로 옮겼다(10-20 스크립트 전용).

# ── 부분 수정 게이트 (§9) ────────────────────────────────────────────────────────
# 관측 근거: 2026-10-28 시드 전송 2,262행(1~4열 부분 payload, update_existing_level)이 행마다 전체 행 재조회 =
# 직전 행+payload (sp_meowsgarden/tools/out/dda_seed_random_20261028/upload/results.jsonl ok 2,262/2,262).
# 그래도 이 경로의 전체 전송은 '시험 1행 통과 기록'(PARTIAL_TRIAL_DIR, 현재 코드 해시에 묶임)이 있을 때만 연다.
# 상수 True 는 시험 기록 없이 여는 수동 우회(기본 False, 바꾸지 말 것).
PARTIAL_UPDATE_VERIFIED = False
PARTIAL_TRIAL_DIR = os.path.normpath(os.path.join(os.path.dirname(CATALOG_PATH), "partial_update_trials"))
PARTIAL_TRIAL_KIND = "dda_seed_partial_update_trial.v1"
SEED_ONLY_CELL_STATES = ("send", "same", "kept", "unverified", "blocked")


def code_fingerprint_files(paths: list, settings: Dict[str, Any]) -> str:
    """시드만 전송 경로 코드 해시 — 관련 모듈 파일 전체 바이트 + 판정 설정 값. 하나라도 바뀌면 시험 기록이 무효."""
    h = hashlib.sha256()
    for pth in sorted(os.path.normpath(str(x)) for x in paths):
        h.update(os.path.basename(pth).encode())
        h.update(b"\0")
        with open(pth, "rb") as fh:
            h.update(hashlib.sha256(fh.read()).digest())
    h.update(json.dumps(settings, sort_keys=True, default=str).encode())
    return h.hexdigest()


def seed_settings_snapshot() -> Dict[str, Any]:
    """코드 해시에 넣는 런타임 판정 설정(모듈 상수의 현재 값)."""
    return {"SEED_EVIDENCE_REQUIRED": SEED_EVIDENCE_REQUIRED, "SEED_PASS_VERDICTS": list(SEED_PASS_VERDICTS),
            "LEGACY_CATALOG_EXPORT": LEGACY_CATALOG_EXPORT, "EXPORT_SEED_FIELDS": list(EXPORT_SEED_FIELDS),
            "CATALOG_SHA256": CATALOG_SHA256, "GAME_SEED_COUNT": _GAME_SEED_COUNT, "DDA_BOARD_ID": DDA_BOARD_ID,
            "INFINITY_SEEDS_KEY": INFINITY_SEEDS_KEY, "SEED_EVIDENCE_KEY": SEED_EVIDENCE_KEY}


def normalize_gb_target(base_url: Any, project_id: Any, board_id: Any) -> Dict[str, str]:
    """GameBoost 대상 식별값: base_url(스킴·호스트 소문자, 끝 '/' 제거, 기본 포트 제거) · project_id · board_id."""
    from urllib.parse import urlsplit
    u = str(base_url or "").strip()
    try:
        sp = urlsplit(u)
        host = (sp.hostname or "").lower()
        port = sp.port
        scheme = (sp.scheme or "").lower()
        if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
            host = f"{host}:{port}"
        norm = f"{scheme}://{host}{sp.path.rstrip('/')}" if scheme and host else u.rstrip("/").lower()
    except ValueError:
        norm = u.rstrip("/").lower()
    return {"base_url": norm, "project_id": str(project_id or "").strip(), "board_id": str(board_id or "").strip()}


def normalize_map(m: Any) -> Optional[Any]:
    """서버/변환 map 비교용 정규화. 문자열이면 JSON 파싱, layer_* 의 빈 tiles 목록([])은 {} 로.
    파싱 불가·dict 아님 → None. 값은 바꾸지 않은 사본을 돌려준다(비교 전용)."""
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            return None
    if not isinstance(m, dict):
        return None
    out = {}
    for k, v in m.items():
        if isinstance(k, str) and k.startswith("layer_") and isinstance(v, dict) \
                and isinstance(v.get("tiles"), list) and not v["tiles"]:
            v = {**v, "tiles": {}}
        out[k] = v
    return out


def map_compare_sha(m: Any) -> Optional[str]:
    n = normalize_map(m)
    return None if n is None else hashlib.sha256(json.dumps(n, ensure_ascii=False, sort_keys=True,
                                                            separators=(",", ":")).encode()).hexdigest()


def seed_only_plan_v2(target_id: str, level_json: Dict[str, Any], townpop: Dict[str, Any],
                      server_row: Any, board_keys: Optional[list] = None) -> Dict[str, Any]:
    """v2 판정. level_json = 배치 원본(무한이면 relabel 후), townpop = 그 변환본(시드 열 넣기 전/후 무관).

    반환: target_id · blocked · reason · detail · serverDigest · change(same/fill/change) ·
          cells{열: {state: send|same|kept|unverified|blocked, server, value?, why?, kind?}} · payload(send 열만).
    """
    res: Dict[str, Any] = {"target_id": target_id, "blocked": True, "reason": "", "cells": {}}

    def _block(reason: str, detail: str = "") -> Dict[str, Any]:
        res.update({"blocked": True, "reason": reason, **({"detail": detail} if detail else {})})
        res["cells"] = {f: {"state": "blocked", "why": reason} for f in EXPORT_SEED_FIELDS}
        res["payload"] = {}
        return res

    if not (_LEVEL_ID.match(target_id or "") or _INF_ID.match(target_id or "")):
        return _block("not_seed_row")
    if server_row is None:
        return _block("no_server_row")
    if not isinstance(server_row, dict):
        return _block("server_row_invalid")
    res["serverDigest"] = row_digest(server_row)
    keys = set(board_keys) if board_keys is not None else set(server_row)
    missing = [f for f in EXPORT_SEED_FIELDS if f not in keys or f not in server_row]
    if missing:
        return _block("no_seed_column", ",".join(missing))
    s_sha = map_compare_sha(server_row.get("map"))
    if s_sha is None:
        return _block("server_map_unverifiable")
    if s_sha != map_compare_sha(townpop.get("map")):
        return _block("server_map_differs")
    if _norm(server_row.get("useTileCount")) != _norm(townpop.get("useTileCount")):
        return _block("server_map_differs", f"useTileCount server={_norm(server_row.get('useTileCount'))} "
                                            f"batch={_norm(townpop.get('useTileCount'))}")
    f = export_fields(DDA_BOARD_ID, target_id, level_json, townpop) or {}
    ev = dict(f.get("fieldEvidence") or {})
    why = dict(f.get("fieldReasons") or {})
    cells: Dict[str, Dict[str, Any]] = {}
    payload: Dict[str, Any] = {}
    for fld in EXPORT_SEED_FIELDS:
        sv = _norm(server_row.get(fld))
        if fld not in f:
            cells[fld] = {"state": "kept", "server": sv, "why": why.get(fld, "absent")}
            continue
        v = f[fld]
        if sv == _norm(v):
            cells[fld] = {"state": "same", "server": sv, "value": v}
        elif SEED_EVIDENCE_REQUIRED and ev.get(fld, "none") != "ok":
            cells[fld] = {"state": "unverified", "server": sv, "value": v, "why": ev.get(fld, "none")}
        else:
            cells[fld] = {"state": "send", "server": sv, "value": v, "kind": "fill" if sv == "" else "change"}
            payload[fld] = v
    kinds = {c.get("kind") for c in cells.values() if c["state"] == "send"}
    res.update({"blocked": False, "reason": f.get("reason", ""), "cells": cells, "payload": payload,
                "change": "change" if "change" in kinds else "fill" if "fill" in kinds else "same"})
    return res


def assert_seed_payload(payload: Dict[str, Any]) -> None:
    """v2 전송 payload: 키 1개 이상 ⊆ 시드 4열, 값마다 게임 형식(is_runtime_seed_str). "" 금지(서버 시드 비우기 없음)."""
    if not payload or not set(payload) <= set(EXPORT_SEED_FIELDS):
        raise ValueError(f"seed payload keys must be a non-empty subset of {EXPORT_SEED_FIELDS}: {sorted(payload)}")
    for k, v in payload.items():
        if not is_runtime_seed_str(k, v):
            raise ValueError(f"invalid seed value for {k}")


def _row_wo_etime(row: Any) -> Any:
    return {k: v for k, v in row.items() if k != "etime"} if isinstance(row, dict) else row


def judge_partial_trial(target_id: str, payload: Dict[str, Any], before_rows: Dict[str, Any],
                        after_rows: Dict[str, Any]) -> Dict[str, Any]:
    """시험 1행 재조회 대조(같은 보드 조회 경로 전후). 통과 = 대상 행(etime 제외) == 직전 행+payload 이고
    다른 모든 행 digest·행 id 집합 불변."""
    before = before_rows.get(target_id)
    after = after_rows.get(target_id)
    expected = _row_wo_etime({**before, **payload}) if isinstance(before, dict) else None
    target_ok = isinstance(after, dict) and dump(_row_wo_etime(after)) == dump(expected)
    bad_keys = [] if target_ok or not isinstance(after, dict) or expected is None else sorted(
        k for k in set(after) | set(expected) if k != "etime" and dump(after.get(k)) != dump(expected.get(k)))
    others_changed = sorted(i for i in set(before_rows) | set(after_rows) if i != target_id
                            and row_digest(before_rows.get(i)) != row_digest(after_rows.get(i)))
    return {"targetOk": target_ok, "badKeys": bad_keys[:20], "othersChanged": len(others_changed),
            "othersChangedSample": others_changed[:10],
            "expectedDigest": row_digest(expected) if expected is not None else None,
            "afterDigest": row_digest(_row_wo_etime(after)) if isinstance(after, dict) else None,
            "passed": bool(target_ok and not others_changed)}


def write_partial_trial_record(rec: Dict[str, Any]) -> str:
    """시험 결과 기록(통과/실패 모두). 'x' 모드 — 덮어쓰지 않는다. 반환 경로."""
    os.makedirs(PARTIAL_TRIAL_DIR, exist_ok=True)
    import time as _t
    stamp = _t.strftime("%Y%m%dT%H%M%S")
    path = os.path.join(PARTIAL_TRIAL_DIR, f"trial_{stamp}_{rec.get('target_id', 'x')}.json")
    with open(path, "x", encoding="utf-8") as fh:
        json.dump({"kind": PARTIAL_TRIAL_KIND, **rec}, fh, ensure_ascii=False, indent=1)
    return path


def partial_update_allowed(code_hash: str, gb_target: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """전체 전송 허용 여부. 상수 우회 또는 '현재 코드 해시 + 같은 GameBoost 대상(base_url·project·board)'의
    통과 기록(대상 행·대조 결과 자체 일관)이 있어야 한다. gb_target 이 None 이면 기록 불일치로 본다."""
    if PARTIAL_UPDATE_VERIFIED:
        return {"allowed": True, "by": "constant"}
    try:
        names = sorted(os.listdir(PARTIAL_TRIAL_DIR))
    except OSError:
        names = []
    for n in reversed(names):
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(PARTIAL_TRIAL_DIR, n), encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        j = r.get("judge") or {}
        if (r.get("kind") == PARTIAL_TRIAL_KIND and r.get("codeHash") == code_hash and r.get("target_id")
                and gb_target is not None and r.get("gbTarget") == gb_target
                and r.get("payload") and j.get("passed") is True and j.get("targetOk") is True
                and j.get("othersChanged") == 0 and j.get("afterDigest") and j.get("afterDigest") == j.get("expectedDigest")):
            return {"allowed": True, "by": "trial", "record": n, "target_id": r.get("target_id")}
    return {"allowed": False, "by": None}

# ── 업로드 후 서버 읽기값 예측 (§13) ─────────────────────────────────────────────
# 근거: 2026-10-20 18:58 L159 실측(backend/data/dda_seeds/server_apply_20261020_1822/l159_upload_via_existing/step2/compare.json)
# + 08-19 에디터 업로드 2401행 관측. 아래 표 외의 표현은 '미확인' → 대상 보류.
READBACK_RULES_VERSION = "dda_readback_rules.v1"
READBACK_RULES = {
    "numeric_string": "보낸 정수 문자열('-?\\d+') → 정수로 읽힘 (timea, unlockTile, col, row, rewardCoin, randSeed, shuffle*, difficulty, teleportRandSeed, autoCollectCount, num, sets, layer, useTileCount 실측)",
    "empty_string": "보낸 \"\" → \"\" (typeImbalance 실측)",
    "backgroundIndex,tileSkin": "보낸 \"0\" → null (그 외 값 미확인)",
    "rewardList": "보낸 \"[]\" → null (그 외 값 미확인 — 비어있지 않은 목록 자동 허용 금지)",
    "useInRandomizer,useTeleportInRandomizer": "보낸 \"0\" → 0 (\"1\" 미확인)",
    "map": "보낸 객체 → 같은 객체(dump 동일)",
    "ddaEasySeeds,ddaHardSeeds": "보낸 문자열 → 같은 문자열",
    "unsent(visualTileSeed,field4,'',idx,id)": "보내지 않은 키 → 서버 기존값 유지(L159 실측: \"\"/\"\"/\"\"/62985)",
    "etime": "서버가 저장 시각으로 갱신(보낸 값 무시) — 비교 제외",
}
_INT_STR = re.compile(r"^-?[0-9]+$")


def predict_readback(payload: Dict[str, Any], base_row: Dict[str, Any]):
    """payload 를 저장했을 때 서버가 돌려줄 행을 READBACK_RULES 로 예측. (pred_row, unverified_keys).
    base_row 는 보내지 않은 키의 기존값 출처(서버 현재 행 또는 출시 행)."""
    pred = {k: v for k, v in base_row.items()}
    unverified = []
    for k, v in payload.items():
        if k == "etime":
            continue
        if k in ("backgroundIndex", "tileSkin"):
            if v == "0":
                pred[k] = None
            else:
                unverified.append(k)
        elif k == "rewardList":
            if v == "[]":
                pred[k] = None
            else:
                unverified.append(k)
        elif k in ("useInRandomizer", "useTeleportInRandomizer"):
            if v == "0":
                pred[k] = 0
            else:
                unverified.append(k)
        elif k == "map" or k in SEED_FIELDS:
            pred[k] = v
        elif isinstance(v, str) and _INT_STR.match(v):
            pred[k] = int(v)
        elif v == "":
            pred[k] = ""
        else:
            unverified.append(k)
        if k not in base_row and k != "map" and k not in unverified:   # map 은 sourceMapSha256 게이트로 별도 검증
            unverified.append(k)
    return pred, unverified
