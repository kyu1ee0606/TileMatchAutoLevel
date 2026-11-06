"""Fake `tilecore serve` (proto 1) for tests — deterministic fake games + fault injection.

Usage: python fake_tilecore_serve.py [--engine tilecore/7.0.0] [--proto 1] [--rules bs] [--sha X]
         [--delay-ms N] [--hang] [--crash-after N] [--unsupported] [--error] [--no-hello] [--no-state]
Faults:  --delay-ms   sleep before each sim reply (per-request thread, so replies overlap)
         --hang       never reply to sim (ping still works)
         --crash-after N  exit(3) while handling the (N+1)-th sim request, without replying
         --unsupported / --error  reply ok:false for every sim
         --no-hello   never send hello; --no-state  omit rng_state_out
Game generation (`fake_games`) is importable so tests can compute the expected C# answer.
Stdlib only; stdin EOF -> exit 0.
"""
import argparse
import json
import random
import sys
import threading
import time


def fake_games(rng, n, early_termination, reseed=None):
    """reseed: seed -> game i uses Random(seed+i) state (mode gen); None -> consume `rng` continuously (gen_state)."""
    games = []
    for i in range(n):
        if reseed is not None:
            rng.seed(reseed + i)
        g = {"cleared": rng.random() < 0.6, "failed": "", "moves": rng.randint(10, 40),
             "combo": rng.randint(0, 9), "tiles_cleared": rng.randint(5, 60)}
        games.append(g)
        if early_termination and len(games) >= 5:
            c = sum(1 for x in games if x["cleared"])
            if c == 0 or c == len(games):
                break
    return games


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="tilecore/7.0.0")
    ap.add_argument("--proto", type=int, default=1)
    ap.add_argument("--rules", default="bs")
    ap.add_argument("--sha", default="fakesha")
    ap.add_argument("--delay-ms", type=int, default=0)
    ap.add_argument("--hang", action="store_true")
    ap.add_argument("--crash-after", type=int, default=-1)
    ap.add_argument("--unsupported", action="store_true")
    ap.add_argument("--error", action="store_true")
    ap.add_argument("--no-hello", action="store_true")
    ap.add_argument("--no-state", action="store_true")
    a = ap.parse_args()

    out_lock = threading.Lock()

    def send(obj):
        with out_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    if not a.no_hello:
        send({"type": "hello", "proto": a.proto, "engine": a.engine, "rules": a.rules, "dll_sha256": a.sha,
              "src_commit": "fake", "threads": 1, "pid": 0})
    sims = 0

    def handle(req):
        if a.hang:
            time.sleep(3600)
        if a.delay_ms:
            time.sleep(a.delay_ms / 1000)
        rid = req["id"]
        if a.unsupported:
            return send({"id": rid, "ok": False, "unsupported": True, "error": "fake unsupported"})
        if a.error:
            return send({"id": rid, "ok": False, "unsupported": False, "error": "fake error"})
        rng = random.Random()
        if req["mode"] == "gen":
            games = fake_games(rng, req["iterations"], req["early_termination"], reseed=req["seed"])
        else:
            st = req["rng_state"]
            rng.setstate((3, tuple(st["mt"]) + (st["index"],), None))
            games = fake_games(rng, req["iterations"], req["early_termination"])
        resp = {"id": rid, "ok": True, "n": len(games), "games": games, "ms": 0.1, "rng_state_out": None}
        if req.get("want_state_out") and not a.no_state:
            _, internal, _ = rng.getstate()
            resp["rng_state_out"] = {"mt": list(internal[:624]), "index": internal[624]}
        send(resp)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        op = req.get("op")
        if op == "ping":
            send({"id": req["id"], "ok": True, "pong": True, "inflight": 0, "rss_mb": 1})
        elif op == "shutdown":
            send({"id": req["id"], "ok": True})
            return
        elif op == "sim":
            if a.crash_after >= 0 and sims >= a.crash_after:
                sys.exit(3)
            sims += 1
            threading.Thread(target=handle, args=(req,), daemon=True).start()
    time.sleep(0.2)  # let in-flight replies flush on EOF


if __name__ == "__main__":
    main()
