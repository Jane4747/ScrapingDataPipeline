import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import collector as c
import select_resume as resume
import run_batch as batch
from collector import extract_listing,next_pages,canonical,access_challenge
class ListingTests(unittest.TestCase):
    def test_single_row_date_is_not_borrowed(self):
        raw='<ul><li><a href="a.html">医院信息系统采购公告</a><span>2026-10-20</span></li><li><a href="b.html">医院耗材采购公告</a></li></ul>'.encode()
        rows={r['url']:r for r in extract_listing(raw,'https://example.org/list.html')}
        self.assertEqual(rows['https://example.org/a.html']['date'],'2026-10-20')
        self.assertEqual(rows['https://example.org/b.html']['date'],'')
    def test_only_observed_next_in_same_domain(self):
        raw='<a href="2.html">下一页</a><a href="999.html">末页</a><a href="https://other.org/p">下一页</a>'.encode()
        self.assertEqual(next_pages(raw,'https://example.org/1.html'),['https://example.org/2.html'])
    def test_detail_without_it_title_is_still_discovered(self):
        raw='<li><a href="a.html">医疗设备采购公告</a></li>'.encode()
        self.assertEqual(len(extract_listing(raw,'https://example.org/')),1)
    def test_truncated_procurement_title_keeps_exact_row_date(self):
        raw='<title>招标信息</title><li><a href="item.html">某市中医院2026年第...</a><span>2026-10-20</span></li>'.encode()
        rows=extract_listing(raw,'https://example.org/zhaobiao/')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['date'],'2026-10-20')
        self.assertTrue(rows[0]['procurement_context'])
    def test_regular_news_not_promoted_to_procurement(self):
        raw='<title>医院新闻</title><li><a href="item.html">医院慰问退休老干部</a><span>2026-10-20</span></li>'.encode()
        self.assertEqual(extract_listing(raw,'https://example.org/news/'),[])
    def test_date_inside_announcement_anchor(self):
        raw='<div><a href="a.html"><span>信息系统采购公示</span><span class="time">2025-10-11 14:04</span></a><a href="b.html">其他采购公告</a></div>'.encode()
        rows=extract_listing(raw,'https://example.org/notice/')
        self.assertEqual(rows[0]['date'],'2025-10-11')
        self.assertEqual(rows[0]['title'],'信息系统采购公示')
        self.assertEqual(rows[1]['date'],'')
    def test_challenge_is_not_treated_as_readable_announcement(self):
        self.assertTrue(access_challenge({'raw':b"<script>var arg1='1a23b4567890abcdef123456789';</script>",'text':''}))
        self.assertFalse(access_challenge({'raw':b'<html>normal</html>','text':'某医院采购公告正文'}))
    def test_observed_www_alias_does_not_include_other_subdomains(self):
        raw='<li><a href="https://www.example.org/a.html">信息系统采购公告</a><span>2025-01-02</span></li><a href="https://other.example.org/b.html">软件采购公告</a><a href="https://www.example.org/2.html">下一页</a>'.encode()
        rows=extract_listing(raw,'https://example.org/list.html')
        self.assertEqual([r['url'] for r in rows],['https://www.example.org/a.html'])
        self.assertEqual(rows[0]['date'],'2025-01-02')
        self.assertEqual(next_pages(raw,'https://example.org/list.html'),['https://www.example.org/2.html'])
    def test_constant_next_control_is_extracted_without_running_script(self):
        raw='''<a href="" onclick="queryArticleByCondition(this,\'/notice/2.html\')">下一页</a><a href="" onclick="queryArticleByCondition(this,buildUrl())">下一页</a>'''.encode()
        self.assertEqual(next_pages(raw,'https://example.org/notice/1.html'),['https://example.org/notice/2.html'])

class TargetedContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        c.write_json(self.root/'contract.json',{'since':'2024-01-01','until':'2026-11-03','min_delay_seconds':0})
        self.entry={'task_id':'S00001','hospital':'测试医院','hospital_ids':'1',
                    'url':'https://example.org/list.html','entry_kind':'procurement_column'}

    def tearDown(self):self.temp.cleanup()

    def item(self,tail,title='医院信息系统采购公告'):
        return {'url':'https://example.org/'+tail,'title':title,'date':'2026-10-20','date_basis':'exact_listing_row'}

    def make_collector(self,targeted=True):
        args=SimpleNamespace(output=str(self.root),since='2024-01-01',until='2026-11-03',scope='digital',
                             max_site_seconds=120,max_list_pages=3,max_new_details=20,
                             details_only=targeted,digital_titles_only=targeted)
        directory=self.root/'sites'/'S00001';directory.mkdir(parents=True)
        items=[self.item(t) for t in ['new.html','ok.html','blocked.html','unsupported.html','twice.html','once.html']]
        items.append(self.item('clinical.html','医院耗材采购公告'))
        c.write_json(directory/'discovered_items.json',items)
        c.write_json(directory/'pages.json',[{**self.item(t+'.html'),'status':status} for t,status in
                    [('ok','ok'),('blocked','blocked'),('unsupported','unsupported'),('twice','error'),('once','error')]])
        c.write_json(directory/'summary.json',{'failures':[
            {'url':'https://example.org/twice.html','status':'error','error':'timeout'},
            {'url':'https://example.org/twice.html','status':'error','error':'timeout'},
            {'url':'https://example.org/once.html','status':'error','error':'timeout'}]})
        state={'pending':['https://example.org/list2.html'] if targeted else [],'visited':['https://example.org/list.html']}
        c.write_json(directory/'listing_state.json',state)
        raw=directory/'list.html';raw.write_text('<a href="unexpected.html">软件采购公告</a>',encoding='utf-8')
        c.write_json(directory/'list_pages.json',[{'url':self.entry['url'],'status':'ok','raw_path':str(raw)}])
        fake=MagicMock()
        fake.fetch.side_effect=lambda url,domains:{'url':url,'status':'ok','raw':b'<html><p>plain announcement</p></html>',
                                                  'text':'医院公告正文','links':[]}
        with patch.object(c,'Fetcher',return_value=fake):obj=c.Collector(self.entry,args)
        obj.attachments=MagicMock();obj.log=MagicMock()
        return obj,fake,state,directory

    def test_targeted_pass_preserves_lists_and_skips_non_it_and_exhausted_urls(self):
        obj,fetcher,state,directory=self.make_collector()
        with patch.object(c,'extract_listing',side_effect=AssertionError('must not reparse saved lists')):
            obj.run()
        fetched={call.args[0] for call in fetcher.fetch.call_args_list}
        self.assertEqual(fetched,{'https://example.org/new.html','https://example.org/once.html'})
        self.assertEqual(c.read_json(directory/'listing_state.json'),state)
        summary=c.read_json(directory/'summary.json')
        self.assertEqual(summary['list_requests_this_pass'],0)
        self.assertEqual(summary['unfetched_non_digital_titles'],1)
        self.assertEqual(summary['skipped_details'],{'ok':1,'blocked':1,'unsupported':1,'retry_limit':1})
        self.assertIn('pending_lists_not_visited_in_details_only_pass',summary['gaps'])
        self.assertIn('non_digital_titles_not_fetched_in_targeted_pass',summary['gaps'])
        self.assertIn('detail_retry_limit_reached',summary['gaps'])
        self.assertFalse(summary['coverage_complete'])

    def test_default_still_fetches_non_it_titles_and_reparses_saved_lists(self):
        obj,fetcher,state,directory=self.make_collector(targeted=False)
        with patch.object(c,'extract_listing',return_value=[]) as reparse:
            obj.run()
        reparse.assert_called_once()
        fetched={call.args[0] for call in fetcher.fetch.call_args_list}
        self.assertEqual(fetched,{'https://example.org/new.html','https://example.org/once.html','https://example.org/clinical.html'})
        self.assertEqual(c.read_json(directory/'summary.json')['unfetched_non_digital_titles'],0)

    def test_selector_ignores_pending_lists_non_it_and_twice_failed_in_targeted_mode(self):
        entries=[]
        for tid,items,failures in [('S00001',[self.item('twice.html'),self.item('clinical.html','医院耗材采购公告')],
                                 [{'url':'https://example.org/twice.html','status':'error'}]*2),
                                ('S00002',[self.item('once.html')],[{'url':'https://example.org/once.html','status':'error'}])]:
            entry={**self.entry,'task_id':tid};entries.append(entry);d=self.root/'sites'/tid;d.mkdir(parents=True)
            c.write_json(d/'summary.json',{'failures':failures});c.write_json(d/'discovered_items.json',items)
            c.write_json(d/'listing_state.json',{'pending':['https://example.org/2.html']})
        c.write_json(self.root/'entrances.json',{'entrances':entries})
        with patch.object(resume,'RUN',self.root),patch('sys.argv',['select_resume.py','--details-only','--digital-titles-only']),\
             patch.object(resume,'extract_listing',side_effect=AssertionError('must not reparse')):
            resume.main()
        self.assertEqual(c.read_json(self.root/'continuation-ids.json'),['S00002'])
        manifest=c.read_json(self.root/'continuation-manifest.json')
        self.assertEqual(manifest[0]['retry_limited_candidates'],1)
        self.assertEqual(manifest[0]['unfetched_non_digital_titles'],1)
        self.assertEqual(manifest[0]['pending_lists'],1)
        self.assertIn('non_digital_titles_not_fetched_in_targeted_pass',manifest[0]['targeted_pass_gaps'])
        self.assertIn('detail_retry_limit_reached',manifest[0]['targeted_pass_gaps'])

    def test_batch_forwards_only_requested_flags(self):
        args=SimpleNamespace(list_pages=2,details=3,seconds=30,wave='test',details_only=True,digital_titles_only=True)
        process=MagicMock();process.wait.return_value=0
        with patch.object(batch,'RUN',self.root),patch.object(batch.subprocess,'Popen',return_value=process) as popen:
            batch.execute(self.entry,args)
        command=popen.call_args.args[0]
        self.assertIn('--details-only',command);self.assertIn('--digital-titles-only',command)
        args.details_only=args.digital_titles_only=False;args.wave='default'
        with patch.object(batch,'RUN',self.root),patch.object(batch.subprocess,'Popen',return_value=process) as popen:
            batch.execute(self.entry,args)
        self.assertNotIn('--details-only',popen.call_args.args[0]);self.assertNotIn('--digital-titles-only',popen.call_args.args[0])


if __name__=='__main__':unittest.main()
