"""Regression checks for missing-input refusal and conservative source validation."""
import json
import os
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
import pymupdf
from cards.web_card_inputs import MaterialDeliveryError, check_material_delivery, inspect_source, prepare, digest, parse_card


class InputAuditTests(unittest.TestCase):
    def test_missing_input_json_and_prose_are_blocked(self):
        for raw in ('本次对话未检测到 source.pdf 与 visual.pdf 附件。',
                    'Unable to proceed: attachment files are unavailable.'):
            with self.assertRaises(MaterialDeliveryError):parse_card(raw,{'page_count':1})
        card={'warnings':['本次对话未检测到用户所述的 source.pdf 附件。'],
              'figures':[],'equations':[],'tables':[]}
        with self.assertRaises(MaterialDeliveryError):check_material_delivery(json.dumps(card),card)

    def test_publisher_supplement_missing_is_not_a_required_attachment_failure(self):
        for warning in (
            '补充材料中的 Fig. S1–S5 和 Table S1 在本材料包中未提供。',
            '补充材料也不在本次附件中；主材料包 ZIP、source.pdf、visual.pdf 均可正常读取。',
            'Supplementary Fig. S1–S5 are not provided in this package.',
        ):
            with self.subTest(warning=warning):
                check_material_delivery('',{'warnings':[warning]})
        with self.assertRaises(MaterialDeliveryError):
            check_material_delivery('',{'warnings':['补充材料缺失，source.pdf 不可读。']})
    def test_no_figures_or_scientific_uncertainty_alone_is_not_delivery_failure(self):
        card={'warnings':['原文未提供确定机制，不能核验该推测。','附件中未提供温度条件，无法核实该参数。'],
              'figures':[],'equations':[],'tables':[],
              'one_line_summary':'无图短文的研究贡献。','key_findings':'原文没有说明该机制。'}
        check_material_delivery(json.dumps(card),card)
        check_material_delivery('The paper reports no figures or tables.',None)

    def test_negated_delivery_failures_do_not_block_real_answers(self):
        for warning in ('未发现附件缺失；ZIP内包含source.pdf和visual.pdf。',
                        'source.pdf和visual.pdf均可读取；未发现附件缺失。',
                        'source.pdf、visual.pdf和source-context.json均已读取；未发现不可读文件。',
                        'No missing attachments were detected.',
                        'No unreadable input files were found.'):
            with self.subTest(warning=warning):
                check_material_delivery('',{'warnings':[warning]})

    def test_negation_does_not_hide_a_separate_delivery_failure(self):
        for warning in ('未发现附件缺失，但visual.pdf无法读取。',
                        '未发现附件缺失；source.pdf不可读。',
                        'No missing attachments, but visual.pdf is unavailable.',
                        '附件已收到，visual.pdf无法读取。',
                        '未检测到source.pdf附件。'):
            with self.subTest(warning=warning),self.assertRaises(MaterialDeliveryError):
                check_material_delivery('',{'warnings':[warning]})

    def test_explicit_nonfailure_classification_preserves_source_coverage_notes(self):
        for prefix in ('不视为本次', '不应视为', '不构成', '并非', '不是'):
            warning='出版社补充材料未随包提供；此项为主文覆盖边界，'+prefix+'附件缺失。'
            with self.subTest(prefix=prefix):
                check_material_delivery('',{'warnings':[warning]})
                with self.assertRaises(MaterialDeliveryError):
                    check_material_delivery('',{'warnings':[warning+'但visual.pdf无法读取。']})

    def test_repository_cover_rejected_but_short_and_scanned_sources_are_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            for name,text,rejected in [('cover','Institutional Repository\nTitle and author metadata only.',True),
                                       ('paper','Abstract\nResearch observations in a brief communication.',False),
                                       ('scan','',False)]:
                path=Path(td)/(name+'.pdf')
                with pymupdf.open() as doc:
                    page=doc.new_page()
                    if text:page.insert_text((30,40),text)
                    doc.save(path)
                with pymupdf.open(path) as doc:
                    if rejected:
                        with self.assertRaisesRegex(ValueError,'机构库'):inspect_source(doc,path)
                    else:self.assertEqual(inspect_source(doc,path)[0]['page_count'],1)

    def test_pruned_frozen_zip_has_explicit_error_without_mutation(self):
        from cards.web_card_inputs import upgrade_evaluation_packet
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);packet={'paper_evaluation_version':'old','input_hashes':{},
                'upload_bundle':{'zip_path':td+'/pruned.zip','zip_sha256':'old'}}
            path=folder/'packet.json';path.write_text(json.dumps(packet));before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'冻结ZIP已被清理'):upgrade_evaluation_packet(folder)
            self.assertEqual(path.read_bytes(),before)

    def test_new_contract_cleanup_telemetry_and_frozen_input_protection(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':td+'/zips'}):
            root=Path(td);source=root/'original.pdf';folder=root/'inputs'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((30,40),'Abstract: source research under stated conditions.');doc.save(source)
            (folder/'pages').mkdir(parents=True);(folder/'pages/P999.png').write_bytes(b'stale')
            packet=prepare(source,folder,'synthetic-audit','Synthetic',digest(source))
            self.assertFalse((folder/'pages/P999.png').exists())
            self.assertEqual(packet['visual_dpi'],220);self.assertFalse(packet['input_budget']['truncated'])
            context=json.loads((folder/'source-context.json').read_text())
            self.assertIn('latex',context['item_templates']['equations'])
            prompt=(folder/'prompt.txt').read_text()
            for key in ('title','intro_summary','conclusion_summary','P001','至少15字符','关键词'):
                self.assertIn(key,prompt)
            self.assertNotIn('$candidates',prompt);self.assertNotIn('----- classify.md -----',prompt)
            hashes={name:digest(folder/name) for name in packet['input_hashes']}
            with self.assertRaisesRegex(ValueError,'冻结材料'):prepare(source,folder,'synthetic-audit','Synthetic',digest(source))
            self.assertEqual(hashes,{name:digest(folder/name) for name in packet['input_hashes']})
