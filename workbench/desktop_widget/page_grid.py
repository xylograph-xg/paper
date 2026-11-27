"""Read-only 20-page display; the four queue rows are stored assignments."""
import json
import math
import sqlite3
import time
from contextlib import closing
from core.api import paths__WorkspacePath as Path

LANES = {'cards': '制卡', 'review': '核验', 'correction': '修正'}
QUEUE_STATES = {'waiting': '等待准备', 'preparing': '准备材料', 'ready': '材料已就绪'}
PENDING_STATES = {'queued', 'preparing', 'ready'}


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _fresh(stamp, at):
    return type(stamp) in (int, float) and 0 <= at - stamp < 30


def _recent_health(stamp, at):
    # Health runs every 30s and per-page checks may finish between cycles.
    # This display proof follows the existing 60s recovery evidence boundary;
    # current DOM/window evidence still independently requires <30s.
    return type(stamp) in (int,float) and 0 <= at-stamp < 60


def _dict(value):
    return value if isinstance(value, dict) else {}


def _canonical_queue(db, tables, jobs, reviews, corrections):
    """Read the owner's durable mixed assignments, never install its schema."""
    canonical = {'shared_page_backlog', 'shared_page_backlog_meta'}
    if not canonical.intersection(tables):
        return None, {}
    if not canonical <= tables:
        raise ValueError('共享排队登记不完整')
    records = [dict(row) for row in db.execute('SELECT * FROM shared_page_backlog_meta')]
    if len(records) != 1 or records[0].get('id') != 1 or records[0].get('enabled') not in (0, 1):
        raise ValueError('共享排队控制记录待核对')
    meta = records[0]
    if meta['enabled'] == 0:
        return None, meta
    for key, lower, upper in (('low_watermark', 1, 100), ('target_tasks', 1, 100), ('queue_depth', 1, 4)):
        value = meta.get(key)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError('共享排队控制数量待核对')
    if meta['low_watermark'] > meta['target_tasks'] or 'shared_workflow_arrivals' not in tables:
        raise ValueError('共享排队顺序登记待核对')
    for key, upper in (('total_tasks', 100), ('current_tasks', 20), ('queued_tasks', 80), ('eligible_pages', 20)):
        if type(meta.get(key)) is not int or not 0 <= meta[key] <= upper:
            raise ValueError('共享排队库存统计待核对')
    if meta['total_tasks'] != meta['current_tasks'] + meta['queued_tasks']:
        raise ValueError('共享排队库存合计待核对')
    claimed = [dict(row) for row in db.execute("SELECT lane,job_id,paper_id,target_id,assigned FROM shared_page_backlog WHERE state='claimed'")]
    if any(row['lane'] not in LANES or any(not isinstance(row[key], str) or not row[key]
           for key in ('job_id', 'paper_id', 'target_id')) for row in claimed):
        raise ValueError('已领取网页原归属待核对')
    meta['_claimed_bindings'] = claimed
    transports = {row['paper_id']: dict(row) for row in db.execute('SELECT * FROM web_page_queue')} if 'web_page_queue' in tables else {}
    queued = []
    for row in db.execute('''SELECT b.*,a.queued_at,a.sequence,a.basis
            FROM shared_page_backlog b LEFT JOIN shared_workflow_arrivals a USING(lane,job_id)
            WHERE b.state='queued' ORDER BY a.queued_at,a.sequence,b.lane,b.job_id'''):
        binding = dict(row); lane = binding['lane']; paper_id = binding['paper_id']
        if (lane not in LANES or not isinstance(binding['target_id'], str) or not binding['target_id']
                or type(binding['queued_at']) not in (int, float) or not math.isfinite(binding['queued_at'])
                or type(binding['sequence']) is not int or binding['sequence'] < 1):
            raise ValueError('共享排队任务归属或顺序待核对')
        if lane == 'review':
            job = reviews.get(binding['job_id'], {})
            if job.get('paper_id') != paper_id or job.get('state') not in PENDING_STATES:
                continue
            state = 'waiting' if job['state'] == 'queued' else job['state']
            packet_folder = job.get('folder') if isinstance(job.get('folder'), str) else ''
        else:
            job = jobs.get(paper_id, {}); material = transports.get(paper_id, {})
            if (job.get('state') != 'queued' or material.get('state') not in QUEUE_STATES
                    or material.get('target_id') != binding['target_id']):
                continue
            selection = json.loads(job['selection']) if isinstance(job.get('selection'), str) else job.get('selection')
            if not isinstance(selection, dict) or not isinstance(selection.get('rework', {}), dict):
                raise ValueError('共享排队材料类型待核对')
            rework = selection.get('rework', {})
            if lane == 'cards':
                if binding['job_id'] != paper_id or rework.get('correction_id') or rework.get('kind') == 'source_review':
                    continue
            else:
                correction = corrections.get(binding['job_id'], {})
                if (correction.get('paper_id') != paper_id or correction.get('kind') != 'source_rework'
                        or correction.get('state') not in PENDING_STATES
                        or rework.get('correction_id') != binding['job_id']):
                    continue
                job = {**job, 'title': correction.get('title', job.get('title', ''))}
            state = material['state']
        queued.append({**binding, 'state': state, 'title': job.get('title') if isinstance(job.get('title'), str) else '',
                       'retry_at': job.get('retry_at', 0), 'canonical': True,
                       'folder': packet_folder if lane == 'review' else ''})
    return queued, meta


