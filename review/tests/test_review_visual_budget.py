import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

import pymupdf
from review import card_review_queue as review
from cards import web_card_inputs as inputs
from core.services import atomic_json


class ReviewVisualBudget(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        with pymupdf.open() as pdf:
            for i in range(3):pdf.new_page().insert_text((40,60),'Full source page '+str(i+1))
            pdf.save(self.root/'source.pdf')
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40,60),'Actual complete card image');pdf.save(self.root/'card-images.pdf')
        (self.root/'supplement.pdf').write_bytes((self.root/'source.pdf').read_bytes())
        atomic_json(self.root/'supplement-context.json',{'source_text':[{'source_page':1,'text':'original supplement text'}]})
        atomic_json(self.root/'source-context.json',{'source_text':[{'source_page':1,'text':'original text'}],
                    'page_manifest':[{'source_page':1,'sha256':'original-png'}],'visual_dpi':220,'visual_encoding':'png'})
        for name in ('card-review.json','review-input-manifest.json'):atomic_json(self.root/name,{'scientific_value':'unchanged'})
        self.request=self.root/'request.json'
        atomic_json(self.request,{'output_folder':str(self.root),'packet':{'input_hashes':{'source.pdf':inputs.digest(self.root/'source.pdf')}}})

    def test_complete_budget_adapts_main_and_supplement_and_preserves_inputs(self):
        originals={name:inputs.digest(self.root/name) for name in ('source.pdf','supplement.pdf','card-images.pdf','card-review.json','review-input-manifest.json')}
        render=review.render_review_visual
        def inflated(source,path,dpi,**kw):
            result=render(source,path,dpi,**kw)
            if dpi==220:
                with Path(path).open('ab') as stream:stream.write(b'x'*400_000)
            return result
        with patch.object(inputs,'MATERIAL_BUDGET_BYTES',400_000),patch.object(review,'render_review_visual',side_effect=inflated):
            review.fit_review_visual_budget(self.request)
        policy=json.loads((self.root/'review-visual-policy.json').read_text())
        self.assertEqual(policy['visual_dpi'],180);self.assertLessEqual(policy['material_bytes'],400_000)
        self.assertEqual(policy['material_bytes'],sum((self.root/n).stat().st_size for n in policy['file_bytes']))
        for name,sha in originals.items():self.assertEqual(inputs.digest(self.root/name),sha)
        context=json.loads((self.root/'source-context.json').read_text())
        self.assertEqual(context['source_text'][0]['text'],'original text')
        self.assertEqual(context['original_page_manifest'][0]['sha256'],'original-png')
        self.assertEqual(len(context['page_manifest']),3)
        self.assertEqual(json.loads((self.root/'supplement-context.json').read_text())['visual_dpi'],180)
        for name in ('visual.pdf','supplement-visual.pdf'):
            with pymupdf.open(self.root/name) as pdf:
                self.assertEqual(len(pdf),3)
                self.assertEqual(pdf.extract_image(pdf[0].get_images()[0][0])['ext'],'jpeg')

    def test_exhausted_budget_preserves_all_pages_and_never_creates_packet(self):
        with patch.object(inputs,'MATERIAL_BUDGET_BYTES',1):
            with self.assertRaisesRegex(ValueError,'超过60MB'):review.fit_review_visual_budget(self.request)
        failure=json.loads((self.root/'material-preparation-failure.json').read_text())
        self.assertEqual(failure['visual_dpi'],72);self.assertFalse(failure['automatic_resubmit'])
        self.assertIn('card-images.pdf',failure['file_bytes']);self.assertIn('supplement.pdf',failure['file_bytes'])
        self.assertFalse((self.root/'packet.json').exists())
        with pymupdf.open(self.root/'visual.pdf') as pdf:self.assertEqual(len(pdf),3)

    def test_frozen_or_attempted_inputs_cannot_be_changed(self):
        before=inputs.digest(self.root/'source-context.json')
        for name in ('packet.json','attempt.json'):
            atomic_json(self.root/name,{'state':'unknown'})
            with self.assertRaisesRegex(ValueError,'冻结或在途'):review.fit_review_visual_budget(self.request)
            self.assertEqual(inputs.digest(self.root/'source-context.json'),before)
            (self.root/name).unlink()


if __name__=='__main__':unittest.main()
