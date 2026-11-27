"""Python-only supervision and a queue-boundary handover for legacy workers."""
from __future__ import annotations
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
import threading
from .paths import WorkspacePath as Path
from .catalog import Catalog,ROOT,load_config,now
from .services import atomic_json


def alive(pid):
    if type(pid) is not int or pid<=0:return False
    try:
        os.kill(pid,0)
        if sys.platform=='darwin':
            import ctypes
            library=ctypes.CDLL('/usr/lib/libproc.dylib')
            data=ctypes.create_string_buffer(512)
            count=library.proc_pidinfo(int(pid),3,0,data,len(data))
            if count>=8:return int.from_bytes(data.raw[4:8],sys.byteorder)!=5
            return False
        if sys.platform.startswith('linux'):
            stat=Path('/proc')/str(pid)/'stat'
            return stat.read_text().rsplit(')',1)[1].strip().split()[0]!='Z'
        state=subprocess.run(['ps','-p',str(pid),'-o','stat='],text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL).stdout.strip()
        return bool(state) and not state.startswith('Z')
    except PermissionError:return True  # EPERM confirms existence, not signalability.
    except (OSError,ValueError,TypeError,OverflowError):return False


def queue_drained(catalog):
    with catalog.connect() as db:
        return not db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running') LIMIT 1").fetchone()


def watch_supervisor(fd):
    """EOF is a kernel-backed lease loss, including a supervisor killed by SIGKILL."""
    os.set_inheritable(fd,False)
    cancelled=threading.Event()
    reason=['收到停止信号']
    def terminated(*_):
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        raise SystemExit(reason[0]+'，worker 停止')
    signal.signal(signal.SIGTERM,terminated)
    def watch():
        try:
            while os.read(fd,1):pass
            reason[0]='监督进程租约 EOF'
        except OSError as exc:
            reason[0]='监督进程租约读取失败：'+str(exc)
        if cancelled.is_set():return
        # Workers have their own process group, including active bridge children.
        if os.getpgrp()==os.getpid():os.killpg(os.getpid(),signal.SIGTERM)
        else:os.kill(os.getpid(),signal.SIGTERM)
        # Python signal handlers can wait behind a native SQLite busy wait.
        # Lease loss must stay bounded even when graceful cleanup is blocked.
        time.sleep(3)
        if os.getpgrp()==os.getpid():os.killpg(os.getpid(),signal.SIGKILL)
        else:os._exit(75)
    threading.Thread(target=watch,daemon=True,name='supervisor-lease').start()
    return cancelled


def stop_requested(folder,identity):
    try:
        request=json.loads((folder/'worker-stop.json').read_text())
        return request.get('pid')==identity['pid'] and request.get('token')==identity['token']
    except (OSError,ValueError):
        return False


