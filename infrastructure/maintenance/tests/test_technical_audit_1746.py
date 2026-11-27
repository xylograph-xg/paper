import json
from core.api import paths__WorkspacePath as Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from maintenance.audit_archive import capture, verify
from core.catalog import Catalog, validate_fetch_capacity
from core.concurrency_control import apply
from maintenance.recovery_backup import create, verify as verify_backup, restore_candidate


class TechnicalAudit1746(unittest.TestCase):
    def test_mixed_archive_records_do_not_disable_index_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'data/example/manifest.json';path.parent.mkdir(parents=True);path.write_text('{}')
            index=capture(['data/example/manifest.json'],'synthetic',root)
            (index.parent/'other-audit.json').write_text('{"findings":[]}')
            report=verify(root,details=True)
            self.assertEqual(report['verified_entries'],1);self.assertEqual(report['skipped_non_indexes'],['other-audit.json'])
            (index.parent/'bad-index.json').write_text('{"kind":"immutable_evidence_index"}')
            with self.assertRaisesRegex(ValueError,'entries'):verify(root)

    def test_runtime_fetch_limits_use_authorized_total_and_keep_refill_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'concurrency-control.json').write_text(json.dumps({'fetch':32,'cards':20}))
            config={'catalog_path':str(root/'catalog.sqlite3'),'fetch_pipeline':{},
                    'web_cards':{'max_parallel_jobs':20,'max_total_pages':20,'refill_min_pending':20}}
            apply(config);policy=config['fetch_pipeline'];validate_fetch_capacity(policy)
            self.assertEqual((policy['download_workers'],policy['fallback_workers']),(22,10))
            self.assertEqual(config['web_cards']['refill_min_pending'],20)
            for policy in ({'download_workers':150,'fallback_workers':1},{'download_workers':True},
                           {'download_workers':22,'fallback_workers':-1}):
                with self.assertRaises(ValueError):validate_fetch_capacity(policy)
            validate_fetch_capacity({'download_workers':1,'fallback_workers':0})

    def test_all_pdf_hosts_are_paced_and_cooldown_is_rechecked(self):
        from fetch.net_limits import pace_arxiv
        with patch('fetch.network.ready') as ready,patch('fetch.network.pace') as pace:
            pace_arxiv('https://publisher.example/paper.pdf')
            pace.assert_called_once_with('pdf:publisher.example',3.0)
            self.assertEqual(ready.call_count,2)
        with patch('fetch.network.ready'),patch('fetch.network.pace') as pace:
            pace_arxiv('https://arxiv.org/pdf/1234.5678')
            pace.assert_called_once_with('arxiv-pdf',15.0)

    def test_legacy_external_review_default_disabled_even_without_pause(self):
        from review.web_feedback import require_current_legacy_control
        with tempfile.TemporaryDirectory() as td:
            config={'catalog_path':td+'/catalog.sqlite3'}
            with self.assertRaisesRegex(PermissionError,'历史评审'):require_current_legacy_control(config)
            (Path(td)/'card-review-control.json').write_text('{"paused_by_user":true}')
            config['legacy_external_review_enabled']=True
            with self.assertRaises(PermissionError):require_current_legacy_control(config)

    def test_mhtml_claim_recovery_checks_hashes_and_original_ledger(self):
        from browser.shared_page_backlog import install
        from browser.shared_claim_recovery import recover_claims
        from browser.attempt_history import read_attempt
        from maintenance.recovery_backup import sha
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);catalog=Catalog(root/'catalog.sqlite3');install(catalog)
            attempt=root/'web_cards/paper/chatgpt/attempt.json';attempt.parent.mkdir(parents=True)
            attempt.write_text('{"state":"not_sent","send_click_started":false,"target_id":"old"}')
            record=read_attempt(attempt);folder=root/'shared-page-repairs/test/diagnostics';folder.mkdir(parents=True)
            for name in ('health.json','body.txt','page.html','page.mhtml','ledger-before.json'):(folder/name).write_text('synthetic')
            (folder/'capture.json').write_text('{"method":"resident_cdp_mhtml","screenshot_available":false}')
            hashes={p.name:sha(p) for p in folder.iterdir()}
            (folder.parent/'journal.json').write_text(json.dumps({'state':'ready','health':{'replace_allowed':False},
                'unrecoverable_fallback':True,'close_authorized':True,'requeue_allowed':False,
                'archive_hashes':hashes,'record':record,'old_target_id':'old'}))
            with catalog.connect() as db:
                db.execute("INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES('cards','paper','paper','old',1,'claimed')")
            entries={'old':{'state':'retired_replaced'}};health={'state':'checked','checked_at':100}
            (folder/'page.mhtml').write_text('changed')
            self.assertEqual(recover_claims(catalog,entries,health,at=100),[])
            (folder/'page.mhtml').write_text('synthetic')
            journal_path=folder.parent/'journal.json'
            journal=json.loads(journal_path.read_text());journal['close_authorized']=False
            journal_path.write_text(json.dumps(journal))
            self.assertEqual(recover_claims(catalog,entries,health,at=100),[])
            journal['close_authorized']=True;journal_path.write_text(json.dumps(journal))
            self.assertEqual(len(recover_claims(catalog,entries,health,at=100)),1)

    def test_supervised_entry_waits_for_owner_lock_without_second_pool(self):
        from cards.web_card_service import run
        with tempfile.TemporaryDirectory() as td:
            config={'catalog_path':td+'/catalog.sqlite3','web_cards':{'background_no_create':True}}
            with patch('cards.web_card_service.owner_enabled',return_value=True), \
                 patch('cards.web_card_service.fcntl.flock',side_effect=[BlockingIOError(),None]), \
                 patch('cards.web_card_service.time.sleep') as wait, \
                 patch('cards.web_card_service.queue.recover') as recover, \
                 patch('browser.web_card_pool.run_pool') as pool:
                run(config)
                wait.assert_called_once_with(5)
                recover.assert_called_once()
                pool.assert_called_once_with(config)

    def test_seed_status_never_claims_lifetime_output_or_stale_activity(self):
        from fetch.fetching import seed_observation
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'seed-discovery-status.json'
            path.write_text(json.dumps({'updated':100,'seeds':{'doi':{'state':'running','records':3,'warnings':1}}}))
            report=seed_observation(td,at=101)
            self.assertEqual(report['returned_records'],3);self.assertFalse(report['lifetime_output_known'])
            self.assertEqual(seed_observation(td,at=1000)['state'],'awaiting_observation')

    def test_user_disabled_data_backup_creates_no_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);catalog=Catalog(root/'data/catalog.sqlite3')
            catalog.upsert({'title':'Synthetic source'})
            with self.assertRaisesRegex(RuntimeError,'禁用数据备份'):
                create({'catalog_path':str(catalog.path)},root=root)
            self.assertFalse((root/'data/recovery-backups').exists())
