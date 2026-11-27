"""Bounded backoff for proven unsent review upload failures.

A receipt qualifies only when it ended before any send click and failed inside
the native upload stage. Each receipt counts once, keyed by lane, job and frozen
material identity, so a rescan or an owner restart cannot add a failure or move
the stored timer. Scientific retry counts, arrivals, page bindings, original
cards and receipts stay untouched; cooling material keeps its real slot and FIFO
position and simply waits.
"""
from functools import lru_cache
import hashlib
import json
import math
import time
from core.api import paths__WorkspacePath as Path

LANE = 'review'
DEFAULT_BACKOFF = (300, 900, 3600)
# The kernel now labels the two halves of the attachment segment separately.
# `attach` remains a valid stored label: receipts written before the split keep
# their evidence and still cool, but no new receipt is produced under it.
UPLOAD_STAGES = ('entry', 'attach', 'attach_write', 'attach_visible', 'settle')
MAX_WINDOW_SECONDS = 86400


class PolicyIntegrityError(ValueError):
    """Stored policy evidence cannot be trusted; new claims must stop."""


def enabled(config):
    return _settings(config if isinstance(config, dict) else {})['enabled']


def _settings(config):
    block = (config.get('card_review') or {}).get('upload_retry')
    if not isinstance(block, dict) or block.get('enabled') is not True:
        return {'enabled': False, 'schedule': DEFAULT_BACKOFF}
    raw = block.get('backoff_seconds', DEFAULT_BACKOFF)
    if (not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= 12 or
            any(type(value) not in (int, float) or isinstance(value, bool) or
                not math.isfinite(value) or not 1 <= value <= MAX_WINDOW_SECONDS for value in raw)):
        raise PolicyIntegrityError('核验上传退避时间窗待核对')
    return {'enabled': True, 'schedule': tuple(float(value) for value in raw)}


def _ddl(db):
    db.execute('''CREATE TABLE IF NOT EXISTS upload_retry_policy(
        lane TEXT NOT NULL, job_id TEXT NOT NULL, inputs_digest TEXT NOT NULL,
        zip_sha256 TEXT NOT NULL, consecutive INTEGER NOT NULL DEFAULT 0,
        total INTEGER NOT NULL DEFAULT 0, last_failure REAL NOT NULL DEFAULT 0,
        next_eligible REAL NOT NULL DEFAULT 0, updated REAL NOT NULL,
        PRIMARY KEY(lane,job_id,inputs_digest,zip_sha256))''')
    db.execute('''CREATE TABLE IF NOT EXISTS upload_retry_receipts(
        failure_receipt_id TEXT PRIMARY KEY, lane TEXT NOT NULL, job_id TEXT NOT NULL,
        inputs_digest TEXT NOT NULL, zip_sha256 TEXT NOT NULL, stage TEXT NOT NULL,
        ended REAL NOT NULL, recorded_at REAL NOT NULL, reason TEXT NOT NULL)''')


def install(catalog):
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _ddl(db)


