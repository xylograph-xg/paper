"""A user pause survives main UI, keeper and direct worker startup paths."""
import json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from fetch import fetch_service
from core.cli import work

class FetchPause(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config={'catalog_path':str(self.root/'catalog.sqlite3')}
        (self.root/'fetch-control.json').write_text(json.dumps({'paused_by_user':True}))

    def test_keeper_and_direct_worker_do_not_create_background_processes(self):
        with patch.object(fetch_service.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'暂停'):fetch_service.start(self.config)
            work(self.config,loop=True,lane='fetch')
            work(self.config,loop=True,lane=None)
            spawn.assert_not_called()
        self.assertFalse((self.root/'catalog.sqlite3').exists())
        self.assertEqual(fetch_service.status(self.config)['state'],'paused_by_user')

    def test_direct_keeper_and_fetch_supervisor_cannot_bypass_pause(self):
        from core import runtime
        with patch.object(fetch_service,'load_config',return_value=self.config),patch.object(fetch_service.subprocess,'Popen') as spawn:
            fetch_service.run(self.root/'config.json');spawn.assert_not_called()
        with patch.object(runtime,'load_config',return_value=self.config),patch.object(runtime.subprocess,'Popen') as spawn:
            runtime.supervise(self.root/'config.json',fetch_only=True);spawn.assert_not_called()

    def test_isolated_scope_without_pause_file_remains_available(self):
        isolated=self.root/'short-cycle';isolated.mkdir()
        self.assertFalse(fetch_service.paused({'catalog_path':str(isolated/'catalog.sqlite3')}))
        (self.root/'fetch-control.json').write_text(json.dumps({'paused_by_user':False}))
        self.assertFalse(fetch_service.paused(self.config))

    def test_corrupt_existing_pause_does_not_resume(self):
        (self.root/'fetch-control.json').write_text('unfinished write')
        self.assertTrue(fetch_service.paused(self.config))

if __name__=='__main__':unittest.main()
