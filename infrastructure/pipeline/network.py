"""Runtime adapter; canonical implementation: fetch.network."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.network',run_name='__main__')
else:
    from ._compat import bind
    bind('network')
