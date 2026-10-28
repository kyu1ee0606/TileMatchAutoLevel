"""Grass / bomb perception candidates (opt-in, runner-side subclass; core bot_simulator.py untouched). Doc 58.

User observations (domain prior, not fitted to AF):
  grass: while a grass tile is covered (an upper-layer tile overlaps it) the player does not perceive it, so picks
         that strip its neighbours (game rule: covered grass is NOT reduced by neighbour picks, TileEffect.cs:965-975,
         fail when remaining neighbours < remaining layers, TileEffect.cs:1453-1466 / TileGroup.cs:2797-2811)
         are made without noticing the risk.
  bomb : a player does not re-decide every turn: once a bomb is noticed it stays noticed until it is defused or
         explodes; the chance to notice a not-yet-noticed exposed bomb grows as its counter falls.

G `grass_cover_blindness`  (no new constant)
  "covered" = the game's own predicate (bot _is_blocked_by_upper == CheckUpperTileExist). While ON, covered grass is
  absent from the player model: (a) the per-turn grass awareness draw only looks at uncovered grass (no draw when
  no uncovered grass), (b) awareness-gated grass scoring (reduce bonus, isolation penalty, public plan) ignores
  covered grass, (c) rollout samples (_v24_determinize copies) drop the grass effect of covered tiles, so search
  does not foresee covered-grass failures. Uncovered grass keeps the existing skill-based awareness draw
  (theta-dependent, never certain). The real game state and rule engine are untouched.

C `bomb_count_awareness`  (no new constant; replaces the bomb_threat_memory experiment, which is not combined)
  per-bomb noticed set in the game state (state._c_noticed), reset at game start.
  notice attempt: for every exposed (uncovered, unpicked, live) bomb not yet noticed, one draw from a DEDICATED RNG
    (state._c_rng, derived from the game seed without consuming the main RNG) with
    p = existing awareness p with logit alpha + beta(theta-1) + gamma / counter   (counter = that bomb's count;
    equal to the existing 'imminent' value at counter 1, strictly increasing as the counter falls; exposure factor kept).
  when: at game start and after every move inside _process_move_effects (after the counters tick) — the transition
    shared by the real game loop and search rollouts; rollout copies carry a cloned RNG + the noticed set, so search
    never advances the real RNG.
  persistence: a noticed bomb stays noticed until it leaves state.bomb_tiles (defused or exploded). No forgetting.
  use: the existing bomb urgency term sees only noticed bombs (others are invisible to the player model); the
    per-turn main-RNG bomb draw of the parent still happens (main RNG consumption unchanged) but no longer gates.
OFF (options absent) -> exactly the parent's behaviour (tests).
"""
from contextlib import contextmanager
import dataclasses
import random
from pathlib import Path
import sys
B_ = Path(__file__).resolve().parents[1]
if str(B_) not in sys.path: sys.path.insert(0, str(B_))
from app.core.bot_simulator import BotSimulator, TileEffectType

G_OPT = "grass_cover_blindness"
C_OPT = "bomb_count_awareness"
_C_SALT = 0x424F4D425F434F554E545F41574152454E455353   # "BOMB_COUNT_AWARENESS"


