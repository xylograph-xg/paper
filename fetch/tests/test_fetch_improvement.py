import json,tempfile,time,unittest,urllib.error
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch,Mock
from fetch.seed_crossref_fallback import discover_seed
from fetch.network import ProviderClient, DeferredRequest
from fetch.fetchpdf_bridge import install_http_guards
from fetch.tests.test_fetch_pipeline import FetchFixtures

class CrossrefSeedTests(unittest.TestCase):
 def test_exact_doi_references_keep_lineage_and_independent_cursor(self):
  with tempfile.TemporaryDirectory() as d:
   client=Mock();client.get.side_effect=[{'message':{'DOI':'10.1000/a','title':['Organic seed'],'reference':[{'DOI':'10.1000/b'},{'DOI':'10.1000/c'}]}},{'message':{'DOI':'10.1000/b','title':['Organic emitter']}},DeferredRequest('crossref',time.time()+100,429)]
   records,resolved,pos,errors=discover_seed(client,d,{'doi':'10.1000/a','title':'seed'},{})
   self.assertEqual(records[0]['discovered_from_seed_dois'],['10.1000/a']);self.assertEqual(pos['v3:crossref-references:10.1000/a']['offset'],1);self.assertTrue(errors)
   client.get.reset_mock();discover_seed(client,d,{'doi':'10.1000/a'},pos);client.get.assert_not_called()
 def test_resource_404_does_not_poison_provider(self):
  with tempfile.TemporaryDirectory() as d:
   error=urllib.error.HTTPError('https://api.crossref.org/works/missing',404,'missing',{},None)
   with patch('fetch.network.urllib.request.urlopen',side_effect=error):
    with self.assertRaises(urllib.error.HTTPError):ProviderClient(d).get(error.url,provider='crossref')
   state=json.loads((Path(d)/'network-state.json').read_text());self.assertFalse(state['crossref'].get('retry_at'))
 def test_wrong_reference_identity_preserves_offset(self):
  with tempfile.TemporaryDirectory() as d:
   client=Mock();client.get.side_effect=[{'message':{'DOI':'10.1000/a','title':['seed'],'reference':[{'DOI':'10.1000/b'}]}},{'message':{'DOI':'10.1000/wrong','title':['wrong']}}]
   records,_,pos,errors=discover_seed(client,d,{'doi':'10.1000/a'},{})
   self.assertEqual(records,[]);self.assertEqual(pos['v3:crossref-references:10.1000/a']['offset'],0);self.assertTrue(errors)

class HTTPDiagnosticsTests(unittest.TestCase):
 def setUp(self):
  import os
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  patcher=patch.dict(os.environ,{'PAPER_NETWORK_STATE_DIR':self.temp.name});patcher.start();self.addCleanup(patcher.stop)
 def test_cooldown_records_real_source_and_never_sends(self):
  import requests
  attempts=[]
  with patch('fetch.network.ready',side_effect=DeferredRequest('openalex',time.time()+100,429)),patch('core.services.public_url'),patch('fetch.public_http.requests_adapter'):
   original=install_http_guards(True,attempts)
   try:
    with self.assertRaises(DeferredRequest):requests.get('https://api.openalex.org/works')
   finally:requests.sessions.Session.send=original
  self.assertEqual(attempts[0]['kind'],'deferred');self.assertEqual(attempts[0]['code'],429)
 def test_success_clears_host_failures_and_checks_global_alias(self):
  import requests
  attempts=[];response=Mock(status_code=200,headers={});response.iter_content.return_value=[]
  with patch('requests.sessions.Session.send',return_value=response),patch('fetch.network.ready') as ready,patch('fetch.network.pace'),patch('fetch.network.succeeded') as succeeded,patch('core.services.public_url'),patch('fetch.public_http.requests_adapter'),patch('fetch.acquisition_budget.remaining',return_value=12):
   original=install_http_guards(True,attempts)
   try:requests.Session().send(requests.Request('GET','https://api.openalex.org/works').prepare())
   finally:requests.sessions.Session.send=original
  self.assertIn(('openalex',),[x.args for x in ready.call_args_list]);succeeded.assert_called_once();self.assertEqual(attempts,[])

class FailurePolicyTests(FetchFixtures):
 def test_transient_channel_failure_does_not_become_terminal_not_found(self):
  from fetch.fetch_policy import begin, finish
  pid=self.catalog.upsert(self.record());begin(self.catalog,self.catalog.get(pid),self.config)
  self.catalog.event(pid,'acquisition_pending',{'attempts':[{'kind':'deferred','code':429,'retry_at':time.time()+3600,'error':'rate limit'},{'kind':'not_found','error':'aggregate miss'}]})
  finish(self.catalog,pid,False,'fallback',self.config)
  with self.catalog.connect() as db:r=db.execute('select * from fetch_targets where paper_id=?',(pid,)).fetchone()
  self.assertEqual(r['state'],'ready');self.assertGreater(r['retry_at'],time.time()+3500)

