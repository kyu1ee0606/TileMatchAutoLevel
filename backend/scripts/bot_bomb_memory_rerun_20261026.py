"""Re-measure bomb_threat_memory after RNG separation (core 17f6445d...). Same PREREG criteria, same seeds/maps.

baseline rows: copied from bomb_memory_key_20261026 (same-seed paired reuse, NOT an independent re-measurement;
OFF path verified identical on core 17f6445d by reproductions). memory rows: re-run, all 5 thetas.
regress: baseline L293 theta .85 seed18M x16 must be 7/16 on this core.
Gate (unchanged): bombD memory joint MSE < baseline, else bombR/bombN memory skipped.
"""
import sys, json, time, hashlib, subprocess, re, shutil, os
from pathlib import Path
B = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B), str(B / 'scripts')]
import bot_bomb_memory_key_20261026 as R
import bot_bomb_memory_key_judge_20261026 as J
c = R.c
SRC = R.OUT
OUT = B / 'data/pv_sandbox/af_calibration/bomb_memory_rerun_20261026'
CORE = '17f6445d3f1ad848fbb19becfbba8fbaadc18c177800a91f2ffb2c399c8cde03'
MAX_GAMES = 2016


def main():
    OUT.mkdir(parents=True, exist_ok=True); R.OUT = OUT; c.OUT = OUT
    sha = hashlib.sha256((B / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    old = json.loads((SRC / 'manifest.json').read_text())
    src_raw = (SRC / 'rows.jsonl').read_bytes()
    man = dict(old, source_hash=sha, previous_source_hash=old['source_hash'], previous_rows_sha256=hashlib.sha256(src_raw).hexdigest(),
               rerun_scope='memory rows re-run (RNG separated); baseline rows same-seed paired reuse, not independent; key phase not re-run',
               rerun_games=dict(regress=16, memory=2000))
    mp = OUT / 'manifest.json'
    if mp.exists(): assert json.loads(mp.read_text()) == json.loads(json.dumps(man))
    else: mp.write_text(json.dumps(man, indent=2))
    rp = OUT / 'rows.jsonl'
    if not rp.exists():
        base = [json.loads(x) for x in src_raw.decode().splitlines()]
        keep = [dict(r, reused_from='bomb_memory_key_20261026') for r in base if r['phase'] in ('bombD', 'bombR', 'bombN') and r['option'] == 'baseline']
        tmp = rp.with_suffix('.tmp'); tmp.write_text(''.join(json.dumps(r) + '\n' for r in keep)); os.replace(tmp, rp)
    rows = [json.loads(x) for x in rp.read_text().splitlines()]
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); new = lambda: sum(r['games'] for r in rows if 'reused_from' not in r)

    def run(phase, opt, levels, n, seed, thetas=R.THETAS):
        for L in levels:
            for t in thetas:
                if (phase, opt, L, t) in done: continue
                free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
                if free < 500 or shutil.disk_usage(B).free < 10 * 1024 ** 3 or new() + n > MAX_GAMES or time.time() - start > 3600:
                    c.log('STOP', free, new()); return False
                rows.append(R.measure(phase, opt, L, t, n, seed)); done.add((phase, opt, L, t))
        return True

    if not run('regress', 'baseline', [293], 16, 18000000, [.85]): return
    reg = [r for r in rows if r['phase'] == 'regress'][0]
    if reg['wins'] != 7: c.log('REGRESS_MISMATCH', reg['wins']); return
    if not run('bombD', 'bomb_threat_memory', old['bomb_diag'], 16, 20000000): return
    D = {o: R.evaluate(rows, 'bombD', o, old['bomb_diag']) for o in ('baseline', 'bomb_threat_memory')}
    gate = D['bomb_threat_memory']['joint_mse'] < D['baseline']['joint_mse']; c.log('GATE', gate)
    if gate:
        if not run('bombR', 'bomb_threat_memory', old['bomb_diag'], 32, 21000000): return
        if not run('bombN', 'bomb_threat_memory', old['bomb_new'], 32, 22000000): return
        J.main(OUT)
    c.log('DONE', len(rows), new())


if __name__ == '__main__':
    main()
