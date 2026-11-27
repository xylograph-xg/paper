"""Grow the main discovery graph from GPT-scored selected cards, without inference."""
import hashlib
import json
import math
import re
import sqlite3
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__now as now, catalog__doi as doi
from core.api import control__pause_decision as pause_decision
from core.api import services__atomic_json as atomic_json



CORE_TITLE = re.compile(r'OLED|organic light.emitting|light.emitting diode|\bTADF\b|thermally activated|phosphorescen|triplet|exciton|singlet fission|spin.orbit|spin coherence|charge transport|organic semiconductor|emitter',re.I)
METHOD_TITLE = re.compile(r'machine learning|data mining|risk minimization|neural|dataset|algorithm|benchmark|classification|regression|language model|\bllm\b|artificial intelligence|reinforcement learning',re.I)


def seed_on_topic(title, abstract=''):
    """A auto-promoted seed must be OLED/triplet/exciton-adjacent, not generic ML/luminescence."""
    from .preprints import relevant
    text=str(title or '')+' '+str(abstract or '')
    if not relevant(text):return False
    if METHOD_TITLE.search(text) and not CORE_TITLE.search(str(title or '')):return False
    return True


def expand_when_idle(catalog,config):
    def finish(value):
        atomic_json(catalog.path.parent/'seed-expansion-status.json',{k:v for k,v in value.items() if k!='metadata'})
        return value
    result={'state':'disabled','updated_at':now()}
    if not config.get('fetch_pipeline',{}).get('auto_seed_expansion'):return finish(result)
    if not pause_decision(config,'fetch').allowed:return finish({**result,'state':'paused'})
    if 'seed_related' not in config.get('discovery_channels',[]):return finish({**result,'state':'seed_channel_disabled'})
    with catalog.connect() as db:
        if db.execute("SELECT 1 FROM jobs WHERE kind IN ('acquire','acquire_fallback','import') AND state IN ('queued','running','waiting_storage') LIMIT 1").fetchone():return finish({**result,'state':'download_queue_busy'})
        if db.execute("SELECT 1 FROM discovery_pending WHERE state='pending' AND retry_at<=? LIMIT 1",(time.time(),)).fetchone():return finish({**result,'state':'retry_candidate_ready'})
        try:
            rows=db.execute("SELECT p.* FROM papers p JOIN web_card_jobs j ON j.paper_id=p.id WHERE p.seed=0 AND p.card_path IS NOT NULL AND p.acquisition='available' AND p.decision='unreviewed' AND j.state='completed' AND j.provider='chatgpt'").fetchall()
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc):raise
            rows=[]
        candidates=[]
        signatures={}
        for row in rows:
            try:metadata=json.loads(row['metadata'])
            except ValueError:continue
            if not isinstance(metadata,dict):continue
            if not doi(metadata.get('doi')):continue
            if any(metadata.get(k) for k in ('user_seed_disabled','selected_as_seed','auto_seed_quality','is_correction','identity_review_required','version_review_required','out_of_scope')):continue
            if db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind IN ('human_decision','seed_auto_quality') LIMIT 1",(row['id'],)).fetchone():continue
            # Content pulled from a manual seed never becomes a new seed, even
            # when it has a high card score. New automatic seeds must be on-topic.
            try:
                if db.execute('SELECT 1 FROM manual_seed_lineage WHERE paper_id=?',(row['id'],)).fetchone():continue
                if db.execute("SELECT 1 FROM seed_discovery_origins o JOIN identifiers i ON i.kind='doi' AND i.value=o.seed_doi "
                              "JOIN manual_seed_roots r ON r.paper_id=i.paper_id WHERE o.paper_id=? LIMIT 1",(row['id'],)).fetchone():continue
            except sqlite3.OperationalError:pass
            if not seed_on_topic(row['title'],metadata.get('abstract')):continue
            try:
                path=Path(row['card_path']);asset=Path(row['asset_path'])
                before=(path.stat(),asset.stat())
                raw=path.read_bytes();card=json.loads(raw)
                item=card['paper_evaluation']['overall_quality'];score=item['score'];pages=item['source_pages']
                if type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=100:continue
                if not isinstance(item.get('reason'),str) or not item['reason'].strip():continue
                if not isinstance(pages,list) or not pages or any(type(p) is not int or p<1 for p in pages):continue
                meta=card.get('meta',{})
                if meta.get('provider')!='chatgpt' or meta.get('source_original_sha256')!=row['asset_hash']:continue
                if not row['asset_hash'] or hashlib.sha256(Path(row['asset_path']).read_bytes()).hexdigest()!=row['asset_hash']:continue
                after=(path.stat(),asset.stat())
                if before!=after:continue
                signatures[row['id']]=after
                candidates.append((float(score),row['id'],row,metadata,hashlib.sha256(raw).hexdigest(),item))
            except (OSError,ValueError,KeyError,TypeError):continue
        if not candidates:
            result.update(state='waiting_scored_cards',eligible_scored_cards=0)
        else:
            score,pid,row,metadata,card_hash,item=sorted(candidates,key=lambda x:(-x[0],x[1]))[0]
            evidence={'score':score,'card_sha256':card_hash,'card_path':row['card_path'],'reason':item['reason'],'source_pages':item['source_pages'],'selected_at':now(),'basis':'GPT overall literature quality; not independent scientific acceptance'}
            try:
                unchanged=(Path(row['card_path']).stat(),Path(row['asset_path']).stat())==signatures[pid]
            except OSError:
                unchanged=False
            if not unchanged:return finish({**result,'state':'candidate_changed'})
            # All potentially slow file reads above were outside a write transaction.
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone()
            same=current is not None and all(current[k]==row[k] for k in row.keys())
            protected=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind IN ('human_decision','seed_auto_quality') LIMIT 1",(pid,)).fetchone()
            busy=db.execute("SELECT 1 FROM jobs WHERE kind IN ('acquire','acquire_fallback','import') AND state IN ('queued','running','waiting_storage') LIMIT 1").fetchone()
            retry=db.execute("SELECT 1 FROM discovery_pending WHERE state='pending' AND retry_at<=? LIMIT 1",(time.time(),)).fetchone()
            complete=db.execute("SELECT 1 FROM web_card_jobs WHERE paper_id=? AND state='completed' AND provider='chatgpt'",(pid,)).fetchone()
            if not same or protected or busy or retry or not complete or not pause_decision(config,'fetch').allowed:
                return finish({**result,'state':'candidate_changed'})
            metadata.update(selected_as_seed=True,auto_seed_quality=evidence)
            db.execute('UPDATE papers SET seed=1,metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),pid))
            db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'seed_auto_quality',json.dumps(evidence,ensure_ascii=False),now()))
            result.update(state='expanded',paper_id=pid,source='scored_selected',score=score,eligible_scored_cards=len(candidates),metadata=metadata)
    return finish(result)
