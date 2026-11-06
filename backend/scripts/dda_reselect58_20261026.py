#!/usr/bin/env python3
"""DDA 역전 확인 58레벨 — 문제 시드 재선정 + 독립 확인 측정 (2026-10-26, 문서 54).

요청 codex-dda-reselect58-20261026. 승인 범위 = 로컬 재선정·확인 측정까지. 업로드·서버/GameBoost 접근·게임 저장소·
Unity·커밋 없음. 기존 스크립트·산출물 수정 없음(읽기만). 결과는 봇 기준(v2.4, θ≤0.65) — 실유저·런타임 PASS 아님.

입력: screen_refine_20261026 (정밀 raw_refine = 판정 근거, targets.json = 확정 시드 meta), confirm12 levels(확정 시드),
      spec_v2_3x4 pm1_selection/pm2_candidates(기존 미선정 후보), run_20261020_130623 t0base/levels.csv(신규 후보 생성).
측정 경로 = 문서 49/53 드라이버 재사용: 맵 = ac.run_once → resolvedMapSha256 → pv.t0ize.bot_level_json,
           판 = m20.games_task (set_rule_parity → _create_initial_state → _precompute_blocking_map → seed → _play_game).
같은 단계 3시드는 정렬하지 않는다 — 교체 시드는 같은 위치(pos)에 들어가고 나머지 시드·순서는 그대로.

명령 (cd backend && venv/bin/python scripts/dda_reselect58_20261026.py <cmd>)
  prep                 : 분류 재대조 + 문제 시드 판정 + 후보 생성(게임 0판) → plan.json (있으면 거부)
  prereg               : PREREG_reselect.json (있으면 거부). 탐색·확인 결과 보기 전
  run explore <B>      : 배치 B 후보 탐색 측정 (재개 가능)
  select <B>           : 배치 B 교체 결정(탐색 자료만, 규칙 고정) → select_B<B>.json (있으면 거부)
  run confirm <B>      : 배치 B 확인 측정(새 봇 대역, 교체 레벨만) (재개 가능)
  budget               : 배치 1 실비용 → 전체 예상 → budget.json (배치 2+ 실행 조건)
  report               : 산출물(levels/seeds/changes/candidates json/manifest/SHA256SUMS)
  status
안전: run.lock(pid)+같은 스크립트 확인, STOP 파일, swap free<500MB·pressure 4·디스크<10GiB → 새 작업 투입 멈춤·회복
(swap ≥900MB) 대기(진행 중 작업만 마침, 체크포인트 유지), ≤30초 간격 상태 출력.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
import dda_screen_refine_20261026 as sr  # noqa: E402  (stats, ZONES, THETAS, load_inputs, build_sel)
import dda_spec_v2_measure20_20261022 as m20  # noqa: E402  (games_task, newcombe, wilson, used_map_seeds)

ac = m20.ac
RUN = m20.RUN
DS = BACKEND / "data/dda_seeds"
OUT = DS / "reselect58_20261026"
SR = sr.OUT
SPEC = m20.SPEC
PLAN = sr.PLAN
SR_SUMS_SHA = "d52915ffdfd80c23daca04d8d523281fbbcb4917183679e04e962bef152f009f"
FR_SUMS_SHA = "63024cb7c08a343385a0057804239a5257e9d92214182af8d6c950201cd1ff0e"
C12_SUMS_SHA = "06ded52acf7ec4991c38ebf86f729520a3e542166716f4045f70f9d4c3993ff9"
PM1_SERVER5 = PLAN / "pm1_server5_preserve_change.csv"
CATALOG_V1 = DS / "dda_t0_seed_catalog.v1.json"
CATALOG_V1_SHA = "57930b559bf935f076b1f77051dd2afc1ed95db60cd4f2cad0bae350fdfc5d13"
ZONES = sr.ZONES                    # (field, zone, delta)
ZF = {zn: f for f, zn, _ in ZONES}
ZD = {zn: d for _, zn, d in ZONES}
ZORD = [zn for _, zn, _ in ZONES]
THETAS = sr.THETAS
UPLOADED9 = {35, 45, 61, 64, 72, 78, 87, 93, 97}
# 문서 53 §3-3 분류(재대조 대상, 문서 그대로 옮김)
DOC53 = {"교차": [254, 553, 571, 612, 633, 674, 734],
         "같은방향≥0.10": [35, 45, 61, 72, 93, 136, 167, 174, 175, 183, 187, 228, 232, 358, 434, 606, 609, 622, 683,
                       756, 772, 923, 955],
         "같은방향0.05~0.10": [64, 78, 87, 97, 105, 107, 112, 127, 146, 148, 227, 261, 265, 353, 363, 367, 387, 406,
                           462, 467],
         "같은방향<0.05": [302, 498, 526, 613, 679, 945, 1013, 1106]}

# ── 규칙 상수 (PREREG 에 그대로 기록) ──
FLOOR = 0.05          # 대상 쌍: 두 단계 중 큰 쪽 W > 0.05 (둘 다 ≤0.05 = 봇 바닥권 → 개선 판단 불가, 대상 아님)
DEV_MIN = 0.10        # 문제 시드: 같은 단계 나머지 2시드 평균 대비 역전 방향으로 ≥0.10 벗어남
GAIN_MIN = 0.03       # 문제 시드: 제외 시 대상 쌍 최소 g 가 ≥0.03 개선
MAX_PER_LEVEL = 2     # 레벨당 교체 상한(단계당 1)
K_CAND = 4            # 교체 단계당 후보 수(기존 미선정 PASS 후보 우선, 부족분 신규)
MAX_DRAW = 12         # 신규 추출 시도 상한(단계당)
NEAR = 0.20           # 후보 W 가 나머지 2시드 평균에서 ≤0.20 (새 극단 금지)
NEW_REV_TOL = 0.05    # 예측상 어느 쌍도 min(기존 g,0) − 0.05 미만 금지
PH = {"explore": {"games": 20, "base": 71_000_000}, "confirm": {"games": 100, "base": 73_000_000}}
MAP_SEED_LO, MAP_SEED_HI = 1_500_000_000, 1_599_999_999
MAP_SEED_KEY = "dda_reselect58_20261026/v1"
TOTAL_CAP = 600_000
B1_CAP = 60_000
MAX_PROC = 2
SWAP_MIN_MB, SWAP_RESUME_MB, DISK_MIN_GB = 500, 900, 10
MAX_PAUSE_SEC = 3 * 3600
PREREG = OUT / "PREREG_reselect.json"
X_RANGE = 0.30


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fsha(p):
    return sha(Path(p).read_bytes())


dump = m20.dump


def save(p, o):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def log(msg, name="run.log"):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    with (OUT / "logs" / name).open("a") as f:
        f.write(line + "\n")


def resource():
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True,
                         text=True).stdout.strip()
    sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    free = float(sw.split("free = ")[1].split("M")[0])
    disk = shutil.disk_usage(str(OUT)).free / 2 ** 30
    return lvl, free, disk, (lvl == "4" or free < SWAP_MIN_MB or disk < DISK_MIN_GB)


def check_inputs():
    assert fsha(SR / "SHA256SUMS") == SR_SUMS_SHA, "screen_refine SHA256SUMS"
    for line in (SR / "SHA256SUMS").read_text().splitlines():
        h, n = line.split("  ")
        assert fsha(SR / n) == h, f"screen_refine {n}"
    assert fsha(PLAN.parent / "SHA256SUMS") == FR_SUMS_SHA, "fullrange SHA256SUMS"
    assert fsha(sr.C12 / "SHA256SUMS") == C12_SUMS_SHA, "confirm12 SHA256SUMS"
    assert fsha(CATALOG_V1) == CATALOG_V1_SHA, "catalog v1"
    return sr.load_inputs()


# ───────────────────────── 분석 기본 ─────────────────────────
def seed_wn(rows):
    a = {}
    for r in rows:
        x = a.setdefault(r["map"], [0, 0])
        x[0] += r["wins"]
        x[1] += r["n"]
    return a


def pair_list(zones):
    return [(a, b) for i, a in enumerate(zones) for b in zones[i + 1:]]


def kind(a, b):
    return "교차" if (a in ("E2", "E1")) != (b in ("E2", "E1")) else "같은방향"


def info(Wa, Wb):
    return not ((Wa <= sr.EXT_LO and Wb <= sr.EXT_LO) or (Wa >= sr.EXT_HI and Wb >= sr.EXT_HI))


def means(sw):
    return {z: sum(v) / len(v) for z, v in sw.items()}


def tg_min(m, tps):
    return min(m[a] - m[b] for a, b in tps)


def rev_mass(m, tps):
    """대상 쌍 역전량 합 R = Σ max(0, −g). 0 = 대상 쌍 점추정 역전 없음"""
    return sum(max(0.0, m[b] - m[a]) for a, b in tps)


def find_problem_seeds(sw, tps):
    """sw = {zone: [seedW pos1..3]} (정밀 300판), tps = 대상 쌍. 규칙(PREREG judge.problemSeed) 그대로."""
    cur = {z: list(v) for z, v in sw.items()}
    picked, used_z = [], set()
    for _ in range(MAX_PER_LEVEL):
        m = means(cur)
        g0 = tg_min(m, tps)
        r0 = rev_mass(m, tps)
        if r0 <= 0:
            break
        rev = [(a, b) for a, b in tps if m[a] - m[b] < 0]
        best = None
        for zi, z in enumerate(ZORD):
            if z not in cur or z in used_z:
                continue
            easy_side = any(a == z for a, _ in rev)   # 더 쉬워야 하는데 어려움 → 어려운(낮은 W) 시드가 범인
            hard_side = any(b == z for _, b in rev)   # 더 어려워야 하는데 쉬움 → 쉬운(높은 W) 시드가 범인
            if not (easy_side or hard_side):
                continue
            for i, s in enumerate(cur[z]):
                oth = [x for j, x in enumerate(cur[z]) if j != i]
                o = sum(oth) / 2
                dev = (o - s) if easy_side and o - s >= DEV_MIN else (s - o) if hard_side and s - o >= DEV_MIN else None
                if dev is None:
                    continue
                m2 = dict(m)
                m2[z] = o
                gain = r0 - rev_mass(m2, tps)
                if gain < GAIN_MIN:
                    continue
                key = (round(gain, 9), round(dev, 9), -zi, -i)
                if best is None or key > best[0]:
                    best = (key, z, i, s, o, gain, dev)
        if best is None:
            break
        _, z, i, s, o, gain, dev = best
        picked.append({"zone": z, "pos": i + 1, "seedW": round(s, 4), "othersMean": round(o, 4),
                       "dev": round(dev, 4), "gainLOO": round(gain, 4), "gminBefore": round(g0, 4),
                       "revMassBefore": round(r0, 4)})
        cur[z][i] = o          # 이후 단계 판정은 '나머지 평균으로 대체' 가정
        used_z.add(z)
    return picked


def classify(st, pairs, zones):
    ip = [p for p in pairs if p["info"]]
    sig = [p for p in ip if p["hi"] < 0]
    for p in sig:
        a, b = p["pair"].split("-")
        p["kind"] = kind(a, b)
    cross = [p for p in sig if p["kind"] == "교차"]
    same = [p for p in sig if p["kind"] == "같은방향"]
    gmin = min(p["g"] for p in sig)
    if cross:
        lab = "교차"
    elif gmin <= -0.10:
        lab = "같은방향≥0.10"
    elif gmin <= -0.05:
        lab = "같은방향0.05~0.10"
    else:
        lab = "같은방향<0.05"
    tier = 1 if lab == "교차" else 2 if lab == "같은방향≥0.10" else 3 if lab == "같은방향0.05~0.10" else 4
    tps = []
    for p in sig:
        a, b = p["pair"].split("-")
        if max(st[a]["W"], st[b]["W"]) > FLOOR:
            tps.append((a, b))
    return {"label": lab, "tier": tier, "gminSig": gmin, "cross": cross, "same": same, "targetPairs": tps,
            "floorOnly": [p["pair"] for p in sig if tuple(p["pair"].split("-")) not in tps]}


# ───────────────────────── 후보 ─────────────────────────
def scan_used_seeds():
    """전역 고유: 기존 맵 randSeed 전부(m20.used_map_seeds) + data 아래 csv/json/jsonl 의 1e9..2^31-1 정수 전부."""
    used = set(m20.used_map_seeds())
    p = subprocess.run(["grep", "-rhoE", r"\b1[0-9]{9}\b|\b20[0-9]{8}\b|\b21[0-4][0-9]{7}\b", "--include=*.csv",
                        "--include=*.json", "--include=*.jsonl", str(BACKEND / "data")], capture_output=True,
                       text=True)
    used.update(int(x) for x in p.stdout.split())
    return used


def existing_cands(L, field):
    """spec_v2 기존 후보(cand 순서). ±1 = pm1_selection(=catalog v1 5개), ±2 = pm2_candidates."""
    out = []
    if field in ("ddaEasySeeds", "ddaHardSeeds"):
        for r in csv.DictReader((SPEC / "pm1_selection.csv").open()):
            if int(r["level"]) == L and r["field"] == field:
                out.append({"cand": int(r["cand"]), "randSeed": int(r["randSeed"]), "useTileCount": int(r["useTileCount"]),
                            "status": r["assignStatus"], "resolvedMapSha256": r["resolvedMapSha256"],
                            "selected": r["selected"] == "True", "dropReason": r["dropReason"]})
    else:
        d = {"ddaEasy2Seeds": "easy2", "ddaHard2Seeds": "hard2"}[field]
        for r in csv.DictReader((SPEC / "pm2_candidates.csv").open()):
            if int(r["level"]) == L and r["dir"] == d:
                out.append({"cand": int(r["cand"]), "randSeed": int(r["randSeed"]), "useTileCount": int(r["useTileCount"]),
                            "status": r["status"], "resolvedMapSha256": r["resolvedMapSha256"],
                            "selected": r["selected"] == "True", "dropReason": r["dropReason"],
                            "condSha256": r["condSha256"]})
    return sorted(out, key=lambda c: c["cand"])


def variants_cond(L, field, seed):
    d = {"ddaEasySeeds": "easy", "ddaHardSeeds": "hard"}[field]
    for v in csv.DictReader((RUN / "config/variants.csv").open()):
        if int(v["level"]) == L and v["dir"] == d and int(v["randSeed"]) == seed:
            return v["condSha256"]
    raise KeyError((L, field, seed))


def build_one(L, utc, seed):
    from app.core.pv.t0ize import bot_level_json
    t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
    r = dict(t0obj["row"])
    r["useTileCount"] = str(utc)
    r["randSeed"] = str(seed)
    r["map"] = t0obj["map"]
    _, resolved = ac.run_once(r)
    lj = bot_level_json(r, resolved)
    return lj, sha(dump(resolved)), sha(json.dumps(lj, sort_keys=True, ensure_ascii=False).encode())[:16]


def cmd_prep():
    import dda_seed_spec_v2_prepare_20261022 as prep
    ac.LOGF[0] = OUT / "logs/assign.log"   # prep import 가 기존 spec_v2 로그 경로로 바꾸므로 신규 폴더로 되돌림
    p = OUT / "plan.json"
    if p.exists():
        raise SystemExit("plan.json exists — not overwriting")
    c12, spec, _ = check_inputs()
    tg = json.loads((SR / "targets.json").read_bytes())
    fs = json.loads((SR / "final_summary.json").read_bytes())
    levels58 = fs["reselectCandidates"]
    assert len(levels58) == 58
    _, rrows = sr.read_raw("refine")
    rby = {}
    for r in rrows:
        rby.setdefault(r["level"], []).append(r)
    lcsv = {int(r["level"]): r for r in csv.DictReader((RUN / "config/levels.csv").open())}
    cat = {e["level"]: e for e in json.loads(CATALOG_V1.read_bytes())["levels"]}
    srv5 = {(int(r["level"]), r["field"]): r for r in csv.DictReader(PM1_SERVER5.open())}
    used = scan_used_seeds()
    c12seeds = {int(s) for r in c12.values() for f in r["fields"].values() if f for s in f.split(",")}
    assert c12seeds <= used
    in_band = sorted(s for s in used if MAP_SEED_LO <= s <= MAP_SEED_HI)
    rng = random.Random(MAP_SEED_KEY)
    lv = {}
    for L in levels58:
        seeds = tg["levels"][str(L)]["seeds"]
        st, pairs, allx, span, zones = sr.stats(L, seeds, rby[L])
        wn = seed_wn(rby[L])
        c = classify(st, pairs, zones)
        sw = {z: [wn[f"{z}:{i}"][0] / wn[f"{z}:{i}"][1] for i in (1, 2, 3)] for z in zones}
        probs = find_problem_seeds(sw, c["targetPairs"]) if c["targetPairs"] else []
        status = ("미실시(바닥권 — 대상 쌍 없음)" if not c["targetPairs"] else
                  "교체 대상 없음(단계 겹침 — 특정 시드 문제 아님)" if not probs else "재선정 대상")
        old53 = next(k for k, v in DOC53.items() if L in v)
        lv[L] = {"level": L, "N": c12[L]["N"], "uploaded9": L in UPLOADED9, "zones": zones,
                 "stageW": {z: round(st[z]["W"], 4) for z in zones},
                 "seedW": {z: [round(x, 4) for x in sw[z]] for z in zones},
                 "seeds": {z: c12[L]["fields"][ZF[z]].split(",") for z in zones},
                 "pairs": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()} for p in pairs],
                 "sigCross": [f"{p['pair']} {p['g']:+.3f}" for p in c["cross"]],
                 "sigSame": [f"{p['pair']} {p['g']:+.3f}" for p in c["same"]],
                 "gminSig": round(c["gminSig"], 4), "label": c["label"], "doc53Label": old53,
                 "labelChanged": old53 != c["label"], "tier": c["tier"],
                 "targetPairs": ["-".join(t) for t in c["targetPairs"]], "floorOnlyPairs": c["floorOnly"],
                 "problemSeeds": probs, "status": status}
    # 우선순위·배치: tier(1 교차, 2 같은방향≥0.10, 3 0.05~0.10, 4 <0.05) → 업로드 9 먼저 → gminSig 오름차순 → 레벨
    order = sorted(lv.values(), key=lambda x: (x["tier"], not x["uploaded9"], x["gminSig"], x["level"]))
    for i, x in enumerate(order):
        x["priority"] = i + 1
        x["batch"] = x["tier"]
    # 후보 생성 (우선순위 순 → 결정적)
    for x in order:
        L = x["level"]
        if x["status"] != "재선정 대상":
            continue
        lr = lcsv[L]
        b = (RUN / f"out/t0base/level_{L}.json").read_bytes()
        t0obj = json.loads(b)
        seen = set()
        for z in x["zones"]:
            for i, s in enumerate(x["seeds"][z]):
                seen.add(tg["levels"][str(L)]["seeds"][f"{z}:{i + 1}"]["resolvedMapSha256"])
        for fld in ("ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds", "ddaHard2Seeds"):
            for cnd in existing_cands(L, fld):
                if cnd["resolvedMapSha256"]:
                    seen.add(cnd["resolvedMapSha256"])
        for ps in x["problemSeeds"]:
            z = ps["zone"]
            field = ZF[z]
            utc = x["N"] + ZD[z]
            cur = {int(s) for zz in x["zones"] for s in x["seeds"][zz]} | {int(t0obj["row"]["randSeed"] or 0)}
            cands = []
            for cnd in existing_cands(L, field):
                if cnd["selected"] or cnd["status"] != "PASS" or cnd["randSeed"] in cur:
                    continue
                if len(cands) >= K_CAND:
                    break
                assert cnd["useTileCount"] == utc
                lj, h, bl = build_one(L, utc, cnd["randSeed"])
                assert h == cnd["resolvedMapSha256"], (L, field, cnd)
                cond = cnd.get("condSha256") or variants_cond(L, field, cnd["randSeed"])
                cands.append({"key": f"{z}:{ps['pos']}:c{cnd['cand']}", "source": "기존 미선정 후보(spec_v2 cand "
                              f"{cnd['cand']}, {cnd['dropReason']})", "randSeed": cnd["randSeed"], "useTileCount": utc,
                              "condSha256": cond, "resolvedMapSha256": h, "botLjSha16": bl, "assign": "PASS(기존 검사)"})
            draws, nfail = 0, []
            while len(cands) < K_CAND and draws < MAX_DRAW:
                while True:
                    s = rng.randint(MAP_SEED_LO, MAP_SEED_HI)
                    if s not in used:
                        used.add(s)
                        break
                draws += 1
                eff = dict(t0obj["row"])
                eff["useTileCount"] = str(utc)
                eff["randSeed"] = str(s)
                v = {"level": L, "dir": {"E2": "easy2", "E1": "easy", "H1": "hard", "H2": "hard2"}[z], "cand": 100 + draws,
                     "useTileCount": utc, "randSeed": s, "sourceCommit": lr["sourceCommit"],
                     "t0baseFileSha256": lr["t0baseFileSha256"], "t0baseMapSha256": lr["t0baseMapSha256"],
                     "requiredOrigMapSha256": lr["origMapSha256"],
                     "condSha256": sha(dump({"sourceCommit": lr["sourceCommit"], "t0baseMapSha256": lr["t0baseMapSha256"],
                                             "row": eff}))}
                rec = prep.check_variant(b, t0obj, v, "reselect58")
                if rec["status"] != "PASS" or rec["resolvedMapSha256"] in seen:
                    nfail.append({"randSeed": s, "why": rec.get("reason") or "resolved_map_duplicate"})
                    continue
                seen.add(rec["resolvedMapSha256"])
                lj, h, bl = build_one(L, utc, s)
                assert h == rec["resolvedMapSha256"]
                cands.append({"key": f"{z}:{ps['pos']}:f{draws}", "source": f"신규 추출({MAP_SEED_KEY} #{draws})",
                              "randSeed": s, "useTileCount": utc, "condSha256": v["condSha256"], "resolvedMapSha256": h,
                              "botLjSha16": bl, "assign": "PASS(check_variant)"})
            ps["candidates"] = cands
            ps["drawFails"] = nfail
            seen.update(c_["resolvedMapSha256"] for c_ in cands)
        # ±1 결속 기준(서버 5개 = 로컬 fullrange 분석 CSV serverCurrent, 없으면 catalog v1 5개)
        x["pm1Server5"] = {}
        for fld in ("ddaEasySeeds", "ddaHardSeeds"):
            r5 = srv5.get((L, fld))
            x["pm1Server5"][fld] = {"value": (r5 or {}).get("serverCurrent") or cat[L][fld],
                                    "src": "fullrange pm1_server5_preserve_change.csv serverCurrent" if r5 and
                                    r5.get("serverCurrent") else "catalog v1"}
        log(f"prep L{L}: problems {[(p['zone'], p['pos']) for p in x['problemSeeds']]} cands "
            f"{[len(p['candidates']) for p in x['problemSeeds']]}", "prep.log")
    allnew = [c_["randSeed"] for x in lv.values() for p in x["problemSeeds"] for c_ in p.get("candidates", [])]
    assert len(allnew) == len(set(allnew))
    out = {"levels": {str(L): lv[L] for L in sorted(lv)}, "order": [x["level"] for x in order],
           "mapSeedBand": [MAP_SEED_LO, MAP_SEED_HI], "existingInBand": in_band, "usedSeedsScanned": len(used),
           "inputs": {"screenRefineSums": SR_SUMS_SHA, "fullrangeSums": FR_SUMS_SHA, "confirm12Sums": C12_SUMS_SHA,
                      "catalogV1": CATALOG_V1_SHA, "pm1Server5Csv": fsha(PM1_SERVER5)}}
    save(p, out)
    c = Counter(x["status"] for x in lv.values())
    log(f"prep done: {dict(c)} labels {dict(Counter(x['label'] for x in lv.values()))} changed "
        f"{[x['level'] for x in lv.values() if x['labelChanged']]} problemSeeds "
        f"{sum(len(x['problemSeeds']) for x in lv.values())} cands {len(allnew)}", "prep.log")


# ───────────────────────── prereg ─────────────────────────
def plan_budget(plan):
    out = {}
    for x in plan["levels"].values():
        if x["status"] != "재선정 대상":
            continue
        ex = sum(len(p["candidates"]) for p in x["problemSeeds"]) * 3 * PH["explore"]["games"]
        nseeds = sum(len(v) for v in x["seeds"].values())
        cf = (nseeds + len(x["problemSeeds"])) * 3 * PH["confirm"]["games"]
        b = out.setdefault(x["batch"], {"levels": 0, "exploreMax": 0, "confirmMax": 0})
        b["levels"] += 1
        b["exploreMax"] += ex
        b["confirmMax"] += cf
    return out


def cmd_prereg():
    if PREREG.exists():
        raise SystemExit("PREREG exists — not overwriting")
    plan = json.loads((OUT / "plan.json").read_bytes())
    bud = plan_budget(plan)
    tot = sum(b["exploreMax"] + b["confirmMax"] for b in bud.values())
    bands = dict(m20.SEED_USED_BANDS, measure20=[m20.SEED_BASE], measure20_n0=[m20.N0_BOT_BASE],
                 confirm12=[65_000_000], screen=[67_000_000], refine=[69_000_000])
    for ph, c in PH.items():
        lo, hi = c["base"], c["base"] + (len(THETAS) - 1) * 10_000 + c["games"] - 1
        for g, vs in bands.items():
            for v in vs:
                assert hi < v or lo > v + 1_000_000, (ph, g, v)
    assert abs(PH["explore"]["base"] - PH["confirm"]["base"]) >= 1_000_000
    lv = plan["levels"].values()
    save(PREREG, {
        "written": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "request": "codex-dda-reselect58-20261026",
        "doc": "claudedocs/difficulty_personalization/54_dda_reselect58_20261026.md",
        "status": "탐색·확인 결과 보기 전 작성. 판정 근거 = 문서 53 정밀(raw_refine, 69M 대역) 자료만",
        "inputs": dict(plan["inputs"], planJson=fsha(OUT / "plan.json"), thisScriptSha256=fsha(Path(__file__)),
                       driverReused={"screenRefine": fsha(BACKEND / "scripts/dda_screen_refine_20261026.py"),
                                     "measure20": fsha(BACKEND / "scripts/dda_spec_v2_measure20_20261022.py"),
                                     "specV2Prepare": fsha(BACKEND / "scripts/dda_seed_spec_v2_prepare_20261022.py")}),
        "scope": {"levels": 58, "byStatus": dict(Counter(x["status"] for x in lv)),
                  "byLabel": dict(Counter(x["label"] for x in lv)),
                  "labelChangedVsDoc53": {str(x["level"]): f"{x['doc53Label']} → {x['label']}" for x in lv
                                          if x["labelChanged"]},
                  "infinity": "infinity_N ↔ level_{500+N}: 원본 결과 재사용 표기만, 별도 측정 없음",
                  "outOfScope": "예산 초과 198·평가불가 356·불확실 추가 측정 없음"},
        "classification": {
            "pair": "정밀 900판/단계, Newcombe 95%. 유의 역전 = 정보있는 쌍 상한<0. 교차 = E(E2/E1) vs H(H1/H2) 쌍, "
                    "같은방향 = E2-E1 또는 H1-H2",
            "label": "교차 유의 역전 1쌍 이상 = 교차, 아니면 유의 역전 최소 g 로 ≥0.10 / 0.05~0.10 / <0.05",
            "priority": "tier(교차 → 같은방향≥0.10 → 0.05~0.10 → <0.05) → 업로드 9행 먼저(위험 가중) → 최소 g 오름차순 → 레벨",
            "batches": "배치 = tier (1 교차 7 = 실비용 측정 파일럿, 2 큰 같은방향, 3 중간, 4 작은)",
            "targetPair": f"유의 역전 쌍 중 max(W_a, W_b) > {FLOOR} 만 대상 — 둘 다 ≤{FLOOR} 는 봇 바닥권(교체 효과를 900판으로도 "
                          "구분 못 함) → 대상 아님. 대상 쌍 없는 레벨 = '미실시(바닥권)' (작은 역전의 비용 대비 기준 겸함)"},
        "judge": {
            "problemSeed": f"대상 쌍 기준, 탐욕 최대 {MAX_PER_LEVEL}개(단계당 1). 후보 시드 = 현재 역전 대상 쌍의 쉬운 쪽 단계에서 "
                           f"나머지 2시드 평균보다 ≥{DEV_MIN} 낮은 시드, 또는 어려운 쪽 단계에서 ≥{DEV_MIN} 높은 시드. 그 시드를 "
                           f"나머지 2시드 평균으로 바꿨을 때 대상 쌍 역전량 합 R = Σmax(0,−g) 감소 ≥{GAIN_MIN} 이어야 함. 여럿이면 감소폭 → "
                           "편차 → 단계 순서 → 위치. 고른 뒤 '나머지 평균'으로 대체 가정하고 반복(R = 0 되면 멈춤). "
                           "정상 시드(조건 미충족) 보존",
            "overlap": "문제 시드 0개 = '교체 대상 없음(단계 겹침)': 단계 평균이 전반적으로 겹침 → 시드 교체 안 함, 잔여 역전으로 "
                       "보고(±1/±2 타일 수 차가 이 맵에서 난이도 순서를 못 만듦 — N±k 구조 결정 필요, 이번 범위 밖)",
            "candidates": f"교체 단계당 {K_CAND}개: (1) spec_v2 기존 미선정 PASS 후보(cand 순서, ±1 = catalog v1 5개 중 4·5번 "
                          f"= 서버 값) (2) 부족분은 신규 추출 — spec_v2 prepare 와 같은 규칙: 같은 t0base·원본 맵, useTileCount = "
                          f"N±k(해당 단계), check_variant(배정 정합: 종류수·mod3·키·총수·구조·순서·재현·visual remap) PASS, 레벨 내 "
                          f"resolved map 고유, 전역 randSeed 고유(기존 맵 시드 + data 아래 1e9~2^31 정수 전부 제외), 대역 "
                          f"[{MAP_SEED_LO},{MAP_SEED_HI}] random.Random({MAP_SEED_KEY!r}) 우선순위 순 결정적. 단계당 추출 시도 ≤"
                          f"{MAX_DRAW}",
            "explore": f"후보당 θ3×{PH['explore']['games']}판 = 60판, 봇 대역 {PH['explore']['base']}+θidx·10000+g. "
                       "비교 기준 = 같은 레벨 다른 시드의 정밀(69M) 시드 W",
            "selection": f"교체 단계별(문제 시드 순): 후보 W(60판) 가 같은 단계 나머지 2시드 정밀 평균에서 ≤{NEAR} AND 그 후보로 바꾼 "
                         f"예측(단계 평균 = 3시드 W 단순평균, 앞서 고른 교체 반영)에서 대상 쌍 역전량 합 R 감소 ≥{GAIN_MIN} AND 어느 쌍도 "
                         f"min(기존 g,0)−{NEW_REV_TOL} 미만 아님(정보있는 쌍). 적격 중 예측 R 최소 → 대상 쌍 최소 g 최대 → "
                         "|W−나머지평균| 작은 → 키 순. "
                         "적격 없음 = 그 단계 원 시드 유지('적합 후보 없음'). 교체 시드는 같은 위치(pos), 다른 시드·순서 불변",
            "confirm": f"교체 1개 이상 레벨만: 새 구성 전 시드(12, L358 = 9) + 교체된 원 시드(대조) 각 θ3×{PH['confirm']['games']}판 = "
                       f"300판(단계 900판, 정밀과 같은 기준). 봇 대역 {PH['confirm']['base']}+θidx·10000+g — 탐색·정밀과 다른 대역",
            "confirmVerdict": {
                "확인 통과": "새 구성에서 정보있는 쌍 전부 Newcombe 상한 ≥0 AND 대상 쌍 점추정 g ≥0",
                "약한 잔여(불확실)": "유의 역전 없음 AND 대상 쌍 또는 다른 정보있는 쌍 점추정 g<0",
                "잔여 역전": "정보있는 쌍 상한<0 1개 이상 (기존 대상 쌍 유지 / 신규 쌍 구분 기록)",
                "같은대역 대조": "원 구성(비교체 시드 확인 자료 + 원 시드 대조 자료)의 같은 대역 g 도 보고 — 개선 폭 참고",
                "극단": f"단계 내 시드 W max−min ≥{X_RANGE} 또는 쉬운 단계 ≤0.02/어려운 단계 ≥0.98 별도 열",
                "smallDiff": "작은 차이 통계 확정 요구 안 함(하한>0 요구 없음)"},
            "noReReselect": "확인 측정 결과로 다시 고르지 않음(재재선정·추가 후보 없음). 잔여·불확실·극단 그대로 보고",
            "multiplicity": "보정 없음",
        },
        "budget": {"plan": {str(k): v for k, v in bud.items()}, "planMaxTotal": tot, "totalCap": TOTAL_CAP,
                   "batch1Cap": B1_CAP,
                   "rule": "배치 1(교차) 탐색+확인 실측 → budget: 평균 판수/레벨 × 남은 대상 레벨 + 누적 > 상한이면 중지·보고(배치 "
                           "2+ 실행 안 함). 실행 중 누적이 상한 넘으면 새 작업 투입 안 함",
                   "cpuPerGame": "0.017 (문서 53 실측 12,113s/729,360판)"},
        "safety": {"procs": MAX_PROC, "lock": "OUT/run.lock(pid) + 같은 스크립트 run 프로세스 확인",
                   "resource": f"작업 투입 전·≤30초: swap free <{SWAP_MIN_MB}MB · pressure 4 · 디스크 <{DISK_MIN_GB}GiB → 새 작업 "
                               f"멈춤(진행 중만 마침), swap ≥{SWAP_RESUME_MB}MB 회복까지 대기(≤3h), 횟수 기록",
                   "checkpoint": "레벨 단위 append raw_<phase>.jsonl, 재개 시 기록된 (level,map,θ) 건너뜀, 중복 assert",
                   "progress": "≤30초 간격 로그"},
        "outputs": "신규 폴더만. levels_reselect58_candidates.json 은 '검토 후 동기화, 자동 교체 금지' 후보. ±1 접두 결속은 별도 열"
                   "(서버 값 미변경, 교체로 접두 불일치 → planned_change 대상 표시)",
        "label": "봇 기준(v2.4 규칙 정합, θ≤0.65). 실유저 클리어율·런타임 PASS 아님",
    })
    (OUT / "PREREG_reselect.sha256").write_text(f"{fsha(PREREG)}  PREREG_reselect.json\n")
    log(f"PREREG written sha={fsha(PREREG)} plan={bud} maxTotal={tot}")
    print(fsha(PREREG))


def check_prereg():
    pre = json.loads(PREREG.read_bytes())
    pin = (OUT / "PREREG_reselect.sha256").read_text().split()[0]
    if fsha(PREREG) != pin:
        raise SystemExit("PREREG sha mismatch")
    assert pre["inputs"]["planJson"] == fsha(OUT / "plan.json"), "plan.json changed"
    return pre


# ───────────────────────── run ─────────────────────────
def raw_path(ph):
    return OUT / f"raw_{ph}.jsonl"


def read_raw(ph):
    done, rows = set(), []
    p = raw_path(ph)
    if p.exists():
        for line in p.open():
            r = json.loads(line)
            k = (r["level"], r["map"], r["theta"])
            assert k not in done, ("dup", ph, k)
            done.add(k)
            rows.append(r)
    return done, rows


def level_task(a):
    rows = []
    t = time.time()
    for k, spec_ in a["maps"].items():
        lj, h, bl = build_one(a["level"], spec_["useTileCount"], spec_["randSeed"])
        assert bl == spec_["botLjSha16"], (a["level"], k)
        for ti in spec_["todo"]:
            r = m20.games_task({"level": a["level"], "map": k, "theta": THETAS[ti], "lj": lj, "games": a["games"],
                                "seedBase": a["base"] + ti * 10_000})
            r.pop("pid", None)
            r.update({"phase": a["phase"], "randSeed": spec_["randSeed"], "zone": spec_["zone"], "role": spec_["role"]})
            rows.append(r)
    return {"level": a["level"], "rows": rows, "sec": time.time() - t}


def maps_for(ph, B, plan):
    """{level: {key: {randSeed,useTileCount,botLjSha16,zone,role}}}"""
    tg = json.loads((SR / "targets.json").read_bytes())
    out = {}
    for Ls, x in plan["levels"].items():
        if x["batch"] != B or x["status"] != "재선정 대상":
            continue
        if ph == "explore":
            out[int(Ls)] = {c["key"]: {"randSeed": c["randSeed"], "useTileCount": c["useTileCount"],
                                       "botLjSha16": c["botLjSha16"], "zone": p["zone"], "role": "cand"}
                            for p in x["problemSeeds"] for c in p["candidates"]}
        else:
            sel = json.loads((OUT / f"select_B{B}.json").read_bytes())["levels"][Ls]
            if not sel["replacements"]:
                continue
            rep = {(r["zone"], r["pos"]): r for r in sel["replacements"]}
            m = {}
            for z in x["zones"]:
                for i in (1, 2, 3):
                    o = tg["levels"][Ls]["seeds"][f"{z}:{i}"]
                    if (z, i) in rep:
                        r = rep[(z, i)]
                        m[f"{z}:{i}"] = {"randSeed": r["newSeed"], "useTileCount": r["useTileCount"],
                                         "botLjSha16": r["botLjSha16"], "zone": z, "role": "new"}
                        m[f"old:{z}:{i}"] = {"randSeed": o["randSeed"], "useTileCount": o["useTileCount"],
                                             "botLjSha16": o["botLjSha16"], "zone": z, "role": "control_old"}
                    else:
                        m[f"{z}:{i}"] = {"randSeed": o["randSeed"], "useTileCount": o["useTileCount"],
                                         "botLjSha16": o["botLjSha16"], "zone": z, "role": "kept"}
            out[int(Ls)] = m
    return out


def all_games():
    return sum(r["n"] for ph in PH for r in read_raw(ph)[1])


def cmd_run(ph, B):
    check_prereg()
    lock = OUT / "run.lock"
    if lock.exists():
        pid = int(lock.read_text().split()[0])
        try:
            os.kill(pid, 0)
            raise SystemExit(f"lock held by live pid {pid}")
        except ProcessLookupError:
            log(f"stale lock (pid {pid}) — removing")
            lock.unlink()
    ps = subprocess.run(["pgrep", "-f", "dda_reselect58_20261026.py run"], capture_output=True, text=True).stdout.split()
    others = [p for p in ps if int(p) != os.getpid()]
    if others:
        raise SystemExit(f"other run process: {others}")
    lock.write_text(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')} {ph} B{B}\n")
    try:
        return _run(ph, B)
    finally:
        lock.unlink(missing_ok=True)


def _run(ph, B):
    blob = subprocess.run(["git", "hash-object", str(m20.BOT_FILE)], capture_output=True, text=True).stdout.strip()
    if blob != m20.BOT_BLOB:
        raise SystemExit(f"bot blob changed: {blob}")
    if (OUT / "STOP").exists():
        raise SystemExit("STOP file present")
    plan = json.loads((OUT / "plan.json").read_bytes())
    if B >= 2:
        bj = OUT / "budget.json"
        if not bj.exists() or not json.loads(bj.read_bytes())["proceed"]:
            raise SystemExit("budget.json missing or proceed=false — batch 2+ blocked")
    if ph == "confirm" and not (OUT / f"select_B{B}.json").exists():
        raise SystemExit("select first")
    mp = maps_for(ph, B, plan)
    games = PH[ph]["games"]
    done, _ = read_raw(ph)
    tasks = []
    for L in sorted(mp, key=lambda L: plan["levels"][str(L)]["priority"]):
        ms = {}
        for k, v in mp[L].items():
            todo = [ti for ti in range(len(THETAS)) if (L, k, THETAS[ti]) not in done]
            if todo:
                ms[k] = dict(v, todo=todo)
        if ms:
            tasks.append({"level": L, "maps": ms, "games": games, "base": PH[ph]["base"], "phase": ph})
    plan_games = sum(len(v["todo"]) for a in tasks for v in a["maps"].values()) * games
    so_far = all_games()
    if so_far + plan_games > TOTAL_CAP or (B == 1 and so_far + plan_games > B1_CAP):
        raise SystemExit(f"budget: {so_far}+{plan_games}")
    lvl, free, disk, bad = resource()
    log(f"[{ph} B{B}:start] levels {len(mp)} todoLevels {len(tasks)} games todo {plan_games} total so far {so_far} "
        f"pressure={lvl} swapFree={free:.0f}MB disk={disk:.0f}GiB prereg={fsha(PREREG)[:16]}")
    t0, last, g_run, cpu, pauses, paused_at = time.time(), 0.0, 0, 0.0, 0, None
    it = iter(tasks)
    nxt = next(it, None)
    stop = None
    with ProcessPoolExecutor(MAX_PROC) as ex, raw_path(ph).open("a") as fo:
        pend = set()
        while True:
            while not stop and nxt is not None and len(pend) < MAX_PROC * 2:
                lvl, free, disk, bad = resource()
                if (OUT / "STOP").exists():
                    stop = "STOP file"
                    log("STOP requested: STOP file")
                    break
                if bad or (paused_at and free < SWAP_RESUME_MB):
                    if not paused_at:
                        paused_at = time.time()
                        pauses += 1
                        log(f"PAUSE #{pauses}: pressure={lvl} swapFree={free:.0f}MB disk={disk:.0f}GiB — 새 작업 투입 멈춤")
                    elif time.time() - paused_at > MAX_PAUSE_SEC:
                        stop = "pause > 3h"
                        log("STOP: " + stop)
                    break
                if paused_at:
                    log(f"RESUME after {time.time() - paused_at:.0f}s swapFree={free:.0f}MB")
                    paused_at = None
                pend.add(ex.submit(level_task, nxt))
                nxt = next(it, None)
            if not pend and (stop or nxt is None):
                break
            fin, pend = wait(pend, timeout=15, return_when=FIRST_COMPLETED) if pend else (set(), set())
            if not fin and not pend:
                time.sleep(15)
            for f in fin:
                r = f.result()
                fo.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r["rows"]))
                fo.flush()
                os.fsync(fo.fileno())
                g_run += sum(x["n"] for x in r["rows"])
                cpu += sum(x["sec"] for x in r["rows"])
            if time.time() - last >= 30:
                last = time.time()
                lvl, free, disk, bad = resource()
                el = time.time() - t0
                log(f"[{ph} B{B}] games {g_run}/{plan_games} {el:.0f}s cpu {cpu:.0f}s inflight {len(pend)} "
                    f"{'PAUSED ' if paused_at else ''}pressure={lvl} swapFree={free:.0f}MB disk={disk:.0f}GiB")
    log(f"[{ph} B{B}:end] games {g_run} wall {time.time() - t0:.0f}s cpu {cpu:.0f}s pauses {pauses}"
        + (f" stopped: {stop}" if stop else ""))
    return 3 if stop else 0


# ───────────────────────── select ─────────────────────────
def explore_W(rows):
    a = seed_wn(rows)
    return {k: (w, n, w / n) for k, (w, n) in a.items()}


def cmd_select(B):
    check_prereg()
    p = OUT / f"select_B{B}.json"
    if p.exists():
        raise SystemExit(f"{p.name} exists — not overwriting")
    plan = json.loads((OUT / "plan.json").read_bytes())
    _, rows = read_raw("explore")
    mp = maps_for("explore", B, plan)
    out = {}
    for L in mp:
        x = plan["levels"][str(L)]
        lr = [r for r in rows if r["level"] == L]
        need = len(mp[L]) * len(THETAS)
        if len(lr) != need:
            raise SystemExit(f"L{L} explore incomplete {len(lr)}/{need}")
        ew = explore_W(lr)
        sw = {z: list(v) for z, v in x["seedW"].items()}
        tps = [tuple(t.split("-")) for t in x["targetPairs"]]
        allp = pair_list(x["zones"])
        g_before = {f"{a}-{b}": means(sw)[a] - means(sw)[b] for a, b in allp}
        reps, notes = [], []
        cur = {z: list(v) for z, v in sw.items()}
        for ps in x["problemSeeds"]:
            z, i = ps["zone"], ps["pos"] - 1
            oth = [v for j, v in enumerate(cur[z]) if j != i]
            o = sum(oth) / 2
            g0 = tg_min(means(cur), tps)
            r0 = rev_mass(means(cur), tps)
            best, evals = None, []
            for c in ps["candidates"]:
                w, n, W = ew[c["key"]]
                trial = {zz: list(v) for zz, v in cur.items()}
                trial[z][i] = W
                m = means(trial)
                gp = tg_min(m, tps)
                rp_ = rev_mass(m, tps)
                ok_near = abs(W - o) <= NEAR
                ok_gain = r0 - rp_ >= GAIN_MIN
                bad_new = [f"{a}-{b}" for a, b in allp
                           if info(m[a], m[b]) and m[a] - m[b] < min(g_before[f"{a}-{b}"], 0) - NEW_REV_TOL]
                elig = ok_near and ok_gain and not bad_new
                evals.append({"key": c["key"], "randSeed": c["randSeed"], "w": w, "n": n, "W": round(W, 4),
                              "absDiff": round(abs(W - o), 4), "predTargetGmin": round(gp, 4),
                              "predRevMass": round(rp_, 4), "eligible": elig,
                              "why": ";".join(([] if ok_near else [f"|W−평균|>{NEAR}"]) +
                                              ([] if ok_gain else [f"개선<{GAIN_MIN}"]) +
                                              ([f"새역전:{','.join(bad_new)}"] if bad_new else []))})
                if elig:
                    key = (-round(rp_, 9), round(gp, 9), -round(abs(W - o), 9), [-ord(ch) for ch in c["key"]])
                    if best is None or key > best[0]:
                        best = (key, c, W, gp)
            if best is None:
                notes.append({"zone": z, "pos": i + 1, "result": "적합 후보 없음 — 원 시드 유지", "evals": evals})
                continue
            _, c, W, gp = best
            cur[z][i] = W
            reps.append({"zone": z, "field": ZF[z], "pos": i + 1, "oldSeed": int(x["seeds"][z][i]),
                         "oldSeedW_refine": x["seedW"][z][i], "newSeed": c["randSeed"], "newKey": c["key"],
                         "source": c["source"], "useTileCount": c["useTileCount"], "condSha256": c["condSha256"],
                         "resolvedMapSha256": c["resolvedMapSha256"], "botLjSha16": c["botLjSha16"],
                         "newW_explore": round(W, 4), "othersMean_refine": round(o, 4),
                         "predTargetGmin": round(gp, 4), "gminBefore": round(g0, 4), "revMassBefore": round(r0, 4),
                         "predRevMass": round(rev_mass(means(cur), tps), 4),
                         "reason": f"{z} pos{i + 1} 시드 W {x['seedW'][z][i]:.3f} vs 나머지 평균 {o:.3f} (편차 {ps['dev']:.3f}) "
                                   f"→ 대상 쌍 {','.join(x['targetPairs'])} 역전 기여",
                         "evals": evals})
        out[str(L)] = {"replacements": reps, "kept": notes}
        log(f"select L{L}: replace {[(r['zone'], r['pos'], r['newKey'], r['newW_explore']) for r in reps]} "
            f"kept {[(n['zone'], n['pos']) for n in notes]}")
    save(p, {"batch": B, "preregSha256": fsha(PREREG), "rawExploreSha256": fsha(raw_path("explore")),
             "levels": out})


# ───────────────────────── budget / report ─────────────────────────
def confirm_eval(L, x, mrows):
    """새 구성(kept+new) 과 원 구성(kept+control_old) 의 단계·쌍 통계."""
    a = seed_wn(mrows)

    def zst(keys_by_zone):
        st = {}
        for z, ks in keys_by_zone.items():
            w = sum(a[k][0] for k in ks)
            n = sum(a[k][1] for k in ks)
            sw_ = [a[k][0] / a[k][1] for k in ks]
            st[z] = {"w": w, "n": n, "W": w / n, "seedW": sw_, "range": max(sw_) - min(sw_)}
        return st

    new = {z: [f"{z}:{i}" for i in (1, 2, 3)] for z in x["zones"]}
    old = {z: [f"old:{z}:{i}" if f"old:{z}:{i}" in a else f"{z}:{i}" for i in (1, 2, 3)] for z in x["zones"]}
    res = {}
    for nm, kz in (("new", new), ("old_sameband", old)):
        st = zst(kz)
        pairs = []
        for A, Bz in pair_list(x["zones"]):
            lo, hi = m20.newcombe(st[A]["w"], st[A]["n"], st[Bz]["w"], st[Bz]["n"])
            pairs.append({"pair": f"{A}-{Bz}", "g": st[A]["W"] - st[Bz]["W"], "lo": lo, "hi": hi,
                          "info": info(st[A]["W"], st[Bz]["W"])})
        res[nm] = (st, pairs)
    st, pairs = res["new"]
    ip = [p for p in pairs if p["info"]]
    sig = [p["pair"] for p in ip if p["hi"] < 0]
    tset = set(x["targetPairs"])
    neg = [p["pair"] for p in ip if p["g"] < 0]
    if sig:
        v = "잔여 역전"
    elif neg:
        v = "약한 잔여(불확실)"
    else:
        v = "확인 통과"
    ext = [z for z, s in st.items() if s["range"] >= X_RANGE] + \
          [z for z, s in st.items() if (z in ("E2", "E1") and s["W"] <= 0.02) or (z in ("H1", "H2") and s["W"] >= 0.98)]
    return {"verdict": v, "sigPairs": sig, "sigTarget": [p for p in sig if p in tset],
            "sigNew": [p for p in sig if p not in tset], "negPairs": neg, "extreme": sorted(set(ext)), "res": res}


def cmd_budget():
    check_prereg()
    plan = json.loads((OUT / "plan.json").read_bytes())
    b1 = [int(L) for L, x in plan["levels"].items() if x["batch"] == 1]
    _, er = read_raw("explore")
    _, cr = read_raw("confirm")
    g1 = sum(r["n"] for r in er + cr if r["level"] in b1)
    cpu1 = sum(r["sec"] for r in er + cr if r["level"] in b1)
    n1 = sum(1 for L in b1 if plan["levels"][str(L)]["status"] == "재선정 대상")
    per = g1 / max(n1, 1)
    rest = [x for x in plan["levels"].values() if x["batch"] >= 2 and x["status"] == "재선정 대상"]
    proj = g1 + per * len(rest)
    bud = plan_budget(plan)
    maxrest = sum(b["exploreMax"] + b["confirmMax"] for k, b in bud.items() if int(k) >= 2)
    proceed = proj <= TOTAL_CAP and g1 + maxrest <= TOTAL_CAP
    save(OUT / "budget.json", {"batch1Levels": n1, "batch1Games": g1, "batch1CpuSec": round(cpu1, 1),
                               "gamesPerLevel": round(per), "cpuPerGame": round(cpu1 / max(g1, 1), 4),
                               "restLevels": len(rest), "projectedTotal": round(proj), "restMaxGames": maxrest,
                               "worstCaseTotal": g1 + maxrest, "cap": TOTAL_CAP, "proceed": proceed})
    log(f"budget: B1 {g1} games / {n1} lv, per {per:.0f}, projected {proj:.0f}, worst {g1 + maxrest}, proceed {proceed}")


def pm1_bind(field, old3, new3, server5):
    from app.core.dda_seed_catalog_v2_2 import pm1_rule
    if field not in ("ddaEasySeeds", "ddaHardSeeds"):
        return "", ""
    ro, rn = pm1_rule(old3, server5), pm1_rule(new3, server5)
    od = ro["kind"] + ("" if ro["kind"] == "keep" else "/" + ro["resolution"])
    nd = rn["kind"] + ("" if rn["kind"] == "keep" else "/" + rn["resolution"])
    return od, nd


def f4(x):
    return round(x, 4)


def cmd_report():
    pre = check_prereg()
    plan = json.loads((OUT / "plan.json").read_bytes())
    c12, spec, _ = sr.load_inputs()
    _, er = read_raw("explore")
    _, cr = read_raw("confirm")
    sels = {}
    for B in (1, 2, 3, 4):
        p = OUT / f"select_B{B}.json"
        if p.exists():
            sels.update(json.loads(p.read_bytes())["levels"])
    inf = {int(r["sourceLevel"]): r for r in csv.DictReader((SR / "infinity_reuse_map.csv").open())}
    lv_rows, seed_rows, changes, cand_levels = [], [], [], []
    allseeds = Counter()
    for r in c12.values():
        for f in r["fields"].values():
            if f:
                allseeds.update(int(s) for s in f.split(","))
    verify = {"condHashUnchanged": True, "nk": True, "levelUnique": True, "globalUnique": True, "issues": []}
    for L in plan["order"]:
        x = plan["levels"][str(L)]
        sel = sels.get(str(L))
        row = {"level": L, "priority": x["priority"], "batch": x["batch"], "uploaded9": x["uploaded9"],
               "doc53Label": x["doc53Label"], "label": x["label"], "labelChanged": x["labelChanged"],
               "sigCross": "; ".join(x["sigCross"]), "sigSame": "; ".join(x["sigSame"]), "gminSig": x["gminSig"],
               "targetPairs": ",".join(x["targetPairs"]), "planStatus": x["status"],
               "problemSeeds": "; ".join(f"{p['zone']}:{p['pos']} W{p['seedW']:.3f} vs {p['othersMean']:.3f}"
                                         for p in x["problemSeeds"]),
               **{f"refine_W_{z}": x["stageW"][z] for z in x["zones"]},
               **{f"refine_seeds_{z}": "|".join(f"{v:.3f}" for v in x["seedW"][z]) for z in x["zones"]},
               "refine_pairs": "; ".join(f"{p['pair']} {p['g']:+.3f}[{p['lo']:+.3f},{p['hi']:+.3f}]"
                                         + ("" if p["info"] else " 정보없음") for p in x["pairs"]),
               "infinity": (f"infinity_{L - 500} ({inf[L]['copyable']}) — 원본 결과 재사용 표기, 측정 없음"
                            if L in inf else "")}
        if x["status"] != "재선정 대상":
            row["outcome"] = x["status"]
        elif sel is None:
            row["outcome"] = "미실시(배치 미진행)"
        elif not sel["replacements"]:
            row["outcome"] = "교체 없음(적합 후보 없음)"
        else:
            mrows = [r for r in cr if r["level"] == L]
            need = (sum(len(v) for v in x["seeds"].values()) + len(sel["replacements"])) * len(THETAS)
            if len(mrows) != need:
                row["outcome"] = f"확인 미완료({len(mrows)}/{need})"
            else:
                ce = confirm_eval(L, x, mrows)
                st, pairs = ce["res"]["new"]
                sto, pairso = ce["res"]["old_sameband"]
                row.update({"outcome": "교체+확인: " + ce["verdict"], "confirmVerdict": ce["verdict"],
                            "confirm_sigTarget": ",".join(ce["sigTarget"]), "confirm_sigNew": ",".join(ce["sigNew"]),
                            "confirm_negPairs": ",".join(ce["negPairs"]), "confirm_extreme": ",".join(ce["extreme"]),
                            **{f"confirm_W_{z}": f4(st[z]["W"]) for z in x["zones"]},
                            **{f"confirm_ci_{z}": "{:.3f}-{:.3f}".format(*m20.wilson(st[z]["w"], st[z]["n"]))
                               for z in x["zones"]},
                            **{f"confirm_seeds_{z}": "|".join(f"{v:.3f}" for v in st[z]["seedW"]) for z in x["zones"]},
                            "confirm_pairs": "; ".join(f"{p['pair']} {p['g']:+.3f}[{p['lo']:+.3f},{p['hi']:+.3f}]"
                                                       + ("" if p["info"] else " 정보없음") for p in pairs),
                            **{f"oldSameBand_W_{z}": f4(sto[z]["W"]) for z in x["zones"]},
                            "oldSameBand_pairs": "; ".join(f"{p['pair']} {p['g']:+.3f}[{p['lo']:+.3f},{p['hi']:+.3f}]"
                                                           for p in pairso)})
                a = seed_wn(mrows)
                newf = {ZF[z]: list(x["seeds"][z]) for z in x["zones"]}
                for rp in sel["replacements"]:
                    newf[rp["field"]][rp["pos"] - 1] = str(rp["newSeed"])
                srow = next(r for r in c12.values() if r["level"] == L)
                cl = json.loads(json.dumps(srow))
                for f_, v in newf.items():
                    cl["fields"][f_] = ",".join(v)
                for rp in sel["replacements"]:
                    k = f"{rp['zone']}:{rp['pos']}"
                    old3 = srow["fields"][rp["field"]]
                    new3 = cl["fields"][rp["field"]]
                    s5 = x.get("pm1Server5", {}).get(rp["field"], {}).get("value", "")
                    ob, nb = pm1_bind(rp["field"], old3, new3, s5) if s5 else ("", "")
                    cl["condSha256"][rp["field"]][rp["pos"] - 1] = rp["condSha256"]
                    changes.append({
                        "level": L, "field": rp["field"], "zone": rp["zone"], "pos": rp["pos"], "N": x["N"],
                        "useTileCount": rp["useTileCount"], "oldSeed": rp["oldSeed"], "newSeed": rp["newSeed"],
                        "source": rp["source"], "reason": rp["reason"], "condSha256": rp["condSha256"],
                        "resolvedMapSha256": rp["resolvedMapSha256"],
                        "oldW_refine300": rp["oldSeedW_refine"], "newW_explore60": rp["newW_explore"],
                        "othersMean_refine": rp["othersMean_refine"],
                        "oldW_confirm300": f4(a[f"old:{k}"][0] / a[f"old:{k}"][1]),
                        "newW_confirm300": f4(a[k][0] / a[k][1]),
                        "old3": old3, "new3": new3, "pm1Server5": s5,
                        "pm1Bind_old": ob, "pm1Bind_new": nb,
                        "pm1Note": ("" if not nb else "서버 값 미변경. " + (
                            "접두 유지" if nb == "keep" else
                            "교체로 접두 불일치 → planned_change 대상(" + nb.split("/")[-1] + ")")),
                        "uploaded9": x["uploaded9"], "confirmVerdict": ce["verdict"],
                        "infinity": row["infinity"]})
                    # 검증: N±k, 레벨 내 고유, 전역 고유
                    if rp["useTileCount"] != x["N"] + ZD[rp["zone"]]:
                        verify["nk"] = False
                        verify["issues"].append(f"L{L} {k} N±k")
                    if allseeds[rp["newSeed"]]:
                        verify["globalUnique"] = False
                        verify["issues"].append(f"L{L} {k} global dup")
                    allseeds[rp["newSeed"]] += 1
                lvseeds = [int(s) for f_ in cl["fields"].values() if f_ for s in f_.split(",")] + [srow["originalRandSeed"]]
                if len(lvseeds) != len(set(lvseeds)):
                    verify["levelUnique"] = False
                    verify["issues"].append(f"L{L} level dup")
                t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
                ch = sha(dump({k_: v for k_, v in t0obj["row"].items() if k_ not in
                               ("map", "ddaEasySeeds", "ddaHardSeeds")}))
                if ch != cl["sourceConditionHash"]:
                    verify["condHashUnchanged"] = False
                    verify["issues"].append(f"L{L} cond hash")
                cl["reselect58"] = {"replaced": [{"field": rp["field"], "pos": rp["pos"], "old": rp["oldSeed"],
                                                  "new": rp["newSeed"]} for rp in sel["replacements"]],
                                    "confirmVerdict": ce["verdict"], "status": "검토 후 동기화 후보 — 자동 교체 금지"}
                cand_levels.append(cl)
                for k in sorted(a):
                    ro = next(r for r in mrows if r["map"] == k)
                    seed_rows.append({"level": L, "phase": "confirm", "map": k, "role": ro["role"], "zone": ro["zone"],
                                      "randSeed": ro["randSeed"], "w": a[k][0], "n": a[k][1], "W": f4(a[k][0] / a[k][1])})
        if sel:
            for rp in sel["replacements"] + sel["kept"]:
                for e in rp["evals"]:
                    seed_rows.append({"level": L, "phase": "explore", "map": e["key"], "role": "cand", "zone": rp["zone"],
                                      "randSeed": e["randSeed"], "w": e["w"], "n": e["n"], "W": e["W"],
                                      "eligible": e["eligible"], "why": e["why"],
                                      "chosen": any(r.get("newKey") == e["key"] for r in sel["replacements"])})
        lv_rows.append(row)
    cols = []
    for r in lv_rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with (OUT / "levels_reselect58.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(lv_rows)
    if seed_rows:
        sc = []
        for r in seed_rows:
            for k in r:
                if k not in sc:
                    sc.append(k)
        with (OUT / "seeds_reselect58.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sc)
            w.writeheader()
            w.writerows(seed_rows)
    if changes:
        with (OUT / "changes.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(changes[0]))
            w.writeheader()
            w.writerows(changes)
    (OUT / "levels_reselect58_candidates.json").write_bytes(
        json.dumps(cand_levels, ensure_ascii=False, indent=0).encode())
    save(OUT / "verify.json", verify)
    summ = {"outcome": dict(Counter(r["outcome"] for r in lv_rows)),
            "labels": dict(Counter(r["label"] for r in lv_rows)),
            "labelChanged": {str(r["level"]): f"{r['doc53Label']} → {r['label']}" for r in lv_rows if r["labelChanged"]},
            "replacedSeeds": len(changes), "replacedByZone": dict(Counter(c["zone"] for c in changes)),
            "games": {"explore": sum(r["n"] for r in er), "confirm": sum(r["n"] for r in cr)},
            "cpuSec": {"explore": round(sum(r["sec"] for r in er), 1), "confirm": round(sum(r["sec"] for r in cr), 1)},
            "verify": verify}
    save(OUT / "summary.json", summ)
    save(OUT / "manifest.json", {
        "id": "dda_reselect58_20261026", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "검토 후 동기화, 자동 교체 금지 — 로컬 후보만. 서버·GameBoost·게임 카탈로그 미변경, 업로드 없음, 운영·무한 DDA OFF",
        "preregSha256": fsha(PREREG), "planSha256": fsha(OUT / "plan.json"),
        "candidatesFile": "levels_reselect58_candidates.json (confirm12 levels 형식, 교체 레벨만, 같은 단계 시드 순서 불변·교체 "
                          "위치만 변경, reselect58 메타 포함)",
        "pm1Binding": "±1 서버 5개 앞 3개 결속 — changes.csv pm1Bind_old/new 열. 서버 값 미변경. planned_change = 별도 결정 필요",
        "infinity": "infinity_N ↔ level_{500+N} 원본 결과 재사용 표기만 — 새 후보 채택 시 무한 복사 계획에 같은 값 반영 필요",
        "inputs": pre["inputs"], "summary": summ,
        "label": "봇 기준(v2.4, θ≤0.65). 확인 통과 ≠ 실유저 밸런스·런타임 PASS"})
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name not in ("SHA256SUMS", "run.lock", "STOP"))
    (OUT / "SHA256SUMS").write_text("".join(f"{fsha(p)}  {p.name}\n" for p in files))
    log("report: " + json.dumps(summ, ensure_ascii=False)[:3000])


def cmd_status():
    for ph in PH:
        d, rows = read_raw(ph)
        print(ph, "units", len(d), "games", sum(r["n"] for r in rows), "cpu", round(sum(r["sec"] for r in rows)),
              "levels", len({r["level"] for r in rows}))
    print("lock", (OUT / "run.lock").read_text() if (OUT / "run.lock").exists() else None, "resource", resource())


if __name__ == "__main__":
    a = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    if a == ["prep"]:
        rc = cmd_prep()
    elif a == ["prereg"]:
        rc = cmd_prereg()
    elif a[:1] == ["run"] and len(a) == 3 and a[1] in PH:
        rc = cmd_run(a[1], int(a[2]))
    elif a[:1] == ["select"] and len(a) == 2:
        rc = cmd_select(int(a[1]))
    elif a == ["budget"]:
        rc = cmd_budget()
    elif a == ["report"]:
        rc = cmd_report()
    elif a == ["status"]:
        rc = cmd_status()
    else:
        raise SystemExit(__doc__)
    sys.exit(rc or 0)
