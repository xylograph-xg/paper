"""Runtime adapter; canonical implementation: core.continuous_start."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.continuous_start',run_name='__main__')
else:
    from ._compat import bind
    bind('continuous_start')
