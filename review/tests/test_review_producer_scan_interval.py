"""Producer scan throttle advances on completion, whether enqueue succeeded or failed."""
import tempfile
import unittest
from types import SimpleNamespace
from concurrent.futures import Future
from unittest.mock import Mock, patch

from core.api import paths__WorkspacePath as Path
from review import card_review_queue as queue


class Clock:
    def __init__(self):self.now=0.0
    def monotonic(self):return self.now


class StopEvent:
    """Fake threading.Event; schedule is the exact tick sequence run() should observe."""
    def __init__(self, clock, schedule):
        self.clock=clock;self.schedule=list(schedule);self.index=0
        if self.schedule:self.clock.now=float(self.schedule[0])
    def is_set(self):return self.index>=len(self.schedule)
    def wait(self, _seconds):
        self.index+=1
        if self.index<len(self.schedule):self.clock.now=float(self.schedule[self.index])


class Cursor:
    def __init__(self, rows):self.rows=rows
    def fetchone(self):return self.rows[0] if self.rows else None


class Database:
    def __init__(self, log):self.log=log
    def execute(self, sql, params=()):
        self.log.append(sql)
        if 'count(*)' in sql:return Cursor([(0,)])
        return Cursor([])


class Connection:
    def __init__(self, log):self.log=log
    def __enter__(self):return Database(self.log)
    def __exit__(self, *_):return False


class Catalog:
    def __init__(self, root, log):
        self.path=Path(root)/'catalog.sqlite3';self.log=log
    def connect(self):
        self.log.append('connect');return Connection(self.log)


class ScanInterval(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.clock=Clock()

    def producer(self, schedule):
        self.claim_log=[]
        producer=queue.ReviewProducer.__new__(queue.ReviewProducer)
        producer.config={'card_review':{'enabled':True,'parallel_jobs':4}}
        producer.catalog=Catalog(self.root,self.claim_log)
        producer.futures={};producer.executor=Mock()
        def submit(callback,*args,**kwargs):
            future=Future()
            if args: return future  # prepared jobs stay in flight in this fake
            try:future.set_result(callback())
            except Exception as exc:future.set_exception(exc)
            return future
        producer.executor.submit.side_effect=submit
        producer.stop_event=StopEvent(self.clock,schedule)
        return producer

    def run_producer(self, schedule, enqueue, enabled=True):
        producer=self.producer(schedule)
        self.errors=Mock()
        with (patch.object(queue,'time',SimpleNamespace(monotonic=self.clock.monotonic)),
              patch.object(queue,'enabled',return_value=enabled),
              patch.object(queue,'enqueue',side_effect=enqueue),
              patch.object(queue,'atomic_json',self.errors),
              patch('browser.api.shared_page_backlog__preparation_head_ids',return_value=set())):
            producer.run()

    def failing_enqueue(self, calls):
        def enqueue(_catalog,_config,**_options):
            calls.append(self.clock.now);raise RuntimeError('synthetic scan failure')
        return enqueue

    def succeeding_enqueue(self, calls, advance=0):
        def enqueue(_catalog,_config,**_options):
            calls.append(self.clock.now)
            if advance:self.clock.now+=advance
        return enqueue

    def test_pending_discovery_does_not_block_saved_response_processing(self):
        producer=self.producer([100,101]);original=Database.execute;served=[]
        job={'id':'saved-while-scan-running','state':'response_saved'}
        def execute(db,sql,params=()):
            if sql.startswith('SELECT j.*') and not served:
                served.append(True);return Cursor([job])
            return original(db,sql,params)
        producer.executor.submit.side_effect=lambda *_args,**_kwargs:Future()
        with (patch.object(queue,'time',SimpleNamespace(monotonic=self.clock.monotonic)),
              patch.object(queue,'enabled',return_value=True),
              patch.object(queue,'atomic_json',Mock()),
              patch('browser.api.shared_page_backlog__preparation_head_ids',return_value=set()),
              patch.object(Database,'execute',execute)):
            producer.run()
        producer.executor.submit.assert_any_call(producer.work,job)
        self.assertEqual(producer.executor.submit.call_count,2)

    def test_failed_enqueue_still_advances_throttle(self):
        # A persistent scan failure must not turn the loop into 1Hz retries.
        calls=[]
        self.run_producer([100,101,998,999,1000,1001],self.failing_enqueue(calls))
        self.assertEqual(calls,[100.0,1000.0])
        self.assertEqual(self.errors.call_count,2)
        self.assertEqual(self.claim_log.count('connect'),6)

    def test_failure_before_fifteen_minutes_does_not_rescan(self):
        calls=[]
        self.run_producer([100,998,999],self.failing_enqueue(calls))
        self.assertEqual(calls,[100.0])

    def test_long_scan_measures_from_completion(self):
        # Finished at 120, so 1019 is still inside the interval.
        calls=[]
        self.run_producer([100,1019,1020],self.succeeding_enqueue(calls,advance=20))
        self.assertEqual(calls,[100.0,1020.0])

    def test_successful_scan_keeps_interval_and_claim_path(self):
        calls=[]
        self.run_producer([100,101,999,1000],self.succeeding_enqueue(calls))
        self.assertEqual(calls,[100.0,1000.0])
        self.assertEqual(self.claim_log.count('connect'),4)
        self.assertEqual(self.errors.call_count,0)

    def test_long_failed_scan_measures_from_completion(self):
        calls=[]
        def fail(*_,**_options):
            calls.append(self.clock.now);self.clock.now+=20
            raise RuntimeError('long scan failure')
        self.run_producer([100,1018,1019,1020],fail)
        self.assertEqual(calls,[100.0,1020.0])
        self.assertEqual(self.errors.call_count,2)
        self.assertEqual(self.claim_log.count('connect'),4)

    def test_saved_response_is_processed_on_tick_after_scan_failure(self):
        producer=self.producer([100,101]);original=Database.execute;served=[]
        job={'id':'original-response','state':'response_saved'}
        def execute(db,sql,params=()):
            if sql.startswith('SELECT j.*') and not served:
                served.append(True);return Cursor([job])
            return original(db,sql,params)
        recorder=Mock()
        with (patch.object(queue,'time',SimpleNamespace(monotonic=self.clock.monotonic)),
              patch.object(queue,'enabled',return_value=True),
              patch.object(queue,'enqueue',side_effect=RuntimeError('scan failed before work')),
              patch.object(queue,'atomic_json',recorder),
              patch('browser.api.shared_page_backlog__preparation_head_ids',return_value=set()),
              patch.object(Database,'execute',execute)):
            producer.run()
        producer.executor.submit.assert_any_call(producer.work,job)
        self.assertEqual(job,{'id':'original-response','state':'response_saved'})
        self.assertTrue(any('UPDATE card_review_jobs' in sql for sql in self.claim_log))
        self.assertEqual(recorder.call_count,1)
        self.assertEqual(recorder.call_args.args[1]['error'],'scan failed before work')

    def test_repeated_run_keeps_initial_scan_local(self):
        calls=[]
        for _ in range(2):self.run_producer([100],self.succeeding_enqueue(calls))
        self.assertEqual(calls,[100.0,100.0])

    def test_pause_scans_and_claims_nothing(self):
        calls=[]
        self.run_producer([100,161],self.succeeding_enqueue(calls),enabled=False)
        self.assertEqual(calls,[])
        self.assertEqual(self.claim_log,[])

    def test_stop_event_exits_without_work(self):
        calls=[]
        self.run_producer([],self.succeeding_enqueue(calls))
        self.assertEqual(calls,[])
        self.assertEqual(self.claim_log,[])


if __name__=='__main__':unittest.main()
