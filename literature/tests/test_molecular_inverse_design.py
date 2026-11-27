"""Inverse molecular design requires a learned model, molecules and design purpose."""
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted

LABEL='topic.machine_learning_molecular_inverse_design'


class MolecularInverseDesignTests(unittest.TestCase):
    def test_explicit_components_in_all_orders(self):
        for term in ['Machine-learning molecular inverse design',
                     'Deep-learning-based inverse design of molecules',
                     'Molecular inverse design using neural networks',
                     'Molecules from machine learning for inverse design',
                     'Inverse design of molecular structures using deep learning',
                     'Inverse design using neural networks for molecules',
                     'Inverse molecular design based on machine learning']:
            with self.subTest(term=term):
                d=document(title=term);r=classify(d)
                self.assertIn(LABEL,accepted(r,1));validate_evidence(d,r)

    def test_own_abstract_is_accepted(self):
        d=document(abstract='We develop a machine-learning model for inverse design of molecules.')
        self.assertIn(LABEL,accepted(classify(d),1))

    def test_first_time_passive_reuses_existing_ownership(self):
        d=document(abstract='Machine-learning molecular inverse design was for the first time studied.')
        self.assertIn(LABEL,accepted(classify(d),1))

    def test_prediction_and_screening_are_distinct(self):
        for title in ['Machine learning predicts molecular emission properties',
                      'Neural networks screen molecular candidates for emission',
                      'Deep learning for molecular materials discovery']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_inverse_design_without_learned_model_is_distinct(self):
        for title in ['Inverse design of molecules using density functional theory',
                      'AI-assisted inverse design of molecular emitters',
                      'ML molecular inverse design']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_nonmolecular_design_is_distinct(self):
        for title in ['Machine-learning inverse design of photonic devices',
                      'Deep learning for inverse design of an optical cavity']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_no_components_joined_across_sentences_or_semicolon(self):
        for title in ['Machine learning predicts spectra. Molecular inverse design is discussed',
                      'Machine learning predicts spectra; molecular inverse design is discussed',
                      'Molecular properties are studied! Deep learning for inverse design']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_design_denial_inside_phrase_does_not_match(self):
        for title in ['Machine learning predicts molecules without inverse design',
                      'Molecular deep learning does not perform inverse design',
                      'Inverse design without neural networks for molecules']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_prefix_negation_remains_excluded(self):
        d=document(abstract='We found no evidence of machine-learning molecular inverse design.')
        self.assertNotIn(LABEL,accepted(classify(d),1))

    def test_history_and_citation_stay_mentions(self):
        for text in ['Previously, machine-learning molecular inverse design was studied.',
                     'Smith et al. report deep-learning inverse design of molecules.']:
            d=document(abstract=text);r=classify(d)
            self.assertNotIn(LABEL,accepted(r,1));self.assertIn(LABEL,{x['id'] for x in r['mentions']});validate_evidence(d,r)

    def test_body_does_not_supply_level1(self):
        d=document(text='We develop machine-learning molecular inverse design.')
        self.assertNotIn(LABEL,accepted(classify(d),1))

    def test_original_layout_and_offsets_are_preserved(self):
        term='deep-learning-based inverse design of molec-\nules'
        d=document(title=term);r=classify(d)
        e=next(l for l in r['level1'] if l['id']==LABEL)['evidence'][0]
        self.assertEqual(e['matched_text'],term);validate_evidence(d,r)

    def test_title_comparison_reuses_existing_ownership(self):
        d=document(title='Beyond machine-learning molecular inverse design: experiments');r=classify(d)
        self.assertNotIn(LABEL,accepted(r,1));self.assertIn(LABEL,{x['id'] for x in r['mentions']})

    def test_application_or_mechanism_is_not_implied(self):
        d=document(title='Machine-learning molecular inverse design');r=classify(d)
        self.assertIn(LABEL,accepted(r,1))
        self.assertFalse({'topic.oled','topic.organic_luminescence','topic.tadf','topic.phosphorescence'} &
                         {x['id'] for x in r['level1']+r['inherited_labels']})
