"""Recover exact page leases from ended receipts, independently of retry limits.

Only an explicit unsent dead-owner receipt can return preparation to its
original FIFO queue. No webpage is changed; unknown receipts remain pinned.
"""
import hashlib
import json
import os
import math
import sqlite3
import time
from core.api import paths__WorkspacePath as Path

from .attempt_history import read_attempt, scan_checkpoint


def release_untouched(catalog, lane, job_id, target_id):
    """Call only from the owner's exception branch before any page operation."""
    from .shared_workflow_queue import release_claim
    return release_claim(catalog, lane, job_id, target_id)


def abandoned_unsent(record, root, *, at):
    """Require an explicit old owner, its death, and an unsent receipt."""
    from core.api import control__read_record as read_record
    owner=read_record(Path(root)/'web-card-service.json')
    pid=record.get('owner_pid');token=record.get('owner_token');created=record.get('created')
    url=record.get('conversation_url') or ''
    if (record.get('state') not in ('ready','not_sent') or record.get('send_click_started') is not False
            or not isinstance(url,str) or '/c/' in url or type(pid) is not int or pid<=0
            or owner.get('pid') != os.getpid() or pid==owner.get('pid')
            or not isinstance(token,str) or not token or not owner.get('token') or token==owner['token']
            or type(created) not in (int,float) or not math.isfinite(created) or at-created<120):
        return False
    try:os.kill(pid,0)
    except ProcessLookupError:return True
    except PermissionError:return False
    return False


def _recover_abandoned(db,row,root,health,*,at):
    if health.get('health') != 'healthy_blank' or not health.get('evidence',{}).get('completed_history_paths'):
        return False
    if row['lane']=='review':
        source=db.execute('SELECT * FROM card_review_jobs WHERE id=? AND paper_id=?',(row['job_id'],row['paper_id'])).fetchone()
        if not source or source['state'] not in ('preparing','submitting','needs_user'):return False
        if source['state']=='needs_user' and json.loads(source['result'])!={} and json.loads(source['result']).get('material_recheck_pending') is not True:return False
        folder=Path(source['folder'])
    else:
        source=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(row['paper_id'],)).fetchone()
        if not source or source['state'] != 'preparing':return False
        folder=root/'web_cards'/row['paper_id']
        material=db.execute('SELECT * FROM web_page_queue WHERE paper_id=?',(row['paper_id'],)).fetchone()
        if not material or material['state'] != 'ready' or material['target_id']!=row['target_id']:return False
    if not folder.resolve().is_relative_to(root.resolve()):return False
    paths=sorted(folder.rglob('attempt.json'));records=[read_attempt(p) for p in paths]
    candidates=[r for r in records if r.get('target_id')==row['target_id'] and abandoned_unsent(r,root,at=at)]
    if not candidates:return False
    record=max(candidates,key=lambda r:r.get('created',0))
    target_records=[r for r in records if r.get('target_id')==row['target_id']]
    if record!=max(target_records,key=lambda r:r.get('created',0)):return False
    if row['lane']=='review' and record.get('review_id')!=row['job_id']:return False
    complete=set(health['evidence']['completed_history_paths'])
    if any(r['_ledger_path'] not in complete for r in records if r.get('target_id')==row['target_id']):return False
    # Unknown records cannot be hidden behind a newer explicitly unsent lease.
    if any(r.get('state') not in ('response_saved','not_sent','ready','deferred') or
           r.get('state')!='response_saved' and r.get('send_click_started') is not False
           for r in records if r.get('target_id')==row['target_id']):return False
    if sorted(folder.rglob('attempt.json'))!=paths or any(read_attempt(r['_ledger_path'])['_ledger_sha256']!=r['_ledger_sha256'] for r in records):return False
    if row['lane']=='correction':
        correction=db.execute('SELECT state,paper_id FROM card_correction_jobs WHERE id=?',(row['job_id'],)).fetchone()
        if not correction or correction['paper_id']!=row['paper_id'] or correction['state'] not in ('ready','submitting'):return False
    from core.api import services__atomic_json as atomic_json
    from .shared_page_repair import atomic_bytes
    from core.api import catalog__now as now
    path=Path(record['_ledger_path']);archive=folder/'history'/('abandoned-unsent-'+record['_ledger_sha256'])
    archive.mkdir(parents=True,exist_ok=True)
    before=archive/'attempt-before.json'
    if not before.exists():atomic_bytes(before,path.read_bytes())
    if hashlib.sha256(before.read_bytes()).hexdigest()!=record['_ledger_sha256']:
        raise ValueError('未发送旧所有者归档指纹不一致')
    ended={k:v for k,v in record.items() if not k.startswith('_')}
    ended.update(state='not_sent',archive_reason='dead_owner_explicit_unsent',finished=at)
    atomic_json(archive/'attempt.json',ended)
    if not path.is_relative_to(folder/'history'):path.unlink()
    if row['lane']=='review':
        db.execute("UPDATE card_review_jobs SET state=?,error='',updated=? WHERE id=?",('ready' if source['state']=='submitting' else 'queued',now(),row['job_id']))
    else:
        db.execute("UPDATE web_card_jobs SET state='queued',error='',updated=? WHERE paper_id=?",(now(),row['paper_id']))
    if row['lane']=='correction':db.execute("UPDATE card_correction_jobs SET state='ready',updated=? WHERE id=?",(now(),row['job_id']))
    db.execute("UPDATE shared_page_backlog SET state='queued' WHERE lane=? AND job_id=? AND target_id=? AND state='claimed'",(row['lane'],row['job_id'],row['target_id']))
    db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'abandoned_unsent_claim_recovery',?,?)",
        (row['paper_id'],json.dumps({'lane':row['lane'],'job_id':row['job_id'],'target_id':row['target_id'],
            'original_ledger_sha256':record['_ledger_sha256'],'old_owner_pid':record['owner_pid'],'archive':str(archive)}),now()))
    return True


