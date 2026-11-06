"""TILECORE bot shadow — replay BotSimulator.simulate_with_profile calls on the C# bot (tilecore `bs` mode) and log differences.

Plan: claudedocs/PLAN_CSHARP_ACCELERATION_20261102.md §0-A (implement -> shadow -> parity -> speed -> on), stage ①/②.
Same switch family as tilecore_shadow.py (solver A* shadow).

Switch = environment variable ``TILECORE_BOT`` if set, else ``TILECORE``:
  * unset / ``off`` (default): nothing here runs; callers keep their original code path.
  * ``shadow``: the Python result is the service result (unchanged values). The per-game cleared flags of the Python run
    are recorded (RecordingBotSimulator = BotSimulator + a list append in _play_game), the same calls (same profile,
    same rngSeed list seed+i, same max_moves) are queued and replayed on ``tilecore bot`` (mode "gen") by ONE background
    daemon thread, and one JSONL line per (request, profile) is appended to the shadow log.
    Every C# failure (missing binary, crash, timeout, unsupported input) is logged, never raised.
  * ``on``: NOT implemented (gate §0-A not passed) -> treated as ``shadow``.

Reproducibility: python game i of the fast path is reseeded with seed+i, so C# can replay it only when ``seed`` is an int.
``seed=None`` (unseeded random.Random) and ``honor_zero_seed`` with randSeed 0 are not reproducible -> logged as
``skip_*`` lines (counted, never compared). early_termination is fine: game i does not depend on later games, so C# runs
exactly the n games python actually ran.

Other environment variables (all optional):
  TILECORE_BOT_DLL         tilecore.dll (default: ~/tilecore/release/v6/bin/tilecore.dll — frozen release, read only)
  TILECORE_DOTNET          dotnet executable (default: "dotnet" on PATH)
  TILECORE_BOT_SHADOW_LOG  JSONL output (default: ~/tilecore/shadow/bot_shadow_diff.jsonl)
  TILECORE_BOT_TIMEOUT_S   subprocess timeout per request (default 120)
  TILECORE_BOT_THREADS     C# --threads (default 1; jobs of one request run in that many threads)
  TILECORE_BOT_QUEUE       max pending shadow requests (default 16; overflow -> one ``dropped_queue_full`` line)
  TILECORE_BOT_SYNC        "1" = run the shadow inline in the caller thread (tests / offline scripts only)
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from .bot_simulator import BotSimulator

_DEFAULT_DLL = os.path.expanduser("~/tilecore/release/v6/bin/tilecore.dll")
_DEFAULT_LOG = os.path.expanduser("~/tilecore/shadow/bot_shadow_diff.jsonl")
_LOG_LOCK = threading.Lock()
_Q_LOCK = threading.Lock()
_queue: Optional["queue.Queue"] = None
_worker: Optional[threading.Thread] = None


def mode() -> str:
    """off | shadow. ``on`` and shadow both mean shadow; anything else is off."""
    raw = os.environ.get("TILECORE_BOT")
    if raw is None or raw.strip() == "":
        raw = os.environ.get("TILECORE") or "off"
    return "shadow" if raw.strip().lower() in ("shadow", "on") else "off"


# ───────────────────────── python side (recording) ─────────────────────────

class RecordingBotSimulator(BotSimulator):
    """BotSimulator that also remembers the cleared flag of every game it plays.

    _play_game is only called by simulate_with_profile's two game loops (not by rollouts), so
    ``cleared_flags[i]`` = game i. Values of the BotSimulationResult are identical to BotSimulator.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.cleared_flags: List[bool] = []

    def _play_game(self, state, profile):  # noqa: D401 — same signature as BotSimulator._play_game
        final = super()._play_game(state, profile)
        self.cleared_flags.append(bool(final.cleared))
        return final


