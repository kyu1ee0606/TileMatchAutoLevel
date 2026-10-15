"""[분석 전용, 읽기 전용] AF 레벨 이벤트의 `attempt` 필드로 직접 묶는 첫 시도 클리어율 — level_start 불필요.

배경: `af_level_metrics.py`는 레벨 재구성을 `level_start`가 판을 열고 다음 `level_start`가 닫는 상태기계로
한다. 이 규칙은 android 1.0.162.30 이전 버전("다시하기"가 `level_start`를 안 냄, RUN_VERSIONS 밖)에선
안 맞아 그 구간을 통째로 버렸다(level_metrics.json의 `clean_ft_by_version`에 RUN_VERSIONS 3개만 존재).

이 스크립트는 `level_start` 없이도 쓸 수 있는 다른 사실에 의존한다: 실측 CSV를 떠보면(§0 조사)
`level_clear`/`level_fail` 이벤트 자체의 `attempt` 필드가 **진짜 재시도 경계와 일치**한다 —
"다시하기" 버튼으로 몇 분~몇 시간 뒤 재도전해도 attempt가 제대로 2,3,... 로 올라간다(level_start 유무와
무관). 같은 attempt 안에서 fail이 여러 번(이어하기/부활류, item_used 증가) 나온 뒤 결국 clear가 나올 수도
있다 — 이 경우도 "그 attempt는 결국 클리어"로 정확히 잡힌다(level_start 기반 재구성과 동일한 결론).

방법: (기기, 레벨, attempt) 로 clear/fail 이벤트를 직접 묶는다(level_start 불필요).
  - 그룹 결과: 그룹에 level_clear가 하나라도 있으면 clear, 전부 fail이면 final_fail.
  - "도움"(helped): 그룹 내 clear/fail 이벤트의 item_used 최댓값>0, 또는 같은 기기의 level_revive/
    booster_use_* 이벤트가 그 그룹의 [최초, 최후] 이벤트 시간 구간 안에 있으면 helped=True.
    **주의**: level_revive 이벤트는 자체 `level`/`attempt` 필드가 비어 있는 경우가 있어(실측 확인)
    시간 구간으로만 귀속한다 — 구버전일수록 revive/booster 로깅 자체가 누락될 수 있어(§0 예시: item_used가
    0→6으로 뛰는데 level_revive 이벤트가 없는 경우 있음) "helped=True 비율"은 **하한**일 수 있다.
  - "첫 시도": 그 (기기,레벨)에서 관측된 attempt 중 최솟값이 1인 경우만(스트림이 이미 진행된 뒤 시작한
    기기 배제 — af_level_metrics.py의 first_obs와 같은 취지), attempt==1 그룹의 결과를 쓴다.
  - clean_ft = 첫 시도 & not helped. (= af_level_metrics.py의 clean_ft 정의와 같은 것을 의도)

Sub-commands:
  validate   RUN_VERSIONS(기존에 신뢰하는 3개 버전)만으로 이 방법을 돌려 기존 level_metrics.json의
             clean_ft_by_version과 레벨별로 맞대어 본다(상관·평균절대차·부호일치) — 이 방법 자체의 검증.
  all        지정한 버전 목록(기본: 아래 CANDIDATE_VERSIONS) 전부에 대해 레벨별 clean_ft 집계
             → af_calibration/attempt_ft/all_versions.json

입력은 전부 읽기만 함(AF CSV, level_metrics.json). 출력: backend/data/pv_sandbox/af_calibration/attempt_ft/.
사용 (backend 디렉터리, venv): venv/bin/python scripts/af_attempt_ft.py validate|all [--versions ...]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

csv.field_size_limit(10 ** 9)

BACKEND = Path(__file__).resolve().parent.parent
AF_DATA = Path.home() / ".cc-web/projects/sp_meowsgarden/af/data"
OUT = BACKEND / "data/pv_sandbox/af_calibration/attempt_ft"
LEVEL_METRICS = BACKEND / "data/pv_sandbox/af_calibration/level_metrics.json"
MAX_LEVEL = 1500

RUN_VERSIONS = {("android", "1.0.162"), ("android", "1.1.0"), ("ios", "2.1.0")}
# AF 데이터에 level_start>=500 충분량 있는 구버전들(level_metrics.json version_check 기준) — 1.0.146/147은
# v1.10.1025(델타 갱신 비활성화) 이전이라 맵 신뢰도는 별도 판단 필요(이 스크립트는 유저 이벤트만 다룸).
CANDIDATE_VERSIONS = [
    ("android", "1.0.146"), ("android", "1.0.147"), ("android", "1.0.148"), ("android", "1.0.149"),
    ("android", "1.0.151"), ("android", "1.0.152"), ("android", "1.0.156"), ("android", "1.0.160"),
    ("android", "1.0.162"), ("android", "1.1.0"), ("ios", "2.0.160"), ("ios", "2.1.0"),
]


def _int(d, k, default=None):
    try:
        v = d.get(k)
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def ts(t):
    return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")


def load_events(data_dir: Path, versions: set):
    """기기별 (clear/fail/revive/booster) 이벤트만 수집. level_start/retry 불필요."""
    per_dev = defaultdict(list)
    seen = set()
    meta = Counter()
    for plat in ("android", "ios"):
        for name in (f"{plat}_in_app_events.csv.gz", f"{plat}_organic_in_app_events.csv.gz"):
            path = data_dir / name
            if not path.exists():
                continue
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="", errors="replace") as fh:
                r = csv.reader(fh)
                h = next(r)
                iN, iV, iT = h.index("Event Name"), h.index("Event Value"), h.index("Event Time")
                iA, iU = h.index("App Version"), h.index("AppsFlyer ID")
                for row in r:
                    n = row[iN]
                    is_booster = n.startswith("booster_use_")
                    if n not in ("level_clear", "level_fail", "level_revive") and not is_booster:
                        continue
                    ver = row[iA]
                    if (plat, ver) not in versions:
                        continue
                    try:
                        val = json.loads(row[iV]) if row[iV] else {}
                    except ValueError:
                        val = {}
                    if not isinstance(val, dict):
                        val = {}
                    payload = json.dumps(val, sort_keys=True, ensure_ascii=False)
                    key = hashlib.sha1("\x1f".join((row[iU], row[iT], n, payload, ver)).encode()).digest()
                    if key in seen:
                        meta["dup_dropped"] += 1
                        continue
                    seen.add(key)
                    nn = "booster" if is_booster else n
                    dev = hashlib.sha1((plat + row[iU]).encode()).hexdigest()[:16]
                    lvl = _int(val, "level")
                    att = _int(val, "attempt")
                    item = _int(val, "item_used", 0) or 0
                    inf = val.get("is_infinite") == "1"
                    per_dev[dev].append((row[iT], nn, lvl, att, item, inf, plat, ver))
                    meta["rows_kept"] += 1
    return per_dev, meta


def build_attempt_groups(per_dev):
    """(기기,레벨,attempt) 로 clear/fail 묶기. revive/booster는 시간창으로 helped 판정에만 쓴다."""
    out = []  # {dev, L, att, clear, helped, n_fail, ver, t0, t1}
    meta = Counter()
    for dev, ev in per_dev.items():
        ev.sort(key=lambda x: x[0])
        groups = defaultdict(list)  # (L, att) -> list of (t, n, item)
        side = []  # (t, n) for revive/booster
        for t, n, lvl, att, item, inf, plat, ver in ev:
            if inf:
                continue
            if n in ("level_revive", "booster"):
                side.append((t, n))
                continue
            if lvl is None or att is None or not (1 <= lvl <= MAX_LEVEL):
                meta[f"missing_attempt_{n}"] += 1
                continue
            groups[(lvl, att)].append((t, n, item, ver, plat))
        # 기기별 레벨당 관측된 최소 attempt(스트림이 이미 진행중이던 기기 배제용)
        min_att = {}
        for (lvl, att), _ in groups.items():
            min_att[lvl] = min(min_att.get(lvl, att), att)
        for (lvl, att), rows in groups.items():
            rows.sort(key=lambda x: x[0])
            t0, t1 = rows[0][0], rows[-1][0]
            clear = any(n == "level_clear" for _, n, _, _, _ in rows)
            max_item = max(item for _, _, item, _, _ in rows)
            revived = any(n == "level_revive" and t0 <= t <= t1 for t, n in side)
            boosted = any(n == "booster" and t0 <= t <= t1 for t, n in side)
            helped = max_item > 0 or revived or boosted
            first_try = min_att.get(lvl) == 1 and att == 1
            ver, plat = rows[-1][3], rows[-1][4]
            out.append({"dev": dev, "L": lvl, "att": att, "clear": clear, "helped": helped,
                        "first_try": first_try, "plat": plat, "ver": ver})
    return out, meta


def aggregate(groups):
    """레벨×버전별 clean_ft(첫시도·무도움) n/clear/rate."""
    by = defaultdict(lambda: Counter())
    for g in groups:
        if not g["first_try"]:
            continue
        key = (g["plat"], g["ver"], g["L"])
        by[key]["n_any"] += 1
        by[key]["clear_any"] += g["clear"]
        if not g["helped"]:
            by[key]["n_clean"] += 1
            by[key]["clear_clean"] += g["clear"]
    out = {}
    for (plat, ver, L), c in by.items():
        out.setdefault(f"{plat}|{ver}", {})[str(L)] = {
            "n_clean": c["n_clean"], "clear_clean": c["clear_clean"],
            "rate_clean": round(c["clear_clean"] / c["n_clean"], 4) if c["n_clean"] else None,
            "n_any_help_included": c["n_any"], "rate_any_help_included": round(c["clear_any"] / c["n_any"], 4) if c["n_any"] else None,
        }
    return out


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def cmd_validate(a):
    per_dev, meta = load_events(Path(a.data_dir), RUN_VERSIONS)
    print("events kept", meta["rows_kept"], "dup", meta["dup_dropped"], flush=True)
    groups, gmeta = build_attempt_groups(per_dev)
    print("attempt groups", len(groups), dict(gmeta), flush=True)
    agg = aggregate(groups)
    save("validate_run_versions.json", agg)

    lm = json.load(open(LEVEL_METRICS))["levels"]
    existing = {r["level"]: r.get("clean_ft_by_version", {}) for r in lm}

    rows = []
    for key, levels in agg.items():
        for L, v in levels.items():
            ex = existing.get(int(L), {}).get(key)
            if ex is None or v["n_clean"] < 30 or ex["n"] < 30:
                continue
            rows.append((key, int(L), v["rate_clean"], v["n_clean"], ex["rate"], ex["n"]))
    diffs = [new - old for _, _, new, _, old, _ in rows]
    n = len(rows)
    sign_agree = sum(1 for _, _, new, _, old, _ in rows if (new >= 0.5) == (old >= 0.5))
    mad = sum(abs(d) for d in diffs) / n if n else None
    rmse = (sum(d * d for d in diffs) / n) ** 0.5 if n else None
    xs = [r[4] for r in rows]
    ys = [r[2] for r in rows]
    if n > 1:
        mx, my = sum(xs) / n, sum(ys) / n
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in ys)
        r = sxy / ((sxx * syy) ** 0.5) if sxx and syy else None
    else:
        r = None
    worst = sorted(rows, key=lambda r: -abs(r[2] - r[4]))[:10]
    print(json.dumps({
        "n_level_version_pairs": n, "mean_abs_diff": round(mad, 4) if mad else None,
        "rmse": round(rmse, 4) if rmse else None, "pearson_r": round(r, 4) if r else None,
        "sign_agreement_vs_0.5": round(sign_agree / n, 3) if n else None,
        "worst10": [{"key": k, "L": L, "attempt_method_rate": nr, "attempt_n": nn, "original_rate": orr, "orig_n": on}
                    for k, L, nr, nn, orr, on in worst],
    }, ensure_ascii=False, indent=1))


def cmd_all(a):
    versions = set(tuple(v.split("|")) for v in a.versions.split(",")) if a.versions else set(CANDIDATE_VERSIONS)
    per_dev, meta = load_events(Path(a.data_dir), versions)
    print("events kept", meta["rows_kept"], "dup", meta["dup_dropped"], flush=True)
    groups, gmeta = build_attempt_groups(per_dev)
    print("attempt groups", len(groups), dict(gmeta), flush=True)
    agg = aggregate(groups)
    save("all_versions.json", agg)
    for k in sorted(agg):
        n_levels = len(agg[k])
        tot_n = sum(v["n_clean"] for v in agg[k].values())
        print(k, "levels_with_data", n_levels, "total_clean_ft_n", tot_n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(AF_DATA))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(f=cmd_validate)
    pa = sub.add_parser("all")
    pa.add_argument("--versions", default="", help="plat|ver,plat|ver,...")
    pa.set_defaults(f=cmd_all)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
