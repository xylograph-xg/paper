import json
import subprocess
import sys
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path

from browser.shared_pool_store import load_pool, save_pool, PoolConflict


class SharedPoolStoreTests(unittest.TestCase):
    def test_submission_ack_merges_same_request_without_downgrading_saved_response(self):
        from browser.shared_pool_store import acknowledge_submitted
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=root/'response.txt';raw.write_text('complete answer')
            digest=hashlib.sha256(raw.read_bytes()).hexdigest();path=root/'pool.json'
            original={'state':'busy','kind':'cards','active_paper_id':'paper'}
            path.write_text(json.dumps({'windows':{'target':original}}))
            stale=load_pool(path);live=load_pool(path)
            live['windows']['target'].update(state='ready',conversation_url='https://chatgpt.com/c/original',
                raw_path=str(raw),raw_sha256=digest)
            save_pool(path,live)
            receipt={'target_id':'target','kind':'cards','paper_id':'paper','state':'response_saved','conversation_url':'https://chatgpt.com/c/original','raw_sha256':digest}
            acknowledge_submitted(path,stale,'target',receipt)
            self.assertEqual(load_pool(path)['windows']['target']['state'],'ready')
            newer=load_pool(path);newer['windows']['target']={'state':'busy','kind':'cards','active_paper_id':'other'}
            save_pool(path,newer)
            # Even if a stale callback's local snapshot was refreshed to the
            # newer job, its immutable original receipt must still be refused.
            stale=load_pool(path)
            with self.assertRaises(PoolConflict):acknowledge_submitted(path,stale,'target',receipt)
            self.assertEqual(load_pool(path)['windows']['target']['active_paper_id'],'other')
            self.assertNotIn('conversation_url',load_pool(path)['windows']['target'])

    def test_new_request_preserves_prior_evidence_without_using_it_as_current_reply(self):
        from browser.shared_pool_store import begin_request, failed_request
        original={'state':'ready','slot':4,'kind':'review','review_id':'old-review',
                  'paper_id':'old','active_paper_id':'old','conversation_url':'https://chatgpt.com/c/old',
                  'raw_path':'original/response.txt','raw_sha256':'old-hash','never_submitted':True}
        entry=dict(original)
        begin_request(entry,'correction','new',correction_id='new-correction')
        self.assertEqual(entry['previous_saved_response']['raw_sha256'],'old-hash')
        self.assertEqual(entry['active_paper_id'],'new');self.assertEqual(entry['slot'],4)
        for key in ('raw_path','raw_sha256','conversation_url','paper_id','review_id','never_submitted'):
            self.assertNotIn(key,entry)
        failed_request(entry,original,page_touched=True,error='upload failed before click')
        self.assertEqual(entry['state'],'needs_inspection')
        self.assertNotIn('raw_sha256',entry)
        failed_request(entry,original,page_touched=False,error='pause before navigation')
        self.assertEqual(entry,original)

    def test_local_failures_keep_observer_and_disconnected_driver_is_released(self):
        from unittest.mock import Mock
        from playwright.sync_api import Error
        from browser.web_card_pool import keep_connection_after_error, refresh_concurrency
        browser=Mock();browser.is_connected.return_value=True
        for exc in (FileNotFoundError('old path'),ValueError('broken control'),PoolConflict('racing target')):
            self.assertTrue(keep_connection_after_error(browser,exc))
        self.assertFalse(keep_connection_after_error(browser,Error('driver lost')))
        browser.is_connected.return_value=False
        self.assertFalse(keep_connection_after_error(browser,ValueError('local')))
        config={'catalog_path':str(self.path.parent/'catalog.db'),'web_cards':{'max_parallel_jobs':8}}
        (self.path.parent/'concurrency-control.json').write_text('{')
        self.assertIn('并发控制需核对',refresh_concurrency(config))
        self.assertEqual(config['web_cards']['max_parallel_jobs'],8)

    def test_reuse_preserves_original_evidence_without_attaching_it_to_new_request(self):
        from browser.shared_pool_store import mark_verified_blank
        entry={'state':'ready','slot':3,'raw_path':'old.txt','raw_sha256':'old-hash',
               'conversation_url':'https://chatgpt.com/c/old','kind':'cards','review_id':'old-review','error':'old protection'}
        mark_verified_blank(entry)
        entry.update(state='busy',active_paper_id='new')
        self.assertNotIn('raw_path',entry)
        self.assertNotIn('raw_sha256',entry)
        self.assertNotIn('conversation_url',entry)
        self.assertEqual(entry['previous_saved_response']['raw_sha256'],'old-hash')
        self.assertEqual(entry['slot'],3)
        self.assertNotIn('review_id',entry)
        self.assertNotIn('error',entry)

    def test_driver_wait_failure_returns_to_owner_without_closing_browser(self):
        from unittest.mock import Mock
        from browser.web_card_pool import pump_owner_wait
        pw=Mock();observer=Mock();pw._sync.side_effect=RuntimeError('driver gone')
        self.assertIn('driver gone',pump_owner_wait(pw,observer))
        observer.stop.assert_called_once();pw.stop.assert_called_once()
        pw.chromium.connect_over_cdp.assert_not_called()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'pool.json'
        self.path.write_text(json.dumps({'windows': {'a': {'state': 'ready_blank', 'slot': 1},
                                                    'b': {'state': 'ready_blank', 'slot': 2}}}))

    def other_process(self, target):
        code = ('from browser.shared_pool_store import load_pool,save_pool; '
                'import sys; p=load_pool(sys.argv[1]); '
                "p['windows'][sys.argv[2]].update(state='busy',active_paper_id='other'); "
                'save_pool(sys.argv[1],p)')
        subprocess.run([sys.executable, '-c', code, str(self.path), target], check=True)

    def test_two_processes_merge_independent_targets_and_keep_references(self):
        old = load_pool(self.path)
        entries, entry = old['windows'], old['windows']['a']
        self.other_process('b')
        entry.update(state='busy', active_paper_id='own')
        save_pool(self.path, old)
        self.assertIs(old['windows'], entries)
        self.assertIs(entries['a'], entry)
        self.assertEqual(load_pool(self.path)['windows']['b']['active_paper_id'], 'other')
        self.assertEqual(entries['b']['state'], 'busy')

    def test_stale_same_target_cannot_erase_an_uncollected_request(self):
        old = load_pool(self.path)
        self.other_process('a')
        old['windows']['a'].update(state='ready', raw_sha256='stale')
        before = self.path.read_bytes()
        with self.assertRaises(PoolConflict):
            save_pool(self.path, old)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(load_pool(self.path)['windows']['a']['state'], 'busy')

    def test_unmodified_stale_snapshot_cannot_roll_back_other_targets(self):
        old = load_pool(self.path)
        self.other_process('a')
        old['observed_at'] = 1
        save_pool(self.path, old)
        self.assertEqual(old['windows']['a']['state'], 'busy')

    def test_invalid_or_untracked_pool_is_not_overwritten(self):
        with self.assertRaises(TypeError):
            save_pool(self.path, json.loads(self.path.read_text()))
        old = load_pool(self.path)
        self.path.write_text('broken')
        with self.assertRaises(ValueError):
            save_pool(self.path, old)
        self.assertEqual(self.path.read_text(), 'broken')
