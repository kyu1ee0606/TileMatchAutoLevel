"""Local, resumable prespecified clean-AF joint calibration; no remote writes."""
import sys, json, time, re, subprocess, shutil, hashlib, dataclasses, math, os
from pathlib import Path
from collections import Counter

B = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(B), str(B / 'scripts')]
import bot_v24_eval as ev
from app.core.bot_simulator import BotSimulator, V21_AWARENESS_DEFAULTS, V24_DEFAULT
from app.core.mc_difficulty import make_skill_profile
from bot_af_L1_31 import spearman

OUT = B / 'data/pv_sandbox/af_calibration/grass_joint_20261026_145752'
TRAIN = [151,184,241,293,51,81,343,442,68,133,164,209,324,396,224,276]
HOLD = [102,354,182,315,355,448,251,382,152,284]
THETAS = [.55,.65,.85,1.,1.2]
CAPS = [.45,.65,.9]
CATS = ['clear','Grass','Bomb','Normal','other','unknown']
RULES = list(V24_DEFAULT) + ['grass_skill_attention','hidden_common_samples']
P,A = ev.v21.prep()
EX = ev._expo()

def save(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2))

def log(*args):
    msg = ' '.join(map(str,args)); print(msg,flush=True)
    with (OUT/'progress.log').open('a') as f: f.write(msg+'\n')

def bucket(s):
    if s.startswith('Grass'): return 'Grass'
    return s if s in ('Bomb','Normal') else 'other'

def target(L):
    a=A[L]; n=a['clean_ft_n']; clear=a['clean_ft_rate']
    reasons=Counter()
    for k,v in a.get('fail_reason',{}).items(): reasons[bucket(k)]+=v
    failure=max(0.,1-clear); known=sum(reasons.values())
    # AF rates are rounded; tolerate rounding, not actual missing failure logs.
    coverage=min(1.,known/(n*failure)) if failure else 1.
    if abs(known-n*failure)<.51: coverage=1.
    return [clear]+[failure*coverage*reasons[k]/known if known else 0. for k in CATS[1:-1]]+[failure*(1-coverage)]

def canonical_cap(L,t,cap):
    return .9 if t==.55 or not P[L]['features'].get('eff_grass') else cap

def key(split,L,t,cap): return (split,L,t,canonical_cap(L,t,cap))

