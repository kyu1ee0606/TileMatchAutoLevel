#!/usr/bin/env python3
"""DDA v2_2 선정 12레벨 — 독립 확인 측정 (2026-10-22, 문서 51).

대상 = spec_v2_2_variant4order_20261022 '선정' 12레벨의 v2_2 선정 시드(4구간 × 3시드) 그대로. 측정 중 변경 금지.
측정 경로 = 문서 49 드라이버(dda_spec_v2_measure20_20261022.py) 의 build_maps / games_task 를 그대로 임포트해 사용
           (set_rule_parity → _create_initial_state → seed → _play_game : 규칙 먼저 적용).
새 봇 시드 대역 65,000,000 + θidx*10_000 + g (g<100). 서버·게임·Unity 접근 없음. 기존 스크립트·자료 수정 없음.

명령 (cd backend && venv/bin/python scripts/dda_v2_2_confirm12_20261022.py <cmd>)
  prereg : 맵 생성·결속 검사(게임 0판) + PREREG_confirm.json 작성 (이미 있으면 거부)
  run    : 측정(재개 가능 — 기록된 (level,map,θ) 건너뜀). 락 파일·자원 체크
  report : 판정·산출물(results/levels/changes/manifest/SHA256SUMS) + 정합 검증 (발행본 있음 — 재실행 금지)
  --check-only : 읽기 전용 점검(PREREG sha·targets, 발행 산출물 verify_final 재실행, manifest/SUMS sha 불변). 쓰기 0
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
import dda_spec_v2_measure20_20261022 as m20  # noqa: E402  (build_maps, games_task, cand_table, newcombe, wilson, resource)

DS = BACKEND / "data/dda_seeds"
MEAS = DS / "spec_v2_measure20_20261022"
SPEC = DS / "spec_v2_3x4_20261022"
V21 = DS / "spec_v2_1_measure20_20261022"
V22 = DS / "spec_v2_2_variant4order_20261022"
OUT = DS / "spec_v2_2_confirm12_20261022"
CATALOG = DS / "dda_t0_seed_catalog.v1.json"
RUN = m20.RUN

V22_MANIFEST_SHA = "a803dc2e84cb74d2275d57f2581af151851f85581d8fb15375b3df8962bdc99d"
V22_LEVELS_SHA = "e71de009649d4cef332307c8dd5a4ee974c23ba5fbefc09ddcef73ed9a081d0e"
V22_RESULTS_SHA = "050c88ad2ba145a59732d713a31be6fccb724054122e05dcfc5827f3eab1886f"
V22_PREREG_SHA = "897a203508ee716ef7008077adbff0f914a6f71f6ad1f6e5406941d65e1bc29a"
SPEC_MANIFEST_SHA = m20.SPEC_MANIFEST_SHA
V21_MANIFEST_SHA = "5c1cae7c99a9fa1dea48935a2f31fc3fe149a579860477dc778bde40b0dcfc5b"
RAW20_SHA = "b805f57b533b435693954c2ceb1fb7a40913cdf6f0be241bf771081fbe10cd18"
MAPS_META_SHA = "44f0945967d55c841a1cd530760942a32e40572832c9f159fd073184faec771d"

LEVELS_OUT = "levels_spec_v2_2_confirm12.json"   # 로더 규칙: SHA256SUMS 안 levels_spec_*.json 1개
LEVELS = [278, 407, 1195, 65, 86, 95, 225, 234, 325, 472, 521, 851]   # 측정 순서 (취약 3 먼저)
ZONES = [("ddaEasy2Seeds", "easy2", -2, "E2"), ("ddaEasySeeds", "easy", -1, "E1"),
         ("ddaHardSeeds", "hard", +1, "H1"), ("ddaHard2Seeds", "hard2", +2, "H2")]
PM1 = ("ddaEasySeeds", "ddaHardSeeds")
THETAS = m20.THETAS                       # (0.29, 0.47, 0.65)
GAMES = 100                               # 시드당 θ별
NS = GAMES * len(THETAS)                  # 시드당 300
NZ = 3 * NS                               # 구간당 900
PREREG_SHA = "6b8450bc372e6bf5f973787721196697d8708391f4af100364666448367cc62c"   # 고정 (문서 51 §1)
FINAL_MANIFEST_SHA = "88a7415b7844fa8cc34ff49e49832d36511e0ccf6b4d01a0a516dfdd2264b76d"   # 발행본 (업로더 드라이런 대상)
FINAL_SUMS_SHA = "06ded52acf7ec4991c38ebf86f729520a3e542166716f4045f70f9d4c3993ff9"
SEED_BASE = 65_000_000                    # 65,000,000 ~ 65,020,099
MAX_PROC = 2
SWAP_MIN_MB = 500


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
    return lvl, free, (lvl == "4" or free < SWAP_MIN_MB)


def check_inputs():
    for p, h in ((V22 / "manifest.json", V22_MANIFEST_SHA), (V22 / "levels_spec_v2_2.json", V22_LEVELS_SHA),
                 (V22 / "results_levels.json", V22_RESULTS_SHA), (V22 / "PREREG_v2_2.json", V22_PREREG_SHA),
                 (SPEC / "manifest.json", SPEC_MANIFEST_SHA), (V21 / "manifest.json", V21_MANIFEST_SHA),
                 (MEAS / "raw_rows.jsonl", RAW20_SHA), (MEAS / "maps_meta.json", MAPS_META_SHA)):
        assert sha(p.read_bytes()) == h, f"input sha mismatch: {p}"


def targets():
    """{L: {field: [cand,...]}} from v2_2 results (선정 레벨만) + levels json 대조."""
    res = {r["level"]: r for r in json.loads((V22 / "results_levels.json").read_text())["levels"]}
    lv = {r["level"]: r for r in json.loads((V22 / "levels_spec_v2_2.json").read_bytes())}
    meta = json.loads((MEAS / "maps_meta.json").read_text())
    t = {}
    for L in LEVELS:
        assert res[L]["verdict"] == "선정", L
        t[L] = {}
        for field, _, dl, _ in ZONES:
            cs = res[L]["output"][field]["cands"]
            assert len(cs) == 3
            seeds = ",".join(str(meta[str(L)][f"{field}:{c}"]["randSeed"]) for c in cs)
            assert seeds == res[L]["output"][field]["seeds"] == lv[L]["fields"][field], (L, field)
            for c in cs:
                assert meta[str(L)][f"{field}:{c}"]["useTileCount"] == lv[L]["N"] + dl
            t[L][field] = cs
    return t, meta


def used_bot_seeds():
    s = set()
    for line in (MEAS / "raw_rows.jsonl").open():
        r = json.loads(line)
        s.update(range(r["seedRange"][0], r["seedRange"][1] + 1))
    return s


def new_seeds():
    return {SEED_BASE + ti * 10_000 + g for ti in range(len(THETAS)) for g in range(GAMES)}


def cmd_prereg():
    p = OUT / "PREREG_confirm.json"
    if p.exists():
        raise SystemExit("PREREG exists — not overwriting")
    check_inputs()
    t, meta = targets()
    lo, hi = SEED_BASE, SEED_BASE + (len(THETAS) - 1) * 10_000 + GAMES - 1
    bands = dict(m20.SEED_USED_BANDS, measure20=[m20.SEED_BASE], measure20_n0=[m20.N0_BOT_BASE])
    for g, vs in bands.items():
        for v in vs:
            assert hi < v or lo > v + 1_000_000, (g, v)
    used = used_bot_seeds()
    ov = used & new_seeds()
    assert not ov
    ct = m20.cand_table()
    spec = {r["level"]: r for r in json.loads((SPEC / "levels_spec_v2.json").read_text())}
    lvb = (V22 / "levels_spec_v2_2.json").read_bytes()
    lv = {r["level"]: r for r in json.loads(lvb)}
    tl, nseeds = {}, 0
    for L in LEVELS:
        maps, mm = m20.build_maps(L, ct, spec[L])
        tl[str(L)] = {"N": lv[L]["N"], "fields": {}}
        for field, _, dl, zn in ZONES:
            rows = []
            for c in t[L][field]:
                k = f"{field}:{c}"
                assert mm[k]["botLjSha16"] == meta[str(L)][k]["botLjSha16"], (L, k)
                rows.append({"map": k, "cand": c, "randSeed": mm[k]["randSeed"], "useTileCount": mm[k]["useTileCount"],
                             "resolvedMapSha256": mm[k]["resolvedMapSha256"], "botLjSha16": mm[k]["botLjSha16"]})
                nseeds += 1
            tl[str(L)]["fields"][field] = {"zone": zn, "seeds": lv[L]["fields"][field], "cands": rows}
    assert nseeds == 144
    total = len(LEVELS) * 12 * len(THETAS) * GAMES
    save(p, {
        "written": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "doc": "claudedocs/difficulty_personalization/51_dda_v2_2_confirm12_20261022.md",
        "status": "결과 보기 전 작성. 확인 측정 — 선정 시드 고정(측정 중 변경 금지), 확인 자료로 후보 재선택(재최적화) 금지",
        "inputs": {"v2_2Manifest": V22_MANIFEST_SHA, "v2_2Levels": V22_LEVELS_SHA, "v2_2Results": V22_RESULTS_SHA,
                   "v2_2Prereg": V22_PREREG_SHA, "specV2Manifest": SPEC_MANIFEST_SHA,
                   "specV2_1Manifest": V21_MANIFEST_SHA, "measure20RawRows": RAW20_SHA,
                   "measure20MapsMeta": MAPS_META_SHA,
                   "driverReused": {"path": "scripts/dda_spec_v2_measure20_20261022.py",
                                    "sha256": sha((BACKEND / "scripts/dda_spec_v2_measure20_20261022.py").read_bytes()),
                                    "functions": "build_maps, games_task (규칙 먼저: set_rule_parity → _create_initial_state)"}},
        "levels": LEVELS, "measureOrder": "L278, L407, L1195 먼저, 그다음 L65·86·95·225·234·325·472·521·851",
        "fieldsCount": 48, "seedsCount": 144, "targets": tl,
        "bot": {"version": m20.BOT_VER, "items": "V24_DEFAULT (규칙 6건)", "blob": m20.BOT_BLOB,
                "call": "set_rule_parity → _create_initial_state → _precompute_blocking_map → seed(base+θidx*10000+g) → _play_game"},
        "thetas": THETAS, "gamesPerSeedPerTheta": GAMES, "gamesPerZone": NZ, "totalGames": total,
        "botSeedBand": [lo, hi],
        "botSeedFormula": "seed = 65_000_000 + θidx*10_000 + g (g<100), 모든 맵·레벨 공통 (CRN)",
        "seedOverlapCheck": {"method": "(1) measure20 raw_rows.jsonl 1560행 seedRange 전개 집합 ∩ 새 시드 300개 = 공집합 "
                                       "(2) measure20 SEED_USED_BANDS + 61M + 63M 각 대역 [v, v+1M] 과 [lo,hi] 비중첩",
                             "rawRowsUsedSeeds": len(used), "intersection": len(ov), "bandsChecked": bands},
        "notMeasured": "원본·N±0 새 측정 안 함 — measure20 기존 값은 참고 열로만. 평가불가 6·미확정 2레벨 측정 안 함",
        "judge": {
            "zoneW": "구간 W = 선정 3시드 × 3θ × 100판 합산 (900판)",
            "pair": "인접 3쌍 E2–E1, E1–H1, H1–H2, g = W_쉬운 − W_어려운, Newcombe hybrid score 95% (z 1.959964, 문서 49/50 "
                    "과 같은 함수 = m20.newcombe, 900 vs 900 독립 근사 — CRN 무시·보수적)",
            "pairStatus": "정보없음(둘 다 0/900 또는 둘 다 900/900) / 유의정렬(하한>0) / 방향만(g>0) / 동률(g=0) / "
                          "역전(g<0) / 유의역전(상한<0)",
            "확인PASS": "3쌍 모두 유의정렬(Newcombe 하한 > 0)",
            "실패": "어느 쌍이든 점추정 역전(g<0). 유의역전(상한<0) 여부 별도 표시",
            "미확정": "PASS·실패 아님 — 점추정 정렬이지만 어느 쌍 CI 가 0 포함, 또는 동률·정보없음 쌍 포함(정보없음 = PASS 아님)",
            "separateReports(판정과 분리)": {
                "rangeSeparation": "쉬운 구간 3시드 최저 W(300판) > 어려운 구간 최고 W, 인접 3쌍 각각과 전부",
                "thetaConsistency": "θ마다 구간 W(300판) 3쌍 모두 g_θ>0 인 θ 수 k/3",
                "seedInversions": "다른 구간 시드 쌍(인접·비인접 전부, 시드 W 300판) 중 쉬운 구간 시드 W < 어려운 구간 시드 W 수, "
                                  "Newcombe 300 vs 300 상한<0 = 유의",
                "vsExploration": "measure20 탐색값(v2_2 best Wz, 쌍 하한) 대비 변화"},
            "noReoptimize": "확인 자료로 후보를 다시 고르지 않음. 실패·미확정 레벨은 보류, 추가탐색은 제안만",
            "multiplicity": "12레벨 × 3쌍, 보정 없음. 900 vs 900, p≈0.5 에서 g 95% CI 반폭 ≈ ±0.046",
        },
        "finalOutput": {
            "base": "spec_v2 levels_spec_v2.json",
            "확인PASS": "v2_2 시드(레코드) 채택",
            "미확정·실패": "v2_2 변경 미적용 = spec_v2 값 유지 + confirm12.hold=true",
            "측정 20레벨 중 확인 대상 아님(v2_2 미확정 L293·L442, 평가불가 6)": "spec_v2 값 유지 + confirm12.hold=true (확인 안 됨)",
            "20레벨 외": "spec_v2 와 동일(검사)",
            "manifest": "검토 후 동기화, 자동 교체 금지 (syncStatus pending_review), 업로드 안 함",
            "checks": "조건해시(dda_seed_catalog_v2.source_condition_hash) 불변 · 배정정합(각 시드 = 그 구간 N±k 후보, condSha256 "
                      "원장 일치) · 전역 시드 고유 · 20레벨 외 동일 · ±1 서버 5개 앞 3개 불일치 목록",
        },
        "cost": {"games": total, "procs": MAX_PROC},
        "resourceStop": f"청크(작업) 시작 전·중(≤30초) swap free < {SWAP_MIN_MB}MB 또는 pressure critical(4) → 새 작업 투입 중지, "
                        "진행 중 작업만 마치고 기록 후 종료(체크포인트). 회복 확인 후 재개(기록된 (level,map,θ) 건너뜀)",
        "lock": "OUT/run.lock (pid) + 시작 전 같은 스크립트 프로세스 확인",
        "label": "봇 기준(v2.4 규칙 정합, θ≤0.65). 실유저 클리어율 아님",
    })
    log(f"PREREG written {sha(p.read_bytes())}; maps built {len(LEVELS)} levels / {nseeds} seeds; band {lo}..{hi}; "
        f"overlap {len(ov)} vs {len(used)} used")
    print(sha(p.read_bytes()))


def pre_sha():
    return sha((OUT / "PREREG_confirm.json").read_bytes())


def check_prereg():
    """PREREG sha 고정값 + PREREG targets == v2_2 선정값(targets() 재구성) 완전 일치. 다르면 중단."""
    b = (OUT / "PREREG_confirm.json").read_bytes()
    if sha(b) != PREREG_SHA:
        raise SystemExit(f"PREREG sha mismatch: {sha(b)}")
    pre = json.loads(b)
    t, meta = targets()
    lv = {r["level"]: r for r in json.loads((V22 / "levels_spec_v2_2.json").read_bytes())}
    if pre["levels"] != LEVELS or set(pre["targets"]) != {str(L) for L in LEVELS}:
        raise SystemExit("PREREG levels mismatch")
    n = 0
    for L in LEVELS:
        pt = pre["targets"][str(L)]
        if pt["N"] != lv[L]["N"] or set(pt["fields"]) != {z[0] for z in ZONES}:
            raise SystemExit(f"PREREG L{L} N/fields mismatch")
        for field, _, dl, zn in ZONES:
            pf = pt["fields"][field]
            want = [{"map": f"{field}:{c}", "cand": c, "randSeed": meta[str(L)][f"{field}:{c}"]["randSeed"],
                     "useTileCount": meta[str(L)][f"{field}:{c}"]["useTileCount"],
                     "resolvedMapSha256": meta[str(L)][f"{field}:{c}"]["resolvedMapSha256"],
                     "botLjSha16": meta[str(L)][f"{field}:{c}"]["botLjSha16"]} for c in t[L][field]]
            if pf["zone"] != zn or pf["seeds"] != lv[L]["fields"][field] or pf["cands"] != want:
                raise SystemExit(f"PREREG targets mismatch L{L} {field}")
            n += len(want)
    if n != 144:
        raise SystemExit(f"PREREG seed count {n}")
    return pre


def cmd_run():
    check_inputs()
    pre = check_prereg()
    lock = OUT / "run.lock"
    if lock.exists():
        pid = int(lock.read_text().split()[0])
        try:
            os.kill(pid, 0)
            raise SystemExit(f"lock held by live pid {pid}")
        except ProcessLookupError:
            log(f"stale lock (pid {pid}) — removing")
            lock.unlink()
    ps = subprocess.run(["pgrep", "-f", "dda_v2_2_confirm12_20261022.py run"], capture_output=True, text=True).stdout.split()
    others = [p for p in ps if int(p) != os.getpid()]
    if others:
        raise SystemExit(f"other run process: {others}")
    lock.write_text(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    try:
        return _run(pre)
    finally:
        lock.unlink(missing_ok=True)


def _run(pre):
    blob = subprocess.run(["git", "hash-object", str(m20.BOT_FILE)], capture_output=True, text=True).stdout.strip()
    if blob != m20.BOT_BLOB:
        raise SystemExit(f"bot blob changed: {blob}")
    lvl, free, bad = resource()
    log(f"[resource:start] pressure={lvl} swapFree={free:.0f}MB prereg={pre_sha()[:16]}")
    if bad:
        log("STOP: resource at start")
        return 2
    raw = OUT / "raw_rows.jsonl"
    done = set()
    if raw.exists():
        for line in raw.open():
            r = json.loads(line)
            key = (r["level"], r["map"], r["theta"])
            assert key not in done, ("dup row", key)
            done.add(key)
    ct = m20.cand_table()
    spec = {r["level"]: r for r in json.loads((SPEC / "levels_spec_v2.json").read_text())}
    tasks = []
    for L in pre["levels"]:
        maps, mm = m20.build_maps(L, ct, spec[L])
        for field, *_ in ZONES:
            for c in pre["targets"][str(L)]["fields"][field]["cands"]:
                k = c["map"]
                assert mm[k]["botLjSha16"] == c["botLjSha16"] and mm[k]["randSeed"] == c["randSeed"], (L, k)
                for ti, th in enumerate(THETAS):
                    if (L, k, th) not in done:
                        tasks.append({"level": L, "map": k, "theta": th, "lj": maps[k], "games": GAMES,
                                      "seedBase": SEED_BASE + ti * 10_000})
    total = len(LEVELS) * 12 * len(THETAS)
    log(f"tasks todo {len(tasks)} / {total} (done {len(done)})")
    t0, last, n_done, games = time.time(), 0.0, len(done), 0
    it = iter(tasks)
    stop = None
    with ProcessPoolExecutor(MAX_PROC) as ex, raw.open("a") as fo:
        pend = set()
        while True:
            while not stop and len(pend) < MAX_PROC * 2:
                lvl, free, bad = resource()                     # 청크 투입 직전 체크
                if bad:
                    stop = f"resource pressure={lvl} swapFree={free:.0f}MB (before submit)"
                    log("STOP requested: " + stop + " (finishing in-flight tasks only)")
                    break
                a = next(it, None)
                if a is None:
                    break
                pend.add(ex.submit(m20.games_task, a))
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
    log(f"run end: {n_done}/{total} tasks, games this run {games}, {time.time() - t0:.0f}s"
        + (f", stopped: {stop}" if stop else ""))
    return 3 if stop else 0


# ───────────────────────── report ─────────────────────────
def pair_status(we, wh, n):
    g = (we - wh) / n
    lo, hi = m20.newcombe(we, n, wh, n)
    if (we == 0 and wh == 0) or (we == n and wh == n):
        st = "정보없음"
    elif lo > 0:
        st = "유의정렬"
    elif g > 0:
        st = "방향만"
    elif g == 0:
        st = "동률"
    elif hi < 0:
        st = "유의역전"
    else:
        st = "역전"
    return {"g": g, "lo": lo, "hi": hi, "st": st}


def level_verdict(pairs):
    if all(p["st"] == "유의정렬" for p in pairs):
        return "확인PASS"
    if any(p["g"] < 0 for p in pairs):
        return "실패(유의역전)" if any(p["st"] == "유의역전" for p in pairs) else "실패"
    return "미확정"


def cmd_report():
    check_inputs()
    pre = check_prereg()
    rows = [json.loads(x) for x in (OUT / "raw_rows.jsonl").open()]
    seen = set()
    for r in rows:
        k = (r["level"], r["map"], r["theta"])
        assert k not in seen, ("dup", k)
        seen.add(k)
        assert r["n"] == GAMES and len(r["perGame"]) == GAMES and r["perGame"].count("1") == r["wins"]
        ti = THETAS.index(r["theta"])
        assert r["seedBase"] == SEED_BASE + ti * 10_000
    new = new_seeds()
    assert not (used_bot_seeds() & new)
    by = {(r["level"], r["map"], r["theta"]): r for r in rows}
    v22res = {r["level"]: r for r in json.loads((V22 / "results_levels.json").read_text())["levels"]}
    out_levels, seed_rows, cnt = [], [], Counter()
    for L in LEVELS:
        tg = pre["targets"][str(L)]["fields"]
        miss = [(c["map"], th) for f, *_ in ZONES for c in tg[f]["cands"] for th in THETAS if (L, c["map"], th) not in by]
        if miss:
            out_levels.append({"level": L, "verdict": "미측정(불완전)", "missing": len(miss)})
            cnt["미측정"] += 1
            continue
        sw, swt, zw, zwt = {}, {}, [], []
        for f, *_ in ZONES:
            for c in tg[f]["cands"]:
                k = c["map"]
                swt[k] = [by[(L, k, th)]["wins"] for th in THETAS]
                sw[k] = sum(swt[k])
            ks = [c["map"] for c in tg[f]["cands"]]
            zw.append(sum(sw[k] for k in ks))
            zwt.append([sum(swt[k][ti] for k in ks) for ti in range(len(THETAS))])
        pairs = [pair_status(zw[i], zw[i + 1], NZ) for i in range(3)]
        verdict = level_verdict(pairs)
        cnt[verdict] += 1
        zk = [[c["map"] for c in tg[f]["cands"]] for f, *_ in ZONES]
        sep = [min(sw[k] for k in zk[i]) > max(sw[k] for k in zk[i + 1]) for i in range(3)]
        th_ok = [all(zwt[i][ti] > zwt[i + 1][ti] for i in range(3)) for ti in range(len(THETAS))]
        inv, n_pairs = [], 0
        for i in range(4):
            for j in range(i + 1, 4):
                for ke in zk[i]:
                    for kh in zk[j]:
                        n_pairs += 1
                        if sw[ke] < sw[kh]:
                            lo, hi = m20.newcombe(sw[ke], NS, sw[kh], NS)
                            inv.append({"easier": ke, "harder": kh, "We": sw[ke] / NS, "Wh": sw[kh] / NS,
                                        "adjacent": j == i + 1, "sig": hi < 0})
        ex = v22res[L]["best"]
        ref = v22res[L].get("ref(참고만)", {})
        zci = [m20.wilson(w, NZ) for w in zw]
        rec = {"level": L, "N": pre["targets"][str(L)]["N"], "verdict": verdict,
               "Wz": [w / NZ for w in zw], "WzWilson": zci, "wins": zw, "n": NZ,
               "pairs": pairs, "rangeSeparation": sep, "rangeSeparationAll": all(sep),
               "thetaConsistency": {"k": sum(th_ok), "perTheta": dict(zip(map(str, THETAS), th_ok)),
                                    "WzTheta": {str(th): [zwt[z][ti] / (3 * GAMES) for z in range(4)]
                                                for ti, th in enumerate(THETAS)}},
               "seedInversions": {"pairs": n_pairs, "count": len(inv), "sig": sum(x["sig"] for x in inv),
                                  "adjacentCount": sum(x["adjacent"] for x in inv),
                                  "adjacentSig": sum(x["adjacent"] and x["sig"] for x in inv), "list": inv},
               "exploration": {"Wz": ex["Wz"], "pairs": ex["pairs"], "grade": v22res[L]["grade"],
                               "dWz": [zw[z] / NZ - ex["Wz"][z] for z in range(4)],
                               "dPairLo": [pairs[i]["lo"] - ex["pairs"][i]["lo"] for i in range(3)]},
               "ref(참고만, measure20 기존)": ref}
        out_levels.append(rec)
        for z, (f, _, dl, zn) in enumerate(ZONES):
            for c in tg[f]["cands"]:
                k = c["map"]
                wl, wh = m20.wilson(sw[k], NS)
                expW = v22res[L]["candW"][f][str(c["cand"])]
                seed_rows.append({"level": L, "zone": zn, "field": f, "cand": c["cand"], "randSeed": c["randSeed"],
                                  "useTileCount": c["useTileCount"], "wins": sw[k], "n": NS, "W": round(sw[k] / NS, 4),
                                  "wilsonLo": round(wl, 4), "wilsonHi": round(wh, 4),
                                  **{f"W_th{th}": round(swt[k][ti] / GAMES, 3) for ti, th in enumerate(THETAS)},
                                  "W_explore150": round(expW, 4), "dVsExplore": round(sw[k] / NS - expW, 4),
                                  "cpuSec": round(sum(by[(L, k, th)]["sec"] for th in THETAS), 1),
                                  "resolvedMapSha256": c["resolvedMapSha256"]})
        print(f"L{L}: {verdict} Wz={[round(w / NZ, 3) for w in zw]} lo={[round(p['lo'], 3) for p in pairs]} "
              f"st={[p['st'] for p in pairs]} θ{sum(th_ok)}/3 sep={sep} inv={len(inv)}/{n_pairs}(sig {sum(x['sig'] for x in inv)})")
    save(OUT / "results_confirm.json", {"prereg": pre_sha(), "label": pre["label"], "counts": dict(cnt),
                                        "levels": out_levels, "rawRowsSha256": sha((OUT / "raw_rows.jsonl").read_bytes()),
                                        "games": sum(r["n"] for r in rows),
                                        "cpuSec": round(sum(r["sec"] for r in rows), 1)})
    with (OUT / "results_seeds.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(seed_rows[0]))
        w.writeheader()
        w.writerows(seed_rows)
    with (OUT / "results_levels.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["level", "verdict", "W_E2", "W_E1", "W_H1", "W_H2", "ci_E2", "ci_E1", "ci_H1", "ci_H2",
                    "lo_E2E1", "lo_E1H1", "lo_H1H2", "st", "theta_k", "rangeSep", "seedInv", "seedInvSig",
                    "explore_Wz", "explore_lo", "ref_W_orig", "ref_W_n0"])
        for r in out_levels:
            if "Wz" not in r:
                w.writerow([r["level"], r["verdict"]])
                continue
            w.writerow([r["level"], r["verdict"], *[round(x, 4) for x in r["Wz"]],
                        *[f"{a:.3f}-{b:.3f}" for a, b in r["WzWilson"]], *[round(p["lo"], 4) for p in r["pairs"]],
                        "|".join(p["st"] for p in r["pairs"]), r["thetaConsistency"]["k"],
                        "".join("Y" if s else "N" for s in r["rangeSeparation"]), r["seedInversions"]["count"],
                        r["seedInversions"]["sig"], "|".join(f"{x:.3f}" for x in r["exploration"]["Wz"]),
                        "|".join(f"{p['lo']:.3f}" for p in r["exploration"]["pairs"]),
                        r["ref(참고만, measure20 기존)"].get("W_orig"), r["ref(참고만, measure20 기존)"].get("W_n0")])
    build_final({r["level"]: r["verdict"] for r in out_levels})
    print(json.dumps(dict(cnt), ensure_ascii=False))


def build_final(verdicts):
    check_prereg()
    spec_b = (SPEC / "levels_spec_v2.json").read_bytes()
    spec_levels = json.loads(spec_b)
    spec_by = {r["level"]: r for r in spec_levels}
    v21_by = {r["level"]: r for r in json.loads((V21 / "levels_spec_v2_1.json").read_bytes())}
    v22_by = {r["level"]: r for r in json.loads((V22 / "levels_spec_v2_2.json").read_bytes())}
    v22v = json.loads((V22 / "manifest.json").read_text())["levelVerdicts"]
    measured20 = sorted(int(x) for x in v22v)
    catalog = {e["level"]: e for e in json.loads(CATALOG.read_bytes())["levels"]}
    final, changes = [], []
    for r in spec_levels:
        L = r["level"]
        if L not in measured20:
            final.append(r)
            continue
        cv = verdicts.get(L)
        if cv == "확인PASS":
            rec = json.loads(json.dumps(v22_by[L]))
            rec["confirm12"] = {"verdict": cv, "hold": False, "adopted": "spec_v2_2", "prereg": pre_sha()}
        else:
            rec = json.loads(json.dumps(spec_by[L]))
            unev = cv is None and v22v[str(L)] == "평가불가"
            if cv is not None:
                reason = f"confirm12 {cv} — v2_2 변경 미적용(spec_v2 값 유지), holdLevels"
            elif unev:
                reason = "v2_2 평가불가 — spec_v2 값 유지, holdLevels 아님(unevaluableLevels, 사용자 결정 사항)"
            else:
                reason = f"v2_2 {v22v[str(L)]} — 이번 확인 범위 밖, spec_v2 값 유지(검증 아님), holdLevels"
            rec["confirm12"] = {"verdict": cv or f"대상아님(v2_2 {v22v[str(L)]})", "hold": not unev,
                                "unevaluable": unev, "adopted": "spec_v2", "reason": reason, "prereg": pre_sha()}
        final.append(rec)
        for field, *_ in ZONES:
            a, b, c, d = (spec_by[L]["fields"][field], v21_by[L]["fields"][field], v22_by[L]["fields"][field],
                          rec["fields"][field])
            pm1 = ""
            if field in PM1 and d:
                pm1 = d.split(",") != catalog[L][field].split(",")[:3]
            changes.append({"level": L, "field": field, "v2_2Verdict": v22v[str(L)],
                            "confirmVerdict": cv or "대상아님", "hold": rec["confirm12"]["hold"],
                            "spec_v2": a, "spec_v2_1": b, "spec_v2_2": c, "final": d,
                            "finalChangedVsV2": d != a, "finalChangedVsV2_2": d != c,
                            "pm1ServerPrefixMismatch": pm1})
    assert len(final) == len(spec_levels)
    for a, b in zip(spec_levels, final):
        assert a["level"] == b["level"]
        if a["level"] not in measured20:
            assert a == b, a["level"]
    (OUT / LEVELS_OUT).write_bytes(dump(final))
    with (OUT / "changes.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0]))
        w.writeheader()
        w.writerows(changes)
    with (OUT / "server_columns_final_confirm12.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds", "ddaHard2Seeds"])
        for r in final:
            w.writerow([r["id"]] + [r["fields"][fl] for fl in ("ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds",
                                                              "ddaHard2Seeds")])
    chk = verify_final(final, spec_levels, measured20, catalog)
    save(OUT / "verify_final.json", chk)
    if not chk["allOk"]:
        raise RuntimeError(f"verify_final allOk=false — manifest·SHA256SUMS 생성 중단: {chk}")
    vc = Counter(v for v in verdicts.values())
    spec_man = json.loads((SPEC / "manifest.json").read_bytes())
    hold_levels = sorted(r["level"] for r in final if r.get("confirm12", {}).get("hold"))
    unev_levels = sorted(r["level"] for r in final if r.get("confirm12", {}).get("unevaluable"))
    pm1_mis = sorted(f"L{r['level']}.{f}" for r in final for f in PM1
                     if r["fields"][f] and r["fields"][f].split(",") != catalog[r["level"]][f].split(",")[:3])
    assert pm1_mis == sorted(f"L{c['level']}.{c['field']}" for c in changes if c["pm1ServerPrefixMismatch"] is True)
    save(OUT / "manifest.json", {
        "id": "dda_seed_spec_v2_2_confirm12_20261022",
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": "검토 후 동기화 — 자동 교체 금지 (syncStatus pending_review). 서버·게임 카탈로그 자동 반영 금지. 업로드 안 함",
        "syncStatus": "pending_review", "notUploaded": True,
        "base": "spec_v2_3x4_20261022", "baseManifestSha256": SPEC_MANIFEST_SHA, "baseLevelsSha256": sha(spec_b),
        "supersedesForReview": {"spec_v2_2_variant4order_20261022": V22_MANIFEST_SHA,
                                "spec_v2_1_measure20_20261022": V21_MANIFEST_SHA,
                                "note": "v2_2 탐색 선정 → 독립 확인 측정 결과로 확인PASS 레벨만 채택"},
        "rule": "문서 51 / PREREG_confirm.json: 확인PASS 레벨만 v2_2 시드 채택. 확인 미확정·실패 + v2_2 미확정(확인 범위 밖) → "
                "spec_v2 값 + holdLevels. v2_2 평가불가 6 → spec_v2 값, unevaluableLevels(holdLevels 아님). 20레벨 외 spec_v2 동일",
        "prereg": pre_sha(), "rawRows": sha((OUT / "raw_rows.jsonl").read_bytes()),
        "newBotGames": sum(1 for _ in (OUT / "raw_rows.jsonl").open()) * GAMES,
        "verdictCounts": dict(vc),
        "levelVerdicts": {str(L): (verdicts.get(L) or f"대상아님(v2_2 {v22v[str(L)]})") for L in measured20},
        "adoptedV2_2Levels": sorted(L for L, v in verdicts.items() if v == "확인PASS"),
        "holdLevels": hold_levels, "unevaluableLevels": unev_levels,
        "changedFieldsVsV2": sum(1 for c in changes if c["finalChangedVsV2"]),
        "pm1ServerPrefixMismatch": pm1_mis,
        "fieldContract": spec_man["fieldContract"], "inputs": spec_man["inputs"],
        "levelsFile": LEVELS_OUT,
        "verify": {k: v for k, v in chk.items() if k != "detail"},
        "warning": "봇 기준(v2.4 규칙 정합, θ≤0.65) — 실유저 검증 아님. ±1 불일치 필드는 서버 5개 앞 3개 이관안과 맞지 않음",
    })
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name not in ("SHA256SUMS", "run.lock"))
    (OUT / "SHA256SUMS").write_text("".join(f"{sha(p.read_bytes())}  {p.name}\n" for p in files))
    print("manifest", sha((OUT / "manifest.json").read_bytes()), "sums", sha((OUT / "SHA256SUMS").read_bytes()))


def verify_final(final, spec_levels, measured20, catalog):
    from app.core import dda_seed_catalog_v2 as c2       # 읽기 전용 사용 (source_condition_hash)
    pm2 = {(int(r["level"]), r["dir"], r["randSeed"]): r for r in csv.DictReader((SPEC / "pm2_candidates.csv").open())}
    var = {(int(v["level"]), v["dir"], v["randSeed"]): v for v in csv.DictReader((RUN / "config/variants.csv").open())}
    meta = json.loads((MEAS / "maps_meta.json").read_text())
    sch_bad, assign_bad, n_seeds = [], [], 0
    for r in final:
        if r["level"] not in measured20:
            continue
        L, N = r["level"], r["N"]
        row0 = json.loads((RUN / f"out/t0base/level_{L}.json").read_bytes())["row"]
        want = catalog[L]["sourceConditionHash"]
        if c2.source_condition_hash(row0) != want or r["sourceConditionHash"] != want:
            sch_bad.append(L)
        for field, dr, dl, _ in ZONES:
            v = r["fields"][field]
            if not v:
                continue
            if r["useTileCount"][field] != N + dl:
                assign_bad.append([L, field, "useTileCount"])
            inv = {str(meta[str(L)][f"{field}:{c}"]["randSeed"]): c for c in range(1, 6)}
            src = var if field in PM1 else pm2
            toks = v.split(",")
            if len(toks) != 3:
                assign_bad.append([L, field, "count"])
            for i, s in enumerate(toks):
                n_seeds += 1
                c = inv.get(s)
                if c is None or meta[str(L)][f"{field}:{c}"]["useTileCount"] != N + dl:
                    assign_bad.append([L, field, s, "not_in_zone_candidates"])
                    continue
                lr = src.get((L, dr, s))
                if lr is None or int(lr["useTileCount"]) != N + dl or r["condSha256"][field][i] != lr["condSha256"]:
                    assign_bad.append([L, field, s, "cond/ledger"])
    seeds = [s for r in final for v in r["fields"].values() if v for s in v.split(",")]
    outside = [a["level"] for a, b in zip(spec_levels, final) if a["level"] not in measured20 and a != b]
    return {"sourceConditionHashMismatch": sch_bad, "assignBad": assign_bad, "seedsChecked20": n_seeds,
            "globalSeedDuplicates": len(seeds) - len(set(seeds)), "outside20DiffVsSpecV2": outside,
            "allOk": not (sch_bad or assign_bad or outside or len(seeds) != len(set(seeds)))}


def cmd_check_only():
    """읽기 전용 점검 — 파일 쓰기 0 (log/save 호출 없음). 입력 sha·PREREG 검사 + 발행 산출물 verify_final 재실행 + sha 불변."""
    res = {}
    check_inputs()
    res["inputsSha"] = "OK"
    check_prereg()
    res["prereg"] = f"OK {PREREG_SHA[:16]} targets == v2_2 선정값(144시드)"
    mb, sb = (OUT / "manifest.json").read_bytes(), (OUT / "SHA256SUMS").read_bytes()
    res["manifestSha"] = sha(mb)
    res["sumsSha"] = sha(sb)
    res["manifestUnchanged"] = sha(mb) == FINAL_MANIFEST_SHA
    res["sumsUnchanged"] = sha(sb) == FINAL_SUMS_SHA
    bad = []
    for line in sb.decode().splitlines():
        h, name = line.split(None, 1)
        if sha((OUT / name.strip()).read_bytes()) != h:
            bad.append(name.strip())
    res["sumsFileMismatch"] = bad
    man = json.loads(mb)
    lf = man["levelsFile"]
    final = json.loads((OUT / lf).read_bytes())
    spec_levels = json.loads((SPEC / "levels_spec_v2.json").read_bytes())
    measured20 = sorted(int(x) for x in json.loads((V22 / "manifest.json").read_text())["levelVerdicts"])
    catalog = {e["level"]: e for e in json.loads(CATALOG.read_bytes())["levels"]}
    chk = verify_final(final, spec_levels, measured20, catalog)
    res["verifyFinalRerun"] = chk
    res["verifyFinalMatchesStored"] = chk == json.loads((OUT / "verify_final.json").read_text())
    ok = (res["manifestUnchanged"] and res["sumsUnchanged"] and not bad and chk["allOk"]
          and res["verifyFinalMatchesStored"])
    res["allOk"] = ok
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("check-only", "--check-only"):
        sys.exit(cmd_check_only())
    OUT.mkdir(parents=True, exist_ok=True)
    sys.exit({"prereg": cmd_prereg, "run": cmd_run, "report": cmd_report}.get(cmd, lambda: sys.exit(__doc__))() or 0)
