import dataclasses
import unittest

from app.core.bot_simulator import BotSimulator, DockSlot, GameState, Move, TileEffectType, TileState, V24_DEFAULT
from app.core.mc_difficulty import make_skill_profile
from app.core import bot_play_summary as S


def pick(occ, cap=7, n=0, container=False, bomb=(), grass=0, locked=0):
    return dict(occ=occ, cap=cap, n=n, container=container, bomb_defuse=list(bomb), grass_total=grass, locked=locked)


def state(dock_types=(), locked=0, grass=None, bombs=None, boxes=None):
    tiles = {0: {}}
    if grass is not None:
        tiles[0]['0_0'] = TileState('t1', 0, 0, 0, TileEffectType.GRASS, {'remaining': grass})
    if bombs:
        for i, (k, v) in enumerate(bombs.items()):
            tiles[0][f'{5 + i}_0'] = TileState('t2', 0, 5 + i, 0, TileEffectType.BOMB, {'remaining': v})
    return GameState(tiles=tiles, dock=[DockSlot(index=i, is_locked=i >= 7 - locked) for i in range(7)],
                     dock_tiles=[TileState(t, 0, 9, i) for i, t in enumerate(dock_types)],
                     bomb_tiles=dict(bombs or {}), craft_boxes=dict(boxes or {}))


class SummaryDefinitionTests(unittest.TestCase):
    def test_hand_computed_normal_failure(self):
        # 6-slot dock (1 locked), grass 2 layers, no bombs/containers.
        start = state(locked=1, grass=2)
        log = [pick(0, 6, n=0, grass=2, locked=1), pick(1, 6, n=1, grass=2, locked=1), pick(2, 6, n=2, grass=1, locked=1),
               pick(0, 6, n=0, grass=1, locked=1), pick(4, 6, n=0, grass=1, locked=1), pick(5, 6, n=0, grass=1, locked=1)]
        end = state(dock_types=('a', 'a', 'b', 'c', 'c', 'd'), locked=1, grass=1)
        s = S.summarize(log, start, end, 'Normal', 138, 'bot_x')
        self.assertEqual(s['picks'], 6)
        self.assertEqual(s['pick_new'], 4)            # n=0 at picks 1,4,5,6
        self.assertEqual(s['pick_match'], 1)          # n=2 at pick 3
        self.assertEqual(s['min_free'], 1)            # 6-5
        self.assertEqual(s['danger_picks'], 2)        # free 2 and 1 at picks 5,6 (free 4,5,4,6 before)
        self.assertEqual(s['danger_tail'], 2)
        self.assertEqual(s['end_pairs'], 2)           # a,a and c,c
        self.assertEqual(s['grass_first'], 2)         # grass 2 -> 1 observed before pick 3 => caused by pick 2
        self.assertEqual(s['grass_left'], 1)
        self.assertEqual(s['key_unlock'], 0)          # lock exists, never unlocked in segment
        self.assertEqual(s['bomb_left_min'], -1)
        self.assertEqual(s['cont_first'], -1)
        self.assertEqual((s['seg_end'], s['seg_boost'], s['sv']), ('Normal', 0, 1))
        self.assertEqual(S.check_ranges(s), [])

    def test_bomb_rules_and_unlock_on_last_pick(self):
        start = state(locked=1, bombs={'0_5_0': 4, '0_6_0': 5}, boxes={'0_1_1': ['k']})
        log = [pick(0, 6, container=False, locked=1), pick(1, 6, bomb=[3], container=True, locked=1)]
        end = state(locked=0, bombs={'0_6_0': 3})
        s = S.summarize(log, start, end, 'clear', 1, 'r')
        self.assertEqual(s['bomb_left_min'], 3)       # defused with 3 left
        self.assertEqual(s['key_unlock'], 2)          # unlock visible only in end state -> pick 2
        self.assertEqual(s['cont_first'], 2)
        s2 = S.summarize(log[:1], start, state(locked=1, bombs={'0_5_0': 0}), 'Bomb', 1, 'r')
        self.assertEqual(s2['bomb_left_min'], 0)      # explosion = 0
        s3 = S.summarize(log[:1], start, state(locked=1, bombs={'0_5_0': 2}), 'clear', 1, 'r')
        self.assertEqual(s3['bomb_left_min'], -2)     # bombs present, no defuse/explosion in segment

    def test_zero_picks_and_seg_end_mapping(self):
        s = S.summarize([], state(), state(), 'NoMoves', 5, 'r')
        self.assertEqual((s['picks'], s['min_free'], s['danger_tail']), (0, -1, 0))
        self.assertEqual(s['seg_end'], 'bot_no_moves')
        for k, v in S.SEG_END_MAP.items():
            self.assertTrue(v in S.GAME_SEG_END or v.startswith('bot_'), (k, v))

    def test_link_tap_is_one_pick_and_classified_by_tapped_tile(self):
        b = S.SummaryBot()
        a = TileState('t1', 0, 0, 0, TileEffectType.LINK_EAST)
        z = TileState('t3', 0, 1, 0, TileEffectType.LINK_WEST)
        st = GameState(tiles={0: {'0_0': a, '1_0': z}}, dock=[DockSlot(index=i) for i in range(7)],
                       dock_tiles=[TileState('t1', 0, 9, 0), TileState('t1', 0, 9, 1)])
        snap = b._snapshot(st, Move(0, '0_0', 't1', tile_state=a, linked_tiles=[(0, '1_0')]))
        self.assertEqual((snap['n'], snap['occ'], snap['cap']), (2, 2, 7))
        log = [snap]
        s = S.summarize(log, st, st, 'clear', 1, 'r')
        self.assertEqual((s['picks'], s['pick_match']), (1, 1))

    def test_linked_bomb_partner_counts_as_defuse(self):
        b = S.SummaryBot()
        a = TileState('t1', 0, 0, 0, TileEffectType.LINK_EAST)
        bomb = TileState('t3', 0, 1, 0, TileEffectType.BOMB, {'remaining': 2})
        st = GameState(tiles={0: {'0_0': a, '1_0': bomb}}, bomb_tiles={'0_1_0': 2}, dock=[DockSlot(index=i) for i in range(7)])
        snap = b._snapshot(st, Move(0, '0_0', 't1', tile_state=a, linked_tiles=[(0, '1_0')]))
        self.assertEqual(snap['bomb_defuse'], [2])


