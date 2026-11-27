"""Periodic viewport evidence on the sole owner's existing asynchronous CDP loop.

No new browser connection, foreground activation, navigation, upload or send.
"""
import asyncio
import base64
import hashlib
import json
import os
import time
from core.api import paths__WorkspacePath as Path, services__atomic_json as atomic_json
from core.api import control__read_record as read_record
from .shared_browser_window import validate_registry
from .shared_page_repair import atomic_bytes

PRODUCER = 'owner-window-screenshot-v1'
PAGE_TIMEOUT_SECONDS = 6
ROUND_TIMEOUT_SECONDS = 45


def request(config):
    """Request fresh evidence from the existing owner; never starts a browser."""
    root=Path(config['catalog_path']).parent
    value={'id':str(time.time_ns()),'requested_at':time.time()}
    atomic_json(root/'window-screenshot-request.json',value)
    return value


def status(config):
    root=Path(config['catalog_path']).parent
    report=read_record(root/'window-screenshots/latest.json')
    service=read_record(root/'web-card-service.json')
    from core.api import runtime__alive as alive
    fresh=bool(report and time.time()-report.get('checked_at',0)<=130
        and report.get('owner_pid')==service.get('pid') and service.get('state')!='stopped'
        and alive(report.get('owner_pid')))
    return {**report,'fresh':fresh}


def _same_slot(root,registry,slot):
    current=read_record(root/'shared-gpt-window.json');validate_registry(current)
    return (current.get('created')==registry.get('created') and current['window_id']==registry['window_id']
        and next((s for s in current['slots'] if s['slot_id']==slot['slot_id']),None)==slot)


def _prune(directory,keep):
    """Only our own old rounds, excluding pinned evidence and all foreign files."""
    import shutil
    rounds=sorted((p for p in (directory/'rounds').iterdir() if p.is_dir() and not p.is_symlink()),reverse=True)
    for old in rounds[keep:]:
        if (old/'pin.json').exists():continue
        marker=read_record(old/'manifest.json')
        if marker.get('producer')==PRODUCER and old.resolve().is_relative_to((directory/'rounds').resolve()):
            shutil.rmtree(old)


