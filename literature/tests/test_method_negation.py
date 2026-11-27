"""Method use must own its predicate polarity; no real-paper IDs or answers."""
import unittest
from literature.classifier import classify,validate_evidence,method_use_negated
from literature.tests.test_context import document,accepted


class MethodNegationTests(unittest.TestCase):
    def test_active_denial_is_only_exact_mention(self):
        for text in ['We did not measure transient PL.',"We didn't measure transient PL.",
                     'We never recorded transient PL.','We could not reliably measure transient PL.',
                     'We cannot measure transient PL.','We no longer use transient PL.']:
            with self.subTest(text=text):
                d=document(text=text,title='Transient PL study');r=classify(d)
                self.assertNotIn('method.time_resolved',accepted(r,2))
                e=next(x for x in r['mentions'] if x['id']=='method.time_resolved')['evidence'][0]
                self.assertEqual(e['basis'],'negated_method_use');self.assertEqual(e['relation'],'mentioned')
                self.assertEqual(e['focus_text'],text);validate_evidence(d,r)

    def test_passive_denial_and_no_method(self):
        for text in ['Transient PL was not measured.','Transient PL measurements were never performed.',
                     'DFT calculations were not performed.','DFT was not used.',
                     'No DFT calculations were performed.','We recorded spectra without using DFT.']:
            with self.subTest(text=text):
                r=classify(document(text=text,title='DFT and transient PL study'))
                self.assertFalse({'method.time_resolved','method.dft'}&accepted(r,2))

    def test_contrast_does_not_borrow_denial(self):
        for text in ['We did not use DFT but measured transient PL.',
                     'DFT was not used, whereas transient PL was recorded.',
                     'Without DFT, we measured transient PL.',
                     'We did not perform DFT and measured transient PL.',
                     'We recorded transient PL but did not use DFT.']:
            with self.subTest(text=text):
                d=document(text=text,title='DFT and transient PL study');r=classify(d)
                self.assertNotIn('method.dft',accepted(r,2));self.assertIn('method.time_resolved',accepted(r,2))
                validate_evidence(d,r)

    def test_coordinated_method_nouns_share_denied_predicate(self):
        for text in ['We did not use DFT or transient PL.',
                     'We never measured transient PL and DFT.',
                     'We did not use DFT and record transient PL.',
                     'We did not measure transient PL or perform DFT.']:
            with self.subTest(text=text):
                self.assertFalse({'method.time_resolved','method.dft'}&accepted(classify(document(text=text)),2))

    def test_not_only_and_nonuse_predicate_negation_keep_actual_method(self):
        for text in ['We not only measured transient PL but also performed DFT.',
                     'We used not only DFT but also transient PL.',
                     'Transient PL measurements were not only performed but also repeated.',
                     'We measured transient PL, which did not show a long lifetime.',
                     'DFT calculations did not predict the measured bandgap.']:
            with self.subTest(text=text):
                r=classify(document(text=text,title='DFT and transient PL study'))
                label='method.dft' if text.startswith('DFT') else 'method.time_resolved'
                self.assertIn(label,accepted(r,2))

    def test_negated_first_occurrence_does_not_hide_later_actual_use(self):
        d=document(text='We did not measure transient PL in solution. We measured transient PL in films.',title='Transient PL study')
        r=classify(d);e=next(x for x in r['level2'] if x['id']=='method.time_resolved')['evidence']
        self.assertEqual(len(e),1);self.assertIn('in films',e[0]['focus_text']);validate_evidence(d,r)

    def test_nonmethod_and_missing_body_are_not_rescued(self):
        d=document(text='We investigate RISC, but did not use DFT.',abstract='We performed DFT.',title='RISC study')
        r=classify(d);self.assertIn('mechanism.risc',accepted(r,2));self.assertNotIn('method.dft',accepted(r,2))
        self.assertEqual(classify(document(abstract='We performed DFT.'))['level2'],[])

    def test_polarity_helper_is_local_and_not_scientific_verification(self):
        for text,denied in [('We did not perform DFT.',True),('We not only performed DFT.',False),
                            ('We measured PL without DFT.',True),('Without DFT, we used PL.',False)]:
            hit='PL' if text.endswith('PL.') else 'DFT';a=text.index(hit)
            self.assertEqual(method_use_negated(text,a,a+len(hit)),denied)
