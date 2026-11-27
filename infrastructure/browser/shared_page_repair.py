"""Journaled page repair on the existing owner connection, never task resends."""
import copy
import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
from email import policy as email_policy
from email.parser import BytesParser
from core.api import paths__WorkspacePath as Path

from .browser_inventory import enumerate_pages
from core.api import control__read_record as read_record, control__mutate_record as mutate_record
from core.api import services__atomic_json as atomic_json
from .shared_browser_window import read_window_inventory, validate_registry, WindowIsolationError
from .shared_page_health import classify, snapshot_page
from .shared_window_owner import check_endpoint, registry_path, require_slot
from .shared_window_tabs import blank_url, create_in_window, _confirm_cleanup


TERMINAL_JOURNALS = frozenset(('ready', 'cancelled', 'archive_failed'))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_text(path, text):
    """Durable UTF-8 replace; the parent directory is fsynced too."""
    atomic_bytes(path, text.encode('utf-8'))


def atomic_bytes(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sync(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _registry(config):
    path = registry_path(config)
    registry = json.loads(path.read_text())
    validate_registry(registry)
    check_endpoint(registry)
    return registry, _sha(path)


def _allowed(config, stopping):
    from cards.api import web_card_service__owner_enabled as owner_enabled
    if stopping() or not owner_enabled(config):
        raise WindowIsolationError('用户已暂停，共享页维护保留原阶段')
    root = Path(config['catalog_path']).parent
    channel = read_record(root / 'web-channel-control.json')
    if channel.get('chatgpt', {}).get('manual_verification_required'):
        raise WindowIsolationError('访问验证优先，保留所有原页面')


def _rebase_registry(path, journal, registry, fingerprint, pool, live):
    """Other slots may change; this repair's exact slot and evidence may not."""
    if fingerprint == journal['registry_sha256']:return
    slot = next(s for s in registry['slots'] if s['slot_id'] == journal['slot_id'])
    old = journal['old_target_id']
    if registry['window_id'] != journal['window_id'] or slot.get('target_id') != old:
        raise WindowIsolationError('原窗口或原槽位变化，不更新修复CAS')
    baseline = journal.get('original_slot')
    metadata = {k:v for k,v in registry.items() if k not in ('slots','revision')}
    slot_hashes = {s['slot_id']:_sha_text(s) for s in registry['slots']}
    adopted = {}
    if baseline is None:
        # Older journals lack a slot snapshot. Adopt only after a proven close,
        # before ANY creation intent, with the original pool/ledger/archive bound.
        entry = pool['windows'].get(old, {})
        original = journal.get('original_entry', {})
        if (journal['state'] != 'closed_confirmed' or journal.get('nonce') or journal.get('candidate')
                or journal.get('close_authorized') is not True or old in live['targets']
                or entry.get('state') != 'repair_pending' or entry.get('repair_id') != journal['id']
                or slot.get('repair_id') != original.get('repair_id')
                or any(h.get('target_id') == old for h in slot.get('replacement_history', []))
                or not journal.get('archive_hashes')):
            raise WindowIsolationError('旧修复缺少可核对的原槽位证据，不更新CAS')
        for name, expected in journal['archive_hashes'].items():
            if _sha(path.parent/'diagnostics'/name) != expected:
                raise WindowIsolationError('旧修复归档变化，不更新CAS')
        record = journal.get('record')
        hashes = dict(journal.get('record_hashes', {}))
        if record:hashes[record['_ledger_path']] = record['_ledger_sha256']
        bindings = {}
        for ledger, expected in hashes.items():
            if Path(ledger).exists():_record_cas(ledger, expected)
            else:
                # Authorized retries move the original receipt into history.
                # Accept only one byte-identical original in that paper's
                # history; never accept a rewritten/current replacement.
                records,_ = _records(path.parent.parent.parent)
                parent = Path(ledger).parent.parent.resolve()
                found = [name for name,r in records.items()
                    if r.get('_ledger_sha256') == expected and r.get('target_id') == old
                    and Path(name).resolve().is_relative_to(parent)
                    and 'history' in Path(name).relative_to(parent).parts]
                if len(found) != 1:
                    raise WindowIsolationError('旧账本缺失或归档不唯一，不更新CAS')
                _record_cas(found[0],expected);bindings[ledger]={'path':found[0],'sha256':expected}
        baseline = copy.deepcopy(slot)
        adopted = dict(original_slot=baseline,legacy_slot_adopted_after_verified_close=True,
                       legacy_ledger_archive_bindings=bindings)
    else:
        if journal.get('registry_metadata') != metadata or not journal.get('registry_slots_sha256'):
            raise WindowIsolationError('登记全局身份CAS变化或原其他槽位证据不足')
        changed = {sid for sid,h in slot_hashes.items() if h != journal['registry_slots_sha256'].get(sid)}
        if not changed or journal['slot_id'] in changed:
            raise WindowIsolationError('登记CAS变化不能归因于其他槽位')
    if slot != baseline:
        raise WindowIsolationError('原槽位字段变化，不更新修复CAS')
    rebases = journal.get('registry_rebases', []) + [{
        'before':journal['registry_sha256'], 'after':fingerprint,
        'checked_at':time.time(), 'slot_id':journal['slot_id']}]
    _journal(path, journal, registry_sha256=fingerprint, registry_rebases=rebases,
             registry_metadata=metadata, registry_slots_sha256=slot_hashes, **adopted)


def _sha_text(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _inventory(browser, registry, candidate_ids=()):
    inventory = read_window_inventory(browser)
    if not inventory.get('complete') or inventory.get('errors'):
        raise WindowIsolationError('实时窗口清单不完整，禁止页生命周期修改')
    registered = {slot['target_id'] for slot in registry['slots'] if slot.get('target_id')}
    inside = {tid for tid, target in inventory['targets'].items()
              if target['window_id'] == registry['window_id']}
    if not inside or len(inside) > 20 or not inside.issubset(registered | set(candidate_ids)):
        raise WindowIsolationError('专用窗口缺失、超额或有非登记页面，禁止接管/关闭/补页')
    return inventory


def _records(root):
    from .attempt_history import index_attempts, read_attempt
    from .original_receipt_recovery import collection_ledgers, _identity
    records, latest = index_attempts(root)
    # Restored conversations are bound to side ledgers, not the immutable old
    # target. Give the existing health/archive/CAS guards the same validated
    # receipt that the observer uses. Never infer a sender or alter its state.
    for tid, (path, saved) in collection_ledgers(root).items():
        try:record = read_attempt(path)
        except (OSError,ValueError):continue
        if record.get('target_id') != tid or _identity(record) != saved:
            continue  # A concurrent collector changed the receipt; recheck later.
        record['_collection_recovery'] = True
        records[record['_ledger_path']] = record
        latest[tid] = record
    return records, latest


def _entry_for(root, record, raw_path, url):
    path = Path(record['_ledger_path'])
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        parts = ()
    review = bool(record.get('review_id')) or bool(parts and parts[0] == 'card_reviews')
    result = {'state': 'ready', 'kind': 'review' if review else 'cards',
              'raw_path': str(Path(raw_path).resolve()), 'raw_sha256': record['raw_sha256'],
              'conversation_url': url}
    paper = record.get('paper_id') or (parts[1] if len(parts) > 1 else None)
    if paper:
        result.update(paper_id=paper, active_paper_id=paper)
    if review and record.get('review_id'):
        result['review_id'] = record['review_id']
    return result


def _persist_pool(root, pool):
    from .shared_pool_store import save_pool
    save_pool(root / 'gpt-window-pool.json', pool)


def _record_cas(path, expected):
    if _sha(path) != expected:
        raise WindowIsolationError('原提交账本已变化，停止维护')


def _capture_png_on_owner(page):
    """Read a viewport PNG on the resident connection without focusing a tab."""
    async def capture():
        session = None
        try:
            session = await asyncio.wait_for(page._impl_obj.context.new_cdp_session(page._impl_obj), 3)
            return await asyncio.wait_for(session.send('Page.captureScreenshot', {
                'format': 'png', 'fromSurface': True, 'captureBeyondViewport': False,
                'optimizeForSpeed': True}), 8)
        finally:
            if session is not None:
                await asyncio.wait_for(session.detach(), 2)

    reply = page._sync(capture())
    data = base64.b64decode(reply['data'], validate=True)
    if (len(data) < 45 or not data.startswith(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR') or
            not data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82') or
            not int.from_bytes(data[16:20], 'big') or not int.from_bytes(data[20:24], 'big')):
        raise WindowIsolationError('原页截图未返回有效PNG，保留原页')
    return data


def _capture_mhtml_on_owner(page):
    """Archive the actual document when the renderer cannot produce a PNG."""
    expected_url = page.url
    async def capture():
        session = None
        try:
            session = await asyncio.wait_for(page._impl_obj.context.new_cdp_session(page._impl_obj), 3)
            return await asyncio.wait_for(session.send('Page.captureSnapshot', {'format': 'mhtml'}), 8)
        finally:
            if session is not None:
                await asyncio.wait_for(session.detach(), 2)
    reply = page._sync(capture())
    data = reply.get('data')
    if not isinstance(data, str) or not data.strip():
        raise WindowIsolationError('原页快照为空，保留原页')
    document = BytesParser(policy=email_policy.default).parsebytes(data.encode('utf-8'))
    if (page.url != expected_url or document.get('Snapshot-Content-Location') != expected_url or
            document.get_content_type() != 'multipart/related' or
            not any(part.get_content_type() == 'text/html' and part.get('Content-Location') == expected_url
                    and part.get_payload(decode=True) for part in document.walk())):
        raise WindowIsolationError('完整网页快照未绑定原页面地址，保留原页')
    return data


def _archive_png(folder, page, guard):
    from playwright.sync_api import TimeoutError as ScreenshotTimeout
    try:
        page.screenshot(path=str(folder / 'page.png'), timeout=15000)
        return {'method': 'playwright', 'timeout_ms': 15000}
    except ScreenshotTimeout as exc:
        guard()
        try:
            image = _capture_png_on_owner(page)
        except asyncio.TimeoutError as capture_error:
            guard()
            document = _capture_mhtml_on_owner(page)
            guard()
            atomic_text(folder / 'page.mhtml', document)
            return {'method': 'resident_cdp_mhtml', 'screenshot_available': False,
                    'playwright_error': str(exc)[:500],
                    'cdp_screenshot_error': type(capture_error).__name__,
                    'snapshot_timeout_seconds': 8, 'foreground_changed': False}
        guard()
        atomic_bytes(folder / 'page.png', image)
        return {'method': 'resident_cdp_viewport', 'capture_timeout_seconds': 8,
                'playwright_error': str(exc)[:500], 'foreground_changed': False}


def _restorable_repair_blank(root, slot, entry, snapshot, record_paths, window_id):
    """Restore only an enrolled, never-used repair page after inventory failure."""
    identity=entry.get('repair_id','')
    if (entry.get('state')!='missing' or entry.get('origin')!='shared_page_health_repair' or
            entry.get('never_submitted') is not True or record_paths or
            any(entry.get(k) for k in ('raw_path','raw_sha256','active_paper_id','review_id','correction_id','submission_unknown')) or
            len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity)):
        return False
    try:
        path=root/'shared-page-repairs'/identity/'journal.json'
        journal=json.loads(path.read_text())
        if (journal.get('state')!='ready' or journal.get('new_target_id')!=slot['target_id'] or
                journal.get('slot_id')!=slot['slot_id'] or journal.get('window_id')!=window_id):return False
        hashes=journal.get('archive_hashes',{})
        if not {'health.json','body.txt','page.html','ledger-before.json'}.issubset(hashes):return False
        if 'page.png' not in hashes:
            capture=json.loads((path.parent/'diagnostics/capture.json').read_text())
            if (not {'page.mhtml','capture.json'}.issubset(hashes) or
                    capture.get('method')!='resident_cdp_mhtml' or capture.get('screenshot_available') is not False):return False
        if any(Path(name).name!=name or _sha(path.parent/'diagnostics'/name)!=expected for name,expected in hashes.items()):return False
        return classify(snapshot,{**entry,'state':'ready_blank'},None)['health']=='healthy_blank'
    except (OSError,ValueError,TypeError,KeyError):return False


def _archive(folder, page, health, record, guard, record_hashes=None, *, allow_missing_unsent_prompt=False):
    """Every diagnostic is required and durable before close permission exists."""
    folder.mkdir(parents=True, exist_ok=False)
    atomic_json(folder / 'health.json', health)
    snapshot = health['evidence']['snapshot']
    guard()
    body = page.locator('body').inner_text(timeout=3000)
    atomic_text(folder / 'body.txt', body)
    guard()
    atomic_text(folder / 'page.html', page.content())
    guard()
    capture = _archive_png(folder, page, guard)
    image_file = 'page.mhtml' if capture['method'] == 'resident_cdp_mhtml' else 'page.png'
    _sync(folder / image_file)
    atomic_json(folder / 'capture.json', capture)
    fingerprints = {name: _sha(folder / name) for name in ('health.json', 'body.txt', 'page.html', image_file)}
    fingerprints['capture.json'] = _sha(folder / 'capture.json')
    if record_hashes:
        guard()
        history = []
        for ledger_path, expected in record_hashes.items():
            # Local immutable ledger CAS for every entry. Window ownership is
            # checked before/after this read and again immediately before close.
            _record_cas(ledger_path, expected)
            history.append({'path': ledger_path, 'sha256': expected,
                            'record': json.loads(Path(ledger_path).read_text())})
        guard()
        atomic_json(folder / 'target-history-before.json', history)
        fingerprints['target-history-before.json'] = _sha(folder / 'target-history-before.json')
    if record:
        source = Path(record['_ledger_path'])
        _record_cas(source, record['_ledger_sha256'])
        atomic_text(folder / 'ledger-before.json', source.read_text())
        prompt = source.parent / 'prompt-actual.txt'
        actual_sha = record.get('actual_prompt_sha256')
        if (allow_missing_unsent_prompt and record.get('state')=='not_sent' and record.get('send_click_started') is False and (not actual_sha or not prompt.exists())):
            atomic_json(folder/'prompt-unavailable.json',{'expected_sha256':actual_sha,'path':str(prompt),'exists':prompt.exists(),'bound_to_attempt':False,'input_fingerprints':record.get('inputs',{})})
            fingerprints['prompt-unavailable.json']=_sha(folder/'prompt-unavailable.json')
            if prompt.exists():
                atomic_text(folder/'unbound-prompt.txt',prompt.read_text())
                fingerprints['unbound-prompt.txt']=_sha(folder/'unbound-prompt.txt')
        elif actual_sha:
            if not prompt.exists():
                # The archived prompt can be missing after an owner restart or
                # an authorized history move. A proven-unsent record still
                # preserves its ledger, inputs and page evidence.
                if record.get('state') == 'not_sent' and record.get('send_click_started') is False:
                    atomic_json(folder / 'prompt-unavailable.json', {
                        'expected_sha256': actual_sha, 'path': str(prompt),
                        'exists': False, 'bound_to_attempt': False,
                        'input_fingerprints': record.get('inputs', {})})
                    fingerprints['prompt-unavailable.json'] = _sha(folder / 'prompt-unavailable.json')
                else:
                    raise WindowIsolationError('原实际提示文件缺失，不能归档关闭')
            else:
                actual = prompt.read_text()
                if hashlib.sha256(actual.encode()).hexdigest() != actual_sha:
                    raise WindowIsolationError('归档前原实际提示指纹变化')
                atomic_text(folder / 'prompt-before.txt', actual)
                fingerprints['prompt-before.txt'] = _sha(folder / 'prompt-before.txt')
        elif (record.get('state') == 'not_sent' and record.get('send_click_started') is False
              and not prompt.exists()):
            atomic_json(folder / 'prompt-not-created.json', {'prompt_not_created': True,
                'send_click_started': False, 'actual_prompt_sha256': None,
                'input_fingerprints': {k: v for k, v in record.items() if 'sha256' in k or 'fingerprint' in k}})
            fingerprints['prompt-not-created.json'] = _sha(folder / 'prompt-not-created.json')
        else:
            raise WindowIsolationError('原实际提示指纹缺失，不能归档关闭')
        fingerprints['ledger-before.json'] = _sha(folder / 'ledger-before.json')
    if snapshot.get('inspection_complete') is not True:
        raise WindowIsolationError('原页错误证据不完整')
    atomic_json(folder / 'archive-manifest.json', {'files': fingerprints, 'complete': True})
    return fingerprints


def _journal(path, journal, state=None, **updates):
    journal.update(updates)
    if state:
        journal['state'] = state
    journal['updated'] = time.time()
    atomic_json(path, journal)


def _candidate(inventory, journal):
    expected = blank_url(journal['nonce'])
    candidates = [target for target in inventory['targets'].values() if target.get('url') == expected]
    if len(candidates) > 1:
        raise WindowIsolationError('补页nonce不唯一，保留全部候选')
    if candidates and candidates[0]['window_id'] != journal['window_id']:
        raise WindowIsolationError('补页候选进入其他窗口，不接管或移动')
    return candidates[0] if candidates else None


def _relocate_archived_ledgers(path, journal):
    """Follow exact-byte history moves, never substitute a newer request."""
    from .attempt_history import read_attempt

    moves = {}
    original_hashes = dict(journal.get('record_hashes', {}))
    original_record = journal.get('record') or {}
    if original_record.get('_ledger_path') and original_record.get('_ledger_sha256'):
        original_hashes.setdefault(original_record['_ledger_path'], original_record['_ledger_sha256'])
    for old, expected in original_hashes.items():
        source = Path(old)
        if source.exists():
            if _sha(source) == expected:
                continue
            # Review recovery may reuse the job path for another target after
            # moving the old ledger to history. Same-target changes still
            # invalidate the old plan, even when a historical copy exists.
            old_target = journal.get('old_target_id')
            new_target = read_attempt(source).get('target_id')
            if not old_target or not new_target or new_target == old_target:
                raise WindowIsolationError('原提交账本已变化，停止维护')
        matches = [p for p in (source.parent / 'history').rglob('attempt.json')
                   if _sha(p) == expected]
        if len(matches) != 1:
            raise WindowIsolationError('原账本缺失且历史归档不唯一，保留页面')
        moves[old] = str(matches[0])
    if not moves:
        return
    atomic_bytes(path.parent / ('before-ledger-relocation-' + _sha(path) + '.json'), path.read_bytes())
    hashes = {moves.get(p, p): v for p, v in original_hashes.items()}
    record = dict(journal.get('record') or {})
    if record.get('_ledger_path') in moves:
        record['_ledger_path'] = moves[record['_ledger_path']]
    _journal(path, journal, record_hashes=hashes, record=record or None,
             record_paths=[moves.get(p, p) for p in journal.get('record_paths', [])],
             ledger_relocations=journal.get('ledger_relocations', []) +
                 [{'paths': moves, 'checked_at': time.time()}])


def _verified_displaced_inputs(folder,record):
    """Project exact sent ZIP bytes into an independent view; keep damaged files."""
    import zipfile,shutil
    from review.api import card_review_queue__check_packet as check_packet
    packet_path=folder/'packet.json';packet_bytes=packet_path.read_bytes();packet=json.loads(packet_bytes)
    if (packet.get('input_hashes')!=record.get('inputs') or
            packet.get('actual_prompt_sha256')!=record.get('actual_prompt_sha256')):
        raise WindowIsolationError('原ZIP与原发送输入指纹不一致')
    bundle=packet['upload_bundle'];zip_path=Path(bundle['zip_path']);zip_sha=bundle['zip_sha256']
    if _sha(zip_path)!=zip_sha:raise WindowIsolationError('原上传ZIP指纹变化')
    if record.get('upload_bundle',{}).get('zip_sha256') not in (None,zip_sha):
        raise WindowIsolationError('原发送ZIP与冻结ZIP不一致')
    prompt=folder/'prompt-actual.txt'
    if _sha(prompt)!=packet['actual_prompt_sha256']:raise WindowIsolationError('原实际提示变化')
    view=folder/('verified-inputs-'+zip_sha)
    if view.exists():check_packet(view);return view
    temporary=Path(tempfile.mkdtemp(prefix='.verified-inputs-',dir=str(folder)));damaged={}
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for name,expected in packet['input_hashes'].items():
                if Path(name).name!=name:raise WindowIsolationError('原输入名称越界')
                source=folder/name
                if source.is_file() and _sha(source)==expected:
                    data=source.read_bytes()
                else:
                    info=archive.getinfo(name)
                    if info.file_size>100_000_000:raise WindowIsolationError('原ZIP条目超出恢复边界')
                    data=archive.read(name)
                    if source.exists():
                        before=source.read_bytes();proof=temporary/'superseded-input-evidence'/name
                        atomic_bytes(proof,before);damaged[name]=hashlib.sha256(before).hexdigest()
                    else:damaged[name]='missing'
                if hashlib.sha256(data).hexdigest()!=expected:raise WindowIsolationError('原ZIP不能提供匹配原件')
                atomic_bytes(temporary/name,data)
        atomic_bytes(temporary/'prompt-actual.txt',prompt.read_bytes())
        atomic_bytes(temporary/'packet.json',packet_bytes)
        atomic_json(temporary/'verified-input-view.json',{'original_folder':str(folder),'original_zip_sha256':zip_sha,
            'original_packet_sha256':hashlib.sha256(packet_bytes).hexdigest(),'damaged_original_sha256':damaged,
            'original_files_unchanged':True,'new_input_generated':False})
        check_packet(temporary)
        if _sha(zip_path)!=zip_sha or packet_path.read_bytes()!=packet_bytes:
            raise WindowIsolationError('原材料恢复期间变化')
        temporary.rename(view)
    except BaseException:
        shutil.rmtree(temporary,ignore_errors=True);raise
    return view


def _restore_displaced_review(config,browser,pool,slot,page,snapshot,previous,urls,records,stopping):
    """Undo legacy TTL displacement only from exact original sent evidence."""
    import re
    from .shared_page_health import _normal,_stable,_receipt,_fingerprint
    tid=slot['target_id'];entry=pool['windows'].get(tid,{})
    if (entry.get('state') not in ('ready_blank','needs_inspection') or
            snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False or
            snapshot.get('terminal_complete') is not True or not _stable(snapshot,previous,snapshot['checked_at']) or
            str(snapshot.get('draft','')).strip() or
            any(snapshot.get(k) for k in ('attachments','uploading','login','verification','quota','errors')) or
            any(r.get('target_id')==tid for r in records.values())):return None
    users,answers=_normal(snapshot)
    if len(users)!=1 or len(answers)!=1 or not answers[0].strip():return None
    from .web_page_observer import _review_markers
    ids=_review_markers(users[0])
    if len(set(ids))!=1:return None
    jid=ids[0]
    from core.api import catalog__Catalog as Catalog,catalog__now as now
    from review.api import (card_review_queue__check_packet as check_packet,
        card_review_queue__current as current,card_review_queue__protected as protected)
    catalog=Catalog(config['catalog_path']);root=catalog.path.parent
    with catalog.connect() as db:
        row=db.execute("SELECT * FROM card_review_jobs WHERE id=? AND state IN ('ready','queued','failed','needs_user')",(jid,)).fetchone()
    if row is None:return None
    job=dict(row);active=Path(job['folder'])
    if (active/'attempt.json').exists():return None
    result=json.loads(job.get('result') or '{}')
    if result and result.get('failure_kind')!='technical':return None
    candidates=[]
    paths=list((root/'claim-lease-release').glob('*/'+jid+'-attempt-retired.json'))
    paths+=list((root/'abnormal-protection-cleanup').glob('*/'+tid+'-attempt-retired.json'))
    paths+=list((root/'protection-resets').glob('*/'+tid+'/attempt-retired.json'))
    for archive in paths:
        raw=archive.read_bytes();a=json.loads(raw)
        if (a.get('target_id')!=tid or a.get('review_id')!=jid or
                a.get('state') not in ('submitted','submission_started','needs_inspection') or
                a.get('send_click_started') is not True):continue
        folders=[];seen=set();prior_job=job
        for _ in range(12):
            folder=Path(prior_job['folder'])
            if str(folder) in seen:break
            seen.add(str(folder));folders.append((folder,prior_job))
            before=folder/'previous-job.json'
            if not before.is_file():break
            prior_job=json.loads(before.read_text())
            if any(prior_job.get(k)!=job.get(k) for k in ('id','paper_id','card_sha256','source_sha256')):break
        for folder,old_job in folders:
            if not folder.resolve().is_relative_to((root/'card_reviews'/job['paper_id']).resolve()):continue
            if (folder/'attempt.json').exists():continue
            try:
                try:packet=check_packet(folder)
                except (OSError,ValueError):
                    folder=_verified_displaced_inputs(folder,a)
                    packet=check_packet(folder)
                if (packet.get('job_id')!=jid or packet.get('input_hashes')!=a.get('inputs') or
                        packet.get('actual_prompt_sha256')!=a.get('actual_prompt_sha256') or
                        packet.get('card_sha256')!=job['card_sha256'] or
                        packet.get('source_original_sha256')!=job['source_sha256']):continue
                prompt=(folder/'prompt-actual.txt').read_text()
                _receipt(snapshot,a,urls,prompt)
                paper,_,_=current(catalog,job,config)
                if protected(catalog,paper):continue
            except (OSError,ValueError,KeyError,TypeError):continue
            candidates.append((archive,raw,a,folder,old_job))
    unique={(hashlib.sha256(raw).hexdigest(),str(folder)):(archive,raw,a,folder,old_job)
        for archive,raw,a,folder,old_job in candidates}
    if len(unique)!=1:return None
    (digest,_), (archive,raw,a,folder,old_job)=next(iter(unique.items()))
    path=folder/'attempt.json';evidence_folder=root/'displaced-review-receipts'/digest
    def guard():
        _allowed(config,stopping);require_slot(config,browser,tid)
        if path.exists() or (active/'attempt.json').exists() or _sha(archive)!=digest:
            raise WindowIsolationError('旧回执恢复前材料/归档变化')
        if _fingerprint(snapshot_page(tid,page))!=_fingerprint(snapshot):
            raise WindowIsolationError('旧回执恢复前实时页面变化')
    guard();evidence_folder.mkdir(parents=True,exist_ok=True)
    health=classify(snapshot,entry,None,urls=urls,previous=previous)
    archived=_archive(evidence_folder/'diagnostics',page,health,None,guard,{})
    atomic_json(evidence_folder/'job-before.json',job)
    atomic_json(evidence_folder/'restore-proof.json',{'original_archive':str(archive),'original_sha256':digest,
        'original_folder':str(folder),'superseded_unsent_folder':str(active),'target_id':tid,
        'archive_hashes':archived,'original_sent_request_not_repeated':True})
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE');fresh=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(jid,)).fetchone()
        if fresh is None or dict(fresh)!=job or db.execute("SELECT 1 FROM shared_page_backlog WHERE lane='review' AND job_id=? AND state='claimed'",(jid,)).fetchone():
            raise WindowIsolationError('旧回执恢复时任务已被领取或发生变化')
        current(catalog,job,config);check_packet(folder);guard()
        atomic_bytes(path,raw)  # Exact old bytes, never a newly invented sender receipt.
        db.execute("DELETE FROM shared_page_backlog WHERE lane='review' AND job_id=? AND state='queued'",(jid,))
        db.execute("UPDATE card_review_jobs SET state='submitted',folder=?,error=?,result=?,updated=? WHERE id=?",
            (str(folder),'已按原指纹恢复被外围误移的已发送回执；只收原会话，不重发',old_job.get('result') or '{}',now(),jid))
        db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'displaced_original_receipt_restored',?,?)",
            (job['paper_id'],json.dumps({'archive':str(archive),'sha256':digest,'target_id':tid,'old_folder':str(active)}),now()))
    from .attempt_history import read_attempt
    return read_attempt(path)


def _recover_orphan_review(config, browser, pool, slot, page, snapshot, previous, urls, records, stopping):
    """Recover an observed complete answer, explicitly without a sender receipt."""
    import re
    from .shared_page_health import _normal, _stable, _receipt, _fingerprint
    tid=slot['target_id'];entry=pool['windows'].get(tid,{})
    if (entry.get('state') not in ('ready_blank','needs_inspection') or
            snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False or
            snapshot.get('terminal_complete') is not True or not _stable(snapshot,previous,snapshot['checked_at']) or
            str(snapshot.get('draft','')).strip() or
            any(snapshot.get(k) for k in ('attachments','uploading','login','verification','quota','errors')) or
            any(r.get('target_id')==tid for r in records.values())):
        return None
    users,answers=_normal(snapshot)
    if len(users)!=1 or len(answers)!=1 or not answers[0].strip():return None
    from .web_page_observer import _review_markers
    ids=_review_markers(users[0])
    if len(set(ids))!=1:return None
    from core.api import catalog__Catalog as Catalog
    from review.api import (card_review_queue__check_packet as check_packet,
        card_review_queue__current as current, card_review_queue__protected as protected)
    catalog=Catalog(config['catalog_path']);root=catalog.path.parent
    with catalog.connect() as db:
        row=db.execute("SELECT * FROM card_review_jobs WHERE id=? AND state IN ('failed','needs_user')",(ids[0],)).fetchone()
    if row is None:return None
    job=dict(row);folder=Path(job['folder']);path=folder/'attempt.json'
    if not folder.resolve().is_relative_to((root/'card_reviews').resolve()) or path.exists():return None
    if json.loads(job.get('result') or '{}'):return None
    packet=check_packet(folder);paper,_,_=current(catalog,job,config)
    if (packet.get('job_id')!=job['id'] or packet.get('card_sha256')!=job.get('card_sha256')
            or packet.get('source_original_sha256')!=job.get('source_sha256')):
        return None
    if protected(catalog,paper):return None
    prompt=folder/'prompt-actual.txt'
    if not prompt.is_file() or _sha(prompt)!=packet['actual_prompt_sha256']:return None
    at=time.time();record={'provider':'chatgpt','kind':'review','review_id':job['id'],
        'target_id':tid,'state':'response_saved','conversation_url':snapshot['url'],
        'inputs':packet['input_hashes'],'actual_prompt_sha256':packet['actual_prompt_sha256'],
        'raw_sha256':hashlib.sha256(answers[0].encode()).hexdigest(),
        'created':at,'created_basis':'recovery_observation_not_send_time','finished':at,
        'recovered_by_owner_pid':os.getpid(),'original_sender_identity_unknown':True,
        'original_attempt_missing':True,'actual_model_unknown':True}
    _receipt(snapshot,record,urls,prompt.read_text())
    raw=folder/'response-raw.txt'
    if raw.exists() and _sha(raw)!=record['raw_sha256']:
        raise WindowIsolationError('无账本回答与原保存正文不同，不覆盖')
    key=_sha_text([tid,snapshot['url'],record['raw_sha256'],packet['actual_prompt_sha256']])
    evidence_folder=root/'orphan-review-receipts'/key
    def guard():
        _allowed(config,stopping);require_slot(config,browser,tid)
        if path.exists():raise WindowIsolationError('原提交账本重新出现，保留原物')
        fresh=snapshot_page(tid,page)
        if _fingerprint(fresh)!=_fingerprint(snapshot):raise WindowIsolationError('无账本回答恢复前实时证据变化')
    guard();evidence_folder.mkdir(parents=True,exist_ok=True)
    health=classify(snapshot,entry,None,urls=urls,previous=previous)
    archived=_archive(evidence_folder/'diagnostics',page,health,None,guard,{})
    atomic_json(evidence_folder/'job-before.json',job)
    atomic_json(evidence_folder/'recovery-proof.json',{'archive_hashes':archived,
        'original_attempt_missing':True,'send_time_unknown':True,'actual_model_unknown':True,
        'target_id':tid,'slot_id':slot['slot_id'],'raw_sha256':record['raw_sha256']})
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
        if fresh is None or dict(fresh)!=job or path.exists():raise WindowIsolationError('原核验任务恢复期间变化')
        if db.execute("SELECT 1 FROM shared_page_backlog WHERE lane='review' AND job_id=? AND target_id!=?",(job['id'],tid)).fetchone():
            raise WindowIsolationError('原材料在另一页已绑定，不接管')
        current(catalog,job,config);check_packet(folder);guard()
        if not raw.exists():atomic_text(raw,answers[0])
        if _sha(raw)!=record['raw_sha256']:raise WindowIsolationError('回答保存物恢复期间变化')
        atomic_json(path,record)
        db.execute("UPDATE card_review_jobs SET state='response_saved',error=?,updated=? WHERE id=?",
            ('原提交账本缺失；按完整实时证据恢复回答，原发送时间与模型未知',__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),job['id']))
    entry.update(state='ready',kind='review',review_id=job['id'],paper_id=job['paper_id'],
        active_paper_id=job['paper_id'],conversation_url=record['conversation_url'],raw_path=str(raw),raw_sha256=record['raw_sha256'])
    entry.pop('error',None);_persist_pool(root,pool)
    from .attempt_history import read_attempt
    return read_attempt(path)


