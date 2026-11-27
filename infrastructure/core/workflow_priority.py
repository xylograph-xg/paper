"""Version-matched article scores; queue timestamps remain immutable evidence."""
import json
import math


def seed_first(db, records):
    """Stable seed priority for recovery scans; retain original record identities.

    Read-only: no receipt, score, retry deadline or queue state is changed.
    """
    from .seed_focus import filter_records
    records=filter_records(db,records)
    if not records or not db.execute("SELECT 1 FROM sqlite_master WHERE name='manual_seed_roots'").fetchone():
        return records
    ids=json.dumps(sorted({row['paper_id'] for row in records}))
    seeds={row[0] for row in db.execute('SELECT paper_id FROM manual_seed_roots WHERE paper_id IN (SELECT value FROM json_each(?))',(ids,))}
    return sorted(records,key=lambda row:row['paper_id'] not in seeds)


def enabled(config):
    return config.get('web_cards', {}).get('shared_window', {}).get('backlog', {}).get('queue_order') == 'paper_score'


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else None


def _passed_corrections(db, tables, config, paper_ids):
    """Immutable original review evidence keeps a correction pinned through recheck."""
    if not config.get('card_correction', {}).get('priority_passed_first') or not {'card_correction_jobs','papers'} <= tables:
        return {}, {}
    direct, rechecks, origins = {}, {}, set()
    jobs = [dict(row) for row in db.execute('SELECT c.id,c.paper_id,c.source_sha256,c.state,c.payload,c.result '
        'FROM card_correction_jobs c JOIN papers p ON p.id=c.paper_id AND p.asset_hash=c.source_sha256 '
        'WHERE c.paper_id IN (SELECT value FROM json_each(?))',(paper_ids,))]
    for job in jobs:
        try:
            assessment = json.loads(job['payload']).get('assessment', {})
            result = json.loads(job['result'])
        except (TypeError, ValueError):
            continue
        score = _number(assessment.get('weighted_score'))
        issues = assessment.get('issue_counts', {})
        if not (assessment.get('model_report_pass', assessment.get('pass')) is True
                and assessment.get('full_source_checked') is True and assessment.get('verdict') == 'pass'
                and score is not None and score >= 85 and assessment.get('missing_inputs') == []
                and issues.get('major') == 0 and issues.get('critical') == 0):
            continue
        origins.add((job['paper_id'], job['source_sha256']))
    for job in jobs:
        if (job['paper_id'], job['source_sha256']) not in origins:continue
        try:result = json.loads(job['result'])
        except (TypeError, ValueError):continue
        if job['state'] not in ('applied', 'superseded'):
            direct[job['id']] = (job['paper_id'], job['source_sha256'])
        elif job['state'] == 'applied' and result.get('after'):
            rechecks[(job['paper_id'], job['source_sha256'], result['after'])] = job['id']
    return direct, rechecks


