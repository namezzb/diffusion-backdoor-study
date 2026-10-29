"""Check the new prompts against all three pinned tokenizers, CPU only."""
from pathlib import Path
import datetime as dt,json,shlex,subprocess,sys,argparse
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'server'))
from stage_school_assets import SchoolSession
REMOTE=r"""
import os,pathlib,json,hashlib,sys,torch
from transformers import CLIPTokenizer
assert os.environ['CUDA_VISIBLE_DEVICES']==''
base=pathlib.Path(sys.argv[1]);code=base/'code/image-search-6913379cd01c'
assert str(base) in ['/data1/zhangzibo/arxiv-tssa','/data2/zhangzibo/arxiv-tssa']
p=code/'research/tssa_optimization_exploration_2026-10-28.json'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
plan=json.loads(p.read_text())
sys.path.insert(0,str(code/'scripts/merging'))
from tssa_sd_runtime import _check_tokenizers
prompt_texts=[row[key] for block in plan['stages'].values() for row in block['rows'] for key in ('prompt','normal_prompt')]
t=CLIPTokenizer.from_pretrained(str(base/'models/sd15/tokenizer'),local_files_only=True)
for name in ('dreamshaper8','openjourney'):
 other=CLIPTokenizer.from_pretrained(str(base/'models'/name/'tokenizer'),local_files_only=True)
 _check_tokenizers(t,other,prompt_texts,name)
rows=[]
for stage,block in plan['stages'].items():
 for row in block['rows']:
  for key in ('prompt','normal_prompt'):
   ids=t(row[key],truncation=False,add_special_tokens=True)['input_ids'];assert len(ids)<=77
   rows.append({'stage':stage,'id':row['id'],'kind':key,'token_length':len(ids)})
assert not torch.cuda.is_initialized()
print(json.dumps({'passed':True,'GPU_initialized':False,'scientific_images':0,'prompt_instances_checked':len(rows),'expert_tokenizer_equivalence':True,'maximum_token_length':max(r['token_length'] for r in rows),'rows':rows}))
"""
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--server',choices=['103','104'],default='104');args=parser.parse_args()
 base=('/data1' if args.server=='103' else '/data2')+'/zhangzibo/arxiv-tssa'
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');record={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'server':args.server,'scope':'new_prompt_tokenization_CPU_only'}
 try:
  with SchoolSession() as session:
   cmd=shlex.join(['env','CUDA_VISIBLE_DEVICES=','HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1','OMP_NUM_THREADS=2','PYTHONDONTWRITEBYTECODE=1',base+'/venv/bin/python','-B','-c',REMOTE,base])
   result=subprocess.run(['ssh','-F',str(session.config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','school'+args.server,cmd],capture_output=True,text=True,timeout=100)
   record.update(returncode=result.returncode,stderr=result.stderr[-2500:])
   if result.returncode:record['stdout']=result.stdout[-2500:]
   else:record['result']=json.loads(result.stdout)
 except Exception as error:record['error']=str(error)
 record['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
 path=OUT/('prompt_CPU_check_'+stamp+'.json')
 with path.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
 print(json.dumps({'path':str(path),**{k:v for k,v in record.items() if k!='result'},'result':{k:v for k,v in record.get('result',{}).items() if k!='rows'}},ensure_ascii=False))
if __name__=='__main__':main()
