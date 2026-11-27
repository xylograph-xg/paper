"""Critical method evidence versus routine characterization; generic examples."""
import unittest
from literature.classifier import classify,validate_evidence,PATTERNS
from literature.focus import method_causal_attribution
from literature.tests.test_context import document


class MethodAttributionTests(unittest.TestCase):
    def test_method_subject_linking_outcome_to_process_can_be_core(self):
        for text,label in [('Transient PL measurements linked efficiency losses to energy transfer.','method.time_resolved'),
                           ('Our time-resolved PL measurements link the emission lifetime to charge trapping.','method.time_resolved'),
                           ('DFT calculations directly linked nonradiative losses to charge transfer.','method.dft'),
                           ('The transient absorption measurements linked the low yield to triplet annihilation.','method.transient_absorption')]:
            with self.subTest(text=text):
                d=document(text=text);r=classify(d);l=next(x for x in r['level2'] if x['id']==label)
                self.assertEqual(l['selection_basis'],'method_causal_attribution')
                self.assertEqual(l['evidence'][0]['focus_text'],text);validate_evidence(d,r)
                self.assertFalse(r['scientific_verified'])

    def test_routine_caption_and_methods_section_do_not_gain_core(self):
        for text in ['We measured transient PL spectra.','Figure 2: Transient PL measurements.',
                     'Transient PL measurements linked the sample file to its identifier.']:
            with self.subTest(text=text):
                r=classify(document(text=text));self.assertNotIn('method.time_resolved',{x['id'] for x in r['level2']})
        d=document(text='Transient PL measurements linked efficiency to energy transfer.');d['chunks'][0]['section']='methods'
        self.assertNotIn('method.time_resolved',{x['id'] for x in classify(d)['level2']})

    def test_uncertainty_history_and_negation_do_not_promote(self):
        for text in ['Transient PL measurements probably linked efficiency to energy transfer.',
                     'Transient PL measurements may link efficiency to energy transfer.',
                     'Previously transient PL measurements linked efficiency to energy transfer.',
                     'Transient PL measurements did not link efficiency to energy transfer.',
                     'Transient PL measurements linked efficiency to energy transfer if traps were absent.',
                     "Transient PL measurements couldn't link efficiency to energy transfer."]:
            with self.subTest(text=text):
                r=classify(document(text=text));self.assertNotIn('method.time_resolved',{x['id'] for x in r['level2']})

    def test_both_scientific_arguments_are_required(self):
        for text in ['Transient PL measurements linked efficiency to sample identifiers.',
                     'Transient PL measurements linked raw files to energy transfer.',
                     'Transient PL measurements linked one sample to another.']:
            with self.subTest(text=text):
                self.assertNotIn('method.time_resolved',{x['id'] for x in classify(document(text=text))['level2']})

    def test_neighboring_subject_cannot_lend_attribution(self):
        for text in ['We recorded transient PL, and other calculations linked efficiency to energy transfer.',
                     'Transient PL measurements were recorded while other results linked efficiency to energy transfer.',
                     'We measured transient PL. Other results linked efficiency to energy transfer.']:
            with self.subTest(text=text):
                self.assertNotIn('method.time_resolved',{x['id'] for x in classify(document(text=text))['level2']})

    def test_critical_method_does_not_promote_neighboring_routine_method(self):
        d=document(text='Transient PL measurements linked efficiency to energy transfer. We performed DFT calculations.')
        r=classify(d);self.assertIn('method.time_resolved',{x['id'] for x in r['level2']})
        self.assertNotIn('method.dft',{x['id'] for x in r['level2']});validate_evidence(d,r)

    def test_body_evidence_is_still_required(self):
        r=classify(document(abstract='Transient PL measurements linked efficiency to energy transfer.'))
        self.assertEqual(r['level2'],[])
        # A positive method-subject result now supplies explicit use evidence.
        text='Our time-resolved PL experiments link the emission lifetime to charge trapping.'
        hit=PATTERNS['method.time_resolved'].search(text)
        self.assertTrue(method_causal_attribution(text,hit.start(),hit.end()))
        self.assertIn('method.time_resolved',{x['id'] for x in classify(document(text=text))['level2']})

    def test_original_pdf_typography_and_page_offsets_retained(self):
        text='Time–resolved\nphotoluminescence experiments linked the high performance to eﬀective energy transfer.'
        d=document(text=text);d['chunks'][0]['section']='conclusion';r=classify(d)
        l=next(x for x in r['level2'] if x['id']=='method.time_resolved')
        self.assertEqual(l['evidence'][0]['focus_text'],text);validate_evidence(d,r)
