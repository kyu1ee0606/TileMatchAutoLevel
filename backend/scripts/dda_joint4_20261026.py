#!/usr/bin/env python3
"""DDA 4단계 공동 선정 + 단일 독립 확인 (2026-10-26, 문서 55). 요청 codex-dda-joint4-selection-singleholdout-20261026.

라운드1(reselect58, 문서 54 '단일 문제 시드 순차 교체')의 후속 — 방식 전환. 대상 = 라운드1 잔여 역전 18 + 확인 통과 중 극단값 14.
레벨마다 E2/E1/H1/H2 단계별 후보 풀(같은 원본 맵·해당 단계 N±k)에서 각 3개를 **함께** 골라(12) 단계 순서 + 단계 내 편차를
맞춘다(같은 단계 내 순서 무관 — 정렬 안 함, 확정 c12 시드 재사용 우선). 조합 고정 후 미사용 봇 대역으로 확인 1회.

선정 자료 = 기존 측정 합산(screen 67M·refine 69M·r1 탐색 71M·r1 확인 73M — 같은 레벨·단계·randSeed·botLj, 봇 v2.4·θ 동일)
          + 부족 후보 탐색(75M). 73M 을 선정에 쓰므로 r1 확인은 더 이상 독립 확인 근거가 아님. 독립 확인 = 77M 만.
서버·GameBoost·게임 저장소·Unity·커밋 없음. 기존 스크립트·산출물 수정 없음. 봇 기준 — 실유저·런타임 PASS 아님.

명령 (cd backend && venv/bin/python scripts/dda_joint4_20261026.py <cmd>)
  prep | prereg | run explore <B> | select <B> | run confirm <B> | budget | report | status
"""
from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from itertools import combinations
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
import dda_reselect58_20261026 as r1  # noqa: E402  (build_one, existing_cands, scan_used_seeds, info, pm1_bind, ...)

m20, sr = r1.m20, r1.sr
DS = r1.DS
OUT = DS / "joint4_20261026"
R1 = r1.OUT
R1_SUMS_SHA = "47b6565a6519bce53482591e2cafbc8294993924bacd5da94601204aab6ae2fb"
ZONES, ZF, ZD, ZORD, THETAS = r1.ZONES, r1.ZF, r1.ZD, r1.ZORD, r1.THETAS
PRIORITY = [734, 174, 254, 633]
POOL = 7                 # 단계당 후보 풀 최소 크기 (c12 3 + 대안 ≥4)
MAX_DRAW = 12
NEED_N = 300             # 선정 자료 합산 n < 300 인 비 c12 후보만 탐색
DELTA = 0.03             # 인접 단계 최소 차(점추정)
RANGE_MAX = 0.30         # 단계 내 시드 W max−min 허용
EXT_LO, EXT_HI = 0.02, 0.98
PH = {"explore": {"games": 40, "base": 75_000_000}, "confirm": {"games": 100, "base": 77_000_000}}
MAP_SEED_LO, MAP_SEED_HI = 1_500_000_000, 1_599_999_999
MAP_SEED_KEY = "dda_joint4_20261026/v1"
CAP_TOTAL = 600_000
R1_USED = 210_240        # reselect58 탐색 14,640 + 확인 195,600
B1_CAP = 25_000
MAX_PROC = 2
SWAP_MIN_MB, SWAP_RESUME_MB, DISK_MIN_GB = 500, 900, 10
PREREG = OUT / "PREREG_joint4.json"
SRC = {"screen": (sr.OUT / "raw_screen.jsonl", 67_000_000), "refine": (sr.OUT / "raw_refine.jsonl", 69_000_000),
       "r1_explore": (R1 / "raw_explore.jsonl", 71_000_000), "r1_confirm": (R1 / "raw_confirm.jsonl", 73_000_000)}

sha, fsha, dump, save = r1.sha, r1.fsha, r1.dump, r1.save


def log(msg, name="run.log"):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    with (OUT / "logs" / name).open("a") as f:
        f.write(line + "\n")


def resource():
    lvl, free, disk, bad = r1.resource()
    return lvl, free, disk, bad


# ───────────────────────── 대상·자료 ─────────────────────────
def targets():
    rows = {int(r["level"]): r for r in csv.DictReader((R1 / "levels_reselect58.csv").open())}
    res = [L for L, r in rows.items() if r.get("confirmVerdict") == "잔여 역전"]
    ext = [L for L, r in rows.items() if r.get("confirmVerdict") == "확인 통과" and r["confirm_extreme"]]
    b1 = [L for L in PRIORITY if L in res]
    b2 = [L for L in res if L not in b1]
    return {1: b1, 2: b2, 3: ext}, rows


def prior_data(levels):
    """{(L, zone, randSeed): {src: [w, n]}} — 같은 레벨·단계·randSeed. 봇 v2.4·θ·games_task 경로 동일(각 스크립트 blob 검사)."""
    d = {}
    for src, (p, base) in SRC.items():
        for line in p.open():
            r = json.loads(line)
            if r["level"] not in levels:
                continue
            assert r["theta"] in THETAS and r["seedBase"] == base + THETAS.index(r["theta"]) * 10_000, (src, r["map"])
            k = (r["level"], r["zone"], int(r["randSeed"]))
            x = d.setdefault(k, {}).setdefault(src, [0, 0])
            x[0] += r["wins"]
            x[1] += r["n"]
    return d


