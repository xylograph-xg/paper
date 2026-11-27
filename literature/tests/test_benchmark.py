"""Evaluation counts vocabulary omissions and rejects changed gold/output inputs."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from literature.benchmark import compare, dump
from literature.classifier import classify
from literature.store import fingerprint
from unittest.mock import patch
from literature.benchmark import freeze_pilot


class BenchmarkTests(unittest.TestCase):
    def test_unopened_holdout_excludes_development_and_does_not_predict(self):
        with tempfile.TemporaryDirectory() as tmp:
            d={'paper_id':'fresh','title':'TADF','abstract':'We report TADF.','metadata_fingerprint':'m',
               'source_fingerprint':'s','chunks':[{'id':'b','text':'Body','page':1,'section':'results'}],'coverage':{}}
            rows=[{'id':pid,'title':'TADF','has_pdf':True,'metadata':{'abstract':'We report TADF.'}} for pid in ['development','fresh']]
            with patch('literature.benchmark.STRATA',[('tadf','TADF')]),patch('literature.benchmark.metadata_rows',return_value=rows),patch('literature.benchmark.source_records',return_value=[{**rows[1],'materials':[{}]}]),patch('literature.benchmark.prepare_document',return_value=d),patch('literature.benchmark.classify') as classifier:
                samples=freeze_pilot('unused',Path(tmp)/'holdout',exclude_paper_ids=['development'],generate_predictions=False)
            classifier.assert_not_called()
            self.assertEqual([s['paper_id'] for s in samples],['fresh'])
            self.assertFalse((Path(tmp)/'holdout/predictions.json').exists())

    def test_open_vocabulary_recall_and_freeze_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            d={'paper_id':'test','title':'TADF','abstract':'','chunks':[],'metadata_fingerprint':'m','source_fingerprint':None}
            result=classify(d)
            gold={'scope':'synthetic validation','papers':[{'paper_id':'test','input_fingerprint':fingerprint(d),
                'level1':[{'id':'topic.tadf','evidence':[{'scope':'title','quote':'TADF'}]},
                          {'id':'gold.topic.uncovered','name':'Uncovered direction','dimension':'topic','evidence':[{'scope':'title','quote':'TADF'}]}], 'level2':[]}]}
            dump(folder/'inputs.json',[d]);dump(folder/'predictions.json',[result]);dump(folder/'gold.json',gold)
            dump(folder/'gold-frozen.json',{'gold_sha256':hashlib.sha256((folder/'gold.json').read_bytes()).hexdigest()})
            dump(folder/'frozen-output-hashes.json',{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('inputs.json','predictions.json')})
            r=compare(folder)['levels']['level1']
            self.assertEqual((r['tp'],r['fp'],r['fn']),(1,0,1))
            self.assertEqual(r['recall'],.5);self.assertEqual(r['out_of_vocabulary_gold'],1)
            (folder/'gold.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'标准答案'):compare(folder)

    def test_ineligible_level_is_reported_but_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            d={'paper_id':'supplementary','title':'TADF','abstract':'','chunks':[],
               'metadata_fingerprint':'m','source_fingerprint':None}
            r=classify(d)
            gold={'scope':'source eligibility test','papers':[{'paper_id':d['paper_id'],
                'input_fingerprint':fingerprint(d),'level1':[],'level2':[],
                'eligible_levels':{'level1':True,'level2':False},'exclusion_reason':'SI-only'}]}
            dump(folder/'inputs.json',[d]);dump(folder/'predictions.json',[r]);dump(folder/'gold.json',gold)
            dump(folder/'gold-frozen.json',{'gold_sha256':hashlib.sha256((folder/'gold.json').read_bytes()).hexdigest()})
            dump(folder/'frozen-output-hashes.json',{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ('inputs.json','predictions.json')})
            result=compare(folder)
            self.assertEqual(result['levels']['level1']['papers'],1)
            self.assertEqual(result['levels']['level2']['papers'],0)
            self.assertFalse(result['papers'][0]['level2']['eligible'])
