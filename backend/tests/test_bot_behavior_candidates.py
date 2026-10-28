import random
from collections import Counter
from tests.test_bot_public_belief import PublicBeliefTests
from app.core.bot_simulator import TileState, TileEffectType, GameState, DockSlot, Move


class BehaviorCandidateTests(PublicBeliefTests):
    def test_emitted_craft_score_resolves_original_box(self):
        import dataclasses
        b,p=self.bot(['hidden_common_samples'])
        emitted=TileState('t1',0,1,0,is_stack_tile=True,is_craft_tile=True,is_crafted=True,
                          original_full_key='0_0_0_2',origin_goal_type='craft_e')
        inner=TileState('secret',0,0,0,is_stack_tile=True,is_craft_tile=True)
        st=GameState(tiles={0:{'1_0':emitted}},stacked_tiles={'inner':inner},
                     craft_boxes={'0_0_0':['inner','0_0_0_2']},
                     goals_remaining={'craft_e':1},dock=[DockSlot(index=i)for i in range(7)])
        b._precompute_blocking_map(st)
        move=Move(0,'1_0','t1',tile_state=emitted)
        b._rng.seed(100)
        before=b._score_move_with_profile(move,st,p)
        q=dataclasses.replace(p,gimmick_awareness=dict(p.gimmick_awareness,v24=list(b._v24)+['public_container_origin_value']))
        b.set_rule_parity(q)
        b._rng.seed(100)
        after=b._score_move_with_profile(move,st,q)
        self.assertAlmostEqual(after-before,6*max(.3,p.goal_priority))
        inner.is_crafted=True
        b._rng.seed(100)
        self.assertAlmostEqual(b._score_move_with_profile(move,st,q),before)

    def test_craft_display_count_excludes_spawned_and_picked(self):
        b,_=self.bot(['public_container_live_value'])
        tiles={str(i):TileState('secret',0,i,0) for i in range(3)}
        tiles['0'].picked=True; tiles['1'].is_crafted=True
        st=GameState(stacked_tiles=tiles,craft_boxes={'box':['0','1','2']})
        self.assertEqual(b._public_craft_count(st,'box'),1)
        tiles['2'].tile_type='different_hidden_truth'
        self.assertEqual(b._public_craft_count(st,'box'),1)
        self.assertEqual(len(st.craft_boxes['box']),3)

    def test_deadline_does_not_lend_urgency_to_later_bomb(self):
        b, _ = self.bot(['public_bomb_deadline'])
        a = TileState('t1', 0, 0, 0, TileEffectType.BOMB)
        z = TileState('t2', 0, 1, 0, TileEffectType.BOMB)
        st = GameState(tiles={0:{'0_0':a,'1_0':z}}, bomb_tiles={'0_0_0':1,'0_1_0':4})
        early = Move(0,'0_0','t1',tile_state=a)
        later = Move(0,'1_0','t2',tile_state=z)
        self.assertEqual(b._public_bomb_deadline(0,st,early),500)
        self.assertEqual(b._public_bomb_deadline(0,st,later),-250)
        later.linked_tiles=[(0,'0_0')]
        self.assertEqual(b._public_bomb_deadline(0,st,later),500)
        self.assertEqual(st.bomb_tiles,{'0_0_0':1,'0_1_0':4})

    def test_key_belief_ignores_actual_hidden_types(self):
        b, _ = self.bot(['hidden_common_samples', 'public_key_stack_plan'])
        outputs = []
        for secrets in [('key', 'key', 'key'), ('t4', 't8', 't9')]:
            st = GameState(tiles={0: {f'{i}_0': TileState(tt, 0, i, 0, TileEffectType.CURTAIN, {'is_open': False}) for i, tt in enumerate(secrets)}}, dock=[DockSlot(index=0, is_locked=True)])
            b._rng.seed(42)
            self.assertTrue(b._v24_determinize(st))
            outputs.append([t.tile_type for t in st.tiles[0].values()])
            self.assertEqual(Counter(outputs[-1]), {'key': 3})
        self.assertEqual(outputs[0], outputs[1])

    def test_key_belief_impossible_public_contract(self):
        b, _ = self.bot(['hidden_common_samples', 'public_key_stack_plan'])
        st = self.state()
        st.dock = [DockSlot(index=0, is_locked=True)]
        self.assertFalse(b._v24_determinize(st))

    def test_memory_can_forget_and_copy_is_independent(self):
        b, p = self.bot(['grass_skill_attention', 'grass_risk_memory'])
        st = GameState(tiles={0: {'0_0': TileState('t1', 0, 0, 0, TileEffectType.GRASS, {'remaining': 2})}})
        st._grass_attention_ttl = 3
        b._rng.seed(2)  # fresh notice missed; retention draw .947... also fails
        b._v21_draw_awareness(st, p)
        self.assertFalse(b._v21_aware['grass'])
        self.assertEqual(st._grass_attention_ttl, 0)
        b._rng.seed(1)
        b._v21_draw_awareness(st, p)
        self.assertEqual(st._grass_attention_ttl, 5)
        st._grass_attention_ttl = 4
        copied = b._v2_copy_state(st)
        copied._grass_attention_ttl = 0
        self.assertEqual(st._grass_attention_ttl, 4)

    def test_style_copied_without_rng_change(self):
        b, _ = self.bot(['public_goal_style'])
        st = self.state(); st._container_style = .5
        before = b._rng.getstate()
        copied = b._v2_copy_state(st)
        self.assertEqual(copied._container_style, .5)
        self.assertEqual(before, b._rng.getstate())



