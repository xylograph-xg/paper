"""Qualified PDF layout variants obey existing ownership and core policy."""
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted
from literature.tests.test_background_questions import chunks


class RolloffLayoutTests(unittest.TestCase):
    def test_current_contribution_across_layout_spaces(self):
        for term in ['efficiency  rolloff','EQE \nroll-off','eﬃciency\u00a0 \troll-oﬀ']:
            with self.subTest(term=term):
                d=document(text='We reduced '+term+' in the devices.')
                r=classify(d);self.assertIn('question.rolloff',{x['id'] for x in r['level2']})
                e=next(x for x in r['level2'] if x['id']=='question.rolloff')['evidence'][0]
                self.assertEqual(e['matched_text'],term);validate_evidence(d,r)

    def test_background_plus_observation_stays_supporting(self):
        d=chunks('In many cases, efficiency \nroll-off performance is better.',
                 'The devices exhibit similar EQE roll-off.')
        r=classify(d);self.assertNotIn('question.rolloff',{x['id'] for x in r['level2']})
        label=next(x for x in r['supporting_labels'] if x['id']=='question.rolloff')
        self.assertEqual(label['selection_basis'],'generic_background_question')
        self.assertEqual(len(label['evidence']),2);validate_evidence(d,r)

    def test_two_generalizing_chunks_do_not_become_core(self):
        d=chunks('Several reports show reduced efficiency  rolloff.',
                 'In general, EQE \nroll-off is reduced.')
        r=classify(d);self.assertNotIn('question.rolloff',{x['id'] for x in r['level2']})
        self.assertIn('question.rolloff',accepted(r,2));validate_evidence(d,r)

    def test_two_current_observations_keep_core(self):
        d=chunks('The device exhibits efficiency  rolloff.',
                 'The second device exhibits EQE \nroll-off at high brightness.')
        r=classify(d);self.assertIn('question.rolloff',{x['id'] for x in r['level2']});validate_evidence(d,r)

    def test_history_remains_mention(self):
        d=document(text='Previously, efficiency \nroll-off was suppressed.')
        r=classify(d);self.assertNotIn('question.rolloff',accepted(r,2))
        self.assertIn('question.rolloff',{x['id'] for x in r['mentions']});validate_evidence(d,r)

    def test_keywords_cannot_become_body_use(self):
        d=document(title='Efficiency roll-off',text='KEYWORDS: efficiency \nroll-off, OLEDs')
        d['chunks'][0]['section']='supporting information'
        r=classify(d);self.assertNotIn('question.rolloff',accepted(r,2))
        self.assertIn('question.rolloff',{x['id'] for x in r['mentions']});validate_evidence(d,r)

    def test_bibliographic_entry_keeps_source_guard(self):
        d=document(text='(17) Smith, A.; Jones, B. Suppressed Efficiency \nRolloff in Emitters.')
        r=classify(d);self.assertNotIn('question.rolloff',accepted(r,2))
        label=next(x for x in r['mentions'] if x['id']=='question.rolloff')
        self.assertEqual(label['evidence'][0]['basis'],'bibliography_entry_only');validate_evidence(d,r)

    def test_reference_section_keeps_exclusion(self):
        d=document(text='We reduced EQE \nrolloff.');d['chunks'][0]['section']='references'
        self.assertNotIn('question.rolloff',accepted(classify(d),2))

    def test_metadata_cannot_replace_body(self):
        d=document(title='Reduced efficiency  rolloff',abstract='We suppress EQE \nroll-off.',text='We measure absorption.')
        self.assertNotIn('question.rolloff',accepted(classify(d),2))

    def test_negation_and_complete_word_boundaries_remain(self):
        for text in ['We found no evidence of efficiency  rolloff.',
                     'We designed EQE \nrolloff-free emitters.',
                     'We suppress inefficiency  rolloff.',
                     'We measured efficiency  rolloffline.',
                     'We measured unqualified rolloff.']:
            with self.subTest(text=text):
                self.assertNotIn('question.rolloff',accepted(classify(document(text=text)),2))
