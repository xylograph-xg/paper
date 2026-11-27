"""User-started full-library L2 candidates, verified originals, independent pause/head.

The scheduler and single writer stay in the parent. Eight spawned processes reuse
original text or parse local PDFs; no model, browser, card answer or primary write.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import time

from core.api import literature_catalog__metadata_rows as metadata_rows
from core.api import literature_catalog__source_records as source_records
from . import background as runtime
from .classifier import classify, metadata_fingerprint, RULE_VERSION
from .inputs import prepare_document, digest
from .store import fingerprint

EVIDENCE_BUDGET = 7000  # Same bounded window as the exposed architecture comparison.
BATCH_SIZE = 64
RETRY_SECONDS = 3600
MAX_FAILURE_ATTEMPTS = 3
_COUNTER = None
_CONTROL = None


def level2_status(config): return runtime.level1_status(config, stage='level2')
def level2_start(config): return runtime.level1_start(config, stage='level2')
def level2_control(config, paused): return runtime.level1_control(config, paused, stage='level2')
def level2_release(config): return runtime.level1_release(config, stage='level2')


def _process_init(control, counter):
    global _COUNTER, _CONTROL
    _COUNTER = counter; _CONTROL = Path(control)


def predict_record(record, generation):
    document = prepare_document(record, fallback_pdf=True, budget=EVIDENCE_BUDGET)
    document.update(annotation_scope='level2', generation_fingerprint=generation)
    result = classify(document)
    for key in ('supporting_labels', 'inherited_labels', 'mentions'):
        result[key] = [v for v in result.get(key, []) if v['level'] == 2]
    result.update(level1=[], level1_state='not_requested', annotation_scope='level2',
                  generation_fingerprint=generation)
    return document, result


def _process_predict(record, generation):
    if runtime.read(_CONTROL).get('paused_by_user', False): return None
    with _COUNTER.get_lock(): _COUNTER.value += 1
    try: return predict_record(record, generation)
    finally:
        with _COUNTER.get_lock(): _COUNTER.value -= 1


def signature(row, generation):
    return fingerprint({'metadata': metadata_fingerprint(row), 'source': row.get('source_fingerprint'),
        'available': row['has_pdf'], 'acquisition': row.get('acquisition'), 'generation': generation,
        'protection': {k: row.get('metadata', {}).get(k) for k in
                       ('identity_review_required', 'version_review_required', 'out_of_scope')}})


def blocked_state(document):
    limitations = document.get('limitations', [])
    if 'source_identity_version_or_scope_protected' in limitations: return 'protected'
    if 'supplementary_input_not_main_article' in limitations: return 'supplementary_only'
    if 'current_original_hash_mismatch' in limitations: return 'source_mismatch'
    if 'missing_registered_original' in limitations: return 'awaiting_original'
    return 'missing_input'


def recovery_input(record, generation):
    """Failure-only identity: actual original/material bytes and public parser code.

    Successful frozen label inputs/generation are unchanged. Changed evidence can
    reopen an exhausted failure without a manual reset or a timed blind retry.
    """
    import inspect
    from importlib.metadata import version
    from core.api import paths__WorkspacePath as WorkspacePath
    from read.api import parser__parse_pdf as parse_pdf

    def bound(path):
        if not path: return None
        try: return digest(WorkspacePath(path))
        except OSError as exc: return {'unreadable': type(exc).__name__}

    materials = [{**item, 'files': {name: bound(WorkspacePath(item['folder']) / name)
                  for name in ('packet.json', 'source-context.json')}}
                 for item in record.get('materials', [])]
    try: parser_path = inspect.getsourcefile(parse_pdf)
    except TypeError: parser_path = None
    return fingerprint({'metadata': metadata_fingerprint(record), 'generation': generation,
        'original': {k: record.get(k) for k in ('asset_path', 'asset_hash', 'acquisition')},
        'actual_original_sha256': bound(record.get('asset_path')),
        'protection': {k: record.get('metadata', {}).get(k) for k in
                      ('identity_review_required', 'version_review_required', 'out_of_scope')},
        'materials': sorted(materials, key=lambda item: (item['lane'], item['folder'])),
        'parser_sha256': bound(parser_path), 'pymupdf_version': version('pymupdf')})


class Worker(runtime.Worker):
    process_init = staticmethod(_process_init)

    def __init__(self, config, nonce):
        super().__init__(config, nonce)
        self.p = runtime.paths(config, 'level2')
        self.failures = runtime.read(self.p['service']).get('failures', {})
        self.generation = fingerprint({'scientific_rules': runtime.generation_fingerprint(),
            'input_policy': 'source-identity-v2', 'selection': 'evidence-window-v1',
            'budget_chars': EVIDENCE_BUDGET, 'local_pdf_fallback': True,
            'preparation_sha256': digest(Path(__file__).with_name('inputs.py'))})
        self.state.update(scope='level2', generation_fingerprint=self.generation,
                          evidence_budget_chars=EVIDENCE_BUDGET, local_pdf_fallback=True)

    def check(self, row, state, reason='', count=0, retry_at=0):
        with self.store.connect(True) as db:
            db.execute('INSERT OR REPLACE INTO level2_checks VALUES(?,?,?,?,?,?,?)',
                (row['id'], signature(row, self.generation), state, count, reason[:1000], retry_at,
                 datetime.now(timezone.utc).isoformat()))

    def guarded_record(self, record):
        if not self.allowed(): return None
        with self.mutex: self.active += 1
        try: return predict_record(record, self.generation)
        finally:
            with self.mutex: self.active -= 1

    def cycle(self):
        rows = metadata_rows(self.config['catalog_path'])
        with self.store.connect() as db:
            checks = {r['paper_id']: dict(r) for r in db.execute('SELECT * FROM level2_checks')}
        # No-PDF entries are coverage records, never successful fine-label runs.
        absent = [r for r in rows if not r['has_pdf'] and
                  checks.get(r['id'], {}).get('signature') != signature(r, self.generation)]
        if not self.allowed(): return False
        if absent:
            with self.store.connect(True) as db:
                db.executemany('INSERT OR REPLACE INTO level2_checks VALUES(?,?,?,?,?,?,?)',
                    [(r['id'], signature(r, self.generation), 'awaiting_original', 0,
                      'missing_registered_original', 0, datetime.now(timezone.utc).isoformat()) for r in absent])
            for r in absent:
                checks[r['id']] = {'signature': signature(r, self.generation),
                                  'state': 'awaiting_original', 'core_count': 0, 'retry_at': 0}
        valid = {r['id']: checks[r['id']] for r in rows
                 if checks.get(r['id'], {}).get('signature') == signature(r, self.generation)}
        done = [v for v in valid.values() if v['state'] in ('completed', 'undetermined')]
        waiting = sum(v['state'] == 'awaiting_original' for v in valid.values())
        blocked = sum(v['state'] in ('protected', 'supplementary_only', 'source_mismatch', 'missing_input') for v in valid.values())
        pending = [r for r in rows if r['has_pdf'] and
                   valid.get(r['id'], {}).get('state') not in ('completed', 'undetermined')]
        # Inspect only previous failures, not every successful original, each scan.
        failed_ids = [r['id'] for r in pending if valid.get(r['id'], {}).get('state') == 'failed']
        exhausted = set()
        for offset in range(0, len(failed_ids), 100):
            for record in source_records(self.config['catalog_path'], failed_ids[offset:offset+100]):
                key = recovery_input(record, self.generation)
                old = self.failures.get(record['id'], {})
                attempts = old.get('input_attempts', old.get('attempts', 0))
                # Legacy failures adopt a key without deleting prior attempts/errors.
                if old.get('recovery_input') not in (None, key): attempts = 0
                self.failures[record['id']] = {**old, 'recovery_input': key,
                    'input_attempts': attempts, 'retry_exhausted': attempts >= MAX_FAILURE_ATTEMPTS}
                if attempts >= MAX_FAILURE_ATTEMPTS: exhausted.add(record['id'])
        self.emit(total=len(rows), completed=len(done), checked=len(valid),
                  matched=sum(v['core_count'] > 0 for v in done), undetermined=len(done)-sum(v['core_count'] > 0 for v in done),
                  awaiting_original=waiting, blocked=blocked,
                  supplementary_only=sum(v['state'] == 'supplementary_only' for v in valid.values()),
                  protected=sum(v['state'] == 'protected' for v in valid.values()),
                  source_mismatch=sum(v['state'] == 'source_mismatch' for v in valid.values()),
                  queued=sum(r['id'] not in exhausted and valid.get(r['id'], {}).get('state') not in
                             ('protected', 'supplementary_only', 'source_mismatch', 'missing_input', 'awaiting_original') for r in pending),
                  failed=sum(v['state'] == 'failed' for v in valid.values()),
                  retry_exhausted=len(exhausted),
                  last_scan_at=datetime.now(timezone.utc).isoformat())
        ready = [r for r in pending if r['id'] not in exhausted and
                 (self.failures.get(r['id'], {}).get('input_attempts') == 0 or
                  time.time() >= valid.get(r['id'], {}).get('retry_at', 0))][:BATCH_SIZE]
        if not ready or not self.allowed(): return False
        records = source_records(self.config['catalog_path'], [r['id'] for r in ready])
        recovery_keys = {r['id']: recovery_input(r, self.generation) for r in records}
        by_id = {r['id']: r for r in ready}
        self.emit(state='running')
        pool = self.executor or ThreadPoolExecutor(max_workers=runtime.PARALLEL)
        try:
            futures = {pool.submit(_process_predict, r, self.generation) if self.executor else
                       pool.submit(self.guarded_record, r): r for r in records}
            for future in as_completed(futures):
                record = futures[future]; row = by_id[record['id']]
                try:
                    value = future.result()
                    if value is None or not self.allowed(): continue
                    if runtime.source_fingerprint() != self.source: continue
                    document, result = value
                    current = source_records(self.config['catalog_path'], [row['id']])
                    if not current: continue
                    current = current[0]
                    # Main identity/protection, raw original AND reused frozen source are
                    # rechecked immediately before writing only the independent L2 head.
                    if (metadata_fingerprint(current) != document['metadata_fingerprint'] or
                        current['asset_hash'] != document['source_fingerprint'] or
                        current['acquisition'] != record['acquisition'] or
                        current['asset_path'] != record['asset_path'] or
                        any(current['metadata'].get(k) != record['metadata'].get(k) for k in
                            ('identity_review_required', 'version_review_required', 'out_of_scope'))): continue
                    provenance = document.get('source_provenance')
                    if provenance:
                        from core.api import paths__WorkspacePath as WorkspacePath
                        if digest(WorkspacePath(current['asset_path'])) != document['source_fingerprint']:
                            self.check(row, 'source_mismatch', 'original_changed_before_publish', retry_at=time.time()+RETRY_SECONDS); continue
                        if digest(WorkspacePath(provenance['path'])) != provenance['sha256']:
                            self.check(row, 'source_mismatch', 'text_changed_before_publish', retry_at=time.time()+RETRY_SECONDS); continue
                    self.store.save_automatic_run(document, result, scope='level2')
                    state = ('completed' if result['level2'] else 'undetermined') if document['chunks'] else blocked_state(document)
                    self.check(row, state, ';'.join(document['limitations']), len(result['level2']),
                               0 if document['chunks'] else time.time()+RETRY_SECONDS)
                    self.failures.pop(row['id'], None)
                    self.emit(last_finished_at=datetime.now(timezone.utc).isoformat(), last_paper_id=row['id'])
                except Exception as exc:
                    old = self.failures.get(row['id'], {}); attempts = old.get('attempts', 0)+1
                    key = recovery_keys[row['id']]
                    input_attempts = (old.get('input_attempts', old.get('attempts', 0))
                                      if old.get('recovery_input') == key else 0)+1
                    retry_at = time.time()+min(3600, 60*2**min(input_attempts-1, 6))
                    self.failures[row['id']] = {'attempts': attempts, 'input_attempts': input_attempts,
                        'recovery_input': key, 'retry_exhausted': input_attempts >= MAX_FAILURE_ATTEMPTS,
                        'retry_at': retry_at, 'error': str(exc)[:300]}
                    self.check(row, 'failed', str(exc), retry_at=retry_at)
                self.emit()
        finally:
            if self.executor is None: pool.shutdown(wait=True, cancel_futures=True)
        return True


if __name__ == '__main__': runtime.main('level2', Worker)
