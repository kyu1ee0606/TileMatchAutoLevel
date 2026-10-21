#!/usr/bin/env python3
"""DDA t0 오프라인 배정 정합 검증 (2026-10-20) — run_20261020_130623 의 13725 설정 대상.

경로: 기존 순수 포트 backend/app/core/pv/cs_shuffle.py 의 shuffle_level_row + resolve_map 만 사용.
  - cs_shuffle.py 는 파일 경로로 단독 로드한다 (app/core/__init__.py 가 bot_simulator 등을 import 하므로
    패키지 import 를 피함). 실행 후 sys.modules 에 봇/솔버/승률 모듈이 없음을 검사·기록한다.
  - bot_simulator.TileDistributor(구형) 사용 안 함. canonical_map / t0ize 재적용 안 함(t0base 삽입 순서 그대로).
입력(읽기 전용): runs/run_20261020_130623/{config/variants.csv, config/levels.csv, out/t0base/*.json}
출력: runs/run_20261020_130623/assign_check_<id>/ (또는 --out) 아래만.
검증 범위: 오프라인 포트 논리 배정 정합. Unity 실행 동일성·비주얼·솔버블·난이도 = 미검증.
사용: .venv/bin/python scripts/dda_t0_assign_check_20261020.py --out <dir> [--limit N]
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import re
import resource
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
RUN = BACKEND / "data/pv_sandbox/dda_t0_all_20261020/runs/run_20261020_130623"
PORT = BACKEND / "app/core/pv/cs_shuffle.py"
NORMAL_RE = re.compile(r"^t([1-9]|1[0-5])$")
LAYER_RE = re.compile(r"^layer_(\d+)$")
FORBIDDEN_MOD = re.compile(r"bot_simulator|solver|simulator|difficulty|win_rate|winrate|autoplay|analyzer|generator")

_spec = importlib.util.spec_from_file_location("cs_shuffle_standalone", PORT)
cs = importlib.util.module_from_spec(_spec)
sys.modules["cs_shuffle_standalone"] = cs   # dataclass 해석용
_spec.loader.exec_module(cs)

_last = [0.0]
LOGF = [None]


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with LOGF[0].open("a") as f:
        f.write(line + "\n")


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024  # macOS: bytes


def resource_check(tag):
    """critical(4) 또는 swap free<500MB → True(중단)."""
    _last[0] = time.time()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                         capture_output=True, text=True).stdout.strip()
    sw = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    log(f"[resource:{tag}] pressure_level={lvl} | {sw} | maxRSS={rss_mb():.1f}MB")
    m = re.search(r"free = ([\d.]+)M", sw)
    return lvl == "4" or bool(m and float(m.group(1)) < 500)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def is_key(tid, eff):  # DB_Level.cs:238
    return tid == "t16" or str(tid).lower() == "key" or str(eff).lower() == "key"


def cells(m):
    for lk, lv in m.items():
        if lk.startswith("layer_") and isinstance(lv, dict) and isinstance(lv.get("tiles"), dict):
            for ck, cell in lv["tiles"].items():
                yield lk, ck, cell


def census(m):
    """map 의 논리 타일 집계: 일반 ID별, key, t0 잔여, 유효 총수 (컨테이너 내부 명시 id 포함)."""
    cnt, key, t0, total, other = Counter(), 0, 0, 0, Counter()
    for lk, ck, cell in cells(m):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        if tid.startswith("stack_") or tid.startswith("craft_"):
            info = cell[2] if len(cell) > 2 else [0]
            n = int(info[0])
            total += n
            ids = info[1].split("_") if len(info) > 1 and info[1] else ["t0"] * n
            if len(ids) != n:
                other["inner_len_mismatch"] += 1
                continue
            for x in ids:
                if is_key(x, ""):
                    key += 1
                elif NORMAL_RE.match(x):
                    cnt[x] += 1
                elif x == "t0":
                    t0 += 1
                else:
                    other[x] += 1
            continue
        total += 1
        if is_key(tid, eff):
            key += 1
        elif NORMAL_RE.match(tid):
            cnt[tid] += 1
        elif tid == "t0":
            t0 += 1
        else:
            other[tid] += 1
    return cnt, key, t0, total, other


def struct_sig(m):
    """ID 값 무관 구조 서명: 레이어/셀 순서·위치·effect·컨테이너 루트/N·key 위치·메타."""
    sig = []
    for lk, ck, cell in cells(m):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        norm = "N" if (tid == "t0" or NORMAL_RE.match(tid)) and not is_key(tid, eff) else tid
        extra = None
        if len(cell) > 2:
            info = cell[2]
            n = info[0]
            ids = info[1].split("_") if len(info) > 1 and info[1] else []
            extra = (n, ["N" if (x == "t0" or NORMAL_RE.match(x)) and not is_key(x, "") else x for x in ids],
                     len(info))
        sig.append((lk, ck, norm, eff, len(cell), json.dumps(extra)))
    meta = {k: v for k, v in m.items() if not k.startswith("layer_")}
    lmeta = [(lk, {k: v for k, v in lv.items() if k != "tiles"}, type(lv.get("tiles")).__name__)
             for lk, lv in m.items() if lk.startswith("layer_") and isinstance(lv, dict)]
    return sha(dump([sig, meta, lmeta]))


def layer_check(m):
    nums = [int(LAYER_RE.match(k).group(1)) for k in m if LAYER_RE.match(k)]
    bad_names = [k for k in m if k.startswith("layer_") and not LAYER_RE.match(k)]
    ok = not bad_names and sorted(nums) == list(range(len(nums)))
    return ok, ("" if ok else f"layers={sorted(nums)} bad={bad_names}")


def run_once(row):
    res = cs.shuffle_level_row(row, strict=False)   # %3 은 아래에서 별도 판정 (n=0 조기 return 포함)
    resolved = cs.resolve_map(row["map"], res)
    return res, resolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    assert str(out).startswith(str(RUN) + "/assign_check_"), "output must be under RUN/assign_check_*"
    out.mkdir(parents=True, exist_ok=True)
    LOGF[0] = out / "resource.log"
    ck_path = out / "checkpoint.json"
    ck = json.loads(ck_path.read_text()) if ck_path.exists() else {"done": 0}

    if resource_check("start"):
        log("start blocked by resource")
        return 2

    levels = {int(r["level"]): r for r in csv.DictReader((RUN / "config/levels.csv").open())}
    variants = list(csv.DictReader((RUN / "config/variants.csv").open()))
    if a.limit:
        variants = variants[:a.limit]
    fields = ["level", "dir", "cand", "group", "requestedTypes", "actualTypes", "typesOK", "idCounts", "mod3OK",
              "keyOrig", "keyAfter", "keyOK", "totalOrig", "totalAfter", "totalOK", "emptySlots", "toAddLen",
              "t0Left", "otherIds", "structOK", "orderOK", "layersOK", "inputHashOK", "condOK",
              "visualRemapInvariant", "resolvedMapSha256", "repro2OK", "rngCalls", "status", "reason"]
    csv_path = out / "per_variant.csv"
    new = not csv_path.exists() or ck["done"] == 0
    fcsv = csv_path.open("w" if new else "a", newline="")
    w = csv.DictWriter(fcsv, fieldnames=fields)
    if new:
        w.writeheader()
    cache = {}
    t0 = time.time()
    stop = None
    for i, v in enumerate(variants):
        if i < ck["done"]:
            continue
        if time.time() - _last[0] > 50 and resource_check(f"i{i}"):
            stop = "resource(critical or swap free<500MB)"
            break
        L = int(v["level"])
        lr = levels[L]
        if L not in cache:
            b = (RUN / f"out/t0base/level_{L}.json").read_bytes()
            cache.clear()
            cache[L] = (b, json.loads(b))
        b, t0obj = cache[L]
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
        rec = {"level": L, "dir": v["dir"], "cand": v["cand"],
               "group": "excluded" if lr["autoApplyExclude"] else "nonexcluded",
               "requestedTypes": int(v["useTileCount"]), "inputHashOK": input_ok, "condOK": cond_ok}
        if not input_ok:
            reasons.append("input_hash_mismatch")
        if not cond_ok:
            reasons.append("cond_hash_mismatch")
        lok, lmsg = layer_check(m)
        rec["layersOK"] = lok
        if not lok:
            reasons.append("layers_not_consecutive:" + lmsg)
        c0, k0, t00, tot0, oth0 = census(m)
        rec["keyOrig"], rec["totalOrig"] = k0, tot0
        try:
            res, resolved = run_once(row)
            res2, resolved2 = run_once(row)
        except cs.PvError as e:
            rec.update(status="FAIL" if isinstance(e, cs.CsClientCrash) else "HOLD",
                       reason=f"port_{type(e).__name__}:{e}")
            w.writerow(rec)
            continue
        rhash, rhash2 = sha(dump(resolved)), sha(dump(resolved2))
        c1, k1, t01, tot1, oth1 = census(resolved)
        rec.update(actualTypes=len(c1), idCounts="|".join(f"{t}:{c1[t]}" for t in sorted(c1, key=lambda s: int(s[1:]))),
                   keyAfter=k1, totalAfter=tot1, emptySlots=len(res.slots), toAddLen=len(res.to_add),
                   t0Left=t01, otherIds="|".join(f"{k}:{n}" for k, n in sorted(oth1.items())),
                   resolvedMapSha256=rhash, repro2OK=rhash == rhash2 and res.assigned == res2.assigned,
                   rngCalls=res.rng_calls)
        rec["typesOK"] = rec["actualTypes"] == rec["requestedTypes"]
        rec["mod3OK"] = all(n % 3 == 0 for n in c1.values()) and k1 % 3 == 0
        exp_key = k0 + 3 * cs.as_int(row.get("unlockTile"))
        rec["keyOK"] = k1 == exp_key
        rec["totalOK"] = tot1 == tot0
        rec["structOK"] = struct_sig(resolved) == struct_sig(m)
        rec["orderOK"] = [(lk, list(lv["tiles"]) if isinstance(lv.get("tiles"), dict) else lv.get("tiles"))
                          for lk, lv in resolved.items() if lk.startswith("layer_")] == \
                         [(lk, list(lv["tiles"]) if isinstance(lv.get("tiles"), dict) else lv.get("tiles"))
                          for lk, lv in m.items() if lk.startswith("layer_")]
        # 비주얼 재매핑(DB_Level.cs:1307-1354)은 종류 간 1:1 → 종류수·%3 불변인지 참고 확인 (seed 0 → vSeed 1)
        vr = cs.apply_visual_tile_remap(res.assigned, 0)
        vc = Counter(cs.CTile("", "", x, "").tile_id_num for x in vr)
        lc = Counter(cs.CTile("", "", x, "").tile_id_num for x in res.assigned)
        rec["visualRemapInvariant"] = sorted(vc.values()) == sorted(lc.values()) and len(vc) == len(lc)
        if len(res.slots) == 0:
            reasons.append("no_empty_slots(port early return)")
        for f, why in (("typesOK", "types_mismatch(actual<requested)" if rec["actualTypes"] < rec["requestedTypes"]
                        else "types_mismatch"), ("mod3OK", "id_count_not_mult3"), ("keyOK", "key_count_changed"),
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
        w.writerow(rec)
        if (i + 1) % 500 == 0:
            fcsv.flush()
            ck_path.write_text(json.dumps({"done": i + 1}))
            log(f"progress {i + 1}/{len(variants)} {(i + 1 - ck['done']) / (time.time() - t0):.1f}/s")
    fcsv.close()
    done = i + 1 if stop is None else i
    ck_path.write_text(json.dumps({"done": done, "total": len(variants), "stopReason": stop}))
    el = time.time() - t0
    bad = sorted(n for n in sys.modules if FORBIDDEN_MOD.search(n))
    log(f"finished done={done}/{len(variants)} stop={stop} elapsed={el:.1f}s "
        f"rate={(done - ck['done']) / max(el, 1e-9):.1f}/s maxRSS={rss_mb():.1f}MB forbiddenModulesLoaded={bad}")
    (out / "run_meta.json").write_text(json.dumps({
        "done": done, "total": len(variants), "stopReason": stop, "elapsedSec": round(el, 1),
        "maxRssMB": round(rss_mb(), 1), "forbiddenModulesLoaded": bad,
        "port": str(PORT.relative_to(BACKEND)), "portSha256": sha(PORT.read_bytes()),
        "scriptSha256": sha(Path(__file__).read_bytes()), "python": sys.version.split()[0]}, indent=1))
    resource_check("end")
    return 0 if stop is None else 3


def summarize(out):
    """per_variant.csv → summary.json (비제외/제외 분리, 사유별, 보류 대상 아님 목록)."""
    out = Path(out).resolve()
    rs = list(csv.DictReader((out / "per_variant.csv").open()))
    levels = list(csv.DictReader((RUN / "config/levels.csv").open()))
    s = {"scope": "offline port logical assignment consistency only (cs_shuffle.py). "
                  "Unity runtime identity / visual / solvable / difficulty = UNVERIFIED",
         "variants": len(rs), "groups": {}}
    for g in ("nonexcluded", "excluded"):
        gr = [r for r in rs if r["group"] == g]
        lv = {}
        for r in gr:
            lv.setdefault(r["level"], set()).add(r["status"])
        s["groups"][g] = {"variants": len(gr), "byStatus": dict(Counter(r["status"] for r in gr)),
                          "levels": len(lv),
                          "levelsAllPass": sum(1 for v in lv.values() if v == {"PASS"}),
                          "reasons": dict(Counter(x for r in gr if r["reason"] for x in r["reason"].split(";"))),
                          "typesShort": sum(1 for r in gr if r["actualTypes"] and int(r["actualTypes"]) < int(r["requestedTypes"]))}
    s["checksAllTrue"] = {f: all(r[f] == "True" for r in rs) for f in
                          ("typesOK", "mod3OK", "keyOK", "totalOK", "structOK", "orderOK", "layersOK", "inputHashOK",
                           "condOK", "repro2OK", "visualRemapInvariant")}
    s["t0LeftTotal"] = sum(int(r["t0Left"] or 0) for r in rs)
    s["paddingUsed"] = sum(1 for r in rs if r["toAddLen"] not in ("", "0"))
    s["notTargetNoConfig"] = {
        "t0baseHoldLevels": [int(r["level"]) for r in levels if r["t0base"] != "OK"],
        "hardHold": [int(r["level"]) for r in levels if r["t0base"] == "OK" and r["hard"] != "OK"],
        "easyHold": [int(r["level"]) for r in levels if r["t0base"] == "OK" and r["easy"] != "OK"],
        "note": "no variant config exists -> not assigned, hold kept (not released)"}
    s["perVariantSha256"] = sha((out / "per_variant.csv").read_bytes())
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in s.items() if k != "notTargetNoConfig"}, ensure_ascii=False, indent=1))
    print({k: (len(v) if isinstance(v, list) else v) for k, v in s["notTargetNoConfig"].items()})


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--summary":
        summarize(sys.argv[2])
        sys.exit(0)
    sys.exit(main())
