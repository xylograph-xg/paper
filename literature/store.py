"""Controlled vocabulary, immutable evidence and topic-specific reading plans."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3
import unicodedata
import uuid

DIMENSIONS = ('topic', 'object', 'question', 'mechanism', 'method', 'application', 'learning')
ROLES = ('intro', 'foundation', 'method', 'progress', 'debate')


class Conflict(ValueError):
    """Stale version or ambiguous vocabulary; reload before editing."""


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def text(value, field, maximum=20000, optional=False):
    if not isinstance(value, str) or len(value) > maximum or (not optional and not value.strip()):
        raise ValueError(f'{field}须为{maximum}字以内的文本')
    return value.strip()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def check_version(row, version):
    if type(version) is not int or row['version'] != version:
        raise Conflict('记录已更新，请刷新后重试')


def rules(value):
    if not isinstance(value, dict) or set(value) - {'q', 'tags', 'year_from', 'year_to', 'has_pdf', 'state'}:
        raise ValueError('筛选条件不合法')
    result = dict(value)
    if 'q' in result: result['q'] = text(result['q'], '检索词', 500, True)
    tags = result.get('tags', {})
    if not isinstance(tags, dict) or set(tags) - set(DIMENSIONS):
        raise ValueError('标签筛选维度不合法')
    for ids in tags.values():
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(t, str) or not t for t in ids):
            raise ValueError('标签筛选须为ID数组')
    for key in ('year_from', 'year_to'):
        if key in result and (type(result[key]) is not int or not 1000 <= result[key] <= 3000):
            raise ValueError('年份不合法')
    if result.get('year_from', 1000) > result.get('year_to', 3000): raise ValueError('年份区间倒置')
    if 'has_pdf' in result and type(result['has_pdf']) is not bool: raise ValueError('原文筛选须为布尔值')
    if result.get('state', 'all') not in ('all', 'candidate', 'confirmed', 'automatic'): raise ValueError('标签状态不合法')
    return result


class Store:
    """SQLite sidecar. Every mutation is atomic; evidence/events are append-only."""

    def __init__(self, path):
        self.path = Path(path)
        # A diagnostic caller must not initialize sidecar tables in the primary DB.
        # Inspect existing databases read-only before mkdir, migrations or BEGIN.
        if self.path.is_file():
            probe = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                if probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='papers'").fetchone():
                    raise ValueError('Literature sidecar must not use the primary Catalog database')
            finally:
                probe.close()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(write=True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS vocabulary(
                  id TEXT PRIMARY KEY, dimension TEXT NOT NULL, name_zh TEXT NOT NULL,
                  name_en TEXT NOT NULL, parent_id TEXT REFERENCES vocabulary(id),
                  status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS aliases(
                  dimension TEXT NOT NULL, normalized TEXT NOT NULL, label TEXT NOT NULL,
                  tag_id TEXT NOT NULL REFERENCES vocabulary(id), PRIMARY KEY(dimension,normalized));
                CREATE TABLE IF NOT EXISTS evidence(
                  id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, tag_id TEXT NOT NULL REFERENCES vocabulary(id),
                  quote TEXT NOT NULL, scope TEXT NOT NULL, page INTEGER, relation TEXT NOT NULL,
                  input_fingerprint TEXT NOT NULL, generator_version TEXT NOT NULL,
                  origin TEXT NOT NULL, created TEXT NOT NULL, locator TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS evidence_paper ON evidence(paper_id,tag_id);
                CREATE TABLE IF NOT EXISTS decisions(
                  paper_id TEXT NOT NULL, tag_id TEXT NOT NULL REFERENCES vocabulary(id),
                  state TEXT NOT NULL, actor TEXT NOT NULL, version INTEGER NOT NULL,
                  PRIMARY KEY(paper_id,tag_id));
                CREATE TABLE IF NOT EXISTS events(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collections(
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL, questions TEXT NOT NULL,
                  rules TEXT NOT NULL, note TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS members(
                  collection_id TEXT NOT NULL REFERENCES collections(id), paper_id TEXT NOT NULL,
                  mode TEXT NOT NULL, role TEXT NOT NULL, position INTEGER NOT NULL,
                  progress TEXT NOT NULL, note TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                  PRIMARY KEY(collection_id,paper_id));
                CREATE TABLE IF NOT EXISTS automatic_runs(
                  id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
                  metadata_fingerprint TEXT NOT NULL, source_fingerprint TEXT,
                  rule_version TEXT NOT NULL, result TEXT NOT NULL, created TEXT NOT NULL,
                  UNIQUE(paper_id,input_fingerprint,rule_version));
                CREATE TABLE IF NOT EXISTS automatic_heads(
                  paper_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES automatic_runs(id));
                CREATE TABLE IF NOT EXISTS automatic_inputs(
                  run_id TEXT PRIMARY KEY REFERENCES automatic_runs(id), document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS level1_heads(
                  paper_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES automatic_runs(id));
                CREATE TABLE IF NOT EXISTS level2_heads(
                  paper_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES automatic_runs(id));
                CREATE TABLE IF NOT EXISTS level2_checks(
                  paper_id TEXT PRIMARY KEY, signature TEXT NOT NULL, state TEXT NOT NULL,
                  core_count INTEGER NOT NULL, reason TEXT NOT NULL, retry_at REAL NOT NULL,
                  updated TEXT NOT NULL);
            ''')
            if 'locator' not in {r[1] for r in db.execute('PRAGMA table_info(evidence)')}:
                db.execute("ALTER TABLE evidence ADD COLUMN locator TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            with db: yield db
        finally:
            db.close()

    def _event(self, db, kind, payload):
        db.execute('INSERT INTO events(kind,payload,created) VALUES(?,?,?)', (kind, encode(payload), stamp()))

    def tags(self, query='', dimension=''):
        if dimension and dimension not in DIMENSIONS: raise ValueError('维度不合法')
        q = normalize(text(query, '检索词', 500, True))
        with self.connect() as db:
            result = []
            for row in db.execute('SELECT * FROM vocabulary ORDER BY dimension,name_zh,id'):
                item = dict(row)
                item['aliases'] = [r[0] for r in db.execute('SELECT label FROM aliases WHERE tag_id=? ORDER BY normalized', (row['id'],))]
                if (not dimension or row['dimension'] == dimension) and (not q or any(q in normalize(a) for a in item['aliases'])):
                    result.append(item)
            return result

    def save_tag(self, *, dimension, name_zh, name_en='', aliases=None, parent_id=None,
                 status='confirmed', id=None, expected_version=None):
        if dimension not in DIMENSIONS or status not in ('candidate', 'confirmed', 'rejected'):
            raise ValueError('维度或词表状态不合法')
        zh = text(name_zh, '中文名', 120)
        en = text(name_en, '英文名', 200, True)
        if not isinstance(aliases or [], list) or len(aliases or []) > 100: raise ValueError('别名须为数组且不超过100个')
        labels = {normalize(a): a for a in [zh, en, *(text(a, '别名', 200) for a in (aliases or []))] if a}
        tid = id or str(uuid.uuid4())
        with self.connect(True) as db:
            old = db.execute('SELECT * FROM vocabulary WHERE id=?', (tid,)).fetchone()
            if id and not old: raise KeyError('标签不存在')
            if old:
                check_version(old, expected_version)
                if dimension != old['dimension']: raise ValueError('已创建标签不可更换维度')
            # Check every ancestor and every descendant after a parent change.
            tree = {r['id']: dict(r) for r in db.execute('SELECT * FROM vocabulary')}
            tree[tid] = {'parent_id': parent_id, 'dimension': dimension}
            for start in tree:
                seen = set(); current = start
                while current:
                    if current in seen or len(seen) >= 3: raise ValueError('标签层级须为1–3层且不能循环')
                    seen.add(current)
                    if current not in tree or tree[current]['dimension'] != tree[start]['dimension']:
                        raise ValueError('父标签不存在或维度不同')
                    current = tree[current]['parent_id']
            for alias in labels:
                hit = db.execute('SELECT tag_id FROM aliases WHERE dimension=? AND normalized=?', (dimension, alias)).fetchone()
                if hit and hit[0] != tid: raise Conflict('同维度已有该名称或别名，请复用原标签')
            version = old['version'] + 1 if old else 1
            db.execute('INSERT OR REPLACE INTO vocabulary VALUES(?,?,?,?,?,?,?)', (tid, dimension, zh, en, parent_id, status, version))
            db.execute('DELETE FROM aliases WHERE tag_id=?', (tid,))
            db.executemany('INSERT INTO aliases VALUES(?,?,?,?)', [(dimension, key, label, tid) for key, label in labels.items()])
            self._event(db, 'tag_saved', {'before': dict(old) if old else None, 'id': tid, 'labels': labels, 'version': version, 'status': status, 'parent_id': parent_id})
        return next(t for t in self.tags() if t['id'] == tid)

    def resolve(self, term, dimension):
        with self.connect() as db:
            row = db.execute('SELECT tag_id FROM aliases WHERE dimension=? AND normalized=?', (dimension, normalize(term))).fetchone()
            return row[0] if row else None

    def annotate(self, records):
        """Atomic batch, max 100. Automatic evidence never changes a human decision."""
        if not isinstance(records, list) or not 1 <= len(records) <= 100: raise ValueError('每批须为1–100条')
        output = []
        with self.connect(True) as db:
            for raw in records:
                if not isinstance(raw, dict): raise ValueError('标注须为对象')
                allowed = {'paper_id', 'tag_id', 'quote', 'scope', 'page', 'relation', 'input_fingerprint', 'generator_version', 'origin', 'state', 'expected_version', 'locator'}
                if set(raw) - allowed: raise ValueError('标注包含未知字段')
                r = {k: raw.get(k) for k in ('paper_id', 'tag_id', 'quote', 'scope', 'page', 'relation', 'input_fingerprint', 'generator_version', 'origin')}
                for field in ('paper_id', 'tag_id', 'quote', 'input_fingerprint', 'generator_version'):
                    r[field] = text(r[field], field, 20000 if field == 'quote' else 200)
                if r['scope'] not in ('title', 'abstract', 'keywords', 'fulltext', 'manual'): raise ValueError('证据来源范围不合法')
                if r['relation'] not in ('about', 'used', 'mentioned'): raise ValueError('标签关系不合法')
                if r['origin'] not in ('manual', 'automatic'): raise ValueError('标注来源不合法')
                if r['origin']=='manual':raise ValueError('已禁止新增人工标签；历史决定仅保留读取')
                locator = raw.get('locator', {})
                if not isinstance(locator, dict) or set(locator) - {'entity','table','figure','conditions'}:
                    raise ValueError('证据定位仅允许材料名、表号、图号、实验条件')
                r['locator'] = {k: text(v, '证据定位', 2000) for k, v in locator.items()}
                if locator and r['scope'] not in ('fulltext','manual'): raise ValueError('图表与实验条件定位仅用于原文或人工判断')
                if r['page'] is not None and (type(r['page']) is not int or r['page'] < 1 or r['scope'] != 'fulltext'):
                    raise ValueError('PDF页码仅用于原文证据，须从1起')
                tag = db.execute('SELECT * FROM vocabulary WHERE id=?', (r['tag_id'],)).fetchone()
                if not tag or tag['status'] == 'rejected': raise ValueError('标签不存在或已弃用')
                state = raw.get('state', 'confirmed' if r['origin'] == 'manual' else 'candidate')
                if state not in ('candidate', 'confirmed', 'rejected') or (r['origin'] == 'automatic' and state != 'candidate'):
                    raise ValueError('自动标注只能保存待确认候选')
                previous = db.execute('SELECT * FROM decisions WHERE paper_id=? AND tag_id=?', (r['paper_id'], r['tag_id'])).fetchone()
                if r['origin'] == 'manual':
                    if previous: check_version(previous, raw.get('expected_version'))
                    elif raw.get('expected_version', 0) != 0: raise Conflict('标注已变化')
                eid = fingerprint(r)
                inserted = db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                           (eid, r['paper_id'], r['tag_id'], r['quote'], r['scope'], r['page'], r['relation'], r['input_fingerprint'], r['generator_version'], r['origin'], stamp(), encode(r['locator']))).rowcount
                protected = bool(previous and previous['actor'] == 'manual' and r['origin'] == 'automatic')
                if not protected and (inserted or not previous or r['origin']=='manual'):
                    version = previous['version'] + 1 if previous else 1
                    db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?)', (r['paper_id'], r['tag_id'], state, r['origin'], version))
                    self._event(db, 'annotation_decision', {'before': dict(previous) if previous else None, 'paper_id': r['paper_id'], 'tag_id': r['tag_id'], 'state': state, 'actor': r['origin'], 'version': version, 'evidence_id': eid})
                output.append({'evidence_id': eid, 'manual_protected': protected})
        return output

    def save_automatic_run(self, document, result, *, scope='both'):
        if scope not in ('both', 'level1', 'level2'): raise ValueError('标注范围不合法')
        if scope == 'level1' and (document.get('chunks') or result.get('level2') or any(
                label['level'] != 1 for key in ('supporting_labels', 'inherited_labels') for label in result.get(key, []))):
            raise ValueError('一级入口禁止原文和二级标签')
        if scope == 'level2' and (result.get('level1') or any(
                label['level'] != 2 for key in ('supporting_labels', 'inherited_labels', 'mentions') for label in result.get(key, []))):
            raise ValueError('二级入口禁止写入一级标签')
        """Immutable local-rule result. A repeat input restores its head idempotently."""
        from .classifier import validate_evidence
        validate_evidence(document,result)
        if result['input_fingerprint']!=fingerprint(document):raise ValueError('自动标注输入指纹不一致')
        value=json.loads(encode(result))
        for label in value['level1']+value['level2']+value.get('supporting_labels',[])+value.get('inherited_labels',[]):
            tag=self.resolve(label['name'],label['dimension'])
            if not tag:
                try:tag=self.save_tag(dimension=label['dimension'],name_zh=label['name'],name_en=label['id'],status='confirmed')['id']
                except Conflict:tag=self.resolve(label['name'],label['dimension'])
            if not tag:raise Conflict('自动词表归一失败，保留原词表')
            label['tag_id']=tag
        run_id=fingerprint({'paper_id':value['paper_id'],'input':value['input_fingerprint'],'rules':value['rule_version']})
        with self.connect(True) as db:
            db.execute('INSERT OR IGNORE INTO automatic_runs VALUES(?,?,?,?,?,?,?,?)',
                (run_id,value['paper_id'],value['input_fingerprint'],value['metadata_fingerprint'],value['source_fingerprint'],value['rule_version'],encode(value),stamp()))
            db.execute('INSERT OR IGNORE INTO automatic_inputs VALUES(?,?)',(run_id,encode(document)))
            heads = scope + '_heads' if scope != 'both' else 'automatic_heads'
            db.execute(f'INSERT INTO {heads} VALUES(?,?) ON CONFLICT(paper_id) DO UPDATE SET run_id=excluded.run_id',(value['paper_id'],run_id))
            saved=json.loads(db.execute('SELECT result FROM automatic_runs WHERE id=?',(run_id,)).fetchone()[0])
        return {**saved,'run_id':run_id}

    def automatic_results(self, paper_id=None, *, scope='both'):
        if scope not in ('both', 'level1', 'level2'): raise ValueError('标注范围不合法')
        heads = scope + '_heads' if scope != 'both' else 'automatic_heads'
        with self.connect() as db:
            rows=db.execute(f'SELECT r.id,r.result FROM {heads} h JOIN automatic_runs r ON r.id=h.run_id'+(' WHERE h.paper_id=?' if paper_id else ''),(paper_id,) if paper_id else ())
            return [{**json.loads(r['result']),'run_id':r['id']} for r in rows]

    def automatic_input(self, paper_id, *, scope='both'):
        if scope not in ('both', 'level1', 'level2'): raise ValueError('标注范围不合法')
        heads = scope + '_heads' if scope != 'both' else 'automatic_heads'
        with self.connect() as db:
            row=db.execute(f'SELECT i.document FROM {heads} h JOIN automatic_inputs i ON i.run_id=h.run_id WHERE h.paper_id=?',(paper_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def annotations(self, paper_id=None):
        with self.connect() as db:
            result = [dict(r) for r in db.execute('''SELECT d.*,v.dimension,v.name_zh,v.name_en,v.status vocabulary_status
                FROM decisions d JOIN vocabulary v ON v.id=d.tag_id''' + (' WHERE paper_id=?' if paper_id else ''), (paper_id,) if paper_id else ())]
            if paper_id:
                for row in result:
                    row['evidence'] = [dict(r) for r in db.execute('SELECT * FROM evidence WHERE paper_id=? AND tag_id=? ORDER BY created,id', (paper_id, row['tag_id']))]
                    for evidence in row['evidence']: evidence['locator'] = json.loads(evidence['locator'])
            return result

    def collections(self):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM collections ORDER BY name,id')]
        for row in rows:
            row['rules'] = json.loads(row['rules']); row['questions'] = json.loads(row['questions'])
        return rows

    def save_collection(self, *, name, goal='', questions=None, filters=None, note='', id=None, expected_version=None):
        name = text(name, '集合名称', 200); goal = text(goal, '学习目标', optional=True)
        note = text(note, '笔记', optional=True)
        if not isinstance(questions or [], list) or len(questions or []) > 100: raise ValueError('问题须为数组且不超过100个')
        qs = [text(q, '学习问题', 1000) for q in (questions or [])]
        filters = rules(filters or {})
        self.validate_filter_tags(filters)
        cid = id or str(uuid.uuid4())
        with self.connect(True) as db:
            old = db.execute('SELECT * FROM collections WHERE id=?', (cid,)).fetchone()
            if id and not old: raise KeyError('集合不存在')
            if old: check_version(old, expected_version)
            db.execute('INSERT OR REPLACE INTO collections VALUES(?,?,?,?,?,?,?)', (cid, name, goal, encode(qs), encode(filters), note, old['version']+1 if old else 1))
            self._event(db, 'collection_saved', {'id': cid, 'before': dict(old) if old else None, 'name': name, 'goal': goal, 'questions': qs, 'rules': filters, 'note': note})
        return next(c for c in self.collections() if c['id'] == cid)

    def validate_filter_tags(self, filters):
        tags = {t['id']: t for t in self.tags()}
        for dimension, ids in filters.get('tags', {}).items():
            if any(t not in tags or tags[t]['dimension'] != dimension for t in ids): raise ValueError('筛选标签不存在或维度不匹配')

    def save_member(self, *, collection_id, paper_id, mode='include', role='foundation', position=0,
                    progress='unread', note='', expected_version=0):
        if mode not in ('include', 'exclude', 'auto') or role not in ROLES or progress not in ('unread', 'reading', 'done'):
            raise ValueError('集合角色、加入方式或进度不合法')
        if type(position) is not int or not 0 <= position <= 100000: raise ValueError('顺序须为0–100000整数')
        note = text(note, '集合笔记', optional=True); paper_id = text(paper_id, '文献ID', 200)
        with self.connect(True) as db:
            if not db.execute('SELECT 1 FROM collections WHERE id=?', (collection_id,)).fetchone(): raise KeyError('集合不存在')
            old = db.execute('SELECT * FROM members WHERE collection_id=? AND paper_id=?', (collection_id, paper_id)).fetchone()
            if old: check_version(old, expected_version)
            elif expected_version != 0: raise Conflict('成员已变化')
            values = (collection_id, paper_id, mode, role, position, progress, note, old['version']+1 if old else 1)
            db.execute('INSERT OR REPLACE INTO members VALUES(?,?,?,?,?,?,?,?)', values)
            self._event(db, 'member_saved', {'before': dict(old) if old else None, 'after': dict(zip(('collection_id','paper_id','mode','role','position','progress','note','version'), values))})
        return next(m for m in self.members(collection_id) if m['paper_id'] == paper_id)

    def members(self, collection_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM members WHERE collection_id=? ORDER BY position,paper_id', (collection_id,))]
