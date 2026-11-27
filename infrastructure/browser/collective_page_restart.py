"""Mass technical failure recovery; no permission to resend any request."""
import hashlib,time,re,json
from core.api import paths__WorkspacePath as Path
from .shared_page_health import _uncollected_history


def _bound_upload_bundle(record):
    """Read legacy review ZIP evidence from its unchanged, verified packet."""
    bundle=record.get('upload_bundle',{})
    if bundle:return bundle
    review_id=record.get('review_id')
    if not review_id or not record.get('inputs') or not record.get('actual_prompt_sha256'):
        return {}
    try:
        folder=Path(record['_ledger_path']).parent
        if folder.name!=review_id or folder.parent.parent.name!='card_reviews':return {}
        from review.api import card_review_queue__check_packet as check_packet
        packet=check_packet(folder)
        if (packet.get('job_id')!=review_id or packet.get('input_hashes')!=record['inputs'] or
                packet.get('actual_prompt_sha256')!=record['actual_prompt_sha256']):return {}
        return packet['upload_bundle']
    except (OSError,ValueError,KeyError,TypeError):return {}


def _verified_cached_attachment(root, name):
    if Path(name).name!=name:return False
    alias=re.sub(r'\s*\([0-9]+\)(?=\.zip$)','',name)
    if not re.fullmatch(r'[0-9a-f]{64}\.zip',alias):return False
    try:
        from codex_desktop_chat.api import bundles__verify_bundle as verify_bundle
        bundle=verify_bundle(root/'app-upload-zips'/alias)
        key=hashlib.sha256(json.dumps(bundle['manifest_files'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return alias in (key+'.zip',bundle['zip_sha256']+'.zip')
    except Exception:return False  # A rejected ZIP grants no page cleanup.


def episode_targets(policy, report, existing, registered, at):
    targets=set(existing) & set(registered)
    if active(policy,report,at):
        targets.update(tid for tid,h in report.get('pages',{}).items()
                       if tid in registered and h.get('health') in ('dirty','unknown','maintenance_error','broken'))
    return targets


def active(policy,report,at):
    if policy.get('collective_restart_enabled') is not True:return False
    stamp=report.get('checked_at')
    minimum=policy.get('collective_min_pages',5)
    if type(minimum) is not int or not 2<=minimum<=20:return False
    if type(stamp) not in (int,float) or not 0<=at-stamp<=90:return False
    return sum(report.get('counts',{}).get(k,0) for k in ('dirty','unknown','maintenance_error','broken'))>=minimum


def eligible(health,entry,record,history):
    s=health.get('evidence',{}).get('snapshot',{})
    if health.get('health') not in ('dirty','healthy_blank'):return False
    if entry.get('owned') is False or entry.get('state') in ('busy','submitting','uploading','preparing','collecting'):return False
    if record:
        if (record.get('state')!='not_sent' or record.get('send_click_started') is not False
            or record.get('target_id')!=s.get('target_id')):return False
    elif not (entry.get('never_submitted') is True and not history and (entry.get('startup_request_id') or
              entry.get('origin')=='shared_page_health_repair' and entry.get('repair_id'))):return False
    if (s.get('inspection_complete') is not True or s.get('streaming') is not False or s.get('uploading') is True
        or s.get('user_texts') or s.get('answer_texts') or s.get('login') or s.get('verification') or s.get('quota')
        or s.get('url','').rstrip('/')!='https://chatgpt.com'):return False
    if _uncollected_history(s['target_id'],history):return False
    draft=s.get('draft','')
    names=s.get('attachment_names',[])
    pipeline_draft=draft.startswith(('仅依据附件完整原文独立生成中文论文阅读卡片。材料标识 web-card-',
                                   '你是独立论文阅读卡片评审。样本类型：'))
    if draft.strip() and (not pipeline_draft or record and names):
        try:
            text=(Path(record['_ledger_path']).parent/'prompt-actual.txt').read_text()
            if hashlib.sha256(text.encode()).hexdigest()!=record.get('actual_prompt_sha256'):return False
            dense = lambda value: re.sub(r'\s+', '', value)
            if dense(draft) not in (dense(text),dense(text.splitlines()[0])):return False
        except (OSError,ValueError,KeyError,IndexError,TypeError):return False
    if s.get('attachments') or names:
        if not names:return False
        bundle=_bound_upload_bundle(record) if record else {}
        expected=Path(bundle.get('zip_path','')).name
        root=next((p.parent for p in Path(record['_ledger_path']).parents if p.name in ('web_cards','card_reviews')),None) if record else Path(entry['_material_root']) if entry.get('_material_root') else None
        def matches(name):
            if name==expected:return True
            # Chrome may suffix an already uploaded identical ZIP with (1).
            alias=re.sub(r'\s*\([0-9]+\)(?=\.zip$)','',name)
            if alias==expected and record:
                file=Path(bundle.get('zip_path',''))
                return file.is_file() and hashlib.sha256(file.read_bytes()).hexdigest()==bundle.get('zip_sha256')
            return bool(not record and root and _verified_cached_attachment(root,name))
        if any(not matches(n) for n in names):return False
    return True


def timed_unsent_restart(policy,health,entry,record,history,previous,at):
    from .stall_timeouts import timeout_seconds
    seconds=timeout_seconds(policy,entry,record)
    if type(seconds) not in (int,float) or seconds<=0 or not eligible(health,entry,record,history):return False
    if health.get('health')!='dirty':return False
    key=hashlib.sha256(str([health['evidence']['fingerprint'],(record or {}).get('_ledger_sha256')]).encode()).hexdigest()
    old=(previous or {}).get('unsent_stall',{})
    first=old.get('first_seen',at) if old.get('key')==key else at
    # A fully terminated, explicitly unsent attempt supplies a real fault time.
    finished=(record or {}).get('finished')
    if not old and type(finished) in (int,float) and 0<finished<=at:first=min(first,finished)
    health['unsent_stall']={'key':key,'first_seen':first,'checked_at':at,'limit_seconds':seconds}
    return at-first>seconds


def failed_upload_eligible(policy,health,entry,record,history,network_errors,at):
    """Explicit 2026-10-15 exception for failed, never-sent native uploads.

    A progress bar alone is never cancellation proof. Require the ended client
    receipt, matching terminal network failure, exact frozen files, blank user
    history and an unchanged pipeline draft. Unknown/sent requests stay intact.
    """
    if policy.get('failed_upload_recovery_enabled') is not True:return False
    s=health.get('evidence',{}).get('snapshot',{})
    if not record or health.get('health')!='uploading' or not record.get('inputs'):return False
    if entry.get('review_id') and entry['review_id']!=record.get('review_id'):return False
    if (record.get('state')!='not_sent' or record.get('send_click_started') is not False
            or type(record.get('owner_pid')) is not int or record['owner_pid']<=0
            or type(record.get('finished')) not in (int,float)
            or not 0<record['finished']<=at or record.get('target_id')!=s.get('target_id')):return False
    from .stall_timeouts import timeout_seconds
    limit=timeout_seconds(policy,entry,record)
    if limit is None or at-record['finished']<=limit:return False
    created=record.get('created')
    if type(created) not in (int,float):return False
    failures=[e for e in network_errors if e.get('target_id')==s.get('target_id') and
              type(e.get('at')) in (int,float) and created<=e['at']<=at and
              e.get('method')=='PUT' and (e.get('failure') in
              ('net::ERR_HTTP2_PROTOCOL_ERROR','net::ERR_HTTP2_PING_FAILED',
               'net::ERR_CONNECTION_RESET','net::ERR_CONNECTION_CLOSED','net::ERR_TIMED_OUT')
               or type(e.get('status')) is int and e['status']>=400)]
    detail=record.get('upload_diagnostic') or {}
    ended_upload=(record.get('error')=='附件上传失败' or record.get('upload_failure_stage') in
                  ('entry','attach','attach_write','attach_visible','settle') or
                  detail.get('failure_kind') in ('write_failed','attachment_not_shown','settle_timeout','full_page_settle_timeout'))
    # The user also authorized cancelling an ended upload that still occupies
    # a native slot. Legacy owners did not keep durable per-request network
    # errors; an exact ended upload receipt is separate evidence, never a claim
    # that this target experienced a particular network error.
    if not failures and not ended_upload:return False
    # Reuse all existing draft/history/attachment protections with only the
    # explicitly authorized upload flag exception; never modify the observation.
    preview={'health':'dirty','evidence':{'snapshot':dict(s,uploading=False)}}
    if not eligible(preview,entry,record,history):return False
    try:
        folder=Path(record['_ledger_path']).parent
        if not record.get('review_id') and entry.get('active_paper_id') and folder.parent.name!=entry['active_paper_id']:return False
        text=(folder/'prompt-actual.txt').read_text()
        if hashlib.sha256(text.encode()).hexdigest()!=record.get('actual_prompt_sha256'):return False
        if s.get('draft','').strip() and s['draft'] not in (text,text.splitlines()[0]):return False
        bundle=_bound_upload_bundle(record);zip_path=Path(bundle.get('zip_path',''))
        if not zip_path.is_file() or hashlib.sha256(zip_path.read_bytes()).hexdigest()!=bundle.get('zip_sha256'):return False
        for name,expected in record.get('inputs',{}).items():
            if Path(name).is_absolute() or '..' in Path(name).parts:return False
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:return False
    except (OSError,ValueError,KeyError,IndexError,TypeError):return False
    health['failed_upload_network_proof']=[{k:e.get(k) for k in ('at','target_id','host','method','status','failure')} for e in failures[-4:]]
    health['failed_upload_receipt_proof']={'ledger_sha256':record['_ledger_sha256'],
        'ended_upload':ended_upload,'original_put_receipt_unknown':detail.get('original_put_unknown') is True}
    return True


def failed_upload_restart(policy,health,entry,record,history,network_errors,previous,at):
    if not failed_upload_eligible(policy,health,entry,record,history,network_errors,at):return False
    key=hashlib.sha256((health['evidence']['fingerprint']+record['_ledger_sha256']).encode()).hexdigest()
    old=(previous or {}).get('failed_upload_check',{})
    same=old.get('key')==key
    last=old.get('checked_at',0) if same else 0
    rounds=old.get('rounds',0) if same else 0
    if not rounds or at-last>=30:rounds+=1;last=at
    health['failed_upload_check']={'key':key,'rounds':rounds,'checked_at':last}
    return rounds>=2
