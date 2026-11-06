"""
DDA 시드 규격 v2 (3×4, 문서 48) — 업로드 판정 규칙.

- v1 모듈(dda_seed_catalog.py)은 바꾸지 않는다: 구규격 manifest(bulk_prepare_20261020_1906 / _20261022_1054)가
  codeSha256 로 v1 파일 바이트를 고정하므로, v1 파일을 고치면 그 실행 경로가 '코드 변경됨'으로 멈춘다.
- 필드: 기존 ddaEasySeeds(−1)/ddaHardSeeds(+1) + 신규 ddaEasy2Seeds(−2)/ddaHard2Seeds(+2).
  · 기존 2필드: 서버에 5개(catalog v1)로 이미 있으면 그대로(3개로 줄이지 않음). 비어 있으면 catalog v1 5개로 채움
    (문서 48 §7-3). 서버 값이 3개면 v2 산출물 ±1(= catalog 접두 3) 과 같을 때만 유지.
  · 신규 2필드: 정확히 3개. v2 산출물에서 보류("")인 필드(L358·L541 hard2 등)는 payload 에 넣지 않는다
    → 서버 기존 값 유지(READBACK_RULES v1 'unsent' 규칙, L159 실측 근거).
- sourceConditionHash: 행 − {map, ddaEasySeeds, ddaHardSeeds, ddaEasy2Seeds, ddaHard2Seeds}
  (게임 DdaMapTransformer.IsCondExcluded 와 같은 목록. 신규 컬럼이 없는 행에서는 v1 해시와 같다).
- v2 산출물은 디렉터리 + manifest sha256 + SHA256SUMS sha256 로 고정한다(측정 후 새 버전이 오면 그 값으로 교체).
"""
import hashlib
import json
import os
import re
from typing import Any, Dict, Optional, Tuple

from . import dda_seed_catalog as v1

PM1_FIELDS = v1.SEED_FIELDS                                  # ("ddaEasySeeds", "ddaHardSeeds")
PM2_FIELDS = ("ddaEasy2Seeds", "ddaHard2Seeds")
SEED_FIELDS = PM1_FIELDS + PM2_FIELDS
COND_HASH_EXCLUDE = ("map",) + SEED_FIELDS
# 서버 행에만 있는 키(출시 행 스냅샷에 없음, map 은 sourceMapSha256 로 별도 검사). 이 밖의 키가 서버 행에 있으면 보류.
SERVER_ONLY_KEYS = ("idx", "etime", "", "field4", "map") + SEED_FIELDS
# 서버에 있을 때 허용하는 개수: 기존 필드 5(구규격·구클라 호환) 또는 3(새 규격), 신규 필드 3
ALLOWED_COUNTS = {"ddaEasySeeds": (5, 3), "ddaHardSeeds": (5, 3), "ddaEasy2Seeds": (3,), "ddaHard2Seeds": (3,)}
WRITE_COUNT = {"ddaEasySeeds": 5, "ddaHardSeeds": 5, "ddaEasy2Seeds": 3, "ddaHard2Seeds": 3}

SPEC_DIR_DEFAULT = os.path.normpath(os.path.join(
    os.path.dirname(v1.CATALOG_PATH), "spec_v2_3x4_20261022"))
SPEC_ID_DEFAULT = "dda_seed_spec_v2_3x4_20261022"
SPEC_MANIFEST_SHA256_DEFAULT = "1a8b57da10c3d61b96659671ba32c220d9e53e873899f7851e46f92f058344ba"
SPEC_SUMS_SHA256_DEFAULT = "4e01190bda2064c4647c65369e1a984c7b2f4dc1fae9fd4eb8ce9734862c0fb5"
SPEC_LEVELS_FILE = "levels_spec_v2.json"

_SEED_TOKEN = re.compile(r"^[1-9][0-9]*$")


def is_valid_seed_str(value: Any, counts: Tuple[int, ...]) -> bool:
    """개수 ∈ counts, 쉼표 구분·공백 없음, 각 1..Int32.Max, 부호·선행0·빈 토큰 불허."""
    if not isinstance(value, str) or not value:
        return False
    toks = value.split(",")
    return len(toks) in counts and all(_SEED_TOKEN.match(t) and int(t) <= v1._INT32_MAX for t in toks)


