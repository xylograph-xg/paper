"""Generic scientific invariants and actual reader/contract integration."""
import copy
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from reading.science_verifier import audit_card, bounded_audit, check_dimensions, compare_assignment, math_spans, parse_math, Unsupported, runtime_identity, VERSIONS
from reading.reading_failures import diagnostics
from read.app.generation_state import generation_complete, METADATA_STAGES


class FormulaTests(unittest.TestCase):
    def test_actual_dependency(self):
        self.assertEqual(runtime_identity(), VERSIONS)

    def test_equivalent_reordering(self):
        self.assertEqual(compare_assignment('x=a+b', 'x=b+a'), 'equivalent')

    def test_fraction_reordering(self):
        self.assertEqual(compare_assignment(r'x=\frac{a}{2}b^2', r'x=\frac{b^2a}{2}'), 'equivalent')

    def test_denominator_reversal(self):
        self.assertEqual(compare_assignment(r'q=\frac{t}{8}w^2', r'q=\frac{t}{8w^2}'), 'different_forms')

    def test_power_changed(self):
        self.assertEqual(compare_assignment('q=t*w^2','q=t*w'), 'different_forms')

    def test_configuration_is_not_product(self):
        self.assertTrue(parse_math(r'\omega^{AA}').is_Symbol)
        self.assertNotEqual(parse_math(r'\omega^{AA}'), parse_math(r'\omega^{BB}'))
        self.assertEqual(compare_assignment(r'q=\omega^{AA}',r'q=\omega^{BB}'), 'different_forms')

    def test_index_changed(self):
        self.assertEqual(compare_assignment('q=E_{0}', 'q=E_{1}'), 'different_forms')

    def test_brace_equivalence(self):
        self.assertEqual(compare_assignment('q=E_0', 'q=E_{0}'), 'equivalent')

    def test_superscript_position(self):
        self.assertEqual(compare_assignment(r'q=\epsilon_{2}^{iso}',r'q=\epsilon_{iso}^2'), 'different_forms')

    def test_state_superscript_unknown(self):
        self.assertEqual(compare_assignment('q=E_{a}^{1}', 'q=E_{a}'), 'unsupported')

    def test_target_changed(self):
        self.assertEqual(compare_assignment('x=a', 'y=a'), 'different_target')

    def test_malformed_never_partial_success(self):
        self.assertEqual(compare_assignment('x=a+', 'x=a'), 'unsupported')

    def test_matrix_is_unknown(self):
        self.assertEqual(compare_assignment(r'x=\begin{matrix}a\end{matrix}', 'x=a'), 'unsupported')

    def test_unsupported_function(self):
        self.assertEqual(compare_assignment('f(t)=a', 'f(t)=b'), 'unsupported')

    def test_numeric_exponent_budget(self):
        with self.assertRaises(Unsupported):
            parse_math('x=2^{99999999}')

    def test_no_python_execution(self):
        self.assertEqual(compare_assignment("x=__import__('os').system('pwd')", 'x=0'), 'unsupported')

    def test_math_delimiters(self):
        self.assertEqual(math_spans(r'$x=a$ and \(x=b\) and $$x=c$$'), ['x=a','x=b','x=c'])


class DimensionTests(unittest.TestCase):
    definitions = {'v': {'length':1,'time':-1}, 'x':{'length':1}, 't':{'time':1}}

    def test_consistent_units(self):
        self.assertEqual(check_dimensions('v=x/t',self.definitions)['state'], 'consistent')

    def test_inconsistent_units(self):
        self.assertEqual(check_dimensions('v=x*t',self.definitions)['state'], 'inconsistent')

    def test_missing_units_unknown(self):
        self.assertEqual(check_dimensions('v=x/t',{'x':{'length':1}})['state'], 'unknown')

    def test_incompatible_addition(self):
        self.assertEqual(check_dimensions('v=x+t',self.definitions)['state'], 'inconsistent')

    def test_rate_and_time(self):
        definitions={'k':{'time':-1},'t':{'time':1},'w':{'time':-1}}
        self.assertEqual(check_dimensions('k=t*w^2',definitions)['state'], 'consistent')
        self.assertEqual(check_dimensions('k=t/w^2',definitions)['state'], 'inconsistent')

    def test_invalid_declaration_unknown(self):
        self.assertEqual(check_dimensions('v=x/t',{'v':{'bananas':1}})['state'], 'unknown')


