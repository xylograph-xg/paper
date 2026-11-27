"""Recover one original conversation in its replacement slot, never resubmit it.

Only the existing CDP owner calls run_once. A separate collection ledger keeps
the immutable original target/submit identity intact until a full answer exists.
"""
import hashlib
import json
import time
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path, services__atomic_json as atomic_json
from .attempt_history import index_attempts, read_attempt
from .shared_window_owner import require_slot, registry_path, require_reusable
from .shared_page_health import snapshot_page
from .shared_page_repair import atomic_bytes
from .shared_pool_store import save_pool, begin_request

PENDING = ('submitted', 'submission_started', 'needs_inspection')
COLLECTION_TERMINAL = ('complete', 'retired_empty', 'retired_closed_browser')
_JOURNALS = {}


def _read(path):
    return json.loads(Path(path).read_text())


def _formal(url):
    from urllib.parse import urlsplit
    import re
    parsed = urlsplit(url or '')
    return (parsed.scheme == 'https' and parsed.netloc == 'chatgpt.com'
            and re.fullmatch(r'/c/[A-Za-z0-9_-]+', parsed.path) is not None
            and not parsed.query and not parsed.fragment and 'local-chatgpt' not in parsed.path)


def _identity(record):
    return {k:v for k,v in record.items() if not k.startswith('_')}


def _verify(root, proof):
    original = Path(proof['original_ledger'])
    if not any(original.resolve().is_relative_to((root/lane).resolve()) for lane in ('web_cards', 'card_reviews')):
        raise ValueError('原回执路径越界')
    saved = proof['original_attempt']
    from cards.api import web_card_inputs__digest as digest
    journal = Path(proof['retirement_journal'])
    if (not journal.resolve().is_relative_to((root/'shared-page-repairs').resolve())
            or digest(journal) != proof['retirement_sha256']):
        raise ValueError('原页完整归档登记变化')
    archive = journal.parent/'diagnostics'
    for name in proof['archive_identity_files']:
        if digest(archive/name) != proof['archive_hashes'].get(name):
            raise ValueError('原回执或实际提示归档变化')
    if hashlib.sha256((original.parent/'prompt-actual.txt').read_bytes()).hexdigest() != saved.get('actual_prompt_sha256'):
        raise ValueError('原实际提示指纹变化')
    if not _formal(saved.get('conversation_url')) or saved.get('state') not in PENDING:
        raise ValueError('没有可唯一恢复的正式原会话')
    live = read_attempt(original)
    if live['_ledger_sha256'] != proof['original_sha256']:
        # A crash after the original response write is reconciled, never resent.
        if not (live.get('state') == 'response_saved'
                and live.get('original_receipt_recovery') == proof['id']):
            raise ValueError('原提交账本变化')
    return original, saved, live


