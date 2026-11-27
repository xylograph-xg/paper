"""Bounded diagnostic archival; active and scientific artifacts are always preserved."""
import fcntl,gzip,hashlib,json,time,os
from core.api import paths__WorkspacePath as Path


def maintain(catalog,days=7,config=None):
 from core.api import services__atomic_json as atomic_json
 from reading.api import reading_contract__file_digest as file_digest
 folder=catalog.path.parent;out=folder/'diagnostic-archive';changed=[]
 with (folder/'diagnostic-retention.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return []
  cutoff=time.time()-days*86400;budget=100
  logs=folder/'logs'
  for entry in os.scandir(logs) if logs.exists() else []:
   if budget<=0:break
   path=Path(entry.path)
   if not entry.is_file() or not path.name.startswith(('acquire-','fetchpdf-','model-job-','discover-')) or not path.name.endswith('.log') or entry.stat().st_mtime>=cutoff:continue
   identifier=path.stem.split('-',2)[-1] if path.name.startswith('model-job-') else path.stem.split('-',1)[1]
   with catalog.connect() as db:
    row=db.execute('SELECT state FROM jobs WHERE id=?',(identifier,)).fetchone()
    if path.name.startswith('fetchpdf-'):
     active=db.execute("SELECT 1 FROM jobs WHERE paper_id=? AND state IN ('queued','running','waiting_storage') LIMIT 1",(identifier,)).fetchone()
    elif path.name.startswith('discover-'):
     active=db.execute("SELECT 1 FROM jobs WHERE kind='discover' AND state='running' LIMIT 1").fetchone()
    else:active=bool(row and row[0] in ('queued','running','waiting_storage'))
   if active or (row and row[0] not in ('done','cancelled') and entry.stat().st_mtime>time.time()-30*86400):continue
   budget-=1;temporary=None
   try:
    out.mkdir(exist_ok=True);destination=out/(path.name+'.'+file_digest(path)[:16]+'.gz');temporary=destination.with_suffix('.tmp')
    before=entry.stat();digest=file_digest(path)
    with path.open('rb') as source,gzip.open(temporary,'wb') as target:
     __import__('shutil').copyfileobj(source,target)
    check=hashlib.sha256()
    with gzip.open(temporary,'rb') as stream:
     for chunk in iter(lambda:stream.read(1024*1024),b''):check.update(chunk)
    after=path.stat()
    if check.hexdigest()!=digest or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise OSError('诊断在归档期间变化，保留原文件')
    temporary.replace(destination);proof={'source':str(path),'archive':str(destination),'sha256':digest}
    atomic_json(destination.with_suffix('.json'),proof);path.unlink();changed.append(proof)
   except (OSError,ValueError) as exc:
    catalog.event(None,'diagnostic_retention_warning',{'file':str(path),'error':str(exc)})
   finally:
    if temporary:temporary.unlink(missing_ok=True)
  if config:
      raw_root=(Path(config['archive_root'])/'raw').resolve()
      with catalog.connect() as db:runs=[dict(row) for row in db.execute("SELECT * FROM runs WHERE json_extract(result,'$.raw_file') LIKE '%.json' ORDER BY created LIMIT 100")]
      for run in runs:
          try:
              result=json.loads(run['result']);path=Path(result.get('raw_file') or '').resolve()
              if not path.is_relative_to(raw_root) or path.suffix!='.json' or not path.is_file() or path.stat().st_mtime>=cutoff:continue
              destination=path.with_suffix('.json.gz');temporary=destination.with_suffix('.tmp')
              with path.open('rb') as source,gzip.open(temporary,'wb') as target:
                  import shutil
                  shutil.copyfileobj(source,target)
              from reading.api import reading_contract__file_digest as file_digest
              digest=file_digest(path)
              check=hashlib.sha256()
              with gzip.open(temporary,'rb') as stream:
                  for block in iter(lambda:stream.read(1024*1024),b''):check.update(block)
              if check.hexdigest()!=digest:raise OSError('原始书目压缩校验失败')
              temporary.replace(destination)
              entry={'source':str(path),'archive':str(destination),'sha256':digest}
              from core.api import services__atomic_json as atomic_json
              atomic_json(destination.with_suffix('.sha256.json'),entry)
              result['raw_file']=str(destination)
              with catalog.connect() as db:db.execute('UPDATE runs SET result=? WHERE id=?',(json.dumps(result,ensure_ascii=False),run['id']))
              path.unlink();changed.append(entry)
          except (OSError,ValueError,TypeError) as exc:
              catalog.event(None,'raw_retention_warning',{'run_id':run['id'],'error':str(exc)})
  if changed:catalog.event(None,'diagnostics_archived',{'files':changed})
 return changed


def read_raw(path):
 path=Path(path)
 if not path.exists() and path.with_suffix(path.suffix+'.gz').exists():path=path.with_suffix(path.suffix+'.gz')
 if path.suffix=='.gz':
  with gzip.open(path,'rt') as stream:return json.load(stream)
 return json.loads(path.read_text())
