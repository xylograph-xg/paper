"""Append-only, desensitized upload attempt evidence for one resident owner.

The uploader records the attempt that owns a page before it writes anything to
that page. The observer binds each network request to the attempt that was
active when the request started, so a late response or a reused page never gets
attributed to that target's newest task. Nothing here sends, navigates or closes
a page, and signed URLs, headers and bodies are never stored.
"""
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict

from core.api import paths__WorkspacePath as Path

EVENTS_FILE = 'upload-attempt-events.jsonl'
NETWORK_FILE = 'web-upload-network.json'
NETWORK_PROJECTION_LIMIT = 100
MAX_BINDINGS = 4000
RESULTS = ('ok', 'failed', 'unknown', 'deferred')
SIGNED_URL = re.compile(r'(https?://[^/\s?#]+)[^\s]*')
QUERY_PAIR = re.compile(r'[?&][A-Za-z0-9_.%+-]+=[^\s&]+')


def desensitize(text, limit=300):
    """Keep the shape of a failure message without its signed path, query,
    headers or body; those are never evidence for upload attribution."""
    if text is None:
        return None
    value = QUERY_PAIR.sub('?<redacted>', SIGNED_URL.sub(r'\1/<redacted>', str(text)))
    return value[:limit] or None

def _scrub(value):
    """Desensitize every string leaf of a kernel detail subtree.

    The external kernel copies raw Playwright exceptions into `settle.error`
    and stage entries, so a signed URL can arrive through those trees as well;
    vocabulary keys are ours, only the leaf values need stripping."""
    if isinstance(value, str):
        return desensitize(value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


_LOCK = threading.RLock()
_ROOT = None
_ACTIVE = {}
_ATTEMPTS = {}
_BINDINGS = OrderedDict()
_NETWORK_EVENTS = []
_SUMMARY = {}


def configure(root):
    """Point the evidence writer at the owner data directory."""
    global _ROOT
    with _LOCK:
        _ROOT = Path(root)
    return _ROOT


def root():
    """Registered evidence directory, or None until the owner registers one.

    There is deliberately no fallback path: an upload may only start once its
    intent has a durable home, and a silent default would write production
    evidence from a test or a stray entry point.
    """
    with _LOCK:
        return _ROOT


def reset():
    """Drop process state; the durable JSONL and its attempt IDs survive."""
    global _ROOT
    with _LOCK:
        _ROOT = None
        _ACTIVE.clear(); _ATTEMPTS.clear(); _BINDINGS.clear()
        _NETWORK_EVENTS.clear(); _SUMMARY.clear()


def owner_identity():
    return {'owner_pid': os.getpid()}


def identity_fields(record):
    return {key: record.get(key) for key in
            ('upload_attempt_id', 'lane', 'job_id', 'paper_id', 'target_id',
             'zip_sha256', 'zip_bytes', 'zip_name', 'sdk_version', 'external_sha256')}


def append(event):
    """Persist one desensitized record; a failed write must stop the upload."""
    folder = root()
    if folder is None:
        raise RuntimeError('上传诊断目录未登记，不启动上传')
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / EVENTS_FILE).open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    with _LOCK:
        if event.get('kind') == 'network':
            _NETWORK_EVENTS.append(event)
            del _NETWORK_EVENTS[:-NETWORK_PROJECTION_LIMIT]
        key = event.get('kind') or event.get('event')
        _SUMMARY[key] = _SUMMARY.get(key, 0) + 1
    return event


def begin(*, lane=None, job_id=None, paper_id=None, target_id=None, zip_path=None,
          zip_sha256=None, zip_bytes=None, sdk_version=None, external_sha256=None,
          timeout_ms=None):
    """Record the upload intent. The caller must not write to the page unless
    this returns, and an unknown or failed write leaves nothing started."""
    attempt_id = uuid.uuid4().hex
    started = time.time()
    record = {'upload_attempt_id': attempt_id, 'lane': lane, 'job_id': job_id,
              'paper_id': paper_id, 'target_id': target_id,
              'zip_name': (Path(zip_path).name if zip_path else None),
              'zip_sha256': zip_sha256, 'zip_bytes': zip_bytes,
              'sdk_version': sdk_version, 'external_sha256': external_sha256,
              'timeout_ms': timeout_ms, 'started_at': started, 'state': 'in_progress'}
    record.update(owner_identity())
    with _LOCK:
        append(dict(record, event='upload_started', kind='upload_started'))
        _ATTEMPTS[attempt_id] = record
        if target_id:
            _ACTIVE[target_id] = attempt_id
    return record


