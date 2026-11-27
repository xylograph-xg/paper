"""Real catalog proof that a review upload wait skips work without moving it."""
import json
import tempfile
import time
import unittest
from core.api import paths__WorkspacePath as Path

from core.catalog import Catalog, now
from cards.web_card_inputs import digest
from core.services import atomic_json
from review import card_review_queue as reviews
from browser import shared_page_backlog as backlog
from browser import shared_workflow_queue as queue
from browser import upload_retry_policy as policy
from browser import web_page_queue as materials


class SharedBacklogUploadCooldownTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path),
            'studio_library_root':str(self.root/'library'),
            'web_cards':{'enabled':True,'max_parallel_jobs':20,'min_reserved_pages':8,
                'shared_window':{'enabled':True,'backlog':{'enabled':True,
                    'low_watermark':70,'target_tasks':100,'queue_depth':4}}},
            'card_review':{'enabled':True,'parallel_jobs':20,'upload_retry':{'enabled':True}},
            'card_correction':{'enabled':True,'parallel_jobs':20}}
        reviews.install(self.catalog); materials.install(self.catalog); backlog.install(self.catalog)
        from cards import web_card_queue as cards
        cards.install(self.catalog)
        self.entries = {f't{i:02}':{'state':'ready','kind':'review','slot':i} for i in range(20)}
        self.number = 0

    def review(self, name=None, *, state='ready', target=None):
        self.number += 1
        name = name or f'review-{self.number}'
        pid = self.catalog.upsert({'title':name,'doi':'10.9999/'+name})
        source = self.root/(name+'.pdf'); source.write_bytes(('synthetic source '+name).encode())
        self.catalog.update(pid, acquisition='available', asset_path=str(source), asset_hash=digest(source))
        card = self.root/'library'/pid/'card.json'
        card.parent.mkdir(parents=True); card.write_text('{}')
        self.catalog.update(pid, card_path=str(card))
        jid = 'review-'+pid
        folder = self.root/'reviews'/jid; folder.mkdir(parents=True)
        (folder/'bundle.zip').write_bytes(b'synthetic zip')
        (folder/'source.pdf').write_bytes(b'synthetic frozen source')
        packet = {'input_hashes':{'source.pdf':digest(folder/'source.pdf')},
            'upload_bundle':{'zip_path':str(folder/'bundle.zip'),'zip_sha256':digest(folder/'bundle.zip')}}
        atomic_json(folder/'packet.json',packet)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (jid,pid,digest(card),digest(source),name,state,str(folder),now()))
            if target is not None:
                db.execute("INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned) VALUES('review',?,?,?,?)",
                           (jid,pid,target,float(self.number)))
        return jid, folder

    def cool(self, jid, folder):
        """Record one proven never-clicked upload receipt for this exact material."""
        packet = json.loads((Path(folder)/'packet.json').read_text())
        finished = time.time()
        attempt = {'state':'not_sent','send_click_started':False,'created':finished-10.0,
            'finished':finished,'upload_failure_stage':'attach','error':'附件上传失败',
            'inputs':packet['input_hashes'],'upload_bundle':packet['upload_bundle']}
        result = policy.record_failure(self.catalog,config=self.config,job_id=jid,attempt=attempt)
        self.assertFalse(result['deduplicated'])
        return result

    def expire(self, jid):
        """Move only the stored instant, never the receipt, into the past."""
        with self.catalog.connect() as db:
            db.execute("UPDATE upload_retry_policy SET next_eligible=? WHERE lane='review' AND job_id=?",
                       (time.time()-1, jid))

    def arrivals(self):
        with self.catalog.connect() as db:
            return [tuple(row) for row in db.execute('SELECT * FROM shared_workflow_arrivals ORDER BY sequence')]

    def bindings(self):
        with self.catalog.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM shared_page_backlog ORDER BY lane,job_id')]

    def test_cooling_head_yields_the_page_to_due_work_and_restores_the_original_rank(self):
        first,first_folder = self.review('first',target='t00')
        second,_ = self.review('second',target='t00')
        before = self.arrivals()
        self.assertEqual(backlog.head_ready(self.catalog,self.config,'t00')['job_id'],first)
        self.cool(first,first_folder)
        self.assertEqual(backlog.head_ready(self.catalog,self.config,'t00')['job_id'],second)
        self.assertEqual(self.arrivals(),before)
        self.assertEqual([(row['target_id'],row['state']) for row in self.bindings()],
                         [('t00','queued'),('t00','queued')])
        # Expiry returns the older arrival to the head; nothing was re-sorted.
        self.expire(first)
        self.assertEqual(backlog.head_ready(self.catalog,self.config,'t00')['job_id'],first)

    def test_preparing_or_missing_material_is_never_treated_as_a_cooldown(self):
        first,first_folder = self.review('preparing',state='preparing',target='t01')
        self.review('ready',target='t01')
        self.assertIsNone(backlog.head_ready(self.catalog,self.config,'t01'))
        self.cool(first,first_folder)
        self.assertIsNone(backlog.head_ready(self.catalog,self.config,'t01'))

    def test_claim_head_binding_refuses_a_cooling_material_and_accepts_the_due_one(self):
        first,first_folder = self.review('first',target='t05')
        second,_ = self.review('second',target='t05')
        self.cool(first,first_folder)
        with self.catalog.connect() as db:
            self.assertFalse(backlog.check_head_binding(db,self.config,'review',first,'t05'))
            self.assertTrue(backlog.check_head_binding(db,self.config,'review',second,'t05'))

    def test_cooldown_never_releases_or_moves_an_existing_claim(self):
        jid,folder = self.review('claimed',target='t02')
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,'review',jid,'t02')
        before = self.bindings()
        self.cool(jid,folder)
        self.assertIsNone(backlog.head_ready(self.catalog,self.config,'t02'))
        self.assertEqual(self.bindings(),before)
        with self.catalog.connect() as db:
            self.assertTrue(backlog.check_claim_binding(db,'review',jid,'t02'))

    def test_reconcile_keeps_the_real_slot_but_excludes_a_wait_from_dispatchable_stock(self):
        cooling,cooling_folder = self.review('cool',target='t03')
        healthy,_ = self.review('healthy',target='t04')
        self.cool(cooling,cooling_folder)
        result = backlog.reconcile(self.config,self.catalog,self.entries,list(self.entries),{},
                                   cards_min_pages=8)
        physical = {row['job_id']:row for row in self.bindings()}
        self.assertEqual(physical[cooling]['target_id'],'t03')
        self.assertEqual(physical[healthy]['target_id'],'t04')
        self.assertEqual(result['upload_cooldown_tasks'],1)
        self.assertLess(result['queued_tasks'],result['physical_queued_tasks'])
        labelled = {row['job_id']:row for row in backlog.rows(self.catalog,self.config)}
        self.assertFalse(labelled[cooling]['upload_due'])
        self.assertTrue(labelled[healthy]['upload_due'])
        self.expire(cooling)
        self.assertTrue({row['job_id']:row for row in backlog.rows(self.catalog,self.config)}[cooling]['upload_due'])

    def test_non_mixed_heads_skips_the_wait_and_restores_the_original_fifo(self):
        first,first_folder = self.review('older')
        second,_ = self.review('newer')
        self.assertEqual([row['job_id'] for row in queue.heads(self.catalog,self.config)['review']],
                         [first,second])
        self.cool(first,first_folder)
        self.assertEqual([row['job_id'] for row in queue.heads(self.catalog,self.config)['review']],[second])
        self.expire(first)
        self.assertEqual([row['job_id'] for row in queue.heads(self.catalog,self.config)['review']],
                         [first,second])

    def test_disabled_policy_leaves_every_head_entry_unchanged(self):
        first,first_folder = self.review('older')
        second,_ = self.review('newer')
        self.cool(first,first_folder)
        config = dict(self.config); config['card_review'] = {'enabled':True,'parallel_jobs':20}
        self.assertEqual([row['job_id'] for row in queue.heads(self.catalog,config)['review']],
                         [first,second])

    def test_unreadable_packet_blocks_only_that_material_and_repaired_material_returns(self):
        cooling,cooling_folder = self.review('cool',target='t06')
        healthy,_ = self.review('healthy',target='t06')
        self.cool(cooling,cooling_folder)
        (Path(cooling_folder)/'packet.json').unlink()
        self.assertEqual(backlog.head_ready(self.catalog,self.config,'t06')['job_id'],healthy)
        # The wait is not a permanent discard: a genuinely re-prepared packet
        # carries a new material key and becomes dispatchable again on its own.
        (Path(cooling_folder)/'source.pdf').write_bytes(b'repaired frozen source')
        (Path(cooling_folder)/'bundle.zip').write_bytes(b'repaired zip')
        atomic_json(Path(cooling_folder)/'packet.json',{
            'input_hashes':{'source.pdf':digest(Path(cooling_folder)/'source.pdf')},
            'upload_bundle':{'zip_path':str(Path(cooling_folder)/'bundle.zip'),
                'zip_sha256':digest(Path(cooling_folder)/'bundle.zip')}})
        self.assertEqual(backlog.head_ready(self.catalog,self.config,'t06')['job_id'],cooling)


if __name__ == '__main__':
    unittest.main()
