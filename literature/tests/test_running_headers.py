"""Repeated physical-page headers cannot substitute for scientific body evidence."""
from copy import deepcopy
import unittest
from literature.classifier import classify, validate_evidence
from literature.tests.test_context import document, accepted

HEADER='Design of bipolar host materials for phosphorescent devices'
BIPOLAR='question.bipolar_charge_transport'


def pages(header=HEADER, starts=(0,0), numbers=(2,3)):
    d=document()
    d['chunks']=[{'id':f'block-{i}','scope':'fulltext','page':page,'page_start':start,
                 'section':'results','role':'body',
                 'text':(f'{page} '+header+'\n\nWe measured absorption spectra.\n')}
                for i,(start,page) in enumerate(zip(starts,numbers))]
    return d


class RunningHeaderTests(unittest.TestCase):
    def test_repeated_header_is_mentioned_with_reproducible_positions(self):
        d=pages();r=classify(d)
        self.assertNotIn(BIPOLAR,accepted(r,2))
        e=next(l for l in r['mentions'] if l['id']==BIPOLAR)['evidence'][0]
        self.assertEqual(e['basis'],'repeated_running_header')
        trace=e['running_header'];self.assertEqual(len(trace['occurrences']),2)
        self.assertEqual({x['page'] for x in trace['occurrences']},{2,3});validate_evidence(d,r)

    def test_real_body_hit_in_same_block_is_kept(self):
        d=pages();d['chunks'][0]['text']+='We designed bipolar host materials by combining electron and hole transport units.'
        r=classify(d);self.assertIn(BIPOLAR,accepted(r,2))
        label=next(l for l in r['level2'] if l['id']==BIPOLAR)
        self.assertTrue(all('running_header' not in e for e in label['evidence']))
        self.assertIn(BIPOLAR,{l['id'] for l in r['mentions']});validate_evidence(d,r)

    def test_metadata_centrality_cannot_validate_header_only_body(self):
        d=pages();d['title']='Bipolar host materials'
        self.assertNotIn(BIPOLAR,accepted(classify(d),2))

    def test_unknown_page_start_is_not_guessed_from_chunk_id(self):
        d=pages()
        for c in d['chunks']:c.pop('page_start')
        self.assertIn(BIPOLAR,accepted(classify(d),2))

    def test_midpage_blocks_are_not_called_page_headers(self):
        d=pages(starts=(100,200));r=classify(d)
        self.assertIn(BIPOLAR,accepted(r,2))
        self.assertFalse(any('running_header' in e for l in r['mentions'] for e in l['evidence']))

    def test_duplicates_on_one_page_are_insufficient(self):
        d=pages(numbers=(2,2));r=classify(d)
        self.assertIn(BIPOLAR,accepted(r,2))

    def test_one_page_or_different_headers_are_not_merged(self):
        d=pages();d['chunks']=d['chunks'][:1]
        self.assertIn(BIPOLAR,accepted(classify(d),2))
        d=pages();d['chunks'][1]['text']=d['chunks'][1]['text'].replace('phosphorescent','fluorescent')
        self.assertIn(BIPOLAR,accepted(classify(d),2))

    def test_repeated_actual_scientific_sentence_stays_body_evidence(self):
        for text in ['We designed bipolar host materials for efficient phosphorescent devices.',
                     'Bipolar host materials were designed for phosphorescent devices.']:
            d=pages(header=text);r=classify(d)
            self.assertIn(BIPOLAR,accepted(r,2));validate_evidence(d,r)

    def test_layout_and_separate_pagination_line_are_supported(self):
        d=pages();d['chunks'][0]['text']='2\n'+HEADER+'\nWe measured spectra.'
        d['chunks'][1]['text']=HEADER.replace(' ','\u00a0')+' 3\nWe measured spectra.'
        r=classify(d);self.assertNotIn(BIPOLAR,accepted(r,2));validate_evidence(d,r)

    def test_filter_uses_repetition_not_one_scientific_term(self):
        d=pages(header='Charge transfer processes in organic molecular crystals')
        r=classify(d);self.assertNotIn('mechanism.ct',accepted(r,2));validate_evidence(d,r)

    def test_level1_never_uses_original_page_header_context(self):
        d=pages(header='Thermally activated delayed fluorescence in molecular films')
        d['title']='TADF materials';r=classify(d)
        self.assertIn('topic.tadf',accepted(r,1));validate_evidence(d,r)

    def test_trace_tampering_is_rejected(self):
        d=pages();r=classify(d)
        for field,value in [('text','invented'),('start',1),('normalized','different'),('occurrences',[])]:
            bad=deepcopy(r);e=next(l for l in bad['mentions'] if l['id']==BIPOLAR)['evidence'][0]
            e['running_header'][field]=value
            with self.assertRaisesRegex(ValueError,'页眉'):validate_evidence(d,bad)

    def test_source_and_reference_sections_keep_their_existing_protection(self):
        d=pages()
        for c in d['chunks']:c['section']='references'
        self.assertNotIn(BIPOLAR,accepted(classify(d),2))

    def test_evidence_quotes_are_not_rewritten(self):
        d=pages();original=deepcopy(d);r=classify(d);self.assertEqual(d,original)
        for l in r['mentions']:
            for e in l['evidence']:
                c=next(c for c in d['chunks'] if c['id']==e['chunk_id'])
                self.assertEqual(c['text'][e['start']:e['end']],e['quote'])
