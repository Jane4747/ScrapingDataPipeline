# -*- coding: utf-8 -*-
"""Conservative, offline extraction of public hospital procurement notices."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
import html
import json
import csv
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

COLUMNS = ['时间','项目名称','产品','招标单位','客户标签','中标单位','运营商类型','中标金额（万元）','场景','评审专家','网址','公告类型','省份','项目编号','中标金额原文','信息缺口','标签依据','响应人资格要求（对供应商基本要求）','资格预审资质要求','医院名称','医院ID','日期依据','采购人依据','采集来源','抓取时间','公告ID','原文SHA256','原文路径','数字化标签','入口任务ID']
DATE_RE = r'(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?:\s*日)?'
NOTICE = r'招标|采购|比选|比价|遴选|询价|议价|磋商|竞争性谈判|中标|中选|成交|资格预审|单一来源|征集|市场调研|采购论证'
DIGITAL = ('信息化','信息系统','软件','服务器','数据库','数据中心','数据空间','数据平台','电子病历','HIS','PACS','LIS','CDSS','智慧医院','智慧医疗','互联网医院','机房','等保','密码应用','人工智能','大模型','算力','物联网','通信','通讯','网络安全','网络设备','网络运维','网络维护','无线网络','网络改造','网络建设','局域网','交换机','防火墙','存储设备','光纤','宽带','数据专线','视频会议','计算机','打印机','扫码','电子签名','数字签名','信息平台','远程报警','视频监控','对讲系统','呼叫系统','门禁','电子叫号','智能排队','显示屏','办公自动化')
DIGITAL += ('官网改版','官网建设','官网运维','网站建设','网站群','门户网站','国产化适配','PDA','终端设备','排队叫号','叫号系统','投票系统','动环系统','网络信息','互联网诊疗','OA','自助入出院','政务专线','信息管理系统')
IT_ROOM=r'信息中心|计算机|服务器|交换机|数据中心|精密空调|汇聚机房|配线间|数据机房|信息机房|网络机房|网络设备'
QUAL_LABELS=[r'申请人(?:的)?资格要求',r'投标人(?:的)?(?:基本)?(?:资格要求|资格条件|资质要求)',r'供应商(?:的)?(?:基本)?(?:资格要求|资格条件|资质要求)',r'响应人(?:的)?(?:基本)?(?:资格要求|资格条件|资质要求)',r'供应商基本要求',r'合格(?:投标人|供应商)(?:应具备的)?(?:条件|资格|要求)',r'参选人(?:的)?资格(?:要求|条件)?',r'参与(?:比选|遴选|采购)(?:的)?(?:资格|条件)']
PREQUAL_LABELS=[r'资格预审(?:资质|资格|条件)?要求',r'资格预审申请人(?:的)?资格要求',r'资格预审(?:的)?资格条件']


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def normalize(value):
    return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()


def term_hit(term, text):
    pattern=re.escape(term)
    if re.fullmatch(r'[A-Za-z]+',term):pattern=r'(?<![A-Za-z])'+pattern+r'(?![A-Za-z])'
    if term=='通信':pattern=r'(?<!交)通信'
    return bool(re.search(pattern,text,re.I))


def date_value(value):
    m = re.search(DATE_RE, str(value or ''))
    if m:
        try:
            return date(*(int(x) for x in m.groups())).isoformat()
        except ValueError:
            return ''
    return ''


def decode(raw):
    for enc in ('utf-8-sig','gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode('utf-8', errors='replace')


def document_text(raw):
    source = decode(raw)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(source, 'html.parser')
        headings = [normalize(t.get_text(' ', strip=True)) for t in soup.select('h1,h2,.article-head .t,.article-title')]+[normalize(t.get_text(' ',strip=True)) for t in soup.select('title')]
        for el in soup.select('script,style,nav,header,footer,noscript'):
            el.decompose()
        # Convert aligned result tables to labelled rows, retaining label units.
        for table in soup.select('table'):
            headers=None
            for tr in [r for r in table.find_all('tr') if r.find_parent('table') is table]:
                cells=tr.find_all(['td','th'],recursive=False)
                vals=[normalize(c.get_text(' ',strip=True)) for c in cells]
                dense=[re.sub(r'\s+','',v) for v in vals]
                formal=r'(?:中标|成交|中选)(?:[（(/](?:中标|成交)[）)]?)?(?:单位|供应商|公司|人|金额|报价|价格)(?:名称)?[）)]?(?:[（(].*[）)])?|供应商名称|服务商名称|主要标的名称'
                header_hits=sum(bool(re.fullmatch(formal,v)) for v in dense)
                header_row=bool(header_hits) and all(re.fullmatch(formal+r'|(?:序号|科室|包号|标包|标项名称|标项|采购编号|遴选编号|项目编号|采购数量|项目名称|名称|服务名称|货物名称|产品名称|中标供应商地址|供应商地址|供应商编码|社会信用代码|统一社会信用代码|评审总得分|综合得分|得分|中标金额/评审价|备注|采购内容|品牌|规格型号|数量|单价|总价|单位)(?:[（(].*[）)])?',v) for v in dense)
                if headers and len(headers)==len(vals):
                    tr.replace_with(soup.new_string('\n'+'\n'.join(h+'：'+v for h,v in zip(headers,vals) if h and v)+'\n'))
                elif len(vals)>=2 and header_row:
                    headers=dense
                    tr.replace_with(soup.new_string('\n'))
        # Retain two-column table adjacency as explicit key/value pairs.
        for tr in soup.select('tr'):
            cells=tr.find_all(['td','th'],recursive=False)
            if len(cells)==2:
                vals=[normalize(c.get_text(' ',strip=True)) for c in cells]
                if vals[0] and vals[1] and len(vals[0])<40:
                    tr.replace_with(soup.new_string('\n'+vals[0].rstrip(':：')+'：'+vals[1]+'\n'))
        # Inline spans split many hospital pages into individual words; retain paragraph flow.
        for paragraph in soup.select('p,li'):
            if not paragraph.find(['table','p','li']):
                paragraph.replace_with(soup.new_string('\n'+normalize(paragraph.get_text(' ',strip=True))+'\n'))
        whole = soup.get_text('\n', strip=True)
        candidates = soup.select('article,.v_news_content,.TRS_Editor,#zoom,.article-content,.article-cont,.article_cont,.detail-content,.news_content,.news-content,.article_content')
        selected = max(candidates, key=lambda e: len(e.get_text()), default=None)
        body = selected.get_text('\n',strip=True) if selected is not None and len(selected.get_text())>80 else whole
    except ImportError:
        headings = [normalize(re.sub('<[^>]+>',' ',v)) for v in re.findall(r'(?is)<(?:h1|h2|title)[^>]*>(.*?)</(?:h1|h2|title)>', source)]
        clean = re.sub(r'(?is)<(script|style|nav|footer)[^>]*>.*?</\1>', ' ', source)
        clean = re.sub(r'(?is)</(?:p|div|tr|li|h\d)>|<br[^>]*>', '\n',clean)
        whole = html.unescape(re.sub(r'<[^>]+>',' ',clean))
        body = whole
    body=re.split(r'(?:\n|^)\s*(?:上一篇|下一篇|相关阅读|相关文章|您可能需要|本栏精选)\s*[:：]?',body)[0]
    return source, '\n'.join(normalize(x) for x in body.splitlines() if normalize(x)), whole, headings


def publication_date(page, raw, text):
    if page.get('date_conflicts') or page.get('date_basis')=='date_conflict':
        return '', '日期冲突待复核：'+json.dumps(page.get('date_conflicts',[]),ensure_ascii=False)
    values = []
    for tag in re.findall(r'(?is)<meta\b[^>]*>',raw):
        attrs = dict((m[0].lower(), html.unescape(m[2])) for m in re.findall(r'([\w:-]+)\s*=\s*([\"\'])(.*?)\2',tag,re.S))
        if attrs.get('name',attrs.get('property','')).lower() in {'pubdate','publishdate','publishtime','publicationdate','datepublished','article:published_time'}:
            d = date_value(attrs.get('content'))
            if d: values.append((d,'网页发布日期元数据'))
    for m in re.finditer(r'"datePublished"\s*:\s*"([^"]+)"',raw):
        d=date_value(m.group(1))
        if d: values.append((d,'网页 datePublished'))
    for m in re.finditer(r'(?:发布(?:日期|时间)|发表(?:日期|时间)|发布时间)\s*[:：]?\s*'+DATE_RE,text):
        if re.search(r'(?:原公告|首次公告|前次公告|原招标公告|原采购公告|首次|原)\s*$',text[max(0,m.start()-16):m.start()]):continue
        try: values.append((date(*(int(x) for x in m.groups())).isoformat(),'正文明确发布日期'))
        except ValueError: pass
    # Listing dates are accepted only when the collector tied them to this exact row.
    if page.get('date_basis') in {'detail_publication','exact_listing_row'}:
        d=date_value(page.get('date'))
        if d: values.append((d, '正文明确发布日期' if page['date_basis']=='detail_publication' else '同条列表精确日期'))
    unique = sorted(set(d for d,_ in values))
    if len(unique)>1:
        return '', '日期冲突：'+'；'.join(unique)
    return values[0] if values else ('','未取得明确发布日期')


def label_value(text, labels, maximum=250):
    pat = '(?:'+'|'.join(labels)+r')(?:\s*[:：]\s*|[ \t]*\n\s*)([^\n]+)'
    for m in re.finditer(pat,text):
        value = re.split(r'\s+(?:地址|联系方式|供应商地址|采购代理机构|项目编号|名称)\s*[:：]',m.group(1))[0].strip()
        compact_value=re.sub(r'\s+','',value)
        if re.fullmatch(r'(?:[一二三四五六七八九十\d]+[、.．])?(?:采购内容|采购范围|采购需求|项目内容|项目需求|采购人信息|供应商资格|响应人全称|投标人全称|供应商全称|公司名称)(?:[（(].*[）)])?[:：]?',compact_value):continue
        if value in {'数量','单位','名称','项目名称','供应商名称','服务商名称','成交公司','中标公司','中标供应商名称','成交供应商名称','货物名称','服务名称','服务内容','服务岗位数量','最高预估金额','规格型号','规格','型号','品牌','单价','总价','金额','中选金额','中标金额','基本要求','采购需求概况'}:continue
        if re.fullmatch(r'(?:\d+[.、．]\s*)?(?:响应人全称|投标人全称|供应商全称|公司名称)(?:[（(].*[）)])?',value):continue
        if re.fullmatch(r'(?:项目)?(?:预算金额|中标金额|成交金额|中选金额|数量|单价|最高限价)(?:[（(].*[）)])?',value):continue
        if value and re.search(r'[\w\u4e00-\u9fff]',value) and len(value)<=maximum:
            return value
    return ''


def notice_type(title):
    rules=[('更正公告',r'更正|变更|澄清'),('终止或废标公告',r'终止|废标|流标|取消'),('资格预审公告',r'资格预审'),('采购论证结果公示',r'论证结果|论证公示'),('中标候选人公示',r'候选人|评标结果'),('中标或成交公告',r'中标|中选|成交|结果公告|结果公示'),('采购意向',r'采购意向'),('单一来源公示',r'单一来源'),('市场调研或征集',r'调研|征集|论证'),('采购公告',NOTICE)]
    return next((name for name,pat in rules if re.search(pat,title)),'采购相关公告')


_PROVINCE_NAMES = [
    '北京市','天津市','河北省','山西省','内蒙古自治区','辽宁省','吉林省','黑龙江省',
    '上海市','江苏省','浙江省','安徽省','福建省','江西省','山东省','河南省','湖北省',
    '湖南省','广东省','广西壮族自治区','海南省','重庆市','四川省','贵州省','云南省',
    '西藏自治区','陕西省','甘肃省','青海省','宁夏回族自治区','新疆维吾尔自治区',
]
PROVINCES = {name:name for name in _PROVINCE_NAMES}
PROVINCES.update({name.removesuffix('省').removesuffix('市').removesuffix('自治区').removesuffix('壮族').removesuffix('回族').removesuffix('维吾尔'):name
                  for name in _PROVINCE_NAMES})
PROVINCES.update({'内蒙古':'内蒙古自治区','广西':'广西壮族自治区','西藏':'西藏自治区',
                  '宁夏':'宁夏回族自治区','新疆':'新疆维吾尔自治区'})


def identity_key(value):
    """Whitespace/punctuation only; never discard a campus or branch qualifier."""
    return re.sub(r'\s+', '', normalize(value)).translate(str.maketrans({'(': '（', ')': '）'}))


def hospital_entities(page):
    entities = page.get('hospital_entities') or []
    if not entities:
        ids = [v for v in re.split(r'[；;]', str(page.get('hospital_ids', ''))) if v]
        name = normalize(page.get('hospital'))
        # The legacy single-institution shape remains readable; a combined entry is not a buyer.
        if name and len(ids) <= 1 and not re.search(r'[；;]', name):
            entities = [{'id': ids[0] if ids else '', 'name': name,
                         'province': page.get('province') or page.get('hospital_region', ''),
                         'aliases': page.get('hospital_aliases') or []}]
    return [dict(e, name=normalize(e.get('name'))) for e in entities
            if isinstance(e, dict) and normalize(e.get('name'))]


def dual_hospital_names(value):
    """Only explicit complete dual names, never a location, historical note or campus."""
    match = re.fullmatch(r'(.+?)[（(]([^）)]+)[）)]', normalize(value))
    if not match:
        return []
    left, right = (normalize(v) for v in match.groups())
    forbidden = r'院区|分院|分部|[东西南北]院|院部|门诊部|曾用|原名|旧称|原址|注销|登记|筹建'
    institutional = r'.{3,}(?:医院|保健院|防治院|卫生院|疗养院|护理院|医学中心|医疗中心)'
    if re.search(forbidden, right) or not all(re.fullmatch(institutional, v) for v in (left, right)):
        return []
    return [left, right]


def buyer_aliases(entity):
    name = entity['name']
    aliases = entity.get('aliases') or []
    if isinstance(aliases, str):
        aliases = [aliases]
    variants = [name] + [normalize(a) for a in aliases if isinstance(a, str)] + dual_hospital_names(name)
    # A short group name cannot identify a named branch even if supplied as an alias.
    qualifiers = re.findall(r'[（(]([^）)]*(?:院区|分院|分部)[^）)]*)[）)]', name)
    tail_qualifier = re.search(r'医院([^（(）)]{1,15}(?:院区|分院|分部))$', name)
    if tail_qualifier:
        qualifiers.append(tail_qualifier.group(1))
    return [v for v in dict.fromkeys(variants) if len(identity_key(v)) >= 4
            and (v == name or not qualifiers or all(identity_key(q) in identity_key(v) for q in qualifiers))]


BUYER_ROLE = r'(?:采\s*购\s*人|招\s*标\s*人|采\s*购\s*单\s*位|招\s*标\s*单\s*位|比\s*选\s*人|征\s*集\s*人)'
BUYER_NUMBER = r'(?:[（(]?[一二三四五六七八九十\d]+(?:\.\d+)*\s*[）)、.．]\s*)?'


def clean_buyer(value):
    value = normalize(value)
    # Numbered or repeated field labels are layout, not part of an institution name.
    prefix = r'^\s*' + BUYER_NUMBER + r'(?:名\s*称|单\s*位\s*名\s*称|' + BUYER_ROLE + r'(?:名\s*称)?)\s*[:：]\s*'
    for _ in range(4):
        cleaned = re.sub(prefix, '', value)
        if cleaned == value:
            break
        value = cleaned
    if re.match(r'^\s*' + BUYER_NUMBER + r'(?:联\s*系\s*人|联\s*系\s*电\s*话|联\s*系\s*方\s*式|地\s*址)\s*[:：]', value):
        return ''
    value = re.split(r'\s*(?:[；;。]|(?:地\s*址|联系方式|联系人员?|联\s*系\s*人|联\s*系\s*电\s*话|采购代理机构|采购项目|项目名称|项目编号|邮编)\s*[:：])', value)[0]
    value = value.strip(' ：:、,，')
    if not 4 <= len(value) <= 180 or re.search(r'采购人信息|资格要求|详情|详见|采购需求|供应商资格', value):
        return ''
    if not re.search(r'医院|保健院|防治院|卫生院|卫生服务中心|卫生服务站|卫生健康[局委]|疾病预防控制中心|疾控中心|血站|血液中心|疗养院|护理院|医疗集团|健康集团|医疗中心|门诊部|诊所|公司|大学|研究院|研究所|医学院|健康委员会', value):
        return ''
    return value


def explicit_buyers(text):
    """Buyer role labels and their name subsections, not arbitrary hospital mentions."""
    found = []
    role = BUYER_ROLE + r'(?:[（(][^）)\n]{0,25}[）)])?(?:名\s*称)?'
    for match in re.finditer(r'(?:^|\n)\s*' + BUYER_NUMBER + role + r'\s*(?:[:：]\s*|[ \t]*\n\s*)([^\n]+)', text):
        value = clean_buyer(match.group(1))
        if value:
            found.append((value, '正文采购人标签：' + normalize(match.group(0))))
    for match in re.finditer(r'(?:采\s*购\s*人|招\s*标\s*人)(?:的)?(?:信息|联系方式)\s*[:：]?', text):
        tail = text[match.end():match.end() + 400]
        tail = re.split(r'采购代理机构|代理机构信息|项目联系方式', tail)[0]
        named = re.search(r'(?:^|\n)\s*' + BUYER_NUMBER + r'(?:单\s*位)?名\s*称\s*[:：]\s*([^\n]+)', tail)
        if named:
            value = clean_buyer(named.group(1))
            if value:
                found.append((value, '正文采购人信息段：' + normalize(named.group(0))))
    return list(dict.fromkeys(found))


def resolve_hospital_buyer(page, title, text):
    """Return an evidence-backed buyer plus only its matched roster records."""
    entities = hospital_entities(page)
    if not entities:
        return None, '入口缺少可核对的医院名录实体'
    entity_aliases = [(e, a) for e in entities for a in buyer_aliases(e)]

    def matches(value):
        target = identity_key(value)
        exact = [(e, a) for e, a in entity_aliases if identity_key(a) == target]
        if exact:
            return exact
        dual = {identity_key(v) for v in dual_hospital_names(value)}
        if dual:
            matched = [(e, a) for e, a in entity_aliases if identity_key(a) in dual]
            if matched:
                return matched
        # Procurement departments are internal roles; branches/campuses are never removed.
        suffix = r'(?:采购中心|招标采购中心|招标采购办公室|采购办公室|信息中心|信息科|信息部|设备科|设备处|采购科|采购办|招标办|总务科)'
        return [(e, a) for e, a in entity_aliases if re.fullmatch(re.escape(identity_key(a)) + suffix, target)]

    labelled = explicit_buyers(text)
    if labelled:
        hits = [(value, basis, matches(value)) for value, basis in labelled]
        # A budget-system “本级” suffix is reconciled only with an independently
        # explicit, same-name formal buyer in this very announcement.
        reconciled = []
        for value, basis, chosen in hits:
            target = identity_key(value)
            if not chosen and target.endswith('本级'):
                formal = [(v, b, selected) for v, b, selected in hits
                          if selected and identity_key(v) == target[:-2]]
                if formal:
                    chosen = formal[0][2]
                    basis += '；“本级”仅依据同文明确正式采购人消解：' + formal[0][0]
            reconciled.append((value, basis, chosen))
        hits = reconciled
        good = [(value, basis, chosen) for value, basis, chosen in hits if chosen]
        if not good:
            return None, '正文明确采购人不匹配入口医院：' + '；'.join(v for v, _ in labelled)
        # Complete, evidenced aliases can vary in text but must identify the same
        # set of original roster IDs. Unmatched roles and different entities remain conflicts.
        signatures = {frozenset(str(e.get('id')) if e.get('id') not in (None, '') else identity_key(e['name'])
                                for e, _ in chosen) for _, _, chosen in hits}
        if any(not chosen for _, _, chosen in hits) or len(signatures) > 1:
            return None, '正文存在多个采购人标签或采购人冲突，待核：' + '；'.join(v for v, _ in labelled)
        good.sort(key=lambda hit: (identity_key(hit[0]).endswith('本级'),
                                  not any(identity_key(hit[0]) == identity_key(e['name']) for e, _ in hit[2])))
        buyer, basis, selected = good[0]
        if len({identity_key(v) for v, _, _ in hits}) > 1:
            basis = '；'.join(dict.fromkeys(b for _, b, _ in hits)) + '；多处采购人标签均匹配同一组原名录实体ID'
    else:
        inferred = []
        for entity, alias in entity_aliases:
            escaped = re.escape(alias)
            patterns = [r'受\s*' + escaped + r'\s*(?:的)?委托',
                        escaped + r'\s*(?:现|拟|将|计划|决定)(?:对|就|开展|进行|公开|组织|通过|以)?[^。；\n]{0,55}(?:采购|招标|比选|询价|磋商)',
                        escaped + r'\s*(?:委托|委托方)[^。；\n]{0,55}(?:采购|招标|比选|询价|磋商)']
            quote = next((m.group(0) for p in patterns for m in [re.search(p, text)] if m), '')
            # An explicit institution-led procurement title is usable evidence, with its basis retained.
            title_match = re.match(r'^(?:[【\[].*?[】\]]\s*)?' + escaped + r'(?=[\s（(\d\u4e00-\u9fff])', title)
            if not quote and title_match and re.search(NOTICE, title[title_match.end():]) and not re.search(r'转载|转发|代发', title):
                # Reject base-name prefix matches to a different branch/campus.
                remainder = title[title_match.end():]
                if not re.match(r'(?:[（(][^）)]*(?:院区|分院)|[^，。；\n]{0,10}(?:分院|院区))', remainder):
                    quote = title
            if quote:
                inferred.append((entity, alias, normalize(quote)))
        aliases = {identity_key(alias) for _, alias, _ in inferred}
        if not inferred:
            own_domain = urlsplit(str(page.get('url', ''))).hostname
            listing_domain = urlsplit(str(page.get('listing_url') or page.get('entry_url') or '')).hostname
            same_domain = bool(own_domain and own_domain == listing_domain)
            self_subject = re.search(r'(?:我院|本院)(?:现|拟|将|计划|决定|就|对|组织|开展|需|需要)[^。；]{0,90}(?:采购|招标|比选|比价|询价|磋商|遴选)|(?:由我院|由本院)[^。；]{0,50}(?:组织|开展)[^。；]{0,30}(?:采购|招标|比选|比价|遴选)', text)
            unique_entities = {(str(v.get('id', '')), v['name']) for v in entities}
            if (len(unique_entities) == 1 and page.get('entrance_verified') is True
                    and page.get('status') == 'ok' and same_domain and self_subject
                    and not re.search(r'转载|转发|代发', title + '\n' + text[:600])):
                entity = entities[0]
                inferred = [(entity, entity['name'], normalize(self_subject.group(0)))]
                aliases = {identity_key(entity['name'])}
                self_basis = '已核验单院同域公告中的自称采购主体：' + normalize(self_subject.group(0)) + '；院站入口：' + str(page.get('listing_url') or page.get('entry_url'))
            else:
                return None, '未取得与名录医院匹配的明确采购人或采购主体语句；不以导航院名或入口归属代填'
        else:
            self_basis = ''
        if len(aliases) > 1:
            return None, '正文或标题存在多个医院采购主体，待逐标包核对'
        buyer = inferred[0][1]
        basis = self_basis or '医院采购主体原文：' + inferred[0][2]
        selected = [(e, a) for e, a, _ in inferred]
    selected_entities = []
    seen = set()
    for entity, alias in selected:
        key = (str(entity.get('id', '')), entity['name'])
        if key not in seen:
            selected_entities.append(entity)
            seen.add(key)
    mapped_names = [e['name'] for e in selected_entities if identity_key(e['name']) != identity_key(buyer)]
    if mapped_names:
        basis += '；名称对应原名录完整别名或双挂牌：' + '；'.join(mapped_names)
    provinces = {PROVINCES.get(normalize(e.get('province')), '') for e in selected_entities}
    provinces.discard('')
    if len(provinces) > 1:
        return None, '匹配的医院名录记录跨省冲突，待核'
    fallback_province = PROVINCES.get(normalize(page.get('province') or page.get('hospital_region')), '')
    province = next(iter(provinces), fallback_province)
    return {'buyer': buyer, 'basis': basis, 'entities': selected_entities, 'province': province,
            'hospital': '；'.join(dict.fromkeys(e['name'] for e in selected_entities)),
            'hospital_ids': '；'.join(dict.fromkeys(str(e.get('id', '')) for e in selected_entities if e.get('id') is not None))}, ''


def award_details(text, title):
    kind=notice_type(title)
    if kind!='中标或成交公告':
        return '',None,'',[]
    original_text=text
    # Restrict final supplier/price facts to the explicit result section when present.
    # Otherwise a later fee table or an appendix instruction can look like a supplier.
    start=re.search(r'(?:^|\n)\s*(?:[一二三四五六七八九十]+|\d{1,2})\s*[、.．]\s*(?:(?:中标|成交|中选)(?:[（(/](?:中标|成交)[）)]?)?\s*(?:信息|情况|结果)|采购结果)\s*[:：]?',text)
    if start:
        # Some short hospital results print the final price immediately before
        # the numbered result section. Only preserve a standalone final-price
        # field when the preceding text has no candidate/competing quote list.
        prior=text[:start.start()]
        prior_prices=[] if re.search(r'候选|投标供应商|评审价格|响应报价',prior) else re.findall(
            r'(?:^|\n)\s*(?:[一二三四五六七八九十\d]+[、.．]\s*)?(?:成交|中标|中选)(?:价格|金额)\s*[:：][^\n]+', prior)
        tail=text[start.end():]
        stop=re.search(r'\n\s*(?:[一二三四五六七八九十]+|\d{1,2})\s*[、.．]\s*(?:主要标的|评审|评标|代理|公告期限|其他|采购小组|项目联系|附件|凡对)',tail)
        text=tail[:stop.start()] if stop else tail
        text+='\n'+'\n'.join(prior_prices)
    winners=[]
    for m in re.finditer(r'(?:中\s*标|成\s*交|中\s*选|中标[（(]成交[）)])[ \t]*(?:供\s*应\s*商|单位|公司|人)[ \t]*(?:名\s*称)?(?:\s*[:：为]\s*|[ \t]*\n\s*)([^\n；;。]+)|(?:供\s*应\s*商|服\s*务\s*商)\s*名\s*称(?:\s*[:：]\s*|[ \t]*\n\s*)([^\n；;。]+)',text):
        name=normalize(m.group(1) or m.group(2)).lstrip(':：').strip()
        name=re.split(r'\s*(?:供应商地址|地址|中标金额|成交金额|统一社会信用代码)\s*[:：]',name)[0].strip()
        if name in {'供应商地址','中标供应商地址','供应商名称','中标金额','中选金额','成交金额','项目名称','采购数量','金额','单位','序号','服务名称','供应商','社会信用代码'}:continue
        if (3<len(name)<180 and re.search(r'公司|中心|研究院|研究所|事务所|商行|经营部|服务部|工作室|工厂|联合体|大学|医院',name)
                and not re.search(r'资格|应当|应公告|必须|不得|要求|提供|详见|见附件|声明函|公告期限|社会信用代码|供应商地址',name)):
            winners.append(name)
    amounts=[]; periodic=False
    # A tender quote is final only when explicitly nested in the award section.
    price_prefix = r'小写|报价|人民币|RMB' + (r'|投标报价' if start else '')
    pat=(r'(?:总\s*)?(?:中\s*标|成\s*交|中\s*选)(?:\s*[（(/]\s*(?:中\s*标|成\s*交)\s*[）)]?)?'
         r'\s*(?:总\s*)?(?:金\s*额|总\s*价|价\s*格|价|报\s*价)\s*[）)]?'
         r'\s*(?:[（(]\s*(?:人民币)?\s*(?P<before>万元|亿元|元)\s*[）)])?\s*[:：为]?\s*'
         r'(?:大写\s*[:：]\s*[零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整正\s]+[；;，,]\s*)?'
         r'(?:(?:' + price_prefix + r')\s*[:：]?\s*)*[¥￥]?\s*(?P<number>[\d,，]+(?:\s*\.\s*\d+)?)\s*'
         r'(?:[（(]\s*)?(?P<after>万元|亿元|元)?[ \t]*[）)]?'
         r'(?P<period>[ \t]*(?:[/／][ \t]*年|每年))?')
    for m in re.finditer(pat,text):
        if re.search(r'预算|限价|控制价',text[max(0,m.start()-12):m.start()]): continue
        unit=m.group('after') or m.group('before')
        if not unit:continue
        # An unaligned table header must not consume the next row's serial number.
        if '\n' in text[m.start():m.start('number')] and not m.group('after'):continue
        try: val=Decimal(re.sub(r'[\s,，]','',m.group('number')))*{'元':Decimal('0.0001'),'万元':Decimal('1'),'亿元':Decimal('10000')}[unit]
        except InvalidOperation: continue
        if val<0: continue
        periodic=periodic or bool(m.group('period'))
        amounts.append((float(val),m.group(0)))
        line_end=text.find('\n',m.start());line=text[m.start():line_end if line_end>=0 else len(text)]
        line_amounts=[]
        for lm in re.finditer(r'([\d,，]+(?:\.\d+)?)\s*(亿元|万元|元)',line):
            if re.search(r'预算|限价|控制价',line[max(0,lm.start()-10):lm.start()]):continue
            lv=Decimal(lm.group(1).replace(',','').replace('，',''))*{'元':Decimal('0.0001'),'万元':Decimal('1'),'亿元':Decimal('10000')}[lm.group(2)]
            line_amounts.append(float(lv))
        if len(set(line_amounts))>1:amounts.extend((lv,line) for lv in line_amounts)
    unique=sorted(set(v for v,_ in amounts))
    notes=[]
    # Several lots / suppliers require lot-level allocation, not an automatic sum.
    multi = len(set(winners))>1 or len(unique)>1 or bool(re.search(r'(?:包号|标包|分包)\s*[:：]?\s*(?:0?2|二|2)|第[二三四五六七八九十]包',original_text))
    amount=unique[0] if len(unique)==1 and not multi and not periodic else None
    if multi and amounts: notes.append('存在多供应商、分包或年度/合同期等多金额口径，未填单一中标金额')
    if periodic:
        context=[normalize(line) for line in original_text.splitlines() if re.search(r'服务期限|服务期|服务时间|1\s*[+＋]\s*1\s*[+＋]\s*1',line)]
        notes.append('原文为按年报价，不能作为合同总额，金额数值留空'+('；服务期原文：'+'；'.join(context[:3]) if context else ''))
    return '；'.join(dict.fromkeys(winners)),amount,'；'.join(dict.fromkeys(q for _,q in amounts)),notes


def section(text, labels):
    starts = list(re.finditer(r'(?:^|\n)\s*(?:[（(]?[一二三四五六七八九十\d]+(?:\.\d+)*\s*[）)、.．]\s*)?'+'(?:'+'|'.join(labels)+')'+r'\s*[:：]?',text))
    if not starts: return ''
    segments=[]
    stop=r'(?:\n|^|(?<=[。；]))\s*(?:[一二三四五六七八九十]+[、.．]|[3-9][、.．]\s*)?\s*(?:论证文件|采购论证时间|获取(?:招标|采购|磋商|谈判|比选|遴选|资格预审)?文件|获取时间|(?:响应|应答)文件\s*(?:提交|递交|开启)|(?:比选|招标|采购)文件\s*(?:发售|递交|提交|获取|开启)|投标(?:文件)?(?:截止|提交|递交)|开标(?:时间|地点)|公告期限|其他补充事宜|凡对本次采购|联系方式|采购人信息|采购代理机构信息|采购需求|项目基本情况|评审办法|评标办法|资格预审方法|资格预审文件的获取)'
    for m in starts:
        tail=text[m.end():]
        end=re.search(stop,tail)
        segment=text[m.start():m.end()+(end.start() if end else len(tail))].strip()
        if len(segment)>len(m.group(0))+3 and segment not in segments: segments.append(segment)
    return '\n\n'.join(segments)


def procurement_sections(text):
    """Return only explicit subject-bearing sections, stopping before procedural clauses."""
    labels=r'采购需求|采购内容|采购范围|招标内容|遴选内容|比选内容|服务内容|项目内容|项目需求|主要标的(?:信息|名称)?|产品清单|采购清单|采购标的|拟采购的(?:服务|货物|标的)(?:说明)?|简要技术需求或服务要求'
    start=r'(?:^|\n)\s*(?:[（(]?[一二三四五六七八九十\d]+(?:\.\d+)*[）)、.．]\s*|\d+(?:\.\d+)+\s+)?('+labels+r')\s*[:：]?'
    stop=r'\n\s*(?:[一二三四五六七八九十]+[、.．]\s*|(?:\d+(?:\.\d+)*[、.．]\s*)?(?:申请人|参选人|响应人|投标人|合格供应商|供应商(?:资格|要求|须)|资格预审|报名|获取(?:文件|招标|采购|遴选)|采购人信息|代理机构|联系方式|评审办法|评分标准|合同条款|公告期限|其他补充|商务要求|售后服务))'
    result=[]
    for match in re.finditer(start,text):
        tail=text[match.end():];ending=re.search(stop,tail)
        content=tail[:ending.start()] if ending else tail
        if content.strip():result.append((match.group(1),content.strip()))
    return result


def digital_evidence(title, project, product, text, qualification, prequalification):
    """Exclude boilerplate websites and supplier qualification from subject matching."""
    subject=' '.join((title,project,product)).replace('工业和信息化部','')
    body=text
    # Shenzhen equipment notices inherit this programme name even when the actual
    # standalone lot is an MRI or ultrasound machine. The umbrella is not evidence
    # that the lot buys IT; retain any independently named software/platform scope.
    umbrella = r'医疗配套设备及信息化建设(?:项目)?'
    subject = re.sub(umbrella, '', subject)
    body = re.sub(umbrella, '', body)
    # Surgical laser fibres transmit treatment energy rather than network data.
    subject = re.sub(r'医用激光光纤', '医用激光耗材', subject)
    body = re.sub(r'医用激光光纤', '医用激光耗材', body)
    for block in (qualification,prequalification):
        for fragment in block.split('\n\n'):
            if fragment:body=body.replace(fragment,'')
    subject_sections=procurement_sections(body)
    terms=[w for w in DIGITAL if term_hit(w,subject)]
    # Explicit hospital IT subjects missing from the short literal vocabulary.
    named_it=re.findall(r'(?:智能[\u4e00-\u9fff]{0,14}(?:管理系统|平台)|智慧[\u4e00-\u9fff]{0,10}(?:管理系统|平台)|AI人机交互|终端安全管理|危急值管理系统|DRG管理系统|敏感数据专项|安防监控|监控系统|UPS蓄电池|网站维护)',subject,re.I)
    terms.extend(named_it)
    # This observed service lot buys the named information-management system.
    # Keep any separate CT-device mention outside the system name as clinical.
    clinical_subject = re.sub(r'(?:移动)?CT卒中急救信息管理系统', '信息管理系统', subject, flags=re.I)
    clinical=bool(re.search(r'计算机断层|X线电子计算机|断层扫描机|球管|乳腺.*X|(?<![A-Za-z])CT(?![A-Za-z])|磁共振|超声|X射线|呼吸机|试剂|内窥镜|腹腔镜|宫腔镜|数字成像系统',clinical_subject,re.I))
    if re.search(r'计算机断层|X线电子计算机|断层扫描机|球管',subject):terms=[w for w in terms if w!='计算机']
    physical_room=bool(re.search(r'冷冻机房|冷水机房|冷机房|电梯机房|放射(?:治疗)?机房|影像机房|辐射机房|热疗室|直线加速器机房|CT机房|热力站|蒸汽发生器',subject,re.I))
    if physical_room:terms=[w for w in terms if w!='机房']
    room_basis=next((normalize(line) for line in (subject+'\n'+'\n'.join(chunk for _,chunk in subject_sections)).splitlines() if re.search(IT_ROOM,line)), '')
    if not room_basis:terms=[w for w in terms if w!='机房']
    non_it=clinical or physical_room or bool(re.search(r'中央空调|空调系统|电梯|发电机|消防|保洁|物业|锅炉|燃气|污水|洗涤|灭菌|消杀|垃圾|绿化|装修|修缮|餐饮|食材|标本运送|物流服务|康复理疗|检验试剂|手术器械|内控风险评估|内控制度建设|科普项目|视频制作|宣传片|印刷品|医用耗材|医疗耗材|生化分析仪|血液成分|手术帽|活检针|太平间|停车场经营|机械式停车|安全评价|实验室检测工作',subject,re.I))
    if '网络' in subject and not re.search('网络招聘',subject):terms.append('网络')
    if terms:return ('混合采购范围需拆包；' if non_it else '')+'标题或项目/标的名称：'+'、'.join(dict.fromkeys(terms))+('；机房用途原文：'+room_basis if '机房' in terms else '')
    evidence=[]
    for label,chunk in subject_sections:
        for line in chunk.splitlines():
            # These are non-subject roles even when embedded in a procurement section.
            if re.search(r'工业和信息化部|政府采购促进|财库|依法|法律法规|就医指南|新闻动态|版权所有|技术支持|信用中国|http[s]?://|资格|资质|报名|联系方式|通讯地址|通信地址|通讯畅通|通信畅通|供应商名称|中标单位|成交单位|公司名称|廉洁|馈赠|赠送|不得接受|不得要求|领取人|截图',line):continue
            hits=[w for w in DIGITAL if term_hit(w,line) and (w!='机房' or room_basis)]
            if not hits:continue
            if re.search(r'如设备需|自带|内置|附带|配套软件|管理软件维护|软件功能|软件终身|数据库分析|设备软件升级|仪器软件|(?:链接|连接)(?:医院|现有|通用).*打印机',line):continue
            action=bool(re.search(r'采购|购买|购置|建设|开发|部署|升级|维护|运维|扩容|改造|对接|订阅|授权|许可|提供.{0,18}服务',line))
            item=bool(re.fullmatch(r'\s*(?:\d+[、.．]?\s*)?(?:服务器|交换机|防火墙|数据库|软件|存储设备|计算机|打印机|视频会议系统|门禁系统|对讲系统|PACS|HIS|LIS)(?:\s*[（(].*[）)])?(?:\s*\d+\s*(?:台|套|项))?\s*',line,re.I))
            if not action and not item:continue
            if non_it:
                explicit=bool(re.search(r'(?:采购|购买|购置|建设|开发|部署|对接|数据存储|影像数据).{0,24}(?:服务器|数据库|软件|信息系统|数据存储|影像数据|PACS|HIS|LIS)|(?:服务器|数据库|软件|信息系统|PACS|HIS|LIS).{0,16}(?:采购|购买|购置|建设|开发|部署|对接)',line,re.I))
                if not explicit:continue
            evidence.append(label+'：'+normalize(line))
    return ('混合采购范围需拆包；' if non_it else '')+'正文明确采购标的字段：'+'；'.join(dict.fromkeys(evidence)) if evidence else ''


def canonical_url(value):
    try:
        p=urlsplit(value)
        query=urlencode([(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_')])
        # Hash routes and #details_ID identify distinct API-backed notices.
        fragment=p.fragment
        if fragment.lower() in {'top','main','header','footer','backtotop'} or fragment.lower().startswith(('utm_','tracking=')):
            fragment=''
        return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,query,fragment))
    except ValueError:
        return value


def attachment_supplements(page, base, project, number, hospital):
    """Only supplement fields from locally saved attachments with positive project identity."""
    supplements=[];gaps=[]
    dense=lambda v:re.sub(r'[\s\W_]+','',v).lower()
    hospital_base=re.split(r'[（(]',hospital)[0]
    stem=re.split(r'医院动态|医院概况|\s+-\s*',project)[0]
    stem=re.sub(r'(?:招标|采购|比选|遴选|竞争性谈判|竞争性磋商|中标|成交|资格预审)(?:邀请)?(?:公告|文件|公示).*$', '',stem)
    stem=stem.replace(hospital,'').replace(hospital_base,'') if hospital_base else stem
    stem=re.sub(r'^\s*20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?','',stem)
    for attachment in page.get('attachments') or []:
        if not isinstance(attachment,dict):gaps.append('附件记录缺少结构信息，待核');continue
        url=attachment.get('url','')
        if attachment.get('status') not in {'ok','unsupported'}:
            gaps.append('附件尚无可用正文，资格/产品待附件补查：'+url);continue
        tp=Path(attachment['text_path']) if attachment.get('text_path') else None
        if tp and not tp.is_absolute():tp=base/tp
        content=tp.read_text(encoding='utf-8-sig',errors='replace').strip() if tp and tp.is_file() and attachment.get('status')=='ok' else ''
        method='已保存可解析文本'
        rp=Path(attachment['raw_path']) if attachment.get('raw_path') else None
        if rp and not rp.is_absolute():rp=base/rp
        if len(content)<60 and rp and rp.is_file() and zipfile.is_zipfile(rp):
            try:
                with zipfile.ZipFile(rp) as z:
                    info=z.getinfo('word/document.xml')
                    if info.file_size>20000000:raise ValueError('document.xml超过20MB')
                    doc=ET.fromstring(z.read(info))
                ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                paragraphs=[]
                for paragraph in doc.findall('.//w:p',ns):
                    value=''.join(n.text or '' for n in paragraph.findall('.//w:t',ns))
                    if value.strip():paragraphs.append(value.strip())
                content='\n'.join(paragraphs);method='DOCX内嵌document.xml按段落及表格顺序只读提取'
            except (KeyError,ValueError,ET.ParseError,zipfile.BadZipFile) as exc:
                gaps.append('附件ZIP非可解析DOCX或正文结构异常：'+url+'；'+str(exc));continue
        if len(content)<60 or len(re.findall(r'[\u4e00-\u9fff]',content))<20:
            gaps.append('附件可解析文本不足；扫描件、旧DOC或表格格式待专项解析：'+url);continue
        attachment_number=label_value(content,['采购项目编号','招标编号','项目编号'])
        identity=''
        if number and attachment_number and dense(number)!=dense(attachment_number):
            gaps.append('附件项目编号与公告不一致，未自动补提：'+url);continue
        if number and len(dense(number))>=5 and dense(number)==dense(attachment_number):identity='项目编号一致：'+number
        elif len(dense(stem))>=6 and dense(stem) in dense(content) and hospital_base and dense(hospital_base) in dense(content):identity='项目主体与医院名称一致：'+stem
        if not identity:gaps.append('附件与本公告项目关联待核，未自动补提：'+url);continue
        digest=attachment.get('sha256','')
        if rp:
            if rp.is_file():
                actual=hashlib.sha256(rp.read_bytes()).hexdigest()
                if digest and actual!=digest:gaps.append('附件原文hash不一致，未自动补提：'+url);continue
                digest=actual
        q=section(content,QUAL_LABELS);pq=section(content,PREQUAL_LABELS)
        p=label_value(content,['主要标的名称','标的名称','采购产品名称','货物名称'])
        supplements.append({'qualification':q,'prequalification':pq,'product':p,'text':content,'evidence':identity+'；附件：'+url+'；原文SHA256：'+(digest or '未提供')+'；原采集状态：'+str(attachment.get('status'))+'；提取来源：'+method+'；保存路径：'+str(rp or tp)})
    return supplements,gaps


def extract_one(page, base, scope='digital', scope_review=None):
    url=canonical_url(str(page.get('url','')))
    raw_path=Path(page['raw_path']) if page.get('raw_path') else None
    if raw_path and not raw_path.is_absolute(): raw_path=base/raw_path
    source=''; text=''; whole=''; headings=[]; raw=b''
    if raw_path and raw_path.is_file():
        raw=raw_path.read_bytes()
        if raw.lstrip().startswith(b'%PDF'):
            if page.get('text_path'):
                tp=Path(page['text_path']);tp=tp if tp.is_absolute() else base/tp
                text=whole=tp.read_text(encoding='utf-8-sig')
        else: source,text,whole,headings=document_text(raw)
    elif page.get('text_path'):
        tp=Path(page['text_path']);tp=tp if tp.is_absolute() else base/tp
        if tp.is_file(): raw=tp.read_bytes();text=whole=decode(raw)
    elif page.get('text'):
        text=whole=str(page['text']);raw=text.encode('utf-8')
    expected_digest = str(page.get('sha256') or '').lower()
    if expected_digest and raw and hashlib.sha256(raw).hexdigest() != expected_digest:
        return None,'原文SHA256与采集记录不一致，待核'
    if not text or len(text)<60:
        return None,'未获得可解析公告正文'
    if len(re.findall(r'[\u4e00-\u9fff]', text)) < 20:
        return None,'正文未含足够可核对的公告文字，可能为访问挑战页或加密响应'
    title=normalize(page.get('title'))
    # Listing cards sometimes prepend a display date. This cleans the title only;
    # the removed date is never adopted as the publication-date evidence.
    title=re.sub(r'^20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s+', '', title)
    # Recover clipped list-card titles only from the actual page's main heading
    # (or its HTML title), never an unrelated navigation H2.
    primary_headings = [normalize(re.sub(r'<[^>]+>', ' ', html.unescape(v)))
                        for v in re.findall(r'(?is)<h1\b[^>]*>(.*?)</h1>', source)]
    if not primary_headings:
        primary_headings = [normalize(re.sub(r'<[^>]+>', ' ', html.unescape(v)))
                            for v in re.findall(r'(?is)<title\b[^>]*>(.*?)</title>', source)]
    compact = lambda value: re.sub(r'[\s\W_]+', '', value)
    if (not title or not re.search(NOTICE, title)) and page.get('procurement_context'):
        full_title = next((h for h in primary_headings if re.search(NOTICE, h)
                           and len(h) >= 10 and (not title or (len(compact(title)) >= 5
                           and compact(title) in compact(h)))), '')
        if full_title:
            title = full_title
    if not title:
        title=next((h for h in primary_headings if re.search(NOTICE,h)), '')
    explicit_result = (bool(re.search(r'结果公告', title))
                       and bool(re.search(r'(?:^|\n)\s*(?:[一二三四五六七八九十\d]+[、.．]\s*)?采购结果\s*(?:[:：]|\n)', text))
                       and bool(re.search(r'供应商名称\s*[:：]', text))
                       and bool(re.search(r'(?:中标|成交)(?:[（(]成交[）)])?\s*金额\s*[:：]', text)))
    if (not re.search(NOTICE,title) and not explicit_result) or re.search(r'招聘|拟聘|录用|人才引进|招聘会',title):
        return None,'未确认是采购公告'
    # Reject an archived detail file whose visible heading belongs to another item.
    # Government announcement bodies often mark every numbered section as H1/H2.
    # Such section labels are not contradictory announcement titles.
    section_heading = r'^(?:[一二三四五六七八九十]+|\d{1,2})\s*[、.．]\s*(?:项目|申请人|采购|招标|中标|成交|主要标的|评审|评标|获取|提交|公告|其他|代理|凡对|对本次|附件)'
    useful=[h for h in headings if re.search(NOTICE,h) and len(h)>10 and not re.search(section_heading,h)]
    key=lambda s:re.sub(r'[\s\W_]+','',s)
    if useful and not any(key(title) in key(h) or key(h) in key(title) or SequenceMatcher(None,key(title),key(h)).ratio()>.7 for h in useful):
        return None,'列表标题与保存详情标题不一致，疑似旧文件名碰撞'
    # Some legacy list items included the date and entire teaser after the actual title.
    precise=next((h for h in useful if key(h) in key(title) and len(title)>len(h)+20),'')
    if precise:title=precise
    identity, identity_error = resolve_hospital_buyer(page, title, text)
    if not identity:
        return None,identity_error
    hospital=identity['hospital']
    dt,date_basis=publication_date(page,source,whole)
    if not dt:
        return None,date_basis
    verified_review=None
    if scope=='digital' and scope_review:
        review_id=scope_review.get('id',scope_review.get('公告ID',''))
        if (scope_review.get('raw_sha256','').lower()==hashlib.sha256(raw).hexdigest()
                and canonical_url(scope_review.get('url',''))==url
                and (not review_id or review_id==hashlib.sha256(url.encode()).hexdigest()[:20])):
            verified_review=scope_review
            decision=scope_review['decision']
            quote_text=normalize(scope_review.get('quote',''))
            if decision in {'exclude','review'}:
                return None,('原文逐条复核判为范围外：' if decision=='exclude' else '原文逐条复核仍待核：')+normalize(scope_review.get('reason',''))+'；原文：'+quote_text
    buyer=identity['buyer']
    buyer_basis=identity['basis']
    project=label_value(text,['采购项目名称','项目名称']) or title
    if len(project)<4 or project.endswith('医院'):project=title
    if verified_review and verified_review.get('corrected_project'):project=normalize(verified_review['corrected_project'])
    kind=notice_type(title)
    winner,amount,quote,gaps=award_details(text,title)
    qualification=section(text,QUAL_LABELS)
    prequalification=section(text,PREQUAL_LABELS)
    experts=section(text,[r'评审专家(?:名单|姓名)?',r'评标委员会(?:成员)?(?:名单|成员名单)?',r'评审委员会(?:成员)?(?:名单|成员名单)?'])
    # Expert blocks end before other standard result-announcement sections.
    if experts: experts=re.split(r'\n\s*(?:[一二三四五六七八九十]+[、.．]|\d+[、.．])?\s*(?:评审结果|代理服务收费|公告期限|其他补充事宜|凡对本次|采购人信息)',experts)[0].strip()
    product=label_value(text,['主要标的名称','标的名称','采购产品名称','货物名称'])
    number=label_value(text,['采购项目编号','招标编号','项目编号','项目编码','采购编号','遴选编号'])
    supplements,attachment_gaps=attachment_supplements(page,base,project,number,hospital)
    gaps.extend(attachment_gaps)
    basis=[];subject_text=text
    for supplement in supplements:
        used=[]
        if supplement['qualification'] and supplement['qualification'] not in qualification:
            qualification+='\n\n【关联附件资格原文】\n'+supplement['qualification'];used.append('供应商资格')
        if supplement['prequalification'] and supplement['prequalification'] not in prequalification:
            prequalification+='\n\n【关联附件预审原文】\n'+supplement['prequalification'];used.append('明确资格预审')
        if not product and supplement['product']:product=supplement['product'];used.append('产品标的')
        subject_text+='\n'+supplement['text'].replace(supplement['qualification'],'').replace(supplement['prequalification'],'')
        basis.append('关联附件'+('补提'+ '、'.join(used) if used else '已审阅')+'：'+supplement['evidence'])
    qualification=qualification.strip();prequalification=prequalification.strip()
    relevance=digital_evidence(title,project,product,subject_text,qualification,prequalification)
    if verified_review:
        relevance=(relevance+'；' if relevance else '')+'原文复核：'+normalize(verified_review['quote'])
        if verified_review.get('corrected_project'):basis.append('项目名称据SHA匹配的原文逐条复核纠正')
        if verified_review.get('mixed_procurement'):relevance+='；混合采购范围需拆包'
    if scope=='digital' and '正文明确采购标的字段：' in relevance and not verified_review:
        return None,'正文标的字段尚无原文SHA匹配的逐条业务复核，待核'
    if scope=='digital' and not relevance:
        if '机房' in title and not re.search(r'冷冻|冷水|放射|辐射|影像|电梯',title) and not re.search(IT_ROOM,subject_text):
            return None,'机房用途未明确，待核数字化关联'
        return None,'未确认采购标的属于医疗数字化、信息化、通信网络及相关设备服务'
    if not product:
        product_terms=[w for w in ('服务器','数据库','软件','网络安全','电子病历','医疗设备','医疗器械','耗材','试剂','保洁','安保','物业','维保','运维','HIS','PACS','LIS') if re.search(re.escape(w),title,re.I)]
        product='、'.join(product_terms)
        if product: basis.append('产品按公告标题关键词归类：'+product)
    else: basis.append('产品取公告或明确关联附件标的名称')
    scene=''
    for label,words in [('网络与数据安全',('安全','等保','密码','备份')),('信息基础设施',('服务器','网络','数据库','机房','算力')),('医院信息系统',('信息系统','电子病历','HIS','PACS','LIS','软件','信息化')),('医疗设备与耗材',('设备','器械','耗材','试剂')),('后勤服务',('保洁','安保','物业','餐饮'))]:
        hits=[w for w in words if re.search(re.escape(w),title,re.I)]
        if hits: scene=label;basis.append('场景按标题关键词归类：'+'、'.join(hits));break
    operators=[label for label,tokens in [('中国移动',('中国移动','中移')) ,('中国电信',('中国电信','中电信','天翼')),('中国联通',('中国联通','中国联合网络通信')),('中国铁塔',('中国铁塔',)),('中国广电',('中国广电',))] if any(t in winner for t in tokens)]
    operator='；'.join(operators)
    if operators:basis.append('运营商类型按中标单位名称关键词识别，未作股权穿透')
    province=identity['province']
    region=province
    labels='·'.join(x for x in (region,normalize(page.get('hospital_level'))) if x)
    if labels: basis.append('客户标签取医院清单登记信息')
    fields={'产品':product,'项目编号':number,'响应人资格要求':qualification}
    for label,value in fields.items():
        if not value:gaps.append(label+'未在已获取正文中提取到')
    if not province:gaps.append('省份待医院地域清单核实')
    if kind=='中标或成交公告':
        if not winner:gaps.append('中标单位未在正文明确提取')
        if amount is None:gaps.append('未取得可直接归属本公告的单一中标金额')
        if not experts:gaps.append('评审专家未披露或未提取')
    else:gaps.append('本公告尚非最终中标成交阶段：中标单位、中标金额及评审专家不适用或尚未公布');experts=''
    if not prequalification:gaps.append('未发现明确资格预审资质要求段落，不以一般供应商资格替代')
    if page.get('attachments') and supplements:gaps.append('关联附件已补提可识别条款；附件完整性及正文外表格仍需复核')
    if any(token in str(page.get('provenance','')) for token in ('legacy','historical_cache','历史')):gaps.append('历史留存原文，本轮未重新抓取，不代表本轮网络访问成功')
    provenance=page.get('provenance','本轮采集')
    if isinstance(provenance,dict):
        prefix='历史留存原文，本轮未重新抓取' if any(token in str(provenance.get('kind','')) for token in ('legacy','historical_cache')) else '本轮网络采集' if provenance.get('kind')=='live_http' else '原文来源待复核'
        provenance=prefix+'；'+json.dumps(provenance,ensure_ascii=False)
    row={'时间':dt,'项目名称':project,'产品':product,'招标单位':buyer,'客户标签':labels,'中标单位':winner,'运营商类型':operator,'中标金额（万元）':amount,'场景':scene,'评审专家':experts,'网址':url,'公告类型':kind,'省份':province,'项目编号':fields['项目编号'],'中标金额原文':quote,'信息缺口':'；'.join(dict.fromkeys(gaps)),'标签依据':'；'.join(basis),'响应人资格要求（对供应商基本要求）':qualification,'资格预审资质要求':prequalification,'医院名称':hospital,'医院ID':identity['hospital_ids'],'日期依据':date_basis,'采购人依据':buyer_basis,'采集来源':str(provenance),'抓取时间':str(page.get('fetched_at','')),'公告ID':hashlib.sha256(url.encode()).hexdigest()[:20],'原文SHA256':hashlib.sha256(raw).hexdigest(),'原文路径':str(raw_path or page.get('text_path','')),'数字化标签':'数字化相关（已匹配采购标的）' if relevance else '未确认数字化相关'}
    if relevance:row['标签依据']+='；数字化标签依据'+relevance
    if verified_review:row['数字化标签']='数字化相关（原文逐条复核，SHA匹配）'
    if '混合采购范围需拆包' in relevance:
        row['数字化标签']='数字化相关（混合采购，需拆包确认IT范围）'
        row['信息缺口']+='；仅确认混合采购含数字化子标的，需按包或明细核验数字化范围；整体金额不可作为数字化金额'
        if row['中标金额（万元）'] is not None:
            row['中标金额（万元）']=None
            row['信息缺口']+='；混合采购总额未拆分数字化份额，金额数值留空，原文保留'
    row['入口任务ID']=str(page.get('task_id',''))
    return row,''


def deduplicate_same_document(rows):
    """Collapse only byte-identical GGZY notices with identical announcement facts."""
    groups={}; retained=[]; evidence=[]
    for row in rows:
        parts=urlsplit(row.get('网址',''))
        digest=row.get('原文SHA256','')
        ids=tuple(sorted(set(x.strip() for x in re.split(r'[；;,，]',row.get('医院ID','')) if x.strip())))
        if (parts.hostname!='www.ggzy.gov.cn'
                or not re.match(r'^/(?:his/)?information/deal/html/[ab]/',parts.path)
                or not re.fullmatch(r'[a-fA-F0-9]{64}',digest) or not ids):
            retained.append(row);continue
        key=(digest.lower(),ids)+tuple(row.get(k,'') for k in ['时间','项目名称','公告类型','项目编号'])
        groups.setdefault(key,[]).append(row)
    facts=['网址','原文路径','原文SHA256','公告ID','抓取时间','入口任务ID']
    for key, group in groups.items():
        if len(group)==1:
            retained.append(group[0]);continue
        rank=lambda r:('本轮网络采集' in r.get('采集来源',''),r.get('抓取时间',''),
                       sum(v not in ('',None) for v in r.values()),r.get('网址',''))
        ordered=sorted(group,key=rank,reverse=True)
        primary=dict(ordered[0]);aliases=ordered[1:]
        primary['采集来源']=primary.get('采集来源','')+'；同原文其他网址：'+'；'.join(r['网址'] for r in aliases)
        retained.append(primary)
        evidence.append({'rule':'仅官方GGZY：原文SHA256、医院ID集合、日期、项目名称、公告类型、项目编号完全相同',
                         'key':{'sha256':key[0],'hospital_ids':list(key[1]),'date':key[2],
                                'project':key[3],'notice_type':key[4],'project_number':key[5]},
                         'primary':{k:primary.get(k,'') for k in facts},
                         'aliases':[{k:r.get(k,'') for k in facts} for r in aliases]})
    return retained,evidence


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pages',required=True);ap.add_argument('--coverage');ap.add_argument('--output-dir',required=True);ap.add_argument('--since',default='2024-01-01');ap.add_argument('--until',default='2026-11-03');ap.add_argument('--scope',choices=['all','digital'],default='digital');ap.add_argument('--workers',type=int,default=4);ap.add_argument('--scope-review');args=ap.parse_args()
    if not 1<=args.workers<=8:ap.error('--workers must be between 1 and 8')
    source=Path(args.pages);pages=read_json(source);pages=pages.get('pages',pages) if isinstance(pages,dict) else pages
    scope_reviews={}
    if args.scope_review:
        payload=read_json(args.scope_review)
        if isinstance(payload,dict):payload=payload.get('reviews',payload.get('items',payload.get('results')))
        if not isinstance(payload,list):raise ValueError('Scope review must be an array or an object containing reviews/items/results')
        for item in payload:
            if item.get('decision') not in {'keep','exclude','review'} or not item.get('url') or not re.fullmatch(r'[a-fA-F0-9]{64}',item.get('raw_sha256','')):
                raise ValueError('Invalid scope review decision/url/raw_sha256')
            if item['decision']=='keep' and not normalize(item.get('quote','')):raise ValueError('A keep review requires an original-text quote')
            key=canonical_url(item['url'])
            if key in scope_reviews and scope_reviews[key]!=item:raise ValueError('Conflicting scope reviews for '+key)
            scope_reviews[key]=item
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    kept={};excluded=[];dupes=0
    executor=ProcessPoolExecutor(max_workers=args.workers) if args.workers>1 and pages else None
    tasks=((page,str(source.parent),args.scope,scope_reviews.get(canonical_url(page.get('url','')))) for page in pages)
    outcomes=executor.map(extract_task,tasks,chunksize=20) if executor else map(extract_task,tasks)
    try:
        for index,(page,(row,reason)) in enumerate(zip(pages,outcomes),1):
            if row and not args.since<=row['时间']<=args.until: row,reason=None,'公告日期不在任务范围'
            if row:
                key=row['网址']
                if key in kept:
                    dupes+=1
                    old=kept[key]
                    if (row['抓取时间'],len(row['响应人资格要求（对供应商基本要求）']))>(old['抓取时间'],len(old['响应人资格要求（对供应商基本要求）'])):kept[key]=row
                else:kept[key]=row
            else:excluded.append({'医院名称':page.get('hospital',''),'任务ID':page.get('task_id',''),'项目名称':page.get('title',''),'网址':page.get('url',''),'原列表日期':page.get('date',''),'未纳入原因':reason,'原文路径':page.get('raw_path','')})
            if index%100==0 or index==len(pages):print(json.dumps({'phase':'extract','processed':index,'total':len(pages),'accepted_unique':len(kept),'excluded':len(excluded)},ensure_ascii=False),flush=True)
    finally:
        if executor:executor.shutdown(wait=True)
    unique_rows,dedup_evidence=deduplicate_same_document(list(kept.values()))
    rows=sorted(unique_rows,key=lambda r:(r['时间'],r['医院名称'],r['项目名称']),reverse=True)
    coverage=read_json(args.coverage) if args.coverage else []
    if isinstance(coverage,dict):coverage=coverage.get('coverage',coverage.get('hospitals',coverage.get('sources',[coverage])))
    summary={'generated_at':datetime.now(timezone.utc).isoformat(),'since':args.since,'until':args.until,'input_pages':len(pages),'records':len(rows),'duplicate_urls':dupes,'excluded':len(excluded),'exclusion_reasons':dict(Counter(x['未纳入原因'] for x in excluded)),'qualification_rows':sum(bool(r['响应人资格要求（对供应商基本要求）']) for r in rows),'prequalification_rows':sum(bool(r['资格预审资质要求']) for r in rows),'award_amount_rows':sum(r['中标金额（万元）'] is not None for r in rows),'status':'partial','scope':'本表包含已取得原文且日期与医院关联可核的公告，不代表全部网站历史完整覆盖。'}
    summary['requested_scope']=args.scope
    summary['duplicate_same_document']=sum(len(item['aliases']) for item in dedup_evidence)
    summary['main_table_entrance_count']=len({r['入口任务ID'] for r in rows if r['入口任务ID']})
    summary['main_table_hospital_name_count']=len({r['医院名称'] for r in rows if r['医院名称']})
    summary['main_table_hospital_name_note']='按明确采购主体匹配的名录医院名称字符串去重计数；组合名称不拆分，不等于唯一法人医院数'
    summary['year_counts']=dict(sorted(Counter(r['时间'][:4] for r in rows).items()))
    summary['announcement_type_counts']=dict(Counter(r['公告类型'] for r in rows))
    summary['scope_review_file']=str(Path(args.scope_review).resolve()) if args.scope_review else None
    summary['scope_review_sha256']=hashlib.sha256(Path(args.scope_review).read_bytes()).hexdigest() if args.scope_review else None
    summary['scope_review_rows']=len(scope_reviews)
    summary['main_rows_with_matched_scope_review']=sum('原文复核：' in r['标签依据'] for r in rows)
    for name,value in [('records',rows),('excluded',excluded),('coverage',coverage),('summary',summary),('columns',COLUMNS),('dedup-evidence',dedup_evidence)]:write_json(out/(name+'.json'),value)
    with (out/'rows.csv').open('w',encoding='utf-8-sig',newline='') as fh:
        writer=csv.DictWriter(fh,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    print(json.dumps(summary,ensure_ascii=False))


def extract_task(task):
    page,base,scope,*review=task
    try:return extract_one(page,Path(base),scope,review[0] if review else None)
    except (OSError,ValueError,KeyError) as exc:return None,'正文读取或结构错误：'+str(exc)


if __name__=='__main__':main()
