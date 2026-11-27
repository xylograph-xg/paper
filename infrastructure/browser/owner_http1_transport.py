"""One original PUT over system curl, on the resident owner's event loop.

No shell, retries, redirects, TLS bypass, browser restart or node selection.
Signed URLs and request headers go through stdin, never process arguments/logs.
"""
import asyncio
import hashlib
import json
import re
import tempfile
from pathlib import Path


class _Response:
    def __init__(self,status,headers,body):
        self.status=status;self.headers=headers;self.content=body
    def dispose(self):pass


class _CurlPut:
    def __init__(self,pw,proxy=None):
        self.pw=pw;self.proxy=proxy

    def fetch(self,url,*,method,headers,data,timeout,max_retries,max_redirects,fail_on_status_code):
        if method!='PUT' or max_retries!=0 or max_redirects!=0:
            raise ValueError('原PUT传输禁止重试、重定向或其他方法')
        return self.pw._sync(self._perform(url,headers,data,timeout))

    async def _perform(self,url,headers,data,timeout):
        def setting(name,value):return name+' = '+json.dumps(str(value),ensure_ascii=False)
        lines=[setting('url',url),setting('request','PUT'),setting('max-time',timeout/1000),
               setting('connect-timeout',min(30,timeout/1000))]
        # Explicit empty proxy/noproxy prevent unrelated environment variables
        # from changing the verified macOS route; direct TUN remains untouched.
        lines += [setting('proxy',self.proxy['server'] if self.proxy else ''),
                  setting('noproxy',self.proxy.get('bypass','') if self.proxy else '')]
        for key,value in headers.items():
            if not re.fullmatch(r'[!#$%&\x27*+.^_`|~0-9A-Za-z-]+',key) or any(c in str(value) for c in '\r\n\x00'):
                raise ValueError('原请求头格式不完整')
            lines.append(setting('header',key+': '+str(value)))
        with tempfile.TemporaryDirectory(prefix='paper-original-put-') as folder:
            base=Path(folder);body=base/'request';reply=base/'response';head=base/'headers'
            await asyncio.to_thread(body.write_bytes,data)
            process=await asyncio.create_subprocess_exec('/usr/bin/curl','--disable','--http1.1',
                '--silent','--show-error','--retry','0','--max-redirs','0','--config','-',
                '--data-binary','@'+str(body),'--output',str(reply),'--dump-header',str(head),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                _,error=await asyncio.wait_for(process.communicate(('\n'.join(lines)+'\n').encode()),timeout/1000+5)
            except TimeoutError as exc:
                raise TimeoutError('original HTTP/1.1 PUT timeout; no complete response within '+str(timeout/1000+5)+' seconds') from exc
            finally:
                if process.returncode is None:
                    process.kill();await process.wait()
            if process.returncode:
                # Curl may have delivered bytes before any error; caller saves
                # unknown and blocks replay, even for an apparently local error.
                raise RuntimeError('原HTTP/1.1 PUT失败；curl_exit='+str(process.returncode)+
                                   '；error_sha256='+hashlib.sha256(error).hexdigest())
            blocks=head.read_bytes().split(b'\r\n\r\n')
            block=next((b for b in reversed(blocks) if b.startswith(b'HTTP/')),None)
            if block is None:raise ValueError('原PUT响应头不完整')
            rows=block.decode('latin-1').split('\r\n');status=int(rows[0].split()[1]);response_headers={}
            for row in rows[1:]:
                key,separator,value=row.partition(':')
                if separator and key.lower() not in ('connection','transfer-encoding','content-length','keep-alive','proxy-connection'):
                    response_headers[key.lower()]=value.strip()
            return _Response(status,response_headers,reply.read_bytes())
