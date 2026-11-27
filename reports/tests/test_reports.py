import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reports_api_under_test', ROOT / 'api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

class ReportsTests(unittest.TestCase):
    def test_all_registered_bytes(self):
        entries = api.list_reports()
        self.assertEqual(len(entries), len({e['path'] for e in entries}))
        self.assertTrue(entries)
        for entry in entries:
            api.read_report(entry['path'])
        self.assertFalse(any(e['path'].endswith('.DS_Store') for e in entries))

    def test_unknown_and_traversal(self):
        for name in ('missing', '../pyproject.toml', '../../etc/passwd'):
            with self.assertRaises(api.ReportNotFoundError):
                api.read_report(name)

    def test_manifest_damage_and_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(api, 'ROOT', root):
                for content in ('{', '{"entries":{}}', json.dumps({'entries':[{'path':'../x','sha256':'0'*64}]}), json.dumps({'entries':[{'path':'x','sha256':'0'*64}]*2})):
                    (root / 'interface.json').write_text(content)
                    with self.assertRaises(api.ReportManifestError):
                        api.list_reports()

    def test_missing_corrupt_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'interface.json').write_text(json.dumps({'entries':[{'path':'x','sha256':'0'*64}]}))
            with patch.object(api, 'ROOT', root):
                with self.assertRaises(api.ReportNotFoundError): api.read_report('x')
                (root / 'x').write_bytes(b'changed')
                with self.assertRaises(api.ReportIntegrityError): api.read_report('x')
                (root / 'x').unlink()
                (root / 'x').symlink_to(ROOT / 'api.py')
                with self.assertRaises(api.ReportIntegrityError): api.read_report('x')

    def test_historical_link(self):
        source = 'workflow-audits/新旧审计合并整改_20261006.md'
        with self.assertRaises(api.ReportNotFoundError):
            api.resolve_report_link(source, '../独立技术审计报告_20261006_0310.md')
        source='__init__.py'
        for link in ('https://example.com/x', '../other/project.py', '/etc/passwd'):
            self.assertIsNone(api.resolve_report_link(source, link))
        with patch.object(api, 'list_reports', return_value=[{'path':source}, {'path':'a/x.md'}, {'path':'b/x.md'}]):
            self.assertIsNone(api.resolve_report_link(source, '../x.md'))

if __name__ == '__main__': unittest.main()
