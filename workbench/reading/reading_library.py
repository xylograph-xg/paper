"""Private reading progress/notes and a derived index of existing card summaries/scores."""
import hashlib
import json
import math
import threading
from core.api import paths__WorkspacePath as Path
from core.api import catalog__now as now

_score_lock=threading.Lock()
_CARD_INDEX_VERSION=4


class ReadingConflict(ValueError):
    pass


def install(catalog):
    with catalog.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS paper_reading_state(
          paper_id TEXT PRIMARY KEY REFERENCES papers(id),
          is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),read_at TEXT,
          note TEXT NOT NULL DEFAULT '',note_version INTEGER NOT NULL DEFAULT 0,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS paper_card_scores(
          paper_id TEXT PRIMARY KEY REFERENCES papers(id),card_path TEXT NOT NULL,
          source_hash TEXT NOT NULL,stat_key TEXT NOT NULL,card_sha256 TEXT NOT NULL,
          overall_quality REAL,direction_novelty REAL,key_findings TEXT,work_summary TEXT,updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS reading_status ON paper_reading_state(is_read,paper_id);
        """)
        db.execute('BEGIN IMMEDIATE')
        columns={row['name'] for row in db.execute('PRAGMA table_info(paper_card_scores)')}
        for name in ('key_findings','work_summary'):
            if name not in columns:db.execute(f'ALTER TABLE paper_card_scores ADD COLUMN {name} TEXT')
        tables=['paper_reading_state','paper_card_scores']
        for table in ('card_review_jobs','card_correction_jobs'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():tables.append(table)
        for table in tables:
            for operation in ('INSERT','UPDATE','DELETE'):
                db.execute(f'CREATE TRIGGER IF NOT EXISTS revision_{table}_{operation.lower()} AFTER {operation} ON {table} '
                           'BEGIN UPDATE catalog_revision SET value=value+1 WHERE id=1; END')


def reading(catalog,pid):
    with catalog.connect() as db:
        if not db.execute('SELECT 1 FROM papers WHERE id=?',(pid,)).fetchone():raise KeyError('论文不存在')
        row=db.execute('SELECT * FROM paper_reading_state WHERE paper_id=?',(pid,)).fetchone()
    result=dict(row) if row else {'paper_id':pid,'is_read':False,'read_at':None,'note':'','note_version':0,'updated':None}
    result['is_read']=bool(result['is_read']);return result


def update(catalog,pid,patch):
    if not isinstance(patch,dict) or not set(patch)<={'is_read','note','note_version'} or not {'is_read','note'}&patch.keys():
        raise ValueError('请提交已读状态或备注')
    if 'is_read' in patch and type(patch['is_read']) is not bool:raise ValueError('已读状态必须为布尔值')
    if 'note' in patch:
        if not isinstance(patch['note'],str) or len(patch['note'])>20000:raise ValueError('备注须为文本，最多20000字')
        if type(patch.get('note_version')) is not int or patch['note_version']<0:raise ValueError('保存备注需要当前版本')
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM papers WHERE id=?',(pid,)).fetchone():raise KeyError('论文不存在')
        row=db.execute('SELECT * FROM paper_reading_state WHERE paper_id=?',(pid,)).fetchone()
        current=dict(row) if row else {'is_read':0,'read_at':None,'note':'','note_version':0}
        if 'note' in patch and patch['note_version']!=current['note_version']:
            raise ReadingConflict('另一窗口已修改备注；当前草稿已保留，请重新打开备注核对后保存。')
        changes={};stamp=now()
        if 'is_read' in patch and bool(current['is_read'])!=patch['is_read']:
            changes.update(is_read=int(patch['is_read']),read_at=stamp if patch['is_read'] else None)
        if 'note' in patch and current['note']!=patch['note']:
            changes.update(note=patch['note'],note_version=current['note_version']+1)
        if changes:
            value={**current,**changes}
            db.execute('INSERT INTO paper_reading_state VALUES(?,?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET '
                       'is_read=excluded.is_read,read_at=excluded.read_at,note=excluded.note,note_version=excluded.note_version,updated=excluded.updated',
                       (pid,value['is_read'],value['read_at'],value['note'],value['note_version'],stamp))
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',
                       (pid,'human_reading_update',json.dumps({'fields':sorted(changes),'note_version':value['note_version']}),stamp))
    return reading(catalog,pid)


def _score(evaluation,key,version=None):
    item=evaluation.get(key)
    if not isinstance(item,dict):return None
    score=item.get('score');pages=item.get('source_pages')
    if type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=100:return None
    if not isinstance(item.get('reason'),str) or not item['reason'].strip():return None
    if not isinstance(pages,list) or not pages or any(type(p) is not int or p<1 for p in pages):return None
    from cards.api import paper_quality__VERSION as VERSION, paper_quality__validate as validate
    if key=='overall_quality' and version==VERSION:
        try:validate(item)
        except ValueError:return None
    return float(score)


def refresh_scores(catalog):
    # Read JSON outside a write transaction; compare Catalog identity before indexing it.
    with _score_lock:
        with catalog.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT id,card_path,asset_hash FROM papers WHERE card_path IS NOT NULL')]
            cached={r['paper_id']:dict(r) for r in db.execute('SELECT * FROM paper_card_scores')}
        pending=[]
        for row in rows:
            path=Path(row['card_path']);source_hash=row['asset_hash'] or ''
            try:
                stat=path.stat();key=json.dumps([_CARD_INDEX_VERSION,stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns])
            except OSError:key=f'unavailable:{_CARD_INDEX_VERSION}'
            old=cached.get(row['id'])
            if old and (old['card_path'],old['source_hash'],old['stat_key'])==(str(path),source_hash,key):continue
            quality=novelty=findings=summary=None;fingerprint=''
            try:
                raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest();card=json.loads(raw)
                evaluation=card.get('paper_evaluation');meta=card.get('meta',{})
                if isinstance(evaluation,dict) and isinstance(meta,dict) and not (meta.get('source_original_sha256') and meta['source_original_sha256']!=source_hash):
                    quality=_score(evaluation,'overall_quality',meta.get('paper_evaluation_version'));novelty=_score(evaluation,'direction_novelty')
                if isinstance(meta,dict) and source_hash and meta.get('source_original_sha256')==source_hash:
                    value=card.get('key_findings')
                    if isinstance(value,str) and value.strip():findings=value
                    value=card.get('one_line_summary')
                    if isinstance(value,str) and value.strip():summary=value
                after=path.stat()
                if key!=json.dumps([_CARD_INDEX_VERSION,after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns]):
                    quality=novelty=findings=summary=None;fingerprint='';key='changing'
            except (OSError,ValueError,TypeError,AttributeError):quality=novelty=findings=summary=None
            pending.append((row['id'],str(path),source_hash,key,fingerprint,quality,novelty,findings,summary,now()))
        removed=set(cached)-{row['id'] for row in rows}
        if pending or removed:
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                for values in pending:
                    current=db.execute('SELECT card_path,coalesce(asset_hash,\'\') source_hash FROM papers WHERE id=?',(values[0],)).fetchone()
                    if not current or (current['card_path'],current['source_hash'])!=(values[1],values[2]):continue
                    db.execute('INSERT INTO paper_card_scores(paper_id,card_path,source_hash,stat_key,card_sha256,overall_quality,direction_novelty,key_findings,work_summary,updated) '
                               'VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET '
                               'card_path=excluded.card_path,source_hash=excluded.source_hash,stat_key=excluded.stat_key,card_sha256=excluded.card_sha256,'
                               'overall_quality=excluded.overall_quality,direction_novelty=excluded.direction_novelty,key_findings=excluded.key_findings,work_summary=excluded.work_summary,updated=excluded.updated',values)
                db.execute('DELETE FROM paper_card_scores WHERE NOT EXISTS(SELECT 1 FROM papers WHERE papers.id=paper_id AND papers.card_path IS NOT NULL)')
