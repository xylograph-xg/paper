"""Isolated launcher lifetime, identity, and read-only startup regressions."""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.catalog import Catalog, ROOT
from core.runtime import alive
from workbench.workbench_service import start


class WorkbenchService(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='paper-workbench-service-');self.root=Path(self.temp.name)
        self.config=json.loads((ROOT/'config/first_round.json').read_text())
        self.config.update(catalog_path=str(self.root/'catalog.sqlite3'),tailscale_enabled=False,local_models_enabled=False)
        self.path=self.root/'config.json';self.path.write_text(json.dumps(self.config));self.config['_config_path']=str(self.path)
        Catalog(self.config['catalog_path']);self.pid=None
        with socket.socket() as server:server.bind(('127.0.0.1',0));self.port=server.getsockname()[1]
    def tearDown(self):
        record=self.root/'workbench-access.json'
        if self.pid is None and record.exists():
            try:self.pid=json.loads(record.read_text()).get('pid')
            except ValueError:pass
        if self.pid and self.pid!=os.getpid() and alive(self.pid):
            os.kill(self.pid,signal.SIGTERM)
            for _ in range(50):
                if not alive(self.pid):break
                time.sleep(.1)
        self.temp.cleanup()
    def command(self):
        return [sys.executable,'-m','workbench.workbench_service','--config',str(self.path),'--port',str(self.port),'--no-browser']
    def health(self,token):
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/workbench-health',headers={'X-Paper-Token':token})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as response:return json.load(response)
    def test_callers_exit_and_one_background_server_survives_with_no_jobs_or_control_changes(self):
        controls={name:b'{"paused_by_user":true}' for name in ('fetch-control.json','local-model-control.json','web-card-control.json')}
        for name,data in controls.items():(self.root/name).write_bytes(data)
        callers=[subprocess.Popen(self.command(),cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        for caller in callers:
            stdout,stderr=caller.communicate(timeout=20)
            self.assertEqual(caller.returncode,0,stderr);self.assertIn('现在可以关闭此终端',stdout)
        record=json.loads((self.root/'workbench-access.json').read_text());self.pid=record['pid']
        self.assertTrue(alive(self.pid));self.assertEqual(os.getpgid(self.pid),self.pid)
        self.assertNotIn(self.pid,[caller.pid for caller in callers]);self.assertTrue(record['background'])
        self.assertEqual(self.health(record['token'])['pid'],self.pid)
        os.kill(self.pid,signal.SIGHUP)
        self.assertTrue(self.health(record['token'])['background'])
        result=subprocess.run(self.command(),cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads((self.root/'workbench-access.json').read_text())['pid'],self.pid)
        self.assertEqual(self.health(record['token'])['pid'],self.pid)
        for name,data in controls.items():self.assertEqual((self.root/name).read_bytes(),data)
        with Catalog(self.config['catalog_path']).connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM papers').fetchone()[0],0)
        self.assertFalse((self.root/'runtime.json').exists())
    def test_unreadable_access_record_blocks_launch_and_remains_unchanged(self):
        record=self.root/'workbench-access.json';record.write_bytes(b'{broken')
        with patch('workbench.workbench_service.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'访问记录不可读'):start(self.config,self.port,False)
            spawn.assert_not_called()
        self.assertEqual(record.read_bytes(),b'{broken')
    def test_explicit_restart_preserves_the_existing_remote_access_token(self):
        token='synthetic-existing-access-token-for-restart'
        (self.root/'workbench-access.json').write_text(json.dumps({'pid':0,'port':self.port,'token':token}))
        result=subprocess.run(self.command(),cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('#access=',result.stdout)
        self.assertNotIn(token,result.stdout)
        record=json.loads((self.root/'workbench-access.json').read_text());self.pid=record['pid']
        self.assertEqual(record['token'],token);self.assertTrue(self.health(token)['background'])


if __name__=='__main__':unittest.main()
