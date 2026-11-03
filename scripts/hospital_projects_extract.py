# -*- coding: utf-8 -*-
"""Extract structured digital-procurement project rows from saved hospital
tender detail HTMLs.

Output columns (user template):
  项目名称, 产品, 招标单位, 客户标签, 中标单位, 运营商类型,
  中标金额（万元）, 场景, 时间
Plus traceability columns: 招采公告URL, 任务ID, 批次, 金额口径备注.
"""
import csv
import glob
import json
import os
import re
import sys
import urllib.parse

BASE = r'E:/CAICTBigData/coding/outputs/hospital-site-crawl-90-20261028'
TMP = r'E:/CAICTBigData/coding/.workbuddy/tmp'
OUT_DIR = os.path.join(BASE, 'projects_table')
SINCE = '2024-01-01'


def to_text(raw):
    """Decode bytes and strip tags to readable text."""
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            h = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        h = raw.decode('utf-8', 'ignore')
    h = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', h)
    h = re.sub(r'(?is)<br\s*/?>|</p>|</div>|</tr>|</li>', '\n', h)
    h = re.sub(r'(?s)<[^>]+>', ' ', h)
    h = h.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'[ \t\r]+', ' ', h)


# ------------------------------------------------------------------ winners
def _is_nonwinner(name, text, pos, hospital_name):
    """True if the matched org is a buyer / agency / the hospital itself."""
    if hospital_name and (hospital_name in name or name in hospital_name):
        return True
    if re.search(r'(?:医院|大学|学院|管理中心)$', name) and '公司' not in name:
        return True  # schools/hospitals are buyers in this corpus
    pre = text[max(0, pos - 30):pos]
    if re.search(r'代理|招标机构|采购人|比选人|招标人|采购单位|项目单位|潜在', pre):
        return True
    return False


def find_winner(text, hospital_name=''):
    """Return winner org name or ''. Award statements only."""
    if re.search(r'废标|作废|终止|流产', text[:600]):
        return ''
    org_re = r'[^\s，。;；()（）]{4,55}?(?:有限公司|有限责任公司|集团|研究院|研究所|事务所|分公司)'
    op_re = (r'(?:(?:中国)?(?:电信|移动|联通|铁塔|广电)(?:翼康|通信|集团|数科|数字)[^\s，。;；()]{0,24}'
             r'|(?:中国)?(?:电信|移动|联通|铁塔|广电)(?:有限公司|分公司))')
    pats = [
        # explicit award phrases (self-qualifying)
        re.compile(r'(?:中标|成交)(?:候选)?(?:供应商|人|单位|企业)\s*(?:名称)?\s*[：:为是]\s*(' + org_re + ')'),
        re.compile(r'(?:第一(?:中标|成交)候选人|排序第一)[^\n]{0,60}?名称\s*[：:]\s*(' + org_re + ')'),
        re.compile(r'(?:中标|成交)[^\n]{0,30}金额[：:][^\n]{0,40}?名称\s*[：:]\s*(' + org_re + ')'),
        # telecom operators often appear without a 公司 suffix in award lines
        re.compile(r'(?:中标|成交)[^\n]{0,60}?(' + op_re + ')'),
    ]
    for p in pats:
        m = p.search(text)
        if m:
            name = m.group(1).strip('：: ，。')
            name = re.sub(r'^[【\[（("]+', '', name)
            name = re.sub(r'（[^）]*）$', '', name) if len(name) > 30 else name
            if len(name) >= 4 and not _is_nonwinner(name, text, m.start(1), hospital_name):
                return name
    # generic 名称：ORG — only when award keywords sit immediately before
    has_award_ctx = bool(re.search(r'(?:中标|成交|遴选)结果|结果公示|中标公告|成交公告|中标(?:候选人)?公示|成交公示|中标通知书|成交通知书', text))
    if has_award_ctx:
        for m in re.finditer(r'名称\s*[：:]\s*(' + org_re + ')', text):
            pre = text[max(0, m.start() - 120):m.start()]
            if not re.search(r'中标|成交|候选|供应商', pre):
                continue
            name = m.group(1).strip('：: ，。')
            if len(name) >= 4 and not _is_nonwinner(name, text, m.start(1), hospital_name):
                return name
    return ''


