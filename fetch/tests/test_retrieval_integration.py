import json
import subprocess
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.catalog import Catalog
from core.services import acquisition
from fetch.fetchpdf_bridge import install_http_guards


class RetrievalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.c=Catalog(self.root/'catalog.sqlite3')
        self.pid=self.c.upsert({'title':'A unique triplet transport experimental report','doi':'10.1000/test'})
        self.config={'archive_volume':str(self.root),'archive_root':str(self.root/'archive'),
                     'require_mounted_volume':False,'catalog_path':str(self.root/'catalog.sqlite3'),
                     'pdf_retrieval':{'enabled':True,'python':'unused','timeout_seconds':10}}
    def tearDown(self):
        self.temp.cleanup()

    def test_download_is_validated_and_rescreened(self):
        def fake_run(*args,**kwargs):
            import pymupdf
            payload=json.loads(kwargs['input']);doc=pymupdf.open();page=doc.new_page()
            page.insert_text((50,50),'A unique triplet transport experimental report DOI: 10.1000/test')
            doc.save(payload['save_path']);doc.close()
            return subprocess.CompletedProcess(args,0,json.dumps({'path':payload['save_path'],'source':'repository'}))
        with patch('core.process_runner.run',side_effect=fake_run):
            acquisition(self.c,self.config,self.pid)
        self.assertEqual(self.c.get(self.pid)['acquisition'],'available')
        self.assertTrue(any(j['kind']=='screen' for j in self.c.jobs()))

    def test_timeout_remains_manual_and_is_not_authentication_claim(self):
        with patch('core.process_runner.run',side_effect=subprocess.TimeoutExpired('fetchpdf',10)):
            acquisition(self.c,self.config,self.pid)
        p=self.c.get(self.pid)
        self.assertEqual(p['acquisition'],'needs_manual_download')
        self.assertEqual(p['acquisition_detail']['attempts'][-1]['kind'],'timeout')

    def test_output_outside_temp_is_rejected(self):
        result=subprocess.CompletedProcess([],0,json.dumps({'path':'/private/tmp/not-allowed.pdf','source':'test'}))
        with patch('core.process_runner.run',return_value=result):
            acquisition(self.c,self.config,self.pid)
        self.assertNotEqual(self.c.get(self.pid)['acquisition'],'available')

    def test_upstream_cannot_disable_tls_verification(self):
        import requests
        response=requests.Response();response.status_code=200;response.headers={};response._content=b'';response._content_consumed=True
        with patch('requests.sessions.Session.send',return_value=response) as original,patch('core.services.public_url') as address, patch('fetch.network.ready'), patch('fetch.network.succeeded'), patch('fetch.net_limits.pace_arxiv'), patch('fetch.acquisition_budget.remaining',return_value=120):
            install_http_guards()
            session=requests.Session();request=requests.Request('GET','https://example.org/paper').prepare()
            session.send(request,verify=False,timeout=(30,60))
            self.assertIs(original.call_args.kwargs['verify'],True)
            self.assertEqual(original.call_args.kwargs['timeout'],(15,15))
            address.assert_called_once_with(request.url)
