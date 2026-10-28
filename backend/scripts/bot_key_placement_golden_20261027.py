"""Key-tile placement parity: game client (golden dll, run only) vs pv/cs_shuffle vs BotSimulator internal t0 pass.

Cases (game repo HEAD StreamingAssets shards, read-only via git show):
  A. every map that still has t0 slots (board or container inner) x unlockTile {1, 2} x seeds {row seed or 1, 12345, 625901}
     (the game assigns keys only to t0 slots: DB_Level.ShuffleEmptyTiles -> DistributeTiles(specifiedCount=xUnlockTile))
  B. every shipped key map (unlockTile > 0) with its own row (keys explicit, no t0 -> client must be a no-op)
Golden: tools/pv_golden/bin/Debug/net8.0/PvGolden.dll `case <input>` (no build). Its source sha must equal the
current game DB_Level.cs / zWellRandom.cs (checked at start).
Compared per t0 slot (layer, pos, inner): type id (16 = key). Also key slot set and lock count (keys // 3).
Writes only inside OUT.  Usage: python bot_key_placement_golden_20261027.py [--bot-only]
"""
import sys, json, hashlib, subprocess, copy
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_af_L32_500 as SH
from app.core.pv.cs_shuffle import shuffle_empty_tiles, PvError
from app.core.bot_simulator import BotSimulator

REPO = B_.parent
DLL = REPO / 'tools/pv_golden/bin/Debug/net8.0/PvGolden.dll'
META = REPO / 'tools/pv_golden/Generated/extract_meta.json'
GAME = Path('/Users/casualdev/sp_meowsgarden')
OUT = B_ / 'data/pv_sandbox/af_calibration/key_placement_golden_20261027'
SEEDS = [12345, 625901]


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(); return p


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_head():
    tab = SH._git_key('HEAD', 'levels'); keys = tab['__keys']; rows = {}
    for v in tab['__vals']:
        o = {keys[i]: v[i] for i in range(min(len(keys), len(v)))}; rows[str(o.get('id'))] = o
    maps = {}
    for i in range(16):
        maps.update(SH._git_key('HEAD', f'levelmap_level_{i}'))
    return rows, maps


def t0_slots(m):
    n = 0
    for lk, lv in m.items():
        if not (lk.startswith('layer_') and isinstance(lv, dict) and isinstance(lv.get('tiles'), dict)): continue
        for td in lv['tiles'].values():
            t = str(td[0])
            if t == 't0': n += 1
            elif t.startswith(('stack', 'craft')) and len(td) > 2 and isinstance(td[2], list) and td[2]:
                cnt = int(td[2][0] or 0); ids = str(td[2][1]).split('_') if len(td[2]) > 1 and td[2][1] else []
                n += cnt if len(ids) != cnt else sum(x == 't0' for x in ids)
    return n


def tid(s):
    s = str(s)
    if s in ('key', 't16'): return 16
    return int(s[1:]) if s.startswith('t') and s[1:].isdigit() else -1


