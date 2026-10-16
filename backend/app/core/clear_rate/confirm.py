"""Validation-tab C confirmation measurement (doc 38 §10) — async jobs on the shared measure / store / verdict path.

    plan_item(model, level_json, placement_level, upload_opts)   fix map + final conditions (cond_hash) before C
    ConfirmJobManager(root)                                       submit / get / cancel / evaluate, persisted to disk
    measurement_kind(seed_band)                                   "confirm" only for the validation-tab band CV

Rules (doc 38 §10, user instructions 2026-10-16):
- Exploration and C are separate kinds. Only measurements this manager wrote on band CV are C; the model's training
  cache (seed11M), pilot bands (S*/C/C2/C3/P2) and request-supplied rows are exploration here, never C.
- The caller fixes the map first: submit() needs the cond_hash returned by plan_item(); a different map / condition /
  placement at submit time is refused (no silent re-plan).
- Mode A only: bot version / protocol / θ grid / games per θ must equal the active model manifest, else refused.
  There is no B confirmation here and A never falls back to B.
- One job per key (cond_hash | protocol | CV | bot-config hash). A queued/running job with that key is returned
  instead of a new one (duplicate click); a finished C for that key is reused, never re-measured. Failures are not
  retried and no other map is picked. At most MAX_CONCURRENT jobs run; the rest wait (queued).
- Cancelled / failed / interrupted (server restart) jobs keep their partial game count for display only: nothing is
  written to the measurement store, and evaluate() refuses them.
- A C measurement only re-checks bot-measurement stability on a separate seed band; it is not an independent
  validation of the real-user clear rate.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import experiment as X
from . import guard
from . import measure as M
from .conditions import cond_hash, finalize_game_conditions
from .features import THETAS
from .predict import BotMeasurement
from .select import PROPOSED

CONFIRM_BAND = "CV"
CONFIRM_BANDS = (CONFIRM_BAND,)
KIND_EXPLORATION, KIND_CONFIRM = "exploration", "confirm"
MAX_CONCURRENT = 2
JOB_SCHEMA = 1

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
ACTIVE = (QUEUED, RUNNING)

# What each registered band is for. The validation tab treats every band except CONFIRM_BAND as exploration.
BAND_PURPOSE = {
    "seed11M": "bot v2.4 training rows / model bot_cache (exploration)",
    "S": "pilot 1 search", "C": "pilot 1 confirmation",
    "S2": "pilot 2 search", "P2": "pilot 2 screening", "S2B": "pilot 2 B search", "C2": "pilot 2 confirmation",
    "S3": "A90 search 3", "C3": "A90 search 3 confirmation",
    "CV": "validation tab C confirmation (doc 38 §10)",
}
# Seed bases used outside this registry (pv pilots 1–9.1M, bot_v24 natural experiments 13M / 23M).
EXTERNAL_BANDS = (1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000, 6_000_000, 7_000_000, 8_000_000,
                  9_100_000, 13_000_000, 23_000_000)
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "data" / "clear_rate_verify"


class ConfirmRejected(ValueError):
    """Request refused before any bot run (status 409 / 422 at the route)."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def measurement_kind(seed_band: Optional[str]) -> str:
    return KIND_CONFIRM if seed_band in CONFIRM_BANDS else KIND_EXPLORATION


def band_span() -> int:
    return (M.LAYOUTS - 1) * 1000 + max(g for _, g in M.PROTOCOLS.values())


def band_registry_problems() -> List[str]:
    """Seed-band collision check (registry + external bands). Empty list = no collision."""
    out, span = [], band_span()
    bases = sorted(M.SEED_BANDS.items(), key=lambda kv: kv[1])
    for (a, x), (b, y) in zip(bases, bases[1:]):
        if y - x <= span:
            out.append(f"band {a}({x}) and {b}({y}) overlap (span {span})")
    for name, base in M.SEED_BANDS.items():
        if name != "seed11M" and any(abs(base - e) <= span for e in EXTERNAL_BANDS):
            out.append(f"band {name}({base}) overlaps an external band")
        if name not in BAND_PURPOSE:
            out.append(f"band {name} has no registered purpose")
    if CONFIRM_BAND not in M.SEED_BANDS:
        out.append(f"confirm band {CONFIRM_BAND} not registered")
    return out


