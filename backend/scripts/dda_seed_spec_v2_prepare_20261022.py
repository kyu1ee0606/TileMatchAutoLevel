#!/usr/bin/env python3
"""DDA 시드 규격 v2 (3x4) 오프라인 준비 (2026-10-22) — 서버 쓰기·읽기 없음, 봇/솔버/난이도 측정 없음.

규격: ddaEasySeeds(N-1)·ddaHardSeeds(N+1)·ddaEasy2Seeds(N-2)·ddaHard2Seeds(N+2), 각 양의 Int32 3개(쉼표), 원본 포함 13종.
  - ±1: 기존 run_20261020_130623 후보 5개(= catalog v1 = 구규격 서버 업로드 값) 중 3개를 규칙으로 선정 (새 시드 없음).
  - ±2: 같은 t0base·같은 계약으로 N±2 후보 5개를 새 대역에서 1회 고정 추출 → 오프라인 배정 정합 검사
        (dda_t0_assign_check_20261020.py 와 같은 판정) → 같은 규칙으로 3개 선정. ±1 결과 재활용 없음.
  - 선정 규칙(양 방향 공통, 난이도 측정 없음): 배정 정합 PASS AND resolved map sha 가 레벨 내 고유 → cand 순서(=추출 순서,
    난이도와 무관) 앞 3개. 3개 미만이면 그 필드 보류. 'difficulty verified' 아님.
입력(읽기 전용): run_20261020_130623/{config, out/t0base}, assign_check_20261020_135511/per_variant.csv, catalog v1(sha 고정).
출력: backend/data/dda_seeds/spec_v2_3x4_20261022/ 아래만.
사용: cd backend && .venv/bin/python scripts/dda_seed_spec_v2_prepare_20261022.py
"""
import csv
import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
import dda_t0_assign_check_20261020 as ac  # noqa: E402  (cs_shuffle 단독 로드, 봇 import 없음)

RUN = ac.RUN
ASSIGN1 = RUN / "assign_check_20261020_135511/per_variant.csv"
CATALOG = BACKEND / "data/dda_seeds/dda_t0_seed_catalog.v1.json"
CATALOG_SHA = "57930b559bf935f076b1f77051dd2afc1ed95db60cd4f2cad0bae350fdfc5d13"
PKG = BACKEND / "data/pv_sandbox/pv_20261002_live3/dda_v24confirm_20261019/package_20261020_0544"
OUT = BACKEND / "data/dda_seeds/spec_v2_3x4_20261022"
N_CAND, N_PICK = 5, 3
SEED_RNG_KEY = "dda_seed_spec_v2_pm2_20261022/v1"
SEED_LO, SEED_HI = 1_300_000_000, 1_399_999_999   # 11억대(±1)·12억대(hold126 예약)·기존 대역과 비중첩
RESERVED = [(1_100_000_000, 1_199_999_999), (1_200_000_000, 1_299_999_999)]
FIELDS = {"easy": ("ddaEasySeeds", -1), "hard": ("ddaHardSeeds", +1),
          "easy2": ("ddaEasy2Seeds", -2), "hard2": ("ddaHard2Seeds", +2)}
COND_EXCL = ("map", "ddaEasySeeds", "ddaHardSeeds")   # catalog v1 / 게임 v1 sourceConditionHash 계약 그대로
LOG = OUT / "logs/run.log"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


ac.LOGF[0] = LOG
sha, dump = ac.sha, ac.dump