def _terminal_empty_restart(config, health, record, previous=None, *, at):
    """Retire a proven original empty terminal after two real rounds; never retry."""
    limit = config.get('web_cards', {}).get('shared_window', {}).get('health_repair', {}).get('hard_restart_after_seconds')
    if health.get('health') != 'terminal_empty' or type(limit) not in (int, float) or limit <= 0:
        return False
    created = (record or {}).get('created')
    if type(created) not in (int, float) or at - created <= limit:
        return False
    key = _sha_text([health['evidence']['fingerprint'], (record or {}).get('_ledger_sha256')])
    old = (previous or {}).get('terminal_empty_check', {})
    check = dict(old) if old.get('key') == key else {'key': key, 'rounds': 0}
    if not check['rounds'] or at - check.get('last_checked_at', at) >= 30:
        check.update(rounds=check['rounds'] + 1, last_checked_at=at)
    health['terminal_empty_check'] = check
    return check['rounds'] >= 2


def _hourly_idle_restart(config, health, entry, record, previous=None, *, at):
    """One-hour fallback for a faulted, fully accounted-for idle page."""
    limit = config.get('web_cards', {}).get('shared_window', {}).get('health_repair', {}).get('hard_restart_after_seconds')
    snapshot = health.get('evidence', {}).get('snapshot', {})
    if (type(limit) not in (int, float) or limit <= 0 or not entry.get('error') or
            health.get('health') not in ('healthy_blank', 'completed_saved') or
            entry.get('state') in ('busy', 'submitting', 'collecting', 'preparing', 'uploading') or
            snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False or
            snapshot.get('uploading') is not False or str(snapshot.get('draft', '')).strip() or
            any(snapshot.get(k) for k in ('attachments', 'login', 'verification', 'quota')) or
            not record or record.get('target_id') != snapshot.get('target_id')):
        return False
    if health['health'] == 'healthy_blank' and not (
            record.get('state') == 'not_sent' and record.get('send_click_started') is False):
        return False
    key = _sha_text([health['evidence']['fingerprint'], entry['error'], record.get('_ledger_sha256')])
    old = (previous or {}).get('hard_restart_check', {})
    first = old.get('first_seen', at) if old.get('key') == key else at
    health['hard_restart_check'] = {'key': key, 'first_seen': first, 'checked_at': at}
    return at - first > limit


