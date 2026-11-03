"""Build an offline DOI library, architecture review and combined figure gallery.

Preserves every collection attempt. Missing full text never receives a fabricated
architecture analysis. PDFs/text and short-path image copies form a portable
library; original filenames and extraction locations remain in the manifest.
"""
import argparse,collections,csv,hashlib,html,json,os,re,shutil
from pathlib import Path

def load(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rel(p,root):return Path(os.path.relpath(p,root)).as_posix()
def e(v):return html.escape(str(v or ''),quote=True)
def native(p):
    p=str(Path(p).resolve())
    return Path('\\\\?\\'+p) if os.name=='nt' and not p.startswith('\\\\?\\') else Path(p)
def publish_image(f,base,out,kind):
    """Shorten only as needed for Windows; preserve full names in the manifest."""
    clean=lambda s:re.sub(r'\s+',' ',re.sub(r'[<>:"/\\|?*#%\x00-\x1f]',' ',str(s))).strip(' .')
    ident=f.get('paper_id') or f.get('arxiv_id');title=clean(f['paper_title'])
    if kind=='figures':label=f.get('label','Figure').replace(' ','_');caption=clean(f.get('caption_title',''))[:30]
    elif kind=='assets':label=clean(f.get('image_name','Image')).replace(' ','_');caption=''
    else:label=f'Page_{f["page"]:03d}_Full_page';caption=''
    tail='__'+label+('__'+caption if caption else '')+'.png'
    destdir=out/'images'/ident;previewdir=out/'images'/'previews'/ident
    budget=min(220,238-len(str(previewdir))-1)
    room=max(22,budget-len(tail));paper=title if len(title)<=room else title[:room-9].rstrip()+'~'+hashlib.sha256(title.encode()).hexdigest()[:8]
    name=paper+tail;dest=destdir/name;destdir.mkdir(parents=True,exist_ok=True)
    source=native(base/f['file']);f['source_file']=str(base/f['file']);f['original_filename']=source.name
    if dest.exists() and sha(dest)!=f['sha256']:raise ValueError('Published image collision: '+str(dest))
    if not dest.exists():shutil.copy2(source,dest)
    f['file']=rel(dest,out/'images')
    if f.get('thumbnail'):
        preview=previewdir/name;previewdir.mkdir(parents=True,exist_ok=True)
        if not preview.exists():shutil.copy2(native(base/f['thumbnail']),preview)
        f['thumbnail']=rel(preview,out/'images')

def build(metadata,sources,notes_path,out,image_dir='images-v2'):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    for name in ['pdfs','text','images','evidence','inbox']:(out/name).mkdir(exist_ok=True)
    meta=load(metadata);notes=load(notes_path);byid=collections.defaultdict(list);evidence={}
    for source in sources:
        source=Path(source).resolve()
        for r in load(source/'catalog.json'):byid[r['id']].append((source,r))
        if (source/'architecture_evidence.json').exists():
            for r in load(source/'architecture_evidence.json'):evidence.setdefault(r['id'],r)
    rows=[];image_results=[]
    for original in meta['rows']:
        attempts=byid[original['id']]
        success=next(((s,r) for s,r in attempts if r['status']=='downloaded'),None)
        r=dict(original);r['collection_attempts']=[{'source':str(s),'status':a['status'],'receipts':rel(s/'receipts'/(r['id']+'.json'),out)} for s,a in attempts]
        r['download_status']=success[1]['status'] if success else ('access_restricted' if any(a['status']=='access_restricted' for s,a in attempts) else 'download_failed' if any(a['status']=='download_failed' for s,a in attempts) else 'no_public_fulltext')
        n=notes['papers'].get(r['id']) if success else None
        r['analysis_status']='method_evidence_reviewed' if n else 'fulltext_pending_review' if success else 'fulltext_missing'
        r['architecture']=n
        if success:
            source,got=success;pdf=source/got['pdf_path'];text=source/got['text_path']
            if sha(pdf)!=got['pdf_sha256']:raise ValueError('Source PDF checksum mismatch: '+r['id'])
            for src,dest in [(pdf,out/'pdfs'/pdf.name),(text,out/'text'/(r['id']+'.txt'))]:
                if dest.exists() and sha(dest)!=sha(src):raise ValueError('Different existing library content: '+str(dest))
                if not dest.exists():shutil.copy2(src,dest)
            r.update(pdf_path=rel(out/'pdfs'/pdf.name,out),text_path='text/'+r['id']+'.txt',pdf_pages=got['pages'],pdf_sha256=got['pdf_sha256'],source_url=got['source_url'],source_version=got['downloaded_version'])
            if r['id'] in evidence:save(out/'evidence'/(r['id']+'.json'),evidence[r['id']])
            ip=source/image_dir/'paper_results'/(r['id']+'.json')
            if not ip.exists():
                other=next((s/image_dir/'paper_results'/(r['id']+'.json') for s,a in attempts if (s/image_dir/'paper_results'/(r['id']+'.json')).exists()),None)
                if other:ip=other
            if ip.exists():
                imgs=load(ip);base=ip.parent.parent
                for field in ['figures','assets','page_references']:
                    for f in imgs.get(field,[]):publish_image(f,base,out,field)
                image_results.append(imgs);r['image_figures']=len(imgs['figures']);r['image_assets']=len(imgs['assets'])
            if n:
                if not all(1<=page<=r['pdf_pages'] for page in n['pages']):raise ValueError('Review page outside PDF '+r['id'])
        rows.append(r)
    counts=dict(collections.Counter(r['download_status'] for r in rows))
    figures=[f for r in image_results for f in r['figures']];assets=[f for r in image_results for f in r['assets']];page_refs=[f for r in image_results for f in r.get('page_references',[])]
    summary={'date':'2026-11-01','registered':len(rows),'downloaded_unique':counts.get('downloaded',0),'missing_fulltext':len(rows)-counts.get('downloaded',0),'download_counts':counts,'reviewed_architectures':sum(r['analysis_status']=='method_evidence_reviewed' for r in rows),'pdf_pages':sum(r.get('pdf_pages',0) for r in rows),'image_papers':len(image_results),'numbered_figures':len(figures),'embedded_assets':len(assets),'page_references':len(page_refs),'unresolved_caption_candidates':sum(len(r['caption_coverage']['unresolved']) for r in image_results),'status':'partial' if counts.get('downloaded',0)<len(rows) else 'completed','extraction_version':image_dir,'visual_review':'Representative source pages/contact sheets reviewed; remaining crops pending individual visual verification'}
    save(out/'catalog.json',rows);save(out/'manifest.json',summary);save(out/'missing_fulltext.json',[r for r in rows if r['download_status']!='downloaded']);save(out/'architecture_analysis.json',{'reviewer':notes['reviewer'],'papers':rows})
    save(out/'images'/'figures_manifest.json',figures);save(out/'images'/'images_manifest.json',assets);save(out/'images'/'page_references.json',page_refs)
    with (out/'download_status.csv').open('w',encoding='utf-8-sig',newline='') as h:
        fields=['id','title','title_cn','doi','download_status','analysis_status','pdf_path','source_url'];w=csv.DictWriter(h,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    with (out/'images'/'image_catalog.csv').open('w',encoding='utf-8-sig',newline='') as h:
        fields=['kind','paper_id','paper_title','image_name','page','file','width','height','sha256'];w=csv.DictWriter(h,fieldnames=fields,extrasaction='ignore');w.writeheader()
        for kind,items in [('numbered_figure',figures),('embedded_asset',assets),('page_reference',page_refs)]:
            for f in items:w.writerow({**f,'kind':kind,'image_name':f.get('label','')+' '+f.get('caption_title',f.get('image_name','')),'page':f.get('page',f.get('first_page'))})
    gallery=[]
    for result in image_results:
        groups=[]
        for label,items in [('编号图',result['figures']),('内嵌素材',result['assets']),('逐页预览',result['page_references'])]:
            cards=[]
            for f in items:
                caption=f.get('label') or f.get('image_name') or f'Page {f["page"]}'
                cards.append(f'<article class="image"><a href="{e(f["file"])}"><img loading="lazy" src="{e(f.get("thumbnail",f["file"]))}" alt="{e(caption)}"></a><b>{e(caption)}</b><p>{e(f.get("caption_title",""))}</p><details><summary>完整图注与文件名</summary><p>{e(f.get("caption",""))}</p><small>{e(f["file"])}</small></details></article>')
            groups.append(f'<details {"open" if label=="编号图" else ""}><summary>{label} · {len(items)}</summary><div class="grid">'+''.join(cards)+'</div></details>')
        gallery.append(f'<section id="p{e(result["paper_id"])}" data-search="{e(result["title"].lower())}"><h2>{e(result["paper_id"])} · {e(result["title"])}</h2><p>编号图自动裁剪，未逐图确认。未解决的已检测图注：{e(", ".join(result["caption_coverage"]["unresolved"])) or "无已检测缺口"}。所有页面均有完整预览备查。</p>'+''.join(groups)+'</section>')
    css='''body{font:16px/1.75 "Microsoft YaHei",Arial,sans-serif;background:#f4f7fa;color:#21374b;max-width:1320px;margin:30px auto;padding:0 24px}h1{font-size:32px}h2{font-size:23px}h3{font-size:19px}a{color:#176b9c;text-decoration:none}a:hover{text-decoration:underline}section{background:white;border:1px solid #d6e1e9;border-radius:8px;margin:22px 0;padding:24px}.muted,small{color:#526b80}.stats,.flow{display:flex;gap:15px;flex-wrap:wrap}.stats div,.node{padding:12px 18px;background:#e8f1f7;border-radius:5px}.stats b{font-size:27px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.image{border:1px solid #d6e1e9;padding:12px;overflow-wrap:anywhere}.image img{width:100%;height:220px;object-fit:contain}input{font:inherit;width:70%;padding:9px}summary{cursor:pointer;font-weight:bold}dl{display:grid;grid-template-columns:115px 1fr;gap:12px}dt{font-weight:bold}dd{margin:0}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:10px;border-bottom:1px solid #d6e1e9;text-align:left;vertical-align:top}th{background:#e8f1f7}.scroll{overflow:auto}code,pre{font-family:Consolas,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#183047;color:white;padding:20px}.notice{border-left:4px solid #b17b15;padding:14px;background:#fff6df}.paper{border-top:2px solid #a6c3d7;padding-top:20px;margin-top:25px}.bad{color:#8a4d13}@media(max-width:800px){.grid{grid-template-columns:1fr}dl{grid-template-columns:1fr}body{padding:0 12px}}'''
    head=f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{css}</style>'
    gallery_intro=f'<title>视觉伺服论文图片库</title><h1>视觉伺服论文图片库</h1><p>{len(image_results)}篇 · {len(figures)}张编号图 · {len(assets)}张论文内去重素材 · {len(page_refs)}页完整预览</p><p>命名：论文名称__Figure_图号__图注简称.png；无独立图名的素材使用论文名称__Page_页码_Image_序号.png。超长名称缩短，完整名称保留在清单。</p><p class="notice">编号图与内嵌素材不能相加当作独立Figure。图像由原PDF直接提取或渲染，未AI重绘。保留来源许可与版权，仅作本地研究整理。自动裁剪存在待复核项，完整页面可用于检查遗漏。</p><p><a href="../architecture_report.html">系统架构分析</a> · <a href="image_catalog.csv">图片命名与来源映射</a></p><input id="q" placeholder="搜索论文名称">'
    script="<script>document.getElementById('q').oninput=function(){const q=this.value.toLowerCase();document.querySelectorAll('[data-search]').forEach(s=>s.hidden=!s.dataset.search.includes(q))}</script>"
    (out/'images'/'index.html').write_text(head+gallery_intro+''.join(gallery)+script+'</html>',encoding='utf8')
    statuses={'downloaded':'已下载','access_restricted':'访问受限','download_failed':'候选链接未取得全文','no_public_fulltext':'未发现开放全文入口'}
    table=[];cards=[]
    for r in rows:
        full=bool(r.get('pdf_path'));n=r['architecture']
        links=f'<a href="{e(r["doi_url"])}">DOI</a>'
        if full:links+=f' · <a href="{e(r["pdf_path"])}">PDF</a> · <a href="{e(r["text_path"])}">逐页文本</a> · <a href="images/index.html#p{e(r["id"])}">图片</a>'
        idcell=f'<a href="#p{e(r["id"])}">{e(r["id"])}</a>' if n else e(r['id'])
        table.append(f'<tr><td>{idcell}</td><td>{e(r["title_cn"])}<br><small>{e(r["title"])}</small></td><td>{statuses[r["download_status"]]}</td><td>{e(n["loop"]) if n else "缺全文，未作系统架构复核"}</td><td>{links}</td></tr>')
        if n:
            fields=[('闭环结构','loop'),('感知与估计','perception'),('控制与执行','control'),('验证范围','validation'),('适用边界','limits'),('木耳采摘启发','transfer')]
            sourcepages=' · '.join(f'<a href="{e(r["pdf_path"])}#page={page}">PDF第{page}页</a>' for page in n['pages'])
            selected_images=[]
            source_images=next((x for x in image_results if x['paper_id']==r['id']),{})
            for f in source_images.get('figures',[]):
                if f['number'] in n.get('figures',[]) and len(selected_images)<2:
                    selected_images.append(f'<figure><a href="images/{e(f["file"])}"><img style="max-width:100%;height:230px;object-fit:contain" src="images/{e(f.get("thumbnail",f["file"]))}" alt="{e(f["label"])}"></a><figcaption>{e(f["label"])} · {e(f["caption_title"])}</figcaption></figure>')
            cards.append(f'<article class="paper" id="p{e(r["id"])}"><h3>{e(r["id"])} · {e(r["title_cn"])}</h3><p class="muted">{e(r["title"])}</p><p>{links}</p><div class="flow">'+''.join(selected_images)+'</div><dl>'+''.join(f'<dt>{label}</dt><dd>{e(n[key])}</dd>' for label,key in fields)+f'</dl><p><small>原文依据：{sourcepages}。前五项归纳作者方法；最后一项为本次工程推断。所读PDF版本：{e(r["source_version"])}。</small></p></article>')
    stats=f'<div class="stats"><div><b>{len(rows)}</b><br>登记论文</div><div><b>{summary["downloaded_unique"]}</b><br>有效PDF／去重</div><div><b>{summary["missing_fulltext"]}</b><br>待补全文</div><div><b>{summary["reviewed_architectures"]}</b><br>架构方法笔记</div></div>'
    intro='<title>视觉伺服论文：全文、图像与系统架构</title><h1>视觉伺服论文库与系统架构分析</h1><p class="muted">2023-2026文献清单 · 整理日期2026-11-01 · 引用量沿用2026-10-27快照，不作为新统计</p>'+stats+f'<p class="notice">本次仅对取得全文的{summary["reviewed_architectures"]}篇阅读摘要、方法段落及部分架构图。其余{summary["missing_fulltext"]}篇保留登记和访问记录，未依据题名补写具体架构。自动图表裁剪尚有逐图复核工作，完整页和内嵌素材均保留。</p><p><a href="images/index.html">打开图片库</a> · <a href="download_status.csv">100篇下载状态</a> · <a href="missing_fulltext.json">全文缺口</a> · <a href="architecture_analysis.json">结构化架构分析</a> · <a href="verification.json">最终核验</a></p>'
    design='''<section><h2>木耳采摘：建议先构建可观测、可回退的分阶段闭环</h2><p>下面是跨论文综合的工程设计建议，不是某篇论文原图，也不是已经验证的木耳采摘系统。</p><div class="flow"><span class="node">RGB-D与时间戳</span>→<span class="node">实例分割／附着点／置信度</span>→<span class="node">深度与运动估计</span>→<span class="node">粗接近PBVS</span>→<span class="node">近距离IBVS</span>→<span class="node">接触／分离控制</span>→<span class="node">采后核验与恢复</span></div><h3>1. 感知和控制用明确的数据接口连接</h3><p>感知层输出target_id、frame_id、采集时间、关键点/附着区域、深度与置信度；估计层输出当前状态、观测年龄与协方差。控制层消费这些量，不把“检测到目标”直接当成“可以执行采摘”。依据：2023-20、2025-18；时延设计启发来自2024-09、2024-21。</p><h3>2. 视觉接近与接触分离分开设计</h3><p>先实现稳定粗定位，再用近距离特征修正；接触后根据夹爪、力/力矩或可用电流反馈进入分离动作。没有力传感器时，不宣称实现了力控。2023-16的插入任务、2023-20的番茄切夹机构只能提供分阶段设计参考，不能替代木耳分离实验。</p><h3>3. 把视场和执行约束放在可检查的位置</h3><p>特征有效性、关节限位、运动速度、邻近菌体距离与控制超时应进入独立的执行检查。先用可解释的IBVS或MPC基线；需要时再加入2025-10的学习补偿或2026-10的MPC教师策略，并测试约束违规率和失配场景。</p><h3>4. 同时记录任务状态和失败证据</h3><p>建议状态：扫描→选择目标→粗接近→精定位→建立接触→分离→投放→采后核验；异常状态包括特征丢失、深度异常、碰撞风险、夹持失败和超时。任务协调可借鉴2024-03的ROS/SMACH；完成判据必须包含“是否采下、是否损伤、是否扰动邻体”，而不只看图像误差变小。</p><h3>5. 为柔软目标保留独立验证</h3><p>2024-23说明整体形变跟踪和物理模型可参与反馈，但其夹爪刚性附着和泡沫物体实验不包含菌体断裂。应先测量附着、形变、滑脱与分离过程，再判断是否需要FEM，而非先把高复杂度模型纳入控制主循环。</p><h3>最低对比实验</h3><p>比较一次定位开环、纯IBVS、混合PBVS/IBVS和加入约束后的方案。按未见菌棒/批次划分测试，记录完整采摘成功率、损伤/残留、邻体扰动、单次周期、人工干预、图像延迟、控制周期与丢失恢复率。论文不同任务的成功率不合并排名。</p></section>'''
    matrix='<section><h2>100篇文献与下载状态</h2><input id="q" placeholder="搜索论文、架构或状态"><div class="scroll"><table><thead><tr><th>编号</th><th>论文</th><th>全文状态</th><th>已核读架构</th><th>入口</th></tr></thead><tbody>'+''.join(table)+'</tbody></table></div></section>'
    script2="<script>q.oninput=function(){const q=this.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))}</script>"
    (out/'architecture_report.html').write_text(head+intro+design+matrix+'<section><h2>已取得全文的逐篇架构笔记</h2>'+''.join(cards)+'</section>'+script2+'</html>',encoding='utf8')
    checks=[]
    for r in rows:
        if r.get('pdf_path'):checks.append({'id':r['id'],'pdf_sha256_matches':sha(out/r['pdf_path'])==r['pdf_sha256'],'review_pages_valid':not r['architecture'] or all(1<=p<=r['pdf_pages'] for p in r['architecture']['pages'])})
    broken=[f['file'] for f in figures+assets+page_refs if not (out/'images'/f['file']).is_file()]
    mismatches=[f['file'] for f in figures+assets+page_refs if (out/'images'/f['file']).is_file() and sha(out/'images'/f['file'])!=f['sha256']]
    save(out/'verification.json',{'registered_unique_dois':len({r['doi'] for r in rows}),'downloaded_pdf_checks':checks,'broken_image_links':broken,'image_hash_mismatches':mismatches,'checked_image_links':len(figures+assets+page_refs),'checks_passed':all(c['pdf_sha256_matches'] and c['review_pages_valid'] for c in checks) and not broken and not mismatches,'coverage':'Partial full text; file integrity and links verified, not all image crops manually reviewed'})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--metadata',required=True);p.add_argument('--sources',nargs='+',required=True);p.add_argument('--notes',required=True);p.add_argument('--out',required=True);p.add_argument('--image-dir',default='images-v2');a=p.parse_args();build(a.metadata,a.sources,a.notes,a.out,a.image_dir)
