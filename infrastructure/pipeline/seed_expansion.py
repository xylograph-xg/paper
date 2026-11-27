"""Runtime adapter; canonical implementation: fetch.seed_expansion."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.seed_expansion',run_name='__main__')
else:
    from ._compat import bind
    bind('seed_expansion')
