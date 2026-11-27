"""Regression evidence for the independent correction audit."""
import json
import unittest
from unittest.mock import patch
from correction.tests import test_card_correction_queue as fixtures
from correction import card_correction_queue as q


class AuditRegressions(unittest.TestCase):
    setUp = fixtures.CorrectionQueue.setUp
    card = fixtures.CorrectionQueue.card
    packet = fixtures.CorrectionQueue.packet
    receipt = fixtures.CorrectionQueue.receipt
    feedback = fixtures.CorrectionQueue.feedback
    original_card_receipt = fixtures.CorrectionQueue.original_card_receipt
    def prepared(self):
        job, path, card = self.card()
        self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        correction = q.enqueue_review(self.catalog, job, self.config)
        q.process(self.catalog, correction, self.config)
        return q.rows(self.catalog)[0]

    def test_late_callback_and_forged_completion(self):
        correction = self.prepared()
        from cards.web_card_queue import jobs
        webjob = jobs(self.catalog)[0]
        self.assertFalse(q.mark_web_state(self.catalog, webjob, 'completed', publication_checked=True))
        self.assertEqual(q.rows(self.catalog)[0]['state'], 'ready')
        self.assertFalse(q.mark_web_state(self.catalog, {**webjob, 'paper_id':'other'}, 'submitted'))
        self.assertTrue(q.allows_web_job(self.config, webjob))
        q.update(self.catalog, correction['id'], 'applied')
        self.assertFalse(q.mark_web_state(self.catalog, webjob, 'submitted'))
        self.assertFalse(q.allows_web_job(self.config, webjob))
        self.assertEqual(q.rows(self.catalog)[0]['state'], 'applied')

    def test_constructor_preserves_live_preparing(self):
        job, path, card = self.card(); self.receipt(job, card)
        q.enqueue_review(self.catalog, job, self.config)
        q.claim(self.catalog, self.config)
        q.CorrectionProducer(self.config)
        self.assertEqual(q.rows(self.catalog)[0]['state'], 'preparing')

    def test_publication_failure_recovers_published_bytes(self):
        job, path, card = self.card(); self.receipt(job, card)
        queued = q.enqueue_review(self.catalog, job, self.config)
        q.claim(self.catalog, self.config)
        before = path.read_bytes()
        with patch('review.card_review_queue.replacement', side_effect=RuntimeError('injected after publication')):
            with self.assertRaises(RuntimeError):
                q.process(self.catalog, queued, self.config)
        published = path.read_bytes()
        self.assertNotEqual(before, published)
        self.assertTrue(q._recover_local(self.catalog, q.rows(self.catalog)[0], self.config))
        self.assertEqual(path.read_bytes(), published)
        self.assertEqual(q.rows(self.catalog)[0]['state'], 'applied')

    def test_migration_insert_failure_rolls_back_both_entities(self):
        from review import card_review_queue as review
        from cards.web_card_queue import jobs
        job, path, card = self.card(); _, result = self.receipt(job, card, 'rework')
        self.original_card_receipt(job, path)
        review.queue_rework(self.catalog, job, self.config, self.catalog.get(job['paper_id']), path, result)
        before = jobs(self.catalog)[0]
        original = q._enqueue
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('injected inside migration transaction')
        with patch.object(q, '_enqueue', side_effect=interrupted):
            self.assertTrue(q.adopt_legacy(self.catalog, self.config)['errors'])
        self.assertEqual(q.rows(self.catalog), [])
        self.assertEqual(jobs(self.catalog)[0], before)
        self.assertEqual(q.adopt_legacy(self.catalog, self.config)['adopted'], 1)

    def test_second_producer_cannot_enter_owned_loop(self):
        import fcntl
        first = q.CorrectionProducer(self.config)
        second = q.CorrectionProducer(self.config)
        with (self.catalog.path.parent/'correction-producer.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(second, '_run_owned') as loop:
                second.run()
            loop.assert_not_called()

    def test_gate_is_read_only_inside_callers_write_transaction(self):
        self.prepared()
        from cards.web_card_queue import jobs
        job = jobs(self.catalog)[0]
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            with patch.object(q, 'Catalog', side_effect=AssertionError('gate must not initialize catalog')):
                self.assertTrue(q.allows_web_job(self.config, job))

    def test_recovery_permission_does_not_allow_dispatch(self):
        correction = self.prepared()
        from cards.web_card_queue import jobs
        job = jobs(self.catalog)[0]
        q.update(self.catalog, correction['id'], 'needs_user', 'technical failure')
        self.assertFalse(q.allows_web_job(self.config, job))
        self.assertTrue(q.allows_web_job(self.config, job, recovery=True))
        self.assertFalse(q.allows_web_job(self.config, {**job,'paper_id':'other'}, recovery=True))

class PreparedIntentRecovery(unittest.TestCase):
    setUp=fixtures.CorrectionQueue.setUp
    card=fixtures.CorrectionQueue.card
    packet=fixtures.CorrectionQueue.packet
    receipt=fixtures.CorrectionQueue.receipt
    feedback=fixtures.CorrectionQueue.feedback
    original_card_receipt=fixtures.CorrectionQueue.original_card_receipt
    prepared=AuditRegressions.prepared

    def interrupted(self):
        job=self.prepared()
        error='唯一生产者核对执行中断；保留候选与原回执，不重新发布或发送'
        with self.catalog.connect() as db:
            db.execute("UPDATE card_correction_jobs SET state='failed',error=? WHERE id=?",('自动终止：'+error,job['id']))
        return q.rows(self.catalog)[0]

    def test_exact_prepared_intent_recovers_once_without_new_rework(self):
        from cards.web_card_queue import jobs
        job=self.interrupted();before=jobs(self.catalog)[0]
        with patch('review.card_review_queue.queue_rework',side_effect=AssertionError('must not create another rework')):
            self.assertEqual(q.sync(self.catalog,self.config),1)
            self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'ready')
        self.assertEqual(jobs(self.catalog)[0],before)
        with self.catalog.connect() as db:
            events=db.execute("SELECT payload FROM events WHERE kind='correction_prepared_intent_reconciled'").fetchall()
        self.assertEqual(len(events),1)
        self.assertIn('previous_error',json.loads(events[0][0]))

    def test_other_failure_is_not_reclassified(self):
        job=self.interrupted()
        with self.catalog.connect() as db:db.execute("UPDATE card_correction_jobs SET error='unrelated failure' WHERE id=?",(job['id'],))
        self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')

    def test_current_unknown_receipt_preserves_failed_state(self):
        job=self.interrupted();root=self.root/'web_cards'/job['paper_id']/'chatgpt';root.mkdir()
        (root/'attempt.json').write_text(json.dumps({'state':'submitted','send_click_started':True}))
        self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')

    def test_changed_task_does_not_restore_admission(self):
        job=self.interrupted();task=self.root/'card_corrections'/job['paper_id']/job['id']/'task.json'
        task.write_text('{}')
        self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')

    def test_changed_source_and_unknown_archive_remain_blocked(self):
        job=self.interrupted()
        root=self.root/'web_cards'/job['paper_id']/'history'/'unknown'/'chatgpt'
        root.mkdir(parents=True)
        (root/'attempt.json').write_text(json.dumps({'state':'submitted','send_click_started':True}))
        self.assertEqual(q.sync(self.catalog,self.config),0)
        (root/'attempt.json').unlink()
        from pathlib import Path
        Path(self.catalog.get(job['paper_id'])['asset_path']).write_bytes(b'changed source')
        self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')

    def test_pause_alone_does_not_restore_ready(self):
        self.interrupted()
        (self.root/'card-correction-control.json').write_text(json.dumps({'paused_by_user':True}))
        self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')

    def test_concurrent_row_change_is_not_overwritten(self):
        job=self.interrupted();original=q._collected_review
        def drift(*args,**kwargs):
            result=original(*args,**kwargs)
            with self.catalog.connect() as db:
                db.execute("UPDATE card_correction_jobs SET error='concurrent evidence decision' WHERE id=?",(job['id'],))
            return result
        with patch.object(q,'_collected_review',side_effect=drift):
            self.assertEqual(q.sync(self.catalog,self.config),0)
        row=q.rows(self.catalog)[0]
        self.assertEqual(row['state'],'failed')
        self.assertEqual(row['error'],'concurrent evidence decision')

    def test_human_protection_and_pause_are_preserved(self):
        job=self.interrupted();self.catalog.event(job['paper_id'],'human_decision',{'decision':'keep'})
        self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')
        (self.root/'card-correction-control.json').write_text(json.dumps({'paused_by_user':True}))
        self.assertEqual(q.sync(self.catalog,self.config),0)

    def test_drift_during_evidence_read_fails_closed(self):
        job=self.interrupted();original=q._collected_review
        def drift(*args,**kwargs):
            result=original(*args,**kwargs)
            source=self.catalog.get(job['paper_id'])['asset_path']
            from pathlib import Path
            Path(source).write_bytes(b'changed after validation')
            return result
        with patch.object(q,'_collected_review',side_effect=drift):
            self.assertEqual(q.sync(self.catalog,self.config),0)
        self.assertEqual(q.rows(self.catalog)[0]['state'],'failed')
