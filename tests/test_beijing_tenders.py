"""Offline regressions for the experimental adapter's factual boundaries."""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import beijing_tenders as bt

class BeijingTenderTests(unittest.TestCase):
    def write(self,folder,name,value):
        p=folder/name;p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return str(p)

    def roster(self):
        return [{'id':1,'name':'示例医院','level':'一级','category':'综合','district':'东城区'}]

    def record(self):
        return {'hospital_id':1,'date':'2025-01-01','project_name':'HIS','url':'https://example.org/notice',
                'quote':'公告正文含HIS采购及中标金额','announcement_type':'中标公告','winner':'甲公司',
                'amount_wan':12,'amount_quote':'中标金额12万元','review_status':'reviewed'}

    def test_url_date_is_not_a_publication_date(self):
        rows=bt.portal_items('<li><a href="https://example.org/t20250101_1.htm">示例医院HIS</a>无日期</li>')
        self.assertEqual(rows[0]['date'],'')

    def test_visible_list_date_is_labelled_unverified(self):
        rows=bt.portal_items('<li><a href="https://example.org/t20250101_1.htm">示例医院HIS</a>发布时间：2024-9-2</li>')
        self.assertEqual(rows[0]['date'],'2024-09-02')
        self.assertIn('待正文核实',rows[0]['date_source'])

    def test_correction_is_not_classified_as_award(self):
        self.assertEqual(bt.parse_notice('<p>公告正文</p>','示例中标结果公告更正公告')['announcement_type'],'更正公告')

    def test_extract_keeps_unknown_fields_and_relation_pending(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);out=folder/'out'
            args=Namespace(roster=self.write(folder,'roster.json',self.roster()),
                           hits=self.write(folder,'hits.json',[{'hospital_id':1,'title':'示例医院HIS中标公告',
                                'url':'https://example.org/t20260101_1.htm','date':'2026-01-01'}]),output=str(out))
            html='<p>项目名称：HIS</p><p>采购人信息</p><p>名称：上级单位</p>'
            with patch.object(bt,'cached',return_value=html),contextlib.redirect_stdout(io.StringIO()):bt.cmd_extract(args)
            r=json.loads((out/'records.json').read_text(encoding='utf-8'))[0]
            self.assertEqual(r['date'],'');self.assertEqual(r['review_status'],'pending')
            self.assertIn('关系待核实',r['source_note']);self.assertNotIn('举办/隶属关系',r['source_note'])
            self.assertIn('未解析到',r['source_note']);self.assertNotIn('未开标',r['source_note'])

    def test_extract_does_not_fill_missing_buyer_from_roster(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);out=folder/'out'
            args=Namespace(roster=self.write(folder,'roster.json',self.roster()),
                           hits=self.write(folder,'hits.json',[{'hospital_id':1,'title':'示例医院HIS招标公告',
                                'url':'https://example.org/notice','date':'2026-01-01'}]),output=str(out))
            with patch.object(bt,'cached',return_value='<p>发布时间：2025年2月3日</p><p>项目名称：HIS</p>'),contextlib.redirect_stdout(io.StringIO()):bt.cmd_extract(args)
            r=json.loads((out/'records.json').read_text(encoding='utf-8'))[0]
            self.assertEqual(r['purchaser'],'');self.assertEqual(r['date'],'2025-02-03')

    def export(self,folder,records,roster=True):
        args=Namespace(roster=self.write(folder,'roster.json',self.roster()) if roster else None,
                       records=self.write(folder,'input.json',records),output=str(folder/'out'),
                       since='2024-01-01',until='2026-10-27')
        with contextlib.redirect_stdout(io.StringIO()):bt.cmd_export(args)
        return json.loads((folder/'out'/'records.validated.json').read_text(encoding='utf-8')),json.loads((folder/'out'/'records.needs_review.json').read_text(encoding='utf-8'))

    def test_export_requires_roster(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'roster'):self.export(Path(d),[self.record()],roster=False)

    def test_pending_draft_is_not_exported_as_verified(self):
        r=self.record();r['review_status']='pending'
        with tempfile.TemporaryDirectory() as d:
            good,pending=self.export(Path(d),[r]);self.assertEqual(good,[]);self.assertEqual(len(pending),1)

    def test_reviewed_records_still_require_date_and_award_stage(self):
        a=self.record();a['date']='2023-12-01'
        b=self.record();b['announcement_type']='招标公告';b['amount_wan']=None
        c=self.record();c['hospital_id']=999
        with tempfile.TemporaryDirectory() as d:
            good,pending=self.export(Path(d),[a,b,c]);self.assertEqual(good,[]);self.assertEqual(len(pending),3)

    def test_reviewed_valid_record_keeps_legacy_csv_filename(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);good,pending=self.export(folder,[self.record()])
            self.assertEqual(len(good),1);self.assertEqual(pending,[])
            with (folder/'out'/'records.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
            self.assertEqual(rows[0],bt.HEADERS);self.assertEqual(rows[1][5],'12.0')

if __name__=='__main__':unittest.main()
