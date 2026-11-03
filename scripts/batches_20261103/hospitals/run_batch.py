"""Run isolated, resumable hospital collectors with a per-domain queue."""
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime, timezone
import argparse, concurrent.futures, json, os, subprocess, sys, threading, time
ROOT=Path(__file__).resolve().parent
RUN=Path(os.environ.get('HOSPITAL_BATCH_RUN', str(ROOT.parents[2]/'outputs/hospital-batch-20261103')))
LOCKS={};GUARD=threading.Lock();COUNTS={};LAST_END={}
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp')
    t.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def execute(entry,args):
    contract=read(RUN/'contract.json')
    host=urlsplit(entry['url']).hostname
    if host.startswith('www.'):host=host[4:]
    with GUARD:lock=LOCKS.setdefault(host,threading.Lock())
    with lock:
        delay=float(contract.get('min_delay_seconds',1))
        remaining=delay-(time.monotonic()-LAST_END.get(host,0))
        if remaining>0:time.sleep(remaining)
        tid=entry['task_id'];directory=RUN/'sites'/tid;directory.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-B',str(ROOT/'collector.py'),'--site',tid,'--entrances',str(RUN/'entrances.json'),
                 '--output',str(RUN),'--since',contract['since'],'--until',contract['until'],'--scope','digital',
                 '--max-list-pages',str(args.list_pages),'--max-new-details',str(args.details),'--max-site-seconds',str(args.seconds)]
        if getattr(args,'details_only',False):command.append('--details-only')
        if getattr(args,'digital_titles_only',False):command.append('--digital-titles-only')
        log=directory/f'pass-{args.wave}.log'
        started=time.monotonic();bounded=False
        with log.open('w',encoding='utf-8') as output:
            process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'})
            try:code=process.wait(timeout=args.seconds+45)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=20);code=-9;bounded=True
                task_lock=directory/'collector.lock'
                if task_lock.exists() and read(task_lock).get('pid')==process.pid:task_lock.unlink()
        pages=read(directory/'pages.json') if (directory/'pages.json').exists() else []
        summary=read(directory/'summary.json') if (directory/'summary.json').exists() else {}
        if bounded or not summary:
            summary={**summary,'task_id':tid,'hospital':entry['hospital'],'hospital_ids':entry['hospital_ids'],'url':entry['url'],
                     'status':'partial' if pages else 'failed','coverage_complete':False,'updated_at':stamp(),
                     'records':len(pages),'successful_details':sum(p.get('status')=='ok' for p in pages),
                     'gaps':list(set(summary.get('gaps',[])+(['bounded_process_deadline'] if bounded else ['no_terminal_receipt']))),
                     'stop_reason':'本站进程达到本轮时限，已保存原文与断点' if bounded else '采集进程退出，详见日志'}
            write(directory/'summary.json',summary)
        receipt={'task_id':tid,'exit_code':code,'bounded_timeout':bounded,'seconds':round(time.monotonic()-started,1),
                 'saved_pages':len(pages),'successful_details':summary.get('successful_details',0),'wave':args.wave,'ended_at':stamp()}
        write(directory/f'pass-{args.wave}.json',receipt)
        LAST_END[host]=time.monotonic()
        return receipt
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wave',default='1');ap.add_argument('--seconds',type=int,default=180)
    ap.add_argument('--list-pages',type=int,default=12);ap.add_argument('--details',type=int,default=100)
    ap.add_argument('--workers',type=int,default=8);ap.add_argument('--ids');ap.add_argument('--limit',type=int)
    ap.add_argument('--details-only',action='store_true');ap.add_argument('--digital-titles-only',action='store_true')
    ap.add_argument('--kind');args=ap.parse_args()
    entries=read(RUN/'entrances.json')['entrances']
    if args.ids:
        ordered=read(Path(args.ids));ids=set(ordered);rank={tid:i for i,tid in enumerate(ordered)}
        entries=sorted([e for e in entries if e['task_id'] in ids],key=lambda e:rank[e['task_id']])
    if args.kind:entries=[e for e in entries if e['entry_kind']==args.kind]
    entries=[e for e in entries if not (RUN/'sites'/e['task_id']/f'pass-{args.wave}.json').exists()]
    if args.limit:entries=entries[:args.limit]
    results=[];print(json.dumps({'queued':len(entries),'wave':args.wave,'workers':args.workers}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futuremap={pool.submit(execute,e,args):e for e in entries}
        for future in concurrent.futures.as_completed(futuremap):
            try:r=future.result()
            except Exception as exc:r={'task_id':futuremap[future]['task_id'],'error':str(exc)}
            results.append(r)
            write(RUN/f'wave-{args.wave}-progress.json',{'started_entries':len(entries),'finished':len(results),'updated_at':stamp(),'receipts':results})
            print(json.dumps({'done':len(results),'total':len(entries),**r},ensure_ascii=True),flush=True)
    write(RUN/f'wave-{args.wave}-complete.json',{'finished_at':stamp(),'entries':len(entries),'receipts':results})
if __name__=='__main__':main()
