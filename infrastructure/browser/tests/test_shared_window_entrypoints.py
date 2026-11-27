"""The watcher and startup entry may request maintenance, never control CDP."""
import io
import json
import tempfile
import unittest
from contextlib import ExitStack,redirect_stdout
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch, Mock

from browser import web_pool_open; from maintenance import web_tab_watch


class SharedWindowEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config={'catalog_path':str(self.root/'catalog.sqlite3'),
                     'web_cards':{'enabled':True,'max_parallel_jobs':6,'max_total_pages':20,
                                  'refill_min_pending':20,
                                  'shared_window':{'enabled':True,'slot_count':20}}}
        self.manifest=self.root/'shared-gpt-window.json'
        self.request_file=self.root/'shared-window-maintenance-request.json'
        self.registry={'schema_version':1,'window_id':123,'state':'ready',
                       'slots':[{'slot_id':f'{i+1:02d}','target_id':f'own-{i}'} for i in range(20)]}
        self.addCleanup(patch.stopall)
        patch.dict('os.environ',{'WEB_GPT_CDP_URL':'http://127.0.0.1:9222'}).start()

    def save_registry(self,record=None):
        self.manifest.write_text(json.dumps(record if record is not None else self.registry))

    def targets(self,missing=None):
        return [{'id':f'own-{i}','type':'page','url':'https://chatgpt.com/'}
                for i in range(20) if i!=missing]+[
                    {'id':'user-gpt','type':'page','url':'https://chatgpt.com/'},
                    {'id':'user-site','type':'page','url':'https://example.com/'},
                    {'id':'worker','type':'service_worker','url':'https://chatgpt.com/'}]

    def watcher(self,targets=None):
        stack=ExitStack();self.addCleanup(stack.close)
        guards={}
        for name in ('playwright.sync_api.sync_playwright',
                     'browser.browser_recovery.check_health',
                     'browser.browser_recovery.maintain_pool',
                     'browser.browser_recovery.open_owned_pages',
                     'maintenance.web_tab_watch.cleanup_candidate'):
            guards[name]=stack.enter_context(patch(name,side_effect=AssertionError('browser operation forbidden')))
        guards['refill']=stack.enter_context(patch('cards.web_card_queue.select'))
        guards['retention']=stack.enter_context(patch('maintenance.web_artifact_retention.compact_completed'))
        guards['display']=stack.enter_context(patch('reading.card_display.maintain'))
        guards['inbox']=stack.enter_context(patch('core.action_inbox.publish'))
        response=io.BytesIO(json.dumps(targets if targets is not None else self.targets()).encode())
        opener=Mock();opener.open.return_value=response
        stack.enter_context(patch('maintenance.web_tab_watch.urllib.request.build_opener',return_value=opener))
        guards['http']=opener.open
        return web_tab_watch.check(self.config),guards

    def assert_no_browser_operation(self,guards):
        for name,mock in guards.items():
            if name.startswith(('playwright.','browser.browser_recovery.','maintenance.web_tab_watch.cleanup')):
                mock.assert_not_called()

    def test_watcher_counts_registered_pool_and_keeps_other_windows_separate(self):
        self.save_registry();before=self.manifest.read_bytes()
        folder=self.root/'web_cards'/'old'/'chatgpt';folder.mkdir(parents=True)
        (folder/'attempt.json').write_text(json.dumps({'state':'needs_inspection','target_id':'own-0','error':'old','finished':1}))
        report,guards=self.watcher()
        self.assert_no_browser_operation(guards)
        self.assertEqual(report['total_pages'],20)
        self.assertEqual(report['counts'],{'chatgpt':20,'qwen':0,'deepseek':0})
        self.assertEqual(report['browser_total_pages'],22)
        self.assertEqual(report['other_pages'],2)
        self.assertEqual(report['over_limit'],[]);self.assertEqual(report['closed'],[])
        self.assertEqual(self.manifest.read_bytes(),before)
        request=json.loads(self.request_file.read_text())
        self.assertEqual(request['action'],'reconcile');self.assertEqual(request['window_id'],123)
        self.assertEqual(request['origin'],'web_tab_watch');self.assertFalse(request['ensure_page'])
        self.assertEqual(len(request['manifest_sha256']),64)
        guards['http'].assert_called_once_with('http://127.0.0.1:9222/json/list',timeout=5)
        guards['inbox'].assert_called_once()
        for name in ('refill','retention','display'):guards[name].assert_not_called()

    def test_watcher_reports_missing_target_without_replacing_or_closing_it(self):
        self.save_registry();before=self.manifest.read_bytes()
        report,guards=self.watcher(self.targets(missing=3))
        self.assert_no_browser_operation(guards)
        self.assertEqual(report['total_pages'],19);self.assertEqual(report['missing_targets'],['own-3'])
        self.assertEqual(report['browser_total_pages'],21);self.assertEqual(report['other_pages'],2)
        self.assertEqual(self.manifest.read_bytes(),before)

    def test_watcher_missing_or_corrupt_registration_never_rebuilds_or_requests_initialization(self):
        for raw in (None,b'{broken',b'[]'):
            with self.subTest(raw=raw):
                if self.manifest.exists():self.manifest.unlink()
                if self.request_file.exists():self.request_file.unlink()
                if raw is not None:self.manifest.write_bytes(raw)
                report,guards=self.watcher()
                self.assert_no_browser_operation(guards)
                self.assertEqual(report['state'],'needs_inspection')
                self.assertEqual(report['total_pages'],0);self.assertEqual(report['other_pages'],22)
                self.assertFalse(self.request_file.exists())
                self.assertEqual(self.manifest.read_bytes() if self.manifest.exists() else None,raw)

    def test_startup_reuses_twenty_blank_slots_without_any_browser_search(self):
        self.save_registry();before=self.manifest.read_bytes()
        with patch('playwright.sync_api.sync_playwright') as playwright,\
                patch('browser.web_pool_open.ensure_startup_page') as opening,redirect_stdout(io.StringIO()):
            result=web_pool_open.request(self.config,ensure_page=True)
        playwright.assert_not_called();opening.assert_not_called()
        self.assertEqual(result['state'],'shared_pool_registered');self.assertTrue(result['reused'])
        self.assertEqual(result['created_pages'],0);self.assertEqual(result['slot_count'],20)
        self.assertEqual(self.manifest.read_bytes(),before)
        request=json.loads(self.request_file.read_text())
        self.assertEqual(request['action'],'reconcile');self.assertTrue(request['ensure_page'])
        self.assertFalse((self.root/'gpt-page-adoption.json').exists())

    def test_explicit_missing_startup_only_requests_owner_initialization(self):
        with patch('playwright.sync_api.sync_playwright') as playwright,redirect_stdout(io.StringIO()):
            result=web_pool_open.request(self.config,ensure_page=True)
        playwright.assert_not_called();self.assertEqual(result['state'],'needs_inspection')
        self.assertEqual(result['created_pages'],0);self.assertFalse(self.manifest.exists())
        request=json.loads(self.request_file.read_text())
        self.assertEqual(request['action'],'initialize');self.assertTrue(request['ensure_page'])
        self.assertEqual(request['origin'],'explicit_open_gpt')

    def test_implicit_missing_startup_cannot_request_initialization(self):
        with patch('playwright.sync_api.sync_playwright') as playwright,redirect_stdout(io.StringIO()):
            result=web_pool_open.request(self.config)
        playwright.assert_not_called();self.assertEqual(result['state'],'needs_inspection')
        self.assertFalse(self.request_file.exists());self.assertFalse(self.manifest.exists())

    def test_corrupt_startup_registration_and_old_request_remain_unchanged(self):
        duplicate=json.loads(json.dumps(self.registry));duplicate['slots'][1]['target_id']='own-0'
        for raw in (b'{broken',json.dumps(duplicate).encode()):
            with self.subTest(raw=raw):
                self.manifest.write_bytes(raw);old_request=b'{"state":"pending","keep":"old receipt"}'
                self.request_file.write_bytes(old_request)
                with patch('playwright.sync_api.sync_playwright') as playwright,redirect_stdout(io.StringIO()):
                    result=web_pool_open.request(self.config,ensure_page=True)
                playwright.assert_not_called();self.assertEqual(result['state'],'needs_inspection')
                self.assertEqual(self.manifest.read_bytes(),raw);self.assertEqual(self.request_file.read_bytes(),old_request)

    def test_registration_with_unfilled_slots_is_preserved_for_owner(self):
        self.registry['slots'][5]['target_id']=None;self.save_registry()
        report,guards=self.watcher()
        self.assert_no_browser_operation(guards)
        self.assertEqual(report['total_pages'],19);self.assertEqual(report['unbound_slots'],1)
        self.assertIsNone(json.loads(self.manifest.read_text())['slots'][5]['target_id'])

    def test_registration_for_other_endpoint_is_not_adopted(self):
        self.registry['endpoint']='http://127.0.0.1:9333';self.save_registry()
        report,guards=self.watcher()
        self.assert_no_browser_operation(guards)
        self.assertEqual(report['state'],'needs_inspection');self.assertEqual(report['total_pages'],0)
        self.assertFalse(self.request_file.exists())


if __name__=='__main__':unittest.main()
