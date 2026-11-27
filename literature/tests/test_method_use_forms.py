"""Method-use complete words and explicit nominal experimental result evidence."""
import unittest
from literature.classifier import classify,validate_evidence,METHOD_USE
from literature.tests.test_context import document,accepted


class MethodUseFormTests(unittest.TestCase):
    def test_complete_operation_forms_and_existing_nouns_retained(self):
        for word in ['measure','measures','measured','measuring','measurement','measurements',
                     'record','records','recorded','recording','recordings','perform','performs','performed','performing',
                     'calculate','calculates','calculated','calculating','calculation','calculations',
                     'determine','determined','determination','determinations','obtain','obtained','obtaining',
                     'conduct','conducted','conducting','fabricate','fabricated','fabrication','fabrications',
                     'deposit','deposited','deposition','depositions','spin-coat','spin-coated','spin-coating']:
            with self.subTest(word=word):self.assertIsNotNone(METHOD_USE.fullmatch(word))

    def test_accidental_stem_words_and_suffixes_are_not_use_evidence(self):
        for word in ['performance','performances','performer','performative','conductivity',
                     'calculatedness','calculative','determinate','depository','measurability',
                     'measurementXYZ','recordedXYZ','fabricative']:
            with self.subTest(word=word):self.assertIsNone(METHOD_USE.search(word))

    def test_broad_stem_alone_cannot_admit_a_method(self):
        for text in ['We discuss transient PL performance in films.',
                     'Transient absorption conductivity is discussed here.',
                     'We discuss transient PL measurability.']:
            with self.subTest(text=text):
                d=document(text=text,title='Transient PL and transient absorption study');r=classify(d)
                self.assertFalse({'method.time_resolved','method.transient_absorption'}&accepted(r,2))
                validate_evidence(d,r)

    def test_method_subject_result_supplies_use_without_accidental_performance(self):
        for text in ['Our time-resolved PL experiments link the emission lifetime to charge trapping.',
                     'Time-resolved PL experiments linked the high performance to energy transfer.']:
            with self.subTest(text=text):
                self.assertIsNone(METHOD_USE.search(text))
                d=document(text=text);r=classify(d)
                label=next(x for x in r['level2'] if x['id']=='method.time_resolved')
                self.assertEqual(label['evidence'][0]['focus_text'],text)
                self.assertEqual(label['evidence'][0]['relation'],'used');validate_evidence(d,r)

    def test_nominal_result_does_not_rescue_unsupported_or_hypothetical_use(self):
        for text in ['Time-resolved PL experiments may link performance to energy transfer.',
                     'Previously time-resolved PL experiments linked performance to energy transfer.',
                     'Time-resolved PL experiments did not link performance to energy transfer.',
                     'Time-resolved PL experiments link performance to sample identifiers.',
                     'We discuss time-resolved PL experiments and their performance.']:
            with self.subTest(text=text):self.assertNotIn('method.time_resolved',accepted(classify(document(text=text)),2))

    def test_normal_operations_captions_and_core_separation_retained(self):
        for text in ['We measured transient PL.','Transient PL measurements are presented here.',
                     'Figure 3: Transient PL spectra.']:
            with self.subTest(text=text):
                d=document(text=text);r=classify(d);self.assertIn('method.time_resolved',accepted(r,2))
                self.assertNotIn('method.time_resolved',{x['id'] for x in r['level2']});validate_evidence(d,r)

    def test_metadata_does_not_supply_body_method_use(self):
        d=document(abstract='Time-resolved PL experiments link performance to energy transfer.')
        self.assertEqual(classify(d)['level2'],[])
