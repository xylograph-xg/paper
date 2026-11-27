"""Runtime adapter; canonical implementation: maintenance.maintenance_audit."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('maintenance.maintenance_audit',run_name='__main__')
else:
    from ._compat import bind
    bind('maintenance_audit')
