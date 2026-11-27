import json,tempfile,threading,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from fetch.discovery_bridge import discover, distinct_seeds

class SeedParallelDiscovery(unittest.TestCase):
 def test_same_doi_has_one_slot(self):
  result=distinct_seeds([{'doi':'10.1000/A','title':'a'},{'doi':'https://doi.org/10.1000/a','title':'duplicate'},{'title':'no identifier'},{'doi':'10.1000/b','title':'b'}])
  self.assertEqual([s['doi'] for s in result],['10.1000/a','10.1000/b'])
 def test_distinct_seeds_overlap_with_independent_cursors(self):
  with tempfile.TemporaryDirectory() as folder:
   barrier=threading.Barrier(2);entered=[];mutex=threading.Lock()
   def get(client,url,params=None,provider=None,**kwargs):
    if '/works/https://doi.org/' in url:
     identifier=url.split('/https://doi.org/')[1]
     with mutex:entered.append(identifier)
     barrier.wait(timeout=3)
     return {'doi':identifier,'id':'W'+identifier[-1]}
    return {'results':[],'meta':{}}
   def parse(w):return {'title':'Organic emitter seed','doi':w['doi'],'openalex_id':w['id']}
   request={'state_dir':folder,'seeds':[{'doi':'10.1000/a','title':'A'},{'doi':'10.1000/b','title':'B'},{'doi':'10.1000/A','title':'duplicate'}],'queries':[],'preprints':{},'discovery_channels':['seed_related'],'network':{'seed_workers':2,'topic_workers':1}}
   with patch('fetch.network.ProviderClient.get',get),patch('fetch.discovery_bridge.oa_record',parse):result=discover(request)
   self.assertCountEqual(entered,['10.1000/a','10.1000/b'])
   self.assertEqual(set(result['seed_tasks']),{'10.1000/a','10.1000/b'})
   for identifier in entered:
    self.assertEqual(result['seed_tasks'][identifier]['state'],'completed')
    self.assertIn('v2:oa-references:'+identifier,result['positions'])
    self.assertIn('v2:oa-citations:'+identifier,result['positions'])
   status=json.loads((Path(folder)/'seed-discovery-status.json').read_text());self.assertEqual(status['seed_workers'],2)
 def test_exhausted_seed_retains_wait_without_network_or_cursor_reset(self):
  import time
  with tempfile.TemporaryDirectory() as folder:
   key='10.1000/a';positions={prefix+key:{'done':True,'next_scan_at':time.time()+3600} for prefix in ['v2:oa-references:','v2:oa-citations:']}
   request={'state_dir':folder,'seeds':[{'doi':key,'title':'A'}],'positions':positions,'queries':[],'preprints':{},'discovery_channels':['seed_related'],'network':{'seed_workers':2}}
   with patch('fetch.network.ProviderClient.get') as get:result=discover(request)
   get.assert_not_called();self.assertEqual(result['seed_tasks'][key]['state'],'waiting_next_scan');self.assertEqual(result['positions'],{})
