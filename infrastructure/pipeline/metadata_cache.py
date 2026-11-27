"""Runtime adapter; canonical implementation: fetch.metadata_cache."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('fetch.metadata_cache',run_name='__main__')
else:
    from ._compat import bind
    bind('metadata_cache')
