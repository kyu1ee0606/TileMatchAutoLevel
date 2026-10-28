"""Doc 59 input: which L32-500 maps were used by earlier measurements (scan of saved outputs). Writes OUT/used_scan.json.

Scanned: data/pv_sandbox/af_calibration/*, data/dda_seeds/*, data/pv_sandbox/dda_t0_all_20261020/*, data/pv_sandbox/pv_20261002_live3/*.
A folder's maps = level ids 32..500 found in its json/jsonl (fields L/level/lv/level_id/levelId/id, level_N keys, and
manifest list fields). Folder classes (fixed rule):
  population / catalog / data : > 200 maps (all-level scans, seed catalogs, version-wide calibrations) and the four named
    large non-targeted folders (bot_v22 version calibration 197, DDA readiness 176, DDA set build v2 199, server GET
    snapshot 106) -> NOT counted as use (counting them leaves 0 unused maps).
  targeted (development / validation / diagnosis) : everything else -> every map in it counts as USED.
"""
import json, sys
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]
D = B_ / 'data'
OUT = D / 'pv_sandbox/af_calibration/combo_prereg_20261027'
POP_OR_DATA = {'pv_sandbox/af_calibration/bot_v22', 'pv_sandbox/pv_20261002_live3/dda_readiness_20261019',
               'pv_sandbox/pv_20261002_live3/dda_sets_v2', 'dda_seeds/bulk_snapshot_20261020_1905_get'}
LIST_KEYS = ('maps', 'new', 'dev', 'val', 'H', 'kdev', 'knew', 'both', 'used', 'used_excluded', 'diagnostic', 'holdout', 'references')


def lv(v):
    if isinstance(v, int): return v if 32 <= v <= 500 else None
    if isinstance(v, str):
        s = v.replace('level_', '')
        if s.isdigit() and 32 <= int(s) <= 500: return int(s)
    return None


def take(o, acc, depth=0):
    if depth > 8: return
    if isinstance(o, dict):
        for k in ('L', 'level', 'lv', 'level_id', 'levelId', 'id'):
            x = lv(o.get(k))
            if x: acc.add(x)
        for k in LIST_KEYS:
            v = o.get(k)
            if isinstance(v, dict):
                for kk, vv in v.items():
                    x = lv(kk)
                    if x: acc.add(x)
                    if isinstance(vv, list): acc |= {y for y in map(lv, vv) if y}
            elif isinstance(v, list): acc |= {y for y in map(lv, v) if y}
        for kk, v in o.items():
            if isinstance(v, (dict, list)):
                if str(kk).startswith('level_') and lv(kk): acc.add(lv(kk))
                take(v, acc, depth + 1)
    elif isinstance(o, list):
        for v in o: take(v, acc, depth + 1)


def main():
    bases = [D / 'pv_sandbox/af_calibration', D / 'dda_seeds', D / 'pv_sandbox/dda_t0_all_20261020', D / 'pv_sandbox/pv_20261002_live3']
    folders = {}
    for base in bases:
        for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name != OUT.name):
            acc = set()
            for f in sorted(d.rglob('*')):
                if f.suffix not in ('.json', '.jsonl') or f.stat().st_size > 80_000_000: continue
                try:
                    if f.suffix == '.jsonl':
                        for line in f.open():
                            try: take(json.loads(line), acc)
                            except ValueError: pass
                    else: take(json.load(f.open()), acc)
                except (ValueError, OSError): pass
            folders[str(d.relative_to(D))] = sorted(acc)
            print(len(acc), d.relative_to(D), flush=True)
    cls = {k: ('population_or_data' if len(v) > 200 or k in POP_OR_DATA else 'targeted') for k, v in folders.items()}
    used = sorted({L for k, v in folders.items() if cls[k] == 'targeted' for L in v})
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / 'used_scan.tmp'
    tmp.write_text(json.dumps(dict(rule=__doc__, folders=folders, cls=cls, used=used), indent=1)); tmp.replace(OUT / 'used_scan.json')
    print('USED', len(used))


if __name__ == '__main__':
    main()
