"""Guarded retries; manual-root pre-click technical failures have a separate budget."""
import argparse
import fcntl
import hashlib
import json
import re
import time
import math
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit
from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config, catalog__now as now
from core.api import services__atomic_json as atomic_json
from .web_card_inputs import digest, parse_card, check_material_delivery, MaterialDeliveryError

PRE_SEND = re.compile(r'附件上传失败|网页文件上传入口已禁用|附件入口暂未就绪|附件仍在上传|未点击发送|后台发送按钮不可用')
UNCERTAIN = re.compile(r'回执|会话URL|不确定|可能已发送|消息不唯一')


def known_unsent(attempt):
    if attempt.get('state') == 'deferred':
        return attempt.get('send_click_started') is False
    if attempt.get('state') != 'not_sent' or attempt.get('send_click_started') is True:
        return False
    if attempt.get('send_click_started') is False:
        return True
    error = attempt.get('error', '')
    return bool(PRE_SEND.search(error)) and not UNCERTAIN.search(error)


def finished_response(path, attempt, packet):
    """Only a persisted complete response bound to actual sent material qualifies."""
    if attempt.get('state') != 'response_saved':
        raise ValueError('原请求没有完整收取证据')
    raw, prompt = path.parent/'response-raw.txt', path.parent/'prompt-actual.txt'
    if not attempt.get('raw_sha256') or digest(raw) != attempt['raw_sha256']:
        raise ValueError('原回答指纹变化')
    if not raw.read_text().strip():
        raise ValueError('原回答为空占位，未完整收取，不自动重试')
    if not attempt.get('actual_prompt_sha256') or digest(prompt) != attempt['actual_prompt_sha256']:
        raise ValueError('实际发送提示指纹缺失或变化')
    if digest(prompt) != packet['input_hashes']['prompt.txt']:
        # The ZIP instruction is a recorded transport wrapper, never an old answer.
        from browser.api import web_upload_bundle__ZIP_INSTRUCTION as ZIP_INSTRUCTION
        original=path.parent.parent/'prompt.txt';bundle=attempt.get('upload_bundle')
        actual=prompt.read_text()
        if original.exists():original_text=original.read_text()
        elif actual.endswith(ZIP_INSTRUCTION):original_text=actual[:-len(ZIP_INSTRUCTION)]
        else:raise ValueError('归档提示缺失且无完整原传输包装')
        if (hashlib.sha256(original_text.encode()).hexdigest()!=packet['input_hashes']['prompt.txt'] or
                actual != original_text+ZIP_INSTRUCTION or not isinstance(bundle,dict)):
            raise ValueError('实际发送提示与冻结输入不同')
        if not bundle.get('zip_path') or not bundle.get('zip_sha256') or digest(bundle['zip_path']) != bundle['zip_sha256']:
            raise ValueError('原上传ZIP指纹缺失或变化')
    if attempt.get('inputs') != packet['input_hashes']:
        raise ValueError('原回答与当前冻结材料不一致')
    parsed = urlsplit(attempt.get('conversation_url', ''))
    if parsed.scheme != 'https' or parsed.hostname not in ('chatgpt.com', 'chat.qwen.ai', 'www.qianwen.com', 'qianwen.com') or not __import__('re').fullmatch(r'/c/[A-Za-z0-9_-]+/?',parsed.path) or parsed.username or parsed.password or parsed.port not in (None,443) or 'local-chatgpt' in parsed.path:
        raise ValueError('原回答缺少正式会话归属')
    return raw.read_text()


def cooperative_digest(path, checkpoint):
    """Hash every byte while allowing the original browser loop to run."""
    path=Path(path);before=path.stat();sha=hashlib.sha256();due=time.monotonic()+.25
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):
            sha.update(block)
            if time.monotonic()>=due:
                checkpoint();due=time.monotonic()+.25
    checkpoint()
    after=path.stat()
    fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
    if any(getattr(before,k)!=getattr(after,k) for k in fields):raise ValueError('冻结文件读取期间变化：'+str(path))
    return sha.hexdigest()