def _preparation_only(db, row, root, entry, health):
    """Release a failed producer's provisional lease, never its old receipts.

    This exact producer error is raised before material readiness, while the
    browser owner requires ready materials before touching the assigned page.
    Missing receipts alone are deliberately insufficient.
    """
    if health.get('health') not in ('completed_saved','raw_path_repair','healthy_blank'):
        return False
    if row['lane']=='review':
        source=db.execute('SELECT state,error,folder,source_sha256 FROM card_review_jobs WHERE id=? AND paper_id=?', (row['job_id'],row['paper_id'])).fetchone()
        if not source or source['state']!='needs_user' or not source['error']:return False
        folder=Path(source['folder']).resolve()
        if not folder.is_relative_to(root/'card_reviews'):return False
        # A complete packet is the mandatory browser-readiness barrier. Keep
        # all jobs with a packet/receipt on the normal receipt recovery path.
        if (folder/'packet.json').exists() or not (folder/'prepare.log').exists():return False
        try:
            request=json.loads((folder/'visual-request.json').read_text())
            if Path(request['output_folder']).resolve()!=folder:return False
            packet=json.loads((Path(request['input_folder'])/'packet.json').read_text())
            if packet['source_original_sha256']!=source['source_sha256']:return False
            if hashlib.sha256((folder/'source.pdf').read_bytes()).hexdigest()!=packet['input_hashes']['source.pdf']:return False
        except (OSError,ValueError,KeyError,TypeError):return False
    else:
        source = db.execute('SELECT state,error FROM web_card_jobs WHERE paper_id=?', (row['paper_id'],)).fetchone()
        material = db.execute('SELECT state,error,target_id FROM web_page_queue WHERE paper_id=?', (row['paper_id'],)).fetchone()
        correction = db.execute('SELECT state,error,paper_id FROM card_correction_jobs WHERE id=?', (row['job_id'],)).fetchone() if row['lane']=='correction' else None
        if (not source or source['state'] != 'needs_inspection' or not source['error'].startswith('材料准备：')
                or not material or material['state'] != 'failed' or material['target_id'] != row['target_id']
                or not material['error'] or source['error']!='材料准备：'+material['error']
                or row['lane']=='correction' and (not correction or correction['state'] != 'needs_user'
                    or correction['error'] != source['error'] or correction['paper_id'] != row['paper_id'])):
            return False
        folder = root/'web_cards'/row['paper_id']
    paths = sorted(folder.rglob('attempt.json'))
    # Current attempts, or a historic use of this exact target, require the
    # normal receipt reconciliation. Other old unknown requests remain pinned.
    if any(not p.is_relative_to(folder/'history') for p in paths):
        return False
    records = [read_attempt(p) for p in paths]
    if any(r.get('target_id') == row['target_id'] for r in records):
        return False
    matched = health.get('matched_record_path')
    if health.get('health')=='healthy_blank':
        ended=health.get('evidence',{}).get('completed_history_paths')
        if (not ended and entry.get('never_submitted') is True and
                health.get('evidence',{}).get('never_submitted_verified') is True):
            # The enrolled owner's complete target index plus a fresh blank
            # snapshot prove this slot was unused. Release only preparation's
            # lease; the source job and its old unknown receipts stay blocked.
            return (sorted(folder.rglob('attempt.json'))==paths and
                    all(read_attempt(r['_ledger_path'])['_ledger_sha256']==r['_ledger_sha256'] for r in records))
        if not ended:return False
        saved=[read_attempt(p) for p in ended]
        return (sorted(folder.rglob('attempt.json'))==paths and
            all(read_attempt(r['_ledger_path'])['_ledger_sha256']==r['_ledger_sha256'] for r in records+saved))
    if not matched:
        return False
    saved = read_attempt(matched)
    if (saved.get('state') != 'response_saved' or saved.get('target_id') != row['target_id']
            or entry.get('raw_sha256') != saved.get('raw_sha256')
            or entry.get('conversation_url') != saved.get('conversation_url')
            or Path(matched).is_relative_to(folder)):
        return False
    return (sorted(folder.rglob('attempt.json')) == paths and
            all(read_attempt(r['_ledger_path'])['_ledger_sha256'] == r['_ledger_sha256'] for r in records)
            and read_attempt(matched)['_ledger_sha256'] == saved['_ledger_sha256'])


