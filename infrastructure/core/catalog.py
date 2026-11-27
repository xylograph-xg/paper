"""Stable identities, human decisions and durable jobs. No network or model calls."""
from __future__ import annotations
from .paths import workspace_root as _workspace_root

import json
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .paths import WorkspacePath as Path

ROOT = _workspace_root()


def now():
    return datetime.now(timezone.utc).isoformat()


def doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I).lower()


def title_key(value):
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def load_config(path=None):
    path = Path(path or ROOT / "config/first_round.json").resolve()
    c = json.loads(path.read_text())
    c["_config_path"] = str(path)
    if type(c.get('local_models_enabled',True)) is not bool:raise ValueError('local_models_enabled必须为布尔值')
    if type(c.get('card_correction',{}).get('priority_passed_first',False)) is not bool:
        raise ValueError('card_correction.priority_passed_first必须为布尔值')
    supervisor=c.get('automatic_issue_handling',{}).get('owner_supervision',{})
    if not isinstance(supervisor,dict) or type(supervisor.get('enabled',False)) is not bool:
        raise ValueError('owner_supervision.enabled必须为布尔值')
    if supervisor and (type(supervisor.get('stale_seconds',300)) is not int or supervisor.get('stale_seconds',300)<300):
        raise ValueError('所有者双心跳故障门槛须至少300秒')
    for key in ("archive_root", "archive_volume", "studio_library_root", "catalog_path", "seed_input_dir"):
        c[key] = str(Path(c[key]).expanduser().resolve())
    n = c["first_round"]["candidate_limit_total"]
    if type(n) is not int or not 1 <= n <= 100:
        raise ValueError("候选数量必须为 1–100")
    # Local model settings are checked only at an explicitly allowed local
    # execution boundary; fetch/web services do not require an Ollama config.
    quota=c['first_round']['direct_card_selection']
    for field in ('first_round_maximum','maximum_per_100_candidates'):
        value=quota.get(field)
        if type(value) is not int or not 0<=value<=100:raise ValueError('自动选入配额必须为 0–100：'+field)
    if type(c.get('screen_seed_limit',5)) is not int or not 1<=c.get('screen_seed_limit',5)<=20:raise ValueError('screen_seed_limit 必须为 1–20')
    if type(c.get('preprint_auto_select',False)) is not bool:raise ValueError('preprint_auto_select 必须是布尔值')
    for section,key,default,maximum in (('fetch_pipeline','target_retry_limit',6,100),('fetch_pipeline','url_retry_limit',3,20)):
        value=c.get(section,{}).get(key,default)
        if type(value) is not int or not 1<=value<=maximum:raise ValueError(key+' 必须为合法的正整数')
    channels=c.get('discovery_channels',[])
    if not isinstance(channels,list) or any(x not in ('oled_topic','seed_related','arxiv','chemrxiv') for x in channels):raise ValueError('检索通道配置不合法')
    policy=c.get('fetch_pipeline',{})
    web=c.get('web_cards',{})
    if web:
        if type(web.get('enabled')) is not bool:raise ValueError('web_cards.enabled必须是布尔值')
        fraction=web.get('selection_fraction',.30)
        if isinstance(fraction,bool) or not isinstance(fraction,(int,float)) or not 0<fraction<=1:raise ValueError('网页精选比例必须在0–1内')
        if type(web.get('max_pages_per_provider',20)) is not int or not 1<=web.get('max_pages_per_provider',20)<=20:raise ValueError('每家网页上限不能超过20')
        if type(web.get('max_parallel_jobs',40)) is not int or not 1<=web.get('max_parallel_jobs',40)<=40:raise ValueError('网页生成并发须为1–40')
        if type(web.get('max_total_pages',20)) is not int or not 1<=web.get('max_total_pages',20)<=20:raise ValueError('专用浏览器总页数须为1–20')
    validate_fetch_capacity(policy)
    if policy.get('fast_task_timeout_seconds',65)<20 or policy.get('fallback_task_timeout_seconds',110)<20:raise ValueError('拉取任务总预算须至少 20 秒，预留验证与落盘时间')
    return c


def validate_fetch_capacity(policy):
    """Static and applied runtime limits share the authorized total of 150."""
    for field,minimum,maximum in [('download_workers',1,150),('fallback_workers',0,149),
                                  ('source_workers',1,8),('seed_workers',1,10),('topic_workers',1,4)]:
        value=policy.get(field,1)
        if type(value) is not int or not minimum<=value<=maximum:
            raise ValueError('拉取并发超出范围：'+field)
    if policy.get('download_workers',1)+policy.get('fallback_workers',1)>150:
        raise ValueError('直链与回退总并发不能超过150')


def validate_local_model(config):
    """Legacy model validation is independent of current fetch/web config."""
    model=config.get('model',{})
    if model.get('provider')!='ollama':raise ValueError('本地模型通道只支持Ollama兼容接口')
    parallel=model.get('parallel_reading_jobs',2)
    if type(parallel) is not int or not 1<=parallel<=2:raise ValueError('本地初筛/制卡模型并发须为1或2')
    from .model_schedule import validate
    validate({'timezone':'Asia/Shanghai','start':'10:00','end':'24:00',**config.get('local_model_schedule',{})})


