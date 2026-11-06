#!/usr/bin/env python3
"""DDA 시드 v2_2 — 변형 4구간(E2>E1>H1>H2) 정렬 기준 오프라인 재선별 (2026-10-22, 문서 50).

새 봇 측정 없음. 입력은 문서 49 측정자료(raw_rows.jsonl)만 재집계. 서버·게임·Unity 접근 없음.
기준 = spec_v2_2_variant4order_20261022/PREREG_v2_2.json (sha 고정, 결과 계산 전 작성).
기존 산출물(spec_v2_3x4 / spec_v2_1_measure20 / spec_v2_measure20)은 읽기만.

명령 (cd backend && venv/bin/python scripts/dda_variant4_order_reselect_20261022.py <cmd>)
  select : 조합 탐색·선정 → results_levels.json, results_combos_top.csv, levels_spec_v2_2.json,
           server_columns_spec_v2_2.csv, changes.csv, manifest.json, SHA256SUMS
  verify : 정합 검증 — 기존 verify 스크립트(dda_seed_spec_v2_verify_20261022)를 스테이징 폴더 대상으로 실행
           (원 스크립트·spec_v2 폴더 수정 없음) + dda_seed_catalog_v2.load_spec / source_condition_hash
           + 구간 배정 정합(각 필드 시드 ∈ 그 필드 N±k 측정 후보, 150판 측정)
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import itertools
import json
import math
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DS = BACKEND / "data/dda_seeds"
MEAS = DS / "spec_v2_measure20_20261022"
SPEC = DS / "spec_v2_3x4_20261022"
V21 = DS / "spec_v2_1_measure20_20261022"
OUT = DS / "spec_v2_2_variant4order_20261022"
RUN = BACKEND / "data/pv_sandbox/dda_t0_all_20261020/runs/run_20261020_130623"
CATALOG = DS / "dda_t0_seed_catalog.v1.json"

PREREG_SHA = "897a203508ee716ef7008077adbff0f914a6f71f6ad1f6e5406941d65e1bc29a"
RAW_SHA = "b805f57b533b435693954c2ceb1fb7a40913cdf6f0be241bf771081fbe10cd18"
MAPS_META_SHA = "44f0945967d55c841a1cd530760942a32e40572832c9f159fd073184faec771d"
SPEC_MANIFEST_SHA = "1a8b57da10c3d61b96659671ba32c220d9e53e873899f7851e46f92f058344ba"
V21_MANIFEST_SHA = "5c1cae7c99a9fa1dea48935a2f31fc3fe149a579860477dc778bde40b0dcfc5b"

ZONES = [("ddaEasy2Seeds", "easy2", -2), ("ddaEasySeeds", "easy", -1), ("ddaHardSeeds", "hard", +1),
         ("ddaHard2Seeds", "hard2", +2)]                  # 쉬움 → 어려움 (기대 W 내림차순)
PM1 = ("ddaEasySeeds", "ddaHardSeeds")
THETAS = (0.29, 0.47, 0.65)
GAMES = 50
NC = 150                                                  # 후보당 3θ 합산 판수
Z95 = 1.959964
LAMBDA = 0.02
FLOOR, CEIL = 0.05, 0.95
LEVELS_FILE = "levels_spec_v2_2.json"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()


def save(p, o):
    p.write_bytes(json.dumps(o, ensure_ascii=False, indent=1).encode())


# ── 문서 49 스크립트(dda_spec_v2_measure20_20261022.py)의 wilson/newcombe 와 같은 식 (임포트 시 cs_shuffle 로드 회피용 복사)
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


def check_inputs():
    pre = OUT / "PREREG_v2_2.json"
    assert sha(pre.read_bytes()) == PREREG_SHA, "PREREG sha mismatch"
    assert sha((MEAS / "raw_rows.jsonl").read_bytes()) == RAW_SHA, "raw_rows sha mismatch"
    assert sha((MEAS / "maps_meta.json").read_bytes()) == MAPS_META_SHA, "maps_meta sha mismatch"
    assert sha((SPEC / "manifest.json").read_bytes()) == SPEC_MANIFEST_SHA, "spec_v2 manifest mismatch"
    assert sha((V21 / "manifest.json").read_bytes()) == V21_MANIFEST_SHA, "spec_v2_1 manifest mismatch"
    return json.loads(pre.read_text())


def load_agg():
    """(L, map) → {θ: (wins, n)}. 문서 49 본 측정(61M 시드)과 N±0(63M) 모두 raw_rows 에 있음."""
    agg = {}
    for line in (MEAS / "raw_rows.jsonl").open():
        r = json.loads(line)
        d = agg.setdefault((r["level"], r["map"]), {})
        assert r["theta"] not in d, ("dup", r["level"], r["map"], r["theta"])
        assert len(r["perGame"]) == r["n"] and r["perGame"].count("1") == r["wins"]
        d[r["theta"]] = (r["wins"], r["n"])
    return agg


def pair_status(we, wh, n):
    g = (we - wh) / n
    lo, hi = newcombe(we, n, wh, n)
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
    return g, lo, hi, st


def eval_combo(cw, ct, combo):
    """combo = (E2 cands, E1 cands, H1 cands, H2 cands). cw[z][c] = 150판 wins, ct[z][c][θi] = wins at θ."""
    wz = [sum(cw[z][c] for c in combo[z]) for z in range(4)]
    pairs = [pair_status(wz[i], wz[i + 1], 3 * NC) for i in range(3)]
    a = all(p[0] > 0 for p in pairs)
    b = all(p[3] == "유의정렬" for p in pairs)
    c = all(min(cw[i][x] for x in combo[i]) > max(cw[i + 1][x] for x in combo[i + 1]) for i in range(3))
    dk = 0
    for ti in range(3):
        wt = [sum(ct[z][x][ti] for x in combo[z]) for z in range(4)]
        dk += all(wt[i] > wt[i + 1] for i in range(3))
    tier = 4 if (b and c) else 3 if b else 2 if a else 1
    rng = [(max(cw[z][x] for x in combo[z]) - min(cw[z][x] for x in combo[z])) / NC for z in range(4)]
    mean_rng = sum(rng) / 4
    min_g = min(p[0] for p in pairs)
    C = sum(len(set(combo[z]) - {1, 2, 3}) for z in range(4))
    J = mean_rng - min_g + LAMBDA * C
    return {"tier": tier, "a": a, "b": b, "c": c, "dK": dk, "J": J, "meanRange": mean_rng, "minGap": min_g,
            "changed": C, "Wz": [w / (3 * NC) for w in wz], "range": rng,
            "pairs": [{"g": p[0], "lo": p[1], "hi": p[2], "st": p[3]} for p in pairs]}


def seeds_of(meta, L, field, cands):
    return ",".join(str(meta[str(L)][f"{field}:{c}"]["randSeed"]) for c in cands)


def cands_of(meta, L, field, value):
    if not value:
        return None
    inv = {str(meta[str(L)][f"{field}:{c}"]["randSeed"]): c for c in range(1, 6)}
    toks = value.split(",")
    if not all(t in inv for t in toks):
        return "foreign"
    return tuple(sorted(inv[t] for t in toks))


def grade_label(e):
    if e is None:
        return "-"
    s = "b" if e["b"] else ("e" if e["a"] else "-")
    if e["a"]:
        s = "a+" + s
    if e["c"]:
        s += "+c"
    return f"{s} (d {e['dK']}/3)"


def cmd_select():
    pre = check_inputs()
    if (OUT / LEVELS_FILE).exists():
        raise SystemExit(f"{OUT / LEVELS_FILE} exists — 재실행 금지(산출물 고정)")
    agg = load_agg()
    meta = json.loads((MEAS / "maps_meta.json").read_text())
    n0meta = json.loads((MEAS / "maps_meta_n0.json").read_text())
    spec_b = (SPEC / "levels_spec_v2.json").read_bytes()
    spec_levels = json.loads(spec_b)
    spec_by = {r["level"]: r for r in spec_levels}
    v21_by = {r["level"]: r for r in json.loads((V21 / "levels_spec_v2_1.json").read_bytes())}
    pm2 = {(int(r["level"]), r["dir"], int(r["cand"])): r for r in csv.DictReader((SPEC / "pm2_candidates.csv").open())}
    var = {(int(v["level"]), v["dir"], int(v["cand"])): v for v in csv.DictReader((RUN / "config/variants.csv").open())}
    catalog = {e["level"]: e for e in json.loads(CATALOG.read_bytes())["levels"]}
    combos3 = list(itertools.combinations(range(1, 6), 3))
    results, top_rows, changes = [], [], []
    t0 = time.time()
    for li, L in enumerate(pre_levels(pre)):
        N = spec_by[L]["N"]
        cw, ct, missing = [], [], []
        for field, _, dl in ZONES:
            cw.append({}), ct.append({})
            for c in range(1, 6):
                k = f"{field}:{c}"
                m = meta[str(L)][k]
                assert m["field"] == field and m["cand"] == c and m["useTileCount"] == N + dl, (L, k)
                d = agg.get((L, k), {})
                if sorted(d) != list(THETAS) or any(d[t][1] != GAMES for t in THETAS):
                    missing.append(k)
                    continue
                cw[-1][c] = sum(d[t][0] for t in THETAS)
                ct[-1][c] = [d[t][0] for t in THETAS]
        ref = {}
        if (L, "orig") in agg:
            ref["W_orig"] = sum(v[0] for v in agg[(L, "orig")].values()) / NC
        n0k = [k for k, c in n0meta[str(L)].items() if c.get("assignStatus") == "PASS" and (L, k) in agg]
        if n0k:
            ref["W_n0"] = sum(sum(v[0] for v in agg[(L, k)].values()) for k in n0k) / (NC * len(n0k))
        rec = {"level": L, "N": N, "ref(참고만)": ref,
               "candW": {ZONES[z][0]: {str(c): cw[z][c] / NC for c in cw[z]} for z in range(4)},
               "candWtheta": {ZONES[z][0]: {str(c): ct[z][c] for c in ct[z]} for z in range(4)}}
        if missing:
            rec.update(verdict="미측정", missing=missing)
            results.append(rec)
            continue
        best, ev_all, n_tier = None, [], Counter()
        v2sel = (1, 2, 3)
        v21c = [cands_of(meta, L, ZONES[z][0], v21_by[L]["fields"][ZONES[z][0]]) for z in range(4)]
        for combo in itertools.product(combos3, repeat=4):
            e = eval_combo(cw, ct, combo)
            n_tier[e["tier"]] += 1
            ov2 = sum(len(set(combo[z]) & set(v2sel)) for z in range(4))
            ov21 = sum(len(set(combo[z]) & set(v21c[z])) for z in range(4) if isinstance(v21c[z], tuple))
            key = (-e["tier"], round(e["J"], 12), -ov2, -ov21, tuple(x for cc in combo for x in cc))
            ev_all.append((key, combo, e))
            if best is None or key < best[0]:
                best = (key, combo, e)
        ev_all.sort(key=lambda x: x[0])
        for rank, (key, combo, e) in enumerate(ev_all[:10], 1):
            top_rows.append({"level": L, "rank": rank, "tier": e["tier"], "J": round(e["J"], 5),
                             "E2": combo[0], "E1": combo[1], "H1": combo[2], "H2": combo[3],
                             "Wz": [round(w, 4) for w in e["Wz"]], "minGap": round(e["minGap"], 4),
                             "meanRange": round(e["meanRange"], 4), "changed": e["changed"], "dK": e["dK"],
                             "pairSt": "|".join(p["st"] for p in e["pairs"])})
        _, combo, e = best
        floorceil = []
        for i in range(3):
            if max(cw[i].values()) / NC <= FLOOR:
                floorceil.append(f"{ZONES[i][0]}~{ZONES[i + 1][0]}:바닥(쉬운쪽 5후보 최고≤{FLOOR})")
            if min(cw[i + 1].values()) / NC >= CEIL:
                floorceil.append(f"{ZONES[i][0]}~{ZONES[i + 1][0]}:천장(어려운쪽 5후보 최저≥{CEIL})")
        if e["tier"] >= 3:
            verdict = "선정"
        elif floorceil:
            verdict = "평가불가"
        elif e["tier"] == 2:
            verdict = "미확정"
        else:
            verdict = "부족"
        e_v2 = eval_combo(cw, ct, (v2sel,) * 4)
        e_v21 = eval_combo(cw, ct, tuple(v21c)) if all(isinstance(x, tuple) for x in v21c) else None
        rec.update(verdict=verdict, bestTier=e["tier"], tierCounts={str(k): v for k, v in sorted(n_tier.items())},
                   floorCeil=floorceil, best={"combo": {ZONES[z][0]: list(combo[z]) for z in range(4)}, **e},
                   grade=grade_label(e), specV2Eval={**e_v2, "grade": grade_label(e_v2)},
                   specV21Eval=({**e_v21, "grade": grade_label(e_v21)} if e_v21 else
                                {"note": "v2_1 에 보류(\"\") 필드 있음 → 4구간 평가 불가",
                                 "cands": [list(x) if isinstance(x, tuple) else x for x in v21c]}))
        # 필드 출력
        out_fields = {}
        for z, (field, dr, dl) in enumerate(ZONES):
            if verdict in ("선정", "미확정"):
                cs = combo[z]
                val = seeds_of(meta, L, field, cs)
                src = pm2 if field not in PM1 else var
                conds = [src[(L, dr, c)]["condSha256"] for c in cs]
                for c in cs:
                    assert str(meta[str(L)][f"{field}:{c}"]["randSeed"]) == src[(L, dr, c)]["randSeed"]
            elif verdict == "부족":
                cs, val, conds = None, "", []
            else:                                    # 평가불가 / 미측정 → spec_v2 그대로
                cs, val, conds = (1, 2, 3), spec_by[L]["fields"][field], spec_by[L]["condSha256"][field]
                assert val == seeds_of(meta, L, field, (1, 2, 3))
            out_fields[field] = (cs, val, conds)
        rec["output"] = {f: {"cands": (list(v[0]) if v[0] else []), "seeds": v[1]} for f, v in out_fields.items()}
        results.append(rec)
        print(f"[{time.time() - t0:5.1f}s] {li + 1:2d}/20 L{L}: {verdict} tier{e['tier']} J={e['J']:.4f} "
              f"Wz={[round(w, 3) for w in e['Wz']]} {grade_label(e)}", flush=True)

    # ── 새 버전 산출물 (spec_v2 기반, 20레벨 4필드만)
    levels = json.loads(spec_b)
    by = {r["level"]: r for r in levels}
    for rec in results:
        L = rec["level"]
        r = by[L]
        for field, dr, dl in ZONES:
            o = rec.get("output", {}).get(field)
            if o is None:
                continue
            new = o["seeds"]
            if rec["verdict"] == "부족":
                r["holds"][field] = "v2_2_variant4order_insufficient(5후보 안 점추정 정렬 불가)"
                r["condSha256"][field] = []
            elif new != r["fields"][field]:
                src = pm2 if field not in PM1 else var
                r["condSha256"][field] = [src[(L, dr, c)]["condSha256"] for c in o["cands"]]
            r["fields"][field] = new
            old2, old21 = spec_by[L]["fields"][field], v21_by[L]["fields"][field]
            pm1_mismatch = field in PM1 and new != "" and new.split(",") != catalog[L][field].split(",")[:3]
            changes.append({"level": L, "field": field, "verdict": rec["verdict"],
                            "spec_v2": old2, "spec_v2_1": old21, "spec_v2_2": new,
                            "v2_2_cands": "|".join(map(str, o["cands"])),
                            "changedVsV2": new != old2, "changedVsV2_1": new != old21,
                            "pm1ServerPrefixMismatch": pm1_mismatch if field in PM1 else ""})
        r["variant4order"] = {"verdict": rec["verdict"], "bestTier": rec.get("bestTier"), "grade": rec.get("grade"),
                              "prereg": PREREG_SHA}
        if rec["verdict"] == "부족":
            r["status"] = "partial" if any(r["fields"].values()) else "hold_v2_2"
    OUT.mkdir(exist_ok=True)
    save(OUT / "results_levels.json", {"prereg": PREREG_SHA, "rawRows": RAW_SHA, "label": "봇 기준(v2.4) — 실유저 아님",
                                       "levels": results})
    with (OUT / "results_combos_top.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(top_rows[0]))
        w.writeheader()
        w.writerows(top_rows)
    (OUT / LEVELS_FILE).write_bytes(dump(levels))
    with (OUT / "server_columns_spec_v2_2.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds", "ddaHard2Seeds"])
        for r in levels:
            w.writerow([r["id"]] + [r["fields"][fl] for fl in ("ddaEasySeeds", "ddaHardSeeds", "ddaEasy2Seeds",
                                                              "ddaHard2Seeds")])
    with (OUT / "changes.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0]))
        w.writeheader()
        w.writerows(changes)
    # 20레벨 밖 차이 0 확인
    for a, b in zip(spec_levels, levels):
        if a["level"] not in set(pre_levels(pre)):
            assert a == b, a["level"]
    seeds = [s for r in levels for v in r["fields"].values() if v for s in v.split(",")]
    assert len(seeds) == len(set(seeds)), "global seed duplicate"
    spec_man = json.loads((SPEC / "manifest.json").read_bytes())
    vc = Counter(r["verdict"] for r in results)
    save(OUT / "manifest.json", {
        "id": "dda_seed_spec_v2_2_variant4order_20261022",
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": "검토 후 동기화 — 자동 교체 금지 (syncStatus pending_review). 게임 카탈로그·서버 자동 반영 금지. 업로드 안 함",
        "syncStatus": "pending_review", "notUploaded": True,
        "base": "spec_v2_3x4_20261022", "baseManifestSha256": SPEC_MANIFEST_SHA, "baseLevelsSha256": sha(spec_b),
        "supersedesForReview": {"spec_v2_1_measure20_20261022": V21_MANIFEST_SHA,
                                "note": "옛 기준(원본 대비) 결과 — 보존. v2_2 는 v2_1 변경을 승계하지 않음"},
        "rule": "문서 50 / PREREG_v2_2.json: 변형 4구간 E2>E1>H1>H2 정렬(원본·N±0 참고만), 사후 기준 변경(사용자 결정)",
        "prereg": PREREG_SHA, "rawRows": RAW_SHA, "newBotGames": 0,
        "verdictCounts": dict(vc),
        "levelVerdicts": {str(r["level"]): r["verdict"] for r in results},
        "changedFieldsVsV2": sum(1 for c in changes if c["changedVsV2"]),
        "pm1ServerPrefixMismatch": [f"L{c['level']}.{c['field']}" for c in changes if c["pm1ServerPrefixMismatch"] is True],
        "fieldContract": spec_man["fieldContract"], "inputs": spec_man["inputs"],
        "warning": "봇 기준(v2.4 규칙 정합, θ≤0.65) — 실유저 검증 아님. 같은 데이터에서 고른 조합(선택 편향) — 확인 측정 전 탐색 결과. "
                   "±1 불일치 필드는 서버 5개 앞 3개 이관안과 맞지 않음",
    })
    write_sums()
    print(json.dumps(dict(vc), ensure_ascii=False), "changedVsV2", sum(1 for c in changes if c["changedVsV2"]))
    print("manifest", sha((OUT / "manifest.json").read_bytes()))


def pre_levels(pre):
    return [int(x) for x in pre["scope"].split("(")[1].split(")")[0].split(",")]


def write_sums():
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (OUT / "SHA256SUMS").write_text("".join(f"{sha(p.read_bytes())}  {p.name}\n" for p in files))


def cmd_verify():
    """정합 검증. 기존 verify 스크립트는 OUT(spec_v2 폴더)에 쓰므로 직접 실행하지 않고, 모듈의 OUT 만 스테이징 폴더로
    바꿔 같은 main() 을 돌린다(원 파일·spec_v2 폴더 무수정). 스테이징 = OUT/verify_stage (levels_spec_v2.json 이름으로 v2_2 복사,
    pm1/pm2 csv 는 v2_2 선정으로 selected 재표시한 복사)."""
    check_inputs()
    levels_b = (OUT / LEVELS_FILE).read_bytes()
    levels = json.loads(levels_b)
    meta = json.loads((MEAS / "maps_meta.json").read_text())
    agg = load_agg()
    stage = OUT / "verify_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    (stage / "levels_spec_v2.json").write_bytes(levels_b)
    chosen = {(r["level"], f, s) for r in levels for f, v in r["fields"].items() if v for s in v.split(",")}
    dirs = {"easy": "ddaEasySeeds", "hard": "ddaHardSeeds", "easy2": "ddaEasy2Seeds", "hard2": "ddaHard2Seeds"}
    for name, fcol in (("pm1_selection.csv", "field"), ("pm2_candidates.csv", "dir")):
        rows = list(csv.DictReader((SPEC / name).open()))
        for r in rows:
            f = r[fcol] if fcol == "field" else dirs[r["dir"]]
            r["selected"] = str((int(r["level"]), f, r["randSeed"]) in chosen)
        with (stage / name).open("w", newline="") as fo:
            w = csv.DictWriter(fo, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    spec_sums_before = sha((SPEC / "SHA256SUMS").read_bytes())
    vpath = BACKEND / "scripts/dda_seed_spec_v2_verify_20261022.py"
    spec_ = importlib.util.spec_from_file_location("v2verify", vpath)
    vm = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(vm)
    vm.OUT = stage
    vm.main()
    pre = json.loads((stage / "verify/precheck.json").read_text())
    assert sha((SPEC / "SHA256SUMS").read_bytes()) == spec_sums_before, "spec_v2 SHA256SUMS changed!"

    # catalog_v2: sourceConditionHash 재계산 + load_spec (±1 접두 검사 포함)
    sys.path.insert(0, str(BACKEND))
    from app.core import dda_seed_catalog_v2 as c2
    catalog = {e["level"]: e for e in json.loads(CATALOG.read_bytes())["levels"]}
    sch_bad = []
    for r in levels:
        if r["catalogStatus"] != "candidate":
            continue
        row0 = json.loads((RUN / f"out/t0base/level_{r['level']}.json").read_bytes())["row"]
        want = catalog[r["level"]]["sourceConditionHash"]
        if c2.source_condition_hash(row0) != want or r["sourceConditionHash"] != want:
            sch_bad.append(r["level"])
    c2.SPEC_LEVELS_FILE = LEVELS_FILE
    try:
        c2.load_spec(str(OUT), sha((OUT / "manifest.json").read_bytes()), sha((OUT / "SHA256SUMS").read_bytes()))
        load_spec = "PASS"
    except Exception as ex:  # noqa: BLE001
        load_spec = f"FAIL: {ex}"

    # 구간 배정 정합: 측정 20레벨 각 필드 시드 ∈ 그 필드(N±k) 측정 후보 cand1~5, 150판 측정, useTileCount 일치
    res = json.loads((OUT / "results_levels.json").read_text())
    tested = {r["level"] for r in res["levels"]}
    assign_bad, n_checked = [], 0
    for r in levels:
        if r["level"] not in tested:
            continue
        L, N = r["level"], r["N"]
        for field, _, dl in ZONES:
            v = r["fields"][field]
            if not v:
                continue
            if r["useTileCount"][field] != N + dl:
                assign_bad.append((L, field, "useTileCount"))
            inv = {str(meta[str(L)][f"{field}:{c}"]["randSeed"]): c for c in range(1, 6)}
            for s in v.split(","):
                n_checked += 1
                c = inv.get(s)
                if c is None:
                    assign_bad.append((L, field, s, "not_in_field_candidates"))
                    continue
                m = meta[str(L)][f"{field}:{c}"]
                d = agg.get((L, f"{field}:{c}"), {})
                if m["useTileCount"] != N + dl or sum(x[1] for x in d.values()) != NC:
                    assign_bad.append((L, field, s, "meta/games"))
    # 20레벨 밖 spec_v2 동일
    spec_levels = json.loads((SPEC / "levels_spec_v2.json").read_bytes())
    outside_diff = [a["level"] for a, b in zip(spec_levels, levels) if a["level"] not in tested and a != b]
    expected_errs = {k: v for k, v in pre["errors"].items()}
    out = {"verifyScript": {"path": str(vpath.relative_to(BACKEND)), "sha256": sha(vpath.read_bytes()),
                            "ranOn": "verify_stage (모듈 OUT 치환, 원 파일 무수정)", "errors": expected_errs,
                            "errorLevels": pre["errorLevels"], "globalUniqueSeeds": pre["globalUniqueSeeds"],
                            "byStatus": pre["byStatus"]},
           "specV2SumsUnchanged": True,
           "sourceConditionHashMismatchLevels": sch_bad,
           "catalogV2LoadSpec": load_spec,
           "assignCheck": {"seedsChecked": n_checked, "bad": assign_bad},
           "outsideMeasuredDiffVsSpecV2": outside_diff}
    save(OUT / "verify_v2_2.json", out)
    write_sums()
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"select": cmd_select, "verify": cmd_verify}.get(cmd, lambda: sys.exit(__doc__))()
