"""Synthetic PDF glyph tests; no sample titles, answers or model calls."""
import json
from core.api import paths__WorkspacePath as Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import pymupdf
from read.app.pdf_geometry import extract_bounded,prepare_geometry,prompt_evidence
from read.app.parser import Equation
from read.app import analyzer


class GeometryTests(unittest.TestCase):
    def setUp(self):
        from read import api as read_api
        policy=json.loads((Path(read_api.__file__).parent/'app/config.json').read_text())['pdf_geometry']
        runtime=patch('read.app.pdf_geometry.BUNDLED_PYTHON',Path(policy.get('python',__import__('sys').executable)))
        runtime.start();self.addCleanup(runtime.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'source.pdf'
        doc=pymupdf.open();page=doc.new_page(width=400,height=300)
        page.insert_text((40,120),'q =',fontsize=12)
        page.insert_text((95,112),'a',fontsize=12)
        page.draw_line((90,116),(109,116),width=.4)
        page.insert_text((95,131),'8',fontsize=12)
        page.insert_text((118,120),'w',fontsize=12)
        page.insert_text((126,114),'2',fontsize=8)
        page.insert_text((180,120),'(9)',fontsize=12)
        page.insert_text((240,120),'OUTSIDE = fake',fontsize=12)
        doc.save(self.path);doc.close()
        self.box=[35,92,210,145]

    def region(self,box=None):
        return {'id':'synthetic-region','page':0,'bbox':box or self.box,'page_size':[400,300]}

    def paper(self,text='8 w2 (9)'):
        eq=Equation('Eq. (9)',9,0,self.box,text,group_label='Eq. (9)',group_numbers=[9],
            group_bbox=self.box,members=[{'label':'Eq. (9)','number':9,'page':1,
            'source_note':'synthetic','confidence':'high','text':text}])
        return NS(pdf_path=str(self.path),page_sizes=[[400,300]],equations=[eq],
                  extraction_audit={},warnings=[]),eq

    def test_real_dependency_extracts_exact_crop(self):
        report=extract_bounded(self.path,[self.region()])
        self.assertEqual(report['runtime']['pdfplumber'],'0.11.9')
        row=report['regions'][0];self.assertIn('q',row['text']);self.assertNotIn('OUTSIDE',row['text'])
        self.assertFalse(row['source_verified'])

    def test_fraction_geometry(self):
        row=extract_bounded(self.path,[self.region()])['regions'][0]
        fraction=row['fraction_candidates'][0]
        self.assertEqual(fraction['above_text'],'a');self.assertEqual(fraction['below_text'],'8')

    def test_superscript_geometry(self):
        row=extract_bounded(self.path,[self.region()])['regions'][0]
        pairs=[(row['glyphs'][r['base_glyph']]['text'],row['glyphs'][r['script_glyph']]['text'],r['position']) for r in row['script_candidates']]
        self.assertIn(('w','2','superscript'),pairs)

    def test_missing_relation_repaired_from_original_only(self):
        paper,eq=self.paper();identity=eq.evidence_id
        prepare_geometry(paper,{'pdf_geometry':{'enabled':True}})
        self.assertIn('=',eq.text);self.assertIn('q',eq.text)
        self.assertEqual(eq.source_geometry['original_extraction'],'8 w2 (9)')
        self.assertEqual(eq.members[0]['text'],eq.text)
        self.assertEqual(eq.evidence_id,identity);self.assertEqual(eq.group_bbox,self.box)

    def test_complete_original_untouched(self):
        paper,eq=self.paper('q = a/8*w2 (9)');prepare_geometry(paper,{'pdf_geometry':{'enabled':True}})
        self.assertEqual(eq.text,'q = a/8*w2 (9)')
        self.assertFalse(eq.source_geometry['relation_recovered'])

    def test_wrong_printed_number_not_repaired(self):
        paper,eq=self.paper();eq.group_numbers=[10]
        prepare_geometry(paper,{'pdf_geometry':{'enabled':True}})
        self.assertEqual(eq.text,'8 w2 (9)')

    def test_disabled_does_not_spawn(self):
        paper,eq=self.paper()
        with patch('read.app.pdf_geometry.extract_bounded') as worker:
            self.assertIsNone(prepare_geometry(paper,{}));worker.assert_not_called()

    def test_no_equations_does_not_spawn(self):
        paper,eq=self.paper();paper.equations=[]
        with patch('read.app.pdf_geometry.extract_bounded') as worker:
            result=prepare_geometry(paper,{'pdf_geometry':{'enabled':True}})
            self.assertEqual(result['state'],'not_needed');worker.assert_not_called()

    def test_invalid_crop_visible(self):
        report=extract_bounded(self.path,[self.region([-20,0,210,145])])
        self.assertEqual(report['regions'][0]['state'],'unsupported')

    def test_coordinate_mismatch_visible(self):
        region=self.region();region['page_size']=[500,300]
        row=extract_bounded(self.path,[region])['regions'][0]
        self.assertEqual(row['state'],'unsupported')

    def test_no_text_layer(self):
        row=extract_bounded(self.path,[self.region([10,200,200,280])])['regions'][0]
        self.assertEqual(row['state'],'no_text_layer')

    def test_timeout_visible_and_original_preserved(self):
        paper,eq=self.paper();prepare_geometry(paper,{'pdf_geometry':{'enabled':True,'timeout_seconds':.00001}})
        self.assertEqual(eq.text,'8 w2 (9)');self.assertIn('不可用',paper.warnings[0])

    def test_missing_worker_visible(self):
        row=extract_bounded(self.path,[self.region()],{'python':'/nonexistent/python'})
        self.assertEqual(row['state'],'unavailable')

    def test_unknown_glyphs_not_repaired(self):
        paper,eq=self.paper()
        row={'id':eq.evidence_id,'state':'extracted','text':'q = a (9)','glyphs':[{'text':'=','x0':60,'x1':65},{'text':'q','x0':45,'x1':50}], 'unknown_glyphs':True}
        with patch('read.app.pdf_geometry.extract_bounded',return_value={'state':'extracted','regions':[row]}):
            prepare_geometry(paper,{'pdf_geometry':{'enabled':True}})
        self.assertEqual(eq.text,'8 w2 (9)')

    def test_new_evidence_reaches_original_card_api(self):
        paper,eq=self.paper();prepare_geometry(paper,{'pdf_geometry':{'enabled':True}})
        card=analyzer._equation_card(paper,eq)
        self.assertEqual(card.source_geometry,eq.source_geometry)
        prompt=prompt_evidence(card.source_geometry)
        self.assertIn('线上 a；线下 8',prompt);self.assertIn('截图优先',prompt)


if __name__=='__main__':unittest.main()
