"""Authenticated workbench on loopback or through the configured tailnet proxy."""
from __future__ import annotations
import json
import re
import csv
import io
import hashlib
import mimetypes
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
import traceback
import threading
import socket
import select
import time
import urllib.parse
import urllib.request
import webbrowser
from http.cookies import SimpleCookie,CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from core.api import paths__WorkspacePath as Path

from core.api import catalog__ROOT as ROOT, catalog__Catalog as Catalog
from core.api import services__init_seeds as init_seeds, services__validate_pdf as validate_pdf


def csv_text(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value


def card_image_asset(root, image_path):
    """Resolve evidence inside a card directory, including relocated card folders."""
    root=Path(root).resolve()
    if not image_path:return None
    image=Path(image_path)
    candidates=[image if image.is_absolute() else root/image]
    # Old absolute paths retain the exact card directory name and relative suffix.
    for i,part in enumerate(image.parts[:-1]):
        if part==root.name:candidates.append(root.joinpath(*image.parts[i+1:]))
    for candidate in candidates:
        candidate=candidate.resolve()
        if candidate.is_relative_to(root) and candidate.is_file():return str(candidate.relative_to(root))
    return None


class WorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads=True

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.request_slots=threading.BoundedSemaphore(16)
        self.handshake_slots=threading.BoundedSemaphore(64)

    def process_request(self,request,address):
        if not self.handshake_slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:threading.Thread(target=self._handshake,args=(request,address),daemon=True).start()
        except BaseException:self.handshake_slots.release();self.shutdown_request(request);raise

    def _handshake(self,request,address):
        try:
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                if not select.select([request],[],[],max(0,deadline-time.monotonic()))[0]:break
                data=request.recv(16385,socket.MSG_PEEK)
                if not data:break
                if b'\r\n\r\n' in data and data.index(b'\r\n\r\n')+4<=16384:
                    self._dispatch(request,address);return
                if len(data)>16384:break
                time.sleep(.01)
            self.shutdown_request(request)
        except OSError:self.shutdown_request(request)
        finally:self.handshake_slots.release()

    def _dispatch(self,request,address):
        if not self.request_slots.acquire(blocking=False):
            body=json.dumps({'error':'工作台正忙，请稍后重试。'},ensure_ascii=False).encode()
            headers=('HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n'
                     f'Content-Length: {len(body)}\r\nRetry-After: 2\r\nCache-Control: no-store\r\n'
                     'X-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n').encode('ascii')
            try:request.sendall(headers+body)
            except OSError:pass
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except Exception:self.request_slots.release();raise

    def process_request_thread(self,*args):
        try:super().process_request_thread(*args)
        finally:self.request_slots.release()


def serve(config,config_path,port,open_browser,*,background=False,access_token=None):
    url=f'http://127.0.0.1:{port}'
    passwordless=config.get('workbench_passwordless') is True
    remote_url=None
    if config.get('tailscale_enabled'):
        from .tailscale_access import setup
        remote_url=setup(config,port)
    allowed_hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    allowed_origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    if remote_url:
        allowed_hosts.add(urllib.parse.urlsplit(remote_url).netloc)
        allowed_origins.add(remote_url)
    # Repeated launcher clicks reuse the existing workbench, including older instances.
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=2) as response:
            existing=response.read(4096)
        reuse=b'<title>'+'文献阅读工作台'.encode()+b'</title>' in existing
    except (OSError,ValueError):
        reuse=False
    if reuse:
        try:
            access=json.loads((Path(config['catalog_path']).parent/'workbench-access.json').read_text())
            from core.api import runtime__alive as alive
            if access.get('port')==port and alive(access['pid']) and not access.get('passwordless'):
                url+='/#access='+access['token']
        except (OSError,ValueError,KeyError):pass
        print('文献工作台已在运行：'+url,flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    token=access_token or secrets.token_urlsafe(32)
    access_suffix='/' if passwordless else '/#access='+token
    access_url=url+access_suffix
    catalog=Catalog(config['catalog_path'])
    if not background:init_seeds(catalog,config)

    try:
        server=create_http_server(config,catalog,port,token,allowed_hosts,allowed_origins)
    except OSError as exc:
        raise RuntimeError(f'端口 {port} 被其他服务占用；请使用 --port 指定其他端口。') from exc
    from core.api import services__atomic_json as atomic_json
    server.background=background
    atomic_json(Path(config['catalog_path']).parent/'workbench-access.json',{'pid':os.getpid(),'port':port,'token':token,'background':background,'remote_url':remote_url,'passwordless':passwordless})
    args=[sys.executable,'-m','core.runtime','--parent',str(os.getpid())]
    if config_path:
        args+=['--config',str(Path(config_path).resolve())]
    from core.api import runtime__runtime_status as runtime_status
    current=runtime_status(Path(config['catalog_path']).parent)
    from reading.api import reading_service__status as reading_status
    from fetch.api import fetch_service__paused as fetch_paused
    from core.api import model_schedule__status as model_status
    detached=reading_status(config)
    if background or config.get('web_cards',{}).get('enabled'):
        # Resident fetch/web keepers own their lifetimes; viewing cards is read-only.
        args=None
    elif fetch_paused(config) and model_status(config)['mode']=='paused':
        args=None
    elif detached.get('state')=='running':
        args=None
    elif current.get('state')=='running':
        if current.get('mode')=='fetch_only' and not current.get('lanes',{}).get('read',{}).get('alive'):
            args+=['--read-only']
        else:args=None
    logs=Path(config['catalog_path']).parent/'logs';logs.mkdir(parents=True,exist_ok=True)
    process=None
    try:
        if args:
            from reading.api import log_output__spawn_logged as spawn_logged
            process=spawn_logged(args,logs/'worker.log',cwd=ROOT,start_new_session=True)
    except BaseException:
        server.server_close();raise
    url=f'http://127.0.0.1:{port}'
    print('文献工作台：'+access_url+('；后台运行，可关闭启动器终端。' if background else '；关闭终端停止网页服务。'),flush=True)
    if remote_url:print('Tailscale 工作台访问链接：'+remote_url+access_suffix,flush=True)
    if open_browser:
        webbrowser.open(access_url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGTERM)


def create_http_server(config,catalog,port,token,allowed_hosts,allowed_origins):
    passwordless=config.get('workbench_passwordless') is True
    passwordless_flag='true' if passwordless else 'false'

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(30)

        def log_message(self,*args):
            pass

        def reply(self,status,data,content_type='application/json; charset=utf-8',headers=None):
            if not isinstance(data,bytes):
                data=json.dumps(data,ensure_ascii=False).encode()
            self.reply_headers(status,content_type,len(data),headers)
            self.wfile.write(data)

        def reply_headers(self,status,content_type,length,headers=None):
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(length))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store')
            nonce=getattr(self,'csp_nonce','')
            self.send_header('Content-Security-Policy',f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            for name,value in (headers or {}).items():self.send_header(name,value)
            self.end_headers()

        def reply_file(self,path):
            with path.open('rb') as stream:
                self.reply_headers(200,mimetypes.guess_type(path)[0] or 'application/octet-stream',os.fstat(stream.fileno()).st_size)
                try:
                    for block in iter(lambda:stream.read(256*1024),b''):self.wfile.write(block)
                except (BrokenPipeError,ConnectionResetError,TimeoutError):pass

        def valid_host(self):
            return self.headers.get('Host') in allowed_hosts

        def trusted_network(self):
            # The HTTP listener is loopback-only. Tailscale Serve supplies the
            # identity header for signed-in tailnet users and strips client copies.
            if self.client_address[0]!='127.0.0.1' or len(self.headers.get_all('Host',[]))!=1:
                return False
            host=self.headers.get('Host')
            port=self.server.server_port
            if host in (f'127.0.0.1:{port}',f'localhost:{port}'):
                return True
            identity=self.headers.get_all('Tailscale-User-Login',[])
            return len(identity)==1 and bool(identity[0].strip())

        def page_html(self,body):
            return body.replace('__CSP_NONCE__',self.csp_nonce).replace('__PAPER_PASSWORDLESS__',passwordless_flag)

        def authenticated(self):
            if self.valid_token(self.headers.get('X-Paper-Token','')):return True
            try:
                cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                cookie=cookies.get('PaperSession')
                return bool(cookie and self.valid_token(cookie.value))
            except (CookieError,TypeError):return False

        def valid_token(self,value):
            return bool(value and value.isascii() and secrets.compare_digest(value,token))

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403,{'error':'无效 Host'})
            if passwordless and not self.trusted_network():
                return self.reply(403,{'error':'请通过本机或已登录的 Tailscale 设备访问工作台'})
            try:
                parsed=urllib.parse.urlsplit(self.path)
                public_static=parsed.path.startswith('/vendor/') and Path(parsed.path).suffix in {'.js','.css','.woff','.woff2','.ttf'}
                if not passwordless and parsed.path not in ('/','/literature','/literature/app.js') and not public_static and not self.authenticated():
                    return self.reply(403,{'error':'请使用启动器显示的访问链接或口令登录'})
                if parsed.path=='/':
                    self.csp_nonce=secrets.token_urlsafe(24)
                    body=self.page_html((ROOT/'workbench/workbench.html').read_text())
                    return self.reply(200,body.encode(),'text/html; charset=utf-8')
                if parsed.path in ('/literature','/literature/app.js'):
                    from importlib.resources import files
                    asset = 'index.html' if parsed.path=='/literature' else 'app.js'
                    body=files('literature').joinpath(asset).read_text(encoding='utf-8')
                    self.csp_nonce=secrets.token_urlsafe(24)
                    return self.reply(200,self.page_html(body).encode(),
                                      'text/html; charset=utf-8' if asset=='index.html' else 'text/javascript; charset=utf-8')
                if parsed.path=='/vendor/runtime-status.json':
                    from core.api import runtime__runtime_status as runtime_status
                    from core.api import storage_health__status as storage_status
                    return self.reply(200,{**runtime_status(Path(config['catalog_path']).parent),'storage':storage_status(config)})
                if parsed.path.startswith('/vendor/'):
                    root=(ROOT/'workbench/vendor').resolve()
                    path=(root/parsed.path.removeprefix('/vendor/')).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        return self.reply(404,{'error':'资源不存在'})
                    return self.reply_file(path)
                if parsed.path=='/api/workbench-health':
                    return self.reply(200,{'service':'paper-workbench','pid':os.getpid(),'port':self.server.server_port,
                                          'background':bool(getattr(self.server,'background',False))})
                if parsed.path=='/api/state':
                    from core.api import model_schedule__status as model_status
                    model_state=model_status(config)
                    args=urllib.parse.parse_qs(parsed.query)
                    limit=int(args.get('limit',['100'])[0]);offset=int(args.get('offset',['0'])[0])
                    tab=args.get('tab',['all'])[0]
                    page=catalog.page(limit,offset,args.get('q',[''])[0],tab,args.get('channel',[''])[0],config.get('pdf_only',False))
                    from core.api import continuous_status__status as continuous_status
                    progress=continuous_status(config['catalog_path'])
                    from fetch.api import fetch_service__status as fetch_service_status
                    fetch_status=fetch_service_status(config)
                    from core.api import control__pause_decision as pause_decision
                    fetch_status['control']=pause_decision(config,'fetch').as_dict()
                    web_config=config.get('web_cards',{})
                    web_jobs=[];web_status={}
                    from review.api import card_review_queue__status as review_status
                    review_state=review_status(config)
                    from correction.api import card_correction_queue__status as correction_status
                    correction_state=correction_status(config)
                    from core.api import concurrency_control__settings as concurrency_settings
                    concurrency=concurrency_settings(config)
                    from literature.api import level1_status, level2_status
                    literature_level1=level1_status(config)
                    literature_level2=level2_status(config)
                    if web_config.get('enabled'):
                        from cards.api import web_card_queue__jobs as web_queue
                        from cards.api import web_card_service__status as web_service_status
                        web_jobs=web_queue(catalog,config);web_status=web_service_status(config)
                    manual_cards = [p['manual_seed_card'] for p in page['papers']] if tab == 'manual_seed_cards' else None
                    etag='"'+hashlib.sha256(json.dumps([page['revision'],parsed.query,manual_cards,page['total'],{k:v for k,v in model_state.items() if k!='checked_at'},web_status,progress,fetch_status,review_state,correction_state,concurrency,literature_level1,literature_level2],sort_keys=True).encode()).hexdigest()+'"'
                    if self.headers.get('If-None-Match')==etag:return self.reply(304,b'',headers={'ETag':etag})
                    with catalog.connect() as db:
                        runs=[dict(r) for r in db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 5')]
                        job_counts=[dict(r) for r in db.execute('SELECT kind,state,count(*) count FROM jobs GROUP BY kind,state')]
                    return self.reply(200,{**page,'continuous':progress,'fetch_service':fetch_status,'fetch_timing':__import__('fetch.api',fromlist=['fetch_timing']).fetch_timing.status(catalog),'job_counts':job_counts,'jobs':catalog.jobs_page(100),'runs':runs,'channels':['期刊与种子关联','arXiv','ChemRxiv（Crossref）'],'schedule':config.get('daily_schedule'),'model_schedule':model_state,'pdf_only':config.get('pdf_only',False),'web_cards':web_config,'web_jobs':web_jobs,'web_service':web_status,'card_review':review_state,'card_correction':correction_state,'concurrency':concurrency,'literature_level1':literature_level1,'literature_level2':literature_level2},headers={'ETag':etag})
                if parsed.path=='/api/card':
                    args=urllib.parse.parse_qs(parsed.query);paper=catalog.get(args['id'][0])
                    if not paper.get('card_path'):return self.reply(404,{'error':'卡片尚未生成'})
                    path=Path(paper['card_path'])
                    raw=path.read_bytes()
                    card_hash=hashlib.sha256(raw).hexdigest()
                    if args.get('sha256', [card_hash])[0] != card_hash:
                        return self.reply(409,{'error':'卡片版本已更新，请刷新工作台后再打开。'})
                    card=json.loads(raw)
                    for item in card.get('figures',[])+card.get('equations',[])+card.get('tables',[]):
                        item['asset_file']=card_image_asset(path.parent,item.get('image_path'))
                    from review.api import review_protection__protection as protection
                    card['_review_protection']=protection(path.parent)
                    from review.api import card_review_queue__for_card as for_card
                    card['_source_review']=for_card(config,paper['id'],card_hash)
                    return self.reply(200,card)
                if parsed.path=='/api/reading':
                    from reading.api import reading_library__reading as reading
                    args=urllib.parse.parse_qs(parsed.query)
                    return self.reply(200,reading(catalog,args['id'][0]))
                if parsed.path=='/export/manual.csv':
                    output=io.StringIO();writer=csv.writer(output)
                    writer.writerow(['题名','年份','DOI','出版社链接','获取状态','核心结论'])
                    for p in catalog.list():
                        if p['acquisition'].startswith('needs'):
                            m=p['metadata'];writer.writerow([csv_text(v) for v in [p['title'],m.get('year',''),m.get('doi',''),m.get('url','') or 'https://doi.org/'+m.get('doi',''),p['acquisition'],(p['assessment'] or {}).get('core_findings','')]])
                    return self.reply(200,('\ufeff'+output.getvalue()).encode(),'text/csv; charset=utf-8')
                if parsed.path=='/asset':
                    q=urllib.parse.parse_qs(parsed.query);paper=catalog.get(q['id'][0]);rel=q.get('file',['source.pdf'])[0]
                    if rel=='source.pdf':
                        path=Path(paper['asset_path'] or '')
                        local_source=Path(paper['card_path']).parent/'source.pdf' if paper.get('card_path') else None
                        if local_source and local_source.is_file():path=local_source
                    else:
                        if not paper['card_path']:
                            raise ValueError('还没有卡片')
                        root=Path(paper['card_path']).parent.resolve()
                        path=(root/rel).resolve()
                        if not path.is_relative_to(root) or path.suffix.lower() not in {'.png','.jpg','.json','.md','.pdf'}:
                            raise ValueError('不允许访问此文件')
                    if not path.is_file():
                        raise ValueError('文件不可用，请连接 SSD 或完成处理')
                    return self.reply_file(path)
                self.reply(404,{'error':'未找到'})
            except (ValueError,KeyError) as exc:
                self.reply(400,{'error':str(exc)})
            except (OSError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as exc:
                traceback.print_exc()
                self.reply(503,{'error':'服务暂不可用：'+str(exc)})
            except Exception:
                traceback.print_exc()
                self.reply(500,{'error':'请求处理失败，请查看服务日志'})

        def do_POST(self):
            if urllib.parse.urlsplit(self.path).path in ('/api/import','/api/import-batch','/api/bind-upload'):
                from .upload_storage import upload_lock
                with upload_lock(catalog):return self._do_POST()
            return self._do_POST()

        def _do_POST(self):
            if not self.valid_host():
                return self.reply(403,{'error':'请求校验失败'})
            origin=self.headers.get('Origin')
            if passwordless:
                if not self.trusted_network():
                    return self.reply(403,{'error':'请通过本机或已登录的 Tailscale 设备访问工作台'})
                if (origin not in allowed_origins or len(self.headers.get_all('Origin',[]))!=1
                        or urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host')):
                    return self.reply(403,{'error':'无效来源'})
            elif not self.valid_token(self.headers.get('X-Paper-Token','')):
                return self.reply(403,{'error':'请求校验失败'})
            elif origin and origin not in allowed_origins:
                return self.reply(403,{'error':'无效来源'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=60*1024*1024:
                    raise ValueError('请求体大小不合法')
                parsed=urllib.parse.urlsplit(self.path)
                if parsed.path.startswith('/api/literature/') and length>1024*1024:raise ValueError('文献整理请求不得超过1MiB')
                body=self.rfile.read(length)
                if len(body)!=length:raise ValueError('请求体未完整接收')
                if parsed.path=='/api/session':
                    if passwordless:
                        return self.reply(200,{'ok':True})
                    return self.reply(200,{'ok':True},headers={'Set-Cookie':f'PaperSession={token}; Path=/; HttpOnly; SameSite=Strict'})
                if parsed.path.startswith('/api/literature/'):
                    from literature.api import Library, Conflict
                    operation=parsed.path.removeprefix('/api/literature/')
                    try:result=Library(config['catalog_path']).dispatch(operation,json.loads(body))
                    except Conflict as exc:return self.reply(409,{'error':str(exc)})
                    return self.reply(200,result)
                if parsed.path=='/api/literature-level1/control':
                    data=json.loads(body)
                    if not isinstance(data,dict) or set(data)!={'paused'} or type(data['paused']) is not bool:
                        raise ValueError('一级标注设置无效')
                    from literature.api import level1_control
                    return self.reply(200,{'ok':True,'literature_level1':level1_control(config,data['paused'])})
                if parsed.path=='/api/literature-level2/control':
                    data=json.loads(body)
                    if not isinstance(data,dict) or set(data)!={'paused'} or type(data['paused']) is not bool:
                        raise ValueError('二级标注设置无效')
                    from literature.api import level2_control
                    return self.reply(200,{'ok':True,'literature_level2':level2_control(config,data['paused'])})
                if parsed.path=='/api/continuous/start':
                    from core.api import continuous_start__start as start
                    return self.reply(200,{'ok':True,'services':start(config,open_browser=True)})
                if parsed.path=='/api/workflow/control':
                    data=json.loads(body)
                    if not isinstance(data,dict) or set(data)!={'target','paused'} or data['target'] not in ('fetch','cards','review','correction') or type(data['paused']) is not bool:
                        raise ValueError('任务设置无效')
                    from core.api import continuous_start__start as start, continuous_start__stop as stop
                    result=stop(config,data['target']) if data['paused'] else start(config,target=data['target'],open_browser=data['target']=='cards')
                    return self.reply(200,{'ok':True,'services':result})
                if parsed.path=='/api/concurrency/control':
                    data=json.loads(body)
                    from core.api import concurrency_control__set_limits as set_limits, concurrency_control__set_minimum as set_minimum
                    minimum_key=next(iter(data)) if isinstance(data,dict) and len(data)==1 else ''
                    result=set_minimum(config,data[minimum_key],minimum_key.removesuffix('_min_pages')) if minimum_key in ('cards_min_pages','review_min_pages','correction_min_pages') else set_limits(config,data)
                    return self.reply(200,{'ok':True,'concurrency':result})
                if parsed.path in ('/api/card-review/control','/api/card-correction/control'):
                    correction=parsed.path=='/api/card-correction/control'
                    target='correction' if correction else 'review'
                    label='修正' if correction else '核验'
                    data=json.loads(body)
                    if not isinstance(data,dict) or not data or not set(data)<={'paused','parallel'}:raise ValueError(label+'设置无效')
                    if 'parallel' in data and (type(data['parallel']) is not int or not 1<=data['parallel']<=20):raise ValueError('并行数量超出允许范围')
                    if 'paused' in data and type(data['paused']) is not bool:raise ValueError('暂停设置无效')
                    if 'parallel' in data:
                        from core.api import concurrency_control__set_limit as set_limit
                        set_limit(config,target,data['parallel'])
                    if 'paused' in data:
                        from core.api import control__mutate_record as mutate_record
                        mutate_record(Path(config['catalog_path']).parent/('card-correction-control.json' if correction else 'card-review-control.json'),
                            {'paused_by_user':data['paused'],'reason':'用户暂停'+label if data['paused'] else '用户恢复'+label},event='user_'+target+'_control')
                    if data.get('paused') is False:
                        from browser.api import shared_browser_window__enabled as shared_enabled
                        if shared_enabled(config):
                            from cards.api import web_card_service__start as start
                            start(config)
                    from correction.api import card_correction_queue__status as correction_status
                    from review.api import card_review_queue__status as review_status
                    return self.reply(200,{'ok':True,('card_correction' if correction else 'card_review'):(correction_status(config) if correction else review_status(config))})
                if parsed.path=='/api/import-batch':
                    from reading.api import batch_import__match_pdf as match_pdf
                    from .upload_storage import prepare
                    folder=prepare(catalog,config,len(body))
                    from .upload_storage import write_upload
                    target=write_upload(folder,body);name=target.name
                    try:
                        papers=catalog.list()
                        digest=hashlib.sha256(body).hexdigest()
                        duplicate=next((p for p in papers if p['asset_hash']==digest and p['asset_path'] and Path(p['asset_path']).is_file()),None)
                        if duplicate:
                            target.unlink(missing_ok=True)
                            return self.reply(200,{'matched':True,'title':duplicate['title'],'reason':'相同 PDF 已归档，无需重复导入','duplicate':True})
                        pid,reason=match_pdf(target,papers)
                    except Exception:
                        target.unlink(missing_ok=True);raise
                    if pid:
                        jid=catalog.enqueue('import',pid,{'source':str(target),'manual':False})
                        return self.reply(200,{'matched':True,'title':catalog.get(pid)['title'],'job_id':jid,'reason':reason})
                    return self.reply(200,{'matched':False,'upload_id':name,'reason':reason})
                if parsed.path=='/api/import':
                    pid=urllib.parse.parse_qs(parsed.query)['id'][0];catalog.get(pid)
                    from .upload_storage import prepare
                    folder=prepare(catalog,config,len(body))
                    from .upload_storage import write_upload
                    target=write_upload(folder,body)
                    try:
                        validate_pdf(target)
                    except Exception:
                        target.unlink(missing_ok=True);raise
                    jid=catalog.enqueue('import',pid,{'source':str(target),'manual':True})
                    return self.reply(200,{'job_id':jid})
                data=json.loads(body)
                if parsed.path=='/api/reveal-local':
                    if not isinstance(data,dict) or set(data)!={'id'} or not isinstance(data['id'],str):
                        raise ValueError('文献标识不正确')
                    paper=catalog.get(data['id'])
                    local_path=paper.get('asset_path') or paper.get('card_path')
                    if not local_path or not Path(local_path).is_file():
                        return self.reply(404,{'error':'本机文件不存在'})
                    if sys.platform!='darwin':
                        return self.reply(400,{'error':'此功能需要在Mac上运行工作台'})
                    subprocess.run(['/usr/bin/open','-R',str(Path(local_path).resolve())],check=True,timeout=10)
                    return self.reply(200,{'ok':True})
                if parsed.path=='/api/reading':
                    from reading.api import reading_library__update as update, reading_library__ReadingConflict as ReadingConflict
                    if not isinstance(data,dict) or not set(data)<={'id','is_read','note','note_version'}:raise ValueError('阅读记录字段不正确')
                    try:result=update(catalog,data['id'],{k:v for k,v in data.items() if k!='id'})
                    except ReadingConflict as exc:return self.reply(409,{'error':str(exc)})
                    return self.reply(200,result)
                if parsed.path=='/api/bind-upload':
                    name=data['upload_id']
                    if not isinstance(name,str) or not re.fullmatch(r'[0-9a-f]{32}\.pdf',name):
                        raise ValueError('上传标识不合法')
                    target=Path(config['catalog_path']).parent/'uploads'/name
                    catalog.get(data['id']);validate_pdf(target)
                    return self.reply(200,{'job_id':catalog.enqueue('import',data['id'],{'source':str(target),'manual':True})})
                if parsed.path=='/api/discover':
                    if data.get('seed_id'):
                        catalog.get(data['seed_id'])
                    jid=catalog.enqueue('discover',payload=data)
                    return self.reply(200,{'job_id':jid})
                if parsed.path=='/api/seed':
                    return self.reply(200,catalog.set_seed(data['id'],data['enabled']))
                if parsed.path=='/api/decision':
                    catalog.decide(data['id'],data['decision'])
                    if data['decision'] in {'deep_read','original_read'} and not config.get('web_cards',{}).get('enabled'):
                        catalog.enqueue('deep_read',data['id'])
                    return self.reply(200,{'ok':True})
                if parsed.path=='/api/retry':
                    catalog.retry(data['job_id']);return self.reply(200,{'ok':True})
                if parsed.path=='/api/screen':
                    return self.reply(200,{'job_id':catalog.enqueue('screen',data['id'])})
                if parsed.path=='/api/model-schedule':
                    from core.api import model_schedule__configure as configure
                    mode=data.get('mode')
                    if mode=='window':
                        if not isinstance(data.get('start'),str) or not isinstance(data.get('end'),str):raise ValueError('请同时设置开始与结束时间')
                        result=configure(config,start=data['start'],end=data['end'])
                    elif mode=='all_day':result=configure(config,start='00:00',end='24:00')
                    elif mode=='allow':
                        if type(data.get('minutes')) is not int:raise ValueError('请设置临时放行分钟数')
                        result=configure(config,allow_minutes=data['minutes'])
                    elif mode=='reset':result=configure(config,reset=True)
                    else:raise ValueError('未知模型时段操作')
                    return self.reply(200,result)
                if parsed.path=='/api/scope':
                    if type(data.get('in_scope')) is not bool:raise ValueError('领域确认必须为布尔值')
                    paper=catalog.get(data['id'])
                    from fetch.api import preprints__RELEVANCE_POLICY as RELEVANCE_POLICY
                    catalog.upsert({**paper['metadata'],'out_of_scope':not data['in_scope'],'scope_manual_override':True,'scope_classification_source':'human','scope_policy':RELEVANCE_POLICY})
                    catalog.event(paper['id'],'human_scope_decision',{'in_scope':data['in_scope']})
                    return self.reply(200,{'ok':True})
                if parsed.path=='/api/acquire':
                    return self.reply(200,{'job_id':catalog.enqueue('acquire',data['id'],{'manual_retry':True,'trigger':'explicit_workbench_retry'})})
                self.reply(404,{'error':'未找到'})
            except (ValueError,KeyError) as exc:
                self.reply(400,{'error':str(exc)})
            except (OSError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as exc:
                traceback.print_exc()
                self.reply(503,{'error':'服务暂不可用：'+str(exc)})
            except Exception:
                traceback.print_exc()
                self.reply(500,{'error':'请求处理失败，请查看服务日志'})

    return WorkbenchHTTPServer(('127.0.0.1',port),Handler)