def _hourly_missing_slot_request(config, root, path, journal, registry, inventory):
    """Bounded new creation epoch after one hour; the old receipt stays unknown."""
    policy = config.get('web_cards', {}).get('shared_window', {}).get('health_repair', {})
    limit = policy.get('hard_restart_after_seconds')
    at = time.time()
    since = journal.get('last_creation_epoch_at', journal.get('created', at))
    if (type(limit) not in (int, float) or limit <= 0 or at - since <= limit or
            journal.get('state') != 'create_unknown' or journal.get('candidate')):
        return None
    if journal.get('extension_cleanup_error') or journal.get('extension_source_path'):
        return None
    nonces = [journal.get('nonce')] + [e.get('nonce') for e in journal.get('creation_epochs', [])]
    if any(t.get('url') == blank_url(n) for n in nonces if n for t in inventory['targets'].values()):
        return None
    key = _sha_text({'slots': registry['slots'], 'targets':
        {tid: t.get('window_id') for tid, t in inventory['targets'].items()}})
    check = journal.get('hourly_missing_check', {})
    if check.get('key') != key:
        _journal(path, journal, hourly_missing_check={'key': key, 'first_seen': at})
        return None
    if at - check.get('first_seen', at) < 30:
        return None
    slot = next(s for s in registry['slots'] if s['slot_id'] == journal['slot_id'])
    request = {'authorized': True, 'state': 'pending', 'purpose': 'new_missing_slot_epoch',
        'journal_id': journal['id'], 'original_nonce': journal.get('nonce'),
        'old_target_id': journal['old_target_id'], 'slot_id': journal['slot_id'],
        'window_id': journal['window_id'], 'journal_created': journal['created'],
        'slot_sha256': hashlib.sha256(json.dumps(slot, sort_keys=True).encode()).hexdigest(),
        'new_nonce': secrets.token_hex(16),
        'authorization': 'docs/authorizations/20261022-one-hour-page-restart.md'}
    request_path = path.parent / 'hourly-missing-slot-request.json'
    atomic_json(request_path, request)
    return request_path


def _authorized_missing_slot(root, path, journal, registry, inventory, fingerprint, request_path=None):
    """A single new user-approved creation epoch; the old nonce stays unknown."""
    request_path=request_path or root/'missing-slot-recovery-request.json'
    request=read_record(request_path)
    fields={'journal_id':journal['id'],'original_nonce':journal.get('nonce'),
            'old_target_id':journal['old_target_id'],'slot_id':journal['slot_id'],
            'window_id':journal['window_id'],'journal_created':journal['created']}
    if (request.get('authorized') is not True or request.get('state')!='pending' or
            request.get('purpose')!='new_missing_slot_epoch' or
            any(request.get(k)!=v for k,v in fields.items()) or
            journal.get('state')!='create_unknown' or journal.get('candidate')):return False
    slot=next(s for s in registry['slots'] if s['slot_id']==journal['slot_id'])
    if (registry['window_id']!=journal['window_id'] or slot.get('target_id')!=journal['old_target_id'] or
            hashlib.sha256(json.dumps(slot,sort_keys=True).encode()).hexdigest()!=request.get('slot_sha256')):
        raise WindowIsolationError('专项缺页恢复槽位归属变化，保留旧创建回执')
    inside={tid for tid,t in inventory['targets'].items() if t['window_id']==registry['window_id']}
    registered={s.get('target_id') for s in registry['slots'] if s.get('target_id')}
    if (not inventory.get('complete') or inventory.get('errors') or len(inside)!=19 or
            inside!=registered-{journal['old_target_id']} or journal['old_target_id'] in inventory['targets'] or
            any(t.get('url')==blank_url(journal['nonce']) for t in inventory['targets'].values())):
        raise WindowIsolationError('专项缺页恢复实时清单不满足19个原登记页及原nonce缺失')
    nonce=request.get('new_nonce');blank_url(nonce)
    if nonce==journal['nonce'] or any(t.get('url')==blank_url(nonce) for t in inventory['targets'].values()):
        raise WindowIsolationError('专项新创建nonce冲突，禁止开页')
    for name,expected in journal.get('archive_hashes',{}).items():
        if Path(name).name!=name or _sha(path.parent/'diagnostics'/name)!=expected:
            raise WindowIsolationError('专项缺页原归档证据变化')
    if not journal.get('close_authorized') or not journal.get('archive_hashes'):
        raise WindowIsolationError('专项缺页缺少原关闭与归档证据')
    atomic_bytes(path.parent/('creation-unknown-'+journal['nonce']+'.json'),path.read_bytes())
    epochs=list(journal.get('creation_epochs',[]))+[{'nonce':journal['nonce'],'state':'create_unknown',
            'not_resolved':True,'new_epoch_authorization':request.get('authorization')}]
    _journal(path,journal,'closed_confirmed',creation_epochs=epochs,registry_sha256=fingerprint,
             authorized_creation_nonce=nonce,missing_slot_recovery_authorization=request.get('authorization'),
             last_creation_epoch_at=time.time())
    mutate_record(request_path,{'state':'consumed','consumed_at':time.time()},event='missing_slot_new_epoch')
    return True


