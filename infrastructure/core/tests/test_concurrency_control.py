import json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from concurrent.futures import ThreadPoolExecutor
from core.concurrency_control import settings, set_limit, set_limits, set_minimum, apply
from core.control import mutate_record, pause_decision
from browser.page_retirement import may_retire

class ConcurrencyControl(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.config={'catalog_path':str(Path(self.tmp.name)/'catalog.sqlite3'),'fetch_pipeline':{'download_workers':8,'fallback_workers':4},'web_cards':{'target_pool_pages':10,'max_parallel_jobs':10,'max_total_pages':20}}
 def test_increase_and_decrease_update_limits_without_restarting(self):
  self.assertEqual(set_limit(self.config,'fetch',24)['fetch'],24)
  self.assertEqual(self.config['fetch_pipeline']['download_workers'],16);self.assertEqual(self.config['fetch_pipeline']['fallback_workers'],8)
  set_limit(self.config,'cards',20);self.assertEqual(self.config['web_cards']['max_parallel_jobs'],20)
  set_limit(self.config,'cards',4);self.assertEqual(self.config['web_cards']['target_pool_pages'],4)
  self.assertEqual(settings(self.config)['fetch'],24)
 def test_new_fetch_options_apply_full_download_capacity(self):
  from core.catalog import validate_fetch_capacity
  for total in (32,54,72,85,100,120,150):
   self.assertEqual(set_limit(self.config,'fetch',total)['fetch'],total)
   policy=self.config['fetch_pipeline']
   self.assertEqual(policy['download_workers']+policy['fallback_workers'],total)
   validate_fetch_capacity(policy)
   self.assertLessEqual(policy['seed_workers'],10)
   self.assertLessEqual(policy['topic_workers'],4)
 def test_invalid_values_cannot_raise_total_page_limit(self):
  for value in [0,21,True]:
   with self.assertRaises(ValueError):set_limit(self.config,'cards',value)
  with self.assertRaises(ValueError):set_limit(self.config,'fetch',151)
 def test_parallel_edits_preserve_other_task_setting(self):
  with ThreadPoolExecutor(2) as p:
   a=p.submit(set_limit,self.config,'fetch',24);b=p.submit(set_limit,self.config,'cards',16);a.result();b.result()
  self.assertEqual(settings(self.config)['fetch'],24);self.assertEqual(settings(self.config)['cards'],16)
 def test_busy_and_unknown_pages_never_retire(self):
  for state,ledger in [('busy','submitted'),('needs_inspection','needs_inspection'),('ready_blank','submission_started')]:
   self.assertFalse(may_retire(state,ledger,'https://chatgpt.com/',0,0))
 def test_finished_page_needs_saved_and_live_hashes_and_no_stream(self):
  self.assertTrue(may_retire('ready','response_saved','https://chatgpt.com/c/own',1,1,live_hash='same',saved_hash='same'))
  self.assertFalse(may_retire('ready','response_saved','https://chatgpt.com/c/own',1,1,streaming=True,live_hash='same',saved_hash='same'))
  self.assertFalse(may_retire('ready','response_saved','https://chatgpt.com/c/own',1,1,live_hash='changed',saved_hash='same'))
 def test_blank_page_with_draft_never_retire(self):
  self.assertTrue(may_retire('ready_blank',None,'https://chatgpt.com/',0,0))
  self.assertFalse(may_retire('ready_blank',None,'https://chatgpt.com/',0,0,draft='user draft'))

class FourLaneConcurrencyControls(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.config={'catalog_path':str(self.root/'catalog.sqlite3'),
   'fetch_pipeline':{'download_workers':16,'fallback_workers':8},
   'web_cards':{'enabled':True,'max_parallel_jobs':20,'max_total_pages':20,
                'shared_window':{'enabled':True,'slot_count':20}},
   'card_review':{'enabled':True,'parallel_jobs':4},
   'card_correction':{'enabled':True,'parallel_jobs':4}}
 def write(self,name,value):
  path=self.root/name;path.write_text(json.dumps(value));return path
 def test_new_fields_have_defaults_without_persisting_or_resuming(self):
  old=self.write('concurrency-control.json',{'fetch':24,'cards':20,'review':6,'updated':123,'marker':'keep'})
  pauses=[self.write(name,{'paused_by_user':True,'reason':'existing user pause'}) for name in
    ('web-card-control.json','card-review-control.json','card-correction-control.json')]
  before={p:p.read_bytes() for p in [old,*pauses]}
  result=settings(self.config)
  self.assertEqual((result['correction'],result['cards_min_pages']),(4,8))
  self.assertEqual(result['review'],6)
  apply(self.config)
  self.assertEqual({p:p.read_bytes() for p in before},before)
  self.assertEqual(self.config['web_cards']['target_pool_pages'],20)
  self.assertEqual(self.config['web_cards']['min_reserved_pages'],8)
  self.assertFalse(any(pause_decision(self.config,scope).allowed for scope in ('web_cards','card_review','card_correction')))
 def test_old_lower_maximum_is_preserved_until_an_explicit_edit(self):
  old=self.write('concurrency-control.json',{'cards':6,'review':4,'fetch':24})
  before=old.read_bytes();self.assertEqual(settings(self.config)['cards_min_pages'],6)
  self.assertEqual(apply(self.config)['cards'],6);self.assertEqual(old.read_bytes(),before)
  self.assertEqual(set_limit(self.config,'correction',7)['cards'],6)
  record=json.loads(old.read_text());self.assertEqual(record['cards_min_pages'],6)
  result=set_limits(self.config,{'cards':8,'cards_min_pages':8})
  self.assertEqual((result['cards'],result['cards_min_pages']),(8,8))
 def test_card_maximum_cannot_implicitly_reduce_a_reservation(self):
  with self.assertRaisesRegex(ValueError,'不能低于'):
   set_limit(self.config,'cards',7)
  self.assertFalse((self.root/'concurrency-control.json').exists())
  self.assertEqual(set_limits(self.config,{'cards':10,'cards_min_pages':10})['cards_min_pages'],10)
  before=(self.root/'concurrency-control.json').read_bytes()
  history=(self.root/'control-events.jsonl').read_bytes()
  with self.assertRaisesRegex(ValueError,'不能低于'):
   set_limit(self.config,'cards',8)
  self.assertEqual((self.root/'concurrency-control.json').read_bytes(),before)
  self.assertEqual((self.root/'control-events.jsonl').read_bytes(),history)
  self.assertEqual(set_limits(self.config,{'cards':4,'cards_min_pages':4})['cards'],4)
 def test_pause_controls_are_independent_and_malformed_correction_fails_closed(self):
  cards=self.write('web-card-control.json',{'paused_by_user':True})
  review=self.write('card-review-control.json',{'paused_by_user':False})
  before={p:p.read_bytes() for p in (cards,review)}
  correction=self.root/'card-correction-control.json'
  mutate_record(correction,{'paused_by_user':True},event='user_correction_pause')
  self.assertFalse(pause_decision(self.config,'card_correction').allowed)
  self.assertTrue(pause_decision(self.config,'card_review').allowed)
  mutate_record(correction,{'paused_by_user':False},event='user_correction_resume')
  self.assertTrue(pause_decision(self.config,'card_correction').allowed)
  self.assertEqual({p:p.read_bytes() for p in before},before)
  correction.write_text('{bad')
  self.assertEqual(pause_decision(self.config,'card_correction').state,'invalid')
  self.assertTrue(pause_decision(self.config,'card_review').allowed)
 def test_correction_limit_changes_keep_fixed_twenty_and_other_controls(self):
  review=self.write('card-review-control.json',{'paused_by_user':True})
  before=review.read_bytes();result=set_limit(self.config,'correction',12)
  self.assertEqual(result['cards'],20);self.assertEqual(result['review'],4)
  self.assertEqual(self.config['card_correction']['parallel_jobs'],12)
  self.assertEqual(self.config['web_cards']['target_pool_pages'],20)
  self.assertEqual(review.read_bytes(),before)
  for target in ('correction','cards_min_pages'):
   for invalid in (0,21,True,1.0,'8'):
    with self.assertRaises(ValueError):set_limit(self.config,target,invalid)
 def test_concurrent_maximum_and_minimum_edits_cannot_publish_an_invalid_pair(self):
  set_limits(self.config,{'cards':20,'cards_min_pages':8})
  with ThreadPoolExecutor(2) as executor:
   jobs=[executor.submit(set_limit,self.config,'cards',8),executor.submit(set_limit,self.config,'cards_min_pages',12)]
   outcomes=[]
   for job in jobs:
    try:job.result();outcomes.append('changed')
    except ValueError:outcomes.append('rejected')
  self.assertEqual(sorted(outcomes),['changed','rejected'])
  values=settings(self.config);self.assertGreaterEqual(values['cards'],values['cards_min_pages'])
 def test_validation_callback_failure_keeps_record_and_history(self):
  record=self.write('local-control.json',{'saved':1})
  before=record.read_bytes()
  def reject(after):raise ValueError('synthetic control conflict')
  with self.assertRaisesRegex(ValueError,'synthetic control conflict'):
   mutate_record(record,{'saved':2},validate=reject)
  self.assertEqual(record.read_bytes(),before);self.assertFalse((self.root/'control-events.jsonl').exists())
 def test_adjusting_minimum_raises_only_a_smaller_maximum_and_preserves_pauses(self):
  set_limits(self.config,{'cards':8,'cards_min_pages':8})
  pauses=[self.write(name,{'paused_by_user':True,'reason':'existing user pause','marker':'keep'}) for name in
    ('web-card-control.json','card-review-control.json','card-correction-control.json')]
  before={path:path.read_bytes() for path in pauses}
  increased=set_minimum(self.config,12)
  self.assertEqual((increased['cards'],increased['cards_min_pages']),(12,12))
  set_limit(self.config,'cards',18)
  decreased=set_minimum(self.config,4)
  self.assertEqual((decreased['cards'],decreased['cards_min_pages']),(18,4))
  self.assertEqual(self.config['web_cards']['target_pool_pages'],20)
  self.assertEqual({path:path.read_bytes() for path in pauses},before)
 def test_minimum_change_uses_latest_maximum_under_lock(self):
  import threading
  from unittest.mock import patch
  set_limits(self.config,{'cards':8,'cards_min_pages':8})
  minimum_waiting=threading.Event();resume_minimum=threading.Event()
  def delay_minimum(path,changes,**options):
   if 'cards_min_pages' in changes:
    minimum_waiting.set()
    if not resume_minimum.wait(3):raise AssertionError('minimum edit wait timed out')
   return mutate_record(path,changes,**options)
  with patch('core.concurrency_control.mutate_record',side_effect=delay_minimum):
   with ThreadPoolExecutor(1) as executor:
    minimum_edit=executor.submit(set_minimum,self.config,12)
    try:
     self.assertTrue(minimum_waiting.wait(3))
     set_limit(self.config,'cards',18)
    finally:resume_minimum.set()
    result=minimum_edit.result(timeout=3)
  self.assertEqual((result['cards'],result['cards_min_pages']),(18,12))
  stored=json.loads((self.root/'concurrency-control.json').read_text())
  self.assertEqual(stored['cards'],18)
 def test_strict_minimum_setter_still_rejects_while_minimum_helper_links_maximum(self):
  set_limits(self.config,{'cards':8,'cards_min_pages':8})
  before=(self.root/'concurrency-control.json').read_bytes()
  with self.assertRaisesRegex(ValueError,'不能低于'):
   set_limit(self.config,'cards_min_pages',12)
  self.assertEqual((self.root/'concurrency-control.json').read_bytes(),before)
  self.assertEqual(set_minimum(self.config,12)['cards'],12)
  for invalid in (0,21,True,1.0,'8'):
   with self.assertRaises(ValueError):set_minimum(self.config,invalid)

class LiveFetchAdjustment(unittest.TestCase):
 def test_increase_starts_more_and_reduction_drains_existing(self):
  import threading,time
  from unittest.mock import patch
  from fetch.tests.test_fetch_pipeline import FetchFixtures
  from fetch.fetching import fetch_loop
  fixture=FetchFixtures();fixture.setUp();self.addCleanup(fixture.tearDown)
  for i in range(5):fixture.catalog.enqueue('acquire',fixture.catalog.upsert(fixture.record(i)))
  set_limit(fixture.config,'fetch',1)
  lock=threading.Lock();started=[];gates=[];stop=threading.Event();errors=[]
  def acquire(catalog,config,job):
   gate=threading.Event()
   with lock:started.append(job['id']);gates.append(gate)
   if not gate.wait(12):raise AssertionError('test gate timed out')
   return {'available':False}
  def run():
   try:fetch_loop(fixture.catalog,fixture.config,True,stop.is_set)
   except BaseException as exc:errors.append(exc)
  def wait_for(count):
   deadline=time.monotonic()+5
   while len(started)<count and time.monotonic()<deadline:time.sleep(.05)
   self.assertEqual(len(started),count)
  with patch('fetch.fetching.run_acquisition',side_effect=acquire):
   thread=threading.Thread(target=run);thread.start()
   try:
    wait_for(1);set_limit(fixture.config,'fetch',4);wait_for(3)
    set_limit(fixture.config,'fetch',1);time.sleep(1.3)
    self.assertEqual(len(started),3);self.assertTrue(all(not g.is_set() for g in gates))
    gates[0].set();gates[1].set();time.sleep(1.3)
    self.assertEqual(len(started),3);self.assertFalse(gates[2].is_set())
   finally:
    stop.set()
    for gate in gates:gate.set()
    thread.join(8)
   self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

class ReviewCorrectionMinimums(FourLaneConcurrencyControls):
 def test_each_minimum_raises_only_its_lane_and_keeps_larger_maximum(self):
  set_minimum(self.config,7,'review')
  result=settings(self.config)
  self.assertEqual((result['review'],result['review_min_pages'],result['correction']),(7,7,4))
  set_limit(self.config,'review',15)
  set_minimum(self.config,2,'review')
  self.assertEqual(settings(self.config)['review'],15)
  set_minimum(self.config,5,'correction')
  self.assertEqual(settings(self.config)['correction'],5)
 def test_total_capacity_rejection_is_atomic(self):
  set_minimum(self.config,4,'review')
  path=self.root/'concurrency-control.json';before=path.read_bytes()
  with self.assertRaisesRegex(ValueError,'合计不能超过20'):
   set_minimum(self.config,10,'review')
  self.assertEqual(path.read_bytes(),before)
 def test_minimum_changes_preserve_all_pause_records(self):
  paths=[self.write(name,{'paused_by_user':True}) for name in ('web-card-control.json','card-review-control.json','card-correction-control.json')]
  before={p:p.read_bytes() for p in paths}
  set_minimum(self.config,5,'review');set_minimum(self.config,4,'correction')
  self.assertEqual({p:p.read_bytes() for p in paths},before)
