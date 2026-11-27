"""Bounded public JSON metadata cache; no PDFs, cookies, failures or credentials.

Native discovery and isolated fetchpdf processes use identical URL keys. Cached
data is only a source response: PDF identity/version/publication checks remain.
"""
import hashlib
import json
import os
from core.api import paths__WorkspacePath as Path
import time
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit

MAX_BYTES=8*1024*1024
TTL_SECONDS=86400
CACHE_BYTES=512*1024*1024
PATHS={
    'api.openalex.org':('/works',),
    'api.crossref.org':('/works','/prefixes'),
    'api.semanticscholar.org':('/graph/v1/paper',),
    'api.unpaywall.org':('/v2/',),
}
PRIVATE_PARAMS={'api_key','apikey','token','key','email','mailto','access_token'}


def identity(url):
    if os.environ.get('PAPER_METADATA_CACHE_ENABLED','1')=='0':return None
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):return None
    prefixes=PATHS.get(parsed.hostname,())
    if not any(parsed.path==prefix or parsed.path.startswith(prefix if prefix.endswith('/') else prefix+'/') for prefix in prefixes):return None
    query=sorted((k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True) if k.lower() not in PRIVATE_PARAMS)
    return urlunsplit(('https',parsed.hostname,parsed.path,urlencode(query),''))


def location(key,folder=None):
    from .network import state_folder
    return state_folder(folder)/'metadata-response-cache'/(hashlib.sha256(key.encode()).hexdigest()+'.json')


def read(url,folder=None):
    key=identity(url)
    if key is None:return None
    path=location(key,folder)
    try:
        if path.stat().st_size>MAX_BYTES*2+4096:return None
        value=json.loads(path.read_text())
        ttl=min(TTL_SECONDS,value.get('ttl_seconds',TTL_SECONDS))
        if value['key']!=key or not 0<=time.time()-value['created']<ttl:return None
        body=value['body'].encode('utf-8')
        if len(body)>MAX_BYTES or hashlib.sha256(body).hexdigest()!=value['sha256']:return None
        if not isinstance(json.loads(body),(dict,list)):return None
        return body
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def write(url,body,folder=None,headers=None):
    key=identity(url)
    if key is None or not isinstance(body,bytes) or len(body)>MAX_BYTES:return False
    try:
        control=str((headers or {}).get('Cache-Control','')).lower()
        if 'no-store' in control or 'no-cache' in control or 'private' in control:return False
        ttl=TTL_SECONDS
        import re
        age=re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)',control)
        if age:ttl=min(ttl,int(age[1]))
        if ttl<=0:return False
        if not isinstance(json.loads(body),(dict,list)):return False
        text=body.decode('utf-8')
        from core.api import services__atomic_json as atomic_json
        path=location(key,folder);path.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(path,{'key':key,'created':time.time(),'ttl_seconds':ttl,'sha256':hashlib.sha256(body).hexdigest(),'body':text})
        prune(path.parent)
        return True
    except (OSError,ValueError,UnicodeError):return False


def prune(folder):
    """At most hourly, discard expired/oldest cache copies, never raw evidence."""
    import fcntl
    folder=Path(folder);stamp=folder/'cleanup.json';at=time.time()
    try:
        if stamp.exists() and 0<=at-stamp.stat().st_mtime<3600:return
        with (folder/'cleanup.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            if stamp.exists() and 0<=at-stamp.stat().st_mtime<3600:return
            files=[]
            for path in folder.glob('*.json'):
                if path==stamp:continue
                try:stat=path.stat();files.append((stat.st_mtime,stat.st_size,path))
                except FileNotFoundError:continue
            total=sum(size for _,size,_ in files)
            for modified,size,path in sorted(files):
                if at-modified>=TTL_SECONDS or total>CACHE_BYTES:
                    path.unlink(missing_ok=True);total-=size
            from core.api import services__atomic_json as atomic_json
            atomic_json(stamp,{'updated':at,'bytes':total},durable=False)
    except OSError:pass  # Cache maintenance never invalidates a fetched response.
