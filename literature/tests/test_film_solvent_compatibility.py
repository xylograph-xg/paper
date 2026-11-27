"""Film solvent compatibility is separate from generic molecular solubility."""
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted

LABEL='question.solvent_orthogonality'


class FilmSolventCompatibilityTests(unittest.TestCase):
    def test_explicit_film_compatibility_questions_are_covered(self):
        for term in ['solvent orthogonality','orthogonal solvents','layer intermixing',
                     'interlayer mixing','solubility of the thin films',
                     'resistance to alcohol solvents','solvent rinsing test']:
            with self.subTest(term=term):
                d=document(text='We investigated '+term+' in multilayer devices.')
                r=classify(d);self.assertIn(LABEL,{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_molecular_solubility_alone_does_not_establish_layer_compatibility(self):
        for text in ['We investigated molecular solubility in toluene.',
                     'We measured absorption in solution.',
                     'We fabricated spin-coated devices with a soluble emitter.',
                     'We observed exciton mixing and layer thickness changes.']:
            self.assertNotIn(LABEL,accepted(classify(document(text=text)),2))

    def test_abstract_cannot_supply_missing_original_text(self):
        d=document(abstract='We investigate solvent orthogonality.',text='We measured absorption.')
        self.assertNotIn(LABEL,accepted(classify(d),2))

    def test_previous_work_stays_mentioned(self):
        d=document(text='Previous work investigated layer intermixing.')
        r=classify(d);self.assertNotIn(LABEL,accepted(r,2));self.assertIn(LABEL,{l['id'] for l in r['mentions']})

    def test_background_film_issue_does_not_become_core(self):
        d=document(text='In general, solvent orthogonality limits processing.')
        r=classify(d);self.assertNotIn(LABEL,{l['id'] for l in r['level2']});self.assertIn(LABEL,accepted(r,2))

    def test_bibliography_and_exact_layout_boundaries(self):
        d=document(text='We investigated solvent\northogonality in multilayer devices.')
        r=classify(d);self.assertIn(LABEL,accepted(r,2));validate_evidence(d,r)
        d['chunks'][0]['section']='references'
        self.assertNotIn(LABEL,accepted(classify(d),2))
