"""Drop-in for dda_spec_v2_measure20_20261022.games_task whose bot profile is the AF-validation measurement profile
(bot_measure_profile.make_measure_profile: v24 rules BASE, grass cap .65, auto_collect, exposure / v24_expo).

New DDA scripts (reselect / joint / screen) use `dda_aligned_games_20261028.games_task` instead of `m20.games_task`.
Past scripts are frozen and keep the old profile (make_skill_profile(theta,'v2.4') = V24_DEFAULT only, no cap/auto_collect/exposure).
Task dict = m20.games_task's {level, map, theta, lj, games, seedBase}; `level` = ORIGINAL level number (DDA variants share it).
auto_collect: a['lj']['autoCollectCount'] if present, else the original level's AF-cache row (bot_level_json drops the field).
Everything else (set_rule_parity -> _create_initial_state -> _precompute_blocking_map -> seed -> _play_game) is unchanged.
"""
import os, sys, time
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_measure_profile as MP


def games_task(a):
    from app.core.bot_simulator import BotSimulator
    t0 = time.time(); lj = a["lj"]
    prof, info = MP.make_measure_profile(a["theta"], a["level"], lj)
    bot = BotSimulator(); bot.set_rule_parity(prof)
    base = bot._create_initial_state(lj, int(lj["max_moves"])); bot._precompute_blocking_map(base)
    wins = []
    for g in range(a["games"]):
        bot._rng.seed(a["seedBase"] + g)
        wins.append(1 if bot._play_game(bot._fast_copy_state(base), prof).cleared else 0)
    return {"level": a["level"], "map": a["map"], "theta": a["theta"], "seedBase": a["seedBase"],
            "seedRange": [a["seedBase"], a["seedBase"] + a["games"] - 1], "n": a["games"], "wins": sum(wins),
            "perGame": "".join(map(str, wins)), "sec": round(time.time() - t0, 3), "pid": os.getpid(), "profile": info}
