"""Offline acceptance of a reviewed web card; never creates a scientific pass."""
import json
import math
from core.api import paths__WorkspacePath as Path
from cards.api import web_card_inputs__digest as digest, web_card_inputs__parse_card as parse_card

VERSION = 'web-production-v1'


def same_scientific_pass(saved, current):
    """Compare historical passing assessments across diagnostic schema changes."""
    if not all(saved.get(key) == current.get(key) == value for key, value in
               {'action':'pass', 'verdict':'pass', 'pass':True, 'full_source_checked':True}.items()):
        return False
    historical = dict(saved)
    if 'coverage_limitations' not in saved and current.get('coverage_limitations') == []:
        historical['coverage_limitations'] = []
    raw = current.get('raw_weighted_score')
    if 'raw_weighted_score' not in saved and type(raw) in (int, float) and math.isfinite(raw):
        if round(raw, 2) == saved.get('weighted_score'):
            historical['raw_weighted_score'] = raw
    if saved.get('failure_kind') == 'unsubstantiated' and current.get('failure_kind') is None:
        # Older parsers used this fallback even on an explicit scientific pass.
        historical['failure_kind'] = None
    return historical == current


def evaluate(card, path, job, folder, assessment, *, published_path=None):
    """Return independent, version-bound acceptance or explicit blockers.

    The caller has already checked the live Catalog source and human guards.
    Old cards must pass the current strict parser without adding missing fields.
    No files, scores, scientific text or controls are changed here.
    """
    path, folder = Path(path), Path(folder)
    published_path = Path(published_path) if published_path is not None else path
    result = {'version': VERSION, 'complete': False, 'blockers': [],
              'review_id': job['id'], 'card_sha256': job['card_sha256'],
              'source_sha256': job['source_sha256']}
    try:
        score = assessment.get('weighted_score')
        issues = assessment.get('issue_counts', {})
        if not (assessment.get('pass') is True and assessment.get('action') == 'pass'
                and assessment.get('verdict') == 'pass' and assessment.get('full_source_checked') is True
                and type(score) in (int, float) and math.isfinite(score) and 85 <= score <= 100
                and assessment.get('missing_inputs') == []
                and issues.get('major') == 0 and issues.get('critical') == 0):
            raise ValueError('完整科学核验尚未通过')
        meta = card.get('meta', {})
        if meta.get('producer')!='web_card_service' or meta.get('provider')!='chatgpt':
            raise ValueError('生产合同只接续当前主GPT网页卡片')
        if meta.get('card_contract_version') not in (None,'card-contract-v2'):
            raise ValueError('未知或旧结构合同版本，保留原科学报告')
        if digest(path) != job['card_sha256']:
            raise ValueError('生产验收卡片版本变化')
        if meta.get('source_original_sha256') != job['source_sha256']:
            raise ValueError('生产验收原文版本变化')
        from .card_review_queue import check_packet
        packet = check_packet(folder)
        if (packet.get('job_id') != job['id'] or packet.get('card_sha256') != job['card_sha256']
                or packet.get('source_original_sha256') != job['source_sha256']
                or packet.get('review_images_version') != 1 or packet.get('review_materials_version') != 2):
            raise ValueError('完整原卡、发送副本及实际图像合同未绑定')
        original = json.loads((folder/'card-original.json').read_text())
        if original != card or digest(folder/'card-original.json') != job['card_sha256']:
            raise ValueError('核验原卡与当前卡片不一致')
        if (digest(published_path.with_name('source.pdf')) != meta.get('source_sha256')
                or packet['input_hashes'].get('source.pdf') != meta.get('source_sha256')):
            raise ValueError('发布原文与核验原文不一致')
        # Reuse the strict production parser without changing the persisted card.
        # Its image association is ignored; actual images are checked below.
        descriptor = {'card_contract_version': 'card-contract-v2', 'page_count': packet['page_count'],
                      'paper_evaluation_version': meta.get('paper_evaluation_version'),
                      'page_manifest': [{'image': ''} for _ in range(packet['page_count'])]}
        parse_card(json.dumps(card, ensure_ascii=False), descriptor)
        manifest = json.loads((folder/'card-image-manifest.json').read_text())['images']
        images = {str(Path(row['path']).resolve()): row for row in manifest}
        if len(images) != len(manifest):raise ValueError('实际图像清单含重复路径')
        sent = json.loads((folder/'card-review.json').read_text())
        expected_sent = {k:v for k,v in card.items() if k not in ('meta', 'paper_evaluation')}
        # Verify the exact declared transformation, including every scientific field.
        import copy
        expected_sent = copy.deepcopy(expected_sent)
        used = set()
        for group in ('figures', 'equations', 'tables'):
            for item in expected_sent[group]:
                raw = Path(item.get('image_path') or '')
                image = (raw if raw.is_absolute() else published_path.parent/raw).resolve()
                row = images.get(str(image))
                if row is None or digest(image) != row['sha256']:
                    raise ValueError('当前实际卡片图像未被完整核验')
                used.add(str(image))
                item['image_path'] = 'card-images.pdf#page='+str(row['page'])
                item['review_image'] = {'file': 'card-images.pdf', 'page': row['page'], 'sha256': row['sha256']}
        if used != set(images) or sent != expected_sent:
            raise ValueError('发送副本与原卡的逐项转换不一致')
        from cards.api import web_card_retry__finished_response as finished_response
        attempt = json.loads((folder/'attempt.json').read_text())
        finished_response(folder/'attempt.json', attempt, packet)
        result.update(complete=True, strict_schema_verified=True, report_sha256=digest(folder/'feedback.json'),
                      review_packet_sha256=digest(folder/'packet.json'),
                      raw_sha256=attempt['raw_sha256'], image_count=len(images))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        result['blockers'].append(str(exc))
    return result


