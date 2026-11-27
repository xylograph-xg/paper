import json
import tempfile
import unittest
from contextlib import contextmanager
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from review import web_feedback as w
from review.card_evaluation import RUBRIC


class ReviewTests(unittest.TestCase):
    def test_other_packet_conversation_rejected_before_scoring(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=root/'data/quality_reviews'
            prior=base/'previous/short_2';current=base/'current/short_2'
            prior.mkdir(parents=True);current.mkdir(parents=True)
            url='https://chatgpt.com/c/prior'
            w.save_json(prior/'web-attempt.json',{'conversation_url':url,'state':'feedback_received'})
            with patch.object(w,'ROOT',root):
                with self.assertRaisesRegex(ValueError,'其他材料占用'):
                    w.require_unique_review_conversation(current,url)
                w.require_unique_review_conversation(current,'https://chatgpt.com/c/new')
                w.require_unique_review_conversation(prior,url)
                with self.assertRaisesRegex(ValueError,'正式会话'):
                    w.require_unique_review_conversation(current,'https://chatgpt.com/')

    def feedback(self):
        return {'sample_kind': 'image_heavy', 'scores': {k: 9 for k in RUBRIC},
                'missing_inputs': [], 'issues': [], 'verdict': 'pass'}

    def test_truncated_and_wrong_kind_rejected(self):
        with self.assertRaises(ValueError):
            w.parse_feedback('```json\n{}', 'image_heavy')
        with self.assertRaises(ValueError):
            w.parse_feedback(json.dumps(self.feedback()), 'mixed')

    def test_missing_inputs_never_pass(self):
        data = self.feedback()
        data['missing_inputs'] = ['paper-review.pdf']
        self.assertFalse(w.parse_feedback(json.dumps(data), 'image_heavy')[1]['pass'])

    def test_known_renderer_citation_preserved(self):
        data = self.feedback()
        data['strengths'] = ['reference CITATION']
        text = json.dumps(data).replace('CITATION', ':chatgpt-content-reference{index="0"}')
        feedback, assessment = w.parse_feedback(text, 'image_heavy')
        self.assertEqual(feedback['strengths'], ['reference [citation 0]'])
        self.assertTrue(assessment['pass'])

    def test_rendered_json_language_title(self):
        self.assertTrue(w.parse_feedback('  JSON  '+json.dumps(self.feedback()),'image_heavy')[1]['pass'])
        self.assertTrue(w.parse_feedback('JSON'+json.dumps(self.feedback()),'image_heavy')[1]['pass'])

    def test_bad_json_reformatted_once_without_upload(self):
        answer=json.dumps(self.feedback());calls=[]
        class Locator:
            def count(self):return 0
        class Page:
            def locator(self,s):return Locator()
        class GPT:
            page=Page()
            def ask(self,*args,**kwargs):
                calls.append(kwargs)
                return answer
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);attempt={}
            bad=answer[:-1]+',}'
            result=w.parse_or_reformat(GPT(),bad,'image_heavy',d,attempt,d/'attempt.json',900)
            self.assertTrue(result[1]['pass']);self.assertEqual(len(calls),1)
            self.assertNotIn('files',calls[0]);self.assertTrue(attempt['format_followup'])
            class ChangedGPT(GPT):
                def ask(self,*args,**kwargs):
                    return answer.replace('"figure_integrity": 9','"figure_integrity": 8')
            with self.assertRaisesRegex(ValueError,'改变了原评分'):
                w.parse_or_reformat(ChangedGPT(),bad,'image_heavy',d,{},d/'changed.json',900)

    def test_uncertain_send_not_repeated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / 'data/quality_reviews/test'
            folder = run / 'image_heavy'
            folder.mkdir(parents=True)
            (folder / 'prompt.txt').write_text('review')
            (folder / 'paper-review.pdf').write_bytes(b'fixture')
            sample = {'kind': 'image_heavy', 'packet_files': ['paper-review.pdf'],
                      'review_pdf_sha256': w.digest(folder / 'paper-review.pdf'), 'feedback': None,
                      'paper_id':'fixture','card_sha256':'card',
                      'input_hashes':{n:w.digest(folder/n) for n in ('paper-review.pdf','prompt.txt')}}
            w.save_json(root/'manifest.json',{'state':'authorized_review','external_submission_blocked':False,'samples':{'image_heavy':'fixture'}})
            from core.catalog import Catalog
            catalog=Catalog(root/'catalog.sqlite3')
            w.save_json(run / 'run.json', {'samples': [sample]})
            calls = []
            class Page:
                url = 'https://chatgpt.com/c/fixture'
                def screenshot(self, **kwargs):
                    pass
            class GPT:
                page = Page()
                def verify_settings(self):
                    return {'model': 'fixture'}
                def ask(self, *args, **kwargs):
                    calls.append(1)
                    raise RuntimeError('connection lost after submission')
            @contextmanager
            def factory():
                yield GPT()
            with patch.object(w, 'ROOT', root), patch.object(w,'require_current_legacy_control'), patch('review.review_ledger.authorized',return_value=True), patch('review.review_ledger.catalog_for',return_value=catalog):
                w.run_reviews(run, factory=factory,manifest_path=root/'manifest.json')
                w.run_reviews(run, factory=factory,manifest_path=root/'manifest.json')
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads((folder / 'web-attempt.json').read_text())['state'], 'needs_inspection')

    def test_changed_pdf_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / 'image_heavy').mkdir()
            (run / 'image_heavy/paper-review.pdf').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                w.packet_files(run, {'kind': 'image_heavy', 'packet_files': ['paper-review.pdf'],
                                     'review_pdf_sha256': 'previous'})

    def test_success_saved_with_actual_settings(self):
        answer = json.dumps(self.feedback())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / 'data/quality_reviews/test'
            folder = run / 'image_heavy'
            folder.mkdir(parents=True)
            (folder / 'prompt.txt').write_text('review')
            (folder / 'paper-review.pdf').write_bytes(b'fixture')
            sample = {'kind': 'image_heavy', 'packet_files': ['paper-review.pdf'],
                      'review_pdf_sha256': w.digest(folder / 'paper-review.pdf'), 'feedback': None,
                      'paper_id':'fixture','card_sha256':'card',
                      'input_hashes':{n:w.digest(folder/n) for n in ('paper-review.pdf','prompt.txt')}}
            w.save_json(root/'manifest.json',{'state':'authorized_review','external_submission_blocked':False,'samples':{'image_heavy':'fixture'}})
            from core.catalog import Catalog
            catalog=Catalog(root/'catalog.sqlite3')
            w.save_json(run / 'run.json', {'samples': [sample]})
            class Locator:
                def count(self):
                    return 0
            class Page:
                url = 'https://chatgpt.com/c/fixture'
                def locator(self, selector):
                    return Locator()
                def screenshot(self, **kwargs):
                    pass
            class GPT:
                page = Page()
                def verify_settings(self):
                    return {'model': 'actual-fixture'}
                def ask(self, *args, **kwargs):
                    return answer
            @contextmanager
            def factory():
                yield GPT()
            with patch.object(w, 'ROOT', root), patch.object(w,'require_current_legacy_control'), patch('review.review_ledger.authorized',return_value=True), patch('review.review_ledger.catalog_for',return_value=catalog):
                result = w.run_reviews(run, factory=factory,manifest_path=root/'manifest.json')
            self.assertEqual(result['state'], 'reviewed')
            self.assertEqual((folder / 'feedback-raw.txt').read_text(), answer)
            attempt = json.loads((folder / 'web-attempt.json').read_text())
            self.assertEqual(attempt['settings']['model'], 'actual-fixture')
            self.assertEqual(attempt['assessment']['weighted_score'], 90)


if __name__ == '__main__':
    unittest.main()
