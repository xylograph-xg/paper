"""Optical emitting dipoles are not arbitrary magnetic/electric dipole objects."""
from copy import deepcopy
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted

LABEL='question.emitter_orientation'


class EmittingDipoleOrientationTests(unittest.TestCase):
    def test_explicit_forward_and_reverse_phrases(self):
        for phrase in ['emitting dipole orientation','emitting dipole orientations',
                       'orientation of the emitting dipoles','orientation of emission dipoles',
                       'orientations of emitting transition dipoles','emission transition dipole orientation']:
            with self.subTest(phrase=phrase):
                d=document(text='We investigate '+phrase+' in the optical film.');r=classify(d)
                self.assertIn(LABEL,{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_metadata_centrality_reuses_accepted_body(self):
        d=document(abstract='We determine the orientation of emitting dipoles.',text='The emitter has a similar orientation distribution.')
        d['chunks'][0]['section']='methods';r=classify(d)
        self.assertIn(LABEL,{l['id'] for l in r['level2']})
        self.assertTrue(all(e['scope']=='fulltext' for l in r['level2'] for e in l['evidence']));validate_evidence(d,r)

    def test_metadata_alone_never_supplies_level2(self):
        self.assertNotIn(LABEL,accepted(classify(document(title='Emitting dipole orientation',abstract='We determine orientation of emitting dipoles.',text='We measure absorption.')),2))

    def test_generic_caption_stays_auxiliary(self):
        d=document(text='Calculated values for the orientation of emitting dipoles.');d['chunks'][0]['section']='methods'
        r=classify(d);self.assertIn(LABEL,accepted(r,2));self.assertNotIn(LABEL,{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_nonemissive_dipoles_and_word_boundaries_are_excluded(self):
        for phrase in ['magnetic dipole orientation','permanent electric dipole orientation',
                       'orientation of electric dipoles','orientation of the emitting particles',
                       'orientation of emitting dipolesish','reemitting dipole orientation',
                       'emitting dipole orientationish']:
            with self.subTest(phrase=phrase):self.assertNotIn(LABEL,accepted(classify(document(text='We investigate '+phrase+'.')),2))

    def test_negated_actual_measurement_is_not_new_body_evidence(self):
        for phrase in ['We did not measure emitting dipole orientation.',
                       'The orientation of emitting dipoles was not measured.',
                       'We never determined orientation of the emitting dipoles.']:
            with self.subTest(phrase=phrase):
                d=document(text=phrase);r=classify(d);self.assertNotIn(LABEL,accepted(r,2));validate_evidence(d,r)
                e=next(l for l in r['mentions'] if l['id']==LABEL)['evidence'][0]
                self.assertTrue(e['orientation_alias']['negated'])

    def test_not_only_and_contrast_scope_keep_actual_positive(self):
        d=document(text='We measured not only emitting dipole orientation but also absorption.')
        self.assertIn(LABEL,accepted(classify(d),2))
        d=document(text='We did not measure emitting dipole orientation; we determined orientation of the emitting dipoles by modeling.')
        r=classify(d);self.assertIn(LABEL,accepted(r,2));validate_evidence(d,r)

    def test_history_and_numbered_bibliography_do_not_supply_body(self):
        for text in ['Previously, we determined emitting dipole orientation.',
                     '(9) Smith, A.; Jones, B. Emitting Dipole Orientation in Films.']:
            with self.subTest(text=text):self.assertNotIn(LABEL,accepted(classify(document(text=text)),2))

    def test_reference_and_keyword_source_guards_remain(self):
        for section,text in [('references','We investigate emitting dipole orientation.'),
                             ('supporting information','KEYWORDS: orientation of the emitting dipoles')]:
            with self.subTest(section=section):
                d=document(text=text);d['chunks'][0]['section']=section;self.assertNotIn(LABEL,accepted(classify(d),2))

    def test_unicode_layout_offsets_and_trace_are_exact(self):
        term='orientation\u00a0of the emitting\n dipoles';d=document(text='We investigate '+term+'.');r=classify(d)
        e=next(l for l in r['level2'] if l['id']==LABEL)['evidence'][0]
        self.assertEqual(e['matched_text'],term);self.assertFalse(e['orientation_alias']['negated']);validate_evidence(d,r)
        for key,value in [('text','invented'),('start',1),('hit_end',1),('negated',True)]:
            changed=deepcopy(r);next(l for l in changed['level2'] if l['id']==LABEL)['evidence'][0]['orientation_alias'][key]=value
            with self.assertRaisesRegex(ValueError,'发射偶极'):validate_evidence(d,changed)

    def test_legacy_alias_and_old_evidence_are_independent(self):
        d=document(text='We investigate transition dipole orientation.')
        d['chunks'].append({'id':'negative','scope':'fulltext','page':2,'section':'results',
                            'text':'We did not measure orientation of emitting dipoles.'})
        r=classify(d);self.assertIn(LABEL,accepted(r,2))
        self.assertIn(LABEL,{l['id'] for l in r['mentions']});validate_evidence(d,r)

    def test_new_concept_does_not_infer_material_or_other_mechanisms(self):
        r=classify(document(text='We investigate orientation of emitting dipoles.'))
        self.assertEqual({l['id'] for l in r['level2']},{LABEL});self.assertFalse(r['level1'])
