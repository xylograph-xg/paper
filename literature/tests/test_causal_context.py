"""Current causal-result ownership without paragraph-wide keyword inheritance."""
from copy import deepcopy
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted

ANCHOR='Herein, we investigate carrier trapping in junctions.'
BRIDGE='Carrier trapping blocks transport.'
RESULT='More importantly, trapped carriers induce triplet accumulation in a hyperfluorescent system.'


class CausalContextTests(unittest.TestCase):
    def test_compound_denial_and_failure_break_each_chain_position(self):
        for verb in ['cannot induce',"can't induce",'can’t induce','fail to induce','failed to induce','are unable to induce']:
            text=ANCHOR+' '+BRIDGE+' '+RESULT.replace('induce',verb)
            with self.subTest(text=text):
                self.assertNotIn('topic.hyperfluorescence',accepted(classify(document(abstract=text)),1))
        for bridge in ['Carrier trapping cannot block transport.', 'Carrier trapping lacks experimental support.']:
            self.assertNotIn('topic.hyperfluorescence',accepted(classify(document(abstract=ANCHOR+' '+bridge+' '+RESULT)),1))

    def test_current_result_with_two_exact_previous_sentences(self):
        text=' '.join([ANCHOR,BRIDGE,RESULT]);d=document(abstract=text);r=classify(d)
        label=next(x for x in r['level1'] if x['id']=='topic.hyperfluorescence')
        evidence=label['evidence'][0]
        self.assertEqual(evidence['basis'],'abstract_linked_causal_result')
        self.assertEqual([x['text'] for x in evidence['causal_chain']['sentences']],[ANCHOR,BRIDGE])
        self.assertEqual(evidence['focus_text'],RESULT)
        validate_evidence(d,r)

    def test_single_adjacent_anchor_can_own_causal_topic(self):
        d=document(abstract=ANCHOR+' Consequently, trapped carriers cause phosphorescence.')
        r=classify(d)
        self.assertIn('topic.phosphorescence',accepted(r,1))
        validate_evidence(d,r)

    def test_history_hypothesis_and_comparison_break_every_position(self):
        for text in [ANCHOR.replace('Herein','Previously')+' '+BRIDGE+' '+RESULT,
                     ANCHOR+' Previously carrier trapping blocked transport. '+RESULT,
                     ANCHOR+' '+BRIDGE+' '+RESULT.replace('induce','might induce'),
                     ANCHOR+' '+BRIDGE+' '+RESULT.replace('induce','do not induce'),
                     ANCHOR+' '+BRIDGE+' '+RESULT.replace('in a hyperfluorescent','whereas other compounds emit in a hyperfluorescent'),
                     ANCHOR+' '+BRIDGE+' '+RESULT.replace('More importantly','Previously')]:
            with self.subTest(text=text):
                self.assertNotIn('topic.hyperfluorescence',accepted(classify(document(abstract=text)),1))

    def test_missing_anchor_unrelated_bridge_long_gap_or_paragraph_break(self):
        for text in [BRIDGE+' '+RESULT,
                     'Herein, we investigate crystalline packing. '+BRIDGE+' '+RESULT,
                     ANCHOR+' Carrier trapping blocks transport. Transport changes carrier mobility. '+RESULT,
                     ANCHOR+'\n\n'+BRIDGE+' '+RESULT,
                     ANCHOR+' '+BRIDGE+' Trapped carriers induce triplet accumulation in a hyperfluorescent system.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.hyperfluorescence',accepted(classify(document(abstract=text)),1))

    def test_abstract_chain_never_supplies_body_or_fine_evidence(self):
        text=ANCHOR+' '+BRIDGE+' '+RESULT
        self.assertNotIn('topic.hyperfluorescence',accepted(classify(document(text=text)),1))
        self.assertEqual(classify(document(abstract=text))['level2'],[])

    def test_causal_trace_tampering_rejected(self):
        d=document(abstract=ANCHOR+' '+BRIDGE+' '+RESULT);r=classify(d)
        for key in ['sentence','link','hit']:
            changed=deepcopy(r)
            trace=next(x for x in changed['level1'] if x['id']=='topic.hyperfluorescence')['evidence'][0]['causal_chain']
            if key=='sentence':trace['sentences'][0]['start']=1
            elif key=='link':trace['shared_terms'][0]=['invented']
            else:trace['hit_start']=0
            with self.assertRaisesRegex(ValueError,'结果链'):validate_evidence(d,changed)
