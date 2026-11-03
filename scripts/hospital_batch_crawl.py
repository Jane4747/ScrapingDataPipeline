"""Batch crawl of the readable hospital official-site entrances.

For each readable entrance (from probe/entry_probe.json):
  1. fetch the entry list page and a few same-directory pagination pages
     (index_1.htm style, ?page=N style, or the href of a 下一页 link);
  2. extract announcement links + dates from each list page;
  3. fetch detail pages for items whose title matches digital-procurement
     keywords (title keyword is a pre-filter only, final judgement is on body);
  4. save raw HTML + per-site summary + global items CSV.

Politeness: sequential requests inside a site with a per-request delay,
several sites in parallel. Stop rules: max pages / max details per site,
or a full list page older than --since (descending-order sites).

Usage:
  python3 scripts/hospital_batch_crawl.py --entrances <entrances.json> \
      --probe <probe/entry_probe.json> --output <dir> [--workers 6] \
      [--since 2024-01-01] [--max-pages 20] [--max-details 80]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

DIGITAL_WORDS = (
    '服务器', '存储', '交换机', '网络', '机房', '云', '虚拟化', '运维', '维保',
    '终端', '数据', '知识库', '数据库', '病案', '科研', '监控', '门禁', '物联网',
    '智慧', '物流', '能源', '系统', '平台', 'HIS', 'LIS', 'PACS', '电子病历',
    '互联网医院', '医保', 'AI', '人工智能', '软件', '安全', '等保', '密码',
    '容灾', '备份', '防火墙', '算力', '大模型', '接口', '信息化', '信息安全',
    '网络安全', '集成', '弱电', '数据中心', '小程序', 'APP', '网站建设',
)
FALSE_LIKE = ('耗材', '试剂', '药品', '被服', '办公用品', '印刷')

DATE_RE = re.compile(
    r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})')
DATE_REV_RE = re.compile(  # "28 2026-10" day-first variant
    r'(\d{1,2})\s+(20\d{2})[-/.](\d{1,2})\b')
DATE_PART_RE = re.compile(  # year-month only
    r'(20\d{2})[-/.年](\d{1,2})(?!\d)')
ANNOUNCE_RE = re.compile(
    r'采购|招标|中标|成交|比选|遴选|谈判|询价|磋商|征集|公告|公示|招采')
PAGINATION_FILE_RE = re.compile(
    r'(?:index|list|page|default|news)[-_]?(\d{1,3})\.(?:s?html?|aspx|php)$', re.I)
NEXT_RE = re.compile(r'下一页|下页|后一页|next|»|›', re.I)

_lock = threading.Lock()
_printq: list[str] = []


def log(msg):
    with _lock:
        _printq.append(msg)
        if len(_printq) >= 20:
            for line in _printq:
                print(line, flush=True)
            _printq.clear()


def flush_log():
    with _lock:
        for line in _printq:
            print(line, flush=True)
        _printq.clear()


def make_opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ctx))
    op.addheaders = [
        ('User-Agent', UA),
        ('Accept', 'text/html,application/xhtml+xml,*/*;q=0.8'),
        ('Accept-Language', 'zh-CN,zh;q=0.9'),
        ('Accept-Encoding', 'identity'),
        ('Connection', 'close'),
    ]
    return op


def fetch2(op, url, timeout=20, max_bytes=800_000):
    req = urllib.request.Request(url)
    started = time.time()
    try:
        with op.open(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes)
            enc = resp.headers.get_content_charset() or ''
            return raw, resp.geturl(), enc, int((time.time() - started) * 1000), resp.status
    except urllib.error.HTTPError as e:
        return b'', url, '', int((time.time() - started) * 1000), e.code
    except Exception as e:
        return b'', url, '', int((time.time() - started) * 1000), f'{type(e).__name__}'


def decode(body, encoding):
    for enc in (encoding, 'utf-8', 'gb18030'):
        try:
            return body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode('utf-8', 'ignore')


def strip_tags(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()


def norm_date(m):
    try:
        return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    except ValueError:
        return ''


def find_date(window):
    d = DATE_RE.search(window)
    if d:
        return norm_date(d)
    d = DATE_REV_RE.search(window)
    if d:
        try:
            return f'{int(d.group(2)):04d}-{int(d.group(3)):02d}-{int(d.group(1)):02d}'
        except ValueError:
            return ''
    d = DATE_PART_RE.search(window)
    if d:
        try:
            return f'{int(d.group(1)):04d}-{int(d.group(2)):02d}-01'
        except ValueError:
            return ''
    return ''


def extract_items(html, page_url):
    """Return list of {title,url,date} for in-site announcement links."""
    items = {}
    low_host = urllib.parse.urlsplit(page_url).netloc
    for m in re.finditer(r'<a\b[^>]*href=(["\'])([^"\']+)\1[^>]*>(.*?)</a>', html, re.S | re.I):
        href, body = m.group(2).strip(), m.group(3)
        if href.startswith(('javascript:', '#', 'mailto:')):
            continue
        text = strip_tags(body)
        # title attr fallback
        tm = re.search(r'title="([^"]+)"', m.group(0), re.I)
        title = text or (tm.group(1) if tm else '')
        if not title:
            # empty-text anchors: title often sits in a sibling div/span just before
            pre = html[max(0, m.start() - 800):m.start()]
            tm2 = re.findall(
                r'<(?:div|h[1-6]|span|p|li)\b[^>]*class="[^"]*(?:h["\s]|title|tit)[^"]*"[^>]*>(.*?)</',
                pre, re.S)
            if tm2:
                title = strip_tags(tm2[-1])
        if not title or len(title) < 6:
            continue
        if not ANNOUNCE_RE.search(title):
            continue
        # same-link HTML entity fix
        href = urllib.parse.urljoin(page_url, href.replace('&amp;', '&'))
        split = urllib.parse.urlsplit(href)
        if split.netloc and low_host not in split.netloc:
            continue
        # date: raw window around the anchor catches <span class="date"> etc.
        window = html[max(0, m.start() - 500):min(len(html), m.end() + 500)]
        date = find_date(window)
        key = href.split('#')[0]
        if key not in items or (date and not items[key]['date']):
            items[key] = {'title': title.strip(), 'url': key, 'date': date}
    if items:
        return list(items.values())
    # fallback: some CMS embed full announcements in the list page itself
    # (<div class="x-tit...">title</div> ... 发布时间：YYYY-MM-DD), no anchors.
    for m in re.finditer(
            r'(?s)<(?:div|h[1-6])[^>]*class="[^"]*(?:x-tit|item-title|list-title)[^"]*"[^>]*>'
            r'(.*?)</(?:div|h[1-6])>.{0,400}?发布时间[:：]\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})',
            html):
        title = strip_tags(m.group(1))
        if not title or not ANNOUNCE_RE.search(title):
            continue
        d = re.match(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})', m.group(2))
        date = norm_date(d) if d else ''
        slug = re.sub(r'\W+', '', title)[:20] or str(len(items))
        items[page_url + '#' + slug] = {
            'title': title, 'url': page_url + '#' + slug, 'date': date}
    return list(items.values())


def digital_hits(title):
    low = title.lower()
    hits = [w for w in DIGITAL_WORDS if w.lower() in low]
    return hits


def find_list_pages(html, page_url, seen):
    """Pagination links: next-page anchors, numeric page links inside a
    pagination block, or ?page=N style queries. May live in subdirs (/p/2.html)."""
    out = []
    split = urllib.parse.urlsplit(page_url)
    for m in re.finditer(r'<a\b[^>]*href=(["\'])([^"\']+)\1[^>]*>(.*?)</a>', html, re.S | re.I):
        href, text = m.group(2), strip_tags(m.group(3))
        full = urllib.parse.urljoin(page_url, href.replace('&amp;', '&'))
        s2 = urllib.parse.urlsplit(full)
        if s2.netloc != split.netloc or full in seen or full == page_url:
            continue
        fname = s2.path.rsplit('/', 1)[-1]
        window = html[max(0, m.start() - 600):m.end() + 200]
        pag_block = bool(re.search(r'下一页|上一页|末页|首页|pagination|paging|_page\b', window, re.I))
        is_next = bool(NEXT_RE.search(text)) and len(text) <= 6
        is_num = (text.strip().isdigit() and 1 <= int(text.strip()) <= 999) \
            or bool(PAGINATION_FILE_RE.search(fname))
        is_query = bool(re.search(
            r'[?&](page|pageno|pageindex|currpage|p)=\d+', s2.query, re.I))
        if is_next or is_query or (is_num and pag_block):
            out.append(full)
    return out[:8]


def crawl_site(ent, outdir, since, max_pages, max_details, delay, opener):
    task_id = ent['task_id']
    site_dir = outdir / task_id
    (site_dir / 'list').mkdir(parents=True, exist_ok=True)
    (site_dir / 'details').mkdir(parents=True, exist_ok=True)
    entry = ent['url']
    since_cmp = since.replace('-', '')

    all_items = {}
    pages_done = []
    queue = [entry]
    seen_pages = set()
    pages_fetched = 0
    stop_reason = ''
    details_fetched = 0
    detail_fail = 0
    errors = []

    while queue and pages_fetched < max_pages:
        url = queue.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        body, final, enc, ms, status = fetch2(opener, url)
        pages_fetched += 1
        if not isinstance(status, int) or status != 200 or not body:
            errors.append({'url': url, 'status': str(status)})
            continue
        html = decode(body, enc)
        (site_dir / 'list' / f'page_{pages_fetched:03d}.html').write_text(
            html, encoding='utf-8', errors='ignore')
        items = extract_items(html, url)
        new = [i for i in items if i['url'] not in all_items]
        for i in new:
            all_items[i['url']] = i
        pages_done.append({'page': pages_fetched, 'url': url, 'items': len(new),
                           'ms': ms, 'status': status})
        log(f'  {task_id} page{pages_fetched} +{len(new)} items (total {len(all_items)})')
        if not new:
            if pages_fetched > 1:
                stop_reason = 'no_new_items'
                break
            # landing/hub page: follow announcement-column navigation links
            for m2 in re.finditer(r'<a\b[^>]*href=(["\'])([^"\']+)\1[^>]*>(.*?)</a>', html, re.S | re.I):
                nav_text = strip_tags(m2.group(3))
                if len(nav_text) <= 12 and re.search(r'招标|采购|公告|公示|招采', nav_text):
                    nav_url = urllib.parse.urljoin(url, m2.group(2).replace('&amp;', '&'))
                    s2 = urllib.parse.urlsplit(nav_url)
                    if s2.netloc == urllib.parse.urlsplit(url).netloc and nav_url not in seen_pages:
                        queue.append(nav_url)
            if len(queue) > 4:
                queue = queue[-4:]
        # descending sites: if every dated item on this page is older than since, stop
        dated = [i['date'].replace('-', '') for i in new if i['date']]
        if dated and max(dated) < since_cmp:
            stop_reason = 'older_than_since'
            break
        for nxt in find_list_pages(html, url, seen_pages):
            queue.append(nxt)
        time.sleep(delay)

    # rank items: dated first desc, undated last
    items = sorted(all_items.values(),
                   key=lambda x: x['date'] or '0000-00-00', reverse=True)
    detail_rows = []
    for i in items:
        hits = digital_hits(i['title'])
        cand = bool(hits) and not any(w in i['title'] for w in FALSE_LIKE)
        row = dict(i, digital_hits='|'.join(hits), candidate=int(cand),
                   detail_status='', detail_ms='')
        if cand and details_fetched < max_details and '#' not in i['url']:
            body, final, enc, ms, status = fetch2(opener, i['url'])
            if isinstance(status, int) and status == 200 and body:
                details_fetched += 1
                safe = re.sub(r'[^0-9A-Za-z]', '', urllib.parse.urlsplit(i['url']).path)[-24:] or f'd{details_fetched}'
                (site_dir / 'details' / f'{safe}.html').write_bytes(body)
                row['detail_status'] = '200'
                row['detail_ms'] = ms
            else:
                detail_fail += 1
                row['detail_status'] = str(status)
            time.sleep(delay)
        detail_rows.append(row)

    summary = {
        'task_id': task_id,
        'hospital': ent['hospital'],
        'batch': ent['batch'],
        'entry': entry,
        'list_pages': pages_fetched,
        'items_total': len(items),
        'items_since': sum(1 for i in items if i['date'] and i['date'] >= since),
        'items_dated': sum(1 for i in items if i['date']),
        'candidates': sum(r['candidate'] for r in detail_rows),
        'details_saved': details_fetched,
        'detail_fail': detail_fail,
        'stop_reason': stop_reason or 'page_cap_or_done',
        'errors': errors[:10],
        'pages': pages_done,
    }
    with open(site_dir / 'items.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'title', 'url', 'date', 'digital_hits', 'candidate',
            'detail_status', 'detail_ms'])
        w.writeheader()
        for r in detail_rows:
            w.writerow(r)
    (site_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f'{task_id} {ent["hospital"][:18]} done: pages={pages_fetched} '
        f'items={len(items)} since={summary["items_since"]} cand={summary["candidates"]} '
        f'det={details_fetched}/{detail_fail} stop={summary["stop_reason"]}')
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entrances', required=True)
    ap.add_argument('--probe', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--since', default='2024-01-01')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--max-pages', type=int, default=20)
    ap.add_argument('--max-details', type=int, default=80)
    ap.add_argument('--delay', type=float, default=1.0)
    ap.add_argument('--only', default='', help='comma separated task_ids to limit run')
    args = ap.parse_args()

    ents = json.load(open(args.entrances, encoding='utf-8'))['entrances']
    probe = json.load(open(args.probe, encoding='utf-8'))['results']
    readable = {r['task_id'] for r in probe if r['kind'] == 'readable'}
    only = {t.strip() for t in args.only.split(',') if t.strip()}

    targets = [e for e in ents if e['task_id'] in readable]
    # P0 already piloted separately
    targets = [e for e in targets if e['task_id'] != 'C0057']
    if only:
        targets = [e for e in targets if e['task_id'] in only]
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f'targets: {len(targets)} readable sites (C0057 excluded)', flush=True)

    summaries = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(crawl_site, e, outdir, args.since, args.max_pages,
                          args.max_details, args.delay, make_opener()): e
                for e in targets}
        for fut in as_completed(futs):
            e = futs[fut]
            try:
                summaries.append(fut.result())
            except Exception as exc:  # site-level crash should not kill the batch
                log(f'FATAL {e["task_id"]} {e["hospital"][:20]}: {type(exc).__name__} {exc}')
                summaries.append({'task_id': e['task_id'], 'hospital': e['hospital'],
                                  'batch': e['batch'], 'entry': e['url'],
                                  'fatal': f'{type(exc).__name__}: {exc}'})
    flush_log()
    summaries.sort(key=lambda s: (s.get('batch', ''), s.get('task_id', '')))
    (outdir / 'batch_summary.json').write_text(
        json.dumps({'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'since': args.since, 'count': len(summaries),
                    'summaries': summaries},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    with open(outdir / 'batch_summary.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['task_id', 'batch', 'hospital', 'entry', 'list_pages',
                    'items_total', 'items_dated', 'items_since', 'candidates',
                    'details_saved', 'detail_fail', 'stop_reason', 'fatal'])
        for s in summaries:
            w.writerow([s.get('task_id'), s.get('batch'), s.get('hospital'),
                        s.get('entry'), s.get('list_pages', 0),
                        s.get('items_total', 0), s.get('items_dated', 0),
                        s.get('items_since', 0), s.get('candidates', 0),
                        s.get('details_saved', 0), s.get('detail_fail', 0),
                        s.get('stop_reason', ''), s.get('fatal', '')])
    tot = Counter()
    for s in summaries:
        for k in ('items_total', 'items_since', 'candidates', 'details_saved', 'detail_fail'):
            tot[k] += s.get(k, 0)
    print('BATCH DONE', dict(tot), flush=True)


if __name__ == '__main__':
    main()
