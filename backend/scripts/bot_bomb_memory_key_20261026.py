"""PREREG (fixed before any run): bomb_threat_memory single candidate + public_key_stack_plan new-map check.

No refit of mixture/awareness; no level-specific branch; no outcome forcing. Local AF cache only.
Phases (separate seeds):
  regress : baseline L293 theta .85 seed18M x16 must reproduce A2 row (7/16) -> default unchanged.
  bombD   : discovery/dev, maps 293/294/449 (already seen in diagnosis), baseline vs memory, 16/theta, seed20M.
            Gate: memory bomb-3 joint MSE < baseline. If not, bomb R/N are skipped (not adopted).
  bombR   : new RNG, same 3 maps, 32/theta, seed21M (same known maps -> not independent-map validation).
  bombN   : new maps chosen by rule only (eff_bomb, editor map same, not excluded, not previously used in
            2026-10-26 bot work, clean n>=100, top 8 by n desc), 32/theta, seed22M.
  key     : new key maps by rule only (unlockTile>0, no craft, editor map same, not excluded, not previously used,
            clean n>=100, top 6 by n desc), keyON all thetas, key_off theta1.2 (+theta1.0 sanity on first map),
            32 games, seed23M. theta<=1 key_off rows reuse keyON rows (search_rollouts=0) - not counted as runs.
"""
import sys, json, time, hashlib, subprocess, re, shutil, os
from pathlib import Path
from collections import Counter
B = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B), str(B / 'scripts')]
import bot_public_deadline_20261026 as prior
c = prior.c; THETAS = prior.THETAS; WEIGHTS = prior.WEIGHTS
OUT = B / 'data/pv_sandbox/af_calibration/bomb_memory_key_20261026'
USED = sorted(set([151, 184, 241, 293, 152, 448, 284, 355, 153, 161, 294, 449,
                   51, 81, 343, 442, 68, 133, 164, 209, 324, 396, 224, 276,
                   102, 354, 182, 315, 251, 382]))
BOMB_DIAG = [293, 294, 449]
MAX_GAMES = 6000; MAX_SEC = 3600


def unlock(L):
    lay = c.ev.base.level_layouts(c.P[L], 1)[0]
    return int(lay.get('xUnlockTile', lay.get('unlockTile', 0)) or 0)


def eligible(L):
    e = c.P[L]
    return (L in c.A and not e.get('exclude') and e.get('map_match_editor') == 'same' and L not in USED
            and c.A[L]['clean_ft_n'] >= 100)


def select_maps():
    Ls = sorted(set(c.P) & set(c.A))
    bomb = [L for L in Ls if eligible(L) and c.P[L]['features'].get('eff_bomb')]
    key = [L for L in Ls if eligible(L) and unlock(L) > 0 and not c.P[L]['features'].get('craft')]
    by_n = lambda L: (-c.A[L]['clean_ft_n'], L)
    return sorted(bomb, key=by_n)[:8], sorted(key, key=by_n)[:6]


def rules(option):
    if option == 'key_off': return list(c.RULES)
    return list(prior.BASE) + ([] if option == 'baseline' else [option])


def measure(phase, option, L, t, n, seed):
    import dataclasses
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=rules(option), grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg); b = c.BotSimulator(); b.set_rule_parity(p)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    wins = 0; reasons = Counter()
    for g in range(n):
        b._rng.seed(seed + g); end = b._play_game(b._fast_copy_state(st), p)
        if end.cleared: wins += 1
        else: reasons[c.ev.base.fail_reason(b, end)] += 1
    row = dict(phase=phase, option=option, L=L, theta=t, games=n, wins=wins, fail_reasons=dict(reasons), seedbase=seed, sec=time.time() - start)
    with (OUT / 'rows.jsonl').open('a') as f: f.write(json.dumps(row) + '\n')
    c.log('ROW', phase, option, L, t, wins, n, round(row['sec'], 2)); return row


def evaluate(rows, phase, option, levels):
    return prior.evaluate([dict(r, phase=phase) for r in rows if r['phase'] == phase], phase, option, levels)


