from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import extractor as e
import apply_verified_reviews as a


class VerifiedReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def case(self,project='服务器采购',buyer='示范医院',extra=''):
        title='示范医院'+project+'中标公告'
        text=('发布时间：2026-06-05\n采购人：'+buyer+'\n项目名称：'+project+
              '\n项目编号：A-001\n三、采购公告发布日期：2026年6月2日\n四、中标信息\n'
              '供应商名称：示范科技有限公司\n中标金额：10000元\n五、主要标的信息\n'+project+'\n'+extra)
        raw=('<html><title>'+title+'</title><article><h1>'+title+'</h1>'+''.join('<p>'+line+'</p>' for line in text.splitlines())+'</article></html>').encode()
        path=self.base/'raw.html';path.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
        page={'url':'https://example.org/notice/1.html','title':title,'raw_path':str(path),'sha256':sha,
              'hospital_entities':[{'id':'1','name':'示范医院','province':'江苏省'}],
              'date':'2026-06-05','date_basis':'exact_listing_row','task_id':'S00001','status':'ok'}
        review={'url':page['url'],'raw_sha256':sha,'current_date':'2026-06-05',
                'current_date_evidence':{'kind':'body_text','path':str(path),'sha256':sha,'quote':'发布时间：2026-06-05'},
                'prior_publication_quotes':['采购公告发布日期：2026年6月2日']}
        excluded={'网址':page['url'],'未纳入原因':'日期冲突：2026-06-02；2026-06-05','原文路径':str(path)}
        return page,review,excluded

    def apply_one(self,page,review,excluded):
        return a.apply_reviews([page],[],[excluded],{},[review],[],self.base)

    def test_verified_reference_date_preserves_other_gates_and_receipt(self):
        page,review,excluded=self.case()
        self.assertIsNone(e.extract_one(page,self.base,'digital')[0])
        rows,remaining,summary,dedup,receipts=self.apply_one(page,review,excluded)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['时间'],'2026-06-05')
        self.assertEqual(rows[0]['中标金额（万元）'],1.0)
        self.assertFalse(remaining);self.assertEqual(receipts[0]['original_exclusions'],[excluded])
        self.assertEqual(summary['verified_date_review_rows'],1)
        self.assertIn('采购公告发布日期',rows[0]['日期依据'])
        again=a.apply_reviews([page],rows,remaining,summary,[review],[],self.base,previous_dedup=dedup)
        self.assertEqual(len(again[0]),1);self.assertEqual(again[4][0]['status'],'already_present_verified')

    def test_wrong_sha_does_not_release_the_excluded_row(self):
        page,review,excluded=self.case();review['raw_sha256']='0'*64
        rows,remaining,_,_,receipts=self.apply_one(page,review,excluded)
        self.assertFalse(rows);self.assertEqual(remaining,[excluded]);self.assertEqual(receipts[0]['status'],'rejected')

    def test_non_it_and_external_buyer_stay_excluded(self):
        for kwargs in [{'project':'医用耗材采购'},{'buyer':'外地医院'}]:
            with self.subTest(kwargs=kwargs):
                page,review,excluded=self.case(**kwargs)
                rows,remaining,_,_,receipts=self.apply_one(page,review,excluded)
                self.assertFalse(rows);self.assertEqual(remaining,[excluded])
                self.assertIn('Other extraction gate rejected',receipts[0]['reason'])

    def test_unreviewed_conflicting_publication_date_stays_excluded(self):
        page,review,excluded=self.case(extra='发布时间：2026-06-04')
        rows,remaining,_,_,receipts=self.apply_one(page,review,excluded)
        self.assertFalse(rows);self.assertEqual(remaining,[excluded])
        self.assertIn('Other unresolved',receipts[0]['reason'])

    def test_date_function_always_restored(self):
        page,review,_=self.case();original=e.publication_date
        with patch.object(e,'extract_one',side_effect=RuntimeError('test exception')):
            with self.assertRaises(RuntimeError):a.extract_verified_date(page,self.base,review)
        self.assertIs(e.publication_date,original)

    def test_evidence_quote_and_range_are_enforced(self):
        page,review,_=self.case();review['current_date_evidence']['quote']='发布时间：2026-06-06'
        with self.assertRaises(ValueError):a.extract_verified_date(page,self.base,review)
        page,review,_=self.case()
        with self.assertRaises(ValueError):a.extract_verified_date(page,self.base,review,since='2026-07-01')

    def test_buyer_quote_must_be_actual_body_and_same_buyer(self):
        page,review,_=self.case();row,_=a.extract_verified_date(page,self.base,review)
        quote=page['title'];old='医院采购主体原文：'+quote+' 发布时间：2026年06月05日'
        row['采购人依据']=old
        field={'url':page['url'],'raw_sha256':page['sha256'],'field':'采购人依据','old_value':old,
               'body_quote':quote,'new_value':'医院采购主体原文：'+quote}
        self.assertEqual(a.corrected_buyer_quote(row,page,self.base,field)['采购人依据'],'医院采购主体原文：'+quote)
        field['body_quote']='示范医院虚构采购公告';field['new_value']='医院采购主体原文：'+field['body_quote']
        with self.assertRaises(ValueError):a.corrected_buyer_quote(row,page,self.base,field)

    def test_existing_dedup_evidence_is_not_lost(self):
        primary={'网址':'https://www.ggzy.gov.cn/a.html','公告ID':'a','原文SHA256':'a'*64,'原文路径':'a'}
        alias={'网址':'https://www.ggzy.gov.cn/b.html','公告ID':'b','原文SHA256':'a'*64,'原文路径':'b'}
        evidence={'key':{'sha256':'a'*64},'primary':primary,'aliases':[alias],'rule':'verified'}
        row={**primary,'采集来源':'历史原文'}
        kept=a.combine_dedup_evidence([evidence],[],[row])
        self.assertEqual(kept,[evidence]);self.assertIn(alias['网址'],row['采集来源'])

    def test_all_individually_reviewed_real_pages(self):
        base=Path(__file__).parent
        pages_file=base/'run/audit-preview-input/pages.json'
        if not pages_file.exists():self.skipTest('Task-local snapshot is absent')
        pages={e.canonical_url(p['url']):p for p in e.read_json(pages_file)}
        for review in a.review_items(e.read_json(base/'review/date-reference-reviews.json')):
            with self.subTest(url=review['url']):
                row,reason=a.extract_verified_date(pages[e.canonical_url(review['url'])],base,review)
                self.assertEqual(reason,'');self.assertEqual(row['时间'],review['current_date'])
        for review in a.review_items(e.read_json(base/'review/field-evidence-reviews.json')):
            page=pages[e.canonical_url(review['url'])];row,reason=e.extract_one(page,base,'digital')
            self.assertEqual(reason,'')
            self.assertEqual(a.corrected_buyer_quote(row,page,base,review)['采购人依据'],review['new_value'])


if __name__=='__main__':unittest.main()
