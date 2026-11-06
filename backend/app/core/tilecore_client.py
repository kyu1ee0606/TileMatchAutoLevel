"""tilecore serve client — resident C# worker (stdin/stdout JSONL) with Python fallback.

Plan: claudedocs/PLAN_CSHARP_BATCH_LIVE_20261106.md §2 stage 1-B. Protocol: proto 1 (plan "serve 프로토콜 초안";
canonical doc ~/tilecore/docs/SERVE_PROTOCOL.md once it exists).

Switches (per path; the shared TILECORE variable is NOT read — plan F14):
  TILECORE_GEN / TILECORE_SWEEP = off|shadow|on   (default off)
  TILECORE_SERVE_DLL      default ~/tilecore/release/v7/bin/tilecore.dll
  TILECORE_SERVE_CMD      full argv override (shell-split), tests only; replaces ``dotnet <dll> serve --threads N``
  TILECORE_DOTNET         dotnet executable (default "dotnet")
  TILECORE_SERVE_SHA      expected dll_sha256 from hello (mismatch -> C# disabled in this process + warning)
  TILECORE_SERVE_ENGINE   expected engine prefix (default "tilecore/7.")
  TILECORE_SERVE_THREADS_GEN (1) / TILECORE_SERVE_THREADS_SWEEP (4)
  TILECORE_TIMEOUT_S (10)  per-request deadline; on expiry the process is killed (no cancel op), restarted later
  TILECORE_START_TIMEOUT_S (15)  wait for hello
  TILECORE_SHADOW_SAMPLE (0)  in ``on`` mode: fraction of calls also re-run in Python and compared
  TILECORE_SHADOW_DIR     default ~/tilecore/shadow  ({path}_shadow_diff.jsonl)

Every C# problem (unavailable, timeout, crash, unsupported, error, bad version) => the same call runs in Python.
Callers are NOT changed by this module; ``simulate`` mirrors ``BotSimulator.simulate_with_profile``.
"""
from __future__ import annotations

import atexit
import concurrent.futures as cf
import dataclasses
import hashlib
import itertools
import json
import logging
import os
import random
import shlex
import statistics
import subprocess
import threading
import time
from typing import Dict, List, Optional

from .bot_simulator import BotSimulationResult, BotSimulator

logger = logging.getLogger(__name__)

PROTO = 1
_DEFAULT_DLL = "~/tilecore/release/v7/bin/tilecore.dll"
_DEFAULT_SHADOW_DIR = "~/tilecore/shadow"
_BACKOFF = (1.0, 2.0, 5.0, 15.0, 60.0)
_PATH_ENV = {"gen": "TILECORE_GEN", "sweep": "TILECORE_SWEEP"}
_DEFAULT_THREADS = {"gen": 1, "sweep": 4}


class ServeUnavailable(Exception):
    """No usable worker right now (backing off, version mismatch, crashed, EOF)."""


class ServeUnsupported(Exception):
    """C# answered unsupported:true."""


class ServeError(Exception):
    """C# answered ok:false (not unsupported) or a malformed reply."""


class ServeSerializeError(ServeError):
    """Request payload not JSON-serializable even after set/frozenset conversion (python fallback, own counter)."""


def _json_default(o):
    """C# request serialization only (python-side objects stay untouched): set/frozenset -> sorted list
    (repr-sorted if elements are not mutually orderable). Anything else -> TypeError -> serialize_error."""
    if isinstance(o, (set, frozenset)):
        try:
            return sorted(o)
        except TypeError:
            return sorted(o, key=repr)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


class ServeDeadline(ServeError):
    """C# answered kind:"deadline" (serve's own budget ran out; process is fine, counted as timeout)."""


def path_mode(path: str) -> str:
    raw = (os.environ.get(_PATH_ENV.get(path, "")) or "off").strip().lower()
    return raw if raw in ("off", "shadow", "on") else "off"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