def main():
    OUT.mkdir(parents=True, exist_ok=True); c.OUT = OUT
    sha = hashlib.sha256((B / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == os.environ['EXPECTED_BOT_SHA256']
    bombN, keyN = select_maps()
    maps = BOMB_DIAG + bombN + keyN
    manifest = dict(source_hash=sha, thetas=THETAS, weights=WEIGHTS, cap=.65, base=prior.BASE, used_excluded=USED,
                    bomb_diag=BOMB_DIAG, bomb_new=bombN, key_new=keyN,
                    seeds=dict(regress=18000000, bombD=20000000, bombR=21000000, bombN=22000000, key=23000000),
                    games=dict(regress=16, bombD=16, bombR=32, bombN=32, key=32),
                    selection=('bomb_new: eff_bomb & editor map same & not excluded & not USED & n>=100, top8 by n; '
                               'key_new: unlockTile>0 & no craft & editor map same & not excluded & not USED & n>=100, top6 by n; '
                               'chosen before viewing AF clear/fail rates of these maps'),
                    criteria=dict(
                        gate='bombD: memory joint MSE(293/294/449) < baseline else skip R/N',
                        bomb_support='bombR joint MSE improves AND bombN joint MSE improves AND bombN clear MAE not worse AND bomb-fail share abs error improves on >=5/8 new maps',
                        key_support='key new maps: keyON joint MSE < keyOFF AND clear abs error improves on >=4/6 maps',
                        adoption='never default in this run; report only'),
                    stop=dict(swap_free_mb=500, disk_gib=10, max_games=MAX_GAMES, max_sec=MAX_SEC),
                    scope='bomb maps historically exposed to bomb awareness fitting (26 s10-2); AF clean first attempt targets; not population trial',
                    maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(), mode=c.P[L]['mode'],
                                  features=c.P[L]['features'], n=c.A[L]['clean_ft_n']) for L in maps})
    if (OUT / 'manifest.json').exists(): assert json.loads((OUT / 'manifest.json').read_text()) == json.loads(json.dumps(manifest))
    else: c.save('manifest.json', manifest)
    rows = [json.loads(x) for x in (OUT / 'rows.jsonl').read_text().splitlines()] if (OUT / 'rows.jsonl').exists() else []
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent0 = sum(r['sec'] for r in rows)

    def run(phase, options, levels, n, seed, thetas=THETAS):
        for L in levels:
            for o in options:
                for t in thetas:
                    if (phase, o, L, t) in done: continue
                    free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
                    games = sum(r['games'] for r in rows)
                    if free < 500 or shutil.disk_usage(B).free < 10 * 1024 ** 3 or spent0 + time.time() - start > MAX_SEC or games + n > MAX_GAMES:
                        c.log('STOP', free, games, round(spent0 + time.time() - start, 1)); return False
                    rows.append(measure(phase, o, L, t, n, seed)); done.add((phase, o, L, t))
        return True

    if not run('regress', ['baseline'], [293], 16, 18000000, [.85]): return
    reg = [r for r in rows if r['phase'] == 'regress'][0]
    if reg['wins'] != 7: c.log('REGRESS_MISMATCH', reg['wins']); return
    summary = dict(regress=reg)
    if not run('bombD', ['baseline', 'bomb_threat_memory'], BOMB_DIAG, 16, 20000000): return
    summary['bombD'] = {o: evaluate(rows, 'bombD', o, BOMB_DIAG) for o in ('baseline', 'bomb_threat_memory')}
    gate = summary['bombD']['bomb_threat_memory']['joint_mse'] < summary['bombD']['baseline']['joint_mse']
    summary['gate_pass'] = gate; c.log('GATE', gate)
    if gate:
        if not run('bombR', ['baseline', 'bomb_threat_memory'], BOMB_DIAG, 32, 21000000): return
        summary['bombR'] = {o: evaluate(rows, 'bombR', o, BOMB_DIAG) for o in ('baseline', 'bomb_threat_memory')}
        if not run('bombN', ['baseline', 'bomb_threat_memory'], bombN, 32, 22000000): return
        summary['bombN'] = {o: evaluate(rows, 'bombN', o, bombN) for o in ('baseline', 'bomb_threat_memory')}
    if not run('key', ['baseline'], keyN, 32, 23000000): return
    if not run('key', ['key_off'], keyN, 32, 23000000, [1.2]): return
    if not run('key', ['key_off'], keyN[:1], 32, 23000000, [1.0]): return
    krows = [r for r in rows if r['phase'] == 'key']
    copied = [dict(r, option='key_off') for r in krows if r['option'] == 'baseline' and r['theta'] != 1.2
              and ('key', 'key_off', r['L'], r['theta']) not in done]
    sanity = [(r['wins'], q['wins']) for r in krows for q in krows if r['option'] == 'baseline' and q['option'] == 'key_off'
              and r['L'] == q['L'] and r['theta'] == q['theta'] == 1.0]
    summary['key'] = {o: evaluate(krows + copied, 'key', o, keyN) for o in ('baseline', 'key_off')}
    summary['key_theta1_sanity_on_off_wins'] = sanity
    summary['settings'] = len(rows); summary['games'] = sum(r['games'] for r in rows); summary['seconds'] = sum(r['sec'] for r in rows)
    c.save('summary.json', summary); c.log('DONE', len(rows))


if __name__ == '__main__':
    main()