def frozen_inputs(folder, packet, paper, *, checkpoint=None):
    hash_file=digest if checkpoint is None else lambda path:cooperative_digest(path,checkpoint)
    if hash_file(paper['asset_path']) != packet['source_original_sha256']:
        raise ValueError('原文已变化，不自动重试')
    for name, expected in packet['input_hashes'].items():
        if hash_file(folder/name) != expected:
            raise ValueError('冻结输入已变化：'+name)
    for index, item in enumerate(packet['page_manifest'], 1):
        image = folder/'pages'/f'P{index:03d}.png'
        if item['source_page'] != index or hash_file(image) != item['sha256']:
            raise ValueError('页图指纹或页码变化')


def eligible(catalog, job, config):
    paper = catalog.get(job['paper_id'])
    from .web_card_rework import authorization
    rework = authorization(job, paper)
    if any(paper['metadata'].get(k) for k in ('identity_review_required', 'version_review_required', 'out_of_scope')):
        raise ValueError('身份/版本/范围待人工核对')
    with catalog.connect() as db:
        human = db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'", (paper['id'],)).fetchone()
    if not rework and (paper['decision'] != 'unreviewed' or paper.get('card_path') or human or (Path(config['studio_library_root'])/paper['id']/'card.json').exists()):
        raise ValueError('已有卡片或人工决定，禁止重试覆盖')
    return paper


def _root_technical_retry(db, job, paper, records):
    """Only exact registered roots and explicit pre-click receipts bypass the cap."""
    if (not records or paper['metadata'].get('user_seed_disabled') or
            not all(a.get('state') in ('not_sent', 'deferred') and
                    a.get('send_click_started') is False for _, a in records)):
        return False
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='manual_seed_roots'").fetchone():
        return False
    return bool(db.execute('SELECT 1 FROM manual_seed_roots WHERE paper_id=? AND input_hash=?',
                           (job['paper_id'], job['source_sha256'])).fetchone())


def reset_unsent_page(pid, records, pages, entries, page_guard=None):
    """A draft/blank page is usable only together with persisted pre-click proof."""
    from browser.api import web_card_transport__require_no_verification as require_no_verification
    from web_gpt.core import STOP_BUTTON
    from browser.api import web_card_pool__USER as USER
    verified=set()
    for _, attempt in records:
        if not known_unsent(attempt) or not attempt.get('target_id'):
            continue
        tid = attempt['target_id']
        if pages is None:
            if attempt.get('tab_cleanup') not in ('closed_error_page', 'already_closed'):
                raise ValueError('等待原页实时核对')
            verified.add(tid)
            continue
        page = pages.get(tid)
        entry = entries.get(tid, {})
        # A page reused for another paper must be left alone.
        if entry.get('active_paper_id') not in (None, pid):
            continue
        if page is None:
            continue  # Pre-click proof, not page absence, authorizes the retry.
        require_no_verification(page)
        stop = page.locator(STOP_BUTTON)
        if page.url.rstrip('/') != 'https://chatgpt.com' or page.locator(USER).count() or any(stop.nth(i).is_visible() for i in range(stop.count())):
            raise ValueError('原页有消息/生成/会话变化，保留待核对')
        from web_gpt.submission import submission_lock
        with submission_lock(timeout=10):
            if page_guard:page_guard(tid)
            # Recheck under the same shared lock as upload/send.
            require_no_verification(page)
            if page.url.rstrip('/') != 'https://chatgpt.com' or page.locator(USER).count() or any(stop.nth(i).is_visible() for i in range(stop.count())):
                raise ValueError('原页在重试核对期间变化')
            page.goto('https://chatgpt.com/', wait_until='domcontentloaded', timeout=30000)
            from browser.api import shared_pool_store__mark_verified_blank as mark_verified_blank
            mark_verified_blank(entries.setdefault(tid,{}))
            entries.setdefault(tid,{}).update(state='ready_blank', origin='verified_unsent_retry', adopted=time.time())
            verified.add(tid)
    return verified


