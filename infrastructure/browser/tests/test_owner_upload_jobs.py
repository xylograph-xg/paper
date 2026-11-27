import asyncio
import json
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from browser.owner_upload_jobs import OwnerUploadJobs


class OwnerUploadTests(unittest.TestCase):
    def test_durable_callback_lease_exists_before_dispatch_and_ends_after_callback(self):
        import tempfile,os
        from pathlib import Path
        from browser.owner_upload_jobs import active_lease_targets
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);owner=root/'web-card-service.json'
            owner.write_text(json.dumps({'pid':os.getpid(),'token':'original-owner'}))
            with patch('browser.upload_trace.root',return_value=root), sync_playwright() as pw:
                jobs=OwnerUploadJobs(pw,1)
                jobs.start('original-target',lambda:True,lane='review')
                self.assertEqual(active_lease_targets(root),{'original-target'})
                owner.write_text(json.dumps({'pid':os.getpid(),'token':'different-owner'}))
                self.assertEqual(active_lease_targets(root),set())
                owner.write_text(json.dumps({'pid':os.getpid(),'token':'original-owner'}))
                jobs.pump();jobs.drain()
                self.assertEqual(active_lease_targets(root),set())

    def test_byte_budget_keeps_five_small_uploads_but_large_package_runs_alone(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5,byte_limit=32_000_000)
            def work():pw._sync(asyncio.sleep(.01));return True
            for i in range(5):self.assertTrue(jobs.start(str(i),work,zip_bytes=6_000_000))
            self.assertEqual(jobs.admitted_zip_bytes,30_000_000)
            jobs.pump();jobs.drain();self.assertEqual(jobs.admitted_zip_bytes,0)
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5,byte_limit=32_000_000)
            self.assertTrue(jobs.start('large',lambda:True,zip_bytes=40_000_000))
            self.assertFalse(jobs.can_accept(1));self.assertFalse(jobs.start('small',lambda:True,zip_bytes=1))
            jobs.pump();self.assertTrue(jobs.can_accept(6_000_000));jobs.drain()

    def test_waiting_seed_zip_keeps_next_capacity_ahead_of_smaller_ordinary_zip(self):
        from browser.web_card_pool import _seed_admission
        from playwright.sync_api import sync_playwright
        seed={'seed_fast_lane':True,'size':8_000_000}
        ordinary={'size':6_000_000}
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5,byte_limit=32_000_000)
            jobs.start('original-upload',lambda:False,zip_bytes=26_000_000);jobs.pump()
            self.assertTrue(jobs.can_accept(ordinary['size']))
            candidates=_seed_admission([seed,ordinary])
            self.assertIsNone(next((row for row in candidates if jobs.can_accept(row['size'])),None))
            stamp=jobs.retained['original-upload']
            jobs.release_observed({'pages':{'original-upload':{'evidence':{'snapshot':{
                'inspection_complete':True,'uploading':False,'checked_at':stamp+1}}}}})
            self.assertIs(next(row for row in candidates if jobs.can_accept(row['size'])),seed)
            jobs.drain()

    def test_large_packages_have_a_separate_concurrency_budget(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,4,byte_limit=48_000_000,large_limit=2,large_threshold=8_000_000)
            self.assertTrue(jobs.start('large1',lambda:True,zip_bytes=10_000_000))
            self.assertTrue(jobs.start('large2',lambda:True,zip_bytes=10_000_000))
            self.assertFalse(jobs.can_accept(9_000_000))
            self.assertFalse(jobs.start('large3',lambda:True,zip_bytes=9_000_000))
            self.assertTrue(jobs.start('small1',lambda:True,zip_bytes=6_000_000))
            self.assertTrue(jobs.can_accept(7_000_000))
            self.assertTrue(jobs.start('small2',lambda:True,zip_bytes=6_000_000))
            self.assertFalse(jobs.can_accept(1_000_000))
            jobs.pump();jobs.drain()
    def test_failed_upload_retains_its_byte_budget_until_original_stop_proof(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5,byte_limit=32_000_000)
            jobs.start('failed',lambda:False,zip_bytes=26_000_000);jobs.pump()
            self.assertFalse(jobs.can_accept(8_000_000));self.assertTrue(jobs.can_accept(6_000_000))
            stamp=jobs.retained['failed']
            jobs.release_observed({'pages':{'failed':{'evidence':{'snapshot':{
                'inspection_complete':True,'uploading':False,'checked_at':stamp+1}}}}})
            self.assertEqual(jobs.admitted_zip_bytes,0);self.assertTrue(jobs.can_accept(40_000_000));jobs.drain()

    def test_unknown_size_reserves_full_budget_and_never_bypasses_five_slots(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5,byte_limit=32_000_000)
            jobs.start('unknown',lambda:True)
            self.assertEqual(jobs.admitted_zip_bytes,32_000_000);self.assertFalse(jobs.can_accept(1));jobs.drain()
    def test_lane_admission_keeps_ended_native_wait_until_confirmed_release(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw);jobs.start('review-page',lambda:False,lane='review');jobs.pump()
            self.assertFalse(jobs.targets);self.assertEqual(jobs.pending_by_lane['review'],1)
            self.assertEqual(jobs.pending_targets_by_lane['review'],{'review-page'})
            jobs.release_observed({'pages':{'review-page':{'evidence':{'snapshot':{
                'inspection_complete':True,'uploading':False,'checked_at':jobs.retained['review-page']+1}}}}})
            self.assertEqual(jobs.pending_by_lane['review'],0);self.assertNotIn('review-page',jobs.lanes)

    def test_confirmed_replacement_releases_only_ended_original_upload_budget(self):
        jobs=OwnerUploadJobs(Mock(),5);jobs.retained={'old':100.0,'other':100.0}
        proof={'old_target_id':'old','new_target_id':'new','journal':'original/journal.json'}
        for report in ({'state':'checked','finished_at':101},
                       {'state':'pending','finished_at':99,'replaced':[proof]},
                       {'state':'checking','finished_at':101,'replaced':[proof]},
                       {'state':'checked','finished_at':101,'replaced':[{**proof,'new_target_id':'old'}]}):
            jobs.release_observed(report);self.assertEqual(len(jobs.retained),2)
        jobs.release_observed({'state':'pending','finished_at':101,'replaced':[proof]})
        self.assertEqual(jobs.retained,{'other':100.0})

    def test_finished_callback_keeps_budget_until_fresh_native_upload_end(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,1);jobs.start('own',lambda:False);jobs.pump()
            self.assertFalse(jobs.targets);self.assertFalse(jobs.available)
            finished=jobs.retained['own']
            def observed(stamp,uploading,complete=True):return {'pages':{'own':{'evidence':{'snapshot':{'checked_at':stamp,'uploading':uploading,'inspection_complete':complete}}}}}
            for h in [observed(finished-1,False),observed(finished+1,True),observed(finished+1,False,False)]:
                jobs.release_observed(h);self.assertFalse(jobs.available)
            jobs.release_observed(observed(finished+1,False));self.assertTrue(jobs.available)
            self.assertTrue(jobs.start('next',lambda:None));jobs.drain()
    def test_five_uploads_overlap_on_one_owner_thread_and_sixth_is_rejected(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5);active=0;peak=0;threads=set();finished=[]
            def upload(tid):
                nonlocal active,peak
                threads.add(threading.get_ident());active+=1;peak=max(peak,active)
                pw._sync(asyncio.sleep(.03))
                active-=1;finished.append(tid)
            for tid in range(5):self.assertTrue(jobs.start(str(tid),lambda tid=tid:upload(tid)))
            self.assertFalse(jobs.start('sixth',lambda:None))
            self.assertFalse(jobs.start('0',lambda:None))
            jobs.drain()
            self.assertEqual(peak,5);self.assertEqual(len(finished),5)
            self.assertEqual(threads,{threading.get_ident()});self.assertFalse(jobs.targets)
            self.assertEqual(len(jobs.reap()),5)
            self.assertFalse(jobs.start('after-close',lambda:None))

    def test_failure_is_retained_and_never_reruns_callback(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw);called=[]
            def uncertain():
                called.append('once');pw._sync(asyncio.sleep(.01));raise RuntimeError('unknown click receipt')
            jobs.start('target',uncertain);jobs.drain()
            self.assertEqual(called,['once']);self.assertIn('unknown click receipt',jobs.reap()[0]['error'])

    def test_upload_is_outside_send_lock_but_pause_stops_before_send(self):
        from browser.web_card_transport import submit_gpt_background, DeferredWeb
        held=False;stopped=False;session=Mock();session._pending_answer=None
        @contextmanager
        def lock():
            nonlocal held
            self.assertFalse(held);held=True
            try:yield
            finally:held=False
        def upload(*args,**kwargs):
            nonlocal stopped
            self.assertFalse(held);stopped=True;return True
        session.verify_settings.side_effect=lambda:self.assertFalse(held)
        with patch('web_gpt.core.upload_files',side_effect=upload), \
             patch('browser.web_card_transport.wait_gpt_upload_ready'), \
             patch('browser.web_card_transport.wait_gpt_upload_settled'), \
             patch('browser.web_card_transport.require_no_verification'):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session,'prompt',['one.zip'],stopping=lambda:stopped,
                                      lock_factory=lock,parallel_upload=True)
        self.assertIsNone(session._pending_answer)
        session.page.locator.assert_not_called()

    def test_idle_owner_pumps_scheduled_job_without_browser_call(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw);called=[]
            jobs.start('idle',lambda:called.append('started'))
            jobs.pump()
            self.assertEqual(called,['started'])
            self.assertFalse(jobs.targets)

    def test_send_readiness_does_not_hold_global_lock_and_rechecks_pause(self):
        from browser.web_card_transport import submit_gpt_background,DeferredWeb
        held=False;stopped=False;session=Mock();session._pending_answer=None
        @contextmanager
        def lock():
            nonlocal held
            self.assertFalse(held);held=True
            try:yield
            finally:held=False
        def waiting(*args):
            nonlocal stopped
            self.assertFalse(held);stopped=True
            return Mock(),None,None
        with patch('web_gpt.core.wait_prompt_box'),patch('web_gpt.core._composer'), \
             patch('browser.web_editor_input.replace'),patch('web_gpt.core._box_text',return_value='prompt'), \
             patch('web_gpt.core._wait_send_ready',side_effect=waiting):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session,'prompt',[],lock_factory=lock,stopping=lambda:stopped,parallel_upload=True)
        self.assertIsNone(session._pending_answer)