def run_python_recorded(level_json: Dict[str, Any], profile, iterations: int, max_moves: Optional[int],
                        seed: Optional[int], early_termination: bool = False, honor_zero_seed: bool = False):
    """simulate_with_profile through RecordingBotSimulator. Returns (BotSimulationResult, record dict)."""
    sim = RecordingBotSimulator()
    t0 = time.perf_counter()
    res = sim.simulate_with_profile(level_json=level_json, profile=profile, iterations=iterations, max_moves=max_moves,
                                    seed=seed, honor_zero_seed=honor_zero_seed, early_termination=early_termination)
    rec = {
        "profile": profile_json(profile),
        "seed": seed,
        "iterations_req": iterations,
        "n": res.iterations,
        "cleared": "".join("1" if c else "0" for c in sim.cleared_flags),
        "py_sec": round(time.perf_counter() - t0, 4),
        "early_termination": bool(early_termination),
        "honor_zero_seed": bool(honor_zero_seed),
    }
    return res, rec


def profile_json(profile) -> Dict[str, Any]:
    d = dataclasses.asdict(profile)
    bt = getattr(profile, "bot_type", None)
    d["bot_type"] = getattr(bt, "value", bt)
    return d


def level_hash(level_json: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(level_json, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


# ───────────────────────── C# side ─────────────────────────

def _dll() -> str:
    return os.environ.get("TILECORE_BOT_DLL") or _DEFAULT_DLL


def run_cs_jobs(jobs: List[Dict[str, Any]], timeout_s: Optional[float] = None) -> Dict[str, Any]:
    """Run ``tilecore bot --jobs <tmp> --out <tmp>``. Returns {"ok", "rows", "wall_s", "error"}. Never raises."""
    dll = _dll()
    if not os.path.exists(dll):
        return {"ok": False, "error": f"tilecore_missing:{dll}", "wall_s": 0.0}
    timeout_s = float(timeout_s if timeout_s is not None else (os.environ.get("TILECORE_BOT_TIMEOUT_S") or 120))
    dotnet = os.environ.get("TILECORE_DOTNET") or "dotnet"
    threads = str(max(1, int(os.environ.get("TILECORE_BOT_THREADS") or 1)))
    t0 = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="tilecore_bot_") as td:
            jp, op = os.path.join(td, "jobs.jsonl"), os.path.join(td, "out.jsonl")
            with open(jp, "w", encoding="utf-8") as f:
                for j in jobs:
                    f.write(json.dumps(j, ensure_ascii=False) + "\n")
            argv = [dotnet, dll, "bot", "--jobs", jp, "--out", op, "--threads", threads]
            try:
                p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": f"timeout_{timeout_s:.0f}s", "wall_s": time.perf_counter() - t0}
            except OSError as exc:
                return {"ok": False, "error": f"spawn:{exc}", "wall_s": time.perf_counter() - t0}
            wall = time.perf_counter() - t0
            if p.returncode != 0 or not os.path.exists(op):
                return {"ok": False, "error": f"exit_{p.returncode}:{(p.stderr or '')[-300:]}", "wall_s": wall}
            rows = []
            with open(op, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rows.append(json.loads(line))
            return {"ok": True, "rows": rows, "wall_s": wall, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "wall_s": time.perf_counter() - t0}


def _first_clear(seed: int, cleared: str) -> Optional[int]:
    i = cleared.find("1")
    return None if i < 0 else seed + i


def compare_record(level_json: Dict[str, Any], max_moves: Optional[int], rec: Dict[str, Any],
                   cs_rows: Optional[List[Dict[str, Any]]], cs_error: Optional[str], cs_wall: float,
                   kind: str, ih: str) -> Dict[str, Any]:
    """One log line for one (request, profile)."""
    prof = rec["profile"]
    seed = rec.get("seed")
    n = int(rec.get("n") or 0)
    py_c = rec.get("cleared") or ""
    line: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": kind,
        "input_hash": ih,
        "profile": prof.get("name"),
        "bot_type": prof.get("bot_type"),
        "seed": seed,
        "n": n,
        "max_moves": max_moves,
        "early_termination": rec.get("early_termination"),
        "py": {"any_clear": "1" in py_c, "first_clear_rng": _first_clear(seed, py_c) if isinstance(seed, int) else None,
               "clears": py_c.count("1"), "clear_rate": round(py_c.count("1") / n, 6) if n else 0.0,
               "cleared": py_c, "sec": rec.get("py_sec")},
        "cs_bin": _dll(),
    }
    if cs_error is not None:
        unsupported = cs_error.startswith("unsupported:")
        line["cs"] = {"sec": round(cs_wall, 4), "error": cs_error}
        line["category"] = "cs_unsupported" if unsupported else "cs_error"
        line["unsupported_reason"] = cs_error[len("unsupported:"):].strip() if unsupported else None
        return line
    games = sorted(cs_rows or [], key=lambda r: r.get("game", 0))
    cs_c = "".join("1" if r.get("cleared") else "0" for r in games)
    line["cs"] = {"any_clear": "1" in cs_c, "first_clear_rng": _first_clear(seed, cs_c),
                  "clears": cs_c.count("1"), "clear_rate": round(cs_c.count("1") / n, 6) if n else 0.0,
                  "cleared": cs_c, "sec": round(cs_wall, 4),
                  "game_ms_sum": round(sum(float(r.get("ms") or 0) for r in games), 2)}
    line["unsupported_reason"] = None
    if cs_c == py_c:
        line["category"] = "same"
    else:
        diff = [i for i in range(max(len(cs_c), len(py_c))) if (cs_c[i:i + 1] or "-") != (py_c[i:i + 1] or "-")]
        line["category"] = "mismatch"
        line["first_diff_game"] = diff[0] if diff else None
        line["diff_games"] = len(diff)
    return line


def _job_for(level_json: Dict[str, Any], max_moves: Optional[int], rec: Dict[str, Any], jid: str) -> Dict[str, Any]:
    seed = int(rec["seed"])
    return {"id": jid, "mode": "gen", "profile": rec["profile"], "level": level_json,
            "rng_seeds": [seed + i for i in range(int(rec["n"]))], "max_moves": max_moves, "force_parity": False}


def skip_reason(rec: Dict[str, Any], level_json: Dict[str, Any]) -> Optional[str]:
    if not isinstance(rec.get("seed"), int):
        return "skip_seed_none"
    if rec.get("honor_zero_seed") and not level_json.get("randSeed"):
        return "skip_honor_zero_seed"
    if int(rec.get("n") or 0) <= 0:
        return "skip_no_games"
    return None


def process_request(level_json: Dict[str, Any], max_moves: Optional[int], records: List[Dict[str, Any]],
                    kind: str = "autoplay") -> List[Dict[str, Any]]:
    """Replay all records of one request on C# (one subprocess) and append one line per record. Never raises."""
    out: List[Dict[str, Any]] = []
    try:
        ih = level_hash(level_json)
        todo, jobs = [], []
        for k, rec in enumerate(records):
            sk = skip_reason(rec, level_json)
            if sk:
                out.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "input_hash": ih,
                            "profile": rec.get("profile", {}).get("name"), "seed": rec.get("seed"),
                            "n": rec.get("n"), "category": sk})
                continue
            jid = f"r{k}"
            todo.append((jid, rec))
            jobs.append(_job_for(level_json, max_moves, rec, jid))
        if jobs:
            r = run_cs_jobs(jobs)
            by_id: Dict[str, List[Dict[str, Any]]] = {}
            for row in r.get("rows") or []:
                by_id.setdefault(str(row.get("id")), []).append(row)
            share = r["wall_s"] / len(jobs)          # one process for all jobs: wall split evenly (start-up included)
            for jid, rec in todo:
                rows = by_id.get(jid)
                err = None
                if not r["ok"]:
                    err = r["error"]
                elif not rows:
                    err = "no_output"
                elif len(rows) == 1 and "error" in rows[0]:
                    e = str(rows[0].get("error"))
                    err = ("unsupported: " + e) if rows[0].get("unsupported") else ("error: " + e)
                out.append(compare_record(level_json, max_moves, rec, rows, err, share, kind, ih))
        for line in out:
            _append(line)
    except Exception as exc:  # noqa: BLE001 — shadow must never affect the service
        try:
            _append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "category": "shadow_internal_error",
                     "error": f"{type(exc).__name__}: {exc}"[:300]})
        except Exception:  # noqa: BLE001
            pass
    return out


