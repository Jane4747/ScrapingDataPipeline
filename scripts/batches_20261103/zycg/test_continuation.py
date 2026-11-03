import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from continue_zycg import typed_url, bisect_dates, audit_pages, page_info, sha


def page(page_number=1, total=2, kind=7, items=None):
    items = items or [('202601/t20260101_1.htm', 'zbgg'), ('202601/t20260101_2.htm', 'zbgg')]
    links = ''.join(f'<li><a href="http://www.ccgp.gov.cn/cggg/zygg/{stage}/{suffix}">某医院服务器中标公告</a>'
                    '<span>2026.01.01 | 采购人：某医院 | 代理机构： 中央国家机关政府采购中心 中标公告 | 北京 |</span></li>'
                    for suffix, stage in items)
    return (f"<html><script>var bidType = '{kind}';var agentName = '中央国家机关政府采购中心';"
            "var start_time = '2026:01:01';var end_time = '2026:01:31';</script>"
            f'<p>共找到 {total} 条内容</p><ul class="vT-srch-result-list-bid">{links}</ul>'
            f'<script>Pager({{size: {(total + 19) // 20},current: {page_number - 1}}});</script></html>').encode()


class ContinuationTests(unittest.TestCase):
    def test_query_identity_keeps_scope_and_separates_types(self):
        a = parse_qs(urlsplit(typed_url(3, '2024-01-01', '2024-01-31', 7)).query)
        b = parse_qs(urlsplit(typed_url(3, '2024-01-01', '2024-01-31', 11)).query)
        self.assertEqual(a['agentName'], ['中央国家机关政府采购中心'])
        self.assertEqual(a['page_index'], ['3'])
        self.assertEqual(a['start_time'], ['2024:01:01'])
        self.assertEqual(a['bidType'], ['7'])
        self.assertEqual(b['bidType'], ['11'])
        self.assertNotEqual(sha(str(a).encode()), sha(str(b).encode()))

    def test_window_split_covers_leap_day_without_gaps(self):
        self.assertEqual(bisect_dates('2024-02-28', '2024-03-01'), [('2024-02-28', '2024-02-29'), ('2024-03-01', '2024-03-01')])
        self.assertEqual(bisect_dates('2024-02-29', '2024-02-29'), [])

    def test_official_count_and_notice_type_are_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'page-2026-01-01_2026-01-31-0001.html'
            path.write_bytes(page())
            self.assertTrue(audit_pages([path], '2026-01-01', '2026-01-31', 7)['verified'])
            self.assertFalse(audit_pages([path], '2026-01-01', '2026-01-31', 11)['verified'])
            path.write_bytes(page(total=3))
            self.assertFalse(audit_pages([path], '2026-01-01', '2026-01-31', 7)['verified'])

    def test_wrong_result_type_cannot_be_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'page-2026-01-01_2026-01-31-0001.html'
            path.write_bytes(page(items=[('202601/a.htm', 'gkzb'), ('202601/b.htm', 'zbgg')]))
            self.assertFalse(audit_pages([path], '2026-01-01', '2026-01-31', 7)['verified'])

    def test_saved_official_page_contract_supports_7_and_11(self):
        import continue_zycg
        import os
        value = os.environ.get('ZYCG_OFFICIAL_CONTRACT_FIXTURE')
        if not value:
            self.skipTest('Optional saved official page is not included in the code repository')
        source = Path(value)
        text = source.read_text(encoding='utf-8')
        self.assertIn('bidTypeSel(7)">中标公告', text)
        self.assertIn('bidTypeSel(11)">成交公告', text)


class PortablePreparationTests(unittest.TestCase):
    def test_empty_baseline_prepares_typed_month_windows_without_network(self):
        import continue_zycg as module
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'ROOT', Path(directory)), \
             patch.object(module, 'START', '2024-02-28'), patch.object(module, 'END', '2024-03-01'), \
             patch.object(module.ManagedFetcher, '_request', side_effect=AssertionError('offline preparation')):
            runner = module.Runner()
            try:
                runner.prepare()
                self.assertEqual(len(runner.queries), 4)
                self.assertEqual({q['bid_type'] for q in runner.queries}, {7, 11})
                self.assertEqual(module.read(Path(directory)/'records.json'), [])
            finally:
                runner.fetcher.finish()


if __name__ == '__main__':
    unittest.main()
