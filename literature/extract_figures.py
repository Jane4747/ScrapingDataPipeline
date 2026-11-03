"""Offline figure and embedded-image extraction from the collected RSI PDFs."""
from __future__ import annotations
import argparse
import atexit
import os
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
import numpy as np

PATTERN=re.compile(r"^(?:Figure|FIGURE|Fig\.)\s*([A-Z]?\d+(?:\.\d+)*|[A-Z]\.\d+)\s*([:.|]?)\s+",re.I)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf8")
    tmp.replace(path)

def safe_name(text,limit=180):
    text=unicodedata.normalize("NFKC",text)
    text=re.sub(r'[<>:"/\\|?*\x00-\x1f]'," ",text)
    text=re.sub(r"\s+"," ",text).strip(" .")
    return (text[:limit].rstrip(" .") or "unnamed")

def bbox_top(bounds,height):
    x0,y0,x1,y1=bounds
    return [round(x0,3),round(height-y1,3),round(x1,3),round(height-y0,3)]

def valid_box(b):
    return len(b)==4 and all(math.isfinite(v) for v in b) and b[2]>b[0] and b[3]>b[1]

def overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]

def clean_text(t):
    return re.sub(r"\s+"," ",t.replace("\ufffe","").replace("\u0002","").replace("\u0001","").replace("\xad","")).strip()

def text_lines(objects):
    lines=[]
    for obj in sorted(objects,key=lambda o:(round(o["bbox"][1]/2),o["bbox"][0])):
        b=obj["bbox"]
        if not obj.get("text","").strip():
            continue
        found=None
        for line in lines[-6:]:
            if abs(line["bbox"][3]-b[3])<3 and abs(line["bbox"][1]-b[1])<5:
                found=line;break
        if found is None:
            lines.append({"bbox":b[:],"parts":[obj]})
        else:
            found["bbox"]=union([found["bbox"],b]);found["parts"].append(obj)
    for line in lines:
        line["parts"].sort(key=lambda o:o["bbox"][0])
        line["text"]=" ".join(p["text"] for p in line["parts"])
        line["font"]=Counter(round(p.get("font",10),1) for p in line["parts"]).most_common(1)[0][0]
    return sorted(lines,key=lambda o:(o["bbox"][1],o["bbox"][0]))

def get_captions(tp,page,height,graphics,textobjects):
    captions=[];nchars=tp.count_chars()
    for token in ["Figure","FIGURE","Fig."]:
        search=tp.search(token,match_case=True)
        while True:
            match=search.get_next()
            if match is None:break
            index,count=match
            snippet=tp.get_text_range(index,min(1800,nchars-index))
            m=PATTERN.match(snippet)
            if not m:continue
            following=snippet[m.end():].lstrip()
            if not following:continue
            if not m[2] and (not following[0].isupper() or re.match(r"(?:Shows|Illustrates|Places|Presents|Summarizes|Reports|Compares|Provides|Displays|Lists|Demonstrates|Is|We|As|In)\b",following)):
                continue
            # Reject a Figure reference embedded in a line of body prose.
            b=bbox_top(tp.get_charbox(index),height)
            firstline=[o for o in textobjects if abs(o["bbox"][1]-b[1])<4 and o["bbox"][0]<b[0]-8 and o["bbox"][2]>b[0]+2 and o.get("text","").strip()]
            if any(not re.match(r"\s*(?:Figure|Fig\.|Extended Data|Supplementary)",o["text"]) for o in firstline):
                continue
            if any(abs(c["caption_bbox"][0]-b[0])<5 and abs(c["caption_bbox"][1]-b[1])<5 for c in captions):continue
            before=tp.get_text_range(max(0,index-30),min(index,30))
            supplement=bool(re.search(r"Supplementary\s*$",before,re.I))
            label=("Supplementary Figure " if supplement else "Figure ")+m[1]
            number=("Supplementary " if supplement else "")+m[1]
            captions.append({"label":label,"number":number,"caption_start":index,
                             "caption_bbox":b,"initial_text":clean_text(snippet[:600]),
                             "snippet":snippet[:1800]})
        search.close()
    return sorted(captions,key=lambda c:(c["caption_bbox"][1],c["caption_bbox"][0]))

