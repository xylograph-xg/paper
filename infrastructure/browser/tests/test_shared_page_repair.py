"""Lifecycle tests use temporary ledgers and an isolated in-memory browser."""
import copy
import asyncio
import base64
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from browser import shared_page_repair as repair
from browser.shared_page_health import classify


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SharedPageRepair(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {'catalog_path': str(self.root / 'catalog.sqlite'), 'web_cards': {
            'enabled': True, 'shared_window': {'enabled': True, 'slot_count': 20,
                'health_repair': {'enabled': True, 'check_interval_seconds': 30,
                                  'max_replacements_per_cycle': 2}}}, 'card_review': {'enabled': False}}
        self.browser = Mock()
        self.registry = {'schema_version': 1, 'window_id': 77, 'revision': 0,
            'endpoint': os.environ.get('WEB_GPT_CDP_URL', 'http://127.0.0.1:9222'),
            'slots': [{'slot_id': f'{i+1:02d}', 'target_id': f't{i:02d}'} for i in range(20)]}
        self.registry_path = self.root / 'shared-gpt-window.json'
        self.registry_path.write_text(json.dumps(self.registry))
        self.pool = {'windows': {f't{i:02d}': {'state': 'ready_blank', 'never_submitted': True}
                                  for i in range(20)}}
        self.pool['windows']['t00'] = {'state': 'needs_inspection'}
        self.targets = {tid: {'target_id': tid, 'window_id': 77, 'url': 'https://chatgpt.com/'}
                        for tid in self.pool['windows']}
        self.pages = {}
        self.snapshots = {}
        self.now = 160.0
        for tid in self.targets:
            self.add_page(tid)
        self.old_page = self.pages['t00']
        self.snapshots['t00']['errors'] = ['net::ERR_SSL_PROTOCOL_ERROR']
        self.prompt = '合成材料 web-card-11111111-1111-4111-8111-111111111111-input123'
        self.ledger_path = self.root / 'web_cards' / 'original-paper' / 'chatgpt' / 'attempt.json'
        self.ledger_path.parent.mkdir(parents=True)
        self.ledger = {'state': 'not_sent', 'target_id': 't00', 'send_click_started': False,
                       'error': 'Page.goto net::ERR_SSL_PROTOCOL_ERROR',
                       'actual_prompt_sha256': sha(self.prompt)}
        (self.ledger_path.parent / 'prompt-actual.txt').write_text(self.prompt)
        self.ledger_path.write_text(json.dumps(self.ledger))
        self.seed_previous()
        for name, effect in [('read_window_inventory', self.inventory), ('enumerate_pages', self.enumerate),
                             ('snapshot_page', self.snapshot), ('require_slot', self.guard),
                             ('create_in_window', self.create)]:
            patcher = patch.object(repair, name, side_effect=effect)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(repair.time, 'time', side_effect=lambda: self.now)
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('web_gpt.core.wait_prompt_box', return_value=Mock(is_visible=lambda: True))
        self.wait_box = patcher.start(); self.addCleanup(patcher.stop)

    def add_page(self, tid, url=None, window_id=77):
        if tid not in self.targets:
            self.targets[tid] = {'target_id': tid, 'window_id': window_id, 'url': url}
        page = Mock()
        page.url = self.targets[tid]['url']
        page.locator.return_value.inner_text.return_value = 'ERR_SSL_PROTOCOL_ERROR'
        page.content.return_value = '<main>ERR_SSL_PROTOCOL_ERROR</main>'
        page.screenshot.side_effect = lambda path, **kwargs: Path(path).write_bytes(b'png-evidence')

        def close():
            self.targets.pop(tid, None)
            self.pages.pop(tid, None)

        def goto(url, **kwargs):
            page.url = url
            self.targets[tid]['url'] = url

        page.close.side_effect = close
        page.goto.side_effect = goto
        self.pages[tid] = page
        self.snapshots[tid] = {'target_id': tid, 'url': page.url, 'checked_at': self.now,
            'inspection_complete': True, 'user_texts': [], 'answer_texts': [], 'draft': '',
            'attachments': 0, 'streaming': False, 'terminal_complete': False,
            'terminal_stopped': False, 'verification': False, 'login': False, 'quota': False,
            'errors': []}
        return page

    def seed_previous(self):
        snapshot = {**self.snapshots['t00'], 'checked_at': 100.0}
        ledger = {**self.ledger, '_ledger_path': str(self.ledger_path.resolve())}
        previous = classify(snapshot, self.pool['windows']['t00'], ledger,
                            urls=[snapshot['url']])
        (self.root / 'shared-page-health.json').write_text(json.dumps(
            {'checked_at': 100.0, 'pages': {'t00': previous}}))

    def inventory(self, browser):
        return {'targets': copy.deepcopy(self.targets), 'total_pages': len(self.targets),
                'complete': True, 'errors': []}

    def enumerate(self, browser):
        return {'pages': dict(self.pages), 'total_pages': len(self.pages), 'complete': True, 'errors': []}

    def snapshot(self, tid, page):
        return {**copy.deepcopy(self.snapshots[tid]), 'url': page.url, 'checked_at': self.now}

    def guard(self, config, browser, tid):
        registry = json.loads(self.registry_path.read_text())
        if tid not in {slot.get('target_id') for slot in registry['slots']}:
            raise repair.WindowIsolationError('unregistered target')
        if self.targets[tid]['window_id'] != registry['window_id']:
            raise repair.WindowIsolationError('moved target')
        return True

    def create(self, browser, window_id, *, root, nonce, owned_ids, on_created, stopping):
        self.assertNotIn('t00', self.targets)
        journal = json.loads((Path(root).parent / 'journal.json').read_text())
        self.assertEqual(journal['state'], 'create_intent')
        manifest = json.loads((Path(root).parent / 'diagnostics' / 'archive-manifest.json').read_text())
        self.assertTrue(manifest['complete'])
        self.assertFalse(stopping())
        candidate = {'target_id': 'replacement', 'window_id': window_id,
                     'url': repair.blank_url(nonce), 'nonce': nonce,
                     'created': True, 'extension_uninstalled': True}
        self.add_page('replacement', candidate['url'], window_id)
        on_created(candidate)
        return candidate

    def test_upload_target_is_not_inspected_or_closed_by_maintenance(self):
        report=repair.run_once(self.config,self.browser,self.pool,
            lock_factory=lambda **kwargs:nullcontext(),excluded_targets={'t00'})
        self.assertIn('t00',report['deferred_upload_targets'])
        self.assertNotIn('t00',[call.args[0] for call in self.snapshot_page.call_args_list])
        self.old_page.close.assert_not_called()
        self.old_page.goto.assert_not_called()

    def run_cycle(self, stopping=None):
        return repair.run_once(self.config, self.browser, self.pool, stopping=stopping,
                               lock_factory=lambda timeout: nullcontext())

    def test_failed_native_upload_is_archived_and_replaced_only_after_two_real_rounds(self):
        self.config['web_cards']['shared_window']['health_repair'].update(
            failed_upload_recovery_enabled=True,stalled_unsent_after_seconds=60)
        self.ledger.update(created=10,finished=40,owner_pid=123,inputs={'source.pdf':sha('source')},
            upload_bundle={'zip_path':str(self.ledger_path.parent/'bundle.zip'),'zip_sha256':sha('zip')})
        (self.ledger_path.parent/'source.pdf').write_text('source');(self.ledger_path.parent/'bundle.zip').write_text('zip')
        self.ledger_path.write_text(json.dumps(self.ledger));before=self.ledger_path.read_bytes()
        self.snapshots['t00'].update(errors=[],uploading=True,draft=self.prompt,attachments=1,attachment_names=['bundle.zip'])
        (self.root/'web-upload-network.json').write_text(json.dumps({'errors':[{
            'target_id':'t00','at':30,'method':'PUT','failure':'net::ERR_HTTP2_PROTOCOL_ERROR'}]}))
        self.run_cycle();self.old_page.close.assert_not_called()
        self.now+=30;result=self.run_cycle()
        self.old_page.close.assert_called_once();self.create_in_window.assert_called_once()
        journal=self.journals()[0]
        self.assertTrue(journal['failed_upload_restart']);self.assertTrue(journal['archive_hashes'])
        self.assertEqual(journal['authorization'],'docs/authorizations/20261015-system-proxy-upload-fix.md')
        self.assertEqual(self.ledger_path.read_bytes(),before);self.assertEqual(len(self.targets),20)
        self.assertTrue(journal['health']['evidence']['snapshot']['uploading'])

    def test_repeated_page_read_failure_still_checks_other_nineteen(self):
        original = self.snapshot
        def failing(tid, page):
            if tid == 't00':
                raise OSError('persistent local read failure')
            return original(tid, page)
        self.snapshot_page.side_effect = failing
        for at in (160, 200):
            self.now = at
            report = self.run_cycle()
            self.assertEqual(report['state'], 'checked')
            self.assertEqual(len(report['pages']), 20)
            self.assertEqual(report['counts'], {'maintenance_error': 1, 'healthy_blank': 19})
            self.assertEqual(report['available'], 19)
            self.assertEqual(report['errors'][0]['target_id'], 't00')
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_lease_callback_failure_does_not_abort_next_pages(self):
        self.snapshots['t00']['errors'] = []
        def recover(tid, health):
            if tid == 't00':
                raise FileNotFoundError('receipt moved during CAS')
            return []
        report = repair.run_once(self.config, self.browser, self.pool,
            lock_factory=lambda timeout: nullcontext(), on_checked_page=recover)
        self.assertEqual(report['state'], 'checked')
        self.assertEqual(len(report['pages']), 20)
        self.assertEqual(report['pages']['t00']['health'], 'maintenance_error')
        self.assertEqual(report['available'], 19)
        self.old_page.close.assert_not_called()

    def test_window_isolation_failure_still_stops_entire_cycle(self):
        self.require_slot.side_effect = repair.WindowIsolationError('ownership changed')
        report = self.run_cycle()
        self.assertEqual(report['state'], 'needs_inspection')
        self.snapshot_page.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_submit_lock_contention_is_waiting_and_never_requests_user_inspection(self):
        lock=Mock(side_effect=RuntimeError('等待网页提交锁超时'))
        report=repair.run_once(self.config,self.browser,self.pool,lock_factory=lock)
        self.assertEqual(report['state'],'waiting_submission_lock')
        self.snapshot_page.assert_not_called()
        self.old_page.close.assert_not_called()

    def test_owner_recovery_callback_runs_under_lock_before_next_page(self):
        from contextlib import contextmanager
        held=False;seen=[]
        @contextmanager
        def lock(**kwargs):
            nonlocal held
            held=True
            try:yield
            finally:held=False
        def callback(tid,health):
            self.assertTrue(held)
            self.assertIn('evidence',health)
            seen.append(tid)
            return [{'target_id':tid}]
        self.snapshots['t00']['errors']=[]
        report=repair.run_once(self.config,self.browser,self.pool,lock_factory=lock,on_checked_page=callback)
        self.assertEqual(len(seen),20)
        self.assertEqual(len(report['recovered_page_leases']),20)
        self.assertFalse(held)

    def test_batch_reads_release_lock_and_page_callbacks_keep_exclusive_target(self):
        from contextlib import contextmanager
        held=False;leased=set();reads=[];callbacks=[]
        @contextmanager
        def lock(**kwargs):
            nonlocal held
            self.assertFalse(held);held=True
            try:yield
            finally:held=False
        @contextmanager
        def lease(tid):
            leased.add(tid)
            try:yield tid!='t01'
            finally:leased.remove(tid)
        original=self.snapshot_page.side_effect
        def snapshot(tid,page):
            reads.append(held);return original(tid,page)
        def callback(tid,health):
            self.assertTrue(held);self.assertIn(tid,leased);callbacks.append(tid)
        self.snapshot_page.side_effect=snapshot;self.snapshots['t00']['errors']=[]
        report=repair.run_once(self.config,self.browser,self.pool,lock_factory=lock,
                              target_lease=lease,on_checked_page=callback)
        self.assertFalse(any(reads));self.assertNotIn('t01',callbacks)
        self.assertIn('t01',report['deferred_upload_targets']);self.assertFalse(leased)

    def test_unknown_receipt_is_archived_once_without_close_move_or_resend(self):
        url='https://chatgpt.com/c/local-chatgpt-unknown'
        self.targets['t00']['url']=self.old_page.url=url
        self.ledger.update(state='needs_inspection',send_click_started=True,conversation_url=url)
        self.ledger_path.write_text(json.dumps(self.ledger));original=self.ledger_path.read_bytes()
        self.snapshots['t00'].update(url=url,user_texts=[self.prompt],answer_texts=[],errors=[])
        self.run_cycle();self.now+=60
        second=self.run_cycle()
        self.assertEqual(second['pages']['t00']['health'],'unknown')
        holds=list((self.root/'shared-page-holds').glob('*/journal.json'))
        self.assertEqual(len(holds),1)
        archived=json.loads(holds[0].read_text())
        self.assertEqual(archived['state'],'preserved')
        self.assertFalse(archived['close_authorized']);self.assertFalse(archived['move_authorized'])
        self.now+=60;self.run_cycle()
        self.assertEqual(len(list((self.root/'shared-page-holds').glob('*/journal.json'))),1)
        self.assertEqual(self.ledger_path.read_bytes(),original)
        self.old_page.close.assert_not_called();self.old_page.goto.assert_not_called()

    def test_missing_repair_blank_requires_journal_hashes_and_no_submission_history(self):
        identity='a'*32;tid='t00';slot={'target_id':tid,'slot_id':'00'}
        entry={'state':'missing','origin':'shared_page_health_repair','repair_id':identity,'never_submitted':True}
        snapshot={**self.snapshots[tid],'url':'https://chatgpt.com/','errors':[]}
        folder=self.root/'shared-page-repairs'/identity
        (folder/'diagnostics').mkdir(parents=True)
        fingerprints={}
        for name in ('health.json','body.txt','page.html','page.png','ledger-before.json'):
            (folder/'diagnostics'/name).write_text('original evidence')
            fingerprints[name]=sha('original evidence')
        repair.atomic_json(folder/'journal.json',{'state':'ready','new_target_id':tid,'slot_id':'00','window_id':77,'archive_hashes':fingerprints})
        check=lambda paths=():repair._restorable_repair_blank(self.root,slot,entry,snapshot,paths,77)
        self.assertTrue(check())
        self.assertFalse(check(('unknown-attempt.json',)))
        snapshot['user_texts']=['unknown request'];self.assertFalse(check())
        snapshot['user_texts']=[]
        (folder/'diagnostics/body.txt').write_text('changed');self.assertFalse(check())

    def test_clean_homepage_with_completed_history_exits_protection(self):
        raw='Completed synthetic original response'
        self.ledger.update(state='response_saved',conversation_url='https://chatgpt.com/c/saved',raw_sha256=sha(raw))
        self.ledger_path.write_text(json.dumps(self.ledger))
        (self.ledger_path.parent/'response-raw.txt').write_text(raw)
        self.snapshots['t00']['errors']=[]
        report=self.run_cycle()
        self.assertEqual(report['pages']['t00']['health'],'healthy_blank')
        self.assertEqual(self.pool['windows']['t00']['state'],'ready_blank')
        self.assertEqual(report['available'],20)
        self.old_page.close.assert_not_called();self.old_page.goto.assert_not_called()

    def test_missing_repair_blank_accepts_complete_mhtml_archive_and_refuses_tampering(self):
        identity='b'*32;tid='t00';slot={'target_id':tid,'slot_id':'00'}
        entry={'state':'missing','origin':'shared_page_health_repair','repair_id':identity,'never_submitted':True}
        snapshot={**self.snapshots[tid],'url':'https://chatgpt.com/','errors':[]}
        folder=self.root/'shared-page-repairs'/identity
        diagnostics=folder/'diagnostics';diagnostics.mkdir(parents=True)
        for name in ('health.json','body.txt','page.html','ledger-before.json','page.mhtml'):
            (diagnostics/name).write_text('original evidence')
        repair.atomic_json(diagnostics/'capture.json',{'method':'resident_cdp_mhtml','screenshot_available':False})
        fingerprints={item.name:repair._sha(item) for item in diagnostics.iterdir()}
        journal={'state':'ready','new_target_id':tid,'slot_id':'00','window_id':77,'archive_hashes':fingerprints}
        repair.atomic_json(folder/'journal.json',journal)
        check=lambda:repair._restorable_repair_blank(self.root,slot,entry,snapshot,(),77)
        self.assertTrue(check())
        (diagnostics/'page.mhtml').write_text('changed document');self.assertFalse(check())
        (diagnostics/'page.mhtml').write_text('original evidence')
        repair.atomic_json(diagnostics/'capture.json',{'method':'resident_cdp_mhtml','screenshot_available':True})
        journal['archive_hashes']['capture.json']=repair._sha(diagnostics/'capture.json')
        repair.atomic_json(folder/'journal.json',journal);self.assertFalse(check())

    def completed_error_homepage(self):
        raw = 'Original complete synthetic answer'
        self.ledger.update(state='response_saved', created=200,
                           conversation_url='https://chatgpt.com/c/original-saved', raw_sha256=sha(raw))
        self.ledger_path.write_text(json.dumps(self.ledger))
        (self.ledger_path.parent / 'response-raw.txt').write_text(raw)
        historical = self.root / 'web_cards/original-paper/history/old/chatgpt/attempt.json'
        historical.parent.mkdir(parents=True)
        record = {**self.ledger, 'created': 100, 'conversation_url': 'https://chatgpt.com/c/old-saved'}
        historical.write_text(json.dumps(record))
        (historical.parent / 'response-raw.txt').write_text(raw)
        (historical.parent / 'prompt-actual.txt').write_text(self.prompt)
        notice = '请尝试重新加载，或退出登录后重新登录'
        self.snapshots['t00'].update(errors=[notice], page_error_detection_version=1,
            page_error_notices=[{'text': notice, 'source': 'visible_main_notice_ui'}])
        self.seed_previous()
        return historical

    def test_completed_error_homepage_archives_full_history_without_changing_answers(self):
        historical = self.completed_error_homepage()
        original = {p: p.read_bytes() for p in (historical, self.ledger_path)}
        report = self.run_cycle()
        self.assertEqual(len(report['replaced']), 1, report)
        journal = self.journals()[0]
        self.assertEqual(set(journal['record_hashes']), {str(p.resolve()) for p in original})
        archived = next((self.root / 'shared-page-repairs').glob('*/diagnostics/target-history-before.json'))
        self.assertEqual({item['path'] for item in json.loads(archived.read_text())}, set(journal['record_hashes']))
        for path, value in original.items():self.assertEqual(path.read_bytes(), value)

    def test_history_disappearance_during_screenshot_preserves_error_homepage(self):
        historical = self.completed_error_homepage()
        def screenshot(path, **kwargs):
            Path(path).write_bytes(b'original PNG');historical.unlink()
        self.old_page.screenshot.side_effect = screenshot
        report = self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        self.assertTrue(report['errors'])

    def test_history_change_after_archive_blocks_close(self):
        historical = self.completed_error_homepage()
        original = repair._journal
        def journal(path, value, state=None, **updates):
            original(path, value, state, **updates)
            if state is None and value['state'] == 'archived':
                historical.write_text(json.dumps({**json.loads(historical.read_text()),
                    'state': 'needs_inspection', 'send_click_started': True}))
        with patch.object(repair, '_journal', side_effect=journal):report = self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        self.assertTrue(report['errors'])

    def test_changed_page_retires_unexecuted_plan_and_requires_new_stable_evidence(self):
        original=repair._journal;changed=False;ledger=self.ledger_path.read_bytes()
        def journal(path,value,state=None,**updates):
            nonlocal changed
            original(path,value,state,**updates)
            if state is None and value['state']=='archived' and not changed:
                changed=True;self.snapshots['t00']['draft']='new user draft'
                self.pool['windows']['t00'].update(state='repair_pending',repair_id=value['id'],repair_in_progress=True)
        with patch.object(repair,'_journal',side_effect=journal):first=self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        saved=self.journals()[0]
        self.assertEqual(saved['state'],'cancelled');self.assertTrue(saved['cancelled_before_close'])
        preserved=Path(saved['superseded_plan'])
        self.assertEqual(repair._sha(preserved),saved['superseded_plan_sha256'])
        self.assertEqual(json.loads(preserved.read_text())['state'],'archived')
        self.assertNotIn('t00',first['pending_repair_targets'])
        self.assertFalse(self.pool['windows']['t00'].get('repair_in_progress'))
        self.assertEqual(self.snapshots['t00']['draft'],'new user draft')
        self.snapshots['t00']['draft']='';self.snapshots['t00']['errors']=['net::ERR_CONNECTION_RESET']
        self.now+=31;self.run_cycle()
        self.old_page.close.assert_not_called()
        self.now+=31;last=self.run_cycle()
        self.assertEqual(len(last['replaced']),1,last)
        self.old_page.close.assert_called_once();self.assertEqual(self.ledger_path.read_bytes(),ledger)

    def test_changed_page_never_retires_unknown_close_or_creation_intent(self):
        original=repair._journal
        def journal(path,value,state=None,**updates):
            original(path,value,state,**updates)
            if state is None and value['state']=='archived':
                original(path,value,'close_intent')
                self.snapshots['t00']['draft']='new user draft'
        with patch.object(repair,'_journal',side_effect=journal):report=self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        self.assertEqual(self.journals()[0]['state'],'close_intent')
        self.assertIn('t00',report['pending_repair_targets'])
        self.assertTrue(report['errors'])

    def journals(self):
        return [json.loads(path.read_text()) for path in (self.root / 'shared-page-repairs').glob('*/journal.json')]

    def test_archives_before_close_then_replaces_same_slot_without_changing_original_ledger(self):
        original = self.ledger_path.read_bytes()
        original_windows = self.pool['windows']
        report = self.run_cycle()
        self.assertEqual(report['state'], 'checked', report)
        self.assertEqual(len(report['replaced']), 1)
        self.assertEqual(report['available'], 20)
        self.assertEqual(report['protected'], 0)
        self.assertIs(self.pool['windows'], original_windows)
        self.assertEqual(self.ledger_path.read_bytes(), original)
        self.old_page.close.assert_called_once()
        self.old_page.screenshot.assert_called_once_with(
            path=str(next((self.root / 'shared-page-repairs').glob('*/diagnostics/page.png'))), timeout=15000)
        self.create_in_window.assert_called_once()
        self.assertEqual(self.pool['windows']['t00']['state'], 'retired_replaced')
        self.assertEqual(self.pool['windows']['replacement']['state'], 'ready_blank')
        slot = json.loads(self.registry_path.read_text())['slots'][0]
        self.assertEqual(slot['target_id'], 'replacement')
        self.assertEqual(slot['replacement_history'][0]['target_id'], 't00')
        self.wait_box.assert_called_once()

    def test_no_prompt_unsent_navigation_error_can_be_archived_without_fabricated_prompt(self):
        self.ledger['actual_prompt_sha256'] = None
        self.ledger_path.write_text(json.dumps(self.ledger))
        (self.ledger_path.parent / 'prompt-actual.txt').unlink()
        self.seed_previous()
        original = self.ledger_path.read_bytes()
        report = self.run_cycle()
        self.assertEqual(len(report['replaced']), 1, report)
        evidence = next((self.root / 'shared-page-repairs').glob('*/diagnostics/prompt-not-created.json'))
        self.assertTrue(json.loads(evidence.read_text())['prompt_not_created'])
        self.assertEqual(self.ledger_path.read_bytes(), original)

    def test_archive_failure_preserves_page_and_still_checks_other_nineteen_pages(self):
        self.old_page.screenshot.side_effect = RuntimeError('screenshot unavailable')
        report = self.run_cycle()
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()
        self.assertEqual(report['counts']['healthy_blank'], 19)
        self.assertEqual(report['state'], 'checked')
        self.assertTrue(report['errors'])
        self.assertTrue((self.root / 'shared-page-health.json').exists())
        journal=self.journals()[0]
        self.assertEqual(journal['state'],'archive_failed')
        self.assertFalse(journal['close_authorized'])
        self.assertEqual(journal['record']['_ledger_path'],str(self.ledger_path.resolve()))

    def test_screenshot_timeout_archives_resident_capture_before_replacing(self):
        from playwright.sync_api import TimeoutError
        self.old_page.screenshot.side_effect = TimeoutError('viewport preparation timed out')
        original = self.ledger_path.read_bytes()
        with patch.object(repair, '_capture_png_on_owner', return_value=b'original-viewport-png') as capture:
            report = self.run_cycle()
        self.assertEqual(len(report['replaced']), 1, report)
        capture.assert_called_once_with(self.old_page)
        self.old_page.close.assert_called_once()
        self.assertEqual(self.ledger_path.read_bytes(), original)
        folder = next((self.root / 'shared-page-repairs').glob('*/diagnostics'))
        self.assertEqual((folder / 'page.png').read_bytes(), b'original-viewport-png')
        self.assertEqual(json.loads((folder / 'capture.json').read_text())['method'], 'resident_cdp_viewport')
        self.assertIn('capture.json', json.loads((folder / 'archive-manifest.json').read_text())['files'])

    def test_failed_resident_capture_never_closes_or_creates(self):
        from playwright.sync_api import TimeoutError
        self.old_page.screenshot.side_effect = TimeoutError('screenshot stalled')
        with patch.object(repair, '_capture_png_on_owner', side_effect=ValueError('invalid PNG')):
            report = self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        self.assertEqual(report['counts']['healthy_blank'], 19)
        self.assertTrue(report['errors'])

    def test_both_screenshot_timeouts_archive_bound_document_without_fabricating_png(self):
        from playwright.sync_api import TimeoutError
        self.old_page.screenshot.side_effect = TimeoutError('renderer screenshot stalled')
        with patch.object(repair, '_capture_png_on_owner', side_effect=asyncio.TimeoutError()), \
                patch.object(repair, '_capture_mhtml_on_owner', return_value='Original bound MHTML document'):
            report = self.run_cycle()
        self.assertEqual(len(report['replaced']), 1, report)
        folder = next((self.root / 'shared-page-repairs').glob('*/diagnostics'))
        self.assertEqual((folder / 'page.mhtml').read_text(), 'Original bound MHTML document')
        self.assertFalse((folder / 'page.png').exists())
        capture = json.loads((folder / 'capture.json').read_text())
        self.assertFalse(capture['screenshot_available'])
        hashes = json.loads((folder / 'archive-manifest.json').read_text())['files']
        self.assertIn('page.mhtml', hashes);self.assertNotIn('page.png', hashes)

    def test_unavailable_document_after_screenshot_timeouts_preserves_original(self):
        from playwright.sync_api import TimeoutError
        self.old_page.screenshot.side_effect = TimeoutError('renderer screenshot stalled')
        with patch.object(repair, '_capture_png_on_owner', side_effect=asyncio.TimeoutError()), \
                patch.object(repair, '_capture_mhtml_on_owner', side_effect=ValueError('wrong origin')):
            report = self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        self.assertTrue(report['errors'])

    def test_page_moved_during_resident_capture_is_preserved(self):
        from playwright.sync_api import TimeoutError
        self.old_page.screenshot.side_effect = TimeoutError('screenshot stalled')
        def capture(page):
            self.targets['t00']['window_id'] = 88
            return b'original-viewport-png'
        with patch.object(repair, '_capture_png_on_owner', side_effect=capture):
            report = self.run_cycle()
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()
        self.assertTrue(report['errors'])

    def test_page_moved_during_archive_is_not_read_again_or_closed(self):
        def body(**kwargs):
            self.targets['t00']['window_id'] = 88
            return 'ERR_SSL_PROTOCOL_ERROR'
        self.old_page.locator.return_value.inner_text.side_effect = body
        report = self.run_cycle()
        self.assertTrue(report['errors'])
        self.old_page.content.assert_not_called()
        self.old_page.screenshot.assert_not_called()
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_registry_cas_change_during_archive_prevents_close(self):
        def screenshot(path, **kwargs):
            Path(path).write_bytes(b'png')
            registry = json.loads(self.registry_path.read_text())
            registry['revision'] += 1
            self.registry_path.write_text(json.dumps(registry))
        self.old_page.screenshot.side_effect = screenshot
        report = self.run_cycle()
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()
        self.assertEqual(report['state'], 'pending')
        self.assertIn('t00', report['pending_repair_targets'])

    def test_initial_pause_has_no_page_reads_or_lifecycle_operations(self):
        report = self.run_cycle(stopping=lambda: True)
        self.assertEqual(report['state'], 'paused')
        self.read_window_inventory.assert_not_called()
        self.snapshot_page.assert_not_called()
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_unused_nonce_network_fault_is_archived_before_bounded_initialization_retry(self):
        original=self.create
        def failed_navigation(*args,**kwargs):
            result=original(*args,**kwargs)
            self.pages['replacement'].goto.side_effect=lambda *a,**k:None
            self.pages['replacement'].url='chrome-error://chromewebdata/'
            return result
        self.create_in_window.side_effect=failed_navigation
        self.run_cycle()
        self.assertEqual(self.journals()[0]['candidate_initialization_fault']['rounds'],1)
        page=self.pages['replacement'];page.goto.reset_mock()
        self.now+=30;self.run_cycle();page.goto.assert_not_called()
        def recovered(url,**kwargs):page.url=url;self.targets['replacement']['url']=url
        page.goto.side_effect=recovered
        self.now+=31;self.run_cycle()
        page.goto.assert_called_once()
        journal=self.journals()[0]
        self.assertEqual(journal['state'],'ready')
        self.assertTrue(Path(journal['candidate_initialization_archive']).is_dir())

    def test_unused_candidate_network_fault_with_user_draft_is_never_retried(self):
        original=self.create
        def user_draft(*args,**kwargs):
            result=original(*args,**kwargs);page=self.pages['replacement']
            page.url='chrome-error://chromewebdata/'
            self.snapshots['replacement']['draft']='user draft'
            return result
        self.create_in_window.side_effect=user_draft
        self.run_cycle();page=self.pages['replacement'];page.goto.reset_mock()
        self.now+=300;self.run_cycle();page.goto.assert_not_called()
        self.assertEqual(self.journals()[0]['state'],'registered')

    def test_foreign_page_in_dedicated_window_blocks_all_dom_and_closes(self):
        self.add_page('foreign', 'https://example.com/private', 77)
        report = self.run_cycle()
        self.assertEqual(report['state'], 'needs_inspection')
        self.snapshot_page.assert_not_called()
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_unknown_creation_is_not_repeated_and_unique_original_nonce_can_recover(self):
        self.create_in_window.side_effect = RuntimeError('lost create reply')
        first = self.run_cycle()
        self.assertEqual(first['state'], 'pending', first)
        self.assertEqual(self.journals()[0]['state'], 'create_unknown')
        second = self.run_cycle()
        self.assertEqual(second['state'], 'pending', second)
        self.assertEqual(self.create_in_window.call_count, 1)
        nonce = self.journals()[0]['nonce']
        self.add_page('replacement', repair.blank_url(nonce), 77)
        third = self.run_cycle()
        self.assertEqual(third['state'], 'checked', third)
        self.assertEqual(self.create_in_window.call_count, 1)
        self.assertEqual(self.pool['windows']['replacement']['state'], 'ready_blank')

    def saved_unknown_candidate(self, *, cleanup=True):
        def lost_final_reply(*args, **kwargs):
            candidate = self.create(*args, **kwargs)
            candidate['extension_uninstalled'] = cleanup
            kwargs['on_created'](candidate)
            raise RuntimeError('lost detach reply after saving candidate')
        self.create_in_window.side_effect = lost_final_reply
        self.run_cycle()
        path = next((self.root/'shared-page-repairs').glob('*/journal.json'))
        self.assertEqual(json.loads(path.read_text())['state'], 'create_unknown')
        return path

    def test_saved_unknown_candidate_recovers_without_repeating_creation(self):
        path = self.saved_unknown_candidate()
        ledger = self.ledger_path.read_bytes()
        result = self.run_cycle()
        self.assertEqual(result['state'], 'checked', result)
        self.assertEqual(json.loads(path.read_text())['state'], 'ready')
        self.assertEqual(self.create_in_window.call_count, 1)
        self.assertEqual(self.ledger_path.read_bytes(), ledger)
        self.assertEqual(self.pool['windows']['replacement']['state'], 'ready_blank')

    def test_saved_unknown_candidate_preserves_unconfirmed_extension_cleanup(self):
        path = self.saved_unknown_candidate(cleanup=False)
        result = self.run_cycle()
        journal = json.loads(path.read_text())
        self.assertEqual(result['state'], 'pending', result)
        self.assertEqual(journal['state'], 'registered')
        self.assertIs(journal['candidate']['extension_uninstalled'], False)
        self.assertEqual(json.loads(self.registry_path.read_text())['slots'][0]['target_id'], 'replacement')
        self.assertEqual(self.pool['windows']['replacement']['state'], 'opening')
        self.pages['replacement'].goto.assert_not_called()
        self.assertEqual(self.create_in_window.call_count, 1)

    def test_saved_unknown_candidate_conflicts_fail_closed(self):
        path = self.saved_unknown_candidate()
        saved = json.loads(path.read_text())
        for field, value in (('target_id', 'other'), ('window_id', 999),
                             ('nonce', 'different'), ('url', 'https://chatgpt.com/')):
            with self.subTest(field=field):
                journal = copy.deepcopy(saved)
                journal['candidate'][field] = value
                path.write_text(json.dumps(journal))
                original = self.registry_path.read_bytes()
                self.run_cycle()
                self.assertEqual(self.registry_path.read_bytes(), original)
                self.assertEqual(json.loads(path.read_text())['state'], 'create_unknown')
                self.pages['replacement'].goto.assert_not_called()
                self.assertEqual(self.create_in_window.call_count, 1)

    def test_saved_unknown_candidate_cleanup_confirmed_by_original_owner(self):
        path = self.saved_unknown_candidate(cleanup=False)
        self.browser.new_browser_cdp_session.return_value.send.return_value = {'extensions': []}
        result = self.run_cycle()
        self.assertEqual(result['state'], 'checked', result)
        journal = json.loads(path.read_text())
        self.assertEqual(journal['state'], 'ready')
        self.assertIs(journal['extension_cleanup_recovery']['original_candidate']['extension_uninstalled'], False)
        self.assertTrue(journal['candidate']['extension_uninstalled'])
        self.assertEqual(self.create_in_window.call_count, 1)
        self.browser.new_browser_cdp_session.return_value.send.assert_called_once_with('Extensions.getExtensions')

    def test_saved_unknown_candidate_missing_or_duplicate_nonce_never_recreates(self):
        path = self.saved_unknown_candidate()
        nonce = json.loads(path.read_text())['nonce']
        self.add_page('duplicate', repair.blank_url(nonce), 77)
        registry = self.registry_path.read_bytes()
        self.run_cycle()
        self.assertEqual(self.registry_path.read_bytes(), registry)
        self.pages['duplicate'].close.assert_not_called()
        self.pages['replacement'].goto.assert_not_called()
        self.pages['duplicate'].close()
        self.pages['replacement'].close()
        self.run_cycle()
        self.assertEqual(json.loads(path.read_text())['state'], 'create_unknown')
        self.assertEqual(self.create_in_window.call_count, 1)

    def test_saved_unknown_candidate_pause_preserves_original_phase(self):
        path = self.saved_unknown_candidate()
        registry = self.registry_path.read_bytes()
        self.run_cycle(stopping=lambda: True)
        self.assertEqual(json.loads(path.read_text())['state'], 'create_unknown')
        self.assertEqual(self.registry_path.read_bytes(), registry)
        self.pages['replacement'].goto.assert_not_called()
        self.assertEqual(self.create_in_window.call_count, 1)

    def test_legacy_candidate_without_nonce_field_uses_exact_nonce_url(self):
        path = self.saved_unknown_candidate()
        journal = json.loads(path.read_text())
        journal['candidate'].pop('nonce')
        path.write_text(json.dumps(journal))
        result = self.run_cycle()
        self.assertEqual(result['state'], 'checked', result)
        self.assertEqual(json.loads(path.read_text())['state'], 'ready')
        self.assertEqual(self.create_in_window.call_count, 1)

    def test_displaced_auto_successor_keeps_exact_receipt_identity(self):
        self.test_displaced_submitted_receipt_restores_exact_bytes_and_never_repeats_request('b'*24+'-auto-1792616961')

    def test_displaced_submitted_receipt_restores_exact_bytes_and_never_repeats_request(self,jid='b'*24):
        from core.api import catalog__Catalog as Catalog
        from browser.shared_pool_store import PoolSnapshot
        catalog=Catalog(self.config['catalog_path'])
        old=self.root/'card_reviews'/'paper'/jid;old.mkdir(parents=True)
        active=old.with_name(jid+'-auto');active.mkdir()
        old_job={'id':jid,'paper_id':'paper','state':'submitted','folder':str(old),
            'result':'{}','error':'sent','updated':'old','card_sha256':'card-hash','source_sha256':'source-hash'}
        (active/'previous-job.json').write_text(json.dumps(old_job))
        prompt='原冻结核验 card-review-'+jid;(old/'prompt-actual.txt').write_text(prompt)
        packet={'job_id':jid,'card_sha256':'card-hash','source_original_sha256':'source-hash',
            'actual_prompt_sha256':sha(prompt),'input_hashes':{'source.pdf':'source-hash'}}
        receipt={'state':'submitted','target_id':'t00','review_id':jid,'created':17,
            'send_click_started':True,'actual_prompt_sha256':sha(prompt),'inputs':packet['input_hashes'],
            'conversation_url':'https://chatgpt.com/c/original','owner_pid':89,
            'settings':{'model':'GPT-6','effort':'高'}}
        archive=self.root/'claim-lease-release'/'1'/(jid+'-attempt-retired.json')
        archive.parent.mkdir(parents=True);archive.write_text(json.dumps(receipt));original=archive.read_bytes()
        with catalog.connect() as db:
            db.execute("CREATE TABLE card_review_jobs(id TEXT PRIMARY KEY,paper_id TEXT,state TEXT,folder TEXT,result TEXT,error TEXT,updated TEXT,card_sha256 TEXT,source_sha256 TEXT)")
            db.execute("INSERT INTO card_review_jobs VALUES(?,?,'needs_user',?,?,'hold','current','card-hash','source-hash')",
                (jid,'paper',str(active),json.dumps({'failure_kind':'technical'})))
            db.execute("CREATE TABLE shared_page_backlog(lane TEXT,job_id TEXT,target_id TEXT,state TEXT)")
            db.execute("INSERT INTO shared_page_backlog VALUES('review',?,'t01','claimed')",(jid,))
        snapshot={**self.snapshots['t00'],'url':receipt['conversation_url'],'checked_at':200,
            'user_texts':[prompt],'answer_texts':['original complete answer'],'terminal_complete':True,'errors':[]}
        self.snapshots['t00']=snapshot;self.pages['t00'].url=snapshot['url'];self.targets['t00']['url']=snapshot['url']
        prior=classify({**snapshot,'checked_at':100},self.pool['windows']['t00'],None,urls=[snapshot['url']])
        pool=PoolSnapshot(self.pool)
        with (patch('review.api.card_review_queue__check_packet',return_value=packet),
              patch('review.api.card_review_queue__current',return_value=({'decision':'unreviewed'},None,None)),
              patch('review.api.card_review_queue__protected',return_value=False),
              patch.object(repair,'_archive',return_value={'page.html':'synthetic'})):
            args=(self.config,self.browser,pool,self.registry['slots'][0],self.pages['t00'],snapshot,prior,[snapshot['url']],{},lambda:False)
            with self.assertRaises(repair.WindowIsolationError):repair._restore_displaced_review(*args)
            self.assertFalse((old/'attempt.json').exists())
            with catalog.connect() as db:db.execute("UPDATE shared_page_backlog SET state='queued'")
            result=repair._restore_displaced_review(*args)
        self.assertEqual((old/'attempt.json').read_bytes(),original);self.assertEqual(archive.read_bytes(),original)
        self.assertEqual(result['created'],17);self.assertEqual(result['owner_pid'],89)
        self.assertEqual(result['state'],'submitted')
        with catalog.connect() as db:
            row=db.execute('SELECT state,folder FROM card_review_jobs').fetchone()
            self.assertEqual(tuple(row),('submitted',str(old)))
            self.assertEqual(db.execute('SELECT count(*) FROM shared_page_backlog').fetchone()[0],0)
        self.assertTrue((active/'previous-job.json').exists())

    def test_orphan_auto_successor_preserves_unknown_sender(self):
        self.test_orphan_review_recovery_is_explicit_and_preserves_unknown_sender('a'*24+'-auto-1792616961')

    def test_draft_identity_preserves_full_review_successor_id(self):
        jid='a'*24+'-auto-1792616961'
        self.assertEqual(repair._draft_identity('材料标识 card-review-'+jid+'；原冻结材料'),('review',jid))

    def test_orphan_review_recovery_is_explicit_and_preserves_unknown_sender(self,jid='a'*24):
        import sqlite3
        from browser.shared_pool_store import PoolSnapshot
        from core.api import catalog__Catalog as Catalog
        catalog=Catalog(self.config['catalog_path'])
        folder=self.root/'card_reviews'/'paper'/jid;folder.mkdir(parents=True)
        prompt='仅原文核验 card-review-'+jid
        (folder/'prompt-actual.txt').write_text(prompt);(folder/'response-raw.txt').write_text('original complete answer')
        with catalog.connect() as db:
            db.execute("CREATE TABLE card_review_jobs(id TEXT PRIMARY KEY,paper_id TEXT,state TEXT,folder TEXT,result TEXT,error TEXT,updated TEXT,card_sha256 TEXT,source_sha256 TEXT)")
            db.execute("INSERT INTO card_review_jobs VALUES(?,?,'failed',?,'{}','original receipt missing','old','card-hash','source-hash')",(jid,'paper',str(folder)))
            db.execute("CREATE TABLE shared_page_backlog(lane TEXT,job_id TEXT,target_id TEXT)")
        snapshot={**self.snapshots['t00'],'checked_at':100,'user_texts':[prompt],
            'answer_texts':['original complete answer'],'terminal_complete':True,'errors':[]}
        self.snapshots['t00']=snapshot
        prior=classify(snapshot,self.pool['windows']['t00'],None,urls=['https://chatgpt.com/'])
        snapshot['url']='https://chatgpt.com/c/orphan';snapshot['checked_at']=200
        prior=classify({**snapshot,'checked_at':100},self.pool['windows']['t00'],None,urls=[snapshot['url']])
        self.targets['t00']['url']=snapshot['url'];self.pages['t00'].url=snapshot['url']
        packet={'job_id':jid,'card_sha256':'card-hash','source_original_sha256':'source-hash','actual_prompt_sha256':sha(prompt),'input_hashes':{'source.pdf':'source-hash'}}
        with (patch('review.api.card_review_queue__check_packet',return_value=packet),
              patch('review.api.card_review_queue__current',return_value=({'decision':'unreviewed'},None,None)),
              patch('review.api.card_review_queue__protected',return_value=False),
              patch.object(repair,'_archive',return_value={'page.html':'synthetic-hash'})):
            result=repair._recover_orphan_review(self.config,self.browser,PoolSnapshot(self.pool),self.registry['slots'][0],
                self.pages['t00'],snapshot,prior,[snapshot['url']],{},lambda:False)
        self.assertEqual(result['state'],'response_saved')
        self.assertTrue(result['original_attempt_missing']);self.assertTrue(result['actual_model_unknown'])
        self.assertNotIn('owner_pid',result);self.assertNotIn('send_click_started',result)
        self.assertEqual((folder/'response-raw.txt').read_text(),'original complete answer')
        with catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM card_review_jobs').fetchone()[0],'response_saved')

    def test_terminal_empty_needs_two_real_rounds_and_never_counts_a_response(self):
        self.config['web_cards']['shared_window']['health_repair']['hard_restart_after_seconds']=3600
        h={'health':'terminal_empty','evidence':{'fingerprint':'original'}}
        r={'created':1,'_ledger_sha256':'original-ledger'}
        self.assertFalse(repair._terminal_empty_restart(self.config,h,r,at=3601))
        self.assertFalse(repair._terminal_empty_restart(self.config,h,r,at=3700))
        prior=copy.deepcopy(h)
        self.assertFalse(repair._terminal_empty_restart(self.config,h,r,prior,at=3710))
        self.assertTrue(repair._terminal_empty_restart(self.config,h,r,prior,at=3730))
        changed={'health':'terminal_empty','evidence':{'fingerprint':'changed'}}
        self.assertFalse(repair._terminal_empty_restart(self.config,changed,r,prior,at=3800))
        self.assertNotIn('state',r)

    def test_hourly_idle_restart_excludes_unknown_and_active_pages(self):
        self.config['web_cards']['shared_window']['health_repair']['hard_restart_after_seconds'] = 3600
        snapshot = dict(self.snapshots['t00'], uploading=False)
        health = {'health': 'healthy_blank', 'evidence': {'fingerprint': 'fixed', 'snapshot': snapshot}}
        entry = {'state': 'missing', 'error': 'technical error'}
        record = dict(self.ledger, _ledger_sha256='same')
        self.assertFalse(repair._hourly_idle_restart(self.config, health, entry, record, at=10))
        prior = copy.deepcopy(health)
        self.assertFalse(repair._hourly_idle_restart(self.config, health, entry, record, prior, at=3610))
        self.assertTrue(repair._hourly_idle_restart(self.config, health, entry, record, prior, at=3611))
        for field, value in [('streaming', True), ('uploading', True), ('login', True), ('draft', 'user draft')]:
            protected = copy.deepcopy(health); protected['evidence']['snapshot'][field] = value
            self.assertFalse(repair._hourly_idle_restart(self.config, protected, entry, record, prior, at=8000))
        self.assertFalse(repair._hourly_idle_restart(self.config, health, dict(entry, state='busy'), record, prior, at=8000))
        self.assertFalse(repair._hourly_idle_restart(self.config, health, entry, dict(record, state='submitted'), prior, at=8000))

    def test_hourly_missing_epoch_waits_hour_and_two_real_checks(self):
        self.config['web_cards']['shared_window']['health_repair']['hard_restart_after_seconds'] = 3600
        self.create_in_window.side_effect = RuntimeError('lost create reply')
        self.run_cycle()
        journal = self.journals()[0]
        self.now += 3599
        self.run_cycle()
        self.assertEqual(self.create_in_window.call_count, 1)
        self.now += 2
        self.run_cycle()
        self.assertEqual(self.create_in_window.call_count, 1)
        self.now += 31
        self.create_in_window.side_effect = self.create
        self.run_cycle()
        self.assertEqual(self.create_in_window.call_count, 2)
        result = self.journals()[0]
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['creation_epochs'][0]['nonce'], journal['nonce'])
        self.assertTrue(result['creation_epochs'][0]['not_resolved'])

    def test_hourly_missing_epoch_preserves_unclean_extension(self):
        self.config['web_cards']['shared_window']['health_repair']['hard_restart_after_seconds'] = 3600
        self.create_in_window.side_effect = RuntimeError('lost create reply')
        self.run_cycle()
        path = next((self.root / 'shared-page-repairs').glob('*/journal.json'))
        journal = json.loads(path.read_text())
        journal['extension_cleanup_error'] = 'unknown worker'
        path.write_text(json.dumps(journal))
        self.now += 3700
        self.run_cycle(); self.now += 31; self.run_cycle()
        self.assertEqual(self.create_in_window.call_count, 1)

    def test_archived_repair_follows_exact_ledger_move(self):
        journal_path = self.root / 'repair' / 'journal.json'
        journal_path.parent.mkdir()
        expected = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        journal = {'record_hashes': {str(self.ledger_path): expected},
            'record_paths': [str(self.ledger_path)],
            'record': {'_ledger_path': str(self.ledger_path), '_ledger_sha256': expected}}
        journal_path.write_text(json.dumps(journal))
        archived = self.ledger_path.parent / 'history' / 'old' / 'attempt.json'
        archived.parent.mkdir(parents=True)
        self.ledger_path.rename(archived)
        repair._relocate_archived_ledgers(journal_path, journal)
        self.assertEqual(journal['record']['_ledger_path'], str(archived))
        self.assertEqual(journal['record_hashes'], {str(archived): expected})
        self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), expected)

    def test_archived_repair_rejects_changed_ledger(self):
        path = self.root / 'repair.json'; path.write_text('{}')
        expected = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        archived = self.ledger_path.parent / 'history' / 'old' / 'attempt.json'
        archived.parent.mkdir(parents=True)
        self.ledger_path.rename(archived)
        archived.write_text('{}')
        with self.assertRaises(repair.WindowIsolationError):
            repair._relocate_archived_ledgers(path, {'record_hashes': {str(self.ledger_path): expected}})

    def test_archived_repair_follows_exact_history_when_job_path_is_reused(self):
        path = self.root / 'repair.json'
        raw = self.ledger_path.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        old_target = json.loads(raw)['target_id']
        journal = {'old_target_id': old_target, 'record_hashes': {str(self.ledger_path): expected}}
        path.write_text(json.dumps(journal))
        archived = self.ledger_path.parent / 'history' / 'old' / 'attempt.json'
        archived.parent.mkdir(parents=True)
        self.ledger_path.rename(archived)

        self.ledger_path.write_text(json.dumps({'target_id': old_target, 'state': 'submitted'}))
        with self.assertRaises(repair.WindowIsolationError):
            repair._relocate_archived_ledgers(path, journal)
        self.assertEqual(journal['record_hashes'], {str(self.ledger_path): expected})

        newer = json.dumps({'target_id': 'different-target', 'state': 'response_saved'})
        self.ledger_path.write_text(newer)
        repair._relocate_archived_ledgers(path, journal)
        self.assertEqual(journal['record_hashes'], {str(archived): expected})
        self.assertEqual(self.ledger_path.read_text(), newer)
        self.assertEqual(archived.read_bytes(), raw)

    def test_missing_slot_new_epoch_requires_exact_explicit_one_time_authorization(self):
        self.create_in_window.side_effect=RuntimeError('lost create reply')
        self.run_cycle();journal=self.journals()[0];old_nonce=journal['nonce']
        registry=json.loads(self.registry_path.read_text());slot=registry['slots'][0]
        request={'authorized':False,'state':'pending','purpose':'new_missing_slot_epoch',
            'journal_id':journal['id'],'original_nonce':old_nonce,'old_target_id':'t00',
            'slot_id':'01','window_id':77,'journal_created':journal['created'],
            'slot_sha256':hashlib.sha256(json.dumps(slot,sort_keys=True).encode()).hexdigest(),
            'new_nonce':'authorized-new-epoch','authorization':'synthetic user approval'}
        request_path=self.root/'missing-slot-recovery-request.json';request_path.write_text(json.dumps(request))
        self.run_cycle();self.assertEqual(self.create_in_window.call_count,1)
        request['authorized']=True;request['slot_sha256']='changed';request_path.write_text(json.dumps(request))
        self.run_cycle();self.assertEqual(self.create_in_window.call_count,1)
        request['slot_sha256']=hashlib.sha256(json.dumps(slot,sort_keys=True).encode()).hexdigest()
        request_path.write_text(json.dumps(request));registry['revision']+=1
        self.registry_path.write_text(json.dumps(registry))
        self.create_in_window.side_effect=self.create;self.run_cycle()
        recovered=self.journals()[0]
        self.assertEqual(recovered['state'],'ready')
        self.assertEqual(recovered['nonce'],'authorized-new-epoch')
        self.assertEqual(recovered['creation_epochs'][0]['nonce'],old_nonce)
        self.assertTrue(recovered['creation_epochs'][0]['not_resolved'])
        self.assertEqual(json.loads(request_path.read_text())['state'],'consumed')
        self.run_cycle();self.assertEqual(self.create_in_window.call_count,2)

    def test_pause_after_close_preserves_closed_phase_without_opening_page(self):
        paused = [False]
        original_close = self.old_page.close.side_effect
        def close():
            original_close()
            paused[0] = True
        self.old_page.close.side_effect = close
        report = self.run_cycle(stopping=lambda: paused[0])
        self.assertEqual(self.journals()[0]['state'], 'closed_confirmed')
        self.create_in_window.assert_not_called()
        self.assertIn('t00', report['pending_repair_targets'])

    def test_failed_extension_uninstall_keeps_new_candidate_opening(self):
        def create(*args, **kwargs):
            candidate = self.create(*args, **kwargs)
            candidate.update(extension_uninstalled=False, extension_cleanup_error='uninstall refused')
            return candidate
        self.create_in_window.side_effect = create
        report = self.run_cycle()
        self.assertEqual(report['state'], 'pending', report)
        self.assertEqual(self.pool['windows']['replacement']['state'], 'opening')
        self.pages['replacement'].goto.assert_not_called()
        self.assertIn('uninstall refused', str(report['errors']))

    def closed_repair(self):
        paused=[False];close=self.old_page.close.side_effect
        def after_close():close();paused[0]=True
        self.old_page.close.side_effect=after_close
        self.run_cycle(stopping=lambda:paused[0])
        path=next((self.root/'shared-page-repairs').glob('*/journal.json'))
        self.assertEqual(json.loads(path.read_text())['state'],'closed_confirmed')
        return path

    def change_registry_slot(self,index):
        registry=json.loads(self.registry_path.read_text())
        registry['slots'][index]['generation']=1;registry['revision']+=1
        self.registry_path.write_text(json.dumps(registry))

    def test_other_slot_update_does_not_strand_proven_closed_slot(self):
        original=self.ledger_path.read_bytes();path=self.closed_repair()
        self.change_registry_slot(1);result=self.run_cycle()
        self.assertEqual(result['state'],'checked',result)
        self.assertEqual(self.create_in_window.call_count,1)
        self.old_page.close.assert_called_once();self.assertEqual(self.ledger_path.read_bytes(),original)
        journal=json.loads(path.read_text());self.assertTrue(journal['registry_rebases'])
        self.assertEqual(json.loads(self.registry_path.read_text())['slots'][1]['generation'],1)

    def test_same_slot_field_change_still_blocks_creation(self):
        self.closed_repair();self.change_registry_slot(0)
        self.run_cycle();self.create_in_window.assert_not_called()

    def test_legacy_closed_journal_adopts_only_verified_original_slot(self):
        path=self.closed_repair();j=json.loads(path.read_text());j.pop('original_slot')
        path.write_text(json.dumps(j));self.change_registry_slot(1)
        result=self.run_cycle();self.assertEqual(result['state'],'checked',result)
        self.assertTrue(json.loads(path.read_text())['legacy_slot_adopted_after_verified_close'])
        self.assertEqual(self.create_in_window.call_count,1)

    def test_legacy_unknown_creation_never_adopts_new_baseline_or_recreates(self):
        path=self.closed_repair();j=json.loads(path.read_text());j.pop('original_slot')
        j.update(state='create_unknown',nonce='original-persistent-nonce')
        path.write_text(json.dumps(j));self.change_registry_slot(1)
        self.run_cycle();self.create_in_window.assert_not_called()
        self.assertNotIn('legacy_slot_adopted_after_verified_close',json.loads(path.read_text()))

    def test_legacy_closed_slot_uses_unique_byte_identical_original_retry_history(self):
        path=self.closed_repair();j=json.loads(path.read_text());j.pop('original_slot')
        path.write_text(json.dumps(j));self.change_registry_slot(1)
        archived=self.ledger_path.parent.parent/'history/authorized-retry/chatgpt/attempt.json'
        archived.parent.mkdir(parents=True);self.ledger_path.rename(archived)
        result=self.run_cycle();self.assertEqual(result['state'],'checked',result)
        self.assertEqual(json.loads(path.read_text())['legacy_ledger_archive_bindings'][str(self.ledger_path.resolve())]['path'],str(archived.resolve()))

    def test_changed_current_ledger_is_never_replaced_by_an_old_archive_match(self):
        path=self.closed_repair();j=json.loads(path.read_text());j.pop('original_slot')
        path.write_text(json.dumps(j));self.change_registry_slot(1)
        archived=self.ledger_path.parent.parent/'history/authorized-retry/chatgpt/attempt.json'
        archived.parent.mkdir(parents=True);archived.write_bytes(self.ledger_path.read_bytes())
        self.ledger_path.write_text(json.dumps({**self.ledger,'state':'submission_started'}))
        self.run_cycle();self.create_in_window.assert_not_called()

    def test_missing_composer_keeps_new_candidate_opening(self):
        self.wait_box.return_value.is_visible = lambda: False
        report = self.run_cycle()
        self.assertEqual(report['state'], 'pending', report)
        self.assertEqual(self.pool['windows']['replacement']['state'], 'opening')

    def test_login_records_persistent_global_verification_block_without_replacement(self):
        self.snapshots['t00'].update(login=True)
        report = self.run_cycle()
        channel = json.loads((self.root / 'web-channel-control.json').read_text())
        self.assertTrue(channel['chatgpt']['manual_verification_required'])
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()
        self.assertEqual(report['counts']['login'], 1)

    def test_foreign_other_window_is_metadata_only_and_does_not_block_owned_repair(self):
        self.add_page('foreign', 'https://example.com/private', 88)
        report = self.run_cycle()
        self.assertEqual(len(report['replaced']), 1, report)
        self.assertEqual(len(self.targets), 21)
        foreign = self.pages['foreign']
        foreign.locator.assert_not_called()
        foreign.content.assert_not_called()
        foreign.screenshot.assert_not_called()
        foreign.goto.assert_not_called()
        foreign.close.assert_not_called()
        self.assertNotIn('foreign', [call.args[0] for call in self.snapshot_page.call_args_list])

    def saved_old_card(self):
        raw = '完整原卡片回答 α，结构是否合格另行核对。'
        url = 'https://chatgpt.com/c/original-card'
        self.ledger.update(state='response_saved', send_click_started=True,
                           conversation_url=url, raw_sha256=sha(raw), paper_id='original-paper')
        self.ledger_path.write_text(json.dumps(self.ledger))
        archive = self.ledger_path.parent / 'archive' / 'opaque-original.bin'
        archive.parent.mkdir()
        archive.write_text(raw)
        self.targets['t00']['url'] = self.old_page.url = url
        self.snapshots['t00'].update(url=url, user_texts=[self.prompt], answer_texts=[raw],
                                    terminal_complete=True, errors=[])
        self.pool['windows']['t00'].update(raw_path=str(self.ledger_path.parent / 'missing.txt'),
            raw_sha256=sha(raw), conversation_url=url, kind='review', review_id='later-review',
            paper_id='wrong-new-paper', active_paper_id='wrong-new-paper')
        latest = self.root / 'card_reviews' / 'wrong-new-paper' / 'latest' / 'attempt.json'
        latest.parent.mkdir(parents=True)
        latest.write_text(json.dumps({'state': 'not_sent', 'target_id': 't00',
            'send_click_started': False, 'actual_prompt_sha256': None, 'review_id': 'later-review'}))
        return archive

    def test_stable_json_prefix_capture_preserves_original_and_reuses_without_sending(self):
        prefix='{"value": "original'
        complete='{"value": "original complete"}'
        url='https://chatgpt.com/c/original-prefix'
        self.ledger.update(state='response_saved',send_click_started=True,conversation_url=url,raw_sha256=sha(prefix))
        original=json.dumps(self.ledger)
        self.ledger_path.write_text(original)
        raw=self.ledger_path.parent/'response-raw.txt';raw.write_text(prefix)
        self.targets['t00']['url']=self.old_page.url=url
        self.snapshots['t00'].update(url=url,user_texts=[self.prompt],answer_texts=[complete],terminal_complete=True,errors=[])
        self.pool['windows']['t00'].update(raw_path=str(raw),raw_sha256=sha(prefix),conversation_url=url)
        first=self.run_cycle();self.assertEqual(first['pages']['t00']['health'],'waiting_stable')
        self.now+=60
        report=self.run_cycle()
        self.assertEqual(report['pages']['t00']['health'],'completed_saved',report)
        self.assertEqual(raw.read_text(),complete)
        archive=raw.parent/'capture-history'/sha(prefix)
        self.assertEqual((archive/'response-prefix.txt').read_text(),prefix)
        self.assertEqual((archive/'attempt-before.json').read_text(),original)
        self.assertEqual(self.pool['windows']['t00']['state'],'ready')
        self.assertEqual(report['collected'][0]['kind'],'prefix_completion')
        self.old_page.goto.assert_not_called();self.old_page.close.assert_not_called()

    def test_prefix_capture_resumes_if_ledger_write_failed_after_raw_save(self):
        prefix='{"value": "original'
        complete='{"value": "original complete"}'
        url='https://chatgpt.com/c/original-prefix'
        self.ledger.update(state='response_saved',send_click_started=True,conversation_url=url,raw_sha256=sha(prefix))
        self.ledger_path.write_text(json.dumps(self.ledger))
        raw=self.ledger_path.parent/'response-raw.txt';raw.write_text(prefix)
        self.targets['t00']['url']=self.old_page.url=url
        self.snapshots['t00'].update(url=url,user_texts=[self.prompt],answer_texts=[complete],terminal_complete=True,errors=[])
        self.pool['windows']['t00'].update(raw_path=str(raw),raw_sha256=sha(prefix),conversation_url=url)
        self.run_cycle();self.now+=60
        original=repair.atomic_json
        def fail_ledger(path,value,*args,**kwargs):
            if Path(path).resolve()==self.ledger_path.resolve():raise OSError('simulated interrupted ledger save')
            return original(path,value,*args,**kwargs)
        with patch.object(repair,'atomic_json',side_effect=fail_ledger):
            failed=self.run_cycle()
        self.assertEqual(failed['state'],'checked');self.assertEqual(raw.read_text(),complete)
        self.assertEqual(failed['pages']['t00']['health'],'maintenance_error')
        self.assertEqual(len(failed['pages']),20)
        self.assertEqual(json.loads(self.ledger_path.read_text())['raw_sha256'],sha(prefix))
        self.now+=60
        report=self.run_cycle()
        self.assertEqual(report['pages']['t00']['health'],'completed_saved',report)
        self.assertEqual(json.loads(self.ledger_path.read_text())['raw_sha256'],sha(complete))

    def test_raw_path_repair_binds_old_card_ledger_instead_of_latest_unsent_review(self):
        archive = self.saved_old_card()
        original = self.ledger_path.read_bytes()
        report = self.run_cycle()
        self.assertEqual(len(report['repaired_paths']), 1, report)
        entry = self.pool['windows']['t00']
        self.assertEqual(entry['raw_path'], str(archive.resolve()))
        self.assertEqual(entry['kind'], 'cards')
        self.assertEqual(entry['paper_id'], 'original-paper')
        self.assertEqual(entry['active_paper_id'], 'original-paper')
        self.assertNotIn('review_id', entry)
        self.assertEqual(self.ledger_path.read_bytes(), original)
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_collection_reply_remains_exclusive_to_original_observer_and_promoter(self):
        self.saved_old_card();before=copy.deepcopy(self.pool['windows']['t00'])
        records,latest=repair._records(self.root)
        latest['t00']['_collection_recovery']=True
        with patch.object(repair,'_records',return_value=(records,latest)):
            result=self.run_cycle()
        self.assertFalse(result['repaired_paths']);self.assertFalse(result['collected'])
        self.assertEqual(self.pool['windows']['t00'],before)
        self.old_page.close.assert_not_called();self.create_in_window.assert_not_called()

    def test_collection_empty_terminal_releases_only_through_two_round_archive(self):
        self.config['web_cards']['shared_window']['health_repair']['hard_restart_after_seconds']=3600
        url='https://chatgpt.com/c/collection-empty'
        self.ledger.update(state='submitted',send_click_started=True,conversation_url=url,created=1)
        self.ledger_path.write_text(json.dumps(self.ledger));original=self.ledger_path.read_bytes()
        self.pool['windows']['t00'].update(state='busy',original_receipt_recovery='validated-collection')
        self.targets['t00']['url']=self.old_page.url=url
        self.snapshots['t00'].update(url=url,user_texts=[self.prompt],terminal_complete=True,uploading=False,errors=[])
        read_records=repair._records
        def inventory(root):
            records,latest=read_records(root)
            for record in records.values():
                if record.get('target_id')=='t00':record['_collection_recovery']=True
            return records,latest
        self.now=4000
        with patch.object(repair,'_records',side_effect=inventory):
            first=self.run_cycle();self.assertFalse(first['replaced'],first)
            self.now=4029;self.assertFalse(self.run_cycle()['replaced'])
            self.now=4030;result=self.run_cycle()
        self.assertEqual(len(result['replaced']),1,result)
        self.assertTrue(self.journals()[0]['terminal_empty_restart'])
        self.assertFalse(self.journals()[0]['requeue_allowed'])
        self.assertFalse(result['collected']);self.assertEqual(self.ledger_path.read_bytes(),original)

    def test_raw_path_repair_second_snapshot_change_prevents_entry_write(self):
        self.saved_old_card()
        original = copy.deepcopy(self.pool['windows']['t00'])
        reads = [0]
        def snapshot(tid, page):
            current = self.snapshot(tid, page)
            if tid == 't00':
                reads[0] += 1
                if reads[0] == 2:
                    current['answer_texts'] = ['changed live answer']
            return current
        self.snapshot_page.side_effect = snapshot
        report = self.run_cycle()
        self.assertEqual(report['state'], 'needs_inspection', report)
        self.assertEqual(self.pool['windows']['t00'], original)
        self.assertFalse(report['repaired_paths'])

    def test_complete_unsaved_answer_is_durably_saved_unchanged_without_json_or_science_edits(self):
        raw = '```json\n{broken JSON, 原始完整科学输出}\n```'
        url = 'https://chatgpt.com/c/original-response'
        self.ledger.update(state='submitted', send_click_started=True, conversation_url=url)
        self.ledger_path.write_text(json.dumps(self.ledger))
        self.targets['t00']['url'] = self.old_page.url = url
        self.snapshots['t00'].update(url=url, user_texts=[self.prompt], answer_texts=[raw],
                                    terminal_complete=True, errors=[])
        self.seed_previous()
        report = self.run_cycle()
        self.assertEqual(len(report['collected']), 1, report)
        self.assertEqual((self.ledger_path.parent / 'response-raw.txt').read_text(), raw)
        saved = json.loads(self.ledger_path.read_text())
        self.assertEqual(saved['state'], 'response_saved')
        self.assertTrue(saved['send_click_started'])
        self.assertEqual(saved['raw_sha256'], sha(raw))
        self.assertEqual(saved['actual_prompt_sha256'], sha(self.prompt))
        self.assertEqual(self.pool['windows']['t00']['kind'], 'cards')
        self.assertEqual(self.pool['windows']['t00']['paper_id'], 'original-paper')
        self.old_page.close.assert_not_called()
        self.create_in_window.assert_not_called()

    def test_crash_after_registry_cas_recovers_existing_candidate_without_second_create(self):
        original_journal = repair._journal
        failed = [False]
        def journal(path, value, state=None, **updates):
            if state == 'registered' and not failed[0]:
                failed[0] = True
                raise RuntimeError('crash immediately after registry CAS')
            return original_journal(path, value, state, **updates)
        with patch.object(repair, '_journal', side_effect=journal):
            first = self.run_cycle()
        self.assertEqual(first['state'], 'pending', first)
        self.assertEqual(self.journals()[0]['state'], 'candidate_created')
        self.assertEqual(self.pool['windows']['replacement']['state'], 'opening')
        self.assertEqual(json.loads(self.registry_path.read_text())['slots'][0]['target_id'], 'replacement')
        second = self.run_cycle()
        self.assertEqual(second['state'], 'checked', second)
        self.assertEqual(self.pool['windows']['replacement']['state'], 'ready_blank')
        self.assertEqual(self.create_in_window.call_count, 1)

    def test_sent_empty_terminal_replacement_archives_but_does_not_reclassify_or_resend_original(self):
        url = 'https://chatgpt.com/c/original-empty-terminal'
        self.ledger.update(state='submitted', send_click_started=True, conversation_url=url)
        self.ledger_path.write_text(json.dumps(self.ledger))
        self.targets['t00']['url'] = self.old_page.url = url
        self.snapshots['t00'].update(url=url, user_texts=[self.prompt],
            terminal_complete=True, errors=['Something went wrong while generating'])
        self.seed_previous()
        original = self.ledger_path.read_bytes()
        report = self.run_cycle()
        self.assertEqual(len(report['replaced']), 1, report)
        self.assertEqual(report['counts']['terminal_no_response'], 1)
        self.assertEqual(self.ledger_path.read_bytes(), original)
        self.assertEqual(self.journals()[0]['record']['state'], 'submitted')

    def test_authorized_unrecoverable_unknown_replaces_without_requeue(self):
        policy=self.config['web_cards']['shared_window']['health_repair']
        policy.update(replace_unrecoverable_pages=True,unrecoverable_after_seconds=120)
        url='https://chatgpt.com/c/local-chatgpt-stalled'
        self.ledger.update(state='needs_inspection',send_click_started=True,conversation_url=url)
        self.ledger_path.write_text(json.dumps(self.ledger))
        self.targets['t00']['url']=self.old_page.url=url
        self.snapshots['t00'].update(url=url,user_texts=[self.prompt],errors=[])
        original=self.ledger_path.read_bytes()
        self.seed_previous()
        first=self.run_cycle()
        self.assertFalse(first['replaced'])
        self.now+=60
        second=self.run_cycle()
        self.assertFalse(second['replaced'])
        self.now+=60
        third=self.run_cycle()
        self.assertEqual(len(third['replaced']),1,third)
        self.assertEqual(self.ledger_path.read_bytes(),original)
        journal=self.journals()[0]
        self.assertTrue(journal['unrecoverable_fallback'])
        self.assertFalse(journal['requeue_allowed'])
        self.assertEqual(self.pool['windows']['replacement']['state'],'ready_blank')

    def test_two_round_policy_archives_before_replace_without_resending(self):
        policy = self.config['web_cards']['shared_window']['health_repair']
        policy.update(replace_unrecoverable_pages=True, stalled_check_rounds=2)
        url = 'https://chatgpt.com/c/local-chatgpt-stalled'
        self.ledger.update(state='needs_inspection', send_click_started=True, conversation_url=url)
        self.ledger_path.write_text(json.dumps(self.ledger))
        self.targets['t00']['url'] = self.old_page.url = url
        self.snapshots['t00'].update(url=url, user_texts=[self.prompt], errors=[])
        original = self.ledger_path.read_bytes()
        self.seed_previous()
        first = self.run_cycle()
        self.assertFalse(first['replaced'])
        self.assertEqual(first['pages']['t00']['bounded_recheck']['rounds'], 1)
        same_round = self.run_cycle()
        self.assertFalse(same_round['replaced'])
        self.now += 30
        second = self.run_cycle()
        self.assertEqual(len(second['replaced']), 1, second)
        journal = self.journals()[-1]
        self.assertEqual(journal['health']['bounded_recheck']['rounds'], 2)
        self.assertIn('health.json', journal['archive_hashes'])
        self.assertFalse(journal['requeue_allowed'])
        self.assertEqual(self.ledger_path.read_bytes(), original)

    def test_changed_stalled_evidence_restarts_round_count(self):
        h = {'health': 'unknown', 'evidence': {'fingerprint': 'original', 'snapshot': {'inspection_complete': True}}}
        read = Mock(return_value=copy.deepcopy(h))
        first = repair.bounded_recheck(copy.deepcopy(h), None, {}, {}, read, at=0, rounds=2)
        same = repair.bounded_recheck(copy.deepcopy(h), first, {}, {}, read, at=5, rounds=2)
        self.assertEqual(same['bounded_recheck']['rounds'], 1)
        read.assert_not_called()
        changed = {'health': 'unknown', 'evidence': {'fingerprint': 'changed', 'snapshot': {'inspection_complete': True}}}
        read.return_value = changed
        second = repair.bounded_recheck(copy.deepcopy(h), first, {}, {}, read, at=30, rounds=2)
        self.assertEqual(second['bounded_recheck']['rounds'], 1)
        self.assertEqual(second['bounded_recheck']['reads'], 0)

    def test_incomplete_inspection_does_not_count_as_stalled_round(self):
        h = {'health': 'unknown', 'evidence': {'snapshot': {'inspection_complete': False}}}
        read = Mock()
        result = repair.bounded_recheck(h, None, {}, {}, read, at=30, rounds=2)
        self.assertNotIn('bounded_recheck', result)
        read.assert_not_called()

    def test_unrecoverable_fallback_protects_active_and_access_states(self):
        self.config['web_cards']['shared_window']['health_repair']['replace_unrecoverable_pages']=True
        h={'health':'unknown','collect_allowed':False,'bounded_recheck':{
            'state':'still_protected','reads':1,'first_seen':0},'evidence':{'snapshot':{
            'target_id':'t00','inspection_complete':True,'streaming':False}}}
        record={'target_id':'t00'}
        self.assertTrue(repair.stalled_page_fallback(self.config,h,{'state':'needs_inspection'},record,at=160))
        for key,value in [('streaming',True),('login',True),('verification',True),('quota',True),('draft','text'),('attachments',1),('inspection_complete',False)]:
            changed=copy.deepcopy(h);changed['evidence']['snapshot'][key]=value
            self.assertFalse(repair.stalled_page_fallback(self.config,changed,{},record,at=160),key)
        for state in ('busy','submitting','collecting','preparing','uploading'):
            self.assertFalse(repair.stalled_page_fallback(self.config,h,{'state':state},record,at=160),state)
        self.assertFalse(repair.stalled_page_fallback(self.config,h,{},None,at=160))
        self.assertFalse(repair.stalled_page_fallback(self.config,h,{},record,at=119))

    def test_local_unknown_streaming_and_quota_fail_closed_without_replacement(self):
        for changed in [{'url': 'https://chatgpt.com/c/local-chatgpt-protected'},
                        {'streaming': True}, {'quota': True}]:
            with self.subTest(changed=changed):
                original = copy.deepcopy(self.snapshots['t00'])
                self.snapshots['t00'].update(changed)
                if 'url' in changed:
                    self.old_page.url = changed['url']
                    self.targets['t00']['url'] = changed['url']
                self.seed_previous()
                self.run_cycle()
                self.old_page.close.assert_not_called()
                self.create_in_window.assert_not_called()
                self.snapshots['t00'] = original
                self.old_page.url = self.targets['t00']['url'] = original['url']


