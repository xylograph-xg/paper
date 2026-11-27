"""Small public-provider HTTP policy with persistent cooldowns, never long retries."""
from core.api import paths__workspace_root as _workspace_root
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import os
from core.api import paths__WorkspacePath as Path
import time
import urllib.error
import urllib.parse
import urllib.request


class DeferredRequest(RuntimeError):
    def __init__(self,provider,retry_at,code=None,*,request_started=False,reason='cooldown'):
        self.provider=provider;self.retry_at=retry_at;self.code=code
        self.request_started=request_started;self.reason=reason
        super().__init__(f'{provider} 暂缓请求（HTTP {code or "cooldown"}），下一次 {datetime.fromtimestamp(retry_at,timezone.utc).isoformat()}')


PROVIDER_HOSTS={'openalex':'api.openalex.org','crossref':'api.crossref.org','s2':'api.semanticscholar.org'}


def canonical_provider(provider):
    """Only explicit API aliases merge; publisher/subdomain permissions do not."""
    aliases={f'pdf:{host}':key for key,host in PROVIDER_HOSTS.items()}
    aliases.update({host:key for key,host in PROVIDER_HOSTS.items()})
    return aliases.get(provider,provider)


def provider_keys(provider):
    canonical=canonical_provider(provider)
    host=PROVIDER_HOSTS.get(canonical)
    return (canonical,'pdf:'+host,host) if host else (canonical,)


def provider_for_url(url):
    host=urllib.parse.urlsplit(url).hostname
    if not host:raise ValueError('缺少请求主机')
    return 'arxiv-pdf' if host in {'arxiv.org','export.arxiv.org'} else canonical_provider('pdf:'+host)


def state_folder(folder=None):
    return Path(folder or os.environ.get('PAPER_NETWORK_STATE_DIR') or _workspace_root()/'data')


