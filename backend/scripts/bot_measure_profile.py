"""Shared bot measurement profile (doc 26 top, 2026-10-28): the SAME profile/cfg the AF-validation runners use.

Extracted from bot_drp_candidates_20261027.profile / bot_p2_prereg_20261027.measure (past runners are frozen, not edited).
New DDA scripts should call make_measure_profile(theta, level_no, level_data) instead of make_skill_profile(theta,'v2.4').

cfg items (all identical to the validation runners):
  v24            = list(V24_DEFAULT) + ['grass_skill_attention','hidden_common_samples'] + ['public_key_stack_plan']
                   (same list incl. the duplicates the runners' prior.BASE has; the rules are used as a set)
  grass_attention_cap = .65, FIXED (beta 4 / l0 .5 / tau 15), alpha / gamma = V21_AWARENESS_DEFAULTS, parity=None
  auto_collect   = level data 'autoCollectCount' (level row / editor level JSON; game DB_Level.cs xAutoCollectCount).
                   level_data without the key -> AF-cache row value (same source as the runners) -> else 0.
  exposure       = {'bomb','grass'}: count of earlier levels with eff_bomb/eff_grass (AF cache bot_v21/exposure.json)
  v24_expo       = {'grass','chain'}: same counts for eff_grass/eff_chain (bot_v24_eval._gc_expo)
Exposure outside the AF cache (L32..500, 469 levels) -- fallback rule (fixed before looking at any result):
  level_no < 32  -> all zeros (the cache docstring: no bomb/grass in L1..31; chain assumed the same)
  level_no > 500 -> cumulative counts after the last cached level (lower bound, no extrapolation)
  DDA variants use the ORIGINAL level number.
info['expo_source'] reports which rule applied.
"""
import sys, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_v24_eval as ev
from app.core.bot_simulator import V21_AWARENESS_DEFAULTS, V24_DEFAULT
from app.core.mc_difficulty import make_skill_profile

GRASS_CAP = .65
RULES = list(V24_DEFAULT) + ['grass_skill_attention', 'hidden_common_samples'] + ['public_key_stack_plan']
_T = {}


def _tables():
    if not _T:
        P, _ = ev.v21.prep()
        _T['P'] = P; _T['EX'] = ev._expo(); _T['GC'] = ev._gc_expo(P)
        cnt = Counter()
        for L in sorted(P):
            for g, f in (('grass', 'eff_grass'), ('chain', 'eff_chain'), ('bomb', 'eff_bomb')):
                if P[L]['features'].get(f, 0) > 0: cnt[g] += 1
        _T['END_EX'] = {'bomb': cnt['bomb'], 'grass': cnt['grass']}
        _T['END_GC'] = {'grass': cnt['grass'], 'chain': cnt['chain']}
        _T['LO'] = min(P); _T['HI'] = max(P)
    return _T


def exposure_for(level_no):
    t = _tables(); L = int(level_no)
    if L in t['EX'] and L in t['GC']: return dict(t['EX'][L]), dict(t['GC'][L]), 'cache'
    if L < t['LO']: return {'bomb': 0, 'grass': 0}, {'grass': 0, 'chain': 0}, 'below_cache_zero'
    return dict(t['END_EX']), dict(t['END_GC']), 'above_cache_end_counts'


def auto_collect_for(level_no, level_data=None):
    if level_data is not None and level_data.get('autoCollectCount') is not None:
        return int(float(level_data['autoCollectCount'] or 0)), 'level_data'
    row = _tables()['P'].get(int(level_no), {}).get('row')
    if row is not None: return int(float(row.get('autoCollectCount') or 0)), 'cache_row'
    return 0, 'default_0'


def make_measure_profile(theta, level_no, level_data=None):
    """-> (profile, info).  Same cfg and key order as the validation runners."""
    p = make_skill_profile(theta, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(ev.v21.FIXED)
    expo, gc, src = exposure_for(level_no); ac, ac_src = auto_collect_for(level_no, level_data)
    cfg.update(alpha=dict(V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(V21_AWARENESS_DEFAULTS['gamma']), exposure=expo, parity=None,
               auto_collect=ac, v24_expo=gc, v24=list(RULES), grass_attention_cap=GRASS_CAP)
    return dataclasses.replace(p, gimmick_awareness=cfg), dict(expo_source=src, auto_collect_source=ac_src)
