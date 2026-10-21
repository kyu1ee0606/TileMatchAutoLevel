#!/usr/bin/env python3
"""DDA 전레벨(L32+) t0 준비 — 오프라인 사본·설정·순수 구조 검증 (2026-10-20).

입력(읽기 전용): sp_meowsgarden 출시 커밋의 빌드 내장 GBoost 파일을 `git show <commit>:<path>` 로만 읽는다.
  - b741f6a3 = Android 1.1.0 / iOS 2.1.0, a2229a5d = Android 1.0.162 (문서 40·45 의 버전→커밋 추론. 런타임 해시 직접 증명 아님)
출력: backend/data/pv_sandbox/dda_t0_all_20261020/ 아래만 쓴다.
  live_copy/<commit>/  복호 사본(levels 테이블·unlock_effect·levelmap 샤드) + 원본 암호 파일 sha256
  out/orig/level_N.json     원본 행(테이블 row) + 원본 map (키·셀 순서 그대로)
  out/t0base/level_N.json   같은 행 + 일반 타일만 t0 로 바꾼 map (순서·위치·층·기믹·key·메타 보존)
  config/variants.csv|json  레벨별 easy 5 + hard 5 설정 (useTileCount, randSeed 만; 맵 복사 없음)
  exceptions.csv, manifest.json, SHA256SUMS
봇 측정·솔버·난이도 탐색 없음. 검증 = 저장 정합(구조)만. 배정 후 정합/솔버블/난이도 = 미검증.
재현: cd backend && .venv/bin/python scripts/dda_t0_all_prepare_20261020.py
"""
import csv
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
sys.path.insert(0, str(BACKEND))
from pv_scan_shards import decrypt_shard_file  # noqa: E402
from app.core.pv.canonical import canonical_map  # noqa: E402

GAME = "/Users/casualdev/sp_meowsgarden"
OUT = BACKEND / "data/pv_sandbox/dda_t0_all_20261020"
PKG = BACKEND / "data/pv_sandbox/pv_20261002_live3/dda_v24confirm_20261019/package_20261020_0544"
LIVE3 = BACKEND / "data/pv_sandbox/pv_20261002_live3/source.json"
BASE_COMMIT = "b741f6a3"          # Android 1.1.0 · iOS 2.1.0
OLD_COMMIT = "a2229a5d"           # Android 1.0.162
COMMIT_PLATFORMS = {BASE_COMMIT: ["android 1.1.0", "ios 2.1.0"], OLD_COMMIT: ["android 1.0.162"]}
MIN_LEVEL = 32
N_CAND = 5
SEED_RNG_KEY = "dda_t0_all_20261020/v1"
SEED_LO, SEED_HI = 1_100_000_000, 1_199_999_999   # 신규 대역 (양의 Int32, 기존 5M~21.6M+ 대역과 비중첩)
NORMAL_RE = re.compile(r"^t([1-9]|1[0-5])$")
RUN_ID = time.strftime("run_%Y%m%d_%H%M%S")
RUN = OUT / "runs" / RUN_ID          # 실행마다 분리: 이전 run 산출물과 섞이지 않음
LOG = RUN / "logs/run.log"
CUTOFF_HHMM = "13:40"                # 2026-10-20 KST: 이후 신규 변환 중단, 패키징만
_last_check = [0.0]


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def past_cutoff():
    return time.strftime("%Y-%m-%d %H:%M") >= "2026-10-20 " + CUTOFF_HHMM


def resource_check(tag):
    """swap free<500MB 또는 kern.memorystatus_vm_pressure_level==4(critical) → 중단 신호(True)."""
    _last_check[0] = time.time()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                         capture_output=True, text=True).stdout.strip()
    sw = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    log(f"[resource:{tag}] pressure_level={lvl} | {sw}")
    m = re.search(r"free = ([\d.]+)M", sw)
    if lvl == "4" or (m and float(m.group(1)) < 500):
        log("[resource] critical or swap free < 500MB -> stop new work")
        return True
    return False