# ───────────────────────── counters ─────────────────────────
_COUNTER_KEYS = ("cs_ok", "unsupported", "error", "timeout", "fallback", "shadow_same", "shadow_mismatch",
                 "serialize_error")
_counters: Dict[str, Dict[str, int]] = {}
_clock = threading.Lock()


def _count(path: str, key: str, n: int = 1) -> None:
    with _clock:
        c = _counters.setdefault(path, {k: 0 for k in _COUNTER_KEYS})
        c[key] += n


def counters() -> Dict[str, Dict[str, int]]:
    with _clock:
        return {p: dict(c) for p, c in _counters.items()}


def reset_counters() -> None:
    with _clock:
        _counters.clear()


# ───────────────────────── worker ─────────────────────────
class ServeWorker:
    """One resident ``tilecore serve`` process; lazy start; thread-safe ``request``."""

    def __init__(self, argv: List[str], *, expect_engine: str = "tilecore/7.", expect_sha: Optional[str] = None,
                 start_timeout_s: float = 15.0):
        self.argv = argv
        self.expect_engine = expect_engine
        self.expect_sha = expect_sha
        self.start_timeout_s = start_timeout_s
        self._lock = threading.RLock()         # guards proc lifecycle + writes
        self._proc: Optional[subprocess.Popen] = None
        self._pending: Dict[str, cf.Future] = {}
        self._plock = threading.Lock()
        self._wlock = threading.Lock()         # serializes pipe writes (taken outside _lock)
        self._ids = itertools.count(1)
        self._hello: Optional[dict] = None
        self._hello_ev = threading.Event()
        self._disabled: Optional[str] = None   # permanent: version mismatch / cannot spawn
        self._fails = 0
        self._retry_at = 0.0
        self.starts = 0
        self.pid_owner = os.getpid()

    @property
    def disabled_reason(self) -> Optional[str]:
        return self._disabled

    def hello(self) -> Optional[dict]:
        return self._hello

    def _fail_all(self, exc: Exception) -> None:
        with self._plock:
            items, self._pending = list(self._pending.values()), {}
        for f in items:
            if not f.done():
                f.set_exception(exc)

    @staticmethod
    def _reap(p: subprocess.Popen) -> None:
        """kill + wait + close pipes. kill comes first so a writer blocked on a full pipe is released (BrokenPipe)."""
        try:
            p.kill()
        except OSError:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass
        for s in (p.stdin, p.stdout):
            try:
                if s:
                    s.close()
            except Exception:
                pass

    def _kill_locked(self, why: str) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            self._reap(p)
        self._hello = None
        self._fail_all(ServeUnavailable(why))

    def _note_failure_locked(self) -> None:
        self._retry_at = time.monotonic() + _BACKOFF[min(self._fails, len(_BACKOFF) - 1)]
        self._fails += 1

    def _reader(self, proc: subprocess.Popen, hello_ev: threading.Event) -> None:
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "fatal":     # e.g. --max-mem-mb exceeded; serve exits 3 -> EOF handling restarts
                    logger.warning("[tilecore_client] serve fatal: %s", msg.get("error"))
                    continue
                if msg.get("type") == "hello":
                    self._hello = msg
                    hello_ev.set()
                    continue
                with self._plock:
                    f = self._pending.pop(str(msg.get("id")), None)
                if f is not None and not f.done():
                    f.set_result(msg)
        except Exception:
            pass
        finally:
            # stdout ended (crash/EOF/reader error): the process may still be alive (stdout closed only) -> reap it
            try:
                proc.kill()                # outside _lock: releases a writer blocked on a full pipe
            except OSError:
                pass
            if self._lock.acquire(timeout=5):
                try:
                    if self._proc is proc:     # schedule restart, fail waiters
                        self._proc = None
                        self._hello = None
                        self._note_failure_locked()
                        self._fail_all(ServeUnavailable("serve process ended"))
                finally:
                    self._lock.release()
            self._reap(proc)
            hello_ev.set()

    def _start_locked(self) -> None:
        if self._disabled:
            raise ServeUnavailable(self._disabled)
        if time.monotonic() < self._retry_at:
            raise ServeUnavailable("restart backoff")
        ev = threading.Event()
        self._hello = None
        try:
            proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        except OSError as exc:
            self._disabled = f"spawn failed: {exc}"
            logger.warning("[tilecore_client] %s", self._disabled)
            raise ServeUnavailable(self._disabled)
        self._proc = proc
        self.starts += 1
        threading.Thread(target=self._reader, args=(proc, ev), daemon=True, name="tilecore-serve-reader").start()
        ev.wait(self.start_timeout_s)
        h = self._hello
        if h is None or self._proc is not proc:
            if self._proc is proc:
                self._kill_locked("hello timeout")
                self._note_failure_locked()
            raise ServeUnavailable("hello not received")
        bad = None
        if h.get("proto") != PROTO:
            bad = f"proto {h.get('proto')} != {PROTO}"
        elif h.get("rules") != "bs":
            bad = f"rules {h.get('rules')!r} != 'bs'"
        elif self.expect_engine and not str(h.get("engine", "")).startswith(self.expect_engine):
            bad = f"engine {h.get('engine')!r} !~ {self.expect_engine!r}"
        elif self.expect_sha and h.get("dll_sha256") != self.expect_sha:
            bad = "dll_sha256 mismatch"
        if bad:
            self._disabled = f"version mismatch: {bad}"
            logger.warning("[tilecore_client] C# disabled, using Python: %s", self._disabled)
            self._kill_locked(self._disabled)
            raise ServeUnavailable(self._disabled)
        self._fails = 0

    def request(self, msg: dict, timeout_s: float) -> dict:
        """Send msg (id assigned here) and wait. ONE deadline covers lock wait, process start, write and reply.
        Raises ServeUnavailable / ServeUnsupported / ServeError / TimeoutError. A timeout kills the process (other
        in-flight requests fail too -> callers fall back). The pipe write happens outside ``_lock`` and a watchdog
        timer kills the process at the deadline, so a full pipe (peer not reading) cannot block anything else."""
        t_end = time.monotonic() + timeout_s
        rid = f"r{next(self._ids)}"
        fut: cf.Future = cf.Future()
        body = dict(msg, id=rid)
        body.setdefault("deadline_ms", int(timeout_s * 1000))
        try:    # before touching the process/pending table: a bad payload leaves no state behind
            line = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=_json_default) + "\n"
        except (TypeError, ValueError) as exc:
            raise ServeSerializeError(f"{type(exc).__name__}: {exc}"[:200])

        def remaining() -> float:
            return max(0.0, t_end - time.monotonic())

        if not self._lock.acquire(timeout=remaining()):
            raise TimeoutError("serve lock wait timeout")
        try:
            if self._proc is not None and self._proc.poll() is not None:
                self._kill_locked("process died")
                self._note_failure_locked()
            if self._proc is None:
                self._start_locked()
            proc = self._proc
            with self._plock:
                self._pending[rid] = fut
        finally:
            self._lock.release()

        watchdog = threading.Timer(remaining(), self._expire, args=(proc,))
        watchdog.daemon = True
        watchdog.start()
        try:
            try:
                if not self._wlock.acquire(timeout=remaining()):
                    raise TimeoutError("serve write lock wait timeout")
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                finally:
                    self._wlock.release()
            except TimeoutError:
                self._expire(proc)
                with self._plock:
                    self._pending.pop(rid, None)
                raise
            except (OSError, ValueError):
                with self._plock:
                    self._pending.pop(rid, None)
                timed_out = time.monotonic() >= t_end          # watchdog killed us mid-write
                self._expire(proc)
                if timed_out:
                    raise TimeoutError("serve write timeout")
                raise ServeUnavailable("write failed")
            try:
                resp = fut.result(timeout=remaining())
            except cf.TimeoutError:
                self._expire(proc)
                with self._plock:
                    self._pending.pop(rid, None)
                raise TimeoutError(f"serve request timeout {timeout_s}s")
        finally:
            watchdog.cancel()
        if not resp.get("ok"):
            if resp.get("unsupported"):
                raise ServeUnsupported(str(resp.get("error", "")))
            if resp.get("kind") == "deadline":
                raise ServeDeadline(str(resp.get("error", "")))
            raise ServeError(f"{resp.get('kind', 'error')}: {resp.get('error', '')}")
        return resp

    def _expire(self, proc: subprocess.Popen) -> None:
        """Deadline hit or write failed: kill ``proc`` right away (no lock -> frees a blocked write), then clean the
        shared state if it is still the current process."""
        try:
            proc.kill()
        except OSError:
            pass
        if self._lock.acquire(timeout=5):
            try:
                if self._proc is proc:
                    self._kill_locked("expired")
                    self._note_failure_locked()
            finally:
                self._lock.release()

    def close(self) -> None:
        with self._lock:
            p = self._proc
            if p is None:
                return
            try:
                p.stdin.close()      # EOF = graceful stop
                p.wait(timeout=2)
            except Exception:
                pass
            self._kill_locked("closed")


