"""Doc 61 step 2b: why does L378 collapse vs the Oct-15 population run (v24f theta1.0 clear 76%)? Diagnostic only.
Configs on L378 x theta 1.0 / 1.2 x 16 games, seed 51M:
  cur_BASE  current core (cbc2e652), v24 = BASE (current B)
  cur_DEF   current core, v24 = None (V24_DEFAULT, like v24f)
  head_DEF  committed HEAD core (git show HEAD, 2026-10-16, ~ v24f era; byte copy argv[1]), v24 = None
  head_BASE HEAD core, v24 = BASE
Other cfg identical (FIXED, alpha/gamma, exposure, parity None, cap .65). Guard + STOP flag. Writes OUT/ablate_rows.jsonl."""
import sys, json, os, dataclasses, importlib.util, hashlib
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/plain_diag_20261027'
L = int(os.environ.get('ABL_L', 378)); GAMES = 16; SEED = 51000000


def load_head(path):
    spec = importlib.util.spec_from_file_location('app.core._bot_simulator_head', path)
    m = importlib.util.module_from_spec(spec); m.__package__ = 'app.core'; sys.modules[spec.name] = m; spec.loader.exec_module(m); return m


def prof(t, v24):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=v24, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    head = load_head(sys.argv[1])
    cfgs = {'cur_BASE': (c.BotSimulator, list(R.prior.BASE)), 'cur_DEF': (c.BotSimulator, None),
            'head_DEF': (head.BotSimulator, None), 'head_BASE': (head.BotSimulator, list(R.prior.BASE))}
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    out = OUT / f'ablate_rows_L{L}.jsonl'
    done = {(json.loads(x)['cfg'], json.loads(x)['theta']) for x in out.read_text().splitlines()} if out.exists() else set()
    for t in (1.0, 1.2):
        for name, (cls, v24) in cfgs.items():
            if (name, t) in done: continue
            if (OUT / 'STOP').exists() or not G.wait_ok(): return
            p = prof(t, v24); b = cls(); b.set_rule_parity(p)
            st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
            wins = 0; fr = Counter()
            for g in range(GAMES):
                b._rng.seed(SEED + g); e = b._play_game(b._fast_copy_state(st), p)
                if e.cleared: wins += 1
                else: fr[c.ev.base.fail_reason(b, e)] += 1
            row = dict(L=L, cfg=name, theta=t, games=GAMES, wins=wins, fail=dict(fr), head_sha=hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()[:16])
            with out.open('a') as f: f.write(json.dumps(row) + '\n')
            print(row, flush=True)


if __name__ == '__main__':
    main()
