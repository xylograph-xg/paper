"""Bounded, auditable re-queue of OA records that were terminal before the OA gate.

Only records with an OA/preprint/repository route are touched. The original
record is preserved; the operation changes queue state and resets the retry
ledger for the selected paper so the new OA-only acquisition path can evaluate
it again. No request is sent by this tool.
"""
import argparse
import json
import time

from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config
from .oa_policy import eligible, priority


def classify(catalog, max_priority=0):
    with catalog.connect() as db:
        rows=db.execute("SELECT key,state,record FROM discovery_pending WHERE state IN ('pending','blocked_fetch')").fetchall()
    selected=[];closed=[]
    for row in rows:
        record=json.loads(row['record'])
        if eligible(record) and priority(record)<=max_priority:
            selected.append(row['key'])
        elif row['state']=='blocked_fetch' and not eligible(record):
            closed.append(row['key'])
    return selected,closed


def requeue(catalog,max_priority=0,limit=500,dry_run=False,exclude_closed=False):
    selected,closed=classify(catalog,max_priority)
    selected=selected[:max(0,int(limit))]
    at=time.time();reason='OA backlog requeue 2026-10-17（OA-only 策略）'
    manifest={'at':at,'max_priority':max_priority,'limit':limit,'dry_run':dry_run,
              'selected':len(selected),'closed_available':len(closed),'exclude_closed':exclude_closed,
              'selected_keys':selected,'closed_keys':closed if exclude_closed else []}
    if not dry_run:
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for key in selected:
                # Reset the target ledger before the pending row: the
                # keep_fetch_policy_pending trigger would otherwise restore
                # the old terminal/backoff state immediately.
                papers={r[0] for r in db.execute('SELECT paper_id FROM fetch_pending_links WHERE key=?',(key,))}
                papers.update(r[0] for r in db.execute('SELECT paper_id FROM fetch_targets WHERE pending_key=?',(key,)))
                for paper_id in papers:
                    db.execute("UPDATE fetch_targets SET state='ready',attempts=0,retry_at=0,error='' WHERE paper_id=?",(paper_id,))
                    db.execute("UPDATE fetch_urls SET attempts=0,failure_class=NULL,error='',retry_at=0 WHERE paper_id=?",(paper_id,))
                db.execute("UPDATE discovery_pending SET state='pending',retry_at=?,error=? WHERE key=?",(at,reason,key))
            if exclude_closed:
                for key in closed:
                    db.execute("UPDATE discovery_pending SET state='excluded',retry_at=0,error=? WHERE key=? AND state='blocked_fetch'",
                               ('closed access skipped（OA-only 策略）',key))
    path=catalog.path.parent/('oa-requeue-%d.json'%int(at))
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'selected':len(selected),'closed_available':len(closed),'manifest':str(path),'dry_run':dry_run}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--max-priority',type=int,default=0,choices=(0,1))
    parser.add_argument('--limit',type=int,default=500)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--exclude-closed',action='store_true')
    args=parser.parse_args()
    config=load_config(args.config)
    result=requeue(Catalog(config['catalog_path']),args.max_priority,args.limit,args.dry_run,args.exclude_closed)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
