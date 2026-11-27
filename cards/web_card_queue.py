"""Persistent web-only card queue and reproducible approximate 30% selection."""
import json
import math
import re
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__now as now


def install(catalog):
    from reading.api import manual_literature__install as install_manual_library
    install_manual_library(catalog)
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS web_card_jobs(
          paper_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, title TEXT NOT NULL,
          selection TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
          provider TEXT, folder TEXT, error TEXT NOT NULL DEFAULT '',
          attempts INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL,
          retry_at REAL NOT NULL DEFAULT 0)''')
    from browser.api import shared_workflow_queue__install as arrival_install
    arrival_install(catalog)


def ranking(paper, config):
    m=paper['metadata'];text=(paper['title']+' '+(m.get('abstract') or '')).casefold()
    terms={word for q in config.get('topic_queries',[]) for word in re.findall(r'[\w-]+',q.casefold()) if len(word)>3}
    matches=sorted(t for t in terms if t in text)
    a=paper.get('assessment') or {}
    relevance=a.get('relevance',0) if not a.get('evidence_unverified') else 0
    if isinstance(relevance,bool) or not isinstance(relevance,(int,float)) or not math.isfinite(relevance):relevance=0
    venue=(m.get('venue') or '').casefold().strip()
    aliases={k.casefold():v.casefold() for k,v in config.get('journal_aliases',{}).items()}
    tier={k.casefold():v for k,v in config.get('journal_priority',{}).items()}.get(aliases.get(venue,venue),0)
    year=m.get('year');year=year if isinstance(year,int) and not isinstance(year,bool) else 0
    citations=m.get('citation_count',m.get('cited_by_count',0)) or 0
    citations=citations if isinstance(citations,(int,float)) else 0
    if not math.isfinite(citations):citations=0
    evidence={'basis':'metadata ranking; not a scientific novelty certification',
              'topic_terms':matches,'existing_verified_relevance':relevance,
              'journal_tier':tier,'year':year,'citations':citations}
    return (len(matches),relevance,tier,math.log1p(max(0,citations)),year),evidence


def _selection_papers(catalog):
    """Selection needs neither whole scientific cards nor discovery history."""
    with catalog.connect() as db:
        rows=[dict(row) for row in db.execute('''SELECT id,title,acquisition,asset_path,asset_hash,decision,card_path,
            json_object('abstract',json_extract(metadata,'$.abstract'),'venue',json_extract(metadata,'$.venue'),
                'year',json_extract(metadata,'$.year'),
                'citation_count',CASE WHEN json_type(metadata,'$.citation_count') IS NULL
                    THEN json_extract(metadata,'$.cited_by_count') ELSE json_extract(metadata,'$.citation_count') END,
                'identity_review_required',json_extract(metadata,'$.identity_review_required'),
                'version_review_required',json_extract(metadata,'$.version_review_required'),
                'out_of_scope',json_extract(metadata,'$.out_of_scope')) AS metadata,
            json_object('relevance',json_extract(assessment,'$.relevance'),
                'evidence_unverified',json_extract(assessment,'$.evidence_unverified')) AS assessment
            FROM papers WHERE acquisition='available' AND asset_path IS NOT NULL
            ORDER BY seed DESC,candidate_order,created''')]
    for row in rows:
        row['metadata']=json.loads(row['metadata']);row['assessment']=json.loads(row['assessment'])
    return rows


def select(catalog, config):
    install(catalog)
    library=Path(config['studio_library_root'])
    with catalog.connect() as db:
        human={r[0] for r in db.execute("SELECT DISTINCT paper_id FROM events WHERE kind='human_decision'")}
    available=[]
    for p in _selection_papers(catalog):
        m=p['metadata']
        if p['acquisition']!='available' or not p.get('asset_path') or not Path(p['asset_path']).is_file():continue
        from .web_card_inputs import valid_source_hash
        if not valid_source_hash(p.get('asset_hash')):
            catalog.selection_check(p['id'],'原文身份待修复：缺少有效SHA-256');continue
        if any(m.get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):continue
        if p['decision'] in ('reject','later'):continue
        available.append(p)
    # Existing/human cards contribute to the denominator, but are never rewritten.
    target=math.floor(len(available)*config.get('web_cards',{}).get('selection_fraction',.30)+.5)
    candidates=[]
    for p in available:
        if p['id'] in human or p['decision']!='unreviewed' or p.get('card_path') or (library/p['id']/'card.json').exists():continue
        score,evidence=ranking(p,config);candidates.append((score,p,evidence))
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Supplemental downloaded inventory and explicitly authorized reworks
        # do not consume the independent metadata selection quota.
        count=db.execute("SELECT count(*) FROM web_card_jobs WHERE coalesce(json_extract(selection,'$.selection_kind'),'selected') NOT IN ('downloaded_refill','manual_library') AND json_extract(selection,'$.rework') IS NULL").fetchone()[0]
        added=[];refilled=[]
        ranked=sorted(candidates,key=lambda row:(row[0],row[1]['id']),reverse=True)
        def enqueue(p,evidence,kind):
            from .web_card_inputs import digest
            try:
                if digest(p['asset_path'])!=p['asset_hash']:return False
            except (OSError,ValueError):return False
            proof={**evidence,'fraction':config.get('web_cards',{}).get('selection_fraction',.30),'eligible_downloaded':len(available),'target':target,'selection_kind':kind}
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',
                       (p['id'],p.get('asset_hash') or '',p['title'],json.dumps(proof,ensure_ascii=False),now()))
            added.append(p['id']);return True
        if config.get('manual_literature',{}).get('enabled'):
            manual = {r['paper_id']:r['source_hash'] for r in db.execute('SELECT * FROM manual_card_priority')}
            from .web_card_inputs import digest
            for _,p,evidence in ranked:
                if manual.get(p['id']) != p.get('asset_hash'):continue
                if db.execute('SELECT 1 FROM web_card_jobs WHERE paper_id=?',(p['id'],)).fetchone():continue
                if any((catalog.path.parent/'web_cards'/p['id']).rglob('attempt.json')):continue
                try:
                    if digest(p['asset_path']) != manual[p['id']]:continue
                except OSError:continue
                enqueue(p,evidence,'manual_library')
        for _,p,evidence in ranked:
            if count>=target:break
            if db.execute('SELECT 1 FROM web_card_jobs WHERE paper_id=?',(p['id'],)).fetchone():continue
            if any((catalog.path.parent/'web_cards'/p['id']).rglob('attempt.json')):continue
            if enqueue(p,evidence,'selected'):count+=1
        # Failed, unknown, finished and delayed jobs are not ready card stock.
        pending=db.execute("SELECT count(*) FROM web_card_jobs WHERE state='queued' AND retry_at<=?",(time.time(),)).fetchone()[0]
        minimum=max(0,int(config.get('web_cards',{}).get('refill_min_pending',0)))
        if pending<minimum:
            from .web_card_inputs import digest
            for _,p,evidence in ranked:
                if pending>=minimum:break
                if db.execute('SELECT 1 FROM web_card_jobs WHERE paper_id=?',(p['id'],)).fetchone():continue
                if any((catalog.path.parent/'web_cards'/p['id']).rglob('attempt.json')):continue
                try:
                    if not p.get('asset_hash') or digest(p['asset_path'])!=p['asset_hash']:continue
                except OSError:continue
                if enqueue(p,evidence,'downloaded_refill'):refilled.append(p['id']);pending+=1
    return {'available':len(available),'target':target,'selected':count,'added':added,'refilled':refilled,'ready_pending':pending,'refill_min_pending':minimum}


def jobs(catalog, config=None):
    install(catalog)
    with catalog.connect() as db:
        records=[dict(r) for r in db.execute('SELECT * FROM web_card_jobs ORDER BY updated')]
        if config is not None:
            from core.api import workflow_priority__sort as sort_articles
            records=sort_articles(db,records,config)
        return records


def claim(catalog,paper_id=None):
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        where=" AND paper_id=?" if paper_id is not None else ''
        args=(time.time(),paper_id) if paper_id is not None else (time.time(),)
        from core.api import workflow_priority__seed_first as seed_first
        candidates=seed_first(db,[dict(row) for row in db.execute("SELECT * FROM web_card_jobs WHERE state='queued' AND retry_at<=?"+where+" ORDER BY (json_extract(selection,'$.rework') IS NOT NULL) DESC,updated",args)])
        r=candidates[0] if candidates else None
        if not r:return None
        db.execute("UPDATE web_card_jobs SET state='preparing',error='',attempts=attempts+1,updated=? WHERE paper_id=?",(now(),r['paper_id']))
        return dict(r)


def update(catalog,pid,**values):
    allowed={'state','provider','folder','error','retry_at'}
    if not values.keys()<=allowed:raise ValueError('Invalid web queue fields')
    values['updated']=now()
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if 'state' in values:
            from core.api import control__transition_decision as transition_decision
            current=db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
            if current is None:raise ValueError('网页任务不存在')
            decision=transition_decision(current['state'],values['state'])
            if not decision.allowed:raise ValueError(decision.reason)
        db.execute('UPDATE web_card_jobs SET '+','.join(k+'=?' for k in values)+' WHERE paper_id=?',(*values.values(),pid))


def recover(catalog):
    """Crash recovery never queues a potentially sent request again."""
    install(catalog)
    with catalog.connect() as db:
        db.execute("UPDATE web_card_jobs SET state='needs_inspection',error='服务中断，保留原会话与材料记录；不自动重发',updated=? WHERE state IN ('preparing','submitting','submitted','collecting')",(now(),))
