import hashlib
import json
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from core.api import paths__WorkspacePath as Path
from browser.startup_page_restart import schedule_stalled, safe
from core.control import read_record

class StartupRestart(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'web_cards':{'shared_window':{'health_repair':{'startup_stalled_reopen_enabled':True}}}}
        self.request={'id':'a'*32}
        self.registry={'window_id':1,'slots':[{'slot_id':'01','target_id':'owned'}]}
        self.pool={'windows':{'owned':{'state':'opening','never_submitted':True,'startup_request_id':'a'*32}}}
        self.snap={'target_id':'owned','inspection_complete':True,'streaming':False,'draft':'old restored draft'}
    def check(self,at):
        schedule_stalled(self.config,self.root,self.pool,self.request,self.registry,[self.snap],at=at)
    def test_only_two_separated_checks_schedule_restart(self):
        self.check(100);self.check(110)
        self.assertFalse((self.root/'startup-page-restart-request.json').exists())
        self.check(130)
        self.assertEqual(read_record(self.root/'startup-page-restart-request.json')['targets'][0]['target_id'],'owned')
    def test_changed_draft_resets_rounds(self):
        self.check(100);self.snap['draft']='new user draft';self.check(130)
        self.assertFalse((self.root/'startup-page-restart-request.json').exists())
    def test_protected_or_used_pages_are_never_scheduled(self):
        for key,value in [('streaming',True),('verification',True),('quota',True),('login',True),('attachments',1),('user_texts',['sent']),('answer_element_count',1),('inspection_complete',False)]:
            with self.subTest(key=key):
                self.assertFalse(safe({**self.snap,key:value}))
        self.pool['windows']['owned']['never_submitted']=False
        self.check(100);self.check(130)
        self.assertFalse((self.root/'startup-page-restart-request.json').exists())
    def test_disabled_policy_does_not_change_request(self):
        self.config={};self.check(100);self.check(130)
        self.assertEqual(self.request,{'id':'a'*32})


class StartupRestartBatch(unittest.TestCase):
    def test_one_missing_target_does_not_block_the_other_items(self):
        from browser.startup_page_restart import run_once
        from core.services import atomic_json
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        config={'catalog_path':str(root/'catalog.db')}
        request={'id':'a'*32}
        registry={'window_id':1,'slots':[{'slot_id':'01','target_id':'t1'},{'slot_id':'02','target_id':'t2'}]}
        pool={'windows':{'t1':{'state':'opening','never_submitted':True,'startup_request_id':request['id']},
                         't2':{'state':'opening','never_submitted':True,'startup_request_id':request['id']}}}
        empty=hashlib.sha256(b'').hexdigest()
        atomic_json(root/'startup-page-restart-request.json',{'state':'pending','startup_request_id':request['id'],
            'window_id':1,'targets':[{'slot_id':'01','target_id':'t1','draft_sha256':empty},
                                     {'slot_id':'02','target_id':'t2','draft_sha256':empty}]})
        pages={'t1':MagicMock(),'t2':MagicMock()}
        def archive(folder,*args,**kwargs):
            folder.mkdir(parents=True,exist_ok=True);(folder/'evidence.txt').write_text('ok')
            return {'evidence.txt':hashlib.sha256(b'ok').hexdigest()}
        def create(browser,wid,**kw):
            kw['on_created']({'target_id':'new2','window_id':wid})
            return {'extension_uninstalled':True}
        inventories=[{'complete':True,'targets':{'t2':{'target_id':'t2','window_id':1,'url':'https://chatgpt.com/'}}},
                     {'complete':True,'targets':{}}]
        with (patch('browser.browser_inventory.enumerate_pages',return_value={'pages':pages}),
              patch('browser.shared_page_repair._records',return_value=({},{})),
              patch('browser.shared_page_repair._archive',side_effect=archive),
              patch('browser.startup_page_restart.require_slot',side_effect=[RuntimeError('No target with given id'),None,None,None]),
              patch('browser.startup_page_restart.snapshot_page',return_value={'inspection_complete':True,'streaming':False,'draft':'','target_id':'t2'}),
              patch('browser.startup_page_restart.read_window_inventory',side_effect=inventories),
              patch('browser.startup_page_restart.create_in_window',side_effect=create),
              patch('browser.startup_page_restart.save_pool')):
            run_once(config,MagicMock(),pool,request,registry,lambda:False)
        saved=json.loads((root/'startup-page-restart-request.json').read_text())
        self.assertEqual(saved['state'],'partial')
        self.assertEqual(saved['blocked_targets'],['t1'])
        self.assertEqual(registry['slots'][1]['target_id'],'new2')
        self.assertEqual(pool['windows']['t1']['state'],'opening')
