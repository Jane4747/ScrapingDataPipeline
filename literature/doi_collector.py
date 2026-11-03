"""DOI/full-text adapter for the existing literature collector (no paid APIs).

Uses pipeline.research.fetch.Fetcher for public HTTP, robots, TLS, size limits,
redirect control and denial handling. Run --dry-run before a new task.
"""
from __future__ import annotations
import argparse, concurrent.futures, difflib, hashlib, io, json, logging, os, re, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from pypdf import PdfReader
from bs4 import BeautifulSoup

REPO=Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path: sys.path.insert(0,str(REPO))
from pipeline.research.fetch import Fetcher, normalize_url

def stamp(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def sha(raw): return hashlib.sha256(raw).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
def safe(text,limit=170):
    s=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',text)
    s=re.sub(r'\s+',' ',s).strip(' .')
    return s[:limit].rstrip(' .') or 'unnamed'
def tokens(text): return set(re.findall(r'[a-z0-9]{3,}',text.lower()))-{'the','and','for','with','using','based','from','that','this'}
def downloaded_totals(records):
    rows=[r for r in records if r.get('status')=='downloaded']
    return {'pages':sum(int(r['pages']) for r in rows),'bytes':sum(int(r.get('pdf_bytes',0)) for r in rows)}
def identity(raw,title,doi):
    if not raw.lstrip().startswith(b'%PDF-'): raise ValueError('Not a PDF')
    reader=PdfReader(io.BytesIO(raw),strict=False)
    if reader.is_encrypted or not 1<=len(reader.pages)<=500: raise ValueError('Encrypted or invalid PDF')
    pages=[p.extract_text() or '' for p in reader.pages]
    first=' '.join(pages[:2]);want=tokens(title);found=tokens(first)
    score=len(want&found)/max(1,len(want))
    doi_match=doi.lower() in re.sub(r'\s+','',first.lower())
    if score<.68 and not (doi_match and score>=.45): raise ValueError(f'PDF identity mismatch (title token recall {score:.2f})')
    return pages,{'title_token_recall':round(score,3),'doi_on_first_two_pages':doi_match,'method':'first-two-page title-token/DOI check; not a human bibliographic review'}

_locks={};_last={};_guard=threading.Lock()
class PoliteFetcher(Fetcher):
    def _throttle(self,url):
        host=urlsplit(url).hostname
        with _guard: lock=_locks.setdefault(host,threading.Lock())
        with lock:
            wait=max(self.delay,self._crawl_delay.get(host,0))-(time.monotonic()-_last.get(host,0))
            if wait>0: time.sleep(wait)
            _last[host]=time.monotonic()

def candidates(row,record,extra):
    w,c=record['work'],record['crossref'];urls=[]
    def add(u,kind):
        u=normalize_url(u or '')
        if u and not any(x['url']==u for x in urls):urls.append({'url':u,'kind':kind})
    for u in extra.get(row['id'],[]):add(u,'curated_public_source')
    if row['doi'].startswith('10.3390/'):
        journal={'Actuators':'actuators','Drones':'drones','AI':'ai','Aerospace':'aerospace','Applied Sciences':'applsci','Sensors':'sensors'}.get(row['venue'])
        if journal and c.get('volume'):
            n=int(re.search(r'(\d{4})$',row['doi'])[1]);volume=str(c['volume']).zfill(2);stem=f'{journal}-{volume}-{n:05}'
            add(f'https://mdpi-res.com/d_attachment/{journal}/{stem}/article_deploy/{stem}.pdf','publisher_oa_pdf')
    for l in w.get('locations',[]):
        if l.get('pdf_url') and (l.get('is_oa') or (l.get('source') or {}).get('type')=='repository'):
            add(l['pdf_url'],'repository_pdf' if 'arxiv' in l['pdf_url'] else 'metadata_pdf')
    for l in w.get('locations',[]):
        src=l.get('source') or {};u=l.get('landing_page_url') or ''
        if src.get('type')=='repository' or l.get('is_oa'):
            if not any(k in u for k in ['doaj.org','doi.org/10.48550']):add(u,'repository_page' if src.get('type')=='repository' else 'publisher_oa_page')
    for l in c.get('link',[]):
        if '.pdf' in l.get('URL','').lower() and any(x.get('is_oa') for x in w.get('locations',[])):add(l['URL'],'crossref_fulltext')
    return urls

def pdf_links(raw,base):
    soup=BeautifulSoup(raw,'html.parser');out=[]
    for meta in soup.find_all('meta'):
        if (meta.get('name') or meta.get('property') or '').lower() in {'citation_pdf_url','wkhealth_pdf_url','eprints.document_url'}:
            out.append(urljoin(base,meta.get('content','')))
    for a in soup.find_all('a',href=True):
        u=urljoin(base,a['href']);txt=a.get_text(' ',strip=True).lower()
        if re.search(r'\.pdf(?:$|[?#])|/bitstreams/.+/download|/document/\d+',u,re.I) or txt in {'download pdf','view/open','full text (pdf)','download file'}:
            out.append(u)
    return list(dict.fromkeys(normalize_url(u) for u in out if normalize_url(u)))[:5]

def collect_one(row,record,extra,root,spec,old):
    if old.get('status')=='downloaded':
        p=(root/old['pdf_path']).resolve();t=(root/old['text_path']).resolve()
        if p.is_relative_to(root) and p.is_file() and sha(p.read_bytes())==old.get('pdf_sha256') and t.is_file() and sha(t.read_bytes())==old.get('text_sha256'):
            return old
    result={**row,'bibliographic_pages':row.get('pages'),'status':'no_public_fulltext','collected_at':stamp(),'attempts':[],'error':''}
    result.pop('pages',None)
    queue=candidates(row,record,extra)
    result['discovered_locations']=queue[:]
    if not queue:return result
    allowed=set(spec['allowed_domains'])|{urlsplit(x['url']).hostname for x in queue}
    fetch=PoliteFetcher(timeout=30,retries=0,delay=spec.get('delay',15),max_bytes=spec.get('max_bytes',67108864))
    tried=set();budget=spec.get('max_requests_per_paper',10)
    try:
        while queue and len(tried)<budget:
            item=queue.pop(0);u=item['url']
            if u in tried:continue
            tried.add(u)
            r=fetch.fetch(u,sorted(allowed));raw=r.pop('raw',b'')
            receipt={k:v for k,v in r.items() if k not in {'text','links'}}
            receipt.update(kind=item['kind'],retrieved_at=stamp(),bytes=len(raw),sha256=sha(raw) if raw else None)
            result['attempts'].append(receipt)
            if raw.lstrip().startswith(b'%PDF-'):
                try:
                    pages,check=identity(raw,row['title'],row['doi'])
                except Exception as ex:
                    receipt.update(identity_error=str(ex));continue
                pdf=root/'pdfs'/(row['id']+'__'+safe(row['title'],160)+'.pdf')
                pdf.parent.mkdir(exist_ok=True)
                if pdf.exists() and sha(pdf.read_bytes())!=sha(raw):raise ValueError('Refusing to overwrite different existing PDF')
                pdf.write_bytes(raw)
                text='\n\n'.join(f'=== PDF PAGE {i} ===\n{t}' for i,t in enumerate(pages,1))
                tp=root/'text'/(row['id']+'.txt');tp.parent.mkdir(exist_ok=True);tp.write_text(text,encoding='utf8')
                result.update(status='downloaded',pdf_path=pdf.relative_to(root).as_posix(),pdf_sha256=sha(raw),pdf_bytes=len(raw),pages=len(pages),text_path=tp.relative_to(root).as_posix(),text_sha256=sha(tp.read_bytes()),source_url=r['url'],identity_check=check,downloaded_version='author/preprint' if ('arxiv.org' in r['url'] or 'repository' in item['kind']) else 'publisher/public-hosted',text_status='available' if len(text)>300 else 'ocr_required')
                break
            if raw and r['status'] in {'ok','empty'}:
                rawpath=root/'raw'/row['id']/(sha(u.encode())[:12]+'.html');rawpath.parent.mkdir(parents=True,exist_ok=True);rawpath.write_bytes(raw)
                for link in reversed(pdf_links(raw,r['url'])):
                    if link not in tried:
                        allowed.add(urlsplit(link).hostname);queue.insert(0,{'url':link,'kind':'linked_public_pdf'})
        if result['status']!='downloaded':
            states={a['status'] for a in result['attempts']}
            result['status']='access_restricted' if states&{'blocked','robots_denied','robots_unavailable'} else 'download_failed'
            result['error']='; '.join(dict.fromkeys(a.get('error','') or a.get('identity_error','') for a in result['attempts'] if a.get('error') or a.get('identity_error')))[:1600]
        return result
    finally:fetch.close()

def load_spec(path):
    path=Path(path).resolve();s=json.loads(path.read_text(encoding='utf8'))
    allowed={'schema_version','task_id','allow_network','output_dir','catalog','records','supplemental','delay','max_bytes','workers','max_requests_per_paper','allowed_domains'}
    if set(s)-allowed or s.get('schema_version')!=2:raise ValueError('Invalid schema or fields')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',s.get('task_id','')):raise ValueError('Invalid task_id')
    if not 15<=s.get('delay',15)<=120 or not 1<=s.get('workers',4)<=6:raise ValueError('Invalid limits')
    root=(path.parent/s['output_dir']).resolve()
    if root==path.parent or root in path.parents:raise ValueError('Dedicated output directory required')
    cat=json.loads((path.parent/s['catalog']).read_text(encoding='utf8'))
    rs=json.loads((path.parent/s['records']).read_text(encoding='utf8'))
    rows=cat['rows'];lookup={r['work']['doi'].lower():r for r in rs}
    if len({r['id'] for r in rows})!=len(rows) or len({r['doi'].lower() for r in rows})!=len(rows):raise ValueError('Duplicate IDs/DOIs')
    if not all('https://doi.org/'+r['doi'].lower() in lookup for r in rows):raise ValueError('Metadata DOI missing')
    extra=json.loads((path.parent/s['supplemental']).read_text(encoding='utf8')) if s.get('supplemental') else {}
    fingerprint=sha(json.dumps({'spec':s,'rows':rows,'records':rs,'supplemental':extra},sort_keys=True).encode())
    return s,root,rows,lookup,extra,fingerprint

def run(spec_path,dry_run=False,resume=False,retry_failed=False):
    s,root,rows,lookup,extra,fingerprint=load_spec(spec_path)
    if dry_run:return {'status':'validated','task_id':s['task_id'],'paper_count':len(rows),'candidate_links':sum(len(candidates(r,lookup['https://doi.org/'+r['doi'].lower()],extra)) for r in rows),'output_dir':str(root),'allow_network':s.get('allow_network',False)}
    if s.get('allow_network') is not True:raise ValueError('allow_network=true required')
    snapshot=root/'input_fingerprint.json'
    if root.exists() and any(root.iterdir()) and not resume:raise ValueError('Existing output; use --resume')
    if snapshot.exists() and json.loads(snapshot.read_text())['sha256']!=fingerprint:raise ValueError('Inputs changed; create a new task')
    root.mkdir(parents=True,exist_ok=True);lock=root/'collection.lock'
    with lock.open('x') as handle:handle.write(str(os.getpid()))
    try:
        save(snapshot,{'sha256':fingerprint,'task_id':s['task_id']});save(root/'spec.snapshot.json',s)
        catpath=root/'catalog.json';previous=json.loads(catpath.read_text(encoding='utf8')) if catpath.exists() else []
        byid={r['id']:r for r in previous};results=dict(byid)
        with concurrent.futures.ThreadPoolExecutor(max_workers=s.get('workers',4)) as pool:
            pending=[r for r in rows if retry_failed or r['id'] not in byid or byid[r['id']]['status']=='downloaded']
            futures={pool.submit(collect_one,r,lookup['https://doi.org/'+r['doi'].lower()],extra,root,s,byid.get(r['id'],{})):r for r in pending}
            for f in concurrent.futures.as_completed(futures):
                row=futures[f]
                try:record=f.result()
                except Exception as ex:record={**row,'status':'download_failed','error':repr(ex),'attempts':[]}
                results[row['id']]=record
                save(root/'receipts'/(row['id']+'.json'),record.get('attempts',[]))
                save(catpath,[results[r['id']] for r in rows if r['id'] in results])
                print(f'{len(results)}/{len(rows)} {row["id"]} {record["status"]}',file=sys.stderr,flush=True)
        output=[results[r['id']] for r in rows];counts={k:sum(r['status']==k for r in output) for k in sorted({r['status'] for r in output})}
        failures=[r for r in output if r['status']!='downloaded'];save(root/'failures.json',failures)
        summary={'task_id':s['task_id'],'status':'partial' if failures else 'completed','finished_at':stamp(),'paper_count':len(rows),'counts':counts,**downloaded_totals(output),'output_dir':str(root)}
        save(root/'manifest.json',summary);return summary
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',required=True);p.add_argument('--dry-run',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--retry-failed',action='store_true',help='Explicitly retry recorded failed candidates; not needed to discover added sources in a new task')
    a=p.parse_args()
    try:
        out=run(a.spec,a.dry_run,a.resume,a.retry_failed);print(json.dumps(out,ensure_ascii=False,indent=2));sys.exit(3 if out['status']=='partial' else 0)
    except Exception as ex:print(json.dumps({'status':'failed','error':repr(ex)},ensure_ascii=False));sys.exit(2)
