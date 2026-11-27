"""Runtime adapter; canonical implementation: core.concurrency_control."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('core.concurrency_control',run_name='__main__')
else:
    from ._compat import bind
    bind('concurrency_control')
