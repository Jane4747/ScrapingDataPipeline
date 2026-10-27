"""Offline audit of a reviewed tender delivery. Does not search or verify facts.

Usage: python -B scripts/tender_audit.py --input-dir outputs/BATCH --output audit.json
The bundle contains hospital_roster.json, hospital_search_log.json,
records.validated.json, candidate_notices.json, collection_scope.json and evidence.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from tender_tools import validate_record


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def all_strings(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,dict):
        for child in value.values():yield from all_strings(child)
    elif isinstance(value,list):
        for child in value:yield from all_strings(child)


def evidence_paths(row):
    value=row.get('evidence_files') or row.get('search_evidence') or row.get('evidence_path') or []
    return value if isinstance(value,list) else [x for x in re.split('[；\n]',value) if x]


def audit_bundle(folder,min_queries=6):
    folder=Path(folder).resolve()
    roster=read(folder/'hospital_roster.json')
    logs=read(folder/'hospital_search_log.json')
    records=read(folder/'records.validated.json')
    candidates=read(folder/'candidate_notices.json')
    scope=read(folder/'collection_scope.json')
    errors=[]
    def issue(kind,detail,hospital_id=None):
        errors.append({'kind':kind,'hospital_id':hospital_id,'detail':str(detail)})
    ids=[int(h['id']) for h in roster]
    hospitals={int(h['id']):h for h in roster}
    if len(ids)!=len(set(ids)):issue('duplicate_hospital_id','医院名单ID重复')
    log_ids=[int(r['hospital_id']) for r in logs]
    if len(log_ids)!=len(set(log_ids)):issue('duplicate_search_log','医院检索日志重复')
    if set(log_ids)!=set(ids):issue('roster_coverage',{'missing':sorted(set(ids)-set(log_ids)),'extra':sorted(set(log_ids)-set(ids))})
    cache={}
    def evidence(row):
        hid=row.get('hospital_id');paths=evidence_paths(row);values=set()
        if not paths:issue('missing_evidence','未记录证据文件',hid)
        for rel in paths:
            path=(folder/rel).resolve()
            if not path.is_relative_to(folder):
                issue('outside_bundle',rel,hid);continue
            if not path.is_file():
                issue('missing_evidence_file',rel,hid);continue
            if path.suffix.lower()=='.json':
                if path not in cache:
                    try:cache[path]=set(all_strings(read(path)))
                    except (ValueError,UnicodeError):
                        issue('invalid_evidence_json',rel,hid);cache[path]=set()
                values.update(cache[path])
        return values
    total=0;verified=0
    for log in logs:
        hid=log['hospital_id']
        queries=[q if isinstance(q,str) else q.get('q',q.get('query','')) for q in log.get('queries',[])]
        total+=len(queries)
        if len({q for q in queries if q})<min_queries:issue('query_shortfall',f'少于{min_queries}条不同的实际查询',hid)
        if log.get('query_count',len(queries))!=len(queries):issue('query_count_mismatch','查询计数不符',hid)
        observed=evidence(log)
        for query in queries:
            if query and query in observed:verified+=1
            else:issue('query_not_in_evidence',query,hid)
    for row in records:
        _,problems=validate_record(row,hospitals,scope['since'],scope['until'])
        for problem in problems:issue('invalid_accepted_record',problem,row.get('hospital_id'))
        evidence(row)
    for row in candidates:
        if int(row['hospital_id']) not in hospitals:issue('unknown_candidate_hospital','候选对象不在名单',row['hospital_id'])
        evidence(row)
    for key,actual in [('searched_hospitals',len(set(log_ids))),('query_count',total),('records',len(records)),('candidates',len(candidates))]:
        if key in scope and scope[key]!=actual:issue('summary_mismatch',{'field':key,'reported':scope[key],'actual':actual})
    retained={int(r['hospital_id']) for r in records+candidates}
    return {'status':'passed' if not errors else 'failed','hospital_count':len(ids),
            'searched_hospitals':len(set(log_ids)),'query_count':total,'queries_verified_in_evidence':verified,
            'accepted_records':len(records),'candidate_or_excluded':len(candidates),
            'hospitals_with_retained_notices':len(retained),'hospitals_without_retained_notices':len(set(ids)-retained),
            'error_count':len(errors),'errors':errors,
            'limitation':'只核对文件、字段、日期口径及查询留痕；不证明公告事实正确或渠道已经穷尽。无保留公告不等于爬取失败。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--min-queries',type=int,default=6)
    args=parser.parse_args()
    if args.min_queries<1:parser.error('--min-queries must be at least 1')
    result=audit_bundle(args.input_dir,args.min_queries)
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    return 0 if result['status']=='passed' else 2


if __name__=='__main__':raise SystemExit(main())
