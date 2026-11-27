"""Existing-entry compatibility interface; new callers use canonical project APIs."""
from ._compat import bind
def resolve_legacy_module(name):return bind(name)
