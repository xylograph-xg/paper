from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from browser.browser_inventory import enumerate_pages


class BrowserInventory(unittest.TestCase):
    def test_same_page_target_binding_is_reused_without_repeated_renderer_attach(self):
        page=Mock(url='https://chatgpt.com/');page.is_closed.return_value=False
        context=Mock(pages=[page]);context.new_cdp_session.return_value.send.return_value={'targetInfo':{'targetId':'original'}}
        browser=SimpleNamespace(contexts=[context],is_connected=lambda:True)
        self.assertTrue(enumerate_pages(browser)['complete'])
        context.new_cdp_session.side_effect=RuntimeError('renderer attach temporarily unavailable')
        result=enumerate_pages(browser)
        self.assertTrue(result['complete']);self.assertIs(result['pages']['original'],page)
        self.assertEqual(context.new_cdp_session.call_count,1)
        page.is_closed.return_value=True
        self.assertEqual(enumerate_pages(browser)['pages'],{})

    def test_failed_detach_is_not_cached_and_disconnected_browser_is_not_adopted(self):
        page=Mock(url='https://chatgpt.com/');page.is_closed.return_value=False
        context=Mock(pages=[page]);session=context.new_cdp_session.return_value
        session.send.return_value={'targetInfo':{'targetId':'original'}}
        session.detach.side_effect=RuntimeError('unknown detach')
        browser=SimpleNamespace(contexts=[context],is_connected=lambda:True)
        self.assertFalse(enumerate_pages(browser)['complete'])
        self.assertFalse(enumerate_pages(browser)['complete'])
        self.assertEqual(context.new_cdp_session.call_count,2)
        browser.is_connected=lambda:False
        self.assertFalse(enumerate_pages(browser)['complete'])
        self.assertEqual(enumerate_pages(browser)['pages'],{})

    def page(self,url='https://chatgpt.com/'):
        return SimpleNamespace(url=url,is_closed=lambda:False)

    def test_closing_page_does_not_discard_other_targets_or_undercount_capacity(self):
        first=self.page();second=self.page();session=Mock()
        session.send.return_value={'targetInfo':{'targetId':'valid'}}
        context=Mock(pages=[first,second]);context.new_cdp_session.side_effect=[RuntimeError('page no object with guid'),session]
        result=enumerate_pages(SimpleNamespace(contexts=[context]),{'chatgpt.com'})
        self.assertEqual(result['pages'],{'valid':second});self.assertEqual(result['total_pages'],2)
        self.assertFalse(result['complete']);session.detach.assert_called_once()

    def test_failed_target_lookup_still_detaches_and_never_closes_pages(self):
        page=Mock(url='https://chatgpt.com/');page.is_closed.return_value=False
        context=Mock(pages=[page]);session=context.new_cdp_session.return_value
        session.send.side_effect=RuntimeError('target vanished')
        result=enumerate_pages(SimpleNamespace(contexts=[context]))
        session.detach.assert_called_once();page.close.assert_not_called();self.assertFalse(result['complete'])

    def test_other_projects_pages_count_toward_limit_without_being_adopted(self):
        page=self.page('https://example.test/');context=Mock(pages=[page])
        result=enumerate_pages(SimpleNamespace(contexts=[context]),{'chatgpt.com'})
        self.assertEqual(result['total_pages'],1);self.assertEqual(result['pages'],{});self.assertTrue(result['complete'])
        context.new_cdp_session.assert_not_called()
