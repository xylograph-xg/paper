"""Group diagnostic histories once, preserving receipt order and lexical paths."""
from core.api import paths__WorkspacePath as Path


def group_histories(items, records, root):
    originals = {}
    for item in items:
        originals.setdefault(item['id'], item)
    sources = {key: Path(item.get('source') or root)
               for key, item in originals.items() if not key.startswith('page:')}
    by_source = {source: [] for source in sources.values()}
    by_target = {}
    for record in records.values():
        by_target.setdefault(record.get('target_id'), []).append(record)
        ledger = Path(record['_ledger_path'])
        for ancestor in (ledger, *ledger.parents):
            if ancestor in by_source:
                by_source[ancestor].append(record)
    return {key: (by_target.get(key.removeprefix('page:'), [])
                  if key.startswith('page:') else
                  by_source[sources[key]] if sources[key].is_dir() else [])
            for key in originals}
