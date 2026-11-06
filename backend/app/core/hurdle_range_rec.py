"""허들 구간 추천(range_rec) 실행·결과 어댑터 — 게임 레포 도구를 별도 프로세스로 돌리고 결과를 화면용으로 정규화.

연결 대상(게임 레포, 읽기만): <game_repo>/tools/dda_hurdle_mix/range_rec/run.sh
  - 출력 = REPORT.md · key_*.txt · levels.csv · bands20.csv · hurdle_levels.csv · result.json
  - 맵툴 실행분은 --out 으로 맵툴 폴더(backend/data/hurdle_rec/runs/<id>/)에 쓴다 → 게임 레포 파일 생성·수정 없음.
  - 게임 레포에서 수동 실행한 결과(range_rec/out/*/result.json)도 목록에 읽기 전용으로 보인다.

장시간 작업 = 파일 상태 + 별도 프로세스(start_new_session) — 맵툴 재시작에도 계산은 계속되고 상태는 파일로 복구.
  jobs/<id>.json(메타) · jobs/<id>.log(stdout+stderr) · jobs/<id>.exit(종료 코드, 래퍼 셸이 기록)
  history.jsonl = 실행 기록(추가만).

결과 스키마: 도구 result.json 이 '계약 v1'(strings/levels/bands …)이면 그대로, 아니면(v0) result.json + CSV 로 재구성.
필드 접근은 전부 normalize() 한 곳 — 도구 스키마가 바뀌면 여기만 고친다. 게임부스트 접속 없음.
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import os
import re
import signal
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

_THIS = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(_THIS, "..", "..", "data", "hurdle_rec"))
RUNS_DIR = os.path.join(DATA_DIR, "runs")
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
HISTORY = os.path.join(DATA_DIR, "history.jsonl")
TOOL_REL = os.path.join("tools", "dda_hurdle_mix", "range_rec")

_lock = threading.Lock()
_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VER_RE = re.compile(r"^[0-9][0-9.]*$")


# ── 경로 ────────────────────────────────────────────────────────────────────
def game_repo() -> str:
    try:
        from ..config import get_settings
        p = getattr(get_settings(), "game_repo_path", None)
    except Exception:  # noqa: BLE001
        p = None
    return os.path.expanduser(p or os.environ.get("GAME_REPO_PATH") or "~/sp_meowsgarden")


def tool_dir() -> str:
    return os.path.join(game_repo(), TOOL_REL)


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 좀비(부모=uvicorn 이 아직 wait 안 함)면 끝난 것으로 본다
    try:
        r = os.waitpid(int(pid), os.WNOHANG)
        if r[0] != 0:
            return False
    except ChildProcessError:
        pass
    return True


# ── 도구 정보 ───────────────────────────────────────────────────────────────
def tool_info() -> Dict[str, Any]:
    td = tool_dir()
    cfg = _read_json(os.path.join(td, "config.json")) or {}
    return {
        "gameRepo": game_repo(),
        "toolDir": td,
        "runSh": os.path.join(td, "run.sh"),
        "exists": os.path.isfile(os.path.join(td, "run.sh")),
        "defaultVersions": cfg.get("versions") or [],
        "platform": cfg.get("platform"),
        "afDir": os.path.expanduser("~/.cc-web/projects/sp_meowsgarden/af"),
    }


# ── 실행 ────────────────────────────────────────────────────────────────────
def _job_paths(job_id: str) -> Tuple[str, str, str]:
    return (os.path.join(JOBS_DIR, f"{job_id}.json"), os.path.join(JOBS_DIR, f"{job_id}.log"),
            os.path.join(JOBS_DIR, f"{job_id}.exit"))


def _jobs() -> List[Dict[str, Any]]:
    out = []
    for p in sorted(glob.glob(os.path.join(JOBS_DIR, "*.json"))):
        j = _read_json(p)
        if j:
            out.append(j)
    return out


def running_job() -> Optional[Dict[str, Any]]:
    for j in reversed(_jobs()):
        if j.get("status") == "running":
            v = job_view(j["id"])
            if v and v["status"] == "running":
                return v
    return None


def start(since: Optional[str], until: Optional[str], versions: Optional[List[str]],
          keep_dda_var: bool = False, memo: str = "") -> Dict[str, Any]:
    """run.sh 를 별도 프로세스로 시작. 이미 실행 중이면 RuntimeError."""
    for d, nm in ((since, "since"), (until, "until")):
        if d and not _DATE_RE.match(d):
            raise ValueError(f"{nm} 형식은 YYYY-MM-DD")
    vers = [v.strip() for v in (versions or []) if v and v.strip()]
    for v in vers:
        if not _VER_RE.match(v):
            raise ValueError(f"버전 형식 오류: {v}")
    info = tool_info()
    if not info["exists"]:
        raise FileNotFoundError(f"run.sh 없음: {info['runSh']}")
    with _lock:
        cur = running_job()
        if cur:
            raise RuntimeError(f"이미 실행 중: {cur['id']}")
        job_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(RUNS_DIR, job_id)
        os.makedirs(JOBS_DIR, exist_ok=True)
        os.makedirs(RUNS_DIR, exist_ok=True)
        meta_p, log_p, exit_p = _job_paths(job_id)
        args = ["--out", out_dir]
        if since:
            args += ["--since", since]
        if until:
            args += ["--until", until]
        if vers:
            args += ["--versions", ",".join(vers)]
        if keep_dda_var:
            args += ["--keep-dda-var"]
        # 래퍼 셸: 종료 코드를 파일로 남긴다(맵툴이 재시작돼 wait 못 해도 판정 가능)
        cmd = ["/bin/bash", "-c", 'bash "$0" "$@"; echo $? > "' + exit_p + '"', info["runSh"], *args]
        logf = open(log_p, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=info["gameRepo"], stdout=logf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        logf.close()
        meta = {
            "id": job_id, "status": "running", "pid": proc.pid, "startedAt": _now(), "finishedAt": None,
            "params": {"since": since, "until": until, "versions": vers, "keepDdaVar": keep_dda_var},
            "memo": memo, "outDir": out_dir, "log": log_p, "cmd": ["run.sh", *args], "exitCode": None,
        }
        _write_json(meta_p, meta)
        _append_history({"event": "start", **{k: meta[k] for k in ("id", "startedAt", "params", "memo", "outDir")}})
        return job_view(job_id) or meta


def stop(job_id: str) -> Dict[str, Any]:
    v = job_view(job_id)
    if not v:
        raise FileNotFoundError(job_id)
    if v["status"] == "running" and v.get("pid"):
        try:
            os.killpg(os.getpgid(int(v["pid"])), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        meta_p, _, _ = _job_paths(job_id)
        m = _read_json(meta_p) or {}
        m.update(status="stopped", finishedAt=_now())
        _write_json(meta_p, m)
        _append_history({"event": "stop", "id": job_id, "at": m["finishedAt"]})
    return job_view(job_id) or v


def _append_history(rec: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def history(limit: int = 100) -> List[Dict[str, Any]]:
    try:
        with open(HISTORY, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except FileNotFoundError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def _tail(path: str, n: int = 40) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [l.rstrip("\n") for l in f.readlines()[-n:]]
    except FileNotFoundError:
        return []


def _tool_status(out_dir: str) -> Optional[Dict[str, Any]]:
    """도구가 출력 폴더에 쓰는 실행 상태 파일(계약 확정 전: 이름 후보 여러 개)."""
    for nm in ("status.json", "progress.json", "state.json", "run_status.json"):
        s = _read_json(os.path.join(out_dir, nm))
        if s:
            return s
    return None


def job_view(job_id: str) -> Optional[Dict[str, Any]]:
    if not _ID_RE.match(job_id or ""):
        return None
    meta_p, log_p, exit_p = _job_paths(job_id)
    m = _read_json(meta_p)
    if not m:
        return None
    if m.get("status") == "running":
        ec = None
        try:
            with open(exit_p) as f:
                ec = int(f.read().strip() or "-1")
        except (FileNotFoundError, ValueError):
            pass
        alive = _pid_alive(m.get("pid"))
        if ec is not None or not alive:
            has_res = os.path.isfile(os.path.join(m["outDir"], "result.json"))
            if ec is None:
                ec = 0 if has_res else -1
            m.update(status="done" if ec == 0 and has_res else "failed", exitCode=ec, finishedAt=_now())
            _write_json(meta_p, m)
            _append_history({"event": "finish", "id": job_id, "status": m["status"], "exitCode": ec, "at": m["finishedAt"]})
    tail = _tail(log_p)
    ts = _tool_status(m["outDir"])
    # 진행 단계 추정: 도구 상태 파일 우선, 없으면 로그 마지막 줄
    ts = ts or {}
    phase = ts.get("message") or ts.get("step") or (tail[-1] if tail else "")
    started = dt.datetime.fromisoformat(m["startedAt"])
    end = dt.datetime.fromisoformat(m["finishedAt"]) if m.get("finishedAt") else dt.datetime.now()
    return {**m, "phase": phase, "pct": ts.get("pct"), "toolState": ts.get("state"), "toolStatus": ts or None, "logTail": tail,
            "elapsedSec": round((end - started).total_seconds(), 1)}


# ── 결과 목록 ───────────────────────────────────────────────────────────────
def _runs_index() -> List[Dict[str, Any]]:
    """맵툴 실행분 + 게임 레포 수동 실행분. id = '<source>:<폴더명>'."""
    out = []
    for src, root in (("maptool", RUNS_DIR), ("game", os.path.join(tool_dir(), "out"))):
        for p in glob.glob(os.path.join(root, "*", "result.json")):
            d = os.path.dirname(p)
            out.append({"id": f"{src}:{os.path.basename(d)}", "source": src, "dir": d, "mtime": os.path.getmtime(p)})
    out.sort(key=lambda r: r["mtime"])
    return out


def list_runs() -> List[Dict[str, Any]]:
    res = []
    for r in _runs_index():
        j = _read_json(os.path.join(r["dir"], "result.json")) or {}
        s = _strings(j)
        res.append({"id": r["id"], "source": r["source"], "dir": r["dir"], "runAt": _run_at(j), "schema": _schema(j),
                    "cons": {"items": s["conservative"].get("items"), "chars": s["conservative"].get("chars")},
                    "aggr": {"items": s["aggressive"].get("items"), "chars": s["aggressive"].get("chars")}})
    return res


def _resolve(run_id: Optional[str]) -> Optional[Dict[str, Any]]:
    idx = _runs_index()
    if not idx:
        return None
    if not run_id or run_id == "latest":
        return idx[-1]
    for r in idx:
        if r["id"] == run_id:
            return r
    return None


# ── 정규화 (도구 스키마 접근은 여기만) ──────────────────────────────────────
def _run_at(j: Dict[str, Any]) -> Optional[str]:
    return j.get("generatedAt") or j.get("run_at") or j.get("runAt")


def _schema(j: Dict[str, Any]) -> str:
    if isinstance(j.get("schema"), str):
        return j["schema"]
    return "v1" if "strings" in j else "v0"


def expand_legacy(key: str) -> Dict[int, str]:
    """`174-175:harder,148:hard` → {레벨: 강도}, 앞 항목 우선."""
    eff: Dict[int, str] = {}
    for t in (key or "").split(","):
        t = t.strip()
        if not t or ":" not in t:
            continue
        r, p = t.split(":", 1)
        a, _, b = r.partition("-")
        for L in range(int(a), int(b or a) + 1):
            eff.setdefault(L, p.strip())
    return eff


def expand_grouped(key: str) -> Dict[int, str]:
    """`harder=174-175,196;hard=148` → {레벨: 강도}, 앞 묶음·앞 항목 우선."""
    eff: Dict[int, str] = {}
    for grp in (key or "").split(";"):
        if not grp.strip() or "=" not in grp:
            continue
        p, _, body = grp.partition("=")
        for t in body.split(","):
            t = t.strip()
            if not t:
                continue
            a, _, b = t.partition("-")
            for L in range(int(a), int(b or a) + 1):
                eff.setdefault(L, p.strip())
    return eff


def legacy_to_grouped(key: str) -> str:
    """기존 형식 → 묶음 형식(강도 첫 등장 순·항목 순서 유지). 변환 후 펼친 결과가 같을 때만 반환(아니면 '')."""
    order: List[str] = []
    groups: Dict[str, List[str]] = {}
    for t in (key or "").split(","):
        t = t.strip()
        if not t or ":" not in t:
            continue
        r, p = t.split(":", 1)
        p = p.strip()
        if p not in groups:
            order.append(p)
            groups[p] = []
        groups[p].append(r.strip())
    g = ";".join(f"{p}={','.join(groups[p])}" for p in order)
    return g if expand_grouped(g) == expand_legacy(key) else ""


def _compress(levels) -> str:
    out: List[List[int]] = []
    for L in sorted(set(levels)):
        if out and out[-1][1] + 1 == L:
            out[-1][1] = L
        else:
            out.append([L, L])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def _strings(j: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    res: Dict[str, Dict[str, Any]] = {}
    for name, short in (("conservative", "cons"), ("aggressive", "aggr")):
        if "strings" in j:
            s = dict(j["strings"].get(name) or {})
            legacy = s.get("legacy") or ""
            grouped = s.get("grouped") or ""
            k = (j.get("keys") or {}).get(short) or {}
            src = "tool"
        else:
            k = (j.get("keys") or {}).get(short) or {}
            legacy = k.get("key") or ""
            grouped = ""
            s = {}
            src = "maptool"
        if not grouped and legacy:
            grouped = legacy_to_grouped(legacy)
            src = "maptool"
        eff = expand_grouped(grouped) if grouped else expand_legacy(legacy)
        res[name] = {
            "grouped": grouped, "legacy": legacy, "groupedSource": src,
            "items": s.get("items", k.get("items")), "chars": len(grouped),
            "legacyChars": len(legacy), "levels": len(eff),
            "byPreset": {p: sum(1 for v in eff.values() if v == p) for p in sorted(set(eff.values()))},
            "withData": s.get("with_data", s.get("withData", k.get("with_data"))),
            "missing": s.get("missingData", s.get("missing", k.get("missing"))) or [],
            "legacyItems": s.get("legacyItems", k.get("items")),
            "effect": s.get("effect"),
            "ranges": s.get("ranges", k.get("ranges")) or [],
            "valid": s.get("valid", k.get("valid")),
            "groupedLegacySame": (expand_grouped(grouped) == expand_legacy(legacy)) if grouped and legacy else None,
            "equivalent": s.get("equivalent"),          # 도구가 확인한 묶음≡기존 형식 동등성(없으면 None)
            "groupedMethod": s.get("groupedMethod"),
        }
    return res


def _f(x) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _read_csv(path: str) -> List[Dict[str, str]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def _band_of(L: int, ranges: List[List[int]]) -> Optional[Tuple[int, int]]:
    for a, b in ranges:
        if a <= L <= b:
            return (a, b)
    return None


def _levels_v0(d: str, j: Dict[str, Any], strings, bands_by: Dict[Tuple[int, int], Dict[str, Any]]) -> List[Dict[str, Any]]:
    effc = expand_legacy(strings["conservative"]["legacy"])
    effa = expand_legacy(strings["aggressive"]["legacy"])
    rc = strings["conservative"]["ranges"]
    ra = strings["aggressive"]["ranges"]
    singles = set(int(x) for x in (j.get("singles") or []))
    out = []
    for r in _read_csv(os.path.join(d, "levels.csv")):
        L = int(r["level"])
        gap = _f(r.get("gap_design"))
        judge = r.get("judge") or ""
        excluded = ""
        if judge.startswith("제외"):
            excluded = judge
        elif r.get("map_changed") == "1":
            excluded = "맵 변경 레벨(단일 후보 제외)"
        elif judge == "표본부족":
            excluded = "표본 부족"
        reasons = []
        for nm, eff, rng in (("보수", effc, rc), ("적극", effa, ra)):
            p = eff.get(L)
            if not p:
                continue
            band = _band_of(L, rng)
            if L in singles and band is None:
                reasons.append(f"{nm}: 단일 {p} — 실측 {_pp(_f(r.get('ftc')))} vs 설계 기대 {_pp(_f(r.get('exp_design')))} (+{_pp(gap)}p)")
            elif band:
                b = bands_by.get(band) or {}
                fill = "" if judge == "쉬움" else " · 개별로는 기준 미달 — 구간을 채우려고 포함"
                reasons.append(f"{nm}: 구간 {band[0]}-{band[1]} {p} — 구간 실측 {_pp(b.get('actual'))} vs 주변 {_pp(b.get('surround'))} "
                               f"(+{_pp(b.get('gap'))}p){fill}")
            else:
                reasons.append(f"{nm}: {p}")
        out.append({
            "level": L, "difficulty": _f(r.get("difficulty")), "ftRuns": int(_f(r.get("ft_runs")) or 0),
            "actual": _f(r.get("ftc")), "ciLo": _f(r.get("ftc_lo")), "ciHi": _f(r.get("ftc_hi")),
            "expDesign": _f(r.get("exp_design")), "expBot": _f(r.get("exp_bot")), "expNeighbor": _f(r.get("exp_neighbor")),
            "gapDesign": gap, "judge": judge, "candidate": r.get("cand") == "1",
            "mapChanged": r.get("map_changed") == "1", "hardOk": r.get("hard_ok") == "1", "harderOk": r.get("harder_ok") == "1",
            "plan": {"conservative": effc.get(L), "aggressive": effa.get(L)},
            "bandCons": list(_band_of(L, rc) or []) or None, "bandAggr": list(_band_of(L, ra) or []) or None,
            "single": L in singles, "reason": " / ".join(reasons), "excluded": excluded,
            "quitNoEnd": _f(r.get("quit_noend")), "botOrig": _f(r.get("bot_orig")),
        })
    return out


def _pp(x) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def _bands_v0(d: str, j: Dict[str, Any], strings) -> List[Dict[str, Any]]:
    cfg = (j.get("config") or {}).get("band") or {}
    rc = [tuple(x) for x in strings["conservative"]["ranges"]]
    ra = [tuple(x) for x in strings["aggressive"]["ranges"]]
    out = []
    for r in _read_csv(os.path.join(d, "bands20.csv")):
        lo, hi = int(r["lo"]), int(r["hi"])
        rel = _f(r.get("rel"))
        try:
            ver = json.loads(r.get("ver_rel") or "{}")
        except json.JSONDecodeError:
            ver = {}
        pc, pa = (lo, hi) in rc or any(a <= lo and hi <= b for a, b in rc), (lo, hi) in ra or any(a <= lo and hi <= b for a, b in ra)
        why = []
        if rel is not None:
            why.append(f"실측 {_pp(_f(r.get('ftc')))} vs 주변 {_pp(_f(r.get('neighbor')))} ({rel * 100:+.1f}%p, 첫 시도 판 {int(_f(r.get('ft_runs')) or 0):,})")
        if ver:
            why.append("버전별 " + " · ".join(f"{k} {v:+.1f}" for k, v in ver.items()))
        if pc or pa:
            why.append("통과: " + "·".join(x for x, ok in (("보수", pc), ("적극", pa)) if ok))
        elif lo < int(cfg.get("min_level") or 0):
            why.append(f"L{cfg.get('min_level')} 미만 — 구간 판정 대상 아님")
        out.append({"start": lo, "end": hi, "actual": _f(r.get("ftc")), "ciLo": _f(r.get("ftc_lo")), "ciHi": _f(r.get("ftc_hi")),
                    "surround": _f(r.get("neighbor")), "gap": rel, "ftRuns": int(_f(r.get("ft_runs")) or 0),
                    "verRel": ver, "verAllPos": r.get("ver_all_pos") == "1",
                    "easyLevels": int(_f(r.get("easy_levels")) or 0), "hardLevels": int(_f(r.get("hard_levels")) or 0),
                    "passCons": pc, "passAggr": pa, "pass": pc or pa, "reason": " · ".join(why)})
    return out


def _hurdle_v0(d: str) -> List[Dict[str, Any]]:
    out = []
    for r in _read_csv(os.path.join(d, "hurdle_levels.csv")):
        out.append({"level": int(r["level"]), "strength": r.get("strength"), "runs": int(_f(r.get("runs")) or 0),
                    "ftc": _f(r.get("ftc")), "abandon": _f(r.get("abandon")), "baseFtc": _f(r.get("base_ftc")),
                    "baseAbandon": _f(r.get("base_abandon")), "removeCandidate": r.get("remove_candidate") or ""})
    return out


EXCLUDE_LABEL = {"level1": "L1", "boss": "보스", "first": "기믹 첫 등장", "map_changed": "맵 변경", "rest": "휴식 레벨(difficulty≥80)",
                 "n_small": "표본 부족", "no_data": "허들 데이터 없음(게임이 자동 제외)"}


def _levels_v1(j: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for r in j["levels"]:
        exc = r.get("excluded") or []
        if isinstance(exc, list):
            exc_codes = list(exc)
            exc_txt = " · ".join(EXCLUDE_LABEL.get(x, x) for x in exc)
        else:
            exc_codes, exc_txt = [], str(exc)
        out.append({
            "level": r["level"], "difficulty": r.get("difficulty"), "ftRuns": r.get("nFirst") or 0,
            "actual": r.get("actual"), "ciLo": r.get("ciLo"), "ciHi": r.get("ciHi"),
            "expDesign": r.get("expDesign"), "expBot": r.get("expBot"), "expNeighbor": r.get("expNeighbor"),
            "gapDesign": r.get("gapDesign"), "judge": r.get("judge"),
            "plan": {"conservative": r.get("presetConservative"), "aggressive": r.get("presetAggressive")},
            "reason": r.get("reason") or "", "excluded": exc_txt, "excludedCodes": exc_codes,
            "byVersion": r.get("byVersion"), "abandon": r.get("abandon"), "botOrig": r.get("botOrig"), "hasData": r.get("hasData"),
        })
    return out


def _bands_v1(j: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for b in j["bands"]:
        ps = b.get("pass")
        pc = bool(ps.get("conservative")) if isinstance(ps, dict) else bool(ps)
        pa = bool(ps.get("aggressive")) if isinstance(ps, dict) else bool(ps)
        out.append({"start": b["start"], "end": b["end"], "actual": b.get("actual"), "ciLo": b.get("ciLo"), "ciHi": b.get("ciHi"),
                    "surround": b.get("surround"), "gap": b.get("gap"), "gapCompared": b.get("gapCompared"),
                    "ftRuns": b.get("nFirst") or 0, "verRel": {k: v * 100 for k, v in (b.get("versionGap") or {}).items()},
                    "passCons": pc, "passAggr": pa, "pass": pc or pa, "reason": b.get("reason") or ""})
    return out


def _hurdle_v1(j: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"level": h["level"], "strength": h.get("preset"), "runs": h.get("runs") or 0, "ftc": h.get("actual"),
             "abandon": h.get("abandon"), "baseFtc": h.get("baseActual"), "baseAbandon": h.get("baseAbandon"),
             "removeCandidate": h.get("removeReason") or ""} for h in (j.get("hurdleRuns") or [])]


def _data_sources(j: Dict[str, Any]) -> Dict[str, Any]:
    ds = j.get("dataSources")
    if ds:
        p = j.get("params") or {}
        return {"platform": p.get("platform"), "versions": p.get("versions"), "since": p.get("since"), "until": p.get("until"),
                "tmin": ds.get("dataStart"), "tmax": ds.get("dataEnd"), "runs": ds.get("runs"), "dup": ds.get("dupRows"),
                "files": [f.get("path") if isinstance(f, dict) else f for f in (ds.get("afFiles") or [])],
                "skip": ds.get("skipped") or {},
                "byVersion": {v: [x.get("runs"), x.get("nFirst")] for v, x in (ds.get("byVersion") or {}).items()},
                "raw": (ds.get("levelRaw") or {}).get("path"), "hurdleData": (ds.get("hurdleData") or {}).get("path"),
                "botOrig": ds.get("botOrig")}
    a, m = j.get("args") or {}, j.get("meta") or {}
    return {"platform": a.get("platform"), "versions": a.get("versions"), "since": a.get("since"), "until": a.get("until"),
            "tmin": m.get("tmin"), "tmax": m.get("tmax"), "runs": m.get("runs"), "dup": m.get("dup"),
            "files": m.get("files") or [], "skip": j.get("skip") or {}, "byVersion": j.get("by_version") or {},
            "raw": a.get("raw"), "hurdleData": a.get("hurdle_data"), "botOrig": a.get("bot_orig")}


def _diff(old: Dict[int, str], new: Dict[int, str]) -> Dict[str, Any]:
    add = [L for L in new if L not in old]
    rem = [L for L in old if L not in new]
    chg = [L for L in new if L in old and new[L] != old[L]]
    return {"same": old == new, "added": _compress(add), "removed": _compress(rem), "changed": _compress(chg),
            "nAdd": len(add), "nRem": len(rem), "nChg": len(chg)}


def normalize(entry: Dict[str, Any]) -> Dict[str, Any]:
    d = entry["dir"]
    j = _read_json(os.path.join(d, "result.json")) or {}
    schema = _schema(j)
    strings = _strings(j)
    if isinstance(j.get("bands"), list) and j["bands"] and "start" in j["bands"][0]:
        bands = _bands_v1(j)
    else:
        bands = _bands_v0(d, j, strings)
    bands_by = {(b["start"], b["end"]): b for b in bands}
    # 구간 추천 범위(40레벨 등)는 20레벨 칸 여러 개 — 합산 값 대신 첫 칸 기준이 아닌 평균(판 가중)으로 근거 생성
    for rng in strings["conservative"]["ranges"] + strings["aggressive"]["ranges"]:
        a, b = int(rng[0]), int(rng[1])
        if (a, b) in bands_by:
            continue
        sub = [x for x in bands if a <= x["start"] and x["end"] <= b and x.get("actual") is not None]
        n = sum(x["ftRuns"] for x in sub)
        if sub and n:
            act = sum(x["actual"] * x["ftRuns"] for x in sub) / n
            sur = sum((x.get("surround") or 0) * x["ftRuns"] for x in sub) / n
            bands_by[(a, b)] = {"actual": act, "surround": sur, "gap": act - sur}
    if isinstance(j.get("levels"), list) and j["levels"] and "level" in j["levels"][0]:
        levels = _levels_v1(j)
    else:
        levels = _levels_v0(d, j, strings, bands_by)
    hurdle = _hurdle_v1(j) if "hurdleRuns" in j else _hurdle_v0(d)
    # 직전 실행 대비(맵툴 계산 — 맵툴·게임 레포 실행분 통틀어 바로 앞 결과)
    idx = _runs_index()
    prev = None
    for i, r in enumerate(idx):
        if r["id"] == entry["id"] and i > 0:
            prev = idx[i - 1]
    diff: Dict[str, Any] = {"prevRunId": prev["id"] if prev else None, "tool": j.get("diffFromPrev") or j.get("diff_from_prev")}
    if prev:
        ps = _strings(_read_json(os.path.join(prev["dir"], "result.json")) or {})
        for nm in ("conservative", "aggressive"):
            o = expand_grouped(ps[nm]["grouped"]) if ps[nm]["grouped"] else expand_legacy(ps[nm]["legacy"])
            n = expand_grouped(strings[nm]["grouped"]) if strings[nm]["grouped"] else expand_legacy(strings[nm]["legacy"])
            diff[nm] = _diff(o, n)
    _attach_checks(j, strings, levels)
    return {
        "id": entry["id"], "source": entry["source"], "dir": d, "schema": schema,
        "runAt": _run_at(j), "dataSources": _data_sources(j),
        "params": j.get("params") or {"config": (j.get("args") or {}).get("config")},
        "strings": strings, "levels": levels, "bands": bands, "hurdleLevels": hurdle,
        "notes": j.get("notes") or [], "removalCandidates": j.get("removalCandidates") or [],
        "effect": j.get("effect"), "sensitivity": j.get("sensitivity"), "diffFromPrev": diff,
        "reportPath": os.path.join(d, "REPORT.md") if os.path.isfile(os.path.join(d, "REPORT.md")) else None,
    }


def _attach_checks(j: Dict[str, Any], strings: Dict[str, Dict[str, Any]], levels: List[Dict[str, Any]]) -> None:
    """각 안 문자열에 자동 검증 4항목(strings[plan].check) — 규칙: app.core.hurdle_active_key."""
    from . import hurdle_active_key as K
    import hashlib
    data_path = os.path.join(game_repo(), "Assets", "StreamingAssets", "Dda", "level_hurdle.json")
    data = K.load_hurdle_data(data_path)
    run_sha = ((j.get("dataSources") or {}).get("hurdleData") or {}).get("sha256")
    cur_sha = None
    try:
        with open(data_path, "rb") as f:
            cur_sha = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        pass
    max_level = int((j.get("config") or {}).get("max_level") or max((l["level"] for l in levels), default=0))
    for nm, s in strings.items():
        intent = {int(l["level"]): (l.get("plan") or {}).get(nm) for l in levels}
        chk = K.check_string(s["grouped"], intent, max_level, data, data_path, s.get("equivalent"))
        chk["data"]["sameAsRun"] = (run_sha == cur_sha) if run_sha and cur_sha else None
        s["check"] = chk


def get_result(run_id: Optional[str]) -> Optional[Dict[str, Any]]:
    e = _resolve(run_id)
    return normalize(e) if e else None


def get_report(run_id: Optional[str]) -> Optional[str]:
    e = _resolve(run_id)
    if not e:
        return None
    try:
        with open(os.path.join(e["dir"], "REPORT.md"), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