def worker_identity(folder,pid,catalog_path):
    """A stale PID without a live mode lock cannot authorize a handover."""
    import fcntl
    try:
        identity=json.loads((folder/'worker-single-identity.json').read_text())
        if identity.get('pid')!=pid or identity.get('catalog_path')!=str(Path(catalog_path).resolve()) or not identity.get('token'):
            raise ValueError('身份记录不匹配')
        with Path(catalog_path).with_suffix('.worker.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return identity
        raise ValueError('旧 worker 已释放锁')
    except (OSError,ValueError) as exc:
        raise RuntimeError('旧 worker 缺少有效身份记录；请先正常停止旧版本，再启动工作台') from exc


def publish(folder,status):
    atomic_json(folder/'runtime.json',status,durable=False)


def runtime_status(folder):
    """The UI must not trust an old 'running' snapshot after a crash."""
    try:status=json.loads((Path(folder)/'runtime.json').read_text())
    except (OSError,ValueError):return {'state':'stopped','lanes':{}}
    if status.get('state')=='running' and (time.time()-status.get('updated',0)>15 or not status.get('pid') or not alive(status['pid'])):
        return {**status,'state':'stale','lanes':{},'error':'监督进程已停止或心跳过期，请重启工作台'}
    if status.get('state')=='running' and status.get('mode')=='fetch_only':
        for lane in ('screen','read'):
            read=attached_read_status(folder,lane)
            if read:status['lanes']={**status.get('lanes',{}),lane:read}
    return status


def attached_read_status(folder,lane='read'):
    """Read workers attached to a UI keep their own lane lock and pipe lease."""
    import fcntl
    try:
        if lane not in ('screen','read'):return None
        identity=json.loads((Path(folder)/('worker-'+lane+'-identity.json')).read_text())
        catalog=Path(identity['catalog_path'])
        if catalog.parent.resolve()!=Path(folder).resolve() or identity.get('lane')!=lane:return None
        with catalog.with_suffix('.'+lane+'.lock').open('r') as fd:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:pass
            else:return None
        heartbeat=json.loads((Path(folder)/('worker-'+lane+'.json')).read_text())
        if heartbeat.get('pid')!=identity['pid'] or not alive(identity['pid']):return None
        return {'pid':identity['pid'],'alive':True,'job':heartbeat.get('kind'),'job_id':heartbeat.get('job_id'),'state':heartbeat.get('state'),'owner':'attached_read'}
    except (OSError,ValueError,KeyError,TypeError):return None


def supervise(config_path=None,parent=None,fetch_only=False,read_only=False):
    config=load_config(config_path);catalog=Catalog(config['catalog_path'])
    from .model_schedule import status as model_status
    from fetch.api import fetch_service__paused as fetch_paused
    if fetch_only and fetch_paused(config):return
    if read_only and model_status(config)['mode'] in ('paused','disabled','invalid'):return
    folder=Path(config['catalog_path']).parent
    (folder/'logs').mkdir(parents=True,exist_ok=True)
    import fcntl
    if fetch_only and read_only:raise ValueError('只能选择一个监督通道')
    lock=(folder/('read-runtime.lock' if read_only else 'runtime.lock')).open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('已有后台监督进程或单 worker；请复用当前后台') from None
    children={};leases={};next_start={};failures={};started={};stopping=False;token=uuid.uuid4().hex
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def publish_snapshot(value):
        if read_only:atomic_json(folder/'read-runtime.json',value,durable=False)
        else:publish(folder,value)
    try:
        while not stopping and (not parent or alive(parent)):
            if read_only:
                try:request=json.loads((folder/'read-runtime-stop.json').read_text())
                except (OSError,ValueError):request={}
                if request.get('pid')==os.getpid() and request.get('token')==token:break
            for lane in (('screen','read') if read_only else ('fetch',) if fetch_only else ('fetch','screen','read')):
                if lane=='fetch' and fetch_paused(config):continue
                if lane in ('screen','read') and model_status(config)['mode'] in ('paused','disabled','invalid'):continue
                child=children.get(lane)
                if not child and not read_only and lane in ('screen','read') and attached_read_status(folder,lane):
                    continue
                if child and child.poll() is not None:
                    os.close(leases.pop(lane))
                    if time.time()-started.get(lane,0)>=60:failures[lane]=0
                    failures[lane]=failures.get(lane,0)+1
                    next_start[lane]=time.time()+min(300,5*2**min(6,failures[lane]))
                    catalog.event(None,'worker_exit',{'lane':lane,'returncode':child.returncode})
                    del children[lane];child=None
                if not child and time.time()>=next_start.get(lane,0):
                    args=[sys.executable,'-m','core.cli']
                    if config_path:args+=['--config',str(config_path)]
                    args+=['worker','--loop','--lane',lane]
                    read_fd,write_fd=os.pipe()
                    args+=['--supervisor-fd',str(read_fd)]
                    try:
                        with (folder/'logs'/('worker-'+lane+'.log')).open('a') as log:
                            children[lane]=subprocess.Popen(args,cwd=ROOT,stdout=log,stderr=log,start_new_session=True,pass_fds=(read_fd,))
                        leases[lane]=write_fd;started[lane]=time.time()
                    except BaseException:
                        os.close(write_fd);raise
                    finally:
                        os.close(read_fd)
            lanes={}
            for lane,child in children.items():
                heartbeat={}
                try:heartbeat=json.loads((folder/('worker-'+lane+'.json')).read_text())
                except (OSError,ValueError):pass
                lanes[lane]={'pid':child.pid,'alive':child.poll() is None,'job':heartbeat.get('kind'),'job_id':heartbeat.get('job_id'),'state':heartbeat.get('state')}
            if not read_only:
                for lane in ('screen','read'):
                    if lane not in lanes and (attached:=attached_read_status(folder,lane)):lanes[lane]=attached
            publish_snapshot({'pid':os.getpid(),'token':token,'updated':time.time(),'revision':config.get('runtime_revision','durable-v2'),'mode':'read_only' if read_only else 'fetch_only' if fetch_only else 'all','state':'running','lanes':lanes})
            time.sleep(2)
    finally:
        for fd in leases.values():os.close(fd)
        for child in children.values():
            if child.poll() is None:
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for child in children.values():
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=5)
        publish_snapshot({'pid':os.getpid(),'updated':time.time(),'state':'stopped','lanes':{}})
        lock.close()


def handover(legacy,parent,config_path=None):
    config=load_config(config_path);catalog=Catalog(config['catalog_path']);barrier=str(uuid.uuid4())
    folder=Path(config['catalog_path']).parent
    identity=worker_identity(folder,legacy,catalog.path) if alive(legacy) else None
    if identity:
        # Stop new claims; interrupted inference returns to its durable queue.
        atomic_json(folder/'worker-stop.json',identity)
    with catalog.connect() as db:
        db.execute("INSERT INTO jobs(id,kind,payload,state,created,updated) VALUES(?,?,?,'waiting_storage',?,?)",(barrier,'handover_barrier',json.dumps({'revision':config.get('runtime_revision','fetch-v3')}),now(),now()))
    atomic_json(folder/'handover.json',{'state':'waiting_for_current_queue','legacy_pid':legacy,'parent_pid':parent,'barrier':barrier,'updated':time.time()})
    publish(folder,{'state':'waiting_for_current_queue','updated':time.time(),'lanes':{}})
    try:
        while alive(parent) and alive(legacy):
            publish(folder,{'state':'waiting_for_current_queue','updated':time.time(),'lanes':{}})
            time.sleep(2)
        if not alive(parent):return
        catalog.finish(barrier,'done')
        atomic_json(folder/'handover.json',{'state':'activated','updated':time.time(),'revision':config.get('runtime_revision','fetch-v3')})
        catalog.event(None,'runtime_handover',{'revision':config.get('runtime_revision','fetch-v3'),'interrupted_jobs':0})
        supervise(config_path,parent)
    finally:
        if identity and stop_requested(folder,identity):
            (folder/'worker-stop.json').unlink(missing_ok=True)
        with catalog.connect() as db:
            db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state='waiting_storage'",(now(),barrier))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config');parser.add_argument('--parent',type=int);parser.add_argument('--legacy',type=int)
    parser.add_argument('--fetch-only',action='store_true')
    parser.add_argument('--read-only',action='store_true')
    args=parser.parse_args()
    if args.legacy:handover(args.legacy,args.parent,args.config)
    else:supervise(args.config,args.parent,args.fetch_only,args.read_only)
