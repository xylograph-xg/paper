import unittest
from cards.paper_quality import validate

class DirectWebpageScore(unittest.TestCase):
    def item(self,score):return {'score':score,'reason':'source evidence','source_pages':[1]}
    def test_direct_score_preserved_without_dimension_arithmetic(self):
        item=self.item(85.01);item['dimensions']={'legacy':{'score':1}}
        self.assertEqual(validate(item,1),85.01)
        self.assertEqual(validate(self.item(79.5),1),79.5)
    def test_invalid_or_ungrounded_scores_still_rejected(self):
        for score in [101,True,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):validate(self.item(score),1)
        item=self.item(80);item['source_pages']=[]
        with self.assertRaises(ValueError):validate(item,1)
    def test_unknown_overall_score_stays_unknown(self):
        self.assertIsNone(validate(self.item(None),1))