def cmd_prep():
    import dda_seed_spec_v2_prepare_20261022 as prep
    r1.ac.LOGF[0] = OUT / "logs/assign.log"
    p = OUT / "plan.json"
    if p.exists():
        raise SystemExit("plan.json exists")
    assert fsha(R1 / "SHA256SUMS") == R1_SUMS_SHA, "reselect58 SHA256SUMS"
    for line in (R1 / "SHA256SUMS").read_text().splitlines():
        h, n = line.split("  ")
        assert fsha(R1 / n) == h, n
    c12, spec, _ = r1.check_inputs()
    batches, r1rows = targets()
    levels = [L for B in (1, 2, 3) for L in batches[B]]
    tg = json.loads((sr.OUT / "targets.json").read_bytes())
    r1plan = json.loads((R1 / "plan.json").read_bytes())
    lcsv = {int(r["level"]): r for r in csv.DictReader((r1.RUN / "config/levels.csv").open())}
    pd = prior_data(set(levels))
    used = r1.scan_used_seeds()
    rng = random.Random(MAP_SEED_KEY)
    r1sel = {}
    for B in (1, 2, 3, 4):
        r1sel.update(json.loads((R1 / f"select_B{B}.json").read_bytes())["levels"])
    out = {}
    for B in (1, 2, 3):
        for L in batches[B]:
            N = c12[L]["N"]
            t0obj = json.loads((r1.RUN / f"out/t0base/level_{L}.json").read_bytes())
            b = (r1.RUN / f"out/t0base/level_{L}.json").read_bytes()
            lr = lcsv[L]
            x1 = r1plan["levels"][str(L)]
            zones = x1["zones"]
            r1cfg = {z: list(x1["seeds"][z]) for z in zones}
            for rp in r1sel[str(L)]["replacements"]:
                r1cfg[rp["zone"]][rp["pos"] - 1] = str(rp["newSeed"])
            seen = set()
            pool = {}
            for z in zones:
                utc = N + ZD[z]
                cs = []
                for i in (1, 2, 3):                      # c12 확정 3 (위치 순)
                    m = tg["levels"][str(L)]["seeds"][f"{z}:{i}"]
                    cs.append({"randSeed": m["randSeed"], "src": f"c12 pos{i}", "c12pos": i, "condSha256":
                               c12[L]["condSha256"][ZF[z]][i - 1], "resolvedMapSha256": m["resolvedMapSha256"],
                               "botLjSha16": m["botLjSha16"]})
                for c in r1.existing_cands(L, ZF[z]):     # spec_v2 미선정 PASS
                    if c["selected"] or c["status"] != "PASS":
                        continue
                    cs.append({"randSeed": c["randSeed"], "src": f"spec_v2 cand{c['cand']}", "c12pos": None,
                               "condSha256": c.get("condSha256") or r1.variants_cond(L, ZF[z], c["randSeed"]),
                               "resolvedMapSha256": c["resolvedMapSha256"], "botLjSha16": None})
                for ps in x1["problemSeeds"]:            # r1 후보(신규 추출분)
                    if ps["zone"] != z:
                        continue
                    for c in ps["candidates"]:
                        if any(c["randSeed"] == y["randSeed"] for y in cs):
                            continue
                        cs.append({"randSeed": c["randSeed"], "src": f"r1 {c['key']}", "c12pos": None,
                                   "condSha256": c["condSha256"], "resolvedMapSha256": c["resolvedMapSha256"],
                                   "botLjSha16": c["botLjSha16"]})
                for c in cs:
                    seen.add(c["resolvedMapSha256"])
                draws, fails = 0, []
                while len(cs) < POOL and draws < MAX_DRAW:
                    while True:
                        s = rng.randint(MAP_SEED_LO, MAP_SEED_HI)
                        if s not in used:
                            used.add(s)
                            break
                    draws += 1
                    eff = dict(t0obj["row"])
                    eff["useTileCount"] = str(utc)
                    eff["randSeed"] = str(s)
                    v = {"level": L, "dir": {"E2": "easy2", "E1": "easy", "H1": "hard", "H2": "hard2"}[z],
                         "cand": 200 + draws, "useTileCount": utc, "randSeed": s, "sourceCommit": lr["sourceCommit"],
                         "t0baseFileSha256": lr["t0baseFileSha256"], "t0baseMapSha256": lr["t0baseMapSha256"],
                         "requiredOrigMapSha256": lr["origMapSha256"],
                         "condSha256": sha(dump({"sourceCommit": lr["sourceCommit"],
                                                 "t0baseMapSha256": lr["t0baseMapSha256"], "row": eff}))}
                    rec = prep.check_variant(b, t0obj, v, "joint4")
                    if rec["status"] != "PASS" or rec["resolvedMapSha256"] in seen:
                        fails.append({"randSeed": s, "why": rec.get("reason") or "resolved_map_duplicate"})
                        continue
                    seen.add(rec["resolvedMapSha256"])
                    cs.append({"randSeed": s, "src": f"joint4 신규 #{draws}", "c12pos": None,
                               "condSha256": v["condSha256"], "resolvedMapSha256": rec["resolvedMapSha256"],
                               "botLjSha16": None})
                for c in cs:                              # 맵 재생성·결속 검사(게임 0판)
                    lj, h, bl = r1.build_one(L, utc, c["randSeed"])
                    assert h == c["resolvedMapSha256"], (L, z, c)
                    assert c["botLjSha16"] in (None, bl), (L, z, c)
                    c["botLjSha16"] = bl
                    c["useTileCount"] = utc
                    c["prior"] = pd.get((L, z, c["randSeed"]), {})
                    c["priorN"] = sum(v[1] for v in c["prior"].values())
                    c["explore"] = c["c12pos"] is None and c["priorN"] < NEED_N
                    c["inR1"] = str(c["randSeed"]) in r1cfg[z]
                pool[z] = {"cands": cs, "drawFails": fails}
            hs = [c["resolvedMapSha256"] for z in zones for c in pool[z]["cands"]]
            assert len(hs) == len(set(hs)), L
            out[str(L)] = {"level": L, "batch": B, "N": N, "zones": zones, "group": "잔여 역전" if B < 3 else "통과·극단값",
                           "uploaded9": L in r1.UPLOADED9, "c12": {z: x1["seeds"][z] for z in zones},
                           "r1cfg": r1cfg, "pool": pool}
            log(f"prep L{L} B{B}: pool {[len(pool[z]['cands']) for z in zones]} explore "
                f"{sum(c['explore'] for z in zones for c in pool[z]['cands'])}", "prep.log")
    save(p, {"levels": out, "batches": {str(k): v for k, v in batches.items()},
             "inputs": {"reselect58Sums": R1_SUMS_SHA, "sources": {k: fsha(v[0]) for k, v in SRC.items()}}})
    log("prep done", "prep.log")


