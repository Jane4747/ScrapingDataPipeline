"""Build a complete, offline hospital website channel register and query plan.

Manual verification is an input declaration, not established by this program.
Missing websites stay unknown; neither searches nor HTTP requests are executed.
Recommended site_relation values: hospital, parent_hospital, university, group,
government, unknown. Other labels are retained without being counted as hospital.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def as_list(value):
    if value in (None, ''):
        return []
    return value if isinstance(value, list) else [value]


def urls(value, field):
    result = []
    for url in as_list(value):
        if not isinstance(url, str) or urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
            raise ValueError(f'{field} must contain HTTP/HTTPS URLs')
        if url not in result:
            result.append(url)
    return result


def one_url(value, field):
    result = urls(value, field)
    if len(result) > 1:
        raise ValueError(f'{field} takes one URL; use multiple channel entries')
    return result[0] if result else None


def normalize_channel(raw):
    website = one_url(raw.get('website_url') or raw.get('official_homepage_url'), 'website_url')
    procurement = one_url(raw.get('procurement_channel_url') or raw.get('procurement_url'), 'procurement_channel_url')
    verification = urls(raw.get('verification_source_urls') or raw.get('verification_source_url'), 'verification_source_urls')
    identity = raw.get('official_identity_status') or 'not_checked'
    if identity == 'verified' and (not website or not verification):
        raise ValueError('Verified official identity requires website_url and verification_source_urls')
    channel_status = raw.get('channel_status') or ('located' if procurement else 'not_checked')
    if channel_status == 'located' and not procurement:
        raise ValueError('Located procurement channel requires procurement_channel_url')
    examples = raw.get('notice_examples') or []
    if not examples and raw.get('notice_example_url'):
        examples = [{'url': raw['notice_example_url'], 'title': raw.get('notice_example_title'),
                     'date': raw.get('notice_example_date'), 'applies_to_hospital': raw.get('applies_to_hospital')}]
    if not isinstance(examples, list):
        raise ValueError('notice_examples must be a list')
    normalized = []
    for example in examples:
        if not isinstance(example, dict):
            raise ValueError('Notice example must be an object')
        applies = example.get('applies_to_hospital')
        if applies is not None and not isinstance(applies, bool):
            raise ValueError('applies_to_hospital must be true, false or null')
        normalized.append({**example, 'url': one_url(example.get('url'), 'notice_example.url'),
                           'title': example.get('title'), 'date': example.get('date'),
                           'applies_to_hospital': applies})
    return {
        'website_url': website,
        'site_owner': raw.get('site_owner'),
        'site_relation': raw.get('site_relation') or raw.get('entity_level') or 'unknown',
        'official_identity_status': identity,
        'procurement_channel_url': procurement,
        'procurement_channel_name': raw.get('procurement_channel_name'),
        'other_column_urls': urls(raw.get('other_column_urls'), 'other_column_urls'),
        'other_column_name': raw.get('other_column_name'),
        'general_notice_url': one_url(raw.get('general_notice_url'), 'general_notice_url'),
        'channel_status': channel_status,
        'access_status': raw.get('access_status') or 'not_requested',
        'notice_examples': normalized,
        'verification_source_urls': verification,
        'evidence_files': as_list(raw.get('evidence_files')),
        'remaining_gap': raw.get('remaining_gap') or raw.get('gap'),
        'notes': raw.get('notes'),
        'observed_at': raw.get('observed_at'),
    }


def make_registry(roster, verified):
    if not isinstance(roster, list) or not isinstance(verified, list):
        raise ValueError('Roster and verified input must be JSON lists')
    hospitals = {}
    by_name = {}
    for row in roster:
        hid = row['id']
        if isinstance(hid, bool) or not isinstance(hid, int) or hid < 1:
            raise ValueError('Roster IDs must be positive integers')
        if hid in hospitals or not isinstance(row.get('name'), str) or not row['name'].strip():
            raise ValueError('Duplicate ID or missing hospital name')
        hospitals[hid] = row
        by_name.setdefault(row['name'], []).append(hid)
    grouped = {hid: [] for hid in hospitals}
    for raw in verified:
        if not isinstance(raw, dict):
            raise ValueError('Verified entries must be objects')
        hid = raw.get('hospital_id')
        name = raw.get('hospital_name') or raw.get('name')
        if hid is None:
            matches = by_name.get(name, [])
            if len(matches) != 1:
                raise ValueError(f'Hospital name must match exactly one roster row: {name}')
            hid = matches[0]
        if isinstance(hid, bool) or not isinstance(hid, int) or hid not in hospitals:
            raise ValueError(f'Hospital outside roster: {hid}')
        if name and name != hospitals[hid]['name']:
            raise ValueError(f'Hospital ID/name mismatch: {hid}')
        entries = raw.get('channels')
        if entries is None:
            entries = [raw]
        if not isinstance(entries, list):
            raise ValueError('channels must be a list')
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Channel must be an object')
            grouped[hid].append(normalize_channel(entry))
    rows = []
    for hid, hospital in hospitals.items():
        name, channels = hospital['name'], grouped[hid]
        queries = [f'"{name}" 官网', f'"{name}" (招标 OR 采购 OR 比选 OR 中标 OR 成交)',
                   f'"{name}" (通知公告 OR 院务公开 OR 招标采购)']
        for channel in channels:
            if channel['official_identity_status'] == 'verified':
                host = urlsplit(channel['website_url']).hostname
                query = f'site:{host} "{name}" (采购 OR 招标 OR 比选 OR 中标 OR 成交)'
                if query not in queries:
                    queries.append(query)
        rows.append({'hospital_id': hid, 'hospital_name': name,
                     'review_status': 'provided_entries' if channels else 'not_checked',
                     'channels': channels,
                     'remaining_gap': None if channels else '官网身份、采购栏目及公告尚未核验；不能据此判断没有官网或没有采购。',
                     'planned_queries': queries, 'execution_status': 'plan_only'})
    all_channels = [channel for row in rows for channel in row['channels']]
    scope = {'schema_version': 1, 'execution_status': 'plan_only',
             'hospital_count': len(rows), 'hospitals_with_provided_entries': sum(bool(row['channels']) for row in rows),
             'hospitals_not_checked': sum(not row['channels'] for row in rows),
             'channel_count': len(all_channels),
             'verified_identity_hospitals': sum(any(c['official_identity_status'] == 'verified' for c in row['channels']) for row in rows),
             'located_procurement_channel_hospitals': sum(any(c['channel_status'] == 'located' for c in row['channels']) for row in rows),
             'hospital_level_verified_identity_hospitals': sum(any(c['site_relation'] == 'hospital' and c['official_identity_status'] == 'verified' for c in row['channels']) for row in rows),
             'hospital_level_located_procurement_hospitals': sum(any(c['site_relation'] == 'hospital' and c['channel_status'] == 'located' for c in row['channels']) for row in rows),
             'upstream_located_procurement_hospitals': sum(any(c['site_relation'] in ('parent_hospital', 'parent_institute', 'university', 'group', 'government') and c['channel_status'] == 'located' for c in row['channels']) for row in rows),
             'site_relation_counts': dict(Counter(c['site_relation'] for c in all_channels)),
             'planned_query_count': sum(len(row['planned_queries']) for row in rows),
             'queries_executed_by_this_command': 0, 'network_requests': 0,
             'limitation': '这是人工核验输入的整理与待执行计划；官网确认不等于采购栏目已定位，上级单位公告不自动证明目标医院使用。'}
    return rows, scope


def build_registry(roster_path, verified_path, output_dir):
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError('Output directory must not already exist')
    rows, scope = make_registry(read_json(roster_path), read_json(verified_path))
    output.mkdir(parents=True, exist_ok=False)
    for name, value in [('hospital_official_channels.json', rows), ('scope.json', scope)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster', required=True)
    parser.add_argument('--verified', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        result = build_registry(args.roster, args.verified, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps({'status': 'completed', **result}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
