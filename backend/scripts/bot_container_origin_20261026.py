"""A2 corrected origin lookup, prespecified 7-map paired comparison; no refit."""
import sys,json,time,hashlib,subprocess,re,shutil,dataclasses,os
from pathlib import Path
from collections import Counter
B=Path(__file__).resolve().parents[1];sys.path[:0]=[str(B),str(B/'scripts')]
import bot_public_deadline_20261026 as prior
c=prior.c;THETAS=prior.THETAS;DIAG=prior.DIAG;HOLD=prior.HOLD
OUT=B/'data/pv_sandbox/af_calibration/container_origin_20261026'
OPTIONS=['baseline','public_container_origin_value']
def measure(option,L,t,n):
 start=time.time();p=c.make_skill_profile(t,'v2.4');cfg=dict(p.gimmick_awareness);cfg.update(c.ev.v21.FIXED)
 rules=c.RULES if option=='key_off' else prior.BASE+([]if option=='baseline'else[option])
 cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']),gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']),exposure=c.EX[L],parity=None,auto_collect=int(float(c.P[L]['row'].get('autoCollectCount')or 0)),v24_expo=c.ev._gc_expo(c.P)[L],v24=rules,grass_attention_cap=.65)
 p=dataclasses.replace(p,gimmick_awareness=cfg);b=c.BotSimulator();b.set_rule_parity(p)
 layout=c.ev.base.level_layouts(c.P[L],1)[0];st=b._create_initial_state(layout,int(layout['max_moves']));b._precompute_blocking_map(st)
 wins=0;reasons=Counter()
 for g in range(n):
  b._rng.seed(18000000+g);end=b._play_game(b._fast_copy_state(st),p)
  if end.cleared:wins+=1
  else:reasons[c.ev.base.fail_reason(b,end)]+=1
 row=dict(phase='paired',option=option,L=L,theta=t,games=n,wins=wins,fail_reasons=dict(reasons),seedbase=18000000,sec=time.time()-start)
 with(OUT/'rows.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')
 c.log('ROW',option,L,t,wins,n,round(row['sec'],2));return row
def main():
 OUT.mkdir(parents=True,exist_ok=True);c.OUT=OUT
 sha=hashlib.sha256((B/'app/core/bot_simulator.py').read_bytes()).hexdigest();assert sha==os.environ['EXPECTED_BOT_SHA256']
 manifest=dict(source_hash=sha,diagnostic=DIAG,holdout=HOLD,options=OPTIONS,thetas=THETAS,weights=prior.WEIGHTS,seed=18000000,games=16,key_off_L153_theta12_games=16,base=prior.BASE,cap=.65,scope='A1 origin identity defect corrected; new experiment, no outcome-based retuning; same maps prespecified before A1 results; historical AF exposure acknowledged',maps={L:dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'],sort_keys=True).encode()).hexdigest(),af=c.A[L],features=c.P[L]['features'])for L in DIAG+HOLD})
 if(OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==json.loads(json.dumps(manifest))
 else:c.save('manifest.json',manifest)
 rows=[json.loads(x)for x in(OUT/'rows.jsonl').read_text().splitlines()]if(OUT/'rows.jsonl').exists()else[]
 done={(r['option'],r['L'],r['theta'])for r in rows};assert len(done)==len(rows)
 spent=sum(r['sec']for r in rows);start=time.time()
 settings=[(o,L,t)for L in DIAG+HOLD for o in OPTIONS for t in THETAS]+[('key_off',153,1.2)]
 for o,L,t in settings:
  if(o,L,t)in done:continue
  free=float(re.search(r'free = ([\d.]+)M',subprocess.check_output(['sysctl','vm.swapusage'],text=True))[1])
  if free<500 or shutil.disk_usage(B).free<10*1024**3 or spent+time.time()-start>1800:c.log('STOP',free);return
  rows.append(measure(o,L,t,16))
 copied=[dict(r,option='key_off')for r in rows if r['option']=='baseline' and r['L']==153 and r['theta']!=1.2]
 summary=dict(diagnostic={o:prior.evaluate(rows,'paired',o,DIAG)for o in OPTIONS},holdout={o:prior.evaluate(rows,'paired',o,HOLD)for o in OPTIONS},key_off_153=prior.evaluate(rows+copied,'paired','key_off',[153]),settings=len(rows),games=sum(r['games']for r in rows),seconds=sum(r['sec']for r in rows))
 c.save('summary.json',summary);c.log('DONE',len(rows))
if __name__=='__main__':main()
