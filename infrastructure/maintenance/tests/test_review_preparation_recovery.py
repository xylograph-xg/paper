import json
import shutil
import unittest
from unittest.mock import patch
from core.api import paths__WorkspacePath as Path,services__atomic_json as atomic_json
from cards.api import web_card_inputs__digest as digest
from review.tests import test_card_review_queue as fixtures
from review import card_review_queue as queue
from correction import card_correction_queue
from browser.shared_page_backlog import install
from maintenance.review_preparation_recovery import recover


class PreparationRecovery(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ReviewQueue();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.catalog=self.fixture.catalog;self.config=self.fixture.config
        self.job,self.card_path,self.card=self.fixture.card()
        self.folder,self.packet=self.fixture.packet(self.job,self.card)
        self.packet.update(job_id=self.job['id'],card_sha256=self.job['card_sha256'],source_original_sha256=self.job['source_sha256'])
        atomic_json(self.folder/'packet.json',self.packet)
        queue.update(self.catalog,self.job['id'],'needs_user','ZIP exceeds local 64MiB upload limit',{})
        self.job=queue.rows(self.catalog)[0]
        card_correction_queue.install(self.catalog);install(self.catalog)

    def test_frozen_complete_packet_reused_once_without_changing_any_material(self):
        before={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        result=recover(self.catalog,self.job,self.config)
        self.assertTrue(result['reused_frozen_packet'])
        self.assertEqual(queue.rows(self.catalog)[0]['state'],'ready')
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()},before)
        with self.assertRaises(ValueError):recover(self.catalog,queue.rows(self.catalog)[0],self.config)

    def test_unfrozen_partial_uses_new_id_and_folder_preserving_original_evidence(self):
        (self.folder/'packet.json').unlink()
        before={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        def prepare(catalog,job,config,**options):
            self.assertFalse(options['locate_quote_pages'])
            folder=Path(job['folder'])
            for name in before:shutil.copy2(self.folder/name,folder/name)
            atomic_json(folder/'packet.json',{**self.packet,'job_id':job['id']})
            return True
        with patch.object(queue,'prepare',side_effect=prepare):result=recover(self.catalog,self.job,self.config)
        self.assertNotEqual(result['old_review_id'],result['new_review_id'])
        self.assertEqual(queue.rows(self.catalog)[0]['id'],result['new_review_id'])
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()},before)

    def test_any_unknown_receipt_pause_or_claim_blocks_recovery(self):
        atomic_json(self.folder/'attempt.json',{'state':'needs_inspection'})
        with self.assertRaises(ValueError):recover(self.catalog,self.job,self.config)
        (self.folder/'attempt.json').unlink()
        atomic_json(self.catalog.path.parent/'card-review-control.json',{'paused_by_user':True})
        with self.assertRaises(ValueError):recover(self.catalog,self.job,self.config)
        (self.catalog.path.parent/'card-review-control.json').unlink()
        with self.catalog.connect() as db:
            db.execute("INSERT INTO shared_page_backlog VALUES('review',?,?,'target',1,'claimed')",(self.job['id'],self.job['paper_id']))
        with self.assertRaises(ValueError):recover(self.catalog,self.job,self.config)
        self.assertEqual(queue.rows(self.catalog)[0],self.job)


if __name__=='__main__':unittest.main()
