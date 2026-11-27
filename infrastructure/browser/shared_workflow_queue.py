"""Immutable arrival evidence for three lanes sharing the registered page pool.

Old rows have no trustworthy creation timestamp. Register them at migration time
and label that basis explicitly; never derive arrival from a changing updated.
Preparation is local. Only ready, authorized, due jobs enter page allocation.
"""
import json
import time


def install(catalog):
    from .upload_retry_policy import install as upload_policy_install
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS shared_workflow_arrivals(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, lane TEXT NOT NULL,
            job_id TEXT NOT NULL, queued_at REAL NOT NULL, basis TEXT NOT NULL,
            UNIQUE(lane,job_id))''')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,lane,key,condition in (
                ('web_card_jobs','cards','paper_id',"json_extract(NEW.selection,'$.rework.correction_id') IS NULL"),
                ('card_review_jobs','review','id','1'),
                ('card_correction_jobs','correction','id','1')):
            if table not in tables:continue
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS arrival_{table}_insert AFTER INSERT ON {table}
                WHEN {condition} BEGIN
                INSERT OR IGNORE INTO shared_workflow_arrivals(lane,job_id,queued_at,basis)
                VALUES('{lane}',NEW.{key},(julianday('now')-2440587.5)*86400,'enqueue'); END''')
            stamp=time.time()
            # Row order is only a deterministic tie-break for legacy registration.
            db.execute(f'''INSERT OR IGNORE INTO shared_workflow_arrivals(lane,job_id,queued_at,basis)
                SELECT ?, source.{key}, ?, 'migration_registration' FROM {table} AS source
                WHERE NOT EXISTS(SELECT 1 FROM shared_workflow_arrivals AS arrival
                    WHERE arrival.lane=? AND arrival.job_id=source.{key})
                ORDER BY source.rowid''', (lane, stamp, lane))
    # Upload backoff evidence lives beside these arrivals and shares their
    # install chain, so no read path has to create schema inside a transaction.
    upload_policy_install(catalog)


def register(catalog,lane,job_id):
    """Record a genuine new enqueue before state updates; idempotent."""
    install(catalog)
    with catalog.connect() as db:
        db.execute('INSERT OR IGNORE INTO shared_workflow_arrivals(lane,job_id,queued_at,basis) VALUES(?,?,?,?)',
                   (lane,job_id,time.time(),'enqueue'))


def heads(catalog,config):
    from correction.api import card_correction_queue__allows_web_job as allows_web_job, card_correction_queue__web_job_kind as web_job_kind
    from cards.api import web_card_service__enabled as cards_enabled
    from review.api import card_review_queue__enabled as review_enabled
    install(catalog)
    result={'cards':[],'review':[],'correction':[]}
    with catalog.connect() as db:
        arrivals={(r['lane'],r['job_id']):dict(r) for r in db.execute('SELECT * FROM shared_workflow_arrivals')}
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'web_page_queue' in tables:
            jobs=db.execute("SELECT j.* FROM web_card_jobs j JOIN web_page_queue q USING(paper_id) WHERE j.state='queued' AND j.retry_at<=? AND q.state='ready'",(time.time(),)).fetchall()
            for row in jobs:
                job=dict(row);lane=web_job_kind(job)
                if not (allows_web_job(config,job) if lane=='correction' else cards_enabled(config)):continue
                selection=json.loads(job['selection'])
                jid=selection.get('rework',{}).get('correction_id') if lane=='correction' else job['paper_id']
                if not jid:continue
                if lane=='correction':
                    if 'card_correction_jobs' not in tables:continue
                    correction=db.execute("SELECT 1 FROM card_correction_jobs WHERE id=? AND paper_id=? AND kind='source_rework' AND state='ready'",
                                          (jid,job['paper_id'])).fetchone()
                    if not correction:continue
                arrival=arrivals.get((lane,jid))
                if arrival:result[lane].append({**arrival,'job_id':jid,'paper_id':job['paper_id']})
        if 'card_review_jobs' in tables and review_enabled(config):
            # The non-mixed heads entry follows the same upload backoff as the
            # mixed page pool: a proven wait skips only that unclaimed material.
            from .upload_retry_policy import annotate as upload_annotate
            candidates=[{**dict(row),'lane':'review','job_id':row['id']} for row in
                        db.execute("SELECT id,paper_id,folder FROM card_review_jobs WHERE state='ready'")]
            upload_annotate(db,candidates,config,at=time.time())
            for row in candidates:
                if row['upload_due'] is False:continue
                arrival=arrivals.get(('review',row['id']))
                if arrival:result['review'].append({**arrival,'paper_id':row['paper_id']})
    from core.api import workflow_priority__sort as sort_articles
    with catalog.connect() as db:
        for lane in result:result[lane]=sort_articles(db,result[lane],config)
    return result


