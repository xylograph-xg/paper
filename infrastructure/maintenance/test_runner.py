"""Discover real component tests, checking their source and reporting coverage gaps."""
from core.api import paths__workspace_root as _workspace_root
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(_workspace_root()).resolve()
PROJECTS = ('fetch', 'cards', 'review', 'correction', 'reading', 'browser',
            'core', 'workbench', 'maintenance', 'read', 'article',
            'codex_desktop_chat', 'desktop_widget', 'reports', 'crawler', 'literature', 'oled_formulas', 'codex_web_client')
SUMMARY_PREFIX = 'PAPER_TEST_SUMMARY='


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def source_errors(tests, root, projects):
    """Native paths are intentional: compatibility relocation must not hide imports."""
    roots = [root, (root.parent / "tools/literature_explorer/literature_explorer").resolve()]
    roots.extend((root / item["path"]).resolve() for item in projects.values() if "path" in item)
    errors = []
    for test in tests:
        if isinstance(test, unittest.loader._FailedTest):
            continue
        module = sys.modules.get(type(test).__module__)
        method = getattr(test, test._testMethodName)
        filenames = [getattr(module, '__file__', None),
                     getattr(getattr(method, '__code__', None), 'co_filename', None)]
        for filename in filenames:
            if not filename or not any(Path(filename).resolve().is_relative_to(base) for base in roots):
                errors.append(f'{test.id()}: source outside workspace: {filename}')
    for name, module in list(sys.modules.items()):
        if name.split('.')[0] in set(projects) | {'pipeline'}:
            filename = getattr(module, '__file__', None)
            if filename and not any(Path(filename).resolve().is_relative_to(base) for base in roots):
                errors.append(f'{name}: component outside workspace: {filename}')
    return sorted(set(errors))


def discover(project, root, projects, pattern):
    folder = root / projects.get(project, {}).get('path', project) / 'tests'
    folder = Path(os.path.normpath(folder))
    if project == 'crawler':
        folder = root.parent / 'tools/literature_explorer/literature_explorer' / 'tests'
    summary = {'project': project, 'root': str(folder), 'status': 'MISSING',
               'test_slots': 0, 'unique_ids': 0, 'duplicate_ids': 0,
               'class_defined_elsewhere': 0, 'tests_run': 0, 'failures': 0,
               'errors': 0, 'skipped': 0, 'loader_errors': [], 'source_errors': []}
    if not folder.is_dir():
        return None, summary
    loader = unittest.TestLoader()
    try:
        suite = loader.discover(str(folder), pattern=pattern,
                               top_level_dir=str(folder if project == 'crawler'
                                                 else folder.parent.parent))
    except (ImportError, OSError, ValueError) as exc:
        summary.update(status='DISCOVERY_FAILED', loader_errors=[str(exc)])
        return None, summary
    tests = list(cases(suite))
    ids = [test.id() for test in tests]
    summary.update(test_slots=len(ids), unique_ids=len(set(ids)),
                   duplicate_ids=len(ids)-len(set(ids)), loader_errors=loader.errors[:])
    summary['class_defined_elsewhere'] = sum(
        not Path(getattr(sys.modules.get(type(test).__module__), '__file__',
                         str(folder))).resolve().is_relative_to(folder)
        for test in tests if not isinstance(test, unittest.loader._FailedTest))
    summary['source_errors'] = source_errors(tests, root, projects)
    summary['status'] = ('DISCOVERY_FAILED' if loader.errors else
                         'SOURCE_FAILED' if summary['source_errors'] else
                         'DISCOVERED' if tests else 'EMPTY')
    return (suite if summary['status'] == 'DISCOVERED' else None), summary


def finish(summary, result):
    summary.update(tests_run=result.testsRun, failures=len(result.failures),
                   errors=len(result.errors), skipped=len(result.skipped),
                   status='PASS' if result.wasSuccessful() else 'FAILED')


