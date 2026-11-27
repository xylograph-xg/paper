"""Compatibility CLI: request owner reconciliation; never reset protection."""
import argparse,json
from core.api import catalog__load_config as load_config
from .abnormal_protection_cleanup import tick


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    parser.add_argument('--minutes',type=float,default=60);args=parser.parse_args()
    tick(load_config('infrastructure/config/first_round.json'),apply=args.apply)
    print(json.dumps({'state':'owner_requested' if args.apply else 'inspection_only',
        'requested_minutes':args.minutes,'actual_policy':'original owner evidence and configured one-hour threshold',
        'original_receipts_unchanged':True}))


if __name__=='__main__':main()