def judge_version() -> str:
    """Verdict criteria id: changes whenever a threshold or the accepted confirm band changes → stored evaluations
    with another id are shown as stale."""
    crit = {k: (list(v) if isinstance(v, tuple) else v) for k, v in PROPOSED.items() if k != "confirm_bands"}
    crit["confirm_bands"] = list(CONFIRM_BANDS)
    return "judge-" + hashlib.sha256(json.dumps(crit, sort_keys=True).encode()).hexdigest()[:10]


def protocol_problems(model: Any) -> List[str]:
    """Mode A C measurement must use exactly what the model was trained on."""
    man, out = model.manifest, []
    if man.get("bot_version") != M.BOT_VERSION:
        out.append(f"bot {M.BOT_VERSION} ≠ model {man.get('bot_version')}")
    proto = man.get("bot_protocol")
    if proto not in M.PROTOCOLS:
        out.append(f"model protocol {proto} unknown to measure.PROTOCOLS")
    else:
        thetas, games = M.PROTOCOLS[proto]
        if tuple(round(t, 2) for t in thetas) != tuple(round(t, 2) for t in THETAS):
            out.append(f"protocol θ {thetas} ≠ model θ {THETAS}")
        if games != int(man.get("bot_games_per_theta", -1)):
            out.append(f"protocol games {games} ≠ model {man.get('bot_games_per_theta')}")
    return out


def plan_item(model: Any, level_json: Dict[str, Any], placement_level: int,
              upload_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Final game conditions + store key + planned games for one map. No bot run."""
    from .service import random_layout
    game_map, cond = finalize_game_conditions(level_json, placement_level, upload_opts)
    expo = M.bot_exposure(model.model["position"], placement_level)
    cfg = M.bot_config(expo, cond)
    h, ch = cond_hash(game_map, cond), M.config_hash(cfg)
    proto = model.manifest["bot_protocol"]
    thetas, games = M.PROTOCOLS.get(proto, ((), 0))
    screen = X.structural_screen(model, game_map, cond, placement_level, random_layout=random_layout(game_map))
    hard = [c for c in screen["blocking"] if c in guard.SUPPRESS]
    return {"cond_hash": h, "bot_config_hash": ch, "protocol": proto, "seed_band": CONFIRM_BAND,
            "bot_version": M.BOT_VERSION, "games_planned": len(thetas) * games,
            "job_key": M.store_key(h, proto, CONFIRM_BAND, ch), "blocking": hard,
            "warnings": [c for c in screen["blocking"] if c not in hard],
            "_game_map": game_map, "_cond": cond, "_exposure": expo}


def public_plan(p: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class JobStore:
    """jobs.json — every job ever submitted (never deleted). On load, queued/running jobs of a previous server
    process become failed ("interrupted"): their partial games are not a completed C."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.jobs: Dict[str, Dict[str, Any]] = raw.get("jobs", {}) if isinstance(raw, dict) else {}
        changed = False
        for j in self.jobs.values():
            if j.get("status") in ACTIVE:
                j.update(status=FAILED, error="서버 재시작으로 중단됨 — 부분 결과는 완료 C 아님", interrupted=True,
                         finished_at=_now())
                changed = True
        if changed:
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": JOB_SCHEMA, "jobs": self.jobs}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def put(self, job: Dict[str, Any]) -> None:
        with self.lock:
            self.jobs[job["job_id"]] = job
            self._write()

    def update(self, job_id: str, **kw: Any) -> Dict[str, Any]:
        with self.lock:
            self.jobs[job_id].update(kw)
            self._write()
            return dict(self.jobs[job_id])

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            j = self.jobs.get(job_id)
            return dict(j) if j else None

    def by_key(self, key: str) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(j) for j in self.jobs.values() if j.get("job_key") == key]


