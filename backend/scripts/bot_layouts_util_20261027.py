"""Common layout rule for bot measurement runners (2026-10-27, doc 63 §2).

Random-layout maps (prep mode 'random': the game re-shuffles t0 per play) must be measured over SEVERAL layouts:
  layouts_for(L, games) -> list of (layout_json, n_games, layout_seed)
  random maps: N_RANDOM layout seeds 1..N_RANDOM, games split evenly (games % N_RANDOM == 0 required)
  fixed maps : the single fixed layout, all games.
Per-game RNG seed convention: seedbase + layout_index * 1000 + game_index (same as bot_v24_eval / doc 62 runner).
"""
from pathlib import Path
import sys
B_ = Path(__file__).resolve().parents[1]
if str(B_ / 'scripts') not in sys.path: sys.path.insert(0, str(B_ / 'scripts'))
N_RANDOM = 16


def layouts_for(c, L, games, n_random=N_RANDOM):
    entry = c.P[L]
    if entry['mode'] == 'random':
        assert games % n_random == 0, (games, n_random)
        lays = c.ev.base.level_layouts(entry, n_random)
        return [(lay, games // n_random, i + 1) for i, lay in enumerate(lays)]
    return [(c.ev.base.level_layouts(entry, 1)[0], games, None)]
