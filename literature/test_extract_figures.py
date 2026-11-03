"""Offline regression tests for PDF figure extraction semantics and preservation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
import numpy as np
s=importlib.util.spec_from_file_location("extract_figures",Path(__file__).with_name("extract_figures.py"))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class FigureTests(unittest.TestCase):
    def test_caption_formats(self):
        for caption in ["Figure 1. Overview","Figure B.1: Pipeline","Figure S2 Results","Fig. 12: Test"]:
            self.assertIsNotNone(m.PATTERN.match(caption),caption)
        self.assertIsNone(m.PATTERN.match("Figure 2(a) shows a result"))

    def test_full_paper_title_preserved_and_filename_safe(self):
        title="Learning to Compose: Recursive Self-Improvement of Shared Executable Stacks for Zero-Shot Long-Horizon Robot Manipulation"
        f={"label":"Figure 12","caption_title":"Overview of a very detailed system architecture and model training framework with many panels"}
        name=m.figure_filename(title,f)
        self.assertTrue(name.startswith(m.safe_name(title)+"__Figure_12__"))
        self.assertLessEqual(len(name),184)
        self.assertNotIn(":",name)
        self.assertTrue(name.endswith(".png"))

    def test_no_overwrite_different_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"x.png"
            a=m.save_image(path,Image.new("RGB",(10,10),"red"))
            b=m.save_image(path,Image.new("RGB",(10,10),"red"))
            self.assertEqual(a["sha256"],b["sha256"])
            with self.assertRaises(ValueError):
                m.save_image(path,Image.new("RGB",(10,10),"blue"))

    def test_pdf_coordinate_to_top_origin(self):
        self.assertEqual(m.bbox_top([10,20,30,50],100),[10,50,30,80])
        self.assertFalse(m.valid_box([10,10,5,20]))

    def test_dense_multipanel_region_uses_full_width(self):
        pg={"width":600,"height":800,"texts":[],"captions":[]}
        cap={"caption_bbox":[65,400,70,409]}
        pg["captions"]=[cap]
        mask=np.zeros((800,600),dtype=bool);mask[320:390,400:550]=True
        self.assertEqual(m.caption_region(pg,cap,mask)[2],565)

    def test_paired_column_captions_stay_separate(self):
        cap={"caption_bbox":[65,400,70,409]}
        other={"caption_bbox":[315,400,320,409]}
        pg={"width":600,"height":800,"texts":[],"captions":[cap,other]}
        mask=np.zeros((800,600),dtype=bool);mask[320:390,400:550]=True
        self.assertEqual(m.caption_region(pg,cap,mask)[2],298)

    def test_crop_preserves_real_pixels(self):
        # Empty-page render is sufficient to test crop origin and output dimensions.
        d=m.pdfium.PdfDocument.new()
        pg=d.new_page(600,800)
        image=m.render_crop(pg,[60,100,360,300],144)
        self.assertEqual(image.size,(600,400))
        image.close();pg.close();d.close()

if __name__=="__main__":
    unittest.main()

