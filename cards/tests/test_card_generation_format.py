"""Generation format is frozen source-only guidance, never a scientific rewrite."""
import json
import os
import tempfile
import unittest
import zipfile
from copy import deepcopy
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog, ROOT
from cards.web_card_inputs import CARD_FORMAT_VERSION, card_format_instructions, digest, parse_card, prepare


class CardGenerationFormat(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        bundle_environment=patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')})
        bundle_environment.start();self.addCleanup(bundle_environment.stop)

    def source(self):
        import pymupdf
        path=self.root/'original.pdf';doc=pymupdf.open();page=doc.new_page()
        page.insert_text((72,72),'Synthetic source evidence with stated conditions.')
        doc.save(path);doc.close();return path

    def test_new_prompt_context_and_single_zip_share_the_authoritative_rules(self):
        source=self.source();original=digest(source);folder=self.root/'inputs'
        with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')}):
            packet=prepare(source,folder,'synthetic-format','Synthetic formatting fixture',original)
        context=json.loads((folder/'source-context.json').read_text())
        prompt=(folder/'prompt.txt').read_text()
        instructions=card_format_instructions((ROOT/'config/web_card_rules.md').read_text())
        self.assertIn(instructions,prompt)
        self.assertEqual(packet['card_format_version'],CARD_FORMAT_VERSION)
        self.assertEqual(context['card_format_version'],CARD_FORMAT_VERSION)
        for field in ('intro_summary','conclusion_summary','key_findings','summary','detail','result',
                      'figure_info','quantities','columns','conditions','reason'):
            self.assertIn(field,instructions)
        self.assertIn(r'\n\n',instructions)
        self.assertNotIn('六个===标题===必须',context['scientific_rules'])
        self.assertNotIn('输出到关键词这一行立即结束',context['scientific_rules'])
        self.assertEqual(context['schema']['figures'],[])
        self.assertEqual(context['schema']['intro_summary'],'')
        with zipfile.ZipFile(packet['upload_bundle']['zip_path']) as bundle:
            self.assertEqual(bundle.read('source-context.json'),(folder/'source-context.json').read_bytes())
            self.assertEqual(bundle.read('source.pdf'),(folder/'source.pdf').read_bytes())
        for name,fingerprint in packet['input_hashes'].items():
            self.assertEqual(digest(folder/name),fingerprint)
        self.assertEqual(digest(source),original)

    def test_json_paragraphs_symbols_and_verbatim_evidence_survive_parsing(self):
        shared={'source_page':1,'evidence_id':'P001','one_line':'限定条件下的结果。',
                'summary':'用途与条件。\n\n独立比较对象。',
                'detail':'直接观察。\n\n作者解释仍为推测。',
                'result':'组一的结论与边界。\n\n组二的结论与边界。',
                'evidence_quote':'The literal source sentence; punctuation and S1 stay unchanged.'}
        card={'title':'Unmodified title','info':{'作者':'Original Names'},'warnings':[],
              'one_line_summary':'一小段连贯工作总结，保留必要条件。',
              'key_findings':'1. 条件一的发现。\n\n2. 条件二的发现。\n\n3. 尚未确定的机制。',
              'intro_summary':'研究目的。\n\n已有工作。\n\n缺口。\n\n本文问题。',
              'conclusion_summary':'结果解释。\n\n意义。\n\n机制。\n\n限制。',
              'figures':[{**shared,'label':'Figure 1','caption':'Verbatim caption: (i), (ii); S1, CT.',
                          'figure_info':'全图概述。\n\n(i)：对象一、坐标与条件。\n\n(ii)：对象二、坐标与条件。'}],
              'equations':[{**shared,'label':'Equation 1','latex':r'\begin{aligned}k_{i,j}&=\frac{1}{\tau_i}\\S_1&\to CT\end{aligned}',
                            'quantities':'k_{i,j}：速率，s⁻¹，给定索引。\nτ_i：寿命，s。','related_labels':[]}],
              'tables':[{**shared,'label':'Table 1','caption':'Original table caption.',
                         'columns':'对象：组别。\n数值：原文单位。',
                         'conditions':'组一：原文温度与环境。\n\n组二：独立比较条件。'}]}
        packet={'card_format_version':CARD_FORMAT_VERSION,'page_count':1,'page_manifest':[{'image':'source.png'}]}
        decoded=parse_card(json.dumps(card,ensure_ascii=False),packet)
        expected=deepcopy(card)
        for group in ('figures','equations','tables'):expected[group][0]['image_path']='source.png'
        self.assertEqual(decoded,expected)

    def test_existing_frozen_packet_is_reused_without_repreparing_or_upgrading(self):
        from browser.web_page_queue import prepare as prepare_queued
        source=self.source();catalog=Catalog(self.root/'catalog.sqlite3')
        pid=catalog.upsert({'title':'Legacy frozen fixture'})
        catalog.update(pid,acquisition='available',asset_path=str(source),asset_hash=digest(source))
        folder=self.root/'web_cards'/pid;folder.mkdir(parents=True)
        (folder/'prompt.txt').write_text('Immutable earlier instructions.')
        packet={'source_original_sha256':digest(source),'input_hashes':{'prompt.txt':digest(folder/'prompt.txt')}}
        (folder/'packet.json').write_text(json.dumps(packet))
        before={p.name:p.read_bytes() for p in folder.iterdir()}
        config={'catalog_path':str(catalog.path),'studio_library_root':str(self.root/'library'),'web_cards':{}}
        job={'paper_id':pid,'source_sha256':digest(source),'selection':'{}'}
        with patch('browser.web_page_queue.subprocess.run') as subprocess:
            self.assertEqual(prepare_queued(config,job),packet);subprocess.assert_not_called()
        self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},before)

    def test_missing_or_mismatched_rules_block_preparation_before_bundle_creation(self):
        source=self.source();rules=self.root/'rules';(rules/'config').mkdir(parents=True)
        for text in ('No format section.', '----- card_format.md -----\n整卡文字格式版本：unknown',
                     '----- card_format.md -----\n整卡文字格式版本：'+CARD_FORMAT_VERSION+'0。'):
            with self.subTest(rules=text):
                (rules/'config/web_card_rules.md').write_text(text)
                with patch('cards.web_card_inputs.ROOT',rules),patch('codex_desktop_chat.bundles.prepare_upload_bundle') as bundle:
                    with self.assertRaisesRegex(ValueError,'整卡通用文字格式'):
                        prepare(source,self.root/'blocked','synthetic','Synthetic',digest(source))
                    bundle.assert_not_called()
                self.assertFalse((self.root/'blocked/prompt.txt').exists())


if __name__=='__main__':unittest.main()
