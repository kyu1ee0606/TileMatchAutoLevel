"""Prespecified paired diagnostic comparison, no refit or server writes."""
import sys,json,time,hashlib,subprocess,re,shutil,os
from pathlib import Path
B=Path(__file__).resolve().parents[1];sys.path[:0]=[str(B),str(B/'scripts')]
import bot_grass_joint_fit_20261026 as core
LEVELS=[152,448,284,184,293,355]
THETAS=[.55,.65,.85,1.,1.2]
WEIGHTS=[0,.11643617331506148,.12554041128800084,0,.7580234153969376]
OUT=B/'data/pv_sandbox/af_calibration/public_planning_pair_20261026'
BASE=list(core.RULES)

def main():
    OUT.mkdir(parents=True,exist_ok=True);core.OUT=OUT
    source_hash=hashlib.sha256((B/'app/core/bot_simulator.py').read_bytes()).hexdigest()
    expected=os.environ.get('EXPECTED_BOT_SHA256')
    if expected and source_hash!=expected:raise RuntimeError('source hash mismatch')
    manifest=dict(levels=LEVELS,thetas=THETAS,weights=WEIGHTS,cap=.65,games_each=32,seedbase=13000000,
                  base=BASE,variant=BASE+['public_gimmick_planning'],source_hash=source_hash,
                  scope='previously observed diagnostic3 plus reference3; paired32, no independent validation or refitting',
                  maps={l:dict(hash=hashlib.sha256(json.dumps(core.P[l]['map'],sort_keys=True).encode()).hexdigest(),af=core.A[l],features=core.P[l]['features'])for l in LEVELS})
    if(OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==json.loads(json.dumps(manifest))
    else:core.save('manifest.json',manifest)
    rows=[json.loads(x)for x in(OUT/'rows.jsonl').read_text().splitlines()]if(OUT/'rows.jsonl').exists()else[]
    done={(r['split'],r['L'],r['theta'])for r in rows};assert len(done)==len(rows)
    spent=sum(r['sec']for r in rows);start=time.time();budget=float(os.environ.get('BOT_COMPUTE_BUDGET_SECONDS','900'))
    for l in LEVELS:
        for mode in['baseline','variant']:
            core.RULES=BASE+(['public_gimmick_planning']if mode=='variant'else[])
            for theta in THETAS:
                if(mode,l,theta)in done:continue
                free=float(re.search(r'free = ([0-9.]+)M',subprocess.check_output(['sysctl','vm.swapusage'],text=True))[1])
                if free<500 or shutil.disk_usage(B).free<10*1024**3 or spent+time.time()-start>budget:
                    core.log('STOP',free,spent+time.time()-start);return
                rows.append(core.measure(mode,l,theta,.65,32))
    result={}
    for mode in['baseline','variant']:
        dd={(r['L'],r['theta']):r for r in rows if r['split']==mode};out=[]
        for l in LEVELS:
            vectors=[core.vector(dd[l,t])for t in THETAS];p=[sum(w*v[j]for w,v in zip(WEIGHTS,vectors))for j in range(len(core.CATS))];a=core.target(l)
            tv=sum(abs(x/(1-p[0])-y/(1-a[0]))for x,y in zip(p[1:],a[1:]))/2 if p[0]<1-1e-12 and a[0]<1-1e-12 else None
            out.append(dict(L=l,predicted=p,actual=a,clear_error=p[0]-a[0],failure_tv=tv,
                            bots={t:dict(wins=dd[l,t]['wins'],games=32,reasons=dd[l,t]['fail_reasons'])for t in THETAS}))
        result[mode]=dict(rows=out,clear_mae=sum(abs(x['clear_error'])for x in out)/len(out),joint_mse=sum(sum((a-b)**2 for a,b in zip(x['predicted'],x['actual']))for x in out)/len(out)/len(core.CATS),
                          failure_tv=sum(x['failure_tv']for x in out if x['failure_tv']is not None)/sum(x['failure_tv']is not None for x in out))
    result.update(configs=len(rows),games=sum(r['games']for r in rows),seconds=sum(r['sec']for r in rows),source_hash=source_hash)
    core.save('summary.json',result);core.log('DONE',len(rows),result['games'],result['seconds'])
if __name__=='__main__':main()
