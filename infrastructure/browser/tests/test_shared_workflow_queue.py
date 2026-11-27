"""Three independent lanes using real temporary Catalog transactions only."""
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog, now
from correction import card_correction_queue as correction
from review import card_review_queue as review
from browser import shared_workflow_queue as shared
from cards import web_card_queue as cards
from browser import web_page_queue as materials
from core.services import atomic_json


class SharedWorkflowQueue(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path': str(self.catalog.path),
            'studio_library_root': str(self.root/'library'),
            'web_cards': {'enabled': True, 'shared_window': {'enabled': True},
                          'max_parallel_jobs': 20, 'min_reserved_pages': 8},
            'card_review': {'enabled': True, 'parallel_jobs': 4},
            'card_correction': {'enabled': True, 'parallel_jobs': 4}}
        cards.install(self.catalog)
        review.install(self.catalog)
        correction.install(self.catalog)
        materials.install(self.catalog)

    def paper(self, name):
        return self.catalog.upsert({'title': name, 'doi': '10.9999/' + name})

    def card_job(self, name='card', *, paper_id=None, state='queued',
                 material_state='ready', selection=None, retry_at=0):
        pid = paper_id or self.paper(name)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs '
                '(paper_id,source_sha256,title,selection,state,updated,retry_at) VALUES(?,?,?,?,?,?,?)',
                (pid, 'source-sha', name, json.dumps(selection or {}), state, now(), retry_at))
            if material_state is not None:
                db.execute('INSERT INTO web_page_queue(paper_id,target_id,state,assigned) VALUES(?,?,?,?)',
                    (pid, 'original-target', material_state, time.time()))
        return pid

    def review_job(self, name='review', *, paper_id=None, state='ready'):
        pid = paper_id or self.paper(name)
        jid = 'review-' + pid
        folder = self.root/'reviews'/jid
        with self.catalog.connect() as db:
            db.execute('INSERT INTO card_review_jobs '
                '(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) VALUES(?,?,?,?,?,?,?,?)',
                (jid, pid, 'card-sha', 'source-sha', name, state, str(folder), now()))
        return next(job for job in review.rows(self.catalog) if job['id'] == jid)

    def correction_job(self, name='correction', *, state='ready', kind='source_rework'):
        ref = self.review_job(name, state='rework_queued')
        job = correction._enqueue(self.catalog, ref, kind, {'synthetic_test': True}, state=state)
        self.card_job(name, paper_id=ref['paper_id'], selection={'rework': {
            'kind': 'source_review', 'review_id': ref['id'], 'old_sha256':ref['card_sha256'], 'correction_id': job['id']}})
        return job

    def arrival(self, lane, job_id):
        with self.catalog.connect() as db:
            row = db.execute('SELECT * FROM shared_workflow_arrivals WHERE lane=? AND job_id=?',
                             (lane, job_id)).fetchone()
        return dict(row) if row is not None else None

    def transport(self, paper_id):
        with self.catalog.connect() as db:
            return dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (paper_id,)).fetchone())

    def material(self, paper_id):
        with self.catalog.connect() as db:
            return dict(db.execute('SELECT * FROM web_page_queue WHERE paper_id=?', (paper_id,)).fetchone())

    def claim(self, paper_id, *, lane='cards', job_id=None, target='new-target'):
        return shared.claim_ready(self.catalog, self.config, lane=lane,
            job_id=job_id or paper_id, paper_id=paper_id, target_id=target)

    def test_new_enqueues_have_one_global_arrival_sequence(self):
        pid = self.card_job()
        rjob = self.review_job()
        cjob = self.correction_job()
        evidence = [self.arrival('cards', pid), self.arrival('review', rjob['id']),
                    self.arrival('correction', cjob['id'])]
        self.assertTrue(all(record['basis'] == 'enqueue' for record in evidence))
        self.assertEqual([record['sequence'] for record in evidence],
                         sorted(record['sequence'] for record in evidence))
        self.assertEqual(len({record['sequence'] for record in evidence}), 3)
        self.assertTrue(all(isinstance(record['queued_at'], float) for record in evidence))

    def test_state_updates_and_repeated_install_preserve_arrival_evidence(self):
        pid = self.card_job()
        before = self.arrival('cards', pid)
        cards.update(self.catalog, pid, state='preparing', error='local preparation')
        shared.install(self.catalog)
        shared.register(self.catalog, 'cards', pid)
        self.assertEqual(self.arrival('cards', pid), before)

    def test_legacy_registration_is_explicit_and_does_not_use_mutable_update_time(self):
        pid = self.paper('legacy')
        with self.catalog.connect() as db:
            db.execute('DROP TRIGGER arrival_web_card_jobs_insert')
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',
                       (pid, 'source', 'legacy', '{}', '2000-01-01T00:00:00+00:00'))
        self.assertIsNone(self.arrival('cards', pid))
        with patch('browser.shared_workflow_queue.time.time', return_value=1234567890):
            shared.install(self.catalog)
        evidence = self.arrival('cards', pid)
        self.assertEqual(evidence['queued_at'], 1234567890)
        self.assertEqual(evidence['basis'], 'migration_registration')

    def test_card_minimum_precedes_global_score_submission_order(self):
        self.config['web_cards']['shared_window']['backlog']={'queue_order':'paper_score'}
        entries={'card-slot':{'state':'ready_blank'},'review-slot':{'state':'ready_blank'}}
        heads={'card-slot':{'lane':'cards','job_id':'card','paper_id':'c','queued_at':1,'sequence':1,'score_order':True,'article_total_score':None},
               'review-slot':{'lane':'review','job_id':'review','paper_id':'r','queued_at':2,'sequence':2,'score_order':True,'article_total_score':175}}
        with patch('browser.shared_page_backlog.head_ready',side_effect=lambda catalog,config,tid:heads[tid]),patch('browser.shared_page_backlog.fixed_reservations',return_value=None):
            result=shared.backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['card-slot']})
        self.assertEqual(result['claim_order'][0]['job_id'],'card')
        self.assertEqual(result['card_ready'],['card-slot'])
        self.assertEqual(result['reserved_capacity'],1)

    def test_seed_precedes_other_lane_minimum_and_score_fast_lane(self):
        for scored in (False,True):
            self.config['web_cards']['shared_window']['backlog']={'queue_order':'paper_score' if scored else 'fifo'}
            entries={'c':{'state':'ready_blank'},'r':{'state':'ready_blank'}}
            heads={'c':{'lane':'cards','job_id':'ordinary','paper_id':'c','fast_lane':True},
                   'r':{'lane':'review','job_id':'seed-retry','paper_id':'r','seed_fast_lane':True}}
            with patch('browser.shared_page_backlog.head_ready',side_effect=lambda catalog,config,tid:heads[tid]),patch('browser.shared_page_backlog.fixed_reservations',return_value={'cards':['c'],'review':['r'],'correction':[]}):
                result=shared.backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']})
            self.assertEqual(result['claim_order'][0]['job_id'],'seed-retry')
            self.assertEqual(entries['c']['state'],'ready_blank')

    def test_minimum_admission_counts_pending_uploads_before_global_article_scores(self):
        self.config['web_cards']['shared_window']['backlog']={'queue_order':'paper_score'}
        entries={'c':{'state':'ready_blank'},'r':{'state':'ready_blank'}}
        heads={'c':{'lane':'cards','job_id':'new','paper_id':'c','queued_at':1,'sequence':1,'score_order':True,'article_total_score':None},
               'r':{'lane':'review','job_id':'old','paper_id':'r','queued_at':2,'sequence':2,'score_order':True,'article_total_score':175}}
        fixed={'cards':['c'],'review':['r'],'correction':[]}
        with patch('browser.shared_page_backlog.head_ready',side_effect=lambda catalog,config,tid:heads[tid]),patch('browser.shared_page_backlog.fixed_reservations',return_value=fixed):
            initial=shared.backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']})
            waiting=shared.backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']},pending_uploads={'review':{'uploading-r'}})
        self.assertEqual(initial['claim_order'][0]['job_id'],'old')
        self.assertEqual(waiting['claim_order'][0]['job_id'],'new')
        self.assertEqual(waiting['active'],initial['active'])
        self.assertEqual(entries['c']['state'],'ready_blank')

    def test_pending_target_already_active_is_not_counted_twice_for_minimum(self):
        self.config['web_cards']['shared_window']['backlog']={'queue_order':'paper_score'}
        entries={'c':{'state':'ready_blank'},'r':{'state':'ready_blank'},'active-r':{'state':'busy','kind':'review'}}
        entries.update({f'active-c-{n}':{'state':'busy','kind':'cards'} for n in range(3)})
        heads={'c':{'lane':'cards','job_id':'new','paper_id':'c','queued_at':1,'sequence':1,'score_order':True,'article_total_score':None},
               'r':{'lane':'review','job_id':'old','paper_id':'r','queued_at':2,'sequence':2,'score_order':True,'article_total_score':175}}
        with patch('browser.shared_page_backlog.head_ready',side_effect=lambda catalog,config,tid:heads[tid]),patch('browser.shared_page_backlog.fixed_reservations',return_value={'cards':['c'],'review':['r'],'correction':[]}):
            same=shared.backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']},pending_uploads={'review':{'active-r'}})
            more=shared.backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']},pending_uploads={'review':{'active-r','other-upload'}})
        self.assertEqual(same['claim_order'][0]['job_id'],'old')
        self.assertEqual(more['claim_order'][0]['job_id'],'new')

    def test_heads_include_only_ready_due_jobs_of_each_lane(self):
        ready_card = self.card_job('ready-card')
        self.card_job('waiting-material', material_state='waiting')
        self.card_job('unprepared', material_state=None)
        self.card_job('cooldown', retry_at=time.time() + 300)
        self.card_job('sent', state='submitted')
        ready_review = self.review_job('ready-review')
        self.review_job('preparing-review', state='preparing')
        self.review_job('sent-review', state='submitted')
        ready_correction = self.correction_job('ready-correction')
        heads = shared.heads(self.catalog, self.config)
        self.assertEqual([job['job_id'] for job in heads['cards']], [ready_card])
        self.assertEqual([job['job_id'] for job in heads['review']], [ready_review['id']])
        self.assertEqual([job['job_id'] for job in heads['correction']], [ready_correction['id']])

    def test_independent_pauses_hide_only_their_lane_and_keep_queue_receipts(self):
        pid = self.card_job()
        rjob = self.review_job()
        cjob = self.correction_job()
        original = self.transport(pid)
        for lane, control_file in (('cards', 'web-card-control.json'),
                                   ('review', 'card-review-control.json'),
                                   ('correction', 'card-correction-control.json')):
            with self.subTest(lane=lane):
                atomic_json(self.root/control_file, {'paused_by_user': True})
                heads = shared.heads(self.catalog, self.config)
                self.assertEqual(heads[lane], [])
                self.assertTrue(all(heads[other] for other in heads if other != lane))
                (self.root/control_file).unlink()
        self.assertEqual(self.transport(pid), original)
        self.assertEqual(next(job for job in review.rows(self.catalog) if job['id'] == rjob['id'])['state'], 'ready')
        self.assertEqual(next(job for job in correction.rows(self.catalog) if job['id'] == cjob['id'])['state'], 'ready')
        self.assertIsNotNone(self.arrival('review', rjob['id']))

    def test_correction_terminal_or_unready_state_never_reenters_web_heads(self):
        for state in ('queued', 'preparing', 'needs_user', 'failed', 'superseded', 'applied', 'submitted'):
            with self.subTest(state=state):
                job = self.correction_job('correction-' + state, state=state)
                self.assertFalse(any(head['job_id'] == job['id'] for head in shared.heads(self.catalog, self.config)['correction']))
                self.assertIsNone(self.claim(job['paper_id'], lane='correction', job_id=job['id']))
                self.assertEqual(self.transport(job['paper_id'])['attempts'], 0)

    def test_non_source_corrections_never_use_browser_pages(self):
        for kind in ('quote_location', 'formatting'):
            with self.subTest(kind=kind):
                job = self.correction_job(kind, kind=kind)
                self.assertEqual(shared.heads(self.catalog, self.config)['correction'], [])
                self.assertIsNone(self.claim(job['paper_id'], lane='correction', job_id=job['id']))

    def test_missing_or_wrong_paper_correction_binding_is_rejected(self):
        job = self.correction_job()
        with self.catalog.connect() as db:
            db.execute('UPDATE card_correction_jobs SET paper_id=? WHERE id=?', (self.paper('other'), job['id']))
        self.assertEqual(shared.heads(self.catalog, self.config)['correction'], [])
        self.assertIsNone(self.claim(job['paper_id'], lane='correction', job_id=job['id']))
        with self.catalog.connect() as db:
            db.execute('DELETE FROM card_correction_jobs WHERE id=?', (job['id'],))
        self.assertIsNotNone(self.arrival('correction', job['id']))
        self.assertEqual(shared.heads(self.catalog, self.config)['correction'], [])
        self.assertIsNone(self.claim(job['paper_id'], lane='correction', job_id=job['id']))

    def test_legacy_without_correction_id_is_classified_before_first_observation(self):
        pid = self.card_job('legacy-sent', state='submitted', selection={
            'rework': {'kind': 'source_review', 'review_id': 'missing-legacy-review'}})
        folder = self.root/'web_cards'/pid/'chatgpt'; folder.mkdir(parents=True)
        url = 'https://chatgpt.com/c/legacy-original'
        path = folder/'attempt.json'
        atomic_json(path, {'state': 'submitted', 'target_id': 'legacy-target',
            'conversation_url': url, 'send_click_started': True})
        before = path.read_bytes(); transport = self.transport(pid)
        entry = {'state': 'busy', 'kind': 'cards', 'active_paper_id': pid,
                 'conversation_url': url}
        entries = {'legacy-target': entry}
        correction.sync(self.catalog, self.config, entries)
        self.assertEqual(entry['kind'], 'correction')
        self.assertNotIn('correction_id', entry)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.transport(pid), transport)
        self.assertEqual(shared.heads(self.catalog, self.config)['cards'], [])
        self.assertEqual(shared.heads(self.catalog, self.config)['correction'], [])
        self.assertIsNone(self.claim(pid))
        self.assertIsNone(self.claim(pid, lane='correction', job_id='fabricated-id'))
        self.assertEqual(self.transport(pid)['attempts'], 0)

    def test_legacy_classification_requires_original_page_and_material_binding(self):
        pid = self.card_job('legacy-binding', state='submitted', selection={
            'rework': {'kind': 'source_review', 'review_id': 'missing-legacy-review'}})
        folder = self.root/'web_cards'/pid/'chatgpt'; folder.mkdir(parents=True)
        url = 'https://chatgpt.com/c/legacy-original'
        path = folder/'attempt.json'
        atomic_json(path, {'state': 'submitted', 'target_id': 'legacy-target',
                          'conversation_url': url})
        before = path.read_bytes()
        for options in ({'conversation_url': 'https://chatgpt.com/c/another'},
                        {'active_paper_id': 'another-paper'},
                        {'review_id': 'unrelated-review'}):
            with self.subTest(options=options):
                entry = {'state': 'busy', 'kind': 'cards', 'active_paper_id': pid,
                         'conversation_url': url, **options}
                correction.sync(self.catalog, self.config, {'legacy-target': entry})
                self.assertEqual(entry['kind'], 'cards')
        entry = {'state': 'busy', 'kind': 'cards', 'active_paper_id': pid,
                 'conversation_url': url}
        correction.sync(self.catalog, self.config, {'another-target': entry})
        self.assertEqual(entry['kind'], 'cards')
        self.assertEqual(path.read_bytes(), before)

    def test_assignment_bootstraps_waiting_material_before_any_ready_heads_exist(self):
        pid = self.card_job(material_state=None)
        self.assertEqual(shared.heads(self.catalog, self.config)['cards'], [])
        materials.assign(self.catalog, ['slot-1'], config=self.config)
        self.assertEqual(self.material(pid)['state'], 'waiting')
        self.assertEqual(self.material(pid)['target_id'], 'slot-1')
        with self.catalog.connect() as db:
            db.execute("UPDATE web_page_queue SET state='ready' WHERE paper_id=?", (pid,))
        self.assertEqual([head['job_id'] for head in shared.heads(self.catalog, self.config)['cards']], [pid])

    def test_paused_lane_is_not_assigned_new_material_but_other_lane_can_prepare(self):
        pid = self.card_job(material_state=None)
        cjob = self.correction_job()
        with self.catalog.connect() as db:
            db.execute('DELETE FROM web_page_queue WHERE paper_id=?', (cjob['paper_id'],))
        atomic_json(self.root/'web-card-control.json', {'paused_by_user': True})
        materials.assign(self.catalog, ['slot-1'], config=self.config)
        with self.catalog.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM web_page_queue WHERE paper_id=?', (pid,)).fetchone())
        self.assertEqual(self.material(cjob['paper_id'])['state'], 'waiting')

    def test_atomic_claim_binds_target_and_consumes_attempt_once(self):
        pid = self.card_job()
        before = self.arrival('cards', pid)
        claimed = self.claim(pid)
        self.assertEqual(claimed['paper_id'], pid)
        self.assertEqual(self.transport(pid)['state'], 'preparing')
        self.assertEqual(self.transport(pid)['attempts'], 1)
        self.assertEqual(self.material(pid)['target_id'], 'new-target')
        self.assertIsNone(self.claim(pid, target='another-target'))
        self.assertEqual(self.material(pid)['target_id'], 'new-target')
        self.assertEqual(self.arrival('cards', pid), before)

    def test_concurrent_claims_yield_one_claim_and_matching_target(self):
        pid = self.card_job()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda target: self.claim(pid, target=target),
                                        ('slot-a', 'slot-b')))
        self.assertEqual(sum(result is not None for result in results), 1)
        winner = ('slot-a', 'slot-b')[next(i for i, result in enumerate(results) if result is not None)]
        self.assertEqual(self.material(pid)['target_id'], winner)
        self.assertEqual(self.transport(pid)['attempts'], 1)

    def test_correction_claim_checks_expected_lane_and_job_id(self):
        job = self.correction_job()
        before = self.transport(job['paper_id'])
        self.assertIsNone(self.claim(job['paper_id'], lane='cards'))
        self.assertIsNone(self.claim(job['paper_id'], lane='correction', job_id='wrong-correction'))
        self.assertEqual(self.transport(job['paper_id']), before)
        self.assertEqual(self.material(job['paper_id'])['target_id'], 'original-target')
        self.assertIsNotNone(self.claim(job['paper_id'], lane='correction', job_id=job['id']))

    def test_kind_change_after_fifo_snapshot_cannot_claim_old_lane(self):
        pid = self.card_job()
        old = shared.heads(self.catalog, self.config)['cards'][0]
        with self.catalog.connect() as db:
            db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                       (json.dumps({'rework': {'correction_id': 'changed-kind'}}), pid))
        self.assertIsNone(self.claim(pid, lane='cards', job_id=old['job_id']))
        self.assertEqual(self.transport(pid)['attempts'], 0)
        self.assertEqual(self.material(pid)['target_id'], 'original-target')

    def test_pause_after_fifo_snapshot_prevents_claim_and_target_rebinding(self):
        for lane, control_file in (('cards', 'web-card-control.json'),
                                   ('correction', 'card-correction-control.json')):
            with self.subTest(lane=lane):
                if lane == 'cards':
                    pid = self.card_job('paused-card'); job_id = pid
                else:
                    job = self.correction_job('paused-correction'); pid = job['paper_id']; job_id = job['id']
                self.assertTrue(shared.heads(self.catalog, self.config)[lane])
                before = self.transport(pid)
                atomic_json(self.root/control_file, {'paused_by_user': True})
                self.assertIsNone(self.claim(pid, lane=lane, job_id=job_id))
                self.assertEqual(self.transport(pid), before)
                self.assertEqual(self.material(pid)['target_id'], 'original-target')
                (self.root/control_file).unlink()

    def test_corrupt_pause_control_blocks_claim_without_consuming_attempt(self):
        pid = self.card_job()
        (self.root/'web-card-control.json').write_text('{')
        self.assertEqual(shared.heads(self.catalog, self.config)['cards'], [])
        self.assertIsNone(self.claim(pid))
        self.assertEqual(self.transport(pid)['attempts'], 0)

    def test_cooldown_sent_unknown_or_unprepared_cannot_bind_or_claim(self):
        for name, options in (
                ('cooldown', {'retry_at': time.time() + 300}),
                ('sent', {'state': 'submitted'}),
                ('unknown', {'state': 'needs_inspection'}),
                ('unprepared', {'material_state': 'waiting'})):
            with self.subTest(name=name):
                pid = self.card_job(name, **options)
                before = self.transport(pid)
                self.assertIsNone(shared.bind_ready(self.catalog, pid, 'not-allowed'))
                self.assertIsNone(self.claim(pid))
                self.assertEqual(self.transport(pid), before)
                self.assertEqual(self.material(pid)['target_id'], 'original-target')

    def test_legacy_rebind_cannot_desynchronize_mixed_queue_material_mirror(self):
        from browser.shared_page_backlog import install
        install(self.catalog)
        pid=self.card_job('mixed-binding')
        before=self.material(pid)
        with self.assertRaisesRegex(ValueError,'禁止仅移动材料镜像'):
            shared.bind_ready(self.catalog,pid,'different-target')
        self.assertEqual(self.material(pid),before)

    def guard_fixture(self, *, rework=False):
        from cards.web_card_inputs import digest
        pid = self.card_job('final-guard', state='preparing')
        source = self.root/'source.pdf'; source.write_bytes(b'synthetic original source')
        folder = self.root/'frozen'; folder.mkdir()
        (folder/'source-context.json').write_text('synthetic frozen context')
        packet = {'source_original_sha256': digest(source),
                  'input_hashes': {'source-context.json': digest(folder/'source-context.json')}}
        atomic_json(folder/'packet.json', packet)
        self.catalog.update(pid, asset_path=str(source), asset_hash=digest(source), acquisition='available')
        selection = {}
        if rework:
            card_path = self.root/'card.json'; card_path.write_text('synthetic original card')
            backup = self.root/'backup'; backup.mkdir()
            (backup/'card.json').write_bytes(card_path.read_bytes())
            selection = {'rework': {'kind': 'source_review', 'old_card_path': str(card_path),
                'old_sha256': digest(card_path), 'backup': str(backup), 'correction_id': 'cid'}}
            self.catalog.update(pid, card_path=str(card_path))
        with self.catalog.connect() as db:
            db.execute('UPDATE web_card_jobs SET source_sha256=?,selection=? WHERE paper_id=?',
                       (digest(source), json.dumps(selection), pid))
        return self.transport(pid), folder, packet, source

    def test_final_submission_guard_accepts_only_current_frozen_input(self):
        from browser.web_submission_guard import check
        job, folder, packet, source = self.guard_fixture()
        self.assertEqual(check(self.catalog, self.config, job, folder, packet)['id'], job['paper_id'])
        source.write_bytes(b'changed original source during upload')
        with self.assertRaisesRegex(ValueError, '原文指纹变化'):
            check(self.catalog, self.config, job, folder, packet)

    def test_final_submission_guard_detects_changed_material_after_prepare(self):
        from browser.web_submission_guard import check
        job, folder, packet, _ = self.guard_fixture()
        (folder/'source-context.json').write_text('changed context during upload')
        with self.assertRaisesRegex(ValueError, '冻结输入指纹变化'):
            check(self.catalog, self.config, job, folder, packet)

    def test_source_review_final_guard_honors_new_human_decision(self):
        from browser.web_submission_guard import check
        job, folder, packet, _ = self.guard_fixture(rework=True)
        self.assertEqual(check(self.catalog, self.config, job, folder, packet)['id'], job['paper_id'])
        card = self.root/'card.json'; original = card.read_bytes()
        self.catalog.decide(job['paper_id'], 'keep')
        with self.assertRaisesRegex(ValueError, '人工决定'):
            check(self.catalog, self.config, job, folder, packet)
        self.assertEqual(card.read_bytes(), original)

    def test_source_review_final_guard_rejects_changed_original_card(self):
        from browser.web_submission_guard import check
        job, folder, packet, _ = self.guard_fixture(rework=True)
        (self.root/'card.json').write_text('changed scientific card')
        with self.assertRaisesRegex(ValueError, '旧卡片已变化'):
            check(self.catalog, self.config, job, folder, packet)

    def test_final_submission_guard_honors_identity_flags_and_claim_version(self):
        from browser.web_submission_guard import check
        job, folder, packet, _ = self.guard_fixture()
        metadata = self.catalog.get(job['paper_id'])['metadata']
        with self.catalog.connect() as db:
            db.execute('UPDATE papers SET metadata=? WHERE id=?',
                       (json.dumps({**metadata, 'version_review_required': True}), job['paper_id']))
        with self.assertRaisesRegex(ValueError, '身份、版本或范围'):
            check(self.catalog, self.config, job, folder, packet)
        with self.catalog.connect() as db:
            db.execute('UPDATE papers SET metadata=? WHERE id=?', (json.dumps(metadata), job['paper_id']))
            db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                       (json.dumps({'changed_queue_version': True}), job['paper_id']))
        with self.assertRaisesRegex(ValueError, '任务版本或队列状态变化'):
            check(self.catalog, self.config, job, folder, packet)


if __name__ == '__main__':
    unittest.main()
