"""Site-specific finishers for the 4 hospital sites that failed generic crawl.

Learned from the gtbjah Crawl4AI tree: discover the real list mechanism first,
then reuse it. Strategies:
  C0003 解放军总医院  - server-rendered portal tables: proclamation-type-1/2.html
                        + Admin-Portal-...-page_num-20-p-N.html; rows carry
                        onclick-details, title in <p title=...>.
  C0067 门头沟区医院  - page-1 items server-rendered in #js-box (links may point
                        to mp.weixin.qq.com); &page=N (N>=2) returns <li> fragments.
  C0077 北大国际医院  - encrypted ajax; use Crawl4AI session + click a.laypage_next,
                        items in div[data] blocks (day/year split date).
  C0082 广安门南区    - static ArticleList li (short titles like 公示 in title attr);
                        pagination via 下一页 href (pagesize/pagenum).

Run with the BigData env: D:/Anaconda3/envs/BigData/python.exe
Output: outputs/hospital-site-crawl-90-20261028/batch-20261028/<TASKID>/render-fix/
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r'E:\CAICTBigData\coding')
sys.path.insert(0, str(ROOT / 'scripts'))
import hospital_batch_crawl as hbc  # noqa: E402

BASE = ROOT / 'outputs/hospital-site-crawl-90-20261028/batch-20261028'
SINCE = '2024-01-01'
DELAY = 1.5
MAX_PAGES = 30
MAX_DETAILS = 100
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / 'outputs/hospital-site-crawl-90-20261028/render-probe/runtime-temp')
os.environ['CRAWL4AI_NO_CLOUD_NOTICE'] = '1'

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def static_op(extra=None):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                     urllib.request.HTTPSHandler(context=CTX))
    op.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0'),
                     ('Accept', 'text/html,*/*;q=0.8'),
                     ('Accept-Language', 'zh-CN,zh;q=0.9'),
                     ('Accept-Encoding', 'identity'), ('Connection', 'close')]
    for k, v in (extra or {}).items():
        op.addheaders.append((k, v))
    return op


def save(d, name, text, binary=False):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if binary:
        p.write_bytes(text)
    else:
        p.write_text(text, encoding='utf-8', errors='ignore')


def write_site_out(tid, hospital, batch, entry, items, pages_fetched,
                   stop, errors, details_saved, detail_fail):
    """Write render-fix items.csv + summary.json in the same schema as the
    batch crawler so the global summary merge stays uniform."""
    site = BASE / tid / 'render-fix'
    items = sorted(items, key=lambda x: x['date'] or '0000-00-00', reverse=True)
    import csv as _csv
    with open(site / 'items.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.DictWriter(f, fieldnames=['title', 'url', 'date', 'notice_type',
                                           'external', 'digital_hits',
                                           'candidate', 'detail_status', 'detail_ms'])
        w.writeheader()
        for i in items:
            hits = hbc.digital_hits(i['title'])
            i.setdefault('candidate', int(bool(hits) and not any(x in i['title'] for x in hbc.FALSE_LIKE)))
            i.setdefault('detail_status', '')
            i.setdefault('detail_ms', '')
            row = dict(i, digital_hits='|'.join(hits))
            w.writerow(row)
    summary = {'task_id': tid, 'hospital': hospital, 'batch': batch, 'entry': entry,
               'list_pages': pages_fetched, 'items_total': len(items),
               'items_dated': sum(1 for i in items if i['date']),
               'items_since': sum(1 for i in items if i['date'] and i['date'] >= SINCE),
               'candidates': sum(1 for i in items if i.get('candidate')),
               'details_saved': details_saved, 'detail_fail': detail_fail,
               'stop_reason': stop, 'engine': 'static+site-specific' if not tid.endswith('C0077') else 'Crawl4AI/browser',
               'errors': errors[:10]}
    (site / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                       encoding='utf-8')
    print(f'{tid} DONE pages={pages_fetched} items={len(items)} '
          f'since={summary["items_since"]} cand={summary["candidates"]} '
          f'det={details_saved}/{detail_fail} stop={stop}', flush=True)
    return summary


def fetch_static(op, url, timeout=25):
    try:
        with op.open(url, timeout=timeout) as r:
            raw = r.read(900_000)
        return hbc.decode(raw, ''), 200
    except urllib.error.HTTPError as e:
        return '', e.code
    except Exception as e:
        return '', f'{type(e).__name__}'


def detail_pass(op, items, site, url_key='url'):
    saved = fail = 0
    for i in items:
        if not i.get('candidate'):
            continue
        u = i[url_key]
        if '#' in u or urllib.parse.urlsplit(u).netloc not in (
                urllib.parse.urlsplit(u).netloc,):
            pass
        body, status = fetch_static(op, u)
        if status == 200 and body:
            safe = re.sub(r'[^0-9A-Za-z]', '', urllib.parse.urlsplit(u).path)[-24:] or f'd{saved}'
            save(site / 'details', f'{safe}.html', body)
            i['detail_status'] = '200'
            saved += 1
        else:
            i['detail_status'] = str(status)
            fail += 1
        time.sleep(DELAY)
    return saved, fail


# ---------------------------------------------------------------- C0003 ----
ROW_RE = re.compile(
    r"(?s)<tr[^>]*onclick=\"location='([^']+)'\">(.*?)</tr>")


def c0003_parse_rows(html, page_url):
    rows = []
    for m in ROW_RE.finditer(html):
        det, body = m.group(1), m.group(2)
        t = re.search(r'<p[^>]*title="([^"]+)"', body)
        d = re.search(r'<td>\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})', body)
        typ = re.search(r'\[([^\]]{2,10})\]', body)
        if not (t and det):
            continue
        rows.append({'title': t.group(1).strip(),
                     'url': urllib.parse.urljoin(page_url, det),
                     'date': hbc.norm_date(re.match(r'(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})', d.group(1))) if d else '',
                     'notice_type': typ.group(1) if typ else ''})
    return rows


def fix_c0003():
    op = static_op()
    site = BASE / 'C0003' / 'render-fix'
    entry = 'https://zbcg.301hospital.com.cn/'
    items = {}
    pages = 0
    errors = []
    stop = 'done'
    for typ in (1, 2):
        url = f'https://zbcg.301hospital.com.cn/Admin-Portal-proclamation-type-{typ}.html'
        for pno in range(1, MAX_PAGES + 1):
            u = url if pno == 1 else \
                f'https://zbcg.301hospital.com.cn/Admin-Portal-proclamation-type-{typ}-page_num-20-p-{pno}.html'
            html, status = fetch_static(op, u)
            pages += 1
            if status != 200:
                errors.append({'url': u, 'status': str(status)})
                break
            save(site / 'list', f'type{typ}_p{pno:03d}.html', html)
            rows = c0003_parse_rows(html, u)
            if not rows:
                stop = 'no_new_items'
                break
            new = 0
            for r in rows:
                if r['url'] not in items:
                    items[r['url']] = r
                    new += 1
            dated = [r['date'].replace('-', '') for r in rows if r['date']]
            print(f'  C0003 type{typ} p{pno} rows={len(rows)} new={new}', flush=True)
            if dated and max(dated) < SINCE.replace('-', ''):
                stop = 'older_than_since'
                break
            if new == 0:
                stop = 'no_new_items'
                break
            time.sleep(DELAY)
    ordered = list(items.values())
    for i in ordered:
        hits = hbc.digital_hits(i['title'])
        i['candidate'] = int(bool(hits) and not any(x in i['title'] for x in hbc.FALSE_LIKE))
    saved, fail = detail_pass(op, ordered, site)
    return write_site_out('C0003', '中国人民解放军总医院', 'P3', entry,
                          ordered, pages, stop, errors, saved, fail)


# ---------------------------------------------------------------- C0067 ----
LI_RE = re.compile(
    r"(?s)<li[^>]*>\s*<div class=\"txt\">\s*<span class=\"time\">\s*(20\d{2}-\d{1,2}-\d{1,2})\s*"
    r"</span>\s*<h4>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>")


def c0067_parse(html):
    out = []
    for m in LI_RE.finditer(html):
        date, href, title = m.group(1), m.group(2), hbc.strip_tags(m.group(3))
        if not title:
            continue
        out.append({'title': title, 'url': href, 'date': date, 'external':
                    'mtgqyy.cn' not in urllib.parse.urlsplit(href).netloc})
    return out


def fix_c0067():
    op = static_op({'Referer': 'https://www.mtgqyy.cn/'})
    site = BASE / 'C0067' / 'render-fix'
    base_url = 'https://www.mtgqyy.cn/index.php?c=article&a=type&tid=77'
    items = {}
    pages = 0
    errors = []
    stop = 'done'
    for pno in range(1, MAX_PAGES + 1):
        u = base_url if pno == 1 else f'{base_url}&page={pno}'
        html, status = fetch_static(op, u)
        pages += 1
        if status != 200:
            errors.append({'url': u, 'status': str(status)})
            break
        save(site / 'list', f'page_{pno:03d}.html', html)
        rows = c0067_parse(html)
        if pno > 1 and not rows:
            stop = 'no_new_items'
            break
        new = 0
        for r in rows:
            if r['url'] not in items:
                items[r['url']] = r
                new += 1
        print(f'  C0067 p{pno} rows={len(rows)} new={new}', flush=True)
        if pno > 1 and new == 0:
            stop = 'no_new_items'
            break
        dated = [r['date'].replace('-', '') for r in rows if r['date']]
        if pno > 1 and dated and min(dated) < SINCE.replace('-', ''):
            stop = 'older_than_since'
            break
        time.sleep(DELAY)
    ordered = list(items.values())
    for i in ordered:
        hits = hbc.digital_hits(i['title'])
        i['candidate'] = int(bool(hits) and not any(x in i['title'] for x in hbc.FALSE_LIKE))
    # details only for same-host items
    saved = fail = 0
    for i in ordered:
        if not i['candidate'] or i['external']:
            continue
        body, status = fetch_static(op, i['url'])
        if status == 200 and body:
            safe = re.sub(r'[^0-9A-Za-z]', '', urllib.parse.urlsplit(i['url']).path)[-24:]
            save(site / 'details', f'{safe}.html', body)
            i['detail_status'] = '200'
            saved += 1
        else:
            i['detail_status'] = str(status)
            fail += 1
        time.sleep(DELAY)
    return write_site_out('C0067', '北京市门头沟区医院', 'P2', base_url,
                          ordered, pages, stop, errors, saved, fail)


# ---------------------------------------------------------------- C0082 ----
ART_RE = re.compile(
    r"(?s)<li><span class=\"DataItemIcon\"></span><a href=\"([^\"]+)\"[^>]*title=\"([^\"]*)\"[^>]*>(.*?)</a>"
    r"<span class=\"Date\">\[(20\d{2}-\d{1,2}-\d{1,2})\]</span>")


def c0082_parse(html, page_url):
    out = []
    for m in ART_RE.finditer(html):
        href, tattr, text, date = m.groups()
        title = tattr.strip() or hbc.strip_tags(text)
        if not title:
            continue
        out.append({'title': title, 'url': href, 'date': date})
    return out


def fix_c0082():
    op = static_op()
    site = BASE / 'C0082' / 'render-fix'
    url = 'http://www.gamhnq.cn/common/index.aspx?nodeid=81'
    items = {}
    pages = 0
    errors = []
    stop = 'done'
    while pages < MAX_PAGES:
        html, status = fetch_static(op, url)
        pages += 1
        if status != 200:
            errors.append({'url': url, 'status': str(status)})
            break
        save(site / 'list', f'page_{pages:03d}.html', html)
        rows = c0082_parse(html, url)
        new = 0
        for r in rows:
            if r['url'] not in items:
                items[r['url']] = r
                new += 1
        print(f'  C0082 p{pages} rows={len(rows)} new={new} url={url[-40:]}', flush=True)
        dated = [r['date'].replace('-', '') for r in rows if r['date']]
        if dated and max(dated) < SINCE.replace('-', ''):
            stop = 'older_than_since'
            break
        if not new and pages > 1:
            stop = 'no_new_items'
            break
        m = re.search(r"href='([^']+)'\s*><img[^>]*title='下一页'", html)
        if not m:
            stop = 'no_next_link'
            break
        nxt = m.group(1)
        if nxt == url:
            stop = 'no_next_link'
            break
        url = nxt
        time.sleep(DELAY)
    ordered = list(items.values())
    for i in ordered:
        hits = hbc.digital_hits(i['title'])
        i['candidate'] = int(bool(hits) and not any(x in i['title'] for x in hbc.FALSE_LIKE))
    saved, fail = detail_pass(op, ordered, site)
    return write_site_out('C0082', '中国中医科学院广安门医院（南区）', 'P2',
                          'http://www.gamhnq.cn/common/index.aspx?nodeid=81',
                          ordered, pages, stop, errors, saved, fail)


# ---------------------------------------------------------------- C0077 ----
# The list is served by POST /cebest-cms/cus/search. The browser computes a
# signature via /cebest-cms/cus/sign and an encrypted searchCondition via
# /cebest-cms/cus/encryptJson; both are plain JSON POSTs we can replicate.
# Responses include content1 (full body HTML), so details need no extra fetch.
C0077_ENTRY = 'https://www.pkuih.edu.cn/news-announcement/hospital-announcement.html'


def c0077_call(op, path, payload):
    req = urllib.request.Request(
        'https://www.pkuih.edu.cn' + path, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json',
                 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0',
                 'Origin': 'https://www.pkuih.edu.cn', 'Referer': C0077_ENTRY,
                 'Accept': 'application/json, text/javascript, */*; q=0.01',
                 'X-Requested-With': 'XMLHttpRequest'})
    with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
        return json.loads(r.read().decode())


def fix_c0077():
    op = static_op()
    site = BASE / 'C0077' / 'render-fix'
    cond = [{"field": "title", "operator": "LIKE", "value": "%%"}]
    cond_json = json.dumps({"conditions": cond})
    s1 = c0077_call(op, '/cebest-cms/cus/sign', {'json': cond_json})
    s2 = c0077_call(op, '/cebest-cms/cus/encryptJson', {'json': cond_json})

    def search(page, limit=50):
        payload = {'limit': limit, 'menuCode': 'M001067', 'page': page,
                   'searchCondition': s2.get('data', ''), 'setting': 0,
                   'sign': s1.get('data', ''), 'sort': ''}
        return c0077_call(op, '/cebest-cms/cus/search', payload)

    probe = search(1, 50)
    limit = 50 if probe.get('numberOfElements', 0) > 6 else 6
    total_pages = probe.get('totalPages', 1)
    print(f'  C0077 api ok: limit={limit} totalPages={total_pages} '
          f'totalElements={probe.get("totalElements")}', flush=True)
    items = []
    stop = 'done'
    pages = 0
    errors = []
    for pno in range(1, min(total_pages, 25) + 1):
        try:
            res = search(pno, limit)
        except Exception as e:
            errors.append({'page': pno, 'error': str(e)[:120]})
            break
        pages += 1
        rows = res.get('content', [])
        if not rows:
            stop = 'no_new_items'
            break
        save(site / 'api', f'page_{pno:03d}.json',
             json.dumps(res, ensure_ascii=False, indent=2))
        oldest = ''
        for x in rows:
            date = (x.get('postTime') or '')[:10]
            if date and date < SINCE:
                oldest = min(filter(None, [oldest, date]))
            items.append({'title': hbc.strip_tags(x.get('title') or ''),
                          'url': f"{C0077_ENTRY}#details_{x.get('classId')}_{x.get('id')}",
                          'date': date, 'detail_url': x.get('note2') or ''})
        newest = max((x['date'] for x in rows if x['date']), default='')
        print(f'  C0077 p{pno}/{total_pages} rows={len(rows)} newest={newest}', flush=True)
        oldest_all = min((x['date'] for x in rows if x['date']), default='')
        if oldest_all and oldest_all < SINCE:
            stop = 'older_than_since'
            break
        time.sleep(DELAY)
    for i in items:
        hits = hbc.digital_hits(i['title'])
        i['candidate'] = int(bool(hits) and not any(x in i['title'] for x in hbc.FALSE_LIKE))
    # content1 bodies are in the saved api pages; write candidate bodies out
    saved = fail = 0
    cand_urls = {i['url'] for i in items if i['candidate']}
    for p in sorted((site / 'api').glob('page_*.json')):
        res = json.loads(p.read_text(encoding='utf-8'))
        for x in res.get('content', []):
            u = f"{C0077_ENTRY}#details_{x.get('classId')}_{x.get('id')}"
            if u in cand_urls and x.get('content1'):
                safe = f"details_{x.get('classId')}_{x.get('id')}"
                save(site / 'details', f'{safe}.html', x['content1'])
                saved += 1
    return write_site_out('C0077', '北京大学国际医院', 'P2', C0077_ENTRY,
                          items, pages, stop, errors, saved, fail)


def main():
    only = sys.argv[1:] or ['C0003', 'C0067', 'C0082']
    results = []
    if 'C0003' in only:
        results.append(fix_c0003())
    if 'C0067' in only:
        results.append(fix_c0067())
    if 'C0082' in only:
        results.append(fix_c0082())
    if 'C0077' in only:
        results.append(asyncio.run(fix_c0077()))
    (ROOT / 'outputs/hospital-site-crawl-90-20261028/render-fix-summary.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