class ConfirmJobManager:
    """runner: measure.measure by default (injectable for tests). start_threads=False → jobs stay queued until
    run_pending() (tests)."""

    def __init__(self, root: Path = DEFAULT_ROOT, *, model_loader: Optional[Callable[[], Any]] = None,
                 runner: Optional[Callable[..., Any]] = None, start_threads: bool = True):
        from .model import load_model
        self.root = Path(root)
        self.jobs = JobStore(self.root / "jobs.json")
        self.store = M.MeasurementStore(self.root / "measurements.json")
        self.store_lock = threading.Lock()
        self.model_loader = model_loader or load_model
        self.runner = runner or M.measure
        self.start_threads = start_threads
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self.submit_lock = threading.Lock()
        self.cancel_flags: Dict[str, threading.Event] = {}
        self.pending: Dict[str, Dict[str, Any]] = {}   # job_id → in-memory inputs (map / cond / exposure)

    # ── plan / submit ─────────────────────────────────────────────────────────────────────────────────────────
    def plan(self, level_json: Dict[str, Any], placement_level: int,
             upload_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        model = self.model_loader()
        p = public_plan(plan_item(model, level_json, placement_level, upload_opts))
        p["protocol_problems"] = protocol_problems(model)
        p["model_version"] = model.version
        p["existing"] = self._existing(p["job_key"])
        return p

    def _existing(self, key: str) -> Optional[Dict[str, Any]]:
        js = self.jobs.by_key(key)
        active = [j for j in js if j["status"] in ACTIVE]
        done = [j for j in js if j["status"] == DONE]
        pick = active or done or sorted(js, key=lambda j: j.get("created_at", ""))[-1:]
        return pick[0] if pick else None

    def submit(self, *, level_json: Dict[str, Any], placement_level: int, expected_cond_hash: str,
               map_id: str = "", batch_id: str = "", upload_opts: Optional[Dict[str, Any]] = None
               ) -> Dict[str, Any]:
        """Returns {"job": job, "created": bool, "reused": None | "active" | "done"}."""
        model = self.model_loader()
        probs = protocol_problems(model) + band_registry_problems()
        if probs:
            raise ConfirmRejected("PROTOCOL_MISMATCH", "; ".join(probs))
        p = plan_item(model, level_json, placement_level, upload_opts)
        if not expected_cond_hash or p["cond_hash"] != expected_cond_hash:
            raise ConfirmRejected("CONDITION_CHANGED",
                                  f"확정한 조건 {expected_cond_hash or '—'} ≠ 현재 {p['cond_hash']} — 다시 확인 후 요청")
        if p["blocking"]:
            raise ConfirmRejected("UNSUPPORTED_INPUT",
                                  "측정해도 판정할 수 없는 입력(학습 지원 밖): " + ", ".join(p["blocking"]))
        with self.submit_lock:
            for j in self.jobs.by_key(p["job_key"]):
                if j["status"] in ACTIVE:
                    return {"job": j, "created": False, "reused": "active"}
            for j in self.jobs.by_key(p["job_key"]):
                if j["status"] == DONE and self._load_record(j) is not None:
                    return {"job": j, "created": False, "reused": "done"}
            job = {"schema": JOB_SCHEMA, "job_id": uuid.uuid4().hex[:16], "job_key": p["job_key"],
                   "measurement_kind": KIND_CONFIRM, "target_mode": X.USER_EXPECTED, "status": QUEUED,
                   "map_id": map_id, "batch_id": batch_id, "placement_level": int(placement_level),
                   "cond_hash": p["cond_hash"], "bot_config_hash": p["bot_config_hash"], "protocol": p["protocol"],
                   "seed_band": CONFIRM_BAND, "seed_base": M.SEED_BANDS[CONFIRM_BAND],
                   "bot_version": M.BOT_VERSION, "model_version_at_submit": model.version,
                   "games_planned": p["games_planned"], "games_done": 0, "cancel_requested": False,
                   "created_at": _now(), "started_at": None, "finished_at": None, "error": None,
                   "measurement_ref": None}
            self.jobs.put(job)
            self.cancel_flags[job["job_id"]] = threading.Event()
            self.pending[job["job_id"]] = {"map": p["_game_map"], "cond": p["_cond"], "exposure": p["_exposure"]}
        if self.start_threads:
            threading.Thread(target=self._run, args=(job["job_id"],), daemon=True,
                             name=f"cr-confirm-{job['job_id']}").start()
        return {"job": job, "created": True, "reused": None}

    # ── run / cancel ──────────────────────────────────────────────────────────────────────────────────────────
    def run_pending(self) -> None:
        """Synchronous run of queued jobs (tests only)."""
        for jid in list(self.pending):
            self._run(jid)

    def _run(self, job_id: str) -> None:
        stop = self.cancel_flags.get(job_id) or threading.Event()
        inp = self.pending.get(job_id)
        with self.slots:
            with self.submit_lock:   # queued → running vs cancel() race
                cur = self.jobs.get(job_id) or {}
                if cur.get("status") != QUEUED or stop.is_set():
                    if cur.get("status") in ACTIVE:
                        self.jobs.update(job_id, status=CANCELLED, finished_at=_now())
                    self.pending.pop(job_id, None)
                    return
                if inp is None:
                    self.jobs.update(job_id, status=FAILED, error="입력 없음(서버 재시작?)", finished_at=_now())
                    return
                job = self.jobs.update(job_id, status=RUNNING, started_at=_now())
            try:
                m, meta = self.runner(inp["map"], inp["cond"], exposure=inp["exposure"], protocol=job["protocol"],
                                      seed_band=CONFIRM_BAND, should_stop=stop.is_set,
                                      on_row=lambda n: self.jobs.update(job_id, games_done=int(n)))
                problems = self._check_result(job, m, meta)
                if problems:
                    raise RuntimeError("측정 결과가 요청과 다름: " + "; ".join(problems))
                if stop.is_set():   # cancel arrived during the last row — the user asked to stop, keep nothing
                    raise M.MeasurementCancelled("cancel requested before store")
                meta = {**meta, "measurement_kind": KIND_CONFIRM, "job_id": job_id, "purpose": BAND_PURPOSE["CV"],
                        "measured_at": _now()}
                with self.store_lock:
                    self.store.put(m, meta)
                self.jobs.update(job_id, status=DONE, games_done=int(meta["games"]), finished_at=_now(),
                                 measurement_ref=M.store_key(m.cond_hash, m.protocol, m.seed_band,
                                                             meta["bot_config_hash"]))
            except M.MeasurementCancelled:
                self.jobs.update(job_id, status=CANCELLED, finished_at=_now())
            except Exception as e:  # noqa: BLE001 — recorded on the job; never retried
                self.jobs.update(job_id, status=FAILED, error=f"{type(e).__name__}: {e}", finished_at=_now())
            finally:
                self.pending.pop(job_id, None)

    @staticmethod
    def _check_result(job: Dict[str, Any], m: BotMeasurement, meta: Dict[str, Any]) -> List[str]:
        out = []
        if m.cond_hash != job["cond_hash"]:
            out.append("cond_hash")
        if meta.get("bot_config_hash") != job["bot_config_hash"]:
            out.append("bot_config_hash")
        if m.seed_band != CONFIRM_BAND or m.protocol != job["protocol"] or m.bot_version != job["bot_version"]:
            out.append("band/protocol/bot")
        if int(meta.get("games", 0)) != int(job["games_planned"]):
            out.append(f"games {meta.get('games')} ≠ {job['games_planned']}")
        return out

    def cancel(self, job_id: str) -> Dict[str, Any]:
        """Queued → cancelled now. Running → cancel_requested; the job stops before its next θ row (the current
        row finishes first) and ends as cancelled with nothing stored."""
        with self.submit_lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job["status"] not in ACTIVE:
                return job
            ev = self.cancel_flags.get(job_id)
            if ev is not None:
                ev.set()
            if job["status"] == QUEUED:
                self.pending.pop(job_id, None)
                return self.jobs.update(job_id, status=CANCELLED, cancel_requested=True, finished_at=_now())
            return self.jobs.update(job_id, cancel_requested=True)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.jobs.get(job_id)

    # ── evaluate ──────────────────────────────────────────────────────────────────────────────────────────────
    def _load_record(self, job: Dict[str, Any]):
        if not job.get("measurement_ref"):
            return None
        rec = self.store.data.get(job["measurement_ref"])
        if not rec or rec.get("meta", {}).get("measurement_kind") != KIND_CONFIRM:
            return None
        return rec

    def evaluate(self, *, job_id: str, level_json: Dict[str, Any], placement_level: int, target: float,
                 upload_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Mode A verdict on a completed validation-tab C measurement. Re-derives the final conditions from the
        current level and refuses when they no longer match the measured ones."""
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] != DONE:
            raise ConfirmRejected("JOB_NOT_DONE", f"작업 상태 {job['status']} — 완료된 C 측정만 판정에 사용")
        rec = self._load_record(job)
        if rec is None:
            raise ConfirmRejected("MEASUREMENT_MISSING", "저장된 C 측정 원자료가 없음")
        model = self.model_loader()
        p = plan_item(model, level_json, placement_level, upload_opts)
        if p["cond_hash"] != job["cond_hash"] or p["bot_config_hash"] != job["bot_config_hash"]:
            raise ConfirmRejected("MEASUREMENT_INVALIDATED",
                                  "맵·게임 조건·배치(봇 설정)가 측정 때와 다름 — 이 측정은 현재 결과로 사용 불가")
        m = BotMeasurement.from_dict(rec["measurement"], source="store")
        if measurement_kind(m.seed_band) != KIND_CONFIRM:
            raise ConfirmRejected("NOT_CONFIRM", f"시드 묶음 {m.seed_band} 은 C 아님")
        from .service import random_layout
        out = X.evaluate_user_expected(model, p["_game_map"], p["_cond"], placement_level, m, target,
                                       random_layout=random_layout(p["_game_map"]), confirm_bands=CONFIRM_BANDS)
        return {"user_expected": out, "provenance": {
            "measurement_kind": KIND_CONFIRM, "job_id": job_id, "measurement_ref": job["measurement_ref"],
            "seed_band": m.seed_band, "seed_base": M.SEED_BANDS[m.seed_band], "protocol": m.protocol,
            "bot_version": m.bot_version, "bot_config_hash": job["bot_config_hash"], "cond_hash": job["cond_hash"],
            "games_completed": int(rec["meta"].get("games", 0)), "measured_at": rec["meta"].get("measured_at"),
            "model_version": model.version, "judge_version": judge_version(), "evaluated_at": _now()}}


_MANAGER: Optional[ConfirmJobManager] = None
_MANAGER_LOCK = threading.Lock()


def manager() -> ConfirmJobManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ConfirmJobManager()
        return _MANAGER


__all__ = ["CONFIRM_BAND", "CONFIRM_BANDS", "KIND_CONFIRM", "KIND_EXPLORATION", "MAX_CONCURRENT", "BAND_PURPOSE",
           "ConfirmRejected", "ConfirmJobManager", "band_registry_problems", "judge_version", "manager",
           "measurement_kind", "plan_item", "protocol_problems"]
