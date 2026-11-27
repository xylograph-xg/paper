"""Validate the addresses that are actually connected; preserve TLS host/SNI."""
import http.client
import socket
import urllib.request


def dial_public(address, timeout=15, source_address=None, **kwargs):
    host,port=address
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    # Share the address policy with services.public_url so DNS-resolved local
    # proxy fake addresses work here too. A literal IP in that range stays
    # rejected by the helper.
    from core.api import services__is_public_address as is_public_address
    if not addresses or any(not is_public_address(host,row[4][0]) for row in addresses):
        raise ValueError('连接地址指向本机或内网，已拒绝')
    last=None
    for family,kind,proto,_,endpoint in addresses:
        connection=socket.socket(family,kind,proto)
        try:
            connection.settimeout(timeout)
            if source_address:connection.bind(source_address)
            connection.connect(endpoint)
            return connection
        except OSError as exc:last=exc;connection.close()
    raise last or OSError('公开地址无法连接')


class HTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self._create_connection=dial_public
        return super().connect()


class HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        self._create_connection=dial_public
        return super().connect()


class HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self,request):return self.do_open(HTTPConnection,request)


class HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self,request):
        return self.do_open(HTTPSConnection,request,context=self._context)


def opener(redirect_handler):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),HTTPHandler(),HTTPSHandler(),redirect_handler)


def requests_adapter():
    from requests.adapters import HTTPAdapter
    from urllib3.connection import HTTPConnection as UHTTP,HTTPSConnection as UHTTPS
    from urllib3.connectionpool import HTTPConnectionPool,HTTPSConnectionPool
    class PinnedHTTP(UHTTP):
        def _new_conn(self):return dial_public((self._dns_host,self.port),self.timeout,self.source_address)
    class PinnedHTTPS(UHTTPS):
        def _new_conn(self):return dial_public((self._dns_host,self.port),self.timeout,self.source_address)
    class HTTPPool(HTTPConnectionPool):ConnectionCls=PinnedHTTP
    class HTTPSPool(HTTPSConnectionPool):ConnectionCls=PinnedHTTPS
    class Adapter(HTTPAdapter):
        def init_poolmanager(self,*args,**kwargs):
            super().init_poolmanager(*args,**kwargs)
            self.poolmanager.pool_classes_by_scheme={'http':HTTPPool,'https':HTTPSPool}
    return Adapter()