_workers: Dict[str, ServeWorker] = {}
_wlock = threading.Lock()


def _make_argv(path: str) -> List[str]:
    cmd = os.environ.get("TILECORE_SERVE_CMD")
    if cmd:
        return shlex.split(cmd)
    threads = int(_env_float(f"TILECORE_SERVE_THREADS_{path.upper()}", _DEFAULT_THREADS.get(path, 1)))
    dll = os.path.expanduser(os.environ.get("TILECORE_SERVE_DLL") or _DEFAULT_DLL)
    return [os.environ.get("TILECORE_DOTNET") or "dotnet", dll, "serve", "--threads", str(max(1, threads))]


def get_worker(path: str) -> ServeWorker:
    with _wlock:
        w = _workers.get(path)
        if w is None or w.pid_owner != os.getpid():
            w = ServeWorker(_make_argv(path),
                            expect_engine=os.environ.get("TILECORE_SERVE_ENGINE", "tilecore/7."),
                            expect_sha=os.environ.get("TILECORE_SERVE_SHA") or None,
                            start_timeout_s=_env_float("TILECORE_START_TIMEOUT_S", 15.0))
            _workers[path] = w
        return w


def shutdown_all() -> None:
    with _wlock:
        ws = list(_workers.values())
        _workers.clear()
    for w in ws:
        if w.pid_owner == os.getpid():
            w.close()


