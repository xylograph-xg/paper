import unittest
from browser.web_card_pool import normalize_json_escapes
import json

class NormalizationTests(unittest.TestCase):
    def test_invalid_math_escape_is_preserved_as_literal_text(self):
        raw=r'{"latex":"\\lambda + \\omega","quoted":"a \\"b\\""}'
        self.assertEqual(normalize_json_escapes(raw),raw)
        broken='{"latex":"'+chr(92)+'lambda"}'
        fixed=normalize_json_escapes(broken)
        self.assertEqual(json.loads(fixed)['latex'],chr(92)+'lambda')
        self.assertEqual(normalize_json_escapes(fixed),fixed)
    def test_valid_unicode_newline_quotes_and_numbers_unchanged(self):
        raw=json.dumps({'value':'line\n"α"','n':235,'latex':r'\frac{x}{y}'})
        self.assertEqual(normalize_json_escapes(raw),raw)

if __name__=='__main__':unittest.main()

class BrowserRefreshTests(unittest.TestCase):
    def test_empty_pool_dispatches_new_target_events_without_creating_pages(self):
        from unittest.mock import Mock
        from browser.web_card_pool import refresh_browser_pages
        browser=Mock();session=browser.new_browser_cdp_session.return_value
        refresh_browser_pages(browser)
        session.send.assert_called_once_with('Target.getTargets')
        session.detach.assert_called_once()

class UploadCooldownTests(unittest.TestCase):
    def test_disabled_input_alone_does_not_block_entire_channel(self):
        from unittest.mock import Mock
        from browser.web_card_pool import record_channel_failure
        router=Mock()
        record_channel_failure(router,RuntimeError('网页文件上传入口已禁用，禁止提交附件'))
        router.block.assert_not_called()
    def test_explicit_upload_limit_still_blocks_channel(self):
        from unittest.mock import Mock
        from browser.web_card_pool import record_channel_failure
        router=Mock();record_channel_failure(router,RuntimeError('附件达到上限'))
        self.assertEqual(router.block.call_args.args[0].kind,'quota')


class BlankPageReconciliationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.pages={tid:Mock(url='https://chatgpt.com/') for tid in ('bad','good')}
        self.entries={tid:{'state':'ready_blank','conversation_url':'original-'+tid,'receipt':'keep'} for tid in self.pages}
        self.dispatch=set(self.pages);self.errors=[]
        self.blank={'users':0,'answers':0,'draft':''}

    def reconcile(self,read_page,latest=None,on_error=None):
        from browser.web_card_pool import reconcile_blank_pages
        return reconcile_blank_pages(self.root,self.pages,self.entries,latest or {},self.dispatch,self.errors,
            read_page=read_page,on_error=on_error)

    def assert_no_dom_mutation(self):
        for page in self.pages.values():
            for name in ('close','reload','goto','fill','click','evaluate'):
                getattr(page,name).assert_not_called()

    def test_bad_composer_does_not_prevent_other_page_becoming_available(self):
        from unittest.mock import Mock
        read=Mock(side_effect=[RuntimeError('找不到输入框'),dict(self.blank)])
        failed=self.reconcile(read)
        self.assertEqual(failed,{'bad'})
        self.assertEqual(self.dispatch,{'good'})
        self.assertEqual(self.entries['bad']['state'],'needs_inspection')
        self.assertEqual(self.entries['good']['state'],'ready_blank')
        self.assertEqual(read.call_count,2)
        self.assertIn('bad',self.errors[0]);self.assertIn('找不到输入框',self.errors[0])
        self.assertEqual(self.entries['bad']['conversation_url'],'original-bad')
        self.assert_no_dom_mutation()

    def test_adoption_failure_keeps_original_ledger_and_url_and_probes_other_page(self):
        from unittest.mock import Mock
        path=self.root/'gpt-page-adoption.json'
        path.write_text(json.dumps({'target_id':'bad','state':'pending','original_url':'original-bad','nonce':'original-nonce'}))
        ledger=self.root/'attempt.json';ledger.write_text(json.dumps({'target_id':'bad','state':'not_sent','send_click_started':False}))
        original=ledger.read_bytes();record=json.loads(original)
        read=Mock(side_effect=[RuntimeError('网页错误，没有输入框'),dict(self.blank)])
        self.reconcile(read,latest={'bad':record})
        adoption=json.loads(path.read_text())
        self.assertEqual(adoption['state'],'needs_inspection')
        self.assertEqual(adoption['original_url'],'original-bad')
        self.assertEqual(adoption['nonce'],'original-nonce')
        self.assertEqual(ledger.read_bytes(),original)
        self.assertEqual(record,json.loads(original))
        self.assertEqual(self.entries['bad']['receipt'],'keep')
        self.assertEqual(self.dispatch,{'good'});self.assertEqual(read.call_count,2)
        self.assert_no_dom_mutation()

    def test_blank_homepage_does_not_release_sent_unknown_or_saved_receipt(self):
        from unittest.mock import Mock
        for state in ('submitted','submission_started','needs_inspection','response_saved'):
            with self.subTest(state=state):
                self.entries['bad']['state']='busy';self.dispatch=set(self.pages)
                record={'state':state,'target_id':'bad','conversation_url':'https://chatgpt.com/c/original','send_click_started':True}
                original=dict(record)
                self.reconcile(Mock(return_value=dict(self.blank)),latest={'bad':record})
                self.assertEqual(self.entries['bad']['state'],'needs_inspection')
                self.assertEqual(self.dispatch,{'good'});self.assertEqual(record,original)
                self.assertEqual(self.entries['bad']['conversation_url'],'original-bad')
        self.assert_no_dom_mutation()

    def test_not_sent_requires_explicit_no_click_proof(self):
        from unittest.mock import Mock
        for record in ({'state':'not_sent'}, {'state':'not_sent','send_click_started':True}, {'state':'deferred'}):
            with self.subTest(record=record):
                self.entries['bad']['state']='busy';self.dispatch=set(self.pages)
                self.reconcile(Mock(return_value=dict(self.blank)),latest={'bad':record})
                self.assertEqual(self.entries['bad']['state'],'needs_inspection')
                self.assertNotIn('bad',self.dispatch)
        self.entries['bad']['state']='busy';self.dispatch=set(self.pages)
        self.reconcile(Mock(return_value=dict(self.blank)),latest={'bad':{'state':'not_sent','send_click_started':False}})
        self.assertEqual(self.entries['bad']['state'],'ready_blank');self.assertIn('bad',self.dispatch)
        self.assert_no_dom_mutation()

    def test_unknown_busy_without_ledger_is_not_proof_of_an_unused_page(self):
        from unittest.mock import Mock
        self.entries['bad']['state']='busy'
        self.reconcile(Mock(return_value=dict(self.blank)))
        self.assertEqual(self.entries['bad']['state'],'needs_inspection')
        self.assertNotIn('bad',self.dispatch);self.assertIn('good',self.dispatch)
        self.assert_no_dom_mutation()

    def test_adoption_does_not_mark_uncertain_send_as_adopted(self):
        from unittest.mock import Mock
        path=self.root/'gpt-page-adoption.json'
        path.write_text(json.dumps({'target_id':'bad','state':'pending','nonce':'keep'}))
        self.reconcile(Mock(return_value=dict(self.blank)),latest={'bad':{'state':'not_sent','send_click_started':True}})
        self.assertEqual(json.loads(path.read_text())['state'],'needs_inspection')
        self.assertNotIn('bad',self.dispatch)
        self.assertNotIn('adopted',self.entries['bad'])
        self.assert_no_dom_mutation()

    def test_draft_or_homepage_answer_is_protected_even_with_known_unsent_record(self):
        from unittest.mock import Mock
        for snapshot in ({'users':0,'answers':0,'draft':'保留草稿'}, {'users':0,'answers':1,'draft':''}):
            with self.subTest(snapshot=snapshot):
                self.entries['bad']['state']='busy';self.dispatch=set(self.pages)
                self.reconcile(Mock(side_effect=[snapshot,dict(self.blank)]),latest={'bad':{'state':'not_sent','send_click_started':False}})
                self.assertNotIn('bad',self.dispatch)
                self.assertEqual(self.entries['bad']['state'],'needs_inspection')
        self.assert_no_dom_mutation()

    def test_channel_failure_callback_still_runs_for_verification(self):
        from unittest.mock import Mock
        error=RuntimeError('需要访问验证');callback=Mock()
        self.reconcile(Mock(side_effect=[error,dict(self.blank)]),on_error=callback)
        callback.assert_called_once_with(error,self.pages['bad'])
        self.assertEqual(self.entries['good']['state'],'ready_blank')
        self.assert_no_dom_mutation()

