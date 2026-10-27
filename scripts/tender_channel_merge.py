"""Merge reviewed channel supplements offline; no search, HTTP or Excel rendering.

Required base files: hospital_roster.json, hospital_search_log.json,
records.validated.json, candidate_notices.json and collection_scope.json.
Supplement groups use records_GROUP.json, candidates_GROUP.json, search_GROUP.json
and relative evidence paths; optional review_decisions.json records resolutions.
The output must not exist and must be separate from both input directories.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path, PureWindowsPath
import shutil

from tender_tools import HEADERS, validate_record


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def unique(values):
    return list(dict.fromkeys(values))


def checked_path(root, relative):
    """Reject absolute paths, traversal and symlink escapes on all platforms."""
    if not isinstance(relative, str) or not relative:
        raise ValueError('Evidence path must be a nonempty relative string')
    windows = PureWindowsPath(relative)
    if windows.is_absolute() or windows.drive or Path(relative).is_absolute():
        raise ValueError(f'Absolute evidence path: {relative}')
    relative = relative.replace('\\', '/')
    if '..' in Path(relative).parts:
        raise ValueError(f'Parent traversal in evidence path: {relative}')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f'Evidence outside input directory: {relative}')
    return path


def paths(row):
    value = row.get('evidence_files') or row.get('evidence_path') or []
    value = value.split('；') if isinstance(value, str) else value
    if not isinstance(value, list) or not value:
        raise ValueError(f'Missing evidence files: {row.get("url", row.get("hospital_id"))}')
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError('Invalid evidence file list')
    return unique(value)


def hospital_ids(row, hospitals, allow_empty=False):
    values = row.get('hospital_ids') or ([row['hospital_id']] if row.get('hospital_id') is not None else [])
    if not isinstance(values, list) or (not values and not allow_empty):
        raise ValueError('Missing or invalid hospital_ids')
    if any(isinstance(value, bool) for value in values):
        raise ValueError('Boolean hospital ID')
    try:
        ids = sorted(set(int(value) for value in values))
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid hospital ID') from exc
    if not set(ids) <= set(hospitals):
        raise ValueError(f'Unknown hospital IDs: {ids}')
    if row.get('hospital_id') is not None and int(row['hospital_id']) not in ids:
        raise ValueError('Primary hospital_id is missing from hospital_ids')
    return ids


def identity(row):
    # One notice/package is one row even when it serves multiple hospitals.
    return (row.get('url', '').split('#')[0], str(row.get('package') or row.get('package_no') or ''))


def normalize(row, hospitals):
    result = dict(row)
    result['hospital_ids'] = hospital_ids(result, hospitals)
    result['hospital_id'] = int(result.get('hospital_id', result['hospital_ids'][0]))
    result['project_number'] = result.get('project_number') or result.get('project_no') or ''
    result['package'] = identity(result)[1]
    result['additional_urls'] = unique(result.get('additional_urls', []) + result.get('related_urls', []))
    result['evidence_files'] = paths(result)
    result['evidence_path'] = '；'.join(result['evidence_files'])
    result['reason'] = result.get('reason') or result.get('candidate_reason') or result.get('source_note', '')
    return result


def join_evidence(keep, other):
    keep['evidence_files'] = unique(keep['evidence_files'] + other['evidence_files'])
    keep['evidence_path'] = '；'.join(keep['evidence_files'])
    keep['additional_urls'] = unique(keep.get('additional_urls', []) + other.get('additional_urls', []))


def merge_row(table, row):
    key = identity(row)
    prior = table.get(key)
    if prior:
        for field in ('winner', 'amount_wan'):
            if row.get(field) not in (None, '') and prior.get(field) not in (None, '') and row[field] != prior[field]:
                raise ValueError(f'Conflicting {field} for {key}')
            if row.get(field) in (None, ''):
                row[field] = prior.get(field)
        join_evidence(row, prior)
        row['hospital_ids'] = sorted(set(row['hospital_ids'] + prior['hospital_ids']))
        row['hospital_id'] = prior['hospital_id']
    table[key] = row


def by_url(table, url):
    matches = [row for row in table.values() if row['url'] == url]
    if len(matches) != 1:
        raise ValueError(f'Review URL must identify exactly one row: {url}')
    return matches[0]


def copied_base_files(base):
    for path in base.rglob('*'):
        relative = path.relative_to(base)
        if 'code' in relative.parts or path.suffix.lower() in ('.xlsx', '.zip') or path.name.endswith('.inspect.ndjson'):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(base):
            raise ValueError(f'Input tree contains a symlink or escaping path: {relative}')
        if path.is_file():
            yield relative, path


def merge_bundle(base_dir, supplement_dir, output_dir, since, until):
    base, supplement, output = (Path(value).resolve() for value in (base_dir, supplement_dir, output_dir))
    date.fromisoformat(since)
    date.fromisoformat(until)
    if since > until:
        raise ValueError('since must not be later than until')
    if not base.is_dir() or not supplement.is_dir():
        raise ValueError('Input directories must exist')
    if output.exists():
        raise ValueError('Output directory must not already exist')
    for source in (base, supplement):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('Output directory must be separate from both input directories')
    roster = read(base / 'hospital_roster.json')
    hospitals = {int(row['id']): row for row in roster}
    if len(hospitals) != len(roster):
        raise ValueError('Duplicate roster IDs')
    prior_scope = read(base / 'collection_scope.json')
    if (prior_scope['since'], prior_scope['until']) != (since, until):
        raise ValueError('Base scope differs from requested period; create a reviewed base for that period')
    historical_logs = read(base / 'hospital_search_log.json')
    if {int(row['hospital_id']) for row in historical_logs} != set(hospitals) or len(historical_logs) != len(roster):
        raise ValueError('Historical search log does not cover the roster exactly once')
    historical_queries = sum(len(row.get('queries', [])) for row in historical_logs)
    if prior_scope.get('query_count') != historical_queries:
        raise ValueError('Historical query count does not match saved logs')
    records, candidates = {}, {}
    for name, table in [('records.validated.json', records), ('candidate_notices.json', candidates)]:
        for row in read(base / name):
            merge_row(table, normalize(row, hospitals))
    old_records, old_candidates = set(records), set(candidates)
    group_files = sorted(supplement.glob('search_*.json'))
    if not group_files:
        raise ValueError('No supplement search_GROUP.json files found')
    logs = []
    for search_file in group_files:
        group = search_file.stem[len('search_'):]
        for stem, table in [('records', records), ('candidates', candidates)]:
            for row in read(supplement / f'{stem}_{group}.json'):
                merge_row(table, normalize(row, hospitals))
        for raw in read(search_file):
            row = dict(raw)
            row['group'] = group
            row['hospital_ids'] = hospital_ids(row, hospitals, allow_empty=True)
            row['queries'] = [item if isinstance(item, str) else item.get('q', item.get('query', '')) for item in row.get('queries', [])]
            if any(not isinstance(query, str) or not query for query in row['queries']):
                raise ValueError('Empty or invalid query')
            if 'query_count' in row and row['query_count'] != len(row['queries']):
                raise ValueError('Supplement query_count does not match queries')
            row['evidence_files'] = paths(row)
            logs.append(row)
    review_file = supplement / 'review_decisions.json'
    review = read(review_file) if review_file.exists() else {}
    for decision in review.get('record_overrides', []):
        row = by_url(records, decision['url'])
        forbidden = {'url', 'hospital_id', 'hospital_ids', 'package', 'package_no', 'evidence_files', 'evidence_path'} & set(decision['fields'])
        if forbidden:
            raise ValueError(f'Review overrides cannot change row identity or evidence: {forbidden}')
        row.update(decision['fields'])
    for decision in review.get('candidate_resolutions', []):
        keep = by_url(records, decision['record_url'])
        for url in decision['candidate_urls']:
            row = by_url(candidates, url)
            join_evidence(keep, row)
            keep['additional_urls'] = unique(keep.get('additional_urls', []) + [url])
            del candidates[identity(row)]
    for decision in review.get('candidate_merges', []):
        keep = by_url(candidates, decision['keep_url'])
        for url in decision['merge_urls']:
            if url == decision['keep_url']:
                raise ValueError('Candidate cannot merge into itself')
            row = by_url(candidates, url)
            join_evidence(keep, row)
            keep['additional_urls'] = unique(keep.get('additional_urls', []) + [url])
            keep['hospital_ids'] = sorted(set(keep['hospital_ids'] + row['hospital_ids']))
            del candidates[identity(row)]
    files = dict(copied_base_files(base))
    cache = {}
    def resolve_evidence(relative):
        possible = [checked_path(source, relative) for source in (base, supplement)]
        matches = [path for path in possible if path.is_file()]
        if not matches:
            raise ValueError(f'Missing evidence file: {relative}')
        if len(matches) == 2 and matches[0].read_bytes() != matches[1].read_bytes():
            raise ValueError(f'Evidence filename collision with different content: {relative}')
        files[Path(relative.replace('\\', '/'))] = matches[-1]
        return matches[-1]
    queries, covered = set(), set()
    for row in logs:
        observed = set()
        for relative in row['evidence_files']:
            path = resolve_evidence(relative)
            if path not in cache:
                cache[path] = set(strings(read(path)))
            observed.update(cache[path])
        for query in row['queries']:
            if query not in observed:
                raise ValueError(f'Query not present in saved evidence: {query}')
            queries.add(query)
        covered.update(row['hospital_ids'])
    for row in list(records.values()) + list(candidates.values()):
        for relative in row['evidence_files']:
            resolve_evidence(relative)
        ids = row['hospital_ids']
        row['hospital_name'] = '、'.join(hospitals[hid]['name'] for hid in ids)
        row['customer_label'] = '；'.join('、'.join(unique(hospitals[hid].get(field, '') for hid in ids)) for field in ('level', 'category', 'district'))
        row['customer_label'] += '（按提供名单；同一公告涉及多院）' if len(ids) > 1 else '（按提供名单）'
    accepted = []
    for row in records.values():
        normalized, errors = validate_record(row, hospitals, since, until)
        if errors:
            raise ValueError(f'Invalid accepted record {row["url"]}: {errors}')
        accepted.append(normalized)
    accepted.sort(key=lambda row: (row['hospital_id'], row['date'], row['project_name']))
    scope = {
        'round_type': 'channel_supplement', 'since': since, 'until': until,
        'roster_rows': len(roster), 'records': len(accepted), 'candidates': len(candidates),
        'new_records': len(set(records) - old_records),
        'new_candidate_rows_by_url': len(set(candidates) - old_candidates),
        'channel_query_count': len(queries), 'channel_searched_hospitals': len(covered),
        'channel_hospital_ids': sorted(covered), 'query_count': historical_queries,
        'searched_hospitals': len(historical_logs),
        'minimum_queries_per_hospital': prior_scope.get('minimum_queries_per_hospital'),
        'accepted': len(accepted), 'needs_review': 0,
        'workbook_filename': '北京一级医院数智化招采_渠道补查版.xlsx',
        'scope_note': '渠道定向补查；原名单逐院查询另存，未声称本轮重新搜索全部医院或穷尽网站。',
        'generation_note': '离线合并已保存的证据与核验决定；没有执行网络检索或Excel渲染。',
    }
    # All content validation above precedes output creation. No existing output is overwritten.
    output.mkdir(parents=True, exist_ok=False)
    for relative, source in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for pattern in ('summary_*.json', 'channels_*.json', 'exclusions_*.json'):
        for path in supplement.glob(pattern):
            shutil.copy2(path, output / path.name)
    for name in ('platform_channels.json', 'hospital_channel_roster.json'):
        path = supplement / name
        if path.exists():
            shutil.copy2(path, output / name)
    save(output / 'records.validated.json', accepted)
    save(output / 'records.needs_review.json', [])
    save(output / 'candidate_notices.json', list(candidates.values()))
    save(output / 'channel_search_log.json', logs)
    save(output / 'collection_scope.json', scope)
    save(output / 'merge_review.json', review)
    note = (
        '北京一级医院数智化招采：渠道补查离线合并结果\n\n'
        f'原名单{len(roster)}家医院；公告日期{since}至{until}。\n'
        f'本轮已保存并核对查询留痕{len(queries)}条，关联{len(covered)}家医院；'
        f'历史逐院日志保留{len(historical_logs)}家、{historical_queries}条查询。\n'
        f'合并后主表{len(accepted)}条，较基准新增{scope["new_records"]}条；'
        f'待核、排除或应用消息共{len(candidates)}条。\n\n'
        '主表为七列CSV和JSON；一份公告的同一采购包涉及多家医院时保留一行，并记录hospital_ids。'
        '候选解决和合并决定保存在merge_review.json，原始证据继续保留。\n'
        '本命令只重放已保存的证据和核验决定，没有执行网络检索或生成Excel。'
        f'如另行运行可选Excel生成器，目标文件名为{scope["workbook_filename"]}。\n'
        '公告金额和来源性质以每条记录的amount_quote、source_note及原文为准；'
        '工程总价不能视为其中数智化部分金额，未知字段保持空白。\n'
        '未检索到或未保留公告不代表医院没有采购；本结果不表示渠道历史公告已穷尽。\n'
    )
    (output / '交付说明.txt').write_text(note, encoding='utf-8')
    with (output / '北京一级医院数智化招采信息.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        for row in accepted:
            trace = '；'.join(filter(None, [row['announcement_type'], row['date'], row['url'], row.get('project_number'), row.get('source_note')]))
            cells = [row['project_name'], row.get('product', ''), row.get('purchaser', ''), row['customer_label'], row.get('winner') or '', row.get('amount_wan'), trace]
            writer.writerow(["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value for value in cells])
    return scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base-dir', 'supplement-dir', 'output-dir', 'since', 'until'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = merge_bundle(args.base_dir, args.supplement_dir, args.output_dir, args.since, args.until)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps({'status': 'completed', **result}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
