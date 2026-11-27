"""Owner-only, explicitly target-bound restart of stalled startup pages."""
import hashlib
import time
from core.api import paths__WorkspacePath as Path
from core.api import control__read_record as read_record
from core.api import services__atomic_json as atomic_json
from .shared_pool_store import save_pool
from .shared_browser_window import read_window_inventory
from .shared_window_owner import require_slot
from .shared_window_tabs import create_in_window, blank_url
from .shared_page_health import snapshot_page


def safe(snapshot):
    return (snapshot.get('inspection_complete') is True and snapshot.get('streaming') is False
            and not any(snapshot.get(k) for k in ('login','verification','quota','user_texts',
                'answer_texts','answer_element_count','attachments')))


def draft_hash(snapshot):
    return hashlib.sha256(snapshot.get('draft','').encode()).hexdigest()


def schedule_stalled(config,root,pool,request,registry,checks,*,at=None):
    """Count two fresh owner checks, separated by the configured interval."""
    policy=config.get('web_cards',{}).get('shared_window',{}).get('health_repair',{})
    if not policy.get('startup_stalled_reopen_enabled'):return
    at=time.time() if at is None else at
    interval=max(30,policy.get('check_interval_seconds',30))
    prior=request.get('startup_health',{})
    if at-prior.get('checked_at',0)<interval:return
    entries={};targets=[];slots={s['target_id']:s for s in registry['slots']}
    for snap in checks:
        tid=snap['target_id'];entry=pool['windows'].get(tid,{})
        if (not safe(snap) or entry.get('state')!='opening' or entry.get('never_submitted') is not True
                or entry.get('startup_request_id')!=request['id']):continue
        fingerprint=draft_hash(snap);old=prior.get('targets',{}).get(tid,{})
        rounds=old.get('rounds',0)+1 if old.get('fingerprint')==fingerprint else 1
        first=old.get('first_seen',at) if old.get('fingerprint')==fingerprint else at
        entries[tid]={'fingerprint':fingerprint,'rounds':rounds,'first_seen':first}
        limit=policy.get('startup_stalled_after_seconds')
        due=rounds>=2 and (limit is None or at-first>limit)
        if due:targets.append({'slot_id':slots[tid]['slot_id'],'target_id':tid,'draft_sha256':fingerprint})
    request['startup_health']={'checked_at':at,'targets':entries}
    path=root/'startup-page-restart-request.json';existing=read_record(path)
    if targets and (not existing or existing.get('state')=='complete'):
        atomic_json(path,{'state':'pending','requested':at,'authorization':'20261012-stalled-startup-reopen',
            'startup_request_id':request['id'],'window_id':registry['window_id'],'targets':targets})