class SubmissionChannelTests(unittest.TestCase):
    def test_healthy_pages_do_not_override_quota_and_expiry_rechecks_without_clear(self):
        import tempfile
        from pathlib import Path
        from browser.web_card_pool import shared_submission_status
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'web-provider-control.json'
            original=json.dumps({'chatgpt':{'blocked_until':200,'explicit_reset':True,'error':'已达上传上限'}})
            path.write_text(original)
            config={'catalog_path':str(root/'catalog.sqlite3'),'web_cards':{'provider':'chatgpt','allowed_providers':['chatgpt']}}
            blocked=shared_submission_status(config,at=199)
            self.assertFalse(blocked['allowed']);self.assertEqual(blocked['state'],'cooldown')
            self.assertEqual(blocked['notice'],'已达上传上限')
            self.assertTrue(shared_submission_status(config,at=200)['allowed'])
            self.assertEqual(path.read_text(),original)
            (root/'web-channel-control.json').write_text('{"chatgpt":{"manual_verification_required":true}}')
            self.assertFalse(shared_submission_status(config,at=201)['allowed'])
            path.write_text('broken')
            invalid=shared_submission_status(config,at=201)
            self.assertFalse(invalid['allowed']);self.assertEqual(invalid['state'],'invalid')

class RoundedQuotaTests(unittest.TestCase):
    def test_zero_minutes_and_past_reset_use_fifteen_minute_probe(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        from browser.upload_quota import reset_time
        from browser.web_card_transport import Router, ProviderFailure
        self.assertIsNone(reset_time('已达上传上限，请等待0分钟后再上传',datetime.now(timezone.utc)))
        with tempfile.TemporaryDirectory() as td:
            router=Router(Path(td))
            with patch('browser.web_card_transport.time.time',return_value=1000):
                router.block(ProviderFailure('已达上传上限，0分钟','chatgpt','quota',True,1000))
            record=json.loads(router.path.read_text())['chatgpt']
            self.assertEqual(record['blocked_until'],1900)
            self.assertFalse(record['explicit_reset'])
            self.assertEqual(record['reset_source'],'cooldown_probe')
class NativeUploadBudgetTests(unittest.TestCase):
    def test_timed_out_native_transfer_keeps_budget_after_client_job_leaves(self):
        from browser.web_card_pool import upload_budget_targets
        from types import SimpleNamespace
        health={'pages':{'old':{'evidence':{'snapshot':{'inspection_complete':True,'uploading':True}}},
                         'completed':{'evidence':{'snapshot':{'inspection_complete':True,'uploading':False}}}}}
        self.assertEqual(upload_budget_targets(SimpleNamespace(targets={'new'}),health),{'old','new'})
        self.assertEqual(upload_budget_targets(None,health),{'old'})
