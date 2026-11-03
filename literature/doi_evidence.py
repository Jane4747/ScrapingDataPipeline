"""Prepare page-addressable evidence windows; extraction does not infer architecture."""
import argparse,json,re
from pathlib import Path
PATTERN=re.compile(r'architecture|framework|block diagram|proposed (?:method|approach|controller|scheme)|control scheme|system consists|system comprises|overall (?:system|structure)|experimental (?:setup|platform)|we propose',re.I)
def prepare(root):
    root=Path(root);rows=json.loads((root/'catalog.json').read_text(encoding='utf8'));result=[]
    for r in rows:
        if r['status']!='downloaded':continue
        text=(root/r['text_path']).read_text(encoding='utf8');snippets=[]
        parts=re.split(r'=== PDF PAGE (\d+) ===',text)
        for i in range(1,len(parts),2):
            number=int(parts[i]);body=parts[i+1];matches=list(PATTERN.finditer(body))
            used=[]
            for m in matches:
                start=max(0,m.start()-180);end=min(len(body),m.end()+650)
                if any(abs(start-old)<500 for old in used):continue
                used.append(start);snippets.append({'page':number,'text':re.sub(r'\s+',' ',body[start:end]),'keyword':m.group()})
        # Prefer early method pages over late citations and keep original first-page abstract.
        snippets.sort(key=lambda s:(s['page']>max(8,r['pages']*.7),s['page']))
        record={'id':r['id'],'title':r['title'],'pdf':r['pdf_path'],'pages':r['pages'],'first_page':parts[2][:4200] if len(parts)>2 else '', 'windows':snippets[:12]}
        result.append(record)
    (root/'architecture_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'papers':len(result),'output':str(root/'architecture_evidence.json')},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();prepare(a.root)
