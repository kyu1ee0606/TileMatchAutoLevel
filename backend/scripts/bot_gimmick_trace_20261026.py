"""Read-only diagnostics of frozen cap .65 model, 3 maps x 3 skills x 4 seeds."""
import sys,json,dataclasses,time,subprocess,re,shutil,os
from pathlib import Path
from collections import Counter
B=Path(__file__).resolve().parents[1];sys.path[:0]=[str(B),str(B/'scripts')]
import bot_v24_eval as ev
from app.core.bot_simulator import BotSimulator,TileEffectType,V24_DEFAULT,V21_AWARENESS_DEFAULTS
from app.core.mc_difficulty import make_skill_profile
OUT=B/'data/pv_sandbox/af_calibration/gimmick_trace_20261026'
FALLBACK_TEST=os.environ.get('DIAG_PUBLIC_FALLBACK')=='1'
if FALLBACK_TEST:OUT=OUT.with_name(OUT.name+'_public_fallback')
P,A=ev.v21.prep();EX=ev._expo();OUT.mkdir(parents=True,exist_ok=True)

class Traced(BotSimulator):
    def __init__(self):
        super().__init__();self.trace=[];self.search_calls=0;self.fallbacks=Counter()
    def _v24_determinize(self,state):
        result=super()._v24_determinize(state)
        if result is False:
            reason='craft'if any(t.is_craft_tile and not t.picked for t in state.stacked_tiles.values())else'locked'if any(s.is_locked for s in state.dock)else'inventory'
            self.fallbacks[reason]+=1
        return result
    def _v2_search_select(self,moves,state,profile):
        self.search_calls+=1;before=sum(self.fallbacks.values())
        result=super()._v2_search_select(moves,state,profile)
        if FALLBACK_TEST and sum(self.fallbacks.values())>before:
            safe=sorted([m for m in moves if m.score>-100]or moves,key=lambda m:-m.score)
            matches=[m for m in safe if m.will_match]
            if matches:return matches[0]
            candidates=self._get_pruned_candidates(safe,state)
            depth=min(self._get_adaptive_depth(state),profile.lookahead_depth)
            return max(candidates,key=lambda m:self._estimate_future_score(state,m,depth))if candidates else safe[0]
        return result
    def _select_move_with_profile(self,moves,state,profile):
        grass=[]
        for li,layer in state.tiles.items():
            for t in layer.values():
                if t.picked or t.effect_type!=TileEffectType.GRASS or t.effect_data.get('remaining',0)<=0:continue
                ns=[layer.get(f'{x}_{y}')for x,y in[(t.x_idx-1,t.y_idx),(t.x_idx+1,t.y_idx),(t.x_idx,t.y_idx-1),(t.x_idx,t.y_idx+1)]]
                grass.append(dict(key=t.full_key,remaining=t.effect_data['remaining'],blocked=self._is_blocked_by_upper(state,t),neighbors=[n.full_key for n in ns if n and not n.picked]))
        before=self.search_calls;fb=sum(self.fallbacks.values());aware=dict(getattr(self,'_v21_aware',{}))
        selected=super()._select_move_with_profile(moves,state,profile)
        self.trace.append(dict(turn=state.moves_used,dock=[t.tile_type for t in state.dock_tiles],aware=aware,grass=grass,bombs=dict(state.bomb_tiles),
                               chosen=None if selected is None else dict(key=selected.tile_state.full_key,type=selected.tile_type,score=selected.score,match=selected.will_match,linked=selected.linked_tiles),
                               search=self.search_calls-before,fallbacks=sum(self.fallbacks.values())-fb,
                               candidates=[dict(key=m.tile_state.full_key,type=m.tile_type,score=m.score,match=m.will_match)for m in sorted(moves,key=lambda m:-m.score)[:6]]))
        return selected

def main():
    for L in[152,448,284]:
        for theta in([1.2]if FALLBACK_TEST else[.65,.85,1.2]):
            for seed in range(13000000,13000004):
                dest=OUT/f'L{L}_theta{theta}_seed{seed}.json'
                if dest.exists():continue
                free=float(re.search(r'free = ([0-9.]+)M',subprocess.check_output(['sysctl','vm.swapusage'],text=True))[1])
                if free<500 or shutil.disk_usage(B).free<10*1024**3:print('STOP',free,flush=True);return
                prof=make_skill_profile(theta,'v2.4');cfg=dict(prof.gimmick_awareness);cfg.update(ev.v21.FIXED)
                cfg.update(alpha=dict(V21_AWARENESS_DEFAULTS['alpha']),gamma=dict(V21_AWARENESS_DEFAULTS['gamma']),exposure=EX[L],parity=None,
                           auto_collect=int(float(P[L]['row'].get('autoCollectCount')or 0)),v24_expo=ev._gc_expo(P)[L],
                           v24=list(V24_DEFAULT)+['grass_skill_attention','hidden_common_samples'],grass_attention_cap=.65)
                prof=dataclasses.replace(prof,gimmick_awareness=cfg);b=Traced();b.set_rule_parity(prof)
                layout=ev.base.level_layouts(P[L],1)[0];st=b._create_initial_state(layout,int(layout['max_moves']));b._precompute_blocking_map(st);b._rng.seed(seed)
                started=time.time();end=b._play_game(st,prof)
                row=dict(L=L,theta=theta,seed=seed,win=end.cleared,reason=None if end.cleared else ev.base.fail_reason(b,end),turns=end.moves_used,
                         search_calls=b.search_calls,fallbacks=dict(b.fallbacks),trace=b.trace,seconds=time.time()-started)
                dest.write_text(json.dumps(row,indent=2));print(L,theta,seed,row['win'],row['reason'],row['turns'],row['search_calls'],row['fallbacks'],flush=True)
    print('DONE',flush=True)
if __name__=='__main__':main()