class SummaryParityTests(unittest.TestCase):
    """Real maps: SummaryBot must choose exactly the same tiles as the plain bot (no behaviour change)."""

    def _profile(self, theta):
        p = make_skill_profile(theta, 'v2.4')
        return dataclasses.replace(p, gimmick_awareness=dict(p.gimmick_awareness, v24=list(V24_DEFAULT)))

    def test_choice_sequence_parity_and_pick_count(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import bot_v24_eval as ev
        P, _ = ev.v21.prep()
        for L in (138, 293):
            layout = ev.base.level_layouts(P[L], 1)[0]
            for theta in (.65, 1.2):
                prof = self._profile(theta)
                keys = []
                for cls in (S.SummaryBot, BotSimulator):
                    class Rec(cls):
                        def _select_move_with_profile(self, moves, st, pr):
                            sel = super()._select_move_with_profile(moves, st, pr)
                            self.rec.append(None if sel is None else sel.tile_state.full_key)
                            return sel
                    b = Rec(); b.rec = []; b.set_rule_parity(prof)
                    st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                    b._rng.seed(77); end = b._play_game(b._fast_copy_state(st), prof)
                    keys.append((b.rec, end.moves_used, end.cleared))
                    if cls is S.SummaryBot:
                        self.assertEqual(len(b.pick_log), end.moves_used)
                self.assertEqual(keys[0], keys[1], (L, theta))


if __name__ == '__main__':
    unittest.main()


class SummaryConfirmedDefinitionTests(unittest.TestCase):
    """55 §9-7 confirmed definitions (2026-10-27)."""

    def test_bomb_beats_normal_when_simultaneous(self):
        b = BotSimulator()
        bomb = TileState('t2', 0, 5, 0, TileEffectType.BOMB, {'remaining': 0})
        end = GameState(tiles={0: {'5_0': bomb}}, bomb_tiles={'0_5_0': 0}, dock=[DockSlot(index=i) for i in range(7)],
                        dock_tiles=[TileState(f'd{i}', 0, 9, i) for i in range(7)])
        end.failed = True; end.max_dock_slots = 7
        self.assertEqual(S.seg_end_category(b, end), 'Bomb')
        bomb.picked = True
        self.assertEqual(S.seg_end_category(b, end), 'Normal')

    def test_auto_collected_bomb_counts(self):
        log = [dict(occ=0, cap=7, n=0, container=False, bomb_defuse=[], bomb_auto=[2], grass_total=0, locked=0)]
        start = state(bombs={'0_5_0': 3})
        s = S.summarize(log, start, state(), 'clear', 1, 'r')
        self.assertEqual(s['bomb_left_min'], 2)

    def test_key_tile_marks_lock_presence(self):
        st = state(); st.tiles[0]['3_3'] = TileState('key', 0, 3, 3)
        self.assertTrue(S.map_presence(st)['lock'])
        self.assertFalse(S.map_presence(state())['lock'])