class _SeqRng:
    def __init__(self, values):
        self.values = list(values); self.calls = 0
    def random(self):
        self.calls += 1
        return self.values.pop(0)


class BombThreatMemoryTests(PublicBeliefTests):
    def bomb_state(self):
        a = TileState('t1', 0, 0, 0, TileEffectType.BOMB, {'remaining': 3})
        z = TileState('t2', 0, 2, 0, TileEffectType.BOMB, {'remaining': 4})
        return GameState(tiles={0: {'0_0': a, '2_0': z}}, bomb_tiles={'0_0_0': 3, '0_2_0': 4})

    def test_default_off_and_no_extra_draw(self):
        from app.core.bot_simulator import V24_DEFAULT
        self.assertNotIn('bomb_threat_memory', V24_DEFAULT)
        b, p = self.bot()
        st = self.bomb_state(); b._precompute_blocking_map(st)
        st._bomb_noticed = frozenset({'0_0_0'})
        mem = _SeqRng([.0]); st._bomb_mem_rng = mem
        b._v21_p_aware = lambda g, prof, imm: 0.0
        b._rng = _SeqRng([.5])
        b._v21_draw_awareness(st, p)
        self.assertFalse(b._v21_aware['bomb'])
        self.assertEqual((b._rng.calls, mem.calls), (1, 0))

    def test_notice_then_retain_then_forget_uses_memory_rng_only(self):
        b, p = self.bot(['bomb_threat_memory'])  # theta 1.2 -> retention .85
        st = self.bomb_state(); b._precompute_blocking_map(st)
        b._v21_p_aware = lambda g, prof, imm: 0.5
        mem = _SeqRng([.8, .86]); st._bomb_mem_rng = mem
        b._rng = _SeqRng([.1])            # fresh notice
        b._v21_draw_awareness(st, p)
        self.assertTrue(b._v21_aware['bomb'])
        self.assertEqual(st._bomb_noticed, frozenset({'0_0_0', '0_2_0'}))
        b._rng = _SeqRng([.9])            # fresh miss; retention .8 < .85 from memory RNG
        b._v21_draw_awareness(st, p)
        self.assertTrue(b._v21_aware['bomb'])
        self.assertEqual(b._rng.calls, 1)
        b._rng = _SeqRng([.9])            # retention .86 fails -> forgotten (never guaranteed)
        b._v21_draw_awareness(st, p)
        self.assertFalse(b._v21_aware['bomb'])
        self.assertEqual(st._bomb_noticed, frozenset())
        b._rng = _SeqRng([.9])            # nothing remembered -> no retention draw at all
        b._v21_draw_awareness(st, p)
        self.assertFalse(b._v21_aware['bomb'])
        self.assertEqual((b._rng.calls, mem.calls), (1, 2))

    def test_on_preserves_main_rng_flow(self):
        import random as _r
        states = []
        for extra in ([], ['bomb_threat_memory']):
            b, p = self.bot(extra)
            st = self.bomb_state(); b._precompute_blocking_map(st)
            st._bomb_noticed = frozenset({'0_0_0'})
            b._v21_p_aware = lambda g, prof, imm: 0.0   # fresh draws always miss -> retention path taken when ON
            b._rng.seed(7)
            for _ in range(5):
                b._v21_draw_awareness(st, p)
            states.append(b._rng.getstate())
        self.assertEqual(states[0], states[1])

    def test_game_start_memory_rng_does_not_consume_main(self):
        b, p = self.bot(['bomb_threat_memory'])
        st = self.bomb_state(); b._precompute_blocking_map(st)
        b._rng.seed(11); before = b._rng.getstate()
        b._v21_p_aware = lambda g, prof, imm: 0.0
        st._bomb_noticed = frozenset({'0_0_0'}); st._bomb_mem_rng = None
        b._v21_draw_awareness(st, p)          # lazily derived memory RNG
        b2, _ = self.bot(); b2._rng.seed(11); b2._rng.random()
        self.assertIsNotNone(st._bomb_mem_rng)
        self.assertEqual(b._rng.getstate(), b2._rng.getstate())  # only the fresh-notice draw consumed

    def test_removed_bomb_leaves_memory_and_copy_independent(self):
        b, p = self.bot(['bomb_threat_memory'])
        st = self.bomb_state(); b._precompute_blocking_map(st)
        st._bomb_noticed = frozenset({'0_0_0'})
        st.tiles[0]['0_0'].picked = True
        mem = _SeqRng([.0]); st._bomb_mem_rng = mem
        b._v21_p_aware = lambda g, prof, imm: 0.0
        b._rng = _SeqRng([.9])
        b._v21_draw_awareness(st, p)
        self.assertFalse(b._v21_aware['bomb'])
        self.assertEqual((b._rng.calls, mem.calls), (1, 0))
        import random as _r
        st._bomb_noticed = frozenset({'0_2_0'})
        st._bomb_mem_rng = _r.Random(5)
        copied = b._v2_copy_state(st)
        copied._bomb_noticed = frozenset()
        copied._bomb_mem_rng.random()
        self.assertEqual(st._bomb_noticed, frozenset({'0_2_0'}))
        self.assertEqual(st._bomb_mem_rng.random(), _r.Random(5).random())


