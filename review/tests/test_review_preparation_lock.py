import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path

from core.catalog import Catalog
from review import card_review_queue; from correction import card_correction_queue
from browser.shared_page_backlog import install as install_backlog
from core.automatic_issue_handler import recover_review_preparation_lock
from cards.web_card_inputs import digest


class ReviewPreparationLockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.pid = self.catalog.upsert({'title':'Synthetic lock recovery'})
        source = self.root/'source.pdf';source.write_bytes(b'original source')
        library = self.root/'cards';card_folder = library/self.pid;card_folder.mkdir(parents=True)
        (card_folder/'source.pdf').write_bytes(source.read_bytes())
        self.card = card_folder/'card.json'
        self.card.write_text(json.dumps({'title':'Synthetic lock recovery', 'meta':{
            'source_original_sha256':digest(source), 'source_sha256':digest(source)}}))
        self.catalog.update(self.pid,asset_path=str(source),asset_hash=digest(source),card_path=str(self.card))
        card_review_queue.install(self.catalog);card_correction_queue.install(self.catalog);install_backlog(self.catalog)
        self.folder = self.root/'card_reviews'/self.pid/'r1';self.folder.mkdir(parents=True)
        (self.folder/'source-context.json').write_text('preserve partial local evidence')
        with self.catalog.connect() as db:
            db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,error,updated) "
                       "VALUES('r1',?,?,?,'synthetic','needs_user',?,'database is locked','original')",
                       (self.pid,digest(self.card),digest(source),str(self.folder)))
            db.execute("UPDATE shared_workflow_arrivals SET queued_at=123,basis='original' WHERE lane='review' AND job_id='r1'")
        self.config = {'catalog_path':str(self.catalog.path),'studio_library_root':str(library),
            'web_cards':{'enabled':True},'card_review':{'enabled':True},'automatic_issue_handling':{'enabled':True}}

    def job(self):
        with self.catalog.connect() as db:return dict(db.execute("SELECT * FROM card_review_jobs WHERE id='r1'").fetchone())

    def test_recovery_preserves_fifo_card_and_partial_materials(self):
        before=self.card.read_bytes();partial=(self.folder/'source-context.json').read_bytes()
        original=self.job()
        result=recover_review_preparation_lock(self.catalog,original,self.config)
        self.assertEqual(result['state'],'queued');self.assertEqual(self.job()['state'],'queued')
        with self.catalog.connect() as db:
            self.assertEqual(db.execute("SELECT queued_at FROM shared_workflow_arrivals WHERE job_id='r1'").fetchone()[0],123)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='automatic_review_preparation_recovery'").fetchone()[0],1)
        self.assertEqual(self.card.read_bytes(),before);self.assertEqual((self.folder/'source-context.json').read_bytes(),partial)
        self.assertIsNone(recover_review_preparation_lock(self.catalog,self.job(),self.config))
        with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,original,self.config)

    def test_any_nested_receipt_or_complete_packet_or_report_blocks(self):
        for name in ['attempt.json','packet.json','response-raw.txt','feedback.json','assessment.json']:
            with self.subTest(name=name):
                p=self.folder/'history'/'previous'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
                with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,self.job(),self.config)
                self.assertEqual(self.job()['updated'],'original');p.unlink()

    def test_user_pause_and_disabled_automation_block(self):
        control=self.root/'card-review-control.json';control.write_text(json.dumps({'paused_by_user':True}))
        self.assertIsNone(recover_review_preparation_lock(self.catalog,self.job(),self.config));control.unlink()
        self.config['automatic_issue_handling']['enabled']=False
        self.assertIsNone(recover_review_preparation_lock(self.catalog,self.job(),self.config))

    def test_changed_card_and_human_decision_block(self):
        before=self.card.read_bytes();self.card.write_text('{}')
        with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,self.job(),self.config)
        self.card.write_bytes(before);self.catalog.event(self.pid,'human_decision',{'keep':True})
        with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,self.job(),self.config)

    def test_page_claim_blocks_without_releasing_it(self):
        with self.catalog.connect() as db:
            db.execute("INSERT INTO shared_page_backlog VALUES('review','r1',?,'target',1,'claimed')",(self.pid,))
        with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,self.job(),self.config)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM shared_page_backlog').fetchone()[0],'claimed')

    def test_existing_correction_blocks(self):
        with self.catalog.connect() as db:
            db.execute("INSERT INTO card_correction_jobs(id,review_id,paper_id,card_sha256,source_sha256,kind,title,state,folder,payload,task_sha256,created,fifo_at,queued_at,updated) "
                       "VALUES('c1','r1',?, 'card','source','quote_location','synthetic','queued',?,'{}','task','now',1,1,'now')",(self.pid,str(self.folder)))
        with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,self.job(),self.config)

    def test_local_recovery_is_bounded_to_two(self):
        for _ in range(2):
            recover_review_preparation_lock(self.catalog,self.job(),self.config)
            with self.catalog.connect() as db:db.execute("UPDATE card_review_jobs SET state='needs_user',error='database is locked' WHERE id='r1'")
        with self.assertRaises(ValueError):recover_review_preparation_lock(self.catalog,self.job(),self.config)

    def test_other_errors_and_existing_result_are_not_retried(self):
        with self.catalog.connect() as db:db.execute("UPDATE card_review_jobs SET error='timeout' WHERE id='r1'")
        self.assertIsNone(recover_review_preparation_lock(self.catalog,self.job(),self.config))
        with self.catalog.connect() as db:db.execute("UPDATE card_review_jobs SET error='database is locked',result=? WHERE id='r1'",(json.dumps({'pass':False}),))
        self.assertIsNone(recover_review_preparation_lock(self.catalog,self.job(),self.config))


if __name__ == '__main__':unittest.main()
