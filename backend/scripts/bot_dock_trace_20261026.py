"""Read-only dock/search trace (diagnosis only): Normal(dock-full) over-failure maps L292/L306/L138/L313.

Baseline = PREREG baseline config (cap .65, keyON rules, memory OFF). New seed band 24M, 5 thetas x 8 games x 4 maps.
Per turn: dock size/capacity/type composition, matches available vs chosen, chosen tile kind (plain/stack/craft
emitted/link), top candidate scores, search & determinize-fallback counts. Untraced same-seed parity check per game.
Atomic checkpoints; resume skips only fully parsed rows.
"""
import sys, json, time, hashlib, subprocess, re, shutil, dataclasses, os
from pathlib import Path
from collections import Counter
B = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B), str(B / 'scripts')]
import bot_public_deadline_20261026 as prior
import trace_parity_20261026 as TP
c = prior.c
OUT = B / 'data/pv_sandbox/af_calibration/dock_trace_20261026'
MAPS = [292, 306, 138, 313]; THETAS = prior.THETAS; GAMES = 8; SEED = 24000000


def kind(t):
    if t is None: return None
    if getattr(t, 'is_crafted', False): return 'craft_emitted'
    if t.is_craft_tile: return 'craft'
    if t.is_stack_tile: return 'stack'
    if t.effect_type is not None and 'LINK' in str(t.effect_type): return 'link'
    return 'plain'


class Traced(c.BotSimulator):
    def __init__(self):
        super().__init__(); self.trace = []; self.search_calls = 0; self.fallbacks = 0

    def _v24_determinize(self, state):
        r = super()._v24_determinize(state)
        if r is False: self.fallbacks += 1
        return r

    def _v2_search_select(self, moves, state, profile):
        self.search_calls += 1
        return super()._v2_search_select(moves, state, profile)

    def _select_move_with_profile(self, moves, state, profile):
        sc0, fb0 = self.search_calls, self.fallbacks
        sel = super()._select_move_with_profile(moves, state, profile)
        dock = Counter(t.tile_type for t in state.dock_tiles)
        cap = sum(1 for s in state.dock if not s.is_locked)
        matches = [m for m in moves if m.will_match]
        self.trace.append(dict(
            turn=state.moves_used, dock=len(state.dock_tiles), cap=cap, dock_types=dict(dock),
            pairs=sum(1 for v in dock.values() if v == 2), singles=sum(1 for v in dock.values() if v == 1),
            n=len(moves), n_match=len(matches), best_match=max((m.score for m in matches), default=None),
            chosen=None if sel is None else dict(type=sel.tile_type, score=round(sel.score, 2), match=sel.will_match,
                                                 kind=kind(sel.tile_state), in_dock=dock.get(sel.tile_type, 0),
                                                 linked=len(sel.linked_tiles or [])),
            search=self.search_calls - sc0, fallback=self.fallbacks - fb0,
            top=[dict(type=m.tile_type, score=round(m.score, 2), match=m.will_match, kind=kind(m.tile_state), in_dock=dock.get(m.tile_type, 0))
                 for m in sorted(moves, key=lambda m: -m.score)[:5]]))
        return sel


def valid_checkpoint(dest, L, t, g):
    if not dest.exists(): return False
    try:
        r = json.loads(dest.read_text())
        return (r.get('L'), r.get('theta'), r.get('g')) == (L, t, g) and isinstance(r.get('trace'), list) \
            and len(r['trace']) == r.get('turns') and 'win' in r and r.get('parity') is True and r.get('parity_mode') == 'strong'
    except (ValueError, OSError):
        return False


def free_swap():
    return float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])


def profile(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=prior.BASE, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == os.environ['EXPECTED_BOT_SHA256']
    man = dict(source_hash=sha, maps=MAPS, thetas=THETAS, games=GAMES, seed=SEED, base=prior.BASE, cap=.65,
               scope='diagnosis only (cause hypotheses); not validation; new seed band 24M',
               map_hash={L: hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest() for L in MAPS})
    mp = OUT / 'manifest.json'
    if mp.exists(): assert json.loads(mp.read_text()) == json.loads(json.dumps(man))
    else: mp.write_text(json.dumps(man, indent=2))
    for L in MAPS:
        for t in THETAS:
            for g in range(GAMES):
                dest = OUT / f'L{L}_t{t}_g{g}.json'
                if valid_checkpoint(dest, L, t, g): continue
                if free_swap() < 500 or shutil.disk_usage(B).free < 10 * 1024 ** 3:
                    print('STOP resource', free_swap(), flush=True); return
                p = profile(L, t); b = TP.recorder(Traced)(); b.set_rule_parity(p)
                layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                b._rng.seed(SEED + g); t0 = time.time(); end = b._play_game(b._fast_copy_state(st), p)
                pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                pst = pb._create_initial_state(layout, int(layout['max_moves'])); pb._precompute_blocking_map(pst)
                pb._rng.seed(SEED + g); pend = pb._play_game(pb._fast_copy_state(pst), p)
                parity, parity_detail = TP.compare(b, end, pb, pend, c.ev.base.fail_reason)
                if not parity:   # strong parity failure: keep evidence aside, never as a completed checkpoint
                    (OUT / (dest.name + '.mismatch')).write_text(json.dumps(dict(parity_detail=parity_detail, traced=b.choice_keys, plain=pb.choice_keys)))
                    print('PARITY_FAIL', dest.name, parity_detail, flush=True); sys.exit(2)
                row = dict(L=L, theta=t, g=g, seed=SEED + g, win=end.cleared, reason=None if end.cleared else c.ev.base.fail_reason(b, end),
                           turns=end.moves_used, parity=parity, parity_mode='strong', parity_detail=parity_detail, choice_keys=b.choice_keys, sec=time.time() - t0,
                           final_dock=[x.tile_type for x in end.dock_tiles], trace=b.trace)
                tmp = dest.with_suffix('.json.tmp'); tmp.write_text(json.dumps(row)); os.replace(tmp, dest)
                print('GAME', L, t, g, row['win'], row['reason'], row['turns'], 'parity', parity, round(row['sec'], 2), flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
