"""Runtime adapter; canonical implementation: core.storage_health."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.storage_health',run_name='__main__')
else:
    from ._compat import bind
    bind('storage_health')
