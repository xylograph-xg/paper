"""Workspace paths and a public compatibility resolver for unchanged receipts.

The old root prefixes are interpreted at file-access boundaries. Frozen JSON,
SQLite rows, prompts, hashes and original response bytes are never rewritten.
"""
import json
import os
import sys
from pathlib import Path as NativePath

def _host():
    value=os.environ.get('PAPER_WORKSPACE_ROOT')
    if value:
        root=NativePath(value).expanduser().resolve()
        if not root.is_dir():raise ValueError('PAPER_WORKSPACE_ROOT 不存在')
        return root
    for root in NativePath(__file__).resolve().parents:
        if (root/'workspace.json').is_file():return root
    return NativePath(__file__).resolve().parents[2]

_ROOT=_host()
_MANIFEST=json.loads((_ROOT/'workspace.json').read_text())
_ALIASES=_MANIFEST.get('physical_roots',{})
_ORIGINAL=NativePath('/Users/xiaoyanhao/project/paper')

_PREFIX_PARTS=tuple(dict.fromkeys((_ROOT.parts,_ORIGINAL.parts)))

def _relocate(value):
    path=NativePath(value)
    parts=path.parts
    # Do not enumerate parents: pathlib preserves the subclass while deriving
    # parents, which would repeatedly invoke this adapter for every ancestor.
    for prefix in _PREFIX_PARTS:
        offset=len(prefix)
        if len(parts)>offset and parts[:offset]==prefix:
            destination=_ALIASES.get(parts[offset])
            if destination is not None:return _ROOT/destination/NativePath(*parts[offset+1:])
    return path

class WorkspacePath(type(NativePath())):
    """Path-compatible reader for current paths and immutable old absolute paths."""
    def __new__(cls,*args):
        return super().__new__(cls,_relocate(NativePath(*args)))
    def __init__(self,*args):
        if sys.version_info >= (3,12):super().__init__(_relocate(NativePath(*args)))
    def __truediv__(self,key):
        return type(self)(NativePath(self)/key)
    def joinpath(self,*args):
        return type(self)(NativePath(self).joinpath(*args))

def workspace_root():
    return WorkspacePath(_ROOT)

def resolve_runtime_path(value):
    return WorkspacePath(value)
