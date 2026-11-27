"""Exercise real authenticated handlers with no listener, worker or model call."""
import io
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import patch
from core.catalog import Catalog
from workbench.web import create_http_server
from core.control import read_record


class FourWorkflowHTTP(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'catalog_path':str(self.root/'catalog.sqlite3'),'web_cards':{'enabled':True,'max_parallel_jobs':20,'shared_window':{'enabled':True}},
                     'card_review':{'enabled':True},'card_correction':{'enabled':True}}
        self.catalog=Catalog(self.config['catalog_path'])
        with patch('workbench.web.WorkbenchHTTPServer',side_effect=lambda address,handler:SimpleNamespace(handler=handler)):
            self.handler=create_http_server(self.config,self.catalog,8771,'test-secret',{'127.0.0.1:8771'},set()).handler

    def post(self,path,data,token='test-secret'):
        request=object.__new__(self.handler);encoded=json.dumps(data).encode()
        request.path=path;request.headers={'Host':'127.0.0.1:8771','X-Paper-Token':token,'Content-Length':str(len(encoded))}
        request.rfile=io.BytesIO(encoded);result=[]
        request.reply=lambda status,data,*args,**kwargs:result.append((status,data))
        request.do_POST()
        return result[0]

    def test_auth_boundary_prevents_controls(self):
        self.assertEqual(self.post('/api/card-correction/control',{'paused':True},token='wrong')[0],403)
        self.assertFalse((self.root/'card-correction-control.json').exists())

    def test_correction_pause_does_not_pause_other_tasks(self):
        status,data=self.post('/api/card-correction/control',{'paused':True,'parallel':7})
        self.assertEqual(status,200);self.assertFalse(data['card_correction']['enabled'])
        self.assertEqual(data['card_correction']['parallel_jobs'],7)
        self.assertTrue(read_record(self.root/'card-correction-control.json')['paused_by_user'])
        for name in ('web-card-control.json','card-review-control.json','fetch-control.json'):
            self.assertFalse((self.root/name).exists())

    def test_invalid_change_does_not_partially_pause(self):
        for path in ('/api/card-correction/control','/api/card-review/control'):
            self.assertEqual(self.post(path,{'paused':True,'parallel':21})[0],400)
        self.assertFalse((self.root/'card-correction-control.json').exists())
        self.assertFalse((self.root/'card-review-control.json').exists())

    def test_atomic_reservation_and_maximum_then_refuse_invalid_reduction(self):
        status,data=self.post('/api/concurrency/control',{'cards':12,'cards_min_pages':12})
        self.assertEqual(status,200);self.assertEqual(data['concurrency']['cards_min_pages'],12)
        before=(self.root/'concurrency-control.json').read_bytes()
        self.assertEqual(self.post('/api/concurrency/control',{'cards':8})[0],400)
        self.assertEqual((self.root/'concurrency-control.json').read_bytes(),before)

    def test_resume_correction_uses_existing_owner_only(self):
        with patch('cards.web_card_service.start',return_value={}) as start:
            self.assertEqual(self.post('/api/card-correction/control',{'paused':False})[0],200)
        start.assert_called_once_with(self.config)
        self.assertFalse((self.root/'web-card-control.json').exists())

    def test_four_task_actions_dispatch_independent_target(self):
        for target in ('fetch','cards','review','correction'):
            with patch('core.continuous_start.start',return_value={}) as start:
                self.assertEqual(self.post('/api/workflow/control',{'target':target,'paused':False})[0],200)
                start.assert_called_once_with(self.config,target=target,open_browser=target=='cards')
            with patch('core.continuous_start.stop',return_value={}) as stop:
                self.assertEqual(self.post('/api/workflow/control',{'target':target,'paused':True})[0],200)
                stop.assert_called_once_with(self.config,target)

    def test_unknown_or_nonboolean_task_action_rejected(self):
        for data in ({'target':'local','paused':False},{'target':'cards','paused':1},{'target':'cards','paused':True,'extra':1}):
            self.assertEqual(self.post('/api/workflow/control',data)[0],400)


if __name__=='__main__':unittest.main()
