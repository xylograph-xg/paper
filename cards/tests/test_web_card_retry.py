import os
import copy
import json
from core.api import paths__WorkspacePath as Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import pymupdf
from core.catalog import Catalog
from cards import web_card_queue as queue
from cards.web_card_inputs import prepare, digest
from cards.web_card_json import normalize
from cards.web_card_retry import run_once, known_unsent

import tempfile
from core.api import paths__WorkspacePath as Path
from browser import upload_trace

UPLOAD_OK = {'ok': True, 'receipt_sufficient': True, 'failure_kind': None,
             'retryable_upload': False, 'stage': 'full_page_recheck', 'stages': [],
             'bundle': {}, 'settle': {}, 'attachment': {}}
UPLOAD_FAIL = {'ok': False, 'receipt_sufficient': False, 'failure_kind': 'write_failed',
               'retryable_upload': True, 'stage': 'attachment_write', 'stages': [],
               'bundle': {}, 'settle': {}, 'attachment': {}}

def _trace_temp(test):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    test.addCleanup(upload_trace.reset)
    upload_trace.configure(Path(folder.name))

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.catalog = Catalog(self.root/'catalog.sqlite3');queue.install(self.catalog)
        bundle_environment=patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')})
        bundle_environment.start();self.addCleanup(bundle_environment.stop)
        self.source = self.root/'source.pdf'
        with pymupdf.open() as doc:
            doc.new_page().insert_text((20, 40), 'Synthetic source observations under stated conditions.');doc.save(self.source)
        self.pid = self.catalog.upsert({'title': 'Synthetic source'})
        self.catalog.update(self.pid, acquisition='available', asset_path=str(self.source), asset_hash=digest(self.source))
        self.folder = self.root/'web_cards'/self.pid
        self.packet = prepare(self.source, self.folder, self.pid, 'Synthetic source', digest(self.source))
        with self.catalog.connect() as db:
            db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,?,?,?)", (self.pid, digest(self.source), 'Synthetic source', '{}', 'failed', 'initial'))
        self.config = {'catalog_path': str(self.catalog.path), 'studio_library_root': str(self.root/'library'),
            'web_cards': {'enabled': True, 'pdf_python': sys.executable,
                'retry': {'enabled': True, 'max_retries': 2, 'backoff_seconds': 300}}}
        self.router = Mock();self.router.choose.return_value = 'chatgpt'
        self.card = {'title': 'Synthetic source', 'info': {k:'原文未提供，无法确认' for k in ('标题','作者','期刊','年份','DOI','研究对象','主要方法','关键词')}, 'one_line_summary': r'$\Omega_{CT}$ differs from $\omega$',
            'key_findings': 'k', 'intro_summary': 'i', 'conclusion_summary': 'c', 'warnings': [],
            'figures': [], 'equations': [], 'tables': [],
            'paper_evaluation': {k: {'score': None, 'reason': '信息不足', 'source_pages': []} for k in ('overall_quality', 'direction_novelty')}}
        from cards.paper_quality import dimension_schema
        dimensions=dimension_schema()
        for item in dimensions.values():item['reason']='信息不足'
        self.card['paper_evaluation']['overall_quality']['dimensions']=dimensions

    def test_explicit_single_json_wrapper_keeps_scientific_values_and_delivery_guard(self):
        from cards.web_card_inputs import parse_card,MaterialDeliveryError
        body=json.dumps(self.card,ensure_ascii=False)
        for prefix,suffix in [('下面是完整结果。\nJSON\n',''),('说明\n```json\n','\n```')]:
            wrapped=prefix+body+suffix
            self.assertEqual(parse_card(wrapped,self.packet),parse_card(body,self.packet))
            self.assertEqual(normalize(wrapped),wrapped)
        with self.assertRaises(MaterialDeliveryError):
            parse_card('附件不可读。\nJSON\n'+body,self.packet)
        for wrapped in ['说明\n'+body,'JSON\n'+body+'\n'+body,'JSON\n'+body+'尾部说明','JSON\n'+body[:-1]]:
            with self.assertRaises(ValueError):parse_card(wrapped,self.packet)
        malformed='说明\nJSON\n'+body[:-1]+',}'
        fixed=normalize(malformed)
        self.assertTrue(fixed.startswith('说明\nJSON\n'))
        self.assertEqual(parse_card(fixed,self.packet),parse_card(body,self.packet))

    def test_loaded_parser_revision_rechecks_old_local_failure_without_external_retry(self):
        self.config['web_cards']['retry']['max_retries']=0
        self.attempt('response_saved','说明\nJSON\n'+json.dumps(self.card))
        raw=(self.folder/'chatgpt/response-raw.txt').read_bytes()
        with patch('cards.web_card_retry.parse_card',side_effect=ValueError('old wrapper parser')) as old:
            old.parser_revision='legacy'
            self.assertEqual(self.tick()['published'],[])
        report=self.tick()
        self.assertEqual(report['published'],[self.pid]);self.assertEqual(self.state(),'completed')
        self.assertEqual((self.folder/'chatgpt/response-raw.txt').read_bytes(),raw)
        self.assertEqual(json.loads((self.folder/'retry.json').read_text())['external_retries'],0)

    def attempt(self, state, raw=None, **extra):
        folder = self.folder/'chatgpt';folder.mkdir(exist_ok=True)
        a = {'provider': 'chatgpt', 'state': state, 'target_id': 'original', 'inputs': self.packet['input_hashes'],
            'settings': {'model': 'synthetic'}, 'created': 1, **extra}
        if raw is not None:
            (folder/'response-raw.txt').write_text(raw)
            (folder/'prompt-actual.txt').write_text((self.folder/'prompt.txt').read_text())
            a.update(raw_sha256=digest(folder/'response-raw.txt'), actual_prompt_sha256=digest(folder/'prompt-actual.txt'),
                conversation_url='https://chatgpt.com/c/synthetic')
        (folder/'attempt.json').write_text(json.dumps(a))
        return a

    def tick(self, **extra):return run_once(self.config, router=self.router, clock=lambda:1000, **extra)
    def state(self):return queue.jobs(self.catalog)[0]['state']

    def test_saved_retry_keeps_pool_receipt_readable_before_next_dispatch(self):
        self.card.pop('key_findings')
        attempt=self.attempt('response_saved',raw=json.dumps(self.card))
        old=self.folder/'chatgpt/response-raw.txt';raw=old.read_bytes()
        entry={'state':'ready','raw_path':str(old),'raw_sha256':attempt['raw_sha256'],
               'conversation_url':attempt['conversation_url'],'active_paper_id':self.pid}
        entries={'original':entry}
        report=self.tick(entries=entries)
        self.assertEqual(report['requeued'],[self.pid])
        self.assertFalse(old.exists())
        self.assertEqual(Path(entry['raw_path']).read_bytes(),raw)
        self.assertEqual(entry['state'],'ready')
        self.assertEqual(entry['active_paper_id'],self.pid)
        self.assertEqual(len(report['relocated_saved_paths']),1)
        self.assertEqual(json.loads((self.folder/'retry.json').read_text())['external_retries'],1)

    def test_archive_path_relocation_requires_exact_bound_receipt(self):
        from cards.web_card_retry import relocate_saved_pool_paths
        attempt=self.attempt('response_saved',raw=json.dumps(self.card))
        ledger=self.folder/'chatgpt/attempt.json';history=self.folder/'history/test';history.mkdir(parents=True)
        old=ledger.parent/'response-raw.txt';ledger.parent.rename(history/'chatgpt')
        original={'state':'busy','raw_path':str(old),'raw_sha256':attempt['raw_sha256'],
                  'conversation_url':attempt['conversation_url']}
        for field,value in [('raw_sha256','changed'),('conversation_url','https://chatgpt.com/c/other'),
                            ('raw_path',str(self.root/'other.txt'))]:
            entry={**original,field:value};before=copy.deepcopy(entry)
            self.assertEqual(relocate_saved_pool_paths({'original':entry},[(ledger,attempt)],history),[])
            self.assertEqual(entry,before)
        entry={'state':'busy','active_paper_id':'next','previous_saved_response':dict(original)}
        relocate_saved_pool_paths({'original':entry},[(ledger,attempt)],history)
        self.assertEqual(entry['state'],'busy');self.assertEqual(entry['active_paper_id'],'next')
        self.assertTrue(Path(entry['previous_saved_response']['raw_path']).is_file())

    def test_exhausted_retry_releases_verified_unsent_lease_without_requeue(self):
        from contextlib import nullcontext
        from browser.shared_page_backlog import install, binding
        install(self.catalog)
        self.config['web_cards']['shared_window']={'enabled':True,'backlog':{'enabled':True}}
        with self.catalog.connect() as db:
            db.execute("INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES('cards',?,?,?,1,'claimed')",(self.pid,self.pid,'original'))
        self.attempt('not_sent',send_click_started=False,error='附件上传失败')
        (self.folder/'retry.json').write_text(json.dumps({'external_retries':2}))
        page=Mock();page.url='https://chatgpt.com/'
        empty=Mock();empty.count.return_value=0;page.locator.return_value=empty
        entries={'original':{'state':'needs_inspection','active_paper_id':self.pid,'slot':3,'raw_sha256':'old'}}
        with patch('browser.web_card_transport.require_no_verification'),patch('web_gpt.submission.submission_lock',return_value=nullcontext()):
            report=self.tick(pages={'original':page},entries=entries)
        self.assertEqual(report['requeued'],[]);self.assertEqual(self.state(),'failed')
        self.assertIsNone(binding(self.catalog,'cards',self.pid))
        self.assertEqual(entries['original']['slot'],3)
        self.assertEqual(entries['original']['state'],'ready_blank')
        self.assertNotIn('raw_sha256',entries['original'])
        self.assertTrue((self.folder/'chatgpt'/'page-lease-release.json').exists())

    def test_delivery_failure_preserves_reply_and_never_retries_same_inputs(self):
        self.card['warnings']=['未收到可读取的 source.pdf 与 visual.pdf 附件。']
        a=self.attempt('response_saved',raw=json.dumps(self.card))
        report=self.tick()
        self.assertEqual(report['requeued'],[]);self.assertEqual(report['published'],[])
        self.assertEqual(self.state(),'needs_inspection')
        self.assertEqual(json.loads((self.folder/'chatgpt/attempt.json').read_text()),a)
        self.assertEqual(json.loads((self.folder/'retry.json').read_text())['external_retries'],0)
        self.assertFalse((self.root/'library'/self.pid/'card.json').exists())

    def test_repeated_delivery_check_does_not_refresh_job_update_time(self):
        self.card['warnings']=['未收到可读取的source.pdf附件。']
        self.attempt('response_saved',raw=json.dumps(self.card))
        self.tick();before=queue.jobs(self.catalog)[0]['updated']
        self.tick();self.assertEqual(queue.jobs(self.catalog)[0]['updated'],before)

    def delivery_authorization(self):
        self.card['warnings']=['未收到可读取的source.pdf附件。']
        self.attempt('response_saved',raw=json.dumps(self.card))
        queue.update(self.catalog,self.pid,state='needs_inspection',error='材料投递失败')
        (self.folder/'retry.json').write_text(json.dumps({'external_retries':2,'state':'delivery_failed',
            'input_hashes':self.packet['input_hashes']}))
        root=self.root/'audit_index';root.mkdir()
        path=root/'delivery-authorization.json'
        path.write_text(json.dumps({'kind':'human_one_extra_delivery_retry','authorization_id':'synthetic',
            'max_extra_per_paper':1,'requests':[{'paper_id':self.pid,'old_inputs':self.packet['input_hashes'],
                'old_response_sha256':digest(self.folder/'chatgpt/response-raw.txt'),
                'candidate_bundle':self.packet['upload_bundle']}]}))
        return path

    def test_one_extra_delivery_repair_preserves_old_count_and_archived_gate(self):
        from cards.web_card_delivery_repair import schedule
        from browser.attempt_history import submission_history
        manifest=self.delivery_authorization();old=(self.folder/'chatgpt/attempt.json').read_bytes()
        result=schedule(self.config,manifest)
        self.assertEqual(result[0]['state'],'queued')
        ledger=json.loads((self.folder/'retry.json').read_text())
        self.assertEqual(ledger['external_retries'],2);self.assertEqual(ledger['delivery_repair']['used'],1)
        history=Path(ledger['delivery_repair']['history'])
        self.assertEqual((history/'chatgpt/attempt.json').read_bytes(),old)
        self.assertTrue(submission_history(self.folder).allowed)
        with self.assertRaises(ValueError):schedule(self.config,manifest)
        manifest.write_text('{}')
        self.assertFalse(submission_history(self.folder).allowed)

    def test_extra_delivery_authorization_does_not_override_pause_or_changed_reply(self):
        from cards.web_card_delivery_repair import schedule
        manifest=self.delivery_authorization()
        (self.root/'web-card-control.json').write_text('{"paused_by_user":true}')
        with self.assertRaisesRegex(ValueError,'暂停'):schedule(self.config,manifest)
        (self.root/'web-card-control.json').unlink()
        (self.folder/'chatgpt/response-raw.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'指纹'):schedule(self.config,manifest)
        self.assertEqual(self.state(),'needs_inspection')
        self.assertNotIn('delivery_repair',json.loads((self.folder/'retry.json').read_text()))

    def test_negated_delivery_warning_uses_structure_validation(self):
        self.card['warnings']=['未发现附件缺失；ZIP内包含source.pdf和visual.pdf。']
        self.attempt('response_saved',raw=json.dumps(self.card))
        report=self.tick()
        self.assertEqual(report['published'],[self.pid]);self.assertEqual(self.state(),'completed')

    def root_seed(self, source_hash=None):
        from review.card_review_queue import install
        install(self.catalog)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO manual_seed_roots(paper_id,source_path,input_hash,registered) VALUES(?,?,?,1)',
                       (self.pid, str(self.source), source_hash or digest(self.source)))

    def test_manual_root_pre_click_retry_keeps_external_count_and_exact_receipt(self):
        self.root_seed()
        a=self.attempt('not_sent',send_click_started=False,error='附件上传失败')
        original=(self.folder/'chatgpt/attempt.json').read_bytes()
        (self.folder/'retry.json').write_text(json.dumps({'external_retries':2,'technical_retries':15}))
        report=self.tick(pages={})
        self.assertEqual(report['requeued'],[self.pid]);self.assertEqual(self.state(),'queued')
        ledger=json.loads((self.folder/'retry.json').read_text())
        self.assertEqual(ledger['external_retries'],2);self.assertEqual(ledger['technical_retries'],16)
        self.assertEqual(ledger['retry_at'],4600)
        self.assertEqual((Path(ledger['history'])/'chatgpt/attempt.json').read_bytes(),original)
        self.assertEqual(json.loads(original),a)
        from browser.attempt_history import submission_history
        self.assertTrue(submission_history(self.folder).allowed)

    def test_manual_root_technical_backoff_progresses_then_stays_bounded(self):
        self.root_seed()
        for count,wait in [(0,300),(1,900),(2,3600),(1000,3600)]:
            queue.update(self.catalog,self.pid,state='failed',error='附件上传失败')
            self.attempt('not_sent',send_click_started=False,error='附件上传失败')
            (self.folder/'retry.json').write_text(json.dumps({'external_retries':2,'technical_retries':count}))
            self.assertEqual(self.tick(pages={})['requeued'],[self.pid])
            ledger=json.loads((self.folder/'retry.json').read_text())
            self.assertEqual(ledger['retry_at'],1000+wait)
            self.assertEqual(ledger['external_retries'],2)

    def test_seed_marker_or_mismatched_root_cannot_bypass_retry_cap(self):
        with self.catalog.connect() as db:
            db.execute('UPDATE papers SET metadata=? WHERE id=?',
                       (json.dumps({'manual_seed_fast_lane':True}),self.pid))
        self.attempt('not_sent',send_click_started=False,error='附件上传失败')
        (self.folder/'retry.json').write_text('{"external_retries":2}')
        self.assertEqual(self.tick()['requeued'],[])
        self.root_seed('changed')
        self.assertEqual(self.tick()['requeued'],[])
        self.assertEqual(json.loads((self.folder/'retry.json').read_text()),{'external_retries':2})

    def test_manual_root_saved_structure_failure_still_has_original_cap(self):
        self.root_seed();self.card.pop('key_findings')
        self.attempt('response_saved',raw=json.dumps(self.card))
        (self.folder/'retry.json').write_text('{"external_retries":2}')
        report=self.tick()
        self.assertEqual(report['requeued'],[])
        self.assertIn('次数已用完',str(report['blocked']))
        self.assertNotIn('technical_retries',json.loads((self.folder/'retry.json').read_text()))

    def test_manual_root_unknown_or_historical_unsent_inference_never_gets_extra_retry(self):
        self.root_seed()
        for state,click in [('submitted',True),('needs_inspection',True),('not_sent',None)]:
            with self.subTest(state=state,click=click):
                self.attempt(state,send_click_started=click,error='附件上传失败')
                (self.folder/'retry.json').write_text('{"external_retries":2}')
                self.assertEqual(self.tick()['requeued'],[])
                self.assertTrue((self.folder/'chatgpt/attempt.json').exists())
                self.assertNotIn('technical_retries',json.loads((self.folder/'retry.json').read_text()))

    def test_safe_pre_click_failure_is_delayed_and_history_is_preserved(self):
        a = self.attempt('not_sent', error='附件上传失败', tab_cleanup='closed_error_page')
        report = self.tick()
        self.assertEqual(report['requeued'], [self.pid]);self.assertEqual(self.state(), 'queued')
        ledger = json.loads((self.folder/'retry.json').read_text())
        self.assertEqual(ledger['retry_at'], 1300);self.assertEqual(ledger['external_retries'], 1)
        self.assertEqual(json.loads((Path(ledger['history'])/'chatgpt/attempt.json').read_text()), a)
        self.assertFalse((self.folder/'chatgpt/attempt.json').exists())
        with patch('cards.web_card_queue.time.time', return_value=1000):self.assertIsNone(queue.claim(self.catalog))
        with patch('cards.web_card_queue.time.time', return_value=1301):self.assertEqual(queue.claim(self.catalog)['paper_id'], self.pid)

    def test_absent_page_or_empty_composer_never_proves_unknown_request_unsent(self):
        for state in ('needs_inspection', 'submission_started', 'submitted', 'preflight'):
            self.attempt(state, error='没有回执，页面空白')
            report = self.tick(pages={}, entries={})
            self.assertEqual(report['requeued'], []);self.assertEqual(self.state(), 'failed')
            self.assertTrue((self.folder/'chatgpt/attempt.json').exists())

    def test_old_not_sent_label_after_click_is_rejected(self):
        self.assertFalse(known_unsent({'state':'deferred'}))
        self.assertFalse(known_unsent({'state':'deferred','send_click_started':True}))
        self.assertFalse(known_unsent({'state': 'not_sent', 'send_click_started': True, 'error': '附件上传失败'}))
        self.assertFalse(known_unsent({'state': 'not_sent', 'error': '输入框清空但未出现唯一用户消息'}))

    def test_unknown_archive_blocks_retry_of_newer_pre_click_failure(self):
        old=self.folder/'history'/'old'/'chatgpt'/'attempt.json';old.parent.mkdir(parents=True)
        old.write_text(json.dumps({'state':'submitted','target_id':'lost','send_click_started':True}))
        self.attempt('not_sent',send_click_started=False,tab_cleanup='closed_error_page')
        report=self.tick()
        self.assertEqual(report['requeued'],[]);self.assertEqual(self.state(),'failed')
        self.assertTrue((self.folder/'chatgpt'/'attempt.json').exists())
        self.assertFalse((self.folder/'retry.json').exists())
        self.router.choose.assert_not_called()

    def test_local_separator_repair_publishes_without_repeating_browser_request(self):
        raw = json.dumps(self.card, ensure_ascii=False).replace('"title": "Synthetic source",', '"title": "Synthetic source"', 1)
        original = self.attempt('response_saved', raw)
        report = self.tick()
        self.assertEqual(report['published'], [self.pid]);self.assertEqual(self.state(), 'completed')
        card = json.loads((self.root/'library'/self.pid/'card.json').read_text())
        self.assertEqual(card['one_line_summary'], self.card['one_line_summary'])
        self.assertFalse(card['meta']['scientific_verified']);self.assertFalse(card['meta']['production_contract_complete'])
        self.assertEqual(digest(self.folder/'chatgpt/response-raw.txt'), original['raw_sha256'])
        self.router.choose.assert_not_called()

    def test_missing_scientific_fields_are_not_invented_and_finished_reply_is_archived(self):
        self.attempt('response_saved', '{"title":"incomplete"}')
        report = self.tick()
        self.assertEqual(report['requeued'], [self.pid]);self.assertFalse((self.root/'library'/self.pid/'card.json').exists())
        ledger = json.loads((self.folder/'retry.json').read_text())
        self.assertEqual((Path(ledger['history'])/'chatgpt/response-raw.txt').read_text(), '{"title":"incomplete"}')
        self.assertIn('缺少 one_line_summary',ledger['failure_detail'])
        self.assertIn('缺少 one_line_summary',queue.jobs(self.catalog)[0]['error'])

    def test_pause_changed_inputs_and_human_cards_block_retry(self):
        self.attempt('not_sent', send_click_started=False, tab_cleanup='closed_error_page')
        (self.root/'web-card-control.json').write_text('{"paused_by_user":true}')
        self.assertEqual(self.tick()['state'], 'paused');self.assertEqual(self.state(), 'failed')
        (self.root/'web-card-control.json').unlink()
        self.catalog.event(self.pid, 'human_decision', {'decision': 'keep'})
        self.assertEqual(self.tick()['requeued'], [])
        with self.catalog.connect() as db:db.execute("DELETE FROM events WHERE kind='human_decision'")
        (self.folder/'prompt.txt').write_text('changed')
        self.assertEqual(self.tick()['requeued'], []);self.assertTrue((self.folder/'chatgpt/attempt.json').exists())

    def test_finished_response_hash_change_blocks_both_local_and_external_retry(self):
        self.attempt('response_saved', json.dumps(self.card))
        (self.folder/'chatgpt/response-raw.txt').write_text('changed')
        self.assertEqual(self.tick()['requeued'], []);self.assertEqual(self.tick()['published'], [])

    def zip_response(self):
        import os
        from browser.web_upload_bundle import prepare_web_upload
        with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')}):
            bundle,prompt=prepare_web_upload(self.folder,self.packet)
        a=self.attempt('response_saved',json.dumps(self.card),upload_bundle=bundle)
        actual=self.folder/'chatgpt/prompt-actual.txt';actual.write_text(prompt)
        a['actual_prompt_sha256']=digest(actual);(self.folder/'chatgpt/attempt.json').write_text(json.dumps(a))
        return a

    def test_exact_recorded_zip_wrapper_allows_local_validation(self):
        self.zip_response()
        self.assertEqual(self.tick()['published'],[self.pid])
        self.assertEqual(self.state(),'completed')
        self.router.choose.assert_not_called()

    def test_changed_zip_or_unrecognized_prompt_wrapper_blocks_retry(self):
        a=self.zip_response();Path(a['upload_bundle']['zip_path']).write_bytes(b'changed package')
        report=self.tick();self.assertEqual(report['published'],[]);self.assertEqual(report['requeued'],[])
        self.assertIn('ZIP指纹',report['blocked'][0]['reason'])
        a=self.attempt('response_saved',json.dumps(self.card),upload_bundle=a['upload_bundle'])
        actual=self.folder/'chatgpt/prompt-actual.txt';actual.write_text(actual.read_text()+' unapproved instruction')
        a['actual_prompt_sha256']=digest(actual);(self.folder/'chatgpt/attempt.json').write_text(json.dumps(a))
        self.assertEqual(self.tick()['requeued'],[]);self.assertEqual(self.tick()['published'],[])

    def test_extra_sends_stop_after_two_retries_but_final_answer_can_still_parse(self):
        (self.folder/'retry.json').write_text('{"external_retries":2}')
        self.attempt('response_saved', '{"title":"incomplete"}')
        self.assertEqual(self.tick()['requeued'], [])
        self.attempt('response_saved', json.dumps(self.card))
        self.assertEqual(self.tick()['published'], [self.pid])

    def test_cooldown_blocks_resubmission(self):
        self.attempt('not_sent', error='附件上传失败', tab_cleanup='closed_error_page')
        self.router.choose.side_effect = RuntimeError('额度冷却')
        self.assertEqual(self.tick()['requeued'], []);self.assertTrue((self.folder/'chatgpt/attempt.json').exists())

    def test_live_page_assigned_to_other_paper_is_never_touched(self):
        self.attempt('not_sent', send_click_started=False)
        page = Mock()
        report = self.tick(pages={'original': page}, entries={'original': {'active_paper_id': 'other'}})
        self.assertEqual(report['requeued'], [self.pid]);page.goto.assert_not_called()

    def test_racing_completion_does_not_get_reopened(self):
        self.attempt('not_sent', send_click_started=False, tab_cleanup='closed_error_page')
        def finish(*args,**kwargs):
            with self.catalog.connect() as db:db.execute("UPDATE web_card_jobs SET state='completed',updated='new' WHERE paper_id=?", (self.pid,))
        with patch('cards.web_card_retry.reset_unsent_page', side_effect=finish):
            self.assertEqual(self.tick()['requeued'], [])
        self.assertEqual(self.state(), 'completed');self.assertTrue((self.folder/'chatgpt/attempt.json').exists())

    def claimed_backlog(self,*,target='original',paper_id=None):
        from browser.shared_page_backlog import install
        install(self.catalog)
        self.config['web_cards']['shared_window']={'enabled':True,'backlog':{'enabled':True}}
        pid=paper_id or self.pid
        with self.catalog.connect() as db:
            db.execute('INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES(?,?,?,?,?,?)',
                       ('cards',pid,pid,target,10,'claimed'))

    def claim_exists(self,paper_id=None):
        with self.catalog.connect() as db:
            return bool(db.execute('SELECT 1 FROM shared_page_backlog WHERE lane=? AND job_id=?',('cards',paper_id or self.pid)).fetchone())

    def test_retry_cas_releases_only_archived_explicit_unsent_exact_lease(self):
        self.claimed_backlog();self.claimed_backlog(target='original',paper_id='other-claimed-paper')
        attempt=self.attempt('not_sent',send_click_started=False,error='附件上传失败',tab_cleanup='closed_error_page')
        report=self.tick()
        self.assertEqual(report['requeued'],[self.pid]);self.assertFalse(self.claim_exists())
        self.assertTrue(self.claim_exists('other-claimed-paper'));self.assertEqual(self.state(),'queued')
        self.assertEqual(report['released_page_leases'],[{'lane':'cards','job_id':self.pid,'target_id':'original'}])
        ledger=json.loads((self.folder/'retry.json').read_text())
        self.assertEqual(ledger['external_retries'],1);self.assertEqual(ledger['retry_at'],1300)
        self.assertEqual(json.loads((Path(ledger['history'])/'chatgpt/attempt.json').read_text()),attempt)

    def test_retry_does_not_release_unknown_or_clicked_original_lease(self):
        self.claimed_backlog()
        for state,clicked in (('needs_inspection',False),('not_sent',True),('submission_started',True)):
            original=self.attempt(state,send_click_started=clicked,error='附件上传失败',tab_cleanup='closed_error_page')
            report=self.tick()
            self.assertEqual(report['requeued'],[]);self.assertTrue(self.claim_exists())
            self.assertEqual(json.loads((self.folder/'chatgpt/attempt.json').read_text()),original)

    def test_retry_input_change_or_exhausted_count_preserves_original_lease(self):
        self.claimed_backlog();self.attempt('not_sent',send_click_started=False,tab_cleanup='closed_error_page')
        original=(self.folder/'prompt.txt').read_text();(self.folder/'prompt.txt').write_text('Changed frozen input')
        self.assertEqual(self.tick()['requeued'],[]);self.assertTrue(self.claim_exists())
        (self.folder/'prompt.txt').write_text(original);atomic=json.dumps({'external_retries':2})
        (self.folder/'retry.json').write_text(atomic)
        self.assertEqual(self.tick()['requeued'],[]);self.assertTrue(self.claim_exists())
        self.assertEqual((self.folder/'retry.json').read_text(),atomic)

    def test_retry_archive_failure_cannot_release_original_claim(self):
        self.claimed_backlog();original=self.attempt('not_sent',send_click_started=False,tab_cleanup='closed_error_page')
        with patch('core.archive_paths.Path.rename',side_effect=OSError('Synthetic archive failure')):
            report=self.tick()
        self.assertEqual(report['requeued'],[]);self.assertTrue(self.claim_exists());self.assertEqual(self.state(),'failed')
        self.assertEqual(json.loads((self.folder/'chatgpt/attempt.json').read_text()),original)

    def test_retry_racing_completion_preserves_original_claim_and_receipt(self):
        self.claimed_backlog();original=self.attempt('not_sent',send_click_started=False,tab_cleanup='closed_error_page')
        def finish(*args,**kwargs):
            with self.catalog.connect() as db:db.execute("UPDATE web_card_jobs SET state='completed',updated='new' WHERE paper_id=?",(self.pid,))
            return {'original'}
        with patch('cards.web_card_retry.reset_unsent_page',side_effect=finish):report=self.tick()
        self.assertEqual(report['requeued'],[]);self.assertTrue(self.claim_exists());self.assertEqual(self.state(),'completed')
        self.assertEqual(json.loads((self.folder/'chatgpt/attempt.json').read_text()),original)

    def test_page_reused_for_another_paper_keeps_old_lease_without_touching_new_page(self):
        self.claimed_backlog();self.attempt('not_sent',send_click_started=False)
        page=Mock();report=self.tick(pages={'original':page},entries={'original':{'active_paper_id':'another'}})
        self.assertEqual(report['requeued'],[self.pid]);self.assertTrue(self.claim_exists())
        page.goto.assert_not_called();self.assertEqual(report.get('released_page_leases',[]),[])

    def protected_rework(self, kind='source_review'):
        target=self.root/'library'/self.pid;target.mkdir(parents=True)
        old=target/'card.json';old.write_text('An immutable original evidence-bound card')
        backup=target/'history'/'protected-source-rework';backup.mkdir(parents=True)
        (backup/'card.json').write_bytes(old.read_bytes())
        self.catalog.update(self.pid,card_path=str(old))
        record={'kind':kind,'review_id':'original-review','correction_id':'independent-correction',
            'old_card_path':str(old),'old_sha256':digest(old),'backup':str(backup),'human_protected':kind!='source_review'}
        with self.catalog.connect() as db:
            db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',(json.dumps({'rework':record}),self.pid))
        self.catalog.decide(self.pid,'keep')
        self.attempt('response_saved',json.dumps(self.card))
        return old

    def test_protected_source_review_candidate_is_not_reported_published_or_requeued(self):
        old=self.protected_rework();before=old.read_bytes()
        first=self.tick()
        self.assertEqual(first['published'],[]);self.assertEqual(first['requeued'],[])
        self.assertEqual(self.state(),'needs_inspection')
        self.assertIn('人工决定',first['blocked'][0]['reason'])
        candidate=self.folder/'gpt-rework-candidate'/'card.json'
        self.assertTrue(candidate.is_file());self.assertEqual(old.read_bytes(),before)
        self.assertTrue((self.folder/'chatgpt'/'attempt.json').is_file())
        checks=json.loads((self.folder/'retry.json').read_text())['local_checks']
        self.assertEqual(next(iter(checks.values()))['state'],'blocked')
        self.assertEqual(next(iter(checks.values()))['job_state'],'needs_inspection')
        second=self.tick()
        self.assertEqual(second['published'],[]);self.assertEqual(second['requeued'],[])
        self.assertEqual(self.state(),'needs_inspection');self.assertEqual(old.read_bytes(),before)
        self.router.choose.assert_not_called()

    def test_existing_manifest_candidate_is_protected_without_false_publication(self):
        old=self.protected_rework('authorized_manifest');before=old.read_bytes()
        report=self.tick()
        self.assertEqual(report['published'],[]);self.assertEqual(report['requeued'],[])
        self.assertEqual(self.state(),'protected');self.assertEqual(old.read_bytes(),before)
        self.assertTrue((self.folder/'gpt-rework-candidate'/'card.json').is_file())
        check=next(iter(json.loads((self.folder/'retry.json').read_text())['local_checks'].values()))
        self.assertEqual(check['state'],'blocked');self.assertEqual(check['job_state'],'protected')
        self.router.choose.assert_not_called()

    def test_successful_mock_publication_requires_real_completed_state(self):
        self.attempt('response_saved',json.dumps(self.card))
        def complete(*args):queue.update(self.catalog,self.pid,state='completed')
        with patch('cards.web_card_service.publish_saved',side_effect=complete) as publish:
            report=self.tick()
        publish.assert_called_once();self.assertEqual(report['published'],[self.pid]);self.assertEqual(self.state(),'completed')
        self.assertEqual(report['requeued'],[])

    def test_mock_return_without_publication_receipt_blocks_future_external_retry(self):
        self.attempt('response_saved',json.dumps(self.card))
        with patch('cards.web_card_service.publish_saved') as publish:
            first=self.tick();second=self.tick()
        publish.assert_called_once()
        for report in (first,second):
            self.assertEqual(report['published'],[]);self.assertEqual(report['requeued'],[])
            self.assertTrue(report['blocked'])
        self.assertEqual(self.state(),'failed');self.router.choose.assert_not_called()


