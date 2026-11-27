"""One deadline for all URLs, fallback lookup, validation and catalog writes."""
import os
import time


def remaining(reserve=0):
    deadline=float(os.environ.get('PAPER_ACQUISITION_DEADLINE','0'))
    if not deadline:return 120
    seconds=deadline-time.monotonic()-reserve
    if seconds<=0:raise TimeoutError('全文获取总预算已耗尽；保留重试状态')
    return seconds
