import io
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch,MagicMock
from browser.browser_start_request import request, run_once


class BrowserStart(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config={'catalog_path':str(self.root/'catalog.db')}

    def test_repeated_click_keeps_pending_launch_identity(self):
        first=request(self.config,'cards');second=request(self.config,'review')
        self.assertEqual(first['id'],second['id'])

    def test_owner_reuses_existing_endpoint_without_open(self):
        request(self.config,'cards');opener=MagicMock();opener.open.return_value.__enter__.return_value=io.StringIO('{"Browser":"Chrome/100"}')
        with patch('cards.web_card_service.owner_enabled',return_value=True),patch('browser.browser_start_request.urllib.request.build_opener',return_value=opener),patch('browser.browser_start_request.subprocess.run') as launch:
            self.assertEqual(run_once(self.config)['state'],'ready');launch.assert_not_called()

    def test_owner_launches_once_in_background_with_fixed_profile(self):
        request(self.config,'cards');opener=MagicMock();opener.open.side_effect=OSError('offline')
        with patch('cards.web_card_service.owner_enabled',return_value=True),patch('browser.browser_start_request.urllib.request.build_opener',return_value=opener),patch('browser.browser_recovery.main_chrome_pid',return_value=None),patch('browser.browser_start_request.subprocess.run') as launch:
            launch.return_value.returncode=0;launch.return_value.stderr=''
            self.assertEqual(run_once(self.config)['state'],'launched');run_once(self.config)
            self.assertEqual(launch.call_count,1);self.assertEqual(launch.call_args.args[0][:3],['open','-gna','Google Chrome'])

    def test_paused_owner_never_launches(self):
        request(self.config,'cards')
        with patch('cards.web_card_service.owner_enabled',return_value=False),patch('browser.browser_start_request.subprocess.run') as launch:
            self.assertEqual(run_once(self.config)['state'],'pending');launch.assert_not_called()

    def test_existing_process_without_endpoint_does_not_open_second_window(self):
        request(self.config,'review');opener=MagicMock();opener.open.side_effect=OSError('offline')
        with patch('cards.web_card_service.owner_enabled',return_value=True),patch('browser.browser_start_request.urllib.request.build_opener',return_value=opener),patch('browser.browser_recovery.main_chrome_pid',return_value=123),patch('browser.browser_start_request.subprocess.run') as launch:
            self.assertEqual(run_once(self.config)['state'],'waiting_endpoint');launch.assert_not_called()

    def closed_ready(self):
        from core.services import atomic_json
        self.config['web_cards']={'browser_recovery':{'enabled':True}}
        previous={'id':'original-launch','state':'ready','pool_state':'ready','target':'cards'}
        registry={'schema_version':1,'window_id':1,'endpoint':'http://127.0.0.1:9222',
                  'slots':[{'slot_id':f'{i:02d}','target_id':f'old-{i}'} for i in range(1,21)]}
        atomic_json(self.root/'browser-start-request.json',previous)
        atomic_json(self.root/'shared-gpt-window.json',registry)
        self.ledger=self.root/'untouched-attempt.json'
        self.ledger.write_text('{"state":"submitted","send_click_started":true}')
        return previous

    def test_closed_ready_browser_needs_two_spaced_checks_and_only_one_launch(self):
        previous=self.closed_ready();opener=MagicMock();opener.open.side_effect=OSError('offline')
        original=self.ledger.read_bytes()
        with (patch('cards.web_card_service.owner_enabled',return_value=True),
              patch('browser.browser_start_request.urllib.request.build_opener',return_value=opener),
              patch('browser.browser_recovery.main_chrome_pid',return_value=None),
              patch('browser.browser_start_request.time.time',return_value=100.0) as clock,
              patch('browser.browser_start_request.subprocess.run') as launch):
            launch.return_value.returncode=0;launch.return_value.stderr=''
            self.assertEqual(run_once(self.config),previous);launch.assert_not_called()
            clock.return_value=129.0
            self.assertEqual(run_once(self.config),previous);launch.assert_not_called()
            clock.return_value=130.0
            result=run_once(self.config)
            self.assertEqual(result['state'],'launched')
            self.assertEqual(result['origin'],'closed_browser_recovery')
            self.assertNotEqual(result['id'],previous['id'])
            run_once(self.config);self.assertEqual(launch.call_count,1)
        self.assertEqual(self.ledger.read_bytes(),original)
        archive=self.root/'browser-start-archives'/result['id']
        self.assertEqual(json.loads((archive/'request.json').read_text()),previous)
        self.assertTrue((archive/'closed-browser-evidence.json').is_file())

    def test_surviving_process_breaks_consecutive_absent_checks(self):
        previous=self.closed_ready()
        from browser.browser_start_request import _recover_closed
        with (patch('browser.browser_recovery.main_chrome_pid',return_value=None) as process,
              patch('browser.browser_start_request.time.time',return_value=100.0) as clock):
            _recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222')
            process.return_value=42;clock.return_value=130.0
            self.assertEqual(_recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222'),previous)
            process.return_value=None;clock.return_value=160.0
            self.assertEqual(_recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222'),previous)
            self.assertEqual(json.loads((self.root/'browser-start-recovery.json').read_text())['checks'],[160.0])

    def test_partial_startup_and_account_pause_cannot_launch_again(self):
        previous=self.closed_ready()
        from browser.browser_start_request import _recover_closed
        from core.services import atomic_json
        with patch('browser.browser_recovery.main_chrome_pid') as process:
            for state in ['loading_pages','initializing','waiting_page_readiness']:
                value=dict(previous,pool_state=state)
                self.assertEqual(_recover_closed(self.config,self.root,value,'http://127.0.0.1:9222'),value)
            atomic_json(self.root/'web-channel-control.json',{'chatgpt':{'manual_verification_required':True}})
            self.assertEqual(_recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222'),previous)
            process.assert_not_called()

    def test_closed_browser_recovery_preserves_hourly_and_five_minute_limits(self):
        previous=self.closed_ready()
        from browser.browser_start_request import _recover_closed
        from core.services import atomic_json
        with (patch('browser.browser_recovery.main_chrome_pid',return_value=None),
              patch('browser.browser_start_request.time.time',return_value=400.0) as clock):
            _recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222')
            path=self.root/'browser-start-recovery.json';record=json.loads(path.read_text())
            for history in [[200.0],[10.0,20.0]]:
                atomic_json(path,{**record,'recoveries':history})
                clock.return_value=430.0
                self.assertEqual(_recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222'),previous)
                self.assertEqual(json.loads(path.read_text())['state'],'recovery_cooldown')

    def test_archived_pending_intent_resumes_same_identity_after_interrupted_write(self):
        previous=self.closed_ready()
        from browser.browser_start_request import _recover_closed
        from core.services import atomic_json
        with (patch('browser.browser_recovery.main_chrome_pid',return_value=None),
              patch('browser.browser_start_request.time.time',return_value=100.0) as clock):
            _recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222')
            clock.return_value=130.0
            pending=_recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222')
            atomic_json(self.root/'browser-start-request.json',previous)
            self.assertEqual(_recover_closed(self.config,self.root,previous,'http://127.0.0.1:9222'),pending)

    def test_pilot_retry_requires_live_endpoint_and_preserves_account_gate(self):
        from core.services import atomic_json
        previous = dict(self.closed_ready(), target='formula_temp_pilot', pool_state='initializing')
        request_path = self.root / 'browser-start-request.json'
        atomic_json(request_path, previous)
        registry_path = self.root / 'shared-gpt-window.json'
        registry = json.loads(registry_path.read_text())
        registry['startup_request_id'] = previous['id']
        atomic_json(registry_path, registry)
        entries = {slot['target_id']: dict(state='opening', never_submitted=True, startup_request_id=previous['id'])
                   for slot in registry['slots']}
        atomic_json(self.root / 'gpt-window-pool.json', {'windows': entries})
        channel = {'chatgpt': {'manual_verification_required': True, 'source': 'user_report_current_chat'}}
        atomic_json(self.root / 'web-channel-control.json', channel)
        atomic_json(self.root / 'formula-only-control.json', dict(mode='temporary_pilot', pilot_folder=str(self.root)))
        (self.root / 'two-papers.zip').write_bytes(b'packet')
        opener = MagicMock()
        opener.open.side_effect = OSError('offline')
        with (patch('cards.web_card_service.owner_enabled', return_value=True),
              patch('browser.formula_only.enabled', return_value=True),
              patch('browser.browser_start_request.urllib.request.build_opener', return_value=opener),
              patch('browser.browser_recovery.main_chrome_pid', return_value=None),
              patch('browser.browser_start_request.time.time', return_value=100) as clock,
              patch('browser.browser_start_request.subprocess.run') as launch):
            launch.return_value.returncode = 0
            launch.return_value.stderr = ''
            self.assertEqual(run_once(self.config)['state'], 'waiting_endpoint')
            self.assertEqual(json.loads(request_path.read_text()), previous)
            clock.return_value = 130
            self.assertEqual(run_once(self.config)['state'], 'launched')
            self.assertEqual(run_once(self.config)['state'], 'launched')
            launch.assert_called_once()
        self.assertEqual(json.loads((self.root/'web-channel-control.json').read_text()), channel)