def plan_cost(plan):
    c = {}
    for x in plan["levels"].values():
        b = c.setdefault(x["batch"], {"levels": 0, "explore": 0, "confirm": 0})
        b["levels"] += 1
        b["explore"] += sum(cc["explore"] for z in x["zones"] for cc in x["pool"][z]["cands"]) * 3 * PH["explore"]["games"]
        b["confirm"] += len(x["zones"]) * 3 * 3 * PH["confirm"]["games"]
    return c


def cmd_prereg():
    if PREREG.exists():
        raise SystemExit("PREREG exists")
    plan = json.loads((OUT / "plan.json").read_bytes())
    cost = plan_cost(plan)
    tot = sum(b["explore"] + b["confirm"] for b in cost.values())
    bands = dict(m20.SEED_USED_BANDS, measure20=[m20.SEED_BASE], measure20_n0=[m20.N0_BOT_BASE],
                 confirm12=[65_000_000], screen=[67_000_000], refine=[69_000_000], r1_explore=[71_000_000],
                 r1_confirm=[73_000_000])
    for ph, c in PH.items():
        lo, hi = c["base"], c["base"] + 2 * 10_000 + c["games"] - 1
        for g, vs in bands.items():
            for v in vs:
                assert hi < v or lo > v + 1_000_000, (ph, g, v)
    batches, rows = targets()
    excluded = {str(L): r["outcome"] for L, r in rows.items()
                if L not in {x["level"] for x in plan["levels"].values()}}
    save(PREREG, {
        "written": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "request": "codex-dda-joint4-selection-singleholdout-20261026",
        "doc": "claudedocs/difficulty_personalization/55_dda_joint4_selection_20261026.md",
        "status": "새 탐색·확인 결과 보기 전 작성. 이전 라운드(r1 reselect58) 결과는 선정 자료로만 사용",
        "inputs": dict(plan["inputs"], planJson=fsha(OUT / "plan.json"), thisScriptSha256=fsha(Path(__file__)),
                       reselect58Script=fsha(BACKEND / "scripts/dda_reselect58_20261026.py")),
        "scope": {"batches": {str(k): v for k, v in batches.items()},
                  "batchMeaning": {"1": "우선 L734·174·254 + L633(단계 내 편차) — 파일럿", "2": "나머지 잔여 역전 14",
                                   "3": "r1 확인 통과 중 극단값 경고 14"},
                  "notIncluded": excluded,
                  "notIncludedRule": "r1 약한 잔여(불확실) 10 = 이번 라운드 제외(유의 역전 없음 — 처리 계획: 별도 승인 시 같은 방식 "
                                     "적용 가능). 교체 대상 없음(단계 겹침) 3·바닥권 5 = 보류 유지. 이전 통과 중 극단 없음 8 = 재측정 "
                                     "안 함. 자동 통과 처리 없음"},
        "selectionData": {
            "sources": {k: {"file": str(v[0].relative_to(BACKEND)), "botBand": v[1]} for k, v in SRC.items()},
            "match": "레벨·단계(zone)·randSeed 일치 행 합산. 맵 = 같은 run_once/bot_level_json (prep 에서 botLjSha16 재계산 "
                     "일치), 봇 v2.4 blob 06a5dc9b, θ 0.29/0.47/0.65, m20.games_task. 서로 다른 봇 대역 = 독립 표본",
            "independence": "r1 확인(73M)을 선정에 사용 → r1 확인 결과는 이후 독립 확인 근거 아님. 독립 확인 = 이번 77M 대역만",
            "explore": f"비 c12 후보 중 선정 자료 n<{NEED_N} 인 것만 θ3×{PH['explore']['games']}=120판 (봇 대역 "
                       f"{PH['explore']['base']}). 합산해서 사용"},
        "pool": f"단계별: c12 확정 3(위치 순) + spec_v2 미선정 PASS + r1 신규 후보(그 단계) + 부족분 신규 추출(같은 규칙: "
                f"t0base·원본 맵, useTileCount = N±k, check_variant PASS, 레벨 내 resolved 고유, 전역 randSeed 고유, 대역 "
                f"[{MAP_SEED_LO},{MAP_SEED_HI}] random.Random({MAP_SEED_KEY!r})) → 단계당 ≥{POOL}. 다른 단계 시드 이동·라벨 교환 "
                "없음",
        "selection": {
            "estimate": "후보 W = 선정 자료 합산 wins/n (3θ 합산)",
            "combo": "단계마다 풀에서 3개(순서 무관) — 레벨 12개. 단계 평균 M = 3 W 단순평균, 범위 R = max−min",
            "objective(사전식 최소)": [
                f"V = Σ 인접 쌍(E2-E1, E1-H1, H1-H2) max(0, {DELTA} − (M_쉬운 − M_어려운)); 두 단계 평균 모두 ≤{EXT_LO} 또는 "
                f"≥{EXT_HI} 이면 그 쌍 0(정보없음, 평가불가 표시)",
                f"S = Σ 단계 max(0, R − {RANGE_MAX})",
                "C = c12 확정 시드가 아닌 시드 수(불필요한 교체 최소화)",
                "D = Σ 단계 |M − M_c12| (원래 단계 평균에서 쏠림 억제 — 전 단계를 쉽게/어렵게 모는 선정 방지)",
                "동률: randSeed 오름차순 튜플"],
            "method": "체인 DP(인접 쌍 비용 + 단계 비용 가법, 사전식 튜플) — 전수와 같은 최적",
            "positions": "선정 3개의 문자열 순서: 유지되는 c12 시드는 원 위치, 빈 위치에 새 시드를 randSeed 순으로 채움(난이도 정렬 아님)",
            "retry": "레벨당 공동 선정 1회 · 확인 1회. 확인 미달 → 보류(재선정·반복 확인 없음)",
            "infeasible": "V>0 또는 S>0 인 최선 조합도 확인은 하되 '선정 단계 미충족' 표시"},
        "confirm": {
            "sample": f"선정 12시드 각 θ3×{PH['confirm']['games']}=300판(단계 900판) — 봇 대역 {PH['confirm']['base']}"
                      "+θidx·10000+g (미사용 대역)",
            "betweenStage": {"확인 통과": "정보있는 쌍 전부 Newcombe 95% 상한 ≥0 AND 인접 쌍 점추정 g ≥0",
                             "약한 잔여(불확실)": "유의 역전 없음, 점추정 g<0 쌍 있음",
                             "잔여 역전": "정보있는 쌍 상한<0 1개 이상",
                             "평가불가": "모든 단계 ≤0.02 또는 모든 단계 ≥0.98"},
            "withinStage": f"단계 내 시드 W(300판) 범위 ≥{RANGE_MAX} = '편차 큼'(단계별 표기), 쉬운 단계 ≤0.02/어려운 단계 ≥0.98 "
                           "= 가장자리. 단계 간 판정과 분리 보고",
            "floor": "바닥권(≤0.05) 수치만으로 실유저 체감·런타임 PASS 단정 안 함"},
        "budget": {"plan": {str(k): v for k, v in cost.items()}, "planTotal": tot, "cumulativeCap": CAP_TOTAL,
                   "usedBefore": R1_USED, "remaining": CAP_TOTAL - R1_USED, "batch1Cap": B1_CAP,
                   "rule": "배치1 실측 후 budget(실측 × 남은 레벨, 계획 최대) 이 잔여 이내일 때만 배치 2·3. 초과 예상 = 중지·보고"},
        "safety": {"procs": MAX_PROC, "resource": f"swap free <{SWAP_MIN_MB}MB·pressure 4·디스크 <{DISK_MIN_GB}GiB → 투입 멈춤, "
                                                  f"≥{SWAP_RESUME_MB}MB 회복 대기", "checkpoint": "레벨 단위 append, 중복 assert",
                   "progress": "≤30초 로그"},
        "label": "봇 기준(v2.4, θ≤0.65). 실유저·런타임 PASS 아님. 후보는 '검토 후 동기화, 자동 교체 금지'"})
    (OUT / "PREREG_joint4.sha256").write_text(f"{fsha(PREREG)}  PREREG_joint4.json\n")
    log(f"PREREG sha={fsha(PREREG)} cost={cost} total={tot}")


