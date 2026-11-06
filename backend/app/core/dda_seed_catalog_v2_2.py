"""
DDA 시드 규격 v2 — ±1 접두3 규칙 정리 (v2_2 산출물부터).

왜 별도 파일인가: 기존 v2 모듈(dda_seed_catalog_v2.py)·실행기(dda_seed_bulk_v2_20261022.py)는 이미 만들어진
v2 manifest(dryrun_v2_20261022/*/manifest.json)의 codeSha256 로 바이트가 고정돼 있다. 그 파일을 고치면 그 경로가
'코드 변경됨'으로 멈추므로, v2_2 규칙은 이 신규 모듈에만 둔다(기존 함수는 재사용만).

±1(ddaEasySeeds/ddaHardSeeds) 필드 판정 — 하드 FAIL(spec_pm1_not_prefix) 대신 분류:
  · keep            확정 3개 == catalog v1 5개(= 구규격 서버 값)의 앞 3개 → 서버 값 그대로(값 변경 없음).
  · planned_change  확정 3개가 앞 3개가 아님 → 서버 5개를 정렬·덮어쓰기 하지 않는다. 제안값만 기록:
                      write3   = 확정 3개로 5→3 쓰기
                      reorder5 = 확정 3개를 앞으로, 나머지는 원래 순서 보존(확정 3개가 5개에 모두 포함될 때만)
                    실제 적용은 기본 비활성(정책 미결) — 실행기에서 명시 플래그 없으면 차단.
  · FAIL            확정 3개의 근거 결속 실패(manifest sha 고정·파일 sha·레벨 조건해시 재계산·시드별 condSha N±k 재계산·
                    형식·중복·manifest 의 pm1ServerPrefixMismatch 목록과 불일치) → CatalogError.
"""
import csv
import hashlib
import json
import os
from collections import Counter
from typing import Any, Dict, Iterable, Optional, Tuple

from . import dda_seed_catalog as v1
from . import dda_seed_catalog_v2 as v2

PM1_FIELDS, PM2_FIELDS, SEED_FIELDS = v2.PM1_FIELDS, v2.PM2_FIELDS, v2.SEED_FIELDS
DELTA = {"ddaEasySeeds": -1, "ddaHardSeeds": 1, "ddaEasy2Seeds": -2, "ddaHard2Seeds": 2}

_DATA = os.path.dirname(v1.CATALOG_PATH)
SPEC_DIR_DEFAULT = os.path.join(_DATA, "spec_v2_2_variant4order_20261022")
SPEC_ID_DEFAULT = "dda_seed_spec_v2_2_variant4order_20261022"
SPEC_MANIFEST_SHA256_DEFAULT = "a803dc2e84cb74d2275d57f2581af151851f85581d8fb15375b3df8962bdc99d"
SPEC_SUMS_SHA256_DEFAULT = "b80ec912fb07eb179714bc9d7639d8cfb7fa926ca3971c73173635d1652a5330"
# 시드별 condSha256 재계산 근거(t0base 행 + levels.csv). levels.csv sha 는 spec manifest inputs.levelsCsv 로 고정.
T0_RUN_DEFAULT = os.path.normpath(os.path.join(
    _DATA, "..", "pv_sandbox", "dda_t0_all_20261020", "runs", "run_20261020_130623"))

PLANNED_MODES = ("write3", "reorder5")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pm1_rule(confirmed3: str, catalog5: str) -> Dict[str, Any]:
    """확정 3개 vs catalog 5개(구규격 서버 값) 관계."""
    c3, c5 = confirmed3.split(","), catalog5.split(",")
    if c3 == c5[:3]:
        return {"kind": "keep", "confirmed3": confirmed3, "catalog5": catalog5}
    pos = [c5.index(x) + 1 if x in c5 else None for x in c3]
    n_in = sum(p is not None for p in pos)
    reorder = ",".join(c3 + [x for x in c5 if x not in c3]) if n_in == 3 else None
    return {"kind": "planned_change", "confirmed3": confirmed3, "catalog5": catalog5,
            "positionsIn5": pos, "containedIn5": n_in,
            "inServer5": "all" if n_in == 3 else ("partial" if n_in else "none"),
            "resolution": "reorder5_possible" if reorder else "write3_required",
            "proposals": {"write3": confirmed3, "reorder5": reorder}}


