"""Shared-lane pause and submission boundaries, using only temporary controls."""
import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from review import card_review_queue; from cards import web_card_service
from core.services import atomic_json
from browser.shared_browser_window import WindowIsolationError
from browser.shared_page_dispatch import dispatch
from cards.web_card_retry import reset_unsent_page
from browser.web_card_transport import DeferredWeb, submit_gpt_background
from review.tests import test_card_review_lane as review_fixtures

import tempfile
from core.api import paths__WorkspacePath as Path
from browser import upload_trace

UPLOAD_OK = {'ok': True, 'receipt_sufficient': True, 'failure_kind': None,
             'retryable_upload': False, 'stage': 'full_page_recheck', 'stages': [],
             'bundle': {}, 'settle': {}, 'attachment': {}}
UPLOAD_FAIL = {'ok': False, 'receipt_sufficient': False, 'failure_kind': 'write_failed',
               'retryable_upload': True, 'stage': 'attachment_write', 'stages': [],
               'bundle': {}, 'settle': {}, 'attachment': {}}

def _trace_temp(test):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    test.addCleanup(upload_trace.reset)
    upload_trace.configure(Path(folder.name))

class SharedLaneControls(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {
            'catalog_path': str(self.root / 'catalog.sqlite'),
            'web_cards': {'enabled': True, 'shared_window': {'enabled': True, 'slot_count': 20}},
            'card_review': {'enabled': True, 'parallel_jobs': 4},
        }

    def pause(self, cards=False, review=False):
        atomic_json(self.root / 'web-card-control.json', {'paused_by_user': cards})
        atomic_json(self.root / 'card-review-control.json', {'paused_by_user': review})

    def test_cards_pause_keeps_shared_review_and_owner_enabled(self):
        self.pause(cards=True)
        before = (self.root / 'web-card-control.json').read_bytes()
        self.assertFalse(web_card_service.enabled(self.config))
        self.assertTrue(card_review_queue.enabled(self.config))
        self.assertTrue(web_card_service.owner_enabled(self.config))
        self.assertEqual((self.root / 'web-card-control.json').read_bytes(), before)

    def test_review_pause_keeps_cards_and_owner_enabled(self):
        self.pause(review=True)
        self.assertTrue(web_card_service.enabled(self.config))
        self.assertFalse(card_review_queue.enabled(self.config))
        self.assertTrue(web_card_service.owner_enabled(self.config))

    def test_both_paused_lanes_do_not_keep_owner_enabled(self):
        self.pause(cards=True, review=True)
        self.assertFalse(web_card_service.enabled(self.config))
        self.assertFalse(card_review_queue.enabled(self.config))
        self.assertFalse(web_card_service.owner_enabled(self.config))

    def test_legacy_review_still_honors_master_cards_pause(self):
        self.config['web_cards']['shared_window']['enabled'] = False
        self.pause(cards=True)
        self.assertFalse(card_review_queue.enabled(self.config))
        self.assertFalse(web_card_service.owner_enabled(self.config))

    def test_stopping_cards_preserves_shared_review_control_and_resident_owner(self):
        self.pause()
        review_before = (self.root / 'card-review-control.json').read_bytes()
        with patch.object(web_card_service, 'status', return_value={'alive': True, 'pid': 12345, 'token': 'synthetic'}):
            web_card_service.stop(self.config)
        self.assertTrue(json.loads((self.root / 'web-card-control.json').read_text())['paused_by_user'])
        self.assertEqual((self.root / 'card-review-control.json').read_bytes(), review_before)
        self.assertTrue(card_review_queue.enabled(self.config))
        self.assertTrue(web_card_service.owner_enabled(self.config))
        self.assertFalse((self.root / 'web-card-stop.json').exists())

    def test_stopping_last_active_lane_requests_owner_stop_with_original_token(self):
        self.pause(review=True)
        with patch.object(web_card_service, 'status', return_value={'alive': True, 'pid': 12345, 'token': 'synthetic'}):
            web_card_service.stop(self.config)
        self.assertFalse(web_card_service.owner_enabled(self.config))
        self.assertEqual(json.loads((self.root / 'web-card-stop.json').read_text()),
                         {'pid': 12345, 'token': 'synthetic'})

    def pages_with_activity(self):
        entries = {f't{i:02d}': {'state': 'ready_blank', 'slot': i} for i in range(20)}
        entries['t00'].update(state='busy', kind='cards')
        entries['t01'].update(state='busy', kind='cards')
        entries['t02'].update(state='busy', kind='review')
        entries['t03'].update(state='busy', kind='review')
        entries['t04']['state'] = 'needs_inspection'
        return entries

    def test_cards_pause_lends_idle_slots_but_preserves_cards_activity_and_unknown_page(self):
        entries = self.pages_with_activity()
        before = copy.deepcopy(entries)
        plan = dispatch(entries, entries, cards_allowed=False, review_limit=20)
        self.assertEqual(plan['card_targets'], ['t00', 't01'])
        self.assertEqual(plan['card_ready'], [])
        self.assertEqual(len(plan['review_ready']), 15)
        self.assertTrue({'t02', 't03'}.issubset(plan['review_targets']))
        self.assertEqual(plan['protected_targets'], ['t04'])
        self.assertFalse(set(plan['card_targets']) & set(plan['review_targets']))
        self.assertEqual(entries, before)

    def test_review_pause_lends_idle_slots_but_preserves_reviews_activity_and_unknown_page(self):
        entries = self.pages_with_activity()
        before = copy.deepcopy(entries)
        plan = dispatch(entries, entries, review_allowed=False)
        self.assertEqual(plan['review_targets'], ['t02', 't03'])
        self.assertEqual(plan['review_ready'], [])
        self.assertEqual(len(plan['card_ready']), 15)
        self.assertTrue({'t00', 't01'}.issubset(plan['card_targets']))
        self.assertEqual(plan['protected_targets'], ['t04'])
        self.assertFalse(set(plan['card_targets']) & set(plan['review_targets']))
        self.assertEqual(entries, before)


class SharedSubmissionGuards(unittest.TestCase):
    def setUp(self):
        _trace_temp(self)
    def test_initial_pause_prevents_settings_upload_prompt_and_click(self):
        page = Mock()
        session = SimpleNamespace(_pending_answer=None, page=page, verify_settings=Mock())
        before_send = Mock()
        with (patch('web_gpt.core.upload_files_detailed', return_value=UPLOAD_OK) as upload,
              patch('web_gpt.core.wait_prompt_box') as prompt_box,
              patch('browser.web_card_transport.wait_gpt_upload_ready') as upload_ready):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session, 'synthetic prompt', ['synthetic.zip'],
                                      on_before_send=before_send, stopping=lambda: True,
                                      lock_factory=lambda: nullcontext())
        session.verify_settings.assert_not_called()
        upload.assert_not_called()
        upload_ready.assert_not_called()
        prompt_box.assert_not_called()
        page.locator.assert_not_called()
        page.evaluate.assert_not_called()
        before_send.assert_not_called()
        self.assertIsNone(session._pending_answer)

    def test_pause_during_attachment_entry_wait_prevents_upload_and_prompt(self):
        page = Mock()
        session = SimpleNamespace(_pending_answer=None, page=page, verify_settings=Mock())
        paused = {'value': False}

        def pause_while_waiting(current_page):
            self.assertIs(current_page, page)
            paused['value'] = True

        with (patch('web_gpt.core.upload_files_detailed', return_value=UPLOAD_OK) as upload,
              patch('web_gpt.core.wait_prompt_box') as prompt_box,
              patch('browser.web_card_transport.wait_gpt_upload_ready', side_effect=pause_while_waiting)):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session, 'synthetic prompt', ['synthetic.zip'],
                                      stopping=lambda: paused['value'], lock_factory=lambda: nullcontext())
        session.verify_settings.assert_called_once()
        upload.assert_not_called()
        prompt_box.assert_not_called()
        page.evaluate.assert_not_called()
        self.assertIsNone(session._pending_answer)

    def test_diagnostic_guard_rejection_after_runtime_error_does_not_read_other_window_notice(self):
        from browser.web_card_pool import record_channel_failure
        page = Mock()
        router = Mock()
        guard = Mock(side_effect=WindowIsolationError('页面已移出专用窗口'))
        with patch('browser.upload_quota.visible_notice') as notice:
            record_channel_failure(router, RuntimeError('合成普通操作失败'), page, page_guard=guard)
        guard.assert_called_once()
        notice.assert_not_called()
        page.locator.assert_not_called()
        page.evaluate.assert_not_called()
        router.block.assert_not_called()

    def test_transport_initial_window_rejection_prevents_all_dom_and_send_operations(self):
        page = Mock()
        box = Mock()
        session = SimpleNamespace(_pending_answer=None, page=page, verify_settings=Mock())
        before_send = Mock()
        guard = Mock(side_effect=WindowIsolationError('页面不在专用窗口'))
        with (patch('web_gpt.core.upload_files_detailed', return_value=UPLOAD_OK) as upload,
              patch('web_gpt.core.wait_prompt_box', return_value=box) as prompt_box,
              patch('browser.web_card_transport.wait_gpt_upload_ready') as upload_ready):
            with self.assertRaises(WindowIsolationError):
                submit_gpt_background(session, 'synthetic prompt', ['synthetic.zip'],
                                      on_before_send=before_send, page_guard=guard,
                                      lock_factory=lambda: nullcontext())
        session.verify_settings.assert_not_called()
        upload.assert_not_called()
        upload_ready.assert_not_called()
        prompt_box.assert_not_called()
        box.fill.assert_not_called()
        page.locator.assert_not_called()
        page.evaluate.assert_not_called()
        before_send.assert_not_called()
        self.assertIsNone(session._pending_answer)

    def test_window_move_while_attachment_entry_waits_prevents_upload_or_prompt_fill(self):
        page = Mock()
        box = Mock()
        session = SimpleNamespace(_pending_answer=None, page=page, verify_settings=Mock())
        guard = Mock(side_effect=[None, WindowIsolationError('页面已移出专用窗口')])
        with (patch('web_gpt.core.upload_files_detailed', return_value=UPLOAD_OK) as upload,
              patch('web_gpt.core.wait_prompt_box', return_value=box) as prompt_box,
              patch('browser.web_card_transport.wait_gpt_upload_ready')):
            with self.assertRaises(WindowIsolationError):
                submit_gpt_background(session, 'synthetic prompt', ['synthetic.zip'],
                                      page_guard=guard, lock_factory=lambda: nullcontext())
        self.assertEqual(guard.call_count, 2)
        upload.assert_not_called()
        prompt_box.assert_not_called()
        box.fill.assert_not_called()
        page.evaluate.assert_not_called()
        self.assertIsNone(session._pending_answer)

    def test_retry_window_rejection_preserves_original_entry_and_never_navigates(self):
        page = Mock()
        page.url = 'https://chatgpt.com/'
        empty = Mock()
        empty.count.return_value = 0
        page.locator.return_value = empty
        entries = {'target': {'state': 'needs_inspection', 'active_paper_id': 'paper'}}
        before = copy.deepcopy(entries)
        records = [(Path('synthetic-attempt.json'), {'state': 'not_sent', 'send_click_started': False,
                                                   'target_id': 'target'})]
        guard = Mock(side_effect=WindowIsolationError('页面已移出专用窗口'))
        with (patch('browser.web_card_transport.require_no_verification'),
              patch('web_gpt.submission.submission_lock', return_value=nullcontext())):
            with self.assertRaises(WindowIsolationError):
                reset_unsent_page('paper', records, {'target': page}, entries, page_guard=guard)
        guard.assert_called_once_with('target')
        page.goto.assert_not_called()
        page.close.assert_not_called()
        self.assertEqual(entries, before)

    def test_unknown_retry_receipt_never_inspects_or_navigates_original_page(self):
        page = Mock()
        entries = {'target': {'state': 'needs_inspection'}}
        before = copy.deepcopy(entries)
        records = [(Path('synthetic-attempt.json'), {'state': 'needs_inspection', 'send_click_started': True,
                                                   'target_id': 'target'})]
        guard = Mock()
        reset_unsent_page('paper', records, {'target': page}, entries, page_guard=guard)
        page.locator.assert_not_called()
        page.goto.assert_not_called()
        page.close.assert_not_called()
        guard.assert_not_called()
        self.assertEqual(entries, before)


class SharedReviewClaimLimits(unittest.TestCase):
    def setUp(self):
        self.fixture = review_fixtures.ReviewLaneTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def assert_not_claimed(self, **options):
        fixture = self.fixture
        with patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(fixture.lane.submit(
                {'target': fixture.page}, fixture.entries, options.pop('active', 0), fixture.router,
                lambda **kw: nullcontext(), lambda: False, **options))
        self.assertEqual(fixture.state(), 'ready')
        self.assertFalse((Path(fixture.job['folder']) / 'attempt.json').exists())
        fixture.page.goto.assert_not_called()
        fixture.page.close.assert_not_called()
        send.assert_not_called()

    def test_empty_assigned_target_set_cannot_claim_an_otherwise_ready_review_job(self):
        self.assert_not_claimed(allowed_targets=set())

    def test_shared_review_budget_full_cannot_claim_below_review_menu_limit(self):
        self.assert_not_claimed(allowed_targets={'target'}, parallel_limit=2, active=2)

    def test_zero_shared_budget_cannot_claim_or_navigate(self):
        self.assert_not_claimed(allowed_targets={'target'}, parallel_limit=0)


if __name__ == '__main__':
    unittest.main()
