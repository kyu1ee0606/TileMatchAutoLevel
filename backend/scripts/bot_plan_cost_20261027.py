"""Cost probe (not an evaluation): seconds/game for skill_planning (P1) and public_craft_belief (P2).
Already-used maps only (292/306 craft, 138 key+stack, 313 bomb+stack, 152 grass), 5 thetas x 4 games x cells
B/P1/P2/P12, seed 34M. Writes only inside OUT."""
import sys, json, time, hashlib, os, re, shutil, subprocess, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_public_deadline_20261026 as prior
c = prior.c
OUT = B_ / 'data/pv_sandbox/af_calibration/plan_cost_20261027'
MAPS = [292, 306, 138, 313, 152]; THETAS = prior.THETAS; GAMES = 4; SEED = 34000000
CELLS = {'B': [], 'P1': ['skill_planning'], 'P2': ['public_craft_belief'], 'P12': ['skill_planning', 'public_craft_belief']}


def _p(n):
    p = OUT / n; assert p.resolve().parent == OUT.resolve(); return p


class Count(c.BotSimulator):
    def __init__(self):
        super().__init__(); self.searches = 0; self.fallback = 0
    def _v2_search_select(self, moves, state, profile):
        self.searches += 1
        return super()._v2_search_select(moves, state, profile)
    def _v24_determinize(self, state):
        r = super()._v24_determinize(state)
        if r is False: self.fallback += 1
        return r


def main():
    assert OUT.name == 'plan_cost_20261027'; OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == os.environ['EXPECTED_BOT_SHA256']
    done = set()
    if _p('rows.jsonl').exists():
        for x in _p('rows.jsonl').read_text().splitlines():
            r = json.loads(x); done.add((r['cell'], r['L'], r['theta']))
    for L in MAPS:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for cell, extra in CELLS.items():
            for t in THETAS:
                if (cell, L, t) in done: continue
                free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
                if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3: print('STOP', free, flush=True); return
                p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
                cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
                           auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
                           v24=list(prior.BASE) + extra, grass_attention_cap=.65)
                p = dataclasses.replace(p, gimmick_awareness=cfg)
                b = Count(); b.set_rule_parity(p); st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                secs = []; wins = 0; reasons = Counter(); moves = 0
                for g in range(GAMES):
                    b._rng.seed(SEED + g); t0 = time.time(); end = b._play_game(b._fast_copy_state(st), p); secs.append(time.time() - t0)
                    wins += end.cleared; moves += end.moves_used
                    if not end.cleared: reasons[c.ev.base.fail_reason(b, end)] += 1
                row = dict(cell=cell, L=L, theta=t, games=GAMES, wins=wins, fail_reasons=dict(reasons), sec_mean=sum(secs) / GAMES,
                           sec_max=max(secs), searches=b.searches, fallback=b.fallback, moves=moves)
                with _p('rows.jsonl').open('a') as f: f.write(json.dumps(row) + '\n')
                print('ROW', cell, L, t, wins, round(row['sec_mean'], 2), round(row['sec_max'], 2), b.searches, b.fallback, flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
