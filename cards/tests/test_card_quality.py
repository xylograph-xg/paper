import hashlib
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace as NS
from reading.reading_bridge import filter_equation_candidates, reviewed_source_matches

class CardQuality(unittest.TestCase):
    def parsed(self,text,box=None,number=None):
        m=dict(text=text,bbox=box or [20,30,80,40],page=1,index=0,number=number)
        return NS(equations=[NS(members=[m],page=0)],figures=[NS(crop_page=0,crop_bbox=[100,100,250,250])],warnings=[])
    def test_plot_labels_not_equations(self):
        for text in ['0 1 x ( T / T ∆ -3)','Abs PL','50 μJ/cm2','ΔT/T (×10−3)']:
            p=self.parsed(text);self.assertEqual(filter_equation_candidates(p),1);self.assertEqual(p.equations,[])
    def test_relation_in_body_preserved(self):
        p=self.parsed('k_total = k_r + k_nr');self.assertEqual(filter_equation_candidates(p),0);self.assertEqual(len(p.equations),1)
    def test_fit_parameter_inside_plot_removed(self):
        p=self.parsed('τ = 1200 ps',[120,120,200,140]);self.assertEqual(filter_equation_candidates(p),1)
    def test_numbered_equation_preserved(self):
        p=self.parsed('H ψ',[120,120,200,140],1);self.assertEqual(filter_equation_candidates(p),0)
    def test_review_only_valid_for_same_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'source.pdf';p.write_bytes(b'original')
            card=NS(meta={'quality_review':{'source_sha256':hashlib.sha256(b'original').hexdigest()}})
            self.assertTrue(reviewed_source_matches(card,p));p.write_bytes(b'replaced');self.assertFalse(reviewed_source_matches(card,p))
