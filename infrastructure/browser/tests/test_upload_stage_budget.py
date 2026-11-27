"""S003 upload stage-budget contract.

Pins the semantics that the recorded budget is an *independent per-stage* budget
rather than one total, that an expiring stage never refreshes its own deadline,
that an unreadable or unsettled upload cannot reach the send click, and that
tightening the parallel limit constrains only new claims.

Offline only: synthetic pages and a fake clock. No browser, no CDP, no outbound
request, no control write.
"""
import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

class FakeClock:
    """time-like object whose monotonic() advances only when the page waits.

    `max_waits` bounds the loop so a stage that refreshes its own deadline fails
    the test instead of spinning forever.
    """

    def __init__(self, start=1000.0, step=0.5, max_waits=64):
        self.now = start
        self.step = step
        self.waits = 0
        self.max_waits = max_waits

    def monotonic(self):
        return self.now

    def time(self):
        return self.now


def settled_page(visible=True):
    """Whole-page scope whose progress bar reads `visible`."""
    bar = Mock()
    bar.is_visible.side_effect = lambda: visible
    bars = SimpleNamespace(count=lambda: 1, nth=lambda i: bar)
    page = Mock()
    page.locator.return_value = bars
    page.wait_for_timeout.side_effect = lambda ms: tick(ms)
    return page, bar


def tick(ms):
    CLOCK.waits += 1
    if CLOCK.waits > CLOCK.max_waits:
        raise AssertionError('stage kept polling past its budget: the deadline was refreshed')
    CLOCK.now += ms / 1000


CLOCK = None


