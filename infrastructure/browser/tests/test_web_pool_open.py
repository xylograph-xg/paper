import unittest
from browser.web_pool_open import eligible

class OpenedPageTests(unittest.TestCase):
    def test_blank_user_opened_page_eligible(self):
        self.assertTrue(eligible('new','https://chatgpt.com/',0,0,''))
    def test_history_draft_and_other_provider_rejected(self):
        for url,users,answers,draft in [('https://chatgpt.com/c/old',0,0,''),('https://chatgpt.com/',1,0,''),('https://chatgpt.com/',0,1,''),('https://chatgpt.com/',0,0,'draft'),('https://chat.qwen.ai/',0,0,'')]:
            self.assertFalse(eligible('new',url,users,answers,draft))
    def test_unknown_prior_submission_cannot_be_released(self):
        for state in ('submitted','submission_started','needs_inspection','response_saved'):
            self.assertFalse(eligible('old','https://chatgpt.com/',0,0,'',{'state':state}))
    def test_busy_or_uncertain_pool_entry_protected(self):
        for state in ('busy','needs_inspection'):
            self.assertFalse(eligible('old','https://chatgpt.com/',0,0,'',None,{'state':state}))
    def test_proved_unsent_is_allowed(self):
        self.assertTrue(eligible('new','https://chatgpt.com/',0,0,'',{'state':'not_sent'},{'state':'ready_blank'}))

if __name__=='__main__':unittest.main()

class ExplicitStartupPageTests(unittest.TestCase):
    def test_empty_browser_opens_one_page_and_dispatches_events(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from browser.web_pool_open import ensure_startup_page
        context=SimpleNamespace(pages=[]);session=Mock()
        def send(method,*args):
            if method=='Target.getTargets':context.pages=[SimpleNamespace(url='https://chatgpt.com/')]
        session.send.side_effect=send
        browser=SimpleNamespace(contexts=[context],new_browser_cdp_session=Mock(return_value=session))
        ensure_startup_page(browser)
        self.assertEqual(sum(c.args[0]=='Target.createTarget' for c in session.send.call_args_list),1)
        self.assertTrue(any(c.args[0]=='Target.getTargets' for c in session.send.call_args_list))
        ensure_startup_page(browser)
        self.assertEqual(browser.new_browser_cdp_session.call_count,1)
    def test_full_browser_does_not_open_another_page(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from browser.web_pool_open import ensure_startup_page
        browser=SimpleNamespace(contexts=[SimpleNamespace(pages=[SimpleNamespace(url='https://example.com/') for _ in range(20)])],new_browser_cdp_session=Mock())
        with self.assertRaises(ValueError):ensure_startup_page(browser)
        browser.new_browser_cdp_session.assert_not_called()
