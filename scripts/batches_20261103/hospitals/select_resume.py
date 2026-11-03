"""Choose evidenced continuation queues, excluding denied/challenged domains."""
from pathlib import Path
import os
import json,hashlib,argparse
from collector import read_json,write_json,extract_listing,digital_hits,lp,url_failure_counts,detail_skip_reason
ROOT=Path(__file__).resolve().parent;RUN=Path(os.environ.get('HOSPITAL_BATCH_RUN', str(ROOT.parents[2]/'outputs/hospital-batch-20261103')))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--skip-reparse',action='store_true')
    parser.add_argument('--details-only',action='store_true');parser.add_argument('--digital-titles-only',action='store_true');args=parser.parse_args()
    skip_reparse=args.skip_reparse or args.details_only
    contract=read_json(RUN/'contract.json')
    since=contract['since'];until=contract['until']
    entries=read_json(RUN/'entrances.json')['entrances'];selected=[];manifest=[];updates=0
    overrides=read_json(RUN/'review/entrance-overrides.json') if (RUN/'review/entrance-overrides.json').exists() else {}
    for e in entries:
        d=RUN/'sites'/e['task_id']
        if (d/'collector.lock').exists() or not (d/'summary.json').exists():continue
        s=read_json(d/'summary.json')
        failures=str(s.get('failures',[]))+' '+str(s.get('gaps',[]))
        denied=any(x in failures for x in ['robots_denied','detail_access_challenge','hospital_identity_mismatch']) or overrides.get(e['task_id'],{}).get('status')=='entry_pending'
        items={x['url']:x for x in read_json(d/'discovered_items.json')} if (d/'discovered_items.json').exists() else {}
        pages=read_json(d/'pages.json') if (d/'pages.json').exists() else []
        pagebyurl={x['url']:x for x in pages}
        for row in read_json(d/'list_pages.json') if (d/'list_pages.json').exists() and not skip_reparse else []:
            if row.get('status')!='ok' or not row.get('raw_path') or not lp(row['raw_path']).exists() or denied:continue
            for item in extract_listing(lp(row['raw_path']).read_bytes(),row['url']):
                item.update(listing_raw_path=row['raw_path'],listing_sha256=row.get('sha256',''))
                items[item['url']]={**items.get(item['url'],{}),**item}
                p=pagebyurl.get(item['url'])
                if p:
                    p['procurement_context']=p.get('procurement_context',False) or item.get('procurement_context',False)
                    if item.get('date') and p.get('date_basis')!='detail_publication':
                        if p.get('date')!=item['date']:updates+=1
                        p.update(date=item['date'],date_basis='exact_listing_row',listing_url=item['listing_url'],
                                 date_source_path=row['raw_path'],date_source_sha256=row.get('sha256',''),
                                 in_date_range=since<=item['date']<=until)
        if not skip_reparse:
            write_json(d/'discovered_items.json',list(items.values()));write_json(d/'pages.json',pages)
        state=read_json(d/'listing_state.json') if (d/'listing_state.json').exists() else {}
        eligible=[x for x in items.values() if not x.get('date') or since<=x['date']<=until]
        counts=url_failure_counts(s.get('failures',[]))
        remaining=[x for x in eligible if not detail_skip_reason(pagebyurl.get(x['url']),counts[x['url']])]
        retry_limited=sum(detail_skip_reason(pagebyurl.get(x['url']),counts[x['url']])=='retry_limit' for x in eligible)
        digital=[x for x in remaining if digital_hits(x.get('title',''))]
        lists=state.get('pending',[])
        targeted=digital if args.digital_titles_only else remaining
        want=not denied and bool(targeted or (lists and not args.details_only))
        if want:selected.append(e['task_id'])
        gaps=[]
        if args.details_only and lists:gaps.append('pending_lists_not_visited_in_details_only_pass')
        if args.digital_titles_only and len(remaining)>len(digital):gaps.append('non_digital_titles_not_fetched_in_targeted_pass')
        if retry_limited:gaps.append('detail_retry_limit_reached')
        manifest.append({'task_id':e['task_id'],'hospital':e['hospital'],'entry_kind':e['entry_kind'],'pending_lists':len(lists),
                         'unfetched_candidates':len(remaining),'unfetched_digital_titles':len(digital),
                         'unfetched_non_digital_titles':len(remaining)-len(digital),'retry_limited_candidates':retry_limited,
                         'details_only':args.details_only,'digital_titles_only':args.digital_titles_only,
                         'targeted_pass_gaps':gaps,
                         'denied_or_challenged':denied,'selected':want})
    write_json(RUN/'continuation-manifest.json',manifest);write_json(RUN/'continuation-ids.json',selected)
    print(json.dumps({'selected':len(selected),'reparsed_date_updates':updates,'details_only':args.details_only,'digital_titles_only':args.digital_titles_only,
                     'pending_list_urls':sum(x['pending_lists'] for x in manifest if x['selected']),
                     'pending_lists_not_targeted':sum(x['pending_lists'] for x in manifest) if args.details_only else 0,
                     'non_digital_titles_not_targeted':sum(x['unfetched_non_digital_titles'] for x in manifest) if args.digital_titles_only else 0,
                     'retry_limited_candidates':sum(x['retry_limited_candidates'] for x in manifest),
                     'unfetched_candidates':sum(x['unfetched_candidates'] for x in manifest if x['selected']),
                     'unfetched_digital_titles':sum(x['unfetched_digital_titles'] for x in manifest if x['selected'])},ensure_ascii=False))
if __name__=='__main__':main()
