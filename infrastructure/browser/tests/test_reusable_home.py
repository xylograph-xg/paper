import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from browser.reusable_home import prepare
from browser.shared_browser_window import WindowIsolationError


class ReusableHome(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.snapshot = {'inspection_complete':True,'url':'https://chatgpt.com/',
                         'composer_available':True,'draft':'','user_texts':[],
                         'answer_texts':[],'attachments':0,'streaming':False}
        self.enterContext(patch('browser.reusable_home.snapshot_page',side_effect=lambda *a:self.snapshot))
        self.enterContext(patch('web_gpt.core.wait_prompt_box'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def archived(self, answer='archived reply', url='https://chatgpt.com/c/original'):
        raw = Path(self.tmp.name) / 'response-raw.txt'
        raw.write_text(answer)
        self.snapshot.update(url=url, user_texts=['original question'], answer_texts=[answer])
        return {'state':'ready','raw_path':str(raw),
                'raw_sha256':hashlib.sha256(answer.encode()).hexdigest(),'conversation_url':url}

    def test_empty_home_waits_for_model_controls_without_network_reload(self):
        self.assertTrue(prepare(self.page)['reused_verified_home'])
        self.page.goto.assert_not_called()
        self.page.get_by_role.return_value.wait_for.assert_called_once_with(state='visible',timeout=30000)

    def test_saved_conversation_still_navigates_home_after_original_reuse_guard(self):
        self.snapshot['url']='https://chatgpt.com/c/original'
        self.assertFalse(prepare(self.page)['reused_verified_home'])
        self.page.goto.assert_called_once_with('https://chatgpt.com/',wait_until='domcontentloaded',timeout=60000)

    def test_changed_draft_attachment_or_unknown_observation_never_navigates(self):
        for changes in ({'draft':'user edit'},{'attachments':1},{'uploading':True},{'streaming':True},
                        {'inspection_complete':False},{'verification':True},{'errors':['site error']}):
            with self.subTest(changes=changes):
                saved=dict(self.snapshot);self.snapshot.update(changes)
                with self.assertRaises(WindowIsolationError):prepare(self.page)
                self.page.goto.assert_not_called();self.snapshot=saved

    def test_site_block_on_exactly_archived_reply_navigates_home(self):
        saved = self.archived()
        self.snapshot['errors'] = ['站点加载失败：Unable to load site（Cloudflare/IP 拦截）']
        self.assertFalse(prepare(self.page, saved=saved)['reused_verified_home'])
        self.page.goto.assert_called_once_with('https://chatgpt.com/', wait_until='domcontentloaded', timeout=60000)

    def test_error_notice_without_exact_archived_reply_never_navigates(self):
        saved = self.archived()
        self.snapshot['errors'] = ['站点加载失败：Unable to load site（Cloudflare/IP 拦截）']
        cases = {
            'no saved entry': None,
            'answer changed': {**saved, 'raw_sha256': '0' * 64},
            'raw file missing': {**saved, 'raw_path': str(Path(self.tmp.name) / 'missing.txt')},
            'url changed': {**saved, 'conversation_url': 'https://chatgpt.com/c/other'},
            'second turn': {**saved},
        }
        for name, entry in cases.items():
            with self.subTest(name):
                self.page.goto.reset_mock()
                extra = {'answer_texts': ['archived reply', 'new reply']} if name == 'second turn' else {}
                original = dict(self.snapshot)
                self.snapshot.update(extra)
                with self.assertRaises(WindowIsolationError):
                    prepare(self.page, saved=entry)
                self.page.goto.assert_not_called()
                self.snapshot = original

    def test_error_notice_with_draft_never_uses_archived_reply_as_escape(self):
        saved = self.archived()
        self.snapshot.update(errors=['site error'], draft='user typing')
        with self.assertRaises(WindowIsolationError): prepare(self.page, saved=saved)
        self.page.goto.assert_not_called()

    def test_composer_ready_but_missing_model_controls_cannot_reach_configuration(self):
        self.page.get_by_role.return_value.wait_for.side_effect=RuntimeError('model controls missing')
        with self.assertRaisesRegex(RuntimeError,'model controls missing'):prepare(self.page)
        self.page.goto.assert_not_called()
