"""Real SQLite/filesystem evidence for safe mixed future-page scheduling."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from core.api import paths__WorkspacePath as Path
import tempfile
import time
import unittest
from unittest.mock import patch

from core.catalog import Catalog, now
from correction import card_correction_queue as corrections
from review import card_review_queue as reviews
from browser import shared_page_backlog as backlog
from cards import web_card_queue as cards
from browser import web_page_queue as materials
from core.services import atomic_json
from cards.web_card_inputs import digest


class SharedPageBacklogTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path),
            'studio_library_root':str(self.root/'library'),
            'web_cards':{'enabled':True, 'max_parallel_jobs':20, 'min_reserved_pages':8,
                'shared_window':{'enabled':True, 'backlog':{
                    'enabled':True, 'low_watermark':70, 'target_tasks':100, 'queue_depth':4}}},
            'card_review':{'enabled':True, 'parallel_jobs':20},
            'card_correction':{'enabled':True, 'parallel_jobs':20}}
        cards.install(self.catalog); reviews.install(self.catalog)
        corrections.install(self.catalog); materials.install(self.catalog)
        backlog.install(self.catalog)
        self.entries = {f't{i:02}':{'state':'ready', 'kind':'cards', 'slot':i} for i in range(20)}
        self.active = {}
        self.number = 0

    def paper(self, name):
        pid = self.catalog.upsert({'title':name, 'doi':'10.9999/'+name})
        source = self.root/(name+'.pdf')
        source.write_bytes(('synthetic source '+name).encode())
        self.catalog.update(pid, acquisition='available', asset_path=str(source), asset_hash=digest(source))
        return self.catalog.get(pid)

    def card(self, name=None, *, target=None, material_state='ready', state='queued', retry_at=0):
        self.number += 1
        paper = self.paper(name or f'card-{self.number}')
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated,retry_at) VALUES(?,?,?,?,?,?,?)',
                       (paper['id'],paper['asset_hash'],paper['title'],'{}',state,now(),retry_at))
            if target is not None:
                db.execute('INSERT INTO web_page_queue(paper_id,target_id,state,assigned) VALUES(?,?,?,?)',
                           (paper['id'],target,material_state,float(self.number)))
        return 'cards', paper['id'], paper['id']

    def review(self, name=None, *, state='ready', target=None):
        self.number += 1
        paper = self.paper(name or f'review-{self.number}')
        card = self.root/'library'/paper['id']/'card.json'
        card.parent.mkdir(parents=True); card.write_text('{}')
        self.catalog.update(paper['id'], card_path=str(card))
        jid = 'review-'+paper['id']
        folder = self.root/'reviews'/jid
        with self.catalog.connect() as db:
            db.execute('INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (jid,paper['id'],digest(card),paper['asset_hash'],paper['title'],state,str(folder),now()))
            if target is not None:
                db.execute("INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned) VALUES('review',?,?,?,?)",
                           (jid,paper['id'],target,float(self.number)))
        return 'review',jid,paper['id']

    def correction(self, *, kind='source_rework'):
        lane, rid, pid = self.review(state='rework_queued')
        job = next(row for row in reviews.rows(self.catalog) if row['id'] == rid)
        correction = corrections._enqueue(self.catalog, job, kind, {'synthetic':True}, state='ready')
        old = Path(self.catalog.get(pid)['card_path'])
        backup = self.root/'backup'/pid
        backup.mkdir(parents=True); (backup/'card.json').write_bytes(old.read_bytes())
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,?,?,?)',
                (pid,job['source_sha256'],job['title'],json.dumps({'rework':{'kind':'source_review',
                 'old_card_path':str(old),'old_sha256':digest(old),'backup':str(backup),
                 'correction_id':correction['id'],'review_id':rid}}),'queued',now()))
        return 'correction',correction['id'],pid

    def make_active(self, *, cards_count=8, total=20):
        self.active = {}
        for i,target in enumerate(self.entries):
            if i >= total:
                break
            lane = 'cards' if i < cards_count else 'review'
            self.entries[target].update(state='busy', kind=lane)
            self.active[target] = {'lane':lane, 'job_id':'current-'+target, 'paper_id':'original-'+target}

    def maintain(self, **kwargs):
        return backlog.reconcile(self.config,self.catalog,self.entries,list(self.entries),self.active,
                                 cards_min_pages=8,**kwargs)

    def raw_bindings(self):
        with self.catalog.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM shared_page_backlog ORDER BY lane,job_id')]

    def arrivals(self):
        with self.catalog.connect() as db:
            return [tuple(row) for row in db.execute('SELECT * FROM shared_workflow_arrivals ORDER BY sequence')]

    def test_score_head_reorders_unclaimed_only_without_changing_arrivals(self):
        old=self.review('older-low',target='t08');high=self.review('newer-high',target='t08')
        with self.catalog.connect() as db:
            db.execute('UPDATE card_review_jobs SET priority=? WHERE id=?',(60,old[1]))
            db.execute('UPDATE card_review_jobs SET priority=? WHERE id=?',(90,high[1]))
        before=self.arrivals()
        self.config['web_cards']['shared_window']['backlog']['queue_order']='paper_score'
        head=backlog.head_ready(self.catalog,self.config,'t08')
        self.assertEqual(head['job_id'],high[1]);self.assertEqual(before,self.arrivals())
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,*old[:2],'t08')
        self.assertIsNone(backlog.head_ready(self.catalog,self.config,'t08'))
        self.assertEqual(before,self.arrivals())

    def test_fixed_lanes_keep_capacity_despite_older_review_fifo(self):
        fixed = {'cards':[f't{i:02}' for i in range(8)],
                 'review':[f't{i:02}' for i in range(8,12)],
                 'correction':[f't{i:02}' for i in range(12,15)]}
        for i in range(70):
            self.review()
        for i in range(40):
            self.card()
        for i in range(12):
            self.correction()
        before = self.arrivals()
        with patch.object(backlog, 'fixed_reservations', return_value=fixed):
            result = self.maintain()
        rows = self.raw_bindings()
        for lane, targets in fixed.items():
            lane_rows = [row for row in rows if row['target_id'] in targets]
            self.assertEqual(len(lane_rows), len(targets)*4)
            self.assertTrue(all(row['lane'] == lane for row in lane_rows))
        self.assertTrue(set(before).issubset(set(self.arrivals())))
        self.assertEqual(result['lane_reserved_targets'], fixed)

    def test_fixed_protected_page_is_not_replaced_or_lent(self):
        fixed = {'cards':['t00'], 'review':['t01'], 'correction':['t02']}
        self.entries['t02'].update(state='needs_inspection', submission_unknown=True)
        for i in range(20):
            self.review()
        self.correction()
        with patch.object(backlog, 'fixed_reservations', return_value=fixed):
            result = self.maintain()
        self.assertIn('t02', result['protected_targets'])
        self.assertFalse(any(row['target_id'] == 't02' for row in self.raw_bindings()))
        self.assertEqual(result['lane_reserved_targets']['correction'], ['t02'])

    def test_idle_fixed_pages_lend_after_timeout_and_keep_own_preparing_capacity(self):
        fixed={'cards':['t00'],'review':['t01','t02'],'correction':[]}
        self.entries={key:self.entries[key] for key in ('t00','t01','t02','t03')}
        self.config['web_cards']['shared_window']['backlog']['idle_borrow_enabled']=True
        self.config['web_cards']['shared_window']['health_repair']={
            'stalled_after_seconds_by_lane':{'cards':120,'review':60,'correction':180}}
        for i in range(20):self.card(target='t00')
        before=self.arrivals()
        with patch.object(backlog,'fixed_reservations',return_value=fixed):
            first=self.maintain(now=1000)
            second=self.maintain(now=1059)
            self.assertEqual(first['idle_borrow_targets'],[])
            self.assertEqual(second['idle_borrow_targets'],[])
            due=self.maintain(now=1121)
            self.assertEqual(set(due['idle_borrow_targets']),{'t01','t02','t03'})
            self.assertEqual({r['target_id'] for r in self.raw_bindings()},set(self.entries))
            from browser.shared_workflow_queue import backlog_dispatch
            allocation=backlog_dispatch(self.catalog,self.config,self.entries,list(self.entries),due)
            self.assertEqual(set(allocation['card_ready']),set(self.entries))
            job=self.review(state='preparing')
            returned=self.maintain(now=1130)
        self.assertNotIn('t01',returned['idle_borrow_targets'])
        self.assertTrue(all(r['lane']=='review' for r in self.raw_bindings() if r['target_id']=='t01'))
        self.assertTrue(set(before).issubset(set(self.arrivals())))
        self.assertEqual(self.entries['t01']['state'],'ready')

    def test_idle_timer_survives_reconcile_but_resets_after_new_page_evidence(self):
        fixed={'cards':['t00'],'review':['t01'],'correction':[]}
        self.entries={key:self.entries[key] for key in ('t00','t01')}
        self.config['web_cards']['shared_window']['backlog']['idle_borrow_enabled']=True
        self.config['web_cards']['shared_window']['health_repair']={
            'stalled_after_seconds_by_lane':{'cards':120,'review':60}}
        self.card()
        with patch.object(backlog,'fixed_reservations',return_value=fixed):
            self.maintain(now=1000)
            self.assertIn('t01',self.maintain(now=1061)['idle_borrow_targets'])
            self.entries['t01']['raw_sha256']='new-saved-answer'
            self.assertNotIn('t01',self.maintain(now=1070)['idle_borrow_targets'])
            self.entries['t01'].update(state='busy')
            self.active['t01']={'lane':'cards','job_id':'original','paper_id':'original'}
            self.assertNotIn('t01',self.maintain(now=2000)['idle_borrow_targets'])
            self.assertEqual(self.maintain(now=3000,inventory_complete=False)['idle_borrow_targets'],[])

    def test_claimed_idle_loan_stays_with_its_original_task_when_own_work_arrives(self):
        from browser.shared_workflow_queue import claim_ready
        fixed={'cards':['t00'],'review':['t01'],'correction':[]}
        self.entries={key:self.entries[key] for key in ('t00','t01')}
        self.config['web_cards']['shared_window']['backlog']['idle_borrow_enabled']=True
        self.config['web_cards']['shared_window']['health_repair']={
            'stalled_after_seconds_by_lane':{'cards':120,'review':60}}
        for i in range(8):self.card(target='t00')
        with patch.object(backlog,'fixed_reservations',return_value=fixed):
            self.maintain(now=1000);self.maintain(now=1061)
            head=backlog.head_ready(self.catalog,self.config,'t01')
            claimed=claim_ready(self.catalog,self.config,lane='cards',job_id=head['job_id'],
                paper_id=head['paper_id'],target_id='t01',assigned=True)
            self.assertIsNotNone(claimed)
            self.entries['t01'].update(state='busy',kind='cards')
            self.active['t01']={'lane':'cards','job_id':head['job_id'],'paper_id':head['paper_id']}
            self.review()
            self.maintain(now=2000)
        binding=backlog.binding(self.catalog,'cards',head['job_id'])
        self.assertEqual(binding['target_id'],'t01');self.assertEqual(binding['state'],'claimed')

    def test_exactly_70_does_not_scan_reflow_or_add(self):
        self.make_active()
        for i in range(50):
            self.card(target=f't{i%20:02}')
        for i in range(20):
            self.card()
        scanned=[]
        result=self.maintain(refill_callback=lambda *args,**kwargs:scanned.append(kwargs))
        self.assertEqual(result['total_tasks'],70)
        self.assertFalse(result['triggered'])
        self.assertEqual(scanned,[])
        self.assertEqual(result['moved'],0)
        self.assertEqual(result['queued_tasks'],50)

    def test_69_triggers_scan_and_fills_real_100(self):
        self.make_active()
        for i in range(49):
            self.card(target=f't{i%20:02}')
        for i in range(40):
            self.card()
        scanned=[]
        result=self.maintain(refill_callback=lambda *args,**kwargs:scanned.append(kwargs))
        self.assertTrue(result['triggered'])
        self.assertEqual(scanned[0]['remaining'],31)
        self.assertEqual(scanned[0]['current_tasks'],20)
        self.assertEqual(result['total_tasks'],100)
        self.assertEqual(result['queued_tasks'],80)
        self.assertEqual(result['shortfall'],0)

    def test_empty_current_positions_are_not_fabricated(self):
        for i in range(110):
            self.card()
        result=self.maintain()
        self.assertEqual(result['current_tasks'],0)
        self.assertEqual(result['queued_tasks'],80)
        self.assertEqual(result['total_tasks'],80)
        self.assertEqual(result['status'],'shortfall')
        self.assertEqual(result['shortfall'],20)
        self.assertEqual(max(sum(row['target_id']==target for row in self.raw_bindings()) for target in self.entries),4)

    def test_reserved_eight_only_cards_other_pages_mix_three_lanes(self):
        self.make_active()
        for i in range(40):
            self.card()
        for i in range(30):
            self.review()
            self.correction()
        result=self.maintain()
        self.assertEqual(result['reserved_targets'],[f't{i:02}' for i in range(8)])
        rows=self.raw_bindings()
        self.assertTrue(all(row['lane']=='cards' for row in rows if row['target_id'] in result['reserved_targets']))
        shared=[row['lane'] for row in rows if row['target_id'] not in result['reserved_targets']]
        self.assertEqual(set(shared),{'cards','review','correction'})
        self.assertEqual(result['total_tasks'],100)

    def test_load_reflow_moves_future_only_and_preserves_arrivals_and_material_state(self):
        self.make_active()
        for i in range(60):
            self.card(target='t00',material_state='preparing' if i==1 else 'ready')
        before=self.arrivals()
        result=self.maintain()
        rows=self.raw_bindings()
        self.assertGreater(result['moved'],0)
        loads=[sum(row['target_id']==target for row in rows) for target in self.entries]
        self.assertLessEqual(max(loads),4)
        self.assertLessEqual(max(loads)-min(loads),1)
        self.assertEqual(self.arrivals(),before)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM web_page_queue WHERE state='preparing'").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM web_page_queue q JOIN shared_page_backlog b USING(paper_id) WHERE q.target_id!=b.target_id').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM web_card_jobs WHERE state!='queued'").fetchone()[0],0)
        self.assertEqual(self.active['t00']['job_id'],'current-t00')

    def test_unknown_unobserved_draft_verification_and_moved_pages_are_not_destinations(self):
        for i in range(80):
            self.card()
        self.entries['t00'].update(state='busy')  # Historical busy, no verified receipt.
        self.entries['t01'].update(state='needs_inspection',submission_unknown=True)
        self.entries['t02'].update(state='ready',draft_text='user draft')
        self.entries['t03'].update(state='ready',verification_required=True)
        self.entries['t04'].update(state='ready',external=True)
        result=self.maintain()
        bad={f't{i:02}' for i in range(5)}
        self.assertEqual(set(result['protected_targets']),bad)
        self.assertEqual(result['current_tasks'],0)
        self.assertTrue(all(row['target_id'] not in bad for row in self.raw_bindings()))
        self.assertEqual(result['total_tasks'],60)

    def test_paused_binding_stays_physical_but_not_runnable_stock_and_can_be_skipped(self):
        paused=self.review(target='t10')
        card=self.card(target='t10')
        atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
        result=self.maintain()
        self.assertEqual(backlog.binding(self.catalog,*paused[:2])['target_id'],'t10')
        self.assertEqual(result['paused_queued_count'],1)
        self.assertEqual(result['queued_tasks'],1)
        self.assertEqual(result['physical_queued_tasks'],2)
        head=backlog.head_ready(self.catalog,self.config,'t10')
        # The card may safely rebalance to a reserved page, while its paused
        # predecessor keeps t10. Directly restore its binding to test skip.
        binding=backlog.binding(self.catalog,*card[:2])
        with self.catalog.connect() as db:
            db.execute('UPDATE shared_page_backlog SET target_id=? WHERE lane=? AND job_id=?',('t10',*card[:2]))
            db.execute('UPDATE web_page_queue SET target_id=? WHERE paper_id=?',('t10',card[2]))
        self.assertEqual(backlog.head_ready(self.catalog,self.config,'t10')['job_id'],card[1])
        self.assertTrue(json.loads((self.root/'card-review-control.json').read_text())['paused_by_user'])

    def test_preparing_head_cannot_be_overtaken(self):
        first=self.review(state='preparing',target='t10')
        second=self.review(target='t10')
        self.assertIsNone(backlog.head_ready(self.catalog,self.config,'t10'))
        with self.catalog.connect() as db:
            self.assertFalse(backlog.check_head_binding(db,self.config,*second[:2],'t10'))
            db.execute("UPDATE card_review_jobs SET state='ready' WHERE id=?",(first[1],))
            self.assertTrue(backlog.check_head_binding(db,self.config,*first[:2],'t10'))

    def test_unknown_attempt_is_neither_new_stock_nor_reassigned(self):
        item=self.card(target='t00')
        folder=self.root/'web_cards'/item[2]/'chatgpt'
        folder.mkdir(parents=True)
        atomic_json(folder/'attempt.json',{'state':'needs_inspection','send_click_started':True,'target_id':'original-page'})
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],0)
        self.assertIsNone(backlog.binding(self.catalog,*item[:2]))
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT target_id FROM web_page_queue WHERE paper_id=?',(item[2],)).fetchone()[0],'t00')
        self.assertEqual(json.loads((folder/'attempt.json').read_text())['target_id'],'original-page')

    def test_explicit_unsent_attempt_is_allowed_but_missing_send_evidence_is_not(self):
        valid=self.card()
        invalid=self.card()
        for item,click in ((valid,False),(invalid,None)):
            folder=self.root/'web_cards'/item[2]/'chatgpt'
            folder.mkdir(parents=True)
            atomic_json(folder/'attempt.json',{'state':'not_sent','send_click_started':click})
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],1)
        self.assertIsNotNone(backlog.binding(self.catalog,*valid[:2]))
        self.assertIsNone(backlog.binding(self.catalog,*invalid[:2]))

    def test_review_active_unsent_ledger_is_not_runnable_until_original_owner_archives_it(self):
        item=self.review()
        job=next(row for row in reviews.rows(self.catalog) if row['id']==item[1])
        folder=Path(job['folder']);folder.mkdir(parents=True)
        atomic_json(folder/'attempt.json',{'state':'not_sent','send_click_started':False})
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],0)
        self.assertIsNone(backlog.binding(self.catalog,*item[:2]))
        self.assertTrue((folder/'attempt.json').is_file())

    def test_source_hash_identity_existing_card_and_human_protections(self):
        changed=self.card('source-changed')
        identity=self.card('identity-unresolved')
        human=self.card('human-protected')
        existing=self.card('existing-card')
        Path(self.catalog.get(changed[2])['asset_path']).write_bytes(b'new scientific source')
        with self.catalog.connect() as db:
            paper=self.catalog.get(identity[2])
            db.execute('UPDATE papers SET metadata=? WHERE id=?',(json.dumps({**paper['metadata'],'version_review_required':True}),identity[2]))
        self.catalog.decide(human[2],'keep')
        card=Path(self.config['studio_library_root'])/existing[2]/'card.json'
        card.parent.mkdir(parents=True);card.write_text('original scientific card')
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],0)
        self.assertEqual(self.raw_bindings(),[])
        self.assertEqual(card.read_text(),'original scientific card')

    def test_local_corrections_never_consume_page_positions(self):
        self.correction(kind='formatting')
        self.correction(kind='quote_location')
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],0)

    def test_claim_is_pinned_and_new_queued_material_cannot_rebind_it(self):
        item=self.card(target='t00')
        self.maintain()
        bound=backlog.binding(self.catalog,*item[:2])
        target=bound['target_id']
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.assertTrue(backlog.check_head_binding(db,self.config,*item[:2],target))
            self.assertTrue(backlog.mark_claimed(db,*item[:2],target))
            db.execute("UPDATE web_card_jobs SET state='preparing' WHERE paper_id=?",(item[2],))
        self.entries[target].update(state='needs_inspection',submission_unknown=True)
        for i in range(10):
            self.card()
        result=self.maintain()
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['target_id'],target)
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'claimed')
        self.assertEqual(result['current_tasks'],0)
        with self.catalog.connect() as db:
            self.assertTrue(backlog.check_claim_binding(db,*item[:2],target))
            self.assertFalse(backlog.check_claim_binding(db,*item[:2],'wrong-page'))

    def test_paused_before_page_use_can_rollback_exact_claim_without_changing_fifo(self):
        item=self.card(target='t00')
        self.maintain()
        target=backlog.binding(self.catalog,*item[:2])['target_id']
        before=self.arrivals()
        with self.catalog.connect() as db:
            self.assertTrue(backlog.mark_claimed(db,*item[:2],target))
            self.assertFalse(backlog.rollback_claim(db,*item[:2],'wrong-page'))
            self.assertTrue(backlog.rollback_claim(db,*item[:2],target))
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'queued')
        self.assertEqual(self.arrivals(),before)

    def test_unknown_claimed_page_with_stale_ready_entry_stays_protected(self):
        first=self.card(target='t00')
        self.maintain()
        target=backlog.binding(self.catalog,*first[:2])['target_id']
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,*first[:2],target)
            db.execute("UPDATE web_card_jobs SET state='needs_inspection' WHERE paper_id=?",(first[2],))
        self.entries[target].update(state='ready')
        for i in range(90):
            self.card()
        result=self.maintain()
        self.assertIn(target,result['protected_targets'])
        self.assertEqual(backlog.binding(self.catalog,*first[:2])['state'],'claimed')
        self.assertIsNone(backlog.head_ready(self.catalog,self.config,target))
        self.assertFalse(any(row['state']=='queued' and row['target_id']==target for row in self.raw_bindings()))

    def test_untouched_failed_claim_can_be_bound_again_without_changing_fifo(self):
        from browser.shared_claim_recovery import release_untouched
        item=self.card(target='t00')
        self.maintain();target=backlog.binding(self.catalog,*item[:2])['target_id']
        arrivals=self.arrivals()
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,*item[:2],target)
            db.execute("UPDATE web_card_jobs SET state='needs_inspection' WHERE paper_id=?",(item[2],))
        release_untouched(self.catalog,*item[:2],target)
        self.assertIsNone(backlog.binding(self.catalog,*item[:2]))
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='queued' WHERE paper_id=?",(item[2],))
        self.maintain()
        self.assertIsNotNone(backlog.binding(self.catalog,*item[:2]))
        self.assertEqual(self.arrivals(),arrivals)

    def test_ended_unsent_claim_recovery_does_not_grant_retry_or_clear_unknown(self):
        from browser.shared_claim_recovery import recover_claims
        item=self.card(target='t00')
        self.maintain();target=backlog.binding(self.catalog,*item[:2])['target_id']
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,*item[:2],target)
            db.execute("UPDATE web_card_jobs SET state='failed' WHERE paper_id=?",(item[2],))
        path=self.root/'web_cards'/item[2]/'chatgpt'/'attempt.json'
        path.parent.mkdir(parents=True)
        atomic_json(path,{'state':'submitted','target_id':target,'send_click_started':True})
        self.entries[target]['state']='ready_blank'
        health={'state':'checked','checked_at':100,'pages':{target:{'health':'healthy_blank','evidence':{}}}}
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'claimed')
        atomic_json(path,{'state':'not_sent','target_id':target,'send_click_started':False})
        self.assertEqual(len(recover_claims(self.catalog,self.entries,health,at=100)),1)
        self.assertIsNone(backlog.binding(self.catalog,*item[:2]))
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(item[2],)).fetchone()[0],'failed')

    def test_fingerprint_cache_invalidates_same_size_content_change(self):
        item=self.card()
        self.maintain()
        source=Path(self.catalog.get(item[2])['asset_path'])
        original=source.read_bytes()
        original_stat=source.stat()
        source.write_bytes(b'X'*len(original))
        os.utime(source,ns=(original_stat.st_atime_ns,original_stat.st_mtime_ns))
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],0)
        # The original binding remains evidence; it cannot move or become stock.
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'queued')

    def test_fingerprint_read_between_version_checks_fails_closed(self):
        source=self.root/'changing.pdf';source.write_bytes(b'original')
        version=backlog._stat_key(source)
        changed=(*version[:-1],version[-1]+1)
        with patch('browser.shared_page_backlog._stat_key',side_effect=[version,changed]):
            with self.assertRaisesRegex(ValueError,'changed'):
                backlog._fingerprint(source)

    def test_cold_fingerprints_yield_outside_write_transactions_and_share_cache(self):
        item=self.card();source=Path(self.catalog.get(item[2])['asset_path'])
        backlog._DIGEST_VERSIONS.clear()
        calls=[]
        token=backlog._HASH_CHECKPOINT.set(lambda:calls.append('owner loop'))
        try:self.assertEqual(backlog._fingerprint(source),digest(source))
        finally:backlog._HASH_CHECKPOINT.reset(token)
        self.assertTrue(calls)
        with patch('cards.web_card_inputs.digest',side_effect=AssertionError('must reuse verified file version')):
            self.assertEqual(backlog._fingerprint(source),digest(source))

    def test_large_inventory_does_not_evict_warmed_fingerprints_before_locked_pass(self):
        backlog._DIGEST_VERSIONS.clear()
        sources=[]
        for i in range(1100):
            path=self.root/('source-'+str(i));path.write_bytes(str(i).encode());sources.append(path)
        with patch('cards.web_card_inputs.digest',wraps=digest) as read_all:
            first=[backlog._fingerprint(path) for path in sources]
            second=[backlog._fingerprint(path) for path in sources]
        self.assertEqual(first,second);self.assertEqual(read_all.call_count,1100)

    def test_changed_source_replaces_cached_version_and_is_read_again(self):
        backlog._DIGEST_VERSIONS.clear()
        path=self.root/'changing-original';path.write_bytes(b'original version')
        first=backlog._fingerprint(path);path.write_bytes(b'changed original version')
        second=backlog._fingerprint(path)
        self.assertNotEqual(first,second);self.assertEqual(second,digest(path))
        self.assertEqual(len(backlog._DIGEST_VERSIONS),1)

    def test_no_live_pages_never_hashes_all_pending_sources_or_changes_bindings(self):
        from browser.web_card_pool import maintain_shared_backlog
        self.card();before=self.arrivals()
        with patch.object(backlog,'reconcile',side_effect=AssertionError('cold scan must wait for pages')):
            result=maintain_shared_backlog(self.config,self.catalog,{},[],{}, {},
                inventory_complete=True,maintenance={})
        self.assertEqual(result['state'],'waiting_pages');self.assertTrue(result['bindings_preserved'])
        self.assertEqual(self.arrivals(),before)

    def test_corrupt_single_rework_does_not_block_other_pages(self):
        for value in ([{'old_card_path':'bad'}],'invalid',12):
            item=self.card()
            with self.catalog.connect() as db:
                db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                           (json.dumps({'rework':value}),item[2]))
        good=self.card()
        result=self.maintain()
        self.assertEqual(result['queued_tasks'],1)
        self.assertIsNotNone(backlog.binding(self.catalog,*good[:2]))

    def test_excluded_claimed_pages_do_not_fake_card_minimum_capacity(self):
        for i,target in enumerate(self.entries):
            if i>=13:
                break
            item=self.card()
            with self.catalog.connect() as db:
                db.execute("INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES(?,?,?,?,?,'claimed')",
                           (*item[:2],item[2],target,float(i)))
        result=self.maintain()
        self.assertEqual(result['eligible_pages'],7)
        self.assertEqual(len(result['reserved_targets']),7)
        self.assertEqual(result['cards_min_shortfall'],1)

    def test_preparation_and_claim_race_between_refill_and_reflow_remains_bound(self):
        first=self.card(target='t00',material_state='preparing')
        second=self.card(target='t01')
        def race(catalog,config,**kwargs):
            with catalog.connect() as db:
                bound=db.execute('SELECT target_id FROM shared_page_backlog WHERE lane=? AND job_id=?',second[:2]).fetchone()
                backlog.mark_claimed(db,*second[:2],bound['target_id'])
                db.execute("UPDATE web_card_jobs SET state='preparing' WHERE paper_id=?",(second[2],))
                db.execute("UPDATE web_page_queue SET state='ready' WHERE paper_id=?",(first[2],))
        self.maintain(refill_callback=race)
        self.assertEqual(backlog.binding(self.catalog,*second[:2])['state'],'claimed')
        self.assertEqual(backlog.binding(self.catalog,*second[:2])['target_id'],'t01')
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM web_page_queue WHERE paper_id=?',(first[2],)).fetchone()[0],'ready')

    def test_incomplete_inventory_does_not_scan_migrate_or_reflow(self):
        self.card(target='t00')
        scanned=[]
        result=self.maintain(inventory_complete=False,refill_callback=lambda *args,**kwargs:scanned.append(kwargs))
        self.assertEqual(result['status'],'waiting_inventory')
        self.assertEqual(self.raw_bindings(),[])
        self.assertEqual(scanned,[])

    def test_repeated_and_concurrent_reconcile_preserve_arrivals_and_do_not_duplicate(self):
        for i in range(35):
            self.card()
        before=self.arrivals()
        result=self.maintain(now=time.time())
        first=self.raw_bindings()
        self.maintain()
        self.assertEqual(self.raw_bindings(),first)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.maintain(),range(2)))
        self.assertEqual(self.raw_bindings(),first)
        self.assertEqual(len(first),35)
        self.assertEqual(self.arrivals(),before)
        self.assertTrue(all(result['total_tasks']==35 for result in results))

    def test_refill_crossing_70_still_completes_original_trigger_to_target(self):
        self.make_active()
        for i in range(49):
            self.card(target=f't{i%20:02}')
        def replenish(catalog,config,**kwargs):
            for i in range(32):
                self.card(target=f't{i%20:02}')
        result=self.maintain(refill_callback=replenish)
        self.assertTrue(result['triggered'])
        self.assertEqual(result['total_tasks'],100)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT triggered FROM shared_page_backlog_meta').fetchone()[0],1)

    def test_zero_or_missing_candidates_is_real_shortfall(self):
        result=self.maintain()
        self.assertEqual(result['total_tasks'],0)
        self.assertEqual(result['shortfall'],100)
        self.assertEqual(result['status'],'shortfall')

    def test_idle_reservation_holds_during_preparation_and_paused_cards_can_lend_it(self):
        for i in range(30):
            self.review(state='preparing')
        result=self.maintain()
        self.assertEqual(len(result['reserved_targets']),8)
        self.assertTrue(all(row['target_id'] not in result['reserved_targets'] for row in self.raw_bindings()))
        atomic_json(self.root/'web-card-control.json',{'paused_by_user':True})
        result=self.maintain()
        self.assertEqual(result['reserved_targets'],[])


    def test_preparation_heads_include_queued_page_head_despite_unassigned_ready_stock(self):
        head=self.review('page-head-needs-input',state='queued',target='t08')
        behind=self.review('page-second',state='queued',target='t08')
        for i in range(20):self.review('ready-stock-'+str(i),state='ready')
        self.maintain()
        with self.catalog.connect() as db:
            heads=backlog.preparation_head_ids(db,self.catalog,self.config,'review')
            rows=db.execute("SELECT b.*,a.queued_at,a.sequence FROM shared_page_backlog b JOIN shared_workflow_arrivals a USING(lane,job_id) WHERE b.target_id='t08' AND b.state='queued'").fetchall()
            records=backlog._source_records(db,time.time(),self.config)
            first=sorted(rows,key=lambda r:backlog._fifo({**dict(r),**records.get((r['lane'],r['job_id']),{})}))[0]
            self.assertIn(first['job_id'],heads)
            self.assertEqual(len({r['job_id'] for r in rows}&heads),1)

if __name__ == '__main__':
    unittest.main()


class DynamicLaneMinimumReservations(SharedPageBacklogTests):
    def test_expansion_uses_idle_pages_and_keeps_other_lane_activity(self):
        from core.concurrency_control import set_limits
        shared=self.config['web_cards']['shared_window']
        shared['fixed_lane_slots']={'cards':['0','1','2','3','4','5','6','7'], 'review':['8','9','10','11'], 'correction':['12','13','14']}
        registry={'slots':[{'slot_id':str(i),'target_id':f't{i:02}'} for i in range(20)]}
        atomic_json(self.root/'shared-gpt-window.json',registry)
        entries=dict(self.entries);entries['t15']={'state':'busy','kind':'cards'};entries['t16']={'state':'needs_inspection','kind':'review'}
        atomic_json(self.root/'gpt-window-pool.json',{'windows':entries})
        set_limits(self.config,{'review_min_pages':6,'correction_min_pages':4})
        with patch('browser.shared_browser_window.validate_registry'):
            result=backlog.fixed_reservations(self.config,self.catalog)
        self.assertEqual(len(result['review']),6);self.assertEqual(len(result['correction']),4)
        self.assertNotIn('t15',result['review']+result['correction'])
        self.assertNotIn('t16',result['review']+result['correction'])
        self.assertEqual(len({t for rows in result.values() for t in rows}),18)



class RetirementScopeTests(unittest.TestCase):
    setUp=SharedPageBacklogTests.setUp
    paper=SharedPageBacklogTests.paper
    card=SharedPageBacklogTests.card
    maintain=SharedPageBacklogTests.maintain

    def test_retirement_scan_does_not_verify_archives_unrelated_to_current_claims(self):
        from browser.shared_claim_recovery import recover_claims
        item=self.card(target='t00');self.maintain()
        target=backlog.binding(self.catalog,*item[:2])['target_id']
        with self.catalog.connect() as db:backlog.mark_claimed(db,*item[:2],target)
        ledger=self.root/'web_cards'/item[2]/'chatgpt/attempt.json'
        ledger.parent.mkdir(parents=True)
        atomic_json(ledger,{'state':'submitted','target_id':target,'send_click_started':True})
        original=ledger.read_bytes()
        journal=self.root/'shared-page-repairs/unrelated/journal.json'
        journal.parent.mkdir(parents=True)
        atomic_json(journal,{'state':'ready','old_target_id':'other-old-target',
            'health':{'replace_allowed':True},'archive_hashes':{
                name:'unchanged-evidence' for name in ['health.json','body.txt','page.html','ledger-before.json','page.png']}})
        health={'state':'checked','checked_at':100,'pages':{}}
        for state in ['busy','retired_replaced']:
            self.entries[target]['state']=state
            with patch('browser.shared_claim_recovery._diagnostic_verified',side_effect=AssertionError('unrelated archive must not be opened')):
                self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
            self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'claimed')
            self.assertEqual(ledger.read_bytes(),original)

    def test_related_retirement_still_requires_exact_archive_and_preserves_source_job(self):
        from browser.shared_claim_recovery import recover_claims
        from browser.attempt_history import read_attempt
        item=self.card(target='t00');self.maintain()
        target=backlog.binding(self.catalog,*item[:2])['target_id']
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,*item[:2],target)
            db.execute("UPDATE web_card_jobs SET state='failed',error='original failure' WHERE paper_id=?",(item[2],))
        self.entries[target]['state']='retired_replaced'
        ledger=self.root/'web_cards'/item[2]/'chatgpt/attempt.json';ledger.parent.mkdir(parents=True)
        atomic_json(ledger,{'state':'not_sent','target_id':target,'send_click_started':False})
        original=ledger.read_bytes();record=read_attempt(ledger)
        folder=self.root/'shared-page-repairs/related';diagnostics=folder/'diagnostics';diagnostics.mkdir(parents=True)
        for name in ['health.json','body.txt','page.html','page.png']:(diagnostics/name).write_bytes(b'original diagnostic')
        (diagnostics/'ledger-before.json').write_bytes(original)
        atomic_json(folder/'journal.json',{'state':'ready','old_target_id':target,'health':{'replace_allowed':True},
            'archive_hashes':{p.name:digest(p) for p in diagnostics.iterdir()},'record':record})
        health={'state':'checked','checked_at':100,'pages':{}}
        (diagnostics/'body.txt').write_bytes(b'changed diagnostic')
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'claimed')
        (diagnostics/'body.txt').write_bytes(b'original diagnostic')
        self.assertEqual(len(recover_claims(self.catalog,self.entries,health,at=100)),1)
        self.assertIsNone(backlog.binding(self.catalog,*item[:2]))
        self.assertEqual(ledger.read_bytes(),original)
        with self.catalog.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT state,error FROM web_card_jobs WHERE paper_id=?',(item[2],)).fetchone()),('failed','original failure'))



class ClaimRecoveryLockTests(unittest.TestCase):
    setUp=SharedPageBacklogTests.setUp
    paper=SharedPageBacklogTests.paper
    card=SharedPageBacklogTests.card
    maintain=SharedPageBacklogTests.maintain

    def _claimed(self, *, ended):
        item=self.card(target='t00');self.maintain()
        target=backlog.binding(self.catalog,*item[:2])['target_id']
        with self.catalog.connect() as db:
            backlog.mark_claimed(db,*item[:2],target)
            db.execute("UPDATE web_card_jobs SET state='failed',error='original failure' WHERE paper_id=?",(item[2],))
        ledger=self.root/'web_cards'/item[2]/'chatgpt/attempt.json';ledger.parent.mkdir(parents=True)
        atomic_json(ledger,{'state':'not_sent' if ended else 'submitted','target_id':target,'send_click_started':not ended})
        self.entries[target]['state']='ready' if ended else 'busy'
        health={'state':'checked','checked_at':100,'pages':{target:{
            'health':'healthy_blank' if ended else 'busy','evidence':{'checked_at':100}}}}
        return item,target,ledger,health

    def _short_connections(self):
        from contextlib import contextmanager
        connect=self.catalog.connect
        @contextmanager
        def bounded():
            with connect() as db:
                # Keep a red regression bounded; production previously waits20s.
                db.execute('PRAGMA busy_timeout=50')
                yield db
        return patch.object(self.catalog,'connect',bounded)

    def test_unknown_claim_does_not_acquire_writer_lock(self):
        import sqlite3
        from browser.shared_claim_recovery import recover_claims
        item,target,ledger,health=self._claimed(ended=False);original=ledger.read_bytes()
        writer=sqlite3.connect(self.catalog.path);self.addCleanup(writer.close)
        writer.execute('BEGIN IMMEDIATE')
        try:
            with self._short_connections():
                self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        finally:writer.rollback()
        self.assertEqual(health['claim_recovery']['state'],'no_candidates')
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'claimed')
        self.assertEqual(ledger.read_bytes(),original)

    def test_eligible_claim_defers_busy_writer_then_rechecks_original_evidence(self):
        import sqlite3
        from browser.shared_claim_recovery import recover_claims
        item,target,ledger,health=self._claimed(ended=True);original=ledger.read_bytes()
        writer=sqlite3.connect(self.catalog.path);self.addCleanup(writer.close)
        writer.execute('BEGIN IMMEDIATE');started=time.monotonic()
        try:
            with self._short_connections():
                self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        finally:writer.rollback()
        self.assertLess(time.monotonic()-started,1)
        self.assertEqual(health['claim_recovery']['state'],'deferred_database_busy')
        self.assertEqual(backlog.binding(self.catalog,*item[:2])['state'],'claimed')
        self.assertEqual(ledger.read_bytes(),original)
        self.assertEqual(len(recover_claims(self.catalog,self.entries,health,at=100)),1)
        self.assertIsNone(backlog.binding(self.catalog,*item[:2]))
        self.assertEqual(ledger.read_bytes(),original)
        with self.catalog.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT state,error FROM web_card_jobs WHERE paper_id=?',(item[2],)).fetchone()),('failed','original failure'))
