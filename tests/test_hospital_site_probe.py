"""Offline tests for the per-hospital website probe and the workbook writer."""
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from scripts import hospital_site_probe as probe
from scripts import hospital_workbook_writer as writer

CONFIG = probe.read_json(probe.DEFAULT_CONFIG)
ROOT = Path(__file__).resolve().parents[1]


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return str(path)


class PlanTests(unittest.TestCase):
    def test_plan_flags_platform_and_group_hosts(self):
        roster = [
            {'hospital_id': 1, 'hospital_name': '示例医院', 'candidate_hosts': ['example-hospital.org']},
            {'hospital_id': 2, 'hospital_name': '平台占位院', 'candidate_hosts': ['ccgp-beijing.gov.cn']},
            {'hospital_id': 3, 'hospital_name': '集团院区', 'candidate_hosts': ['301hospital.com.cn']},
            {'hospital_id': 4, 'hospital_name': '无候选域名院'},
        ]
        rows = probe.normalize_roster(roster)
        plan, scope = probe.build_plan(rows, CONFIG)
        self.assertEqual(scope['hospital_count'], 4)
        self.assertEqual(scope['network_requests'], 0)
        self.assertEqual(scope['execution_status'], 'plan_only')
        self.assertEqual(plan[1]['targets'][0]['kind'], 'platform_host')
        self.assertFalse(plan[1]['targets'][0]['probe'])
        self.assertTrue(plan[2]['targets'][0]['probe'])
        self.assertEqual(plan[3]['status'], 'no_host')
        self.assertEqual(scope['hospitals_without_hosts'], 1)

    def test_roster_rejects_duplicate_and_missing_name(self):
        with self.assertRaises(ValueError):
            probe.normalize_roster([{'hospital_id': 1, 'hospital_name': 'A'}, {'hospital_id': 1, 'hospital_name': 'B'}])
        with self.assertRaises(ValueError):
            probe.normalize_roster([{'hospital_id': 2, 'hospital_name': '  '}])

    def test_extract_columns_ranks_procurement_links_first(self):
        html = """
        <html><body>
        <a href="/Html/News/Columns/12/1.html">招聘信息</a>
        <a href="/Html/News/Columns/88/1.html">招标采购</a>
        <a href="/info/2051/3022.htm">通知公告</a>
        <a href="/cg/index.htm">中标公示</a>
        </body></html>
        """
        candidates = probe.extract_columns(html, 'https://hospital.example.org/', CONFIG, 400)
        anchors = [item['anchor'] for item in candidates]
        self.assertIn('招标采购', anchors)
        self.assertNotIn('招聘信息', anchors)
        self.assertTrue(candidates[0]['score'] >= candidates[-1]['score'])

    def test_probe_target_skips_non_probable_hosts(self):
        record, requests = probe.probe_target({'host': 'ccgp.gov.cn', 'kind': 'platform_host', 'probe': False,
                                               'reason': 'Platform host.'}, CONFIG)
        self.assertEqual(requests, 0)
        self.assertEqual(record['status'], 'skipped')


