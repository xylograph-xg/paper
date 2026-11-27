"""Persistent CDP connection; reconcile saved replies before reusing owned tabs."""
import json
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit
from core.api import catalog__Catalog as Catalog, catalog__ROOT as ROOT, catalog__now as now
from core.api import services__atomic_json as atomic_json
from .shared_pool_store import load_pool,save_pool,begin_request,failed_request,acknowledge_submitted
from cards.api import web_card_queue as queue

USER='[data-chatgpt-search-unit-key$=":user"], [data-message-author-role="user"]'
MARKER=re.compile(r'web-card-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})-')


def _seed_admission(claims):
    """Reserve next upload capacity for a runnable seed, including larger ZIPs."""
    seeds=[row for row in claims if row.get('seed_fast_lane')]
    return seeds or claims


def identify(page,attempt,expected):
    """A target alone is insufficient: require exactly one matching material turn."""
    import hashlib
    from web_gpt.core import _dense
    if not expected or attempt.get('actual_prompt_sha256')!=hashlib.sha256(expected.encode('utf-8')).hexdigest():
        raise ValueError('原提交提示指纹缺失或不一致')
    users=page.locator(USER)
    if users.count()!=1:raise ValueError('用户请求不唯一，不接受多轮混合回答')
    from .web_message_text import read_user_text
    text=read_user_text(users.first,expected)
    found=MARKER.findall(text)
    if len(found)!=1 or _dense(expected) not in _dense(text):raise ValueError('材料标识或完整提示不一致')
    if not page.url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in page.url:raise ValueError('等待正式会话URL')
    original=attempt.get('conversation_url','')
    if original.startswith('https://chatgpt.com/c/') and 'local-chatgpt' not in original and original!=page.url:
        raise ValueError('正式会话URL与原提交不一致')
    return found[0]


def normalize_json_escapes(raw):
    from cards.api import web_card_json__normalize_escapes as normalize_escapes
    return normalize_escapes(raw)


def record_channel_failure(router, exc, page=None, page_guard=None):
    """Shared channel pause/cooldown for the active pool execution path."""
    from .web_upload_bundle import UploadSizeError
    if isinstance(exc,UploadSizeError):return
    from .web_card_transport import ProviderFailure, failure_kind
    from .upload_quota import visible_notice, _reset_timestamp
    notice=None
    if page_guard:
        try:page_guard()
        except Exception:page=None
    if page is not None:
        try:notice=visible_notice(page)
        except Exception:pass
    kind=failure_kind(str(exc))
    if kind!='verification' and notice:kind=notice.get('kind') or 'quota'
    if kind in ('quota','network','verification'):
        reset=_reset_timestamp(notice)
        router.block(ProviderFailure(str(exc),'chatgpt',kind,False,reset,reset_evidence=notice))


def record_upload_network_failure(router, event):
    """A proven PUT transport failure cools new dispatch, never its old request.

    Generic ERR_FAILED/ABORTED may be an intentional cancellation or protocol
    experiment; only original, attributed transport errors reach this gate.
    """
    if (event.get('phase')!='requestfailed' or event.get('method')!='PUT' or
            event.get('attributed') is not True or not event.get('upload_attempt_id') or
            not str(event.get('host','')).endswith(('.oaiusercontent.com','.blob.core.windows.net'))):
        return False
    code=event.get('failure','')
    if not re.fullmatch(r'net::ERR_(?:HTTP2_[A-Z_]+|NETWORK_CHANGED|INTERNET_DISCONNECTED|CONNECTION_[A-Z_]+|TIMED_OUT|NAME_NOT_RESOLVED)',code):
        return False
    from .web_card_transport import ProviderFailure
    router.block(ProviderFailure('附件原PUT传输中断：'+code+'；'+event['host']+
        '；冷却仅限制新派发，不证明原请求未发送','chatgpt','network',False))
    return True


def refresh_browser_pages(browser):
    """Pump CDP events even when there are no pages to interact with."""
    from .owner_browser_calls import bounded_call
    session=bounded_call(browser,'new_browser_cdp_session')
    try:bounded_call(session,'send','Target.getTargets')
    finally:bounded_call(session,'detach')


def pump_owner_wait(pw,observer):
    """A driver wait failure releases only this connection, preserving Chrome."""
    import asyncio
    pause=asyncio.sleep(.5)
    try:pw._sync(pause)
    except Exception as exc:
        pause.close()
        if observer:observer.stop()
        try:pw.stop()
        except Exception:pass
        return '驱动等待中断：'+str(exc)[:200]
    return None


def keep_connection_after_error(browser, exc):
    """Local evidence/control failures do not disconnect the observer."""
    from playwright.sync_api import Error as BrowserError
    if browser is None or isinstance(exc,BrowserError):return False
    try:return browser.is_connected()
    except Exception:return False


def owner_error_status(pid, token, exc, *, preserve, loaded_version):
    """Keep the startup version and actual failure frames, without stale activity."""
    import traceback
    return dict(pid=pid, token=token,
                state='waiting_evidence' if preserve else 'waiting_browser',
                updated=time.time(), error=type(exc).__name__+': '+str(exc)[:300],
                error_traceback=traceback.format_exception(type(exc),exc,exc.__traceback__,limit=8),
                code_version=loaded_version, mode='persistent_cdp_pool')


def refresh_concurrency(config):
    """Invalid controls block new work while original replies remain collectable."""
    from core.api import concurrency_control__apply as apply
    from core.api import control__InvalidControl as InvalidControl
    try:apply(config)
    except (InvalidControl,ValueError,OSError) as exc:return '并发控制需核对：'+str(exc)[:300]
    return None


def reconcile_blank_pages(root,pages,entries,latest,dispatch_ids,errors,*,read_page,on_error=None,save=atomic_json,record_index=None):
    """Check each owned homepage independently; never change its DOM or ledger.

    ``read_page`` must return users, answers and composer text after the channel
    verification check. An unavailable composer protects only that target; the
    caller can still collect and allocate other pages on the same connection.
    """
    from .web_pool_open import eligible
    root=Path(root);snapshots={};failures={};failed=set()

    def protect(tid,message):
        entries.setdefault(tid,{}).update(state='needs_inspection',error=message[:500])
        dispatch_ids.discard(tid)

    def inspect(tid):
        if tid in failures:raise failures[tid]
        if tid not in snapshots:
            try:snapshots[tid]=read_page(pages[tid])
            except Exception as exc:failures[tid]=exc;raise
        return snapshots[tid]

    def failed_page(tid,exc):
        protect(tid,'空白页核对失败，保留原页与回执：'+str(exc))
        if tid not in failed:
            failed.add(tid);errors.append(tid+': 空白页核对失败：'+str(exc)[:200])
            if on_error:on_error(exc,pages[tid])

    adoption_paths=[root/'gpt-page-adoption.json',*(root/'browser-page-adoptions').glob('*.json')]
    for adoption_path in adoption_paths:
        if not adoption_path.exists():continue
        tid=None;adoption=None
        try:
            adoption=json.loads(adoption_path.read_text());tid=adoption.get('target_id')
            if adoption.get('state') not in ('pending','opening') or tid not in dispatch_ids:continue
            page=pages[tid]
            if page.url.rstrip('/')!='https://chatgpt.com':continue
            snapshot=inspect(tid)
            record=latest.get(tid)
            blank=eligible(tid,page.url,snapshot['users'],snapshot['answers'],snapshot['draft'],record,entries.get(tid)) and (
                not record or record.get('send_click_started') is False)
            if blank:
                entries.setdefault(tid,{}).update(state='ready_blank',adopted=time.time(),origin='explicit_open_gpt')
                adoption.update(state='adopted',finished=time.time())
            else:
                message='页面有草稿/历史/未确认提交，不自动接管'
                protect(tid,message);adoption.update(state='needs_inspection',error=message)
            save(adoption_path,adoption)
        except Exception as exc:
            if tid in pages:
                failed_page(tid,exc)
                if isinstance(adoption,dict):
                    adoption.update(state='needs_inspection',error='空白页核对失败：'+str(exc)[:500])
                    save(adoption_path,adoption)
            else:errors.append('页面接管记录需核对：'+str(exc)[:200])

    for tid,page in pages.items():
        if tid not in entries or tid not in dispatch_ids:continue
        try:
            if page.url.rstrip('/')!='https://chatgpt.com':continue
            snapshot=inspect(tid)
            if snapshot['users']:continue
            record=latest.get(tid,{})
            known_unsent=record.get('state') in ('not_sent','deferred') and record.get('send_click_started') is False
            verified_history=(record_index is not None and entries[tid].get('state')=='ready_blank' and
                time.time()-entries[tid].get('blank_history_verified_at',0)<60 and
                entries[tid].get('blank_history_ledger_hashes')=={p:r['_ledger_sha256'] for p,r in record_index.items() if r.get('target_id')==tid})
            if (record and not known_unsent and not verified_history) or (not record and entries[tid].get('state') not in ('ready','ready_blank')):
                protect(tid,'原请求尚未证实结束，空白页不能释放')
                continue
            if snapshot['answers'] or snapshot['draft'].strip():
                protect(tid,'页面有回答或草稿，保留原页，不释放')
                continue
            entries[tid]['state']='ready_blank'
        except Exception as exc:failed_page(tid,exc)
    return failed


