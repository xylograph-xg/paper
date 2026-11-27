import hashlib
import json
import tempfile
import time
import unittest
from core.api import paths__WorkspacePath as Path
from core.catalog import Catalog
from cards.web_card_queue import install
from fetch.seed_expansion import expand_when_idle

class SeedExpansion(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.catalog=Catalog(self.root/'catalog.sqlite3');install(self.catalog)
  self.config={'catalog_path':str(self.catalog.path),'fetch_pipeline':{'auto_seed_expansion':True},'discovery_channels':['seed_related']}
 def paper(self,score,metadata=None):
  pid=self.catalog.upsert({'title':'Organic triplet exciton emitter '+str(score),'doi':'10.1000/'+str(score),**(metadata or {})})
  source=self.root/(pid+'.pdf');source.write_bytes(b'synthetic source');h=hashlib.sha256(source.read_bytes()).hexdigest()
  card=self.root/(pid+'.json');card.write_text(json.dumps({'paper_evaluation':{'overall_quality':{'score':score,'reason':'有充分对照','source_pages':[1]}},'meta':{'provider':'chatgpt','source_original_sha256':h}}))
  self.catalog.update(pid,acquisition='available',asset_hash=h,asset_path=str(source),card_path=str(card))
  with self.catalog.connect() as db:db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,provider,updated) VALUES(?,?,?,?,'completed','chatgpt','now')",(pid,h,'test','{}'))
  return pid
 def test_highest_quality_then_next_nonseed_and_cards_unchanged(self):
  low=self.paper(72);high=self.paper(94);path=Path(self.catalog.get(high)['card_path']);before=path.read_bytes()
  self.assertEqual(expand_when_idle(self.catalog,self.config)['paper_id'],high)
  self.assertTrue(self.catalog.get(high)['seed']);self.assertEqual(path.read_bytes(),before)
  self.assertEqual(expand_when_idle(self.catalog,self.config)['paper_id'],low)
 def test_active_queue_and_ready_retry_prevent_promotion(self):
  pid=self.paper(90);jid=self.catalog.enqueue('acquire',pid)
  self.assertEqual(expand_when_idle(self.catalog,self.config)['state'],'download_queue_busy')
  self.catalog.finish(jid,'done');self.catalog.retain_discovery([{'title':'Organic triplet new','doi':'10.1000/new'}],{})
  self.assertEqual(expand_when_idle(self.catalog,self.config)['state'],'retry_candidate_ready')
  self.assertFalse(self.catalog.get(pid)['seed'])
 def test_future_retries_allow_new_seed_without_resetting_retry(self):
  pid=self.paper(90);self.catalog.retain_discovery([{'title':'Organic triplet new','doi':'10.1000/new'}],{})
  retry=time.time()+3600;self.catalog.pending_result('10.1000/new','pending',retry_at=retry)
  self.assertEqual(expand_when_idle(self.catalog,self.config)['paper_id'],pid)
  with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT retry_at FROM discovery_pending').fetchone()[0],retry)
 def test_user_removed_and_uncertain_identity_are_protected(self):
  self.paper(99,{'user_seed_disabled':True});self.paper(98,{'identity_review_required':True});pid=self.paper(81)
  self.assertEqual(expand_when_idle(self.catalog,self.config)['paper_id'],pid)
 def test_missing_bad_rating_or_changed_source_not_promoted(self):
  for score in (None,True,101,float('nan')):self.paper(score)
  pid=self.paper(95);Path(self.catalog.get(pid)['asset_path']).write_bytes(b'changed')
  self.assertEqual(expand_when_idle(self.catalog,self.config)['state'],'waiting_scored_cards')
 def test_content_derived_from_manual_seed_is_not_promoted(self):
  from fetch.manual_seed_lineage import install as install_lineage
  install_lineage(self.catalog)
  root=self.paper(50,{'selected_as_seed':True});derived=self.paper(99)
  with self.catalog.connect() as db:
   db.execute('INSERT INTO manual_seed_roots VALUES(?,?,?,?)',(root,'/tmp/seed.pdf','hash',time.time()))
   db.execute('INSERT INTO manual_seed_lineage VALUES(?,?,?)',(derived,root,time.time()))
  self.assertEqual(expand_when_idle(self.catalog,self.config)['state'],'waiting_scored_cards')
  self.assertFalse(self.catalog.get(derived)['seed'])
 def test_off_topic_machine_learning_card_is_not_promoted(self):
  pid=self.paper(99,{'title':'Machine-learning risk minimization for generic tabular data'})
  self.assertEqual(expand_when_idle(self.catalog,self.config)['state'],'waiting_scored_cards')
  self.assertFalse(self.catalog.get(pid)['seed'])
 def test_pause_is_persistent_and_no_fallback_scores(self):
  self.paper(90);(self.root/'fetch-control.json').write_text('{"paused_by_user":true}')
  self.assertEqual(expand_when_idle(self.catalog,self.config)['state'],'paused')
  self.assertFalse(any(p['seed'] for p in self.catalog.list()))
