"""Runtime adapter; canonical implementation: fetch.fetch_service."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.fetch_service',run_name='__main__')
else:
    from ._compat import bind
    bind('fetch_service')