class DisplacedInputView(unittest.TestCase):
    def test_exact_zip_restores_independent_view_without_changing_damaged_files(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); original={'visual.pdf':b'original visual','card-images.pdf':b'original images','source.pdf':b'source'}
            bundle=folder/'original.zip'
            with zipfile.ZipFile(bundle,'w') as archive:
                for name,data in original.items():archive.writestr(name,data)
            inputs={name:hashlib.sha256(data).hexdigest() for name,data in original.items()}
            prompt=b'original prompt';(folder/'prompt-actual.txt').write_bytes(prompt)
            packet={'input_hashes':inputs,'actual_prompt_sha256':hashlib.sha256(prompt).hexdigest(),
                'upload_bundle':{'zip_path':str(bundle),'zip_sha256':repair._sha(bundle)}}
            raw=json.dumps(packet).encode();(folder/'packet.json').write_bytes(raw)
            for name,data in original.items():(folder/name).write_bytes(b'overwritten' if name!='source.pdf' else data)
            record={'inputs':inputs,'actual_prompt_sha256':packet['actual_prompt_sha256']}
            view=repair._verified_displaced_inputs(folder,record)
            self.assertEqual((view/'packet.json').read_bytes(),raw)
            for name,data in original.items():self.assertEqual((view/name).read_bytes(),data)
            self.assertEqual((folder/'visual.pdf').read_bytes(),b'overwritten')
            self.assertEqual((view/'superseded-input-evidence'/'visual.pdf').read_bytes(),b'overwritten')
            self.assertEqual(repair._verified_displaced_inputs(folder,record),view)
            (folder/'prompt-actual.txt').write_bytes(b'changed')
            with self.assertRaises(repair.WindowIsolationError):repair._verified_displaced_inputs(folder,record)
            (folder/'prompt-actual.txt').write_bytes(prompt);bundle.write_bytes(b'changed zip')
            with self.assertRaises(repair.WindowIsolationError):repair._verified_displaced_inputs(folder,record)

    def test_review_media_namespace_isolates_duplicate_job_folders(self):
        from review.card_review_queue import _review_media_folder
        first=_review_media_folder('/media','paper','same-review','/jobs/original')
        second=_review_media_folder('/media','paper','same-review','/jobs/auto')
        self.assertNotEqual(first,second)
        self.assertEqual(first,_review_media_folder('/media','paper','same-review','/jobs/original'))


