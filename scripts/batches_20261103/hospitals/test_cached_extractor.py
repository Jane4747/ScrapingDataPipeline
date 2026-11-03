import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import cached_extractor as cached

class EvidenceCacheTests(unittest.TestCase):
    def test_reuses_only_when_evidence_and_review_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'raw.html';raw.write_text('first evidence',encoding='utf-8')
            page={'url':'https://example.org/item','raw_path':str(raw),'title':'采购公告'}
            task=(page,str(root),'digital',None)
            with patch.dict(os.environ,{'SIXPROVINCE_EXTRACT_CACHE':str(root/'cache'),'SIXPROVINCE_EXTRACTOR_SHA':cached.CODE_SHA}):
                with patch.object(cached,'ORIGINAL_EXTRACT_TASK',return_value=({'verified':True},'')) as extract:
                    self.assertEqual(cached.cache_extract_task(task)[0],{'verified':True})
                    cached.cache_extract_task(task);self.assertEqual(extract.call_count,1)
                    raw.write_text('changed evidence at the same URL',encoding='utf-8')
                    cached.cache_extract_task(task);self.assertEqual(extract.call_count,2)
                    cached.cache_extract_task((*task[:3],{'decision':'exclude','quote':'changed evidence'}))
                    self.assertEqual(extract.call_count,3)
                    raw2=root/'attachment.txt';raw2.write_text('software scope',encoding='utf-8')
                    page['attachments']=[{'text_path':str(raw2)}]
                    cached.cache_extract_task(task);self.assertEqual(extract.call_count,4)
                    raw2.write_text('different procurement scope',encoding='utf-8')
                    cached.cache_extract_task(task);self.assertEqual(extract.call_count,5)
    def test_rejects_code_change_during_process_start(self):
        with patch.dict(os.environ,{'SIXPROVINCE_EXTRACT_CACHE':'unused','SIXPROVINCE_EXTRACTOR_SHA':'different'}):
            with self.assertRaisesRegex(RuntimeError,'changed'):
                cached.cache_extract_task(({},'.','digital',None))

if __name__=='__main__':unittest.main()
