"""Manage detached screening/card supervision without touching the fetch owner."""
import json
from core.api import paths__WorkspacePath as Path
import subprocess
import sys
import threading
import time
from core.api import catalog__ROOT as ROOT
from core.api import model_schedule__status as model_status
from core.api import runtime__alive as alive, runtime__attached_read_status as attached_read_status, runtime__runtime_status as runtime_status


def status(config):
    folder=Path(config['catalog_path']).parent
    try:owner=json.loads((folder/'read-runtime.json').read_text())
    except (OSError,ValueError):owner={}
    running=owner.get('state')=='running' and owner.get('mode')=='read_only' and time.time()-owner.get('updated',0)<15 and alive(owner.get('pid',0))
    lanes={lane:value for lane in ('screen','read') if (value:=attached_read_status(folder,lane))}
    return {'state':'running' if running else 'stopped','pid':owner.get('pid') if running else None,
            'model_schedule':model_status(config),'lanes':lanes}


def start(config,config_path=None):
    schedule=model_status(config)
    if schedule['mode'] in ('paused','disabled','invalid'):
        return {'state':'paused','pid':None,'reason':schedule['reason'],'model_schedule':schedule}
    folder=Path(config['catalog_path']).parent
    from core.api import catalog__Catalog as Catalog
    with Catalog(config['catalog_path']).connect() as db:
        table=db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_deployment'").fetchone()
        pending=db.execute("SELECT 1 FROM workflow_deployment WHERE key='audit1246' AND state='switching_reader'").fetchone() if table else None
    if pending:return {'state':'waiting_workflow','pid':None,'reason':'审计整改正在切换阅读流程；原任务保留'}
    existing=status(config)
    if existing['state']=='running':return {**existing,'reused':True}
    runtime=runtime_status(folder)
    if runtime.get('state')=='running' and runtime.get('mode')=='all':
        return {'state':'running','reused':True,'owner':'workbench','lanes':runtime['lanes'],'model_schedule':model_status(config)}
    if existing['lanes']:raise RuntimeError('已有阅读 worker，请复用它或先正常停止')
    (folder/'logs').mkdir(parents=True,exist_ok=True)
    args=[sys.executable,'-m','core.runtime','--read-only']
    if config_path:args+=['--config',str(Path(config_path).resolve())]
    from .log_output import spawn_logged
    process=spawn_logged(args,folder/'logs/reading-supervisor.log',cwd=ROOT,stdin=subprocess.DEVNULL,start_new_session=True)
    threading.Thread(target=process.wait,daemon=True,name='reading-supervisor-reaper').start()
    for _ in range(100):
        if process.poll() is not None:raise RuntimeError('阅读监督启动失败，请查看 reading-supervisor.log')
        existing=status(config)
        if existing['state']=='running' and len(existing['lanes'])==2:return existing
        time.sleep(.1)
    raise RuntimeError('阅读通道尚未确认启动，请查看 reading-status 与日志，勿重复启动')


def request_stop(config):
    from core.api import services__atomic_json as atomic_json
    folder=Path(config['catalog_path']).parent
    existing=status(config)
    if existing['state']!='running':return existing
    owner=json.loads((folder/'read-runtime.json').read_text())
    atomic_json(folder/'read-runtime-stop.json',{'pid':owner['pid'],'token':owner['token']})
    return {'state':'stop_requested','pid':owner['pid']}
