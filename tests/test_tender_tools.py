import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tender_tools import amount_to_wan,validate_record,build_task,read_json
class TenderTests(unittest.TestCase):
    def test_yuan_preserves_cents(self):self.assertEqual(amount_to_wan('1,234,567.89','元'),123.456789)
    def test_missing_not_zero(self):self.assertIsNone(amount_to_wan(None));self.assertEqual(amount_to_wan('0','元'),0)
    def test_unknown_unit_not_guessed(self):
        with self.assertRaises(ValueError):amount_to_wan('10','美元')
    def valid(self):return {'hospital_id':1,'date':'2025-01-01','project_name':'HIS','url':'https://example.org/notice','quote':'结果原文','announcement_type':'中标公告','winner':'甲公司','amount_wan':12,'amount_quote':'中标金额12万元'}
    def test_budget_is_not_award(self):
        r=self.valid();r['announcement_type']='招标公告';self.assertIn('非确定成交结果不得填中标金额',validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1])
    def test_candidates_not_award(self):
        r=self.valid();r['announcement_type']='中标候选人公示';self.assertTrue(validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1])
    def test_date_required_and_roster_bound(self):
        r=self.valid();r['date']='';r['hospital_id']=999;self.assertEqual(len(validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1]),2)
    def test_out_of_range(self):
        r=self.valid();r['date']='2023-12-31';self.assertTrue(validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1])
    def test_redacted_winner_does_not_erase_disclosed_amount(self):
        r=self.valid();r['winner']=None;self.assertFalse(validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1])
    def test_nonaward_winner_rejected_without_amount(self):
        for stage in ['招标公告','单一来源采购意向','中标候选人公示','中标公告更正公告','拟定中标结果']:
            with self.subTest(stage=stage):
                r=self.valid();r['announcement_type']=stage;r['amount_wan']=None
                self.assertIn('非确定成交结果不得填中标单位',validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1])
    def test_award_winner_can_have_no_disclosed_total(self):
        r=self.valid();r['amount_wan']=None
        self.assertFalse(validate_record(r,{1:{}},'2024-01-01','2026-10-26')[1])
    def test_domain_scoped_plan_no_expansion(self):
        with tempfile.TemporaryDirectory() as d:
            build_task([{'url':'https://a.example.org/n1'},{'url':'https://a.example.org/n1'},{'url':'https://b.example.org/n2'}],d,'valid-task','2024-01-01','2026-10-26')
            s=read_json(Path(d)/'sources.json')['sources'];self.assertEqual(len(s),2);self.assertEqual(s[0]['allowed_domains'],['a.example.org']);self.assertEqual(len(s[0]['seeds']),1)
if __name__=='__main__':unittest.main()
