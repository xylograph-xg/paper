import json,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from browser.account_readiness import recheck


class AccountRecovery(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.channel={'manual_verification_required':True,'source':'user_report_current_chat','target_slots':['02','08','16']}
        self.control=self.root/'web-channel-control.json';self.save_control()
        self.registry={'window_id':7,'slots':[{'slot_id':f'{n:02d}','target_id':f't{n}'} for n in range(1,21)]}
        (self.root/'shared-gpt-window.json').write_text(json.dumps(self.registry))
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch('core.catalog.load_config',return_value={}))
        self.enabled=stack.enter_context(patch('cards.web_card_service.owner_enabled',return_value=True))
    def save_control(self):self.control.write_text(json.dumps({'chatgpt':self.channel,'qwen':{'manual_verification_required':True}}))
    def pages(self,at):
        return [{'target_id':f't{n}','account_ready':True,'account_authenticated':True,'login':False,
                 'window_observed':True,'window_id':7,'checked_at':at,'window_checked_at':at} for n in range(1,21)]
    def test_two_complete_fresh_authenticated_checks_release_only_observed_gate(self):
        recheck(self.root,self.pages(100),at=100);self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
        recheck(self.root,self.pages(129),at=129);self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
        recheck(self.root,self.pages(131),at=131)
        result=json.loads(self.control.read_text());self.assertFalse(result['chatgpt']['manual_verification_required']);self.assertTrue(result['qwen']['manual_verification_required'])
        before=(self.root/'control-events.jsonl').read_bytes();recheck(self.root,self.pages(150),at=150)
        self.assertEqual((self.root/'control-events.jsonl').read_bytes(),before)
    def test_incomplete_stale_login_foreign_window_and_user_pause_never_release(self):
        for change in ({'account_ready':False},{'account_authenticated':False},{'login':True},{'window_observed':False},{'window_id':8},{'checked_at':0}):
            recheck(self.root,self.pages(100),at=100);pages=self.pages(131);pages[0].update(change);recheck(self.root,pages,at=131)
            self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
        recheck(self.root,self.pages(200),at=200);self.enabled.return_value=False;recheck(self.root,self.pages(231),at=231)
        self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
    def test_renewed_dom_hold_still_requires_all_pages(self):
        self.channel = {'manual_verification_required':True,'reason':'共享页检查发现登录或访问验证',
            'target_id':'t2','observed':80,'source':'resident_dom_authenticated_recheck',
            'recovered_at':50,'recovery_proof':str(self.root/'account-recovery.json')}
        self.save_control()
        for at in (100,110,140):
            pages = [dict(page,inspection_complete=True,verification=False) for page in self.pages(at)]
            pages[1]['login'] = at==100
            recheck(self.root,pages,at=at,formula_window=True)
            self.assertEqual(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'],at!=140)
    def test_formula_shared_gate_requires_two_authenticated_challenge_free_checks(self):
        self.channel = dict(manual_verification_required=True,reason='共享页检查发现登录或访问验证',
                            observed=85,target_id='t5')
        self.save_control()
        def check(at,challenge=False):
            pages = [dict(p,verification=False,inspection_complete=True) for p in self.pages(at)]
            pages[8]['verification'] = challenge
            recheck(self.root,pages,at=at,formula_window=True)
        check(100)
        check(131,True)
        self.assertEqual(json.loads((self.root/'account-recovery.json').read_text())['waiting_targets'],['t9'])
        check(140)
        self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
        check(171)
        self.assertFalse(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])

    def test_long_gap_unknown_gate_or_control_change_cannot_release(self):
        recheck(self.root,self.pages(100),at=100);recheck(self.root,self.pages(200),at=200)
        self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
        self.channel['source']='explicit_manual_hold';self.save_control()
        recheck(self.root,self.pages(231),at=231);recheck(self.root,self.pages(262),at=262)
        self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
        self.channel['source']='user_report_current_chat';self.save_control();recheck(self.root,self.pages(300),at=300)
        def changed(_):
            self.channel['reason']='new hold';self.save_control();return True
        self.enabled.side_effect=changed
        with self.assertRaises(ValueError):recheck(self.root,self.pages(331),at=331)
        self.assertTrue(json.loads(self.control.read_text())['chatgpt']['manual_verification_required'])
