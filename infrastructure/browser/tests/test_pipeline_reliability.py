import asyncio
import hashlib
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch


class MetadataSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_guards_share_one_session_but_not_position_results(self):
        from browser.owner_browser_calls import _metadata_session_async
        async def attach():
            await asyncio.sleep(.02);return object()
        browser=SimpleNamespace(new_browser_cdp_session=AsyncMock(side_effect=attach))
        sessions=await asyncio.gather(*(_metadata_session_async(browser) for _ in range(20)))
        self.assertTrue(all(s is sessions[0] for s in sessions))
        browser.new_browser_cdp_session.assert_awaited_once()

    async def test_cancelled_reader_cannot_cancel_other_readers_attachment(self):
        from browser.owner_browser_calls import _metadata_session_async
        async def attach():
            await asyncio.sleep(.03);return object()
        browser=SimpleNamespace(new_browser_cdp_session=AsyncMock(side_effect=attach))
        first=asyncio.create_task(asyncio.wait_for(_metadata_session_async(browser),.005))
        second=asyncio.create_task(_metadata_session_async(browser))
        with self.assertRaises(TimeoutError):await first
        self.assertIsNotNone(await second);browser.new_browser_cdp_session.assert_awaited_once()


class CooperativeLockTests(unittest.TestCase):
    def test_maintenance_cannot_reacquire_before_queued_submissions(self):
        from playwright.sync_api import sync_playwright
        from browser.owner_upload_jobs import OwnerUploadJobs
        from browser.web_page_observer import responsive_lock
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as folder:
            with patch.dict('os.environ',{'WEB_GPT_SUBMIT_LOCK':str(Path(folder)/'lock')}):
                jobs=OwnerUploadJobs(pw);order=[]
                def maintenance():
                    for _ in range(2):
                        with responsive_lock(pw,1):
                            order.append('maintenance');pw._sync(asyncio.sleep(.02))
                    return True
                def send(name):
                    with responsive_lock(pw,1):order.append(name)
                    return True
                jobs.start('health',maintenance)
                jobs.start('one',lambda:send('one'));jobs.start('two',lambda:send('two'))
                jobs.drain()
                self.assertEqual(order,['maintenance','one','two','maintenance'])
                self.assertFalse([x for x in jobs.reap() if x.get('error')])
                self.assertFalse(pw._paper_submission_waiters)


class ConsistentReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self,change=None):
        from browser.web_page_observer import PageObserver
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        path=root/'attempt.json';prompt='web-card-12345678-1234-1234-1234-123456789abc-input'
        url='https://chatgpt.com/c/original';raw='{"answer":"original"}'
        a={'state':'submitted','created':1,'target_id':'own','actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
        path.write_text(json.dumps(a));(root/'prompt-actual.txt').write_text(prompt)
        snapshot={'login':False,'streaming':False,'complete':True,'answers':1,'receipt_schema':1,
                  'receipt_url':url,'user_variants':[[prompt,prompt]],'answer_variants':[raw,raw],'answer_busy':False}
        count=0
        async def evaluate(*args):
            nonlocal count
            count+=1
            if change:change(count,snapshot,path,a)
            return dict(snapshot)
        page=Mock(url=url);page.evaluate=AsyncMock(side_effect=evaluate)
        observer=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()));observer.pages={'own':page}
        result=await observer.inspect('own',page,[url],{'own':(path,a)})
        return root,path,page,result

    async def test_complete_answer_keeps_all_guards_with_four_renderer_round_trips(self):
        root,path,page,result=await self.fixture()
        self.assertTrue(result['saved']);self.assertEqual(page.evaluate.await_count,4)
        page.locator.return_value.count.assert_not_called()
        self.assertEqual(json.loads(path.read_text())['state'],'response_saved')

    async def test_changed_final_identity_or_streaming_never_saves(self):
        for key,value in [('user_variants',[['other','other']]),('streaming',True),('answer_busy',True)]:
            def change(count,snapshot,*args):
                if count==4:snapshot[key]=value
            root,path,page,result=await self.fixture(change)
            self.assertNotIn('saved',result);self.assertFalse((root/'response-raw.txt').exists())

    async def test_newer_ledger_during_final_snapshot_is_preserved(self):
        newer={}
        def change(count,snapshot,path,a):
            if count==4:
                newer.update(a,state='needs_inspection',error='new original owner evidence')
                path.write_text(json.dumps(newer))
        root,path,page,result=await self.fixture(change)
        self.assertNotIn('saved',result);self.assertEqual(json.loads(path.read_text()),newer)


class OriginalCurlTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_bytes_headers_http1_and_redirect_refusal(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from browser.owner_http1_transport import _CurlPut
        received=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def do_PUT(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                received.append((self.path,self.request_version,self.headers.get('X-Original'),body))
                self.send_response(307 if self.path=='/redirect' else 201)
                self.send_header('Location','/must-not-replay');self.send_header('Content-Length','2')
                self.send_header('X-Original-Response','verified');self.end_headers();self.wfile.write(b'ok')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=_CurlPut(None);payload=b'PK exact original ZIP bytes'
            for suffix in ['/original','/redirect']:
                reply=await client._perform('http://127.0.0.1:'+str(server.server_port)+suffix,{'X-Original':'same'},payload,2000)
                self.assertEqual(reply.status,307 if suffix=='/redirect' else 201)
                self.assertEqual(reply.content,b'ok');self.assertEqual(reply.headers['x-original-response'],'verified')
            self.assertEqual(len(received),2)
            self.assertTrue(all(v=='HTTP/1.1' and h=='same' and b==payload for _,v,h,b in received))
        finally:await asyncio.to_thread(server.shutdown);server.server_close();thread.join()

    async def test_network_failure_is_one_unknown_result_without_retry(self):
        from browser.owner_http1_transport import _CurlPut
        with self.assertRaisesRegex(RuntimeError,'curl_exit='):
            await _CurlPut(None)._perform('http://127.0.0.1:1/original?sig=private',{},b'PK original',1000)

    async def test_untrusted_tls_is_rejected_before_any_put(self):
        import ssl
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from browser.owner_http1_transport import _CurlPut
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):received.append(True)
            def log_message(self,*args):pass
        with tempfile.TemporaryDirectory() as folder:
            cert=Path(folder)/'cert.pem';key=Path(folder)/'key.pem'
            proc=await asyncio.create_subprocess_exec('/usr/bin/openssl','req','-x509','-newkey','rsa:2048',
                '-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost',
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            self.assertEqual(await proc.wait(),0)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert,key);server.socket=ctx.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with self.assertRaisesRegex(RuntimeError,'curl_exit=60'):
                    await _CurlPut(None)._perform('https://localhost:'+str(server.server_port)+'/original',{},b'PK original',2000)
                self.assertFalse(received)
            finally:await asyncio.to_thread(server.shutdown);server.server_close();thread.join()