def bind_ready(catalog,paper_id,target_id):
    """Legacy unclaimed rebinding is blocked while mixed page bindings exist."""
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='shared_page_backlog'").fetchone():
            raise ValueError('混合队列必须使用已登记绑定与原子领取，禁止仅移动材料镜像')
        row=db.execute("SELECT j.*,q.state AS material_state FROM web_card_jobs j JOIN web_page_queue q USING(paper_id) WHERE j.paper_id=? AND j.state='queued' AND j.retry_at<=? AND q.state='ready'",(paper_id,time.time())).fetchone()
        if row is None:return None
        db.execute('UPDATE web_page_queue SET target_id=? WHERE paper_id=?',(target_id,paper_id))
        return {'paper_id':paper_id,'target_id':target_id,'state':'ready'}


def claim_ready(catalog,config,*,lane,job_id,paper_id,target_id,assigned=False):
    """CAS the exact FIFO decision and claim its prepared source-only transport."""
    from correction.api import card_correction_queue__allows_web_job as allows_web_job, card_correction_queue__web_job_kind as web_job_kind
    from core.api import seed_focus__allowed as seed_allowed
    if not seed_allowed(config,paper_id):return None
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if assigned:
            from .shared_page_backlog import check_head_binding
            if not check_head_binding(db,config,lane,job_id,target_id):return None
        row=db.execute("SELECT j.*,q.state AS material_state FROM web_card_jobs j JOIN web_page_queue q USING(paper_id) WHERE j.paper_id=? AND j.state='queued' AND j.retry_at<=? AND q.state='ready'",(paper_id,time.time())).fetchone()
        if row is None:return None
        job=dict(row);selection=json.loads(job['selection'])
        actual_id=selection.get('rework',{}).get('correction_id') if lane=='correction' else paper_id
        if web_job_kind(job)!=lane or actual_id!=job_id or not allows_web_job(config,job):return None
        if lane=='correction':
            row=db.execute("SELECT 1 FROM card_correction_jobs WHERE id=? AND paper_id=? AND kind='source_rework' AND state='ready'",(job_id,paper_id)).fetchone()
            if row is None:return None
        if assigned:
            from .shared_page_backlog import mark_claimed
            if not mark_claimed(db,lane,job_id,target_id):return None
        from core.api import catalog__now as now
        db.execute('UPDATE web_page_queue SET target_id=? WHERE paper_id=?',(target_id,paper_id))
        db.execute("UPDATE web_card_jobs SET state='preparing',error='',attempts=attempts+1,updated=? WHERE paper_id=?",(now(),paper_id))
        job.pop('material_state',None)
        return job


def check_claim(catalog,lane,job_id,target_id):
    """Recheck the exact durable page lease under the shared submission lock."""
    from .shared_page_backlog import check_claim_binding
    with catalog.connect() as db:
        if not check_claim_binding(db,lane,job_id,target_id):
            raise ValueError('共享队列原页面领取归属变化；不导航或发送')


def release_claim(catalog,lane,job_id,target_id):
    """Release only a caller-verified completed lease; never edit its ledger."""
    from .shared_page_backlog import remove_binding
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return remove_binding(db,lane,job_id,target_id,expected_state='claimed')


def rollback_claim(catalog,lane,job_id,target_id):
    """A proven pause before any page use restores its original queued lease."""
    from .shared_page_backlog import rollback_claim as undo
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return undo(db,lane,job_id,target_id)