def annotate(db, records, config):
    records = list(records)
    if not records:return records
    paper_ids=json.dumps(sorted({record['paper_id'] for record in records}))
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pinned, rechecks = _passed_corrections(db, tables, config, paper_ids)
    manual = {}
    if config.get('manual_literature',{}).get('enabled') and {'manual_card_priority','papers'} <= tables:
        manual = {r[0]:r[1] for r in db.execute('SELECT m.paper_id,m.source_hash FROM manual_card_priority m '
            'JOIN papers p ON p.id=m.paper_id AND p.asset_hash=m.source_hash')}
    seed_fast = set()
    if 'manual_seed_roots' in tables:
        seed_fast = {r[0] for r in db.execute('SELECT paper_id FROM manual_seed_roots')}
    for record in records:
        source = record.get('source_job') or record
        try:selection = json.loads(source.get('selection') or '{}')
        except (ValueError,TypeError):selection = {}
        if not isinstance(selection,dict):selection = {}
        correction = record.get('correction') or {}
        rework = selection.get('rework') or {}
        if not isinstance(rework, dict):rework = {}
        cid = correction.get('id') or rework.get('correction_id')
        if cid is None and record.get('lane') == 'correction':cid = record.get('job_id')
        if cid is None and source.get('kind') in ('formatting','quote_location','source_rework'):
            cid = source.get('id', record.get('job_id'))
        binding = pinned.get(cid)
        record['passed_correction_priority'] = bool(binding and binding[0] == record['paper_id']
            and source.get('source_sha256', binding[1]) == binding[1])
        if record.get('lane') == 'review' or (source.get('card_sha256') and source.get('kind') is None):
            record['passed_correction_priority'] |= (record['paper_id'], source.get('source_sha256'),
                source.get('card_sha256')) in rechecks and source.get('state') not in ('passed','superseded')
        record['manual_priority'] = (record.get('lane','cards') == 'cards' and not selection.get('rework')
            and record.get('paper_id') in manual and source.get('source_sha256') == manual[record['paper_id']])
        record['seed_fast_lane'] = record.get('paper_id') in seed_fast
    if not enabled(config):
        for record in records:record.pop("score_order",None)
        return records
    scores = {}
    if 'paper_card_scores' in tables:
        query='SELECT s.*,r.result AS review_result FROM paper_card_scores s LEFT JOIN card_review_jobs r ON r.paper_id=s.paper_id AND r.card_sha256=s.card_sha256 AND r.source_sha256=s.source_hash' if 'card_review_jobs' in tables else 'SELECT s.*,NULL AS review_result FROM paper_card_scores s'
        query+=' WHERE s.paper_id IN (SELECT value FROM json_each(?))'
        for row in db.execute(query,(paper_ids,)):
            item = dict(row); review_score = None
            if item.get('review_result'):
                try: review_score = _number(json.loads(item['review_result']).get('weighted_score'))
                except (ValueError, TypeError): pass
            quality = _number(item.get('overall_quality'))
            scores[item['paper_id']] = {'article_quality':quality, 'article_review_score':review_score,
                'article_total_score':quality+review_score if quality is not None and review_score is not None else None,
                'article_novelty':_number(item.get('direction_novelty'))}
    policy = config.get('web_cards', {}).get('shared_window', {}).get('backlog', {}).get('fast_lane', {})
    fast_enabled = policy.get('enabled') is True
    quality_min = _number(policy.get('card_quality_min', 80))
    review_min = _number(policy.get('review_score_min', 85))
    total_min = _number(policy.get('total_score_min', 170))
    for record in records:
        source = record.get('source_job') or record
        fallback = {'article_quality':_number(source.get('priority')), 'article_novelty':_number(source.get('novelty')),
                    'article_total_score':None, 'article_review_score':None}
        record.update(scores.get(record['paper_id'], fallback), score_order=True)
        quality = record.get('article_quality'); review = record.get('article_review_score')
        total = record.get('article_total_score')
        record['fast_lane'] = bool(fast_enabled and (
            quality_min is not None and quality is not None and quality >= quality_min or
            review_min is not None and review is not None and review >= review_min or
            total_min is not None and total is not None and total >= total_min))
    return records


def key(record):
    priority = (not record.get('seed_fast_lane',False),
                not record.get('passed_correction_priority',False),
                not record.get('manual_priority',False),
                not record.get('fast_lane',False))
    arrival = (record.get('queued_at', record.get('fifo_at', 0)) or 0,
               record.get('sequence', 0) or 0, record.get('job_id', record.get('id', '')), record.get('lane', ''))
    if not record.get('score_order'):
        return priority + arrival
    total, quality, novelty = (record.get(k) for k in ('article_total_score','article_quality','article_novelty'))
    return (*priority, total is None, -(total or 0), quality is None, -(quality or 0), novelty is None, -(novelty or 0), *arrival)


def sort(db, records, config):
    from .seed_focus import filter_records
    return sorted(annotate(db, filter_records(db,records,config), config), key=key)
