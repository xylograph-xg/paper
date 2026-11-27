"""Recover proven unsent reviews without discarding receipts or changing science."""
import json
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__now as now
from core.api import services__atomic_json as atomic_json
from cards.api import web_card_inputs__digest as digest


def recover(catalog, config):
    from .card_review_queue import enabled, current, protected, check_packet
    from browser.api import (upload_retry_policy__guard as cooldown_guard,
                             upload_retry_policy__material_identity as material_identity,
                             web_upload_bundle__check_zip_size as check_zip_size)
    report = {'recovered': [], 'retained': [], 'checked_at': time.time()}
    if not enabled(config):return report
    with catalog.connect() as db:
        jobs = [dict(r) for r in db.execute("SELECT * FROM card_review_jobs WHERE state IN ('needs_user','failed')")]
    from core.api import workflow_priority__seed_first as seed_first
    with catalog.connect() as db:
        jobs=seed_first(db,jobs)
    for job in jobs:
        folder = Path(job['folder']); path = folder/'attempt.json'
        try:
            retained=json.loads(job['result'])
            if retained and retained.get('material_recheck_pending') is not True:continue
            if not path.is_file():continue
            attempt = json.loads(path.read_text())
            # Missing click evidence is uncertain; only an explicit false is safe.
            if attempt.get('state') != 'not_sent' or attempt.get('send_click_started') is not False:continue
            if attempt.get('review_id') != job['id']:raise ValueError('回执归属不一致')
            if any((folder/name).exists() for name in ('response-raw.txt','feedback.json','assessment.json')):
                raise ValueError('已有回答或报告，保留收取链')
            paper, _, _ = current(catalog,job,config)
            if protected(catalog,paper):raise ValueError('人工保护')
            packet = check_packet(folder)
            bundle = packet['upload_bundle']
            check_zip_size(bundle)
            check_zip_size({'size': Path(bundle['zip_path']).stat().st_size})
            from browser.api import original_upload_http1__material_intent as material_intent
            if material_intent(catalog.path.parent,'review',job['id'],job['paper_id'],packet['upload_bundle']['zip_sha256']):
                raise ValueError('原附件PUT已有持久意图，保留原材料回执，不重传')
            if attempt.get('inputs') != packet['input_hashes'] or attempt.get('actual_prompt_sha256') != packet['actual_prompt_sha256']:
                raise ValueError('回执与冻结输入不一致')
            fingerprint = digest(path)
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                fresh = db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
                if dict(fresh) != job or digest(path) != fingerprint or not enabled(config):raise ValueError('状态变化')
                if db.execute("SELECT 1 FROM shared_page_backlog WHERE lane='review' AND job_id=? AND state!='queued'",(job['id'],)).fetchone():
                    raise ValueError('原页面仍领取，由所有者核对')
                if db.execute('SELECT 1 FROM card_correction_jobs WHERE review_id=?',(job['id'],)).fetchone():raise ValueError('已有修正')
                current(catalog,job,config)
                if protected(catalog,paper):raise ValueError('人工保护变化')
                # Only a proven upload wait can hold the requeue; the receipt,
                # page and original FIFO stay untouched and the next scan retries.
                cooldown_guard(db,config,job['id'],identity=material_identity(packet))
                archive = folder/'history'/('unsent-'+fingerprint)
                archive.mkdir(parents=True,exist_ok=True)
                atomic_json(archive/'recovery.json',{'job':job,'attempt_sha256':fingerprint,'checked_at':time.time()})
                destination = archive/'attempt.json'
                if destination.exists():raise ValueError('归档已存在，保留待核对')
                path.replace(destination)
                db.execute("UPDATE card_review_jobs SET state='ready',error='',updated=? WHERE id=?",(now(),job['id']))
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'review_unsent_requeued',?,?)",
                    (job['paper_id'],json.dumps({'review_id':job['id'],'archive':str(archive),'previous_error':job['error']}),now()))
            report['recovered'].append(job['id'])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            report['retained'].append({'id':job['id'],'reason':str(exc)})
    atomic_json(catalog.path.parent/'review-channel-recovery.json',report)
    return report
