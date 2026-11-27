"""Version-bound corrections, separate from verification and browser ownership.

Local quote/whitespace corrections do not consume a browser page. Scientific
rework uses the existing source-only card transport, with a correction lease.
This module never connects to a browser or changes an uncertain send receipt.
"""
import fcntl
import hashlib
import json
import traceback
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from core.api import paths__WorkspacePath as Path

from core.api import catalog__Catalog as Catalog, catalog__now as now
from core.api import services__atomic_json as atomic_json
from cards.api import web_card_inputs__digest as digest

VERSION = 'independent-correction-v1'
STATES = ('queued', 'preparing', 'ready', 'submitted', 'applied', 'needs_user', 'superseded', 'failed')
TERMINAL = ('applied', 'needs_user', 'superseded', 'failed')


class CorrectionPaused(RuntimeError):
    """A pure user pause before a local publication or source-rework reset."""


def _require_running(config):
    from core.api import control__pause_decision as pause_decision
    decision=pause_decision(config,'card_correction',enabled=config.get('card_correction',{}).get('enabled') is True)
    if decision.state=='paused':
        raise CorrectionPaused(decision.reason)
    if not decision.allowed:
        raise ValueError('修正控制需核对：'+decision.reason)


def enabled(config):
    from core.api import control__pause_decision as pause_decision
    return (config.get('card_correction', {}).get('enabled') is True and
            pause_decision(config, 'card_correction').allowed)


