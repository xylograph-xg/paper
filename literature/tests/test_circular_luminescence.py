"""Emitted circular polarization is distinct from circular excitation or CPL alone."""
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted

LABEL='topic.circularly_polarized_luminescence'


class CircularLuminescenceTests(unittest.TestCase):
    def test_full_emission_terms_share_one_direction(self):
        for term in ['circularly polarized luminescence','circularly polarised luminescence',
                     'circularly polarized photoluminescence','circularly polarised electroluminescence',
                     'circularly-polarized emission','circularly polarised photo-luminescence']:
            with self.subTest(term=term):
                d=document(title='Chiral clusters with '+term);r=classify(d)
                self.assertIn(LABEL,accepted(r,1));validate_evidence(d,r)

    def test_current_abstract_full_term_is_accepted(self):
        d=document(abstract='We report circularly polarized luminescence from a new material.')
        r=classify(d);self.assertIn(LABEL,accepted(r,1));validate_evidence(d,r)

    def test_original_first_time_passive_route_is_reused(self):
        d=document(abstract='Circularly polarized luminescence was for the first time studied.')
        self.assertIn(LABEL,accepted(classify(d),1))

    def test_adjacent_result_requires_actual_matching_owner(self):
        for preceding,expected in [('We prepare emitters.',True),('Previously we prepared emitters.',False),('',False)]:
            d=document(abstract=preceding+' These emitters exhibit circularly polarized luminescence.')
            self.assertEqual(LABEL in accepted(classify(d),1),expected)

    def test_bare_acronym_never_supplies_definition(self):
        for title in ['CPL-active emitters','CPL spectra','CPL excitation','CPL OLEDs']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_circular_excitation_is_not_circular_emission(self):
        for title in ['Fluorescence under circularly polarized light',
                      'Circularly polarised excitation of emitters',
                      'Photoluminescence using circularly polarized laser illumination',
                      'Circular dichroism of molecular absorbers']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_other_polarizations_and_word_boundaries_are_not_aliases(self):
        for title in ['Linearly polarized luminescence','Elliptically polarised emission',
                      'Circularly depolarized luminescence','circularly polarized luminescenceish']:
            with self.subTest(title=title):self.assertNotIn(LABEL,accepted(classify(document(title=title)),1))

    def test_previous_or_cited_abstract_remains_mentioned(self):
        for text in ['Previously, circularly polarized luminescence was studied.',
                     'Smith et al. report circularly polarized luminescence.']:
            d=document(abstract=text);r=classify(d)
            self.assertNotIn(LABEL,accepted(r,1));self.assertIn(LABEL,{x['id'] for x in r['mentions']});validate_evidence(d,r)

    def test_explicit_negative_remains_excluded(self):
        text='We found no evidence of circularly polarized luminescence.'
        self.assertNotIn(LABEL,accepted(classify(document(abstract=text)),1))

    def test_fulltext_alone_cannot_supply_level1(self):
        d=document(text='We report circularly polarized luminescence.')
        self.assertNotIn(LABEL,accepted(classify(d),1))

    def test_hyphen_and_layout_keep_original_evidence_offsets(self):
        term='circularly\npolarised photo-luminescence'
        text='We report '+term+' from emitters.';d=document(abstract=text);r=classify(d)
        e=next(l for l in r['level1'] if l['id']==LABEL)['evidence'][0]
        self.assertEqual(e['matched_text'],term);self.assertEqual(e['focus_text'],text);validate_evidence(d,r)

    def test_comparison_title_preserves_old_ownership_rule(self):
        d=document(title='Beyond circularly polarized luminescence: fluorescence');r=classify(d)
        self.assertNotIn(LABEL,accepted(r,1));self.assertIn(LABEL,{x['id'] for x in r['mentions']});validate_evidence(d,r)

    def test_material_and_mechanism_are_not_implied(self):
        d=document(title='Circularly polarized luminescence of gold clusters');r=classify(d)
        self.assertIn(LABEL,accepted(r,1))
        self.assertFalse({'topic.oled','topic.organic_luminescence','topic.tadf','topic.phosphorescence'} &
                         {x['id'] for x in r['level1']+r['inherited_labels']})