def pm1_field_state(field: str, server_value: Any, rule: Dict[str, Any],
                    mode: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """±1 필드 (state, 보낼 값). 보낼 값 None = payload 제외(서버 기존 값 유지, v1 unsent 규칙).
    keep 규칙:  서버 = catalog5 또는 확정3 → keep(같은 값 재전송) / 빈 값 → fill(catalog5, 문서 48 §7-3) / 그 외 conflict.
    planned 규칙: 서버 = catalog5 → planned_change(보내지 않음) / 빈 값 → planned_change_empty(보내지 않음, catalog5 로 채우지 않음)
                서버 = 확정3 또는 reorder5 → keep(이미 해결) / 그 외 conflict.
                mode(write3|reorder5) 가 주어지면 planned 상태를 planned_write 로 바꾸고 제안값을 보냄
                (제안값 없음 = planned_unresolvable). mode 사용 manifest 는 실행기에서 별도 플래그 없이는 차단."""
    sv = "" if server_value is None else server_value
    if rule["kind"] == "keep":
        if sv in (rule["catalog5"], rule["confirmed3"]) and v2.is_valid_seed_str(sv, v2.ALLOWED_COUNTS[field]):
            return "keep", sv
        if sv == "":
            return "fill", rule["catalog5"]
        return "conflict", None
    resolved = [v for v in (rule["confirmed3"], rule["proposals"]["reorder5"]) if v]
    if sv in resolved and v2.is_valid_seed_str(sv, v2.ALLOWED_COUNTS[field]):
        return "keep", sv
    if sv == rule["catalog5"] or sv == "":
        st = "planned_change" if sv else "planned_change_empty"
        if mode is None:
            return st, None
        if mode not in PLANNED_MODES:
            raise ValueError(f"planned mode {mode}")
        val = rule["proposals"][mode]
        return ("planned_write", val) if val else ("planned_unresolvable", None)
    return "conflict", None


def _levels_file_from_sums(sums: Dict[str, str]) -> str:
    c = [n for n in sums if n.startswith("levels_spec_") and n.endswith(".json") and "/" not in n]
    if len(c) != 1:
        raise v1.CatalogError(f"spec_levels_file_ambiguous: {c}")
    return c[0]


def load_spec(spec_dir: str = SPEC_DIR_DEFAULT, manifest_sha256: str = SPEC_MANIFEST_SHA256_DEFAULT,
              sums_sha256: str = SPEC_SUMS_SHA256_DEFAULT, t0_run: str = T0_RUN_DEFAULT,
              levels_file: Optional[str] = None, hold_levels: Iterable[int] = ()) -> Dict[str, Any]:
    """v2_x 산출물 로드 + 결속 검사. ±1 비접두는 FAIL 이 아니라 pm1Rule 로 분류. 결속 실패 시 CatalogError."""
    try:
        mbytes = open(os.path.join(spec_dir, "manifest.json"), "rb").read()
        sbytes = open(os.path.join(spec_dir, "SHA256SUMS"), "rb").read()
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
    lf = levels_file or _levels_file_from_sums(sums)
    try:
        lbytes = open(os.path.join(spec_dir, lf), "rb").read()
        csv_bytes = open(os.path.join(t0_run, "config", "levels.csv"), "rb").read()
    except OSError as e:
        raise v1.CatalogError(f"spec_missing: {e}") from e
    if sums.get("manifest.json") != manifest_sha256 or sums.get(lf) != _sha(lbytes):
        raise v1.CatalogError("spec_file_sha_mismatch")
    man = json.loads(mbytes)
    if man.get("inputs", {}).get("catalog", {}).get("sha256") != v1.CATALOG_SHA256:
        raise v1.CatalogError("spec_catalog_binding_mismatch")
    fc = man.get("fieldContract", {})
    if set(fc) != set(SEED_FIELDS) or any(fc[f].get("delta") != DELTA[f] or fc[f].get("count") != 3 for f in SEED_FIELDS):
        raise v1.CatalogError("spec_field_contract_mismatch")
    if man.get("inputs", {}).get("levelsCsv") != _sha(csv_bytes):
        raise v1.CatalogError("spec_levels_csv_binding_mismatch")
    lcsv = {int(r["level"]): r for r in csv.DictReader(csv_bytes.decode().splitlines())}
    cat = v1.load_catalog()["_byLevel"]
    src = v1.load_source_rows()["rows"]
    holds = set(int(x) for x in hold_levels) | set(int(x) for x in man.get("holdLevels", []))
    by, rules, glob = {}, {}, Counter()
    for s in json.loads(lbytes):
        n = int(s["level"])
        by[n] = s
        if s.get("hold") or s.get("holdLevel"):
            holds.add(n)
        if s.get("status") not in ("ready4", "partial"):
            continue
        e = cat.get(n)
        if e is None or e["status"] != "candidate" or e["sourceConditionHash"] != s["sourceConditionHash"] \
                or e["sourceMapSha256"] != s["sourceMapSha256"] or e["N"] != s["N"]:
            raise v1.CatalogError(f"spec_level_binding_mismatch: {n}")
        if v2.source_condition_hash(src[f"level_{n}"]) != s["sourceConditionHash"]:
            raise v1.CatalogError(f"spec_condition_hash_recompute_mismatch: {n}")
        try:
            t0 = json.loads(open(os.path.join(t0_run, "out", "t0base", f"level_{n}.json"), "rb").read())
        except OSError as ex:
            raise v1.CatalogError(f"spec_t0base_missing: {n}") from ex
        row0 = t0["row"]
        if v2.source_condition_hash(row0) != s["sourceConditionHash"] or t0["origMapSha256"] != s["sourceMapSha256"]:
            raise v1.CatalogError(f"spec_t0base_binding_mismatch: {n}")
        orig = int(row0["randSeed"])
        if "originalRandSeed" in s and int(s["originalRandSeed"]) != orig:
            raise v1.CatalogError(f"spec_original_seed_mismatch: {n}")
        lvl_seeds = []
        for f in SEED_FIELDS:
            v = s["fields"][f]
            if v == "":
                if f in PM1_FIELDS or f not in s.get("holds", {}):
                    raise v1.CatalogError(f"spec_empty_without_hold: {n}.{f}")
                continue
            if not v2.is_valid_seed_str(v, (3,)) or len(set(v.split(","))) != 3:
                raise v1.CatalogError(f"spec_seed_format: {n}.{f}")
            ut = e["N"] + DELTA[f]
            if s.get("useTileCount", {}).get(f) != ut or not 1 <= ut <= 15:
                raise v1.CatalogError(f"spec_use_tile_count_binding: {n}.{f}")
            cs = s.get("condSha256", {}).get(f) or []
            toks = v.split(",")
            if len(cs) != 3:
                raise v1.CatalogError(f"spec_cond_sha_missing: {n}.{f}")
            for tok, h in zip(toks, cs):
                eff = dict(row0)
                eff["useTileCount"] = str(ut)
                eff["randSeed"] = tok
                if _sha(v1.dump({"sourceCommit": lcsv[n]["sourceCommit"], "t0baseMapSha256": lcsv[n]["t0baseMapSha256"],
                                 "row": eff})) != h:
                    raise v1.CatalogError(f"spec_cond_sha_binding: {n}.{f}.{tok}")
            lvl_seeds += [int(t) for t in toks]
        if orig in lvl_seeds or len(set(lvl_seeds)) != len(lvl_seeds):
            raise v1.CatalogError(f"spec_seed_not_unique_in_level: {n}")
        glob.update(lvl_seeds)
        rules[n] = {f: pm1_rule(s["fields"][f], e[f]) for f in PM1_FIELDS}
    dup = [k for k, c in glob.items() if c > 1]
    if dup:
        raise v1.CatalogError(f"spec_global_seed_dup: {len(dup)}")
    planned = sorted((n, f) for n, r in rules.items() for f, x in r.items() if x["kind"] == "planned_change")
    declared = man.get("pm1ServerPrefixMismatch")
    if declared is not None and sorted(declared) != sorted(f"L{n}.{f}" for n, f in planned):
        raise v1.CatalogError("spec_pm1_planned_list_mismatch")
    return {"id": man.get("id"), "dir": spec_dir, "manifestSha256": manifest_sha256, "sumsSha256": sums_sha256,
            "levelsFile": lf, "levelsSha256": _sha(lbytes), "levelsCsvSha256": _sha(csv_bytes), "manifest": man,
            "_byLevel": by, "pm1Rule": rules, "holdLevels": sorted(holds),
            "pm1Planned": [f"L{n}.{f}" for n, f in planned]}
