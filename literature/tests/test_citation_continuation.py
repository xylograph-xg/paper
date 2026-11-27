"""Bounded cited-author passive continuation and explicit own-work resets."""
from copy import deepcopy
import unittest

from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted


CITED = 'Smith et al. synthesized a series of organic compounds.'
PASSIVE = 'Comprehensive characterization via X-ray crystallography was conducted.'


class CitationContinuationTests(unittest.TestCase):
    def test_cited_author_passive_method_is_mentioned_not_used(self):
        for first in [CITED, 'These compounds were reported by Smith and colleagues.']:
            with self.subTest(first=first):
                d=document(text=first+' '+PASSIVE, title='X-ray crystallography study')
                r=classify(d)
                self.assertNotIn('method.xray', accepted(r,2))
                e=next(x for x in r['mentions'] if x['id']=='method.xray')['evidence'][0]
                self.assertEqual(e['relation'],'mentioned')
                self.assertEqual(e['basis'],'cited_author_passive_continuation')
                self.assertEqual(e['citation_antecedent'],{'text':first,'start':0,'end':len(first)})
                self.assertEqual(e['focus_text'],PASSIVE)
                validate_evidence(d,r)

    def test_cited_author_passive_abstract_cannot_supply_topic(self):
        text=CITED+' Aggregation-induced emission was investigated in these compounds.'
        d=document(abstract=text);r=classify(d)
        self.assertNotIn('topic.aie',accepted(r,1))
        self.assertIn('topic.aie',{x['id'] for x in r['mentions']})
        validate_evidence(d,r)

    def test_own_work_and_uncited_passives_remain_eligible(self):
        for first in ['', 'We synthesized a series of organic compounds. ',
                      'The compounds are described in this study. ']:
            with self.subTest(first=first):
                d=document(text=first+PASSIVE,title='X-ray crystallography study');r=classify(d)
                self.assertIn('method.xray',accepted(r,2));validate_evidence(d,r)

    def test_explicit_current_subject_resets_citation_ownership(self):
        for sentence in ['We conducted X-ray crystallography on the new material.',
                         'Our X-ray crystallography measurements were conducted at room temperature.',
                         'In this study, X-ray crystallography was performed.',
                         'Herein, X-ray crystallography was performed.']:
            with self.subTest(sentence=sentence):
                d=document(text=CITED+' '+sentence,title='X-ray crystallography study');r=classify(d)
                self.assertIn('method.xray',accepted(r,2));validate_evidence(d,r)
        r=classify(document(abstract=CITED+' In this study, aggregation-induced emission was investigated.'))
        self.assertIn('topic.aie',accepted(r,1))

    def test_review_scope_in_title_is_preserved(self):
        r=classify(document(title='Review of aggregation-induced emission',
            abstract=CITED+' Aggregation-induced emission was investigated.'))
        self.assertIn('topic.aie',{x['id'] for x in r['level1']})
        self.assertEqual(next(x for x in r['level1'] if x['id']=='topic.aie')['evidence'][0]['scope'],'title')

    def test_no_paragraph_or_nonadjacent_inheritance(self):
        for middle in ['\n\n', ' The next section concerns a new experimental study. ']:
            with self.subTest(middle=middle):
                r=classify(document(text=CITED+middle+PASSIVE,title='X-ray crystallography study'))
                self.assertIn('method.xray',accepted(r,2))

    def test_no_chunk_or_source_crossing(self):
        d=document(text=PASSIVE,abstract=CITED,title='X-ray crystallography study')
        self.assertIn('method.xray',accepted(classify(d),2))
        d=document(text=PASSIVE,title='X-ray crystallography study')
        d['chunks'].insert(0,{'id':'prior','scope':'fulltext','page':1,'section':'results','text':CITED})
        self.assertIn('method.xray',accepted(classify(d),2))
        d=document(abstract='Aggregation-induced emission was investigated.',text=CITED)
        self.assertIn('topic.aie',accepted(classify(d),1))

    def test_prior_procedure_exception_does_not_erase_cited_owner(self):
        d=document(text=CITED+' X-ray crystallography was performed as previously described.',
                   title='X-ray crystallography study')
        self.assertNotIn('method.xray',accepted(classify(d),2))

    def test_exact_unicode_trace_and_tampering(self):
        first='Müller et al. synthesized novel compounds.'
        d=document(text=first+'\nComprehensive X-ray crystallography was\nconducted.',
                   title='X-ray crystallography study');r=classify(d)
        self.assertNotIn('method.xray',accepted(r,2));validate_evidence(d,r)
        for key,value in [('text','invented'),('start',1),('end',2)]:
            changed=deepcopy(r)
            next(x for x in changed['mentions'] if x['id']=='method.xray')['evidence'][0]['citation_antecedent'][key]=value
            with self.assertRaisesRegex(ValueError,'引用归属'):validate_evidence(d,changed)
