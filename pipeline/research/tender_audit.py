"""Offline replay of archived notices; preserve all original failures."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
from pathlib import Path
from .tenders import DEFAULT_RULES, load_rules, parse_html, read_json, write_json, now


def audit(rules_path, input_dir, output_dir, collections=()):
    rules = load_rules(rules_path)
    registry = {s['id']:s for s in rules['sources']}
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError('audit output must be empty')
    output_dir.mkdir(parents=True,exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    def relative(path):
        try:
            return Path(path).resolve().relative_to(repo).as_posix()
        except ValueError:
            return str(Path(path).resolve())
    page_files = sorted(input_dir.glob('*/pages.json'))
    page_files += [Path(c)/'pages.json' for c in collections]
    observations, failures, records, inputs = [], [], {}, []
    for page_file in page_files:
        folder = page_file.parent
        inputs.append({'path':relative(page_file),'sha256':hashlib.sha256(page_file.read_bytes()).hexdigest()})
        failure_file = folder/'failures.json'
        if failure_file.exists():
            failures.extend({**f,'ledger_file':relative(failure_file)} for f in read_json(failure_file))
        for page in read_json(page_file):
            sid = page['source_id']
            row = {'source_id':sid,'url':page.get('url'),'fetched_at':page.get('fetched_at'),
                   'original_status':page.get('status'),'original_rule_status':page.get('rule_status'),
                   'http_status':page.get('http_status'),'error':page.get('error',''),
                   'pages_file':relative(page_file),'replay_status':'not_available'}
            raw_name = page.get('raw_path') or page.get('raw_file')
            raw = folder/raw_name if raw_name else None
            if sid in registry and raw and raw.is_file() and page.get('status') in {'ok','empty'}:
                blob = raw.read_bytes()
                row['raw_path'] = relative(raw)
                row['sha256'] = hashlib.sha256(blob).hexdigest()
                if not blob.lstrip().startswith(b'%PDF'):
                    parsed = parse_html(blob,page['url'],registry[sid],rules)
                    row.update(replay_status=parsed['status'],title=parsed['title'],
                               discovered_links=len(parsed['links']))
                    if parsed['detail']:
                        rec = {**parsed['detail'],'raw_path':row['raw_path'],'sha256':row['sha256'],
                               'fetched_at':row['fetched_at'],'rules_version':rules['rules_version']}
                        records[rec['record_id']] = rec
            observations.append(row)
    source_rows = []
    for sid, source in registry.items():
        obs = [p for p in observations if p['source_id']==sid]
        recs = [r for r in records.values() if r['source_id']==sid]
        fails = [f for f in failures if f.get('source_id')==sid]
        state = ('detail_parsed' if recs else 'listing_discovered' if any(
                 p['replay_status']=='listing' for p in obs) else
                 'attempted_unresolved' if obs else 'not_attempted')
        source_rows.append({'source_id':sid,'name':source['name'],'matrix_group':source['matrix_group'],
                            'state':state,'attempted_pages':len(obs),'detail_records':len(recs),
                            'medical_digital_candidates':sum(r['medical_digital_candidate'] for r in recs),
                            'failure_codes':dict(Counter(f['code'] for f in fails)),
                            'latest_failure_reason':fails[-1].get('reason','') if fails else '',
                            'latest_replay_status':obs[-1]['replay_status'] if obs else '',
                            'next_action':source.get('next_action'),
                            'limitations':source['limitations']})
    summary = {'schema_version':1,'status':'partial','generated_at':now(),'rules_version':rules['rules_version'],
               'registered_sources':len(registry),'sources_with_attempts':sum(s['attempted_pages']>0 for s in source_rows),
               'page_attempts':len(observations),'unique_detail_records':len(records),
               'sources_with_details':sum(s['detail_records']>0 for s in source_rows),
               'medical_digital_candidates':sum(r['medical_digital_candidate'] for r in records.values()),
               'historical_failure_rows':len(failures),'historical_failure_codes':dict(Counter(f['code'] for f in failures)),
               'source_states':dict(Counter(s['state'] for s in source_rows)),
               'note':'离线解析改进不代表重新联网成功；保留原始失败。记录/候选均不等于已核验中标项目。'}
    for name, value in [('summary',summary),('sources',source_rows),('observations',observations),
                        ('records',list(records.values())),('historical_failures',failures),('inputs',inputs)]:
        write_json(output_dir/(name+'.json'),value)
    write_json(output_dir/'rules.snapshot.json',rules)
    lines = ['# 医疗数字化中标规则逐站验证','',f"规则版本：{rules['rules_version']}；生成：{summary['generated_at']}。",'',
             '本报告按实际请求和保存原文重放生成。原失败不覆盖；离线解析修复与联网成功分开。', '',
             f"登记 {len(registry)} 项；{summary['sources_with_attempts']} 项有网页尝试，累计 {len(observations)} 页次。",
             f"从原文解析 {len(records)} 条详情，涉及 {summary['sources_with_details']} 个来源；医疗数字化候选 {summary['medical_digital_candidates']} 条。均待事实核验。",'',
             f"保留历史失败/未执行记录 {len(failures)} 条；代码和原因见同目录 historical_failures.json。",'',
             '| 来源 | 当前最高验证阶段 | 页次/详情 | 历史失败代码 | 原因/待补条件 |','|---|---|---:|---|---|']
    def cell(value):
        return str(value or '').replace('|','/').replace('\n',' ')[:220]
    for s in source_rows:
        lines.append(f"| {cell(s['name'])} (`{s['source_id']}`) | {s['state']} | {s['attempted_pages']}/{s['detail_records']} | {cell(', '.join(s['failure_codes']))} | {cell(s['latest_failure_reason'] or s['limitations'])} |")
    lines += ['', '完整字段及原文定位见 observations.json、records.json、inputs.json。',
              '省级入口并不等于全部地市已完成适配；商业授权、JSON契约、附件全文/OCR和人工项目归并仍有缺口。','']
    (output_dir/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rules',type=Path,default=DEFAULT_RULES)
    p.add_argument('--input-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--collection',type=Path,action='append',default=[])
    a=p.parse_args()
    print(audit(a.rules,a.input_dir,a.output_dir,a.collection))


if __name__=='__main__':
    main()
