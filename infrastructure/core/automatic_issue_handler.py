"""Bounded local issue reconciliation under the existing material worker.

Browser observations, receipt collection and proven pre-send retries remain with
one original owner. Never open a browser, clear a pause, or invent science here.
"""
import hashlib
import json
import math
import time
from .paths import WorkspacePath as Path
from .catalog import now
from .services import atomic_json

PREPARATION_BLOCK = '材料准备：已有提交或不确定记录；只核对原会话，不重新发送'
ARCHIVE_BLOCK = '原请求没有完整收取证据'


def review_preparation_fingerprint():
    """Invalidate only local preparation checks after their implementation changes."""
    from review.api import card_review_repair__repair as repair,card_review_queue as queue
    paths=[Path(repair.__code__.co_filename),Path(queue.__file__),Path(__file__).with_name('paths.py')]
    loaded_revision=getattr(repair,'recovery_revision','legacy')
    return hashlib.sha256((''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in paths)+loaded_revision).encode()).hexdigest()


def recover_archived_dispatch(catalog, job, config):
    """Release a blocked source-rework dispatch only after all archives pass.

    No active attempt may exist. Ready materials, original correction task,
    original source/card and committed rework must still match. FIFO is retained.
    """
    from correction.api import card_correction_queue__allows_web_job as allows_web_job, card_correction_queue__check_task as check_task
    from cards.api import web_card_rework__submission_history as submission_history
    if job['state']!='needs_inspection' or job['error']!=ARCHIVE_BLOCK or not allows_web_job(config,job,recovery=True):
        return None
    record=json.loads(job['selection']).get('rework',{})
    cid=record.get('correction_id')
    if record.get('kind')!='source_review' or not cid:return None
    folder=catalog.path.parent/'web_cards'/job['paper_id']
    if list(folder.glob('*/attempt.json')):raise ValueError('当前请求仍需核对，不恢复派发')
    decision=submission_history(catalog,job,folder)
    if not decision.allowed:raise ValueError(decision.reason)
    from cards.api import web_card_retry__frozen_inputs as frozen_inputs
    packet=json.loads((folder/'packet.json').read_text())
    frozen_inputs(folder,packet,catalog.get(job['paper_id']))
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
        material=db.execute('SELECT * FROM web_page_queue WHERE paper_id=?',(job['paper_id'],)).fetchone()
        correction=db.execute('SELECT * FROM card_correction_jobs WHERE id=?',(cid,)).fetchone()
        if (fresh is None or dict(fresh)!=job or material is None or material['state']!='ready'
                or correction is None or correction['paper_id']!=job['paper_id']
                or correction['state']!='needs_user' or correction['error']!=ARCHIVE_BLOCK):
            raise ValueError('原派发/材料/修正状态变化，保留原记录')
        task=check_task(dict(correction))
        if task.get('review',{}).get('id')!=record['review_id']:raise ValueError('修正与原核验归属不一致')
        if list(folder.glob('*/attempt.json')) or not allows_web_job(config,dict(fresh),recovery=True):
            raise ValueError('恢复时暂停或回执变化')
        if not submission_history(catalog,dict(fresh),folder).allowed:raise ValueError('恢复时归档证据变化')
        frozen_inputs(folder,packet,catalog.get(job['paper_id']))
        db.execute("UPDATE web_card_jobs SET state='queued',error='',updated=? WHERE paper_id=?",(now(),job['paper_id']))
        db.execute("UPDATE card_correction_jobs SET state='ready',error='原完整回执及旧容量守卫归档已核对',updated=? WHERE id=?",(now(),cid))
        db.execute("UPDATE shared_page_backlog SET state='queued' WHERE lane='correction' AND job_id=? AND state='claimed'",(cid,))
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'automatic_archive_dispatch_recovery',?,?)",
            (job['paper_id'],json.dumps({'correction_id':cid,'reason':'all archived receipts checked; no active attempt'}),now()))
    return {'paper_id':job['paper_id'],'correction_id':cid,'state':'queued'}


def enabled(config):
    return config.get('automatic_issue_handling', {}).get('enabled') is True


