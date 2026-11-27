"""Optional per-thread checkpoints for long, pure catalog reads.

The ordinary catalog behavior is unchanged without an explicit owner callback.
Writes, explicit transactions and non-SELECT statements never yield here.
"""
from contextlib import contextmanager
import re
import sqlite3
import threading
import time

_LOCAL=threading.local()


def set_checkpoint(callback):
    """Install a callback only on this thread; return the previous callback."""
    if callback is not None and not callable(callback):raise TypeError('数据库读取检查点必须可调用或为None')
    previous=getattr(_LOCAL,'checkpoint',None);_LOCAL.checkpoint=callback
    return previous


@contextmanager
def read_checkpoints(db, *, interval=.05, steps=1000):
    callback=getattr(_LOCAL,'checkpoint',None)
    if callback is None:
        yield;return
    # A paused rollback-journal reader can prevent a yielded writer committing.
    # Catalogs use WAL; other connection modes retain their ordinary execution.
    if str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()!='wal':
        yield;return
    reading=False;last=time.monotonic();failure=[]
    def trace(statement):
        nonlocal reading
        # Conservative: WITH/PRAGMA/DDL and transaction statements do not yield.
        reading=bool(re.match(r'^\s*SELECT\b',statement,re.I))
    def progress():
        nonlocal last
        if not reading or db.in_transaction or time.monotonic()-last<interval:return 0
        last=time.monotonic()
        try:callback()
        except BaseException as exc:
            failure.append(exc);return 1
        return 0
    db.set_trace_callback(trace);db.set_progress_handler(progress,steps)
    try:
        try:yield
        except sqlite3.OperationalError as exc:
            if failure:raise failure[0] from exc
            raise
    finally:
        db.set_progress_handler(None,0);db.set_trace_callback(None)
