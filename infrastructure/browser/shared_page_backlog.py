"""Durable mixed future work on the keeper's twenty fixed browser pages.

Only this local binding table and the existing card-material target mirror are
changed. Original arrivals, source jobs, inputs, attempts and controls are never
rewritten. The owner supplies *verified* current bindings: an old busy entry is
not inventory. Every page has four future positions; its current request stays
on its original target, including a claimed request whose receipt is uncertain.
"""
from collections.abc import Mapping
from contextvars import ContextVar
import json
import math
from core.api import paths__WorkspacePath as Path
import time

from .shared_page_dispatch import ACTIVE_STATES, READY_STATES, UNKNOWN_STATES
from .upload_retry_policy import due as upload_due

LANES = ('cards', 'review', 'correction')
PENDING = frozenset(('queued', 'preparing', 'ready'))
MATERIAL_PENDING = frozenset(('waiting', 'preparing', 'ready'))
UNCERTAIN = frozenset(('preparing', 'submitting', 'submitted', 'collecting',
                       'needs_inspection', 'needs_user'))
_HASH_CHECKPOINT = ContextVar('backlog_hash_checkpoint', default=None)
# One latest proven version per observed path. A small LRU thrashes when the
# pending corpus exceeds its capacity, including again under the write lock.
_DIGEST_VERSIONS = {}


def enabled(config):
    shared = config.get('web_cards', {}).get('shared_window', {})
    return shared.get('enabled') is True and shared.get('backlog', {}).get('enabled') is True


def _policy(config):
    value = config.get('web_cards', {}).get('shared_window', {}).get('backlog', {})
    policy = {'low_watermark': value.get('low_watermark', 70),
              'target_tasks': value.get('target_tasks', 100),
              'queue_depth': value.get('queue_depth', 4)}
    for key, maximum in (('low_watermark', 100), ('target_tasks', 100), ('queue_depth', 4)):
        if type(policy[key]) is not int or not 1 <= policy[key] <= maximum:
            raise ValueError('Invalid shared backlog ' + key)
    if policy['low_watermark'] > policy['target_tasks']:
        raise ValueError('Backlog low watermark exceeds target tasks')
    return policy


def fixed_reservations(config, catalog):
    """Resolve persistent slot identities without changing browser ownership."""
    value = config.get('web_cards', {}).get('shared_window', {}).get('fixed_lane_slots')
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(LANES):
        raise ValueError('Invalid fixed lane slots')
    if any(not isinstance(value[lane], list) for lane in LANES):
        raise ValueError('Invalid fixed lane slots')
    ids = [sid for lane in LANES for sid in value[lane]]
    if (any(not isinstance(value[lane], list) for lane in LANES) or
            any(not isinstance(sid, str) for sid in ids) or len(ids) != len(set(ids)) or len(ids) > 20):
        raise ValueError('Invalid fixed lane slot identities')
    from .shared_browser_window import validate_registry
    registry = json.loads((catalog.path.parent / 'shared-gpt-window.json').read_text())
    validate_registry(registry)
    targets = {slot['slot_id']: slot.get('target_id') for slot in registry['slots']}
    if any(sid not in targets for sid in ids):
        raise ValueError('Fixed lane slot is not registered')
    from core.api import concurrency_control__settings as settings
    minima=settings(config)
    allowed=_allowed(config)
    result={lane:[targets[sid] for sid in value[lane] if targets[sid]][:minima[lane+'_min_pages']] if allowed[lane] else [] for lane in LANES}
    root=catalog.path.parent
    pool_path=root/'gpt-window-pool.json';service_path=root/'web-card-service.json'
    pool=json.loads(pool_path.read_text()).get('windows',{}) if pool_path.exists() else {}
    previous=json.loads(service_path.read_text()).get('shared_backlog',{}).get('lane_reserved_targets',{}) if service_path.exists() else {}
    used={tid for row in result.values() for tid in row}
    for lane in LANES:
        if not allowed[lane]:continue
        candidates=list(dict.fromkeys(previous.get(lane,[])+list(targets.values())))
        for tid in candidates:
            if len(result[lane])>=minima[lane+'_min_pages']:break
            entry=pool.get(tid,{})
            compatible=entry.get('state') in ('ready','ready_blank') or (entry.get('kind')==lane and entry.get('state') in ACTIVE_STATES)
            if tid and tid in targets.values() and tid not in used and compatible:
                result[lane].append(tid);used.add(tid)
    return result


