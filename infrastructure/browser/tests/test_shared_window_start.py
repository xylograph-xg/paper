import tempfile
import unittest
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch,MagicMock
from core.services import atomic_json
from browser.shared_window_start import run_once

class StartWindow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config={'catalog_path':str(self.root/'catalog.db')}
        self.registry={'schema_version':1,'window_id':1,'endpoint':'http://127.0.0.1:9222',
            'slots':[{'slot_id':f'{i:02d}','target_id':f'old{i}'} for i in range(1,21)]}
        atomic_json(self.root/'shared-gpt-window.json',self.registry)
        atomic_json(self.root/'browser-start-request.json',{'id':'0123456789abcdef','state':'ready'})
        atomic_json(self.root/'gpt-window-pool.json',{'windows':{'old1':{'state':'submitted','paper_id':'preserve'}}})
        from browser.shared_pool_store import load_pool
        self.pool=load_pool(self.root/'gpt-window-pool.json')
    def test_surviving_registered_window_is_not_replaced(self):
        inv={'complete':True,'targets':{'old1':{'target_id':'old1','window_id':1,'url':'https://chatgpt.com/c/original'}}}
        with patch('browser.shared_window_start.read_window_inventory',return_value=inv),patch('browser.shared_window_start.bounded_call') as call:
            run_once(self.config,MagicMock(),self.pool,lambda **kw:nullcontext(),lambda:False)
            call.assert_not_called()
        self.assertEqual(self.pool['windows']['old1']['state'],'submitted')
    def test_uncertain_creation_does_not_repeat(self):
        atomic_json(self.root/'browser-start-request.json',{'id':'0123456789abcdef','state':'ready','window_creation_intent':123})
        with patch('browser.shared_window_start.read_window_inventory',return_value={'complete':True,'targets':{}}),patch('browser.shared_window_start.bounded_call') as call:
            run_once(self.config,MagicMock(),self.pool,lambda **kw:nullcontext(),lambda:False)
            call.assert_not_called()
    def test_pause_prevents_any_browser_operation(self):
        with patch('browser.shared_window_start.read_window_inventory') as inventory:
            run_once(self.config,MagicMock(),self.pool,lambda **kw:nullcontext(),lambda:True)
            inventory.assert_not_called()
    def test_missing_window_creates_twenty_and_preserves_original_request(self):
        import json
        archive=self.root/'browser-start-archives/0123456789abcdef/registry.json'
        archive.parent.mkdir(parents=True)
        archived=json.dumps(self.registry,separators=(',',':')).encode()
        archive.write_bytes(archived)
        inv={'complete':True,'targets':{}}
        created={'complete':True,'targets':{'first':{'target_id':'first','window_id':2,'url':'about:blank#paper-slot-startup-0123456789abcdef'}}}
        pages={}
        def create(browser,wid,**kw):
            tid=kw['nonce'];kw['on_created']({'target_id':tid,'window_id':wid})
        def enumerate_all(browser):
            registry=json.loads((self.root/'shared-gpt-window.json').read_text())
            for slot in registry['slots']:
                page=MagicMock();page.url='https://chatgpt.com/';page.locator.return_value.is_visible.return_value=True
                pages[slot['target_id']]=page
            return {'pages':pages}
        with patch('browser.shared_window_start.read_window_inventory',side_effect=[inv,created]),patch('browser.shared_window_start.bounded_call'),patch('browser.shared_window_start.create_in_window',side_effect=create) as create_tab,patch('browser.browser_inventory.enumerate_pages',side_effect=enumerate_all),patch('browser.shared_page_health.snapshot_page',return_value={'inspection_complete':True,'streaming':False,'composer_available':True}):
            run_once(self.config,MagicMock(),self.pool,lambda **kw:nullcontext(),lambda:False)
        self.assertEqual(create_tab.call_count,19)
        self.assertEqual(self.pool['windows']['old1'],{'state':'submitted','paper_id':'preserve'})
        self.assertEqual(json.loads((self.root/'browser-start-request.json').read_text())['ready_slots'],20)
        self.assertTrue((self.root/'browser-start-archives/0123456789abcdef/registry.json').exists())
        self.assertEqual(archive.read_bytes(),archived)

    def test_lost_initializing_window_is_rebuilt_once_without_reusing_old_pages(self):
        import json
        request={'id':'0123456789abcdef','state':'ready','initializing_window':1,
                 'window_creation_intent':123,'pool_state':'waiting_page_readiness'}
        atomic_json(self.root/'browser-start-request.json',request)
        for i in range(1,21):
            self.pool['windows'][f'old{i}']={'state':'opening','never_submitted':True}
        inv={'complete':True,'targets':{}}
        created={'complete':True,'targets':{'first':{'target_id':'first','window_id':2,
                 'url':'about:blank#paper-slot-startup-0123456789abcdef'}}}
        pages={}
        def create(browser,wid,**kw):
            tid=kw['nonce'];kw['on_created']({'target_id':tid,'window_id':wid})
        def enumerate_all(browser):
            registry=json.loads((self.root/'shared-gpt-window.json').read_text())
            for slot in registry['slots']:
                page=MagicMock();page.url='https://chatgpt.com/';page.locator.return_value.is_visible.return_value=True
                pages[slot['target_id']]=page
            return {'pages':pages}
        with (patch('browser.shared_window_start.read_window_inventory',side_effect=[inv,created]),
              patch('browser.shared_window_start.bounded_call'),
              patch('browser.shared_window_start.create_in_window',side_effect=create) as create_tab,
              patch('browser.browser_inventory.enumerate_pages',side_effect=enumerate_all),
              patch('browser.shared_page_health.snapshot_page',return_value={'inspection_complete':True,'streaming':False,'composer_available':True})):
            run_once(self.config,MagicMock(),self.pool,lambda **kw:nullcontext(),lambda:False)
        self.assertEqual(create_tab.call_count,19)
        saved=json.loads((self.root/'browser-start-request.json').read_text())
        self.assertEqual(saved['ready_slots'],20)
        self.assertEqual(saved['initializing_window'],2)
        self.assertNotEqual(saved.get('window_creation_intent'),123)
        self.assertEqual(self.pool['windows']['old1']['state'],'retired_window_lost')
        self.assertTrue((self.root/'browser-start-rebuilds').exists())
    def test_unready_composer_does_not_wait_or_prevent_other_startup_slots(self):
        import json
        request={'id':'0123456789abcdef','state':'ready','initializing_window':1}
        atomic_json(self.root/'browser-start-request.json',request)
        registry={**self.registry,'startup_request_id':request['id']}
        atomic_json(self.root/'shared-gpt-window.json',registry)
        pages={}
        for slot in registry['slots']:
            tid=slot['target_id'];page=MagicMock();page.url='https://chatgpt.com/'
            pages[tid]=page;self.pool['windows'][tid]={'state':'opening'}
        inv={'complete':True,'targets':{tid:{'target_id':tid,'window_id':1,'url':page.url}
                                     for tid,page in pages.items()}}
        def snapshot(tid,page):
            return {'inspection_complete':True,'streaming':False,'composer_available':tid!='old1',
                    'target_id':tid,'checked_at':100.0,'errors':[]}
        with (patch('browser.shared_window_start.read_window_inventory',return_value=inv),
              patch('browser.browser_inventory.enumerate_pages',return_value={'pages':pages}),
              patch('browser.shared_page_health.snapshot_page',side_effect=snapshot),
              patch('web_gpt.core.find_prompt_box',side_effect=AssertionError('startup must not wait'))):
            run_once(self.config,MagicMock(),self.pool,lambda **kw:nullcontext(),lambda:False)
        self.assertEqual(self.pool['windows']['old1']['state'],'opening')
        self.assertEqual(json.loads((self.root/'browser-start-request.json').read_text())['ready_slots'],19)