def active_targets(catalog,entries,live_targets,observation,latest,*,owner_pid,at=None):
    """Count only fresh original-session work, never a historical busy page.

    A completed but not yet collected answer still occupies its current slot.
    Once the owner has verified/saved it and made the page ready, it leaves the
    inventory. Unknown requests without current identity evidence stay protected
    by the page pool, but are not invented tasks in the 70/100 inventory.
    """
    from core.api import paths__WorkspacePath as Path
    from correction.api import card_correction_queue__web_job_kind as web_job_kind
    from review.api import card_review_queue__TERMINAL as TERMINAL
    at=time.time() if at is None else at
    stamp=observation.get('updated',0)
    if (observation.get('owner_pid')!=owner_pid or observation.get('activity_schema_version')!=1
            or not isinstance(stamp,(int,float)) or not 0<=at-stamp<30):return {}
    live=set(live_targets)
    card_ids=json.dumps(sorted({entry.get('active_paper_id') or entry.get('paper_id')
        for tid,entry in entries.items() if tid in live and (entry.get('active_paper_id') or entry.get('paper_id'))}))
    with catalog.connect() as db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cards={row['paper_id']:dict(row) for row in db.execute('SELECT paper_id,state,selection FROM web_card_jobs '
            'WHERE paper_id IN (SELECT value FROM json_each(?))',(card_ids,))} if 'web_card_jobs' in tables else {}
        reviews={row['id']:dict(row) for row in db.execute('SELECT id,paper_id,state FROM card_review_jobs')} if 'card_review_jobs' in tables else {}
    result={}
    for page in observation.get('pages',[]):
        tid=page.get('target_id');checked=page.get('checked_at',0);entry=entries.get(tid,{})
        if (tid not in live or tid in result or page.get('activity_verified') is not True
                or not isinstance(checked,(int,float)) or not 0<=at-checked<30
                or entry.get('state') not in ('busy','submitting','submitted','collecting','submission_started','needs_inspection')
                or not (page.get('streaming') is True or page.get('complete') is True and page.get('answers',0)>0)):
            continue
        record=latest.get(tid,{})
        try:
            path=Path(record['_ledger_path']);attempt=json.loads(path.read_text())
        except (OSError,ValueError,KeyError,TypeError):continue
        url=page.get('url','')
        if (attempt.get('target_id')!=tid or attempt.get('state') not in ('submitted','submission_started','needs_inspection','response_saved')
                or not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url
                or attempt.get('conversation_url')!=url or not attempt.get('actual_prompt_sha256')):continue
        lane=page.get('kind')
        if lane=='review':
            jid=attempt.get('review_id');job=reviews.get(jid)
            if not job or job['state'] in TERMINAL and page.get('streaming') is not True:continue
            if entry.get('review_id') not in (None,jid):continue
            pid=job['paper_id']
        elif lane in ('cards','correction'):
            pid=entry.get('active_paper_id') or entry.get('paper_id');job=cards.get(pid)
            if not job or job['state'] in ('completed','protected') or web_job_kind(job)!=lane:continue
            if path.parent.parent.name!=pid:continue
            jid=json.loads(job['selection']).get('rework',{}).get('correction_id') if lane=='correction' else pid
            if not jid:continue
        else:continue
        result[tid]={'lane':lane,'job_id':jid,'paper_id':pid}
    return result