def measure(split,L,t,cap,games):
    start=time.time(); prof=make_skill_profile(t,'v2.4')
    cfg=dict(prof.gimmick_awareness); cfg.update(ev.v21.FIXED)
    cfg.update(alpha=dict(V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(V21_AWARENESS_DEFAULTS['gamma']),
               exposure=EX[L], parity=None, auto_collect=int(float(P[L]['row'].get('autoCollectCount')or 0)),
               v24_expo=ev._gc_expo(P)[L],v24=RULES,grass_attention_cap=cap)
    prof=dataclasses.replace(prof,gimmick_awareness=cfg)
    b=BotSimulator(); b.set_rule_parity(prof)
    layout=ev.base.level_layouts(P[L],1)[0]
    st=b._create_initial_state(layout,int(layout['max_moves']));b._precompute_blocking_map(st)
    wins=0;reasons=Counter();seedbase=12000000 if split=='train' else 13000000
    for g in range(games):
        b._rng.seed(seedbase+g)
        end=b._play_game(b._fast_copy_state(st),prof)
        if end.cleared:wins+=1
        else:reasons[ev.base.fail_reason(b,end)]+=1
    row=dict(split=split,L=L,theta=t,cap=cap,games=games,wins=wins,fail_reasons=dict(reasons),seedbase=seedbase,sec=time.time()-start)
    with(OUT/'rows.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')
    log('ROW',split,L,t,cap,wins,games,dict(reasons),round(row['sec'],2))
    return row

def vector(r):
    c=Counter()
    for k,v in r['fail_reasons'].items():c[bucket(k)]+=v
    return [r['wins']/r['games']]+[c[x]/r['games']for x in CATS[1:]]

def simplex_fit(X,Y):
    # Convex joint MSE, projected gradient on the five-weight simplex.
    n=len(Y); H=[[sum(row[i]*row[j]for row in X)/n for j in range(5)]for i in range(5)]
    c=[sum(row[i]*y for row,y in zip(X,Y))/n for i in range(5)]
    step=1/max(2*max(sum(abs(v)for v in row)for row in H),1e-9);w=[.2]*5
    for _ in range(20000):
        v=[w[i]-step*2*(sum(H[i][j]*w[j]for j in range(5))-c[i])for i in range(5)]
        u=sorted(v,reverse=True);rho=max(i for i in range(5)if u[i]-(sum(u[:i+1])-1)/(i+1)>0)
        threshold=(sum(u[:rho+1])-1)/(rho+1);nw=[max(x-threshold,0)for x in v]
        if max(abs(x-y)for x,y in zip(w,nw))<1e-11:w=nw;break
        w=nw
    loss=sum((sum(a*b for a,b in zip(row,w))-y)**2 for row,y in zip(X,Y))/n
    return w,loss

def evaluate(rows,split,levels,cap,weights):
    out=[]
    for L in levels:
        vv=[vector(rows[key(split,L,t,cap)])for t in THETAS]
        pred=[sum(w*v[j]for w,v in zip(weights,vv))for j in range(len(CATS))];actual=target(L)
        af=A[L];out.append(dict(L=L,predicted=pred,actual=actual,clean_n=af['clean_ft_n'],fail_n=sum(af.get('fail_reason',{}).values()),
                               bounds=[af['unaided_clear_lower_bound'],af['unaided_clear_upper_bound']],features=P[L]['features']))
    mse=sum(sum((a-b)**2 for a,b in zip(r['predicted'],r['actual']))for r in out)/(len(out)*len(CATS))
    return dict(rows=out,joint_mse=mse,clear_mae=sum(abs(r['predicted'][0]-r['actual'][0])for r in out)/len(out),
                midpoint_mae=sum(abs(r['predicted'][0]-sum(r['bounds'])/2)for r in out)/len(out),
                clear_rho=spearman([r['predicted'][0]for r in out],[r['actual'][0]for r in out]))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source_hash=hashlib.sha256((B/'app/core/bot_simulator.py').read_bytes()).hexdigest()
    manifest=dict(train=TRAIN,holdout=HOLD,thetas=THETAS,caps=CAPS,categories=CATS,rules=RULES,train_games=16,holdout_games=64,
                  train_seedbase=12000000,holdout_seedbase=13000000,source_hash=source_hash,af_date='2026-10-14',
                  selection='previous diagnostic4 + previous coverage4; new16 by mechanic-stratum level quantiles20/40/60/80, train20/60 holdout40/80; fixed n>=100, previous24 excluded from new16; before new simulations add holdout152/284 for adequate observed grass-failure sample sizes',
                  maps={L:dict(hash=hashlib.sha256(json.dumps(P[L]['map'],sort_keys=True).encode()).hexdigest(),features=P[L]['features'],af=A[L])for L in TRAIN+HOLD})
    if(OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==json.loads(json.dumps(manifest))
    else:save('manifest.json',manifest)
    rowslist=[json.loads(x)for x in(OUT/'rows.jsonl').read_text().splitlines()]if(OUT/'rows.jsonl').exists()else[]
    rows={key(r['split'],r['L'],r['theta'],r['cap']):r for r in rowslist};assert len(rows)==len(rowslist)
    start=time.time();spent=sum(r['sec']for r in rowslist)
    def ensure(split,L,t,cap,games):
        k=key(split,L,t,cap)
        if k in rows:return
        free=float(re.search(r'free = ([0-9.]+)M',subprocess.check_output(['sysctl','vm.swapusage'],text=True))[1])
        if free<500 or shutil.disk_usage(B).free<10*1024**3 or spent+time.time()-start>float(os.environ.get('BOT_COMPUTE_BUDGET_SECONDS','720')):
            log('STOP',free,round(spent+time.time()-start,2));sys.exit(0)
        rows[k]=measure(split,L,t,k[3],games)
    for L in TRAIN:
        for cap in CAPS:
            for t in THETAS:ensure('train',L,t,cap,16)
    if(OUT/'selected.json').exists():selected=json.loads((OUT/'selected.json').read_text())
    else:
        candidates=[]
        for cap in CAPS:
            X=[];Y=[]
            for L in TRAIN:
                vv=[vector(rows[key('train',L,t,cap)])for t in THETAS]
                for j,y in enumerate(target(L)):X.append([v[j]for v in vv]);Y.append(y)
            weights,loss=simplex_fit(X,Y);candidates.append(dict(cap=cap,weights=weights,train_joint_mse=loss))
        selected=dict(selected=min(candidates,key=lambda x:x['train_joint_mse']),candidates=candidates,locked_before_holdout=True)
        save('selected.json',selected);log('SELECTED',json.dumps(selected))
    cap=selected['selected']['cap'];weights=selected['selected']['weights']
    for L in HOLD:
        for t in THETAS:ensure('holdout',L,t,cap,64)
        ensure('holdout',L,1.2,.9,64)
    baseline=[.178187799,0,0,0,.821812201]
    # Baseline only needs two profiles; fill unrelated slots with their selected-cap rows (zero weights).
    baseline_rows=dict(rows)
    for L in HOLD:
        for t in THETAS[1:-1]:baseline_rows[key('holdout',L,t,.9)]=rows[key('holdout',L,t,cap)]
    summary=dict(selected=selected,train=evaluate(rows,'train',TRAIN,cap,weights),holdout=evaluate(rows,'holdout',HOLD,cap,weights),
                 holdout_equal=evaluate(rows,'holdout',HOLD,cap,[.2]*5),holdout_previous_fixed=evaluate(baseline_rows,'holdout',HOLD,.9,baseline),
                 configs=len(rows),games=sum(r['games']for r in rows.values()),seconds=sum(r['sec']for r in rows.values()))
    save('summary.json',summary);log('DONE',summary['configs'],summary['games'],round(summary['seconds'],2))

if __name__=='__main__':main()
