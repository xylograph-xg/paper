"""Durable per-target and per-URL retry policy, including old live worker compatibility."""
import hashlib,json,time,ssl,random
from core.api import catalog__now as now

SCHEMA_SQL="""
CREATE TABLE IF NOT EXISTS fetch_targets(paper_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'ready',retry_at REAL NOT NULL DEFAULT 0,pending_key TEXT,error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS fetch_pending_links(key TEXT PRIMARY KEY,paper_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fetch_urls(paper_id TEXT NOT NULL,url TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 failure_class TEXT,error TEXT,retry_at REAL NOT NULL DEFAULT 0,PRIMARY KEY(paper_id,url));
CREATE TRIGGER IF NOT EXISTS new_fetch_inputs AFTER UPDATE OF record ON discovery_pending
WHEN OLD.state NOT IN ('excluded','quarantined') AND (coalesce(json_extract(NEW.record,'$.pdf_urls'),'')!=coalesce(json_extract(OLD.record,'$.pdf_urls'),'') OR coalesce(json_extract(NEW.record,'$.arxiv_version_id'),'')!=coalesce(json_extract(OLD.record,'$.arxiv_version_id'),''))
BEGIN UPDATE fetch_targets SET state='ready',retry_at=0,error='' WHERE pending_key=NEW.key OR paper_id=(SELECT paper_id FROM fetch_pending_links WHERE key=NEW.key);
UPDATE discovery_pending SET state='pending',retry_at=0 WHERE key=NEW.key; END;
-- Storage contract: an older live worker cannot erase a producer's retry/terminal result.
CREATE TRIGGER IF NOT EXISTS keep_fetch_policy_pending AFTER UPDATE OF state,retry_at ON discovery_pending
WHEN NEW.state IN ('pending','queued') AND EXISTS(SELECT 1 FROM fetch_targets t WHERE (t.pending_key=NEW.key OR t.paper_id=(SELECT paper_id FROM fetch_pending_links WHERE key=NEW.key)) AND (t.state='terminal' OR t.retry_at>NEW.retry_at))
BEGIN UPDATE discovery_pending SET state=CASE WHEN (SELECT state FROM fetch_targets WHERE pending_key=NEW.key OR paper_id=(SELECT paper_id FROM fetch_pending_links WHERE key=NEW.key) LIMIT 1)='terminal' THEN 'blocked_fetch' ELSE 'pending' END,
 retry_at=(SELECT retry_at FROM fetch_targets WHERE pending_key=NEW.key OR paper_id=(SELECT paper_id FROM fetch_pending_links WHERE key=NEW.key) LIMIT 1),error=(SELECT error FROM fetch_targets WHERE pending_key=NEW.key OR paper_id=(SELECT paper_id FROM fetch_pending_links WHERE key=NEW.key) LIMIT 1) WHERE key=NEW.key; END;
CREATE TRIGGER IF NOT EXISTS reject_blocked_fetch_job AFTER INSERT ON jobs
WHEN NEW.kind IN ('acquire','acquire_fallback') AND coalesce(json_extract(NEW.payload,'$.manual_retry'),0)!=1
 AND EXISTS(SELECT 1 FROM fetch_targets t WHERE t.paper_id=NEW.paper_id AND (t.state='terminal' OR t.retry_at>cast(strftime('%s','now') AS REAL)))
BEGIN INSERT OR REPLACE INTO fetch_pending_links(key,paper_id) SELECT json_extract(NEW.payload,'$.pending_key'),NEW.paper_id WHERE json_extract(NEW.payload,'$.pending_key') IS NOT NULL;
UPDATE jobs SET state='cancelled',error='目标重试策略阻止重复获取' WHERE id=NEW.id;
UPDATE discovery_pending SET state=CASE WHEN (SELECT state FROM fetch_targets WHERE paper_id=NEW.paper_id)='terminal' THEN 'blocked_fetch' ELSE 'pending' END,retry_at=(SELECT retry_at FROM fetch_targets WHERE paper_id=NEW.paper_id),error='目标累计重试策略阻止重复排队' WHERE key=json_extract(NEW.payload,'$.pending_key'); END;
CREATE TRIGGER IF NOT EXISTS fetch_done_requires_asset AFTER UPDATE OF state ON jobs
WHEN NEW.kind IN ('acquire','acquire_fallback') AND NEW.state='done' AND NOT EXISTS(SELECT 1 FROM papers p WHERE p.id=NEW.paper_id AND p.acquisition='available' AND p.asset_path IS NOT NULL)
BEGIN UPDATE jobs SET state=CASE WHEN EXISTS(SELECT 1 FROM fetch_targets t WHERE t.paper_id=NEW.paper_id AND t.state='terminal') THEN 'needs_manual' ELSE 'deferred' END WHERE id=NEW.id; END;
"""

