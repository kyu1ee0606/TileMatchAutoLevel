"""Static artifact join only: no simulator, training or execution API imports."""
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
import af_level_metrics as af
from pv_scan_shards import decrypt_shard_file

CAL = af.OUT_DIR
OUT = CAL / 'refresh_20261019' / 'bot_join_verified.json'
KEYS = ('randSeed','useTileCount','unlockTile','shuffleTile','typeImbalance','autoCollectCount','timea','layer')
THETAS = {0.55,0.65,0.85,1.0}
ITEMS = {'unknown_hide','curtain_hide','unknown_nobonus','ac_inner','stack_hide','dock_rel'}

def load(p):
    return json.loads(p.read_text())

def shard(c,key):
    path=f'Assets/StreamingAssets/GBoost/a{hashlib.md5(key.encode()).hexdigest()}.txt'
    return decrypt_shard_file(subprocess.check_output(['git','-C',str(af.GAME_REPO),'show',f'{c}:{path}']))

def main():
    assert not OUT.exists(), 'Do not overwrite audit'
    inputs=['bot_v21/prep.json','bot_v24/prep.json','cand_a1a2/prep_ext.json',
            'bot_v24/bot_v2.4f_no_rules_only.json','cand_a1a2/bot_v24_rules_A2.json']
    prep={int(k):v for k,v in load(CAL/inputs[0]).items()}
    assert prep=={int(k):v for k,v in load(CAL/inputs[1]).items()}
    prep.update({int(k):v for k,v in load(CAL/inputs[2])['levels'].items()})
    bots=defaultdict(list)
    for name in inputs[3:]:
        for r in load(CAL/name)['rows']:
            bots[r['L']].append((name,r))
    snaps={}
    for commit in sorted(set(af.VERSION_SHARD_COMMIT.values())):
        maps={}
        for i in range(6): maps.update(shard(commit,f'levelmap_level_{i}'))
        tab=shard(commit,'levels')
        rows={}
        for v in tab['__vals']:
            r=dict(zip(tab['__keys'],v));rows[str(r.get('id'))]=r
        snaps[commit]=(maps,rows)
    refreshed=load(CAL/'refresh_20261019/summary.json')['levels']
    out=[]
    for a in refreshed:
        L=a['level']; candidates=bots.get(L,[]); p=prep.get(L)
        n=a['all_known']['combined']['n']; rate=a['all_known']['combined']['rate']
        if rate is None or rate>=.85: continue
        rec={'level':L,'af_n':n,'af_rate':rate,'af_new_n':a['all_known']['new']['n'],
             'editor_same_n':a['same']['combined']['n'],'sources':sorted({f for f,r in candidates}),
             'policy_exclusion':p['exclude'] if p else None,'versions':{},'bot_rows':len(candidates)}
        protocol=bool(candidates) and len(candidates)==4 and {r['theta'] for f,r in candidates}==THETAS
        # Ablation producer copies unaffected base rows. Their configuration labels
        # retain inactive flags; accept only when the triggering feature is absent.
        def flags_ok(r):
            flags=set(r.get('v24') or [])
            if not ITEMS<=flags or p is None:return False
            f=p['features']
            inactive={'ac_policy':float(p['row'].get('autoCollectCount') or 0)==0,
                'curtain_memory_v24':not f.get('eff_curtain'),
                'bomb_beta':not f.get('eff_bomb'),'bomb_impulse':not f.get('eff_bomb'),
                'stack_early':not f.get('stack'),'key_first':not f.get('key')}
            return all(inactive.get(flag,False) for flag in flags-ITEMS)
        protocol=protocol and all(r['games']==128 and 0<=r['wins']<=128 and
            r['ver']=='v2.4' and flags_ok(r) and
            all(r.get(k) is None for k in ('parity','psavvy','cmem','beta','extra')) for f,r in candidates)
        rec['protocol_complete']=protocol
        if p:
            h=af._map_hashes(p['map'])[0];rec['bot_map_sha256']=h
            rec['conditions_sha256']=hashlib.sha256(json.dumps(p['row'],sort_keys=True).encode()).hexdigest()
            for version,v in a['versions'].items():
                commit=v['commit'];maps,rows=snaps[commit];key=f'level_{L}'
                m=maps.get(key);r=rows.get(key,{})
                match=m is not None and af._map_hashes(m)[0]==h
                cond={k:r.get(k) for k in KEYS}==p['row']
                rec['versions'][version]={'map_match':match,'condition_match':cond,
                    'n':v['old_n']+v['new_n'],'new_n':v['new_n']}
        matched=sum(v['n'] for v in rec['versions'].values() if v['map_match'] and v['condition_match'])
        rec['matched_af_n']=matched
        if rec['policy_exclusion']: status='policy_excluded'
        elif not candidates: status='no_compatible_bot_result'
        elif not protocol: status='protocol_review'
        elif matched!=n: status='map_or_condition_review'
        elif rec['policy_exclusion']: status='policy_excluded'
        elif n<100: status='af_sample_below100'
        else: status='reusable_candidate'
        rec['status']=status
        rec['bot_rates']={str(r['theta']):r['wins']/r['games'] for f,r in candidates}
        out.append(rec)
    summary=dict(Counter(r['status'] for r in out))
    supported=[r for r in out if r['af_n']>=100]
    result={'scope':'AF first-try ended any-help <85%; stored v2.4 rules-only theta4x128 artifacts. No new games.',
        'provenance_limit':'Result rows lack embedded map hash; join is reconstructed from stored prep + producer code + Git shards. Not an immutable per-run attestation.',
        'inputs_sha256':{x:hashlib.sha256((CAL/x).read_bytes()).hexdigest() for x in inputs},
        'summary_all_low':summary,'summary_n100':dict(Counter(r['status'] for r in supported)),
        'levels':out}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='levels'},ensure_ascii=False,indent=2))
    for status in sorted(summary):print(status,[r['level'] for r in supported if r['status']==status])

if __name__=='__main__':main()
