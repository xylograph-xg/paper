import time,unittest
from unittest.mock import patch
from fetch.tests.test_fetch_pipeline import FetchFixtures
from cards import web_card_queue as queue
from browser.web_page_queue import assign, next_ready, MaterialProducer

class PageQueueTests(FetchFixtures):
 def setUp(self):
  super().setUp();queue.install(self.catalog);self.ids=[]
  from core.catalog import now
  with self.catalog.connect() as db:
   for i in range(6):
    pid=f'paper-{i}';self.ids.append(pid)
    db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',(pid,'hash','title','{}',now()))
 def bindings(self):
  with self.catalog.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM web_page_queue')]
 def test_assign_shortest_queues_and_keep_fixed_binding(self):
  assign(self.catalog,['a','b']);first={r['paper_id']:r['target_id'] for r in self.bindings()}
  self.assertEqual(len(first),4);self.assertEqual(list(first.values()).count('a'),2)
  assign(self.catalog,['a','b','c']);second={r['paper_id']:r['target_id'] for r in self.bindings()}
  self.assertTrue(all(second[p]==t for p,t in first.items()));self.assertEqual(list(second.values()).count('c'),2)
 def test_only_ready_material_and_correct_page_can_be_claimed(self):
  assign(self.catalog,['a','b']);self.assertIsNone(next_ready(self.catalog,['a']))
  pid=self.bindings()[0]['paper_id']
  with self.catalog.connect() as db:db.execute("UPDATE web_page_queue SET state='ready' WHERE paper_id=?",(pid,))
  result=next_ready(self.catalog,['a']);self.assertEqual(result['paper_id'],pid)
  self.assertIsNone(next_ready(self.catalog,['b']))
  self.assertEqual(queue.claim(self.catalog,pid)['paper_id'],pid);self.assertIsNone(queue.claim(self.catalog,pid))
 def test_reduction_rehomes_unsent_queue_without_requeueing_submitted(self):
  assign(self.catalog,['a','b']);pid=self.bindings()[0]['paper_id'];queue.claim(self.catalog,pid);queue.update(self.catalog,pid,state='submitted')
  assign(self.catalog,['b']);self.assertNotIn(pid,[r['paper_id'] for r in self.bindings()]);self.assertTrue(all(r['target_id']=='b' for r in self.bindings()))
  self.assertEqual(next(j for j in queue.jobs(self.catalog) if j['paper_id']==pid)['state'],'submitted')
 def test_preparation_runs_off_browser_thread_and_does_not_claim_job(self):
  assign(self.catalog,['a'],config=self.config);producer=MaterialProducer(self.config)
  with patch('browser.web_page_queue.prepare',return_value={}) as prepare,patch('cards.web_card_service.enabled',return_value=True),patch('core.automatic_issue_handler.run_once'),patch('reading.manual_literature.run_once'):
   producer.start()
   deadline=time.monotonic()+3
   while not next_ready(self.catalog,['a']) and time.monotonic()<deadline:time.sleep(.02)
   producer.stop();self.assertTrue(prepare.called);self.assertIsNotNone(next_ready(self.catalog,['a']))
  self.assertTrue(all(j['state']=='queued' for j in queue.jobs(self.catalog)))

class SelectionIsolationTests(unittest.TestCase):
 def test_slow_selection_runs_on_existing_worker_and_lock_error_is_contained(self):
  import threading,tempfile,sqlite3
  from types import SimpleNamespace
  from pathlib import Path
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as directory:
   producer=MaterialProducer.__new__(MaterialProducer);producer.config={'web_cards':{}};producer.catalog=SimpleNamespace(path=Path(directory)/'catalog.sqlite3')
   producer.stop_event=threading.Event();producer.selection={'old':True};entered=threading.Event();release=threading.Event()
   def scan(*args):entered.set();release.wait(2);raise sqlite3.OperationalError('database is locked')
   with patch('cards.api.web_card_service__enabled',return_value=True),patch('browser.web_page_queue.queue.select',side_effect=scan):
    thread=threading.Thread(target=producer.refresh_selection);thread.start()
    try:
     self.assertTrue(entered.wait(1));self.assertEqual(producer.selection,{'old':True});self.assertTrue(thread.is_alive())
    finally:release.set();thread.join(3)
   self.assertFalse(thread.is_alive());self.assertEqual(producer.selection,{'old':True})
   self.assertIn('database is locked',(Path(directory)/'web-selection-discovery.json').read_text())
   producer.stop_event.set()
   with patch('cards.api.web_card_service__enabled',return_value=True),patch('browser.web_page_queue.queue.select') as select:
    producer.refresh_selection();select.assert_not_called()