def _retry_unused_candidate(config, browser, root, path, journal, entry, page, snapshot, stopping):
    """Recover an attributed initialization network error, never a sent page."""
    tid=journal['candidate']['target_id']
    if (page.url!='chrome-error://chromewebdata/' or entry.get('never_submitted') is not True or
            entry.get('state')!='opening' or entry.get('repair_id')!=journal['id'] or
            snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False or
            snapshot.get('draft','').strip() or any(snapshot.get(k) for k in
                ('user_texts','answer_texts','attachments','login','verification','quota'))):
        return False
    records,_=_records(root)
    if any(record.get('target_id')==tid for record in records.values()):return False
    from .shared_page_health import _fingerprint
    key=_fingerprint(snapshot);at=time.time();old=journal.get('candidate_initialization_fault',{})
    check=dict(old) if old.get('fingerprint')==key else {'fingerprint':key,'first_seen':at,'rounds':0}
    if not check['rounds'] or at-check.get('last_round_at',at)>=30:
        check.update(rounds=check['rounds']+1,last_round_at=at)
    policy=config['web_cards']['shared_window']['health_repair']
    limit=policy.get('startup_stalled_after_seconds',60)
    _journal(path,journal,candidate_initialization_fault=check,candidate_observation=snapshot)
    if check['rounds']<2 or type(limit) not in (int,float) or at-check['first_seen']<=limit:
        raise WindowIsolationError('已登记未使用候选网络故障，等待原P85与两轮真实复核')
    def guard():
        _allowed(config,stopping);require_slot(config,browser,tid)
        if _fingerprint(snapshot_page(tid,page))!=key:
            raise WindowIsolationError('未使用候选在恢复前变化，保留页面')
        current,_=_records(root)
        if any(record.get('target_id')==tid for record in current.values()):
            raise WindowIsolationError('候选已有请求账本，禁止初始化恢复')
    guard()
    folder=path.parent/('initialization-fault-'+secrets.token_hex(8))
    hashes=_archive(folder,page,{'evidence':{'snapshot':snapshot}},None,guard)
    _journal(path,journal,candidate_initialization_archive=str(folder),candidate_initialization_hashes=hashes)
    guard();page.goto('https://chatgpt.com/',wait_until='commit',timeout=5000)
    return True


def _resume(config, browser, pool, path, journal, stopping, report):
    root = Path(config['catalog_path']).parent
    entries = pool['windows']
    old = journal['old_target_id']
    _allowed(config, stopping)
    registry, fingerprint = _registry(config)
    slot = next(slot for slot in registry['slots'] if slot['slot_id'] == journal['slot_id'])
    candidate_id = journal.get('candidate', {}).get('target_id')
    # A create_intent may have succeeded before its receipt was saved. Read
    # nonce metadata first, but never issue create again after this intent.
    live = read_window_inventory(browser)
    if not live.get('complete') or live.get('errors'):
        raise WindowIsolationError('补页恢复时实时清单不完整')
    hourly_request = _hourly_missing_slot_request(config, root, path, journal, registry, live)
    _authorized_missing_slot(root,path,journal,registry,live,fingerprint, hourly_request)
    if (registry['window_id'] != journal['window_id'] and registry.get('startup_request_id')
            and old not in live['targets'] and (not candidate_id or candidate_id not in live['targets'])
            and (not journal.get('nonce') or not any(t.get('url') == blank_url(journal['nonce']) for t in live['targets'].values()))):
        _journal(path,journal,'cancelled',reason='原窗口及原页/nonce候选均缺失，已由登记启动窗口替代；保留原请求与全部证据，不重发',
                 superseded_startup_request_id=registry['startup_request_id'])
        return
    recovered = _candidate(live, journal) if journal.get('nonce') else None
    if recovered:
        saved = journal.get('candidate', {})
        if candidate_id:
            if (candidate_id != recovered['target_id'] or
                    saved.get('window_id') != journal['window_id'] or
                    saved.get('nonce', journal['nonce']) != journal['nonce'] or
                    saved.get('url') != blank_url(journal['nonce'])):
                raise WindowIsolationError('已保存候选与实时nonce归属冲突，保留原回执')
            # A detach failure can leave the already-saved candidate in
            # create_unknown. Reconcile that exact operation, preserving its
            # cleanup receipt; never create another page or infer cleanup.
            if journal['state'] in ('create_intent', 'create_unknown'):
                _journal(path, journal, 'candidate_created', candidate=saved)
        else:
            candidate_id = recovered['target_id']
            _journal(path, journal, 'candidate_created', candidate={**recovered, 'nonce': journal['nonce']})
    inventory = _inventory(browser, registry, [candidate_id] if candidate_id else [])
    pages = enumerate_pages(browser)
    # A single unreadable renderer must not freeze every other page.  The exact
    # page this journal is about still has to be present and window-verified.
    if old in inventory['targets'] and old not in pages['pages']:
        raise WindowIsolationError('原Playwright页面清单不完整')
    if candidate_id and candidate_id in inventory['targets'] and candidate_id not in pages['pages']:
        raise WindowIsolationError('候选Playwright页面清单不完整')
    current_pages = pages['pages']
    if slot.get('target_id') == candidate_id and candidate_id:
        if slot.get('repair_id') != journal['id']:
            raise WindowIsolationError('槽位已由其他维护改变，不覆写')
        _journal(path, journal, 'registered', registry_after_sha256=fingerprint)
    else:
        _rebase_registry(path,journal,registry,fingerprint,pool,live)
        if slot.get('target_id') != old:
            raise WindowIsolationError('专用槽位登记CAS冲突，保留原页及候选')
    if journal['state'] in ('archived', 'close_intent'):
        _relocate_archived_ledgers(path, journal)
        if old in inventory['targets']:
            if inventory['targets'][old]['window_id'] != journal['window_id']:
                raise WindowIsolationError('原页已移出专窗，不关闭')
            require_slot(config, browser, old)
            original = journal['record']
            if original:
                _record_cas(original['_ledger_path'], original['_ledger_sha256'])
            for ledger_path, expected in journal.get('record_hashes', {}).items():
                _record_cas(ledger_path, expected)
            live_records,_ = _records(root)
            live_paths = [name for name,r in live_records.items() if r.get('target_id') == old]
            if journal.get('ledger_relocations') and set(live_paths) != set(journal['record_paths']):
                raise WindowIsolationError('原target全量账本与迁移后归档不一致，保留原页')
            health = classify(snapshot_page(old, current_pages[old]), journal['original_entry'], original,
                              urls=[target['url'] for target in inventory['targets'].values()],
                              previous=journal['baseline'], record_paths=live_paths,target_history_complete=True)
            fallback = False
            if journal.get('unrecoverable_fallback') and health['evidence']['fingerprint'] == journal['health']['evidence']['fingerprint']:
                health['bounded_recheck'] = journal['health'].get('bounded_recheck', {})
                fallback = stalled_page_fallback(config, health, journal['original_entry'], original, at=time.time())
            if journal.get('collective_unsent_restart') and health['evidence']['fingerprint']==journal['health']['evidence']['fingerprint']:
                from .collective_page_restart import eligible
                from .attempt_history import read_attempt
                fallback=eligible(health,journal['original_entry'],original,[read_attempt(p) for p in journal.get('record_paths',[])])
            if journal.get('failed_upload_restart') and health['evidence']['fingerprint']==journal['health']['evidence']['fingerprint']:
                from .collective_page_restart import failed_upload_eligible
                from .attempt_history import read_attempt
                recovery_policy=config.get('web_cards',{}).get('shared_window',{}).get('health_repair',{})
                network=read_record(root/'web-upload-network.json').get('errors',[])
                fallback=failed_upload_eligible(recovery_policy,health,journal['original_entry'],original,
                    [read_attempt(p) for p in journal.get('record_paths',[])],network,time.time())
            if journal.get('terminal_empty_restart'):
                fallback = _terminal_empty_restart(config, health, original, previous=journal['health'], at=time.time())
            if journal.get('hourly_idle_restart'):
                fallback = _hourly_idle_restart(config, health, journal['original_entry'], original,
                    previous=journal['health'], at=time.time())
            if (not health['replace_allowed'] and not fallback) or health['health'] != journal['health']['health']:
                if journal['state']=='archived' and not journal.get('nonce') and not journal.get('candidate'):
                    # No close/create intent exists. Retire this stale plan so
                    # future cycles can collect fresh evidence instead of
                    # excluding the target forever. Never reuse its old proof.
                    for name,expected in journal['archive_hashes'].items():
                        if _sha(path.parent/'diagnostics'/name)!=expected:
                            raise WindowIsolationError('取消过期修复前原归档变化')
                    _allowed(config,stopping);require_slot(config,browser,old)
                    before=path.read_bytes();digest=hashlib.sha256(before).hexdigest()
                    preserved=path.parent/'superseded-plans'/(digest+'.json')
                    if preserved.exists() and _sha(preserved)!=digest:
                        raise WindowIsolationError('过期修复计划的保存物变化')
                    if not preserved.exists():atomic_bytes(preserved,before)
                    entry=entries.get(old,{})
                    if entry.get('state')=='repair_pending' and entry.get('repair_id')==journal['id']:
                        entry.update(state='needs_inspection');entry.pop('repair_id',None)
                        entry.pop('repair_in_progress',None)
                        _persist_pool(root,pool)
                    _journal(path,journal,'cancelled',cancelled_before_close=True,
                        reason='关闭意图前页面证据变化；保留原页，退出旧计划后重新实查',
                        superseded_plan=str(preserved),superseded_plan_sha256=digest,
                        replacement_recheck={'health':health['health'],
                            'fingerprint':health['evidence']['fingerprint'],
                            'checked_at':health['evidence']['checked_at']})
                    report.setdefault('cancelled_before_close',[]).append(old)
                    return
                raise WindowIsolationError('关闭前原页健康证据变化，保留原页')
            for name, expected in journal['archive_hashes'].items():
                if _sha(path.parent / 'diagnostics' / name) != expected:
                    raise WindowIsolationError('关闭前归档证据变化')
            _allowed(config, stopping)
            entries[old].update(state='repair_pending', repair_id=journal['id'])
            _persist_pool(root, pool)
            _journal(path, journal, 'close_intent')
            current_pages[old].close()
        inventory = _inventory(browser, registry, [candidate_id] if candidate_id else [])
        if old in inventory['targets']:
            raise WindowIsolationError('关闭回执尚未证实，禁止开新页')
        _journal(path, journal, 'closed_confirmed')
    if journal['state'] == 'closed_confirmed':
        _allowed(config, stopping)
        inventory = _inventory(browser, registry)
        if old in inventory['targets']:
            raise WindowIsolationError('原target仍实时存在，禁止补页')
        _journal(path, journal, 'create_intent', nonce=journal.pop('authorized_creation_nonce',None) or secrets.token_hex(16))
        owned = {s['target_id'] for s in registry['slots'] if s.get('target_id')}

        def created(candidate):
            _journal(path, journal, 'candidate_created', candidate=candidate)

        try:
            candidate = create_in_window(browser, journal['window_id'], root=path.parent / 'extension',
                                         nonce=journal['nonce'], owned_ids=owned, on_created=created,
                                         stopping=lambda: stopping() or not _maintenance_allowed(config))
            _journal(path, journal, 'candidate_created', candidate=candidate)
        except Exception as exc:
            if getattr(exc, 'candidate', None):
                created({**exc.candidate, 'extension_cleanup_error': getattr(exc, 'extension_cleanup_error', None),
                         'extension_source_path': getattr(exc, 'extension_source_path', None)})
            else:
                _journal(path, journal, 'create_unknown', error=str(exc)[:500],
                         extension_cleanup_error=getattr(exc, 'extension_cleanup_error', None),
                         extension_source_path=getattr(exc, 'extension_source_path', None))
            raise
        candidate_id = candidate['target_id']
    if journal['state'] in ('create_intent', 'create_unknown'):
        # Never repeat an unacknowledged chrome.tabs.create operation.
        raise WindowIsolationError('创建回执不确定，仅按原nonce等待唯一候选，不重复补页')
    if journal['state'] == 'candidate_created':
        _allowed(config, stopping)
        candidate_id = journal['candidate']['target_id']
        registry, fingerprint = _registry(config)
        inventory = _inventory(browser, registry, [candidate_id])
        target = inventory['targets'].get(candidate_id)
        if (not target or target['window_id'] != journal['window_id'] or
                target['url'] != blank_url(journal['nonce'])):
            raise WindowIsolationError('新候选nonce或原窗口不一致，保留待核对')
        _rebase_registry(path,journal,registry,fingerprint,pool,inventory)
        entries.setdefault(candidate_id, {'state': 'opening', 'origin': 'shared_page_health_repair',
                                          'repair_id': journal['id'], 'never_submitted': True})
        _persist_pool(root, pool)
        slot = next(s for s in registry['slots'] if s['slot_id'] == journal['slot_id'])
        if slot.get('target_id') != old:
            raise WindowIsolationError('更换前原槽位target变化')
        slot.setdefault('replacement_history', []).append({'target_id': old, 'repair_id': journal['id'],
            'retired_at': time.time(), 'health': journal['health']['health'], 'diagnostics': str(path.parent / 'diagnostics')})
        slot.update(target_id=candidate_id, state='opening', repair_id=journal['id'],
                    generation=int(slot.get('generation', 0)) + 1)
        registry['revision'] = int(registry.get('revision', 0)) + 1
        _allowed(config, stopping)
        if _sha(registry_path(config)) != fingerprint:
            raise WindowIsolationError('登记写入前CAS冲突')
        atomic_json(registry_path(config), registry)
        _journal(path, journal, 'registered', registry_after_sha256=_sha(registry_path(config)))
    if journal['state'] == 'registered':
        _allowed(config, stopping)
        candidate_id = journal['candidate']['target_id']
        entries.setdefault(old, {}).update(state='retired_replaced', repair_id=journal['id'], retired_at=time.time())
        new = entries.setdefault(candidate_id, {'state': 'opening', 'origin': 'shared_page_health_repair',
                                                'repair_id': journal['id'], 'never_submitted': True})
        _persist_pool(root, pool)
        if journal.get('candidate', {}).get('extension_uninstalled') is False:
            require_slot(config, browser, candidate_id)
            try:
                proof = _confirm_cleanup(browser, path.parent/'extension',
                                         stopping=lambda: stopping() or not _maintenance_allowed(config))
            except Exception as exc:
                original_error = (journal['candidate'].get('extension_cleanup_error')
                                  or journal.get('extension_cleanup_error') or '卸载回执未证实')
                raise WindowIsolationError('临时扩展核对失败，新候选保留opening：' +
                                           str(original_error) + '；' + str(exc)) from exc
            _allowed(config, stopping)
            _journal(path, journal, extension_cleanup_recovery={**proof,
                'original_candidate': copy.deepcopy(journal['candidate']),
                'original_error': journal.get('extension_cleanup_error')},
                candidate={**journal['candidate'], 'extension_uninstalled': True,
                           'extension_cleanup_error': None}, extension_cleanup_error=None)
        if journal.get('candidate', {}).get('extension_cleanup_error') or journal.get('extension_cleanup_error'):
            raise WindowIsolationError('临时扩展卸载失败，新候选保留opening：' +
                str(journal.get('candidate', {}).get('extension_cleanup_error') or journal['extension_cleanup_error']))
        if journal.get('candidate', {}).get('extension_uninstalled') is False:
            raise WindowIsolationError('临时扩展卸载回执未证实，新候选保留opening')
        require_slot(config, browser, candidate_id)
        pages = enumerate_pages(browser)
        if not pages['complete'] or candidate_id not in pages['pages']:
            raise WindowIsolationError('新候选Playwright回执缺失，保留opening')
        page = pages['pages'][candidate_id]
        before = snapshot_page(candidate_id, page)
        _journal(path,journal,candidate_observation=before)
        if before.get('verification') or before.get('login'):
            _manual_block(root, candidate_id)
            raise WindowIsolationError('新页要求登录/验证，保留opening原页')
        if page.url == blank_url(journal['nonce']):
            _allowed(config, stopping)
            page.goto('https://chatgpt.com/', wait_until='commit', timeout=5000)
        elif page.url.rstrip('/') != 'https://chatgpt.com' and not _retry_unused_candidate(
                config,browser,root,path,journal,new,page,before,stopping):
            raise WindowIsolationError('新候选URL变化，不导航未知页面')
        require_slot(config, browser, candidate_id)
        ready = snapshot_page(candidate_id, page)
        if ready.get('site_blocked'):
            # Cloudflare "Unable to load site" is an egress-IP block, not a
            # missing composer. Retry the page slowly instead of treating the
            # candidate as permanently unready or opening another page.
            last = journal.get('network_reload_at', 0)
            if time.time() - last >= 300:
                _allowed(config, stopping)
                require_slot(config, browser, candidate_id)
                _journal(path, journal, network_reload_at=time.time())
                try:
                    page.goto('https://chatgpt.com/', wait_until='domcontentloaded', timeout=15000)
                except Exception as exc:
                    _journal(path, journal, network_reload_error=str(exc)[:300])
                ready = snapshot_page(candidate_id, page)
            if ready.get('site_blocked'):
                _journal(path, journal, network_block=ready.get('errors') or [])
                raise WindowIsolationError('站点按IP拦截：Unable to load site；等待网络恢复，不重复建页')
        if ready.get('login') or ready.get('verification'):
            _manual_block(root, candidate_id)
        if (new.get('never_submitted') is True and new.get('origin')=='shared_page_health_repair'
                and (ready.get('draft','').strip() or ready.get('attachments'))):
            # A nonce-created, still-opening page can restore the site's old
            # pipeline draft. Archive it; no task has been allowed to use it.
            from .collective_page_restart import eligible
            proof_entry={**new,'startup_request_id':journal['nonce'],'_material_root':str(root)}
            fragment_only = (not ready.get('attachments') and
                             _known_prompt_fragment(str(ready.get('draft',''))))
            if (new.get('repair_id')!=journal['id'] or
                    (not eligible({'health':'dirty','evidence':{'snapshot':ready}},
                                  proof_entry,None,[]) and not fragment_only)):
                raise WindowIsolationError('新页恢复的草稿或附件归属不明，保留opening')
            def candidate_guard():
                _allowed(config,stopping);require_slot(config,browser,candidate_id)
                current=snapshot_page(candidate_id,page)
                if (current.get('draft')!=ready.get('draft') or current.get('attachment_names')!=ready.get('attachment_names')
                    or current.get('user_texts') or current.get('answer_texts') or current.get('streaming') is not False
                    or current.get('login') or current.get('verification') or current.get('quota')):
                    raise WindowIsolationError('新候选在归档期间变化，保留页面')
            archive=path.parent/('restored-candidate-'+secrets.token_hex(8))
            hashes=_archive(archive,page,{'evidence':{'snapshot':ready}},None,candidate_guard)
            candidate_guard()
            _journal(path,journal,candidate_draft_archive=str(archive),candidate_draft_archive_hashes=hashes)
            from web_gpt.core import wait_prompt_box,_composer
            box=wait_prompt_box(page,timeout=3000);scope=_composer(page,box)
            for name in ready.get('attachment_names',[]):
                for label in ('移除 '+name,'Remove '+name):
                    buttons=scope.get_by_role('button',name=label,exact=True)
                    while buttons.count():
                        _allowed(config,stopping);require_slot(config,browser,candidate_id)
                        buttons.first.evaluate('(el)=>el.click()');page.wait_for_timeout(200)
            from .web_editor_input import replace
            _allowed(config,stopping);require_slot(config,browser,candidate_id);replace(box,'')
            ready=snapshot_page(candidate_id,page)
        if (ready.get('inspection_complete') is not True or ready.get('login') or ready.get('verification') or
                ready.get('quota') or ready.get('streaming') is not False or ready.get('user_texts') or
                ready.get('answer_texts') or ready.get('draft', '').strip() or ready.get('attachments', 0)):
            raise WindowIsolationError('新主页非已核对空白或要求用户操作，保留opening')
        from web_gpt.core import wait_prompt_box
        _allowed(config, stopping)
        require_slot(config, browser, candidate_id)
        box = wait_prompt_box(page, timeout=5000)
        if not box.is_visible():
            raise WindowIsolationError('新主页输入框未真实显示，保留opening')
        _allowed(config, stopping)
        new.update(state='ready_blank', adopted=time.time())
        _persist_pool(root, pool)
        _journal(path, journal, 'ready', new_target_id=candidate_id, ready_snapshot=ready)
        report['replaced'].append({'slot_id': journal['slot_id'], 'old_target_id': old,
                                   'new_target_id': candidate_id, 'journal': str(path)})


