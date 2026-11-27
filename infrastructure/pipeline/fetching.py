"""Runtime adapter; canonical implementation: fetch.fetching."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.fetching',run_name='__main__')
else:
    from ._compat import bind
    bind('fetching')
