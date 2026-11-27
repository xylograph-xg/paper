"""Periodic dedicated-browser counts and cleanup of archived owned tabs."""
import json
import os
import signal
import sys
import time
import urllib.request
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit
from core.api import catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json

HOSTS={'chatgpt':{'chatgpt.com'},'qwen':{'chat.qwen.ai','www.qianwen.com','qianwen.com'},'deepseek':{'chat.deepseek.com'}}


def _local_targets(endpoint):
    """Loopback CDP metadata must not traverse the fluctuating system proxy."""
    url=urlsplit(endpoint)
    if (url.scheme not in ('http','https') or url.hostname not in ('localhost','127.0.0.1','::1')
            or not url.port or url.username or url.password or url.path not in ('','/')
            or url.query or url.fragment):
        raise ValueError('专用CDP必须为本机端口，不接受认证、路径或查询')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint.rstrip('/')+'/json/list',timeout=5) as stream:return json.load(stream)


def counts(targets):
    return {provider:sum(t.get('type')=='page' and urlsplit(t.get('url','')).hostname in hosts for t in targets)
            for provider,hosts in HOSTS.items()}


def cleanup_candidate(attempt,folder):
    if attempt.get('reused_window'):return False
    if not attempt.get('target_id') or attempt.get('tab_cleanup') in ('closed_error_page','closed_saved_response','closed_by_watch','already_closed','preserved_verification','preserved_reusable_window'):return False
    if attempt.get('state')=='response_saved':
        from cards.api import web_card_inputs__digest as digest
        raw=folder/'response-raw.txt'
        return raw.is_file() and bool(attempt.get('raw_sha256')) and digest(raw)==attempt['raw_sha256']
    return attempt.get('state') in ('not_sent','needs_inspection') and bool(attempt.get('error')) and bool(attempt.get('finished'))


def check_shared(config):
    """Read HTTP target metadata; the resident owner performs all CDP operations."""
    from browser.api import web_pool_open__shared_window_record as shared_window_record, web_pool_open__shared_maintenance_request as shared_maintenance_request
    folder=Path(config['catalog_path']).parent
    report={'pid':os.getpid(),'updated':time.time(),'interval_seconds':60,
            'counts':{provider:0 for provider in HOSTS},'total_pages':0,
            'browser_total_pages':0,'other_pages':0,'closed':[],'errors':[],
            'shared_window':True,'slot_count':20,
            'browser_recovery':{'state':'owner_managed','pool_maintenance':{'state':'owner_managed'}}}
    record=None
    try:record,fingerprint=shared_window_record(config)
    except (OSError,ValueError,TypeError) as exc:
        report['state']='needs_inspection';report['errors'].append('共享窗口登记需要核对：'+str(exc)[:300])
    try:
        endpoint=os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222')
        if urlsplit(endpoint).hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('专用CDP必须为本机')
        targets=_local_targets(endpoint)
        if not isinstance(targets,list) or any(not isinstance(t,dict) for t in targets):raise ValueError('浏览器页面元数据格式错误')
        browser_pages=[t for t in targets if t.get('type')=='page']
        report['browser_total_pages']=len(browser_pages)
        if record is not None:
            owned={s['target_id'] for s in record['slots'] if s.get('target_id')}
            pool_pages=[t for t in browser_pages if t.get('id') in owned]
            report.update(window_id=record['window_id'],total_pages=len(pool_pages),
                          counts=counts(pool_pages),missing_targets=sorted(owned-{t.get('id') for t in pool_pages}),
                          unbound_slots=20-len(owned),state='observed')
            shared_maintenance_request(config,'web_tab_watch',record,fingerprint)
            report['maintenance_requested']=True
        report['other_pages']=report['browser_total_pages']-report['total_pages']
    except Exception as exc:
        report['state']='needs_inspection';report['errors'].append(type(exc).__name__+': '+str(exc)[:400])
    report['over_limit']=['共享窗口固定页池'] if report['total_pages']>20 else []
    atomic_json(folder/'web-tab-check.json',report)
    from core.api import action_inbox__publish as publish
    publish(config)
    return report


