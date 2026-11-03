"""Versioned medical tender rules, bounded collection and durable failure ledger.

Uses the repository's existing Fetcher (DNS/robots/TLS/redirect/size controls).
API hints are deliberately data, never executable undocumented API requests.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from .config import validate_seed_url
from .fetch import Fetcher, is_allowed_url, normalize_url

DEFAULT_RULES = Path(__file__).resolve().parents[2] / 'configs' / 'medical_digital_tender_rules.json'
MODES = {'public_html', 'authorized_api', 'licensed_export', 'manual', 'directory'}
RESULT_WORDS = re.compile(r'中标|成交|中选|候选人|采购|招标|遴选|比选|签约|合同|喜报')
BAD_LINK = re.compile(r'登录|注册|投诉|法规|政策|帮助|操作手册|采购目录|法律|指南|招聘')
DATE = re.compile(r'(?<!\d)(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def load_rules(path=DEFAULT_RULES):
    rules = read_json(path)
    if rules.get('schema_version') != 1 or not rules.get('sources'):
        raise ValueError('rules require schema_version=1 and nonempty sources')
    seen = set()
    for s in rules['sources']:
        sid = s.get('id', '')
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,79}', sid) or sid in seen:
            raise ValueError('invalid or duplicate source id: ' + sid)
        seen.add(sid)
        if s.get('access_mode') not in MODES or s.get('profile') not in rules['profiles']:
            raise ValueError('unknown access mode/profile: ' + sid)
        domains = s.get('allowed_domains', [])
        if s['access_mode'] == 'public_html' and not s.get('seeds'):
            raise ValueError('public source requires explicit seeds: ' + sid)
        for url in s.get('seeds', []):
            validate_seed_url(url, domains)
        if any(ref not in rules['references'] for ref in s.get('reference_ids', [])):
            raise ValueError('unknown evidence reference: ' + sid)
        profile = rules['profiles'][s['profile']]
        # Validate selectors before a network run, so a typo cannot erase a ledger.
        for key in ('list_selectors', 'body_selectors', 'next_selectors', 'title_selectors', 'date_selectors'):
            for selector in profile.get(key, []):
                BeautifulSoup('', 'html.parser').select(selector)
    return rules


def select_sources(rules, source_ids):
    wanted = set(source_ids or [])
    unknown = wanted - {s['id'] for s in rules['sources']}
    if unknown:
        raise ValueError('unknown sources: ' + ', '.join(sorted(unknown)))
    return [s for s in rules['sources'] if not wanted or s['id'] in wanted]


def plan(rules, sources):
    return {'schema_version': 1, 'status': 'planned', 'network_requests': 0,
            'generated_at': now(), 'rules_version': rules['rules_version'],
            'sources': [{**s, 'next_action': ('bounded_probe' if s['access_mode'] == 'public_html'
                        else 'supply_authorized_export' if s['access_mode'] in {'licensed_export', 'authorized_api'}
                        else 'verify_directory_or_identity')} for s in sources]}


def decode_html(raw):
    """Avoid requests' ISO-8859-1 default and BeautifulSoup's GBK mis-detection."""
    head = raw[:4096].decode('ascii', errors='ignore')
    declared = re.search(r'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', head, re.I)
    encodings = ([declared.group(1)] if declared else []) + ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        if encoding.lower() in {'gbk', 'gb2312'}:
            encoding = 'gb18030'
        try:
            return raw.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def first_content(soup, selectors):
    for selector in selectors:
        nodes = soup.select(selector)
        nodes = [n for n in nodes if len(n.get_text(' ', strip=True)) >= 30]
        if nodes:
            return max(nodes, key=lambda n: len(n.get_text(' ', strip=True))), selector
    return None, ''


def date_value(value):
    m = DATE.search(value)
    if m:
        try:
            return datetime(*map(int, m.groups())).date().isoformat()
        except ValueError:
            pass
    return ''


def stage_of(title):
    # A candidate, correction or cancellation must never become a final award.
    for label, terms in [('cancellation', ['废标', '流标', '终止']),
                         ('correction', ['更正', '变更', '澄清']),
                         ('candidate', ['候选人', '评标结果']),
                         ('contract', ['合同']),
                         ('award', ['中标', '成交', '中选']),
                         ('intention', ['采购意向']),
                         ('tender', ['招标', '采购公告', '采购邀请函', '比选', '询价'])]:
        if any(t in title for t in terms):
            return label
    return 'source_claim' if any(t in title for t in ['签约', '喜报']) else 'unknown'


def labeled_fields(soup):
    """Keep repeated table labels; never flatten different lots or suppliers."""
    fields = {}
    for tr in soup.select('tr'):
        cells = tr.find_all(['td', 'th'], recursive=False)
        if len(cells) % 2 == 0:
            for n in range(0, len(cells), 2):
                label = cells[n].get_text(' ', strip=True).rstrip(':：')
                value = cells[n + 1].get_text(' ', strip=True)
                if label and value and len(label) < 50:
                    fields.setdefault(label, []).append(value)
    return fields


def amount_mentions(text):
    # Preserve unit, role, local context. Do not add amounts or select a total.
    amounts = []
    pattern = r'(?<![\d.])([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(亿元|万元|元)(?![/／])'
    for m in re.finditer(pattern, text):
        context = text[max(0, m.start()-55):min(len(text), m.end()+35)]
        role = 'unknown'
        prefix = text[max(0, m.start()-45):m.start()]
        labels = list(re.finditer(r'预算|最高限价|中标|成交|合同|代理服务费|代理费(?:总金额)?|服务费|单价|总价|报价', prefix))
        if labels:
            word = labels[-1].group()
            role = 'fee' if word.startswith('代理费') else {'预算':'budget', '最高限价':'ceiling', '中标':'award', '成交':'award',
                    '合同':'contract', '代理服务费':'fee', '服务费':'fee',
                    '单价':'unit_price', '总价':'total', '报价':'quote'}[word]
        try:
            value = Decimal(m.group(1).replace(',', '')) * {'元':1, '万元':10000, '亿元':100000000}[m.group(2)]
        except InvalidOperation:
            continue
        amounts.append({'raw':m.group(), 'cny':format(value, 'f'), 'role':role, 'context':context,
                        'start':m.start(), 'end':m.end(), 'requires_review': True})
    return amounts


def parse_html(raw, url, source, rules):
    soup = BeautifulSoup(decode_html(raw), 'html.parser')
    profile = rules['profiles'][source['profile']]
    title_node = None
    for selector in profile.get('title_selectors', ['.detail-title', '.ewb-art-hd']):
        title_node = soup.select_one(selector)
        if title_node is not None:
            break
    title_node = title_node if title_node is not None else soup.find('h1') or soup.find('title')
    title = title_node.get_text(' ', strip=True) if title_node else ''
    whole = soup.get_text(' ', strip=True)
    challenge = re.search(r'安全验证|人机验证|访问验证|访问过于频繁|验证码|verify you are human|access denied|just a moment',
                          title, re.I)
    if challenge or (len(whole) < 600 and re.search(r'人机验证|安全验证|访问过于频繁', whole)):
        return {'status':'challenge', 'title':title, 'detail':None, 'links':[], 'directory_links':[]}
    if soup.select('input[type=password]') and len(whole) < 1800:
        return {'status':'login_required', 'title':title, 'detail':None, 'links':[], 'directory_links':[]}
    links, directory_links, seen = [], [], set()
    for a in soup.select('a[href], option[value]'):
        href = a.get('href') if a.name == 'a' else a.get('value')
        target = normalize_url(urljoin(url, href or ''))
        text = a.get_text(' ', strip=True)
        if target and not is_allowed_url(target, source['allowed_domains']):
            directory_links.append({'url':target, 'text':text, 'verification':'candidate_only'})
    selected = []
    for selector in profile.get('list_selectors', []):
        selected.extend(soup.select(selector))
    for a in selected:
        target = normalize_url(urljoin(url, a.get('href', '')))
        text = a.get_text(' ', strip=True)
        # A short channel label is not a detail record; menus never become awards.
        if (not target or target == normalize_url(url) or target in seen
                or not is_allowed_url(target, source['allowed_domains']) or BAD_LINK.search(text)):
            continue
        vendor_news = source['source_kind'] == 'vendor' and re.search(r'医疗|医院|智慧|基层|健康|AI',text)
        if len(text) >= 10 and (RESULT_WORDS.search(text) or vendor_news):
            seen.add(target)
            links.append({'url':target, 'title':text, 'kind':'detail'})
    for selector in profile.get('next_selectors', []):
        for a in soup.select(selector):
            if not re.search(r'下一页|下页|Next|›|»', a.get_text(' ', strip=True), re.I):
                continue
            target = normalize_url(urljoin(url, a.get('href', '')))
            if target and target not in seen and is_allowed_url(target, source['allowed_domains']):
                seen.add(target)
                links.append({'url':target, 'title':a.get_text(' ', strip=True), 'kind':'list'})
    body, selector = first_content(soup, profile.get('body_selectors', []))
    detail = None
    if body is not None and len(title) >= 10 and (RESULT_WORDS.search(title) or source['source_kind'] == 'vendor'):
        text = body.get_text('\n', strip=True)
        fields = labeled_fields(soup)
        published = Fetcher._date(soup)
        if not published:
            for date_selector in profile.get('date_selectors',[]):
                node = soup.select_one(date_selector)
                published = date_value(node.get_text(' ',strip=True)) if node else ''
                if published:
                    break
        if not published:
            for key in ['公告时间', '公告日期', '发布时间', '发布日期']:
                if key in fields:
                    published = date_value(fields[key][0])
                    if published:
                        break
        health = [w for w in rules['keywords']['health'] if w.lower() in (title + text).lower()]
        digital = [w for w in rules['keywords']['digital'] if re.search(
            r'(?<![a-zA-Z])' + re.escape(w) + r'(?![a-zA-Z])' if w.isascii() else re.escape(w),
            title + text, re.I)]
        amounts = amount_mentions(text)
        for label, values in fields.items():
            if re.search(r'金额|限价|单价|报价',label):
                for value in values:
                    for mention in amount_mentions(label + '：' + value):
                        amounts.append({**mention,'source':'summary_table','label':label})
        detail = {'record_id': hashlib.sha256((source['id'] + '\n' + normalize_url(url)).encode()).hexdigest()[:24],
                  'source_id':source['id'], 'source_kind':source['source_kind'], 'url':url, 'title':title,
                  'published_at':published, 'event_date':'',
                  'stage':'source_claim' if source['source_kind']=='vendor' else stage_of(title),
                  'claimed_stage':stage_of(title) if source['source_kind']=='vendor' else None,
                  'stage_review_required':bool(re.search(r'预中标|公示期满|如无异议',text)),
                  'content_scope':profile.get('content_scope','article_text'),
                  'labeled_fields':fields, 'amount_mentions':amounts,
                  'amount_cny':None, 'suppliers':[], 'lots':[], 'project_id':None,
                  'health_terms':health, 'digital_terms':digital,
                  'medical_digital_candidate':bool(health and digital),
                  'review_status':'source_claim' if source['source_kind'] == 'vendor' else 'pending',
                  'body_selector':selector, 'text':text,
                  'attachments':[{'url':normalize_url(urljoin(url,a['href'])), 'title':a.get_text(' ',strip=True)}
                                 for a in body.select('a[href]') if re.search(r'\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)',a['href'],re.I)]}
    shell = Fetcher._is_js_shell(raw, whole) or (not title and any(
        marker in decode_html(raw) for marker in profile.get('dynamic_markers',[])))
    return {'status':'detail_parsed' if detail else 'dynamic_shell' if shell else 'listing' if links else 'fetched_only',
            'title':title, 'detail':detail, 'links':links[:500], 'directory_links':directory_links[:1000]}


def failure_code(result):
    status, error = result.get('status',''), result.get('error','')
    http = result.get('http_status')
    if status.startswith('robots_'):
        return status
    if http in {401,403,429}:
        return {401:'authentication_required',403:'http_forbidden',429:'rate_limited'}[http]
    if 'TLS' in error:
        return 'tls_error'
    if 'DNS' in error:
        return 'dns_error'
    if 'timed out' in error.lower() or 'timeout' in error.lower():
        return 'timeout'
    if 'outside' in error or 'non-public' in error:
        return 'domain_scope_denied'
    if http == 404:
        return 'http_not_found'
    if 'OCR' in error:
        return 'ocr_required'
    if 'JavaScript' in error:
        return 'dynamic_shell'
    if status == 'blocked':
        return 'access_challenge'
    if http and 400 <= http <= 599:
        return 'http_' + str(http)
    return status or 'request_error'


def collect(rules, sources, output, *, allow_network=False, max_pages=2, max_depth=1,
            timeout=15, delay=2, fetcher_factory=Fetcher):
    if not allow_network:
        raise ValueError('network requires --allow-network')
    if not 1 <= max_pages <= 100 or not 0 <= max_depth <= 3 or not 0 < timeout <= 120 or delay < 1:
        raise ValueError('budget: pages 1..100, depth 0..3, timeout (0,120], delay >=1')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be empty; use a new run id')
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'rules.snapshot.json', rules)
    write_json(output / 'scope.json',{'allow_network':True,'rules_version':rules['rules_version'],
               'sources':[{'source_id':s['id'],'access_mode':s['access_mode'],'seeds':s.get('seeds',[])} for s in sources],
               'budget':{'max_pages_per_source':max_pages,'max_depth':max_depth,'timeout':timeout,'delay':delay},
               'started_at':now()})
    pages, failures, records, pending = [], [], [], []
    def checkpoint():
        write_json(output / 'pages.json', pages)
        write_json(output / 'failures.json', failures)
        write_json(output / 'records.json', records)
        write_json(output / 'pending.json', pending)
    try:
        for source in sources:
            sid = source['id']
            print('验证来源: ' + sid, file=sys.stderr, flush=True)
            if source['access_mode'] != 'public_html':
                failures.append({'source_id':sid, 'url':source.get('homepage'), 'stage':'preflight',
                                 'attempted':False, 'code':source.get('blocker_code','authorization_required'),
                                 'reason':source['limitations'], 'next_action':source.get('next_action','核验入口/提供授权导出'),
                                 'observed_at':now()})
                checkpoint()
                continue
            fetcher = fetcher_factory(timeout=timeout, retries=0, delay=delay, browser=False, max_bytes=4*1024*1024,
                                      transport=source.get('transport','requests'))
            queue = deque((url,0,'seed') for url in source['seeds'])
            seen, attempted = set(), 0
            stop_reason = 'page_budget'
            try:
                while queue and attempted < max_pages:
                    url, depth, kind = queue.popleft()
                    if url in seen:
                        continue
                    seen.add(url)
                    attempted += 1
                    fetched_at = now()
                    result = fetcher.fetch(url, source['allowed_domains'])
                    raw = result.pop('raw', b'')
                    row = {k:v for k,v in result.items() if k not in {'text','links'}}
                    row.update(source_id=sid, fetched_at=fetched_at, depth=depth, request_kind=kind)
                    if raw:
                        folder = output / 'archive' / sid
                        folder.mkdir(parents=True,exist_ok=True)
                        stem = hashlib.sha256(url.encode()).hexdigest()[:20]
                        suffix = '.pdf' if raw.lstrip().startswith(b'%PDF') else '.html'
                        raw_path = folder / (stem + suffix)
                        raw_path.write_bytes(raw)
                        row['raw_path'] = raw_path.relative_to(output).as_posix()
                        row['sha256'] = hashlib.sha256(raw).hexdigest()
                    parsed = None
                    if raw and result.get('content_type') in {'text/html','application/xhtml+xml','', 'text/plain'} and result.get('status') in {'ok','empty'}:
                        parsed = parse_html(raw,result['url'],source,rules)
                        row['rule_status'] = parsed['status']
                        row['title'] = parsed['title']
                        row['directory_links'] = parsed['directory_links']
                        row['discovered_links'] = parsed['links']
                        if parsed['detail']:
                            rec = parsed['detail']
                            rec.update(fetched_at=fetched_at, raw_path=row['raw_path'], sha256=row['sha256'])
                            records.append(rec)
                            (folder / (stem + '.txt')).write_text(rec['text'],encoding='utf-8')
                        if depth < max_depth:
                            # Test a real detail before spending the budget on other seeds.
                            for a in reversed(parsed['links']):
                                if a['url'] not in seen:
                                    queue.appendleft((a['url'],depth+1,a['kind']))
                    if result['status'] != 'ok' or (parsed and parsed['status'] in {'challenge','login_required','dynamic_shell','fetched_only'}):
                        code = (parsed['status'] if parsed and parsed['status'] in {'challenge','login_required','dynamic_shell','fetched_only'}
                                else failure_code(result))
                        if code == 'fetched_only':
                            code = 'discovery_no_links'
                        failures.append({'source_id':sid, 'url':url, 'final_url':result.get('url'),
                                         'stage':'parse' if parsed else 'fetch','attempted':True,'code':code,
                                         'http_status':result.get('http_status'), 'raw_path':row.get('raw_path'),
                                         'reason':result.get('error') or '当前规则未取得公告正文/详情链接；首页可达不等于采集成功',
                                         'next_action':rules['failure_actions'].get(code,'核对响应原文和官方入口后，在新目录复测'),
                                         'observed_at':fetched_at})
                    pages.append(row)
                    checkpoint()
                    if failures and failures[-1].get('source_id')==sid and failures[-1].get('url')==url and failures[-1]['code'] in {
                            'robots_denied','robots_unavailable','http_forbidden','rate_limited','challenge','login_required',
                            'authentication_required','access_challenge','domain_scope_denied'}:
                        stop_reason = 'source_stopped:' + failures[-1]['code']
                        break
                pending.extend({'source_id':sid,'url':u,'depth':d,'kind':k,'reason':stop_reason}
                               for u,d,k in queue if u not in seen)
            finally:
                fetcher.close()
            checkpoint()
    except BaseException as exc:
        failures.append({'stage':'run','attempted':False,'code':'interrupted' if isinstance(exc,KeyboardInterrupt) else 'internal_error',
                         'reason':str(exc),'observed_at':now()})
        checkpoint()
        raise
    status = 'partial' if failures or pending else 'completed'
    summary = {'schema_version':1,'status':status,'finished_at':now(),'rules_version':rules['rules_version'],
               'source_count':len(sources),'attempted_pages':len(pages),'detail_records':len(records),
               'medical_digital_candidates':sum(r['medical_digital_candidate'] for r in records),
               'failure_count':len(failures),'unattempted_sources':sum(not f['attempted'] for f in failures),
               'pending_pages':len(pending),'failure_codes':dict(Counter(f['code'] for f in failures)),
               'note':'有限规则验证；不代表全量覆盖。详情记录/候选线索均不等于已核验中标项目。'}
    checkpoint()
    write_json(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','collect','parse','export-config'])
    parser.add_argument('--rules',type=Path,default=DEFAULT_RULES)
    parser.add_argument('--source',action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--input-file',type=Path)
    parser.add_argument('--url')
    parser.add_argument('--seed-url',action='append',default=[])
    parser.add_argument('--allow-network',action='store_true')
    parser.add_argument('--max-pages',type=int,default=2)
    parser.add_argument('--max-depth',type=int,default=1)
    parser.add_argument('--timeout',type=float,default=15)
    parser.add_argument('--delay',type=float,default=2)
    args = parser.parse_args(argv)
    try:
        rules = load_rules(args.rules)
        sources = select_sources(rules,args.source)
        if args.seed_url:
            if args.command != 'collect' or len(sources) != 1 or sources[0]['access_mode'] != 'public_html':
                raise ValueError('--seed-url requires collect and one public --source')
            for url in args.seed_url:
                validate_seed_url(url,sources[0]['allowed_domains'])
            sources = [{**sources[0], 'seeds':list(dict.fromkeys(args.seed_url))}]
        if args.command == 'collect':
            if not args.source:
                raise ValueError('collect requires explicit --source; no implicit all-site crawl')
            result = collect(rules,sources,args.output,allow_network=args.allow_network,
                             max_pages=args.max_pages,max_depth=args.max_depth,timeout=args.timeout,delay=args.delay)
        else:
            if args.output.exists():
                raise ValueError('output already exists; preserve previous results')
            if args.command == 'parse':
                if len(sources) != 1 or not args.input_file or not args.url:
                    raise ValueError('parse requires one --source, --input-file and --url')
                if not is_allowed_url(args.url,sources[0]['allowed_domains']):
                    raise ValueError('parse URL outside source domains')
                result = parse_html(args.input_file.read_bytes(),args.url,sources[0],rules)
            elif args.command == 'export-config':
                public = [s for s in sources if s['access_mode'] == 'public_html']
                if not public:
                    raise ValueError('no public sources to export')
                result = {'version':1,'topic':'医疗数字化中标情报：有限公开网页采集',
                          'sources':[{k:s[k] for k in ['id','name','allowed_domains','seeds']} for s in public]}
            else:
                result = plan(rules,sources)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            write_json(args.output,result)
        print(json.dumps({'status':result.get('status','completed'),'output':str(args.output),
                          **(result if args.command == 'collect' else {})},ensure_ascii=False))
        return 3 if result.get('status') == 'partial' else 0
    except (ValueError,OSError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
