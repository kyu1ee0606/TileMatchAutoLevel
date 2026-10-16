"""Shared bot measurement for candidate maps — one function for both target modes (doc 35 §3-6 #2, §9-8).

    measure(game_map, conditions, *, placement_level, exposure, protocol, seed_band) -> BotMeasurement
    MeasurementStore(path)   JSON store keyed by cond_hash + protocol + seed band + bot config (both modes share it)

Same bot and settings as the training rows of the active model (`bot_v24_eval.run_task` with the V24_DEFAULT items,
`bot_v21_fit.FIXED`, V21 awareness defaults, level exposure, `bot_af_L32_500.level_layouts`), so a map measured
here on the training seed band reproduces the stored training rows exactly (checked by the pilot script's golden
step). Seeds: band base + layout_index*1000 + game (training "seed11M" = 11,000,000; doc 35 P-a S = 15,000,000,
C = 16,000,000). The bot plays without boosters / revives.

Bot config depends on the placement level through `exposure` (number of earlier live levels containing bomb /
grass — bomb / grass awareness), so the store key carries a bot-config hash as well as the condition hash: a change
of map, game fields or placement gives a different key (old entries are never reused).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from .conditions import cond_hash, normalize_conditions
from .predict import BotMeasurement

BOT_VERSION = "v2.4"
LAYOUTS = 32                                   # bot_af_L32_500.LAYOUTS
FIXED = {"beta": 4.0, "l0": 0.5, "tau": 15.0}   # bot_v21_fit.FIXED
SEED_BANDS = {"seed11M": 11_000_000, "S": 15_000_000, "C": 16_000_000}
# protocol → (θ list, games per θ). theta4x128_v1 = the model protocol (A, and B search). theta085x512_v1 = B confirm.
PROTOCOLS: Dict[str, Tuple[Tuple[float, ...], int]] = {
    "theta4x128_v1": ((0.55, 0.65, 0.85, 1.0), 128),
    "theta085x512_v1": ((0.85,), 512),
}
EXPOSURE_GIMMICKS = ("bomb", "grass")          # bot_v21_fit.GIMMICKS (awareness exposure)
NO_AIDS = {"booster": False, "revive": False}


def v24_items() -> Tuple[str, ...]:
    from app.core.bot_simulator import V24_DEFAULT
    return tuple(V24_DEFAULT)


def bot_exposure(position: Dict[str, Any], placement_level: int) -> Dict[str, Dict[str, int]]:
    """Exposure inputs for placement L from a position table ({"exposure": {L: {gimmick: n_levels_before}}}):
    bomb / grass for the awareness model, grass / chain for v2.4 gc_naive (item off by default — recorded only)."""
    keys = sorted(int(k) for k in position["exposure"])
    e = position["exposure"][str(min(max(int(placement_level), keys[0]), keys[-1]))]
    return {"exposure": {g: int(e.get(g, 0)) for g in EXPOSURE_GIMMICKS},
            "v24_expo": {g: int(e.get(g, 0)) for g in ("grass", "chain")}}


def bot_config(exposure: Dict[str, Dict[str, int]], conditions: Dict[str, Any]) -> Dict[str, Any]:
    cond = normalize_conditions(conditions)
    return {"bot_version": BOT_VERSION, "v24_items": list(v24_items()), "fixed": FIXED,
            "exposure": exposure["exposure"], "v24_expo": exposure["v24_expo"],
            "auto_collect": cond["autoCollectCount"], "aids": NO_AIDS}


def config_hash(cfg: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def layout_mode(game_map: Dict[str, Any]) -> str:
    from app.core.pv.cs_shuffle import build_level_model, get_empty_tile_list
    return "random" if get_empty_tile_list(build_level_model(copy.deepcopy(game_map))) else "fixed"


def level_layouts(game_map: Dict[str, Any], cond: Dict[str, Any], mode: str, n_layouts: int):
    """bot_af_L32_500.level_layouts on (map, final conditions)."""
    from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles
    from app.core.pv.t0ize import bot_level_json
    if mode == "fixed":
        return [bot_level_json({"randSeed": cond["randSeed"] or 1, "useTileCount": cond["useTileCount"],
                                "unlockTile": cond["unlockTile"] or 0}, game_map)]
    out = []
    for s in range(1, n_layouts + 1):
        res = shuffle_empty_tiles(game_map, rand_seed=s, use_tile_count=cond["useTileCount"],
                                  unlock_tile=cond["unlockTile"] or 0, shuffle_tile=cond["shuffleTile"] or 0,
                                  type_imbalance=cond["typeImbalance"] or 0, strict=True)
        out.append(bot_level_json({"randSeed": s, "useTileCount": cond["useTileCount"],
                                   "unlockTile": cond["unlockTile"] or 0}, resolve_map(game_map, res)))
    return out


def _fail_reason(bot, s) -> str:
    """bot_af_L32_500.fail_reason."""
    if not s.failed:
        return "clear" if s.cleared else "unfinished"
    if bot._is_dock_full(s):
        return "Normal"
    if any(v <= 0 for v in s.bomb_tiles.values()):
        return "Bomb"
    if bot._check_grass_impossible(s):
        return "Grass"
    if bot._check_ice_impossible(s):
        return "Ice"
    if bot._check_chain_impossible(s):
        return "Chain"
    if s.moves_used >= s.max_moves:
        return "MaxMoves"
    return "NoMoves"


def measure_theta(game_map: Dict[str, Any], conditions: Dict[str, Any], *, theta: float, games: int,
                  seed_base: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """One (θ, games) row — bot_v24_eval.run_task logic on an explicit map + final conditions."""
    import dataclasses
    from app.core.bot_simulator import BotSimulator, V21_AWARENESS_DEFAULTS
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    cond = normalize_conditions(conditions)
    mode = layout_mode(game_map)
    lays = level_layouts(game_map, cond, mode, min(LAYOUTS, games) if mode == "random" else 1)
    per = games // len(lays)
    prof = make_skill_profile(theta, BOT_VERSION)
    aw = dict(prof.gimmick_awareness)
    aw.update(cfg["fixed"])
    aw["alpha"], aw["gamma"] = dict(V21_AWARENESS_DEFAULTS["alpha"]), dict(V21_AWARENESS_DEFAULTS["gamma"])
    aw["exposure"] = dict(cfg["exposure"])
    aw["parity"] = None
    aw["auto_collect"] = int(cfg["auto_collect"])
    aw["v24_expo"] = dict(cfg["v24_expo"])
    aw["v24"] = list(cfg["v24_items"])
    prof = dataclasses.replace(prof, gimmick_awareness=aw)
    bot = BotSimulator()
    wins, left, left_board, reasons, n = 0, [], [], Counter(), 0
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        bot.set_rule_parity(prof)
        st0 = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(st0)
        for g in range(per):
            bot._rng.seed(seed_base + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(st0), prof)
            n += 1
            if final.cleared:
                wins += 1
            else:
                rem = total - final.total_tiles_cleared
                left.append(rem)
                left_board.append(rem - len(final.dock_tiles))
                reasons[_fail_reason(bot, final)] += 1
    return {"theta": theta, "games": n, "wins": wins, "layouts": len(lays), "fail_reasons": dict(reasons),
            "fail_tiles_left": left, "fail_tiles_left_board": left_board, "sec": round(time.time() - t0, 3)}


def _row_task(args: Dict[str, Any]) -> Dict[str, Any]:
    import resource
    r = measure_theta(args["map"], args["cond"], theta=args["theta"], games=args["games"],
                      seed_base=args["seed_base"], cfg=args["cfg"])
    r["maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20, 1)  # macOS: bytes
    return r


def measure(game_map: Dict[str, Any], conditions: Dict[str, Any], *, exposure: Dict[str, Dict[str, int]],
            protocol: str, seed_band: str, executor=None) -> Tuple[BotMeasurement, Dict[str, Any]]:
    """Measure the final game conditions under `protocol` on `seed_band`. Returns the BotMeasurement (tagged with
    cond_hash / seed band / no aids) and run meta (bot config + hash, games, cpu seconds, peak worker RSS).
    executor: optional ProcessPoolExecutor (θ rows run in parallel)."""
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol {protocol}")
    if seed_band not in SEED_BANDS:
        raise ValueError(f"unknown seed band {seed_band}")
    cond = normalize_conditions(conditions)
    thetas, games = PROTOCOLS[protocol]
    cfg = bot_config(exposure, cond)
    tasks = [{"map": game_map, "cond": cond, "theta": t, "games": games, "seed_base": SEED_BANDS[seed_band],
              "cfg": cfg} for t in thetas]
    rows = list(executor.map(_row_task, tasks)) if executor else [_row_task(t) for t in tasks]
    m = BotMeasurement(bot_version=BOT_VERSION, protocol=protocol, cond_hash=cond_hash(game_map, cond),
                       rows=tuple({k: v for k, v in r.items() if k not in ("sec", "maxrss_mb")} for r in rows),
                       seed_band=seed_band, source="measure", aids_simulated=dict(NO_AIDS))
    meta = {"bot_config": cfg, "bot_config_hash": config_hash(cfg), "games": sum(r["games"] for r in rows),
            "cpu_sec": round(sum(r["sec"] for r in rows), 2), "peak_worker_rss_mb": max(r["maxrss_mb"] for r in rows),
            "seed_rule": f"{SEED_BANDS[seed_band]:,} + layout_index*1000 + game"}
    return m, meta


def store_key(chash: str, protocol: str, seed_band: str, cfg_hash: str) -> str:
    return f"{chash}|{protocol}|{seed_band}|{cfg_hash}"


class MeasurementStore:
    """Measurement records shared by both modes. Key = cond_hash | protocol | seed band | bot-config hash.
    A record is returned only when every key part matches, so changed conditions / placement never hit."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, Any] = (json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {})

    def get(self, chash: str, protocol: str, seed_band: str, cfg_hash: str) -> Optional[Tuple[BotMeasurement, Dict]]:
        rec = self.data.get(store_key(chash, protocol, seed_band, cfg_hash))
        if not rec:
            return None
        return BotMeasurement.from_dict(rec["measurement"], source="store"), rec["meta"]

    def put(self, m: BotMeasurement, meta: Dict[str, Any]) -> None:
        d = {"bot_version": m.bot_version, "protocol": m.protocol, "cond_hash": m.cond_hash, "rows": list(m.rows),
             "seed_band": m.seed_band, "skill_config": m.skill_config, "aids_simulated": m.aids_simulated}
        self.data[store_key(m.cond_hash, m.protocol, m.seed_band, meta["bot_config_hash"])] = {"measurement": d,
                                                                                              "meta": meta}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.path)


def measure_cached(store: Optional[MeasurementStore], game_map: Dict[str, Any], conditions: Dict[str, Any], *,
                   exposure: Dict[str, Dict[str, int]], protocol: str, seed_band: str,
                   executor=None) -> Tuple[BotMeasurement, Dict[str, Any], bool]:
    """measure() through the store. Returns (measurement, meta, from_store)."""
    cond = normalize_conditions(conditions)
    h, ch = cond_hash(game_map, cond), config_hash(bot_config(exposure, cond))
    if store is not None:
        hit = store.get(h, protocol, seed_band, ch)
        if hit:
            return hit[0], hit[1], True
    m, meta = measure(game_map, cond, exposure=exposure, protocol=protocol, seed_band=seed_band, executor=executor)
    if store is not None:
        store.put(m, meta)
    return m, meta, False


__all__ = ["BOT_VERSION", "PROTOCOLS", "SEED_BANDS", "MeasurementStore", "bot_config", "bot_exposure",
           "config_hash", "measure", "measure_cached", "measure_theta"]
