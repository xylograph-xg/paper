"""Metadata parser interface; isolates the tool's top-level module names."""
import sys
from pathlib import Path

def load_metadata_parsers():
    original=list(sys.path);prefixes=('connectors','models','config','storage','screening','discovery','ranking')
    previous={name:module for name,module in list(sys.modules.items()) if name.split('.')[0] in prefixes}
    for name in previous:sys.modules.pop(name,None)
    before=set(sys.modules)
    try:
        sys.path.insert(0,str(Path(__file__).resolve().parent/'literature_explorer'))
        from connectors.openalex import parse_work
        from connectors.semantic_scholar import parse_paper
        return parse_work,parse_paper
    finally:
        sys.path[:]=original
        for name in set(sys.modules)-before:
            if name.split('.')[0] in prefixes:
                sys.modules.pop(name,None)
        sys.modules.update(previous)