def run_once(config,browser,pool,request,registry,stopping):
    root=Path(config['catalog_path']).parent
    path=root/'startup-page-restart-request.json';restart=read_record(path)
    if restart.get('state') in ('complete','partial','superseded') or not restart:return registry
    if restart.get('startup_request_id')!=request['id'] or restart.get('window_id')!=registry['window_id']:
        return registry
    from .browser_inventory import enumerate_pages
    from .shared_page_repair import _archive
    from .shared_page_repair import _records
    records,_=_records(root)
    original_targets={t['target_id'] for t in restart['targets']}
    if any(r.get('target_id') in original_targets for r in records.values()):
        raise ValueError('启动页存在请求账本，保留原页且不重发')
    pages=enumerate_pages(browser)['pages']

    def block(item,exc):
        item.update(state='blocked',blocked_at=time.time(),
            error=(type(exc).__name__+': '+str(exc))[:600])
        restart['blocked_targets']=sorted({t['target_id'] for t in restart['targets']
            if t.get('state')=='blocked'})
        atomic_json(path,restart)

    # Archive every original before clearing any composer (draft storage may be shared).
    for item in restart['targets']:
        if stopping():return registry
        if item.get('state')=='blocked' or item.get('archive_hashes'):continue
        try:
            tid=item['target_id'];entry=pool['windows'].get(tid,{})
            if (entry.get('startup_request_id')!=request['id'] or entry.get('never_submitted') is not True
                    or entry.get('state')!='opening'):raise ValueError('启动页归属或状态变化')
            require_slot(config,browser,tid)
            snap=snapshot_page(tid,pages[tid])
            if not safe(snap) or draft_hash(snap)!=item['draft_sha256']:raise ValueError('启动页内容变化，保留页面')
            folder=root/'browser-start-archives'/request['id']/'stalled-restart'/item['slot_id']
            item['archive_hashes']=_archive(folder,pages[tid],{'evidence':{'snapshot':snap}},None,
                lambda:require_slot(config,browser,tid))
            item['archive_path']=str(folder);atomic_json(path,restart)
        except Exception as exc:
            # One vanished/changed target must not hold the other nineteen
            # startup replacements behind it.
            block(item,exc)
    for item in restart['targets']:
        if stopping():return registry
        if item.get('state') in ('registered','blocked'):continue
        try:
            folder=Path(item['archive_path'])
            if any(hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected
                    for name,expected in item['archive_hashes'].items()):raise ValueError('完整归档指纹变化，不关页')
            tid=item['target_id'];slot=next(s for s in registry['slots'] if s['slot_id']==item['slot_id'])
            inventory=read_window_inventory(browser)
            if not inventory.get('complete') or inventory.get('errors'):raise ValueError('专窗清单未完整读取')
            if tid in inventory['targets']:
                require_slot(config,browser,tid)
                snap=snapshot_page(tid,pages[tid])
                atomic_json(root/'startup-restart-live-check.json',snap)
                if not safe(snap) or (snap.get('draft','').strip() and draft_hash(snap)!=item['draft_sha256']):
                    raise ValueError('关页前内容变化，保留页面')
                item.update(state='clear_intent');atomic_json(path,restart)
                if snap.get('draft','').strip():
                    from web_gpt.core import find_prompt_box
                    find_prompt_box(pages[tid]).fill('',timeout=3000)
                fresh=snapshot_page(tid,pages[tid])
                if not safe(fresh) or fresh.get('draft','').strip():raise ValueError('草稿清理未证实，不关闭')
                require_slot(config,browser,tid)
                item.update(state='close_intent');atomic_json(path,restart)
                pages[tid].close()
            item.setdefault('nonce','startup-restart-'+request['id']+'-'+item['slot_id'])
            inventory=read_window_inventory(browser)
            if tid in inventory['targets']:raise ValueError('原页仍存在，不重复补页')
            candidates=[t for t in inventory['targets'].values() if t['url']==blank_url(item['nonce'])]
            if item.get('state')=='create_intent' and not candidates:
                raise ValueError('开页回执未知，按nonce等待核对')
            item.update(state='create_intent');atomic_json(path,restart)
            def persist(candidate):
                if slot['target_id'] not in (tid,candidate['target_id']):raise ValueError('固定槽位变化')
                pool['windows'][tid].update(state='retired_replaced',replacement_target_id=candidate['target_id'],restart_archive=item['archive_path'])
                slot['target_id']=candidate['target_id']
                pool['windows'][candidate['target_id']]={'state':'opening','never_submitted':True,'startup_request_id':request['id']}
                save_pool(root/'gpt-window-pool.json',pool)
                atomic_json(root/'shared-gpt-window.json',registry)
                item.update(state='candidate_registered',new_target_id=candidate['target_id']);atomic_json(path,restart)
            result=create_in_window(browser,registry['window_id'],root=root/'browser-start-extensions',nonce=item['nonce'],
                owned_ids={s['target_id'] for s in registry['slots']},on_created=persist,stopping=stopping,timeout=10)
            if result.get('extension_uninstalled') is not True:raise ValueError('补页扩展卸载尚未证实')
            item.update(state='registered');atomic_json(path,restart)
        except Exception as exc:
            block(item,exc)
    remaining=[t for t in restart['targets'] if t.get('state') not in ('registered','blocked')]
    if remaining:
        restart.update(state='pending',blocked_targets=sorted({t['target_id'] for t in restart['targets'] if t.get('state')=='blocked'}))
    else:
        blocked=any(t.get('state')=='blocked' for t in restart['targets'])
        restart.update(state='partial' if blocked else 'complete',finished=time.time(),
            blocked_targets=sorted({t['target_id'] for t in restart['targets'] if t.get('state')=='blocked'}))
    atomic_json(path,restart)
    return registry
