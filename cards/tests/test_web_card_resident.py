import json
import tempfile
import time
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import patch
from core.catalog import Catalog
from cards import web_card_queue as queue
from browser.web_card_transport import Router, ProviderFailure, UncertainWeb, DeferredWeb, run_with_failover, provider_page_count, owned_error_cleanup, collect_owned
from cards.web_card_inputs import parse_card, prepare, digest

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

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.sqlite3');self.library=self.root/'library'
        self.config={'catalog_path':str(self.catalog.path),'studio_library_root':str(self.library),'web_cards':{'selection_fraction':.30},'topic_queries':['triplet exciton OLED'],'journal_priority':{'Nature':3}}
        self.ids=[]
        for i in range(10):
            pid=self.catalog.upsert({'title':f'Triplet exciton OLED material {i}','doi':f'10.1234/{i}','year':2020+i,'venue':'Nature' if i>=7 else 'Other'},candidate=True)
            source=self.root/f'{i}.pdf';source.write_bytes(b'%PDF fixture')
            self.catalog.update(pid,acquisition='available',asset_path=str(source),asset_hash=digest(source));self.ids.append(pid)
    def test_approximately_thirty_percent_reproducible_and_deduplicated(self):
        first=queue.select(self.catalog,self.config);self.assertEqual(first['target'],3);self.assertEqual(len(first['added']),3)
        self.assertEqual(set(first['added']),set(self.ids[7:]));self.assertEqual(queue.select(self.catalog,self.config)['added'],[])

    def test_supplemental_inventory_does_not_block_new_metadata_selection(self):
        queue.install(self.catalog)
        with self.catalog.connect() as db:
            for pid in self.ids[:8]:
                db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',
                    (pid,'fixture','fixture',json.dumps({'selection_kind':'downloaded_refill'}),'fixture'))
        result=queue.select(self.catalog,self.config)
        self.assertEqual(set(result['added']),set(self.ids[8:]))
        self.assertEqual(result['selected'],2)

    def test_archived_submission_without_queue_row_is_not_selected_again(self):
        path=self.root/'web_cards'/self.ids[9]/'history'/'old'/'chatgpt'/'attempt.json'
        path.parent.mkdir(parents=True);path.write_text('{"state":"needs_inspection"}')
        result=queue.select(self.catalog,self.config)
        self.assertNotIn(self.ids[9],result['added'])
    def test_human_decisions_and_existing_cards_protected(self):
        self.catalog.decide(self.ids[9],'keep');self.library.mkdir();folder=self.library/self.ids[8];folder.mkdir();(folder/'card.json').write_text('human card')
        chosen=queue.select(self.catalog,self.config)['added'];self.assertNotIn(self.ids[9],chosen);self.assertNotIn(self.ids[8],chosen)
        self.assertEqual((folder/'card.json').read_text(),'human card')
    def test_identity_pending_and_out_of_scope_not_selected(self):
        for pid,key in [(self.ids[9],'identity_review_required'),(self.ids[8],'out_of_scope')]:
            p=self.catalog.get(pid);self.catalog.upsert({**p['metadata'],key:True})
        selected=queue.select(self.catalog,self.config);self.assertEqual(selected['available'],8);self.assertEqual(selected['target'],2)
        self.assertFalse(set(selected['added'])&set(self.ids[8:]))
    def test_crash_and_deferred_claim_do_not_duplicate_sent_job(self):
        queue.select(self.catalog,self.config);job=queue.claim(self.catalog);queue.update(self.catalog,job['paper_id'],state='submitted')
        queue.recover(self.catalog);self.assertEqual(next(j for j in queue.jobs(self.catalog) if j['paper_id']==job['paper_id'])['state'],'needs_inspection')
        second=queue.claim(self.catalog);queue.update(self.catalog,second['paper_id'],state='queued',retry_at=time.time()+60)
        third=queue.claim(self.catalog);self.assertNotEqual(third['paper_id'],second['paper_id']);self.assertIsNone(queue.claim(self.catalog))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.router=Router(self.root)
    def test_unsent_limit_and_network_switch_to_qwen(self):
        for kind in ('quota','network'):
            router=Router(self.root/kind);calls=[]
            def request(provider,*args):
                calls.append(provider)
                if provider=='chatgpt':raise ProviderFailure('blocked',provider,kind,True)
                return 'answer'
            result,provider=run_with_failover(router,{},self.root,{},request_fn=request)
            self.assertEqual(calls,['chatgpt','qwen']);self.assertEqual((result,provider),('answer','qwen'));self.assertEqual(router.choose(),'qwen')
    def test_manual_verification_persists_and_blocks_automatic_retries(self):
        from browser.web_card_transport import failure_kind
        self.assertEqual(failure_kind('访问验证，请完成以下操作，验证您是真人'),'verification')
        self.router.block(ProviderFailure('访问验证','qwen','verification',True))
        self.assertEqual(Router(self.root).choose(),'chatgpt')
        self.router.block(ProviderFailure('quota','chatgpt','quota',True))
        with self.assertRaises(DeferredWeb):self.router.choose()
        from maintenance.web_tab_watch import cleanup_candidate
        self.assertFalse(cleanup_candidate({'state':'needs_inspection','target_id':'own','error':'访问验证','finished':1,'tab_cleanup':'preserved_verification'},self.root))
    def test_gpt_falls_back_only_to_ready_fixed_qwen_window(self):
        (self.root/'web-provider-selection.json').write_text(json.dumps({'provider':'chatgpt','allowed_providers':['chatgpt','qwen'],'reuse_qwen_window':True}))
        self.router.block(ProviderFailure('quota','chatgpt','quota',True,time.time()+100))
        with self.assertRaises(DeferredWeb):self.router.choose()
        (self.root/'qwen-window.json').write_text(json.dumps({'state':'ready'}))
        self.assertEqual(self.router.choose(),'qwen')
        (self.root/'qwen-window.json').write_text(json.dumps({'state':'needs_inspection'}))
        with self.assertRaises(DeferredWeb):self.router.choose()

    def test_requested_unready_provider_does_not_silently_use_other_models(self):
        (self.root/'web-provider-selection.json').write_text(json.dumps({'provider':'deepseek','state':'login_required'}))
        with self.assertRaises(DeferredWeb):self.router.choose()
        (self.root/'web-provider-selection.json').write_text(json.dumps({'provider':'deepseek','state':'ready'}))
        self.assertEqual(self.router.choose(),'deepseek')
    def test_sent_or_unknown_request_not_repeated_across_models(self):
        calls=[]
        def request(provider,*args):calls.append(provider);raise ProviderFailure('lost after send',provider,'network',False)
        with self.assertRaises(UncertainWeb):run_with_failover(self.router,{},self.root,{},request_fn=request)
        self.assertEqual(calls,['chatgpt']);self.assertEqual(self.router.choose(),'qwen')
    def test_all_network_down_waits_without_page_storm(self):
        calls=[]
        def request(provider,*args):calls.append(provider);raise ProviderFailure('down',provider,'network',True)
        with self.assertRaises(DeferredWeb):run_with_failover(self.router,{},self.root,{},request_fn=request)
        self.assertEqual(calls,['chatgpt','qwen'])
        with self.assertRaises(DeferredWeb):run_with_failover(self.router,{},self.root,{},request_fn=request)
        self.assertEqual(len(calls),2)
    def test_explicit_reset_restores_gpt_priority(self):
        self.router.block(ProviderFailure('quota','chatgpt','quota',True,time.time()+100));self.assertEqual(Router(self.root).choose(),'qwen')
        from core.control import mutate_record
        mutate_record(self.router.path,{'chatgpt':{**self.router.state['chatgpt'],'blocked_until':time.time()-1}})
        self.assertEqual(self.router.choose(),'chatgpt')
    def test_per_provider_budget_includes_other_projects(self):
        pages=[SimpleNamespace(url='https://chatgpt.com/c/x') for _ in range(20)]+[SimpleNamespace(url='https://chat.qwen.ai/c/y') for _ in range(20)]+[SimpleNamespace(url='https://other.test/')]
        browser=SimpleNamespace(contexts=[SimpleNamespace(pages=pages)])
        self.assertEqual(provider_page_count(browser,'chatgpt'),20);self.assertEqual(provider_page_count(browser,'qwen'),20)
    def test_error_page_diagnostics_saved_before_close(self):
        unrelated=SimpleNamespace(closed=False)
        class Page:
            url='https://chat.qwen.ai/c/failed';closed=False
            def is_closed(self):return self.closed
            def locator(self,*args):return SimpleNamespace(inner_text=lambda **kw:'Network error')
            def screenshot(self,**kwargs):Path(kwargs['path']).write_bytes(b'image')
            def close(p):
                self.assertTrue((self.root/'attempt.json').is_file());self.assertTrue((self.root/'error-page.txt').is_file());p.closed=True
        page=Page();a={'state':'needs_inspection'};owned_error_cleanup(page,self.root,a)
        self.assertTrue(page.closed);self.assertFalse(unrelated.closed);self.assertEqual(a['tab_cleanup'],'closed_error_page')


class InputsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def fixture(self):
        import pymupdf
        source=self.root/'original.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((72,72),'Triplet excitons persist under stated conditions.');page.add_text_annot((80,80),'PRIVATE NOTE');doc.set_metadata({'author':'private metadata'});doc.save(source);doc.close()
        return source
    def test_all_pages_visual_source_only_and_annotations_removed(self):
        import pymupdf
        source=self.fixture();original=digest(source);packet=prepare(str(source),str(self.root/'inputs'),'test','test',original)
        with pymupdf.open(self.root/'inputs/source.pdf') as doc:
            self.assertEqual(len(doc),1);self.assertEqual(list(doc[0].annots() or []),[]);self.assertFalse(doc.metadata.get('author'))
        with pymupdf.open(self.root/'inputs/visual.pdf') as doc:self.assertEqual(len(doc),1)
        self.assertEqual(digest(source),original);self.assertEqual(len(packet['files']),3);self.assertTrue(Path(packet['page_manifest'][0]['image']).exists())
    def test_changed_source_blocks_before_materials_upload(self):
        with self.assertRaises(ValueError):prepare(str(self.fixture()),str(self.root/'inputs'),'test','test','wronghash')
    def test_invalid_or_duplicate_json_and_page_mapping_rejected(self):
        base={'title':'t','info':{k:'原文未提供，无法确认' for k in ('标题','作者','期刊','年份','DOI','研究对象','主要方法','关键词')},'one_line_summary':'s','key_findings':'k','intro_summary':'i','conclusion_summary':'c','warnings':[],'figures':[],'equations':[],'tables':[]}
        packet={'page_count':1,'page_manifest':[{'image':'one.png'}]}
        self.assertEqual(parse_card(json.dumps(base),packet)['title'],'t')
        with self.assertRaises(ValueError):parse_card('{"title":"a","title":"b"}',packet)
        base['figures']=[{'source_page':2,'evidence_id':'P002'}]
        with self.assertRaises(ValueError):parse_card(json.dumps(base),packet)
    def test_existing_human_card_never_uses_transport(self):
        from cards.web_card_service import process_job
        catalog=Catalog(self.root/'catalog.sqlite3');pid=catalog.upsert({'title':'manual card'});queue.install(catalog)
        source=self.fixture();catalog.update(pid,acquisition='available',asset_path=str(source));target=self.root/'library'/pid;target.mkdir(parents=True);(target/'card.json').write_text('human preserved')
        config={'catalog_path':str(catalog.path),'studio_library_root':str(self.root/'library')}
        with catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',(pid,'synthetic','manual card','{}','now'))
        with patch('browser.web_card_transport.run_with_failover') as request:
            process_job(config,{'paper_id':pid},None,None,lambda:False);request.assert_not_called()
        self.assertEqual((target/'card.json').read_text(),'human preserved')

    def test_formal_card_published_with_migrated_source_and_unverified_science(self):
        import threading
        from cards.web_card_service import process_job
        catalog=Catalog(self.root/'catalog.sqlite3');pid=catalog.upsert({'title':'source only'});queue.install(catalog)
        source=self.fixture();catalog.update(pid,acquisition='available',asset_path=str(source),asset_hash=digest(source))
        folder=self.root/'web_cards'/pid;packet=prepare(str(source),str(folder),pid,'source only',digest(source))
        config={'catalog_path':str(catalog.path),'studio_library_root':str(self.root/'library'),'web_cards':{}}
        with catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',(pid,digest(source),'source only','{}','now'))
        job=queue.claim(catalog)
        from cards.paper_quality import RUBRIC
        evaluation={k:{'score':None,'reason':'信息不足','source_pages':[]} for k in ('overall_quality','direction_novelty')}
        evaluation['overall_quality']['dimensions']={k:{'score':None,'reason':'信息不足','source_pages':[]} for k in RUBRIC}
        raw=json.dumps({'title':'source only','info':{k:'原文未提供，无法确认' for k in ('标题','作者','期刊','年份','DOI','研究对象','主要方法','关键词')},'one_line_summary':'s','key_findings':'k','intro_summary':'i','conclusion_summary':'c','warnings':[],'figures':[],'equations':[],'tables':[],'paper_evaluation':evaluation})
        attempt={'settings':{'model':'test'},'conversation_url':'https://chatgpt.com/c/test','raw_sha256':'test'}
        with patch('browser.web_card_transport.run_with_failover',return_value=((raw,attempt),'chatgpt')) as transport:
            process_job(config,job,None,threading.Semaphore(1),lambda:False);transport.assert_called_once()
        target=self.root/'library'/pid;card=json.loads((target/'card.json').read_text())
        self.assertTrue((target/'source.pdf').is_file());self.assertTrue((target/'pages/P001.png').is_file())
        self.assertEqual(catalog.get(pid)['card_path'],str(target/'card.json'));self.assertFalse(card['meta']['scientific_verified'])
        self.assertFalse(card['meta']['production_contract_complete']);self.assertEqual(queue.jobs(catalog)[0]['state'],'completed')
        self.assertEqual(card['meta']['card_format_version'],packet['card_format_version'])


