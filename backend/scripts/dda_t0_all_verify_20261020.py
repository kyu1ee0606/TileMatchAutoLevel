#!/usr/bin/env python3
"""dda_t0_all_20261020 run 산출물 독립 정적 검증 (저장 정합만; 배정 후 정합/솔버블/난이도는 검증 안 함).

사용: cd backend && .venv/bin/python scripts/dda_t0_all_verify_20261020.py data/pv_sandbox/dda_t0_all_20261020/runs/<run_id>
생성기 코드를 import 하지 않고 규칙을 다시 구현해 원본↔t0base 를 셀 단위로 대조한다.
"""
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

NORMAL = re.compile(r"^t([1-9]|1[0-5])$")


def key(tid, eff):  # DB_Level.cs:238
    return tid == "t16" or str(tid).lower() == "key" or str(eff).lower() == "key"


def h(b):
    return hashlib.sha256(b).hexdigest()


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def cmp_level(o, t):
    """원본 map o 와 t0base map t 대조. 반환: (오류목록, 원본 일반 타입 Counter, 유효 총수)."""
    err, cnt, total = [], Counter(), 0
    if list(o) != list(t):
        err.append("top_keys_order")
    for k in o:
        if not k.startswith("layer_"):
            if o[k] != t.get(k):
                err.append(f"meta:{k}")
            continue
        lo, lt = o[k], t.get(k, {})
        if list(lo) != list(lt) or any(lo[x] != lt[x] for x in lo if x != "tiles"):
            err.append(f"layer_meta:{k}")
        to, tt = lo.get("tiles"), lt.get("tiles")
        if not isinstance(to, dict):
            if to != tt:
                err.append(f"nondict_tiles:{k}")
            continue
        if list(to) != list(tt):
            err.append(f"cell_order:{k}")
            continue
        for ck, co in to.items():
            ct = tt[ck]
            eff = co[1] if len(co) > 1 else ""
            if len(co) != len(ct) or co[1:2] != ct[1:2]:
                err.append(f"cell_shape_or_effect:{k}/{ck}")
                continue
            tid = co[0]
            if tid.startswith(("stack_", "craft_")):
                if ct[0] != tid or co[2][0] != ct[2][0]:
                    err.append(f"container_root_or_N:{k}/{ck}")
                n = int(co[2][0])
                total += n
                io = co[2][1].split("_") if len(co[2]) > 1 and co[2][1] else None
                it = ct[2][1].split("_") if len(ct[2]) > 1 and ct[2][1] else None
                if io is None:
                    if it is not None:
                        err.append(f"inner_added:{k}/{ck}")
                    continue
                if it is None or len(io) != n or len(it) != n:
                    err.append(f"inner_len:{k}/{ck}")
                    continue
                for a, b in zip(io, it):
                    if NORMAL.match(a) and not key(a, ""):
                        cnt[a] += 1
                        if b != "t0":
                            err.append(f"inner_not_t0:{k}/{ck}")
                    elif a != b:
                        err.append(f"inner_changed:{k}/{ck}")
                continue
            total += 1
            if NORMAL.match(tid) and not key(tid, eff):
                cnt[tid] += 1
                if ct[0] != "t0":
                    err.append(f"normal_not_t0:{k}/{ck}")
            elif ct[0] != tid:
                err.append(f"nonnormal_changed:{k}/{ck}")
    for k in t:
        if k not in o:
            err.append(f"extra_key:{k}")
    return err, cnt, total


def main(run):
    run = Path(run)
    root = run.parents[1]
    res = Counter()
    # 1) SHA256SUMS
    for line in (run / "SHA256SUMS").read_text().splitlines():
        s, p = line.split("  ", 1)
        res["sha_ok" if h((root / p).read_bytes()) == s else "sha_BAD"] += 1
    man = json.loads((run / "manifest.json").read_text())
    base = man["source"]["baseCommit"]
    rows = {int(r["level"]): r for r in csv.DictReader((run / "config/levels.csv").open())}
    var = list(csv.DictReader((run / "config/variants.csv").open()))
    # 2) 원본↔t0base 셀 대조
    for L, r in rows.items():
        of = run / f"out/orig/{base}/level_{L}.json"
        ob = of.read_bytes()
        oj = json.loads(ob)
        if h(ob) != r["origFileSha256"] or h(dump(oj["map"])) != r["origMapSha256"]:
            res["orig_hash_BAD"] += 1
        tf = run / f"out/t0base/level_{L}.json"
        if r["t0base"] != "OK":
            res["t0_hold"] += 1
            if tf.exists():
                res["t0_file_for_hold_BAD"] += 1
            continue
        tb = tf.read_bytes()
        tj = json.loads(tb)
        if h(tb) != r["t0baseFileSha256"] or h(dump(tj["map"])) != r["t0baseMapSha256"] or tj["row"] != oj["row"]:
            res["t0_hash_or_row_BAD"] += 1
        err, cnt, total = cmp_level(oj["map"], tj["map"])
        if err:
            res["cmp_BAD"] += 1
            print(L, err[:5])
        if len(cnt) != int(r["distinctNormal"]) or total != int(r["effTotal"]) or any(c % 3 for c in cnt.values()):
            res["count_BAD"] += 1
        res["t0_ok"] += 1
    # 3) 설정
    seeds = [int(v["randSeed"]) for v in var]
    res["seed_dup"] = len(seeds) - len(set(seeds))
    res["seed_range_BAD"] = sum(1 for s in seeds if not 0 < s < 2**31)
    per = Counter((v["level"], v["dir"]) for v in var)
    res["cand_not5"] = sum(1 for c in per.values() if c != 5)
    for v in var:
        r = rows[int(v["level"])]
        n = int(r["distinctNormal"])
        utc = int(v["useTileCount"])
        if utc != (n - 1 if v["dir"] == "easy" else n + 1) or not 1 <= utc <= 15 or utc > int(r["t0Sets"]):
            res["utc_BAD"] += 1
        if v["t0baseFileSha256"] != r["t0baseFileSha256"] or v["requiredOrigMapSha256"] != r["origMapSha256"]:
            res["link_BAD"] += 1
        t = json.loads((run / f"out/t0base/level_{v['level']}.json").read_text())
        er = dict(t["row"])
        er["useTileCount"], er["randSeed"] = str(utc), v["randSeed"]
        if h(dump({"sourceCommit": base, "t0baseMapSha256": v["t0baseMapSha256"], "row": er})) != v["condSha256"]:
            res["cond_BAD"] += 1
        if v["difficultyRank"] not in ("", "None"):
            res["rank_not_null_BAD"] += 1
    res["variants"] = len(var)
    print(json.dumps(dict(res), ensure_ascii=False))
    bad = {k: v for k, v in res.items() if "BAD" in k and v} or (res["seed_dup"] or res["cand_not5"])
    print("RESULT", "FAIL" if bad else "PASS(storage-structure only)")


if __name__ == "__main__":
    main(sys.argv[1])
