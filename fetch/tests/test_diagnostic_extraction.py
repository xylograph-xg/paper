"""Geometry regressions for split caption text and detached inline math factors."""
import tempfile,unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
import pymupdf
from read.app import parser
from read.app.evidence_preparation import complete_column_captions,expand_unnumbered_relation_lines

class ExtractionGeometry(unittest.TestCase):
 def test_owner_preparation_filters_table_headers_before_math_expansion(self):
  from unittest.mock import patch
  table=parser.Equation('unnumbered',None,0,[0,0,100,20],'Table 9 | Synthetic response rate (s=seconds)')
  table.members=[{'number':None,'page':1,'text':table.text,'bbox':table.bbox}]
  header=parser.Equation('header',None,0,[0,30,100,45],'Signal (nm) Rate (s-1) Yield (%)')
  header.members=[{'number':None,'page':1,'text':header.text,'bbox':header.bbox}]
  relation=parser.Equation('relation',None,0,[0,60,100,75],'C = A B')
  relation.members=[{'number':None,'page':1,'text':relation.text,'bbox':relation.bbox}]
  numbered=parser.Equation('Eq. (7)',7,0,[0,90,100,110],'opaque PDF glyphs')
  numbered.members=[{'number':7,'page':1,'text':numbered.text,'bbox':numbered.bbox}]
  parsed=SimpleNamespace(equations=[table,header,relation,numbered],figures=[],extraction_audit={},warnings=[])
  names=['repair_sections','recover_split_figures','recover_caption_text','complete_column_captions','recover_numbered_equations','expand_unnumbered_relation_lines','include_adjacent_definitions']
  from contextlib import ExitStack
  with ExitStack() as stack:
   for name in names:stack.enter_context(patch('read.app.evidence_preparation.'+name))
   stack.enter_context(patch.object(parser,'_collect_candidates'))
   stack.enter_context(patch.object(parser,'_attach_equation_context'))
   parser.prepare_evidence(parsed,{})
  self.assertEqual([e.label for e in parsed.equations],['relation','Eq. (7)'])
  self.assertEqual(len(parsed.extraction_audit['rejected_equation_candidates']),2)
  self.assertTrue(parsed.extraction_audit['rejected_equation_candidates'][0]['requires_table_review'])

 def test_caption_math_block_continues_before_larger_body_text(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'caption.pdf';doc=pymupdf.open();page=doc.new_page(width=600,height=800)
   page.insert_text((40,100),'FIG. 12. Synthetic measured response for several values',fontsize=8)
   page.insert_text((40,111),'q = 2 in panel (b), including uncertainty.',fontsize=8)
   page.insert_text((40,128),'Body interpretation must remain outside the caption.',fontsize=10)
   doc.save(path);doc.close()
   with pymupdf.open(path) as source:
    lines=[line for b in source[0].get_text('dict')['blocks'] if b.get('type')==0 for line in b['lines']]
   first=lines[0];figure=parser.Figure(12,'Fig. 12',None,parser._line_text(first),0,list(first['bbox']))
   # Original crop width includes the column, not just the printed first line.
   figure.caption_bbox[2]=290
   parsed=SimpleNamespace(pdf_path=str(path),figures=[figure],paragraphs=[],extraction_audit={})
   complete_column_captions(parsed)
   self.assertIn('including uncertainty',figure.caption)
   self.assertNotIn('Body interpretation',figure.caption)
   self.assertGreater(figure.caption_bbox[3],first['bbox'][3])

 def test_detached_right_factor_and_left_superscript_are_in_crop(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'inline.pdf';doc=pymupdf.open();page=doc.new_page(width=600,height=800)
   page.insert_text((300,100),'P',fontsize=10)
   page.insert_text((310,100),'= Q',fontsize=10)
   page.insert_text((350,100),'R, under independence assumptions.',fontsize=10)
   page.insert_text((40,100),'Unrelated left-column text',fontsize=10)
   doc.save(path);doc.close()
   box=[310,89,330,104];eq=parser.Equation('Eq. (p.1 unnumbered)',None,0,box,'= Q')
   eq.members=[{'number':None,'page':1,'bbox':box,'text':'= Q'}];eq.group_bbox=box[:]
   parsed=SimpleNamespace(pdf_path=str(path),equations=[eq],extraction_audit={})
   expand_unnumbered_relation_lines(parsed,parser)
   self.assertLess(eq.group_bbox[0],310);self.assertGreater(eq.group_bbox[2],350)
   self.assertIn('R, under independence assumptions',eq.text)
   self.assertNotIn('left-column',eq.text)
   self.assertEqual(eq.members[0]['bbox'],eq.group_bbox)

 def test_one_column_relation_can_cross_page_midpoint(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'single-column.pdf';doc=pymupdf.open();page=doc.new_page(width=600,height=800)
   page.insert_text((40,100),'C = A',fontsize=10)
   page.insert_text((300,100),'B',fontsize=10)
   doc.save(path);doc.close()
   box=[40,89,69,104];eq=parser.Equation('Eq. (p.1 unnumbered)',None,0,box,'C = A')
   eq.members=[{'number':None,'page':1,'bbox':box,'text':'C = A'}];eq.group_bbox=box[:]
   parsed=SimpleNamespace(pdf_path=str(path),equations=[eq],extraction_audit={})
   expand_unnumbered_relation_lines(parsed,parser)
   self.assertGreater(eq.group_bbox[2],300)

 def test_flattened_symbol_and_abbreviation_retrieve_original_definitions(self):
  from read.app.evidence_preparation import source_definitions
  paragraphs=[parser.Paragraph(0,0,[0,0,100,10],'The extended motion approximation (XM) is defined here.'),parser.Paragraph(1,2,[0,0,100,10],'Dij and Wkl denote signal diffusion and carrier hopping rate, respectively.'),parser.Paragraph(2,3,[0,0,100,10],'Dij is locally defined as another effective rate.')]
  parsed=SimpleNamespace(paragraphs=paragraphs)
  text=source_definitions(parsed,'Dkm + Wlm, XM')
  self.assertIn('extended motion approximation',text)
  self.assertIn('signal diffusion and carrier hopping',text)
  self.assertIn('locally defined as another',text)
  self.assertIn('PDF p.3',text)
  self.assertNotIn('triplet',text)

 def test_two_column_neighboring_math_is_excluded(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'columns.pdf';doc=pymupdf.open();page=doc.new_page(width=600,height=800)
   page.insert_text((40,60),'Several original words establish the left column.',fontsize=9)
   page.insert_text((310,60),'Several original words establish the right column.',fontsize=9)
   page.insert_text((40,100),'L = M + N',fontsize=10)
   page.insert_text((310,100),'P = Q',fontsize=10)
   page.insert_text((355,100),'R',fontsize=10)
   doc.save(path);doc.close()
   box=[310,89,337,104];eq=parser.Equation('Eq. (p.1 unnumbered)',None,0,box,'P = Q')
   eq.members=[{'number':None,'page':1,'bbox':box,'text':'P = Q'}];eq.group_bbox=box[:]
   parsed=SimpleNamespace(pdf_path=str(path),equations=[eq],extraction_audit={})
   expand_unnumbered_relation_lines(parsed,parser)
   self.assertGreater(eq.group_bbox[0],300);self.assertGreater(eq.group_bbox[2],355)
   self.assertNotIn('L = M',eq.text)