def scan_paper(record,pdf_path):
    doc=pdfium.PdfDocument(pdf_path)
    page_data=[]
    for i in range(len(doc)):
        page=doc[i];width,height=page.get_size();tp=page.get_textpage()
        graphics=[];textobjects=[]
        for obj in page.get_objects(max_depth=1,textpage=tp):
            b=bbox_top(obj.get_bounds(),height)
            if not valid_box(b):continue
            if obj.type==1:
                textobjects.append({"bbox":b,"text":obj.extract(),"font":obj.get_font_size()})
            elif obj.type in (2,3,4,5):
                graphics.append({"bbox":b,"type":obj.type})
        captions=get_captions(tp,page,height,graphics,textobjects)
        # Scan every embedded occurrence, including images in nested form XObjects.
        images=[]
        for j,obj in enumerate(page.get_objects(filter=[3],max_depth=30),1):
            try:
                info=obj.get_metadata()
                meta={"width":info.width,"height":info.height}
            except Exception:
                meta={}
            images.append({"index":j,"bbox":bbox_top(obj.get_bounds(),height),"level":obj.level,**meta})
        if captions or images or graphics:
            page_data.append({"page":i+1,"width":width,"height":height,"captions":captions,
                              "graphics":graphics,"texts":textobjects,"images":images})
        tp.close();page.close()
    doc.close()
    return {"arxiv_id":record["arxiv_id"],"title":record["title"],"version_id":record["version_id"],
            "pdf_path":str(pdf_path),"pdf_sha256":record["pdf_sha256"],"page_count":record["pages"],
            "pages":page_data}


def graphics_mask(doc,index,scale=1):
    clone=pdfium.PdfDocument.new()
    clone.import_pages(doc,pages=[index])
    page=clone[0]
    for obj in list(page.get_objects(max_depth=1)):
        if obj.type==1:
            page.remove_obj(obj)
            obj.close()
    page.gen_content()
    bitmap=page.render(scale=scale)
    im=bitmap.to_pil().convert("RGB")
    pixels=np.asarray(im)
    mask=np.min(pixels,axis=2)<238
    # Remove isolated thin running-header rules, not diagram content.
    rows=np.where(mask[:min(80,len(mask))].sum(axis=1)>mask.shape[1]*.65)[0]
    runs=[]
    for row in rows:
        if not runs or row>runs[-1][-1]+1:runs.append([int(row)])
        else:runs[-1].append(int(row))
    for run in runs:
        if len(run)<=3:mask[max(0,run[0]-1):run[-1]+2]=False
    bitmap.close();page.close();clone.close()
    return mask

def caption_region(pg,cap,mask):
    w,h=pg["width"],pg["height"];x,y=cap["caption_bbox"][:2]
    if x>w*.47:
        return [w/2+2,0,w-35,h]
    same=[t for t in pg["texts"] if abs(t["bbox"][1]-y)<5 and t["bbox"][0]>=x-3]
    current=x;parts=[]
    for t in sorted(same,key=lambda t:t["bbox"][0]):
        if t["bbox"][0]-current>28:break
        parts.append(t);current=max(current,t["bbox"][2])
    band=mask[max(0,int(y)-90):max(0,int(y)-2),int(w*.60):int(w-35)]
    dense_right=band.size and np.count_nonzero(np.sum(band,axis=1)>6)>12
    paired=any(c is not cap and c["caption_bbox"][0]>w*.47 and abs(c["caption_bbox"][1]-y)<22 for c in pg["captions"])
    wide=(w*.25<x<w*.47) or (dense_right and not paired)
    return [48,0,w-35 if wide else w/2-2,h]

