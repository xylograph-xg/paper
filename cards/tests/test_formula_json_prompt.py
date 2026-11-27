import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from cards.web_card_inputs import ROOT, prepare, digest

class FormulaJSONPrompt(unittest.TestCase):
    def test_frozen_rules_and_actual_prompt_preserve_escaped_commands(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.pdf'
            doc=pymupdf.open();doc.new_page();doc.save(source);doc.close()
            folder=root/'inputs';prepare(source,folder,'test','synthetic',digest(source))
            prompt=(folder/'prompt.txt').read_text()
            rules=json.loads((folder/'source-context.json').read_text())['scientific_rules']
            expected=r'{"latex":"\\frac{a}{b}"}'
            self.assertIn(expected,prompt);self.assertIn(expected,rules)
            self.assertEqual(json.loads(expected)['latex'],r'\frac{a}{b}')
            self.assertFalse(any(ord(c)<32 for c in json.loads(expected)['latex']))
            self.assertIn('最终JSON中必须写四个反斜线',rules)
            for rule in ('P{source_page:03d}','范围为1至本请求注明的原文总页数N','所有必填字符串必须是非空字符串','解码后必须成为真正换行'):
                self.assertIn(rule,prompt);self.assertIn(rule,rules)
