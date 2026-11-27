"""Local JSON interface; no worker, browser or model entry points."""
import argparse
import json
import sys
from .api import Library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--store')
    parser.add_argument('operation', choices=['query','detail','tags','save_tag','annotate','collections','save_collection','members','save_member','import_oled_vocabulary','auto_label'])
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
        result = Library(args.catalog, args.store).dispatch(args.operation, data)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error':str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__': raise SystemExit(main())
