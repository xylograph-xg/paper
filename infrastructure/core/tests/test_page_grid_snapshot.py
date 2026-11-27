"""The compact grid reads actual target assignments without allocating jobs."""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from desktop_widget.page_grid import page_grid
from desktop_widget.snapshot import snapshot


class PageGridSnapshot(unittest.TestCase):
    def test_fresh_resident_blank_observation_does_not_need_pool_heartbeat(self):
        self.pool['observed_at']=self.at-100
        self.write(self.data/'gpt-window-pool.json',self.pool)
        self.write(self.data/'shared-page-health.json',{'checked_at':self.at,'pages':{'T01':{'health':'healthy_blank'}}})
        self.observer['pages'][0].update(window_observed=True,window_checked_at=self.at,
            window_id=7,state='idle',streaming=False,answers=0,url='https://chatgpt.com/')
        self.write(self.data/'web-page-observer.json',self.observer)
        value=page_grid(self.root,at=self.at,owner_live=True)
        cell=next(c for c in value['cells'] if c['column']==1 and c['row']==1)
        self.assertEqual(cell['status'],'idle')
        self.observer['pages'][0]['url']='https://chatgpt.com/c/local-chatgpt-unknown'
        self.write(self.data/'web-page-observer.json',self.observer)
        value=page_grid(self.root,at=self.at,owner_live=True)
        cell=next(c for c in value['cells'] if c['column']==1 and c['row']==1)
        self.assertNotEqual(cell['status'],'idle')

    def test_stale_health_cannot_prove_blank_page_reusable(self):
        self.pool['observed_at']=self.at-100
        self.write(self.data/'gpt-window-pool.json',self.pool)
        self.write(self.data/'shared-page-health.json',{'checked_at':self.at-100,
            'pages':{'T01':{'health':'healthy_blank'}}})
        self.observer['pages'][0].update(window_observed=True,window_checked_at=self.at,
            window_id=7,state='idle',streaming=False,answers=0,url='https://chatgpt.com/')
        self.write(self.data/'web-page-observer.json',self.observer)
        value=page_grid(self.root,at=self.at,owner_live=True)
        cell=next(c for c in value['cells'] if c['column']==1 and c['row']==1)
        self.assertNotEqual(cell['status'],'idle')

    def test_thirty_second_health_boundary_does_not_turn_blank_pages_orange(self):
        self.pool['observed_at']=self.at-100
        self.write(self.data/'gpt-window-pool.json',self.pool)
        self.write(self.data/'shared-page-health.json',{'checked_at':self.at-40,
            'pages':{'T01':{'health':'healthy_blank'}}})
        self.observer['pages'][0].update(window_observed=True,window_checked_at=self.at,
            window_id=7,state='idle',streaming=False,answers=0,url='https://chatgpt.com/')
        self.write(self.data/'web-page-observer.json',self.observer)
        result=page_grid(self.root,at=self.at,owner_live=True)
        cell=next(c for c in result['cells'] if c['column']==1 and c['row']==1)
        self.assertEqual(cell['status'],'idle')
        self.assertGreaterEqual(result['currentStatusCounts']['idle'],1)
        self.write(self.data/'shared-page-health.json',{'checked_at':self.at-61,
            'pages':{'T01':{'health':'healthy_blank'}}})
        result=page_grid(self.root,at=self.at,owner_live=True)
        cell=next(c for c in result['cells'] if c['column']==1 and c['row']==1)
        self.assertEqual(cell['status'],'unobserved')
        self.assertIn('已过期',cell['tooltip'])

    def test_current_owner_preparation_is_waiting_without_counting_as_generation(self):
        self.mixed_schema();self.mixed_queued('pending',claimed=True,state='preparing')
        folder=self.data/'web_cards'/'pending'
        with self.db() as db:db.execute("UPDATE web_card_jobs SET folder=?,state='preparing' WHERE paper_id=?",(str(folder),'pending'))
        self.service['token']='current-owner';self.write(self.data/'web-card-service.json',self.service)
        self.pool['windows']['T01'].update(state='busy',kind='cards',active_paper_id='pending')
        self.write(self.data/'gpt-window-pool.json',self.pool)
        self.write(folder/'chatgpt/attempt.json',{'state':'ready','send_click_started':False,'target_id':'T01',
            'owner_pid':self.pid,'owner_token':'current-owner'})
        self.observer['pages'][0].update(streaming=False)
        self.write(self.data/'web-page-observer.json',self.observer)
        value=page_grid(self.root,at=self.at,owner_live=True)
        cell=next(c for c in value['cells'] if c['column']==1 and c['row']==1)
        self.assertEqual(cell['status'],'awaiting')
        self.assertIn('尚未开始发送',cell['detail'])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name); self.data = self.root / 'data'; self.data.mkdir()
        (self.root / 'config').mkdir(); self.at = 1000.; self.pid = os.getpid()
        self.config = {'catalog_path': str(self.data / 'catalog.sqlite3'),
                       'web_cards': {'enabled': True, 'shared_window': {'enabled': True}}}
        self.write(self.root / 'config/first_round.json', self.config)
        self.slots = [{'slot_id': f'{column:02d}', 'target_id': f'T{column:02d}', 'state': 'present'} for column in range(1, 21)]
        self.registry = {'schema_version': 1, 'window_id': 7, 'slots': self.slots}
        self.status = {**self.registry, 'updated': self.at, 'owner_pid': self.pid}
        self.service = {'pid': self.pid, 'state': 'running', 'updated': self.at}
        self.pool = {'observed_at': self.at, 'shared_window_id': 7,
                     'windows': {slot['target_id']: {'state': 'ready_blank'} for slot in self.slots}}
        self.observer = {'updated': self.at, 'owner_pid': self.pid, 'activity_schema_version': 1,
                         'pages': [{'target_id': slot['target_id'], 'checked_at': self.at,
                                    'url': 'https://chatgpt.com/', 'state': 'idle', 'streaming': False} for slot in self.slots]}
        self.persist()
        with self.db() as db:
            db.executescript('''CREATE TABLE web_card_jobs(paper_id TEXT PRIMARY KEY,title TEXT,state TEXT,selection TEXT,folder TEXT);
                CREATE TABLE web_page_queue(paper_id TEXT PRIMARY KEY,target_id TEXT,state TEXT,assigned REAL);
                CREATE TABLE card_review_jobs(id TEXT PRIMARY KEY,paper_id TEXT,title TEXT,state TEXT,folder TEXT);
                CREATE TABLE card_correction_jobs(id TEXT PRIMARY KEY,paper_id TEXT,title TEXT,state TEXT,kind TEXT);''')

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.data / 'catalog.sqlite3')) as db:
            with db:
                yield db

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    def persist(self):
        for name, value in [('shared-gpt-window.json', self.registry), ('shared-gpt-window-status.json', self.status),
                            ('web-card-service.json', self.service), ('gpt-window-pool.json', self.pool),
                            ('web-page-observer.json', self.observer)]:
            self.write(self.data / name, value)

    def grid(self, **kwargs):
        return page_grid(self.root, at=self.at, owner_live=kwargs.get('owner_live', True))

    def cell(self, column=1, row=1, **kwargs):
        return next(cell for cell in self.grid(**kwargs)['cells'] if cell['column'] == column and cell['row'] == row)

    def queued(self, paper_id='p1', target='T01', state='ready', assigned=1., job_state='queued', selection=None):
        folder = self.data / 'web_cards' / paper_id
        with self.db() as db:
            db.execute('INSERT INTO web_card_jobs VALUES(?,?,?,?,?)', (paper_id, 'Article ' + paper_id, job_state, json.dumps(selection or {}), str(folder)))
            db.execute('INSERT INTO web_page_queue VALUES(?,?,?,?)', (paper_id, target, state, assigned))
        return folder

    def mixed_schema(self, *, enabled=1):
        self.config.update(card_review={'enabled': True}, card_correction={'enabled': True})
        self.write(self.root / 'config/first_round.json', self.config)
        with self.db() as db:
            db.executescript('''CREATE TABLE shared_page_backlog(
                lane TEXT,job_id TEXT,paper_id TEXT,target_id TEXT,assigned REAL,state TEXT,
                PRIMARY KEY(lane,job_id));
                CREATE TABLE shared_workflow_arrivals(sequence INTEGER PRIMARY KEY,lane TEXT,
                job_id TEXT,queued_at REAL,basis TEXT,UNIQUE(lane,job_id));
                CREATE TABLE shared_page_backlog_meta(id INTEGER PRIMARY KEY,enabled INTEGER,
                last_reconciled REAL,low_watermark INTEGER,target_tasks INTEGER,queue_depth INTEGER,
                triggered INTEGER,total_tasks INTEGER,queued_tasks INTEGER,current_tasks INTEGER,
                eligible_pages INTEGER,reserved_targets TEXT,status TEXT,paused_queued_count INTEGER);''')
            db.execute('INSERT INTO shared_page_backlog_meta VALUES(1,?,1000,70,100,4,1,0,0,0,20,?,\'ready\',0)',
                       (enabled, json.dumps([slot['target_id'] for slot in self.slots[:8]])))

    def mixed_queued(self, job_id, *, lane='cards', paper_id=None, target='T01',
                     state='ready', assigned=1., queued_at=1., sequence=1, claimed=False):
        paper_id = paper_id or job_id
        if lane == 'review':
            with self.db() as db:
                db.execute('INSERT INTO card_review_jobs VALUES(?,?,?,?,?)',
                           (job_id, paper_id, 'Review ' + job_id, state, '/review/' + job_id))
        elif lane == 'correction':
            self.queued(paper_id, target, state, assigned, selection={'rework': {'kind': 'source_review', 'correction_id': job_id}})
            with self.db() as db:
                db.execute('INSERT INTO card_correction_jobs VALUES(?,?,?,?,?)',
                           (job_id, paper_id, 'Correction ' + job_id, 'ready', 'source_rework'))
        else:
            self.queued(paper_id, target, state, assigned)
        with self.db() as db:
            db.execute('INSERT INTO shared_page_backlog VALUES(?,?,?,?,?,?)',
                       (lane, job_id, paper_id, target, assigned, 'claimed' if claimed else 'queued'))
            db.execute('INSERT INTO shared_workflow_arrivals VALUES(?,?,?,?,?)',
                       (sequence, lane, job_id, queued_at, 'enqueue'))

    def running(self, lane='cards', column=1):
        tid = f'T{column:02d}'; url = f'https://chatgpt.com/c/session-{column}'
        folder = self.queued(job_state='submitted', target=tid)
        entry = self.pool['windows'][tid]; entry.update(state='busy', kind=lane, active_paper_id='p1')
        if lane == 'review':
            folder = self.data / 'card_reviews/p1/review1'; entry['review_id'] = 'review1'
            with self.db() as db:
                db.execute('INSERT INTO card_review_jobs VALUES(?,?,?,?,?)', ('review1', 'p1', 'Reviewed article', 'submitted', str(folder)))
        ledger = folder / ('attempt.json' if lane == 'review' else 'chatgpt/attempt.json')
        self.write(ledger, {'target_id': tid, 'conversation_url': url, 'actual_prompt_sha256': 'bound', 'review_id': entry.get('review_id')})
        self.observer['pages'][column - 1].update(activity_verified=True, kind=lane, streaming=True, state='generating', url=url)
        self.persist()

    def direct_position(self, column=1, *, window=7, observed=True, stamp=None):
        self.observer['window_schema_version'] = 1
        self.observer['pages'][column - 1].update(window_observed=observed, window_id=window,
                                                window_checked_at=self.at if stamp is None else stamp)
        self.persist()

    def test_dispatch_blocked_ready_page_is_protected_instead_of_idle(self):
        self.status['dispatch'] = {'protected_targets': ['T01']}
        self.persist()
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertIn('后台派发检查', self.cell()['tooltip'])
        self.assertEqual(self.cell(column=2)['status'], 'idle')

    def test_other_owner_dispatch_cannot_relabel_current_page(self):
        self.status.update(owner_pid=self.pid + 1, dispatch={'protected_targets': ['T01']})
        self.direct_position()
        self.assertEqual(self.cell()['status'], 'idle')

    def test_owner_backlog_keeps_protection_while_window_inventory_refreshes(self):
        self.service.update(shared_window_id=7, shared_backlog={'protected_targets': ['T01']})
        self.persist()
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertEqual(self.cell(column=2)['status'], 'idle')

    def test_other_window_backlog_cannot_relabel_current_page(self):
        self.service.update(shared_window_id=8, shared_backlog={'protected_targets': ['T01']})
        self.persist()
        self.assertEqual(self.cell()['status'], 'idle')

    def test_protected_dispatch_does_not_hide_verified_running_session(self):
        self.running()
        self.status['dispatch'] = {'protected_targets': ['T01']}
        self.persist()
        self.assertEqual(self.cell()['status'], 'running')

    def test_exact_20_columns_5_rows_and_stable_row_major_order(self):
        grid = self.grid()
        self.assertEqual((grid['columns'], grid['rows'], len(grid['cells'])), (20, 5, 100))
        self.assertEqual([(cell['column'], cell['row']) for cell in grid['cells']], [(column, row) for row in range(1, 6) for column in range(1, 21)])
        self.assertEqual(self.cell()['status'], 'idle')
        self.assertEqual(self.cell(row=2)['status'], 'empty')

    def test_disabled_shared_window_has_no_grid(self):
        self.config['web_cards']['shared_window']['enabled'] = False
        self.write(self.root / 'config/first_round.json', self.config)
        self.assertIsNone(self.grid())

    def test_current_lane_uses_verified_generating_observation_and_bound_title(self):
        for lane in ('cards', 'review', 'correction'):
            with self.subTest(lane=lane):
                with self.db() as db:
                    for table in ('web_card_jobs', 'web_page_queue', 'card_review_jobs'):
                        db.execute('DELETE FROM ' + table)
                self.running(lane)
                cell = self.cell()
                self.assertEqual(cell['status'], 'running'); self.assertEqual(cell['lane'], lane)
                self.assertIn('article' if lane == 'review' else 'Article', cell['title'])
                self.assertIs(cell['observed'], True)

    def test_wrong_original_ledger_does_not_attach_previous_article_title(self):
        self.running()
        self.write(self.data / 'web_cards/p1/chatgpt/attempt.json', {'target_id': 'OLD', 'conversation_url': 'https://chatgpt.com/c/other', 'actual_prompt_sha256': 'bound'})
        self.assertEqual(self.cell()['title'], '')

    def test_stale_busy_is_unobserved_not_running(self):
        self.running(); self.observer['updated'] = self.at - 31; self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved'); self.assertIsNone(self.cell()['lane'])

    def test_fresh_direct_window_and_material_observation_survive_long_upload(self):
        self.running()
        self.status['updated'] = self.at - 120
        self.pool['observed_at'] = self.at - 120
        self.service['updated'] = self.at - 120
        self.direct_position()
        self.assertEqual(self.cell()['status'], 'running')
        self.assertEqual(self.cell()['lane'], 'cards')
        self.assertIs(self.cell()['observed'], True)

    def test_failed_direct_position_is_single_page_unobserved_without_old_fallback(self):
        self.running()
        self.direct_position(observed=False, window=None)
        self.observer['pages'][0]['window_error'] = '位置核对超时'
        self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved')
        self.assertIn('位置核对超时', self.cell()['tooltip'])
        self.assertEqual(self.cell(column=2)['status'], 'idle')

    def test_stale_or_invalid_new_position_cannot_fall_back_to_fresh_old_present(self):
        self.running()
        for kwargs in [{'stamp': self.at - 31}, {'window': None}, {'window': True}, {'observed': 'true'}]:
            with self.subTest(kwargs=kwargs):
                self.direct_position(**kwargs)
                self.assertEqual(self.cell()['status'], 'unobserved')

    def test_direct_position_still_requires_fresh_matching_owner_and_dom(self):
        self.running(); self.direct_position()
        self.observer['owner_pid'] = self.pid + 1; self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved')
        self.observer['owner_pid'] = self.pid
        self.observer['pages'][0]['checked_at'] = self.at - 31; self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved')
        self.observer['pages'][0]['checked_at'] = self.at
        self.observer['updated'] = self.at - 31; self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved')

    def test_new_position_does_not_turn_unknown_material_into_running(self):
        self.running(); self.direct_position()
        self.observer['pages'][0]['activity_verified'] = False; self.persist()
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertIsNone(self.cell()['lane'])

    def test_fresh_outside_position_protects_page_and_hides_its_queue(self):
        self.running(); self.queued('next'); self.direct_position(window=99)
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertIsNone(self.cell()['lane'])
        self.assertEqual(self.cell(row=2)['status'], 'empty')

    def test_fresh_direct_position_shows_true_assignment_despite_stale_pool(self):
        self.queued(); self.pool['observed_at'] = self.at - 120
        self.status['updated'] = self.at - 120; self.direct_position()
        self.assertEqual(self.cell(row=2)['status'], 'queued')
        self.assertIs(self.cell(row=2)['observed'], True)
        # Position proves where the page is, not that its old composer is empty.
        self.assertNotEqual(self.cell()['status'], 'idle')

    def test_window_only_observation_never_claims_dom_activity(self):
        self.queued()
        self.observer['pages'][0] = {'target_id': 'T01', 'state': 'not_observed'}
        self.direct_position()
        self.assertEqual(self.cell()['status'], 'unobserved')
        self.assertEqual(self.cell(row=2)['status'], 'queued')
        self.assertIs(self.cell(row=2)['observed'], True)

    def test_each_stale_or_mismatched_evidence_blocks_live_color(self):
        self.running()
        for source, field, value in [(self.pool, 'observed_at', self.at - 31), (self.status, 'updated', self.at - 31),
                                     (self.status, 'owner_pid', self.pid + 1), (self.observer, 'owner_pid', self.pid + 1),
                                     (self.status, 'window_id', 99), (self.service, 'state', 'stopped')]:
            with self.subTest(field=field, value=value):
                previous = source[field]; source[field] = value; self.persist()
                self.assertEqual(self.cell()['status'], 'unobserved')
                source[field] = previous; self.persist()
        self.assertEqual(self.cell(owner_live=False)['status'], 'unobserved')

    def test_duplicate_target_observation_never_claims_running(self):
        self.running(); self.observer['pages'].append(dict(self.observer['pages'][0])); self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved')

    def test_unverified_stream_or_page_error_is_protected(self):
        self.observer['pages'][0].update(streaming=True, state='generating'); self.persist()
        self.assertEqual(self.cell()['status'], 'protected')
        self.observer['pages'][0].update(streaming=False, state='inspection_error', error='verification needed'); self.persist()
        self.assertIn('verification needed', self.cell()['tooltip'])

    def test_protected_entry_and_completed_uncollected_receipt_are_distinct(self):
        self.running(); self.observer['pages'][0].update(streaming=False, complete=True, state='complete')
        self.pool['windows']['T01']['state'] = 'needs_inspection'; self.persist()
        self.assertEqual(self.cell()['status'], 'protected')
        self.pool['windows']['T01']['state'] = 'busy'; self.persist()
        self.assertEqual(self.cell()['status'], 'awaiting')
        self.assertEqual(self.cell()['lane'], 'cards')

    def test_queue_rows_use_stored_target_and_assignment_order_only(self):
        self.queued('late', assigned=9.); self.queued('early', assigned=2., state='waiting')
        self.queued('other-page', target='T02', state='preparing')
        self.assertEqual(self.cell(row=2)['title'], 'Article early')
        self.assertEqual(self.cell(row=3)['title'], 'Article late')
        self.assertEqual(self.cell(column=2, row=2)['title'], 'Article other-page')
        self.assertEqual(self.cell(row=4)['status'], 'empty')

    def test_more_than_four_assigned_items_are_reported_without_extra_cells(self):
        for index in range(6):
            self.queued('p' + str(index), assigned=float(index))
        self.assertEqual(self.cell(row=5)['title'], 'Article p3')
        self.assertIn('另有 2 项', self.cell(row=5)['tooltip'])
        self.assertEqual(len(self.grid()['cells']), 100)

    def test_pause_preserves_original_generation_and_control_records(self):
        self.running()
        control = self.data / 'web-card-control.json'
        self.write(control, {'paused_by_user': True, 'reason': 'pause'})
        before = control.read_bytes()
        self.assertEqual(self.cell()['status'], 'running')
        self.assertEqual(control.read_bytes(), before)

    def test_no_queue_invented_for_unassigned_review_or_stale_history(self):
        self.queued('done', job_state='completed'); self.queued('submitted', job_state='submitted')
        self.queued('failed-material', state='failed'); self.queued('foreign', target='FOREIGN')
        with self.db() as db:
            db.execute('INSERT INTO card_review_jobs VALUES(?,?,?,?,?)', ('global-review', 'p', 'Not page assigned', 'ready', '/temp'))
        self.assertTrue(all(cell['status'] == 'empty' for cell in self.grid()['cells'] if cell['row'] > 1))

    def test_correction_requires_matching_independent_queue_binding(self):
        self.queued('corr', selection={'rework': {'kind': 'source_review', 'correction_id': 'c'}})
        self.assertEqual(self.cell(row=2)['status'], 'empty')
        with self.db() as db:
            db.execute('INSERT INTO card_correction_jobs VALUES(?,?,?,?,?)', ('c', 'corr', 'Correction', 'ready', 'source_rework'))
        self.assertEqual(self.cell(row=2)['lane'], 'correction')
        with self.db() as db:
            db.execute("UPDATE card_correction_jobs SET state='needs_user'")
        self.assertEqual(self.cell(row=2)['status'], 'empty')

    def test_mixed_same_page_queues_sort_by_immutable_arrival_and_sequence(self):
        self.mixed_schema()
        self.mixed_queued('card', assigned=0, queued_at=8, sequence=3)
        self.mixed_queued('review', lane='review', assigned=99, queued_at=3, sequence=2)
        self.mixed_queued('correction', lane='correction', paper_id='rework', assigned=100, queued_at=3, sequence=1)
        self.assertEqual([self.cell(row=row)['lane'] for row in range(2, 5)], ['correction', 'review', 'cards'])
        self.assertEqual([self.cell(row=row)['title'] for row in range(2, 5)], ['Correction correction', 'Review review', 'Article card'])
        self.assertEqual([self.cell(row=row)['arrivalSequence'] for row in range(2, 5)], [1, 2, 3])
        self.assertIn('低于 70 项时', self.grid()['legend'])
        self.assertIn('最多 100 项', self.grid()['legend'])

    def test_canonical_empty_table_never_falls_back_to_legacy_card_assignments(self):
        self.queued('old')
        self.mixed_schema()
        self.assertTrue(all(cell['status'] == 'empty' for cell in self.grid()['cells'][20:]))

    def test_canonical_assignments_do_not_double_count_their_legacy_mirror(self):
        self.mixed_schema()
        self.mixed_queued('same')
        grid = self.grid()
        self.assertEqual(sum(cell['status'] == 'queued' for cell in grid['cells']), 1)
        self.assertEqual(grid['backlog']['queuedTasks'], 1)
        self.assertEqual(grid['backlog']['authorizedDueQueuedTasks'], 1)

    def test_disabled_canonical_uses_old_assignment_display(self):
        self.mixed_schema(enabled=0)
        self.queued('legacy')
        self.assertEqual(self.cell(row=2)['title'], 'Article legacy')
        self.assertNotIn('arrivalSequence', self.cell(row=2))

    def test_safe_material_migration_moves_column_without_changing_fifo(self):
        self.mixed_schema()
        self.mixed_queued('card', target='T01', queued_at=7, sequence=1)
        self.mixed_queued('review', lane='review', target='T02', queued_at=9, sequence=2)
        self.assertEqual(self.cell(column=1, row=2)['title'], 'Article card')
        with self.db() as db:
            db.execute("UPDATE shared_page_backlog SET target_id='T02',assigned=9999 WHERE job_id='card'")
            db.execute("UPDATE web_page_queue SET target_id='T02' WHERE paper_id='card'")
        self.assertEqual(self.cell(column=1, row=2)['status'], 'empty')
        self.assertEqual(self.cell(column=2, row=2)['title'], 'Article card')
        self.assertEqual(self.cell(column=2, row=3)['title'], 'Review review')
        self.assertEqual(self.cell(column=2, row=2)['queuedAt'], 7)

    def test_claimed_canonical_item_is_not_a_queued_task_or_legacy_fallback(self):
        self.mixed_schema()
        self.mixed_queued('claimed', claimed=True)
        self.mixed_queued('review-claimed', lane='review', sequence=2, claimed=True)
        self.assertEqual(self.grid()['backlog']['queuedTasks'], 0)
        self.assertTrue(all(cell['status'] == 'empty' for cell in self.grid()['cells'][20:]))

    def test_claimed_original_target_cannot_borrow_idle_pool_state(self):
        self.mixed_schema()
        self.mixed_queued('unknown', claimed=True)
        cell = self.cell()
        self.assertEqual(cell['status'], 'protected')
        self.assertIsNone(cell['lane'])
        self.assertIn('已有领取记录', cell['tooltip'])
        self.assertEqual(self.grid()['backlog']['currentTasks'], 0)

    def claimed_running(self, lane='cards', *, mismatch=False):
        self.running(lane)
        self.mixed_schema()
        job_id = 'review1' if lane == 'review' else 'p1'
        path = self.data / ('card_reviews/p1/review1/attempt.json' if lane == 'review' else 'web_cards/p1/chatgpt/attempt.json')
        attempt = json.loads(path.read_text()); attempt['state'] = 'submitted'; self.write(path, attempt)
        with self.db() as db:
            db.execute('INSERT INTO shared_page_backlog VALUES(?,?,?,?,?,?)',
                       (lane, 'other-job' if mismatch else job_id, 'p1', 'T01', 1., 'claimed'))
        return path

    def test_fresh_exact_claimed_card_generation_remains_running(self):
        self.claimed_running('cards')
        self.assertEqual(self.cell()['status'], 'running')
        self.assertEqual(self.cell()['lane'], 'cards')
        self.assertEqual(self.grid()['backlog']['currentTasks'], 1)

    def test_fresh_exact_claimed_review_generation_remains_running(self):
        self.claimed_running('review')
        self.assertEqual(self.cell()['status'], 'running')
        self.assertEqual(self.cell()['lane'], 'review')
        self.assertEqual(self.grid()['backlog']['currentTasks'], 1)

    def test_claimed_mismatched_original_identity_is_protected_despite_verified_stream(self):
        self.claimed_running(mismatch=True)
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertIsNone(self.cell()['lane'])
        self.assertEqual(self.grid()['backlog']['currentTasks'], 0)

    def test_stale_claim_observation_is_gray_and_is_not_an_awaiting_task(self):
        self.claimed_running()
        self.observer['updated'] = self.at - 31; self.persist()
        self.assertEqual(self.cell()['status'], 'unobserved')
        self.assertEqual(self.grid()['backlog']['currentTasks'], 0)

    def test_saved_but_unreleased_claim_requires_exact_complete_original_evidence(self):
        self.claimed_running()
        self.pool['windows']['T01']['state'] = 'ready'
        self.observer['pages'][0].update(streaming=False, complete=True, answers=1)
        self.persist()
        self.assertEqual(self.cell()['status'], 'awaiting')
        self.assertEqual(self.cell()['lane'], 'cards')
        self.observer['pages'][0]['answers'] = 0; self.persist()
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertEqual(self.grid()['backlog']['currentTasks'], 0)

    def test_pending_states_use_real_preparation_status_for_each_type(self):
        self.mixed_schema()
        self.mixed_queued('card', state='preparing', sequence=1)
        self.mixed_queued('review', lane='review', state='queued', sequence=2)
        self.mixed_queued('correction', lane='correction', state='waiting', sequence=3)
        self.assertIn('准备材料', self.cell(row=2)['detail'])
        self.assertIn('等待准备', self.cell(row=3)['detail'])
        self.assertIn('等待准备', self.cell(row=4)['detail'])

    def test_terminal_or_claimed_source_states_cannot_remain_queue_colors(self):
        self.mixed_schema()
        self.mixed_queued('card', sequence=1)
        self.mixed_queued('review', lane='review', sequence=2)
        self.mixed_queued('correction', lane='correction', sequence=3)
        with self.db() as db:
            db.execute("UPDATE web_card_jobs SET state='preparing' WHERE paper_id='card'")
            db.execute("UPDATE card_review_jobs SET state='submitted' WHERE id='review'")
            db.execute("UPDATE card_correction_jobs SET state='needs_user' WHERE id='correction'")
        self.assertEqual(self.grid()['backlog']['queuedTasks'], 0)

    def test_correction_requires_exact_canonical_id_and_source_rework_kind(self):
        self.mixed_schema()
        self.mixed_queued('correction', lane='correction')
        with self.db() as db:
            db.execute("UPDATE web_card_jobs SET selection=?", (json.dumps({'rework': {'correction_id': 'other'}}),))
        self.assertEqual(self.cell(row=2)['status'], 'empty')
        with self.db() as db:
            db.execute("UPDATE web_card_jobs SET selection=?", (json.dumps({'rework': {'correction_id': 'correction'}}),))
            db.execute("UPDATE card_correction_jobs SET kind='formatting'")
        self.assertEqual(self.cell(row=2)['status'], 'empty')

    def test_unmatched_paper_or_transport_target_does_not_show_bound_queue(self):
        self.mixed_schema()
        self.mixed_queued('card', sequence=1)
        self.mixed_queued('review', lane='review', sequence=2)
        with self.db() as db:
            db.execute("UPDATE web_page_queue SET target_id='OLD' WHERE paper_id='card'")
            db.execute("UPDATE card_review_jobs SET paper_id='other' WHERE id='review'")
        self.assertEqual(self.grid()['backlog']['queuedTasks'], 0)

    def test_paused_material_remains_visible_but_does_not_fill_runnable_inventory(self):
        self.mixed_schema()
        self.mixed_queued('card', sequence=1)
        self.mixed_queued('review', lane='review', sequence=2)
        self.write(self.data / 'card-review-control.json', {'paused_by_user': True, 'reason': '用户暂停'})
        cell = self.cell(row=3)
        self.assertEqual(cell['lane'], 'review')
        self.assertEqual(cell['status'], 'queued')
        self.assertIn('该类型已暂停，保留材料/原归属', cell['tooltip'])
        self.assertIs(cell['runnable'], False)
        self.assertEqual(self.grid()['backlog']['queuedTasks'], 2)
        self.assertEqual(self.grid()['backlog']['authorizedDueQueuedTasks'], 1)
        self.assertEqual(self.grid()['backlog']['pausedQueuedTasks'], 1)

    def test_incomplete_or_corrupt_canonical_metadata_is_gray_without_fallback(self):
        self.mixed_schema()
        self.queued('old')
        with self.db() as db:
            db.execute('UPDATE shared_page_backlog_meta SET queue_depth=20')
        grid = self.grid()
        self.assertTrue(all(cell['status'] == 'unobserved' for cell in grid['cells'][20:]))
        self.assertIn('共享排队登记待核对', grid['legend'])
        with self.db() as db:
            db.execute('DROP TABLE shared_page_backlog_meta')
        self.assertTrue(all(cell['status'] == 'unobserved' for cell in self.grid()['cells'][20:]))

    def test_missing_arrival_evidence_never_invents_fifo_from_assignment_time(self):
        self.mixed_schema()
        self.mixed_queued('no-arrival')
        with self.db() as db:
            db.execute('DELETE FROM shared_workflow_arrivals')
        self.assertEqual(self.cell(row=2)['status'], 'unobserved')
        self.assertIn('顺序待核对', self.cell(row=2)['detail'])

    def test_corrupt_material_selection_never_defaults_to_a_card_queue(self):
        self.mixed_schema()
        self.mixed_queued('damaged')
        with self.db() as db:
            db.execute("UPDATE web_card_jobs SET selection='{'")
        self.assertEqual(self.cell(row=2)['status'], 'unobserved')

    def test_canonical_more_than_four_never_adds_cells_or_claims_extra_capacity(self):
        self.mixed_schema()
        for index in range(5):
            self.mixed_queued(str(index), sequence=index + 1)
        grid = self.grid()
        self.assertEqual(len(grid['cells']), 100)
        self.assertEqual(sum(cell['status'] == 'queued' for cell in grid['cells']), 4)
        self.assertEqual(grid['backlog']['queuedTasks'], 4)

    def test_moved_page_hides_canonical_mixed_queue_without_editing_binding(self):
        self.mixed_schema()
        self.mixed_queued('review', lane='review')
        before = (self.data / 'catalog.sqlite3').read_bytes()
        self.direct_position(window=99)
        self.assertEqual(self.cell()['status'], 'protected')
        self.assertEqual(self.cell(row=2)['status'], 'empty')
        self.assertEqual((self.data / 'catalog.sqlite3').read_bytes(), before)

    def test_zero_material_or_pages_does_not_color_empty_grid_to_seventy(self):
        self.mixed_schema()
        self.assertEqual(self.grid()['backlog']['queuedTasks'], 0)
        self.assertEqual(self.grid()['backlog']['currentTasks'], 0)
        self.assertTrue(all(cell['status'] == 'empty' for cell in self.grid()['cells'][20:]))

    def test_shortfall_legend_keeps_actual_counts_and_no_fabricated_one_hundred(self):
        self.mixed_schema()
        self.mixed_queued('review', lane='review')
        with self.db() as db:
            db.execute("UPDATE shared_page_backlog_meta SET status='shortfall',total_tasks=1,queued_tasks=1")
        grid = self.grid()
        self.assertIn('库存或可用网页不足', grid['legend'])
        self.assertEqual(grid['backlog']['queuedTasks'], 1)

    def test_owner_safe_inventory_counts_are_used_only_when_fresh(self):
        self.mixed_schema()
        self.mixed_queued('card')
        with self.db() as db:
            db.execute('UPDATE shared_page_backlog_meta SET total_tasks=4,current_tasks=3,queued_tasks=1')
        grid = self.grid()
        self.assertEqual(grid['backlog']['inventoryTasks'], 4)
        self.assertEqual(grid['backlog']['inventoryCurrentTasks'], 3)
        self.assertEqual(grid['backlog']['inventoryQueuedTasks'], 1)
        self.assertIn('最近调度核对的可调度库存 4 项', grid['legend'])
        # The owner's stock observation never turns a blank page into a current job.
        self.assertEqual(grid['backlog']['currentTasks'], 0)
        self.assertTrue(all(cell['status'] == 'idle' for cell in grid['cells'][:20]))
        with self.db() as db:
            db.execute('UPDATE shared_page_backlog_meta SET last_reconciled=969')
        grid = self.grid()
        self.assertIs(grid['backlog']['inventoryConfirmed'], False)
        self.assertIsNone(grid['backlog']['inventoryTasks'])
        self.assertIn('库存待后台所有者新鲜核对', grid['legend'])
        self.assertEqual(self.cell(row=2)['status'], 'queued')

    def test_stopped_owner_or_invalid_inventory_cannot_claim_current_stock(self):
        self.mixed_schema()
        self.assertIsNone(self.grid(owner_live=False)['backlog']['inventoryTasks'])
        with self.db() as db:
            db.execute('UPDATE shared_page_backlog_meta SET total_tasks=100,current_tasks=0,queued_tasks=0')
        self.assertEqual(self.cell(row=2)['status'], 'unobserved')
        self.assertIsNone(self.grid()['backlog']['inventoryTasks'])

    def test_canonical_grid_read_never_installs_or_mutates_schema_files_controls(self):
        self.mixed_schema()
        self.mixed_queued('review', lane='review')
        self.write(self.data / 'card-review-control.json', {'paused_by_user': True})
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with patch('core.catalog.Catalog', side_effect=AssertionError('display must stay read only')):
            self.assertEqual(self.cell(row=2)['title'], 'Review review')
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)

    def test_outside_slot_keeps_protection_without_queue_or_active_color(self):
        self.running(); self.status['slots'] = [dict(slot) for slot in self.slots]
        self.status['slots'][0]['state'] = 'outside_window'; self.persist()
        self.assertEqual(self.cell()['status'], 'protected'); self.assertIsNone(self.cell()['lane'])
        self.assertEqual(self.cell(row=2)['status'], 'empty')

    def test_corrupt_registration_does_not_repair_it_or_adopt_foreign_targets(self):
        self.registry['slots'][1]['target_id'] = 'T01'; self.persist()
        self.queued()
        grid = self.grid()
        self.assertEqual(len(grid['cells']), 100)
        self.assertTrue(all(cell['status'] == 'unobserved' for cell in grid['cells'][:20]))
        self.assertTrue(all(cell['status'] == 'empty' for cell in grid['cells'][20:]))

    def test_missing_catalog_is_not_created(self):
        (self.data / 'catalog.sqlite3').unlink()
        self.assertEqual(self.cell(row=2)['status'], 'empty')
        self.assertFalse((self.data / 'catalog.sqlite3').exists())

    def test_snapshot_is_read_only_and_serializes_optional_grid(self):
        self.queued(); before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        progress = {'downloaded': 0, 'total': 0, 'active_fetch': 0, 'pending': 0, 'blocked': 0, 'cards': 0, 'last_card_completed': None}
        with patch('core.continuous_status.status', return_value=progress):
            value = snapshot(self.root)
        self.assertEqual(len(value['pageGrid']['cells']), 100)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)


if __name__ == '__main__':
    unittest.main()