class Catalog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from fetch.api import fetch_timing__install as install
        from reading.api import reading_library__install as install_reading
        from .schema_cache import signature,ready,record
        fingerprint,required=signature((Catalog.__init__,install,install_reading))
        if self.path.is_file():
            with self.connect() as db:
                if ready(db,fingerprint,required):return
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript("""
            CREATE TABLE IF NOT EXISTS papers(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, title_key TEXT NOT NULL,
              metadata TEXT NOT NULL, seed INTEGER NOT NULL DEFAULT 0,
              candidate_order INTEGER, decision TEXT NOT NULL DEFAULT 'unreviewed',
              acquisition TEXT NOT NULL DEFAULT 'not_attempted', asset_path TEXT,
              asset_hash TEXT, assessment TEXT, card_path TEXT, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS identifiers(
              kind TEXT NOT NULL, value TEXT NOT NULL, paper_id TEXT NOT NULL REFERENCES papers(id),
              PRIMARY KEY(kind,value));
            CREATE TABLE IF NOT EXISTS discoveries(
              paper_id TEXT REFERENCES papers(id), reason TEXT NOT NULL,
              PRIMARY KEY(paper_id,reason));
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, paper_id TEXT, payload TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'queued', error TEXT NOT NULL DEFAULT '',
              attempts INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(kind,ifnull(paper_id,''))
              WHERE state IN ('queued','running','waiting_storage');
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY, paper_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY, created TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS auto_selections(
              paper_id TEXT PRIMARY KEY REFERENCES papers(id), window INTEGER NOT NULL,
              evidence TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS auto_selection_checks(paper_id TEXT PRIMARY KEY,reason TEXT NOT NULL,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS daily_runs(day TEXT PRIMARY KEY,job_id TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_cursors(key TEXT PRIMARY KEY,position INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS source_progress(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS discovery_pending(key TEXT PRIMARY KEY,record TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',retry_at REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS event_paper_kind ON events(paper_id,kind,id);
            CREATE INDEX IF NOT EXISTS paper_title_key ON papers(title_key);
            CREATE INDEX IF NOT EXISTS job_state_kind ON jobs(state,kind,created);
            CREATE INDEX IF NOT EXISTS pending_retry ON discovery_pending(state,retry_at);
            CREATE TRIGGER IF NOT EXISTS fetch_done_requires_asset_base AFTER UPDATE OF state ON jobs
            WHEN NEW.kind IN ('acquire','acquire_fallback') AND NEW.state='done'
              AND NOT EXISTS(SELECT 1 FROM papers p WHERE p.id=NEW.paper_id AND p.acquisition='available' AND p.asset_path IS NOT NULL)
            BEGIN
              UPDATE jobs SET state='deferred',error=CASE WHEN error='' THEN '尚无原文资产，不能标记获取成功' ELSE error END
              WHERE id=NEW.id AND state='done';
            END;
            CREATE TRIGGER IF NOT EXISTS preserve_removed_seeds AFTER UPDATE OF seed ON papers
            WHEN NEW.seed=1 AND coalesce(json_extract(NEW.metadata,'$.user_seed_disabled'),0)=1
            BEGIN
              UPDATE papers SET seed=0,metadata=json_set(metadata,'$.selected_as_seed',json('false')) WHERE id=NEW.id;
            END;
            CREATE TRIGGER IF NOT EXISTS preserve_explicit_seed_membership AFTER UPDATE OF seed ON papers
            WHEN NEW.seed=1 AND NOT coalesce(json_extract(NEW.metadata,'$.selected_as_seed'),0)
              AND NOT coalesce(json_extract(NEW.metadata,'$.is_correction'),0)
            BEGIN
              UPDATE papers SET seed=0 WHERE id=NEW.id;
            END;
            """)
            # Seed compatibility guards preserve explicit human seed intent; centralized here.
            # Migrate legacy business triggers to explicit Python transitions.
            db.execute('DROP TRIGGER IF EXISTS seed_control_compat')
            db.executescript("""
            CREATE TABLE IF NOT EXISTS catalog_revision(id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER NOT NULL);
            INSERT OR IGNORE INTO catalog_revision VALUES(1,0);
            """)
            for table in ('papers','jobs','events','runs','auto_selection_checks'):
                for operation in ('INSERT','UPDATE','DELETE'):
                    name='revision_'+table+'_'+operation.lower()
                    db.execute(f'CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON {table} BEGIN UPDATE catalog_revision SET value=value+1 WHERE id=1; END')

        install(self)
        install_reading(self)
        with self.connect() as db:record(db,fingerprint)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.create_function("unicode_fold",1,lambda v:__import__("unicodedata").normalize("NFKC",str(v or "")).casefold(),deterministic=True)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            from .cooperative_sql import read_checkpoints
            with read_checkpoints(db), db:
                yield db
        finally:
            db.close()

    def upsert(self, record, reason="", seed=False, candidate=False):
        record = dict(record)
        if seed and not record.get('is_correction'):record.setdefault('selected_as_seed',True)
        for field in ('source','channels','pdf_urls'):
            if field in record:
                value=record[field]
                record[field]=[value] if isinstance(value,str) else list(value or [])
        record['doi'] = doi(record.get('doi'))
        if not str(record.get('title', '')).strip():
            raise ValueError('论文缺少题名')
        ids = [(k, str(record[k])) for k in ('doi', 'openalex_id', 'semantic_scholar_id','arxiv_id') if record.get(k)]
        family=re.sub(r'(?:-v|\.v|/v)\d+$','',record['doi']) if record['doi'].startswith('10.26434/chemrxiv') else ''
        if family:ids.append(('chemrxiv_family',family))
        key = title_key(record['title'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            matches = {r['paper_id'] for k,v in ids for r in db.execute('SELECT paper_id FROM identifiers WHERE kind=? AND value=?',(k,v))}
            if len(matches)>1:
                raise ValueError('来源身份冲突，需要人工合并')
            existing = db.execute('SELECT * FROM papers WHERE id=?',(next(iter(matches)),)).fetchone() if matches else None
            if existing is None:
                # Only merge title matches when known DOIs do not conflict.
                rows = db.execute('SELECT * FROM papers WHERE title_key=?',(key,)).fetchall()
                rows = [r for r in rows if not (record['doi'] and json.loads(r['metadata']).get('doi') and record['doi']!=json.loads(r['metadata'])['doi'])]
                if len(rows)>1:raise ValueError('题名对应多个身份，需人工核对，拒绝自动新建重复记录')
                if len(rows)==1:
                    existing=rows[0]
            pid = existing['id'] if existing else str(uuid.uuid4())
            data = json.loads(existing['metadata']) if existing else {}
            version_change=bool(family and re.sub(r'(?:-v|\.v|/v)\d+$','',data.get('doi',''))==family)
            if version_change:
                def version(identifier):
                    match=re.search(r'(?:-v|\.v|/v)(\d+)$',identifier)
                    return int(match[1]) if match else 0
                if version(data.get('doi',''))>version(record['doi']):
                    record={**record,**{k:v for k,v in data.items() if k not in {'channels','source','pdf_urls'}}}
                    key=title_key(record['title'])
            arxiv_publication=bool(record.get('arxiv_id') and record.get('arxiv_id')==data.get('arxiv_id') and data.get('doi','').startswith('10.48550/arxiv.'))
            if record.get('arxiv_id') and record.get('arxiv_id')==data.get('arxiv_id'):
                old=re.search(r'v(\d+)$',data.get('arxiv_version_id',''))
                incoming=re.search(r'v(\d+)$',record.get('arxiv_version_id',''))
                if old and incoming and int(old[1])>int(incoming[1]):
                    record={**record,**{k:v for k,v in data.items() if k not in {'channels','source','pdf_urls'}}}
                    key=title_key(record['title'])
            if data.get('doi') and record['doi'] and data['doi']!=record['doi'] and not (version_change or arxiv_publication):
                raise ValueError('相同来源身份对应冲突 DOI，需要人工核对')
            for k,v in record.items():
                if v not in (None,'',[]):
                    if k=='abstract' and len(data.get(k,'') or '')>len(v) and record.get('abstract_authoritative') is not True:
                        continue
                    if k in {'pdf_urls','source','channels','discovered_from_seed_dois'}:
                        old=data.get(k,[])
                        old=[old] if isinstance(old,str) else list(old or [])
                        v=list(dict.fromkeys(old+v))
                    data[k]=v
            order=existing['candidate_order'] if existing else None
            if candidate and order is None and not (seed or (existing and existing['seed'])):
                order=db.execute('SELECT coalesce(max(candidate_order),0)+1 FROM papers').fetchone()[0]
            seed_member=bool((seed or (existing and existing['seed'])) and (data.get('is_correction') or data.get('selected_as_seed')) and not data.get('user_seed_disabled'))
            if existing:
                db.execute('UPDATE papers SET title=?,title_key=?,metadata=?,seed=?,candidate_order=? WHERE id=?',
                           (data['title'],key,json.dumps(data,ensure_ascii=False),int(seed_member),order,pid))
            else:
                db.execute('INSERT INTO papers(id,title,title_key,metadata,seed,candidate_order,created) VALUES(?,?,?,?,?,?,?)',
                           (pid,data['title'],key,json.dumps(data,ensure_ascii=False),int(seed_member),order,now()))
            for k,v in ids:
                db.execute('INSERT OR IGNORE INTO identifiers VALUES(?,?,?)',(k,v,pid))
            if reason:
                db.execute('INSERT OR IGNORE INTO discoveries VALUES(?,?)',(pid,reason))
            from fetch.api import manual_seed_lineage__record_origin as record_origin
            record_origin(db,pid,record,reason)
            return pid

    def find_doi(self,value):
        key=doi(value)
        if not key:return None
        with self.connect() as db:
            row=db.execute("SELECT paper_id FROM identifiers WHERE kind='doi' AND value=?",(key,)).fetchone()
        return row['paper_id'] if row else None

    def get(self,pid):
        with self.connect() as db:
            row=db.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone()
            if not row:
                raise KeyError('论文不存在')
            result=dict(row)
            result['metadata']=json.loads(result['metadata'])
            result['assessment']=json.loads(result['assessment']) if result['assessment'] else None
            result['reasons']=[r[0] for r in db.execute('SELECT reason FROM discoveries WHERE paper_id=?',(pid,))]
            pending=db.execute("SELECT payload FROM events WHERE paper_id=? AND kind='acquisition_pending' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
            result['acquisition_detail']=json.loads(pending[0]) if pending and result['acquisition']!='available' else None
            automatic=db.execute('SELECT evidence,window FROM auto_selections WHERE paper_id=?',(pid,)).fetchone()
            result['automatic_selection']=dict(evidence=json.loads(automatic['evidence']),window=automatic['window']) if automatic else None
            gate=db.execute('SELECT reason FROM auto_selection_checks WHERE paper_id=?',(pid,)).fetchone()
            result['automatic_gate']=gate[0] if gate else None
            return result

    def list(self):
        with self.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM papers ORDER BY seed DESC,candidate_order,created')]
            reasons={};pending={};automatic={}
            for r in db.execute('SELECT paper_id,reason FROM discoveries'):reasons.setdefault(r['paper_id'],[]).append(r['reason'])
            for r in db.execute("SELECT e.paper_id,e.payload FROM events e JOIN (SELECT paper_id,max(id) id FROM events WHERE kind='acquisition_pending' GROUP BY paper_id) latest ON e.id=latest.id"):
                pending[r['paper_id']]=json.loads(r['payload'])
            for r in db.execute('SELECT * FROM auto_selections'):
                automatic[r['paper_id']]={'evidence':json.loads(r['evidence']),'window':r['window']}
            gates={r['paper_id']:r['reason'] for r in db.execute('SELECT * FROM auto_selection_checks')}
        for r in rows:
            r['metadata']=json.loads(r['metadata']);r['assessment']=json.loads(r['assessment']) if r['assessment'] else None
            r['reasons']=reasons.get(r['id'],[]);r['acquisition_detail']=pending.get(r['id']) if r['acquisition']!='available' else None
            r['automatic_selection']=automatic.get(r['id'])
            r['automatic_gate']=gates.get(r['id'])
        return rows

    def page(self,limit=100,offset=0,query='',tab='all',channel='',pdf_only=False,include_read=False):
        if not 1<=limit<=200 or offset<0:raise ValueError('分页参数不合法')
        from reading.api import reading_library__refresh_scores as refresh_scores
        refresh_scores(self)
        terms=['1'];args=[]
        filters={'seeds':'seed=1','deep':"(papers.card_path IS NOT NULL OR decision IN ('deep_read','original_read')) AND coalesce(rs.is_read,0)=0",'read':'rs.is_read=1','pending':"acquisition LIKE 'needs%'",'candidates':"candidate_order IS NOT NULL AND decision='unreviewed' AND coalesce(rs.is_read,0)=0"}
        seed_cards = {}
        if tab == 'manual_seed_cards':
            from reading.api import manual_literature__seed_cards
            seed_cards = manual_literature__seed_cards(self)
            terms.append("EXISTS(SELECT 1 FROM json_each(?) j WHERE j.key=papers.id "
                         "AND json_extract(j.value,'$.sha256')=sc.card_sha256 "
                         "AND sc.card_path=papers.card_path AND sc.source_hash=papers.asset_hash)")
            args.append(json.dumps(seed_cards))
        if include_read:filters['deep']=filters['deep'].replace(' AND coalesce(rs.is_read,0)=0','')
        manual_views = ('deep_regular','deep_manual_seeds','deep_manual_derived')
        if tab not in ('all','manual_seed_cards',*filters,*manual_views):raise ValueError('列表类型不合法')
        if tab in manual_views:terms.append(filters['deep'])
        if tab in filters:terms.append(filters[tab])
        if pdf_only and tab=='candidates':terms.append("acquisition='available' AND asset_path IS NOT NULL AND coalesce(json_extract(metadata,'$.out_of_scope'),0)=0")
        public_fields=['papers.title',*[f"coalesce(json_extract(metadata,'$.{k}'),'')" for k in ('doi','venue','year','abstract','authors')],*[f"coalesce(json_extract(assessment,'$.{k}'),'')" for k in ('core_findings','recommendation_reason','novelty','tags')]]
        public_fields.extend(("coalesce(sc.work_summary,'')","coalesce(sc.key_findings,'')","coalesce(rs.note,'')"))
        search='unicode_fold('+"||' '||".join(public_fields)+')'
        for word in __import__('unicodedata').normalize('NFKC',query).casefold().split():
            terms.append(search+" LIKE ? ESCAPE '\\'");args.append('%'+word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        if channel:terms.append("EXISTS(SELECT 1 FROM json_each(json_extract(metadata,'$.channels')) WHERE value=?)");args.append(channel)
        where=' AND '.join(terms)
        projection="""papers.id,papers.title,seed,candidate_order,decision,acquisition,asset_path,papers.card_path,created,
          coalesce(rs.is_read,0) AS is_read,rs.read_at,coalesce(rs.note,'') AS note,coalesce(rs.note_version,0) AS note_version,
          sc.overall_quality,sc.direction_novelty,sc.card_sha256 AS evaluation_card_sha256,sc.work_summary AS card_work_summary,sc.key_findings AS card_key_findings,
          json_object('doi',json_extract(metadata,'$.doi'),'venue',json_extract(metadata,'$.venue'),'year',json_extract(metadata,'$.year'),
            'channels',json_extract(metadata,'$.channels'),'publication_kind',json_extract(metadata,'$.publication_kind'),
            'identity_review_required',json_extract(metadata,'$.identity_review_required'),'version_review_required',json_extract(metadata,'$.version_review_required'),'arxiv_version_id',json_extract(metadata,'$.arxiv_version_id'),'asset_preprint_version',json_extract(metadata,'$.asset_preprint_version'),'is_correction',json_extract(metadata,'$.is_correction'),'out_of_scope',json_extract(metadata,'$.out_of_scope'),
            'abstract',substr(json_extract(metadata,'$.abstract'),1,1000),'authors',json_extract(metadata,'$.authors')) AS metadata,
          json_object('core_findings',json_extract(assessment,'$.core_findings'),'recommendation_reason',json_extract(assessment,'$.recommendation_reason'),
            'novelty',json_extract(assessment,'$.novelty'),'evidence_quote',json_extract(assessment,'$.evidence_quote'),
            'evidence_scope',json_extract(assessment,'$.evidence_scope'),'tags',json_extract(assessment,'$.tags'),
            'workflow_fingerprint',json_extract(assessment,'$.workflow_fingerprint'),'prompt_version',json_extract(assessment,'$.prompt_version')) AS assessment"""
        with self.connect() as db:
            source='FROM papers LEFT JOIN paper_reading_state rs ON rs.paper_id=papers.id LEFT JOIN paper_card_scores sc ON sc.paper_id=papers.id'
            review_score=review_state=review_complete='NULL'
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='card_review_jobs'").fetchone():
                source+=' LEFT JOIN card_review_jobs cr ON cr.paper_id=papers.id AND cr.card_sha256=sc.card_sha256 AND cr.source_sha256=sc.source_hash'
                review_score="CASE WHEN json_valid(cr.result) THEN CASE WHEN json_type(cr.result,'$.weighted_score') IN ('integer','real') AND json_extract(cr.result,'$.weighted_score') BETWEEN 0 AND 100 THEN json_extract(cr.result,'$.weighted_score') END END"
                review_state='cr.state'
                review_complete="CASE WHEN json_valid(cr.result) THEN CASE WHEN json_type(cr.result,'$.full_source_checked') IN ('true','false') THEN json_extract(cr.result,'$.full_source_checked') END END"
            # Correction completion is version-bound; old applied jobs cannot
            # make a changed card/source visible in the curated reading library.
            corrected = '0'
            scientific_pass = '0'
            if review_state != 'NULL':
                scientific_pass = """cr.state='passed' AND CASE WHEN json_valid(cr.result) THEN
                    json_extract(cr.result,'$.pass')=1
                    AND json_extract(cr.result,'$.full_source_checked')=1
                    AND json_extract(cr.result,'$.verdict')='pass'
                    AND json_extract(cr.result,'$.action')='pass'
                    AND json_type(cr.result,'$.weighted_score') IN ('integer','real')
                    AND json_extract(cr.result,'$.weighted_score') BETWEEN 85 AND 100
                    AND json_type(cr.result,'$.missing_inputs')='array'
                    AND json_array_length(cr.result,'$.missing_inputs')=0
                    AND json_extract(cr.result,'$.issue_counts.major')=0
                    AND json_extract(cr.result,'$.issue_counts.critical')=0
                    ELSE 0 END"""
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='card_correction_jobs'").fetchone():
                corrected = """EXISTS(SELECT 1 FROM card_correction_jobs cc
                    WHERE cc.paper_id=papers.id AND cc.state='applied'
                      AND cc.source_sha256=papers.asset_hash AND cc.source_sha256=sc.source_hash
                      AND sc.card_path=papers.card_path AND sc.card_sha256 IS NOT NULL
                      AND CASE WHEN json_valid(cc.result)
                        THEN (json_extract(cc.result,'$.after')=sc.card_sha256
                          OR EXISTS(SELECT 1 FROM events e WHERE e.paper_id=papers.id
                            AND e.kind='card_source_review' AND CASE WHEN json_valid(e.payload) THEN
                              json_extract(e.payload,'$.state')='passed'
                              AND json_extract(e.payload,'$.before')=json_extract(cc.result,'$.after')
                              AND json_extract(e.payload,'$.after')=sc.card_sha256 ELSE 0 END)) ELSE 0 END)"""
            corrected = '(' + corrected + ') AND (' + scientific_pass + ')'
            if tab == 'deep' or tab in manual_views:
                where += ' AND (' + corrected + ')'
            from fetch.api import manual_seed_lineage__library_condition as library_condition
            if tab in manual_views:where += ' AND ('+library_condition(db,tab)+')'
            total_score=f'round(sc.overall_quality+({review_score}),2)'
            projection+=f',({review_score}) AS review_score,({total_score}) AS total_score,({review_state}) AS review_state,({review_complete}) AS review_full_source_checked'
            order='total_score IS NULL,total_score DESC,sc.overall_quality IS NULL,sc.overall_quality DESC,sc.direction_novelty IS NULL,sc.direction_novelty DESC,created DESC,papers.id' if tab!='pending' else 'seed DESC,created DESC,papers.id'
            total=db.execute('SELECT count(*) '+source+' WHERE '+where,args).fetchone()[0]
            rows=[dict(r) for r in db.execute('SELECT '+projection+' '+source+' WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',(*args,limit,offset))]
            stats=dict(db.execute("SELECT count(*) papers,sum(acquisition='available' AND asset_path IS NOT NULL) assets,sum(papers.card_path IS NOT NULL) cards,"+
                                 "sum(coalesce(rs.is_read,0)=1) read,sum((papers.card_path IS NOT NULL OR decision IN ('deep_read','original_read')) AND coalesce(rs.is_read,0)=0 AND ("+corrected+")) unread_deep "+source).fetchone())
            for group in manual_views:
                stats[group]=db.execute('SELECT count(*) '+source+' WHERE '+filters['deep']+
                    ' AND ('+corrected+') AND ('+library_condition(db,group)+')').fetchone()[0]
            revision=db.execute('SELECT value FROM catalog_revision WHERE id=1').fetchone()[0]
            ids=[r['id'] for r in rows];details={};gates={};reasons={};automatic={}
            if ids:
                marks=','.join('?' for _ in ids)
                for r in db.execute('SELECT paper_id,reason FROM discoveries WHERE paper_id IN ('+marks+')',ids):reasons.setdefault(r['paper_id'],[]).append(r['reason'])
                automatic={r['paper_id']:{'window':r['window']} for r in db.execute('SELECT paper_id,window FROM auto_selections WHERE paper_id IN ('+marks+')',ids)}
                gates={r['paper_id']:r['reason'] for r in db.execute('SELECT paper_id,reason FROM auto_selection_checks WHERE paper_id IN ('+marks+')',ids)}
                for pid in ids:
                    e=db.execute("SELECT payload FROM events WHERE paper_id=? AND kind IN ('acquisition_pending','acquisition_fast_pending') ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
                    if e:details[pid]=json.loads(e[0])
        from .services import SCREEN_PROMPT_VERSION,screen_workflow_fingerprint
        current_screen=screen_workflow_fingerprint(load_config()['model'])
        for row in rows:
            if tab == 'manual_seed_cards':
                row['manual_seed_card'] = seed_cards[row['id']]
            row['is_read']=bool(row['is_read'])
            if row['review_full_source_checked'] is not None:row['review_full_source_checked']=bool(row['review_full_source_checked'])
            row['metadata']=json.loads(row['metadata']);row['assessment']=json.loads(row['assessment'])
            if not row['assessment'].get('core_findings'):row['assessment']=None
            row['assessment_stale']=bool(row['assessment'] and (row['assessment'].get('prompt_version')!=SCREEN_PROMPT_VERSION or row['assessment'].get('workflow_fingerprint')!=current_screen))
            row['reasons']=reasons.get(row['id'],[]);row['automatic_selection']=automatic.get(row['id'])
            row['automatic_gate']=gates.get(row['id']);row['acquisition_detail']=details.get(row['id']) if row['acquisition']!='available' else None
        return {'papers':rows,'total':total,'offset':offset,'limit':limit,'stats':stats,'revision':revision}

    def recheck_scope(self,limit=200):
        from fetch.api import preprints__relevant as relevant, preprints__RELEVANCE_POLICY as RELEVANCE_POLICY
        with self.connect() as db:
            rows=[dict(r) for r in db.execute("SELECT key,record FROM discovery_pending WHERE state='excluded' AND error!='人工忽略' AND coalesce(json_extract(record,'$.scope_policy'),'')!=? ORDER BY rowid LIMIT ?",(RELEVANCE_POLICY,limit))]
            for row in rows:
                record=json.loads(row['record']);record['scope_policy']=RELEVANCE_POLICY
                accepted=relevant(record['title']+' '+(record.get('abstract') or ''))
                db.execute('UPDATE discovery_pending SET record=?,state=?,retry_at=?,error=? WHERE key=?',(json.dumps(record,ensure_ascii=False),'pending' if accepted else 'excluded',__import__('time').time()+__import__('random').uniform(0,300),'重新核对领域政策 '+RELEVANCE_POLICY,row['key']))
        return len(rows)

    def update(self,pid,**fields):
        allowed={'acquisition','asset_path','asset_hash','assessment','card_path'}
        if not fields.keys()<=allowed:
            raise ValueError('不允许修改这些字段')
        with self.connect() as db:
            for key,value in fields.items():
                if key=='assessment':
                    value=json.dumps(value,ensure_ascii=False)
                db.execute(f'UPDATE papers SET {key}=? WHERE id=?',(value,pid))

    def event(self,pid,kind,payload):
        with self.connect() as db:
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,kind,json.dumps(payload,ensure_ascii=False),now()))

    def selection_check(self,pid,reason):
        with self.connect() as db:
            previous=db.execute('SELECT reason FROM auto_selection_checks WHERE paper_id=?',(pid,)).fetchone()
            if previous and previous[0]==reason:return
            db.execute('INSERT INTO auto_selection_checks VALUES(?,?,?) ON CONFLICT(paper_id) DO UPDATE SET reason=excluded.reason,updated=excluded.updated',(pid,reason,now()))
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'auto_selection_gate',json.dumps({'reason':reason}),now()))

    def decide(self,pid,decision):
        if decision not in {'unreviewed','keep','later','reject','deep_read','original_read'}:
            raise ValueError('非法阅读决定')
        self.get(pid)
        with self.connect() as db:
            db.execute('UPDATE papers SET decision=? WHERE id=?',(decision,pid))
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'human_decision',json.dumps({'decision':decision}),now()))
            if decision=='reject':
                db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE paper_id=? AND state IN ('queued','waiting_storage')",(now(),pid))

    def set_seed(self,pid,enabled):
        if type(enabled) is not bool:raise ValueError('种子状态必须为布尔值')
        paper=self.get(pid)
        if paper['metadata'].get('is_correction') or not (paper['seed'] or paper['card_path'] or paper['decision'] in {'deep_read','original_read'}):
            raise ValueError('只能从精读库选择种子，勘误不参与检索展开')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT metadata FROM papers WHERE id=?',(pid,)).fetchone()
            data=json.loads(row[0]);data.update(selected_as_seed=enabled,user_seed_disabled=not enabled)
            db.execute('UPDATE papers SET seed=?,metadata=? WHERE id=?',(int(enabled),json.dumps(data,ensure_ascii=False),pid))
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'human_seed_change',json.dumps({'seed_id':pid,'seed_action':'add' if enabled else 'remove'}),now()))
            if not enabled:db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE kind='discover' AND paper_id=? AND state='queued' AND json_extract(payload,'$.trigger')='seed_added'",(now(),pid))
            jid=str(uuid.uuid4())
            db.execute('INSERT INTO jobs(id,kind,paper_id,payload,state,created,updated) VALUES(?,?,?,?,?,?,?)',(jid,'seed_control',pid,json.dumps({'seed_action':'add' if enabled else 'remove'}),'done',now(),now()))
            if enabled and not db.execute("SELECT 1 FROM jobs WHERE kind='discover' AND paper_id=? AND state IN ('queued','running','waiting_storage')",(pid,)).fetchone():
                db.execute('INSERT INTO jobs(id,kind,paper_id,payload,created,updated) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),'discover',pid,json.dumps({'seed_id':pid,'trigger':'seed_added'}),now(),now()))
        return {'seed':enabled,'job_id':jid}

    def enqueue(self,kind,pid=None,payload=None):
        if kind=='discover' and (payload or {}).get('seed_action') in ('add','remove'):
            result=self.set_seed(payload['seed_id'],payload['seed_action']=='add')
            return result['job_id']
        if pid:
            self.get(pid)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute("SELECT id FROM jobs WHERE kind=? AND ifnull(paper_id,'')=? AND state IN ('queued','running','waiting_storage','waiting_workflow') ORDER BY created LIMIT 1",(kind,pid or '')).fetchone()
            if existing:return existing[0]
            jid=str(uuid.uuid4())
            try:
                db.execute('INSERT INTO jobs(id,kind,paper_id,payload,created,updated) VALUES(?,?,?,?,?,?)',
                           (jid,kind,pid,json.dumps(payload or {},ensure_ascii=False),now(),now()))
            except sqlite3.IntegrityError:
                row=db.execute("SELECT id FROM jobs WHERE kind=? AND ifnull(paper_id,'')=? AND state IN ('queued','running','waiting_storage')",(kind,pid or '')).fetchone()
                if not row:
                    raise
                jid=row[0]
            return jid

    def enqueue_daily(self,day):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT job_id FROM daily_runs WHERE day=?',(day,)).fetchone()
            if previous:return {'job_id':previous[0],'already_scheduled':True}
            active=db.execute("SELECT id,payload FROM jobs WHERE kind='discover' AND paper_id IS NULL AND state IN ('queued','running','waiting_storage')").fetchone()
            if active and json.loads(active['payload']).get('seed_id'):
                return {'busy':True,'message':'关联检索正在进行，本日全通道检索尚未登记'}
            jid=active['id'] if active else str(uuid.uuid4())
            if not active:
                db.execute('INSERT INTO jobs(id,kind,payload,created,updated) VALUES(?,?,?,?,?)',(jid,'discover',json.dumps({'scheduled_day':day}),now(),now()))
            db.execute('INSERT INTO daily_runs VALUES(?,?,?)',(day,jid,now()))
            return {'job_id':jid,'already_scheduled':False}

    def jobs_page(self,limit=100):
        if not 1<=limit<=200:raise ValueError("任务分页参数不合法")
        with self.connect() as db:return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY CASE WHEN state='running' THEN 0 WHEN state='queued' THEN 1 WHEN state IN ('failed','partial') THEN 2 ELSE 3 END,created DESC LIMIT ?",(limit,))]

    def jobs(self):
        with self.connect() as db:
            jobs=[dict(r) for r in db.execute("SELECT * FROM jobs WHERE state IN ('queued','running','waiting_storage','failed','partial') OR id IN (SELECT id FROM jobs ORDER BY created DESC LIMIT 200) ORDER BY CASE WHEN state IN ('failed','partial') THEN 0 WHEN state IN ('running','waiting_storage') THEN 1 WHEN state='queued' THEN 2 ELSE 3 END,created DESC")]
            recovered={r[0]:r[1] for r in db.execute("SELECT json_extract(payload,'$.old_job_id'),json_extract(payload,'$.job_id') FROM events WHERE kind='reading_policy_job' ORDER BY id")}
            for job in jobs:
                if job['id'] in recovered:job['recovered_by']=recovered[job['id']]
            return jobs

    def claim(self,kinds=None):
        if kinds is not None and not kinds:
            return None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            where=' AND kind IN ('+','.join('?' for _ in kinds)+')' if kinds else ''
            row=db.execute("SELECT * FROM jobs WHERE state='queued'"+where+" ORDER BY CASE WHEN kind='auto_select' THEN 0 ELSE 1 END,created LIMIT 1",tuple(kinds or [])).fetchone()
            if row:
                db.execute("UPDATE jobs SET state='running',attempts=attempts+1,updated=? WHERE id=?",(now(),row['id']))
                result=dict(row);result['payload']=json.loads(result['payload']);return result

    def finish(self,jid,state,error=''):
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,error=?,updated=? WHERE id=?',(state,error[:2000],now(),jid))

    def defer(self,jid,reason):
        """Schedule pauses preserve the same queue entry and retry budget."""
        with self.connect() as db:
            row=db.execute("SELECT kind,payload FROM jobs WHERE id=? AND state='running'",(jid,)).fetchone()
            if row and row['kind']=='deep_read':
                payload=json.loads(row['payload']);payload['resume']=True
                db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(payload),jid))
            db.execute("UPDATE jobs SET state='queued',attempts=max(0,attempts-1),error=?,updated=? WHERE id=? AND state='running'",(reason[:2000],now(),jid))

    def recover(self,kinds=None):
        # Called only after acquiring the exclusive worker lock; no other worker is alive.
        with self.connect() as db:
            where=' AND kind IN ('+','.join('?' for _ in kinds)+')' if kinds else ''
            db.execute("UPDATE jobs SET state='failed',error='上次进程中断；已保存检查点，可恢复重试',updated=? WHERE state='running'"+where,(now(),*tuple(kinds or [])))

    def cursors(self):
        with self.connect() as db:
            result={r['key']:r['position'] for r in db.execute('SELECT * FROM source_cursors')}
            result.update({r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM source_progress')})
            return result

    def retain_discovery(self,records,positions):
        """Persist the entire page before advancing each successful query cursor."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for record in records:
                if not isinstance(record,dict) or not isinstance(record.get('title'),str) or not record['title'].strip():continue
                record=dict(record)
                key=doi(record.get('doi')) or title_key(record['title'])
                try:
                    for field in ('pdf_urls','channels','discovery_reasons','discovered_from_seed_dois'):
                        value=record.get(field) or []
                        value=[value] if isinstance(value,str) else value
                        if not isinstance(value,list) or any(not isinstance(item,str) for item in value):raise ValueError('列表字段格式异常：'+field)
                        record[field]=value
                except ValueError as exc:
                    db.execute("INSERT INTO discovery_pending(key,record,state,error) VALUES(?,?,'quarantined',?) ON CONFLICT(key) DO NOTHING",(key,json.dumps(record,ensure_ascii=False),str(exc)))
                    continue
                old=db.execute('SELECT record FROM discovery_pending WHERE key=?',(key,)).fetchone()
                if old and not doi(record.get('doi')):
                    prior=json.loads(old[0]);conflict=any(prior.get(k) and record.get(k) and prior[k]!=record[k] for k in ('arxiv_id','openalex_id','semantic_scholar_id'))
                    if conflict:
                        import hashlib
                        quarantine=key+':conflict:'+hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()[:16]
                        db.execute("INSERT OR IGNORE INTO discovery_pending(key,record,state,error) VALUES(?,?,'quarantined','相同题名存在不兼容身份；原记录保留')",(quarantine,json.dumps(record,ensure_ascii=False)))
                        continue
                changed=False
                new_pdf=False
                if old:
                    previous=json.loads(old[0])
                    incoming=record
                    record={**previous,**{k:v for k,v in incoming.items() if v not in (None,'',[])}}
                    if len(previous.get('abstract') or '')>len(record.get('abstract') or '') and incoming.get('abstract_authoritative') is not True:record['abstract']=previous['abstract']
                    changed=bool(record.get('arxiv_version_id') and record.get('arxiv_version_id')!=previous.get('arxiv_version_id'))
                    new_pdf=bool(set(record.get('pdf_urls') or [])-set(previous.get('pdf_urls') or []))
                    for field in ('pdf_urls','channels','discovery_reasons','discovered_from_seed_dois'):
                        prior=previous.get(field) or []
                        prior=[prior] if isinstance(prior,str) else prior
                        record[field]=list(dict.fromkeys(prior+(record.get(field) or [])))
                db.execute('INSERT INTO discovery_pending(key,record) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET record=excluded.record',(key,json.dumps(record,ensure_ascii=False)))
                if changed:db.execute("UPDATE discovery_pending SET state='pending',retry_at=0 WHERE key=?",(key,))
                elif new_pdf:db.execute("UPDATE discovery_pending SET retry_at=0 WHERE key=? AND state='pending'",(key,))
            for key,position in positions.items():
                if isinstance(position,(dict,list,str)):
                    db.execute('INSERT INTO source_progress VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(position)))
                else:
                    db.execute('INSERT INTO source_cursors VALUES(?,?) ON CONFLICT(key) DO UPDATE SET position=excluded.position',(key,position))

    def pending_discovery(self,at=None):
        import time
        with self.connect() as db:
            return [(r['key'],json.loads(r['record'])) for r in db.execute("SELECT key,record FROM discovery_pending WHERE state='pending' AND retry_at<=? ORDER BY rowid",(time.time() if at is None else at,))]

    def pending_result(self,key,state='done',error='',retry_at=0):
        with self.connect() as db:db.execute('UPDATE discovery_pending SET state=?,error=?,retry_at=? WHERE key=?',(state,error,retry_at,key))

    def retry(self,jid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row or row['state'] not in {'failed','waiting_storage','partial'}:
                raise ValueError('此任务不可重试')
            active=db.execute("SELECT id FROM jobs WHERE kind=? AND paper_id IS ? AND id!=? AND state IN ('queued','running','waiting_storage','waiting_workflow')",(row['kind'],row['paper_id'],jid)).fetchone()
            if active:raise ValueError('同类型任务已经排队或正在运行，历史失败记录保留')
            db.execute("UPDATE jobs SET state='queued',error='',updated=? WHERE id=?",(now(),jid))

    def reserve_auto(self,pid,evidence,first_limit,window_limit=2):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p=db.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone()
            if not p or p['seed'] or not p['candidate_order'] or p['decision']!='unreviewed':
                return False
            if db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(pid,)).fetchone():
                return False
            window=(p['candidate_order']-1)//100
            count=db.execute('SELECT count(*) FROM auto_selections WHERE window=?',(window,)).fetchone()[0]
            cap=min(window_limit,first_limit) if window==0 else window_limit
            if count>=cap:
                db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'auto_selection_deferred',json.dumps({'reason':'quota','window':window,'limit':cap}),now()))
                return False
            db.execute('INSERT INTO auto_selections VALUES(?,?,?,?)',(pid,window,json.dumps(evidence,ensure_ascii=False),now()))
            db.execute("UPDATE papers SET decision='deep_read' WHERE id=?",(pid,))
            return True
