import unittest
from unittest.mock import patch

from cards.web_card_service import code_version
from browser.web_card_pool import owner_error_status


class OwnerRuntimeDiagnostics(unittest.TestCase):
    def test_reports_loaded_limit_when_disk_code_has_a_different_limit(self):
        # Reproduce an old process after the source was changed to support 150.
        with patch('core.concurrency_control.MAX_FETCH', 32):
            captured = code_version()
        self.assertEqual(captured['loaded_concurrency_limits']['fetch'], 32)
        self.assertIn('concurrency_control.py', captured['module_sha256'])
        self.assertIn('catalog.py', captured['module_sha256'])

    def test_failure_preserves_startup_version_and_real_frames_without_activity(self):
        captured = {'loaded_concurrency_limits': {'fetch': 32}, 'captured_at': 1}
        try:
            raise ValueError('并行数量超出允许范围')
        except ValueError as exc:
            status = owner_error_status(12, 'own', exc, preserve=True,
                                        loaded_version=captured)
        self.assertIs(status['code_version'], captured)
        self.assertEqual(status['state'], 'waiting_evidence')
        self.assertIn('test_failure_preserves_startup_version', ''.join(status['error_traceback']))
        self.assertNotIn('workers', status)
        self.assertNotIn('actual_parallel', status)
        self.assertNotIn('uploading_pages', status)

    def test_driver_failure_retains_version_without_claiming_connected(self):
        status = owner_error_status(12, 'own', RuntimeError('connection lost'),
                                    preserve=False, loaded_version={'captured_at': 1})
        self.assertEqual(status['state'], 'waiting_browser')
        self.assertEqual(status['code_version']['captured_at'], 1)


if __name__ == '__main__':
    unittest.main()
