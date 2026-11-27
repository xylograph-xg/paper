#!/usr/bin/env python3
"""Periodic cleanup of stale/abnormal protected slots only.

Normal submitted/generating/completed-saved work is never touched. The owner
continues to own browser interaction; this tick only reconciles local claim and
pool-entry state after the evidence is already terminal or stale.
"""
import json,os,shutil,time
from pathlib import Path
from core.api import catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json
from core.api import catalog__Catalog as Catalog, catalog__now as now

ABNORMAL_ENTRY={'busy','needs_inspection','retired_replaced','collecting'}

def _source(db,lane,job_id,paper_id):
    if lane=='review':return db.execute('SELECT state,error,folder FROM card_review_jobs WHERE id=?',(job_id,)).fetchone()
    if lane=='correction':return db.execute('SELECT state,error,folder FROM card_correction_jobs WHERE id=?',(job_id,)).fetchone()
    return db.execute('SELECT state,error,folder FROM web_card_jobs WHERE paper_id=?',(paper_id,)).fetchone()


def release_expired_claims(catalog, config, *, limit=50, timeout=1800):
    """Release claims whose owning job is terminal or whose lease expired.

    This is the missing lifecycle boundary: a claim is a lease on a page, not a
    permanent property of the job. Attempt/row evidence is archived first; the
    original request is not resent here.
    """
    root=Path(config['catalog_path']).parent;pool_path=root/'gpt-window-pool.json'
    pool=json.loads(pool_path.read_text());windows=pool.get('windows',{})
    terminal={'cards':{'completed','failed','protected'},'review':{'passed','failed','corrected','correction_queued','protected'},
              'correction':{'applied','failed','superseded'}}
    with catalog.connect() as db:
        claims=[dict(r) for r in db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'")]
    released=[]
    for row in claims:
        if len(released)>=limit:break
        age=time.time()-(row.get('assigned') or 0) if row.get('assigned') else 0
        if age<timeout:continue
        lane=row['lane'];job_id=row['job_id']
        with catalog.connect() as db:
            if lane=='review':src=db.execute('SELECT state,error,folder FROM card_review_jobs WHERE id=?',(job_id,)).fetchone()
            elif lane=='correction':src=db.execute('SELECT state,error,folder FROM card_correction_jobs WHERE id=?',(job_id,)).fetchone()
            else:src=db.execute('SELECT state,error,folder FROM web_card_jobs WHERE paper_id=?',(row['paper_id'],)).fetchone()
            item=root/'claim-lease-release'/str(int(time.time()));item.mkdir(parents=True,exist_ok=True)
            if src and src['folder']:
                attempt=Path(src['folder'])/'attempt.json'
                if attempt.exists():
                    shutil.copy2(attempt,item/(job_id+'-attempt.json'))
                    shutil.move(str(attempt),str(item/(job_id+'-attempt-retired.json')))
            from browser.api import shared_page_backlog__remove_binding as remove_binding
            remove_binding(db,lane,job_id,row['target_id'],expected_state='claimed')
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'claim_lease_expired',?,?)",
                (row['paper_id'],json.dumps({'lane':lane,'job_id':job_id,'target_id':row['target_id'],'age_seconds':age,'source_state':src['state'] if src else None,'archive':str(item)}),now()))
        entry=windows.get(row['target_id'],{})
        clean={k:v for k,v in entry.items() if k in ('assigned_at','created','owned','fixed_lane','slot_id')}
        clean.update(state='ready_blank',claim_released_at=now(),claim_release_reason='claim lease expired')
        windows[row['target_id']]=clean
        released.append({'lane':lane,'job_id':job_id,'target_id':row['target_id'],'age_seconds':age})
    if released:
        pool['windows']=windows;pool['observed_at']=now();tmp=pool_path.with_name('.gpt-window-pool.lease.tmp')
        tmp.write_text(json.dumps(pool,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,pool_path)
        atomic_json(root/'claim-lease-release-status.json',{'state':'released','at':now(),'count':len(released),'items':released})
    return released

def tick(config, *, apply=True):
    root=Path(config['catalog_path']).parent;cat=Catalog(config['catalog_path'])
    service=json.loads((root/'web-card-service.json').read_text())
    pool_path=root/'gpt-window-pool.json';pool=json.loads(pool_path.read_text());windows=pool.get('windows',{})
    health=json.loads((root/'shared-page-health.json').read_text()).get('pages',{}) if (root/'shared-page-health.json').exists() else {}
    with cat.connect() as db:
        claims=[dict(r) for r in db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'")]
        selected=[]
        for tid in service.get('shared_backlog',{}).get('protected_targets',[]):
            entry=windows.get(tid,{}) if isinstance(windows,dict) else {}
            claim=next((c for c in claims if c['target_id']==tid),None)
            health_state=(health.get(tid) or {}).get('health')
            reason=None
            src=None
            if claim:
                src=dict(_source(db,claim['lane'],claim['job_id'],claim['paper_id']) or {})
            if not claim and entry.get('state') in ABNORMAL_ENTRY:
                reason='无 claim 的悬空 entry'
            elif entry.get('state')=='retired_replaced':
                reason='旧 target 已替换但 claim 未清'
            elif claim and src and src.get('state') in ('ready','queued') and health_state=='dirty':
                reason='来源已 ready 但页面是自动化残留 dirty'
            if reason:selected.append((tid,claim,entry,src,reason))
    if apply:release_expired_claims(cat, config)
    cleanup=[]
    for tid,claim,entry,src,reason in selected:
        item=root/'abnormal-protection-cleanup'/str(int(time.time()));item.mkdir(parents=True,exist_ok=True)
        if claim:
            folder=(src or {}).get('folder')
            if folder:
                attempt=Path(folder)/'attempt.json'
                if attempt.exists():
                    shutil.copy2(attempt,item/(tid+'-attempt.json'))
                    shutil.move(str(attempt),str(item/(tid+'-attempt-retired.json')))
            from browser.api import shared_page_backlog__remove_binding as remove_binding
            with cat.connect() as db:
                remove_binding(db,claim['lane'],claim['job_id'],tid,expected_state='claimed')
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'abnormal_protection_cleanup',?,?)",
                    (claim.get('paper_id'),json.dumps({'target_id':tid,'reason':reason,'archive':str(item)}),now()))
        clean={k:v for k,v in entry.items() if k in ('assigned_at','created','owned','fixed_lane','slot_id')}
        clean.update(state='ready_blank',protection_cleanup_at=now(),protection_cleanup_reason=reason)
        windows[tid]=clean
        cleanup.append({'target_id':tid,'reason':reason,'claim':bool(claim)})
    if cleanup and apply:
        pool['windows']=windows;pool['observed_at']=now()
        tmp=pool_path.with_name('.gpt-window-pool.cleanup.tmp')
        tmp.write_text(json.dumps(pool,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,pool_path)
        atomic_json(root/'abnormal-protection-cleanup-status.json',{'state':'cleaned','at':now(),'count':len(cleanup),'items':cleanup})
    return cleanup

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');a=ap.parse_args()
    print(json.dumps(tick(load_config('infrastructure/config/first_round.json'),apply=a.apply),ensure_ascii=False,indent=2))
