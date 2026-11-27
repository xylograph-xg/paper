# Regression invariants retained from test_audit_safety.py; historical audit reports remain unchanged.
"""Synthetic fault regressions: no production catalog, model or network APIs."""
import io
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.cli import worker_locks, work
from core.catalog import Catalog, ROOT
from core.runtime import alive, handover, runtime_status, stop_requested
from core.services import bridge, screen, validate_assessment, auto_select
from workbench.web import create_http_server


def assessment(quote):
    return {'core_findings':'模型初筛结果','recommendation_reason':'待核对','novelty':'相对背景的贡献',
            'relevance':5,'tags':['test'],'novelty_high':True,'evidence_quote':quote}


class SyntheticCatalog(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.sqlite3')
        self.config=json.loads((ROOT/'config/first_round.json').read_text())
        self.config['local_models_enabled']=True  # Explicit isolated legacy-mode fixture.
        self.config.update(catalog_path=str(self.catalog.path),archive_volume=str(self.root),
                           archive_root=str(self.root/'archive'),studio_library_root=str(self.root/'library'),
                           seed_input_dir=str(self.root/'seeds'),automatic_schedule_enabled=False)
        self.config_path=self.root/'config.json';self.config_path.write_text(json.dumps(self.config))
        self.config['model']['autostart']=False
        from core.model_schedule import configure
        configure(self.config,allow_minutes=60)
        self.config_path.write_text(json.dumps(self.config))
        identity=patch('core.model_identity.resolve_identity',return_value='synthetic-weights')
        identity.start();self.addCleanup(identity.stop)

    def tearDown(self):self.temp.cleanup()

    def wait_until(self,predicate,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.05)
        self.fail('Timed out waiting for isolated test process')

    def cleanup_process(self,p):
        if p.poll() is None:
            os.killpg(p.pid,signal.SIGKILL)
        p.wait(timeout=5)


class LockRegressions(SyntheticCatalog):
    def test_lane_locks_allow_parallel_lanes_but_reject_single_and_duplicate(self):
        with worker_locks(self.catalog.path,'fetch'),worker_locks(self.catalog.path,'read'):
            with self.assertRaises(RuntimeError):
                with worker_locks(self.catalog.path):pass
            with self.assertRaises(RuntimeError):
                with worker_locks(self.catalog.path,'read'):pass
        with worker_locks(self.catalog.path):pass

    def test_single_worker_excludes_both_lanes_until_exit(self):
        with worker_locks(self.catalog.path):
            for lane in ('fetch','screen','read'):
                with self.assertRaises(RuntimeError):
                    with worker_locks(self.catalog.path,lane):pass
        with worker_locks(self.catalog.path,'read'):pass

    def test_real_work_holds_mode_guard_during_job_and_releases_on_error(self):
        pid=self.catalog.upsert({'title':'Synthetic document'})
        self.catalog.enqueue('deep_read',pid)
        def job(*_):
            with self.assertRaises(RuntimeError):work(self.config,lane='fetch')
            raise RuntimeError('injected deep reading failure')
        with patch('core.model_job.run',side_effect=job),patch('sys.stderr',new=io.StringIO()):
            work(self.config)
        failed=self.catalog.jobs()[0]
        self.assertEqual(failed['state'],'failed')
        self.assertIn('Traceback',failed['error'])
        self.assertIn('injected deep reading failure',failed['error'])
        with worker_locks(self.catalog.path,'fetch'):pass


class EvidenceRegressions(SyntheticCatalog):
    def test_discretionary_hyphen_matches_retained_joined_and_unicode_quote(self):
        for quote in ('Measured phosphorescent emission.', 'Measured phosphores-cent emission.',
                      'Measured phosphores‐cent emission.', 'Measured phosphores-\ncent emission.'):
            with self.subTest(quote=quote):
                out=validate_assessment(assessment(quote),'Measured phosphores‐\ncent emission.')
                self.assertFalse(out['evidence_unverified'])
                self.assertEqual(out['evidence_excerpts'],[quote])

    def test_ordinary_hyphens_minus_signs_and_invented_words_remain_literal(self):
        for quote,source in [('The hostguest result is reproducible.','The host-guest result is reproducible.'),
                             ('The measured equation ab is reproducible.','The measured equation a-b is reproducible.'),
                             ('Measured phosphorescent emission is high.','Measured phosphorescent emission is low.')]:
            with self.subTest(quote=quote),self.assertRaises(ValueError):
                validate_assessment(assessment(quote),source)

    def test_short_or_fabricated_quote_is_retained_only_as_unverified_screening(self):
        for quote in ('Measured fabricated response.','short',''):
            original=assessment(quote)
            result=validate_assessment(original,'Actual measurement of the response.',strict=False)
            self.assertTrue(result['evidence_unverified'])
            self.assertFalse(result['novelty_high'])
            self.assertEqual(result['evidence_quote'],'')
            self.assertEqual(result['evidence_excerpts'],[])
            self.assertEqual(result['core_findings'],original['core_findings'])
            self.assertEqual(original['evidence_quote'],quote)

    def test_bad_schema_still_fails_in_soft_mode(self):
        data=assessment('');data['relevance']='5'
        with self.assertRaises(ValueError):validate_assessment(data,'',strict=False)

    def test_missing_evidence_is_explicitly_unverified_without_model_call(self):
        pid=self.catalog.upsert({'title':'Synthetic missing evidence'})
        self.config['pdf_only']=False
        with (patch('core.services.evidence_input',return_value=('','仅标题与摘要')),
              patch('core.services.urllib.request.urlopen') as request):
            screen(self.catalog,self.config,pid)
            request.assert_not_called()
        saved=self.catalog.get(pid)['assessment']
        self.assertTrue(saved['evidence_unverified'])
        self.assertFalse(saved['novelty_high'])

    def test_screen_saves_unverified_assessment_raw_output_and_blocks_auto_selection(self):
        pid=self.catalog.upsert({'title':'Synthetic measurement','venue':'Physical Review Letters','year':2026},candidate=True)
        pdf=self.root/'source.pdf';pdf.write_bytes(b'fixture')
        self.catalog.update(pid,asset_path=str(pdf),acquisition='available')
        raw=json.dumps(assessment('Measured fabricated response.'))
        def response(*_,**__):return io.BytesIO(json.dumps({'message':{'content':raw}}).encode())
        with (patch('core.services.evidence_input',return_value=('Actual measurement of the response.','PDF 文字层全文')),
              patch('core.services.urllib.request.urlopen',side_effect=response) as request):
            screen(self.catalog,self.config,pid)
            screen(self.catalog,self.config,pid)
            self.assertEqual(request.call_count,1)
        saved=self.catalog.get(pid)['assessment']
        self.assertTrue(saved['evidence_unverified']);self.assertEqual(saved['relevance'],5)
        auto_select(self.catalog,self.config)
        self.assertEqual(self.catalog.get(pid)['decision'],'unreviewed')
        with self.catalog.connect() as db:
            event=db.execute("SELECT payload FROM events WHERE kind='model_screen_raw'").fetchone()
            self.assertEqual(json.loads(event[0])['response'],raw)


class HttpRegressions(SyntheticCatalog):
    def setUp(self):
        super().setUp();self.hosts=set();self.token='synthetic-token'
        self.config['workbench_passwordless']=False
        self.server=create_http_server(self.config,self.catalog,0,self.token,self.hosts,set())
        host='127.0.0.1:'+str(self.server.server_port);self.hosts.add(host);self.url='http://'+host
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
        super().tearDown()

    def request(self,path,body=None):
        req=urllib.request.Request(self.url+path,data=body,headers={'X-Paper-Token':self.token})
        try:response=urllib.request.urlopen(req,timeout=3)
        except urllib.error.HTTPError as exc:response=exc
        with response:return response.status,json.load(response)

    def test_corrupted_pdf_returns_readable_400_and_removes_upload(self):
        pid=self.catalog.upsert({'title':'Synthetic upload'})
        for path in ('/api/import?id='+pid,'/api/import-batch'):
            status,body=self.request(path,b'%PDF-1.7\nthis is a corrupt document')
            self.assertEqual(status,400);self.assertIn('PDF 损坏',body['error'])
            self.assertEqual(list((self.root/'uploads').glob('*.pdf')),[])
        self.assertFalse(self.catalog.jobs())

    def test_get_and_post_runtime_timeout_and_unexpected_errors_are_json(self):
        faults=[(RuntimeError('storage unavailable'),503),(subprocess.TimeoutExpired('test',1),503),
                (TypeError('injected programming error'),500)]
        with patch('workbench.web.traceback.print_exc'):
            for fault,expected in faults:
                with self.subTest(fault=fault),patch.object(self.catalog,'list',side_effect=fault),patch.object(self.catalog,'page',side_effect=fault):
                    for path,body in [('/api/state',None),('/api/import-batch',b'%PDF-fixture')]:
                        status,data=self.request(path,body)
                        self.assertEqual(status,expected);self.assertTrue(data['error'])


class SupervisorRegressions(SyntheticCatalog):
    def exit_observation(self,pids):
        processes=[]
        for pid in pids:
            try:os.kill(pid,0);exists=True
            except ProcessLookupError:exists=False
            except PermissionError:exists='unknown'
            processes.append({'pid':pid,'alive':alive(pid),'kill0_exists':exists})
        paths=[self.root/'runtime.lock',self.catalog.path.with_suffix('.worker.lock')]
        paths.extend(self.catalog.path.with_suffix('.'+lane+'.lock')
                     for lane in ('fetch','screen','read'))
        locks=[]
        for path in paths:
            self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))
            if not path.exists():
                locks.append({'path':str(path),'status':'missing'});continue
            with path.open('r+b') as fd:
                entry={'path':str(path),'inode':os.fstat(fd.fileno()).st_ino}
                try:
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    fcntl.flock(fd,fcntl.LOCK_UN);entry['status']='available'
                except BlockingIOError:entry['status']='held'
                locks.append(entry)
        return {'time':time.monotonic(),'processes':processes,'locks':locks}

    def test_lock_observation_identifies_fixture_locks_without_releasing_them(self):
        with worker_locks(self.catalog.path):
            observed=self.exit_observation([os.getpid()])
            self.assertTrue(observed['processes'][0]['kill0_exists'])
            self.assertEqual({x['path'] for x in observed['locks'] if x['status']=='held'},
                {str(self.root/'runtime.lock'),str(self.catalog.path.with_suffix('.worker.lock'))})
            with self.assertRaises(RuntimeError):
                with worker_locks(self.catalog.path):pass
        self.assertFalse(any(x['status']=='held' for x in self.exit_observation([])['locks']))

    def test_wrong_token_cannot_request_worker_stop(self):
        identity={'pid':123,'token':'right'}
        (self.root/'worker-stop.json').write_text(json.dumps({'pid':123,'token':'wrong'}))
        self.assertFalse(stop_requested(self.root,identity))

    def test_killed_supervisor_stops_both_real_lane_workers(self):
        code="from pipeline import runtime; from pathlib import Path; import sys; runtime.publish=lambda folder,status:runtime.atomic_json(folder/'runtime.json',status); runtime.supervise(sys.argv[1])"
        with (self.root/'supervisor.log').open('w') as log:
            p=subprocess.Popen([sys.executable,'-c',code,str(self.config_path)],cwd=ROOT,
                               stdout=log,stderr=log,start_new_session=True)
        pids=[]
        try:
            self.wait_until(lambda:all((self.root/('worker-'+lane+'-identity.json')).exists() for lane in ('fetch','screen','read')))
            pids=[json.loads((self.root/('worker-'+lane+'-identity.json')).read_text())['pid'] for lane in ('fetch','screen','read')]
            self.assertTrue(all(alive(pid) for pid in pids))
            p.kill();p.wait(timeout=5)
            observations=[]
            def stopped():
                value=self.exit_observation(pids);observations.append(value)
                # Keep the original criterion and ten-second deadline. Diagnostics
                # do not turn a genuine surviving lock into a successful test.
                return not any(x['alive'] for x in value['processes'])
            try:
                self.wait_until(stopped)
                self.assertEqual(runtime_status(self.root)['state'],'stale')
                with worker_locks(self.catalog.path):pass
            finally:
                print('WORKER_EXIT_EVIDENCE='+json.dumps(observations),file=sys.stderr)
        finally:
            self.cleanup_process(p)
            for pid in pids:
                if alive(pid):os.killpg(pid,signal.SIGKILL)

    def test_lease_loss_stops_active_worker_and_bridge_descendant(self):
        pid=self.catalog.upsert({'title':'Synthetic blocking read'})
        job=self.catalog.enqueue('deep_read',pid)
        code="""import json,sys,subprocess
from core.api import paths__WorkspacePath as Path
from pipeline import services
from core.cli import work
config=json.loads(Path(sys.argv[1]).read_text())
def deep_read(*args):
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    Path(sys.argv[3]).write_text(str(child.pid))
    child.wait()
services.deep_read=deep_read
from pipeline import model_job
model_job.run=lambda *args: deep_read()
work(config,True,'read',int(sys.argv[2]))
"""
        read_fd,write_fd=os.pipe();marker=self.root/'bridge-pid'
        with (self.root/'worker.log').open('w') as log:
            p=subprocess.Popen([sys.executable,'-c',code,str(self.config_path),str(read_fd),str(marker)],cwd=ROOT,
                               pass_fds=(read_fd,),start_new_session=True,stdout=log,stderr=log)
        os.close(read_fd);child_pid=None
        try:
            self.wait_until(marker.exists);child_pid=int(marker.read_text())
            os.close(write_fd);write_fd=None
            p.wait(timeout=5)
            self.wait_until(lambda:not alive(child_pid))
            self.assertNotEqual(p.returncode,0)
            self.catalog.recover(('deep_read',))
            self.assertEqual(next(j for j in self.catalog.jobs() if j['id']==job)['state'],'failed')
            with worker_locks(self.catalog.path,'read'):pass
        finally:
            if write_fd is not None:os.close(write_fd)
            self.cleanup_process(p)
            if child_pid and alive(child_pid):os.kill(child_pid,signal.SIGKILL)

    def test_handover_with_config_uses_token_and_cooperative_exit(self):
        with (self.root/'single.log').open('w') as log:
            p=subprocess.Popen([sys.executable,'-m','core.cli','--config',str(self.config_path),'worker','--loop'],
                               cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        try:
            self.wait_until(lambda:(self.root/'worker-single-identity.json').exists())
            with patch('core.runtime.publish'),patch('core.runtime.supervise') as supervise:
                handover(p.pid,os.getpid(),str(self.config_path))
                supervise.assert_called_once_with(str(self.config_path),os.getpid())
            self.assertEqual(p.wait(timeout=5),0)
            self.assertEqual(json.loads((self.root/'handover.json').read_text())['state'],'activated')
            self.assertFalse((self.root/'worker-stop.json').exists())
        finally:self.cleanup_process(p)

    def test_unknown_live_process_is_never_signalled_by_handover(self):
        with patch('core.runtime.os.kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'缺少有效身份记录'):
                handover(os.getpid(),os.getpid(),str(self.config_path))
            self.assertTrue(all(call.args[1]==0 for call in kill.call_args_list))
        self.assertFalse(self.catalog.jobs())


class BridgeRegressions(SyntheticCatalog):
    def test_timeout_retains_stderr_and_partial_stdout(self):
        log=self.root/'logs/bridge.log'
        exc=subprocess.TimeoutExpired('bridge',1,output=b'partial response',stderr=b'failure location')
        with patch('core.process_runner.run',side_effect=exc):
            with self.assertRaises(subprocess.TimeoutExpired):bridge('synthetic',{},log=log,timeout=1)
        self.assertEqual(log.read_text(),'failure location')
        self.assertEqual(log.with_suffix('.log.stdout').read_text(),'partial response')


if __name__=='__main__':unittest.main()
