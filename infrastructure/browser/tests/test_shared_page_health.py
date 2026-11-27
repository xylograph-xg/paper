"""Health decisions bind to original receipts; all evidence lives in tempdirs."""
import copy
import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import Mock

from browser.shared_page_health import classify, snapshot_page


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class SharedPageHealth(unittest.TestCase):
    def test_original_terminal_empty_can_be_identified_without_faking_a_response(self):
        snapshot={**self.snapshot,'uploading':False}
        result=self.check(snapshot,entry={'state':'busy'})
        self.assertEqual(result['health'],'terminal_empty')
        self.assertFalse(result['replace_allowed']);self.assertFalse(result['requeue_allowed'])
        for patch in ({'streaming':True},{'uploading':True},{'draft':'new user draft'},{'login':True}):
            protected=self.check({**snapshot,**patch},entry={'state':'busy'})
            self.assertNotEqual(protected['health'],'terminal_empty')
        self.assertNotEqual(self.check({**snapshot,'user_texts':['different material']},entry={'state':'busy'})['health'],'terminal_empty')

    def test_never_used_owned_repair_stays_recoverable_after_inspection_error(self):
        s={**self.snapshot,'url':'https://chatgpt.com/','user_texts':[],'answer_texts':[],
           'errors':['net::ERR_CONNECTION_RESET'],'terminal_complete':False}
        e={'state':'needs_inspection','never_submitted':True,'origin':'shared_page_health_repair','repair_id':'original-owner-nonce'}
        first=classify(s,e,None,target_history_complete=True)
        second=classify({**s,'checked_at':130},e,None,previous=first,target_history_complete=True)
        self.assertEqual(second['health'],'not_sent_error');self.assertTrue(second['replace_allowed'])
        self.assertFalse(classify(s,e,None,target_history_complete=False)['replace_allowed'])
        self.assertFalse(classify({**s,'checked_at':130},dict(e,submission_unknown=True),None,
                                 previous=first,target_history_complete=True)['replace_allowed'])
    def test_startup_opening_error_page_is_replaceable_after_stable_history_check(self):
        snapshot={**self.snapshot,'url':'chrome-error://chromewebdata/','user_texts':[],'answer_texts':[],
                  'errors':['net::ERR_SSL_PROTOCOL_ERROR'],'terminal_complete':False}
        entry={'state':'opening','never_submitted':True}
        first=classify(snapshot,entry,None,target_history_complete=True)
        second=classify({**snapshot,'checked_at':130},entry,None,previous=first,target_history_complete=True)
        self.assertEqual(second['health'],'not_sent_error')
        self.assertTrue(second['replace_allowed'])
        self.assertFalse(classify(snapshot,entry,None,target_history_complete=False)['replace_allowed'])
        self.assertFalse(classify(snapshot,entry,None,target_history_complete=True,
            record_paths=[self.attempt['_ledger_path']])['replace_allowed'])
    def test_startup_opening_proxy_error_waits_for_reload_not_replacement(self):
        snapshot={**self.snapshot,'url':'chrome-error://chromewebdata/','user_texts':[],'answer_texts':[],
                  'errors':['net::ERR_PROXY_CONNECTION_FAILED'],'terminal_complete':False}
        entry={'state':'opening','never_submitted':True}
        first=classify(snapshot,entry,None,target_history_complete=True)
        second=classify({**snapshot,'checked_at':130},entry,None,previous=first,target_history_complete=True)
        self.assertEqual(second['health'],'network_unavailable')
        self.assertFalse(second['replace_allowed'])
    def test_never_used_flag_cannot_shadow_a_real_sent_history(self):
        s={**self.snapshot,'url':'https://chatgpt.com/','user_texts':[],'answer_texts':[],
           'errors':['net::ERR_CONNECTION_RESET'],'terminal_complete':False}
        e={'state':'needs_inspection','never_submitted':True,'origin':'shared_page_health_repair','repair_id':'original-owner-nonce'}
        h=classify(s,e,None,target_history_complete=True,record_paths=[self.attempt['_ledger_path']])
        self.assertFalse(h['replace_allowed']);self.assertNotEqual(h['health'],'healthy_blank')
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.prompt = '只处理 web-card-11111111-1111-4111-8111-111111111111-input123 的合成材料。'
        self.url = 'https://chatgpt.com/c/original-response'
        self.entry = {'state': 'needs_inspection'}
        self.snapshot = {
            'target_id': 'original-target', 'url': self.url, 'checked_at': 100.0,
            'inspection_complete': True, 'user_texts': [self.prompt], 'answer_texts': [],
            'draft': '', 'attachments': 0, 'streaming': False, 'terminal_complete': True,
            'user_turn_complete': False, 'terminal_stopped': False, 'verification': False,
            'login': False, 'quota': False, 'errors': [],
        }
        self.attempt = self.record(self.root / 'original')

    def record(self, folder, state='submitted', raw=None, prompt=None, url=None):
        folder.mkdir(parents=True, exist_ok=True)
        actual_prompt = self.prompt if prompt is None else prompt
        (folder / 'prompt-actual.txt').write_text(actual_prompt)
        record = {
            'state': state, 'target_id': 'original-target', 'send_click_started': True,
            'conversation_url': self.url if url is None else url,
            'actual_prompt_sha256': sha(actual_prompt), 'created': 1.0,
        }
        if raw is not None:
            record['raw_sha256'] = sha(raw)
            (folder / 'response-raw.txt').write_text(raw)
        path = folder / 'attempt.json'
        path.write_text(json.dumps(record))
        return {**record, '_ledger_path': str(path.resolve())}

    def check(self, snapshot=None, entry=None, attempt=None, **options):
        current = copy.deepcopy(self.snapshot if snapshot is None else snapshot)
        data = self.entry if entry is None else entry
        ledger = self.attempt if attempt is None else attempt
        return classify(current, data, ledger, urls=options.pop('urls', [current['url']]), **options)

    def stable_check(self, snapshot=None, entry=None, attempt=None, **options):
        current = copy.deepcopy(self.snapshot if snapshot is None else snapshot)
        first = self.check(current, entry, attempt, **options)
        current['checked_at'] += 60
        return self.check(current, entry, attempt, previous=first, **options)

    def test_invalid_json_saved_prefix_can_complete_only_from_stable_original_response(self):
        prefix='{"value": "part'
        live='{"value": "part completed"}'
        record=self.record(self.root/'prefix',state='response_saved',raw=prefix)
        self.snapshot['answer_texts']=[live]
        entry={'state':'needs_inspection','raw_sha256':sha(prefix),'raw_path':str(self.root/'prefix'/'response-raw.txt'),
               'conversation_url':self.url}
        first=self.check(entry=entry,attempt=record)
        self.assertEqual(first['health'],'waiting_stable')
        result=self.stable_check(entry=entry,attempt=record)
        self.assertEqual(result['health'],'saved_prefix_completion');self.assertTrue(result['collect_allowed'])
        self.assertEqual((self.root/'prefix'/'response-raw.txt').read_text(),prefix)
        self.snapshot['answer_texts']=['{"value": "different"}']
        self.assertEqual(self.stable_check(entry=entry,attempt=record)['health'],'saved_response_protected')

    def test_busy_page_with_bound_saved_answer_can_recover_its_slot(self):
        raw = '{"answer":"saved original"}'
        record = self.record(self.root/'saved', state='response_saved', raw=raw)
        snapshot = {**self.snapshot, 'answer_texts': [raw], 'uploading': False}
        entry = {'state': 'busy', 'conversation_url': self.url}
        result = self.check(snapshot, entry, record, target_history_complete=True)
        self.assertEqual(result['health'], 'raw_path_repair')
        self.assertEqual(result['repair_raw_path'], str((self.root/'saved'/'response-raw.txt').resolve()))
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])
        for update in ({'streaming': True}, {'uploading': True}, {'draft': 'new draft'},
                       {'terminal_complete': False}, {'answer_texts': ['different']}):
            with self.subTest(update=update):
                h = self.check({**snapshot, **update}, entry, record, target_history_complete=True)
                self.assertNotEqual(h['health'], 'raw_path_repair')
        self.assertEqual(self.check(snapshot, entry, record)['health'], 'busy')
        self.assertEqual(self.check(snapshot, entry, record, target_history_complete=True,
                                    record_paths=[self.attempt['_ledger_path']])['health'], 'busy')

    def test_valid_saved_json_is_never_replaced_by_a_larger_changed_answer(self):
        record=self.record(self.root/'valid',state='response_saved',raw='{}')
        self.snapshot['answer_texts']=['{} trailing']
        entry={'state':'needs_inspection','raw_sha256':sha('{}'),'conversation_url':self.url}
        self.assertEqual(self.stable_check(entry=entry,attempt=record)['health'],'saved_response_protected')

    def saved(self, folder=None, raw='完整合成回答 α'):
        record = self.record(folder or self.root / 'saved', state='response_saved', raw=raw)
        entry = {'state': 'ready', 'raw_path': str(Path(record['_ledger_path']).parent / 'response-raw.txt'),
                 'raw_sha256': sha(raw), 'conversation_url': self.url}
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['answer_texts'] = [raw]
        return snapshot, entry, record

    def test_old_saved_response_does_not_shadow_current_terminal_request(self):
        _, entry, saved = self.saved()
        current = self.record(self.root/'current', state='needs_inspection', url=self.url+'-new')
        snapshot = {**self.snapshot, 'url': current['conversation_url'], 'terminal_complete': True}
        result = self.stable_check(snapshot, entry, current, record_paths=[saved['_ledger_path']])
        self.assertEqual(result['health'], 'terminal_no_response')
        self.assertTrue(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])

    def test_saved_history_allows_clean_homepage_only_after_all_receipts_end(self):
        _, entry, saved = self.saved()
        blank = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [], 'terminal_complete': False}
        self.assertEqual(self.check(blank, entry, saved)['health'], 'healthy_blank')
        unknown = self.record(self.root/'unknown', state='needs_inspection')
        result = self.check(blank, entry, unknown, record_paths=[saved['_ledger_path']])
        self.assertFalse(result['replace_allowed'])
        self.assertNotEqual(result['health'], 'healthy_blank')
        Path(saved['_ledger_path']).parent.joinpath('response-raw.txt').write_text('changed')
        self.assertNotEqual(self.check(blank, entry, saved)['health'], 'healthy_blank')

    def homepage_error_case(self, name='homepage-error'):
        _, entry, saved = self.saved(self.root / name / 'saved')
        unsent = self.record(self.root / name / 'unsent', state='not_sent', url='https://chatgpt.com/')
        unsent['send_click_started'] = False
        Path(unsent['_ledger_path']).write_text(json.dumps(unsent))
        notice = '请尝试重新加载，或退出登录后重新登录'
        snapshot = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [],
                    'answer_texts': [], 'terminal_complete': False, 'errors': [notice],
                    'page_error_detection_version': 1,
                    'page_error_notices': [{'text': notice, 'source': 'visible_main_notice_ui'}]}
        return snapshot, {**entry, 'state': 'needs_inspection'}, saved, unsent

    def test_completed_homepage_ui_error_requires_stability_and_archival_without_requeue(self):
        snapshot, entry, saved, unsent = self.homepage_error_case()
        paths = [saved['_ledger_path'], unsent['_ledger_path']]
        before = {path: Path(path).read_bytes() for path in paths}
        raw = Path(entry['raw_path']).read_bytes()
        first = self.check(snapshot, entry, unsent, record_paths=paths)
        self.assertEqual(first['health'], 'waiting_stable')
        self.assertFalse(first['replace_allowed'])
        self.assertFalse(self.check({**snapshot, 'checked_at': 109.0}, entry, unsent,
                                    previous=first, record_paths=paths)['replace_allowed'])
        result = self.stable_check(snapshot, entry, unsent, record_paths=paths)
        self.assertEqual(result['health'], 'completed_homepage_error')
        self.assertTrue(result['replace_allowed'])
        self.assertEqual(set(result['evidence']['completed_history_paths']), set(paths))
        self.assertEqual(result['evidence']['homepage_error_notice'], snapshot['errors'][0])
        self.assertEqual(result['evidence']['snapshot']['page_error_notices'], snapshot['page_error_notices'])
        self.assertFalse(result['collect_allowed'])
        self.assertFalse(result['requeue_allowed'])
        self.assertEqual({path: Path(path).read_bytes() for path in paths}, before)
        self.assertEqual(Path(entry['raw_path']).read_bytes(), raw)

    def test_homepage_error_text_requires_current_ui_provenance_and_exact_notice(self):
        snapshot, entry, saved, unsent = self.homepage_error_case()
        variants = [
            {'page_error_detection_version': None}, {'page_error_detection_version': True},
            {'page_error_notices': []},
            {'page_error_notices': [{'text': snapshot['errors'][0], 'source': 'assistant_message'}]},
            {'page_error_notices': [{'text': '论文引述：' + snapshot['errors'][0], 'source': 'visible_main_notice_ui'}]},
            {'errors': snapshot['errors'] + ['请登录后继续']},
            {'page_error_notices': [{'text': '请登录后继续', 'source': 'visible_main_notice_ui'}]},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                result = self.stable_check({**snapshot, **changes}, entry, unsent,
                                           record_paths=[saved['_ledger_path']])
                self.assertFalse(result['replace_allowed'])

    def test_homepage_error_preserves_messages_account_blocks_drafts_and_activity(self):
        snapshot, entry, saved, unsent = self.homepage_error_case()
        variants = [
            {'user_texts': [self.prompt]}, {'answer_texts': [snapshot['errors'][0]]},
            {'answer_element_count': 1}, {'draft': 'new draft'}, {'attachments': 1},
            {'login': True}, {'verification': True}, {'quota': True}, {'streaming': True},
            {'inspection_complete': False}, {'url': self.url},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                result = self.stable_check({**snapshot, **changes}, entry, unsent,
                                           record_paths=[saved['_ledger_path']])
                self.assertFalse(result['replace_allowed'])
        for changes in ({'state': 'busy'}, {'submission_unknown': True}, {'owned': False}):
            with self.subTest(entry=changes):
                result = self.stable_check(snapshot, {**entry, **changes}, unsent,
                                           record_paths=[saved['_ledger_path']])
                self.assertFalse(result['replace_allowed'])

    def test_homepage_error_requires_every_target_history_to_end_with_verified_artifacts(self):
        for mode in ('unknown', 'missing_raw', 'changed_raw', 'empty_raw', 'changed_prompt', 'missing_ledger', 'invalid_url'):
            with self.subTest(mode=mode):
                snapshot, entry, saved, unsent = self.homepage_error_case(mode)
                paths = [saved['_ledger_path']]
                artifact = Path(entry['raw_path'])
                if mode == 'unknown':
                    unknown = self.record(self.root / mode / 'unknown', state='needs_inspection')
                    paths.append(unknown['_ledger_path'])
                elif mode == 'missing_raw':
                    artifact.unlink()
                elif mode == 'changed_raw':
                    artifact.write_text('changed')
                elif mode == 'empty_raw':
                    artifact.write_text('')
                    saved['raw_sha256'] = sha('')
                    Path(saved['_ledger_path']).write_text(json.dumps(saved))
                elif mode == 'changed_prompt':
                    artifact.parent.joinpath('prompt-actual.txt').write_text('changed prompt')
                elif mode == 'missing_ledger':
                    Path(saved['_ledger_path']).unlink()
                elif mode == 'invalid_url':
                    saved['conversation_url'] = 'https://chatgpt.com/'
                    Path(saved['_ledger_path']).write_text(json.dumps(saved))
                result = self.stable_check(snapshot, entry, unsent, record_paths=paths)
                self.assertFalse(result['replace_allowed'])
                self.assertFalse(result['requeue_allowed'])

    def test_homepage_error_stability_includes_the_ui_error_provenance(self):
        snapshot, entry, saved, unsent = self.homepage_error_case()
        first = self.check(snapshot, entry, unsent, record_paths=[saved['_ledger_path']])
        changed = {**snapshot, 'checked_at': 160.0,
                   'page_error_notices': [{**snapshot['page_error_notices'][0], 'source': 'assistant_message'}]}
        self.assertFalse(self.check(changed, entry, unsent, previous=first,
                                    record_paths=[saved['_ledger_path']])['replace_allowed'])

    def test_unsubmitted_blank_page_is_healthy_and_never_needs_replacement(self):
        snapshot = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [], 'terminal_complete': False}
        result = classify(snapshot, {'state': 'ready_blank'}, urls=[snapshot['url']])
        self.assertEqual(result['health'], 'healthy_blank')
        self.assertFalse(result['replace_allowed'])

    def test_current_homepage_loading_error_on_known_unsent_page_is_not_healthy(self):
        notice='请尝试重新加载，或退出登录后重新登录'
        snapshot={**self.snapshot,'url':'https://chatgpt.com/','user_texts':[],
            'terminal_complete':False,'errors':[notice],'page_error_detection_version':1,
            'page_error_notices':[{'text':notice,'source':'visible_main_notice_ui'}]}
        attempt={'state':'not_sent','target_id':'original-target','send_click_started':False}
        first=classify(snapshot,{'state':'needs_inspection'},attempt,urls=[snapshot['url']])
        self.assertEqual(first['health'],'waiting_stable');self.assertFalse(first['replace_allowed'])
        snapshot['checked_at']=160
        second=classify(snapshot,{'state':'needs_inspection'},attempt,urls=[snapshot['url']],previous=first)
        self.assertEqual(second['health'],'not_sent_error');self.assertTrue(second['replace_allowed'])
        self.assertFalse(second['requeue_allowed'])
        snapshot['page_error_notices'][0]['source']='assistant_message'
        self.assertFalse(classify(snapshot,{'state':'needs_inspection'},attempt,urls=[snapshot['url']],previous=first)['replace_allowed'])
        snapshot['page_error_notices'][0]['source']='visible_main_notice_ui'
        attempt['send_click_started']=True
        self.assertEqual(classify(snapshot,{'state':'needs_inspection'},attempt,urls=[snapshot['url']],previous=first)['health'],'unknown')

    def test_observed_short_retry_notice_requires_original_unsent_proof_and_stability(self):
        notice = '请重试，或退出登录后重新登录'
        snapshot = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [],
                    'terminal_complete': False, 'composer_available': False,
                    'errors': [notice], 'page_error_detection_version': 1,
                    'page_error_notices': [{'text': notice, 'source': 'visible_main_notice_ui'}]}
        attempt = {'state': 'not_sent', 'target_id': 'original-target', 'send_click_started': False}
        first = classify(snapshot, self.entry, attempt)
        self.assertEqual(first['health'], 'waiting_stable')
        second = classify({**snapshot, 'checked_at': 130.0}, self.entry, attempt, previous=first)
        self.assertEqual(second['health'], 'not_sent_error')
        self.assertTrue(second['replace_allowed'])
        self.assertFalse(second['requeue_allowed'])
        for changed in ({'login': True}, {'verification': True}, {'quota': True},
                        {'streaming': True}, {'draft': 'user draft'}, {'attachments': 1}):
            with self.subTest(changed=changed):
                self.assertFalse(classify({**snapshot, **changed, 'checked_at': 130.0},
                                         self.entry, attempt, previous=first)['replace_allowed'])

    def test_unavailable_or_unattributed_error_page_never_becomes_healthy_blank(self):
        blank = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [],
                 'terminal_complete': False}
        for changed in ({'composer_available': False}, {'errors': ['unclassified page failure']},
                        {'errors': ['请重试，或退出登录后重新登录'],
                         'page_error_detection_version': 1,
                         'page_error_notices': [{'text': '请重试，或退出登录后重新登录',
                                                'source': 'assistant_message'}]}):
            with self.subTest(changed=changed):
                result = classify({**blank, **changed}, {'state': 'ready_blank'})
                self.assertEqual(result['health'], 'protected')
                self.assertFalse(result['replace_allowed'])

    def test_saved_homepage_without_composer_is_not_reusable(self):
        blank, entry, saved = self.saved()
        blank.update(url='https://chatgpt.com/', user_texts=[], answer_texts=[],
                     terminal_complete=False, composer_available=False)
        self.assertNotEqual(self.check(blank, entry, saved)['health'], 'healthy_blank')

    def test_busy_and_streaming_pages_are_always_preserved(self):
        for state, streaming in [('busy', False), ('submitting', False), ('collecting', False),
                                 ('needs_inspection', True)]:
            with self.subTest(state=state, streaming=streaming):
                snapshot = {**self.snapshot, 'streaming': streaming, 'errors': ['Something went wrong']}
                result = self.stable_check(snapshot, {'state': state})
                self.assertEqual(result['health'], 'busy')
                self.assertFalse(result['replace_allowed'])

    def test_login_verification_and_quota_are_preserved_even_on_error_page(self):
        for flag in ('login', 'verification', 'quota'):
            with self.subTest(flag=flag):
                snapshot = {**self.snapshot, flag: True, 'errors': ['ERR_SSL_PROTOCOL_ERROR']}
                result = self.stable_check(snapshot)
                self.assertEqual(result['health'], flag)
                self.assertFalse(result['replace_allowed'])

    def test_quota_notice_never_becomes_bad_unsent_page(self):
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                   'error': '附件上传失败：已达上传上限'}
        snapshot = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [], 'terminal_complete': False}
        result = self.stable_check(snapshot, attempt=attempt)
        self.assertEqual(result['health'], 'quota')
        self.assertFalse(result['replace_allowed'])

    def test_scientific_limit_words_do_not_classify_a_saved_reply_as_quota(self):
        for raw in ('PLQY达到高值；TT人口30%限制决定效率上限。',
                    'There are too many files in the measured scientific dataset; quota is a model parameter.'):
            with self.subTest(raw=raw):
                snapshot, entry, saved = self.saved(self.root / sha(raw), raw=raw)
                snapshot.update(body=self.prompt + '\n' + raw, quota_detection_version=1,
                                quota_notice='', quota_notices=[], errors=[raw])
                result = self.check(snapshot, entry, saved)
                self.assertEqual(result['health'], 'completed_saved')
                self.assertFalse(result['replace_allowed'])

    def test_live_quota_notice_evidence_is_retained_without_replacement_or_requeue(self):
        notice = '文件附件数量限制。请于10月9日 23:45后重试。'
        snapshot = {**self.snapshot, 'quota': True, 'quota_detection_version': 1,
                    'quota_notice': notice, 'quota_notices': [
                        {'text': notice, 'source': 'visible_notice_ui', 'role': 'menu', 'testid': None}]}
        result = self.check(snapshot)
        self.assertEqual(result['health'], 'quota')
        self.assertEqual(result['evidence']['quota_notice'], notice)
        self.assertEqual(result['evidence']['snapshot']['quota_notices'], snapshot['quota_notices'])
        self.assertEqual(result['evidence']['quota_source'], 'live_notice_ui')
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])

    def test_old_quota_error_is_history_when_current_notice_reader_finds_no_limit(self):
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                   'error': '附件上传失败：已达上传上限'}
        original = copy.deepcopy(attempt)
        snapshot = {**self.snapshot, 'quota_detection_version': 1, 'quota_notice': '', 'quota_notices': []}
        result = self.check(snapshot, attempt=attempt)
        self.assertEqual(result['health'], 'unknown')
        self.assertNotIn('quota_source', result['evidence'])
        self.assertTrue(result['evidence']['historical_attempt_error']['quota'])
        self.assertEqual(result['evidence']['historical_attempt_error']['error'], attempt['error'])
        self.assertEqual(result['evidence']['quota_notice'], '')
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])
        self.assertEqual(attempt, original)

    def test_old_upload_error_does_not_mark_current_clean_unsent_page_broken(self):
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                   'error': '附件上传失败：已达上传上限', 'retries': 2}
        snapshot = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [],
                    'terminal_complete': False, 'quota_detection_version': 1,
                    'quota_notice': '', 'quota_notices': []}
        original = copy.deepcopy(attempt)
        result = self.stable_check(snapshot, entry={'state': 'ready_blank'}, attempt=attempt)
        self.assertEqual(result['health'], 'healthy_blank')
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])
        self.assertEqual(attempt, original)

    def test_current_clean_page_with_old_quota_and_uncollected_history_stays_unknown(self):
        prior = self.record(self.root / 'outstanding-quota', state='submitted')
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                   'error': 'Upload limit reached.'}
        snapshot = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [],
                    'terminal_complete': False, 'quota_detection_version': 1,
                    'quota_notice': '', 'quota_notices': []}
        result = self.stable_check(snapshot, entry={'state': 'ready_blank'}, attempt=attempt,
                                   record_paths=[prior['_ledger_path']])
        self.assertEqual(result['health'], 'unknown')
        self.assertIn(prior['_ledger_path'], result['evidence']['uncollected_history'])
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])

    def test_current_limit_notice_still_protects_page_with_old_unsent_error(self):
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                   'error': 'Previous upload limit reached.'}
        snapshot = {**self.snapshot, 'quota': True, 'quota_detection_version': 1,
                    'quota_notice': 'Upload limit reached. Try again later.', 'quota_notices': []}
        result = self.check(snapshot, attempt=attempt)
        self.assertEqual(result['health'], 'quota')
        self.assertEqual(result['evidence']['quota_source'], 'live_notice_ui')
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])

    def test_legacy_snapshot_preserves_transport_limit_as_fail_closed(self):
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                   'error': 'Upload limit reached.'}
        result = self.check(attempt=attempt)
        self.assertEqual(result['health'], 'quota')
        self.assertEqual(result['evidence']['quota_source'], 'attempt_error')
        self.assertFalse(result['replace_allowed'])

    def test_local_and_blank_urls_do_not_prove_known_sent_request_finished(self):
        for url in ('https://chatgpt.com/c/local-chatgpt-unknown', 'https://chatgpt.com/'):
            with self.subTest(url=url):
                snapshot = {**self.snapshot, 'url': url, 'errors': ['Something went wrong']}
                result = self.stable_check(snapshot)
                self.assertEqual(result['health'], 'unknown')
                self.assertFalse(result['replace_allowed'])

    def test_user_turn_complete_alone_cannot_release_lost_active_request(self):
        snapshot = {**self.snapshot, 'terminal_complete': False, 'user_turn_complete': True}
        result = self.stable_check(snapshot)
        self.assertEqual(result['health'], 'unknown')
        self.assertFalse(result['replace_allowed'])

    def test_formal_empty_assistant_terminal_requires_two_stable_checks(self):
        entry_before = copy.deepcopy(self.entry)
        attempt_before = copy.deepcopy(self.attempt)
        first = self.check()
        self.assertEqual(first['health'], 'waiting_stable')
        self.assertFalse(first['replace_allowed'])
        result = self.stable_check()
        self.assertEqual(result['health'], 'terminal_no_response')
        self.assertTrue(result['replace_allowed'])
        self.assertEqual(result['terminal_error']['original_state'], 'submitted')
        self.assertTrue(result['terminal_error']['send_click_started'])
        self.assertFalse(result['requeue_allowed'])
        self.assertEqual(result['matched_record_path'], self.attempt['_ledger_path'])
        self.assertEqual(self.entry, entry_before)
        self.assertEqual(self.attempt, attempt_before)

    def test_empty_assistant_strings_are_not_uncollected_responses(self):
        for answers in ([''], [' ', '\n\t'], ['', '\u3000']):
            for state in ('submitted', 'submission_started', 'needs_inspection'):
                with self.subTest(answers=answers, state=state):
                    snapshot = {**self.snapshot, 'answer_texts': answers}
                    attempt = {**self.attempt, 'state': state}
                    first = self.check(snapshot, attempt=attempt)
                    self.assertEqual(first['health'], 'waiting_stable')
                    result = self.stable_check(snapshot, attempt=attempt)
                    self.assertEqual(result['health'], 'terminal_no_response')
                    self.assertTrue(result['replace_allowed'])
                    self.assertEqual(result['evidence']['answer_count'], 0)
                    self.assertFalse(result['collect_allowed'])
                    self.assertFalse(result['requeue_allowed'])

    def test_nonempty_response_keeps_original_bytes_between_empty_placeholders(self):
        raw = ' \n{"synthetic": "完整回答 α"}\n '
        snapshot = {**self.snapshot, 'answer_texts': ['', raw, '\n\t']}
        result = self.stable_check(snapshot)
        self.assertEqual(result['health'], 'completed_unsaved')
        self.assertEqual(result['evidence']['raw'], raw)
        self.assertEqual(result['evidence']['raw_sha256'], sha(raw))
        self.assertEqual(result['evidence']['answer_count'], 1)
        self.assertTrue(result['collect_allowed'])
        self.assertFalse(result['replace_allowed'])

    def test_existing_empty_saved_artifact_is_terminal_failure_without_ledger_changes(self):
        for raw in ('', ' \n\t\u3000'):
            with self.subTest(raw=raw):
                snapshot, entry, record = self.saved(self.root / ('saved-empty-' + sha(raw)), raw=raw)
                snapshot['answer_texts'] = ['', '\n']
                ledger = Path(record['_ledger_path'])
                before = ledger.read_bytes()
                artifact = Path(entry['raw_path'])
                artifact_before = artifact.read_bytes()
                first = self.check(snapshot, entry, record)
                self.assertEqual(first['health'], 'waiting_stable')
                self.assertFalse(first['replace_allowed'])
                result = self.stable_check(snapshot, entry, record)
                self.assertEqual(result['health'], 'terminal_no_response')
                self.assertTrue(result['replace_allowed'])
                self.assertTrue(result['evidence']['empty_saved_artifact'])
                self.assertEqual(result['matched_record_path'], str(ledger))
                self.assertFalse(result['collect_allowed'])
                self.assertFalse(result['requeue_allowed'])
                self.assertEqual(ledger.read_bytes(), before)
                self.assertEqual(artifact.read_bytes(), artifact_before)

    def test_archived_empty_saved_artifact_uses_original_prompt_after_new_unsent_attempt(self):
        snapshot, entry, saved = self.saved(self.root / 'history' / 'archived-empty', raw='')
        snapshot['answer_texts'] = []
        latest = self.record(self.root / 'new-unsent', state='not_sent', prompt='新材料 card-review-' + 'a' * 24)
        latest['send_click_started'] = False
        result = self.stable_check(snapshot, {**entry, 'state': 'needs_inspection'}, latest,
                                   record_paths=[saved['_ledger_path']])
        self.assertEqual(result['health'], 'terminal_no_response')
        self.assertTrue(result['replace_allowed'])
        self.assertEqual(result['matched_record_path'], saved['_ledger_path'])
        self.assertEqual(result['evidence']['receipt']['actual_prompt_sha256'], sha(self.prompt))

    def test_missing_changed_or_nonempty_saved_artifact_never_releases_empty_live_page(self):
        for mode in ('missing', 'changed', 'nonempty', 'wrong_prompt', 'no_terminal', 'duplicate_url', 'ambiguous'):
            with self.subTest(mode=mode):
                snapshot, entry, saved = self.saved(self.root / mode, raw='scientific answer' if mode == 'nonempty' else '')
                snapshot['answer_texts'] = []
                path = Path(entry['raw_path'])
                options = {}
                if mode == 'missing':
                    path.unlink()
                elif mode == 'changed':
                    path.write_text('changed')
                elif mode == 'wrong_prompt':
                    snapshot['user_texts'] = ['材料不同 card-review-' + 'f' * 24]
                elif mode == 'no_terminal':
                    snapshot['terminal_complete'] = False
                elif mode == 'duplicate_url':
                    options['urls'] = [self.url, self.url]
                elif mode == 'ambiguous':
                    other = self.record(self.root / 'other-empty', state='response_saved', raw='')
                    options['record_paths'] = [other['_ledger_path']]
                result = self.stable_check(snapshot, entry, saved, **options)
                self.assertEqual(result['health'], 'saved_response_protected')
                self.assertFalse(result['replace_allowed'])
                self.assertFalse(result['collect_allowed'])

    def test_empty_saved_artifact_still_protects_unknown_login_streaming_and_local_pages(self):
        snapshot, entry, saved = self.saved(self.root / 'empty-protected', raw='')
        snapshot['answer_texts'] = []
        for fields in ({'login': True}, {'verification': True}, {'streaming': True},
                       {'url': 'https://chatgpt.com/c/local-chatgpt-pending'}):
            with self.subTest(fields=fields):
                self.assertFalse(self.stable_check({**snapshot, **fields}, entry, saved)['replace_allowed'])
        latest = self.record(self.root / 'new-unknown-empty', state='needs_inspection',
                             prompt='新未知材料 card-review-' + 'b' * 24)
        result = self.stable_check(snapshot, entry, latest, record_paths=[saved['_ledger_path']])
        self.assertFalse(result['replace_allowed'])

    def test_visible_stopped_thinking_is_terminal_error_evidence_without_assistant_answer(self):
        snapshot = {**self.snapshot, 'terminal_complete': False, 'terminal_stopped': True,
                    'errors': ['Stopped thinking']}
        result = self.stable_check(snapshot)
        self.assertEqual(result['health'], 'terminal_no_response')
        self.assertTrue(result['replace_allowed'])

    def test_busy_receipt_with_explicit_stopped_status_uses_bounded_empty_terminal_path(self):
        snapshot={**self.snapshot,'terminal_complete':False,'terminal_stopped':True,'uploading':False}
        result=self.check(snapshot,entry={'state':'busy'})
        self.assertEqual(result['health'],'terminal_empty')
        self.assertFalse(result['replace_allowed']);self.assertFalse(result['requeue_allowed'])
        for fields in ({'streaming':True},{'uploading':True},{'draft':'new draft'},
                       {'login':True},{'verification':True},{'quota':True}, {'terminal_stopped':False}):
            with self.subTest(fields=fields):
                protected=self.check({**snapshot,**fields},entry={'state':'busy'})
                self.assertNotEqual(protected['health'],'terminal_empty')
                self.assertFalse(protected['replace_allowed'])

    def test_empty_reply_with_hard_generation_error_can_be_archived_after_stability(self):
        snapshot = {**self.snapshot, 'terminal_complete': False, 'errors': ['Something went wrong']}
        self.assertEqual(self.check(snapshot)['health'], 'waiting_stable')
        self.assertTrue(self.stable_check(snapshot)['replace_allowed'])

    def test_too_short_or_changed_observation_is_not_stable(self):
        first = self.check()
        snapshot = {**self.snapshot, 'checked_at': 109.0}
        self.assertFalse(self.check(snapshot, previous=first)['replace_allowed'])
        snapshot = {**self.snapshot, 'checked_at': 160.0, 'errors': ['Something went wrong']}
        self.assertFalse(self.check(snapshot, previous=first)['replace_allowed'])

    def test_duplicate_url_or_changed_target_blocks_terminal_replacement(self):
        self.assertEqual(self.stable_check(urls=[self.url, self.url])['health'], 'unknown')
        snapshot = {**self.snapshot, 'target_id': 'another-target'}
        self.assertEqual(self.stable_check(snapshot)['health'], 'unknown')

    def test_prompt_hash_or_unique_material_mismatch_blocks_terminal_replacement(self):
        wrong_hash = {**self.attempt, 'actual_prompt_sha256': '0' * 64}
        self.assertEqual(self.stable_check(attempt=wrong_hash)['health'], 'unknown')
        wrong_user = {**self.snapshot, 'user_texts': [self.prompt.replace('input123', 'input456')]}
        self.assertEqual(self.stable_check(wrong_user)['health'], 'unknown')
        duplicate_user = {**self.snapshot, 'user_texts': [self.prompt, self.prompt]}
        self.assertEqual(self.stable_check(duplicate_user)['health'], 'unknown')

    def test_complete_unsaved_response_is_collected_verbatim_and_never_marked_unsent(self):
        raw = '{ malformed JSON is still the complete original response α'
        snapshot = {**self.snapshot, 'answer_texts': [raw]}
        self.assertEqual(self.check(snapshot)['health'], 'waiting_stable')
        result = self.stable_check(snapshot)
        self.assertEqual(result['health'], 'completed_unsaved')
        self.assertTrue(result['collect_allowed'])
        self.assertFalse(result['replace_allowed'])
        self.assertFalse(result['requeue_allowed'])
        self.assertEqual(result['evidence']['raw'], raw)
        self.assertEqual(result['evidence']['raw_sha256'], sha(raw))
        self.assertEqual(self.attempt['state'], 'submitted')

    def test_partial_unsaved_answer_is_preserved_without_collection_or_replacement(self):
        snapshot = {**self.snapshot, 'answer_texts': ['partial'], 'terminal_complete': False}
        result = self.stable_check(snapshot)
        self.assertEqual(result['health'], 'unknown')
        self.assertFalse(result['collect_allowed'])
        self.assertFalse(result['replace_allowed'])

    def test_saved_complete_reply_checks_original_hash_url_and_prompt(self):
        snapshot, entry, record = self.saved()
        result = self.check(snapshot, entry, record)
        self.assertEqual(result['health'], 'completed_saved')
        self.assertEqual(result['matched_record_path'], record['_ledger_path'])
        self.assertFalse(result['replace_allowed'])
        self.assertEqual(result['evidence']['receipt']['actual_prompt_sha256'], sha(self.prompt))

    def test_saved_site_block_waits_for_stable_proof_then_archives_before_replacement(self):
        from browser.shared_page_health import SITE_BLOCK_ERROR
        snapshot,entry,record=self.saved()
        snapshot.update(site_blocked=True,errors=[SITE_BLOCK_ERROR])
        raw=Path(record['_ledger_path']).parent/'response-raw.txt';original=raw.read_bytes()
        first=self.check(snapshot,entry,record)
        self.assertEqual(first['health'],'waiting_stable');self.assertFalse(first['replace_allowed'])
        health=self.stable_check(snapshot,entry,record)
        self.assertEqual(health['health'],'completed_saved');self.assertTrue(health['replace_allowed'])
        self.assertEqual(health['matched_record_path'],record['_ledger_path'])
        self.assertFalse(health['requeue_allowed']);self.assertEqual(raw.read_bytes(),original)

    def test_saved_site_block_never_overrides_current_activity_or_user_protection(self):
        from browser.shared_page_health import SITE_BLOCK_ERROR
        snapshot,entry,record=self.saved()
        snapshot.update(site_blocked=True,errors=[SITE_BLOCK_ERROR])
        for change in ({'streaming':True},{'uploading':True},{'draft':'user draft'},
                       {'attachments':1},{'login':True},{'verification':True},{'quota':True}):
            with self.subTest(change=change):
                health=self.stable_check({**snapshot,**change},entry,record)
                self.assertFalse(health['replace_allowed']);self.assertFalse(health['requeue_allowed'])
        newer=self.record(self.root/'unknown-site-block',state='needs_inspection',prompt='different prompt')
        health=self.stable_check(snapshot,entry,newer,record_paths=[record['_ledger_path']])
        self.assertFalse(health['replace_allowed']);self.assertFalse(health['requeue_allowed'])

    def test_latest_unsent_review_cannot_relabel_previous_saved_card_response(self):
        snapshot, entry, original = self.saved()
        review_prompt = '核对合成材料 card-review-' + 'b' * 24
        latest = self.record(self.root / 'new-review', state='not_sent', prompt=review_prompt)
        latest['send_click_started'] = False
        result = self.check(snapshot, entry, latest)
        self.assertEqual(result['health'], 'completed_saved')
        self.assertEqual(result['matched_record_path'], original['_ledger_path'])
        self.assertEqual(result['evidence']['receipt']['actual_prompt_sha256'], sha(self.prompt))

    def test_latest_unknown_review_cannot_release_page_using_previous_saved_card(self):
        snapshot, entry, original = self.saved()
        latest = self.record(self.root / 'new-unknown-review', state='needs_inspection',
                             prompt='核对合成材料 card-review-' + 'b' * 24)
        result = self.check(snapshot, entry, latest)
        self.assertEqual(result['health'], 'unknown')
        self.assertFalse(result['replace_allowed'])
        self.assertIsNone(result['matched_record_path'])

    def test_old_error_in_sent_ledger_cannot_replace_current_visible_terminal_evidence(self):
        snapshot = {**self.snapshot, 'terminal_complete': False, 'user_turn_complete': True}
        attempt = {**self.attempt, 'error': 'Something went wrong'}
        result = self.stable_check(snapshot, attempt=attempt)
        self.assertEqual(result['health'], 'unknown')
        self.assertFalse(result['replace_allowed'])

    def test_unique_renamed_history_file_repairs_pointer_by_content_and_original_receipt(self):
        snapshot, entry, record = self.saved()
        before = copy.deepcopy(entry)
        old_folder = Path(record['_ledger_path']).parent
        archived = self.root / 'history' / 'version-x'
        archived.parent.mkdir()
        old_folder.rename(archived)
        (archived / 'response-raw.txt').rename(archived / 'arbitrary-name.payload')
        result = self.check(snapshot, entry, self.attempt, history_roots=[self.root / 'history'])
        self.assertEqual(result['health'], 'raw_path_repair')
        self.assertEqual(result['repair_raw_path'], str((archived / 'arbitrary-name.payload').resolve()))
        self.assertEqual(result['matched_record_path'], str((archived / 'attempt.json').resolve()))
        self.assertFalse(result['replace_allowed'])
        self.assertEqual(entry, before)

    def test_same_raw_copies_in_history_are_ambiguous_and_never_guessed_by_name(self):
        snapshot, entry, record = self.saved()
        old_folder = Path(record['_ledger_path']).parent
        archived = self.root / 'history' / 'version-x'
        archived.parent.mkdir()
        old_folder.rename(archived)
        raw = (archived / 'response-raw.txt').read_text()
        (archived / 'extra-copy.txt').write_text(raw)
        result = self.check(snapshot, entry, self.attempt, history_roots=[self.root / 'history'])
        self.assertEqual(result['health'], 'saved_response_protected')
        self.assertFalse(result['replace_allowed'])
        self.assertNotIn('repair_raw_path', result)

    def test_matching_file_without_original_ledger_and_prompt_cannot_repair_pointer(self):
        snapshot, entry, record = self.saved()
        source = Path(entry['raw_path'])
        archive = self.root / 'history'
        archive.mkdir()
        source.rename(archive / 'response-raw.txt')
        (Path(record['_ledger_path']).parent / 'attempt.json').unlink()
        result = self.check(snapshot, entry, self.attempt, history_roots=[archive])
        self.assertEqual(result['health'], 'saved_response_protected')
        self.assertFalse(result['replace_allowed'])

    def test_existing_corrupted_raw_is_not_silently_replaced_by_good_backup(self):
        snapshot, entry, record = self.saved()
        self.record(self.root / 'history' / 'good', state='response_saved', raw=snapshot['answer_texts'][0])
        Path(entry['raw_path']).write_text('changed original')
        result = self.check(snapshot, {**entry, 'state': 'needs_inspection'}, record,
                            history_roots=[self.root / 'history'])
        self.assertEqual(result['health'], 'saved_response_protected')
        self.assertFalse(result['replace_allowed'])

    def test_history_record_with_wrong_url_or_prompt_never_repairs_pointer(self):
        snapshot, entry, record = self.saved()
        Path(entry['raw_path']).unlink()
        self.record(self.root / 'history' / 'wrong', state='response_saved', raw=snapshot['answer_texts'][0],
                    url='https://chatgpt.com/c/different')
        result = self.check(snapshot, entry, self.attempt, history_roots=[self.root / 'history'])
        self.assertEqual(result['health'], 'saved_response_protected')
        self.assertFalse(result['replace_allowed'])

    def test_explicit_not_sent_ssl_or_upload_failure_requires_stable_empty_page(self):
        for error in ('net::ERR_SSL_PROTOCOL_ERROR', '附件上传失败'):
            with self.subTest(error=error):
                attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False, 'error': error}
                snapshot = {**self.snapshot, 'url': 'chrome-error://chromewebdata/',
                            'user_texts': [], 'terminal_complete': False, 'errors': [error]}
                first = self.check(snapshot, attempt=attempt)
                self.assertFalse(first['replace_allowed'])
                result = self.stable_check(snapshot, attempt=attempt)
                self.assertEqual(result['health'], 'not_sent_error')
                self.assertTrue(result['replace_allowed'])
                self.assertFalse(result['requeue_allowed'])

    def test_later_unsent_attempt_cannot_release_blank_page_with_unknown_sent_history(self):
        prior = self.record(self.root / 'older-sent', state='needs_inspection')
        latest = self.record(self.root / 'new-unsent', state='not_sent')
        latest.update(send_click_started=False, error='net::ERR_SSL_PROTOCOL_ERROR')
        snapshot = {**self.snapshot, 'url': 'chrome-error://chromewebdata/',
                    'user_texts': [], 'terminal_complete': False, 'errors': ['net::ERR_SSL_PROTOCOL_ERROR']}
        for entry_state in ('needs_inspection', 'ready_blank'):
            with self.subTest(entry_state=entry_state):
                result = self.stable_check(snapshot, entry={'state': entry_state}, attempt=latest,
                                           record_paths=[prior['_ledger_path']])
                self.assertEqual(result['health'], 'unknown')
                self.assertFalse(result['replace_allowed'])
                self.assertIn(prior['_ledger_path'], result['evidence']['uncollected_history'])

    def test_old_sent_history_needs_matching_saved_input_prompt_url_and_file(self):
        prior = self.record(self.root / 'older-sent', state='submitted')
        prior['inputs'] = {'source.pdf': 'original-source-hash'}
        Path(prior['_ledger_path']).write_text(json.dumps(prior))
        saved = self.record(self.root / 'older-saved', state='response_saved', raw='旧请求完整回答')
        saved['inputs'] = dict(prior['inputs'])
        Path(saved['_ledger_path']).write_text(json.dumps(saved))
        latest = self.record(self.root / 'new-unsent', state='not_sent')
        latest.update(send_click_started=False, error='附件上传失败')
        snapshot = {**self.snapshot, 'url': 'chrome-error://chromewebdata/',
                    'user_texts': [], 'terminal_complete': False, 'errors': ['附件上传失败']}
        paths = [prior['_ledger_path'], saved['_ledger_path']]
        result = self.stable_check(snapshot, attempt=latest, record_paths=paths)
        self.assertEqual(result['health'], 'saved_response_protected')
        self.assertFalse(result['replace_allowed'])
        for changes in ({'inputs': {'source.pdf': 'other-input'}},
                        {'conversation_url': 'https://chatgpt.com/c/other'},
                        {'actual_prompt_sha256': '0' * 64}, {'raw_sha256': '0' * 64}):
            with self.subTest(changes=changes):
                changed = {**saved, **changes}
                Path(saved['_ledger_path']).write_text(json.dumps(changed))
                result = self.stable_check(snapshot, attempt=latest, record_paths=paths)
                self.assertEqual(result['health'], 'unknown')
                self.assertFalse(result['replace_allowed'])

    def test_other_target_unknown_history_does_not_block_this_known_unsent_page(self):
        prior = self.record(self.root / 'other-target', state='submission_started')
        prior['target_id'] = 'other-target'
        Path(prior['_ledger_path']).write_text(json.dumps(prior))
        latest = {**self.attempt, 'state': 'not_sent', 'send_click_started': False,
                  'error': 'net::ERR_SSL_PROTOCOL_ERROR'}
        snapshot = {**self.snapshot, 'url': 'chrome-error://chromewebdata/',
                    'user_texts': [], 'terminal_complete': False, 'errors': ['net::ERR_SSL_PROTOCOL_ERROR']}
        result = self.stable_check(snapshot, attempt=latest, record_paths=[prior['_ledger_path']])
        self.assertTrue(result['replace_allowed'])

    def test_uncertain_click_flag_draft_attachment_or_stop_prevents_unsent_replacement(self):
        attempt = {**self.attempt, 'state': 'not_sent', 'send_click_started': False, 'error': '附件上传失败'}
        clean = {**self.snapshot, 'url': 'https://chatgpt.com/', 'user_texts': [], 'terminal_complete': False}
        cases = [(clean, {**attempt, 'send_click_started': True}),
                 ({**clean, 'draft': '用户新草稿'}, attempt),
                 ({**clean, 'attachments': 1}, attempt),
                 ({**clean, 'streaming': True}, attempt)]
        for snapshot, record in cases:
            with self.subTest(snapshot=snapshot, record=record):
                self.assertFalse(self.stable_check(snapshot, attempt=record)['replace_allowed'])

    def test_unowned_incomplete_and_unreadable_states_never_recommend_replacement(self):
        self.assertFalse(self.check(entry={'owned': False})['replace_allowed'])
        self.assertFalse(self.check({**self.snapshot, 'inspection_complete': False})['replace_allowed'])
        self.assertFalse(self.check({**self.snapshot, 'user_texts': None})['replace_allowed'])

    def test_snapshot_reader_only_evaluates_owned_page_and_keeps_user_completion_separate(self):
        page = Mock(spec=['evaluate', 'url'])
        page.url = self.url
        page.evaluate.return_value = {**self.snapshot, 'terminal_complete': False,
                                      'user_turn_complete': True, 'answer_variants': []}
        result = snapshot_page('original-target', page)
        self.assertTrue(result['inspection_complete'])
        self.assertFalse(result['terminal_complete'])
        self.assertTrue(result['user_turn_complete'])
        page.evaluate.assert_called_once()
        self.assertNotIn('answer_variants', result)

    def test_snapshot_prefers_same_json_variant_as_raw_collector(self):
        page = Mock(spec=['evaluate', 'url'])
        page.url = self.url
        page.evaluate.return_value = {**self.snapshot, 'answer_variants': [['{"a":1}', 'rendered 1 {"a":1}']]}
        result = snapshot_page('original-target', page)
        self.assertEqual(result['answer_texts'], ['{"a":1}'])

    def test_snapshot_read_failure_returns_preserve_evidence(self):
        page = Mock(spec=['evaluate', 'url'])
        page.url = self.url
        page.evaluate.side_effect = RuntimeError('CDP disconnected')
        snapshot = snapshot_page('original-target', page)
        self.assertFalse(snapshot['inspection_complete'])
        self.assertFalse(self.check(snapshot)['replace_allowed'])


if __name__ == '__main__':
    unittest.main()
