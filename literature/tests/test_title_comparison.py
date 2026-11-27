"""Comparison-only title hits cannot supply affirmative direction evidence."""
from copy import deepcopy
import unittest

from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted


class TitleComparisonTests(unittest.TestCase):
    def test_direct_beyond_comparison_is_mentioned_not_affirmed(self):
        for word in ['Beyond','Beyond conventional','Beyond traditional','Beyond established','Beyond standard']:
            with self.subTest(word=word):
                d=document(title=word+' TADF: phosphorescence in crystals');r=classify(d)
                self.assertNotIn('topic.tadf',accepted(r,1))
                self.assertIn('topic.phosphorescence',accepted(r,1))
                e=next(x for x in r['mentions'] if x['id']=='topic.tadf')['evidence'][0]
                self.assertEqual(e['basis'],'title_comparison_only')
                self.assertEqual(e['relation'],'mentioned')
                self.assertEqual(e['title_comparison']['text'],word+' TADF')
                validate_evidence(d,r)

    def test_rule_uses_dimension_and_local_position_not_one_term(self):
        for title,excluded,retained in [
            ('Beyond conventional phosphorescence: TADF emitters','topic.phosphorescence','topic.tadf'),
            ('Beyond OLEDs: TADF emitters','topic.oled','topic.tadf'),
            ('Beyond traditional exciplex: phosphorescence','topic.exciplex','topic.phosphorescence')]:
            with self.subTest(title=title):
                r=classify(document(title=title))
                self.assertNotIn(excluded,accepted(r,1));self.assertIn(retained,accepted(r,1))

    def test_genuine_theme_is_retained_by_independent_abstract(self):
        d=document(title='Beyond conventional TADF: a new design',
                   abstract='Herein, we investigate TADF in a new series of emitters.')
        r=classify(d);self.assertIn('topic.tadf',accepted(r,1))
        label=next(x for x in r['level1'] if x['id']=='topic.tadf')
        self.assertTrue(all(e['scope']=='abstract' for e in label['evidence']))
        self.assertIn('topic.tadf',{x['id'] for x in r['mentions']})
        validate_evidence(d,r)

    def test_same_title_another_affirmative_hit_is_retained(self):
        d=document(title='Beyond conventional TADF: new TADF emitters')
        r=classify(d);label=next(x for x in r['level1'] if x['id']=='topic.tadf')
        self.assertEqual(len(label['evidence']),1)
        self.assertGreater(label['evidence'][0]['quote'].rfind('TADF'),0)
        self.assertEqual(len(next(x for x in r['mentions'] if x['id']=='topic.tadf')['evidence']),1)
        validate_evidence(d,r)

    def test_marker_cannot_reach_across_another_phrase_or_clause(self):
        for title in ['Beyond efficiency limits: TADF emitters',
                      'Beyond conventional devices, TADF emitters',
                      'TADF emitters beyond conventional efficiency limits',
                      'Beyond conventional crystallography and TADF emitters',
                      'Beyond conventional: TADF emitters',
                      'Conventional TADF emitters with improved efficiency']:
            with self.subTest(title=title):
                self.assertIn('topic.tadf',accepted(classify(document(title=title)),1))

    def test_complete_word_marker_and_non_topic_objects_are_unchanged(self):
        for title in ['Beyondness conventional TADF emitters','Abeyond TADF emitters',
                      'Beyond conventional TADFxyz: TADF emitters']:
            with self.subTest(title=title):
                self.assertIn('topic.tadf',accepted(classify(document(title=title)),1))
        self.assertIn('object.crystal',accepted(classify(document(title='Beyond conventional organic crystals')),1))

    def test_source_is_title_only_without_body_or_abstract_veto(self):
        d=document(title='TADF emitters',abstract='Beyond conventional TADF, we investigate phosphorescence.',
                   text='We investigate RISC beyond conventional TADF.')
        r=classify(d);self.assertIn('topic.tadf',accepted(r,1));self.assertIn('mechanism.risc',accepted(r,2))
        self.assertFalse(any('title_comparison' in e for l in r['mentions'] for e in l['evidence']))
        self.assertEqual(classify(document(title='Beyond conventional DFT calculations'))['level2'],[])
        validate_evidence(d,r)

    def test_unicode_long_alias_and_exact_trace(self):
        d=document(title='Beyond\u00a0conventional thermally activated delayed fluorescence: phosphorescence')
        r=classify(d);self.assertNotIn('topic.tadf',accepted(r,1))
        e=next(x for x in r['mentions'] if x['id']=='topic.tadf')['evidence'][0]
        trace=e['title_comparison']
        self.assertEqual(d['title'][trace['start']:trace['end']],trace['text'])
        self.assertEqual(d['title'][trace['hit_start']:trace['hit_end']],e['matched_text'])
        validate_evidence(d,r)

    def test_comparison_trace_tampering_rejected(self):
        d=document(title='Beyond conventional TADF: phosphorescence');r=classify(d)
        for key,value in [('text','invented'),('start',1),('end',2),('hit_start',0),('hit_end',1)]:
            changed=deepcopy(r)
            e=next(x for x in changed['mentions'] if x['id']=='topic.tadf')['evidence'][0]
            e['title_comparison'][key]=value
            with self.assertRaisesRegex(ValueError,'标题比较'):validate_evidence(d,changed)

    def test_parent_retrieval_inference_survives_an_affirmative_child(self):
        d=document(title='Beyond conventional TADF: MR-TADF emitters');r=classify(d)
        self.assertIn('topic.mr_tadf',{x['id'] for x in r['level1']})
        self.assertIn('topic.tadf',{x['id'] for x in r['inherited_labels']})
        validate_evidence(d,r)
