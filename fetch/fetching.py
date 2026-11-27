"""Durable metadata discovery plus bounded fast/slow acquisition dispatch."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from core.api import paths__WorkspacePath as Path
import subprocess
import sqlite3
import sys
import time
import traceback
from core.api import catalog__ROOT as ROOT, catalog__now as now, catalog__doi as doi
from core.api import services

FETCH_KINDS=('discover','acquire','import','acquire_fallback')


def seed_observation(root,at=None):
    """Counts describe the latest run, never the lifetime of a seed."""
    at=time.time() if at is None else at
    try:
        value=json.loads((Path(root)/'seed-discovery-status.json').read_text())
        updated=value.get('updated',0)
        if not 0<=at-updated<=300:return {'state':'awaiting_observation','counts_scope':'latest_run'}
        seeds=value['seeds']
        return {'state':'observed','observed_at':updated,'counts_scope':'latest_run',
                'active_seeds':sum(x.get('state')=='running' for x in seeds.values()),
                'returned_records':sum(x.get('records',0) for x in seeds.values()),
                'warning_count':sum(x.get('warnings',0) for x in seeds.values()),
                'lifetime_output_known':False}
    except (OSError,ValueError,TypeError,KeyError):return {'state':'awaiting_observation','counts_scope':'latest_run'}


def discovery_schedule_path(catalog):
    return catalog.path.parent/'discovery-schedule.json'


def discovery_schedule(catalog):
    try:return json.loads(discovery_schedule_path(catalog).read_text())
    except (OSError,ValueError):return {}


def record_discovery_schedule(catalog,config,added,seed_id=None):
    """Back off empty discovery rounds instead of paying the full scan every minute."""
    base=max(1,int(config.get('fetch_pipeline',{}).get('discovery_interval_seconds',60)))
    cap=max(base,int(config.get('fetch_pipeline',{}).get('discovery_empty_backoff_max_seconds',3600)))
    previous=discovery_schedule(catalog);at=time.time()
    if added or seed_id:
        state={'empty_streak':0,'next_allowed_at':at+base,'last_queued':len(added or []),'updated':at}
    else:
        streak=int(previous.get('empty_streak',0))+1
        delay=min(cap,base*(4**min(streak-1,4)))
        state={'empty_streak':streak,'next_allowed_at':at+delay,'last_queued':0,'updated':at}
    services.atomic_json(discovery_schedule_path(catalog),state)
    return state


def schedule_discovery(catalog,config):
    policy=config.get('fetch_pipeline',{})
    with catalog.connect() as db:
        if db.execute("SELECT 1 FROM jobs WHERE kind='handover_barrier' AND state='waiting_storage'").fetchone():return
        if db.execute("SELECT 1 FROM jobs WHERE kind='discover' AND state IN ('queued','running','waiting_storage')").fetchone():return
        queued=db.execute("SELECT count(*) FROM jobs WHERE kind IN ('acquire','import') AND state IN ('queued','running')").fetchone()[0]
        if queued>=policy.get('queue_low_water',40):return
        latest=db.execute("SELECT state,updated FROM jobs WHERE kind='discover' ORDER BY created DESC LIMIT 1").fetchone()
    from datetime import datetime
    if latest and time.time()-datetime.fromisoformat(latest['updated']).timestamp()<policy.get('discovery_interval_seconds',60):return
    if discovery_schedule(catalog).get('next_allowed_at',0)>time.time():return
    services.archive_root(config)
    return {'job_id':catalog.enqueue('discover',payload={'trigger':'fetch_queue_refill'})}


def persist_page(catalog,output,raw_path):
    # Records and progress are committed atomically before the checkpoint is retired.
    catalog.retain_discovery(output.get('pool') or [],output.get('positions') or {})
    services.atomic_json(raw_path,output)


def _locked_retry(call,attempts=3,delay=0.2):
    """Let a short writer finish instead of aborting a whole queue pass."""
    for attempt in range(attempts):
        try:return call()
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower() or attempt==attempts-1:raise
            time.sleep(delay*(attempt+1))


def queue_pending(catalog,config):
    from .preprints import relevant,recent_enough
    from .oa_policy import eligible as oa_eligible,priority as oa_priority
    from .network import ready as provider_ready,DeferredRequest
    from urllib.parse import urlsplit
    capacity=config.get('fetch_pipeline',{}).get('queue_high_water',200)
    scan_limit=max(capacity,int(config.get('fetch_pipeline',{}).get('queue_scan_limit',400)))
    oa_only=bool(config.get('fetch_pipeline',{}).get('oa_only',True))
    def pending(key,state='done',error='',retry_at=0):
        return _locked_retry(lambda: catalog.pending_result(key,state,error,retry_at))
    def hosts_ready(record):
        hosts=[]
        for url in record.get('pdf_urls') or []:
            host=urlsplit(url).hostname
            if host:hosts.append('pdf:'+host)
        if not hosts:return True,None
        retry=[]
        for provider in dict.fromkeys(hosts):
            try:provider_ready(provider,catalog.path.parent);return True,None
            except DeferredRequest as exc:retry.append(exc.retry_at or time.time()+900)
        return False,min(retry) if retry else None
    with catalog.connect() as db:
        queued=db.execute("SELECT count(*) FROM jobs WHERE kind IN ('acquire','acquire_fallback','import') AND state IN ('queued','running','waiting_storage')").fetchone()[0]
        slow_queued=db.execute("SELECT count(*) FROM jobs WHERE kind='acquire_fallback' AND state IN ('queued','running','waiting_storage')").fetchone()[0]
    entries=catalog.pending_discovery()
    normalized=[]
    for key,p in entries:
        try:
            from core.api import record_contract__normalize as normalize
            normalized.append((key,normalize(p)))
        except (ValueError,TypeError) as exc:
            pending(key,'quarantined',error=str(exc))
            catalog.event(None,'discovery_item_error',{'key':key,'error':str(exc)})
    if oa_only:
        # Highest-yield OA routes first, then other OA routes, then records
        # with a direct PDF. Closed publisher links are skipped below.
        normalized.sort(key=lambda e:(0 if e[1].get('manual_seed_fast_lane') else 1,oa_priority(e[1]),0 if e[1].get('pdf_urls') else 1))
        ordered=normalized
    else:
        # Legacy interleaving for callers that explicitly disable the OA gate.
        buckets={k:[] for k in ('journal','arxiv','chemrxiv')}
        for key,p in normalized:
            channel=next((x for x in p.get('channels',[]) if x in buckets),'journal');buckets[channel].append((key,p))
        for bucket in buckets.values():bucket.sort(key=lambda e:bool(e[1].get('pdf_urls')),reverse=True)
        ordered=[]
        for index in range(max((len(x) for x in buckets.values()),default=0)):
            ordered.extend(bucket[index] for bucket in buckets.values() if index<len(bucket))
    added=[];scanned=0
    for key,p in ordered:
        if queued>=capacity or scanned>=scan_limit:break
        scanned+=1
        try:
            direct=bool(p.get('pdf_urls') or p.get('arxiv_id') or p.get('open_access_pdf'))
            kind='acquire' if direct or not config.get('pdf_retrieval',{}).get('enabled') else 'acquire_fallback'
            if kind=='acquire_fallback' and slow_queued>=config.get('fetch_pipeline',{}).get('fallback_queue_limit',50):continue
            if not relevant(p['title']+' '+(p.get('abstract') or '')):
                pending(key,'excluded',error='缺少有机发光/激子领域上下文');continue
            reasons=p.get('discovery_reasons') or []
            if isinstance(reasons,str):reasons=[reasons]
            seed_linked=bool(p.get('discovered_from_seed_dois')) or any(str(x).startswith(('参考文献：','引用种子：')) for x in reasons)
            if not seed_linked and not recent_enough(p,config.get('discovery_max_age_years',20)):
                pending(key,'excluded',error='早于最近20年窗口');continue
            if oa_only and not oa_eligible(p):
                pending(key,'excluded',error='无自动OA路径；跳过闭源/需真人核验出版商');continue
            host_ok,host_retry=hosts_ready(p)
            if not host_ok:
                pending(key,'pending',retry_at=host_retry or time.time()+900,error='主机冷却等待');continue
            if p['title'].lower().startswith(('erratum','correction','retraction')):
                pending(key);continue
            existing_pid=catalog.find_doi(p.get('doi')) if p.get('doi') else None
            paper=catalog.get(existing_pid) if existing_pid else None
            if paper is None:
                changed=True
            else:
                changed=bool(set(p.get('pdf_urls') or [])-set(paper['metadata'].get('pdf_urls') or []))
                changed=changed or bool(p.get('arxiv_version_id') and p.get('arxiv_version_id')!=paper['metadata'].get('arxiv_version_id'))
            if changed:
                pid=_locked_retry(lambda: catalog.upsert(p))
                for reason in p.get('discovery_reasons') or []:_locked_retry(lambda: catalog.upsert(p,reason=reason))
                paper=catalog.get(pid)
            else:
                pid=existing_pid
            if paper['seed'] or paper['decision']=='reject' or paper['metadata'].get('out_of_scope'):
                pending(key);continue
            if paper['asset_path'] and Path(paper['asset_path']).is_file():
                target=paper['metadata'].get('arxiv_version_id');have=paper['metadata'].get('asset_preprint_version')
                current=not target or target==have or paper['metadata'].get('asset_target_version')==target
                if current:
                    if paper['candidate_order'] is None:_locked_retry(lambda: catalog.upsert(p,candidate=True))
                    pending(key);continue
            with catalog.connect() as db:
                active=db.execute("SELECT 1 FROM jobs WHERE paper_id=? AND kind IN ('acquire','acquire_fallback','import') AND state IN ('queued','running','waiting_storage')",(pid,)).fetchone()
            if active:
                pending(key,'pending',retry_at=time.time()+30);continue
            # A ready target can still have exhausted its cumulative budget.
            # Preserve that ledger; only a changed input may reach begin/reset.
            from .fetch_policy import fingerprint
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                target=None
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fetch_targets'").fetchone():
                    target=db.execute('SELECT * FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()
                if target and target['input_hash']==fingerprint(paper['metadata']):
                    fast_lane=bool(paper['metadata'].get('manual_seed_fast_lane'))
                    exhausted=target['attempts']>=config.get('fetch_pipeline',{}).get('target_retry_limit',6) and not fast_lane
                    if fast_lane and target['state']=='terminal':
                        db.execute("UPDATE fetch_targets SET state='ready',retry_at=0,error='' WHERE paper_id=?",(pid,))
                        target=db.execute('SELECT * FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()
                    if target['state']=='terminal' or exhausted or target['retry_at']>time.time():
                        blocked=(target['state']=='terminal' or exhausted) and not fast_lane
                        db.execute('UPDATE discovery_pending SET state=?,retry_at=?,error=? WHERE key=?',
                                   ('blocked_fetch' if blocked else 'pending',target['retry_at'],target['error'] or '遵循原目标次数及等待策略',key))
                        continue
            jid=_locked_retry(lambda: catalog.enqueue(kind,pid,{'pending_key':key,'trigger':'discovery'}))
            # An INSERT policy trigger can cancel this ID. Never report it as
            # queued or overwrite the policy's durable pending/terminal state.
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                job=db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()
                if not job or job['state'] not in ('queued','running','waiting_storage'):continue
                db.execute("UPDATE discovery_pending SET state='queued',retry_at=0,error='' WHERE key=?",(key,))
            added.append(jid);queued+=1
            if kind=='acquire_fallback':slow_queued+=1
        except (ValueError,KeyError,TypeError) as exc:
            pending(key,'quarantined',error=str(exc))
            catalog.event(None,'discovery_item_error',{'key':key,'error':str(exc)})
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower():raise
    return added


def discover_and_queue(catalog,config,seed_id=None):
    archive=services.archive_root(config);folder=catalog.path.parent
    run_id=now().replace(':','-');checkpoint=folder/'discovery-checkpoints'/(run_id+'.json')
    checkpoint.parent.mkdir(parents=True,exist_ok=True)
    seeds=[p['metadata'] for p in catalog.list() if p['seed'] and not p['metadata'].get('is_correction')]
    if seed_id:seeds=[catalog.get(seed_id)['metadata']]
    payload={'seeds':seeds,'queries':config.get('topic_queries',[]),'discovery_channels':config.get('discovery_channels',['oled_topic','seed_related','arxiv','chemrxiv']),'positions':catalog.cursors(),
             'preprints':config.get('preprint_channels',{}),'network':{**config.get('fetch_pipeline',{}),'discovery_max_age_years':config.get('discovery_max_age_years',20)},
             'checkpoint_path':str(checkpoint),'state_dir':str(folder)}
    partial=False
    try:
        output=services.bridge('fetch.discovery_bridge',payload,log=folder/'logs'/('discover-'+run_id+'.log'),timeout=config.get('fetch_pipeline',{}).get('discovery_timeout_seconds',180))
    except Exception:
        if not checkpoint.exists():raise
        output=json.loads(checkpoint.read_text());partial=True
        output.setdefault('warnings',[]).append('检索子进程中断；已恢复成功页面，失败来源游标保持原值')
    persist_page(catalog,output,archive/'raw'/(run_id+'.json'))
    for p in output.get('resolved',[]):
        try:
            is_seed=any(doi(s.get('doi'))==doi(p.get('doi')) for s in seeds)
            catalog.upsert(p,reason='种子元数据补全',seed=is_seed or bool(p.get('is_correction')))
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            catalog.event(None,'discovery_resolved_error',{'record':p,'error':str(exc)})
    added=queue_pending(catalog,config)
    schedule=record_discovery_schedule(catalog,config,added,seed_id)
    result={'queued_acquisitions':added,'metadata_count':len(output.get('pool',[])),'partial':partial,
            'warnings':output.get('warnings',[]),'channels':output.get('channels',{}),'raw_file':str(archive/'raw'/(run_id+'.json')),
            'empty_streak':schedule.get('empty_streak'),'next_discovery_at':schedule.get('next_allowed_at')}
    with catalog.connect() as db:db.execute('INSERT INTO runs VALUES(?,?,?)',(run_id,now(),json.dumps(result,ensure_ascii=False)))
    checkpoint.unlink(missing_ok=True)
    catalog.event(None,'discovery_page_completed',{'positions':output.get('positions',{}),'metadata_count':len(output.get('pool',[])),'partial':partial})
    return added


def restore_checkpoints(catalog,config):
    root=catalog.path.parent/'discovery-checkpoints'
    for checkpoint in sorted(root.glob('*.json')):
        try:
            output=json.loads(checkpoint.read_text());archive=services.archive_root(config)
            persist_page(catalog,output,archive/'raw'/('recovered-'+checkpoint.name));checkpoint.unlink()
            catalog.event(None,'discovery_checkpoint_restored',{'file':checkpoint.name,'count':len(output.get('pool',[]))})
        except (OSError,ValueError):continue


def run_acquisition(catalog,config,job):
    from .network import ready as provider_ready,DeferredRequest
    from urllib.parse import urlsplit
    paper=catalog.get(job['paper_id']);metadata=paper['metadata']
    urls=list(metadata.get('pdf_urls') or [])
    if metadata.get('open_access_pdf'):urls.append(metadata['open_access_pdf'])
    if metadata.get('arxiv_id'):urls.append('https://arxiv.org/pdf/'+str(metadata.get('arxiv_version_id') or metadata['arxiv_id']))
    hosts=[urlsplit(url).hostname for url in urls if urlsplit(url).hostname]
    if hosts:
        waits=[]
        for host in dict.fromkeys(hosts):
            provider='arxiv-pdf' if host in ('arxiv.org','export.arxiv.org') else 'pdf:'+host
            try:provider_ready(provider,catalog.path.parent);break
            except DeferredRequest as exc:waits.append(exc.retry_at or time.time()+900)
        else:
            return {'available':False,'skipped':True,'host_wait':min(waits)}
    log=catalog.path.parent/'logs'/('acquire-'+job['id']+'.log');log.parent.mkdir(parents=True,exist_ok=True)
    policy=config.get('fetch_pipeline',{})
    budget=policy.get('fallback_task_timeout_seconds',110) if job['kind']=='acquire_fallback' else policy.get('fast_task_timeout_seconds',65)
    from core.api import process_runner__run as child_run
    with log.open('a') as stderr:
        result=child_run([sys.executable,'-m','fetch.acquire_bridge'],input=json.dumps({'config':config,'job':job}),
                              cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=stderr,timeout=budget)
    if result.returncode:raise RuntimeError(log.read_text()[-4000:] or '获取子进程失败')
    return json.loads(result.stdout)


def complete_acquisition(catalog,config,job,result):
    key=job['payload'].get('pending_key');pid=job['paper_id'];paper=catalog.get(pid)
    def target_policy():
        with catalog.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='fetch_targets' AND type='table'").fetchone():return None
            return db.execute('SELECT state,retry_at FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()
    if result.get('waiting_storage'):
        catalog.finish(job['id'],'waiting_storage',result.get('error','SSD 无法使用'))
        if key:catalog.pending_result(key,'pending',error='等待 SSD 恢复',retry_at=time.time()+30)
        return
    if result.get('host_wait'):
        catalog.finish(job['id'],'deferred')
        if key:catalog.pending_result(key,'pending',retry_at=result['host_wait'],error='主机冷却等待')
        return
    if result.get('skipped') or paper['decision']=='reject':
        catalog.finish(job['id'],'cancelled')
        if key:
            if paper['decision']=='reject' or not result.get('policy_blocked'):
                catalog.pending_result(key,'excluded',error='人工忽略')
            else:
                target=target_policy()
                catalog.pending_result(key,'blocked_fetch' if target and target['state']=='terminal' else 'pending',
                    retry_at=target['retry_at'] if target else time.time()+config.get('fetch_pipeline',{}).get('transient_retry_seconds',900),
                    error='目标获取策略暂缓；不是人工忽略')
        return
    available=paper['asset_path'] and Path(paper['asset_path']).is_file() and paper['acquisition']=='available'
    catalog.finish(job['id'],'done' if available else 'deferred')
    if available:
        if not paper['seed']:catalog.upsert(paper['metadata'],candidate=True)
        if key:catalog.pending_result(key)
        catalog.enqueue('screen',pid)
    elif job['kind']=='acquire' and config.get('pdf_retrieval',{}).get('enabled') and not paper['metadata'].get('arxiv_id'):
        target=target_policy()
        if target and target['state']!='terminal' and target['retry_at']>time.time():
            if key:catalog.pending_result(key,'pending',retry_at=target['retry_at'],error='未发出请求的主机槽位等待')
            return
        with catalog.connect() as db:
            slow=db.execute("SELECT count(*) FROM jobs WHERE kind='acquire_fallback' AND state IN ('queued','running','waiting_storage')").fetchone()[0]
        if slow<config.get('fetch_pipeline',{}).get('fallback_queue_limit',50):
            catalog.enqueue('acquire_fallback',pid,job['payload'])
        elif key:
            catalog.pending_result(key,'pending',retry_at=time.time()+config.get('fetch_pipeline',{}).get('transient_retry_seconds',900),error='全文回退队列已满，保留后续重试')
    else:
        target=target_policy()
        if target and (target['state']=='terminal' or target['retry_at']>0):
            if key:catalog.pending_result(key,'blocked_fetch' if target['state']=='terminal' else 'pending',
                retry_at=target['retry_at'],error='遵循目标获取策略的原退避时间')
            return
        with catalog.connect() as db:
            row=db.execute("SELECT payload FROM events WHERE paper_id=? AND kind IN ('acquisition_pending','acquisition_fast_pending') ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
        attempts=json.loads(row[0]).get('attempts',[]) if row else []
        retry_at=max([x.get('retry_at',0) for x in attempts]+[0])
        if not retry_at:
            transient=any(x.get('kind') in ('timeout','download_error','deferred') for x in attempts)
            retry_at=time.time()+(config.get('fetch_pipeline',{}).get('transient_retry_seconds',900) if transient else config.get('pdf_retry_hours',24)*3600)
        if key:catalog.pending_result(key,'pending',retry_at=retry_at,error='等待重试或补充原文')


def recover_fetch(catalog,config):
    catalog.recover(FETCH_KINDS)
    restore_checkpoints(catalog,config)
    from .fetch_wait_recovery import reconcile
    reconcile(catalog)
    with catalog.connect() as db:
        # One explicit recovery after policy changes, without erasing old errors.
        revision=config.get('runtime_revision','fetch-v3')
        activated=db.execute("SELECT 1 FROM events WHERE kind='fetch_policy_activation' AND json_extract(payload,'$.revision')=?",(revision,)).fetchone()
        if not activated:
            count=0  # Preserve backoff across deployments; no mass reactivation.
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(NULL,?,?,?)',('fetch_policy_activation',json.dumps({'revision':revision,'pending_reactivated':count}),now()))
        db.execute("UPDATE discovery_pending SET state='pending',retry_at=0 WHERE state='queued' AND NOT EXISTS (SELECT 1 FROM jobs WHERE kind IN ('acquire','acquire_fallback','import') AND state IN ('queued','running','waiting_storage') AND json_extract(payload,'$.pending_key')=discovery_pending.key)")
        jobs=[dict(r) for r in db.execute("SELECT * FROM jobs WHERE kind IN ('acquire','acquire_fallback','import') AND state IN ('failed','waiting_storage')")]
    for job in jobs:
        if job['attempts']>=config.get('job_retry_limit',3):continue
        if catalog.get(job['paper_id'])['decision']=='reject':continue
        try:catalog.retry(job['id'])
        except Exception as exc:
            catalog.event(job['paper_id'],'fetch_recovery_warning',{'job_id':job['id'],'error':str(exc)})


def fetch_loop(catalog,config,loop,should_stop):
    policy=config.get('fetch_pipeline',{})
    active={};last_schedule=0;last_diagnostics=0;initialized=False
    with ExitStack() as stack:
        from core.api import concurrency_control__MAX_FETCH as MAX_FETCH
        # Executors start threads lazily. Dispatch still follows the live lane
        # limits; its authorized upper range must not queue behind 32 threads.
        pools={name:stack.enter_context(ThreadPoolExecutor(max_workers=n)) for name,n in
               [('fast',MAX_FETCH),('slow',MAX_FETCH),('discover',1)]}
        while True:
            from core.api import concurrency_control__apply as apply_concurrency
            from core.api import control__pause_decision as pause_decision
            control_error=dispatch_error=None
            try:
                apply_concurrency(config)
                decision=pause_decision(config,'fetch')
                if decision.state=='invalid':raise ValueError(decision.reason)
                paused=not decision.allowed
            except (OSError,ValueError,TypeError,KeyError):
                control_error=traceback.format_exc()[-4000:];paused=False
            stopping=should_stop()
            stopping=stopping or paused
            if not initialized and not stopping and not control_error:
                try:
                    recover_fetch(catalog,config);queue_pending(catalog,config);initialized=True
                except sqlite3.OperationalError as exc:
                    if not any(s in str(exc).lower() for s in ('locked','busy')):raise
                    dispatch_error=traceback.format_exc()[-4000:]
            for future,job in list(active.items()):
                if not future.done():continue
                try:
                    try:
                        result=future.result()
                    except services.StorageUnavailable as exc:catalog.finish(job['id'],'waiting_storage',str(exc))
                    except Exception:
                        error=traceback.format_exc()[-4000:];catalog.finish(job['id'],'failed',error)
                        key=job['payload'].get('pending_key')
                        if key:catalog.pending_result(key,'pending',retry_at=time.time()+policy.get('transient_retry_seconds',900),error=error[-500:])
                    else:
                        try:
                            if job['kind']=='discover':catalog.finish(job['id'],'done')
                            else:complete_acquisition(catalog,config,job,result)
                        except sqlite3.OperationalError:raise
                        except Exception:
                            error=traceback.format_exc()[-4000:];catalog.finish(job['id'],'failed',error)
                            key=job['payload'].get('pending_key')
                            if key:catalog.pending_result(key,'pending',retry_at=time.time()+policy.get('transient_retry_seconds',900),error=error[-500:])
                except sqlite3.OperationalError as exc:
                    if not any(s in str(exc).lower() for s in ('locked','busy')):raise
                    # Keep the completed future for local persistence retry;
                    # do not submit another acquisition or discard its result.
                    dispatch_error=traceback.format_exc()[-4000:];continue
                del active[future]
            if loop and initialized and not stopping and not control_error and not dispatch_error and time.monotonic()-last_schedule>=5:
                last_schedule=time.monotonic()
                try:
                    services.archive_root(config)
                    from core.api import storage_health__status as storage_status
                    if storage_status(config).get("free_bytes",0)<config.get("minimum_free_bytes",256*1024*1024):raise services.StorageUnavailable("SSD 空间不足，保持等待")
                    queue_pending(catalog,config)
                    if config.get('automatic_schedule_enabled'):schedule_discovery(catalog,config)
                    with catalog.connect() as db:
                        db.execute("UPDATE jobs SET state='queued',updated=? WHERE state='waiting_storage' AND kind IN ('discover','acquire','acquire_fallback','import')",(now(),))
                except services.StorageUnavailable as exc:
                    services.atomic_json(catalog.path.parent/'storage-health.json',{'state':'waiting_storage','error':str(exc),'updated':time.time()},durable=False)
                except Exception:print(traceback.format_exc(),file=sys.stderr,flush=True)
            if initialized and not stopping and not control_error and not dispatch_error:
                fast_kinds=('import','acquire','acquire_fallback') if policy.get('fallback_workers',2)==0 else ('import','acquire')
                for name,kinds,slots in [('fast',fast_kinds,policy.get('download_workers',4)),('slow',('acquire_fallback',),policy.get('fallback_workers',2)),('discover',('discover',),1)]:
                    running=sum((j['kind'] in kinds) for j in active.values())
                    for _ in range(slots-running):
                        try:job=catalog.claim(kinds)
                        except sqlite3.OperationalError as exc:
                            if not any(s in str(exc).lower() for s in ('locked','busy')):raise
                            dispatch_error=traceback.format_exc()[-4000:];break
                        if not job:break
                        future=pools[name].submit(services.discover,catalog,config,job['payload'].get('seed_id')) if name=='discover' else pools[name].submit(run_acquisition,catalog,config,job)
                        active[future]=job
                    if dispatch_error:break
            services.atomic_json(catalog.path.parent/'worker-fetch.json',{'pid':os.getpid(),'updated':time.time(),'state':'working' if active else 'blocked_control' if control_error else 'waiting_database' if dispatch_error else 'idle',
                                  'control_error':control_error,'dispatch_error':dispatch_error,
                                  'executor_capacity':{'direct':MAX_FETCH,'fallback':MAX_FETCH,'discovery':1},
                                  'completed_waiting_persistence':sum(f.done() for f in active),
                                  'job_id':next(iter(active.values()))['id'] if active else None,'kind':'parallel_fetch' if active else None,
                                  'capacity':{'direct':policy.get('download_workers',4),'fallback':policy.get('fallback_workers',2),'discovery':1,'seeds':policy.get('seed_workers',6),'topics':policy.get('topic_workers',2)},
                                  'seed_observation':seed_observation(catalog.path.parent),
                                  'actual_active':{'direct':sum(not f.done() and j['kind'] in ('import','acquire') for f,j in active.items()),'fallback':sum(not f.done() and j['kind']=='acquire_fallback' for f,j in active.items()),'discovery':sum(not f.done() and j['kind']=='discover' for f,j in active.items())},
                                  'active':[{'id':j['id'],'kind':j['kind'],'paper_id':j['paper_id']} for j in active.values()]},durable=False)
            if time.monotonic()-last_diagnostics>=60:
                try:
                    from .fetch_diagnostics import report
                    services.atomic_json(catalog.path.parent/'fetch-diagnostics.json',report(catalog),durable=False)
                    last_diagnostics=time.monotonic()
                except (OSError,ValueError,sqlite3.Error):pass
            if (stopping or not loop) and not active:break
            time.sleep(1)
