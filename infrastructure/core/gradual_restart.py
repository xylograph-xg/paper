#!/usr/bin/env python3
"""Wait for the shared web owner to become idle, then restart it.

This is a drain-boundary restart, not a kill: active generations/uploads are
allowed to finish. The same registered launchd owner is then restarted so new
code/config is loaded without discarding accepted work.
"""
import argparse,json,os,subprocess,time
from pathlib import Path
from core.api import catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json


def _read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def _remaining(service, observer):
    total=0
    for key in ('workers','review_workers','correction_workers','uploading_pages'):
        value=service.get(key)
        if type(value) is int and value>0:total+=value
    generated=sum(1 for p in observer.get('pages',[]) if isinstance(p,dict) and p.get('state')=='generating')
    return max(total,generated)


def _busy(service, observer):
    for key in ('workers','review_workers','correction_workers','uploading_pages'):
        value=service.get(key)
        if type(value) is int and value>0:return True
    return any(p.get('state')=='generating' for p in observer.get('pages',[]) if isinstance(p,dict))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--timeout',type=float,default=1800)
    parser.add_argument('--config',default='infrastructure/config/first_round.json')
    args=parser.parse_args()
    config=load_config(args.config);root=Path(config['catalog_path']).parent
    status_path=root/'web-gradual-restart.json'
    started=time.time();stable=0;last={}
    target='gui/%s/local.paper.web-cards' % os.getuid()
    atomic_json(status_path,{'state':'waiting','started':started,'timeout':args.timeout,
                             'remaining':_remaining({},{}),
                             'message':'等待当前生成和上传结束，再重启 owner'})
    while time.time()-started<args.timeout:
        service=_read(root/'web-card-service.json');observer=_read(root/'web-page-observer.json')
        last={'pid':service.get('pid'),'state':service.get('state'),
              'workers':service.get('workers'),'review_workers':service.get('review_workers'),
              'correction_workers':service.get('correction_workers'),'uploading_pages':service.get('uploading_pages')}
        if _busy(service,observer):
            stable=0
            atomic_json(status_path,{'state':'waiting','started':started,'updated':time.time(),
                                     'remaining':_remaining(service,observer),
                                     'message':'等待当前生成和上传结束，再重启 owner','last':last})
            time.sleep(2);continue
        stable+=1
        if stable<2:
            time.sleep(2);continue
        atomic_json(status_path,{'state':'restarting','started':started,'updated':time.time(),
                                 'remaining':0,'message':'已空闲，正在重启 owner','last':last})
        proc=subprocess.run(['launchctl','kickstart','-k',target],capture_output=True,text=True)
        if proc.returncode:
            atomic_json(status_path,{'state':'failed','started':started,'updated':time.time(),
                                     'message':'重启失败：'+(proc.stderr or proc.stdout)[:500],'last':last})
            return 2
        time.sleep(8);service=_read(root/'web-card-service.json')
        atomic_json(status_path,{'state':'restarted','started':started,'updated':time.time(),
                                 'message':'已渐进重启，等待新 owner 就绪','pid':service.get('pid'),
                                 'owner_state':service.get('state'),'last':last})
        return 0
    atomic_json(status_path,{'state':'timeout','started':started,'updated':time.time(),
                             'message':'等待超时，未重启；活动任务保留','last':last})
    return 3


if __name__=='__main__':
    raise SystemExit(main())