class GrassBombBot(BotSimulator):
    # ── G ────────────────────────────────────────────────────────────────────────────────────────
    def _covered_grass(self, state):
        return [t for layer in state.tiles.values() for t in layer.values()
                if not t.picked and t.effect_type == TileEffectType.GRASS
                and t.effect_data.get("remaining", 0) > 0 and self._is_blocked_by_upper(state, t)]

    @contextmanager
    def _hide_covered_grass(self, state):
        """Temporarily remove covered grass from the player's view (restores tiles and caches)."""
        if G_OPT not in self._v24:
            yield; return
        tiles = self._covered_grass(state)
        caches = (state._accessible_cache, state._accessible_type_counts, dict(state._blocking_cache))
        for t in tiles: t.effect_type = TileEffectType.NONE
        try:
            yield
        finally:
            for t in tiles: t.effect_type = TileEffectType.GRASS
            state._accessible_cache, state._accessible_type_counts = caches[0], caches[1]
            state._blocking_cache.clear(); state._blocking_cache.update(caches[2])

    def _grass_reduce_bonus(self, base_score, move, state, profile, dock_count):
        with self._hide_covered_grass(state):
            return super()._grass_reduce_bonus(base_score, move, state, profile, dock_count)

    def _grass_isolation_penalty(self, base_score, state, profile, tile_state):
        with self._hide_covered_grass(state):
            return super()._grass_isolation_penalty(base_score, state, profile, tile_state)

    def _public_grass_plan(self, move, state, profile):
        with self._hide_covered_grass(state):
            return super()._public_grass_plan(move, state, profile)

    def _v24_determinize(self, state):
        r = super()._v24_determinize(state)
        if r is not False and G_OPT in self._v24:
            for t in self._covered_grass(state):      # rollout copy only (_v2_copy_state copies unpicked tiles)
                t.effect_type = TileEffectType.NONE
            state._accessible_cache = None; state._accessible_type_counts = None
        return r

    # ── C: per-bomb persistent awareness ─────────────────────────────────────────────────────────
    def _exposed_bombs(self, state):
        out = []
        for bomb_key in sorted(state.bomb_tiles):
            parts = bomb_key.split('_')
            if len(parts) < 3: continue
            tile = state.tiles.get(int(parts[0]), {}).get(f"{parts[1]}_{parts[2]}")
            if tile is not None and not tile.picked and not self._is_blocked_by_upper(state, tile):
                out.append(bomb_key)
        return out

    def _c_p(self, profile, counter):
        cfg = dict(profile.gimmick_awareness or {})
        gamma = dict(cfg.get("gamma") or {})
        gamma["bomb"] = float(gamma.get("bomb", 0.0)) / max(1, int(counter))
        cfg["gamma"] = gamma
        return BotSimulator._v21_p_aware(self, "bomb", dataclasses.replace(profile, gimmick_awareness=cfg), True)

    def _c_update(self, state):
        """Notice attempts for exposed, not-yet-noticed bombs; drop bombs that left the board. Dedicated RNG only."""
        rng = getattr(state, "_c_rng", None)
        profile = getattr(self, "_c_profile", None)
        if rng is None or profile is None:
            return
        noticed = set(getattr(state, "_c_noticed", ())) & set(state.bomb_tiles)
        for k in self._exposed_bombs(state):
            if k not in noticed and rng.random() < self._c_p(profile, state.bomb_tiles[k]):
                noticed.add(k)
        state._c_noticed = frozenset(noticed)

    def _play_game(self, state, profile):
        self.set_rule_parity(profile)                                     # parent does the same first; no RNG
        if C_OPT in self._v24:
            self._c_profile = profile
            r = random.Random(); r.setstate(self._rng.getstate())        # clone: main RNG untouched
            r.seed(r.getrandbits(128) ^ _C_SALT)
            state._c_rng = r; state._c_noticed = frozenset()
            self._c_update(state)                                         # turn 1 attempt
        else:
            self._c_profile = None
            state._c_rng = None; state._c_noticed = frozenset()
        return super()._play_game(state, profile)

    def _process_move_effects(self, state, *a, **k):
        r = super()._process_move_effects(state, *a, **k)
        if C_OPT in self._v24:
            self._c_update(state)
        return r

    def _v2_copy_state(self, state):
        n = super()._v2_copy_state(state)
        n._c_noticed = getattr(state, "_c_noticed", frozenset())
        rng = getattr(state, "_c_rng", None)
        if rng is not None:
            n._c_rng = random.Random(); n._c_rng.setstate(rng.getstate())
        else:
            n._c_rng = None
        return n

    def _bomb_urgency(self, base_score, state, tile_state):
        if C_OPT not in self._v24:
            return super()._bomb_urgency(base_score, state, tile_state)
        noticed = getattr(state, "_c_noticed", frozenset())
        full = state.bomb_tiles
        state.bomb_tiles = {k: v for k, v in full.items() if k in noticed}
        try:
            return super()._bomb_urgency(base_score, state, tile_state)
        finally:
            state.bomb_tiles = full

    # ── per-turn draw: G hides covered grass; C keeps the parent's main-RNG draw but gates by the noticed set ──
    def _v21_draw_awareness(self, state, profile):
        with self._hide_covered_grass(state):
            r = super()._v21_draw_awareness(state, profile)
        if C_OPT in self._v24 and state.bomb_tiles:
            self._v21_aware["bomb"] = True      # urgency itself only sees noticed bombs (_bomb_urgency)
        return r
