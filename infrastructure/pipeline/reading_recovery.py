"""Runtime adapter; canonical implementation: reading.reading_recovery."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.reading_recovery',run_name='__main__')
else:
    from ._compat import bind
    bind('reading_recovery')
