"""Workbench access boundaries with a local isolated catalog and HTTP service."""
import json
import socket
import tempfile
import threading
import time
from unittest.mock import patch
from contextlib import contextmanager
import unittest
import urllib.error
import urllib.request
from core.api import paths__WorkspacePath as Path
from core.catalog import Catalog, ROOT
from workbench.web import create_http_server


class WorkbenchAccess(unittest.TestCase):
    def test_reveal_local_uses_catalog_path_and_rejects_arbitrary_paths(self):
        auth={'X-Paper-Token':self.secret,'Origin':self.url}
        body=json.dumps({'id':self.pid}).encode()
        with patch('workbench.web.subprocess.run') as run, patch('workbench.web.sys.platform','darwin'):
            self.assertEqual(self.request('/api/reveal-local',body)[0],403)
            self.assertEqual(self.request('/api/reveal-local',body,auth)[0],200)
            run.assert_called_once_with(['/usr/bin/open','-R',str((self.root/'original.pdf').resolve())],check=True,timeout=10)
            run.reset_mock()
            self.assertEqual(self.request('/api/reveal-local',json.dumps({'id':self.pid,'path':'/tmp/other'}).encode(),auth)[0],400)
            run.assert_not_called()
            (self.root/'original.pdf').unlink()
            self.assertEqual(self.request('/api/reveal-local',body,auth)[0],404)
            card=self.root/'card.json';card.write_text('{}')
            self.catalog.update(self.pid,asset_path=None,card_path=str(card))
            self.assertEqual(self.request('/api/reveal-local',body,auth)[0],200)
            run.assert_called_once_with(['/usr/bin/open','-R',str(card.resolve())],check=True,timeout=10)

    def test_unchanged_state_returns_304_and_modified_state_invalidates_etag(self):
        status,headers,body=self.request('/api/state',headers={'X-Paper-Token':self.secret})
        self.assertEqual(status,200);etag={k.lower():v for k,v in headers.items()}['etag']
        self.assertEqual(self.request('/api/state',headers={'X-Paper-Token':self.secret,'If-None-Match':etag})[0],304)
        self.catalog.update(self.pid,assessment={'core_findings':'changed evidence'})
        self.assertEqual(self.request('/api/state',headers={'X-Paper-Token':self.secret,'If-None-Match':etag})[0],200)
    def test_web_mode_exposes_resident_queue_and_migrated_visuals(self):
        self.config['web_cards']={'enabled':True,'selection_fraction':.30,'max_pages_per_provider':20}
        from cards.web_card_queue import install
        install(self.catalog)
        status,headers,body=self.request('/api/state',headers={'X-Paper-Token':self.secret})
        state=json.loads(body);self.assertEqual(status,200);self.assertTrue(state['web_cards']['enabled']);self.assertEqual(state['web_jobs'],[])
        folder=self.root/'new-library';(folder/'pages').mkdir(parents=True)
        (folder/'pages/P001.png').write_bytes(b'page evidence')
        (folder/'source.pdf').write_bytes(b'%PDF canonical source')
        card={'figures':[],'equations':[],'tables':[{'label':'Table 1','image_path':str(folder/'pages/P001.png')}]}
        (folder/'card.json').write_text(json.dumps(card));self.catalog.update(self.pid,card_path=str(folder/'card.json'))
        result=json.loads(self.request('/api/card?id='+self.pid,headers={'X-Paper-Token':self.secret})[2])
        self.assertEqual(result['tables'][0]['asset_file'],'pages/P001.png')
        self.assertEqual(self.request('/asset?id='+self.pid,headers={'X-Paper-Token':self.secret})[2],b'%PDF canonical source')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.db')
        self.config=json.loads((ROOT/'config/first_round.json').read_text());self.config['catalog_path']=str(self.catalog.path)
        self.config['workbench_passwordless']=False
        self.config['local_models_enabled']=True  # Only the isolated schedule API fixture.
        self.secret='synthetic-private-access-token';self.hosts=set();self.origins=set()
        self.server=create_http_server(self.config,self.catalog,0,self.secret,self.hosts,self.origins)
        host='127.0.0.1:'+str(self.server.server_port);self.hosts.add(host);self.url='http://'+host;self.origins.add(self.url)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.pid=self.catalog.upsert({'title':'Private synthetic title'})
        source=self.root/'original.pdf';source.write_bytes(b'%PDF synthetic original')
        self.catalog.update(self.pid,asset_path=str(source))
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2);self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.url+path,data=body,headers=headers or {})
        try:response=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3)
        except urllib.error.HTTPError as exc:response=exc
        with response:return response.status,dict(response.headers),response.read()
    def test_public_bootstrap_never_discloses_token_or_catalog_and_sets_csp(self):
        status,headers,body=self.request('/')
        self.assertEqual(status,200);self.assertNotIn(self.secret.encode(),body);self.assertNotIn(b'Private synthetic title',body)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy']);self.assertEqual(headers['X-Frame-Options'],'DENY')
        self.assertIn(b'nonce=',body);self.assertNotIn(b' onclick="',body)
    def test_all_data_gets_require_authentication(self):
        for path in ['/api/state','/asset?id='+self.pid,'/vendor/runtime-status.json','/export/manual.csv']:
            self.assertEqual(self.request(path)[0],403)
            self.assertEqual(self.request(path,headers={'Cookie':'PaperSession=wrong'})[0],403)
        self.assertEqual(self.request('/api/state',headers={'X-Paper-Token':'é'})[0],403)
    def test_session_cookie_allows_pdf_and_state_without_exposing_post_token(self):
        status,headers,_=self.request('/api/session',b'{}',{'X-Paper-Token':self.secret,'Origin':self.url})
        self.assertEqual(status,200);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        cookie=headers['Set-Cookie'].split(';')[0]
        status,_,body=self.request('/api/state',headers={'Cookie':cookie})
        self.assertEqual(status,200);self.assertIn(b'Private synthetic title',body)
        self.assertEqual(self.request('/asset?id='+self.pid,headers={'Cookie':cookie})[0],200)
        self.assertEqual(self.request('/api/discover',b'{}',{'Cookie':cookie,'Origin':self.url})[0],403)
    def test_cross_origin_post_rejected_even_with_token(self):
        self.assertEqual(self.request('/api/session',b'{}',{'X-Paper-Token':self.secret,'Origin':'https://outside.test'})[0],403)
        self.assertEqual(self.request('/api/session',b'{}',{'X-Paper-Token':'é'})[0],403)
        self.assertEqual(self.request('/api/state',headers={'X-Paper-Token':self.secret})[0],200)

    def test_passwordless_loopback_and_tailnet_reads_and_same_origin_writes(self):
        config={**self.config,'workbench_passwordless':True}
        remote='workbench.test.ts.net:8768'
        hosts={remote};origins={'http://'+remote}
        with create_http_server(config,self.catalog,0,self.secret,hosts,origins) as server:
            local_host=f'127.0.0.1:{server.server_port}'
            local='http://'+local_host
            hosts.add(local_host);origins.add(local)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def request(path,headers=None,body=None):
                    req=urllib.request.Request(local+path,headers=headers or {},data=body)
                    try:response=opener.open(req,timeout=3)
                    except urllib.error.HTTPError as exc:response=exc
                    with response:return response.status,response.headers,response.read()
                self.assertIn(b'name="paper-passwordless" content="true"',request('/')[2])
                self.assertIn(b'name="paper-passwordless" content="true"',request('/literature')[2])
                self.assertEqual(request('/api/state?tab=manual_seed_cards')[0],200)
                self.assertEqual(request('/api/state',{'Host':remote,'X-Paper-Token':self.secret})[0],403)
                tailnet={'Host':remote,'Tailscale-User-Login':'reader@example.test'}
                self.assertEqual(request('/asset?id='+self.pid,tailnet)[0],200)
                self.assertEqual(request('/api/workbench-health',{'Host':'foreign.test',**{k:v for k,v in tailnet.items() if k!='Host'}})[0],403)
                body=json.dumps({'id':self.pid,'is_read':True}).encode()
                self.assertEqual(request('/api/reading',tailnet,body)[0],403)
                self.assertEqual(request('/api/reading',{**tailnet,'Origin':local},body)[0],403)
                self.assertEqual(request('/api/reading',{**tailnet,'Origin':'http://'+remote},body)[0],200)
                status,headers,_=request('/api/session',{'Origin':local},b'{}')
                self.assertEqual(status,200);self.assertNotIn('Set-Cookie',headers)
            finally:
                server.shutdown();thread.join(timeout=2)
    def test_static_files_are_public_but_runtime_and_path_escape_are_not(self):
        self.assertEqual(self.request('/vendor/marked.esm.js')[0],200)
        self.assertEqual(self.request('/vendor/../services.py')[0],403)
        self.assertEqual(self.request('/vendor/../../README.js')[0],404)

    def test_model_schedule_requires_explicit_authenticated_override_and_valid_window(self):
        def write(data,headers=None):
            return self.request('/api/model-schedule',json.dumps(data).encode(),headers)
        auth={'X-Paper-Token':self.secret,'Origin':self.url}
        self.assertEqual(write({'mode':'allow','minutes':30})[0],403)
        self.assertEqual(write({'mode':'all_day'})[0],403)
        self.assertEqual(write({'mode':'window','start':'09:00','end':'24:00'},auth)[0],400)
        self.assertEqual(write({'mode':'window','start':'12:00','end':'23:00'},auth)[0],200)
        status,_,body=write({'mode':'allow','minutes':30},auth)
        self.assertEqual(status,200);value=json.loads(body)
        self.assertEqual(value['mode'],'manual');self.assertTrue(value['allowed']);self.assertTrue(value['override_until'])
        status,_,body=write({'mode':'reset'},auth)
        value=json.loads(body);self.assertEqual(status,200);self.assertEqual(value['start'],'10:00')
        self.assertEqual(value['end'],'24:00');self.assertIsNone(value['override_until'])
        status,_,body=write({'mode':'all_day'},auth)
        value=json.loads(body);self.assertEqual(status,200);self.assertEqual(value['mode'],'all_day')
        self.assertTrue(value['allowed']);self.assertIsNone(value['override_until'])

    @staticmethod
    def available_slots(semaphore):
        with semaphore._cond:
            return semaphore._value

    def assert_request_capacity_released(self, timeout=3):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.available_slots(self.server.request_slots)==16:return
            time.sleep(.01)
        self.fail('HTTP capacity did not recover: available='+
                  str(self.available_slots(self.server.request_slots)))

    @contextmanager
    def admitted_idle_connections(self,prefix=b''):
        clients=[];active=[];entered={};exited=set();condition=threading.Condition()
        original=self.server._handshake
        def observed(request,address):
            with condition:
                entered[address]=time.monotonic();condition.notify_all()
            try:return original(request,address)
            finally:
                with condition:exited.add(address);condition.notify_all()
        with patch.object(self.server,'_handshake',side_effect=observed):
            try:
                self.assert_request_capacity_released()
                # Admit each connection before the next; do not measure the TCP backlog.
                for _ in range(16):
                    client=socket.create_connection(self.server.server_address,timeout=3)
                    clients.append(client);address=client.getsockname()
                    if prefix:client.sendall(prefix)
                    with condition:
                        self.assertTrue(condition.wait_for(lambda:address in entered,timeout=1),
                                        'Idle client was not admitted: '+str(entered))
                with condition:
                    active=[c.getsockname() for c in clients if c.getsockname() not in exited]
                    self.assertEqual(len(active),16,{'entered':entered,'exited':list(exited)})
                self.assertEqual(self.available_slots(self.server.request_slots),16)
                yield
            finally:
                for client in clients:client.close()
                with condition:
                    self.assertTrue(condition.wait_for(
                        lambda:all(caddr in exited for caddr in active),timeout=3),
                        {'entered':entered,'exited':list(exited)})
        self.assert_request_capacity_released()

    def test_slow_connections_are_bounded_and_release_capacity_on_close(self):
        self.assertEqual(self.request('/')[0],200)
        with self.admitted_idle_connections():
            # No retry: a healthy request during active idle handshakes must work.
            self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/')[0],200)

    def test_complete_requests_are_bounded_and_release_capacity(self):
        clients=[];release=threading.Event();condition=threading.Condition();entered=[]
        original=self.server.RequestHandlerClass.do_GET
        def held(handler):
            with condition:entered.append(handler.client_address);condition.notify_all()
            if not release.wait(3):raise AssertionError('Timed out waiting for test release')
            return original(handler)
        with patch.object(self.server.RequestHandlerClass,'do_GET',held):
            try:
                for number in range(16):
                    client=socket.create_connection(self.server.server_address,timeout=3)
                    clients.append(client)
                    client.sendall(('GET / HTTP/1.0\r\nHost: '+self.url[7:]+'\r\n\r\n').encode())
                    with condition:
                        self.assertTrue(condition.wait_for(lambda:len(entered)==number+1,timeout=1))
                self.assertEqual(self.available_slots(self.server.request_slots),0)
                status,headers,_=self.request('/')
                self.assertEqual(status,503);self.assertEqual(headers['Retry-After'],'2')
            finally:
                release.set();responses=[]
                try:
                    for client in clients:
                        response=b''
                        while chunk:=client.recv(65536):response+=chunk
                        responses.append(response)
                finally:
                    for client in clients:client.close()
                for response in responses:
                    self.assertTrue(response.startswith(b'HTTP/1.0 200'),response[:80])
        self.assert_request_capacity_released()
        self.assertEqual(self.request('/')[0],200)

    def test_capacity_check_rejects_permanent_slot_loss(self):
        self.assertTrue(self.server.request_slots.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(AssertionError,'capacity did not recover'):
                self.assert_request_capacity_released(timeout=.02)
        finally:self.server.request_slots.release()
        self.assert_request_capacity_released()

    def test_health_requires_authentication_and_reports_only_the_web_service(self):
        self.assertEqual(self.request('/api/workbench-health')[0],403)
        status,_,body=self.request('/api/workbench-health',headers={'X-Paper-Token':self.secret})
        health=json.loads(body);self.assertEqual(status,200)
        self.assertEqual(health['service'],'paper-workbench')
        self.assertEqual(health['port'],self.server.server_port)
        self.assertFalse(health['background']);self.assertNotIn('token',health)

    def test_reading_api_is_authenticated_preserves_notes_and_invalidates_state_etag(self):
        endpoint='/api/reading';auth={'X-Paper-Token':self.secret,'Origin':self.url}
        def write(**patch):return self.request(endpoint,json.dumps({'id':self.pid,**patch}).encode(),auth)
        self.assertEqual(self.request(endpoint+'?id='+self.pid)[0],403)
        self.assertEqual(self.request(endpoint,json.dumps({'id':self.pid,'is_read':True}).encode())[0],403)
        initial=self.request('/api/state',headers=auth);self.assertEqual(initial[0],200);etag={k.lower():v for k,v in initial[1].items()}['etag']
        self.assertEqual(write(note='备注 unique_note_marker',note_version=0)[0],200)
        status,_,body=write(note='stale',note_version=0);self.assertEqual(status,409)
        current=json.loads(self.request(endpoint+'?id='+self.pid,headers=auth)[2]);self.assertIn('unique_note_marker',current['note'])
        self.assertEqual(self.request('/api/state',headers={**auth,'If-None-Match':etag})[0],200)
        self.assertEqual(write(is_read=1)[0],400)
        self.assertEqual(write(is_read=True)[0],200)
        read_page=json.loads(self.request('/api/state?tab=read',headers=auth)[2]);self.assertEqual(read_page['total'],1)
        self.assertEqual(read_page['papers'][0]['note_version'],1)
        self.assertEqual(write(is_read=False)[0],200)
        self.assertEqual(json.loads(self.request('/api/state?tab=read',headers=auth)[2])['total'],0)

if __name__=='__main__':unittest.main()