def _maintenance_allowed(config):
    try:
        _allowed(config, lambda: False)
        return True
    except Exception:
        return False


def _manual_block(root, tid):
    path = root / 'web-channel-control.json'
    def merge_locked(proposed):
        previous = read_record(path).get('chatgpt', {})
        if previous.get('manual_verification_required'):
            proposed['chatgpt'] = previous
        else:
            proposed['chatgpt'] = {**previous, **proposed['chatgpt']}
    mutate_record(path, {'chatgpt': {
        'manual_verification_required': True, 'reason': '共享页检查发现登录或访问验证',
        'observed': time.time(), 'target_id': tid}}, event='shared_page_manual_verification', validate=merge_locked)


def bounded_recheck(health, previous, ledger, entry, reread, *, at, rounds=None, interval=30):
    """Recheck unchanged evidence after distinct scheduled inspection rounds."""
    if health.get('health') not in ('unknown', 'saved_response_protected'):
        return health
    if rounds is not None and health.get('evidence', {}).get('snapshot', {}).get('inspection_complete') is not True:
        return health  # Failed observation never counts as a real inspection round.
    key = hashlib.sha256(json.dumps([health.get('evidence', {}).get('fingerprint'),
        (ledger or {}).get('_ledger_sha256'), entry.get('raw_sha256')]).encode()).hexdigest()
    prior = (previous or {}).get('bounded_recheck', {})
    check = dict(prior) if prior.get('key') == key else {'key':key,'first_seen':at,'state':'waiting','reads':0}
    if rounds is not None:
        if 'rounds' not in check:
            check.update(rounds=1, last_round_at=at)
        elif at-check['last_round_at'] >= max(10, interval):
            check.update(rounds=check['rounds']+1, last_round_at=at)
        due = check['rounds'] >= rounds
    else:
        due = at-check['first_seen'] >= 60
    if check['reads'] == 0 and due:
        fresh = reread()
        if rounds is not None and fresh.get('evidence', {}).get('fingerprint') != health.get('evidence', {}).get('fingerprint'):
            # The extra read found a changed page; it has not stalled for two rounds.
            return bounded_recheck(fresh, None, ledger, entry, reread,
                                   at=at, rounds=rounds, interval=interval)
        check.update(reads=1,checked_at=time.time(),state='still_protected' if fresh.get('health') in
            ('unknown','saved_response_protected') else 'reconciled',reason=fresh.get('reason'))
        health = fresh
    health['bounded_recheck'] = check
    return health


def stalled_page_fallback(config, health, entry, record, *, at):
    """Authorized page replacement only; never authorize retry of its request."""
    policy = config.get('web_cards', {}).get('shared_window', {}).get('health_repair', {})
    if policy.get('replace_unrecoverable_pages') is not True:
        return False
    if health.get('health') not in ('unknown', 'saved_response_protected') or health.get('collect_allowed'):
        return False
    check = health.get('bounded_recheck', {})
    snapshot = health.get('evidence', {}).get('snapshot', {})
    rounds = policy.get('stalled_check_rounds')
    due = (check.get('rounds', 0) >= max(2, rounds) if type(rounds) is int else
           at-check.get('first_seen',at) >= max(120,policy.get('unrecoverable_after_seconds',120)))
    if policy.get('stalled_after_seconds_by_lane'):
        from .stall_timeouts import timeout_seconds
        seconds=timeout_seconds(policy,entry,record)
        due=due and seconds is not None and at-check.get('first_seen',at)>seconds
    if check.get('state') != 'still_protected' or check.get('reads') != 1 or not due:
        return False
    if (snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False or
            snapshot.get('draft','').strip() or
            any(snapshot.get(k) for k in ('login', 'verification', 'quota', 'attachments'))):
        return False
    # A target-bound request supplies ownership; a live producer is never a fault.
    return bool(record and record.get('target_id') == snapshot.get('target_id') and
                entry.get('owned') is not False and
                entry.get('state') not in ('busy', 'submitting', 'collecting', 'preparing', 'uploading'))


def _idle_homepage(snapshot):
    """True only for a fully read, empty, non-streaming ChatGPT home page."""
    return (snapshot.get('inspection_complete') is True
            and snapshot.get('streaming') is False and snapshot.get('uploading') is False
            and not snapshot.get('user_texts') and not snapshot.get('answer_texts')
            and not snapshot.get('attachments') and not str(snapshot.get('draft', '')).strip()
            and not any(snapshot.get(k) for k in ('login', 'verification', 'quota'))
            and str(snapshot.get('url', '')).rstrip('/') == 'https://chatgpt.com')


