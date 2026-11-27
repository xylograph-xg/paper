import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from workbench.web import csv_text
from workbench.upload_storage import collect,prepare
from core.api import catalog__Catalog as Catalog

class CsvAudit(unittest.TestCase):
    def test_formula_prefixes(self):
        for value in ('=1','  +2','\t@sum(1)','\r-2','\n=3'):self.assertTrue(csv_text(value).startswith("'"))
        self.assertEqual(csv_text('正常题名'),'正常题名')

class UploadAudit(unittest.TestCase):
    def test_expiration_preserves_queued_input_and_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog=Catalog(str(Path(folder)/'catalog.sqlite3'));uploads=Path(folder)/'uploads';uploads.mkdir()
            orphan=uploads/('a'*32+'.pdf');orphan.write_bytes(b'old');os.utime(orphan,(0,0))
            active=uploads/('b'*32+'.pdf');active.write_bytes(b'active');os.utime(active,(0,0))
            catalog.enqueue('import',payload={'source':str(active)})
            self.assertEqual(collect(catalog)['eligible'],[str(orphan)]);self.assertTrue(orphan.exists())
            collect(catalog,apply=True);self.assertFalse(orphan.exists());self.assertTrue(active.exists())
            with self.assertRaises(ValueError):prepare(catalog,{'upload_storage':{'max_bytes':6}},1)

class SlowConnectionAudit(unittest.TestCase):
    from workbench.tests.test_workbench_access import WorkbenchAccess
    setUp=WorkbenchAccess.setUp
    tearDown=WorkbenchAccess.tearDown
    request=WorkbenchAccess.request
    available_slots=staticmethod(WorkbenchAccess.available_slots)
    assert_request_capacity_released=WorkbenchAccess.assert_request_capacity_released
    admitted_idle_connections=WorkbenchAccess.admitted_idle_connections
    def test_sixteen_incomplete_headers_do_not_starve_health(self):
        with self.admitted_idle_connections(b'GET / HTTP/1.1\r\n'):
            self.assertEqual(self.request('/api/workbench-health',
                headers={'X-Paper-Token':self.secret})[0],200)

class LogAudit(unittest.TestCase):
    def test_live_child_rotates_without_restart(self):
        import sys
        from reading.api import log_output__spawn_logged as spawn_logged
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'child.log'
            process=spawn_logged([sys.executable,'-c','import sys;sys.stdout.write("x"*6000000);sys.stdout.flush()'],path)
            self.assertEqual(process.wait(timeout=15),0)
            self.assertTrue(path.with_name('child.log.1').exists())
            self.assertLess(path.stat().st_size,5*1024*1024)
