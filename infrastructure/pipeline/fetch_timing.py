"""Runtime adapter; canonical implementation: fetch.fetch_timing."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.fetch_timing',run_name='__main__')
else:
    from ._compat import bind
    bind('fetch_timing')
