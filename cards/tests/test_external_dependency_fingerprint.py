"""S001 external kernel fingerprint: registration is the source of truth.

Offline only. Temporary registries and synthetic kernel files; no owner, no CDP,
no network and no control write.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from cards import web_card_service as service


def sha(text):
    return hashlib.sha256(text).hexdigest()


class ExternalFingerprint(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.external = self.root / 'kernel'
        (self.external / 'web_gpt').mkdir(parents=True)
        for name in ('core.py', '__init__.py', 'zip_uploads.py'):
            (self.external / 'web_gpt' / name).write_text('synthetic ' + name)
        (self.root / 'codex_desktop_chat').mkdir()
        (self.root / 'codex_desktop_chat' / 'bundles.py').write_text('synthetic packer')
        projects = {'cards': 'cards', 'browser': 'browser', 'core': 'core',
                    'review': 'review', 'correction': 'correction', 'reading': 'workbench/reading'}
        for folder in projects.values():
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / projects['reading'] / 'manual_literature.py').write_text('synthetic intake')
        (self.root / 'workspace.json').write_text(json.dumps(
            {'projects': {name: {'path': path} for name, path in projects.items()}}))
        registry = self.root / 'infrastructure'
        registry.mkdir()
        self.registry = registry / 'tool-dependencies.json'
        self.write_registry(self.external)
        self.env = patch.dict(__import__('os').environ, {'WEB_GPT_IMPORT_ROOT': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.workspace = patch('core.api.paths__workspace_root', return_value=self.root)
        self.workspace.start()
        self.addCleanup(self.workspace.stop)
        modules = patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        # A sibling module may already have imported the real kernel through
        # mock.patch('web_gpt.core....'); this guard must describe the temporary
        # registration below, not whatever an earlier test left loaded here.
        sys.modules.pop('web_gpt.core', None)

    def write_registry(self, source_dir, import_root=None):
        entry = {'id': 'web_gpt', 'source_dir': str(source_dir / 'web_gpt')}
        if import_root is not None:
            entry['python_import_root'] = str(import_root)
        self.registry.write_text(json.dumps({'tools': [entry]}))

    def test_registered_kernel_files_are_hashed_from_the_registered_path(self):
        report = service.external_dependencies()
        self.assertEqual(report['status'], 'ok', report['errors'])
        self.assertEqual(report['hashes']['dependency:web_gpt.core'],
                         sha((self.external / 'web_gpt' / 'core.py').read_bytes()))
        self.assertEqual(report['files']['dependency:codex_desktop_chat.bundles'],
                         str((self.root / 'codex_desktop_chat' / 'bundles.py').resolve()))
        self.assertTrue(report['sdk_version'])
        self.assertEqual(report['hashes']['dependency:playwright.sdk'],
                         sha(report['sdk_version'].encode()))

    def test_a_single_byte_change_in_one_external_file_changes_the_fingerprint(self):
        before = service.external_dependencies()['hashes']['dependency:web_gpt.core']
        (self.external / 'web_gpt' / 'core.py').write_text('synthetic core.py drift')
        after = service.external_dependencies()['hashes']['dependency:web_gpt.core']
        self.assertNotEqual(before, after)
        merged = service.code_version()['module_sha256']
        self.assertEqual(merged['dependency:web_gpt.core'], after)
        self.assertNotIn(before, set(merged.values()))

    def test_environment_override_that_is_not_the_registration_is_incomplete_not_silent(self):
        with patch.dict(__import__('os').environ, {'WEB_GPT_IMPORT_ROOT': str(self.root / 'elsewhere')}):
            report = service.external_dependencies()
        self.assertEqual(report['status'], 'incomplete')
        self.assertTrue(any('WEB_GPT_IMPORT_ROOT' in item for item in report['errors']))

    def test_missing_registration_is_incomplete_without_raising(self):
        self.registry.write_text(json.dumps({'tools': []}))
        report = service.external_dependencies()
        self.assertEqual(report['status'], 'incomplete')
        self.assertTrue(report['hashes'], 'a stable key must still exist for comparison')

    def test_loaded_module_outside_the_registered_path_is_reported(self):
        import sys
        fake = type(sys)('web_gpt.core')
        fake.__file__ = str(self.root / 'elsewhere' / 'core.py')
        with patch.dict(sys.modules, {'web_gpt.core': fake}):
            report = service.external_dependencies()
        self.assertEqual(report['status'], 'incomplete')
        self.assertTrue(any('实际加载内核' in item for item in report['errors']))

    def test_code_version_publishes_the_evidence_the_supervisor_compares(self):
        version = service.code_version()
        block = version['external_dependencies']
        self.assertEqual(block['status'], 'ok', block['errors'])
        self.assertNotIn('hashes', block, 'hashes live in module_sha256 so the existing comparison covers them')
        for key in ('dependency:web_gpt.core', 'dependency:web_gpt.package',
                    'dependency:web_gpt.zip_uploads', 'dependency:codex_desktop_chat.bundles',
                    'dependency:playwright.sdk'):
            self.assertIn(key, version['module_sha256'])
        self.assertEqual(version['module_sha256']['workbench/reading/manual_literature.py'],sha(b'synthetic intake'))


if __name__ == '__main__':
    unittest.main()
