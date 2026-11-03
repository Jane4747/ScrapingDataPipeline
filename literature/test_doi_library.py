import hashlib,tempfile,unittest
from pathlib import Path
from doi_library import publish_image
class Tests(unittest.TestCase):
    def test_windows_publish_path_is_short_and_preserves_source_names(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'source';base.mkdir();(base/'source.png').write_bytes(b'original image');(base/'thumb.png').write_bytes(b'preview')
            f={'paper_id':'2026-01','paper_title':'A very long paper title '*15,'label':'Figure 1','caption_title':'An architecture with multiple interconnected modules','file':'source.png','thumbnail':'thumb.png','sha256':hashlib.sha256(b'original image').hexdigest()}
            out=Path(temp)/'library';publish_image(f,base,out,'figures')
            self.assertLessEqual(len(str(out/'images'/f['file'])),238)
            self.assertLessEqual(len(str(out/'images'/f['thumbnail'])),238)
            self.assertEqual((out/'images'/f['file']).read_bytes(),b'original image')
            self.assertEqual(f['original_filename'],'source.png')
if __name__=='__main__':unittest.main()
