"""Triplet host compatibility and bipolar architecture are distinct targets."""
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted

TRIPLET='question.triplet_energy_confinement'
BIPOLAR='question.bipolar_charge_transport'


class HostEnergyTransportTests(unittest.TestCase):
    def test_explicit_host_triplet_compatibility_evidence(self):
        for text in ['We investigate the triplet energy gradient between host and emitter.',
                     'We designed host materials with a high T1 level.',
                     'We reveal that the T1 energy of the emitter is incompatible with these hosts.']:
            d=document(text=text);r=classify(d)
            self.assertIn(TRIPLET,{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_t1_measurement_and_generic_bandgap_are_not_confinement(self):
        for text in ['We measured the T1 energy at 77 K.',
                     'We increased the host HOMO-LUMO energy gap.',
                     'We reduced singlet-triplet gaps of the emitters.',
                     'We investigated electronic confinement in a quantum dot.']:
            self.assertNotIn(TRIPLET,accepted(classify(document(text=text)),2))

    def test_bipolar_design_requires_both_carriers_or_explicit_role(self):
        for text in ['We designed bipolar green host materials.',
                     'We designed the host by combining both of the hole-transporting carbazole and electron-transporting imidazole in one structure.']:
            d=document(text=text);r=classify(d)
            self.assertIn(BIPOLAR,{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_single_carrier_and_unrelated_bipolar_system_are_insufficient(self):
        for text in ['We designed electron-transporting host materials.',
                     'We measured hole mobility in a host.',
                     'We studied bipolar neurons.',
                     'We designed a donor-acceptor emitter.']:
            self.assertNotIn(BIPOLAR,accepted(classify(document(text=text)),2))

    def test_two_questions_do_not_imply_each_other(self):
        self.assertNotIn(TRIPLET,accepted(classify(document(text='We designed bipolar host materials.')),2))
        self.assertNotIn(BIPOLAR,accepted(classify(document(text='We investigate triplet energy confinement.')),2))

    def test_metadata_does_not_supply_missing_body_question(self):
        r=classify(document(title='Bipolar hosts with triplet energy confinement',text='We measured emission spectra.'))
        self.assertFalse({TRIPLET,BIPOLAR}&accepted(r,2))

    def test_history_and_generic_background_remain_separate(self):
        d=document(text='Previous work designed bipolar hosts with a high T1 level.')
        self.assertFalse({TRIPLET,BIPOLAR}&accepted(classify(d),2))
        d=document(text='In general, triplet energy confinement limits efficiency.')
        r=classify(d);self.assertNotIn(TRIPLET,{l['id'] for l in r['level2']})

    def test_layout_keeps_exact_original_text(self):
        d=document(text='We investigate the triplet\nenergy gradient between host and guest.')
        r=classify(d);self.assertIn(TRIPLET,accepted(r,2));validate_evidence(d,r)
