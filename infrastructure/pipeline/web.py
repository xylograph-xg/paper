"""Runtime adapter; canonical implementation: workbench.web."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('workbench.web',run_name='__main__')
else:
    from ._compat import bind
    bind('web')