def crawler_run(root, pattern):
    """The crawler's bare config/models imports stay in a separate interpreter."""
    explorer = root.parent / 'tools/literature_explorer/literature_explorer'
    env = dict(os.environ, PAPER_WORKSPACE_ROOT=str(root))
    command = [sys.executable, str(root/'infrastructure/maintenance/test_runner.py'),
               '--crawler-child', '--pattern', pattern]
    result = subprocess.run(command, cwd=explorer, env=env,
                            text=True, capture_output=True)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    reports = [line[len(SUMMARY_PREFIX):] for line in result.stdout.splitlines()
               if line.startswith(SUMMARY_PREFIX)]
    try:
        summary = json.loads(reports[0]) if len(reports) == 1 else None
        if (not isinstance(summary, dict) or summary.get('project') != 'crawler'
                or summary.get('root') != str(explorer/'tests')
                or any(type(summary.get(k)) is not int or summary[k] < 0 for k in
                       ('test_slots', 'unique_ids', 'duplicate_ids', 'tests_run',
                        'failures', 'errors', 'skipped'))
                or summary['unique_ids'] > summary['test_slots']
                or summary['duplicate_ids'] != summary['test_slots']-summary['unique_ids']
                or summary['skipped'] > summary['tests_run']
                or type(summary.get('loader_errors')) is not list
                or type(summary.get('source_errors')) is not list
                or (summary.get('status') == 'PASS' and
                    (result.returncode != 0 or summary['failures'] or summary['errors']
                     or summary['loader_errors'] or summary['source_errors']
                     or summary['tests_run'] != summary['test_slots']))):
            raise ValueError('missing, inconsistent or invalid crawler receipt')
        return summary, result.returncode == 0 and summary.get('status') == 'PASS'
    except (ValueError, TypeError, KeyError) as exc:
        return {'project': 'crawler', 'status': 'RECEIPT_FAILED', 'error': str(exc)}, False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', choices=PROJECTS, action='append')
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('--crawler-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = ROOT
    projects = json.loads((root/'workspace.json').read_text())['projects']
    sys.path.insert(0, str(root))
    if args.crawler_child:
        sys.path.insert(0, str(root.parent/'tools/literature_explorer/literature_explorer'))
        crawler_projects = {**projects, **{k: {} for k in
            ('config', 'connectors', 'discovery', 'models', 'ranking', 'storage')}}
        suite, summary = discover('crawler', root, crawler_projects, args.pattern)
        if suite is not None:
            finish(summary, unittest.TextTestRunner(verbosity=1).run(suite))
        print(SUMMARY_PREFIX+json.dumps(summary, ensure_ascii=False))
        return 0 if summary['status'] == 'PASS' else 1

    combined = unittest.TestSuite()
    summaries = []
    suites = []
    all_ids = []
    selected = args.project or PROJECTS
    for project in selected:
        if project == 'crawler':
            continue
        suite, summary = discover(project, root, projects, args.pattern)
        summaries.append(summary)
        if suite is not None:
            tests = list(cases(suite))
            all_ids.extend(test.id() for test in tests)
            suites.append((summary, tests))
            combined.addTests(suite)
    # Discovering later components can import earlier packages from a stale root.
    provenance = source_errors(list(cases(combined)), root, projects)
    if provenance:
        for summary, _ in suites:
            summary.update(status='SOURCE_FAILED', source_errors=provenance)
    elif suites:
        result = unittest.TextTestRunner(verbosity=1).run(combined)
        failed = Counter(id(test) for test, _ in result.failures)
        errored = Counter(id(test) for test, _ in result.errors)
        skipped = Counter(id(test) for test, _ in result.skipped)
        # Class/module setup failures have synthetic holders rather than test ids;
        # retain the authoritative overall result instead of inventing per-case PASS.
        for summary, tests in suites:
            summary.update(status='EXECUTED', tests_run=None,
                           failures=sum(failed[id(t)] for t in tests),
                           errors=sum(errored[id(t)] for t in tests),
                           skipped=sum(skipped[id(t)] for t in tests))
        executed_ok = result.wasSuccessful()
        overall_result = {'tests_run': result.testsRun, 'failures': len(result.failures),
                          'errors': len(result.errors), 'skipped': len(result.skipped)}
    else:
        overall_result = {'tests_run': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    if provenance:
        overall_result = {'tests_run': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    ok = not provenance and not any(s['status'] in
        ('MISSING', 'EMPTY', 'DISCOVERY_FAILED', 'SOURCE_FAILED') for s in summaries)
    ok = ok and not overall_result['failures'] and not overall_result['errors']
    if suites and not provenance:
        ok = ok and executed_ok
    for project in selected:
        if project == 'crawler':
            try:
                summary, passed = crawler_run(root, args.pattern)
            except OSError as exc:
                summary, passed = {'project': project, 'status': 'DISCOVERY_FAILED',
                                   'error': str(exc)}, False
            summaries.append(summary)
            ok = ok and passed
    crawler = [s for s in summaries if s['project'] == 'crawler']
    report = {'status': 'PASS' if ok else 'INCOMPLETE_OR_FAILED',
              'workspace_root': str(root), 'python': sys.executable,
              'pycache_prefix': sys.pycache_prefix, 'components': summaries,
              'test_slots': len(all_ids)+sum(s.get('test_slots', 0) for s in crawler),
              'unique_ids': len(set(all_ids))+sum(s.get('unique_ids', 0) for s in crawler),
              'duplicate_ids': len(all_ids)-len(set(all_ids))+sum(s.get('duplicate_ids', 0) for s in crawler),
              **{k: overall_result[k]+sum(s.get(k, 0) for s in crawler)
                 for k in ('tests_run', 'failures', 'errors', 'skipped')},
              'missing_components': [s['project'] for s in summaries if s['status'] == 'MISSING']}
    print(SUMMARY_PREFIX+json.dumps(report, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
