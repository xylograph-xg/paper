"""Pause races before page contact preserve review work and its unsent intent."""
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, nullcontext
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.catalog import Catalog
from review.card_review_lane import ReviewLane
from review import card_review_queue as queue
from core.services import atomic_json


class ReviewPauseBoundary(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {'catalog_path': str(self.root/'catalog.sqlite3'),
            'card_review': {'enabled': True, 'parallel_jobs': 20},
            'web_cards': {'enabled': True, 'upload_settle_timeout_seconds': 180}}
        self.catalog = Catalog(self.config['catalog_path']); queue.install(self.catalog)
        self.lane = ReviewLane.__new__(ReviewLane)
        self.lane.config = self.config; self.lane.catalog = self.catalog
        self.folder = self.root/'review'; self.folder.mkdir()
        self.path = self.folder/'attempt.json'
        self.prompt = 'Synthetic review input for pause-only tests'
        (self.folder/'prompt-actual.txt').write_text(self.prompt)
        atomic_json(self.folder/'packet.json', {'review_images_version': 1})
        self.packet = {'input_hashes': {'source.pdf': 'source-sha'},
            'actual_prompt_sha256': 'actual-prompt-sha',
            'upload_bundle': {'zip_path': str(self.folder/'synthetic.zip')}}
        with self.catalog.connect() as db:
            db.execute('INSERT INTO card_review_jobs '
                '(id,paper_id,card_sha256,source_sha256,title,state,folder,updated) '
                'VALUES(?,?,?,?,?,?,?,?)',
                ('review-id', 'paper-id', 'card-sha', 'source-sha', 'Synthetic',
                 'ready', str(self.folder), 'synthetic-timestamp'))
        self.entries = {'target': {'state': 'ready_blank'}}
        self.page = Mock(); self.page.url = 'https://chatgpt.com/'
        self.router = Mock(); self.router.choose.return_value = 'chatgpt'

    def pause(self):
        atomic_json(self.root/'card-review-control.json', {'paused_by_user': True})

    def state(self):
        with self.catalog.connect() as db:
            return db.execute('SELECT state FROM card_review_jobs WHERE id=?',
                              ('review-id',)).fetchone()['state']

    def dependencies(self):
        stack = ExitStack()
        stack.enter_context(patch('review.card_review_queue.current', return_value=self.packet))
        stack.enter_context(patch('review.card_review_queue.check_packet', return_value=self.packet))
        stack.enter_context(patch('browser.web_card_pool.record_channel_failure'))
        stack.enter_context(patch('browser.reusable_home.snapshot_page',return_value={
            'inspection_complete':True,'url':'https://chatgpt.com/c/saved','draft':'',
            'composer_available':True}))
        return stack

    def submit(self, lock_factory=None, stopping=None):
        return self.lane.submit({'target': self.page}, self.entries, 0, self.router,
            lock_factory or (lambda **kwargs: nullcontext()), stopping or (lambda: False),
            allowed_targets={'target'}, job_id='review-id')

    def assert_no_page_contact(self):
        self.page.goto.assert_not_called()
        self.page.locator.assert_not_called()
        self.page.close.assert_not_called()

    def assert_ready_without_live_receipt(self):
        self.assertEqual(self.state(), 'ready')
        self.assertEqual(self.entries['target'], {'state': 'ready_blank'})
        self.assertFalse(self.path.exists())
        self.assert_no_page_contact()

    def test_already_paused_does_not_create_intent_or_touch_page(self):
        self.pause()
        with patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.submit())
        send.assert_not_called(); self.router.choose.assert_not_called()
        self.assert_ready_without_live_receipt()
        self.assertEqual(list(self.folder.rglob('attempt.json')), [])

    def test_pause_between_initial_check_and_claim_keeps_ready_task(self):
        def choose():
            self.pause(); return 'chatgpt'
        self.router.choose.side_effect = choose
        with self.dependencies(), patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.submit())
        send.assert_not_called(); self.assert_ready_without_live_receipt()

    def test_pause_at_submission_lock_archives_only_unsent_intent(self):
        @contextmanager
        def paused_lock(**kwargs):
            self.assertTrue(self.path.exists())
            self.pause(); yield
        with self.dependencies(), patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.submit(paused_lock))
        send.assert_not_called(); self.assert_ready_without_live_receipt()
        archives = list(self.folder.rglob('attempt.json'))
        self.assertEqual(len(archives), 1)
        receipt = json.loads(archives[0].read_text())
        self.assertEqual(receipt['state'], 'not_sent')
        self.assertFalse(receipt['send_click_started'])
        self.assertEqual(receipt['target_id'], 'target')
        self.assertEqual((self.folder/'prompt-actual.txt').read_text(), self.prompt)

    def test_stop_at_submission_lock_keeps_task_and_unsent_evidence(self):
        stop = False
        @contextmanager
        def stopped_lock(**kwargs):
            nonlocal stop
            stop = True; yield
        with self.dependencies(), patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.submit(stopped_lock, stopping=lambda: stop))
        send.assert_not_called(); self.assert_ready_without_live_receipt()
        archives = list(self.folder.rglob('attempt.json'))
        self.assertEqual(len(archives), 1)
        self.assertFalse(json.loads(archives[0].read_text())['send_click_started'])

    def test_explicit_resume_can_claim_same_ready_job_and_preserves_original_archive(self):
        with self.catalog.connect() as db:
            arrival = dict(db.execute("SELECT * FROM shared_workflow_arrivals WHERE lane='review' AND job_id='review-id'").fetchone())
        @contextmanager
        def paused_lock(**kwargs):
            self.pause(); yield
        with self.dependencies(), patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.submit(paused_lock))
        send.assert_not_called()
        archived = next(self.folder.rglob('attempt.json')); original = archived.read_bytes()
        (self.root/'card-review-control.json').unlink()
        def resumed_send(session, prompt, files, **options):
            options['on_before_send']()
            self.page.url = 'https://chatgpt.com/c/resumed-original-job'
            return 0
        with self.dependencies(), \
                patch('browser.shared_window_owner.require_reusable'), \
                patch('web_gpt.core.wait_prompt_box', return_value=Mock()), \
                patch('browser.gpt_model_policy.configure_session',
                      return_value=SimpleNamespace(settings={'model': 'GPT-6', 'effort': 'High'})), \
                patch('browser.web_card_transport.submit_gpt_background', side_effect=resumed_send) as send:
            self.assertTrue(self.submit())
        send.assert_called_once(); self.assertEqual(self.state(), 'submitted')
        self.assertTrue(json.loads(self.path.read_text())['send_click_started'])
        self.assertEqual(archived.read_bytes(), original)
        with self.catalog.connect() as db:
            self.assertEqual(dict(db.execute("SELECT * FROM shared_workflow_arrivals WHERE lane='review' AND job_id='review-id'").fetchone()), arrival)

    def test_pause_after_page_contact_keeps_live_intent_for_inspection(self):
        from browser.web_card_transport import DeferredWeb
        def upload_paused(session, prompt, files, **options):
            self.pause(); raise DeferredWeb('核验已暂停，保留上传中的原页面')
        with self.dependencies(), \
                patch('browser.shared_window_owner.require_reusable'), \
                patch('web_gpt.core.wait_prompt_box', return_value=Mock()), \
                patch('browser.gpt_model_policy.configure_session',
                      return_value=SimpleNamespace(settings={'model': 'GPT-6', 'effort': 'High'})), \
                patch('browser.web_card_transport.submit_gpt_background', side_effect=upload_paused):
            self.assertFalse(self.submit())
        self.page.goto.assert_called_once()
        self.assertEqual(self.state(), 'needs_user')
        self.assertEqual(self.entries['target']['state'], 'needs_inspection')
        receipt = json.loads(self.path.read_text())
        self.assertEqual(receipt['state'], 'not_sent'); self.assertFalse(receipt['send_click_started'])
        self.assertEqual(list(self.folder.rglob('attempt.json')), [self.path])
        self.page.close.assert_not_called()

    def test_changed_input_is_kept_for_inspection_and_does_not_become_pause_retry(self):
        with patch('review.card_review_queue.current', side_effect=ValueError('原卡片已变化')), \
                patch('browser.web_card_pool.record_channel_failure'), \
                patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.submit())
        self.assertEqual(self.state(), 'needs_user')
        self.assertEqual(self.entries['target']['state'], 'ready_blank')
        self.assert_no_page_contact(); send.assert_not_called()

    def test_uncertain_send_keeps_original_receipt_and_blocks_repeat(self):
        def send(session, prompt, files, **options):
            options['on_before_send'](); raise RuntimeError('Unknown receipt after click')
        with self.dependencies(), \
                patch('browser.shared_window_owner.require_reusable'), \
                patch('web_gpt.core.wait_prompt_box', return_value=Mock()), \
                patch('browser.gpt_model_policy.configure_session',
                      return_value=SimpleNamespace(settings={'model': 'GPT-6', 'effort': 'High'})), \
                patch('browser.web_card_transport.submit_gpt_background', side_effect=send):
            self.assertFalse(self.submit())
        receipt = self.path.read_bytes()
        self.assertTrue(json.loads(receipt)['send_click_started'])
        self.assertEqual(json.loads(receipt)['state'], 'needs_inspection')
        self.assertEqual(self.state(), 'needs_user')
        self.assertEqual(self.entries['target']['state'], 'needs_inspection')
        with patch('browser.web_card_transport.submit_gpt_background') as repeated:
            self.assertFalse(self.submit())
        repeated.assert_not_called(); self.assertEqual(self.path.read_bytes(), receipt)
        self.page.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
