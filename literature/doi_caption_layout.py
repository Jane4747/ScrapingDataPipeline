"""Caption detection from physical text-object geometry.

Avoids duplicated/invisible searchable text layers whose search indices can point
above the visible caption. Crops cannot bridge the preceding caption boundary.
"""
import re
RX=re.compile(r'^(?:Supplementary\s+)?(?:Figure|FIGURE|Fig\.?)\s*([A-Z]?\d+(?:\.\d+)*|[A-Z]\.\d+)\s*[:.|]?\s*',re.I)
BODY=re.compile(r'^(?:shows?|illustrates?|presents?|summarizes?|reports?|compares?|provides?|displays?|lists?|demonstrates?|is|are|we|as|in|depicts?|describes?)\b',re.I)

def install(m):
    def captions(tp,page,height,graphics,objects):
        width=page.get_size()[0];found=[]
        # Start at the actual label object, never at a line merged across columns.
        starters=[o for o in objects if re.match(r'^\s*(?:Supplementary\s+)?(?:Figure|FIGURE|Fig\.)\s*',o.get('text',''))]
        for start in starters:
            b=start['bbox'];row=sorted([o for o in objects if abs(o['bbox'][1]-b[1])<4 and o['bbox'][0]>=b[0]-2],key=lambda o:o['bbox'][0])
            pieces=[];end=b[0]
            for obj in row:
                if pieces and obj['bbox'][0]-end>20:break
                pieces.append(obj);end=max(end,obj['bbox'][2])
            if not pieces:continue
            text=m.clean_text(' '.join(o['text'] for o in pieces));match=RX.match(text)
            if not match:continue
            tail=text[match.end():].strip()
            if BODY.match(tail):continue
            if any(c['number']==match[1] and abs(c['caption_bbox'][1]-b[1])<5 for c in found):continue
            line={'text':text,'bbox':m.union([o['bbox'] for o in pieces])}
            left=b[0]-4;right=width-25 if b[0]>width*.47 or end>width*.54 else width*.5-2
            following=[o for o in objects if o['bbox'][0]>=left and o['bbox'][2]<=right+4 and o['bbox'][1]>line['bbox'][1]+4 and o['bbox'][1]<line['bbox'][1]+140]
            lines=m.text_lines(following)
            chosen=[line];last=line['bbox'][3]
            for nxt in lines[:8]:
                b=nxt['bbox']
                if b[1]-last>9 or b[1]<last-2 or RX.match(nxt['text']):break
                if abs(b[0]-line['bbox'][0])>70:break
                chosen.append(nxt);last=b[3]
            cap=m.clean_text(' '.join(x['text'] for x in chosen))
            title=RX.sub('',cap);title=re.split(r'(?<=[a-z)])\.\s',title,maxsplit=1)[0]
            label='Figure '+match[1]
            found.append({'label':label,'number':match[1],'caption_bbox':line['bbox'],'caption_start':None,'snippet':cap,'initial_text':cap,'physical_caption_end':last,'physical_caption':cap,'physical_title':' '.join(title.split()[:18])})
        return found
    old_resolve=m.resolve_caption
    def resolve(pg,cap,mask):
        copy=mask.copy();y=cap['caption_bbox'][1];x=cap['caption_bbox'][0]
        previous=[c for c in pg['captions'] if c['caption_bbox'][1]<y-14 and (x<pg['width']*.47)==(c['caption_bbox'][0]<pg['width']*.47)]
        if previous:
            floor=max(c.get('physical_caption_end',c['caption_bbox'][3]) for c in previous)
            copy[:max(0,int(floor)+2),:]=False
        result=old_resolve(pg,cap,copy)
        if result:result.update(caption=cap['physical_caption'],caption_title=cap['physical_title'],method='Physical text-object caption + graphics-mask crop; previous-caption boundary')
        return result
    m.get_captions=captions;m.resolve_caption=resolve
