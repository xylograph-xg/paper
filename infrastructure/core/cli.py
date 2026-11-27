from __future__ import annotations
import argparse
import fcntl
import json
import os
import sys
import time
import traceback
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from .paths import WorkspacePath as Path

from .catalog import Catalog, load_config
from . import services


@contextmanager
def worker_locks(path,lane=None):
    """Lane workers share a mode guard; a single worker owns it exclusively."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        locks=[]
        if not lane:
            locks.append((path.parent/'runtime.lock',fcntl.LOCK_EX))
        locks.append((path.with_suffix('.worker.lock'),fcntl.LOCK_SH if lane else fcntl.LOCK_EX))
        if lane:
            locks.append((path.with_suffix('.'+lane+'.lock'),fcntl.LOCK_EX))
        for name,mode in locks:
            fd=stack.enter_context(name.open('a'))
            try:fcntl.flock(fd,mode|fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('已有互斥 worker 或监督进程运行，拒绝重复启动') from None
        yield


def work(config,loop=False,lane=None,supervisor_fd=None):
    from fetch.api import fetch_service__paused as fetch_paused
    if lane in (None,'fetch') and fetch_paused(config):return
    from .runtime import watch_supervisor, stop_requested
    catalog=Catalog(config['catalog_path'])
    with worker_locks(catalog.path,lane):
        folder=catalog.path.parent
        identity_path=folder/('worker-'+(lane or 'single')+'-identity.json')
        identity={'pid':os.getpid(),'token':uuid.uuid4().hex,'catalog_path':str(catalog.path.resolve()),'lane':lane}
        services.atomic_json(identity_path,identity)
        lease_cancel=None
        # The pipe is inherited only by this worker, never by bridge subprocesses.
        try:
            if supervisor_fd is not None:
                lease_cancel=watch_supervisor(supervisor_fd)
            if lane=='fetch' and config.get('fetch_pipeline',{}).get('enabled'):
                from fetch.api import fetching__fetch_loop as fetch_loop
                fetch_loop(catalog,config,loop,lambda:stop_requested(folder,identity))
            else:
                _work(catalog,config,loop,lane,lambda:stop_requested(folder,identity))
        finally:
            if lease_cancel is not None:lease_cancel.set()
            identity_path.unlink(missing_ok=True)
            if lane:
                services.atomic_json(folder/('worker-'+lane+'.json'),{'pid':os.getpid(),'updated':time.time(),'state':'stopped','job_id':None,'kind':None})
            if supervisor_fd is not None:
                os.close(supervisor_fd)


def _work(catalog,config,loop,lane,should_stop):
    from .model_schedule import MODEL_KINDS, ModelWindowClosed, status as model_status
    kinds={'fetch':('discover','acquire','import'),'screen':('screen','auto_select'),'read':('deep_read',)}.get(lane)
    if lane in ('read','screen') and model_status(config)['mode'] in ('paused','disabled','invalid'):
        return
    catalog.recover(kinds)
    if lane in ('read','screen'):
        from reading.api import reading_recovery__activate as activate
        activate(catalog,config)
    last_schedule_check=0
    last_maintenance=0
    while True:
        stopping=should_stop()
        if loop and not stopping and lane in ('read','screen') and time.monotonic()-last_maintenance>=60:
            last_maintenance=time.monotonic()
            services.maintain_jobs(catalog,config,kinds=kinds,audit_assets=False)
            if lane=='screen':
                from maintenance.api import artifact_retention__maintain as maintain
                maintain(catalog,config=config)
        if loop and not stopping and lane not in ('read','screen') and (config.get('daily_schedule',{}).get('mode')=='on_completion' or time.monotonic()-last_schedule_check>=60):
            last_schedule_check=time.monotonic()
            try:
                if time.monotonic()-last_maintenance>=60:
                    last_maintenance=time.monotonic()
                    services.maintain_jobs(catalog,config)
                services.maybe_daily(catalog,config)
            except services.StorageUnavailable:
                pass
            except Exception as exc:
                print('每日检索登记失败：'+traceback.format_exc()[-4000:],file=sys.stderr,flush=True)
        window=model_status(config)
        eligible=kinds
        if not window['allowed']:
            eligible=tuple(kind for kind in (kinds or ('discover','acquire','import','acquire_fallback','screen','auto_select','deep_read')) if kind not in MODEL_KINDS and not (kind=='auto_select' and config.get('local_models_enabled',True) is False))
        job=None if stopping else catalog.claim(eligible)
        def heartbeat():
            if lane:
                current=model_status(config)
                services.atomic_json(Path(config['catalog_path']).parent/('worker-'+lane+'.json'),{'pid':os.getpid(),'updated':time.time(),'job_id':job['id'] if job else None,'kind':job['kind'] if job else None,'state':'working' if job else 'idle' if current['allowed'] or lane=='fetch' else 'waiting_schedule','model_schedule':current if lane!='fetch' else None},durable=False)
        heartbeat()
        if not job:
            if not loop or stopping:
                break
            time.sleep(2);continue
        state='done'
        try:
            kind=job['kind'];pid=job['paper_id'];payload=job['payload']
            if kind=='discover':
                services.discover(catalog,config,payload.get('seed_id'))
            elif kind in {'acquire','import','acquire_fallback'}:
                services.acquisition(catalog,config,pid,payload.get('source'),payload.get('manual',False),stage='fallback' if kind=='acquire_fallback' else 'all')
                if kind=='import' and catalog.get(pid)['acquisition']=='available':
                    catalog.enqueue('screen',pid)
            elif kind=='screen':
                from .model_job import run
                state=run(catalog,config,job,should_stop,heartbeat)
                catalog.enqueue('auto_select')
            elif kind=='auto_select':
                services.auto_select(catalog,config)
            elif kind=='deep_read':
                from .model_job import run
                state=run(catalog,config,job,should_stop,heartbeat)
            else:
                raise ValueError('未知任务类型')
            catalog.finish(job['id'],state)
        except ModelWindowClosed as exc:
            catalog.defer(job['id'],str(exc))
            catalog.event(pid,'model_job_paused',{'job_id':job['id'],'kind':kind,'reason':str(exc)})
        except services.StorageUnavailable as exc:
            catalog.finish(job['id'],'waiting_storage',str(exc))
        except Exception as exc:
            details=traceback.format_exc()[-4000:]
            catalog.finish(job['id'],'failed',details)
            print(f"{job['kind']}: {details}",file=sys.stderr,flush=True)


def main():
    parser=argparse.ArgumentParser(description='统一文献阅读流水线')
    parser.add_argument('--config',default=None)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('init')
    commands.add_parser('status')
    commands.add_parser('discover')
    commands.add_parser('daily')
    commands.add_parser('migrate')
    commands.add_parser('fetch-start')
    commands.add_parser('fetch-stop')
    commands.add_parser('fetch-status')
    repair=commands.add_parser('repair-reading');repair.add_argument('--dry-run',action='store_true')
    commands.add_parser('reading-contracts')
    commands.add_parser('reading-start');commands.add_parser('reading-stop');commands.add_parser('reading-status')
    schedule=commands.add_parser('model-schedule')
    schedule.add_argument('--start');schedule.add_argument('--end')
    schedule.add_argument('--allow-minutes',type=int);schedule.add_argument('--reset',action='store_true')
    schedule.add_argument('--all-day',action='store_true',help='持久设置全天候模型运行（保留用户暂停）')
    worker=commands.add_parser('worker');worker.add_argument('--loop',action='store_true');worker.add_argument('--lane',choices=['fetch','screen','read'])
    worker.add_argument('--supervisor-fd',type=int,help=argparse.SUPPRESS)
    server=commands.add_parser('serve');server.add_argument('--port',type=int,default=8767);server.add_argument('--no-browser',action='store_true')
    decision=commands.add_parser('select');decision.add_argument('paper_id');decision.add_argument('decision',choices=['keep','later','reject','deep_read','original_read'])
    remake=commands.add_parser('remake');remake.add_argument('paper_id');remake.add_argument('--force',action='store_true',help='显式重制已完成或已评审卡片，旧证据保存在 history')
    importer=commands.add_parser('import');importer.add_argument('paper_id');importer.add_argument('path')
    args=parser.parse_args()
    config=load_config(args.config);catalog=Catalog(config['catalog_path'])
    if args.command=='init':
        services.init_seeds(catalog,config)
        print(json.dumps({'papers':len(catalog.list()),'message':'种子已登记，原文导入已排队'},ensure_ascii=False))
    elif args.command in {'fetch-start','fetch-stop','fetch-status'}:
        from fetch.api import fetch_service__start as start, fetch_service__request_stop as request_stop, fetch_service__status as status
        result=start(config,args.config) if args.command=='fetch-start' else request_stop(config) if args.command=='fetch-stop' else status(config)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=='status':
        print(json.dumps({'papers':catalog.list(),'jobs':catalog.jobs()},ensure_ascii=False,indent=2))
    elif args.command=='repair-reading':
        from reading.api import reading_recovery__activate as activate, reading_recovery__READ_KINDS as READ_KINDS
        with worker_locks(catalog.path,'screen'),worker_locks(catalog.path,'read'):
            if not args.dry_run:catalog.recover(READ_KINDS)
            print(json.dumps(activate(catalog,config,args.dry_run),ensure_ascii=False,indent=2))
    elif args.command=='reading-contracts':
        from reading.api import reading_contract__inventory as inventory
        print(json.dumps(inventory(config['studio_library_root']),ensure_ascii=False,indent=2))
    elif args.command=='model-schedule':
        from .model_schedule import configure,status
        if args.all_day and (args.reset or args.start is not None or args.end is not None or args.allow_minutes is not None):
            raise ValueError('全天候不能与其他时段设置同时使用')
        if args.all_day:args.start,args.end='00:00','24:00'
        if args.reset and (args.start is not None or args.end is not None or args.allow_minutes is not None):
            raise ValueError('恢复默认不能与其他时段设置同时使用')
        result=configure(config,start=args.start,end=args.end,allow_minutes=args.allow_minutes,reset=args.reset) if args.reset or args.start is not None or args.end is not None or args.allow_minutes is not None else status(config)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command in ('reading-start','reading-stop','reading-status'):
        from reading.api import reading_service__start as start, reading_service__request_stop as request_stop, reading_service__status as status
        result=start(config,args.config) if args.command=='reading-start' else request_stop(config) if args.command=='reading-stop' else status(config)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=='discover':
        print(json.dumps({'job_id':catalog.enqueue('discover')},ensure_ascii=False))
    elif args.command=='daily':
        services.archive_root(config)
        print(json.dumps(catalog.enqueue_daily(datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()),ensure_ascii=False))
    elif args.command=='migrate':
        from maintenance.api import migration__migrate as migrate
        summary=migrate(catalog,config)
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        if summary.get('warnings'):raise SystemExit(2)
    elif args.command=='worker':
        work(config,args.loop,args.lane,args.supervisor_fd)
    elif args.command=='serve':
        from workbench.api import web__serve as serve
        serve(config,args.config,args.port,not args.no_browser)
    elif args.command=='remake':
        paper=catalog.get(args.paper_id)
        if paper['decision'] not in ('deep_read','original_read'):raise ValueError('请先人工选入精读库')
        print(json.dumps({'job_id':catalog.enqueue('deep_read',args.paper_id,{'force':args.force,'trigger':'manual_remake'})}))
    elif args.command=='select':
        catalog.decide(args.paper_id,args.decision)
        if args.decision in {'deep_read','original_read'}:
            catalog.enqueue('deep_read',args.paper_id)
    elif args.command=='import':
        source=Path(args.path).resolve()
        services.validate_pdf(source)
        print(json.dumps({'job_id':catalog.enqueue('import',args.paper_id,{'source':str(source),'manual':True})}))


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(traceback.format_exc()[-4000:],file=sys.stderr);sys.exit(1)