def locate_retired_receipt(record, *, archive_path=None):
    """Resolve an archived receipt only by its unchanged bytes and target."""
    path=Path(record['_ledger_path'])
    try:
        current=read_attempt(path)
        if current['_ledger_sha256']==record['_ledger_sha256']:return current
    except FileNotFoundError:pass
    paper=next((parent for parent in path.parents if parent.parent.name in ('web_cards','card_reviews')),None)
    if paper is None:raise ValueError('原回执不在登记材料目录')
    matches=[]
    for candidate in paper.rglob('attempt.json'):
        scan_checkpoint()
        current=read_attempt(candidate)
        if (current['_ledger_sha256']==record['_ledger_sha256'] and
                current.get('target_id')==record.get('target_id')):matches.append(current)
    if not matches and archive_path is not None:
        archived=read_attempt(archive_path)
        if (archived['_ledger_sha256']==record['_ledger_sha256'] and
                archived.get('target_id')==record.get('target_id')):
            archived.update(_evidence_archive_path=archived['_ledger_path'],_ledger_path=record['_ledger_path'])
            return archived
    if len(matches)!=1:raise ValueError('原回执未找到唯一相同指纹归档，保留原记录')
    return matches[0]


def _diagnostic_verified(path, expected, cache):
    """Reuse a hash only while all filesystem identity/version fields match."""
    path=Path(path)
    def key(stat):return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    before=key(path.stat());name=str(path.resolve())
    if cache.get(name)==(before,expected):return True
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    after=key(path.stat())
    if before!=after or actual!=expected:
        cache.pop(name,None);return False
    cache[name]=(after,expected)
    return True

