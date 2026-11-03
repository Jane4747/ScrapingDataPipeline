"""Incrementally extract each newly downloaded PDF in an isolated subprocess."""
import argparse,json,subprocess,sys,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--watch',action='store_true');p.add_argument('--image-dir',default='images');p.add_argument('--correct-captions',action='store_true');p.add_argument('--paper-ids',default='');p.add_argument('--reuse-assets');a=p.parse_args();root=Path(a.root).resolve()
    selected=set(a.paper_ids.split(',')) if a.paper_ids else None
    attempted=set();logs=root/a.image_dir/'worker_logs';logs.mkdir(parents=True,exist_ok=True)
    while True:
        records=json.loads((root/'catalog.json').read_text(encoding='utf8'))
        for r in records:
            if r['status']!='downloaded' or r['id'] in attempted or (selected and r['id'] not in selected):continue
            attempted.add(r['id'])
            command=[sys.executable,'-B',str(Path(__file__).with_name('doi_figures.py')),'--root',str(root),'--paper-id',r['id'],'--image-dir',a.image_dir]
            if a.correct_captions:command.append('--correct-captions')
            if a.reuse_assets:command.extend(['--reuse-assets',a.reuse_assets])
            try:
                cp=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=480)
                (logs/(r['id']+'.out.txt')).write_bytes(cp.stdout);(logs/(r['id']+'.err.txt')).write_bytes(cp.stderr)
                print(r['id'],cp.returncode,cp.stdout.decode('utf8','replace')[-450:],flush=True)
            except subprocess.TimeoutExpired:
                print(r['id'],'extraction_timeout',flush=True)
        if not a.watch:break
        if not (root/'collection.lock').exists():
            final=json.loads((root/'catalog.json').read_text(encoding='utf8'))
            if not any(r['status']=='downloaded' and r['id'] not in attempted and (not selected or r['id'] in selected) for r in final):break
        time.sleep(10)
    cp=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('doi_figures.py')),'--root',str(root),'--image-dir',a.image_dir,'--finalize'])
    return cp.returncode
if __name__=='__main__':raise SystemExit(main())