def _journal_index(root):
    index = {}
    live = set()
    for path in (root/'shared-page-repairs').glob('*/journal.json'):
        key = str(path);live.add(key);stat = path.stat()
        version = (stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        cached = _JOURNALS.get(key)
        if cached is None or cached[0] != version:
            raw = path.read_bytes();after = path.stat()
            if version != (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('原页归档登记读取期间变化')
            cached = (version,json.loads(raw));_JOURNALS[key] = cached
        journal = cached[1]
        index.setdefault(journal.get('old_target_id'),[]).append((path,journal))
    prefix = str(root/'shared-page-repairs')+'/'
    for key in list(_JOURNALS):
        if key.startswith(prefix) and key not in live:_JOURNALS.pop(key,None)
    return index


def _retirement(root, record, journals=None):
    """An exact completed archive binds the old request to its logical slot.

    A new dedicated-window epoch may have no replacement_history. The original
    immutable close journal, never a guessed active window, provides lineage.
    """
    from cards.api import web_card_inputs__digest as digest
    source = Path(record['_ledger_path']).resolve();matches = []
    journals = _journal_index(root) if journals is None else journals
    for path,journal in journals.get(record.get('target_id'),[]):
        if (journal.get('old_target_id') != record.get('target_id') or journal.get('state') != 'ready'
                or journal.get('close_authorized') is not True):continue
        archive = path.parent/'diagnostics';bound = journal.get('archive_hashes', {})
        required = ('health.json','body.txt','page.html','capture.json')
        if not all(name in bound for name in required):continue
        if any(Path(name).name != name or digest(archive/name) != sha for name,sha in bound.items()):
            raise ValueError('原故障页完整归档指纹变化')
        if 'page.png' not in bound:
            # The resident archiver already accepts a URL-bound complete MHTML
            # when both screenshot methods time out. Apply that same contract
            # to receipt lineage; a missing image alone is never sufficient.
            if 'page.mhtml' not in bound:continue
            capture=_read(archive/'capture.json')
            manifest=_read(archive/'archive-manifest.json')
            if (capture.get('method')!='resident_cdp_mhtml' or
                    capture.get('screenshot_available') is not False or
                    capture.get('foreground_changed') is not False or
                    manifest.get('complete') is not True or manifest.get('files')!=bound):continue
            from email.parser import BytesParser
            from email.policy import default as email_policy
            document=BytesParser(policy=email_policy).parsebytes((archive/'page.mhtml').read_bytes())
            url=record.get('conversation_url')
            if (not _formal(url) or document.get('Snapshot-Content-Location')!=url or
                    document.get_content_type()!='multipart/related' or
                    not any(part.get_content_type()=='text/html' and part.get('Content-Location')==url
                            and part.get_payload(decode=True) for part in document.walk())):continue
        identity_files = None
        saved = journal.get('record') or {}
        legacy_bound = (Path(saved.get('_ledger_path') or '.').resolve() == source
                        and saved.get('_ledger_sha256') == record['_ledger_sha256'])
        hashes = journal.get('record_hashes', {})
        mapped = any(Path(k).resolve() == source and v == record['_ledger_sha256'] for k,v in hashes.items())
        if ((mapped or legacy_bound) and bound.get('ledger-before.json') == record['_ledger_sha256']
                and bound.get('prompt-before.txt') == record.get('actual_prompt_sha256')):
            identity_files = ['ledger-before.json','prompt-before.txt']
        elif mapped and 'target-history-before.json' in bound:
            histories = _read(archive/'target-history-before.json')
            exact = [r for r in histories if Path(r.get('path') or '.').resolve() == source
                     and r.get('sha256') == record['_ledger_sha256'] and _identity(r.get('record',{})) == _identity(record)]
            if len(exact)==1:identity_files = ['target-history-before.json']
        if identity_files is None:continue
        matches.append((path,journal,identity_files))
    if len(matches) != 1:return None
    return matches[0]


def _pending(catalog, records):
    from core.api import workflow_priority__seed_first as seed_first
    candidates=[]
    for record in records.values():
        source=Path(record['_ledger_path'])
        rel=source.relative_to(catalog.path.parent.resolve()).parts
        if (record.get('state') not in PENDING or record.get('send_click_started') is not True
                or not _formal(record.get('conversation_url')) or len(rel)!=4 or 'history' in rel):continue
        candidates.append({'paper_id':rel[1],'record':record})
    with catalog.connect() as db:
        return [row['record'] for row in seed_first(db,sorted(candidates,key=lambda r:r['record'].get('created',0)))]


def inspect_pending(config, catalog):
    """Read-only source/archive eligibility; never invokes browser or sender."""
    root=Path(config['catalog_path']).parent;records,_=index_attempts(root)
    registry=_read(registry_path(config));journals=_journal_index(root);items=[]
    for record in _pending(catalog,records):
        item={'ledger':record['_ledger_path'],'target_id':record['target_id'],'eligible':False}
        try:
            retired=_retirement(root,record,journals)
            if retired is None:raise ValueError('没有唯一完整关闭归档，保留原请求')
            path,journal,identity_files=retired
            slots=[s for s in registry['slots'] if s['slot_id']==journal['slot_id']]
            if len(slots)!=1:raise ValueError('原逻辑槽位缺少唯一当前登记')
            packet_sha=_source(catalog,Path(record['_ledger_path']),_identity(record))
            item.update(eligible=True,slot_id=journal['slot_id'],retirement_journal=str(path),
                        collection_target_id=slots[0]['target_id'],packet_sha256=packet_sha)
        except (OSError,ValueError,KeyError,TypeError) as exc:item['error']=str(exc)[:500]
        items.append(item)
    return {'items':items,'browser_operations':False,'model_requests':False}


def collection_ledgers(root):
    """Validated side ledgers for the original observer; no DOM or navigation."""
    root = Path(root);result = {};errors=[];conflicts=set()
    for path in (root/'original-receipts').glob('*/proof.json'):
        try:
            proof = _read(path)
            if not isinstance(proof,dict):raise ValueError('原收取恢复登记不是对象')
            if proof.get('state') in COLLECTION_TERMINAL:continue
            original, saved, live = _verify(root, proof)
            side = path.with_name('attempt.json');attempt = _read(side)
            expected = {**saved, 'target_id': proof['collection_target_id']}
            # Only collection fields may advance in the side ledger.
            fields = ('state', 'raw_sha256', 'tab_cleanup', 'reused_window', 'observed_complete_at')
            comparable = {k:v for k,v in attempt.items() if k not in fields}
            if (attempt.get('state') not in (*PENDING, 'response_saved')
                    or comparable != {k:v for k,v in expected.items() if k not in fields}):
                raise ValueError('原会话收取副本身份变化')
            pool = _read(root/'gpt-window-pool.json')
            if pool['windows'].get(attempt['target_id'], {}).get('original_receipt_recovery') != proof['id']:
                continue  # An interrupted reservation is reconciled by the owner.
            tid = attempt['target_id']
            if tid in result or tid in conflicts:
                conflicts.add(tid);result.pop(tid,None)
                raise ValueError('同页存在多个原会话恢复意图')
            result[tid] = (side, attempt)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append({'path':str(path),'error':str(exc)[:400]})
    if errors or (root/'original-receipt-collection-errors.json').exists():
        atomic_json(root/'original-receipt-collection-errors.json',{'checked_at':time.time(),'errors':errors})
    return result


def _has_draft(snapshot):
    # The native empty rich-text editor returns a newline. Match the existing
    # reusable-page guard without changing any composer or prompt bytes.
    draft=snapshot.get('draft','')
    return not isinstance(draft,str) or bool(draft.strip())


def _blank(snapshot):
    return (snapshot.get('inspection_complete') is True and not snapshot.get('errors')
            and snapshot.get('url', '').rstrip('/') == 'https://chatgpt.com'
            and snapshot.get('composer_available') is True
            and snapshot.get('streaming') is False and snapshot.get('uploading') is False
            and not _has_draft(snapshot)
            and not any(snapshot.get(k) for k in ('user_texts', 'answer_texts', 'answer_element_count',
                'attachments', 'login', 'verification', 'quota')))


def _idle(page,entry,snapshot):
    if entry.get('state')=='ready_blank':return _blank(snapshot)
    if (entry.get('state')!='ready' or snapshot.get('inspection_complete') is not True
            or snapshot.get('streaming') is not False or snapshot.get('uploading') is not False
            or _has_draft(snapshot)
            or any(snapshot.get(k) for k in ('errors','attachments','login','verification','quota'))):return False
    # Reuse the established full saved-body/URL/empty-composer guard. A healthy
    # completed page need not wait for a new model task to turn it into a home.
    require_reusable(page,entry)
    return True


def _enabled(config, kind):
    from core.api import control__pause_decision as pause_decision, control__provider_decisions as provider_decisions
    scope = {'cards':'web_cards', 'review':'card_review', 'correction':'card_correction'}[kind]
    root = Path(config['catalog_path']).parent
    return (pause_decision(config, scope).allowed and
            provider_decisions(root, policy=config.get('web_cards', {}))['chatgpt'].allowed)


def _source(catalog, source, saved):
    from cards.api import web_card_inputs__digest as digest
    rel = source.relative_to(catalog.path.parent.resolve()).parts
    paper = catalog.get(rel[1])
    # Review receipts and packets share the immutable version folder. Cards
    # keep their receipt in chatgpt/ beneath the packet. Never guess a sibling
    # version or fall back to a paper-level packet when evidence is missing.
    packet_path = (source.parent if rel[0]=='card_reviews' else source.parent.parent)/'packet.json'
    packet = _read(packet_path)
    if (paper['acquisition'] != 'available' or packet.get('source_original_sha256') != paper['asset_hash']
            or saved.get('inputs') != packet.get('input_hashes')
            or any(paper['metadata'].get(k) for k in ('identity_review_required', 'version_review_required', 'out_of_scope'))
            or digest(paper['asset_path']) != paper['asset_hash']):
        raise ValueError('原回执材料、原文或身份版本变化')
    if rel[0] == 'web_cards' and packet.get('paper_id') != paper['id']:
        raise ValueError('原制卡材料身份变化')
    if rel[0] == 'card_reviews' and (packet.get('job_id') != saved.get('review_id')
            or digest(paper['card_path']) != packet.get('card_sha256')):
        raise ValueError('原核验卡片版本变化')
    for name, sha in packet['input_hashes'].items():
        if Path(name).name != name or digest(packet_path.parent/name) != sha:
            raise ValueError('原冻结材料指纹变化')
    from .web_upload_bundle import ZIP_INSTRUCTION
    prompt=packet_path.with_name('prompt.txt').read_text()
    actual=source.with_name('prompt-actual.txt').read_text()
    if actual not in (prompt,prompt+ZIP_INSTRUCTION):raise ValueError('实际提示不等于原冻结提示及已知包装')
    if digest(source.with_name('prompt-actual.txt'))!=saved.get('actual_prompt_sha256'):
        raise ValueError('原实际提示指纹变化')
    import re
    if saved.get('review_id'):
        from .web_page_observer import _review_identity
        if not _review_identity(actual,saved['review_id']):
            raise ValueError('原核验材料标识变化')
    else:
        from .web_card_pool import MARKER
        if MARKER.findall(actual)!=[paper['id']]:raise ValueError('原制卡材料标识变化')
    return digest(packet_path)


def _navigate(config,catalog,browser,pool,page,proof_path,proof,stopping,lock_factory):
    """Resume a proven pre-navigation reservation; unknown navigations stay put."""
    if proof['state']!='prepared' or stopping() or not _enabled(config,proof['kind']):return
    root=catalog.path.parent.resolve();tid=proof['collection_target_id']
    with lock_factory(timeout=5):
        if stopping() or not _enabled(config,proof['kind']):return
        require_slot(config,browser,tid)
        registry=_read(registry_path(config))
        if (registry['window_id']!=proof['window_id'] or
                next(s for s in registry['slots'] if s['slot_id']==proof['slot_id'])!=proof['slot_snapshot']):
            raise ValueError('收取恢复准备阶段槽位变化')
        original,saved,_=_verify(root,proof)
        if _source(catalog,original,saved)!=proof['packet_sha256']:raise ValueError('收取恢复准备材料变化')
        entry=pool['windows'][tid]
        if not (entry==proof['previous_entry'] or entry.get('original_receipt_recovery')==proof['id']):
            raise ValueError('收取恢复准备期间页面已被领取')
        with catalog.connect() as db:
            if db.execute("SELECT 1 FROM shared_page_backlog WHERE target_id=? AND state='claimed'",(tid,)).fetchone():
                raise ValueError('收取恢复准备期间页面已被领取')
        if not _idle(page,proof['previous_entry'],snapshot_page(tid,page)):raise ValueError('收取恢复准备期间页面已变化')
        if entry.get('original_receipt_recovery')!=proof['id']:
            begin_request(entry,proof['kind'],original.relative_to(root).parts[1])
        entry.update(repair_in_progress=True,original_receipt_recovery=proof['id'])
        save_pool(root/'gpt-window-pool.json',pool)
        proof['state']='navigation_intent';atomic_json(proof_path,proof)
    try:
        require_slot(config,browser,tid)
        if stopping() or not _enabled(config,proof['kind']):return
        page.goto(saved['conversation_url'],wait_until='domcontentloaded',timeout=10000)
        proof['state']='observing'
    except Exception as exc:proof.update(state='navigation_unknown',error=str(exc)[:400])
    atomic_json(proof_path,proof)


def _promote(root, proof_path, proof, pool, catalog, page, urls):
    original, saved, live = _verify(root, proof)
    side = _read(proof_path.with_name('attempt.json'))
    if side.get('state') != 'response_saved':return False
    if _source(catalog, original, saved) != proof['packet_sha256']:
        raise ValueError('原材料登记变化')
    validated = collection_ledgers(root).get(proof['collection_target_id'])
    if not validated or validated[1] != side:raise ValueError('收取副本无法复核')
    raw = proof_path.with_name('response-raw.txt').read_bytes()
    if (not raw.strip() or hashlib.sha256(raw).hexdigest() != side.get('raw_sha256')
            or side.get('conversation_url') != saved['conversation_url']):
        raise ValueError('原会话完整回答绑定变化')
    snapshot = snapshot_page(proof['collection_target_id'], page)
    from .web_page_observer import response_identity
    from web_gpt.core import ANSWER, _message_text
    expected = original.with_name('prompt-actual.txt').read_text()
    if (snapshot.get('inspection_complete') is not True or snapshot.get('streaming') is not False
            or snapshot.get('uploading') is not False or _has_draft(snapshot) or snapshot.get('attachments')
            or any(snapshot.get(k) for k in ('login','verification','quota','errors'))
            or len(snapshot.get('user_texts', [])) != 1
            or not response_identity(side, expected, snapshot['user_texts'][0], page.url,
                                     urls, proof['collection_target_id'])
            or _message_text(page.locator(ANSWER).last).encode() != raw):
        raise ValueError('原会话回答实时复核变化，保留副本')
    destination = original.with_name('response-raw.txt')
    if destination.exists() and destination.read_bytes() != raw:
        raise ValueError('原回答已有不同保存物，不覆盖')
    atomic_bytes(destination, raw)
    final = {**saved, 'state':'response_saved', 'raw_sha256':side['raw_sha256'],
             'observed_complete_at':side['observed_complete_at'],
             'original_receipt_recovery':proof['id'], 'collection_target_id':proof['collection_target_id']}
    # Target, submit time, settings, prompt and inputs remain original evidence.
    if live.get('state') != 'response_saved':atomic_json(original, final)
    tid = proof['collection_target_id'];entry = pool['windows'][tid]
    if entry.get('original_receipt_recovery') != proof['id']:
        raise ValueError('收取页面归属变化')
    entry.update(state='ready', conversation_url=saved['conversation_url'], raw_path=str(destination),
                 raw_sha256=side['raw_sha256'])
    entry.pop('repair_in_progress', None)
    save_pool(root/'gpt-window-pool.json', pool)
    if proof['kind'] == 'review':
        with catalog.connect() as db:
            db.execute("UPDATE card_review_jobs SET state='response_saved',error='' WHERE id=? AND state IN ('submitted','submitting','needs_user','failed')",
                       (saved['review_id'],))
    # Card jobs stay needs_inspection/failed until the existing local parser and
    # publication/retry guards consume the complete original response.
    atomic_json(proof_path, {**proof, 'state':'complete', 'completed_at':time.time()})
    return True


def _retire_closed_empty(root, proof_path, proof, registry):
    """Recognize only a completed, guarded terminal-empty page retirement."""
    if proof.get('state') not in ('observing','navigation_unknown'):return False
    tid=proof['collection_target_id']
    slots=[s for s in registry['slots'] if s['slot_id']==proof['slot_id']]
    if (registry['window_id']!=proof['window_id'] or len(slots)!=1
            or slots[0].get('target_id')==tid):return False
    _verify(root,proof)
    side=read_attempt(proof_path.with_name('attempt.json'))
    if side.get('state') not in PENDING:return False
    retired=_retirement(root,side)
    if retired is None:return False
    path,journal,_=retired
    health=journal.get('health',{})
    if (journal.get('terminal_empty_restart') is not True
            or health.get('health')!='terminal_empty'
            or health.get('terminal_empty_check',{}).get('rounds',0)<2
            or journal.get('requeue_allowed') is not False
            or not any(s.get('target_id')==tid and s.get('repair_id')==journal['id']
                       for s in slots[0].get('replacement_history',[]))):return False
    # This is a page-retirement outcome, never successful answer collection.
    atomic_json(proof_path,{**proof,'state':'retired_empty','retired_at':time.time(),
        'collection_retirement_journal':str(path),'collection_retirement_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'original_request_preserved':True,'answer_collected':False,'resubmission_allowed':False})
    return True


def _retire_closed_browser(root, proof_path, proof, registry, present_targets):
    """Retire only a collection target proven lost with its whole browser epoch.

    This does not terminate the original request. Its immutable URL may later
    be read in a new guarded slot; an uncertain navigation in a live epoch is
    never replayed. The original side ledger and intent bytes remain archived.
    """
    tid = proof['collection_target_id']
    if (tid in present_targets or proof.get('window_id') == registry.get('window_id')
            or proof.get('state') not in ('prepared', 'observing', 'navigation_unknown', 'navigation_intent')):
        return False
    request_id = registry.get('startup_request_id', '')
    if not request_id or Path(request_id).name != request_id:return False
    archive = root/'browser-start-archives'/request_id
    old = _read(archive/'registry.json');closed = _read(archive/'closed-browser-evidence.json')
    previous = _read(archive/'request.json')
    previous_id = previous.get('id')
    if not isinstance(previous_id,str) or not previous_id:return False
    request = _read(root/'browser-start-request.json')
    checks = closed.get('checks', [])
    # An explicit start can reuse a registered window. Its latest request ID
    # differs from the window's creation ID; the closure writer binds both
    # the latest request and the unchanged registry in this fingerprint.
    identity = hashlib.sha256(json.dumps({'request_id':previous_id,
        'registry':old, 'profile':closed.get('profile'), 'endpoint':closed.get('endpoint')},
        sort_keys=True).encode()).hexdigest()
    if (request.get('id') != request_id or request.get('origin') != 'closed_browser_recovery'
            or closed.get('identity') != identity or not closed.get('endpoint')
            or closed['endpoint'] != old.get('endpoint') or closed['endpoint'] != registry.get('endpoint')
            or request.get('state') != 'ready' or request.get('previous_request_id') != previous_id
            or closed.get('previous_request_id') != previous_id
            or old.get('window_id') != proof.get('window_id')
            or not any(s.get('slot_id') == proof['slot_id'] and s.get('target_id') == tid for s in old['slots'])
            or closed.get('process_absent') is not True or closed.get('endpoint_unavailable') is not True
            or len(checks) != 2 or checks[1]-checks[0] < 30
            or checks[1] != closed.get('checked_at') or checks[1] > registry.get('created', 0)):
        return False
    _verify(root, proof)
    side = _read(proof_path.with_name('attempt.json'))
    expected = {**proof['original_attempt'], 'target_id':tid}
    if side != expected or proof_path.with_name('response-raw.txt').exists():return False
    epoch = hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest()
    destination = proof_path.parent/'closed-browser-epochs'/epoch
    hashes = {}
    for name in ('proof.json', 'attempt.json', 'prompt-actual.txt'):
        raw = proof_path.with_name(name).read_bytes();saved = destination/name
        if saved.exists() and saved.read_bytes() != raw:raise ValueError('旧收取意图归档冲突')
        atomic_bytes(saved, raw);hashes[name] = hashlib.sha256(raw).hexdigest()
    evidence = {name:hashlib.sha256((archive/name).read_bytes()).hexdigest()
                for name in ('registry.json', 'closed-browser-evidence.json', 'request.json')}
    atomic_json(proof_path, {**proof, 'state':'retired_closed_browser',
        'collection_epoch_archive':str(destination), 'collection_epoch_hashes':hashes,
        'closed_browser_archive':str(archive), 'closed_browser_hashes':evidence,
        'original_request_preserved':True, 'answer_collected':False, 'resubmission_allowed':False})
    return True


def run_once(config, catalog, browser, pool, pages, *, complete, stopping, lock_factory, target_lease=None,
             present_targets=None, known_urls=None):
    """One bounded owner pass; fixed replacement slots only, no new tabs/sends.

    Restarted navigation intents are observed as-is; an uncertain navigation
    never starts another recovery epoch or changes the source submission.
    """
    root = Path(config['catalog_path']).parent
    present_targets = set(pages) if present_targets is None else set(present_targets)
    urls = [p.url for p in pages.values()] if known_urls is None else list(known_urls)
    report = {'checked_at':time.time(), 'started':[], 'collected':[], 'retired_empty':[], 'blocked':[], 'candidate_waits':[]}
    if not complete or stopping():return report
    registry = _read(registry_path(config))
    records, latest = index_attempts(root)
    lease = target_lease or (lambda tid:nullcontext(True))
    active = set()
    for proof_path in (root/'original-receipts').glob('*/proof.json'):
        try:
            proof = _read(proof_path)
            if not isinstance(proof,dict):raise ValueError('原收取恢复登记不是对象')
            if proof.get('state') in COLLECTION_TERMINAL:continue
            for field in ('id','kind','collection_target_id'):
                if not isinstance(proof[field],str) or not proof[field]:raise ValueError('原收取恢复身份缺失')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            report['blocked'].append({'path':str(proof_path),'error':str(exc)[:400]});continue
        tid = proof['collection_target_id'];active.add(tid)
        try:
            if _retire_closed_browser(root,proof_path,proof,registry,present_targets):
                report.setdefault('retired_closed_browser',[]).append(proof['id']);continue
            if _retire_closed_empty(root,proof_path,proof,registry):
                report['retired_empty'].append(proof['id']);continue
            if tid not in pages:
                report['blocked'].append({'id':proof['id'],'error':'原收取页不在当前清单，原请求保留、不重发'})
                continue
            with lease(tid) as acquired:
                if not acquired:continue
                require_slot(config, browser, tid)
                if proof.get('state')=='prepared':
                    _navigate(config,catalog,browser,pool,pages[tid],proof_path,proof,stopping,lock_factory)
                if pool['windows'].get(tid, {}).get('original_receipt_recovery') != proof['id']:
                    raise ValueError('原收取意图缺少固定页面归属，保留待核对')
                if _promote(root, proof_path, proof, pool, catalog, pages[tid], urls):
                    report['collected'].append(proof['id'])
        except (OSError, ValueError, KeyError) as exc:
            report['blocked'].append({'id':proof['id'], 'error':str(exc)[:400]})
    journals = _journal_index(root)
    rejected_targets=set()
    for record in _pending(catalog,records):
        if stopping():break
        tid = record.get('target_id')
        if (tid in present_targets or record.get('state') not in PENDING or not _formal(record.get('conversation_url'))
                or record.get('send_click_started') is not True):continue
        # Only the current active card/review ledger is restored, never a stale
        # archived generation whose successor has already been committed.
        source = Path(record['_ledger_path'])
        rel = source.relative_to(root.resolve()).parts
        if 'history' in rel or len(rel) != 4:continue
        kind = 'review' if record.get('review_id') else record.get('kind', 'cards')
        if kind not in ('cards', 'review', 'correction') or not _enabled(config, kind):continue
        rid = hashlib.sha256((record['_ledger_path']+record['_ledger_sha256']).encode()).hexdigest()
        directory = root/'original-receipts'/rid;proof_path = directory/'proof.json'
        if proof_path.exists() and _read(proof_path).get('state') == 'retired_closed_browser':
            epoch = hashlib.sha256(json.dumps({'window_id':registry['window_id'],
                'created':registry.get('created'), 'startup_request_id':registry.get('startup_request_id')},
                sort_keys=True).encode()).hexdigest()[:16]
            rid += '-'+epoch
            directory = root/'original-receipts'/rid;proof_path = directory/'proof.json'
        if proof_path.exists():continue
        try:retired = _retirement(root,record,journals)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            report['blocked'].append({'ledger':record['_ledger_path'],'error':str(exc)[:400]});continue
        if retired is None:continue
        journal_path, journal, identity_files = retired
        fixed=config.get('web_cards',{}).get('shared_window',{}).get('fixed_lane_slots',{})
        reserved={sid for values in fixed.values() for sid in values}
        compatible=set(fixed.get(kind,[]))|{s['slot_id'] for s in registry['slots'] if s['slot_id'] not in reserved}
        slots=sorted((s for s in registry['slots'] if s['slot_id'] in compatible),
                     key=lambda s:s['slot_id']!=journal['slot_id'])
        if record['conversation_url'] in urls:continue
        slot=None
        for candidate in slots:
            current_tid=candidate.get('target_id');entry=pool['windows'].get(current_tid,{})
            if (current_tid not in pages or current_tid in active or current_tid in rejected_targets or entry.get('state') not in ('ready_blank','ready')
                    or entry.get('repair_in_progress')):continue
            from cards.api import web_card_retry__known_unsent as known_unsent
            if current_tid in latest and not known_unsent(latest[current_tid]) and latest[current_tid].get('state')!='response_saved':continue
            with catalog.connect() as db:
                claimed=db.execute("SELECT 1 FROM shared_page_backlog WHERE target_id=? AND state='claimed'",(current_tid,)).fetchone()
            if claimed:continue
            # A metadata-ready page can still contain a protected draft, be
            # leased by an uploader, or fail its fresh inspection. It must not
            # make all later safe slots unreachable for every original receipt.
            try:
                with lease(current_tid) as acquired:
                    if not acquired:raise ValueError('原页面正在被其他原所有者操作占用')
                    require_slot(config,browser,current_tid)
                    candidate_snapshot=snapshot_page(current_tid,pages[current_tid])
                    if not _idle(pages[current_tid],entry,candidate_snapshot):
                        raise ValueError(candidate_snapshot.get('inspection_error') or '原页面尚未通过完整空闲或完整已收取复用核对')
            except (OSError,ValueError,KeyError,RuntimeError) as exc:
                rejected_targets.add(current_tid)
                report['candidate_waits'].append({'target_id':current_tid,'slot_id':candidate['slot_id'],
                    'reason':str(exc)[:400],'checked_at':time.time()})
                continue
            slot=candidate;break
        if slot is None:continue
        current_tid=slot['target_id'];entry=pool['windows'][current_tid]
        try:
            with lease(current_tid) as acquired:
                if not acquired:continue
                page = pages[current_tid]
                snapshot = snapshot_page(current_tid, page)
                if not _idle(page,entry,snapshot):continue
                with lock_factory(timeout=5):
                    if stopping() or not _enabled(config, kind):continue
                    require_slot(config, browser, current_tid)
                    live_registry = _read(registry_path(config))
                    if (live_registry['window_id'] != registry['window_id']
                            or next(s for s in live_registry['slots'] if s['slot_id'] == slot['slot_id']) != slot):
                        raise ValueError('原回执恢复槽位变化')
                    if not _idle(page,entry,snapshot_page(current_tid, page)):
                        raise ValueError('原回执恢复前页面变化')
                    original = read_attempt(source)
                    if original['_ledger_sha256'] != record['_ledger_sha256']:raise ValueError('原回执CAS变化')
                    prompt = source.with_name('prompt-actual.txt').read_bytes()
                    if hashlib.sha256(prompt).hexdigest() != record.get('actual_prompt_sha256'):
                        raise ValueError('原实际提示指纹变化')
                    saved = _identity(record)
                    packet_sha = _source(catalog, source, saved)
                    directory.mkdir(parents=True, exist_ok=True)
                    atomic_bytes(directory/'prompt-actual.txt', prompt)
                    atomic_json(directory/'attempt.json', {**saved, 'target_id':current_tid})
                    proof = {'id':rid, 'state':'prepared', 'kind':kind,
                             'original_ledger':str(source), 'original_sha256':record['_ledger_sha256'],
                             'original_attempt':saved, 'collection_target_id':current_tid,
                             'packet_sha256':packet_sha,
                             'retirement_journal':str(journal_path),
                             'retirement_sha256':__import__('cards.api',fromlist=['web_card_inputs__digest']).web_card_inputs__digest(journal_path),
                             'archive_hashes':journal['archive_hashes'],
                             'archive_identity_files':identity_files,
                             'window_id':registry['window_id'], 'slot_id':slot['slot_id'],
                             'original_slot_id':journal['slot_id'],
                             'slot_snapshot':slot, 'reuse_snapshot':snapshot}
                    import copy
                    proof['previous_entry']=copy.deepcopy(entry)
                    atomic_json(proof_path, proof)
                # Navigating an already-sent unique conversation does not submit
                # the original scientific request. No send/upload/UI clicks exist.
                _navigate(config,catalog,browser,pool,page,proof_path,proof,stopping,lock_factory)
                report['started'].append(rid)
                break  # At most one new recovery navigation per maintenance pass.
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            report['blocked'].append({'ledger':str(source), 'error':str(exc)[:400]})
    atomic_json(root/'original-receipt-recovery-status.json', report)
    return report
