"""Procurement adapter for the existing research pipeline; no new HTTP engine.

prepare: read a roster XLSX; plan: build a collection-only v1 task using
verified seed URLs; export: validate reviewed records and produce seven columns.
Dates and award amounts must come from notice text. Unknowns remain blank.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re,zipfile
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

HEADERS=['项目名称','产品','招标单位','客户标签','中标单位','中标金额（万元）','来源与追溯']
AWARDS={'中标公告','成交公告','中标结果','成交结果','竞价结果','比价成交','合同公告','中标（成交）公告','中标结果公告','成交结果公告'}
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save_json(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def read_roster(book):
    with zipfile.ZipFile(book) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rel={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheet=next(s for s in ET.fromstring(z.read('xl/workbook.xml')).find('s:sheets',NS) if s.attrib['name']=='03-一级医院')
        target=rel[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
        target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        roster=[]
        for row in ET.fromstring(z.read(target)).findall('.//s:sheetData/s:row',NS):
            cells={}
            for c in row:
                value=c.find('s:v',NS);value=value.text if value is not None else ''
                if c.attrib.get('t')=='s':value=strings[int(value)]
                elif c.attrib.get('t')=='inlineStr':
                    el=c.find('s:is',NS);value=''.join(el.itertext()) if el is not None else ''
                cells[re.sub(r'\d','',c.attrib['r'])]=value
            if not str(cells.get('A','')).isdigit() or not cells.get('C'):continue
            roster.append({'id':int(cells['A']),'name':cells['C'],'district':cells.get('B',''),'category':cells.get('D',''),'level':cells.get('E',''),'medical_code':cells.get('F',''),'aliases':cells.get('G',''),'source_sheet':'03-一级医院','source_row':int(row.attrib['r'])})
        return roster

def amount_to_wan(raw,unit='万元'):
    if raw is None or raw=='':return None
    if isinstance(raw,bool):raise ValueError('金额不能是布尔值')
    s=str(raw).strip().replace(',','').replace('，','')
    if not re.fullmatch(r'\d+(?:\.\d+)?',s):raise ValueError('仅接受明确的非负金额数值')
    try:v=Decimal(s)
    except InvalidOperation:raise ValueError('无效金额') from None
    factors={'元':Decimal('0.0001'),'人民币元':Decimal('0.0001'),'万元':Decimal(1),'人民币万元':Decimal(1),'亿元':Decimal(10000)}
    if unit not in factors:raise ValueError('未知币种或金额单位，需人工核对')
    return float(v*factors[unit])

def build_task(candidates,folder,task_id,since,until):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    hosts={}
    for item in candidates:
        url=item.get('url','');p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username:continue
        hosts.setdefault(p.hostname,[])
        if url not in hosts[p.hostname]:hosts[p.hostname].append(url)
    if not hosts:raise ValueError('没有经发现的候选网址')
    sources=[{'id':'notice_'+hashlib.sha256(host.encode()).hexdigest()[:10],'name':host,'seeds':urls,'allowed_domains':[host]} for host,urls in sorted(hosts.items())]
    save_json(folder/'sources.json',{'version':1,'topic':'北京一级医院数智化招采公告原文','sources':sources})
    task={'schema_version':1,'task_id':task_id,'title':'北京一级医院数智化招采公告原文采集','question':'仅采集公开招标、中标、成交及合同原文并保留追溯信息，不进行市场分析。','research_type':'health_deployment','source_config':'sources.json','region':'北京市','scenarios':['医院数智化'],'allow_network':True,'stages':['collection'],'collection':{'mode':'crawl'},'time_range':{'basis':'publication','since':since,'until':until},'budget':{'max_pages':max(map(lambda s:len(s['seeds']),sources)),'max_depth':0,'workers':3,'delay':1,'timeout':20,'retries':0,'browser':False},'delivery':['json','markdown']}
    save_json(folder/'task.json',task)
    return {'sources':len(sources),'urls':sum(len(s['seeds']) for s in sources),'task':str(folder/'task.json')}

def validate_record(record,roster,since,until):
    r=dict(record);errors=[]
    try:hid=int(r.get('hospital_id'))
    except (TypeError,ValueError):hid=-1
    if hid not in roster:errors.append('医院不在一级医院名单')
    d=str(r.get('date',''))[:10]
    try:date.fromisoformat(d)
    except ValueError:errors.append('缺少可核对的公告日期')
    else:
        if d<since or d>until:errors.append('公告日期不在范围内')
    if not r.get('project_name'):errors.append('缺少项目名称')
    p=urlsplit(r.get('url',''))
    if p.scheme not in ('https','http') or not p.hostname:errors.append('缺少有效来源网址')
    if not r.get('quote'):errors.append('缺少原文证据')
    stage=str(r.get('announcement_type',''))
    confirmed_award=(stage in AWARDS or any(x in stage for x in ['中标结果','成交公告','成交结果','竞价结果','协议比价成交','中标公告'])) and not any(x in stage for x in ['候选','招标公告','采购意向','拟定','废标','终止','更正','取消'])
    if r.get('winner') not in (None,'') and not confirmed_award:
        errors.append('非确定成交结果不得填中标单位')
    amount=r.get('amount_wan')
    if amount not in (None,''):
        try:r['amount_wan']=amount_to_wan(amount,'万元')
        except ValueError as exc:errors.append(str(exc))
        if not confirmed_award:
            errors.append('非确定成交结果不得填中标金额')
        if not r.get('amount_quote'):errors.append('缺少中标金额原文，不能用预算代替')
        # Public mirrors sometimes redact the supplier while retaining the amount.
        # Keep each independently evidenced field; do not invent a winner.
    return r,errors

def identity(r):
    # Exact notice/package deduplication only; procurement/result stages remain distinct.
    return (r.get('hospital_id'),r.get('url','').split('#')[0],str(r.get('package','')),r.get('winner',''),r.get('amount_wan'))

def export_records(roster,records,output,since='2024-01-01',until='2026-10-26'):
    hospitals={int(h['id']):h for h in roster};accepted=[];rejected=[];seen=set()
    for raw in records:
        r,errors=validate_record(raw,hospitals,since,until)
        if errors:rejected.append({'record':r,'reasons':errors});continue
        key=identity(r)
        if key in seen:continue
        seen.add(key);h=hospitals[int(r['hospital_id'])]
        r['customer_label']='；'.join([h['level'],h['category'],h['district']])+'（按提供名单）'
        r['hospital_name']=h['name']
        accepted.append(r)
    accepted.sort(key=lambda r:(r['hospital_id'],r['date'],r['project_name']))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    save_json(output/'records.validated.json',accepted);save_json(output/'records.needs_review.json',rejected)
    with (output/'北京一级医院数智化招采信息.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(HEADERS)
        for r in accepted:
            trace='；'.join(filter(None,[r['announcement_type'],r['date'],r['url'],r.get('project_number',''),r.get('source_note','')]))
            row=[r['project_name'],r.get('product',''),r.get('purchaser',''),r['customer_label'],r.get('winner',''),r.get('amount_wan'),trace]
            writer.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for v in row])
    return {'accepted':len(accepted),'needs_review':len(rejected)}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('prepare');q.add_argument('--workbook',required=True);q.add_argument('--output',required=True)
    q=sub.add_parser('plan');q.add_argument('--candidates',required=True);q.add_argument('--output',required=True);q.add_argument('--task-id',required=True)
    q=sub.add_parser('export');q.add_argument('--roster',required=True);q.add_argument('--records',required=True);q.add_argument('--output',required=True)
    for q in list(sub.choices.values())[1:]:q.add_argument('--since',default='2024-01-01');q.add_argument('--until',default='2026-10-26')
    a=p.parse_args()
    if a.command=='prepare':r=read_roster(a.workbook);save_json(a.output,r);result={'hospitals':len(r)}
    elif a.command=='plan':result=build_task(read_json(a.candidates),a.output,a.task_id,a.since,a.until)
    else:result=export_records(read_json(a.roster),read_json(a.records),a.output,a.since,a.until)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
