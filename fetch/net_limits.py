"""Persisted host pacing shared by direct downloads and their redirects."""
import fcntl
import time
from urllib.parse import urlsplit


def pace_arxiv(url):
    parsed=urlsplit(url)
    if not parsed.hostname:raise ValueError('缺少下载主机')
    if parsed.hostname not in {'arxiv.org','export.arxiv.org'}:
        from .network import ready,pace
        provider='pdf:'+parsed.hostname.lower()
        ready(provider);pace(provider,3.0);ready(provider)
        return
    delay=3.2 if parsed.path.startswith('/api/') else 15.0
    from .network import pace,ready
    ready('arxiv' if parsed.path.startswith('/api/') else 'arxiv-pdf')
    pace('arxiv' if parsed.path.startswith('/api/') else 'arxiv-pdf',delay)


from contextlib import contextmanager
import hashlib


@contextmanager
def pdf_connection(url):
    """One direct transfer per host across processes; contention defers the task."""
    host=urlsplit(url).hostname
    if not host:raise ValueError('缺少下载主机')
    from .network import state_folder,DeferredRequest
    folder=state_folder();folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(host.lower().encode()).hexdigest()
    with (folder/('pdf-host-'+key+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeferredRequest('pdf:'+host.lower(),time.time()+3,reason='host_busy') from None
        yield
