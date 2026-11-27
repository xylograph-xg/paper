"""Metadata parser interface; isolates the tool's top-level module names."""
import sys
from importlib.util import find_spec
from pathlib import Path

def load_metadata_parsers():
    original=list(sys.path);prefixes=('connectors','models','config','storage','screening','discovery','ranking')
    previous={name:module for name,module in list(sys.modules.items()) if name.split('.')[0] in prefixes}
    for name in previous:sys.modules.pop(name,None)
    before=set(sys.modules)
    try:
        source = Path(__file__).resolve().parents[3] / 'tools/literature_explorer/literature_explorer'
        if not (source / 'config.py').is_file():
            package = find_spec('literature_explorer')
            if not package or not package.submodule_search_locations:
                raise ImportError('Missing paper-literature-explorer')
            source = Path(next(iter(package.submodule_search_locations)))
        sys.path.insert(0, str(source))
        from connectors.openalex import parse_work
        from connectors.semantic_scholar import parse_paper
        return parse_work,parse_paper
    finally:
        sys.path[:]=original
        for name in set(sys.modules)-before:
            if name.split('.')[0] in prefixes:
                sys.modules.pop(name,None)
        sys.modules.update(previous)
