"""Read-only metadata projection for ordinary literature organization.

No Catalog construction, migrations, score refreshes, report bodies or worker actions.
"""
import json
from pathlib import Path
import sqlite3


def metadata_rows(catalog_path):
    """Return all registered papers and current version-bound score records.

    SQLite read transaction gives a consistent snapshot. Missing scores remain None;
    review_state is the stored state, never a new scientific/production verdict.
    """
    path = Path(catalog_path).resolve()
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        source = 'papers p'; projection = 'p.id,p.title,p.metadata,p.acquisition,p.asset_path,p.asset_hash source_fingerprint'
        current_scores = 'paper_card_scores' in tables
        if current_scores:
            source += ' LEFT JOIN paper_card_scores s ON s.paper_id=p.id AND s.source_hash=p.asset_hash AND s.card_path=p.card_path'
            projection += ',s.overall_quality,s.direction_novelty'
        else: projection += ',NULL overall_quality,NULL direction_novelty'
        if 'paper_reading_state' in tables:
            source += ' LEFT JOIN paper_reading_state rs ON rs.paper_id=p.id'
            projection += ',coalesce(rs.is_read,0) is_read,coalesce(rs.note,\'\') note'
        else: projection += ',0 is_read,\'\' note'
        if current_scores and 'card_review_jobs' in tables:
            source += ' LEFT JOIN card_review_jobs r ON r.paper_id=p.id AND r.card_sha256=s.card_sha256 AND r.source_sha256=s.source_hash'
            projection += ",r.state review_state,CASE WHEN json_valid(r.result) AND json_type(r.result,'$.weighted_score') IN ('integer','real') THEN json_extract(r.result,'$.weighted_score') END review_score"
        else: projection += ',NULL review_state,NULL review_score'
        rows = []
        for row in db.execute('SELECT ' + projection + ' FROM ' + source + ' ORDER BY p.id'):
            item = dict(row); item['metadata'] = json.loads(item['metadata'])
            item['has_pdf'] = bool(item.pop('asset_path') and item['acquisition'] == 'available')
            item['is_read'] = bool(item['is_read'])
            if item['review_score'] is not None and not 0 <= item['review_score'] <= 100: item['review_score'] = None
            rows.append(item)
        return rows
    finally:
        db.close()


def source_records(catalog_path, paper_ids):
    """Read current source identities and exact registered material pointers, max 100.

    No receipt bodies, scientific cards or workflow writes. Paths are local inputs,
    not authorization to resend or modify the original materials.
    """
    if not isinstance(paper_ids, list) or not 1 <= len(paper_ids) <= 100 or any(not isinstance(p, str) for p in paper_ids):
        raise ValueError('须指定1–100个文献ID')
    db = sqlite3.connect(Path(catalog_path).resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        marks = ','.join('?' for _ in paper_ids)
        rows = {r['id']:dict(r) for r in db.execute('SELECT id,title,metadata,acquisition,asset_path,asset_hash FROM papers WHERE id IN ('+marks+')',paper_ids)}
        for row in rows.values(): row['metadata']=json.loads(row['metadata']); row['materials']=[]
        for table in ('web_card_jobs','card_review_jobs','card_correction_jobs'):
            if table not in tables: continue
            identity = 'paper_id' if table=='web_card_jobs' else 'id'
            for r in db.execute(f'SELECT paper_id,source_sha256,folder,{identity} AS original_job_id FROM {table} WHERE paper_id IN ({marks})',paper_ids):
                if r['paper_id'] in rows and r['folder']:
                    rows[r['paper_id']]['materials'].append({**dict(r),'lane':table})
        return list(rows.values())
    finally:
        db.close()
