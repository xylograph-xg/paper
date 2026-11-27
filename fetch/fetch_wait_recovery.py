"""Repair only evidenced pre-request host waits misrouted into fallback.

Preserves attempts and old events; never revives terminal targets or source cooldowns.
"""
import json,time
from .fetch_policy import fingerprint
from .network import ready,DeferredRequest
from urllib.parse import urlsplit

def reconcile(catalog,limit=20):
    changed=[]
    with catalog.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fetch_targets'").fetchone():return []
        rows=db.execute("SELECT t.*,p.metadata,p.asset_path,p.decision FROM fetch_targets t JOIN papers p ON p.id=t.paper_id WHERE t.state='ready' AND t.retry_at>? AND p.acquisition!='available' AND p.decision NOT IN ('reject','ignore') AND t.paper_id IN (SELECT paper_id FROM events WHERE kind='acquisition_fast_pending' AND json_extract(payload,'$.attempts[0].kind') IN ('deferred','resource_wait') AND json_extract(payload,'$.attempts[0].code') IS NULL) LIMIT ?",(time.time(),limit)).fetchall()
    for r in rows:
        metadata=json.loads(r['metadata'])
        if r['input_hash']!=fingerprint(metadata) or any(metadata.get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):continue
        with catalog.connect() as db:
            fast=db.execute("SELECT id,payload FROM events WHERE paper_id=? AND kind='acquisition_fast_pending' ORDER BY id DESC LIMIT 1",(r['paper_id'],)).fetchone()
        if not fast:continue
        errors=json.loads(fast['payload']).get('attempts') or []
        if not errors or not all(x.get('kind') in ('deferred','resource_wait') and x.get('code') is None and x.get('retry_at',0)<=time.time() and x.get('url') in metadata.get('pdf_urls',[]) for x in errors):continue
        try:
            for x in errors:ready('pdf:'+urlsplit(x['url']).hostname,catalog.path.parent)
        except DeferredRequest:continue
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE paper_id=? AND kind IN ('acquire','acquire_fallback','import') AND state IN ('queued','running','waiting_storage')",(r['paper_id'],)).fetchone():continue
            if db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='fetch_resource_wait_reconciled' AND json_extract(payload,'$.fast_event_id')=?",(r['paper_id'],fast['id'])).fetchone():continue
            updated=db.execute("UPDATE fetch_targets SET retry_at=0,error='已核对历史未发请求槽位等待；保留原次数及失败记录' WHERE paper_id=? AND state='ready' AND input_hash=? AND retry_at=?",(r['paper_id'],r['input_hash'],r['retry_at'])).rowcount
            if not updated:continue
            if r['pending_key']:db.execute("UPDATE discovery_pending SET state='pending',retry_at=0 WHERE key=? AND state='pending'",(r['pending_key'],))
            from core.api import catalog__now as now
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(r['paper_id'],'fetch_resource_wait_reconciled',json.dumps({'fast_event_id':fast['id'],'input_hash':r['input_hash'],'old_retry_at':r['retry_at'],'attempts_preserved':r['attempts'],'errors':errors}),now()))
            changed.append(r['paper_id'])
    return changed
