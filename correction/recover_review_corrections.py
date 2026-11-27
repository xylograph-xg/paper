"""Reconcile collected formatting failures without editing or resending answers."""
import json
from . import card_correction_queue as q
from core.api import catalog__now as now, services__atomic_json as atomic_json
from core.api import paths__WorkspacePath as Path
from cards.api import web_card_inputs__digest as digest

ERRORS = ('修正原字符串不一致', '修正字段超出排版范围', '修正改变科学文字、数值或符号；退回核对')


def _resume_unsent_routing(catalog, config, report):
    """An older loaded parser can reject a new local task before transport starts."""
    with catalog.connect() as db:
        jobs = [dict(r) for r in db.execute("SELECT * FROM card_correction_jobs WHERE kind='source_rework' AND state IN ('needs_user','failed') AND error IN ('重大问题原核验报告变化','自动终止：重大问题原核验报告变化')")]
    from review.api import card_review_queue as review
    from core.api import workflow_priority__seed_first as seed_first
    with catalog.connect() as db:
        jobs=seed_first(db,jobs)
    for job in jobs:
        try:
            task = q.check_task(job)
            data, assessment, _ = q._collected_review(catalog, task['review'], config)
            if data != task.get('feedback') or assessment != task.get('assessment') or not q._rework_action(config,data,assessment,task['review']['folder']):continue
            paper, _, _ = review.current(catalog, task['review'], config)
            if review.protected(catalog, paper):raise ValueError('人工决定仅保留建议')
            for attempt in (catalog.path.parent/'web_cards'/job['paper_id']).glob('*/attempt.json'):
                if json.loads(attempt.read_text()).get('correction_id') == job['id']:
                    raise ValueError('新修正已有网页账本，仅核对原回执')
            with catalog.connect() as db:
                transport = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (job['paper_id'],)).fetchone()
            if transport and json.loads(transport['selection']).get('rework', {}).get('correction_id') == job['id']:
                raise ValueError('新修正已绑定网页运输，不恢复本地准备')
            q._require_running(config)
            proof=Path(job['folder'])/'config-routing-recovery.json'
            record={'old_job':job,'task_sha256':job['task_sha256'],'evidence':task['evidence']}
            if proof.exists():
                if json.loads(proof.read_text())!=record:raise ValueError('恢复证据变化')
            else:atomic_json(proof,record)
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                fresh = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (job['id'],)).fetchone()
                current_transport = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (job['paper_id'],)).fetchone()
                if (not fresh or dict(fresh) != job or (dict(transport) if transport else None) !=
                        (dict(current_transport) if current_transport else None)):continue
                db.execute("UPDATE card_correction_jobs SET state='queued',error='',updated=? WHERE id=?", (now(),job['id']))
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'correction_routing_parser_resumed',?,?)",
                           (job['paper_id'],json.dumps({'old_job':job,'no_transport_binding':True}),now()))
            report['advanced'].append({'id':job['id'],'reason':'新版分流合同已核对；新任务无网页账本，恢复本地准备'})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['pending'].append({'id':job['id'],'reason':str(exc)[:400]})


def _retire(catalog, job, record):
    # Save the old row byte-for-byte as JSON evidence before the conditional state change.
    record = {'schema_version':1, 'old_job':job, **record}
    target = Path(job['folder'])/'routing-resolution.json'
    if target.exists():
        saved = json.loads(target.read_text())
        if saved != record:raise ValueError('旧修正分流证据变化，保留待核对')
    else:atomic_json(target, record)
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (job['id'],)).fetchone()
        if fresh is None or dict(fresh) != job:return False
        current = db.execute('SELECT card_path,asset_hash FROM papers WHERE id=?', (job['paper_id'],)).fetchone()
        if (not current or current['asset_hash'] != job['source_sha256'] or
                digest(current['card_path']) != record['current_card_sha256']):return False
        db.execute("UPDATE card_correction_jobs SET state='superseded',error=?,updated=? WHERE id=? AND state='needs_user'",
                   (record['reason'], now(), job['id']))
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'correction_routing_reconciled',?,?)",
                   (job['paper_id'], json.dumps({k:v for k,v in record.items() if k != 'old_job'}, ensure_ascii=False), now()))
    return True