def reconcile(catalog, config, *, limit=5):
    """Resume metadata-only acceptance for existing exact passing versions.

    Runs in the original material worker, respects review/seed/human pauses,
    and preserves old scientific reports and publication intents byte-for-byte.
    """
    from .card_review_queue import enabled, current, protected, parse_review, finish_publication
    from core.api import services__atomic_json as atomic_json, workflow_priority__seed_first as seed_first
    import copy
    import fcntl
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('生产验收批量必须为1至20的整数')
    root = catalog.path.parent/'production-acceptance'
    report = {'accepted':[], 'blocked':[], 'state':'paused' if not enabled(config) else 'checked'}
    if not enabled(config):return report
    root.mkdir(exist_ok=True)
    with (root/'acceptance.lock').open('a') as lock:
        try:fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {**report, 'state':'another_check_running'}
        for intent_path in root.glob('*/*/publication-intent.json'):
            intent = json.loads(intent_path.read_text())
            if intent.get('state') == 'completed':continue
            try:
                finish_publication(catalog,intent,intent_path.parent,config)
                report['accepted'].append(intent['job']['paper_id'])
            except (OSError,ValueError,KeyError,TypeError) as exc:
                report['blocked'].append({'path':str(intent_path),'error':str(exc)[:400]})
        with catalog.connect() as db:
            rows=seed_first(db,[dict(r) for r in db.execute("SELECT * FROM card_review_jobs WHERE state='passed' AND json_extract(result,'$.publication_alias') IS NOT 1 ORDER BY updated,id")])
        for job in rows:
            if len(report['accepted'])>=limit or not enabled(config):break
            try:
                paper=catalog.get(job['paper_id']);path=Path(paper.get('card_path') or '')
                card=json.loads(path.read_text());meta=card.get('meta',{})
                if meta.get('production_contract_complete') is True:continue
                if meta.get('source_review',{}).get('job_id')!=job['id'] or meta.get('scientific_verified') is not True:continue
                # Existing fields must independently pass the strict parser;
                # an old generation flag never supplies missing scientific data.
                before=digest(path)
                paper,_,_=current(catalog,{**job,'card_sha256':before},config)
                if protected(catalog,paper):continue
                from core.api import seed_focus__allowed as allowed
                if not allowed(config,job['paper_id']):continue
                backup=path.parent/'history'/('source-review-'+job['id'])/'card.json'
                original=json.loads(backup.read_text())
                if {k:v for k,v in original.items() if k!='meta'}!={k:v for k,v in card.items() if k!='meta'}:
                    raise ValueError('已通过版本的科学内容变化')
                folder=Path(job['folder']);_,assessment=parse_review((folder/'response-raw.txt').read_text(),folder,
                    optional_external_supplements=config.get('review_standard',{}).get('external_supplements_optional') is True)
                saved_assessment=json.loads(job['result'])
                if not same_scientific_pass(saved_assessment,assessment):raise ValueError('原科学核验记录变化')
                proof=meta['source_review']
                if (proof.get('card_sha256')!=job['card_sha256'] or proof.get('source_sha256')!=job['source_sha256']
                        or proof.get('report_sha256')!=digest(folder/'feedback.json')):
                    raise ValueError('已通过卡片的原科学报告绑定变化')
                acceptance=evaluate(original,backup,job,folder,assessment,published_path=path)
                if not acceptance['complete']:
                    report['blocked'].append({'paper_id':job['paper_id'],'blockers':acceptance['blockers']});continue
                import hashlib
                key=hashlib.sha256((before+VERSION+acceptance['report_sha256']).encode()).hexdigest()
                output=root/job['paper_id']/key;output.mkdir(parents=True,exist_ok=True)
                if (output/'publication-intent.json').exists():continue
                with (path.parent/'web-publish.lock').open('a') as publication_lock:
                    fcntl.flock(publication_lock,fcntl.LOCK_EX)
                    if digest(path)!=before:raise ValueError('生产验收期间正式卡片变化')
                    candidate=copy.deepcopy(card)
                    candidate['meta'].update(production_contract_complete=True,
                        production_contract_status='verified',production_contract=acceptance)
                    atomic_json(output/'card-before.json',card)
                    atomic_json(output/'card-candidate.json',candidate)
                    intent={'kind':'production_acceptance','state':'pending','job':job,'result':saved_assessment,
                        'path':str(path),'before':before,'after':digest(output/'card-candidate.json'),
                        'scientific_before':job['card_sha256'],'evidence_folder':str(folder)}
                    atomic_json(output/'publication-intent.json',intent)
                    finish_publication(catalog,intent,output,config)
                report['accepted'].append(job['paper_id'])
            except (OSError,ValueError,KeyError,TypeError) as exc:
                report['blocked'].append({'paper_id':job['paper_id'],'error':str(exc)[:400]})
    atomic_json(root/'status.json',report)
    return report
