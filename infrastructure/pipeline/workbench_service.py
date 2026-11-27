"""Runtime adapter; canonical implementation: workbench.workbench_service."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('workbench.workbench_service',run_name='__main__')
else:
    from ._compat import bind
    bind('workbench_service')
