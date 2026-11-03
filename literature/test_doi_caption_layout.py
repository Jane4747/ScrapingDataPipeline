import unittest,re,types
import numpy as np
from doi_caption_layout import install

def fake():
    return types.SimpleNamespace(text_lines=lambda xs:sorted(xs,key=lambda x:x['bbox'][1]),clean_text=lambda s:re.sub(r'\s+',' ',s).strip(),union=lambda bs:[min(x[0] for x in bs),min(x[1] for x in bs),max(x[2] for x in bs),max(x[3] for x in bs)],resolve_caption=lambda pg,cap,mask:None)
class Tests(unittest.TestCase):
    def test_right_column_caption_not_merged_with_left_prose(self):
        m=fake();install(m);page=types.SimpleNamespace(get_size=lambda:(600,800))
        objects=[{'bbox':[35,300,280,311],'text':'Body text in left column.'},{'bbox':[320,300,570,311],'text':'Fig. 3. System architecture.'}]
        caps=m.get_captions(None,page,800,[],objects)
        self.assertEqual(len(caps),1);self.assertEqual(caps[0]['number'],'3');self.assertEqual(caps[0]['caption_bbox'][0],320)
    def test_prose_reference_is_not_a_caption(self):
        m=fake();install(m);page=types.SimpleNamespace(get_size=lambda:(600,800))
        objects=[{'bbox':[35,300,280,311],'text':'Figure 2 shows the controller response.'}]
        self.assertEqual(m.get_captions(None,page,800,[],objects),[])
    def test_crop_does_not_bridge_preceding_caption(self):
        m=fake();seen=[];m.resolve_caption=lambda pg,cap,mask:seen.append(mask.copy())
        install(m);previous={'caption_bbox':[35,100,150,112],'physical_caption_end':120};current={'caption_bbox':[35,300,150,312]}
        m.resolve_caption({'captions':[previous,current],'width':600},current,np.ones((800,600),dtype=bool))
        self.assertFalse(seen[0][:122].any());self.assertTrue(seen[0][122:].all())
if __name__=='__main__':unittest.main()
