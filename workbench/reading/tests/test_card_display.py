import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace as Obj
from reading.card_display import build, unique_region, number
from reading.reading_contract import file_digest

class DisplayTests(unittest.TestCase):
    def test_unique_figure_page_and_number_required(self):
        fig=Obj(number=1,crop_page=1,caption_page=1,crop_confidence='high',caption_confidence='high',graphics_found=True,sublabel=None,crop_bbox=[10,10,100,100],caption_bbox=[10,110,100,130])
        parsed=Obj(figures=[fig],equations=[])
        self.assertEqual(unique_region({'number':1,'source_page':2},'figures',parsed),(1,[10,10,100,100]))
        self.assertIsNone(unique_region({'number':1,'source_page':1},'figures',parsed))
        parsed.figures.append(fig)
        self.assertIsNone(unique_region({'number':1,'source_page':2},'figures',parsed))
    def test_uncertain_labels_and_graphics_rejected(self):
        self.assertIsNone(number({'label':'Fig. 1(a)'},'figures'))
        self.assertIsNone(number({'label':'Equations 1-3'},'equations'))
        self.assertEqual(number({'label':'公式 (2)'},'equations'),2)
    def test_pdf_crop_is_high_resolution_science_unchanged_and_cached(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);doc=pymupdf.open();page=doc.new_page(width=400,height=500)
            page.draw_rect(pymupdf.Rect(40,100,300,270),color=(0,0,0))
            page.insert_text((40,295),'Figure 1. Example measurement and full axis labels.',fontsize=10)
            page.insert_textbox(pymupdf.Rect(40,330,350,480),'Supporting source text '*20,fontsize=10)
            doc.save(root/'source.pdf');doc.close()
            card={'figures':[{'label':'Fig. 1','number':1,'source_page':1}],'equations':[]}
            (root/'card.json').write_text(json.dumps(card));before=file_digest(root/'card.json')
            result=build(root)
            self.assertEqual(file_digest(root/'card.json'),before)
            self.assertEqual(result['dpi'],300)
            self.assertTrue(result['items'])
            item=result['items']['figures:0'];self.assertGreater(item['width'],1000)
            crop=root/item['asset'];stamp=crop.stat().st_mtime_ns
            self.assertEqual(build(root)['items'],result['items']);self.assertEqual(crop.stat().st_mtime_ns,stamp)

if __name__=='__main__':unittest.main()