class WriterTests(unittest.TestCase):
    def build_workbook(self, path):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '05-全量明细'
        sheet['C4'] = '医院名称'
        sheet['S4'] = '招标采购网址'
        sheet['C5'] = '示例医院'
        sheet['C6'] = '未核实医院'
        sheet['S5'] = '旧平台入口'
        workbook.save(path)
        return str(path)

    def build_records(self, path):
        records = [
            {'hospital_id': 1, 'hospital_name': '示例医院', 'level': '三级', 'owner': '市属',
             'homepage_url': 'https://hospital.example.org/', 'channel_status': 'found',
             'top_candidate': {'url': 'https://hospital.example.org/zbcg.htm', 'anchor': '招标采购', 'score': 6},
             'evidence': [{'target_url': 'https://hospital.example.org/', 'status': 'ok', 'http_status': 200}]},
            {'hospital_id': 2, 'hospital_name': '未核实医院', 'level': '二级', 'owner': '民营',
             'homepage_url': None, 'channel_status': 'unknown',
             'evidence': [{'target_url': 'https://missing.example.org/', 'status': 'access_failed'}]},
        ]
        write_json(path, records)
        return str(path)

    def test_dry_run_reports_changes_without_touching_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = self.build_workbook(Path(tmp) / 'roster.xlsx')
            records = self.build_records(Path(tmp) / 'records.json')
            before = Path(workbook).read_bytes()
            args = writer.argparse.Namespace(
                workbook=workbook, sheet='05-全量明细', records=records,
                config=str(probe.DEFAULT_CONFIG), head_row=4, name_col='C', level_col='D', owner_col='H',
                homepage_col='T', status_col='U', channel_col='S', update_channel=True,
                list_sheet='06-未找到待核查清单', apply=False, output=None, no_backup=False)
            original_parse = writer.argparse.ArgumentParser.parse_args
            writer.argparse.ArgumentParser.parse_args = lambda self, argv=None: args
            try:
                self.assertEqual(writer.main([]), 0)
            finally:
                writer.argparse.ArgumentParser.parse_args = original_parse
            self.assertEqual(Path(workbook).read_bytes(), before)
            self.assertFalse((Path(tmp) / 'roster.xlsx.bak').exists())

    def test_apply_writes_columns_rebuilds_list_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = self.build_workbook(Path(tmp) / 'roster.xlsx')
            records = self.build_records(Path(tmp) / 'records.json')
            args = writer.argparse.Namespace(
                workbook=workbook, sheet='05-全量明细', records=records,
                config=str(probe.DEFAULT_CONFIG), head_row=4, name_col='C', level_col='D', owner_col='H',
                homepage_col='T', status_col='U', channel_col='S', update_channel=True,
                list_sheet='06-未找到待核查清单', apply=True, output=None, no_backup=False)
            original_parse = writer.argparse.ArgumentParser.parse_args
            writer.argparse.ArgumentParser.parse_args = lambda self, argv=None: args
            try:
                self.assertEqual(writer.main([]), 0)
            finally:
                writer.argparse.ArgumentParser.parse_args = original_parse
            from openpyxl import load_workbook
            saved = load_workbook(workbook)
            sheet = saved['05-全量明细']
            self.assertTrue(str(sheet['T5'].value).startswith('https://hospital.example.org'))
            self.assertIn('有本级采购栏目', str(sheet['U5'].value))
            self.assertEqual(sheet['S5'].value, 'https://hospital.example.org/zbcg.htm')
            self.assertEqual(sheet['T6'].value, None)
            self.assertIn('未核实', str(sheet['U6'].value))
            listing = saved['06-未找到待核查清单']
            self.assertEqual(listing.max_row, 2)
            self.assertEqual(listing['B2'].value, '未核实医院')
            self.assertTrue((Path(tmp) / 'roster.xlsx.bak').exists())

    def test_missing_sheet_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = self.build_workbook(Path(tmp) / 'roster.xlsx')
            records = self.build_records(Path(tmp) / 'records.json')
            args = writer.argparse.Namespace(
                workbook=workbook, sheet='不存在的表', records=records,
                config=str(probe.DEFAULT_CONFIG), head_row=4, name_col='C', level_col='D', owner_col='H',
                homepage_col='T', status_col='U', channel_col='S', update_channel=False,
                list_sheet=None, apply=False, output=None, no_backup=False)
            original_parse = writer.argparse.ArgumentParser.parse_args
            writer.argparse.ArgumentParser.parse_args = lambda self, argv=None: args
            try:
                self.assertEqual(writer.main([]), 2)
            finally:
                writer.argparse.ArgumentParser.parse_args = original_parse


if __name__ == '__main__':
    unittest.main()
