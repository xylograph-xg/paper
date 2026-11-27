"""Regression tests for the 2026-10-17 fetch efficiency repairs."""
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from core.api import paths__WorkspacePath as Path
from fetch.discovery_bridge import discover
from fetch.fetch_policy import classify
from fetch.fetching import discovery_schedule, record_discovery_schedule, schedule_discovery
from fetch.network import failed


class NetworkGuardClassification(unittest.TestCase):
    def test_local_proxy_guard_failure_is_retryable(self):
        for value in ('下载地址指向本机或内网，已拒绝', '连接地址指向本机或内网，已拒绝'):
            self.assertEqual(classify(value), 'transient')
            self.assertEqual(classify(ValueError(value)), 'transient')
        self.assertEqual(classify('html 网页'), 'deterministic')


class AuthCooldownTests(unittest.TestCase):
    def test_401_stays_bounded_instead_of_a_full_day(self):
        with tempfile.TemporaryDirectory() as folder:
            retry_at = 0
            for _ in range(4):
                retry_at = failed('openalex', 401, folder=folder)
            self.assertLess(retry_at, time.time() + 3700)

    def test_403_publisher_block_keeps_the_long_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            retry_at = 0
            for _ in range(3):
                retry_at = failed('pdf:publisher.example', 403, folder=folder)
            self.assertGreater(retry_at, time.time() + 80000)


class DiscoverySeedGateTests(unittest.TestCase):
    def test_one_openalex_cooldown_does_not_emit_one_warning_per_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {'openalex': {'code': 401, 'failures': 3, 'retry_at': time.time() + 3600, 'updated': time.time()}}
            (Path(folder) / 'network-state.json').write_text(json.dumps(state))
            request = {
                'seeds': [{'doi': '10.1000/a', 'title': 'Organic triplet seed'},
                          {'doi': '10.1000/b', 'title': 'Organic emitter seed'}],
                'queries': [], 'positions': {}, 'network': {}, 'preprints': {},
                'discovery_channels': ['seed_related'], 'state_dir': folder,
            }
            output = discover(request)
            self.assertEqual(output['seed_tasks']['10.1000/a']['state'], 'fallback_waiting')
            self.assertEqual(output['seed_tasks']['10.1000/b']['state'], 'fallback_waiting')
            self.assertTrue(any('种子通道暂缓' in warning for warning in output['warnings']))
            self.assertFalse(any('openalex seed:' in warning for warning in output['warnings']))
            self.assertLess(len(output['warnings']), 4)

    def test_seed_rotation_advances_between_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {'openalex': {'code': 401, 'failures': 3, 'retry_at': time.time() + 3600, 'updated': time.time()}}
            (Path(folder) / 'network-state.json').write_text(json.dumps(state))
            first = {'seeds': [{'doi': '10.1000/a', 'title': 'A'}, {'doi': '10.1000/b', 'title': 'B'},
                               {'doi': '10.1000/c', 'title': 'C'}],
                     'queries': [], 'positions': {}, 'network': {}, 'preprints': {},
                     'discovery_channels': ['seed_related'], 'state_dir': folder}
            discover(first)
            rotation = json.loads((Path(folder) / 'seed-rotation.json').read_text())
            self.assertGreater(rotation['offset'], 0)


class DiscoveryBackoffTests(unittest.TestCase):
    def test_empty_runs_back_off_and_a_productive_run_resets(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = type('CatalogStub', (), {'path': Path(folder) / 'catalog.sqlite3'})()
            config = {'fetch_pipeline': {'discovery_interval_seconds': 60,
                                         'discovery_empty_backoff_max_seconds': 3600}}
            first = record_discovery_schedule(catalog, config, [])
            second = record_discovery_schedule(catalog, config, [])
            third = record_discovery_schedule(catalog, config, [])
            self.assertEqual([first['empty_streak'], second['empty_streak'], third['empty_streak']], [1, 2, 3])
            self.assertLess(first['next_allowed_at'], second['next_allowed_at'])
            self.assertLess(second['next_allowed_at'], third['next_allowed_at'])
            productive = record_discovery_schedule(catalog, config, ['job'])
            self.assertEqual(productive['empty_streak'], 0)
            self.assertLessEqual(productive['next_allowed_at'], time.time() + 61)
            self.assertEqual(discovery_schedule(catalog)['empty_streak'], 0)


class ScheduleGateTests(unittest.TestCase):
    def test_future_backoff_prevents_a_new_discovery_job(self):
        from fetch.tests.test_fetch_pipeline import FetchFixtures
        case = FetchFixtures('run')
        case.setUp()
        try:
            (case.root / 'discovery-schedule.json').write_text(json.dumps(
                {'empty_streak': 3, 'next_allowed_at': time.time() + 300, 'updated': time.time()}))
            self.assertIsNone(schedule_discovery(case.catalog, case.config))
            with case.catalog.connect() as db:
                self.assertEqual(db.execute("select count(*) from jobs where kind='discover'").fetchone()[0], 0)
            (case.root / 'discovery-schedule.json').write_text(json.dumps(
                {'empty_streak': 0, 'next_allowed_at': 0, 'updated': time.time()}))
            with patch('fetch.fetching.services.archive_root'):
                self.assertTrue(schedule_discovery(case.catalog, case.config)['job_id'])
        finally:
            case.tearDown()


if __name__ == '__main__':
    unittest.main()
