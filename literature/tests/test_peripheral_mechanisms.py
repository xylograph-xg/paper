"""Do not borrow a measured outcome's importance for speculative mechanisms."""
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document


class PeripheralMechanismTests(unittest.TestCase):
    def test_speculative_explanations_remain_exact_supporting_evidence(self):
        for text in ['We reduced efficiency roll-off, probably by suppressing triplet-triplet annihilation.',
                     'We improved efficiency, possibly by suppressing TTA.',
                     'We reduced roll-off; TTA probably causes the residual loss.',
                     'We improved efficiency. TTA is likely responsible for the loss.']:
            with self.subTest(text=text):
                d=document(text=text,title='Efficiency of emitters');r=classify(d)
                self.assertNotIn('mechanism.tta',{x['id'] for x in r['level2']})
                label=next(x for x in r['supporting_labels'] if x['id']=='mechanism.tta')
                self.assertEqual(label['selection_basis'],'speculative_or_general_mechanism')
                self.assertIn('TTA' if 'TTA' in text else 'triplet-triplet annihilation',label['evidence'][0]['quote'])
                validate_evidence(d,r)

    def test_general_alternative_cannot_borrow_proposed_from_historical_name(self):
        text='Generally, energy can be transferred by a mechanism proposed by Dexter or through FRET.'
        r=classify(document(text=text))
        self.assertNotIn('mechanism.dexter',{x['id'] for x in r['level2']})
        self.assertIn('mechanism.dexter',{x['id'] for x in r['supporting_labels']})

    def test_explicit_hypothesis_target_in_title_or_abstract_is_retained(self):
        text='We reduced efficiency roll-off, probably by suppressing TTA.'
        for title,abstract in [('TTA in emitters',''),
                               ('Emitter study','We investigate the hypothesized role of TTA.'),
                               ('Emitter study','We test whether TTA might account for the loss.')]:
            with self.subTest(abstract=abstract,title=title):
                r=classify(document(text=text,title=title,abstract=abstract))
                self.assertIn('mechanism.tta',{x['id'] for x in r['level2']})

    def test_background_or_side_explanation_in_abstract_does_not_rescue_core(self):
        text='We improved efficiency, probably by suppressing TTA.'
        for abstract in ['TTA is common in emitters.',
                         'Previously we investigated TTA.',
                         'We demonstrate improved efficiency, probably by suppressing TTA.']:
            with self.subTest(abstract=abstract):
                r=classify(document(text=text,abstract=abstract))
                self.assertNotIn('mechanism.tta',{x['id'] for x in r['level2']})

    def test_independent_direct_evidence_can_keep_same_mechanism_core(self):
        d=document(text='We improved efficiency, probably by suppressing TTA. We directly investigate TTA through nonlinear decays.')
        self.assertIn('mechanism.tta',{x['id'] for x in classify(d)['level2']})

    def test_other_mechanism_in_observed_clause_and_other_dimensions_unchanged(self):
        d=document(text='We investigate RISC, but TTA probably causes losses. We measured temperature-dependent spectra.',
                   abstract='We develop temperature-dependent spectroscopy.')
        r=classify(d)
        self.assertIn('mechanism.risc',{x['id'] for x in r['level2']})
        self.assertNotIn('mechanism.tta',{x['id'] for x in r['level2']})
        self.assertIn('method.temperature',{x['id'] for x in r['level2']})

    def test_metadata_does_not_create_missing_body_mechanism(self):
        r=classify(document(abstract='We investigate the possible role of TTA.',title='TTA study'))
        self.assertEqual(r['level2'],[])