class EvidenceIntegrationTests(unittest.TestCase):
    def fixture(self):
        card={'meta':{},'intro_summary':r'An estimate is $q=\frac{t}{8w^2}$.',
              'figures':[], 'equations':[{'latex':r'q=\frac{t}{8}w^2 \quad (2)',
              'equation_text':'q = tw2/8 (2)', 'evidence_status':'verified',
              'evidence_quote':'The rate is defined here.', 'context':[{'index':2}]}]}
        parsed={'paragraphs':[{'index':2,'page':1,'text':'The rate is defined here.'}]}
        return card,parsed

    def test_find_cross_field_disagreement_without_overwriting(self):
        card,parsed=self.fixture();original=copy.deepcopy(card)
        result=audit_card(card,parsed)
        self.assertIn('cross_field_formula_disagreement',[r['code'] for r in result['findings']])
        self.assertEqual(card,original)
        self.assertFalse(result['scientific_verified'])

    def test_comparison_between_two_summaries(self):
        card,parsed=self.fixture();card['equations'][0]['latex']=''
        card['intro_summary']=r'$q=\frac{t}{8w^2}$'
        card['key_findings']=r'$q=\frac{t}{8}w^2$'
        self.assertIn('cross_field_formula_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_label_font_does_not_hide_formula(self):
        self.assertEqual(compare_assignment(r'q_{ABC}=a^2',r'q_{\text{ABC}}=\frac{1}{a^2}'),'different_forms')

    def test_citation_not_entailment(self):
        card,parsed=self.fixture();result=audit_card(card,parsed)
        self.assertEqual(result['citations'][0]['state'],'literal_match')
        self.assertEqual(result['citations'][0]['entailment'],'not_checked')

    def test_citation_outside_context_not_verified(self):
        card,parsed=self.fixture();card['equations'][0]['context']=[]
        self.assertEqual(audit_card(card,parsed)['citations'][0]['state'],'unverified')

    def test_incomplete_raw_relation_flagged(self):
        card,parsed=self.fixture();card['equations'][0]['equation_text']='8 w2 (2)'
        self.assertIn('source_relation_incomplete',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_script_relocation_detected(self):
        card,parsed=self.fixture()
        card['equations'][0]['latex']=r'd(t)=\begin{cases}d_0+at^{1/2}\end{cases}'
        card['intro_summary']=r'The law uses $t_{1/2}$.'
        self.assertIn('script_position_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_new_index_not_assumed_wrong(self):
        card,parsed=self.fixture();card['equations'][0]['latex']='q=w_1'
        card['intro_summary']=r'A new variable is $w_2$.'
        self.assertNotIn('script_position_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_new_power_not_assumed_wrong(self):
        card,parsed=self.fixture();card['equations'][0]['latex']='q=t^{1/2}'
        card['intro_summary']=r'An independent expression is $t^2$.'
        self.assertNotIn('script_position_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_uncertainty_propagation(self):
        card,parsed=self.fixture();card['equations'][0]['evidence_status']='needs_review'
        result=audit_card(card,parsed)
        self.assertIn('unverified_evidence',[r['code'] for r in result['findings']])
        card['meta']['science_checks']=result
        self.assertTrue(diagnostics(card)['automatic_retry_blocked'])

    def test_generic_abbreviation_mismatch(self):
        card,parsed=self.fixture()
        parsed['paragraphs'][0]['text']+=' This is collision-induced relaxation (CIR).'
        card['intro_summary']='CIR (chemical-induced relaxation) matters.'
        self.assertIn('abbreviation_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_correct_abbreviation_no_flag(self):
        card,parsed=self.fixture()
        parsed['paragraphs'][0]['text']+=' This is collision-induced relaxation (CIR).'
        card['intro_summary']='CIR (collision-induced relaxation) matters.'
        self.assertNotIn('abbreviation_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_chinese_parentheses_and_hyphen_initials(self):
        card,parsed=self.fixture()
        parsed['paragraphs'][0]['text']+=' collision-induced relaxation (CIR).'
        card['intro_summary']='CIR（Chemical-pair Inhomogeneous Relaxation）matters.'
        self.assertIn('abbreviation_disagreement',[r['code'] for r in audit_card(card,parsed)['findings']])

    def test_dimension_declarations_must_have_source(self):
        card,parsed=self.fixture()
        card['meta']['source_dimension_evidence']=[{'symbol':'q','dimensions':{'time':-1},
            'source_quote':'invented source','paragraph_index':2,'page':1}]
        self.assertEqual(audit_card(card,parsed)['dimension_checks'][0]['state'],'unknown')

    def test_subprocess_actual_integration(self):
        card,parsed=self.fixture();result=bounded_audit(card,parsed)
        self.assertEqual(result['state'],'needs_review')
        self.assertEqual(result['runtime'],VERSIONS)

    def test_timeout_blocks_instead_of_success(self):
        card,parsed=self.fixture()
        self.assertEqual(bounded_audit(card,parsed,timeout=.00001)['state'],'unavailable')

    def test_missing_dependency_blocks(self):
        card,parsed=self.fixture()
        with patch('reading.science_verifier.runtime_identity',return_value={}):
            result=audit_card(card,parsed)
        self.assertTrue(result['blocking']);self.assertEqual(result['state'],'unavailable')

    def test_missing_dependency_fails_before_model_setup(self):
        from reading import reading_bridge
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'source.pdf').write_bytes(b'synthetic')
            with patch('reading.science_verifier.runtime_identity',return_value={}),patch.object(reading_bridge,'reading_config') as model:
                with self.assertRaisesRegex(RuntimeError,'核验依赖缺失'):
                    reading_bridge.process({'out_dir':folder,'model':{}})
                model.assert_not_called()

    def test_completion_gate(self):
        card={'meta':{'metadata_generation_ok':True,'generation':{'schema_version':2,
              'stages':{s:{'state':'ok'} for s in METADATA_STAGES}}}, 'equations':[],
              'figures':[{'image_path':'fixture.png','status':'ok','classification_status':'ok',
                          'evidence_status':'verified','evidence_quote':'original'}]}
        self.assertTrue(generation_complete(card))
        card['meta']['science_checks']={'blocking':True}
        self.assertFalse(generation_complete(card))


if __name__=='__main__':
    unittest.main()
