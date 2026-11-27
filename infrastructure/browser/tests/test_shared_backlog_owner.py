"""Owner integration uses real temporary queues, without browser or network."""
import copy
import json
from core.api import paths__WorkspacePath as Path
import tempfile
import time
import unittest
import sqlite3
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from core.catalog import Catalog, now
from core.services import atomic_json
from cards.web_card_inputs import digest
from cards import web_card_queue as cards
from review import card_review_queue as reviews
from browser import shared_page_backlog as backlog
from browser import shared_workflow_queue as shared
from browser.web_card_pool import maintain_shared_backlog
from browser.web_page_queue import install as material_install


class BacklogOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.catalog=Catalog(self.root/'catalog.db')
        self.config={'catalog_path':str(self.catalog.path),'studio_library_root':str(self.root/'library'),
            'web_cards':{'enabled':True,'max_parallel_jobs':20,'min_reserved_pages':8,
                'refill_min_pending':20,'shared_window':{'enabled':True,'backlog':{'enabled':True,
                    'low_watermark':70,'target_tasks':100,'queue_depth':4}}},
            'card_review':{'enabled':True,'parallel_jobs':20},
            'card_correction':{'enabled':False,'parallel_jobs':20}}
        cards.install(self.catalog);reviews.install(self.catalog);material_install(self.catalog);backlog.install(self.catalog)
        self.entries={f'page-{i:02}':{'state':'ready_blank','slot':i} for i in range(20)}

    def paper(self,name):
        pid=self.catalog.upsert({'title':name,'doi':'10.9999/'+name})
        source=self.root/(pid+'.pdf');source.write_bytes(('Synthetic original '+name).encode())
        self.catalog.update(pid,asset_path=str(source),asset_hash=digest(source),acquisition='available')
        return pid

    def card(self,name,state='ready',target='page-00'):
        pid=self.paper(name)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',
                (pid,self.catalog.get(pid)['asset_hash'],name,'{}',now()))
            db.execute('INSERT INTO web_page_queue(paper_id,target_id,state,assigned) VALUES(?,?,?,?)',(pid,target,state,time.time()))
        return pid

    def review(self,name,state='ready'):
        pid=self.paper(name);card=self.root/'library'/pid/'card.json';card.parent.mkdir(parents=True)
        card.write_text('{}');self.catalog.update(pid,card_path=str(card))
        rid='review-'+pid;folder=self.root/'reviews'/rid;folder.mkdir(parents=True)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) VALUES(?,?,?,?,?,?,?,?)',
                (rid,pid,digest(card),self.catalog.get(pid)['asset_hash'],name,state,str(folder),now()))
        return rid,pid

    def lease(self,lane,jid,pid,target):
        with self.catalog.connect() as db:
            db.execute('INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES(?,?,?,?,?,?)',
                (lane,jid,pid,target,time.time(),'queued'))
            if lane!='review':db.execute('UPDATE web_page_queue SET target_id=? WHERE paper_id=?',(target,pid))

    def test_card_claim_requires_its_exact_target_and_first_ready_head(self):
        waiting=self.card('earlier','waiting');ready=self.card('later')
        self.lease('cards',waiting,waiting,'page-00');self.lease('cards',ready,ready,'page-00')
        self.assertIsNone(shared.claim_ready(self.catalog,self.config,lane='cards',job_id=ready,paper_id=ready,target_id='page-00',assigned=True))
        with self.catalog.connect() as db:db.execute("UPDATE web_page_queue SET state='ready' WHERE paper_id=?",(waiting,))
        self.assertIsNone(shared.claim_ready(self.catalog,self.config,lane='cards',job_id=waiting,paper_id=waiting,target_id='page-01',assigned=True))
        self.assertIsNotNone(shared.claim_ready(self.catalog,self.config,lane='cards',job_id=waiting,paper_id=waiting,target_id='page-00',assigned=True))
        self.assertEqual(backlog.binding(self.catalog,'cards',waiting)['state'],'claimed')
        shared.check_claim(self.catalog,'cards',waiting,'page-00')
        with self.assertRaises(ValueError):shared.check_claim(self.catalog,'cards',waiting,'page-01')

    def test_card_claim_race_consumes_original_job_and_binding_once(self):
        pid=self.card('race');self.lease('cards',pid,pid,'page-00')
        def claim(_):return shared.claim_ready(self.catalog,self.config,lane='cards',job_id=pid,paper_id=pid,target_id='page-00',assigned=True)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(claim,range(2)))
        self.assertEqual(sum(item is not None for item in results),1)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT attempts FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()[0],1)

    def test_other_page_can_dispatch_while_earlier_assigned_head_prepares(self):
        waiting=self.card('earlier','waiting');later=self.card('same-page-later');rjob,rpid=self.review('other-page')
        self.lease('cards',waiting,waiting,'page-00');self.lease('cards',later,later,'page-00');self.lease('review',rjob,rpid,'page-08')
        status={'reserved_targets':list(self.entries)[:8],'cards_min_shortfall':0}
        allocation=shared.backlog_dispatch(self.catalog,self.config,self.entries,list(self.entries),status)
        self.assertEqual([(r['lane'],r['job_id'],r['target_id']) for r in allocation['claim_order']],[('review',rjob,'page-08')])
        self.assertEqual(backlog.binding(self.catalog,'cards',later)['target_id'],'page-00')

    def test_review_lease_cannot_use_a_newly_reserved_card_page(self):
        rid,pid=self.review('old-review');self.lease('review',rid,pid,'page-00')
        allocation=shared.backlog_dispatch(self.catalog,self.config,self.entries,list(self.entries),
            {'reserved_targets':list(self.entries)[:8],'cards_min_shortfall':0})
        self.assertEqual(allocation['claim_order'],[]);self.assertEqual(allocation['reserved_capacity'],8)

    def test_protected_page_never_dispatches_even_if_queued_head_was_ready(self):
        pid=self.card('protected');self.lease('cards',pid,pid,'page-00');self.entries['page-00']['verification_required']=True
        allocation=shared.backlog_dispatch(self.catalog,self.config,self.entries,list(self.entries),{'reserved_targets':[]})
        self.assertEqual(allocation['claim_order'],[])

    def observation(self,pid,*,kind='cards',complete=False):
        target='page-00';url='https://chatgpt.com/c/current';folder=self.root/'web_cards'/pid/'chatgpt';folder.mkdir(parents=True)
        path=folder/'attempt.json';atomic_json(path,{'target_id':target,'state':'submitted','conversation_url':url,
            'actual_prompt_sha256':'synthetic-verified-hash','send_click_started':True})
        self.entries[target].update(state='busy',kind=kind,paper_id=pid)
        report={'owner_pid':456,'activity_schema_version':1,'updated':100,'pages':[{'target_id':target,'checked_at':100,
            'activity_verified':True,'streaming':not complete,'complete':complete,'answers':1,'kind':kind,'url':url}]}
        return report,{target:{'_ledger_path':str(path)}},path

    def test_inventory_requires_current_owner_and_fresh_original_attempt(self):
        pid=self.card('current');report,latest,path=self.observation(pid)
        result=shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=456,at=101)
        self.assertEqual(result['page-00']['job_id'],pid)
        self.assertEqual(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=999,at=101),{})
        self.assertEqual(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=456,at=131),{})
        original=json.loads(path.read_text());atomic_json(path,{**original,'target_id':'other'})
        self.assertEqual(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=456,at=101),{})

    def test_current_complete_answer_waiting_for_collection_counts_until_page_saved(self):
        pid=self.card('complete');report,latest,_=self.observation(pid,complete=True)
        self.assertEqual(len(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=456,at=101)),1)
        self.entries['page-00']['state']='ready'
        self.assertEqual(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=456,at=101),{})

    def test_stale_busy_unknown_without_identity_never_makes_seventy_tasks(self):
        pid=self.card('unknown');report,latest,_=self.observation(pid)
        report['pages'][0]['activity_verified']=False
        self.assertEqual(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,owner_pid=456,at=101),{})

    def test_active_inventory_does_not_read_historical_review_bodies(self):
        pid=self.card('thin-inventory');report,latest,_=self.observation(pid)
        connect=self.catalog.connect
        @contextmanager
        def thin_connection():
            with connect() as db:
                def authorize(action,table,column,*args):
                    if action==sqlite3.SQLITE_READ and table=='card_review_jobs' and column=='result':
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                db.set_authorizer(authorize)
                yield db
        with patch.object(self.catalog,'connect',thin_connection):
            self.assertEqual(shared.active_targets(self.catalog,self.entries,self.entries,report,latest,
                owner_pid=456,at=101)['page-00']['job_id'],pid)

    def test_low_inventory_refill_is_local_and_rate_limited_to_sixty_seconds(self):
        state={}
        def reconcile(config,catalog,entries,targets,active,**options):
            return options['refill_callback'](catalog,config,remaining=100,current_tasks=0,queued_tasks=0,eligible_pages=20)
        with patch('browser.shared_page_backlog.reconcile',side_effect=reconcile),patch('browser.shared_workflow_queue.refill_backlog',return_value={'added':0}) as refill:
            first=maintain_shared_backlog(self.config,self.catalog,self.entries,self.entries,{}, {},inventory_complete=True,maintenance=state,at=100)
            second=maintain_shared_backlog(self.config,self.catalog,self.entries,self.entries,{}, {},inventory_complete=True,maintenance=state,at=159)
            third=maintain_shared_backlog(self.config,self.catalog,self.entries,self.entries,{}, {},inventory_complete=True,maintenance=state,at=160)
        self.assertEqual(first,{'added':0});self.assertEqual(third,first)
        self.assertEqual(second['state'],'waiting_refill_interval');self.assertEqual(refill.call_count,2)

    def test_health_blocked_ready_page_is_not_inventory_destination_or_reserved(self):
        pid=self.card('health-blocked-ready')
        before=copy.deepcopy(self.entries)
        with patch('browser.shared_workflow_queue.refill_backlog',return_value={}):
            result=maintain_shared_backlog(self.config,self.catalog,self.entries,list(self.entries),{}, {},
                inventory_complete=True,maintenance={},at=time.time(),excluded_targets={'page-00'})
        self.assertEqual(result['eligible_pages'],19)
        self.assertIn('page-00',result['protected_targets'])
        self.assertNotIn('page-00',result['reserved_targets'])
        self.assertNotIn('page-00',result['eligible_targets'])
        self.assertNotEqual(backlog.binding(self.catalog,'cards',pid)['target_id'],'page-00')
        self.assertEqual(self.entries,before)

    def test_backlog_writer_contention_preserves_bindings_and_retries_next_round(self):
        pid=self.card('waiting-for-writer')
        self.lease('cards',pid,pid,'page-00')
        with self.catalog.connect() as writer:
            writer.execute('BEGIN IMMEDIATE')
            result=maintain_shared_backlog(self.config,self.catalog,self.entries,list(self.entries),{}, {},
                inventory_complete=True,maintenance={},checkpoint=lambda:None)
        self.assertEqual(result['state'],'waiting_backlog_writer')
        self.assertFalse(result['inventory_complete'])
        self.assertEqual(backlog.binding(self.catalog,'cards',pid)['state'],'queued')
        with patch('browser.shared_workflow_queue.refill_backlog',return_value={}):
            result=maintain_shared_backlog(self.config,self.catalog,self.entries,list(self.entries),{}, {},
                inventory_complete=True,maintenance={},checkpoint=lambda:None)
        self.assertEqual(result['queued_tasks'],1)

    def test_all_health_blocked_pages_cannot_inflate_threshold_or_bind_stock(self):
        pid=self.card('no-healthy-destination')
        with patch('browser.shared_workflow_queue.refill_backlog') as refill:
            result=maintain_shared_backlog(self.config,self.catalog,self.entries,list(self.entries),{}, {},
                inventory_complete=True,maintenance={},at=time.time(),excluded_targets=set(self.entries))
        self.assertEqual(result['eligible_pages'],0)
        self.assertEqual(result['total_tasks'],0)
        self.assertEqual(result['queued_tasks'],0)
        self.assertEqual(result['reserved_targets'],[])
        self.assertEqual(result['protected_targets'],list(self.entries))
        self.assertIsNone(backlog.binding(self.catalog,'cards',pid))
        refill.assert_not_called()

    def test_verified_active_page_still_counts_when_other_page_health_is_blocked(self):
        pid=self.card('healthy-current');report,latest,_=self.observation(pid)
        before=copy.deepcopy(self.entries)
        with patch('browser.shared_workflow_queue.refill_backlog',return_value={}):
            result=maintain_shared_backlog(self.config,self.catalog,self.entries,list(self.entries),report,latest,
                inventory_complete=True,maintenance={},owner_pid=456,at=101,excluded_targets={'page-01'})
        self.assertEqual(result['current_tasks'],1)
        self.assertEqual(result['eligible_pages'],19)
        self.assertIn('page-00',result['eligible_targets'])
        self.assertIn('page-00',result['reserved_targets'])
        self.assertIn('page-01',result['protected_targets'])
        self.assertEqual(self.entries,before)

    def test_refill_uses_only_temporary_stock_target_and_real_review_candidates(self):
        original=copy.deepcopy(self.config)
        records=[{'lane':'cards'}]*30+[{'lane':'review'}]*20+[{'lane':'correction'}]*5
        with patch('review.card_review_queue.enqueue',return_value=2) as enqueue,patch('browser.shared_page_backlog.eligible_records',return_value=records),patch('cards.web_card_queue.select',return_value={'added':['a'],'refilled':['a']}) as select:
            result=shared.refill_backlog(self.catalog,self.config,remaining=40,current_tasks=10,queued_tasks=50,eligible_pages=20)
        self.assertEqual(select.call_args.args[1]['web_cards']['refill_min_pending'],65)
        self.assertEqual(result['cards_refilled'],1);enqueue.assert_called_once_with(self.catalog,self.config,maintain_cycles=False)
        self.assertEqual(self.config,original)

    def test_protected_queued_rows_do_not_consume_new_eligible_card_stock(self):
        for index in range(3):self.card('legacy-protected-'+str(index))
        with patch('review.card_review_queue.enqueue',return_value=0),patch('browser.shared_page_backlog.eligible_records',return_value=[]),patch('cards.web_card_queue.select',return_value={}) as select:
            result=shared.refill_backlog(self.catalog,self.config,remaining=100,current_tasks=0,queued_tasks=0,eligible_pages=20)
        self.assertEqual(select.call_args.args[1]['web_cards']['refill_min_pending'],103)
        self.assertEqual(result['requested_card_stock'],100);self.assertEqual(result['raw_pending_offset'],3)
        self.assertEqual(len(cards.jobs(self.catalog)),3)

    def test_many_real_reviews_do_not_starve_reserved_card_refill(self):
        self.config['web_cards']['selection_fraction']=.001
        for index in range(80):self.review('review-stock-'+str(index))
        for index in range(3):self.card('existing-card-'+str(index))
        for index in range(35):self.paper('download-not-yet-selected-'+str(index))
        before=copy.deepcopy(self.config)
        with patch('review.card_review_queue.enqueue',return_value=0):
            result=shared.refill_backlog(self.catalog,self.config,remaining=63,current_tasks=5,queued_tasks=32,eligible_pages=8)
        self.assertEqual(result['reserved_card_stock'],32);self.assertEqual(result['requested_card_stock'],32)
        self.assertEqual(result['cards_added'],29)
        self.assertEqual(len([row for row in backlog.eligible_records(self.catalog,self.config) if row['lane']=='cards']),32)
        self.assertEqual(len(reviews.rows(self.catalog)),80);self.assertEqual(self.config,before)

    def test_reserved_stock_uses_available_pages_depth_and_total_task_budget(self):
        records=[{'lane':'review'}]*250
        with patch('review.card_review_queue.enqueue',return_value=0),patch('browser.shared_page_backlog.eligible_records',return_value=records),patch('cards.web_card_queue.select',return_value={}):
            scarce=shared.refill_backlog(self.catalog,self.config,remaining=8,current_tasks=0,queued_tasks=0,eligible_pages=2)
            self.config['web_cards']['shared_window']['backlog']['target_tasks']=25
            bounded=shared.refill_backlog(self.catalog,self.config,remaining=5,current_tasks=20,queued_tasks=0,eligible_pages=20)
        self.assertEqual(scarce['requested_card_stock'],8);self.assertEqual(bounded['requested_card_stock'],5)

    def test_reserved_refill_does_not_resume_paused_card_lane(self):
        atomic_json(self.root/'web-card-control.json',{'paused_by_user':True})
        original=(self.root/'web-card-control.json').read_bytes()
        with patch('review.card_review_queue.enqueue',return_value=0),patch('browser.shared_page_backlog.eligible_records',return_value=[{'lane':'review'}]*250),patch('cards.web_card_queue.select') as select:
            result=shared.refill_backlog(self.catalog,self.config,remaining=100,current_tasks=0,queued_tasks=0,eligible_pages=20)
        select.assert_not_called();self.assertEqual(result['cards_added'],0)
        self.assertEqual((self.root/'web-card-control.json').read_bytes(),original)


if __name__=='__main__':unittest.main()