def _present(db):
    return {'upload_retry_policy', 'upload_retry_receipts'} <= {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def material_identity(material):
    """Return (inputs_digest, zip_sha256) for one exact frozen upload packet."""
    if not isinstance(material, dict):
        return None
    inputs = material.get('input_hashes') if 'input_hashes' in material else material.get('inputs')
    bundle = material.get('upload_bundle')
    if (not isinstance(inputs, dict) or not inputs or not isinstance(bundle, dict) or
            any(not isinstance(name, str) or not isinstance(value, str) or not value
                for name, value in inputs.items())):
        return None
    zip_sha = bundle.get('zip_sha256')
    if not isinstance(zip_sha, str) or len(zip_sha) != 64:
        return None
    canonical = json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest(), zip_sha


def upload_failure(attempt):
    """Only an ended, never-clicked native upload technical failure qualifies."""
    if (not isinstance(attempt, dict) or attempt.get('state') != 'not_sent' or
            attempt.get('send_click_started') is not False or
            type(attempt.get('finished')) not in (int, float) or
            isinstance(attempt.get('finished'), bool) or not math.isfinite(attempt['finished'])):
        return ''
    stage = attempt.get('upload_failure_stage')
    return stage if isinstance(stage, str) and stage in UPLOAD_STAGES else ''


def _receipt_id(job_id, inputs_digest, zip_sha256, attempt):
    seed = json.dumps([LANE, job_id, inputs_digest, zip_sha256, attempt.get('created'),
                       attempt.get('finished'), attempt.get('upload_failure_stage')], sort_keys=True)
    return hashlib.sha256(seed.encode()).hexdigest()


def window(consecutive, schedule=DEFAULT_BACKOFF):
    """Fifth minute, then fifteenth, then a low frequency hour for later failures."""
    if type(consecutive) is not int or consecutive < 1:
        raise PolicyIntegrityError('核验上传退避次数待核对')
    return float(schedule[min(consecutive, len(schedule)) - 1])


def _validated(row):
    """A malformed stored row grants no cooldown and never reads as zero failures.

    A cleared streak legitimately keeps its last failure time beside a zero wait,
    so only impossible counts and non-finite times count as corruption.
    """
    try:
        consecutive = int(row['consecutive']); total = int(row['total'])
        last = float(row['last_failure']); next_eligible = float(row['next_eligible'])
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise PolicyIntegrityError('核验上传退避记录待核对') from exc
    if (consecutive < 0 or total < 0 or consecutive > total or
            not math.isfinite(last) or not math.isfinite(next_eligible) or
            last < 0 or next_eligible < 0):
        raise PolicyIntegrityError('核验上传退避记录待核对')
    return consecutive, total, last, next_eligible


def _stored(db, job_id, inputs_digest, zip_sha256):
    return db.execute('SELECT * FROM upload_retry_policy WHERE lane=? AND job_id=? '
                      'AND inputs_digest=? AND zip_sha256=?',
                      (LANE, job_id, inputs_digest, zip_sha256)).fetchone()


def record_failure(catalog, *, config, job_id, attempt, reason='', at=None):
    """Count one proven upload receipt once and store its next eligible instant."""
    if not enabled(config):
        return None
    stage = upload_failure(attempt)
    if not stage:
        return None
    identity = material_identity(attempt)
    if identity is None:
        return None
    inputs_digest, zip_sha256 = identity
    ended = float(attempt['finished'])
    receipt = _receipt_id(job_id, inputs_digest, zip_sha256, attempt)
    stamp = time.time() if at is None else at
    schedule = _settings(config)['schedule']
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _ddl(db)
        inserted = db.execute('INSERT OR IGNORE INTO upload_retry_receipts('
            'failure_receipt_id,lane,job_id,inputs_digest,zip_sha256,stage,ended,recorded_at,reason) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            (receipt, LANE, job_id, inputs_digest, zip_sha256, stage, ended, stamp, str(reason)[:700]))
        previous = _stored(db, job_id, inputs_digest, zip_sha256)
        prior_consecutive, prior_total, prior_last = (0, 0, 0.0)
        if previous is not None:
            prior_consecutive, prior_total, prior_last, _ = _validated(previous)
        if not inserted.rowcount:
            if previous is None:
                raise PolicyIntegrityError('核验上传退避回执没有对应策略记录')
            return {'deduplicated': True, 'failure_receipt_id': receipt, 'consecutive': prior_consecutive,
                    'total': prior_total, 'last_failure': prior_last,
                    'next_eligible': float(previous['next_eligible'])}
        ended = max(ended, prior_last) if prior_last else ended
        consecutive = prior_consecutive + 1
        due = ended + window(consecutive, schedule)
        db.execute('INSERT INTO upload_retry_policy(lane,job_id,inputs_digest,zip_sha256,'
            'consecutive,total,last_failure,next_eligible,updated) VALUES(?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(lane,job_id,inputs_digest,zip_sha256) DO UPDATE SET '
            'consecutive=excluded.consecutive,total=excluded.total,last_failure=excluded.last_failure,'
            'next_eligible=excluded.next_eligible,updated=excluded.updated',
            (LANE, job_id, inputs_digest, zip_sha256, consecutive, prior_total + 1, ended, due, stamp))
    return {'deduplicated': False, 'failure_receipt_id': receipt, 'consecutive': consecutive,
            'total': prior_total + 1, 'last_failure': ended, 'next_eligible': due}


def settle_success(catalog, *, config, job_id, attempt, at=None):
    """A sent receipt clears only the consecutive streak; totals and evidence stay."""
    if not enabled(config):
        return False
    identity = material_identity(attempt)
    if identity is None:
        return False
    inputs_digest, zip_sha256 = identity
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not _present(db):
            return False
        row = _stored(db, job_id, inputs_digest, zip_sha256)
        if row is None:
            return False
        consecutive, _, _, next_eligible = _validated(row)
        if not consecutive and not next_eligible:
            return False
        db.execute('UPDATE upload_retry_policy SET consecutive=0,next_eligible=0,updated=? '
                   'WHERE lane=? AND job_id=? AND inputs_digest=? AND zip_sha256=?',
                   (time.time() if at is None else at, LANE, job_id, inputs_digest, zip_sha256))
    return True


@lru_cache(maxsize=2048)
def _packet_identity(folder, version):
    """Reuse one proven packet version, never a partially rewritten packet."""
    path = Path(folder) / 'packet.json'
    packet = json.loads(path.read_text())
    stat = path.stat()
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != version:
        raise PolicyIntegrityError('核验冻结材料在清单读取期间变化')
    return material_identity(packet)


def _identity_for(folder):
    path = Path(folder) / 'packet.json'
    stat = path.stat()
    version = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return _packet_identity(str(folder), version)


def cooling(db, job_id, folder=None, *, config=None, identity=None, at=None):
    """Stored cooling instant for this exact material; None when nothing cools.

    An unreadable packet cannot disprove a recorded failure, so it reports an
    open-ended wait instead of silently counting zero failures.
    """
    if not enabled(config if isinstance(config, dict) else {}) or not _present(db):
        return None
    rows = db.execute('SELECT * FROM upload_retry_policy WHERE lane=? AND job_id=?', (LANE, job_id)).fetchall()
    if not rows:
        return None
    if identity is None:
        if folder is None:
            raise PolicyIntegrityError('核验上传退避查询缺少材料指纹')
        try:
            identity = _identity_for(folder)
        except (OSError, ValueError, TypeError, PolicyIntegrityError):
            identity = None
    if identity is None:
        return float('inf')
    for row in rows:
        _, _, _, next_eligible = _validated(row)
        if row['inputs_digest'] == identity[0] and row['zip_sha256'] == identity[1]:
            return next_eligible if next_eligible > (time.time() if at is None else at) else None
    return None


def annotate(db, records, config=None, *, at=None):
    """Attach due evidence to queue records; unknown material never cools silently."""
    records = list(records)
    if not enabled(config if isinstance(config, dict) else {}) or not _present(db):
        for record in records:
            record['upload_due'] = True
            record.pop('upload_cooldown_until', None)
            record.pop('upload_policy_error', None)
        return records
    now = time.time() if at is None else at
    for record in records:
        record['upload_due'] = True
        record.pop('upload_cooldown_until', None)
        record.pop('upload_policy_error', None)
        if record.get('lane') != LANE:
            continue
        folder = record.get('folder') or (record.get('source_job') or {}).get('folder')
        try:
            wait = cooling(db, record.get('job_id'), folder, config=config, at=now)
        except PolicyIntegrityError:
            # Scheduling keeps the material and refuses new claims; the claim
            # guard re-raises so a damaged row is never read as zero failures.
            record['upload_due'] = False
            record['upload_policy_error'] = '核验上传退避记录待核对'
            continue
        if wait is None:
            continue
        record['upload_due'] = False
        if math.isfinite(wait):
            record['upload_cooldown_until'] = wait
        else:
            record['upload_policy_error'] = '核验冻结材料清单待核对'
    return records


def due(record):
    """A missing label means no policy evidence, never an invented cooldown."""
    return record.get('upload_due', True) is True


def first_eligible(db, rows, config=None, *, at=None, diagnostics=None):
    """First row in the caller's own order whose exact material is not waiting.

    Only jobs that already have policy evidence read a packet, so an ordinary
    queue costs one indexed lookup and the immutable arrival order is unchanged.
    """
    rows = list(rows)
    if not rows:
        return None
    if not enabled(config if isinstance(config, dict) else {}) or not _present(db):
        return rows[0]
    tracked = {row[0] for row in db.execute(
        'SELECT DISTINCT job_id FROM upload_retry_policy WHERE lane=?', (LANE,))}
    for row in rows:
        if row['id'] not in tracked:
            return row
        try:
            waiting = cooling(db, row['id'], row['folder'], config=config, at=at)
        except PolicyIntegrityError as exc:
            # Corruption refuses this material, not every healthy job behind it.
            # Keep the row and FIFO intact; the caller persists the diagnostic.
            if diagnostics is not None:
                diagnostics.append({'job_id': row['id'], 'reason': str(exc)[:200]})
            continue
        if waiting is None:
            return row
    return None


def guard(db, config, job_id, folder=None, *, identity=None, at=None):
    """Refuse a claim or a send that would run inside a recorded cooldown."""
    wait = cooling(db, job_id, folder, config=config, identity=identity, at=at)
    if wait is None:
        return False
    if not math.isfinite(wait):
        raise PolicyIntegrityError('核验上传冷却材料清单待核对；停止新领取')
    remaining = max(0, round(wait - (time.time() if at is None else at)))
    raise ValueError('核验上传冷却中，剩余 %d 秒；保留原页与原入队顺序' % remaining)


def summary(db, config, *, at=None):
    """Read-only counts of tracked failures and how many still wait."""
    if not enabled(config if isinstance(config, dict) else {}) or not _present(db):
        return {'enabled': False, 'tracked_jobs': 0, 'cooling_jobs': 0, 'total_failures': 0}
    now = time.time() if at is None else at
    rows = db.execute('SELECT job_id,consecutive,total,last_failure,next_eligible '
                      'FROM upload_retry_policy WHERE lane=?', (LANE,)).fetchall()
    jobs = {}
    for row in rows:
        _, _, _, next_eligible = _validated(row)
        entry = jobs.setdefault(row['job_id'], {'total': 0, 'cooling': False})
        entry['total'] += int(row['total'])
        entry['cooling'] |= next_eligible > now
    return {'enabled': True, 'tracked_jobs': len(jobs),
            'cooling_jobs': sum(1 for entry in jobs.values() if entry['cooling']),
            'total_failures': sum(entry['total'] for entry in jobs.values())}