def _catalog(path, config=None, *, at=None):
    """One read transaction, without constructors, migrations or new files."""
    jobs, reviews, corrections, queued, meta = {}, {}, {}, [], {}
    if not path.is_file():
        return jobs, reviews, corrections, queued, meta
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.3)) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'web_card_jobs' in tables:
                jobs = {row['paper_id']: dict(row) for row in db.execute('SELECT * FROM web_card_jobs')}
            if 'card_review_jobs' in tables:
                reviews = {row['id']: dict(row) for row in db.execute('SELECT * FROM card_review_jobs')}
            if 'card_correction_jobs' in tables:
                corrections = {row['id']: dict(row) for row in db.execute('SELECT * FROM card_correction_jobs')}
            queued, meta = _canonical_queue(db, tables, jobs, reviews, corrections)
            if queued is None and {'web_page_queue', 'web_card_jobs'} <= tables:
                queued = [dict(row) for row in db.execute("SELECT q.paper_id,q.target_id,q.state,q.assigned,j.title,j.selection FROM web_page_queue q JOIN web_card_jobs j USING(paper_id) WHERE j.state='queued' AND q.state IN ('waiting','preparing','ready') ORDER BY q.assigned,q.paper_id")]
            queued = queued or []
            from core.api import workflow_priority__sort as sort_articles
            queued = sort_articles(db, queued, config or {})
            # Display only: a recorded upload wait keeps its real slot and shows
            # as not due. This never allocates, moves or releases any material.
            from browser.api import upload_retry_policy__annotate as annotate_uploads
            annotate_uploads(db, queued, config or {}, at=at)
    except (OSError, sqlite3.Error, ValueError, KeyError, IndexError, TypeError) as exc:
        # A partial catalog read cannot provide trustworthy job bindings.
        return {}, {}, {}, [], {'error': '共享排队登记待核对：' + str(exc)}
    return jobs, reviews, corrections, queued, meta