@contextmanager
def state_file(folder=None):
    folder=state_folder(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'network-state.json'
    with (folder/'network-state.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:data=json.loads(path.read_text())
        except (OSError,ValueError):data={}
        original=json.dumps(data,sort_keys=True)
        yield data
        if json.dumps(data,sort_keys=True)!=original:
            from core.api import services__atomic_json as atomic_json
            atomic_json(path,data)


def ready(provider,folder=None):
    with state_file(folder) as data:
        states=[data.get(key,{}) for key in provider_keys(provider)]
        state=max(states,key=lambda value:value.get('retry_at',0))
    if state.get('retry_at',0)>time.time():
        raise DeferredRequest(canonical_provider(provider),state['retry_at'],state.get('code'))


def retry_seconds(headers,default=60):
    value=(headers or {}).get('Retry-After')
    if value:
        try:return max(1,float(value))
        except ValueError:
            try:return max(1,parsedate_to_datetime(value).timestamp()-time.time())
            except (TypeError,ValueError,OverflowError):pass
    return default


def failed(provider,code=None,headers=None,folder=None):
    with state_file(folder) as data:
        keys=provider_keys(provider);provider=keys[0]
        states=[data.get(key,{}) for key in keys]
        old=data.get(provider,{})
        failures=max(state.get('failures',0) for state in states)+1
        if code==429:
            delay=retry_seconds(headers,min(900,60*2**min(failures-1,4)))
        elif code==401:
            # An auth response is either a bad/absent credential or an upstream
            # transient. Keep probing with a bounded backoff instead of locking
            # every seed/PDF request out for a full day.
            delay=min(3600,60*2**min(failures-1,5))
        else:
            delay=min(600,15*2**min(failures-1,5))
        if code==403:
            # Publisher WAF blocks are host-specific; retain the longer pause.
            delay=max(delay,86400 if failures>=3 else 600)
        delay*=__import__('random').uniform(1,1.1)
        retry_at=max(time.time()+delay,max(state.get('retry_at',0) for state in states))
        data[provider]={**old,'retry_at':retry_at,'code':code,'failures':failures,'updated':time.time()}
    return retry_at


def succeeded(provider,folder=None,started=None):
    with state_file(folder) as data:
        keys=provider_keys(provider)
        if started is not None and any(data.get(key,{}).get('updated',0)>started and data.get(key,{}).get('retry_at',0)>time.time() for key in keys):return
        for key in keys:
            if key==keys[0] or key in data:
                data[key]={**data.get(key,{}),'retry_at':0,'code':None,'failures':0,'updated':time.time()}


def pace(provider,interval,folder=None):
    # Reserve a time slot while holding the lock, then sleep outside it.
    with state_file(folder) as data:
        keys=provider_keys(provider);provider=keys[0];old=data.get(provider,{})
        slot=max(time.time(),max(data.get(key,{}).get('slot',0) for key in keys)+interval)
        if slot-time.time()>max(5,2*interval):
            raise DeferredRequest(provider,slot,reason='pacing')
        data[provider]={**old,'slot':slot}
    time.sleep(max(0,slot-time.time()))


@contextmanager
def arxiv_connection(folder=None):
    folder=state_folder(folder);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'arxiv-api-active.lock').open('a') as fd:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield


class ProviderClient:
    def __init__(self,folder=None,timeout=15):
        self.folder=state_folder(folder);self.timeout=timeout

    def get(self,url,params=None,provider=None,xml=False):
        provider=canonical_provider(provider or urllib.parse.urlsplit(url).hostname)
        headers={'User-Agent':'PaperLibrary/0.3 (personal literature research)','Accept':'application/atom+xml' if xml else 'application/json'}
        params=dict(params or {})
        email=os.environ.get('OPENALEX_EMAIL') or os.environ.get('OPENALEX_MAILTO') or os.environ.get('CROSSREF_EMAIL')
        if email:
            headers['User-Agent']+=f' (mailto:{email})'
            if provider in ('openalex','crossref'):params['mailto']=email
        if provider=='openalex' and os.environ.get('OPENALEX_API_KEY'):
            headers['Authorization']='Bearer '+os.environ['OPENALEX_API_KEY']
        if provider=='s2':
            key=os.environ.get('S2_API_KEY') or os.environ.get('SEMANTIC_SCHOLAR_API_KEY')
            if key:headers['x-api-key']=key
        query=urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
        request=urllib.request.Request(url+('?' if '?' not in url else '&')+query if query else url,headers=headers)
        from .metadata_cache import read as cache_read,write as cache_write
        cached=cache_read(request.full_url,self.folder) if not xml else None
        if cached is not None:return json.loads(cached)
        ready(provider,self.folder)
        started=time.time()
        interval={'openalex':1.0,'crossref':1.1,'s2':1.1,'arxiv':3.2,'pdf:www.cambridge.org':1.1}.get(provider,.2)
        guard=arxiv_connection(self.folder) if provider=='arxiv' else nullcontext()
        with guard:
            pace(provider,interval,self.folder)
            ready(provider,self.folder)
            try:
                with urllib.request.urlopen(request,timeout=self.timeout) as response:
                    body=response.read(8*1024*1024+1)
                    response_headers=getattr(response,'headers',{})
                if len(body)>8*1024*1024:raise ValueError('书目响应超过 8MB')
                data=body if xml else json.loads(body)
            except urllib.error.HTTPError as exc:
                if exc.code in (400,404,405,410,422):raise
                retry_at=failed(provider,exc.code,exc.headers,self.folder)
                raise DeferredRequest(provider,retry_at,exc.code,request_started=True,reason='http') from None
            except ValueError as exc:
                raise ValueError(f'{provider} 书目格式/体积错误：{exc}') from exc
            except OSError as exc:
                retry_at=failed(provider,folder=self.folder)
                raise DeferredRequest(provider,retry_at,request_started=True,reason='transport') from exc
        succeeded(provider,self.folder,started)
        if not xml:cache_write(request.full_url,body,self.folder,response_headers)
        return data