def _after_fork_child() -> None:   # a forked child must never touch the parent's pipes
    global _wlock, _clock, _SLOCK
    _wlock = threading.Lock()
    _clock = threading.Lock()
    _SLOCK = threading.Lock()
    _workers.clear()


atexit.register(shutdown_all)
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


# ───────────────────────── RNG state helpers ─────────────────────────
def rng_state_to_json(rng: random.Random) -> Optional[dict]:
    """CPython getstate() = (3, (mt0..mt623, index), gauss_next). None if not representable."""
    ver, internal, gauss = rng.getstate()
    if ver != 3 or gauss is not None or len(internal) != 625:
        return None
    return {"mt": list(internal[:624]), "index": internal[624]}


def rng_state_from_json(rng: random.Random, st: dict) -> None:
    mt, idx = st["mt"], int(st["index"])
    if len(mt) != 624 or not (0 <= idx <= 624):
        raise ValueError("bad rng_state")
    rng.setstate((3, tuple(int(x) for x in mt) + (idx,), None))


# ───────────────────────── max_moves / support ─────────────────────────
def resolve_max_moves(level_json: dict, max_moves: Optional[int]) -> int:
    """Same as BotSimulator.simulate_with_profile (bot_simulator.py:914-922)."""
    if max_moves is None:
        max_moves = level_json.get("max_moves")
        if not max_moves:
            total = sum(len(level_json.get(f"layer_{i}", {}).get("tiles", {}))
                        for i in range(int(level_json.get("layer", 0) or 0)))
            max_moves = total + 50
    return max_moves


