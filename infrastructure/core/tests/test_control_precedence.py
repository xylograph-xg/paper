import json
from core.api import paths__WorkspacePath as Path
import tempfile
import time
import unittest
from unittest.mock import patch
from core.control import evaluate, mutate_record, pause_decision, provider_decisions, submission_decision
from browser.web_card_transport import Router, ProviderFailure, DeferredWeb
from browser.web_card_pool import record_channel_failure


class ControlPrecedence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config={'catalog_path':str(self.root/'catalog.sqlite3')}

    def test_user_pause_precedes_verification_and_cooldown(self):
        result=evaluate('web',paused=True,verification=True,blocked_until=time.time()+100)
        self.assertEqual(result.state,'paused');self.assertFalse(result.requires_user_action)

    def test_malformed_controls_never_resume(self):
        path=self.root/'web-card-control.json'
        for raw in ('[]','broken','{"paused_by_user":"false"}'):
            path.write_text(raw)
            self.assertFalse(pause_decision(self.config,'web_cards').allowed)

    def test_manual_verification_is_not_expiring_cooldown(self):
        mutate_record(self.root/'web-channel-control.json',{'chatgpt':{'manual_verification_required':True}})
        result=provider_decisions(self.root,policy={'allowed_providers':['chatgpt']},at=time.time()+100000)['chatgpt']
        self.assertEqual(result.state,'needs_user');self.assertIsNone(result.expires_at)

    def test_disabled_provider_cannot_block_authorized_provider(self):
        (self.root/'qwen-window.json').write_text('broken')
        self.assertEqual(Router(self.root,{'provider':'chatgpt','allowed_providers':['chatgpt']}).choose(),'chatgpt')

    def test_empty_authorized_provider_list_never_falls_back(self):
        with self.assertRaises(DeferredWeb):Router(self.root,{'provider':'chatgpt','allowed_providers':[]}).choose()

    def test_old_selection_cannot_expand_current_static_scope(self):
        (self.root/'web-provider-selection.json').write_text('{"allowed_providers":["qwen"]}')
        with self.assertRaises(DeferredWeb):Router(self.root,{'allowed_providers':['chatgpt']}).choose()

    def test_disabled_local_models_do_not_resume_when_runtime_file_is_absent(self):
        from core.model_schedule import status
        from reading.reading_service import start
        config={**self.config,'local_models_enabled':False}
        self.assertEqual(status(config)['mode'],'disabled')
        with patch('reading.reading_service.subprocess.Popen') as spawn:
            self.assertEqual(start(config)['state'],'paused');spawn.assert_not_called()

    def test_provider_control_refreshes_between_calls(self):
        router=Router(self.root,{'allowed_providers':['chatgpt']})
        self.assertEqual(router.choose(),'chatgpt')
        mutate_record(self.root/'web-provider-control.json',{'chatgpt':{'blocked_until':time.time()+100}})
        with self.assertRaises(DeferredWeb):router.choose()

    def test_sent_unknown_and_saved_attempts_cannot_send_again(self):
        for state in ('submitted','submission_started','needs_inspection','response_saved','ready',None):
            self.assertFalse(submission_decision([{'state':state}]).allowed)
        self.assertTrue(submission_decision([{'state':'not_sent'},{'state':'deferred'}]).allowed)

    def test_controls_keep_other_fields_and_append_history(self):
        path=self.root/'fetch-control.json';path.write_text('{"paused_by_user":true,"marker":"keep"}')
        mutate_record(path,{'paused_by_user':False},event='user_resume')
        mutate_record(path,{'paused_by_user':True},event='user_pause')
        records=[json.loads(line) for line in (self.root/'control-events.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in records],['user_resume','user_pause'])
        self.assertEqual(records[0]['before']['marker'],'keep')
        self.assertEqual(records[1]['after']['marker'],'keep')

    def test_pool_estimated_hour_is_never_website_reset(self):
        router=Router(self.root)
        record_channel_failure(router,RuntimeError('附件已达到上限，没有明确恢复时间'))
        record=json.loads(router.path.read_text())['chatgpt']
        self.assertFalse(record['explicit_reset']);self.assertEqual(record['reset_source'],'cooldown_probe')
        self.assertGreater(record['blocked_until'],time.time())

    def test_pool_live_notice_keeps_reset_evidence(self):
        from datetime import datetime,timezone
        router=Router(self.root);reset=datetime.fromtimestamp(time.time()+600,timezone.utc).isoformat()
        notice={'source':'live_browser_notice','notice':'上传上限，请在10分钟后重试','not_before_utc':reset}
        with patch('browser.upload_quota.visible_notice',return_value=notice):
            record_channel_failure(router,RuntimeError('附件上传失败'),object())
        record=json.loads(router.path.read_text())['chatgpt']
        self.assertTrue(record['explicit_reset']);self.assertEqual(record['reset_evidence'],notice)

    def test_pool_verification_persists_channel_pause(self):
        router=Router(self.root,{'allowed_providers':['chatgpt']})
        # A stale quota notice on the same page must not turn verification into a timed retry.
        with patch('browser.upload_quota.visible_notice',return_value={'not_before_utc':'2030-01-01T00:00:00+00:00'}):
            record_channel_failure(router,RuntimeError('访问验证：请验证您是真人'),object())
        with self.assertRaises(DeferredWeb):router.choose()
        self.assertTrue(json.loads((self.root/'web-channel-control.json').read_text())['chatgpt']['manual_verification_required'])

    def test_legacy_explicit_boolean_does_not_mislead_panel(self):
        from desktop_widget.snapshot import snapshot
        data=self.root/'data';data.mkdir()
        (data/'web-provider-control.json').write_text(json.dumps({'chatgpt':{'blocked_until':time.time()+60,'reason':'quota','explicit_reset':True}}))
        warnings=snapshot(self.root)['warnings']
        self.assertTrue(any('探测恢复' in w for w in warnings));self.assertFalse(any('网页提示' in w for w in warnings))


class QueueTransitions(unittest.TestCase):
    def test_unknown_or_possibly_sent_jobs_cannot_requeue(self):
        from core.catalog import Catalog
        from cards import web_card_queue as queue
        with tempfile.TemporaryDirectory() as td:
            catalog=Catalog(Path(td)/'catalog.sqlite3');queue.install(catalog)
            with catalog.connect() as db:
                db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated,state) VALUES('p','hash','title','{}','now','submitted')")
            for after in ('queued','preparing','submitting','invented'):
                with self.assertRaises(ValueError):queue.update(catalog,'p',state=after)
            queue.update(catalog,'p',state='needs_inspection')
            with self.assertRaises(ValueError):queue.update(catalog,'p',state='queued')

    def test_completed_and_human_protected_are_terminal(self):
        from core.control import transition_decision
        for before in ('completed','protected'):
            self.assertTrue(transition_decision(before,before).allowed)
            self.assertFalse(transition_decision(before,'failed').allowed)
