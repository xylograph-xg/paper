"""Bibliography structure overrides mistaken body-section metadata locally."""
from copy import deepcopy
import unittest

from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted


ENTRY = ('Adv. Mater. 2020, 32, 123456.\n'
         '(17) Müller, A.; Jones, B.; Chen, C. Design of Narrowband Emitters '
         'Investigated Using X-ray Crystallography.')


class BibliographyOwnershipTests(unittest.TestCase):
    def test_numbered_author_entry_is_not_own_research_in_wrong_sections(self):
        for section in ['methods', 'results', 'discussion', 'unknown']:
            with self.subTest(section=section):
                d=document(text=ENTRY, title='Narrowband X-ray crystallography study')
                d['chunks'][0]['section']=section
                r=classify(d)
                self.assertNotIn('question.narrowband', accepted(r,2))
                self.assertNotIn('method.xray', accepted(r,2))
                e=next(x for x in r['mentions'] if x['id']=='method.xray')['evidence'][0]
                self.assertEqual(e['basis'], 'bibliography_entry_only')
                self.assertEqual(e['bibliography_entry']['text'], ENTRY[ENTRY.index('(17)'):])
                validate_evidence(d,r)

    def test_bracket_and_period_numbering(self):
        for marker in ['[3]', '3.', '(301)']:
            with self.subTest(marker=marker):
                r=classify(document(text=ENTRY.replace('(17)',marker)))
                self.assertNotIn('method.xray', accepted(r,2))

    def test_real_methods_with_inline_citations_and_numbered_operations(self):
        for text in ['We performed X-ray crystallography following Smith and Jones [17].',
                     '(1) X-ray crystallography was performed on our crystals.',
                     '(17) Smith and Jones reported prior work; we performed X-ray crystallography.',
                     'Journal of Materials 2020, 32, 123456.\nWe performed X-ray crystallography.',
                     'We used X-ray crystallography (Smith, A.; Jones, B., 2020).',
                     'We performed X-ray crystallography.\n(17) Smith, A.; Jones, B. A different technique.']:
            with self.subTest(text=text):
                d=document(text=text,title='X-ray crystallography study');r=classify(d)
                self.assertIn('method.xray',accepted(r,2));validate_evidence(d,r)

    def test_separate_current_paragraph_in_same_chunk_remains_eligible(self):
        d=document(text=ENTRY+'\n\nWe performed X-ray crystallography on our samples.',
                   title='X-ray crystallography study')
        r=classify(d);self.assertIn('method.xray',accepted(r,2))
        self.assertIn('bibliography_entry_only', {e['basis'] for x in r['mentions'] for e in x['evidence']})
        validate_evidence(d,r)

    def test_no_cross_chunk_or_metadata_veto(self):
        d=document(text=ENTRY, title='Narrowband emission')
        d['chunks'].append({'id':'own', 'scope':'fulltext', 'page':2, 'section':'methods',
                            'text':'We performed X-ray crystallography.'})
        r=classify(d)
        self.assertIn('method.xray',accepted(r,2));validate_evidence(d,r)

    def test_trace_tampering_is_rejected(self):
        d=document(text=ENTRY);r=classify(d)
        original=next(x for x in r['mentions'] if x['id']=='method.xray')['evidence'][0]
        self.assertIn('bibliography_entry',original)
        for key,value in [('text','invented'),('start',0),('end',1),('author_count',1)]:
            with self.subTest(key=key):
                changed=deepcopy(r)
                next(x for x in changed['mentions'] if x['id']=='method.xray')['evidence'][0]['bibliography_entry'][key]=value
                with self.assertRaisesRegex(ValueError,'书目'):validate_evidence(d,changed)

    def test_bibliography_cannot_supply_degradation_workflow(self):
        d=document(text='(6) Smith, A.; Jones, B. Degradation products were determined using HPLC.\n\n'
                        'We performed LC-MS on these samples.',title='Degradation product analysis')
        r=classify(d)
        self.assertNotIn('method.degradation_product_analysis',accepted(r,2))
        validate_evidence(d,r)
