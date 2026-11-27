"""Runtime adapter; canonical implementation: fetch.fetch_wait_recovery."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.fetch_wait_recovery',run_name='__main__')
else:
    from ._compat import bind
    bind('fetch_wait_recovery')
