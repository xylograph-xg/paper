"""Explicit exciton topics preserve input and scientific ownership boundaries."""
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted


class ExcitonFamilyTests(unittest.TestCase):
    def test_full_topic_names_cover_distinct_exciton_routes(self):
        for name, label in [('intermolecular singlet fission','topic.singlet_fission'),
                            ('intramolecular singlet-fission','topic.singlet_fission'),
                            ('hot-exciton-assisted exciplex','topic.hot_exciton'),
                            ('hot exciplex','topic.hot_exciton')]:
            with self.subTest(name=name):
                d=document(title='Design of '+name+' systems');r=classify(d)
                self.assertIn(label, accepted(r,1));validate_evidence(d,r)

    def test_bare_abbreviations_and_different_physics_are_insufficient(self):
        for name in ['SF emitters','hot carrier transport','intersystem crossing',
                     'singlet-to-triplet conversion','thermal excitons']:
            self.assertFalse({'topic.singlet_fission','topic.hot_exciton'} & accepted(classify(document(title=name)),1))

    def test_abstract_current_versus_historical_ownership(self):
        for name, label in [('singlet fission','topic.singlet_fission'),('hot excitons','topic.hot_exciton')]:
            d=document(abstract='We investigate '+name+' in these materials.')
            self.assertIn(label,accepted(classify(d),1))
            d=document(abstract='Previous work investigated '+name+' in related materials.')
            r=classify(d);self.assertNotIn(label,accepted(r,1));self.assertIn(label,{l['id'] for l in r['mentions']})

    def test_body_alone_does_not_supply_broad_topic(self):
        r=classify(document(text='We investigate singlet fission and hot excitons.'))
        self.assertFalse({'topic.singlet_fission','topic.hot_exciton'} & accepted(r,1))

    def test_comparison_and_negation_remain_protected(self):
        for name, label in [('singlet fission','topic.singlet_fission'),('hot excitons','topic.hot_exciton')]:
            self.assertNotIn(label,accepted(classify(document(title='Beyond '+name+': molecular fluorescence')),1))
            self.assertNotIn(label,accepted(classify(document(abstract='We found no evidence of '+name+'.')),1))

    def test_hot_exciplex_does_not_imply_tadf_or_fission(self):
        r=classify(document(title='Hot-exciplex systems'))
        self.assertIn('topic.hot_exciton',accepted(r,1))
        self.assertFalse({'topic.tadf','topic.singlet_fission'} & {l['id'] for l in r['level1']+r['inherited_labels']})

    def test_layout_evidence_offsets_are_original(self):
        d=document(abstract='We investigate singlet\nfission in molecular crystals.');r=classify(d)
        e=next(l for l in r['level1'] if l['id']=='topic.singlet_fission')['evidence'][0]
        self.assertEqual(e['matched_text'],'singlet\nfission');validate_evidence(d,r)