def check_prereg():
    pin = (OUT / "PREREG_joint4.sha256").read_text().split()[0]
    if fsha(PREREG) != pin:
        raise SystemExit("PREREG sha mismatch")
    pre = json.loads(PREREG.read_bytes())
    assert pre["inputs"]["planJson"] == fsha(OUT / "plan.json")
    return pre


# ───────────────────────── run ─────────────────────────
def raw_path(ph):
    return OUT / f"raw_{ph}.jsonl"


def read_raw(ph):
    done, rows = set(), []
    if raw_path(ph).exists():
        for line in raw_path(ph).open():
            r = json.loads(line)
            k = (r["level"], r["map"], r["theta"])
            assert k not in done, ("dup", ph, k)
            done.add(k)
            rows.append(r)
    return done, rows


def maps_for(ph, B, plan):
    out = {}
    for Ls, x in plan["levels"].items():
        if x["batch"] != B:
            continue
        if ph == "explore":
            ms = {f"{z}:{c['randSeed']}": {"randSeed": c["randSeed"], "useTileCount": c["useTileCount"],
                                           "botLjSha16": c["botLjSha16"], "zone": z, "role": "explore"}
                  for z in x["zones"] for c in x["pool"][z]["cands"] if c["explore"]}
        else:
            sel = json.loads((OUT / f"select_B{B}.json").read_bytes())["levels"][Ls]
            byseed = {(z, c["randSeed"]): c for z in x["zones"] for c in x["pool"][z]["cands"]}
            ms = {}
            for z in x["zones"]:
                for i, s in enumerate(sel["final"][z]):
                    c = byseed[(z, int(s))]
                    ms[f"{z}:{i + 1}"] = {"randSeed": c["randSeed"], "useTileCount": c["useTileCount"],
                                          "botLjSha16": c["botLjSha16"], "zone": z, "role": "confirm"}
        if ms:
            out[int(Ls)] = ms
    return out


def level_task(a):
    rows = []
    for k, s in a["maps"].items():
        lj, h, bl = r1.build_one(a["level"], s["useTileCount"], s["randSeed"])
        assert bl == s["botLjSha16"], (a["level"], k)
        for ti in s["todo"]:
            r = m20.games_task({"level": a["level"], "map": k, "theta": THETAS[ti], "lj": lj, "games": a["games"],
                                "seedBase": a["base"] + ti * 10_000})
            r.pop("pid", None)
            r.update({"phase": a["phase"], "randSeed": s["randSeed"], "zone": s["zone"], "role": s["role"]})
            rows.append(r)
    return {"level": a["level"], "rows": rows}


