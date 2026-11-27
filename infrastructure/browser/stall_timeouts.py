"""Lane-specific fault deadlines calibrated from frozen recovery evidence."""
def timeout_seconds(policy,entry,record=None):
    lane=entry.get('kind')
    if lane not in ('cards','review','correction'):
        lane='review' if (record or {}).get('review_id') else 'cards'
    limits=policy.get('stalled_after_seconds_by_lane',{})
    value=limits.get(lane,policy.get('stalled_unsent_after_seconds'))
    ceiling = policy.get('hard_restart_after_seconds')
    if type(ceiling) in (int, float) and ceiling > 0:
        value = min(value, ceiling) if type(value) in (int, float) and value > 0 else ceiling
    return value if type(value) in (int,float) and value>0 else None
