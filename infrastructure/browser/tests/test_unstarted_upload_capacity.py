import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from browser import upload_trace
from browser.owner_upload_jobs import OwnerUploadJobs,unstarted_proof
from browser.web_card_pool import upload_budget_targets


class UnstartedProofTests(unittest.TestCase):
    def test_preflight_and_opted_in_writer_not_entered_are_explicit_proofs(self):
        self.assertIsNotNone(unstarted_proof({},page_touched=False))
        self.assertIsNotNone(unstarted_proof({},page_touched=True,local_file_paths=True))
        self.assertIsNone(unstarted_proof({},page_touched=True,local_file_paths=False))

    def test_file_assignment_intent_and_unknown_send_never_release(self):
        self.assertIsNone(unstarted_proof({'send_click_started':True},page_touched=False))
        for state in ['intent','written','unknown']:
            self.assertIsNone(unstarted_proof({'upload_diagnostic':{'local_file_write_state':state}},
                page_touched=False,local_file_paths=True))

    def test_review_preflight_returns_false_and_notifies_without_any_page_operation(self):
        from review.card_review_lane import ReviewLane
        from review import card_review_queue
        with tempfile.TemporaryDirectory() as folder:
            lane=ReviewLane.__new__(ReviewLane);lane.catalog=SimpleNamespace(path=Path(folder)/'catalog.sqlite')
            lane.config={};notify=Mock()
            with patch.object(card_review_queue,'enabled',return_value=False):
                result=lane.submit({}, {},0,Mock(),Mock(),lambda:False,on_unstarted=notify)
            self.assertIs(result,False);notify.assert_called_once()
            self.assertIs(notify.call_args.args[0]['native_file_write_started'],False)


class UnstartedCapacityTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        upload_trace.configure(self.root);self.addCleanup(upload_trace.reset)

    def run_case(self, callback_factory):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw,5,byte_limit=32000000)
            jobs.start('own',callback_factory(jobs),lane='cards',zip_bytes=54849064)
            while jobs.targets:pw._sync(asyncio.sleep(.001))
            return jobs

    def test_large_never_started_callback_releases_bytes_without_old_health_watermark(self):
        def callback(jobs):
            def run():
                self.assertTrue(jobs.note_unstarted('own',unstarted_proof({},page_touched=False)))
                return False
            return run
        jobs=self.run_case(callback)
        self.assertEqual(jobs.admitted_zip_bytes,0);self.assertFalse(jobs.retained);self.assertTrue(jobs.can_accept(1000000))
        self.assertNotIn('own',jobs.released)
        health={'pages':{'own':{'evidence':{'snapshot':{'inspection_complete':True,'uploading':True,'checked_at':1}}}}}
        self.assertIn('own',upload_budget_targets(jobs,health))
        events=[json.loads(l) for l in (self.root/upload_trace.EVENTS_FILE).read_text().splitlines()]
        self.assertEqual(events[-1]['kind'],'upload_capacity_released_unstarted')
        self.assertEqual(events[-1]['admitted_zip_bytes'],54849064)

    def test_plain_false_or_exception_keeps_unknown_capacity(self):
        for callback in [lambda jobs:lambda:False,lambda jobs:Mock(side_effect=RuntimeError('unknown'))]:
            jobs=self.run_case(callback);self.assertIn('own',jobs.retained);self.assertEqual(jobs.admitted_zip_bytes,54849064)

    def test_note_from_parent_or_other_target_has_no_effect(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            jobs=OwnerUploadJobs(pw);jobs.start('own',lambda:False)
            self.assertFalse(jobs.note_unstarted('own',unstarted_proof({},page_touched=False)))
            while jobs.targets:pw._sync(asyncio.sleep(.001))
            self.assertIn('own',jobs.retained)

    def test_later_exception_invalidates_unstarted_claim(self):
        def callback(jobs):
            def run():
                jobs.note_unstarted('own',unstarted_proof({},page_touched=False))
                raise RuntimeError('later evidence unknown')
            return run
        self.assertIn('own',self.run_case(callback).retained)

    def test_release_evidence_write_failure_retains_capacity(self):
        def callback(jobs):
            def run():
                jobs.note_unstarted('own',unstarted_proof({},page_touched=False));return False
            return run
        with patch.object(upload_trace,'append',side_effect=OSError('disk full')):
            jobs=self.run_case(callback)
        self.assertIn('own',jobs.retained);self.assertTrue(any('disk full' in row.get('error','') for row in jobs.reap()))
