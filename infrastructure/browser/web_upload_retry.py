"""Scoped quota watcher: captures visible reset notices and resumes unsent jobs at reset."""
from __future__ import annotations
from core.api import paths__workspace_root as _workspace_root
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json
from browser.api import upload_quota__visible_notice as visible_notice, upload_quota__unsent_page as unsent_page

ROOT = _workspace_root()


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def alive(pid):
    try:
        if not isinstance(pid,int) or pid <= 0:return False
        os.kill(pid,0)
        return True
    except OSError:
        return False


def scope(base):
    base = Path(base).resolve()
    if base.parent != ROOT / 'data/web_card_loops':
        raise ValueError('Retry watcher accepts only an authorized web loop directory')
    loop = read(base / 'loop.json')
    if loop.get('state') == 'paused_by_user' or loop.get('active_round') not in (1,2,3):
        return base, loop, []
    rd = base / f"round-{loop['active_round']:02d}"
    run = read(rd / 'run.json')
    if len(loop.get('sample_ids',[])) != 5 or loop.get('round_limit') != 3:
        raise ValueError('Five-paper, three-round authorization scope missing')
    samples = [s for s in run.get('samples',[]) if s.get('paper_id') in loop['sample_ids']]
    return base, loop, [(rd/s['kind'],s) for s in samples]


def capture(base):
    from playwright.sync_api import sync_playwright
    base, loop, samples = scope(base)
    pending = [(folder, a, p) for folder,_ in samples for p in folder.glob('*/web-attempt.json')
               if (a := read(p)).get('state') == 'needs_inspection' and '附件上传失败' in a.get('error','')]
    # A prior coordinator may already have archived a proved-unsent attempt and
    # left the current worker waiting on the shared gate. Update that gate only.
    for folder,_ in samples:
        if read(folder/'progress.json').get('state')=='reviewed':continue
        for archived in folder.glob('*/web-attempt-quota-unsent.json'):
            target=archived.parent/'web-attempt.json'
            if not target.exists():pending.append((folder,read(archived),archived))
    if not pending:return 0
    captured = 0
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9222')
        pages = {}
        for context in browser.contexts:
            for page in context.pages:
                target = context.new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']['targetId']
                pages[target] = page
        for folder, attempt, path in pending:
            page = pages.get(attempt.get('target_id'))
            if page is None or not unsent_page(page):continue
            owners = [p for p in base.glob('round-*/*/*/web-attempt.json') if p != path and read(p).get('target_id') == attempt.get('target_id')]
            if owners:continue
            notice = visible_notice(page)
            if not notice or not notice.get('not_before_utc') or notice['not_before_utc'] in attempt.get('quota_retry_windows',[]):continue
            archived=path.name=='web-attempt-quota-unsent.json'
            worker_waiting=archived and alive(loop.get('worker_pid'))
            if archived and datetime.fromisoformat(notice['not_before_utc'])<=datetime.now(timezone.utc):continue
            old_control=read(base/'upload-control.json')
            if old_control.get('not_before_utc')!=notice['not_before_utc'] or old_control.get('source')!='live_browser_notice':
                atomic_json(base/'upload-control.json',dict(notice,reason='Live attachment limit',policy='Retry at page reset; existing worker preferred, no duplicate worker'))
            if worker_waiting:
                progress=read(folder/'progress.json')
                if progress.get('state')!='waiting_upload_quota' or progress.get('upload_quota',{}).get('not_before_utc')!=notice['not_before_utc']:
                    progress.update(state='waiting_upload_quota',upload_quota=notice,updated_at=datetime.now(timezone.utc).isoformat())
                    atomic_json(folder/'progress.json',progress)
                captured+=1
                continue
            if archived:path=path.parent/'web-attempt.json'
            atomic_json(path.parent / 'quota-before-capture.json',attempt)
            attempt.update(state='waiting_upload_quota', upload_quota=notice, unsent_verified=True,
                           quota_wait_pid=None, retry_owner='quota_watcher')
            atomic_json(path, attempt)
            atomic_json(base / 'upload-control.json', dict(notice,reason='Live attachment limit',policy='Retry at page reset; original unsent target only'))
            progress = read(folder / 'progress.json')
            progress.update(state='waiting_upload_quota', upload_quota=notice, updated_at=datetime.now(timezone.utc).isoformat())
            atomic_json(folder / 'progress.json',progress)
            captured += 1
    return captured


def watch(base):
    base,_,_ = scope(base)
    children = {}
    with (base/'upload-retry-watch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            while True:
                base, loop, samples = scope(base)
                if loop.get('state') == 'paused_by_user':break
                if loop.get('active_round') == 3 and samples and all(read(f/'progress.json').get('state')=='reviewed' for f,_ in samples):break
                status = dict(pid=os.getpid(),updated=time.time(),state='watching',children={str(p):c.pid for p,c in children.items() if c.poll() is None})
                atomic_json(base/'upload-retry-watch.json',status)
                try:
                    capture(base)
                    for folder, sample in samples:
                        if folder in children and children[folder].poll() is None:continue
                        candidates=[read(p) for p in folder.glob('*/web-attempt.json')]
                        waiting=[a for a in candidates if a.get('state')=='waiting_upload_quota' and not alive(a.get('quota_wait_pid'))]
                        if not waiting:continue
                        reset=max(datetime.fromisoformat(a['upload_quota']['not_before_utc']) for a in waiting)
                        control=read(base/'upload-control.json')
                        if control.get('not_before_utc'):reset=max(reset,datetime.fromisoformat(control['not_before_utc']))
                        if datetime.now(timezone.utc)<reset:continue
                        # Runner rechecks exact page, immutable hashes, pause and serial locks.
                        log=(folder/'quota-resume.log').open('a')
                        try:
                            children[folder]=subprocess.Popen([sys.executable,str(base/'run_round.py'),'--round',str(loop['active_round']),'--resume-sample',sample['kind']],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                        finally:log.close()
                except Exception as exc:
                    status.update(state='needs_inspection',error=str(exc)[:500]);atomic_json(base/'upload-retry-watch.json',status)
                time.sleep(3)
        finally:
            atomic_json(base/'upload-retry-watch.json',dict(pid=os.getpid(),updated=time.time(),state='stopped'))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--loop-dir',required=True)
    parser.add_argument('--capture-once',action='store_true')
    args=parser.parse_args()
    if args.capture_once:print('Captured quota resets:',capture(args.loop_dir))
    else:watch(args.loop_dir)