def clear_proven_unsent_draft(root, page, entry, snapshot):
    """Clear an exact archived, never-sent prompt from an idle slot.

    The draft is preserved first. Only an exact prompt/attempt match with
    ``state=not_sent`` and ``send_click_started=false`` is eligible; anything
    else keeps the page and its draft untouched.
    """
    from .restored_web_draft import clear, evidence
    from web_gpt.core import wait_prompt_box
    if entry.get('state') != 'ready_blank' or not _idle_homepage({**snapshot, 'draft': ''}):
        return False
    draft = str(snapshot.get('draft') or '')
    if not draft.strip():
        return False
    proof = evidence(root, draft)
    if not proof:
        return False
    attempt = json.loads(Path(proof['attempt_path']).read_text())
    if attempt.get('state') != 'not_sent' or attempt.get('send_click_started') is not False:
        return False
    entry['never_submitted'] = True
    entry.setdefault('startup_request_id', 'unsent-' + proof['prompt_sha256'][:16])
    box = wait_prompt_box(page, timeout=3000)
    return clear(root, page, entry, box, draft, 0, 0, False)


def _draft_identity(draft):
    """Return (lane, job_id) from the frozen material marker, if present."""
    import re
    match = re.search(r'材料标识 (?:web-card-([0-9a-f-]{36})|card-review-([A-Za-z0-9_-]+))', draft)
    if not match:
        return None
    return ('card', match.group(1)) if match.group(1) else ('review', match.group(2))


_PROMPT_FRAGMENT_HEADS = (
    '你是独立论文阅读卡片评审',
    '你是严格的论文阅读卡片评审',
    '仅依据附件完整原文独立生成中文论文阅读卡片',
    '你是一名严谨的科研文献阅读助手',
)


def _known_prompt_fragment(draft):
    """Site-restored fragments begin with our frozen prompt headings."""
    text = draft.lstrip()
    return any(text.startswith(head) for head in _PROMPT_FRAGMENT_HEADS)


def stale_draft_eligible(root, entry, draft):
    """A restored draft may be cleared only when its job is not active here."""
    identity = _draft_identity(draft)
    if entry.get('active_paper_id') or entry.get('correction_id') or entry.get('job_id'):
        return False
    if not identity:
        # A new tab can restore only the first line of a prompt. That fragment
        # has no material marker, but the heading proves it is ours, not a user
        # draft; the caller still requires an idle page with no attachments.
        return _known_prompt_fragment(draft)
    lane, job_id = identity
    import sqlite3
    try:
        db = sqlite3.connect('file:' + str(Path(root) / 'catalog.sqlite3') + '?mode=ro',
                             uri=True, timeout=3)
        try:
            if lane == 'card':
                row = db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?', (job_id,)).fetchone()
            else:
                row = db.execute('SELECT state FROM card_review_jobs WHERE id=?', (job_id,)).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return False
    active = ('preparing', 'busy', 'submitting', 'submitted', 'collecting')
    return not row or row[0] not in active


def clear_stale_draft(root, page, entry, snapshot):
    """Archive and clear a restored draft whose job is not active on this slot.

    Used for copies restored after a page was replaced, for prompts from an
    older prompt revision, and for jobs already completed elsewhere. The page
    must be idle with no user message, answer, attachment or generation.
    """
    from .web_editor_input import replace
    from web_gpt.core import wait_prompt_box, _box_text
    if entry.get('state') not in ('ready_blank', 'needs_inspection') or not _idle_homepage(
            {**snapshot, 'draft': ''}):
        return False
    draft = str(snapshot.get('draft') or '')
    if not stale_draft_eligible(root, entry, draft):
        return False
    folder = (Path(root) / 'stale-draft-cleanups' /
              str(snapshot.get('target_id') or 'unknown') / str(time.time_ns()))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'draft.txt').write_text(draft)
    atomic_json(folder / 'snapshot.json', snapshot)
    box = wait_prompt_box(page, timeout=3000)
    replace(box, '')
    if _box_text(box).strip():
        atomic_json(folder / 'clear-failed.json', {'reason': 'editor still has text',
                                                   'checked_at': time.time()})
        return False
    atomic_json(folder / 'cleared.json', {'identity': _draft_identity(draft),
                                          'cleared_at': time.time()})
    return True