class ContainerDigCapacityTests(PublicBeliefTests):
    def stack_state(self, dock_n=0):
        top = TileState('key', 0, 0, 0, is_stack_tile=True, stack_index=2)
        mid = TileState('t8', 0, 0, 0, is_stack_tile=True, stack_index=1)
        low = TileState('t9', 0, 0, 0, is_stack_tile=True, stack_index=0)
        other = TileState('t5', 0, 3, 0)
        st = GameState(tiles={0: {'0_0': top, '3_0': other}}, stacked_tiles={'0_0_0_1': mid, '0_0_0_0': low},
                       craft_boxes={'0_0_0': ['0_0_0_0', '0_0_0_1', '0_0_0_2']},
                       dock=[DockSlot(index=i) for i in range(7)],
                       dock_tiles=[TileState(f'd{i}', 0, 9, i) for i in range(dock_n)])
        return st, top, other

    def score_bonus(self, b, st, tile, dock_n):
        return b._v24_behaviour_bonus(Move(0, tile.position_key, tile.tile_type, tile_state=tile), st, dock_n, dock_n)

    def test_default_off(self):
        from app.core.bot_simulator import V24_DEFAULT
        self.assertNotIn('container_dig_capacity', V24_DEFAULT)
        b, _ = self.bot(['stack_early'])
        st, top, other = self.stack_state()
        st._dig_box = '0_0_0'
        self.assertEqual(self.score_bonus(b, st, other, 0), 0.0)

    def test_public_remaining_and_capacity_sign(self):
        b, _ = self.bot(['container_dig_capacity'])  # theta 1.2 -> s=1, w=8
        st, top, other = self.stack_state()
        self.assertEqual(b._cdc_container(st, top), ('0_0_0', 2))
        self.assertEqual(self.score_bonus(b, st, top, 0), 8.0)      # free 7: room
        st5, top5, _ = self.stack_state(5)
        self.assertEqual(self.score_bonus(b, st5, top5, 5), -8.0)   # free 2: 2-1 < min(2,2)
        top.tile_type = 'secret_changed'                             # hidden/own type never changes the count
        self.assertEqual(b._cdc_container(st, top), ('0_0_0', 2))

    def test_dig_continue_and_new_single_suppressed(self):
        b, _ = self.bot(['container_dig_capacity'])
        st, top, other = self.stack_state()
        st._dig_box = '0_0_0'
        self.assertEqual(self.score_bonus(b, st, top, 0), 16.0)     # room + continue
        self.assertEqual(self.score_bonus(b, st, other, 0), -8.0)   # new single mid-dig
        st.dock_tiles = [TileState('t5', 0, 9, 0)]
        self.assertEqual(self.score_bonus(b, st, other, 1), 0.0)    # type already in dock: not a new single
        st.dock_tiles = []
        for k in ('0_0_0_0', '0_0_0_1'):
            st.stacked_tiles[k].picked = True
        top.picked = True
        self.assertEqual(self.score_bonus(b, st, other, 0), 0.0)    # exhausted dig ends

    def test_scoring_does_not_touch_rng_and_copy_independent(self):
        b, _ = self.bot(['container_dig_capacity'])
        st, top, other = self.stack_state(); st._dig_box = '0_0_0'
        b._rng.seed(3); before = b._rng.getstate()
        self.score_bonus(b, st, other, 0); self.score_bonus(b, st, top, 0)
        self.assertEqual(before, b._rng.getstate())
        copied = b._v2_copy_state(st); copied._dig_box = None
        self.assertEqual(st._dig_box, '0_0_0')


