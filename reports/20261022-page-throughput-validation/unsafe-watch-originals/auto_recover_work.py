#!/usr/bin/env python3
"""Automatic, bounded recovery of stale technical work.

Rules:
* cards needs_inspection >30 min -> archive, fresh folder, requeue
* reviews submitted >30 min -> archive old row, fresh rerun folder, queue
* correction failed due changed review -> reset the current card's review to
  a fresh rerun; old correction/report remains archived.

Never invents a pass and never reuses an old attempt.
"""
import hashlib,json,os,shutil,time
from datetime import datetime
from pathlib import Path
from core.api import catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json
from core.api import catalog__Catalog as Catalog, catalog__now as now

def _age(value):
    if isinstance(value,(int,float)):return max(0,time.time()-value)
    try:return max(0,time.time()-datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp())
    except (ValueError,TypeError):return 0

def _archive(folder,base,pid):
    item=Path(base)/pid;item.mkdir(parents=True,exist_ok=True)
    old=Path(folder) if folder else None
    if old and old.exists():
        for name in ('attempt.json','response-raw.txt','packet.json','card.json'):
            p=old/name
            if p.exists():shutil.copy2(p,item/name)
    return item

def _clear_page_state(con,pid):
    con.execute("DELETE FROM shared_page_backlog WHERE paper_id=? AND state='claimed'",(pid,))

def _card_source(con,pid):
    row=con.execute("SELECT asset_path,card_path FROM papers WHERE id=?",(pid,)).fetchone()
    if not row or not row['asset_path'] or not Path(row['asset_path']).exists():return None
    if row['card_path']:return None
    return row

def requeue_cards(catalog,config,limit=20):
    root=Path(config['catalog_path']).parent;base=root/'auto-recovered-cards'/str(int(time.time()));out=[]
    with catalog.connect() as con:
        rows=[dict(r) for r in con.execute("SELECT * FROM web_card_jobs WHERE state='needs_inspection'")]
    for job in rows:
        if len(out)>=limit:break
        if _age(job['updated'])<1800:continue
        with catalog.connect() as con:
            if not _card_source(con,job['paper_id']):continue
            item=_archive(job['folder'],base,job['paper_id'])
            (item/'old-job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2)+'\n')
            folder=root/'web_cards'/job['paper_id'];folder.mkdir(parents=True,exist_ok=True)
            con.execute("UPDATE web_card_jobs SET state='queued',folder=?,error=?,attempts=0,retry_at=0,updated=? WHERE paper_id=? AND state='needs_inspection'",
                        (str(folder),'超时自动撤回，归档后重新排队',now(),job['paper_id']))
            con.execute("INSERT INTO web_page_queue(paper_id,target_id,state,assigned,error) VALUES(?,'','waiting',0,?) ON CONFLICT(paper_id) DO UPDATE SET target_id='',state='waiting',assigned=0,error=excluded.error",
                        (job['paper_id'],'超时自动撤回重排'))
            _clear_page_state(con,job['paper_id'])
            con.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'card_timeout_requeue',?,?)",
                        (job['paper_id'],json.dumps({'old_folder':job['folder'],'archive':str(item)}),now()))
        out.append(job['paper_id'])
    if out:atomic_json(root/'auto-recover-status.json',{'state':'ok','at':now(),'cards':len(out)})
    return out

def _rerun_review(con,pid,card_sha,root,reason):
    row=con.execute("SELECT * FROM card_review_jobs WHERE paper_id=? AND card_sha256=?",(pid,card_sha)).fetchone()
    if not row:return None
    job=dict(row);folder=root/'card_reviews'/pid/(job['id']+'-auto-'+str(int(time.time())));folder.mkdir(parents=True,exist_ok=True)
    (folder/'previous-job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2)+'\n')
    con.execute("UPDATE card_review_jobs SET state='queued',folder=?,error='',result='{}',updated=? WHERE id=?",(str(folder),now(),job['id']))
    con.execute("INSERT OR IGNORE INTO shared_workflow_arrivals(lane,job_id,queued_at,basis) VALUES('review',?,?,?)",(job['id'],time.time(),reason))
    _clear_page_state(con,pid)
    return job['id']

def rerun_submitted_reviews(catalog,config,limit=5):
    root=Path(config['catalog_path']).parent;out=[]
    with catalog.connect() as con:
        rows=[dict(r) for r in con.execute("SELECT * FROM card_review_jobs WHERE state='submitted'")]
    for job in rows:
        if len(out)>=limit:break
        if _age(job['updated'])<1800:continue
        with catalog.connect() as con:
            if con.execute("SELECT 1 FROM papers WHERE id=?",(job['paper_id'],)).fetchone() is None:continue
            rid=_rerun_review(con,job['paper_id'],job['card_sha256'],root,'review_submitted_timeout_20261019')
            if rid:out.append(rid)
    return out

def rerun_changed_corrections(catalog,config,limit=5):
    root=Path(config['catalog_path']).parent;out=[]
    with catalog.connect() as con:
        rows=[dict(r) for r in con.execute("SELECT DISTINCT paper_id FROM card_correction_jobs WHERE state='failed' AND error LIKE '%核验报告变化%'")]
    for row in rows:
        if len(out)>=limit:break
        pid=row['paper_id']
        with catalog.connect() as con:
            score=con.execute("SELECT card_sha256 FROM paper_card_scores WHERE paper_id=?",(pid,)).fetchone()
            if not score:continue
            rid=_rerun_review(con,pid,score['card_sha256'],root,'correction_report_changed_20261019')
            if rid:out.append(rid)
    return out

def tick(config):
    cat=Catalog(config['catalog_path'])
    result={'cards':requeue_cards(cat,config),'reviews':rerun_submitted_reviews(cat,config),'corrections':rerun_changed_corrections(cat,config)}
    # The no-user policy must survive an owner/material-thread stall.
    try:
        from core.api import automatic_issue_handler__normalize_needs_user as normalize_needs_user
        result['normalized']=len(normalize_needs_user(cat,config))
    except (OSError,ValueError,TypeError) as exc:
        result['normalized_error']=str(exc)[:300]
    atomic_json(Path(config['catalog_path']).parent/'auto-recover-work-status.json',{'at':now(),**result})
    return result

if __name__=='__main__':
    print(json.dumps(tick(load_config('infrastructure/config/first_round.json')),ensure_ascii=False,indent=2))
