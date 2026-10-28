"""Read-only paired trace (diagnosis only): why container_dig_capacity (G) worsens bomb+stack maps.

Maps L313/L298/L332 (worse under G) + L292 (improved, control). Cells B vs G, same seeds (28M band), 5 thetas x 8.
Per turn: exposed bombs (rem), bomb awareness, bomb-pick availability/score, chosen move kind and whether it is a
container (dig) pick, dig state, and the dig bonus of chosen vs best bomb pick. Untraced same-seed parity per game.
Output folder is new and verified to be the only write target.
"""
import sys, json, time, hashlib, subprocess, re, shutil, dataclasses, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_public_deadline_20261026 as prior
import trace_parity_20261026 as TP
c = prior.c
REPLAY = os.environ.get('DIG_TRACE_REPLAY') == '1'   # replay of N-stage seeds 22M (diagnosis of the worsened cells)
OUT = B_ / ('data/pv_sandbox/af_calibration/dig_bomb_trace_replay22M_20261026' if REPLAY else 'data/pv_sandbox/af_calibration/dig_bomb_trace_20261026')
MAPS = [313, 332] if REPLAY else [313, 298, 332, 292]
THETAS = [.65, .85] if REPLAY else prior.THETAS
GAMES = 32 if REPLAY else 8
SEED = 22000000 if REPLAY else 28000000
CELLS = {'B': [], 'G': ['container_dig_capacity']}


class Traced(c.BotSimulator):
    def __init__(self):
        super().__init__(); self.trace = []

    def _select_move_with_profile(self, moves, state, profile):
        aware = dict(getattr(self, '_v21_aware', {}))
        exposed = {}
        for k, v in state.bomb_tiles.items():
            p = k.split('_'); t = state.tiles.get(int(p[0]), {}).get(f"{p[1]}_{p[2]}")
            if t is not None and not t.picked and not self._is_blocked_by_upper(state, t): exposed[k] = v
        bomb_moves = [m for m in moves if f"{m.layer_idx}_{m.position}" in state.bomb_tiles
                      or any(f"{li}_{lp}" in state.bomb_tiles for li, lp in (m.linked_tiles or []))]
        dig = getattr(state, '_dig_box', None)
        sel = super()._select_move_with_profile(moves, state, profile)
        def info(m):
            if m is None: return None
            cont = self._cdc_container(state, m.tile_state)
            return dict(type=m.tile_type, score=round(m.score, 2), match=m.will_match,
                        container=None if cont is None else cont[0], bomb_pick=m in bomb_moves)
        best_bomb = max(bomb_moves, key=lambda m: m.score, default=None)
        self.trace.append(dict(turn=state.moves_used, dock=len(state.dock_tiles), exposed=exposed,
                               min_rem=min(exposed.values()) if exposed else None, aware_bomb=aware.get('bomb'),
                               dig=dig, n=len(moves), chosen=info(sel), best_bomb=info(best_bomb)))
        return sel


def profile(L, t, cell):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(prior.BASE) + CELLS[cell], grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def valid(dest, key):
    if not dest.exists(): return False
    try:
        r = json.loads(dest.read_text())
        return (r.get('L'), r.get('theta'), r.get('g'), r.get('cell')) == key and len(r.get('trace', [])) == r.get('turns') and r.get('parity') is True and r.get('parity_mode') == 'strong'
    except (ValueError, OSError):
        return False


def main():
    assert OUT.parent.name == 'af_calibration' and OUT.name in ('dig_bomb_trace_20261026', 'dig_bomb_trace_replay22M_20261026')
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == os.environ['EXPECTED_BOT_SHA256']
    man = dict(source_hash=sha, maps=MAPS, thetas=THETAS, games=GAMES, seed=SEED, cells=CELLS, base=prior.BASE,
               scope='diagnosis only (cause hypotheses); paired B vs G same seeds; not validation')
    mp = OUT / 'manifest.json'
    if mp.exists(): assert json.loads(mp.read_text()) == json.loads(json.dumps(man))
    else:
        tmp = OUT / 'manifest.tmp'; tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, mp)
    for L in MAPS:
        for t in THETAS:
            for g in range(GAMES):
                for cell in CELLS:
                    dest = OUT / f'L{L}_t{t}_g{g}_{cell}.json'
                    if valid(dest, (L, t, g, cell)): continue
                    free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
                    if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3: print('STOP', free, flush=True); return
                    p = profile(L, t, cell); layout = c.ev.base.level_layouts(c.P[L], 1)[0]
                    b = TP.recorder(Traced)(); b.set_rule_parity(p); st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                    b._rng.seed(SEED + g); t0 = time.time(); end = b._play_game(b._fast_copy_state(st), p)
                    pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p); ps = pb._create_initial_state(layout, int(layout['max_moves'])); pb._precompute_blocking_map(ps)
                    pb._rng.seed(SEED + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                    parity, parity_detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                    if not parity:   # strong parity failure: keep evidence aside, never as a completed checkpoint
                        (OUT / (dest.name + '.mismatch')).write_text(json.dumps(dict(parity_detail=parity_detail, traced=b.choice_keys, plain=pb.choice_keys)))
                        print('PARITY_FAIL', dest.name, parity_detail, flush=True); sys.exit(2)
                    row = dict(L=L, theta=t, g=g, cell=cell, seed=SEED + g, win=end.cleared, reason=None if end.cleared else c.ev.base.fail_reason(b, end),
                               turns=end.moves_used, parity=parity, parity_mode='strong', parity_detail=parity_detail, choice_keys=b.choice_keys, sec=time.time() - t0, trace=b.trace)
                    tmp = OUT / (dest.name + '.tmp'); tmp.write_text(json.dumps(row)); os.replace(tmp, dest)
                    print('GAME', L, t, g, cell, row['win'], row['reason'], row['turns'], 'parity', parity, round(row['sec'], 2), flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