def all_games():
    return sum(r["n"] for ph in PH for r in read_raw(ph)[1])


def cmd_run(ph, B):
    check_prereg()
    lock = OUT / "run.lock"
    if lock.exists():
        pid = int(lock.read_text().split()[0])
        try:
            os.kill(pid, 0)
            raise SystemExit(f"lock held by {pid}")
        except ProcessLookupError:
            lock.unlink()
    ps = [p for p in subprocess.run(["pgrep", "-f", "dda_joint4_20261026.py run"], capture_output=True,
                                    text=True).stdout.split() if int(p) != os.getpid()]
    if ps:
        raise SystemExit(f"other run {ps}")
    lock.write_text(f"{os.getpid()} {time.strftime('%H:%M:%S')} {ph} B{B}\n")
    try:
        return _run(ph, B)
    finally:
        lock.unlink(missing_ok=True)


def _run(ph, B):
    blob = subprocess.run(["git", "hash-object", str(m20.BOT_FILE)], capture_output=True, text=True).stdout.strip()
    if blob != m20.BOT_BLOB:
        raise SystemExit("bot blob changed")
    if (OUT / "STOP").exists():
        raise SystemExit("STOP")
    plan = json.loads((OUT / "plan.json").read_bytes())
    if B >= 2:
        bj = OUT / "budget.json"
        if not bj.exists() or not json.loads(bj.read_bytes())["proceed"]:
            raise SystemExit("budget.json proceed=false")
    if ph == "confirm" and not (OUT / f"select_B{B}.json").exists():
        raise SystemExit("select first")
    mp = maps_for(ph, B, plan)
    games = PH[ph]["games"]
    done, _ = read_raw(ph)
    tasks = []
    for L in mp:
        ms = {k: dict(v, todo=[ti for ti in range(3) if (L, k, THETAS[ti]) not in done]) for k, v in mp[L].items()}
        ms = {k: v for k, v in ms.items() if v["todo"]}
        if ms:
            tasks.append({"level": L, "maps": ms, "games": games, "base": PH[ph]["base"], "phase": ph})
    todo = sum(len(v["todo"]) for a in tasks for v in a["maps"].values()) * games
    so_far = all_games()
    if R1_USED + so_far + todo > CAP_TOTAL or (B == 1 and so_far + todo > B1_CAP):
        raise SystemExit(f"budget {R1_USED}+{so_far}+{todo}")
    lvl, free, disk, bad = resource()
    log(f"[{ph} B{B}:start] levels {len(mp)} tasks {len(tasks)} games {todo} soFar {so_far} swapFree={free:.0f}MB "
        f"disk={disk:.0f}GiB prereg={fsha(PREREG)[:16]}")
    t0, last, g, cpu, pauses, paused = time.time(), 0.0, 0, 0.0, 0, None
    it = iter(tasks)
    nxt = next(it, None)
    stop = None
    with ProcessPoolExecutor(MAX_PROC) as ex, raw_path(ph).open("a") as fo:
        pend = set()
        while True:
            while not stop and nxt is not None and len(pend) < MAX_PROC * 2:
                lvl, free, disk, bad = resource()
                if (OUT / "STOP").exists():
                    stop = "STOP"
                    break
                if bad or (paused and free < SWAP_RESUME_MB):
                    if not paused:
                        paused, pauses = time.time(), pauses + 1
                        log(f"PAUSE #{pauses} swapFree={free:.0f}MB pressure={lvl} disk={disk:.0f}GiB")
                    elif time.time() - paused > 3 * 3600:
                        stop = "pause>3h"
                    break
                if paused:
                    log(f"RESUME after {time.time() - paused:.0f}s swapFree={free:.0f}MB")
                    paused = None
                pend.add(ex.submit(level_task, nxt))
                nxt = next(it, None)
            if not pend and (stop or nxt is None):
                break
            if pend:
                fin, pend = wait(pend, timeout=15, return_when=FIRST_COMPLETED)
            else:
                fin = set()
                time.sleep(15)
            for f in fin:
                r = f.result()
                fo.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r["rows"]))
                fo.flush()
                os.fsync(fo.fileno())
                g += sum(x["n"] for x in r["rows"])
                cpu += sum(x["sec"] for x in r["rows"])
            if time.time() - last >= 30:
                last = time.time()
                lvl, free, disk, bad = resource()
                log(f"[{ph} B{B}] games {g}/{todo} {time.time() - t0:.0f}s cpu {cpu:.0f}s inflight {len(pend)} "
                    f"{'PAUSED ' if paused else ''}swapFree={free:.0f}MB disk={disk:.0f}GiB")
    log(f"[{ph} B{B}:end] games {g} wall {time.time() - t0:.0f}s cpu {cpu:.0f}s pauses {pauses}"
        + (f" stopped {stop}" if stop else ""))
    return 3 if stop else 0


# ───────────────────────── select (체인 DP) ─────────────────────────
def pair_cost(Ma, Mb):
    if (Ma <= EXT_LO and Mb <= EXT_LO) or (Ma >= EXT_HI and Mb >= EXT_HI):
        return 0.0
    return max(0.0, DELTA - (Ma - Mb))


