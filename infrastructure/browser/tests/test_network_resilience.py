"""Transport observations throttle new work without replaying old requests."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from browser import upload_trace
from browser.web_card_pool import record_upload_network_failure
from browser.web_card_transport import ProviderFailure, Router
from browser.web_page_observer import PageObserver


class NetworkResilience(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        upload_trace.configure(self.root);self.addCleanup(upload_trace.reset)
        self.observer=PageObserver(self.root,SimpleNamespace(_loop=asyncio.get_running_loop()))
        self.page=Mock();self.observer.pages={'original':self.page};self.observer.window_targets={'original'}
        self.router=Router(self.root)
        self.observer.on_upload_network_failure=lambda event:record_upload_network_failure(self.router,event)

    def request(self, failure=None):
        return SimpleNamespace(_guid='request-original',
            url='https://files.oaiusercontent.com/files/private?sig=secret',
            method='PUT',resource_type='xhr',failure=failure)

    async def test_original_network_failure_cools_new_dispatch_and_keeps_active_material(self):
        attempt=upload_trace.begin(target_id='original',zip_path='/tmp/synthetic.zip')
        self.observer._network_event('original',self.page,self.request(),phase='request')
        with patch('browser.web_card_transport.time.time',return_value=1000.0):
            self.observer._network_event('original',self.page,
                self.request('net::ERR_NETWORK_CHANGED'),phase='requestfailed')
        state=json.loads(self.router.path.read_text())['chatgpt']
        self.assertEqual(state['blocked_until'],1300.0)
        self.assertEqual(state['reason'],'network');self.assertFalse(state['explicit_reset'])
        self.assertEqual(state['reset_source'],'cooldown_probe')
        self.assertEqual(upload_trace.active('original'),attempt['upload_attempt_id'])
        events=[json.loads(s) for s in (self.root/upload_trace.EVENTS_FILE).read_text().splitlines()]
        self.assertNotIn('upload_finished',[event['kind'] for event in events])
        self.assertNotIn('secret',json.dumps(events))

    async def test_only_attributed_original_put_transport_failures_can_cool_dispatch(self):
        event={'phase':'requestfailed','method':'PUT','attributed':True,'upload_attempt_id':'original',
               'host':'files.oaiusercontent.com','failure':'net::ERR_HTTP2_PROTOCOL_ERROR'}
        router=Mock();self.assertTrue(record_upload_network_failure(router,event))
        failure=router.block.call_args.args[0]
        self.assertFalse(failure.unsent);self.assertEqual(failure.kind,'network')
        for changed in ({'attributed':False},{'upload_attempt_id':None},{'method':'POST'},
                        {'phase':'response','status':403},{'host':'unrelated.example'},
                        {'failure':'net::ERR_FAILED'},{'failure':'net::ERR_ABORTED'}):
            with self.subTest(changed=changed):
                router.reset_mock()
                self.assertFalse(record_upload_network_failure(router,{**event,**changed}))
                router.block.assert_not_called()

    async def test_network_failure_never_shortens_or_relabels_account_quota(self):
        with patch('browser.web_card_transport.time.time',return_value=1000.0):
            self.router.block(ProviderFailure('original quota','chatgpt','quota',False,5000.0))
            before=self.router.path.read_bytes()
            self.router.block(ProviderFailure('network changed','chatgpt','network',False))
        self.assertEqual(self.router.path.read_bytes(),before)

    async def test_http_error_records_only_whitelisted_diagnostic_header_values(self):
        upload_trace.begin(target_id='original',zip_path='/tmp/synthetic.zip')
        self.observer._network_event('original',self.page,self.request(),phase='request')
        self.observer._network_event('original',self.page,self.request(),403,phase='response',
            response_headers={'x-ms-error-code':'AuthenticationFailed','retry-after':'120',
                              'set-cookie':'private-cookie','authorization':'private-auth'})
        event=self.observer._network_events[-1]
        self.assertEqual(event['server_error_code'],'AuthenticationFailed')
        self.assertEqual(event['retry_after_seconds'],120)
        self.assertFalse(self.router.path.exists())
        self.assertNotIn('private-',json.dumps(event));self.assertNotIn('secret',json.dumps(event))
        self.observer._network_event('original',self.page,self.request(),403,phase='response',
            response_headers={'x-ms-error-code':'bad?sig=secret','retry-after':'private'})
        self.assertNotIn('server_error_code',self.observer._network_events[-1])

    async def test_cooldown_write_error_keeps_the_network_observer_running(self):
        self.observer.on_upload_network_failure=Mock(side_effect=OSError('disk full'))
        self.observer._network_event('original',self.page,
            self.request('net::ERR_CONNECTION_RESET'),phase='requestfailed')
        self.assertIn('network_cooldown',self.observer._network_write_error)
        self.assertEqual(self.observer._network_events[-1]['failure'],'net::ERR_CONNECTION_RESET')


class BrowserNetworkEvidence(unittest.TestCase):
    def test_real_local_put_response_and_disconnect_keep_original_attribution(self):
        """Synthetic loopback bytes only; never uses the dedicated CDP browser."""
        import socket
        import struct
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from playwright.sync_api import sync_playwright

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=b'<html><body>isolated upload fixture</body></html>'
                self.send_response(200);self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def do_PUT(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                if self.path=='/files/reset':
                    self.connection.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('ii',1,0))
                    self.connection.close();self.close_connection=True;return
                self.send_response(403);self.send_header('Content-Length','0')
                self.send_header('x-ms-error-code','AuthenticationFailed')
                self.send_header('set-cookie','must-not-be-recorded');self.end_headers()

        with tempfile.TemporaryDirectory() as folder:
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            upload_trace.configure(Path(folder))
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True,
                        executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                        args=['--no-proxy-server'])
                    try:
                        page=browser.new_page();page.goto('http://127.0.0.1:'+str(server.server_port))
                        observer=PageObserver(folder,pw)
                        observer.pages={'synthetic':page._impl_obj};observer.window_targets={'synthetic'}
                        observer._update_network_pages()
                        original=upload_trace.begin(target_id='synthetic',zip_path='/tmp/synthetic.zip')
                        status=page.evaluate("async()=>{const r=await fetch('/files/reject',{method:'PUT',body:new Uint8Array(1024)});return r.status}")
                        self.assertEqual(status,403)
                        event=next(e for e in observer._network_events if e.get('status')==403)
                        self.assertEqual(event['server_error_code'],'AuthenticationFailed')
                        self.assertEqual(event['upload_attempt_id'],original['upload_attempt_id'])
                        second=upload_trace.begin(target_id='synthetic',zip_path='/tmp/second.zip')
                        outcome=page.evaluate("async()=>{try{await fetch('/files/reset',{method:'PUT',body:new Uint8Array(1024)});return 'unexpected'}catch(e){return 'failed'}}")
                        self.assertEqual(outcome,'failed')
                        failed=next(e for e in reversed(observer._network_events) if e.get('phase')=='requestfailed')
                        self.assertTrue(failed['failure'])
                        self.assertEqual(failed['upload_attempt_id'],second['upload_attempt_id'])
                        self.assertEqual(upload_trace.active('synthetic'),second['upload_attempt_id'])
                        self.assertNotIn('must-not-be-recorded',(Path(folder)/upload_trace.EVENTS_FILE).read_text())
                        observer.stop()
                    finally:browser.close()
            finally:
                upload_trace.reset();server.shutdown();server.server_close();thread.join(timeout=2)