class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright=sync_playwright().start()
        chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        try:
            cls.browser=cls.playwright.chromium.launch(**({'executable_path':str(chrome)} if chrome.is_file() else {}),headless=True)
        except Exception:
            cls.playwright.stop();raise
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.playwright.stop()
    def test_background_gpt_input_uses_no_system_clipboard_or_front_switch(self):
        import types
        from unittest.mock import patch
        from browser.web_card_transport import submit_gpt_background
        try:import web_gpt.core
        except ModuleNotFoundError:self.skipTest('Shared web_gpt owner package is not installed in this checkout')
        page=self.browser.new_page()
        try:
            page.route('https://chatgpt.com/c/synthetic-test',lambda route:route.fulfill(status=200,body='<html></html>'))
            page.goto('https://chatgpt.com/c/synthetic-test')
            page.set_content('<form><div id="prompt-textarea" contenteditable="true" role="textbox"></div><button type="button" aria-label="发送">send</button></form>')
            page.evaluate("""() => { document.querySelector('button').onclick=()=>{
                document.getElementById('prompt-textarea').textContent='';window.sent=(window.sent||0)+1;
                const user=document.createElement('div');user.setAttribute('data-message-author-role','user');
                user.textContent='Background prompt';document.body.appendChild(user);
            }; }""")
            session=types.SimpleNamespace(page=page,_pending_answer=None,verify_settings=lambda:None)
            import contextlib
            with patch('browser.web_card_transport.formal_gpt_url',return_value=True),patch('web_gpt.submission.submission_lock',return_value=contextlib.nullcontext()),patch('web_gpt.core._clipboard',side_effect=AssertionError('clipboard forbidden')),patch.object(page,'bring_to_front',side_effect=AssertionError('foreground forbidden')):
                self.assertEqual(submit_gpt_background(session,'Background prompt',[]),0)
            self.assertEqual(page.evaluate('window.sent'),1)
        finally:page.close()
    def test_completion_outside_markdown_is_collected(self):
        page=self.browser.new_page()
        try:
            page.set_content('<article><div id="answer">Complete response</div><button aria-label="Copy">copy</button></article>')
            result=collect_owned(page,0,'chatgpt',('#answer','#stop',lambda e:e.inner_text()),5)
            self.assertEqual(result,'Complete response')
        finally:page.close()
    def test_new_gpt_turn_container_completion_is_collected(self):
        page=self.browser.new_page()
        try:
            page.set_content('<div data-talvt-turn-state="complete"><div><div data-chatgpt-search-message-ids="unique"><div id="answer">Saved JSON</div></div></div><button aria-label="复制">copy</button></div>')
            self.assertEqual(collect_owned(page,0,'chatgpt',('#answer','#stop',lambda e:e.inner_text()),5),'Saved JSON')
        finally:page.close()
    def test_streaming_partial_rejected_and_visible_error_detected(self):
        page=self.browser.new_page()
        try:
            page.set_content('<article><div id="answer">Partial</div><button aria-label="Copy">copy</button><button id="stop">stop</button></article>')
            with self.assertRaises(TimeoutError):collect_owned(page,0,'chatgpt',('#answer','#stop',lambda e:e.inner_text()),1)
            page.set_content('<div role="alert">Network error: connection failed</div>')
            with self.assertRaisesRegex(RuntimeError,'网页报错'):collect_owned(page,0,'chatgpt',('#answer','#stop',lambda e:e.inner_text()),3)
        finally:page.close()