def install(catalog):
 with catalog.connect() as db:db.executescript(SCHEMA_SQL)

def fingerprint(metadata):
 return hashlib.sha256(json.dumps({k:metadata.get(k) for k in ('doi','pdf_urls','open_access_pdf','arxiv_version_id')},sort_keys=True).encode()).hexdigest()

def begin(catalog,paper,config,pending_key=None,manual=False):
 install(catalog);signature=fingerprint(paper['metadata']);limit=config.get('fetch_pipeline',{}).get('target_retry_limit',6)
 with catalog.connect() as db:
  db.execute('BEGIN IMMEDIATE')
  if pending_key:db.execute('INSERT OR REPLACE INTO fetch_pending_links VALUES(?,?)',(pending_key,paper['id']))
  fast=bool(paper['metadata'].get('manual_seed_fast_lane'))
  old=db.execute('SELECT * FROM fetch_targets WHERE paper_id=?',(paper['id'],)).fetchone()
  if fast and old and old['state']=='terminal':
   db.execute("UPDATE fetch_targets SET state='ready',retry_at=0,error='' WHERE paper_id=?",(paper['id'],))
  if old and old['input_hash']==signature and not manual and not fast and (old['state']=='terminal' or old['retry_at']>time.time() or old['attempts']>=limit):return False
  if old and old['input_hash']!=signature:db.execute("UPDATE fetch_targets SET input_hash=?,attempts=0,state='ready',retry_at=0,error='' WHERE paper_id=?",(signature,paper['id']))
  db.execute("INSERT INTO fetch_targets(paper_id,input_hash,attempts,pending_key) VALUES(?,?,1,?) ON CONFLICT(paper_id) DO UPDATE SET attempts=attempts+1,state='ready',retry_at=0,pending_key=coalesce(excluded.pending_key,pending_key)",(paper['id'],signature,pending_key))
 return True

def classify(error,kind=None,code=None):
 text=str(error).lower()
 if code in (401,403) or kind=='access_check':return 'access_required'
 # A local address-guard rejection is environment-dependent (proxy/DNS mode),
 # not a property of the URL. Never turn it into a permanent deterministic
 # exclusion; the bounded target retry limit still applies.
 if kind=='network_guard' or any(x in text for x in ('指向本机或内网','连接地址指向')):return 'transient'
 if code in (400,404,405,410) or isinstance(error,(ValueError,ssl.SSLCertVerificationError)) or 'certificate_verify_failed' in text or any(x in text for x in ('未匹配','缺少匹配 doi','html 网页','不是 pdf','加密','损坏')):return 'deterministic'
 if code==429 or (isinstance(code,int) and code>=500) or kind in ('timeout','deferred') or any(x in text for x in ('timed out','timeout','connection','预算已耗尽')):return 'transient'
 return 'not_found' if kind=='not_found' else 'transient'

def record_url(catalog,pid,url,error,kind=None,code=None,retry_at=0,*,request_started=None):
 category='transient' if request_started is False else classify(error,kind,code)
 count=0 if request_started is False or kind=='resource_wait' else 1
 with catalog.connect() as db:db.execute('INSERT INTO fetch_urls VALUES(?,?,?,?,?,?) ON CONFLICT(paper_id,url) DO UPDATE SET attempts=attempts+excluded.attempts,failure_class=CASE WHEN excluded.attempts=0 AND failure_class IN (\'deterministic\',\'access_required\') THEN failure_class ELSE excluded.failure_class END,error=excluded.error,retry_at=CASE WHEN excluded.attempts=0 THEN max(retry_at,excluded.retry_at) ELSE excluded.retry_at END',(pid,url,count,category,str(error),retry_at))
 return category

def select_urls(catalog,pid,urls,limit,retry_limit=3):
 install(catalog)
 with catalog.connect() as db:history={r['url']:dict(r) for r in db.execute('SELECT * FROM fetch_urls WHERE paper_id=?',(pid,))}
 valid=[u for u in dict.fromkeys(urls) if history.get(u,{}).get('failure_class') not in ('deterministic','access_required') and history.get(u,{}).get('attempts',0)<retry_limit and history.get(u,{}).get('retry_at',0)<=time.time()]
 return sorted(valid,key=lambda u:history.get(u,{}).get('attempts',0))[:limit]

