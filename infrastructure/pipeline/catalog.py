"""Runtime adapter; canonical implementation: core.catalog."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.catalog',run_name='__main__')
else:
    from ._compat import bind
    bind('catalog')
