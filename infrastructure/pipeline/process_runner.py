"""Runtime adapter; canonical implementation: core.process_runner."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.process_runner',run_name='__main__')
else:
    from ._compat import bind
    bind('process_runner')