def _profile_json(profile) -> dict:
    d = dataclasses.asdict(profile)
    bt = getattr(profile, "bot_type", None)
    d["bot_type"] = getattr(bt, "value", bt)
    return d


def _pre_reject(simulator, level_json, seed, honor_zero_seed) -> Optional[str]:
    if honor_zero_seed and level_json.get("randSeed", 0) == 0:
        return "honor_zero_seed"
    if seed is None and rng_state_to_json(simulator._rng) is None:
        return "rng_state_unrepresentable"
    return None


# ───────────────────────── C# call + result build ─────────────────────────
def _build_result(profile, games: List[dict], max_moves: int) -> BotSimulationResult:
    n = len(games)
    moves = [int(g["moves"]) for g in games]
    combo = [int(g["combo"]) for g in games]
    tiles = [int(g["tiles_cleared"]) for g in games]
    cleared = sum(1 for g in games if g["cleared"])
    return BotSimulationResult(
        bot_type=profile.bot_type, bot_name=profile.name, iterations=n,
        clear_rate=cleared / n if n > 0 else 0,
        avg_moves=statistics.mean(moves) if moves else 0,
        min_moves=min(moves) if moves else 0,
        max_moves=max(moves) if moves else max_moves,
        std_moves=statistics.stdev(moves) if len(moves) > 1 else 0,
        avg_combo=statistics.mean(combo) if combo else 0,
        avg_tiles_cleared=statistics.mean(tiles) if tiles else 0,
    )


def _cs_call(path, level_json, profile, iterations, mm, seed, early_termination, pre_state):
    """Returns (games, rng_state_out|None). Raises Serve*/TimeoutError. Never touches simulator._rng."""
    msg = {"op": "sim", "mode": "gen" if seed is not None else "gen_state",
           "profile": _profile_json(profile), "level": level_json, "iterations": int(iterations),
           "seed": seed, "rng_state": None if seed is not None else pre_state,
           "max_moves": int(mm), "early_termination": bool(early_termination), "want_state_out": True}
    resp = get_worker(path).request(msg, _env_float("TILECORE_TIMEOUT_S", 10.0))
    games = resp.get("games")
    if not isinstance(games, list) or int(resp.get("n", -1)) != len(games):
        raise ServeError("malformed games")
    try:
        for g in games:
            g["cleared"], g["moves"], g["combo"], g["tiles_cleared"]
    except (KeyError, TypeError):
        raise ServeError("malformed game row")
    return games, resp.get("rng_state_out")


def _classify(path: str, exc: Exception) -> str:
    key = ("unsupported" if isinstance(exc, ServeUnsupported) else
           "serialize_error" if isinstance(exc, ServeSerializeError) else
           "timeout" if isinstance(exc, (TimeoutError, ServeDeadline)) else "error")
    _count(path, key)
    return key


# ───────────────────────── shadow log ─────────────────────────
_SLOCK = threading.Lock()