class DigBombYieldTests(ContainerDigCapacityTests):
    def with_bomb(self, st, rem):
        bomb = TileState('t7', 0, 5, 0, TileEffectType.BOMB, {'remaining': rem})
        st.tiles[0]['5_0'] = bomb; st.bomb_tiles = {'0_5_0': rem}
        return bomb

    def test_yield_off_keeps_dig_terms(self):
        b, _ = self.bot(['container_dig_capacity'])
        st, top, other = self.stack_state(); self.with_bomb(st, 1)
        self.assertEqual(self.score_bonus(b, st, top, 0), 8.0)      # G alone ignores bomb deadline

    def test_near_bomb_removes_dig_priority_and_never_suppresses_bomb(self):
        b, _ = self.bot(['container_dig_capacity', 'dig_bomb_yield'])
        st, top, other = self.stack_state(); bomb = self.with_bomb(st, 3)  # 3 <= min(2,2)+1
        st._dig_box = '0_0_0'
        self.assertEqual(self.score_bonus(b, st, top, 0), 0.0)      # no start/continue priority
        self.assertEqual(self.score_bonus(b, st, other, 0), 0.0)    # no new-single suppression either
        self.assertEqual(self.score_bonus(b, st, bomb, 0), 0.0)     # bomb tile never suppressed
        st5, top5, _ = self.stack_state(5); self.with_bomb(st5, 3)
        self.assertEqual(self.score_bonus(b, st5, top5, 5), -8.0)   # dock-room penalty unchanged

    def test_far_bomb_same_as_dig_and_rng_untouched(self):
        b, _ = self.bot(['container_dig_capacity', 'dig_bomb_yield'])
        st, top, other = self.stack_state(); bomb = self.with_bomb(st, 9)
        st._dig_box = '0_0_0'
        b._rng.seed(4); before = b._rng.getstate()
        self.assertEqual(self.score_bonus(b, st, top, 0), 16.0)
        self.assertEqual(self.score_bonus(b, st, other, 0), -8.0)
        self.assertEqual(self.score_bonus(b, st, bomb, 0), 0.0)     # bomb tile exempt from suppression
        self.assertEqual(before, b._rng.getstate())


