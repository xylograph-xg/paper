"""Discovery is separate from execution; missing and foreign sources fail closed."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from maintenance import test_runner as runner


class Discovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = {'review': {'path': 'review'}}
        (self.root/'workspace.json').write_text(json.dumps({'projects': self.projects}))

    def test_missing_directory_is_not_a_pass(self):
        suite, info = runner.discover('review', self.root, self.projects, 'test_*.py')
        self.assertIsNone(suite)
        self.assertEqual(info['status'], 'MISSING')
        self.assertEqual(info['tests_run'], 0)

    def test_empty_directory_is_not_a_pass(self):
        (self.root/'review/tests').mkdir(parents=True)
        loader = Mock(errors=[])
        loader.discover.return_value = unittest.TestSuite()
        with patch.object(runner.unittest, 'TestLoader', return_value=loader), \
             patch.object(runner, 'source_errors', return_value=[]):
            suite, info = runner.discover('review', self.root, self.projects, 'test_*.py')
        self.assertIsNone(suite)
        self.assertEqual(info['status'], 'EMPTY')

    def test_loader_errors_block_execution(self):
        (self.root/'review/tests').mkdir(parents=True)
        loader = Mock(errors=['broken import'])
        loader.discover.return_value = unittest.TestSuite()
        with patch.object(runner.unittest, 'TestLoader', return_value=loader):
            suite, info = runner.discover('review', self.root, self.projects, 'test_*.py')
        self.assertIsNone(suite)
        self.assertEqual(info['loader_errors'], ['broken import'])

    def test_discovery_exception_is_reported(self):
        (self.root/'review/tests').mkdir(parents=True)
        loader = Mock(errors=[])
        loader.discover.side_effect = ImportError('wrong directory')
        with patch.object(runner.unittest, 'TestLoader', return_value=loader):
            suite, info = runner.discover('review', self.root, self.projects, 'test_*.py')
        self.assertIsNone(suite)
        self.assertEqual(info['status'], 'DISCOVERY_FAILED')

    def test_foreign_test_and_method_paths_are_rejected(self):
        test = Discovery('test_missing_directory_is_not_a_pass')
        self.assertTrue(runner.source_errors([test], self.root, {}))

    def test_same_workspace_inherited_methods_remain_legal(self):
        class Child(Discovery):pass
        test = Child('test_missing_directory_is_not_a_pass')
        self.assertEqual(runner.source_errors([test], runner.ROOT, {}), [])

    def test_foreign_component_package_is_rejected(self):
        fake = SimpleNamespace(__file__='/outside/review/__init__.py')
        with patch.dict(sys.modules, {'review.foreign_fixture': fake}):
            self.assertTrue(runner.source_errors([], self.root, {'review': {}}))

    def test_duplicate_ids_are_counted_without_deduplication(self):
        (self.root/'review/tests').mkdir(parents=True)
        tests = [Discovery('test_empty_directory_is_not_a_pass') for _ in range(2)]
        loader = Mock(errors=[])
        loader.discover.return_value = unittest.TestSuite(tests)
        with patch.object(runner.unittest, 'TestLoader', return_value=loader), \
             patch.object(runner, 'source_errors', return_value=[]):
            suite, info = runner.discover('review', self.root, self.projects, 'special*.py')
        self.assertEqual(info['test_slots'], 2)
        self.assertEqual(info['unique_ids'], 1)
        self.assertEqual(info['duplicate_ids'], 1)
        self.assertEqual(suite.countTestCases(), 2)
        loader.discover.assert_called_once_with(str(self.root/'review/tests'),
            pattern='special*.py', top_level_dir=str(self.root))

    def receipt(self, **changes):
        value = {'project': 'crawler', 'root': str(self.root.parent/'tools/literature_explorer/literature_explorer/tests'),
                 'status': 'PASS', 'test_slots': 20, 'unique_ids': 20, 'duplicate_ids': 0,
                 'tests_run': 20, 'failures': 0, 'errors': 0, 'skipped': 0,
                 'loader_errors': [], 'source_errors': []}
        value.update(changes)
        return runner.SUMMARY_PREFIX+json.dumps(value)+'\n'

    def test_crawler_uses_its_own_python_cwd_and_workspace(self):
        result = subprocess.CompletedProcess([], 0, self.receipt(), 'actual stderr\n')
        with patch.object(runner.subprocess, 'run', return_value=result) as run, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            info, ok = runner.crawler_run(self.root, 'custom*.py')
        self.assertTrue(ok)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], sys.executable)
        self.assertIn('--crawler-child', args[0])
        self.assertEqual(args[0][-1], 'custom*.py')
        self.assertEqual(kwargs['cwd'], self.root.parent/'tools/literature_explorer/literature_explorer')
        self.assertEqual(kwargs['env']['PAPER_WORKSPACE_ROOT'], str(self.root))
        self.assertEqual(info['tests_run'], 20)

    def test_crawler_bad_receipts_and_failure_never_pass(self):
        for stdout, code in [('OK\n', 0), ('PAPER_TEST_SUMMARY=broken\n', 0),
                             (self.receipt()*2, 0), (self.receipt(), 1),
                             (self.receipt(tests_run=0), 0), (self.receipt(errors=1), 0),
                             (self.receipt(test_slots=-1), 0),
                             (self.receipt(unique_ids=21), 0),
                             (self.receipt(duplicate_ids=1), 0),
                             (self.receipt(skipped=21), 0),
                             (self.receipt(root='/wrong/tests'), 0)]:
            with self.subTest(stdout=stdout, code=code), \
                 patch.object(runner.subprocess, 'run', return_value=
                     subprocess.CompletedProcess([], code, stdout, '')), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                _, ok = runner.crawler_run(self.root, 'test_*.py')
                self.assertFalse(ok)

    def test_targeting_missing_component_returns_nonzero(self):
        output = io.StringIO()
        with patch.object(runner, 'ROOT', self.root), contextlib.redirect_stdout(output):
            self.assertEqual(runner.main(['--project', 'review']), 1)
        report = json.loads(output.getvalue().split(runner.SUMMARY_PREFIX)[-1])
        self.assertEqual(report['missing_components'], ['review'])
        self.assertEqual(report['tests_run'], 0)

    def test_multiple_projects_and_pattern_are_not_lost(self):
        output = io.StringIO()
        with patch.object(runner, 'ROOT', self.root), \
             patch.object(runner, 'discover', wraps=runner.discover) as discover, \
             contextlib.redirect_stdout(output):
            self.assertEqual(runner.main(['--project', 'review', '--project', 'correction',
                                         '--pattern', 'special*.py']), 1)
        self.assertEqual([c.args[0] for c in discover.call_args_list], ['review', 'correction'])
        self.assertTrue(all(c.args[-1] == 'special*.py' for c in discover.call_args_list))

    def test_no_test_runs_when_source_validation_fails(self):
        tests = [Discovery('test_empty_directory_is_not_a_pass')]
        info = {'project': 'review', 'status': 'DISCOVERED'}
        with patch.object(runner, 'ROOT', self.root), \
             patch.object(runner, 'discover', return_value=(unittest.TestSuite(tests), info)), \
             patch.object(runner.unittest, 'TextTestRunner') as execute, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(['--project', 'review']), 1)
        execute.assert_not_called()
        self.assertEqual(info['status'], 'SOURCE_FAILED')


if __name__ == '__main__':unittest.main()