def recover_review_preparation_lock(catalog, job, config):
    """Retry only local preparation interrupted by SQLite contention, twice.

    A prepared packet, any receipt/report, a page claim or an existing correction
    blocks recovery. Keep the original arrival and all partial source materials.
    This does not submit, release a page or consume an external retry.
    """
    from review.api import card_review_queue__enabled as review_enabled, card_review_queue__current as current, card_review_queue__protected as protected
    if (not enabled(config) or not review_enabled(config) or job['state'] != 'needs_user'
            or job['error'] != 'database is locked' or json.loads(job['result']) != {}):
        return None
    folder = Path(job['folder'])

    def unused():
        return not any(
            any(folder.rglob(name)) for name in
            ('attempt.json', 'packet.json', 'response-raw.txt', 'feedback.json', 'assessment.json'))

    if not unused():
        raise ValueError('已有准备完成或回执证据；不恢复准备')
    paper, _, _ = current(catalog, job, config)
    if protected(catalog, paper):
        raise ValueError('人工决定卡片保留原状态')
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh = db.execute('SELECT * FROM card_review_jobs WHERE id=?', (job['id'],)).fetchone()
        if fresh is None or dict(fresh) != job or not unused() or not review_enabled(config):
            raise ValueError('核验准备状态或暂停变化')
        if db.execute('SELECT 1 FROM card_correction_jobs WHERE review_id=?', (job['id'],)).fetchone():
            raise ValueError('已有独立修正；保留原任务')
        if db.execute("SELECT 1 FROM shared_page_backlog WHERE lane='review' AND job_id=? AND state!='queued'",
                      (job['id'],)).fetchone():
            raise ValueError('页面材料已领取；由原所有者核对')
        count = db.execute("SELECT count(*) FROM events WHERE paper_id=? AND kind='automatic_review_preparation_recovery' "
                           "AND json_extract(payload,'$.review_id')=?", (job['paper_id'], job['id'])).fetchone()[0]
        if count >= 2:
            raise ValueError('本地数据库锁恢复上限已到')
        paper, _, _ = current(catalog, job, config)
        if protected(catalog, paper):
            raise ValueError('恢复时人工保护变化')
        db.execute("UPDATE card_review_jobs SET state='queued',error='',updated=? WHERE id=?", (now(), job['id']))
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'automatic_review_preparation_recovery',?,?)",
                   (job['paper_id'], json.dumps({'review_id':job['id'], 'number':count+1,
                    'reason':'SQLite contention before complete packet or page claim',
                    'previous_error':job['error'], 'previous_updated':job['updated'],
                    'card_sha256':job['card_sha256'], 'source_sha256':job['source_sha256']}), now()))
    return {'paper_id':job['paper_id'], 'review_id':job['id'], 'state':'queued', 'kind':'local_preparation_lock'}


def disposition(item):
    text = item['action']
    if item['id'].startswith('channel:') or '登录' in text or '验证码' in text or '访问验证' in text:
        return '等待访问恢复', '通道保持暂停；检测恢复后核对，不自动通过登录或验证码'
    if '额度' in text or '上传上限' in text:
        return '等待额度探测', '由原网页所有者按原提示时间或冷却探测核对'
    if '冲突或歧义' in text or '上限已到' in text:
        return '自动保留', '保留原卡及证据报告，不选择未经原文证实的科学结论'
    if item['id'].startswith(('page:', 'receipt:')) or '可能已发送' in text or '回执' in text or '会话' in text:
        return '原所有者核对', '持续核对原target、正式会话与材料指纹；不重发未知请求'
    if item['id'].startswith('review:'):
        return '核验材料检查', '核对原卡和原文；有新增证据且未达上限时有限补齐复核'
    if item['id'].startswith('correction:') or text == PREPARATION_BLOCK:
        return '重做归档检查', '核对已授权重做、旧回答归档和准备失败证据后恢复'
    return '自动证据核对', '由既有重试及页面维护流程处理；证据不足时保留原记录'


def diagnosis(item):
    """Describe the blocker without claiming that classification repaired it."""
    text = item['action']
    stage, route = disposition(item)
    if stage == '等待访问恢复':
        return {'kind':'access', 'state':'external_wait', 'route':route}
    if stage == '等待额度探测':
        return {'kind':'quota', 'state':'cooldown', 'route':route}
    if stage == '自动保留':
        return {'kind':'protected_evidence', 'state':'retained', 'route':route}
    if '指纹' in text or '字符串不一致' in text or '范围' in text:
        return {'kind':'input_mismatch', 'state':'evidence_pending', 'route':route}
    if '材料缺失' in text or '附件缺失' in text or '未覆盖' in text:
        return {'kind':'incomplete_materials', 'state':'evidence_pending', 'route':route}
    if '结构' in text or '评分' in text or 'JSON' in text:
        return {'kind':'output_contract', 'state':'evidence_pending', 'route':route}
    if stage == '原所有者核对':
        return {'kind':'original_receipt', 'state':'owner_check_pending', 'route':route}
    return {'kind':'technical_failure', 'state':'evidence_pending', 'route':route}


