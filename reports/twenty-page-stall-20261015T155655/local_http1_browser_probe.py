"""Loopback HTTPS + separate headless browser, no production profile/CDP/data."""
import hashlib,http.server,json,os,ssl,subprocess,tempfile,threading,socket,select
from pathlib import Path
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix='paper-http1-local-') as td:
    root=Path(td);cert=root/'cert.pem';key=root/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
        '-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
    os.environ['NODE_EXTRA_CA_CERTS']=str(cert)
    from playwright.sync_api import sync_playwright
    from browser.original_upload_http1 import OriginalPutProbe
    seen=[];tls_events=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):
            body=b'<html><body>Isolated upload fixture</body></html>'
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_PUT(self):
            data=self.rfile.read(int(self.headers['Content-Length']))
            seen.append({'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'authorization_sha256':hashlib.sha256(self.headers.get('Authorization','').encode()).hexdigest(),
                'cookie_sha256':hashlib.sha256(self.headers.get('Cookie','').encode()).hexdigest(),
                'version':self.request_version,'alpn':self.connection.selected_alpn_protocol()})
            self.send_response(201);self.send_header('Content-Length','2');self.send_header('X-Original-Response','yes');self.end_headers();self.wfile.write(b'OK')
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key);tls.set_alpn_protocols(['h2','http/1.1'])
    server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    connect_count=[]
    class Proxy(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_CONNECT(self):
            host,port=self.path.rsplit(':',1)
            assert host in ('localhost','127.0.0.1','wrong.localhost') and int(port)==server.server_port
            upstream=socket.create_connection(('127.0.0.1',int(port)),timeout=5)
            connect_count.append(self.path);self.send_response(200);self.end_headers();self.wfile.flush()
            try:
                peers=(self.connection,upstream)
                while True:
                    ready,_,_=select.select(peers,[],[],10)
                    if not ready:return
                    for source in ready:
                        data=source.recv(65536)
                        if not data:return
                        (upstream if source is self.connection else self.connection).sendall(data)
            finally:upstream.close()
    proxy_server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Proxy)
    proxy_thread=threading.Thread(target=proxy_server.serve_forever,daemon=True);proxy_thread.start()
    base=f'https://localhost:{server.server_port}'
    # Native fixture only negotiates HTTP/1.1 too; the important evidence is that
    # API's original PUT negotiates HTTP/1.1, while browser interception works.
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True,args=['--disable-http2']);ctx=browser.new_context(ignore_https_errors=True)
        ctx.add_cookies([{'name':'fixture-session','value':'original-cookie','url':base}]);page=ctx.new_page();page.goto(base)
        api=pw.request.new_context(ignore_https_errors=False,proxy={'server':f'http://127.0.0.1:{proxy_server.server_port}'})
        try:
            mismatch_response=api.get(f'https://wrong.localhost:{server.server_port}')
        except Exception as exc:
            assert 'CERT' in str(exc).upper() or 'certificate' in str(exc).lower(),str(exc)
        else:raise AssertionError(str({'unexpected_status':mismatch_response.status,'proxy_connect_count':connect_count,'response':mismatch_response.text()[:250]}))
        payload=b'PK'+b'a'*12_000_000;expected=hashlib.sha256(payload).hexdigest()
        probe=OriginalPutProbe(root,api,'fixture')
        context={'lane':'review','job_id':'fixture','paper_id':'fixture','target_id':'fixture',
                 'bundle':{'zip_sha256':expected}}
        with patch('browser.original_upload_http1.matches',side_effect=lambda request:request.method=='PUT' and request.url.startswith(base+'/upload')):
            probe.arm(page,context,lambda:None)
            result=page.evaluate('''async (size)=>{
                const bytes=new Uint8Array(size);bytes.fill(97);bytes[0]=80;bytes[1]=75;
                const r=await fetch('/upload',{method:'PUT',body:bytes,headers:{Authorization:'fixture-auth'}});
                return {status:r.status,body:await r.text(),header:r.headers.get('X-Original-Response')};
            }''',len(payload))
            page.evaluate('''async(size)=>{const b=new Uint8Array(size);b.fill(97);b[0]=80;b[1]=75;
                try{await fetch('/upload',{method:'PUT',body:b});return 'unexpected'}catch{return 'blocked'}}''',len(payload))
        assert result=={'status':201,'body':'OK','header':'yes'},result
        assert connect_count, 'API must use the original-style CONNECT proxy'
        assert len(seen)==1 and seen[0]['sha256']==expected,seen
        assert seen[0]['version']=='HTTP/1.1' and seen[0]['alpn']!='h2',seen
        assert seen[0]['authorization_sha256']==hashlib.sha256(b'fixture-auth').hexdigest(),seen
        assert seen[0]['cookie_sha256']==hashlib.sha256(b'fixture-session=original-cookie').hexdigest()
        assert probe.read()['fulfilled'] is True
        # TLS verification stays on: an untrusted second context must reject.
        api.dispose();ctx.close();browser.close()
    server.shutdown();server.server_close();proxy_server.shutdown();proxy_server.server_close()
    result={'scope':'loopback HTTPS; isolated headless Chrome; no production connection',
            'request_count':len(seen),'proxy_connect_count':len(connect_count),'server':seen,'page_result':result,'intent':probe.read(),
            'tls_validation':'API verification enabled; trusted local CA; wrong DNS hostname rejected through CONNECT proxy; fixture browser ignores its self-signed CA only',
            'limitation':'ServiceWorker interception is not proven; IP TLS host checks in proxy SDK are outside production DNS-only whitelist; unobserved PUT is not success'}
    Path(__file__).with_name('local-http1-browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'request_count':len(seen),'bytes':len(payload),'status':result['page_result']['status'],'protocol':seen[0]['version'],'alpn':seen[0]['alpn']}))
