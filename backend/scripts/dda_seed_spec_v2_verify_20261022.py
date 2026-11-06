#!/usr/bin/env python3
"""DDA 시드 규격 v2 (3x4) 업로드 전 검증 — 로컬 파일만 읽음 (서버 읽기·쓰기 없음, 봇 없음).

입력: spec_v2_3x4_20261022/{levels_spec_v2.json, pm1_selection.csv, pm2_candidates.csv, manifest.json}
      + run_20261020_130623 t0base/levels.csv, catalog v1, 구규격 bulk_prepare_20261022_1054 (manifest·results·snapshot),
        L159 업로드 증거 step2/after.raw.json
출력: spec_v2_3x4_20261022/verify/{precheck.json, expected_payload_4fields.json}, SHA256SUMS (폴더 전체)
사용: cd backend && .venv/bin/python scripts/dda_seed_spec_v2_verify_20261022.py
"""
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "data/dda_seeds/spec_v2_3x4_20261022"
RUN = BACKEND / "data/pv_sandbox/dda_t0_all_20261020/runs/run_20261020_130623"
CATALOG = BACKEND / "data/dda_seeds/dda_t0_seed_catalog.v1.json"
OLD = BACKEND / "data/dda_seeds/bulk_prepare_20261022_1054"
OLD_SHA = "310d210575b0f82b9b2f4b83cf251644bd7825ce7b8c1ca8c96dba358b45b7fd"
OLD_1906 = BACKEND / "data/dda_seeds/bulk_prepare_20261020_1906"
OLD_1906_SHA = "fbd24f9feed26d93a19bcef6609f5a524971329583fd302b135174c024af936d"
L159_AFTER = BACKEND / "data/dda_seeds/server_apply_20261020_1822/l159_upload_via_existing/step2/after.raw.json"
FIELDS = {"ddaEasySeeds": -1, "ddaHardSeeds": +1, "ddaEasy2Seeds": -2, "ddaHard2Seeds": +2}
OLD_FIELDS = ("ddaEasySeeds", "ddaHardSeeds")
TOKEN = re.compile(r"^[1-9][0-9]*$")
INT32 = 2**31 - 1


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def fmt_ok(v):
    toks = v.split(",") if isinstance(v, str) and v else []
    return len(toks) == 3 and all(TOKEN.match(t) and int(t) <= INT32 for t in toks) and len(set(toks)) == 3


def server_rows(path):
    o = json.loads(Path(path).read_text())
    if isinstance(o, dict) and "__keys" in o:
        ks = o["__keys"]
        return {str(r[ks.index("id")]): dict(zip(ks, r)) for r in o["__vals"]}
    if isinstance(o, dict):
        return {k: v for k, v in o.items() if isinstance(v, dict)}
    return {r["id"]: r for r in o}