def recover_preparation(catalog, job, config):
    from correction.api import card_correction_queue__allows_web_job as allows_web_job
    from cards.api import web_card_rework__submission_history as submission_history
    if job['state'] != 'needs_inspection' or job['error'] != PREPARATION_BLOCK or not allows_web_job(config, job, recovery=True):
        return None
    record = json.loads(job['selection']).get('rework', {})
    cid = record.get('correction_id')
    if not cid:
        return None
    folder = catalog.path.parent/'web_cards'/job['paper_id']
    if list(folder.glob('*/attempt.json')):
        raise ValueError('当前重做已有回执，保留原页不恢复提交')
    decision = submission_history(catalog, job, folder)
    if not decision.allowed:
        raise ValueError(decision.reason)
    from correction.api import card_correction_queue__check_task as check_task
    with catalog.connect() as db:
        row = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (cid,)).fetchone()
    if row is None or row['paper_id'] != job['paper_id'] or row['kind'] != 'source_rework':
        raise ValueError('修正与材料归属不一致')
    task = check_task(dict(row))
    if task.get('review', {}).get('id') != record.get('review_id'):
        raise ValueError('修正与原核验归属不一致')
    # Only this deterministic preparation failure occurred before any page use.
    # Recheck under the transaction before releasing a provisional claim.
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?', (job['paper_id'],)).fetchone()
        material = db.execute('SELECT * FROM web_page_queue WHERE paper_id=?', (job['paper_id'],)).fetchone()
        correction = db.execute('SELECT * FROM card_correction_jobs WHERE id=?', (cid,)).fetchone()
        if (fresh is None or dict(fresh) != job or material is None or material['state'] != 'failed'
                or material['error'] != PREPARATION_BLOCK.removeprefix('材料准备：')
                or correction is None or correction['state'] != 'needs_user' or correction['error'] != PREPARATION_BLOCK):
            raise ValueError('准备失败状态变化，不释放原领取')
        if dict(correction) != dict(row):
            raise ValueError('修正版本变化')
        check_task(dict(correction))
        if list(folder.glob('*/attempt.json')) or not allows_web_job(config, dict(fresh), recovery=True):
            raise ValueError('恢复时暂停或回执变化')
        if not submission_history(catalog, dict(fresh), folder).allowed:
            raise ValueError('恢复时历史证据变化')
        db.execute("UPDATE web_card_jobs SET state='queued',error='',updated=? WHERE paper_id=?", (now(),job['paper_id']))
        db.execute("UPDATE web_page_queue SET state='waiting',error='' WHERE paper_id=?", (job['paper_id'],))
        db.execute("UPDATE card_correction_jobs SET state='ready',error='旧回执归档及发送前准备失败已自动核对',updated=? WHERE id=?", (now(),cid))
        db.execute("UPDATE shared_page_backlog SET state='queued' WHERE lane='correction' AND job_id=? AND state='claimed'", (cid,))
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'automatic_preparation_recovery',?,?)",
                   (job['paper_id'],json.dumps({'correction_id':cid,'reason':'authorized archived receipt; preparation failed before page use'}),now()))
    return {'paper_id':job['paper_id'], 'correction_id':cid, 'state':'queued'}





