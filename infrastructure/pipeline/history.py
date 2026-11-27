"""Runtime adapter; canonical implementation: maintenance.history."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.history',run_name='__main__')
else:
    from ._compat import bind
    bind('history')
