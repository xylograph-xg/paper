"""Generic question background cannot accumulate into a current-study core."""
import unittest
from literature.classifier import classify,validate_evidence
from literature.tests.test_context import document,accepted


GENERAL='In many cases, efficiency roll-off limits device performance.'
CURRENT='The tested device exhibits efficiency roll-off.'


def chunks(*texts, title='Unspecified system', abstract=''):
    d=document(title=title,abstract=abstract)
    d['chunks']=[{'id':f'body-{i}','scope':'fulltext','page':i+1,'section':'results','text':t} for i,t in enumerate(texts)]
    return d


class BackgroundQuestionTests(unittest.TestCase):
    def check_supporting(self,d):
        r=classify(d)
        self.assertNotIn('question.rolloff',{l['id'] for l in r['level2']})
        label=next(l for l in r['supporting_labels'] if l['id']=='question.rolloff')
        self.assertEqual(label['selection_basis'],'generic_background_question')
        validate_evidence(d,r)
        return label

    def test_two_generic_chunks_do_not_establish_core(self):
        label=self.check_supporting(chunks(GENERAL,'In general, efficiency roll-off limits output.'))
        self.assertEqual(len(label['evidence']),2)

    def test_one_background_plus_one_plain_observation_is_not_two_current_chunks(self):
        self.check_supporting(chunks(GENERAL,CURRENT))

    def test_generic_contribution_words_do_not_establish_current_focus(self):
        self.check_supporting(chunks('Several reports have shown how to reduce efficiency roll-off.'))
        self.check_supporting(chunks('Many studies aim to suppress efficiency roll-off.'))

    def test_explicit_current_owner_resets_generalizing_language(self):
        for text in ['We find that in many cases efficiency roll-off is reduced.',
                     'In general, our devices show reduced efficiency roll-off.',
                     'In many cases, efficiency roll-off is reduced in our devices.',
                     'This study generally demonstrates reduced efficiency roll-off.']:
            with self.subTest(text=text):
                d=chunks(text);r=classify(d)
                self.assertIn('question.rolloff',{l['id'] for l in r['level2']});validate_evidence(d,r)

    def test_two_real_results_keep_existing_core_route(self):
        d=chunks(CURRENT,'The second device exhibits efficiency roll-off at higher brightness.')
        self.assertIn('question.rolloff',{l['id'] for l in classify(d)['level2']})

    def test_independent_current_contribution_keeps_core(self):
        d=chunks(GENERAL,'We reduced efficiency roll-off in the optimized device.')
        self.assertIn('question.rolloff',{l['id'] for l in classify(d)['level2']})

    def test_stated_study_target_in_metadata_is_not_erased(self):
        for title,abstract in [('Efficiency roll-off in OLEDs',''),
                               ('Device study','We investigate efficiency roll-off.')]:
            d=chunks(GENERAL,title=title,abstract=abstract)
            self.assertIn('question.rolloff',{l['id'] for l in classify(d)['level2']})

    def test_metadata_still_cannot_supply_missing_body(self):
        r=classify(document(title='Efficiency roll-off',abstract='We investigate efficiency roll-off.'))
        self.assertNotIn('question.rolloff',accepted(r,2))

    def test_contrast_resets_local_general_background(self):
        d=chunks('In general, device losses differ, but the device design suppresses efficiency roll-off.')
        self.assertIn('question.rolloff',{l['id'] for l in classify(d)['level2']})

    def test_later_current_sentence_cannot_own_previous_generic_question(self):
        self.check_supporting(chunks('Many studies suppress efficiency roll-off. We designed a new emitter.'))
        self.check_supporting(chunks('Many studies suppress efficiency roll-off.43,44 We designed a new emitter.'))

    def test_old_quotes_pages_and_offsets_remain_exact(self):
        d=chunks('In many cases, eﬃciency roll-oﬀ limits device output.',CURRENT)
        label=self.check_supporting(d)
        for e in label['evidence']:
            text=next(c['text'] for c in d['chunks'] if c['id']==e['chunk_id'])
            self.assertEqual(text[e['start']:e['end']],e['quote'])
            self.assertEqual(text[e['focus_start']:e['focus_end']],e['focus_text'])

    def test_other_dimensions_and_current_method_are_unchanged(self):
        d=chunks(GENERAL,'We performed DFT calculations.',title='DFT study')
        r=classify(d);self.assertIn('method.dft',{l['id'] for l in r['level2']})
        validate_evidence(d,r)
