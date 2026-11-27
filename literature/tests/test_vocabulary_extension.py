"""Generic scope distinctions and evaluation-only semantic correspondence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from literature.classifier import classify
from literature.benchmark import compare, dump
from literature.store import fingerprint


def doc(text, abstract='We study emitter orientation and charge trapping using solution-processed devices.'):
    return {'paper_id':'scope','title':'Material study','abstract':abstract,'metadata_fingerprint':'m','source_fingerprint':'s',
        'chunks':[{'id':'b','page':1,'scope':'fulltext','section':'methods','text':text}]}


class VocabularyExtensionTests(unittest.TestCase):
    def workflow_document(self, methods='HPLC analysis and mass spectrometry were performed as described previously.',
                          products='A mixture of degradation products was observed in GPC analysis.'):
        d=doc(methods,abstract='We identify degradation products in aged emitters.')
        if products:d['chunks'].append({'id':'products','scope':'fulltext','page':2,'section':'results','text':products})
        return d

    def test_joint_workflow_keeps_both_method_and_product_evidence(self):
        r=classify(self.workflow_document())
        labels=[x for x in r['level2'] if x['id']=='method.degradation_product_analysis']
        self.assertEqual(len(labels),1)
        self.assertEqual({e['chunk_id'] for e in labels[0]['evidence']},{'b','products'})
        self.assertIn('current_use_citing_prior_procedure',{e.get('procedure_reference') for e in labels[0]['evidence']})

    def test_single_instrument_or_missing_product_link_is_insufficient(self):
        docs=[self.workflow_document(methods='Mass spectrometry was performed on the sample.'),
              self.workflow_document(methods='HPLC analysis was performed on degradation products.'),
              self.workflow_document(products='We identified degradation products.'),
              self.workflow_document(products='HPLC purification yielded the synthetic compound.')]
        for d in docs:
            with self.subTest(d=d):
                r=classify(d)
                self.assertNotIn('method.degradation_product_analysis',{x['id'] for x in r['level2']+r['supporting_labels']})

    def test_historical_and_hypothetical_workflows_are_not_current_evidence(self):
        for methods in ['Previously we performed HPLC analysis and mass spectrometry.',
                        'HPLC analysis and mass spectrometry could be performed.',
                        'HPLC analysis was performed and mass spectrometry might be used.']:
            r=classify(self.workflow_document(methods=methods))
            self.assertNotIn('method.degradation_product_analysis',{x['id'] for x in r['level2']+r['supporting_labels']})

    def test_metadata_cannot_supply_missing_joint_workflow(self):
        d=self.workflow_document(methods='We measured absorption spectra.',products='')
        d['title']='HPLC and mass spectrometry of degradation products'
        self.assertNotIn('method.degradation_product_analysis',{x['id'] for x in classify(d)['level2']})

    def test_product_context_must_be_current_body_evidence(self):
        for products in ['Previous work found degradation products in GPC analysis.',
                         'Degradation products could be observed in GPC analysis.']:
            r=classify(self.workflow_document(products=products))
            self.assertNotIn('method.degradation_product_analysis',{x['id'] for x in r['level2']+r['supporting_labels']})

    def test_dft_noun_inflections_support_method_centrality(self):
        terms=['calculation','calculations','method','methods','study','studies',
               'result','results','optimization','optimizations','optimisation','optimisations']
        for term in terms:
            with self.subTest(term=term):
                d=doc('We performed density functional theory calculations on these molecules.',abstract='We compare computed energies.')
                d['title']='DFT '+term+' of molecular systems'
                r=classify(d)
                labels=[x for x in r['level2'] if x['id']=='method.dft']
                self.assertEqual(len(labels),1)
                self.assertEqual(labels[0]['evidence'][0]['scope'],'fulltext')
                self.assertIn('density functional theory',labels[0]['evidence'][0]['quote'])

    def test_dft_inflections_do_not_accept_unbounded_or_incomplete_words(self):
        for phrase in ['DFT stud','XDFT calculations','DFT methodological','DFT studies2']:
            with self.subTest(phrase=phrase):
                r=classify(doc('We used '+phrase+' to measure the system.',abstract='We examine molecules.'))
                self.assertNotIn('method.dft',{x['id'] for x in r['level2']+r['supporting_labels']})

    def test_dft_inflections_preserve_body_use_and_routine_method_boundaries(self):
        for text in ['We measured absorption spectra.',
                     'Previously we performed DFT calculations on related molecules.']:
            d=doc(text,abstract='We compare DFT studies.');d['title']='DFT studies of materials'
            self.assertNotIn('method.dft',{x['id'] for x in classify(d)['level2']+classify(d)['supporting_labels']})
        r=classify(doc('We used DFT calculations to estimate energies.',abstract='We report efficient emitters.'))
        self.assertNotIn('method.dft',{x['id'] for x in r['level2']})
        self.assertIn('method.dft',{x['id'] for x in r['supporting_labels']})

    def test_ordinary_vibronic_coupling_does_not_imply_spin_vibronic(self):
        for text in ['We investigate vibronic coupling in Raman spectra.',
                     'We investigate spin-orbit coupling and vibronic coupling.',
                     'We suppress vibronic coupling in a rigid framework.']:
            with self.subTest(text=text):
                r=classify(doc(text,abstract='We investigate vibronic coupling.'))
                ids={x['id'] for x in r['level2']+r['supporting_labels']+r['inherited_labels']}
                self.assertNotIn('mechanism.spin_vibronic',ids)

    def test_explicit_spin_vibronic_aliases_preserve_original_evidence(self):
        for term in ['spin-vibronic coupling','spin vibronic coupling','spinvibronic coupling','spin–vibronic coupling']:
            with self.subTest(term=term):
                text='We investigate '+term+' in these emitters.'
                r=classify(doc(text,abstract='We investigate '+term+'.'))
                labels=[x for x in r['level2'] if x['id']=='mechanism.spin_vibronic']
                self.assertEqual(len(labels),1)
                self.assertIn(term,labels[0]['evidence'][0]['quote'])

    def test_explicit_background_and_metadata_only_spin_vibronic_are_insufficient(self):
        r=classify(doc('Previously we investigated spin-vibronic coupling.',
                       abstract='We investigate spin-vibronic coupling.'))
        self.assertNotIn('mechanism.spin_vibronic',{x['id'] for x in r['level2']+r['supporting_labels']})
        self.assertIn('mechanism.spin_vibronic',{x['id'] for x in r['mentions']})
        r=classify(doc('We measure ordinary vibronic coupling.',abstract='We investigate spin-vibronic coupling.'))
        self.assertNotIn('mechanism.spin_vibronic',{x['id'] for x in r['level2']+r['supporting_labels']})

    def test_actual_process_and_traps_and_orientation(self):
        d=doc('We spin-coated the active layer to fabricate devices. We investigate electron trapping and emitter orientation distributions.')
        ids={x['id'] for x in classify(d)['level2']}
        self.assertTrue({'method.solution_processing','mechanism.charge_trapping','question.emitter_orientation'}<=ids)

    def test_solubility_optical_trapping_and_crystal_orientation_are_not_these_tags(self):
        d=doc('We measured solution absorption spectra of a soluble molecule. We investigate optical trapping and crystal orientation.',abstract='We study molecular properties.')
        ids={x['id'] for x in classify(d)['level2']+classify(d)['supporting_labels']}
        self.assertFalse(ids&{'method.solution_processing','mechanism.charge_trapping','question.emitter_orientation'})

    def test_metadata_cannot_supply_missing_body_process(self):
        d=doc('We measured absorption spectra.')
        self.assertNotIn('method.solution_processing',{x['id'] for x in classify(d)['level2']})

    def test_frozen_one_to_one_semantic_mapping_and_original_gold_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=doc('We investigate electron trapping in these films.')
            result=classify(d)
            gold={'scope':'synthetic equivalence audit','papers':[{'paper_id':d['paper_id'],'input_fingerprint':fingerprint(d),'level1':[],
                'level2':[{'id':'gold.mechanism.trapping','name':'Trapping','dimension':'mechanism','evidence':[{'chunk_id':'b','page':1,'quote':'electron trapping'}]}]}]}
            mapping={'mappings':[{'reference_id':'gold.mechanism.trapping','label_id':'mechanism.charge_trapping','level':2,'dimension':'mechanism','definition':'Electron or hole trapping'}]}
            for name,value in [('inputs.json',[d]),('predictions.json',[result]),('gold.json',gold),('semantic-map.json',mapping)]:dump(root/name,value)
            sha=hashlib.sha256((root/'gold.json').read_bytes()).hexdigest();dump(root/'gold-frozen.json',{'gold_sha256':sha})
            def freeze():dump(root/'frozen-output-hashes.json',{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ['inputs.json','predictions.json','semantic-map.json']})
            freeze();metrics=compare(root)['levels']['level2']
            self.assertEqual((metrics['tp'],metrics['fn']),(1,0));self.assertEqual(hashlib.sha256((root/'gold.json').read_bytes()).hexdigest(),sha)
            mapping['mappings'].append({**mapping['mappings'][0],'reference_id':'gold.mechanism.second'})
            dump(root/'semantic-map.json',mapping);freeze()
            with self.assertRaisesRegex(ValueError,'一对一'):compare(root)
