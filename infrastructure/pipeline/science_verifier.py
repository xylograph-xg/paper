"""Runtime adapter; canonical implementation: reading.science_verifier."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.science_verifier',run_name='__main__')
else:
    from ._compat import bind
    bind('science_verifier')
