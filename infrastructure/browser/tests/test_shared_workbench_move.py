import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import Mock,patch
from browser import shared_workbench_move as move
from browser.shared_browser_window import WindowIsolationError

class AuthorizedWorkbenchMove(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'shared-workbench-move.json'
        self.config={'catalog_path':str(self.root/'catalog.sqlite3')}
        self.registry={'window_id':77,'slots':[{'target_id':f't{i}'} for i in range(20)]}
        self.journal={'authorized':True,'registry_sha256':'sha','window_id':77,'target_id':'workbench','url':'http://127.0.0.1:8767/','state':'pending'}
        self.path.write_text(json.dumps(self.journal));self.browser=Mock();self.session=Mock();self.worker=Mock()
        self.session.send.return_value={'id':'extension'}
        self.browser.new_browser_cdp_session.return_value=self.session
        self.before={'complete':True,'errors':[],'targets':{s['target_id']:{'window_id':77,'url':'https://chatgpt.com/'} for s in self.registry['slots']}}
        self.before['targets']['workbench']={'window_id':77,'url':self.journal['url']}
        self.after=json.loads(json.dumps(self.before));self.after['targets']['workbench']['window_id']=88
        self.worker.evaluate.return_value={'windowId':88,'focused':False,'tabId':21}
    def run_move(self,inventories):
        with patch('browser.shared_page_repair._allowed'),patch('browser.shared_page_repair._registry',return_value=(self.registry,'sha')),patch.object(move,'_worker',return_value=self.worker),patch.object(move,'read_window_inventory',side_effect=inventories):
            return move.run_once(self.config,self.browser,stopping=lambda:False)
    def test_moves_exact_original_tab_and_verifies_twenty_without_creation_or_close(self):
        r=self.run_move([self.before,self.after]);self.assertEqual(r['state'],'verified');self.assertEqual(r['fixed_slots'],20)
        expression=self.worker.evaluate.call_args.args[0]
        self.assertIn('tabId: matches[0].id',expression);self.assertIn('focused: false',expression)
        self.assertNotIn('tabs.create',expression);self.assertNotIn('tabs.remove',expression)
        self.session.send.assert_any_call('Extensions.uninstall',{'id':'extension'})
        self.assertIsNone(move.run_once(self.config,self.browser,stopping=lambda:False).get('error'))
        self.assertEqual(self.worker.evaluate.call_count,1)
    def test_unknown_move_receipt_is_observed_without_reissuing(self):
        self.journal['state']='move_unknown';self.path.write_text(json.dumps(self.journal))
        with self.assertRaises(WindowIsolationError):self.run_move([self.before])
        self.worker.evaluate.assert_not_called()
        self.assertEqual(self.run_move([self.after,self.after])['state'],'verified')
        self.worker.evaluate.assert_not_called()
    def test_original_target_disappeared_does_not_recreate_or_move_another(self):
        self.before['targets'].pop('workbench')
        r=self.run_move([self.before]);self.assertEqual(r['state'],'cancelled_target_missing')
        self.worker.evaluate.assert_not_called();self.browser.new_browser_cdp_session.assert_not_called()

    def test_unauthorized_or_extra_unknown_tabs_are_protected(self):
        self.journal['authorized']=False;self.path.write_text(json.dumps(self.journal))
        with self.assertRaises(WindowIsolationError):self.run_move([self.before])
        self.journal['authorized']=True;self.path.write_text(json.dumps(self.journal))
        self.before['targets']['foreign']={'window_id':77,'url':'https://example.com/'}
        with self.assertRaises(WindowIsolationError):self.run_move([self.before])
        self.worker.evaluate.assert_not_called()

    def test_completed_and_missing_journals_do_not_request_the_submission_lock(self):
        self.assertTrue(move.pending(self.config))
        for state in ('verified','cancelled_target_missing'):
            self.journal['state']=state;self.path.write_text(json.dumps(self.journal))
            self.assertFalse(move.pending(self.config))
        self.path.unlink();self.assertFalse(move.pending(self.config))
