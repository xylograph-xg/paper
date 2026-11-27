"""Locked, optimistic entry updates for the shared page pool.

Load a snapshot before editing. Save merges untouched targets from the latest
file and rejects concurrent edits to the same target, before any navigation.
This local file lock never acquires the browser submission lock or changes DOM.
"""
import copy
import fcntl
import json
import time
from contextlib import contextmanager
from core.api import paths__WorkspacePath as Path

from core.api import services__atomic_json as atomic_json


class PoolConflict(RuntimeError):
    pass


class PoolSnapshot(dict):
    def __init__(self, value):
        super().__init__(value)
        self.baseline = copy.deepcopy(value)


def load_pool(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not isinstance(value.get('windows'), dict):
        raise ValueError('共享页池损坏，保留原文件')
    return PoolSnapshot(value)


def mark_verified_blank(entry):
    """Keep old saved evidence without treating it as the current conversation."""
    previous = {k: entry.pop(k) for k in ('raw_path', 'raw_sha256', 'conversation_url', 'paper_id', 'active_paper_id', 'kind', 'review_id', 'correction_id', 'original_receipt_recovery') if k in entry}
    if previous:
        entry['previous_saved_response'] = {**entry.get('previous_saved_response', {}), **previous}
    entry.pop('error', None)
    entry['state'] = 'ready_blank'


def begin_request(entry, kind, paper_id, *, review_id=None, correction_id=None):
    """After live reuse checks, separate saved evidence from the new request."""
    previous = {k: entry.pop(k) for k in ('raw_path', 'raw_sha256', 'conversation_url',
                'paper_id', 'active_paper_id', 'kind', 'review_id', 'correction_id', 'original_receipt_recovery') if k in entry}
    if previous:
        entry['previous_saved_response'] = {**entry.get('previous_saved_response', {}), **previous}
    for name in ('blank_history_verified_at', 'blank_history_ledger_hashes', 'never_submitted', 'error'):
        entry.pop(name, None)
    entry.update(state='busy', kind=kind, active_paper_id=paper_id)
    if review_id is not None:
        entry['review_id'] = review_id
    if correction_id is not None:
        entry['correction_id'] = correction_id


def failed_request(entry, original, *, page_touched, error):
    """Restore untouched ownership; a used page needs fresh DOM evidence."""
    if not page_touched:
        entry.clear()
        entry.update(original)
        from .shared_browser_window import WindowIsolationError
        if isinstance(error,WindowIsolationError):
            # The live preflight invalidated eligibility, even though it did
            # not mutate the page. Keep original ownership and saved evidence.
            entry.update(state='needs_inspection',error=str(error)[:700],
                         eligibility_invalidated_at=time.time())
    else:
        entry.update(state='needs_inspection', error=str(error)[:700])


@contextmanager
def _lock(path, timeout=5):
    with path.with_suffix(path.suffix + '.lock').open('a') as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('共享页池写锁忙，等待下一轮')
                time.sleep(.02)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def save_pool(path, pool):
    if not isinstance(pool, PoolSnapshot):
        raise TypeError('页池写入必须使用原读取快照')
    path = Path(path)
    absent = object()
    with _lock(path):
        current = load_pool(path) if path.exists() else PoolSnapshot(pool.baseline)
        merged = copy.deepcopy(dict(current))
        for field in set(pool.baseline) | set(pool):
            if field == 'windows':
                before, desired, live = pool.baseline['windows'], pool['windows'], current['windows']
                for tid in set(before) | set(desired):
                    old, new = before.get(tid, absent), desired.get(tid, absent)
                    if old == new:
                        continue
                    if live.get(tid, absent) != old and live.get(tid, absent) != new:
                        raise PoolConflict('原页面归属已并发变化，停止写入：' + tid)
                    if new is absent:
                        merged['windows'].pop(tid, None)
                    else:
                        merged['windows'][tid] = copy.deepcopy(new)
            elif pool.baseline.get(field, absent) != pool.get(field, absent):
                # Inventory metadata is the single owner's latest observation.
                if field in pool:
                    merged[field] = copy.deepcopy(pool[field])
                else:
                    merged.pop(field, None)
        atomic_json(path, merged)
        # Preserve references held by repair/review lanes and the owner loop.
        entries = pool['windows']
        for tid in set(entries) - set(merged['windows']):
            entries.pop(tid)
        for tid, entry in merged['windows'].items():
            if tid in entries:
                entries[tid].clear()
                entries[tid].update(entry)
            else:
                entries[tid] = entry
        pool.clear()
        pool.update({**merged, 'windows': entries})
        pool.baseline = copy.deepcopy(dict(pool))
    return pool


def acknowledge_submitted(path, pool, target_id, receipt):
    """Merge only the same request ACK; a collected response is never downgraded."""
    if receipt.get('target_id') != target_id or receipt.get('state') not in ('submitted', 'response_saved'):
        raise PoolConflict('提交确认缺少原target或正式回执')
    expected={'kind':receipt.get('kind'),'active_paper_id':receipt.get('paper_id'),
              'review_id':receipt.get('review_id'),'correction_id':receipt.get('correction_id')}
    if expected['kind'] not in ('cards','review','correction') or not expected['active_paper_id']:
        raise PoolConflict('提交确认缺少不可变的原任务身份')
    with _lock(Path(path)):
        live = load_pool(path)
        entry = live['windows'].get(target_id, {})
        fields = ('kind', 'active_paper_id', 'review_id', 'correction_id')
        if any(entry.get(k) != expected.get(k) for k in fields):
            raise PoolConflict('提交确认页面已属于其他请求，保留原回执')
        url = receipt.get('conversation_url')
        if not url or entry.get('conversation_url') not in (None, '', url):
            raise PoolConflict('提交确认原会话发生变化')
        if entry.get('state') == 'ready' and entry.get('raw_sha256'):
            import hashlib
            raw = Path(entry['raw_path'])
            if (receipt.get('state') != 'response_saved' or receipt.get('raw_sha256') != entry['raw_sha256']
                    or hashlib.sha256(raw.read_bytes()).hexdigest() != entry['raw_sha256']):
                raise PoolConflict('提交确认遇到不同完整回答')
        elif entry.get('state') in ('busy', 'submitting', 'submitted'):
            entry['conversation_url'] = url
        else:
            raise PoolConflict('提交确认页面状态需重新核对')
        atomic_json(Path(path), dict(live))
        pool['windows'][target_id].clear();pool['windows'][target_id].update(copy.deepcopy(entry))
        pool.baseline['windows'][target_id] = copy.deepcopy(entry)
    return entry
