"""Generic context regression cases, independent of real-paper identifiers."""
from copy import deepcopy
import unittest

from literature.classifier import classify, validate_evidence, sentence_span
from literature.inputs import blocks_from_pages


def document(text='', abstract='', title='Unspecified system'):
    return {'paper_id':'context-test','title':title,'abstract':abstract,
        'metadata_fingerprint':'m','source_fingerprint':'s',
        'chunks':[{'id':'body','scope':'fulltext','page':1,'section':'results','text':text}] if text else []}


def accepted(result, level):
    return {x['id'] for x in result[f'level{level}']+result['supporting_labels'] if x['level']==level}


class ContextTests(unittest.TestCase):
    def test_adjacent_abstract_result_has_exact_antecedent(self):
        for subject,verb in [('These hybrids','emit'),('Such hybrids','exhibit'),('This hybrid','shows')]:
            with self.subTest(subject=subject):
                noun='hybrid' if subject=='This hybrid' else 'hybrids'
                first='Herein, we prepare '+noun+' from two components.'
                text=first+' '+subject+' '+verb+' phosphorescence at room temperature.'
                d=document(abstract=text);r=classify(d)
                label=next(x for x in r['level1'] if x['id']=='topic.phosphorescence')
                evidence=label['evidence'][0]
                self.assertEqual(evidence['basis'],'abstract_adjacent_result')
                self.assertEqual(evidence['antecedent'],{'text':first,'start':0,'end':len(first)})
                validate_evidence(d,r)

    def test_abstract_result_does_not_borrow_history_or_hypothesis(self):
        for first in ['Previously we prepared hybrids.', 'In 2018 we prepared hybrids.',
                      'We review hybrids.', 'We propose that hybrids might be useful.',
                      'Hybrids are known to be useful.', 'We prepare other hybrids.']:
            with self.subTest(first=first):
                r=classify(document(abstract=first+' These hybrids emit phosphorescence.'))
                self.assertNotIn('topic.phosphorescence',accepted(r,1))

    def test_abstract_result_requires_adjacent_matching_subject(self):
        for text in ['These hybrids emit phosphorescence.',
                     'We prepare crystals. These hybrids emit phosphorescence.',
                     'We prepare hybrids. Optical spectra are collected. These hybrids emit phosphorescence.',
                     'We prepare hybrids. These hybrids might emit phosphorescence.',
                     'We prepare hybrids. These hybrids show fluorescence while other compounds emit phosphorescence.',
                     'We prepare hybrids. These hybrids exhibit no evidence for phosphorescence.']:
            with self.subTest(text=text):
                self.assertNotIn('topic.phosphorescence',accepted(classify(document(abstract=text)),1))

    def test_abstract_result_does_not_admit_fine_or_body_labels(self):
        r=classify(document(abstract='We prepare hybrids. These hybrids show RISC.',
                            text='We prepare hybrids. These hybrids emit phosphorescence.'))
        self.assertNotIn('mechanism.risc',accepted(r,2))
        self.assertNotIn('topic.phosphorescence',accepted(r,1))

    def test_abstract_antecedent_tampering_is_rejected(self):
        d=document(abstract='We prepare hybrids. These hybrids emit phosphorescence.')
        r=classify(d);validate_evidence(d,r)
        for field,value in [('text','invented'),('start',1),('end',3)]:
            changed=deepcopy(r)
            next(x for x in changed['level1'] if x['id']=='topic.phosphorescence')['evidence'][0]['antecedent'][field]=value
            with self.assertRaisesRegex(ValueError,'指代'):validate_evidence(d,changed)

    def test_current_method_can_cite_prior_procedure_with_exact_evidence(self):
        for phrase in ['as described previously','as previously described','as reported earlier','as earlier detailed']:
            with self.subTest(phrase=phrase):
                text='DFT calculations were performed '+phrase+'.'
                d=document(text=text,title='DFT calculations of emitters')
                r=classify(d);labels=[x for x in r['level2'] if x['id']=='method.dft']
                self.assertEqual(len(labels),1)
                self.assertEqual(labels[0]['evidence'][0]['procedure_reference'],'current_use_citing_prior_procedure')
                self.assertEqual(labels[0]['evidence'][0]['focus_text'],text)
                validate_evidence(d,r)

    def test_prior_work_is_not_excused_by_procedure_reference(self):
        texts=['Previously we performed DFT calculations as described previously.',
               'In 2012 DFT calculations were performed as described previously.',
               'DFT calculations had been performed as previously described.',
               'Smith et al. performed DFT calculations as described previously.',
               'DFT calculations were not performed as described previously.',
               'DFT calculations, but X-ray measurements were performed as described previously.',
               'DFT calculations and X-ray measurements were performed as described previously.']
        for text in texts:
            with self.subTest(text=text):
                r=classify(document(text=text,title='DFT calculations of emitters'))
                self.assertNotIn('method.dft',accepted(r,2))

    def test_current_procedure_does_not_promote_routine_or_nonmethod_labels(self):
        r=classify(document(text='DFT calculations were performed as described previously.'))
        self.assertNotIn('method.dft',{x['id'] for x in r['level2']})
        self.assertIn('method.dft',{x['id'] for x in r['supporting_labels']})
        r=classify(document(text='RISC rates were measured as described previously.',title='RISC study'))
        self.assertNotIn('mechanism.risc',accepted(r,2))

    def test_nearby_own_claim_cannot_validate_historical_direction(self):
        d=document(abstract='Previous work investigated phosphorescence. We report TADF emitters.')
        r=classify(d)
        self.assertNotIn('topic.phosphorescence',accepted(r,1))
        self.assertIn('topic.tadf',accepted(r,1))

    def test_passive_abstract_claim_recognized(self):
        r=classify(document(abstract='TADF emitters are synthesized and characterized.'))
        self.assertIn('topic.tadf',accepted(r,1))

    def test_own_previous_work_is_still_previous(self):
        r=classify(document(text='Previously we investigated Dexter energy transfer. We investigate reverse intersystem crossing here.'))
        self.assertNotIn('mechanism.dexter',accepted(r,2))
        self.assertIn('mechanism.risc',accepted(r,2))

    def test_workup_quench_does_not_become_emission_quenching(self):
        d=document(text='The reaction was quenched carefully with water. We measured fluorescence quenching in the resulting films.')
        r=classify(d)
        values=[x for x in r['level2']+r['supporting_labels'] if x['id']=='question.quenching']
        self.assertTrue(values)
        self.assertTrue(all('reaction' not in e['focus_text'] for label in values for e in label['evidence']))
        self.assertNotIn('question.quenching',accepted(classify(document(text='The mixture was quenched with water.')),2))

    def test_abbreviation_and_matched_sentence_offsets(self):
        text='Example et al. reported Dexter energy transfer. We investigate RISC in Fig. 2 at 3.5 K.'
        r=classify(document(text=text))
        self.assertNotIn('mechanism.dexter',accepted(r,2))
        validate_evidence(document(text=text),r)
        a,b=sentence_span(text,text.index('RISC'),text.index('RISC')+4)
        self.assertEqual(text[a:b],'We investigate RISC in Fig. 2 at 3.5 K.')
        changed=deepcopy(r);changed['level2'][0]['evidence'][0]['focus_text']='invented'
        with self.assertRaisesRegex(ValueError,'判定句'):validate_evidence(document(text=text),changed)

    def test_roman_headings_identify_methods_and_exclude_references(self):
        pages=[{'source_page':1,'text':'II. EXPERIMENTAL METHODS\nWe measured transient photoluminescence spectra.\nIII. RESULTS AND DISCUSSION\nWe investigated RISC in these emitters.\nIV. REFERENCES\nA. Author reported Dexter energy transfer.'}]
        blocks=blocks_from_pages(pages)
        self.assertEqual({b['section'] for b in blocks},{'methods','results and discussion'})
        self.assertFalse(any('Author' in b['text'] for b in blocks))
