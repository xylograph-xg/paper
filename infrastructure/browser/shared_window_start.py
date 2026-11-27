"""Explicit startup initialization, executed on the sole owner's connection."""
import json
import os
import re
import time
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json
from core.api import control__read_record as read_record
from .owner_browser_calls import bounded_call
from .shared_browser_window import read_window_inventory, validate_registry
from .shared_window_tabs import blank_url, create_in_window
from .shared_pool_store import save_pool

NETWORK_FAILURE=re.compile(r'ERR_(?:PROXY_CONNECTION_FAILED|INTERNET_DISCONNECTED|NAME_NOT_RESOLVED|NETWORK_CHANGED|CONNECTION_(?:CLOSED|RESET|REFUSED|TIMED_OUT)|TIMED_OUT)')


def run_once(config, browser, pool, lock_factory, stopping, *, first_slot_only=False):
    root=Path(config['catalog_path']).parent
    request_path=root/'browser-start-request.json'; request=read_record(request_path)
    if request.get('state')!='ready' or request.get('pool_state')=='ready' or stopping():return
    if request.get('network_retry_at',0)>time.time():return
    registry_path=root/'shared-gpt-window.json'
    with lock_factory(timeout=5):
        inventory=read_window_inventory(browser)
        if not inventory['complete']:return
        old=read_record(registry_path)
        if old:validate_registry(old)
        # A whole registered window can disappear while Chrome itself stays up
        # (window closed, renderer/tab discard, proxy crash).  The startup request
        # then keeps a stale ``initializing_window`` and only fills ``None`` slots,
        # so no code path can ever create the twenty pages again.  Rebuild only
        # when every old target is gone and every old slot is proven never used;
        # any real ledger or non-blank entry keeps the original path blocked.
        lost_window=None
        if old and request.get('initializing_window'):
            wid=request['initializing_window']
            live_in_window=any(t.get('window_id')==wid for t in inventory['targets'].values())
            old_ids={s.get('target_id') for s in old['slots'] if s.get('target_id')}
            old_entries=[pool['windows'].get(tid,{}) for tid in old_ids]
            never_used=(bool(old_ids) and all(e.get('never_submitted') is True
                and e.get('state') in ('opening','ready_blank') for e in old_entries))
            if (not live_in_window and never_used
                    and not any(tid in inventory['targets'] for tid in old_ids)):
                from .attempt_history import index_attempts
                records,_unused=index_attempts(root)
                if not any(r.get('target_id') in old_ids for r in records.values()):
                    lost_window=wid
        if lost_window is not None:
            archive=root/'browser-start-rebuilds'/f'{int(time.time()*1000)}-{lost_window}'
            atomic_json(archive/'request.json',request)
            atomic_json(archive/'registry.json',old)
            restart_path=root/'startup-page-restart-request.json'
            pending_restart=read_record(restart_path)
            if pending_restart and pending_restart.get('state') not in ('complete','superseded'):
                atomic_json(archive/'startup-page-restart.json',pending_restart)
                pending_restart.update(state='superseded',superseded_at=time.time(),
                    reason='window_lost_before_send')
                atomic_json(restart_path,pending_restart)
            old_ids={s.get('target_id') for s in old['slots'] if s.get('target_id')}
            for tid in old_ids:
                entry=pool['windows'].get(tid)
                if entry and entry.get('never_submitted') is True:
                    entry.update(state='retired_window_lost',retired_at=time.time(),
                        error='原窗口丢失且该槽从未发送；完整归档后重建')
            request.pop('initializing_window',None)
            request.pop('window_creation_intent',None)
            request.pop('startup_health',None)
            request.update(rebuild_reason='window_lost',rebuild_from_window=lost_window,
                rebuild_requested=time.time(),pool_state='rebuild_pending',
                loaded_slots=0,ready_slots=0)
            save_pool(root/'gpt-window-pool.json',pool)
            atomic_json(request_path,request)
        # A surviving registered window is maintained through its existing repair path.
        if old and not request.get('initializing_window'):
            if any(t['window_id']==old['window_id'] for t in inventory['targets'].values()):
                if all(inventory['targets'].get(s.get('target_id'),{}).get('window_id')==old['window_id'] for s in old['slots']):
                    request.update(pool_state='ready',pool_checked=time.time());atomic_json(request_path,request)
                return
            # All old targets must be absent. Their material ledgers remain untouched.
            if any(s.get('target_id') in inventory['targets'] for s in old['slots']):return
        nonce='startup-'+request['id']; url=blank_url(nonce)
        if not request.get('initializing_window'):
            candidates=[t for t in inventory['targets'].values() if t['url']==url]
            if not candidates:
                if request.get('window_creation_intent'):return
                request.update(window_creation_intent=time.time(),pool_state='initializing')
                atomic_json(request_path,request)
                session=bounded_call(browser,'new_browser_cdp_session')
                try:bounded_call(session,'send','Target.createTarget',{'url':url,'newWindow':True,'background':True})
                finally:bounded_call(session,'detach')
                inventory=read_window_inventory(browser)
                candidates=[t for t in inventory['targets'].values() if t['url']==url]
            if len(candidates)!=1:return
            first=candidates[0];wid=first['window_id']
            if any(t['window_id']==wid and t['target_id']!=first['target_id'] for t in inventory['targets'].values()):return
            archive=root/'browser-start-archives'/request['id']/'registry.json'
            if old and not archive.exists():atomic_json(archive,old)
            registry={'schema_version':1,'window_id':wid,'endpoint':old.get('endpoint','http://127.0.0.1:9222'),
                'slots':[{'slot_id':f'{i:02d}','target_id':first['target_id'] if i==1 else None} for i in range(1,21)],
                'startup_request_id':request['id'],'created':time.time()}
            pool['windows'][first['target_id']]={'state':'opening','never_submitted':True,'startup_request_id':request['id']}
            save_pool(root/'gpt-window-pool.json',pool);atomic_json(registry_path,registry)
            request.update(initializing_window=wid,pool_state='initializing');atomic_json(request_path,request)
        registry=read_record(registry_path);validate_registry(registry)
        if registry.get('startup_request_id')!=request['id']:return
        from .startup_page_restart import run_once as restart_stalled_pages
        registry=restart_stalled_pages(config,browser,pool,request,registry,stopping)
        for slot in registry['slots']:
            if stopping():return
            if slot.get('target_id'):continue
            def persist(candidate):
                slot['target_id']=candidate['target_id']
                pool['windows'][candidate['target_id']]={'state':'opening','never_submitted':True,'startup_request_id':request['id']}
                save_pool(root/'gpt-window-pool.json',pool);atomic_json(registry_path,registry)
            create_in_window(browser,registry['window_id'],root=root/'browser-start-extensions',
                nonce=nonce+'-'+slot['slot_id'],owned_ids={s['target_id'] for s in registry['slots'] if s.get('target_id')},
                on_created=persist,stopping=stopping,timeout=10)
        from .browser_inventory import enumerate_pages
        from .shared_page_health import snapshot_page
        pages=enumerate_pages(browser)['pages'];ready=0;checks=[]
        for slot in (registry['slots'][:1] if first_slot_only else registry['slots']):
            if stopping():return
            tid=slot['target_id'];page=pages.get(tid)
            if page is None:continue
            entry=pool['windows'][tid]
            if entry.get('state')!='opening':ready+=1;continue
            if page.url.startswith('about:blank') or page.url.startswith('chrome-error://'):
                # Dispatch navigation on the resident connection without waiting
                # for each document; readiness is observed on following passes.
                session=bounded_call(page.context,'new_cdp_session',page)
                try:bounded_call(session,'send','Page.navigate',{'url':'https://chatgpt.com/'})
                finally:bounded_call(session,'detach')
            request.update(pool_state='loading_pages',loaded_slots=sum(p.url.startswith('https://chatgpt.com/') for t,p in pages.items() if t in {s['target_id'] for s in registry['slots']}),pool_checked=time.time())
            atomic_json(request_path,request)
            snap=snapshot_page(tid,page)
            checks.append(snap)
            if (snap.get('inspection_complete') is True and not any(snap.get(k) for k in
                ('login','verification','quota','user_texts','answer_texts','attachments','errors')) and not snap.get('draft','').strip() and snap.get('streaming') is False and snap.get('composer_available') is True):
                entry.update(state='ready_blank',adopted=time.time());ready+=1
        save_pool(root/'gpt-window-pool.json',pool)
        atomic_json(root/'browser-start-page-checks.json',{'checked_at':time.time(),'owner_pid':os.getpid(),'pages':checks})
        network_errors=[snap for snap in checks if NETWORK_FAILURE.search(
            '\n'.join(str(v) for v in snap.get('errors',[])))]
        if network_errors:
            # Keep the same startup pages and retry navigation after a bounded
            # delay instead of closing/recreating twenty pages while the proxy
            # route is down.
            request.update(pool_state='waiting_network',network_retry_at=time.time()+30,
                network_error_count=len(network_errors),ready_slots=ready,pool_checked=time.time())
            atomic_json(request_path,request)
            return
        request.pop('network_retry_at',None);request.pop('network_error_count',None)
        from .startup_page_restart import schedule_stalled
        schedule_stalled(config,root,pool,request,registry,checks)
        request.update(pool_state='ready' if ready==20 else 'waiting_page_readiness',ready_slots=ready,pool_checked=time.time())
        atomic_json(request_path,request)