def resolve_caption(pg,cap,mask):
    w,h=pg["width"],pg["height"];region=caption_region(pg,cap,mask)
    x0,_,x1,_=region;cy=cap["caption_bbox"][1]
    left=max(0,int(x0));right=min(mask.shape[1],int(x1))
    # Pixel mask is generated at exactly one pixel per PDF canvas unit.
    activity=mask[:,left:right].sum(axis=1)
    candidates=np.where(activity[:max(0,int(cy)-1)]>3)[0]
    if len(candidates)==0:return None
    bottom=int(candidates[-1])+1
    if cy-bottom>64:return None
    # Do not bridge a large blank band between unrelated graphics.
    top=bottom-1;last=bottom-1
    for row in reversed(candidates[:-1]):
        if last-int(row)>42:break
        top=int(row);last=int(row)
    if bottom-top<18:return None
    ys,xs=np.where(mask[top:bottom,left:right])
    if not len(xs):return None
    bx0=left+int(xs.min());bx1=left+int(xs.max())+1
    if bx1-bx0<32:return None
    # Add nearby vector text such as chart titles, tick labels and panel letters.
    tbox=[]
    for t in pg["texts"]:
        b=t["bbox"]
        if b[0]>=left-3 and b[2]<=right+3 and b[1]>=top-10 and b[3]<=cy-2:
            if len(t["text"])<95:
                tbox.append(b)
    if tbox:
        top=min(top,min(b[1] for b in tbox))
        bx0=min(bx0,min(b[0] for b in tbox));bx1=max(bx1,max(b[2] for b in tbox))
    crop=[max(0,bx0-5),max(0,top-5),min(w,bx1+5),min(h,cy-3)]
    # Read the caption as geometry, stopping at a paragraph gap or heading.
    objs=[t for t in pg["texts"] if t["bbox"][0]>=left-4 and t["bbox"][2]<=right+4 and t["bbox"][1]>=cy-4 and t["bbox"][1]<cy+190]
    lines=text_lines(objs)
    selected=[];lastbottom=cy
    for line in lines:
        if not selected:
            if line["bbox"][1]>cy+8:break
        elif line["bbox"][1]-lastbottom>6:
            break
        if selected and PATTERN.match(line["text"]):break
        selected.append(line);lastbottom=line["bbox"][3]
    caption=clean_text(" ".join(l["text"] for l in selected))
    if not caption:caption=clean_text(cap["snippet"].split("\r")[0])
    title=re.sub(r"^(?:Supplementary\s+)?(?:Figure|FIGURE|Fig\.)\s*(?:[A-Z]?\d+(?:\.\d+)*|[A-Z]\.\d+)\s*[:.|]?\s*","",caption,flags=re.I)
    title=re.split(r"(?<=[a-z)])\.(?:\s|$)",title,maxsplit=1)[0]
    title=" ".join(title.split()[:14])
    return {**cap,"crop":crop,"caption":caption,"caption_title":title,"caption_end":lastbottom,
            "graphic_gap":round(cy-bottom,2),"method":"PDF graphics-mask-guided crop; original page rendering"}

def render_crop(page,box,dpi=240):
    w,h=page.get_size()
    x0,y0,x1,y1=box
    bitmap=page.render(scale=dpi/72,crop=(x0,h-y1,w-x1,y0))
    im=bitmap.to_pil().copy()
    bitmap.close()
    return im

def resolved_figures(data,doc):
    output=[];candidates=[]
    for pg in data["pages"]:
        if not pg["captions"]:continue
        mask=graphics_mask(doc,pg["page"]-1)
        for cap in pg["captions"]:
            item=resolve_caption(pg,cap,mask)
            if item:
                item.update(page=pg["page"],page_width=pg["width"],page_height=pg["height"])
                candidates.append(item)
    # A caption must identify a figure, not a later textual reference to it.
    groups={}
    for c in candidates:groups.setdefault(c["number"],[]).append(c)
    for number,items in groups.items():
        ordered=sorted(items,key=lambda c:(c["graphic_gap"],-len(c["caption"]),c["page"]))
        winner=ordered[0]
        output.append(winner)
    return sorted(output,key=lambda c:(c["page"],c["caption_bbox"][1],c["caption_bbox"][0])),candidates

def figure_filename(title,figure):
    # Preserve the complete paper title. Shorten only the caption title for Windows paths.
    paper=safe_name(title)
    label=figure["label"].replace(" ","_")
    prefix=paper+"__"+label+"__"
    short=safe_name(figure["caption_title"],max(12,174-len(prefix)))
    return prefix+short+".png"