def run_once(catalog, config):
    report = {'advanced':[], 'pending':[]}
    if not q.enabled(config) or not config.get('card_correction', {}).get('priority_passed_first'):return report
    _resume_unsent_routing(catalog, config, report)
    from review.api import card_review_queue as review
    with catalog.connect() as db:
        jobs = [dict(r) for r in db.execute("SELECT * FROM card_correction_jobs WHERE kind='formatting' AND state='needs_user'")]
    from core.api import workflow_priority__seed_first as seed_first
    with catalog.connect() as db:
        jobs=seed_first(db,jobs)
    for job in jobs:
        if job['error'] not in ERRORS:continue
        try:
            task = q.check_task(job)
            # The original report, URL, attachment and prompt are all checked.
            data, assessment, _ = q._collected_review(catalog, task['review'], config)
            if data != task.get('feedback'):raise ValueError('原修正报告变化')
            paper = catalog.get(job['paper_id'])
            if review.protected(catalog, paper):raise ValueError('人工决定仅保留建议')
            path = Path(paper.get('card_path') or '')
            current_hash = digest(path)
            if current_hash != job['card_sha256']:
                with catalog.connect() as db:
                    followups = [dict(r) for r in db.execute("SELECT * FROM card_correction_jobs WHERE paper_id=? AND source_sha256=? AND state='applied'",
                                                           (job['paper_id'],job['source_sha256']))]
                successor = next((r for r in followups if json.loads(r['result']).get('after') == current_hash), None)
                if successor:
                    # The new card has already been published by the original pipeline.
                    if successor['kind']=='source_rework':
                        with catalog.connect() as db:
                            webjob = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (job['paper_id'],)).fetchone()
                        if not webjob:raise ValueError('新版缺少原文制卡登记')
                        q._published_rework(catalog, successor, dict(webjob), config)
                    else:
                        q.check_task(successor)
                        journal = json.loads((Path(successor['folder'])/'publication.json').read_text())
                        if (journal.get('after') != current_hash or journal.get('correction_id') != successor['id']
                                or journal.get('task_sha256') != successor['task_sha256']
                                or digest(Path(successor['folder'])/'card-candidate.json') != current_hash):
                            raise ValueError('本地新版缺少原修正发布证据')
                    review.current(catalog, {**task['review'],'card_sha256':current_hash}, config)
                    reason = '旧建议已由原文新版替代；新版独立核验继续，保留旧报告'
                    binding = {'successor_correction_id':successor['id']}
                else:
                    card = json.loads(path.read_text());origin = card.get('meta', {}).get('source_review', {}).get('job_id')
                    with catalog.connect() as db:
                        row = db.execute('SELECT * FROM card_review_jobs WHERE id=?', (origin,)).fetchone()
                        chain = db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='card_source_review' AND json_extract(payload,'$.state')='passed' AND json_extract(payload,'$.after')=?",
                                           (job['paper_id'],current_hash)).fetchone()
                    if not row or row['state']!='passed' or not chain:raise ValueError('新版尚无完整核验或修正发布证据')
                    newer = dict(row)
                    _, passed, _ = q._collected_review(catalog, newer, config)
                    if passed['action'] != 'pass':raise ValueError('新版报告没有完整科学通过')
                    review.current(catalog, {**newer,'card_sha256':current_hash}, config)
                    reason = '后续当前版本完整核验已通过；旧修正建议失效，保留旧报告'
                    binding = {'successor_review_id':origin}
            else:
                if assessment['action'] != 'rework':raise ValueError('原建议不能自动分流为原文重做')
                review.current(catalog, task['review'], config)
                q._require_running(config)
                successor = q.enqueue_review(catalog, task['review'], config, data, assessment)
                reason = '建议涉及科学文字或无效排版位置，转独立原文重做；旧任务与FIFO保留'
                binding = {'successor_correction_id':successor['id']}
            q._require_running(config)
            if _retire(catalog, job, {'correction_id':job['id'], 'current_card_sha256':current_hash,
                                      'reason':reason, **binding}):
                report['advanced'].append({'id':job['id'], 'reason':reason, **binding})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['pending'].append({'id':job['id'],'reason':str(exc)[:400]})
    return report
