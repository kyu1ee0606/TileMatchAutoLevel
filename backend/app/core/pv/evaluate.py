"""E-P1-3: seed-variant evaluation (04 §A4) — bots/solver are imported, shared core is NOT modified.

Metric W = mean bot success rate over skill points θ (bot-weighted success; NOT a human clear rate).
Games are run per (map, θ) with explicit per-game seeds `seed_base + i` (BotSimulator seeds its
RNG with seed+i, same as simulate_with_profile), early termination OFF, so the same game index i
uses the same bot random stream across candidate maps (CRN) and outcomes can be paired.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, Sequence

from app.core.bot_simulator import BotSimulator
from app.core.mc_difficulty import make_skill_profile

THETAS = (0.29, 0.47, 0.65)  # population N(0.47, 0.18) ±1σ (04 §A4)
EVAL_VERSION = "pv-eval@1"


def candidate_seeds(struct_hash: str, k: int) -> List[int]:
    """04 §A4: seed_k = 1 + (u32(sha256(f"{structHash}|{k}")[:4]) mod (2^31-2)); unique, in [1, 2^31-1]."""
    out: List[int] = []
    seen = set()
    j = 0
    while len(out) < k:
        d = hashlib.sha256(f"{struct_hash}|{j}".encode("utf-8")).digest()
        s = 1 + (int.from_bytes(d[:4], "big") % (2**31 - 2))
        j += 1
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class _TrackingBot(BotSimulator):
    """Records tray occupancy once per turn via the per-turn hook `_update_curtain_memory`
    (called exactly once at the top of every `_play_game` turn; `_is_game_over` is also used
    inside look-ahead and would over-count)."""

    def reset_track(self) -> None:
        self.t_max = 0
        self.t_crisis_turns = 0
        self.t_turns = 0

    def _observe(self, state) -> None:
        occ = len(state.dock_tiles)
        self.t_turns += 1
        if occ > self.t_max:
            self.t_max = occ
        if occ >= state.max_dock_slots - 1:
            self.t_crisis_turns += 1

    def _update_curtain_memory(self, state, profile):  # noqa: D401 - hook
        self._observe(state)
        return super()._update_curtain_memory(state, profile)


def run_games_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """ProcessPool unit: games [start, start+count) of one (map, θ)."""
    t0 = time.time()
    bot = _TrackingBot()
    lj = args["level_json"]
    profile = make_skill_profile(float(args["theta"]))
    base = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(base)
    wins: List[int] = []
    dock_max: List[int] = []
    crisis_any: List[int] = []
    crisis_frac: List[float] = []
    for i in range(args["start"], args["start"] + args["count"]):
        bot._rng.seed(args["seed_base"] + i)
        bot.reset_track()
        state = bot._fast_copy_state(base)
        final = bot._play_game(state, profile)
        bot._observe(final)
        wins.append(1 if final.cleared else 0)
        dock_max.append(bot.t_max)
        crisis_any.append(1 if bot.t_crisis_turns > 0 else 0)
        crisis_frac.append(bot.t_crisis_turns / max(1, bot.t_turns))
    return {
        "key": args["key"], "theta": args["theta"], "start": args["start"],
        "wins": wins, "dockMax": dock_max, "crisisAny": crisis_any, "crisisFrac": crisis_frac,
        "sec": time.time() - t0,
    }


def evaluate_maps(
    executor,
    maps: Dict[str, Dict[str, Any]],
    games_per_point: int,
    seed_base: int,
    thetas: Sequence[float] = THETAS,
    chunk: int = 100,
) -> Dict[str, Dict[str, Any]]:
    """Evaluate bot-level-json maps. Returns {key: {"theta": {θ: {...per-game lists...}}, "W": float}}.

    Game i at θ index t uses bot seed `seed_base + t*10_000 + i` — identical across maps (CRN).
    """
    futures = []
    for key, lj in maps.items():
        for t_idx, th in enumerate(thetas):
            for start in range(0, games_per_point, chunk):
                futures.append(executor.submit(run_games_task, {
                    "key": key, "theta": th, "level_json": lj,
                    "seed_base": seed_base + t_idx * 10_000,
                    "start": start, "count": min(chunk, games_per_point - start),
                }))
    acc: Dict[str, Dict[float, List[Dict[str, Any]]]] = {}
    cpu = 0.0
    for f in futures:
        r = f.result()
        cpu += r["sec"]
        acc.setdefault(r["key"], {}).setdefault(r["theta"], []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for key, per_theta in acc.items():
        th_out = {}
        for th, parts in per_theta.items():
            parts.sort(key=lambda p: p["start"])
            merged = {k: [x for p in parts for x in p[k]] for k in ("wins", "dockMax", "crisisAny", "crisisFrac")}
            n = len(merged["wins"])
            th_out[str(th)] = {
                **merged,
                "n": n,
                "rate": sum(merged["wins"]) / n,
                "dockMaxMean": sum(merged["dockMax"]) / n,
                "crisisGameRate": sum(merged["crisisAny"]) / n,
                "crisisTurnFrac": sum(merged["crisisFrac"]) / n,
            }
        out[key] = {"theta": th_out, "W": sum(v["rate"] for v in th_out.values()) / len(th_out)}
    out["_cpuSec"] = cpu  # type: ignore[assignment]
    return out


def solve_check(level_json: Dict[str, Any], node_budget: int = 5000, time_cap_s: float = 600.0) -> Dict[str, Any]:
    """Solver A with a node budget (time cap only as a safety net; 04 C9). UNCERTAIN = unverified."""
    from app.core.solver import solve_level

    t0 = time.time()
    r = solve_level(level_json, node_budget=node_budget, time_budget_s=time_cap_s)
    verdict = r.get("verdict") if isinstance(r, dict) else getattr(r, "verdict", None)
    if hasattr(verdict, "value"):
        verdict = verdict.value
    return {"verdict": str(verdict), "nodeBudget": node_budget, "sec": round(time.time() - t0, 2)}
