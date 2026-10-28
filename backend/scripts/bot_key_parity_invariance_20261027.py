"""Old-vs-new core invariance for the 2026-10-27 key parity fix (observation, small).

OLD = byte copy of bot_simulator.py at sha 4196e75a (passed as argv[1], loaded as a sibling module of app.core).
S. raw HEAD maps with t0 and unlockTile == 0 (bot internal t0 path): _create_initial_state tile types per slot,
   dock locks, all_tile_type_counts identical (no games).
G. measured maps (prep set L32-500): all key maps (unlockTile>0) + every 12th non-key map, theta .85 baseline profile
   (same as play_summary_check_20261027), 1 game each with OLD and NEW from the same seed: chosen tile sequence,
   end category, moves, dock locks identical.
Writes only inside OUT.
"""
import sys, json, hashlib, importlib.util, dataclasses
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_public_deadline_20261026 as prior
import bot_key_placement_golden_20261027 as KP
from app.core import bot_simulator as NEW
c = prior.c
OUT = B_ / 'data/pv_sandbox/af_calibration/key_parity_invariance_20261027'
SEED = 35000000


def load_old(path):
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest().startswith('4196e75a')
    spec = importlib.util.spec_from_file_location('app.core._bot_simulator_old_4196e75a', path)
    mod = importlib.util.module_from_spec(spec); mod.__package__ = 'app.core'
    sys.modules[spec.name] = mod; spec.loader.exec_module(mod); return mod


def snap(st):
    out = {}
    for t in [x for lay in st.tiles.values() for x in lay.values()] + list(st.stacked_tiles.values()):
        out[(t.original_full_key or t.full_key)] = t.tile_type
    return dict(types=sorted(out.items()), locks=[s.is_locked for s in st.dock], cap=st.max_dock_slots,
                counts=sorted(dict(st.all_tile_type_counts).items()))


def recorder(base):
    class R(base):
        def _play_game(self, state, profile):
            self._main = state; self.seq = []; return super()._play_game(state, profile)

        def _apply_move(self, state, move):
            if state is getattr(self, '_main', None) and move.tile_state is not None:
                self.seq.append(move.tile_state.original_full_key or move.tile_state.full_key)
            return super()._apply_move(state, move)
    return R


def profile(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(prior.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    OLD = load_old(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    # S: raw t0 maps, unlock 0
    rows, maps = KP.load_head(); s_res = []
    for lid in sorted(maps, key=lambda s: int(s.split('_')[1])):
        row = rows.get(lid)
        if row is None or int(float(row.get('unlockTile') or 0)) or not KP.t0_slots(maps[lid]): continue
        for seed in (int(float(row.get('randSeed') or 0)) or 1, 12345):
            lj = dict(maps[lid]); nums = [int(k[6:]) for k in lj if k.startswith('layer_') and k[6:].isdigit()]
            lj['layer'] = max(int(lj.get('layer') or 0), max(nums, default=-1) + 1)
            lj.update(randSeed=seed, useTileCount=int(row.get('useTileCount') or 0), unlockTile=0)
            a = snap(OLD.BotSimulator()._create_initial_state(json.loads(json.dumps(lj)), 300))
            b = snap(NEW.BotSimulator()._create_initial_state(json.loads(json.dumps(lj)), 300))
            s_res.append(dict(level=lid, seed=seed, same=a == b))
    # G: games
    key = [L for L in sorted(c.P) if int(c.P[L]['row'].get('unlockTile') or 0) > 0]
    non = [L for L in sorted(c.P) if L not in key][::12]
    g_res = []
    done = set()
    if (OUT / 'games.jsonl').exists():
        g_res = [json.loads(x) for x in (OUT / 'games.jsonl').read_text().splitlines()]; done = {r['level'] for r in g_res}
    for L in key + non:
        if L in done: continue
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]; p = profile(L, .85); r = {}
        for name, mod in (('old', OLD), ('new', NEW)):
            b = recorder(mod.BotSimulator)(); b.set_rule_parity(p)
            st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
            b._rng.seed(SEED + L); end = b._play_game(b._fast_copy_state(st), p)
            r[name] = dict(seq=b.seq, cat=c.ev.base.fail_reason(b, end), moves=end.moves_used,
                           locks=[s.is_locked for s in end.dock], init=snap(st))
        row = dict(level=L, key=L in key, same=r['old'] == r['new'], cat=r['new']['cat'], moves=r['new']['moves'])
        g_res.append(row)
        with (OUT / 'games.jsonl').open('a') as f: f.write(json.dumps(row) + '\n')
        print('GAME', L, row['key'], row['same'], row['cat'], flush=True)
    summ = dict(S_runs=len(s_res), S_diff=[r for r in s_res if not r['same']],
                G_key=len([r for r in g_res if r['key']]), G_non=len([r for r in g_res if not r['key']]),
                G_diff=[r['level'] for r in g_res if not r['same']], games_played=2 * len(g_res))
    (OUT / 'summary.json').write_text(json.dumps(summ, indent=1)); print(json.dumps(summ, indent=1))


if __name__ == '__main__':
    main()
