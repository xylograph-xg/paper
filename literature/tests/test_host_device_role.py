"""Controlled material-host role aliases, never an unrestricted bare host."""
from copy import deepcopy
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted

LABEL='object.host'


class HostDeviceRoleTests(unittest.TestCase):
    def test_explicit_device_material_role_in_title_is_core(self):
        for phrase in ['Host for OLEDs','Hosts for blue PhOLEDs',
                       'Host for white phosphorescent organic light-emitting diodes',
                       'Emitter and host for high-performance organic light emitting diodes']:
            with self.subTest(phrase=phrase):
                d=document(title=phrase);r=classify(d)
                self.assertIn(LABEL,{l['id'] for l in r['level1']});validate_evidence(d,r)

    def test_current_abstract_role_still_uses_original_ownership(self):
        d=document(abstract='We report a host for green OLEDs.');r=classify(d)
        self.assertIn(LABEL,accepted(r,1));validate_evidence(d,r)
        self.assertNotIn(LABEL,accepted(classify(document(abstract='A host for green OLEDs is available.')),1))

    def test_hypothetical_negative_and_historical_roles_are_not_admitted(self):
        for phrase in ['Previously reported host for OLEDs','Smith et al. developed a host for OLEDs',
                       'A material might be a host for OLEDs','If a host for OLEDs becomes available',
                       'We do not report a host for OLEDs','A host for OLEDs was not synthesized',
                       'No host for OLEDs','Future host for OLEDs']:
            for scope in ['title','abstract']:
                with self.subTest(phrase=phrase,scope=scope):
                    self.assertNotIn(LABEL,accepted(classify(document(**{scope:phrase})),1))

    def test_nonmaterial_host_and_events_are_not_material_evidence(self):
        for phrase in ['Biological host for OLEDs','Institutional host for OLEDs',
                       'Computer host for OLEDs','Host for OLED workshops',
                       'Host for OLED research','Host for OLED conferences']:
            with self.subTest(phrase=phrase):
                self.assertNotIn(LABEL,accepted(classify(document(title=phrase)),1))

    def test_bare_host_and_other_device_uses_are_not_new_aliases(self):
        for phrase in ['A host','A new host design','Host for solar cells','Host organism',
                       'Host institution','Host for OLEDish devices','Ghost for OLEDs']:
            with self.subTest(phrase=phrase):self.assertNotIn(LABEL,accepted(classify(document(title=phrase)),1))

    def test_fulltext_cannot_supply_level1(self):
        self.assertNotIn(LABEL,accepted(classify(document(text='We report a host for OLEDs.')),1))

    def test_no_topic_or_fine_mechanism_is_inferred(self):
        r=classify(document(title='Host for OLEDs'))
        self.assertIn(LABEL,accepted(r,1));self.assertFalse(r['level2'])
        self.assertFalse({'topic.tadf','topic.phosphorescence'} & accepted(r,1))

    def test_new_alias_review_and_current_role_contrasted_with_history(self):
        for phrase in ['Review of hosts for OLEDs','We review hosts for OLEDs']:
            with self.subTest(phrase=phrase):self.assertIn(LABEL,accepted(classify(document(title=phrase)),1))
        d=document(title='Previously reported host for OLEDs',abstract='We develop a host for OLEDs.')
        r=classify(d);self.assertIn(LABEL,accepted(r,1));validate_evidence(d,r)

    def test_unicode_positions_and_guard_trace_are_exact(self):
        phrase='Host\u00a0for white phosphorescent organic light\u2010emitting diodes'
        d=document(title=phrase);r=classify(d);label=next(l for l in r['level1'] if l['id']==LABEL)
        e=label['evidence'][0];self.assertEqual(e['matched_text'],phrase)
        self.assertTrue(e['host_device_role']['eligible']);validate_evidence(d,r)
        for key,value in [('text','invented'),('start',1),('end',2),('hit_start',1),('eligible',False)]:
            changed=deepcopy(r);next(l for l in changed['level1'] if l['id']==LABEL)['evidence'][0]['host_device_role'][key]=value
            with self.assertRaisesRegex(ValueError,'主体角色'):validate_evidence(d,changed)

    def test_rejected_new_hit_retained_beside_independent_legacy_alias(self):
        d=document(title='New host materials',abstract='Previously we reported a host for OLEDs.')
        r=classify(d);self.assertIn(LABEL,accepted(r,1))
        e=next(l for l in r['mentions'] if l['id']==LABEL)['evidence'][0]
        self.assertFalse(e['host_device_role']['eligible']);self.assertEqual(e['relation'],'mentioned');validate_evidence(d,r)

    def test_legacy_host_aliases_and_local_negative_are_preserved(self):
        for phrase in ['Bipolar host','Triplet hosts','Host molecules','Universal host','Host materials']:
            with self.subTest(phrase=phrase):self.assertIn(LABEL,accepted(classify(document(title=phrase)),1))
        self.assertNotIn(LABEL,accepted(classify(document(title='Host-free OLEDs')),1))

    def test_beyond_comparison_is_local_to_new_alias_hit(self):
        self.assertNotIn(LABEL,accepted(classify(document(title='Beyond host for OLEDs')),1))
        r=classify(document(title='Beyond host for OLEDs: new host materials'))
        self.assertIn(LABEL,accepted(r,1));validate_evidence(document(title='Beyond host for OLEDs: new host materials'),r)
