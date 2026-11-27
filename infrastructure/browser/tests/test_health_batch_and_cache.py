"""A blocked renderer must not serialize other owned-page checks."""
import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from browser.shared_claim_recovery import _diagnostic_verified
from browser.shared_page_health import _snapshot_pages


class EvidenceCache(unittest.TestCase):
    def test_cached_hash_invalidates_for_changed_bytes_or_expected_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'page.html';file.write_bytes(b'original')
            fingerprint=hashlib.sha256(file.read_bytes()).hexdigest();cache={}
            with patch('browser.shared_claim_recovery.hashlib.sha256',wraps=hashlib.sha256) as digest:
                self.assertTrue(_diagnostic_verified(file,fingerprint,cache))
                self.assertTrue(_diagnostic_verified(file,fingerprint,cache))
                self.assertEqual(digest.call_count,1)
                stat=file.stat();file.write_bytes(b'modified')
                os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                self.assertFalse(_diagnostic_verified(file,fingerprint,cache))
                self.assertEqual(digest.call_count,2)
                expected=hashlib.sha256(b'modified').hexdigest()
                self.assertTrue(_diagnostic_verified(file,expected,cache))


class OwnedHealthBatch(unittest.TestCase):
    def test_one_delayed_page_keeps_other_snapshots_fresh_and_bounds_total_wait(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            try:
                pages={name:browser.new_page() for name in ('blocked','healthy-a','healthy-b')}
                for page in pages.values():page.set_content('<main><div id="prompt-textarea" contenteditable="true"></div></main>')
                async def delayed(*args,**kwargs):await asyncio.sleep(10)
                with patch.object(pages['blocked']._impl_obj,'evaluate',side_effect=delayed):
                    start=time.monotonic();snapshots=_snapshot_pages(pages);elapsed=time.monotonic()-start
                self.assertLess(elapsed,6)
                self.assertFalse(snapshots['blocked']['inspection_complete'])
                self.assertIn('TimeoutError',snapshots['blocked']['inspection_error'])
                for name in ('healthy-a','healthy-b'):
                    self.assertTrue(snapshots[name]['inspection_complete'])
                    self.assertLess(time.time()-snapshots[name]['checked_at'],6)
            finally:browser.close()
