"""Access immutable old receipts after physical directory migration."""
import json
from pathlib import Path as NativePath
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path, paths__workspace_root as workspace_root

class WorkspacePaths(unittest.TestCase):
    def test_old_absolute_receipt_path_reads_same_bytes_without_rewriting(self):
        root=workspace_root();folder=root/'infrastructure/data'
        folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as td:
            current=NativePath(td)/'receipt.json';body=b'{"state":"submitted","hash":"original"}'
            current.write_bytes(body)
            suffix=current.relative_to(NativePath(root/'infrastructure/data'))
            legacy=NativePath('/Users/xiaoyanhao/project/paper/data')/suffix
            self.assertEqual(Path(legacy).read_bytes(),body)
            self.assertEqual(current.read_bytes(),body)
    def test_nested_package_path_resolves_once(self):
        root=workspace_root()
        self.assertEqual(root/'core/catalog.py',root/'infrastructure/core/catalog.py')
        self.assertTrue((root/'core/catalog.py').is_file())
        self.assertEqual(root.joinpath('read','app','parser.py'),root/'workbench/read/app/parser.py')
    def test_unrelated_external_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            p=NativePath(td)/'data/receipt.json'
            self.assertEqual(str(Path(p)),str(p))
        similar=NativePath('/Users/xiaoyanhao/project/paper-other/data/receipt.json')
        self.assertEqual(str(Path(similar)),str(similar))
    def test_default_zip_storage_belongs_to_shared_runtime(self):
        from codex_desktop_chat.bundles import default_bundle_dir
        self.assertEqual(default_bundle_dir(),NativePath.home()/'process'/'app-upload-zips')

    def test_relative_paths_remain_relative_for_archival_manifests(self):
        root=workspace_root()
        self.assertEqual(str((root/'infrastructure/core/catalog.py').relative_to(root)), 'infrastructure/core/catalog.py')
        self.assertEqual(str(Path('pipeline/example.py')), 'pipeline/example.py')
