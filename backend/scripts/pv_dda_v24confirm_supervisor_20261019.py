"""Self-supervisor for pv_dda_v24confirm_20261019.py (independent OS process; no remote session needed).

Single instance: exclusive flock on supervisor.lock (second start exits immediately).
Persistent state (sup_state.json, survives supervisor restarts): supervisor starts, runner starts, halt reason/time,
last worker change, throughput baseline, swap history, consecutive bad-tick counters.

Every TICK s: time, memory pressure level, swap free, disk free, RAM free %, runner liveness, progress -> sup.log (TSV).
Rules (2026-10-19 instruction + 19:45 coordinator):
  STOP (any worker count): pressure critical(4) | swap free < 500MB | disk < 10GiB
       -> safe stop: SIGTERM runner group (finished stages are checkpointed), 20 s grace, then SIGKILL; halt.
  DEGRADE (sustained = BAD_TICKS consecutive ticks, counted ONLY while the runner is alive, reset at runner start
       and at pool-size change): swap used +400MB within 5 min | RAM free < 15% | swap free < 600MB
       | live CPU share per worker of the CURRENT runner group < 0.5 over the last 5 min of the current segment
         (judged only after >= 3 min of observation in that segment; past progress records are not used —
          per-level games/s varies ~2.5x with map size, 03:05 false stop, doc 44 §5-0)
  NO PROGRESS: runner alive but no new stage checkpoint (scan/c1/c2/result) for 45 min -> safe stop, halt.
       -> workers > 1: workers - 1 (applies at next level).  workers == 1: safe stop (as STOP), halt.
  STEP UP (+1, max MAXW): >= 10 min since last change, >= 1 level done at current workers, swap free >= 700MB,
       pressure <= 2, swap rise < 200MB in 5 min, RAM free >= 20%, >= 30 min before 09:30.
  RESUME after halt: only after 15 min of continuous good conditions (swap free >= resume_free_mb file value,
       default 1000, floor 700; pressure < 4; RAM free >= 20%; swap rise < 200MB in 5 min), before 09:30, at most MAX_RUNNER_STARTS runner starts in total (persisted).
  SUPERVISOR RESTART LIMIT: supervisor starts after hardening are counted in sup_state.json; if more than
       MAX_SUP_RESTARTS restarts -> no new batches: safe-stop runner (if any), write STOP, exit.
  DEADLINE: 09:30 KST NO_NEW_AFTER (runner stops before next stage). 09:50 SIGTERM. 09:55 SIGKILL. 09:58 exit.
Only the runner process group started/adopted here is ever signalled. Never touches other processes.
Resume after any stop: remove STOP if present, then
  cd backend && nohup venv/bin/python scripts/pv_dda_v24confirm_supervisor_20261019.py >> <OUT>/supervisor.out 2>&1 &
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3", "dda_v24confirm_20261019")
RUNNER = [os.path.join(BACKEND, "venv", "bin", "python"), os.path.join(BACKEND, "scripts", "pv_dda_v24confirm_20261019.py"), "run"]
TICK, MAXW, BAD_TICKS = 20, 4, 3
MAX_RUNNER_STARTS, MAX_SUP_RESTARTS = 8, 3
STATE = os.path.join(OUT, "sup_state.json")


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()   # local time = KST on this Mac


T_NO_NEW, T_TERM, T_KILL, T_EXIT = ts("2026-10-20 09:30"), ts("2026-10-20 09:50"), ts("2026-10-20 09:55"), ts("2026-10-20 09:58")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def pressure():
    try:
        return int(sh(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip())
    except ValueError:
        return -1


def mem_free_pct():
    m = re.search(r"free percentage: (\d+)%", sh(["memory_pressure", "-Q"]))
    return int(m.group(1)) if m else -1


def swap():
    s = sh(["sysctl", "vm.swapusage"])
    return float(re.search(r"used = ([\d.]+)M", s).group(1)), float(re.search(r"free = ([\d.]+)M", s).group(1))


def event(msg):
    with open(os.path.join(OUT, "sup_events.log"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{msg}\n")


def workers():
    try:
        return int(open(os.path.join(OUT, "workers")).read().strip())
    except (OSError, ValueError):
        return 1


def set_workers(w, why):
    with open(os.path.join(OUT, "workers"), "w") as f:
        f.write(str(w))
    event(f"workers -> {w} ({why})")


def progress():
    p = os.path.join(OUT, "progress.jsonl")
    return [json.loads(x) for x in open(p)] if os.path.exists(p) else []


def queue_left():
    q = json.load(open(os.path.join(OUT, "queue.json")))
    return sum(1 for it in q if not os.path.exists(os.path.join(OUT, "work", f"{it['level']:04d}", "result.json")))


def resume_free_mb():
    """Resume threshold (MB swap free), file `resume_free_mb` (read each tick; floor 700 = stop 500 + 200 margin)."""
    try:
        return max(700, int(open(os.path.join(OUT, "resume_free_mb")).read().strip()))
    except (OSError, ValueError):
        return 1000


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"supStarts": [], "runnerStarts": [], "halt": None, "lastChange": 0, "basePw": None, "swapHist": [],
            "bad": {}, "goodSince": None, "stopped": None,
            "note": "pre-hardening supervisor starts 19:26 81717, 19:34 83229, 19:35 83473, 19:43 85004 (not counted)"}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


class Runner:
    def __init__(self, pid, popen=None):
        self.pid, self.popen = pid, popen

    def alive(self):
        if self.popen is not None:
            return self.popen.poll() is None
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        return "pv_dda_v24confirm_20261019.py" in sh(["ps", "-o", "command=", "-p", str(self.pid)])


def adopt():
    try:
        r = Runner(int(open(os.path.join(OUT, "runner.pid")).read().strip()))
    except (OSError, ValueError):
        return None
    return r if r.alive() else None


def safe_stop(run, why):
    """TERM runner group -> 20 s grace -> KILL. Only the runner's own process group."""
    if run is None or not run.alive():
        return
    try:
        os.killpg(run.pid, signal.SIGTERM)
        event(f"{why}: SIGTERM runner group {run.pid}")
    except ProcessLookupError:
        return
    for _ in range(20):
        time.sleep(1)
        if not run.alive():
            event(f"runner {run.pid} exited after TERM")
            return
    try:
        os.killpg(run.pid, signal.SIGKILL)
        event(f"{why}: SIGKILL runner group {run.pid} (no exit within 20 s)")
    except ProcessLookupError:
        pass


