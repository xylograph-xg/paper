"""Compatibility exports; authoritative evidence preparation lives in read/app."""
from read.api import evidence_preparation; globals().update({k:getattr(evidence_preparation,k) for k in getattr(evidence_preparation,'__all__',[x for x in dir(evidence_preparation) if not x.startswith('_')])})
