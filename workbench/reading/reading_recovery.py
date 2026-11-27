"""Bounded recovery bound to actual workflow/model inputs, preserving history."""
import json
from core.api import paths__WorkspacePath as Path
from .reading_contract import READING_CONTRACT_VERSION
from core.api import services__SCREEN_PROMPT_VERSION as SCREEN_PROMPT_VERSION
from read.api import generation_state__generation_complete as generation_complete

READ_KINDS=('screen','deep_read')
READING_POLICY=f'reading-v{READING_CONTRACT_VERSION}-screen-v{SCREEN_PROMPT_VERSION}'


def activate(catalog,config,dry_run=False):
    import fcntl
    with (catalog.path.parent/'reading-policy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _activate(catalog,config,dry_run)


def _activate(catalog,config,dry_run=False):
    from .reading_contract import producer_fingerprint,file_digest,verified_completion
    from .reading_bridge import reading_config,reading_input_hash
    from core.api import services__screen_workflow_fingerprint as screen_workflow_fingerprint
    from core.api import model_identity__resolve_identity as resolve_identity
    import hashlib
    try:
        digest=resolve_identity(config['model'])
        screen_hash=screen_workflow_fingerprint(config['model'])
        revision=READING_POLICY+':'+hashlib.sha256((producer_fingerprint()+screen_hash+digest).encode()).hexdigest()
        reader_config=reading_config(config['model'],config.get('reading_domain_prompt'),model_digest=digest)
    except (OSError,ValueError,RuntimeError) as exc:
        return {'revision':READING_POLICY,'jobs':[],'skipped':{'input_identity_unavailable':1},'error':str(exc)}
    result={'revision':revision,'dry_run':dry_run,'jobs':[],'skipped':{}}
    def skip(reason):result['skipped'][reason]=result['skipped'].get(reason,0)+1
    with catalog.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS reading_recovery_processed(revision TEXT,kind TEXT,paper_id TEXT,PRIMARY KEY(revision,kind,paper_id))')
        applied=db.execute("SELECT 1 FROM events WHERE kind='reading_policy_activation' AND json_extract(payload,'$.revision')=?",(revision,)).fetchone()
        failures=[dict(r) for r in db.execute("SELECT * FROM jobs WHERE kind IN ('screen','deep_read') AND state IN ('failed','partial','waiting_storage') AND NOT EXISTS(SELECT 1 FROM reading_recovery_processed p WHERE p.revision=? AND p.kind=jobs.kind AND p.paper_id=jobs.paper_id) ORDER BY created DESC",(revision,))]
    seen=set()
    budget=config.get('reading_recovery_batch_size',20)
    finished=True
    for job in failures:
        if len(result['jobs'])>=budget:finished=False;break
        with catalog.connect() as db:
            backlog=db.execute("SELECT count(*) FROM jobs WHERE kind=? AND state IN ('queued','running','waiting_storage','waiting_workflow')",(job['kind'],)).fetchone()[0]
        if backlog>=config.get('reading_queue_limit',60):
            finished=False;skip('queue_capacity');continue
        key=(job['kind'],job['paper_id'])
        if key in seen:continue
        seen.add(key)
        if not job['paper_id']:continue
        paper=catalog.get(job['paper_id'])
        if paper['decision']=='reject' or any(paper['metadata'].get(k) for k in ('identity_review_required','out_of_scope')):
            skip('human_or_identity_gate');continue
        if not paper['asset_path'] or not Path(paper['asset_path']).is_file():skip('original_unavailable');continue
        if job['kind']=='screen' and (paper['assessment'] or {}).get('prompt_version')==SCREEN_PROMPT_VERSION and (paper['assessment'] or {}).get('workflow_fingerprint')==screen_hash:
            skip('current_assessment_exists');continue
        if job['kind']=='deep_read':
            if paper['decision'] not in ('deep_read','original_read'):skip('not_selected');continue
            card={}
            if paper['card_path']:
                try:card=json.loads(Path(paper['card_path']).read_text())
                except (OSError,ValueError):skip('card_needs_manual_check');continue
                if not isinstance(card,dict):skip('card_needs_manual_check');continue
            from review.api import review_protection__protection as protection
            if card.get('meta',{}).get('quality_review') or (paper['card_path'] and protection(Path(paper['card_path']).parent)):skip('reviewed_card_protected');continue
            input_hash=reading_input_hash(file_digest(paper['asset_path']),reader_config)
            meta=card.get('meta',{})
            if meta.get('reading_input_hash')==input_hash:
                from .reading_failures import diagnostics
                if diagnostics(card)['automatic_retry_blocked'] or meta.get('retry_guard',{}).get('automatic_retry_blocked'):
                    skip('same_input_deterministic_failure');continue
                if paper['card_path'] and verified_completion(Path(paper['card_path']).parent):
                    skip('current_card_complete');continue
            payload=json.loads(job.get('payload') or '{}')
            if not card and payload.get('reading_input_hash')==input_hash:
                from .reading_failures import failure_class
                if failure_class(job.get('error'))=='workflow':
                    skip('same_input_workflow_failure');continue
        with catalog.connect() as db:
            recovered=db.execute("SELECT id FROM jobs WHERE kind=? AND paper_id=? AND json_extract(payload,'$.trigger')='reading_policy_recovery' AND json_extract(payload,'$.revision')=? AND json_extract(payload,'$.previous_job_id')=? LIMIT 1",(*key,revision,job['id'])).fetchone()
            if recovered:
                if not dry_run:db.execute('INSERT OR IGNORE INTO reading_recovery_processed VALUES(?,?,?)',(revision,*key))
                skip('recovery_receipt_exists');continue
        with catalog.connect() as db:
            active=db.execute("SELECT 1 FROM jobs WHERE kind=? AND paper_id=? AND state IN ('queued','running','waiting_storage','waiting_workflow')",key).fetchone()
        if active:skip('already_queued');continue
        item={'old_job_id':job['id'],'paper_id':job['paper_id'],'kind':job['kind']}
        if not dry_run:
            item['job_id']=catalog.enqueue(job['kind'],job['paper_id'],{'trigger':'reading_policy_recovery','previous_job_id':job['id'],'revision':revision,**({'reading_input_hash':input_hash} if job['kind']=='deep_read' else {})})
            catalog.event(job['paper_id'],'reading_policy_job',item)
            with catalog.connect() as db:db.execute('INSERT OR IGNORE INTO reading_recovery_processed VALUES(?,?,?)',(revision,*key))
        result['jobs'].append(item)
    result['batch_complete']=finished
    if applied and not result['jobs']:result['already_activated']=True
    if not dry_run:catalog.event(None,'reading_policy_activation' if finished else 'reading_policy_batch',result)
    return result
