"""Four workflow buttons keep shared services and unrelated pauses intact."""
import copy
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import patch

from core import continuous_start; from cards import web_card_service
from core.control import pause_decision


class FourWorkflowControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.config = {
            'catalog_path': str(self.data / 'catalog.sqlite3'),
            'web_cards': {'enabled': True, 'shared_window': {'enabled': True, 'slot_count': 20}},
            'card_review': {'enabled': True},
            'card_correction': {'enabled': True},
        }
        self.controls = {
            'fetch': 'fetch-control.json', 'cards': 'web-card-control.json',
            'review': 'card-review-control.json', 'correction': 'card-correction-control.json',
            'watcher': 'web-tab-watch-control.json', 'local': 'local-model-control.json',
        }
        for name in self.controls.values():
            self.write(name, {'paused_by_user': True, 'marker': name})
        self.write('web-provider-selection.json', {'provider': 'chatgpt', 'allowed_providers': ['chatgpt'],
                                                  'state': 'ready', 'marker': 'keep'})
        self.addCleanup(patch.stopall)
        patch('core.continuous_start.ROOT', self.root).start()
        self.run = patch('core.continuous_start.subprocess.run',
                         return_value=SimpleNamespace(returncode=0, stderr='', stdout='')).start()
        self.alive = patch('core.runtime.alive', return_value=False).start()
        patch('cards.web_card_service.status', return_value={'alive': True, 'pid': 98765, 'token': 'owned'}).start()
        self.fetch_stop = patch('fetch.fetch_service.request_stop', return_value={'state': 'stop_requested'}).start()

    def write(self, name, value):
        path = self.data / name
        path.write_text(json.dumps(value))
        return path

    def capture(self, except_for=()):
        return {name: (self.data / name).read_bytes() for key, name in self.controls.items()
                if key not in except_for}

    def assert_preserved(self, before):
        self.assertEqual({name: (self.data / name).read_bytes() for name in before}, before)

    def set_pause(self, target, paused):
        path = self.data / self.controls[target]
        value = json.loads(path.read_text())
        value['paused_by_user'] = paused
        self.write(path.name, value)

    def calls(self):
        return [call.args[0] for call in self.run.call_args_list]

    def test_scope_exposes_four_workflows_and_all_stays_fetch_cards(self):
        controls, labels, owners = continuous_start.scope('all')
        self.assertEqual(controls, ('fetch-control.json', 'web-card-control.json'))
        self.assertEqual(labels, ('local.paper.fetch', 'local.paper.web-cards', 'local.paper.web-tab-watch'))
        self.assertEqual(len(owners), 3)
        for target in ('review', 'correction'):
            controls, labels, owners = continuous_start.scope(target)
            self.assertEqual(controls, (self.controls[target],))
            self.assertEqual(labels, ('local.paper.web-cards', 'local.paper.web-tab-watch'))
            self.assertEqual(owners, ('web-card-service.json', 'web-tab-check.json'))

    def test_start_review_or_correction_resumes_only_its_workflow_and_opens_no_page(self):
        for target in ('review', 'correction'):
            with self.subTest(target=target):
                self.set_pause(target, True)
                self.run.reset_mock()
                before = self.capture(except_for=(target,))
                provider = (self.data / 'web-provider-selection.json').read_bytes()
                continuous_start.start(self.config, open_browser=True, target=target)
                self.assertFalse(json.loads((self.data / self.controls[target]).read_text())['paused_by_user'])
                self.assert_preserved(before)
                self.assertEqual((self.data / 'web-provider-selection.json').read_bytes(), provider)
                calls = self.calls()
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(call[:2] == ['launchctl', 'kickstart'] and '-k' not in call for call in calls))
                self.assertTrue(web_card_service.owner_enabled(self.config))
                self.set_pause(target, True)

    def test_all_start_keeps_review_correction_and_local_pauses(self):
        before = self.capture(except_for=('fetch', 'cards', 'watcher'))
        continuous_start.start(self.config, target='all')
        self.assert_preserved(before)
        self.assertEqual(len(self.calls()), 3)
        self.assertFalse(pause_decision(self.config, 'card_review').allowed)
        self.assertFalse(pause_decision(self.config, 'card_correction').allowed)

    def test_start_requests_browser_from_shared_owner_without_separate_cdp(self):
        result=continuous_start.start(self.config, open_browser=True, target='cards')
        self.assertEqual(len(self.calls()),2)
        self.assertTrue(result['browser']['owner_requested'])
        request=json.loads((self.data/'browser-start-request.json').read_text())
        self.assertEqual(request['state'],'pending')
        self.assertEqual(request['target'],'cards')
        self.assertTrue(json.loads((self.data/'shared-window-maintenance-request.json').read_text())['ensure_page'])

    def test_stop_cards_keeps_shared_owner_watcher_and_other_lanes(self):
        for survivor in ('review', 'correction'):
            with self.subTest(survivor=survivor):
                self.set_pause('cards', False)
                self.set_pause(survivor, False)
                self.write('web-card-service.json', {'pid': 98765, 'token': 'owned'})
                self.run.reset_mock(); self.alive.reset_mock()
                before = self.capture(except_for=('cards',))
                result = continuous_start.stop(self.config, target='cards')
                self.assert_preserved(before)
                self.assertTrue(result['web_cards']['shared_owner_kept'])
                self.assertEqual(result['web_cards']['state'], 'paused_by_user')
                self.assertTrue(web_card_service.owner_enabled(self.config))
                self.run.assert_not_called(); self.alive.assert_not_called()
                self.assertFalse((self.data / 'web-card-stop.json').exists())
                self.set_pause(survivor, True)

    def test_stop_review_or_correction_keeps_cards_and_never_pauses_cards(self):
        self.set_pause('cards', False)
        for target in ('review', 'correction'):
            with self.subTest(target=target):
                self.set_pause(target, False)
                before = self.capture(except_for=(target,))
                self.run.reset_mock(); self.alive.reset_mock()
                result = continuous_start.stop(self.config, target=target)
                self.assert_preserved(before)
                self.assertTrue(result[target]['shared_owner_kept'])
                self.run.assert_not_called(); self.alive.assert_not_called()
                self.fetch_stop.assert_not_called()

    def test_last_web_lane_stops_only_the_original_owner_and_watcher(self):
        for target in ('review', 'correction'):
            with self.subTest(target=target):
                self.set_pause(target, False)
                self.run.reset_mock()
                before = self.capture(except_for=(target, 'watcher'))
                continuous_start.stop(self.config, target=target)
                self.assert_preserved(before)
                self.assertFalse(web_card_service.owner_enabled(self.config))
                self.assertTrue(json.loads((self.data / self.controls['watcher']).read_text())['paused_by_user'])
                calls = self.calls()
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(call[:3] == ['launchctl', 'kill', 'SIGTERM'] for call in calls))
                self.assertEqual({call[3].rsplit('/', 1)[-1] for call in calls},
                                 {'local.paper.web-cards', 'local.paper.web-tab-watch'})
                self.assertEqual(json.loads((self.data / 'web-card-stop.json').read_text()),
                                 {'pid': 98765, 'token': 'owned'})
                self.fetch_stop.assert_not_called()

    def test_last_lane_with_unknown_owner_identity_never_guesses_a_stop_request(self):
        self.set_pause('review', False)
        with patch('cards.web_card_service.status', return_value={'alive': True, 'pid': 98765, 'token': ''}):
            continuous_start.stop(self.config, target='review')
        self.assertFalse((self.data / 'web-card-stop.json').exists())
        self.assertTrue(json.loads((self.data / self.controls['cards']).read_text())['paused_by_user'])

    def test_all_stop_keeps_shared_owner_when_review_is_authorized(self):
        self.set_pause('fetch', False); self.set_pause('cards', False); self.set_pause('review', False)
        self.write('fetch-service.json', {'pid': 45678})
        self.write('web-card-service.json', {'pid': 98765, 'token': 'owned'})
        before = self.capture(except_for=('fetch', 'cards'))
        result = continuous_start.stop(self.config, target='all')
        self.assert_preserved(before)
        self.assertTrue(result['web_cards']['shared_owner_kept'])
        self.assertEqual(len(self.calls()), 1)
        self.assertTrue(self.calls()[0][3].endswith('/local.paper.fetch'))
        self.assertTrue(all(call.args == (45678,) for call in self.alive.call_args_list))

    def test_isolated_or_disabled_new_workflow_is_rejected_before_mutation(self):
        original = self.capture()
        isolated = {**self.config, 'catalog_path': str(self.root / 'other/catalog.sqlite3')}
        with self.assertRaises(ValueError):continuous_start.start(isolated, target='review')
        disabled = copy.deepcopy(self.config); disabled['card_correction']['enabled'] = False
        with self.assertRaises(ValueError):continuous_start.start(disabled, target='correction')
        with self.assertRaises(ValueError):continuous_start.stop(self.config, target='unknown')
        self.assert_preserved(original)
        self.run.assert_not_called()

    def test_missing_provider_selection_is_not_initialized_by_new_lane_start(self):
        (self.data / 'web-provider-selection.json').unlink()
        continuous_start.start(self.config, target='review')
        self.assertFalse((self.data / 'web-provider-selection.json').exists())
        self.assertTrue(web_card_service.owner_enabled(self.config))


if __name__ == '__main__':
    unittest.main()
