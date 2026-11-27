import asyncio
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from browser.owner_upload_jobs import OwnerUploadJobs
from browser.owner_work_lane import OwnerWorkLane


class IndependentUploadLaneTests(unittest.TestCase):
    def test_pause_arriving_during_final_database_guard_never_clicks_send(self):
        from contextlib import nullcontext
        from browser.web_card_transport import submit_gpt_background,DeferredWeb
        stopped=False;session=Mock();session._pending_answer=None;button=Mock()
        def final_guard():
            nonlocal stopped
            stopped=True
        with patch('web_gpt.core.wait_prompt_box'),patch('web_gpt.core._composer'), \
                patch('browser.web_editor_input.replace'),patch('web_gpt.core._box_text',return_value='prompt'), \
                patch('web_gpt.core._wait_send_ready',return_value=(button,None,None)), \
                patch('web_gpt.core._button_enabled',return_value=True),patch('web_gpt.core.count_answers',return_value=0):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session,'prompt',[],on_before_send=final_guard,
                    stopping=lambda:stopped,parallel_upload=True,lock_factory=nullcontext)
        button.evaluate.assert_not_called();self.assertIsNone(session._pending_answer)

    def test_parallel_preflight_and_send_receipt_wait_do_not_hold_global_lock(self):
        from contextlib import contextmanager
        from playwright.sync_api import sync_playwright
        from browser.web_card_transport import submit_gpt_background
        with sync_playwright() as pw:
            held=False;verifying=0;peak=0;sent=[]
            @contextmanager
            def lock():
                nonlocal held
                self.assertFalse(held);held=True
                try:yield
                finally:held=False
            def verify():
                nonlocal verifying,peak
                self.assertFalse(held);verifying+=1;peak=max(peak,verifying)
                pw._sync(asyncio.sleep(.02));verifying-=1
            def acknowledgement(*args):
                self.assertFalse(held);pw._sync(asyncio.sleep(.02));return True
            jobs=OwnerUploadJobs(pw)
            sessions=[]
            for index in range(5):
                session=Mock();session._pending_answer=None;session.page.url='https://chatgpt.com/c/'+str(index)
                session.verify_settings.side_effect=verify
                users=Mock();users.count.side_effect=[0,1];session.page.locator.return_value=users
                sessions.append(session)
            button=Mock()
            def click(*args,**kwargs):
                self.assertTrue(held);self.assertEqual(kwargs.get('timeout'),3000)
            button.evaluate.side_effect=click
            with patch('web_gpt.core.wait_prompt_box'),patch('web_gpt.core._composer'), \
                    patch('browser.web_editor_input.replace'),patch('web_gpt.core._box_text',return_value='prompt'), \
                    patch('web_gpt.core._wait_send_ready',return_value=(button,None,None)), \
                    patch('web_gpt.core._button_enabled',return_value=True),patch('web_gpt.core.count_answers',return_value=0), \
                    patch('web_gpt.core._sent',side_effect=acknowledgement), \
                    patch('browser.web_message_text.read_user_text',return_value='prompt'):
                def submit(session):
                    submit_gpt_background(session,'prompt',[],parallel_upload=True,lock_factory=lock)
                    sent.append(session);return True
                for index,session in enumerate(sessions):jobs.start(str(index),lambda session=session:submit(session))
                jobs.drain()
            self.assertEqual(peak,5);self.assertEqual(len(sent),5)
            self.assertFalse([r for r in jobs.reap() if r.get('error')])

    def test_twenty_jobs_refill_five_slots_on_the_same_owner_thread(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5);pending=list(range(20));finished=[];threads=set()
            running=0;peak=0
            def upload(tid):
                nonlocal running,peak
                threads.add(threading.get_ident());running+=1;peak=max(peak,running)
                pw._sync(asyncio.sleep(.025))
                running-=1;finished.append(tid);return True
            def fill():
                while pending and jobs.available:
                    tid=pending.pop(0)
                    self.assertTrue(jobs.start(str(tid),lambda tid=tid:upload(tid),lane='cards'))
            lane=OwnerWorkLane(pw,fill,interval=.005);lane.start()
            deadline=time.monotonic()+3
            while len(finished)<20 and time.monotonic()<deadline:pw._sync(asyncio.sleep(.01))
            lane.drain();jobs.drain()
            self.assertEqual(sorted(finished),list(range(20)))
            self.assertEqual(peak,5);self.assertEqual(threads,{threading.get_ident()})
            self.assertFalse(jobs.retained);self.assertFalse(lane.errors)

    def test_missing_capacity_requires_two_complete_same_epoch_inventories(self):
        jobs=OwnerUploadJobs(Mock());jobs.retained={'old':10};jobs.lanes={'old':'review'}
        archive=Mock()
        def check(at,epoch='new',complete=True,targets=()):
            jobs.release_missing(set(targets),complete=complete,epoch=epoch,archive=archive,at=at)
        check(100);check(129);self.assertIn('old',jobs.retained)
        check(130,epoch='changed');check(159,epoch='changed');archive.assert_not_called()
        check(160,epoch='changed',complete=False);check(161,epoch='changed')
        check(191,epoch='changed',targets=('old',));check(200,epoch='changed')
        archive.assert_not_called();check(230,epoch='changed')
        self.assertFalse(jobs.retained);self.assertFalse(jobs.lanes)
        proof=archive.call_args.args[0]
        self.assertEqual(proof['action'],'release_upload_capacity_only')
        self.assertTrue(proof['original_request_unchanged'])

    def test_capacity_archive_failure_keeps_original_reservation(self):
        jobs=OwnerUploadJobs(Mock());jobs.retained={'old':10};archive=Mock(side_effect=OSError('disk'))
        jobs.release_missing(set(),complete=True,epoch='e',archive=archive,at=100)
        with self.assertRaises(OSError):jobs.release_missing(set(),complete=True,epoch='e',archive=archive,at=130)
        self.assertEqual(jobs.retained,{'old':10})

    def test_old_native_snapshot_does_not_reclaim_successfully_released_credit(self):
        from browser.web_card_pool import upload_budget_targets
        jobs=OwnerUploadJobs(Mock());jobs.released={'done':200}
        def health(at):return {'pages':{'done':{'evidence':{'snapshot':{
            'inspection_complete':True,'uploading':True,'checked_at':at}}}}}
        self.assertFalse(upload_budget_targets(jobs,health(199)))
        self.assertEqual(upload_budget_targets(jobs,health(201)),{'done'})


class IndependentCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_answer_is_saved_while_submission_lock_is_unavailable(self):
        from browser.web_page_observer import PageObserver
        from browser.web_card_pool import USER
        from web_gpt.core import ANSWER
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'attempt.json'
            prompt='web-card-12345678-1234-1234-1234-123456789abc-input'
            url='https://chatgpt.com/c/original';raw='{"answer":"original"}'
            a={'state':'submission_started','created':1,'target_id':'own',
               'send_click_started':True,'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
            path.write_text(json.dumps(a));(root/'prompt-actual.txt').write_text(prompt)
            users=Mock();users.count=AsyncMock(return_value=1);users.first.evaluate=AsyncMock(return_value=[prompt,prompt])
            answers=Mock();answers.last.evaluate=AsyncMock(return_value=[raw,raw]);answers.last.get_attribute=AsyncMock(return_value='false')
            page=Mock(url=url);page.evaluate=AsyncMock(return_value={'login':False,'streaming':False,'complete':True,'answers':1})
            page.locator.side_effect=lambda selector:{USER:users,ANSWER:answers}[selector]
            observer=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()));observer.pages={'own':page}
            with patch('web_gpt.submission.submission_lock',side_effect=AssertionError('collection used send lock')) as lock:
                result=await observer.inspect('own',page,[url],{'own':(path,a)})
            lock.assert_not_called();self.assertTrue(result['saved'])
            self.assertEqual((root/'response-raw.txt').read_text(),raw)
            self.assertEqual(json.loads(path.read_text())['state'],'response_saved')


class SubmittedReceiptTests(unittest.TestCase):
    def test_late_send_ack_preserves_saved_answer(self):
        from browser.web_card_transport import commit_submitted
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'attempt.json';a={'state':'submission_started','created':1,'target_id':'own','actual_prompt_sha256':'p'}
            raw=b'original answer';(path.parent/'response-raw.txt').write_bytes(raw)
            saved={**a,'state':'response_saved','conversation_url':'https://chatgpt.com/c/own',
                'raw_sha256':hashlib.sha256(raw).hexdigest(),'observed_complete_at':2}
            path.write_text(json.dumps(saved))
            commit_submitted(path,a,prior_count=0,conversation_url=saved['conversation_url'])
            current=json.loads(path.read_text());self.assertEqual(current['state'],'response_saved')
            self.assertEqual(current['raw_sha256'],saved['raw_sha256'])
            before=path.read_bytes();a['created']=0
            with self.assertRaises(ValueError):commit_submitted(path,a,prior_count=0,conversation_url=saved['conversation_url'])
            self.assertEqual(path.read_bytes(),before)

    def test_ack_failure_can_preserve_saved_answer_without_inventing_prior_count(self):
        from browser.web_card_transport import commit_submitted
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'attempt.json';raw=b'original complete answer'
            a={'state':'submission_started','created':1,'target_id':'own','actual_prompt_sha256':'p'}
            saved={**a,'state':'response_saved','conversation_url':'https://chatgpt.com/c/own',
                   'raw_sha256':hashlib.sha256(raw).hexdigest()}
            (path.parent/'response-raw.txt').write_bytes(raw);path.write_text(json.dumps(saved))
            commit_submitted(path,a,prior_count=None,conversation_url=saved['conversation_url'])
            current=json.loads(path.read_text());self.assertEqual(current['state'],'response_saved')
            self.assertNotIn('prior_count',current)
            path.write_text(json.dumps({**a,'state':'submission_started'}));before=path.read_bytes()
            with self.assertRaises(ValueError):commit_submitted(path,a,prior_count=None,conversation_url=saved['conversation_url'])
            self.assertEqual(path.read_bytes(),before)
