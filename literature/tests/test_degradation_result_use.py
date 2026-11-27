"""A coupled chromatography-MS result can establish use without a procedure verb."""
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted

LABEL='method.degradation_product_analysis'


class DegradationResultUseTests(unittest.TestCase):
    def doc(self,text,abstract='We identify degradation products in irradiated emitters.'):
        return document(text=text,abstract=abstract)

    def test_explicit_coupled_subject_and_product_result(self):
        for text in ['LC-MS analysis revealed degradation products.',
                     'GC-MS identified the degradation products formed during ageing.',
                     'Our LC-MS measurements directly detected degradation products.',
                     'The GC-MS results showed that the degradation products were oxidized species.']:
            with self.subTest(text=text):
                d=self.doc(text);r=classify(d);self.assertIn(LABEL,accepted(r,2));validate_evidence(d,r)
                self.assertIn('chromatography_ms_result_use',{e.get('method_result') for l in r['level2'] if l['id']==LABEL for e in l['evidence']})

    def test_degradation_context_is_still_required(self):
        for text in ['LC-MS analysis revealed the target compound with high purity.',
                     'GC-MS identified the synthetic products.',
                     'HPLC analysis revealed degradation products.',
                     'Mass spectrometry revealed degradation products.']:
            with self.subTest(text=text):self.assertNotIn(LABEL,accepted(classify(self.doc(text)),2))

    def test_subject_and_clause_cannot_be_borrowed(self):
        for text in ['We discussed LC-MS; other experiments revealed degradation products.',
                     'LC-MS was available, while optical analysis revealed degradation products.',
                     'LC-MS and other experiments revealed degradation products.',
                     'Other measurements revealed degradation products near the LC-MS instrument.']:
            with self.subTest(text=text):self.assertNotIn(LABEL,accepted(classify(self.doc(text)),2))

    def test_history_citation_future_and_uncertainty_remain_excluded(self):
        for text in ['Previously LC-MS analysis revealed degradation products.',
                     'Smith et al. report that LC-MS analysis revealed degradation products.',
                     'LC-MS analysis could reveal degradation products.',
                     'LC-MS analysis probably revealed degradation products.',
                     'LC-MS analysis revealed degradation products if the sample was aged.']:
            with self.subTest(text=text):self.assertNotIn(LABEL,accepted(classify(self.doc(text)),2))

    def test_result_denial_is_not_positive_method_result(self):
        for text in ['LC-MS analysis revealed no degradation products.',
                     'LC-MS analysis did not reveal degradation products.',
                     'LC-MS analysis never identified degradation products.']:
            with self.subTest(text=text):self.assertNotIn(LABEL,accepted(classify(self.doc(text)),2))

    def test_body_and_source_guards_remain(self):
        r=classify(document(abstract='LC-MS analysis revealed degradation products.'))
        self.assertNotIn(LABEL,accepted(r,2))
        for section in ['references','acknowledgments','unknown']:
            d=self.doc('LC-MS analysis revealed degradation products.');d['chunks'][0]['section']=section
            self.assertNotIn(LABEL,accepted(classify(d),2))

    def test_bibliography_in_wrong_section_is_not_use(self):
        d=self.doc('(12) Author, A. LC-MS analysis revealed degradation products. J. Chem. 2020, 1, 2-4.')
        self.assertNotIn(LABEL,accepted(classify(d),2))

    def test_preserve_unaccepted_caption_after_result_acceptance(self):
        d=self.doc('LC-MS analysis revealed degradation products. Figure 2: LC-MS instrument.')
        r=classify(d);self.assertIn(LABEL,accepted(r,2))
        mention=next(l for l in r['mentions'] if l['id']==LABEL)
        self.assertTrue(any('Figure 2:' in e['focus_text'] for e in mention['evidence']));validate_evidence(d,r)

    def test_existing_core_selection_not_bypassed(self):
        d=self.doc('LC-MS analysis revealed degradation products.',abstract='We study optical emission.')
        r=classify(d);self.assertNotIn(LABEL,{l['id'] for l in r['level2']});self.assertIn(LABEL,{l['id'] for l in r['supporting_labels']})

    def test_original_layout_and_offsets_preserved(self):
        text='LC–MS\nanalysis indeed revealed that the detected degradation\nproducts were oxidized species.'
        d=self.doc(text);r=classify(d);l=next(l for l in r['level2'] if l['id']==LABEL)
        self.assertEqual(l['evidence'][0]['matched_text'],'LC–MS');self.assertEqual(l['evidence'][0]['focus_text'],text);validate_evidence(d,r)

    def test_neighboring_routine_method_not_promoted(self):
        d=self.doc('LC-MS analysis revealed degradation products. We performed DFT calculations.')
        r=classify(d);self.assertIn(LABEL,accepted(r,2));self.assertNotIn('method.dft',{l['id'] for l in r['level2']})
