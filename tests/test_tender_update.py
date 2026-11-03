import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pipeline.research.tender_fields import extract_fields, normalize, link_qualifications, QUAL, PREQUAL, HEADERS
from pipeline.research.beijing_ggzy import parse_response, form_for
from pipeline.research.national_ggzy import archive_windows, timeout_parts
from pipeline.research.tender_update import validate_scope, source_lock, summarize
from pipeline.research.zycg import discover


class FieldTests(unittest.TestCase):
    def test_experts_stop_before_fees_and_contacts(self):
        value=extract_fields('<p>五、评审专家名单：</p><p>张某、李某</p><p>六、代理服务收费</p><p>联系方式：王某</p>')
        self.assertEqual(value['评审专家'],'张某、李某')

    def test_qualification_keeps_subclauses_and_stops_before_file_time(self):
        html='<p>二、申请人的资格要求：</p><p>1.满足基本规定。</p><p>2.落实采购政策：专门面向小微企业。</p><p>3.本项目的特定资格要求：具备许可证。</p><p>三、获取招标文件</p><p>2024-01-01</p>'
        value=extract_fields(html,url='https://example.gov.cn/notice')
        self.assertIn('许可证',value[QUAL]);self.assertNotIn('2024-01',value[QUAL])
        self.assertEqual(value[PREQUAL],'')
        self.assertEqual(value['_field_evidence'][QUAL]['url'],'https://example.gov.cn/notice')

    def test_prequalification_title_is_required_for_generic_applicant_section(self):
        html='<p>三、申请人资格要求：</p><p>具有三级资质</p><p>四、资格预审文件的获取</p>'
        value=extract_fields(html,'示例医院信息系统资格预审公告')
        self.assertIn('三级资质',value[PREQUAL])

    def test_no_invented_experts_or_qualifications(self):
        value=normalize({'公告日期':'2024-01-01','项目名称':'项目','相关网页':'https://example.gov.cn'},'央采')
        self.assertEqual(value['评审专家'],'');self.assertEqual(value[QUAL],'')
        self.assertEqual(value['时间'],'2024-01-01');self.assertEqual(len(HEADERS),22)
        self.assertIn('规则标签待核验',value['标签依据'])

    def test_matching_title_alone_cannot_link_qualification(self):
        a={'项目名称':'同名','项目编号':'','招标单位':'医院',QUAL:'要求','时间':'2024-01-01','网址':'a'}
        b={'项目名称':'同名','项目编号':'','招标单位':'医院','时间':'2024-02-01','网址':'b'}
        link_qualifications([a,b]);self.assertFalse(b.get(QUAL))

    def test_conflicting_versions_are_not_silently_joined(self):
        rows=[{'项目编号':'P1','招标单位':'医院','时间':'2024-01-01',QUAL:'甲','网址':'a'},
              {'项目编号':'P1','招标单位':'医院','时间':'2024-01-02',QUAL:'乙','网址':'b'},
              {'项目编号':'P1','招标单位':'医院','时间':'2024-02-01','网址':'c','信息缺口':''}]
        link_qualifications(rows);self.assertFalse(rows[-1].get(QUAL));self.assertIn('多个版本',rows[-1]['信息缺口'])

    def test_future_notice_cannot_supply_prior_award_qualification(self):
        rows=[{'项目编号':'P1','招标单位':'医院','时间':'2025-01-01',QUAL:'甲','网址':'a'},
              {'项目编号':'P1','招标单位':'医院','时间':'2024-02-01','网址':'b'}]
        link_qualifications(rows);self.assertFalse(rows[-1].get(QUAL))

