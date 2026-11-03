// Local finite batch job for the user's explicitly requested 2026 collection.
// This is part of the collection pipeline, not a scheduled notification service.
import fs from 'node:fs/promises';
import {openSync,closeSync} from 'node:fs';
import path from 'node:path';
import {spawn,execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const support=path.dirname(fileURLToPath(import.meta.url));
const repo='E:/CAICTBigData/coding';
const root=repo+'/outputs/national-ggzy-medical-digital-2026-20261028';
const python='D:/Anaconda3/envs/BigData/python.exe';
const node='C:/Users/Jane/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe';
const builder=path.join(support,'build.mjs');
const jobFile=path.join(root,'job.json');
const env={...process.env,PYTHONIOENCODING:'utf-8',PYTHONUTF8:'1',PATH:'D:\\Anaconda3\\envs\\BigData\\Library\\bin;D:\\Anaconda3\\envs\\BigData;'+process.env.PATH};
const phases=[
  {id:'government',title:'政府采购',dir:path.join(root,'collection-v2'),args:['--sources','1,3','--business','02','--notice-types','0202,0201']},
  {id:'engineering',title:'工程建设',dir:path.join(root,'collection-engineering'),args:['--sources','1,2,6','--business','01','--notice-types','0104,0101']},
];
const job={created_at:new Date().toISOString(),status:'running',supervisor_pid:process.pid,current_phase:null,collector_pid:null,workbook:'E:/CAICTBigData/coding/outputs/01a17c0d-96d1-79a3-9665-f4fc255ee0c7/全国公共资源交易平台_医疗数字化_2026.xlsx',max_batch_rounds:12,api_calls_per_batch:500,max_detail_calls_per_phase:6000,refresh_seconds:180,phases:phases.map(p=>({id:p.id,title:p.title,status:'queued',directory:p.dir})),events:[]};
async function save(){job.updated_at=new Date().toISOString();await fs.writeFile(jobFile+'.tmp',JSON.stringify(job,null,2));await fs.rename(jobFile+'.tmp',jobFile);}
async function readState(p){try{return JSON.parse(await fs.readFile(path.join(p.dir,'state.json'),'utf8'));}catch(e){if(e.code==='ENOENT')return null;throw e;}}
let lastExport=0,lastRows=-1;
function exportWorkbook(force=false){
  if(!force&&Date.now()-lastExport<180000)return;
  try{
    const output=execFileSync(node,[builder],{cwd:support,env,windowsHide:true,encoding:'utf8',timeout:180000,maxBuffer:2*1024*1024});
    console.log(output.trim());lastExport=Date.now();
    job.last_export_at=new Date().toISOString();job.last_export_error=null;
  }catch(e){job.last_export_error=String(e.message).slice(0,700);console.error('Workbook export:',job.last_export_error);}
}
await fs.mkdir(root,{recursive:true});
await save();
exportWorkbook(true);
let stopped=false;
for(let round=1;round<=job.max_batch_rounds&&!stopped;round++){
  for(const p of phases){
    const previous=await readState(p);
    if(previous?.status==='completed')continue;
    const statePath=path.join(p.dir,'state.json');
    const args=['-B','-m','pipeline.research.national_ggzy','--start','2026-01-01','--end','2026-10-28','--output',p.dir,...p.args,'--max-api-calls','500','--max-details','6000'];
    if(previous)args.push('--resume');
    const logPath=path.join(root,`collector-${p.id}-${String(round).padStart(2,'0')}.log`);
    const log=openSync(logPath,'a');
    job.current_phase=p.id;job.current_round=round;
    const child=spawn(python,args,{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});
    closeSync(log);
    job.collector_pid=child.pid;
    job.phases.find(x=>x.id===p.id).status='running';
    await save();
    let ended=false,exitCode=null,error=null;
    child.once('exit',code=>{ended=true;exitCode=code;});
    child.once('error',e=>{ended=true;error=e.message;});
    while(!ended){
      await new Promise(r=>setTimeout(r,15000));
      const s=await readState(p);
      if(s){job.phase_progress={records:Object.keys(s.records??{}).length,pending_windows:s.pending?.length??0,status:s.status};}
      if(job.phase_progress?.records!==lastRows){exportWorkbook(false);lastRows=job.phase_progress?.records??lastRows;}
      await save();
    }
    const s=await readState(p);
    job.events.push({at:new Date().toISOString(),phase:p.id,round,exit_code:exitCode,error,state_status:s?.status,stop_reason:s?.stop_reason});
    job.collector_pid=null;
    job.phases.find(x=>x.id===p.id).status=s?.status??'failed';
    exportWorkbook(true);
    await save();
    const budgetStop=s?.stop_reason?.startsWith('API request budget reached');
    const done=s?.status==='completed';
    if(error||exitCode!==0||(!done&&!budgetStop)){
      job.status='paused';job.stop_reason=error??s?.stop_reason??'阶段存在未恢复失败或详情预算不足，保留检查点';stopped=true;break;
    }
  }
  const current=await Promise.all(phases.map(readState));
  if(current.every(s=>s?.status==='completed')){job.status='completed_selected_scope';stopped=true;}
}
if(!stopped){job.status='partial';job.stop_reason='批次数预算已到，检查点和未完成窗口已保留';}
job.current_phase=null;job.collector_pid=null;job.finished_at=new Date().toISOString();
exportWorkbook(true);
await save();
console.log(JSON.stringify(job));