def release_archived_unsent_lease(db,config,job,records,verified_targets,history):
    """Release the exact failed lease inside the successful retry transaction.

    Source/input/old-page checks and retry CAS precede this helper. A moved,
    active or unknown original page cannot gain new authority from a queued row.
    The archived pre-click receipt remains intact; this only removes its lease.
    """
    from browser.api import shared_page_backlog__enabled as backlog_enabled, shared_page_backlog__remove_binding as remove_binding
    from correction.api import card_correction_queue__web_job_kind as web_job_kind
    if not backlog_enabled(config) or not db.execute("SELECT 1 FROM sqlite_master WHERE name='shared_page_backlog'").fetchone():return []
    lane=web_job_kind(job)
    jid=json.loads(job['selection']).get('rework',{}).get('correction_id') if lane=='correction' else job['paper_id']
    if not jid:return []
    released=[]
    for path,attempt in records:
        tid=attempt.get('target_id')
        if (attempt.get('state')!='not_sent' or attempt.get('send_click_started') is not False
                or tid not in (verified_targets or ())):continue
        archived=history/path.parent.name/'attempt.json'
        if not archived.is_file() or json.loads(archived.read_text())!=attempt:
            raise ValueError('原未发送回执没有完整归档，不释放页面领取')
        match=db.execute("SELECT 1 FROM shared_page_backlog WHERE lane=? AND job_id=? AND paper_id=? AND target_id=? AND state='claimed'",
                         (lane,jid,job['paper_id'],tid)).fetchone()
        if match and remove_binding(db,lane,jid,tid,expected_state='claimed'):
            released.append({'lane':lane,'job_id':jid,'target_id':tid})
    return released



def release_verified_unsent_lease(catalog,config,job,records,verified_targets):
    """Archive exact pre-click receipts and free leases without granting a retry."""
    from browser.api import shared_page_backlog__enabled as backlog_enabled, shared_page_backlog__remove_binding as remove_binding
    from correction.api import card_correction_queue__web_job_kind as web_job_kind
    if not backlog_enabled(config) or not verified_targets:return []
    lane=web_job_kind(job)
    jid=json.loads(job['selection']).get('rework',{}).get('correction_id') if lane=='correction' else job['paper_id']
    if not jid:return []
    released=[]
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='shared_page_backlog'").fetchone():return []
        for path,a in records:
            tid=a.get('target_id')
            if a.get('state')!='not_sent' or a.get('send_click_started') is not False or tid not in verified_targets:continue
            if json.loads(path.read_text())!=a:raise ValueError('原未发送回执变化，不释放租约')
            receipt=path.parent/'page-lease-release.json'
            if receipt.exists() and json.loads(receipt.read_text())['attempt']!=a:raise ValueError('原租约释放归档变化')
            if not receipt.exists():atomic_json(receipt,{'attempt':a,'target_id':tid,'verified_at':time.time(),'requeue_authorized':False})
            if remove_binding(db,lane,jid,tid,expected_state='claimed'):
                released.append({'lane':lane,'job_id':jid,'target_id':tid})
    return released


def relocate_saved_pool_paths(entries, records, history):
    """Update only exact original receipts after their directories are archived.

    The exclusive owner persists these entries before its next dispatch. This
    changes a local path, never page state, ownership, retry counts or content.
    """
    moved = []
    for ledger_path, attempt in records:
        if attempt.get('state') != 'response_saved':
            continue
        old = ledger_path.parent / 'response-raw.txt'
        new = history / ledger_path.parent.name / 'response-raw.txt'
        if not new.is_file() or digest(new) != attempt.get('raw_sha256'):
            continue
        entry = entries.get(attempt.get('target_id'), {})
        for receipt in (entry, entry.get('previous_saved_response', {})):
            if (receipt.get('raw_path') and Path(receipt['raw_path']).resolve() == old.resolve()
                    and receipt.get('raw_sha256') == attempt.get('raw_sha256')
                    and receipt.get('conversation_url') == attempt.get('conversation_url')):
                receipt['raw_path'] = str(new.resolve())
                moved.append({'target_id': attempt['target_id'], 'old_path': str(old.resolve()),
                              'raw_path': str(new.resolve()), 'raw_sha256': attempt['raw_sha256']})
    return moved


