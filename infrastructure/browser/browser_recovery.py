"""Bounded recovery of the dedicated Chrome; never repeat a submitted request."""
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit
from core.api import catalog__ROOT as ROOT, catalog__now as now
from core.api import control__pause_decision as pause_decision, control__read_record as read_record
from core.api import services__atomic_json as atomic_json

ENDPOINT='http://127.0.0.1:9222'


def targets(endpoint):
    if urlsplit(endpoint).hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('仅恢复本机专用浏览器')
    with urllib.request.urlopen(endpoint+'/json/list',timeout=5) as response:return json.load(response)


def owned_ids(folder):
    ids=set(read_record(folder/'gpt-window-pool.json').get('windows',{}))
    ids.update(read_record(folder/'browser-recovery.json').get('new_targets',[]))
    for path in (folder/'browser-page-adoptions').glob('*.json'):
        tid=read_record(path).get('target_id')
        if tid:ids.add(tid)
    for path in (folder/'browser_diagnostics').glob('*/report.json'):
        try:ids.update(s['target_id'] for s in json.loads(path.read_text()).get('sessions',[]))
        except (OSError,ValueError,KeyError):pass
    return ids


def main_chrome_pid(profile,port):
    result=subprocess.run(['ps','-axo','pid=,command='],capture_output=True,text=True,check=True)
    found=[]
    for line in result.stdout.splitlines():
        parts=line.strip().split(None,1)
        if len(parts)!=2:continue
        command=parts[1]
        if command.startswith('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome ') and re.search(r'(?:^|\s)--user-data-dir='+re.escape(str(profile))+r'(?:\s|$)',command) and re.search(r'(?:^|\s)--remote-debugging-port='+str(port)+r'(?:\s|$)',command):found.append(int(parts[0]))
    if len(found)>1:raise RuntimeError('专用Chrome进程不唯一，不关闭')
    return found[0] if found else None


def enroll(folder,tids):
    directory=folder/'browser-page-adoptions';directory.mkdir(exist_ok=True)
    for tid in tids:atomic_json(directory/(tid+'.json'),{'target_id':tid,'state':'pending','origin':'authorized_browser_recovery','requested':time.time()})


def open_owned_pages(config,urls,use_bootstrap=False,pool_target=None):
    sys.path.insert(0,os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[3] / 'chatgpt_playwright')))
    from playwright.sync_api import sync_playwright
    folder=Path(config['catalog_path']).parent
    endpoint=os.environ.get('WEB_GPT_CDP_URL',ENDPOINT);ids=[];blank_ids=[]
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint,timeout=10000,no_defaults=True)
        current=[p for c in browser.contexts for p in c.pages]
        bootstrap=current[0] if use_bootstrap and len(current)==1 and current[0].url=='about:blank' else None
        if len(current)+len(urls)-(1 if bootstrap else 0)>20:raise RuntimeError('浏览器总页数已达上限，不补开')
        for index,url in enumerate(urls):
            if pool_target is not None:
                from core.api import concurrency_control__settings as settings
                from core.api import concurrency_control__apply as apply
                apply(config)
                desired=config['web_cards']['target_pool_pages']+quarantined_slots(folder,live_targets=targets(endpoint))
                live=[t for t in targets(endpoint) if t.get('type')=='page']
                if sum(t['id'] in owned_ids(folder) for t in live)>=desired:break
            page=bootstrap if index==0 and bootstrap else browser.contexts[0].new_page();page._web_gpt_background=True
            cdp=page.context.new_cdp_session(page)
            try:tid=cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
            finally:cdp.detach()
            ids.append(tid)
            directory=folder/'browser-page-adoptions';directory.mkdir(exist_ok=True)
            if url=='https://chatgpt.com/':atomic_json(directory/(tid+'.json'),{'target_id':tid,'state':'opening','origin':'authorized_pool_maintenance','requested':time.time()})
            page.goto(url,wait_until='commit' if pool_target is not None else 'domcontentloaded',timeout=15000 if pool_target is not None else 60000)
            if url=='https://chatgpt.com/':
                from web_gpt.core import wait_prompt_box
                from .web_card_transport import require_no_verification
                require_no_verification(page);wait_prompt_box(page,timeout=10000 if pool_target is not None else 30000);blank_ids.append(tid)
                enroll(folder,[tid]) # A later page timeout must not lose this ready slot.
            # Restored conversations require exact original material evidence.
            else:
                from .web_card_pool import USER
                from web_gpt.core import _dense
                for path in (folder/'web_cards').glob('*/chatgpt/attempt.json'):
                    a=json.loads(path.read_text())
                    if a.get('conversation_url')!=url or a.get('state') not in ('submitted','submission_started','needs_inspection'):continue
                    expected=path.parent/'prompt-actual.txt';users=page.locator(USER)
                    if not expected.exists() or users.count()!=1 or _dense(expected.read_text()) not in _dense(users.first.inner_text()):continue
                    if hashlib.sha256(expected.read_bytes()).hexdigest()!=a.get('actual_prompt_sha256'):continue
                    a.setdefault('target_history',[]).append(a.get('target_id'));a['target_id']=tid;a['recovered_at']=now();atomic_json(path,a)
    enroll(folder,blank_ids)
    return ids


