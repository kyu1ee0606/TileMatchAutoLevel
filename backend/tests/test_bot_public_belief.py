"""Opt-in behaviour contracts; no level outcomes or AF-fit expectations."""
import dataclasses
import random
import unittest
from collections import Counter

from app.core.bot_simulator import BotSimulator, GameState, TileState, TileEffectType, Move, DockSlot, V24_DEFAULT
from app.core.mc_difficulty import make_skill_profile


class PublicBeliefTests(unittest.TestCase):
    def bot(self, extra=()):
        b = BotSimulator()
        p = make_skill_profile(1.2, 'v2.4')
        # Isolate the option under test: pre-K1C default list (K1C = key_first + bomb_count_awareness, adopted
        # 2026-10-27, has its own tests in test_bot_k1c_core.py; public_craft_belief adopted 2026-10-27, doc 68,
        # tests in test_bot_p2_default.py).
        # B alignment (2026-10-27): V24_DEFAULT also holds the 3 measurement-BASE items -> isolate those too (frozen list).
        base = [x for x in V24_DEFAULT if x not in ('key_first', 'bomb_count_awareness', 'public_craft_belief',
                                                    'grass_skill_attention', 'hidden_common_samples', 'public_key_stack_plan')]
        p = dataclasses.replace(p, gimmick_awareness=dict(p.gimmick_awareness, v24=base + list(extra)))
        b.set_rule_parity(p)
        return b, p

    def state(self, hidden_type='secret'):
        a = TileState('t1', 0, 0, 0)
        h = TileState(hidden_type, 0, 1, 0, TileEffectType.CURTAIN, {'is_open': False})
        return GameState(tiles={0: {'0_0': a, '1_0': h}}, dock_tiles=[TileState('t1', 0, 2, 0)])

    def test_defaults_unchanged(self):
        # B alignment (2026-10-27, user decision): default == measurement BASE items.
        for x in ('grass_skill_attention', 'hidden_common_samples', 'public_key_stack_plan'):
            self.assertIn(x, V24_DEFAULT)

    def test_skill_attention_monotone_and_novice_baseline(self):
        b, _ = self.bot(['grass_skill_attention'])
        old, _ = self.bot()
        values = []
        for t in [.3, .55, .65, .85, 1., 1.2]:
            p = make_skill_profile(t, 'v2.4')
            values.append(b._v21_p_aware('grass', p, True))
            if t <= .55:
                self.assertEqual(values[-1], old._v21_p_aware('grass', p, True))
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], .9)
        self.assertTrue(all(x < 1 for x in values))

    def test_expert_can_still_miss_grass(self):
        b, p = self.bot(['grass_skill_attention'])
        st = GameState(tiles={0: {'0_0': TileState('t1', 0, 0, 0, TileEffectType.GRASS, {'remaining': 2})}})
        b._rng.seed(2)  # first uniform draw .956... exceeds the .9 attention cap
        b._v21_draw_awareness(st, p)
        self.assertFalse(b._v21_aware['grass'])

    def test_attention_cap_override_and_validation(self):
        b, p = self.bot(['grass_skill_attention'])
        for cap in [.45, .65, .9]:
            q = dataclasses.replace(p, gimmick_awareness=dict(p.gimmick_awareness, grass_attention_cap=cap))
            self.assertEqual(b._v21_p_aware('grass', q, True), cap)
        for cap in [0, 1, float('nan')]:
            q = dataclasses.replace(p, gimmick_awareness=dict(p.gimmick_awareness, grass_attention_cap=cap))
            with self.assertRaises(ValueError):
                b._v21_p_aware('grass', q, True)

    def test_single_hidden_inferred_without_reading_truth(self):
        b, _ = self.bot(['hidden_common_samples'])
        for secret in ['t2', 't15']:
            st = self.state(secret)
            self.assertTrue(b._v24_determinize(st))
            self.assertEqual(st.tiles[0]['1_0'].tile_type, 't1')
            self.assertEqual(Counter(t.tile_type for t in st.tiles[0].values()) + Counter(t.tile_type for t in st.dock_tiles), {'t1': 3})

    def test_inconsistent_inventory_no_oracle_fallback(self):
        b, _ = self.bot(['hidden_common_samples'])
        st = self.state(); st.dock_tiles.clear()
        self.assertFalse(b._v24_determinize(st))
        self.assertEqual(st.tiles[0]['1_0'].tile_type, 'secret')

    def test_locked_key_contract_skips_belief(self):
        b, _ = self.bot(['hidden_common_samples'])
        st = self.state(); st.dock = [DockSlot(0, is_locked=True)]
        self.assertFalse(b._v24_determinize(st))

    def test_regular_stack_registry_is_not_a_craft_box(self):
        b, _ = self.bot(['hidden_common_samples'])
        top = TileState('t1', 0, 0, 0, is_stack_tile=True, stack_index=1)
        bottom = TileState('secret', 0, 0, 0, is_stack_tile=True, stack_index=0)
        st = GameState(tiles={0: {'0_0': top}}, dock_tiles=[TileState('t1', 0, 1, 0)],
                       stacked_tiles={top.full_key: top, bottom.full_key: bottom},
                       craft_boxes={'0_0_0': [bottom.full_key, top.full_key]})
        self.assertTrue(b._v24_determinize(st))
        self.assertEqual(bottom.tile_type, 't1')
        copied = b._v2_copy_state(st)
        self.assertIs(copied.tiles[0]['0_0'], copied.stacked_tiles[top.full_key])
        copied.tiles[0]['0_0'].picked = True
        self.assertTrue(copied.stacked_tiles[top.full_key].picked)
        self.assertFalse(top.picked)

    def test_decision_counts_ignore_hidden_truth(self):
        b, _ = self.bot(['hidden_common_samples'])
        st = self.state('secret')
        st.all_tile_type_counts = {'secret': 99, 't1': 100}
        self.assertEqual(b._decision_tile_counts(st), {'t1': 1})
        self.assertTrue(b._v24_determinize(st))
        self.assertEqual(st.all_tile_type_counts, {'t1': 2})

    def test_rollout_copy_does_not_mutate_stack_effects(self):
        b, _ = self.bot(['hidden_common_samples'])
        st = self.state()
        t = TileState('hidden', 1, 0, 0, TileEffectType.GRASS, {'remaining': 2}, is_stack_tile=True, stack_index=0)
        st.stacked_tiles[t.full_key] = t
        copied = b._v2_copy_state(st)
        copied.stacked_tiles[t.full_key].effect_data['remaining'] = 0
        self.assertEqual(t.effect_data['remaining'], 2)
        copied.tiles[0]['1_0'].effect_data['is_open'] = True
        self.assertFalse(st.tiles[0]['1_0'].effect_data['is_open'])

    def test_common_seeds_and_parent_rng_restored(self):
        b, p = self.bot(['hidden_common_samples'])
        parent = b._rng
        seen = []
        def fake(st, move, profile, seeds):
            seen.append(list(seeds)); b._rng.random()
            return float(move.position)
        b._v2_rollout_value = fake
        moves = [Move(0, str(i), 't1', score=0) for i in [1, 2]]
        self.assertEqual(b._v2_search_select(moves, GameState(), p).position, '2')
        self.assertEqual(seen[0], seen[1])
        self.assertIs(parent, b._rng)

    def test_baseline_rng_and_legacy_rollout_path(self):
        b, p = self.bot()
        b._rng.seed(123); expected = random.Random(123)
        seen = []
        def fake(st, move, profile, seeds):
            self.assertIsNone(seeds); seen.append(b._rng.random()); return 0
        b._v2_rollout_value = fake
        b._v2_search_select([Move(0, str(i), 't1') for i in [1, 2]], GameState(), p)
        self.assertEqual(seen, [expected.random(), expected.random()])


if __name__ == '__main__':
    unittest.main()
