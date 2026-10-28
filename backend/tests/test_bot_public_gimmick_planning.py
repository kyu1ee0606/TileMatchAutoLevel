"""Public geometry choices; no hardcoded live-level outcomes."""
import dataclasses
import unittest
from unittest.mock import patch
from app.core.bot_simulator import BotSimulator, GameState, TileState, TileEffectType, Move, DockSlot, V24_DEFAULT
from app.core.mc_difficulty import make_skill_profile

class PublicPlanningTests(unittest.TestCase):
    def setup_bot(self):
        b=BotSimulator(); p=make_skill_profile(1.2,'v2.4')
        p=dataclasses.replace(p,gimmick_awareness=dict(p.gimmick_awareness,v24=list(V24_DEFAULT)+['public_gimmick_planning','hidden_common_samples','grass_skill_attention']))
        b.set_rule_parity(p); b._v21_aware={'grass':True}
        return b,p

    def fixture(self):
        grass=TileState('t1',0,1,1,TileEffectType.GRASS,{'remaining':2})
        left=TileState('t2',0,0,1); right=TileState('t3',0,2,1)
        cover=TileState('t4',1,1,1)
        st=GameState(tiles={0:{'1_1':grass,'0_1':left,'2_1':right},1:{'1_1':cover}})
        return st,grass,left,right,cover

    def move(self,t,linked=()):
        return Move(layer_idx=t.layer_idx,position=t.position_key,tile_type=t.tile_type,tile_state=t,linked_tiles=list(linked))

    def test_default_not_enabled(self):
        self.assertNotIn('public_gimmick_planning',V24_DEFAULT)

    def test_notice_required_for_cover_progress_and_isolation(self):
        b,p=self.setup_bot(); st,g,l,r,c=self.fixture()
        self.assertGreater(b._public_grass_plan(self.move(c),st,p),0)
        self.assertLess(b._public_grass_plan(self.move(l),st,p),-100)
        b._v21_aware={'grass':False}
        self.assertEqual(b._public_grass_plan(self.move(c),st,p),0)
        self.assertEqual(b._public_grass_plan(self.move(l),st,p),0)
        self.assertEqual(g.effect_data['remaining'],2)
        self.assertFalse(c.picked)

    def test_linked_mate_risk_even_when_main_not_adjacent(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        main=TileState('t5',0,0,0);st.tiles[0]['0_0']=main
        self.assertEqual(b._public_grass_plan(self.move(main),st,p),0)
        self.assertLess(b._public_grass_plan(self.move(main,[(0,'0_1')]),st,p),-100)

    def test_pair_removes_two_neighbors_as_one_action(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        third=TileState('t6',0,1,0);st.tiles[0]['1_0']=third
        self.assertEqual(b._public_grass_plan(self.move(l),st,p),0)
        self.assertLess(b._public_grass_plan(self.move(l,[(0,'2_1')]),st,p),-100)

    def test_stack_top_does_not_clear_cover(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        c.is_stack_tile=True;c.under_stacked_tile_key='inner'
        st.stacked_tiles['inner']=TileState('secret',1,1,1,is_stack_tile=True)
        self.assertEqual(b._public_grass_plan(self.move(c),st,p),0)
        st.stacked_tiles['inner'].tile_type='different_secret'
        self.assertEqual(b._public_grass_plan(self.move(c),st,p),0)

    def test_final_registered_stack_tile_can_clear_cover(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        c.is_stack_tile=True;c.stack_index=0
        st.stacked_tiles[c.full_key]=c
        st.craft_boxes['1_1_1']=[c.full_key]
        self.assertGreater(b._public_grass_plan(self.move(c),st,p),0)

    def test_craft_neighbor_uses_original_root_not_spawn_cell(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        del st.tiles[0]['0_1']
        l.original_full_key='0_0_1_0';l.x_idx=4;l.y_idx=4
        l.is_craft_tile=True;l.is_stack_tile=True;l.is_crafted=True
        st.tiles[0]['4_4']=l
        self.assertLess(b._public_grass_plan(self.move(l),st,p),-100)

    def test_stack_top_is_not_original_neighbor(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        l.is_stack_tile=True;l.stack_index=1
        bottom=TileState('hidden',0,0,1,is_stack_tile=True,stack_index=0)
        l.under_stacked_tile_key=bottom.full_key
        st.stacked_tiles[bottom.full_key]=bottom
        self.assertEqual(b._public_grass_plan(self.move(l),st,p),0)

    def test_locked_slot_pressure_matches_capacity(self):
        b,p=self.setup_bot();st=GameState(dock=[DockSlot(0),DockSlot(1,is_locked=True)])
        self.assertEqual(b._v24_dock_shift(st),1)
        st.dock[1].is_locked=False
        self.assertEqual(b._v24_dock_shift(st),0)

    def test_unsupported_belief_returns_to_regular_selector(self):
        b,p=self.setup_bot();st,g,l,r,c=self.fixture()
        moves=[self.move(l),self.move(r)]
        with patch.object(b,'_v2_rollout_value',return_value=None):
            self.assertIsNone(b._v2_search_select(moves,st,p))
        st.dock_tiles=[TileState('t9',0,i,9) for i in range(3)]
        with patch.object(b,'_rng') as rng, patch.object(b,'_v2_search_select',return_value=None), patch.object(b,'_estimate_future_score',side_effect=lambda st,m,d:100 if m is moves[1] else 0):
            rng.random.return_value=1
            self.assertIs(b._select_move_with_profile(moves,st,p),moves[1])

if __name__=='__main__':unittest.main()