class ResidentCapture(unittest.TestCase):
    PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')

    def page(self, data=None):
        session=SimpleNamespace(send=AsyncMock(return_value={'data':base64.b64encode(self.PNG).decode() if data is None else data}),detach=AsyncMock())
        context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
        impl=SimpleNamespace(context=context)
        return SimpleNamespace(_impl_obj=impl,_sync=asyncio.run),session

    def test_bounded_existing_context_capture_detaches_and_never_focuses(self):
        page,session=self.page()
        original=asyncio.wait_for
        with patch.object(repair.asyncio,'wait_for',wraps=original) as bounded:
            self.assertEqual(repair._capture_png_on_owner(page),self.PNG)
        page._impl_obj.context.new_cdp_session.assert_awaited_once_with(page._impl_obj)
        session.send.assert_awaited_once_with('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False,'optimizeForSpeed':True})
        session.detach.assert_awaited_once()
        self.assertEqual([call.args[1] for call in bounded.call_args_list],[3,8,2])

    def test_invalid_or_empty_png_is_refused_after_detach(self):
        for value in ('', 'invalid base64', base64.b64encode(b'not a PNG').decode(),base64.b64encode(self.PNG[:33]).decode()):
            with self.subTest(data=value):
                page,session=self.page(value)
                with self.assertRaises(Exception):repair._capture_png_on_owner(page)
                session.detach.assert_awaited_once()

    def test_capture_timeout_detaches_original_session(self):
        page,session=self.page();session.send.side_effect=asyncio.TimeoutError()
        with self.assertRaises(asyncio.TimeoutError):repair._capture_png_on_owner(page)
        session.detach.assert_awaited_once()

    def mhtml_page(self, content=None):
        url='https://chatgpt.com/c/original-page'
        document=(f'Snapshot-Content-Location: {url}\r\nMIME-Version: 1.0\r\n'
                  'Content-Type: multipart/related; boundary="original"\r\n\r\n'
                  f'--original\r\nContent-Type: text/html\r\nContent-Location: {url}\r\n\r\n'
                  '<html><main>Original complete document</main></html>\r\n--original--\r\n')
        page,session=self.page();page.url=url;session.send.return_value={'data':document if content is None else content}
        return page,session,document

    def test_mhtml_contains_exact_document_origin_and_detaches(self):
        page,session,document=self.mhtml_page()
        self.assertEqual(repair._capture_mhtml_on_owner(page),document)
        session.send.assert_awaited_once_with('Page.captureSnapshot',{'format':'mhtml'})
        session.detach.assert_awaited_once()

    def test_mhtml_wrong_origin_empty_or_missing_html_is_refused(self):
        _,_,document=self.mhtml_page()
        for value in ('',document.replace('/original-page','/other-page'),document.replace('text/html','text/plain')):
            with self.subTest(content=value):
                page,session,_=self.mhtml_page(value)
                with self.assertRaises(repair.WindowIsolationError):repair._capture_mhtml_on_owner(page)
                session.detach.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
