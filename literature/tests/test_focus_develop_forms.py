"""Research-focus develop verbs do not include nominal background vocabulary."""
import unittest

from literature.classifier import classify,validate_evidence,ABSTRACT_FOCUS as FOCUS
from literature.tests.test_context import document,accepted


class DevelopFocusFormTests(unittest.TestCase):
    def test_complete_develop_verb_forms_remain_focus_cues(self):
        for word in ['develop','develops','developed','developing','DEVELOPED']:
            with self.subTest(word=word):self.assertIsNotNone(FOCUS.fullmatch(word))

    def test_nominal_adjectival_and_accidental_suffixes_are_not_actions(self):
        for word in ['development','developments','developmental','developmentally',
                     'developer','developers','developability','developedness','developingXYZ']:
            with self.subTest(word=word):self.assertIsNone(FOCUS.search(word))

    def test_nominal_background_alone_does_not_own_abstract_topic(self):
        for text in ['TADF can inform future material development.',
                     'The development of phosphorescence materials remains challenging.',
                     'OLEDs motivate further technological developments.']:
            with self.subTest(text=text):
                d=document(abstract=text);r=classify(d)
                self.assertEqual(r['level1'],[])
                self.assertTrue(r['mentions'])
                self.assertEqual(r['mentions'][0]['evidence'][0]['focus_text'],text)
                validate_evidence(d,r)

    def test_actual_develop_actions_can_own_abstract_direction(self):
        for text in ['A new route develops TADF emitters.',
                     'TADF emitters are developed in a new series.',
                     'A strategy developing TADF emitters is described.']:
            with self.subTest(text=text):
                d=document(abstract=text);r=classify(d)
                self.assertIn('topic.tadf',accepted(r,1));validate_evidence(d,r)

    def test_nominal_phrase_with_explicit_current_owner_remains_eligible(self):
        for text in ['In this work, the development of TADF emitters is examined.',
                     'We discuss the development of TADF emitters.',
                     'Our study concerns the development of TADF emitters.']:
            with self.subTest(text=text):
                self.assertIn('topic.tadf',accepted(classify(document(abstract=text)),1))

    def test_title_and_independent_abstract_evidence_are_not_vetoed(self):
        d=document(title='Development of TADF emitters',abstract='TADF can inform future development.')
        r=classify(d);self.assertIn('topic.tadf',accepted(r,1));validate_evidence(d,r)
        d=document(abstract='TADF can inform future material development. Herein, we investigate phosphorescence.')
        r=classify(d);self.assertNotIn('topic.tadf',accepted(r,1))
        self.assertIn('topic.phosphorescence',accepted(r,1));validate_evidence(d,r)

    def test_history_and_cited_passive_guards_remain(self):
        for text in ['Previously we developed TADF emitters.',
                     'Smith et al. developed TADF emitters.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.tadf',accepted(classify(document(abstract=text)),1))
        d=document(text='Smith et al. developed emitters. X-ray crystallography was conducted.',
                   title='X-ray crystallography study')
        self.assertNotIn('method.xray',accepted(classify(d),2))

    def test_comparison_title_and_nominal_background_cannot_rescue_each_other(self):
        d=document(title='Beyond conventional TADF: phosphorescence',
                   abstract='TADF can inform future material development.')
        r=classify(d);self.assertNotIn('topic.tadf',accepted(r,1))
        self.assertIn('topic.phosphorescence',accepted(r,1))
        e=next(x for x in r['mentions'] if x['id']=='topic.tadf')['evidence']
        self.assertEqual({x['scope'] for x in e},{'title','abstract'});validate_evidence(d,r)

    def test_source_gates_and_explicit_body_use_are_retained(self):
        d=document(abstract='We develop TADF emitters using DFT calculations.',
                   text='We conducted X-ray crystallography on the crystals.')
        r=classify(d);self.assertIn('topic.tadf',accepted(r,1))
        self.assertNotIn('method.dft',accepted(r,2));self.assertIn('method.xray',accepted(r,2))
        validate_evidence(d,r)

    def test_nominal_background_cannot_own_an_adjacent_abstract_result(self):
        d=document(abstract='The development of hybrids remains challenging. These hybrids exhibit phosphorescence.')
        self.assertNotIn('topic.phosphorescence',accepted(classify(d),1))
        d=document(abstract='Herein, we develop hybrids. These hybrids exhibit phosphorescence.')
        self.assertIn('topic.phosphorescence',accepted(classify(d),1))

    def test_original_fulltext_admission_is_not_changed_by_abstract_guard(self):
        d=document(title='Narrowband performance',
                   text='Material development enables narrowband emission.')
        d['chunks'][0]['section']='abstract'
        r=classify(d)
        self.assertIn('question.narrowband',accepted(r,2))
        self.assertEqual(r['level1'],[])
        validate_evidence(d,r)
