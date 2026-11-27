"""One original PUT experiment on the sole owner's thread, with durable intent.

No CDP connection, browser/profile restart or conversation request is made here.
Only the exact complete ZIP bytes on the armed original task page can qualify.
"""
import hashlib
import asyncio
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from urllib.parse import urlsplit
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json

HOST=re.compile(r'sdmntpr[a-z0-9-]+\.oaiusercontent\.com')
_CONTROLLER=None


def system_proxy(text):
    """Reuse the existing macOS HTTPS route; never change browser/OS settings."""
    fields=dict(re.findall(r'^\s*(\w+)\s*:\s*([^\n]+)',text,re.M))
    if any(fields.get(k,'0').strip()=='1' for k in ('ProxyAutoConfigEnable','ProxyAutoDiscoveryEnable')):
        raise ValueError('Automatic proxy route requires explicit verification')
    if fields.get('HTTPSEnable','0').strip()!='1':
        if fields.get('SOCKSEnable','0').strip()=='1':raise ValueError('SOCKS-only system route requires explicit verification')
        return None
    host=fields.get('HTTPSProxy','').strip();port=fields.get('HTTPSPort','').strip()
    if not re.fullmatch(r'[A-Za-z0-9.-]+',host) or not port.isdigit() or not 1<=int(port)<=65535:
        raise ValueError('Existing system HTTPS proxy is unreadable')
    bypass=[];inside=False
    for line in text.splitlines():
        if 'ExceptionsList' in line:inside=True;continue
        if inside and line.strip()=='}':break
        if inside and ':' in line:bypass.extend(line.split(':',1)[1].strip().split(','))
    return {'server':f'http://{host}:{port}','bypass':','.join(bypass)}


def error_evidence(exc):
    text=str(exc)
    codes=re.findall(r'\b(?:EAI_AGAIN|ENOTFOUND|ECONNRESET|ECONNREFUSED|EPIPE|ETIMEDOUT|ERR_[A-Z_]+|UNABLE_TO_[A-Z_]+|CERT_[A-Z_]+)\b',text)
    return {'error_type':type(exc).__name__,'error_codes':sorted(set(codes)),
            'error_message_sha256':_sha(text.encode()),
            'error_category':'certificate' if 'certificate' in text.lower() else 'timeout' if isinstance(exc,TimeoutError) or 'timeout' in text.lower() else 'network_or_client'}


def _sha(data):return hashlib.sha256(data).hexdigest()


def material_intent(root,lane,job_id,paper_id,zip_sha256):
    """Read prior intents and reservations; an armed reservation still blocks.

    A real PUT receipt takes priority, but a durable reservation was written
    before the browser could issue its PUT.  It remains a cross-epoch guard
    until a per-material evidence recovery explicitly releases it.
    """
    key=_sha(json.dumps([lane,job_id,paper_id,zip_sha256],sort_keys=True).encode())
    directory=Path(root)/'original-put-http1'
    for path in [*directory.glob('*/intent.json'),*directory.glob('*/reservation.json')]:
        record=json.loads(path.read_text())
        if record.get('material_key')==key:
            return {'state':record.get('state'),'path':str(path),'fulfilled':record.get('fulfilled') is True,
                    'status':record.get('status')}
    return None


def matches(request):
    try:
        u=urlsplit(request.url)
        return request.method=='PUT' and u.scheme=='https' and u.port in (None,443) and not u.username and not u.password and bool(HOST.fullmatch(u.hostname or ''))
    except ValueError:return False


def forward_headers(request,body):
    headers=request.all_headers();u=urlsplit(request.url)
    normalized={key.lower():value for key,value in headers.items()}
    if normalized.get('host',u.hostname).lower() not in (u.hostname,u.hostname+':443'):
        raise ValueError('Original Host does not match TLS identity')
    if 'content-length' in normalized and normalized['content-length']!=str(len(body)):
        raise ValueError('Original Content-Length does not match ZIP')
    blocked={'host','content-length','connection','transfer-encoding','upgrade','proxy-connection','keep-alive','trailer','te'}
    blocked.update(v.strip().lower() for v in normalized.get('connection','').split(','))
    return {k:v for k,v in headers.items() if k.lower() not in blocked and not k.startswith(':')}


