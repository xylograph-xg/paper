"""Launch the reading UI in its own session; never starts workflow workers."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from core.api import paths__WorkspacePath as Path
from core.api import catalog__ROOT as ROOT, catalog__load_config as load_config
from core.api import runtime__alive as alive


def access(config,port):
    path=Path(config['catalog_path']).parent/'workbench-access.json'
    if not path.exists():return {}
    try:record=json.loads(path.read_text())
    except (OSError,ValueError) as exc:raise RuntimeError('工作台访问记录不可读，保留原服务等待核对。') from exc
    if not isinstance(record,dict):raise RuntimeError('工作台访问记录格式不正确。')
    if record.get('port')!=port:return {}
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',str(record.get('token',''))):
        raise RuntimeError('工作台访问口令记录不正确。')
    return record


def probe(config,port):
    record=access(config,port)
    if not record or not alive(record.get('pid')):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url=f'http://127.0.0.1:{port}'
    request=urllib.request.Request(url+'/api/workbench-health',headers={'X-Paper-Token':record['token']})
    try:
        with opener.open(request,timeout=2) as response:health=json.load(response)
        if isinstance(health,dict) and health.get('service')=='paper-workbench' and health.get('pid')==record['pid'] and health.get('port')==port:
            return {**record,'background':health.get('background') is True}
    except urllib.error.HTTPError as exc:
        if exc.code==404:
            with opener.open(url,timeout=2) as response:body=response.read(4096)
            if b'<title>'+ '文献阅读工作台'.encode()+b'</title>' in body:
                return {**record,'background':False}
        elif exc.code==503:
            raise RuntimeError('现有工作台正忙，未重复启动；请稍后再打开启动器。') from exc
    except (OSError,ValueError):pass
    return None


def announce(record,port,open_browser):
    suffix='/' if record.get('passwordless') else '/#access='+record['token']
    local=f'http://127.0.0.1:{port}'+suffix
    print('文献工作台：'+local,flush=True)
    if record.get('remote_url'):print('远程查阅链接：'+record['remote_url']+suffix,flush=True)
    print('网页服务已在独立后台运行，现在可以关闭此终端。' if record.get('background') else
          '检测到旧前台网页服务；请保留原服务终端，本次启动器可关闭。',flush=True)
    if open_browser:webbrowser.open(local)


def start(config,port=8767,open_browser=True,timeout=35):
    if type(port) is not int or not 1<=port<=65535:raise ValueError('工作台端口必须为 1–65535。')
    folder=Path(config['catalog_path']).parent;folder.mkdir(parents=True,exist_ok=True)
    with (folder/f'workbench-start-{port}.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        existing=probe(config,port)
        if existing:
            announce(existing,port,open_browser);return existing
        logs=folder/'logs';logs.mkdir(exist_ok=True)
        log_path=logs/'workbench-service.log'
        args=[sys.executable,'-u','-m','workbench.workbench_service','--run','--config',config['_config_path'],'--port',str(port)]
        print('正在启动后台文献工作台…',flush=True)
        from reading.api import log_output__spawn_logged as spawn_logged
        process=spawn_logged(args,log_path,cwd=ROOT,stdin=subprocess.DEVNULL,start_new_session=True,close_fds=True)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError(f'工作台启动失败，详情见 {log_path}。')
            ready=probe(config,port)
            if ready and ready.get('background'):
                announce(ready,port,open_browser);return ready
            time.sleep(.2)
        raise RuntimeError(f'后台工作台尚未就绪，未重复启动；详情见 {log_path}。')


def run(config,port):
    folder=Path(config['catalog_path']).parent;folder.mkdir(parents=True,exist_ok=True)
    with (folder/f'workbench-server-{port}.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('已有后台工作台运行，拒绝重复启动。') from None
        previous=access(config,port)
        signal.signal(signal.SIGHUP,signal.SIG_IGN)
        def stop(*_):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop)
        from .web import serve
        serve(config,config['_config_path'],port,False,background=True,access_token=previous.get('token'))


def main():
    parser=argparse.ArgumentParser(description='启动独立后台文献工作台，启动器退出后仍可远程查阅。')
    parser.add_argument('--config');parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--no-browser',action='store_true');parser.add_argument('--run',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();config=load_config(args.config)
    try:
        if args.run:run(config,args.port)
        else:start(config,args.port,not args.no_browser)
    except KeyboardInterrupt:pass
    except (OSError,ValueError,RuntimeError) as exc:
        print(str(exc),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
