"""Journal Society abbreviations cannot provide spin-orbit coupling evidence."""
import unittest
from copy import deepcopy
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted

LABEL='mechanism.soc'


class SocJournalDisambiguationTests(unittest.TestCase):
    def doc(self,text):return document(text=text,abstract='We investigate spin-orbit coupling in emitters.')

    def test_soc_journal_and_year_is_not_physical_evidence(self):
        for text in ['Bull. Korean Chem. Soc. 2011, Vol. 32, No. 3.',
                     'J. Am. Chem. Soc. 2022, 144, 123-130.',
                     'J. Electrochem. Soc. 2019, 166, 1-5.',
                     'J. Phys. Soc. Jpn. 2020, 89, 123.',
                     'J. R. Soc. 2005, 1, 22.']:
            with self.subTest(text=text):
                d=self.doc(text);r=classify(d);self.assertNotIn(LABEL,accepted(r,2))
                self.assertIn(LABEL,{l['id'] for l in r['mentions']});validate_evidence(d,r)

    def test_uppercase_journal_printing_is_also_ambiguous(self):
        d=self.doc('J. AM. CHEM. SOC. 2021, 12, 15.');r=classify(d)
        self.assertNotIn(LABEL,accepted(r,2));validate_evidence(d,r)

    def test_physical_acronym_survives_all_original_cases(self):
        for term in ['SOC','soc','Soc']:
            with self.subTest(term=term):
                d=self.doc('We investigate '+term+' in the excited states.');r=classify(d)
                self.assertIn(LABEL,accepted(r,2));validate_evidence(d,r)

    def test_full_scientific_name_is_not_rejected(self):
        d=self.doc('We calculate spin-orbit coupling matrix elements.');r=classify(d)
        self.assertIn(LABEL,accepted(r,2));validate_evidence(d,r)

    def test_no_ban_without_both_journal_and_date_context(self):
        for text in ['We report SOC. The states have mixed character.',
                     'SOC. 2021 was the measurement year.',
                     'We measured SOC in 2021.',
                     'Chem. SOC measurements reveal spin mixing.']:
            with self.subTest(text=text):self.assertIn(LABEL,accepted(classify(self.doc(text)),2))

    def test_journal_rejection_does_not_veto_later_true_soc(self):
        d=self.doc('J. Am. Chem. Soc. 2022, 12, 24. We investigate SOC in these molecules.')
        r=classify(d);self.assertIn(LABEL,accepted(r,2))
        self.assertFalse(any('acronym_disambiguation' in e for l in r['level2'] if l['id']==LABEL for e in l['evidence']))
        self.assertTrue(any('acronym_disambiguation' in e for l in r['mentions'] if l['id']==LABEL for e in l['evidence']));validate_evidence(d,r)

    def test_journal_rejection_does_not_veto_earlier_full_name(self):
        d=self.doc('We report spin-orbit coupling in emitters. J. Am. Chem. Soc. 2023, 12, 24.')
        r=classify(d);self.assertIn(LABEL,accepted(r,2));validate_evidence(d,r)

    def test_history_guard_is_not_relaxed(self):
        d=self.doc('Previously, SOC was investigated in these materials. J. Am. Chem. Soc. 2023, 12, 24.')
        self.assertNotIn(LABEL,accepted(classify(d),2))

    def test_metadata_still_cannot_supply_body_evidence(self):
        r=classify(document(abstract='We investigate SOC in emitters.'))
        self.assertNotIn(LABEL,accepted(r,2))

    def test_pdf_line_break_and_original_trace_are_preserved(self):
        text='J. Am. Chem.\nSoc.\n2022, 144, 100.';d=self.doc(text);r=classify(d)
        e=next(l for l in r['mentions'] if l['id']==LABEL)['evidence'][0]
        trace=e['acronym_disambiguation'];self.assertEqual(text[trace['start']:trace['end']],trace['text'])
        self.assertEqual(e['matched_text'],'Soc');validate_evidence(d,r)

    def test_rejection_trace_tampering_is_detected(self):
        d=self.doc('J. Am. Chem. Soc. 2020, 144, 100.');r=classify(d);broken=deepcopy(r)
        e=next(l for l in broken['mentions'] if l['id']==LABEL)['evidence'][0]
        e['acronym_disambiguation']['text']='changed'
        with self.assertRaises(ValueError):validate_evidence(d,broken)

    def test_more_than_two_journal_hits_are_retained(self):
        text='J. Am. Chem. Soc. 2020, 1, 2.\nJ. Am. Chem. Soc. 2021, 1, 2.\nJ. Am. Chem. Soc. 2022, 1, 2.'
        d=self.doc(text);r=classify(d);self.assertNotIn(LABEL,accepted(r,2))
        e=next(l for l in r['mentions'] if l['id']==LABEL)['evidence'];self.assertEqual(len(e),3);validate_evidence(d,r)
