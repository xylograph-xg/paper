import hashlib,json,os,tempfile,unittest
from pathlib import Path
from contextlib import ExitStack,nullcontext
from unittest.mock import Mock,patch
from browser.shared_window_owner import refresh_requested


class RequestedRefresh(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'data';self.root.mkdir();self.config={'catalog_path':str(self.root/'catalog.sqlite3')}
        auth=self.root.parent/'docs/authorizations/20261015-small-package-and-login-detection.md';auth.parent.mkdir(parents=True);auth.write_text('explicit user refresh')
        self.registry={'schema_version':1,'window_id':7,'endpoint':'http://127.0.0.1:9222','slots':[
            {'slot_id':f'{i:02d}','target_id':'own' if i==1 else f't{i}'} for i in range(1,21)]}
        (self.root/'shared-gpt-window.json').write_text(json.dumps(self.registry))
        (self.root/'web-card-service.json').write_text(json.dumps({'pid':os.getpid(),'token':'original-token'}))
        self.request={'id':'a'*32,'state':'pending','authorized':True,'owner_pid':os.getpid(),
            'owner_token_sha256':hashlib.sha256(b'original-token').hexdigest(),'authorization_sha256':hashlib.sha256(auth.read_bytes()).hexdigest(),
            'window_id':7,'targets':[{'slot_id':'01','target_id':'own'}]}
        self.path=self.root/'owned-page-refresh.json';self.path.write_text(json.dumps(self.request));self.page=Mock()
        self.snapshot={'target_id':'own','url':'https://chatgpt.com/','inspection_complete':True,'streaming':False,'uploading':False,
            'user_texts':[],'answer_texts':[],'draft':'','attachments':0,'login':False,'verification':False,'quota':False,
            'errors':['浏览器检查未能完成。请重新加载此页面以重试']}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('cards.web_card_service.owner_enabled',return_value=True))
        self.stack.enter_context(patch('browser.shared_window_owner.require_slot'))
        self.stack.enter_context(patch('browser.shared_page_health.snapshot_page',side_effect=lambda *a:dict(self.snapshot)))
        self.records=self.stack.enter_context(patch('browser.shared_page_repair._records',return_value=({},{})))
        self.archive=self.stack.enter_context(patch('browser.shared_page_repair._archive',return_value={'page.html':'synthetic'}))
        self.stack.enter_context(patch('browser.browser_inventory.enumerate_pages',return_value={'pages':{'own':self.page}}))
    def run_once(self):return refresh_requested(self.config,Mock(),lock_factory=lambda **_:nullcontext(),stopping=lambda:False)
    def test_one_archived_refresh_keeps_identity_and_never_replays(self):
        self.assertEqual(self.run_once(),['own']);self.page.reload.assert_called_once_with(wait_until='commit',timeout=5000)
        self.archive.assert_called_once();self.assertEqual(self.run_once(),[]);self.page.reload.assert_called_once()
        self.assertEqual(json.loads((self.root/'shared-gpt-window.json').read_text()),self.registry)
    def test_navigation_timeout_keeps_unknown_without_repeating_reload(self):
        self.page.reload.side_effect=TimeoutError('receipt unknown');self.assertEqual(self.run_once(),[])
        self.assertEqual(json.loads(self.path.read_text())['targets'][0]['state'],'refresh_unknown')
        self.run_once();self.page.reload.assert_called_once()
    def test_blank_editor_newline_and_recovered_homepage_are_refreshable(self):
        self.snapshot.update(draft='\n',composer_available=True,errors=[])
        self.assertEqual(self.run_once(),['own']);self.page.reload.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text())['targets'][0]['observed_snapshot']['draft'],'\n')
    def test_draft_upload_login_verification_or_unknown_request_blocks_refresh(self):
        for changes in ({'draft':'new draft'},{'uploading':True},{'login':True},{'verification':True},{'streaming':True},{'errors':[]}):
            self.path.write_text(json.dumps(self.request));old=dict(self.snapshot);self.snapshot.update(changes)
            self.run_once();self.page.reload.assert_not_called();self.snapshot=old
        self.path.write_text(json.dumps(self.request));self.records.return_value=({'p':{'target_id':'own','state':'submitted'}},{})
        self.run_once();self.page.reload.assert_not_called()
