import hashlib
import unittest
import json
import tempfile
from core.api import paths__WorkspacePath as Path
from unittest.mock import Mock, AsyncMock

from browser.web_message_text import read_user_text, read_user_text_async, select_user_text, expand_original_user
from browser.web_card_pool import identify


class FullUserTextTests(unittest.TestCase):
    def setUp(self):
        self.pid = '12345678-1234-1234-1234-123456789abc'
        self.prompt = 'web-card-' + self.pid + '-material\n完整规则与附件约定'
        self.url = 'https://chatgpt.com/c/original'
        self.attempt = {'actual_prompt_sha256': hashlib.sha256(self.prompt.encode()).hexdigest(),
                        'conversation_url': self.url}
        self.page = Mock(); self.page.url = self.url
        self.users = self.page.locator.return_value; self.users.count.return_value = 1
        self.users.first.evaluate.return_value = [self.prompt, self.prompt[:20] + '显示更多']

    def test_full_dom_text_recovers_folded_display_and_keeps_identity(self):
        self.assertEqual(identify(self.page, self.attempt, self.prompt), self.pid)
        self.page.goto.assert_not_called(); self.users.first.click.assert_not_called()

    def test_only_truncated_text_never_qualifies(self):
        self.users.first.evaluate.return_value = [self.prompt[:20], self.prompt[:20]]
        with self.assertRaises(ValueError): identify(self.page, self.attempt, self.prompt)

    def test_multi_turn_or_changed_original_url_still_blocks(self):
        self.users.count.return_value = 2
        with self.assertRaises(ValueError): identify(self.page, self.attempt, self.prompt)
        self.users.count.return_value = 1; self.page.url = 'https://chatgpt.com/c/other'
        with self.assertRaises(ValueError): identify(self.page, self.attempt, self.prompt)

    def test_changed_prompt_hash_and_multiple_markers_still_block(self):
        with self.assertRaises(ValueError): identify(self.page, self.attempt, self.prompt + 'changed')
        self.users.first.evaluate.return_value = [self.prompt + '\nweb-card-' + self.pid + '-duplicate']
        with self.assertRaises(ValueError): identify(self.page, self.attempt, self.prompt)

    def test_matching_visible_variant_and_unavailable_dom(self):
        self.assertEqual(select_user_text(['unrelated hidden text', self.prompt], self.prompt), self.prompt)
        self.assertEqual(select_user_text(['', '']), '')
        with self.assertRaises(ValueError): select_user_text(None)
        self.users.first.evaluate.side_effect = TimeoutError('DOM timeout')
        with self.assertRaises(TimeoutError): read_user_text(self.users.first, self.prompt)


class AsyncFullTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_observer_reads_same_complete_variant(self):
        locator = Mock(); locator.evaluate = AsyncMock(return_value=['full original prompt', 'full...'])
        self.assertEqual(await read_user_text_async(locator, 'full original prompt'), 'full original prompt')
        locator.click.assert_not_called()


class ExpansionGuardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.prompt = 'web-card-12345678-1234-1234-1234-123456789abc-' + '原文通用规则' * 100
        (self.root/'prompt-actual.txt').write_text(self.prompt)
        self.record = {'target_id':'own', 'state':'needs_inspection',
            'conversation_url':'https://chatgpt.com/c/original',
            '_ledger_path':str(self.root/'attempt.json'),
            'actual_prompt_sha256':hashlib.sha256(self.prompt.encode()).hexdigest()}
        self.snapshot = {'inspection_complete':True, 'streaming':False, 'user_texts':[self.prompt[:220]+'…显示更多'],
                         'url':self.record['conversation_url']}
        self.page = Mock(); self.page.url = self.snapshot['url']; self.page.evaluate.return_value = True

    def test_only_local_expansion_and_no_receipt_write(self):
        result = expand_original_user(self.page,self.record,self.snapshot,target_id='own')
        self.assertEqual(result['state'],'expanded'); self.page.evaluate.assert_called_once()
        self.page.goto.assert_not_called(); self.assertFalse((self.root/'attempt.json').exists())

    def test_empty_newline_draft_allows_only_bound_local_expansion(self):
        result=expand_original_user(self.page,self.record,{**self.snapshot,'draft':' \n '},target_id='own')
        self.assertEqual(result['state'],'expanded');self.page.evaluate.assert_called_once()
        self.page.goto.assert_not_called()

    def test_pause_sensitive_page_states_and_multiple_users_block_click(self):
        for key,value in [('streaming',True),('login',True),('verification',True),('quota',True),('draft','unsent'),
                          ('attachments',1),('errors',['unknown']),('user_texts',['one','two'])]:
            with self.subTest(key=key):
                self.assertIsNone(expand_original_user(self.page,self.record,{**self.snapshot,key:value},target_id='own'))
        self.page.evaluate.assert_not_called()

    def test_changed_target_url_hash_or_unrelated_prefix_blocks(self):
        for record in [{**self.record,'target_id':'foreign'},{**self.record,'conversation_url':'https://chatgpt.com/c/other'},
                       {**self.record,'actual_prompt_sha256':'changed'},{**self.record,'state':'not_sent'}]:
            self.assertIsNone(expand_original_user(self.page,record,self.snapshot,target_id='own'))
        self.assertIsNone(expand_original_user(self.page,self.record,{**self.snapshot,'user_texts':['unrelated']},target_id='own'))
        self.page.evaluate.assert_not_called()

    def test_complete_prompt_is_read_only_and_missing_button_does_not_accept_prefix(self):
        self.assertIsNone(expand_original_user(self.page,self.record,{**self.snapshot,'user_texts':[self.prompt]},target_id='own'))
        self.page.evaluate.assert_not_called(); self.page.evaluate.return_value = False
        result = expand_original_user(self.page,self.record,self.snapshot,target_id='own')
        self.assertEqual(result['state'],'no_unique_expand_button')


if __name__ == '__main__': unittest.main()
