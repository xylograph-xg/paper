"""Explicit rework authorization bound to the original card fingerprint."""
import json
import re
from core.api import paths__WorkspacePath as Path
from .web_card_inputs import digest


def archived_capacity_deferral(path, attempt, packet):
    """Recognize the legacy pre-page capacity guard inside a checked archive.

    That exact exception was raised before page selection/creation in the old
    transport. This is evidence of that guard, not an inference from a blank
    page. Keep the original ledger unchanged; generic deferred stays unknown.
    """
    inputs=attempt.get('inputs')
    bound_inputs=(isinstance(inputs,dict) and {'source.pdf','visual.pdf','source-context.json','prompt.txt'}==set(inputs)==set(packet['input_hashes'])
        and all(isinstance(h,str) and re.fullmatch(r'[0-9a-f]{64}',h) for h in inputs.values())
        and all(inputs.get(k)==packet['input_hashes'].get(k) for k in ('source.pdf','visual.pdf')))
    return (attempt.get('state')=='deferred' and attempt.get('provider')=='chatgpt'
            and attempt.get('error')=='DeferredWeb: chatgpt 已达20页，等待本任务页收取/关闭'
            and bound_inputs
            and not any(attempt.get(k) for k in ('target_id','conversation_url','actual_prompt_sha256',
                'raw_sha256','send_click_started','settings','prior_count','upload_bundle'))
            and type(attempt.get('created')) in (int,float)
            and type(attempt.get('finished')) in (int,float)
            and 0<=attempt['finished']-attempt['created']<=5
            and path.parent.parent.name=='history'
            and {p.name for p in path.parent.iterdir()}=={'attempt.json'})

def authorization(job,paper):
    record=json.loads(job['selection']).get('rework')
    if not record:return None
    old=Path(record['old_card_path'])
    backup=Path(record['backup'])/'card.json'
    if paper.get('card_path')!=str(old) or not old.is_file() or digest(old)!=record['old_sha256']:
        raise ValueError('重做授权对应的旧卡片已变化，保留原卡片待核对')
    if not backup.is_file() or digest(backup)!=record['old_sha256']:
        raise ValueError('重做旧卡片备份指纹不一致')
    return record


def archived_receipts(catalog, job):
    """Exempt only complete old receipts belonging to a committed source rework.

    Active or unrelated history is still handled by the ordinary no-resend gate.
    No receipt or archived answer is modified or supplied to the new model call.
    """
    trial_paths=[]
    if json.loads(job['selection']).get('manual_seed_trial'):
        from .seed_trials import archived_receipts as trial_receipts
        trial_paths=trial_receipts(catalog,job)
    paper = catalog.get(job['paper_id'])
    record = authorization(job, paper)
    if not record or record.get('kind') != 'source_review':
        return trial_paths
    if (any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope'))
            or digest(paper['asset_path']) != job['source_sha256']):
        raise ValueError('重做原文身份或指纹待核对')
    with catalog.connect() as db:
        if db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'", (paper['id'],)).fetchone():
            raise ValueError('人工保护的卡片不自动重做')
        events = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM events WHERE paper_id=? AND kind='card_review_rework'", (paper['id'],))]
    if paper['decision'] != 'unreviewed' or not any(e.get('review_id') == record['review_id'] for e in events):
        raise ValueError('缺少已提交的原文重做事件')
    if digest(record['review_report']) != record['review_report_sha256']:
        raise ValueError('原重做核验报告指纹变化')
    root = catalog.path.parent/'web_cards'/paper['id']
    from .web_card_retry import finished_response, known_unsent
    exempt = []
    for event in events:
        folder = root/'history'/('source-review-'+event['review_id'])
        intent = json.loads((folder/'reset-intent.json').read_text())
        packet = json.loads((folder/'packet.json').read_text())
        if (intent.get('review_id') != event['review_id'] or
                intent.get('job', {}).get('paper_id') != paper['id'] or
                packet.get('source_original_sha256') != job['source_sha256']):
            raise ValueError('原重做归档身份或原文变化')
        receipts = list(folder.rglob('attempt.json'))
        if not receipts:
            raise ValueError('原重做归档没有回执')
        # A complete primary receipt and its original packet are required before
        # exempting any old pre-page guard records in this authorized archive.
        primary=folder/'chatgpt/attempt.json'
        finished_response(primary,json.loads(primary.read_text()),packet)
        for path in receipts:
            attempt = json.loads(path.read_text())
            if known_unsent(attempt) or archived_capacity_deferral(path,attempt,packet):
                exempt.append(path)
            else:
                finished_response(path, attempt, packet)
                exempt.append(path)
    return exempt+trial_paths


def submission_history(catalog, job, folder):
    from browser.api import attempt_history__submission_history as check
    return check(folder, exclude_paths=archived_receipts(catalog, job))