def run_dll(case_path):
    r = subprocess.run(['dotnet', str(DLL), 'case', str(case_path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0: raise RuntimeError(r.stderr[-500:])
    return json.loads(r.stdout)


def cs_types(m, row, run):
    try:
        res = shuffle_empty_tiles(m, rand_seed=run['randSeed'], use_tile_count=row.get('useTileCount'),
                                  unlock_tile=run['unlockTile'], shuffle_tile=row.get('shuffleTile'),
                                  type_imbalance=row.get('typeImbalance'), strict=False)
    except PvError as e:
        return None, type(e).__name__
    return {(s.layer_name, s.pos, -1 if s.inner_index is None else s.inner_index): tid(a)
            for s, a in zip(res.slots, res.assigned)}, None


def bot_types(m, row, run, slots):
    """BotSimulator internal path on the RAW map (t0 kept): read the type the bot put on every golden t0 slot."""
    lj = copy.deepcopy(m)
    nums = [int(k[6:]) for k in lj if k.startswith('layer_') and k[6:].isdigit()]
    lj['layer'] = max(int(lj.get('layer') or 0), max(nums, default=-1) + 1)
    lj['randSeed'] = run['randSeed']; lj['useTileCount'] = int(row.get('useTileCount') or 0)
    lj['unlockTile'] = run['unlockTile']; lj['xShuffleTile'] = int(float(row.get('shuffleTile') or 0))
    lj['xTypeImbalance'] = int(float(row.get('typeImbalance') or 0))
    b = BotSimulator()
    try:
        st = b._create_initial_state(lj, 300)
    except Exception as e:  # noqa: BLE001
        return None, None, type(e).__name__
    by = {}
    seen = set()
    for t in [x for lay in st.tiles.values() for x in lay.values()] + list(st.stacked_tiles.values()):
        if id(t) in seen: continue
        seen.add(id(t))
        if t.stack_index >= 0 and (t.is_stack_tile or t.is_craft_tile):
            k = t.original_full_key or t.full_key
            l, x, y, i = k.split('_')
            by[(f'layer_{l}', f'{x}_{y}', int(i))] = tid(t.tile_type)
        else:
            by[(f'layer_{t.layer_idx}', t.position_key, -1)] = tid(t.tile_type)
    locks = sum(1 for s in st.dock if s.is_locked)
    return {k: by.get(k, -99) for k in slots}, locks, None


def main():
    bot_only = '--bot-only' in sys.argv
    meta = json.loads(META.read_text())
    src_ok = (sha(GAME / meta['source']) == meta['sourceSha256'] and sha(GAME / meta['zWellRandom']) == meta['zWellRandomSha256'])
    if not src_ok: print('GOLDEN SOURCE MISMATCH -> abort'); sys.exit(2)
    OUT.mkdir(parents=True, exist_ok=True); (OUT / 'cases').mkdir(exist_ok=True)
    rows, maps = load_head()
    cases = []
    for lid in sorted(maps, key=lambda s: int(s.split('_')[1])):
        row = rows.get(lid)
        if row is None: continue
        m = maps[lid]; u = int(float(row.get('unlockTile') or 0)); n = t0_slots(m)
        seed0 = int(float(row.get('randSeed') or 0)) or 1
        if n:
            runs = [{'randSeed': s, 'unlockTile': k} for k in (1, 2) for s in [seed0] + SEEDS]
            cases.append(('A', lid, row, m, runs))
        elif u > 0:
            cases.append(('B', lid, row, m, [{'randSeed': seed0, 'unlockTile': u}]))
    report = []
    for kind, lid, row, m, runs in cases:
        cp = _p('cases') if False else OUT / 'cases' / f'{lid}.json'
        if not bot_only or not (OUT / 'cases' / f'{lid}.golden.json').exists():
            r2 = {k: v for k, v in row.items()}; r2['map'] = m
            cp.write_text(json.dumps({'caseId': lid, 'kind': 'key_parity', 'note': 'key placement parity 20261027', 'levelId': lid,
                                      'dumpRng': False, 'row': r2, 'runs': runs}))
            g = run_dll(cp)
            (OUT / 'cases' / f'{lid}.golden.json').write_text(json.dumps(g))
        g = json.loads((OUT / 'cases' / f'{lid}.golden.json').read_text())
        for run, res in zip(runs, g['results']):
            rec = dict(kind=kind, level=lid, run=run, golden_exc=(res.get('exception') or {}).get('type'))
            if res.get('types') is None:
                rec.update(status='golden_no_types'); report.append(rec); continue
            gm = {(p[0], p[1], p[2]): t for p, t in zip(res['positions'], res['types'])}
            gkeys = sorted(k for k, v in gm.items() if v == 16)
            tot16 = int((res['selfCheck'].get('totalPerType') or {}).get('16', 0))
            rec.update(t0=len(gm), golden_keys=len(gkeys), golden_total_keys=tot16, golden_locks=tot16 // 3)
            c, cerr = cs_types(m, row, run)
            if c is None: rec.update(cs='exc:' + cerr)
            else:
                rec.update(cs_type_mismatch=sum(1 for k in gm if c.get(k) != gm[k]),
                           cs_key_mismatch=sum(1 for k in gm if (c.get(k) == 16) != (gm[k] == 16)))
            bt, locks, berr = bot_types(m, row, run, list(gm))
            if bt is None: rec.update(bot='exc:' + berr)
            else:
                rec.update(bot_type_mismatch=sum(1 for k in gm if bt[k] != gm[k]),
                           bot_key_mismatch=sum(1 for k in gm if (bt[k] == 16) != (gm[k] == 16)),
                           bot_keys=sum(1 for k in gm if bt[k] == 16), bot_locks=locks)
            report.append(rec)
    with open(_p('report.jsonl.tmp'), 'w') as f:
        for r in report: f.write(json.dumps(r) + '\n')
    _p('report.jsonl.tmp').replace(_p('report.jsonl'))
    def agg(sel):
        rs = [r for r in report if sel(r) and 't0' in r]
        f = lambda k: sum(1 for r in rs if r.get(k, 0) != 0 or str(r.get(k.split('_')[0], '')).startswith('exc'))
        return dict(runs=len(rs), cs_type_mm_runs=f('cs_type_mismatch'), cs_key_mm_runs=f('cs_key_mismatch'),
                    bot_type_mm_runs=f('bot_type_mismatch'), bot_key_mm_runs=f('bot_key_mismatch'),
                    bot_lock_mm_runs=sum(1 for r in rs if r.get('bot_locks') is not None and r['bot_locks'] != r['golden_locks']))
    summ = dict(golden_dll_sha=sha(DLL), game_db_level_sha=meta['sourceSha256'], cases=len(cases),
                A=agg(lambda r: r['kind'] == 'A'), B=agg(lambda r: r['kind'] == 'B'),
                golden_no_types=sum(1 for r in report if r.get('status') == 'golden_no_types'))
    _p('summary.json').write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == '__main__':
    main()
