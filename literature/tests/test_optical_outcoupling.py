"""Outcoupling, optical modeling and actual angular EL remain distinct."""
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted

TOPIC='topic.oled_optical_outcoupling'
QUESTION='question.light_outcoupling'
MODEL='method.optical_halfspace_model'
ANGULAR='method.angle_resolved_el'


class OpticalOutcouplingTests(unittest.TestCase):
    def test_oled_direction_is_metadata_domain_qualified(self):
        d=document(title='Surface out-coupling in OLEDs');r=classify(d)
        self.assertIn(TOPIC,accepted(r,1));validate_evidence(d,r)
        self.assertNotIn(TOPIC,accepted(classify(document(title='Optical outcoupling in a laser cavity')),1))

    def test_body_domain_cannot_supply_level1_context(self):
        d=document(title='Optical outcoupling',text='We investigate OLEDs.')
        self.assertNotIn(TOPIC,accepted(classify(d),1))

    def test_surface_emission_patterns_have_their_own_direction(self):
        r=classify(document(title='Electroluminescence emission pattern of organic light-emitting diodes'))
        self.assertIn(TOPIC,accepted(r,1))

    def test_outcoupling_is_not_internal_quantum_efficiency(self):
        for text in ['We increase charge recombination efficiency.',
                     'We investigate internal quantum efficiency.',
                     'We improve external quantum efficiency.']:
            self.assertNotIn(QUESTION,accepted(classify(document(text=text)),2))
        self.assertIn(QUESTION,accepted(classify(document(text='We investigate surface out-coupling efficiency.')),2))

    def test_half_space_model_requires_optical_context_and_use(self):
        d=document(title='Half-space optical model',text='We used a half-space model in our optical simulation.')
        r=classify(d);self.assertIn(MODEL,accepted(r,2));validate_evidence(d,r)
        self.assertNotIn(MODEL,accepted(classify(document(text='We used a half-space model in a topology proof.')),2))

    def test_method_requires_body_evidence_even_when_named_in_title(self):
        d=document(title='Angle-resolved EL and half-space optical model',text='We measured current density.')
        self.assertFalse({MODEL,ANGULAR}&accepted(classify(d),2))

    def test_named_angular_el_is_actual_measurement(self):
        d=document(title='Angle-resolved electroluminescence',text='We measured angle-resolved electroluminescence.')
        r=classify(d);self.assertIn(ANGULAR,{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_surface_edge_measurement_needs_angles_in_same_evidence(self):
        text='We measure the surface- and edge-emitted photon fluxes from the OLED at external angles.'
        d=document(title='EL emission patterns of OLEDs',text=text);r=classify(d)
        self.assertIn(ANGULAR,{l['id'] for l in r['level2']});validate_evidence(d,r)
        self.assertNotIn(ANGULAR,accepted(classify(document(text='We measure surface- and edge-emitted photon fluxes.')),2))

    def test_ordinary_el_spectrum_and_angular_simulation_are_not_measurements(self):
        for text in ['We measured the EL spectra.',
                     'We simulated angular emission patterns with an optical model.']:
            self.assertNotIn(ANGULAR,accepted(classify(document(text=text)),2))

    def test_history_and_negated_method_use_stay_protected(self):
        for text in ['Previous work measured angle-resolved electroluminescence.',
                     'We did not measure angle-resolved electroluminescence.']:
            self.assertNotIn(ANGULAR,accepted(classify(document(text=text)),2))

    def test_question_and_model_do_not_imply_measured_angular_el(self):
        r=classify(document(text='We used a half-space optical model to investigate light outcoupling.'))
        self.assertIn(MODEL,accepted(r,2));self.assertIn(QUESTION,accepted(r,2));self.assertNotIn(ANGULAR,accepted(r,2))

    def test_original_newline_layout_is_retained(self):
        d=document(title='Outcoupling of OLEDs',text='We investigate surface out-\ncoupling efficiency.')
        r=classify(d);self.assertIn(QUESTION,accepted(r,2));validate_evidence(d,r)
