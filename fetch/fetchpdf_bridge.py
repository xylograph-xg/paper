"""Isolated public-only fetchpdf runner; stdout is a single JSON result."""
import contextlib
import json
import os
import sys
from core.api import paths__WorkspacePath as Path


RESPONSE_LIMIT = 60 * 1024 * 1024
METADATA_LIMIT = 8 * 1024 * 1024


def install_http_guards(unpaywall_enabled=True, attempts=None, statistics=None):
    # Third-party HTTP remains subject to our public-address and TLS policy.
    import requests
    from core.api import services__public_url as public_url
    import time
    from .network import succeeded,pace,provider_for_url,PROVIDER_HOSTS
    original=requests.sessions.Session.send
    def checked_send(session,request,**kwargs):
        from .network import ready,failed,DeferredRequest
        from urllib.parse import urlsplit
        host=urlsplit(request.url).hostname
        if host=='api.unpaywall.org' and not unpaywall_enabled:
            raise ValueError('Unpaywall 未配置联系邮箱，已跳过请求')
        public_url(request.url)
        if not getattr(session,'_paper_public_connections',False):
            from .public_http import requests_adapter
            session.mount('https://',requests_adapter());session.mount('http://',requests_adapter())
            session._paper_public_connections=True
        kwargs['proxies']={}
        provider=provider_for_url(request.url)
        def record(kind,code=None,retry_at=0,error='',*,request_started=False,reason=None):
            if attempts is not None:attempts.append({'url':provider,'provider':provider,'kind':kind,'code':code,
                'retry_at':retry_at,'error':error,'request_started':request_started,'wait_reason':reason})
        from .metadata_cache import read as cache_read,write as cache_write
        cacheable=request.method=='GET' and not kwargs.get('stream') and not request.headers.get('Cookie')
        cached=cache_read(request.url) if cacheable else None
        if cached is not None:
            response=requests.Response();response.status_code=200;response.url=request.url;response.request=request
            response._content=cached;response._content_consumed=True;response.encoding='utf-8'
            response.headers['Content-Type']='application/json';response.from_cache=True
            if statistics is not None:statistics['cache_hits']=statistics.get('cache_hits',0)+1
            return response
        started=time.time()
        try:
            ready(provider)
            if provider in PROVIDER_HOSTS:
                pace(provider,{'openalex':1.0,'s2':1.1,'crossref':1.1}[provider])
            else:
                from .net_limits import pace_arxiv
                pace_arxiv(request.url)
            ready(provider)
        except DeferredRequest as exc:
            record('resource_wait' if exc.reason in ('pacing','host_busy') else 'deferred',exc.code,exc.retry_at,str(exc),reason=exc.reason);raise
        kwargs['verify']=True
        timeout=kwargs.get('timeout') or 15
        from .acquisition_budget import remaining
        budget=min(15,remaining(12))
        kwargs['timeout']=tuple(min(t or budget,budget) for t in timeout) if isinstance(timeout,tuple) else min(timeout,budget)
        if statistics is not None:statistics['requests_started']=statistics.get('requests_started',0)+1
        follow_redirects=kwargs.pop('allow_redirects',True)
        kwargs['stream']=True
        kwargs['allow_redirects']=False
        def bounded_response(response, **_):
            if getattr(response,'_paper_body_checked',False) is True:
                return response
            content_type=response.headers.get('Content-Type','').lower()
            limit=METADATA_LIMIT if any(t in content_type for t in ('json','xml','text/')) else RESPONSE_LIMIT
            try:
                advertised=response.headers.get('Content-Length')
                if advertised and int(advertised)>limit:
                    raise ValueError('获取响应超过体积限制')
                body=bytearray()
                # iter_content counts decoded bytes, including gzip/chunked responses.
                for chunk in response.iter_content(chunk_size=64*1024):
                    if len(body)+len(chunk)>limit:
                        raise ValueError('获取响应超过体积限制')
                    body.extend(chunk)
                response._content=bytes(body)
                response._content_consumed=True
            finally:
                response.close()
            response._paper_body_checked=True
            return response
        # Session.send consumes redirect bodies to prepare _next even when
        # allow_redirects=False. A response hook bounds them before that happens.
        previous_hooks=request.hooks.get('response',[])
        request.hooks['response']=[bounded_response,*previous_hooks]
        try:
            try:response=original(session,request,**kwargs)
            finally:request.hooks['response']=previous_hooks
        except requests.RequestException as exc:
            record('timeout' if isinstance(exc,requests.Timeout) else 'download_error',error=type(exc).__name__,request_started=True);raise
        retry_at=0
        if response.status_code in (401,403,429,500,502,503,504):
            retry_at=failed(provider,response.status_code,response.headers)
        if response.status_code>=400:
            record('access_check' if response.status_code in (401,403) else 'http_error',response.status_code,retry_at,
                   error='HTTP '+str(response.status_code),request_started=True)
        if response.status_code in (429,500,502,503,504):
            response.close()
            raise DeferredRequest(provider,retry_at,response.status_code,request_started=True,reason='http')
        bounded_response(response)
        if response.status_code==200:
            succeeded(provider,started=started)
        # Requests eagerly consumes redirect bodies even with stream=True;
        # resolve them only after every hop has passed the same bounded reader.
        if follow_redirects and response.status_code in (301,302,303,307,308):
            redirect_options={k:v for k,v in kwargs.items() if k!='allow_redirects'}
            history=list(session.resolve_redirects(response,request,**redirect_options))
            if history:
                history.insert(0,response)
                response=history.pop()
                response.history=history
        if cacheable and response.status_code==200:
            cache_write(request.url,response.content,headers=response.headers)
        return response
    requests.sessions.Session.send=checked_send
    return original


def main():
    payload=json.load(sys.stdin)
    attempts=[]
    statistics={'requests_started':0,'cache_hits':0}
    install_http_guards(bool(payload.get('email')),attempts,statistics)
    if payload.get('email'):
        os.environ['EMAIL']=payload['email']
    os.environ.pop('SERPAPI_API_KEY',None)
    os.environ.pop('ELSEVIER_TDM_API_KEY',None)
    source=[None]
    with contextlib.redirect_stdout(sys.stderr):
        from fetchpdf import fetch_pdf
        from fetchpdf.retrieval.institutional import disable_cookies
        disable_cookies()
        path=fetch_pdf(payload['doi'],payload['save_path'],email=payload.get('email'),
                       verbose=True,delay=1,allow_xml_fallback=False,use_playwright=False,
                       _source_out=source)
    result={'path':str(path) if path else None,'source':source[0],
            'unpaywall_enabled':bool(payload.get('email')),'attempts':attempts,**statistics}
    if path and (not Path(path).is_file() or Path(path).stat().st_size>60*1024*1024):
        raise ValueError('输出文件无效或超过 60MB')
    print(json.dumps(result))


if __name__=='__main__':
    from core.api import process_runner__watch_parent as watch_parent
    watch_parent()
    main()
