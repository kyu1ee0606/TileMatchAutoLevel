"""Read-only hazard trace (diagnosis only, not validation): L152 grass / L293 bomb.

Baseline = A2 baseline config (cap .65, keyON rules). New seed band 19M, 5 thetas x 8 games x 2 maps.
Per turn records: awareness, number of candidate moves whose immediate result is grass-impossible or
bomb-explosion (evaluated on a copy, RNG state restored), whether chosen move was such a hazard.
Does not modify game state of the real playthrough beyond the normal bot play.
"""
import sys, json, time, hashlib, subprocess, re, shutil, dataclasses, os
from pathlib import Path
from collections import Counter
B = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B), str(B / 'scripts')]
import bot_public_deadline_20261026 as prior
import trace_parity_20261026 as TP
c = prior.c
OUT = B / 'data/pv_sandbox/af_calibration/hazard_trace_20261026'
MAPS = [152, 293]; THETAS = prior.THETAS; GAMES = 8; SEED = 19000000


class Traced(c.BotSimulator):
    def __init__(self):
        super().__init__(); self.trace = []

    def _hazard(self, state, move):
        rs = self._rng.getstate(); hint = getattr(self, '_v23_hint', None)
        try:
            s = self._fast_copy_state(state)
            exposed = set()
            for k in s.bomb_tiles:
                p = k.split('_')
                t = s.tiles.get(int(p[0]), {}).get(f"{p[1]}_{p[2]}")
                if t is not None and not t.picked and not self._is_blocked_by_upper(s, t): exposed.add(k)
            m = next((x for x in self._get_available_moves(s) if x.tile_state.full_key == move.tile_state.full_key), None)
            if m is None: return dict(err=1)
            self._apply_move(s, m); s.moves_used += 1
            self._process_move_effects(s, exposed, set())
            return dict(grass=bool(self._check_grass_impossible(s)), bomb=any(v <= 0 for v in s.bomb_tiles.values()),
                        full=bool(self._is_dock_full(s)))
        finally:
            self._rng.setstate(rs)
            if hint is not None: self._v23_hint = hint

    def _select_move_with_profile(self, moves, state, profile):
        hz = {m.tile_state.full_key: self._hazard(state, m) for m in moves}
        bombs = {}
        for k, v in state.bomb_tiles.items():
            p = k.split('_'); t = state.tiles.get(int(p[0]), {}).get(f"{p[1]}_{p[2]}")
            if t is not None and not t.picked:
                bombs[k] = dict(rem=v, exposed=not self._is_blocked_by_upper(state, t))
        aware = dict(getattr(self, '_v21_aware', {}))
        sel = super()._select_move_with_profile(moves, state, profile)
        safe = [m for m in moves if not any(hz[m.tile_state.full_key].get(x) for x in ('grass', 'bomb'))]
        rec = dict(turn=state.moves_used, dock=len(state.dock_tiles), n=len(moves), aware=aware, bombs=bombs,
                   n_grass_trap=sum(1 for v in hz.values() if v.get('grass')),
                   n_bomb_trap=sum(1 for v in hz.values() if v.get('bomb')),
                   n_safe=len(safe),
                   best_safe=max((m.score for m in safe), default=None),
                   chosen=None if sel is None else dict(key=sel.tile_state.full_key, type=sel.tile_type, score=sel.score,
                                                        match=sel.will_match, bomb_pick=sel.tile_state.full_key in state.bomb_tiles,
                                                        **hz.get(sel.tile_state.full_key, {})),
                   top=[dict(key=m.tile_state.full_key, score=round(m.score, 2), match=m.will_match, **hz[m.tile_state.full_key])
                        for m in sorted(moves, key=lambda m: -m.score)[:5]])
        self.trace.append(rec)
        return sel


def valid_checkpoint(dest, L, t, g):
    """Skip only a fully parsed, complete game row; anything else is re-run."""
    if not dest.exists(): return False
    try:
        r = json.loads(dest.read_text())
        return (r.get('L'), r.get('theta'), r.get('g')) == (L, t, g) and isinstance(r.get('trace'), list) \
            and len(r['trace']) == r.get('turns') and 'win' in r and r.get('parity') is True and r.get('parity_mode') == 'strong'
    except (ValueError, OSError):
        return False


def free_swap():
    return float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == os.environ['EXPECTED_BOT_SHA256']
    man = dict(source_hash=sha, maps=MAPS, thetas=THETAS, games=GAMES, seed=SEED, base=prior.BASE, cap=.65,
               scope='diagnosis only (cause hypotheses); not validation; new seed band 19M',
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
                p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
                cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
                           auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=prior.BASE, grass_attention_cap=.65)
                p = dataclasses.replace(p, gimmick_awareness=cfg); b = TP.recorder(Traced)(); b.set_rule_parity(p)
                layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                b._rng.seed(SEED + g); t0 = time.time()
                end = b._play_game(b._fast_copy_state(st), p)
                # parity: same seed with untraced bot must give identical outcome (trace must not perturb play)
                pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                pst = pb._create_initial_state(layout, int(layout['max_moves'])); pb._precompute_blocking_map(pst)
                pb._rng.seed(SEED + g); pend = pb._play_game(pb._fast_copy_state(pst), p)
                parity, parity_detail = TP.compare(b, end, pb, pend, c.ev.base.fail_reason)
                if not parity:   # strong parity failure: keep evidence aside, never as a completed checkpoint
                    (OUT / (dest.name + '.mismatch')).write_text(json.dumps(dict(parity_detail=parity_detail, traced=b.choice_keys, plain=pb.choice_keys)))
                    print('PARITY_FAIL', dest.name, parity_detail, flush=True); sys.exit(2)
                row = dict(L=L, theta=t, g=g, seed=SEED + g, win=end.cleared, reason=None if end.cleared else c.ev.base.fail_reason(b, end),
                           turns=end.moves_used, parity=parity, parity_mode='strong', parity_detail=parity_detail, choice_keys=b.choice_keys, sec=time.time() - t0, trace=b.trace)
                tmp = dest.with_suffix('.json.tmp')
                tmp.write_text(json.dumps(row)); os.replace(tmp, dest)  # atomic: no truncated checkpoint
                print('GAME', L, t, g, row['win'], row['reason'], row['turns'], 'parity', parity, 'trace', len(b.trace), round(row['sec'], 2), flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
