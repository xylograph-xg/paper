import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime,timezone
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from browser.upload_quota import reset_time, unsent_page
from browser.web_upload_retry import scope


class ResetParsing(unittest.TestCase):
    observed=datetime(2026,10,6,21,14,tzinfo=timezone.utc)
    def test_real_chinese_notice(self):
        reset=reset_time('你已达到文件附件数量限制\n请于 10月7日 6:11 后重试',self.observed)
        self.assertEqual(reset.isoformat(),'2026-10-06T22:11:00+00:00')
    def test_native_attachment_menu_wait_one_hour(self):
        reset=reset_time('已达上传上限\n请等待 1小时 后再上传',self.observed)
        self.assertEqual(reset.isoformat(),'2026-10-06T22:14:00+00:00')
    def test_tomorrow_relative_and_english(self):
        self.assertEqual(reset_time('Upload limit reached. Try again at October 7, 2026 6:11 AM',self.observed).isoformat(),'2026-10-06T22:11:00+00:00')
        self.assertEqual(reset_time('上传次数限制\n请在明天 06:11 重试',self.observed).isoformat(),'2026-10-07T22:11:00+00:00')
        self.assertEqual(reset_time('Upload limit reached. Try again in 20 minutes',self.observed).isoformat(),'2026-10-06T21:34:00+00:00')
    def test_unknown_or_unrelated_times_are_not_guessed(self):
        for text in ('附件上传失败','上传上限\n6:11','本次报告于06:11完成','上传上限\n请于10月7日 25:11后重试','Upload limit reached. Try again at 01:00'):
            self.assertIsNone(reset_time(text,self.observed))

    def test_upgrade_or_retry_native_notice(self):
        observed=datetime(2026,10,25,21,14,tzinfo=timezone.utc)
        text='你目前已用完附件额度。请升级套餐获取更多额度，或在 05:48 后 后重试。\n升级至 Pro'
        self.assertEqual(reset_time(text,observed),datetime(2026,10,25,21,48,tzinfo=timezone.utc))

    def test_optional_retry_clause_requires_retry_instruction(self):
        for text in ('附件额度用完，或在 06:11 后重试。',
                     '附件额度用完，可于 06：11 后再上传。'):
            with self.subTest(text=text):
                self.assertEqual(reset_time(text,self.observed),datetime(2026,10,6,22,11,tzinfo=timezone.utc))
        for text in ('附件额度用完，或在 06:11 查看套餐。',
                     '附件额度用完，或在 06:11 查看套餐。之后再重试。',
                     '附件额度用完，或在 01:00 后重试。'):
            with self.subTest(text=text):self.assertIsNone(reset_time(text,self.observed))

    def test_native_optional_retry_visible_notice_preserves_evidence(self):
        from unittest.mock import Mock
        from browser.upload_quota import visible_notice
        text='附件额度已用完，或在 06:11 后重试。'
        page=Mock();page.evaluate.return_value={'version':2,'notices':[
            {'text':text,'notice_id':'native-quota:1','first_seen_at':self.observed.timestamp()}]}
        with patch('browser.upload_quota.datetime') as clock:
            clock.now.return_value=self.observed
            clock.fromtimestamp.side_effect=datetime.fromtimestamp
            result=visible_notice(page)
        self.assertEqual(result['not_before_utc'],'2026-10-06T22:11:00+00:00')
        self.assertEqual(result['notice'],text)
        self.assertEqual(result['notice_id'],'native-quota:1')
        self.assertEqual(result['first_observed_at'],self.observed.isoformat())

    def test_incomplete_quota_read_fails_closed(self):
        from unittest.mock import Mock
        from browser.upload_quota import visible_notice
        for value in (None,[],{'version':2},{'version':2,'notices':[{'text':'已达上传上限','first_seen_at':float('nan'),'notice_id':'x'}]}):
            with self.subTest(value=value):
                page=Mock();page.evaluate.return_value=value
                with self.assertRaises(ValueError):visible_notice(page)


