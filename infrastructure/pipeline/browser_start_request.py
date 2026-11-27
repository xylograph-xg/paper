"""Runtime adapter; canonical implementation: browser.browser_start_request."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.browser_start_request',run_name='__main__')
else:
    from ._compat import bind
    bind('browser_start_request')
