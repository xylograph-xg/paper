"""Efficiency-rolloff word forms require the same original-text ownership."""
import unittest

from literature.classifier import classify, validate_evidence, PATTERNS, canonical
from literature.tests.test_context import document, accepted


class RolloffFormTests(unittest.TestCase):
    def test_compound_plural_and_spaced_forms_have_same_meaning(self):
        for term in ['efficiency rolloff','efficiency rolloffs','efficiency roll-offs',
                     'efficiency roll offs','EQE rolloff','EQE rolloffs',
                     'efficiency roll-off','EQE roll-off']:
            with self.subTest(term=term):
                d=document(text='We suppressed '+term+' in the devices.')
                r=classify(d);self.assertIn('question.rolloff',accepted(r,2));validate_evidence(d,r)

    def test_single_normalized_separator_between_efficiency_and_rolloff(self):
        for term in ['efficiency\nroll-off','EQE\trolloffs']:
            with self.subTest(term=term):
                r=classify(document(text='We reduced '+term+' at high brightness.'))
                self.assertIn('question.rolloff',accepted(r,2))

    def test_multi_whitespace_layout_keeps_current_contribution(self):
        # Revisit the recorded limitation under the accepted background guard.
        for term in ['efficiency  rolloff','efficiency \nroll-off']:
            with self.subTest(term=term):
                self.assertIn('question.rolloff',accepted(classify(document(text='We reduced '+term+'.')),2))

    def test_pdf_ligatures_and_hyphen_wrap_keep_original_offsets(self):
        term='eﬃciency roll-\noff'
        d=document(text='We reduced '+term+' at high brightness.')
        r=classify(d);self.assertIn('question.rolloff',accepted(r,2))
        e=next(l for l in r['level2'] if l['id']=='question.rolloff')['evidence'][0]
        self.assertEqual(e['matched_text'],term)
        self.assertIn(term,e['quote']);validate_evidence(d,r)

    def test_actual_results_remain_eligible_without_first_person(self):
        for text in ['The devices exhibit suppressed efficiency rolloffs.',
                     'The device design reduced EQE rolloff at high brightness.']:
            d=document(text=text);r=classify(d)
            self.assertIn('question.rolloff',accepted(r,2));validate_evidence(d,r)

    def test_similar_words_and_unqualified_rolloff_do_not_match(self):
        for term in ['efficiency rollout','efficiency rolloffish','efficiency rolloffline',
                     'inefficiency rolloff','EQEs rolloff','rolloffs','optical attenuation']:
            with self.subTest(term=term):
                self.assertIsNone(PATTERNS['question.rolloff'].search(canonical(term)[0]))
                self.assertNotIn('question.rolloff',accepted(classify(document(text='We studied '+term+'.')),2))

    def test_metadata_cannot_supply_missing_fulltext_evidence(self):
        d=document(title='Reduced efficiency rolloffs',abstract='We suppressed EQE rolloff.',
                   text='We measured the optical absorption.')
        self.assertNotIn('question.rolloff',accepted(classify(d),2))

    def test_author_keywords_alone_are_not_accepted(self):
        d=document(title='Low efficiency rolloffs',text='KEYWORDS: efficiency rolloffs, OLEDs')
        d['chunks'][0]['section']='supporting information';r=classify(d)
        self.assertNotIn('question.rolloff',accepted(r,2))
        self.assertIn('question.rolloff',{l['id'] for l in r['mentions']});validate_evidence(d,r)

    def test_historical_sentence_is_still_only_a_mention(self):
        d=document(text='Previously, efficiency rolloffs were suppressed in these devices.')
        r=classify(d);self.assertNotIn('question.rolloff',accepted(r,2))
        self.assertIn('question.rolloff',{l['id'] for l in r['mentions']});validate_evidence(d,r)

    def test_bibliography_cannot_supply_a_new_alias(self):
        d=document(text='(17) Smith, A.; Jones, B. Design of Emitters with Suppressed Efficiency Rolloffs.')
        r=classify(d);self.assertNotIn('question.rolloff',accepted(r,2))
        e=next(l for l in r['mentions'] if l['id']=='question.rolloff')['evidence'][0]
        self.assertEqual(e['basis'],'bibliography_entry_only');validate_evidence(d,r)

    def test_explicit_reference_section_is_excluded(self):
        d=document(text='We suppressed efficiency rolloffs.')
        d['chunks'][0]['section']='references'
        self.assertNotIn('question.rolloff',accepted(classify(d),2))

    def test_negative_and_free_forms_do_not_become_positive_labels(self):
        for text in ['We found no evidence of efficiency rolloffs.',
                     'We designed efficiency rolloff-free emitters.']:
            with self.subTest(text=text):
                self.assertNotIn('question.rolloff',accepted(classify(document(text=text)),2))