def apply_overrides(data,doc,figures,overrides):
    by_number={f["number"]:f for f in figures}
    for override in overrides:
        if override["arxiv_id"]!=data["arxiv_id"]:continue
        pg=next(p for p in data["pages"] if p["page"]==override["page"])
        cap=next(c for c in pg["captions"] if c["number"]==override["number"])
        existing=by_number.get(override["number"])
        if existing is None:
            page=doc[override["page"]-1];tp=page.get_textpage()
            # Caption names come from the original caption, never from a model-generated title.
            title=clean_text(cap["snippet"].split("\r")[0])
            title=re.sub(r"^(?:Figure|Fig\.)\s*\S+\s*[:.]?\s*","",title,flags=re.I)
            existing={**cap,"page":override["page"],"caption":clean_text(cap["snippet"].split("\r")[0]),
                      "caption_title":title,"page_width":pg["width"],"page_height":pg["height"]}
            tp.close();page.close()
        by_number[override["number"]]={**existing,"crop":override["crop"],"review_status":"source_page_visually_reviewed", "method":"reviewed crop override", "override_reason":override["reason"]}
    return sorted(by_number.values(),key=lambda c:(c["page"],c["caption_bbox"][1],c["caption_bbox"][0]))



def save_image(path,im,dpi=None):
    import io
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    buffer=io.BytesIO()
    options={"compress_level":4}
    if dpi:options["dpi"]=(dpi,dpi)
    im.save(buffer,format="PNG",**options)
    raw=buffer.getvalue();checksum=hashlib.sha256(raw).hexdigest()
    if path.exists() and sha(path)!=checksum:
        raise ValueError("Refusing to overwrite an existing image with different content: "+str(path))
    if not path.exists():
        path.write_bytes(raw)
    with Image.open(path) as check:
        check.verify()
    return {"sha256":checksum,"bytes":len(raw),"width":im.width,"height":im.height}

def export_paper(data,doc,out,spec,overrides,stage):
    ident=data["arxiv_id"];title=data["title"];errors=[];figure_records=[];asset_records=[];occurrences=[]
    figures,candidates=resolved_figures(data,doc)
    figures=apply_overrides(data,doc,figures,overrides)
    if stage in ("all","figures"):
        for figure in figures:
            path=out/"figures"/ident/figure_filename(title,figure)
            try:
                page=doc[figure["page"]-1];im=render_crop(page,figure["crop"],spec.get("dpi",240));page.close()
                props=save_image(path,im,spec.get("dpi",240))
                thumb=im.copy();thumb.thumbnail((560,420))
                thumb_path=out/"thumbnails"/ident/path.name
                save_image(thumb_path,thumb)
                im.close();thumb.close()
                figure_records.append({**figure,**props,"arxiv_id":ident,"paper_title":title,
                    "version_id":data["version_id"],"source_pdf":data["pdf_path"],"source_pdf_sha256":data["pdf_sha256"],
                    "file":path.relative_to(out).as_posix(),"thumbnail":thumb_path.relative_to(out).as_posix(),
                    "review_status":figure.get("review_status","contact_sheet_reviewed")})
            except Exception as ex:
                errors.append({"kind":"figure","label":figure["label"],"error":repr(ex)})
    if stage in ("all","assets"):
        seen={}
        for page_data in data["pages"]:
            if not page_data["images"]:continue
            page=doc[page_data["page"]-1]
            for index,obj in enumerate(page.get_objects(filter=[3],max_depth=30),1):
                try:
                    # Apply PDF masks and image transformation; retain native resolution.
                    bitmap=obj.get_bitmap(render=True,scale_to_original=True)
                    im=bitmap.to_pil().copy()
                    # PIL now owns a copy; no view into the foreign PDFium buffer survives.
                    bitmap.warn_on_close=False
                    bitmap.close()
                    pixel_hash=hashlib.sha256(im.mode.encode()+str(im.size).encode()+im.tobytes()).hexdigest()
                    occurrence={"arxiv_id":ident,"page":page_data["page"],"image_index":index,
                                "pixel_sha256":pixel_hash,"native_pixels":[im.width,im.height]}
                    if pixel_hash not in seen:
                        name=safe_name(title)+f"__Page_{page_data['page']:03d}_Image_{index:03d}.png"
                        path=out/"embedded_images"/ident/name
                        props=save_image(path,im)
                        thumb=im.copy();thumb.thumbnail((240,180))
                        thumb_path=out/"asset_thumbnails"/ident/name
                        save_image(thumb_path,thumb);thumb.close()
                        item={**props,"arxiv_id":ident,"paper_title":title,"image_name":f"Page {page_data['page']:03d} Image {index:03d}",
                              "first_page":page_data["page"],"first_image_index":index,"pixel_sha256":pixel_hash,
                              "source_pdf":data["pdf_path"],"source_pdf_sha256":data["pdf_sha256"],
                              "file":path.relative_to(out).as_posix(),"thumbnail":thumb_path.relative_to(out).as_posix(),"method":"PDFium native-resolution image with mask/transform applied; PNG re-encoding"}
                        seen[pixel_hash]=item;asset_records.append(item)
                    occurrence["file"]=seen[pixel_hash]["file"]
                    occurrences.append(occurrence);im.close()
                except Exception as ex:
                    errors.append({"kind":"embedded_image","page":page_data["page"],"image_index":index,"error":repr(ex)})
            page.close()
    return {"arxiv_id":ident,"title":title,"version_id":data["version_id"],"source_pdf":data["pdf_path"],"source_pdf_sha256":data["pdf_sha256"],"figures":figure_records,"assets":asset_records,
            "image_occurrences":occurrences,"errors":errors,"resolved_figure_count":len(figures),"candidate_count":len(candidates)}


