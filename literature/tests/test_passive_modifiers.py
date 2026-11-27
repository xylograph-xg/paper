"""Bounded novel passive results belong only to their abstract subject clause."""
import unittest
from literature.classifier import classify,validate_evidence,FOCUS
from literature.tests.test_context import document,accepted


class PassiveModifierTests(unittest.TestCase):
    def test_explicit_first_time_passive_subject(self):
        for auxiliary in ['is','are','was','were']:
            for verb in ['studied','fabricated','examined','characterized','synthesized']:
                with self.subTest(auxiliary=auxiliary,verb=verb):
                    d=document(abstract='OLEDs '+auxiliary+' for the first time '+verb+'.')
                    r=classify(d);self.assertIn('topic.oled',accepted(r,1));validate_evidence(d,r)

    def test_layout_preserves_exact_quote_and_focus(self):
        text='OLEDs were for\n the  first\ttime fabricated.'
        d=document(abstract=text);r=classify(d)
        label=next(l for l in r['level1'] if l['id']=='topic.oled');e=label['evidence'][0]
        self.assertEqual(e['focus_text'],text);self.assertEqual(e['quote'],text);validate_evidence(d,r)

    def test_modified_subject_retains_semantic_topic(self):
        d=document(abstract='Circularly polarised OLEDs were for the first time fabricated.')
        self.assertIn('topic.oled',accepted(classify(d),1))

    def test_historical_result_is_not_current(self):
        for prefix in ['Previously,','In 2010,','In earlier work,','In other studies,']:
            with self.subTest(prefix=prefix):
                r=classify(document(abstract=prefix+' OLEDs were for the first time fabricated.'))
                self.assertNotIn('topic.oled',accepted(r,1))

    def test_cited_result_is_not_our_result(self):
        for text in ['Smith et al. report that OLEDs were for the first time fabricated.',
                     'OLEDs were for the first time fabricated as reported by Smith et al.',
                     'According to the literature, OLEDs were for the first time fabricated.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.oled',accepted(classify(document(abstract=text)),1))

    def test_future_and_conditional_are_not_executed(self):
        for text in ['If OLEDs were for the first time fabricated, emission might improve.',
                     'It remains a future goal that OLEDs are for the first time fabricated.',
                     'OLEDs may be for the first time fabricated.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.oled',accepted(classify(document(abstract=text)),1))

    def test_denied_results_are_not_positive_topics(self):
        for text in ['No OLEDs were for the first time fabricated.',
                     'OLEDs were not for the first time fabricated.',
                     'OLEDs were for the first time not fabricated.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.oled',accepted(classify(document(abstract=text)),1))

    def test_another_clause_and_predicate_cannot_borrow_subject(self):
        for text in ['Crystals were for the first time fabricated while OLEDs remain unavailable.',
                     'Crystals were for the first time fabricated for comparison with OLEDs.',
                     'OLEDs remain unavailable, but crystals were for the first time fabricated.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.oled',accepted(classify(document(abstract=text)),1))

    def test_adjacent_sentence_cannot_lend_this_passive_owner(self):
        text='Crystals were for the first time fabricated. OLEDs are promising for displays.'
        self.assertNotIn('topic.oled',accepted(classify(document(abstract=text)),1))

    def test_contiguous_original_passive_is_unchanged(self):
        self.assertIn('topic.oled',accepted(classify(document(abstract='OLEDs were fabricated.')),1))

    def test_title_and_source_scope_are_unchanged(self):
        d=document(title='OLEDs',abstract='A sample was obtained.')
        self.assertIn('topic.oled',accepted(classify(d),1))
        d=document(text='OLEDs were for the first time fabricated.')
        self.assertNotIn('topic.oled',accepted(classify(d),1))

    def test_fulltext_focus_has_no_modifier_expansion(self):
        self.assertIsNone(FOCUS.search('Singlet-triplet gaps were for the first time studied.'))
        d=document(text='Singlet-triplet gaps were for the first time studied.')
        d['chunks'][0]['section']='unknown'
        self.assertNotIn('question.deltaest',accepted(classify(d),2))