if __name__=='__main__':unittest.main()

class ServiceStatusTests(unittest.TestCase):
    def test_slow_attachment_upload_is_not_reported_as_stopped(self):
        from cards.web_card_service import status
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'web-card-service.json').write_text(json.dumps({'pid':123,'state':'running','updated':time.time()-120,'workers':1,'stage':'preparing_submission'}))
            with patch('cards.web_card_service._owner_process_confirmed',return_value=True):
                value=status({'catalog_path':str(root/'catalog.sqlite3'),'web_cards':{'enabled':True}})
            self.assertEqual(value['state'],'running');self.assertTrue(value['alive']);self.assertTrue(value['heartbeat_stale'])

class UploadSubmissionBoundaryTests(unittest.TestCase):
    def setUp(self):
        _trace_temp(self)
    def test_upload_failure_never_marks_send_started(self):
        import contextlib
        from unittest.mock import Mock
        from browser.web_card_transport import submit_gpt_background
        callback=Mock();session=SimpleNamespace(_pending_answer=None,page=object(),verify_settings=lambda:None)
        with patch('web_gpt.submission.submission_lock',return_value=contextlib.nullcontext()),patch('browser.web_card_transport.wait_gpt_upload_ready'),patch('web_gpt.core.upload_files_detailed',return_value=UPLOAD_FAIL):
            with self.assertRaisesRegex(RuntimeError,'附件上传失败'):submit_gpt_background(session,'prompt',['source.pdf'],on_before_send=callback)
        callback.assert_not_called();self.assertIsNone(session._pending_answer)