def joint_select(x, W):
    """W = {zone: {randSeed: W}}. 반환 (final {zone:[seeds]}, cost tuple, 내역)."""
    zones = x["zones"]
    c12 = {z: [int(s) for s in x["c12"][z]] for z in zones}
    m12 = {z: sum(W[z][s] for s in c12[z]) / 3 for z in zones}
    trip = {}
    for z in zones:
        trip[z] = []
        for t in combinations(sorted(W[z]), 3):
            ws = [W[z][s] for s in t]
            M = sum(ws) / 3
            trip[z].append({"t": t, "M": M, "S": max(0.0, max(ws) - min(ws) - RANGE_MAX),
                            "C": sum(s not in c12[z] for s in t), "D": abs(M - m12[z])})
    best = {i: (round(0.0, 12), round(c["S"], 12), c["C"], round(c["D"], 12), c["t"]) for i, c in
            enumerate(trip[zones[0]])}
    back = [{}]
    for zi in range(1, len(zones)):
        prev, cur = trip[zones[zi - 1]], trip[zones[zi]]
        nb, bk = {}, {}
        for j, c in enumerate(cur):
            bb = None
            for i, p in enumerate(prev):
                v = best[i]
                cand = (round(v[0] + pair_cost(p["M"], c["M"]), 12), round(v[1] + c["S"], 12), v[2] + c["C"],
                        round(v[3] + c["D"], 12), v[4] + c["t"])
                if bb is None or cand < bb[0]:
                    bb = (cand, i)
            nb[j], bk[j] = bb
        best, back = nb, back + [bk]
    j = min(best, key=lambda k: best[k])
    cost = best[j]
    sel = [None] * len(zones)
    for zi in range(len(zones) - 1, -1, -1):
        sel[zi] = trip[zones[zi]][j]
        if zi:
            j = back[zi][j]
    final = {}
    for zi, z in enumerate(zones):
        t = list(sel[zi]["t"])
        keep = [s if s in t else None for s in c12[z]]
        new = sorted(s for s in t if s not in c12[z])
        final[z] = [str(s if s is not None else new.pop(0)) for s in keep]
    return final, {"V": cost[0], "S": cost[1], "C": cost[2], "D": cost[3],
                   "M": {zones[i]: round(sel[i]["M"], 4) for i in range(len(zones))}, "M_c12": {z: round(m12[z], 4)
                                                                                                for z in zones}}


def cmd_select(B):
    check_prereg()
    p = OUT / f"select_B{B}.json"
    if p.exists():
        raise SystemExit("exists")
    plan = json.loads((OUT / "plan.json").read_bytes())
    _, er = read_raw("explore")
    out = {}
    for Ls, x in plan["levels"].items():
        if x["batch"] != B:
            continue
        L = int(Ls)
        W, data = {}, {}
        for z in x["zones"]:
            W[z] = {}
            for c in x["pool"][z]["cands"]:
                w = sum(v[0] for v in c["prior"].values())
                n = sum(v[1] for v in c["prior"].values())
                ex = [r for r in er if r["level"] == L and r["map"] == f"{z}:{c['randSeed']}"]
                if c["explore"]:
                    assert len(ex) == 3, (L, z, c["randSeed"])
                w += sum(r["wins"] for r in ex)
                n += sum(r["n"] for r in ex)
                assert n > 0, (L, z, c["randSeed"])
                W[z][c["randSeed"]] = w / n
                data[f"{z}:{c['randSeed']}"] = {"w": w, "n": n, "W": round(w / n, 4), "src": c["src"],
                                                "bySource": {**c["prior"], **({"explore75M": [sum(r["wins"] for r in ex),
                                                                                              sum(r["n"] for r in ex)]}
                                                                              if ex else {})}}
        final, info_ = joint_select(x, W)
        out[Ls] = {"final": final, "cost": info_, "data": data,
                   "selectionMet": info_["V"] == 0 and info_["S"] == 0}
        log(f"select L{L}: V {info_['V']:.3f} S {info_['S']:.3f} C {info_['C']} D {info_['D']:.3f} M {info_['M']} "
            f"(c12 {info_['M_c12']})")
    save(p, {"batch": B, "prereg": fsha(PREREG), "rawExplore": fsha(raw_path("explore")) if raw_path("explore").exists()
             else None, "levels": out})


# ───────────────────────── budget / report ─────────────────────────
def cmd_budget():
    check_prereg()
    plan = json.loads((OUT / "plan.json").read_bytes())
    _, er = read_raw("explore")
    _, cr = read_raw("confirm")
    b1 = {x["level"] for x in plan["levels"].values() if x["batch"] == 1}
    g1 = sum(r["n"] for r in er + cr if r["level"] in b1)
    cpu1 = sum(r["sec"] for r in er + cr if r["level"] in b1)
    cost = plan_cost(plan)
    rest = sum(b["explore"] + b["confirm"] for k, b in cost.items() if int(k) >= 2)
    proj = R1_USED + g1 + rest
    ok = proj <= CAP_TOTAL
    save(OUT / "budget.json", {"batch1Games": g1, "batch1Cpu": round(cpu1, 1), "restPlanned": rest, "r1Used": R1_USED,
                               "projectedCumulative": proj, "cap": CAP_TOTAL, "proceed": ok})
    log(f"budget: B1 {g1} games cpu {cpu1:.0f}s, rest {rest}, cumulative projected {proj}/{CAP_TOTAL} proceed {ok}")


def zstats(rows, zones, keymap):
    a = r1.seed_wn(rows)
    st = {}
    for z in zones:
        ks = keymap[z]
        w = sum(a[k][0] for k in ks)
        n = sum(a[k][1] for k in ks)
        sw = [a[k][0] / a[k][1] for k in ks]
        st[z] = {"w": w, "n": n, "W": w / n, "seedW": sw, "range": max(sw) - min(sw)}
    pairs = []
    for A, Bz in r1.pair_list(zones):
        lo, hi = m20.newcombe(st[A]["w"], st[A]["n"], st[Bz]["w"], st[Bz]["n"])
        pairs.append({"pair": f"{A}-{Bz}", "adj": zones.index(Bz) == zones.index(A) + 1, "g": st[A]["W"] - st[Bz]["W"],
                      "lo": lo, "hi": hi, "info": r1.info(st[A]["W"], st[Bz]["W"])})
    return st, pairs


