"""Runtime adapter; canonical implementation: browser.browser_inventory."""
_paper_adapter=True
if __name__=='__main__':
    from runpy import run_module
    run_module('browser.browser_inventory',run_name='__main__')
else:
    from ._compat import bind
    bind('browser_inventory')
