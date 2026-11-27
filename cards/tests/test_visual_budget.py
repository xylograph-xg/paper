import json
import os
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
import pymupdf
from cards import web_card_inputs as inputs


class VisualBudget(unittest.TestCase):
    def test_adaptive_budget_zip_and_frozen_packet(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'CODEX_CHAT_ZIP_DIR':td+'/zips'}):
            root=Path(td);source=root/'original.pdf';folder=root/'inputs'
            with pymupdf.open() as doc:
                for _ in range(3):doc.new_page().insert_text((30,40),'Abstract: evidence with equations and figures.')
                doc.save(source)
            render=inputs.render_visual
            def inflated(doc,path,pages,dpi):
                result=render(doc,path,pages,dpi)
                if dpi==220:
                    with path.open('ab') as stream:stream.write(b'x'*200_000)
                return result
            with patch.object(inputs,'MATERIAL_BUDGET_BYTES',150_000),patch.object(inputs,'render_visual',side_effect=inflated):
                packet=inputs.prepare(source,folder,'budget-test','Synthetic',inputs.digest(source))
            self.assertEqual(packet['visual_dpi'],180)
            self.assertLessEqual(packet['upload_bundle']['size'],inputs.REMOTE_ZIP_LIMIT_BYTES)
            self.assertEqual(packet['page_count'],3)
            context=json.loads((folder/'source-context.json').read_text())
            self.assertEqual(context['visual_dpi'],180)
            with pymupdf.open(folder/'visual.pdf') as doc:
                self.assertEqual(len(doc),3)
                self.assertEqual(doc.extract_image(doc[0].get_images()[0][0])['ext'],'jpeg')
            before=(folder/'packet.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'冻结材料'):
                inputs.prepare(source,folder,'budget-test','Synthetic',inputs.digest(source))
            self.assertEqual(before,(folder/'packet.json').read_bytes())

    def test_oversize_nonvisual_input_blocks_without_packet(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'original.pdf'
            with pymupdf.open() as doc:doc.new_page();doc.save(source)
            with patch.object(inputs,'MATERIAL_BUDGET_BYTES',1),patch.object(inputs,'VISUAL_DPI_STEPS',(72,)):
                with self.assertRaisesRegex(ValueError,'超过48MB'):
                    inputs.prepare(source,root/'inputs','blocked','Synthetic',inputs.digest(source))
            self.assertFalse((root/'inputs/packet.json').exists())
            self.assertTrue((root/'inputs/material-preparation-failure.json').exists())

    def test_soft_target_preserves_all_pages_source_and_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'CODEX_CHAT_ZIP_DIR':td+'/zips'}):
            root=Path(td);source=root/'source.pdf'
            with pymupdf.open() as doc:
                for _ in range(2):doc.new_page().insert_text((30,40),'Abstract: equations, conditions and full source.')
                doc.save(source)
            original=source.read_bytes();render=inputs.render_visual
            def inflated(doc,path,pages,dpi):
                manifest=render(doc,path,pages,dpi)
                if dpi>150:
                    with path.open('ab') as stream:stream.write(b'x'*200_000)
                return manifest
            with patch.object(inputs,'MATERIAL_TARGET_BYTES',100_000),patch.object(inputs,'render_visual',side_effect=inflated):
                packet=inputs.prepare(source,root/'new','soft-target','Synthetic',inputs.digest(source))
            self.assertEqual(packet['visual_dpi'],150);self.assertTrue(packet['material_target_met'])
            self.assertEqual(source.read_bytes(),original);self.assertEqual(packet['page_count'],2)
            self.assertEqual(len(packet['page_manifest']),2)
            with pymupdf.open(root/'new/source.pdf') as source_doc, pymupdf.open(root/'new/visual.pdf') as visual_doc:
                self.assertEqual(len(source_doc),len(visual_doc));self.assertEqual(len(visual_doc),2)
            before=(root/'new/packet.json').read_bytes()
            with self.assertRaises(ValueError):inputs.prepare(source,root/'new','soft-target','Synthetic',inputs.digest(source))
            self.assertEqual(before,(root/'new/packet.json').read_bytes())

    def test_soft_target_is_not_a_hard_rejection_or_a_reason_to_blur_all_pages(self):
        policy=inputs.visual_budget(40_000_000,150)
        self.assertTrue(policy['accepted']);self.assertFalse(policy['material_target_met'])
        self.assertFalse(inputs.visual_budget(40_000_000,180)['accepted'])
        self.assertFalse(inputs.visual_budget(61_000_000,72)['accepted'])