AMOUNT_PATTERNS = [
    re.compile(r'(?:中标|成交)(?:总)?(?:金额|总价|价格)\s*[：:为是]?\s*[约¥￥]?\s*([\d,，.]+)\s*(万元|元)'),
    re.compile(r'(?:中标|成交)[^\n]{0,12}?金额\s*为\s*[约¥￥]?\s*([\d,，.]+)\s*(万元|元)'),
    re.compile(r'(?:成交价|中标价|总报价|报价总额|投标报价)\s*[：:为是]?\s*[约¥￥]?\s*([\d,，.]+)\s*(万元|元)'),
    re.compile(r'(?:金额|总价|价格)\s*[：:为是]\s*[¥￥]?\s*([\d,，.]+)\s*(万元|元)'),
]

DATE_IN_TEXT = re.compile(
    r'(?:发布(?:日期|时间)|发表(?:日期|时间)|日期|时间)\s*[：:]\s*(20\d{2})[-/.年]\s*(\d{1,2})[-/.月]\s*(\d{1,2})\s*日?')


def backfill_date(text):
    m = DATE_IN_TEXT.search(text)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            return ''
    return ''


def find_amount(text):
    """Return (amount_wan, note). Award amounts only; budget/ceiling excluded."""
    if re.search(r'废标|作废|终止|流产', text[:600]):
        return '', ''
    has_award_ctx = bool(re.search(r'(?:中标|成交|遴选)结果|结果公示|中标公告|成交公告|中标通知书|成交通知书', text))
    for i, p in enumerate(AMOUNT_PATTERNS):
        if i == 3 and not has_award_ctx:
            continue
        for m in p.finditer(text):
            # blacklist: budget / ceiling price near the phrase
            pre = text[max(0, m.start() - 14):m.start()]
            if re.search(r'预算|限价|控制价|概算|最高', pre):
                continue
            num = float(m.group(1).replace(',', '').replace('，', ''))
            if m.group(2) == '元':
                num = num / 10000.0
            if num <= 0 or num > 10_000_000:  # sanity: >1000亿 unlikely
                continue
            note = '成交/中标金额' if i < 2 else ('报价类（结果公告内）' if i == 2 else '结果公告内金额（口径待核）')
            return round(num, 2), note
    return '', ''


PRODUCT_WORDS = [
    ('服务器', '服务器'), ('存储', '存储'), ('交换机', '交换机'), ('路由器', '路由器'),
    ('防火墙', '防火墙'), ('上网行为', '上网行为管理'), ('负载均衡', '负载均衡'),
    ('机房', '机房建设'), ('UPS', 'UPS'), ('精密空调', '精密空调'),
    ('数据库', '数据库'), ('操作系统', '操作系统'), ('中间件', '中间件'), ('虚拟化', '虚拟化'),
    ('HIS', 'HIS'), ('LIS', 'LIS'), ('PACS', 'PACS'), ('电子病历', '电子病历'),
    ('手麻', '手术麻醉系统'), ('护理', '护理系统'), ('互联网医院', '互联网医院'),
    ('自助', '自助设备'), ('叫号', '分诊叫号'), ('挂号', '挂号系统'),
    ('监控', '视频监控'), ('门禁', '门禁'), ('物联网', '物联网'), ('5G', '5G'),
    ('无线网络', '无线网络'), ('WiFi', 'WiFi'), ('综合布线', '综合布线'),
    ('等保', '等保测评'), ('密评', '商用密码评估'), ('态势感知', '态势感知'),
    ('堡垒机', '堡垒机'), ('容灾', '容灾'), ('备份', '数据备份'),
    ('数据治理', '数据治理'), ('数据中台', '数据中台'), ('数据中心', '数据中心'),
    ('知识库', '知识库'), ('CDSS', 'CDSS'), ('人工智能', '人工智能'), ('AI', 'AI'),
    ('大模型', '大模型'), ('算力', '算力'), ('云平台', '云平台'), ('云计算', '云计算'),
    ('运维', '运维服务'), ('维保', '维保服务'), ('弱电', '弱电工程'),
    ('信息科', '信息化建设'), ('信息化建设', '信息化建设'), ('软件', '软件'),
    ('平台', '平台'), ('系统', '系统'), ('终端', '终端'), ('电脑', '台式电脑'),
    ('打印机', '打印机'), ('影像', '影像设备'), ('B超', '超声'), ('CT', 'CT'),
]