class StockRefillTests(unittest.TestCase):
    setUp=QueueTests.setUp
    def enable(self,minimum):
        import hashlib
        self.config['web_cards']['refill_min_pending']=minimum
        for pid in self.ids:self.catalog.update(pid,asset_hash=hashlib.sha256(Path(self.catalog.get(pid)['asset_path']).read_bytes()).hexdigest())
    def test_refill_beyond_selection_fraction_is_idempotent(self):
        self.enable(5);first=queue.select(self.catalog,self.config)
        self.assertEqual(first['target'],3);self.assertEqual(first['ready_pending'],5);self.assertEqual(len(first['refilled']),2)
        self.assertEqual(queue.select(self.catalog,self.config)['added'],[])
        kinds=[json.loads(j['selection'])['selection_kind'] for j in queue.jobs(self.catalog)]
        self.assertEqual(kinds.count('downloaded_refill'),2)
    def test_failed_jobs_do_not_count_as_ready_and_are_not_requeued(self):
        queue.select(self.catalog,self.config);old=queue.jobs(self.catalog)
        for j in old:queue.update(self.catalog,j['paper_id'],state='failed')
        self.enable(4);r=queue.select(self.catalog,self.config)
        self.assertEqual(r['ready_pending'],4);self.assertFalse(set(r['refilled'])&{j['paper_id'] for j in old})
        self.assertEqual(sum(j['state']=='failed' for j in queue.jobs(self.catalog)),3)
    def test_delayed_jobs_and_manual_decisions_remain_protected(self):
        queue.select(self.catalog,self.config)
        for j in queue.jobs(self.catalog):queue.update(self.catalog,j['paper_id'],retry_at=time.time()+3600)
        self.catalog.decide(self.ids[0],'keep');self.enable(2)
        r=queue.select(self.catalog,self.config);self.assertEqual(r['ready_pending'],2);self.assertNotIn(self.ids[0],r['added'])
        self.assertEqual(sum(j['retry_at']>time.time() for j in queue.jobs(self.catalog)),3)
    def test_changed_source_not_used_for_refill(self):
        queue.select(self.catalog,self.config);self.enable(10)
        pid=self.ids[6];Path(self.catalog.get(pid)['asset_path']).write_bytes(b'changed source')
        r=queue.select(self.catalog,self.config);self.assertNotIn(pid,r['refilled']);self.assertEqual(r['ready_pending'],9)
    def test_historical_attempt_without_queue_row_is_not_refilled(self):
        queue.select(self.catalog,self.config);self.enable(10)
        pid=self.ids[6];folder=self.catalog.path.parent/'web_cards'/pid/'chatgpt';folder.mkdir(parents=True);(folder/'attempt.json').write_text('{"state":"needs_inspection"}')
        r=queue.select(self.catalog,self.config);self.assertNotIn(pid,r['refilled']);self.assertEqual(r['ready_pending'],9)
