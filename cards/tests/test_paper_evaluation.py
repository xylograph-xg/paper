import json
import tempfile
import unittest
from copy import deepcopy
from core.api import paths__WorkspacePath as Path
from cards.web_card_inputs import parse_card, EVALUATION_VERSION, prepare, digest, upgrade_evaluation_packet
from cards.paper_quality import RUBRIC, weighted_score, validate

class PaperEvaluation(unittest.TestCase):
 def setUp(self):
  self.packet={'page_count':2,'page_manifest':[],'paper_evaluation_version':EVALUATION_VERSION}
  self.card={'title':'test','info':{},'one_line_summary':'test','key_findings':'test','intro_summary':'test','conclusion_summary':'test','warnings':[],'figures':[],'equations':[],'tables':[], 'paper_evaluation':{k:{'score':78,'reason':'有对照但样本有限','source_pages':[1]} for k in ('overall_quality','direction_novelty')}}
  self.card['paper_evaluation']['overall_quality']['dimensions']={key:{'score':7.8,'reason':'Synthetic source strengths and limitations','source_pages':[1]} for key in RUBRIC}
 def test_scores_preserved_and_legacy_card_compatible(self):
  self.assertEqual(parse_card(json.dumps(self.card),self.packet)['paper_evaluation'],self.card['paper_evaluation'])
  legacy=deepcopy(self.card);legacy['paper_evaluation']['overall_quality'].pop('dimensions')
  self.assertEqual(parse_card(json.dumps(legacy),{**self.packet,'paper_evaluation_version':'paper-evaluation-v1'})['paper_evaluation']['overall_quality']['score'],78)
  self.card.pop('paper_evaluation');self.packet.pop('paper_evaluation_version')
  self.assertNotIn('paper_evaluation',parse_card(json.dumps(self.card),self.packet))
 def test_missing_rating_and_invalid_score_or_evidence_rejected(self):
  for change in [{'score':True},{'score':101},{'score':-1},{'score':float('nan')},{'score':'80'},{'source_pages':[]},{'source_pages':[3]},{'reason':''}]:
   with self.subTest(change=change):
    card=deepcopy(self.card);card['paper_evaluation']['overall_quality'].update(change)
    with self.assertRaises(ValueError):parse_card(json.dumps(card),self.packet)
  self.card.pop('paper_evaluation')
  with self.assertRaises(ValueError):parse_card(json.dumps(self.card),self.packet)
 def test_insufficient_evidence_not_fabricated_score(self):
  for item in self.card['paper_evaluation'].values():item.update(score=None,reason='信息不足：缺少比较',source_pages=[])
  for item in self.card['paper_evaluation']['overall_quality']['dimensions'].values():item.update(score=None,reason='信息不足',source_pages=[])
  self.assertIsNone(parse_card(json.dumps(self.card),self.packet)['paper_evaluation']['direction_novelty']['score'])
 def test_old_unsent_packet_upgraded_and_unknown_attempt_protected(self):
  import pymupdf
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source=root/'original.pdf';doc=pymupdf.open();doc.new_page();doc.save(source);doc.close()
   folder=root/'inputs';packet=prepare(source,folder,'test','test',digest(source))
   context=json.loads((folder/'source-context.json').read_text())
   context['schema']['paper_evaluation']['overall_quality'].pop('dimensions',None);context.pop('paper_quality_rubric')
   (folder/'source-context.json').write_text(json.dumps(context))
   prompt=(folder/'prompt.txt').read_text().split('\n另在paper_evaluation给本文两项文献评价',1)[0]+'\n另在paper_evaluation给本文两项文献评价，旧版整体评分。\n'
   (folder/'prompt.txt').write_text(prompt);packet['paper_evaluation_version']='paper-evaluation-v1'
   for name in ('source-context.json','prompt.txt'):packet['input_hashes'][name]=digest(folder/name)
   from codex_desktop_chat.bundles import prepare_upload_bundle
   packet['upload_bundle']=prepare_upload_bundle([str(folder/name) for name in packet['files']])
   old_zip=packet['upload_bundle']['zip_sha256'];old_context=(folder/'source-context.json').read_bytes()
   (folder/'packet.json').write_text(json.dumps(packet))
   original=digest(folder/'source.pdf')
   self.assertTrue(upgrade_evaluation_packet(folder));self.assertFalse(upgrade_evaluation_packet(folder))
   self.assertEqual(digest(folder/'source.pdf'),original)
   packet=json.loads((folder/'packet.json').read_text())
   self.assertEqual(packet['paper_evaluation_version'],EVALUATION_VERSION)
   self.assertNotEqual(packet['upload_bundle']['zip_sha256'],old_zip)
   self.assertEqual((folder/('before-'+EVALUATION_VERSION+'-source-context.json')).read_bytes(),old_context)
   self.assertEqual((folder/'prompt.txt').read_text().count('另在paper_evaluation给本文两项文献评价'),1)
   self.assertNotIn('dimensions',json.loads((folder/'source-context.json').read_text())['schema']['paper_evaluation']['overall_quality'])
   import zipfile
   with zipfile.ZipFile(packet['upload_bundle']['zip_path']) as bundle:
    context_names=[name for name in bundle.namelist() if name.endswith('source-context.json')]
    self.assertEqual(len(context_names),1);self.assertEqual(bundle.read(context_names[0]),(folder/'source-context.json').read_bytes())
   packet=json.loads((folder/'packet.json').read_text());packet.pop('paper_evaluation_version');(folder/'packet.json').write_text(json.dumps(packet))
   (folder/'chatgpt').mkdir();(folder/'chatgpt/attempt.json').write_text('{"state":"submitted"}')
   before=(folder/'packet.json').read_bytes()
   with self.assertRaises(ValueError):upgrade_evaluation_packet(folder)
   self.assertEqual((folder/'packet.json').read_bytes(),before)

 def test_weighted_quality_has_distinct_contribution_and_evidence_without_changing_inputs(self):
  quality=self.card['paper_evaluation']['overall_quality'];dimensions=quality['dimensions']
  for key,score in zip(RUBRIC,[5,8,8,9,8]):dimensions[key]['score']=score
  self.assertEqual(weighted_score(dimensions),72.5)
  quality['score']=72.5;before=deepcopy(self.card)
  self.assertEqual(parse_card(json.dumps(self.card),self.packet)['paper_evaluation']['overall_quality']['score'],72.5)
  self.assertEqual(self.card,before)
  dimensions['contribution']['score']=9;quality['score']=84.5
  self.assertEqual(validate(quality,2),84.5)
  quality['score']=85
  self.assertEqual(parse_card(json.dumps(self.card),self.packet)['paper_evaluation']['overall_quality']['score'],85)
  quality['score']=85.01
  self.assertEqual(parse_card(json.dumps(self.card),self.packet)['paper_evaluation']['overall_quality']['score'],85.01)

 def test_direct_overall_score_does_not_require_dimensions(self):
  quality=self.card['paper_evaluation']['overall_quality'];quality.pop('dimensions')
  self.assertEqual(parse_card(json.dumps(self.card),self.packet)['paper_evaluation']['overall_quality']['score'],78)
  for value in (True,101,float('nan'),'80'):
   quality['score']=value
   with self.assertRaises(ValueError):parse_card(json.dumps(self.card),self.packet)
