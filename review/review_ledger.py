"""Fail-closed external authorization and durable per-card submission claims."""
import json,time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config

def catalog_for(manifest=None):
 loop=json.loads(Path(manifest).read_text()) if manifest else {}
 cfg=load_config(loop.get('config_path'));return Catalog(cfg['catalog_path'])

def install(catalog):
 with catalog.connect() as db:db.executescript("""
 CREATE TABLE IF NOT EXISTS external_authorizations(scope TEXT PRIMARY KEY,destination TEXT NOT NULL,materials TEXT NOT NULL,
 human_evidence TEXT NOT NULL,expires REAL NOT NULL,enabled INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS review_submissions(paper_id TEXT NOT NULL,card_sha256 TEXT NOT NULL,state TEXT NOT NULL,
 run_dir TEXT,updated REAL NOT NULL,PRIMARY KEY(paper_id,card_sha256));
 """)

def authorized(loop,catalog,scope):
 if loop.get('external_submission_blocked') is not False or loop.get('state') not in ('authorized_review','reviewing'):return False
 install(catalog)
 with catalog.connect() as db:r=db.execute('SELECT * FROM external_authorizations WHERE scope=?',(str(Path(scope).resolve()),)).fetchone()
 if not (r and r['enabled']==1 and r['expires']>time.time() and r['human_evidence'] and r['destination']=='https://chatgpt.com/' and set(json.loads(r['materials']))=={'paper_pdf','card','screenshots','prompt'}):return False
 try:
  evidence=json.loads(r['human_evidence'])
  ids=evidence['sample_ids'];count=evidence.get('sample_count',4)
  return (type(count) is int and count>0 and len(ids)==count and len(set(ids))==count
          and set(loop.get('samples',{}).values())==set(ids))
 except (ValueError,TypeError,KeyError):return False

def reserve(catalog,pid,card_hash,run_dir):
 install(catalog)
 with catalog.connect() as db:
  db.execute('BEGIN IMMEDIATE')
  prior=db.execute('SELECT state FROM review_submissions WHERE paper_id=? AND card_sha256=?',(pid,card_hash)).fetchone()
  if prior:return False
  db.execute('INSERT INTO review_submissions VALUES(?,?,?,?,?)',(pid,card_hash,'reserved',str(run_dir),time.time()))
 return True

def update(catalog,pid,card_hash,state,run_dir):
 with catalog.connect() as db:db.execute('UPDATE review_submissions SET state=?,run_dir=?,updated=? WHERE paper_id=? AND card_sha256=?',(state,str(run_dir),time.time(),pid,card_hash))

def reconcile(catalog,root):
 install(catalog)
 for p in Path(root).glob('*/run.json'):
  try:
   run=json.loads(p.read_text())
   for sample in run.get('samples',[]):
    if sample['kind'] not in ('image_heavy','equation_heavy','mixed'):raise ValueError('评审类型不合法')
    folder=(p.parent/sample['kind']).resolve()
    if not folder.is_relative_to(p.parent.resolve()):raise ValueError('评审目录越界')
    attempt=folder/'web-attempt.json'
    if attempt.exists():
     state=json.loads(attempt.read_text()).get('state','needs_inspection')
     claimed=reserve(catalog,sample['paper_id'],sample['card_sha256'],p.parent)
     if not claimed:
      with catalog.connect() as db:prior=db.execute('SELECT run_dir FROM review_submissions WHERE paper_id=? AND card_sha256=?',(sample['paper_id'],sample['card_sha256'])).fetchone()
      if Path(prior['run_dir']).resolve()!=p.parent.resolve():raise ValueError('同一卡片存在跨目录回执冲突')
     update(catalog,sample['paper_id'],sample['card_sha256'],state,p.parent)
  except (OSError,ValueError,KeyError,TypeError):raise ValueError('评审账本对账失败，停止外发：'+str(p))