def resource_due():
    return time.time() - _last_check[0] > 60


def git_show(commit, path):
    r = subprocess.run(["git", "-C", GAME, "show", f"{commit}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def gb_path(key):
    return f"Assets/StreamingAssets/GBoost/a{hashlib.md5(key.encode()).hexdigest()}.txt"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def load_commit(commit):
    """커밋의 levels/unlock_effect 테이블과 levelmap 샤드를 복호해 사본 저장."""
    d = OUT / "live_copy" / commit
    d.mkdir(parents=True, exist_ok=True)
    raw_sha, maps, tables = {}, {}, {}
    for key in ["levels", "unlock_effect"] + [f"levelmap_level_{i}" for i in range(30)]:
        b = git_show(commit, gb_path(key))
        if b is None:
            continue
        raw_sha[key] = {"path": gb_path(key), "sha256_encrypted": sha(b)}
        obj = decrypt_shard_file(b)
        (d / f"{key}.json").write_bytes(dump(obj))
        if key.startswith("levelmap_"):
            maps.update(obj)
        else:
            ks = obj["__keys"]
            tables[key] = {str(r[ks.index("id")]): {ks[i]: r[i] for i in range(min(len(ks), len(r)))}
                           for r in obj["__vals"]}
    (d / "SOURCE.json").write_bytes(dump({"commit": commit, "platforms": COMMIT_PLATFORMS[commit],
                                          "files": raw_sha, "readVia": "git show (no checkout)"}))
    return maps, tables, raw_sha


def iter_cells(m):
    for lk, lv in m.items():
        if lk.startswith("layer_") and isinstance(lv, dict):
            tiles = lv.get("tiles", {})
            if isinstance(tiles, dict):   # 빈 층은 "tiles": [] 로 저장됨 → 그대로 보존, 순회 생략
                for ck, cell in tiles.items():
                    yield lk, ck, cell


def nonempty_list_layers(m):
    """tiles 가 비어 있지 않은 list 인 층(미지원 형태) → 보류 사유."""
    return [lk for lk, lv in m.items() if lk.startswith("layer_") and isinstance(lv, dict)
            and isinstance(lv.get("tiles"), list) and lv["tiles"]]


def is_key(tid, eff):
    """DB_Level.cs:238 isKeyTile 그대로: t16 / id key / effect key."""
    return tid == "t16" or str(tid).lower() == "key" or str(eff).lower() == "key"


def analyze(m):
    """원본 map 분석: 일반 distinct(내부 명시 포함·key 제외), 개수, 문제."""
    cnt, keys, issues = Counter(), Counter(), []
    t0_orig = 0
    total = 0
    for lk, ck, cell in iter_cells(m):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        if tid.startswith("stack_") or tid.startswith("craft_"):
            info = cell[2] if len(cell) > 2 else None
            if not isinstance(info, list) or not info:
                issues.append(f"container_no_info:{lk}/{ck}")
                continue
            n = int(info[0])
            total += n
            inner = info[1] if len(info) > 1 else ""
            if inner:
                ids = inner.split("_")
                if len(ids) != n:
                    issues.append(f"inner_count_mismatch:{lk}/{ck}")   # 로더 t0 폴백 = 정상 변환 아님
                    continue
                for x in ids:
                    if is_key(x, ""):
                        keys["inner_key"] += 1
                    elif NORMAL_RE.match(x):
                        cnt[x] += 1
                    elif x == "t0":
                        t0_orig += 1
                    else:
                        issues.append(f"inner_unknown_id:{x}")
            else:
                t0_orig += n
            continue
        total += 1
        if is_key(tid, eff):
            keys[tid if NORMAL_RE.match(tid) else "key"] += 1
        elif NORMAL_RE.match(tid):
            cnt[tid] += 1
        elif tid == "t0":
            t0_orig += 1
        else:
            issues.append(f"unknown_tile:{tid}")
    return cnt, keys, t0_orig, total, issues


def to_t0(m):
    """일반 타일 id 만 t0. 키/셀/레이어 순서·기믹·컨테이너 루트/방향/N 보존."""
    out = json.loads(json.dumps(m))   # 순서 보존 깊은 복사
    for lk, ck, cell in iter_cells(out):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        if tid.startswith("stack_") or tid.startswith("craft_"):
            info = cell[2]
            if len(info) > 1 and info[1]:
                info[1] = "_".join(x if (is_key(x, "") or not NORMAL_RE.match(x)) else "t0"
                                   for x in info[1].split("_"))
        elif NORMAL_RE.match(tid) and not is_key(tid, eff):
            cell[0] = "t0"
    return out


def order_sig(m):
    return [(lk, list(lv["tiles"].keys()) if isinstance(lv.get("tiles"), dict) else lv.get("tiles"))
            for lk, lv in m.items()
            if lk.startswith("layer_") and isinstance(lv, dict)]


def struct_sig(m):
    """t0화 무관 구조 서명: 위치·층·기믹·컨테이너 루트/N·key 위치."""
    sig = []
    for lk, ck, cell in iter_cells(m):
        tid, eff = cell[0], cell[1] if len(cell) > 1 else ""
        norm = "N" if (NORMAL_RE.match(tid) and not is_key(tid, eff)) or tid == "t0" else tid
        extra = None
        if len(cell) > 2:
            info = cell[2]
            inner = [("N" if (NORMAL_RE.match(x) or x == "t0") and not is_key(x, "") else x)
                     for x in (info[1].split("_") if len(info) > 1 and info[1] else [])]
            extra = (info[0], inner)
        sig.append((lk, ck, norm, eff, json.dumps(extra)))
    meta = {k: v for k, v in m.items() if not k.startswith("layer_")}
    lmeta = {lk: {k: v for k, v in lv.items() if k != "tiles"} for lk, lv in m.items()
             if lk.startswith("layer_") and isinstance(lv, dict)}
    return json.dumps([sig, meta, lmeta])


def canon_sha(level_json):
    """af_level_metrics._map_hashes 와 같은 canonical sha256 (LIVE3 비교용)."""
    return hashlib.sha256(json.dumps(canonical_map(level_json), separators=(",", ":")).encode()).hexdigest()


def toint(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def main():
    if resource_check("start") or past_cutoff():
        log("start blocked (resource/deadline)")
        return
    maps_b, tabs_b, raw_b = load_commit(BASE_COMMIT)
    log(f"loaded {BASE_COMMIT}: maps={len(maps_b)} levels_rows={len(tabs_b.get('levels', {}))}")
    resource_check("after_base")
    maps_a, tabs_a, raw_a = load_commit(OLD_COMMIT)
    log(f"loaded {OLD_COMMIT}: maps={len(maps_a)} levels_rows={len(tabs_a.get('levels', {}))}")
    rows_b, rows_a = tabs_b["levels"], tabs_a["levels"]

    # 플랫폼(커밋) 차이: map 바이트 + 행
    plat_diff = []
    for k in sorted(set(maps_b) | set(maps_a), key=lambda s: int(s.split("_")[1])):
        L = int(k.split("_")[1])
        mb, ma = maps_b.get(k), maps_a.get(k)
        rb, ra = rows_b.get(k), rows_a.get(k)
        if mb is None or ma is None:
            plat_diff.append({"level": L, "kind": "missing_in_" + (OLD_COMMIT if ma is None else BASE_COMMIT)})
            continue
        dm = dump(mb) != dump(ma)
        dr = [c for c in sorted(set(rb or {}) | set(ra or {})) if (rb or {}).get(c) != (ra or {}).get(c)]
        if dm or dr:
            plat_diff.append({"level": L, "kind": "map" if dm else "row", "rowCols": dr})
    log(f"platform diffs: {len(plat_diff)} (L>={MIN_LEVEL}: {sum(1 for d in plat_diff if d['level'] >= MIN_LEVEL)})")

    # LIVE3 에디터 스냅샷 대비 (참고용)
    live3 = {}
    try:
        src = json.loads(LIVE3.read_text())
        for it in src["levels"]:
            n = it.get("meta", {}).get("level_number")
            if isinstance(n, int):
                live3[n] = canon_sha(it.get("level_json"))
        del src
    except Exception as e:  # noqa: BLE001
        log(f"live3 read fail {e}")

    # 보스/기믹 첫 등장 (출시 커밋 테이블 기준)
    unlock = tabs_b.get("unlock_effect", {})
    first_gimmick = {toint(r.get("unlockLevel")) + 1: r.get("id") for r in unlock.values()}

    # 기존 시드 수집 (중복 금지 대상)
    used = set()
    for r in rows_b.values():
        for t in str(r.get("randSeed", "")).split("|"):
            if t.strip().lstrip("-").isdigit():
                used.add(int(t))
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

    # 패키지 측정 재사용 판정용
    pkg_levels = set()
    with (PKG / "sets.csv").open() as f:
        for r in csv.DictReader(f):
            pkg_levels.add(int(r["level"]))

    levels = sorted((int(k.split("_")[1]) for k in maps_b if int(k.split("_")[1]) >= MIN_LEVEL))
    plat_by_level = {d["level"]: d for d in plat_diff}
    for sub in (f"out/orig/{BASE_COMMIT}", f"out/orig/{OLD_COMMIT}", "out/t0base", "config"):
        (RUN / sub).mkdir(parents=True, exist_ok=True)
    # 구버전(a2229a5d) 원본도 분리 보존 (변형은 BASE_COMMIT 기준만)
    for k, ma in maps_a.items():
        if int(k.split("_")[1]) >= MIN_LEVEL:
            (RUN / f"out/orig/{OLD_COMMIT}/{k}.json").write_bytes(dump(
                {"_note": "OFFLINE COPY — NOT UPLOADED. source=" + OLD_COMMIT, "level": int(k.split("_")[1]),
                 "row": rows_a.get(k, {}), "map": ma}))
    del maps_a
    rows_out, variants, exc, done = [], [], [], []
    stop_reason = None
    for L in levels:
        if past_cutoff():
            stop_reason = f"deadline {CUTOFF_HHMM}"
        elif resource_due() and resource_check(f"L{L}"):
            stop_reason = "resource"
        if stop_reason:
            exc.append({"level": L, "scope": "run", "reason": f"not_processed:{stop_reason}"})
            continue
        k = f"level_{L}"
        m, row = maps_b[k], rows_b.get(k, {})
        cnt, keys, t0_orig, total, issues = analyze(m)
        N = len(cnt)
        meta_raw = row.get("useTileCount")
        meta_utc = toint(meta_raw, None)
        unlock_tile = toint(row.get("unlockTile"))
        imb = row.get("typeImbalance", "")
        acc = toint(row.get("autoCollectCount"))
        n_keys = sum(keys.values())
        reasons_all, notes = [], []
        bad_list = nonempty_list_layers(m)
        if bad_list:
            reasons_all.append("tiles_nonempty_list:" + ",".join(bad_list))
        if issues:
            reasons_all.append("map_issue:" + ";".join(sorted(set(i.split(":")[0] for i in issues))))
        if t0_orig:
            reasons_all.append("orig_has_t0(runtime types not countable)")
        if n_keys and unlock_tile > 0:
            reasons_all.append("fixed_key_with_unlockTile>0(key set may be added)")
        bad3 = [t for t, c in cnt.items() if c % 3] + [t for t, c in keys.items() if c % 3]
        if bad3:
            reasons_all.append("orig_type_count_not_mult3:" + ",".join(sorted(bad3)))
        t0n = sum(cnt.values())
        if t0n % 3:
            reasons_all.append("t0_count_not_mult3")
        # 메타 useTileCount vs 실제 distinct: 0/빈값은 '원본 무t0 → 런타임 미사용' 근거 기록, 그 외 불일치 = 보류
        meta_flag, meta_basis = "", ""
        if meta_utc in (None, 0):
            meta_flag = "meta_unset"
            meta_basis = f"meta useTileCount={meta_raw!r}; original has no t0 so runtime never uses it"
        elif meta_utc != N:
            meta_flag = "meta_mismatch"
            meta_basis = f"meta useTileCount={meta_utc} != realized distinct {N}; no basis to choose -> hold"
        if imb not in ("", "0", 0, None):
            notes.append(f"typeImbalance={imb}(setting types may differ from realized distinct)")
        excl = []
        if 1 <= acc <= 3:
            excl.append("boss(autoCollectCount)")
        if L in first_gimmick:
            excl.append(f"gimmick_first({first_gimmick[L]})")
        if toint(row.get("timea")) or toint(m.get("timea")):
            excl.append("time_attack")
        pd = plat_by_level.get(L)
        compat = [BASE_COMMIT] + ([] if pd else [OLD_COMMIT])
        orig_map_sha = sha(dump(m))

        # 산출: orig + t0base (보류여도 원본 사본은 보존)
        orig_obj = {"_note": "OFFLINE COPY — NOT UPLOADED. source=" + BASE_COMMIT, "level": L, "row": row, "map": m}
        (RUN / f"out/orig/{BASE_COMMIT}/{k}.json").write_bytes(dump(orig_obj))
        status_t0 = "HOLD" if reasons_all else "OK"
        t0_sha, t0_map_sha = "", ""
        if not reasons_all:
            tm = to_t0(m)
            # 저장 정합 검증
            ca, kb, t0b, totb, isb = analyze(tm)
            chk = []
            if order_sig(tm) != order_sig(m):
                chk.append("order")
            if struct_sig(tm) != struct_sig(m):
                chk.append("struct")
            if totb != total:
                chk.append("total")
            if ca:
                chk.append("normal_left")
            if t0b != t0n:
                chk.append("t0n")
            if kb != keys:
                chk.append("keys")
            if isb:
                chk.append("issues")
            if chk:
                status_t0 = "HOLD"
                reasons_all.append("convert_check_fail:" + ",".join(chk))
            else:
                t0_obj = {"_note": "OFFLINE t0 BASE — NOT UPLOADED. use with config/variants (useTileCount, randSeed)",
                          "level": L, "sourceCommit": BASE_COMMIT, "origMapSha256": orig_map_sha,
                          "row": row, "map": tm}
                b = dump(t0_obj)
                (RUN / f"out/t0base/{k}.json").write_bytes(b)
                t0_sha, t0_map_sha = sha(b), sha(dump(tm))
        sets_t0 = t0n // 3
        dirs = {}
        for d, utc in (("easy", N - 1), ("hard", N + 1)):
            r = []
            if status_t0 != "OK":
                r.append("t0base_hold")
            if meta_flag == "meta_mismatch":
                r.append("meta_mismatch")
            if not 1 <= utc <= 15:
                r.append(f"useTileCount_out_of_range({utc})")
            if utc > sets_t0:
                r.append(f"useTileCount>{sets_t0}sets(realized types<setting)")
            if d == "easy" and utc < 2:
                r.append("easy_types<2")
            dirs[d] = (utc, r)
            if r:
                exc.append({"level": L, "scope": d, "reason": ";".join(r)})
                continue
            for j in range(N_CAND):
                seed = draw()
                eff_row = dict(row)
                eff_row["useTileCount"] = str(utc)
                eff_row["randSeed"] = str(seed)
                cond = sha(dump({"sourceCommit": BASE_COMMIT, "t0baseMapSha256": t0_map_sha, "row": eff_row}))
                variants.append({"level": L, "dir": d, "cand": j + 1, "useTileCount": utc, "randSeed": seed,
                                 "sourceCommit": BASE_COMMIT, "compatibleCommits": "|".join(compat),
                                 "requiredOrigMapSha256": orig_map_sha, "t0baseFileSha256": t0_sha,
                                 "t0baseMapSha256": t0_map_sha, "condSha256": cond,
                                 "intent": d, "difficultyRank": None, "verified": "no(storage-structure only)",
                                 "autoApply": ("excluded:" + "|".join(excl)) if excl else "eligible(manual approval)"})
        for rr in reasons_all:
            exc.append({"level": L, "scope": "t0base", "reason": rr})
        for e in excl:
            exc.append({"level": L, "scope": "autoApply", "reason": e})
        if meta_flag == "meta_mismatch":
            exc.append({"level": L, "scope": "meta", "reason": "meta_mismatch: " + meta_basis})
        if pd:
            exc.append({"level": L, "scope": "platform", "reason": f"{OLD_COMMIT} differs:{pd['kind']}"})
        done.append(L)
        rows_out.append({"level": L, "sourceCommit": BASE_COMMIT, "compatibleCommits": "|".join(compat),
                         "origFileSha256": sha(dump(orig_obj)), "origMapSha256": orig_map_sha,
                         "t0baseFileSha256": t0_sha, "t0baseMapSha256": t0_map_sha,
                         "live3Same": (live3.get(L) == canon_sha(m)) if L in live3 else None,
                         "distinctNormal": N, "meta_useTileCount": meta_raw, "metaFlag": meta_flag,
                         "metaBasis": meta_basis, "typeImbalance": imb,
                         "unlockTile": unlock_tile, "keys": n_keys, "effTotal": total, "t0Count": t0n,
                         "t0Sets": sets_t0, "t0base": status_t0,
                         "easy": "OK" if not dirs["easy"][1] else "HOLD", "hard": "OK" if not dirs["hard"][1] else "HOLD",
                         "autoApplyExclude": "|".join(excl), "notes": ";".join(notes),
                         "platformDiff": pd["kind"] if pd else "",
                         "pkg60Level": L in pkg_levels})

    (RUN / "checkpoint.json").write_bytes(dump({"done": done, "stopReason": stop_reason}))
    with (RUN / "config/levels.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0]))
        w.writeheader()
        w.writerows(rows_out)
    with (RUN / "config/variants.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(variants[0]))
        w.writeheader()
        w.writerows(variants)
    (RUN / "config/variants.json").write_bytes(json.dumps(
        {"baseCommit": BASE_COMMIT,
         "versionConstraint": "apply only when level row sourceCommit is in compatibleCommits AND current map "
                              "sha256 == requiredOrigMapSha256; otherwise use original (fallback)",
         "variants": variants}, ensure_ascii=False, indent=0).encode())
    with (RUN / "exceptions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "scope", "reason"])
        w.writeheader()
        w.writerows(exc)
    seeds = [v["randSeed"] for v in variants]
    assert len(seeds) == len(set(seeds)) and all(0 < s < 2**31 for s in seeds)
    full = [r for r in rows_out if r["easy"] == "OK" and r["hard"] == "OK"]
    part = [r for r in rows_out if (r["easy"] == "OK") != (r["hard"] == "OK")]
    hold = [r for r in rows_out if r["easy"] != "OK" and r["hard"] != "OK"]
    manifest = {
        "id": "dda_t0_all_20261020", "runId": RUN_ID, "stopReason": stop_reason,
        "status": "OFFLINE PREPARATION ONLY — not applied/uploaded; no bot/solver/difficulty run",
        "source": {"baseCommit": BASE_COMMIT, "variantsBasedOn": BASE_COMMIT, "platforms": COMMIT_PLATFORMS,
                   "files": {BASE_COMMIT: raw_b, OLD_COMMIT: raw_a},
                   "versionToCommitBasis": "docs 40/45 + af_level_metrics.VERSION_SHARD_COMMIT; "
                                            "INFERENCE from git history, NOT proven by runtime map hash",
                   "live3Note": "editor LIVE3 snapshot (pv_20261002_live3/source.json) is NOT the shipped data; "
                                f"compared by canonical sha256 only; shipped {BASE_COMMIT}/{OLD_COMMIT} shards used as original",
                   "live3SameCount": sum(1 for r in rows_out if r["live3Same"] is True),
                   "live3DiffCount": sum(1 for r in rows_out if r["live3Same"] is False)},
        "platformDiffs": plat_diff,
        "contract": {
            "t0": "only normal t1..t15 ids that are not isKeyTile (DB_Level.cs:238: t16 / id key / effect key) -> t0; "
                  "stack/craft root/direction/N kept; explicit inner normal ids -> t0, inner key kept; "
                  "layer/cell JSON order kept; empty layers ('tiles': []) kept; gimmick effects/meta kept; "
                  "effective total = normal cells + container inner N, unchanged",
            "N": "distinct normal ids incl. explicit container inner, excluding key",
            "easy": "useTileCount=N-1", "hard": "useTileCount=N+1", "validRange": "1..15 (0=max fallback,16=key)",
            "variantFields": "row copy with map=t0base map, useTileCount, randSeed (single positive Int32)",
            "versionConstraint": "variant valid only for compatibleCommits with requiredOrigMapSha256 match",
            "condSha256": "sha256 of {sourceCommit, t0baseMapSha256 (order-preserving), effective row incl. "
                          "useTileCount/randSeed/unlockTile/typeImbalance/shuffle*/visual fields}",
            "seed": {"rng": f"random.Random({SEED_RNG_KEY!r}) sequential draw in level order, easy then hard",
                     "range": [SEED_LO, SEED_HI],
                     "excluded": "existing level randSeeds, package sets.csv tokens, seed_bands ranges; globally unique"},
            "holdRules": ["map issue / inner count mismatch (loader fallback) / non-empty list tiles",
                          "original contains t0", "fixed key + unlockTile>0", "type count %3 != 0",
                          "meta useTileCount (non-zero) != realized distinct", "useTileCount out of 1..15",
                          "useTileCount > t0 sets", "easy < 2 types"],
        },
        "verification": {"storageStructure": "checked (order, structure signature, total, keys, %3)",
                         "postAssignment": "UNVERIFIED", "solvable": "UNVERIFIED", "difficulty": "UNVERIFIED",
                         "difficultyRank": None, "easyHardLabel": "intent only, not PASS"},
        "measurementReuse": {"count": 0, "reason": "package_20261020_0544 measured randSeed/θ variants of "
                             "original-type maps, not t0 useTileCount N±1 maps; conditions differ"},
        "counts": {"levels": len(levels), "processed": len(rows_out), "bothOK": len(full), "partial": len(part),
                   "hold": len(hold), "t0baseOK": sum(1 for r in rows_out if r["t0base"] == "OK"),
                   "variants": len(variants), "autoApplyExcluded": sum(1 for r in rows_out if r["autoApplyExclude"]),
                   "metaMismatch": sum(1 for r in rows_out if r["metaFlag"] == "meta_mismatch"),
                   "metaUnset": sum(1 for r in rows_out if r["metaFlag"] == "meta_unset"),
                   "exceptionReasons": dict(Counter(e["scope"] + ":" + e["reason"].split("(")[0].split(":")[0]
                                                    for e in exc))},
        "generatedBy": "backend/scripts/dda_t0_all_prepare_20261020.py",
    }
    (RUN / "manifest.json").write_bytes(json.dumps(manifest, ensure_ascii=False, indent=1).encode())
    # SHA256SUMS: 이번 run 파일 + live_copy
    lines = []
    for base in (RUN, OUT / "live_copy"):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != "SHA256SUMS" and p.suffix != ".log":
                lines.append(f"{sha(p.read_bytes())}  {p.relative_to(OUT)}")
    (RUN / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    resource_check("end")
    log("counts " + json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
