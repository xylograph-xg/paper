"""Regression: publisher URL must never become an equation explanation."""
import sys
import unittest
from core.api import paths__WorkspacePath as Path

sys.path.insert(0,str(__import__('core.api',fromlist=['paths__workspace_root']).paths__workspace_root()/'read/app'))
from parser import _is_display_equation_text


class ReaderRegression(unittest.TestCase):
    def test_publisher_notice_and_citation_links_are_not_equations(self):
        self.assertFalse(_is_display_equation_text('Reprints and permission information is available at http://www.nature.com/reprints'))
        self.assertFalse(_is_display_equation_text('https://doi.org/10.1000/example'))
        self.assertFalse(_is_display_equation_text('Contact: scientist@example.org'))

    def test_actual_equations_remain_candidates(self):
        self.assertTrue(_is_display_equation_text('k_total = k_r + k_nr'))
        self.assertTrue(_is_display_equation_text('E = h * nu'))
