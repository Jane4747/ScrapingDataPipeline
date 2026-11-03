"""Apply individually verified date/quotation corrections without changing the extractor.

Default CLI mode is read-only. --apply updates an already finished extraction.
Every correction is bound to an exact URL, immutable raw SHA, and literal evidence.
All hospital, digital-scope, amount and date-range gates remain in force.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup

import extractor as e

ROOT=Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review_items(payload):
    items=payload if isinstance(payload,list) else payload.get('reviews',[])
    if not isinstance(items,list):raise ValueError('Review file must contain a reviews array')
    return items


def page_document(page,base,review):
    if e.canonical_url(page.get('url',''))!=e.canonical_url(review.get('url','')):
        raise ValueError('Review URL mismatch')
    path=Path(page.get('raw_path',''))
    if not path.is_absolute():path=base/path
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=review.get('raw_sha256','').lower():raise ValueError('Review raw SHA mismatch')
    if page.get('sha256') and sha!=page['sha256'].lower():raise ValueError('Page raw SHA mismatch')
    source,body,whole,_=e.document_text(raw)
    return path,sha,source,body,whole


def verified_date(page,base,review):
    path,sha,source,body,whole=page_document(page,base,review)
    current=e.date_value(review.get('current_date',''))
    if not current or current!=review.get('current_date'):raise ValueError('Invalid reviewed date')
    evidence=review.get('current_date_evidence',{})
    proof_path=Path(evidence.get('path',''))
    if not proof_path.is_absolute():proof_path=base/proof_path
    if proof_path.resolve()!=path.resolve() or digest(proof_path)!=evidence.get('sha256'):
        raise ValueError('Current-date evidence path/SHA mismatch')
    kind=evidence.get('kind');quote=evidence.get('quote','')
    if kind not in {'body_text','raw_html'}:raise ValueError('Unsupported date-evidence kind')
    haystack=whole if kind=='body_text' else source
    if not quote or quote not in haystack or e.date_value(quote)!=current:
        raise ValueError('Current-date quote is absent or does not prove the reviewed date')
    prior=review.get('prior_publication_quotes',[])
    if not prior:raise ValueError('No individually verified preceding-announcement quotation')
    filtered=whole
    for old in prior:
        if (not isinstance(old,str) or old not in whole
                or not re.search(r'(?:采购|招标|磋商|询价|谈判)公告\s*发布(?:日期|时间)',old)
                or not e.date_value(old) or e.date_value(old)==current):
            raise ValueError('Invalid or absent preceding-announcement quotation')
        filtered=filtered.replace(old,'')
    actual,basis=e.publication_date(page,source,filtered)
    if actual!=current:
        raise ValueError('Other unresolved publication-date evidence remains: '+basis)
    return current,quote,prior


def extract_verified_date(page,base,review,scope_review=None,since='2024-01-01',until='2026-11-03'):
    current,quote,prior=verified_date(page,base,review)
    if not since<=current<=until:raise ValueError('Reviewed date outside requested interval')
    original=e.publication_date
    url=e.canonical_url(review['url'])
    def one_reviewed_date(candidate,raw,text):
        if e.canonical_url(candidate.get('url',''))==url:
            return current,'原文逐条日期复核（URL及SHA匹配）：'+e.normalize(quote)
        return original(candidate,raw,text)
    e.publication_date=one_reviewed_date
    try:
        row,reason=e.extract_one(page,base,'digital',scope_review)
    finally:
        e.publication_date=original
    if row:
        row['日期依据']+='；前序公告引用：'+'；'.join(e.normalize(x) for x in prior)
    return row,reason


def corrected_buyer_quote(row,page,base,review):
    _,sha,source,body,whole=page_document(page,base,review)
    if row.get('原文SHA256')!=sha:raise ValueError('Main-row raw SHA mismatch')
    if review.get('field')!='采购人依据':raise ValueError('Only the reviewed buyer quotation may be corrected')
    quote=review.get('body_quote','');value=review.get('new_value','')
    if (not quote or quote not in body or value!='医院采购主体原文：'+quote
            or not row.get('招标单位') or row['招标单位'] not in quote):
        raise ValueError('Buyer quotation is not the actual body title for this buyer')
    if row.get('采购人依据') not in {review.get('old_value'),value}:
        raise ValueError('Buyer evidence changed since the individual review')
    updated=dict(row);updated['采购人依据']=value
    return updated


def corrected_reviewed_buyer_quote(row,page,base,review):
    """Apply one URL/SHA-pinned buyer quote that was replayed against the raw page."""
    _,sha,source,body,whole=page_document(page,base,review)
    if row.get('原文SHA256')!=sha:raise ValueError('Main-row raw SHA mismatch')
    if review.get('decision')!='correct' or review.get('verified_raw_sha256') is not True:
        raise ValueError('Buyer review is not explicitly approved')
    quote=review.get('quote','');buyer=review.get('buyer','');value=review.get('corrected_buyer_basis','')
    selector=review.get('source_selector','')
    if not quote or not buyer or buyer not in quote or not value.endswith(quote):
        raise ValueError('Reviewed buyer quote/value mismatch')
    if selector and not selector.startswith('current_article_body:'):
        soup=BeautifulSoup(source,'html.parser')
        candidates=[e.normalize(x.get_text(' ',strip=True)) for x in soup.select(selector)]
        if e.normalize(quote) not in candidates or review.get('verified_current_element_exact_text') is not True:
            raise ValueError('Reviewed buyer heading is no longer exact')
    elif e.normalize(quote) not in e.normalize(body) and e.normalize(quote) not in e.normalize(whole):
        raise ValueError('Reviewed buyer body quote is absent')
    if row.get('采购人依据') not in {review.get('old_buyer_basis'),value}:
        raise ValueError('Buyer evidence changed since the review')
    updated=dict(row);updated['采购人依据']=value
    return updated


def combine_dedup_evidence(previous,current,rows):
    merged={}
    for item in previous+current:
        key=json.dumps(item['key'],ensure_ascii=False,sort_keys=True)
        old=merged.get(key)
        if old:
            members=[old['primary']]+old['aliases']+[item['primary']]+item['aliases']
            byurl={member['网址']:member for member in members}
            primary=item['primary']
            merged[key]={**item,'aliases':[member for url,member in byurl.items() if url!=primary['网址']]}
        else:merged[key]=item
    byurl={row['网址']:row for row in rows}
    for item in merged.values():
        row=byurl.get(item['primary']['网址'])
        if row and item['aliases']:
            source=row.get('采集来源','').split('；同原文其他网址：',1)[0]
            row['采集来源']=source+'；同原文其他网址：'+'；'.join(x['网址'] for x in item['aliases'])
    return list(merged.values())


def apply_reviews(pages,records,excluded,summary,date_reviews,field_reviews,base,
                  buyer_reviews=None,
                  scope_reviews=None,previous_dedup=None,since='2024-01-01',until='2026-11-03'):
    scope_reviews=scope_reviews or {};previous_dedup=previous_dedup or [];buyer_reviews=buyer_reviews or []
    bypage={e.canonical_url(p['url']):p for p in pages}
    byrow={e.canonical_url(r['网址']):dict(r) for r in records}
    remaining=list(excluded);receipts=[]
    for review in date_reviews:
        url=e.canonical_url(review.get('url',''))
        originals=[x for x in remaining if e.canonical_url(x.get('网址',''))==url and x.get('未纳入原因','').startswith('日期冲突')]
        receipt={'kind':'date_reference','url':url,'raw_sha256':review.get('raw_sha256'),
                 'original_exclusions':originals,
                 'original_exclusion_reasons':[x['未纳入原因'] for x in originals] or [review.get('original_exclusion_reason','')],
                 'review':review}
        try:
            if url not in bypage:raise ValueError('Reviewed URL not found in current pages')
            row,reason=extract_verified_date(bypage[url],base,review,scope_reviews.get(url),since,until)
            if not row:raise ValueError('Other extraction gate rejected the page: '+reason)
            old=byrow.get(url)
            receipt['status']='already_present_verified' if old and old.get('时间')==row['时间'] and old.get('原文SHA256')==row['原文SHA256'] else 'applied'
            byrow[url]=row
            remaining=[x for x in remaining if x not in originals]
            receipt.update(date=row['时间'],announcement_id=row['公告ID'])
        except (ValueError,OSError,KeyError) as exc:
            receipt.update(status='rejected',reason=str(exc))
        receipts.append(receipt)
    for review in field_reviews:
        url=e.canonical_url(review.get('url',''))
        receipt={'kind':'field_evidence','url':url,'raw_sha256':review.get('raw_sha256'),'review':review}
        try:
            if url not in bypage or url not in byrow:raise ValueError('Reviewed field URL absent from current pages/main rows')
            before=byrow[url]['采购人依据']
            byrow[url]=corrected_buyer_quote(byrow[url],bypage[url],base,review)
            receipt.update(status='already_present_verified' if before==byrow[url]['采购人依据'] else 'applied',
                           field='采购人依据',before=before,after=byrow[url]['采购人依据'])
        except (ValueError,OSError,KeyError) as exc:
            receipt.update(status='rejected',reason=str(exc))
        receipts.append(receipt)
    for review in buyer_reviews:
        url=e.canonical_url(review.get('url',''))
        receipt={'kind':'buyer_evidence','url':url,'raw_sha256':review.get('raw_sha256'),'review':review}
        try:
            if url not in bypage or url not in byrow:raise ValueError('Reviewed buyer URL absent from current pages/main rows')
            if any(e.canonical_url(x.get('url',''))==url for x in field_reviews):
                receipt.update(status='superseded_by_field_review',field='采购人依据',
                               before=byrow[url]['采购人依据'],after=byrow[url]['采购人依据'])
                receipts.append(receipt);continue
            before=byrow[url]['采购人依据']
            byrow[url]=corrected_reviewed_buyer_quote(byrow[url],bypage[url],base,review)
            receipt.update(status='already_present_verified' if before==byrow[url]['采购人依据'] else 'applied',
                           field='采购人依据',before=before,after=byrow[url]['采购人依据'])
        except (ValueError,OSError,KeyError) as exc:
            receipt.update(status='rejected',reason=str(exc))
        receipts.append(receipt)
    rows,new_dedup=e.deduplicate_same_document(list(byrow.values()))
    dedup=combine_dedup_evidence(previous_dedup,new_dedup,rows)
    rows.sort(key=lambda r:(r['时间'],r['医院名称'],r['项目名称']),reverse=True)
    revised=dict(summary)
    revised.update(generated_at=datetime.now(timezone.utc).isoformat(),records=len(rows),excluded=len(remaining),
                   exclusion_reasons=dict(Counter(x['未纳入原因'] for x in remaining)),
                   qualification_rows=sum(bool(r['响应人资格要求（对供应商基本要求）']) for r in rows),
                   prequalification_rows=sum(bool(r['资格预审资质要求']) for r in rows),
                   award_amount_rows=sum(r['中标金额（万元）'] is not None for r in rows),
                   main_table_entrance_count=len({r['入口任务ID'] for r in rows if r['入口任务ID']}),
                   main_table_hospital_name_count=len({r['医院名称'] for r in rows}),
                   year_counts=dict(sorted(Counter(r['时间'][:4] for r in rows).items())),
                   announcement_type_counts=dict(Counter(r['公告类型'] for r in rows)),
                   main_rows_with_matched_scope_review=sum('原文复核：' in r['标签依据'] for r in rows),
                   duplicate_same_document=sum(len(x['aliases']) for x in dedup),
                   verified_date_review_rows=sum(x['kind']=='date_reference' and x['status']!='rejected' for x in receipts),
                   verified_field_review_rows=sum(x['kind']=='field_evidence' and x['status']!='rejected' for x in receipts),
                   verified_buyer_review_rows=sum(x['kind']=='buyer_evidence' and x['status']!='rejected' for x in receipts),
                   verified_review_rejections=sum(x['status']=='rejected' for x in receipts))
    return rows,remaining,revised,dedup,receipts


def atomic_json(path,value):
    temporary=path.with_suffix(path.suffix+'.verified.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages',required=True);parser.add_argument('--output-dir',required=True)
    parser.add_argument('--date-reviews',default=str(ROOT/'review/date-reference-reviews.json'))
    parser.add_argument('--field-reviews',default=str(ROOT/'review/field-evidence-reviews.json'))
    parser.add_argument('--buyer-reviews',default=str(ROOT/'review/buyer-evidence-reviews.json'))
    parser.add_argument('--scope-review');parser.add_argument('--since',default='2024-01-01');parser.add_argument('--until',default='2026-11-03')
    parser.add_argument('--apply',action='store_true',help='Update the finished extraction; otherwise inspect proposed receipts only')
    args=parser.parse_args();out=Path(args.output_dir);pagefile=Path(args.pages)
    pages=e.read_json(pagefile);pages=pages.get('pages',pages) if isinstance(pages,dict) else pages
    scope={e.canonical_url(x['url']):x for x in review_items(e.read_json(args.scope_review))} if args.scope_review else {}
    previous=e.read_json(out/'dedup-evidence.json') if (out/'dedup-evidence.json').exists() else []
    records,excluded,summary,dedup,receipts=apply_reviews(pages,e.read_json(out/'records.json'),e.read_json(out/'excluded.json'),
        e.read_json(out/'summary.json'),review_items(e.read_json(args.date_reviews)),review_items(e.read_json(args.field_reviews)),
        pagefile.parent,review_items(e.read_json(args.buyer_reviews)),scope,previous,args.since,args.until)
    summary.update(date_reference_reviews_sha256=digest(args.date_reviews),field_evidence_reviews_sha256=digest(args.field_reviews),
                   buyer_evidence_reviews_sha256=digest(args.buyer_reviews),
                   verified_review_receipt=str((out/'verified-review-receipts.json').resolve()))
    receipt={'generated_at':datetime.now(timezone.utc).isoformat(),'extractor_sha256':digest(ROOT/'extractor.py'),
             'date_review_sha256':digest(args.date_reviews),'field_review_sha256':digest(args.field_reviews),
             'buyer_review_sha256':digest(args.buyer_reviews),
             'applied_to_files':args.apply,'items':receipts}
    if args.apply:
        for name,value in [('records',records),('excluded',excluded),('summary',summary),('dedup-evidence',dedup),('verified-review-receipts',receipt)]:
            atomic_json(out/(name+'.json'),value)
        temporary=out/'rows.csv.verified.tmp'
        with temporary.open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=e.COLUMNS);writer.writeheader();writer.writerows(records)
        temporary.replace(out/'rows.csv')
    print(json.dumps({'applied_to_files':args.apply,'records':len(records),'excluded':len(excluded),
                      'receipts':[{k:v for k,v in r.items() if k not in {'review','original_exclusions'}} for r in receipts]},ensure_ascii=False))


if __name__=='__main__':main()
