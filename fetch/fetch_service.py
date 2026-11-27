"""Detached Python keeper for the fetch supervisor, independent of the web UI."""
import argparse
import fcntl
import json
import os
from core.api import paths__WorkspacePath as Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from core.api import catalog__ROOT as ROOT, catalog__load_config as load_config, catalog__Catalog as Catalog
from core.api import runtime__alive as alive, runtime__runtime_status as runtime_status
from core.api import services__atomic_json as atomic_json


def paused(config):
    """Persist the user's fetch pause across UI and keeper restarts."""
    from core.api import control__pause_decision as pause_decision
    return not pause_decision(config,'fetch').allowed


def _keeper_paused(config):
    """A seed focus gate drains fetch work, but retains its original idle keeper."""
    from core.api import control__pause_decision as pause_decision
    decision=pause_decision(config,'fetch')
    return not decision.allowed and decision.source!=str(Path(config['catalog_path']).parent/'seed-focus-control.json')


def status(config):
    folder=Path(config['catalog_path']).parent
    if paused(config):return {'state':'paused_by_user','paused_by_user':True,'message':'用户已暂停拉取，打开工作台不会恢复'}
    try:owner=json.loads((folder/'fetch-service.json').read_text())
    except (OSError,ValueError):return {'state':'stopped'}
    running=owner.get('state')=='running' and alive(owner['pid']) and time.time()-owner.get('updated',0)<30
    catalog=Catalog(config['catalog_path'])
    with catalog.connect() as db:
        counts=db.execute('SELECT count(*) papers,sum(asset_path IS NOT NULL) assets FROM papers').fetchone()
        pending=[dict(r) for r in db.execute('SELECT state,count(*) count FROM discovery_pending GROUP BY state')]
    from core.api import storage_health__status as storage_status
    return {'state':'running' if running else 'stopped','pid':owner['pid'],'updated':owner.get('updated'),
            'runtime':runtime_status(folder),'storage':storage_status(config),'papers':counts['papers'],'assets':counts['assets'],'pending':pending,
            'log':str(folder/'logs/fetch-service.log')}


def start(config,config_path=None):
    if paused(config):raise RuntimeError('用户已暂停拉取')
    folder=Path(config['catalog_path']).parent;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'fetch-service-start.lock').open('a') as launch_lock:
        deadline=time.monotonic()+12
        while True:
            try:
                fcntl.flock(launch_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:
                    raise RuntimeError('拉取启动正在核对，请查看 fetch-status，勿重复启动')
                time.sleep(.1)
        return _start_locked(config,config_path)


def _start_locked(config,config_path=None):
    if paused(config):raise RuntimeError('用户已暂停拉取；打开工作台不会恢复，需明确恢复拉取后再启动')
    folder=Path(config['catalog_path']).parent;folder.mkdir(parents=True,exist_ok=True)
    current=status(config)
    if current['state']=='running':return {**current,'reused':True}
    # Respect an existing UI supervisor; never launch a second fetch owner.
    with (folder/'runtime.lock').open('a') as fd:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('当前已有工作台后台或单 worker；先正常关闭该后台，再执行 fetch-start') from None
    (folder/'logs').mkdir(exist_ok=True)
    path=Path(config_path or ROOT/'config/first_round.json').resolve()
    with (folder/'logs/fetch-service.log').open('a') as log:
        process=subprocess.Popen([sys.executable,'-m','fetch.fetch_service','--config',str(path)],cwd=ROOT,
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    # Reap it if this caller stays alive; it remains detached when the CLI exits.
    threading.Thread(target=process.wait,daemon=True,name='fetch-service-reaper').start()
    for _ in range(100):
        if process.poll() is not None:raise RuntimeError('拉取服务启动失败，请查看 '+str(folder/'logs/fetch-service.log'))
        current=status(config)
        if current['state']=='running':return current
        time.sleep(.1)
    raise RuntimeError('拉取服务尚未确认启动，请查看 fetch-status 和日志，勿重复启动')


def request_stop(config):
    folder=Path(config['catalog_path']).parent
    try:owner=json.loads((folder/'fetch-service.json').read_text())
    except (OSError,ValueError):return {'state':'stopped'}
    atomic_json(folder/'fetch-service-stop.json',{'pid':owner['pid'],'token':owner['token']})
    return {'state':'stop_requested','pid':owner['pid'],'message':'将在停止当前子任务后退出，未完成队列仍保留'}


def run(config_path):
    config=load_config(config_path);folder=Path(config['catalog_path']).parent
    if _keeper_paused(config):return
    logs=folder/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (folder/'fetch-service.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        token=secrets.token_hex(32);process=None;stopping=False;restart_at=0;failures=0;started=0
        keeper=None
        if config.get('fetch_pipeline',{}).get('prevent_idle_sleep') and Path('/usr/bin/caffeinate').is_file():
            keeper=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def stop(*_):
            nonlocal stopping
            stopping=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:
            while not stopping and not _keeper_paused(config):
                try:request=json.loads((folder/'fetch-service-stop.json').read_text())
                except (OSError,ValueError):request={}
                if request.get('pid')==os.getpid() and request.get('token')==token:break
                if process and process.poll() is not None:
                    failures=1 if time.time()-started>60 else failures+1
                    restart_at=time.time()+min(300,5*2**min(failures,6));process=None
                if process is None and time.time()>=restart_at and not paused(config):
                    with (logs/'fetch-supervisor.log').open('a') as log:
                        process=subprocess.Popen([sys.executable,'-m','core.runtime','--config',str(config_path),
                                                  '--parent',str(os.getpid()),'--fetch-only'],cwd=ROOT,
                                                 stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                    started=time.time()
                atomic_json(folder/'fetch-service.json',{'pid':os.getpid(),'token':token,'updated':time.time(),'state':'running',
                              'supervisor_pid':process.pid if process else None,'config_path':str(config_path)})
                time.sleep(2)
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            if keeper and keeper.poll() is None:keeper.terminate();keeper.wait(timeout=5)
            atomic_json(folder/'fetch-service.json',{'pid':os.getpid(),'token':token,'updated':time.time(),'state':'stopped'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    run(Path(args.config).resolve())
