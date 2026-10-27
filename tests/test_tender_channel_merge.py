import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tender_channel_merge import merge_bundle


class ChannelMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, self.extra, self.out = (self.root / name for name in ('base', 'supplement', 'result'))
        self.base.mkdir()
        self.extra.mkdir()
        self.write(self.base, 'hospital_roster.json', [
            {'id': 1, 'name': '甲医院', 'level': '一级', 'category': '综合', 'district': '甲区'},
            {'id': 2, 'name': '乙医院', 'level': '一级', 'category': '综合', 'district': '乙区'},
        ])
        self.write(self.base, 'hospital_search_log.json', [
            {'hospital_id': 1, 'queries': ['甲医院 HIS'], 'evidence_files': ['evidence/old.json']},
            {'hospital_id': 2, 'queries': ['乙医院 HIS'], 'evidence_files': ['evidence/old.json']},
        ])
        self.write(self.base, 'evidence/old.json', {'queries': ['甲医院 HIS', '乙医院 HIS']})
        self.write(self.base, 'records.validated.json', [])
        self.write(self.base, 'candidate_notices.json', [])
        self.write(self.base, 'collection_scope.json', {'since': '2024-01-01', 'until': '2026-10-27', 'query_count': 2, 'minimum_queries_per_hospital': 1})
        self.write(self.extra, 'evidence/new.json', {'queries': [{'q': '共同病案 系统 采购'}], 'body': '病案系统采购公示'})
        self.write(self.extra, 'records_group.json', [self.record()])
        self.write(self.extra, 'candidates_group.json', [])
        self.write(self.extra, 'search_group.json', [{'hospital_ids': [1, 2], 'queries': ['共同病案 系统 采购'], 'query_count': 1, 'evidence_files': ['evidence/new.json']}])

    def write(self, root, name, value):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def read(self, name):
        return json.loads((self.out / name).read_text(encoding='utf-8'))

    def record(self, **changes):
        row = {'hospital_id': 1, 'hospital_ids': [1, 2], 'project_name': '共用病案系统', 'product': '=HYPERLINK("bad")', 'purchaser': '医院集团', 'date': '2026-10-25', 'announcement_type': '单一来源采购公示', 'url': 'https://example.org/notice/1', 'quote': '甲乙医院共用病案系统', 'winner': None, 'amount_wan': None, 'evidence_files': ['evidence/new.json']}
        row.update(changes)
        return row

    def merge(self, **overrides):
        args = dict(base_dir=self.base, supplement_dir=self.extra, output_dir=self.out, since='2024-01-01', until='2026-10-27')
        args.update(overrides)
        return merge_bundle(**args)

    def test_shared_notice_is_one_row_and_keeps_history_and_csv_safety(self):
        self.write(self.extra, 'records_group.json', [self.record(hospital_ids=[1]), self.record(hospital_id=2, hospital_ids=[2])])
        result = self.merge()
        self.assertEqual((result['records'], result['channel_query_count'], result['channel_searched_hospitals']), (1, 1, 2))
        self.assertEqual((result['query_count'], result['searched_hospitals']), (2, 2))
        row = self.read('records.validated.json')[0]
        self.assertEqual(row['hospital_ids'], [1, 2])
        self.assertIn('甲医院、乙医院', row['hospital_name'])
        self.assertIsNone(row['winner'])
        self.assertIsNone(row['amount_wan'])
        self.assertEqual((self.base / 'hospital_search_log.json').read_bytes(), (self.out / 'hospital_search_log.json').read_bytes())
        with (self.out / '北京一级医院数智化招采信息.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(len(rows[0]), 7)
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertEqual(rows[1][4:6], ['', ''])

    def test_candidate_resolution_preserves_decision_and_original_evidence(self):
        old = self.record(url='https://example.org/candidate', evidence_files=['evidence/old.json'])
        self.write(self.base, 'candidate_notices.json', [old])
        decision = {'candidate_resolutions': [{'record_url': 'https://example.org/notice/1', 'candidate_urls': [old['url']], 'reason': 'Explicit reviewed relationship'}]}
        self.write(self.extra, 'review_decisions.json', decision)
        self.merge()
        self.assertEqual(self.read('candidate_notices.json'), [])
        self.assertEqual(self.read('merge_review.json'), decision)
        self.assertIn('evidence/old.json', self.read('records.validated.json')[0]['evidence_files'])
        self.assertIn(old['url'], self.read('records.validated.json')[0]['additional_urls'])

    def test_delivery_note_is_regenerated_from_current_counts(self):
        old_note = '旧版主表14条，候选28条；已经生成Excel。'
        (self.base / '交付说明.txt').write_text(old_note, encoding='utf-8')
        result = self.merge()
        note = (self.out / '交付说明.txt').read_text(encoding='utf-8')
        self.assertNotIn(old_note, note)
        self.assertIn('合并后主表1条', note)
        self.assertIn('待核、排除或应用消息共0条', note)
        self.assertIn('没有执行网络检索或生成Excel', note)
        self.assertEqual((self.base / '交付说明.txt').read_text(encoding='utf-8'), old_note)
        self.assertEqual(result['workbook_filename'], '北京一级医院数智化招采_渠道补查版.xlsx')

    def test_rejects_query_with_no_saved_execution_evidence(self):
        self.write(self.extra, 'evidence/new.json', {'query': 'different query'})
        with self.assertRaisesRegex(ValueError, 'Query not present'):
            self.merge()
        self.assertFalse(self.out.exists())

    def test_rejects_evidence_path_escape(self):
        self.write(self.extra, 'records_group.json', [self.record(evidence_files=['../private.json'])])
        with self.assertRaisesRegex(ValueError, 'Parent traversal'):
            self.merge()
        self.assertFalse(self.out.exists())

    def test_rejects_unknown_shared_hospital(self):
        self.write(self.extra, 'records_group.json', [self.record(hospital_ids=[1, 999])])
        with self.assertRaisesRegex(ValueError, 'Unknown hospital'):
            self.merge()

    def test_rejects_missing_evidence(self):
        self.write(self.extra, 'records_group.json', [self.record(evidence_files=['evidence/missing.json'])])
        with self.assertRaisesRegex(ValueError, 'Missing evidence'):
            self.merge()

    def test_rejects_same_path_with_changed_evidence(self):
        self.write(self.base, 'evidence/new.json', {'query': 'different content'})
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.merge()

    def test_rejects_award_amount_in_procurement_stage(self):
        self.write(self.extra, 'records_group.json', [self.record(amount_wan=100, amount_quote='预算100万元')])
        with self.assertRaisesRegex(ValueError, 'Invalid accepted record'):
            self.merge()

    def test_rejects_conflicting_awards(self):
        self.write(self.extra, 'records_group.json', [self.record(winner='甲公司'), self.record(winner='乙公司')])
        with self.assertRaisesRegex(ValueError, 'Conflicting winner'):
            self.merge()

    def test_rejects_existing_or_nested_output_and_changed_period(self):
        self.out.mkdir()
        (self.out / 'keep.txt').write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'already exist'):
            self.merge()
        self.assertEqual((self.out / 'keep.txt').read_text(encoding='utf-8'), 'keep')
        with self.assertRaisesRegex(ValueError, 'separate'):
            self.merge(output_dir=self.base / 'nested')
        with self.assertRaisesRegex(ValueError, 'Base scope differs'):
            self.merge(output_dir=self.root / 'other', since='2025-01-01')


if __name__ == '__main__':
    unittest.main()