async def capture(root,browser,pages,registered_targets):
    """Capture only freshly window-verified fixed slots; isolate every failure."""
    root=Path(root);control=read_record(root/'window-screenshot-control.json')
    if control.get('enabled') is not True:return {'state':'disabled','images':[]}
    registry=read_record(root/'shared-gpt-window.json');validate_registry(registry)
    from .owner_browser_calls import _metadata_session_async
    session=await asyncio.wait_for(_metadata_session_async(browser),3)
    directory=root/'window-screenshots';round_dir=directory/'rounds'/str(time.time_ns())
    round_dir.mkdir(parents=True,exist_ok=True)
    semaphore=asyncio.Semaphore(3);results={}
    async def one(slot):
        tid=slot.get('target_id');result={'slot_id':slot['slot_id'],'target_id':tid,'state':'missing'}
        results[slot['slot_id']]=result
        if not tid or tid not in registered_targets or tid not in pages:return result
        page=pages[tid];page_session=None;stage='semaphore_wait';timings={}
        async def measured(name,operation):
            nonlocal stage
            stage=name;started=time.monotonic()
            try:return await operation
            finally:timings[name]=time.monotonic()-started
        async def position():
            value=await asyncio.wait_for(session.send('Browser.getWindowForTarget',{'targetId':tid}),3)
            if value.get('windowId')!=registry['window_id'] or not _same_slot(root,registry,slot):
                raise ValueError('固定页面已离开原专窗或登记变化')
        async with semaphore:
            started=time.monotonic();deadline=asyncio.get_running_loop().time()+PAGE_TIMEOUT_SECONDS
            result.update(check_started_at=time.time(),page_timeout_seconds=PAGE_TIMEOUT_SECONDS,
                          stage_seconds=timings)
            try:
                # One shared deadline, rather than fresh budgets at every stage.
                # Slow early targets must release the three capture slots in time
                # for all twenty registered targets to receive a bounded attempt.
                async with asyncio.timeout_at(deadline):
                    await measured('window_before',position())
                    page_session=await measured('attach',asyncio.wait_for(page.context.new_cdp_session(page),3))
                    reply=await measured('capture',page_session.send('Page.captureScreenshot',{
                        'format':'jpeg','quality':65,'fromSurface':True,'captureBeyondViewport':False,
                        'optimizeForSpeed':True}))
                    stage='validate_image';raw=base64.b64decode(reply['data'],validate=True)
                    if len(raw)<32 or len(raw)>12_000_000 or raw[:2]!=b'\xff\xd8' or raw[-2:]!=b'\xff\xd9':
                        raise ValueError('页面未返回有效有界JPEG截图')
                    await measured('window_after',position())
                    path=round_dir/(slot['slot_id']+'.jpg')
                    await measured('persist',asyncio.to_thread(atomic_bytes,path,raw))
                    result.update(state='captured',path=str(path),sha256=hashlib.sha256(raw).hexdigest(),
                                  checked_at=time.time(),bytes=len(raw),url=page.url)
            except asyncio.CancelledError:
                result.update(state='capture_timeout',error_stage=stage,error='Round cancelled capture')
                raise
            except Exception as exc:
                result.update(state='capture_error',error_stage=stage,error=(type(exc).__name__+': '+str(exc))[:400])
            finally:
                result['operation_duration_seconds']=time.monotonic()-started
                try:
                    if page_session is not None:
                        # Dispatch detach once even after timeout, with only a minimal
                        # scheduling turn then; never add a fresh two-second page wait.
                        remaining=max(.001,deadline-asyncio.get_running_loop().time())
                        try:await measured('detach',asyncio.wait_for(page_session.detach(),min(2,remaining)))
                        except asyncio.CancelledError:
                            result['detach_error']='CancelledError: round ended during detach'
                            raise
                        except Exception as exc:result['detach_error']=(type(exc).__name__+': '+str(exc))[:200]
                finally:
                    result.update(check_finished_at=time.time(),duration_seconds=time.monotonic()-started)
        return result
    tasks={slot['slot_id']:asyncio.create_task(one(slot)) for slot in registry['slots']}
    done,pending=await asyncio.wait(tasks.values(),timeout=ROUND_TIMEOUT_SECONDS)
    for task in pending:task.cancel()
    if pending:await asyncio.gather(*pending,return_exceptions=True)
    images=[]
    for slot in registry['slots']:
        task=tasks[slot['slot_id']]
        if not task.cancelled() and task.exception() is None:images.append(task.result())
        else:
            partial=results.get(slot['slot_id'],{})
            # A completed, post-window-verified persisted JPEG remains valid if
            # only detach was cancelled. Preserve the separate cleanup failure.
            images.append({**partial,'slot_id':slot['slot_id'],'target_id':slot.get('target_id'),
                'state':'captured' if partial.get('state')=='captured' else 'capture_timeout',
                'round_cancelled':True})
    captured=sum(r['state']=='captured' for r in images)
    report={'producer':PRODUCER,'owner_pid':os.getpid(),'checked_at':time.time(),
        'capture_schema_version':2,'page_timeout_seconds':PAGE_TIMEOUT_SECONDS,
        'round_timeout_seconds':ROUND_TIMEOUT_SECONDS,
        'window_id':registry['window_id'],'registry_created':registry.get('created'),
        'round_dir':str(round_dir),'slot_count':len(images),'captured':captured,
        'state':'complete' if captured==len(images) else 'partial','images':images}
    atomic_json(round_dir/'manifest.json',report);atomic_json(directory/'latest.json',report)
    keep=control.get('retain_rounds',30)
    if type(keep) is not int or not 2<=keep<=120:keep=30
    await asyncio.to_thread(_prune,directory,keep)
    return report


async def run(observer):
    """Independent bounded screenshot worker; receipt/status checks keep running."""
    last=0;request_id=None
    while True:
        try:
            control=read_record(observer.root/'window-screenshot-control.json')
            pending=read_record(observer.root/'window-screenshot-request.json')
            interval=control.get('interval_seconds',60)
            if type(interval) not in (int,float) or not 30<=interval<=3600:interval=60
            due=time.monotonic()-last>=interval or pending.get('id')!=request_id
            if (control.get('enabled') is True and observer.window_browser is not None and due):
                last=time.monotonic();request_id=pending.get('id')
                await capture(observer.root,observer.window_browser,dict(observer.pages),set(observer.window_targets))
        except asyncio.CancelledError:raise
        except Exception as exc:
            atomic_json(observer.root/'window-screenshot-error.json',
                {'checked_at':time.time(),'owner_pid':os.getpid(),'error':(type(exc).__name__+': '+str(exc))[:500]})
        await asyncio.sleep(1)
