"""Offline regression tests for access boundaries and procurement semantics."""
import json
from pathlib import Path
import tempfile
import unittest
from pipeline.research.tenders import (load_rules, select_sources, plan, parse_html,
                                      amount_mentions, stage_of, collect, failure_code)


class TenderRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules()
        cls.ccgp = select_sources(cls.rules,['ccgp'])[0]

    def test_matrix_and_provinces(self):
        self.assertEqual(len(self.rules['province_directories']),31)
        self.assertEqual({s['matrix_group'] for s in self.rules['sources']},{'A','B','C'})
        self.assertEqual(len({s['id'] for s in self.rules['sources']}),len(self.rules['sources']))

    def test_plan_never_claims_execution(self):
        result = plan(self.rules,self.rules['sources'])
        self.assertEqual(result['network_requests'],0)
        self.assertEqual(result['status'],'planned')

    def test_unknown_source_is_error(self):
        with self.assertRaises(ValueError):
            select_sources(self.rules,['not-a-site'])

    def test_no_implicit_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                collect(self.rules,[self.ccgp],Path(tmp)/'run')
            self.assertFalse((Path(tmp)/'run').exists())

    def test_gbk_and_old_body(self):
        html = '''<meta charset="gb2312"><title>某医院信息化平台中标公告</title>
        <table><tr><td>公告时间</td><td>2026年10月25日</td></tr></table>
        <div class="vT_detail_content"><p>某医院信息化平台采购中标金额为100万元，项目经采购程序确认。</p></div>'''
        parsed = parse_html(html.encode('gb18030'),'https://www.ccgp.gov.cn/x.htm',self.ccgp,self.rules)
        self.assertEqual(parsed['status'],'detail_parsed')
        self.assertEqual(parsed['detail']['published_at'],'2026-10-25')
        self.assertTrue(parsed['detail']['medical_digital_candidate'])
        self.assertIsNone(parsed['detail']['amount_cny'])

    def test_new_body_and_unknown_dates(self):
        html = '<title>某医院电子病历系统中标公告</title><div class="vF_detail_content">'+('医院电子病历系统采购详情。'*10)+'</div>'
        result = parse_html(html.encode(),'https://www.ccgp.gov.cn/2024/x.htm',self.ccgp,self.rules)
        self.assertEqual(result['detail']['published_at'],'')
        self.assertEqual(result['detail']['event_date'],'')

    def test_portal_heading_does_not_replace_notice_title(self):
        s=select_sources(self.rules,['ggzy_tianjin'])[0]
        html='''<h1>全国公共资源交易平台（天津市）</h1><h1 class="detail-title">医院数据库服务成交公告</h1>
        <div class="detail-body">本项目数据库服务已经履行采购程序，具体采购人及中标供应商以公告原文为准。</div>'''
        record=parse_html(html.encode(),'https://ggzy.zwfwb.tj.gov.cn/x',s,self.rules)['detail']
        self.assertEqual(record['title'],'医院数据库服务成交公告')
        self.assertEqual(record['stage'],'award')

    def test_dynamic_detail_with_empty_title_is_reported(self):
        s=select_sources(self.rules,['ggzy_qinghai'])[0]
        html='<h1 id="mytitle"></h1><p>项目信息</p><script src="js/projectDetail.js"></script>'
        parsed=parse_html(html.encode(),'http://www.qhggzyjy.gov.cn/ggzy/projectDetail.html',s,self.rules)
        self.assertEqual(parsed['status'],'dynamic_shell')
        self.assertIsNone(parsed['detail'])

    def test_vendor_award_stays_source_claim(self):
        s=select_sources(self.rules,['iflyhealth'])[0]
        html='<h1>讯飞医疗某医院项目中标喜报发布</h1><article>'+('医疗信息化软件项目新闻陈述。'*12)+'</article>'
        record=parse_html(html.encode(),'https://www.xunfeihealthcare.com/news/1',s,self.rules)['detail']
        self.assertEqual(record['stage'],'source_claim')
        self.assertEqual(record['claimed_stage'],'award')
        self.assertEqual(record['review_status'],'source_claim')

    def test_challenge_200_is_not_success(self):
        html = '<title>安全验证</title><p>请完成安全验证。</p>'
        result = parse_html(html.encode(),'https://www.ccgp.gov.cn/x',self.ccgp,self.rules)
        self.assertEqual(result['status'],'challenge')
        self.assertIsNone(result['detail'])

    def test_candidates_corrections_cancellations_are_not_awards(self):
        self.assertEqual(stage_of('医院中标候选人公示'),'candidate')
        self.assertEqual(stage_of('医院中标公告更正'),'correction')
        self.assertEqual(stage_of('医院中标项目终止公告'),'cancellation')

    def test_amount_units_and_roles_remain_separate(self):
        mentions = amount_mentions('预算200万元；成交金额158.23万元；代理服务费2万元。')
        self.assertEqual([m['cny'] for m in mentions],['2000000','1582300.00','20000'])
        self.assertEqual([m['role'] for m in mentions],['budget','award','fee'])
        self.assertTrue(all(m['requires_review'] for m in mentions))

    def test_agency_fee_after_award_reference(self):
        mentions = amount_mentions('以中标金额为基准收取。本项目代理费总金额：1.335000 万元')
        self.assertEqual(mentions[0]['role'],'fee')

    def test_total_in_summary_table_is_retained(self):
        html = '''<title>某医院信息化平台中标公告</title>
        <table><tr><td>总中标金额</td><td>￥89.000000 万元（人民币）</td></tr></table>
        <div class="vF_detail_content">本采购项目详情中包含项目编号、采购人、代理机构等资料，请核对原文。</div>'''
        detail = parse_html(html.encode(),'https://www.ccgp.gov.cn/x',self.ccgp,self.rules)['detail']
        self.assertEqual(detail['amount_mentions'][0]['cny'],'890000.000000')
        self.assertEqual(detail['amount_mentions'][0]['role'],'award')
        self.assertIsNone(detail['amount_cny'])

    def test_multiple_lots_not_flattened(self):
        html = '''<title>医院信息化服务中标公告</title><div class="vF_detail_content">
        <table><tr><td>供应商名称</td><td>甲公司</td></tr><tr><td>供应商名称</td><td>乙公司</td></tr></table>
        <p>第1包中标10万元；第2包中标20万元。详细资料见附件和供应商清单。</p></div>'''
        result = parse_html(html.encode(),'https://www.ccgp.gov.cn/x',self.ccgp,self.rules)['detail']
        self.assertEqual(result['labeled_fields']['供应商名称'],['甲公司','乙公司'])
        self.assertIsNone(result['amount_cny'])
        self.assertEqual(result['lots'],[])

    def test_cross_domain_candidates_never_queued(self):
        html = '''<ul class="vT-srch-result-list-bid"><li><a href="https://evil.invalid/x">医院电子病历中标结果公告</a></li>
        <li><a href="/cggg/a.htm">医院电子病历中标结果公告</a></li></ul>'''
        result = parse_html(html.encode(),'https://www.ccgp.gov.cn/',self.ccgp,self.rules)
        self.assertEqual(len(result['links']),1)
        self.assertEqual(len(result['directory_links']),1)

    def test_failure_reason_classification(self):
        self.assertEqual(failure_code({'status':'blocked','http_status':429}),'rate_limited')
        self.assertEqual(failure_code({'status':'robots_unavailable','error':'timeout'}),'robots_unavailable')
        self.assertEqual(failure_code({'status':'error','error':'TLS verification failed'}),'tls_error')

    def test_durable_failures_and_preflight(self):
        class Denied:
            def __init__(self,**kwargs): pass
            def fetch(self,url,domains):
                return {'requested_url':url,'url':url,'status':'blocked','http_status':403,'error':'HTTP 403'}
            def close(self): pass
        sources = select_sources(self.rules,['ccgp','qcc'])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'run'
            result = collect(self.rules,sources,out,allow_network=True,max_pages=1,fetcher_factory=Denied)
            self.assertEqual(result['status'],'partial')
            fails = json.loads((out/'failures.json').read_text(encoding='utf8'))
            self.assertEqual({f['code'] for f in fails},{'http_forbidden','authorization_required'})
            self.assertEqual(result['attempted_pages'],1)
            self.assertGreater(result['pending_pages'],0)
            with self.assertRaises(ValueError):
                collect(self.rules,sources,out,allow_network=True,fetcher_factory=Denied)

    def test_shanxi_list_selectors_replay(self):
        """2026-10-27.5: 山西公资首页146条结果类链接位于sx_dynamic/cs_tab_box_cont容器。"""
        source = select_sources(self.rules, ['ggzy_shanxi'])[0]
        self.assertEqual(source['profile'], 'shanxi_ggzy')
        html = ('<div class="sx_dynamic"><div class="cs_tab_box_cont cs_show">'
                '<a href="/xwzxtz/1070567.jhtml">山西省公共资源交易平台电子保函服务供应商公开遴选终止公告</a>'
                '</div></div>')
        parsed = parse_html(html.encode(), 'http://prec.sxzwfw.gov.cn/', source, self.rules)
        self.assertEqual(parsed['status'], 'listing')
        self.assertEqual(len(parsed['links']), 1)
        self.assertEqual(parsed['links'][0]['url'], 'http://prec.sxzwfw.gov.cn/xwzxtz/1070567.jhtml')

    def test_provincial_homepage_listing_never_fakes_details(self):
        """2026-10-27.5: 省站首页列表命中只算listing；无正文就不产生detail记录。"""
        fixture = {
            'ggzy_hebei': '<div class="ewb-notice-block"><li class="ewb-notice-item">'
                          '<a href="/hbggfwpt/tzgg/001001/20261022/a.htm">石家庄市政府采购服务中心关于河北省省本级医疗设备采购中标公告</a>',
            'ggzy_xinjiang': '<div class="trade-content"><div class="bd-item"><div class="trade-list"><ul>'
                             '<li class="news-list-item"><a href="/xinjiangggzy_new/jyxx/001001/001001004/20261027/b.htm">克拉玛依市氢气管网设施建设项目初步设计（二次）中标候选人公示</a></li>',
            'ggzy_qinghai': '<div class="bdl"><ul class="proj-list"><li class="proj-item ongoing">'
                            '<a href="/ggzy/projectDetail.html?infoid=abc">[青海省·省本级] [公开招标] 某医院信息化运维项目</a>',
        }
        for sid, html in fixture.items():
            source = select_sources(self.rules, [sid])[0]
            parsed = parse_html(html.encode(), source['seeds'][0], source, self.rules)
            self.assertEqual(parsed['status'], 'listing', sid)
            self.assertIsNone(parsed['detail'], sid)
            self.assertTrue(parsed['links'], sid)

    def test_shanxi_detail_title_date_body(self):
        """2026-10-27.5: 山西详情标题/日期/正文选择器来自真实详情HTML。"""
        source = select_sources(self.rules, ['ggzy_shanxi'])[0]
        html = ('<div class="cs_twoC_box"><div class="cs_xq_content">'
                '<p class="cs_title_P1">山西省公共资源交易平台电子保函服务供应商公开遴选终止公告</p>'
                '<p class="cs_title_P3">发布日期：2026-07-02 15:27</p>'
                + '<p>某医院电子保函服务项目详情陈述。</p>' * 12 + '</div></div>')
        record = parse_html(html.encode(), 'https://prec.sxzwfw.gov.cn/xwzxtz/1070567.jhtml', source, self.rules)['detail']
        self.assertIsNotNone(record)
        self.assertEqual(record['title'], '山西省公共资源交易平台电子保函服务供应商公开遴选终止公告')
        self.assertEqual(record['published_at'], '2026-07-02')
        self.assertEqual(record['stage'], 'cancellation')

    def test_access_denial_stops_remaining_seeds(self):
        class Denied:
            def __init__(self,**kwargs):pass
            def fetch(self,url,domains):
                return {'requested_url':url,'url':url,'status':'blocked','http_status':429,'error':'HTTP 429'}
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run'
            summary=collect(self.rules,[self.ccgp],out,allow_network=True,max_pages=4,fetcher_factory=Denied)
            self.assertEqual(summary['attempted_pages'],1)
            pending=json.loads((out/'pending.json').read_text(encoding='utf8'))
            self.assertEqual(pending[0]['reason'],'source_stopped:rate_limited')
            self.assertTrue((out/'scope.json').is_file())


if __name__ == '__main__':
    unittest.main()
