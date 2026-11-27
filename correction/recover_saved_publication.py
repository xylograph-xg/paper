"""Resume a complete correction answer blocked only by an SSD alias copy error.

No HTTP, no send, no page release; original publication and version guards apply.
"""
import json
import fcntl
from core.api import paths__WorkspacePath as Path
from cards.api import web_card_inputs__digest as digest


def run_once(catalog,config,limit=3):
    from .card_correction_queue import enabled
    if not enabled(config):return []
    with catalog.connect() as db:
        jobs=[dict(x) for x in db.execute("SELECT w.* FROM web_card_jobs w JOIN card_correction_jobs c ON c.id=json_extract(w.selection,'$.rework.correction_id') WHERE c.state='needs_user' AND w.state IN ('needs_inspection','failed') AND c.error LIKE '%same file%' LIMIT ?",(limit,))]
    results=[]
    with (catalog.path.parent/'correction-recovery.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        return _recover_jobs(catalog, config, jobs)


def _recover_jobs(catalog, config, jobs):
    from .card_correction_queue import enabled, _bound_job
    results=[]
    for job in jobs:
        try:
            bound = _bound_job(catalog, job)
            if bound is None or bound['state'] != 'needs_user':continue
            with catalog.connect() as db:
                fresh = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (job['paper_id'],)).fetchone()
            if fresh is None or dict(fresh) != job:continue
            folder=catalog.path.parent/'web_cards'/job['paper_id']
            paths=list(folder.glob('*/attempt.json'))
            if len(paths)!=1:raise ValueError('原完整回执不唯一，继续核对')
            attempt=json.loads(paths[0].read_text());packet=json.loads((folder/'packet.json').read_text())
            from cards.api import web_card_retry__finished_response as finished_response, web_card_retry__frozen_inputs as frozen_inputs
            finished_response(paths[0],attempt,packet)
            frozen_inputs(folder,packet,catalog.get(job['paper_id']))
            raw=paths[0].parent/'response-raw.txt'
            if digest(raw)!=attempt['raw_sha256']:raise ValueError('原回答指纹不一致')
            if not enabled(config):continue
            from cards.api import web_card_service__publish_saved as publish_saved
            publish_saved(config,job,raw.read_text(),attempt,'chatgpt')
            fresh=None
            with catalog.connect() as db:fresh=db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
            results.append({'paper_id':job['paper_id'],'state':fresh['state']})
        except (OSError,ValueError,KeyError,TypeError) as exc:results.append({'paper_id':job['paper_id'],'state':'cycling','reason':str(exc)[:700]})
    return results
