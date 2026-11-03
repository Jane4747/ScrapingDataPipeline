"""Read-only reachability probe for hospital entry pages.

One GET per entrance (plus one robots.txt per domain) so a batch of 90 sites
can be triaged before any crawling: readable / needs rendering / restricted /
broken. No paging, no detail crawl, no retries that could look like load.

Usage:
  python3 scripts/hospital_entry_probe.py --entrances <entrances.json> --output <dir>
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
TIMEOUT = 20
KEYWORDS = ('采购', '招标', '中标', '成交', '比选', '谈判', '调研', '公告')


def fetch(url, timeout=TIMEOUT, max_bytes=600_000):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'identity',
        'Connection': 'close',
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read(max_bytes)
        return {
            'status': resp.status,
            'final_url': resp.geturl(),
            'content_type': resp.headers.get('Content-Type', ''),
            'encoding': resp.headers.get_content_charset() or 'utf-8',
            'body': raw,
            'elapsed_ms': int((time.time() - started) * 1000),
        }


def decode(body, encoding):
    for enc in (encoding, 'utf-8', 'gb18030'):
        try:
            return body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode('utf-8', 'ignore')


def page_title(html):
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    if not m:
        return ''
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()[:120]


def visible_text_len(html):
    text = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html)
    text = re.sub(r'<[^>]+>', ' ', text)
    return len(re.sub(r'\s+', '', text))


def classify(status, html, final_url, entry_url, robots):
    text_len = visible_text_len(html)
    low = html.lower()
    js_shell = text_len < 600 or ('enable javascript' in low or '请开启javascript' in low.replace(' ', ''))
    keyword_hits = sum(1 for k in KEYWORDS if k in html)
    same_host = urllib.parse.urlsplit(final_url).netloc == urllib.parse.urlsplit(entry_url).netloc
    if status in (401, 403, 407, 412, 429, 451, 503):
        kind = 'restricted'
    elif status in (404, 410):
        kind = 'broken'
    elif status >= 400:
        kind = 'error'
    elif not same_host:
        kind = 'redirect_external'
    elif js_shell:
        kind = 'needs_rendering'
    elif robots.get('blocked'):
        kind = 'robots_blocked'
    else:
        kind = 'readable'
    return {'kind': kind, 'text_len': text_len, 'js_shell': js_shell,
            'keyword_hits': keyword_hits, 'same_host': same_host}


def check_robots(entry_url):
    parts = urllib.parse.urlsplit(entry_url)
    robots_url = f'{parts.scheme}://{parts.netloc}/robots.txt'
    try:
        res = fetch(robots_url, timeout=12, max_bytes=80_000)
        text = decode(res['body'], res['encoding'])
        blocked = bool(re.search(r'(?im)^\s*disallow:\s*/\s*$', text))
        return {'url': robots_url, 'status': res['status'], 'blocked': blocked,
                'note': 'disallow_all' if blocked else 'allow'}
    except urllib.error.HTTPError as exc:
        return {'url': robots_url, 'status': exc.code, 'blocked': False, 'note': 'http_error'}
    except Exception as exc:  # noqa: BLE001 - probe keeps going on any transport error
        return {'url': robots_url, 'status': None, 'blocked': False,
                'note': type(exc).__name__}


def probe_one(entry, robots_cache):
    url = entry['url'].strip()
    out = {
        'task_id': entry['task_id'], 'batch': entry['batch'], 'hospital': entry['hospital'],
        'column_type': entry['column_type'], 'url': url,
    }
    try:
        res = fetch(url)
        html = decode(res['body'], res['encoding'])
        domain = urllib.parse.urlsplit(url).netloc
        if domain not in robots_cache:
            robots_cache[domain] = check_robots(url)
        robots = robots_cache[domain]
        info = classify(res['status'], html, res['final_url'], url, robots)
        out.update({
            'http_status': res['status'], 'final_url': res['final_url'],
            'content_type': res['content_type'], 'title': page_title(html),
            'bytes': len(res['body']), 'elapsed_ms': res['elapsed_ms'],
            'robots': robots.get('note'), **info,
        })
    except urllib.error.HTTPError as exc:
        out.update({'http_status': exc.code, 'kind': 'restricted' if exc.code in (401, 403, 412, 429) else 'error',
                    'title': '', 'bytes': 0, 'elapsed_ms': None, 'error': f'HTTPError {exc.code}'})
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError) as exc:
        reason = getattr(exc, 'reason', exc)
        kind = 'dns_fail' if 'getaddrinfo' in str(reason) or 'Name or service' in str(reason) else 'unreachable'
        out.update({'http_status': None, 'kind': kind, 'title': '', 'bytes': 0,
                    'elapsed_ms': None, 'error': f'{type(exc).__name__}: {reason}'})
    except Exception as exc:  # noqa: BLE001
        out.update({'http_status': None, 'kind': 'error', 'title': '', 'bytes': 0,
                    'elapsed_ms': None, 'error': f'{type(exc).__name__}: {exc}'})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--entrances', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()

    data = json.loads(Path(args.entrances).read_text(encoding='utf-8'))
    entries = data['entrances'] if isinstance(data, dict) else data
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    robots_cache = {}
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(probe_one, e, robots_cache) for e in entries]
        for fut in futures:
            results.append(fut.result())
    order = {e['task_id']: i for i, e in enumerate(entries)}
    results.sort(key=lambda r: order[r['task_id']])

    summary = {}
    for r in results:
        summary[r['kind']] = summary.get(r['kind'], 0) + 1
    payload = {
        'probed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'entrances': len(results),
        'summary': summary,
        'results': results,
    }
    (out_dir / 'entry_probe.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    with (out_dir / 'entry_probe.csv').open('w', encoding='utf-8-sig', newline='') as fh:
        cols = ['task_id', 'batch', 'hospital', 'column_type', 'kind', 'http_status', 'title',
                'text_len', 'keyword_hits', 'robots', 'elapsed_ms', 'url', 'final_url', 'error']
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(json.dumps({'entrances': len(results), 'summary': summary,
                      'out': str(out_dir / 'entry_probe.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