class StageBudget(unittest.TestCase):
    def setUp(self):
        global CLOCK
        CLOCK = FakeClock()
        _trace_temp(self)

    @contextmanager
    def reading(self, visible=True):
        page, bar = settled_page(visible)
        with patch('browser.web_card_transport.time', CLOCK), \
             patch('browser.web_card_transport.require_no_verification'), \
             patch('browser.web_card_transport.visible_notice', return_value=None):
            yield page, bar

    def test_expiring_settle_does_not_refresh_its_own_deadline(self):
        """A refreshed deadline would never fire; the poll count proves it did not."""
        from browser.web_card_transport import wait_gpt_upload_settled
        CLOCK.max_waits = 8
        with self.reading(visible=True) as (page, _bar):
            with self.assertRaises(RuntimeError) as caught:
                wait_gpt_upload_settled(page, 2000)
        self.assertIn('附件仍在上传', str(caught.exception))
        # 2000ms / 500ms polls = 4 waits, then the 5th read is already past due.
        self.assertEqual(CLOCK.waits, 4)
        self.assertEqual(CLOCK.now, 1002.0)

    def test_a_refreshing_settle_fails_bounded_instead_of_spinning(self):
        """Guard against a budget that re-arms itself: polling stops with a failure."""
        global CLOCK
        CLOCK = FakeClock(max_waits=3)
        from browser.web_card_transport import wait_gpt_upload_settled
        with self.reading(visible=True) as (page, _bar):
            with self.assertRaises(AssertionError) as caught:
                wait_gpt_upload_settled(page, 10 ** 9)
        self.assertIn('deadline was refreshed', str(caught.exception))

    def test_unreadable_settle_state_is_not_a_ready_receipt_and_never_returns_quietly(self):
        """Missing reads must surface as a failure, not as 'settled, go ahead and send'."""
        from browser.web_card_transport import wait_gpt_upload_settled
        page = Mock()
        page.locator.side_effect = RuntimeError('Locator.count: target page closed')
        with patch('browser.web_card_transport.time', CLOCK), \
             patch('browser.web_card_transport.require_no_verification'), \
             patch('browser.web_card_transport.visible_notice', return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                wait_gpt_upload_settled(page, 2000)
        self.assertIn('closed', str(caught.exception))
        self.assertEqual(CLOCK.waits, 0)

    def test_clear_settle_returns_at_first_read_without_spending_the_budget(self):
        from browser.web_card_transport import wait_gpt_upload_settled
        with self.reading(visible=False) as (_page, _bar):
            wait_gpt_upload_settled(_page, 180000)
        self.assertEqual(CLOCK.waits, 0)
        self.assertEqual(CLOCK.now, 1000.0)

    def test_one_knob_fans_out_to_independent_stage_budgets(self):
        """`upload_timeout` is spent once by the kernel and again by the page recheck.

        This is why the recorded 180s is not an upper bound on the whole upload.
        """
        from browser.web_card_transport import DeferredWeb, submit_gpt_background
        seen = {}
        session = Mock()
        session._pending_answer = None

        def upload(_page, _files, timeout=None):
            seen['attachment_and_scope'] = timeout
            paused['value'] = True          # stop right after the kernel stage
            return UPLOAD_OK

        def settle(_page, timeout, _stopping):
            seen['page_settle'] = timeout

        paused = {'value': False}
        with patch('web_gpt.core.upload_files_detailed', side_effect=upload), \
             patch('web_gpt.core.wait_prompt_box'), \
             patch('browser.web_card_transport.wait_gpt_upload_ready'), \
             patch('browser.web_card_transport.wait_gpt_upload_settled', side_effect=settle), \
             patch('browser.web_card_transport.require_no_verification'):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session, 'synthetic prompt', ['synthetic.zip'],
                                      upload_timeout=180000, stopping=lambda: paused['value'],
                                      lock_factory=lambda: nullcontext(), parallel_upload=True)
        self.assertEqual(seen, {'attachment_and_scope': 180000, 'page_settle': 180000})
        self.assertIsNone(session._pending_answer)

    def test_settle_failure_stops_before_prompt_fill_and_click(self):
        from browser.web_card_transport import submit_gpt_background
        session = Mock()
        session._pending_answer = None
        box = Mock()
        with patch('web_gpt.core.upload_files_detailed', return_value=UPLOAD_OK), \
             patch('web_gpt.core.wait_prompt_box', return_value=box) as prompt_box, \
             patch('browser.web_card_transport.wait_gpt_upload_ready'), \
             patch('browser.web_card_transport.wait_gpt_upload_settled',
                   side_effect=RuntimeError('附件仍在上传，未点击发送；稍后重试')), \
             patch('browser.web_card_transport.require_no_verification'):
            with self.assertRaises(RuntimeError):
                submit_gpt_background(session, 'synthetic prompt', ['synthetic.zip'],
                                      lock_factory=lambda: nullcontext(), parallel_upload=True)
        prompt_box.assert_not_called()
        box.fill.assert_not_called()
        box.evaluate.assert_not_called()
        self.assertIsNone(session._pending_answer)
        session.page.evaluate.assert_not_called()

    def test_lowering_the_upload_limit_gates_new_claims_without_cancelling_active_jobs(self):
        import asyncio
        from playwright.sync_api import sync_playwright
        from browser.owner_upload_jobs import OwnerUploadJobs
        with sync_playwright() as pw:
            jobs = OwnerUploadJobs(pw, 5)
            order = []

            def upload(tid):
                pw._sync(asyncio.sleep(.05))
                order.append(tid)
                return 'settled'

            for tid in ('0', '1', '2'):
                self.assertTrue(jobs.start(tid, lambda tid=tid: upload(tid)))
            self.assertEqual(jobs.targets, {'0', '1', '2'})
            jobs.limit = 2                       # tighten for new claims only
            self.assertFalse(jobs.available)
            self.assertEqual(jobs.targets, {'0', '1', '2'})   # nothing cancelled
            self.assertFalse(jobs.start('3', lambda: None))   # no new job beyond the limit
            jobs.drain()
            self.assertEqual(sorted(order), ['0', '1', '2'])
            self.assertEqual(len(jobs.reap()), 3)
            self.assertEqual(len(jobs.budget_targets), 3)     # retained still counts


if __name__ == '__main__':
    unittest.main()