def check_variant(b, t0obj, v, group):
    """dda_t0_assign_check_20261020.main 루프 본문과 같은 판정 (한 설정)."""
    m = t0obj["map"]
    reasons = []
    input_ok = sha(b) == v["t0baseFileSha256"] and sha(dump(m)) == v["t0baseMapSha256"] \
        and t0obj["origMapSha256"] == v["requiredOrigMapSha256"]
    row = dict(t0obj["row"])
    row["useTileCount"] = str(v["useTileCount"])
    row["randSeed"] = str(v["randSeed"])
    cond_ok = sha(dump({"sourceCommit": v["sourceCommit"], "t0baseMapSha256": v["t0baseMapSha256"],
                        "row": row})) == v["condSha256"]
    row["map"] = m
    rec = {"level": v["level"], "dir": v["dir"], "cand": v["cand"], "group": group,
           "useTileCount": v["useTileCount"], "randSeed": v["randSeed"], "condSha256": v["condSha256"],
           "requestedTypes": int(v["useTileCount"]), "inputHashOK": input_ok, "condOK": cond_ok}
    if not input_ok:
        reasons.append("input_hash_mismatch")
    if not cond_ok:
        reasons.append("cond_hash_mismatch")
    lok, lmsg = ac.layer_check(m)
    rec["layersOK"] = lok
    if not lok:
        reasons.append("layers_not_consecutive:" + lmsg)
    c0, k0, t00, tot0, oth0 = ac.census(m)
    rec["keyOrig"], rec["totalOrig"] = k0, tot0
    try:
        res, resolved = ac.run_once(row)
        res2, resolved2 = ac.run_once(row)
    except ac.cs.PvError as e:
        rec.update(status="FAIL" if isinstance(e, ac.cs.CsClientCrash) else "HOLD",
                   reason=f"port_{type(e).__name__}:{e}")
        return rec
    rhash, rhash2 = sha(dump(resolved)), sha(dump(resolved2))
    c1, k1, t01, tot1, oth1 = ac.census(resolved)
    rec.update(actualTypes=len(c1), idCounts="|".join(f"{t}:{c1[t]}" for t in sorted(c1, key=lambda s: int(s[1:]))),
               keyAfter=k1, totalAfter=tot1, emptySlots=len(res.slots), toAddLen=len(res.to_add),
               t0Left=t01, otherIds="|".join(f"{k}:{n}" for k, n in sorted(oth1.items())),
               resolvedMapSha256=rhash, repro2OK=rhash == rhash2 and res.assigned == res2.assigned,
               rngCalls=res.rng_calls)
    rec["typesOK"] = rec["actualTypes"] == rec["requestedTypes"]
    rec["mod3OK"] = all(n % 3 == 0 for n in c1.values()) and k1 % 3 == 0
    rec["keyOK"] = k1 == k0 + 3 * ac.cs.as_int(row.get("unlockTile"))
    rec["totalOK"] = tot1 == tot0
    rec["structOK"] = ac.struct_sig(resolved) == ac.struct_sig(m)
    lay = lambda mm: [(lk, list(lv["tiles"]) if isinstance(lv.get("tiles"), dict) else lv.get("tiles"))  # noqa: E731
                      for lk, lv in mm.items() if lk.startswith("layer_")]
    rec["orderOK"] = lay(resolved) == lay(m)
    vr = ac.cs.apply_visual_tile_remap(res.assigned, 0)
    vc = Counter(ac.cs.CTile("", "", x, "").tile_id_num for x in vr)
    lc = Counter(ac.cs.CTile("", "", x, "").tile_id_num for x in res.assigned)
    rec["visualRemapInvariant"] = sorted(vc.values()) == sorted(lc.values()) and len(vc) == len(lc)
    if len(res.slots) == 0:
        reasons.append("no_empty_slots(port early return)")
    for f, why in (("typesOK", "types_mismatch"), ("mod3OK", "id_count_not_mult3"), ("keyOK", "key_count_changed"),
                   ("totalOK", "total_changed"), ("structOK", "struct_changed"), ("orderOK", "order_changed"),
                   ("repro2OK", "not_reproducible"), ("visualRemapInvariant", "visual_remap_not_invariant")):
        if not rec[f]:
            reasons.append(why)
    if t01:
        reasons.append(f"t0_left:{t01}")
    if oth1 != oth0 or oth1:
        reasons.append("other_ids:" + rec["otherIds"])
    if res.to_add:
        reasons.append(f"padding_used:{len(res.to_add)}")
    rec["status"] = "PASS" if not reasons else "FAIL"
    rec["reason"] = ";".join(reasons)
    return rec