def verdict(st, pairs):
    if all(s["W"] <= EXT_LO for s in st.values()) or all(s["W"] >= EXT_HI for s in st.values()):
        return "평가불가"
    ip = [p for p in pairs if p["info"]]
    if any(p["hi"] < 0 for p in ip):
        return "잔여 역전"
    if any(p["g"] < 0 for p in ip):
        return "약한 잔여(불확실)"
    return "확인 통과"


def fp(pairs):
    return "; ".join(f"{p['pair']} {p['g']:+.3f}[{p['lo']:+.3f},{p['hi']:+.3f}]" + ("" if p["info"] else " 정보없음")
                     for p in pairs)


def cmd_report():
    pre = check_prereg()
    plan = json.loads((OUT / "plan.json").read_bytes())
    c12, _, _ = sr.load_inputs()
    _, er = read_raw("explore")
    _, cr = read_raw("confirm")
    sels = {}
    for B in (1, 2, 3):
        p = OUT / f"select_B{B}.json"
        if p.exists():
            sels.update(json.loads(p.read_bytes())["levels"])
    r1rows = {int(r["level"]): r for r in csv.DictReader((R1 / "levels_reselect58.csv").open())}
    inf = {int(r["sourceLevel"]): r for r in csv.DictReader((sr.OUT / "infinity_reuse_map.csv").open())}
    allseeds = Counter(int(s) for r in c12.values() for f in r["fields"].values() if f for s in f.split(","))
    lv, seeds, changes, cand = [], [], [], []
    verify = {"nk": True, "levelUnique": True, "globalUnique": True, "condHashUnchanged": True, "issues": []}
    for Ls, x in sorted(plan["levels"].items(), key=lambda kv: (kv[1]["batch"], kv[0])):
        L = int(Ls)
        rr = r1rows[L]
        row = {"level": L, "batch": x["batch"], "group": x["group"], "uploaded9": x["uploaded9"],
               **{f"c12refine_W_{z}": rr.get(f"refine_W_{z}") for z in x["zones"]},
               **{f"r1confirm_W_{z}": rr.get(f"confirm_W_{z}") for z in x["zones"]},
               "r1confirm_seeds": " ".join(f"{z}:{rr.get('confirm_seeds_' + z)}" for z in x["zones"]),
               "r1Verdict": rr.get("confirmVerdict"), "r1Extreme": rr.get("confirm_extreme"),
               "infinity": (f"infinity_{L - 500} — 원본 결과 재사용 표기" if L in inf else "")}
        s = sels.get(Ls)
        if not s:
            row["outcome"] = "미실시(배치 미진행)"
            lv.append(row)
            continue
        row.update({"selV": s["cost"]["V"], "selS": s["cost"]["S"], "selChangesVsC12": s["cost"]["C"],
                    "selD": s["cost"]["D"], "selectionMet": s["selectionMet"],
                    **{f"sel_M_{z}": s["cost"]["M"][z] for z in x["zones"]},
                    "final": " ".join(f"{z}:{','.join(s['final'][z])}" for z in x["zones"])})
        for k, d in s["data"].items():
            z, sd = k.split(":")
            seeds.append({"level": L, "phase": "selection(합산)", "zone": z, "randSeed": int(sd), "src": d["src"],
                          "w": d["w"], "n": d["n"], "W": d["W"], "bySource": json.dumps(d["bySource"]),
                          "chosen": sd in s["final"][z], "inC12": sd in x["c12"][z], "inR1": sd in x["r1cfg"][z]})
        mrows = [r for r in cr if r["level"] == L]
        need = len(x["zones"]) * 9
        if len(mrows) != need:
            row["outcome"] = f"확인 미완료({len(mrows)}/{need})"
            lv.append(row)
            continue
        km = {z: [f"{z}:{i}" for i in (1, 2, 3)] for z in x["zones"]}
        st, pairs = zstats(mrows, x["zones"], km)
        v = verdict(st, pairs)
        spread = [z for z in x["zones"] if st[z]["range"] >= RANGE_MAX]
        edge = [z for z in x["zones"] if (z in ("E2", "E1") and st[z]["W"] <= EXT_LO) or
                (z in ("H1", "H2") and st[z]["W"] >= EXT_HI)]
        row.update({"outcome": "확인: " + v, "betweenStage": v,
                    "sigPairs": ",".join(p["pair"] for p in pairs if p["info"] and p["hi"] < 0),
                    "negPairs": ",".join(p["pair"] for p in pairs if p["info"] and p["g"] < 0),
                    "withinStage_spread": ",".join(spread) or "없음", "withinStage_edge": ",".join(edge) or "없음",
                    **{f"confirm_W_{z}": round(st[z]["W"], 4) for z in x["zones"]},
                    **{f"confirm_ci_{z}": "{:.3f}-{:.3f}".format(*m20.wilson(st[z]["w"], st[z]["n"])) for z in x["zones"]},
                    **{f"confirm_seeds_{z}": "|".join(f"{w:.3f}" for w in st[z]["seedW"]) for z in x["zones"]},
                    **{f"confirm_range_{z}": round(st[z]["range"], 3) for z in x["zones"]},
                    "confirm_pairs": fp(pairs)})
        a = r1.seed_wn(mrows)
        for z in x["zones"]:
            for i in (1, 2, 3):
                k = f"{z}:{i}"
                seeds.append({"level": L, "phase": "confirm77M", "zone": z, "pos": i, "randSeed": int(s["final"][z][i - 1]),
                              "w": a[k][0], "n": a[k][1], "W": round(a[k][0] / a[k][1], 4)})
        cl = json.loads(json.dumps(c12[L]))
        byseed = {(z, c["randSeed"]): c for z in x["zones"] for c in x["pool"][z]["cands"]}
        for z in x["zones"]:
            f_ = ZF[z]
            cl["fields"][f_] = ",".join(s["final"][z])
            for i in range(3):
                old, new = x["c12"][z][i], s["final"][z][i]
                c = byseed[(z, int(new))]
                cl["condSha256"][f_][i] = c["condSha256"]
                if c["useTileCount"] != x["N"] + ZD[z]:
                    verify["nk"] = False
                    verify["issues"].append(f"L{L} {z} N±k")
                if old != new:
                    if allseeds[int(new)]:
                        verify["globalUnique"] = False
                        verify["issues"].append(f"L{L} {z} global dup {new}")
                    allseeds[int(new)] += 1
            if x["c12"][z] != s["final"][z]:
                s5 = ""
                if f_ in ("ddaEasySeeds", "ddaHardSeeds"):
                    r5 = json.loads((r1.OUT / "plan.json").read_bytes())["levels"][Ls].get("pm1Server5", {}).get(f_)
                    s5 = r5["value"] if r5 else next(e for e in json.loads(r1.CATALOG_V1.read_bytes())["levels"]
                                                     if e["level"] == L)[f_]
                ob, nb = r1.pm1_bind(f_, ",".join(x["c12"][z]), ",".join(s["final"][z]), s5) if s5 else ("", "")
                changes.append({"level": L, "field": f_, "zone": z, "N": x["N"], "useTileCount": x["N"] + ZD[z],
                                "c12": ",".join(x["c12"][z]), "r1": ",".join(x["r1cfg"][z]),
                                "joint4": ",".join(s["final"][z]),
                                "replacedVsC12": sum(a_ != b_ for a_, b_ in zip(x["c12"][z], s["final"][z])),
                                "sameAsR1": x["r1cfg"][z] == s["final"][z],
                                "newSeedSources": "; ".join(f"{n_}={byseed[(z, int(n_))]['src']}" for n_ in s["final"][z]
                                                            if n_ not in x["c12"][z]),
                                "pm1Server5": s5, "pm1Bind_c12": ob, "pm1Bind_joint4": nb,
                                "pm1Note": "" if not nb else ("서버 값 미변경. " + ("접두 유지" if nb == "keep" else
                                                                             "접두 불일치 → planned_change 대상(" +
                                                                             nb.split("/")[-1] + ")")),
                                "uploaded9": x["uploaded9"], "betweenStage": v, "withinStageSpread": z in spread,
                                "infinity": row["infinity"]})
        lvs = [int(t) for f_ in cl["fields"].values() if f_ for t in f_.split(",")] + [c12[L]["originalRandSeed"]]
        if len(lvs) != len(set(lvs)):
            verify["levelUnique"] = False
            verify["issues"].append(f"L{L} level dup")
        t0obj = json.loads((r1.RUN / f"out/t0base/level_{L}.json").read_bytes())
        if sha(dump({k: v_ for k, v_ in t0obj["row"].items() if k not in ("map", "ddaEasySeeds", "ddaHardSeeds")})) \
                != cl["sourceConditionHash"]:
            verify["condHashUnchanged"] = False
        cl["joint4"] = {"betweenStage": v, "withinStageSpread": spread, "edge": edge, "selectionMet": s["selectionMet"],
                        "status": "검토 후 동기화 후보 — 자동 교체 금지"}
        cand.append(cl)
        lv.append(row)

    def wcsv(name, rows):
        if not rows:
            return
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        with (OUT / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    wcsv("levels_joint4.csv", lv)
    wcsv("seeds_joint4.csv", seeds)
    wcsv("changes_joint4.csv", changes)
    (OUT / "levels_joint4_candidates.json").write_bytes(json.dumps(cand, ensure_ascii=False, indent=0).encode())
    summ = {"outcome": dict(Counter(r["outcome"] for r in lv)),
            "spreadZones": sum(len(r.get("withinStage_spread", "").split(",")) for r in lv
                               if r.get("withinStage_spread") not in (None, "", "없음")),
            "changedFields": len(changes), "replacedSeedsVsC12": sum(c["replacedVsC12"] for c in changes),
            "games": {"explore": sum(r["n"] for r in er), "confirm": sum(r["n"] for r in cr)},
            "cpuSec": round(sum(r["sec"] for r in er + cr), 1),
            "cumulative": R1_USED + sum(r["n"] for r in er + cr), "cap": CAP_TOTAL, "verify": verify}
    save(OUT / "summary.json", summ)
    save(OUT / "manifest.json", {
        "id": "dda_joint4_20261026", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "검토 후 동기화, 자동 교체 금지 — 로컬 후보. 서버·GameBoost·카탈로그 미변경, 업로드 없음, 운영·무한 DDA OFF",
        "method": "4단계 공동 선정(라운드1 reselect58 = 단일 문제 시드 순차 교체와 구분) + 미사용 77M 대역 확인 1회",
        "history": "changes_joint4.csv: c12(확정) → r1(reselect58) → joint4 열로 연결",
        "independence": "r1 확인(73M)은 선정 자료로 사용 — 독립 확인 근거 아님. 독립 확인 = 77M",
        "preregSha256": fsha(PREREG), "planSha256": fsha(OUT / "plan.json"), "inputs": pre["inputs"], "summary": summ,
        "label": "봇 기준(v2.4, θ≤0.65). 실유저·런타임 PASS 아님. 바닥권 수치로 체감 단정 금지"})
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name not in ("SHA256SUMS", "run.lock", "STOP"))
    (OUT / "SHA256SUMS").write_text("".join(f"{fsha(p)}  {p.name}\n" for p in files))
    log("report " + json.dumps(summ, ensure_ascii=False)[:2000])


def cmd_status():
    for ph in PH:
        d, rows = read_raw(ph)
        print(ph, len(d), sum(r["n"] for r in rows))
    print("lock", (OUT / "run.lock").read_text() if (OUT / "run.lock").exists() else None, resource())


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
