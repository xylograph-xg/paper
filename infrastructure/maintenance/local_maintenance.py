"""Local policy maintenance for live legacy owners; never calls models or discovery."""
import os,time,json,fcntl
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json

def step(catalog,config):
 from fetch.api import fetch_policy__install as install
 install(catalog)
 changes=catalog.recheck_scope(config.get('scope_recheck_batch_size',200))
 job=catalog.claim(('auto_select',))
 if job:
  from core.api import services__auto_select as auto_select
  try:auto_select(catalog,config);catalog.finish(job['id'],'done')
  except Exception as exc:catalog.finish(job['id'],'failed',str(exc))
 stale=refresh_stale_assessments(catalog,config)
 return {'scope_rechecked':changes,'stale_screen_queued':stale,'auto_select':job['id'] if job else None}

def refresh_stale_assessments(catalog,config):
 from core.api import services__SCREEN_PROMPT_VERSION as SCREEN_PROMPT_VERSION, services__screen_workflow_fingerprint as screen_workflow_fingerprint
 fingerprint=screen_workflow_fingerprint(config['model'])
 limit=config.get('reading_recovery_batch_size',20)
 with catalog.connect() as db:
  pending=db.execute("SELECT count(*) FROM jobs WHERE kind='screen' AND state IN ('queued','running','waiting_storage')").fetchone()[0]
  if pending>=config.get('reading_queue_limit',60):return []
  rows=list(db.execute("SELECT id,asset_path,metadata FROM papers WHERE decision!='reject' AND acquisition='available' AND asset_path IS NOT NULL AND assessment IS NOT NULL AND (coalesce(json_extract(assessment,'$.prompt_version'),0)!=? OR coalesce(json_extract(assessment,'$.workflow_fingerprint'),'')!=?) AND NOT EXISTS(SELECT 1 FROM jobs WHERE jobs.paper_id=papers.id AND kind='screen' AND state IN ('queued','running','waiting_storage')) ORDER BY created LIMIT ?",(SCREEN_PROMPT_VERSION,fingerprint,min(limit,config.get('reading_queue_limit',60)-pending))))
 jobs=[]
 for row in rows:
  meta=json.loads(row['metadata'])
  if meta.get('identity_review_required') or meta.get('out_of_scope') or not Path(row['asset_path']).is_file():continue
  jobs.append(catalog.enqueue('screen',row['id'],{'trigger':'bounded_stale_assessment_refresh','prompt_version':SCREEN_PROMPT_VERSION}))
 return jobs

def main():
 cfg=load_config();catalog=Catalog(cfg['catalog_path']);folder=catalog.path.parent
 with (folder/'local-maintenance.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  parent=int(os.environ.get('PAPER_MAINTENANCE_PARENT','0'))
  retention_at=0
  while True:
   from core.api import runtime__alive as alive
   if parent and not alive(parent):break
   try:
    latest=load_config(cfg.get("_config_path"))
    if latest["catalog_path"]==cfg["catalog_path"]:cfg=latest
    result=step(catalog,cfg)
    if time.time()-retention_at>3600:
     from .artifact_retention import maintain
     result["archived_diagnostics"]=len(maintain(catalog,config=cfg));retention_at=time.time()
   except Exception as exc:result={'error':str(exc)}
   atomic_json(folder/'local-maintenance.json',{'pid':os.getpid(),'updated':time.time(),**result},durable=False)
   time.sleep(30)

if __name__=='__main__':main()