def check_health(config,force_restart=False):
    folder=Path(config['catalog_path']).parent
    if config.get('web_cards',{}).get('shared_window',{}).get('enabled') or (folder/'shared-gpt-window.json').exists():
        return {'state':'owner_managed'}
    if folder.resolve()!=(ROOT/'data').resolve():return {'state':'out_of_scope'}
    if not config.get('web_cards',{}).get('browser_recovery',{}).get('enabled'):return {'state':'disabled'}
    if not pause_decision(config,'web_cards').allowed:return {'state':'paused'}
    manual=read_record(folder/'web-channel-control.json')
    if manual.get('chatgpt',{}).get('manual_verification_required'):return {'state':'manual_verification'}
    endpoint=os.environ.get('WEB_GPT_CDP_URL',ENDPOINT);path=folder/'browser-recovery.json';record=read_record(path)
    try:
        live=[t for t in targets(endpoint) if t.get('type')=='page']
        atomic_json(folder/'browser-health-snapshot.json',{'updated':time.time(),'pages':live})
        if live and not force_restart and not any(t.get('url','').startswith('chrome-error://') for t in live):
            record.pop('error',None);record.update(state='healthy',failures=0,updated=time.time());atomic_json(path,record);return record
        fault='no_pages' if not live else 'explicit_recovery_test' if force_restart else 'chrome_error_page'
    except (OSError,ValueError) as exc:
        fault=str(exc);record['failures']=record.get('failures',0)+1
        if record['failures']<2 and not force_restart:
            record.update(state='retry_connection',error=fault,updated=time.time());atomic_json(path,record);return record
        live=read_record(folder/'browser-health-snapshot.json').get('pages',[])
    if not force_restart and time.time()-record.get('last_recovery',0)<300:return {**record,'state':'recovery_cooldown'}
    history=[t for t in record.get('recoveries',[]) if t>time.time()-3600]
    if len(history)>=2:return {**record,'state':'recovery_limit'}
    # Do not shut down another project's/user's dedicated-browser page.
    unknown=[t['id'] for t in live if t.get('id') not in owned_ids(folder)]
    if unknown:
        record.update(state='needs_inspection',error='有非本任务页面，不关闭浏览器',unknown_targets=unknown);atomic_json(path,record);return record
    record.update(state='recovering',error=fault,last_recovery=time.time(),recoveries=history+[time.time()],updated=time.time())
    atomic_json(path,record)
    try:
        if fault=='no_pages':ids=open_owned_pages(config,['https://chatgpt.com/'])
        else:
            profile=Path(os.environ.get('WEB_GPT_CHROME_PROFILE',str(Path.home()/'ChromeProfiles/chatgpt_auto'))).resolve()
            port=urlsplit(endpoint).port or 9222;pid=main_chrome_pid(profile,port)
            plan=[]
            for t in live:
                url=t.get('url','')
                if url.startswith('https://chatgpt.com/c/') and 'local-chatgpt' not in url:plan.append(url)
            record.update(previous_pid=pid,saved_pages=live,restore_urls=list(dict.fromkeys(plan)));atomic_json(path,record)
            if pid:
                os.kill(pid,signal.SIGTERM)
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    try:os.kill(pid,0)
                    except ProcessLookupError:break
                    time.sleep(.2)
                else:raise RuntimeError('专用Chrome未正常退出，不强制关闭')
            subprocess.run(['open','-gna','Google Chrome','--args','--remote-debugging-port='+str(port),'--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check','about:blank'],check=True)
            deadline=time.monotonic()+25
            while True:
                try:targets(endpoint);break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.5)
            ids=open_owned_pages(config,list(dict.fromkeys(plan)) or ['https://chatgpt.com/'],use_bootstrap=True)
        record.update(state='recovered',failures=0,new_targets=ids,finished=time.time());atomic_json(path,record);return record
    except Exception as exc:
        from .web_card_transport import failure_kind
        if failure_kind(str(exc))=='verification':
            manual['chatgpt']={'manual_verification_required':True,'reason':str(exc)[:300],'observed':time.time()}
            atomic_json(folder/'web-channel-control.json',manual)
        record.update(state='needs_inspection',error=str(exc)[:700],finished=time.time());atomic_json(path,record);return record