def _selection(value):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def page_grid(root, *, at=None, owner_live=False):
    """Project durable slots and observed activity; never allocate any work."""
    root = Path(root); at = time.time() if at is None else at
    config = _read(root / 'config/first_round.json')
    if _dict(_dict(config.get('web_cards')).get('shared_window')).get('enabled') is not True:
        return None
    catalog = Path(config.get('catalog_path', root / 'data/catalog.sqlite3')); data = catalog.parent
    registry = _read(data / 'shared-gpt-window.json')
    error = ''
    try:
        from browser.api import shared_browser_window__validate_registry as validate_registry
        validate_registry(registry)
        slots = registry['slots']
    except (ValueError, TypeError, AttributeError) as exc:
        error = str(exc)
        slots = [{'slot_id': f'{column:02d}', 'target_id': None} for column in range(1, 21)]
    service = _read(data / 'web-card-service.json')
    observer = _read(data / 'web-page-observer.json')
    status = _read(data / 'shared-gpt-window-status.json')
    pool = _read(data / 'gpt-window-pool.json')
    health_report = _read(data / 'shared-page-health.json')
    same_owner = owner_live and type(service.get('pid')) is int and service['pid'] > 0 and service.get('state') not in ('stopped', 'stopping')
    window_fresh = (same_owner and _fresh(status.get('updated'), at) and status.get('owner_pid') == service['pid']
                    and status.get('window_id') == registry.get('window_id'))
    dispatch_view = _dict(status.get('dispatch'))
    dispatch_protected = ({target for target in dispatch_view.get('protected_targets', []) if isinstance(target, str)}
                          if same_owner and status.get('owner_pid') == service['pid']
                          and isinstance(dispatch_view.get('protected_targets'), list) else set())
    # Window inventory is rewritten during maintenance before dispatch finishes.
    # Keep the same owner's last checked protection through that interval.
    owner_backlog = _dict(service.get('shared_backlog'))
    if same_owner and service.get('shared_window_id') == registry.get('window_id'):
        targets = owner_backlog.get('protected_targets', [])
        if isinstance(targets, list):
            dispatch_protected.update(target for target in targets if isinstance(target, str))
    observer_fresh = (same_owner and observer.get('activity_schema_version') == 1
                      and observer.get('owner_pid') == service['pid'] and _fresh(observer.get('updated'), at))
    pool_fresh = (_fresh(pool.get('observed_at'), at) and pool.get('shared_window_id') == registry.get('window_id'))
    status_slots = status.get('slots') if isinstance(status.get('slots'), list) else []
    live_slots = {slot.get('slot_id'): slot for slot in status_slots if isinstance(slot, dict)}
    observed = {}
    for page in observer.get('pages', []) if isinstance(observer.get('pages'), list) else []:
        tid = page.get('target_id') if isinstance(page, dict) else None
        if tid and tid not in observed:
            observed[tid] = page
        elif tid:
            # Duplicate target observations invalidate that page, not its neighbors.
            observed[tid] = {}
    entries = pool.get('windows', {}) if isinstance(pool.get('windows'), dict) else {}
    jobs, reviews, corrections, queued, backlog = _catalog(catalog, config, at=at)
    from core.api import control__pause_decision as pause_decision
    lane_controls = {lane: pause_decision({**config, 'catalog_path': str(catalog)}, scope,
                        enabled=_dict(config.get(scope)).get('enabled') is True)
                     for lane, scope in (('cards', 'web_cards'), ('review', 'card_review'),
                                         ('correction', 'card_correction'))}

    def bound_current(tid, entry, page, lane):
        if lane == 'review':
            job = reviews.get(entry.get('review_id'), {})
            ledger = Path(job['folder']) / 'attempt.json' if isinstance(job.get('folder'), str) and job['folder'] else None
            job_id = entry.get('review_id')
        else:
            paper_id = entry.get('active_paper_id') or entry.get('paper_id')
            job = jobs.get(paper_id, {})
            ledger = Path(job['folder']) / 'chatgpt/attempt.json' if isinstance(job.get('folder'), str) and job['folder'] else None
            job_id = _dict(_selection(job.get('selection')).get('rework')).get('correction_id') if lane == 'correction' else paper_id
        attempt = _read(ledger) if ledger else {}
        if (attempt.get('target_id') != tid or not attempt.get('actual_prompt_sha256')
                or attempt.get('conversation_url') != page.get('url')):
            return '', None
        if lane == 'review' and attempt.get('review_id') != entry.get('review_id'):
            return '', None
        title = job.get('title') if isinstance(job.get('title'), str) else ''
        url = page.get('url', '')
        review_terminal = lane == 'review' and job.get('state') in (
            'passed', 'corrected', 'correction_queued', 'rework_queued', 'needs_user', 'superseded', 'failed')
        if (attempt.get('state') not in ('submitted', 'submission_started', 'needs_inspection', 'response_saved')
                or not isinstance(url, str) or not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url
                or not (page.get('streaming') is True or page.get('complete') is True
                        and type(page.get('answers')) is int and page['answers'] > 0)
                or review_terminal and page.get('streaming') is not True
                or lane != 'review' and job.get('state') in ('completed', 'protected')):
            return title, None
        identity = {'lane': lane, 'job_id': job_id, 'paper_id': job.get('paper_id')}
        return title, identity

    claimed_by_target = {}
    for claimed in backlog.get('_claimed_bindings', []):
        claimed_by_target.setdefault(claimed['target_id'], []).append(claimed)

    assignments = {}
    for item in queued:
        if item.get('canonical'):
            lane = item['lane']
        else:
            rework = _dict(_selection(item['selection']).get('rework'))
            lane = 'correction' if rework.get('correction_id') or rework.get('kind') == 'source_review' else 'cards'
            if lane == 'correction':
                bound = corrections.get(rework.get('correction_id'), {})
                if (bound.get('paper_id') != item['paper_id'] or bound.get('kind') != 'source_rework'
                        or bound.get('state') not in PENDING_STATES):
                    continue
        decision = lane_controls[lane]
        retry_at = item.get('retry_at', 0)
        cooling = item.get('upload_due', True) is not False
        due = (type(retry_at) in (int, float) and math.isfinite(retry_at) and retry_at <= at) and cooling
        assignments.setdefault(item['target_id'], []).append({**item, 'lane': lane,
                  'runnable': decision.allowed and due, 'control_state': decision.state,
                  'control_reason': decision.reason, 'due': due})

    def cell(column, position, target, status_name='empty', *, lane=None, title='', detail='', observed_now=False):
        label = '当前' if position == 1 else f'排队 {position - 1}'
        tooltip = f'页面 {column:02d} · {label}'
        if lane in LANES:
            tooltip += ' · ' + LANES[lane]
        if detail:
            tooltip += '\n' + detail
        if title:
            tooltip += '\n' + title
        if target:
            tooltip += '\nTarget: ' + target
        return {'id': f'{column:02d}-{position}', 'column': column, 'row': position,
                'targetID': target, 'status': status_name, 'lane': lane, 'title': title,
                'detail': detail, 'tooltip': tooltip, 'observed': observed_now}

    # Display reservation pages first; never change the owner's slot registry,
    # target bindings, or FIFO order within each page.
    reserved = backlog.get('reserved_targets', [])
    if isinstance(reserved, str):
        try:
            reserved = json.loads(reserved)
        except ValueError:
            reserved = []
    reserved = set(reserved) if isinstance(reserved, list) else set()
    fixed_slots = _dict(_dict(config.get('web_cards')).get('shared_window')).get('fixed_lane_slots')
    observed_reservations = owner_backlog.get('lane_reserved_targets') if same_owner and _fresh(owner_backlog.get('last_reconciled'), at) else None
    if isinstance(observed_reservations,dict):
        slot_ids={s.get('target_id'):s['slot_id'] for s in slots}
        fixed_slots={lane:[slot_ids[t] for t in observed_reservations.get(lane,[]) if t in slot_ids] for lane in LANES}
    if isinstance(fixed_slots, dict) and all(isinstance(fixed_slots.get(lane), list) for lane in LANES):
        order = [sid for lane in LANES for sid in fixed_slots[lane]]
        slot_lane = {sid: lane for lane in LANES for sid in fixed_slots[lane]}
        display_slots = sorted(slots, key=lambda slot: order.index(slot['slot_id']) if slot['slot_id'] in order else 20)
    else:
        slot_lane = {}
        display_slots = sorted(slots, key=lambda slot: slot.get('target_id') not in reserved)

    current, waiting = [], {position: [] for position in range(2, 6)}
    queued_count = runnable_count = paused_count = cooldown_count = 0
    for column, slot in enumerate(display_slots, 1):
        tid = slot.get('target_id'); sid = slot['slot_id']; entry = entries.get(tid, {})
        entry = entry if isinstance(entry, dict) else {}
        live_slot = live_slots.get(sid, {})
        matching_slot = live_slot.get('target_id') == tid and bool(tid)
        page = observed.get(tid, {})
        direct_window = 'window_observed' in page
        if direct_window:
            # The resident observer continues this check while uploads hold the
            # submission lock. A failed new check cannot borrow an older result.
            position_known = (observer_fresh and page.get('window_observed') is True
                              and _fresh(page.get('window_checked_at'), at)
                              and type(page.get('window_id')) is int and page['window_id'] >= 0)
            outside = position_known and page['window_id'] != registry.get('window_id')
            present = position_known and page['window_id'] == registry.get('window_id')
            checked = present and _fresh(page.get('checked_at'), at)
        else:
            outside = matching_slot and live_slot.get('state') == 'outside_window'
            present = window_fresh and matching_slot and live_slot.get('state') == 'present'
            checked = present and observer_fresh and pool_fresh and _fresh(page.get('checked_at'), at)
        lane = page.get('kind') if checked and page.get('activity_verified') is True else None
        title, identity = bound_current(tid, entry, page, lane) if lane in LANES else ('', None)
        claimed = claimed_by_target.get(tid, [])
        preparing_claim = None
        if len(claimed)==1:
            binding=claimed[0];job=reviews.get(binding['job_id'],{}) if binding['lane']=='review' else jobs.get(binding['paper_id'],{})
            folder=job.get('folder')
            if not folder and binding['lane'] in ('cards','correction'):
                folder=str(data/'web_cards'/binding['paper_id'])
            attempt=_read(Path(folder)/('attempt.json' if binding['lane']=='review' else 'chatgpt/attempt.json')) if isinstance(folder,str) and folder else {}
            if (job.get('state') in ('preparing','submitting') and entry.get('active_paper_id')==binding['paper_id']
                    and entry.get('kind')==binding['lane'] and attempt.get('target_id')==tid
                    and attempt.get('state')=='ready' and attempt.get('send_click_started') is False
                    and attempt.get('owner_pid')==service.get('pid') and attempt.get('owner_token')==service.get('token')
                    and isinstance(service.get('token'),str) and bool(service['token'])):
                preparing_claim=(binding,job)
        exact_claim = (len(claimed) == 1 and identity is not None and all(
                       identity.get(key) == claimed[0][key] for key in ('lane', 'job_id', 'paper_id')))
        if error:
            item = cell(column, 1, tid, 'unobserved', detail='窗口登记待核对：' + error)
        elif backlog.get('error'):
            item = cell(column, 1, tid, 'unobserved', detail=backlog['error'])
        elif not tid:
            item = cell(column, 1, tid, 'unavailable', detail='槽位尚未绑定网页')
        elif outside:
            item = cell(column, 1, tid, 'protected', detail='原页面已移出专窗；仅保留原请求核对')
        elif (present and observer_fresh and _fresh(page.get('checked_at'),at)
              and page.get('login') is True and page.get('state')=='login_required'):
            item=cell(column,1,tid,'protected',detail=f'等待手动登录 · 原固定槽位 {sid} · 新提交已暂停；保留原页面',observed_now=True)
            item['loginRequired']=True
        elif not checked:
            detail = page.get('window_error') if direct_window else ''
            item = cell(column, 1, tid, 'unobserved', detail=detail or observer.get('error') or '等待同一后台所有者的新鲜网页观测')
        elif preparing_claim and page.get('streaming') is False:
            binding,job=preparing_claim
            item=cell(column,1,tid,'awaiting',lane=binding['lane'],title=job.get('title',''),
                detail='当前后台已领取 · 正在设置模型或上传材料 · 尚未开始发送',observed_now=True)
        elif claimed and not exact_claim:
            age = max(0, int(at-min(float(r.get('assigned',at)) for r in claimed)))
            reason = '仍在生成，材料归属待核对' if page.get('streaming') is True else '领取与当前页面回执归属待核对'
            item = cell(column, 1, tid, 'protected',
                        detail=f'已有领取记录 · {reason} · 分配已持续 {age//60} 分钟 · 后台自动核对，保留原请求', observed_now=True)
        elif lane in LANES and page.get('streaming') is True:
            item = cell(column, 1, tid, 'running', lane=lane, title=title, detail='原会话材料归属已核对 · 正在生成', observed_now=True)
        elif (entry.get('state') in ('needs_inspection', 'verification', 'draft', 'repairing')
              or page.get('state') in ('inspection_error', 'empty_response') or page.get('streaming') is True):
            item = cell(column, 1, tid, 'protected', title=title,
                        detail=page.get('error') or entry.get('error') or '页面受保护；草稿、生成或材料归属尚未核对', observed_now=True)
        elif claimed:
            item = cell(column, 1, tid, 'awaiting', lane=lane, title=title,
                        detail='原领取任务及会话已核对 · 等待完整收取或释放核对', observed_now=True)
        elif tid in dispatch_protected:
            item = cell(column, 1, tid, 'protected', title=title,
                        detail='后台派发检查尚未允许复用；保留原页与回执，等待核对', observed_now=True)
        elif (pool_fresh and entry.get('state') in ('ready', 'ready_blank') or
              entry.get('state') == 'ready_blank' and page.get('state') == 'idle'
              and page.get('streaming') is False and page.get('answers') == 0
              and page.get('url','').rstrip('/') == 'https://chatgpt.com'
              and _recent_health(_dict(_dict(_dict(health_report.get('pages')).get(tid)).get('evidence')).get('checked_at', health_report.get('checked_at')), at)
              and _dict(_dict(health_report.get('pages')).get(tid)).get('health') == 'healthy_blank'):
            item = cell(column, 1, tid, 'idle', detail='已核对为空闲网页', observed_now=True)
        elif entry.get('state') in ('ready','ready_blank') and not pool_fresh:
            item = cell(column, 1, tid, 'unobserved', detail='网页观测正常；页池或健康证据已过期，等待更新', observed_now=True)
        elif lane in LANES:
            item = cell(column, 1, tid, 'awaiting', lane=lane, title=title, detail='原会话已绑定 · 等待完整收取核对', observed_now=True)
        else:
            item = cell(column, 1, tid, 'protected', detail='原任务状态或材料归属待核对', observed_now=True)
        item['slotID'] = sid
        item['tooltip'] = f'固定槽位 {sid} · 显示列 {column:02d}\n' + item['tooltip']
        if sid in slot_lane:
            item['tooltip'] += '\n固定专属：' + LANES[slot_lane[sid]]
        current.append(item)
        assigned = assignments.get(tid, []) if tid and not outside else []
        for position in range(2, 6):
            index = position - 2
            if backlog.get('error'):
                item = cell(column, position, tid, 'unobserved', detail=backlog['error'])
            elif index < len(assigned):
                job = assigned[index]; detail = '已实际分配 · ' + QUEUE_STATES[job['state']]
                if job['control_state'] == 'paused':
                    detail += ' · 该类型已暂停，保留材料/原归属'
                    paused_count += 1
                elif job['control_state'] != 'ready':
                    detail += ' · 暂不派发：' + job['control_reason']
                elif not job['due']:
                    if job.get('upload_due') is False:
                        cooldown_count += 1
                        detail += (' · ' + job['upload_policy_error'] + '，停止新领取'
                                   if job.get('upload_policy_error')
                                   else ' · 上传失败退避中，稍后自动恢复原排名')
                    else:
                        detail += ' · 尚未到重试时间'
                if not present:
                    detail += ' · 网页待实时核对'
                if position == 5 and len(assigned) > 4:
                    detail += f' · 另有 {len(assigned) - 4} 项已分配排队'
                item = cell(column, position, tid, 'queued', lane=job['lane'], title=job['title'], detail=detail, observed_now=present)
                item.update(runnable=job['runnable'], controlState=job['control_state'])
                if job.get('canonical'):
                    item.update(jobID=job['job_id'], queuedAt=job['queued_at'], arrivalSequence=job['sequence'])
                queued_count += 1
                runnable_count += int(job['runnable'])
            else:
                item = cell(column, position, tid, detail='没有已分配排队材料')
            item['slotID'] = sid
            item['tooltip'] = f'固定槽位 {sid} · 显示列 {column:02d}\n' + item['tooltip']
            if sid in slot_lane:
                item['tooltip'] += '\n固定专属：' + LANES[slot_lane[sid]]
            waiting[position].append(item)
    current_count = sum(item['status'] in ('running', 'awaiting') for item in current)
    legend = ('预留制卡%d列、核验%d列、修正%d列，其余共享。' % tuple(len(fixed_slots[lane]) for lane in LANES)) if isinstance(fixed_slots, dict) else ''
    legend += '制卡蓝 · 核验紫 · 修正绿 · 正常保护/等待/生成同lane色 · 严重保护首格深红 · 其他异常橙色/红色。首行为当前网页，下四行为已实际分配的排队材料。'
    current_status_counts = {name:sum(item['status']==name for item in current) for name in ('running','awaiting','idle','unobserved','protected','unavailable')}
    legend += (f"\n当前生成 {current_status_counts['running']} 页 · 上传或收取 {current_status_counts['awaiting']} 页 · 空闲 {current_status_counts['idle']} 页 · 待观测 {current_status_counts['unobserved']} 页 · 保护 {current_status_counts['protected']+current_status_counts['unavailable']} 页。")
    inventory_fresh = same_owner and _fresh(backlog.get('last_reconciled'), at) and backlog.get('enabled') == 1 and not backlog.get('error')
    if backlog.get('error'):
        legend += '\n' + backlog['error']
    elif backlog.get('enabled') == 1:
        legend += f'\n格内任务 {current_count + queued_count} 项：已核对当前 {current_count} 项 · 已分配排队 {queued_count} 项（未暂停且到期 {runnable_count} 项，暂停保留 {paused_count} 项）。'
        if cooldown_count:
            legend += f'上传失败退避 {cooldown_count} 项保留原格位与原入队顺序，到期自动恢复。'
        legend += f'低于 {backlog["low_watermark"]} 项时补充并重组至最多 {backlog["target_tasks"]} 项；材料或可用页面不足按实际数量。'
        if inventory_fresh:
            legend += f'\n最近调度核对的可调度库存 {backlog["total_tasks"]} 项：在途 {backlog["current_tasks"]} 项＋可调度排队 {backlog["queued_tasks"]} 项。暂停排队、未知回执与失败不计入触发库存。'
        else:
            legend += '\n触发库存待后台所有者新鲜核对；不借用旧数量。'
        if backlog.get('status') == 'shortfall':
            legend += ' 当前调度记录：库存或可用网页不足。'
    cells = current + [item for position in range(2, 6) for item in waiting[position]]
    def severity(item):
        status=item.get('status');detail=str(item.get('detail',''))+' '+str(item.get('tooltip',''))
        if status == 'unavailable':return 'critical'
        if status == 'protected':
            severe=('登录','验证','额度','移出专窗','未知','不完整','错误','失败','异常',
                    '发送前页面证据','needs_inspection','没有原请求证据')
            return 'critical' if any(token in detail for token in severe) else 'normal'
        # No gray: unobserved/idle/empty are still normal display states.  The
        # legend and tooltip carry the evidence freshness.
        return 'normal'
    for item in cells:item['severity']=severity(item)
    # A severe first-row cell is darkened; the other queue positions in that
    # column are marked orange so the problem distribution is visible without
    # turning the whole grid gray.
    severe_columns={item['column'] for item in cells if item.get('row')==1 and item.get('severity')=='critical'}
    for item in cells:
        if item.get('row',1)>1 and item.get('column') in severe_columns and item.get('status') in ('queued','awaiting'):
            item['severity']='warning'
    # Use the queued lane for an otherwise lane-less idle page.
    queue_lane={}
    for item in cells:
        if item.get('row',1)>1 and item.get('status')=='queued' and item.get('column') not in queue_lane:
            queue_lane[item['column']]=item.get('lane')
    for item in cells:
        if item.get('row')==1 and not item.get('lane') and item.get('column') in queue_lane:
            item['lane']=queue_lane[item['column']]
    return {'columns': 20, 'rows': 5, 'updated': at, 'windowID': registry.get('window_id'),
            'legend': legend, 'currentStatusCounts':current_status_counts,
            'backlog': {'enabled': backlog.get('enabled') == 1, 'currentTasks': current_count,
                        'queuedTasks': queued_count, 'authorizedDueQueuedTasks': runnable_count,
                        'pausedQueuedTasks': paused_count, 'uploadCooldownQueuedTasks': cooldown_count,
                        'error': backlog.get('error', ''),
                        'inventoryConfirmed': bool(inventory_fresh),
                        'inventoryTasks': backlog.get('total_tasks') if inventory_fresh else None,
                        'inventoryCurrentTasks': backlog.get('current_tasks') if inventory_fresh else None,
                        'inventoryQueuedTasks': backlog.get('queued_tasks') if inventory_fresh else None},
            'cells': cells}
