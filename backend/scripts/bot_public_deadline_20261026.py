"""Two public-feature corrections; fixed mixture; prespecified map holdout."""
import sys,json,time,hashlib,subprocess,re,shutil,dataclasses,os
from pathlib import Path
from collections import Counter
B=Path(__file__).resolve().parents[1];sys.path[:0]=[str(B),str(B/'scripts')]
import bot_grass_joint_fit_20261026 as c
DIAG=[152,284,293];REF=[184,355];HOLD=[153,161,294,449]
THETAS=[.55,.65,.85,1.,1.2];WEIGHTS=[0,.11643617331506148,.12554041128800084,0,.7580234153969376]
OPTIONS=['baseline','public_container_live_value','public_bomb_deadline']
OUT=B/'data/pv_sandbox/af_calibration/public_deadline_20261026'
BASE=c.RULES+['public_key_stack_plan']

def measure(phase,option,L,t,n):
 start=time.time();p=c.make_skill_profile(t,'v2.4');cfg=dict(p.gimmick_awareness);cfg.update(c.ev.v21.FIXED)
 rules=c.RULES if option=='key_off' else BASE+([]if option=='baseline'else[option])
 cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']),gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']),exposure=c.EX[L],parity=None,auto_collect=int(float(c.P[L]['row'].get('autoCollectCount')or 0)),v24_expo=c.ev._gc_expo(c.P)[L],v24=rules,grass_attention_cap=.65)
 p=dataclasses.replace(p,gimmick_awareness=cfg);b=c.BotSimulator();b.set_rule_parity(p)
 layout=c.ev.base.level_layouts(c.P[L],1)[0];st=b._create_initial_state(layout,int(layout['max_moves']));b._precompute_blocking_map(st)
 wins=0;reasons=Counter();seedbase=16000000 if phase=='discovery' else 17000000
 for g in range(n):
  b._rng.seed(seedbase+g);end=b._play_game(b._fast_copy_state(st),p)
  if end.cleared:wins+=1
  else:reasons[c.ev.base.fail_reason(b,end)]+=1
 row=dict(phase=phase,option=option,L=L,theta=t,games=n,wins=wins,fail_reasons=dict(reasons),seedbase=seedbase,sec=time.time()-start)
 with(OUT/'rows.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')
 c.log('ROW',phase,option,L,t,wins,n,round(row['sec'],2));return row

def evaluate(rows,phase,option,levels):
 d={(r['L'],r['theta']):r for r in rows if r['phase']==phase and r['option']==option};out=[]
 for L in levels:
  vs=[c.vector(d[L,t])for t in THETAS];p=[sum(w*v[j]for w,v in zip(WEIGHTS,vs))for j in range(len(c.CATS))];a=c.target(L)
  out.append(dict(L=L,predicted=p,actual=a,clear_error=p[0]-a[0],joint_mse=sum((x-y)**2 for x,y in zip(p,a))/len(c.CATS),failure_tv=sum(abs(x/(1-p[0])-y/(1-a[0]))for x,y in zip(p[1:],a[1:]))/2 if p[0]<1 and a[0]<1 else None))
 return dict(rows=out,joint_mse=sum(x['joint_mse']for x in out)/len(out),clear_mae=sum(abs(x['clear_error'])for x in out)/len(out))

def main():
 OUT.mkdir(parents=True,exist_ok=True);c.OUT=OUT;sha=hashlib.sha256((B/'app/core/bot_simulator.py').read_bytes()).hexdigest();assert sha==os.environ['EXPECTED_BOT_SHA256']
 manifest=dict(source_hash=sha,diagnostic=DIAG,references=REF,holdout=HOLD,thetas=THETAS,weights=WEIGHTS,options=OPTIONS,base=BASE,cap=.65,selection='diagnostic3jointMSEonly; tiebaseline; no combination/refit',seeds=[16000000,17000000],games=dict(discovery=16,diagnostic_confirmation=16,holdout=32,key_off_L153_theta12=32),scope='holdout selected using only mapfeatures/n; all prior AF was historically exposed; not population trial',maps={L:dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'],sort_keys=True).encode()).hexdigest(),mode=c.P[L]['mode'],features=c.P[L]['features'],af=c.A[L])for L in DIAG+REF+HOLD})
 if(OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==json.loads(json.dumps(manifest))
 else:c.save('manifest.json',manifest)
 rows=[json.loads(x)for x in(OUT/'rows.jsonl').read_text().splitlines()]if(OUT/'rows.jsonl').exists()else[]
 done={(r['phase'],r['option'],r['L'],r['theta'])for r in rows};assert len(done)==len(rows)
 spent=sum(r['sec']for r in rows);start=time.time()
 def run(phase,options,levels,n,thetas=THETAS):
  for L in levels:
   for option in options:
    for t in thetas:
     if(phase,option,L,t)in done:continue
     free=float(re.search(r'free = ([\d.]+)M',subprocess.check_output(['sysctl','vm.swapusage'],text=True))[1])
     if free<500 or shutil.disk_usage(B).free<10*1024**3 or spent+time.time()-start>1800:
      c.log('STOP',free,spent+time.time()-start);return False
     rows.append(measure(phase,option,L,t,n))
  return True
 if not run('discovery',OPTIONS,DIAG+REF,16):return
 discovery={o:evaluate(rows,'discovery',o,DIAG)for o in OPTIONS};c.save('discovery.json',discovery)
 best=min(OPTIONS,key=lambda o:discovery[o]['joint_mse']);selected=dict(option=best,weights=WEIGHTS,losses={o:discovery[o]['joint_mse']for o in OPTIONS},source_hash=sha)
 if(OUT/'selected.json').exists():assert json.loads((OUT/'selected.json').read_text())==selected
 else:c.save('selected.json',selected)
 c.log('SELECTED',best,selected['losses']);opts=['baseline'] if best=='baseline' else ['baseline',best]
 if not run('confirmation',opts,DIAG,16):return
 if not run('holdout',opts,HOLD,32):return
 if not run('holdout',['key_off'],[153],32,[1.2]):return
 # Lower four skill tiers have no rollout and hence key belief has no effect.
 copied=[dict(r,option='key_off') for r in rows if r['phase']=='holdout' and r['option']=='baseline' and r['L']==153 and r['theta']!=1.2]
 summary=dict(discovery=discovery,selected=selected,reference_discovery={o:evaluate(rows,'discovery',o,REF)for o in OPTIONS},confirmation={o:evaluate(rows,'confirmation',o,DIAG)for o in opts},holdout={o:evaluate(rows,'holdout',o,HOLD)for o in opts},key_off_153=evaluate(rows+copied,'holdout','key_off',[153]),settings=len(rows),games=sum(r['games']for r in rows),seconds=sum(r['sec']for r in rows))
 c.save('summary.json',summary);c.log('DONE',len(rows))
if __name__=='__main__':main()