def refill_backlog(catalog,config,*,remaining,current_tasks,queued_tasks,eligible_pages):
    """Add only new eligible downloaded cards and existing GPT review candidates.

    The caller rate-limits this local operation. It uses a temporary preparation
    stock target and never rewrites persisted concurrency, pauses or retry rows.
    """
    from review.api import card_review_queue__enqueue as enqueue, card_review_queue__enabled as review_enabled
    from cards.api import web_card_service__enabled as cards_enabled
    from .shared_page_backlog import eligible_records
    from cards.api import web_card_queue__select as select
    # The original material producer maintains cycles. Page allocation must
    # not repeat its full frozen-material hashes on the resident CDP loop.
    added_review=enqueue(catalog,config,maintain_cycles=False) if review_enabled(config) else 0
    records=eligible_records(catalog,config)
    other=sum(record['lane']!='cards' for record in records)
    safe_cards=sum(record['lane']=='cards' for record in records)
    policy=config.get('web_cards',{}).get('shared_window',{}).get('backlog',{})
    target=policy.get('target_tasks',100)
    future_limit=max(0,int(target)-current_tasks)
    # Global review/correction stock cannot fill a card-only reserved page.
    # Keep real unsent card material for each available reserved future row,
    # even when other workflows have a very large unbound global queue.
    reserved_pages=min(config['web_cards'].get('min_reserved_pages',8),max(0,eligible_pages))
    reserved_stock=min(future_limit,reserved_pages*policy.get('queue_depth',4))
    desired=max(reserved_stock,max(0,future_limit-other))
    selection={}
    offset=0
    if cards_enabled(config):
        # select()'s legacy stock counter includes correction transports and
        # queued rows whose protected source is no longer eligible. They remain
        # untouched, but must not consume the new requested *card* inventory.
        with catalog.connect() as db:
            raw_pending=db.execute("SELECT count(*) FROM web_card_jobs WHERE state='queued' AND retry_at<=?",(time.time(),)).fetchone()[0]
        offset=max(0,raw_pending-safe_cards)
        local={**config,'web_cards':{**config['web_cards'],'refill_min_pending':desired+offset}}
        selection=select(catalog,local)
    return {'added_review':added_review,'cards_added':len(selection.get('added',[])),
            'cards_refilled':len(selection.get('refilled',[])),'requested_card_stock':desired,
            'reserved_card_stock':reserved_stock,'raw_pending_offset':offset,
            'remaining_before':remaining,'eligible_pages':eligible_pages}


