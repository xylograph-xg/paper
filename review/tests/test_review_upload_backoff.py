"""Real receipt, catalog and dispatch proof for the review upload backoff."""
import json
import sqlite3
import time
import unittest
from contextlib import contextmanager, nullcontext, ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from core.api import paths__WorkspacePath as Path

from core.services import atomic_json
from review.card_review_lane import ReviewLane
from review import card_review_queue as queue
from review.review_channel_recovery import recover
from review.tests.test_card_review_queue import ReviewQueue
from browser.shared_page_backlog import install as install_backlog
from browser import upload_retry_policy as policy
from browser.web_card_transport import DeferredWeb, UploadStageFailure
from correction.card_correction_queue import install as install_corrections


class ReviewUploadBackoffTests(ReviewQueue):
    def setUp(self):
        super().setUp()
        self.config['card_review']['upload_retry'] = {'enabled':True,'backoff_seconds':[300,900,3600]}
        install_backlog(self.catalog); install_corrections(self.catalog)
        self.lane = ReviewLane.__new__(ReviewLane)
        self.lane.config = self.config
        self.lane.catalog = self.catalog
        self.router = Mock(); self.router.choose.return_value = 'chatgpt'
        self.page = Mock(); self.page.url = 'https://chatgpt.com/'
        empty = Mock(); empty.count.return_value = 0; self.page.locator.return_value = empty
        self.entries = {'target':{'state':'ready_blank','slot':1}}

    def ready(self, title='Synthetic', quality=87, novelty=88, *, images=True):
        """One fully prepared review job whose real packet carries a frozen ZIP."""
        job, _, card = self.card(title, quality, novelty)
        folder, packet = self.packet(job, card)
        if images:packet['review_images_version'] = 1
        atomic_json(folder/'packet.json', packet)
        queue.update(self.catalog, job['id'], 'ready')
        return job, folder, packet

    def reset_page(self):
        self.entries.clear(); self.entries['target'] = {'state':'ready_blank','slot':1}
        self.page.reset_mock(); self.page.url = 'https://chatgpt.com/'
        empty = Mock(); empty.count.return_value = 0; self.page.locator.return_value = empty

    def clear_attempt(self, folder):
        Path(folder).joinpath('attempt.json').unlink(missing_ok=True)

    def cool(self, job, packet):
        attempt = {'state':'not_sent','send_click_started':False,'created':time.time()-10,
            'finished':time.time(),'upload_failure_stage':'attach','error':'附件上传失败',
            'inputs':packet['input_hashes'],'upload_bundle':packet['upload_bundle']}
        return policy.record_failure(self.catalog,config=self.config,job_id=job['id'],attempt=attempt)

    def expire(self, job_id):
        with self.catalog.connect() as db:
            db.execute('UPDATE upload_retry_policy SET next_eligible=? WHERE job_id=?',
                       (time.time()-1, job_id))

    def corrupt(self, job_id, *, consecutive=-1):
        with self.catalog.connect() as db:
            db.execute('UPDATE upload_retry_policy SET consecutive=? WHERE job_id=?',
                       (consecutive, job_id))

    def stored(self, job_id):
        with self.catalog.connect() as db:
            return dict(db.execute('SELECT * FROM upload_retry_policy WHERE job_id=?',(job_id,)).fetchone())

    def rejection(self):
        return json.loads((self.catalog.path.parent/'review-dispatch-rejection.json').read_text())

    def stack(self, packet):
        stack = ExitStack()
        stack.enter_context(patch('review.card_review_queue.check_packet', return_value=packet))
        stack.enter_context(patch('browser.shared_window_owner.require_reusable'))
        stack.enter_context(patch('browser.reusable_home.prepare', return_value={'inspection_complete':True}))
        stack.enter_context(patch('browser.gpt_model_policy.configure_session',
            return_value=SimpleNamespace(settings={'model':'GPT-6','effort':'High'})))
        stack.enter_context(patch('browser.web_card_pool.record_channel_failure'))
        return stack

    def state(self, job_id):
        return next(row for row in queue.rows(self.catalog) if row['id'] == job_id)['state']

    def rows_in(self, table):
        with self.catalog.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM '+table)]

    def attempt(self, folder):
        return json.loads((Path(folder)/'attempt.json').read_text())

    def submit(self, *, options=None):
        return self.lane.submit({'target':self.page},self.entries,0,self.router,
            (lambda **kw: nullcontext()) if options is None else options, lambda:False)

    def test_upload_failure_is_counted_once_from_the_durable_receipt(self):
        job, folder, packet = self.ready()
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure('附件上传失败','attach')):
            self.assertFalse(self.submit())
        attempt = self.attempt(folder)
        self.assertEqual(attempt['state'],'not_sent');self.assertFalse(attempt['send_click_started'])
        self.assertEqual(attempt['upload_failure_stage'],'attach')
        rows = self.rows_in('upload_retry_policy')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['consecutive'],1)
        self.assertEqual(rows[0]['next_eligible'],attempt['finished']+300)
        receipts = self.rows_in('upload_retry_receipts')
        self.assertEqual(len(receipts),1);self.assertEqual(receipts[0]['stage'],'attach')
        self.assertEqual(receipts[0]['job_id'],job['id'])

    def test_every_entry_refuses_the_wait_without_starting_another_upload(self):
        job, folder, packet = self.ready()
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure('附件上传失败','attach')) as send:
            self.assertFalse(self.submit());self.assertEqual(send.call_count,1)
            queue.update(self.catalog, job['id'], 'ready'); self.reset_page()
            self.assertFalse(self.submit())
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                lambda **kw:nullcontext(),lambda:False,job_id=job['id'],assigned_target_id='target'))
            self.reset_page()
            self.assertFalse(self.submit())
        self.assertEqual(send.call_count,1)
        self.page.goto.assert_not_called()
        rejection = json.loads((self.catalog.path.parent/'review-dispatch-rejection.json').read_text())
        self.assertIn('upload_cooldown',rejection['reason'])
        self.assertEqual(len(self.rows_in('upload_retry_receipts')),1)
        self.assertEqual(self.state(job['id']),'ready')

    def test_expiry_restores_the_same_material_without_a_new_request(self):
        job, folder, packet = self.ready()
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure('附件上传失败','attach')) as submit:
            self.assertFalse(self.submit())
            queue.update(self.catalog, job['id'], 'ready'); self.reset_page()
            self.clear_attempt(folder)
            self.assertFalse(self.submit())
            self.assertEqual(submit.call_count,1)
            self.expire(job['id'])
            self.reset_page(); self.clear_attempt(folder)
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                lambda **kw:nullcontext(),lambda:False))
        self.assertEqual(submit.call_count,2)
        self.assertEqual(len(self.rows_in('upload_retry_receipts')),2)
        self.assertEqual(self.rows_in('upload_retry_policy')[0]['consecutive'],2)

    def test_unknown_receipt_is_never_counted_as_an_upload_failure(self):
        job, folder, packet = self.ready()
        def send(session, prompt, files, **options):
            options['on_before_send'](); raise RuntimeError('Unknown receipt')
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background', side_effect=send):
            self.assertFalse(self.submit())
        self.assertEqual(self.rows_in('upload_retry_receipts'),[])
        self.assertEqual(self.rows_in('upload_retry_policy'),[])
        attempt = self.attempt(folder)
        self.assertTrue(attempt['send_click_started']);self.assertEqual(attempt['state'],'needs_inspection')
        self.assertNotIn('upload_failure_stage',attempt)

    def test_pause_during_upload_is_not_an_upload_failure(self):
        job, folder, packet = self.ready()
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background',
                side_effect=DeferredWeb('已暂停，未上传材料')):
            self.assertFalse(self.submit())
        self.assertEqual(self.rows_in('upload_retry_receipts'),[])
        self.assertEqual(self.rows_in('upload_retry_policy'),[])
        attempt = self.attempt(folder)
        self.assertFalse(attempt['send_click_started'])
        self.assertNotIn('upload_failure_stage',attempt)

    def test_final_send_guard_refuses_the_click_without_adding_a_failure(self):
        job, folder, packet = self.ready()
        clicks = []
        def send(session, prompt, files, **options):
            options['on_before_send'](); clicks.append('clicked'); return 0
        @contextmanager
        def locking(*args, **options):
            if not locking.seen:
                locking.seen = True
                # Simulate the wait appearing after this page was already
                # claimed: an ended, never-clicked upload receipt exists now.
                locking.result = policy.record_failure(self.catalog,config=self.config,job_id=job['id'],
                    attempt={**self.attempt(folder),'state':'not_sent','finished':time.time(),
                             'upload_failure_stage':'attach'})
            yield
        locking.seen = False
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background', side_effect=send):
            self.assertFalse(self.submit(options=locking))
        self.assertEqual(clicks,[])
        self.assertEqual(locking.result['consecutive'],1)
        attempt = self.attempt(folder)
        self.assertFalse(attempt['send_click_started']);self.assertEqual(attempt['state'],'not_sent')
        self.assertEqual(len(self.rows_in('upload_retry_receipts')),1)

    def test_healthy_material_still_dispatches_while_another_waits(self):
        cooling, _, cooling_packet = self.ready(title='cooling')
        healthy, _, healthy_packet = self.ready(title='healthy', quality=60)
        self.cool(cooling, cooling_packet)
        prompts = []
        def send(session, prompt, files, **options):
            prompts.append(Path(files[0]).name); return 0
        with self.stack(healthy_packet), patch('browser.web_card_transport.submit_gpt_background', side_effect=send):
            self.assertTrue(self.submit())
        self.assertEqual(self.state(cooling['id']),'ready')
        self.assertEqual(self.state(healthy['id']),'submitted')
        self.assertEqual(prompts,[Path(healthy_packet['upload_bundle']['zip_path']).name])

    def test_recovery_waits_for_the_backoff_then_keeps_the_original_receipt(self):
        job, folder, packet = self.ready(images=False)
        atomic_json(folder/'attempt.json',{'state':'not_sent','send_click_started':False,
            'review_id':job['id'],'inputs':packet['input_hashes'],
            'actual_prompt_sha256':packet['actual_prompt_sha256'],
            'upload_bundle':packet['upload_bundle'],'created':time.time()-10,'finished':time.time(),
            'upload_failure_stage':'attach','error':'附件上传失败'})
        queue.update(self.catalog, job['id'],'needs_user','附件上传失败')
        self.cool(job, packet)
        report = recover(self.catalog,self.config)
        self.assertEqual(report['recovered'],[])
        self.assertIn('冷却',report['retained'][0]['reason'])
        self.assertTrue((Path(folder)/'attempt.json').is_file())
        self.expire(job['id'])
        report = recover(self.catalog,self.config)
        self.assertEqual(report['recovered'],[job['id']])
        self.assertFalse((Path(folder)/'attempt.json').is_file())
        archived = list(Path(folder).glob('history/*/attempt.json'))
        self.assertEqual(len(archived),1)
        self.assertEqual(json.loads(archived[0].read_text())['upload_failure_stage'],'attach')
        self.assertEqual(self.state(job['id']),'ready')
        row = next(item for item in queue.rows(self.catalog) if item['id']==job['id'])
        # Recovery re-queues with the original arrival: no science counters,
        # no result body and no ledger column were invented by the backoff.
        self.assertEqual(json.loads(row['result']),{})
        self.assertEqual(row['error'],'')

    def test_policy_never_touches_card_limits_or_the_review_ledger_columns(self):
        job, folder, packet = self.ready()
        with self.catalog.connect() as db:
            columns = [row[1] for row in db.execute('PRAGMA table_info(card_review_jobs)')]
            cards_before = [dict(row) for row in db.execute('SELECT * FROM web_card_jobs')]
        self.assertNotIn('retry_at',columns)
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure('附件上传失败','attach')):
            for _ in range(3):
                self.assertFalse(self.submit())
                queue.update(self.catalog, job['id'],'ready'); self.reset_page()
        self.assertEqual(len(self.rows_in('upload_retry_receipts')),1)
        with self.catalog.connect() as db:
            self.assertEqual([dict(row) for row in db.execute('SELECT * FROM web_card_jobs')],cards_before)
        self.assertEqual(self.state(job['id']),'ready')

    def test_disabled_policy_submits_every_attempt_as_before(self):
        job, folder, packet = self.ready()
        self.lane.config = {**self.config,'card_review':{k:value for k,value in
            self.config['card_review'].items() if k != 'upload_retry'}}
        calls = []
        def send(session, prompt, files, **options):
            calls.append(prompt); raise UploadStageFailure('附件上传失败','attach')
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background', side_effect=send):
            for _ in range(2):
                self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                    lambda **kw:nullcontext(),lambda:False))
                queue.update(self.catalog, job['id'],'ready')
                self.reset_page(); self.clear_attempt(folder)
        self.assertEqual(len(calls),2)
        self.assertEqual(self.rows_in('upload_retry_receipts'),[])
        self.assertEqual(self.rows_in('upload_retry_policy'),[])

    def test_damaged_policy_row_at_the_claim_refuses_only_this_material(self):
        job, folder, packet = self.ready()
        self.cool(job, packet)
        self.corrupt(job['id'])
        proofs=[]
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                lambda **kw:nullcontext(),lambda:False,on_unstarted=proofs.append))
        send.assert_not_called()
        self.assertEqual(self.state(job['id']),'ready')
        self.assertEqual(self.stored(job['id'])['consecutive'],-1)
        self.assertFalse((Path(folder)/'attempt.json').exists())
        self.assertEqual(self.entries['target']['state'],'ready_blank')
        self.assertIn('upload_policy_error',self.rejection()['reason'])
        self.assertEqual(len(proofs),1)
        self.assertIs(proofs[0]['native_file_write_started'],False)

    def test_prior_reservation_without_a_put_preserves_material_before_page_use(self):
        from browser.original_upload_http1 import OriginalPutProbe
        job,folder,packet=self.ready()
        probe=OriginalPutProbe(self.catalog.path.parent,Mock(),'old-reservation')
        context={'lane':'review','job_id':job['id'],'paper_id':job['paper_id'],
                 'target_id':'target','bundle':packet['upload_bundle']}
        self.assertTrue(probe.arm(Mock(),context,lambda:None))
        evidence=probe.reservation.read_bytes();proofs=[]
        with self.stack(packet),patch('browser.web_card_transport.submit_gpt_background',return_value=0) as send,\
                patch('browser.shared_window_owner.require_reusable'):
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                lambda **kw:nullcontext(),lambda:False,on_unstarted=proofs.append))
        send.assert_not_called()
        self.assertFalse(probe.path.exists())
        self.assertEqual(probe.reservation.read_bytes(),evidence)
        self.assertEqual(self.state(job['id']),'ready')
        self.page.goto.assert_not_called()
        self.assertFalse((Path(folder)/'attempt.json').exists())
    def test_claim_policy_error_does_not_escape_into_the_dispatch_cycle(self):
        # The owner calls this synchronously at web_card_pool.py:717 and only then
        # dispatches cards and corrections in the same cycle; an exception leaking
        # past submit() would skip that whole remainder every round.
        job, _, packet = self.ready()
        self.cool(job, packet)
        self.corrupt(job['id'])
        for parallel in (False,True):
            with self.subTest(parallel_upload=parallel):
                try:
                    result=self.lane.submit({'target':self.page},self.entries,0,self.router,
                        lambda **kw:nullcontext(),lambda:False,parallel_upload=parallel)
                except Exception as exc:
                    self.fail('ReviewLane.submit leaked %s: %s' % (type(exc).__name__,exc))
                self.assertFalse(result)
                self.reset_page()
        self.assertEqual(self.state(job['id']),'ready')

    def test_damaged_policy_row_never_downgrades_a_sent_request(self):
        job, folder, packet = self.ready()
        self.cool(job, packet); self.expire(job['id'])
        def send(session, prompt, files, **options):
            options['on_before_send']()
            self.corrupt(job['id'])   # the damage appears only after the durable send
            return 0
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background', side_effect=send):
            self.assertTrue(self.submit())
        attempt = self.attempt(folder)
        self.assertEqual(attempt['state'],'submitted')
        self.assertTrue(attempt['send_click_started'])
        self.assertIn('upload_settle_policy_error',attempt)
        self.assertNotIn('needs_inspection',json.dumps(attempt))
        self.assertEqual(self.state(job['id']),'submitted')
        self.assertEqual(self.entries['target'].get('state'),'busy')
        self.assertEqual(self.stored(job['id'])['consecutive'],-1)
        self.assertIn('upload_policy_error',self.rejection()['reason'])

    def test_a_busy_write_lock_on_the_streak_clear_never_downgrades_a_sent_request(self):
        # Second documented raise path at the same call: the clear opens its own
        # BEGIN IMMEDIATE, so a concurrent writer can block it and fail.
        job, folder, packet = self.ready()
        def send(session, prompt, files, **options):
            options['on_before_send']()
            return 0
        with self.stack(packet), \
                patch('browser.web_card_transport.submit_gpt_background', side_effect=send) as submit, \
                patch('browser.upload_retry_policy.settle_success',
                      side_effect=sqlite3.OperationalError('database is locked')) as clear:
            self.assertTrue(self.submit())
        self.assertEqual(clear.call_count,1);self.assertEqual(submit.call_count,1)
        attempt = self.attempt(folder)
        self.assertEqual(attempt['state'],'submitted')
        self.assertIn('OperationalError',attempt['upload_settle_policy_error'])
        self.assertEqual(self.state(job['id']),'submitted')
        self.assertEqual(self.entries['target'].get('state'),'busy')
        self.assertNotIn('needs_inspection',json.dumps(self.entries['target']))
        self.assertIn('upload_policy_error',self.rejection()['reason'])

    def test_persistent_receipt_reason_is_stripped_of_the_signed_url(self):
        job, folder, packet = self.ready()
        leak = 'PUT https://files.oaiusercontent.com/files/secret?sig=private 401'
        with self.stack(packet), patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure(leak,'attach_write')):
            self.assertFalse(self.submit())
        self.assertEqual(self.attempt(folder)['upload_failure_stage'],'attach_write')
        receipts = self.rows_in('upload_retry_receipts')
        self.assertEqual(len(receipts),1)
        for secret in ('signed?','sig=private','private'):
            self.assertNotIn(secret,receipts[0]['reason'])
        self.assertIn('files.oaiusercontent.com',receipts[0]['reason'])

    def test_failed_upload_policy_lock_still_finishes_the_original_unsent_job(self):
        job,folder,packet=self.ready()
        with self.stack(packet),patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure('synthetic upload failure','attach_write')),patch(
                'browser.upload_retry_policy.record_failure',side_effect=sqlite3.OperationalError('database is locked')):
            self.assertFalse(self.submit())
        self.assertEqual(self.state(job['id']),'needs_user')
        self.assertEqual(self.attempt(folder)['state'],'not_sent')
        self.assertFalse(self.attempt(folder)['send_click_started'])
        self.assertIn('OperationalError',self.attempt(folder)['upload_failure_policy_error'])
        self.assertEqual(self.entries['target']['state'],'needs_inspection')

    def test_diagnostic_write_failure_cannot_skip_unsent_cleanup(self):
        job,folder,packet=self.ready()
        original=__import__('review.card_review_lane',fromlist=['atomic_json']).atomic_json
        def write(path,value,*args,**kwargs):
            if Path(path).name=='review-dispatch-rejection.json':raise OSError('diagnostic disk unavailable')
            return original(path,value,*args,**kwargs)
        with self.stack(packet),patch('browser.web_card_transport.submit_gpt_background',
                side_effect=UploadStageFailure('synthetic upload failure','attach_write')),patch(
                'browser.upload_retry_policy.record_failure',side_effect=sqlite3.OperationalError('database is locked')),patch(
                'review.card_review_lane.atomic_json',side_effect=write):
            self.assertFalse(self.submit())
        self.assertEqual(self.state(job['id']),'needs_user')
        self.assertEqual(self.entries['target']['state'],'needs_inspection')
        self.assertEqual(self.attempt(folder)['state'],'not_sent')

    def test_corrupt_first_material_does_not_starve_a_healthy_following_material(self):
        damaged,_,packet=self.ready('damaged');self.cool(damaged,packet);self.corrupt(damaged['id'])
        healthy,folder,packet=self.ready('healthy')
        with self.stack(packet),patch('browser.web_card_transport.submit_gpt_background',return_value=0) as send:
            self.assertTrue(self.submit())
        self.assertEqual(send.call_count,1)
        self.assertEqual(self.state(damaged['id']),'ready')
        self.assertEqual(self.stored(damaged['id'])['consecutive'],-1)
        self.assertEqual(self.state(healthy['id']),'submitted')
        self.assertEqual(self.rejection()['job_id'],damaged['id'])



    def test_ended_receipt_recovers_lost_queue_ack_without_requeueing_or_freeing_upload(self):
        job,folder,packet=self.ready()
        queue.update(self.catalog,job['id'],'submitting')
        receipt={'review_id':job['id'],'target_id':'target','state':'not_sent','send_click_started':False,
                 'finished':time.time(),'inputs':packet['input_hashes'],'error':'original upload failed'}
        atomic_json(folder/'attempt.json',receipt)
        self.entries['target'].update(kind='review',review_id=job['id'],state='busy')
        before=(folder/'attempt.json').read_bytes()
        with patch('review.card_review_queue.check_packet',return_value=packet):
            self.assertEqual(self.lane.reconcile_submissions(self.entries,excluded_targets={'target'}),[])
            self.assertEqual(self.lane.reconcile_submissions(self.entries),[job['id']])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()[0],'needs_user')
        self.assertEqual(self.entries['target']['state'],'needs_inspection')
        self.assertEqual((folder/'attempt.json').read_bytes(),before)

    def test_unknown_ended_receipt_never_becomes_ready_or_terminal(self):
        job,folder,packet=self.ready();queue.update(self.catalog,job['id'],'submitting')
        atomic_json(folder/'attempt.json',{'review_id':job['id'],'target_id':'target','state':'needs_inspection',
            'send_click_started':True,'finished':time.time(),'inputs':packet['input_hashes']})
        self.assertEqual(self.lane.reconcile_submissions(self.entries),[])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()[0],'submitting')

    def test_original_put_unknown_is_retained_across_epoch_and_recovery(self):
        import hashlib
        from browser.original_upload_http1 import OriginalPutProbe
        job,folder,packet=self.ready();self.cool(job,packet);self.expire(job['id'])
        bundle=packet['upload_bundle'];payload=Path(bundle['zip_path']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),bundle['zip_sha256'])
        api=Mock();api.fetch.side_effect=TimeoutError('ECONNRESET')
        probe=OriginalPutProbe(self.catalog.path.parent,api,'old-epoch');page=Mock()
        probe.arm(page,{'lane':'review','job_id':job['id'],'paper_id':job['paper_id'],
            'target_id':'target','bundle':bundle},lambda:None)
        request=SimpleNamespace(method='PUT',url='https://sdmntprwestus.oaiusercontent.com/upload?sig=fixture',
            post_data_buffer=payload,all_headers=lambda:{})
        page.route.call_args.args[1](Mock(request=request))
        self.assertEqual(probe.read()['state'],'unknown')
        attempt={'review_id':job['id'],'target_id':'target','state':'not_sent','send_click_started':False,
            'finished':time.time(),'inputs':packet['input_hashes'],'actual_prompt_sha256':packet['actual_prompt_sha256']}
        atomic_json(folder/'attempt.json',attempt);queue.update(self.catalog,job['id'],'needs_user')
        before=(folder/'attempt.json').read_bytes()
        with self.stack(packet):
            report=recover(self.catalog,self.config)
        self.assertNotIn(job['id'],report['recovered']);self.assertEqual(before,(folder/'attempt.json').read_bytes())
        queue.update(self.catalog,job['id'],'ready')
        with self.stack(packet):self.assertFalse(self.submit())
        self.assertIn('持久意图',self.rejection()['reason'])
        self.assertEqual(api.fetch.call_count,1)

if __name__ == '__main__':
    unittest.main()