def check(config):
    from core.api import concurrency_control__apply as apply_concurrency
    apply_concurrency(config)
    folder=Path(config['catalog_path']).parent
    from browser.api import web_pool_open__shared_mode as shared_mode
    if shared_mode(config):return check_shared(config)
    # Refill independently of slow uploads in the card keeper's submission loop.
    try:
        from core.api import control__pause_decision as pause_decision
        if config.get('web_cards',{}).get('refill_min_pending') and pause_decision(config,'web_cards').allowed:
            from core.api import catalog__Catalog as Catalog
            from cards.api import web_card_queue__select as select
            from browser.api import shared_page_backlog__enabled as backlog_enabled
            selection_config={**config,'web_cards':{**config['web_cards'],'refill_min_pending':0}} if backlog_enabled(config) else config
            select(Catalog(config['catalog_path']),selection_config)
    except Exception as exc:print('card stock refill:',type(exc).__name__,str(exc)[:200],flush=True)
    # Local disk housekeeping is independent of browser/network availability.
    try:
        stamp=folder/'web-artifact-retention.json'
        if not stamp.exists() or time.time()-stamp.stat().st_mtime>600:
            from .web_artifact_retention import compact_completed
            compact_completed(config)
            from reading.api import card_display__maintain as maintain
            maintain(config)
    except Exception as exc:
        print('artifact retention:', type(exc).__name__, str(exc)[:200], flush=True)
    from browser.api import web_pool_open__shared_mode as shared_mode
    if shared_mode(config):return check_shared(config)
    try:
        from browser.api import browser_recovery__check_health as check_health
        recovery=check_health(config)
        from browser.api import browser_recovery__maintain_pool as maintain_pool
        recovery['pool_maintenance']=maintain_pool(config)
    except Exception as exc:recovery={'state':'needs_inspection','error':str(exc)[:300]}
    endpoints={provider:os.environ.get({'qwen':'WEB_QWEN_CDP_URL','deepseek':'WEB_DEEPSEEK_CDP_URL'}.get(provider,'WEB_GPT_CDP_URL'),os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222')) for provider in HOSTS}
    report={'pid':os.getpid(),'updated':time.time(),'interval_seconds':60,'counts':{},'total_pages':0,'closed':[],'errors':[],'browser_recovery':recovery}
    for endpoint in set(endpoints.values()):
        try:
            if urlsplit(endpoint).hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('专用CDP必须为本机')
            targets=_local_targets(endpoint)
            report['total_pages']+=sum(t.get('type')=='page' for t in targets)
            found=counts(targets)
            for provider in HOSTS:
                if endpoints[provider]==endpoint:report['counts'][provider]=found[provider]
            eligible=[]
            for path in (folder/'web_cards').glob('*/*/attempt.json'):
                if path.parent.name not in HOSTS or endpoints[path.parent.name]!=endpoint:continue
                attempt=json.loads(path.read_text())
                if cleanup_candidate(attempt,path.parent):eligible.append((path,attempt))
            if eligible:
                sys.path.insert(0,os.environ.get('WEB_GPT_IMPORT_ROOT','/Users/xiaoyanhao/project/chatgpt_playwright'))
                from playwright.sync_api import sync_playwright
                from web_gpt.submission import submission_lock
                from web_gpt.core import ANSWER,STOP_BUTTON,_message_text
                from web_gpt.qwen import ANSWER as QA,STOP as QS,message_text
                with sync_playwright() as p:
                    browser=p.chromium.connect_over_cdp(endpoint,timeout=10000,no_defaults=True)
                    with submission_lock(timeout=10):
                        from browser.api import browser_inventory__enumerate_pages as enumerate_pages
                        inventory=enumerate_pages(browser);pages=inventory['pages']
                        report['errors'].extend(inventory['errors'])
                        for path,attempt in eligible:
                            current=json.loads(path.read_text())
                            if not cleanup_candidate(current,path.parent):continue
                            page=pages.get(current['target_id'])
                            if page is None:continue
                            if page.url!=current.get('conversation_url'):continue
                            challenge=page.locator('#nocaptcha,[class*="captcha"]')
                            if any(challenge.nth(i).is_visible() for i in range(challenge.count())):continue
                            if not inventory['complete'] or sum(x.url==page.url for x in pages.values())!=1:continue
                            if current['state']=='response_saved':
                                provider=current['provider'];selector,stop,extract=(QA,QS,message_text) if provider=='qwen' else (ANSWER,STOP_BUTTON,_message_text)
                                if provider=='deepseek':
                                    from web_gpt.deepseek import ANSWER as DA,STOP as DS,message_text as DT
                                    selector,stop,extract=DA,DS,DT
                                stops=page.locator(stop);answers=page.locator(selector)
                                if any(stops.nth(i).is_visible() for i in range(stops.count())) or not answers.count():continue
                                if extract(answers.last)!=(path.parent/'response-raw.txt').read_text():continue
                            page.close();current['tab_cleanup']='closed_by_watch';atomic_json(path,current);report['closed'].append(current['target_id'])
                    # Disconnect Playwright without closing the dedicated Chrome.
            after_targets=_local_targets(endpoint)
            report['total_pages']+=sum(t.get('type')=='page' for t in after_targets)-sum(t.get('type')=='page' for t in targets)
            after=counts(after_targets)
            for provider in HOSTS:
                if endpoints[provider]==endpoint:report['counts'][provider]=after[provider]
        except Exception as exc:report['errors'].append(type(exc).__name__+': '+str(exc)[:500])
    report['over_limit']=['专用浏览器总页数'] if report['total_pages']>config.get('web_cards',{}).get('max_total_pages',20) else []
    atomic_json(folder/'web-tab-check.json',report)
    from core.api import action_inbox__publish as publish
    publish(config)
    return report


def run(config):
    import fcntl
    folder=Path(config['catalog_path']).parent;stop=False
    def stopping(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
    with (folder/'web-tab-watch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not stop:
            from core.api import control__pause_decision as pause_decision
            if not pause_decision(config,'tab_watch').allowed:break
            try:
                from .owner_supervision import tick as supervise_owner
                supervise_owner(config)
            except Exception as exc:
                print('owner supervision:',type(exc).__name__,str(exc)[:300],flush=True)
            from maintenance.sync_failed_dois import tick as sync_failed_dois
            sync_failed_dois(config)
            control=folder/'concurrency-control.json'
            revision=control.stat().st_mtime_ns if control.exists() else 0
            report=check(config)
            maintenance=report.get('browser_recovery',{}).get('pool_maintenance',{})
            interval=5 if maintenance.get('state')=='waiting' else 60
            for _ in range(interval):
                if stop:break
                current=control.stat().st_mtime_ns if control.exists() else 0
                if current!=revision:break
                time.sleep(1)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('run','check'));parser.add_argument('--config');args=parser.parse_args()
    config=load_config(args.config)
    if args.command=='run':run(config)
    else:print(json.dumps(check(config),ensure_ascii=False,indent=2))
