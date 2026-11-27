"""Runtime adapter; canonical implementation: maintenance.migration."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.migration',run_name='__main__')
else:
    from ._compat import bind
    bind('migration')
