"""Project observed parallel work, keeping reservation and menu limits separate."""
import time

LANES=('cards','review','correction')


def observed(observer,*,at=None):
    at=time.time() if at is None else at
    checked=observer.get('updated',0)
    if observer.get('activity_schema_version')!=1 or not isinstance(checked,(int,float)) or not 0<=at-checked<30:
        return None,None
    if observer.get('page_count')==0:
        return None,None
    counts={lane:0 for lane in LANES};seen=set()
    for page in observer.get('pages',[]):
        tid=page.get('target_id');stamp=page.get('checked_at',0)
        if not tid or tid in seen:continue
        seen.add(tid)
        if (page.get('activity_verified') is True and page.get('streaming') is True and
                page.get('kind') in counts and isinstance(stamp,(int,float)) and 0<=at-stamp<30):
            counts[page['kind']]+=1
    return counts,checked


def project(service,*,owner_live,observer=None,at=None):
    """None means no fresh measurement; explicit measured zero stays zero.

    A paused lane may still have original pages generating. Old workers or page
    budgets are never substituted for observed activity. No I/O or side effects.
    """
    at=time.time() if at is None else at
    if not owner_live or service.get('state') in ('stopped','stopping'):
        return {'actual_parallel':None,'actual_parallel_checked_at':None,'actual_parallel_confirmed':False}
    counts,stamp=observed(observer or {},at=at)
    live_observation=counts is not None and (observer or {}).get('owner_pid')==service.get('pid')
    if not live_observation:
        counts=None
    if counts is None:
        counts=service.get('actual_parallel');stamp=service.get('actual_parallel_checked_at',0)
    valid=(isinstance(counts,dict) and all(type(counts.get(lane)) is int and 0<=counts[lane]<=20 for lane in LANES)
           and isinstance(stamp,(int,float)) and 0<=at-stamp<30
           and (live_observation or isinstance(service.get('updated'),(int,float)) and 0<=at-service['updated']<30))
    return {'actual_parallel':counts if valid else None,'actual_parallel_checked_at':stamp if valid else None,
            'actual_parallel_confirmed':bool(valid)}
