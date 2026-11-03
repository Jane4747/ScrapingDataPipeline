"""Offline import of institution/user-provided PDFs into a NEW collection attempt."""
import argparse,json,shutil,re
from pathlib import Path
from pypdf import PdfReader
from doi_collector import identity,safe,sha,save,stamp,tokens

def match(first,rows):
    compact=''.join(first.lower().split());found=tokens(first);scores=[]
    canonical=lambda t:''.join(re.findall(r'[a-z0-9]',t.lower()))
    front=canonical(first[:2400])
    for r in rows:
        want=tokens(r['title']);score=len(want&found)/max(1,len(want))
        position=front.find(canonical(r['title']));exact=position>=0;doi=r['doi'].lower() in compact
        position_bonus=2*max(0,1-position/500) if exact else 0
        if (doi and score>=.45) or exact or score>=.9:scores.append((score+4*exact+2*doi+position_bonus,r))
    scores.sort(key=lambda s:-s[0])
    if not scores or (len(scores)>1 and scores[0][0]-scores[1][0]<.12):return None
    return scores[0][1]

def run(inbox,catalog,out):
    inbox=Path(inbox).resolve();out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a NEW output directory')
    if out==inbox or out in inbox.parents:raise ValueError('Separate output directory required')
    rows=json.loads(Path(catalog).read_text(encoding='utf8'))['rows'];out.mkdir(parents=True,exist_ok=True)
    results=[];unmatched=[]
    for source in sorted(inbox.glob('*.pdf')):
        try:
            reader=PdfReader(source,strict=False);first=' '.join(p.extract_text() or '' for p in reader.pages[:2]);row=match(first,rows)
            if row is None:raise ValueError('Unmatched or ambiguous title/DOI; left in inbox')
            raw=source.read_bytes();pages,check=identity(raw,row['title'],row['doi'])
            if any(r['id']==row['id'] for r in results):raise ValueError('Duplicate paper; left in inbox')
            pdf=out/'pdfs'/(row['id']+'__'+safe(row['title'],160)+'.pdf');pdf.parent.mkdir(exist_ok=True);shutil.copy2(source,pdf)
            text=out/'text'/(row['id']+'.txt');text.parent.mkdir(exist_ok=True);text.write_text('\n\n'.join(f'=== PDF PAGE {i} ===\n{t}' for i,t in enumerate(pages,1)),encoding='utf8')
            result={**row,'bibliographic_pages':row.get('pages'),'pages':len(pages),'status':'downloaded','pdf_path':pdf.relative_to(out).as_posix(),'text_path':text.relative_to(out).as_posix(),'pdf_sha256':sha(raw),'pdf_bytes':len(raw),'text_sha256':sha(text.read_bytes()),'source_url':source.as_uri(),'downloaded_version':'user/institution supplied; version not inferred','collected_at':stamp(),'identity_check':check}
            results.append(result)
        except Exception as ex:unmatched.append({'file':str(source),'error':str(ex)})
    save(out/'catalog.json',results);save(out/'unmatched.json',unmatched)
    summary={'status':'partial' if unmatched else 'completed','imported':len(results),'unmatched':len(unmatched),'network_used':False,'output_dir':str(out)};save(out/'manifest.json',summary);print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inbox',required=True);p.add_argument('--catalog',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.inbox,a.catalog,a.out)
