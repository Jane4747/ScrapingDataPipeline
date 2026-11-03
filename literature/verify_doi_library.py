"""Verify saved local links, source checksums and required library coverage."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit,unquote
from bs4 import BeautifulSoup

def verify(root):
    root=Path(root).resolve();errors=[];counts={};anchor_cache={}
    for name in ['architecture_report.html','images/index.html']:
        p=root/name;soup=BeautifulSoup(p.read_text(encoding='utf8'),'html.parser');ids={x['id'] for x in soup.select('[id]')};links=soup.select('a[href],img[src]');counts[name]=len(links)
        for el in links:
            url=el.get('href') or el.get('src');u=urlsplit(url)
            if u.scheme or u.netloc:continue
            target=(p.parent/unquote(u.path)).resolve() if u.path else p
            if not target.is_file():errors.append({'file':name,'link':url,'issue':'missing target'})
            elif not u.path and u.fragment and u.fragment not in ids:errors.append({'file':name,'link':url,'issue':'missing anchor'})
            elif u.fragment and u.path.endswith('.html'):
                if target not in anchor_cache:
                    other=BeautifulSoup(target.read_text(encoding='utf8'),'html.parser');anchor_cache[target]={x['id'] for x in other.select('[id]')}
                if u.fragment not in anchor_cache[target]:errors.append({'file':name,'link':url,'issue':'missing cross-file anchor'})
    saved=json.loads((root/'verification.json').read_text(encoding='utf8'));summary=json.loads((root/'manifest.json').read_text(encoding='utf8'))
    report={'html_links':counts,'broken_links':errors,'file_integrity_passed':saved['checks_passed'],'downloaded':summary['downloaded_unique'],'architectures':summary['reviewed_architectures'],'passed':not errors and saved['checks_passed'] and summary['reviewed_architectures']==summary['downloaded_unique']}
    (root/'link_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return report['passed']
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();raise SystemExit(0 if verify(a.root) else 2)