class SyntaxTests(unittest.TestCase):
    def test_only_separators_change_not_math_string_values(self):
        raw = r'{"math":"\\Omega_{CT} + \\omega" "n":2,}'
        self.assertEqual(json.loads(normalize(raw)), {'math': r'\Omega_{CT} + \omega', 'n': 2})
    def test_valid_json_and_duplicate_fields_remain_intact(self):
        raw = '{"a":"x,y } ","a":"second"}'
        self.assertEqual(normalize(raw), raw)


class UploadGuardTests(unittest.TestCase):
    def setUp(self):
        _trace_temp(self)
    def test_disabled_upload_without_quota_notice_does_not_pause_entire_provider(self):
        from browser.web_card_pool import record_channel_failure
        router=Mock();record_channel_failure(router,RuntimeError('网页文件上传入口已禁用，禁止提交附件'))
        router.block.assert_not_called()
        record_channel_failure(router,RuntimeError('已达上传上限'))
        self.assertEqual(router.block.call_args.args[0].kind,'quota')
    def test_timeout_or_pause_happens_before_callback_or_click(self):
        from browser.web_card_transport import submit_gpt_background
        import types
        session = types.SimpleNamespace(page=Mock(), _pending_answer=None, verify_settings=Mock())
        callback = Mock()
        with patch('web_gpt.submission.submission_lock'),patch('web_gpt.core.upload_files_detailed',return_value=UPLOAD_OK),\
             patch('browser.web_card_transport.wait_gpt_upload_ready'),\
             patch('browser.web_card_transport.wait_gpt_upload_settled',side_effect=RuntimeError('附件仍在上传，未点击发送')):
            with self.assertRaisesRegex(RuntimeError,'仍在上传'):
                submit_gpt_background(session,'prompt',['source.pdf'],callback)
        callback.assert_not_called();session.page.evaluate.assert_not_called()


class UploadProgressBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw=sync_playwright().start()
        chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        try:
            cls.browser=cls.pw.chromium.launch(**({'executable_path':str(chrome)} if chrome.is_file() else {}),headless=True)
        except Exception:
            cls.pw.stop();raise
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def test_visible_upload_progress_blocks_send_until_it_actually_finishes(self):
        from browser.web_card_transport import wait_gpt_upload_settled
        page=self.browser.new_page()
        try:
            page.set_content('<div role="progressbar" aria-label="正在上传文件 visual.pdf">uploading</div>')
            with self.assertRaisesRegex(RuntimeError,'未点击发送'):wait_gpt_upload_settled(page,timeout=50)
            page.evaluate("setTimeout(()=>document.querySelector('[role=progressbar]').remove(),100)")
            wait_gpt_upload_settled(page,timeout=2000)
        finally:page.close()
    def test_pause_during_upload_does_not_wait_or_send(self):
        from browser.web_card_transport import wait_gpt_upload_settled, DeferredWeb
        page=self.browser.new_page()
        try:
            page.set_content('<div role="progressbar">uploading</div>')
            with self.assertRaises(DeferredWeb):wait_gpt_upload_settled(page,stopping=lambda:True)
        finally:page.close()

class EmptySavedArtifactTests(unittest.TestCase):
    def test_empty_saved_hash_does_not_authorize_retry(self):
        import hashlib
        from cards.web_card_retry import finished_response
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'attempt.json'
            (path.parent/'response-raw.txt').write_bytes(b'')
            attempt={'state':'response_saved','raw_sha256':hashlib.sha256(b'').hexdigest()}
            with self.assertRaisesRegex(ValueError,'空占位'):
                finished_response(path,attempt,{})
