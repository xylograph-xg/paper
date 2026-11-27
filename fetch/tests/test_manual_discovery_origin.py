import tempfile
import unittest
from unittest.mock import patch
from fetch.discovery_bridge import discover
from core.record_contract import normalize

class ManualDiscoveryOrigin(unittest.TestCase):
    def test_real_discovery_checkpoint_carries_actual_parent_doi(self):
        with tempfile.TemporaryDirectory() as folder:
            def get(client,url,params=None,provider=None,**kwargs):
                if '/works/https://doi.org/' in url:return {'doi':'10.1000/root','id':'WROOT'}
                return {'results':[{'doi':'10.1000/child','id':'WCHILD'}],'meta':{}}
            def parse(w):return {'title':'Paper '+w['id'],'doi':w['doi'],'openalex_id':w['id']}
            request={'state_dir':folder,'seeds':[{'doi':'10.1000/root','title':'Root'}],
                'queries':[],'preprints':{},'discovery_channels':['seed_related'],'network':{'seed_workers':1}}
            with patch('fetch.network.ProviderClient.get',get),patch('fetch.discovery_bridge.oa_record',parse):
                result=discover(request)
            self.assertTrue(result['pool'])
            self.assertTrue(all(row['discovered_from_seed_dois']==['10.1000/root'] for row in result['pool']))
            self.assertTrue(all(not row.get('discovered_from_seed_dois') for row in result['resolved']))

    def test_malformed_origin_is_quarantined_by_normalization(self):
        with self.assertRaises(ValueError):normalize({'title':'paper','discovered_from_seed_dois':{'guess':'parent'}})
