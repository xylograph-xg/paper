"""Cold imports and active-owner compatibility across the physical API boundary."""
import json
from core.api import paths__WorkspacePath as Path
import subprocess
import sys
import unittest

ROOT = __import__('core.api',fromlist=['paths__workspace_root']).paths__workspace_root()


class SubprojectInterfaces(unittest.TestCase):
    def child(self, code):
        return subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                              capture_output=True, text=True, timeout=20, check=True)

    def test_public_catalog_is_the_unique_cold_implementation(self):
        self.child('''from core.api import catalog__Catalog
from core.catalog import Catalog
from pipeline.catalog import Catalog as previous
assert catalog__Catalog is Catalog is previous
from pipeline.runtime import watch_supervisor
from core.runtime import watch_supervisor as actual
assert watch_supervisor is actual
''')

    def test_already_loaded_owner_keeps_its_existing_object(self):
        self.child('''import types,sys
old=types.ModuleType('pipeline.catalog')
old.Catalog=type('ExistingCatalog',(),{})
sys.modules['pipeline.catalog']=old
from pipeline._compat import bind
assert bind('catalog') is old
from core.api import catalog__Catalog
assert catalog__Catalog is old.Catalog
assert sys.modules['core.catalog'] is old
''')

    def test_importing_public_gateways_does_not_load_business_workers(self):
        self.child('''import importlib,sys
for project in ('fetch','cards','review','correction','reading','browser','core','workbench','maintenance'):
    importlib.import_module(project+'.api')
for name in ('core.catalog','core.runtime','browser.web_card_pool','cards.web_card_service','fetch.fetching'):
    assert name not in sys.modules,name
''')

    def test_legacy_cli_help_remains_safe_without_starting_services(self):
        for name in ('pipeline.fetch_service','pipeline.resident','pipeline.web_card_inputs','pipeline.workbench_service'):
            with self.subTest(name=name):
                result=subprocess.run([sys.executable,'-m',name,'--help'],cwd=ROOT,
                                      capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('usage:',result.stdout)


if __name__=='__main__':unittest.main()