def recover_claims(catalog, entries, health, *, at, retirement_cache=None):
    retirement_cache={} if retirement_cache is None else retirement_cache
    if health.get('state') not in ('checked', 'pending', 'waiting_interval'):
        return []
    root = catalog.path.parent.resolve()
    from .owner_upload_jobs import active_lease_targets
    active_uploads=active_lease_targets(root)
    # Retirement proof can only release an existing claimed retired target.
    # Snapshot this negative filter before expensive archive reads; the write
    # transaction below still rechecks current rows and every original guard.
    with catalog.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='shared_page_backlog'").fetchone():return []
        claimed=list(db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'"))
        retired_targets={row['target_id'] for row in claimed
                         if row['target_id'] not in active_uploads
                         and entries.get(row['target_id'],{}).get('state')=='retired_replaced'}
    started=time.monotonic()
    scope={'state':'scanning','started_at':time.time(),'candidate_targets':len(retired_targets),
           'journals_seen':0,'unrelated_skipped':0,'records_verified':0}
    health['retirement_scan']=scope
    retired = {}
    journals=(root/'shared-page-repairs').glob('*/journal.json') if retired_targets else ()
    for path in journals:
        # This evidence scan precedes BEGIN IMMEDIATE below. Keep the original
        # owner loop responsive without yielding inside the lease write CAS.
        scan_checkpoint()
        scope['journals_seen']+=1
        try:
            journal = json.loads(path.read_text())
            if journal.get('old_target_id') not in retired_targets:
                scope['unrelated_skipped']+=1
                continue
            if journal.get('state') != 'ready' or not (journal.get('health', {}).get('replace_allowed') is True or
                    journal.get('unrecoverable_fallback') is True and journal.get('close_authorized') is True
                    and journal.get('requeue_allowed') is False):
                continue
            hashes=journal.get('archive_hashes', {})
            if not {'health.json','body.txt','page.html','ledger-before.json'}.issubset(hashes):
                continue
            if 'page.png' not in hashes:
                if not {'page.mhtml','capture.json'}.issubset(hashes):continue
                capture=json.loads((path.parent/'diagnostics/capture.json').read_text())
                if capture.get('method')!='resident_cdp_mhtml' or capture.get('screenshot_available') is not False:continue
            if any(Path(name).name!=name or
                   not _diagnostic_verified(path.parent/'diagnostics'/name,expected,retirement_cache)
                   for name,expected in hashes.items()):
                continue
            record=journal.get('record')
            if record:
                # Completed journals keep immutable original paths. A later bounded
                # review retry can archive that receipt; absence is not release proof
                # and must not abort maintenance of every other fixed page.
                current = locate_retired_receipt(record,archive_path=path.parent/'diagnostics/ledger-before.json')
                if current['_ledger_sha256']==record['_ledger_sha256']:
                    retired[journal['old_target_id']]=current
                    scope['records_verified']+=1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            health.setdefault('recovery_errors', []).append({
                'stage': 'retired_receipt_evidence', 'path': str(path),
                'reason': type(exc).__name__ + ': ' + str(exc)[:500]})
            continue  # Unreadable retirement proof grants no release or retry.
    scope.update(state='checked',completed_at=time.time(),duration_seconds=time.monotonic()-started)
    # A read-only negative filter cannot authorize a release. It avoids taking
    # the global writer lock for busy/unknown pages or absent retirement proof.
    # Newly claimed rows wait for the original owner's next normal pass.
    candidates=set()
    for row in claimed:
        tid=row['target_id'];entry=entries.get(tid,{})
        h=health.get('pages',{}).get(tid,{})
        checked=h.get('evidence',{}).get('checked_at',health.get('checked_at',0))
        if (tid in active_uploads or type(checked) not in (int,float)
                or not math.isfinite(checked) or at-checked>60 or checked>at+1):continue
        ended=retired.get(tid)
        if ended and entry.get('state')=='retired_replaced':
            folder=root/('card_reviews' if row['lane']=='review' else 'web_cards')/row['paper_id']
            possible=(Path(ended['_ledger_path']).is_relative_to(folder) and
                      (row['lane']!='review' or ended.get('review_id')==row['job_id']))
        else:
            possible=(entry.get('state') in ('ready','ready_blank') and
                      h.get('health') in ('healthy_blank','completed_saved','raw_path_repair'))
        if possible:candidates.add((row['lane'],row['job_id'],tid))
    write_status={'state':'no_candidates','candidate_claims':len(candidates),
                  'write_lock_policy':'nonblocking_original_owner_retry'}
    health['claim_recovery']=write_status
    if not candidates:return []
    released = []
    with catalog.connect() as db:
        # A browser maintenance callback must not spend the Catalog's20s busy
        # timeout under the shared submit lock. No request/state changes occur
        # before the original lease CAS is acquired; the next pass rechecks all.
        db.execute('PRAGMA busy_timeout=0')
        lock_started=time.monotonic()
        try:db.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            if (getattr(exc,'sqlite_errorcode',0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
            write_status.update(state='deferred_database_busy',
                                write_lock_wait_seconds=time.monotonic()-lock_started)
            return []
        write_status.update(state='checked',write_lock_wait_seconds=time.monotonic()-lock_started)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='shared_page_backlog'").fetchone():
            return []
        for row in list(db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'")):
            if (row['lane'],row['job_id'],row['target_id']) not in candidates:continue
            if row['target_id'] in active_uploads:continue
            entry = entries.get(row['target_id'], {})
            h = health.get('pages', {}).get(row['target_id'], {})
            checked = h.get('evidence',{}).get('checked_at',health.get('checked_at',0))
            if type(checked) not in (int,float) or not math.isfinite(checked) or at-checked > 60 or checked > at+1:
                continue
            ended=retired.get(row['target_id'])
            if ended and entry.get('state')=='retired_replaced':
                original=Path(ended['_ledger_path'])
                folder=root/('card_reviews' if row['lane']=='review' else 'web_cards')/row['paper_id']
                if (original.is_relative_to(folder) and
                        (row['lane']!='review' or ended.get('review_id')==row['job_id'])):
                    db.execute("DELETE FROM shared_page_backlog WHERE lane=? AND job_id=? AND target_id=? AND state='claimed'", (row['lane'],row['job_id'],row['target_id']))
                    released.append({k:row[k] for k in ('lane','job_id','paper_id','target_id')})
                continue
            if entry.get('state') not in ('ready', 'ready_blank') or h.get('health') not in ('healthy_blank', 'completed_saved', 'raw_path_repair'):
                continue
            if _recover_abandoned(db,row,root,h,at=at):
                released.append({**{k:row[k] for k in ('lane','job_id','paper_id','target_id')},'reason':'dead_owner_explicit_unsent'})
                continue
            if _preparation_only(db, row, root, entry, h):
                db.execute("DELETE FROM shared_page_backlog WHERE lane=? AND job_id=? AND target_id=? AND state='claimed'", (row['lane'],row['job_id'],row['target_id']))
                from core.api import catalog__now as now
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'preparation_claim_release',?,?)",
                           (row['paper_id'],json.dumps({'job_id':row['job_id'],'target_id':row['target_id'],
                            'reason':'preparation_failed_before_page_use','matched_record_path':h.get('matched_record_path')}),now()))
                released.append({**{k:row[k] for k in ('lane','job_id','paper_id','target_id')}, 'reason':'preparation_failed_before_page_use'})
                continue
            if row['lane'] == 'review':
                source = db.execute('SELECT state,folder FROM card_review_jobs WHERE id=? AND paper_id=?', (row['job_id'], row['paper_id'])).fetchone()
                folder = Path(source['folder']) if source else None
            else:
                source = db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?', (row['paper_id'],)).fetchone()
                folder = root / 'web_cards' / row['paper_id']
            if not source or source['state'] in ('preparing', 'submitting', 'collecting'):
                continue
            # All active and archived receipts must end, regardless of retry cap.
            paths = list(folder.rglob('attempt.json'))
            if not paths:
                continue  # Absence never proves that a browser operation ended.
            records = [read_attempt(p) for p in paths]
            records = [r for r in records if r.get('target_id') == row['target_id']]
            if not records:
                continue
            if any(r.get('state') not in ('not_sent', 'response_saved') or
                   r.get('state') == 'not_sent' and r.get('send_click_started') is not False for r in records):
                continue
            proven = h.get('matched_record_path') in {r['_ledger_path'] for r in records}
            if h.get('health') == 'healthy_blank':
                # The live owner classified the complete target history. A new
                # unknown receipt is excluded above; tasks stay in their state.
                proven = bool(h.get('evidence', {}).get('completed_history_paths')) or all(r.get('state') == 'not_sent' for r in records)
            if not proven:
                continue
            # Recheck on-disk evidence inside the same SQLite lease CAS.
            if any(read_attempt(r['_ledger_path'])['_ledger_sha256'] != r['_ledger_sha256'] for r in records):
                continue
            db.execute("DELETE FROM shared_page_backlog WHERE lane=? AND job_id=? AND target_id=? AND state='claimed'", (row['lane'], row['job_id'], row['target_id']))
            released.append({k: row[k] for k in ('lane', 'job_id', 'paper_id', 'target_id')})
    return released
