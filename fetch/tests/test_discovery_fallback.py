import time
from unittest.mock import patch
from fetch.tests.test_fetch_pipeline import FetchFixtures
from fetch.discovery_bridge import discover

class DiscoveryFallback(FetchFixtures):
 def request(self,positions=None):
  return {'queries':['OLED'],'seeds':[],'preprints':{},'state_dir':str(self.root),'positions':positions or {},'discovery_channels':['oled_topic']}
 def crossref(self):
  return {'message':{'items':[{'DOI':'10.1000/new','title':['Organic OLED emitter']}],'next-cursor':'next-crossref'}}
 def test_empty_openalex_and_s2_continue_crossref_cursor(self):
  seen=[]
  def get(client,url,params=None,provider=None,xml=False):
   seen.append((provider,params))
   if provider=='openalex':return {'results':[],'meta':{'next_cursor':None}}
   if provider=='s2':return {'data':[]}
   return self.crossref()
  positions={'v2:crossref-topic:OLED':{'cursor':'original-crossref','snapshot':'2026-10-05'}}
  with patch('fetch.network.ProviderClient.get',new=get):out=discover(self.request(positions))
  self.assertEqual([p for p,_ in seen],['openalex','s2','crossref'])
  self.assertEqual(seen[-1][1]['cursor'],'original-crossref')
  self.assertTrue(seen[-1][1]['filter'].startswith('type:journal-article,until-created-date:2026-10-05,from-pub-date:'))
  self.assertEqual(len(out['pool']),1)
  self.assertTrue(out['positions']['v2:oa-topic:OLED']['done'])
 def test_provider_failure_mode_skips_crossref_when_primary_empty(self):
  seen=[]
  def get(client,url,params=None,provider=None,xml=False):
   seen.append(provider)
   if provider=='openalex':return {'results':[],'meta':{'next_cursor':None}}
   if provider=='s2':return {'data':[]}
   return self.crossref()
  request=self.request();request['network']={'crossref_topic_fallback':'provider_failure'}
  with patch('fetch.network.ProviderClient.get',new=get):out=discover(request)
  self.assertNotIn('crossref',seen);self.assertEqual(len(out['pool']),0)
 def test_crossref_topic_budget_caps_fallbacks(self):
  seen=[]
  def get(client,url,params=None,provider=None,xml=False):
   seen.append(provider)
   if provider=='openalex':return {'results':[],'meta':{'next_cursor':None}}
   if provider=='s2':return {'data':[]}
   return self.crossref()
  request=self.request();request['queries']=['a','b','c','d','e'];request['network']={'crossref_topic_fallback':'always','crossref_topic_budget':2,'topic_workers':1}
  with patch('fetch.network.ProviderClient.get',new=get):discover(request)
  self.assertEqual(seen.count('crossref'),2)

 def test_cooling_primary_does_not_block_s2_offset(self):
  seen=[]
  def get(client,url,params=None,provider=None,xml=False):
   seen.append((provider,params));return {'data':[{'paperId':'s1','title':'Organic OLED emitter'}],'next':301}
  positions={'v2:oa-topic:OLED':{'done':True,'next_scan_at':time.time()+3600},'v2:s2-topic:OLED':{'offset':201}}
  with patch('fetch.network.ProviderClient.get',new=get):out=discover(self.request(positions))
  self.assertEqual([p for p,_ in seen],['s2']);self.assertEqual(seen[0][1]['offset'],201)
  self.assertEqual(out['positions']['v2:s2-topic:OLED']['offset'],301)
 def test_both_cooling_sources_continue_crossref(self):
  positions={k:{'done':True,'next_scan_at':time.time()+3600} for k in ('v2:oa-topic:OLED','v2:s2-topic:OLED')}
  seen=[]
  def get(client,url,params=None,provider=None,xml=False):seen.append(provider);return self.crossref()
  with patch('fetch.network.ProviderClient.get',new=get):out=discover(self.request(positions))
  self.assertEqual(seen,['crossref']);self.assertEqual(len(out['pool']),1)
 def test_nonempty_primary_does_not_query_backups(self):
  seen=[]
  def get(client,url,params=None,provider=None,xml=False):
   seen.append(provider);return {'results':[{'id':'https://openalex.org/W1','title':'Organic OLED emitter'}],'meta':{'next_cursor':'next-oa'}}
  with patch('fetch.network.ProviderClient.get',new=get):out=discover(self.request())
  self.assertEqual(seen,['openalex']);self.assertEqual(out['positions']['v2:oa-topic:OLED']['cursor'],'next-oa')
 def test_failed_backup_does_not_commit_cursor_or_unblock_others(self):
  positions={k:{'done':True,'next_scan_at':time.time()+3600} for k in ('v2:oa-topic:OLED','v2:s2-topic:OLED')}
  positions['v2:crossref-topic:OLED']={'cursor':'unchanged','snapshot':'2026-10-05'}
  with patch('fetch.network.ProviderClient.get',side_effect=RuntimeError('source unavailable')):out=discover(self.request(positions))
  self.assertNotIn('v2:crossref-topic:OLED',out['positions'])
  self.assertTrue(out['warnings']);self.assertEqual(positions['v2:crossref-topic:OLED']['cursor'],'unchanged')
