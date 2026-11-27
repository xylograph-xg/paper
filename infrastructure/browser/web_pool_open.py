"""Enroll an explicitly user-opened blank GPT page; create a page only on an explicit startup click."""
import json
import hashlib
import os
import sys
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json


def shared_mode(config):
    return config.get('web_cards',{}).get('shared_window',{}).get('enabled') is True


def shared_window_record(config):
    """Read the owner's registration; never repair or adopt pages here."""
    root=Path(config['catalog_path']).parent
    path=root/'shared-gpt-window.json'
    raw=path.read_bytes()
    record=json.loads(raw)
    wanted=config['web_cards']['shared_window'].get('slot_count',20)
    if type(wanted) is not int or wanted!=20:raise ValueError('共享窗口必须登记20个固定槽位')
    if not isinstance(record,dict):raise ValueError('共享窗口登记必须为对象')
    from .shared_browser_window import validate_registry
    validate_registry(record)
    endpoint=os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222')
    if record.get('endpoint',endpoint)!=endpoint:raise ValueError('共享窗口登记的浏览器端口不一致')
    return record,hashlib.sha256(raw).hexdigest()


def shared_maintenance_request(config,origin,record=None,manifest_sha256='',ensure_page=False):
    """Queue an owner-only maintenance request, without granting send authority."""
    root=Path(config['catalog_path']).parent
    request={'schema_version':1,'state':'pending','requested':time.time(),'origin':origin,
             'action':'reconcile' if record is not None else 'initialize',
             'slot_count':20,'ensure_page':bool(ensure_page),'manifest_sha256':manifest_sha256}
    if record is not None:request['window_id']=record['window_id']
    atomic_json(root/'shared-window-maintenance-request.json',request)
    return request


def request_shared(config,ensure_page=False):
    try:
        record,fingerprint=shared_window_record(config)
    except FileNotFoundError:
        result={'state':'needs_inspection','reused':False,'created_pages':0,'slot_count':20,
                'error':'共享窗口尚未登记，入口不会自行创建或接管页面'}
        if ensure_page:
            maintenance=shared_maintenance_request(config,'explicit_open_gpt',ensure_page=True)
            result.update(maintenance_requested=True,action=maintenance['action'])
        return result
    except (OSError,ValueError,TypeError) as exc:
        return {'state':'needs_inspection','reused':False,'created_pages':0,'slot_count':20,
                'error':'共享窗口登记需要核对：'+str(exc)[:300]}
    maintenance=shared_maintenance_request(config,'explicit_open_gpt',record,fingerprint,ensure_page)
    return {'state':'shared_pool_registered','reused':True,'created_pages':0,
            'window_id':record['window_id'],'slot_count':20,'maintenance_requested':True,
            'action':maintenance['action'],'pool_state':record.get('state','registered')}


def eligible(tid, url, users, answers, draft, ledger=None, entry=None):
    if url.rstrip('/') != 'https://chatgpt.com' or users or answers or draft.strip():return False
    if ledger and ledger.get('state') not in ('not_sent','deferred'):return False
    if entry and entry.get('state') not in ('ready','ready_blank'):return False
    return True


def ensure_startup_page(browser):
    existing=[page for context in browser.contexts for page in context.pages]
    # The browser process can be alive with zero tabs. A connection is
    # not a usable GPT window; an explicit click may create one.
    if not any(page.url.split('?')[0].rstrip('/')=='https://chatgpt.com' for page in existing):
        if len(existing)>=20:raise ValueError('浏览器已达20页，请先释放一个页面')
        session=browser.new_browser_cdp_session()
        session.send('Target.createTarget',{'url':'https://chatgpt.com/','background':False})
        deadline=time.monotonic()+15
        while True:
            session.send('Target.getTargets')  # Dispatch newly opened page events.
            if any(page.url.rstrip('/')=='https://chatgpt.com' for context in browser.contexts for page in context.pages):break
            if time.monotonic()>deadline:raise RuntimeError('GPT页面尚未打开')
            time.sleep(.2)
        session.detach()


def request(config,ensure_page=False):
    if shared_mode(config):
        record=request_shared(config,ensure_page)
        print(json.dumps(record,ensure_ascii=False))
        return record
    sys.path.insert(0,os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[3] / 'chatgpt_playwright')))
    from playwright.sync_api import sync_playwright
    from web_gpt.core import ANSWER,wait_prompt_box,_box_text
    from .web_card_pool import USER
    from .web_card_transport import require_no_verification
    root=Path(config['catalog_path']).parent
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222'),no_defaults=True)
        candidates=[]
        if ensure_page:ensure_startup_page(browser)
        for context in browser.contexts:
            for page in context.pages:
                if page.url.rstrip('/')!='https://chatgpt.com':continue
                require_no_verification(page)
                cdp=context.new_cdp_session(page)
                try:tid=cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
                finally:cdp.detach()
                if eligible(tid,page.url,page.locator(USER).count(),page.locator(ANSWER).count(),_box_text(wait_prompt_box(page,timeout=5000))):candidates.append(tid)
        if len(candidates)!=1:raise ValueError('需要唯一已打开的空白GPT页；不自动新建或清空其他页面')
        record={'target_id':candidates[0],'requested':time.time(),'origin':'explicit_open_gpt','state':'pending'}
        atomic_json(root/'gpt-page-adoption.json',record)
        print(json.dumps(record,ensure_ascii=False))
        return record


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--config');parser.add_argument('--wait',type=int,default=0);parser.add_argument('--ensure-page',action='store_true')
    args=parser.parse_args();end=time.monotonic()+args.wait
    while True:
        try:request(load_config(args.config),ensure_page=args.ensure_page);break
        except Exception:
            if time.monotonic()>=end:raise
            time.sleep(1)
