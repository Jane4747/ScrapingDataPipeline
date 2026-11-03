import unittest
from doi_import import match
class Tests(unittest.TestCase):
    def test_exact_front_title_wins_over_generic_shared_words(self):
        rows=[{'id':'A','title':'Deep Visual Servoing of an Aerial Robot Using Keypoint Feature Extraction','doi':'10.1/a'},{'id':'B','title':'Robot Visual Servoing Using Deep Learning','doi':'10.1/b'}]
        text=rows[0]['title']+' Abstract: Robot visual servoing using deep learning is discussed.'
        self.assertEqual(match(text,rows)['id'],'A')
    def test_ambiguous_titles_remain_unassigned(self):
        rows=[{'id':'A','title':'Image Visual Servoing','doi':'10.1/a'},{'id':'B','title':'Image Visual Servoing','doi':'10.1/b'}]
        self.assertIsNone(match('Image Visual Servoing',rows))
if __name__=='__main__':unittest.main()