def finish(attempt_id, *, result, failure_kind=None, retryable_upload=None, stage=None,
           exception_type=None, exception_message=None, receipt_sufficient=None,
           bundle=None, stages=None, settle=None, attachment=None):
    """Write the closing receipt. An unknown result is never recorded as done."""
    if result not in RESULTS:
        raise ValueError('上传结束结果不在合同内：' + str(result))
    with _LOCK:
        record = _ATTEMPTS.get(attempt_id) or {}
        ended = time.time()
        payload = identity_fields(record)
        payload.update({'result': result, 'failure_kind': failure_kind,
                        'retryable_upload': bool(retryable_upload), 'stage': stage,
                        'exception_type': exception_type,
                        'exception_message': desensitize(exception_message),
                        'receipt_sufficient': receipt_sufficient,
                        'zip_identity_mismatch': False,
                        'started_at': record.get('started_at'), 'finished_at': ended,
                        'duration_seconds': round(ended - record.get('started_at', ended), 3),
                        'state': 'finished' if result in ('ok', 'failed') else result})
        if bundle is not None:
            identity = bundle.get('identity') or {}
            incoming = bundle.get('zip_sha256')
            intended = record.get('zip_sha256')
            if incoming and intended and incoming != intended:
                # The package that reached the page is not the one the intent
                # recorded; keep both so a pair is never read as one material.
                payload['zip_identity_mismatch'] = True
                payload['intent_zip_sha256'] = intended
            for key, value in (('zip_name', bundle.get('zip_name')),
                               ('zip_sha256', incoming), ('zip_bytes', bundle.get('zip_bytes'))):
                if value is not None:
                    payload[key] = value
            payload['sdk_version'] = identity.get('sdk_version', payload.get('sdk_version'))
            payload['external_sha256'] = identity.get('source_sha256', payload.get('external_sha256'))
        payload.update(owner_identity())
        append(dict(payload, event='upload_finished', kind='upload_finished',
                    stages=_scrub(list(stages or [])), settle=_scrub(dict(settle or {})),
                    attachment=_scrub(dict(attachment or {}))))
        target = record.get('target_id')
        if target and _ACTIVE.get(target) == attempt_id:
            _ACTIVE.pop(target, None)
        record.update(state=payload['state'], result=result, finished_at=ended)
        _ATTEMPTS[attempt_id] = record
    return payload


def active(target_id):
    with _LOCK:
        return _ACTIVE.get(target_id)


def attempt(attempt_id):
    with _LOCK:
        record = _ATTEMPTS.get(attempt_id)
        return dict(record) if record else None


def bind_request(request_key, attempt_id):
    """Remember the attempt that owned the page when this request started."""
    if not request_key:
        return None
    with _LOCK:
        _BINDINGS[request_key] = attempt_id
        _BINDINGS.move_to_end(request_key)
        while len(_BINDINGS) > MAX_BINDINGS:
            _BINDINGS.popitem(last=False)
    return attempt_id


def lookup_request(request_key):
    with _LOCK:
        return _BINDINGS.get(request_key)


def record_network(event):
    """Store one desensitized network observation bound to its original attempt."""
    payload = dict(event)
    payload.setdefault('upload_attempt_id', None)
    payload.update(owner_identity())
    append(dict(payload, event='network', kind='network'))
    return payload


def network_projection(at, targets=None):
    """Compatibility projection for the legacy web-upload-network.json reader."""
    with _LOCK:
        events = [dict(event) for event in _NETWORK_EVENTS]
        summary = dict(_SUMMARY)
        states = {attempt_id: record.get('state') for attempt_id, record in _ATTEMPTS.items()}
        active_targets = set(_ACTIVE) if targets is None else set(targets)
    return {'owner_pid': os.getpid(), 'updated': at, 'schema_version': 2,
            'events_jsonl': str(root() / EVENTS_FILE) if root() else None,
            'errors': events, 'network_event_count': len(events),
            'upload_attempt_states': states,
            'active_upload_targets': sorted(active_targets),
            'counters': summary}
