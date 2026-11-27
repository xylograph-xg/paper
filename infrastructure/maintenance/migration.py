"""Read-only legacy intake. Preserve complete exploration snapshots and ID aliases."""
from contextlib import closing
import hashlib
import json
import sqlite3
from core.api import paths__WorkspacePath as Path

from core.api import catalog__ROOT as ROOT, catalog__doi as doi
from core.api import services__atomic_json as atomic_json


def migrate(catalog,config):
    summary={'legacy_cards':0,'exploration_papers':0,'crawler_papers':0,'warnings':[]}
    mapping=[]
    for path in sorted((ROOT/'read/app/workspace').glob('*/card.json')):
        try:
            c=json.loads(path.read_text());info=c.get('info') or {}
            record={'title':c.get('title') or path.parent.name,'doi':doi(info.get('DOI','')),'venue':info.get('期刊','')}
            source=path.parent/'source.pdf'
            digest=hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None
            matching=next((p for p in catalog.list() if digest and p['metadata'].get('input_sha256')==digest),None)
            pid=matching['id'] if matching else catalog.upsert(record,'旧 read 阅读卡片')
            if not catalog.get(pid)['card_path']:
                catalog.update(pid,card_path=str(path.resolve()))
            if source.exists() and catalog.get(pid)['card_path']==str(path.resolve()):
                # Old Studio card libraries already have an active local original.
                # Keep that link even if a queued seed import also archived a copy.
                catalog.update(pid,asset_path=str(source.resolve()),asset_hash=digest,acquisition='available')
            mapping.append({'source':str(path),'paper_id':pid});summary['legacy_cards']+=1
        except Exception as exc:
            summary['warnings'].append(str(path)+': '+str(exc))
    path=ROOT/'article/data/exploration/exploration.sqlite3'
    if path.exists():
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            available={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            snapshot={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] if name in available else [] for name in ('sessions','rounds','nodes','events')}
            missing=set(snapshot)-available
            if missing:summary['warnings'].append('article 缺少历史表：'+','.join(sorted(missing)))
            atomic_json(Path(config['catalog_path']).parent/'legacy/exploration.json',snapshot)
            selected={n['paper_id'] for n in snapshot['nodes'] if n.get('active') and n.get('paper_id')}
            for round in snapshot['rounds']:
                for record in json.loads(round['papers']):
                    try:
                        old_id=record.get('paper_id');pid=catalog.upsert(record,'旧 article 探索轮次：'+round['id'])
                        with catalog.connect() as target:
                            prior=target.execute('SELECT paper_id FROM identifiers WHERE kind=? AND value=?',('article',old_id)).fetchone()
                            if prior and prior[0]!=pid:raise ValueError('article历史ID映射冲突；拒绝覆盖')
                            target.execute('INSERT OR IGNORE INTO identifiers VALUES(?,?,?)',('article',old_id,pid))
                        if old_id in selected and catalog.get(pid)['decision']=='unreviewed':
                            catalog.decide(pid,'keep')
                        mapping.append({'source':'article','old_id':old_id,'paper_id':pid,'round_id':round['id']})
                        summary['exploration_papers']+=1
                    except Exception as exc:
                        summary['warnings'].append('article: '+str(exc))
    path=ROOT/'crawler/literature_explorer/data/literature.db'
    if path.exists():
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            available={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            feedback={r['paper_id']:r['decision'] for r in db.execute('SELECT * FROM user_feedback')} if 'user_feedback' in available else {}
            if 'papers' not in available:
                summary['warnings'].append('crawler 缺少 papers 表；原库保留')
                atomic_json(Path(config['catalog_path']).parent/'legacy/id_map.json',mapping)
                return summary
            for row in db.execute('SELECT * FROM papers'):
                try:
                    record=dict(row);pid=catalog.upsert(record,'旧 crawler 文献记录')
                    with catalog.connect() as target:
                        prior=target.execute('SELECT paper_id FROM identifiers WHERE kind=? AND value=?',('crawler',record['paper_id'])).fetchone()
                        if prior and prior[0]!=pid:raise ValueError('crawler历史ID映射冲突；拒绝覆盖')
                        target.execute('INSERT OR IGNORE INTO identifiers VALUES(?,?,?)',('crawler',record['paper_id'],pid))
                    decision={'interesting':'keep','reject':'reject','later':'later'}.get(feedback.get(record['paper_id']))
                    if decision and catalog.get(pid)['decision']=='unreviewed':
                        catalog.decide(pid,decision)
                    mapping.append({'source':'crawler','old_id':record['paper_id'],'paper_id':pid})
                    summary['crawler_papers']+=1
                except Exception as exc:
                    summary['warnings'].append('crawler: '+str(exc))
    atomic_json(Path(config['catalog_path']).parent/'legacy/id_map.json',mapping)
    return summary
