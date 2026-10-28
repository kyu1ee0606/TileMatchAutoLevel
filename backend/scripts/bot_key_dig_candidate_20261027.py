"""K2 candidate `key_container_dig` (opt-in, runner-side subclass; core bot_simulator.py untouched).

Doc 57. Diagnosis (doc 56 §9 / 26 top): L138 keys sit inside one stack; the bot takes the first keys late, then
two keys wait in the dock while the non-key tiles between them fill the 6 open slots.

Rule (public information only, active only while a dock slot is locked):
- hidden_keys = 3 x locked slots - keys in dock - keys visible on the board (type not hidden by curtain/unknown).
  (lock count is public; the game locks keys // 3 slots, TileGroup.cs:1335-1338)
- a "key container" = a stack/craft whose earlier tile is a key now waiting in the dock (the player saw it come out).
- bonus key_first_w * s(theta) (existing fitted weight 30, no new constant) for picking the current top / emitted
  tile of a key container when hidden_keys > 0, the pick is not a key (key_first covers keys), and
  free slots >= 4 (after the pick free >= 3, i.e. outside the existing 'danger' zone free <= 2, doc 55 §8).
OFF (option absent) or no locked slot -> returns exactly the parent's value, no RNG use.
"""
from pathlib import Path
import sys
B_ = Path(__file__).resolve().parents[1]
if str(B_) not in sys.path: sys.path.insert(0, str(B_))
from app.core.bot_simulator import BotSimulator

OPTION = "key_container_dig"


def container_id(t):
    if t is None: return None
    if t.is_craft_tile:
        k = t.original_full_key or t.full_key
        return 'c:' + k.rsplit('_', 1)[0]
    if t.is_stack_tile:
        return f's:{t.layer_idx}_{t.x_idx}_{t.y_idx}'
    return None


class KeyDigBot(BotSimulator):
    def _v24_behaviour_bonus(self, move, state, dock_count, dc_risk):
        bonus = super()._v24_behaviour_bonus(move, state, dock_count, dc_risk)
        if OPTION not in self._v24:
            return bonus
        locked = sum(1 for sl in state.dock if sl.is_locked)
        ts = move.tile_state
        if locked == 0 or ts is None or move.tile_type == "key" or not (ts.is_stack_tile or ts.is_craft_tile):
            return bonus
        free = (len(state.dock) - locked) - dock_count
        if free < 4:
            return bonus
        dock_keys = [t for t in state.dock_tiles if t.tile_type == "key"]
        if not dock_keys:
            return bonus
        visible = sum(1 for layer in state.tiles.values() for t in layer.values()
                      if t.tile_type == "key" and not t.picked and not self._v24_type_hidden(state, t))
        if 3 * locked - len(dock_keys) - visible <= 0:
            return bonus
        if container_id(ts) in {container_id(t) for t in dock_keys}:
            bonus += self._v24_bp["key_first_w"] * self._v24_skill()
        return bonus
