"""Plan and run per-hospital official website probes for procurement columns.

This is the reusable form of the manual rounds done in the 2026-10-27 session:
per hospital, locate the hospital-level homepage, then look for a tendering /
procurement column on that site. Two explicit modes keep planning and network
use separate:

    python scripts/hospital_site_probe.py --roster roster.json --plan --output-dir ...
    python scripts/hospital_site_probe.py --roster roster.json --probe --allow-network --output-dir ...

`--plan` never touches the network and only emits probe targets plus review
queries. `--probe` requires `--allow-network` and bounds every request by
timeout, response size, link count and robots policy.

A located column is evidence that the page exists. It is not proof that the
hospital published tenders there, and a platform host is never accepted as a
hospital-level homepage.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / 'configs' / 'hospital_site_probe.json'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def host_of(url):
    host = urllib.parse.urlsplit(url).hostname or ''
    return host.lower().lstrip('www.')


def is_platform_host(host, config):
    host = host.lower()
    return any(host == domain or host.endswith('.' + domain) for domain in config['platform_domains'])


def is_group_host(host, config):
    host = host.lower()
    return any(host == domain or host.endswith('.' + domain) for domain in config.get('group_domains', []))


def normalize_roster(roster):
    if not isinstance(roster, list):
        raise ValueError('Roster must be a JSON list')
    rows = []
    seen = set()
    for raw in roster:
        if not isinstance(raw, dict):
            raise ValueError('Roster rows must be objects')
        hid = raw.get('hospital_id')
        name = (raw.get('hospital_name') or '').strip()
        if isinstance(hid, bool) or not isinstance(hid, int) or hid < 1:
            raise ValueError('hospital_id must be a positive integer')
        if hid in seen:
            raise ValueError(f'Duplicate hospital_id: {hid}')
        if not name:
            raise ValueError(f'Missing hospital_name for id {hid}')
        seen.add(hid)
        hosts = []
        for value in raw.get('candidate_hosts') or []:
            host = value.strip().lower() if isinstance(value, str) else None
            if not host:
                continue
            if host.startswith(('http://', 'https://')):
                host = host_of(host)
            if host and host not in hosts:
                hosts.append(host)
        if raw.get('candidate_homepage'):
            home = raw['candidate_homepage'].strip()
            host = host_of(home) if home.startswith(('http://', 'https://')) else home
            if host and host not in hosts:
                hosts.append(host)
        rows.append({'hospital_id': hid, 'hospital_name': name,
                     'hosts': hosts, 'level': raw.get('level'),
                     'owner': raw.get('owner'), 'notes': raw.get('notes')})
    return rows


def build_plan(rows, config):
    plan = []
    query_total = 0
    for row in rows:
        queries = [pattern.format(name=row['hospital_name']) for pattern in config['search_queries']]
        targets = []
        for host in row['hosts']:
            if is_platform_host(host, config):
                targets.append({'host': host, 'kind': 'platform_host', 'probe': False,
                                'reason': 'Platform host; cannot be a hospital-level homepage.'})
            elif is_group_host(host, config):
                targets.append({'host': host, 'kind': 'group_host', 'probe': True,
                                'reason': 'Group site; needs explicit judgement whether it carries this hospital.'})
            else:
                targets.append({'host': host, 'kind': 'candidate_homepage', 'probe': True, 'reason': None})
        query_total += len(queries)
        plan.append({'hospital_id': row['hospital_id'], 'hospital_name': row['hospital_name'],
                     'level': row['level'], 'owner': row['owner'], 'hosts': row['hosts'],
                     'roster_hosts': len(row['hosts']), 'planned_queries': queries, 'targets': targets,
                     'status': 'no_host' if not row['hosts'] else 'planned', 'execution_status': 'plan_only'})
    scope = {'schema_version': 1, 'execution_status': 'plan_only', 'hospital_count': len(rows),
             'hospitals_with_hosts': sum(1 for row in plan if row['hosts']),
             'hospitals_without_hosts': sum(1 for row in plan if not row['hosts']),
             'planned_query_count': query_total, 'network_requests': 0,
             'limitation': config['limitation']}
    return plan, scope


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            attrs = dict(attrs)
            self._href = attrs.get('href')
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'a' and self._href is not None:
            self.links.append((self._href, ''.join(self._text).strip()))
            self._href = None


def extract_columns(html, base_url, config, max_links):
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    keywords = config['column_keywords']
    candidates = []
    for href, anchor in parser.links[:max_links]:
        if not href:
            continue
        absolute = urllib.parse.urljoin(base_url, href)
        if urllib.parse.urlsplit(absolute).scheme not in ('http', 'https'):
            continue
        text = anchor or href
        haystack = (text + ' ' + urllib.parse.unquote(href)).lower()
        if any(word in haystack for word in keywords['exclude']):
            continue
        score = 0
        matched = []
        for group, weight in (('strong', 3), ('medium', 1)):
            for word in keywords[group]:
                if word in haystack:
                    score += weight
                    matched.append(word)
        if not matched:
            continue
        path = urllib.parse.urlsplit(absolute).path.lower()
        if any(hint in path for hint in config['column_path_hints']):
            score += 2
        candidates.append({'url': absolute, 'anchor': anchor, 'matched': matched, 'score': score})
    candidates.sort(key=lambda item: (-item['score'], item['url']))
    deduped = []
    seen = set()
    for item in candidates:
        key = item['url']
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _robots_allows(url, config):
    parts = urllib.parse.urlsplit(url)
    robots_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, '/robots.txt', '', ''))
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        with urllib.request.urlopen(robots_url, timeout=config['request']['timeout_seconds']) as response:
            body = response.read(min(config['request']['max_bytes'], 200000)).decode('utf-8', 'replace')
        parser.parse(body.splitlines())
    except (urllib.error.URLError, OSError, ValueError):
        return True, 'robots_unreachable'
    return parser.can_fetch(config['request']['user_agent'], url), 'robots_read'


def _fetch(url, config):
    request = urllib.request.Request(url, headers={'User-Agent': config['request']['user_agent']})
    with urllib.request.urlopen(request, timeout=config['request']['timeout_seconds']) as response:
        raw = response.read(config['request']['max_bytes'])
        final_url = response.geturl()
        status = response.getcode()
        encoding = response.headers.get_content_charset() or 'utf-8'
    return {'status': status, 'final_url': final_url, 'html': raw.decode(encoding, 'replace')}


def probe_target(target, config):
    started = time.time()
    record = {'host': target['host'], 'kind': target['kind'], 'target_url': 'https://' + target['host'] + '/',
              'status': 'unknown', 'detail': None, 'http_status': None, 'final_url': None,
              'elapsed_seconds': None, 'candidates': []}
    if not target['probe']:
        record['status'] = 'skipped'
        record['detail'] = target.get('reason') or 'Not probed by policy.'
        return record, 0
    request_count = 0
    url = record['target_url']
    if config['request'].get('respect_robots', True):
        allowed, detail = _robots_allows(url, config)
        request_count += 1
        record['robots'] = detail
        if not allowed:
            record['status'] = 'robots_denied'
            record['detail'] = 'robots.txt disallows the homepage for this agent.'
            record['elapsed_seconds'] = round(time.time() - started, 2)
            return record, request_count
    try:
        fetched = _fetch(url, config)
        request_count += 1
    except urllib.error.HTTPError as exc:
        record.update({'status': 'http_error', 'http_status': exc.code, 'detail': f'HTTP {exc.code}'})
        record['elapsed_seconds'] = round(time.time() - started, 2)
        return record, request_count
    except (urllib.error.URLError, OSError) as exc:
        record.update({'status': 'access_failed', 'detail': f'{type(exc).__name__}: {exc}'})
        record['elapsed_seconds'] = round(time.time() - started, 2)
        return record, request_count
    record['http_status'] = fetched['status']
    record['final_url'] = fetched['final_url']
    final_host = host_of(fetched['final_url'])
    if final_host and final_host != record['host']:
        record['detail'] = f'Redirected to {final_host}.'
        if is_platform_host(final_host, config) or is_group_host(final_host, config):
            record['status'] = 'not_hospital_homepage'
            record['detail'] = f'Homepage redirects to platform or group host {final_host}.'
            record['elapsed_seconds'] = round(time.time() - started, 2)
            return record, request_count
    try:
        record['candidates'] = extract_columns(fetched['html'], fetched['final_url'], config,
                                               config['request']['max_links_per_page'])
    except (ValueError, TypeError, RuntimeError) as exc:
        record.update({'status': 'parse_failed', 'detail': f'HTML parse failed: {exc}'})
        record['elapsed_seconds'] = round(time.time() - started, 2)
        return record, request_count
    record['status'] = 'ok' if record['candidates'] else 'no_column_candidate'
    record['elapsed_seconds'] = round(time.time() - started, 2)
    return record, request_count


def run_probe(plan, config):
    records = []
    requests = 0
    for row in plan:
        row_record = {'hospital_id': row['hospital_id'], 'hospital_name': row['hospital_name'],
                      'level': row['level'], 'owner': row['owner'], 'targets': []}
        for target in row['targets']:
            record, count = probe_target(target, config)
            requests += count
            row_record['targets'].append(record)
        best = None
        for record in row_record['targets']:
            for candidate in record.get('candidates', []):
                if best is None or candidate['score'] > best['score']:
                    best = {**candidate, 'via_host': record['host']}
        reachable = [r for r in row_record['targets'] if r['status'] in ('ok', 'no_column_candidate')]
        homepage = reachable[0]['final_url'] or reachable[0]['target_url'] if reachable else None
        row_record['homepage_url'] = homepage
        row_record['top_candidate'] = best
        row_record['channel_status'] = 'found' if best else ('not_found' if reachable else 'unknown')
        row_record['evidence'] = [{'target_url': r['target_url'], 'http_status': r['http_status'],
                                   'status': r['status'], 'detail': r['detail']} for r in row_record['targets']]
        records.append(row_record)
    scope = {'schema_version': 1, 'execution_status': 'executed', 'hospital_count': len(records),
             'network_requests': requests,
             'located_columns': sum(1 for r in records if r['channel_status'] == 'found'),
             'reachable_without_column': sum(1 for r in records if r['channel_status'] == 'not_found'),
             'unresolved': sum(1 for r in records if r['channel_status'] == 'unknown'),
             'limitation': config['limitation']}
    return records, scope


def write_bundle(output_dir, name_payload_pairs, scope):
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError('Output directory must not already exist')
    output.mkdir(parents=True)
    written = {}
    for name, payload in name_payload_pairs:
        (output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        written[name] = str(output / name)
    (output / 'scope.json').write_text(json.dumps(scope, ensure_ascii=False, indent=2), encoding='utf-8')
    written['scope.json'] = str(output / 'scope.json')
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--roster', required=True, help='JSON list of hospitals, optional candidate_hosts per row')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--output-dir', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true', help='Offline plan only; no network access')
    mode.add_argument('--probe', action='store_true', help='Run HTTP probes; requires --allow-network')
    parser.add_argument('--allow-network', action='store_true')
    args = parser.parse_args(argv)
    try:
        config = read_json(args.config)
        rows = normalize_roster(read_json(args.roster))
        plan, plan_scope = build_plan(rows, config)
        if args.plan:
            written = write_bundle(args.output_dir, [('probe_plan.json', plan)], plan_scope)
            print(json.dumps({'status': 'completed', 'mode': 'plan', 'scope': plan_scope,
                              'outputs': written}, ensure_ascii=False))
            return 0
        if not args.allow_network:
            print(json.dumps({'status': 'failed', 'error': '--probe requires --allow-network'}, ensure_ascii=False))
            return 2
        records, scope = run_probe(plan, config)
        written = write_bundle(args.output_dir, [('probe_plan.json', plan), ('probe_records.json', records)], scope)
        print(json.dumps({'status': 'completed', 'mode': 'probe', 'scope': scope,
                          'outputs': written}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
