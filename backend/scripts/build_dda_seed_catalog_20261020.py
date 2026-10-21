#!/usr/bin/env python3
"""맵에디터 DDA 시드 개발용 목록 생성 (2026-10-20, 문서 47).

입력(읽기 전용, 게임측 dda_runtime_t0 산출물 디렉터리):
  <src>/server/server_levels_dda_columns.csv   id,ddaEasySeeds,ddaHardSeeds (후보 1216만 값)
  <src>/verify/dda_t0_verify_list.json         레벨별 status·sourceMapSha256·N·사유
  <src>/verify/cross_check.json                위 두 파일 sha256 교차 기록
출력:
  backend/data/dda_seeds/dda_t0_seed_catalog.v1.json
  (sha256 은 app/core/dda_seed_catalog.py::CATALOG_SHA256 에 고정 — 재생성 시 함께 갱신)

시드·N·해시는 입력 값 그대로 옮긴다(새 생성/선별/교체 없음).
사용: python3 backend/scripts/build_dda_seed_catalog_20261020.py --src <dda_runtime_t0 out dir>
      python3 backend/scripts/build_dda_seed_catalog_20261020.py --source-rows <live_copy/b741f6a3/levels.json>
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

CATALOG_VERSION = "dda_seed_catalog.v1"
SEED_RE = re.compile(r"^[1-9][0-9]*$")
INT32_MAX = 2147483647
OUT = Path(__file__).resolve().parents[1] / "data" / "dda_seeds" / "dda_t0_seed_catalog.v1.json"


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def valid_seeds(s: str) -> bool:
    toks = s.split(",")
    return len(toks) == 5 and all(SEED_RE.match(t) and int(t) <= INT32_MAX for t in toks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="dda_runtime_t0 산출 디렉터리 (server/, verify/ 포함)")
    ap.add_argument("--source-rows", help="출시 levels 테이블 복호 사본(levels.json) → 원본 행 스냅샷 생성")
    a = ap.parse_args()
    if a.source_rows:
        return build_source_rows(Path(a.source_rows))
    if not a.src:
        ap.error("--src 또는 --source-rows 필요")
    src = Path(a.src)
    p_csv = src / "server" / "server_levels_dda_columns.csv"
    p_ver = src / "verify" / "dda_t0_verify_list.json"
    p_xc = src / "verify" / "cross_check.json"

    xc = json.loads(p_xc.read_text())
    sha_csv, sha_ver = sha_file(p_csv), sha_file(p_ver)
    if xc["serverCsv"]["sha256"] != sha_csv or xc["verifyList"]["sha256"] != sha_ver or xc["problems"]:
        print("cross_check 불일치 — 중단", file=sys.stderr)
        return 1

    ver = json.loads(p_ver.read_text())
    seeds = {}
    with p_csv.open() as f:
        for r in csv.DictReader(f):
            if r["ddaEasySeeds"] or r["ddaHardSeeds"]:
                seeds[r["id"]] = (r["ddaEasySeeds"], r["ddaHardSeeds"])

    levels, problems = [], []
    for e in sorted(ver["levels"], key=lambda x: x["level"]):
        out = {"level": e["level"], "status": e["status"], "sourceMapSha256": e["sourceMapSha256"],
               "sourceConditionHash": e["sourceConditionHash"]}
        if e["status"] == "candidate":
            pair = seeds.pop(e["levelId"], None)
            if pair is None or not all(valid_seeds(s) for s in pair):
                problems.append(f"{e['levelId']}: seeds missing/invalid")
                continue
            out.update({"N": e["N"], "ddaEasySeeds": pair[0], "ddaHardSeeds": pair[1]})
        else:
            out["reasons"] = e.get("reasons", [])
        levels.append(out)
    if seeds:
        problems.append(f"server csv 값이 있는데 후보가 아닌 id {len(seeds)}개: {sorted(seeds)[:5]}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    cat = {
        "catalogVersion": CATALOG_VERSION,
        "settingsVersion": ver["settingsVersion"],
        "transformVersion": ver["transformVersion"],
        "note": "DEV verification catalog for the map editor — NOT server columns. "
                "Only ddaEasySeeds/ddaHardSeeds go to the server levels table.",
        "source": {
            "dir": src.name,
            "server_levels_dda_columns.csv": sha_csv,
            "dda_t0_verify_list.json": sha_ver,
            "cross_check.json": sha_file(p_xc),
            "runId": ver["source"]["runId"],
            "baseCommit": ver["source"]["baseCommit"],
        },
        "contract": {
            "mapHash": "sha256(json.dumps(_convert_to_townpop_format(level_json)['map'], ensure_ascii=False, separators=(',',':')))",
            "sourceConditionHash": ver["contract"]["sourceConditionHash"],
            "seedColumns": ver["contract"]["seedColumns"],
        },
        "counts": {"levels": len(levels),
                   "byStatus": {s: sum(1 for x in levels if x["status"] == s)
                                for s in sorted({x["status"] for x in levels})}},
        "levels": levels,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(cat, ensure_ascii=False, separators=(",", ":")).encode()
    OUT.write_bytes(data)
    print(OUT, hashlib.sha256(data).hexdigest(), cat["counts"])
    return 0




# ── 원본 행 스냅샷 (2026-10-20 P1, 문서 47 §5) ─────────────────────────────────
# 시드만 내보내기의 신뢰 기준. 출시 levels 테이블(b741f6a3 복호 사본) 행을 자료형·키 순서 그대로 보존하고,
# 각 행의 sourceConditionHash 가 개발용 목록 값과 같은지 확인한다(다르면 중단). 서버 컬럼 아님.
ROWS_OUT = OUT.parent / "dda_t0_source_rows.v1.json"


def build_source_rows(levels_json: Path) -> int:
    cat = json.loads(OUT.read_bytes())
    t = json.loads(levels_json.read_text())
    ks = t["__keys"]
    rows = {str(r[0]): {ks[i]: r[i] for i in range(min(len(ks), len(r)))} for r in t["__vals"]}
    excl = ("map", "ddaEasySeeds", "ddaHardSeeds")
    out, problems = {}, []
    for e in cat["levels"]:
        lid = f"level_{e['level']}"
        row = rows.get(lid)
        if row is None:
            problems.append(f"{lid}: no row")
            continue
        h = hashlib.sha256(json.dumps({k: v for k, v in row.items() if k not in excl},
                                      ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if h != e["sourceConditionHash"]:
            problems.append(f"{lid}: condition hash mismatch")
            continue
        out[lid] = row
    if problems:
        print("\n".join(problems[:20]), file=sys.stderr)
        return 1
    doc = {"rowsVersion": "dda_t0_source_rows.v1", "catalogSha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
           "source": {"file": f"{levels_json.parent.name}/{levels_json.name}", "sha256": sha_file(levels_json)},
           "note": "Shipped levels-table rows (original types/key order) for DDA catalog levels; "
                   "each verified sourceConditionHash == catalog. Trust anchor for seed-only export. NOT server columns.",
           "rows": out}
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    ROWS_OUT.write_bytes(data)
    print(ROWS_OUT, hashlib.sha256(data).hexdigest(), len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
