"""
DDA 시드 개발용 목록 + 레벨별 판정 (문서 47).

- 목록: backend/data/dda_seeds/dda_t0_seed_catalog.v1.json (sha256 고정 — 다르면 로드 거부).
  서버 컬럼이 아니다. 서버로 가는 값은 levels.ddaEasySeeds / ddaHardSeeds 두 문자열뿐.
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


def classify(value: Any, expected: str) -> str:
    """match(정답) / missing(없음·빈 값) / invalid(형식 오류) / other(정상 형식·다른 값)."""
    if value is None or value == "":
        return "missing"
    if not is_valid_seed_str(value):
        return "invalid"
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


def export_fields(board_id: str, level_id: str, level_json: Dict[str, Any],
                  townpop: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """일반(전체 행) GameBoost 익스포트에 넣을 두 필드. None = 이 보드엔 필드를 추가하지 않음.

    levels 보드면 항상 두 키를 명시한다: 유효 후보면 값, 아니면 "" (+reason).
    [P1] 유효 후보라도 이번 업로드 행(다른 컬럼)이 검증 기준 원본 행과 다르면 "" (row_changed) —
    행이 바뀌면 런타임 조건 해시가 달라져 시드가 무효이기 때문. 일반 편집 값은 그대로 둔다(덮어쓰지 않음).
    """
    if board_id != DDA_BOARD_ID:
        return None
    m = _LEVEL_ID.match(level_id or "")
    if not m:
        return {"ddaEasySeeds": "", "ddaHardSeeds": "", "reason": "not_level_row"}
    f = _seed_values(int(m.group(1)), level_json, townpop)
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


def apply_export_fields(board_id: str, level_id: str, level_json: Dict[str, Any],
                        townpop: Dict[str, Any]) -> Dict[str, Any]:
    """townpop 에 두 필드를 넣어 반환 (levels 보드 외엔 그대로)."""
    f = export_fields(board_id, level_id, level_json, townpop)
    if f is None:
        return townpop
    townpop["ddaEasySeeds"] = f["ddaEasySeeds"]
    townpop["ddaHardSeeds"] = f["ddaHardSeeds"]
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


def seed_only_plan(level_id: str, level_json: Dict[str, Any], townpop: Dict[str, Any],
                   server_row: Any) -> Dict[str, Any]:
    """'시드만 내보내기' — 서버 현재 행을 그대로 두고 두 컬럼만 바꾼 payload.

    신뢰 조건(하나라도 실패하면 blocked, 기본값 추정 없음):
      levels 행 id · 원본 행 스냅샷 존재 · 서버 행 존재·dict·두 컬럼 존재 ·
      서버 행(map/시드/etime/id 제외)이 스냅샷과 같음 · 서버 map 해시 = sourceMapSha256.
    payload = 두 시드 필드만 (부분 수정, §9). 서버 행 전체 재전송은 하지 않는다.
    """
    res: Dict[str, Any] = {"target_id": level_id, "blocked": True}
    m = _LEVEL_ID.match(level_id or "")
    if not m:
        res["reason"] = "not_level_row"
        return res
    level = int(m.group(1))
    try:
        snap = load_source_rows()["rows"].get(level_id)
        entry = load_catalog()["_byLevel"].get(level)
    except CatalogError as e:
        res.update({"reason": "catalog_error", "detail": str(e)})
        return res
    if snap is None or entry is None:
        res["reason"] = "no_snapshot"
        return res
    if server_row is None:
        res["reason"] = "no_server_row"
        return res
    if not isinstance(server_row, dict):
        res["reason"] = "server_row_invalid"
        return res
    if any(f not in server_row for f in SEED_FIELDS):
        res["reason"] = "no_seed_column"
        return res
    diff = row_diff(server_row, snap)
    if diff:
        res.update({"reason": "server_row_differs", "detail": ",".join(diff[:8])})
        return res
    msha = _server_map_sha(server_row.get("map"))
    if msha is None:
        res["reason"] = "server_map_unverifiable"
        return res
    if msha != entry["sourceMapSha256"]:
        res["reason"] = "server_map_differs"
        return res
    seeds = _seed_values(level, level_json, townpop)
    # [§9] 전체 행 재전송 금지 — 2026-10-20 L159 시험에서 null rewardList 가 [["null",0,0,0]] 로 바뀌었다.
    # payload 는 두 시드 필드만(부분 수정). 실제 전송은 PARTIAL_UPDATE_VERIFIED 가 True 일 때만.
    payload = {"ddaEasySeeds": seeds["ddaEasySeeds"], "ddaHardSeeds": seeds["ddaHardSeeds"]}
    before = (_norm(server_row.get("ddaEasySeeds")), _norm(server_row.get("ddaHardSeeds")))
    after = (seeds["ddaEasySeeds"], seeds["ddaHardSeeds"])
    change = ("same" if before == after else "clear" if after == ("", "") else
              "fill" if before == ("", "") else "change")
    res.update({"blocked": False, "reason": seeds["reason"], "change": change,
                "server": {"ddaEasySeeds": before[0], "ddaHardSeeds": before[1]},
                "ddaEasySeeds": after[0], "ddaHardSeeds": after[1],
                "serverDigest": row_digest(server_row), "payload": payload})
    return res


def write_guard(existing_row: Any, payload: Dict[str, Any], confirm: bool) -> Optional[str]:
    """실제 업로드 직전 안전 조건. 서버의 비어 있지 않은 시드를 비우거나 다른 값으로 바꾸려면 confirm 필요.
    반환: None=통과, 문자열=차단 사유."""
    if not isinstance(existing_row, dict):
        return None                      # 새 행(서버 값 없음)
    srv = tuple(_norm(existing_row.get(f)) for f in SEED_FIELDS)
    new = tuple(_norm(payload.get(f)) for f in SEED_FIELDS)
    if srv != ("", "") and srv != new and not confirm:
        return "needs_dda_confirm"
    return None


# ── 부분 수정 게이트 (§9) ────────────────────────────────────────────────────────
# real_array save(new=0)가 '보내지 않은 컬럼'을 보존한다는 근거(코드·문서·관측)가 아직 없다.
# 근거가 확보되고 사용자 승인이 나기 전까지 실제 부분 수정 전송은 차단한다(미리보기/dry-run 은 허용).
PARTIAL_UPDATE_VERIFIED = False


def assert_partial_payload(payload: Dict[str, Any]) -> None:
    """전송 payload 는 정확히 두 시드 필드만, 각 값은 5개 시드 문자열 또는 "" 여야 한다."""
    if set(payload) != set(SEED_FIELDS):
        raise ValueError(f"partial payload keys must be exactly {SEED_FIELDS}: {sorted(payload)}")
    for f in SEED_FIELDS:
        if payload[f] != "" and not is_valid_seed_str(payload[f]):
            raise ValueError(f"invalid seed value for {f}")


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