class SafeRetry(unittest.TestCase):
    def module(self):
        path=__import__('core.api',fromlist=['paths__workspace_root']).paths__workspace_root()/'data/web_card_loops/20261007_five_papers/run_round.py'
        if not path.is_file():self.skipTest('Retired experiment integration fixture is not present')
        spec=importlib.util.spec_from_file_location('quota_test_runner',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_only_explicit_quota_and_unsent_page_retry_once(self):
        module=self.module()
        reset={'not_before_utc':'2020-01-01T00:00:00+00:00','retry_after_shanghai':'2020-01-01 08:00'}
        class Page:
            url='https://chatgpt.com/'
            def evaluate(self,_):pass
        class GPT:
            page=Page()
            calls=0
            def verify_settings(self):return {'model':'frozen'}
            def submit(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:raise RuntimeError('附件上传失败')
                self.page.url='https://chatgpt.com/c/test'
                return 0
        g=GPT()
        @contextmanager
        def session(*args):yield g
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);folder=base/'review';folder.mkdir();prompt=base/'prompt.txt';prompt.write_text('test');pdf=base/'paper.pdf';pdf.write_bytes(b'frozen')
            (base/'loop.json').write_text(json.dumps({'state':'running_round'}))
            with patch.object(module,'HERE',base),patch.object(module,'session_factory',session),patch.object(module,'retry_session',session),patch.object(module,'browser_count',return_value=1),patch.object(module,'page_target',return_value='exact-target'),patch.object(module,'visible_notice',return_value=reset),patch.object(module,'unsent_page',return_value=True):
                result=module.submit(folder,prompt,[pdf],'marker',20)
            self.assertEqual(result['state'],'submitted')
            self.assertEqual(g.calls,2)
            self.assertEqual(result['quota_retry_windows'],[reset['not_before_utc']])
            self.assertTrue((folder/'quota-attempt-1.json').exists())

    def test_uncertain_upload_failure_is_not_retried(self):
        module=self.module()
        class GPT:
            class page:
                url='https://chatgpt.com/'
                @staticmethod
                def evaluate(_):pass
            def verify_settings(self):return {}
            def submit(self,*args,**kwargs):raise RuntimeError('附件上传失败')
        @contextmanager
        def session():yield GPT()
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);folder=base/'review';folder.mkdir();prompt=base/'prompt.txt';prompt.write_text('test')
            (base/'loop.json').write_text(json.dumps({'state':'running_round'}))
            with patch.object(module,'HERE',base),patch.object(module,'session_factory',session),patch.object(module,'browser_count',return_value=1),patch.object(module,'page_target',return_value='target'),patch.object(module,'visible_notice',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'附件上传失败'):module.submit(folder,prompt,[],'marker',20)
            self.assertEqual(json.loads((folder/'web-attempt.json').read_text())['state'],'needs_inspection')
            self.assertFalse((base/'upload-control.json').exists())

    def test_input_change_blocks_saved_retry_before_browser_use(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);folder=base/'review';folder.mkdir();prompt=base/'prompt.txt';prompt.write_text('modified')
            (folder/'web-attempt.json').write_text(json.dumps({'state':'waiting_upload_quota','unsent_verified':True,'prompt_sha256':'old','files_sha256':{},'attribution_marker':'marker'}))
            with self.assertRaisesRegex(RuntimeError,'frozen inputs changed'):module.submit(folder,prompt,[],'marker',20)

    def test_scope_cannot_expand_to_old_model_directories(self):
        with self.assertRaises(ValueError):scope('/tmp/local_model')


class Scheduler(unittest.TestCase):
    def check(self, reset, owner=None):
        from browser import web_upload_retry as scheduler
        class EndTick(Exception):pass
        class Child:
            pid=12345
            def poll(self):return None
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);folder=base/'round-02/paper';review=folder/'review';review.mkdir(parents=True)
            (review/'web-attempt.json').write_text(json.dumps({'state':'waiting_upload_quota','upload_quota':{'not_before_utc':reset},'quota_wait_pid':owner}))
            loop={'active_round':2,'state':'running_round'};samples=[(folder,{'kind':'paper'})]
            with patch.object(scheduler,'scope',return_value=(base,loop,samples)),patch.object(scheduler,'capture',return_value=0),patch.object(scheduler,'alive',return_value=bool(owner)),patch.object(scheduler.subprocess,'Popen',return_value=Child()) as start,patch.object(scheduler.time,'sleep',side_effect=EndTick):
                with self.assertRaises(EndTick):scheduler.watch(base)
                return start.call_args
    def test_before_reset_does_not_launch(self):
        self.assertIsNone(self.check('2099-01-01T00:00:00+00:00'))
    def test_at_reset_launches_only_the_blocked_sample(self):
        call=self.check('2000-01-01T00:00:00+00:00')
        self.assertIsNotNone(call)
        self.assertIn('--resume-sample',call.args[0])
        self.assertEqual(call.args[0][-1],'paper')
    def test_active_original_worker_prevents_duplicate(self):
        self.assertIsNone(self.check('2000-01-01T00:00:00+00:00',owner=123))
