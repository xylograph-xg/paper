"""Time-resolved optical method word forms, with unchanged admission/core gates."""
import unittest
from literature.classifier import classify,validate_evidence,PATTERNS,canonical
from literature.tests.test_context import document,accepted

LABEL='method.time_resolved'


class TimeResolvedAliasTests(unittest.TestCase):
    def test_full_words_and_pl_alias_have_exact_body_evidence(self):
        for phrase in ['time-resolved photoluminescence','time-resolved fluorescence',
                       'time-resolved PL','time-resolved spectroscopy',
                       'transient photoluminescence','transient phosphorescent decays',
                       'fluorescence decay curves','photoluminescence decay measurements']:
            with self.subTest(phrase=phrase):
                d=document(text='We measured '+phrase+' in our films.',title=phrase+' study')
                r=classify(d);label=next(x for x in r['level2'] if x['id']==LABEL)
                self.assertEqual(label['evidence'][0]['matched_text'],phrase)
                self.assertEqual(label['evidence'][0]['relation'],'used')
                validate_evidence(d,r)

    def test_line_wrapping_and_unicode_hyphens_keep_original_offsets(self):
        for phrase in ['time-resolved\nphotoluminescence','time–resolved PL',
                       'time-resolved photolumines-\ncence']:
            with self.subTest(phrase=phrase):
                d=document(text='We measured '+phrase+' spectra.',title='Time-resolved PL study')
                r=classify(d);e=next(x for x in r['level2'] if x['id']==LABEL)['evidence'][0]
                self.assertEqual(e['matched_text'],phrase);validate_evidence(d,r)

    def test_no_unbounded_stem_or_nonoptical_decay_alias(self):
        for phrase in ['time-resolved PLastic','time-resolved photoluminescently',
                       'time-resolved fluorescenceXYZ','transient population decays',
                       'transient thermal decays','transient absorption',
                       'fluorescence decay measurementsXYZ']:
            with self.subTest(phrase=phrase):
                self.assertIsNone(PATTERNS[LABEL].search(canonical(phrase)[0]))

    def test_lexical_hit_does_not_bypass_current_use_or_history(self):
        for text in ['Time-resolved PL is a common technique.',
                     'Previously we measured time-resolved PL.',
                     'We did not measure time-resolved PL.']:
            with self.subTest(text=text):
                r=classify(document(text=text,title='Time-resolved PL study'))
                self.assertNotIn(LABEL,accepted(r,2))

    def test_routine_measurement_still_supporting(self):
        d=document(text='We measured time-resolved PL spectra in these films.')
        r=classify(d)
        self.assertNotIn(LABEL,{x['id'] for x in r['level2']})
        self.assertIn(LABEL,{x['id'] for x in r['supporting_labels']})
        validate_evidence(d,r)

    def test_metadata_cannot_supply_missing_body_method(self):
        r=classify(document(title='Time-resolved PL study',abstract='We measured time-resolved PL.'))
        self.assertNotIn(LABEL,accepted(r,2))
        self.assertNotIn(LABEL,accepted(r,1))

    def test_preexisting_short_aliases_remain_recognized(self):
        for phrase in ['time-resolved emission','transient PL','transient decay',
                       'emission decay profile']:
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(PATTERNS[LABEL].search(canonical(phrase)[0]))

    def test_new_forms_share_accepted_negation_and_contrast_guards(self):
        for phrase in ['time-resolved PL','time-resolved fluorescence',
                       'transient phosphorescent decays','photoluminescence decay curves']:
            for text,used in [('We did not measure '+phrase+'.',False),
                              (phrase+' was not measured.',False),
                              ('We did not use DFT and record '+phrase+'.',False),
                              ('We did not use DFT but recorded '+phrase+'.',True),
                              ('We not only measured '+phrase+' but also performed DFT.',True)]:
                with self.subTest(text=text):
                    d=document(text=text,title=phrase+' study');r=classify(d)
                    self.assertEqual(LABEL in accepted(r,2),used)
                    validate_evidence(d,r)