def source_condition_hash(row: Dict[str, Any]) -> str:
    """sha256(dump(행 − {map, 시드 4필드}))."""
    return hashlib.sha256(v1.dump({k: v for k, v in row.items() if k not in COND_HASH_EXCLUDE})).hexdigest()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_spec(spec_dir: str = SPEC_DIR_DEFAULT, manifest_sha256: str = SPEC_MANIFEST_SHA256_DEFAULT,
              sums_sha256: str = SPEC_SUMS_SHA256_DEFAULT) -> Dict[str, Any]:
    """v2 산출물 로드 + 고정 검사(manifest sha, SHA256SUMS sha, 레벨 파일 sha, catalog v1 결속, ±1 접두 3).
    실패 시 v1.CatalogError."""
    try:
        mbytes = open(os.path.join(spec_dir, "manifest.json"), "rb").read()
        sbytes = open(os.path.join(spec_dir, "SHA256SUMS"), "rb").read()
        lbytes = open(os.path.join(spec_dir, SPEC_LEVELS_FILE), "rb").read()
    except OSError as e:
        raise v1.CatalogError(f"spec_missing: {e}") from e
    if _sha(mbytes) != manifest_sha256:
        raise v1.CatalogError(f"spec_manifest_sha_mismatch: {_sha(mbytes)}")
    if _sha(sbytes) != sums_sha256:
        raise v1.CatalogError(f"spec_sums_sha_mismatch: {_sha(sbytes)}")
    sums = {}
    for line in sbytes.decode().splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            sums[name.strip()] = h
    if sums.get("manifest.json") != manifest_sha256 or sums.get(SPEC_LEVELS_FILE) != _sha(lbytes):
        raise v1.CatalogError("spec_file_sha_mismatch")
    man = json.loads(mbytes)
    if (man.get("inputs", {}).get("catalog", {}).get("sha256")) != v1.CATALOG_SHA256:
        raise v1.CatalogError("spec_catalog_binding_mismatch")
    if set(man.get("fieldContract", {})) != set(SEED_FIELDS):
        raise v1.CatalogError("spec_field_contract_mismatch")
    cat = v1.load_catalog()
    by = {}
    for s in json.loads(lbytes):
        n = int(s["level"])
        e = cat["_byLevel"].get(n)
        if s.get("status") in ("ready4", "partial"):
            if e is None or e["status"] != "candidate" or e["sourceConditionHash"] != s["sourceConditionHash"] \
                    or e["sourceMapSha256"] != s["sourceMapSha256"] or e["N"] != s["N"]:
                raise v1.CatalogError(f"spec_level_binding_mismatch: {n}")
            for f in PM1_FIELDS:
                if s["fields"][f] != ",".join(e[f].split(",")[:3]):
                    raise v1.CatalogError(f"spec_pm1_not_prefix: {n}.{f}")
            for f in SEED_FIELDS:
                if s["fields"][f] != "" and not is_valid_seed_str(s["fields"][f], (3,)):
                    raise v1.CatalogError(f"spec_seed_format: {n}.{f}")
        by[n] = s
    return {"id": man.get("id"), "dir": spec_dir, "manifestSha256": manifest_sha256, "sumsSha256": sums_sha256,
            "levelsSha256": _sha(lbytes), "manifest": man, "_byLevel": by}


def field_targets(entry: Dict[str, Any], spec_entry: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """필드별 쓰기 목표. 기존 필드 = catalog v1 5개, 신규 필드 = v2 산출물 3개. None = 미대상(보류, payload 제외)."""
    out: Dict[str, Optional[str]] = {f: entry[f] for f in PM1_FIELDS}
    for f in PM2_FIELDS:
        out[f] = spec_entry["fields"][f] or None
    return out


def field_state(field: str, server_value: Any, target: Optional[str], spec_value: str) -> Tuple[str, Optional[str]]:
    """(state, 보낼 값). state: keep / fill / not_target / conflict.
    keep: 서버 값이 목표(5) 또는 v2 접두 3과 같음 → 서버 값 그대로 다시 보냄(보낸 문자열 → 같은 문자열).
    fill: 서버 값 없음/빈 값 → 목표. not_target: 목표 없음 → 보내지 않음. conflict: 그 외(형식 오류 포함)."""
    if target is None:
        return "not_target", None
    sv = "" if server_value is None else server_value
    if sv == target or (sv == spec_value and is_valid_seed_str(sv, ALLOWED_COUNTS[field])):
        return "keep", sv
    if sv == "":
        return "fill", target
    return "conflict", None


# ── 업로드 후 서버 읽기값 예측 v2 ─────────────────────────────────────────────────
READBACK_RULES_VERSION = "dda_readback_rules.v2"
READBACK_RULES = dict(v1.READBACK_RULES)
READBACK_RULES.update({
    "ddaEasy2Seeds,ddaHard2Seeds": "보낸 문자열 → 같은 문자열 (가정 — 실측 없음. 실제 쓰기 첫 1행 probe 로 확인 전 청크 금지)",
    "ddaEasy2Seeds,ddaHard2Seeds(column_absent)": "서버 행에 컬럼이 없으면 보내지 않음(no_v2_column 보류) — 컬럼 생성 표현 미확인",
    "unsent(ddaEasy2Seeds,ddaHard2Seeds)": "보류 필드는 보내지 않음 → 서버 기존값 유지 (v1 unsent 규칙 준용, L159 실측)",
})
READBACK_UNVERIFIED = ("ddaEasy2Seeds,ddaHard2Seeds",)


def predict_readback(payload: Dict[str, Any], base_row: Dict[str, Any]):
    """v1 규칙 + 신규 2필드(서버 행에 컬럼이 있을 때만 '같은 문자열', 없으면 미확인)."""
    rest = {k: v for k, v in payload.items() if k not in PM2_FIELDS}
    pred, unverified = v1.predict_readback(rest, base_row)
    for k in PM2_FIELDS:
        if k in payload:
            if k in base_row:
                pred[k] = payload[k]
            else:
                unverified.append(k)
    return pred, unverified
