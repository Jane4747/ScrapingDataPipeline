import importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('doi_adapter',Path(__file__).with_name('doi_collector.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def test_bibliographic_page_range_is_not_pdf_page_count(self):
        rows=[{'status':'downloaded','pages':8,'pdf_bytes':100},{'status':'no_public_fulltext','pages':'207-214'}]
        self.assertEqual(m.downloaded_totals(rows),{'pages':8,'bytes':100})
    def test_html_pdf_candidates_preserve_queries_and_resolve_relative(self):
        raw=b'<meta name="citation_pdf_url" content="/paper.pdf?version=2"><a href="javascript:bad()">PDF</a>'
        self.assertEqual(m.pdf_links(raw,'https://example.edu/article/1'),['https://example.edu/paper.pdf?version=2'])
    def test_wrong_paper_cannot_be_download_success(self):
        page=type('Page',(),{'extract_text':lambda _: 'An unrelated medical review of lung cancer'})()
        fake=type('Reader',(),{'is_encrypted':False,'pages':[page]})()
        with patch.object(m,'PdfReader',return_value=fake):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):m.identity(b'%PDF-test','Image-Based Visual Servoing for Robot Manipulators','10.1/test')
    def test_not_pdf_rejected_even_if_file_extension_pdf(self):
        with self.assertRaisesRegex(ValueError,'Not a PDF'):m.identity(b'<html>login</html>','Paper','10.1/a')
    def test_mdpi_url_and_repository_fallback(self):
        row={'id':'2023-20','doi':'10.3390/act12060253','venue':'Actuators'}
        rec={'crossref':{'volume':'12'},'work':{'locations':[{'pdf_url':'https://arxiv.org/pdf/2301.01234','is_oa':True}]}}
        result=m.candidates(row,rec,{})
        self.assertIn('actuators-12-00253.pdf',result[0]['url']);self.assertEqual(len(result),2)
    def test_path_characters_are_safe(self):
        self.assertEqual(m.safe(' Paper: A/B?* '),'Paper A B')
    def test_resume_does_not_accept_modified_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'p.pdf').write_bytes(b'changed');(root/'t.txt').write_text('text')
            old={'status':'downloaded','pdf_path':'p.pdf','text_path':'t.txt','pdf_sha256':m.sha(b'original'),'text_sha256':m.sha(b'text')}
            row={'id':'x','doi':'10.1/x','title':'A paper'}
            out=m.collect_one(row,{'work':{'locations':[]},'crossref':{}},{},root,{},old)
            self.assertEqual(out['status'],'no_public_fulltext')
if __name__=='__main__':unittest.main()
