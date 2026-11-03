"""Pilot crawl for the 北京大学第三医院 招标采购 column (task C0057).

Purpose: prove the list → detail pipeline on the P0 site before touching the
other 89 entrances. Reads the paginated list, keeps items published on or after
the task start date, flags likely digital-procurement titles, then saves the
matched detail pages. One request at a time with a delay; no retries storm.

Usage:
  python3 scripts/puh3_pilot_crawl.py --output <dir> [--since 2024-01-01] [--max-pages 91]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'https://www.puh3.net.cn/xwzx/rdgg1/'
LIST_URL = BASE + 'zbcg.htm'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
DELAY = 1.0

DIGITAL_WORDS = (
    '信息', '软件', '系统', '平台', '数据', '服务器', '存储', '交换机', '网络', '安全',
    '云', '机房', '数据库', '接口', '智慧', '智能', '人工智能', 'AI', '运维', '维保',
    '病案', '电子病历', '影像', 'PACS', 'LIS', 'HIS', 'DRG', 'DIP', '医保', '互联网医院',
    '监控', '门禁', '物联网', '终端', '密码', '等保', '容灾', '备份', '大模型', '算力',
)
EXCLUDE_DEVICE = ('试剂', '耗材', '药品', '设备维保', '消毒', '被服', '家具', '空调', '电梯')


def opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    build = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
    build.addheaders = [('User-Agent', UA), ('Accept-Encoding', 'identity'),
                        ('Accept-Language', 'zh-CN,zh;q=0.9')]
    return build


def get(op, url, timeout=30):
    with op.open(urllib.request.Request(url), timeout=timeout) as resp:
        return resp.status, resp.geturl(), resp.read(1_500_000)


def parse_items(html, page_url=LIST_URL):
    """Items live in <li id="line_..."> rows; the featured block (tz-top) repeats the first three."""
    items = []
    for m in re.finditer(r'(?s)<li[^>]*id="line_[^"]*"[^>]*>(.*?)</li>', html):
        body = m.group(1)
        a = re.search(r'href="([^"]*?/info/\d+/\d+\.htm)"', body)
        t = re.search(r'<h2[^>]*>(.*?)</h2>', body, re.S)
        d = re.search(r'<span[^>]*>\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\s*</span>', body)
        if not (a and t):
            continue
        title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', t.group(1))).strip()
        date = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}' if d else ''
        canonical = urllib.parse.urljoin(page_url, a.group(1))
        items.append({'title': title, 'date': date, 'url': canonical})
    if items:
        return items
    for m in re.finditer(r'(?s)<a[^>]+href="([^"]*?/info/\d+/\d+\.htm)"[^>]*>(.*?)</a>', html):
        body = m.group(2)
        if 'tz-top' not in body:
            continue
        t = re.search(r'<h2[^>]*>(.*?)</h2>', body, re.S)
        d = re.search(r'<span>\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\s*</span>', body)
        if not t:
            continue
        items.append({
            'title': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', t.group(1))).strip(),
            'date': f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}' if d else '',
            'url': urllib.parse.urljoin(page_url, m.group(1)),
        })
    return items


def digital_hits(title):
    hits = [w for w in DIGITAL_WORDS if w.lower() in title.lower()]
    blocked = [w for w in EXCLUDE_DEVICE if w in title]
    return hits, blocked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--output', required=True)
    ap.add_argument('--since', default='2024-01-01')
    ap.add_argument('--max-pages', type=int, default=52)
    ap.add_argument('--max-details', type=int, default=120)
    args = ap.parse_args()

    out = Path(args.output)
    (out / 'list').mkdir(parents=True, exist_ok=True)
    (out / 'detail').mkdir(parents=True, exist_ok=True)
    op = opener()

    page_urls = [LIST_URL] + [f'{BASE}zbcg/{n}.htm' for n in range(90, 90 - args.max_pages, -1)]
    all_items, pages_log, stop = [], [], False
    for idx, url in enumerate(page_urls, start=1):
        if stop:
            break
        try:
            status, final, body = get(op, url)
            html = body.decode('utf-8', 'ignore')
            (out / 'list' / f'page_{idx:03d}.html').write_text(html, encoding='utf-8')
            items = parse_items(html, url)
            dated = [i['date'] for i in items if i['date']]
            oldest = min(dated) if dated else ''
            pages_log.append({'page': idx, 'url': url, 'status': status, 'items': len(items),
                              'oldest': oldest})
            for it in items:
                it['list_page'] = idx
            all_items.extend(items)
            if oldest and oldest < args.since:
                stop = True
        except Exception as exc:  # noqa: BLE001 - a failed page is logged, not fatal
            pages_log.append({'page': idx, 'url': url, 'status': None, 'items': 0,
                              'error': f'{type(exc).__name__}: {exc}'})
        time.sleep(DELAY)

    seen, kept = set(), []
    for it in all_items:
        if it['url'] in seen:
            continue
        seen.add(it['url'])
        if it['date'] and it['date'] >= args.since:
            hits, blocked = digital_hits(it['title'])
            it['digital_hits'] = hits
            it['device_words'] = blocked
            it['candidate'] = bool(hits)
            kept.append(it)
    kept.sort(key=lambda x: (x['date'], x['title']), reverse=True)

    details, fetched = [], 0
    for it in kept:
        if not it['candidate'] or fetched >= args.max_details:
            continue
        try:
            status, final, body = get(op, it['url'])
            name = re.sub(r'[^0-9A-Za-z]+', '_', it['url'].rsplit('/', 1)[-1])
            (out / 'detail' / name).write_bytes(body)
            html = body.decode('utf-8', 'ignore')
            it['detail_status'] = status
            it['detail_bytes'] = len(body)
            it['detail_title'] = (re.search(r'<title[^>]*>(.*?)</title>', html, re.S).group(1).strip()
                                  if re.search(r'<title[^>]*>(.*?)</title>', html, re.S) else '')
            fetched += 1
            details.append(it)
        except Exception as exc:  # noqa: BLE001
            it['detail_status'] = None
            it['detail_error'] = f'{type(exc).__name__}: {exc}'
        time.sleep(DELAY)

    with (out / 'list_items.csv').open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['date', 'title', 'url', 'list_page', 'digital_hits', 'device_words',
                    'candidate', 'detail_status', 'detail_bytes'])
        for it in kept:
            w.writerow([it['date'], it['title'], it['url'], it['list_page'],
                        '、'.join(it['digital_hits']), '、'.join(it['device_words']),
                        int(it['candidate']), it.get('detail_status', ''), it.get('detail_bytes', '')])
    summary = {
        'site': '北京大学第三医院 招标采购',
        'list_url': LIST_URL,
        'since': args.since,
        'pages_fetched': len(pages_log),
        'list_items_total': len(seen),
        'items_since_start': len(kept),
        'candidates': sum(1 for i in kept if i['candidate']),
        'details_saved': fetched,
        'detail_failures': sum(1 for i in kept if i.get('detail_error')),
        'earliest_kept': min((i['date'] for i in kept), default=''),
        'latest_kept': max((i['date'] for i in kept), default=''),
        'pages': pages_log,
    }
    (out / 'pilot_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'pages'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
