"""Keep failed reviews/corrections cycling; three completed failures recard."""
import json
import time
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json, catalog__now as now


def policy(config):
    path=Path(config['catalog_path']).parent.parent/'config/review-cycle-policy.json'
    return json.loads(path.read_text()) if path.exists() else {}


def failure_limit(config):
    value=policy(config).get('failures_before_recard',3)
    if type(value) is not int or value!=3:
        raise ValueError('本轮仅授权当前卡片版本连续三次完整核验失败后重做')
    return value


def completed_failure(catalog,job,config=None):
    """A collected answer alone cannot turn technical failure into science failure."""
    from .card_review_repair import collected
    from .card_review_queue import parse_review
    collected(catalog,job)
    _,assessment=parse_review((Path(job['folder'])/'response-raw.txt').read_text(),job['folder'],
            optional_external_supplements=(config or {}).get('review_standard',{}).get('external_supplements_optional') is True)
    if assessment['action']=='pass':
        raise ValueError('原报告科学通过，技术发布异常不计科学失败')
    if assessment.get('failure_kind')!='scientific':
        raise ValueError('未完成、有歧义或无依据的核验不计科学失败')
    return assessment


def failure_count(catalog,job,config=None,*,diagnostics=None,stopping=None):
    """Recheck historical reports instead of counting technical recheck events."""
    with catalog.connect() as db:
        events=list(db.execute("SELECT payload FROM events WHERE paper_id=? AND kind='card_review_cycle' AND json_extract(payload,'$.card_sha256')=?",
                               (job['paper_id'],job['card_sha256'])))
    count=0;seen=set()
    def excluded(saved,reason):
        if diagnostics is not None:diagnostics.append({'review_id':saved.get('old_review_id'),'reason':reason})
    for event in events:
        if stopping and stopping():raise InterruptedError('原所有者停止历史核验扫描，保留原证据')
        saved=json.loads(event['payload'])
        if not saved.get('old_folder') or not saved.get('old_review_id'):
            excluded(saved,'历史事件缺少原报告定位，不计科学失败');continue
        key=(saved['old_folder'],saved['old_review_id'])
        if key in seen:
            excluded(saved,'同一原报告事件重复，不重复计数');continue
        previous={**job,'id':saved['old_review_id'],'folder':saved['old_folder']}
        try:completed_failure(catalog,previous,config)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            excluded(saved,str(exc)[:400]);continue
        seen.add(key)
        count+=1
    return count


def run_once(catalog,config,*,stopping=None):
    from . import card_review_queue as q
    from .card_review_repair import repair
    stopping = stopping or (lambda: False)
    report={'checked_at':time.time(),'advanced':[],'pending':[],'not_counted':[]}
    if not policy(config).get('enabled') or not q.enabled(config):return report
    limit=failure_limit(config)
    with catalog.connect() as db:
        jobs=[dict(r) for r in db.execute("SELECT r.* FROM card_review_jobs r WHERE r.state='needs_user' OR (r.state='failed' AND json_extract(r.result,'$.failure_kind')='scientific' AND NOT EXISTS(SELECT 1 FROM card_correction_jobs active WHERE active.review_id=r.id AND active.state IN ('queued','preparing','ready','submitted'))) OR (r.state IN ('correction_queued','rework_queued') AND EXISTS(SELECT 1 FROM card_correction_jobs c WHERE c.review_id=r.id AND c.state IN ('needs_user','failed')))")]
    from core.api import workflow_priority__seed_first as seed_first
    with catalog.connect() as db:
        jobs=seed_first(db,jobs)
    for job in jobs:
        if stopping():break
        try:
            paper,path,_=q.current(catalog,job,config)
            if q.protected(catalog,paper):raise ValueError('人工保护，仅保存候选')
            assessment=completed_failure(catalog,job,config)
            if stopping():break
            count=failure_count(catalog,job,config,diagnostics=report['not_counted'],stopping=stopping)
            if stopping():break
            if job['state']=='failed':
                with catalog.connect() as db:
                    fresh=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
                    if fresh is None or dict(fresh)!=job:continue
                # Retain the failed row until guarded preparation/recard commits.
                # Polling a blocked candidate is not a recovered terminal task.
            if job['state'] in ('correction_queued','rework_queued'):
                q.update(catalog,job['id'],'needs_user','修正未通过，转独立核验循环',json.loads(job['result']))
                with catalog.connect() as db:job=dict(db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone())
            if count>=limit-1:
                q.queue_rework(catalog,job,config,paper,path,{**json.loads(job['result']),**assessment,'cycle_failure_count':count+1})
                report['advanced'].append({'id':job['id'],'action':'source_recard'})
            else:
                result=repair(catalog,job,config,cycle=True)
                report['advanced'].append(result)
            break # One expensive preparation per original producer scan.
        except InterruptedError:
            report['state']='stopping'
            break
        except (OSError,ValueError,KeyError,TypeError) as exc:
            report['pending'].append({'id':job['id'],'reason':str(exc)[:400]})
    if stopping():report['state']='stopping'
    atomic_json(catalog.path.parent/'review-cycle-status.json',report)
    return report
