"""Durable active recovery queue for every review/correction retained task.

Runs on the existing local material thread. Submission remains exclusively with
its browser owner. Original job results/receipts stay intact until existing
validated recovery actions advance them.
"""
import collections,hashlib,json,time
from .paths import WorkspacePath as Path
from .services import atomic_json

TABLES={'review':'card_review_jobs','correction':'card_correction_jobs'}

def install(catalog):
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS workflow_recovery_jobs(
          lane TEXT NOT NULL,job_id TEXT NOT NULL,paper_id TEXT NOT NULL,
          evidence_sha256 TEXT NOT NULL,state TEXT NOT NULL,stage TEXT NOT NULL,
          reason TEXT NOT NULL,first_seen REAL NOT NULL,last_checked REAL NOT NULL,
          next_check REAL NOT NULL,checks INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(lane,job_id))''')


def scan(catalog,config):
    install(catalog);at=time.time();items=[];updates=[]
    with catalog.connect() as db:known={(r['lane'],r['job_id']) for r in db.execute('SELECT lane,job_id FROM workflow_recovery_jobs')}
    for lane,table in TABLES.items():
        with catalog.connect() as db:
            if not db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone():continue
            jobs=[dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE state IN ('needs_user','failed')")]
        cooling_jobs=set()
        if lane=='review' and jobs:
            # A proven upload wait is its own recovery stage: the material stays
            # queued with its original FIFO and the receipt is never rewritten.
            from browser.api import upload_retry_policy__annotate as annotate_uploads
            with catalog.connect() as db:
                entries=annotate_uploads(db,[{'lane':'review','job_id':job['id'],'folder':job['folder']}
                                             for job in jobs],config,at=at)
                cooling_jobs={entry['job_id'] for entry in entries if entry['upload_due'] is False}
        for job in jobs:
            try:
                from .control import pause_decision
                pause=pause_decision(config,'card_review' if lane=='review' else 'card_correction')
                folder=Path(job['folder']);attempt={}
                if lane=='review' and (folder/'attempt.json').exists():attempt=json.loads((folder/'attempt.json').read_text())
                # Correction transport belongs to the web_cards ledger, not its task folder.
                if lane=='correction':
                    paths=sorted((catalog.path.parent/'web_cards'/job['paper_id']).glob('*/attempt.json'))
                    attempts=[json.loads(p.read_text()) for p in paths]
                    attempt=max(attempts,key=lambda x:x.get('created',0),default={})
                stage='retry_unsent' if attempt.get('state')=='not_sent' and attempt.get('send_click_started') is False else 'collect_original' if attempt.get('state') in ('submitted','submission_started','needs_inspection') else 'apply_saved_or_cycle' if attempt.get('state')=='response_saved' else 'reconcile_materials'
                if stage=='retry_unsent' and job['id'] in cooling_jobs:stage='upload_cooldown'
                if not pause.allowed:stage='respect_pause'
                reason=job.get('error','')
                signature=hashlib.sha256(json.dumps({'job':job,'attempt':attempt},sort_keys=True).encode()).hexdigest()
            except (OSError,ValueError,KeyError,TypeError) as exc:
                stage='reconcile_evidence';reason=str(exc);signature=hashlib.sha256(json.dumps(job,sort_keys=True).encode()).hexdigest()
            updates.append((lane,job,signature,stage,reason))
            items.append({'lane':lane,'job_id':job['id'],'stage':stage,'reason':reason,'next_check':at+60})
        with catalog.connect() as db:
            db.execute(f"UPDATE workflow_recovery_jobs SET state='advanced',last_checked=? WHERE lane=? AND state='cycling' AND NOT EXISTS(SELECT 1 FROM {table} j WHERE j.id=workflow_recovery_jobs.job_id AND j.state IN ('needs_user','failed'))",(at,lane))
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for lane,job,signature,stage,reason in updates:
            fresh=db.execute('SELECT state FROM '+TABLES[lane]+' WHERE id=?',(job['id'],)).fetchone()
            if not fresh or fresh['state'] not in ('needs_user','failed'):continue
            db.execute('''INSERT INTO workflow_recovery_jobs VALUES(?,?,?,?,?,?,?,?,?,?,1)
              ON CONFLICT(lane,job_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,
              state='cycling',stage=excluded.stage,reason=excluded.reason,last_checked=excluded.last_checked,
              next_check=excluded.next_check,checks=checks+1''',(lane,job['id'],job['paper_id'],signature,'cycling',stage,reason,at,at,at+60))
            if (lane,job['id']) not in known:
                from .catalog import now
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'workflow_recovery_registered',?,?)",(job['paper_id'],json.dumps({'lane':lane,'job_id':job['id'],'state_before':job['state'],'reason':job.get('error'),'evidence_sha256':signature}),now()))
    from browser.api import upload_retry_policy__summary as upload_summary
    with catalog.connect() as db:
        backoff=upload_summary(db,config,at=at)
    report={'updated':at,'interval_seconds':60,'state':'cycling','counts':dict(collections.Counter(x['lane'] for x in items)),
        'stages':dict(collections.Counter(x['stage'] for x in items)),'items':items,'upload_backoff':backoff}
    atomic_json(catalog.path.parent/'workflow-recovery-status.json',report)
    return report


def run_once(catalog,config,*,stopping=None,maintain_review_cycle=True):
    stopping=stopping or (lambda:False)
    if stopping():return {'state':'stopping','actions':[]}
    if config.get('automatic_issue_handling',{}).get('enabled') is not True:return {'state':'disabled'}
    initial=scan(catalog,config)
    # Real actions reuse all existing packet, pause, original-receipt and FIFO guards.
    from review.api import review_channel_recovery__recover as recover
    from correction.api import card_correction_queue__sync as sync
    from review.api import review_cycle__run_once as cycle
    from correction.api import recover_saved_publication__run_once as publish
    actions=[]
    recovery_actions = [('unsent_reviews', lambda: recover(catalog, config)),
                        ('saved_publication', lambda: publish(catalog, config)),
                        ('corrections', lambda: sync(catalog, config))]
    if maintain_review_cycle:
        recovery_actions.append(('science_cycle', lambda: cycle(catalog, config, stopping=stopping)))
    for name,action in recovery_actions:
        if stopping():break
        try:actions.append({'action':name,'result':action()})
        except (OSError,ValueError,KeyError,TypeError) as exc:actions.append({'action':name,'error':str(exc)[:700]})
    if stopping():
        report={**initial,'state':'stopping','actions':actions}
        atomic_json(catalog.path.parent/'workflow-recovery-status.json',report)
        return report
    # Owner reconciles claimed pages and collects originals even during quota wait.
    try:
        from browser.api import web_pool_open__request_shared as request_shared
        actions.append({'action':'owner_reconcile','result':request_shared(config,ensure_page=False)})
    except (OSError,ValueError,KeyError,TypeError) as exc:actions.append({'action':'owner_reconcile','error':str(exc)[:700]})
    report=scan(catalog,config);report['actions']=actions
    atomic_json(catalog.path.parent/'workflow-recovery-status.json',report)
    return report


def decorate(config,lane,result):
    """Display active recovery separately from historical terminal evidence.

    Requires a fresh actual loop heartbeat; a stale registry is never enough.
    """
    import sqlite3
    from contextlib import closing
    path=Path(config['catalog_path']);heartbeat=path.parent/'workflow-recovery-status.json'
    try:
        live=json.loads(heartbeat.read_text())
        if not 0<=time.time()-live['updated']<=180:return result
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            active={r[0] for r in db.execute("SELECT job_id FROM workflow_recovery_jobs WHERE lane=? AND state='cycling' AND last_checked>=?",(lane,time.time()-180))}
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):return result
    counts=dict(result.get('counts',{}));result['historical_counts']=dict(counts)
    for state in ('needs_user','failed'):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            table=TABLES[lane]
            n=db.execute(f"SELECT count(*) FROM {table} j JOIN workflow_recovery_jobs r ON r.job_id=j.id AND r.lane=? WHERE j.state=? AND r.state='cycling' AND r.last_checked>=?",(lane,state,time.time()-180)).fetchone()[0]
        counts[state]=max(0,counts.get(state,0)-n);counts['recovery_pending']=counts.get('recovery_pending',0)+n
    for job in result.get('jobs',[]):
        if job.get('id') in active and job.get('state') in ('needs_user','failed'):
            job['original_state']=job['state'];job['state']='recovery_pending'
    result['counts']=counts;result['recovery_cycle']={'active':len(active),'checked_at':live['updated'],'interval_seconds':60}
    return result
