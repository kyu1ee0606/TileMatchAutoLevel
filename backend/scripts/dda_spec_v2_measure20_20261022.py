#!/usr/bin/env python3
"""DDA 시드 규격 v2 (3x4) — 대표 20레벨 봇 난이도 측정 (2026-10-22, 문서 49).

서버 읽기·쓰기 없음. 게임 저장소·Unity 수정 없음. 재학습 없음. 결과는 봇 기준(v2.4 규칙 정합 V24_DEFAULT) — 실유저 클리어율 아님.

맵: 원본 = run_20261020_130623/out/orig/b741f6a3/level_L.json (출시 맵, cs 포트 배정 = 원본 그대로)
     후보 = t0base + (useTileCount, randSeed) → cs_shuffle.shuffle_level_row + resolve_map (dda_t0_assign_check 와 같은 경로)
           → resolvedMapSha256 를 pm1_selection.csv / pm2_candidates.csv 저장값과 대조(불일치 = 측정 중지)
     봇 입력 = pv.t0ize.bot_level_json(row, resolved)
봇: make_skill_profile(θ, "v2.4") (= V24_DEFAULT 규칙 6건, 행동 항목 없음), BotSimulator.set_rule_parity → _create_initial_state
    → 판마다 _rng.seed(SEED_BASE + θidx*10_000 + g) → _play_game  (natural_experiment.run_task / bot_v24_eval 와 같은 호출 순서)
    같은 (θ, g) 는 모든 맵·레벨에서 같은 시드 (CRN).
명령: select | prereg | run | report      (cd backend && /opt/homebrew/bin/python3.13 scripts/dda_spec_v2_measure20_20261022.py <cmd>)
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
import dda_t0_assign_check_20261020 as ac  # noqa: E402  (cs_shuffle 단독 로드 + run_once)

RUN = ac.RUN
SPEC = BACKEND / "data/dda_seeds/spec_v2_3x4_20261022"
SPEC_MANIFEST_SHA = "1a8b57da10c3d61b96659671ba32c220d9e53e873899f7851e46f92f058344ba"
OUT = BACKEND / "data/dda_seeds/spec_v2_measure20_20261022"
BOT_FILE = BACKEND / "app/core/bot_simulator.py"
BOT_BLOB = "06a5dc9b36a33c40178239c236c63a917071c796"   # HEAD b757f70 (V24_DEFAULT = 규칙 6건)
BOT_VER = "v2.4"
THETAS = (0.29, 0.47, 0.65)                             # pv.evaluate.THETAS (문서 48 §2 "θ 3점")
GAMES = 50
SEED_BASE = 61_000_000                                  # 새 대역: 61,000,000 ~ 61,020,049 (아래 SEED_USED 와 비중첩 확인)
SEED_USED_BANDS = {                                     # 레지스트리(seed_bands.json) + 스크립트·문서에서 쓰인 봇 시드 대역
    "R2_v1": [5_000_000, 6_000_000, 7_000_000, 9_100_000], "earlierChecks": [7_600_000, 7_800_000, 5_200_000,
                                                                            7_200_000, 9_300_000, 9_500_000],
    "v24confirm": [21_000_000, 21_200_000, 21_400_000, 21_600_000], "bot_v24_E1": [11_000_000],
    "natural_exp": [13_000_000], "doc_mentions": [8_200_000, 15_000_000, 16_000_000],
    "scripts_misc": [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_300_000, 6_300_000, 7_300_000, 8_000_000,
                     9_000_000, 9_400_000, 10_000_000, 23_000_000, 31_000_000, 32_000_000, 33_000_000,
                     41_000_000, 51_000_000, 52_000_000, 53_000_000],
}
FIELDS = [("ddaEasy2Seeds", "easy2", -2), ("ddaEasySeeds", "easy", -1), ("ddaHardSeeds", "hard", +1),
          ("ddaHard2Seeds", "hard2", +2)]
TIER = {"ddaEasy2Seeds": -2, "ddaEasySeeds": -1, "orig": 0, "ddaHardSeeds": 1, "ddaHard2Seeds": 2}
EXCLUDE = {358: "hard2 불가(N+2>t0세트)", 541: "hard2 불가(N+2>t0세트)", 158: "원본 조건 불일치(별도 승인)",
           1466: "원본 불일치·보류", 1523: "원본 불일치·보류", 35: "부스터 강제 튜토리얼", 45: "부스터 강제 튜토리얼"}
P5 = {429, 433, 441, 466, 479, 493, 494, 499}
SEGMENTS = [("32-100", 32, 100, 3), ("101-300", 101, 300, 5), ("301-500", 301, 500, 4),
            ("501-1000", 501, 1000, 4), ("1001+", 1001, 99999, 4)]
SEL_KEY = "dda_spec_v2_measure20_20261022/select/v1"
Z95 = 1.959964
MAX_PROC = 2
# ── 부록(2026-10-22, L65·L86 결과 확인 후 추가된 탐색적 대조군): N±0 = 원본 N 유지 t0 재배정, 레벨당 5개
N0_CANDS = 5
N0_SEED_KEY = "dda_spec_v2_measure20_n0_20261022/v1"
N0_SEED_LO, N0_SEED_HI = 1_400_000_000, 1_499_999_999   # 맵 randSeed: 11억(±1)·12억(hold126)·13억(±2) 대역 밖
N0_BOT_BASE = 63_000_000                                 # 봇 시드: 63,000,000~63,020,049 (61M 본 측정 등과 비중첩)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def save(p, o):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    with (OUT / "logs/run.log").open("a") as f:
        f.write(line + "\n")


def resource():
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True,
                         text=True).stdout.strip()
    sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    free = float(sw.split("free = ")[1].split("M")[0])
    return lvl, free, (lvl == "4" or free < 500)


# ───────────────────────── selection ─────────────────────────
def features(L, lr, t0obj):
    m = t0obj["map"]
    lay = [v for k, v in m.items() if k.startswith("layer_") and isinstance(v.get("tiles"), dict) and v["tiles"]]
    gim, stack, craft = set(), 0, 0
    for v in lay:
        for c in v["tiles"].values():
            if c[0].startswith("stack"):
                stack += 1
            if c[0].startswith("craft"):
                craft += 1
            e = (c[1] or "").split("_")[0]
            if e and not e.isdigit():
                gim.add(e)
            elif e.isdigit():
                gim.add("bomb")
    size = max(int(v.get("col", 0)) * int(v.get("row", 0)) for v in lay) if lay else 0
    return {"level": L, "N": int(lr["distinctNormal"]), "layers": len(lay), "tiles": int(lr["effTotal"]),
            "boardMaxCells": size, "gimmicks": sorted(gim - {"unknown"}), "unknown": "unknown" in gim,
            "stack": stack > 0, "craft": craft > 0, "t0Sets": int(lr["t0Sets"])}


def bins(f):
    N, la, t = f["N"], f["layers"], f["tiles"]
    out = {("N", "≤8" if N <= 8 else "9-10" if N <= 10 else "11-12" if N <= 12 else "≥13"),
           ("layers", "≤3" if la <= 3 else "4-6" if la <= 6 else "≥7"),
           ("tiles", "≤90" if t <= 90 else "91-150" if t <= 150 else "151-240" if t <= 240 else ">240"),
           ("stack", f["stack"]), ("craft", f["craft"]), ("gimmick_any", bool(f["gimmicks"])),
           ("unknown", f["unknown"])}
    out |= {("gimmick", g) for g in f["gimmicks"]}
    return out


def cmd_select():
    man = SPEC / "manifest.json"
    assert sha(man.read_bytes()) == SPEC_MANIFEST_SHA, "spec_v2 manifest sha mismatch"
    spec = {r["level"]: r for r in json.loads((SPEC / "levels_spec_v2.json").read_text())}
    levels = {int(r["level"]): r for r in csv.DictReader((RUN / "config/levels.csv").open())}
    pool, excluded = [], Counter()
    for L, s in sorted(spec.items()):
        if not all(s["fields"][f] for f, _, _ in FIELDS):
            excluded["not_ready4"] += 1
            continue
        if L in EXCLUDE or L in P5:
            excluded["explicit:" + EXCLUDE.get(L, "P5 격리")] += 1
            continue
        t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
        row = t0obj["row"]
        if int(float(row.get("autoCollectCount") or 0)) > 0:
            excluded["냥이(autoCollectCount>0)"] += 1
            continue
        if int(float(row.get("timea") or 0)) > 0:
            excluded["타임어택(timea>0)"] += 1
            continue
        pool.append(features(L, levels[L], t0obj))
    rng = random.Random(SEL_KEY)
    rng.shuffle(pool)
    covered, chosen = set(), []
    for name, lo, hi, q in SEGMENTS:
        seg = [f for f in pool if lo <= f["level"] <= hi]
        for _ in range(q):                       # 탐욕: 아직 안 덮인 (특징, 값) 을 가장 많이 더하는 레벨, 동률은 섞인 순서
            best = max(seg, key=lambda f: len(bins(f) - covered))
            seg.remove(best)
            covered |= bins(best)
            chosen.append(dict(best, segment=name, newBins=sorted(map(str, bins(best) - (covered - bins(best))))))
    chosen.sort(key=lambda f: f["level"])
    allbins = set().union(*(bins(f) for f in pool))
    save(OUT / "selection.json", {
        "rule": "pool = spec_v2 ready4 − 명시 제외(EXCLUDE·P5) − 냥이 − 타임어택; 구간 할당 3/5/4/4/4; 구간 안에서 "
                "탐욕 커버리지(N·층·타일수·스택·craft·기믹 유무/종류·unknown), 동률은 random.Random(SEL_KEY) 섞은 순서",
        "selKey": SEL_KEY, "poolSize": len(pool), "excludedCounts": dict(excluded),
        "binsCoveredBySelection": len(covered), "binsInPool": len(allbins),
        "binsMissing": sorted(map(str, allbins - covered)), "levels": chosen,
        "poolBySegment": {n: sum(1 for f in pool if lo <= f["level"] <= hi) for n, lo, hi, _ in SEGMENTS}})
    for f in chosen:
        print(f["segment"], f["level"], f["N"], f["layers"], f["tiles"], f["boardMaxCells"], f["gimmicks"],
              "S" if f["stack"] else "", "C" if f["craft"] else "", "U" if f["unknown"] else "")
    print("pool", len(pool), dict(excluded), "bins", len(covered), "/", len(allbins), sorted(map(str, allbins - covered)))


# ───────────────────────── maps ─────────────────────────
def cand_table():
    """{level: {field: [ {cand, randSeed, useTileCount, resolvedMapSha256, selected} ×5 ]}}"""
    t = {}
    for r in csv.DictReader((SPEC / "pm1_selection.csv").open()):
        t.setdefault(int(r["level"]), {}).setdefault(r["field"], []).append(
            {"cand": int(r["cand"]), "randSeed": int(r["randSeed"]), "useTileCount": int(r["useTileCount"]),
             "resolvedMapSha256": r["resolvedMapSha256"], "selected": r["selected"] == "True"})
    name = {"easy2": "ddaEasy2Seeds", "hard2": "ddaHard2Seeds"}
    for r in csv.DictReader((SPEC / "pm2_candidates.csv").open()):
        t.setdefault(int(r["level"]), {}).setdefault(name[r["dir"]], []).append(
            {"cand": int(r["cand"]), "randSeed": int(r["randSeed"]), "useTileCount": int(r["useTileCount"]),
             "resolvedMapSha256": r["resolvedMapSha256"], "selected": r["selected"] == "True",
             "assignStatus": r["status"]})
    for L in t:
        for f in t[L]:
            t[L][f].sort(key=lambda x: x["cand"])
    return t


def build_maps(L, ct, spec_row):
    from app.core.pv.t0ize import bot_level_json
    orig = json.loads((RUN / f"out/orig/b741f6a3/level_{L}.json").read_bytes())
    t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
    assert sha(dump(orig["map"])) == t0obj["origMapSha256"] == spec_row["sourceMapSha256"], f"L{L} orig sha"
    maps, meta = {}, {}
    row = dict(orig["row"])
    row["map"] = orig["map"]
    # 원본(비보류 후보 레벨)은 t0 가 없다 → 배정 없음, 출시 맵 그대로. randSeed>0 이면 포트로도 같은지 확인.
    assert not any(c[0] == "t0" for k, v in orig["map"].items() if k.startswith("layer_")
                   and isinstance(v.get("tiles"), dict) for c in v["tiles"].values()), f"L{L} orig has t0"
    resolved = orig["map"]
    if ac.cs.as_int(row.get("randSeed")) > 0:
        assert dump(ac.run_once(row)[1]) == dump(resolved), f"L{L} orig port differs"
    maps["orig"] = bot_level_json(row, resolved)
    meta["orig"] = {"field": "orig", "cand": 0, "randSeed": int(orig["row"]["randSeed"]),
                    "useTileCount": int(orig["row"]["useTileCount"]), "selected": True,
                    "resolvedMapSha256": sha(dump(resolved)), "origUnchanged": dump(resolved) == dump(orig["map"])}
    for field, _, _ in FIELDS:
        cands = ct[L][field]
        assert len(cands) == 5
        sel = [c["randSeed"] for c in cands if c["selected"]]
        assert ",".join(map(str, sel)) == spec_row["fields"][field], f"L{L} {field} selection mismatch"
        for c in cands:
            r = dict(t0obj["row"])
            r["useTileCount"] = str(c["useTileCount"])
            r["randSeed"] = str(c["randSeed"])
            r["map"] = t0obj["map"]
            res, resolved = ac.run_once(r)
            h = sha(dump(resolved))
            assert h == c["resolvedMapSha256"], f"L{L} {field} c{c['cand']} resolved sha mismatch"
            k = f"{field}:{c['cand']}"
            maps[k] = bot_level_json(r, resolved)
            meta[k] = dict(c, field=field)
    hashes = [m["resolvedMapSha256"] for m in meta.values()]
    assert len(set(hashes)) == len(hashes), f"L{L} duplicate resolved maps"
    for k, lj in maps.items():
        meta[k]["botLjSha16"] = sha(json.dumps(lj, sort_keys=True, ensure_ascii=False).encode())[:16]
    return maps, meta


def games_task(a):
    from app.core.bot_simulator import BotSimulator
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    lj = a["lj"]
    prof = make_skill_profile(a["theta"], BOT_VER)
    bot = BotSimulator()
    bot.set_rule_parity(prof)
    base = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(base)
    wins = []
    for g in range(a["games"]):
        bot._rng.seed(a["seedBase"] + g)
        wins.append(1 if bot._play_game(bot._fast_copy_state(base), prof).cleared else 0)
    return {"level": a["level"], "map": a["map"], "theta": a["theta"], "seedBase": a["seedBase"],
            "seedRange": [a["seedBase"], a["seedBase"] + a["games"] - 1], "n": a["games"], "wins": sum(wins),
            "perGame": "".join(map(str, wins)), "sec": round(time.time() - t0, 3), "pid": os.getpid()}


def cmd_prereg():
    p = OUT / "PREREG.json"
    if p.exists():
        raise SystemExit("PREREG exists — not overwriting")
    sel = json.loads((OUT / "selection.json").read_text())
    lo, hi = SEED_BASE, SEED_BASE + (len(THETAS) - 1) * 10_000 + GAMES - 1
    for g, vs in SEED_USED_BANDS.items():
        for v in vs:
            assert hi < v or lo > v + 1_000_000, (g, v)
    # 측정 전 맵 생성·결속 검사만 (게임 0판)
    ct = cand_table()
    spec = {r["level"]: r for r in json.loads((SPEC / "levels_spec_v2.json").read_text())}
    maps_meta = {}
    for f in sel["levels"]:
        _, meta = build_maps(f["level"], ct, spec[f["level"]])
        maps_meta[str(f["level"])] = meta
    save(OUT / "maps_meta.json", maps_meta)
    save(p, {
        "written": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "doc": "claudedocs/difficulty_personalization/49_*.md",
        "levels": [f["level"] for f in sel["levels"]], "selectionSha256": sha((OUT / "selection.json").read_bytes()),
        "mapsMetaSha256": sha((OUT / "maps_meta.json").read_bytes()),
        "bot": {"version": BOT_VER, "items": "V24_DEFAULT (규칙 6건)", "blob": BOT_BLOB,
                "call": "set_rule_parity → _create_initial_state → seed(base+θidx*10000+g) → _play_game"},
        "thetas": THETAS, "gamesPerTheta": GAMES, "mapsPerLevel": 21, "seedBand": [lo, hi],
        "seedFormula": "seed = 61_000_000 + θidx*10_000 + g (g<50), 모든 맵·레벨 공통 (CRN)",
        "metric": "W = 3θ 합산 클리어율 (150판). Δ = W_cand − W_orig. 필드 평균 = 선정 3개 합산(450판)",
        "ci": "맵 W: Wilson 95% (z=1.96, 150판 합산 이항 근사). Δ: Newcombe hybrid score 95% (독립 근사, CRN 무시 = 보수적)",
        "judge": {
            "direction": "쉬움(easy/easy2): Δ>0 일치, 어려움(hard/hard2): Δ<0 일치, Δ=0 = 변화 없음(불일치로 셈)",
            "confirmed": "방향 일치 AND Δ의 95% CI 가 0 을 포함하지 않음",
            "reversed_sig": "방향 반대 AND 95% CI 가 0 을 포함하지 않음",
            "ceiling_floor": "W_orig ≥ 0.95 이면 쉬움 필드, W_orig ≤ 0.05 이면 어려움 필드 = 평가 불가(판정 제외, 따로 집계)",
            "order": "기대 순서 W(easy2) ≥ W(easy) ≥ W(orig) ≥ W(hard) ≥ W(hard2). 필드 평균(선정 3개) 인접 쌍이 반대면 역전, "
                     "Newcombe CI 가 0 제외면 유의 역전. 후보 단위: 서로 다른 단계 후보 쌍(원본 포함) 중 더 쉬워야 할 쪽 W 가 "
                     "작으면 역전, CI 0 제외면 유의 역전",
            "unfit": "선정 후보 부적합 = (R1) 원본 대비 유의 역방향 OR (R2) 인접 단계(바깥쪽 또는 안쪽, 원본 제외) 의 기존 선정 3개 "
                     "합산 W 와 비교해 유의 역전",
            "reselect": "필드에 부적합 선정 후보가 1개라도 있으면 재선별 필요. 새 선정 = 5개 중 부적합(R1·R2 동일 기준, 기준값은 "
                        "기존 선정 합산) 제외 후 cand 순서 앞 3개 (측정값 순 고르기 아님 — 승자의 저주 방지). 3개 미만이면 그 필드 보류. "
                        "참고(채택 안 함): 측정 W 극단 순 3개를 골랐을 때 바뀌는 수",
            "levelSummary": "필드 평균 방향 일치·확인 여부, 역전 수",
            "noObsNoPass": "측정 안 한 후보·레벨은 '미측정' — PASS 로 세지 않음",
            "power": "150 vs 150판, p≈0.5 에서 Δ 95% CI 반폭 ≈ ±0.11. |Δ|<0.1 수준의 차이는 확인 불가가 정상",
            "multiplicity": "후보 400개 × z=1.96 — 영가설에서 우연 유의 역방향 기대 ≈ 400×0.025 = 10개. 보정 없음, 보고에 명시",
        },
        "cost": {"games": 20 * 21 * 3 * GAMES, "cpuPerGame": [0.020, 0.032, 0.045], "procs": MAX_PROC,
                 "expectedWallMin": [round(20 * 21 * 150 * c / 2 / 60, 1) for c in (0.020, 0.032)] +
                                    [round(20 * 21 * 150 * 0.045 / 1.5 / 60, 1)]},
        "resourceStop": "pressure critical(4) 또는 swap free < 500MB → 새 작업 중지·실행 중 풀 종료(체크포인트 유지)",
        "label": "봇 기준(v2.4 규칙 정합). 실유저 클리어율 아님",
    })
    log(f"PREREG written; maps built for {len(maps_meta)} levels, seed band {lo}..{hi}")


def used_map_seeds():
    """기존 randSeed 전부 (출시 행·±1 variants·±2 pm2·패키지 sets.csv)."""
    used = set()
    for v in csv.DictReader((RUN / "config/variants.csv").open()):
        used.add(int(v["randSeed"]))
    for r in csv.DictReader((SPEC / "pm2_candidates.csv").open()):
        used.add(int(r["randSeed"]))
    tbl = json.loads((RUN.parents[1] / "live_copy/b741f6a3/levels.json").read_text())
    ks = tbl["__keys"]
    for r in tbl["__vals"]:
        for t in str(r[ks.index("randSeed")]).split("|"):
            if t.strip().lstrip("-").isdigit():
                used.add(int(t))
    pkg = BACKEND / "data/pv_sandbox/pv_20261002_live3/dda_v24confirm_20261019/package_20261020_0544"
    for r in csv.DictReader((pkg / "sets.csv").open()):
        used.update(int(t) for t in r["randSeed"].split("|") if t.isdigit())
    return used


def build_n0(L, meta_n0):
    from app.core.pv.t0ize import bot_level_json
    t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
    maps = {}
    for k, c in meta_n0.items():
        if c["assignStatus"] != "PASS":
            continue
        r = dict(t0obj["row"])
        r["useTileCount"] = str(c["useTileCount"])
        r["randSeed"] = str(c["randSeed"])
        r["map"] = t0obj["map"]
        res, resolved = ac.run_once(r)
        assert sha(dump(resolved)) == c["resolvedMapSha256"], f"L{L} {k} n0 resolved sha mismatch"
        maps[k] = bot_level_json(r, resolved)
    return maps


def cmd_prereg_n0():
    import dda_seed_spec_v2_prepare_20261022 as prep   # check_variant (같은 배정 검사)
    p = OUT / "PREREG_addendum_n0.json"
    if p.exists():
        raise SystemExit("addendum exists — not overwriting")
    pre = json.loads((OUT / "PREREG.json").read_text())
    meta_all = json.loads((OUT / "maps_meta.json").read_text())
    levels = {int(r["level"]): r for r in csv.DictReader((RUN / "config/levels.csv").open())}
    lo, hi = N0_BOT_BASE, N0_BOT_BASE + (len(THETAS) - 1) * 10_000 + GAMES - 1
    for g, vs in dict(SEED_USED_BANDS, measure20=[SEED_BASE]).items():
        for v in vs:
            assert hi < v or lo > v + 1_000_000, (g, v)
    used = used_map_seeds()
    in_band = sorted(s for s in used if N0_SEED_LO <= s <= N0_SEED_HI)
    rng = random.Random(N0_SEED_KEY)
    out, nfail = {}, 0
    for L in pre["levels"]:
        lr = levels[L]
        t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
        b = (RUN / f"out/t0base/level_{L}.json").read_bytes()
        N = int(lr["distinctNormal"])
        seen = {m["resolvedMapSha256"] for m in meta_all[str(L)].values()}
        out[str(L)] = {}
        for c in range(1, N0_CANDS + 1):
            while True:
                s = rng.randint(N0_SEED_LO, N0_SEED_HI)
                if s not in used:
                    used.add(s)
                    break
            row = dict(t0obj["row"])
            row["useTileCount"] = str(N)
            row["randSeed"] = str(s)
            cond = sha(dump({"sourceCommit": t0obj["sourceCommit"], "t0baseMapSha256": lr["t0baseMapSha256"],
                             "row": row}))
            v = {"level": L, "dir": "n0", "cand": c, "useTileCount": N, "randSeed": s,
                 "sourceCommit": t0obj["sourceCommit"], "requiredOrigMapSha256": lr["origMapSha256"],
                 "t0baseFileSha256": lr["t0baseFileSha256"], "t0baseMapSha256": lr["t0baseMapSha256"],
                 "condSha256": cond}
            assert sha(b) == lr["t0baseFileSha256"]
            rec = prep.check_variant(b, t0obj, v, "n0")
            st = rec["status"]
            if st == "PASS" and rec["resolvedMapSha256"] in seen:
                st = "FAIL"
                rec["reason"] = "resolved_map_duplicate"
            seen.add(rec.get("resolvedMapSha256"))
            nfail += st != "PASS"
            out[str(L)][f"n0:{c}"] = {"field": "n0", "cand": c, "randSeed": s, "useTileCount": N,
                                      "condSha256": cond, "assignStatus": st, "assignReason": rec.get("reason", ""),
                                      "resolvedMapSha256": rec.get("resolvedMapSha256")}
        for k, lj in build_n0(L, out[str(L)]).items():
            out[str(L)][k]["botLjSha16"] = sha(json.dumps(lj, sort_keys=True, ensure_ascii=False).encode())[:16]
    save(OUT / "maps_meta_n0.json", out)
    save(p, {
        "written": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": "탐색적 대조군 — 기존 2레벨(L65·L86) 결과 확인 후 추가. 본 PREREG.json·판정 기준·재선별 규칙은 소급 변경 없음. "
                  "N±0 분석은 해석·권고용(재선별 규칙에 쓰지 않음)",
        "basePreregSha256": sha((OUT / "PREREG.json").read_bytes()),
        "mapsMetaN0Sha256": sha((OUT / "maps_meta_n0.json").read_bytes()),
        "candidatesPerLevel": N0_CANDS, "why5": "±1/±2 필드 후보 수(5)와 같게 — 같은 후보 간 산포 비교",
        "useTileCount": "원본 N (levels.csv distinctNormal = 메타 useTileCount)",
        "mapSeeds": {"rngKey": N0_SEED_KEY, "band": [N0_SEED_LO, N0_SEED_HI], "existingInBand": in_band,
                     "excluded": "출시 randSeed·±1 variants·±2 pm2·패키지 sets.csv (중복 0)"},
        "assign": "run_once(cs_shuffle) + spec_v2 prepare.check_variant (±2 와 같은 검사) + 레벨 내 resolved map 고유",
        "assignFail": nfail,
        "bot": pre["bot"], "thetas": THETAS, "gamesPerTheta": GAMES,
        "botSeedBand": [lo, hi], "botSeedFormula": "seed = 63_000_000 + θidx*10_000 + g — 본 측정(61M)과 다른 대역(지시). "
                                                     "N±0 와 다른 맵 비교는 독립 표본(Newcombe 독립 가정과 일치)",
        "analysis": {
            "A_reassign": "원본(디자이너) vs N±0: Δ = W_n0 − W_orig (후보별 150판, N±0 합산 5개=750판)",
            "B_typecount": "N±0 vs ±1/±2: Δ = W_field − W_n0합산 (필드 선정 3개 합산 450판 vs 750판, 후보별 150판). "
                           "의도 방향·확인/미확정/역방향 판정은 본 기준과 같음(기준만 원본→N±0 합산)",
            "C_original": "원본 vs ±1/±2 = 본 PREREG 기준 그대로",
            "decomp": "필드 평균 Δ(원본 기준) = (W_n0 − W_orig) + (W_field − W_n0) 로 분해 보고",
            "ci": "Wilson 95% / Newcombe hybrid 95% (z 1.96), 평가불가 기준은 기준 맵 W ≥0.95(쉬움)/≤0.05(어려움)",
        },
        "label": "봇 기준(v2.4 규칙 정합). 실유저 클리어율 아님",
    })
    log(f"addendum n0 written: levels {len(out)}, assignFail {nfail}, in-band existing {in_band}")


def cmd_run():
    pre = json.loads((OUT / "PREREG.json").read_text())
    blob = subprocess.run(["git", "hash-object", str(BOT_FILE)], capture_output=True, text=True).stdout.strip()
    if blob != BOT_BLOB:
        raise SystemExit(f"bot blob changed: {blob}")
    lvl, free, bad = resource()
    log(f"[resource:start] pressure={lvl} swapFree={free:.0f}MB")
    if bad:
        log("STOP: resource at start")
        return 2
    raw = OUT / "raw_rows.jsonl"
    done = set()
    if raw.exists():
        for line in raw.open():
            r = json.loads(line)
            done.add((r["level"], r["map"], r["theta"]))
    ct = cand_table()
    spec = {r["level"]: r for r in json.loads((SPEC / "levels_spec_v2.json").read_text())}
    meta_all = json.loads((OUT / "maps_meta.json").read_text())
    tasks = []
    for L in pre["levels"]:
        maps, meta = build_maps(L, ct, spec[L])
        assert all(meta[k]["botLjSha16"] == meta_all[str(L)][k]["botLjSha16"] for k in meta), f"L{L} lj drift"
        for k, lj in maps.items():
            for ti, th in enumerate(THETAS):
                if (L, k, th) not in done:
                    tasks.append({"level": L, "map": k, "theta": th, "lj": lj, "games": GAMES,
                                  "seedBase": SEED_BASE + ti * 10_000})
    total = 20 * 21 * len(THETAS)
    if (OUT / "PREREG_addendum_n0.json").exists():          # 본 측정 작업 먼저, 그 뒤 N±0
        mn0 = json.loads((OUT / "maps_meta_n0.json").read_text())
        for L in pre["levels"]:
            for k, lj in build_n0(L, mn0[str(L)]).items():
                assert sha(json.dumps(lj, sort_keys=True, ensure_ascii=False).encode())[:16] == mn0[str(L)][k]["botLjSha16"]
                total += len(THETAS)
                for ti, th in enumerate(THETAS):
                    if (L, k, th) not in done:
                        tasks.append({"level": L, "map": k, "theta": th, "lj": lj, "games": GAMES,
                                      "seedBase": N0_BOT_BASE + ti * 10_000})
    log(f"tasks todo {len(tasks)} / {total} (done {len(done)})")
    t0, last, n_done, games = time.time(), 0.0, len(done), 0
    it = iter(tasks)
    with ProcessPoolExecutor(MAX_PROC) as ex, raw.open("a") as fo:
        pend = set()
        stop = None
        while True:
            while not stop and len(pend) < MAX_PROC * 2:
                a = next(it, None)
                if a is None:
                    break
                pend.add(ex.submit(games_task, a))
            if not pend:
                break
            fin, pend = wait(pend, timeout=20, return_when=FIRST_COMPLETED)
            for f in fin:
                r = f.result()
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
                fo.flush()
                n_done += 1
                games += r["n"]
            if time.time() - last >= 30:
                last = time.time()
                lvl, free, bad = resource()
                el = time.time() - t0
                log(f"progress {n_done}/{total} tasks, games this run {games}, {el:.0f}s, "
                    f"{games / max(el, 1):.1f} g/s, pressure={lvl} swapFree={free:.0f}MB")
                if bad and not stop:
                    stop = f"resource pressure={lvl} swapFree={free:.0f}MB"
                    log("STOP requested: " + stop + " (finishing in-flight tasks only)")
    log(f"run end: {n_done}/{total} tasks, {time.time() - t0:.0f}s" + (f", stopped: {stop}" if stop else ""))
    return 3 if stop else 0


# ───────────────────────── report ─────────────────────────
def wilson(w, n, z=Z95):
    if n == 0:
        return (float("nan"),) * 2
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def newcombe(w1, n1, w2, n2, z=Z95):
    """CI of p1 − p2 (Newcombe hybrid score, method 10)."""
    p1, p2 = w1 / n1, w2 / n2
    l1, u1 = wilson(w1, n1, z)
    l2, u2 = wilson(w2, n2, z)
    d = p1 - p2
    return d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def verdict(tier, w, n, wr, nr):
    """의도 방향 판정 (§1-3 과 같은 규칙, 기준 맵 = (wr, nr))."""
    d = w / n - wr / nr
    lo, hi = newcombe(w, n, wr, nr)
    if tier == 0:
        return d, lo, hi, ("유의차" if lo > 0 or hi < 0 else "차이미확정")
    Wr = wr / nr
    intended = d > 0 if tier < 0 else d < 0
    sig = lo > 0 or hi < 0
    if (tier < 0 and Wr >= 0.95) or (tier > 0 and Wr <= 0.05):
        v = "평가불가(천장/바닥)"
    elif intended:
        v = "확인" if sig else "방향일치(미확정)"
    elif d == 0:
        v = "변화없음"
    else:
        v = "유의역방향" if sig else "역방향경향"
    return d, lo, hi, v


def cmd_report_n0(pre, meta_all, agg):
    mn0 = json.loads((OUT / "maps_meta_n0.json").read_text())
    rows, lv, cnt = [], [], Counter()
    for L in pre["levels"]:
        keys = [k for k, c in mn0[str(L)].items() if c["assignStatus"] == "PASS"]
        base = list(meta_all[str(L)])
        if any((L, k) not in agg or agg[(L, k)][1] != 150 for k in keys + base):
            lv.append({"level": L, "status": "미측정(불완전)"})
            continue
        wo = agg[(L, "orig")][0]
        w0 = sum(agg[(L, k)][0] for k in keys)
        n0 = 150 * len(keys)
        d, lo, hi, v = verdict(0, w0, n0, wo, 150)
        rec = {"level": L, "status": "측정", "W_orig": wo / 150, "W_n0": w0 / n0, "A_reassign": d, "A_lo": lo,
               "A_hi": hi, "A_verdict": v, "n0cands": {}, "fields": {}}
        cnt[("A", v, "up" if d > 0 else "down" if d < 0 else "0")] += 1
        for k in keys:
            dk, lk, hk, vk = verdict(0, agg[(L, k)][0], 150, wo, 150)
            rec["n0cands"][k] = {"W": agg[(L, k)][0] / 150, "dOrig": dk, "lo": lk, "hi": hk, "v": vk}
            rows.append({"level": L, "map": k, "kind": "n0", "W": round(agg[(L, k)][0] / 150, 4), "ref": "orig",
                         "delta": round(dk, 4), "lo": round(lk, 4), "hi": round(hk, 4), "verdict": vk,
                         "randSeed": mn0[str(L)][k]["randSeed"], "selected": ""})
        for field, _, _ in FIELDS:
            t = TIER[field]
            sel = [f"{field}:{c}" for c in range(1, 6) if meta_all[str(L)][f"{field}:{c}"]["selected"]]
            wf = sum(agg[(L, k)][0] for k in sel)
            dB, lB, hB, vB = verdict(t, wf, 450, w0, n0)
            dC, lC, hC, vC = verdict(t, wf, 450, wo, 150)
            rec["fields"][field] = {"W": wf / 450, "B_vsN0": dB, "B_lo": lB, "B_hi": hB, "B_verdict": vB,
                                    "C_vsOrig": dC, "C_lo": lC, "C_hi": hC, "C_verdict": vC,
                                    "decomp_reassign": w0 / n0 - wo / 150, "decomp_typecount": wf / 450 - w0 / n0}
            cnt[("B_field", vB)] += 1
            cnt[("C_field", vC)] += 1
            for c in range(1, 6):
                k = f"{field}:{c}"
                dk, lk, hk, vk = verdict(t, agg[(L, k)][0], 150, w0, n0)
                cnt[("B_cand", vk)] += 1
                rows.append({"level": L, "map": k, "kind": field, "W": round(agg[(L, k)][0] / 150, 4),
                             "ref": "n0_pooled", "delta": round(dk, 4), "lo": round(lk, 4), "hi": round(hk, 4),
                             "verdict": vk, "randSeed": meta_all[str(L)][k]["randSeed"],
                             "selected": meta_all[str(L)][k]["selected"]})
        lv.append(rec)
    with (OUT / "results_n0.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    save(OUT / "report_n0.json", {"levels": lv, "counts": {str(k): v for k, v in sorted(cnt.items(), key=str)},
                                  "label": "탐색적 대조군(해석·권고용). 봇 기준 — 실유저 아님"})
    print("N0:", json.dumps({str(k): v for k, v in sorted(cnt.items(), key=str)}, ensure_ascii=False))


def cmd_newver():
    """reselection.csv(§1-3 규칙)의 재선별 필드만 바꾼 spec_v2 다음 버전 산출물. 바뀌는 필드 없으면 만들지 않음."""
    rs = [r for r in csv.DictReader((OUT / "reselection.csv").open()) if r["needReselect"] == "True"]
    if not rs:
        print("no reselection — no new version")
        return 0
    nv = BACKEND / "data/dda_seeds/spec_v2_1_measure20_20261022"
    if nv.exists():
        raise SystemExit(f"{nv} exists")
    base_b = (SPEC / "levels_spec_v2.json").read_bytes()
    levels = json.loads(base_b)
    by = {r["level"]: r for r in levels}
    meta_all = json.loads((OUT / "maps_meta.json").read_text())
    pm2 = {(int(r["level"]), r["dir"], int(r["cand"])): r for r in csv.DictReader((SPEC / "pm2_candidates.csv").open())}
    v1 = {(int(v["level"]), v["dir"], int(v["cand"])): v for v in csv.DictReader((RUN / "config/variants.csv").open())}
    dirs = {"ddaEasySeeds": "easy", "ddaHardSeeds": "hard", "ddaEasy2Seeds": "easy2", "ddaHard2Seeds": "hard2"}
    changes = []
    for r in rs:
        L, field = int(r["level"]), r["field"]
        rec = by[L]
        old = rec["fields"][field]
        if r["hold"] == "True":
            new, conds = "", []
            rec["holds"][field] = "measure20_reselect_insufficient(<3 fit candidates)"
        else:
            cands = json.loads(r["newSel"])
            new = ",".join(str(meta_all[str(L)][f"{field}:{c}"]["randSeed"]) for c in cands)
            assert new == r["newSeeds"]
            src = pm2 if field in ("ddaEasy2Seeds", "ddaHard2Seeds") else v1
            conds = [src[(L, dirs[field], c)]["condSha256"] for c in cands]
        rec["fields"][field] = new
        rec["condSha256"][field] = conds
        rec.setdefault("measure20", {})[field] = {"old": old, "new": new, "unfitSelected": r["selUnfit"]}
        changes.append({"level": L, "field": field, "old": old, "new": new, "hold": r["hold"],
                        "unfitSelectedCand": r["selUnfit"], "newSelCand": r["newSel"]})
    nv.mkdir(parents=True)
    (nv / "levels_spec_v2_1.json").write_bytes(dump(levels))
    with (nv / "server_columns_spec_v2_1.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id"] + [fl for fl, _, _ in [FIELDS[1], FIELDS[2], FIELDS[0], FIELDS[3]]])
        for rec in levels:
            w.writerow([rec["id"]] + [rec["fields"][fl] for fl in ("ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds",
                                                                     "ddaHard2Seeds")])
    with (nv / "changes.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0]))
        w.writeheader()
        w.writerows(changes)
    seeds = [s for rec in levels for v in rec["fields"].values() if v for s in v.split(",")]
    assert len(seeds) == len(set(seeds)), "global seed duplicate"
    save(nv / "manifest.json", {
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "base": "spec_v2_3x4_20261022",
        "baseManifestSha256": SPEC_MANIFEST_SHA, "baseLevelsSha256": sha(base_b),
        "rule": "문서 49 §1-3 재선별 규칙(측정 20레벨만). 나머지 레벨은 spec_v2 그대로",
        "measurePrereg": sha((OUT / "PREREG.json").read_bytes()), "changes": len(changes),
        "warning": "게임 카탈로그 동기화 필요. 봇 기준 — 실유저 검증 아님. 업로드 안 함",
        "notUploaded": True})
    files = sorted(p for p in nv.iterdir() if p.name != "SHA256SUMS")
    (nv / "SHA256SUMS").write_text("".join(f"{sha(p.read_bytes())}  {p.name}\n" for p in files))
    print(nv, len(changes), sha((nv / "manifest.json").read_bytes()))


def cmd_report():
    pre = json.loads((OUT / "PREREG.json").read_text())
    meta_all = json.loads((OUT / "maps_meta.json").read_text())
    agg = {}
    th_rows = {}
    for line in (OUT / "raw_rows.jsonl").open():
        r = json.loads(line)
        k = (r["level"], r["map"])
        a = agg.setdefault(k, [0, 0, 0.0])
        a[0] += r["wins"]
        a[1] += r["n"]
        a[2] += r["sec"]
        th_rows[(r["level"], r["map"], r["theta"])] = r
    rows, lv_sum, inversions, resel = [], [], [], []
    cnt = Counter()
    for L in pre["levels"]:
        meta = meta_all[str(L)]
        if any((L, k) not in agg or agg[(L, k)][1] != 150 for k in meta):
            lv_sum.append({"level": L, "status": "미측정(불완전)"})
            cnt["level_unmeasured"] += 1
            continue
        W = {k: agg[(L, k)][0] / agg[(L, k)][1] for k in meta}
        wo, no = agg[(L, "orig")][0], 150
        Wo = W["orig"]
        pooled = {}
        for field, _, _ in FIELDS:
            ks = [f"{field}:{c}" for c in range(1, 6) if meta[f"{field}:{c}"]["selected"]]
            pooled[field] = (sum(agg[(L, k)][0] for k in ks), 450)
        pooled["orig"] = (wo, no)

        def judge(field, w, n):
            sgn = -1 if TIER[field] < 0 else 1           # 쉬움: W_cand − W_orig > 0 기대 → d = (W_orig − W_cand)·sgn < 0 ...
            d = w / n - Wo
            lo, hi = newcombe(w, n, wo, no)
            intended = d > 0 if TIER[field] < 0 else d < 0
            unevaluable = (TIER[field] < 0 and Wo >= 0.95) or (TIER[field] > 0 and Wo <= 0.05)
            sig = lo > 0 or hi < 0
            if unevaluable:
                v = "평가불가(천장/바닥)"
            elif intended and sig:
                v = "확인"
            elif intended:
                v = "방향일치(미확정)"
            elif d == 0:
                v = "변화없음"
            elif sig:
                v = "유의역방향"
            else:
                v = "역방향경향"
            del sgn
            return d, lo, hi, v, intended, unevaluable

        def unfit(field, k):
            w = agg[(L, k)][0]
            reasons = []
            d, lo, hi, v, _, unev = judge(field, w, 150)
            if v == "유의역방향":
                reasons.append("R1 원본 대비 유의 역방향")
            t = TIER[field]
            for nb in (t - 1, t + 1):
                if nb == 0 or abs(nb) > 2:
                    continue
                nf = next(f for f, tt in TIER.items() if tt == nb)
                pw, pn = pooled[nf]
                # 더 쉬운 단계(작은 tier)의 W 가 커야 한다
                easier_w, easier_n, harder_w, harder_n = (w, 150, pw, pn) if t < nb else (pw, pn, w, 150)
                lo2, hi2 = newcombe(easier_w, easier_n, harder_w, harder_n)
                if hi2 < 0:
                    reasons.append(f"R2 {nf} 합산 대비 유의 역전")
            return reasons

        fsum = {}
        for field, _, _ in FIELDS:
            w, n = pooled[field]
            d, lo, hi, v, intended, unev = judge(field, w, n)
            fsum[field] = {"W": w / n, "delta": d, "ciLo": lo, "ciHi": hi, "verdict": v}
            cand_info = []
            for c in range(1, 6):
                k = f"{field}:{c}"
                m = meta[k]
                wc, nc, sec = agg[(L, k)]
                dc, loc, hic, vc, intc, unevc = judge(field, wc, nc)
                wl, wh = wilson(wc, nc)
                uf = unfit(field, k)
                rows.append({"level": L, "field": field, "tier": TIER[field], "cand": c, "randSeed": m["randSeed"],
                             "useTileCount": m["useTileCount"], "selected": m["selected"], "wins": wc, "n": nc,
                             "W": round(wc / nc, 4), "wilsonLo": round(wl, 4), "wilsonHi": round(wh, 4),
                             "W_orig": round(Wo, 4), "delta": round(dc, 4), "deltaLo": round(loc, 4),
                             "deltaHi": round(hic, 4), "verdict": vc, "unfit": ";".join(uf),
                             **{f"W_th{th}": round(th_rows[(L, k, th)]["wins"] / GAMES, 3) for th in THETAS},
                             "cpuSec": round(sec, 1), "resolvedMapSha256": m["resolvedMapSha256"]})
                cnt[("cand", vc)] += 1
                if m["selected"]:
                    cnt[("sel", vc)] += 1
                cand_info.append({"cand": c, "selected": m["selected"], "unfit": uf, "W": wc / nc,
                                  "seed": m["randSeed"], "unev": unevc})
            sel_unfit = [x for x in cand_info if x["selected"] and x["unfit"]]
            ok = [x for x in cand_info if not x["unfit"]]
            new = ok[:3]
            ext = sorted(cand_info, key=lambda x: -x["W"] if TIER[field] < 0 else x["W"])[:3]
            resel.append({"level": L, "field": field, "selUnfit": [x["cand"] for x in sel_unfit],
                          "needReselect": bool(sel_unfit), "oldSel": [x["cand"] for x in cand_info if x["selected"]],
                          "newSel": [x["cand"] for x in new] if sel_unfit else None,
                          "newSeeds": ",".join(str(x["seed"]) for x in new) if sel_unfit and len(new) >= 3 else None,
                          "hold": bool(sel_unfit) and len(new) < 3,
                          "refExtremeSel": sorted(x["cand"] for x in ext),
                          "refExtremeDiffers": sorted(x["cand"] for x in ext) != [x["cand"] for x in cand_info
                                                                                  if x["selected"]]})
        # 역전: 필드 평균 인접 + 후보 단위 서로 다른 단계 쌍
        order = ["ddaEasy2Seeds", "ddaEasySeeds", "orig", "ddaHardSeeds", "ddaHard2Seeds"]
        f_inv = []
        for a, b in zip(order, order[1:]):
            (wa, na), (wb, nb) = pooled[a], pooled[b]
            if wa / na < wb / nb:
                lo, hi = newcombe(wa, na, wb, nb)
                f_inv.append({"pair": f"{a}<{b}", "Wa": wa / na, "Wb": wb / nb, "sig": hi < 0})
        units = [("orig", "orig", W["orig"])] + [(f, f"{f}:{c}", W[f"{f}:{c}"]) for f, _, _ in FIELDS
                                                  for c in range(1, 6)]
        c_inv = []
        for i, (fa, ka, wa) in enumerate(units):
            for fb, kb, wb in units[i + 1:]:
                if TIER[fa] == TIER[fb]:
                    continue
                (e_f, e_k, e_w), (h_f, h_k, h_w) = ((fa, ka, wa), (fb, kb, wb)) if TIER[fa] < TIER[fb] else \
                    ((fb, kb, wb), (fa, ka, wa))
                if e_w < h_w:
                    lo, hi = newcombe(agg[(L, e_k)][0], 150, agg[(L, h_k)][0], 150)
                    sel_both = (e_k == "orig" or meta[e_k]["selected"]) and (h_k == "orig" or meta[h_k]["selected"])
                    c_inv.append({"easier": e_k, "harder": h_k, "We": e_w, "Wh": h_w, "sig": hi < 0,
                                  "bothSelected": sel_both, "tierGap": abs(TIER[e_f] - TIER[h_f])})
        inversions.append({"level": L, "fieldInversions": f_inv, "candInversions": c_inv})
        n_pairs = sum(1 for i, a in enumerate(units) for b in units[i + 1:] if TIER[a[0]] != TIER[b[0]])
        lv_sum.append({"level": L, "status": "측정", "W_orig": Wo, "fields": fsum,
                       "fieldInvCount": len(f_inv), "fieldInvSig": sum(x["sig"] for x in f_inv),
                       "candPairs": n_pairs, "candInv": len(c_inv), "candInvSig": sum(x["sig"] for x in c_inv),
                       "candInvSigSelected": sum(x["sig"] and x["bothSelected"] for x in c_inv),
                       "cpuSec": sum(agg[(L, k)][2] for k in meta)})
    if (OUT / "PREREG_addendum_n0.json").exists():
        cmd_report_n0(pre, meta_all, agg)
    with (OUT / "results_candidates.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (OUT / "reselection.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(resel[0]))
        w.writeheader()
        for r in resel:
            w.writerow({k: (json.dumps(v) if isinstance(v, list) else v) for k, v in r.items()})
    save(OUT / "inversions.json", inversions)
    save(OUT / "report.json", {"levels": lv_sum, "counts": {str(k): v for k, v in cnt.items()},
                               "reselectFields": [r for r in resel if r["needReselect"]],
                               "refExtremeDiffers": sum(r["refExtremeDiffers"] for r in resel),
                               "label": pre["label"]})
    print(json.dumps({str(k): v for k, v in sorted(cnt.items(), key=str)}, ensure_ascii=False, indent=0))
    print("reselect fields:", [(r["level"], r["field"], r["selUnfit"], r["newSel"], r["hold"]) for r in resel
                                if r["needReselect"]])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    OUT.mkdir(parents=True, exist_ok=True)
    sys.exit({"select": cmd_select, "prereg": cmd_prereg, "prereg_n0": cmd_prereg_n0, "run": cmd_run, "newver": cmd_newver,
              "report": cmd_report}[cmd]() or 0)
