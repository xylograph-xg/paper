"""Read-only task rows show live activity separately from reserved capacity."""
import json
import os
import tempfile
import time
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from desktop_widget.snapshot import snapshot


class FourWorkflowSnapshot(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root/'data'; self.data.mkdir()
        config_folder = self.root/'config'; config_folder.mkdir()
        self.config = {'catalog_path': str(self.data/'catalog.sqlite3'),
            'web_cards': {'enabled': True, 'max_parallel_jobs': 20, 'min_reserved_pages': 8,
                          'shared_window': {'enabled': True}},
            'card_review': {'enabled': True, 'parallel_jobs': 4},
            'card_correction': {'enabled': True, 'parallel_jobs': 4}}
        self.write(config_folder/'first_round.json', self.config)
        self.progress = {'downloaded': 40, 'total': 100, 'active_fetch': 5, 'pending': 20,
                         'blocked': 0, 'cards': 7, 'last_card_completed': None}
        self.write(self.data/'fetch-service.json', {'pid': os.getpid(), 'state': 'running', 'updated': time.time()})

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value))

    def service(self, actual=None, **fields):
        value = {'pid': os.getpid(), 'state': 'running', 'updated': time.time(),
                 'workers': 19, 'review_workers': 13, 'correction_workers': 11,
                 'pool_busy': 20, 'fixed_slots': 20, 'live_fixed_slots': 20,
                 'slot_budget': {'cards': 8, 'review': 4, 'correction': 4},
                 'reserved_card_pages': 8, 'actual_parallel_checked_at': time.time()}
        if actual is not None:
            value['actual_parallel'] = actual
        value.update(fields)
        self.write(self.data/'web-card-service.json', value)

    def rows(self):
        with patch('core.continuous_status.status', return_value=self.progress):
            value = snapshot(self.root)
        return {row['concurrencyTarget']: row for row in value['rows'] if row.get('concurrencyTarget')}

    def test_four_rows_have_requested_order_and_separate_card_reservation(self):
        self.service({'cards': 3, 'review': 2, 'correction': 1})
        rows = self.rows()
        self.assertEqual(list(rows), ['fetch', 'cards', 'review', 'correction'])
        self.assertEqual([rows[lane]['group'] for lane in rows],
                         ['paper · 拉取', 'paper · 制卡', 'paper · 核验', 'paper · 修正'])
        self.assertEqual(rows['cards']['reservedPages'], 8)
        self.assertEqual(rows['cards']['concurrencyTarget'], 'cards')
        self.assertEqual(rows['cards']['actualParallel'], 3)
        self.assertNotEqual(rows['cards']['actualParallel'], rows['cards']['reservedPages'])

    def test_actual_parallel_uses_confirmed_map_not_menu_worker_or_slot_budget(self):
        self.service({'cards': 3, 'review': 2, 'correction': 1})
        rows = self.rows()
        for lane, expected in (('cards', 3), ('review', 2), ('correction', 1)):
            with self.subTest(lane=lane):
                self.assertEqual(rows[lane]['actualParallel'], expected)
                self.assertIs(rows[lane]['actualParallelConfirmed'], True)

    def test_fetch_actual_parallel_comes_from_current_work_not_configured_limit(self):
        self.service({'cards': 0, 'review': 0, 'correction': 0})
        fetch = self.rows()['fetch']
        self.assertEqual(fetch['actualParallel'], self.progress['active_fetch'])
        self.assertIs(fetch['actualParallelConfirmed'], True)

    def test_stale_fetch_status_is_unobserved_without_reusing_old_job_count(self):
        self.service({'cards': 0, 'review': 0, 'correction': 0})
        self.write(self.data/'fetch-service.json',
                   {'pid': os.getpid(), 'state': 'running', 'updated': time.time() - 120})
        fetch = self.rows()['fetch']
        self.assertIsNone(fetch['actualParallel'])
        self.assertIs(fetch['actualParallelConfirmed'], False)

    def test_confirmed_zero_does_not_fall_back_to_fixed_page_count(self):
        self.service({'cards': 0, 'review': 0, 'correction': 0})
        rows = self.rows()
        for lane in ('cards', 'review', 'correction'):
            self.assertEqual(rows[lane]['actualParallel'], 0)
            self.assertIs(rows[lane]['actualParallelConfirmed'], True)
        self.assertEqual(rows['cards']['reservedPages'], 8)

    def test_missing_activity_map_is_unobserved_without_invented_zero(self):
        self.service()
        rows = self.rows()
        for lane in ('cards', 'review', 'correction'):
            self.assertIsNone(rows[lane]['actualParallel'])
            self.assertIs(rows[lane]['actualParallelConfirmed'], False)

    def test_stale_owner_heartbeat_does_not_claim_live_parallelism(self):
        stale = time.time() - 120
        self.service({'cards': 3, 'review': 2, 'correction': 1},
                     updated=stale, actual_parallel_checked_at=stale)
        rows = self.rows()
        for lane in ('cards', 'review', 'correction'):
            self.assertIsNone(rows[lane]['actualParallel'])
            self.assertIs(rows[lane]['actualParallelConfirmed'], False)

    def test_stopped_owner_does_not_claim_remote_requests_finished(self):
        self.service({'cards': 3, 'review': 2, 'correction': 1}, pid=-1, state='stopped')
        rows = self.rows()
        for lane in ('cards', 'review', 'correction'):
            self.assertIsNone(rows[lane]['actualParallel'])
            self.assertIs(rows[lane]['actualParallelConfirmed'], False)

    def test_paused_lanes_keep_confirmed_original_activity_until_it_finishes(self):
        self.service({'cards': 3, 'review': 2, 'correction': 1})
        for lane, filename in (('cards', 'web-card-control.json'),
                               ('review', 'card-review-control.json'),
                               ('correction', 'card-correction-control.json')):
            self.write(self.data/filename, {'paused_by_user': True})
        rows = self.rows()
        for lane, expected in (('cards', 3), ('review', 2), ('correction', 1)):
            self.assertEqual(rows[lane]['state'], '已暂停')
            self.assertEqual(rows[lane]['actualParallel'], expected)
            self.assertIs(rows[lane]['actualParallelConfirmed'], True)

    def test_correction_activity_never_increases_card_count(self):
        self.service({'cards': 0, 'review': 1, 'correction': 7})
        rows = self.rows()
        self.assertEqual(rows['cards']['actualParallel'], 0)
        self.assertEqual(rows['review']['actualParallel'], 1)
        self.assertEqual(rows['correction']['actualParallel'], 7)

    def test_read_only_snapshot_preserves_runtime_control_and_does_not_create_database(self):
        self.service({'cards': 3, 'review': 2, 'correction': 1})
        control = self.data/'card-correction-control.json'
        self.write(control, {'paused_by_user': True, 'reason': 'user pause'})
        before = {path: path.read_bytes() for path in self.root.rglob('*.json')}
        self.rows()
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*.json')}, before)
        self.assertFalse((self.data/'catalog.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
