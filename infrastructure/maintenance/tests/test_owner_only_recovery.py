"""The HTTP watcher never retires receipts or requeues a sent model request."""
import json, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from maintenance import auto_recover_work as recovery, abnormal_protection_cleanup as cleanup
from maintenance import web_tab_watch as watcher


class OwnerOnlyRecovery(unittest.TestCase):
    def test_legacy_timeout_entries_never_open_catalog_or_change_original_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt=root/'attempt.json';receipt.write_text('{"state":"submitted"}')
            pool=root/'gpt-window-pool.json';pool.write_text('{"windows":{"original":{"state":"busy"}}}')
            before=(receipt.read_bytes(),pool.read_bytes());catalog=Mock()
            catalog.connect.side_effect=AssertionError('HTTP-side catalog mutation forbidden')
            config={'catalog_path':str(root/'catalog.sqlite3')}
            self.assertEqual(recovery.requeue_cards(catalog,config),[])
            self.assertEqual(recovery.rerun_submitted_reviews(catalog,config),[])
            self.assertEqual(recovery.rerun_changed_corrections(catalog,config),[])
            self.assertEqual(cleanup.release_expired_claims(catalog,config,timeout=0),[])
            catalog.connect.assert_not_called()
            self.assertEqual((receipt.read_bytes(),pool.read_bytes()),before)

    def test_recovery_tick_only_requests_original_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'catalog_path':str(Path(tmp)/'catalog.sqlite3')}
            record={'window_id':77,'slots':[]}
            with (patch('browser.api.web_pool_open__shared_window_record',return_value=(record,'fingerprint')),
                  patch('browser.api.web_pool_open__shared_maintenance_request') as request):
                result=recovery.tick(config)
            self.assertEqual(result['state'],'owner_requested')
            request.assert_called_once_with(config,'legacy_technical_recovery_delegate',record,'fingerprint')
            self.assertTrue(result['original_requests_unchanged'])

    def test_shared_watch_check_does_not_refill_or_housekeep_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'catalog_path':str(Path(tmp)/'catalog.sqlite3'),'web_cards':{'refill_min_pending':20}}
            with (patch('core.api.concurrency_control__apply'),
                  patch('browser.api.web_pool_open__shared_mode',return_value=True),
                  patch.object(watcher,'check_shared',return_value={'state':'observed'}),
                  patch('cards.api.web_card_queue__select') as select,
                  patch('maintenance.web_artifact_retention.compact_completed') as compact):
                self.assertEqual(watcher.check(config),{'state':'observed'})
            select.assert_not_called();compact.assert_not_called()

    def test_watch_run_never_invokes_legacy_cleanup_writers(self):
        import signal
        with tempfile.TemporaryDirectory() as tmp:
            config={'catalog_path':str(Path(tmp)/'catalog.sqlite3')};handlers={}
            def one_check(_config):handlers[signal.SIGTERM]();return {}
            with (patch.object(watcher.signal,'signal',side_effect=lambda sig,fn:handlers.update({sig:fn})),
                  patch('core.api.control__pause_decision',return_value=SimpleNamespace(allowed=True)),
                  patch('maintenance.owner_supervision.tick'),patch('maintenance.sync_failed_dois.tick'),
                  patch.object(watcher,'check',side_effect=one_check),
                  patch.object(recovery,'tick') as recover,patch.object(cleanup,'tick') as clean):
                watcher.run(config)
            recover.assert_not_called();clean.assert_not_called()
