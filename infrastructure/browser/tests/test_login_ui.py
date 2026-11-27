"""Account UI evidence on disposable DOM and the original observer contract."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

from browser.shared_page_health import LOGIN_UI_SCRIPT,snapshot_page,classify
from browser.web_page_observer import PageObserver,status_script


class LoginDOM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.environ.get(
            'PAPER_TEST_CHROME','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.page=self.browser.new_page()
        self.page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body='<main></main>'))
        self.page.goto('https://chatgpt.com/')
        self.addCleanup(self.page.close)
    def test_visible_login_controls_and_modal_need_no_old_testid(self):
        for html in ('<button>登录</button>','<button aria-label="Log in"></button>',
                     '<div role="button">Sign in</div>',
                     '<div role="dialog"><h1>登录 ChatGPT</h1><button>继续</button></div>',
                     '<a href="https://auth.openai.com/authorize?secret=not-recorded">继续</a>'):
            with self.subTest(html=html):
                self.page.set_content(html)
                account=self.page.evaluate(LOGIN_UI_SCRIPT)
                self.assertTrue(account['login']);self.assertNotIn('not-recorded',json.dumps(account))
                snapshot=snapshot_page('owned',self.page)
                self.assertTrue(snapshot['login'])
                self.assertEqual(classify(snapshot,{'state':'ready_blank'},None)['health'],'login')
    def test_scientific_messages_drafts_hidden_and_unrelated_links_are_not_login(self):
        for html in ('<div data-message-author-role="assistant"><button>Log in</button></div>',
                     '<div data-message-author-role="user"><a href="/auth/login">登录</a></div>',
                     '<div contenteditable="true">请先登录</div>',
                     '<button style="display:none">登录</button>',
                     '<button aria-hidden="true">Sign in</button>',
                     '<a href="https://example.test/auth/login">参考文献</a>',
                     '<main>论文引用 Please log in to continue.</main>'):
            with self.subTest(html=html):
                self.page.set_content(html);self.assertFalse(self.page.evaluate(LOGIN_UI_SCRIPT)['login'])
    def test_auth_redirect_is_recorded_without_query_or_cookie(self):
        self.page.goto('https://auth.openai.com/log-in?token=private')
        account=self.page.evaluate(LOGIN_UI_SCRIPT)
        self.assertTrue(account['login']);self.assertNotIn('private',json.dumps(account))
    def test_ready_requires_visible_account_ui_and_composer_without_ui_error(self):
        good='<button data-testid="accounts-profile-button">Private user name</button><div id="prompt-textarea" contenteditable="true">\n</div>'
        self.page.set_content(good)
        result=self.page.evaluate(LOGIN_UI_SCRIPT)
        self.assertTrue(result['account_ready']);self.assertNotIn('Private user name',json.dumps(result))
        self.page.set_content('<button aria-label="打开个人资料菜单">Private name</button><div role="textbox" contenteditable="true">\n</div>')
        result=self.page.evaluate(LOGIN_UI_SCRIPT)
        self.assertTrue(result['account_ready']);self.assertNotIn('Private name',json.dumps(result))
        for html in ('<div id="prompt-textarea" contenteditable="true"></div>',
                     '<div data-message-author-role="assistant">'+good+'</div>',
                     good+'<div role="alert">上传已达上限</div>',
                     good+'<div role="alert">浏览器检查未能完成，请重新加载</div>'):
            with self.subTest(html=html):
                self.page.set_content(html);self.assertFalse(self.page.evaluate(LOGIN_UI_SCRIPT)['account_ready'])

    def observer_status(self, html):
        from web_gpt.core import ANSWER,STOP_BUTTON,SEND_BUTTONS
        self.page.set_content(html)
        return self.page.evaluate(status_script(),{'answer':ANSWER,'stop':STOP_BUTTON,'send':SEND_BUTTONS})

    def test_status_distinguishes_current_assistant_completion_from_old_reply_and_user_turn(self):
        assistant='<article data-talvt-turn-state="complete"><div data-message-author-role="assistant">Original reply</div></article>'
        result=self.observer_status(assistant)
        self.assertTrue(result['complete']);self.assertFalse(result['streaming']);self.assertEqual(result['answers'],1)
        result=self.observer_status(assistant+'<article data-talvt-turn-state="complete"><div data-message-author-role="user">New request</div></article>')
        self.assertFalse(result['complete'])
        result=self.observer_status(assistant+'<button data-testid="stop-button">Stop</button>')
        self.assertTrue(result['streaming'])
        result=self.observer_status(assistant+'<button data-testid="stop-button" hidden>Stop</button>')
        self.assertFalse(result['streaming'])

    def test_gray_send_without_progress_is_unready_evidence_not_proof_of_uploading(self):
        for draft in ('','Original prompt'):
            with self.subTest(draft=draft):
                result=self.observer_status('<form><div role="textbox" contenteditable="true">'+draft+'</div><div data-testid="attachment-preview">original.zip</div><button data-testid="send-button" aria-disabled="true">Send</button></form>')
                self.assertTrue(result['send_button_present']);self.assertTrue(result['send_button_disabled'])
                self.assertFalse(result['upload_indicator_visible']);self.assertFalse(result['streaming'])
        result=self.observer_status('<form><div role="textbox" contenteditable="true">Prompt</div><button data-testid="send-button">Send</button><div role="progressbar">Uploading</div></form>')
        self.assertFalse(result['send_button_disabled']);self.assertTrue(result['upload_indicator_visible'])

    def test_historical_quota_strings_never_block_a_current_clean_page(self):
        from browser.upload_quota import visible_notice
        self.page.set_content('<form><div id="prompt-textarea" contenteditable="true"></div><input type="file"></form>')
        self.page.evaluate('''() => Object.defineProperty(window, '__paperUploadNotices', {
          configurable: true, get() { throw new Error('historical cache must not be read'); }})''')
        self.assertIsNone(visible_notice(self.page))
        from browser.web_card_transport import wait_gpt_upload_ready
        # The exact old loop: a ready native input must pass without opening a
        # menu or consuming an old cached "seven minutes" notice.
        wait_gpt_upload_ready(self.page,1000)

    def test_formula_zip_probe_matches_real_document_controls(self):
        from browser.web_card_transport import attachment_entry, wait_gpt_upload_ready
        editor = '<form><div id="prompt-textarea" contenteditable="true"></div>'
        for html, ready in [
            ('<input type="file" accept="image/*"></form>',False),
            ('<input type="file" capture></form>',False),
            ('</form><form><input type="file" aria-label="Upload files"></form>',False),
            ('</form><input type="file" aria-label="Upload files" accept=".zip">',True),
            ('<input type="file"></form><button role="menuitem" aria-disabled="true">Upload files</button>',False),
        ]:
            with self.subTest(html=html):
                self.page.set_content(editor+html)
                self.assertEqual(attachment_entry(self.page)['ready'],ready)
                if ready:
                    wait_gpt_upload_ready(self.page,500)

    def test_live_relative_notice_keeps_first_seen_deadline_across_reads(self):
        from browser.upload_quota import visible_notice
        self.page.set_content('<div role="menu">已达上传上限<br>请等待 7分钟 后再上传</div>')
        first=visible_notice(self.page);second=visible_notice(self.page)
        self.assertTrue(first);self.assertEqual(first['not_before_utc'],second['not_before_utc'])
        self.assertEqual(first['first_observed_at'],second['first_observed_at'])
        self.assertEqual(first['notice_id'],second['notice_id'])
        self.assertEqual(first['read_kind'],'current_visible_ui')
        self.assertEqual(first['evidence_version'],2)

    def test_current_quota_without_reset_and_expired_relative_notice_remain_blocking(self):
        from browser.upload_quota import visible_notice
        from browser.web_card_transport import wait_gpt_upload_ready
        for message in ('已达上传上限','已达上传上限<br>请等待 7分钟 后再上传'):
            with self.subTest(message=message):
                self.page.set_content('<form><div id="prompt-textarea" contenteditable="true"></div><input type="file"></form><div role="alert">'+message+'</div>')
                first=visible_notice(self.page)
                if '7分钟' in message:
                    self.page.evaluate('() => { for (const item of window.__paperQuotaLiveState.active) item.first -= 3600; }')
                notice=visible_notice(self.page)
                self.assertTrue(notice);self.assertIsNone(notice['not_before_utc'])
                with self.assertRaisesRegex(RuntimeError,'附件额度限制'):
                    wait_gpt_upload_ready(self.page,1000)

    def test_removed_quota_does_not_survive_as_live_or_reuse_a_new_notice_identity(self):
        from browser.upload_quota import visible_notice
        self.page.set_content('<div role="dialog">已达上传上限<br>请等待 7分钟 后再上传</div>')
        first=visible_notice(self.page)
        self.page.set_content('<main><div id="prompt-textarea" contenteditable="true"></div></main>')
        self.assertIsNone(visible_notice(self.page))
        self.page.set_content('<div role="dialog">已达上传上限<br>请等待 7分钟 后再上传</div>')
        second=visible_notice(self.page)
        self.assertNotEqual(first['notice_id'],second['notice_id'])

    def test_quota_words_in_science_drafts_sidebar_and_hidden_ui_never_block(self):
        from browser.upload_quota import visible_notice
        for html in ('<div data-message-author-role="assistant"><div role="alert">已达上传上限 请等待7分钟</div></div>',
                     '<div contenteditable="true"><div role="alert">已达上传上限 请等待7分钟</div></div>',
                     '<aside><div role="alert">已达上传上限 请等待7分钟</div></aside>',
                     '<div role="alert" hidden>已达上传上限 请等待7分钟</div>',
                     '<main>原文引用：已达上传上限，请等待7分钟</main>'):
            with self.subTest(html=html):
                self.page.set_content(html);self.assertIsNone(visible_notice(self.page))

    def test_live_unknown_quota_uses_cooldown_without_claiming_a_site_reset(self):
        from unittest.mock import patch
        from browser.web_card_transport import Router
        from browser.web_card_pool import record_channel_failure
        self.page.set_content('<div role="alert">已达上传上限</div>')
        with tempfile.TemporaryDirectory() as folder:
            router=Router(folder)
            with patch('browser.web_card_transport.time.time',return_value=1000):
                record_channel_failure(router,RuntimeError('unready'),self.page)
            record=json.loads((Path(folder)/'web-provider-control.json').read_text())['chatgpt']
            self.assertEqual(record['reason'],'quota');self.assertEqual(record['blocked_until'],1900)
            self.assertFalse(record['explicit_reset']);self.assertEqual(record['reset_source'],'cooldown_probe')


class LoginObserver(unittest.IsolatedAsyncioTestCase):
    async def test_auth_redirect_and_other_hosts_never_read_conversation_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            observer=PageObserver(folder,SimpleNamespace(_loop=asyncio.get_running_loop()))
            page=Mock(url='https://auth.openai.com/log-in')
            page.evaluate=AsyncMock(return_value={'login':True,'login_evidence':[{'source':'auth_location','text':'auth.openai.com/log-in'}]})
            self.assertEqual((await observer.inspect('own',page,[page.url],{}))['state'],'login_required')
            page.url='https://example.test/';page.evaluate=AsyncMock(return_value={'login':False})
            self.assertEqual((await observer.inspect('own',page,[page.url],{}))['state'],'inspection_required')
            page.locator.assert_not_called()

    async def test_login_is_reported_before_message_reads_and_persists_target_and_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'shared-gpt-window.json').write_text(json.dumps({'slots':[{'slot_id':'02','target_id':'own'}]}))
            (root/'web-channel-control.json').write_text(json.dumps({'qwen':{'manual_verification_required':True}}))
            observer=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
            evidence=[{'source':'visible_login_control','text':'登录'}]
            page=Mock(url='https://chatgpt.com/');page.evaluate=AsyncMock(return_value={'login':True,'login_detection_version':2,'login_evidence':evidence})
            result=await observer.inspect('own',page,[page.url],{})
            self.assertEqual(result['state'],'login_required');page.locator.assert_not_called()
            control=json.loads((root/'web-channel-control.json').read_text())
            self.assertTrue(control['qwen']['manual_verification_required'])
            self.assertEqual(control['chatgpt']['block_kind'],'login')
            self.assertEqual(control['chatgpt']['login_targets']['own']['slot_id'],'02')
            self.assertIn('02',control['chatgpt']['reason'])
            before=(root/'control-events.jsonl').read_bytes()
            await observer.inspect('own',page,[page.url],{})
            self.assertEqual((root/'control-events.jsonl').read_bytes(),before)
            page.evaluate=AsyncMock(return_value={'login':False});empty=Mock();empty.count=AsyncMock(return_value=0);page.locator.return_value=empty
            await observer.inspect('own',page,[page.url],{})
            self.assertTrue(json.loads((root/'web-channel-control.json').read_text())['chatgpt']['manual_verification_required'])