def release_proven_presend_claims(catalog, config, report=None):
    """Release page claims whose source failed before send and ledger proves it.

    A protected page is not a scientific result.  Model-picker, window-isolation,
    lock, pool-conflict and entry failures are pre-send technical failures when
    the attempt is absent or explicitly not_sent with send_click_started false.
    """
    import os
    from browser.api import shared_page_backlog__remove_binding as remove_binding
    safe=('Locator expected','TimeoutError: Locator','WindowIsolationError','database is locked',
          'PoolConflict','附件入口暂未就绪','附件上传失败','没有找到 ChatGPT 输入框')
    from browser.api import owner_upload_jobs__active_lease_targets as active_lease_targets
    active_uploads=active_lease_targets(catalog.path.parent)
    released=[]
    with catalog.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_page_backlog'").fetchone():
            return released  # No installed page ledger grants no release authority.
        claims=[dict(row) for row in db.execute("SELECT * FROM shared_page_backlog WHERE state='claimed'")]
        for row in claims:
            if row['target_id'] in active_uploads:continue
            lane=row['lane'];job_id=row['job_id']
            if lane=='review':
                source=db.execute('SELECT state,error,folder FROM card_review_jobs WHERE id=?',(job_id,)).fetchone()
            elif lane=='correction':
                source=db.execute('SELECT state,error,folder FROM card_correction_jobs WHERE id=?',(job_id,)).fetchone()
            else:
                source=db.execute('SELECT state,error,folder FROM web_card_jobs WHERE paper_id=?',(row['paper_id'],)).fetchone()
            if source is None:continue
            source=dict(source)
            if source.get('state') not in ('failed','queued'):continue
            error=source.get('error') or ''
            folder=source.get('folder')
            attempt=None
            if folder and os.path.exists(os.path.join(folder,'attempt.json')):
                try:attempt=json.loads(Path(folder,'attempt.json').read_text())
                except (OSError,ValueError,TypeError):continue
            if attempt is not None:
                if attempt.get('state')!='not_sent' or attempt.get('send_click_started') is not False:continue
            elif not any(marker in error for marker in safe):
                continue
            try:
                remove_binding(db,lane,job_id,row['target_id'],expected_state='claimed')
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'automatic_presend_claim_release',?,?)",
                    (row['paper_id'],json.dumps({'lane':lane,'job_id':job_id,'target_id':row['target_id'],'reason':error[:300]}),now()))
                released.append({'lane':lane,'job_id':job_id,'target_id':row['target_id']})
            except (OSError,ValueError,TypeError):
                continue
    if report is not None:report.setdefault('presend_claims_released',[]).extend(released)
    return released


def requeue_proven_unsent_review(catalog, config, report=None):
    """Requeue technical review failures only when the ledger proves no send."""
    if config.get('review_standard',{}).get('no_user_state') is not True:
        return []
    # Reuse the receipt/packet/identity/pause/backoff/claim guards instead of
    # moving an attempt solely because its error text matches a UI marker.
    from review.api import review_channel_recovery__recover as recover
    recovered=recover(catalog,config)
    changed=[{'lane':'review','id':rid,'state':'ready'} for rid in recovered['recovered']]
    if report is not None:report.setdefault('technical_retries',[]).extend(changed)
    return changed


def normalize_needs_user(catalog, config, report=None):
    """Remove the manual needs_user terminal when the no-user policy is on.

    Evidence is preserved; the job becomes an automatic scientific/technical
    failure and is never resent. A later explicit policy can re-open it.
    """
    if config.get('review_standard', {}).get('no_user_state') is not True:
        return []
    changed = []
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        reviews = [dict(row) for row in db.execute("SELECT id,paper_id,error,result FROM card_review_jobs WHERE state='needs_user'")]
        for row in reviews:
            reason = row.get('error') or '证据不足'
            failure = reason if reason.startswith('自动终止：') else '自动终止：' + reason[:700]
            db.execute("UPDATE card_review_jobs SET state='failed',error=?,updated=? WHERE id=? AND state='needs_user'",
                       (failure, now(), row['id']))
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'automatic_review_failed',?,?)",
                       (row['paper_id'], json.dumps({'review_id': row['id'], 'reason': reason}), now()))
            changed.append({'lane': 'review', 'id': row['id'], 'state': 'failed'})
        corrections = [dict(row) for row in db.execute("SELECT id,paper_id,error FROM card_correction_jobs WHERE state='needs_user'")]
        for row in corrections:
            reason = row.get('error') or '证据不足'
            failure = reason if reason.startswith('自动终止：') else '自动终止：' + reason[:700]
            db.execute("UPDATE card_correction_jobs SET state='failed',error=?,updated=? WHERE id=? AND state='needs_user'",
                       (failure, now(), row['id']))
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'automatic_correction_failed',?,?)",
                       (row['paper_id'], json.dumps({'correction_id': row['id'], 'reason': reason}), now()))
            changed.append({'lane': 'correction', 'id': row['id'], 'state': 'failed'})
    if report is not None:
        report.setdefault('normalized', []).extend(changed)
    return changed