class OriginalPutProbe:
    def __init__(self,root,api,epoch,*,proxy_source='fixture',max_zip_bytes=None):
        self.root=Path(root)/'original-put-http1'/epoch;self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'intent.json';self.reservation=self.root/'reservation.json';self.api=api;self.hooks={};self.proxy_source=proxy_source
        self.max_zip_bytes=max_zip_bytes

    def read(self):
        try:return json.loads(self.path.read_text())
        except FileNotFoundError:return None

    def claim(self,record,*,path=None):
        # Exclusive create + fsync before any network call: a crash consumes this
        # one-shot epoch too. An existing incomplete file is never replayed.
        try:fd=os.open(path or self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:return False
        with os.fdopen(fd,'w') as stream:
            json.dump(record,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        directory=os.open(self.root,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return True

    def save(self,record,**change):
        record.update(change,updated_at=time.time());atomic_json(self.path,record)

    def restore(self,pages):
        record=self.read()
        if not record:return
        tid=record.get('target_id');page=pages.get(tid)
        if page is not None and tid not in self.hooks:
            def block(route):
                request=route.request
                if not matches(request):route.continue_();return
                body=request.post_data_buffer
                if _sha(request.url.encode())==record.get('request_sha256') or isinstance(body,bytes) and _sha(body)==record.get('zip_sha256'):
                    route.abort('failed')
                else:route.continue_()
            page.route('**/*',block);self.hooks[tid]=block

    def arm(self,page,context,guard):
        expected=context.get('bundle',{}).get('zip_sha256')
        if not re.fullmatch('[0-9a-f]{64}',expected or ''):return False
        key=_sha(json.dumps([context.get('lane'),context.get('job_id'),context.get('paper_id'),expected],sort_keys=True).encode())
        for intent in self.root.parent.glob('*/intent.json'):
            old=json.loads(intent.read_text())
            if old.get('material_key')==key:raise RuntimeError('原上传探测已有持久意图，保留原回执，不重传')
        if self.max_zip_bytes is not None:
            size=context.get('bundle',{}).get('size')
            if type(size) is not int or not 0<size<=self.max_zip_bytes:return False
        existing=self.read()
        if existing is not None:
            if existing.get('material_key')==key:
                raise RuntimeError('原上传探测已有持久意图，保留原回执，不重传')
            return False
        reservation={'material_key':key,'target_id':context.get('target_id'),'job_id':context.get('job_id'),
                     'zip_sha256':expected,'upload_attempt_id':context.get('upload_attempt_id'),
                     'reserved_at':time.time(),'state':'armed'}
        if not self.claim(reservation,path=self.reservation):
            prior=json.loads(self.reservation.read_text())
            if prior.get('material_key')==key:raise RuntimeError('原上传对照已登记该材料，保留原回执，不重传')
            return False
        def handle(route):
            request=route.request
            if not matches(request):route.continue_();return
            request_sha=_sha(request.url.encode())
            for old_path in self.root.parent.glob('*/intent.json'):
                if json.loads(old_path.read_text()).get('request_sha256')==request_sha:
                    route.abort('failed');return
            body=request.post_data_buffer
            # A multipart/block PUT or unreadable body is outside this probe;
            # keep the original native path, report no successful intervention.
            if (not isinstance(body,bytes) or _sha(body)!=expected
                    or self.max_zip_bytes is not None and len(body)>self.max_zip_bytes):
                route.continue_();return
            prior=self.read()
            if prior is not None:
                if prior.get('material_key')==key:route.abort('failed')
                else:route.continue_()
                return
            try:guard();headers=forward_headers(request,body)
            except Exception:
                route.abort('failed');return
            record={'schema_version':1,'state':'intent','created_at':time.time(),'owner_pid':os.getpid(),
                'target_id':context.get('target_id'),'lane':context.get('lane'),'job_id':context.get('job_id'),
                'material_key':key,'zip_sha256':expected,'zip_bytes':len(body),
                'request_sha256':_sha(request.url.encode()),'host':urlsplit(request.url).hostname,
                'transport':('system-curl-http1.1' if type(self.api).__name__=='_CurlPut' else 'playwright-api-http1.1'),
                'automatic_retries':0,'max_redirects':0}
            record['proxy_source']=self.proxy_source
            if not self.claim(record):route.abort('failed');return
            response=None
            try:
                response=self.api.fetch(request.url,method='PUT',headers=headers,data=body,timeout=180000,
                    max_retries=0,max_redirects=0,fail_on_status_code=False)
                self.save(record,state='response_saved',status=response.status,elapsed_seconds=time.time()-record['created_at'])
                from .owner_http1_transport import _Response
                if isinstance(response,_Response):
                    route.fulfill(status=response.status,headers=response.headers,body=response.content)
                else:route.fulfill(response=response)
                self.save(record,fulfilled=True)
            except (Exception,asyncio.CancelledError) as exc:
                # No native fallback or API retry after a possibly delivered PUT.
                try:self.save(record,state='unknown' if response is None else 'response_saved',
                              **error_evidence(exc),fulfilled=False)
                finally:route.abort('failed')
            finally:
                if response is not None:response.dispose()
        page.route('**/*',handle);self.hooks[context['target_id']]=handle
        return True


class OriginalPutUploads:
    """Promote only after the bounded original PUT and native settle succeeded."""
    def __init__(self,root,api,epoch,proxy_source,*,promote=False,max_probe_zip_bytes=None):
        self.root=root;self.api=api;self.epoch=epoch;self.proxy_source=proxy_source;self.promote=promote
        self.first=OriginalPutProbe(root,api,epoch,proxy_source=proxy_source,max_zip_bytes=max_probe_zip_bytes);self.probes={}
        self.restored={}

    def for_material(self,context):
        first=self.first.read() or {}
        if not (self.promote and first.get('fulfilled') is True and first.get('native_settled') is True
                and type(first.get('status')) is int and 200<=first['status']<300):return self.first
        key=_sha(json.dumps([context.get('lane'),context.get('job_id'),context.get('paper_id'),
            context.get('bundle',{}).get('zip_sha256')],sort_keys=True).encode())
        if key not in self.probes:
            self.probes[key]=OriginalPutProbe(self.root,self.api,'material-'+key,proxy_source=self.proxy_source)
        return self.probes[key]

    def restore(self,pages):
        fresh={tid:page for tid,page in pages.items() if self.restored.get(tid) is not page}
        if not fresh:return
        records={tid:[] for tid in fresh}
        for path in self.first.root.parent.glob('*/intent.json'):
            record=json.loads(path.read_text())
            if record.get('target_id') in records:records[record['target_id']].append(record)
        for tid,page in fresh.items():
            history=records[tid]
            if history:
                def block(route,history=history):
                    request=route.request
                    if not matches(request):route.continue_();return
                    body=request.post_data_buffer;request_sha=_sha(request.url.encode())
                    if any(request_sha==r.get('request_sha256') or isinstance(body,bytes) and _sha(body)==r.get('zip_sha256') for r in history):route.abort('failed')
                    else:route.continue_()
                page.route('**/*',block)
        self.restored.update(fresh)


def configure(root,pw,policy):
    global _CONTROLLER
    _CONTROLLER=None
    if policy.get('enabled') is not True:return
    epoch=policy.get('epoch','')
    if not re.fullmatch('[a-zA-Z0-9-]{1,80}',epoch) or policy.get('max_materials',1)!=1:raise ValueError('Invalid original PUT one-shot policy')
    probe_limit=policy.get('max_probe_zip_bytes')
    if probe_limit is not None and (type(probe_limit) is not int or probe_limit<=0):raise ValueError('Invalid bounded probe size')
    from importlib.metadata import version
    if version('playwright')!='1.63.0':raise ValueError('HTTP/1.1 probe requires the locally verified SDK')
    if any(os.environ.get(k) for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')):
        raise ValueError('Explicit proxy present: protocol experiment not configured for this route')
    proxy=None
    if os.uname().sysname=='Darwin':
        result=subprocess.run(['/usr/sbin/scutil','--proxy'],capture_output=True,text=True,timeout=3,check=True)
        proxy=system_proxy(result.stdout)
    options={'ignore_https_errors':False}
    if proxy:options['proxy']=proxy
    transport=policy.get('transport','playwright')
    if transport not in ('playwright','system_curl'):raise ValueError('未知原PUT传输')
    if transport=='system_curl':
        from .owner_http1_transport import _CurlPut
        api=_CurlPut(pw,proxy)
    else:api=pw.request.new_context(**options)
    _CONTROLLER=OriginalPutUploads(root,api,epoch,
        proxy_source='macos_existing_https_proxy' if proxy else 'existing_direct_route',
        promote=policy.get('promote_on_native_success') is True,max_probe_zip_bytes=policy.get('max_probe_zip_bytes'))


def restore(pages):
    if _CONTROLLER is not None:_CONTROLLER.restore(pages)


@contextmanager
def armed(page,context,guard):
    controller=_CONTROLLER.for_material(context) if _CONTROLLER is not None else None
    active=controller is not None and controller.arm(page,context,guard)
    # Keep its duplicate guard installed until page retirement/owner handoff.
    try:yield
    finally:
        if active:
            record=controller.read()
            if record:
                context.setdefault('upload_diagnostic',{}).update(original_put_intent=str(controller.path),
                    original_put_state=record.get('state'),original_put_unknown=record.get('state')=='unknown')
        if active and controller.read() is None:
            record=json.loads(controller.reservation.read_text())
            record.update(state='not_observed',finished_at=time.time())
            atomic_json(controller.reservation,record)


def native_settled(context):
    path=context.get('upload_diagnostic',{}).get('original_put_intent')
    if path:
        record=json.loads(Path(path).read_text())
        if record.get('state')=='response_saved' and record.get('fulfilled') is True:
            record.update(native_settled=True,native_settled_at=time.time());atomic_json(path,record)