class SeedTraceIsolationTests(unittest.TestCase):
 def make_producer(self, blocked):
  import tempfile,sqlite3
  from pathlib import Path
  from contextlib import contextmanager
  from types import SimpleNamespace
  directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);path=Path(directory.name)/'catalog.sqlite3'
  with sqlite3.connect(path) as db:db.execute('CREATE TABLE web_page_queue(paper_id TEXT,state TEXT)')
  @contextmanager
  def connect():
   db=sqlite3.connect(path)
   try:
    with db:yield db
   finally:db.close()
  catalog=SimpleNamespace(path=path,connect=connect)
  with patch('core.api.catalog__Catalog',return_value=catalog),patch('browser.web_page_queue.install'),patch.object(MaterialProducer,'run',blocked):
   return MaterialProducer({'catalog_path':str(path),'web_cards':{'material_prepare_workers':1}})

 def test_long_material_round_does_not_starve_repeated_seed_observation(self):
  import threading
  entered=threading.Event();observed=threading.Event();calls=[]
  def blocked(producer,worker=0):entered.set();producer.stop_event.wait(3)
  producer=self.make_producer(blocked)
  def monitor(config):
   calls.append(threading.get_ident())
   if len(calls)>=3:observed.set()
  with patch('core.api.seed_focus__monitor',side_effect=monitor),patch('browser.web_page_queue.SEED_TRACE_INTERVAL_SECONDS',.01,create=True):
   producer.start()
   try:
    self.assertTrue(entered.wait(1));self.assertTrue(observed.wait(1));self.assertTrue(producer.threads[0].is_alive())
    self.assertEqual(len(set(calls)),1);self.assertNotEqual(calls[0],producer.threads[0].ident)
   finally:producer.stop()
   count=len(calls);time.sleep(.03);self.assertEqual(len(calls),count)
  self.assertFalse(producer.seed_trace_thread.is_alive())

 def test_monitor_error_is_recorded_and_next_round_recovers(self):
  import threading,json
  done=threading.Event();calls=[]
  def blocked(producer,worker=0):producer.stop_event.wait(3)
  producer=self.make_producer(blocked)
  def monitor(config):
   calls.append(1)
   if len(calls)==1:raise ValueError('changed original evidence')
   done.set()
  with patch('core.api.seed_focus__monitor',side_effect=monitor),patch('browser.web_page_queue.SEED_TRACE_INTERVAL_SECONDS',.01,create=True):
   producer.start()
   try:self.assertTrue(done.wait(1))
   finally:producer.stop()
  error=json.loads((producer.catalog.path.parent/'seed-tracking-error.json').read_text());self.assertEqual(error['error'],'changed original evidence')
  worker=json.loads((producer.catalog.path.parent/'seed-tracking-worker.json').read_text());self.assertGreaterEqual(worker['completed_rounds'],1);self.assertEqual(worker['failed_rounds'],1)

 def test_stop_drains_one_inflight_monitor_without_overlap_or_restart(self):
  import threading
  active=threading.Event();release=threading.Event();stopped=threading.Event();calls=[]
  def blocked(producer,worker=0):producer.stop_event.wait(3)
  producer=self.make_producer(blocked)
  def monitor(config):calls.append(1);active.set();release.wait(2)
  with patch('core.api.seed_focus__monitor',side_effect=monitor),patch('browser.web_page_queue.SEED_TRACE_INTERVAL_SECONDS',.01,create=True):
   producer.start();self.assertTrue(active.wait(1))
   thread=threading.Thread(target=lambda:(producer.stop(),stopped.set()));thread.start()
   try:
    self.assertFalse(stopped.wait(.03));self.assertEqual(len(calls),1)
   finally:release.set();thread.join(2)
   self.assertTrue(stopped.is_set());self.assertEqual(len(calls),1);self.assertFalse(producer.seed_trace_thread.is_alive())