SCENARIO_RULES = [
    ('网络与数据安全', ('安全', '等保', '密评', '态势感知', '防火墙', '容灾', '备份', '堡垒机', '密码', '等级保护')),
    ('IT基础设施与运维', ('服务器', '存储', '交换机', '路由器', '机房', 'UPS', '空调', '运维', '维保', '虚拟化', '算力', '综合布线', '弱电', '终端', '电脑', '打印机', '云平台', '负载均衡', '上网行为')),
    ('临床数据与知识服务', ('数据治理', '数据中台', '数据中心', '知识库', 'CDSS', '病案', '科研数据', '数据空间', '数据库', '大数据')),
    ('智慧后勤与安防', ('监控', '门禁', '物联网', '智慧后勤', '物流', '能源', '停车', '污水', '安防', '后勤')),
    ('临床与运营信息系统', ('HIS', 'LIS', 'PACS', '电子病历', '手麻', '护理', '互联网医院', '挂号', '叫号', '自助', '医保', '系统', '平台', '软件', '信息化')),
]


def find_products(text):
    out = []
    for kw, name in PRODUCT_WORDS:
        if kw.lower() in text.lower() and name not in out:
            out.append(name)
    return '、'.join(out[:6])


def find_scenario(text):
    low = text.lower()
    for name, words in SCENARIO_RULES:
        if any(w.lower() in low for w in words):
            return name
    return ''


OPERATOR_RULES = [
    ('中国移动', ('中国移动', '中移', '移动通信', '铁通', '咪咕')),
    ('中国电信', ('中国电信', '电信股份', '天翼')),
    ('中国联通', ('中国联通', '联通')),
    ('中国铁塔', ('中国铁塔', '铁塔')),
    ('中国广电', ('中国广电', '广电网络')),
]


def operator_type(winner):
    if not winner:
        return ''
    # names that BEGIN with an operator token are operator subsidiaries
    m = re.match(r'^(?:中国)?(移动|电信|联通|铁塔|广电)', winner)
    if m:
        return {'移动': '中国移动', '电信': '中国电信', '联通': '中国联通',
                '铁塔': '中国铁塔', '广电': '中国广电'}[m.group(1)]
    for name, words in OPERATOR_RULES:
        if any(w in winner for w in words):
            return name
    return '非运营商'


# ------------------------------------------------- relevance classification
DIG_STRONG = ('数据', '网络', '软件', '信息化', '信息安全', '智慧', '互联网', '服务器',
              '存储', '交换机', '机房', '等保', '密码', '网络安全', '数据库', '运维',
              '云平台', '算力', '大模型', '人工智能', '物联网', '门禁', '视频监控',
              '电子病历', 'HIS', 'LIS', 'PACS', 'CDSS', 'OA', '网站', '小程序',
              '系统集成', '综合布线', '数据中心', '知识库', '中台', '弱电')
DIG_WEAK = ('系统', '平台', '终端', '电脑', '数字', '信息', '监控', '维保')
CONSTR = ('更新工程', '改造工程', '提升改造', '修缮', '维修工程', '安装工程', '建设工程',
          '土建', '管道', '锅炉', '电梯', '消防', '氧气', '衰变池', '净化', '装修',
          '装饰', '拆除', '园林绿化', '幕墙', '防水', '监理', '市容', '绿化',
          '冷却塔', '填料', '过滤器', '通风系统', '灭菌器')
MEDDEV = ('内窥镜', '手术系统', '医用设备', '医疗设备', '带量采购', '彩超', '超声诊断',
          '超声设备', '监护仪', '呼吸机', '麻醉机', '血透', '核磁', 'CT机', '直线加速器',
          '康复设备', '医疗装备', '医疗器械', '器械', '设备购置', '设备更新', '医用',
          '射线', '灭菌', '药学', '药房')


def _hvac(title):
    if '空调' not in title:
        return False
    return not any(w in title for w in ('机房空调', '精密空调', '数据中心', '机房'))


def classify_relevance(title, text):
    """Return (bucket, reason): keep | excluded_construction | excluded_meddev | excluded_no_signal."""
    t = title
    head = text[:2500] if text else ''
    if any(w in t for w in CONSTR) or _hvac(t):
        return 'excluded_construction', '标题含工程建设/后勤改造/设备维保类关键词'
    if any(w in t for w in MEDDEV):
        if not any(w in t for w in DIG_STRONG):
            return 'excluded_meddev', '标题为医用设备/耗材类，非数字化采购'
    if any(w in t for w in DIG_STRONG):
        return 'keep', ''
    if any(w in t for w in DIG_WEAK) and not any(w in t for w in MEDDEV):
        return 'keep', ''
    # title has no signal — allow strong signal from detail body
    if head and any(w in head for w in DIG_STRONG):
        return 'keep', '标题无信号，正文含数字化关键词'
    if not any(w in t for w in DIG_WEAK):
        return 'excluded_no_signal', '标题与正文均无数字化关键词'
    return 'excluded_no_signal', '仅有弱信号词且正文无数字化关键词'