def _shadow_log(path: str, rec: dict) -> None:
    try:
        d = os.path.expanduser(os.environ.get("TILECORE_SHADOW_DIR") or _DEFAULT_SHADOW_DIR)
        os.makedirs(d, exist_ok=True)
        with _SLOCK, open(os.path.join(d, f"{path}_shadow_diff.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _res_key(r: BotSimulationResult) -> tuple:
    return (r.iterations, r.clear_rate, r.avg_moves, r.min_moves, r.max_moves, r.std_moves, r.avg_combo,
            r.avg_tiles_cleared)


def _state_hash(rng: random.Random) -> str:
    return hashlib.sha256(repr(rng.getstate()).encode()).hexdigest()[:16]


def _lvl_hash(level_json) -> str:
    return hashlib.sha256(json.dumps(level_json, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ───────────────────────── public adapter ─────────────────────────
def simulate(simulator: BotSimulator, level_json: dict, profile, *, iterations: int,
             max_moves: Optional[int] = None, seed: Optional[int] = None, honor_zero_seed: bool = False,
             early_termination: bool = False, path: str = "gen") -> BotSimulationResult:
    """Drop-in for ``simulator.simulate_with_profile`` (same arguments, + path). See module doc."""
    def py():
        return simulator.simulate_with_profile(level_json, profile, iterations=iterations, max_moves=max_moves,
                                               seed=seed, honor_zero_seed=honor_zero_seed,
                                               early_termination=early_termination)

    mode = path_mode(path)
    if mode == "off":
        return py()

    reject = _pre_reject(simulator, level_json, seed, honor_zero_seed)
    if reject:
        _count(path, "unsupported")
        _count(path, "fallback")
        return py()

    mm = resolve_max_moves(level_json, max_moves)
    pre_state = rng_state_to_json(simulator._rng) if seed is None else None
    pre_rng_state = simulator._rng.getstate()

    if mode == "shadow":
        t0 = time.perf_counter()
        res = py()
        py_s = time.perf_counter() - t0
        end_hash = _state_hash(simulator._rng)
        rec = {"ts": time.time(), "path": path, "lvl": _lvl_hash(level_json), "seed": seed, "n_req": iterations,
               "profile": getattr(profile, "name", None), "py_s": round(py_s, 4)}
        try:
            t1 = time.perf_counter()
            games, st_out = _cs_call(path, level_json, profile, iterations, mm, seed, early_termination, pre_state)
            rec["cs_s"] = round(time.perf_counter() - t1, 4)
            cs_res = _build_result(profile, games, mm)
            same_res = _res_key(cs_res) == _res_key(res)
            same_state = False
            if st_out is not None:
                chk = random.Random()
                rng_state_from_json(chk, st_out)
                same_state = _state_hash(chk) == end_hash
            # seed given: python reseeds per game, C# end state is informational only
            ok = same_res and (same_state or seed is not None)
            rec.update(category="same" if ok else "mismatch", same_result=same_res, same_state=same_state)
            _count(path, "cs_ok")
            _count(path, "shadow_same" if ok else "shadow_mismatch")
        except Exception as exc:
            rec["category"] = {"unsupported": "cs_unsupported", "timeout": "timeout",
                                                                      "serialize_error": "serialize_error"}.get(_classify(path, exc),
                                                                                           "cs_error")
            rec["error"] = str(exc)[:200]
        _shadow_log(path, rec)
        return res

    # mode == "on"
    try:
        games, st_out = _cs_call(path, level_json, profile, iterations, mm, seed, early_termination, pre_state)
        res = _build_result(profile, games, mm)
        if seed is None and st_out is None:
            raise ServeError("rng_state_out missing")
        if st_out is not None:
            rng_state_from_json(simulator._rng, st_out)
    except Exception as exc:
        _classify(path, exc)
        _count(path, "fallback")
        simulator._rng.setstate(pre_rng_state)      # python re-run sees the RNG state from before the call
        return py()
    _count(path, "cs_ok")
    sample = _env_float("TILECORE_SHADOW_SAMPLE", 0.0)
    if sample > 0 and random.random() < sample:
        _sample_compare(path, level_json, profile, iterations, max_moves, seed, honor_zero_seed, early_termination,
                        pre_rng_state, res, simulator._rng)
    return res


def _sample_compare(path, level_json, profile, iterations, max_moves, seed, honor_zero_seed, early_termination,
                    pre_rng_state, cs_res, cs_end_rng) -> None:
    try:
        chk = BotSimulator()
        chk._rng.setstate(pre_rng_state)
        py_res = chk.simulate_with_profile(level_json, profile, iterations=iterations, max_moves=max_moves,
                                           seed=seed, honor_zero_seed=honor_zero_seed,
                                           early_termination=early_termination)
        same = _res_key(py_res) == _res_key(cs_res) and (seed is not None or
                                                         _state_hash(chk._rng) == _state_hash(cs_end_rng))
        _count(path, "shadow_same" if same else "shadow_mismatch")
        _shadow_log(path, {"ts": time.time(), "path": path, "lvl": _lvl_hash(level_json), "seed": seed,
                           "category": "same" if same else "mismatch", "sampled_on": True})
    except Exception as exc:     # never break the service
        logger.warning("[tilecore_client] sample compare failed: %s", exc)


# ───────────────────────── sweep (rl_sim._parallel_point_sweep) ─────────────────────────
class _RecordingSim(BotSimulator):
    """BotSimulator that also records [cleared, moves, combo, tiles_cleared] of every game (picklable, top level)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rec_games: List[list] = []

    def _play_game(self, state, profile):
        f = super()._play_game(state, profile)
        self.rec_games.append([bool(f.cleared), int(f.moves_used), int(f.combo_count), int(f.total_tiles_cleared)])
        return f


def _sweep_params(args: dict):
    from . import mc_difficulty as mc
    theta = float(args["theta"])
    return (theta, mc.make_skill_profile(theta, args.get("bot_version", "v1")),
            max(4, min(500, int(args.get("rollouts", mc.DEFAULT_ROLLOUTS_PER_POINT)))),
            args.get("seed", mc.DEFAULT_BASE_SEED))


def _point_dict(args: dict, theta: float, res) -> dict:
    """Same dict/rounding as mc_difficulty.sweep_point_task (res: BotSimulationResult)."""
    from . import mc_difficulty as mc
    return {"key": args.get("key"), "error": None, "theta": round(theta, 4),
            "clear_rate": round(res.clear_rate, 4), "iterations": res.iterations,
            "ci_half_width": round(mc._wilson_half_width(res.clear_rate, res.iterations), 4),
            "avg_moves": round(res.avg_moves, 2), "avg_tiles_cleared": round(res.avg_tiles_cleared, 2)}


def sweep_point_task_recorded(args: dict) -> dict:
    """Pool task for shadow: python result exactly like ``sweep_point_task`` + per-game records.
    Returns {"point": <sweep_point_task dict>, "games": [[cleared,moves,combo,tiles],...], "py_s": float}."""
    from . import mc_difficulty as mc
    t0 = time.perf_counter()
    try:
        theta, profile, iters, seed = _sweep_params(args)
        sim = _RecordingSim()
        res = sim.simulate_with_profile(args["level_json"], profile, iterations=iters, max_moves=args.get("max_moves"),
                                        seed=seed, honor_zero_seed=False, early_termination=True)
        return {"point": _point_dict(args, theta, res), "games": sim.rec_games, "py_s": time.perf_counter() - t0}
    except Exception:
        return {"point": mc.sweep_point_task(args), "games": None, "py_s": time.perf_counter() - t0}


def _cs_point(args: dict, path: str = "sweep"):
    """One sweep point on C# (gen mode, seed given). Returns (point_dict, games) or raises Serve*/TimeoutError.
    Pre-rejects (ServeUnsupported): bot_version != v1."""
    if args.get("bot_version", "v1") != "v1":
        raise ServeUnsupported("bot_version != v1")
    theta, profile, iters, seed = _sweep_params(args)
    lj = args["level_json"]
    mm = resolve_max_moves(lj, args.get("max_moves"))
    games, _ = _cs_call(path, lj, profile, iters, mm, int(seed), True, None)
    return _point_dict(args, theta, _build_result(profile, games, mm)), games


def _cs_many(tasks: List[dict], path: str):
    """Pipeline tasks to the resident worker. Returns list aligned with tasks: (point, games) | Exception."""
    n = max(1, int(_env_float("TILECORE_SERVE_THREADS_SWEEP", _DEFAULT_THREADS["sweep"])))

    def one(a):
        try:
            return _cs_point(a, path)
        except Exception as exc:
            return exc
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(one, tasks))


def sweep_points(tasks: List[dict], path: str = "sweep", fallback_map=None) -> List[dict]:
    """Same dicts, same order as ``mc_difficulty.sweep_point_task`` over ``tasks``. Points go to C# concurrently; any
    point C# cannot do (unsupported/error/timeout/bot_version != v1) goes to ``fallback_map(list_of_tasks)`` (default:
    sequential in-process ``sweep_point_task``)."""
    from . import mc_difficulty as mc
    if fallback_map is None:
        fallback_map = lambda ts: [mc.sweep_point_task(t) for t in ts]    # noqa: E731
    if not tasks:
        return []
    if path_mode(path) == "off":                  # switch off: C# never touched
        return fallback_map(list(tasks))
    out: List[Optional[dict]] = [None] * len(tasks)
    redo = []
    for i, r in enumerate(_cs_many(tasks, path)):
        if isinstance(r, Exception):
            _classify(path, r)
            _count(path, "fallback")
            redo.append(i)
        else:
            _count(path, "cs_ok")
            out[i] = r[0]
    if redo:
        for i, p in zip(redo, fallback_map([tasks[i] for i in redo])):
            out[i] = p
    return out   # type: ignore[return-value]


def _shadow_sweep(pool, tasks: List[dict], path: str) -> List[dict]:
    recs = list(pool.map(sweep_point_task_recorded, tasks, chunksize=1))
    points = [r["point"] for r in recs]
    try:
        cs = _cs_many(tasks, path)
        for a, rec, r in zip(tasks, recs, cs):
            row = {"ts": time.time(), "path": path, "lvl": _lvl_hash(a["level_json"]), "theta": a.get("theta"),
                   "seed": a.get("seed"), "py_s": round(rec["py_s"], 4)}
            if isinstance(r, Exception):
                row["category"] = {"unsupported": "cs_unsupported", "timeout": "timeout",
                                                                      "serialize_error": "serialize_error"}.get(_classify(path, r),
                                                                                              "cs_error")
                row["error"] = str(r)[:200]
            else:
                _count(path, "cs_ok")
                same = rec["games"] is not None and [[g["cleared"], g["moves"], g["combo"], g["tiles_cleared"]]
                                                     for g in r[1]] == rec["games"] and r[0] == rec["point"]
                row["category"] = "same" if same else "mismatch"
                _count(path, "shadow_same" if same else "shadow_mismatch")
            _shadow_log(path, row)
    except Exception as exc:      # shadow must never break the service
        logger.warning("[tilecore_client] sweep shadow failed: %s", exc)
    return points


def run_sweep(pool, tasks: List[dict], path: str = "sweep") -> List[dict]:
    """Single call site in rl_sim._parallel_point_sweep: replaces
    ``list(pool.map(sweep_point_task, tasks, chunksize=1))``.
      off    -> exactly that expression (C# never touched)
      on     -> C# first; unsupported/failed points go through ``pool`` (python)
      shadow -> python via pool (records games) is the result; C# replay compared & logged"""
    from . import mc_difficulty as mc
    mode = path_mode(path)
    if mode == "off":
        return list(pool.map(mc.sweep_point_task, tasks, chunksize=1))
    if mode == "shadow":
        return _shadow_sweep(pool, tasks, path)
    return sweep_points(tasks, path, fallback_map=lambda ts: list(pool.map(mc.sweep_point_task, ts, chunksize=1)))
