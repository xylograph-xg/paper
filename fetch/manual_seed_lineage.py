"""Evidence-backed manual seed ancestry, independent of cards and reading notes."""
import json
import time


def install(catalog):
    with catalog.connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS manual_seed_roots(
              paper_id TEXT PRIMARY KEY REFERENCES papers(id),source_path TEXT NOT NULL,
              input_hash TEXT NOT NULL,registered REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS seed_discovery_origins(
              paper_id TEXT NOT NULL REFERENCES papers(id),seed_doi TEXT NOT NULL,
              basis TEXT NOT NULL,registered REAL NOT NULL,PRIMARY KEY(paper_id,seed_doi));
            CREATE TABLE IF NOT EXISTS manual_seed_lineage(
              paper_id TEXT NOT NULL REFERENCES papers(id),root_id TEXT NOT NULL REFERENCES papers(id),
              registered REAL NOT NULL,PRIMARY KEY(paper_id,root_id));
            CREATE INDEX IF NOT EXISTS origin_seed_doi ON seed_discovery_origins(seed_doi);
            CREATE INDEX IF NOT EXISTS discovery_reason_lookup ON discoveries(reason);
        ''')
        for table in ('manual_seed_roots','seed_discovery_origins','manual_seed_lineage'):
            for action in ('INSERT','UPDATE','DELETE'):
                db.execute(f'CREATE TRIGGER IF NOT EXISTS revision_{table}_{action.lower()} AFTER {action} ON {table} '
                           'BEGIN UPDATE catalog_revision SET value=value+1 WHERE id=1; END')


def register_root(catalog, paper, path, digest):
    if paper['metadata'].get('is_correction'):
        raise ValueError('勘误保留关联，不作为独立检索种子')
    if paper['metadata'].get('user_seed_disabled') or paper['decision']=='reject':
        raise ValueError('用户移除种子或人工忽略仍受保护')
    if not paper['seed']:
        catalog.upsert({'title':paper['title'],'doi':paper['metadata'].get('doi')}, seed=True,
                       reason='用户手动文献库种子')
    with catalog.connect() as db:
        db.execute('INSERT OR IGNORE INTO manual_seed_roots VALUES(?,?,?,?)',
                   (paper['id'],str(path),digest,time.time()))
        row=db.execute('SELECT metadata FROM papers WHERE id=?',(paper['id'],)).fetchone()
        data=json.loads(row[0]) if row and row[0] else {}
        if not data.get('manual_seed_fast_lane'):
            data['manual_seed_fast_lane']=True
            db.execute('UPDATE papers SET metadata=? WHERE id=?',(json.dumps(data,ensure_ascii=False),paper['id']))


def record_origin(db, pid, record, reason=''):
    """Called inside Catalog's identity transaction; no guessed relations."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='seed_discovery_origins'").fetchone():return
    from core.api import catalog__doi as doi
    origins = record.get('discovered_from_seed_dois') or []
    if not isinstance(origins,list) or any(not isinstance(v,str) for v in origins):return
    parents = {doi(value):'live_seed_doi' for value in origins if doi(value)}
    saved_reasons = record.get('discovery_reasons') or []
    reasons = [reason]+(saved_reasons if isinstance(saved_reasons,list) else [])
    for text in reasons:
        if not isinstance(text,str):continue
        for prefix in ('参考文献：','引用种子：'):
            if text.startswith(prefix):
                title = text[len(prefix):]
                rows = list(db.execute("SELECT p.id,i.value FROM papers p JOIN identifiers i "
                    "ON i.paper_id=p.id AND i.kind='doi' WHERE p.title=?",(title,)))
                if len(rows)==1:parents[rows[0]['value']]='legacy_exact_seed_title'
    own = {row[0] for row in db.execute("SELECT value FROM identifiers WHERE paper_id=? AND kind='doi'",(pid,))}
    for parent,basis in parents.items():
        if parent not in own:
            db.execute('INSERT OR IGNORE INTO seed_discovery_origins VALUES(?,?,?,?)',
                       (pid,parent,basis,time.time()))


def reconcile(catalog):
    """Load the evidence graph once; never issue one full identity scan per node."""
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        roots = [row[0] for row in db.execute('SELECT paper_id FROM manual_seed_roots')]
        if not roots:
            db.execute('DELETE FROM manual_seed_lineage')
            return {'manual_seeds':0,'derived':0}
        identifiers = {}; own = {}; titles = {}
        for row in db.execute("SELECT p.id,p.title,i.value FROM papers p JOIN identifiers i "
                              "ON i.paper_id=p.id AND i.kind='doi'"):
            identifiers.setdefault(row['value'],set()).add(row['id'])
            own.setdefault(row['id'],set()).add(row['value'])
            titles.setdefault(row['title'],[]).append(row['value'])
        origins = {(r['paper_id'],r['seed_doi']) for r in db.execute('SELECT * FROM seed_discovery_origins')}
        legacy = []
        for row in db.execute("SELECT paper_id,reason FROM discoveries WHERE reason LIKE '参考文献：%' OR reason LIKE '引用种子：%'"):
            title = row['reason'].split('：',1)[1]
            parents = titles.get(title,[])
            if len(parents)==1 and parents[0] not in own.get(row['paper_id'],set()):
                key=(row['paper_id'],parents[0])
                if key not in origins:
                    origins.add(key);legacy.append((*key,'legacy_exact_seed_title',time.time()))
        db.executemany('INSERT OR IGNORE INTO seed_discovery_origins VALUES(?,?,?,?)',legacy)
        children = {}
        for child,parent_doi in origins:
            for parent in identifiers.get(parent_doi,()):children.setdefault(parent,set()).add(child)
        rows = []
        for root in roots:
            frontier = [root]; visited = {root}
            while frontier:
                for child in children.get(frontier.pop(),()):
                    if child in visited:continue
                    visited.add(child);frontier.append(child)
                    rows.append((child,root,time.time()))
        expected = {(child, root) for child, root, _ in rows}
        stale = [(r[0], r[1]) for r in db.execute('SELECT paper_id,root_id FROM manual_seed_lineage')
                 if (r[0], r[1]) not in expected]
        db.executemany('DELETE FROM manual_seed_lineage WHERE paper_id=? AND root_id=?', stale)
        db.executemany('INSERT OR IGNORE INTO manual_seed_lineage VALUES(?,?,?)',rows)
        return {'manual_seeds':len(roots),'derived':db.execute('SELECT count(DISTINCT paper_id) FROM manual_seed_lineage '
            'WHERE paper_id NOT IN (SELECT paper_id FROM manual_seed_roots)').fetchone()[0]}


def library_condition(db, group):
    has_roots = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='manual_seed_roots'").fetchone())
    has_lineage = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='manual_seed_lineage'").fetchone())
    root = 'EXISTS(SELECT 1 FROM manual_seed_roots mr WHERE mr.paper_id=papers.id)' if has_roots else '0'
    derived = 'EXISTS(SELECT 1 FROM manual_seed_lineage ml WHERE ml.paper_id=papers.id)' if has_lineage else '0'
    return {'deep_regular':f'NOT ({root}) AND NOT ({derived})',
            'deep_manual_seeds':root,'deep_manual_derived':f'({derived}) AND NOT ({root})'}[group]
