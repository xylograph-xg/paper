"""Runtime adapter; canonical implementation: browser.stall_timeouts."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.stall_timeouts',run_name='__main__')
else:
    from ._compat import bind
    bind('stall_timeouts')