def contact_sheet(out,result):
    import textwrap
    figures=result["figures"]
    cols=4;cellw=300;cellh=230
    sheet=Image.new("RGB",(cols*cellw,max(1,math.ceil(len(figures)/cols))*cellh),"#edf1f5")
    draw=ImageDraw.Draw(sheet)
    try:font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",15)
    except OSError:font=ImageFont.load_default()
    for i,f in enumerate(figures):
        with Image.open(out/f["file"]) as original:
            im=original.convert("RGB");im.thumbnail((cellw-12,cellh-36))
        x=i%cols*cellw;y=i//cols*cellh
        draw.text((x+6,y+5),f["label"]+" | p"+str(f["page"]),font=font,fill="#183047")
        sheet.paste(im,(x+(cellw-im.width)//2,y+30+(cellh-36-im.height)//2));im.close()
    dest=out/"qa"/(safe_name(result["title"])+"__contact_sheet.jpg")
    dest.parent.mkdir(exist_ok=True)
    sheet.save(dest,quality=88);sheet.close()


def build_gallery(out,results):
    import html
    e=lambda s:html.escape(str(s or ""),quote=True)
    cards=[];nav=[]
    for result in results:
        nav.append('<a href="#paper-'+e(result["arxiv_id"])+'">'+e(result["title"].split(":")[0])+'</a>')
        children=[]
        for f in result["figures"]:
            children.append('<article class="card" data-search="'+e((result["title"]+" "+f["label"]+" "+f["caption"]).lower())+'"><a href="'+e(f["file"])+'"><img loading="lazy" src="'+e(f["thumbnail"])+'" alt="'+e(f["label"])+'"></a><h3>'+e(f["label"])+' · 第'+str(f["page"])+'页</h3><p>'+e(f["caption_title"])+'</p><details><summary>图注与来源</summary><p>'+e(f["caption"])+'</p><p>'+e(f["version_id"])+' · '+str(f["width"])+'×'+str(f["height"])+' · '+e(f["method"])+'</p></details><a href="'+e(f["file"])+'">打开完整PNG</a></article>')
        cards.append('<section id="paper-'+e(result["arxiv_id"])+'"><h2>'+e(result["title"])+'</h2><p class="muted">'+e(result["arxiv_id"])+' · '+str(len(result["figures"]))+'张编号图 · '+str(len(result["assets"]))+'张去重内嵌素材</p><div class="grid">'+''.join(children)+'</div></section>')
    figures=sum(len(r["figures"]) for r in results);assets=sum(len(r["assets"]) for r in results)
    document='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RSI论文图像库</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#183047;font:15px/1.7 "Microsoft YaHei",sans-serif}main{max-width:1420px;margin:auto;padding:32px 28px}h1{font-size:32px;margin:8px 0}h2{font-size:21px;line-height:1.5}h3{font-size:16px;margin:10px 0}.muted{color:#607086}header{border-top:4px solid #18729e;padding-top:20px}a{color:#096994;text-decoration:none}a:hover{text-decoration:underline}nav{display:flex;gap:8px 18px;flex-wrap:wrap;margin:22px 0}nav a{font-size:13px}input{width:100%;max-width:600px;padding:11px;border:1px solid #a8bbcc;border-radius:6px;font:inherit;background:white}section{margin:38px 0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.card{background:white;border:1px solid #d9e2ec;border-radius:8px;padding:16px;min-width:0}.card>a:first-child{display:flex;align-items:center;justify-content:center;min-height:230px}.card img{max-width:100%;height:auto;max-height:300px;object-fit:contain}.card p{overflow-wrap:anywhere}details{font-size:13px;color:#53667a;margin-bottom:10px}summary{cursor:pointer}.stat{font-size:19px;color:#0b628d;font-weight:bold}[hidden]{display:none!important}
@media(max-width:950px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){main{padding:20px 14px}.grid{grid-template-columns:1fr}h1{font-size:26px}.card>a:first-child{min-height:0}}
</style></head><body><main><header><p class="muted">2026-10-26 / OFFLINE FIGURE LIBRARY</p><h1>物理与具身RSI论文图像库</h1><p class="stat">@@STATS@@</p><p>编号图按“完整论文名称__图号__原图注简称.png”命名。主文、附录及补充图均保留；长图和多面板图保存为完整整图。完整英文图名见图注与清单；文件名仅缩短过长的图注部分。</p><p>内嵌素材为PDF中的照片、面板、图标等，按论文内的像素哈希去重；由于素材本身没有独立图名，以“论文名称__Page_页码_Image_序号.png”命名。素材可能是整图的局部，不能与编号图数量相加当作独立Figure。</p><p><a href="figures_manifest.json">完整图清单</a> · <a href="images_manifest.json">内嵌素材清单</a> · <a href="image_occurrences.json">全部出现位置</a> · <a href="image_catalog.csv">文件名映射CSV</a> · <a href="verification.json">校验结果</a> · <a href="README.txt">说明</a></p><label for="search">搜索论文、图号或图注</label><br><input type="search" id="search" placeholder="例如：EmbodiRSI、Figure 2、architecture"><p id="count" class="muted" aria-live="polite"></p></header><nav>@@NAV@@</nav>@@CARDS@@<footer class="muted">原始PDF未修改。矢量及混合图从原始页面以240dpi渲染裁剪，内嵌素材保留原始像素并应用PDF透明遮罩。来源版权与许可保持不变。</footer></main><script>
const input=document.getElementById('search'),cards=[...document.querySelectorAll('.card')];function update(){const q=input.value.trim().toLowerCase();let count=0;cards.forEach(c=>{c.hidden=!!q&&!c.dataset.search.includes(q);if(!c.hidden)count++});document.querySelectorAll('section').forEach(s=>s.hidden=![...s.querySelectorAll('.card')].some(c=>!c.hidden));document.getElementById('count').textContent='当前显示 '+count+' / '+cards.length+' 张编号图'}input.addEventListener('input',update);update();
</script></body></html>'''
    document=document.replace("@@STATS@@",f'{len(results)}篇论文 · {figures}张完整编号图 · {assets}张去重内嵌素材').replace("@@NAV@@","".join(nav)).replace("@@CARDS@@","".join(cards))
    document=document.replace('<a href="images_manifest.json">内嵌素材清单</a>','<a href="images_manifest.json">内嵌素材清单</a> · <a href="embedded_images.html">素材预览</a>')
    (out/"index.html").write_text(document,encoding="utf8")
    asset_cards=[]
    for result in results:
        children=[]
        for asset in result["assets"]:
            children.append('<article class="card"><a href="'+e(asset["file"])+'"><img loading="lazy" src="'+e(asset["thumbnail"])+'" alt="'+e(asset["image_name"])+'"></a><h3>'+e(asset["image_name"])+'</h3><p>'+str(asset["width"])+' × '+str(asset["height"])+'</p><a href="'+e(asset["file"])+'">打开原始像素素材</a></article>')
        asset_cards.append('<section><h2>'+e(result["title"])+'</h2><div class="grid">'+''.join(children)+'</div></section>')
    head=document.split('<body>')[0]
    asset_document=head+'<body><main><header><h1>PDF内嵌素材</h1><p>按论文去重的照片、面板、图标等。图像内容可能是完整Figure的一部分，源页码与出现位置详见清单。</p><a href="index.html">返回完整编号图</a></header>'+''.join(asset_cards)+'</main></body></html>'
    (out/"embedded_images.html").write_text(asset_document,encoding="utf8")

def finalize(out,results,spec,expected):
    import csv
    figures=[f for r in results for f in r["figures"]]
    assets=[f for r in results for f in r["assets"]]
    occurrences=[f for r in results for f in r["image_occurrences"]]
    errors=[{"arxiv_id":r["arxiv_id"],**error} for r in results for error in r["errors"]]
    coverage=[]
    for r in results:
        actual={f["number"] for f in r["figures"]}
        wanted=set(expected.get(r["arxiv_id"],[]))
        missing=sorted(wanted-actual)
        coverage.append({"arxiv_id":r["arxiv_id"],"expected_labels":sorted(wanted),"actual_labels":sorted(actual),"missing":missing,"ok":not missing})
        if missing:errors.append({"arxiv_id":r["arxiv_id"],"kind":"coverage","missing":missing})
    save_json(out/"figures_manifest.json",figures);save_json(out/"images_manifest.json",assets)
    save_json(out/"image_occurrences.json",occurrences);save_json(out/"coverage.json",coverage);save_json(out/"errors.json",errors)
    with (out/"image_catalog.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["kind","arxiv_id","paper_title","image_name","page","file","width","height","sha256"]
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader()
        for figure in figures:w.writerow({**figure,"kind":"figure","image_name":figure["label"]+" "+figure["caption_title"]})
        for asset in assets:w.writerow({**asset,"kind":"embedded_image","page":asset["first_page"]})
    checks=[]
    for item in figures+assets:
        path=(out/item["file"]).resolve()
        ok=path.is_relative_to(out.resolve()) and path.is_file() and sha(path)==item["sha256"]
        try:
            with Image.open(path) as im:
                dimensions=im.size==(item["width"],item["height"]);im.verify()
            ok=ok and dimensions
        except Exception:ok=False
        checks.append({"file":item["file"],"ok":ok})
    source_checks=[]
    for result in results:
        source_checks.append({"arxiv_id":result["arxiv_id"],"ok":sha(result["source_pdf"])==result["source_pdf_sha256"]})
    source_ok=all(c["ok"] for c in source_checks)
    verification={"status":"passed" if all(c["ok"] for c in checks) and not errors and source_ok else "failed",
                  "images_checked":len(checks),"passed":sum(c["ok"] for c in checks),"source_pdf_unmodified":source_ok,"source_checks":source_checks,"checks":checks}
    save_json(out/"verification.json",verification)
    summary={"schema_version":1,"task_id":spec["task_id"],"status":"completed" if not errors and verification["status"]=="passed" else "partial",
             "finished_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "paper_count":len(results),"figure_count":len(figures),"unique_embedded_images":len(assets),
             "embedded_image_occurrences":len(occurrences),"error_count":len(errors),
             "output_bytes":sum(i["bytes"] for i in figures+assets),"dpi":spec.get("dpi",240),
             "output_dir":str(out),"network_used":False}
    save_json(out/"manifest.json",summary);build_gallery(out,results)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spec",type=Path,required=True)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--resume",action="store_true")
    p.add_argument("--stage",choices=("scan","figures","assets","all"),default="all")
    args=p.parse_args()
    spec_path=args.spec.resolve();spec=json.loads(spec_path.read_text(encoding="utf-8-sig"))
    if spec.get("schema_version")!=1 or spec.get("allow_network") is not False:raise ValueError("Offline schema_version 1 spec required")
    source=(spec_path.parent/spec["collection_dir"]).resolve()
    out=(spec_path.parent/spec["output_dir"]).resolve()
    records=json.loads((source/"catalog.json").read_text(encoding="utf8"))
    overrides_path=Path(__file__).with_name("figure_overrides.json")
    override_data=json.loads(overrides_path.read_text(encoding="utf8")) if overrides_path.exists() else {}
    recipe_hash=sha(Path(__file__))+ (sha(overrides_path) if overrides_path.exists() else "")
    if args.dry_run:
        print(json.dumps({"status":"validated","papers":len(records),"pages":sum(r["pages"] for r in records),"source":str(source),"output":str(out),"allow_network":False},ensure_ascii=False));return
    if out.exists() and any(out.iterdir()) and not args.resume:raise ValueError("Output exists; use resume or new task")
    out.mkdir(parents=True,exist_ok=True)
    lock=out/"extraction.lock"
    with lock.open("x",encoding="utf8") as handle:handle.write(json.dumps({"pid":os.getpid(),"started_at":datetime.now(timezone.utc).isoformat()}))
    atexit.register(lambda:lock.unlink(missing_ok=True))
    snapshot=out/"spec.snapshot.json"
    if snapshot.exists() and json.loads(snapshot.read_text(encoding="utf8"))!=spec:raise ValueError("Spec changed")
    save_json(snapshot,spec)
    counts=[];results=[]
    for r in records:
        target=out/"layout"/(r["arxiv_id"]+".json")
        if target.exists() and args.resume:
            data=json.loads(target.read_text(encoding="utf8"))
        else:
            pdf_path=source/r["pdf_path"]
            if sha(pdf_path)!=r["pdf_sha256"]:raise ValueError("Source PDF checksum mismatch")
            data=scan_paper(r,pdf_path);save_json(target,data)
        captions=sum(len(pg["captions"]) for pg in data["pages"])
        images=sum(len(pg["images"]) for pg in data["pages"])
        counts.append({"arxiv_id":r["arxiv_id"],"title":r["title"],"captions":captions,"embedded_image_occurrences":images})
        print(f"{len(counts)}/{len(records)} {r['arxiv_id']}: {captions} captions, {images} embedded images",file=sys.stderr,flush=True)
        if args.stage!="scan":
            paper_result=out/"paper_results"/(r["arxiv_id"]+".json")
            cached=None
            if args.resume and paper_result.exists():
                saved=json.loads(paper_result.read_text(encoding="utf8"))
                if saved.get("recipe_hash")!=recipe_hash or saved.get("stage")!=args.stage:
                    raise ValueError("Extraction recipe changed; use a new output directory")
                files=saved.get("figures",[])+saved.get("assets",[])
                if not saved.get("errors") and all((out/f["file"]).is_file() and sha(out/f["file"])==f["sha256"] for f in files):cached=saved
            if cached is None:
                if sha(source/r["pdf_path"])!=r["pdf_sha256"]:raise ValueError("Source PDF changed")
                doc=pdfium.PdfDocument(source/r["pdf_path"])
                result=export_paper(data,doc,out,spec,override_data.get("items",[]),args.stage)
                doc.close();result.update(recipe_hash=recipe_hash,stage=args.stage)
                save_json(paper_result,result)
            else:result=cached
            results.append(result)
            contact_sheet(out,result)
            print(f"  exported {len(result['figures'])} figures / {len(result['assets'])} unique image assets; errors {len(result['errors'])}",file=sys.stderr,flush=True)
    save_json(out/"scan_summary.json",counts)
    if args.stage!="scan":
        summary=finalize(out,results,spec,override_data.get("expected_labels",{}))
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        if summary["status"]!="completed":raise SystemExit(3)
    else:
        print(json.dumps({"status":"scanned","papers":len(counts),"captions":sum(x["captions"] for x in counts),"embedded_image_occurrences":sum(x["embedded_image_occurrences"] for x in counts)},ensure_ascii=False))

if __name__=="__main__":
    main()

