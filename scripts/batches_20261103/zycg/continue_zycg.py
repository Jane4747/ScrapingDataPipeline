"""Checkpointed orchestration of the repository's existing ZYCG collector.

The repository module owns HTTP access checks, list parsing, medical scope,
notice parsing and the eight output fields. This module adds task isolation,
request-typed cache folders, evidence, conservative pacing and coverage checks.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from bs4 import BeautifulSoup
from pipeline.research import zycg
from pipeline.research.fetch import Fetcher
from pipeline.research.tenders import decode_html

WORK = Path(__file__).resolve().parent
ROOT = REPO / 'outputs/zycg-continuation-20261103'
START, END = '2024-01-01', '2026-11-03'
ORIGINAL_SEARCH_URL = zycg.search_url


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def record_key(record):
    url = record.get('detail', {}).get('公告链接') or record.get('notice', {}).get('url', '')
    p = urlsplit(url)
    return (p.hostname or '').lower().removeprefix('www.') + p.path + ('?' + p.query if p.query else '')


def typed_url(page, start, end, kind):
    p = urlsplit(ORIGINAL_SEARCH_URL(page, start, end))
    params = dict(parse_qsl(p.query, keep_blank_values=True))
    params['bidType'] = str(kind)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(params), ''))


def bisect_dates(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a == b:
        return []
    middle = a + (b - a) // 2
    return [(a.isoformat(), middle.isoformat()), ((middle + timedelta(days=1)).isoformat(), b.isoformat())]


def page_info(raw):
    html = decode_html(raw)
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    total = re.search(r'共找到\s*([\d,]+)\s*条', text)
    pager = re.search(r'Pager\s*\(\s*\{\s*size\s*:\s*(\d+)', html, re.S)
    variables = dict(re.findall(r"var\s+(bidType|agentName|start_time|end_time)\s*=\s*'([^']*)'", html))
    return {'total': int(total[1].replace(',', '')) if total else None,
            'pages': int(pager[1]) if pager else (0 if total and int(total[1].replace(',', '')) == 0 else None),
            'variables': variables, 'items': zycg.parse_search_page(html)}


def audit_pages(paths, start, end, kind):
    parsed = []
    for p in sorted(paths):
        page = int(p.stem.rsplit('-', 1)[-1])
        parsed.append((page, page_info(p.read_bytes())))
    if not parsed:
        return {'verified': False, 'total': None, 'unique': 0, 'saved_pages': 0, 'reason': 'no_list_pages'}
    last = parsed[0][1]['pages']
    used = [(n, x) for n, x in parsed if last is None or n <= max(last, 1)]
    totals = {x['total'] for _, x in used}
    urls = {item['url'] for _, x in used for item in x['items']}
    expected = next(iter(totals)) if len(totals) == 1 else None
    contract = all(x['variables'].get('bidType') == str(kind)
                   and x['variables'].get('agentName') == zycg.AGENT
                   and x['variables'].get('start_time', '').replace(':', '-') == start
                   and x['variables'].get('end_time', '').replace(':', '-') == end for _, x in used)
    contiguous = last is not None and set(range(1, max(last, 1) + 1)).issubset({n for n, _ in used})
    wrong_type = sum(not ('/zbgg/' in u if kind == 7 else '/cjgg/' in u) for u in urls) if kind in (7, 11) else 0
    verified = contract and contiguous and expected is not None and len(urls) == expected and wrong_type == 0
    return {'verified': verified, 'total': expected, 'unique': len(urls), 'declared_pages': last,
            'saved_pages': len(used), 'contract_matches': contract, 'wrong_notice_type_urls': wrong_type,
            'reason': 'counts_and_contract_match' if verified else 'counts_or_contract_unverified'}


class ManagedFetcher(Fetcher):
    def __init__(self, owner, delay):
        super().__init__(timeout=30, retries=1, delay=delay)
        self.owner, self.interval = owner, delay
        self.next_request_at = 0.0
        self.last_response = None

    def close(self):
        # zycg.collect closes a query view; keep the ordinary session stable
        # throughout this source task, and close it once at the outer boundary.
        pass

    def finish(self):
        super().close()

    def _request(self, url):
        wait = self.next_request_at - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        result = super()._request(url)
        self.next_request_at = time.monotonic() + self.interval
        return result

    def _download(self, url, allowed_domains, check_robots=True, limit=None):
        result = super()._download(url, allowed_domains, check_robots, limit)
        self.last_response = result
        return result

    def fetch(self, url, allowed_domains):
        if self.owner.paused:
            return {'status': 'deferred', 'error': 'Source paused; pending detail retained', 'url': url}
        name = 'detail-' + hashlib.md5(url.encode()).hexdigest()[:12] + '.html'
        if name in self.owner.body_pool and 'search.ccgp.gov.cn' not in url:
            p = Path(self.owner.body_pool[name])
            result = self.extract_cached(p.read_bytes(), {'url': url, 'http_status': 200, 'method': 'historical_cache'}, allowed_domains)
            self.owner.cache_body_hits += 1
            return result
        self.last_response = None
        started = now()
        result = super().fetch(url, allowed_domains)
        self.owner.network_fetch_calls += 1
        metadata = {'at': started, 'url': url, 'status': result.get('status'),
                    'http_status': result.get('http_status'), 'title': result.get('title'),
                    'content_type': result.get('content_type'), 'error': result.get('error'),
                    'query_id': self.owner.active_query, 'cached': False}
        if self.last_response:
            final_url, status, headers, body = self.last_response
            metadata['http_status'] = status
            metadata['response_headers'] = {k: v for k, v in headers.items()
                                            if k.lower() in {'retry-after', 'date', 'content-type', 'server'}}
            if result.get('status') != 'ok' and body:
                filename = f"failure-{self.owner.network_fetch_calls:05d}-{sha(url.encode())[:12]}.html"
                failure_file = ROOT / 'failure_evidence' / filename
                failure_file.parent.mkdir(parents=True, exist_ok=True)
                failure_file.write_bytes(body)
                metadata.update(body_file=str(failure_file), body_sha256=sha(body), body_bytes=len(body))
        with (ROOT / 'http_events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(metadata, ensure_ascii=False) + '\n')
        if result.get('status') != 'ok':
            self.owner.failures.append(metadata)
            self.owner.paused = True
            self.owner.pause_reason = metadata
            self.owner.checkpoint()
        return result


class Runner:
    def __init__(self, delay=8.0):
        ROOT.mkdir(parents=True, exist_ok=True)
        self.paused = False
        self.pause_reason = None
        self.active_query = None
        self.active_type = 0
        self.network_fetch_calls = 0
        self.cache_body_hits = 0
        self.failures = []
        self.records = {}
        self.body_pool = {}
        self.cache_sources = []
        self.queries = []
        self.started_at = now()
        self.delay = delay
        self.fetcher = ManagedFetcher(self, delay)

    def checkpoint(self):
        write(ROOT / 'records.json', list(self.records.values()))
        value = {'schema_version': 1, 'task_id': f'zycg-results-{START}-{END}', 'start': START, 'end': END,
                 'started_at': self.started_at, 'updated_at': now(), 'status': 'partial' if self.paused else 'running',
                 'active_query': self.active_query, 'records': len(self.records),
                 'network_fetch_calls': self.network_fetch_calls, 'cache_body_hits': self.cache_body_hits,
                 'pause_reason': self.pause_reason, 'failures': self.failures, 'queries': self.queries}
        write(ROOT / 'state.json', value)

    def merge(self, records):
        for record in records:
            d = record.get('detail', {})
            if START <= d.get('公告日期', '') <= END and zycg.is_result_notice(d.get('公告链接', '')):
                self.records[record_key(record)] = record

    def query(self, start, end, kind, cache_proof=None, from_cache=None):
        key = sha(json.dumps({'start': start, 'end': end, 'bidType': kind, 'agentName': zycg.AGENT}, sort_keys=True).encode())[:16]
        q = {'id': key, 'start': start, 'end': end, 'bid_type': kind, 'status': 'pending',
             'directory': str(ROOT / 'q' / f'type-{kind}-{key}'),
             'cache_proof': cache_proof, 'from_cache': from_cache or []}
        self.queries.append(q)
        return q

    def prepare(self, baseline_files=(), cache_roots=()):
        # Only caller-selected baselines/caches are considered. Historical cache
        # completion requires exact window, notice type and page-count evidence.
        for source in baseline_files:
            payload = read(source)
            records = payload.get('records', []) if isinstance(payload, dict) else payload
            for item in records:
                if 'detail' in item:
                    self.merge([item])
                else:
                    notice = {'url': item.get('公告链接', ''), 'title': item.get('公告标题', item.get('项目名称', '')),
                              'published_at': item.get('公告日期', ''), 'buyer': item.get('招标单位', ''),
                              'agent': item.get('采购执行机构', ''), 'notice_type': item.get('公告类型', '')}
                    self.merge([{'row': {key: item.get(key) for key in zycg.COLUMNS}, 'detail': item,
                                 'notice': notice, '_record_source': str(source)}])
        for cache_root in cache_roots:
            for path in Path(cache_root).glob('detail-*.html'):
                self.body_pool[path.name] = str(path.resolve())
        write(ROOT / 'body_cache_sources.json', self.body_pool)
        for start, end in zycg.month_windows(START, END):
            for kind in (7, 11):
                sources = [p for cache_root in cache_roots for p in Path(cache_root).glob(f'page-{start}_{end}-*.html')]
                proof = audit_pages(sources, start, end, kind) if sources else None
                q = self.query(start, end, kind, cache_proof=proof)
                if proof and proof['verified']:
                    cache = Path(q['directory']) / 'cache'
                    cache.mkdir(parents=True, exist_ok=True)
                    for source in sources:
                        destination = cache / source.name
                        if not destination.exists():
                            shutil.copy2(source, destination)
                        self.cache_sources.append({'source': str(source), 'target': str(destination),
                                                   'sha256': sha(source.read_bytes())})
        write(ROOT / 'cache_reuse_provenance.json', self.cache_sources)
        write(ROOT / 'baseline_records.json', list(self.records.values()))
        self.checkpoint()

    def audit_query(self, q):
        paths = list((Path(q['directory']) / 'cache').glob(f"page-{q['start']}_{q['end']}-*.html"))
        if q.get('from_cache'):
            proof = q['cache_proof']
            return {'verified': proof['verified'], 'total': proof['total'], 'unique': proof['unique'],
                    'basis': proof['basis'], 'saved_pages': proof['saved_pages']}
        return audit_pages(paths, q['start'], q['end'], q['bid_type'])

    def restore(self):
        saved = read(ROOT / 'state.json')
        if saved['start'] != START or saved['end'] != END:
            raise ValueError('Existing checkpoint has another date scope')
        self.queries = saved['queries']
        self.records = {record_key(record): record for record in read(ROOT / 'records.json')}
        self.body_pool = read(ROOT / 'body_cache_sources.json')
        self.network_fetch_calls = saved['network_fetch_calls']
        self.cache_body_hits = saved['cache_body_hits']
        self.failures = saved['failures']
        self.started_at = saved['started_at']
        for query in self.queries:
            if query['status'] == 'running':
                query['status'] = 'pending'

    def run_query(self, q):
        self.active_query, self.active_type = q['id'], q['bid_type']
        q['status'], q['started_at'] = 'running', now()
        directory = Path(q['directory'])
        cache = directory / 'cache'
        cache.mkdir(parents=True, exist_ok=True)
        print(f"[query] {q['start']}~{q['end']} type={q['bid_type']} {q['id']}", flush=True)
        self.checkpoint()
        if not q.get('cache_proof'):
            first = cache / f"page-{q['start']}_{q['end']}-0001.html"
            if first.exists():
                raw = first.read_bytes()
            else:
                result = self.fetcher.fetch(typed_url(1, q['start'], q['end'], q['bid_type']), zycg.ALLOWED_DOMAINS)
                if result.get('status') != 'ok':
                    q.update(status='partial', finished_at=now(), failures=[self.pause_reason])
                    self.checkpoint()
                    return
                raw = result.get('raw') or b''
                first.write_bytes(raw)
            info = page_info(raw)
            variables = info['variables']
            if variables.get('bidType') != str(q['bid_type']) or variables.get('agentName') != zycg.AGENT:
                raise ValueError('Search form did not retain the requested notice type and agent')
            if info['pages'] and info['pages'] > 20:
                parts = bisect_dates(q['start'], q['end'])
                if not parts:
                    raise ValueError('Single-day query still exceeds the planned page window')
                children = [self.query(a, b, q['bid_type']) for a, b in parts]
                for child in children:
                    self.queries.remove(child)
                index = self.queries.index(q) + 1
                self.queries[index:index] = children
                q.update(status='split', children=[child['id'] for child in children], split_reason='declared_pages_above_20', declared_pages=info['pages'])
                self.checkpoint()
                return
        def progress(message):
            q['last_message'], q['updated_at'] = message, now()
            print(message, flush=True)
            self.checkpoint()
        code = zycg.collect(q['start'], q['end'], directory, 400, 30, self.delay,
                            split_monthly=False, from_cache=[Path(x) for x in q['from_cache']] or None,
                            progress=progress, include_all=False)
        payload = read(directory / 'zycg_medical_bid.json')
        self.merge(payload['records'])
        for record in payload['records']:
            name = 'detail-' + hashlib.md5(record['notice']['url'].encode()).hexdigest()[:12] + '.html'
            p = cache / name
            if p.exists():
                self.body_pool[name] = str(p)
        audit = self.audit_query(q)
        completed = audit['verified'] and not payload['failures'] and not payload['details_limited']
        q.update(status='completed' if completed else 'partial', finished_at=now(), adapter_exit_code=code,
                 adapter_status=payload['status'], counts=payload['counts'], coverage=audit, failures=payload['failures'])
        self.checkpoint()

    def run(self):
        zycg.Fetcher = lambda **kwargs: self.fetcher
        zycg.search_url = lambda page, start, end: typed_url(page, start, end, self.active_type)
        zycg.write_table = lambda *args, **kwargs: None
        position = 0
        while position < len(self.queries) and not self.paused:
            q = self.queries[position]
            position += 1
            if q['status'] == 'completed':
                continue
            try:
                self.run_query(q)
            except Exception as exc:
                q.update(status='partial', finished_at=now(), error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
                self.failures.append({'at': now(), 'stage': 'unexpected_exception', 'query_id': q['id'],
                                      'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
                self.paused = True
                self.pause_reason = self.failures[-1]
                self.checkpoint()
                break
        self.active_query = None
        self.checkpoint()
        state = read(ROOT / 'state.json')
        leaves = [q for q in self.queries if q['status'] != 'split']
        state.update(status='completed' if all(q['status'] == 'completed' for q in leaves) else 'partial',
                     finished_at=now(), completed_queries=sum(q['status'] == 'completed' for q in leaves),
                     total_leaf_queries=len(leaves), records=len(self.records))
        write(ROOT / 'state.json', state)
        print(json.dumps({'status': state['status'], 'records': len(self.records),
                          'completed_queries': state['completed_queries'], 'total_leaf_queries': len(leaves),
                          'failures': len(self.failures), 'output': str(ROOT)}, ensure_ascii=False), flush=True)


def main():
    global ROOT, START, END
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', default=START)
    parser.add_argument('--end', default=END)
    parser.add_argument('--baseline', type=Path, action='append', default=[])
    parser.add_argument('--cache-root', type=Path, action='append', default=[])
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--delay', type=float, default=8.0)
    args = parser.parse_args()
    ROOT = args.output.resolve()
    START, END = args.start, args.end
    if date.fromisoformat(START) > date.fromisoformat(END):
        parser.error('start must not be after end')
    if args.delay < 0:
        parser.error('delay must be nonnegative')
    existing = (ROOT / 'state.json').exists()
    if existing and not args.resume:
        raise FileExistsError('An existing run is preserved; do not overwrite its checkpoints')
    if (ROOT / 'run.lock').exists():
        raise FileExistsError('Run lock exists; verify the owning process without deleting the lock')
    runner = Runner(args.delay)
    try:
        if existing:
            runner.restore()
        else:
            runner.prepare(args.baseline, args.cache_root)
        spec = {'schema_version': 1, 'task_id': f'zycg-results-{START}-{END}', 'start': START, 'end': END,
                'adapter': str(Path(zycg.__file__)), 'adapter_sha256': sha(Path(zycg.__file__).read_bytes()),
                'agent': zycg.AGENT, 'result_notice_types': [7, 11], 'delay_seconds': args.delay,
                'same_source_concurrency': 1, 'max_pages_per_query': 400,
                'planned_queries': len(runner.queries), 'baseline_records': len(runner.records),
                'validated_at': now(), 'allow_network': not args.validate_only}
        write(ROOT / 'request.json', spec)
        if args.validate_only:
            write(ROOT / 'validated_plan.json', spec)
            print(json.dumps({'status': 'validated', **spec}, ensure_ascii=False), flush=True)
            return
        lock = ROOT / 'run.lock'
        with lock.open('x', encoding='utf-8') as handle:
            json.dump({'pid': os.getpid(), 'started_at': now()}, handle)
        try:
            runner.run()
        finally:
            if read(lock)['pid'] == os.getpid():
                lock.unlink()
    finally:
        runner.fetcher.finish()


if __name__ == '__main__':
    main()
