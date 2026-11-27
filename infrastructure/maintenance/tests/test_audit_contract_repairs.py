import json
import unittest
from core.api import paths__WorkspacePath as Path
from review.tests import test_card_review_queue as fixtures
from review import card_review_queue as review
from cards.web_card_inputs import parse_card, EVALUATION_INSTRUCTIONS, damaged_latex
from cards.web_card_json import normalize


class AuditContractRepairs(unittest.TestCase):
    setUp=fixtures.ReviewQueue.setUp
    card=fixtures.ReviewQueue.card
    packet=fixtures.ReviewQueue.packet
    feedback=fixtures.ReviewQueue.feedback

    def test_prompt_contains_exact_checklist_and_correction_contract(self):
        job,_,card=self.card();prompt=review.prompt_for(job,card,1)
        self.assertIn(json.dumps([{'group':'figures','label':'Fig. 1','source_page':1}],ensure_ascii=False),prompt)
        for text in ('0–10','不是0–100','before必须逐字','不额外加入','无major/critical'):
            self.assertIn(text,prompt)
        self.assertNotIn('逐项复算',EVALUATION_INSTRUCTIONS)

    def test_token_merges_or_splits_are_not_formatting(self):
        for before,after in [('1 2','12'),('alpha beta','alphabeta'),('12','1 2')]:
            with self.assertRaises(ValueError):review.formatting_candidate({'figures':[{'summary':before}]},[{'path':'figures.0.summary','before':before,'after':after}])
        fixed=review.formatting_candidate({'figures':[{'summary':'A condition.'}]},[{'path':'figures.0.summary','before':'A condition.','after':'A\ncondition.'}])
        self.assertEqual(fixed['figures'][0]['summary'],'A\ncondition.')

    def test_latex_newline_escape_damage_is_not_silently_accepted(self):
        for latex in ('\nabla x','\nu','\frac{x}{y}','\beta','\rho','\times'):
            self.assertTrue(damaged_latex(latex))
        self.assertFalse(damaged_latex(r'\nabla x'))
        self.assertFalse(damaged_latex(r'\frac{x}{y}'+'\n+z'))

    def test_page_failure_does_not_hide_other_corruption(self):
        _,_,card=self.card();card['figures']=[]
        card['equations']=[{'label':'Eq','source_page':99,'evidence_id':'bad','latex':'\nabla x','quantities':'q'}]
        with self.assertRaises(ValueError) as context:parse_card(json.dumps(card),{'page_count':1,'page_manifest':[{'image':'one'}]})
        self.assertIn('证据页码不匹配',str(context.exception));self.assertIn('控制字符',str(context.exception))

    def test_control_characters_in_prose_are_rejected(self):
        _,_,card=self.card();card['figures']=[];card['intro_summary']='damaged\x08text'
        with self.assertRaisesRegex(ValueError,'文本含损坏控制字符'):parse_card(json.dumps(card),{'page_count':1,'page_manifest':[{'image':'one'}]})

    def test_normalizer_does_not_guess_valid_but_damaged_latex_escapes(self):
        raw=r'{"latex":"\nabla x"}'
        self.assertEqual(normalize(raw),raw)
        self.assertTrue(damaged_latex(json.loads(normalize(raw))['latex']))
        self.assertEqual(json.loads(normalize(r'{"latex":"\kappa"}'))['latex'],r'\kappa')

    def test_replacement_terminal_conflict_is_explicit_and_preserves_receipt(self):
        job,_,_=self.card();fingerprint='new-fingerprint'
        review.replacement(self.catalog,job,fingerprint,'needs_user',{'reason':'unknown receipt'})
        with self.assertRaisesRegex(ValueError,'已有终态'):review.replacement(self.catalog,job,fingerprint,'queued')
        row=next(r for r in review.rows(self.catalog) if r['card_sha256']==fingerprint)
        self.assertEqual(row['state'],'needs_user');self.assertEqual(json.loads(row['result']),{'reason':'unknown receipt'})