def install(catalog):
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS card_correction_jobs(
          id TEXT PRIMARY KEY, review_id TEXT NOT NULL, paper_id TEXT NOT NULL,
          card_sha256 TEXT NOT NULL, source_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
          title TEXT NOT NULL, state TEXT NOT NULL, folder TEXT NOT NULL,
          payload TEXT NOT NULL, task_sha256 TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
          error TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, fifo_at REAL NOT NULL, queued_at REAL NOT NULL,
          updated TEXT NOT NULL, UNIQUE(review_id,kind))''')
        db.execute('CREATE INDEX IF NOT EXISTS correction_fifo ON card_correction_jobs(state,fifo_at,id)')
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f'CREATE TRIGGER IF NOT EXISTS revision_card_correction_jobs_{operation.lower()} '
                       f'AFTER {operation} ON card_correction_jobs '
                       'BEGIN UPDATE catalog_revision SET value=value+1 WHERE id=1; END')
    from browser.api import shared_workflow_queue__install as install_arrivals
    install_arrivals(catalog)


def rows(catalog):
    install(catalog)
    with catalog.connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM card_correction_jobs ORDER BY fifo_at,id')]


def update(catalog, cid, state, error='', result=None, *, expected=None, webjob=None):
    if state not in STATES:
        raise ValueError('未知修正阶段')
    transitions = {'queued':('preparing','needs_user','superseded','failed'),
        'preparing':('queued','ready','applied','needs_user','failed'),
        'ready':('submitted','applied','needs_user','superseded','failed'),
        'submitted':('applied','needs_user','failed')}
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (cid,)).fetchone()
        if expected is not None and (row is None or dict(row) != expected):
            return False
        if webjob is not None:
            fresh = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (webjob['paper_id'],)).fetchone()
            if fresh is None or dict(fresh)['selection'] != webjob['selection']:
                return False
        if row is None or (state != row['state'] and state not in transitions.get(row['state'], ())):
            return False
        return bool(db.execute('UPDATE card_correction_jobs SET state=?,error=?,result=coalesce(?,result),updated=? WHERE id=? AND state=?',
                   (state, error[:1000], json.dumps(result, ensure_ascii=False) if result is not None else None, now(), cid, row['state'])).rowcount)


def _job_ref(job):
    return {key:job.get(key) for key in ('id', 'paper_id', 'card_sha256', 'source_sha256',
                                        'priority', 'novelty', 'title', 'folder')}


def _collected_review(catalog, job, config=None):
    """Recheck all original inputs, the complete reply and its unique formal URL."""
    from review.api import card_review_queue as review
    folder = Path(job['folder']); packet = review.check_packet(folder)
    attempt = json.loads((folder/'attempt.json').read_text())
    if (attempt.get('state') != 'response_saved' or
            attempt.get('raw_sha256') != digest(folder/'response-raw.txt') or
            attempt.get('inputs') != packet['input_hashes'] or
            attempt.get('actual_prompt_sha256') != packet['actual_prompt_sha256']):
        raise ValueError('原核验尚未完整收取或材料指纹变化，不修正或重发')
    url = attempt.get('conversation_url', '')
    if not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url:
        raise ValueError('原核验没有正式会话回执')
    for other in (catalog.path.parent/'card_reviews').glob('*/*/attempt.json'):
        if other.resolve() == (folder/'attempt.json').resolve():
            continue
        if json.loads(other.read_text()).get('conversation_url') == url:
            raise ValueError('原核验会话归属不唯一')
    data, result = review.parse_review((folder/'response-raw.txt').read_text(), folder,
        optional_external_supplements=(config or {}).get('review_standard',{}).get('external_supplements_optional') is True)
    if ((config or {}).get('review_standard',{}).get('no_user_state') is True
            and result.get('action') == 'needs_user'):
        result = {**result, 'auto_action': 'rework',
                  'blocking_reason': '自动重做：' + (result.get('blocking_reason') or '证据不足'),
                  'action': 'rework'}
    evidence = {str(folder/name):digest(folder/name) for name in
                ('attempt.json', 'packet.json', 'prompt-actual.txt', 'response-raw.txt', 'card-original.json')}
    for name in ('feedback.json', 'assessment.json'):
        if (folder/name).exists():
            evidence[str(folder/name)] = digest(folder/name)
    return data, result, evidence


def _enqueue(catalog, job, kind, task, *, state='queued', error='', fifo_at=None, db=None):
    if db is None:
        install(catalog)
    cid = hashlib.sha256((job['id']+job['card_sha256']+kind+VERSION).encode()).hexdigest()[:24]
    folder = catalog.path.parent/'card_corrections'/job['paper_id']/cid
    task = {'schema_version':1, 'correction_id':cid, 'kind':kind, 'review':_job_ref(job), **task}
    from contextlib import nullcontext
    owned = db is None
    with (catalog.connect() if owned else nullcontext(db)) as db:
        if owned:
            db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM card_correction_jobs WHERE review_id=? AND kind=?', (job['id'], kind)).fetchone()
        if old:
            return dict(old)
        folder.mkdir(parents=True, exist_ok=True)
        atomic_json(folder/'task.json', task)
        at = now()
        try: fast=bool(db.execute('SELECT 1 FROM manual_seed_roots WHERE paper_id=?',(job['paper_id'],)).fetchone())
        except Exception: fast=False
        arrival = -1.0 if fast else (time.time() if fifo_at is None else fifo_at)
        db.execute('INSERT INTO card_correction_jobs '
                   '(id,review_id,paper_id,card_sha256,source_sha256,kind,title,state,folder,payload,task_sha256,error,created,fifo_at,queued_at,updated) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (cid, job['id'], job['paper_id'], job['card_sha256'], job['source_sha256'], kind, job['title'],
                    state, str(folder), json.dumps(task, ensure_ascii=False), digest(folder/'task.json'), error[:1000],
                    at, arrival, arrival, at))
        return dict(db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (cid,)).fetchone())


def partial_rework_allowed(data, result, folder):
    """A complete ambiguous report can still trigger a source-only bounded repair.

    No scientific edit is applied here. Original ambiguity/verdict stays intact;
    the replacement card must undergo an independent complete review.
    """
    from cards.api import web_card_evidence__canonical as canonical, web_card_evidence__literal_match as literal_match
    if (result.get('action') != 'needs_user' or result.get('full_source_checked') is not True or
            result.get('verdict') != 'cannot_evaluate' or result.get('missing_inputs')):
        return False
    major=[i for i in data.get('issues',[]) if i.get('severity') in ('major','critical')]
    if not major:
        return False
    folder=Path(folder)
    texts={r['source_page']:r['text'] for r in json.loads((folder/'source-context.json').read_text())['source_text']}
    card=json.loads((folder/'card-original.json').read_text())
    for issue in major:
        quote=issue.get('source_quote');page=issue.get('source_page');path=issue.get('path')
        if (type(page) is not int or not isinstance(quote,str) or len(canonical(quote).replace(' ',''))<15 or
                not literal_match(quote,texts.get(page,''),case_sensitive=True) or not isinstance(path,str)):
            return False
        value=card
        try:
            for part in path.split('.'):
                value=value[int(part)] if isinstance(value,list) and part.isdigit() else value[part]
        except (KeyError,IndexError,TypeError,ValueError):
            return False
    return True


def _rework_action(config, data, result, folder):
    if result.get('auto_action')=='rework':
        original={**result,'action':'needs_user'}
        return (partial_rework_allowed(data,original,folder) or
                bool(result.get('offline_blockers')) and result.get('full_source_checked') is True
                and not result.get('missing_inputs'))
    return (result['action']=='rework' or
            config.get('card_correction',{}).get('partial_ambiguous_rework') is True and
            partial_rework_allowed(data,result,folder))


def enqueue_review(catalog, job, config, data=None, result=None):
    """Produce a correction request; the verifier never applies the request here."""
    from review.api import card_review_queue as review
    paper, _, _ = review.current(catalog, job, config)
    actual_data, actual_result, evidence = _collected_review(catalog, job, config)
    if data is not None and data != actual_data or result is not None and result != actual_result:
        raise ValueError('修正建议与原核验回答不一致')
    action = actual_result['action']
    partial=_rework_action(config,actual_data,actual_result,job['folder']) and action=='needs_user'
    if (action not in ('correct', 'rework') and not partial or
            action=='rework' and not _rework_action(config,actual_data,actual_result,job['folder'])):
        raise ValueError('原核验未提出允许的修正或重做')
    kind = 'formatting' if action == 'correct' else 'source_rework'
    protected = review.protected(catalog, paper)
    return _enqueue(catalog, job, kind,
                    {'feedback':actual_data, 'assessment':actual_result, 'evidence':evidence,
                     'partial_ambiguous_rework':partial, 'preserve_original_ambiguity':partial},
                    state='needs_user' if protected else 'queued',
                    error='人工决定卡片仅保存建议，不覆盖或重做' if protected else '')


def enqueue_quotes(catalog, job, config, texts=None, fixes=None):
    """Only exact unique quote locations from the locally verified source text."""
    from review.api import card_review_queue as review
    paper, _, card = review.current(catalog, job, config)
    text_path = Path(job['folder'])/'source-text-verified.json'
    verified = json.loads(text_path.read_text())
    if not isinstance(verified, list) or any(not isinstance(t, str) for t in verified):
        raise ValueError('引文定位原文文字层未核对')
    if texts is not None and texts != verified:
        raise ValueError('引文定位文字层变化')
    _, actual_fixes = review.locate_quotes(card, verified)
    if not actual_fixes or fixes is not None and fixes != actual_fixes:
        raise ValueError('引文定位不唯一或建议变化')
    root = catalog.path.parent/'web_cards'/job['paper_id']
    packet = json.loads((root/'packet.json').read_text())
    if packet['source_original_sha256'] != job['source_sha256']:
        raise ValueError('引文定位原文版本变化')
    evidence = {str(text_path):digest(text_path), str(root/'packet.json'):digest(root/'packet.json')}
    for name in ('source.pdf', 'source-context.json'):
        if digest(root/name) != packet['input_hashes'][name]:
            raise ValueError('引文定位原文材料变化')
        evidence[str(root/name)] = digest(root/name)
    protected = review.protected(catalog, paper)
    return _enqueue(catalog, job, 'quote_location', {'fixes':actual_fixes, 'text_path':str(text_path), 'evidence':evidence},
                    state='needs_user' if protected else 'queued',
                    error='人工决定卡片仅保存引文定位建议' if protected else '')


def check_task(job):
    path = Path(job['folder'])/'task.json'
    if digest(path) != job['task_sha256']:
        raise ValueError('修正任务指纹变化')
    task = json.loads(path.read_text())
    if task != json.loads(job['payload']) or task['correction_id'] != job['id']:
        raise ValueError('修正任务与队列不一致')
    for path, expected in task.get('evidence', {}).items():
        if digest(path) != expected:
            raise ValueError('原核验或修正材料指纹变化')
    return task


def claim(catalog, config=None):
    install(catalog)
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        from core.api import workflow_priority__sort as sort_articles
        candidates=sort_articles(db,[dict(r) for r in db.execute("SELECT * FROM card_correction_jobs WHERE state='queued' ORDER BY fifo_at,id")],config or {})
        row=candidates[0] if candidates else None
        if row is None:
            return None
        db.execute("UPDATE card_correction_jobs SET state='preparing',updated=? WHERE id=?", (now(), row['id']))
        return dict(row)


def _publish_local(catalog, job, task, config):
    from review.api import card_review_queue as review
    ref = task['review']; paper, path, card = review.current(catalog, ref, config)
    with (path.parent/'web-publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_task(job); paper, path, card = review.current(catalog, ref, config)
        if review.protected(catalog, paper):
            raise ValueError('人工决定卡片仅保存建议，不覆盖')
        _require_running(config)
        if job['kind'] == 'quote_location':
            texts = json.loads(Path(task['text_path']).read_text())
            candidate, fixes = review.locate_quotes(card, texts)
            if fixes != task['fixes']:
                raise ValueError('引文定位建议变化，不修改')
            action = 'quote_location'; event_kind = 'card_quote_location_corrected'
        else:
            data, result, _ = _collected_review(catalog, ref, config)
            if data != task['feedback'] or result != task['assessment'] or result['action'] != 'correct':
                raise ValueError('排版修正核验报告变化')
            with catalog.connect() as db:
                old_count = db.execute("SELECT count(*) FROM events WHERE paper_id=? AND "
                    "(kind='card_correction_applied' AND json_extract(payload,'$.kind')='formatting' OR "
                    "kind='card_source_review' AND json_extract(payload,'$.state')='corrected')", (job['paper_id'],)).fetchone()[0]
            if old_count >= 1:
                raise ValueError('排版修正后仍需修正；保留反馈，不循环修改')
            candidate = review.formatting_candidate(card, data.get('corrections', []))
            action = 'correct'; event_kind = 'card_source_review'
            candidate['meta']['source_review'] = {'job_id':ref['id'], 'card_sha256':ref['card_sha256'],
                'report':str(Path(ref['folder'])/'feedback.json'), 'weighted_score':result['weighted_score'],
                'scores':result['scores'], 'issue_counts':result['issue_counts'],
                'full_source_checked':True, 'action':action}
        candidate['meta'].update(scientific_verified=False, scientific_validation_status='unreviewed',
                                 quality_status='needs_review', production_contract_complete=False)
        candidate['meta']['correction'] = {'job_id':job['id'], 'kind':job['kind'], 'before':job['card_sha256']}
        backup = path.parent/'history'/('correction-'+job['id']); backup.mkdir(parents=True, exist_ok=True)
        if not (backup/'card.json').exists():
            shutil.copy2(path, backup/'card.json')
        if digest(backup/'card.json') != job['card_sha256']:
            raise ValueError('修正备份指纹变化')
        atomic_json(Path(job['folder'])/'card-candidate.json', candidate)
        paper,path,_=review.current(catalog,ref,config)
        if digest(path) != job['card_sha256'] or review.protected(catalog, paper):
            raise ValueError('修正发布时版本或人工保护变化')
        _require_running(config)
        after = digest(Path(job['folder'])/'card-candidate.json')
        atomic_json(Path(job['folder'])/'publication.json', {'path':str(path), 'after':after, 'action':action, 'event_kind':event_kind,
            'correction_id':job['id'], 'before':job['card_sha256'], 'source_sha256':job['source_sha256'], 'task_sha256':job['task_sha256']})
        atomic_json(path, candidate)
        after = digest(path)
        result = {'action':action, 'kind':job['kind'], 'before':job['card_sha256'], 'after':after,
                  'scientific_verified':False, 'recheck_required':True}
        return _finish_local(catalog, job, task, result, event_kind)


def _finish_local(catalog, job, task, result, event_kind):
    from review.api import card_review_queue as review
    ref = task['review']
    review.replacement(catalog, ref, result['after'], 'queued')
    with catalog.connect() as db:
        previous=db.execute('SELECT result FROM card_review_jobs WHERE id=?',(ref['id'],)).fetchone()
    assessment=(json.loads(previous['result']) if previous else {}) or task.get('assessment', {})
    review.update(catalog, ref['id'], 'corrected', '独立修正已完成，等待新版核验',
                  {**assessment,'correction_result':result})
    catalog.event(job['paper_id'], event_kind, {'state':'corrected', 'correction_id':job['id'],
                  'review_id':ref['id'], 'before':job['card_sha256'], 'after':result['after']})
    catalog.event(job['paper_id'], 'card_correction_applied', result)
    update(catalog, job['id'], 'applied', result=result)
    return result


def _recover_local(catalog, job, config):
    journal = Path(job['folder'])/'publication.json'
    if job['kind'] == 'source_rework' or not journal.exists():
        return False
    task = check_task(job); record = json.loads(journal.read_text())
    if any(record.get(key) != job[value] for key,value in (('correction_id','id'),('before','card_sha256'),('source_sha256','source_sha256'),('task_sha256','task_sha256'))):
        raise ValueError('中断发布日志与原修正任务指纹不一致')
    paper = catalog.get(job['paper_id']); path = Path(paper.get('card_path') or '')
    from review.api import card_review_queue as review
    with (path.parent/'web-publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _require_running(config)
        with catalog.connect() as db:
            fresh = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (job['id'],)).fetchone()
        if fresh is None or dict(fresh) != job:
            return False
        paper = catalog.get(job['paper_id'])
        if (path.resolve() != Path(record['path']).resolve() or
                Path(paper.get('card_path') or '').resolve() != path.resolve() or
                paper.get('asset_hash') != job['source_sha256'] or
                digest(paper['asset_path']) != job['source_sha256'] or review.protected(catalog, paper)):
            raise ValueError('中断发布的原文、路径或人工保护变化')
        if digest(path) == job['card_sha256']:
            return False  # Candidate was never published; retain it, do not publish implicitly.
        candidate = Path(job['folder'])/'card-candidate.json'
        if digest(path) != record['after'] or digest(candidate) != record['after']:
            raise ValueError('中断发布的新版指纹不一致')
        meta = json.loads(candidate.read_text()).get('meta', {})
        if (meta.get('correction') != {'job_id':job['id'], 'kind':job['kind'], 'before':job['card_sha256']} or
                meta.get('scientific_verified') is not False or meta.get('production_contract_complete') is not False):
            raise ValueError('中断发布候选缺少原修正归属或独立核验标记')
        result = {'action':record['action'], 'kind':job['kind'], 'before':job['card_sha256'],
                  'after':record['after'], 'scientific_verified':False, 'recheck_required':True}
        # Recovery is explicit, bound to the already published bytes, never a resend.
        with catalog.connect() as db:
            db.execute("UPDATE card_correction_jobs SET state='preparing' WHERE id=? AND state IN ('preparing','needs_user')", (job['id'],))
        _finish_local(catalog, job, task, result, record['event_kind'])
        return True


def process(catalog, job, config):
    """Apply a local correction or prepare one bounded, source-only rework."""
    from review.api import card_review_queue as review
    task = check_task(job)
    ref=task['review'];paper,path,_=review.current(catalog,ref,config)
    if review.protected(catalog,paper):
        raise ValueError('人工决定卡片仅保存建议，不修正或重做')
    if job['kind'] != 'source_rework':
        return _publish_local(catalog, job, task, config)
    data, result, _ = _collected_review(catalog, ref, config)
    if data != task['feedback'] or result != task['assessment'] or not _rework_action(config,data,result,ref['folder']):
        raise ValueError('重大问题原核验报告变化')
    if review.protected(catalog, paper):
        raise ValueError('人工决定卡片仅保存建议，不重做')
    _require_running(config)
    # The existing routine enforces two reworks, original receipt archival,
    # card/source fingerprints and source-only material generation.
    with (path.parent/'web-publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_task(job); paper, path, _ = review.current(catalog, ref, config)
        if review.protected(catalog, paper):
            raise ValueError('人工保护变化，不退回重做')
        _require_running(config)
        review.queue_rework(catalog, ref, config, paper, path,
                            {**result, 'correction_id':job['id'], 'correction_fifo_at':job['fifo_at']})
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,selection FROM web_card_jobs WHERE paper_id=?', (job['paper_id'],)).fetchone()
            record = json.loads(row['selection']).get('rework') if row else None
            if (row is None or row['state'] != 'queued' or not record or record.get('review_id') != ref['id']):
                update_state = 'needs_user'; error = '原重做未入队，保留上限或保护提示'
            else:
                selection = json.loads(row['selection'])
                selection['rework'].update(correction_id=job['id'], correction_fifo_at=job['fifo_at'])
                db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                           (json.dumps(selection, ensure_ascii=False), job['paper_id']))
                update_state = 'ready'; error = '等待原文材料及共享网页；原卡片继续保留'
            db.execute('UPDATE card_correction_jobs SET state=?,error=?,updated=? WHERE id=?',
                       (update_state, error, now(), job['id']))
    return {'state':update_state, 'correction_id':job['id']}


def web_job_kind(job):
    selection = json.loads(job.get('selection') or '{}')
    rework = selection.get('rework', {})
    return 'correction' if rework.get('correction_id') or rework.get('kind') == 'source_review' else 'cards'


def _bound_job(catalog, job):
    with catalog.connect() as db:
        return _bound_rows(db, job)


def _bound_rows(db, job):
    record = json.loads(job.get('selection') or '{}').get('rework', {})
    if not record.get('correction_id'):
        raise ValueError('修正任务缺少实体绑定')
    row = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (record.get('correction_id'),)).fetchone()
    fresh = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (job.get('paper_id'),)).fetchone()
    if row is None or fresh is None:
        return None
    correction = dict(row)
    if (dict(fresh).get('selection') != job.get('selection') or
            dict(fresh).get('source_sha256') != job.get('source_sha256') or
            correction['paper_id'] != job.get('paper_id') or
            correction['source_sha256'] != job.get('source_sha256') or
            correction['review_id'] != record.get('review_id') or
            correction['card_sha256'] != record.get('old_sha256')):
        return None
    return correction


def allows_web_job(config, job, *, recovery=False):
    from core.api import seed_focus__allowed as seed_allowed
    if not seed_allowed(config,job.get('paper_id')):return False
    if web_job_kind(job) == 'correction':
        # A failed legacy adoption must never acquire a card slot or bypass the
        # correction controls. Its original conversation remains collect-only.
        record = json.loads(job.get('selection') or '{}').get('rework', {})
        if not isinstance(record.get('correction_id'), str) or not record['correction_id']:
            return False
        if not enabled(config) or not config.get('catalog_path'):
            return False
        try:
            with sqlite3.connect(Path(config['catalog_path']).as_uri()+'?mode=ro', uri=True, timeout=1) as db:
                db.row_factory = sqlite3.Row
                bound = _bound_rows(db, job)
            allowed_states = ('needs_user',) if recovery else ('ready','submitted')
            return bool(bound and bound['kind'] == 'source_rework' and bound['state'] in allowed_states)
        except (sqlite3.Error, ValueError, TypeError):
            return False
    if recovery:
        return False
    from cards.api import web_card_service__enabled as cards_enabled
    return cards_enabled(config)


def mark_web_state(catalog, job, state, **details):
    """Mirror a transport result without changing the original transport ledger."""
    record = json.loads(job.get('selection') or '{}').get('rework', {})
    cid = record.get('correction_id')
    bound = _bound_job(catalog, job) if cid else None
    if bound is None:
        return False
    mapped = {'submitted':'submitted', 'collecting':'submitted', 'completed':'applied',
              'protected':'needs_user', 'failed':'needs_user', 'needs_inspection':'needs_user'}.get(state)
    # The sender may report a completed status before local publication. Only
    # sync() can prove a new card plus an intact complete response and finish it.
    if state == 'completed':
        return False
    if mapped:
        return update(catalog, cid, mapped, details.get('error', ''),
               {'transport_state':state, 'review_id':record.get('review_id'), 'recheck_required':state == 'completed', **details}, expected=bound, webjob=job)


def _published_rework(catalog, job, webjob, config):
    """Require source, actual prompt, saved response and published card binding."""
    from cards.api import web_card_retry__finished_response as finished_response
    root = catalog.path.parent/'web_cards'/job['paper_id']
    paper = catalog.get(job['paper_id'])
    path = Path(paper.get('card_path') or '')
    expected = Path(config['studio_library_root'])/job['paper_id']/'card.json'
    versioned=(path.name=='card.json' and path.parent.parent.name=='publications' and
               path.parent.parent.parent.resolve()==expected.parent.resolve())
    if (path.resolve() != expected.resolve() and not versioned) or not path.is_file() or digest(path) == job['card_sha256']:
        raise ValueError('重做完成状态缺少绑定的新版正式卡片')
    if paper.get('asset_hash') != job['source_sha256'] or digest(paper['asset_path']) != job['source_sha256']:
        raise ValueError('重做完成时原文指纹变化')
    packet = json.loads((root/'packet.json').read_text())
    if packet.get('source_original_sha256') != job['source_sha256']:
        raise ValueError('重做材料原文版本不一致')
    records = []
    for attempt_path in root.glob('*/attempt.json'):
        attempt = json.loads(attempt_path.read_text())
        if attempt.get('state') == 'response_saved':
            finished_response(attempt_path, attempt, packet)
            records.append(attempt)
        else:
            from cards.api import web_card_retry__known_unsent as known_unsent
            if not known_unsent(attempt):
                raise ValueError('重做仍有未完整收取的原请求')
    if len(records) != 1:
        raise ValueError('重做完整回答回执不唯一或缺失')
    attempt = records[0]; card = json.loads(path.read_text()); meta = card.get('meta', {})
    if versioned:
        provenance=json.loads(path.with_name('web-provenance.json').read_text())
        if (meta.get('publication_id')!=path.parent.name or provenance.get('publication_id')!=path.parent.name or
                provenance.get('card_sha256')!=digest(path) or
                Path(provenance.get('packet','')).resolve()!=(root/'packet.json').resolve() or
                meta.get('input_hashes')!=packet['input_hashes'] or
                provenance.get('attempt',{}).get('raw_sha256')!=attempt['raw_sha256']):
            raise ValueError('新版发布目录、材料或回执指纹不一致')
    record = meta.get('selection', {}).get('rework', {})
    legacy = json.loads(job['payload']).get('legacy_adoption') is True
    allowed_ids = (None, job['id']) if legacy else (job['id'],)
    if (meta.get('producer') != 'web_card_service' or meta.get('provider') != 'chatgpt' or
            meta.get('source_original_sha256') != job['source_sha256'] or
            meta.get('source_sha256') != packet['input_hashes']['source.pdf'] or
            digest(path.with_name('source.pdf')) != meta['source_sha256'] or
            meta.get('raw_sha256') != attempt['raw_sha256'] or
            meta.get('actual_prompt_sha256') != attempt['actual_prompt_sha256'] or
            meta.get('conversation_url') != attempt['conversation_url'] or
            record.get('correction_id') not in allowed_ids or record.get('review_id') != job['review_id'] or
            record.get('old_sha256') != job['card_sha256']):
        raise ValueError('重做新卡片与原文、完整回答或修正任务不一致')
    return digest(path)


def check_retry_prompt(path,root,receipt):
    from cards.api import web_card_retry__known_unsent as known_unsent
    from browser.api import web_upload_bundle__ZIP_INSTRUCTION as ZIP_INSTRUCTION
    prompt=path.parent/'prompt-actual.txt'
    prompt_not_created=(known_unsent(receipt) and receipt.get('send_click_started') is False
        and not receipt.get('actual_prompt_sha256') and not prompt.exists())
    if not prompt_not_created and (digest(prompt)!=receipt.get('actual_prompt_sha256') or
            prompt.read_text() not in ((root/'prompt.txt').read_text(),(root/'prompt.txt').read_text()+ZIP_INSTRUCTION)):
        raise ValueError('归档实际提示变化')


def resume_scheduled_retry(catalog,job,webjob,config):
    """Mirror an already authorized, archived retry; never create another retry."""
    from review.api import card_review_queue as review
    from cards.api import web_card_retry__eligible as eligible, web_card_retry__frozen_inputs as frozen_inputs, web_card_retry__known_unsent as known_unsent
    from cards.api import web_card_rework__submission_history as submission_history
    if not enabled(config) or job['kind']!='source_rework' or job['state'] not in ('submitted','needs_user') or webjob['state']!='queued':return False
    root=catalog.path.parent/'web_cards'/job['paper_id'];ledger_path=root/'retry.json'
    ledger=json.loads(ledger_path.read_text());ledger_sha=digest(ledger_path)
    if ledger.get('state')!='scheduled' or type(ledger.get('external_retries')) is not int or not 1<=ledger['external_retries']<=2:return False
    history=Path(ledger['history']).resolve()
    if not history.is_relative_to((root/'history').resolve()):raise ValueError('重试归档越界')
    if list(root.glob('*/attempt.json')):raise ValueError('仍有当前请求回执，不能恢复重试派发')
    if not submission_history(catalog,webjob,root).allowed:raise ValueError('存在未知历史请求，不能恢复重试派发')
    paper=eligible(catalog,webjob,config);task=check_task(job)
    review.current(catalog,task['review'],config)
    packet=json.loads((root/'packet.json').read_text())
    if ledger.get('input_hashes')!=packet['input_hashes'] or ledger.get('retry_at')!=webjob['retry_at']:raise ValueError('重试计划与冻结材料不一致')
    frozen_inputs(root,packet,paper)
    paths=list(history.glob('*/attempt.json'))
    if not paths:raise ValueError('重试缺少原回执归档')
    receipts={}
    from browser.api import web_upload_bundle__ZIP_INSTRUCTION as ZIP_INSTRUCTION
    for path in paths:
        receipt=json.loads(path.read_text());receipts[path]=digest(path)
        if receipt.get('inputs')!=packet['input_hashes']:raise ValueError('归档重试材料指纹变化')
        check_retry_prompt(path,root,receipt)
        if receipt.get('state')=='response_saved':
            raw=path.parent/'response-raw.txt';url=receipt.get('conversation_url','')
            if not raw.read_text().strip() or digest(raw)!=receipt.get('raw_sha256') or not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url:raise ValueError('归档完整回答证据不足')
        elif not known_unsent(receipt):raise ValueError('归档请求尚未明确结束')
        bundle=receipt.get('upload_bundle')
        if bundle and digest(bundle['zip_path'])!=bundle.get('zip_sha256'):raise ValueError('归档ZIP变化')
    selection=json.loads(webjob['selection']).get('rework',{})
    if selection.get('correction_id')!=job['id'] or selection.get('review_id')!=job['review_id'] or selection.get('old_sha256')!=job['card_sha256']:raise ValueError('重试任务归属变化')
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('SELECT * FROM card_correction_jobs WHERE id=?',(job['id'],)).fetchone()
        current=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
        if fresh is None or current is None or dict(fresh)!=job or dict(current)!=webjob or digest(ledger_path)!=ledger_sha or not enabled(config):raise ValueError('重试同步期间状态变化')
        if list(root.glob('*/attempt.json')) or any(digest(p)!=sha for p,sha in receipts.items()):raise ValueError('重试同步期间回执变化')
        if not submission_history(catalog,webjob,root).allowed:raise ValueError('历史请求在重试同步期间变化')
        eligible(catalog,webjob,config);check_task(job)
        db.execute("UPDATE card_correction_jobs SET state='ready',error='已核对原归档重试计划，等待共享网页',updated=? WHERE id=?",(now(),job['id']))
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'correction_scheduled_retry_resumed',?,?)",(job['paper_id'],json.dumps({'correction_id':job['id'],'history':str(history),'retry_ledger_sha256':ledger_sha,'external_retries':ledger['external_retries']}),now()))
    return True


def _resume_prepared_rework(catalog, job, webjob, config):
    """Reconcile an existing unsent intent after the old producer race.

    No new rework, retry or model request is created. The original task/report,
    unchanged current source/card and ended archived receipts remain mandatory.
    """
    interrupted = '唯一生产者核对执行中断；保留候选与原回执，不重新发布或发送'
    if (job['kind'] != 'source_rework' or job['state'] not in ('needs_user','failed')
            or job['error'].removeprefix('自动终止：') != interrupted
            or webjob['state'] != 'queued' or not enabled(config)):
        return False
    from review.api import card_review_queue as review
    from cards.api import web_card_rework__submission_history as submission_history
    task = check_task(job); ref = task['review']
    paper, path, _ = review.current(catalog, ref, config)
    root = catalog.path.parent/'web_cards'/job['paper_id']
    with (path.parent/'web-publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _require_running(config)
        selection = json.loads(webjob['selection'])['rework']
        backup = Path(selection['backup'])/'card.json'
        paths = [Path(job['folder'])/'task.json',Path(paper['asset_path']),path,backup,
                 Path(selection['review_report']),*(Path(p) for p in task.get('evidence',{}))]
        versions = {str(p.resolve()):(p.stat().st_dev,p.stat().st_ino,p.stat().st_size,
                    p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths}
        task = check_task(job); paper, path, _ = review.current(catalog, ref, config)
        if review.protected(catalog,paper) or _bound_job(catalog,webjob) != job:
            raise ValueError('已准备重做的原归属或人工保护变化')
        if (digest(backup) != job['card_sha256'] or
                digest(selection['review_report']) != selection['review_report_sha256']):
            raise ValueError('已准备重做的原卡或报告变化')
        data, result, _ = _collected_review(catalog, ref, config)
        if (data != task['feedback'] or result != task['assessment']
                or not _rework_action(config,data,result,ref['folder'])):
            raise ValueError('原报告不满足既有重做证据条件')
        # No current request, including known-unsent drafts, may be adopted by
        # this local bookkeeping repair. Historical unknown requests still block.
        if list(root.glob('*/attempt.json')) or not submission_history(catalog,webjob,root).allowed:
            raise ValueError('已准备重做仍有原请求或未知历史，不恢复发送准入')
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            fresh = db.execute('SELECT * FROM card_correction_jobs WHERE id=?',(job['id'],)).fetchone()
            current = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
            if fresh is None or current is None or dict(fresh)!=job or dict(current)!=webjob:
                return False
            _require_running(config)
            if list(root.glob('*/attempt.json')) or any(
                    (Path(p).stat().st_dev,Path(p).stat().st_ino,Path(p).stat().st_size,
                     Path(p).stat().st_mtime_ns,Path(p).stat().st_ctime_ns)!=v for p,v in versions.items()):
                raise ValueError('已准备重做在恢复期间发生证据变化')
            db.execute("UPDATE card_correction_jobs SET state='ready',error='已核对原准备意图，等待材料及共享网页',updated=? WHERE id=?",(now(),job['id']))
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'correction_prepared_intent_reconciled',?,?)",
                (job['paper_id'],json.dumps({'correction_id':job['id'],'previous_state':job['state'],
                 'previous_error':job['error'],'task_sha256':job['task_sha256'],
                 'selection_sha256':hashlib.sha256(webjob['selection'].encode()).hexdigest(),
                 'new_rework_or_retry_created':False},ensure_ascii=False),now()))
    return True


def sync(catalog, config, entries=None):
    """Observe existing source-rework progress; completion requires a saved ledger."""
    from review.api import card_review_queue as review
    install(catalog)
    with catalog.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='web_card_jobs'").fetchone():
            return 0
        jobs = [dict(r) for r in db.execute("SELECT * FROM web_card_jobs WHERE "
            "json_extract(selection,'$.rework.correction_id') IS NOT NULL OR json_extract(selection,'$.rework.kind')='source_review'")]
    changed = 0;retry_retained=[]
    for webjob in jobs:
        cid = json.loads(webjob['selection'])['rework'].get('correction_id')
        with catalog.connect() as db:
            row = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (cid,)).fetchone() if cid else None
        job = dict(row) if row is not None else None
        root = catalog.path.parent/'web_cards'/webjob['paper_id']
        for attempt_path in root.glob('*/attempt.json'):
            attempt = json.loads(attempt_path.read_text())
            tid = attempt.get('target_id')
            if (entries is not None and tid in entries and
                    (entries[tid].get('active_paper_id') or entries[tid].get('paper_id')) == webjob['paper_id'] and
                    entries[tid].get('conversation_url') == attempt.get('conversation_url') and
                    attempt.get('conversation_url','').startswith('https://chatgpt.com/c/') and
                    'local-chatgpt' not in attempt['conversation_url'] and
                    not entries[tid].get('review_id') and entries[tid].get('correction_id') in (None, cid)):
                entries[tid]['kind']='correction'
                if cid:entries[tid]['correction_id']=cid
            if job is None:
                continue
            # An uncertain receipt is always visible even when the transport was
            # marked terminal by a previous service instance.
            if attempt.get('state') in ('submission_started', 'submitted', 'needs_inspection'):
                if job['state'] == 'ready' and webjob['state'] in ('submitted', 'collecting'):
                    changed += bool(mark_web_state(catalog, webjob, 'submitted'))
        if job is None:
            continue
        try:
            if _resume_prepared_rework(catalog,job,webjob,config):
                changed += 1
                continue
        except (OSError,ValueError,KeyError,TypeError) as exc:
            retry_retained.append({'correction_id':job['id'],'reason':str(exc)[:400]})
            continue
        if webjob['state']=='queued' and job['state'] in ('submitted','needs_user'):
            try:
                if resume_scheduled_retry(catalog,job,webjob,config):changed+=1
            except (OSError,ValueError,KeyError,TypeError) as exc:
                retry_retained.append({'correction_id':job['id'],'reason':str(exc)[:400]})
            continue
        if webjob['state'] == 'completed' and job['state'] in ('ready','submitted','needs_user'):
            try:
                task = check_task(job)
                after = _published_rework(catalog, job, webjob, config)
            except Exception as exc:
                mark_web_state(catalog, webjob, 'needs_inspection', error=str(exc)); changed += 1; continue
            review.replacement(catalog, task['review'], after, 'queued')
            if _bound_job(catalog, webjob):
                if job['state'] == 'needs_user':
                    # Saved-publication recovery has independently verified the full chain.
                    with catalog.connect() as db:
                        db.execute("UPDATE card_correction_jobs SET state='submitted' WHERE id=? AND state='needs_user' AND updated=?", (job['id'],job['updated']))
                    job = next(row for row in rows(catalog) if row['id'] == job['id'])
                changed += update(catalog, job['id'], 'applied', result={'before':job['card_sha256'], 'after':after, 'recheck_required':True}, expected=job, webjob=webjob)
        elif webjob['state'] in ('failed', 'needs_inspection', 'protected') and job['state'] not in TERMINAL:
            mark_web_state(catalog, webjob, webjob['state'], error=webjob['error']); changed += 1
    atomic_json(catalog.path.parent/'correction-retry-retained.json',{'checked_at':time.time(),'items':retry_retained})
    if retry_retained:
        with (catalog.path.parent/'correction-diagnostics.jsonl').open('a') as log:
            log.write(json.dumps({'at':now(), 'kind':'retry_retained', 'items':retry_retained}, ensure_ascii=False)+'\n')
    return changed


def adopt_legacy(catalog, config):
    """Label already-authorized review reworks; never reset or resend them.

    Old terminal/unknown requests remain terminal/unknown. Only an existing due
    unsent queue entry can become a ready correction entry. Unknown legacy
    arrival times are explicitly labelled as migration registration.
    """
    install(catalog)
    with catalog.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='web_card_jobs'").fetchone():
            return {'adopted':0, 'preserved':0, 'errors':[]}
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='card_review_jobs'").fetchone():
            return {'adopted':0, 'preserved':0, 'errors':[]}
        old_jobs = [dict(r) for r in db.execute("SELECT * FROM web_card_jobs WHERE "
            "json_extract(selection,'$.rework.kind')='source_review' AND "
            "json_extract(selection,'$.rework.correction_id') IS NULL")]
    report = {'adopted':0, 'preserved':0, 'errors':[]}
    for old in old_jobs:
        try:
            selection = json.loads(old['selection']); record = selection['rework']
            with catalog.connect() as db:
                row = db.execute('SELECT * FROM card_review_jobs WHERE id=?', (record['review_id'],)).fetchone()
            if row is None:
                raise ValueError('旧重做没有原核验任务，不更改旧请求')
            review_job = dict(row)
            if review_job['card_sha256'] != record['old_sha256'] or review_job['source_sha256'] != old['source_sha256']:
                raise ValueError('旧重做的核验/原卡片/原文绑定不一致')
            if digest(Path(record['backup'])/'card.json') != record['old_sha256']:
                raise ValueError('旧重做原卡片备份变化')
            if digest(record['review_report']) != record['review_report_sha256']:
                raise ValueError('旧重做原核验报告变化')
            data, result, evidence = _collected_review(catalog, review_job, config)
            if result['action'] != 'rework':
                raise ValueError('旧报告未允许重大问题重做')
            ledgers = [json.loads(p.read_text()) for p in
                       (catalog.path.parent/'web_cards'/old['paper_id']).glob('*/attempt.json')]
            from cards.api import web_card_retry__known_unsent as known_unsent
            if old['state'] == 'queued' and all(known_unsent(a) for a in ledgers):
                state = 'ready'
            elif old['state'] in ('submitted', 'collecting') and ledgers and all(a.get('state') in ('submitted', 'submission_started', 'response_saved') for a in ledgers):
                state = 'submitted'
            else:
                # Completed is checked by sync(), not assumed from a queue label.
                state = 'submitted' if old['state'] == 'completed' else 'needs_user'
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                fresh = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (old['paper_id'],)).fetchone()
                if fresh is None or dict(fresh) != old:
                    raise ValueError('登记期间旧重做状态变化，不更改')
                correction = _enqueue(catalog, review_job, 'source_rework',
                    {'feedback':data, 'assessment':result, 'evidence':evidence, 'legacy_adoption':True,
                     'fifo_basis':'migration_registration'},
                    state=state, error='既有重做仅登记独立修正归属，不重排或重发', db=db)
                selection['rework'].update(correction_id=correction['id'], correction_fifo_at=correction['fifo_at'])
                db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                           (json.dumps(selection, ensure_ascii=False), old['paper_id']))
            report['adopted'] += 1
            report['preserved'] += state == 'needs_user'
        except Exception as exc:
            report['errors'].append({'paper_id':old['paper_id'], 'error':str(exc)[:600]})
    return report


def ready_requests(catalog):
    """Only actual prepared, due source reworks join the browser FIFO."""
    install(catalog)
    with catalog.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='web_page_queue'").fetchone():
            return []
        return [dict(r) for r in db.execute("SELECT c.id,c.paper_id,c.fifo_at,q.target_id,q.assigned "
            "FROM card_correction_jobs c JOIN web_card_jobs j USING(paper_id) JOIN web_page_queue q USING(paper_id) "
            "WHERE c.kind='source_rework' AND c.state='ready' AND j.state='queued' AND q.state='ready' AND j.retry_at<=? "
            "AND json_extract(j.selection,'$.rework.correction_id')=c.id ORDER BY c.fifo_at,c.id", (time.time(),))]


def status(config):
    path = Path(config['catalog_path']); counts = {}; jobs = []; finished = None;local_pending=page_pending=0
    if path.is_file():
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1) as db:
            db.row_factory = sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='card_correction_jobs'").fetchone():
                counts = dict(db.execute('SELECT state,count(*) FROM card_correction_jobs GROUP BY state'))
                jobs = [dict(r) for r in db.execute('SELECT id,review_id,paper_id,title,kind,state,error,created,fifo_at,updated '
                    'FROM card_correction_jobs ORDER BY fifo_at,id')]
                local_pending=sum(job['kind']!='source_rework' and job['state']=='queued' for job in jobs)
                page_pending=sum(job['kind']=='source_rework' and job['state'] in ('queued','ready') for job in jobs)
                from core.api import workflow_priority__sort as sort_articles
                jobs = sort_articles(db, jobs, config)[:100]
                row = db.execute("SELECT updated FROM card_correction_jobs WHERE state IN ('applied','needs_user','failed') ORDER BY updated DESC LIMIT 1").fetchone()
                finished = row['updated'] if row else None
    from core.api import concurrency_control__settings as settings
    parallel = settings(config).get('correction', config.get('card_correction', {}).get('parallel_jobs', 4))
    from core.api import workflow_recovery__decorate as decorate
    return decorate(config,'correction',{'enabled':enabled(config), 'parallel_jobs':parallel, 'counts':counts, 'jobs':jobs, 'last_finished_at':finished,
            'local_pending':local_pending,'page_pending':page_pending})


class CorrectionProducer:
    """Local work only. The existing browser owner sends and collects reworks."""
    def __init__(self, config):
        self.config = config; self.catalog = Catalog(config['catalog_path']); install(self.catalog)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name='card-correction-producer', daemon=True)
        self.workers = max(1, min(8, int(config.get('card_correction', {}).get('prepare_workers', 4))))
        self.executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix='card-correction-prepare')
        self.futures = set()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set(); self.thread.join(); self.executor.shutdown(wait=True)

    def work(self,job):
        try:
            process(self.catalog,job,self.config)
        except CorrectionPaused as exc:
            update(self.catalog,job['id'],'queued','用户暂停，未发布或退回重做；'+str(exc))
        except Exception as exc:
            update(self.catalog,job['id'],'needs_user',str(exc))
            try:
                with (self.catalog.path.parent/'correction-diagnostics.jsonl').open('a') as log:
                    log.write(json.dumps({'at':now(), 'kind':'task_error', 'correction_id':job['id'], 'error_type':type(exc).__name__, 'traceback':traceback.format_exc()})+'\n')
            except OSError:
                pass

    def run(self):
        with (self.catalog.path.parent/'correction-producer.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            self._run_owned()

    def _run_owned(self):
        routing_checked = None
        running_jobs = {}
        while not self.stop_event.is_set():
            try:
                if enabled(self.config):
                    if routing_checked is None or time.monotonic() - routing_checked >= 15*60:
                        try:
                            from .recover_review_corrections import run_once
                            routing = run_once(self.catalog, self.config)
                            atomic_json(self.catalog.path.parent/'correction-routing-status.json', {'updated':now(), **routing})
                        finally:
                            routing_checked = time.monotonic()
                    # Only this owner submits these futures. A preparing row
                    # remains live until its own worker ends; persisted rows
                    # without a live future still use the original recovery.
                    running_jobs = {future:jid for future,jid in running_jobs.items() if not future.done()}
                    active_ids = set(running_jobs.values())
                    for interrupted in rows(self.catalog):
                        from core.api import seed_focus__allowed as seed_allowed
                        if not seed_allowed(self.config,interrupted.get('paper_id')):continue
                        if interrupted['id'] in active_ids:continue
                        if interrupted['state'] in ('preparing','needs_user'):
                            try:
                                recovered = _recover_local(self.catalog, interrupted, self.config)
                            except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                                if interrupted['state'] == 'preparing':
                                    update(self.catalog, interrupted['id'], 'needs_user', str(exc))
                                continue
                            if not recovered and interrupted['state'] == 'preparing':
                                update(self.catalog, interrupted['id'], 'needs_user', '唯一生产者核对执行中断；保留候选与原回执，不重新发布或发送')
                    self.futures = {future for future in self.futures if not future.done()}
                    while len(self.futures) < self.workers and not self.stop_event.is_set():
                        job = claim(self.catalog, self.config)
                        if not job:break
                        future = self.executor.submit(self.work, job)
                        self.futures.add(future)
                        running_jobs[future] = job['id']
                    self.stop_event.wait(3)
                    continue
            except Exception as exc:
                try:
                    with (self.catalog.path.parent/'correction-diagnostics.jsonl').open('a') as log:
                        log.write(json.dumps({'at':now(), 'kind':'producer_error', 'error_type':type(exc).__name__, 'error':str(exc)[:700], 'traceback':traceback.format_exc()})+'\n')
                except OSError:
                    pass
            self.stop_event.wait(1)
