"""Core conclusions are required in the same generated card response."""
import json
import tempfile
import unittest
from copy import deepcopy
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from cards.web_card_inputs import parse_card, prepare, digest, WORK_SUMMARY_VERSION


class CardFindings(unittest.TestCase):
    def test_missing_or_blank_core_findings_rejected(self):
        packet={'page_count':1,'page_manifest':[]}
        card={'title':'Synthetic card','info':{},'one_line_summary':'summary','key_findings':'findings',
              'intro_summary':'motivation','conclusion_summary':'discussion','warnings':[],
              'figures':[],'equations':[],'tables':[]}
        self.assertEqual(parse_card(json.dumps(card),packet)['key_findings'],'findings')
        for value in (None,'','   ',[]):
            with self.subTest(value=value):
                invalid=deepcopy(card);invalid['key_findings']=value
                with self.assertRaisesRegex(ValueError,'缺少 key_findings'):parse_card(json.dumps(invalid),packet)
        card.pop('key_findings')
        with self.assertRaisesRegex(ValueError,'缺少 key_findings'):parse_card(json.dumps(card),packet)

    def test_new_input_requires_findings_in_same_response(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'original.pdf';doc=pymupdf.open();doc.new_page();doc.save(source);doc.close()
            with patch('codex_desktop_chat.bundles.prepare_upload_bundle',return_value={'synthetic':True,'size':1024}):
                packet=prepare(source,root/'input','synthetic','Synthetic paper',digest(source))
            prompt=(root/'input/prompt.txt').read_text()
            self.assertIn('核心结论key_findings必须与本次图式卡片在同一个回答中一起生成',prompt)
            self.assertIn('不使用初筛摘要替代',prompt)
            self.assertEqual(packet['work_summary_version'],WORK_SUMMARY_VERSION)
            self.assertIn('不同文章不套统一句式',prompt)
            self.assertNotIn('约30字，保留核心条件',json.loads((root/'input/source-context.json').read_text())['scientific_rules'])
            for name,fingerprint in packet['input_hashes'].items():self.assertEqual(digest(root/'input'/name),fingerprint)


if __name__=='__main__':unittest.main()