def _append(line: Dict[str, Any]) -> None:
    path = os.environ.get("TILECORE_BOT_SHADOW_LOG") or _DEFAULT_LOG
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = (json.dumps(line, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    with _LOG_LOCK:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


# ───────────────────────── background queue ─────────────────────────

def _worker_loop(q: "queue.Queue") -> None:
    while True:
        item = q.get()
        try:
            process_request(*item)
        except Exception:  # noqa: BLE001
            pass
        finally:
            q.task_done()


def _get_queue() -> "queue.Queue":
    global _queue, _worker
    with _Q_LOCK:
        if _queue is None or _worker is None or not _worker.is_alive():
            _queue = queue.Queue(maxsize=max(1, int(os.environ.get("TILECORE_BOT_QUEUE") or 16)))
            _worker = threading.Thread(target=_worker_loop, args=(_queue,), name="tilecore-bot-shadow", daemon=True)
            _worker.start()
        return _queue


def submit(level_json: Dict[str, Any], max_moves: Optional[int], records: List[Dict[str, Any]],
           kind: str = "autoplay") -> None:
    """Queue one request for the shadow worker. Returns immediately; never raises."""
    try:
        if not records:
            return
        if (os.environ.get("TILECORE_BOT_SYNC") or "") == "1":
            process_request(level_json, max_moves, records, kind)
            return
        try:
            _get_queue().put_nowait((level_json, max_moves, records, kind))
        except queue.Full:
            _append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "input_hash": level_hash(level_json),
                     "category": "dropped_queue_full", "profiles": [r.get("profile", {}).get("name") for r in records]})
    except Exception:  # noqa: BLE001
        pass


