"""Doc 67: random-layout craft maps — why does B' (current default, core 39d2de55) under-succeed?  Diagnostic only.

Part T (trace, strong parity): B' on L208 (16 layouts x 2) and L149 (16 x 1), theta 1.2, seed 65M + layout*1000 + g.
  Per pick: whether the theta>1 search actually ran (rollout value computed) or fell back (determinize refused because
  an unspawned craft tile remains); for non-match picks with dock risk >= 4: chosen class (pair / new single), the
  chosen type's other copies by location (accessible now / covered on board / craft box unspawned / stack inner),
  and how many alternative non-match candidates had an accessible partner or formed a pair.
Part C (contrast, no trace): theta 1.2 x 32 games (16 layouts x 2), seed 66M, maps 208, 149, 256, 239:
  B' / B'+P2 (public_craft_belief: unspawned craft contents sampled from the public remain counter, existing option)
  / B'-HCS (hidden_common_samples off: legacy rollouts on the real board = upper bound with full craft knowledge).
  Plus L208 theta .85 x 32 for the same three cells.
Part T2 (added): human-hypothesis metrics, B' thetas .65/.85/1.2 on L208/L149 (see part_t2).
Part C trimmed to maps 208/149/256 at theta 1.2 (budget). Rows already written before the change are kept
(trace_rows.jsonl lacks the per-pick free/stack/craft fields, which were added for T2).
Guard + STOP flag. Writes OUT/trace_rows.jsonl, OUT/trace2_rows.jsonl, OUT/contrast_rows.jsonl.
"""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_layouts_util_20261027 as LU
import trace_parity_20261026 as TP
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/craft_diag_20261027'
BASE = list(R.prior.BASE)
CELLS = {"B'": BASE, 'P2': BASE + ['public_craft_belief'], 'HCS-': [x for x in BASE if x != 'hidden_common_samples']}


class Diag(c.BotSimulator):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.plog = []; self._search_calls = 0; self._search_none = 0

    def _v2_rollout_value(self, state, move, profile, rollout_seeds=None):
        v = super()._v2_rollout_value(state, move, profile, rollout_seeds)
        self._search_calls += 1
        if v is None: self._search_none += 1
        return v

    def _where(self, state, tt, acc_keys, exclude):
        cnt = Counter()
        on_board = set()
        for lay in state.tiles.values():
            for t in lay.values():
                on_board.add(id(t))
                if t.picked or t.tile_type != tt or t is exclude: continue
                cnt['accessible' if t.full_key in acc_keys else 'covered'] += 1
        for t in state.stacked_tiles.values():
            if t.picked or t.tile_type != tt or id(t) in on_board or t is exclude: continue
            cnt['craft_box' if (t.is_craft_tile and not t.is_crafted) else 'stack_inner'] += 1
        return cnt

    def _select_move_with_profile(self, moves, state, profile):
        c0, n0 = self._search_calls, self._search_none
        sel = super()._select_move_with_profile(moves, state, profile)
        if sel is None: return sel
        searched = self._search_calls > c0; refused = self._search_none > n0
        ts = sel.tile_state
        rec = dict(searched=searched, refused=refused, match=sel.will_match, occ=len(state.dock_tiles),
                   free=state.max_dock_slots - len(state.dock_tiles),
                   stack=bool(ts and ts.is_stack_tile and not ts.is_craft_tile), craft=bool(ts and ts.is_craft_tile))
        dc = len(state.dock_tiles) + (self._v24_dock_shift(state) if self._v24 else 0)
        if dc >= 4 and not sel.will_match:
            dock = Counter(t.tile_type for t in state.dock_tiles)
            acc = {m.tile_state.full_key for m in moves if m.tile_state is not None}
            w = self._where(state, sel.tile_type, acc, sel.tile_state)
            alts = [m for m in moves if not m.will_match and m is not sel and m.tile_state is not None]
            rec.update(cls='pair' if dock.get(sel.tile_type, 0) == 1 else 'new', where=dict(w),
                       alt_n=len(alts), alt_pair=sum(1 for m in alts if dock.get(m.tile_type, 0) == 1),
                       alt_access=sum(1 for m in alts if self._where(state, m.tile_type, acc, m.tile_state)['accessible'] > 0))
        self.plog.append(rec)
        return sel