def install(catalog):
    from .shared_workflow_queue import install as arrivals_install
    arrivals_install(catalog)
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS shared_page_backlog(
            lane TEXT NOT NULL CHECK(lane IN ('cards','review','correction')),
            job_id TEXT NOT NULL, paper_id TEXT NOT NULL, target_id TEXT NOT NULL,
            assigned REAL NOT NULL, state TEXT NOT NULL DEFAULT 'queued'
                CHECK(state IN ('queued','claimed')), PRIMARY KEY(lane,job_id))''')
        db.execute('CREATE INDEX IF NOT EXISTS shared_backlog_target ON shared_page_backlog(target_id,state)')
        db.execute('''CREATE TABLE IF NOT EXISTS shared_page_idle(
            target_id TEXT PRIMARY KEY, identity TEXT NOT NULL, idle_since REAL NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS shared_page_backlog_meta(
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
            last_reconciled REAL NOT NULL, low_watermark INTEGER NOT NULL,
            target_tasks INTEGER NOT NULL, queue_depth INTEGER NOT NULL,
            triggered INTEGER NOT NULL, total_tasks INTEGER NOT NULL,
            queued_tasks INTEGER NOT NULL, current_tasks INTEGER NOT NULL,
            eligible_pages INTEGER NOT NULL, reserved_targets TEXT NOT NULL,
            status TEXT NOT NULL, paused_queued_count INTEGER NOT NULL DEFAULT 0)''')


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _idle_borrow_targets(db, config, entries, eligible, active, fixed_owner, sources, guards, bindings, stamp):
    """Persist verified idle periods; retain enough dedicated pages for own work."""
    if config.get('web_cards',{}).get('shared_window',{}).get('backlog',{}).get('idle_borrow_enabled') is not True:
        return []
    from .stall_timeouts import timeout_seconds
    import hashlib
    policy=config['web_cards']['shared_window'].get('health_repair',{})
    blocked={row['target_id'] for key,row in bindings.items() if row['state']=='queued'
             and (key not in sources or guards.get(key))}
    idle=[tid for tid in eligible if tid not in active and tid not in blocked
          and entries[tid].get('state') in ('ready','ready_blank')]
    for row in db.execute('SELECT target_id FROM shared_page_idle').fetchall():
        if row['target_id'] not in idle:
            db.execute('DELETE FROM shared_page_idle WHERE target_id=?',(row['target_id'],))
    due=[]
    for tid in idle:
        entry=entries[tid]
        identity=hashlib.sha256(json.dumps({k:entry.get(k) for k in
            ('state','kind','active_paper_id','paper_id','review_id','correction_id','raw_sha256','conversation_url','repair_id')},
            sort_keys=True).encode()).hexdigest()
        old=db.execute('SELECT identity,idle_since FROM shared_page_idle WHERE target_id=?',(tid,)).fetchone()
        since=old['idle_since'] if old and old['identity']==identity else stamp
        db.execute('INSERT INTO shared_page_idle VALUES(?,?,?) ON CONFLICT(target_id) DO UPDATE SET '
                   'identity=excluded.identity,idle_since=excluded.idle_since',(tid,identity,since))
        limit=timeout_seconds(policy,{'kind':fixed_owner.get(tid) or entry.get('kind')})
        if limit is not None and stamp-since>=limit:
            due.append(tid)
    allowed=_allowed(config)
    demand={lane:sum(record['lane']==lane and allowed[lane] and not guards[key] and upload_due(record)
        and bindings.get(key,{}).get('state')!='claimed' for key,record in sources.items()) for lane in LANES}
    # Reserve one idle dedicated page per legal own task before lending extras,
    # including tasks still preparing their source-only material.
    retained=set()
    for lane in LANES:
        own=[tid for tid in idle if fixed_owner.get(tid)==lane]
        retained.update(own[:demand[lane]])
    return [tid for tid in due if tid not in retained]


def _allowed(config):
    from cards.api import web_card_service__enabled as cards_enabled
    from review.api import card_review_queue__enabled as review_enabled
    from correction.api import card_correction_queue__enabled as correction_enabled
    return {'cards': cards_enabled(config), 'review': review_enabled(config),
            'correction': correction_enabled(config)}


def _json(value):
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('Invalid queue record')
    return result


def _source_records(db, now, config=None, *, bound_papers=None):
    """Real unsent source records, including preparation that uses no webpage."""
    tables = _tables(db)
    result = {}
    if 'shared_workflow_arrivals' not in tables:
        return result
    if bound_papers is not None and not bound_papers:
        return result
    scope = " AND paper_id IN (SELECT value FROM json_each(?))" if bound_papers is not None else ""
    params = (json.dumps(sorted(bound_papers)),) if scope else ()
    arrival_query = 'SELECT a.* FROM shared_workflow_arrivals a'
    if scope:
        arrival_query += (' JOIN shared_page_backlog b USING(lane,job_id) '
                          'WHERE b.paper_id IN (SELECT value FROM json_each(?))')
    arrivals = {(row['lane'], row['job_id']): dict(row)
                for row in db.execute(arrival_query, params)}
    if 'web_card_jobs' in tables:
        material = {row['paper_id']: dict(row) for row in db.execute('SELECT * FROM web_page_queue WHERE 1=1'+scope, params)} if 'web_page_queue' in tables else {}
        corrections = {row['id']: dict(row) for row in db.execute('SELECT * FROM card_correction_jobs WHERE 1=1'+scope, params)} if 'card_correction_jobs' in tables else {}
        for row in db.execute("SELECT * FROM web_card_jobs WHERE state='queued' AND retry_at<=?"+scope, (now, *params)):
            job = dict(row)
            try:
                selection = _json(job['selection'])
                rework = selection.get('rework') or {}
                if not isinstance(rework, dict):
                    continue
                lane = 'correction' if rework.get('kind') == 'source_review' or rework.get('correction_id') else 'cards'
                job_id = rework.get('correction_id') if lane == 'correction' else job['paper_id']
                if not job_id:
                    continue
                correction = corrections.get(job_id) if lane == 'correction' else None
                if lane == 'correction' and (not correction or correction['paper_id'] != job['paper_id'] or
                        correction['kind'] != 'source_rework' or correction['state'] not in PENDING or
                        correction['source_sha256'] != job['source_sha256']):
                    continue
                queue = material.get(job['paper_id'])
                if queue and queue['state'] not in MATERIAL_PENDING:
                    continue
                arrival = arrivals.get((lane, job_id))
                if not arrival:
                    continue
                result[(lane, job_id)] = {**arrival, 'lane': lane, 'job_id': job_id,
                    'paper_id': job['paper_id'], 'source_job': job, 'material': queue,
                    'correction': correction,
                    'state': queue['state'] if queue else 'waiting',
                    'ready': bool(queue and queue['state'] == 'ready' and
                                  (correction is None or correction['state'] == 'ready'))}
            except (ValueError, TypeError, KeyError):
                continue
    if 'card_review_jobs' in tables:
        for row in db.execute("SELECT * FROM card_review_jobs WHERE state IN ('queued','preparing','ready')"+scope, params):
            job = dict(row)
            arrival = arrivals.get(('review', job['id']))
            if arrival:
                result[('review', job['id'])] = {**arrival, 'lane': 'review',
                    'job_id': job['id'], 'paper_id': job['paper_id'], 'source_job': job,
                    'material': None, 'correction': None, 'state': job['state'],
                    'ready': job['state'] == 'ready'}
    from core.api import workflow_priority__annotate as annotate
    annotate(db, result.values(), config or {})
    from .upload_retry_policy import annotate as upload_annotate
    upload_annotate(db, result.values(), config or {}, at=now)
    from core.api import seed_focus__filter_records as focus_filter
    admitted={(r['lane'],r['job_id']) for r in focus_filter(db,result.values(),config)}
    return {key:record for key,record in result.items() if key in admitted}


def _unsent(path):
    if not path.exists():
        return True
    attempt = _json(path.read_text())
    return attempt.get('state') in ('not_sent', 'deferred') and attempt.get('send_click_started') is False


def _stat_key(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _digest_version(path, version):
    cached=_DIGEST_VERSIONS.get(path)
    if cached is not None and cached[0]==version:return cached[1]
    from cards.api import web_card_inputs__digest as digest
    checkpoint=_HASH_CHECKPOINT.get()
    if checkpoint is None:result=digest(path)
    else:
        from cards.api import web_card_retry__cooperative_digest as cooperative_digest
        result=cooperative_digest(path,checkpoint)
    if _stat_key(Path(path)) != version:
        raise ValueError('Fingerprint changed during inventory inspection')
    _DIGEST_VERSIONS[path]=(version,result)
    return result


def _fingerprint(path):
    """Cache only proven file versions, never missing/unreadable evidence.

    This is local scheduling evidence. The original before-send guard still
    reads the complete frozen inputs and source, without using this cache.
    """
    resolved = path.resolve()
    version = _stat_key(resolved)
    result = _digest_version(str(resolved), version)
    if _stat_key(resolved) != version:
        raise ValueError('Fingerprint changed during inventory inspection')
    return result


def _guard(db, catalog, config, record):
    """Binding eligibility is stricter than an old queued label alone.

    Sending still requires the owner's original frozen-input/model/URL checks.
    Historical archived answers are not made into new requests by this helper.
    """
    row = db.execute('SELECT * FROM papers WHERE id=?', (record['paper_id'],)).fetchone()
    if row is None:
        return 'missing source identity'
    paper = dict(row)
    try:
        paper['metadata'] = _json(paper['metadata'])
        job = record['source_job']
        if any(paper['metadata'].get(key) for key in ('identity_review_required', 'version_review_required', 'out_of_scope')):
            return 'source identity, version or scope requires review'
        if not job['source_sha256'] or paper.get('asset_hash') != job['source_sha256']:
            return 'source fingerprint differs'
        source = Path(paper.get('asset_path') or '')
        if paper['acquisition'] != 'available' or not source.is_file() or _fingerprint(source) != job['source_sha256']:
            return 'original source changed or unavailable'
        human = db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'", (record['paper_id'],)).fetchone()
        if record['lane'] == 'review':
            # Current card/version and active attempt are bound before preparing.
            card = Path(paper.get('card_path') or '')
            expected = Path(config['studio_library_root']) / record['paper_id'] / 'card.json'
            versioned=(card.name=='card.json' and card.parent.parent.name=='publications'
                       and card.parent.parent.parent.resolve()==expected.parent.resolve())
            if not card.is_file() or (card.resolve()!=expected.resolve() and not versioned) or _fingerprint(card)!=job['card_sha256']:
                return 'card fingerprint differs'
            if (Path(job['folder']) / 'attempt.json').exists():
                # The review transport refuses any active attempt ledger. A
                # proven pause before page use is archived by its original
                # owner first; scheduling never removes a ledger to enable send.
                return 'review request already has an active receipt'
        else:
            # The rework authorization uses the same unchanged-file evidence
            # cache here; the original final guard rehashes before each send.
            rework = _json(job['selection']).get('rework')
            if rework:
                if not isinstance(rework, dict):
                    return 'rework evidence is unreadable'
                old = Path(rework['old_card_path'])
                backup = Path(rework['backup']) / 'card.json'
                if (paper.get('card_path') != str(old) or not old.is_file() or
                        _fingerprint(old) != rework['old_sha256'] or not backup.is_file() or
                        _fingerprint(backup) != rework['old_sha256']):
                    return 'rework original card or backup differs'
            if rework and rework.get('kind')=='manual_seed_trial' and (human or paper['decision']!='unreviewed'):
                return 'human-protected independent seed generation'
            if rework and rework.get('kind') == 'source_review':
                if human or paper['decision'] != 'unreviewed':
                    return 'human-protected scientific rework'
                correction = record['correction']
                if not correction or correction['card_sha256'] != rework['old_sha256']:
                    return 'correction old card differs'
            elif not rework and (human or paper['decision'] != 'unreviewed' or paper.get('card_path') or
                    (Path(config['studio_library_root']) / record['paper_id'] / 'card.json').exists()):
                return 'existing or human-protected card'
            folder = catalog.path.parent / 'web_cards' / record['paper_id']
            for path in folder.glob('*/attempt.json'):
                if not _unsent(path):
                    return 'card request may already be sent'
    except (OSError, ValueError, KeyError, TypeError):
        return 'source, material or receipt evidence is unreadable'
    return ''


def _fifo(record):
    from core.api import workflow_priority__key as key
    return key(record)


def eligible_records(catalog, config):
    """Read genuine runnable unsent stock for the owner's limited refill scan."""
    allowed = _allowed(config)
    with catalog.connect() as db:
        claimed = {(row['lane'], row['job_id']) for row in db.execute("SELECT lane,job_id FROM shared_page_backlog WHERE state='claimed'")} if 'shared_page_backlog' in _tables(db) else set()
        records = _source_records(db, time.time(), config)
        return sorted(({key: value for key, value in record.items()
                        if key not in ('source_job', 'material', 'correction')}
                       for key, record in records.items() if key not in claimed and allowed[record['lane']] and
                       upload_due(record) and not _guard(db, catalog, config, record)), key=_fifo)


def rows(catalog, config=None):
    """Read bindings without installing schema or mutating a source queue."""
    with catalog.connect() as db:
        if 'shared_page_backlog' not in _tables(db):
            return []
        bindings = list(db.execute('SELECT b.*,a.queued_at,a.sequence,a.basis FROM shared_page_backlog b '
                'LEFT JOIN shared_workflow_arrivals a USING(lane,job_id) ORDER BY a.queued_at,a.sequence,b.lane,b.job_id'))
        sources = _source_records(db, time.time(), config, bound_papers={row['paper_id'] for row in bindings})
        result = []
        for row in bindings:
            record = dict(row)
            source = sources.get((row['lane'], row['job_id']))
            record.update(material_state=source['state'] if source else None,
                          ready=bool(source and source['ready']),
                          upload_due=upload_due(source) if source else True)
            if source and not upload_due(source):
                record['upload_cooldown_until'] = source.get('upload_cooldown_until')
                record['upload_policy_error'] = source.get('upload_policy_error')
            result.append(record)
        return result


def binding(catalog, lane, job_id):
    with catalog.connect() as db:
        if 'shared_page_backlog' not in _tables(db):
            return None
        row = db.execute('SELECT * FROM shared_page_backlog WHERE lane=? AND job_id=?', (lane, job_id)).fetchone()
        return dict(row) if row else None


def check_binding(db, lane, job_id, target_id, *, state='queued'):
    return bool(db.execute('SELECT 1 FROM shared_page_backlog WHERE lane=? AND job_id=? AND target_id=? AND state=?',
                          (lane, job_id, target_id, state)).fetchone())


def check_claim_binding(db, lane, job_id, target_id):
    return check_binding(db, lane, job_id, target_id, state='claimed')


def mark_claimed(db, lane, job_id, target_id):
    """Call inside the same BEGIN IMMEDIATE as the original source-job CAS."""
    return db.execute("UPDATE shared_page_backlog SET state='claimed' WHERE lane=? AND job_id=? AND target_id=? AND state='queued'",
                      (lane, job_id, target_id)).rowcount == 1


def rollback_claim(db, lane, job_id, target_id):
    """Owner CAS only after proving pause before page use and before send."""
    return db.execute("UPDATE shared_page_backlog SET state='queued' WHERE lane=? AND job_id=? AND target_id=? AND state='claimed'",
                      (lane, job_id, target_id)).rowcount == 1


def remove_binding(db, lane, job_id, target_id, *, expected_state=None):
    """Owner-only release, after original answer or explicit unsent evidence."""
    clause = ' AND state=?' if expected_state else ''
    args = (lane, job_id, target_id, expected_state) if expected_state else (lane, job_id, target_id)
    return db.execute('DELETE FROM shared_page_backlog WHERE lane=? AND job_id=? AND target_id=?' + clause, args).rowcount


def _head(db, catalog, config, target_id):
    if 'shared_page_backlog' not in _tables(db):
        return None
    if db.execute("SELECT 1 FROM shared_page_backlog WHERE target_id=? AND state='claimed'", (target_id,)).fetchone():
        return None
    allowed = _allowed(config)
    bindings = list(db.execute("SELECT b.*,a.queued_at,a.sequence FROM shared_page_backlog b JOIN shared_workflow_arrivals a USING(lane,job_id) "
                          "WHERE b.target_id=? AND b.state='queued' ORDER BY a.queued_at,a.sequence,b.job_id,b.lane", (target_id,)))
    records = _source_records(db, time.time(), config, bound_papers={row['paper_id'] for row in bindings})
    bindings = sorted(bindings, key=lambda row: _fifo({**dict(row), **records.get((row['lane'], row['job_id']), {})}))
    for row in bindings:
        from core.api import seed_focus__filter_records as focus_filter
        if not focus_filter(db,[dict(row)],config):continue
        if not allowed[row['lane']]:
            continue  # A separate paused lane must not stop other workflows.
        record = records.get((row['lane'], row['job_id']))
        if not record or record['paper_id'] != row['paper_id'] or not record['ready']:
            return None  # Preparation retains this page's runnable FIFO head.
        if record['material'] and record['material']['target_id'] != target_id:
            return None
        if _guard(db, catalog, config, record):
            return None
        if not upload_due(record):
            # A recorded upload wait skips only this proven unclaimed material;
            # the page keeps its slot and the later due item takes its turn.
            continue
        return {key: value for key, value in {**record, **dict(row)}.items()
                if key not in ('source_job', 'material', 'correction')}
    return None


def head_ready(catalog, config, target_id):
    with catalog.connect() as db:
        return _head(db, catalog, config, target_id)


def check_head_binding(db, config, lane, job_id, target_id):
    from core.api import catalog__Catalog as Catalog
    # Reuse the caller's transaction; constructing a Catalog would install schema.
    catalog = object.__new__(Catalog)
    catalog.path = Path(config['catalog_path'])
    record = _head(db, catalog, config, target_id)
    return bool(record and record['lane'] == lane and record['job_id'] == job_id)


def _destinations(entries, live_targets, active_targets):
    targets = set(live_targets)
    if len(targets) > 20 or not all(isinstance(target, str) and target for target in targets):
        raise ValueError('Backlog requires at most twenty fixed target IDs')
    if not isinstance(active_targets, Mapping):
        raise ValueError('active_targets must map verified targets to current bindings')
    active = {}
    eligible, protected = [], []
    def order(target):
        slot = entries.get(target, {}).get('slot')
        return slot if type(slot) is int else 21, target
    for target in sorted(targets, key=order):
        entry = entries.get(target)
        value = active_targets.get(target)
        blocked = (not isinstance(entry, Mapping) or entry.get('owned') is False or
            entry.get('eligible') is False or entry.get('external') or entry.get('submission_unknown') or
            entry.get('verification_required') or entry.get('ledger_state') in UNKNOWN_STATES or
            entry.get('attempt_state') in UNKNOWN_STATES or entry.get('draft') or entry.get('has_draft') or
            entry.get('draft_text') or entry.get('attachments') or entry.get('uploading') or entry.get('repair_in_progress'))
        verified = (isinstance(value, Mapping) and value.get('lane') in LANES and
                    isinstance(value.get('job_id'), str) and value.get('job_id') and
                    isinstance(value.get('paper_id'), str) and value.get('paper_id'))
        if blocked:
            protected.append(target)
        elif entry.get('state') in READY_STATES:
            eligible.append(target)
        elif entry.get('state') in ACTIVE_STATES and verified:
            eligible.append(target)
            active[target] = dict(value)
        else:
            protected.append(target)
    return eligible, protected, active


def _write_binding(db, record, target, stamp):
    key = (record['lane'], record['job_id'])
    old = db.execute('SELECT target_id,state FROM shared_page_backlog WHERE lane=? AND job_id=?', key).fetchone()
    if old and old['state'] != 'queued':
        return False
    if record['lane'] != 'review':
        material = db.execute('SELECT state FROM web_page_queue WHERE paper_id=?', (record['paper_id'],)).fetchone()
        if material and material['state'] not in MATERIAL_PENDING:
            return False
        if material:
            db.execute('UPDATE web_page_queue SET target_id=? WHERE paper_id=?', (target, record['paper_id']))
        else:
            db.execute("INSERT INTO web_page_queue(paper_id,target_id,state,assigned) VALUES(?,?,'waiting',?)", (record['paper_id'], target, stamp))
    db.execute("INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES(?,?,?,?,?,'queued') "
               "ON CONFLICT(lane,job_id) DO UPDATE SET target_id=excluded.target_id,assigned=CASE WHEN shared_page_backlog.target_id=excluded.target_id THEN shared_page_backlog.assigned ELSE excluded.assigned END",
               (*key, record['paper_id'], target, stamp))
    return True


def _cleanup(db,config=None):
    """Retire only queued bindings; uncertain claimed requests remain pinned."""
    tables = _tables(db)
    for row in list(db.execute("SELECT * FROM shared_page_backlog WHERE state='queued'")):
        table, column = ('card_review_jobs', 'id') if row['lane'] == 'review' else ('web_card_jobs', 'paper_id')
        key = row['job_id'] if row['lane'] == 'review' else row['paper_id']
        source = db.execute(f'SELECT state FROM {table} WHERE {column}=?', (key,)).fetchone() if table in tables else None
        state = source['state'] if source else None
        pending = PENDING if row['lane'] == 'review' else frozenset(('queued',))
        if state in pending:
            from core.api import seed_focus__filter_records as focus_filter
            if config and state in ('queued','ready') and not focus_filter(db,[dict(row)],config):
                # Hold only untouched future bindings, preserving the global source/FIFO and prepared files.
                import hashlib
                from core.api import services__atomic_json as atomic_json
                original=dict(row);identity=hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()
                path=Path(config['catalog_path']).parent/'seed-focus-held-bindings'/(identity+'.json')
                if not path.exists():atomic_json(path,{'original_binding':original,'held_at':time.time(),'source_and_arrival_unchanged':True})
                remove_binding(db,row['lane'],row['job_id'],row['target_id'],expected_state='queued')
            continue
        if state in UNCERTAIN:
            db.execute("UPDATE shared_page_backlog SET state='claimed' WHERE lane=? AND job_id=?", (row['lane'], row['job_id']))
        else:
            remove_binding(db, row['lane'], row['job_id'], row['target_id'], expected_state='queued')


def _reservation(eligible, active, minimum, allowed, bindings):
    if not allowed['cards']:
        return []
    reserved = [target for target in eligible if active.get(target, {}).get('lane') == 'cards'][:minimum]
    heads = {}
    for row in sorted(bindings.values(), key=lambda row: (row.get('queued_at', float('inf')),
                                                         row.get('sequence', 0), row['job_id'])):
        if row['state'] == 'queued' and allowed[row['lane']]:
            heads.setdefault(row['target_id'], row['lane'])
    idle = [target for target in eligible if target not in active and target not in reserved]
    # Holding pages that already have a card at their runnable FIFO head avoids
    # blocking another lane merely because the minimum was changed at >=70.
    idle.sort(key=lambda target: (0 if heads.get(target) == 'cards' else 1 if target not in heads else 2,
                                  eligible.index(target)))
    return reserved + idle[:max(0, minimum - len(reserved))]


def reconcile(config, catalog, entries, live_targets, active_targets, *,
              inventory_complete=True, refill_callback=None, now=None,
              cards_min_pages=None, allowed=None, checkpoint=None, initialize=True):
    """Below 70 genuine tasks, safely refill/reflow toward 100 real positions.

    The optional callback is called once outside SQLite locks as
    ``callback(catalog, config, remaining=..., current_tasks=..., queued_tasks=...,
    eligible_pages=...)``. The owner limits its source scan frequency. An
    incomplete live inventory never assigns or reorders work. At/above the low
    watermark only migration/cleanup occurs, preserving existing bindings.
    """
    if initialize:
        install(catalog)
    policy = _policy(config)
    stamp = time.time() if now is None else now
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0:
        raise ValueError('Invalid reconciliation time')
    if cards_min_pages is None:
        from core.api import concurrency_control__settings as settings
        cards_min_pages = settings(config)['cards_min_pages']
    if type(cards_min_pages) is not int or not 1 <= cards_min_pages <= 20:
        raise ValueError('Invalid card reservation minimum')
    eligible, protected, active = _destinations(entries, live_targets, active_targets)
    allowed = _allowed(config) if allowed is None else {lane: bool(allowed.get(lane, False)) for lane in LANES}
    fixed = fixed_reservations(config, catalog)
    fixed_owner = {target: lane for lane, targets in (fixed or {}).items() for target in targets}
    reserved = []
    if allowed['cards']:
        reserved = [target for target in eligible if active.get(target, {}).get('lane') == 'cards'][:cards_min_pages]
        reserved += [target for target in eligible if target not in active and target not in reserved][:max(0, cards_min_pages - len(reserved))]
    refill = None

    def reconcile_transaction(do_reflow=False, force_trigger=False):
        nonlocal eligible, protected, active, reserved
        # Hash first-seen large originals outside the write lock. The locked
        # pass rechecks the complete version key, receipt and source-job state;
        # changed evidence cannot inherit a cached approval.
        token=_HASH_CHECKPOINT.set(checkpoint)
        try:
            with catalog.connect() as read_db:
                for record in _source_records(read_db, stamp, config).values():
                    if checkpoint is not None:checkpoint()
                    _guard(read_db, catalog, config, record)
        finally:_HASH_CHECKPOINT.reset(token)
        with catalog.connect() as db:
            if checkpoint is not None:
                db.execute('PRAGMA busy_timeout=0')
            db.execute('BEGIN IMMEDIATE')
            _cleanup(db,config)
            # A claimed original request cannot be made idle by a stale ready
            # entry. Only the exact newly observed binding can host future work.
            for row in db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'"):
                target = row['target_id']
                verified = active.get(target, {})
                if target in eligible and any(verified.get(key) != row[key] for key in ('lane','job_id','paper_id')):
                    eligible.remove(target)
                    protected.append(target)
                    active.pop(target, None)
            sources = _source_records(db, stamp, config)
            guards = {key: _guard(db, catalog, config, record) for key, record in sources.items()}
            live = set(live_targets)
            # A claim whose page vanished cannot make progress. Release it only
            # when there is no pending source job or the original page has no
            # send/unknown guard; source evidence and immutable arrival remain.
            for row in list(db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'")):
                if row['target_id'] in live:
                    continue
                key = (row['lane'], row['job_id'])
                source = sources.get(key)
                # Only an unguarded source still waiting to run is released.
                # Sent/unknown/needs-user jobs keep their original claim as
                # evidence even when their old page is gone.
                if (source is not None and not guards.get(key)
                        and source.get('state') in ('queued', 'preparing', 'ready')):
                    remove_binding(db, row['lane'], row['job_id'], row['target_id'], expected_state='claimed')
            bindings = {(row['lane'], row['job_id']): dict(row) for row in db.execute('SELECT * FROM shared_page_backlog')}
            # Genuine legacy card queues migrate in their original target, only
            # where a healthy current page and four physical positions exist.
            counts = {target: sum(row['state'] == 'queued' and row['target_id'] == target for row in bindings.values()) for target in eligible}
            if enabled(config) and inventory_complete:
                for key, record in sorted(sources.items(), key=lambda item: _fifo(item[1])):
                    material = record['material']
                    if key in bindings or not material or guards[key]:
                        continue
                    target = material['target_id']
                    if target not in counts or counts[target] >= policy['queue_depth']:
                        continue
                    # A paused original binding may be migrated, never newly
                    # allocated or moved to a different target.
                    if _write_binding(db, record, target, material['assigned']):
                        counts[target] += 1
                        bindings[key] = {'lane':key[0], 'job_id':key[1], 'paper_id':record['paper_id'], 'target_id':target, 'state':'queued'}
            arrival_bindings = {key: {**row, 'queued_at':sources[key]['queued_at'],
                                     'sequence':sources[key]['sequence']} if key in sources else row
                                for key,row in bindings.items()}
            reserved = ([target for target in fixed['cards'] if target in eligible]
                        if fixed is not None else _reservation(eligible,active,cards_min_pages,allowed,arrival_bindings))
            def runnable(key, row):
                return (row['state'] == 'queued' and key in sources and not guards[key] and
                        allowed[row['lane']] and upload_due(sources[key]) and
                        row['paper_id'] == sources[key]['paper_id'] and
                        row['target_id'] in eligible and
                        (not sources[key]['material'] or sources[key]['material']['target_id'] == row['target_id']))
            queued = sum(runnable(key, row) for key, row in bindings.items())
            current = len(active)
            borrowable=(_idle_borrow_targets(db,config,entries,eligible,active,fixed_owner,sources,guards,bindings,stamp)
                        if inventory_complete and fixed is not None else [])
            misplaced = fixed is not None and any(row['state'] == 'queued' and
                row['target_id'] in fixed_owner and fixed_owner[row['target_id']] != row['lane']
                and row['target_id'] not in borrowable
                and key in sources and not guards[key] and allowed[row['lane']]
                for key, row in bindings.items())
            manual_waiting = any((record.get('seed_fast_lane') or record.get('manual_priority')) and
                                 (key not in bindings or bindings[key]['state']=='queued')
                                 and not guards[key] and allowed[record['lane']]
                                 for key,record in sources.items())
            triggered = enabled(config) and (force_trigger or misplaced or manual_waiting or bool(borrowable) or current + queued < policy['low_watermark'])
            can_reflow = triggered and inventory_complete and bool(eligible)
            moved = added = 0
            if do_reflow and can_reflow:
                pinned = {key: row for key, row in bindings.items()
                          if row['state'] == 'claimed' or key not in sources or guards.get(key) or
                          not allowed[row['lane']] or not upload_due(sources[key])}
                candidates = sorted((record for key, record in sources.items()
                                     if allowed[record['lane']] and not guards[key] and key not in pinned), key=_fifo)
                future_limit = max(0, policy['target_tasks'] - current)
                # Pinning paused or protected material does not add runnable
                # stock, but it still occupies one real future position.
                loads = {target: sum(row['state'] == 'queued' and row['target_id'] == target for row in pinned.values()) for target in eligible}
                selected = []
                remaining_shared_work = sum(record['lane'] != 'cards' for record in candidates)
                for record in candidates:
                    destinations = [target for target in eligible if loads[target] < policy['queue_depth'] and
                                    (fixed_owner.get(target, record['lane']) == record['lane'] or target in borrowable if fixed is not None
                                     else record['lane'] == 'cards' or target not in reserved)]
                    if len(selected) >= future_limit:
                        break
                    if record['lane'] != 'cards':
                        remaining_shared_work -= 1
                    if fixed is not None and record['lane'] == 'cards':
                        # Card work uses dedicated slots or verified expired idle
                        # loans; otherwise shared slots retain their original policy.
                        destinations = [target for target in destinations if target in set(fixed.get('cards', [])) or target in borrowable]
                    if not destinations:
                        continue
                    # Seed each reserved card page before lending excess card
                    # work to the mixed pages. Then balance total current+future.
                    if record['lane'] == 'cards':
                        mixed_room = sum(max(0,policy['queue_depth']-loads[target])
                                         for target in eligible if target not in reserved)
                        card_room = [target for target in destinations if target in reserved]
                        if card_room and remaining_shared_work >= mixed_room:
                            destinations = card_room
                        empty_reserved = [target for target in destinations if target in reserved and
                                          not active.get(target) and loads[target] == 0]
                        if empty_reserved:
                            destinations = empty_reserved
                    if fixed is not None:
                        dedicated = [target for target in destinations if fixed_owner.get(target) == record['lane']
                                     and (not borrowable or not active.get(target) and loads[target]==0)]
                        if dedicated:
                            destinations = dedicated
                    target = min(destinations, key=lambda target: (loads[target] + int(target in active), eligible.index(target)))
                    selected.append((record, target))
                    loads[target] += 1
                for record, target in selected:
                    key = (record['lane'], record['job_id'])
                    old = bindings.get(key)
                    if _write_binding(db, record, target, stamp):
                        moved += bool(old and old['target_id'] != target)
                        added += old is None
                selected_keys = {(record['lane'], record['job_id']) for record, _ in selected}
                for key, row in bindings.items():
                    if key not in pinned and key not in selected_keys:
                        # Leave excess source jobs in the global queue, retaining
                        # their immutable arrival and any prepared packet.
                        remove_binding(db, *key, row['target_id'], expected_state='queued')
                bindings = {(row['lane'], row['job_id']): dict(row) for row in db.execute('SELECT * FROM shared_page_backlog')}
                # q target may have changed; reread the mirror in this transaction.
                sources = _source_records(db, stamp, config)
                queued = sum(runnable(key, row) for key, row in bindings.items())
            paused = sum(row['state'] == 'queued' and not allowed[row['lane']] for row in bindings.values())
            cooling = sum(row['state'] == 'queued' and key in sources and not upload_due(sources[key])
                          for key, row in bindings.items())
            total = current + queued
            state = 'disabled' if not enabled(config) else 'waiting_inventory' if not inventory_complete else 'shortfall' if triggered and total < policy['target_tasks'] else 'ready'
            from core.api import workflow_priority__enabled as score_order
            from core.api import concurrency_control__settings as settings
            lane_minima = settings(config)
            result = {**policy, 'enabled':enabled(config), 'last_reconciled':stamp,
                'queue_order': 'paper_score' if score_order(config) else 'fifo',
                'triggered':bool(triggered), 'current_tasks':current, 'queued_tasks':queued,
                'upload_cooldown_tasks':cooling,
                'total_tasks':total, 'ready_queued_tasks':sum(runnable(key,row) and sources[key]['ready'] for key,row in bindings.items()),
                'preparing_queued_tasks':sum(runnable(key,row) and not sources[key]['ready'] for key,row in bindings.items()),
                'paused_queued_count':paused, 'eligible_pages':len(eligible),
                'eligible_targets':eligible, 'protected_targets':protected,
                'reserved_targets':reserved, 'lane_reserved_targets':fixed or {'cards':reserved}, 'cards_min_pages':cards_min_pages,
                'idle_borrow_targets':borrowable,
                'cards_min_shortfall':max(0, cards_min_pages - len(reserved)) if allowed['cards'] else 0,
                'lane_min_shortfall':{lane:max(0,lane_minima[lane+'_min_pages']-len((fixed or {'cards':reserved}).get(lane,[]))) if allowed[lane] else 0 for lane in LANES},
                'physical_queued_tasks':sum(row['state'] == 'queued' for row in bindings.values()),
                'capacity':current + policy['queue_depth'] * len(eligible),
                'shortfall':max(0, policy['target_tasks'] - total), 'moved':moved, 'added':added,
                'status':state, 'inventory_complete':bool(inventory_complete)}
            db.execute('INSERT INTO shared_page_backlog_meta '
                '(id,enabled,last_reconciled,low_watermark,target_tasks,queue_depth,triggered,total_tasks,queued_tasks,current_tasks,eligible_pages,reserved_targets,status,paused_queued_count) '
                'VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                'enabled=excluded.enabled,last_reconciled=excluded.last_reconciled,low_watermark=excluded.low_watermark,'
                'target_tasks=excluded.target_tasks,queue_depth=excluded.queue_depth,triggered=excluded.triggered,'
                'total_tasks=excluded.total_tasks,queued_tasks=excluded.queued_tasks,current_tasks=excluded.current_tasks,'
                'eligible_pages=excluded.eligible_pages,reserved_targets=excluded.reserved_targets,status=excluded.status,'
                'paused_queued_count=excluded.paused_queued_count',
                (int(result['enabled']),stamp,policy['low_watermark'],policy['target_tasks'],policy['queue_depth'],
                 int(triggered),total,queued,current,len(eligible),json.dumps(reserved),state,paused))
            return result

    result = reconcile_transaction()
    trigger = result['triggered']
    if trigger and inventory_complete and eligible and refill_callback:
        refill = refill_callback(catalog, config, remaining=max(0, policy['target_tasks'] - result['total_tasks']),
                                current_tasks=result['current_tasks'], queued_tasks=result['queued_tasks'],
                                eligible_pages=len(eligible))
    if trigger and inventory_complete and eligible:
        result = reconcile_transaction(do_reflow=True, force_trigger=True)
        result['triggered'] = True  # Before refill is the threshold evidence.
    result['refill'] = refill
    return result


def preparation_head_ids(db, catalog, config, lane):
    """Actual assigned FIFO heads needing preparation, never claimed material."""
    if 'shared_page_backlog' not in _tables(db):return set()
    rows=db.execute("SELECT b.*,a.queued_at,a.sequence FROM shared_page_backlog b JOIN shared_workflow_arrivals a USING(lane,job_id) WHERE b.state='queued' AND NOT EXISTS (SELECT 1 FROM shared_page_backlog c WHERE c.target_id=b.target_id AND c.state='claimed')").fetchall()
    records=_source_records(db,time.time(),config,bound_papers={row['paper_id'] for row in rows});allowed=_allowed(config)
    heads={}
    for row in sorted(rows,key=lambda r:_fifo({**dict(r),**records.get((r['lane'],r['job_id']),{})})):
        if not allowed[row['lane']] or row['target_id'] in heads:continue
        heads[row['target_id']]=row
    return {r['job_id'] for r in heads.values() if r['lane']==lane}
