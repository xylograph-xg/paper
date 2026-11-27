import unittest
from review.review_tabs import close_page


class Tabs(unittest.TestCase):
    def page(self, text, generating=False):
        class Locator:
            def __init__(self, stop=False):self.stop=stop
            def count(self):return int(generating) if self.stop else 1
            def nth(self,i):return self
            def is_visible(self):return generating
            @property
            def last(self):return self
        class Page:
            closed=False
            def locator(self,s):return Locator(s=='stop')
            def close(self):self.closed=True
        return Page()

    def test_saved_answer_closed_even_when_scientific_review_failed(self):
        p=self.page('revise')
        self.assertEqual(close_page(p,'revise','answer','stop',lambda _: 'revise'),'closed')
        self.assertTrue(p.closed)

    def test_running_and_changed_answers_remain_open(self):
        for running,text,expected in [(True,'saved','generating'),(False,'new','answer_changed')]:
            p=self.page(text,running)
            self.assertEqual(close_page(p,'saved','answer','stop',lambda _:text),expected)
            self.assertFalse(p.closed)
