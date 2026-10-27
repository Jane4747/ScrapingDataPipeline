import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tender_audit import audit_bundle


class AuditTests(unittest.TestCase):
    def make_bundle(self,root):
        files={
            'hospital_roster.json':[{'id':1,'name':'示例医院'}],
            'hospital_search_log.json':[{'hospital_id':1,'queries':['示例医院 HIS'], 'evidence_files':['evidence/query.json']}],
            'records.validated.json':[], 'candidate_notices.json':[],
            'collection_scope.json':{'since':'2024-01-01','until':'2026-10-27','query_count':1},
            'evidence/query.json':{'queries':[{'q':'示例医院 HIS'}],'result':[]}}
        for name,value in files.items():self.save(root,name,value)
    def save(self,root,name,value):
        path=Path(root)/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    def test_zero_hits_is_not_fetch_failure(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_bundle(root);r=audit_bundle(root,1)
            self.assertEqual(r['status'],'passed');self.assertEqual(r['hospitals_without_retained_notices'],1)
    def test_planned_query_cannot_count_as_executed(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_bundle(root);self.save(root,'evidence/query.json',{'queries':[{'q':'别的查询'}]})
            r=audit_bundle(root,1);self.assertEqual(r['queries_verified_in_evidence'],0)
            self.assertIn('query_not_in_evidence',[x['kind'] for x in r['errors']])
    def test_missing_hospital_is_coverage_error(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_bundle(root);self.save(root,'hospital_roster.json',[{'id':1},{'id':2}])
            self.assertIn('roster_coverage',[x['kind'] for x in audit_bundle(root,1)['errors']])
    def test_evidence_must_stay_inside_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_bundle(root)
            self.save(root,'hospital_search_log.json',[{'hospital_id':1,'queries':['示例医院 HIS'],'evidence_files':['../secret.json']}])
            self.assertIn('outside_bundle',[x['kind'] for x in audit_bundle(root,1)['errors']])
    def test_missing_evidence_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_bundle(root);(Path(root)/'evidence/query.json').unlink()
            self.assertIn('missing_evidence_file',[x['kind'] for x in audit_bundle(root,1)['errors']])


if __name__=='__main__':unittest.main()
