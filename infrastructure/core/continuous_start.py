"""Explicit main-project controls for fetch, cards, verification and correction.

The three web workflows share the existing owner and watcher. ``all`` retains
its historical fetch/cards meaning and does not resume verification/correction.
"""
import argparse
import json
import os
import subprocess
import time
from .paths import WorkspacePath as Path
from .catalog import ROOT,load_config,now
from .control import mutate_record,read_record


def scope(target):
    web_labels=('local.paper.web-cards','local.paper.web-tab-watch')
    web_owners=('web-card-service.json','web-tab-check.json')
    groups={
        'fetch':(('fetch-control.json',),('local.paper.fetch',),('fetch-service.json',)),
        'cards':(('web-card-control.json',),web_labels,web_owners),
        'review':(('card-review-control.json',),web_labels,web_owners),
        'correction':(('card-correction-control.json',),web_labels,web_owners),
    }
    if target in groups:return groups[target]
    if target=='all':return tuple(groups['fetch'][i]+groups['cards'][i] for i in range(3))
    raise ValueError('未知任务类别')


def _main_data(config):
    data=Path(config['catalog_path']).parent
    if data.resolve()!=(ROOT/'data').resolve():raise ValueError('一键入口只控制主目录，历史隔离任务不恢复')
    return data


def start(config,open_browser=False,target="all"):
    data=_main_data(config)
    controls,labels,owners=scope(target)
    if target in ('review','correction'):
        from browser.api import shared_browser_window__enabled as shared_enabled
        section='card_review' if target=='review' else 'card_correction'
        if not shared_enabled(config) or config.get(section,{}).get('enabled') is not True:
            raise ValueError('核验与修正需要启用共享专用窗口及对应任务')
    for name in controls:
        path=data/name
        mutate_record(path,{'paused_by_user':False,'reason':'用户启动任务：'+target,'updated_at':now()},event='user_resume')
    if target in ('all','cards'):
        mutate_record(data/'web-tab-watch-control.json',{'paused_by_user':False,'reason':'用户启动制卡页面维护','updated_at':now()},event='user_resume')
    if target!='fetch':
        path=data/'web-provider-selection.json'
        # Starting a service preserves a valid existing channel decision.
        if not path.exists() and target in ('all','cards'):
            mutate_record(path,{'provider':'chatgpt','allowed_providers':['chatgpt'],'reuse_qwen_window':False,
                               'deepseek_paused_by_user':True,'state':'ready','reason':'当前GPT唯一通道规则','updated_at':now()},event='initialize_provider')
        elif path.exists():read_record(path)
    results={}
    from browser.api import shared_browser_window__enabled as shared_enabled
    shared_browser=target!='fetch' and shared_enabled(config)
    if shared_browser:
        from browser.api import browser_start_request__request as request_browser
        requested=request_browser(config,target)
        from browser.api import web_pool_open__request_shared as request_shared
        pool=request_shared(config,ensure_page=True)
        if pool.get('state')=='needs_inspection' and not pool.get('maintenance_requested'):
            raise RuntimeError(pool['error'])
        results['browser']={'ok':True,'state':requested['state'],'owner_requested':True}
    domain=f'gui/{os.getuid()}'
    for label in labels:
        p=subprocess.run(['launchctl','kickstart',domain+'/'+label],capture_output=True,text=True)
        results[label]={'ok':p.returncode==0,'error':p.stderr.strip()}
    if any(not x['ok'] for x in results.values()):raise RuntimeError('常驻服务启动未确认：'+json.dumps(results,ensure_ascii=False))
    if not shared_browser and open_browser and target in ('all','cards'):
        p=subprocess.run(['/bin/zsh',str(ROOT/'article/open_gpt.command')],cwd=ROOT,capture_output=True,text=True,timeout=40)
        results['browser']={'ok':p.returncode==0,'message':p.stdout[-700:],'error':p.stderr[-300:]}
        if p.returncode:raise RuntimeError('GPT页面未就绪：'+p.stderr[-300:])
        subprocess.run([str(ROOT/'.venv-web-feedback/bin/python'),'-m','maintenance.web_tab_watch','check'],cwd=ROOT,capture_output=True,text=True,timeout=30)
    return results


def stop(config,target="all"):
    data=_main_data(config)
    controls,labels,owners=scope(target)
    for name in controls:
        path=data/name
        mutate_record(path,{'paused_by_user':True,'reason':'用户从左侧任务栏确认停止：'+target,'updated_at':now()},event='user_pause')
    from fetch.api import fetch_service__request_stop as request_stop
    from cards.api import web_card_service__owner_enabled as owner_enabled, web_card_service__stop as stop_cards
    result={}
    if target in ('all','fetch'):result['fetch']=request_stop(config)
    if target in ('all','cards'):result['web_cards']=stop_cards(config)
    if target in ('review','correction'):result[target]={'state':'paused_by_user'}
    if target!='fetch':
        if owner_enabled(config):
            # The stopped workflow has relinquished only its idle capacity. Do
            # not signal or await the shared driver while another lane runs.
            labels=tuple(label for label in labels if label=='local.paper.fetch')
            owners=tuple(name for name in owners if name=='fetch-service.json')
            key='web_cards' if target in ('all','cards') else target
            result[key]={**result[key],'state':'paused_by_user','shared_owner_kept':True}
        else:
            mutate_record(data/'web-tab-watch-control.json',{'paused_by_user':True,
                'reason':'全部网页任务已暂停','updated_at':now()},event='user_pause')
            if target in ('review','correction'):
                # The shared owner may have been started as a detached process,
                # rather than by launchd. Request that exact owner to exit
                # without calling stop_cards(), which would pause another lane.
                from cards.api import web_card_service__status as owner_status
                from .services import atomic_json
                owner=owner_status(config)
                if (owner.get('alive') is True and type(owner.get('pid')) is int and owner['pid']>0
                        and isinstance(owner.get('token'),str) and owner['token']):
                    atomic_json(data/'web-card-stop.json',{'pid':owner['pid'],'token':owner['token']})
                    result[target]['owner_stop_requested']=True
    domain=f'gui/{os.getuid()}'
    for label in labels:
        p=subprocess.run(['launchctl','kill','SIGTERM',domain+'/'+label],capture_output=True,text=True)
        result[label]={'signal_sent':p.returncode==0,'message':p.stderr.strip()}
    # Keep the sidebar control disabled until the old owners have exited.
    from .runtime import alive
    pids=[]
    for name in owners:
        try:pid=json.loads((data/name).read_text()).get('pid')
        except (OSError,ValueError):continue
        if type(pid) is int:pids.append(pid)
    deadline=time.monotonic()+25
    while any(alive(pid) for pid in pids) and time.monotonic()<deadline:time.sleep(.2)
    if any(alive(pid) for pid in pids):raise RuntimeError('已持久暂停，部分进程正在退出；请等待状态更新后再启动')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--open-browser',action='store_true');parser.add_argument('--stop',action='store_true');parser.add_argument('--target',choices=('all','fetch','cards','review','correction'),default='all');args=parser.parse_args()
    print(json.dumps(stop(load_config(),args.target) if args.stop else start(load_config(),args.open_browser,args.target),ensure_ascii=False,indent=2))
