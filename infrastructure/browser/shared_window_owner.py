"""Window registration and dispatch guards used only by the existing CDP owner."""
from core.api import paths__workspace_root as _workspace_root
import hashlib
import json
import os
import time
from core.api import paths__WorkspacePath as Path

from core.api import services__atomic_json as atomic_json
from .owner_browser_calls import bounded_call, _metadata_session
from .shared_browser_window import (enabled,read_window_inventory,register_window,
                                   reconcile_window,validate_registry,WindowIsolationError)


def registry_path(config):
    return Path(config['catalog_path']).parent/'shared-gpt-window.json'


def check_endpoint(registry):
    actual=registry.get('endpoint')
    expected=os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222').rstrip('/')
    if not isinstance(actual,str) or actual.rstrip('/')!=expected:
        raise WindowIsolationError('共享窗口连接地址缺失或变化，保留原登记等待核对')


def refresh_requested(config,browser,*,lock_factory,stopping,excluded_targets=()):
    """One explicit refresh of proven unsent browser-check failures; no sends."""
    from core.api import control__read_record as read_record
    from cards.api import web_card_service__owner_enabled as owner_enabled,web_card_retry__known_unsent as known_unsent
    from .browser_inventory import enumerate_pages
    from .shared_page_health import snapshot_page,_fingerprint
    from .shared_page_repair import _archive,_records,_record_cas
    root=Path(config['catalog_path']).parent;path=root/'owned-page-refresh.json';request=read_record(path)
    if not request or request.get('state')=='complete':return []
    service=read_record(root/'web-card-service.json')
    if (request.get('authorized') is not True or request.get('owner_pid')!=os.getpid()
            or service.get('pid')!=os.getpid() or not service.get('token')
            or hashlib.sha256(str(service.get('token','')).encode()).hexdigest()!=request.get('owner_token_sha256')):return []
    import re
    if (not re.fullmatch('[a-f0-9]{32}',str(request.get('id',''))) or
            not isinstance(request.get('targets'),list) or not 1<=len(request['targets'])<=20 or
            len({t['target_id'] for t in request['targets']})!=len(request['targets'])):
        raise WindowIsolationError('明确刷新清单损坏')
    authorization=root.parent/'docs/authorizations/20261015-small-package-and-login-detection.md'
    if hashlib.sha256(authorization.read_bytes()).hexdigest()!=request.get('authorization_sha256'):
        raise WindowIsolationError('明确刷新授权指纹变化')
    registry=json.loads(registry_path(config).read_text());validate_registry(registry);check_endpoint(registry)
    records,_=_records(root);results=[]
    for item in request['targets']:
        if item.get('state') in ('done','refresh_intent','refresh_unknown','blocked'):continue
        tid=item['target_id']
        if tid in excluded_targets:continue
        try:
            with lock_factory(timeout=5):
                if stopping() or not owner_enabled(config):return results
                require_slot(config,browser,tid)
                slot=next(s for s in registry['slots'] if s['slot_id']==item['slot_id'])
                if registry['window_id']!=request['window_id'] or slot['target_id']!=tid:
                    raise WindowIsolationError('刷新原槽位变化')
                page=enumerate_pages(browser)['pages'][tid];snapshot=snapshot_page(tid,page)
                item['observed_snapshot']=snapshot
                history=[r for r in records.values() if r.get('target_id')==tid]
                if any(not known_unsent(r) for r in history):raise WindowIsolationError('原请求未知或已发送，不刷新')
                def safe(s):
                    return (s.get('inspection_complete') is True and s.get('streaming') is False
                        and s.get('uploading') is False and s.get('url','').rstrip('/')=='https://chatgpt.com'
                        and not str(s.get('draft','')).strip()
                        and not any(s.get(k) for k in ('attachments','user_texts','answer_texts',
                            'answer_element_count','login','verification','quota'))
                        and (any('浏览器检查未能完成' in str(e) and '重新加载' in str(e) for e in s.get('errors',[]))
                             or s.get('composer_available') is True and not s.get('errors')))
                if not safe(snapshot):
                    evidence={k:snapshot.get(k) for k in ('inspection_complete','streaming','uploading','url',
                        'attachments','answer_element_count','login','verification','quota','composer_available','errors')}
                    evidence.update(draft_length=len(str(snapshot.get('draft','')).strip()),
                        user_count=len(snapshot.get('user_texts',[])),answer_count=len(snapshot.get('answer_texts',[])))
                    item['blocked_evidence']=evidence
                    raise WindowIsolationError('原页实时检查不满足明确刷新条件；具体阻断项见blocked_evidence')
                def guard():
                    if stopping() or not owner_enabled(config):raise WindowIsolationError('用户已暂停')
                    require_slot(config,browser,tid)
                    if not safe(fresh:=snapshot_page(tid,page)) or _fingerprint(fresh)!=_fingerprint(snapshot):
                        raise WindowIsolationError('刷新前页面证据变化')
                    live,_=_records(root)
                    if {r['_ledger_path'] for r in live.values() if r.get('target_id')==tid}!={r['_ledger_path'] for r in history}:
                        raise WindowIsolationError('刷新前原请求历史变化')
                    for r in history:_record_cas(r['_ledger_path'],r['_ledger_sha256'])
                folder=root/'owned-page-refreshes'/request['id']/item['slot_id']
                item['archive_hashes']=_archive(folder,page,{'evidence':{'snapshot':snapshot}},
                    history[-1] if history else None,guard,{r['_ledger_path']:r['_ledger_sha256'] for r in history},
                    allow_missing_unsent_prompt=True)
                guard();item.update(state='refresh_intent',intent_at=time.time());atomic_json(path,request)
                try:
                    page.reload(wait_until='commit',timeout=5000)
                    item.update(state='done',finished=time.time());results.append(tid)
                except Exception as exc:item.update(state='refresh_unknown',error=str(exc)[:300])
                atomic_json(path,request)
        except Exception as exc:
            item.update(state='blocked',error=str(exc)[:300]);atomic_json(path,request)
    request.update(state='complete' if all(t.get('state') in ('done','refresh_unknown','blocked') for t in request['targets']) else 'pending',checked_at=time.time())
    atomic_json(path,request)
    return results