def finish(catalog,pid,available,stage,config):
 with catalog.connect() as db:
  target=db.execute('SELECT * FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()
  if not target:return
  row=db.execute('SELECT metadata FROM papers WHERE id=?',(pid,)).fetchone()
  fast=bool(json.loads(row[0]).get('manual_seed_fast_lane')) if row and row[0] else False
  if fast and target['state']=='terminal':
   db.execute("UPDATE fetch_targets SET state='ready',retry_at=0,error='' WHERE paper_id=?",(pid,))
   target=db.execute('SELECT * FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone()
  if available:
   db.execute("UPDATE fetch_targets SET state='ready',retry_at=0,error='' WHERE paper_id=?",(pid,));return
  if target['state']=='terminal':return  # Never revive a terminal changed after claim.
  attempt=db.execute("SELECT payload FROM events WHERE paper_id=? AND kind IN ('acquisition_pending','acquisition_fast_pending') ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
  errors=json.loads(attempt[0]).get('attempts',[]) if attempt else []
  sources=[x for x in errors if not x.get('aggregate')]
  # Legacy fast resource_wait already means a verified pre-request lock wait.
  legacy_wait=stage=='fast' and errors and all(x.get('kind')=='resource_wait' for x in errors)
  pure_wait=bool(sources) and all(x.get('request_started') is False and x.get('kind') in ('resource_wait','deferred') for x in sources) and all(x.get('request_started') is False for x in errors if x.get('aggregate'))
  if legacy_wait or pure_wait:
   at=time.time();eligible=[x.get('retry_at',0) for x in sources if x.get('retry_at',0)>at and x.get('code') not in (401,403)]
   retry=max(at+1,min(eligible)) if eligible else max(at+60,max(x.get('retry_at',0) for x in errors))
   reason='来源等待；本次未发出请求，保留重试预算'
   db.execute("UPDATE fetch_targets SET attempts=max(0,attempts-1),state='ready',retry_at=?,error=? WHERE paper_id=?",(retry,reason,pid))
   if target['pending_key']:db.execute("UPDATE discovery_pending SET state='pending',retry_at=?,error=? WHERE key=?",(retry,reason,target['pending_key']))
   db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'fetch_source_wait',json.dumps({'stage':stage,'retry_at':retry,'attempts_preserved':max(0,target['attempts']-1),'evidence':errors}),now()))
   return
  limit=config.get('fetch_pipeline',{}).get('target_retry_limit',6)
  terminal=target['attempts']>=limit and not fast
  # Fast failure still permits one independent multi-source fallback.
  categories=[classify(x.get('error',''),x.get('kind'),x.get('code')) for x in errors]
  if stage=='fallback' and categories and all(c in ('deterministic','access_required','not_found') for c in categories) and not fast:terminal=True
  delay=min(86400,900*2**min(target['attempts']-1,6))*random.uniform(.85,1.15)
  at=time.time();timed=[x for x in errors if x.get('retry_at',0)>at]
  # Only new explicit source evidence permits earliest-source scheduling.
  # Permission failures and old/unknown receipts retain their original clock.
  eligible=[x['retry_at'] for x in timed if 'request_started' in x and x.get('code') not in (401,403) and
            (x.get('kind') in ('deferred','resource_wait') or x.get('code')==429 or isinstance(x.get('code'),int) and x['code']>=500)]
  independent=bool(eligible) and all('request_started' in x for x in timed) and not terminal
  source_clock=min(eligible) if independent else max([x.get('retry_at',0) for x in errors]+[0])
  retry=max(at+delay,source_clock) if stage=='fallback' or terminal else 0
  reason='seed 快车道无限重试：保留目标并退避' if fast else ('获取失败达到目标上限或确定性终态；新链接/版本或显式人工重试可恢复' if terminal else '有界退避等待公开来源重试')
  db.execute('UPDATE fetch_targets SET state=?,retry_at=?,error=? WHERE paper_id=?',('terminal' if terminal else 'ready',retry,reason,pid))
  if target['pending_key']:db.execute('UPDATE discovery_pending SET state=?,retry_at=?,error=? WHERE key=?',('blocked_fetch' if terminal else 'pending',retry,reason,target['pending_key']))
  db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'fetch_retry_policy',json.dumps({'attempts':target['attempts'],'terminal':terminal,'retry_at':retry,'classes':categories,'source_clock':source_clock,'independent_sources':independent}),now()))
