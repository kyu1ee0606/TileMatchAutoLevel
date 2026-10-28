"""Doc 65 input (re-scan incl. docs 56-64 outputs; derived from bot_k1c_exposure_scan_20261027): per-map MEASURED exposure (rows actually measured), not manifest exclusion lists. Writes OUT/exposure.json.

Scope: every output folder under af_calibration, dda_seeds, dda_t0_all, pv_20261002_live3 (docs 56-64 included).
A map counts as measured in a folder only if it appears as the L/level field of a row-like record:
  every line of *.jsonl, and dicts inside list-valued json files / 'rows' arrays; files named *manifest*, *used*,
  *selected*, *summary*, *judgement*, *tables*, *impact* are skipped (they hold selection / exclusion lists or aggregates).
Folder kinds:
  af_compare : bot runs whose per-map result was compared with AF (calibration / candidate / diagnosis runs)
  bot_only   : bot-vs-bot or cost / parity / trace runs without AF comparison (named in BOT_ONLY)
  population : > 200 measured maps or POP_OR_DATA (same as doc 59) -> ignored
"""
import json
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]
D = B_ / 'data'
OUT = D / 'pv_sandbox/af_calibration/se_power_prereg_20261027'
SKIP_NAME = ('manifest', 'used', 'selected', 'summary', 'judgement', 'tables', 'impact')
POP_OR_DATA = {'pv_sandbox/af_calibration/bot_v22', 'pv_sandbox/pv_20261002_live3/dda_readiness_20261019',
               'pv_sandbox/pv_20261002_live3/dda_sets_v2', 'dda_seeds/bulk_snapshot_20261020_1905_get'}
BOT_ONLY = {'key_parity_invariance_20261027', 'key_placement_golden_20261027', 'key_unlock_diag_20261027', 'grass_bomb_cost_20261027',
            'grass_bomb_cost_v2_20261027', 'plan_cost_20261027', 'play_summary_check_20261027', 'plan_summary_dist_20261027',
            'k1c_port_20261027'}


def lv(v):
    if isinstance(v, int): return v if 32 <= v <= 500 else None
    if isinstance(v, str):
        s = v.replace('level_', '')
        if s.isdigit() and 32 <= int(s) <= 500: return int(s)
    return None


def rec(o, acc):
    if isinstance(o, dict):
        for k in ('L', 'level', 'lv', 'level_id', 'levelId'):
            x = lv(o.get(k))
            if x: acc.add(x); break


def main():
    bases = [D / 'pv_sandbox/af_calibration', D / 'dda_seeds', D / 'pv_sandbox/dda_t0_all_20261020', D / 'pv_sandbox/pv_20261002_live3']
    folders = {}
    for base in bases:
        for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name != OUT.name):
            acc = set()
            for f in sorted(d.rglob('*')):
                if f.suffix not in ('.json', '.jsonl') or any(s in f.name.lower() for s in SKIP_NAME) or f.stat().st_size > 80_000_000: continue
                try:
                    if f.suffix == '.jsonl':
                        for line in f.open():
                            try: rec(json.loads(line), acc)
                            except ValueError: pass
                    else:
                        o = json.load(f.open())
                        items = o if isinstance(o, list) else (o.get('rows') if isinstance(o, dict) and isinstance(o.get('rows'), list) else [])
                        for it in items: rec(it, acc)
                except (ValueError, OSError): pass
            folders[str(d.relative_to(D))] = sorted(acc)
    kind = {}
    for k, v in folders.items():
        name = k.split('/')[-1]
        kind[k] = 'population' if (len(v) > 200 or k in POP_OR_DATA) else ('bot_only' if name in BOT_ONLY else 'af_compare')
    af = sorted({L for k, v in folders.items() if kind[k] == 'af_compare' for L in v})
    bo = sorted({L for k, v in folders.items() if kind[k] == 'bot_only' for L in v})
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / 'exposure.tmp'; tmp.write_text(json.dumps(dict(rule=__doc__, folders=folders, kind=kind, af_compare=af, bot_only=bo), indent=1))
    tmp.replace(OUT / 'exposure.json')
    print('af_compare maps', len(af), 'bot_only maps', len(bo))


if __name__ == '__main__':
    main()
