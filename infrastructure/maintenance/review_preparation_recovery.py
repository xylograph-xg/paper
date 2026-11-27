"""Explicit local recovery of unclaimed reviews that failed before dispatch."""
import argparse
import fcntl
import hashlib
import json
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog,catalog__now as now,catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json
from cards.api import web_card_inputs__digest as digest
from browser.api import attempt_history__index_attempts as index_attempts
from review.api import card_review_queue as queue

ERRORS=frozenset(('ZIP exceeds local 64MiB upload limit','核对媒体已有非登记文件，保留待核对'))


def verify(catalog,job,config):
    if (not queue.enabled(config) or job['state']!='needs_user' or job['error'] not in ERRORS or
            json.loads(job['result'])):raise ValueError('不是本轮限定的未派发准备失败')
    paper,_,_=queue.current(catalog,job,config)
    if queue.protected(catalog,paper):raise ValueError('人工保护')
    folder=Path(job['folder']).resolve()
    root=catalog.path.parent.resolve()/'card_reviews'/job['paper_id']
    if not folder.is_relative_to(root):raise ValueError('原准备目录归属变化')
    if any(folder.rglob('response-raw.txt')) or any(folder.rglob('attempt.json')):
        raise ValueError('存在原请求或回答，不恢复准备')
    records,_=index_attempts(catalog.path.parent)
    for path,record in records.items():
        if (Path(path).is_relative_to(folder) or record.get('review_id')==job['id'] or
                record.get('job_id')==job['id']):raise ValueError('历史请求仍需原所有者核对')
    with catalog.connect() as db:
        if db.execute("SELECT 1 FROM shared_page_backlog WHERE lane='review' AND job_id=?",(job['id'],)).fetchone():
            raise ValueError('已有页面分配，不离线恢复')
        if db.execute('SELECT 1 FROM card_correction_jobs WHERE review_id=?',(job['id'],)).fetchone():
            raise ValueError('已有修正，不改原任务归属')
    return folder


def recover(catalog,job,config):
    """Reuses frozen bytes or builds an independent candidate; never browser I/O."""
    lock=catalog.path.parent/'card-review-material-repair.lock'
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder=verify(catalog,job,config)
        frozen=(folder/'packet.json').exists()
        if frozen:
            candidate=job;new_folder=folder
            packet=queue.check_packet(folder)
        else:
            new_id=hashlib.sha256((job['id']+job['card_sha256']+job['source_sha256']+'local-preparation-recovery-v1').encode()).hexdigest()[:24]
            new_folder=folder.parent/new_id
            if new_folder.exists():raise ValueError('独立准备候选已存在，不覆盖')
            candidate={**job,'id':new_id,'folder':str(new_folder),'state':'queued'}
            new_folder.mkdir()
            originals={p.name:digest(p) for p in folder.iterdir() if p.is_file()}
            atomic_json(new_folder/'local-recovery-intent.json',{'original_job':job,'original_files':originals,
                'new_review_id':new_id,'no_original_request':True,'created':now()})
            if not queue.prepare(catalog,candidate,config,locate_quote_pages=False):raise ValueError('本地准备未完成')
            packet=queue.check_packet(new_folder)
            if any(not (folder/name).is_file() or digest(folder/name)!=sha for name,sha in originals.items()):
                raise ValueError('旧准备证据变化，不登记候选')
        if (packet.get('job_id')!=candidate['id'] or packet.get('card_sha256')!=job['card_sha256'] or
                packet.get('source_original_sha256')!=job['source_sha256']):raise ValueError('材料包身份不一致')
        if Path(packet['upload_bundle']['zip_path']).stat().st_size>=60_000_000:
            raise ValueError('冻结ZIP仍超当前60MB预算，不入队')
        packet_sha=digest(new_folder/'packet.json')
        result={'old_review_id':job['id'],'new_review_id':candidate['id'],'reused_frozen_packet':frozen,
                'old_folder':str(folder),'new_folder':str(new_folder),'packet_sha256':packet_sha,
                'zip_bytes':packet['upload_bundle'].get('size'),'previous_error':job['error'],'state':'ready',
                'no_old_materials_modified':True,'no_request_sent_by_recovery':True}
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
            if current is None or dict(current)!=job:raise ValueError('原准备任务变化，不登记候选')
            verify(catalog,job,config)
            if digest(new_folder/'packet.json')!=packet_sha:raise ValueError('新冻结包变化')
            queue.check_packet(new_folder)
            db.execute("UPDATE card_review_jobs SET id=?,folder=?,state='ready',error='',updated=? WHERE id=?",
                       (candidate['id'],str(new_folder),now(),job['id']))
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'review_local_preparation_recovered',?,?)",
                       (job['paper_id'],json.dumps(result,ensure_ascii=False),now()))
        return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--review-id',action='append',required=True)
    parser.add_argument('--report',required=True);args=parser.parse_args()
    if len(args.review_id)>4 or len(set(args.review_id))!=len(args.review_id):parser.error('每次显式恢复最多4个不同任务')
    config=load_config();catalog=Catalog(config['catalog_path']);report={'at':time.time(),'recovered':[],'retained':[]}
    for rid in args.review_id:
        try:
            with catalog.connect() as db:row=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(rid,)).fetchone()
            if row is None:raise ValueError('原任务不存在')
            report['recovered'].append(recover(catalog,dict(row),config))
        except (OSError,ValueError,KeyError,TypeError) as exc:report['retained'].append({'id':rid,'reason':str(exc)[:600]})
        atomic_json(Path(args.report),report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