def _recover_archive(catalog, job, folder, ledger_path, ledger):
    """Finish the ledger after commit, or restore proven receipts after rollback.

    No new request is sent; the consumed retry count never decreases.
    Old prepared ledgers without exact move fingerprints remain blocked.
    """
    moves=ledger.get('archive_moves')
    if not isinstance(moves,list) or not moves:raise ValueError('旧归档缺少逐项指纹；保留待核对')
    from core.api import archive_paths__move_with_links
    for move in moves:
        original=Path(move['original']);archived=Path(move['archived'])
        if not original.is_relative_to(folder) or not archived.is_relative_to(folder/'history'):
            raise ValueError('归档恢复路径不属于原任务')
        if archived.with_name('.'+archived.name+'.links-move.json').exists():
            archive_paths__move_with_links(original,archived)
        if original.with_name('.'+original.name+'.links-move.json').exists():
            archive_paths__move_with_links(archived,original)
    with catalog.connect() as db:
        current=db.execute('SELECT state,retry_at FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
    if current and current['state']=='queued' and current['retry_at']==ledger.get('retry_at'):
        ledger['state']='scheduled';atomic_json(ledger_path,ledger);return
    for move in moves:
        original=Path(move['original']);archived=Path(move['archived'])
        if not original.is_relative_to(folder) or not archived.is_relative_to(folder/'history'):
            raise ValueError('归档恢复路径不属于原任务')
        if original.exists() and archived.exists():raise ValueError('归档恢复路径冲突；不覆盖')
        receipt=(original if original.exists() else archived)/'attempt.json'
        if digest(receipt)!=move['attempt_sha256']:raise ValueError('归档恢复回执指纹变化')
    for move in moves:
        original=Path(move['original']);archived=Path(move['archived'])
        if archived.exists():archive_paths__move_with_links(archived,original)
    ledger['state']='archive_rolled_back';ledger['recovered_at']=now()
    atomic_json(ledger_path,ledger)


def run_once(config, *, pages=None, entries=None, router=None, clock=time.time, page_guard=None,
             checkpoint=None, monotonic=time.monotonic):
    """Called by the exclusive keeper; never sends, switches providers or unpauses."""
    policy = config.get('web_cards', {}).get('retry', {})
    from .web_card_service import enabled, publish_saved
    root = Path(config['catalog_path']).parent
    report = {'updated': now(), 'requeued': [], 'published': [], 'released_page_leases': [], 'blocked': [], 'enabled': policy.get('enabled', False)}
    if not policy.get('enabled') or not enabled(config):
        report['state'] = 'paused';return report
    from browser.api import web_media_storage__require_config_storage as require_config_storage
    require_config_storage(config)
    catalog = Catalog(config['catalog_path'])
    maximum = min(2, max(0, int(policy.get('max_retries', 2))))
    limit = min(10, max(1, int(policy.get('batch_size', 3))))
    budget=policy.get('inspection_budget_seconds',5.0)
    if type(budget) not in (int,float) or not math.isfinite(budget) or not 0<budget<=10:
        raise ValueError('重试巡检时间预算须为0至10秒之间的有限正数')
    completed = 0
    entries = entries if entries is not None else {}
    with (root/'web-card-retry.lock').open('a') as lock:
        try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:return report
        from . import web_card_queue as queue
        all_jobs=queue.jobs(catalog)
        from core.api import workflow_priority__seed_first as seed_first
        with catalog.connect() as db:
            all_jobs=seed_first(db,all_jobs)
        for recovered_job in all_jobs:
            recovery_folder=root/'web_cards'/recovered_job['paper_id']
            recovery_ledger=recovery_folder/'retry.json'
            if recovered_job['state']=='queued' and recovery_ledger.exists():
                recovery=json.loads(recovery_ledger.read_text())
                if recovery.get('state') in ('archive_in_progress','archive_completed','database_committed'):
                    try:_recover_archive(catalog,recovered_job,recovery_folder,recovery_ledger,recovery)
                    except (OSError,ValueError,KeyError) as exc:report['blocked'].append({'paper_id':recovered_job['paper_id'],'reason':str(exc)[:250]})
        candidates=[job for job in reversed(all_jobs) if job['state'] in ('failed','needs_inspection')]
        cursor_path=root/'web-card-retry-scan.json'
        try:cursor=json.loads(cursor_path.read_text()).get('next_paper_id')
        except FileNotFoundError:cursor=None
        except (OSError,ValueError,AttributeError) as exc:
            # This derived position grants no execution authority. Reinspect
            # from the start using unchanged receipt/retry/publication gates.
            report['scan_cursor_error']=str(exc)[:300];cursor=None
        start=next((i for i,j in enumerate(candidates) if j['paper_id']==cursor),0)
        candidates=candidates[start:]+candidates[:start]
        # Cursor fairness stays within each class; retries never lose seed priority.
        with catalog.connect() as db:
            candidates=seed_first(db,candidates)
        started=monotonic();inspected=0;next_id=None
        for index,job in enumerate(candidates):
            if inspected and monotonic()-started>=budget:break
            inspected+=1;next_id=candidates[(index+1)%len(candidates)]['paper_id']
            pid = job['paper_id'];folder = root/'web_cards'/pid;ledger_path = folder/'retry.json'
            try:
                if checkpoint:checkpoint()
                if ledger_path.exists():
                    pending=json.loads(ledger_path.read_text())
                    if pending.get('state') in ('prepared','archive_in_progress','archive_completed','database_committed'):
                        _recover_archive(catalog,job,folder,ledger_path,pending)
                publication=folder/'publication-intent.json';pending_publication=None
                if publication.exists():
                    intent=json.loads(publication.read_text())
                    if intent.get('state')!='committed':
                        if intent.get('state')!='files_written':raise ValueError('发布中断待核对；禁止重新生成')
                        pending_publication=intent
                records = [(p, json.loads(p.read_text())) for p in sorted(folder.glob('*/attempt.json'))]
                if not records:raise ValueError('没有原请求证据，不重试准备失败')
                from browser.api import attempt_history__submission_history as submission_history
                from .web_card_rework import archived_receipts
                # A journal recovery only reconciles its unique saved local reply;
                # it never grants another submission or rewrites archived receipts.
                archive_needed=bool(json.loads(job['selection']).get('manual_seed_trial') or list((folder/'history').glob('source-review-*')))
                if not pending_publication:
                    archived=archived_receipts(catalog,job) if archive_needed else []
                    historical=submission_history(folder,exclude_paths=[p for p,_ in records]+archived)
                    if not historical.allowed:
                        raise ValueError('历史请求未有完整且获准的结束证据，只核对原会话')
                if any(a.get('state') != 'response_saved' and not known_unsent(a) for _, a in records):
                    raise ValueError('已发送或回执不确定，只核对原会话')
                paper = catalog.get(pid) if pending_publication else eligible(catalog, job, config)
                ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'external_retries': 0, 'local_checks': {}}
                packet = json.loads((folder/'packet.json').read_text());frozen_inputs(folder, packet, paper,checkpoint=checkpoint)
                if job.get('source_sha256') and job['source_sha256'] != packet['source_original_sha256']:
                    raise ValueError('任务原文指纹与冻结输入不一致')
                saved = [(p, a, finished_response(p, a, packet)) for p, a in records if a.get('state') == 'response_saved']
                if pending_publication:
                    matching=[(p,a,raw) for p,a,raw in saved if a.get('raw_sha256')==pending_publication.get('raw_sha256') and a.get('provider')=='chatgpt']
                    if len(matching)!=1:raise ValueError('中断发布缺少唯一原回答回执；禁止重新生成')
                    _,a,raw=matching[0];publish_saved(config,job,raw,a,'chatgpt')
                    with catalog.connect() as db:
                        reconciled=db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
                    if not reconciled or reconciled['state']!='completed':raise ValueError('中断发布保护未解除；原回答与文件保留')
                    report['published'].append(pid);completed+=1
                    if completed>=limit:break
                    continue

                # A model-reported delivery failure is not a JSON failure and never
                # acquires authority to resubmit the same frozen input.
                for _, _, raw in saved:
                    try:
                        from .web_card_json import normalize
                        normalized_delivery=normalize(raw)
                        try:delivery_card=json.loads(normalized_delivery)
                        except (ValueError,TypeError):delivery_card=None
                        check_material_delivery(raw,delivery_card)
                    except MaterialDeliveryError as exc:
                        ledger.update(state='delivery_failed',error=str(exc),input_hashes=packet['input_hashes'])
                        atomic_json(ledger_path,ledger)
                        if job['state']!='needs_inspection' or job['error']!=str(exc):
                            queue.update(catalog,pid,state='needs_inspection',error=str(exc))
                        raise
                # Local parsing runs once per raw-answer/material/normalizer fingerprint.
                for p, attempt, raw in saved:
                    if attempt.get('provider') != 'chatgpt':continue
                    from .web_card_json import normalize
                    loaded_revision=getattr(parse_card,'parser_revision','legacy')+':'+getattr(normalize,'syntax_revision','legacy')
                    key = hashlib.sha256((attempt['raw_sha256']+json.dumps(packet['input_hashes'], sort_keys=True)+digest(Path(__file__).with_name('web_card_json.py'))+digest(Path(__file__).with_name('web_card_inputs.py'))+loaded_revision).encode()).hexdigest()
                    previous=ledger.setdefault('local_checks', {}).get(key)
                    if previous:
                        if previous.get('state') in ('blocked','publishing','published'):
                            raise ValueError(previous.get('error') or '原发布回执需核对；不重新生成相同输入')
                        continue
                    normalized = normalize(raw)
                    try:parse_card(normalized, packet)
                    except (ValueError, TypeError, AttributeError) as exc:
                        ledger['local_checks'][key] = {'state': 'failed', 'error': str(exc)[:1200],
                            'raw_sha256':attempt['raw_sha256'],'checked_at':now()}
                        ledger['validation_error']=str(exc)[:1200]
                        atomic_json(ledger_path, ledger);continue
                    if normalized != raw:
                        (p.parent/'response-retry-normalized.txt').write_text(normalized)
                        attempt = {**attempt, 'normalization': {'kind': 'json_syntax_only', 'normalized_sha256': digest(p.parent/'response-retry-normalized.txt')}}
                    # Record the intent first so a failed publication is not retried forever.
                    ledger['local_checks'][key] = {'state': 'publishing'};atomic_json(ledger_path, ledger)
                    publish_saved(config, job, normalized, attempt, 'chatgpt')
                    with catalog.connect() as db:
                        published=db.execute('SELECT state,error FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
                    if published is None or published['state']!='completed':
                        actual=published['state'] if published else 'missing'
                        reason=(published['error'] if published else '') or '原发布回执未完成，保留候选与原回答'
                        ledger['local_checks'][key]={'state':'blocked','job_state':actual,'error':reason[:700]}
                        atomic_json(ledger_path,ledger)
                        raise ValueError(reason)
                    ledger['local_checks'][key] = {'state': 'published'};atomic_json(ledger_path, ledger)
                    report['published'].append(pid);completed += 1;break
                if pid in report['published']:
                    if completed >= limit:break
                    continue
                with catalog.connect() as db:
                    technical_retry = _root_technical_retry(db, job, paper, records)
                if not technical_retry and ledger.get('external_retries', 0) >= maximum:
                    if pages is not None and router is not None and router.choose()=='chatgpt' and enabled(config):
                        verified=reset_unsent_page(pid,records,pages,entries,page_guard=page_guard)
                        freed=release_verified_unsent_lease(catalog,config,job,records,verified)
                        if freed:report.setdefault('released_page_leases',[]).extend(freed)
                    raise ValueError('自动重试次数已用完')
                # Old failed replies remain evidence, never new generation inputs.
                for _, attempt in records:
                    if known_unsent(attempt) and attempt.get('inputs') != packet['input_hashes']:
                        raise ValueError('未发送记录与当前材料不一致')
                if router is None or router.choose() != 'chatgpt':raise ValueError('等待GPT通道恢复，暂停/额度优先')
                if not enabled(config):raise ValueError('用户已暂停')
                verified_targets=reset_unsent_page(pid, records, pages, entries, page_guard=page_guard)
                counter = 'technical_retries' if technical_retry else 'external_retries'
                previous_count = ledger.get(counter, 0)
                if type(previous_count) is not int or previous_count < 0:
                    raise ValueError('原重试计数无效，保留待核对')
                count = previous_count+1
                multiplier = (1, 3, 12)[min(count-1, 2)] if technical_retry else 3**(count-1)
                delay = max(60, int(policy.get('backoff_seconds', 300)))*multiplier
                reason = '已完整收取但结构未通过' if saved else '确认发送前失败'
                detail = ledger.get('validation_error','') if saved else '；'.join(
                    a.get('error','') for _,a in records if known_unsent(a))[:1200]
                retry_kind = 'seed-technical-retry' if technical_retry else 'automatic-retry'
                history = folder/'history'/f'{retry_kind}-{count}-{time.time_ns()}'
                archive_moves=[{'original':str(p.parent),'archived':str(history/p.parent.name),'attempt_sha256':digest(p)} for p,_ in records]
                from core.api import seed_focus__capture as capture_seed
                with catalog.connect() as evidence_db:
                    is_seed=evidence_db.execute('SELECT 1 FROM manual_seed_roots WHERE paper_id=?',(job['paper_id'],)).fetchone() if evidence_db.execute("SELECT 1 FROM sqlite_master WHERE name='manual_seed_roots'").fetchone() else None
                if is_seed:capture_seed(config,job['paper_id'],'before_authorized_retry')
                # CAS protects completion/human changes from a stale retry scan.
                with catalog.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current = db.execute('SELECT state,updated FROM web_card_jobs WHERE paper_id=?', (pid,)).fetchone()
                    if not current or tuple(current) != (job['state'], job['updated']):raise ValueError('任务已变化，不重新排队')
                    fresh = eligible(catalog, job, config)
                    if technical_retry and not _root_technical_retry(db, job, fresh, records):
                        raise ValueError('根种子身份或原文绑定变化，不增加技术重试')
                    if current['state'] not in ('failed','needs_inspection'):
                        raise ValueError('仅允许证据核对完成的失败任务有限重试')
                    if not submission_history(folder,exclude_paths=[p for p,_ in records]+(archived_receipts(catalog,job) if archive_needed else [])).allowed:
                        raise ValueError('历史请求证据在重试前变化，不重新排队')
                    for p, attempt in records:
                        if json.loads(p.read_text()) != attempt:raise ValueError('原请求证据在核对期间变化')
                        if attempt.get('state') == 'response_saved':finished_response(p, attempt, packet)
                    frozen_inputs(folder, packet, paper)
                    ledger.update({counter: count})
                    ledger.update(state='archive_in_progress', retry_at=clock()+delay,
                                  reason=reason, failure_detail=detail, history=str(history), input_hashes=packet['input_hashes'],archive_moves=archive_moves)
                    atomic_json(ledger_path, ledger)
                    history.mkdir(parents=True, exist_ok=False)
                    from core.api import archive_paths__move_with_links
                    for p, _ in records:archive_paths__move_with_links(p.parent,history/p.parent.name)
                    ledger['state']='archive_completed';atomic_json(ledger_path,ledger)
                    relocated = relocate_saved_pool_paths(entries, records, history)
                    label = '种子技术重试 '+str(count) if technical_retry else '自动重试 '+str(count)+'/'+str(maximum)
                    db.execute("UPDATE web_card_jobs SET state='queued',retry_at=?,error=?,updated=? WHERE paper_id=?", (ledger['retry_at'], label+'：'+reason+('；'+detail[:900] if detail else ''), now(), pid))
                    released=release_archived_unsent_lease(db,config,job,records,verified_targets,history)
                ledger['state'] = 'scheduled';atomic_json(ledger_path, ledger)
                catalog.event(pid, 'web_card_retry_scheduled', {'attempt': count, 'counter': counter, 'reason': reason, 'history': str(history), 'retry_at': ledger['retry_at']})
                report['requeued'].append(pid);completed += 1
                if relocated:report.setdefault('relocated_saved_paths', []).extend(relocated)
                if released:report.setdefault('released_page_leases',[]).extend(released)
                if completed >= limit:break
            except Exception as exc:
                report['blocked'].append({'paper_id': pid, 'reason': str(exc)[:250]})
        report['state'] = 'checked'
        report.update(inspected=inspected,candidate_count=len(candidates),scan_elapsed_seconds=monotonic()-started,
                      scan_budget_seconds=budget,next_paper_id=next_id)
        atomic_json(cursor_path,{'next_paper_id':next_id,'updated':time.time()})
        atomic_json(root/'web-card-retry-status.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--config');args = parser.parse_args()
    config = load_config(args.config)
    # Standalone use must hold the same lock as the keeper, preventing two writers.
    with (Path(config['catalog_path']).parent/'web-card-service.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(run_once(config), ensure_ascii=False))
