"""Explicit startup click requests, executed by the existing browser owner only."""
import fcntl
import hashlib
import json
import os
import subprocess
import time
import uuid
import urllib.request
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit
from core.api import services__atomic_json as atomic_json
from core.api import control__read_record as read_record


def request(config, target):
    root=Path(config['catalog_path']).parent
    with (root/'browser-start.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=root/'browser-start-request.json';old=read_record(path)
        if old.get('state') in ('pending','launching','launched','waiting_endpoint'):
            return old
        value={'id':uuid.uuid4().hex,'state':'pending','target':target,'requested':time.time()}
        atomic_json(path,value);return value


def run_once(config):
    root=Path(config['catalog_path']).parent
    path=root/'browser-start-request.json'
    with (root/'browser-start.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        value=read_record(path)
        if value.get('state') not in ('pending','launching','launched','waiting_endpoint','ready'):return value
        from cards.api import web_card_service__owner_enabled as owner_enabled
        if not owner_enabled(config):return value
        endpoint=os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222').rstrip('/')
        url=urlsplit(endpoint)
        if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or not url.port or url.path:
            raise ValueError('启动仅允许本机专用Chrome端口')
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(endpoint+'/json/version',timeout=2) as response:version=json.load(response)
            if not str(version.get('Browser','')).startswith(('Chrome/','HeadlessChrome/')):raise ValueError('端口不是Chrome')
        except OSError:
            version=None
        if version:
            if value['state']=='ready':return value
            value.update(state='ready',reused=True,checked=time.time());atomic_json(path,value);return value
        if value['state']=='ready':
            value=_recover_closed(config,root,value,endpoint)
            if value['state'] != 'pending':
                if value.get('target') == 'formula_temp_pilot':
                    return {**value, 'state': 'waiting_endpoint'}
                return value
        # An unknown launch receipt is never permission to open another window.
        if value['state']!='pending':return value
        profile=Path(os.environ.get('WEB_GPT_CHROME_PROFILE',str(Path.home()/'ChromeProfiles/chatgpt_auto'))).resolve()
        from .browser_recovery import main_chrome_pid
        existing=main_chrome_pid(profile,url.port)
        if existing:
            value.update(state='waiting_endpoint',existing_pid=existing,checked=time.time());atomic_json(path,value);return value
        value.update(state='launching',owner_pid=os.getpid(),launch_intent=time.time());atomic_json(path,value)
        try:
            result=subprocess.run(['open','-gna','Google Chrome','--args','--remote-debugging-port='+str(url.port),
                '--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check','https://chatgpt.com/'],
                capture_output=True,text=True,timeout=30)
            value.update(state='launched' if result.returncode==0 else 'failed',returncode=result.returncode,
                         error=result.stderr[-300:],checked=time.time())
        except (OSError,subprocess.TimeoutExpired) as exc:
            value.update(state='launching',error=str(exc)[:300],checked=time.time())
        atomic_json(path,value);return value


def _recoverable_pilot(config, root, request, registry, channel):
    if request.get('target') != 'formula_temp_pilot' or request.get('id') != registry.get('startup_request_id'):
        return False
    if channel.get('manual_verification_required') and channel.get('source') != 'user_report_current_chat':
        return False
    from .formula_only import enabled
    control = read_record(root/'formula-only-control.json')
    if control.get('mode') != 'temporary_pilot' or not control.get('pilot_folder') or not enabled(config):
        return False
    pilot = Path(control['pilot_folder'])
    if not (pilot/'two-papers.zip').is_file() or (pilot/'attempt.json').exists():
        return False
    from .shared_pool_store import load_pool
    entries = load_pool(root/'gpt-window-pool.json')['windows']
    slots = [entries.get(slot['target_id'], {}) for slot in registry['slots']]
    return all(entry.get('never_submitted') is True and entry.get('state') in ('opening', 'ready_blank')
               and entry.get('startup_request_id') == request['id'] for entry in slots)


def _recover_closed(config, root, previous, endpoint):
    """Two absent-process checks can request one new launch on the same owner.

    A live process, partial startup, account pause, damaged registry or unknown
    launch receipt never grants a new launch. Original ledgers stay untouched.
    """
    if not config.get('web_cards',{}).get('browser_recovery',{}).get('enabled'):
        return previous
    channel = read_record(root/'web-channel-control.json').get('chatgpt', {})
    registry = read_record(root/'shared-gpt-window.json')
    if not registry:
        return previous
    from .shared_browser_window import validate_registry
    validate_registry(registry)
    if registry.get('endpoint')!=endpoint or not all(s.get('target_id') for s in registry['slots']):return previous
    if previous.get('pool_state') != 'ready' or channel.get('manual_verification_required'):
        # The user explicitly requested a login recheck for an unsent pilot.
        # A previously observed ready endpoint can disappear during initialization.
        if not _recoverable_pilot(config, root, previous, registry, channel):
            return previous
    profile=Path(os.environ.get('WEB_GPT_CHROME_PROFILE',str(Path.home()/'ChromeProfiles/chatgpt_auto'))).resolve()
    from .browser_recovery import main_chrome_pid
    pid=main_chrome_pid(profile,urlsplit(endpoint).port)
    path=root/'browser-start-recovery.json';old=read_record(path);at=time.time()
    identity=hashlib.sha256(json.dumps({'request_id':previous['id'],'registry':registry,
        'profile':str(profile),'endpoint':endpoint},sort_keys=True).encode()).hexdigest()
    history=[t for t in old.get('recoveries',[]) if isinstance(t,(int,float)) and at-3600<t<=at]
    if pid:
        atomic_json(path,{'state':'waiting_existing_process','pid':pid,'checked_at':at,'recoveries':history})
        return previous
    if old.get('identity')==identity and old.get('state')=='requested':
        # Resume the same durable intent if the owner stopped between writes.
        pending=old['next_request'];atomic_json(root/'browser-start-request.json',pending);return pending
    checks=old.get('checks',[]) if old.get('identity')==identity else []
    if not checks or at-checks[-1]>=30:checks=(checks+[at])[-2:]
    evidence={'state':'waiting_second_check','identity':identity,'checks':checks,'checked_at':at,
              'profile':str(profile),'endpoint':endpoint,'previous_request_id':previous['id'],
              'process_absent':True,'endpoint_unavailable':True,'recoveries':history}
    if len(checks)<2:
        atomic_json(path,evidence);return previous
    if len(history)>=2 or history and at-history[-1]<300:
        evidence['state']='recovery_cooldown';atomic_json(path,evidence);return previous
    pending={'id':uuid.uuid4().hex,'state':'pending','target':previous.get('target','cards'),
             'requested':at,'origin':'closed_browser_recovery','previous_request_id':previous['id']}
    archive=root/'browser-start-archives'/pending['id']
    atomic_json(archive/'request.json',previous);atomic_json(archive/'registry.json',registry)
    atomic_json(archive/'closed-browser-evidence.json',evidence)
    evidence.update(state='requested',next_request=pending,recoveries=history+[at],archive=str(archive))
    atomic_json(path,evidence);atomic_json(root/'browser-start-request.json',pending)
    return pending