def maintain_shared_backlog(config,catalog,entries,live_targets,observation,latest,*,inventory_complete,maintenance,
                            owner_pid=None,at=None,excluded_targets=(),checkpoint=None):
    """Local bounded queue maintenance; no browser calls or implicit resumes."""
    import sqlite3
    from .shared_page_backlog import reconcile
    from .shared_workflow_queue import active_targets,refill_backlog
    if not live_targets:
        return {'state':'waiting_pages','eligible_pages':0,'current_tasks':0,'queued_tasks':0,
                'inventory_complete':bool(inventory_complete),'bindings_preserved':True}
    at=time.time() if at is None else at
    current=active_targets(catalog,entries,live_targets,observation,latest,owner_pid=os.getpid() if owner_pid is None else owner_pid,at=at)
    # Fixed-window presence alone does not make a target schedulable. The
    # owner's health/repair gate also governs inventory, binding and reservation.
    # Keep all registered targets in the view so protected pages stay visible,
    # without rewriting original pool ownership or a historical receipt.
    excluded=set(excluded_targets)
    destinations={tid:{**entry,'eligible':False} if tid in excluded else entry
                  for tid,entry in entries.items()}
    def replenish(cat,cfg,**request):
        if at-maintenance.get('last_refill',float('-inf'))<60:
            return {'state':'waiting_refill_interval','next_at':maintenance['last_refill']+60}
        maintenance['last_refill']=at
        try:return refill_backlog(cat,cfg,**request)
        except Exception as exc:return {'state':'refill_error','error':str(exc)[:500]}
    try:
        return reconcile(config,catalog,destinations,live_targets,current,inventory_complete=inventory_complete,
                         refill_callback=replenish,now=at,checkpoint=checkpoint,initialize=checkpoint is None)
    except sqlite3.OperationalError as exc:
        if (getattr(exc,'sqlite_errorcode',0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
            raise
        return {'state':'waiting_backlog_writer','inventory_complete':False,'bindings_preserved':True}


def shared_upload_limit(config):
    policy=config.get('web_cards',{}).get('parallel_uploads',{})
    if policy.get('enabled') is not True:return 1
    limit=policy.get('max_pages',5)
    if type(limit) is not int or not 1 <= limit <= 5:raise ValueError('并行上传上限必须为1–5')
    return limit




def upload_entry_is_blocked(root):
    """Persistent admission gate from durable upload results, not callback flags."""
    path=Path(root)/'upload-attempt-events.jsonl'
    if not path.exists():return False
    lines=[]
    try:
        with path.open('rb') as f:
            f.seek(0,2);size=f.tell();f.seek(max(0,size-200000));lines=f.read().decode('utf-8','replace').splitlines()
    except OSError:return False
    finished=[]
    for line in reversed(lines):
        try:record=json.loads(line)
        except (ValueError,TypeError):continue
        if record.get('event')!='upload_finished':continue
        finished.append(record)
        if len(finished)>=3:break
    if len(finished)<3:return False
    if any(r.get('result')=='ok' for r in finished):return False
    if not all(r.get('result')=='failed' and r.get('failure_kind')=='entry_not_ready' for r in finished):return False
    last=finished[0].get('finished_at')
    return type(last) in (int,float) and time.time()-last<300


def upload_budget_targets(jobs, health):
    """A timed-out client does not release a still-uploading native page."""
    native = {tid for tid,value in health.get('pages',{}).items()
              if value.get('evidence',{}).get('snapshot',{}).get('inspection_complete') is True
              and value.get('evidence',{}).get('snapshot',{}).get('uploading') is True
              and getattr(jobs,'released',{}).get(tid,0) < value.get('evidence',{}).get('snapshot',{}).get('checked_at',float('inf'))}
    return (getattr(jobs,'budget_targets',jobs.targets) if jobs else set()) | native


def shared_submission_status(config, *, at=None):
    """Page health and provider permission are independent dispatch gates."""
    from core.api import control__provider_decisions as provider_decisions, control__read_record as read_record, control__InvalidControl as InvalidControl
    root=Path(config['catalog_path']).parent
    decision=provider_decisions(root,policy=config['web_cards'],at=at)['chatgpt']
    try:block=read_record(root/'web-provider-control.json').get('chatgpt',{})
    except InvalidControl:block={}
    if not isinstance(block,dict):block={}
    return {'allowed':decision.allowed,'state':decision.state,'reason':decision.reason,
            'retry_not_before':decision.expires_at,'notice':block.get('error','') if not decision.allowed else '',
            'explicit_reset':block.get('explicit_reset',False) if not decision.allowed else False}


def run_pool(config):
    from .web_card_transport import Router,DeferredWeb,ProviderFailure,submit_gpt_background,collect_owned,require_no_verification
    from cards.api import web_card_service__publish_saved as publish_saved, web_card_service__enabled as enabled, web_card_service__owner_enabled as owner_enabled, web_card_service__code_version as code_version
    from cards.api import web_card_inputs__digest as digest
    root=Path(config['catalog_path']).parent;catalog=Catalog(config['catalog_path'])
    loaded_version=code_version()
    sys.path.insert(0,os.environ.get('WEB_GPT_IMPORT_ROOT','/Users/xiaoyanhao/project/chatgpt_playwright'))
    from playwright.sync_api import sync_playwright
    from web_gpt import create_session
    from web_gpt.core import ANSWER,STOP_BUTTON,_message_text,_dense
    from .web_page_observer import responsive_lock
    submission_lock=lambda timeout=180:responsive_lock(pw,timeout)
    router=Router(root,policy=config['web_cards']);stop=False;token=secrets.token_hex(24);last_retry=0;last_health=0;health={};selection={};errors=[];retirement_cache={}
    def halt(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,halt);signal.signal(signal.SIGINT,halt)
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from cards.api import web_card_service__process_job as process_job
    qwen_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='fixed-qwen');qwen_future=None
    browser=None;pw=None;observer=None;upload_jobs=None;last_review_reconcile=0
    from core.api import cooperative_sql__set_checkpoint as set_db_checkpoint
    from .attempt_history import set_scan_checkpoint
    checkpoint_installed=False;previous_checkpoint=None
    previous_scan_checkpoint=None
    def database_checkpoint():
        if stop:raise InterruptedError('原所有者正常退出，保留未完成任务')
        from greenlet import getcurrent
        if pw is not None and getcurrent() is not pw._dispatcher_fiber:
            pw._sync(__import__('asyncio').sleep(0))
    upload_lane=None;dispatch_view={};collecting_targets=set()
    @contextmanager
    def maintenance_target(tid):
        if tid in collecting_targets or upload_jobs and tid in upload_jobs.targets:
            yield False;return
        collecting_targets.add(tid)
        try:yield True
        finally:collecting_targets.discard(tid)
    parallel_uploads=shared_upload_limit(config)
    from .shared_browser_window import enabled as shared_enabled,WindowIsolationError
    shared=shared_enabled(config)
    from .shared_page_backlog import enabled as backlog_enabled
    mixed_backlog=shared and backlog_enabled(config)
    if mixed_backlog:
        from .shared_page_backlog import install as install_backlog
        install_backlog(catalog)
    backlog_maintenance={}
    from .shared_window_owner import observe as observe_window,require_slot,require_reusable
    from .shared_page_dispatch import dispatch
    from .web_page_queue import MaterialProducer,assign,next_ready
    producer=MaterialProducer(config);producer.start()
    from correction.api import card_correction_queue__allows_web_job as allows_web_job, card_correction_queue__web_job_kind as web_job_kind
    correction_lane=None
    if config.get('card_correction',{}).get('enabled'):
        from correction.api import card_correction_lane__CorrectionLane as CorrectionLane
        correction_lane=CorrectionLane(config)
    review_lane=None
    if config.get('card_review',{}).get('enabled'):
        from review.api import card_review_lane__ReviewLane as ReviewLane
        review_lane=ReviewLane(config)
    def publish_upload_status():
        from core.api import control__read_record as read_record
        record=read_record(root/'web-card-service.json')
        if record.get('pid')!=os.getpid() or record.get('token')!=token:return
        record.update(updated=time.time(),upload_parallel_limit=parallel_uploads,
            uploading_pages=len(upload_jobs.targets),uploading_targets=sorted(upload_jobs.targets),
            upload_budget_used=len(upload_budget_targets(upload_jobs,dispatch_view.get('health',{}))),
            upload_admitted_zip_bytes=upload_jobs.admitted_zip_bytes,upload_zip_byte_limit=upload_jobs.byte_limit,
            retained_upload_targets=sorted(upload_jobs.retained),
            submission_lock_metrics=dict(vars(pw).get('_paper_submission_metrics',{})),
            upload_dispatch_worker='independent_owner_loop',response_collection_worker='independent_observer_loop')
        atomic_json(root/'web-card-service.json',record,durable=False)
    def claim_upload_size(row):
        """Read only the already frozen packet size for admission ordering."""
        try:
            lane=row.get('lane');pid=row.get('paper_id');jid=row.get('job_id')
            folder=(root/'card_reviews'/str(pid)/str(jid) if lane=='review'
                    else root/'web_cards'/str(pid))
            packet=json.loads((folder/'packet.json').read_text())
            size=packet.get('upload_bundle',{}).get('size')
            return size if type(size) is int and size>0 else None
        except (OSError,ValueError,TypeError,KeyError):
            return None

    def execute_card_job(job,candidate,pool,entries,pages,guard,resource_status,active,review_active,correction_active):
        lane_kind=web_job_kind(job)
        pid=job['paper_id'];folder=root/'web_cards'/pid;paper=catalog.get(pid)
        submission_page=None;submission_attempt=None;page_touched=False;original_entry=None;packet=None
        # Publish the active preparation before slow attachment uploads.
        # Otherwise a newly restarted keeper still appears stopped.
        atomic_json(root/'web-card-service.json',dict(pid=os.getpid(),token=token,state='running',stage='preparing_submission',updated=time.time(),workers=active,review_workers=review_active,preparing=1,mode='persistent_cdp_pool',pool_ready=sum(e.get('state') in ('ready','ready_blank') for e in entries.values()),**resource_status,config_path=config['_config_path']))
        try:
            target=Path(config['studio_library_root'])/pid
            with catalog.connect() as db:human=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(pid,)).fetchone()
            from cards.api import web_card_rework__authorization as authorization
            rework=authorization(job,paper)
            if rework and rework.get('kind') in ('source_review','manual_seed_trial') and (human or paper['decision']!='unreviewed'):raise ValueError('入队后出现人工决定，只保留修正建议')
            if not rework and (paper['decision']!='unreviewed' or paper.get('card_path') or human or (target/'card.json').exists()):raise ValueError('已有卡片或人工决定，不覆盖')
            if any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):raise ValueError('身份/版本/范围待核对')
            from cards.api import web_card_rework__submission_history as submission_history
            decision=submission_history(catalog,job,folder)
            if not decision.allowed:raise ValueError(decision.reason)
            folder.mkdir(parents=True,exist_ok=True);packet_path=folder/'packet.json'
            if not packet_path.exists():raise ValueError('前置材料未就绪，不在发送循环中临时准备')
            packet=json.loads(packet_path.read_text())
            from .original_upload_http1 import material_intent
            if material_intent(root,lane_kind,candidate.get('job_id'),pid,packet.get('upload_bundle',{}).get('zip_sha256')):
                raise ValueError('原上传已有持久意图或预留，保留原回执，不重复进入页面流程')
            from .web_upload_bundle import check_zip_size
            check_zip_size(packet.get('upload_bundle',{}))
            if digest(paper['asset_path'])!=packet['source_original_sha256']:raise ValueError('原文指纹变化')
            for name,h in packet['input_hashes'].items():
                if digest(folder/name)!=h:raise ValueError('冻结材料指纹变化')
            tid=candidate['target_id'];page=pages[tid];submission_page=page;path=folder/'chatgpt/attempt.json';path.parent.mkdir(parents=True,exist_ok=True)
            a=dict(provider='chatgpt',state='ready',target_id=tid,reused_window=True,inputs=packet['input_hashes'],created=time.time(),send_click_started=False,kind=lane_kind,paper_id=pid,owner_pid=os.getpid(),owner_token=token);submission_attempt=a
            if lane_kind=='correction':a['correction_id']=json.loads(job['selection'])['rework']['correction_id']
            # Preserve the pause/stop boundary before any page inspection,
            # without keeping the lock throughout the slow target-only reads.
            with submission_lock(timeout=30):
                if stop or not allows_web_job(config,job):raise DeferredWeb('Paused before page inspection')
            require_reusable(page,entries[tid])
            with submission_lock(timeout=30):
                if stop or not allows_web_job(config,job):raise DeferredWeb('此任务已暂停，保留原页面，未导航或上传')
                if guard:guard(tid)
                if mixed_backlog:
                    from .shared_workflow_queue import check_claim
                    check_claim(catalog,lane_kind,candidate['job_id'],tid)
                from .web_submission_guard import check as check_submission
                check_submission(catalog,config,job,folder,packet)
                original_entry=dict(entries[tid])
                begin_request(entries[tid],lane_kind,pid,correction_id=
                    json.loads(job['selection'])['rework']['correction_id'] if lane_kind=='correction' else None)
                save_pool(root/'gpt-window-pool.json',pool)
                page_touched=True
            if stop or not allows_web_job(config,job):raise DeferredWeb('Paused before page preparation')
            if guard:guard(tid)
            from .reusable_home import prepare as prepare_home
            a['page_preparation']=prepare_home(page,saved=original_entry)
            from .gpt_model_policy import configure_session
            a.update(stage='model_configuration');atomic_json(path,a)
            s=configure_session(page,root)
            a.update(stage='upload_preparation',settings=s.settings,conversation_url=page.url);atomic_json(path,a)
            from .web_upload_bundle import prepare_web_upload
            bundle,prompt=prepare_web_upload(folder,packet)
            a['upload_bundle']=bundle;atomic_json(path,a)
            (path.parent/'prompt-actual.txt').write_text(prompt)
            a['actual_prompt_sha256']=digest(path.parent/'prompt-actual.txt');atomic_json(path,a)
            def before_send():
                if guard:guard(tid)
                if stop or not allows_web_job(config,job):raise DeferredWeb('此任务已暂停，未点击发送')
                if router.choose()!='chatgpt':raise DeferredWeb('当前附件通道不可用，未点击发送')
                if mixed_backlog:check_claim(catalog,lane_kind,candidate['job_id'],tid)
                check_submission(catalog,config,job,folder,packet)
                a.update(state='submission_started',send_click_started=True);atomic_json(path,a)
            def identified(identifier,detail):
                a.update(upload_attempt_id=identifier,upload_diagnostic=detail);atomic_json(path,a)
            def stage(name):
                a.update(stage=name)
                if not a.get('send_click_started'):atomic_json(path,a)
            prior=submit_gpt_background(s,prompt,[bundle['zip_path']],on_before_send=before_send,
                upload_timeout=(config['web_cards'].get('upload_large_settle_timeout_seconds',
                    config['web_cards'].get('upload_settle_timeout_seconds',180))
                    if isinstance(bundle.get('size'),int) and bundle['size']>=config['web_cards'].get('parallel_uploads',{}).get('large_zip_threshold',8_000_000)
                    else config['web_cards'].get('upload_settle_timeout_seconds',180))*1000,stopping=lambda:stop or bool(upload_jobs and upload_jobs.closing) or not allows_web_job(config,job),lock_factory=submission_lock,parallel_upload=bool(upload_jobs),
                page_guard=(lambda:guard(tid)) if guard else None,
                upload_context={'lane':lane_kind,'paper_id':pid,'job_id':candidate.get('job_id'),
                    'local_file_paths':config['web_cards'].get('parallel_uploads',{}).get('local_file_paths') is True,
                    'target_id':tid,'bundle':bundle,'on_identified':identified,'on_stage':stage})
            from .web_card_transport import commit_submitted
            commit_submitted(path,a,prior_count=prior,conversation_url=page.url)
            acknowledge_submitted(root/'gpt-window-pool.json',pool,tid,a)
            with catalog.connect() as db:
                ack=db.execute("UPDATE web_card_jobs SET state='submitted',provider='chatgpt',folder=?,error=?,updated=? WHERE paper_id=? AND state='preparing'",
                    (str(folder),'已发送，等待原会话回答',now(),pid)).rowcount
            if lane_kind=='correction':
                correction_active+=1
                if correction_lane and ack:correction_lane.state(job,'submitted')
            else:active+=1
            return True
        except Exception as exc:
            import traceback
            from .owner_browser_calls import _exception_record
            from .web_upload_bundle import UploadSizeError
            detail=_exception_record(exc,submission_attempt.get('stage','lease_preflight') if submission_attempt else 'lease_preflight')
            if submission_attempt is not None and a.get('send_click_started') and path.is_file():
                current=json.loads(path.read_text())
                if current.get('state')=='response_saved':
                    from .web_card_transport import commit_submitted
                    commit_submitted(path,a,prior_count=None,conversation_url=submission_page.url)
                    a['submission_followup_error']=detail;atomic_json(path,a)
                    return True
            if submission_attempt is not None and a.get('state')=='submitted':
                a['queue_ack_error']=detail;atomic_json(path,a);return True
            if submission_attempt is not None:
                (path.parent/'error-trace.txt').write_text(traceback.format_exc())
            if original_entry is not None:
                failed_request(entries[tid],original_entry,page_touched=page_touched,error=exc)
            if submission_attempt is not None:
                a.update(state='needs_inspection' if a.get('send_click_started') else 'not_sent',finished=time.time(),**detail)
                try:
                    if a.get('send_click_started'):a['conversation_url']=submission_page.url
                    else:a['observed_page_url']=submission_page.url
                    if not isinstance(exc,WindowIsolationError):
                        if guard:guard(tid)
                        (path.parent/'error-page.txt').write_text(submission_page.locator('body').inner_text(timeout=3000))
                        if a.get('stage')=='model_configuration':
                            (path.parent/'model-configuration-dom.html').write_text(submission_page.locator('body').evaluate('(el)=>el.outerHTML')[:200000])
                except Exception:pass
                if a.get('send_click_started') and path.is_file() and json.loads(path.read_text()).get('state')=='response_saved':
                    from .web_card_transport import commit_submitted
                    commit_submitted(path,a,prior_count=None,conversation_url=submission_page.url)
                    a['submission_followup_error']=detail;atomic_json(path,a);return True
                atomic_json(path,a)
            if original_entry is not None and page_touched:
                try:save_pool(root/'gpt-window-pool.json',pool)
                except Exception as pool_error:errors.append('故障页状态写入待核对：'+str(pool_error)[:200])
            lane_enabled = enabled(config) if lane_kind=='cards' else __import__('correction.api',fromlist=['card_correction_queue']).card_correction_queue.enabled(config)
            paused_unsent=(isinstance(exc,DeferredWeb) and (stop or not lane_enabled)
                and (submission_attempt is None or not a.get('send_click_started')))
            if paused_unsent:
                if submission_attempt is not None and path.exists():
                    import shutil
                    archived=folder/'history'/('paused-before-send-'+str(time.time_ns()))
                    archived.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(path.parent),str(archived))
                queue.update(catalog,pid,state='queued',error='用户暂停，未发送待办保留')
                if mixed_backlog and not page_touched:
                    from .shared_workflow_queue import rollback_claim
                    rollback_claim(catalog,lane_kind,candidate['job_id'],candidate['target_id'])
            elif isinstance(exc,WindowIsolationError) and not page_touched:
                queue.update(catalog,pid,state='queued',retry_at=time.time()+30,error='页面发送前检查未通过，未触碰材料：'+str(exc)[:500])
            else:queue.update(catalog,pid,state='failed' if isinstance(exc,UploadSizeError) or submission_attempt is not None and a.get('state')=='not_sent' else 'needs_inspection',error=detail['error'])
            if mixed_backlog and not page_touched and not paused_unsent:
                from .shared_claim_recovery import release_untouched
                release_untouched(catalog,lane_kind,candidate['job_id'],candidate['target_id'])
            errors.append(detail['error'][:300])
            if not isinstance(exc,WindowIsolationError):
                record_channel_failure(router,exc,submission_page,
                    page_guard=(lambda:guard(tid)) if guard and submission_page is not None else None)
            if upload_jobs:
                from .owner_upload_jobs import unstarted_proof
                proof=unstarted_proof(submission_attempt,page_touched=page_touched,
                    local_file_paths=config['web_cards'].get('parallel_uploads',{}).get('local_file_paths') is True)
                if proof is not None:
                    proof.update(paper_id=pid,job_id=candidate.get('job_id'),
                        admission_zip_sha256=(packet or {}).get('upload_bundle',{}).get('zip_sha256'))
                    upload_jobs.note_unstarted(candidate['target_id'],proof)

    def refill_uploads():
        """Independent admission lane; all DOM still belongs to this owner."""
        if stop or not upload_jobs or upload_jobs.closing or not dispatch_view or not upload_jobs.available:return
        if upload_entry_is_blocked(root):return
        if refresh_concurrency(config) or not owner_enabled(config):return
        from core.api import control__read_record as read_record
        request=read_record(root/'web-card-stop.json')
        if request.get('pid')==os.getpid() and request.get('token')==token:return
        registry=read_record(root/'shared-gpt-window.json')
        if registry!=dispatch_view['registry']:return
        observation=read_record(root/'web-page-observer.json')
        if observation.get('owner_pid')!=os.getpid() or not 0<=time.time()-observation.get('updated',0)<30:return
        window_id=registry.get('window_id')
        registered={s['target_id'] for s in registry['slots']}
        checked={p['target_id'] for p in observation.get('pages',[])
            if p.get('window_observed') is True and p.get('window_id')==window_id
            and 0<=time.time()-p.get('window_checked_at',0)<30}
        checked.intersection_update(registered)
        if not checked:return
        status=shared_submission_status(config)
        if not status['allowed']:return
        current_pool=load_pool(root/'gpt-window-pool.json');current_entries=current_pool['windows']
        current_pages={tid:page for tid,page in dispatch_view['pages'].items() if tid in checked}
        current_health=dispatch_view['health']
        upload_jobs.release_observed(current_health)
        from .shared_workflow_queue import backlog_dispatch,claim_ready
        from .shared_claim_recovery import release_untouched
        launched=[]
        for _ in range(parallel_uploads):
            if not upload_jobs.available or len(upload_budget_targets(upload_jobs,current_health))>=parallel_uploads:break
            if not shared_submission_status(config)['allowed']:break
            allocation=backlog_dispatch(catalog,config,current_entries,dispatch_view['eligible'],dispatch_view['backlog'],
                inventory_complete=True,excluded_targets=upload_jobs.budget_targets|collecting_targets|(registered-checked),
                pending_uploads=upload_jobs.pending_targets_by_lane)
            claims=_seed_admission([row for row in allocation['claim_order']
                if row['target_id'] in current_pages and (row['lane']!='review' or review_lane)])
            candidates=[]
            for row in claims:
                if row['lane']=='review' and not review_lane:continue
                packet_path=(root/'card_reviews'/row['paper_id']/row['job_id']/'packet.json' if row['lane']=='review'
                             else root/'web_cards'/row['paper_id']/'packet.json')
                try:
                    bundle=json.loads(packet_path.read_text()).get('upload_bundle',{})
                    size=bundle.get('size')
                except (OSError,ValueError,TypeError):bundle={};size=None
                if upload_jobs.can_accept(size):
                    candidates.append((row,size,bundle))
            if not candidates:break
            claim,zip_bytes,admission_bundle=candidates[0];tid=claim['target_id'];lane=claim['lane']
            packet_path=(root/'card_reviews'/claim['paper_id']/claim['job_id']/'packet.json' if lane=='review'
                         else root/'web_cards'/claim['paper_id']/'packet.json')
            live_guard=lambda target:require_slot(config,browser,target)
            active_counts=allocation['active']
            resource=dict(dispatch_view['resources'])
            if lane=='review':
                if not review_lane:break
                options={'allowed_targets':{tid},'parallel_limit':allocation['budget']['review'],
                    'page_guard':live_guard,'job_id':claim['job_id'],'assigned_target_id':tid,
                    'use_backlog':True,'parallel_upload':True,
                    'on_submitted':lambda receipt,tid=tid,pool=current_pool:
                        acknowledge_submitted(root/'gpt-window-pool.json',pool,tid,receipt),
                    'on_unstarted':lambda proof,tid=tid,claim=dict(claim),bundle=dict(admission_bundle):
                        upload_jobs.note_unstarted(tid,{**proof,'job_id':claim['job_id'],'paper_id':claim['paper_id'],
                            'admission_zip_sha256':bundle.get('zip_sha256')}),
                    'persist_pool':lambda pool=current_pool:save_pool(root/'gpt-window-pool.json',pool)}
                args=(dict(current_pages),current_entries,active_counts['review'],dict(options))
                started=upload_jobs.start(tid,lambda args=args:review_lane.submit(args[0],args[1],args[2],router,
                    submission_lock,lambda:stop or upload_jobs.closing,**args[3]),lane=lane,zip_bytes=zip_bytes)
            else:
                job=claim_ready(catalog,config,lane=lane,job_id=claim['job_id'],paper_id=claim['paper_id'],target_id=tid,assigned=True)
                if job is None:break
                args=(job,dict(claim),current_pool,current_entries,dict(current_pages),live_guard,resource,
                      active_counts['cards'],active_counts['review'],active_counts['correction'])
                started=upload_jobs.start(tid,lambda args=args:execute_card_job(*args),lane=lane,zip_bytes=zip_bytes)
                if not started:release_untouched(catalog,lane,claim['job_id'],tid)
            if not started:break
            launched.append({'target_id':tid,'lane':lane,'job_id':claim['job_id']})
        if launched:
            atomic_json(root/'owner-upload-dispatch.json',{'owner_pid':os.getpid(),'updated':time.time(),
                'window_id':window_id,'launched':launched,'upload_parallel_limit':parallel_uploads,
                'upload_budget_used':len(upload_budget_targets(upload_jobs,current_health))},durable=False)
            publish_upload_status()

    atomic_json(root/'web-card-service.json',dict(pid=os.getpid(),token=token,state='waiting_browser',
        stage='connecting',code_version=loaded_version,updated=time.time(),workers=0,review_workers=0,mode='persistent_cdp_pool',config_path=config['_config_path']),durable=False)
    try:
        while not stop:
            errors=[];allocation={}
            try:
                concurrency_error=refresh_concurrency(config)
                if concurrency_error:errors.append(concurrency_error)
                stop_request=__import__('core.api',fromlist=['control']).control.read_record(root/'web-card-stop.json')
                if stop_request.get('pid')==os.getpid() and stop_request.get('token')==token:break
                if not owner_enabled(config):break
                if shared:
                    from .browser_start_request import run_once as start_requested_browser
                    start_requested_browser(config)
                from .web_media_storage import require_config_storage
                try:require_config_storage(config)
                except OSError as exc:
                    atomic_json(root/'web-card-service.json',{'pid':os.getpid(),'token':token,'state':'waiting_storage','updated':time.time(),'error':str(exc)},durable=False)
                    time.sleep(1)
                    continue
                if browser is None or not browser.is_connected():
                    if pw is None:
                        pw=sync_playwright().start()
                        if not checkpoint_installed:
                            previous_checkpoint=set_db_checkpoint(database_checkpoint)
                            previous_scan_checkpoint=set_scan_checkpoint(database_checkpoint)
                            checkpoint_installed=True
                        from . import upload_trace
                        from .web_page_observer import PageObserver
                        upload_trace.configure(root)
                        from .original_upload_http1 import configure as configure_upload_probe
                        configure_upload_probe(root,pw,config['web_cards'].get('original_put_http1',{}))
                        observer=PageObserver(root,pw)
                        observer.on_upload_network_failure=lambda event:record_upload_network_failure(router,event)
                        observer.start()
                        if shared and parallel_uploads>1:
                            from .owner_upload_jobs import OwnerUploadJobs
                            upload_policy=config['web_cards'].get('parallel_uploads',{})
                            upload_jobs=OwnerUploadJobs(pw,parallel_uploads,
                                byte_limit=upload_policy.get('max_total_zip_bytes'),
                                large_limit=upload_policy.get('max_large_pages'),
                                large_threshold=upload_policy.get('large_zip_threshold',8_000_000))
                            if mixed_backlog:
                                from .owner_work_lane import OwnerWorkLane
                                upload_lane=OwnerWorkLane(pw,refill_uploads,interval=5);upload_lane.start()
                    browser=pw.chromium.connect_over_cdp(os.environ.get('WEB_GPT_CDP_URL','http://127.0.0.1:9222'),timeout=30000,no_defaults=True)
                selection=dict(producer.selection) # A slow/locked discovery cannot skip observation or collection.
                refresh_browser_pages(browser)
                if shared and (root/'shared-workbench-move.json').exists():
                    from .shared_workbench_move import run_once as move_workbench, pending as move_pending
                    try:
                        if move_pending(config):
                            with submission_lock(timeout=5):move_workbench(config,browser,stopping=lambda:stop)
                    except Exception as exc:errors.append('工作台后台移窗：'+str(exc)[:300])
                pool=load_pool(root/'gpt-window-pool.json');entries=pool['windows']
                if shared:
                    from .shared_window_owner import refresh_requested
                    try:refresh_requested(config,browser,lock_factory=submission_lock,stopping=lambda:stop,
                                          excluded_targets=upload_jobs.targets if upload_jobs else ())
                    except Exception as exc:errors.append('明确刷新原页：'+str(exc)[:300])
                    from .shared_window_start import run_once as initialize_start_window
                    try:initialize_start_window(config,browser,pool,submission_lock,lambda:stop)
                    except Exception as exc:
                        # Startup/replacement trouble must not bypass the live
                        # observer and the health checks of the remaining pages.
                        errors.append('启动页维护：'+str(exc)[:500])
                health_policy=config['web_cards'].get('shared_window',{}).get('health_repair',{})
                if not concurrency_error and shared and health_policy.get('enabled') and time.monotonic()-last_health>=health_policy.get('check_interval_seconds',30):
                    from .shared_page_repair import run_once as repair_pages
                    retirement_cache={}
                    def recover_checked_page(tid, page_health):
                        with catalog.connect() as db:
                            if not db.execute("SELECT 1 FROM shared_page_backlog WHERE target_id=? AND state='claimed'",(tid,)).fetchone():
                                return []
                        from .shared_claim_recovery import recover_claims
                        checked=page_health.get('evidence',{}).get('checked_at',0)
                        recovery_health={'state':'checked','checked_at':checked,'pages':{tid:page_health}}
                        released=recover_claims(catalog,entries,recovery_health,at=time.time(),retirement_cache=retirement_cache)
                        # Keep local evidence failures visible in the maintenance report.
                        page_health['recovery_errors']=recovery_health.get('recovery_errors',[])
                        page_health['retirement_scan']=recovery_health.get('retirement_scan',{})
                        page_health['claim_recovery']=recovery_health.get('claim_recovery',{})
                        return released
                    health=repair_pages(config,browser,pool,stopping=lambda:stop,lock_factory=submission_lock,
                        on_checked_page=recover_checked_page if mixed_backlog else None,
                        excluded_targets=upload_jobs.targets if upload_jobs else (),target_lease=maintenance_target)
                    last_health=time.monotonic()
                if upload_jobs:upload_jobs.release_observed(health)
                from .browser_inventory import enumerate_pages
                inventory=enumerate_pages(browser);all_pages=inventory['pages']
                window_view=observe_window(config,browser,entries) if shared else None
                if upload_jobs and shared:
                    registry=__import__('core.api',fromlist=['control']).control.read_record(root/'shared-gpt-window.json')
                    upload_jobs.release_missing(set(all_pages),complete=inventory['complete'] and window_view['inventory_complete'],
                        epoch=str(registry.get('created'))+':'+str(registry.get('window_id')),
                        archive=lambda proof:atomic_json(root/'upload-capacity-releases'/
                            (proof['target_id']+'-'+str(int(proof['callback_finished_at']*1000000))+'.json'),
                            dict(proof,owner_pid=os.getpid())))
                collect_ids=set(window_view['collect_target_ids']) if shared else set(all_pages)
                pages={tid:page for tid,page in all_pages.items() if tid in collect_ids and urlsplit(page.url).hostname=='chatgpt.com'}
                if shared and time.monotonic()-getattr(observer,'last_original_recovery',0)>=30:
                    observer.last_original_recovery=time.monotonic()
                    from .original_receipt_recovery import run_once as recover_original_receipts
                    try:
                        recover_original_receipts(config,catalog,browser,pool,pages,
                            complete=inventory['complete'] and window_view['inventory_complete'],
                            stopping=lambda:stop,lock_factory=submission_lock,target_lease=maintenance_target,
                            present_targets=set(all_pages),known_urls=[p.url for p in all_pages.values()])
                    except Exception as exc:errors.append('原会话收取恢复：'+str(exc)[:400])
                from .original_upload_http1 import restore as restore_upload_probe
                dispatch_ids=set(window_view['eligible_target_ids'])&set(pages) if shared else set(pages)
                restore_upload_probe({tid:page for tid,page in pages.items() if tid in dispatch_ids})
                if correction_lane:correction_lane.sync(entries)
                # An original fixed page can redirect to the auth host. Keep
                # it observable without making it dispatchable or inspecting
                # other windows; non-ChatGPT pages only get the account check.
                observation_pages=({**pages,**{s['target_id']:all_pages[s['target_id']] for s in window_view['slots']
                    if s.get('state')=='present' and s.get('target_id') in all_pages}} if shared else all_pages)
                observer.update(observation_pages,lane_entries=entries,
                    shared_browser=browser if shared else None,
                    registered_targets={s['target_id'] for s in window_view['slots'] if s.get('target_id')} if shared else None)
                repairing={tid for tid,e in entries.items() if e.get('state') in ('repair_pending','opening') or e.get('repair_in_progress')}
                repairing.update(health.get('pending_repair_targets',[]))
                dispatch_ids-=repairing
                if upload_jobs:upload_jobs.pump()
                uploading_targets=upload_jobs.targets if upload_jobs else set()
                dispatch_ids-=uploading_targets
                if upload_jobs:
                    for result in upload_jobs.reap():
                        error=str(result.get('error') or '')
                        if error:
                            errors.append(error)
                if review_lane and time.monotonic()-last_review_reconcile>=30:
                    last_review_reconcile=time.monotonic()
                    try:review_lane.reconcile_submissions(entries,excluded_targets=uploading_targets)
                    except (OSError,ValueError,sqlite3.Error) as exc:
                        errors.append('review_receipt_reconcile: '+type(exc).__name__+': '+str(exc)[:200])
                reusable_health={'completed_saved','healthy_blank','raw_path_repair','completed_unsaved'}
                active_page_states={'busy','submitting','submitted','collecting','submission_started'}
                dispatch_ids-={tid for tid,result in health.get('pages',{}).items() if result.get('health') not in reusable_health
                    and not (result.get('health')=='busy' and entries.get(tid,{}).get('state') in active_page_states)}
                # Lifecycle journals retain ownership until the new blank page is verified.
                pages={tid:page for tid,page in pages.items() if tid not in repairing}
                managed_total=window_view['live_fixed_slots'] if shared else inventory['total_pages']
                dispatch_complete=inventory['complete'] and (window_view['inventory_complete'] and not window_view['errors'] if shared else True)
                if health.get('state')=='paused':
                    dispatch_complete=False
                dispatch_block_reasons=[]
                if concurrency_error:
                    dispatch_complete=False;dispatch_block_reasons.append(concurrency_error)
                if not inventory['complete']:dispatch_block_reasons.extend(inventory['errors'] or ['原连接页面清单未完整读取'])
                if shared:dispatch_block_reasons.extend(window_view['errors'])
                if health.get('state')=='paused':dispatch_block_reasons.append('共享页维护因用户暂停停止')
                guard=(lambda tid:require_slot(config,browser,tid)) if shared else None
                if shared and not concurrency_error:
                    from .authorized_unsent_restore import run_once as restore_authorized_unsent
                    restored=restore_authorized_unsent(config,browser,pool,lock_factory=submission_lock,
                        stopping=lambda:stop,excluded_targets=uploading_targets)
                    if restored:last_health=0
                errors.extend(inventory['errors'])
                if shared:errors.extend(window_view['errors'])
                resource_status=dict(code_version=loaded_version,live_total_pages=managed_total, scheduling_shared=shared,scheduling_backlog=mixed_backlog,
                    scheduling_restart_required=(shared_enabled(config)!=shared or (shared and backlog_enabled(config))!=mixed_backlog),
                    dispatch_block_reasons=dispatch_block_reasons,historical_pool_entries=max(0,len(entries)-managed_total))
                if shared:resource_status.update(shared_window_id=window_view['window_id'],fixed_slots=20,
                    live_fixed_slots=managed_total,browser_total_pages=inventory['total_pages'],
                    other_window_pages=window_view['other_window_pages'],shared_window_state=window_view['state'])
                if health:
                    resource_status.update(page_health_checked_at=health.get('checked_at'),page_health_counts=health.get('counts',{}),
                        page_health_available=health.get('available'),page_health_protected=health.get('protected'),
                        page_health_replaced=len(health.get('replaced',[])),page_health_errors=health.get('errors',[]),page_health_state=health.get('state'))
                pool.update(observed_at=time.time(),live_total_pages=managed_total,live_gpt_targets=list(pages),inventory_complete=inventory['complete'])
                if shared:pool.update(shared_window_id=window_view['window_id'],fixed_slots=20,browser_total_pages=inventory['total_pages'])
                if inventory['complete'] and (not shared or window_view['inventory_complete'] and not window_view['errors']):
                    for tid,entry in entries.items():
                        if entry.get('state') in ('repair_pending','opening','retired_replaced') or entry.get('repair_in_progress'):continue
                        if tid not in pages:
                            entry.update(state='needs_inspection' if entry.get('state') in ('busy','needs_inspection') else 'missing',
                                error='原页面不在当前浏览器；保留原记录，不重新发送')
                save_pool(root/'gpt-window-pool.json',pool)
                # A blank composer alone is not proof that the previous request ended.
                from .attempt_history import index_attempts
                record_index,latest=index_attempts(root)
                from web_gpt.core import wait_prompt_box,_box_text
                def read_blank_page(page):
                    require_no_verification(page)
                    # Use the same visible, nonempty message evidence as health.
                    # Raw locator counts include empty assistant placeholders.
                    from .shared_page_health import snapshot_page
                    observed=snapshot_page('blank_check',page)
                    if not observed.get('inspection_complete') or observed.get('errors'):
                        raise ValueError('空白页可见消息核对未完成')
                    if observed.get('composer_available') is False:
                        raise ValueError('页面输入区尚未可用；保留原页，不派发新任务')
                    return {'users':len(observed['user_texts']),
                            'answers':len(observed['answer_texts']), 'draft':observed['draft']}
                reconcile_blank_pages(root,{t:p for t,p in pages.items() if t not in uploading_targets},entries,latest,dispatch_ids,errors,read_page=read_blank_page,
                    on_error=lambda exc,page:record_channel_failure(router,exc,page),record_index=record_index)
                jobs={j['paper_id']:j for j in queue.jobs(catalog)};active=0;correction_active=0
                observation_path=root/'web-page-observer.json'
                observation=json.loads(observation_path.read_text()) if observation_path.exists() else {}
                page_states={x['target_id']:x for x in observation.get('pages',[])} if time.time()-observation.get('updated',0)<30 else {}
                # The observer is the sole shared raw-answer collector. This
                # lane only validates/publishes already saved receipts and never
                # rereads every generating page or waits on the send lock.
                from contextlib import nullcontext
                saved_targets={tid for tid,a in latest.items() if a.get('state')=='response_saved'
                    and entries.get(tid,{}).get('state')!='ready_blank'
                    and (a.get('review_id') or not a.get('publish_checked'))}
                review_pages={t:p for t,p in pages.items() if t not in uploading_targets
                    and (not upload_jobs or t not in upload_jobs.targets) and (not shared or t in saved_targets)}
                collecting_targets.update(review_pages if shared else ())
                try:
                    review_active=review_lane.collect(review_pages,entries,page_states,router,
                        (lambda **kwargs:nullcontext()) if shared else submission_lock,lambda:stop) if review_lane else 0
                finally:collecting_targets.difference_update(review_pages)
                if shared:
                    review_active=sum(p.get('kind')=='review' and p.get('activity_verified') is True and p.get('streaming') is True for p in page_states.values())
                collecting_targets.update(saved_targets & set(pages))
                try:
                    # Real current material identity, never the stale pool URL, selects the ledger.
                    for tid,page in pages.items():
                        if tid in uploading_targets or upload_jobs and tid in upload_jobs.targets:continue
                        if shared and latest.get(tid,{}).get('review_id'):continue
                        if shared and tid not in saved_targets:
                            state=page_states.get(tid,{})
                            if state.get('activity_verified') is True and state.get('streaming') is True:
                                if state.get('kind')=='cards':active+=1
                                elif state.get('kind')=='correction':correction_active+=1
                            continue
                        users=page.locator(USER)
                        if users.count()!=1:continue
                        markers=MARKER.findall(users.first.inner_text())
                        if len(markers)!=1:continue
                        pid=markers[0];folder=root/'web_cards'/pid;path=folder/'chatgpt/attempt.json'
                        if not path.is_file() or pid not in jobs:continue
                        a=json.loads(path.read_text())
                        if a.get('target_id')!=tid:continue
                        expected_path=path.parent/'prompt-actual.txt'
                        if not expected_path.is_file():continue
                        try:
                            require_no_verification(page);identify(page,a,expected_path.read_text())
                            if sum(x.url==page.url for x in pages.values())!=1:raise ValueError('会话URL不唯一')
                            answers=page.locator(ANSWER)
                            stops=page.locator(STOP_BUTTON)
                            done=(page_states.get(tid,{}).get('complete',False) or a.get('state')=='response_saved') and not any(stops.nth(i).is_visible() for i in range(stops.count()))
                            entry=entries.setdefault(tid,{})
                            if done and not answers.count():
                                error='原会话已结束但没有正式回答；需要核对，不自动重发'
                                entry.update(state='needs_inspection',paper_id=pid,conversation_url=page.url,error=error)
                                (path.parent/'error-page.txt').write_text(page.locator('body').inner_text())
                                a.update(state='needs_inspection',conversation_url=page.url,error=error)
                                atomic_json(path,a)
                                queue.update(catalog,pid,state='needs_inspection',provider='chatgpt',error=error)
                                continue
                            if not done or not answers.count():
                                # Missing fresh observation after reconnect is not generation evidence.
                                if a.get('state')=='needs_inspection' and not page_states.get(tid,{}).get('streaming'):
                                    entry.update(state='needs_inspection',error=a.get('error','等待原页实时核对'))
                                    continue
                                if jobs[pid]['state'] in ('completed','protected'):
                                    entry.update(state='needs_inspection',error='已保存结果的原页面状态变化，保留页面，不重新提交')
                                    continue
                                entry.update(state='busy',paper_id=pid,conversation_url=page.url,kind=web_job_kind(jobs[pid]))
                                if web_job_kind(jobs[pid])=='correction':correction_active+=1
                                else:active+=1
                                queue.update(catalog,pid,state='submitted',provider='chatgpt',error='原会话仍生成；只等待，不重发')
                                continue
                            if a.get('state')!='response_saved':
                                raw=collect_owned(page,a.get('prior_count',0),'chatgpt',(ANSWER,STOP_BUTTON,_message_text),30,lambda:stop)
                                with submission_lock(timeout=30):
                                    identify(page,a,expected_path.read_text())
                                    if not raw.strip():raise ValueError('原会话没有正式回答，保留回执不释放或重发')
                                    (path.parent/'response-raw.txt').write_text(raw)
                                    a.update(state='response_saved',conversation_url=page.url,raw_sha256=digest(path.parent/'response-raw.txt'),tab_cleanup='preserved_reusable_window',reused_window=True)
                                    atomic_json(path,a)
                            raw_path=path.parent/'response-raw.txt'
                            if digest(raw_path)!=a['raw_sha256'] or _message_text(answers.last)!=raw_path.read_text():raise ValueError('落盘指纹或实时回答变化')
                            entry.update(state='ready',paper_id=pid,conversation_url=page.url,raw_path=str(raw_path.resolve()),raw_sha256=a['raw_sha256'])
                            if mixed_backlog:
                                from .shared_workflow_queue import release_claim
                                lane=web_job_kind(jobs[pid])
                                jid=json.loads(jobs[pid]['selection']).get('rework',{}).get('correction_id') if lane=='correction' else pid
                                if jid:release_claim(catalog,lane,jid,tid)
                            save_pool(root/'gpt-window-pool.json',pool)
                            from core.api import seed_focus__allowed as seed_allowed
                            if not seed_allowed(config,pid):
                                reason='仅手选种子模式：原完整回答已保存，暂停普通文献发布'
                                if jobs[pid]['state'] not in ('completed','protected') and jobs[pid].get('error')!=reason:
                                    queue.update(catalog,pid,state='needs_inspection',error=reason)
                                continue
                            if jobs[pid]['state'] not in ('completed','protected') and not a.get('publish_checked'):
                                raw=raw_path.read_text();normalized=normalize_json_escapes(raw)
                                if normalized!=raw:
                                    (path.parent/'response-normalized.txt').write_text(normalized)
                                    a['normalization']={'kind':'invalid_json_backslash_only','normalized_sha256':digest(path.parent/'response-normalized.txt')}
                                try:publish_saved(config,jobs[pid],normalized,a,'chatgpt')
                                except Exception as exc:queue.update(catalog,pid,state='failed',provider='chatgpt',error='原始回答已收取，结构未通过：'+str(exc)[:700])
                                a['publish_checked']=True;atomic_json(path,a)
                        except Exception as exc:
                            entries.setdefault(tid,{}).update(state='needs_inspection',error=str(exc)[:500]);errors.append(pid+': '+str(exc)[:200])
                            record_channel_failure(router,exc,page)
                finally:collecting_targets.difference_update(saved_targets)
                save_pool(root/'gpt-window-pool.json',pool)
                if not concurrency_error and inventory['complete'] and time.monotonic()-last_retry>=60:
                    from cards.api import web_card_retry__run_once as retry_failed
                    retry_last_yield=[0.0]
                    def retry_checkpoint():
                        if stop:raise InterruptedError('所有者正在正常退出，保留原重试任务')
                        stamp=time.monotonic()
                        if stamp-retry_last_yield[0]<.1:return
                        retry_last_yield[0]=stamp
                        # The resident connection continues observing and draining
                        # original uploads while full local hashes are checked.
                        pw._sync(__import__('asyncio').sleep(0))
                    retry_failed(config,pages={t:p for t,p in pages.items() if t in dispatch_ids} if shared else pages,
                                 entries=entries,router=router,page_guard=guard,checkpoint=retry_checkpoint)
                    last_retry=time.monotonic();save_pool(root/'gpt-window-pool.json',pool)
                from .page_retirement import retire_excess
                owned_count=sum(tid in entries for tid in pages)
                quarantined=sum(entries.get(tid,{}).get('state')=='needs_inspection' for tid in pages)
                usable=min(config['web_cards'].get('target_pool_pages',10)+quarantined,max(0,config['web_cards'].get('max_total_pages',20)-(managed_total-owned_count)))
                try:closed=[] if shared else retire_excess(root,pages,entries,latest,usable)
                except Exception as exc:
                    closed=[];errors.append('并行缩减等待：'+str(exc)[:150])
                if closed:
                    inventory['total_pages']-=len(closed)
                    pool.update(live_total_pages=inventory['total_pages'],live_gpt_targets=list(pages))
                    save_pool(root/'gpt-window-pool.json',pool)
                # Prepare/send at most one job each cycle, while every other page generates.
                from review.api import card_review_queue__enabled as reviews_enabled
                review_pending=False
                if review_lane:
                    with review_lane.catalog.connect() as db:
                        review_pending=bool(db.execute("SELECT 1 FROM card_review_jobs WHERE state IN ('queued','preparing','ready') LIMIT 1").fetchone())
                queue_heads=None;claim=None
                if mixed_backlog:
                    from .shared_workflow_queue import claim_ready,backlog_dispatch
                    from .shared_claim_recovery import recover_claims
                    recovered_claims=recover_claims(catalog,entries,health,at=time.time(),retirement_cache=retirement_cache) if not concurrency_error else []
                    resource_status['recovered_page_leases']=health.get('recovered_page_leases',[])+recovered_claims
                    backlog=maintain_shared_backlog(config,catalog,entries,window_view['eligible_target_ids'],
                        observation,latest,inventory_complete=dispatch_complete,maintenance=backlog_maintenance,
                        excluded_targets=set(window_view['eligible_target_ids'])-dispatch_ids,
                        checkpoint=database_checkpoint) if not concurrency_error else {'state':'invalid_control'}
                    dispatch_complete=dispatch_complete and backlog.get('state')!='waiting_backlog_writer'
                    allocation=backlog_dispatch(catalog,config,entries,window_view['eligible_target_ids'],backlog,
                        inventory_complete=dispatch_complete,excluded_targets=set(window_view['eligible_target_ids'])-dispatch_ids,
                        pending_uploads=upload_jobs.pending_targets_by_lane if upload_jobs else None)
                elif shared:
                    from .shared_workflow_queue import heads,claim_ready
                    preparation_slots=[tid for tid in dispatch_ids if entries.get(tid,{}).get('state') in ('ready','ready_blank')
                        or entries.get(tid,{}).get('kind') in ('cards','card','correction') and entries.get(tid,{}).get('state')=='busy']
                    assign(catalog,preparation_slots,config=config)
                    queue_heads=heads(catalog,config)
                if not mixed_backlog:allocation=dispatch(entries,window_view['eligible_target_ids'],cards_limit=config['web_cards'].get('max_parallel_jobs',20),
                    review_limit=config.get('card_review',{}).get('parallel_jobs',4),
                    correction_limit=config.get('card_correction',{}).get('parallel_jobs',4),
                    cards_min_pages=config['web_cards'].get('min_reserved_pages',8),queue_heads=queue_heads,hold_card_reservation=True,
                    cards_pending=bool(queue_heads['cards']),review_pending=bool(queue_heads['review']),
                    correction_pending=bool(queue_heads['correction']),cards_allowed=enabled(config),
                    review_allowed=bool(review_lane) and reviews_enabled(config),
                    correction_allowed=bool(correction_lane) and __import__('correction.api',fromlist=['card_correction_queue']).card_correction_queue.enabled(config),
                    inventory_complete=dispatch_complete,excluded_targets=set(window_view['eligible_target_ids'])-dispatch_ids) if shared else None
                if shared:
                    submission_status=shared_submission_status(config)
                    resource_status['submission_channel']=submission_status
                    allocation['submission_channel']=submission_status
                    # Keep durable assignments; do not claim/upload while blocked.
                    # Re-evaluate the live control every cycle, including expiry.
                    if (not upload_lane and submission_status['allowed'] and allocation['claim_order']
                            and (not upload_jobs or upload_jobs.available
                                 and len(upload_budget_targets(upload_jobs,health)) < parallel_uploads)):
                        claims=list(allocation['claim_order'])
                        def claim_room(row):
                            lane=row.get('lane')
                            if lane not in ('cards','review','correction'):return False
                            return allocation['active'][lane] < allocation['budget'][lane]
                        def claim_fits(row):
                            if upload_jobs is None:return True
                            return upload_jobs.can_accept(claim_upload_size(row))
                        # Ordinary small ZIPs may not consume the bytes a seed
                        # is waiting for; active uploads still finish normally.
                        claims=_seed_admission([row for row in claims if claim_room(row)])
                        claim=next((row for row in claims if claim_fits(row)),None)
                if shared:
                    window_view.update(dispatch=allocation,updated=time.time())
                    resource_status.update(slot_budget=allocation['budget'],protected_slots=allocation['protected'],
                        cards_min_pages=config['web_cards'].get('min_reserved_pages',8),dispatch_policy=allocation.get('policy','cards_reservation_then_fifo'),
                        reserved_card_pages=allocation.get('reserved_capacity',0),reserved_card_idle=len(allocation.get('reserved_idle_targets',[])),
                        cards_min_shortfall=allocation.get('cards_min_shortfall',0),correction_workers=correction_active,correction_parallel=config.get('card_correction',{}).get('parallel_jobs',4))
                    if mixed_backlog:resource_status['shared_backlog']=backlog
                    atomic_json(root/'shared-gpt-window-status.json',window_view,durable=False)
                    if upload_lane:
                        dispatch_view.update(registry=__import__('core.api',fromlist=['control']).control.read_record(root/'shared-gpt-window.json'),
                            pages=dict(pages),eligible=sorted(dispatch_ids),health=health,backlog=backlog,resources=dict(resource_status))
                capacity_ok=dispatch_complete and managed_total<=config['web_cards'].get('max_total_pages',20)
                if review_lane and capacity_ok and (not shared or claim and claim['lane']=='review'):
                    atomic_json(root/'web-card-service.json',dict(pid=os.getpid(),token=token,state='running',
                        stage='review_submission_check',updated=time.time(),workers=active,review_workers=review_active,
                        desired_parallel=config['web_cards'].get('max_parallel_jobs',10),review_parallel=config.get('card_review',{}).get('parallel_jobs',0),
                        pool_ready=sum(tid in pages and e.get('state') in ('ready','ready_blank') for tid,e in entries.items()),
                        **resource_status,mode='persistent_cdp_pool',config_path=config['_config_path']),durable=False)
                    options={'allowed_targets':{claim['target_id']},'parallel_limit':allocation['budget']['review'],'page_guard':guard,'job_id':claim['job_id']} if shared else {}
                    if mixed_backlog:options.update(assigned_target_id=claim['target_id'],use_backlog=True)
                    options['persist_pool']=lambda:save_pool(root/'gpt-window-pool.json',pool)
                    if upload_jobs:
                        options['parallel_upload']=True
                        options['persist_pool']=lambda pool=pool:save_pool(root/'gpt-window-pool.json',pool)
                        args=(dict(pages),entries,max(review_active,allocation['active']['review']),dict(options))
                        upload_jobs.start(claim['target_id'],lambda args=args:review_lane.submit(args[0],args[1],args[2],router,submission_lock,lambda:stop or upload_jobs.closing,**args[3]),lane='review')
                    elif review_lane.submit(pages,entries,max(review_active,allocation['active']['review']) if shared else review_active,router,submission_lock,lambda:stop,**options):review_active+=1
                    save_pool(root/'gpt-window-pool.json',pool)
                ready=[(tid,pages[tid]) for tid,e in entries.items() if e.get('state') in ('ready','ready_blank') and tid in pages and (not shared or tid in allocation['card_ready']+allocation['correction_ready'])]
                slot_ids=allocation['card_targets'] if shared else sorted((tid for tid,e in entries.items() if tid in pages and e.get('state') in ('busy','ready','ready_blank') and not (e.get('kind')=='review' and e.get('state')=='busy')),key=lambda tid:(entries[tid].get('state')!='busy',tid))[:config['web_cards'].get('max_parallel_jobs',20)]
                if shared:
                    candidate=None
                    if claim and claim['lane'] in ('cards','correction'):
                        requested=claim if mixed_backlog else next(r for r in queue_heads[claim['lane']] if r['job_id']==claim['job_id'])
                        candidate={'paper_id':requested['paper_id'],'target_id':claim['target_id'],'job_id':claim['job_id'],'lane':claim['lane']}
                else:
                    assign(catalog,slot_ids)
                    candidate=next_ready(catalog,[tid for tid,_ in ready])
                try:provider=router.choose()
                except DeferredWeb:provider=None
                card_limit=allocation['budget'][claim['lane']] if shared and claim and claim['lane'] in ('cards','correction') else 0 if shared else config['web_cards'].get('max_parallel_jobs',10)
                card_active=max(correction_active if claim and claim['lane']=='correction' else active,allocation['active'][claim['lane']]) if shared and claim and claim['lane'] in ('cards','correction') else 0 if shared else active
                if candidate and ready and card_active<card_limit and provider=='chatgpt' and capacity_ok:
                    job=claim_ready(catalog,config,lane=candidate['lane'],job_id=candidate['job_id'],paper_id=candidate['paper_id'],target_id=candidate['target_id'],assigned=mixed_backlog) if shared else queue.claim(catalog,candidate['paper_id'])
                    if job:
                        args=(job,dict(candidate),pool,entries,dict(pages),guard,dict(resource_status),active,review_active,correction_active)
                        if upload_jobs:
                            if not upload_jobs.start(candidate['target_id'],lambda args=args:execute_card_job(*args),lane=candidate['lane']):
                                raise RuntimeError('上传槽位分配变化；保留已领取任务，不重复提交')
                        else:execute_card_job(*args)
                if not shared and not concurrency_error and provider=='qwen' and (qwen_future is None or qwen_future.done()):
                    if qwen_future is not None:qwen_future.result()
                    job=queue.claim(catalog)
                    if job:
                        if json.loads(job['selection']).get('rework'):
                            queue.update(catalog,job['paper_id'],state='queued',retry_at=time.time()+60,error='本次重做仅允许GPT网页版，等待GPT通道')
                        else:qwen_future=qwen_executor.submit(process_job,config,job,router,threading.Semaphore(1),lambda:stop)
                if qwen_future is not None and not qwen_future.done():active+=1
                counts={}
                for j in queue.jobs(catalog):counts[j['state']]=counts.get(j['state'],0)+1
                if correction_lane:correction_lane.sync(entries)
                resource_status['correction_workers']=correction_active
                resource_status.update(upload_parallel_limit=parallel_uploads,uploading_pages=len(upload_jobs.targets) if upload_jobs else 0,
                    uploading_targets=sorted(upload_jobs.targets) if upload_jobs else [])
                resource_status.update(upload_budget_used=len(upload_budget_targets(upload_jobs,health)),
                    upload_admitted_zip_bytes=upload_jobs.admitted_zip_bytes if upload_jobs else 0,
                    upload_zip_byte_limit=upload_jobs.byte_limit if upload_jobs else None,
                    retained_upload_targets=sorted(upload_jobs.retained) if upload_jobs else [],
                    native_upload_wait_targets=sorted(upload_budget_targets(None,health)))
                from .shared_workflow_activity import observed
                actual,activity_checked_at=observed(__import__('core.api',fromlist=['control']).control.read_record(observation_path))
                resource_status.update(actual_parallel=actual,actual_parallel_checked_at=activity_checked_at,actual_parallel_confirmed=actual is not None)
                resource_status['submission_lock_metrics']=dict(vars(pw).get('_paper_submission_metrics',{}))
                if upload_lane:
                    resource_status.update(upload_dispatch_worker='independent_owner_loop',
                        response_collection_worker='independent_observer_loop',upload_dispatch_checks=upload_lane.completed,
                        upload_dispatch_errors=upload_lane.errors[-5:])
                phase='running' if active or correction_active or review_active or ready else 'waiting_browser'
                if shared and not submission_status['allowed'] and not (active or correction_active or review_active):
                    phase='waiting_channel'
                if not dispatch_complete:phase='waiting_page_inspection'
                atomic_json(root/'web-card-service.json',dict(pid=os.getpid(),token=token,state=phase,updated=time.time(),selection={k:v for k,v in selection.items() if k!='added'},jobs=counts,workers=active,review_workers=review_active,desired_parallel=config['web_cards'].get('max_parallel_jobs',10),review_parallel=config.get('card_review',{}).get('parallel_jobs',0),max_total_pages=config['web_cards'].get('max_total_pages',20),mode='persistent_cdp_pool',pool_ready=sum(tid in dispatch_ids and e.get('state') in ('ready','ready_blank') for tid,e in entries.items()),pool_busy=sum(tid in pages and e.get('state')=='busy' for tid,e in entries.items()),**resource_status,inventory_complete=dispatch_complete,errors=errors[-5:],config_path=config['_config_path']))
            except Exception as exc:
                errors.append(type(exc).__name__+': '+str(exc)[:300])
                preserve=keep_connection_after_error(browser,exc)
                # Only driver/connection failures release the resident connection.
                if not preserve and pw is not None:
                    dispatch_view.clear()
                    if upload_lane:upload_lane.drain();upload_lane=None
                    if upload_jobs:upload_jobs.drain()
                    if observer:observer.stop()
                    try:pw.stop()
                    except Exception as disconnect_error:errors.append('连接释放：'+str(disconnect_error)[:200])
                if not preserve:pw=None;browser=None
                atomic_json(root/'web-card-service.json',owner_error_status(
                    os.getpid(),token,exc,preserve=preserve,loaded_version=loaded_version))
            for _ in range(1 if shared and allocation.get('claim_order') and len(allocation['claim_order'])>1 else 10):
                if stop:break
                if pw is not None:
                    wait_error=pump_owner_wait(pw,observer)
                    if wait_error:
                        errors.append(wait_error)
                        pw=None;browser=None
                        atomic_json(root/'web-card-service.json',dict(pid=os.getpid(),token=token,state='waiting_browser',
                            updated=time.time(),error=errors[-1],mode='persistent_cdp_pool'))
                        break # The existing owner reconnects; no page is closed.
                else:time.sleep(.5)
    finally:
        stop=True
        if upload_lane:upload_lane.drain()
        if upload_jobs:upload_jobs.drain()
        atomic_json(root/'web-card-service.json',dict(pid=os.getpid(),token=token,state='stopped',updated=time.time()))
        if correction_lane:correction_lane.stop()
        if review_lane:review_lane.stop()
        producer.stop()
        if observer:observer.stop()
        if checkpoint_installed:
            set_db_checkpoint(previous_checkpoint)
            set_scan_checkpoint(previous_scan_checkpoint)
        if pw is not None:pw.stop()
        qwen_executor.shutdown(wait=True,cancel_futures=True)
