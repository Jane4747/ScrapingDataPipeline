"""Offline DOI adapter reusing literature/extract_figures.py without modifying it.

Numbered vector/mixed figures, every embedded occurrence, and page references
are separate outputs. Automatic crops never imply visual/manual verification.
"""
import argparse, csv, hashlib, html, importlib.util, json, os, re, sys
from pathlib import Path

def load(path):return json.loads(Path(path).read_text(encoding='utf8'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def native(path):
    p=str(Path(path).resolve())
    return Path('\\\\?\\'+p) if os.name=='nt' and not p.startswith('\\\\?\\') else Path(p)
def module():
    spec=importlib.util.spec_from_file_location('shared_figure_extractor',Path(__file__).with_name('extract_figures.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def rewrite(value):
    if isinstance(value,list):return [rewrite(v) for v in value]
    if isinstance(value,dict):return {('paper_id' if k=='arxiv_id' else k):rewrite(v) for k,v in value.items()}
    return value

def extract(root,ident,dpi=240,image_dir='images',correct_captions=False,reuse_assets=None):
    root=Path(root).resolve();rows=load(root/'catalog.json');r=next(x for x in rows if x['id']==ident)
    if r['status']!='downloaded':raise ValueError('No downloaded PDF')
    out=native(root/image_dir);m=module();source=root/r['pdf_path']
    if correct_captions:
        from doi_caption_layout import install
        install(m)
    if sha(source)!=r['pdf_sha256']:raise ValueError('Source checksum mismatch')
    dest=out/'paper_results'/(ident+'.json');recipe=sha(Path(__file__))+sha(Path(__file__).with_name('extract_figures.py'))
    if correct_captions:recipe+=sha(Path(__file__).with_name('doi_caption_layout.py'))
    if dest.exists():
        old=load(dest)
        if old.get('recipe')==recipe and not old.get('errors') and all((out/x['file']).is_file() and sha(out/x['file'])==x['sha256'] for x in old['figures']+old['assets']+old.get('page_references',[])):
            return {'paper_id':ident,'status':'cached','figures':len(old['figures']),'assets':len(old['assets'])}
        raise ValueError('Existing extraction differs or is partial; use a new image output directory')
    legacy={**r,'arxiv_id':ident,'version_id':r.get('source_url',r['doi_url'])}
    layout=m.scan_paper(legacy,source);m.save_json(out/'layout'/(ident+'.json'),rewrite(layout))
    doc=m.pdfium.PdfDocument(source)
    result=m.export_paper(layout,doc,out,{'dpi':dpi},[],'figures' if reuse_assets else 'all')
    for f in result['figures']:f['review_status']='automatic_crop_pending_visual_review'
    pages=[]
    for i in range(0 if reuse_assets else len(doc)):
        p=doc[i];bitmap=p.render(scale=120/72);image=bitmap.to_pil().copy();bitmap.close();p.close()
        filename=m.safe_name(r['title'])+f'__Page_{i+1:03d}__Full_page.png'
        target=out/'page_references'/ident/filename
        props=m.save_image(target,image,120);image.close()
        pages.append({**props,'paper_id':ident,'paper_title':r['title'],'page':i+1,'file':target.relative_to(out).as_posix(),'method':'120dpi full-page reference; not an isolated Figure'})
    if reuse_assets:
        cached_base=root/reuse_assets;cached=load(cached_base/'paper_results'/(ident+'.json'))
        for field in ['assets','image_occurrences','page_references']:
            values=cached.get(field,[])
            for item in values:
                for key in ['file','thumbnail']:
                    if key in item:item[key]=Path(os.path.relpath(cached_base/item[key],root/image_dir)).as_posix()
            if field=='page_references':pages=values
            else:result[field]=values
    doc.close();m.contact_sheet(out,result)
    result=rewrite(result);result.update(recipe=recipe,doi=r['doi'],page_references=pages,review_status='automatic_extraction_pending_visual_review',source_version=r.get('downloaded_version'))
    # Record every detected caption, including crops the heuristic could not resolve.
    detected={c['number'] for pg in layout['pages'] for c in pg['captions']}
    resolved={f['number'] for f in result['figures']}
    result['caption_coverage']={'detected':sorted(detected),'cropped':sorted(resolved),'unresolved':sorted(detected-resolved),'scope':'Detected caption candidates only; not proof that all figures were recognized'}
    save(dest,result)
    return {'paper_id':ident,'status':'extracted','figures':len(result['figures']),'assets':len(result['assets']),'unresolved_captions':len(detected-resolved),'errors':len(result['errors'])}

def finalize(root,image_dir='images'):
    root=Path(root).resolve();out=native(root/image_dir);results=[load(x) for x in sorted((out/'paper_results').glob('*.json'))]
    figures=[f for r in results for f in r['figures']];assets=[f for r in results for f in r['assets']];pages=[f for r in results for f in r['page_references']]
    occurrences=[f for r in results for f in r['image_occurrences']]
    errors=[{'paper_id':r['paper_id'],**e} for r in results for e in r['errors']]
    checks=[]
    from PIL import Image
    for f in figures+assets+pages:
        p=out/f['file'];ok=p.is_file() and sha(p)==f['sha256']
        try:
            with Image.open(p) as im:ok=ok and im.size==(f['width'],f['height']);im.verify()
        except Exception:ok=False
        checks.append({'file':f['file'],'ok':ok})
    save(out/'figures_manifest.json',figures);save(out/'images_manifest.json',assets);save(out/'page_references.json',pages);save(out/'image_occurrences.json',occurrences)
    save(out/'errors.json',errors);save(out/'verification.json',{'checks':checks,'all_images_openable_and_hash_match':all(x['ok'] for x in checks),'visual_review':'pending except explicitly recorded in visual_review.json'})
    with (out/'image_catalog.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        fields=['kind','paper_id','paper_title','image_name','page','caption','file','width','height','sha256','review_status']
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for kind,items in [('numbered_figure',figures),('embedded_asset',assets),('full_page_reference',pages)]:
            for f in items:writer.writerow({**f,'kind':kind,'image_name':f.get('label','')+' '+f.get('caption_title',f.get('image_name','')),'page':f.get('page',f.get('first_page'))})
    e=lambda s:html.escape(str(s or ''),quote=True)
    sections=[]
    for r in results:
        cards=[]
        for kind,items in [('编号整图',r['figures']),('内嵌素材',r['assets']),('逐页预览',r['page_references'])]:
            parts=[]
            for f in items:
                label=f.get('label') or f.get('image_name') or f'Page {f["page"]}'
                parts.append(f'<article class="card"><a href="{e(f["file"])}"><img loading="lazy" src="{e(f.get("thumbnail",f["file"]))}"></a><h4>{e(label)}</h4><p>{e(f.get("caption_title",""))}</p><details><summary>来源与完整图注</summary><p>{e(f.get("caption",""))}</p><small>{e(f["file"])}</small></details></article>')
            cards.append(f'<details {"open" if kind=="编号整图" else ""}><summary>{kind} · {len(items)}</summary><div class="grid">'+''.join(parts)+'</div></details>')
        sections.append(f'<section data-title="{e(r["title"].lower())}"><h2>{e(r["paper_id"])} · {e(r["title"])}</h2><p>DOI: {e(r["doi"])}；裁剪待逐图复核。未解决图注：{e(", ".join(r["caption_coverage"]["unresolved"])) or "无已检测缺口"}</p>'+''.join(cards)+'</section>')
    summary={'paper_count':len(results),'numbered_figures':len(figures),'embedded_assets':len(assets),'embedded_occurrences':len(occurrences),'page_references':len(pages),'unresolved_caption_candidates':sum(len(r['caption_coverage']['unresolved']) for r in results),'extraction_errors':len(errors),'images_verified':len(checks),'status':'partial' if errors else 'extracted_pending_visual_review'}
    save(out/'manifest.json',summary)
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>视觉伺服论文图像库</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;background:#f4f7fa;color:#1c344b;margin:25px auto;max-width:1400px;padding:0 24px}section{margin:28px 0;background:white;padding:20px;border:1px solid #d7e1e8}a{color:#176b9c}h2{font-size:21px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.card{border:1px solid #d7e1e8;padding:12px;overflow-wrap:anywhere}img{max-width:100%;height:220px;object-fit:contain}summary{cursor:pointer;font-weight:bold}small{font-size:12px}input{font:inherit;width:70%;padding:8px}</style><h1>视觉伺服论文图像库</h1><p>论文名__图号__图注简称.png。没有独立图名的素材以论文名__Page_页码_Image_序号.png命名。超长文件名缩短，完整论文名和图注保留在清单中。</p><p>原始图像未使用AI重绘；矢量与混合图由原页渲染裁剪。内嵌素材、编号整图、逐页预览分别计数。来源许可与版权保持不变。</p><p>@@SUMMARY@@</p><p><a href="../architecture_report.html">系统架构分析</a> · <a href="image_catalog.csv">文件名映射</a> · <a href="verification.json">文件完整性核验</a></p><input id="q" placeholder="按论文名称筛选">@@SECTIONS@@<script>q.oninput=()=>document.querySelectorAll('section').forEach(s=>s.hidden=!s.dataset.title.includes(q.value.toLowerCase()))</script></html>'''
    (out/'index.html').write_text(document.replace('@@SUMMARY@@',e(json.dumps(summary,ensure_ascii=False))).replace('@@SECTIONS@@',''.join(sections)),encoding='utf8')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--paper-id');p.add_argument('--finalize',action='store_true');p.add_argument('--image-dir',default='images');p.add_argument('--correct-captions',action='store_true');p.add_argument('--reuse-assets')
    a=p.parse_args()
    try:print(json.dumps(finalize(a.root,a.image_dir) if a.finalize else extract(a.root,a.paper_id,image_dir=a.image_dir,correct_captions=a.correct_captions,reuse_assets=a.reuse_assets),ensure_ascii=False))
    except Exception as ex:print(json.dumps({'status':'failed','paper_id':a.paper_id,'error':repr(ex)},ensure_ascii=False));sys.exit(2)