# ── live throughput (current runner only) ──────────────────────────────────────────────────────────────
EFF_WINDOW, EFF_MIN_OBS, EFF_MIN = 300, 180, 0.5      # s, s, CPU-share per worker
STALL_SEC = 45 * 60                                   # no new stage checkpoint for this long -> stop


def _cpu_secs(t):
    d = 0
    if "-" in t:
        d, t = t.split("-")
    parts = [float(x) for x in t.split(":")]
    sec = 0.0
    for x in parts:
        sec = sec * 60 + x
    return int(d) * 86400 + sec


def group_cpu(pgid):
    """(total CPU s of runner process group, number of pool worker processes)."""
    cpu, nw = 0.0, 0
    for line in sh(["ps", "-A", "-o", "pgid=,time=,command="]).splitlines():
        f = line.split(None, 2)
        if len(f) < 3 or f[0] != str(pgid):
            continue
        cpu += _cpu_secs(f[1])
        if "spawn_main" in f[2] and "resource_tracker" not in f[2]:
            nw += 1
    return cpu, nw


def efficiency(hist, now, seg_t0):
    """CPU share per worker over the last EFF_WINDOW s of the current segment (same runner, same worker count).
    hist [[t, cpu, nw]]; seg_t0 = max(runner start, last worker-count change). None until EFF_MIN_OBS observed."""
    lo = max(seg_t0, now - EFF_WINDOW)
    pts = [h for h in hist if h[0] >= lo]
    if not pts or now - seg_t0 < EFF_MIN_OBS or pts[-1][0] - pts[0][0] < EFF_MIN_OBS * 0.8:
        return None
    nw = pts[-1][2]
    if nw <= 0:
        return 0.0
    return (pts[-1][1] - pts[0][1]) / ((pts[-1][0] - pts[0][0]) * nw)


