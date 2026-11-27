"""Legacy HTTP-side cleanup delegates to the sole owner; never edits receipts."""
from core.api import catalog__load_config as load_config


def release_expired_claims(catalog,config,*,limit=50,timeout=1800):
    """Age alone cannot release a claim, even when its source looks terminal."""
    return []


def tick(config,*,apply=True):
    if apply:
        from .auto_recover_work import tick as request_owner
        request_owner(config)
    return []


if __name__=='__main__':
    import argparse,json
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    print(json.dumps(tick(load_config('infrastructure/config/first_round.json'),apply=args.apply)))
