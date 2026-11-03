"""Bounded public hospital procurement collection in a Crawl4AI Chrome session.

The current SPA merges only the first 20 rows of each category. Discover the
published endpoints through the page, then paginate both lists in the same
browser context. No model, challenge solving, dependency installation or TLS bypass.
"""
from __future__ import annotations
import argparse, asyncio, hashlib, json, os, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

BASE='https://www.gtbjah.cn'
TZ=timezone(timedelta(hours=8))
def now():return datetime.now(TZ).isoformat(timespec='seconds')
def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
def pubdate(value):
    return datetime.fromtimestamp(value/1000,TZ).date().isoformat() if isinstance(value,(int,float)) and value>0 else ''
def clean(s):return re.sub(r'\s+',' ',s or '').strip()
def parse_tables(html):
    soup=BeautifulSoup(html,'html.parser'); tables=[]
    for ti,t in enumerate(soup.find_all('table')):
        rows=[]
        for tr in t.find_all('tr'):
            if tr.find_parent('table') is not t:continue
            cells=tr.find_all(['td','th'],recursive=False)
            if cells and not any(c.find('table') for c in cells):
                rows.append([clean(c.get_text('',strip=True)) for c in cells])
        if rows:tables.append({'table_index':ti,'rows':rows})
    return tables