def pick(cands):
    """선정 규칙: PASS AND resolvedMapSha256 레벨 내 고유(seen 공유) → cand 순서 앞 N_PICK. 반환 (선정, 사유별 탈락)."""
    chosen, dropped = [], []
    for c in sorted(cands, key=lambda r: int(r["cand"])):
        if c["status"] != "PASS":
            dropped.append((c, "assign_" + c["status"]))
        elif c["resolvedMapSha256"] in pick.seen:
            dropped.append((c, "resolved_map_duplicate"))
        elif len(chosen) < N_PICK:
            chosen.append(c)
            pick.seen.add(c["resolvedMapSha256"])
        else:
            dropped.append((c, "not_needed(rank>3)"))
    return chosen, dropped


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if ac.resource_check("start"):
        log("start blocked by resource")
        return 2
    cat_b = CATALOG.read_bytes()
    assert sha(cat_b) == CATALOG_SHA, "catalog sha mismatch"
    catalog = {e["level"]: e for e in json.loads(cat_b)["levels"]}
    levels = {int(r["level"]): r for r in csv.DictReader((RUN / "config/levels.csv").open())}
    v1 = {}
    for v in csv.DictReader((RUN / "config/variants.csv").open()):
        v1.setdefault(int(v["level"]), []).append(v)
    a1 = {}
    for r in csv.DictReader(ASSIGN1.open()):
        a1[(int(r["level"]), r["dir"], int(r["cand"]))] = r

    # 기존 시드 전부 금지 (출시 randSeed·±1 variants·패키지 sets·seed_bands·예약 대역)
    used = set()
    for L, vs in v1.items():
        used.update(int(v["randSeed"]) for v in vs)
    rows_tbl = json.loads((RUN.parents[1] / "live_copy/b741f6a3/levels.json").read_text())
    ks = rows_tbl["__keys"]
    for r in rows_tbl["__vals"]:
        for t in str(r[ks.index("randSeed")]).split("|"):
            if t.strip().lstrip("-").isdigit():
                used.add(int(t))
    with (PKG / "sets.csv").open() as f:
        for r in csv.DictReader(f):
            used.update(int(t) for t in r["randSeed"].split("|") if t.isdigit())
    bands = json.loads((PKG / "seed_bands.json").read_text())
    band_ranges = [(v, v + 1_000_000) for g in bands.values() if isinstance(g, dict) for v in g.values()]
    assert all(hi < SEED_LO or lo > SEED_HI for lo, hi in band_ranges + RESERVED)
    in_band = sorted(s for s in used if SEED_LO <= s <= SEED_HI)   # 패키지 sets.csv 개별 시드 5개 등 → draw 에서 제외됨
    log(f"existing seeds inside new band (excluded from draw): {in_band}")
    rng = random.Random(SEED_RNG_KEY)

    def draw():
        while True:
            s = rng.randint(SEED_LO, SEED_HI)
            if s not in used:
                used.add(s)
                return s

    pm1_rows, pm2_rows, out_levels, holds = [], [], [], []
    t_start = time.time()
    for L in sorted(catalog):
        if time.time() - ac._last[0] > 50 and ac.resource_check(f"L{L}"):
            log("STOP: resource")
            return 3
        ce = catalog[L]
        rec = {"level": L, "id": f"level_{L}", "catalogStatus": ce["status"], "N": ce.get("N"),
               "sourceMapSha256": ce.get("sourceMapSha256"), "sourceConditionHash": ce.get("sourceConditionHash"),
               "fields": {f: "" for f, _ in FIELDS.values()}, "useTileCount": {}, "condSha256": {},
               "holds": {}, "status": None}
        if ce["status"] != "candidate":
            rec["status"] = "not_candidate"
            rec["holds"] = {f: "catalog_" + ce["status"] for f, _ in FIELDS.values()}
            out_levels.append(rec)
            continue
        lr = levels[L]
        b = (RUN / f"out/t0base/level_{L}.json").read_bytes()
        t0obj = json.loads(b)
        row0 = t0obj["row"]
        N = int(lr["distinctNormal"])
        group = "excluded" if lr["autoApplyExclude"] else "nonexcluded"
        # 결속 검사: catalog ↔ run (map sha·조건 해시·N·행 useTileCount)
        bind = []
        if t0obj["origMapSha256"] != ce["sourceMapSha256"] or lr["origMapSha256"] != ce["sourceMapSha256"]:
            bind.append("source_map_sha_mismatch")
        if sha(dump({k: v for k, v in row0.items() if k not in COND_EXCL})) != ce["sourceConditionHash"]:
            bind.append("source_condition_hash_mismatch")
        if N != ce["N"] or ac.cs.as_int(row0.get("useTileCount")) != N:
            bind.append("N_mismatch")
        if sha(b) != lr["t0baseFileSha256"]:
            bind.append("t0base_file_sha_mismatch")
        if bind:
            rec["status"] = "hold_binding"
            rec["holds"] = {f: ";".join(bind) for f, _ in FIELDS.values()}
            out_levels.append(rec)
            continue
        pick.seen = set()
        sets_t0 = int(lr["t0Sets"])
        orig_seed = ac.cs.as_int(row0.get("randSeed"))
        # ±1: 기존 5 후보 (catalog 문자열과 순서까지 같은지 확인)
        for d in ("easy", "hard"):
            field = FIELDS[d][0]
            vs = sorted((v for v in v1[L] if v["dir"] == d), key=lambda v: int(v["cand"]))
            cat_seeds = ce[field].split(",")
            if [v["randSeed"] for v in vs] != cat_seeds or len(vs) != N_CAND:
                rec["holds"][field] = "catalog_seed_order_mismatch"
                continue
            cands = []
            for v in vs:
                r = dict(a1[(L, d, int(v["cand"]))])
                assert r["dir"] == d
                r.update(randSeed=v["randSeed"], useTileCount=v["useTileCount"], condSha256=v["condSha256"])
                cands.append(r)
            chosen, dropped = pick(cands)
            for c in cands:
                why = next((w for x, w in dropped if x is c), "")
                pm1_rows.append({"level": L, "field": field, "cand": c["cand"], "randSeed": c["randSeed"],
                                 "useTileCount": c["useTileCount"], "assignStatus": c["status"],
                                 "resolvedMapSha256": c["resolvedMapSha256"], "selected": c in chosen,
                                 "dropReason": why})
            if len(chosen) < N_PICK:
                rec["holds"][field] = f"insufficient_candidates({len(chosen)}<{N_PICK})"
                continue
            rec["fields"][field] = ",".join(c["randSeed"] for c in chosen)
            rec["useTileCount"][field] = int(vs[0]["useTileCount"])
            rec["condSha256"][field] = [c["condSha256"] for c in chosen]
        # ±2: 신규 후보 5개, 배정 검사
        for d, delta in (("easy2", -2), ("hard2", +2)):
            field = FIELDS[d][0]
            utc = N + delta
            r = []
            if not 1 <= utc <= 15:
                r.append(f"useTileCount_out_of_range({utc})")
            if utc > sets_t0:
                r.append(f"useTileCount>{sets_t0}sets")
            if d == "easy2" and utc < 2:
                r.append("easy_types<2")
            if r:
                rec["holds"][field] = ";".join(r)
                continue
            cands = []
            for j in range(N_CAND):
                seed = draw()
                eff = dict(row0)
                eff["useTileCount"] = str(utc)
                eff["randSeed"] = str(seed)
                v = {"level": L, "dir": d, "cand": j + 1, "useTileCount": utc, "randSeed": seed,
                     "sourceCommit": lr["sourceCommit"], "t0baseFileSha256": lr["t0baseFileSha256"],
                     "t0baseMapSha256": lr["t0baseMapSha256"], "requiredOrigMapSha256": lr["origMapSha256"],
                     "condSha256": sha(dump({"sourceCommit": lr["sourceCommit"],
                                             "t0baseMapSha256": lr["t0baseMapSha256"], "row": eff}))}
                cands.append(check_variant(b, t0obj, v, group))
            chosen, dropped = pick(cands)
            for c in cands:
                c["selected"] = c in chosen
                c["dropReason"] = next((w for x, w in dropped if x is c), "")
                pm2_rows.append(c)
            if len(chosen) < N_PICK:
                rec["holds"][field] = f"insufficient_candidates({len(chosen)}<{N_PICK})"
                continue
            rec["fields"][field] = ",".join(str(c["randSeed"]) for c in chosen)
            rec["useTileCount"][field] = utc
            rec["condSha256"][field] = [c["condSha256"] for c in chosen]
        allseeds = [orig_seed] + [int(s) for f in rec["fields"].values() if f for s in f.split(",")]
        assert len(allseeds) == len(set(allseeds)), f"L{L} seed dup"
        rec["autoApplyExclude"] = lr["autoApplyExclude"]
        rec["originalRandSeed"] = orig_seed
        nf = sum(1 for f in rec["fields"].values() if f)
        rec["status"] = "ready4" if nf == 4 else ("partial" if nf else "hold_all")
        out_levels.append(rec)
        if L % 100 == 0:
            log(f"progress L{L} pm2_variants={len(pm2_rows)} {time.time() - t_start:.0f}s")

    for rec in out_levels:
        for f, why in rec["holds"].items():
            holds.append({"level": rec["level"], "field": f, "reason": why})
    with (OUT / "pm1_selection.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pm1_rows[0]))
        w.writeheader()
        w.writerows(pm1_rows)
    pm2_fields = ["level", "dir", "cand", "group", "useTileCount", "randSeed", "condSha256", "requestedTypes",
                  "actualTypes", "typesOK", "idCounts", "mod3OK", "keyOrig", "keyAfter", "keyOK", "totalOrig",
                  "totalAfter", "totalOK", "emptySlots", "toAddLen", "t0Left", "otherIds", "structOK", "orderOK",
                  "layersOK", "inputHashOK", "condOK", "visualRemapInvariant", "resolvedMapSha256", "repro2OK",
                  "rngCalls", "status", "reason", "selected", "dropReason"]
    with (OUT / "pm2_candidates.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pm2_fields)
        w.writeheader()
        w.writerows(pm2_rows)
    with (OUT / "holds.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "field", "reason"])
        w.writeheader()
        w.writerows(holds)
    (OUT / "levels_spec_v2.json").write_bytes(json.dumps(out_levels, ensure_ascii=False, indent=0).encode())
    with (OUT / "server_columns_spec_v2.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id"] + [fn for fn, _ in FIELDS.values()])
        for rec in out_levels:
            w.writerow([rec["id"]] + [rec["fields"][fn] for fn, _ in FIELDS.values()])

    cand = [r for r in out_levels if r["catalogStatus"] == "candidate"]
    counts = {
        "catalogLevels": len(out_levels), "candidateLevels": len(cand),
        "byStatus": dict(Counter(r["status"] for r in out_levels)),
        "fieldReady": {fn: sum(1 for r in out_levels if r["fields"][fn]) for fn, _ in FIELDS.values()},
        "fieldReadyNonExcluded": {fn: sum(1 for r in cand if r["fields"][fn] and not r.get("autoApplyExclude"))
                                  for fn, _ in FIELDS.values()},
        "ready4NonExcluded": sum(1 for r in cand if r["status"] == "ready4" and not r.get("autoApplyExclude")),
        "holdReasons": dict(Counter(f"{h['field']}:{h['reason'].split('(')[0]}" for h in holds
                                    if not h["reason"].startswith("catalog_"))),
        "pm1": {"candidates": len(pm1_rows), "assignStatus": dict(Counter(r["assignStatus"] for r in pm1_rows)),
                "dropReasons": dict(Counter(r["dropReason"] for r in pm1_rows if r["dropReason"]))},
        "pm2": {"candidates": len(pm2_rows), "status": dict(Counter(r["status"] for r in pm2_rows)),
                "dropReasons": dict(Counter(r["dropReason"] for r in pm2_rows if r["dropReason"])),
                "failReasons": dict(Counter(x for r in pm2_rows if r.get("reason")
                                            for x in r["reason"].split(";")))},
    }
    bad = sorted(n for n in sys.modules if ac.FORBIDDEN_MOD.search(n))
    manifest = {
        "id": "dda_seed_spec_v2_3x4_20261022", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "OFFLINE PREPARATION ONLY — no server read/write, no bot/solver/difficulty measurement",
        "fieldContract": {fn: {"delta": dl, "useTileCount": f"N{dl:+d}", "count": N_PICK,
                               "format": "positive Int32 x3, comma separated, no spaces"}
                          for fn, dl in FIELDS.values()},
        "uniqueness": "per level: original randSeed + 12 seeds all distinct; resolved maps distinct within level",
        "selectionRule": "both ±1 and ±2: assign-check PASS AND resolvedMapSha256 unique within level -> first 3 by "
                         "cand order (= draw order, unrelated to difficulty). NOT difficulty-verified.",
        "pm1Source": "existing 5 candidates (run_20261020_130623 variants = catalog v1 = old-spec server values), "
                     "assign check assign_check_20261020_135511; no new seeds",
        "pm2Generation": {"rng": f"random.Random({SEED_RNG_KEY!r}) sequential, level order, easy2 then hard2, "
                                 f"{N_CAND} per field", "range": [SEED_LO, SEED_HI],
                          "excluded": "release randSeeds, all ±1 variant seeds, package sets.csv, seed_bands, "
                                      "reserved 1.1B/1.2B bands",
                          "holdRules": ["useTileCount outside 1..15", "useTileCount > t0 sets", "easy types < 2",
                                        "< 3 PASS unique candidates"], "noClamp": True},
        "conditionHashContract": "sourceConditionHash = sha256(dump(row - {map, ddaEasySeeds, ddaHardSeeds})) "
                                 "(catalog v1/game v1). condSha256 = sha256(dump({sourceCommit, t0baseMapSha256, "
                                 "row with useTileCount/randSeed strings}))",
        "warnings": ["game code / verifier / console accept exactly 5 seeds and ±1 only — not compatible with this spec",
                     "game sourceConditionHash excludes only map+ddaEasySeeds+ddaHardSeeds; adding server columns "
                     "ddaEasy2Seeds/ddaHard2Seeds changes the baked row -> all levels fall back unless the game "
                     "exclusion list is extended",
                     "difficulty of ±1/±2 variants UNMEASURED (no Δ/CI); order easy2<easy<orig<hard<hard2 is intent only"],
        "inputs": {"catalog": {"path": str(CATALOG.relative_to(BACKEND)), "sha256": CATALOG_SHA},
                   "levelsCsv": sha((RUN / "config/levels.csv").read_bytes()),
                   "variantsCsv": sha((RUN / "config/variants.csv").read_bytes()),
                   "assignCheck1PerVariant": sha(ASSIGN1.read_bytes()),
                   "portSha256": sha(ac.PORT.read_bytes()),
                   "assignCheckScriptSha256": sha(Path(ac.__file__).read_bytes()),
                   "scriptSha256": sha(Path(__file__).read_bytes())},
        "counts": counts, "forbiddenModulesLoaded": bad, "elapsedSec": round(time.time() - t_start, 1),
        "generatedBy": "backend/scripts/dda_seed_spec_v2_prepare_20261022.py",
    }
    (OUT / "manifest.json").write_bytes(json.dumps(manifest, ensure_ascii=False, indent=1).encode())
    ac.resource_check("end")
    log("counts " + json.dumps(counts, ensure_ascii=False))
    log(f"forbiddenModulesLoaded={bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
