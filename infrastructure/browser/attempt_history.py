"""Complete immutable receipt indexing and submission gates, including archives."""
import hashlib
import json
from pathlib import Path as NativePath
import re
from stat import S_ISREG
import threading
import time
from core.api import paths__WorkspacePath as Path

from core.api import control__submission_decision as submission_decision

_CACHE = {}
_CACHE_LOCK=threading.RLock()
_SCAN_LOCAL=threading.local()


def set_scan_checkpoint(callback):
    """Cooperate only on the original owner thread; workers keep pure scans."""
    if callback is not None and not callable(callback):raise TypeError('回执扫描检查点必须可调用或为None')
    previous=getattr(_SCAN_LOCAL,'checkpoint',None)
    _SCAN_LOCAL.checkpoint=callback
    _SCAN_LOCAL.last=time.monotonic()
    return previous


def scan_checkpoint():
    """Yield between read-only scan items, never inside a cache/DB write lock."""
    callback=getattr(_SCAN_LOCAL,'checkpoint',None)
    if callback is not None:
        at=time.monotonic()
        if at-getattr(_SCAN_LOCAL,'last',at)>=.05:
            _SCAN_LOCAL.last=at
            callback()


def read_attempt(path):
    path = Path(path).resolve()
    return _read_attempt(path, path.stat())


def _read_attempt(path, stat):
    key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    with _CACHE_LOCK:cached = _CACHE.get(str(path))
    if cached and cached[0] == key:
        return dict(cached[1])
    raw = path.read_bytes()
    after = path.stat()
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != key:
        raise ValueError('提交账本读取期间变化：' + str(path))
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError('原提交账本不是对象：' + str(path))
    record.update(_ledger_path=str(path), _ledger_sha256=hashlib.sha256(raw).hexdigest())
    with _CACHE_LOCK:_CACHE[str(path)] = (key, record)
    return dict(record)


def attempt_order(record):
    # Immutable original intent precedes update times of older saved receipts.
    for name in ('created', 'updated_at', 'updated'):
        stamp = record.get(name)
        if type(stamp) in (int, float):
            return stamp
    return Path(record['_ledger_path']).stat().st_mtime


def _index_attempts(root):
    records, latest = {}, {}
    root=Path(root).resolve()
    prefix=str(root).rstrip("/")+"/"
    for lane in ('web_cards', 'card_reviews'):
        # Resolve each lane once. rglob does not descend into symlinked
        # directories, so a regular leaf already has a canonical path.
        for path in (NativePath(root) / lane).resolve().rglob('attempt.json'):
            scan_checkpoint()
            stat = path.lstat()
            record = _read_attempt(path, stat) if S_ISREG(stat.st_mode) else read_attempt(path)
            records[record['_ledger_path']] = record
            tid = record.get('target_id')
            if tid and (tid not in latest or attempt_order(record) > attempt_order(latest[tid])):
                latest[tid] = record
    # Removed archives must not keep an ever-growing process cache.
    with _CACHE_LOCK:cached_paths=list(_CACHE)
    for path in cached_paths:
        scan_checkpoint()
        if path.startswith(prefix) and path not in records:
            with _CACHE_LOCK:_CACHE.pop(path,None)
    return records, latest



def index_attempts(root):
    # A local recovery may atomically archive an unsent receipt during scanning.
    # Rescan the entire tree, never silently drop a possibly uncertain request.
    for retry in range(3):
        try:
            return _index_attempts(root)
        except FileNotFoundError:
            if retry == 2:raise


def submission_history(folder, *, exclude_paths=()):
    """Uncertain archives block; explicit bounded completed retries may proceed.

    Do not treat an empty active directory as absence of historical submission.
    This does not grant a retry: the existing retry CAS and input checks do that.
    """
    folder = Path(folder)
    excluded = {Path(path).resolve() for path in exclude_paths}
    records = [read_attempt(path) for path in folder.rglob('attempt.json') if path.resolve() not in excluded]
    retry_path = folder / 'retry.json'
    retry = json.loads(retry_path.read_text()) if retry_path.exists() else {}
    from cards.api import web_card_structure_repair__authorized_archives as authorized_archives
    structure_archives = authorized_archives(folder, retry.get('structure_repair'))
    blocking = []
    for record in records:
        path = Path(record['_ledger_path'])
        if path in structure_archives:
            continue
        archived = 'history' in path.relative_to(folder.resolve()).parts
        from cards.api import web_card_retry__known_unsent as known_unsent
        if known_unsent(record):
            continue
        if archived and record.get('state') == 'response_saved':
            from cards.api import web_card_delivery_repair__authorized_archive as authorized_archive
            if authorized_archive(path,record,retry.get('delivery_repair')):
                continue
            parts = path.relative_to(folder.resolve()).parts
            match = re.fullmatch(r'automatic-retry-(\d+)-\d+', parts[1]) if len(parts) > 2 and parts[0] == 'history' else None
            if (match and retry.get('state') == 'scheduled' and
                    int(match[1]) <= min(2, retry.get('external_retries', 0)) and
                    record.get('inputs') == retry.get('input_hashes')):
                raw, prompt = path.parent / 'response-raw.txt', path.parent / 'prompt-actual.txt'
                url = record.get('conversation_url', '')
                if (raw.is_file() and raw.read_text().strip() and prompt.is_file() and
                        hashlib.sha256(raw.read_bytes()).hexdigest() == record.get('raw_sha256') and
                        hashlib.sha256(prompt.read_bytes()).hexdigest() == record.get('actual_prompt_sha256') and
                        url.startswith('https://chatgpt.com/c/') and 'local-chatgpt' not in url):
                    continue
        blocking.append(record)
    return submission_decision(blocking)
