"""Bound temporary uploads; never collect files referenced by unfinished jobs."""
import argparse
import fcntl
import hashlib
import json
import re
import time
from contextlib import contextmanager
from core.api import paths__WorkspacePath as Path

@contextmanager
def upload_lock(catalog):
    with (catalog.path.parent/'uploads.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield

def collect(catalog, *, apply=False, ttl_seconds=7*86400):
    folder=catalog.path.parent/'uploads'
    protected=set();completed=set()
    with catalog.connect() as db:
        for row in db.execute("SELECT payload,state,paper_id FROM jobs WHERE kind='import'"):
            payload=json.loads(row['payload'] or '{}')
            source=payload.get('source')
            if not source:continue
            source=str(Path(source).resolve())
            if row['state']=='done':
                paper=catalog.get(row['paper_id'])
                if paper.get('asset_path') and Path(paper['asset_path']).is_file():
                    with Path(paper['asset_path']).open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
                    if sha==paper.get('asset_hash'):completed.add((source,sha))
            else:protected.add(source) # Failed/unknown jobs also preserve input.
    eligible=[];total=0
    for path in folder.glob('*.pdf'):
        if path.is_symlink() or not re.fullmatch(r'[0-9a-f]{32}\.pdf',path.name):continue
        info=path.stat();total+=info.st_size
        resolved=str(path.resolve())
        if resolved in protected:continue
        done=any(source==resolved and sha==hashlib.sha256(path.read_bytes()).hexdigest() for source,sha in completed)
        if not done and any(source==resolved for source,sha in completed):continue
        if done or time.time()-info.st_mtime>ttl_seconds:
            eligible.append(str(path))
            if apply:path.unlink();total-=info.st_size
    return {'eligible':eligible,'bytes':total,'applied':apply}

def write_upload(folder,body):
    import secrets
    target=folder/(secrets.token_hex(16)+'.pdf')
    try:
        with target.open('xb') as stream:stream.write(body);stream.flush()
        return target
    except BaseException:
        target.unlink(missing_ok=True);raise


def prepare(catalog,config,incoming):
    folder=catalog.path.parent/'uploads';folder.mkdir(parents=True,exist_ok=True)
    policy=config.get('upload_storage',{})
    result=collect(catalog,apply=True,ttl_seconds=policy.get('ttl_seconds',7*86400))
    if result['bytes']+incoming>policy.get('max_bytes',1024*1024*1024):raise ValueError('上传暂存额度不足；保留已有材料')
    import shutil
    if shutil.disk_usage(folder).free<incoming+100*1024*1024:raise ValueError('磁盘可用空间不足')
    return folder

if __name__=='__main__':
    from core.api import catalog__Catalog as Catalog,catalog__load_config as load_config
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    catalog=Catalog(load_config()['catalog_path'])
    with upload_lock(catalog):print(json.dumps(collect(catalog,apply=args.apply),ensure_ascii=False))
