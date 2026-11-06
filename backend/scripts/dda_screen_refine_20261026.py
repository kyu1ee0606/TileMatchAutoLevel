#!/usr/bin/env python3
"""DDA 시드 전 범위 — 소량 선별 측정 → 대상 한정 정밀 측정 (2026-10-26, 문서 53).

요청 codex-dda-screen-then-refine-20261026. 승인 범위 = 로컬 선별 측정 + 대상 한정 정밀 측정.
서버·GameBoost·게임 저장소·Unity 접근 없음. 기존 스크립트·산출물 수정 없음. 시드 교체 산출물 만들지 않음.
결과는 봇 기준(v2.4 규칙 정합, θ≤0.65) — 실유저 클리어율·런타임 PASS 아님.

시드 = spec_v2_2_confirm12 확정 후보(levels_spec_v2_2_confirm12.json) 4필드 각 3개, 문자열 순서 그대로(정렬·재선정 없음).
측정 경로 = 문서 49 드라이버(dda_spec_v2_measure20_20261022.py) 재사용:
  맵 = 같은 배정 경로(ac.run_once → resolvedMapSha256 를 pm1/pm2 원장과 대조 → pv.t0ize.bot_level_json).
       build_maps 는 21맵 전부 + 4필드 필수라 선정 3시드만 같은 호출로 만든다(build_sel). prep 에서 build_maps
       결과와 botLjSha16 일치 검사(가능한 레벨 전부).
  판 = m20.games_task 그대로 (set_rule_parity → _create_initial_state → _precompute_blocking_map → seed → _play_game).

명령 (cd backend && venv/bin/python scripts/dda_screen_refine_20261026.py <cmd>)
  prep           : 대상 목록 + 맵 생성·결속 검사(게임 0판) → targets.json (있으면 거부)
  prereg         : PREREG_screen.json 작성(있으면 거부). 결과 보기 전
  run screen     : 선별 측정 (재개 가능 — 기록된 (level,map,θ) 건너뜀)
  report screen  : 선별 판정 + 정밀 대상 선정(refine_targets.json, 규칙 고정)
  run refine     : 정밀 측정 (refine_targets.json 대상만)
  report final   : 최종 분류 + 무한 매핑 + SHA256SUMS
  status         : 진행 현황(읽기 전용)
안전 중지: OUT/STOP 파일 생성 → 새 작업 투입 중지, 진행 중 작업만 마치고 종료(체크포인트 유지).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
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
import dda_spec_v2_measure20_20261022 as m20  # noqa: E402  (build_maps, games_task, cand_table, newcombe, wilson)

ac = m20.ac
RUN = m20.RUN
DS = BACKEND / "data/dda_seeds"
OUT = DS / "screen_refine_20261026"
PLAN = DS / "fullrange_plan_20261023/analysis"
C12 = DS / "spec_v2_2_confirm12_20261022"
SPEC = m20.SPEC

C12_MANIFEST_SHA = "88a7415b7844fa8cc34ff49e49832d36511e0ccf6b4d01a0a516dfdd2264b76d"
C12_LEVELS_SHA = "950ec2bd1358050776707f757f040303be81f24855c6f934e511e64781610508"
C12_RESLV_SHA = "f434196ec4cd637924f5fd2e23de43f61c7e5091805e07f1ea827c3b3909b60f"
ZONES = [("ddaEasy2Seeds", "E2", -2), ("ddaEasySeeds", "E1", -1), ("ddaHardSeeds", "H1", 1),
         ("ddaHard2Seeds", "H2", 2)]
THETAS = m20.THETAS
PHASES = {"screen": {"games": 10, "base": 67_000_000}, "refine": {"games": 100, "base": 69_000_000}}
MAX_PROC = 2
SWAP_MIN_MB = 500
DISK_MIN_GB = 10
SCREEN_CAP = 450_000
REFINE_CAP = 300_000
TOTAL_CAP = 800_000
BIG = -0.10            # 큰 역전: 단계 평균 차 g = W_쉬운 − W_어려운 ≤ −0.10
EXT_LO, EXT_HI = 0.02, 0.98
RANGE_SCREEN = 0.50    # 단계 내 시드 W(30판) max−min
RANGE_REFINE = 0.30    # 단계 내 시드 W(300판) max−min
PREREG = OUT / "PREREG_screen.json"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fsha(p):
    return sha(Path(p).read_bytes())


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


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


# ───────────────────────── targets / maps ─────────────────────────
def load_inputs():
    assert fsha(C12 / "manifest.json") == C12_MANIFEST_SHA, "confirm12 manifest sha"
    assert fsha(C12 / "levels_spec_v2_2_confirm12.json") == C12_LEVELS_SHA, "confirm12 levels sha"
    assert fsha(C12 / "results_levels.csv") == C12_RESLV_SHA, "confirm12 results sha"
    assert fsha(SPEC / "manifest.json") == m20.SPEC_MANIFEST_SHA, "spec_v2 manifest sha"
    c12 = {r["level"]: r for r in json.loads((C12 / "levels_spec_v2_2_confirm12.json").read_bytes())}
    spec = {r["level"]: r for r in json.loads((SPEC / "levels_spec_v2.json").read_bytes())}
    cls = {int(r["level"]): r for r in csv.DictReader((PLAN / "classification_L32_L1530.csv").open())}
    return c12, spec, cls


def group_of(r):
    pc, ms = r["planClass"], r["measure"]
    if pc == "준비완료(데이터)·난이도검증필요":
        return "screen", ("검증필요:평가불가(spec_v2)" if ms.startswith("unevaluable") else "검증필요:미측정")
    if pc.startswith("업로드완료"):
        if ms.startswith("bot_confirm_pass"):
            return "reuse", "업로드완료:confirm12 확인PASS 재사용"
        return "screen", "업로드완료:미측정(사후 선별)"
    if pc == "준비완료(데이터)":
        return "reuse", "confirm12 확인PASS 재사용"
    if pc == "보류":
        return "hold", f"보류:{r['prepReason_reorder5']}|{ms}"
    if pc == "승인필요":
        return "hold", f"승인필요:{r['prepReason_reorder5']}"
    if pc == "정책상제외":
        return "excluded", f"정책상제외:{r['prepReason_reorder5']}|{r['catalogReasons']}"
    raise ValueError(pc)


_CACHE = {}


def _ct():
    if "ct" not in _CACHE:
        _CACHE["ct"] = m20.cand_table()
    return _CACHE["ct"]


def build_sel(L, spec_row, c12_row):
    """확정 시드(4필드 × 3, 문자열 순서)만 build_maps 와 같은 호출로 생성. {key: lj}, {key: meta}."""
    from app.core.pv.t0ize import bot_level_json
    ct = _ct()
    orig = json.loads((RUN / f"out/orig/b741f6a3/level_{L}.json").read_bytes())
    t0obj = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())
    assert sha(dump(orig["map"])) == t0obj["origMapSha256"] == spec_row["sourceMapSha256"], f"L{L} orig sha"
    maps, meta = {}, {}
    for field, zn, dl in ZONES:
        s = c12_row["fields"][field]
        if not s:
            continue
        assert s == spec_row["fields"][field], f"L{L} {field} confirm12 != spec_v2"
        byseed = {c["randSeed"]: c for c in ct[L][field]}
        for i, sd in enumerate(int(x) for x in s.split(",")):
            c = byseed[sd]
            assert c["selected"], (L, field, sd)
            assert c["useTileCount"] == c12_row["N"] + dl == c12_row["useTileCount"][field], (L, field, sd)
            r = dict(t0obj["row"])
            r["useTileCount"] = str(c["useTileCount"])
            r["randSeed"] = str(sd)
            r["map"] = t0obj["map"]
            _, resolved = ac.run_once(r)
            h = sha(dump(resolved))
            assert h == c["resolvedMapSha256"], f"L{L} {field} {sd} resolved sha mismatch"
            k = f"{zn}:{i + 1}"
            lj = bot_level_json(r, resolved)
            maps[k] = lj
            meta[k] = {"field": field, "zone": zn, "pos": i + 1, "randSeed": sd, "cand": c["cand"],
                       "useTileCount": c["useTileCount"], "resolvedMapSha256": h,
                       "botLjSha16": sha(json.dumps(lj, sort_keys=True, ensure_ascii=False).encode())[:16]}
    hs = [m["resolvedMapSha256"] for m in meta.values()]
    assert len(set(hs)) == len(hs), f"L{L} duplicate maps"
    return maps, meta


def prep_task(a):
    L = a["level"]
    t = time.time()
    try:
        _, meta = build_sel(L, a["spec"], a["c12"])
    except Exception as e:  # noqa: BLE001
        return {"level": L, "ok": False, "error": repr(e)[:300]}
    cross = "n/a"
    try:
        _, mm = m20.build_maps(L, _ct(), a["spec"])
        bys = {v["randSeed"]: v["botLjSha16"] for k, v in mm.items() if k != "orig"}
        cross = all(bys.get(m["randSeed"]) == m["botLjSha16"] for m in meta.values())
    except Exception as e:  # noqa: BLE001  (L358·L541 hard2 빈 값 등 — build_maps 미지원)
        cross = "build_maps_unsupported:" + type(e).__name__
    return {"level": L, "ok": True, "meta": meta, "crossBuildMaps": cross, "sec": round(time.time() - t, 2)}


def cmd_prep():
    p = OUT / "targets.json"
    if p.exists():
        raise SystemExit("targets.json exists — not overwriting")
    c12, spec, cls = load_inputs()
    groups, todo = {}, []
    for L in sorted(cls):
        g, why = group_of(cls[L])
        groups[L] = {"group": g, "why": why, "planClass": cls[L]["planClass"], "measure": cls[L]["measure"]}
        if g == "screen":
            todo.append({"level": L, "spec": spec[L], "c12": c12[L]})
    log(f"prep: {len(cls)} rows, groups {dict(Counter(v['group'] for v in groups.values()))}, build {len(todo)}",
        "prep.log")
    res, t0, last = {}, time.time(), 0
    with ProcessPoolExecutor(MAX_PROC) as ex:
        futs = [ex.submit(prep_task, a) for a in todo]
        pend = set(futs)
        while pend:
            fin, pend = wait(pend, timeout=20, return_when=FIRST_COMPLETED)
            for f in fin:
                r = f.result()
                res[r["level"]] = r
            if time.time() - last >= 30:
                last = time.time()
                log(f"prep progress {len(res)}/{len(todo)} {time.time() - t0:.0f}s", "prep.log")
    fails = {L: r["error"] for L, r in res.items() if not r["ok"]}
    cross = Counter(str(r.get("crossBuildMaps")) for r in res.values() if r["ok"])
    assert cross.get("False", 0) == 0, "build_sel != build_maps botLj"
    out = {"levels": {}, "groups": {str(L): v for L, v in groups.items()}, "mapFail": {str(k): v for k, v in fails.items()},
           "crossBuildMaps": dict(cross)}
    for L, r in sorted(res.items()):
        if r["ok"]:
            out["levels"][str(L)] = {"N": c12[L]["N"], "why": groups[L]["why"], "seeds": r["meta"],
                                     "crossBuildMaps": r["crossBuildMaps"]}
    save(p, out)
    log(f"prep done: ok {len(out['levels'])}, mapFail {len(fails)} {fails}, cross {dict(cross)}, "
        f"seeds {sum(len(v['seeds']) for v in out['levels'].values())}, {time.time() - t0:.0f}s", "prep.log")


# ───────────────────────── prereg ─────────────────────────
def screen_budget(tg):
    return sum(len(v["seeds"]) for v in tg["levels"].values()) * len(THETAS) * PHASES["screen"]["games"]


def cmd_prereg():
    if PREREG.exists():
        raise SystemExit("PREREG exists — not overwriting")
    tg = json.loads((OUT / "targets.json").read_bytes())
    nseeds = sum(len(v["seeds"]) for v in tg["levels"].values())
    sg = screen_budget(tg)
    assert sg <= SCREEN_CAP and sg + REFINE_CAP <= TOTAL_CAP, (sg, REFINE_CAP)
    bands = dict(m20.SEED_USED_BANDS, measure20=[m20.SEED_BASE], measure20_n0=[m20.N0_BOT_BASE], confirm12=[65_000_000])
    for ph, c in PHASES.items():
        lo, hi = c["base"], c["base"] + (len(THETAS) - 1) * 10_000 + c["games"] - 1
        for g, vs in bands.items():
            for v in vs:
                assert hi < v or lo > v + 1_000_000, (ph, g, v)
    sc = PHASES["screen"]["base"], PHASES["refine"]["base"]
    assert abs(sc[0] - sc[1]) >= 1_000_000
    cnt = Counter(v["group"] for v in tg["groups"].values())
    why = Counter(v["why"] for v in tg["levels"].values())
    save(PREREG, {
        "written": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "request": "codex-dda-screen-then-refine-20261026",
        "doc": "claudedocs/difficulty_personalization/53_dda_screen_then_refine_20261026.md",
        "status": "결과 보기 전 작성. 확정 시드 값 고정 — 같은 단계 3시드 정렬·재선정 없음, 시드 교체 산출물 없음",
        "inputs": {"confirm12Manifest": C12_MANIFEST_SHA, "confirm12Levels": C12_LEVELS_SHA,
                   "confirm12ResultsLevels": C12_RESLV_SHA, "specV2Manifest": m20.SPEC_MANIFEST_SHA,
                   "classification": fsha(PLAN / "classification_L32_L1530.csv"),
                   "infinityCopyPlan": fsha(PLAN / "infinity_copy_plan.csv"),
                   "targetsJson": fsha(OUT / "targets.json"),
                   "driverReused": {"path": "scripts/dda_spec_v2_measure20_20261022.py",
                                    "sha256": fsha(BACKEND / "scripts/dda_spec_v2_measure20_20261022.py"),
                                    "functions": "games_task, cand_table, newcombe, wilson, ac.run_once; build_maps 는 "
                                                 "prep 교차검사(botLjSha16 일치)"},
                   "thisScriptSha256": fsha(Path(__file__))},
        "scope": {
            "official": "정식 L32~L1530 1499행 (fullrange_plan 분류 그대로)",
            "groupCounts": dict(cnt),
            "screenTargets": len(tg["levels"]), "screenSeeds": nseeds, "screenWhy": dict(why),
            "mapFail": tg["mapFail"],
            "screen": "검증필요 1142(미측정 1136 + 평가불가 6) + 업로드완료 59 중 미측정 57(서버 값 = 후보, 사후 선별 — 업로드 "
                      "결정 바꾸지 않음, 결과 별도 집계)",
            "reuse": "confirm12 확인PASS 9 = 준비완료 7(L225·234·325·472·521·851·1195) + 업로드완료 2(L65·L95) — 같은 시드 "
                     "900판/구간 기존 결과 재사용, 재측정 안 함",
            "notMeasured": "보류 7(L86·278·293·407·442·1466·1523) · 승인필요 1(L158) · 정책상제외 283 — 기존 사유 그대로 기록",
            "threeField": "L358·L541 = ddaHard2Seeds 비움(3단계 E2/E1/H1만 비교)",
            "infinity": "infinity_N → level_{500+N} 결과 재사용(측정 안 함). 복사 가능 853 = 원본 분류 그대로 상속, 보류 177 = "
                        "원본 사유. 복사 정합성·런타임 QA 는 별개(미실시)",
        },
        "bot": {"version": m20.BOT_VER, "items": "V24_DEFAULT (규칙 6건)", "blob": m20.BOT_BLOB,
                "call": "set_rule_parity → _create_initial_state → _precompute_blocking_map → seed(base+θidx*10000+g) → "
                        "_play_game (m20.games_task)"},
        "thetas": THETAS,
        "screen": {"gamesPerSeedPerTheta": PHASES["screen"]["games"], "perSeed": 30, "perStage": 90,
                   "perLevel": "360 (3단계 레벨 270)", "totalGames": sg,
                   "botSeedBand": [PHASES["screen"]["base"], PHASES["screen"]["base"] + 20_009],
                   "why": "단계 평균(90판)으로 큰 역전(Δ≤−0.10)·극단만 거른다. 90 vs 90 에서 p≈0.5 Newcombe 반폭 ≈ ±0.14 — "
                          "작은 차이 확정은 목표 아님(사용자 지시). 30판/θ 이상은 예산(≤45만) 초과"},
        "refine": {"gamesPerSeedPerTheta": PHASES["refine"]["games"], "perSeed": 300, "perStage": 900,
                   "perLevel": "3600 (3단계 2700) — confirm12 와 같은 수준", "capGames": REFINE_CAP,
                   "botSeedBand": [PHASES["refine"]["base"], PHASES["refine"]["base"] + 20_099],
                   "independence": "정밀은 새 봇 시드 대역 — 판정은 정밀 자료만 사용(선별 자료와 합산 안 함, 선택 편향·평균회귀 방지)"},
        "botSeedOverlapCheck": {"bands": bands, "rule": "각 대역 [v, v+1M] 과 비중첩"},
        "crn": "같은 (θ, g) 시드는 모든 맵·레벨 공통. 비교는 독립 근사(Newcombe) — CRN 무시 = 보수적",
        "judge": {
            "stageW": "단계 W = 3시드 × 3θ 합산 클리어율 (선별 90판/정밀 900판). 시드 W = 3θ 합산(선별 30/정밀 300)",
            "pairs": "단계 쌍 전부(4단계 6쌍, 3단계 3쌍), g = W_쉬운 − W_어려운, Newcombe hybrid 95% (m20.newcombe, z 1.96). "
                     "정보없음 = 두 단계 모두 ≤0.02 또는 모두 ≥0.98 (판정 제외)",
            "screen": {
                "평가불가": "모든 단계 W ≤0.02 또는 모든 단계 W ≥0.98 (봇 θ 범위 밖) — 정밀 안 함",
                "R_big(큰 역전)": "정보있는 쌍 중 g ≤ −0.10",
                "R_sig(유의 역전)": "정보있는 쌍 중 Newcombe 상한 < 0",
                "X_range(시드 범위 큼)": "어느 단계든 시드 W(30판) max−min ≥ 0.50",
                "X_edge(방향 반대 극단)": "쉬운 단계(E2·E1) W ≤ 0.02 또는 어려운 단계(H1·H2) W ≥ 0.98",
                "정밀대상": "R_big·R_sig·X_range·X_edge 중 하나 이상",
                "불확실": "플래그 없음 AND 가장 쉬운 단계 vs 가장 어려운 단계 Newcombe 하한 ≤ 0 (소표본으로 단계 차가 안 보임) — "
                        "PASS 도 실패도 아님. 정밀 자동 전환 안 함(보고·제안만)",
                "선별통과": "플래그 없음 AND 최쉬움−최어려움 하한 > 0. 인접 소역전(−0.10<g<0, CI 0 포함)은 비고로만 기록. "
                         "'선별 통과' ≠ 실유저 밸런스 검증·런타임 PASS",
            },
            "refineSelection": "정밀대상 전부를 우선순위 순으로: (1) R_sig 또는 R_big — 최소 g 오름차순, (2) X_range — 최대 범위 "
                               "내림차순, (3) X_edge 만 — 레벨 오름차순. 누적 판수 ≤ 300,000 까지 실시, 나머지 = '정밀대상(예산 "
                               "초과·미실시)'. 선별 완료 후 결정적으로 계산(refine_targets.json)",
            "refine": {
                "평가불가": "모든 단계 ≤0.02 또는 ≥0.98",
                "역전 유지": "정보있는 쌍 중 Newcombe 상한 < 0 (유의 역전) 1개 이상 → 재선별 후보 목록(시드 교체 안 함)",
                "불확실": "유의 역전 없음 AND (점추정 역전 쌍 g<0 있음 OR 최쉬움−최어려움 하한 ≤ 0)",
                "역전 해소/없음": "점추정 역전 없음 AND 최쉬움−최어려움 하한 > 0",
                "극단": "정밀에서 X_range(시드 300판 max−min ≥0.30)·X_edge 재평가 → '극단 유지'(검토 목록) / '극단 해소'. "
                        "역전 판정과 별도 열",
            },
            "noReoptimize": "정밀은 확인만. 시드 자동 교체·재생성·후보 탐색 없음",
            "multiplicity": "레벨 ~1200 × 쌍 6, 보정 없음 — 선별 R_sig 는 영가설에서도 일부 발생(정밀이 거름)",
        },
        "budget": {"screenGames": sg, "refineCapGames": REFINE_CAP, "totalCap": TOTAL_CAP,
                   "cpuPerGame": "0.018~0.045s (confirm12 0.0215 실측, L1001+ 느림)",
                   "expectedCpuH": [round((sg + REFINE_CAP) * c / 3600, 1) for c in (0.02, 0.045)],
                   "expectedWallH_2proc": [round((sg + REFINE_CAP) * c / 3600 / 2, 1) for c in (0.02, 0.045)],
                   "rule": "실행 중 누적이 상한을 넘으면 새 작업 투입 안 함"},
        "safety": {"procs": MAX_PROC, "lock": "OUT/run.lock(pid) + 같은 스크립트 run 프로세스 확인",
                   "resourceStop": f"작업 투입 전·≤30초마다: swap free < {SWAP_MIN_MB}MB · pressure critical(4) · 디스크 < "
                                   f"{DISK_MIN_GB}GiB → 새 작업 중지, 진행 중만 마치고 종료(체크포인트)",
                   "checkpoint": "레벨 단위 append(raw_<phase>.jsonl), 재개 시 기록된 (level,map,θ) 건너뜀 — 같은 판 두 번 금지(중복 "
                                 "행 assert)", "manualStop": "OUT/STOP 파일", "progress": "≤30초 간격 로그"},
        "label": "봇 기준(v2.4 규칙 정합, θ≤0.65). 실유저 클리어율 아님. 선별 통과 ≠ 런타임 PASS",
    })
    (OUT / "PREREG_screen.sha256").write_text(f"{fsha(PREREG)}  PREREG_screen.json\n")
    log(f"PREREG written sha={fsha(PREREG)} screenGames={sg} seeds={nseeds}")
    print(fsha(PREREG))


# ───────────────────────── run ─────────────────────────
def level_task(a):
    L = a["level"]
    t = time.time()
    maps, meta = build_sel(L, a["spec"], a["c12"])
    for k, m in a["expect"].items():
        assert meta[k]["botLjSha16"] == m["botLjSha16"] and meta[k]["randSeed"] == m["randSeed"], (L, k)
    rows = []
    for k, ti in a["todo"]:
        r = m20.games_task({"level": L, "map": k, "theta": THETAS[ti], "lj": maps[k], "games": a["games"],
                            "seedBase": a["base"] + ti * 10_000})
        r.pop("pid", None)
        r.update({"phase": a["phase"], "randSeed": meta[k]["randSeed"], "zone": meta[k]["zone"]})
        rows.append(r)
    return {"level": L, "rows": rows, "sec": time.time() - t}


def raw_path(phase):
    return OUT / f"raw_{phase}.jsonl"


def read_raw(phase):
    done, rows = set(), []
    p = raw_path(phase)
    if p.exists():
        for line in p.open():
            r = json.loads(line)
            key = (r["level"], r["map"], r["theta"])
            assert key not in done, ("dup row", phase, key)
            done.add(key)
            rows.append(r)
    return done, rows


def check_prereg():
    pre = json.loads(PREREG.read_bytes())
    sha_now = fsha(PREREG)
    pinned = (OUT / "PREREG_screen.sha256").read_text().split()[0]
    if sha_now != pinned:
        raise SystemExit(f"PREREG sha mismatch {sha_now} != {pinned}")
    assert pre["inputs"]["targetsJson"] == fsha(OUT / "targets.json"), "targets.json changed"
    assert pre["inputs"]["classification"] == fsha(PLAN / "classification_L32_L1530.csv")
    return pre


def cmd_run(phase):
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
    ps = subprocess.run(["pgrep", "-f", "dda_screen_refine_20261026.py run"], capture_output=True, text=True).stdout.split()
    others = [p for p in ps if int(p) != os.getpid()]
    if others:
        raise SystemExit(f"other run process: {others}")
    lock.write_text(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')} {phase}\n")
    try:
        return _run(phase)
    finally:
        lock.unlink(missing_ok=True)


def _run(phase):
    blob = subprocess.run(["git", "hash-object", str(m20.BOT_FILE)], capture_output=True, text=True).stdout.strip()
    if blob != m20.BOT_BLOB:
        raise SystemExit(f"bot blob changed: {blob}")
    if (OUT / "STOP").exists():
        raise SystemExit("STOP file present — remove to run")
    c12, spec, _ = load_inputs()
    tg = json.loads((OUT / "targets.json").read_bytes())
    if phase == "screen":
        levels = [int(L) for L in tg["levels"]]
    else:
        rt = json.loads((OUT / "refine_targets.json").read_bytes())
        assert rt["preregSha256"] == fsha(PREREG)
        levels = [x["level"] for x in rt["run"]]
    games = PHASES[phase]["games"]
    done, _ = read_raw(phase)
    _, other = read_raw("refine" if phase == "screen" else "screen")
    already = len(done) * games + len(other) * PHASES["refine" if phase == "screen" else "screen"]["games"]
    tasks, total_units = [], 0
    for L in levels:
        seeds = tg["levels"][str(L)]["seeds"]
        todo = [(k, ti) for k in seeds for ti in range(len(THETAS)) if (L, k, THETAS[ti]) not in done]
        total_units += len(seeds) * len(THETAS)
        if todo:
            tasks.append({"level": L, "spec": spec[L], "c12": c12[L], "expect": seeds, "todo": todo, "games": games,
                          "base": PHASES[phase]["base"], "phase": phase})
    plan_games = sum(len(a["todo"]) for a in tasks) * games
    cap = SCREEN_CAP if phase == "screen" else REFINE_CAP
    phase_done = len(done) * games
    if phase_done + plan_games > cap or already + plan_games > TOTAL_CAP:
        raise SystemExit(f"budget exceeded: phase {phase_done}+{plan_games} > {cap} or total {already}+{plan_games}")
    lvl, free, disk, bad = resource()
    log(f"[{phase}:start] levels {len(levels)} todoLevels {len(tasks)} units {len(done)}/{total_units} "
        f"games todo {plan_games} pressure={lvl} swapFree={free:.0f}MB disk={disk:.0f}GiB prereg={fsha(PREREG)[:16]}")
    if bad:
        log(f"STOP: resource at start")
        return 2
    t0, last, n_units, g_run, cpu = time.time(), 0.0, len(done), 0, 0.0
    lv_done = 0
    it = iter(tasks)
    stop = None
    with ProcessPoolExecutor(MAX_PROC) as ex, raw_path(phase).open("a") as fo:
        pend = set()
        while True:
            while not stop and len(pend) < MAX_PROC * 2:
                lvl, free, disk, bad = resource()
                if bad:
                    stop = f"resource pressure={lvl} swapFree={free:.0f}MB disk={disk:.0f}GiB (before submit)"
                    log("STOP requested: " + stop)
                    break
                if (OUT / "STOP").exists():
                    stop = "STOP file"
                    log("STOP requested: STOP file")
                    break
                a = next(it, None)
                if a is None:
                    break
                pend.add(ex.submit(level_task, a))
            if not pend:
                break
            fin, pend = wait(pend, timeout=15, return_when=FIRST_COMPLETED)
            for f in fin:
                r = f.result()
                fo.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r["rows"]))
                fo.flush()
                os.fsync(fo.fileno())
                n_units += len(r["rows"])
                g_run += sum(x["n"] for x in r["rows"])
                cpu += sum(x["sec"] for x in r["rows"])
                lv_done += 1
            if time.time() - last >= 30:
                last = time.time()
                lvl, free, disk, bad = resource()
                el = time.time() - t0
                rate = g_run / max(el, 1)
                eta = (plan_games - g_run) / max(rate, 1e-9) / 60
                log(f"[{phase}] units {n_units}/{total_units} levels+{lv_done}/{len(tasks)} games {g_run}/{plan_games} "
                    f"{el:.0f}s {rate:.1f}g/s cpu {cpu:.0f}s eta {eta:.0f}min pressure={lvl} swapFree={free:.0f}MB "
                    f"disk={disk:.0f}GiB")
                if bad and not stop:
                    stop = f"resource pressure={lvl} swapFree={free:.0f}MB disk={disk:.0f}GiB"
                    log("STOP requested: " + stop + " (finishing in-flight only)")
    log(f"[{phase}:end] units {n_units}/{total_units} games {g_run} wall {time.time() - t0:.0f}s cpu {cpu:.0f}s"
        + (f" stopped: {stop}" if stop else ""))
    return 3 if stop else 0


# ───────────────────────── analysis ─────────────────────────
def stats(L, seeds, rows):
    """seeds = targets meta; rows = raw rows of this level (one phase)."""
    agg = {}
    for r in rows:
        a = agg.setdefault(r["map"], [0, 0])
        a[0] += r["wins"]
        a[1] += r["n"]
    zones = [zn for _, zn, _ in ZONES if any(m["zone"] == zn for m in seeds.values())]
    st = {}
    for zn in zones:
        ks = sorted(k for k, m in seeds.items() if m["zone"] == zn)
        w = sum(agg[k][0] for k in ks)
        n = sum(agg[k][1] for k in ks)
        sw = [agg[k][0] / agg[k][1] for k in ks]
        st[zn] = {"w": w, "n": n, "W": w / n, "seedW": sw, "range": max(sw) - min(sw)}
    pairs = []
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            A, B = st[a], st[b]
            info = not ((A["W"] <= EXT_LO and B["W"] <= EXT_LO) or (A["W"] >= EXT_HI and B["W"] >= EXT_HI))
            lo, hi = m20.newcombe(A["w"], A["n"], B["w"], B["n"])
            pairs.append({"pair": f"{a}-{b}", "adj": zones.index(b) == i + 1, "g": A["W"] - B["W"], "lo": lo, "hi": hi,
                          "info": info})
    allx = all(s["W"] <= EXT_LO for s in st.values()) or all(s["W"] >= EXT_HI for s in st.values())
    span = next(p for p in pairs if p["pair"] == f"{zones[0]}-{zones[-1]}")
    return st, pairs, allx, span, zones


def flags_of(st, pairs, range_thr):
    ip = [p for p in pairs if p["info"]]
    f = {"R_big": [p["pair"] for p in ip if p["g"] <= BIG], "R_sig": [p["pair"] for p in ip if p["hi"] < 0],
         "X_range": [z for z, s in st.items() if s["range"] >= range_thr],
         "X_edge": [z for z, s in st.items() if (z in ("E2", "E1") and s["W"] <= EXT_LO)
                    or (z in ("H1", "H2") and s["W"] >= EXT_HI)]}
    return f, (min((p["g"] for p in ip), default=0.0))


def fmt(x):
    return round(x, 4)


def screen_eval(tg, rows_by):
    out = []
    for Ls, v in tg["levels"].items():
        L = int(Ls)
        rows = rows_by.get(L, [])
        need = len(v["seeds"]) * len(THETAS)
        if len(rows) != need:
            out.append({"level": L, "why": v["why"], "screen": "미완료", "units": f"{len(rows)}/{need}"})
            continue
        st, pairs, allx, span, zones = stats(L, v["seeds"], rows)
        f, gmin = flags_of(st, pairs, RANGE_SCREEN)
        if allx:
            cat = "평가불가(바닥/천장)"
        elif any(f.values()):
            cat = "정밀대상"
        elif span["lo"] <= 0:
            cat = "불확실"
        else:
            cat = "선별통과"
        small = [p["pair"] for p in pairs if p["info"] and p["adj"] and p["g"] < 0]
        out.append({"level": L, "why": v["why"], "screen": cat, "zones": "".join(zones),
                    **{f"W_{z}": fmt(st[z]["W"]) for z in zones},
                    **{f"seeds_{z}": "|".join(f"{x:.2f}" for x in st[z]["seedW"]) for z in zones},
                    **{f"range_{z}": fmt(st[z]["range"]) for z in zones},
                    "gmin": fmt(gmin), "span": f"{span['pair']} {span['g']:.3f} [{span['lo']:.3f},{span['hi']:.3f}]",
                    "pairs": "; ".join(f"{p['pair']} {p['g']:+.3f}[{p['lo']:+.3f},{p['hi']:+.3f}]"
                                       + ("" if p["info"] else " 정보없음") for p in pairs),
                    "flags": ";".join(f"{k}:{','.join(x)}" for k, x in f.items() if x), "smallAdjRev": ",".join(small),
                    "_f": f, "_gmin": gmin, "_st": st})
    return out


def cmd_report_screen():
    pre = check_prereg()
    tg = json.loads((OUT / "targets.json").read_bytes())
    _, rows = read_raw("screen")
    by = {}
    for r in rows:
        by.setdefault(r["level"], []).append(r)
    ev = screen_eval(tg, by)
    inc = [e for e in ev if e["screen"] == "미완료"]
    if inc:
        raise SystemExit(f"screen incomplete: {len(inc)} levels")
    # 정밀 대상 우선순위 (PREREG judge.refineSelection)
    cand = [e for e in ev if e["screen"] == "정밀대상"]

    def prio(e):
        f = e["_f"]
        if f["R_sig"] or f["R_big"]:
            return (0, e["_gmin"], e["level"])
        if f["X_range"]:
            return (1, -max(e["_st"][z]["range"] for z in f["X_range"]), e["level"])
        return (2, e["level"], 0)
    cand.sort(key=prio)
    run, over, acc = [], [], 0
    for e in cand:
        g = len(tg["levels"][str(e["level"])]["seeds"]) * len(THETAS) * PHASES["refine"]["games"]
        if acc + g <= REFINE_CAP:
            acc += g
            run.append({"level": e["level"], "games": g, "prio": list(prio(e))[:2], "flags": e["flags"]})
        else:
            over.append({"level": e["level"], "games": g, "prio": list(prio(e))[:2], "flags": e["flags"]})
    save(OUT / "refine_targets.json", {"preregSha256": fsha(PREREG), "rawScreenSha256": fsha(raw_path("screen")),
                                       "rule": pre["judge"]["refineSelection"], "run": run, "overBudget": over,
                                       "refineGames": acc})
    cols = ["level", "why", "screen", "zones", "W_E2", "W_E1", "W_H1", "W_H2", "seeds_E2", "seeds_E1", "seeds_H1",
            "seeds_H2", "range_E2", "range_E1", "range_H1", "range_H2", "gmin", "span", "flags", "smallAdjRev", "pairs"]
    with (OUT / "screen_levels.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for e in sorted(ev, key=lambda x: x["level"]):
            w.writerow(e)
    c = Counter((e["why"], e["screen"]) for e in ev)
    fl = Counter(k for e in cand for k, x in e["_f"].items() if x)
    summ = {"screenGames": sum(r["n"] for r in rows), "cpuSec": round(sum(r["sec"] for r in rows), 1),
            "byWhyCat": {f"{a}|{b}": n for (a, b), n in sorted(c.items())},
            "byCat": dict(Counter(e["screen"] for e in ev)), "refineCandFlags": dict(fl),
            "refineRun": len(run), "refineOver": len(over), "refineGames": acc,
            "smallAdjRevLevels": sum(1 for e in ev if e.get("smallAdjRev"))}
    save(OUT / "screen_summary.json", summ)
    log("screen report: " + json.dumps(summ, ensure_ascii=False))


def cmd_report_final():
    check_prereg()
    tg = json.loads((OUT / "targets.json").read_bytes())
    rt = json.loads((OUT / "refine_targets.json").read_bytes())
    _, srows = read_raw("screen")
    _, rrows = read_raw("refine")
    sby, rby = {}, {}
    for r in srows:
        sby.setdefault(r["level"], []).append(r)
    for r in rrows:
        rby.setdefault(r["level"], []).append(r)
    sev = {e["level"]: e for e in screen_eval(tg, sby)}
    run_set = {x["level"] for x in rt["run"]}
    over_set = {x["level"] for x in rt["overBudget"]}
    c12res = {int(r["level"]): r for r in csv.DictReader((C12 / "results_levels.csv").open())}
    final, refine_rows = {}, []
    for L in run_set:
        v = tg["levels"][str(L)]
        need = len(v["seeds"]) * len(THETAS)
        if len(rby.get(L, [])) != need:
            refine_rows.append({"level": L, "refine": "정밀 미완료"})
            continue
        st, pairs, allx, span, zones = stats(L, v["seeds"], rby[L])
        f, gmin = flags_of(st, pairs, RANGE_REFINE)
        ip = [p for p in pairs if p["info"]]
        if allx:
            rev = "평가불가(바닥/천장)"
        elif any(p["hi"] < 0 for p in ip):
            rev = "역전 유지"
        elif any(p["g"] < 0 for p in ip) or span["lo"] <= 0:
            rev = "불확실"
        else:
            rev = "역전 해소/없음"
        ext = "극단 유지" if (f["X_range"] or f["X_edge"]) else "극단 해소/없음"
        refine_rows.append({"level": L, "why": v["why"], "screenFlags": sev[L]["flags"], "refine": rev, "extreme": ext,
                            "zones": "".join(zones), **{f"W_{z}": fmt(st[z]["W"]) for z in zones},
                            **{f"seeds_{z}": "|".join(f"{x:.3f}" for x in st[z]["seedW"]) for z in zones},
                            **{f"ci_{z}": "{:.3f}-{:.3f}".format(*m20.wilson(st[z]["w"], st[z]["n"])) for z in zones},
                            "gmin": fmt(gmin), "refineFlags": ";".join(f"{k}:{','.join(x)}" for k, x in f.items() if x),
                            "pairs": "; ".join(f"{p['pair']} {p['g']:+.3f}[{p['lo']:+.3f},{p['hi']:+.3f}]"
                                               + ("" if p["info"] else " 정보없음") for p in pairs)})
    rmap = {r["level"]: r for r in refine_rows}
    for Ls, gv in tg["groups"].items():
        L = int(Ls)
        g, why = gv["group"], gv["why"]
        if g == "excluded":
            cat = "정책상제외"
        elif g == "hold":
            cat = "보류(기존 사유)" if why.startswith("보류") else "승인필요(기존 사유)"
        elif g == "reuse":
            cat = f"기존 확인PASS 재사용(confirm12 {c12res[L]['verdict']})"
        elif Ls in tg["mapFail"]:
            cat = "평가불가(맵 생성 실패)"
        else:
            s = sev[L]["screen"]
            if s != "정밀대상":
                cat = s
            elif L in over_set:
                cat = "정밀대상(예산 초과·미실시)"
            else:
                r = rmap[L]
                if r["refine"] == "역전 유지":
                    cat = "정밀 확인됨(역전 유지)"
                elif r["refine"] == "역전 해소/없음":
                    cat = "정밀 확인됨(역전 해소/없음" + (", 극단 유지)" if r["extreme"] == "극단 유지" else ")")
                elif r["refine"] == "불확실":
                    cat = "불확실(정밀)"
                else:
                    cat = r["refine"] if r["refine"].startswith("평가불가") else "정밀 미완료"
        final[L] = {"level": L, "group": g, "why": why, "final": cat}
    with (OUT / "final_levels.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "group", "why", "final"])
        w.writeheader()
        for L in sorted(final):
            w.writerow(final[L])
    if refine_rows:
        cols = sorted({k for r in refine_rows for k in r}, key=lambda k: (k != "level", k))
        with (OUT / "refine_levels.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in sorted(refine_rows, key=lambda x: x["level"]):
                w.writerow(r)
    inf = []
    for r in csv.DictReader((PLAN / "infinity_copy_plan.csv").open()):
        src = int(r["sourceLevel"])
        assert src == 500 + int(r["infinity"])
        inf.append({"infinity": f"infinity_{r['infinity']}", "sourceLevel": src, "copyable": r["copyable"],
                    "planReason": r["reason"], "sourceFinal": final[src]["final"],
                    "note": "원본 결과 재사용(동일 맵, 측정 안 함). 복사 정합성·런타임 QA 별도"})
    with (OUT / "infinity_reuse_map.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(inf[0]))
        w.writeheader()
        w.writerows(inf)
    resel = [r for r in refine_rows if r.get("refine") == "역전 유지"]
    summ = {
        "official": dict(Counter(v["final"] for v in final.values())),
        "officialByWhy": {f"{k[0]}|{k[1]}": n for k, n in sorted(Counter((v["why"].split("|")[0], v["final"])
                                                                           for v in final.values()).items())},
        "infinity": dict(Counter((x["copyable"], x["sourceFinal"]) for x in inf).most_common()),
        "games": {"screen": sum(r["n"] for r in srows), "refine": sum(r["n"] for r in rrows)},
        "cpuSec": {"screen": round(sum(r["sec"] for r in srows), 1), "refine": round(sum(r["sec"] for r in rrows), 1)},
        "reselectCandidates": [r["level"] for r in sorted(resel, key=lambda x: x["level"])],
        "extremeKept": [r["level"] for r in refine_rows if r.get("extreme") == "극단 유지"],
        "label": "봇 기준(v2.4, θ≤0.65). 선별 통과 ≠ 실유저 밸런스 검증·런타임 PASS. 시드 교체 산출물 없음",
    }
    summ["infinity"] = {f"{a}|{b}": n for (a, b), n in summ["infinity"].items()}
    save(OUT / "final_summary.json", summ)
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name not in ("SHA256SUMS", "run.lock", "STOP"))
    (OUT / "SHA256SUMS").write_text("".join(f"{fsha(p)}  {p.name}\n" for p in files))
    log("final report: " + json.dumps(summ, ensure_ascii=False)[:3000])


def cmd_status():
    for ph in PHASES:
        d, rows = read_raw(ph)
        print(ph, "units", len(d), "games", sum(r["n"] for r in rows), "cpu", round(sum(r["sec"] for r in rows)),
              "levels", len({r["level"] for r in rows}))
    print("lock", (OUT / "run.lock").read_text() if (OUT / "run.lock").exists() else None, "resource", resource())


if __name__ == "__main__":
    a = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    if a[:1] == ["prep"]:
        rc = cmd_prep()
    elif a[:1] == ["prereg"]:
        rc = cmd_prereg()
    elif a[:1] == ["run"] and a[1:2] in (["screen"], ["refine"]):
        rc = cmd_run(a[1])
    elif a == ["report", "screen"]:
        rc = cmd_report_screen()
    elif a == ["report", "final"]:
        rc = cmd_report_final()
    elif a[:1] == ["status"]:
        rc = cmd_status()
    else:
        raise SystemExit(__doc__)
    sys.exit(rc or 0)
