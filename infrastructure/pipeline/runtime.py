"""Runtime adapter; canonical implementation: core.runtime."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.runtime',run_name='__main__')
else:
    from ._compat import bind
    bind('runtime')
