import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hospital_official_channels import build_registry, make_registry


class OfficialChannelsTests(unittest.TestCase):
    def setUp(self):
        self.roster = [{'id': 1, 'name': '甲医院'}, {'id': 2, 'name': '乙医院'}]

    def test_every_hospital_present_unknown_is_not_absence_and_queries_are_only_plans(self):
        rows, scope = make_registry(self.roster, [])
        self.assertEqual([r['hospital_id'] for r in rows], [1, 2])
        self.assertEqual(rows[0]['review_status'], 'not_checked')
        self.assertEqual(rows[0]['channels'], [])
        self.assertEqual(scope['hospitals_not_checked'], 2)
        self.assertEqual(scope['queries_executed_by_this_command'], 0)
        self.assertTrue(all(r['execution_status'] == 'plan_only' for r in rows))

    def test_verified_homepage_does_not_create_procurement_channel(self):
        rows, scope = make_registry(self.roster, [{'hospital_name': '甲医院', 'website_url': 'https://example.org/',
            'official_identity_status': 'verified', 'verification_source_url': 'https://example.org/about'}])
        channel = rows[0]['channels'][0]
        self.assertIsNone(channel['procurement_channel_url'])
        self.assertEqual(channel['channel_status'], 'not_checked')
        self.assertEqual(scope['verified_identity_hospitals'], 1)
        self.assertEqual(scope['located_procurement_channel_hospitals'], 0)

    def test_multiple_channels_preserved_and_parent_notice_not_assumed_hospital_use(self):
        rows, _ = make_registry(self.roster, [
            {'hospital_id': 1, 'site_relation': 'parent_hospital', 'website_url': 'https://parent.example.org/',
             'notice_examples': [{'url': 'https://parent.example.org/notice', 'title': '集团采购'}]},
            {'hospital_id': 1, 'site_relation': 'hospital', 'website_url': 'https://hospital.example.org/'}])
        self.assertEqual(len(rows[0]['channels']), 2)
        self.assertIsNone(rows[0]['channels'][0]['notice_examples'][0]['applies_to_hospital'])

    def test_rejects_unknown_or_ambiguous_hospital(self):
        with self.assertRaises(ValueError): make_registry(self.roster, [{'hospital_id': 3}])
        with self.assertRaises(ValueError): make_registry(self.roster, [{'hospital_name': '未列医院'}])
        with self.assertRaises(ValueError): make_registry(self.roster, [{'hospital_id': 1, 'hospital_name': '乙医院'}])

    def test_identity_and_located_channel_need_supporting_fields(self):
        with self.assertRaises(ValueError):
            make_registry(self.roster, [{'hospital_id': 1, 'official_identity_status': 'verified', 'website_url': 'https://example.org/'}])
        with self.assertRaises(ValueError):
            make_registry(self.roster, [{'hospital_id': 1, 'channel_status': 'located'}])

    def test_general_notice_not_promoted_and_parent_channel_counted_separately(self):
        rows, scope = make_registry(self.roster, [
            {'hospital_id': 1, 'website_url': 'https://hospital.example.org/', 'site_relation': 'hospital',
             'official_identity_status': 'verified', 'verification_source_urls': ['https://hospital.example.org/about'],
             'channel_status': 'not_located', 'other_column_urls': ['https://hospital.example.org/news'], 'other_column_name': '通知公告'},
            {'hospital_id': 1, 'website_url': 'https://parent.example.org/', 'site_relation': 'university',
             'procurement_channel_url': 'https://parent.example.org/tenders', 'channel_status': 'located'},
            {'hospital_id': 2, 'website_url': 'https://old.example.org/', 'site_relation': 'hospital',
             'official_identity_status': 'verified_historical_reference'}])
        self.assertEqual(scope['hospital_level_verified_identity_hospitals'], 1)
        self.assertEqual(scope['hospital_level_located_procurement_hospitals'], 0)
        self.assertEqual(scope['upstream_located_procurement_hospitals'], 1)
        self.assertEqual(rows[0]['channels'][0]['other_column_name'], '通知公告')
        self.assertEqual(rows[0]['channels'][0]['other_column_urls'], ['https://hospital.example.org/news'])

    def test_output_is_new_and_inputs_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); roster = root / 'roster.json'; verified = root / 'verified.json'; out = root / 'new'
            roster.write_text(json.dumps(self.roster), encoding='utf-8'); verified.write_text('[]', encoding='utf-8')
            original = roster.read_bytes()
            scope = build_registry(roster, verified, out)
            self.assertEqual(scope['hospital_count'], 2)
            self.assertEqual(roster.read_bytes(), original)
            with self.assertRaises(ValueError): build_registry(roster, verified, out)
            self.assertTrue((out / 'hospital_official_channels.json').is_file())


if __name__ == '__main__':
    unittest.main()
