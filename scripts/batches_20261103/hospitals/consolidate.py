"""Assemble immutable notice evidence and account for every original roster ID."""
from pathlib import Path
import os
from collections import Counter, defaultdict
from datetime import datetime,timezone
import json
ROOT=Path(__file__).resolve().parent;RUN=Path(os.environ.get('HOSPITAL_BATCH_RUN', str(ROOT.parents[2]/'outputs/hospital-batch-20261103')))
def read(p,default=None):
    return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else default
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp')
    t.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def split(v):return [x for x in str(v or '').replace(';','；').split('；') if x]
def main():
    entries=read(RUN/'entrances.json')['entrances'];roster=read(RUN/'roster.json');pages=[];coverage=[]
    seedfiles=[p for p in sorted(RUN.glob('seed-pages-*.json')) if not p.name.endswith(('-receipt.json','-pending.json'))]
    seedpages=[item for p in seedfiles for item in read(p,[])]
    pubpages=read(RUN/'public/pages.json',[])
    if isinstance(pubpages,dict):pubpages=pubpages.get('pages',[])
    livepages=read(RUN/'public/live-pages.json',[])
    if isinstance(livepages,dict):livepages=livepages.get('pages',[])
    linkedpages=read(RUN/'public/linked-pages.json',[])
    if isinstance(linkedpages,dict):linkedpages=linkedpages.get('pages',[])
    renderpages=read(RUN/'render/pages.json',[])
    if isinstance(renderpages,dict):renderpages=renderpages.get('pages',[])
    ajaxpages=read(RUN/'render/ajax-pages.json',[])
    if isinstance(ajaxpages,dict):ajaxpages=ajaxpages.get('pages',[])
    renderpages=renderpages+ajaxpages
    renderbytask=defaultdict(list)
    for item in renderpages:renderbytask[item.get('task_id','')].append(item)
    adaptercoverage=defaultdict(list)
    for item in read(RUN/'render/ajax-coverage.json',[]):adaptercoverage[item.get('task_id','')].append(item)
    remainingbytask={m['task_id']:m for m in read(RUN/'final-remaining-manifest.json',[])}
    pubpages=pubpages+livepages+linkedpages
    publicbyid=defaultdict(list);externalbyid=defaultdict(list)
    overrides=read(RUN/'review/entrance-overrides.json',{})
    for item in read(RUN/'public/linked-coverage.json',[]):
        for ident in split(item.get('hospital_ids')):externalbyid[ident].append(item)
    for p in pubpages+seedpages:
        for ident in split(p.get('hospital_ids')):publicbyid[ident].append(p)
    for e in entries:
        d=RUN/'sites'/e['task_id'];p=read(d/'pages.json',[]);s=read(d/'summary.json')
        combined=p+renderbytask[e['task_id']]
        p=list({(item.get('url'),item.get('sha256'),item.get('hospital_ids')):item for item in combined}.values())
        if not s:s={'status':'running' if (d/'collector.lock').exists() else 'not_attempted','coverage_complete':False,'stop_reason':'入口尚未结束本轮采集'}
        override=overrides.get(e['task_id'],{})
        if override.get('status')=='entry_pending':
            p=[{**item,'entrance_verified':False,'association_verified':False,
                'entry_identity_warning':override.get('stop_reason','入口主体未确认')} for item in p]
        pages.extend(p)
        record={**e,**s,'url':e['url'],'saved_page_rows':len(p)}
        lists=read(d/'list_pages.json',[])
        if s.get('status')=='partial' and not any(x.get('status')=='ok' for x in p+lists):
            record['status']='failed'
        if s.get('status')=='failed' and any(x.get('status')=='ok' for x in renderbytask[e['task_id']]):
            record['status']='partial'
        if override:record.update(override)
        extras=adaptercoverage[e['task_id']]
        if extras:
            record['adapter_receipts']=extras
            record['list_requests']=record.get('list_requests',0)+sum(x.get('list_requests',0) for x in extras)
            record['gaps']=list(dict.fromkeys(record.get('gaps',[])+[g for x in extras for g in x.get('gaps',[])]))
            record['coverage_note']='；'.join(f"公开列表接口另访问{x.get('list_requests',0)}页，取得{x.get('successful_details',0)}条详情；接口声明{x.get('observed_total_records','未披露')}条公告，尚未全部取得" for x in extras)
        remaining=remainingbytask.get(e['task_id'])
        if remaining:
            record['remaining_discovery_receipt']=remaining
            detail=f"已发现但未取得正文的候选{remaining.get('unfetched_candidates',0)}条，其中标题数字化候选{remaining.get('unfetched_digital_titles',0)}条；待访问列表页{remaining.get('pending_lists',0)}个；累计失败至少两次的候选{remaining.get('retry_limited_candidates',0)}条"
            record['stop_reason']='；'.join(x for x in [record.get('stop_reason',''),detail] if x)
        dates=sorted(x['date'] for x in p if x.get('status')=='ok' and x.get('date'))
        record['earliest_date']=dates[0] if dates else '';record['latest_date']=dates[-1] if dates else ''
        supplements={x['url'] for h in e['hospital_entities'] for x in publicbyid[h['id']]}
        if supplements:record['coverage_note']='；'.join(x for x in [record.get('coverage_note',''),f'另有历史留存或公共采购平台原文候选{len(supplements)}条，需以主表采购人核验后的纳入数为准'] if x)
        external={x['url']:x for h in e['hospital_entities'] for x in externalbyid[h['id']]}
        if external:
            record['external_link_receipts']=list(external.values())
            note=f'院站直接官方外链补查{len(external)}条：'+'；'.join(dict.fromkeys(x.get('stop_reason','') for x in external.values()))
            record['stop_reason']='；'.join(x for x in [record.get('stop_reason',''),note] if x)
        coverage.append(record)
    for r in roster:
        if r['task_id']:continue
        e=r['entity'];pub=publicbyid[e['id']];source=r['source'];urls=list(dict.fromkeys(x['url'] for x in pub))
        coverage.append({'task_id':'ROSTER-'+e['id'],'hospital':e['name'],'hospital_ids':e['id'],'province':e['province'],
            'url':'','status':'public_only' if pub else 'no_entry','coverage_complete':False,
            'list_requests':0,'saved_page_rows':len(pub),'earliest_date':min((p.get('date') or '9999' for p in pub),default=''),
            'latest_date':max((p.get('date') or '' for p in pub),default=''),
            'stop_reason':'原清单未有已核验的可抓院级入口；'+('已取得历史留存或公共平台原文候选，逐条主体/范围复核' if pub else '官方平台既有原文与本轮已发现线索中暂未匹配可用公告；不等于该院没有数字化采购'),
            'original_entrance_status':source.get('采购入口状态',''),'original_home_status':source.get('官网核验状态',''),
            'public_evidence_urls':urls,'original_source_row':e['source_row']})
    pages.extend(pubpages);pages.extend(seedpages)
    entry_ids={e['task_id'] for e in entries}
    pages.extend(p for p in renderpages if p.get('task_id') not in entry_ids)
    seen=set();unique=[]
    # Keep multiple provenance variants until extraction chooses the most useful
    # readable content, but avoid duplicated identical acquisition entries.
    for p in pages:
        key=(p.get('url'),p.get('sha256'),p.get('hospital_ids'))
        if key in seen:continue
        seen.add(key);unique.append(p)
    seedrecordfiles=[p for p in sorted(RUN.glob('seed-records-*.json')) if not p.name.endswith(('-receipt.json','-holds.json','-pending.json'))]
    seedrecordkeys={(r.get('网址'),r.get('原文SHA256'),r.get('医院ID')) for f in seedrecordfiles for r in read(f,[])}
    def provenance_kind(page):
        value=page.get('provenance',{})
        return str(value.get('kind','')) if isinstance(value,dict) else str(value)
    seeded_delivery_kinds={'historical_completed_region_seed','historical_beijing_xiongan_delivery',
                           'historical_puh3_reviewed_notice','historical_official_review_bundle'}
    extraction_pages=[p for p in unique if provenance_kind(p) not in seeded_delivery_kinds
                      and (p.get('url'),p.get('sha256'),p.get('hospital_ids')) not in seedrecordkeys]
    assert {r['entity']['id'] for r in roster}=={i for c in coverage for i in split(c.get('hospital_ids'))}
    write(RUN/'pages.json',unique);write(RUN/'extraction-pages.json',extraction_pages);write(RUN/'coverage.json',coverage)
    report={'as_of':datetime.now(timezone.utc).isoformat(),'original_roster_records':len(roster),'crawl_entries':len(entries),
        'coverage_rows':len(coverage),'input_pages':len(unique),'extraction_pages':len(extraction_pages),'public_pages':len(pubpages),'seed_pages':len(seedpages),
        'seed_page_files':[str(p) for p in seedfiles],
        'seed_record_files':[str(p) for p in seedrecordfiles],
        'page_statuses':dict(Counter(p.get('status') for p in unique)),
        'entrance_statuses':dict(Counter(c['status'] for c in coverage)),
        'all_original_ids_accounted_for':True}
    write(RUN/'consolidation.json',report);print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
