"""[분석 전용, 읽기 전용] AppsFlyer 로우 데이터 → 레벨별 실제 유저 클리어율·세부 지표 (봇 보정 1단계).

산출: claudedocs/difficulty_personalization/13_af_bot_calibration_data.md 의 근거 데이터.
  - backend/data/pv_sandbox/af_calibration/level_metrics.json (+ level_metrics.csv)
  - 식별자(AppsFlyer ID·광고 ID·CUID·IP 등)는 메모리 안 해시로만 쓰고 출력하지 않는다.

입력 (모두 읽기만 함):
  - AF 저장소 data/{android,ios}_{,organic_}in_app_events.csv.gz (cc-web 최신 API pull 반영분)
  - 에디터 LIVE 3차 배치 사본 backend/data/pv_sandbox/pv_20261002_live3/source.json
  - 게임 저장소 sp_meowsgarden 의 빌드 내장 샤드(git show 로 커밋별 스냅샷 읽기, 저장소 수정 없음)
    · 보스/기믹 첫 등장 표시는 현재 샤드 levels·unlock_effect 테이블(tools/level_audit/extract_levels.py)

판 재구성 규칙 = 게임 위키 IMPL_SPEC §V2-2-3 / §V2-6 (tools/af_dda_analyze.py) 과 동일:
  기기별 시간순, 같은 초는 clear → fail → revive → retry → start → booster.
  level_start 가 판을 열고 다음 level_start 가 닫는다. 결과 = clear / final_fail(마지막 fail 뒤
  revive 없음) / no_end(기록 없음: 포기·강제 종료·불명) / censored(데이터 끝에서 열린 채 종료).
  정식 판만(is_infinite≠1, 1 ≤ level ≤ 1500).
중복 제거 키 = AF ID + Event Time + Event Name + 키 정렬 payload + App Version.

사용 (backend 디렉터리에서, app.core.pv 임포트 때문에 venv 사용):
    .venv/bin/python scripts/af_level_metrics.py
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

csv.field_size_limit(10 ** 9)

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

AF_DATA = Path.home() / ".cc-web/projects/sp_meowsgarden/af/data"
GAME_REPO = Path("/Users/casualdev/sp_meowsgarden")
EDITOR_SOURCE = BACKEND / "data/pv_sandbox/pv_20261002_live3/source.json"
OUT_DIR = BACKEND / "data/pv_sandbox/af_calibration"

LEVEL_EVENTS = {"level_start", "level_clear", "level_fail", "level_revive", "level_retry"}
TIE_ORDER = {"level_clear": 0, "level_fail": 1, "level_revive": 2, "level_retry": 3,
             "level_start": 4, "booster": 5}
KEEP_KEYS = ("level", "attempt", "is_infinite", "item_used", "tiles_left", "combo_max", "play_sec", "fail_reason")
MAX_LEVEL = 1500
SEGMENTS = [(1, 31), (32, 100), (101, 300), (301, 500), (501, 1000), (1001, 1500)]

# 판 재구성이 성립하는 버전: 결과창 '다시하기'도 level_start 를 발행(1.0.162.30~, MMP §F-3).
# 그 이전 버전은 재도전 판이 start 없이 이어져 판이 합쳐지므로 제외(실측 확인은 version_check).
RUN_VERSIONS = {("android", "1.0.162"), ("android", "1.1.0"), ("ios", "2.1.0")}

# 앱 버전 → 빌드 내장 레벨 맵 샤드 커밋 (델타 갱신은 v1.10.1025 부터 비활성 → 빌드 내장본이 실제 맵).
# 근거: 버전 반영 커밋 이전의 마지막 샤드 변경 커밋.
#   1.0.162: b4ce386f(09-08 버전 재부여) 직전 샤드 변경 a2229a5d(09-08)
#   1.1.0 / iOS 2.1.0: 727328a9(09-29 플랫폼 버전 반영) 직전 샤드 변경 b741f6a3(09-21)
VERSION_SHARD_COMMIT = {
    ("android", "1.0.162"): "a2229a5d",
    ("android", "1.1.0"): "b741f6a3",
    ("ios", "2.1.0"): "b741f6a3",
}
SHARD_HISTORY = ["b741f6a3", "51fa8f2b", "a2229a5d", "9593daea", "1e0b3579", "446adb43"]


# ---------------------------------------------------------------------------
# 이벤트 적재
# ---------------------------------------------------------------------------

def _int(d, k, default=None):
    try:
        v = d.get(k)
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def load_events(data_dir: Path):
    per_dev = defaultdict(list)
    seen = set()
    meta = {"rows_kept": 0, "dup_dropped": 0, "min_time": None, "max_time": None,
            "files": [], "version_check": defaultdict(Counter), "level_start_versions": Counter()}
    for plat in ("android", "ios"):
        for name in (f"{plat}_in_app_events.csv.gz", f"{plat}_organic_in_app_events.csv.gz"):
            path = data_dir / name
            if not path.exists():
                continue
            meta["files"].append(name)
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="", errors="replace") as fh:
                r = csv.reader(fh)
                h = next(r)
                iN, iV, iT = h.index("Event Name"), h.index("Event Value"), h.index("Event Time")
                iA, iU = h.index("App Version"), h.index("AppsFlyer ID")
                for row in r:
                    n = row[iN]
                    is_booster = n.startswith("booster_use_")
                    if n not in LEVEL_EVENTS and not is_booster:
                        continue
                    try:
                        val = json.loads(row[iV]) if row[iV] else {}
                    except ValueError:
                        val = {}
                    if not isinstance(val, dict):
                        val = {}
                    ver = row[iA]
                    payload = json.dumps(val, sort_keys=True, ensure_ascii=False)
                    key = hashlib.sha1("\x1f".join((row[iU], row[iT], n, payload, ver)).encode()).digest()
                    if key in seen:
                        meta["dup_dropped"] += 1
                        continue
                    seen.add(key)
                    vc = meta["version_check"][f"{plat}|{ver}"]
                    if n == "level_start":
                        meta["level_start_versions"][f"{plat}|{ver}"] += 1
                        vc["start"] += 1
                        if (_int(val, "attempt") or 0) >= 2:
                            vc["start_att2"] += 1
                    elif n == "level_retry":
                        vc["retry"] += 1
                    if (plat, ver) not in RUN_VERSIONS:
                        continue
                    t = row[iT]
                    if meta["min_time"] is None or t < meta["min_time"]:
                        meta["min_time"] = t
                    if meta["max_time"] is None or t > meta["max_time"]:
                        meta["max_time"] = t
                    nn = "booster" if is_booster else n
                    val = {k: val[k] for k in KEEP_KEYS if k in val}  # 메모리 절약
                    dev =hashlib.sha1((plat + row[iU]).encode()).hexdigest()[:16]  # 메모리 전용
                    per_dev[dev].append((t, TIE_ORDER[nn], nn, val, plat, ver))
                    meta["rows_kept"] += 1
    return per_dev, meta


# ---------------------------------------------------------------------------
# 판 재구성
# ---------------------------------------------------------------------------

def _new_run(dev, d, t, plat, ver):
    return {"dev": dev, "L": _int(d, "level", 0), "att": _int(d, "attempt", 0),
            "t0": t, "plat": plat, "ver": ver, "fails": 0, "revives": 0,
            "boosters": 0, "item": 0, "clear": False, "last": None, "infinite": False,
            "open_at_end": False, "clear_ev": None, "fail_ev": None}


def _apply(cur, n, d):
    if n in ("level_clear", "level_fail"):
        if d.get("is_infinite") == "1":
            cur["infinite"] = True
        cur["item"] = max(cur["item"], _int(d, "item_used", 0) or 0)
    if n == "level_fail":
        cur["fails"] += 1
        cur["last"] = "fail"
        cur["fail_ev"] = d
    elif n == "level_revive":
        cur["revives"] += 1
        cur["last"] = "revive"
    elif n == "level_clear":
        cur["clear"] = True
        cur["last"] = "clear"
        cur["clear_ev"] = d
    elif n == "booster":
        cur["boosters"] += 1


def build_runs(per_dev, legacy=False):
    """legacy=True: §V2-6 규칙 그대로(직전 start 판에 붙임).
    기본: 오프라인 일괄 전송으로 같은 초에 start·종료가 뒤섞이는 경우를 보정 — 종료·부활·부스터
    이벤트를 이벤트의 `level` 과 같은 열린 판에 붙이고, 같은 초에 그 레벨 start 가 있으면 start 뒤로 미룬다.
    무한 판(is_infinite=1)·level 값 없는 이벤트는 직전 start 판에 붙인다."""
    runs = []
    ties = Counter()
    orphan = Counter()        # 붙일 판이 없는 이벤트
    q_cnt = Counter()         # 보정 통계
    for dev, ev in per_dev.items():
        ev.sort(key=lambda x: (x[0], x[1]))
        for a, b in zip(ev, ev[1:]):
            if a[0] == b[0] and a[2] != b[2]:
                ties[f"{a[2]}>{b[2]}"] += 1
        dev_runs = []
        if legacy:
            cur = None
            for t, _, n, d, plat, ver in ev:
                if n == "level_start":
                    if cur:
                        dev_runs.append(cur)
                    cur = _new_run(dev, d, t, plat, ver)
                    continue
                if cur is None:
                    orphan[n] += 1
                    continue
                if n in ("level_clear", "level_fail") and d.get("is_infinite") != "1":
                    lv = _int(d, "level")
                    if lv is not None and lv != cur["L"]:
                        q_cnt["end_level_ne_run_level"] += 1
                _apply(cur, n, d)
            if cur:
                cur["open_at_end"] = True
                dev_runs.append(cur)
        else:
            open_by_level = {}
            latest = None
            i = 0
            while i < len(ev):
                j = i
                while j < len(ev) and ev[j][0] == ev[i][0]:
                    j += 1
                group = ev[i:j]
                start_levels = {_int(d, "level", 0) for _, _, n, d, _, _ in group if n == "level_start"}
                deferred = []

                def target(n, d):
                    if n == "level_retry":
                        return "skip"
                    lv = _int(d, "level")
                    if d.get("is_infinite") == "1" or lv is None or lv == 0:
                        return latest
                    return open_by_level.get(lv)

                for t, _, n, d, plat, ver in group:
                    if n == "level_start":
                        continue
                    lv = _int(d, "level")
                    tg = target(n, d)
                    if tg == "skip":
                        continue
                    if lv in start_levels and (tg is None or tg["clear"]):
                        deferred.append((n, d))   # 같은 초 그 레벨 start 뒤로
                        continue
                    if tg is None:
                        orphan[n] += 1
                        continue
                    if tg is not latest:
                        q_cnt["attached_to_non_latest_run"] += 1
                    _apply(tg, n, d)
                for t, _, n, d, plat, ver in group:
                    if n != "level_start":
                        continue
                    r = _new_run(dev, d, t, plat, ver)
                    old = open_by_level.get(r["L"])
                    if old is not None:
                        dev_runs.append(old)
                    open_by_level[r["L"]] = r
                    latest = r
                for n, d in deferred:
                    tg = target(n, d)
                    if tg is None:
                        orphan[n] += 1
                        continue
                    q_cnt["deferred_after_same_second_start"] += 1
                    _apply(tg, n, d)
                # 다른 레벨의 오래된 열린 판은 닫는다(10분 이상 지난 판)
                tnow = datetime.strptime(group[0][0], "%Y-%m-%d %H:%M:%S")
                for L, r in list(open_by_level.items()):
                    if r is latest:
                        continue
                    if (tnow - datetime.strptime(r["t0"], "%Y-%m-%d %H:%M:%S")).total_seconds() > 600:
                        dev_runs.append(r)
                        del open_by_level[L]
                i = j
            for r in open_by_level.values():
                if r is latest:
                    r["open_at_end"] = True
                dev_runs.append(r)
        runs.extend(dev_runs)
    level_mismatch = q_cnt
    for r in runs:
        if r["clear"]:
            r["oc"] = "clear"
        elif r["last"] == "fail":
            r["oc"] = "final_fail"
        elif r["open_at_end"]:
            r["oc"] = "censored"
        else:
            r["oc"] = "no_end"
        r["helped"] = r["item"] > 0 or r["boosters"] > 0 or r["revives"] > 0
    return runs, ties, orphan, level_mismatch


def mark_first_try(runs):
    """첫 시도 = 그 기기의 그 레벨 첫 관측 판이면서 attempt==1 (관측 전 시도 가능성 배제)."""
    seen = set()
    for r in sorted(runs, key=lambda x: (x["dev"], x["t0"])):
        k = (r["dev"], r["L"])
        r["first_obs"] = k not in seen
        r["first_try"] = r["first_obs"] and r["att"] == 1
        seen.add(k)


# ---------------------------------------------------------------------------
# 통계 도구
# ---------------------------------------------------------------------------

def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(max(0.0, c - hw), 4), round(min(1.0, c + hw), 4)


def q(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = (len(s) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return round(s[lo] + (s[hi] - s[lo]) * (i - lo), 2)


def dist(vals):
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": round(sum(vals) / len(vals), 2),
            "p10": q(vals, .1), "p25": q(vals, .25), "p50": q(vals, .5),
            "p75": q(vals, .75), "p90": q(vals, .9)}


TL_BINS = [(1, 3), (4, 6), (7, 9), (10, 15), (16, 30), (31, 10 ** 6)]


def tl_hist(vals):
    out = {}
    for lo, hi in TL_BINS:
        lab = f"{lo}-{hi}" if hi < 10 ** 6 else f"{lo}+"
        out[lab] = sum(1 for v in vals if lo <= v <= hi)
    out["0_or_missing"] = sum(1 for v in vals if v <= 0)
    return out


def seg_of(L):
    for a, b in SEGMENTS:
        if a <= L <= b:
            return f"{a}-{b}"
    return None


# ---------------------------------------------------------------------------
# 맵 일치 (빌드 내장 샤드 vs 에디터 LIVE 3차)
# ---------------------------------------------------------------------------

def _map_hashes(level_json):
    from app.core.pv.canonical import canonical_map, struct_hash
    c = canonical_map(level_json)
    full = hashlib.sha256(json.dumps(c, separators=(",", ":")).encode()).hexdigest()
    return full, struct_hash(c)


def load_map_match():
    from pv_scan_shards import decrypt_shard_file

    def show(commit, key):
        p = f"Assets/StreamingAssets/GBoost/a{hashlib.md5(key.encode()).hexdigest()}.txt"
        r = subprocess.run(["git", "-C", str(GAME_REPO), "show", f"{commit}:{p}"], capture_output=True)
        return r.stdout if r.returncode == 0 else None

    src = json.loads(EDITOR_SOURCE.read_text())
    editor = {it["meta"]["level_number"]: _map_hashes(it["level_json"]) for it in src["levels"]
              if isinstance(it.get("meta", {}).get("level_number"), int)}
    snaps = {}
    for c in sorted(set(VERSION_SHARD_COMMIT.values())):
        maps = {}
        for i in range(16):
            b = show(c, f"levelmap_level_{i}")
            if b:
                maps.update(decrypt_shard_file(b))
        res = {}
        for L in range(1, MAX_LEVEL + 1):
            m = maps.get(f"level_{L}")
            if m is None or L not in editor:
                res[L] = "missing"
                continue
            full, st = _map_hashes(m)
            res[L] = "same" if full == editor[L][0] else ("types_differ" if st == editor[L][1] else "struct_differ")
        snaps[c] = res
    meta = {"editor_batch": src.get("batch_id"), "editor_saved_at": src.get("saved_at"),
            "version_shard_commit": {f"{p}|{v}": c for (p, v), c in VERSION_SHARD_COMMIT.items()},
            "per_commit_diff_counts": {c: dict(Counter(v for v in res.values())) for c, res in snaps.items()}}
    return snaps, meta


def level_tags():
    """보스(autoCollectCount 1~3)·기믹 첫 등장(unlockLevel+1) — 현재 샤드 테이블(읽기 전용)."""
    sys.path.insert(0, str(GAME_REPO / "tools/level_audit"))
    try:
        import extract_levels as xl
        meta = xl.load_table("levels")
        unlock = xl.load_table("unlock_effect")
    except Exception:  # noqa: BLE001 — 태그는 보조 정보
        return set(), set()
    boss = set()
    for lid, row in meta.items():
        if lid.startswith("level_"):
            try:
                if 1 <= int(float(row.get("autoCollectCount") or 0)) <= 3:
                    boss.add(int(lid[6:]))
            except ValueError:
                pass
    first = {int(float(r.get("unlockLevel") or 0)) + 1 for r in unlock.values()}
    return boss, first


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------

def level_block(rs):
    """한 레벨(또는 구간)의 판 목록 → 지표."""
    ended = [r for r in rs if r["oc"] in ("clear", "final_fail")]
    ft = [r for r in rs if r["first_try"] and r["oc"] != "censored"]
    ft_end = [r for r in ft if r["oc"] in ("clear", "final_fail")]
    clean = [r for r in ft_end if not r["helped"]]
    k_clean = sum(1 for r in clean if r["oc"] == "clear")
    k_all = sum(1 for r in ended if r["oc"] == "clear")
    ft_noend = sum(1 for r in ft if r["oc"] == "no_end")
    ft_noend_clean = sum(1 for r in ft if r["oc"] == "no_end" and not r["helped"])

    lo, hi = wilson(k_clean, len(clean))
    out = {
        "runs_total": len(rs),
        "runs_ended": len(ended),
        "outcomes": dict(Counter(r["oc"] for r in rs)),
        "clear_rate_all_ended": round(k_all / len(ended), 4) if ended else None,
        "users": len({r["dev"] for r in rs}),
        "first_try_runs": len(ft),
        "first_try_ended": len(ft_end),
        "first_try_users": len({r["dev"] for r in ft}),
        # 봇 비교 기준: 첫 시도 · 무부스터(item_used=0, booster_use 0) · 무부활, 클리어/최종 실패로 끝난 판
        "clean_ft_n": len(clean),
        "clean_ft_clear": k_clean,
        "clean_ft_rate": round(k_clean / len(clean), 4) if clean else None,
        "clean_ft_ci95": [lo, hi],
        # 민감도: 첫시도 무도움 기록없음(no_end)을 실패로 넣은 클리어율
        "clean_ft_rate_noend_as_fail": round(k_clean / (len(clean) + ft_noend_clean), 4)
        if (len(clean) + ft_noend_clean) else None,
        # 하한: 도움 받은 첫 시도 판을 전부 '도움 없으면 실패'로 본 비율 = 무도움 클리어 / 첫 시도 종료 판 전체
        "unaided_clear_lower_bound": round(k_clean / len(ft_end), 4) if ft_end else None,
        # 상한: 도움 판 중 실패 이벤트가 없었던(부활·실패 전 부스터만) 클리어 판을 무도움 클리어로 간주
        "unaided_clear_upper_bound": round((k_clean + sum(1 for r in ft_end if r["helped"] and r["oc"] == "clear"
                                                           and r["fails"] == 0)) / len(ft_end), 4) if ft_end else None,
        "clean_ft_users": len({r["dev"] for r in clean}),
        "clean_ft_top10_user_share": round(sum(c for _, c in Counter(r["dev"] for r in clean).most_common(10))
                                           / len(clean), 4) if clean else None,
        "ft_help_rate": round(sum(1 for r in ft_end if r["helped"]) / len(ft_end), 4) if ft_end else None,
        "ft_booster_rate": round(sum(1 for r in ft_end if r["item"] > 0 or r["boosters"] > 0) / len(ft_end), 4)
        if ft_end else None,
        "ft_revive_rate": round(sum(1 for r in ft_end if r["revives"] > 0) / len(ft_end), 4) if ft_end else None,
        "ft_noend_rate": round(ft_noend / len(ft), 4) if ft else None,
        "ft_clear_rate_any_help": round(sum(1 for r in ft_end if r["oc"] == "clear") / len(ft_end), 4)
        if ft_end else None,
    }
    # 실패 시 tiles_left / combo_max / play_sec (첫시도 무도움 판; 계측은 1.0.162.10+)
    fails = [r for r in clean if r["oc"] == "final_fail"]
    clears = [r for r in clean if r["oc"] == "clear"]
    tl = [v for v in (_int(r["fail_ev"] or {}, "tiles_left") for r in fails) if v is not None]
    out["fail_tiles_left"] = dist(tl)
    out["fail_tiles_left_hist"] = tl_hist(tl)
    out["fail_reason"] = dict(Counter((r["fail_ev"] or {}).get("fail_reason", "") for r in fails))
    out["combo_max_clear"] = dist([v for v in (_int(r["clear_ev"] or {}, "combo_max") for r in clears) if v is not None])
    out["combo_max_fail"] = dist([v for v in (_int(r["fail_ev"] or {}, "combo_max") for r in fails) if v is not None])
    out["play_sec_clear"] = dist([v for v in (_int(r["clear_ev"] or {}, "play_sec") for r in clears) if v is not None])
    out["play_sec_fail"] = dist([v for v in (_int(r["fail_ev"] or {}, "play_sec") for r in fails) if v is not None])
    return out


def attempts_to_clear(rs):
    """첫 관측 판이 attempt==1 인 (기기,레벨) 쌍: 첫 클리어까지 판 수(기록 없음 판 포함)."""
    by = defaultdict(list)
    for r in rs:
        by[(r["dev"], r["L"])].append(r)
    vals, never = [], 0
    for lst in by.values():
        lst.sort(key=lambda x: x["t0"])
        if not lst[0]["first_try"]:
            continue
        n = 0
        cleared = False
        for r in lst:
            if r["oc"] == "censored":
                break
            n += 1
            if r["oc"] == "clear":
                cleared = True
                break
        if cleared:
            vals.append(n)
        else:
            never += 1
    d = dist(vals)
    d["pairs_not_cleared_in_obs"] = never
    d["share_cleared_1st"] = round(sum(1 for v in vals if v == 1) / len(vals), 4) if vals else None
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(AF_DATA))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--skip-maps", action="store_true")
    ap.add_argument("--legacy-order", action="store_true", help="§V2-6 규칙 그대로(레벨 키 보정 없음) — 민감도 비교용")
    a = ap.parse_args()

    per_dev, meta = load_events(Path(a.data_dir))
    print(f"events kept {meta['rows_kept']} dup {meta['dup_dropped']} range {meta['min_time']}~{meta['max_time']}",
          flush=True)
    runs, ties, orphan, level_mismatch = build_runs(per_dev, legacy=a.legacy_order)
    del per_dev
    mark_first_try(runs)
    all_runs_n = len(runs)
    infinite_n = sum(1 for r in runs if r["infinite"])
    oor_n = sum(1 for r in runs if not r["infinite"] and not (1 <= r["L"] <= MAX_LEVEL))
    runs = [r for r in runs if not r["infinite"] and 1 <= r["L"] <= MAX_LEVEL]
    print(f"runs {all_runs_n} → official {len(runs)}", flush=True)

    if a.skip_maps:
        snaps, map_meta = {}, {}
    else:
        snaps, map_meta = load_map_match()
    boss, gfirst = level_tags()

    by_level = defaultdict(list)
    for r in runs:
        by_level[r["L"]].append(r)

    rows = []
    for L in range(1, MAX_LEVEL + 1):
        rs = by_level.get(L, [])
        b = level_block(rs)
        b["level"] = L
        b["segment"] = seg_of(L)
        b["is_boss"] = L in boss
        b["is_gimmick_first"] = L in gfirst
        b["attempts_to_clear"] = attempts_to_clear(rs)
        # 버전·플랫폼 구성 (첫시도 무도움 판)
        clean = [r for r in rs if r["first_try"] and r["oc"] in ("clear", "final_fail") and not r["helped"]]
        comp = Counter(f"{r['plat']}|{r['ver']}" for r in clean)
        b["clean_ft_by_version"] = {
            k: {"n": n, "rate": round(sum(1 for r in clean if f"{r['plat']}|{r['ver']}" == k and r["oc"] == "clear") / n, 4)}
            for k, n in comp.items()}
        # 맵 일치: 그 레벨 판(첫시도 무도움)의 버전별 빌드 내장 맵이 에디터와 같은 비율
        if snaps:
            st = Counter()
            for r in clean or rs:
                c = VERSION_SHARD_COMMIT.get((r["plat"], r["ver"]))
                st[snaps[c][L] if c else "unknown"] += 1
            tot = sum(st.values())
            if tot == 0:
                cur = snaps[VERSION_SHARD_COMMIT[("android", "1.1.0")]][L]
                b["map_match"] = "same" if cur == "same" else "mismatch"
            else:
                same_share = st["same"] / tot
                b["map_match"] = "same" if same_share >= 0.999 else ("mismatch" if same_share <= 0.001 else "mixed")
            b["map_match_detail"] = dict(st)
        rows.append(b)

    # 구간 집계
    segs = {}
    for lo, hi in SEGMENTS:
        rs = [r for r in runs if lo <= r["L"] <= hi]
        sb = level_block(rs)
        lv = [x for x in rows if lo <= x["level"] <= hi]
        sb["attempts_to_clear"] = attempts_to_clear(rs)
        sb["levels"] = hi - lo + 1
        sb["levels_with_runs"] = sum(1 for x in lv if x["runs_total"] > 0)
        for th in (10, 30, 100):
            sb[f"levels_clean_ft_ge{th}"] = sum(1 for x in lv if x["clean_ft_n"] >= th)
        rates = [x["clean_ft_rate"] for x in lv if x["clean_ft_n"] >= 30]
        sb["level_rate_mean_ge30"] = round(sum(rates) / len(rates), 4) if rates else None
        sb["level_rate_sd_ge30"] = round((sum((v - sb["level_rate_mean_ge30"]) ** 2 for v in rates) / (len(rates) - 1)) ** .5, 4) \
            if len(rates) > 1 else None
        sb["map_match_levels"] = dict(Counter(x.get("map_match", "n/a") for x in lv))
        sb["boss_levels"] = sum(1 for x in lv if x["is_boss"])
        # 버전별 첫시도 무도움 클리어율
        vb = {}
        for key in sorted({f"{r['plat']}|{r['ver']}" for r in rs}):
            sub = [r for r in rs if f"{r['plat']}|{r['ver']}" == key]
            blk = level_block(sub)
            vb[key] = {"clean_ft_n": blk["clean_ft_n"], "clean_ft_rate": blk["clean_ft_rate"],
                       "clean_ft_ci95": blk["clean_ft_ci95"], "ft_help_rate": blk["ft_help_rate"]}
        sb["by_version"] = vb
        # 보스 제외 버전
        nb = level_block([r for r in rs if r["L"] not in boss])
        sb["non_boss_clean_ft_n"], sb["non_boss_clean_ft_rate"] = nb["clean_ft_n"], nb["clean_ft_rate"]
        sb["boss_only_clean_ft"] = {k: level_block([r for r in rs if r["L"] in boss])[k]
                                    for k in ("clean_ft_n", "clean_ft_rate")}
        segs[f"{lo}-{hi}"] = sb

    # 생존 편향: 기준 구간(L32~100) 첫시도 무도움 클리어율 — 각 구간 도달 기기 vs 전체
    ref = defaultdict(lambda: [0, 0])
    reached = defaultdict(set)
    for r in runs:
        s = seg_of(r["L"])
        reached[s].add(r["dev"])
        if 32 <= r["L"] <= 100 and r["first_try"] and r["oc"] in ("clear", "final_fail") and not r["helped"]:
            ref[r["dev"]][1] += 1
            ref[r["dev"]][0] += r["oc"] == "clear"
    ref_ok = {d: v[0] / v[1] for d, v in ref.items() if v[1] >= 10}
    survival = {"reference": "L32-100 첫시도 무도움 클리어율, 그 구간 판 ≥10 기기", "all": dist(list(ref_ok.values()))}
    for lo, hi in SEGMENTS[2:]:
        s = f"{lo}-{hi}"
        vals = [ref_ok[d] for d in reached[s] if d in ref_ok]
        survival[s] = dist(vals)
        survival[s]["devices_reached"] = len(reached[s])
    # 도움 사용률 — 같은 L32~100 기준으로 도달 기기 비교
    help_ref = defaultdict(lambda: [0, 0])
    for r in runs:
        if 32 <= r["L"] <= 100 and r["first_try"] and r["oc"] in ("clear", "final_fail"):
            help_ref[r["dev"]][1] += 1
            help_ref[r["dev"]][0] += r["helped"]
    hr = {d: v[0] / v[1] for d, v in help_ref.items() if v[1] >= 10}
    survival["help_rate_L32_100_all"] = dist(list(hr.values()))
    for lo, hi in SEGMENTS[2:]:
        s = f"{lo}-{hi}"
        survival[f"help_rate_L32_100_reached_{s}"] = dist([hr[d] for d in reached[s] if d in hr])

    # 첫 시도 판정 점검: 첫 관측 판 attempt 분포
    att_first = Counter(min(r["att"], 3) for r in runs if r["first_obs"])

    thresholds = {}
    for th in (10, 30, 100):
        thresholds[f"clean_ft_ge{th}"] = sum(1 for x in rows if x["clean_ft_n"] >= th)
        thresholds[f"clean_ft_ge{th}_L32plus"] = sum(1 for x in rows if x["clean_ft_n"] >= th and x["level"] >= 32)
    thresholds["clean_ft_n_p10_p50_p90_L32plus"] = [q([x["clean_ft_n"] for x in rows if x["level"] >= 32], p)
                                                     for p in (.1, .5, .9)]

    plat_ver = Counter(f"{r['plat']}|{r['ver']}" for r in runs)
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": {
            "data_files": meta["files"], "event_time_range_kst": [meta["min_time"], meta["max_time"]],
            "run_build_mode": "legacy(§V2-6)" if a.legacy_order else "level-keyed(같은 초 보정)",
            "run_versions": sorted(f"{p}|{v}" for p, v in RUN_VERSIONS),
            "events_kept": meta["rows_kept"], "dup_dropped": meta["dup_dropped"],
            "runs_reconstructed": all_runs_n, "runs_infinite": infinite_n, "runs_level_out_of_range": oor_n,
            "official_runs": len(runs), "official_runs_by_version": dict(plat_ver),
            "devices": len({r["dev"] for r in runs}),
        },
        "version_check": {k: dict(v) for k, v in meta["version_check"].items() if v.get("start", 0) >= 500},
        "quality": {
            "same_second_pairs": dict(ties.most_common(15)),
            "orphan_end_events_without_start": dict(orphan),
            "run_build_stats": dict(level_mismatch),
            "first_obs_attempt_dist": {str(k): v for k, v in sorted(att_first.items())},
            "outcomes_all": dict(Counter(r["oc"] for r in runs)),
        },
        "definitions": {
            "clean_ft": "첫 시도(기기의 그 레벨 첫 관측 판이고 attempt=1) · item_used=0 · booster_use_* 0건 · level_revive 0건 · 결과가 clear/final_fail",
            "final_fail": "판의 마지막 결과 이벤트가 fail(뒤에 revive 없음)",
            "no_end": "start 뒤 clear/fail 없이 다음 start (포기·강제종료·불명)",
            "unaided_clear_lower_bound": "무도움 첫시도 클리어 / 첫시도 종료 판 전체 (도움 판을 전부 실패로 간주한 하한)",
            "unaided_clear_upper_bound": "(무도움 첫시도 클리어 + 실패 이벤트 없이 부스터만 쓰고 클리어한 첫시도 판) / 첫시도 종료 판 전체",
            "attempts_to_clear": "첫 관측 판이 첫 시도인 (기기,레벨) 쌍의 첫 클리어까지 판 수(기록 없음 판 포함)",
            "map_match": "판(첫시도 무도움, 없으면 전체)의 앱 버전별 빌드 내장 샤드 맵이 에디터 LIVE3 와 같은 비율: same(100%)/mixed/mismatch(0%)",
            "ci": "Wilson 95%",
        },
        "map_meta": map_meta,
        "thresholds": thresholds,
        "segments": segs,
        "survival_bias": survival,
        "levels": rows,
    }
    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    (od / "level_metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    cols = ["level", "segment", "is_boss", "is_gimmick_first", "map_match", "users", "runs_total", "runs_ended",
            "clear_rate_all_ended", "first_try_ended", "clean_ft_n", "clean_ft_users", "clean_ft_clear", "clean_ft_rate",
            "ci_lo", "ci_hi", "clean_ft_rate_noend_as_fail", "unaided_clear_lower_bound", "unaided_clear_upper_bound", "ft_help_rate",
            "ft_booster_rate", "ft_revive_rate", "ft_noend_rate", "att_to_clear_mean", "att_to_clear_p50",
            "att_pairs_not_cleared", "fail_tl_n", "fail_tl_p25", "fail_tl_p50", "fail_tl_p75",
            "combo_clear_p50", "combo_fail_p50", "play_sec_clear_p50", "play_sec_fail_p50"]
    with open(od / "level_metrics.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for x in rows:
            w.writerow([x["level"], x["segment"], int(x["is_boss"]), int(x["is_gimmick_first"]), x.get("map_match", ""),
                        x["users"], x["runs_total"], x["runs_ended"], x["clear_rate_all_ended"], x["first_try_ended"],
                        x["clean_ft_n"], x["clean_ft_users"], x["clean_ft_clear"], x["clean_ft_rate"], x["clean_ft_ci95"][0],
                        x["clean_ft_ci95"][1], x["clean_ft_rate_noend_as_fail"], x["unaided_clear_lower_bound"],
                        x["unaided_clear_upper_bound"],
                        x["ft_help_rate"], x["ft_booster_rate"], x["ft_revive_rate"], x["ft_noend_rate"],
                        x["attempts_to_clear"].get("mean"), x["attempts_to_clear"].get("p50"),
                        x["attempts_to_clear"]["pairs_not_cleared_in_obs"], x["fail_tiles_left"]["n"],
                        x["fail_tiles_left"].get("p25"), x["fail_tiles_left"].get("p50"),
                        x["fail_tiles_left"].get("p75"), x["combo_max_clear"].get("p50"),
                        x["combo_max_fail"].get("p50"), x["play_sec_clear"].get("p50"), x["play_sec_fail"].get("p50")])
    print("done", od, flush=True)


if __name__ == "__main__":
    main()
