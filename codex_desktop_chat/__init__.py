"""Compatibility entry for callers that only add paper to the import path."""
from importlib.util import spec_from_file_location
from pathlib import Path
import sys

_source = Path(__file__).resolve().parents[2] / "tools" / "codex_desktop_chat" / __name__
_spec = spec_from_file_location(__name__, _source / "__init__.py",
                               submodule_search_locations=[str(_source)])
_module = sys.modules[__name__]
_module.__spec__ = _spec
_module.__loader__ = _spec.loader
_module.__file__ = _spec.origin
_module.__path__ = _spec.submodule_search_locations
_spec.loader.exec_module(_module)
