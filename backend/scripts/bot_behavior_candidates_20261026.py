"""Prespecified three independent behavioural hypotheses, fixed mixture, no refit."""
import sys,json,time,hashlib,subprocess,re,shutil,dataclasses,os
from pathlib import Path
from collections import Counter
B=Path(__file__).resolve().parents[1];sys.path[:0]=[str(B),str(B/'scripts')]
import bot_grass_joint_fit_20261026 as c
LEVELS=[152,448,284,184,293,355];THETAS=[.55,.65,.85,1.,1.2]
WEIGHTS=[0,.11643617331506148,.12554041128800084,0,.7580234153969376]
OPTIONS=['baseline','grass_risk_memory','public_goal_style','public_key_stack_plan']
OUT=B/'data/pv_sandbox/af_calibration/behavior_candidates_20261026'

def measure(phase,option,L,t,n):
 start=time.time();p=c.make_skill_profile(t,'v2.4');cfg=dict(p.gimmick_awareness);cfg.update(c.ev.v21.FIXED)
 cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']),gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']),exposure=c.EX[L],parity=None,auto_collect=int(float(c.P[L]['row'].get('autoCollectCount')or 0)),v24_expo=c.ev._gc_expo(c.P)[L],v24=c.RULES+([]if option=='baseline'else[option]),grass_attention_cap=.65)
 p=dataclasses.replace(p,gimmick_awareness=cfg);b=c.BotSimulator();b.set_rule_parity(p)
 layout=c.ev.base.level_layouts(c.P[L],1)[0];st=b._create_initial_state(layout,int(layout['max_moves']));b._precompute_blocking_map(st)
 wins=0;reasons=Counter();seedbase=14000000 if phase=='discovery' else 15000000
 for g in range(n):
  b._rng.seed(seedbase+g);end=b._play_game(b._fast_copy_state(st),p)
  if end.cleared:wins+=1
  else:reasons[c.ev.base.fail_reason(b,end)]+=1
 row=dict(phase=phase,option=option,L=L,theta=t,games=n,wins=wins,fail_reasons=dict(reasons),seedbase=seedbase,sec=time.time()-start)
 with(OUT/'rows.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')
 c.log('ROW',phase,option,L,t,wins,n,round(row['sec'],2));return row

def evaluate(rows,phase,option):
 d={(r['L'],r['theta']):r for r in rows if r['phase']==phase and r['option']==option};out=[]
 for L in LEVELS:
  vectors=[c.vector(d[L,t])for t in THETAS];p=[sum(w*v[j]for w,v in zip(WEIGHTS,vectors))for j in range(len(c.CATS))];a=c.target(L)
  out.append(dict(L=L,predicted=p,actual=a,clear_error=p[0]-a[0],joint_mse=sum((x-y)**2 for x,y in zip(p,a))/len(c.CATS),failure_tv=sum(abs(x/(1-p[0])-y/(1-a[0]))for x,y in zip(p[1:],a[1:]))/2 if p[0]<1 and a[0]<1 else None))
 return dict(rows=out,diagnostic_joint_mse=sum(x['joint_mse']for x in out[:3])/3,reference_joint_mse=sum(x['joint_mse']for x in out[3:])/3,clear_mae=sum(abs(x['clear_error'])for x in out)/6)

def main():
 OUT.mkdir(parents=True,exist_ok=True);c.OUT=OUT
 sha=hashlib.sha256((B/'app/core/bot_simulator.py').read_bytes()).hexdigest()
 assert sha==os.environ['EXPECTED_BOT_SHA256']
 manifest=dict(source_hash=sha,levels=LEVELS,thetas=THETAS,weights=WEIGHTS,options=OPTIONS,cap=.65,base_rules=c.RULES,discovery_games=16,confirmation_games=32,seeds=[14000000,15000000],selection='diagnostic first3 jointMSE only; reference3 not selection; fixed weights; select single only if improves baseline',memory='globalattention TTL2..5 retention.55...85; fresh awareness only recharges',style='public main container impact only .5/1.5 at run start copied RNG',key='noCraft key_locks public hiddenkey=3*locked-visibleboardanddockkey; impossiblefallback',maps={L:dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'],sort_keys=True).encode()).hexdigest(),af=c.A[L])for L in LEVELS})
 if(OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==json.loads(json.dumps(manifest))
 else:c.save('manifest.json',manifest)
 rows=[json.loads(x)for x in(OUT/'rows.jsonl').read_text().splitlines()]if(OUT/'rows.jsonl').exists()else[]
 done={(r['phase'],r['option'],r['L'],r['theta'])for r in rows};assert len(done)==len(rows)
 spent=sum(r['sec']for r in rows);start=time.time()
 for phase in ['discovery','confirmation']:
  if phase=='confirmation':
   discovery={o:evaluate(rows,'discovery',o)for o in OPTIONS};c.save('discovery.json',discovery)
   best=min(OPTIONS,key=lambda o:discovery[o]['diagnostic_joint_mse'])
   selected=dict(option=best,weights=WEIGHTS,source_hash=sha,losses={o:discovery[o]['diagnostic_joint_mse']for o in OPTIONS})
   if(OUT/'selected.json').exists():assert json.loads((OUT/'selected.json').read_text())==selected
   else:c.save('selected.json',selected)
   c.log('SELECTED',best,selected['losses'])
   if best=='baseline':c.save('summary.json',dict(discovery=discovery,selected=selected,no_adoption=True));return
   opts=['baseline',best];n=32
  else:opts=OPTIONS;n=16
  for L in LEVELS:
   for option in opts:
    for t in THETAS:
     if(phase,option,L,t)in done:continue
     free=float(re.search(r'free = ([\d.]+)M',subprocess.check_output(['sysctl','vm.swapusage'],text=True))[1])
     if free<500 or shutil.disk_usage(B).free<10*1024**3 or spent+time.time()-start>1800:
      c.log('STOP',free,spent+time.time()-start);return
     rows.append(measure(phase,option,L,t,n))
 confirmation={o:evaluate(rows,'confirmation',o)for o in opts}
 c.save('summary.json',dict(discovery=discovery,selected=selected,confirmation=confirmation,settings=len(rows),games=sum(r['games']for r in rows),seconds=sum(r['sec']for r in rows)));c.log('DONE',len(rows))
if __name__=='__main__':main()
