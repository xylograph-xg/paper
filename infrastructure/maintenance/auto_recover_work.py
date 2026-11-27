"""Compatibility entry: TTL is never evidence of an ended model request.

All page/receipt/claim recovery belongs to the original browser owner. This
HTTP-side entry may only queue its registered maintenance request.
"""
import json,time
from datetime import datetime
from core.api import paths__WorkspacePath as Path
from core.api import catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json


def _age(value):
    if isinstance(value,(int,float)):return max(0,time.time()-value)
    try:return max(0,time.time()-datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp())
    except (ValueError,TypeError):return 0


def requeue_cards(catalog,config,limit=20):
    """Retired unsafe timeout writer; no permission to requeue uncertain work."""
    return []


def rerun_submitted_reviews(catalog,config,limit=5):
    """A submitted request is never retried because of elapsed time."""
    return []


def rerun_changed_corrections(catalog,config,limit=5):
    """Original report/version/receipt checks remain with the owner."""
    return []


def tick(config):
    from browser.api import (web_pool_open__shared_window_record as shared_window_record,
                             web_pool_open__shared_maintenance_request as request)
    result={'cards':[],'reviews':[],'corrections':[],'state':'owner_requested',
            'at':time.time(),'original_requests_unchanged':True}
    try:
        record,fingerprint=shared_window_record(config)
        request(config,'legacy_technical_recovery_delegate',record,fingerprint)
    except (OSError,ValueError,TypeError) as exc:
        result.update(state='needs_inspection',error=str(exc)[:500])
    atomic_json(Path(config['catalog_path']).parent/'auto-recover-work-status.json',result)
    return result


if __name__=='__main__':
    print(json.dumps(tick(load_config('infrastructure/config/first_round.json')),ensure_ascii=False,indent=2))
