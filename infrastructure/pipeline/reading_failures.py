"""Runtime adapter; canonical implementation: reading.reading_failures."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('reading.reading_failures',run_name='__main__')
else:
    from ._compat import bind
    bind('reading_failures')
