#!/usr/bin/env python3
"""DDA t0 보류 126 후속 준비 + 순수 오프라인 배정 검증 (2026-10-20, 사용자 새 계약).

대상: run_20261020_130623 의 t0base 보류 126레벨만 (orig_has_t0 70 + fixed_key_with_unlockTile>0 56).
  완료 1372 재작업 없음. L322 = DDA 후보 전체 제외 표시만 (사용자 결정, 기존 산출물 삭제 없음).
계약:
  - 원형 보존. 변형 맵 = 일반 t1~t15(컨테이너 내부 명시 포함, isKeyTile 제외) → t0. 기존 t0·고정키(t16/id key/effect key) 보존.
  - 키 기준선: 원형을 원본 randSeed 로 순수 배정(cs_shuffle) → 최종 키 총수 + 고정 키 좌표.
    변형(N-1/N+1 × 시드 5)의 최종 키 총수 == 기준선, 고정 키 좌표 유지 → PASS. 다르면 레벨 HOLD + 원인 기록.
    unlockTile 원본값 그대로 (0/차감 없음).
  - N: 원형 메타 useTileCount 와 원형 실제 배정 결과 distinct(키 제외, 컨테이너 내부 포함) 대조. 불일치/근거 부족 = HOLD.
  - 시드: 1회 고정 추출 (정적 유효 방향에만, 검증 결과로 재추출·재선별 없음).
경로: backend/app/core/pv/cs_shuffle.py 를 파일 경로로 단독 로드 (app/core import 회피). 봇/솔버/승률 모듈 로드 0 기록.
입력(읽기 전용): runs/run_20261020_130623/{config/levels.csv, config/variants.csv, exceptions.csv, out/orig/b741f6a3/*.json},
  패키지 sets.csv/seed_bands.json. 이전 run SHA256SUMS 를 시작 전/종료 후 재검사.
출력: runs/run_<id>/ 아래만.
사용: .venv/bin/python scripts/dda_t0_hold126_prepare_20261020.py [--limit N]   (N = 앞에서 N레벨 시험)
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import random
import re
import resource
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "data/pv_sandbox/dda_t0_all_20261020"
PREV = OUT / "runs/run_20261020_130623"
PREV_SUMS_SHA = "f3d49f56c791825f136758e79726e68ba3095ee51af4367e60b63dde4a1a2ca2"
PKG = BACKEND / "data/pv_sandbox/pv_20261002_live3/dda_v24confirm_20261019/package_20261020_0544"
PORT = BACKEND / "app/core/pv/cs_shuffle.py"
BASE_COMMIT = "b741f6a3"
N_CAND = 5
SEED_RNG_KEY = "dda_t0_hold126_20261020/v1"
SEED_LO, SEED_HI = 1_200_000_000, 1_299_999_999   # 이전 run 11억~12억 미만, 21.0M~21.6M 대역과 비중첩, 양의 Int32
L322_REASON = "excluded_all_dda: tiles 36 / 12 sets, N+1 impossible -> future new level (user decision 2026-10-20)"
NORMAL_RE = re.compile(r"^t([1-9]|1[0-5])$")
LAYER_RE = re.compile(r"^layer_(\d+)$")
FORBIDDEN_MOD = re.compile(r"bot_simulator|solver|simulator|difficulty|win_rate|winrate|autoplay|analyzer|generator")

_spec = importlib.util.spec_from_file_location("cs_shuffle_standalone", PORT)
cs = importlib.util.module_from_spec(_spec)
sys.modules["cs_shuffle_standalone"] = cs
_spec.loader.exec_module(cs)

RUN_ID = time.strftime("run_%Y%m%d_%H%M%S")
RUN = OUT / "runs" / RUN_ID
_last = [0.0]


def log(msg):
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with (RUN / "logs/run.log").open("a") as f:
        f.write(line + "\n")


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024  # macOS bytes


def resource_check(tag):
    """critical(4) 또는 swap free<500MB → True(중지)."""
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


def is_key(tid, eff):  # DB_Level.cs:234-238
    return tid == "t16" or str(tid).lower() == "key" or str(eff).lower() == "key"


def cells(m):
    for lk, lv in m.items():
        if lk.startswith("layer_") and isinstance(lv, dict) and isinstance(lv.get("tiles"), dict):
            for ck, cell in lv["tiles"].items():
                yield lk, ck, cell


def census(m):
    """일반 ID별 개수, 키 좌표 집합, t0 잔여, 유효 총수, 기타/문제. 컨테이너 내부 포함 (내부 id 없으면 t0 n개)."""
    cnt, keys, t0, total, other = Counter(), set(), 0, 0, Counter()
    for lk, ck, cell in cells(m):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        if tid.startswith("stack_") or tid.startswith("craft_"):
            info = cell[2] if len(cell) > 2 else None
            if not isinstance(info, list) or not info:
                other["container_no_info"] += 1
                continue
            n = int(info[0])
            total += n
            ids = info[1].split("_") if len(info) > 1 and info[1] else ["t0"] * n
            if len(ids) != n:
                other["inner_len_mismatch"] += 1   # 로더 t0 폴백 → 정상 변환 아님
                continue
            for i, x in enumerate(ids):
                if is_key(x, ""):
                    keys.add((lk, ck, i))
                elif NORMAL_RE.match(x):
                    cnt[x] += 1
                elif x == "t0":
                    t0 += 1
                else:
                    other[x] += 1
            continue
        total += 1
        if is_key(tid, eff):
            keys.add((lk, ck, None))
        elif NORMAL_RE.match(tid):
            cnt[tid] += 1
        elif tid == "t0":
            t0 += 1
        else:
            other[tid] += 1
    return cnt, keys, t0, total, other


def to_t0(m):
    """일반 id 만 t0 (내부 명시 포함). 키·기존 t0·셀/레이어 순서·기믹·컨테이너 루트/방향/N 보존."""
    out = json.loads(json.dumps(m))
    for lk, ck, cell in cells(out):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        if tid.startswith("stack_") or tid.startswith("craft_"):
            info = cell[2]
            if len(info) > 1 and info[1]:
                info[1] = "_".join("t0" if (NORMAL_RE.match(x) and not is_key(x, "")) else x
                                   for x in info[1].split("_"))
        elif NORMAL_RE.match(tid) and not is_key(tid, eff):
            cell[0] = "t0"
    return out


def struct_sig(m):
    """ID 값 무관 구조 서명: 레이어/셀 순서·위치·effect·컨테이너 루트/N·key 위치·메타."""
    sig = []
    for lk, ck, cell in cells(m):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        norm = "N" if (tid == "t0" or NORMAL_RE.match(tid)) and not is_key(tid, eff) else tid
        extra = None
        if len(cell) > 2:
            info = cell[2]
            ids = info[1].split("_") if len(info) > 1 and info[1] else []
            extra = (info[0], ["N" if (x == "t0" or NORMAL_RE.match(x)) and not is_key(x, "") else "K" for x in ids],
                     len(info))
        sig.append((lk, ck, norm, eff, len(cell), json.dumps(extra)))
    meta = {k: v for k, v in m.items() if not k.startswith("layer_")}
    lmeta = [(lk, {k: v for k, v in lv.items() if k != "tiles"}, type(lv.get("tiles")).__name__)
             for lk, lv in m.items() if lk.startswith("layer_") and isinstance(lv, dict)]
    return sha(dump([sig, meta, lmeta]))


def order_sig(m):
    return [(lk, list(lv["tiles"]) if isinstance(lv.get("tiles"), dict) else lv.get("tiles"))
            for lk, lv in m.items() if lk.startswith("layer_")]


def layers_ok(m):
    nums = [int(LAYER_RE.match(k).group(1)) for k in m if LAYER_RE.match(k)]
    return not [k for k in m if k.startswith("layer_") and not LAYER_RE.match(k)] and sorted(nums) == list(range(len(nums)))


def assign(row, m):
    """순수 오프라인 배정 2회 (재현 확인). strict=False 후 %3 별도 판정 (n=0 조기 return 포함)."""
    r = dict(row)
    r["map"] = m
    res = cs.shuffle_level_row(r, strict=False)
    resolved = cs.resolve_map(m, res)
    res2 = cs.shuffle_level_row(r, strict=False)
    resolved2 = cs.resolve_map(m, res2)
    return res, resolved, sha(dump(resolved)) == sha(dump(resolved2)) and res.assigned == res2.assigned


def single_seed(v):
    s = str(v if v is not None else "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def verify_sums(tag):
    """이전 run SHA256SUMS 자체 해시 + 전 항목 재계산."""
    p = PREV / "SHA256SUMS"
    ok_self = sha(p.read_bytes()) == PREV_SUMS_SHA
    bad, n = [], 0
    for line in p.read_text().splitlines():
        h, rel = line.split("  ", 1)
        n += 1
        if sha((OUT / rel).read_bytes()) != h:
            bad.append(rel)
    log(f"[sums:{tag}] selfSha={'OK' if ok_self else 'MISMATCH'} entries={n} bad={len(bad)}")
    return {"selfShaOK": ok_self, "entries": n, "bad": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    RUN.mkdir(parents=True, exist_ok=False)
    if resource_check("start"):
        log("start blocked by resource")
        return 2
    sums_before = verify_sums("before")

    prev_levels = {int(r["level"]): r for r in csv.DictReader((PREV / "config/levels.csv").open())}
    prev_exc = list(csv.DictReader((PREV / "exceptions.csv").open()))
    hold_reason = {}
    for e in prev_exc:
        if e["scope"] == "t0base":
            hold_reason.setdefault(int(e["level"]), []).append(e["reason"])
    excl_prev = {}
    for e in prev_exc:
        if e["scope"] == "autoApply":
            excl_prev.setdefault(int(e["level"]), []).append(e["reason"])
    targets = sorted(hold_reason)
    assert len(targets) == 126, len(targets)
    if a.limit:
        targets = targets[:a.limit]

    # 시드 사용 집합: 이전 run 변형, 레벨 행 randSeed, 패키지, 대역
    used = {int(v["randSeed"]) for v in csv.DictReader((PREV / "config/variants.csv").open())}
    orig = {}
    for L in sorted(prev_levels):
        o = json.loads((PREV / f"out/orig/{BASE_COMMIT}/level_{L}.json").read_bytes())
        for t in str(o["row"].get("randSeed", "")).split("|"):
            if t.strip().lstrip("-").isdigit():
                used.add(int(t))
        if L in hold_reason:
            orig[L] = o
    with (PKG / "sets.csv").open() as f:
        for r in csv.DictReader(f):
            for t in r["randSeed"].split("|"):
                if t.isdigit():
                    used.add(int(t))
    bands = json.loads((PKG / "seed_bands.json").read_text())
    band_ranges = [(v, v + 1_000_000) for g in bands.values() if isinstance(g, dict) for v in g.values()]
    assert all(hi < SEED_LO or lo > SEED_HI for lo, hi in band_ranges)
    rng = random.Random(SEED_RNG_KEY)

    def draw():
        while True:
            s = rng.randint(SEED_LO, SEED_HI)
            if s not in used:
                used.add(s)
                return s

    for sub in ("out/t0base", "config"):
        (RUN / sub).mkdir(parents=True, exist_ok=True)
    rows_out, variants, per_var, exc, done = [], [], [], [], []
    exc.append({"level": 322, "scope": "dda_candidate", "reason": L322_REASON})
    stop = None

    for L in targets:
        if time.time() - _last[0] > 50 and resource_check(f"L{L}"):
            stop = "resource(critical or swap free<500MB)"
            break
        o = orig[L]
        row, m = o["row"], o["map"]
        orig_sha = sha(dump(m))
        reasons = []
        c0, k0, t00, tot0, oth0 = census(m)
        utc_meta = cs.as_int(row.get("useTileCount"))
        unlock = cs.as_int(row.get("unlockTile"))
        seed0 = single_seed(row.get("randSeed"))
        if oth0:
            reasons.append("map_issue:" + ",".join(sorted(oth0)))
        if not layers_ok(m):
            reasons.append("layers_not_consecutive")

        # 1) 원형 기준선: 원본 seed 순수 배정 (t0 없으면 n=0 → CS:1202 조기 return, RNG 0)
        base = {"baseEmpty": None, "baseKeys": None, "baseN": None, "baseMod3": None, "baseRepro": None}
        resolved0 = None
        if not reasons and t00 == 0:
            # 원형에 t0 없음 → 게임은 emptyTilesLength==0 에서 return (CS:1202): RNG·unlockTile 키 추가 없음 = 원형 그대로
            resolved0 = m
            base.update(baseEmpty=0, baseKeys=len(k0), baseN=len(c0),
                        baseMod3=all(v % 3 == 0 for v in c0.values()) and len(k0) % 3 == 0, baseRepro=True)
            if not base["baseMod3"]:
                reasons.append("baseline_id_count_not_mult3")
        elif not reasons:
            if seed0 is None or seed0 == 0:
                reasons.append(f"baseline_seed_unusable(randSeed={row.get('randSeed')!r})")
            elif utc_meta <= 0:
                reasons.append("N_basis_missing(meta useTileCount<=0 with original t0 -> skin count)")
            else:
                try:
                    res0, resolved0, rep0 = assign(row, m)
                except cs.PvError as e:
                    reasons.append(f"baseline_port_{type(e).__name__}:{e}")
                else:
                    cb, kb, tb, totb, othb = census(resolved0)
                    base.update(baseEmpty=len(res0.slots), baseKeys=len(kb), baseN=len(cb),
                                baseMod3=all(v % 3 == 0 for v in cb.values()) and len(kb) % 3 == 0, baseRepro=rep0)
                    if tb:
                        reasons.append(f"baseline_t0_left:{tb}")
                    if not base["baseMod3"]:
                        reasons.append("baseline_id_count_not_mult3")
                    if not rep0:
                        reasons.append("baseline_not_reproducible")
                    if not k0 <= kb:
                        reasons.append("baseline_fixed_key_moved")
        # 2) N 근거: 메타 vs 원형 실제 배정 distinct
        N = base["baseN"]
        if N is not None and not reasons:
            if utc_meta <= 0 and t00 == 0:
                n_basis = f"meta useTileCount={row.get('useTileCount')!r} unset; original has no t0 -> realized distinct {N}"
            elif utc_meta != N:
                n_basis = f"meta useTileCount={utc_meta} != realized distinct {N}"
                reasons.append("N_basis_mismatch")
            else:
                n_basis = f"meta useTileCount={utc_meta} == realized distinct {N}"
        else:
            n_basis = ""
        # 3) 변형 맵
        tm, t0_sha, t0_map_sha, t0n = None, "", "", 0
        if not reasons:
            tm = to_t0(m)
            c1, k1, t01, tot1, oth1 = census(tm)
            chk = [n for n, ok in (("order", order_sig(tm) == order_sig(m)), ("struct", struct_sig(tm) == struct_sig(m)),
                                   ("total", tot1 == tot0), ("normal_left", not c1), ("keys", k1 == k0),
                                   ("issues", not oth1)) if not ok]
            t0n = t01
            if chk:
                reasons.append("convert_check_fail:" + ",".join(chk))
            elif t0n % 3:
                reasons.append("t0_count_not_mult3")
        sets_t0 = t0n // 3
        dirs = {}
        if not reasons:
            b = dump({"_note": "OFFLINE t0 BASE (hold126 follow-up) — NOT UPLOADED", "level": L,
                      "sourceCommit": BASE_COMMIT, "origMapSha256": orig_sha, "row": row, "map": tm})
            (RUN / f"out/t0base/level_{L}.json").write_bytes(b)
            t0_sha, t0_map_sha = sha(b), sha(dump(tm))
            for d, utc in (("easy", N - 1), ("hard", N + 1)):
                r = []
                if not 1 <= utc <= 15:
                    r.append(f"useTileCount_out_of_range({utc})")
                if utc > sets_t0 - max(unlock, 0):
                    r.append(f"useTileCount>{sets_t0 - max(unlock, 0)}normal_sets")
                if d == "easy" and utc < 2:
                    r.append("easy_types<2")
                dirs[d] = r
                if r:
                    exc.append({"level": L, "scope": d, "reason": ";".join(r)})
        # 4) 시드 1회 고정 추출 + 순수 배정 검증 (재추출·재선별 없음)
        lv_vars = []
        for d, r in dirs.items():
            if r:
                continue
            utc = N - 1 if d == "easy" else N + 1
            for j in range(N_CAND):
                seed = draw()
                eff_row = dict(row)
                eff_row["useTileCount"] = str(utc)
                eff_row["randSeed"] = str(seed)
                cond = sha(dump({"sourceCommit": BASE_COMMIT, "t0baseMapSha256": t0_map_sha, "row": eff_row}))
                res, rv, rep = assign(eff_row, tm)
                cv, kv, tv, totv, othv = census(rv)
                rec = {"level": L, "dir": d, "cand": j + 1, "useTileCount": utc, "randSeed": seed,
                       "actualTypes": len(cv), "idCounts": "|".join(f"{t}:{cv[t]}" for t in sorted(cv, key=lambda s: int(s[1:]))),
                       "keyBaseline": base["baseKeys"], "keyAfter": len(kv), "fixedKeysKept": k0 <= kv,
                       "emptySlots": len(res.slots), "toAddLen": len(res.to_add), "t0Left": tv,
                       "totalOK": totv == tot0, "structOK": struct_sig(rv) == struct_sig(tm),
                       "orderOK": order_sig(rv) == order_sig(m), "layersOK": layers_ok(rv), "repro2OK": rep,
                       "resolvedMapSha256": sha(dump(rv)), "rngCalls": res.rng_calls}
                why = []
                if rec["actualTypes"] != utc:
                    why.append("types_mismatch")
                if not (all(v % 3 == 0 for v in cv.values()) and len(kv) % 3 == 0):
                    why.append("id_count_not_mult3")
                if len(kv) != base["baseKeys"]:
                    why.append(f"key_total_changed({base['baseKeys']}->{len(kv)})")
                if not rec["fixedKeysKept"]:
                    why.append("fixed_key_moved")
                if tv:
                    why.append(f"t0_left:{tv}")
                if othv:
                    why.append("other_ids")
                if len(res.slots) == 0:
                    why.append("no_empty_slots")
                for f in ("totalOK", "structOK", "orderOK", "layersOK", "repro2OK"):
                    if not rec[f]:
                        why.append(f.replace("OK", "_fail"))
                rec["status"] = "PASS" if not why else "HOLD"
                rec["reason"] = ";".join(why)
                per_var.append(rec)
                lv_vars.append({"level": L, "dir": d, "cand": j + 1, "useTileCount": utc, "randSeed": seed,
                                "sourceCommit": BASE_COMMIT, "requiredOrigMapSha256": orig_sha,
                                "t0baseFileSha256": t0_sha, "t0baseMapSha256": t0_map_sha, "condSha256": cond,
                                "unlockTile": row.get("unlockTile"), "intent": d, "difficultyRank": None,
                                "verified": "offline port assignment only", "assignStatus": rec["status"],
                                "autoApply": ("excluded:" + "|".join(excl_prev[L])) if L in excl_prev
                                else "eligible(manual approval)"})
        variants.extend(lv_vars)
        key_changed = sorted({r["reason"] for r in per_var if r["level"] == L and "key_total_changed" in r["reason"]})
        if key_changed:
            cause = ("original has no t0 -> ShuffleEmptyTiles returns at emptyTilesLength==0 (DB_Level.cs:1202) before "
                     f"unlockTile is read (:1204), so unlockTile={unlock} key sets are never added in the original; t0 "
                     f"variant has empty slots -> DistributeTiles adds {unlock} key set(s) (:1208/:1496) -> dock lock "
                     "slots keyTileCount/3 increase (Dock.cs:874)") if base["baseEmpty"] == 0 and unlock > 0 else \
                "key total differs from baseline; see per_variant.csv"
            exc.append({"level": L, "scope": "key_baseline", "reason": cause})
        lv_status = {r["status"] for r in per_var if r["level"] == L}
        ready = {d: (not dirs.get(d)) and d in dirs and
                 all(r["status"] == "PASS" for r in per_var if r["level"] == L and r["dir"] == d)
                 for d in ("easy", "hard")}
        for rr in reasons:
            exc.append({"level": L, "scope": "level", "reason": rr})
        rows_out.append({"level": L, "prevHoldReason": ";".join(hold_reason[L]), "origMapSha256": orig_sha,
                         "t0baseFileSha256": t0_sha, "t0baseMapSha256": t0_map_sha,
                         "metaUseTileCount": row.get("useTileCount"), "N": N, "nBasis": n_basis,
                         "unlockTile": row.get("unlockTile"), "fixedKeys": len(k0), "origT0": t00,
                         "baselineEmpty": base["baseEmpty"], "baselineKeys": base["baseKeys"],
                         "effTotal": tot0, "t0Count": t0n, "t0Sets": sets_t0,
                         "easy": "READY" if ready["easy"] else "HOLD", "hard": "READY" if ready["hard"] else "HOLD",
                         "levelStatus": "READY" if ready["easy"] and ready["hard"] else
                         ("PARTIAL" if ready["easy"] or ready["hard"] else "HOLD"),
                         "variantStatuses": "|".join(sorted(lv_status)),
                         "autoApplyExclude": "|".join(excl_prev.get(L, [])), "holdReasons": ";".join(reasons)})
        done.append(L)
        (RUN / "checkpoint.json").write_text(json.dumps({"done": done, "stopReason": stop}))

    (RUN / "checkpoint.json").write_text(json.dumps({"done": done, "total": len(targets), "stopReason": stop}))

    def wcsv(p, rows, fields=None):
        if not rows:
            return
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    wcsv(RUN / "config/levels.csv", rows_out)
    wcsv(RUN / "config/variants_all.csv", variants)
    ready_lv = {(r["level"], d) for r in rows_out for d in ("easy", "hard") if r[d] == "READY"}
    ready_vars = [v for v in variants if (v["level"], v["dir"]) in ready_lv]
    wcsv(RUN / "config/variants.csv", ready_vars)
    wcsv(RUN / "per_variant.csv", per_var)
    wcsv(RUN / "exceptions.csv", exc, ["level", "scope", "reason"])
    seeds = [v["randSeed"] for v in variants]
    assert len(seeds) == len(set(seeds)) and all(0 < s < 2**31 for s in seeds)
    bad_mods = sorted(n for n in sys.modules if FORBIDDEN_MOD.search(n))
    sums_after = verify_sums("after")
    st = Counter(r["levelStatus"] for r in rows_out)
    manifest = {
        "id": "dda_t0_hold126_20261020", "runId": RUN_ID, "stopReason": stop,
        "status": "OFFLINE PREPARATION ONLY — not applied; no bot/solver/win-rate/difficulty run",
        "inputRun": {"path": str(PREV.relative_to(OUT)), "SHA256SUMS_sha256": PREV_SUMS_SHA,
                     "sumsBefore": sums_before, "sumsAfter": sums_after},
        "userDecision": {"L322": L322_REASON, "priorL322Artifacts": "kept (not deleted); excluded from DDA candidates"},
        "contract": {
            "variantMap": "normal t1..t15 (incl. explicit container inner) -> t0; existing t0, fixed keys "
                          "(t16/id key/effect key) position/count/effect, containers, gimmicks, order kept",
            "keyBaseline": "original map assigned with original randSeed (cs_shuffle) -> final key total + fixed key "
                           "coords; every variant must keep the same total and fixed coords; unlockTile kept as original",
            "N": "meta useTileCount must equal realized distinct (non-key, incl. container inner) of the original "
                 "assignment; else HOLD", "easy": "N-1", "hard": "N+1", "validRange": "1..15",
            "seed": {"rng": f"random.Random({SEED_RNG_KEY!r}) level order, easy then hard, statically valid dirs only",
                     "range": [SEED_LO, SEED_HI], "excluded": "prior run variants, level randSeeds, package sets, bands",
                     "redrawOrReselect": "none"},
        },
        "counts": {"targets": len(targets), "processed": len(rows_out), "levelStatus": dict(st),
                   "variantsDrawn": len(variants), "variantsReady": len(ready_vars),
                   "perVariant": dict(Counter(r["status"] for r in per_var)),
                   "readyAutoApplyExcluded": sum(1 for r in rows_out if r["levelStatus"] == "READY" and r["autoApplyExclude"]),
                   "exceptionReasons": dict(Counter(e["scope"] + ":" + re.split(r"[:(]", e["reason"])[0] for e in exc))},
        "forbiddenModulesLoaded": bad_mods, "maxRssMB": round(rss_mb(), 1),
        "port": str(PORT.relative_to(BACKEND)), "portSha256": sha(PORT.read_bytes()),
        "generatedBy": "backend/scripts/dda_t0_hold126_prepare_20261020.py",
        "scriptSha256": sha(Path(__file__).read_bytes()),
        "unverified": ["Unity runtime identity (G3)", "visual remap runtime", "solvable", "difficulty", "apply"],
    }
    (RUN / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    lines = [f"{sha(p.read_bytes())}  {p.relative_to(OUT)}" for p in sorted(RUN.rglob("*"))
             if p.is_file() and p.name != "SHA256SUMS" and p.suffix != ".log"]
    (RUN / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    resource_check("end")
    log("counts " + json.dumps(manifest["counts"], ensure_ascii=False) + f" forbidden={bad_mods}")
    return 0 if stop is None else 3


if __name__ == "__main__":
    sys.exit(main())