class ChemRxivTests(unittest.TestCase):
 def test_cached_source_is_bound_to_exact_doi_and_title(self):
  from fetch.chemrxiv_enrichment import resolve
  with tempfile.TemporaryDirectory() as d:
   client=Mock();client.get.return_value={'doi':'10.26434/chemrxiv-2026-abc','title':'Organic triplet emission experiment','asset':{'original':{'url':'https://www.cambridge.org/paper.pdf'}}}
   m={'doi':'10.26434/chemrxiv-2026-abc','title':'Organic triplet emission experiment','pdf_urls':[]}
   row=resolve(client,d,m);self.assertEqual(row['pdf_urls'],['https://www.cambridge.org/paper.pdf'])
   resolve(client,d,m);self.assertEqual(client.get.call_count,1)
   with self.assertRaises(ValueError):resolve(client,d,{**m,'title':'Entirely unrelated document'})
 def test_wrong_doi_or_foreign_download_host_is_blocked(self):
  from fetch.chemrxiv_enrichment import resolve
  with tempfile.TemporaryDirectory() as d:
   client=Mock();client.get.return_value={'doi':'10.26434/chemrxiv-wrong','title':'Organic triplet emission experiment','asset':{'url':'http://localhost/paper.pdf'}}
   with self.assertRaises(ValueError):resolve(client,d,{'doi':'10.26434/chemrxiv-2026-abc','title':'Organic triplet emission experiment'})

class ResourceWaitTests(FetchFixtures):
 def test_lock_contention_consumes_no_retry_budget_or_fallback(self):
  from fetch.fetch_policy import begin, finish, record_url
  from fetch.fetching import complete_acquisition
  row=self.record();row['pdf_urls']=['https://www.cambridge.org/paper.pdf'];self.catalog.retain_discovery([row],{})
  pid=self.catalog.upsert(row);key=row['doi'];begin(self.catalog,self.catalog.get(pid),self.config,key)
  wait=time.time()+3;record_url(self.catalog,pid,row['pdf_urls'][0],'slot busy',kind='resource_wait',retry_at=wait)
  self.catalog.event(pid,'acquisition_fast_pending',{'attempts':[{'kind':'resource_wait','retry_at':wait,'code':None}]})
  finish(self.catalog,pid,False,'fast',self.config)
  with self.catalog.connect() as db:
   target=db.execute('select * from fetch_targets where paper_id=?',(pid,)).fetchone();url=db.execute('select * from fetch_urls where paper_id=?',(pid,)).fetchone()
  self.assertEqual(target['attempts'],0);self.assertEqual(url['attempts'],0);self.assertEqual(target['retry_at'],wait)
  self.config['pdf_retrieval']['enabled']=True
  jid=self.catalog.enqueue('acquire',pid,{'pending_key':key});complete_acquisition(self.catalog,self.config,{'id':jid,'kind':'acquire','paper_id':pid,'payload':{'pending_key':key}},{'available':False})
  with self.catalog.connect() as db:self.assertFalse(db.execute("select 1 from jobs where kind='acquire_fallback'").fetchone())

class WaitReconciliationTests(FetchFixtures):
 def test_only_verified_preflight_wait_is_released_preserving_count(self):
  from fetch.fetch_policy import begin
  from fetch.fetch_wait_recovery import reconcile
  row=self.record();row['pdf_urls']=['https://www.cambridge.org/paper.pdf'];self.catalog.retain_discovery([row],{})
  pid=self.catalog.upsert(row);begin(self.catalog,self.catalog.get(pid),self.config,row['doi'])
  self.catalog.event(pid,'acquisition_fast_pending',{'attempts':[{'url':row['pdf_urls'][0],'kind':'deferred','code':None,'retry_at':time.time()-1}]})
  with self.catalog.connect() as db:db.execute('update fetch_targets set retry_at=? where paper_id=?',(time.time()+10000,pid))
  self.assertEqual(reconcile(self.catalog),[pid])
  with self.catalog.connect() as db:r=db.execute('select * from fetch_targets where paper_id=?',(pid,)).fetchone()
  self.assertEqual(r['attempts'],1);self.assertEqual(r['retry_at'],0)
 def test_http_failures_and_terminal_targets_are_preserved(self):
  from fetch.fetch_policy import begin
  from fetch.fetch_wait_recovery import reconcile
  pid=self.catalog.upsert(self.record());begin(self.catalog,self.catalog.get(pid),self.config)
  self.catalog.event(pid,'acquisition_fast_pending',{'attempts':[{'url':'https://www.cambridge.org/paper.pdf','kind':'deferred','code':429,'retry_at':time.time()-1}]})
  with self.catalog.connect() as db:db.execute("update fetch_targets set state='terminal',retry_at=? where paper_id=?",(time.time()+10000,pid))
  self.assertEqual(reconcile(self.catalog),[])