def drain(timeout_s: float = 60.0) -> bool:
    """Wait until the queue is empty (tests / scripts). True if drained."""
    q = _queue
    if q is None:
        return True
    end = time.time() + timeout_s
    while time.time() < end:
        if q.unfinished_tasks == 0:
            return True
        time.sleep(0.05)
    return False


# ───────────────────────── summary ─────────────────────────

def summarize(path: Optional[str] = None) -> Dict[str, Any]:
    """Counts per category/profile from a shadow log (for the parity table)."""
    path = path or os.environ.get("TILECORE_BOT_SHADOW_LOG") or _DEFAULT_LOG
    cats: Dict[str, int] = {}
    per: Dict[str, Dict[str, Any]] = {}
    reasons: Dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            x = json.loads(line)
            c = x.get("category", "?")
            cats[c] = cats.get(c, 0) + 1
            p = per.setdefault(str(x.get("profile")), {"lines": 0, "games": 0, "py_sec": 0.0, "cs_sec": 0.0})
            p["lines"] += 1
            p[c] = p.get(c, 0) + 1
            if c in ("same", "mismatch"):
                p["games"] += int(x.get("n") or 0)
                p["py_sec"] += float(x["py"].get("sec") or 0)
                p["cs_sec"] += float(x["cs"].get("sec") or 0)
            if x.get("unsupported_reason"):
                r = x["unsupported_reason"][:80]
                reasons[r] = reasons.get(r, 0) + 1
    return {"categories": cats, "per_profile": per, "unsupported_reasons": reasons}