def prof(L, t, v24):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=v24, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def part_t():
    out = OUT / 'trace_rows.jsonl'
    done = {(r['L'], r['layout'], r['g']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L, per in ((208, 2), (149, 1)):
        plan = LU.layouts_for(c, L, 16 * per); p = prof(L, 1.2, CELLS["B'"])
        for li, (lay, ng, lseed) in enumerate(plan):
            for g in range(ng):
                if (L, lseed, g) in done: continue
                if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return False
                b = TP.recorder(Diag)(); b.set_rule_parity(p)
                st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
                b._rng.seed(65000000 + li * 1000 + g); end = b._play_game(b._fast_copy_state(st), p)
                pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                ps = pb._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); pb._precompute_blocking_map(ps)
                pb._rng.seed(65000000 + li * 1000 + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                if not ok: print('PARITY_FAIL', L, lseed, g, detail, flush=True); sys.exit(2)
                row = dict(L=L, layout=lseed, g=g, cat=c.ev.base.fail_reason(b, end), cleared=end.cleared,
                           tiles_left=sum(1 for l2 in end.tiles.values() for t in l2.values() if not t.picked), plog=b.plog, parity='strong')
                with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        print('TRACE', L, flush=True)
    return True


def part_c():
    out = OUT / 'contrast_rows.jsonl'
    done = {(r['L'], r['cell'], r['theta']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    jobs = [(L, 1.2) for L in (208, 149, 256)]   # trimmed 2026-10-27 (budget <= 700 incl. trace v2): 239 and L208 theta .85 dropped
    for L, t in jobs:
        plan = LU.layouts_for(c, L, 32)
        for cell, v24 in CELLS.items():
            if (L, cell, t) in done: continue
            if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return
            p = prof(L, t, v24); w = 0; fr = Counter(); left = []; calls = none = 0
            for li, (lay, ng, _) in enumerate(plan):
                b = Diag(); b.set_rule_parity(p)
                st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
                for g in range(ng):
                    b._rng.seed(66000000 + li * 1000 + g); e = b._play_game(b._fast_copy_state(st), p)
                    if e.cleared: w += 1
                    else: fr[c.ev.base.fail_reason(b, e)] += 1; left.append(sum(1 for l2 in e.tiles.values() for x in l2.values() if not x.picked))
                calls += b._search_calls; none += b._search_none
            row = dict(L=L, cell=cell, theta=t, games=32, wins=w, fail=dict(fr), tiles_left=sorted(left), rollout_calls=calls, rollout_refused=none)
            with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
            print(row, flush=True)
    print('DONE', flush=True)


def part_t2():
    """Human-hypothesis metrics (added 2026-10-27): B' on L208 / L149, thetas .65 / .85 / 1.2, 16 layouts x 1 game,
    seed 67M; per pick free slots / stack / craft / match always recorded. Strong parity replay."""
    out = OUT / 'trace2_rows.jsonl'
    done = {(r['L'], r['theta'], r['layout']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L in (208, 149):
        plan = LU.layouts_for(c, L, 16)
        for t in (.65, .85, 1.2):
            p = prof(L, t, CELLS["B'"])
            for li, (lay, ng, lseed) in enumerate(plan):
                if (L, t, lseed) in done: continue
                if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return False
                b = TP.recorder(Diag)(); b.set_rule_parity(p)
                st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
                b._rng.seed(67000000 + li * 1000); end = b._play_game(b._fast_copy_state(st), p)
                pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                ps = pb._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); pb._precompute_blocking_map(ps)
                pb._rng.seed(67000000 + li * 1000); pe = pb._play_game(pb._fast_copy_state(ps), p)
                ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                if not ok: print('PARITY_FAIL', L, t, lseed, detail, flush=True); sys.exit(2)
                row = dict(L=L, theta=t, layout=lseed, cat=c.ev.base.fail_reason(b, end), cleared=end.cleared,
                           tiles_left=sum(1 for l2 in end.tiles.values() for x in l2.values() if not x.picked), plog=b.plog, parity='strong')
                with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
            print('TRACE2', L, t, flush=True)
    return True


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    if part_t() and part_t2(): part_c()