class DigReviewFixTests(ContainerDigCapacityTests):
    def test_locked_slots_excluded_from_dig_room(self):
        b, _ = self.bot(['container_dig_capacity'])   # no dock_rel / public_gimmick_planning
        st, top, other = self.stack_state(3)
        self.assertEqual(self.score_bonus(b, st, top, 3), 8.0)       # 7 open slots: free 4 -> room
        for i in (4, 5, 6):
            st.dock[i].is_locked = True                               # 4 open slots: free 1 -> no room
        self.assertEqual(self.score_bonus(b, st, top, 3), -8.0)

    def test_rollout_step_updates_dig_state(self):
        b, _ = self.bot(['container_dig_capacity'])
        st, top, other = self.stack_state(); b._precompute_blocking_map(st); st._dig_box = None
        moves = {m.tile_state.full_key: m for m in b._get_available_moves(st)}
        self.assertTrue(b._v2_step(st, moves[top.full_key]))
        self.assertEqual(st._dig_box, '0_0_0')
        b2, _ = self.bot()                                            # option OFF: no dig state written
        st2, top2, _ = self.stack_state(); b2._precompute_blocking_map(st2); st2._dig_box = None
        moves2 = {m.tile_state.full_key: m for m in b2._get_available_moves(st2)}
        b2._v2_step(st2, moves2[top2.full_key])
        self.assertIsNone(st2._dig_box)


class PlanningAndCraftBeliefTests(PublicBeliefTests):
    def test_plan_budget_default_and_skill_planning(self):
        from app.core.mc_difficulty import make_skill_profile
        b_off, _ = self.bot()
        b_on, _ = self.bot(['skill_planning'])
        for theta, off, on in ((.55, (0, 10), (1, 6)), (.65, (0, 10), (1, 6)), (.85, (0, 10), (1, 8)),
                               (1.0, (0, 10), (1, 10)), (1.2, (2, 10), (2, 10))):
            p = make_skill_profile(theta, 'v2.4')
            self.assertEqual(b_off._plan_budget(p), off, theta)
            self.assertEqual(b_on._plan_budget(p), on, theta)
        self.assertEqual(b_on._plan_budget(make_skill_profile(0.0, 'v2.4')), (0, 10))   # depth 0: no planning

    def _craft_state(self, b, L=292):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import bot_v24_eval as ev
        P, _ = ev.v21.prep()
        lay = ev.base.level_layouts(P[L], 1)[0]
        st = b._create_initial_state(lay, int(lay['max_moves'])); b._precompute_blocking_map(st)
        return st

    def test_craft_belief_off_keeps_refusal(self):
        b, _ = self.bot(['hidden_common_samples'])
        st = self._craft_state(b)
        b._rng.seed(1)
        self.assertFalse(b._v24_determinize(b._v2_copy_state(st)))

    def test_craft_belief_never_reads_hidden_types(self):
        b, _ = self.bot(['hidden_common_samples', 'public_craft_belief'])
        outs = []
        for variant in range(2):
            st = self._craft_state(b)
            board = {id(t) for layer in st.tiles.values() for t in layer.values()}
            hidden = [t for k, t in sorted(st.stacked_tiles.items()) if t.is_craft_tile and not t.is_crafted and id(t) not in board]
            self.assertTrue(hidden)
            if variant:   # change the TRUE hidden contents (rotate types); public view unchanged
                types = [t.tile_type for t in hidden]
                for t, tt in zip(hidden, types[1:] + types[:1]):
                    t.tile_type = tt
            s = b._v2_copy_state(st)
            b._rng.seed(9)
            self.assertTrue(b._v24_determinize(s))
            outs.append([t.tile_type for k, t in sorted(s.stacked_tiles.items()) if t.is_craft_tile])
        self.assertEqual(outs[0], outs[1])
