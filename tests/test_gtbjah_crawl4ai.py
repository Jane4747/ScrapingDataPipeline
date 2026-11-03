import unittest
from datetime import datetime, timezone
from scripts.gtbjah_crawl4ai import parse_tables, pubdate

class HospitalCollectionTests(unittest.TestCase):
    def test_publication_date_uses_shanghai(self):
        value=datetime(2023,12,31,16,30,tzinfo=timezone.utc).timestamp()*1000
        self.assertEqual(pubdate(value),'2024-01-01')
    def test_unknown_publication_stays_unknown(self):
        self.assertEqual(pubdate(None),'')
        self.assertEqual(pubdate(0),'')
    def test_nested_layout_table_does_not_duplicate_project(self):
        html='<table><tr><td><table><tr><th>项目名称</th><th>成交供应商</th></tr><tr><td>医保<span>数据</span>接口</td><td>甲公司</td></tr></table></td></tr></table>'
        tables=parse_tables(html)
        self.assertEqual(len(tables),1)
        self.assertEqual(tables[0]['rows'][1],['医保数据接口','甲公司'])
    def test_chinese_inline_spans_preserve_project_identity(self):
        tables=parse_tables('<table><tr><td>病案<span>电子化</span>系统</td><td>成<span>交</span>供应商：甲公司</td></tr></table>')
        self.assertEqual(tables[0]['rows'][0][0],'病案电子化系统')
        self.assertEqual(tables[0]['rows'][0][1],'成交供应商：甲公司')

if __name__=='__main__':unittest.main()