def load_hospital_meta():
    """医院ID -> (区域, 等级, 全称); plus name -> same for fuzzy lookup."""
    import io
    d = json.load(open(os.path.join(TMP, 'hosp_rows.json'), encoding='utf-8'))
    rows = list(csv.reader(io.StringIO(d['csv_data'])))
    header = ['医院ID', '区域', '医院全称', '别名', '机构类型（初分）', '任务范围', '原表等级', '本院官网']
    ix = {h: i for i, h in enumerate(header)}
    by_id, by_name = {}, {}
    for r in rows[1:]:
        if not r or not r[ix['医院ID']].strip():
            continue
        level = r[ix['原表等级']].strip()
        level_short = '三甲' if '三级甲等' in level else ('三乙' if '三级乙等' in level else ('二级' if level.startswith('二级') else level[:6]))
        meta = (r[ix['区域']].strip(), level_short, r[ix['医院全称']].strip())
        by_id[r[ix['医院ID']].strip()] = meta
        by_name[meta[2]] = meta
    return by_id, by_name


def cust_label(hospital_name, hosp_ids, by_id, by_name):
    meta = by_name.get(hospital_name)
    if not meta:
        for i in [x.strip() for x in re.split('[；;]', hosp_ids) if x.strip()]:
            if i in by_id:
                meta = by_id[i]
                break
    if not meta:  # fuzzy: hospital name contained in table name or vice versa
        for n, m in by_name.items():
            if n and (n in hospital_name or hospital_name in n):
                meta = m
                break
    if meta:
        parts = [p for p in (meta[0], meta[1]) if p]
        return '·'.join(parts) if parts else ''
    return ''


def detail_path_for(url, task_id, source):
    """Resolve saved detail HTML for an item URL, or ''. """
    if source == 'pilot':
        seg = urllib.parse.urlsplit(url).path.rsplit('/', 1)[-1].replace('.htm', '')
        p = os.path.join(BASE, 'pilot-puh3-v4', 'detail', f'{seg}_htm')
        return p if os.path.exists(p) else ''
    safe = re.sub(r'[^0-9A-Za-z]', '', urllib.parse.urlsplit(url).path)[-24:]
    for sub in (['render-fix'] if source == 'fix' else []):
        p = os.path.join(BASE, 'batch-20261028', task_id, sub, 'details', f'{safe}.html')
        if os.path.exists(p):
            return p
    p = os.path.join(BASE, 'batch-20261028', task_id, 'details', f'{safe}.html')
    return p if os.path.exists(p) else ''