async def collect(args):
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    for var,sub in [('TEMP','runtime-temp'),('TMP','runtime-temp'),('CRAWL4_AI_BASE_DIRECTORY','runtime-cache')]:
        p=out/sub;p.mkdir(exist_ok=True);os.environ[var]=str(p)
    os.environ['CRAWL4AI_NO_CLOUD_NOTICE']='1'
    from crawl4ai import AsyncWebCrawler,BrowserConfig,CrawlerRunConfig,CacheMode
    pages=[]; captured=[]
    async def keep(page,**kw):pages.append(page)
    manifest={'task_id':'gtbjah-digital-procurement-20261028','engine':'Crawl4AI 0.9.5 / system Chrome','started_at':now(),'since':args.since,'until':args.until,'entry_url':BASE+'/purchase','list_categories':[78,79],'max_list_pages_per_category':args.max_list_pages,'max_details':args.max_details,'delay_seconds':args.delay,'tls_verified':True,'status':'running','failures':[],'list_coverage':[]}
    write_json(out/'collection.json',manifest)
    cfg=BrowserConfig(chrome_channel='chrome',headless=True,ignore_https_errors=False,verbose=False)
    async with AsyncWebCrawler(config=cfg,base_directory=str(out/'runtime-cache')) as crawler:
        crawler.crawler_strategy.set_hook('on_page_context_created',keep)
        r=await crawler.arun(url=BASE+'/purchase',config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS,session_id='gtbjah-public',wait_for='css:.pi-content',wait_for_timeout=20000,delay_before_return_html=1,page_timeout=45000,capture_network_requests=True,verbose=False))
        if not r.success:raise RuntimeError('Entry render failed: '+str(r.error_message))
        write_json(out/'entry.json',{'url':BASE+'/purchase','success':r.success,'status':r.status_code,'fetched_at':now()})
        (out/'entry.html').write_text(r.html,encoding='utf-8')
        page=pages[-1]
        async def fetch(path,target):
            if target.exists():return json.loads(target.read_text(encoding='utf-8'))
            assert path.startswith('/api/directive/') and not urlsplit(path).netloc
            for attempt in range(2):
                await asyncio.sleep(args.delay if attempt==0 else 4)
                try:
                    result=await page.evaluate('''async path => {
                      const ac=new AbortController();const timer=setTimeout(()=>ac.abort(),30000);
                      try {const r=await fetch(path,{signal:ac.signal});const text=await r.text();
                      if(text.length>4000000)throw new Error('response exceeds size cap');
                      return {status:r.status,url:r.url,text};}finally{clearTimeout(timer);}
                    }''',path)
                    if urlsplit(result['url']).netloc!='www.gtbjah.cn':raise ValueError('Unexpected response host')
                    rec={'url':result['url'],'status':result['status'],'fetched_at':now(),'body':result['text']}
                    if result['status'] in (403,429):
                        write_json(target.with_suffix('.failure.json'),rec)
                        raise PermissionError('Public endpoint blocked or rate limited; stop')
                    if result['status']!=200:raise ValueError('HTTP '+str(result['status']))
                    rec['data']=json.loads(result['text'])
                    write_json(target,rec);return rec
                except PermissionError:raise
                except Exception as exc:
                    if attempt:raise
        items={}
        for category in (78,79):
            reached=False
            for idx in range(1,args.max_list_pages+1):
                path=f'/api/directive/contentList?categoryId={category}&pageIndex={idx}&count=20&orderField=publishDate&orderType=desc'
                data=(await fetch(path,out/'raw'/'lists'/f'{category}-{idx:03d}.json'))['data']['page']
                rows=data['list']; dates=[pubdate(x.get('publishDate')) for x in rows]
                manifest['list_coverage'].append({'category':category,'page':idx,'total_count':data['totalCount'],'total_pages':data['totalPage'],'count':len(rows),'newest':max(dates,default=''),'oldest':min(dates,default='')})
                for x in rows:
                    date=pubdate(x.get('publishDate'))
                    if not date or args.since<=date<=args.until:items[x['id']]=x
                print(f'LIST category={category} page={idx}/{data["totalPage"]} rows={len(rows)} range={min(dates,default="")}..{max(dates,default="")}',flush=True)
                if not rows or data.get('lastPage') or (all(dates) and max(dates)<args.since):reached=True;break
            if not reached:manifest['failures'].append({'stage':'list','category':category,'error':'list page budget exhausted'})
        ordered=sorted(items.values(),key=lambda x:(x.get('publishDate',0),x['id']),reverse=True)
        write_json(out/'list-items.json',ordered)
        records=[]
        for ix,item in enumerate(ordered[:args.max_details],1):
            nid=item['id']; date=pubdate(item.get('publishDate'));target=out/'raw'/'details'/f'{nid}.json'
            try:
                rec=await fetch(f'/api/directive/content?id={nid}&containsAttribute=true',target)
                obj=rec['data'].get('object') or {};attr=rec['data'].get('attribute') or {};html=attr.get('text') or ''
                if obj.get('id')!=nid:raise ValueError('Detail id mismatch')
                folder=out/'raw'/'articles';folder.mkdir(parents=True,exist_ok=True)
                hp=folder/f'{nid}.html';tp=folder/f'{nid}.txt'
                if not hp.exists():hp.write_text(html,encoding='utf-8')
                soup=BeautifulSoup(html,'html.parser'); text=soup.get_text('\n',strip=True)
                if not tp.exists():tp.write_text(text,encoding='utf-8')
                row={'id':nid,'title':obj.get('title',item['title']),'published_at':pubdate(obj.get('publishDate')) or date,'category':item['categoryId'],'url':f'{BASE}/purchase/{nid}','legacy_url':obj.get('url'),'fetched_at':rec['fetched_at'],'raw_api':str(target),'raw_html':str(hp),'raw_text':str(tp),'has_files':bool(obj.get('hasFiles')),'text':text,'tables':parse_tables(html),'images':[i.get('src') for i in soup.find_all('img')],'sha256':hashlib.sha256(html.encode()).hexdigest()}
                records.append(row)
                print(f'DETAIL {ix}/{len(ordered)} id={nid} date={row["published_at"]} tables={len(row["tables"])} chars={len(text)}',flush=True)
            except PermissionError:raise
            except Exception as exc:
                manifest['failures'].append({'stage':'detail','id':nid,'error':str(exc)})
            write_json(out/'notices.json',records)
        if len(ordered)>args.max_details:manifest['failures'].append({'stage':'detail','error':'detail budget exhausted','remaining':len(ordered)-args.max_details})
    manifest.update({'finished_at':now(),'listed_in_scope':len(ordered),'successful_details':len(records),'status':'partial' if manifest['failures'] else 'completed','note':'Complete means selected official category/date collection; project extraction and attachment review are separate.'})
    write_json(out/'collection.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k!='list_coverage'},ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--since',default='2024-01-01');p.add_argument('--until',default='2026-10-28');p.add_argument('--max-list-pages',type=int,default=15);p.add_argument('--max-details',type=int,default=250);p.add_argument('--delay',type=float,default=1.5);p.add_argument('--dry-run',action='store_true');args=p.parse_args()
    assert args.max_list_pages in range(1,21) and 1<=args.max_details<=300 and args.delay>=1
    assert datetime.fromisoformat(args.since)<=datetime.fromisoformat(args.until)
    if args.dry_run:print(json.dumps(vars(args),default=str));return
    asyncio.run(collect(args))
if __name__=='__main__':main()