class ContractTests(unittest.TestCase):
    def test_live_export_counts_reconcile_with_accepted_rows(self):
        import contextlib,io
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/'request.json').write_text(json.dumps({'task_id':'test','start':'2024-01-01','end':'2024-12-31'}),encoding='utf-8')
            for source in ['zycg','ggzy_national','ggzy_beijing']:
                folder=p/source;folder.mkdir()
                (folder/'progress.json').write_text(json.dumps({'status':'running','records':999}),encoding='utf-8')
                (folder/'records.json').write_text(json.dumps([{'公告日期':'2024-01-01','项目名称':'example','相关网页':source},{'公告日期':'2023-01-01','项目名称':'outside'}]),encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):summarize(p)
            value=json.loads((p/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(value['records'],3)
            self.assertEqual(sum(r['records'] for r in value['sources']),value['records'])
    def test_timeout_splits_date_window_without_losing_days(self):
        self.assertEqual(timeout_parts({'start':'2024-01-01','end':'2024-01-04'},'AbortError'),[('2024-01-01','2024-01-02'),('2024-01-03','2024-01-04')])

    def test_access_denial_is_never_reclassified_as_timeout(self):
        self.assertEqual(timeout_parts({'start':'2024-01-01','end':'2024-01-04'},'HTTP 403 Forbidden; CAPTCHA'),[])

    def test_single_day_timeout_is_not_split_indefinitely(self):
        self.assertEqual(timeout_parts({'start':'2024-01-01','end':'2024-01-01'},'AbortError'),[])

    def test_historical_api_routing_and_months_have_no_gap(self):
        windows=list(archive_windows('2024-01-01','2026-10-29'))
        self.assertEqual(windows[0],('2024-01-01','2024-01-31','history'))
        self.assertEqual(windows[-1][2],'current')
        from datetime import date,timedelta
        for a,b in zip(windows,windows[1:]):self.assertEqual(date.fromisoformat(a[1])+timedelta(days=1),date.fromisoformat(b[0]))

    def test_invalid_budget_or_reversed_dates_rejected(self):
        with self.assertRaises(ValueError):validate_scope('2025-01-01','2024-01-01','safe-id',3.5,100,100,100)
        with self.assertRaises(ValueError):validate_scope('2024-01-01','2024-02-01','safe-id',0,100,100,100)

    def test_lock_not_stolen_or_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'source.lock').write_text('existing')
            with self.assertRaises(ValueError):
                with source_lock(p):pass
            self.assertEqual((p/'source.lock').read_text(),'existing')

    def test_beijing_json_string_rows_and_missing_schema(self):
        rows,total=parse_response({'result':'[{"title":"医院"}]','total':1})
        self.assertEqual(total,1);self.assertEqual(rows[0]['title'],'医院')
        with self.assertRaises(ValueError):parse_response({'message':'blocked'})
        with self.assertRaises(ValueError):parse_response({'result':'alert(1)','total':1})

    def test_beijing_public_request_has_fixed_date_and_scope(self):
        value=form_for('2024-01-01','2024-01-31','医',1)
        self.assertEqual(value['channel_second'],'jyxxzfcg');self.assertEqual(value['starttime'],'2024-01-01')
        self.assertEqual(value['scope'],'title')

    def test_search_challenge_is_not_empty_success(self):
        class Fake:
            def fetch(self,*args):return {'status':'ok','raw':b'<html><p>access challenge</p></html>'}
        rows,failures=discover(Fake(),'2024-01-01','2024-01-31',2,lambda x:None)
        self.assertEqual(rows,[]);self.assertEqual(failures[0]['code'],'unexpected_response')

    def test_declared_last_page_does_not_request_clamped_duplicate(self):
        html=b'<ul class="vT-srch-result-list-bid"><li><a href="http://example.gov.cn">example</a><span>2024.01.01</span></li></ul><script>Pager({ size: 1, current: 0 });</script>'
        class Fake:
            calls=0
            def fetch(self,*args):self.calls+=1;return {'status':'ok','raw':html}
        fake=Fake();rows,failures=discover(fake,'2024-01-01','2024-01-31',3,lambda x:None)
        self.assertEqual(fake.calls,1);self.assertFalse(failures)

if __name__=='__main__':unittest.main()