def update_bad(bad, conds, alive):
    """Counters accumulate only while the runner is alive; frozen (unchanged) while halted."""
    if not alive:
        return dict(bad)
    return {k: (bad.get(k, 0) + 1) if v else 0 for k, v in conds.items()}


def newest_checkpoint():
    t = 0.0
    wd = os.path.join(OUT, "work")
    for d in os.listdir(wd):
        for fn in ("scan.json", "c1.json", "c2.json", "result.json"):
            p = os.path.join(wd, d, fn)
            if os.path.exists(p):
                t = max(t, os.path.getmtime(p))
    return t


def stalled(now, run_t0, newest, limit=STALL_SEC):
    return now - max(run_t0, newest) > limit


def new_run_ctx(pid, t0):
    return {"pid": pid, "t0": t0, "segT0": t0, "hist": [], "nw": None}


def main():
    lock = open(os.path.join(OUT, "supervisor.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another supervisor holds supervisor.lock — exit", flush=True)
        sys.exit(1)
    lock.write(str(os.getpid()))
    lock.flush()
    with open(os.path.join(OUT, "supervisor.pid"), "w") as f:
        f.write(str(os.getpid()))
    with open(os.path.join(OUT, "NO_NEW_AFTER"), "w") as f:
        f.write(str(T_NO_NEW))
    st = load_state()
    st["supStarts"].append({"t": time.time(), "pid": os.getpid()})
    run = adopt()
    event(f"supervisor start pid={os.getpid()} (hardened start #{len(st['supStarts'])}, "
          f"runner starts so far {len(st['runnerStarts'])}){' adopted runner ' + str(run.pid) if run else ''}")
    if len(st["supStarts"]) - 1 > MAX_SUP_RESTARTS:
        safe_stop(run, "supervisor restart limit exceeded")
        open(os.path.join(OUT, "STOP"), "w").write("supervisor restart limit exceeded\n")
        st["stopped"] = {"t": time.time(), "why": "supervisor restart limit"}
        save_state(st)
        event("supervisor restart limit exceeded — STOP written, no new batches, exit")
        return
    save_state(st)
    log = open(os.path.join(OUT, "sup.log"), "a")
    while True:
        now = time.time()
        pr, (used, free), mf = pressure(), swap(), mem_free_pct()
        disk = shutil.disk_usage("/System/Volumes/Data").free / 2**30
        st["swapHist"] = [h for h in st["swapHist"] if now - h[0] <= 300] + [[now, used]]
        rise = used - min(u for _, u in st["swapHist"])
        alive = run is not None and run.alive()
        prog = progress()
        w = workers()
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tpressure={pr}\tswapFreeMB={free:.0f}\trise5m={rise:.0f}"
                  f"\tdiskGiB={disk:.1f}\tworkers={w}\trunner={run.pid if alive else '-'}\tdone={len(prog)}"
                  f"\tmemFree%={mf}\thalt={'Y' if st['halt'] else '-'}\n")
        log.flush()

        if now >= T_EXIT:
            safe_stop(run if alive else None, "deadline exit")
            event("supervisor exit (deadline)")
            save_state(st)
            return
        if now >= T_KILL and alive:
            os.killpg(run.pid, signal.SIGKILL)
            event(f"09:55 hard stop: SIGKILL runner group {run.pid}")
        elif now >= T_TERM and alive:
            safe_stop(run, "09:50 safe stop")

        # live throughput of the CURRENT runner only (no past progress records) + sustained counters
        rc = st.get("run")
        eff, stall = None, False
        if alive:
            if not rc or rc.get("pid") != run.pid:
                rc = st["run"] = new_run_ctx(run.pid, now)
                st["bad"] = {}
            cpu, nw = group_cpu(run.pid)
            if rc["nw"] != nw:                       # pool size changed (applied at level boundary) -> new segment
                rc["nw"], rc["segT0"] = nw, now
                st["bad"] = {}
            rc["hist"] = [h for h in rc["hist"] if now - h[0] <= EFF_WINDOW + 60] + [[now, cpu, nw]]
            eff = efficiency(rc["hist"], now, rc["segT0"])
            stall = stalled(now, rc["t0"], newest_checkpoint())
        degrade = eff is not None and eff < EFF_MIN
        conds = {"swapRise400": rise > 400, "ramLow15": 0 <= mf < 15, "throughput50": degrade, "swapFree600": free < 600}
        st["bad"] = update_bad(st["bad"], conds, alive)
        sustained = [k for k in conds if st["bad"].get(k, 0) >= BAD_TICKS]
        if alive:
            log.write(f"\t\tlive eff={eff if eff is None else round(eff, 3)} nw={rc['nw']} bad={st['bad']}\n")
            log.flush()
        cur = [r for r in prog if alive and r["workers"] == w and r.get("t", "") >= time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(rc["segT0"]))]
        crit = pr >= 4 or free < 500 or disk < 10

        if alive and (crit or stall or (sustained and w == 1)):
            why = (f"STOP pressure={pr} swapFree={free:.0f} disk={disk:.1f}" if crit
                   else f"NO PROGRESS: no new stage checkpoint for {STALL_SEC // 60} min" if stall
                   else f"DEGRADE at 1 worker (sustained {sustained}, eff={eff}) swapFree={free:.0f} rise5m={rise:.0f} memFree={mf}%")
            safe_stop(run, why)
            st["halt"] = {"t": now, "why": why}
            st["goodSince"] = None
            st["lastChange"] = now
            if w > 1:
                set_workers(w - 1, "after stop")
        elif alive and now - st["lastChange"] >= 120:
            if w > 1 and sustained:
                set_workers(w - 1, f"reduce (sustained {sustained}) swapFree={free:.0f} rise5m={rise:.0f} memFree={mf}%")
                st["lastChange"] = now
            elif w < MAXW and now - st["lastChange"] >= 600 and cur and free >= 700 and pr <= 2 and rise < 200 \
                    and mf >= 20 and now < T_NO_NEW - 1800:
                set_workers(w + 1, f"step up swapFree={free:.0f} rise5m={rise:.0f} pressure={pr} memFree={mf}%")
                st["lastChange"] = now

        alive = run is not None and run.alive()
        rfree = resume_free_mb()
        good = free >= rfree and pr < 4 and mf >= 20 and rise < 200
        st["goodSince"] = (st["goodSince"] or now) if good else None
        can_start = now < T_NO_NEW and not os.path.exists(os.path.join(OUT, "STOP")) and queue_left() > 0
        if not alive and can_start:
            halted = st["halt"] is not None
            if len(st["runnerStarts"]) >= MAX_RUNNER_STARTS:
                if not st.get("stopped"):
                    st["stopped"] = {"t": now, "why": "runner start limit"}
                    event(f"runner start limit {MAX_RUNNER_STARTS} reached — no new batches")
            elif not halted or (st["goodSince"] and now - st["goodSince"] >= 900):
                rl = open(os.path.join(OUT, "runner.log"), "a")
                p = subprocess.Popen(RUNNER, cwd=BACKEND, stdout=rl, stderr=subprocess.STDOUT, start_new_session=True)
                run = Runner(p.pid, p)
                with open(os.path.join(OUT, "runner.pid"), "w") as f:
                    f.write(str(p.pid))
                st["run"] = new_run_ctx(p.pid, now)
                st["bad"] = {}
                st["runnerStarts"].append({"t": now, "pid": p.pid, "workers": workers(),
                                           "afterHalt": st["halt"]})
                event(f"runner start pid={p.pid} workers={workers()} (runner start #{len(st['runnerStarts'])})"
                      + (f" resume after halt: {st['halt']['why']}" if halted else ""))
                st["halt"] = None
                st["lastChange"] = now
        if not alive and queue_left() == 0:
            event("queue complete — supervisor exit")
            save_state(st)
            return
        save_state(st)
        time.sleep(TICK)


if __name__ == "__main__":
    main()
