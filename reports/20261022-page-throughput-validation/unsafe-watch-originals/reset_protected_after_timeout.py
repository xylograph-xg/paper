#!/usr/bin/env python3
"""Reset protected page slots after a timeout, preserving an audit archive.

The user explicitly authorizes reopening the affected slot and clearing its
claim/pool/attempt protection after 10 minutes. Original requests are archived,
never marked unsent, and are never resent by this tool.
"""
import argparse,json,os,shutil,time
from pathlib import Path
from core.api import catalog__load_config as load_config
from core.api import catalog__Catalog as Catalog, catalog__now as now

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');ap.add_argument('--minutes',type=float,default=10);a=ap.parse_args()
    c=load_config('infrastructure/config/first_round.json');cat=Catalog(c['catalog_path']);root=Path(c['catalog_path']).parent
    service=json.loads((root/'web-card-service.json').read_text())
    pool=json.loads((root/'gpt-window-pool.json').read_text())
    windows=pool.get('windows',{})
    protected=set(service.get('shared_backlog',{}).get('protected_targets') or [])
    with cat.connect() as db:
        claims=[dict(r) for r in db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'")]
    claim_by={r['target_id']:r for r in claims}
    targets=sorted(protected)
    stamp=str(int(time.time()));archive_root=root/'protection-resets'/stamp
    plans=[]
    for tid in targets:
        entry=windows.get(tid,{}) if isinstance(windows,dict) else {}
        claim=claim_by.get(tid)
        age=None
        for value in ((claim or {}).get('assigned'),entry.get('assigned_at'),entry.get('updated'),entry.get('created')):
            if isinstance(value,(int,float)) and value>0:
                age=max(0,(time.time()-value)/60);break
        plans.append((tid,claim,entry,age))
    selected=[p for p in plans if p[3] is None or p[3]>=a.minutes]
    print(json.dumps({'protected':len(targets),'selected':len(selected),'minutes':a.minutes,
        'targets':[{'target':p[0][:12],'age_minutes':None if p[3] is None else round(p[3],1),
                    'claim':bool(p[1]),'entry':p[2].get('state')} for p in selected]},ensure_ascii=False,indent=2))
    if not a.apply:return
    archive_root.mkdir(parents=True,exist_ok=True)
    for tid,claim,entry,age in selected:
        item=archive_root/tid;item.mkdir(parents=True,exist_ok=True)
        receipt={'target_id':tid,'reset_at':now(),'age_minutes':age,'entry_before':entry,'claim':claim,
                 'original_request_reset_not_resent':True}
        folder=None
        if claim:
            with cat.connect() as db:
                if claim['lane']=='review':
                    row=db.execute('SELECT folder FROM card_review_jobs WHERE id=?',(claim['job_id'],)).fetchone();folder=row['folder'] if row else None
                elif claim['lane']=='correction':
                    row=db.execute('SELECT folder FROM card_correction_jobs WHERE id=?',(claim['job_id'],)).fetchone();folder=row['folder'] if row else None
                else:
                    row=db.execute('SELECT folder FROM web_card_jobs WHERE paper_id=?',(claim['paper_id'],)).fetchone();folder=row['folder'] if row else None
        if folder:
            attempt=Path(folder)/'attempt.json'
            if attempt.exists():
                shutil.copy2(attempt,item/'attempt.json');shutil.move(str(attempt),str(item/'attempt-retired.json'))
                receipt['attempt_archived']=True
        if claim:
            from browser.api import shared_page_backlog__remove_binding as remove_binding
            with cat.connect() as db:
                remove_binding(db,claim['lane'],claim['job_id'],tid,expected_state='claimed')
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'protection_timeout_reset',?,?)",
                    (claim.get('paper_id'),json.dumps({'target_id':tid,'age_minutes':age,'archive':str(item)}),now()))
        clean={k:v for k,v in entry.items() if k in ('assigned_at','created','owned','fixed_lane','slot_id')}
        clean.update({'state':'ready_blank','protection_reset':now(),'protection_reset_reason':'超过10分钟，用户授权重开并重置保护','protection_archive':str(item)})
        windows[tid]=clean
        (item/'reset.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    pool['windows']=windows;pool['observed_at']=time.time()
    tmp=root/'.gpt-window-pool.reset.tmp';tmp.write_text(json.dumps(pool,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,root/'gpt-window-pool.json')
    print('reset',len(selected),'archive',archive_root)
if __name__=='__main__':main()
