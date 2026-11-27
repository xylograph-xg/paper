"""Each acquisition uses its own Python process; MuPDF is never shared by threads."""
import json
import os
import sys
import time
import traceback
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog
from core.api import services__acquisition as acquisition


def main():
    payload=json.load(sys.stdin);config=payload['config'];job=payload['job']
    os.environ['PAPER_NETWORK_STATE_DIR']=str(Path(config['catalog_path']).parent)
    os.environ['PAPER_PDF_SOCKET_TIMEOUT']=str(config.get('fetch_pipeline',{}).get('socket_timeout_seconds',12))
    catalog=Catalog(config['catalog_path']);paper=catalog.get(job['paper_id'])
    from core.api import services__archive_root as archive_root
    archive_root(config)
    from .fetch_policy import begin,finish
    if paper['decision']=='reject':
        print(json.dumps({'skipped':True}));return
    if not begin(catalog,paper,config,job['payload'].get('pending_key'),bool(job['payload'].get('manual') or job['payload'].get('manual_retry'))):
        print(json.dumps({'skipped':True,'policy_blocked':True}));return
    if paper['decision']=='reject':
        print(json.dumps({'skipped':True}));return
    stage='fallback' if job['kind']=='acquire_fallback' else 'fast'
    policy=config.get('fetch_pipeline',{})
    budget=policy.get('fallback_task_timeout_seconds',110) if stage=='fallback' else policy.get('fast_task_timeout_seconds',65)
    os.environ['PAPER_ACQUISITION_DEADLINE']=str(time.monotonic()+budget-5)
    args=job['payload'];started=time.monotonic()
    try:acquisition(catalog,config,paper['id'],args.get('source'),args.get('manual',False),stage)
    except Exception as exc:
        from core.api import services__StorageUnavailable as StorageUnavailable, services__archive_root as archive_root
        if isinstance(exc,StorageUnavailable) or (isinstance(exc,OSError) and exc.errno in (5,6,19,28,30)):
            from core.api import services__atomic_json as atomic_json
            atomic_json(catalog.path.parent/'storage-health.json',{'state':'waiting_storage','error':str(exc),'updated':time.time()},durable=False)
            catalog.event(paper['id'],'storage_unavailable',{'error':str(exc)})
            raise StorageUnavailable('SSD 无法写入，保留拉取任务等待存储恢复') from exc
        archive_root(config)
        catalog.event(paper['id'],'acquisition_pending',{'attempts':[{'kind':'timeout' if isinstance(exc,TimeoutError) else 'download_error','error':str(exc)}]})
        finish(catalog,paper['id'],False,stage,config)
        raise
    result=catalog.get(paper['id'])
    finish(catalog,paper['id'],result['acquisition']=='available',stage,config)
    catalog.event(paper['id'],'acquisition_timing',{'stage':stage,'seconds':round(time.monotonic()-started,3),'available':result['acquisition']=='available'})
    print(json.dumps({'available':result['acquisition']=='available','stage':stage}))


if __name__=='__main__':
    from core.api import process_runner__watch_parent as watch_parent
    watch_parent()
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
