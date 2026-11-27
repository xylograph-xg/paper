"""Authenticated temporary workbench routes; only loopback HTTP is used."""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from core.api import catalog__Catalog as Catalog
from workbench.web import create_http_server


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.catalog=Catalog(Path(self.temp.name)/'catalog.db')
        self.pid=self.catalog.upsert({'title':'TADF emitters for OLEDs','doi':'10.1000/http'})
        hosts=set();origins=set();self.secret='isolated-literature-test'
        self.server=create_http_server({'catalog_path':str(self.catalog.path)},self.catalog,0,self.secret,hosts,origins)
        self.host='127.0.0.1:'+str(self.server.server_port)
        hosts.add(self.host);origins.add('http://'+self.host)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,path,data=None,auth=True,headers=None):
        connection=http.client.HTTPConnection(self.host,timeout=5)
        h={'Content-Type':'application/json',**({'X-Paper-Token':self.secret} if auth else {}),**(headers or {})}
        try:
            connection.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),h)
            response=connection.getresponse();body=response.read().decode()
            return response.status,body
        finally:connection.close()

    def test_public_shell_and_script_no_private_data(self):
        status,body=self.request('/literature',auth=False)
        self.assertEqual(status,200);self.assertIn('文献标签与主题学习',body)
        self.assertNotIn('Transient spectroscopy',body)
        self.assertEqual(self.request('/literature/app.js',auth=False)[0],200)
        self.assertEqual(self.request('/api/literature/query',{},auth=False)[0],403)
        self.assertEqual(self.request('/api/literature/query',{},headers={'Origin':'https://invalid.example'})[0],403)
        self.assertEqual(self.request('/api/literature/query',{},headers={'Host':'invalid.example'})[0],403)

    def test_level1_control_is_authenticated_strict_and_separate(self):
        from unittest.mock import patch
        from literature.background import level1_status
        endpoint='/api/literature-level1/control'
        with patch('literature.background.level1_start',return_value={'state':'running'}) as start:
            self.assertEqual(self.request(endpoint,{'paused':False},auth=False)[0],403)
            self.assertEqual(self.request(endpoint,{'paused':False,'target':'cards'})[0],400)
            self.assertEqual(self.request(endpoint,{'paused':0})[0],400)
            start.assert_not_called()
            self.assertEqual(self.request(endpoint,{'paused':False})[0],200)
            start.assert_called_once()
        self.assertEqual(self.request(endpoint,{'paused':True})[0],200)
        self.assertTrue(level1_status({'catalog_path':str(self.catalog.path)})['paused_by_user'])
        self.assertFalse((self.catalog.path.parent/'web-card-control.json').exists())
        self.assertFalse((self.catalog.path.parent/'fetch-control.json').exists())

    def test_level2_control_is_authenticated_strict_and_separate(self):
        from unittest.mock import patch
        from literature.background_level2 import level2_status
        endpoint='/api/literature-level2/control'
        with patch('literature.background.level1_start',return_value={'state':'running'}) as start:
            self.assertEqual(self.request(endpoint,{'paused':False},auth=False)[0],403)
            self.assertEqual(self.request(endpoint,{'paused':False,'target':'cards'})[0],400)
            self.assertEqual(self.request(endpoint,{'paused':0})[0],400)
            start.assert_not_called()
            self.assertEqual(self.request(endpoint,{'paused':False})[0],200)
            start.assert_called_once()
        self.assertEqual(self.request(endpoint,{'paused':True})[0],200)
        self.assertTrue(level2_status({'catalog_path':str(self.catalog.path)})['paused_by_user'])
        self.assertFalse((self.catalog.path.parent/'literature-level1-control.json').exists())
        self.assertFalse((self.catalog.path.parent/'web-card-control.json').exists())
        self.assertFalse((self.catalog.path.parent/'fetch-control.json').exists())

    def test_end_to_end_routes_conflict_and_evidence(self):
        status,body=self.request('/api/literature/query',{})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['total'],1)
        status,body=self.request('/api/literature/save_tag',{'dimension':'method','name_zh':'瞬态光谱','aliases':['Transient spectroscopy']})
        self.assertEqual(status,200);tag=json.loads(body)
        record={'paper_id':self.pid,'tag_id':tag['id'],'quote':'Transient spectroscopy','scope':'title','relation':'used'}
        self.assertEqual(self.request('/api/literature/annotate',{'records':[record]})[0],400)
        self.assertEqual(self.request('/api/literature/auto_label',{'paper_ids':[self.pid]})[0],200)
        self.assertEqual(self.request('/api/literature/annotate',{'records':[record]})[0],400)
        _,body=self.request('/api/literature/detail',{'paper_id':self.pid})
        a=json.loads(body)['annotations'][0]
        self.assertEqual(a['state'],'automatic');self.assertIn(a['evidence'][0]['scope'],('title','abstract'))
        record['origin']='automatic'
        self.assertEqual(self.request('/api/literature/annotate',{'records':[record]})[0],400)
        self.assertEqual(self.request('/api/literature/not-an-operation',{})[0],400)
        _,body=self.request('/api/literature/save_collection',{'name':'方法学习'})
        cid=json.loads(body)['id']
        self.assertEqual(self.request('/api/literature/save_member',{'collection_id':cid,'paper_id':self.pid,'role':'method'})[0],200)
        _,body=self.request('/api/literature/query',{'collection_id':cid})
        self.assertEqual(json.loads(body)['papers'][0]['membership']['role'],'method')


if __name__=='__main__':unittest.main()
