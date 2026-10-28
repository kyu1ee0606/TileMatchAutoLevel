"""Small validation of bot level_summary (spec 55 §8, sv=1). Not a measurement of bot quality.

Part A (new, <=200 games): baseline config (cap .65, PREREG base rules), maps L138(lock+stack) / L292(craft+link+bomb)
/ L152(grass+link) / L293(bomb), thetas .65/.85/1.2 x 8 games, seed 33M. Each game is also replayed with the plain bot
(strong parity: identical chosen-tile sequence, outcome, dock). Output: rows.jsonl (one summary per game) + sanity.json.
Part B (post-hoc, no games): subset of keys recomputed from existing dock_trace_20261026 (weak-parity trace).
Writes only inside OUT.
"""
import sys, json, hashlib, os, re, shutil, subprocess, dataclasses, statistics
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_public_deadline_20261026 as prior
import trace_parity_20261026 as TP
from app.core import bot_play_summary as S
c = prior.c
OUT = B_ / 'data/pv_sandbox/af_calibration/play_summary_check_20261027'
MAPS = [138, 292, 152, 293]; THETAS = [.65, .85, 1.2]; GAMES = 8; SEED = 33000000
KEYS = ['picks', 'pick_new', 'pick_match', 'min_free', 'danger_picks', 'danger_tail', 'end_pairs',
        'bomb_left_min', 'grass_first', 'grass_left', 'key_unlock', 'cont_first']


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(); return p


def profile(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(prior.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def part_a():
    rows = []
    if _p('rows.jsonl').exists():
        rows = [json.loads(x) for x in _p('rows.jsonl').read_text().splitlines()]
    done = {(r['level'], r['_theta'], r['_g']) for r in rows}
    for L in MAPS:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in THETAS:
            p = profile(L, t)
            for g in range(GAMES):
                if (L, t, g) in done: continue
                free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
                if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3: print('STOP', free, flush=True); return None
                b = TP.recorder(S.SummaryBot)(); b.set_rule_parity(p)
                st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                b.pick_log = []; b._rng.seed(SEED + g); end = b._play_game(b._fast_copy_state(st), p)
                cat = c.ev.base.fail_reason(b, end)
                s = S.summarize(b.pick_log, st, end, cat, L, f'bot_L{L}_t{t}_s{SEED + g}')
                pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                ps = pb._create_initial_state(layout, int(layout['max_moves'])); pb._precompute_blocking_map(ps)
                pb._rng.seed(SEED + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                if not ok: print('PARITY_FAIL', L, t, g, detail, flush=True); sys.exit(2)
                s.update(_theta=t, _g=g, _bot_category=cat, _parity='strong', _range_violations=S.check_ranges(s),
                         _picks_eq_moves=len(b.pick_log) == end.moves_used)
                with _p('rows.jsonl').open('a') as f: f.write(json.dumps(s) + '\n')
                rows.append(s); print('GAME', L, t, g, s['seg_end'], s['picks'], flush=True)
    return rows


def describe(vals):
    vals = sorted(vals)
    if not vals: return None
    q = lambda f: vals[min(len(vals) - 1, int(f * (len(vals) - 1) + .5))]
    return dict(n=len(vals), min=vals[0], p25=q(.25), p50=q(.5), p75=q(.75), max=vals[-1])


def part_b():
    src = B_ / 'data/pv_sandbox/af_calibration/dock_trace_20261026'
    out = {}
    for f in sorted(src.glob('L*_t*_g*.json')):
        r = json.loads(f.read_text()); tr = r['trace']
        frees = [x['cap'] - x['dock'] for x in tr]; danger = [v <= 2 for v in frees]
        tail = 0
        for d in reversed(danger):
            if not d: break
            tail += 1
        s = dict(picks=len(tr), pick_new=sum(x['chosen']['in_dock'] == 0 for x in tr), pick_match=sum(x['chosen']['in_dock'] == 2 for x in tr),
                 min_free=min(frees) if frees else -1, danger_picks=sum(danger), danger_tail=tail,
                 end_pairs=sum(v == 2 for v in Counter(r['final_dock']).values()),
                 cont_first=next((k + 1 for k, x in enumerate(tr) if x['chosen']['kind'] in ('stack', 'craft', 'craft_emitted')), 0),
                 seg_end=S.SEG_END_MAP.get(r['reason'] or 'clear'))
        out.setdefault(r['L'], []).append(s)
    return {L: {k: describe([s[k] for s in v]) for k in ('picks', 'pick_new', 'pick_match', 'min_free', 'danger_picks', 'danger_tail', 'end_pairs', 'cont_first')}
            | {'seg_end': dict(Counter(s['seg_end'] for s in v))} for L, v in out.items()}


def main():
    assert OUT.parent.name == 'af_calibration' and OUT.name == 'play_summary_check_20261027'
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest()
    mod = hashlib.sha256((B_ / 'app/core/bot_play_summary.py').read_bytes()).hexdigest()
    man = dict(core=sha, summary_module=mod, maps=MAPS, thetas=THETAS, games=GAMES, seed=SEED, base=prior.BASE, sv=S.SV)
    if _p('manifest.json').exists(): assert json.loads(_p('manifest.json').read_text()) == json.loads(json.dumps(man))
    else: _p('manifest.json').write_text(json.dumps(man, indent=2))
    rows = part_a()
    if rows is None: return
    sanity = dict(part_a={L: {k: describe([r[k] for r in rows if r['level'] == L]) for k in KEYS}
                          | {'seg_end': dict(Counter(r['seg_end'] for r in rows if r['level'] == L)),
                             'range_violations': sum(bool(r['_range_violations']) for r in rows if r['level'] == L),
                             'picks_eq_moves': all(r['_picks_eq_moves'] for r in rows if r['level'] == L)} for L in MAPS},
                  part_b_dock_trace_weak_parity=part_b(), games_new=len(rows) * 2)
    tmp = _p('sanity.tmp'); tmp.write_text(json.dumps(sanity, indent=2)); os.replace(tmp, _p('sanity.json'))
    print('DONE', len(rows), flush=True)


if __name__ == '__main__':
    main()
