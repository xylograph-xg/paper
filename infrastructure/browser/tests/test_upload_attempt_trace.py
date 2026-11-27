"""S001 upload attribution contract: one durable ID per upload, honest kinds.

Offline only. Synthetic pages, temporary evidence directories. No browser, no
CDP, no upload, no send, no control write and no signed URL, header or body.
"""
import json
import tempfile
import unittest
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from browser import upload_trace
from browser.web_card_transport import (DeferredWeb, UploadStageFailure, submit_gpt_background)

OK_DETAIL = {'ok': True, 'receipt_sufficient': True, 'stage': 'full_page_recheck',
             'failure_kind': None, 'retryable_upload': False, 'stages': [], 'bundle': {},
             'settle': {'result': 'settled'}, 'attachment': {'confirmed_new': True}}


def detail(**changes):
    merged = {key: (dict(value) if isinstance(value, dict) else value) for key, value in OK_DETAIL.items()}
    merged.update(changes)
    return merged


FAILED_DETAIL = detail(ok=False, receipt_sufficient=False, stage='progress_settle',
                       failure_kind='settle_timeout', retryable_upload=True)


def session(page=None):
    return SimpleNamespace(_pending_answer=None, page=page or Mock(), verify_settings=lambda: None)


def records(root):
    path = Path(root) / upload_trace.EVENTS_FILE
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TraceContract(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.addCleanup(upload_trace.reset)
        upload_trace.configure(self.root)

    def test_intent_is_written_before_the_page_is_touched(self):
        page = Mock()
        context = {'lane': 'review', 'job_id': 'job-1', 'paper_id': 'paper-1', 'target_id': 'T1'}
        with (patch('web_gpt.submission.submission_lock', return_value=nullcontext()),
              patch('browser.web_card_transport.wait_gpt_upload_ready'),
              patch('browser.web_card_transport.wait_gpt_upload_settled'),
              patch('web_gpt.core.upload_files_detailed', return_value=OK_DETAIL) as upload):
            with self.assertRaises(RuntimeError):
                submit_gpt_background(session(page), 'prompt', ['synthetic.zip'], upload_timeout=180000,
                                      lock_factory=lambda: nullcontext(), parallel_upload=True,
                                      upload_context=context)
        started = records(self.root)[0]
        self.assertEqual(started['kind'], 'upload_started')
        self.assertEqual(upload.call_args.kwargs['timeout'], 180000)
        for field in ('upload_attempt_id', 'lane', 'job_id', 'paper_id', 'target_id', 'zip_name',
                      'sdk_version', 'external_sha256', 'owner_pid'):
            self.assertIn(field, started)

    def test_unregistered_evidence_directory_means_no_upload_at_all(self):
        upload_trace.reset()
        page = Mock()
        with (patch('browser.web_card_transport.wait_gpt_upload_ready'),
              patch('web_gpt.core.upload_files_detailed') as upload):
            with self.assertRaises(DeferredWeb):
                submit_gpt_background(session(page), 'prompt', ['synthetic.zip'],
                                      lock_factory=lambda: nullcontext(), parallel_upload=True)
        upload.assert_not_called()
        page.locator.assert_not_called()

    def test_closing_receipt_failure_protects_the_page_and_never_sends(self):
        page = Mock()
        with (patch('browser.web_card_transport.wait_gpt_upload_ready'),
              patch('web_gpt.core.upload_files_detailed', return_value=OK_DETAIL),
              patch.object(upload_trace, 'finish', side_effect=OSError('disk full'))):
            with self.assertRaisesRegex(DeferredWeb, '保留原页面待核对'):
                submit_gpt_background(session(page), 'prompt', ['synthetic.zip'],
                                      lock_factory=lambda: nullcontext(), parallel_upload=True)
        self.assertTrue((self.root / upload_trace.EVENTS_FILE).exists())
        self.assertEqual([line['kind'] for line in records(self.root)], ['upload_started'])
        self.assertEqual(upload_trace.attempt(upload_trace.active('x')) if upload_trace.active('x') else 'cleared', 'cleared')

    def test_unknown_outcome_is_never_recorded_as_finished(self):
        attempt = upload_trace.begin(target_id='T1', zip_path='/tmp/x.zip')
        closed = upload_trace.finish(attempt['upload_attempt_id'], result='unknown', failure_kind='unknown')
        self.assertEqual(closed['state'], 'unknown')
        self.assertEqual(records(self.root)[-1]['state'], 'unknown')

    def test_exception_message_is_stored_without_the_signed_path(self):
        attempt = upload_trace.begin(target_id='T1', zip_path='/tmp/x.zip')
        upload_trace.finish(attempt['upload_attempt_id'], result='failed', failure_kind='write_failed',
                            exception_type='RuntimeError',
                            exception_message='PUT https://files.oaiusercontent.com/files/secret?sig=private 401')
        raw = (self.root / upload_trace.EVENTS_FILE).read_text()
        self.assertNotIn('secret?sig', raw)
        self.assertNotIn('private', raw)
        self.assertIn('files.oaiusercontent.com', raw)


class FailureClassification(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.addCleanup(upload_trace.reset)
        upload_trace.configure(self.root)

    def submit(self, *, detail_value=None, exception=None, stopping=lambda: False, context=None):
        page = Mock()
        with (patch('browser.web_card_transport.wait_gpt_upload_ready'),
              patch('browser.web_card_transport.wait_gpt_upload_settled'),
              patch('web_gpt.core.upload_files_detailed',
                    side_effect=exception if exception else (lambda *a, **k: detail_value)),
              patch('web_gpt.core.wait_prompt_box', side_effect=RuntimeError('stop here')),
              patch('web_gpt.core._composer')):
            with self.assertRaises(Exception) as caught:
                submit_gpt_background(session(page), 'prompt', ['synthetic.zip'], upload_timeout=180000,
                                      stopping=stopping, lock_factory=lambda: nullcontext(),
                                      parallel_upload=True, upload_context=context if context is not None else {})
        return caught.exception, records(self.root)[-1]

    def test_technical_upload_failures_still_reach_the_bounded_backoff_stage(self):
        error, closed = self.submit(detail_value=FAILED_DETAIL)
        self.assertIsInstance(error, UploadStageFailure)
        self.assertEqual(error.stage, 'settle')
        self.assertEqual(closed['failure_kind'], 'settle_timeout')
        self.assertTrue(closed['retryable_upload'])

    def test_pause_quota_verification_and_input_changes_are_not_upload_failures(self):
        for exception, kind, stage in (
                (DeferredWeb('已暂停，未上传材料'), 'paused', None),
                (RuntimeError('附件额度限制：文件附件数量已达上限'), 'quota', None),
                (RuntimeError('访问验证：请在专用浏览器手动验证您是真人'), 'verification', None),
                (RuntimeError('提交前冻结材料改变，不能打包上传'), 'input_changed', None)):
            with self.subTest(kind=kind):
                error, closed = self.submit(exception=exception)
                self.assertEqual(closed['failure_kind'], kind)
                self.assertFalse(closed['retryable_upload'])
                if stage is None:
                    self.assertNotIsInstance(error, UploadStageFailure)

    def test_unreadable_settle_state_stays_unknown_and_blocks_the_backoff(self):
        error, closed = self.submit(detail_value=detail(ok=False, receipt_sufficient=False,
            stage='progress_settle', failure_kind='settle_unreadable', retryable_upload=False))
        self.assertEqual(closed['failure_kind'], 'settle_unreadable')
        self.assertFalse(closed['retryable_upload'])
        self.assertNotIsInstance(error, UploadStageFailure)

    def test_write_failure_and_missing_attachment_close_different_segments(self):
        written, closed_write = self.submit(detail_value=detail(
            ok=False, receipt_sufficient=False, stage='attachment_write',
            failure_kind='write_failed', retryable_upload=True))
        shown, closed_shown = self.submit(detail_value=detail(
            ok=False, receipt_sufficient=False, stage='attachment_visible',
            failure_kind='attachment_not_shown', retryable_upload=True))
        self.assertEqual((written.stage, shown.stage), ('attach_write', 'attach_visible'))
        self.assertEqual((closed_write['stage'], closed_shown['stage']),
                         ('attachment_write', 'attachment_visible'))

    def test_a_stage_label_alone_never_opens_a_backoff(self):
        # Counting follows the kernel's own retryable flag: a detail that names a
        # backoff stage but denies retryability must not reach the policy.
        error, closed = self.submit(detail_value=detail(
            ok=False, receipt_sufficient=False, stage='attachment_write',
            failure_kind='write_failed', retryable_upload=False))
        self.assertNotIsInstance(error, UploadStageFailure)
        self.assertEqual(closed['failure_kind'], 'write_failed')
        self.assertFalse(closed['retryable_upload'])

    def test_kernel_detail_subtrees_are_stripped_before_the_durable_write(self):
        # The external kernel copies raw Playwright exceptions into settle.error
        # and stage entries; those strings are not evidence and never stay.
        attempt = upload_trace.begin(target_id='T1', zip_path='/tmp/x.zip')
        upload_trace.finish(attempt['upload_attempt_id'], result='failed',
                            failure_kind='settle_unreadable',
                            stages=[{'stage': 'progress_settle', 'outcome': 'unreadable',
                                     'file': 'https://x.test/files/a?sig=b'},
                                    {'stage': 'attachment_write', 'outcome': 'written'}],
                            settle={'error': 'TimeoutError: PUT https://files.oaiusercontent.com/signed?sig=secret 401',
                                    'progress_bars': 2, 'rechecks': 1},
                            attachment={'expected': 'synthetic.zip',
                                        'observed': 'GET https://h.test/files/y?token=zz ended'})
        raw = (self.root / upload_trace.EVENTS_FILE).read_text()
        for secret in ('signed?', 'sig=secret', 'sig=b', 'token=zz'):
            self.assertNotIn(secret, raw)
        self.assertIn('files.oaiusercontent.com', raw)
        closed = records(self.root)[-1]
        self.assertEqual(closed['settle']['progress_bars'], 2)
        self.assertEqual(closed['settle']['rechecks'], 1)
        self.assertEqual(closed['attachment']['expected'], 'synthetic.zip')
        self.assertEqual([entry['stage'] for entry in closed['stages']],
                         ['progress_settle', 'attachment_write'])
        self.assertIn('<redacted>', closed['settle']['error'])

    def test_five_interleaved_uploads_have_disjoint_ids_and_zip_bindings(self):
        closed_records = []
        for index in range(5):
            context = {'lane': 'review', 'job_id': 'job-%d' % index, 'paper_id': 'paper-%d' % index,
                       'target_id': 'T%d' % index,
                       'bundle': {'zip_sha256': 'sha-%d' % index, 'size': 7}}
            _, closed = self.submit(detail_value=detail(bundle={'zip_name': 'synthetic.zip',
                        'zip_sha256': 'sha-%d' % index, 'zip_bytes': 7,
                        'identity': {'sdk_version': '1.63.0', 'source_sha256': 'e3b591fc'}}),
                        context=context)
            closed_records.append(closed)
        self.assertEqual(len({line['upload_attempt_id'] for line in closed_records}), 5)
        self.assertEqual(sorted(line['zip_sha256'] for line in closed_records), ['sha-%d' % i for i in range(5)])
        pairs = {}
        for line in records(self.root):
            pairs.setdefault(line['upload_attempt_id'], []).append((line['kind'], line['zip_sha256']))
        for entries in pairs.values():
            self.assertEqual({sha for _, sha in entries}, {entries[0][1]})

    def test_attempt_ledger_is_stamped_through_the_callback(self):
        seen = {}

        def identified(identifier, diagnostic):
            seen['id'] = identifier
            seen['diagnostic'] = dict(diagnostic)

        self.submit(detail_value=OK_DETAIL, context={'lane': 'cards', 'target_id': 'T1',
                                                    'on_identified': identified})
        self.assertEqual(set(seen), {'id', 'diagnostic'})
        self.assertEqual(seen['diagnostic']['state'], 'in_progress')
        self.assertEqual(seen['diagnostic']['lane'], 'cards')

    def test_repacked_package_is_flagged_instead_of_relabelled(self):
        _, closed = self.submit(detail_value=detail(bundle={'zip_name': 'synthetic.zip',
            'zip_sha256': 'sha-actual', 'zip_bytes': 7,
            'identity': {'sdk_version': '1.63.0', 'source_sha256': 'e3b591fc'}}),
            context={'lane': 'review', 'target_id': 'T1', 'bundle': {'zip_sha256': 'sha-intent', 'size': 7}})
        self.assertTrue(closed['zip_identity_mismatch'])
        self.assertEqual(closed['intent_zip_sha256'], 'sha-intent')
        self.assertEqual(closed['zip_sha256'], 'sha-actual')


if __name__ == '__main__':
    unittest.main()
