import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from review.tests.test_card_review_queue import ReviewQueue
from review import card_review_queue as review
from review.review_cycle import completed_failure, failure_count, failure_limit
from browser.shared_workflow_queue import backlog_dispatch
from core.services import atomic_json


class ReviewAuditSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.catalog_path=str(Path(self.tmp.name)/'catalog.sqlite3')

    def test_incomplete_inventory_never_reads_controls_or_claims_new_work(self):
        config={'catalog_path':self.catalog_path,'web_cards':{'enabled':True,'max_parallel_jobs':20,'min_reserved_pages':8},
                'card_review':{'enabled':True,'parallel_jobs':20},
                'card_correction':{'enabled':True,'parallel_jobs':20}}
        entries={'active':{'state':'busy','kind':'review'},'idle':{'state':'ready_blank'}}
        with patch('browser.shared_page_backlog.fixed_reservations',side_effect=ValueError('invalid control')) as minima:
            allocation=backlog_dispatch(None,config,entries,['active','idle'],{},inventory_complete=False)
        minima.assert_not_called()
        self.assertEqual(allocation['claim_order'],[])
        self.assertEqual(allocation['active']['review'],1)
        self.assertIn('active',allocation['review_targets'])

    def test_valid_inventory_still_rejects_invalid_controls(self):
        config={'catalog_path':self.catalog_path,'web_cards':{'enabled':True},'card_review':{},'card_correction':{}}
        with patch('browser.shared_page_backlog.fixed_reservations',side_effect=ValueError('invalid control')):
            with self.assertRaisesRegex(ValueError,'invalid control'):
                backlog_dispatch(None,config,{},[],{},inventory_complete=True)

    def test_collected_malformed_report_and_pass_report_are_not_scientific_failures(self):
        fixture=ReviewQueue();fixture.setUp();self.addCleanup(fixture.doCleanups)
        job,_,card=fixture.card();folder,packet=fixture.packet(job,card)
        fixture.receipt(folder,packet,fixture.feedback())
        receipt=json.loads((folder/'attempt.json').read_text());receipt['finished']=1
        atomic_json(folder/'attempt.json',receipt)
        with self.assertRaisesRegex(ValueError,'科学通过'):
            completed_failure(fixture.catalog,job)
        # A fully collected malformed response satisfies receipt provenance,
        # but must fail the scientific-report contract before any cycle count.
        raw='{"scores":'
        (folder/'response-raw.txt').write_text(raw)
        from cards.web_card_inputs import digest
        receipt['raw_sha256']=digest(folder/'response-raw.txt');atomic_json(folder/'attempt.json',receipt)
        with self.assertRaises(ValueError):completed_failure(fixture.catalog,job)

    def test_historical_technical_events_and_duplicates_are_not_counted(self):
        fixture=ReviewQueue();fixture.setUp();self.addCleanup(fixture.doCleanups)
        job,_,_=fixture.card()
        for old in ('failed','valid','valid'):
            fixture.catalog.event(job['paper_id'],'card_review_cycle',{
                'card_sha256':job['card_sha256'],'old_folder':old,'old_review_id':old})
        fixture.catalog.event(job['paper_id'],'card_review_cycle',{'card_sha256':job['card_sha256']})
        def check(catalog,previous,config=None):
            if previous['id']=='failed':raise ValueError('invalid report')
            return {'action':'needs_user'}
        excluded=[]
        with patch('review.review_cycle.completed_failure',side_effect=check):
            self.assertEqual(failure_count(fixture.catalog,job,diagnostics=excluded),1)
        self.assertEqual(len(excluded),3)

    def test_policy_cannot_silently_change_authorized_three_failures(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir()
            config={'catalog_path':str(root/'data/catalog.sqlite3')}
            for value in (True,2,4):
                atomic_json(root/'config/review-cycle-policy.json',{'enabled':True,'failures_before_recard':value})
                with self.assertRaises(ValueError):failure_limit(config)
            atomic_json(root/'config/review-cycle-policy.json',{'enabled':True,'failures_before_recard':3})
            self.assertEqual(failure_limit(config),3)

    def test_review_storage_checks_its_own_root_before_creating_payload(self):
        fixture=ReviewQueue();fixture.setUp();self.addCleanup(fixture.doCleanups)
        job,_,_=fixture.card()
        fixture.config['card_review']['media_root']=str(fixture.root/'review-volume')
        fixture.config['web_cards']['media_root']=str(fixture.root/'different-volume')
        fixture.config['archive_volume']='/Volumes/synthetic-missing'
        with patch('browser.web_media_storage.require_volume',side_effect=OSError('volume unavailable')) as gate:
            with self.assertRaisesRegex(OSError,'volume unavailable'):review.prepare(fixture.catalog,job,fixture.config)
        gate.assert_called_once_with(fixture.config['card_review']['media_root'],fixture.config['archive_volume'])
        self.assertFalse((fixture.root/'review-volume').exists())


if __name__=='__main__':unittest.main()
