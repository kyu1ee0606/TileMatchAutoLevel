"""Freeze the PRE-FIX core (bot_simulator.py sha 4196e75a, byte copy given as argv[1]) initial-state outputs as a test golden.

Cases = every backend/tests/golden/pv_t0 input x run, two readings each:
  raw      : the input map as is (t0 kept -> bot internal t0 pass)
  resolved : the client-resolved map from the golden expected file (no t0)
For each: sha256 of the per-tile type strings by slot key (+ key/t16 counts), all_tile_type_counts, dock lock flags, max_dock_slots and a sha256 of
bot._rng.getstate() after _create_initial_state (RNG untouched check).
unlockTile = 0 cases must stay identical in the new core; unlockTile > 0 cases are the legacy-fallback reference.
Output: backend/tests/golden/key_parity/legacy_4196e75a.json (atomic).
"""
import sys, json, copy, hashlib, importlib.util, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_)]
GOLD = B_ / 'tests/golden/pv_t0'
OUT = B_ / 'tests/golden/key_parity/legacy_4196e75a.json'


def as_int(v):
    try: return int(float(v or 0))
    except (TypeError, ValueError): return 0


def level_json(row, run, the_map):
    r = dict(row); r.update(run)
    lj = copy.deepcopy(the_map)
    nums = [int(k[6:]) for k in lj if k.startswith('layer_') and k[6:].isdigit()]
    lj['layer'] = max(as_int(lj.get('layer')), max(nums, default=-1) + 1)
    for k in list(lj):
        if k.startswith('layer_') and isinstance(lj[k].get('tiles'), list): lj[k]['tiles'] = {}
    lj['randSeed'] = as_int(r.get('randSeed')); lj['useTileCount'] = as_int(r.get('useTileCount'))
    lj['unlockTile'] = as_int(r.get('unlockTile'))
    lj['xShuffleTile'] = as_int(r.get('shuffleTile')); lj['xTypeImbalance'] = as_int(r.get('typeImbalance'))
    return lj


def snapshot(sim_cls, lj):
    b = sim_cls(); b._rng.seed(12345)
    try:
        st = b._create_initial_state(copy.deepcopy(lj), 300)
    except Exception as e:  # noqa: BLE001
        return dict(error=type(e).__name__)
    tiles = {}
    for t in [x for lay in st.tiles.values() for x in lay.values()] + list(st.stacked_tiles.values()):
        tiles[t.original_full_key or t.full_key] = t.tile_type
    return dict(tiles_sha=hashlib.sha256(json.dumps(sorted(tiles.items())).encode()).hexdigest(), n_tiles=len(tiles),
                n_key=sum(1 for v in tiles.values() if v == 'key'), n_t16=sum(1 for v in tiles.values() if v == 't16'), counts=dict(sorted(st.all_tile_type_counts.items())),
                locks=[s.is_locked for s in st.dock], cap=st.max_dock_slots,
                rng=hashlib.sha256(repr(b._rng.getstate()).encode()).hexdigest())


def cases():
    for f in sorted((GOLD / 'inputs').glob('*.json')):
        inp = json.loads(f.read_text()); exp = json.loads((GOLD / 'expected' / f.name).read_text())
        runs = inp.get('runs') or [{}]
        for i, (run, res) in enumerate(zip(runs, exp['results'])):
            yield f'{f.stem}#{i}:raw', inp['row'], run, inp['row']['map']
            if res.get('resolvedMap'):
                yield f'{f.stem}#{i}:resolved', inp['row'], run, res['resolvedMap']


def main():
    path = sys.argv[1]
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest(); assert sha.startswith('4196e75a'), sha
    spec = importlib.util.spec_from_file_location('app.core._bot_simulator_legacy_4196e75a', path)
    mod = importlib.util.module_from_spec(spec); mod.__package__ = 'app.core'; sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
    out = dict(source_sha256=sha, rng_seed=12345, cases={})
    for cid, row, run, m in cases():
        lj = level_json(row, run, m)
        out['cases'][cid] = dict(unlock=lj['unlockTile'], legacy=snapshot(mod.BotSimulator, lj))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(out, sort_keys=True)); os.replace(tmp, OUT)
    n0 = sum(1 for v in out['cases'].values() if v['unlock'] == 0)
    print('cases', len(out['cases']), 'unlock0', n0, 'errors', sum(1 for v in out['cases'].values() if 'error' in v['legacy']))


if __name__ == '__main__':
    main()
