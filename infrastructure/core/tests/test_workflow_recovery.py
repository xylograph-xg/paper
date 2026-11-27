import json,tempfile,time,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.catalog import Catalog
from review.card_review_queue import install as install_reviews
from correction.card_correction_queue import install as install_corrections
from core.workflow_recovery import scan, decorate, run_once

class WorkflowRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cat=Catalog(self.root/'catalog.sqlite3')
  install_reviews(self.cat);install_corrections(self.cat)
  self.pid=self.cat.upsert({'title':'Organic test','doi':'10.1000/test'})
  self.config={'catalog_path':str(self.cat.path),'automatic_issue_handling':{'enabled':True}}
  with self.cat.connect() as db:db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,error,updated) VALUES('review',?,'card','source','test','needs_user',?,'{}','unknown receipt','now')",(self.pid,str(self.root/'review')))
 def tearDown(self):self.tmp.cleanup()
 def test_all_blockers_are_durable_and_rechecked_without_mutating_science(self):
  with patch('core.control.pause_decision') as pause:
   pause.return_value.allowed=True
   first=scan(self.cat,self.config);second=scan(self.cat,self.config)
  self.assertEqual(first['counts'],{'review':1});self.assertEqual(second['counts'],first['counts'])
  with self.cat.connect() as db:
   self.assertEqual(db.execute('select checks from workflow_recovery_jobs').fetchone()[0],2)
   self.assertEqual(db.execute('select state,result from card_review_jobs').fetchone()[:],('needs_user','{}'))
 def test_recovery_display_requires_fresh_worker_heartbeat(self):
  with patch('core.control.pause_decision') as pause:
   pause.return_value.allowed=True;scan(self.cat,self.config)
  r=decorate(self.config,'review',{'counts':{'needs_user':1},'jobs':[{'id':'review','state':'needs_user'}]})
  self.assertEqual(r['counts']['recovery_pending'],1);self.assertEqual(r['jobs'][0]['original_state'],'needs_user')
  (self.root/'workflow-recovery-status.json').write_text(json.dumps({'updated':time.time()-200}))
  r=decorate(self.config,'review',{'counts':{'needs_user':1},'jobs':[]});self.assertNotIn('recovery_pending',r['counts'])
 def test_completed_job_leaves_active_recovery(self):
  with patch('core.control.pause_decision') as pause:
   pause.return_value.allowed=True;scan(self.cat,self.config)
   with self.cat.connect() as db:db.execute("update card_review_jobs set state='ready'")
   self.assertEqual(scan(self.cat,self.config)['counts'],{})
  with self.cat.connect() as db:self.assertEqual(db.execute('select state from workflow_recovery_jobs').fetchone()[0],'advanced')
 def test_active_loop_invokes_existing_actions_and_never_connects_browser(self):
  with patch('core.control.pause_decision') as pause,patch('review.review_channel_recovery.recover',return_value={'recovered':[]}) as recover,patch('correction.card_correction_queue.sync',return_value=0) as sync,patch('correction.recover_saved_publication.run_once',return_value=[]) as publish,patch('review.review_cycle.run_once',return_value={}) as cycle,patch('browser.web_pool_open.request_shared',return_value={}) as owner:
   pause.return_value.allowed=True;r=run_once(self.cat,self.config)
  recover.assert_called_once();sync.assert_called_once();cycle.assert_called_once();owner.assert_called_once_with(self.config,ensure_page=False)
  self.assertEqual(len(r['actions']),5);publish.assert_called_once()

 def test_background_maintenance_skips_duplicate_science_cycle(self):
  with patch('core.control.pause_decision') as pause,patch('review.review_channel_recovery.recover') as recover,patch('correction.card_correction_queue.sync') as sync,patch('correction.recover_saved_publication.run_once') as publish,patch('review.review_cycle.run_once') as cycle,patch('browser.web_pool_open.request_shared') as owner:
   pause.return_value.allowed=True
   for action in (recover,sync,publish,owner):action.return_value={}
   result=run_once(self.cat,self.config,maintain_review_cycle=False)
  cycle.assert_not_called()
  self.assertEqual([entry['action'] for entry in result['actions']],['unsent_reviews','saved_publication','corrections','owner_reconcile'])

 def test_stop_before_scan_preserves_jobs_and_does_no_actions(self):
  with patch('core.workflow_recovery.scan') as scan_mock:
   result=run_once(self.cat,self.config,stopping=lambda:True)
  self.assertEqual(result['state'],'stopping');scan_mock.assert_not_called()
  with self.cat.connect() as db:self.assertEqual(db.execute('select state,result from card_review_jobs').fetchone()[:],('needs_user','{}'))
 def test_stop_after_one_recovery_does_not_enter_more_work(self):
  import threading
  stop=threading.Event()
  def finish_current(*args):stop.set();return {'recovered':[]}
  with patch('review.review_channel_recovery.recover',side_effect=finish_current),patch('correction.recover_saved_publication.run_once') as publish,patch('review.review_cycle.run_once') as cycle,patch('browser.web_pool_open.request_shared') as owner:
   result=run_once(self.cat,self.config,stopping=stop.is_set)
  self.assertEqual(result['state'],'stopping');self.assertEqual(len(result['actions']),1)
  publish.assert_not_called();cycle.assert_not_called();owner.assert_not_called()