def backlog_dispatch(catalog,config,entries,live_targets,status,*,inventory_complete=True,excluded_targets=(),pending_uploads=None):
    """Submit only an assigned page's ready head; preparation cannot be skipped."""
    from .shared_page_backlog import head_ready
    from .shared_page_dispatch import dispatch
    from cards.api import web_card_service__enabled as cards_enabled
    from review.api import card_review_queue__enabled as review_enabled
    from correction.api import card_correction_queue__enabled as correction_enabled
    allowed={'cards':cards_enabled(config),'review':review_enabled(config),'correction':correction_enabled(config)}
    limits={'cards':config['web_cards'].get('max_parallel_jobs',20),
            'review':config.get('card_review',{}).get('parallel_jobs',4),
            'correction':config.get('card_correction',{}).get('parallel_jobs',4)}
    # Existing activity remains protected even when current observation is stale.
    allocation=dispatch(entries,live_targets,cards_limit=limits['cards'],review_limit=limits['review'],
        correction_limit=limits['correction'],cards_min_pages=config['web_cards'].get('min_reserved_pages',8),
        queue_heads={'cards':[],'review':[],'correction':[]},cards_pending=False,review_pending=False,
        correction_pending=False,cards_allowed=allowed['cards'],review_allowed=allowed['review'],
        correction_allowed=allowed['correction'],hold_card_reservation=True,
        inventory_complete=inventory_complete,excluded_targets=excluded_targets)
    reserved=set(status.get('reserved_targets',[]));excluded=set(excluded_targets)
    from .shared_page_backlog import fixed_reservations
    # An invalid control makes the caller's inventory non-dispatchable. Do not
    # reread that control through fixed_reservations and abort original collection.
    fixed = fixed_reservations(config, catalog) if inventory_complete else None
    fixed_owner = {target: lane for lane, targets in (fixed or {}).items() for target in targets}
    borrowable=set(status.get('idle_borrow_targets',[])) if config.get('web_cards',{}).get('shared_window',{}).get('backlog',{}).get('idle_borrow_enabled') is True else set()
    fixed_cards = set((fixed or {}).get('cards', [])) if fixed else set()
    shared_targets = set(live_targets) - set(fixed_owner) if fixed else set()
    leftover = config.get('web_cards', {}).get('shared_window', {}).get('backlog', {}).get(
        'leftover_order', ['correction', 'review'])
    if not isinstance(leftover, (list, tuple)) or set(leftover) - set(('cards', 'review', 'correction')):
        raise ValueError('leftover_order must contain cards/review/correction')
    leftover_rank = {lane: index for index, lane in enumerate(leftover)}
    protected=set(allocation['protected_targets'])|set(status.get('protected_targets',[]))
    allocation.update(protected_targets=sorted(protected),protected=len(protected),capacity=max(0,20-len(protected)))
    ready={lane:[] for lane in allowed};claims=[]
    if inventory_complete:
        for tid in live_targets:
            if tid in excluded or tid in protected or entries.get(tid,{}).get('state') not in ('ready','ready_blank'):continue
            head=head_ready(catalog,config,tid)
            if not head or tid in reserved and head['lane']!='cards' and tid not in borrowable:continue
            if tid in fixed_owner and head['lane'] != fixed_owner[tid] and tid not in borrowable:continue
            # Cards are the fixed input lane.  Shared pages are reserved for
            # correction first, then review; a card must not consume them.
            if fixed and tid in shared_targets and head['lane'] == 'cards' and tid not in borrowable:continue
            claims.append({**head,'target_id':tid,'reserved':tid in reserved})
        from core.api import workflow_priority__key as key, workflow_priority__enabled as score_order
        minima={'cards':config['web_cards'].get('min_reserved_pages',8),
                'review':config.get('card_review',{}).get('min_reserved_pages',4),
                'correction':config.get('card_correction',{}).get('min_reserved_pages',3)}
        def minimum_priority(row):
            lane=row['lane'];minimum=minima[lane]
            reserved_for_lane=fixed_owner.get(row['target_id'])==lane or lane=='cards' and row['reserved']
            lane_key='card' if lane=='cards' else lane
            active_targets={tid for tid in allocation[lane_key+'_targets']
                            if entries.get(tid,{}).get('state') in ('busy','submitting','submitted','collecting','submission_started')}
            occupied=max(allocation['active'][lane],len(active_targets|set((pending_uploads or {}).get(lane,()))))
            # A fast-lane article may not steal the last reserved capacity of a
            # lane that is still below its authorized minimum.  Fill minima
            # first; fast lane then wins across lanes that already have their
            # minimum resources.
            if reserved_for_lane and occupied<minimum:
                return (0,occupied/minimum)
            if row.get('fast_lane'):
                return (-1,0)
            return (1,0)
        def shared_rank(row):
            return leftover_rank.get(row['lane'], 99) if row['target_id'] in shared_targets else 0
        claims.sort(key=lambda row:(not row.get('seed_fast_lane',False),minimum_priority(row),shared_rank(row),key(row),not row['reserved'],row['target_id']) if score_order(config) else
                    (not row.get('seed_fast_lane',False),not row['reserved'],shared_rank(row),key(row),row['target_id']))
        claims=[row for row in claims if allowed[row['lane']]]
        permitted=[]
        for row in claims:
            lane=row['lane']
            if allocation['active'][lane]+len(ready[lane])>=limits[lane]:continue
            ready[lane].append(row['target_id']);permitted.append(row)
        claims=permitted
    held=[tid for tid in reserved if entries.get(tid,{}).get('state') in ('ready','ready_blank') and tid not in ready['cards'] and tid not in borrowable]
    for lane,key in (('cards','card'),('review','review'),('correction','correction')):
        original=[tid for tid in allocation[key+'_targets'] if entries.get(tid,{}).get('state') not in ('ready','ready_blank')]
        allocation[key+'_ready']=ready[lane]
        allocation[key+'_targets']=original+ready[lane]+(held if lane=='cards' else [])
        allocation['budget'][lane]=min(limits[lane],allocation['active'][lane]+len(ready[lane])+(len(held) if lane=='cards' else 0)) if allowed[lane] else 0
        allocation['status'][lane]='ready' if ready[lane] else 'running' if allocation['active'][lane] else 'paused' if not allowed[lane] else 'waiting_queue'
    allocation.update(claim_order=claims,ready_jobs={row['target_id']:row for row in claims},
        reserved_idle_targets=held,reserved_capacity=len(reserved),cards_min_shortfall=status.get('cards_min_shortfall',0),
        policy='assigned_mixed_page_score' if status.get('queue_order')=='paper_score' else 'assigned_mixed_page_fifo',backlog=status)
    return allocation