def main():
    levels = json.loads((OUT / "levels_spec_v2.json").read_text())
    catalog = {e["level"]: e for e in json.loads(CATALOG.read_bytes())["levels"]}
    lcsv = {int(r["level"]): r for r in csv.DictReader((RUN / "config/levels.csv").open())}
    pm1 = list(csv.DictReader((OUT / "pm1_selection.csv").open()))
    pm2 = list(csv.DictReader((OUT / "pm2_candidates.csv").open()))
    resolved = {}
    for r in pm1:
        if r["selected"] == "True":
            resolved[(int(r["level"]), r["randSeed"])] = r["resolvedMapSha256"]
    for r in pm2:
        if r["selected"] == "True":
            resolved[(int(r["level"]), r["randSeed"])] = r["resolvedMapSha256"]

    errs, glob_seeds = Counter(), Counter()
    per_level_err = {}
    payload = {}
    for rec in levels:
        L, e = rec["level"], []
        vals = rec["fields"]
        if rec["catalogStatus"] != "candidate":
            if any(vals.values()):
                e.append("non_candidate_has_value")
            per_level_err[L] = e
            continue
        t0 = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
        row0 = t0["row"]
        ce = catalog[L]
        if sha(dump({k: v for k, v in row0.items() if k not in ("map",) + OLD_FIELDS})) != ce["sourceConditionHash"] \
                or rec["sourceConditionHash"] != ce["sourceConditionHash"]:
            e.append("source_condition_hash")
        if t0["origMapSha256"] != ce["sourceMapSha256"] or rec["sourceMapSha256"] != ce["sourceMapSha256"]:
            e.append("source_map_sha")
        N = ce["N"]
        orig = int(row0["randSeed"])
        seeds_lvl, rmaps = [], []
        for f, dl in FIELDS.items():
            v = vals[f]
            if not v:
                if f not in rec["holds"]:
                    e.append(f"{f}:empty_without_hold")
                continue
            if not fmt_ok(v):
                e.append(f"{f}:format")
                continue
            toks = [int(t) for t in v.split(",")]
            if orig in toks:
                e.append(f"{f}:equals_original_seed")
            if rec["useTileCount"].get(f) != N + dl or not 1 <= N + dl <= 15:
                e.append(f"{f}:useTileCount")
            for s, cs_ in zip(toks, rec["condSha256"][f]):
                eff = dict(row0)
                eff["useTileCount"] = str(N + dl)
                eff["randSeed"] = str(s)
                if sha(dump({"sourceCommit": lcsv[L]["sourceCommit"], "t0baseMapSha256": lcsv[L]["t0baseMapSha256"],
                             "row": eff})) != cs_:
                    e.append(f"{f}:condSha256")
                rm = resolved.get((L, str(s)))
                if not rm:
                    e.append(f"{f}:not_in_selected_candidates")
                rmaps.append(rm)
            seeds_lvl += toks
        if len(seeds_lvl + [orig]) != len(set(seeds_lvl + [orig])):
            e.append("seed_not_unique_in_level")
        if len(rmaps) != len(set(rmaps)):
            e.append("resolved_map_not_unique_in_level")
        if rec["status"] == "ready4" and len(set(seeds_lvl + [orig])) != 13:
            e.append("ready4_not_13")
        # ±1 3개 = catalog 5 의 접두 3개인지 (구규격 값과의 관계)
        for f in OLD_FIELDS:
            if vals[f] and ce[f].split(",")[:3] != vals[f].split(","):
                e.append(f"{f}:not_prefix_of_catalog5")
        glob_seeds.update(seeds_lvl)
        per_level_err[L] = e
        payload[rec["id"]] = {f: vals[f] for f in FIELDS}
    for k, n in glob_seeds.items():
        if n > 1:
            errs["global_seed_dup"] += 1
    for L, e in per_level_err.items():
        for x in e:
            errs[x.split("(")[0]] += 1

    # 구규격 업로드(550 완료)·L159·L158 과의 관계 — 로컬 증거만
    old_ok = [json.loads(x)["id"] for x in (OLD / "results.jsonl").read_text().splitlines()
              if json.loads(x).get("status") == "ok"]
    old_entries = {e["id"]: e for e in json.loads((OLD / "manifest.json").read_bytes())["entries"]}
    byid = {r["id"]: r for r in levels}
    rel = Counter()
    for i in old_ok:
        p = old_entries[i]["payload"]
        r = byid[i]
        ce = catalog[r["level"]]
        for f in OLD_FIELDS:
            if p[f] != ce[f]:
                rel["old_payload_ne_catalog5"] += 1
            elif r["fields"][f] and p[f].split(",")[:3] == r["fields"][f].split(","):
                rel[f"{f}:new3_is_prefix_of_uploaded5"] += 1
            else:
                rel[f"{f}:other"] += 1
    snap = server_rows(OLD / "server_levels_snapshot.raw.json")
    sample = next(iter(snap.values()))
    l159 = server_rows(L159_AFTER)["level_159"]
    s158 = snap.get("level_158", {})
    special = {
        "L159": {"serverAfterUpload": {f: l159.get(f) for f in OLD_FIELDS},
                 "equalsCatalog5": all(l159.get(f) == catalog[159][f] for f in OLD_FIELDS),
                 "new": {f: byid["level_159"]["fields"][f] for f in FIELDS}},
        "L158": {"serverSnapshot1054": {f: s158.get(f) for f in OLD_FIELDS},
                 "equalsCatalog5": all(s158.get(f) == catalog[158][f] for f in OLD_FIELDS),
                 "note": "condition mismatch (useInRandomizer/useTeleportInRandomizer \"\") — separate approval",
                 "new": {f: byid["level_158"]["fields"][f] for f in FIELDS}},
    }
    # 구규격 폴더 보존 확인 (복사 없음 — 경로·sha 만 기록)
    def sums(d):
        r = subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=d, capture_output=True, text=True)
        failed = [ln for ln in r.stdout.splitlines() if not ln.endswith(": OK")]
        return {"rc": r.returncode, "notOK": failed}
    preserve = {
        str(OLD.relative_to(BACKEND)): {"manifestSha256": sha((OLD / "manifest.json").read_bytes()),
                                        "expected": OLD_SHA, "sha256sums": sums(OLD),
                                        "resultsOk": len(old_ok), "firstOk": old_ok[0], "lastOk": old_ok[-1],
                                        "note": "apply.log is appended after SHA256SUMS was written (11:11 stop) "
                                                "→ its mismatch is expected; no file modified by this run"},
        str(OLD_1906.relative_to(BACKEND)): {"manifestSha256": sha((OLD_1906 / "manifest.json").read_bytes()),
                                             "expected": OLD_1906_SHA, "sha256sums": sums(OLD_1906)},
    }
    nonempty = [r for r in levels if any(r["fields"].values())]
    pre = {
        "scope": "local files only; no server read/write; no bot",
        "levels": len(levels), "levelsWithAnyField": len(nonempty),
        "byStatus": dict(Counter(r["status"] for r in levels)),
        "errors": dict(errs), "errorLevels": {str(L): e for L, e in per_level_err.items() if e},
        "globalUniqueSeeds": len(glob_seeds),
        "checks": ["format: 3 positive Int32, comma, no spaces/leading zero, no dup in field",
                   "not equal original randSeed", "13 distinct per ready4 level (orig + 12)",
                   "global seed uniqueness", "sourceConditionHash/sourceMapSha256 = catalog v1 (recomputed from t0base row)",
                   "useTileCount = N + delta within 1..15", "condSha256 recomputed per seed",
                   "resolved map distinct within level", "±1 3 = first 3 of catalog 5 (= old-spec server value)"],
        "oldSpecRelation": {"uploadedOk": len(old_ok), **dict(rel)},
        "special": special,
        "serverSnapshotColumns1054": {"keys": len(sample), "hasNewFields": [f for f in ("ddaEasy2Seeds", "ddaHard2Seeds")
                                                                             if f in sample]},
        "preserve": preserve,
        "readbackRulesExtensionNeeded": [
            "ddaEasy2Seeds,ddaHard2Seeds: '보낸 문자열 → 같은 문자열' 미실측 (규칙 v1 은 두 필드만) → 1행 실측 후 v2 규칙에 추가",
            "서버 전용 키 집합에 신규 2컬럼 추가(현재 실행기 기준 {idx, etime, '', field4, ddaEasySeeds, ddaHardSeeds})",
            "3개 형식 검사(현재 is_valid_seed_str 은 정확히 5개)"],
        "expectedPayloadNote": "4-field values to append to the existing full-row converter payload (§47-13 path); "
                               "NOT sent. Holds -> \"\" per field.",
    }
    (OUT / "verify").mkdir(exist_ok=True)
    (OUT / "verify/precheck.json").write_bytes(json.dumps(pre, ensure_ascii=False, indent=1).encode())
    (OUT / "verify/expected_payload_4fields.json").write_bytes(json.dumps(payload, ensure_ascii=False, indent=0).encode())
    lines = [f"{sha(p.read_bytes())}  {p.relative_to(OUT)}" for p in sorted(OUT.rglob("*"))
             if p.is_file() and p.name != "SHA256SUMS" and p.suffix != ".log"]
    (OUT / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: pre[k] for k in ("levels", "levelsWithAnyField", "byStatus", "errors", "globalUniqueSeeds",
                                          "oldSpecRelation", "serverSnapshotColumns1054")}, ensure_ascii=False, indent=1))
    print(json.dumps(special, ensure_ascii=False))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "note"} for k, v in preserve.items()}, indent=1))


if __name__ == "__main__":
    main()