def quarantined_slots(folder,live_targets):
    """Preserve uncertain conversations but do not count them as working slots."""
    pool=read_record(Path(folder)/'gpt-window-pool.json').get('windows',{})
    return sum(t.get('type')=='page' and pool.get(t.get('id'),{}).get('state')=='needs_inspection' for t in live_targets)


def pool_capacity(live,owned,target,limit=20):
    """Count only live owned slots; other pages still consume total capacity."""
    pages=[t for t in live if t.get('type')=='page']
    return max(0,min(max(0,int(target)-sum(t.get('id') in owned for t in pages)),int(limit)-len(pages)))


def maintain_pool(config):
    folder=Path(config['catalog_path']).parent
    if config.get('web_cards',{}).get('shared_window',{}).get('enabled') or (folder/'shared-gpt-window.json').exists():
        return {'state':'owner_managed'}
    from core.api import concurrency_control__apply as apply_concurrency
    apply_concurrency(config)
    folder=Path(config['catalog_path']).parent
    target=config.get('web_cards',{}).get('target_pool_pages',0)
    if not target or folder.resolve()!=(ROOT/'data').resolve():return {'state':'disabled'}
    if not pause_decision(config,'web_cards').allowed:return {'state':'paused'}
    if read_record(folder/'web-channel-control.json').get('chatgpt',{}).get('manual_verification_required'):return {'state':'manual_verification'}
    sys.path.insert(0,os.environ.get('WEB_GPT_IMPORT_ROOT',str(Path(__file__).resolve().parents[3] / 'chatgpt_playwright')))
    from web_gpt.submission import submission_lock
    record={'target_pages':target,'updated':time.time()}
    try:
        with submission_lock(timeout=5):
            live=targets(os.environ.get('WEB_GPT_CDP_URL',ENDPOINT))
            quarantined=quarantined_slots(folder,live)
            record['quarantined_pages']=quarantined
            count=pool_capacity(live,owned_ids(folder),target+quarantined,config['web_cards'].get('max_total_pages',20))
            record['created_targets']=open_owned_pages(config,['https://chatgpt.com/']*min(count,2),pool_target=target) if count else []
            record['state']='waiting' if count>len(record['created_targets']) else 'maintained'
    except Exception as exc:
        record.update(state='waiting',error=str(exc)[:400])
        from .web_card_transport import failure_kind
        if failure_kind(str(exc))=='verification':
            manual=read_record(folder/'web-channel-control.json');manual['chatgpt']={'manual_verification_required':True,'reason':str(exc)[:300],'observed':time.time()};atomic_json(folder/'web-channel-control.json',manual)
    atomic_json(folder/'browser-pool-maintenance.json',record)
    return record
