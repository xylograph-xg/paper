"""Clock boundaries and real isolated process overlap/cancellation, without inference."""
from datetime import datetime
import json
import os
from core.api import paths__WorkspacePath as Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from core.catalog import Catalog, ROOT
from core.cli import _work, worker_locks
from core.model_schedule import configure, status, ModelWindowClosed, schedule_path, set_user_pause, require_allowed
from core import model_job
from core.runtime import alive

ZONE = ZoneInfo('Asia/Shanghai')

FIXTURE_INFERENCE = '''import json,os,sys,time,subprocess
from core.api import paths__WorkspacePath as Path
from core.runtime import watch_supervisor
from core.services import atomic_json
data=json.loads(Path(sys.argv[1]).read_text());watch_supervisor(int(sys.argv[2]))
folder=Path(data['config']['catalog_path']).parent
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
atomic_json(folder/(data['job']['kind']+'.entered'),{'pid':os.getpid(),'child':child.pid})
while not (folder/'release').exists():time.sleep(.05)
atomic_json(Path(data['result']),{'state':'done'})
'''


class ModelScheduling(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / 'catalog.db')
        self.config = json.loads((ROOT / 'config/first_round.json').read_text())
        self.config['local_models_enabled'] = True  # Explicit synthetic legacy-mode fixture.
        self.config.update(catalog_path=str(self.catalog.path), automatic_schedule_enabled=False,
                           require_mounted_volume=False, archive_volume=str(self.root),
                           archive_root=str(self.root / 'archive'), studio_library_root=str(self.root / 'library'))
        self.config['model']['autostart'] = False

    def tearDown(self):
        self.temp.cleanup()

    def clock(self, value):
        return datetime.fromisoformat('2026-10-06T' + value + '+08:00')

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.05)
        self.fail('Isolated process condition timed out')

    def test_daily_boundary_and_timezone(self):
        for value, allowed in [('00:00:00',False), ('09:59:59',False), ('10:00:00',True), ('23:59:59',True)]:
            with self.subTest(value=value):
                self.assertEqual(status(self.config,self.clock(value))['allowed'],allowed)
        value = status(self.config, datetime.fromisoformat('2026-10-06T01:59:59+00:00'))
        self.assertFalse(value['allowed'])
        self.assertEqual(value['next_allowed_at'],'2026-10-06T10:00:00+08:00')

    def test_user_pause_survives_window_reset_and_manual_override(self):
        set_user_pause(self.config,True,'human stop')
        self.assertEqual(status(self.config,self.clock('12:00:00'))['mode'],'paused')
        configure(self.config,allow_minutes=60,at=self.clock('12:00:00'))
        configure(self.config,reset=True,at=self.clock('12:00:00'))
        with self.assertRaises(ModelWindowClosed):require_allowed(self.config)
        set_user_pause(self.config,False)
        self.assertTrue(status(self.config,self.clock('12:00:00'))['allowed'])
        self.assertFalse(status(self.config,self.clock('01:00:00'))['allowed'])

    def test_user_pause_blocks_start_and_recovery_without_touching_queue(self):
        from reading.reading_service import start
        jid=self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic pause'}))
        set_user_pause(self.config,True)
        with patch('reading.reading_service.subprocess.Popen') as spawn:
            self.assertEqual(start(self.config)['state'],'paused');spawn.assert_not_called()
        with patch('core.catalog.Catalog.recover') as recover,patch('reading.reading_recovery.activate') as activate:
            _work(self.catalog,self.config,False,'read',lambda:False)
            recover.assert_not_called();activate.assert_not_called()
        job=next(j for j in self.catalog.jobs() if j['id']==jid)
        self.assertEqual(job['state'],'queued');self.assertEqual(job['attempts'],0)

    def test_deferred_read_keeps_checkpoint_resume_even_without_failed_attempt(self):
        jid=self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic resume'}),{'force':True})
        self.catalog.claim(('deep_read',))
        self.catalog.defer(jid,'user pause')
        job=next(j for j in self.catalog.jobs() if j['id']==jid)
        self.assertEqual(job['attempts'],0)
        payload=json.loads(job['payload'])
        self.assertTrue(payload['resume']);self.assertTrue(payload['force'])

    def test_legal_custom_window_resumes_next_day(self):
        configure(self.config,start='12:30',end='20:15',at=self.clock('12:00:00'))
        self.assertFalse(status(self.config,self.clock('12:29:59'))['allowed'])
        self.assertTrue(status(self.config,self.clock('12:30:00'))['allowed'])
        value=status(self.config,self.clock('20:15:00'))
        self.assertFalse(value['allowed']);self.assertEqual(value['next_allowed_at'],'2026-10-07T12:30:00+08:00')

    def test_all_day_persists_across_midnight_without_override(self):
        value=configure(self.config,start='00:00',end='24:00',at=self.clock('01:00:00'))
        self.assertEqual(value['mode'],'all_day');self.assertIsNone(value['override_until'])
        for value in ['00:00:00','09:59:59','10:00:00','23:59:59']:
            current=status(self.config,self.clock(value))
            self.assertTrue(current['allowed']);self.assertIsNone(current['next_allowed_at'])
        self.assertTrue(status(self.config,datetime.fromisoformat('2026-10-07T00:00:00+08:00'))['allowed'])
        configure(self.config,reset=True,at=self.clock('01:00:00'))
        self.assertFalse(status(self.config,self.clock('01:00:00'))['allowed'])

    def test_all_day_preserves_pause_and_does_not_start_queued_work(self):
        jid=self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic paused all day'}))
        set_user_pause(self.config,True,'human stop')
        value=configure(self.config,start='00:00',end='24:00',at=self.clock('01:00:00'))
        self.assertEqual(value['mode'],'paused');self.assertFalse(value['allowed'])
        self.assertEqual(value['start'],'00:00')
        from reading.reading_service import start
        with patch('reading.reading_service.subprocess.Popen') as spawn:
            self.assertEqual(start(self.config)['state'],'paused');spawn.assert_not_called()
        job=next(j for j in self.catalog.jobs() if j['id']==jid)
        self.assertEqual(job['state'],'queued');self.assertEqual(job['attempts'],0)
        set_user_pause(self.config,False)
        self.assertTrue(status(self.config,self.clock('01:00:00'))['allowed'])

    def test_invalid_or_night_window_does_not_write(self):
        for start,end in [('09:59','24:00'),('23:00','02:00'),('13:00','12:00'),('10:00','25:00')]:
            with self.assertRaises(ValueError):configure(self.config,start=start,end=end)
        self.assertFalse(schedule_path(self.config).exists())

    def test_override_is_explicit_finite_shared_and_resettable(self):
        at=self.clock('01:00:00')
        value=configure(self.config,allow_minutes=60,at=at)
        self.assertTrue(value['allowed']);self.assertEqual(value['mode'],'manual')
        self.assertTrue(status(self.config,self.clock('01:59:59'))['allowed'])
        self.assertFalse(status(self.config,self.clock('02:00:00'))['allowed'])
        self.assertEqual(schedule_path(self.config).stat().st_mode & 0o777,0o600)
        configure(self.config,reset=True,at=at)
        self.assertFalse(status(self.config,at)['allowed'])

    def test_custom_window_revokes_manual_override(self):
        at=self.clock('01:00:00')
        configure(self.config,allow_minutes=60,at=at)
        value=configure(self.config,start='11:00',end='00:00',at=at)
        self.assertFalse(value['allowed']);self.assertIsNone(value['override_until'])

    def test_corrupt_file_fails_closed_and_can_reset(self):
        schedule_path(self.config).write_text('{bad')
        self.assertEqual(status(self.config,self.clock('12:00:00'))['mode'],'invalid')
        self.assertFalse(status(self.config,self.clock('12:00:00'))['allowed'])
        configure(self.config,reset=True,at=self.clock('12:00:00'))
        self.assertTrue(status(self.config,self.clock('12:00:00'))['allowed'])

    def test_paused_jobs_keep_budget_and_do_not_block_other_kinds(self):
        model = self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic card'}))
        screen = self.catalog.enqueue('screen',self.catalog.upsert({'title':'Synthetic screen'}))
        automatic = self.catalog.enqueue('auto_select')
        paused = status(self.config,self.clock('01:00:00'))
        with (patch('core.model_schedule.status',return_value=paused),
              patch('core.services.auto_select') as select,
              patch('core.model_job.run') as inference):
            _work(self.catalog,self.config,False,None,lambda:False)
            select.assert_called_once();inference.assert_not_called()
        jobs={j['id']:j for j in self.catalog.jobs()}
        for key in (model,screen):
            self.assertEqual(jobs[key]['state'],'queued');self.assertEqual(jobs[key]['attempts'],0)
        self.assertEqual(jobs[automatic]['state'],'done')
        self.assertIsNone(self.catalog.claim(()))

    def test_paused_read_lane_cannot_claim_fetch_or_screen(self):
        card = self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic card'}))
        screen = self.catalog.enqueue('screen',self.catalog.upsert({'title':'Synthetic screen'}))
        fetch = self.catalog.enqueue('discover')
        with (patch('core.model_schedule.status',return_value=status(self.config,self.clock('01:00:00'))),
              patch('reading.reading_recovery.activate')):
            _work(self.catalog,self.config,False,'read',lambda:False)
        self.assertTrue(all(j['state']=='queued' for j in self.catalog.jobs()))

    def test_pause_requeues_same_job_without_consuming_attempt(self):
        jid = self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic card'}))
        allowed = status(self.config,self.clock('12:00:00'))
        calls=0
        def stopped():
            nonlocal calls
            calls+=1
            return calls>1
        with (patch('core.model_schedule.status',return_value=allowed),
              patch('reading.reading_recovery.activate'),
              patch('core.model_job.run',side_effect=ModelWindowClosed('paused'))):
            _work(self.catalog,self.config,False,'read',stopped)
        job=next(j for j in self.catalog.jobs() if j['id']==jid)
        self.assertEqual(job['state'],'queued');self.assertEqual(job['attempts'],0)

    def fixture_process(self, args, **kwargs):
        # Real child and grandchild inherit the inference lease and group contract.

        return self.real_popen([sys.executable,'-c',FIXTURE_INFERENCE,*args[-2:]],**kwargs)

    def test_two_independent_workers_overlap_real_job_processes(self):
        configure(self.config,allow_minutes=60)
        card=self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic card'}))
        screen=self.catalog.enqueue('screen',self.catalog.upsert({'title':'Synthetic screen'}))
        errors=[];threads=[]
        def work_lane(lane):
            try:
                with worker_locks(self.catalog.path,lane):_work(self.catalog,self.config,False,lane,lambda:False)
            except BaseException as exc:errors.append(exc)
        self.real_popen=subprocess.Popen
        with patch('core.model_job.subprocess.Popen',side_effect=self.fixture_process):
            try:
                threads=[threading.Thread(target=work_lane,args=(lane,),daemon=True) for lane in ('read','screen')]
                for thread in threads:thread.start()
                self.wait_for(lambda:all((self.root/(kind+'.entered')).exists() for kind in ('screen','deep_read')))
                markers=[json.loads((self.root/(kind+'.entered')).read_text()) for kind in ('screen','deep_read')]
                self.assertNotEqual(markers[0]['pid'],markers[1]['pid'])
                for jid in (card,screen):
                    self.assertEqual(next(j for j in self.catalog.jobs() if j['id']==jid)['state'],'running')
                (self.root/'release').touch()
            finally:
                (self.root/'release').touch()
                for thread in threads:thread.join(8)
        self.assertEqual(errors,[]);self.assertTrue(all(not t.is_alive() for t in threads))
        for jid in (card,screen):self.assertEqual(next(j for j in self.catalog.jobs() if j['id']==jid)['state'],'done')
        for marker in markers:self.wait_for(lambda:not alive(marker['child']))

    def test_window_closing_kills_active_process_and_descendant(self):
        configure(self.config,allow_minutes=60)
        jid=self.catalog.enqueue('deep_read',self.catalog.upsert({'title':'Synthetic card'}));job=self.catalog.claim(('deep_read',))
        self.real_popen=subprocess.Popen
        def window(config):
            return {'allowed':not (self.root/'deep_read.entered').exists()}
        with (patch('core.model_job.subprocess.Popen',side_effect=self.fixture_process),
              patch('core.model_job.status',side_effect=window)):
            with self.assertRaises(ModelWindowClosed):model_job.run(self.catalog,self.config,job)
        marker=json.loads((self.root/'deep_read.entered').read_text())
        self.wait_for(lambda:not alive(marker['pid']) and not alive(marker['child']))
        self.catalog.defer(jid,'window closed')
        recovered=self.catalog.claim(('deep_read',))
        self.assertEqual(recovered['id'],jid);self.assertEqual(recovered['attempts'],0)

    def test_no_process_is_spawned_when_window_is_closed(self):
        paused=status(self.config,self.clock('01:00:00'))
        with (patch('core.model_schedule.status',return_value=paused),
              patch('core.model_job.subprocess.Popen') as spawn):
            with self.assertRaises(ModelWindowClosed):model_job.run(self.catalog,self.config,{'id':'test'})
            spawn.assert_not_called()

    def test_detached_reading_supervisor_can_reuse_and_stop_both_lanes(self):
        from reading.reading_service import start, status as reading_status, request_stop
        config_path=self.root/'config.json';config_path.write_text(json.dumps(self.config))
        try:
            started=start(self.config,config_path)
            self.assertEqual(set(started['lanes']),{'screen','read'})
            self.assertEqual(start(self.config,config_path)['pid'],started['pid'])
            self.assertTrue(start(self.config,config_path)['reused'])
            pids=[lane['pid'] for lane in started['lanes'].values()]
            request_stop(self.config)
            self.wait_for(lambda:reading_status(self.config)['state']=='stopped')
            for pid in pids:self.wait_for(lambda:not alive(pid))
        finally:
            request_stop(self.config)

    def test_killed_model_owner_lease_stops_job_and_descendant(self):
        configure(self.config,allow_minutes=60)
        config_path=self.root/'config.json';config_path.write_text(json.dumps(self.config))
        fixture_path=self.root/'fixture-job.py';fixture_path.write_text(FIXTURE_INFERENCE)
        code='''import json,subprocess,sys
from core.api import paths__WorkspacePath as Path
from pipeline import model_job
from core.catalog import Catalog
config=json.loads(Path(sys.argv[1]).read_text());catalog=Catalog(config['catalog_path'])
real_popen=subprocess.Popen
def spawn(args,**kwargs):return real_popen([sys.executable,'-c',Path(sys.argv[2]).read_text(),*args[-2:]],**kwargs)
model_job.subprocess.Popen=spawn
job={'id':'synthetic-owner','kind':'deep_read','paper_id':None}
model_job.run(catalog,config,job)
'''
        process=subprocess.Popen([sys.executable,'-c',code,str(config_path),str(fixture_path)],cwd=ROOT,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        marker=None
        try:
            self.wait_for(lambda:(self.root/'deep_read.entered').exists())
            marker=json.loads((self.root/'deep_read.entered').read_text())
            process.kill();process.wait(timeout=3)
            self.wait_for(lambda:not alive(marker['pid']) and not alive(marker['child']))
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=3)
            if marker:
                for pid in (marker['pid'],marker['child']):
                    if alive(pid):os.kill(pid,signal.SIGKILL)

    def test_screen_request_boundary_rejects_night_even_without_worker(self):
        from core.services import screen
        pid=self.catalog.upsert({'title':'Synthetic screen boundary'})
        self.config['pdf_only']=False
        paused=status(self.config,self.clock('01:00:00'))
        with (patch('core.services.evidence_input',return_value=('Synthetic measurable evidence.','PDF')),
              patch('core.model_schedule.status',return_value=paused),
              patch('core.services.urllib.request.urlopen') as request):
            with self.assertRaises(ModelWindowClosed):screen(self.catalog,self.config,pid)
            request.assert_not_called()

    def test_historical_partial_does_not_crash_reader_maintenance_when_retry_exists(self):
        from core.services import maintain_jobs
        pid=self.catalog.upsert({'title':'Synthetic repeated partial'})
        old=self.catalog.enqueue('deep_read',pid);self.catalog.claim(('deep_read',));self.catalog.finish(old,'partial')
        active=self.catalog.enqueue('deep_read',pid)
        self.config['job_retry_delay_seconds']=0
        maintain_jobs(self.catalog,self.config,kinds=('deep_read',),audit_assets=False)
        values={j['id']:j for j in self.catalog.jobs()}
        self.assertEqual(values[old]['state'],'partial');self.assertEqual(values[active]['state'],'queued')
        with self.assertRaisesRegex(ValueError,'已经排队'):self.catalog.retry(old)


if __name__=='__main__':unittest.main()
