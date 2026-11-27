"""Runtime adapter; canonical implementation: reading.evidence_repair."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.evidence_repair',run_name='__main__')
else:
    from ._compat import bind
    bind('evidence_repair')