def run_once(catalog, config, *, stopping=None, maintain_review_cycle=True):
    stopping=stopping or (lambda:False)
    if stopping():return {'state':'stopping'}
    if not enabled(config):
        return {'state':'disabled'}
    from .workflow_recovery import run_once as recover_workflows
    recover_workflows(catalog, config, stopping=stopping,
                      maintain_review_cycle=maintain_review_cycle)
    if stopping():return {'state':'stopping'}
    root = catalog.path.parent
    from .action_inbox import snapshot
    items = snapshot(config)['items']
    from .control import read_record
    previous = read_record(root/'automatic-issue-status.json')
    previous_items = {item['id']: item for item in previous.get('items', [])}
    report = {'updated':time.time(), 'state':'checked', 'interval_seconds':60, 'recovered':[], 'checks':[],
              'items':[{'id':item['id'], 'title':item['title'], 'stage':disposition(item)[0],
                        'handling':'automatic', 'resolution_state':'retained', 'reason':item['action'], 'diagnosis':diagnosis(item)} for item in items]}
    from browser.api import attempt_history__index_attempts as index_attempts
    from browser.api import shared_page_health___uncollected_history as _uncollected_history
    try:
        records, _ = index_attempts(root)
    except (OSError, ValueError) as exc:
        report['state'] = 'evidence_pending'
        report['record_error'] = str(exc)[:500]
        atomic_json(root/'automatic-issue-status.json', report)
        return report
    from browser.api import receipt_history_groups__group_histories as group_histories
    histories = group_histories(items, records, root)
    # Every inbox entry receives a local evidence check. A missing target or an
    # elapsed timeout never grants permission to submit or discard a receipt.
    for item in report['items']:
        key = item['id']
        previous_item = previous_items.get(key, {})
        stamp = previous_item.get('first_observed_at', report['updated'])
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= stamp <= report['updated']:
            stamp = report['updated']
        item['first_observed_at'] = stamp
        item['retained_observation_age_seconds'] = report['updated'] - stamp
        history = histories[key]
        item['receipt_count'] = len(history)
        item['uncollected_receipts'] = sum(len(_uncollected_history(t,history))
            for t in {r.get('target_id') for r in history if r.get('target_id')})
        item['evidence_checked_at'] = time.time()
        item['evidence_scope'] = 'local_receipt_history'
        item['browser_checked'] = False
    with catalog.connect() as db:
        jobs = [dict(row) for row in db.execute("SELECT * FROM web_card_jobs WHERE state='needs_inspection' AND error IN (?,?)", (PREPARATION_BLOCK,ARCHIVE_BLOCK))]
    from .workflow_priority import seed_first
    with catalog.connect() as db:
        jobs=seed_first(db,jobs)
    for job in jobs:
        try:
            result = (recover_archived_dispatch if job['error']==ARCHIVE_BLOCK else recover_preparation)(catalog, job, config)
            if result:report['recovered'].append(result)
        except (OSError, ValueError, KeyError) as exc:
            report['checks'].append({'paper_id':job['paper_id'],'state':'evidence_pending','reason':str(exc)[:500]})
    # Complete ambiguous reports may also contain grounded card defects. Route
    # bounded source-only regeneration without converting the verdict to pass.
    from correction.api import card_correction_queue__enabled as corrections_enabled, card_correction_queue__partial_rework_allowed as partial_rework_allowed, card_correction_queue__enqueue_review as enqueue_review
    if corrections_enabled(config) and config.get('card_correction',{}).get('partial_ambiguous_rework') is True:
        with catalog.connect() as db:
            reviews=[dict(r) for r in db.execute("SELECT r.*,a.queued_at,a.sequence FROM card_review_jobs r LEFT JOIN shared_workflow_arrivals a ON a.lane='review' AND a.job_id=r.id WHERE r.state='needs_user' AND json_extract(r.result,'$.full_source_checked')=1 AND NOT EXISTS(SELECT 1 FROM card_correction_jobs c WHERE c.review_id=r.id)")]
            from .workflow_priority import sort as sort_articles
            reviews=sort_articles(db,reviews,config)
        for job in reviews:
            try:
                from correction.api import card_correction_queue___collected_review as _collected_review
                data,result,_=_collected_review(catalog,job,config)
                if not partial_rework_allowed(data,result,job['folder']):continue
                correction=enqueue_review(catalog,job,config,data,result)
                if correction['state']=='queued':
                    from review.api import card_review_queue__update as update
                    update(catalog,job['id'],'correction_queued','完整核验仍有歧义；有原文证据的问题已进入有限修正，歧义继续保留',
                        {**result,'correction_id':correction['id'],'original_verdict_preserved':True})
                    report['recovered'].append({'paper_id':job['paper_id'],'correction_id':correction['id'],'kind':'partial_ambiguous_rework'})
                    break
            except (OSError,ValueError,KeyError) as exc:
                report['checks'].append({'paper_id':job['paper_id'],'state':'evidence_pending','reason':str(exc)[:500]})
    # Existing repair enforces original collection, new inputs, two-pass maximum,
    # human protection and pause. Unchanged deterministic inputs are checked once.
    from review.api import card_review_queue__enabled as reviews_enabled
    if reviews_enabled(config):
        with catalog.connect() as db:
            interrupted = [dict(row) for row in db.execute(
                "SELECT * FROM card_review_jobs WHERE state='needs_user' AND error='database is locked' AND result='{}'")]
        with catalog.connect() as db:
            interrupted=seed_first(db,interrupted)
        for job in interrupted:
            try:
                recovery = recover_review_preparation_lock(catalog, job, config)
                if recovery:report['recovered'].append(recovery)
            except (OSError, ValueError, KeyError) as exc:
                report['checks'].append({'paper_id':job['paper_id'], 'state':'evidence_pending', 'reason':str(exc)[:500]})
        ledger_path = root/'automatic-review-material-checks.json'
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        with catalog.connect() as db:
            reviews = [dict(row) for row in db.execute("SELECT * FROM card_review_jobs WHERE state='needs_user' AND json_extract(result,'$.full_source_checked')=0 ORDER BY updated")]
        attempted = 0
        preparation_version=review_preparation_fingerprint()
        with catalog.connect() as db:
            reviews=seed_first(db,reviews)
        for job in reviews:
            assessment = json.loads(job['result'])
            if assessment.get('verdict') == 'cannot_evaluate' and not assessment.get('missing_inputs'):
                continue
            folder = Path(job['folder']);manifest = root/'card_review_supplements'/job['paper_id']/'manifest.json'
            evidence = [job['card_sha256'],job['source_sha256'],job['result'],preparation_version]
            for path in [folder/'packet.json',folder/'attempt.json',manifest]:
                evidence.append(hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'missing')
            key = hashlib.sha256(json.dumps(evidence).encode()).hexdigest()
            previous = ledger.get(key, {})
            if previous:
                if previous.get('state') != 'runtime_wait' or previous.get('next_retry_at', 0) > time.time() or previous.get('attempts', 0) >= 3:
                    continue
            if attempted >= 1:break
            attempted += 1
            try:
                from review.api import card_review_repair__repair as repair
                result = repair(catalog, job, config)
                report['recovered'].append(result);ledger[key]={'state':'repaired','result':result,'preparation_version':preparation_version}
            except (OSError, ValueError, KeyError) as exc:
                ledger[key]={'state':'runtime_wait' if isinstance(exc, PermissionError) else 'retained',
                             'reason':str(exc)[:500], 'attempts':previous.get('attempts',0)+1,
                             'next_retry_at':time.time()+300,'preparation_version':preparation_version}

            atomic_json(ledger_path,ledger)
    from collections import Counter
    report['retained_over_6h'] = sum(item.get('retained_observation_age_seconds', 0) >= 21600 for item in report['items'])
    report['retained_over_24h'] = sum(item.get('retained_observation_age_seconds', 0) >= 86400 for item in report['items'])
    report['problem_counts'] = dict(Counter(item['diagnosis']['kind'] for item in report['items']))
    report['handling_counts'] = dict(Counter(item['diagnosis']['state'] for item in report['items']))
    release_proven_presend_claims(catalog, config, report)
    requeue_proven_unsent_review(catalog, config, report)
    normalize_needs_user(catalog, config, report)
    atomic_json(root/'automatic-issue-status.json', report)
    return report
