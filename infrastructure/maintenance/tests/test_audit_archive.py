import json
from core.api import paths__WorkspacePath as Path
import tempfile
import unittest
from maintenance.audit_archive import capture, verify


class ImmutableAuditArchive(unittest.TestCase):
    def test_snapshot_survives_original_change_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'data/example/manifest.json';source.parent.mkdir(parents=True);source.write_text('{"hash":"old"}')
            index=capture(['data/example/manifest.json'],'baseline',root)
            source.write_text('{"hash":"new"}')
            self.assertEqual(verify(root),1)
            with self.assertRaises(ValueError):capture(['data/example/manifest.json'],'baseline',root)
            entry=json.loads(index.read_text())['entries'][0]
            (index.parent/entry['object']).write_text('tampered')
            with self.assertRaises(ValueError):verify(root)

    def test_runtime_control_cannot_enter_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'data').mkdir();(root/'data/web-card-control.json').write_text('{}')
            with self.assertRaises(ValueError):capture(['data/web-card-control.json'],'runtime',root)
