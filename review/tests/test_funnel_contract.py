"""Regression coverage for the October 18 review funnel audit."""
import json
import unittest
from unittest.mock import patch
from review.tests.test_card_review_queue import ReviewQueue
from review import card_review_queue as q
from review.review_cycle import completed_failure
from correction import card_correction_queue as correction


class FunnelContract(unittest.TestCase):
    def setUp(self):
        self.fixture=ReviewQueue();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_minor_advice_passes_but_major_and_incomplete_do_not(self):
        f=self.fixture;job,_,card=f.card();folder,_=f.packet(job,card)
        data=f.feedback()
        data['issues']=[{'severity':'minor','finding':'Optional readability advice','evidence':'Original source evidence','source_page':1,
                         'source_quote':'The observation was supported by an independent control experiment.'}]
        _,result=q.parse_review(json.dumps(data),folder)
        self.assertEqual(result['action'],'pass');self.assertIsNone(result['failure_kind'])
        data['issues'][0]['severity']='major'
        self.assertNotEqual(q.parse_review(json.dumps(data),folder)[1]['action'],'pass')
        data['issues'][0]['severity']='minor';data['source_pages_reviewed']=[]
        self.assertNotEqual(q.parse_review(json.dumps(data),folder)[1]['action'],'pass')

    def test_cycle_uses_explicit_configuration_after_receipt_validation(self):
        with patch('review.card_review_repair.collected') as receipt,patch.object(q,'parse_review',return_value=({}, {'action':'rework','failure_kind':'scientific'})) as parse:
            with __import__('tempfile').TemporaryDirectory() as d:
                from pathlib import Path
                (Path(d)/'response-raw.txt').write_text('{}')
                completed_failure(None,{'folder':d},{'review_standard':{'external_supplements_optional':True}})
        receipt.assert_called_once();self.assertTrue(parse.call_args.kwargs['optional_external_supplements'])

    def test_correction_recheck_matches_enqueue_configuration(self):
        f=self.fixture;job,_,card=f.card();folder,packet=f.packet(job,card)
        data=f.feedback();data['verdict']='cannot_evaluate'
        data['issues']=[{'severity':'major','finding':'Card defect','evidence':'Source evidence',
                         'source_page':1,'source_quote':'The observation was supported by an independent control experiment.',
                         'path':'figures.0.summary'}]
        f.receipt(folder,packet,data)
        f.config['review_standard']={'no_user_state':True}
        feedback,assessment,evidence=correction._collected_review(f.catalog,job,f.config)
        self.assertEqual(assessment['auto_action'],'rework')
        task={'review':job,'feedback':feedback,'assessment':assessment,'evidence':evidence}
        with patch.object(correction,'check_task',return_value=task),patch.object(q,'queue_rework',side_effect=ValueError('reached original rework guard')):
            with self.assertRaisesRegex(ValueError,'reached original rework guard'):
                correction.process(f.catalog,{'kind':'source_rework','id':'synthetic','fifo_at':1},f.config)

    def test_pure_ambiguity_never_becomes_an_automatic_rework_permission(self):
        f=self.fixture;job,_,card=f.card();folder,packet=f.packet(job,card)
        data=f.feedback();data['verdict']='cannot_evaluate';f.receipt(folder,packet,data)
        f.config['review_standard']={'no_user_state':True}
        with self.assertRaisesRegex(ValueError,'未提出允许'):
            correction.enqueue_review(f.catalog,job,f.config)