def collect_items():
    """Yield dicts: task_id,batch,hospital,hosp_ids,title,url,date,src."""
    ent = json.load(open(os.path.join(BASE.rsplit('/', 1)[0], 'idea-trees' in BASE and '' or '', ''), encoding='utf-8')) if False else None
    tree_dir = r'E:/CAICTBigData/coding/idea-trees/hospital-site-crawl-90-20261028'
    entrances = json.load(open(os.path.join(tree_dir, 'entrances.json'), encoding='utf-8'))['entrances']
    ent_by_id = {e['task_id']: e for e in entrances}

    items = []
    # batch sites (exclude render-fix subdir items; collected separately)
    for p in glob.glob(os.path.join(BASE, 'batch-20261028', 'C*', 'items.csv')):
        tid = p.split(os.sep)[-2]
        e = ent_by_id.get(tid, {})
        for r in csv.DictReader(open(p, encoding='utf-8-sig')):
            if r.get('candidate') == '1':
                items.append(dict(task_id=tid, batch=e.get('batch', ''), hospital=e.get('hospital', ''),
                                  hosp_ids=e.get('hospital_ids', ''), title=r['title'], url=r['url'],
                                  date=r['date'], src='batch'))
    # fix sites
    for p in glob.glob(os.path.join(BASE, 'batch-20261028', 'C*', 'render-fix', 'items.csv')):
        tid = p.split(os.sep)[-3]
        e = ent_by_id.get(tid, {})
        for r in csv.DictReader(open(p, encoding='utf-8-sig')):
            if r.get('candidate') == '1':
                items.append(dict(task_id=tid, batch=e.get('batch', ''), hospital=e.get('hospital', ''),
                                  hosp_ids=e.get('hospital_ids', ''), title=r['title'], url=r['url'],
                                  date=r['date'], src='fix'))
    # pilot
    rows = list(csv.DictReader(open(os.path.join(BASE, 'pilot-puh3-v4', 'list_items.csv'), encoding='utf-8-sig')))
    for r in rows:
        if r.get('candidate') == '1':
            items.append(dict(task_id='C0057', batch='P0', hospital='北京大学第三医院',
                              hosp_ids='', title=r['title'], url=r['url'], date=r['date'], src='pilot'))
    return items


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    by_id, by_name = load_hospital_meta()
    items = collect_items()
    print('candidate items:', len(items))

    out_rows = []
    excluded = []
    stat = {'no_detail': 0, 'winner': 0, 'amount': 0, 'read_fail': 0}
    for it in items:
        dp = detail_path_for(it['url'], it['task_id'], it['src'])
        text = ''
        if dp:
            try:
                raw = open(dp, 'rb').read()
                text = to_text(raw)
            except OSError:
                stat['read_fail'] += 1
        if not text:
            text = it['title']
            stat['no_detail'] += 1
        hosp_name = it['hospital']
        bucket, reason = classify_relevance(it['title'], text)
        winner = find_winner(text, hosp_name)
        amount, note = find_amount(text)
        date_out = it['date'] or backfill_date(text)
        if winner:
            stat['winner'] += 1
        if amount:
            stat['amount'] += 1
        row = {
            '项目名称': it['title'],
            '产品': find_products(text if len(text) > 200 else it['title'] + ' ' + text),
            '招标单位': hosp_name,
            '客户标签': cust_label(hosp_name, it['hosp_ids'], by_id, by_name),
            '中标单位': winner,
            '运营商类型': operator_type(winner),
            '中标金额（万元）': amount,
            '场景': find_scenario(it['title'] + ' ' + (text[:3000] if text else '')),
            '时间': date_out,
            '金额口径备注': note,
            '招采公告URL': it['url'],
            '任务ID': it['task_id'],
            '批次': it['batch'],
        }
        if bucket == 'keep':
            out_rows.append(row)
        else:
            row['排除原因'] = reason
            excluded.append(row)

    # project scope: 2024-01-01 onwards; undated rows kept but flagged
    for r in out_rows:
        r['金额口径备注'] = ('日期缺：列表页与正文均未标注发布日期' if not r['时间'] else r['金额口径备注'])
    in_scope = [r for r in out_rows if r['时间'] >= SINCE]
    undated = [r for r in out_rows if not r['时间']]
    out_rows = in_scope + undated

    out_rows.sort(key=lambda r: (r['时间'] or '9999', r['任务ID']), reverse=True)
    fields = ['项目名称', '产品', '招标单位', '客户标签', '中标单位', '运营商类型',
              '中标金额（万元）', '场景', '时间', '金额口径备注', '招采公告URL', '任务ID', '批次']
    out_csv = os.path.join(OUT_DIR, '医院数字化招采项目表_20261028.csv')
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    # excluded audit trail
    exc_csv = os.path.join(OUT_DIR, '排除记录_非数字化候选_20261028.csv')
    with open(exc_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['项目名称', '招标单位', '时间', '排除原因',
                                          '招采公告URL', '任务ID', '批次'])
        w.writeheader()
        for r in excluded:
            w.writerow({k: r.get(k, '') for k in w.fieldnames})

    import collections
    print('kept rows:', len(out_rows), '| excluded:', len(excluded))
    print('with winner:', stat['winner'], '| with amount:', stat['amount'],
          '| no detail text:', stat['no_detail'], '| read fail:', stat['read_fail'])
    print('场景:', dict(collections.Counter(r['场景'] for r in out_rows)))
    print('运营商:', dict(collections.Counter(r['运营商类型'] for r in out_rows if r['运营商类型'])))
    print('排除原因:', dict(collections.Counter(r['排除原因'] for r in excluded)))
    dated = collections.Counter((r['时间'] or '(无日期)')[:4] for r in out_rows)
    print('年份:', dict(sorted(dated.items())))
    print('saved:', out_csv)


if __name__ == '__main__':
    sys.exit(main())
