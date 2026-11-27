"""Runtime adapter; canonical implementation: core.model_schedule."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.model_schedule',run_name='__main__')
else:
    from ._compat import bind
    bind('model_schedule')