def observe(config,browser,entries):
    """Register the already owned window once; observe stable slots thereafter."""
    root=Path(config['catalog_path']).parent;path=registry_path(config)
    inventory=read_window_inventory(browser)
    if path.exists():
        registry=json.loads(path.read_text());validate_registry(registry)
    else:
        registry=register_window(inventory,set(entries))
        registry.update(created=time.time(),owner_pid=os.getpid(),
                        endpoint=os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222'))
        atomic_json(path,registry)
    check_endpoint(registry)
    report=reconcile_window(registry,inventory,set(entries))
    fixed={s['target_id'] for s in registry['slots'] if s.get('target_id')}
    historical={tid for tid,e in entries.items() if tid in inventory['targets'] and tid not in fixed
                and e.get('state') in ('busy','needs_inspection','submitted','submission_started','collecting')}
    outside=set(report['collect_only_target_ids'])
    unfinished={tid for tid in outside if entries.get(tid,{}).get('state') in
                ('busy','needs_inspection','submitted','submission_started','collecting')}
    report['collect_target_ids']=sorted((set(report['collect_target_ids'])-outside)|unfinished|historical)
    report['collect_only_target_ids']=sorted(unfinished|historical)
    report.update(updated=time.time(),owner_pid=os.getpid(),slot_count=20,
                  live_fixed_slots=sum(s['state']=='present' for s in report['slots']),
                  live_bound_targets=sum(s.get('target_id') in inventory['targets'] for s in registry['slots']),
                  outside_window_slots=sum(s['state']=='outside_window' for s in report['slots']),
                  browser_total_pages=inventory['total_pages'])
    atomic_json(root/'shared-gpt-window-status.json',report,durable=False)
    request=root/'shared-window-maintenance-request.json'
    if request.exists():
        pending=json.loads(request.read_text())
        if pending.get('state')=='pending':
            expected_sha=pending.get('manifest_sha256')
            matches=not expected_sha or hashlib.sha256(path.read_bytes()).hexdigest()==expected_sha
            pending.update(state='checked' if matches else 'superseded',checked=time.time(),
                           owner_pid=os.getpid(),window_state=report['state'],created_pages=0)
            atomic_json(request,pending)
    return report


def require_slot(config,browser,tid):
    """Recheck the original target's window immediately before DOM mutations."""
    registry=json.loads(registry_path(config).read_text());validate_registry(registry)
    check_endpoint(registry)
    if tid not in {s.get('target_id') for s in registry['slots']}:
        raise WindowIsolationError('页面不在20个固定槽位中，禁止发送')
    # This is a fresh position query every time, not a cached permission. A
    # single shared metadata session removes repeated browser attach/detach RPCs.
    for retry in range(2):
        try:
            with _metadata_session(browser) as session:
                window=bounded_call(session,'send','Browser.getWindowForTarget',{'targetId':tid})['windowId']
            break
        except TimeoutError as exc:
            if retry:raise TimeoutError('原target窗口归属只读核对超时；未授予页面操作权限') from exc
    current=json.loads(registry_path(config).read_text());validate_registry(current);check_endpoint(current)
    original_slot=next(s for s in registry['slots'] if s.get('target_id')==tid)
    current_slot=next(s for s in current['slots'] if s['slot_id']==original_slot['slot_id'])
    metadata=lambda r:{k:v for k,v in r.items() if k not in ('slots','revision')}
    if current_slot!=original_slot or metadata(current)!=metadata(registry):
        raise WindowIsolationError('窗口归属检查期间登记变化；保留原页')
    if window!=registry['window_id']:
        raise WindowIsolationError('页面已移出专用窗口；只保留原请求收取，不派新任务')
    return True


def require_reusable(page,entry, *, allow_temporary_home=False):
    """A saved reply and empty composer must still match before navigation."""
    from cards.api import web_card_inputs__digest as digest
    from .page_retirement import may_retire
    from .web_card_pool import USER
    from web_gpt.core import ANSWER,STOP_BUTTON,_message_text,wait_prompt_box,_box_text
    answers=page.locator(ANSWER);stops=page.locator(STOP_BUTTON)
    saved=entry.get('raw_sha256','')
    if entry.get('state')=='ready':
        try:
            valid=bool(entry.get('raw_path')) and digest(Path(entry['raw_path']))==saved
        except OSError as exc:
            raise WindowIsolationError('复用页原回答路径不可读取，等待原账本修复') from exc
        if not valid or page.url!=entry.get('conversation_url'):
            raise WindowIsolationError('复用页的原回答指纹或会话URL变化，保留原页面')
        if not Path(entry['raw_path']).read_text().strip():
            raise WindowIsolationError('原回答文件为空占位，禁止作为完整回答复用')
    actual=hashlib.sha256(_message_text(answers.last).encode()).hexdigest() if answers.count() else ''
    users=page.locator(USER).count(); answer_count=answers.count()
    box=wait_prompt_box(page,timeout=3000)
    draft=_box_text(box)
    streaming=any(stops.nth(i).is_visible() for i in range(stops.count()))
    if draft.strip():
        from .restored_web_draft import clear
        if clear(_workspace_root()/'data',page,entry,box,draft,users,answer_count,streaming):draft=''
    url=page.url
    if allow_temporary_home and entry.get('state')=='ready_blank' and url=='https://chatgpt.com/?temporary-chat=true':
        url='https://chatgpt.com/'
    if not may_retire(entry.get('state'),'response_saved' if saved else None,url,users,answer_count,draft,streaming,actual,saved):
        raise WindowIsolationError('复用页有草稿、生成或未收齐回执，保留原页面：'+json.dumps(dict(state=entry.get('state'),url=page.url,users=users,answers=answer_count,draft_length=len(draft.strip()),streaming=streaming,saved=bool(saved)),ensure_ascii=False))
    return True
