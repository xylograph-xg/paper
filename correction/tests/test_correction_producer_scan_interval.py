"""Correction routing throttle advances on completion, for run_once and status-write failures."""
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from concurrent.futures import Future
from unittest.mock import Mock, patch

import correction.recover_review_corrections as recovery
from correction import card_correction_queue as queue


class Clock:
    def __init__(self):self.now=0.0
    def monotonic(self):return self.now


class StopEvent:
    """Fake threading.Event; schedule is the exact tick sequence _run_owned should observe."""
    def __init__(self, clock, schedule):
        self.clock=clock;self.schedule=list(schedule);self.index=0
        if self.schedule:self.clock.now=float(self.schedule[0])
    def is_set(self):return self.index>=len(self.schedule)
    def wait(self, _seconds):
        if _seconds < 1:return  # Executor polling does not advance the scheduled outer tick.
        self.index+=1
        if self.index<len(self.schedule):self.clock.now=float(self.schedule[self.index])


class ScanInterval(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=SimpleNamespace()
        self.root.path=pathlib.Path(self.directory.name)/'catalog.sqlite3'
        self.clock=Clock()

    def producer(self, schedule):
        producer=queue.CorrectionProducer.__new__(queue.CorrectionProducer)
        producer.config={'card_correction':{'enabled':True}}
        producer.catalog=self.root
        producer.workers=1;producer.futures=set();producer.work=Mock()
        def submit(function,*args):
            future=Future()
            try:future.set_result(function(*args))
            except BaseException as exc:future.set_exception(exc)
            return future
        producer.executor=SimpleNamespace(submit=submit)
        producer.stop_event=StopEvent(self.clock,schedule)
        return producer

    def run_producer(self, schedule, run_once, atomic_json=None, enabled=True):
        producer=self.producer(schedule)
        self.rows=Mock(return_value=[])
        self.claim=Mock(return_value=None)
        self.recover=Mock(return_value=True)
        with (patch.object(queue,'time',SimpleNamespace(monotonic=self.clock.monotonic)),
              patch.object(queue,'enabled',return_value=enabled),
              patch.object(queue,'rows',self.rows),
              patch.object(queue,'claim',self.claim),
              patch.object(queue,'_recover_local',self.recover),
              patch.object(queue,'atomic_json',atomic_json or Mock()),
              patch.object(recovery,'run_once',side_effect=run_once)):
            producer._run_owned()

    def failing_run_once(self, calls):
        def run_once(_catalog,_config):
            calls.append(self.clock.now);raise RuntimeError('synthetic routing failure')
        return run_once

    def succeeding_run_once(self, calls, advance=0):
        def run_once(_catalog,_config):
            calls.append(self.clock.now)
            if advance:self.clock.now+=advance
            return {'candidates':0}
        return run_once

    def diagnostics(self):
        log=self.root.path.parent/'correction-diagnostics.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_run_once_failure_still_throttles(self):
        # A failure ending at 100 may retry at 1000, never at 101 or 999.
        calls=[]
        self.run_producer([100,101,999,1000],self.failing_run_once(calls))
        self.assertEqual(calls,[100.0,1000.0])
        self.assertEqual(self.rows.call_count,2)
        self.assertEqual(self.claim.call_count,2)

    def test_status_write_failure_throttles_without_fake_success(self):
        calls=[]
        writes=Mock(side_effect=OSError('synthetic status write failure'))
        self.run_producer([100,101,999,1000],self.succeeding_run_once(calls),atomic_json=writes)
        self.assertEqual(calls,[100.0,1000.0])
        self.assertEqual(writes.call_count,2)
        kinds={entry['kind'] for entry in self.diagnostics()}
        self.assertEqual(kinds,{'producer_error'})
        self.assertEqual(len(self.diagnostics()),2)

    def test_long_routing_run_measures_from_completion(self):
        # Finished at 120: 1019 is inside the interval, 1020 may retry.
        calls=[]
        self.run_producer([100,1019,1020],self.succeeding_run_once(calls,advance=20))
        self.assertEqual(calls,[100.0,1020.0])

    def test_successful_cycle_keeps_rows_and_claim_on_every_tick(self):
        calls=[]
        self.run_producer([100,101,1000],self.succeeding_run_once(calls))
        self.assertEqual(calls,[100.0,1000.0])
        self.assertEqual(self.rows.call_count,3)
        self.assertEqual(self.claim.call_count,3)

    def test_long_failed_routing_measures_from_completion(self):
        calls=[]
        def fail(*_):
            calls.append(self.clock.now);self.clock.now+=20
            raise RuntimeError('long routing failure')
        self.run_producer([100,1019,1020],fail)
        self.assertEqual(calls,[100.0,1020.0])
        self.assertEqual(self.claim.call_count,1)
        self.assertEqual(len(self.diagnostics()),2)

    def test_existing_task_recovers_and_runs_after_routing_failure(self):
        producer=self.producer([100,101]);producer.work=Mock()
        job={'id':'original-correction','state':'preparing'};recover=Mock(return_value=True)
        with (patch.object(queue,'time',SimpleNamespace(monotonic=self.clock.monotonic)),
              patch.object(queue,'enabled',return_value=True),
              patch.object(recovery,'run_once',side_effect=RuntimeError('routing failure')),
              patch.object(queue,'rows',return_value=[job]),
              patch.object(queue,'claim',return_value=job),
              patch.object(queue,'_recover_local',recover)):
            producer._run_owned()
        recover.assert_called_once_with(producer.catalog,job,producer.config)
        producer.work.assert_called_once_with(job)
        self.assertEqual(job,{'id':'original-correction','state':'preparing'})

    def test_run_once_failure_does_not_create_successful_status(self):
        writes=Mock();calls=[]
        self.run_producer([100],self.failing_run_once(calls),atomic_json=writes)
        writes.assert_not_called()
        self.assertFalse((self.root.path.parent/'correction-routing-status.json').exists())
        diagnostics=self.diagnostics();self.assertEqual(len(diagnostics),1)
        self.assertEqual(diagnostics[0]['kind'],'producer_error')
        self.assertEqual(diagnostics[0]['error'],'synthetic routing failure')

    def test_failed_status_write_preserves_previous_success_bytes(self):
        path=self.root.path.parent/'correction-routing-status.json'
        previous=b'{"updated":"previous","candidates":7}';path.write_bytes(previous)
        calls=[]
        self.run_producer([100],self.succeeding_run_once(calls),
                          atomic_json=Mock(side_effect=OSError('write failed')))
        self.assertEqual(path.read_bytes(),previous)
        self.assertEqual(self.diagnostics()[0]['kind'],'producer_error')

    def test_repeated_run_keeps_initial_routing_local(self):
        calls=[]
        for _ in range(2):self.run_producer([100],self.succeeding_run_once(calls))
        self.assertEqual(calls,[100.0,100.0])

    def test_pause_routes_and_claims_nothing(self):
        calls=[]
        self.run_producer([100,160],self.succeeding_run_once(calls),enabled=False)
        self.assertEqual(calls,[])
        self.assertEqual(self.rows.call_count,0)
        self.assertEqual(self.claim.call_count,0)

    def test_stop_event_exits_without_work(self):
        calls=[]
        self.run_producer([],self.succeeding_run_once(calls))
        self.assertEqual(calls,[])
        self.assertEqual(self.rows.call_count,0)
        self.assertEqual(self.diagnostics(),[])


class ActiveCorrectionOwnership(unittest.TestCase):
    setUp=ScanInterval.setUp
    producer=ScanInterval.producer

    def execute(self, *, workers=1, orphan=False, finish=False):
        producer=self.producer([1,2,3]);producer.workers=workers
        jobs=[{'id':'live-'+str(i),'paper_id':'paper-'+str(i),'state':'queued'} for i in range(workers)]
        interrupted={'id':'orphan','paper_id':'other-paper','state':'preparing'}
        pending=[]
        def submit(*_):
            future=Future();future.set_running_or_notify_cancel();pending.append(future)
            return future
        producer.executor=SimpleNamespace(submit=submit)
        def claim(*_):
            job=next((j for j in jobs if j['state']=='queued'),None)
            if job:job['state']='preparing'
            return dict(job) if job else None
        def records(*_):
            return [dict(j) for j in jobs]+([dict(interrupted)] if orphan else [])
        def update(_catalog,jid,state,*_):
            next(j for j in jobs+[interrupted] if j['id']==jid)['state']=state
        recover=Mock(return_value=False)
        original_wait=producer.stop_event.wait
        def wait(seconds):
            original_wait(seconds)
            if finish and seconds>=1 and producer.stop_event.index==1:
                for future in pending:future.set_exception(RuntimeError('worker ended before committing'))
        producer.stop_event.wait=wait
        with (patch.object(queue,'time',SimpleNamespace(monotonic=self.clock.monotonic)),
              patch.object(queue,'enabled',return_value=True),
              patch.object(queue,'rows',side_effect=records),
              patch.object(queue,'claim',side_effect=claim),
              patch.object(queue,'update',side_effect=update),
              patch.object(queue,'_recover_local',recover),
              patch.object(queue,'atomic_json',Mock()),
              patch.object(recovery,'run_once',return_value={})):
            producer._run_owned()
        return jobs,interrupted,recover

    def test_running_work_is_not_misclassified_as_interrupted(self):
        jobs,_,recover=self.execute()
        self.assertEqual(jobs[0]['state'],'preparing')
        recover.assert_not_called()

    def test_all_concurrent_running_jobs_retain_ownership(self):
        jobs,_,recover=self.execute(workers=2)
        self.assertEqual([j['state'] for j in jobs],['preparing','preparing'])
        recover.assert_not_called()

    def test_other_orphan_still_recovers_while_work_is_running(self):
        jobs,orphan,recover=self.execute(orphan=True)
        self.assertEqual(jobs[0]['state'],'preparing')
        self.assertEqual(orphan['state'],'needs_user')
        self.assertTrue(recover.called)
        self.assertEqual({call.args[1]['id'] for call in recover.call_args_list},{'orphan'})

    def test_finished_future_does_not_permanently_hide_uncommitted_job(self):
        jobs,_,recover=self.execute(finish=True)
        self.assertEqual(jobs[0]['state'],'needs_user')
        self.assertTrue(recover.called)
        self.assertEqual(recover.call_args.args[1]['id'],'live-0')


if __name__=='__main__':unittest.main()
