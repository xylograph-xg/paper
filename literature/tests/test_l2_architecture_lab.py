"""Independent architecture contracts, no corpus, models or production sidecar writes."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from literature.experiments.l2_lab.api import classify_level2,validate_output
from literature.experiments.l2_lab.text import BM25,pagerank
from literature.experiments.l2_lab.evaluation import score


def doc(body='',section='results',title='TADF emitters',abstract=''):
    return {'paper_id':'synthetic','title':title,'abstract':abstract,
            'chunks':[{'id':'body','text':body,'page':2,'scope':'fulltext','section':section}] if body else []}


class L2ArchitectureTests(unittest.TestCase):
    strategies=('retrieval','assertion_graph')

    def test_metadata_is_not_fine_evidence_and_missing_body_remains_empty(self):
        for strategy in self.strategies:
            value=classify_level2(doc(title='We investigate reverse intersystem crossing',abstract='We performed DFT calculations.'),strategy)
            self.assertFalse(value['level2']);self.assertFalse(value['supporting_labels']);self.assertEqual(value['level2_state'],'missing_input')
            self.assertFalse(value['scientific_verified']);self.assertFalse(value['models_used']);self.assertFalse(value['production_publish'])

    def test_actual_study_mechanism_and_routine_method_roles(self):
        for strategy in self.strategies:
            value=classify_level2(doc('We investigate reverse intersystem crossing. We performed cyclic voltammetry measurements.',title='Reverse intersystem crossing in TADF emitters'),strategy)
            self.assertIn('mechanism.risc',{x['id'] for x in value['level2']})
            self.assertNotIn('mechanism.isc',{x['id'] for x in value['level2']+value['supporting_labels']})
            self.assertNotIn('method.electrochemistry',{x['id'] for x in value['level2']})
            self.assertIn('method.electrochemistry',{x['id'] for x in value['supporting_labels']})

    def test_history_negative_hypothetical_and_reference_sources(self):
        examples=[doc('Previous studies investigated reverse intersystem crossing.'),doc('We did not perform cyclic voltammetry measurements.'),doc('Future work could investigate reverse intersystem crossing.'),doc('We investigate reverse intersystem crossing.',section='references')]
        for strategy in self.strategies:
            for source in examples:
                value=classify_level2(source,strategy);self.assertFalse(value['level2']);self.assertFalse(value['supporting_labels']);self.assertTrue(value['mentions'])

    def test_exact_unicode_original_spans_and_tampering_rejected(self):
        for strategy in self.strategies:
            source=doc('  We investigate spin–orbit coupling in the excited states.  ')
            value=classify_level2(source,strategy);self.assertTrue(value['level2']);validate_output(source,value)
            changed=copy.deepcopy(value);changed['level2'][0]['evidence'][0]['start']+=1
            with self.assertRaises(ValueError):validate_output(source,changed)
            changed=copy.deepcopy(value);changed['level2'][0]['evidence'][0]['page']=3
            with self.assertRaises(ValueError):validate_output(source,changed)

    def test_open_phrases_are_discoveries_never_automatic_tags(self):
        source=doc('We investigate proton tunneling pathways. Proton tunneling pathways reveal a kinetic isotope effect.')
        for strategy in self.strategies:
            value=classify_level2(source,strategy);self.assertTrue(value['unmapped_phrases']);self.assertFalse(value['level2'])
            self.assertTrue(all(p['status']=='unmapped_discovery_not_a_tag' for p in value['unmapped_phrases']))
            validate_output(source,value)

    def test_candidates_do_not_load_old_classifier_or_read_runtime_data(self):
        with patch('literature.classifier.classify',side_effect=AssertionError('old classifier forbidden')),patch('pathlib.Path.read_text',side_effect=AssertionError('hidden input forbidden')),patch('pathlib.Path.write_text',side_effect=AssertionError('production write forbidden')):
            for strategy in self.strategies:classify_level2(doc('We investigate reverse intersystem crossing.'),strategy)

    def test_irrelevant_inputs_do_not_gain_tags_and_configuration_strict(self):
        for strategy in self.strategies:
            self.assertEqual(classify_level2(doc('The weather forecast reports sunny conditions.'),strategy)['level2'],[])
        for strategy,settings in [('unknown',None),('retrieval',{'core_threshold':float('nan'),'method_threshold':4}),('retrieval',{'paper_id':'special'})]:
            with self.assertRaises(ValueError):classify_level2(doc(),strategy,settings)

    def test_claim_frames_distinguish_tool_from_research_target(self):
        from literature.experiments.l2_lab.claim_api import classify_claims
        source=doc('We used cyclic voltammetry to investigate a charge-transfer state.')
        output=classify_claims(source)
        self.assertIn('mechanism.ct',{x['id'] for x in output['level2']})
        self.assertNotIn('method.electrochemistry',{x['id'] for x in output['level2']})
        self.assertIn('method.electrochemistry',{x['id'] for x in output['supporting_labels']})
        self.assertTrue(output['claim_fields']);validate_output(source,output)
        self.assertFalse(classify_claims(doc(title='DFT calculation'))['level2'])
        self.assertFalse(classify_claims(doc('Previously we investigated reverse intersystem crossing.'))['level2'])

    def test_ranking_components_and_evaluation_do_not_hide_oov(self):
        ranks=pagerank({'a','b'},{'a':{'b':1},'b':{'a':1}})
        self.assertAlmostEqual(sum(ranks.values()),1)
        bm=BM25(['energy transfer transfer','nothing relevant']);self.assertGreater(bm.score('energy transfer',0),bm.score('energy transfer',1))
        source=doc('We investigate reverse intersystem crossing.',title='Reverse intersystem crossing')
        result=classify_level2(source)
        reference={'papers':[{'paper_id':'synthetic','input_fingerprint':result['input_fingerprint'],'level2':[
            {'id':'mechanism.risc','evidence':[{'chunk_id':'body','page':2,'quote':source['chunks'][0]['text']}]},
            {'id':'gold.unknown','evidence':[{'chunk_id':'body','page':2,'quote':source['chunks'][0]['text']}]}]}]}
        metrics=score([source],[result],reference)['metrics'];self.assertEqual((metrics['tp'],metrics['fn'],metrics['oov_gold']),(1,1,1));self.assertEqual(metrics['recall'],.5)


if __name__=='__main__':unittest.main()
