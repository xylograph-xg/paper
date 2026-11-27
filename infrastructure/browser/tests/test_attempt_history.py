import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path

from browser.attempt_history import index_attempts, submission_history, read_attempt


class AttemptHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'web_cards' / 'paper'

    def receipt(self, suffix, state, **extra):
        path = self.folder / suffix / 'attempt.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'target_id': 'target', 'state': state, **extra}))
        return path

    def test_archived_unknown_request_blocks_an_empty_active_directory(self):
        for state in ('submitted', 'needs_inspection', 'submission_started'):
            path = self.receipt('history/old/chatgpt', state)
            self.assertFalse(submission_history(self.folder).allowed)
            path.unlink()

    def test_pause_before_send_archive_preserves_queue_permission(self):
        self.receipt('history/paused/attempt', 'not_sent', send_click_started=False)
        self.assertTrue(submission_history(self.folder).allowed)

    def test_saved_archive_needs_explicit_retry_and_matching_fingerprints(self):
        raw, prompt = 'Complete original reply', 'Original prompt'
        path = self.receipt('history/automatic-retry-1-100/chatgpt', 'response_saved',
                            inputs={'pdf': 'hash'}, raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                            actual_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                            conversation_url='https://chatgpt.com/c/original')
        (path.parent/'response-raw.txt').write_text(raw)
        (path.parent/'prompt-actual.txt').write_text(prompt)
        self.assertFalse(submission_history(self.folder).allowed)
        (self.folder/'retry.json').write_text(json.dumps({'state': 'scheduled', 'external_retries': 1,
                                                        'input_hashes': {'pdf': 'hash'}}))
        self.assertTrue(submission_history(self.folder).allowed)
        (path.parent/'response-raw.txt').write_text('Changed')
        self.assertFalse(submission_history(self.folder).allowed)

    def test_modified_old_receipt_does_not_become_latest_intent(self):
        self.receipt('chatgpt', 'submitted', created=200)
        older = self.receipt('history/old/chatgpt', 'response_saved', created=100, updated=900)
        _, latest = index_attempts(self.root)
        self.assertEqual(latest['target']['created'], 200)
        before = read_attempt(older)
        older.write_text(json.dumps({'target_id': 'target', 'state': 'needs_inspection', 'created': 100}))
        self.assertNotEqual(before['_ledger_sha256'], read_attempt(older)['_ledger_sha256'])

    def test_broken_archival_evidence_fails_closed(self):
        path = self.receipt('history/old/chatgpt', 'not_sent', send_click_started=False)
        path.write_text('broken')
        with self.assertRaises(ValueError):
            submission_history(self.folder)

    def test_complete_index_resolves_linked_receipt_and_rechecks_file_identity(self):
        original = self.receipt('history/original', 'submitted', created=200)
        linked = self.folder / 'history' / 'linked' / 'attempt.json'
        linked.parent.mkdir()
        linked.symlink_to(original)
        expected = read_attempt(original)
        canonical = str(original.resolve())
        self.assertEqual(index_attempts(self.root), ({canonical: expected}, {'target': expected}))
        replacement = original.with_name('replacement.json')
        replacement.write_text(json.dumps({'target_id': 'target', 'state': 'needs_inspection', 'created': 200}))
        replacement.replace(original)
        records, latest = index_attempts(self.root)
        self.assertEqual(records[canonical], latest['target'])
        self.assertNotEqual(latest['target']['_ledger_sha256'], expected['_ledger_sha256'])

class ArchiveRace(unittest.TestCase):
    def test_missing_path_rescans_without_dropping_receipts(self):
        from unittest.mock import patch
        from browser.attempt_history import index_attempts
        records=({'archive':{'state':'needs_inspection'}},{'target':{'state':'needs_inspection'}})
        with patch('browser.attempt_history._index_attempts',side_effect=[FileNotFoundError(),records]) as scan:
            self.assertEqual(index_attempts('/unused'),records)
            self.assertEqual(scan.call_count,2)

    def test_persistent_missing_path_blocks_instead_of_claiming_empty(self):
        from unittest.mock import patch
        from browser.attempt_history import index_attempts
        with patch('browser.attempt_history._index_attempts',side_effect=FileNotFoundError()):
            with self.assertRaises(FileNotFoundError):index_attempts('/unused')

class ReceiptScanResponsiveness(unittest.TestCase):
    setUp=AttemptHistoryTests.setUp
    receipt=AttemptHistoryTests.receipt
    def test_archived_receipt_resolution_also_pumps_without_changing_identity(self):
        import asyncio
        import time
        from unittest.mock import patch
        from browser.attempt_history import set_scan_checkpoint
        from browser.shared_claim_recovery import locate_retired_receipt
        paths=[self.receipt(f'history/{i}/chatgpt','needs_inspection',created=i) for i in range(6)]
        record=read_attempt(paths[3]);record['_ledger_path']=str(self.folder/'history/missing/chatgpt/attempt.json')
        loop=asyncio.new_event_loop();self.addCleanup(loop.close);observed=[]
        async def observer():observed.append(True)
        loop.create_task(observer())
        def slow_read(path):
            time.sleep(.02)
            return read_attempt(path)
        previous=set_scan_checkpoint(lambda:loop.run_until_complete(asyncio.sleep(0)))
        try:
            with patch('browser.shared_claim_recovery.read_attempt',side_effect=slow_read):
                resolved=locate_retired_receipt(record)
        finally:set_scan_checkpoint(previous)
        self.assertTrue(observed)
        self.assertEqual(resolved['_ledger_sha256'],record['_ledger_sha256'])
        self.assertEqual(resolved['target_id'],record['target_id'])
        self.assertEqual(resolved['state'],'needs_inspection')
    def test_complete_scan_pumps_owner_loop_without_omitting_old_unknown_receipts(self):
        import asyncio
        import time
        from unittest.mock import patch
        from browser.attempt_history import set_scan_checkpoint
        for i in range(6):self.receipt(f'history/{i}/chatgpt', 'needs_inspection', created=i)
        loop=asyncio.new_event_loop();self.addCleanup(loop.close)
        observed=[]
        async def observer():
            observed.append('original-loop-ran')
        loop.create_task(observer())
        from browser.attempt_history import _read_attempt
        def slow_read(path, stat):
            time.sleep(.02)
            return _read_attempt(path, stat)
        previous=set_scan_checkpoint(lambda:loop.run_until_complete(asyncio.sleep(0)))
        try:
            with patch('browser.attempt_history._read_attempt',side_effect=slow_read):
                records,latest=index_attempts(self.root)
        finally:set_scan_checkpoint(previous)
        self.assertTrue(observed)
        self.assertEqual(len(records),6)
        self.assertEqual(latest['target']['created'],5)
        self.assertFalse(submission_history(self.folder).allowed)

    def test_owner_stop_during_scan_fails_closed_and_checkpoint_is_thread_local(self):
        import threading
        from unittest.mock import patch
        from browser.attempt_history import set_scan_checkpoint
        self.receipt('chatgpt','submitted',created=1)
        def stop():raise InterruptedError('owner stopping')
        previous=set_scan_checkpoint(stop)
        background=[]
        try:
            worker=threading.Thread(target=lambda:background.append(index_attempts(self.root)))
            worker.start();worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(background[0][0]),1)
            with patch('browser.attempt_history.time.monotonic',return_value=1e12):
                with self.assertRaises(InterruptedError):index_attempts(self.root)
        finally:set_scan_checkpoint(previous)