def run_once(config, browser, pool, *, stopping=None, lock_factory=None, on_checked_page=None, excluded_targets=(), target_lease=None):
    """Check/recover one owner's fixed slots; preserve the supplied windows dict.

    Reports ``counts/available/protected/replaced/repaired_paths/collected`` and
    errors plus pending repair targets. An optional owner callback reconciles
    exact leases immediately under the same submission lock. Scientific cards
    are not edited; sent requests are never reclassified as unsent or resent.
    ``lock_factory(timeout=5)`` may be the owner's responsive submission lock;
    the fallback uses the unchanged public web_gpt environment/default lock.
    """
    root = Path(config['catalog_path']).parent
    report = {'checked_at': time.time(), 'state': 'checking', 'counts': {}, 'available': 0,
              'protected': 0, 'replaced': [], 'repaired_paths': [], 'collected': [],
              'errors': [], 'pending_repair_targets': []}
    stopping = stopping or (lambda: False)
    from contextlib import nullcontext
    independent_maintenance=target_lease is not None
    target_lease = target_lease or (lambda tid: nullcontext(True))
    policy = config.get('web_cards', {}).get('shared_window', {}).get('health_repair', {})
    if not policy.get('enabled'):
        report['state'] = 'disabled'
        return report
    health_path = root / 'shared-page-health.json'
    journal_root = root / 'shared-page-repairs'
    try:
        _allowed(config, stopping)
        from .shared_pool_store import PoolSnapshot, PoolConflict
        if not isinstance(pool,PoolSnapshot):pool=PoolSnapshot(pool)
        entries = pool['windows']
        if not isinstance(entries, dict):
            raise ValueError('原页池windows损坏')
        previous = read_record(health_path)
        interval = max(10, int(policy.get('check_interval_seconds', 30)))
        composer_failures = dict(previous.get('composer_failures') or {})
        network_reloads = dict(previous.get('network_reloads') or {})
        journals = [(p, json.loads(p.read_text())) for p in journal_root.glob('*/journal.json')]
        pending = [(p, j) for p, j in journals if j.get('state') not in TERMINAL_JOURNALS]
        report['pending_repair_targets'] = sorted({j['old_target_id'] for _, j in pending} |
            {j['candidate']['target_id'] for _, j in pending if j.get('candidate')})
        if not pending and report['checked_at'] - previous.get('checked_at', 0) < interval:
            return {**previous, 'state': 'waiting_interval'}
        if lock_factory is None:
            from web_gpt.submission import submission_lock
            lock_factory = submission_lock
        acquired=False
        with (nullcontext() if independent_maintenance else lock_factory(timeout=5)):
            acquired=True
            _allowed(config, stopping)
            registry, registry_sha = _registry(config)
            candidates = [j['candidate']['target_id'] for _, j in pending if j.get('candidate')]
            # Discover an unacknowledged candidate using its persisted nonce
            # before checking otherwise-foreign pages in the dedicated window.
            inventory = read_window_inventory(browser)
            if not inventory.get('complete') or inventory.get('errors'):
                raise WindowIsolationError('实时专窗清单不完整')
            for _, journal in pending:
                if journal.get('nonce'):
                    found = _candidate(inventory, journal)
                    if found:
                        candidates.append(found['target_id'])
            inventory = _inventory(browser, registry, candidates)
            from .collective_page_restart import active as collective_active, eligible as collective_eligible
            episode_path=root/'collective-restart-episode.json'
            episode=read_record(episode_path)
            registered_ids={slot.get('target_id') for slot in registry['slots']}
            from .collective_page_restart import episode_targets as reconcile_episode_targets
            episode_targets=reconcile_episode_targets(policy,previous,episode.get('targets',[]),registered_ids,time.time())
            fresh_mass_restart=collective_active(policy,previous,time.time())
            mass_restart=fresh_mass_restart or bool(episode_targets)
            if episode_targets:atomic_json(episode_path,{'targets':sorted(episode_targets),'updated':time.time()})
            maximum = min(20 if mass_restart else 2, max(0, int(policy.get('collective_max_replacements_per_cycle',20) if mass_restart else policy.get('max_replacements_per_cycle',2))))
            report['collective_restart_triggered']=mass_restart
            # Existing nonce-bound repairs are completions, not new reopen
            # quota. Retry least-recently checked first so old retained
            # journals cannot starve newly registered replacements.
        pending.sort(key=lambda pair:pair[1].get('updated',pair[1].get('created',0)))
        for path, journal in pending[:min(20,len(pending)) if maximum else 0]:
            try:
                with target_lease(journal['old_target_id']) as available:
                    if not available:continue
                    with (nullcontext() if independent_maintenance else lock_factory(timeout=5)):
                        _allowed(config,stopping)
                        _resume(config, browser, pool, path, journal, stopping, report)
            except Exception as exc:
                report['errors'].append({'target_id': journal['old_target_id'], 'reason': str(exc)[:500]})
                _journal(path, journal, error=str(exc)[:500])
        registry, registry_sha = _registry(config)
        inventory = _inventory(browser, registry, candidates)
        pages = enumerate_pages(browser)
        # Health checks are per target and skip unreadable pages; one slow or
        # closed renderer must not stop replacement of the other slots.
        if not pages['complete']:
            report['inventory_incomplete'] = pages.get('errors', [])
        records, latest = _records(root)
        records_by_target = {}
        for ledger_path, record in records.items():
            records_by_target.setdefault(record.get('target_id'), []).append(ledger_path)
        urls = [target['url'] for target in inventory['targets'].values()]
        healths = {}
        pending_old = {j['old_target_id'] for _, j in pending if j.get('state') not in TERMINAL_JOURNALS}
        pending_new = {j['candidate']['target_id'] for _, j in pending
                       if j.get('state') not in TERMINAL_JOURNALS and j.get('candidate')}
        started = 0 # Existing nonce completions do not consume new reset quota.
        from .shared_page_health import _snapshot_pages
        checked_pages={}
        for checked_slot in registry['slots']:
            target_id=checked_slot.get('target_id')
            entry_now=entries.get(target_id,{})
            if (not target_id or target_id in excluded_targets or target_id in pending_old | pending_new
                or entry_now.get('state')=='repair_pending' or
                entry_now.get('state')=='opening' and not entry_now.get('startup_request_id')):continue
            page_now=pages['pages'].get(target_id)
            if page_now is None:continue
            try:require_slot(config,browser,target_id)
            except Exception as exc:
                report['errors'].append({'target_id':target_id,'stage':'snapshot_window_guard','reason':str(exc)[:500]})
                continue
            checked_pages[target_id]=page_now
        snapshots=_snapshot_pages(checked_pages,reader=snapshot_page)
        for slot in registry['slots']:
            tid = slot.get('target_id')
            if tid in excluded_targets:
                report.setdefault('deferred_upload_targets',[]).append(tid)
                report['protected'] += 1
                continue
            target = inventory['targets'].get(tid)
            if not tid or not target or target['window_id'] != registry['window_id']:
                report['protected'] += 1
                continue
            if tid in pending_old | pending_new or entries.get(tid, {}).get('state') == 'repair_pending' or (
                    entries.get(tid, {}).get('state') == 'opening' and not entries.get(tid, {}).get('startup_request_id')):
                report['protected'] += 1
                continue
            try:
                with target_lease(tid) as available:
                    if not available:
                        report.setdefault('deferred_upload_targets',[]).append(tid)
                        report['protected']+=1
                        continue
                    with (nullcontext() if independent_maintenance else lock_factory(timeout=5)):
                        _allowed(config,stopping)
                        require_slot(config, browser, tid)
                        page = pages['pages'].get(tid)
                        if not page:
                            report['protected'] += 1
                            continue
                        snapshot = snapshots.get(tid) or snapshot_page(tid,page)
                        if snapshot.get('inspection_complete') is not True and snapshot.get('inspection_error'):
                            raise RuntimeError(snapshot['inspection_error'])
                        if (snapshot.get('site_blocked') and
                                str(snapshot.get('url', '')).rstrip('/') == 'https://chatgpt.com' and
                                not str(snapshot.get('draft', '')).strip()):
                            # A Cloudflare IP block is not a dirty page. Retry a
                            # reload at most every five minutes; keep the slot.
                            last = network_reloads.get(tid, 0)
                            if time.time() - last >= 300:
                                _allowed(config, stopping)
                                require_slot(config, browser, tid)
                                try:
                                    page.goto('https://chatgpt.com/', wait_until='domcontentloaded',
                                              timeout=15000)
                                    network_reloads[tid] = time.time()
                                    report.setdefault('network_block_reloads', []).append(tid)
                                except Exception as exc:
                                    report.setdefault('network_reload_errors', []).append(
                                        {'target_id': tid, 'reason': str(exc)[:300]})
                                snapshot = snapshot_page(tid, page)
                        from .web_message_text import expand_original_user
                        expansion = expand_original_user(page, latest.get(tid), snapshot, target_id=tid)
                        if expansion:
                            report.setdefault('prompt_expansions', []).append(expansion)
                            if expansion['state'] == 'expanded':
                                snapshot = snapshot_page(tid, page)
                        entry = entries.get(tid, {})
                        if str(snapshot.get('draft') or '').strip() and _idle_homepage(
                                {**snapshot, 'draft': ''}):
                            # A prepared-but-never-sent draft is not a reason to
                            # keep the page idle forever. Exact unsent evidence
                            # comes first; a restored/stale prompt is cleared
                            # only when its job is not active on this slot.
                            _allowed(config, stopping)
                            require_slot(config, browser, tid)
                            if clear_proven_unsent_draft(root, page, entry, snapshot):
                                _persist_pool(root, pool)
                                snapshot = snapshot_page(tid, page)
                                report.setdefault('cleared_unsent_drafts', []).append(tid)
                            elif clear_stale_draft(root, page, entry, snapshot):
                                if entry.get('state') == 'needs_inspection' and not records_by_target.get(tid):
                                    # A replacement page with only a site-restored
                                    # fragment has no target history; once cleared it
                                    # is a verified blank slot, not a task page.
                                    from .shared_pool_store import mark_verified_blank
                                    mark_verified_blank(entry)
                                    entry['recovered_restored_fragment_at'] = time.time()
                                    _persist_pool(root, pool)
                                snapshot = snapshot_page(tid, page)
                                report.setdefault('cleared_stale_drafts', []).append(tid)
                        prior = previous.get('pages', {}).get(tid)
                        recovered = _restore_displaced_review(config,browser,pool,slot,page,snapshot,prior,urls,records,stopping)
                        if not recovered:
                            recovered = _recover_orphan_review(config,browser,pool,slot,page,snapshot,prior,urls,records,stopping)
                        if recovered:
                            records[recovered['_ledger_path']]=recovered;latest[tid]=recovered
                            records_by_target.setdefault(tid,[]).append(recovered['_ledger_path'])
                            report.setdefault('recovered_orphan_reviews',[]).append({'target_id':tid,'review_id':recovered['review_id']})
                        from .shared_claim_recovery import abandoned_unsent
                        abandoned=latest.get(tid) and abandoned_unsent(latest[tid],root,at=time.time())
                        if abandoned and latest[tid].get('state')=='ready' and snapshot.get('inspection_complete') is True:
                            original=latest[tid]
                            from .collective_page_restart import eligible as unsent_eligible
                            preview_record={**original,'state':'not_sent'}
                            preview=classify(snapshot,entry,preview_record,urls=urls,
                                record_paths=records_by_target.get(tid,()),target_history_complete=True)
                            if unsent_eligible(preview,entry,preview_record,[records[p] for p in records_by_target.get(tid,())]):
                                # The old process has exited, and its pre-click ledger
                                # plus live empty user history prove this request unsent.
                                _allowed(config,stopping);require_slot(config,browser,tid)
                                _record_cas(original['_ledger_path'],original['_ledger_sha256'])
                                fresh=snapshot_page(tid,page)
                                if fresh!=snapshot and classify(fresh,entry,preview_record,urls=urls)['evidence']['fingerprint']!=preview['evidence']['fingerprint']:
                                    raise WindowIsolationError('旧所有者未发送页证据变化')
                                folder=root/'abandoned-unsent-evidence'/original['_ledger_sha256']
                                folder.mkdir(parents=True,exist_ok=True)
                                before=folder/'attempt-before.json'
                                if not before.exists():atomic_bytes(before,Path(original['_ledger_path']).read_bytes())
                                if _sha(before)!=original['_ledger_sha256']:raise WindowIsolationError('原未发送证据归档变化')
                                atomic_json(folder/'page-before.json',snapshot)
                                ended={k:v for k,v in original.items() if not k.startswith('_')}
                                ended.update(state='not_sent',finished=time.time(),error='旧所有者已退出，原账本明确未点击发送',
                                    dead_owner_evidence=str(folder))
                                atomic_json(original['_ledger_path'],ended)
                                from .attempt_history import read_attempt
                                current=read_attempt(original['_ledger_path'])
                                records[current['_ledger_path']]=current;latest[tid]=current
                                report.setdefault('ended_abandoned_unsent',[]).append(tid)
                        if abandoned and entry.get('state') in ('busy','submitting','collecting','preparing'):
                            preview=classify(snapshot,{**entry,'state':'needs_inspection'},latest.get(tid),urls=urls,
                                previous=prior,record_paths=records_by_target.get(tid,()))
                            if preview.get('health')=='healthy_blank' and preview.get('evidence',{}).get('completed_history_paths'):
                                from .shared_pool_store import mark_verified_blank
                                _allowed(config,stopping)
                                require_slot(config,browser,tid)
                                for ledger_path in records_by_target.get(tid,()):
                                    _record_cas(ledger_path,records[ledger_path]['_ledger_sha256'])
                                fresh=classify(snapshot_page(tid,page),{**entry,'state':'needs_inspection'},latest.get(tid),
                                    urls=urls,record_paths=records_by_target.get(tid,()))
                                if fresh.get('health')=='healthy_blank':
                                    mark_verified_blank(entry)
                                    entry.pop('error',None)
                                    entry['abandoned_owner_blank_verified_at']=time.time()
                                    _persist_pool(root,pool)
                        if _restorable_repair_blank(root,slot,entry,snapshot,records_by_target.get(tid,()),registry['window_id']):
                            _allowed(config,stopping)
                            require_slot(config,browser,tid)
                            entry.update(state='ready_blank',restored_missing_blank_at=time.time())
                            entry.pop('error',None)
                            _persist_pool(root,pool)
                        health = classify(snapshot, entry, latest.get(tid), urls=urls, previous=prior,
                                          record_paths=records_by_target.get(tid, ()), history_roots=(),target_history_complete=True)
                        if (latest.get(tid,{}).get('_collection_recovery')
                                and health['health']!='terminal_empty'):
                            # Side replies belong exclusively to the original
                            # observer/promoter. Health may retire a proven empty
                            # terminal, but cannot publish/rebind/reuse its body.
                            health.update(collect_allowed=False,replace_allowed=False)
                            healths[tid]=health;report['protected']+=1
                            continue
                        health = bounded_recheck(health, prior, latest.get(tid), entry,
                            lambda: classify(snapshot_page(tid,page),entry,latest.get(tid),urls=urls,previous=prior,
                                record_paths=records_by_target.get(tid,()),history_roots=(),target_history_complete=True), at=time.time(),
                            rounds=policy.get('stalled_check_rounds'), interval=interval)
                        terminal_empty_restart = _terminal_empty_restart(config, health, latest.get(tid),
                            previous=prior, at=time.time())
                        hourly_restart = _hourly_idle_restart(config, health, entry, latest.get(tid),
                            previous=prior, at=time.time())
                        if (health.get('health') == 'protected'
                                and snapshot.get('composer_available') is False
                                and not snapshot.get('site_blocked')
                                and _idle_homepage(snapshot)):
                            # A blank home page without a usable composer is a
                            # browser-check failure. Reload once after two real
                            # observations instead of holding it forever.
                            from .shared_page_health import _fingerprint
                            key = _fingerprint(snapshot)
                            prior_failure = composer_failures.get(tid) or {}
                            rounds = (prior_failure.get('rounds', 0) + 1
                                      if prior_failure.get('key') == key else 1)
                            if rounds >= 2 and time.time() - prior_failure.get('at', 0) >= interval:
                                _allowed(config, stopping)
                                require_slot(config, browser, tid)
                                folder = root / 'composer-page-refreshes' / tid / str(int(time.time()))
                                folder.mkdir(parents=True, exist_ok=True)
                                atomic_json(folder / 'before.json', snapshot)
                                try:
                                    page.reload(wait_until='domcontentloaded', timeout=15000)
                                    report.setdefault('reloaded_pages', []).append(tid)
                                    composer_failures.pop(tid, None)
                                    snapshot = snapshot_page(tid, page)
                                    health = classify(snapshot, entry, latest.get(tid), urls=urls,
                                        previous=prior, record_paths=records_by_target.get(tid, ()),
                                        history_roots=(), target_history_complete=True)
                                except Exception as exc:
                                    health.setdefault('evidence', {})['refresh_error'] = str(exc)[:300]
                                    composer_failures[tid] = {'key': key, 'rounds': rounds,
                                                              'at': time.time()}
                            else:
                                composer_failures[tid] = {'key': key, 'rounds': rounds,
                                                          'at': time.time()}
                        healths[tid] = health
                        from .collective_page_restart import timed_unsent_restart
                        timed_restart=timed_unsent_restart(policy,health,entry,latest.get(tid),
                            [records[p] for p in records_by_target.get(tid,())],prior,time.time())
                        from .collective_page_restart import failed_upload_restart
                        failed_transfer_restart=failed_upload_restart(policy,health,entry,latest.get(tid),
                            [records[p] for p in records_by_target.get(tid,())],
                            read_record(root/'web-upload-network.json').get('errors',[]),prior,time.time())
                        report['counts'][health['health']] = report['counts'].get(health['health'], 0) + 1
                        if (health['health']=='unknown' and health.get('bounded_recheck',{}).get('reads')==1
                                and latest.get(tid) and health.get('evidence',{}).get('snapshot',{}).get('inspection_complete') is True):
                            record=latest[tid]
                            identity=hashlib.sha256((tid+health['evidence']['fingerprint']+record['_ledger_sha256']).encode()).hexdigest()
                            hold=root/'shared-page-holds'/identity
                            journal=hold/'journal.json'
                            if not journal.exists():
                                _allowed(config,stopping)
                                def hold_guard():
                                    require_slot(config,browser,tid)
                                    _record_cas(record['_ledger_path'],record['_ledger_sha256'])
                                hold.mkdir(parents=True,exist_ok=True)
                                evidence={'target_id':tid,'slot_id':slot['slot_id'],'window_id':registry['window_id'],
                                    'record_path':record['_ledger_path'],'record_sha256':record['_ledger_sha256'],
                                    'close_authorized':False,'move_authorized':False,'created':time.time()}
                                try:
                                    hashes=_archive(hold/'diagnostics',page,health,record,hold_guard,
                                        {p:records[p]['_ledger_sha256'] for p in records_by_target.get(tid,())})
                                    atomic_json(journal,{**evidence,'state':'preserved','archive_hashes':hashes})
                                except Exception as exc:
                                    atomic_json(journal,{**evidence,'state':'archive_failed','error':str(exc)[:500]})
                            report.setdefault('protected_archives',[]).append(str(journal))
                        if health['health'] in ('login', 'verification'):
                            _manual_block(root, tid)
                        matched = records.get(health.get('matched_record_path'))
                        if health['health']=='healthy_blank' and health['evidence'].get('completed_history_paths'):
                            _allowed(config,stopping)
                            require_slot(config,browser,tid)
                            for ledger_path in records_by_target.get(tid,()):
                                _record_cas(ledger_path,records[ledger_path]['_ledger_sha256'])
                            fresh=classify(snapshot_page(tid,page),entry,latest.get(tid),urls=urls,
                                record_paths=records_by_target.get(tid,()))
                            if fresh['health']!='healthy_blank':raise WindowIsolationError('主页释放前证据变化')
                            from .shared_pool_store import mark_verified_blank
                            mark_verified_blank(entry)
                            entry.update(blank_history_verified_at=time.time(),
                                blank_history_ledger_hashes={p:records[p]['_ledger_sha256'] for p in records_by_target.get(tid,())})
                            _persist_pool(root,pool)
                        elif health['health'] == 'raw_path_repair' and matched:
                            _allowed(config, stopping)
                            require_slot(config, browser, tid)
                            if entry.get('state') == 'busy':
                                for ledger_path in records_by_target.get(tid, ()):
                                    _record_cas(ledger_path, records[ledger_path]['_ledger_sha256'])
                            _record_cas(matched['_ledger_path'], matched['_ledger_sha256'])
                            fresh = classify(snapshot_page(tid, page), entry, latest.get(tid), urls=urls, previous=prior,
                                             record_paths=records_by_target.get(tid, ()), history_roots=(),
                                             target_history_complete=True)
                            if (fresh['health'] != 'raw_path_repair' or fresh.get('matched_record_path') != health['matched_record_path'] or
                                    fresh['repair_raw_path'] != health['repair_raw_path'] or
                                    fresh['evidence']['raw_sha256'] != health['evidence']['raw_sha256']):
                                raise WindowIsolationError('修复原回答路径前实时证据变化')
                            entry.pop('review_id', None)
                            entry.update(_entry_for(root, matched, health['repair_raw_path'], snapshot['url']))
                            _persist_pool(root, pool)
                            report['repaired_paths'].append({'target_id': tid, 'raw_path': entry['raw_path']})
                        elif health['health'] == 'saved_prefix_completion' and matched:
                            _allowed(config,stopping)
                            require_slot(config,browser,tid)
                            _record_cas(matched['_ledger_path'],matched['_ledger_sha256'])
                            fresh=classify(snapshot_page(tid,page),entry,latest.get(tid),urls=urls,previous=prior,
                                record_paths=records_by_target.get(tid,()))
                            if (fresh.get('health') != 'saved_prefix_completion' or
                                    fresh.get('matched_record_path') != matched['_ledger_path'] or
                                    fresh['evidence']['complete_sha256'] != health['evidence']['complete_sha256']):
                                raise WindowIsolationError('补收前原回答、URL或提示变化')
                            ev=fresh['evidence'];raw_path=Path(ev['raw_path'])
                            archive=raw_path.parent/'capture-history'/ev['prefix_sha256']
                            archive.mkdir(parents=True,exist_ok=True)
                            prefix=archive/'response-prefix.txt';before=archive/'attempt-before.json'
                            original=Path(ev['prefix_path']).read_bytes()
                            if hashlib.sha256(original).hexdigest()!=ev['prefix_sha256']:
                                raise WindowIsolationError('补收前旧前缀指纹变化')
                            if prefix.exists() and _sha(prefix)!=ev['prefix_sha256']:
                                raise WindowIsolationError('旧前缀归档损坏')
                            if not prefix.exists():atomic_bytes(prefix,original)
                            if not before.exists():atomic_bytes(before,Path(matched['_ledger_path']).read_bytes())
                            _record_cas(before,matched['_ledger_sha256'])
                            journal={'state':'prepared','prefix_path':str(prefix.resolve()),
                                'prefix_sha256':ev['prefix_sha256'],'complete_sha256':ev['complete_sha256'],
                                'original_ledger_sha256':matched['_ledger_sha256']}
                            atomic_json(raw_path.parent/'capture-completion.json',journal)
                            live=ev['snapshot']['answer_texts'][-1]
                            if hashlib.sha256(live.encode()).hexdigest()!=ev['complete_sha256']:
                                raise WindowIsolationError('补收正文指纹变化')
                            _record_cas(matched['_ledger_path'],matched['_ledger_sha256'])
                            atomic_text(raw_path,live)
                            current={k:v for k,v in matched.items() if not k.startswith('_')}
                            current.update(raw_sha256=ev['complete_sha256'],capture_completion={**journal,'completed_at':time.time()})
                            atomic_json(matched['_ledger_path'],current)
                            atomic_json(raw_path.parent/'capture-completion.json',{**journal,'state':'complete'})
                            entry.update(_entry_for(root,{**current,'_ledger_path':matched['_ledger_path']},raw_path,snapshot['url']))
                            _persist_pool(root,pool)
                            health={**health,'health':'completed_saved','collect_allowed':False,
                                'evidence':{**ev,'raw_sha256':ev['complete_sha256']}}
                            healths[tid]=health
                            report['counts']['saved_prefix_completion']-=1
                            report['counts']['completed_saved']=report['counts'].get('completed_saved',0)+1
                            report['collected'].append({'target_id':tid,'ledger_path':matched['_ledger_path'],
                                'raw_sha256':current['raw_sha256'],'kind':'prefix_completion','prefix_archive':str(prefix)})
                        elif health.get('collect_allowed') and matched:
                            _allowed(config, stopping)
                            require_slot(config, browser, tid)
                            _record_cas(matched['_ledger_path'], matched['_ledger_sha256'])
                            fresh = classify(snapshot_page(tid, page), entry, matched, urls=urls, previous=prior)
                            if not fresh.get('collect_allowed') or fresh['evidence']['raw_sha256'] != health['evidence']['raw_sha256']:
                                raise WindowIsolationError('落盘前原完整回答变化')
                            raw_path = Path(matched['_ledger_path']).parent / 'response-raw.txt'
                            if raw_path.exists() and _sha(raw_path) != health['evidence']['raw_sha256']:
                                raise WindowIsolationError('原回答文件已有不同内容，不覆盖')
                            atomic_text(raw_path, health['evidence']['raw'])
                            current = {k: v for k, v in matched.items() if not k.startswith('_')}
                            current.update(state='response_saved', raw_sha256=_sha(raw_path), conversation_url=snapshot['url'],
                                           reused_window=True, tab_cleanup='preserved_reusable_window', finished=time.time())
                            _record_cas(matched['_ledger_path'], matched['_ledger_sha256'])
                            atomic_json(matched['_ledger_path'], current)
                            entry.pop('review_id', None)
                            entry.update(_entry_for(root, {**current, '_ledger_path': matched['_ledger_path']}, raw_path, snapshot['url']))
                            _persist_pool(root, pool)
                            report['collected'].append({'target_id': tid, 'ledger_path': matched['_ledger_path'], 'raw_sha256': current['raw_sha256']})
                        elif (terminal_empty_restart or hourly_restart or failed_transfer_restart or timed_restart or health['replace_allowed'] or stalled_page_fallback(config, health, entry, latest.get(tid), at=time.time()) or
                              mass_restart and tid in episode_targets and (not policy.get('stalled_after_seconds_by_lane') or timed_restart)
                              and collective_eligible(health,entry,latest.get(tid),[records[p] for p in records_by_target.get(tid,())])) and started < maximum:
                            _allowed(config, stopping)
                            require_slot(config, browser, tid)
                            registry_now, sha_now = _registry(config)
                            actual = next(s for s in registry_now['slots'] if s['slot_id'] == slot['slot_id'])
                            if actual.get('target_id') != tid:
                                raise WindowIsolationError('归档前槽位CAS冲突')
                            identity = secrets.token_hex(16)
                            path = journal_root / identity / 'journal.json'
                            record = matched or latest.get(tid)
                            record_hashes = ({p: records[p]['_ledger_sha256'] for p in records_by_target.get(tid, ())}
                                             if health['evidence'].get('completed_history_paths') or not health['replace_allowed'] else {})
                            def archive_guard():
                                require_slot(config, browser, tid)
                                for ledger_path, expected in record_hashes.items():
                                    _record_cas(ledger_path, expected)
                            folder = path.parent / 'diagnostics'
                            try:
                                archived = _archive(folder, page, health, record,
                                                    archive_guard, record_hashes,
                                                    allow_missing_unsent_prompt=(timed_restart or mass_restart) and collective_eligible(health,entry,record,[records[p] for p in records_by_target.get(tid,())]))
                            except Exception as exc:
                                # Preserve ownership even when a diagnostic cannot be captured.
                                # This terminal failure never authorizes close, creation or claim release.
                                _journal(path, {'id':identity,'state':'archive_failed',
                                    'slot_id':slot['slot_id'],'window_id':registry_now['window_id'],
                                    'old_target_id':tid,'registry_sha256':sha_now,
                                    'original_entry':copy.deepcopy(entry),'health':health,'record':record,
                                    'record_paths':records_by_target.get(tid,()),'record_hashes':record_hashes,
                                    'archive_complete':False,'close_authorized':False,'created':time.time(),
                                    'error':type(exc).__name__+': '+str(exc)[:500]})
                                report['errors'].append({'target_id': tid, 'reason': '归档失败，原页保留：' + type(exc).__name__ + ': ' + str(exc)[:400]})
                                report['protected'] += 1
                                continue
                            journal = {'id': identity, 'state': 'archived', 'slot_id': slot['slot_id'],
                                'window_id': registry_now['window_id'], 'old_target_id': tid, 'registry_sha256': sha_now,
                                'original_slot': copy.deepcopy(actual),
                                'registry_metadata':{k:v for k,v in registry_now.items() if k not in ('slots','revision')},
                                'registry_slots_sha256':{s['slot_id']:_sha_text(s) for s in registry_now['slots']},
                                'original_entry': copy.deepcopy(entry), 'health': health, 'baseline': prior,
                                'record': record, 'record_paths': records_by_target.get(tid, ()),
                                'record_hashes': record_hashes,
                                'archive_hashes': archived, 'created': time.time(),
                                'collective_unsent_restart': (timed_restart or mass_restart) and collective_eligible(health,entry,record,[records[p] for p in records_by_target.get(tid,())]),
                                'timed_unsent_restart':timed_restart,
                                'failed_upload_restart':failed_transfer_restart,
                                'hourly_idle_restart':hourly_restart,
                                'terminal_empty_restart':terminal_empty_restart,
                                'unrecoverable_fallback': not health['replace_allowed'],
                                'close_authorized': True, 'requeue_allowed': False,
                                'authorization': ('docs/authorizations/20261022-page-throughput-repair.md' if terminal_empty_restart else 'docs/authorizations/20261022-one-hour-page-restart.md' if hourly_restart else 'docs/authorizations/20261015-system-proxy-upload-fix.md' if failed_transfer_restart else 'docs/authorizations/20261013-one-minute-stalled-restart.md' if timed_restart else 'docs/authorizations/20261012-collective-page-restart.md' if mass_restart else
                                    'docs/authorizations/20261012-two-round-orange-replacement.md'
                                    if policy.get('stalled_check_rounds') else
                                    'docs/authorizations/20261009-unrecoverable-page-replacement.md')}
                            _journal(path, journal)
                            started += 1
                            try:
                                _resume(config, browser, pool, path, journal, stopping, report)
                            except Exception as exc:
                                report['errors'].append({'target_id': tid, 'reason': str(exc)[:500]})
                                _journal(path, journal, error=str(exc)[:500])
                            pending.append((path, journal))
                        if entries.get(tid, {}).get('state') in ('ready', 'ready_blank'):
                            report['available'] += 1
                        else:
                            report['protected'] += 1
                        if on_checked_page is not None:
                            with (lock_factory(timeout=5) if independent_maintenance else nullcontext()):
                                _allowed(config,stopping)
                                report.setdefault('recovered_page_leases', []).extend(on_checked_page(tid, health) or [])
            except (WindowIsolationError, PoolConflict):
                # Shared ownership, pause and storage conflicts still stop writes.
                raise
            except Exception as exc:
                # Retain this page and its lifecycle journal. A local failure
                # must not prevent fresh inspection of the remaining slots.
                reason = type(exc).__name__ + ': ' + str(exc)[:500]
                report['errors'].append({'target_id': tid, 'stage': 'page_maintenance', 'reason': reason})
                observed_evidence = healths.get(tid, {}).get('evidence') or {
                    'target_id': tid, 'checked_at': time.time(), 'inspection_complete': False}
                healths[tid] = {'health': 'maintenance_error', 'replace_allowed': False,
                    'collect_allowed': False, 'reason': reason,
                    'evidence': observed_evidence}
        report['counts'] = {}
        for page_health in healths.values():
            kind = page_health['health']
            report['counts'][kind] = report['counts'].get(kind, 0) + 1
            for error in page_health.get('recovery_errors', []):
                if error not in report['errors']:report['errors'].append(error)
        report['pages'] = healths
        final_registry, _ = _registry(config)
        final_inventory = read_window_inventory(browser)
        healthy = {tid for tid, health in healths.items()
                   if health['health'] in ('healthy_blank', 'completed_saved', 'raw_path_repair')}
        healthy.update(item['target_id'] for item in report['collected'])
        healthy.update(item['new_target_id'] for item in report['replaced'])
        healthy.difference_update(tid for tid, page_health in healths.items()
                                  if page_health['health'] == 'maintenance_error')
        final_ready = sum(slot.get('target_id') in healthy and
                          final_inventory.get('targets', {}).get(slot['target_id'], {}).get('window_id') == final_registry['window_id'] and
                          entries.get(slot['target_id'], {}).get('state') in ('ready', 'ready_blank')
                          for slot in final_registry['slots'])
        report.update(available=final_ready, protected=20-final_ready)
        active_journals = [j for _, j in pending if j.get('state') not in TERMINAL_JOURNALS]
        report['pending_repair_targets'] = sorted({j['old_target_id'] for j in active_journals} |
            {j['candidate']['target_id'] for j in active_journals if j.get('candidate')})
        report['state'] = 'pending' if active_journals else 'checked'
        report['finished_at']=time.time()
        report['duration_seconds']=max(0,report['finished_at']-report['checked_at'])
        report['composer_failures']=composer_failures
        report['network_reloads']=network_reloads
        atomic_json(health_path, report)
    except Exception as exc:
        # A pause between two per-target locks still reports already closed or
        # unknown operations; it never loses the persistent repair ownership.
        active_pending=[j for _,j in locals().get('pending',[]) if j.get('state') not in TERMINAL_JOURNALS]
        if active_pending:
            report['pending_repair_targets']=sorted({j['old_target_id'] for j in active_pending} |
                {j['candidate']['target_id'] for j in active_pending if j.get('candidate')})
        lock_busy=not locals().get('acquired',True) and ('等待网页提交锁超时' in str(exc) or isinstance(exc,TimeoutError))
        report['state'] = 'waiting_submission_lock' if lock_busy else 'paused' if '暂停' in str(exc) else 'needs_inspection'
        report['errors'].append({'reason': str(exc)[:500]})
        try:
            atomic_json(root / 'shared-page-repair-status.json', report)
        except OSError:
            pass
    report['finished_at']=time.time()
    report['duration_seconds']=max(0,report['finished_at']-report['checked_at'])
    try:
        atomic_json(root / 'shared-page-repair-status.json', report)
    except OSError:
        pass
    return report
